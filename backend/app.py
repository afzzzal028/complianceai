import os
import time
import json
import cv2
import traceback
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import database
from ocr_engine import ProductOCR
from barcode_engine import BarcodeRadar
from rule_engine import RuleEngine
from scorer import ComplianceScorer
from intelligence_engine import IntelligenceEngine
from pdf_report import generate_compliance_pdf
import rule_registry

app = Flask(__name__, template_folder='templates', static_folder='templates')
CORS(app, resources={r'/api/*': config.cors_config()})

if config.TRUST_PROXY:
    # behind nginx / Render / Railway so request.remote_addr is the real client
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Initialize engines
ocr = ProductOCR()
barcode_radar = BarcodeRadar()
rule_engine = RuleEngine()
scorer = ComplianceScorer()
intel_engine = IntelligenceEngine()

UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(os.path.dirname(__file__), 'uploads')
REPORTS_FOLDER = os.environ.get('REPORTS_FOLDER') or os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORTS_FOLDER, exist_ok=True)

# ==================== Rate Limiting Middleware ====================
RATE_LIMIT_BUCKET = {}
MAX_REQUESTS_PER_MINUTE = 60

def rate_limit(max_per_minute=60):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr or '127.0.0.1'
            now = time.time()
            requests_list = RATE_LIMIT_BUCKET.get(ip, [])
            
            # Purge requests older than 60 seconds
            requests_list = [t for t in requests_list if now - t < 60]
            if len(requests_list) >= max_per_minute:
                return jsonify({
                    'error': 'API rate limit exceeded. Please wait a moment before scanning again.',
                    'retry_after_seconds': int(60 - (now - requests_list[0]))
                }), 429

            requests_list.append(now)
            RATE_LIMIT_BUCKET[ip] = requests_list
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ==================== Routes ====================
@app.route('/')
def index():
    return render_template(
        'index.html',
        scanner_url=config.PUBLIC_API_URL or '/',
        admin_url=config.PUBLIC_ADMIN_URL or 'http://localhost:5001/admin',
        portfolio_url=config.PORTFOLIO_URL or 'http://localhost:5500/index.html',
    )


@app.route('/sw.js')
def service_worker():
    return send_from_directory('templates', 'sw.js', mimetype='application/javascript')


@app.route('/manifest.json')
def manifest():
    return send_from_directory('templates', 'manifest.json', mimetype='application/json')


@app.route('/api/health', methods=['GET'])
def health():
    registry = rule_registry.get_registry()
    active = [r for r in registry if r['enabled'] and r['implemented']]
    return jsonify({
        'status': 'ok',
        'app': 'ComplianceAI',
        'version': '2.0.0-SIH2026',
        'engines': {
            'ocr': 'EasyOCR + Multi-Pass Preprocessing',
            'barcode': 'PyZbar + OpenCV Barcode/QR Radar',
            'rules': f"{len(active)} Active Legal Metrology Rules (2011 & 2022 Amendments)",
            'database': 'SQLite Embedded DB',
            'pdf_generator': 'FPDF2 Form LM-2026'
        },
        'rule_count': len(active),
        'rule_registry_total': len(registry),
        'public_urls': {
            'scanner': config.PUBLIC_API_URL or request.host_url.rstrip('/'),
            'admin': config.PUBLIC_ADMIN_URL,
            'portfolio': config.PORTFOLIO_URL,
        },
        'server_time': datetime.now().isoformat()
    })


@app.route('/api/rules', methods=['GET'])
def get_rules():
    """Live rule registry straight from the database.

    This is what the admin panel edits, so the main page and the portfolio
    always show the registry as it is right now.
    """
    summary = rule_registry.registry_summary()
    return jsonify({
        'summary': {k: v for k, v in summary.items() if k != 'rules'},
        'rules': summary['rules'],
        'server_time': datetime.now().isoformat()
    })


