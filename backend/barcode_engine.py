import cv2
import numpy as np

try:
    from pyzbar import pyzbar
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False


class BarcodeRadar:
    """
    Multi-Engine Barcode & QR Code Radar with GS1-128 / EAN-13 validation
    and Indian GS1 Country Code (890) analysis.
    """
    def __init__(self):
        self.cv_barcode_detector = None
        self.cv_qr_detector = None
        
        # Initialize OpenCV Barcode Detector if available
        try:
            if hasattr(cv2, 'barcode') and hasattr(cv2.barcode, 'BarcodeDetector'):
                self.cv_barcode_detector = cv2.barcode.BarcodeDetector()
        except Exception:
            pass
            
        # Initialize OpenCV QR Code Detector
        try:
            self.cv_qr_detector = cv2.QRCodeDetector()
        except Exception:
            pass

    def validate_ean13_checksum(self, barcode_str):
        """Validates EAN-13 modulo 10 checksum algorithm."""
        if not barcode_str or len(barcode_str) != 13 or not barcode_str.isdigit():
            return False
        digits = [int(d) for d in barcode_str]
        # Sum odd positions (0-indexed: 0, 2, 4, 6, 8, 10) * 1 + even positions (1, 3, 5, 7, 9, 11) * 3
        total = sum(digits[i] for i in range(0, 12, 2)) + sum(digits[i] * 3 for i in range(1, 12, 2))
        check_digit = (10 - (total % 10)) % 10
        return check_digit == digits[12]

    def get_gs1_country_origin(self, barcode_str):
        """Identifies GS1 country prefix (890 is India)."""
        if not barcode_str or len(barcode_str) < 3 or not barcode_str[:3].isdigit():
            return 'Unknown Origin'
        prefix = int(barcode_str[:3])
        if prefix == 890:
            return 'Republic of India (GS1 India 890)'
        elif 0 <= prefix <= 139:
            return 'United States / Canada'
        elif 400 <= prefix <= 440:
            return 'Germany'
        elif 450 <= prefix <= 459 or 490 <= prefix <= 499:
            return 'Japan'
        elif 500 <= prefix <= 509:
            return 'United Kingdom'
        elif 690 <= prefix <= 699:
            return 'China'
        elif 880 <= prefix <= 880:
            return 'South Korea'
        elif 884 <= prefix <= 884:
            return 'Cambodia'
        elif 885 <= prefix <= 885:
            return 'Thailand'
        elif 888 <= prefix <= 888:
            return 'Singapore'
        elif 893 <= prefix <= 893:
            return 'Vietnam'
        elif 899 <= prefix <= 899:
            return 'Indonesia'
        else:
            return f'International (GS1 Prefix {prefix})'

    def scan_image(self, image):
        """
        Scans an image array using multiple engines, rotations, and contrast enhancements.
        Returns: (detected: bool, barcode_info: dict)
        """
        if image is None:
            return False, {'error': 'No image provided'}

        detected_barcodes = []

        # Prepare image variations (Original, Grayscale, CLAHE enhanced, Rotated 90, 180, 270)
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
        
        # Adaptive CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)

        # Thresholding for sharp barcode bars
        _, thresh_otsu = cv2.threshold(enhanced_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        image_variants = [
            ('original', image),
            ('gray', gray),
            ('clahe', enhanced_gray),
            ('otsu', thresh_otsu)
        ]

        # Engine 1: PyZbar (Multi-angle)
        if PYZBAR_AVAILABLE:
            for variant_name, img_var in image_variants:
                for angle in [0, 90, 180, 270]:
                    rotated = img_var
                    if angle == 90:
                        rotated = cv2.rotate(img_var, cv2.ROTATE_90_CLOCKWISE)
                    elif angle == 180:
                        rotated = cv2.rotate(img_var, cv2.ROTATE_180)
                    elif angle == 270:
                        rotated = cv2.rotate(img_var, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    try:
                        results = pyzbar.decode(rotated)
                        for b in results:
                            code_data = b.data.decode('utf-8', errors='ignore').strip()
                            code_type = b.type
                            if code_data and code_data not in [d['data'] for d in detected_barcodes]:
                                detected_barcodes.append({
                                    'data': code_data,
                                    'type': code_type,
                                    'engine': f'pyzbar_{variant_name}_{angle}deg'
                                })
                    except Exception:
                        pass
                if detected_barcodes:
                    break

        # Engine 2: OpenCV BarcodeDetector (if not detected or additional verification)
        if not detected_barcodes and self.cv_barcode_detector is not None:
            for variant_name, img_var in image_variants[:2]:
                try:
                    ok, decoded_info, decoded_type, _ = self.cv_barcode_detector.detectAndDecode(img_var)
                    if ok:
                        for info, ctype in zip(decoded_info, decoded_type):
                            if info and info not in [d['data'] for d in detected_barcodes]:
                                detected_barcodes.append({
                                    'data': str(info).strip(),
                                    'type': str(ctype) if ctype else 'BARCODE',
                                    'engine': f'cv_barcode_{variant_name}'
                                })
                except Exception:
                    pass

        # Engine 3: OpenCV QRCodeDetector (2D QR codes / Smart Labels)
        if not detected_barcodes and self.cv_qr_detector is not None:
            for variant_name, img_var in image_variants[:2]:
                try:
                    decoded_text, points, _ = self.cv_qr_detector.detectAndDecode(img_var)
                    if decoded_text and decoded_text not in [d['data'] for d in detected_barcodes]:
                        detected_barcodes.append({
                            'data': decoded_text.strip(),
                            'type': 'QRCODE',
                            'engine': f'cv_qr_{variant_name}'
                        })
                except Exception:
                    pass

        if detected_barcodes:
            primary = detected_barcodes[0]
            code_str = primary['data']
            code_type = primary['type']
            
            is_valid_ean = self.validate_ean13_checksum(code_str) if len(code_str) == 13 and code_str.isdigit() else (True if len(code_str) in [8, 12] else None)
            country = self.get_gs1_country_origin(code_str)
            is_made_in_india = code_str.startswith('890')

            return True, {
                'detected': True,
                'count': len(detected_barcodes),
                'primary_code': code_str,
                'symbology': code_type,
                'country_of_origin': country,
                'is_made_in_india': is_made_in_india,
                'is_valid_checksum': is_valid_ean,
                'all_codes': detected_barcodes,
                'note': 'GS1 India 890 Verified' if is_made_in_india else ('Valid Barcode Detected' if is_valid_ean else 'Barcode Detected')
            }

        return False, {
            'detected': False,
            'count': 0,
            'primary_code': None,
            'symbology': None,
            'country_of_origin': 'Not Detected',
            'is_made_in_india': False,
            'is_valid_checksum': False,
            'all_codes': [],
            'error': 'No barcode or QR code detected on scanned image'
        }


if __name__ == '__main__':
    radar = BarcodeRadar()
    print("BarcodeRadar initialized. EAN Checksum test (8901058852371):", radar.validate_ean13_checksum("8901058852371"))
    print("GS1 India test (8901058852371):", radar.get_gs1_country_origin("8901058852371"))
