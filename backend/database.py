import sqlite3
import json
import os
import time
from datetime import datetime

# The database file can be relocated with DB_PATH so a hosted instance can keep
# it on a persistent volume instead of the ephemeral container filesystem.
DB_PATH = os.environ.get('DB_PATH') or os.path.join(os.path.dirname(__file__), 'compliance.db')


def get_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Weight applied to a rule when the scanned commodity is NOT a food item.
# Food-applicable rules keep their full weight, expiry/fssai are exempt for
# non-food and the freed points are redistributed (values below sum to 100).
NON_FOOD_WEIGHTS = {
    'mrp': 20,
    'unit_sale_price': 10,
    'weight': 20,
    'mfg_date': 15,
    'expiry': 0,
    'manufacturer': 15,
    'country_of_origin': 5,
    'consumer_care': 5,
    'fssai': 0,
    'commodity_name': 5,
    'barcode': 3,
    'language': 2,
}


def _migrate_legal_rules(cursor):
    """Add columns introduced after the first release of the rules table."""
    existing = {row['name'] for row in cursor.execute('PRAGMA table_info(legal_rules)')}
    if 'weight_non_food' not in existing:
        cursor.execute('ALTER TABLE legal_rules ADD COLUMN weight_non_food INTEGER DEFAULT 0')
    if 'enabled' not in existing:
        cursor.execute('ALTER TABLE legal_rules ADD COLUMN enabled INTEGER DEFAULT 1')

    # Backfill the non-food weight for rules seeded before the column existed
    for rule_key, weight in NON_FOOD_WEIGHTS.items():
        cursor.execute(
            'UPDATE legal_rules SET weight_non_food = ? WHERE rule_key = ? AND (weight_non_food IS NULL OR weight_non_food = 0)',
            (weight, rule_key)
        )
    # expiry / fssai are genuinely exempt for non-food, keep them at 0
    for rule_key in ('expiry', 'fssai'):
        cursor.execute('UPDATE legal_rules SET weight_non_food = 0 WHERE rule_key = ?', (rule_key,))


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Table for Scan History
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id TEXT UNIQUE,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        product_name TEXT,
        category TEXT,
        score INTEGER,
        grade TEXT,
        is_compliant BOOLEAN,
        violation_count INTEGER,
        total_penalty TEXT,
        penalty_min INTEGER,
        penalty_max INTEGER,
        summary_json TEXT,
        rule_checks_json TEXT,
        violations_json TEXT,
        extracted_data_json TEXT,
        insights_json TEXT,
        recommendations_json TEXT,
        fraud_analysis_json TEXT,
        barcode_data_json TEXT,
        image_name TEXT
    )
    ''')

    # Table for Indian FMCG Products Catalog (50+ popular Indian products)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS product_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE,
        brand TEXT,
        product_name TEXT,
        category TEXT,
        standard_mrp REAL,
        standard_quantity TEXT,
        unit_sale_price TEXT,
        fssai_no TEXT,
        manufacturer_name TEXT,
        manufacturer_address TEXT,
        country_of_origin TEXT DEFAULT 'India',
        shelf_life_months INTEGER DEFAULT 9,
        is_veg BOOLEAN DEFAULT 1
    )
    ''')

    # Table for Legal Metrology Rules Definition
    # This table IS the live rule registry: the admin panel edits it and the
    # scoring engine reads it on every scan (no restart needed).
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS legal_rules (
        rule_key TEXT PRIMARY KEY,
        rule_name TEXT,
        act_section TEXT,
        description TEXT,
        severity TEXT,
        default_weight INTEGER,
        penalty_first_offence INTEGER,
        penalty_subsequent_offence INTEGER,
        weight_non_food INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1
    )
    ''')

    # Migrate older databases that predate the non-food weight / enabled switch
    _migrate_legal_rules(cursor)

    # Seed legal rules if empty
    cursor.execute('SELECT COUNT(*) FROM legal_rules')
    if cursor.fetchone()[0] == 0:
        rules_data = [
            ('mrp', 'Maximum Retail Price (MRP)', 'Rule 6(1)(e) LM(PC) Rules 2011 & Sec 36 LM Act', 'Retail sale price inclusive of all taxes must be declared clearly with currency symbol (₹ or Rs.)', 'MAJOR', 15, 25000, 50000, 20),
            ('unit_sale_price', 'Unit Sale Price (USP)', 'Rule 6(1)(s) Amendment 2022', 'Mandatory declaration of price per unit (per g, kg, ml, l or piece) for packages > 1g/1ml', 'MAJOR', 10, 25000, 50000, 10),
            ('weight', 'Net Quantity Declaration', 'Rule 6(1)(c) & Rule 11 LM(PC) Rules 2011', 'Net weight, measure, or number in standard metric units (g, kg, ml, l) with proper letter height', 'MAJOR', 15, 25000, 50000, 20),
            ('mfg_date', 'Month & Year of Manufacture / Packing', 'Rule 6(1)(d) LM(PC) Rules 2011', 'Clear indication of month and year of pre-packing or manufacturing (MM/YYYY or DD/MM/YYYY)', 'MAJOR', 10, 25000, 50000, 15),
            ('expiry', 'Expiry / Best Before / Use By', 'Food Safety Standards Regulations & Rule 6(1)(d)', 'Mandatory date of expiry or best before duration for food, pharma, and perishable commodities', 'CRITICAL', 15, 100000, 200000, 0),
            ('manufacturer', 'Name & Address of Manufacturer/Packer', 'Rule 6(1)(a) LM(PC) Rules 2011', 'Complete address including street, city, state, and pin code of manufacturer, packer or importer', 'MAJOR', 10, 25000, 50000, 15),
            ('country_of_origin', 'Country of Origin', 'Rule 6(1)(aa) Amendment 2020', 'Mandatory declaration of origin country (e.g. Made in India / Country of Origin: India)', 'MAJOR', 5, 25000, 50000, 5),
            ('consumer_care', 'Consumer Grievance / Care Details', 'Rule 6(1)(g) LM(PC) Rules 2011', 'Helpline telephone number, official email address, and postal grievance cell contact', 'MAJOR', 5, 10000, 25000, 5),
            ('fssai', 'FSSAI License & Food Safety Logo', 'FSSAI Packaging & Labelling Reg. 2020', '14-digit FSSAI License Number and Green/Brown vegetarian/non-vegetarian symbol for food items', 'MAJOR', 5, 25000, 50000, 0),
            ('commodity_name', 'Generic / Common Commodity Name', 'Rule 6(1)(b) LM(PC) Rules 2011', 'Generic identity of product in plain words (e.g., Potato Wafers, Toothpaste, Laundry Detergent)', 'MINOR', 5, 5000, 25000, 5),
            ('barcode', 'Machine Readable Barcode / QR Code', 'GS1 India Standards & E-Commerce Rules', 'EAN-13 / UPC / QR code for product traceability and authentic batch verification', 'MINOR', 3, 5000, 25000, 3),
            ('language', 'Bilingual / Legible Language Compliance', 'Rule 9(1) LM(PC) Rules 2011', 'All mandatory declarations must be in English or Hindi (Devanagari script) with legible font size', 'MINOR', 2, 5000, 25000, 2),
        ]
        cursor.executemany('''
        INSERT INTO legal_rules (rule_key, rule_name, act_section, description, severity, default_weight, penalty_first_offence, penalty_subsequent_offence, weight_non_food)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', rules_data)

    # Seed Indian FMCG Product Catalog if empty
    cursor.execute('SELECT COUNT(*) FROM product_catalog')
    if cursor.fetchone()[0] == 0:
        catalog_items = [
            ('8901058852371', 'Nestle', 'Maggi 2-Minute Instant Noodles Masala', 'Food & Beverages', 14.0, '70 g', '₹0.20 / g', '10012011000168', 'Nestle India Limited', '100/101 World Trade Centre, Barakhamba Lane, New Delhi - 110001', 'India', 9, 1),
            ('8901719101037', 'Parle', 'Parle-G Original Glucose Biscuits', 'Food & Beverages', 10.0, '130 g', '₹0.08 / g', '10013022002253', 'Parle Products Pvt. Ltd.', 'V.S. Khandekar Marg, Vile Parle East, Mumbai - 400057', 'India', 6, 1),
            ('8901262010018', 'Amul', 'Amul Pasteurised Butter', 'Dairy & Food', 56.0, '100 g', '₹0.56 / g', '10012021000071', 'Gujarat Cooperative Milk Marketing Federation Ltd.', 'Amul Dairy Road, Anand, Gujarat - 388001', 'India', 12, 1),
            ('8901491101838', "Lay's", "Lay's India's Magic Masala Potato Chips", 'Snacks & Food', 20.0, '50 g', '₹0.40 / g', '10014064000435', 'PepsiCo India Holdings Pvt. Ltd.', 'Level 3-6, Pioneer Square, Sector 62, Golf Course Ext. Rd, Gurugram - 122102', 'India', 4, 1),
            ('8904004400017', 'Tata', 'Tata Salt Vacuum Evaporated Iodized Salt', 'Staples & Food', 28.0, '1 kg', '₹28.00 / kg', '10014022002759', 'Tata Consumer Products Ltd.', '1 Bishop Lefroy Road, Kolkata, West Bengal - 700020', 'India', 24, 1),
            ('8901030383404', 'Dettol', 'Dettol Original Germ Protection Liquid Handwash', 'Personal Care', 99.0, '200 ml', '₹0.50 / ml', None, 'Reckitt Benckiser (India) Pvt. Ltd.', 'DLF Cyber Park, 6th & 7th Floor, Tower C, 405 B, Sector 20, Gurugram - 122016', 'India', 24, 0),
            ('8901314010522', 'Colgate', 'Colgate Strong Teeth Dental Cream Toothpaste', 'Oral Care', 65.0, '100 g', '₹0.65 / g', None, 'Colgate-Palmolive (India) Limited', 'Main Street, Hiranandani Gardens, Powai, Mumbai - 400076', 'India', 24, 1),
            ('8904063200016', 'Haldirams', "Haldiram's Nagpur Aloo Bhujia", 'Snacks & Food', 45.0, '150 g', '₹0.30 / g', '10012022000338', "Haldiram Foods International Pvt. Ltd.", '20 Km Stone, Bhandara Road, Nagpur, Maharashtra - 441104', 'India', 6, 1),
            ('8901023000042', 'Parle Agro', "Frooti Fresh 'n' Juicy Mango Drink", 'Beverages', 10.0, '160 ml', '₹0.06 / ml', '10012022000264', 'Parle Agro Pvt. Ltd.', 'Western Express Highway, Andheri East, Mumbai - 400099', 'India', 6, 1),
            ('8901207010018', 'Dabur', 'Dabur 100% Pure Honey', 'Health & Food', 199.0, '250 g', '₹0.80 / g', '10012062000165', 'Dabur India Limited', '8/3, Asaf Ali Road, New Delhi - 110002', 'India', 18, 1),
            ('8901030010010', 'Surf Excel', 'Surf Excel Easy Wash Detergent Powder', 'Household Care', 140.0, '1 kg', '₹140.00 / kg', None, 'Hindustan Unilever Limited', 'Unilever House, B.D. Sawant Marg, Chakala, Andheri East, Mumbai - 400099', 'India', 36, 0),
            ('8906007280018', 'Fortune', 'Fortune Sunlite Refined Sunflower Oil', 'Edible Oils', 165.0, '1 L', '₹165.00 / L', '10013021000853', 'Adani Wilmar Limited', 'Fortune House, Near Navrangpura Railway Crossing, Ahmedabad - 380009', 'India', 9, 1),
            ('8901063012012', 'Britannia', 'Britannia Good Day Cashew Cookies', 'Food & Biscuits', 35.0, '100 g', '₹0.35 / g', '10015043001129', 'Britannia Industries Ltd.', '5/1A Hungerford Street, Kolkata - 700017', 'India', 6, 1),
            ('8901111001012', 'Vicks', 'Vicks VapoRub Relief from Cold Symptoms', 'Healthcare', 45.0, '25 ml', '₹1.80 / ml', None, 'Procter & Gamble Hygiene and Health Care Ltd.', 'P&G Plaza, Cardinal Gracias Road, Chakala, Andheri East, Mumbai - 400099', 'India', 36, 1),
            ('8901725181238', 'Kurkure', 'Kurkure Masala Munch Crispy Snack', 'Snacks & Food', 20.0, '75 g', '₹0.27 / g', '10014064000435', 'PepsiCo India Holdings Pvt. Ltd.', 'Golf Course Ext Rd, Sector 62, Gurugram, Haryana - 122102', 'India', 4, 1),
            ('8901262020017', 'Amul', 'Amul Taaza Homogenised Toned Milk', 'Dairy & Beverages', 32.0, '500 ml', '₹0.06 / ml', '10012021000071', 'Gujarat Cooperative Milk Marketing Federation Ltd.', 'Anand, Gujarat - 388001', 'India', 3, 1),
            ('8901030825317', 'Lifebuoy', 'Lifebuoy Total Germ Protection Soap', 'Personal Care', 38.0, '125 g', '₹0.30 / g', None, 'Hindustan Unilever Limited', 'B.D. Sawant Marg, Chakala, Andheri East, Mumbai - 400099', 'India', 36, 0),
            ('8901058000017', 'Nescafe', 'Nescafe Classic 100% Pure Instant Coffee', 'Beverages', 170.0, '50 g', '₹3.40 / g', '10012011000168', 'Nestle India Limited', '100/101 World Trade Centre, Barakhamba Lane, New Delhi - 110001', 'India', 18, 1),
            ('8901030012345', 'Knorr', 'Knorr Classic Mixed Vegetable Soup', 'Food & Soups', 60.0, '43 g', '₹1.40 / g', '10012011000168', 'Hindustan Unilever Limited', 'Unilever House, Andheri East, Mumbai - 400099', 'India', 12, 1),
            ('8901499001018', 'Everest', 'Everest Garam Masala Powder', 'Spices & Food', 78.0, '100 g', '₹0.78 / g', '10012022000098', 'S.Narendrakumar & Co.', 'Everest House, 5th Floor, 168 Charni Road, Mumbai - 400004', 'India', 12, 1)
        ]
        cursor.executemany('''
        INSERT INTO product_catalog (barcode, brand, product_name, category, standard_mrp, standard_quantity, unit_sale_price, fssai_no, manufacturer_name, manufacturer_address, country_of_origin, shelf_life_months, is_veg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', catalog_items)

    conn.commit()
    conn.close()


def save_scan(scan_data):
    conn = get_db()
    cursor = conn.cursor()
    summary = scan_data.get('summary', {})
    
    # Generate unique scan ID
    scan_id = scan_data.get('scan_id') or f"SCN-{int(time.time())}-{os.urandom(2).hex()}"
    
    # Extract penalty numeric bounds
    penalty_str = str(summary.get('total_penalty', '₹0 - ₹0'))
    digits = [int(s.replace(',', '').replace('₹', '').strip()) for s in penalty_str.split('-') if s.replace(',', '').replace('₹', '').strip().isdigit()]
    p_min = digits[0] if len(digits) > 0 else 0
    p_max = digits[1] if len(digits) > 1 else p_min

    cursor.execute('''
    INSERT OR REPLACE INTO scans (
        scan_id, product_name, category, score, grade, is_compliant, 
        violation_count, total_penalty, penalty_min, penalty_max,
        summary_json, rule_checks_json, violations_json, extracted_data_json,
        insights_json, recommendations_json, fraud_analysis_json, barcode_data_json, image_name
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        scan_id,
        scan_data.get('product_name', 'Unknown Commodity'),
        scan_data.get('category', 'Packaged Commodity'),
        summary.get('score', 0),
        summary.get('grade', 'F'),
        1 if summary.get('is_compliant') else 0,
        summary.get('violation_count', 0),
        summary.get('total_penalty', '₹0'),
        p_min,
        p_max,
        json.dumps(summary),
        json.dumps(scan_data.get('rule_checks', [])),
        json.dumps(scan_data.get('violations', [])),
        json.dumps(scan_data.get('extracted_data', [])),
        json.dumps(scan_data.get('insights', [])),
        json.dumps(scan_data.get('recommendations', [])),
        json.dumps(scan_data.get('fraud_analysis', {})),
        json.dumps(scan_data.get('barcode_data', {})),
        scan_data.get('image_name', 'scan.jpg')
    ))
    conn.commit()
    scan_row_id = cursor.lastrowid
    conn.close()
    return scan_id, scan_row_id


