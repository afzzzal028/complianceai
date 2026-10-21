import rule_registry


class ComplianceScorer:
    """
    Calibrated Scoring & Legal Metrology Act Section 36/38 Penalty Calculator.

    Every weight, penalty band, severity and display name comes from the live
    rule registry (the `legal_rules` table), so edits made in the admin panel
    change the score of the very next scan. The built-in values are only used
    as a fallback when a registry row is missing.
    """
    def __init__(self, registry=None):
        self.registry = registry

    def _registry(self, registry=None):
        """Registry to score against: explicit > instance > fresh DB read."""
        reg = registry if registry is not None else self.registry
        return reg if reg is not None else rule_registry.get_registry()

    def get_rule_weights(self, is_food, registry=None):
        """Active weights for the commodity category (food vs non-food)."""
        return rule_registry.get_scoring_rules(self._registry(registry), is_food)

    def _rule(self, rule_key, registry=None):
        rules = {r['rule_key']: r for r in self._registry(registry)}
        return rules.get(rule_key, {})

    def calculate_score(self, check_results, is_food, registry=None):
        weights = self.get_rule_weights(is_food, registry)
        total_score = 0
        violations = []
        advisories = []

        for rule_key, weight in weights.items():
            if weight == 0:
                continue  # Exempt rule for this category

            rule = self._rule(rule_key, registry)
            rule_name = rule.get('rule_name', rule_key)
            act_section = rule.get('act_section', 'LM(PC) Rules 2011')
            severity = rule.get('severity', 'MINOR')
            penalty_min = rule.get('penalty_min', 5000)
            penalty_max = rule.get('penalty_max', 25000)

            if rule_key in check_results:
                passed, details = check_results[rule_key]
                details = details or {}

                if passed:
                    # Check for partial score / advisory deductions
                    if rule_key == 'mrp' and not details.get('inclusive_of_taxes', True):
                        # Passed amount, but missing 'incl of all taxes' phrase
                        awarded = int(weight * 0.85)
                        total_score += awarded
                        advisories.append({
                            'rule': rule_key,
                            'rule_name': rule_name,
                            'note': 'MRP is present, but mandatory phrase "(incl. of all taxes)" was not found.'
                        })
                    elif rule_key == 'weight' and not details.get('is_si_compliant', True):
                        # Non-standard unit like 'gm' instead of 'g'
                        awarded = int(weight * 0.90)
                        total_score += awarded
                        advisories.append({
                            'rule': rule_key,
                            'rule_name': rule_name,
                            'note': details.get('unit_note', 'Use standard SI symbol')
                        })
                    else:
                        total_score += weight
                else:
                    # Failed rule -> Violation
                    violations.append({
                        'rule': rule_key,
                        'rule_name': rule_name,
                        'severity': severity,
                        'weight_lost': weight,
                        'act_section': act_section,
                        'penalty_range': f"₹{penalty_min:,} - ₹{penalty_max:,}",
                        'penalty_min': penalty_min,
                        'penalty_max': penalty_max,
                        'details': details
                    })

        total_score = max(0, min(100, total_score))
        grade = self.get_grade(total_score)
        is_compliant = total_score >= 75 and not any(v['severity'] == 'CRITICAL' for v in violations)

        total_min_pen = sum(v['penalty_min'] for v in violations)
        total_max_pen = sum(v['penalty_max'] for v in violations)
        total_penalty_str = f"₹{total_min_pen:,} - ₹{total_max_pen:,}" if violations else "₹0"

        return {
            'score': total_score,
            'max_score': 100,
            'grade': grade,
            'is_compliant': is_compliant,
            'violations': violations,
            'advisories': advisories,
            'violation_count': len(violations),
            'total_penalty': total_penalty_str,
            'penalty_min': total_min_pen,
            'penalty_max': total_max_pen
        }

    def get_grade(self, score):
        if score >= 90:
            return 'A+'
        elif score >= 80:
            return 'A'
        elif score >= 70:
            return 'B'
        elif score >= 60:
            return 'C'
        elif score >= 50:
            return 'D'
        else:
            return 'F'

    def generate_recommendations(self, score_result, category_name):
        recs = []
        violations = score_result.get('violations', [])
        advisories = score_result.get('advisories', [])

        if score_result['is_compliant'] and not violations:
            recs.append("Package fully complies with Legal Metrology (Packaged Commodities) Rules, 2011.")
            recs.append("Approved for unrestricted commercial distribution in India.")
            return recs

        # Critical Violations first
        for v in violations:
            rname = v['rule_name']
            sec = v['act_section']
            if v['severity'] == 'CRITICAL':
                recs.append(f"URGENT STATUTORY ACTION: Print legible {rname} immediately. Mandatory under {sec} to avoid product recall.")
            elif v['severity'] == 'MAJOR':
                recs.append(f"MANDATORY CORRECTION: {rname} missing or invalid ({sec}). Exposure to compounding fine {v['penalty_range']}.")
            else:
                recs.append(f"COMPLIANCE IMPROVEMENT: Update packaging label to include clear {rname}.")

        for adv in advisories:
            recs.append(f"LABEL ADVISORY: {adv['note']}")

        return recs

    def generate_report(self, check_results, extracted_data, category_name, is_food,
                        barcode_info=None, fraud_analysis=None, registry=None):
        registry = self._registry(registry)
        rules_by_key = {r['rule_key']: r for r in registry}

        score_result = self.calculate_score(check_results, is_food, registry)

        # Build rule check list
        rule_checks_list = []
        weights = self.get_rule_weights(is_food, registry)

        for rule_key, weight in weights.items():
            if weight == 0:
                continue
            passed, details = check_results.get(rule_key, (False, {}))
            rule = rules_by_key.get(rule_key, {})
            rule_checks_list.append({
                'rule': rule_key,
                'rule_name': rule.get('rule_name', rule_key),
                'passed': passed,
                'weight': weight,
                'severity': rule.get('severity', 'MINOR'),
                'act_section': rule.get('act_section', 'LM(PC) Rules 2011'),
                'details': details
            })

        recs = self.generate_recommendations(score_result, category_name)

        return {
            'summary': {
                'score': score_result['score'],
                'grade': score_result['grade'],
                'is_compliant': score_result['is_compliant'],
                'violation_count': score_result['violation_count'],
                'total_penalty': score_result['total_penalty'],
                'penalty_min': score_result['penalty_min'],
                'penalty_max': score_result['penalty_max'],
                'commodity_category': category_name,
                'is_food_product': is_food
            },
            'extracted_data': [{'text': d['text'], 'confidence': d.get('confidence', 0.9)} for d in extracted_data],
            'rule_checks': rule_checks_list,
            'violations': score_result['violations'],
            'advisories': score_result['advisories'],
            'recommendations': recs,
            'barcode_data': barcode_info or {},
            'fraud_analysis': fraud_analysis or {}
        }
