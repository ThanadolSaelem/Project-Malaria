# pipeline-deepseek — รัน stack เราบน deepseek-harness (ใน container)

ชั้นที่ทำให้ **deepseek-harness** ขับ **Tiel ผ่าน LiteLLM** และต่อ **MCP tools เดิม** (HexStrike/REA)
โดยรัน **ใน container** เป็น service `deepseek-harness` ขนานกับ `harnessrouter` ใน compose เดิม
(deepseek UI = `:3080`, HarnessRouter เดิม = `:3000`) ใช้ stack เดิมทั้งหมดร่วมกัน

## ทำไมรันใน container (ไม่ใช่ `npx` บน host)

| รันบน host (`npx`) แบบเดิม | รันใน container (ตอนนี้) |
|---|---|
| bash/command tool ของ Tiel รัน **บน Mac** — เสี่ยงกับงานมัลแวร์ | bash รัน **ใน container** = isolation |
| host ต้องลง node/pnpm/npx/corepack เอง (เปราะ) | อบใน image ครั้งเดียวตอน build |
| ต้องใช้ `localhost:xxxx` + เจอพอร์ตชน | ใช้ **ชื่อ service** (`litellm:4000` ฯลฯ) ใน network เดียว |
| หลาย step | `docker compose --profile full up -d --build` หรือดับเบิลคลิก `start.command` |

> โมเดล Tiel ยังอยู่บน host (llama.cpp Metal GPU) — containerize แค่ตัว orchestrator
> มันคุยกับ llama ผ่าน `litellm` (service) เหมือนเดิม **ไม่เสีย GPU**

## Deploy (คุณทำแค่นี้)

```bash
git checkout pipeline-deepseek && git pull origin pipeline-deepseek
# ให้ llama (Tiel:8090, vision:8093) รันอยู่ก่อน — ถ้ายัง รัน pipeline/mac/start.command
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build
# เปิด UI (token อยู่ใน log):
docker compose -f docker-compose.yml -f docker-compose.mac.yml logs deepseek-harness | grep token
```

หรือ **ดับเบิลคลิก `pipeline/mac/start.command`** — มันทำ llama → docker stack (รวม deepseek-harness)
→ เปิด :3080 ให้พร้อม token อัตโนมัติ

## เวอร์ชันต้อง pin ให้ตรง (บทเรียนสำคัญ)

deepseek-harness เป็น dev-preview และ **`dsh-mcp-client` pin peer deps แบบ exact** (ไม่ใช่ `^`)
→ เวอร์ชัน plugin **ต้องเท่ากับ runtime เป๊ะ** `Dockerfile.deepseek-harness` ตั้ง:

```
ARG DSH_VERSION=0.2.1-rc.2      # runtime dsh + dsh-mcp-client ใช้เวอร์ชันนี้คู่กัน
```

อยากอัป/ลดเวอร์ชัน: แก้ `DSH_VERSION` ที่เดียว (ทั้ง runtime + plugin ขยับพร้อมกัน) แล้ว rebuild
> `latest` dist-tag ของ dsh-mcp-client ค้างที่ `0.0.1-rc.1` (เก่ามาก) — ห้ามลงแบบไม่ระบุเวอร์ชัน

## กลไกที่ไขออกมาแล้ว (ทำไมก่อนหน้านี้ไม่ติด)

- **cordis.patch มี 2 แบบ (ต่างที่ key):** `- id: X` เดี่ยว = **patch row ที่มีอยู่** ·
  `- insert: [...]` = **สร้าง row ใหม่** (ยืนยันจาก dsh-base/dsh-web-app ที่สร้าง row ทั้งหมดด้วย insert)
  → provider = patch `llm-pi-ai` (มีอยู่แล้ว) · **MCP = `insert`** (row ใหม่) ‼️ จุดนี้คือตัวที่ทำให้ติด
  ใช้ `- id:` เดี่ยวกับ id ที่ไม่มีอยู่ = `patch: entry ... not found` แล้วถูกข้าม
