"""Live Legal Metrology rule registry.

The `legal_rules` table is the authoritative registry. The admin panel edits it,
this module reads it, and the scorer/engine consume it on every scan -- so a
change made in the admin panel is visible on the next scan with no restart.

Anything the admin adds that has no automated check behind it is still listed
(flagged `implemented: False`) so the operator can see it is registered but not
machine-evaluated.
"""
from database import get_legal_rules


# Statutory penalty bands (Section 36 & 38, Legal Metrology Act 2009).
# The DB can override both numbers per rule.
DEFAULT_PENALTIES = {
    'mrp': {'min': 25000, 'max': 50000},
    'unit_sale_price': {'min': 25000, 'max': 50000},
    'weight': {'min': 25000, 'max': 50000},
    'mfg_date': {'min': 25000, 'max': 50000},
    'expiry': {'min': 50000, 'max': 200000},
    'manufacturer': {'min': 25000, 'max': 50000},
    'country_of_origin': {'min': 25000, 'max': 50000},
    'consumer_care': {'min': 10000, 'max': 25000},
    'fssai': {'min': 25000, 'max': 100000},
    'commodity_name': {'min': 5000, 'max': 25000},
    'barcode': {'min': 5000, 'max': 25000},
    'language': {'min': 5000, 'max': 25000},
}

# The 12 checks the engine can actually evaluate, with their built-in metadata.
# Used as a fallback when the DB row is missing or incomplete.
BUILTIN_RULES = {
    'mrp': {
        'name': 'Maximum Retail Price (MRP)',
        'act_section': 'Rule 6(1)(e) LM(PC) Rules 2011 & Sec 36 LM Act',
        'severity': 'MAJOR',
        'weight': 15,
        'weight_non_food': 20,
    },
    'unit_sale_price': {
        'name': 'Unit Sale Price (USP)',
        'act_section': 'Rule 6(1)(s) Amendment 2022',
        'severity': 'MAJOR',
        'weight': 10,
        'weight_non_food': 10,
    },
    'weight': {
        'name': 'Net Quantity Declaration',
        'act_section': 'Rule 6(1)(c) & Rule 11 LM(PC) Rules 2011',
        'severity': 'MAJOR',
        'weight': 15,
        'weight_non_food': 20,
    },
    'mfg_date': {
        'name': 'Month & Year of Manufacture / Packing',
        'act_section': 'Rule 6(1)(d) LM(PC) Rules 2011',
        'severity': 'MAJOR',
        'weight': 10,
        'weight_non_food': 15,
    },
    'expiry': {
        'name': 'Expiry / Best Before / Use By',
        'act_section': 'FSSAI FSSR 2020 & Rule 6(1)(d)',
        'severity': 'CRITICAL',
        'weight': 15,
        'weight_non_food': 0,
    },
    'manufacturer': {
        'name': 'Name & Address of Manufacturer/Packer',
        'act_section': 'Rule 6(1)(a) LM(PC) Rules 2011',
        'severity': 'MAJOR',
        'weight': 10,
        'weight_non_food': 15,
    },
    'country_of_origin': {
        'name': 'Country of Origin',
        'act_section': 'Rule 6(1)(aa) Amendment 2020',
        'severity': 'MAJOR',
        'weight': 5,
        'weight_non_food': 5,
    },
    'consumer_care': {
        'name': 'Consumer Grievance / Care Details',
        'act_section': 'Rule 6(1)(g) LM(PC) Rules 2011',
        'severity': 'MAJOR',
        'weight': 5,
        'weight_non_food': 5,
    },
    'fssai': {
        'name': 'FSSAI License & Food Safety Logo',
        'act_section': 'FSSAI Packaging & Labelling Reg. 2020',
        'severity': 'MAJOR',
        'weight': 5,
        'weight_non_food': 0,
    },
    'commodity_name': {
        'name': 'Generic / Common Commodity Name',
        'act_section': 'Rule 6(1)(b) LM(PC) Rules 2011',
        'severity': 'MINOR',
        'weight': 5,
        'weight_non_food': 5,
    },
    'barcode': {
        'name': 'Machine Readable Barcode / QR Code',
        'act_section': 'GS1 India Standards & E-Commerce Rules',
        'severity': 'MINOR',
        'weight': 3,
        'weight_non_food': 3,
    },
    'language': {
        'name': 'Bilingual / Legible Language Compliance',
        'act_section': 'Rule 9(1) LM(PC) Rules 2011',
        'severity': 'MINOR',
        'weight': 2,
        'weight_non_food': 2,
    },
}

