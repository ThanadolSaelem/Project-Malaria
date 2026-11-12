# Prompt lessons — คลังบทเรียนการจูน Tiel

ลูปที่ 2 ของ Propose–Probe–Compose (ดู `pipeline/docs/prompt-tuning-ppc.md`).
จดทุกครั้งที่ **compose สำเร็จ**: อะไรช่วย (PASS) อะไรทำพัง (FAIL) **พร้อมหลักฐานจากการรัน**
(วันที่ / เคสทดสอบ / สัญญาณที่ดีขึ้นหรือแย่ลง). ก่อนจูน domain ใด อ่านหัวข้อนั้นก่อน
เพื่อไม่ซ้ำรอยที่เคยพังมาแล้ว.

รูปแบบบรรทัด:
`- [PASS/FAIL] <การแก้> -> <ผลต่อพฤติกรรม> (หลักฐาน: <วันที่/เคส/รอบ>)`

---

## Qwen Code Harness & MCP Integration

- [PASS] ใช้ "httpUrl" แทน "url" สำหรับ Streamable HTTP MCP servers ใน Qwen Code -> เชื่อมต่อสำเร็จ ไม่ติดค้าง Timeout ที่ SSE handshake (หลักฐาน: 2026-11-10)
- [PASS] ตั้งค่า "trust": true ใต้แต่ละ mcpServer ใน /root/.qwen/settings.json (User Scope) และห้ามใส่ mcpServers ใน /workspace/.qwen/settings.json -> Qwen Code ไม่ล็อกผ่าน isGatedMcpScope(workspace) และไม่ต้องอาศัย mcpApprovals.json ทำให้ MCP ทั้ง 6 ตัว (hexstrike, rea, cve, memory, search, specialist) ต่อติด auto ทันทีแม้ recreate คอนเทนเนอร์ใหม่ (หลักฐาน: 2026-11-11)
- [FAIL] คัดลอก "mcpServers" ลงใน /workspace/.qwen/settings.json (Workspace Scope) -> Qwen Code เมิน "trust": true แล้วบังคับ "approvalState": "pending" ใน /root/.qwen/mcpApprovals.json ทุกครั้งที่ recreate ทำให้ MCP ขึ้น disconnected ทั้งหมด (หลักฐาน: 2026-11-11 จาก chunk-GBMK5PEL.js isGatedMcpScope และ /runtime/mcp)
- [PASS] ตั้งค่า "tools": {"approvalMode": "auto"} ใน settings.json -> เปิดโหมดอนุมัติเครื่องมืออัตโนมัติผ่าน Classifier โดยไม่ต้องกด Approve ด้วยมือใน UI ทุกครั้ง

## General (ใช้ได้ทุกงาน)

<!-- ตัวอย่าง (ลบออกเมื่อมีของจริง):
- [PASS] บังคับขึ้น verdict + ความมั่นใจเป็นหัวข้อแรกก่อนรายละเอียด -> Tiel ไม่หยุดแค่ list facts (หลักฐาน: 2026-10-19, เคส Minecraft APK, 3/3 รอบไปถึง verdict)
-->

## APK / Android

<!-- - [PASS] เช็ก signer + endpoint ก่อน decompile -> ได้ verdict เร็วขึ้น ~2 step (หลักฐาน: ...) -->

## PE / PyInstaller (.exe)

<!-- - [PASS] ระบุว่า .exe ที่เป็น PyInstaller ให้ pyinstxtractor-ng -> pycdc ไม่ใช่ Ghidra -> เลิกเสียเวลาเปิด Ghidra กับ stub (หลักฐาน: ...) -->

## OSINT / เว็บมิจฉาชีพ

<!-- passive only — ดู guardrail ใน system prompt -->

## pcap / network

<!-- - [ ] ... -->

## WPA / cracking

<!-- - [ ] ... -->

## Report / docx (TLP:AMBER)

- [PASS] แยก format ออกจากเนื้อหา: ให้โมเดลผลิต "content JSON + รูปหลักฐาน" แล้วใช้
  `pipeline/reporting/assemble.py` ประกอบ docx -> format ตรงเฉลยเสมอ
  (หลักฐาน: 2026-10-19 เคส NHSO — โมเดลประกอบเองได้ Times New Roman 14KB ไม่มีรูป;
  ประกอบผ่าน template แล้ว font/ขอบ/heading/banner/ฝัง Sarabun ตรงเฉลยหมด)
- [FAIL] ให้โมเดลประกอบ .docx เอง / สอนกฎ Sarabun 16pt ใน prompt -> เปราะ เลือก font ผิด
  ตัด: ย้าย format ไป template + script แทน
- [ ] ยังขาด: workflow ให้ Tiel เซฟรูปหลักฐานลง evidence/ อัตโนมัติ (web ผ่าน REA,
  โค้ด render เป็นรูป) — ต้องทดสอบกับ Tiel จริง
