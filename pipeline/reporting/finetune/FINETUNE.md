# Finetune Tiel — LoRA adapter สำหรับ "content/style" ของรายงาน TLP:AMBER

เป้าหมาย: สอน Tiel ให้ **ผลิต content JSON ฟอร์แมตบ้าน** (ภาษาราชการ, โครงหัวข้อ, เขียน JSON
ตาม schema, อ้างรูป, redact) โดยไม่ต้อง prompt ยาว — **ไม่ใช่สอน format** (format = template + assemble.py)

## กฎเหล็ก
- เทรนเพื่อ **content/style เท่านั้น** ห้ามเทรนให้โมเดลจัด format/สร้าง .docx (ย้อนไปหาความเปราะ)
- **TLP:AMBER = sensitive** → เตรียม dataset **บนเครื่องคุณเอง (local)** ห้ามอัป gold จริงขึ้น cloud
- เป็น **LoRA adapter** → โหลดเฉพาะตอนทำรายงาน, วิเคราะห์/tool-call รัน Tiel เปล่า → core ไม่เปลี่ยน

## ขั้นตอน (ทำตามลำดับ)

### 1. เตรียม "ฝั่ง output" — gold .docx → content JSON  ← ทำได้เลย (local, Mac)
```bash
# วาง gold 13 ฉบับไว้โฟลเดอร์เดียว (local เท่านั้น) แล้ว:
python3 docx_to_contentjson.py gold_reports/ -O gold_json/
```
`docx_to_contentjson.py` ตัดรูป/ฟอนต์ที่ฝังทิ้ง เหลือ text+โครง → ได้ JSON เล็ก ๆ ต่อไฟล์
**เป็น best-effort — ต้อง review/แก้** จุดที่รู้ว่าต้องแก้เอง:
- `lead` (เช่น "ข้อจำกัดของขอบเขต:") ตอนนี้ออกมาเป็น `plain` → เปลี่ยน type + แยก label/text
- `note` body เป็น placeholder → ใส่เนื้อหาหมายเหตุจริง
- `figure.image` เป็น `<ใส่ชื่อไฟล์รูป>` → ไม่ต้องแก้ก็ได้ (ตอนเทรน caption สำคัญกว่าชื่อไฟล์)
- `signature` → ใส่ date

### 2. เตรียม "ฝั่ง input" — findings brief ต่อเคส
แต่ละเคสต้องมี input ที่จับคู่กับ output JSON. รูปแบบที่แนะนำ (สอน "เรียบเรียง" ตรงเป้า):
```
input  = ข้อเท็จจริงย่อ (เป้าหมาย, hash, endpoint/IOC, finding list, รูปแต่ละอันแสดงอะไร)
output = content JSON เต็ม (จากข้อ 1)
```
วางคู่กันเป็น `dataset/<case>/facts.md` + `dataset/<case>/content.json`

### 3. ประกอบ training set (ขั้นถัดไป — ยังไม่ได้ทำ)
`make_dataset.py` (จะสร้างให้เมื่อยืนยันรูปแบบ input): แปลงทุกเคสเป็น jsonl แบบ chat/sharegpt
พร้อม **decompose** 1 ฉบับ → หลายตัวอย่าง (ทั้งฉบับ + ราย section + ราย finding→block)
→ 13 ฉบับ ≈ 200-260 ตัวอย่าง

### 4. เทรน (เครื่อง GPU — ไม่ใช่ Mac)
- ต้องมี **base weights HF/safetensors** ของ Cyber-Tiel (GGUF เทรนตรงไม่ได้)
- เช่า GPU (A100 80GB / H100) → QLoRA 4-bit; toolchain: LLaMA-Factory หรือ axolotl
- **MoE caveat**: แปะ LoRA ที่ attention (q/k/v/o) พอ — อย่ายุ่ง expert/router
- hyperparams งาน style แคบ: **r=8-16, alpha 16-32, lr ~1e-4, 1-3 epochs**
- **mix ตัวอย่างงานเดิม ~10-20%** (วิเคราะห์/tool-call) กัน catastrophic forgetting

### 5. วัดผล (อย่าเชื่อ loss)
- กัน gold 1-2 ฉบับเป็น held-out → ให้ LoRA สร้าง JSON → **diff กับ gold** + เช็ก behavioral
  (อ้างรูปครบ? redact ครบ? โครงถูก?) และ **เทียบกับ baseline few-shot** — ไม่ชนะชัด = ยังไม่คุ้ม

### 6. เสิร์ฟ
convert adapter → GGUF → `llama-server ... --lora report-style.gguf` (โหลดเฉพาะงานรายงาน)

## ไฟล์ในโฟลเดอร์นี้
- `docx_to_contentjson.py` — ข้อ 1 (gold .docx → content JSON) **ทดสอบแล้วกับ 2 เฉพาะ gold โครงถูก**
- `make_dataset.py` — ข้อ 3 (ยังไม่สร้าง — รอยืนยันรูปแบบ input)

## สำคัญ: dataset โตเองจากงานจริง
ทุกรายงานที่ทำเสร็จจากนี้ (content.json + facts) drop เข้า `dataset/` → ชุดเทรนโตขึ้นเรื่อย ๆ
ยิ่งทำยิ่งมีข้อมูล → finetune รอบหน้ายิ่งดี
