import cv2
import numpy as np
import easyocr
import os
import re


class ProductOCR:
    """
    High-Accuracy OCR Engine tailored for Indian Packaged Goods with
    Multi-Scale Image Preprocessing and Indian Packaging Domain Normalizer.
    """
    def __init__(self):
        # Keep the model cache on the persistent volume in a container, so the
        # ~100 MB of weights are downloaded once instead of on every deploy.
        model_dir = os.environ.get('EASYOCR_MODULE_PATH')
        kwargs = {'gpu': False, 'verbose': False}
        if model_dir:
            os.makedirs(model_dir, exist_ok=True)
            kwargs['model_storage_directory'] = model_dir
            kwargs['download_enabled'] = True
        self.reader = easyocr.Reader(['en'], **kwargs)

    def preprocess_variants(self, image):
        """
        Creates multiple optimized image variants to maximize OCR detection on shiny,
        reflective, curved, or micro-font packaging.
        """
        h, w = image.shape[:2]
        
        # 1. Upscale if image is low-resolution (< 1200px max dimension)
        scale_factor = 1.0
        if max(h, w) < 1200:
            scale_factor = 1200.0 / max(h, w)
            image_scaled = cv2.resize(image, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
        else:
            image_scaled = image

        gray = cv2.cvtColor(image_scaled, cv2.COLOR_BGR2GRAY)

        # 2. Variant A: CLAHE (Contrast Limited Adaptive Histogram Equalization) - Removes plastic glare
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        clahe_enhanced = clahe.apply(gray)
        clahe_color = cv2.cvtColor(clahe_enhanced, cv2.COLOR_GRAY2BGR)

        # 3. Variant B: Unsharp Masking (Sharpen micro-fonts on ₹5 sachets)
        gaussian_blur = cv2.GaussianBlur(gray, (0, 0), 2.0)
        unsharp = cv2.addWeighted(gray, 1.6, gaussian_blur, -0.6, 0)
        unsharp_color = cv2.cvtColor(unsharp, cv2.COLOR_GRAY2BGR)

        # 4. Variant C: Bilateral Denoised Grayscale (smooths textures while keeping edges sharp)
        bilateral = cv2.bilateralFilter(gray, 9, 75, 75)
        bilateral_color = cv2.cvtColor(bilateral, cv2.COLOR_GRAY2BGR)

        return [
            ('clahe', clahe_color),
            ('unsharp', unsharp_color),
            ('bilateral', bilateral_color),
            ('original', image_scaled)
        ]

    def normalize_indian_packaging_text(self, raw_text):
        """
        Domain-Specific Post-Processor: Fixes common OCR confusions specific
        to Indian packaging declarations under Legal Metrology Rules.
        """
        if not raw_text:
            return ""

        text = raw_text.strip()

        # Fix Currency & MRP typos
        text = re.sub(r'\bM[\.\s]*R[\.\s]*P[\.\s]*[:\s=]*', 'MRP ', text, flags=re.IGNORECASE)
        text = re.sub(r'\bM[\.\s]*R[\.\s]*P\b', 'MRP', text, flags=re.IGNORECASE)
        text = re.sub(r'[\?Fz]\s*(\d+(?:\.\d{1,2})?)', r'₹\1', text) # ?50.00 -> ₹50.00
        text = re.sub(r'\bRs[\.\s]*(\d+)', r'₹\1', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(Incl|Inclu|Inclusive)[\.\s]*(of|ot)[\.\s]*(all|al)[\.\s]*(taxes|tax)\b', 'incl. of all taxes', text, flags=re.IGNORECASE)

        # Fix Unit Sale Price (USP) typos
        text = re.sub(r'\bU[\.\s]*S[\.\s]*P[\.\s]*[:\s=]*', 'USP ', text, flags=re.IGNORECASE)
        text = re.sub(r'\bUnit[\.\s]*Sale[\.\s]*Price\b', 'Unit Sale Price', text, flags=re.IGNORECASE)

        # Fix Net Weight / Net Quantity typos
        text = re.sub(r'\bN[ce]t[\.\s]*(Wt|Weight|Qty|Quantity|Cont|Contents)[\.\s]*[:\s=]*', 'Net Wt: ', text, flags=re.IGNORECASE)
        text = re.sub(r'(\d+)\s*(g|gm|gms|kg|ml|l|ltr|litre|liter|mg)\b', r'\1 \2', text, flags=re.IGNORECASE)

        # Fix Manufacturing / Packing Date typos
        text = re.sub(r'\b(Mfd|Mfg|Mid|Mft|Mfq|Manuf|Manufactured)[\.\s]*(Date|Dt|On)?[\.\s]*[:\s=]*', 'Mfd Date: ', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(Pkd|Pkg|Packed)[\.\s]*(Date|Dt|On)?[\.\s]*[:\s=]*', 'Packed Date: ', text, flags=re.IGNORECASE)

        # Fix Expiry / Best Before typos
        text = re.sub(r'\b(Exp|Expiry|Exd|Exo)[\.\s]*(Date|Dt)?[\.\s]*[:\s=]*', 'Exp Date: ', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(Best[\.\s]*Before|Use[\.\s]*By|Used[\.\s]*By|BB)[\.\s]*[:\s=]*', 'Best Before: ', text, flags=re.IGNORECASE)

        # Fix FSSAI typos
        text = re.sub(r'\b(FSSA1|FSSAI|FSSAL|FSAI)[\.\s]*(Lic|License|Licence|No)?[\.\s]*[:\s=]*', 'FSSAI Lic. No. ', text, flags=re.IGNORECASE)

        # Fix Country of Origin & Manufacturer typos
        text = re.sub(r'\b(Made|Product|Origin)[\.\s]*(in|of)[\.\s]*(India|IND)\b', 'Made in India', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(Mfg|Mfd|Packed|Marketed|Manufactured)[\.\s]*(by|at|for)[\.\s]*[:\s=]*', r'\1 by: ', text, flags=re.IGNORECASE)

        # Fix Consumer Care Helpline typos
        text = re.sub(r'\b(Customer|Consumer)[\.\s]*(Care|Support|Helpline|Feedback)[\.\s]*[:\s=]*', 'Consumer Care: ', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(Toll[\s-]*Free)[\.\s]*[:\s=]*', 'Toll Free: ', text, flags=re.IGNORECASE)

        return text

    def extract_text(self, image_path_or_array):
        """
        Runs Multi-Pass OCR with image enhancement and deduplication.
        Returns list of dicts: [{'text': str, 'confidence': float, 'bbox': list, 'normalized': str}]
        """
        if isinstance(image_path_or_array, str):
            image = cv2.imread(image_path_or_array)
        else:
            image = image_path_or_array

        if image is None:
            return []

        variants = self.preprocess_variants(image)
        extracted_dict = {}  # key: cleaned text, value: item dict

        # Run OCR over CLAHE and Unsharp variants
        for variant_name, img_var in variants[:2]:
            try:
                results = self.reader.readtext(img_var, detail=1, paragraph=False)
                for (bbox, text, conf) in results:
                    cleaned = text.strip()
                    if conf > 0.15 and len(cleaned) > 1:
                        normalized = self.normalize_indian_packaging_text(cleaned)
                        key = re.sub(r'\s+', ' ', normalized.lower().strip())
                        
                        # Keep highest confidence entry
                        if key not in extracted_dict or conf > extracted_dict[key]['confidence']:
                            extracted_dict[key] = {
                                'text': normalized,
                                'raw_text': cleaned,
                                'confidence': float(conf),
                                'bbox': [[int(p[0]), int(p[1])] for p in bbox],
                                'variant': variant_name
                            }
            except Exception as e:
                print(f"[OCR] Error processing variant {variant_name}: {e}")

        # If sparse results, fallback to original raw image
        if len(extracted_dict) < 3:
            try:
                results_fallback = self.reader.readtext(image, detail=1, paragraph=False)
                for (bbox, text, conf) in results_fallback:
                    cleaned = text.strip()
                    if conf > 0.10 and len(cleaned) > 1:
                        normalized = self.normalize_indian_packaging_text(cleaned)
                        key = re.sub(r'\s+', ' ', normalized.lower().strip())
                        if key not in extracted_dict or conf > extracted_dict[key]['confidence']:
                            extracted_dict[key] = {
                                'text': normalized,
                                'raw_text': cleaned,
                                'confidence': float(conf),
                                'bbox': [[int(p[0]), int(p[1])] for p in bbox],
                                'variant': 'original_fallback'
                            }
            except Exception:
                pass

        final_list = list(extracted_dict.values())
        # Sort by vertical position (Y-coordinate of top-left bbox)
        final_list.sort(key=lambda x: x['bbox'][0][1] if x.get('bbox') else 0)
        return final_list


if __name__ == "__main__":
    ocr = ProductOCR()
    print("OCR Engine Ready.")
    sample_text = "M.R.P. Rs. 20.00 (Incl. of all taxes) Net Wt: 70g Mfd Date: 05/2026 FSSA1 Lic No 10012011000168 Made in India"
    print("Test Normalization:\nInput: ", sample_text)
    norm = ocr.normalize_indian_packaging_text(sample_text)
    print("Output:", norm.encode('ascii', errors='replace').decode())
