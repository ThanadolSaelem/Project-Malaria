# TLP:AMBER report — สัญญา (contract) ระหว่าง Tiel กับตัวประกอบรายงาน

เป้าหมาย: ให้รายงาน `.docx` ออกมา **ตรงฟอร์แมตบ้าน สกมช.** ทุกครั้ง โดย **โมเดลไม่ต้องรู้เรื่อง format เลย**

## สถาปัตยกรรม (สำคัญ — อ่านก่อน)

```
Tiel  ──produces──►  content.json  +  รูปหลักฐาน (pipeline/evidence/*.png)
                          │
                          ▼
            python3 assemble.py content.json -o report.docx
                          │  (format ทั้งหมดมาจาก template.docx)
                          ▼
                   report.docx  (ฟอร์แมตบ้าน สกมช.)
```

- **โมเดลผลิตแค่ "เนื้อหา" (JSON) + "รูป"** — ไม่แตะ font/ขอบ/heading/ตาราง
  (เหตุผล: เคยให้โมเดลประกอบ docx เอง ได้ Times New Roman 14KB ไม่มีรูป — เปราะเกินไป)
- **format เป็น deterministic** มาจาก `template.docx` (header/footer/badge TLP + ฝัง Sarabun)
  และ `build_report.py` (engine จาก skill `ncsa-tlp-report`)
- ตัวประกอบรัน **Python** (ต้องมี `Pillow` สำหรับ `figure`) — รันฝั่งที่มี Python
  (Mac/คอนเทนเนอร์) ไม่ใช่ใน sandbox ของ Tiel ที่ Python น้อย

## วิธีรัน

**โหมดอัตโนมัติเต็ม (แบบ C) — Tiel ทำเองในคอนเทนเนอร์:**
mount ไว้ให้แล้วใน `hexstrike-server` (ดู docker-compose):
`/reporting` (โค้ด+template, read-only) · `/evidence` (รูป) · `/reports` (output, เขียนได้)
```bash
# Tiel สั่งเองผ่าน command tool:
python3 /reporting/assemble.py /reports/<name>.json -o /reports/<name>.docx
```
ได้ `.docx` โผล่ที่ `pipeline/reports/` บน Mac ทันที (ไม่ต้อง copy-paste)

**โหมดแมนนวล (รันบน Mac):**
```bash
cd pipeline/reporting
python3 assemble.py <content.json> -o /path/to/report.docx
#   --template <file>       override template.docx
#   --evidence-dir <dir>    override โฟลเดอร์รูป (ดีฟอลต์ ../evidence)
```
ต้องมี `Pillow` ถ้ามี figure จริง (คอนเทนเนอร์ลงให้แล้ว; บน Mac: `pip install pillow`)

รูปที่อ้างใน JSON แต่ยังไม่มีไฟล์ → assemble.py ใส่ **placeholder กรอบ** ให้ (ไม่ fail)
และพิมพ์ `WARN:` บอกว่ารูปไหนยังขาด — เติมรูปแล้วรันซ้ำได้

ไฟล์ตัวอย่าง: `sample_report.json` (ลองรันได้เลย — รูปจะเป็น placeholder)

⚠️ โหมด C ไม่มีจังหวะให้คนตรวจก่อนประกอบ → **ตรวจ redaction ที่ไฟล์ .docx ผลลัพธ์ก่อนส่งออกนอกเสมอ**

## สคีมา JSON

```jsonc
{
  "fig_numbering": "continuous",        // "continuous" (ดีฟอลต์: รูปเลข 1..N ทั้งฉบับ) หรือ "per_section"
  "titles": ["บรรทัดชื่อ 1 (ตัวหนา)", "บรรทัดชื่อ 2"],
  "date": "วันที่จัดทำรายงาน 19 ตุลาคม พ.ศ. 2569",
  "blocks": [ ... ]                     // เรียงตามลำดับที่จะปรากฏในรายงาน
}
```

`blocks` — แต่ละอันเป็น object มี `type` ตามนี้:

| type | fields | ใช้ทำ |
|---|---|---|
| `heading` | `text`, `new_page?` | หัวข้อหลัก "1. / 2. / 3." (ตัวหนา) |
| `sub` | `text`, `new_page?` | หัวข้อย่อย "2.1" |
| `plain` | `text`, `tab?` | ย่อหน้าปกติ (justified, ย่อหน้าแรกมี tab) |
| `bullet` | `text` | ข้อ "•" |
| `dash` | `text` | ข้อย่อย "-" |
| `numbered` | `n`, `text` | ข้อ "1) 2)" |
| `lead` | `label`, `text` | ป้ายตัวหนา + ข้อความ (เช่น "ข้อจำกัด: ...") |
| `table` | `rows`, `widths?`, `header?` | ตาราง (หัวแถวแรกเทา ตัวหนา). `widths` รวม 9071 twips; ไม่ใส่ = แบ่งเท่ากัน |
| `figure` | `image`, `caption`, `width_cm?`, `border?` | รูปกรอบ 16 ซม. + caption "รูปภาพที่ N". `image` = ชื่อไฟล์ใน evidence/ |
| `placeholder` | `caption` | กรอบว่างรอแนบรูป (นับเลขรูปด้วย) |
| `status` | `value` | บรรทัด "สถานะ: ..." (Tested/Inconclusive/Not Tested/Not Confirmed) |
| `code` | `lines[]`, `sz?` | กล่อง monospace (เช่น tree โครงสร้างไฟล์) |
| `note` | `text` | "หมายเหตุ:" + ย่อหน้า |
| `signature` | `date`, `unit?` | ปิดท้าย: หน่วยงาน + วันที่ |
| `page_break` / `spacer` | — | ขึ้นหน้าใหม่ / เว้นบรรทัด |