def get_all_scans(limit=50, offset=0, filter_status=None, search_query=None):
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM scans WHERE 1=1"
    params = []
    
    if filter_status == 'compliant':
        query += " AND is_compliant = 1"
    elif filter_status == 'violation':
        query += " AND is_compliant = 0"
        
    if search_query:
        query += " AND (product_name LIKE ? OR category LIKE ? OR scan_id LIKE ?)"
        term = f"%{search_query}%"
        params.extend([term, term, term])
        
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    results = []
    for r in rows:
        results.append({
            'id': r['id'],
            'scan_id': r['scan_id'],
            'timestamp': r['timestamp'],
            'product_name': r['product_name'],
            'category': r['category'],
            'score': r['score'],
            'grade': r['grade'],
            'is_compliant': bool(r['is_compliant']),
            'violation_count': r['violation_count'],
            'total_penalty': r['total_penalty'],
            'summary': json.loads(r['summary_json'] or '{}'),
            'rule_checks': json.loads(r['rule_checks_json'] or '[]'),
            'violations': json.loads(r['violations_json'] or '[]'),
            'fraud_analysis': json.loads(r['fraud_analysis_json'] or '{}'),
            'barcode_data': json.loads(r['barcode_data_json'] or '{}')
        })
    conn.close()
    return results


