pipeline/evidence/  —  รูปหลักฐานสำหรับรายงาน TLP:AMBER
=========================================================

โฟลเดอร์นี้ bind-mount เข้า container เป็น /evidence  (ดู docker-compose)
Tiel เซฟรูปหลักฐานที่จับ/สร้างระหว่าง process ลงที่นี่ แล้วอ้างในไฟล์ JSON เนื้อหา
ด้วย "ชื่อไฟล์" (เช่น "image": "fig_decompiled_token.png")
จากนั้น pipeline/reporting/assemble.py จะหยิบรูปจากที่นี่มาใส่กรอบในรายงาน

ที่มาของรูป (ดู ../reporting/report_contract.md ประกอบ):
  - หน้าเว็บ  → REA headless Chromium ถ่าย screenshot (CDP) → เซฟ .png ที่นี่
  - โค้ด/strings/terminal/decompile → render ข้อความเป็น PNG (ไม่ใช่จับจอ GUI)
  - GUI ของโปรแกรม → ทำไม่ได้ใน container (ใช้ placeholder ให้คนแนบภายหลัง)

การตั้งชื่อ: สื่อความ + ขึ้นต้น fig_  เช่น fig_pyinstaller_tree.png, fig_endpoints.png

⚠️ redaction: ปิดบัง token/credential/เบอร์/อีเมล/URL ตรงของระบบที่ยังไม่ถูกแก้ ในรูปก่อนเซฟ

ไฟล์รูปจริงใน evidence/ ถูก .gitignore (เป็นหลักฐานของเคส ไม่ commit) — เก็บแต่ README นี้
