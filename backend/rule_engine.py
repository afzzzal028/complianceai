import re
from datetime import datetime
from barcode_engine import BarcodeRadar
import rule_registry


class RuleEngine:
    """
    12-Rule Compliance Engine for India's Legal Metrology (Packaged Commodities)
    Rules 2011 and 2021/2022 Statutory Amendments.
    """
    def __init__(self):
        self.barcode_radar = BarcodeRadar()
        # Rule metadata and standard legal citations.
        # Single source of truth lives in rule_registry.BUILTIN_RULES; the live
        # registry (DB backed) overrides names, severities and weights.
        self.rule_definitions = rule_registry.BUILTIN_RULES

    def _join_texts(self, texts):
        return ' '.join([t['text'] for t in texts if isinstance(t, dict) and 'text' in t])

    # 1. RULE: Maximum Retail Price (MRP)
    def check_mrp(self, texts):
        combined = self._join_texts(texts)
        
        # Check for mandatory "inclusive of all taxes" clause
        has_taxes_phrase = bool(re.search(
            r'(?:incl(?:usive)?\.?\s*(?:of)?\s*(?:all)?\s*taxes?|inclusive of all taxes|taxes included|all taxes incl)', 
            combined, re.IGNORECASE
        ))

        # Patterns for MRP amounts
        patterns = [
            r'(?:MRP|M\.?R\.?P\.?|Maximum\s+Retail\s+Price)\s*(?:Rs\.?|₹|INR|@)?\s*[:\s/-]*\s*(\d+(?:\.\d{1,2})?)',
            r'(?:Rs\.?|₹|INR)\s*(\d+(?:\.\d{1,2})?)\s*(?:only|/-|\.00|\b)',
            r'Price\s*(?:Rs\.?|₹|INR)?\s*[:\s/-]*\s*(\d+(?:\.\d{1,2})?)',
            r'MRP\s*[:\s]*(\d+(?:\.\d{1,2})?)',
            r'M\.?R\.?P\.?\s*[:\s]*(\d+)',
        ]
        
        extracted_amount = None
        matched_str = ""

        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                extracted_amount = float(match.group(1))
                matched_str = match.group(0)
                break

        # Fallback line-by-line inspection
        if extracted_amount is None:
            for t in texts:
                txt = t['text']
                if re.search(r'\b(?:MRP|M\.?R\.?P\.?|Retail Price)\b', txt, re.IGNORECASE):
                    nums = re.findall(r'(\d+(?:\.\d{1,2})?)', txt)
                    if nums:
                        try:
                            extracted_amount = float(nums[-1])
                            matched_str = txt
                            break
                        except:
                            pass

        if extracted_amount is not None:
            return True, {
                'amount': extracted_amount,
                'formatted': f"₹{extracted_amount:.2f}",
                'raw_text': matched_str,
                'inclusive_of_taxes': has_taxes_phrase,
                'tax_note': 'Complies with tax inclusion rule' if has_taxes_phrase else 'Advisory: Add explicit "(incl. of all taxes)" phrase'
            }

        return False, {'error': 'MRP declaration not detected or illegible'}

    # 2. RULE: Unit Sale Price (USP) - Mandatory 2022 Amendment
    def check_unit_sale_price(self, texts, mrp_info=None, weight_info=None):
        combined = self._join_texts(texts)
        patterns = [
            r'(?:USP|U\.?S\.?P\.?|Unit\s+Sale\s+Price|Unit\s+Price)\s*[:\s/-]*(?:Rs\.?|₹|INR)?\s*(\d+(?:\.\d{1,4})?)\s*(?:per|/)\s*(g|kg|gm|ml|l|ltr|piece|pc|unit|nos?|100g|100ml|100gm|10g)\b',
            r'(?:Rs\.?|₹)\s*(\d+(?:\.\d{1,4})?)\s*(?:per|/)\s*(g|kg|gm|ml|l|ltr|piece|pc|unit|100g|100ml)\b',
            r'(\d+(?:\.\d{1,4})?)\s*(?:Rs\.?|₹|p)\s*(?:per|/)\s*(g|kg|ml|l|unit)\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                price = float(match.group(1))
                unit = match.group(2)
                return True, {
                    'declared_usp': price,
                    'unit': unit,
                    'formatted': f"₹{price} / {unit}",
                    'raw_text': match.group(0),
                    'source': 'declared'
                }

        # If not explicitly printed, calculate expected USP if MRP and Net Qty are known
        if mrp_info and weight_info and weight_info.get('numeric_value'):
            mrp_val = mrp_info.get('amount', 0)
            qty_val = weight_info.get('numeric_value', 1)
            unit_str = weight_info.get('standard_unit', 'unit').lower()
            
            calculated_usp = round(mrp_val / qty_val, 4) if qty_val > 0 else 0
            base_unit = 'g' if 'g' in unit_str else ('ml' if 'ml' in unit_str else ('kg' if 'kg' in unit_str else ('l' if 'l' in unit_str else 'unit')))
            
            # If item is large, calculate per 100g / per kg
            display_usp = f"₹{calculated_usp:.2f} / {base_unit}"
            if base_unit in ['g', 'ml'] and qty_val >= 1000:
                display_usp = f"₹{(calculated_usp * 1000):.2f} / {'kg' if base_unit == 'g' else 'L'}"

            return False, {
                'error': 'Declared Unit Sale Price (USP) missing on pack (Mandatory 2022 Amendment)',
                'calculated_expected_usp': display_usp,
                'suggestion': f'Print declared USP as: {display_usp}'
            }

        return False, {'error': 'Unit Sale Price (USP) declaration missing on packaging'}

    # 3. RULE: Net Quantity Declaration
    def check_weight(self, texts):
        combined = self._join_texts(texts)
        patterns = [
            r'(?:Net\s+(?:Wt\.?|Weight|Qty|Quantity|Vol|Volume|Contents|Measure))\s*[:\s/-]*\s*(\d+(?:\.\d+)?)\s*(g|kg|gm|gms|grams|ml|l|ltr|litre|liter|mg|pcs|pieces|nos?|units?|count|m|cm)\b',
            r'(?:Net\s+Wt|Net\s+Qty)\s*[:\s/-]*\s*(\d+(?:\.\d+)?)\s*(g|kg|gm|gms|ml|l|ltr)\b',
            r'(\d+(?:\.\d+)?)\s*(g|kg|gm|gms|ml|l|ltr|litre|liter|mg|pcs|pieces|nos?)\b',
            r'(?:Weight|Volume|Quantity)\s*[:\s/-]*\s*(\d+(?:\.\d+)?)\s*(g|kg|gm|gms|ml|l|ltr)\b',
            r'(?:Contents|Each|Per)\s+(?:packet|box|unit|piece|pack)?\s*[:\s/-]*\s*(\d+(?:\.\d+)?)\s*(g|kg|ml|l)\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                raw_qty = float(match.group(1))
                unit_raw = match.group(2).lower()
                
                # Standardize to SI unit (Rule 11)
                standard_unit = unit_raw
                if unit_raw in ['gm', 'gms', 'grams']:
                    standard_unit = 'g'
                elif unit_raw in ['ltr', 'litre', 'liter']:
                    standard_unit = 'L'
                elif unit_raw in ['pcs', 'pieces', 'nos', 'no', 'count']:
                    standard_unit = 'units'

                is_si_compliant = unit_raw not in ['gm', 'gms']

                return True, {
                    'quantity': f"{raw_qty} {standard_unit}",
                    'numeric_value': raw_qty,
                    'standard_unit': standard_unit,
                    'raw_unit': unit_raw,
                    'is_si_compliant': is_si_compliant,
                    'unit_note': 'Standard SI unit' if is_si_compliant else "Advisory: Use 'g' instead of 'gm/gms' per Rule 11"
                }

        return False, {'error': 'Net Quantity declaration not detected'}

    # 4. RULE: Month & Year of Manufacture / Packing
    def check_mfg_date(self, texts):
        combined = self._join_texts(texts)
        month_names = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
        patterns = [
            r'(?:Mfg\.?|Mfd\.?|Manufactured|Manufacturing|Production|Packed|Pkg\.?|Pkd\.?|Produced)\s*(?:Date|Dt\.?|On|In|During)?\s*[:\s/-]*\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:Mfg\.?|Mfd\.?|Packed|Pkd\.?)\s*(?:Date|Dt\.?|On)?\s*[:\s/-]*\s*(\d{1,2}\s+' + month_names + r'\s*\d{2,4})',
            r'(?:Mfg\.?|Mfd\.?|Packed|Pkd\.?)\s*(?:Date|Dt\.?|On)?\s*[:\s/-]*\s*(' + month_names + r'\s*\d{2,4})',
            r'(?:Month\s+(?:&|and)?\s+Year\s+of\s+(?:Mfg|Mfd|Packing|Manufacture))\s*[:\s/-]*\s*(\d{1,2}[/-]\d{2,4})',
            r'(?:Mfg|Mfd|Pkd|Packed)\s*[:\s/-]*\s*(\d{1,2}[/-]\d{4})',
            r'(?:Date\s+of\s+(?:Manufacture|Packing|Mfg|Mfd|Pkg))\s*[:\s/-]*\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                return True, {
                    'mfg_date': date_str,
                    'raw_text': match.group(0)
                }

        # Line scan for standard dates after Mfd keyword
        for t in texts:
            txt = t['text']
            if re.search(r'\b(?:Mfg|Mfd|Pkd|Packed|Manufactured)\b', txt, re.IGNORECASE):
                d_match = re.search(r'(\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', txt)
                if d_match:
                    return True, {'mfg_date': d_match.group(1), 'raw_text': txt}

        return False, {'error': 'Date of Manufacture / Packing declaration missing'}

    # 5. RULE: Expiry / Best Before / Use By (Mandatory for food/perishables)
    def check_expiry(self, texts, is_food):
        if not is_food:
            return True, {
                'exempt': True,
                'note': 'Non-food / Durable commodity (Expiry not statutory mandatory under FSSR)'
            }

        combined = self._join_texts(texts)
        month_names = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
        patterns = [
            r'(?:Exp\.?|Expiry|Exd\.?|Best\s*Before|Use\s*By|Used\s*By|BB|EXP)\s*(?:Date|Dt\.?|On)?\s*[:\s/-]*\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:Exp\.?|Expiry|Best\s*Before|Use\s*By)\s*[:\s/-]*\s*(\d{1,2}\s+' + month_names + r'\s*\d{2,4})',
            r'(?:Exp\.?|Expiry|Best\s*Before|Use\s*By)\s*[:\s/-]*\s*(' + month_names + r'\s*\d{2,4})',
            r'(?:Best\s*Before|Best\s*within|Use\s*within)\s*[:\s/-]*\s*(\d+)\s*(months?|days?|years?)\s*(?:from\s+(?:mfg|mfd|pkg|packing|date))?',
            r'(?:Exp|Expiry|Use\s*By)\s*[:\s/-]*\s*(\d{1,2}[/-]\d{4})',
            r'(?:Valid\s+until|Shelf\s+life|Use\s*before)\s*[:\s/-]*\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d+\s+months?)'
        ]

        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                if len(match.groups()) > 1 and match.group(2):
                    expiry_val = f"{match.group(1)} {match.group(2)}"
                else:
                    expiry_val = match.group(1)
                return True, {
                    'expiry_declaration': expiry_val,
                    'raw_text': match.group(0),
                    'is_duration': 'month' in match.group(0).lower() or 'day' in match.group(0).lower()
                }

        # Check for keywords
        for t in texts:
            txt = t['text'].lower()
            if any(k in txt for k in ['best before', 'use by', 'expiry', 'exp dt', 'exp date']):
                nums = re.findall(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4}|\d+\s*months?)', txt)
                if nums:
                    return True, {'expiry_declaration': nums[0], 'raw_text': t['text']}

        return False, {'error': 'Expiry Date / Best Before declaration missing on food commodity (CRITICAL)'}

    # 6. RULE: Manufacturer / Packer / Importer Details
    def check_manufacturer(self, texts):
        combined = self._join_texts(texts)
        mfr_keywords = [
            'manufactured by', 'manufactured at', 'manufactured for', 'marketed by',
            'packed by', 'packed at', 'produced by', 'made by', 'brand owner',
            'mfg by', 'mfd by', 'mfg at', 'mfd at', 'imported by', 'packer:', 'manufacturer:'
        ]
        
        has_keyword = False
        detected_kw = ""
        for kw in mfr_keywords:
            if kw in combined.lower():
                has_keyword = True
                detected_kw = kw
                break

        # Check for address indicators (Pincode, City/State/Road)
        has_pincode = bool(re.search(r'\b\d{6}\b', combined))
        has_address_words = bool(re.search(r'(?:road|street|marg|nagar|sector|lane|industrial|estate|pvt|ltd|limited|delhi|mumbai|bengaluru|kolkata|chennai|hyderabad|ahmedabad|pune|gurugram|noida)', combined, re.IGNORECASE))

        if has_keyword:
            return True, {
                'declaration_type': detected_kw,
                'has_pincode': has_pincode,
                'has_address_details': has_address_words,
                'status': 'Complete' if (has_pincode or has_address_words) else 'Partial (Missing Pincode/Full Address)'
            }

        return False, {'error': 'Manufacturer / Packer name & address declaration not found'}

    # 7. RULE: Country of Origin (Mandatory Rule 6(1)(aa))
    def check_country_of_origin(self, texts, barcode_info=None):
        combined = self._join_texts(texts)
        origin_patterns = [
            r'(?:Country\s+of\s+Origin|Made\s+in|Product\s+of|Produced\s+in|Manufactured\s+in)\s*[:\s/-]*\s*([A-Za-z\s]+)',
            r'\bMade\s+in\s+India\b',
            r'\bProduct\s+of\s+India\b',
            r'\bOrigin\s*:\s*India\b'
        ]
        
        for pattern in origin_patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                country = match.group(1).strip() if match.groups() else 'India'
                return True, {
                    'country': country,
                    'is_india': 'india' in country.lower(),
                    'raw_text': match.group(0)
                }

        # Check barcode radar fallback if barcode confirms 890 GS1 India
        if barcode_info and barcode_info.get('is_made_in_india'):
            return True, {
                'country': 'India',
                'is_india': True,
                'source': 'GS1 India 890 Barcode Verified',
                'advisory': 'Printed text recommended alongside GS1 barcode'
            }

        return False, {'error': 'Country of Origin declaration missing on packaging'}

    # 8. RULE: Consumer Care Helpline / Grievance Redressal (Rule 6(1)(g))
    def check_consumer_care(self, texts):
        combined = self._join_texts(texts)
        
        # Look for toll-free numbers, emails, or care phrases
        phone_match = re.search(r'(?:1800\s*[-]?\s*\d{3}\s*[-]?\s*\d{3,4}|\+91\s*[-]?\s*\d{10}|\b\d{10,11}\b)', combined)
        email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', combined)
        care_keyword = bool(re.search(r'(?:consumer\s*care|customer\s*care|toll\s*free|grievance|feedback|helpline)', combined, re.IGNORECASE))

        if care_keyword or phone_match or email_match:
            return True, {
                'helpline_phone': phone_match.group(0) if phone_match else None,
                'helpline_email': email_match.group(0) if email_match else None,
                'has_care_keyword': care_keyword,
                'summary': f"Phone: {phone_match.group(0) if phone_match else 'N/A'}, Email: {email_match.group(0) if email_match else 'N/A'}"
            }

        return False, {'error': 'Consumer Grievance Helpline / Email declaration missing'}

    # 9. RULE: FSSAI License & Food Safety Logo
    def check_fssai(self, texts, is_food):
        if not is_food:
            return True, {'exempt': True, 'note': 'Non-food commodity (FSSAI license not applicable)'}

        combined = self._join_texts(texts)
        
        # 14-digit FSSAI number regex
        fssai_match = re.search(r'(?:FSSAI|Lic(?:ense)?\.?\s*No\.?)\s*[:\s/-]*\s*(\d{14})', combined, re.IGNORECASE)
        if not fssai_match:
            fssai_match = re.search(r'\b(1\d{13})\b', combined) # FSSAI license numbers start with 1 (10012..., 1152...)

        # Vegetarian / Non-Vegetarian declaration
        veg_declaration = bool(re.search(r'(?:100%\s*veg|vegetarian|green\s*dot|veg\s*logo)', combined, re.IGNORECASE))

        if fssai_match:
            lic_no = fssai_match.group(1)
            return True, {
                'fssai_license': lic_no,
                'is_valid_14_digit': len(lic_no) == 14,
                'is_veg_declared': veg_declaration,
                'raw_text': fssai_match.group(0)
            }

        return False, {'error': '14-digit FSSAI License Number missing on food commodity'}

    # 10. RULE: Generic Commodity Name (Rule 6(1)(b))
    def check_commodity_name(self, texts):
        combined = self._join_texts(texts)
        commodity_terms = [
            'instant noodles', 'noodles', 'biscuits', 'cookies', 'potato chips', 'wafers',
            'butter', 'pasteurised butter', 'milk', 'toned milk', 'iodized salt', 'salt',
            'liquid handwash', 'handwash', 'soap', 'toilet soap', 'toothpaste', 'dental cream',
            'namkeen', 'bhujia', 'mango drink', 'juice', 'honey', 'pure honey', 'detergent powder',
            'detergent', 'sunflower oil', 'edible oil', 'refined oil', 'coffee', 'instant coffee',
            'tea', 'green tea', 'soup', 'garam masala', 'spices', 'shampoo', 'hair oil',
            'face wash', 'body lotion', 'snack food', 'confectionery', 'packaged drinking water'
        ]
        
        combined_lower = combined.lower()
        for term in commodity_terms:
            if term in combined_lower:
                return True, {
                    'commodity_name': term.title(),
                    'detected_phrase': term
                }

        # Fallback to first high-confidence line
        if texts and len(texts) > 0:
            top_line = texts[0]['text']
            if len(top_line.split()) <= 5:
                return True, {'commodity_name': top_line, 'note': 'Inferred from label title'}

        return False, {'error': 'Common / Generic commodity name not clearly declared'}

    # 11. RULE: Barcode / QR Code Presence & GS1 Validation
    def check_barcode(self, image, barcode_radar_result=None):
        if barcode_radar_result and barcode_radar_result.get('detected'):
            return True, barcode_radar_result

        # Scan directly if radar result wasn't precomputed
        detected, radar_info = self.barcode_radar.scan_image(image)
        return detected, radar_info

    # 12. RULE: Language & Bilingual Standard (English / Hindi)
    def check_language(self, texts):
        combined = self._join_texts(texts)
        has_english = any(c.isascii() and c.isalpha() for c in combined)
        has_hindi = any('\u0900' <= c <= '\u097F' for c in combined)

        if has_english and has_hindi:
            return True, {
                'english': True,
                'hindi': True,
                'status': 'Bilingual (English + Hindi Devanagari) — Fully Compliant with Rule 9'
            }
        elif has_english:
            return True, {
                'english': True,
                'hindi': False,
                'status': 'English Only (Permissible national standard)'
            }
        elif has_hindi:
            return True, {
                'english': False,
                'hindi': True,
                'status': 'Hindi Devanagari Only (Permissible standard)'
            }

        return False, {'error': 'No recognizable Latin or Devanagari script detected'}

    # Commodity Category Classifier
    def classify_commodity_category(self, texts):
        combined = self._join_texts(texts).lower()
        
        food_keywords = [
            'biscuit', 'biscuits', 'chip', 'chips', 'chocolate', 'candy', 'snack', 'snacks',
            'namkeen', 'bhujia', 'milk', 'butter', 'ghee', 'cheese', 'curd', 'dahi', 'paneer',
            'juice', 'drink', 'beverage', 'tea', 'coffee', 'water', 'rice', 'wheat', 'atta',
            'flour', 'salt', 'sugar', 'oil', 'edible oil', 'masala', 'spices', 'soup', 'sauce',
            'ketchup', 'honey', 'jam', 'noodle', 'noodles', 'pasta', 'atta', 'maida', 'dal',
            'fssai', 'nutrition', 'calories', 'protein', 'fat', 'energy', 'maggi', 'parle', 'amul'
        ]
        
        personal_care_keywords = ['soap', 'shampoo', 'handwash', 'toothpaste', 'cream', 'lotion', 'face wash', 'dettol', 'colgate', 'lifebuoy']
        household_keywords = ['detergent', 'surf', 'cleaner', 'dishwash', 'bleach', 'harpic', 'vim', 'powder']
        pharma_keywords = ['tablets', 'capsules', 'syrup', 'ointment', 'vicks', 'paracetamol', 'iodine', 'bandage']

        if any(k in combined for k in pharma_keywords):
            return 'Pharmaceuticals & Healthcare', False
        elif any(k in combined for k in personal_care_keywords):
            return 'Personal Care & Cosmetics', False
        elif any(k in combined for k in household_keywords):
            return 'Household Care & Cleaning', False
        elif any(k in combined for k in food_keywords):
            return 'Food & Beverages', True
        
        return 'Packaged Commodity (General)', False

    # Orchestrate All 12 Checks
    def run_all_checks(self, texts, image):
        category_name, is_food = self.classify_commodity_category(texts)
        
        # 1. Barcode
        barcode_passed, barcode_info = self.check_barcode(image)
        
        # 2. MRP
        mrp_passed, mrp_info = self.check_mrp(texts)
        
        # 3. Net Qty
        weight_passed, weight_info = self.check_weight(texts)
        
        # 4. Unit Sale Price
        usp_passed, usp_info = self.check_unit_sale_price(texts, mrp_info, weight_info)
        
        # 5. Mfg Date
        mfg_passed, mfg_info = self.check_mfg_date(texts)
        
        # 6. Expiry
        expiry_passed, expiry_info = self.check_expiry(texts, is_food)
        
        # 7. Manufacturer
        mfr_passed, mfr_info = self.check_manufacturer(texts)
        
        # 8. Country of Origin
        origin_passed, origin_info = self.check_country_of_origin(texts, barcode_info)
        
        # 9. Consumer Care
        care_passed, care_info = self.check_consumer_care(texts)
        
        # 10. FSSAI
        fssai_passed, fssai_info = self.check_fssai(texts, is_food)
        
        # 11. Commodity Name
        comm_passed, comm_info = self.check_commodity_name(texts)
        
        # 12. Language
        lang_passed, lang_info = self.check_language(texts)

        results = {
            'mrp': (mrp_passed, mrp_info),
            'unit_sale_price': (usp_passed, usp_info),
            'weight': (weight_passed, weight_info),
            'mfg_date': (mfg_passed, mfg_info),
            'expiry': (expiry_passed, expiry_info),
            'manufacturer': (mfr_passed, mfr_info),
            'country_of_origin': (origin_passed, origin_info),
            'consumer_care': (care_passed, care_info),
            'fssai': (fssai_passed, fssai_info),
            'commodity_name': (comm_passed, comm_info),
            'barcode': (barcode_passed, barcode_info),
            'language': (lang_passed, lang_info),
        }

        return results, category_name, is_food, barcode_info