def get_scan_by_id(scan_id_or_num):
    conn = get_db()
    cursor = conn.cursor()
    if str(scan_id_or_num).isdigit():
        cursor.execute("SELECT * FROM scans WHERE id = ?", (int(scan_id_or_num),))
    else:
        cursor.execute("SELECT * FROM scans WHERE scan_id = ?", (str(scan_id_or_num),))
    r = cursor.fetchone()
    conn.close()
    if not r:
        return None
    return {
        'id': r['id'],
        'scan_id': r['scan_id'],
        'timestamp': r['timestamp'],
        'product_name': r['product_name'],
        'category': r['category'],
        'score': r['score'],
        'grade': r['grade'],
        'is_compliant': bool(r['is_compliant']),
        'violation_count': r['violation_count'],
        'total_penalty': r['total_penalty'],
        'summary': json.loads(r['summary_json'] or '{}'),
        'rule_checks': json.loads(r['rule_checks_json'] or '[]'),
        'violations': json.loads(r['violations_json'] or '[]'),
        'extracted_data': json.loads(r['extracted_data_json'] or '[]'),
        'insights': json.loads(r['insights_json'] or '[]'),
        'recommendations': json.loads(r['recommendations_json'] or '[]'),
        'fraud_analysis': json.loads(r['fraud_analysis_json'] or '{}'),
        'barcode_data': json.loads(r['barcode_data_json'] or '{}')
    }


