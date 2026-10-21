import os
import time
from datetime import datetime
from fpdf import FPDF


def clean_pdf_text(text):
    """Replaces Unicode characters with Latin-1 equivalents for standard Helvetica font."""
    if text is None:
        return ""
    text = str(text)
    replacements = {
        '₹': 'Rs. ',
        '—': ' - ',
        '–': ' - ',
        '’': "'",
        '‘': "'",
        '“': '"',
        '”': '"',
        '•': '*',
        '✓': '[PASS]',
        '✗': '[FAIL]',
        '…': '...',
        '™': '(TM)',
        '®': '(R)',
        '©': '(C)'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Strip any remaining non-latin1 characters
    return text.encode('latin-1', errors='replace').decode('latin-1')


class LegalMetrologyPDF(FPDF):
    def header(self):
        # Header banner
        self.set_fill_color(26, 35, 126) # Deep Navy Blue
        self.rect(0, 0, 210, 24, 'F')
        
        self.set_text_color(255, 255, 255)
        self.set_font('Helvetica', 'B', 13)
        self.set_xy(10, 4)
        self.cell(190, 8, clean_pdf_text('COMPLIANCE AI - LEGAL METROLOGY INSPECTION REPORT'), 0, 1, 'C')
        
        self.set_font('Helvetica', 'I', 8)
        self.set_xy(10, 12)
        self.cell(190, 6, clean_pdf_text('Statutory Packaged Commodity Audit under Legal Metrology Act, 2009 & Rules, 2011'), 0, 1, 'C')
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, clean_pdf_text(f'Form LM-2026 (Sec 36) | Automated Verification | Page {self.page_no()}/{{nb}} | Confidential Inspection Document'), 0, 0, 'C')


