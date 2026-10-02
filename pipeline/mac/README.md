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
แล้วขึ้น stack ด้วย override ของ Mac:
```bash
cd pipeline
docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d --build
```
Docker Desktop จะเห็น project นี้ กดปุ่ม ▶ / ⏹ สตาร์ท/หยุดทุก container พร้อมกันได้
(หลังจากครั้งแรกที่ `up` แล้ว)

## เช็ค
```bash
curl http://localhost:8090/v1/models   # llama.cpp native (โมเดล)
curl http://localhost:4000/v1/models   # litellm (big-brain → llama.cpp)
curl http://localhost:8888/health      # hexstrike-server (ใน docker, arm64)
# harnessrouter: เปิด http://localhost:3000
```

## หมายเหตุ
- **เครื่องมือความปลอดภัย**: `Dockerfile.hexstrike-server.arm64` ลง core tools จาก
  debian repo (nmap, nikto, sqlmap, gobuster, ffuf, feroxbuster, hydra, john ฯลฯ)
  ตัวที่ไม่มีใน debian (subfinder/amass/nuclei รุ่นใหม่) hexstrike จะรายงานว่า
  `unavailable` เฉยๆ ไม่ crash — เพิ่มทีหลังได้
- **อยากรัน hexstrike-server แบบ native แทน** (เร็วกว่า build image / ใช้ tool ที่
  brew ลงได้ครบกว่า) → ใช้ `1-install-tools.sh` + `2-run-hexstrike.sh` แล้ว **ไม่ต้อง
  ใช้** `docker-compose.mac.yml` (ขึ้น `docker compose up -d` เฉยๆ hexstrike-mcp จะ
  วิ่งออกไปหา server บน host ผ่าน `host.docker.internal:8888` — ดูค่าดีฟอลต์ใน compose)
- `llama.env`, `logs/`, `hexstrike-env/` ถูก gitignore ไว้ ไม่ขึ้น git
- ครั้งแรก build image `hexstrike-server.arm64` ใช้เวลาหลายนาที (compile python deps
  บางตัว) — ครั้งถัดไป docker cache ไว้ให้