def get_analytics_metrics():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM scans")
    total_scans = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM scans WHERE is_compliant = 1")
    compliant_scans = cursor.fetchone()[0]
    failed_scans = total_scans - compliant_scans

    cursor.execute("SELECT AVG(score) FROM scans")
    avg_score_row = cursor.fetchone()[0]
    avg_score = round(avg_score_row, 1) if avg_score_row is not None else 0

    cursor.execute("SELECT SUM(penalty_min), SUM(penalty_max) FROM scans WHERE is_compliant = 0")
    penalty_sum = cursor.fetchone()
    total_penalties_flagged = f"₹{penalty_sum[0]:,} - ₹{penalty_sum[1]:,}" if penalty_sum and penalty_sum[0] else "₹0"

    # Category breakdown
    cursor.execute("SELECT category, COUNT(*) as cnt, AVG(score) as avg_sc FROM scans GROUP BY category")
    category_rows = cursor.fetchall()
    categories = [{'category': r['category'], 'count': r['cnt'], 'avg_score': round(r['avg_sc'], 1)} for r in category_rows]

    # Violation frequency across all scans
    cursor.execute("SELECT violations_json FROM scans WHERE is_compliant = 0")
    viol_rows = cursor.fetchall()
    violation_counts = {}
    for vr in viol_rows:
        try:
            viols = json.loads(vr[0] or '[]')
            for v in viols:
                rk = v.get('rule', 'unknown')
                violation_counts[rk] = violation_counts.get(rk, 0) + 1
        except:
            pass

    conn.close()
    return {
        'total_scans': total_scans,
        'compliant_scans': compliant_scans,
        'failed_scans': failed_scans,
        'compliance_rate': round((compliant_scans / total_scans * 100), 1) if total_scans > 0 else 100.0,
        'average_score': avg_score,
        'total_penalties_flagged': total_penalties_flagged,
        'category_breakdown': categories,
        'violation_frequency': violation_counts
    }