## Checklist เนื้อหา (โมเดลต้องทำครบ)

- **โครงมาตรฐาน (มัลแวร์):** 1 ขอบเขตและลักษณะการตรวจสอบ (ที่มา/วิธี/ข้อจำกัด) ·
  2 ผลการตรวจสอบ (2.x: ข้อมูลไฟล์+hash, พฤติกรรม, endpoint/IOC, C2/ส่งออก + `status`) ·
  3 บทสรุป · `note` · `signature`
- **ทุก finding ต้องมีหลักฐาน:** finding เชิงเทคนิค = มี `figure` (รูปโค้ด/ผลเครื่องมือ) และ/หรือ `table`
  (IOC/endpoint/hash) ประกอบเสมอ อย่าเล่าลอย ๆ
- **อ้างรูปในเนื้อก่อนเสมอ:** เขียน "ตามรูปภาพที่ N" (หรือช่วง "ตามรูปภาพที่ 1 - 2") ก่อนบล็อก `figure`
  และ N ต้องตรงกับลำดับ continuous
- **ตาราง IOC:** endpoint/โดเมน/IP/hash ใส่เป็น `table` ไม่ใช่ร้อยเรียงในย่อหน้า
- **ลงท้ายด้วย verdict ใน 3. บทสรุป** (ตาม section "Threat verdict" ใน system prompt)

## รูปหลักฐาน (evidence) — ได้มาจากไหน

เซฟลง `pipeline/evidence/` (→ bind mount `/evidence`) แล้วอ้างด้วยชื่อไฟล์ใน `image`:

| ชนิดหลักฐาน | Tiel ทำยังไง |
|---|---|
| หน้าเว็บ (เว็บมิจฉาชีพ/phishing/login) | REA headless Chromium ถ่าย screenshot ผ่าน CDP → เซฟ .png |
| โค้ด/strings/terminal/decompile (ส่วนใหญ่) | เอา **ข้อความที่ได้** render เป็น PNG (HTML→Chromium หรือ text-to-image) ไม่ใช่จับจอ |
| หน้าต่าง GUI ของโปรแกรม | ❌ ไม่มีจอใน container (และ .exe ไม่รัน — static) → ใช้ `placeholder` ให้คนแนบภายหลัง |

ตั้งชื่อไฟล์สื่อความ เช่น `fig_pyinstaller_tree.png`, `fig_decompiled_token.png`

## กฎ redaction (บังคับ — เอกสารตั้งรับ)

- **ปิดบังในรูปและข้อความ:** credential, token/JWT, เบอร์โทร, อีเมลผู้แจ้ง, URL/path ตรงของระบบที่ยังไม่ถูกแก้
  (ส่งค่าจริงให้เจ้าของระบบผ่านช่องทางควบคุม ไม่ใส่ในรายงาน)
- รายงานนี้เป็น **เอกสารตั้งรับ**: บอก finding + ข้อเสนอแก้ไข ไม่ใส่ขั้นตอน exploit/วิธี bypass/path เข้าถึงที่ใช้ได้จริง
- ไม่มีลิงก์ไป workspace AI บุคคลที่สาม/คลาวด์ส่วนตัว

## กฎการเขียน (house style)

- ประโยคราชการสมบูรณ์ ไม่ใช่ note สั้น ๆ; นำลิสต์ด้วยประโยค "... มีดังนี้"
- ศัพท์อังกฤษตามหลังไทย Proper Case ในวงเล็บ: การข้ามการยืนยันตัวตน (Authentication Bypass)
- วันที่ พ.ศ. เว้นวรรค: "19 ตุลาคม พ.ศ. 2569"
- **ห้ามใช้ em dash (—)** ทุกที่ ใช้คำ/วงเล็บ/"-" แทน
- status: Tested / Inconclusive / Not Tested / Not Confirmed (+ เหตุผลสั้น)

## หมายเหตุ engine

- `build_report.py` = engine จาก skill `anthropic-skills:ncsa-tlp-report` (อย่าแก้ตรรกะ format เอง
  ถ้า skill อัปเดต ให้ sync ไฟล์นี้ตาม)
- `template.docx` = เฉลยที่ strip เนื้อหา/รูป body ออก เหลือ header/footer/badge + ฝังเฉพาะ Sarabun (≈250KB)