- **`dsh-mcp-client` ไม่ใช่ bundle** → แค่ `dsh plugin add` ติดตั้งลง node_modules (Dockerfile ทำตอน build)
  ก็พอ — `insert` หา plugin ด้วย `name` เจอเอง **ไม่ต้องทำเป็น bundle/wrapper**
- **`dsh web --host` รับ IP จริงเท่านั้น** (wildcard `0.0.0.0` ถูก reject) → `entrypoint.sh`
  ดึง IP ของ container มา bind แล้ว Docker map `:3080` ออก host (+ `--trusted-host localhost:3080`)

## ยังต้องทำต่อ (ก่อนใช้งานจริง)

| เรื่อง | สถานะ |
|---|---|
| provider (Cyber-Tiel/Vision/NIM) โผล่ใน UI | ✅ ใช้ได้ (Tiel ตอบผ่าน LiteLLM ใน container) |
| tool `mcp__hexstrike__*` / `mcp__rea__*` | ✅ ติดแล้วด้วย `- insert:` (hexstrike log ยืนยัน ListTools 200) |
| REA 139 tool ล้น context ของ Tiel | ✅ แก้ด้วย REA router (3 meta-tool, ดู `rea_mcp_router.py`) |
| **system prompt** (กฎ + workflow + identity) | ✅ wire แล้ว: `cyber-operator.system.md` → `/dsh/AGENTS.md` (dsh-agent-instructions โหลดทุก session; identity มาจากเนื้อ AGENTS.md เอง — ไม่ patch persona เพราะ profile patch ต้องมี `name`) |
| report assembler (`assemble.py`) ใน deepseek container | ⚠️ ยังไม่ครบ — bash ของ Tiel อยู่ใน deepseek (node, ไม่มี python/pillow/`/reporting`). เนื้อหา (JSON+รูป) ทำได้ แต่ขั้น "ประกอบ .docx" ต้องรันที่ host/hexstrike-server ไปก่อน |
| memory (`memory_*`) ที่ system prompt อ้างถึง | ✅ ต่อแล้ว: KG memory-mcp (`:8002`) ผ่าน insert `mcp-memory` → `mcp__memory__*` (add/relate/search/read/delete) |

> ✅ **ความปลอดภัย:** system prompt (กฎ guardrail: local-only, redaction, ห้ามส่ง cloud,
> authorized scope) wire แล้วผ่าน `/dsh/AGENTS.md` — **หลัง deploy ให้ทดสอบยืนยัน**ว่า Tiel
> ตอบเป็น Cyber-Tiel + รู้กฎ (ถาม "what are your rules?") ก่อนเอาไปแตะตัวอย่างจริง และงานที่
> แตะตัวอย่างต้องไปทาง MCP (hexstrike/rea container) ไม่ใช่ bash ในตัว harness

## ไฟล์ในชั้นนี้

| ไฟล์ | หน้าที่ |
|---|---|
| `Dockerfile.deepseek-harness` (ที่ `pipeline/`) | build image: node + pin dsh + ติดตั้ง mcp-client เข้า profile |
| `cordis.patch.yml` | config: provider (patch `llm-pi-ai`) + MCP 2 server (service names). mount `:ro` ที่ `/config` แล้ว entrypoint copy ไป profile (เขียนได้ — UI ต้องเขียนทับไฟล์นี้เพื่อ save settings/ack) |
| `profile.package.json` | profile web (bundles: dsh-base + dsh-web-app) — COPY เข้า image |
| `entrypoint.sh` | bind IP ของ container + เปิด `:3080` |
| service `deepseek-harness` ใน `docker-compose.yml` | ผูกทุกอย่างเข้า stack (profile full) |

## ทางเลือก: รันบน host ด้วย `npx` (legacy)

`deploy.sh` ยังเก็บวิธีรันบน host (`npx @deepseek-ai/dsh web`) ไว้ — เร็วสำหรับลองเล่น
แต่ **ไม่แนะนำสำหรับงานจริง** เพราะ bash รันบน Mac (ไม่มี isolation) และต้องสลับ url เป็น localhost