@app.route('/api/analyze', methods=['POST'])
@rate_limit(max_per_minute=30)
def analyze_product():
    """
    Main Analysis Pipeline:
    1. Read uploaded image
    2. Run Multi-Pass OCR with Indian packaging normalizer
    3. Run Multi-Engine Barcode Radar & GS1 India validation
    4. Run 12-Rule Legal Metrology Engine
    5. Run Intelligence & Fraud Radar (Tamper check, USP math, Catalog check, Shelf life)
    6. Generate Calibrated Score & Statutory Section 36 Penalty Assessment
    7. Save to SQLite database
    8. Generate Official PDF Audit Certificate
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image file uploaded'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'Empty image filename'}), 400

    scan_id = f"SCN-{int(time.time())}-{os.urandom(2).hex().upper()}"
    filename = f"{scan_id}.jpg"
    temp_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(temp_path)

    try:
        image = cv2.imread(temp_path)
        if image is None:
            return jsonify({'error': 'Uploaded file is not a valid or readable image'}), 400

        # Step 1: Multi-Engine Barcode & QR Radar
        barcode_detected, barcode_info = barcode_radar.scan_image(image)

        # Step 2: Multi-Pass OCR Text Extraction
        extracted_texts = ocr.extract_text(image)

        # Step 3: 12-Rule Legal Metrology Verification
        check_results, category_name, is_food, barcode_info = rule_engine.run_all_checks(extracted_texts, image)

        # Step 3b: Live rule registry (read fresh so admin edits apply now)
        registry = rule_registry.get_registry()

        # Step 4: Intelligence, Fraud Radar & Price Comparison
        fraud_analysis = intel_engine.run_full_intelligence(
            image, extracted_texts, check_results, barcode_info, category_name, is_food
        )

        # Step 5: Scoring & Report Generation
        report = scorer.generate_report(
            check_results, extracted_texts, category_name, is_food, barcode_info, fraud_analysis,
            registry=registry
        )
        report['scan_id'] = scan_id
        report['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Determine best guess product title
        catalog_match = fraud_analysis.get('catalog_comparison', {})
        if catalog_match.get('in_catalog'):
            product_title = f"{catalog_match.get('brand', '')} {catalog_match.get('official_product_name', '')}".strip()
        else:
            comm_match = check_results.get('commodity_name', (False, {}))[1] or {}
            product_title = comm_match.get('commodity_name', 'Packaged Commodity')

        report['product_name'] = product_title
        report['category'] = category_name

        # Step 6: Save to SQLite Database
        database.save_scan(report)

        # Step 7: Generate PDF Certificate
        pdf_path = os.path.join(REPORTS_FOLDER, f"Certificate_{scan_id}.pdf")
        try:
            generate_compliance_pdf(report, pdf_path)
            report['pdf_download_url'] = f"/api/export-pdf/{scan_id}"
        except Exception as e:
            print(f"[PDF Error] {e}")
            report['pdf_download_url'] = None

        return jsonify(report)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

    finally:
        # Clean up temporary scan image
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


@app.route('/api/history', methods=['GET'])
def get_history():
    limit = min(int(request.args.get('limit', 50)), 100)
    offset = int(request.args.get('offset', 0))
    status_filter = request.args.get('filter') # 'compliant' or 'violation'
    query = request.args.get('search')
    
    scans = database.get_all_scans(limit=limit, offset=offset, filter_status=status_filter, search_query=query)
    return jsonify({
        'scans': scans,
        'count': len(scans),
        'offset': offset,
        'limit': limit
    })


@app.route('/api/scan/<scan_id>', methods=['GET'])
def get_single_scan(scan_id):
    scan = database.get_scan_by_id(scan_id)
    if not scan:
        return jsonify({'error': 'Scan record not found'}), 404
    return jsonify(scan)


@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    metrics = database.get_analytics_metrics()
    return jsonify(metrics)


@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    barcode = request.args.get('barcode')
    search = request.args.get('search')
    if barcode or search:
        item = database.find_catalog_product(barcode=barcode, search_name=search)
        return jsonify({'product': item})
    products = database.get_all_catalog_products()
    return jsonify({'products': products, 'count': len(products)})


@app.route('/api/export-pdf/<scan_id>', methods=['GET'])
def download_pdf(scan_id):
    pdf_path = os.path.join(REPORTS_FOLDER, f"Certificate_{scan_id}.pdf")
    if not os.path.exists(pdf_path):
        # Regenerate from database if missing
        scan = database.get_scan_by_id(scan_id)
        if not scan:
            return jsonify({'error': 'Scan record not found'}), 404
        try:
            generate_compliance_pdf(scan, pdf_path)
        except Exception as e:
            return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500

    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"Compliance_Certificate_{scan_id}.pdf"
    )


@app.route('/api/demo-samples', methods=['GET'])
def get_demo_samples():
    """
    Returns 6 pre-configured realistic Indian product mock samples for 1-click hackathon judging demo.
    """
    samples = [
        {
            'id': 'maggi_sample',
            'name': 'Maggi 2-Minute Instant Noodles (Masala)',
            'brand': 'Nestle India',
            'badge': 'Grade A+ (Fully Compliant)',
            'category': 'Food & Beverages',
            'icon': '🍜',
            'description': 'Real Indian packaging with MRP, 2022 Unit Sale Price, 14-digit FSSAI Lic, and GS1 890 barcode.',
            'mock_data': {
                'scan_id': 'SCN-DEMO-MAGGI',
                'product_name': 'Nestle Maggi 2-Minute Masala Noodles',
                'category': 'Food & Beverages',
                'summary': {
                    'score': 95,
                    'grade': 'A+',
                    'is_compliant': True,
                    'violation_count': 0,
                    'total_penalty': '₹0',
                    'penalty_min': 0,
                    'penalty_max': 0,
                    'commodity_category': 'Food & Beverages',
                    'is_food_product': True
                },
                'extracted_data': [
                    {'text': 'Nestle Maggi 2-Minute Masala Instant Noodles', 'confidence': 0.98},
                    {'text': 'MRP ₹14.00 (incl. of all taxes)', 'confidence': 0.99},
                    {'text': 'USP: ₹0.20 / g', 'confidence': 0.96},
                    {'text': 'Net Wt: 70 g', 'confidence': 0.98},
                    {'text': 'Mfd Date: 02/2026', 'confidence': 0.97},
                    {'text': 'Best Before 9 Months from Manufacturing', 'confidence': 0.95},
                    {'text': 'Manufactured by Nestle India Ltd, New Delhi 110001', 'confidence': 0.94},
                    {'text': 'Country of Origin: India', 'confidence': 0.99},
                    {'text': 'Consumer Care: 1800-103-1947 wecare@in.nestle.com', 'confidence': 0.96},
                    {'text': 'FSSAI Lic. No. 10012011000168', 'confidence': 0.99},
                    {'text': '100% Vegetarian (Green Dot)', 'confidence': 0.97}
                ],
                'rule_checks': [
                    {'rule': 'mrp', 'rule_name': 'Maximum Retail Price (MRP)', 'passed': True, 'weight': 15, 'act_section': 'Rule 6(1)(e) LM Rules 2011', 'details': {'amount': 14.0, 'formatted': '₹14.00', 'inclusive_of_taxes': True}},
                    {'rule': 'unit_sale_price', 'rule_name': 'Unit Sale Price (USP)', 'passed': True, 'weight': 10, 'act_section': 'Rule 6(1)(s) Amend. 2022', 'details': {'declared_usp': 0.20, 'unit': 'g', 'formatted': '₹0.20 / g'}},
                    {'rule': 'weight', 'rule_name': 'Net Quantity Declaration', 'passed': True, 'weight': 15, 'act_section': 'Rule 6(1)(c) & Rule 11', 'details': {'quantity': '70 g', 'numeric_value': 70.0, 'is_si_compliant': True}},
                    {'rule': 'mfg_date', 'rule_name': 'Month & Year of Manufacture', 'passed': True, 'weight': 10, 'act_section': 'Rule 6(1)(d) LM Rules', 'details': {'mfg_date': '02/2026'}},
                    {'rule': 'expiry', 'rule_name': 'Expiry Date / Best Before', 'passed': True, 'weight': 15, 'act_section': 'FSSAI Packaging Reg.', 'details': {'expiry_declaration': '9 Months'}},
                    {'rule': 'manufacturer', 'rule_name': 'Manufacturer Details', 'passed': True, 'weight': 10, 'act_section': 'Rule 6(1)(a) LM Rules', 'details': {'declaration_type': 'manufactured by', 'has_pincode': True}},
                    {'rule': 'country_of_origin', 'rule_name': 'Country of Origin', 'passed': True, 'weight': 5, 'act_section': 'Rule 6(1)(aa) Amend. 2020', 'details': {'country': 'India', 'is_india': True}},
                    {'rule': 'consumer_care', 'rule_name': 'Consumer Care Helpline', 'passed': True, 'weight': 5, 'act_section': 'Rule 6(1)(g) LM Rules', 'details': {'helpline_phone': '1800-103-1947', 'helpline_email': 'wecare@in.nestle.com'}},
                    {'rule': 'fssai', 'rule_name': 'FSSAI License & Logo', 'passed': True, 'weight': 5, 'act_section': 'FSSR Food Safety 2020', 'details': {'fssai_license': '10012011000168', 'is_veg_declared': True}},
                    {'rule': 'commodity_name', 'rule_name': 'Generic Commodity Name', 'passed': True, 'weight': 5, 'act_section': 'Rule 6(1)(b) LM Rules', 'details': {'commodity_name': 'Instant Noodles'}},
                    {'rule': 'barcode', 'rule_name': 'Barcode & Traceability', 'passed': True, 'weight': 3, 'act_section': 'GS1 India Standards', 'details': {'detected': True, 'primary_code': '8901058852371', 'is_made_in_india': True}},
                    {'rule': 'language', 'rule_name': 'Language Compliance', 'passed': True, 'weight': 2, 'act_section': 'Rule 9(1) LM Rules', 'details': {'english': True, 'hindi': True}}
                ],
                'violations': [],
                'advisories': [],
                'recommendations': [
                    'Package fully complies with Legal Metrology (Packaged Commodities) Rules, 2011.',
                    'Approved for unrestricted commercial distribution across all Indian states.'
                ],
                'barcode_data': {
                    'detected': True,
                    'primary_code': '8901058852371',
                    'country_of_origin': 'Republic of India (GS1 India 890)',
                    'is_made_in_india': True,
                    'is_valid_checksum': True,
                    'symbology': 'EAN-13'
                },
                'fraud_analysis': {
                    'tamper_detection': {'tampering_detected': False, 'risk_level': 'NONE', 'details': 'Monolithic original print. No dual-pricing or stickers.'},
                    'usp_verification': {'is_verified': True, 'calculated_true_usp': '₹0.20 / g', 'is_accurate': True, 'verdict': 'USP declaration mathematically verified.'},
                    'catalog_comparison': {'in_catalog': True, 'brand': 'Nestle', 'official_product_name': 'Maggi 2-Minute Instant Noodles Masala', 'standard_catalog_mrp': '₹14.00', 'is_overcharging_detected': False, 'verdict': 'Verified Genuine: Matches manufacturer standard specifications.'},
                    'freshness_analysis': {'is_expired': False, 'status_label': 'Fresh & Valid stock (Batch 02/2026)'}
                }
            }
        },
        {
            'id': 'overcharging_violation_sample',
            'name': 'Pasted Sticker Overcharging Violation',
            'brand': 'Local Store Tampered Pack',
            'badge': 'Grade F (Critical Penalty)',
            'category': 'Food & Beverages',
            'icon': '⚠️',
            'description': 'Retailer pasted a fake ₹35 sticker over original ₹20 MRP. Missing FSSAI, USP and Consumer Care.',
            'mock_data': {
                'scan_id': 'SCN-DEMO-VIOLATION',
                'product_name': 'Potato Chips Snack (Tampered Packaging)',
                'category': 'Snacks & Food',
                'summary': {
                    'score': 42,
                    'grade': 'F',
                    'is_compliant': False,
                    'violation_count': 5,
                    'total_penalty': '₹1,50,000 - ₹3,25,000',
                    'penalty_min': 150000,
                    'penalty_max': 325000,
                    'commodity_category': 'Snacks & Food',
                    'is_food_product': True
                },
                'extracted_data': [
                    {'text': 'Crispy Potato Wafers Masala', 'confidence': 0.94},
                    {'text': 'SPECIAL PRICE MRP ₹35.00', 'confidence': 0.91},
                    {'text': 'Original MRP ₹20.00', 'confidence': 0.88},
                    {'text': 'Net Wt: 50 gms', 'confidence': 0.92},
                    {'text': 'Mfg Date: 11/2025', 'confidence': 0.90}
                ],
                'rule_checks': [
                    {'rule': 'mrp', 'rule_name': 'Maximum Retail Price (MRP)', 'passed': True, 'weight': 15, 'act_section': 'Sec 36(1) LM Act', 'details': {'amount': 35.0, 'inclusive_of_taxes': False}},
                    {'rule': 'unit_sale_price', 'rule_name': 'Unit Sale Price (USP)', 'passed': False, 'weight': 10, 'act_section': 'Rule 6(1)(s) 2022 Amend.', 'details': {'error': 'Declared USP missing'}},
                    {'rule': 'weight', 'rule_name': 'Net Quantity Declaration', 'passed': True, 'weight': 15, 'act_section': 'Rule 6(1)(c)', 'details': {'quantity': '50 g', 'is_si_compliant': False, 'unit_note': 'Use g instead of gms'}},
                    {'rule': 'mfg_date', 'rule_name': 'Month & Year of Manufacture', 'passed': True, 'weight': 10, 'act_section': 'Rule 6(1)(d)', 'details': {'mfg_date': '11/2025'}},
                    {'rule': 'expiry', 'rule_name': 'Expiry Date / Best Before', 'passed': False, 'weight': 15, 'act_section': 'FSSAI Packaging Reg.', 'details': {'error': 'Missing expiry date on food item (CRITICAL)'}},
                    {'rule': 'manufacturer', 'rule_name': 'Manufacturer Details', 'passed': False, 'weight': 10, 'act_section': 'Rule 6(1)(a)', 'details': {'error': 'No manufacturer address found'}},
                    {'rule': 'country_of_origin', 'rule_name': 'Country of Origin', 'passed': False, 'weight': 5, 'act_section': 'Rule 6(1)(aa)', 'details': {'error': 'Origin declaration missing'}},
                    {'rule': 'consumer_care', 'rule_name': 'Consumer Care Helpline', 'passed': False, 'weight': 5, 'act_section': 'Rule 6(1)(g)', 'details': {'error': 'Missing helpline/email'}},
                    {'rule': 'fssai', 'rule_name': 'FSSAI License & Logo', 'passed': False, 'weight': 5, 'act_section': 'FSSR 2020', 'details': {'error': '14-digit FSSAI Lic missing'}},
                    {'rule': 'commodity_name', 'rule_name': 'Generic Commodity Name', 'passed': True, 'weight': 5, 'act_section': 'Rule 6(1)(b)', 'details': {'commodity_name': 'Potato Chips'}},
                    {'rule': 'barcode', 'rule_name': 'Barcode & Traceability', 'passed': False, 'weight': 3, 'act_section': 'GS1 India', 'details': {'error': 'Barcode missing/unreadable'}},
                    {'rule': 'language', 'rule_name': 'Language Compliance', 'passed': True, 'weight': 2, 'act_section': 'Rule 9(1)', 'details': {'english': True, 'hindi': False}}
                ],
                'violations': [
                    {'rule': 'expiry', 'rule_name': 'Expiry Date / Best Before', 'severity': 'CRITICAL', 'act_section': 'FSSAI Act Sec 59', 'penalty_range': '₹50,000 - ₹2,00,000'},
                    {'rule': 'unit_sale_price', 'rule_name': 'Unit Sale Price (USP)', 'severity': 'MAJOR', 'act_section': 'Rule 6(1)(s) Amend. 2022', 'penalty_range': '₹25,000 - ₹50,000'},
                    {'rule': 'manufacturer', 'rule_name': 'Manufacturer Details', 'severity': 'MAJOR', 'act_section': 'Rule 6(1)(a) LM Rules', 'penalty_range': '₹25,000 - ₹50,000'},
                    {'rule': 'fssai', 'rule_name': 'FSSAI License & Logo', 'severity': 'MAJOR', 'act_section': 'FSSR 2020', 'penalty_range': '₹25,000 - ₹1,00,000'},
                    {'rule': 'consumer_care', 'rule_name': 'Consumer Care Helpline', 'severity': 'MAJOR', 'act_section': 'Rule 6(1)(g)', 'penalty_range': '₹10,000 - ₹25,000'}
                ],
                'recommendations': [
                    'URGENT STATUTORY ACTION: Missing Expiry Date is a critical health hazard under FSSAI Section 59.',
                    'ILLEGAL OVERCHARGING: Pasted sticker increases price to ₹35.00 against standard catalog ₹20.00.',
                    'ISSUE FORM LM-2026 NOTICE: Retailer liable for compounding penalty under Section 36 LM Act.'
                ],
                'barcode_data': {'detected': False, 'country_of_origin': 'Not Detected'},
                'fraud_analysis': {
                    'tamper_detection': {'tampering_detected': True, 'risk_level': 'HIGH (OVER-STICKERED MRP DETECTED)', 'details': 'Detected pasted sticker border and conflicting dual prices: [20.0, 35.0]. Severe violation of Section 36(2) LM Act.'},
                    'usp_verification': {'is_verified': True, 'calculated_true_usp': '₹0.70 / g', 'is_accurate': False, 'verdict': 'USP missing from pack. At ₹35.00 for 50g, calculated rate is ₹0.70/g.'},
                    'catalog_comparison': {'in_catalog': True, 'brand': "Lay's", 'official_product_name': "Lay's Magic Masala Potato Chips", 'standard_catalog_mrp': '₹20.00', 'is_overcharging_detected': True, 'price_difference': '+₹15.00', 'verdict': 'ALERT: Retailer Overcharging Detected! Scanned price ₹35.00 exceeds standard ₹20.00.'},
                    'freshness_analysis': {'is_expired': False, 'status_label': 'Manufactured 11/2025 (Missing explicit expiry date)'}
                }
            }
        },
        {
            'id': 'parle_sample',
            'name': 'Parle-G Glucose Biscuits (130g)',
            'brand': 'Parle Products',
            'badge': 'Grade A+ (Compliant)',
            'category': 'Food & Beverages',
            'icon': '🍪',
            'description': 'Verified Indian FMCG staple with standard ₹10.00 MRP, 130g Net Quantity, and GS1 890 barcode.',
            'mock_data': None # Dynamically constructed if requested
        },
        {
            'id': 'amul_sample',
            'name': 'Amul Pasteurised Butter (100g)',
            'brand': 'GCMMF Amul',
            'badge': 'Grade A+ (Compliant)',
            'category': 'Dairy & Food',
            'icon': '🧈',
            'description': 'Official dairy product packaging with cold-chain expiry date and ₹56.00 MRP.',
            'mock_data': None
        },
        {
            'id': 'surf_excel_sample',
            'name': 'Surf Excel Detergent Powder (1kg)',
            'brand': 'Hindustan Unilever',
            'badge': 'Grade A (Non-Food Compliant)',
            'category': 'Household Care',
            'icon': '🧼',
            'description': 'Non-food commodity demo showing automatic exemption of FSSAI & Expiry date rules.',
            'mock_data': None
        },
        {
            'id': 'dettol_sample',
            'name': 'Dettol Liquid Handwash (200ml)',
            'brand': 'Reckitt Benckiser',
            'badge': 'Grade A (Personal Care)',
            'category': 'Personal Care',
            'icon': '🧴',
            'description': 'Personal care commodity verifying metric volume (ml), batch number, and helpline details.',
            'mock_data': None
        }
    ]
    return jsonify({'samples': samples, 'count': len(samples)})


@app.route('/api/clear-history', methods=['POST'])
def clear_history():
    database.clear_all_history()
    return jsonify({'success': True, 'message': 'Scan history cleared'})


if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "=" * 60)
    print("  COMPLIANCE AI — LEGAL METROLOGY SCANNER (SIH 2026)")
    print("=" * 60)
    print(f"  Local Web App:  http://127.0.0.1:{port}")
    print(f"  Network/Phone:  http://{local_ip}:{port}")
    print("=" * 60 + "\n")
    app.run(debug=False, host='0.0.0.0', port=port)
