# บันทึกส่งมอบ: Qwen Code Auto-Delegation

## สรุป

แก้ pipeline ให้ Qwen Code ใช้ Flint (`:8090`) เป็น coordinator จริง: มอบหมายงาน security/recon/WSTG ไป Cyber-Model (`:8091`) และงานภาพ/OCR ไป Vision (`:8093`) โดยอัตโนมัติ ส่วนโค้ด สคริปต์ parser และการประกอบรายงานอยู่ใน parent Flint turn ตามปกติ ไม่ต้องให้ผู้ใช้เตือนให้ส่งงานต่อ

## ผลตรวจ Qwen Code package

ตรวจ npm package `@qwen-code/qwen-code@0.27.2` ที่ `latest` ชี้อยู่ในวันที่ 2026-11-12 และ pin รุ่นนี้ใน Dockerfile เพื่อให้ schema ที่ตรวจไม่เปลี่ยนตามการ build ในอนาคต (tarball SHA-256: `3bdf4c84af2208ceaed5a6f8308504457fdb72d997eafba5b243061ad2d007bc`).
แหล่ง package: [npm tarball 0.27.2](https://registry.npmjs.org/@qwen-code/qwen-code/-/qwen-code-0.27.2.tgz).

- เครื่องมือ native สำหรับมอบหมายคือ `agent` (UI/API อาจแสดงเป็น `Agent`); `description` และ `prompt` เป็นพารามิเตอร์ที่ต้องมี ส่วน `subagent_type` และ `run_in_background` ใช้เลือก named agent และรอผลแบบ foreground ได้ การเรียกใน prompt จึงใช้ `agent(..., subagent_type="cyber-specialist", run_in_background=false)` ไม่ใช่การพึ่ง Claude Code syntax ที่ไม่มีใน Qwen
- `team_create` เป็นเครื่องมือจริง แต่ Agent Team ทำงานร่วมกันและ teammate เริ่มทำงานพร้อมกัน จึงปิดไว้สำหรับเครื่องที่มี `-np 1` และมี VRAM/GPU memory ร่วมกัน การเรียก synchronous named agent ที่กำหนด `run_in_background=false` ยังใช้ได้
- Frontmatter ปัจจุบัน `name`, `description`, `model` รองรับ และ `disallowedTools` รองรับสำหรับจำกัดเครื่องมือของ named agents
- Qwen Code CLI ปกติไม่ได้ถือว่า `AGENTS.md` เป็น context file พิเศษโดยอัตโนมัติ ค่าเริ่มต้นคือ `QWEN.md`; ต้องกำหนด `context.fileName: "AGENTS.md"` อย่างชัดเจน Named agent มี context ของตนเอง ส่วน fork agent สืบทอด full context ของ parent จึงห้ามใช้ fork ใน routing นี้
- `isGatedMcpScope` ครอบคลุม project/workspace scope; การคง MCP servers ไว้ใน user-scope settings พร้อม `trust: true` และไม่ทำสำเนาลง workspace settings สอดคล้องกับ package behavior และบทเรียนเดิมใน `prompt-lessons.md`

ผลจาก tarball ยืนยัน schema และพฤติกรรมที่ package ระบุเท่านั้น ไม่ได้ยืนยันว่า Mac โหลด named agents, settings, MCP หรือเครื่องมือได้จริงหลัง restart

## สาเหตุหลักและการเปลี่ยนแปลงรายไฟล์

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `pipeline/Dockerfile.qwen-code` | Pin `@qwen-code/qwen-code@0.27.2` แทน `@latest` เพื่อให้ native tool schema และบริบทที่ตรวจไว้ทำซ้ำได้ |
| `pipeline/qwen-code/settings.json` | ตั้ง `context.fileName` เป็น `AGENTS.md`, ตั้ง `agents.defaultBackground` เป็น `false`, ปิด `experimental.agentTeam`; คง MCP definitions ใน user-scope settings |
| `pipeline/qwen-code/entrypoint.sh` | ติดตั้ง named agents ใน `/workspace/.qwen/agents` จุดเดียว; extract เฉพาะเนื้อหาหลัง `## SYSTEM PROMPT` ไป `/workspace/AGENTS.md`; ไม่ทำสำเนา instructions ซ้ำใน `/root/.qwen` หรือ `/root`; ค่า Agent Team เริ่มต้นเป็น `0` |
| `pipeline/cyber-operator.system.md` | ระบุ Flint เป็น coordinator; เพิ่ม routing อัตโนมัติสำหรับ security และภาพ; ให้ coding/reporting อยู่ใน parent; กำหนด native named `agent` เทียบกับ stateless MCP, ปิด nested delegation/parallel LLM calls, และระบุ local-only data boundary; แก้ความขัดแย้งที่เดิมบอกให้ใช้ native vision agent แต่กลับสั่งใช้ Bash curl เป็นทางหลัก โดยคงคำแนะนำ security และเครื่องมือเดิมส่วนอื่น |
| `pipeline/qwen-code/agents/cyber-specialist.md` | จำกัดเป็น Cyber-Model งานเดียว ตรวจ scope ซ้ำ และห้ามส่งกลับไป Flint/เรียกตัวแทนอื่น |
| `pipeline/qwen-code/agents/vision-analyst.md` | กำหนด OCR/ภาพเป็นงานเฉพาะ ใช้ Vision ในเครื่อง และห้าม delegate ต่อ |
| `pipeline/qwen-code/agents/coding-orchestrator.md` | ระบุชัดว่าเป็น worker เฉพาะเมื่อแยก endpoint แล้วเท่านั้น เพราะปกติใช้ Flint `:8090` slot เดียวกับ parent |
| `pipeline/specialist_mcp_http.py` | แยก stateless one-shot MCP ออกจาก native agent; ใช้ allowlist alias ของ local `:8090`/`:8091`, serialize คำขอตาม endpoint ภายใน MCP process นี้เท่านั้น, จำกัดคำแนะนำไม่ให้ child วนเรียก และปิด `ask_coding_orchestrator` เป็นค่าเริ่มต้น |
| `pipeline/docker-compose.yml` | ตั้ง Agent Team เป็น `0`; ระบุ `ALLOW_ORCHESTRATOR_DELEGATION: "0"`; แก้คำอธิบาย specialist MCP ให้ตรงกับการทำงานแบบ stateless/local |
| `pipeline/control_plane.py` | ทำให้ settings ที่ control plane สร้างตรงกับไฟล์ตั้งต้น: โหลด `AGENTS.md`, ทำ named agents เป็น foreground โดยปริยาย, และปิด Agent Team |
| `pipeline/docs/qwen-delegation-handoff.md` | เพิ่มบันทึกนี้พร้อมวิธีทดสอบหลัง merge |

## Audit aliases / n8n

ไม่พบ mismatch ที่ต้องแก้ใน `pipeline/litellm-config.yaml`, `pipeline/node-config.json`, `pipeline/n8n/workflows/0_Dual_Brain_Auto_Relay_Loop.json` หรือ routing หลักของ `pipeline/control_plane.py`:

- `flint`, `orchestrator`, `gpt-oss-120b` และชื่อ legacy เช่น `cybermodel` ถูก map ไป orchestrator ที่ `:8090` (ชื่อ `gpt-oss-120b` เป็น registry key/alias ไม่ได้แปลว่า Qwen Code กำลังใช้โมเดล cloud)
- `cyber-model`, `cyber-tiel` และ `exploit-specialist` เป็น alias ของ specialist `:8091`; `vision` ชี้ `:8093`
- n8n เป็น Dual-Brain relay แยกต่างหากและใช้ alias `cyber-model`/`orchestrator` ที่มีอยู่แล้ว จึงไม่แก้ workflow ที่ไม่ได้เป็นตัวเรียก Qwen native subagent

## Static validation ที่รันจริง

ผลผ่าน ณ workspace นี้:

```text
PASS: py_compile pipeline/specialist_mcp_http.py pipeline/control_plane.py
PASS: sh -n pipeline/qwen-code/entrypoint.sh
PASS: awk AGENTS extraction (21136 bytes; begins with coordinator role; no section marker)
PASS: JSON pipeline/qwen-code/settings.json
PASS: JSON pipeline/node-config.json
PASS: JSON pipeline/n8n/workflows/0_Dual_Brain_Auto_Relay_Loop.json
PASS: JSON pipeline/n8n/workflows/1_Modular_Pentest_Agent_Node_Hub.json
PASS: JSON pipeline/n8n/workflows/2_Visual_Pentest_Pipeline_Stages.json
PASS: JSON pipeline/n8n/workflows/3_Control_Plane_Node_Manager.json
PASS: YAML pipeline/docker-compose.yml
PASS: YAML pipeline/litellm-config.yaml local alias-to-port audit
PASS: YAML frontmatter pipeline/qwen-code/agents/cyber-specialist.md
PASS: YAML frontmatter pipeline/qwen-code/agents/coding-orchestrator.md
PASS: YAML frontmatter pipeline/qwen-code/agents/vision-analyst.md
PASS: git diff --check
SKIP: docker compose config --quiet (Docker Compose CLI unavailable in sandbox)
```

ไม่มีการรันหรืออ้างผล live บน Mac, Docker container, llama-server หรือการมอบหมายจริง และไม่ได้เพิ่มผล `PASS`/`FAIL` ปลอมใน `pipeline/prompt-lessons.md`

## Mac Post-Merge Test Playbook

ใช้กับเครื่องที่ checkout branch `pipeline-deepseek` แล้ว และให้ llama-server ในเครื่องทำงานตามปกติ คำสั่งด้านล่างต้องรันจาก root ของ repository; `docker compose up --build` จำเป็นเพราะมีทั้ง image, environment และ mounted config เปลี่ยน ไม่ควรใช้ `restart` อย่างเดียวซึ่งไม่ rebuild image:

```bash
git checkout pipeline-deepseek
git pull --ff-only origin pipeline-deepseek
cd pipeline
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build qwen-code specialist-mcp
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full ps qwen-code specialist-mcp
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full logs --tail=100 qwen-code specialist-mcp
```

กลับไปที่ root ของ repository แล้วเปิดติดตาม log แยก terminal โดยไม่ลบ/แก้ log เดิม:

```bash
tail -f pipeline/mac/logs/llama.log
tail -f pipeline/mac/logs/llama-specialist.log
```

รันแต่ละ prompt อย่างน้อย 3 รอบโดยใช้ target/input เดิมทุกครั้ง เพื่อเทียบพฤติกรรมแบบ PPC; ห้ามใส่ชื่อ agent หรือสั่งให้ “delegate” ใน prompt ทดสอบ:

1. **Recon/WSTG อัตโนมัติ** — “ฉันเป็นเจ้าของและอนุญาตให้ทดสอบเฉพาะเว็บแอป local lab ที่ `http://host.docker.internal:18056` เท่านั้น ช่วยทำการตรวจแบบ low-impact ตาม WSTG เพื่อระบุ security headers, routes ที่เปิดเผย และจุดที่ควรตรวจต่อ ห้าม brute force, exploit, เปลี่ยนข้อมูล หรือแตะระบบอื่น ระบุเครื่องมือและหลักฐานจริงที่ใช้”
2. **ทบทวนความเสี่ยงก่อน exploit โดยไม่รัน** — “สำหรับแอป local lab ที่ฉันเป็นเจ้าของและอนุญาตเฉพาะ `http://host.docker.internal:18056` ช่วยประเมินคำขอจำลองนี้โดยไม่ส่งจริง: `POST /profile/preferences HTTP/1.1; Host: host.docker.internal:18056; Content-Type: application/json; body={\"theme\":\"dark\"}` ว่ามีผลเปลี่ยนสถานะหรือทำให้บริการหยุดชะงักหรือไม่ ให้สรุปความเสี่ยง ขอบเขต และเงื่อนไขที่ต้องได้รับอนุญาตแยกก่อนดำเนินการ”
3. **ภาพ/OCR** — “อ่านข้อความในภาพหน้าจอที่แนบให้ครบ สรุปป้าย ปุ่ม URL และข้อความแจ้งเตือนตามที่มองเห็น แยกส่วนที่ไม่ชัดหรืออ่านไม่ได้ และอย่าคาดเดาข้อความที่มองไม่เห็น”
4. **Coding อยู่ใน Flint** — “เขียนสคริปต์ Python แบบ deterministic สำหรับอ่าน JSON ตัวอย่าง `{"findings":[{"id":"F-01","severity":"low","title":"Demo"}]}` แล้วพิมพ์ CSV คอลัมน์ `id,severity,title` พร้อม unit test สั้น ๆ ห้ามเรียก network หรือ target”

### สิ่งที่ต้องสังเกตใน log

- ใน `pipeline/mac/logs/llama.log` ควรเห็นคำขอหลักจาก `:8090` เลือก native `agent` สำหรับ prompt security/ภาพโดยไม่ต้องให้ผู้ใช้บอกให้ส่งต่อ และเห็น parent รอ/สรุปผลกลับมา งาน parser ใน prompt 4 ควรทำใน Flint เอง ไม่วนเรียก Flint `:8090` ซ้ำ
- สำหรับ prompt 1–2 ให้ `pipeline/mac/logs/llama-specialist.log` มี request ที่มาจาก Cyber-Model `:8091` และมีผลตอบกลับจริง แม้ผู้ใช้ไม่ได้เอ่ยชื่อเครื่องมือหรือ agent ถ้าเห็น Flint ทำงานยาวขึ้นแต่ไม่มี request ฝั่ง specialist ให้ถือว่ายังไม่ผ่านพฤติกรรมอัตโนมัติ
- prompt ภาพควรไป local Vision `:8093`; โดยปกติไม่ควรทำให้ `llama-specialist.log` มี Cyber-Model request ส่วน prompt โค้ดควรไม่เรียก `:8091` และไม่เกิด request ซ้อนกลับไป `:8090`
- ตรวจว่าไม่มี child เรียกวนกลับ parent, ไม่มี model-backed concurrent generation, ไม่มี target data ถูกส่งไป `nim`/`or-glm` และไม่มีการอ้างผลทดสอบที่ไม่ได้รัน
- lock ใน specialist MCP serialize เฉพาะคำขอที่ผ่าน MCP process เดียวกัน ไม่ใช่ global slot scheduler ระหว่าง MCP, native agent และ client อื่น; การไม่ทำ generation ซ้อนจึงอาศัย synchronous foreground routing/การตั้งค่าและพฤติกรรม coordinator ด้วย ต้องยืนยันจาก Mac runtime log

## ขอบเขตผลที่ยืนยันได้

การตรวจ package และ static validations ทำใน GitHub workspace เท่านั้น ผล live หลัง merge ยังต้องยืนยันบน Mac โดย playbook ข้างต้น โดยเฉพาะ package version ที่ติดตั้งจริง, การค้นพบ `/workspace/.qwen/agents`, การโหลด `AGENTS.md` ผ่าน `context.fileName`, MCP trust/connectivity และการเห็น request ที่ `:8091`/`:8093` ใน runtime logs.