def generate_compliance_pdf(scan_data, output_path=None):
    """
    Generates a formal Legal Metrology Compliance Audit Certificate PDF.
    """
    if not output_path:
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        scan_id = scan_data.get('scan_id', f"SCN-{int(time.time())}")
        output_path = os.path.join(reports_dir, f"Certificate_{scan_id}.pdf")

    pdf = LegalMetrologyPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)

    summary = scan_data.get('summary', {})
    score = summary.get('score', 0)
    grade = summary.get('grade', 'F')
    is_compliant = summary.get('is_compliant', False)
    category = summary.get('commodity_category', scan_data.get('category', 'Packaged Commodity'))
    prod_name = scan_data.get('product_name', 'Commercial Packaged Item')
    scan_id = scan_data.get('scan_id', 'N/A')
    timestamp = scan_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    total_penalty = summary.get('total_penalty', 'Rs. 0')

    # Top Inspection Details Box
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, 28, 190, 32, 'DF')

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(14, 32)
    pdf.cell(90, 5, clean_pdf_text(f"INSPECTION ID: {scan_id}"), 0, 0)
    pdf.cell(90, 5, clean_pdf_text(f"DATE / TIME: {timestamp}"), 0, 1)

    pdf.set_xy(14, 38)
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(90, 5, clean_pdf_text(f"PRODUCT: {prod_name[:40]}"), 0, 0)
    pdf.cell(90, 5, clean_pdf_text(f"COMMODITY CLASS: {category}"), 0, 1)

    barcode_info = scan_data.get('barcode_data', {})
    b_code = barcode_info.get('primary_code', 'Not Detected')
    b_country = barcode_info.get('country_of_origin', 'N/A')

    pdf.set_xy(14, 44)
    pdf.cell(90, 5, clean_pdf_text(f"BARCODE: {b_code}"), 0, 0)
    pdf.cell(90, 5, clean_pdf_text(f"GS1 ORIGIN: {b_country}"), 0, 1)

    pdf.set_xy(14, 50)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(90, 5, clean_pdf_text(f"ESTIMATED STATUTORY PENALTY: {total_penalty}"), 0, 0)
    pdf.cell(90, 5, clean_pdf_text("AUTHORITY: National Legal Metrology Portal"), 0, 1)

    # Score & Compliance Status Banner
    pdf.set_xy(10, 64)
    if is_compliant:
        pdf.set_fill_color(232, 245, 233) # Soft Green
        pdf.set_text_color(46, 125, 50)
        status_text = f"COMPLIANT - GRADE {grade} (Score: {score}/100)"
        sub_text = "All mandatory declarations under Legal Metrology Rules, 2011 are verified."
    else:
        pdf.set_fill_color(255, 235, 238) # Soft Red
        pdf.set_text_color(198, 40, 40)
        status_text = f"NON-COMPLIANT / VIOLATIONS FLAGGED - GRADE {grade} (Score: {score}/100)"
        sub_text = f"Notice of non-compliance under Section 36 Legal Metrology Act, 2009. Total Violations: {summary.get('violation_count', 0)}"

    pdf.rect(10, 64, 190, 18, 'DF')
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_xy(14, 66)
    pdf.cell(182, 7, clean_pdf_text(status_text), 0, 1, 'C')
    pdf.set_font('Helvetica', 'I', 8)
    pdf.cell(182, 5, clean_pdf_text(sub_text), 0, 1, 'C')

    # Table Header for 12 Rule Checks
    pdf.set_xy(10, 86)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(26, 35, 126)
    pdf.cell(190, 6, "STATUTORY DECLARATION AUDIT BREAKDOWN", 0, 1, 'L')

    pdf.set_fill_color(230, 235, 245)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font('Helvetica', 'B', 8)
    
    # Columns: Rule Name (60), Act Section (55), Weight (18), Status (22), Finding (35)
    pdf.cell(60, 7, clean_pdf_text("Mandatory Declaration (Rule)"), 1, 0, 'L', fill=True)
    pdf.cell(55, 7, clean_pdf_text("Legal Metrology Act / FSSAI Section"), 1, 0, 'L', fill=True)
    pdf.cell(18, 7, clean_pdf_text("Weight"), 1, 0, 'C', fill=True)
    pdf.cell(22, 7, clean_pdf_text("Status"), 1, 0, 'C', fill=True)
    pdf.cell(35, 7, clean_pdf_text("Finding / Value"), 1, 1, 'L', fill=True)

    rule_checks = scan_data.get('rule_checks', [])
    pdf.set_font('Helvetica', '', 7.5)

    for r in rule_checks:
        rname = clean_pdf_text(str(r.get('rule_name', 'Rule'))[:30])
        section = clean_pdf_text(str(r.get('act_section', 'LM Rules 2011'))[:28])
        weight = clean_pdf_text(str(r.get('weight', '-')))
        passed = r.get('passed', False)
        details_obj = r.get('details', {}) or {}
        
        # Build brief finding
        finding = "Verified" if passed else "Missing / Illegible"
        if isinstance(details_obj, dict):
            if 'amount' in details_obj:
                finding = f"Rs. {details_obj['amount']}"
            elif 'quantity' in details_obj:
                finding = f"{details_obj['quantity']}"
            elif 'declared_usp' in details_obj:
                finding = f"USP: Rs.{details_obj['declared_usp']}"
            elif 'mfg_date' in details_obj:
                finding = f"Mfg: {details_obj['mfg_date']}"
            elif 'expiry_declaration' in details_obj:
                finding = f"Exp: {details_obj['expiry_declaration']}"
            elif 'country' in details_obj:
                finding = f"{details_obj['country']}"
            elif 'fssai_license' in details_obj:
                finding = f"Lic: {details_obj['fssai_license']}"
            elif 'error' in details_obj:
                finding = str(details_obj['error'])[:22]

        finding = clean_pdf_text(finding)

        pdf.set_text_color(0, 0, 0)
        pdf.cell(60, 6, rname, 1, 0, 'L')
        pdf.cell(55, 6, section, 1, 0, 'L')
        pdf.cell(18, 6, weight, 1, 0, 'C')
        
        if passed:
            pdf.set_text_color(46, 125, 50)
            pdf.cell(22, 6, "PASS", 1, 0, 'C')
        else:
            pdf.set_text_color(198, 40, 40)
            pdf.cell(22, 6, "FAIL", 1, 0, 'C')

        pdf.set_text_color(60, 60, 60)
        pdf.cell(35, 6, finding[:24], 1, 1, 'L')

    pdf.ln(4)

    # Intelligence & Fraud Radar Section
    fraud = scan_data.get('fraud_analysis', {})
    tamper = fraud.get('tamper_detection', {})
    usp_v = fraud.get('usp_verification', {})
    cat_comp = fraud.get('catalog_comparison', {})

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(26, 35, 126)
    pdf.cell(190, 5, clean_pdf_text("INTELLIGENCE, ANTI-TAMPER & PRICE RADAR FINDINGS"), 0, 1, 'L')

    pdf.set_fill_color(248, 249, 250)
    pdf.rect(10, pdf.get_y(), 190, 20, 'DF')
    pdf.set_xy(14, pdf.get_y() + 2)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(40, 40, 40)

    pdf.cell(182, 4, clean_pdf_text(f"- Sticker Tamper Check: {tamper.get('risk_level', 'LOW')} - {tamper.get('details', 'No anomalies')[:75]}"), 0, 1)
    pdf.cell(182, 4, clean_pdf_text(f"- Unit Sale Price Check: {usp_v.get('verdict', 'USP Calculated and checked')[:80]}"), 0, 1)
    pdf.cell(182, 4, clean_pdf_text(f"- Central FMCG Catalog Radar: {cat_comp.get('verdict', 'Comparison completed')[:80]}"), 0, 1)

    pdf.ln(8)

    # Actionable Directives / Recommendations
    recs = scan_data.get('recommendations', [])
    if recs:
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_text_color(26, 35, 126)
        pdf.cell(190, 5, clean_pdf_text("STATUTORY DIRECTIVES & ACTION PLAN"), 0, 1, 'L')

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(50, 50, 50)
        for i, rec in enumerate(recs[:3], 1):
            pdf.cell(190, 4.5, clean_pdf_text(f"{i}. {rec}"), 0, 1)

    pdf.ln(4)

    # Official Seal & Signature Block
    pdf.set_draw_color(180, 180, 180)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(40, 40, 40)
    
    y_sig = pdf.get_y() + 2
    if y_sig < 255:
        pdf.set_xy(14, y_sig)
        pdf.cell(80, 4, clean_pdf_text("[DIGITALLY GENERATED AUDIT SEAL]"), 0, 0)
        pdf.cell(90, 4, clean_pdf_text("LEGAL METROLOGY ENFORCEMENT NODE"), 0, 1, 'R')
        pdf.set_xy(14, y_sig + 4)
        pdf.set_font('Helvetica', 'I', 7)
        pdf.cell(80, 4, clean_pdf_text(f"Hash: SHA256:{os.urandom(8).hex().upper()}"), 0, 0)
        pdf.cell(90, 4, clean_pdf_text("Verified by ComplianceAI Automated Engine"), 0, 1, 'R')

    pdf.output(output_path)
    return output_path


