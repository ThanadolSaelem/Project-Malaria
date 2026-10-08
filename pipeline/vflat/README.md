# vFlat Scan — document dewarp/enhance service

สแกนรูปถ่ายเอกสาร/หลักฐานให้ "แบน คม พื้นขาว" ก่อนป้อนให้ vision model (Qwen2.5-VL)
อ่าน → OCR แม่นขึ้นมาก โดยเฉพาะรูปที่ถ่ายเบี้ยว แสงไม่เท่ากัน มีเงา

เป็น port ของ pipeline สแกนจากแอป vFlat (Android) มาเป็น **numpy/OpenCV + TFLite
ล้วน** ไม่ต้องใช้ OpenGL/GPU — รันบน CPU (arm64/amd64) ในคอนเทนเนอร์เล็กๆ ได้

## ขั้นตอนใน pipeline (vflat_scan.py)

1. **blackpoint** (TFLite) — ประเมิน black point / ว่าควรลบเงาหรือไม่
2. **freeform** (TFLite) — หา control grid 25×25 แล้ว **dewarp** (รีดหน้ากระดาษให้แบน)
3. **sharpen** — unsharp mask
4. **enhance** (TFLite) — flat-field correction ลบเงา ทำพื้นหลังขาว

## HTTP API (app.py, FastAPI)

```
POST /scan   file=@photo.jpg              → image/jpeg  (ภาพที่สแกนแล้ว)
POST /scan   file=@doc.pdf                → application/pdf (ทุกหน้า)
POST /scan   file=@doc.pdf  ?page=2       → image/jpeg  (หน้าเดียว)
GET  /healthz                             → {"status":"ok"}
```

query params: `dewarp` `sharpen` `enhance` `trim` (bool, default true), `quality`
(1-100, default 95), `dpi` (PDF rendering, default 200), `pagesize` (auto/a4/letter)

ปิด dewarp (`?dewarp=false`) สำหรับภาพที่แบนอยู่แล้วแต่หม่น — จะได้แค่ลบเงา+คม
ไม่ดัดรูปทรง

## ใช้ใน Project-Malaria

- service `vflat-scan` ใน `docker-compose.yml` (default profile)
  - ภายใน compose network: `http://vflat-scan:8000`
  - จาก host: `http://localhost:8006`
- helper บน host:
  - `pipeline/mac/scan-doc.sh in.jpg [out.jpg]` — สแกนเซฟไฟล์ (ไว้ล้างรูปหลักฐานก่อนแปะ report)
  - `pipeline/mac/ask-vision.sh --scan photo.jpg "อ่านให้หน่อย"` — สแกนแล้วให้ vision model อ่านเลย

## ทดสอบเร็วๆ (ดูผลแต่ละขั้น)

```bash
# ในคอนเทนเนอร์ หรือที่ไหนก็ได้ที่มี deps:
python3 run_test.py path/to/photo.jpg ./out
#   เซฟ 1_padded / 2_dewarp / 3_sharpen / 4_final .jpg ให้เทียบ
```

## หมายเหตุทรัพย์สินทางปัญญา

โมเดล `.tflite` ในโฟลเดอร์ `models/` มาจากแอป vFlat — ใช้ภายใน pipeline นี้สำหรับ
งานตรวจสอบของเราเอง (local-first) ไม่ได้เผยแพร่ซ้ำเป็นผลิตภัณฑ์ หากจะใช้เชิงพาณิชย์
หรือแจกจ่ายต่อ ควรตรวจเงื่อนไขสิทธิ์ของ vFlat ก่อน
