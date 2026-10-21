# PS 26034 - Drawbacks & Solutions

---

## 15 Major Drawbacks & How to Fix Them

---

### DRAWBACK 1: OCR Fails on Bad Quality Images

**Problem:** Product photos taken in poor lighting, blurry, or angled. OCR can't extract text correctly.

**Solution:**
- Add image quality check before OCR
- Ask user to retake if blurry
- Use multiple angles (front, back, top)
- PaddleOCR handles most Indian fonts well
- Confidence score for each extracted field

---

### DRAWBACK 2: Different Product Languages

**Problem:** Products in Tamil, Telugu, Hindi, Bengali. OCR only reads English.

**Solution:**
- Use multilingual OCR (Google Vision API supports 100+ languages)
- Focus on key fields: MRP always has ₹ symbol
- Dates always in DD/MM/YYYY format
- Numbers are universal
- Start with English + Hindi, add more later

---

### DRAWBACK 3: MRP Format Varies

**Problem:** Some print "MRP Rs. 10", some "Maximum Retail Price ₹10.00", some "MRP: 10/-"

**Solution:**
- Create regex patterns for all formats
- Pattern 1: MRP + ₹ + number
- Pattern 2: MRP Rs. + number
- Pattern 3: MRP: + number
- Pattern 4: Maximum Retail Price + number
- Test on 100+ products to catch all variations

---

### DRAWBACK 4: Products Without Expiry Date

**Problem:** Non-food items (soap, shampoo) don't have expiry. System flags as violation.

**Solution:**
- Check product category first
- Food items: Expiry required
- Non-food items: Expiry not required
- Create category list:
  - Food: Biscuits, chips, milk, etc.
  - Non-food: Soap, detergent, cosmetics
- Only check expiry for food items

---

### DRAWBACK 5: Ingredient List Hard to Parse

**Problem:** Ingredients in small font, multiple lines, hard to read.

**Solution:**
- Use high-resolution OCR
- Focus on keyword detection: "Ingredients:", "Contents:"
- Check if list exists, not full parsing
- Severity: Minor violation (not critical)
- Flag for human review if uncertain

---

### DRAWBACK 6: Barcode Detection Difficult

**Problem:** Barcodes on curved surfaces, damaged, or partially visible.

**Solution:**
- Use barcode detection library (pyzbar, OpenCV)
- Check if barcode region exists
- Don't need to read barcode, just detect presence
- If barcode area detected but unreadable = warning
- If no barcode detected = violation

---

### DRAWBACK 7: Small Products Have Tiny Text

**Problem:** Small packets (₹5 shampoo) have text <1mm height. Hard to read.

**Solution:**
- Increase image resolution
- Crop and enhance specific regions
- Use super-resolution if needed
- Accept that some fields may be unreadable
- Flag as "Unable to verify" rather than violation

---

### DRAWBACK 8: Fake MRP Stickers

**Problem:** Seller puts fake MRP sticker over original. AI reads fake MRP.

**Solution:**
- Detect sticker presence (edge detection)
- Check font consistency across package
- Compare MRP font with other text
- Flag if MRP looks different from rest
- Severity: HIGH - likely tampering

---

### DRAWBACK 9: Multi-Pack Confusion

**Problem:** "Buy 1 Get 1 Free" packs have different MRP logic. System confused.

**Solution:**
- Detect "Combo", "Pack of", "Family Pack" text
- Check net quantity vs MRP ratio
- If quantity high but MRP low = suspicious
- Flag for manual review
- Not a violation, just unusual

---

### DRAWBACK 10: Government Rules Change

**Problem:** Legal Metrology rules updated. System uses old rules.

**Solution:**
- Store rules in database, not hardcoded
- Update rules when government notifies
- Version control for rules
- Alert when rules are old
- Easy to update without code change

---

### DRAWBACK 11: Regional Products Not in Database

**Problem:** Local products (pickle, papad) don't follow standard formats.

**Solution:**
- Start with branded products (easy)
- Add local products gradually
- Accept partial compliance for small manufacturers
- Focus on major violations only
- Community contribution for local products

---

### DRAWBACK 12: Mobile Camera Quality Varies

**Problem:** Cheap phones have poor cameras. Photos not clear enough.

**Solution:**
- Minimum resolution requirement (5MP)
- Image quality check before processing
- Suggest better lighting
- Allow multiple attempts
- Cloud-based enhancement if needed

---

### DRAWBACK 13: Products in Plastic Wrapping

**Problem:** Reflections from plastic wrapping affect OCR accuracy.

**Solution:**
- Use polarization filter (advanced)
- Take photo at angle to reduce reflection
- Enhance image to reduce glare
- Accept some OCR errors
- Confidence scoring for uncertain fields

---

### DRAWBACK 14: No Internet in Rural Areas

**Problem:** Farmers/small shops don't have internet. Can't use app.

**Solution:**
- Offline mode for basic checks
- Cache OCR model locally
- Store results sync when online
- SMS-based verification option
- works without internet for core features

---

### DRAWBACK 15: Lawyers Challenge Accuracy

**Problem:** If system wrong, companies sue for defamation.

**Solution:**
- Never claim 100% accuracy
- Show confidence score
- Add disclaimer: "For reference only"
- Suggest human verification for legal action
- Insurance for false claims

---

## QUICK FIX SUMMARY

| # | Drawback | Fix Difficulty | Impact |
|---|----------|----------------|--------|
| 1 | Bad image quality | Easy | Medium |
| 2 | Multiple languages | Medium | High |
| 3 | MRP format varies | Easy | High |
| 4 | No expiry on non-food | Easy | Medium |
| 5 | Ingredients hard to parse | Medium | Low |
| 6 | Barcode detection | Easy | Low |
| 7 | Small text | Medium | Medium |
| 8 | Fake MRP stickers | Hard | High |
| 9 | Multi-pack confusion | Easy | Low |
| 10 | Rules change | Easy | High |
| 11 | Local products | Medium | Low |
| 12 | Camera quality | Easy | Medium |
| 13 | Plastic reflections | Medium | Low |
| 14 | No internet | Medium | Medium |
| 15 | Legal challenges | Hard | High |

---

## TOP 5 PRIORITIES

```
MUST FIX:
1. MRP format variations (Easy)
2. Non-food expiry check (Easy)
3. Rules in database (Easy)
4. Language support (Medium)
5. Fake sticker detection (Hard)

ALL OTHERS: Can handle later
```

---

## FINAL ANSWER

```
PS 26034 has 15 drawbacks.
All are solvable.
Most are EASY to fix.
5 must be fixed for demo.
10 can be handled post-hackathon.

THIS IS STILL THE BEST PROBLEM TO PICK.
```
