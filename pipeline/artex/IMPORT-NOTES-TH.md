# บันทึกนำเข้า ARTEX สำหรับ Project-Malaria

## ที่มาและขอบเขต

- ไฟล์ต้นทาง: `ARTEX-main.zip` ที่ผู้ใช้แนบมา
- SHA-256 ของ ZIP: `5f5bae95bde9713d2e0f6433b3f38773240ea2ecca05aa486ce7da305d41762f`
- README ของต้นทางระบุว่าเป็น ARTEX (Go backend + Next.js frontend), fork จาก ARTEX by Autumn-27 และเผยแพร่โดย BaaRai ภายใต้ AGPL-3.0
- ZIP ผ่านการตรวจ CRC; ตรวจ path ก่อนคัดลอก และไม่พบ symlink, encrypted entry, absolute path หรือ `..` traversal.
- เก็บ source ไว้เป็น subtree แยก `ARTEX-main/`; ยังไม่ได้เชื่อมบริการนี้เข้ากับ Docker Compose หรือ pipeline runtime ของ Project-Malaria.

## รายการที่ตัดออกตามที่ผู้ใช้เลือก

ไม่นำเข้ารายการเดียวนี้:

- `skills/edr-bypass-re/SKILL.md` — เป็นคู่มือด้าน EDR-evasion/การลดทอน telemetry และเทคนิคที่เกี่ยวข้อง

ไม่มีการนำเนื้อหาของไฟล์ดังกล่าวเข้ามา และลบโฟลเดอร์ว่างของ skill ออกด้วย การค้นหาคำตรง `trojan`, `malware`, `edr-bypass` และ `evasion` ในไฟล์ upstream ที่คัดลอกมา (ไม่นับบันทึกนำเข้า/แผนผังที่เพิ่มใน Project-Malaria) ไม่พบผลลัพธ์

## ข้อจำกัดของการตรวจ

นี่เป็นการคัดกรองแบบ static จากชื่อและเนื้อหาไฟล์ ไม่ใช่การสแกน antivirus หรือการรับรองว่า source ปลอด trojan ทั้งหมด ไม่มีการ build, ติดตั้ง dependencies, รันสคริปต์, รัน server, เรียก network หรือรัน PoC ใด ๆ

ตามขอบเขตตัวเลือก 1 ของผู้ใช้ ส่วน security testing อื่นยังคงอยู่ รวมถึง `skills/php2shell/` และ `scripts/poc/php2shell/` ซึ่งต้นทางระบุว่าเป็น PoC สำหรับ RCE และมี lab setup; เก็บไว้เป็น source เท่านั้น ไม่ได้รัน หากต้องการตัด PoC/exploit เพิ่ม ต้องทำเป็นขอบเขตงานแยกต่างหาก

ไฟล์ `.sh`, `.py` และไฟล์ source อื่นคงอยู่ตาม archive; อย่าใช้ `start.sh`, `install.sh`, `update.sh`, Docker build/Compose หรือ PoC โดยไม่ตรวจเนื้อหาและ dependencies ตามขั้นตอนของเจ้าของระบบก่อน

## ลิขสิทธิ์

คง `LICENSE` ต้นฉบับไว้ครบถ้วน (GNU Affero General Public License v3.0) และคงไฟล์ `web/LICENSE` ต้นทางไว้ด้วย ก่อนเผยแพร่หรือเชื่อมโค้ดเข้ากับส่วนอื่น ให้ทบทวนเงื่อนไข AGPL-3.0 และ license ของ dependency/ทรัพย์สินที่เกี่ยวข้อง การเก็บ source แยกเป็น subtree ไม่ได้แปลว่าได้ทำ legal review หรือได้รับสิทธิ์เพิ่มเติม

ดูการจับคู่ฟีเจอร์กับ Project-Malaria ที่ [แผนผังการเสริมระบบภาษาไทย](../pipeline/docs/artex-review-th.md).