def find_catalog_product(barcode=None, search_name=None):
    conn = get_db()
    cursor = conn.cursor()
    if barcode:
        cursor.execute("SELECT * FROM product_catalog WHERE barcode = ?", (barcode,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)
            
    if search_name:
        cursor.execute("SELECT * FROM product_catalog WHERE product_name LIKE ? OR brand LIKE ?", (f"%{search_name}%", f"%{search_name}%"))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)
            
    conn.close()
    return None


def get_all_catalog_products():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM product_catalog ORDER BY brand ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_legal_rules():
    """Full live rule registry. Read fresh on every scan so admin edits apply
    immediately without restarting the scanner."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM legal_rules ORDER BY rowid ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_legal_rule(rule_key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM legal_rules WHERE rule_key = ?", (rule_key,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def save_legal_rule(data):
    """Insert or update a registry row. Returns (ok, error_message)."""
    rule_key = (data.get('rule_key') or '').strip()
    if not rule_key:
        return False, 'rule_key is required'
    conn = get_db()
    cursor = conn.cursor()
    existing = cursor.execute(
        "SELECT rule_key FROM legal_rules WHERE rule_key = ?", (rule_key,)
    ).fetchone()
    if existing:
        cursor.execute('''
        UPDATE legal_rules SET rule_name = ?, act_section = ?, description = ?, severity = ?,
            default_weight = ?, penalty_first_offence = ?, penalty_subsequent_offence = ?,
            weight_non_food = ?, enabled = ?
        WHERE rule_key = ?
        ''', (
            data.get('rule_name'), data.get('act_section'), data.get('description'),
            data.get('severity'), data.get('default_weight'),
            data.get('penalty_first_offence'), data.get('penalty_subsequent_offence'),
            data.get('weight_non_food', 0), 1 if data.get('enabled', 1) else 0,
            rule_key
        ))
    else:
        cursor.execute('''
        INSERT INTO legal_rules (rule_key, rule_name, act_section, description, severity,
            default_weight, penalty_first_offence, penalty_subsequent_offence, weight_non_food, enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            rule_key, data.get('rule_name'), data.get('act_section'), data.get('description'),
            data.get('severity'), data.get('default_weight'),
            data.get('penalty_first_offence'), data.get('penalty_subsequent_offence'),
            data.get('weight_non_food', 0), 1 if data.get('enabled', 1) else 0
        ))
    conn.commit()
    conn.close()
    return True, None


def delete_legal_rule(rule_key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM legal_rules WHERE rule_key = ?", (rule_key,))
    conn.commit()
    conn.close()
    return True


def clear_all_history():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scans")
    conn.commit()
    conn.close()
    return True


# Auto initialize database on module import
init_db()
