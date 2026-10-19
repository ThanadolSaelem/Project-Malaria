# Prompt lessons — คลังบทเรียนการจูน Tiel

ลูปที่ 2 ของ Propose–Probe–Compose (ดู `pipeline/docs/prompt-tuning-ppc.md`).
จดทุกครั้งที่ **compose สำเร็จ**: อะไรช่วย (✅) อะไรทำพัง (❌) **พร้อมหลักฐานจากการรัน**
(วันที่ / เคสทดสอบ / สัญญาณที่ดีขึ้นหรือแย่ลง). ก่อนจูน domain ใด อ่านหัวข้อนั้นก่อน
เพื่อไม่ซ้ำรอยที่เคยพังมาแล้ว.

รูปแบบบรรทัด:
`- [✅/❌] <การแก้> → <ผลต่อพฤติกรรม> (หลักฐาน: <วันที่/เคส/รอบ>)`

---

## General (ใช้ได้ทุกงาน)

<!-- ตัวอย่าง (ลบออกเมื่อมีของจริง):
- [✅] บังคับขึ้น verdict + ความมั่นใจเป็นหัวข้อแรกก่อนรายละเอียด → Tiel ไม่หยุดแค่ list facts (หลักฐาน: 2026-10-19, เคส Minecraft APK, 3/3 รอบไปถึง verdict)
-->

## APK / Android

<!-- - [✅] เช็ก signer + endpoint ก่อน decompile → ได้ verdict เร็วขึ้น ~2 step (หลักฐาน: ...) -->

## PE / PyInstaller (.exe)

<!-- - [✅] ระบุว่า .exe ที่เป็น PyInstaller ให้ pyinstxtractor-ng → pycdc ไม่ใช่ Ghidra → เลิกเสียเวลาเปิด Ghidra กับ stub (หลักฐาน: ...) -->

## OSINT / เว็บมิจฉาชีพ

<!-- passive only — ดู guardrail ใน system prompt -->

## pcap / network

<!-- - [ ] ... -->

## WPA / cracking

<!-- - [ ] ... -->
