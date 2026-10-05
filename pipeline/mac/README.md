# Mac (Apple Silicon / arm64) setup

## สรุปสั้น: "ปุ่มเดียว" ได้แค่ไหน?

บน Apple Silicon **ทุกอย่างลง Docker ได้ ยกเว้นตัวเดียว: โมเดล (llama.cpp)**
เพราะ Docker Desktop บน Mac **ไม่ส่ง GPU (Metal) เข้า container** — รันโมเดลใน
Docker จะได้แต่ CPU ช้ามาก ดังนั้น llama.cpp ต้องรัน **native** บน host

ส่วน `hexstrike-server` เดิมรัน native เพราะ image Kali เป็น amd64 (ต้อง emulate)
→ ตอนนี้มี **`Dockerfile.hexstrike-server.arm64`** (debian base, arm64 แท้) แล้ว
จึงยัดลง Docker ได้ ไม่ต้อง emulate อีก

```
┌─ native (host) ─┐   ┌──────────── docker compose (ปุ่มเดียว) ─────────────┐
│ llama.cpp :8090 │◄──│ litellm ◄── harnessrouter                           │
│   (Metal GPU)   │   │                   │                                 │
└─────────────────┘   │ hexstrike-server :8888 ◄── hexstrike-mcp :8001 ◄────┘
                      └─────────────────────────────────────────────────────┘
```

## วิธีใช้ — เลือกอันใดอันหนึ่ง

### ก) ปุ่มเดียวจริง (ดับเบิลคลิก)
```bash
cp pipeline/mac/llama.env.example pipeline/mac/llama.env   # แก้ path โมเดลให้ตรง
```
แล้ว **ดับเบิลคลิก `pipeline/mac/start.command`** ใน Finder — สคริปต์จะ:
1. สตาร์ท llama.cpp native บน :8090 (ถ้ายังไม่ขึ้น)
2. `docker compose up` ทั้ง stack (litellm + hexstrike-server arm64 + hexstrike-mcp + harnessrouter)
3. เปิด http://localhost:3000 ให้

### ข) ใน Docker Desktop (กดปุ่ม ▶ ของ compose project)
สตาร์ท llama.cpp native เองก่อน 1 ครั้ง:
```bash
llama-server -m <model.gguf> --host 0.0.0.0 --port 8090 --alias cybermodel -ngl 99 --jinja
```
แล้วขึ้น stack ด้วย override ของ Mac (ต้องมี `--profile full` เพื่อให้
hexstrike-server ขึ้นด้วย):
```bash
cd pipeline
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build
```
Docker Desktop จะเห็น project นี้ กดปุ่ม ▶ / ⏹ สตาร์ท/หยุดทุก container พร้อมกันได้
(หลังจากครั้งแรกที่ `up` แล้ว)

> ทำไมต้อง `--profile full`: hexstrike-server ถูกตั้ง profile `full` ไว้ใน
> docker-compose.yml (กัน Linux/Kali build image หนักโดยไม่ตั้งใจ) flag นี้เปิดมัน
> ส่วน override ของ Mac จะสลับ build ไปเป็น arm64 ให้เอง

## เช็ค
```bash
curl http://localhost:8090/v1/models   # llama.cpp native (orchestrator / Tiel-35B)
curl http://localhost:8091/v1/models   # llama.cpp native (specialist / exploit model)
curl http://localhost:4000/v1/models   # litellm (big-brain → llama.cpp)
curl http://localhost:8888/health      # hexstrike-server (ใน docker, arm64)
# harnessrouter: เปิด http://localhost:3000
```

## ผู้ช่วยเขียน exploit (specialist, :8091) + การ hardening
`start.command` จะสตาร์ท llama.cpp **2 ตัว**: orchestrator (:8090) และ specialist
(:8091, ดีฟอลต์ BugTraceAI-CORE-Ultra-27B) ที่ Tiel เรียกผ่าน MCP tool
`ask_exploit_specialist`. ตั้งค่าใน `pipeline/mac/llama.env` (ดู `.example`).

