dsh-workspace/ — home/workspace ของ deepseek-harness agent (Tiel)
=================================================================
โฟลเดอร์นี้ถูก bind-mount เป็น /root (HOME) ใน container `deepseek-harness`
(ดู pipeline/docker-compose.yml). โมเดลมักสร้างโฟลเดอร์งานไว้ในบ้านของมัน เช่น
/root/<ชื่อเคส>/... — การ mount ออก host ตรงนี้ทำให้ไฟล์พวกนั้น:

  • ไม่หายตอน `docker compose up --force-recreate` / rebuild (เดิมอยู่ใน
    writable layer ของ container = ephemeral → หายเกลี้ยง)
  • เปิดอ่าน/ดาวน์โหลดจาก host ได้ที่ pipeline/dsh-workspace/ บน Mac/Windows

reproducible: เป็น relative path → Docker สร้างโฟลเดอร์นี้ให้เองตอน `up`
ครั้งแรกบนเครื่องใหม่ ไม่ต้อง setup อะไรเพิ่ม

⚠️ ความปลอดภัย: ไฟล์งานเคสที่นี่ "อาจมีข้อมูลอ่อนไหว" (หลักฐาน/credential/
ข้อมูลเป้าหมาย) → .gitignore กันไม่ให้ commit ทั้งโฟลเดอร์ (เก็บแค่ README นี้)
อย่าแก้ .gitignore ให้ commit เนื้อในโฟลเดอร์นี้

หมายเหตุ: หลักฐานที่จะใส่ "รายงาน" ให้เซฟลง /evidence และ report JSON ลง /reports
(path สัมบูรณ์) เสมอ — สองอันนั้นเป็น bind mount ที่ assemble.py และ container
เครื่องมืออื่น (HexStrike/REA) เห็นร่วมกัน ส่วน /root นี้เห็นเฉพาะ agent เอง
