---
title: Book Opportunity Scraping — Product Card
doc_id: CARD-book-opportunity-scraping
doc_type: product-card
verdict: merge
version: 0.1
date: 2026-10-08
status: ร่างเพื่อพิจารณา
owner: Product owner (Book Dev)
---

# Book Opportunity Scraping — Product Card

## 1. สรุปคุณค่าในหนึ่งประโยค

ชุดสคริปต์หลวม ๆ ที่เก็บราคา crypto/DeFi/FX/หุ้น/ตั๋วบิน, อันดับ SEO, เครื่องมือ AI และ "money opportunities" — งานเกือบทั้งหมดมี data product รายโดเมนเป็นเจ้าของแล้ว

## 2. ปัญหาและผู้ใช้เป้าหมาย

- ปัญหาที่ตั้งใจ: หาโอกาสทำเงินและติดตามตลาดหลายชนิดจากที่เดียว
- ผู้ใช้: operator คนเดียว

## 3. สิ่งที่ทำได้จริงตอนนี้

- สคริปต์ที่ root: `scrape_ai_tools.py`, `scrape_crypto_prices.py`, `scrape_defi_yields.py`, `scrape_exchange_rates.py`, `scrape_stock_prices.py`, `scrape_flight_prices.py`, `scrape_seo_rankings.py`, `scrape_fb_local.py`
- `opportunities/scrape_money_opportunities.py` ให้คะแนนโอกาสจาก HN/GitHub/search
- เขียน CSV แบบ atomic; test ใช้ fixture offline
- README ประกาศเองว่าเป็น Tier C "loose bag"

## 4. หลักฐานสถานะ

| รายการ | ค่า (ตรวจจาก repository) |
|---|---|
| Stack | Python |
| Commits | 16 (แรก 2026-07-09 → ล่าสุด 2026-10-01) |
| Source | 17 ไฟล์ / 5,888 บรรทัด |
| Tests | 17 ไฟล์ |
| CI | 1 workflow |
| Deploy config | ไม่มี |
| Live URL | ไม่มี |
| README | 88 บรรทัด (`book-opportunity-scraping`) |
| โครงสร้างซ้ำ (template family) | 1 repo ที่มี structure signature เดียวกัน |

## 5. คุณค่าและจุดต่าง

- เจ้าของโดเมนที่ถูกต้องมีอยู่แล้ว: `book-ai-tools-data`, `book-products/book-crypto-data`, `book-defi-data`, `book-fx-data`, `book-stock-data`, `book-flight-data`, `book-seo-data`
- การ synthesis "opportunity" ข้ามโดเมนถูกประกาศว่า retired แล้วใน roadmap data-scrapers

## 6. ช่องว่างสำคัญ

- `scrape_fb_local.py` เก็บอีเมลที่น่าจะเป็นข้อมูลส่วนบุคคลจากโพสต์ Facebook — README ระบุเองว่าเสี่ยง PDPA/Facebook ToS
- scrape หน้า search engine ด้วย User-Agent แบบเบราว์เซอร์ ไม่มี robots handling
- ซ้ำซ้อนกับ data product รายโดเมน

## 7. คำตัดสิน

**`merge`** — ซ้ำกับ canonical รายโดเมนข้างต้น ให้ย้าย parser/fixture ที่ยังมีค่าไปยัง repo เจ้าของ แล้ว archive repo นี้ และเลิกใช้ `scrape_fb_local.py` ทันทีโดยไม่ย้าย จะไม่เปลี่ยน verdict เพราะไม่มีความสามารถเฉพาะที่ repo อื่นไม่มี **[ต้องยืนยัน]** สำหรับ money-opportunity scoring

## 8. ขั้นต่อไป

1. หยุด cron ของ `scrape_fb_local.py` และลบข้อมูลอีเมลที่เก็บไว้ใน `data/` ตามนโยบาย PDPA (ต้องให้เจ้าของอนุมัติ)
2. เทียบ parser กับ repo เจ้าของรายโดเมนและย้ายเฉพาะส่วนที่ขาด
3. archive หลังอนุมัติ

## การอนุมัติ

| บทบาท | สถานะ | วันที่ | ลงนาม |
|---|---|---|---|
| Product owner (Book Dev) | รอพิจารณา | — | ________ |

## แหล่งข้อมูล

- `README.md`
- `PRODUCT.md`
- `scrape_fb_local.py`
- `opportunities/scrape_money_opportunities.py`
- `(solo-empire) repository-catalog/roadmaps/data-scrapers.yaml`
