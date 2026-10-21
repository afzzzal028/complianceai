import os
import sys
import unittest
import database
from barcode_engine import BarcodeRadar
from ocr_engine import ProductOCR
from rule_engine import RuleEngine
from scorer import ComplianceScorer
from intelligence_engine import IntelligenceEngine
from pdf_report import generate_compliance_pdf
from app import app


class TestComplianceAI(unittest.TestCase):
    def setUp(self):
        self.app_client = app.test_client()
        self.radar = BarcodeRadar()
        self.ocr = ProductOCR()
        self.rules = RuleEngine()
        self.scorer = ComplianceScorer()
        self.intel = IntelligenceEngine()

    def test_01_database_and_catalog(self):
        products = database.get_all_catalog_products()
        self.assertGreaterEqual(len(products), 15, "Product catalog should have at least 15 seeded FMCG items")
        maggi = database.find_catalog_product(barcode="8901058852371")
        self.assertIsNotNone(maggi, "Maggi barcode lookup should succeed")
        self.assertEqual(maggi['brand'], 'Nestle')

    def test_02_barcode_radar(self):
        country = self.radar.get_gs1_country_origin("8901058852371")
        self.assertIn("Republic of India", country)

    def test_03_ocr_text_normalizer(self):
        sample = "M.R.P. Rs. 20.00 (Incl. of all taxes) Net Wt: 70g Mfd Date: 05/2026 FSSA1 Lic No 10012011000168 Made in India"
        normalized = self.ocr.normalize_indian_packaging_text(sample)
        self.assertIn("MRP", normalized)
        self.assertIn("incl. of all taxes", normalized)
        self.assertIn("Net Wt", normalized)
        self.assertIn("FSSAI", normalized)

    def test_04_twelve_rule_engine(self):
        texts = [
            {'text': 'Nestle Maggi 2-Minute Masala Noodles'},
            {'text': 'MRP ₹14.00 (incl. of all taxes)'},
            {'text': 'USP: ₹0.20 / g'},
            {'text': 'Net Wt: 70 g'},
            {'text': 'Mfd Date: 01/2026'},
            {'text': 'Best Before 9 Months from Mfd'},
            {'text': 'Manufactured by Nestle India Ltd, New Delhi 110001'},
            {'text': 'Made in India'},
            {'text': 'Consumer Care: 1800-103-1947 wecare@in.nestle.com'},
            {'text': 'FSSAI Lic. No. 10012011000168'}
        ]
        results, cat, is_food, binfo = self.rules.run_all_checks(texts, None)
        self.assertTrue(is_food)
        self.assertEqual(cat, 'Food & Beverages')
        self.assertTrue(results['mrp'][0])
        self.assertTrue(results['weight'][0])
        self.assertTrue(results['expiry'][0])
        self.assertTrue(results['fssai'][0])

    def test_05_calibrated_scoring(self):
        check_results = {
            'mrp': (True, {'amount': 14.0, 'inclusive_of_taxes': True}),
            'unit_sale_price': (True, {'declared_usp': 0.20, 'unit': 'g'}),
            'weight': (True, {'quantity': '70 g', 'numeric_value': 70.0, 'is_si_compliant': True}),
            'mfg_date': (True, {'mfg_date': '01/2026'}),
            'expiry': (True, {'expiry_declaration': '9 Months'}),
            'manufacturer': (True, {'has_pincode': True}),
            'country_of_origin': (True, {'country': 'India'}),
            'consumer_care': (True, {'helpline_phone': '1800-103-1947'}),
            'fssai': (True, {'fssai_license': '10012011000168'}),
            'commodity_name': (True, {'commodity_name': 'Instant Noodles'}),
            'barcode': (True, {'primary_code': '8901058852371'}),
            'language': (True, {'english': True, 'hindi': True})
        }
        report = self.scorer.generate_report(check_results, [], 'Food & Beverages', True)
        self.assertGreaterEqual(report['summary']['score'], 90)
        self.assertEqual(report['summary']['grade'], 'A+')
        self.assertTrue(report['summary']['is_compliant'])

    def test_06_intelligence_engine(self):
        res = {
            'mrp': (True, {'amount': 14.0}),
            'weight': (True, {'numeric_value': 70.0, 'standard_unit': 'g'}),
            'unit_sale_price': (True, {'declared_usp': 0.20}),
            'mfg_date': (True, {'mfg_date': '01/2026'}),
            'expiry': (True, {'expiry_declaration': '10/2026'}),
            'commodity_name': (True, {'commodity_name': 'Maggi Instant Noodles'})
        }
        binfo = {'primary_code': '8901058852371'}
        report = self.intel.run_full_intelligence(None, [], res, binfo, 'Food & Beverages', True)
        self.assertTrue(report['usp_verification']['is_verified'])
        self.assertTrue(report['catalog_comparison']['in_catalog'])

    def test_07_pdf_generation(self):
        mock_data = {
            'scan_id': 'SCN-UNIT-TEST',
            'product_name': 'Test Item',
            'category': 'Food & Beverages',
            'summary': {'score': 88, 'grade': 'A', 'is_compliant': True, 'total_penalty': 'Rs. 0'},
            'rule_checks': [
                {'rule_name': 'Maximum Retail Price', 'act_section': 'Rule 6(1)(e)', 'weight': 15, 'passed': True, 'details': {'amount': 20.0}}
            ],
            'recommendations': ['Complies with legal standards']
        }
        pdf_path = os.path.join(os.path.dirname(__file__), 'reports', 'test_cert.pdf')
        out = generate_compliance_pdf(mock_data, pdf_path)
        self.assertTrue(os.path.exists(out))
        self.assertGreater(os.path.getsize(out), 1000)

    def test_08_flask_api_routes(self):
        res = self.app_client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['status'], 'ok')

        res_samples = self.app_client.get('/api/demo-samples')
        self.assertEqual(res_samples.status_code, 200)
        self.assertGreaterEqual(len(res_samples.json['samples']), 5)

        res_cat = self.app_client.get('/api/catalog')
        self.assertEqual(res_cat.status_code, 200)
        self.assertGreaterEqual(len(res_cat.json['products']), 15)


if __name__ == '__main__':
    unittest.main()
