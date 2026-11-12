# n8n Modular Node Workflows & Dual-Brain Auto-Relay Engine

ทุกอย่างรวมศูนย์อยู่ใน **n8n จริง (`http://localhost:5678`)** โดยไม่มีหน้า Dashboard แยก (ส่วนพอร์ต `:8010` ทำหน้าที่เป็นเฉพาะ **Headless Backend API Bridge** เบื้องหลังเพื่อให้โหนดใน n8n เรียกใช้เครื่องมือและจัดการสถานะของวงจรผลัดไม้ได้)

พร้อมตั้งค่า `N8N_SECURE_COOKIE: "false"` ใน `docker-compose.yml` เรียบร้อยแล้ว ทำให้เปิดใช้งานผ่าน Safari หรือ HTTP ปกติได้ทันทีโดยไม่ติดแจ้งเตือน Secure Cookie

---

## ผังโหนด (Workflows) ที่ถูกนำเข้าสู่ n8n อัตโนมัติ

เมื่อเปิด `http://localhost:5678` จะพบ **4 Workflows** ที่วางผังโหนดไว้ให้พร้อมใช้งาน:

### `0. Dual-Brain Auto-Relay Loop (Orchestrator ⇄ Cyber-Model วนทำงานอัตโนมัติจนกว่าจะเสร็จจริง)`
ออกแบบมาเพื่อแก้ปัญหา **AI หยุดทำงานไปเองกลางคัน** และให้โมเดลทั้ง 2 ตัวส่งไม้ต่อกันตามความถนัดภายใน Session เดียวกัน:
- **Zone 1 — เริ่มภารกิจ & แตก Checklist ย่อย (`POST /api/relay/init`)**:
  - รับโจทย์จากแชทหรือปุ่มรัน แล้วแตกเป็นรายการ `Checklist` ย่อย (กำหนดเพดานความปลอดภัยเริ่มต้นไว้ที่ `max_iterations = 30` รอบ)
- **Zone 2 — ตัวคัดแยกงานอัตโนมัติ (`Hybrid Task Dispatcher` -> `IF Switch`)**:
  - ตรวจป้ายส่งไม้ต่อ (`HANDOVER_TO`) + ให้โมเดลเล็ก `summarizer (:8092)` และกฎวิเคราะห์งานตัดสินว่าก้าวต่อไปเป็นงานสายไหน:
    - **งานด้าน Cyber Security / Recon / VA / แกะ Binary / ค้น CVE** -> วิ่งไปสายบนหา **`Brain B: Cyber-Model (:8091)`**
    - **งานด้าน Coding / เขียนสคริปต์ Python/PoC / แก้บั๊ก / เรียบเรียงรายงาน `.docx`** -> วิ่งไปสายล่างหา **`Brain A: Orchestrator (:8090)`**
  - **Cross-Brain Rescue**: หากสมองตัวเดิมติด Error หรือไม่คืบหน้าติดต่อกัน 2 รอบ ระบบจะบังคับสลับให้อีกสมองเข้ามาช่วยแก้ทางทันที
- **Zone 3A (`Brain B: Cyber-Model :8091`) & Zone 3B (`Brain A: Orchestrator :8090`)**:
  - โมเดลทั้ง 2 ตัวเปิด `--jinja` เต็มรูปแบบ สามารถกดเรียกโหนดเครื่องมือ (`HexStrike`, `REA`, `CVE`, `Search`, `Memory`, `shot`, `vflat`, `php2shell`, `Report Assembler`) ที่เสียบอยู่ใต้ตัวมันได้เองโดยตรง และคุณสามารถกดปุ่ม `D` (Deactivate) หรือดึงสายโหนดเครื่องมือออกบนแคนวาส n8n ได้ทุกเมื่อ
- **Zone 4 — ด่านตรวจรับงานและกระตุ้นต่ออัตโนมัติ (`Handover Updater` -> `Completion Gate IF`)**:
  - ตรวจว่า `Checklist` ถูกทำครบทุกข้อหรือยัง (และถ้าสั่งทำรายงาน จะตรวจว่ามีไฟล์ `.docx` ถูกสร้างใน `/reports` จริงหรือยัง)
  - **ถ้ายังไม่ครบ (`is_done = false`)**: แม้ AI จะหยุดพูดไปเอง สาย `false` ของโหนด `Completion Gate` จะ **วนลูปกลับไปปลุก `Zone 2 (Task Dispatcher)` อัตโนมัติ** เพื่อส่งงานให้ AI ตัวถัดไปทำต่อทันทีโดยไม่ต้องรอคนพิมพ์กระตุ้น!

---

### `1. Cyber-Model Modular AI Agent (ถอด/เสียบ MCP, Plugin, Model เป็น Node)`
- ผังโหนดสำหรับคุยโต้ตอบแบบปกติ (1 คำสั่งต่อ 1 รอบ) ที่มีโหนดโมเดล (`Orchestrator`, `Cyber-Model`, `NVIDIA NIM`, `OpenRouter GLM-5.3`) และโหนดเครื่องมือทั้งหมดแยกเป็นชิ้นๆ ให้ลากสายสลับหรือกด `D` เปิด/ปิดได้ทันที

### `2. Visual Pentest Pipeline (Recon -> Screenshot+Vision -> Specialist -> DOCX Report)`
- ไปป์ไลน์แบบเรียงลำดับขั้น: ตั้งค่าเป้าหมาย -> แคปหน้าเว็บและให้ Vision อ่าน (`shot`) -> สแกนช่องโหว่ -> วิเคราะห์ผล -> ประกอบรายงาน `.docx`

### `3. System Control Plane (เช็คไฟเขียว/แดง · สลับ Tool-RAG · เปิด/ปิด Plugin · Restart Node)`
- โหนดสำหรับสั่งเปิด/ปิด `Tool-RAG`, ถอด/เสียบปลั๊กอิน (`php2shell`, `shot`, `vflat`, `reporting`), หรือสั่ง Restart บริการ/โมเดลจากใน n8n ได้โดยตรง

---

## วิธีเปิดหรือรีโหลดการตั้งค่าใหม่

```bash
# 1) รีสตาร์ทโมเดลทั้งคู่ (ให้ :8091 Cyber-Model เปิด --jinja สำหรับเรียก Tool)
pkill -f llama-server
bash pipeline/mac/run-models.command

# 2) อัปเดต n8n (เปิด N8N_SECURE_COOKIE=false + โหลดผังโหนดชุดใหม่) และรีสตาร์ท LiteLLM
cd pipeline
docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d n8n litellm
```
หรือดับเบิลคลิกที่ `pipeline/mac/run-node-studio.command` เพื่อเปิด **n8n (`http://localhost:5678`)** ได้เลย
