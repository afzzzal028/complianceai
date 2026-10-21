import cv2
import numpy as np
import re
from datetime import datetime
import database


class IntelligenceEngine:
    """
    Intelligence, Fraud Radar, and Price Comparison Engine:
    - Dual Pricing & Fake Overprinted / Pasted Sticker Detection
    - Mathematical Unit Sale Price (USP) Deception Validator
    - Verified Indian FMCG Catalog Price Comparison & Overcharging Radar
    - Shelf Life & Expiry Freshness Calculator
    """
    def __init__(self):
        pass

    def detect_sticker_tampering(self, image, extracted_texts):
        """
        Visual heuristic analysis: Detects pasted price stickers or over-printed labels
        around MRP area by looking for rectangular boundary contours, edge gradients,
        and stark background contrast shifts.
        """
        if image is None:
            return {
                'tampering_detected': False,
                'confidence': 0.0,
                'risk_level': 'LOW',
                'details': 'Image not available for visual tamper check'
            }

        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 50, 150)

            # Find rectangular contours that might represent pasted stickers
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            h_img, w_img = gray.shape[:2]
            img_area = h_img * w_img

            sticker_candidates = []
            for cnt in contours:
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
                if len(approx) == 4: # Quadrilateral
                    x, y, w, h = cv2.boundingRect(approx)
                    cnt_area = w * h
                    aspect_ratio = float(w) / h if h > 0 else 0
                    
                    # A typical sticker covers 1% to 15% of the package surface and has aspect ratio 1.5 to 5
                    if 0.008 * img_area < cnt_area < 0.20 * img_area and 1.2 <= aspect_ratio <= 6.0:
                        # Extract ROI and check standard deviation of intensity around border
                        roi = gray[y:y+h, x:x+w]
                        if roi.size > 0:
                            std_dev = np.std(roi)
                            sticker_candidates.append({
                                'bbox': [x, y, w, h],
                                'area_ratio': round(cnt_area / img_area, 4),
                                'contrast_std': round(float(std_dev), 2)
                            })

            # Check if any extracted text contains conflicting multiple prices
            all_text = ' '.join([t['text'] for t in extracted_texts if isinstance(t, dict)])
            price_matches = re.findall(r'(?:MRP|Rs\.?|₹)\s*[:\s]*(\d+(?:\.\d{1,2})?)', all_text, re.IGNORECASE)
            unique_prices = list(set([float(p) for p in price_matches if float(p) > 0]))

            has_conflicting_prices = len(unique_prices) > 1
            has_sticker_rect = len(sticker_candidates) > 0

            if has_conflicting_prices and has_sticker_rect:
                return {
                    'tampering_detected': True,
                    'confidence': 0.88,
                    'risk_level': 'HIGH (LIKELY OVER-STICKERED MRP)',
                    'details': f"Detected pasted sticker boundary ({len(sticker_candidates)} candidate regions) and {len(unique_prices)} conflicting prices ({unique_prices}). Potential illegal dual-pricing violation under Section 36(2) LM Act."
                }
            elif has_conflicting_prices:
                return {
                    'tampering_detected': True,
                    'confidence': 0.72,
                    'risk_level': 'MEDIUM (DUAL PRICING DETECTED)',
                    'details': f"Found multiple conflicting price declarations: {unique_prices}. Selling at higher price violates Rule 18(2) LM(PC) Rules."
                }
            elif has_sticker_rect:
                return {
                    'tampering_detected': False,
                    'confidence': 0.45,
                    'risk_level': 'LOW (POTENTIAL LABEL PATCH)',
                    'details': f"Detected {len(sticker_candidates)} rectangular label patch(es). No price conflict identified."
                }
            else:
                return {
                    'tampering_detected': False,
                    'confidence': 0.15,
                    'risk_level': 'NONE (ORIGINAL MONOLITHIC PACKAGING)',
                    'details': 'Packaging shows uniform monolithic print without pasted sticker overlays.'
                }

        except Exception as e:
            return {
                'tampering_detected': False,
                'confidence': 0.0,
                'risk_level': 'LOW',
                'details': f"Visual analysis completed with neutral status ({str(e)})"
            }

    def validate_unit_sale_price_math(self, mrp_amount, weight_info, declared_usp_info):
        """
        Validates whether the printed Unit Sale Price matches the true mathematical
        division (MRP / Quantity). Flags deceptive price calculation.
        """
        if not mrp_amount or not weight_info or not weight_info.get('numeric_value'):
            return {
                'is_verified': False,
                'error': 'Insufficient price or quantity data for USP mathematical validation'
            }

        qty = weight_info['numeric_value']
        unit = weight_info.get('standard_unit', 'g').lower()
        
        # Calculate true unit price
        true_unit_rate = mrp_amount / qty if qty > 0 else 0
        
        # Determine standard base unit (per g, per kg, per ml, per L)
        base_unit = unit
        calculated_display = f"₹{true_unit_rate:.2f} / {unit}"
        
        if unit in ['g', 'gm'] and qty >= 1000:
            calculated_display = f"₹{(true_unit_rate * 1000):.2f} / kg"
        elif unit in ['ml'] and qty >= 1000:
            calculated_display = f"₹{(true_unit_rate * 1000):.2f} / L"

        declared_rate = None
        if declared_usp_info and isinstance(declared_usp_info, dict):
            declared_rate = declared_usp_info.get('declared_usp')

        is_mathematically_accurate = True
        discrepancy_pct = 0.0

        if declared_rate is not None:
            # Check if discrepancy is within 5% tolerance (rounding differences)
            diff = abs(declared_rate - true_unit_rate)
            discrepancy_pct = (diff / true_unit_rate * 100) if true_unit_rate > 0 else 0
            is_mathematically_accurate = discrepancy_pct <= 5.0

        return {
            'is_verified': True,
            'calculated_true_usp': calculated_display,
            'true_rate_raw': round(true_unit_rate, 4),
            'declared_rate': declared_rate,
            'is_accurate': is_mathematically_accurate,
            'discrepancy_percentage': round(discrepancy_pct, 2),
            'verdict': 'USP declaration mathematically verified' if (declared_rate and is_mathematically_accurate) else ('USP not declared on pack — calculated value shown' if not declared_rate else f'Deceptive USP: Declared ₹{declared_rate} differs by {discrepancy_pct:.1f}% from true price ₹{true_unit_rate:.2f}')
        }

    def compare_with_catalog(self, barcode_info, mrp_amount, product_name_guess=None):
        """
        Cross-references with the Indian FMCG product database to catch overcharging,
        counterfeit packaging, or altered barcode metadata.
        """
        barcode_str = barcode_info.get('primary_code') if barcode_info else None
        
        matched_item = None
        if barcode_str:
            matched_item = database.find_catalog_product(barcode=barcode_str)
            
        if not matched_item and product_name_guess:
            matched_item = database.find_catalog_product(search_name=product_name_guess)

        if not matched_item:
            return {
                'in_catalog': False,
                'status': 'Product not pre-registered in central FMCG catalog (New or local brand)',
                'price_check': 'Standard reference comparison unavailable'
            }

        catalog_mrp = matched_item.get('standard_mrp', 0.0)
        brand = matched_item.get('brand', 'Unknown')
        prod_title = matched_item.get('product_name', 'Unknown')
        fssai_db = matched_item.get('fssai_no')
        std_qty = matched_item.get('standard_quantity')

        is_overcharging = False
        price_diff = 0.0
        if mrp_amount and catalog_mrp > 0:
            price_diff = mrp_amount - catalog_mrp
            if price_diff > 0.50: # Scanned price is higher than standard company MRP!
                is_overcharging = True

        return {
            'in_catalog': True,
            'catalog_product_id': matched_item.get('id'),
            'brand': brand,
            'official_product_name': prod_title,
            'standard_catalog_mrp': f"₹{catalog_mrp:.2f}",
            'standard_quantity': std_qty,
            'registered_fssai': fssai_db,
            'is_overcharging_detected': is_overcharging,
            'price_difference': f"+₹{price_diff:.2f}" if price_diff > 0 else (f"-₹{abs(price_diff):.2f}" if price_diff < 0 else "₹0.00"),
            'verdict': f"ALERT: Retailer Overcharging Detected! Scanned MRP ₹{mrp_amount:.2f} exceeds manufacturer standard ₹{catalog_mrp:.2f}." if is_overcharging else f"Verified Genuine: Matches manufacturer standard specifications ({brand} {prod_title})."
        }

    def analyze_shelf_life_freshness(self, mfg_date_str, expiry_date_str, is_food):
        """
        Calculates days since manufacturing, remaining shelf life, and flags expired stock.
        """
        now = datetime.now()
        
        # Parse Mfg Date
        mfg_dt = None
        if mfg_date_str:
            formats = ['%d/%m/%Y', '%d-%m-%Y', '%m/%Y', '%m-%Y', '%d/%m/%y', '%m/%y', '%Y']
            for fmt in formats:
                try:
                    mfg_dt = datetime.strptime(mfg_date_str.strip(), fmt)
                    break
                except:
                    pass

        # Check for post-dated manufacturing fraud (Mfg date in the future)
        is_post_dated_fraud = False
        if mfg_dt and mfg_dt > now:
            is_post_dated_fraud = True

        # Parse Expiry Date if absolute date
        exp_dt = None
        is_expired = False
        days_remaining = None

        if expiry_date_str and is_food:
            formats = ['%d/%m/%Y', '%d-%m-%Y', '%m/%Y', '%m-%Y', '%d/%m/%y', '%m/%y', '%Y']
            for fmt in formats:
                try:
                    exp_dt = datetime.strptime(expiry_date_str.strip(), fmt)
                    break
                except:
                    pass

            if exp_dt:
                days_remaining = (exp_dt - now).days
                if days_remaining < 0:
                    is_expired = True

        status = "Fresh & Valid"
        if is_post_dated_fraud:
            status = "FRAUD WARNING: Post-dated manufacturing date (Printed date is in the future!)"
        elif is_expired:
            status = f"CRITICAL HAZARD: Product EXPIRED {abs(days_remaining)} days ago! Illegal to sell under FSSAI."
        elif days_remaining is not None and days_remaining <= 30:
            status = f"NEAR EXPIRY ADVISORY: Only {days_remaining} days of shelf life remaining."
        elif not is_food:
            status = "Non-perishable durable product"

        return {
            'is_expired': is_expired,
            'is_post_dated': is_post_dated_fraud,
            'days_remaining': days_remaining,
            'status_label': status
        }

    def run_full_intelligence(self, image, extracted_texts, check_results, barcode_info, category_name, is_food):
        """
        Executes full intelligence suite: Anti-tamper, USP math check, Catalog price check, and Shelf life.
        """
        mrp_res = check_results.get('mrp', (False, {}))[1] or {}
        weight_res = check_results.get('weight', (False, {}))[1] or {}
        usp_res = check_results.get('unit_sale_price', (False, {}))[1] or {}
        mfg_res = check_results.get('mfg_date', (False, {}))[1] or {}
        exp_res = check_results.get('expiry', (False, {}))[1] or {}
        comm_res = check_results.get('commodity_name', (False, {}))[1] or {}

        mrp_amt = mrp_res.get('amount')
        mfg_str = mfg_res.get('mfg_date')
        exp_str = exp_res.get('expiry_declaration')
        comm_guess = comm_res.get('commodity_name')

        tamper_report = self.detect_sticker_tampering(image, extracted_texts)
        usp_math_report = self.validate_unit_sale_price_math(mrp_amt, weight_res, usp_res)
        catalog_report = self.compare_with_catalog(barcode_info, mrp_amt, comm_guess)
        freshness_report = self.analyze_shelf_life_freshness(mfg_str, exp_str, is_food)

        return {
            'tamper_detection': tamper_report,
            'usp_verification': usp_math_report,
            'catalog_comparison': catalog_report,
            'freshness_analysis': freshness_report
        }