เพราะ specialist เป็นโมเดล offensive/uncensored ที่โหลดจาก HuggingFace จึงมี 3 ชั้นกัน:
- **(3) เช็ก SHA256 ก่อนสตาร์ท** — ตั้ง `SPECIALIST_MODEL_SHA256` ให้ตรงค่าจาก repo
  ทางการ ถ้าไม่ตรง start.command จะ**ไม่สตาร์ท** specialist (กันไฟล์ถูกแก้/โหลดผิดตัว).
  หา hash เอง: `shasum -a 256 <file.gguf>`
- **(1a) override chat template** — ใช้ `pipeline/mac/chatml.jinja` ของเราแทน template
  ที่ฝังในไฟล์ gguf (จุดที่ "Poisoned GGUF Templates" ฝังคำสั่งอันตราย). ถ้า build
  llama.cpp ไม่รองรับ `--chat-template-file` เปลี่ยนเป็น `--chat-template chatml`
- **(1b) ขังไม่ให้ออกเน็ต** — รันใต้ `sandbox-exec` (profile `specialist-sandbox.sb`)
  บล็อก outbound ทั้งหมด แต่ยัง listen :8091 ให้ LiteLLM ได้. ถ้า llama ไม่ยอมขึ้น
  ใต้ sandbox ปิดด้วย `export SPECIALIST_SANDBOX=0` ใน `llama.env`

> ชั้นสุดท้าย (สำคัญสุด): system prompt บังคับ "อ่าน code ก่อนรันเสมอ" — output ของ
> specialist เป็น **draft ให้ review** ไม่ใช่ของที่เอาไปรันดิบๆ

## หมายเหตุ
- **เครื่องมือความปลอดภัย (ครบชุด)**: `Dockerfile.hexstrike-server.arm64` ลงให้
  ครบเท่าที่ทำได้บน arm64:
  - apt: `nmap masscan dirb wfuzz sqlmap hydra john dnsenum dnsrecon`
  - Go (ProjectDiscovery): `nuclei httpx subfinder naabu katana dnsx` + `gobuster`
  - Rust: `feroxbuster` (binary)
  - clone: `whatweb` (ruby), `nikto` (perl)
  - data: nuclei templates + **SecLists** ที่ `/usr/share/seclists`
  ตัวไหนโหลด/บิลด์พลาดจะข้าม (ไม่ล้ม build) hexstrike รายงาน `unavailable` เฉยๆ
  > ⚠️ build นานขึ้นมาก (Go compile หลายตัว) + image ใหญ่ขึ้น (SecLists ~1GB+)
  > ไม่อยากได้ SecLists: แก้ `docker-compose.mac.yml` → `INSTALL_SECLISTS: "false"`
  > wordlist สำหรับ ffuf/gobuster: `/usr/share/seclists/...` หรือ `/usr/share/dirb/wordlists/common.txt`
- **อยากรัน hexstrike-server แบบ native แทน** (เร็วกว่า build image / ใช้ tool ที่
  brew ลงได้ครบกว่า) → ใช้ `1-install-tools.sh` + `2-run-hexstrike.sh` แล้ว **ไม่ต้อง
  ใช้** `docker-compose.mac.yml` (ขึ้น `docker compose up -d` เฉยๆ hexstrike-mcp จะ
  วิ่งออกไปหา server บน host ผ่าน `host.docker.internal:8888` — ดูค่าดีฟอลต์ใน compose)
- `llama.env`, `logs/`, `hexstrike-env/` ถูก gitignore ไว้ ไม่ขึ้น git
- ครั้งแรก build image `hexstrike-server.arm64` ใช้เวลาหลายนาที (compile python deps
  บางตัว) — ครั้งถัดไป docker cache ไว้ให้