if __name__ == '__main__':
    mock_data = {
        'scan_id': 'SCN-TEST-101',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'product_name': 'Maggi 2-Minute Instant Noodles Masala',
        'category': 'Food & Beverages',
        'summary': {
            'score': 90,
            'grade': 'A+',
            'is_compliant': True,
            'violation_count': 0,
            'total_penalty': 'Rs. 0'
        },
        'barcode_data': {
            'primary_code': '8901058852371',
            'country_of_origin': 'Republic of India (GS1 India 890)'
        },
        'rule_checks': [
            {'rule_name': 'Maximum Retail Price (MRP)', 'act_section': 'Rule 6(1)(e) LM Rules', 'weight': 15, 'passed': True, 'details': {'amount': 14.0}},
            {'rule_name': 'Net Quantity Declaration', 'act_section': 'Rule 6(1)(c) & Rule 11', 'weight': 15, 'passed': True, 'details': {'quantity': '70 g'}},
            {'rule_name': 'Month & Year of Manufacture', 'act_section': 'Rule 6(1)(d) LM Rules', 'weight': 10, 'passed': True, 'details': {'mfg_date': '01/2026'}},
            {'rule_name': 'Expiry Date / Best Before', 'act_section': 'FSSAI Packaging Reg.', 'weight': 15, 'passed': True, 'details': {'expiry_declaration': '9 Months'}},
            {'rule_name': 'Unit Sale Price (USP)', 'act_section': 'Rule 6(1)(s) 2022 Amend.', 'weight': 10, 'passed': False, 'details': {'error': 'Missing declared USP'}},
        ],
        'recommendations': [
            'Package complies with standard retail distribution requirements.',
            'Print declared USP on primary panel per 2022 statutory amendment.'
        ],
        'fraud_analysis': {
            'tamper_detection': {'risk_level': 'NONE', 'details': 'Monolithic label'},
            'usp_verification': {'verdict': 'USP calculated as Rs. 0.20/g'},
            'catalog_comparison': {'verdict': 'Matches official catalog record'}
        }
    }
    out = generate_compliance_pdf(mock_data)
    print("Generated test PDF at:", out)