SEVERITY_ORDER = {'CRITICAL': 0, 'MAJOR': 1, 'MINOR': 2}


def _coerce_int(value, fallback):
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def build_registry(db_rows=None):
    """Merge the DB registry over the built-in defaults.

    Returns an ordered list of rule configs. Each entry carries both the
    scoring inputs (weight / penalties / severity) and the display metadata.
    """
    if db_rows is None:
        db_rows = get_legal_rules()

    by_key = {row['rule_key']: row for row in db_rows if row.get('rule_key')}
    registry = {}

    for key, builtin in BUILTIN_RULES.items():
        row = by_key.get(key, {})
        penalties = DEFAULT_PENALTIES.get(key, {'min': 5000, 'max': 25000})
        registry[key] = {
            'rule_key': key,
            'rule_name': row.get('rule_name') or builtin['name'],
            'act_section': row.get('act_section') or builtin['act_section'],
            'description': row.get('description') or '',
            'severity': (row.get('severity') or builtin['severity']).upper(),
            'weight': _coerce_int(row.get('default_weight'), builtin['weight']),
            'weight_non_food': _coerce_int(row.get('weight_non_food'), builtin['weight_non_food']),
            'penalty_min': _coerce_int(row.get('penalty_first_offence'), penalties['min']),
            'penalty_max': _coerce_int(row.get('penalty_subsequent_offence'), penalties['max']),
            'enabled': 1 if row.get('enabled', 1) in (1, True, '1') else 0,
            'implemented': True,
            'source': 'db' if row else 'builtin',
        }

    # Registry rows added by the operator with no automated check behind them
    for key, row in by_key.items():
        if key in registry:
            continue
        registry[key] = {
            'rule_key': key,
            'rule_name': row.get('rule_name') or key,
            'act_section': row.get('act_section') or 'LM(PC) Rules 2011',
            'description': row.get('description') or '',
            'severity': (row.get('severity') or 'MINOR').upper(),
            'weight': _coerce_int(row.get('default_weight'), 0),
            'weight_non_food': _coerce_int(row.get('weight_non_food'), 0),
            'penalty_min': _coerce_int(row.get('penalty_first_offence'), 5000),
            'penalty_max': _coerce_int(row.get('penalty_subsequent_offence'), 25000),
            'enabled': 1 if row.get('enabled', 1) in (1, True, '1') else 0,
            'implemented': False,
            'source': 'db',
        }

    return sorted(
        registry.values(),
        key=lambda r: (SEVERITY_ORDER.get(r['severity'], 3), -r['weight'], r['rule_key'])
    )


def get_registry():
    """Live registry straight from the DB (fresh read on every call)."""
    return build_registry(get_legal_rules())


def get_scoring_rules(registry=None, is_food=True):
    """Registry entries that take part in scoring for this commodity category.

    Rules switched off in the admin panel, and rules without an automated
    check, are excluded from the score.
    """
    if registry is None:
        registry = get_registry()
    scoring = {}
    for rule in registry:
        if not rule['implemented'] or not rule['enabled']:
            continue
        weight = rule['weight'] if is_food else rule['weight_non_food']
        if weight <= 0:
            continue
        scoring[rule['rule_key']] = weight
    return scoring


def registry_summary(registry=None):
    """Compact view used by the main page and the portfolio telemetry."""
    if registry is None:
        registry = get_registry()
    active = [r for r in registry if r['enabled'] and r['implemented']]
    return {
        'total': len(registry),
        'active': len(active),
        'disabled': len(registry) - len(active),
        'critical': len([r for r in active if r['severity'] == 'CRITICAL']),
        'major': len([r for r in active if r['severity'] == 'MAJOR']),
        'minor': len([r for r in active if r['severity'] == 'MINOR']),
        'food_weight_total': sum(r['weight'] for r in active),
        'non_food_weight_total': sum(r['weight_non_food'] for r in active),
        'rules': registry,
    }
