pipeline/reports/  —  รายงานที่ประกอบแล้ว (output)
====================================================

โฟลเดอร์นี้ bind-mount เข้าคอนเทนเนอร์เป็น /reports (เขียนได้)
ใช้กับโหมดอัตโนมัติเต็ม (แบบ C): Tiel ทำเองทั้งหมดในคอนเทนเนอร์

ขั้นตอนที่ Tiel ทำ (ดู ../reporting/report_contract.md + system prompt):
  1. วิเคราะห์ + เซฟรูปหลักฐานลง /evidence (ปิดบังค่าอ่อนไหวก่อน)
  2. เขียนเนื้อหาเป็น JSON ลง /reports/<ชื่อ>.json  (ตามสคีมา report_contract.md)
  3. สั่ง:  python3 /reporting/assemble.py /reports/<ชื่อ>.json -o /reports/<ชื่อ>.docx
  4. ได้ไฟล์ .docx ฟอร์แมตบ้าน สกมช. โผล่ที่นี่ (= pipeline/reports/ บน Mac)

⚠️ ก่อนส่งออกนอก: เปิด .docx ตรวจซ้ำว่า redaction ครบ (token/credential/เบอร์/URL ตรง)
   โหมดนี้ไม่มีจังหวะให้คนเบรกก่อนประกอบ การตรวจจึงอยู่ที่ไฟล์ผลลัพธ์

ทั้ง .json และ .docx ในโฟลเดอร์นี้เป็นของเคส → .gitignore (เก็บแต่ README นี้)
