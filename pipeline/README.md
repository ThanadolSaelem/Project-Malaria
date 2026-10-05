# Pipeline: HarnessRouter × HexStrike-AI × LiteLLM

รวมสามโปรแกรมเป็นไปป์ไลน์เดียว โดยแต่ละตัวทำงานคนละ **ชั้น** (ไม่ได้แทนกัน):

| โปรแกรม | ชั้น | หน้าที่ในไปป์ไลน์ |
|---|---|---|
| **HarnessRouter** | harness runtime | เลือกและรัน harness (Claude Code / Qwen Code / OpenCode / …) เปิด API เดียวให้ app |
| **HexStrike-AI** | tools (MCP) | ให้ harness ใช้เครื่องมือความปลอดภัย 150+ ตัวผ่าน MCP |
| **LiteLLM** | provider switch | รับ request โมเดลจาก harness แล้วสลับ NIM/Groq/Cerebras เอง กัน timeout/delay |

## ภาพรวมการไหล

```
             OpenAI Responses API (:3000)
  your app ───────────────────────────────► HarnessRouter
                                                  │  รัน harness CLI ใน sandbox ต่อ session
                                    ┌─────────────┴──────────────┐
                          โมเดล (tokens)                   เครื่องมือ (MCP)
                                    │                              │
                                    ▼                              ▼
                          LiteLLM proxy (:4000)          HexStrike MCP (:8001, HTTP)
                          model = "big-brain"                     │
                                    │                              ▼
                    ┌───────────────┼───────────────┐    HexStrike server (:8888)
                    ▼               ▼               ▼             │
                 NIM (หลัก)  →   Groq  →   Cerebras         nmap / nuclei / sqlmap / … 150+
                        (429/5xx/timeout → fallback)
```

จุดสำคัญ: harness มี **สองสายลงล่างแยกกัน** — สายโมเดลผ่าน LiteLLM, สายเครื่องมือผ่าน HexStrike MCP. ทั้งสองไม่เกี่ยวกัน จึงประกอบเป็นไปป์ไลน์เดียวได้พอดีตามที่ต้องการ

## ไฟล์ในโฟลเดอร์นี้

- `docker-compose.yml` — รันสามชั้น (litellm, hexstrike-mcp, harnessrouter) บน network เดียว + service `hexstrike-server` แบบ opt-in (profile `full`)
- `litellm-config.yaml` — chain NIM → Groq → Cerebras + `context_window_fallbacks`
- `hexstrike_mcp_http.py` — ห่อ HexStrike MCP ให้พูด HTTP (ต้นฉบับพูด stdio อย่างเดียว)
- `Dockerfile.hexstrike-mcp` — image เล็กๆ สำหรับตัวห่อข้างบน
- `Dockerfile.hexstrike-server` — image ฐาน Kali ที่รันเครื่องมือจริง (ใช้กับ profile `full`)
- `verify.sh` — เช็คทั้งสามชั้นก่อนไปเปิด Console
- `.env.example` — คีย์ provider + connection/policy ของ HarnessRouter

## ขั้นตอนติดตั้ง

### 1. ใส่คีย์
```bash
cd pipeline
cp .env.example .env
# แก้ .env ใส่ NVIDIA_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY และเปลี่ยน HR_AUTH_PASSWORD
```

### 2. ยืนยันชื่อโมเดลใน `litellm-config.yaml`
ชื่อในไฟล์เป็นตัวอย่าง ยิง `/v1/models` ของแต่ละเจ้าเช็คก่อน ถ้าเจอ 404 = ชื่อไม่ตรง ไม่ใช่ config พัง

### 3. เตรียม HexStrike **server** (ตัวที่รันเครื่องมือจริง) — เลือก 1 โหมด
`hexstrike_server.py` ต้องอยู่บนเครื่องที่ **ติดตั้งเครื่องมือครบ** (nmap, sqlmap…):

**โหมด A — รันแยกเองบน Kali/Parrot** (ควบคุมเครื่องมือได้เต็มที่)
```bash
cd hexstrike-ai-main
python3 -m venv hexstrike-env && source hexstrike-env/bin/activate
pip install -r requirements.txt
python3 hexstrike_server.py            # ฟังที่ :8888
```
คง `HEXSTRIKE_SERVER=http://host.docker.internal:8888` ใน `.env`

**โหมด B — ให้ compose build ให้** (turnkey กว่า แต่ image หนักหลาย GB)
- แก้ `.env`: `HEXSTRIKE_SERVER=http://hexstrike-server:8888`
- ใช้ `--profile full` ตอน up (ข้อ 4)
- ชุดเครื่องมือใน image เป็น "core" ไม่ครบ 150 ตัว เครื่องมือที่ไม่มีจะถูกรายงานว่า unavailable — เพิ่มได้ใน `Dockerfile.hexstrike-server`

### 4. เปิดไปป์ไลน์
```bash
docker compose up -d --build                    # โหมด A
docker compose --profile full up -d --build     # โหมด B (build server ด้วย)
docker compose logs -f harnessrouter            # รอจนขึ้น: [harnessrouter] ready on :3000
```

### 4b. เช็คทุกชั้นก่อนไปต่อ
```bash
bash pipeline/verify.sh                                   # Linux / macOS / Git Bash
```
บน Windows PowerShell (ไม่มี WSL/bash) ใช้เวอร์ชัน .ps1 แทน:
```powershell
powershell -ExecutionPolicy Bypass -File pipeline\verify.ps1
```
ตรวจว่า LiteLLM ตอบ + `big-brain` ทะลุ provider จริง, HexStrike server มีชีวิต, และ MCP endpoint ตอบ — ผ่านครบค่อยไปข้อ 5
- LiteLLM ตอบที่ `http://localhost:4000/v1` (โมเดล `big-brain`) — เทสก่อนได้:
  ```bash
  curl http://localhost:4000/v1/chat/completions -H "Content-Type: application/json" \
    -d '{"model":"big-brain","messages":[{"role":"user","content":"ping"}],"max_tokens":20}'
  ```
- HexStrike MCP ตอบที่ `http://localhost:8001/mcp`
- Memory MCP ตอบที่ `http://localhost:8002/mcp`
- Specialist MCP ตอบที่ `http://localhost:8003/mcp`

### 5. ลงทะเบียน MCP ทั้ง 3 ตัวใน HarnessRouter Console
เปิด `http://localhost:3000` (login จาก `.env`) → หน้า plugins/MCP ของ harness ที่จะใช้ → เพิ่ม remote MCP (ใช้ชื่อ service ในเครือข่าย compose, **Transport**: HTTP streamable):
- **HexStrike** (เครื่องมือ pentest): `http://hexstrike-mcp:8001/mcp`
- **Memory** (จำข้ามรอบ): `http://memory-mcp:8002/mcp`
- **Specialist** (เขียน exploit): `http://specialist-mcp:8003/mcp` — tool `ask_exploit_specialist`

> Specialist จะคืน error จนกว่าจะมี llama-server ตัวที่ 2 (โมเดล offensive) ขึ้นบน
> host `:8091` + มี alias `exploit-specialist` ใน `litellm-config.yaml` (ตั้งให้แล้ว).
> บน Mac: ตั้ง `LLAMA_CMD_SPECIALIST` ใน `pipeline/mac/llama.env` (ดู example).

connection ไปยัง LiteLLM ถูกตั้งไว้ใน `.env` แล้ว (`HR_SECRET_GLOBAL_HARNESS_CONN_LITELLM` + policy) HarnessRouter จะให้ harness ยิงโมเดลผ่าน `http://litellm:4000/v1` เอง ไม่ต้องตั้งใน UI ซ้ำ

## สองเรื่องที่ต้องเช็คเอง (ผมยืนยันแทนไม่ได้จากที่นี่)

1. **sandbox ของ HarnessRouter ต้องยิงออกไปหา service อื่นได้** — HarnessRouter รัน harness ใน sandbox แยกและไม่ให้สิทธิ์พิเศษ ถ้า sandbox บล็อก egress harness จะต่อ `litellm:4000` หรือ `hexstrike-mcp:8001` ไม่ได้ ทดสอบด้วยการสั่ง task ให้ harness เรียก MCP tool สักตัว ถ้าไม่เห็น tool ให้ตรวจ network ของ sandbox ก่อนโทษ config

2. **ToS + สิทธิ์การใช้งาน** — (ก) NIM free tier นิยาม "production use" กว้างและต้องมี license สำหรับงานจริง งานเทส/วิจัยส่วนตัวโอเค; ถ้าเป็นงานลูกค้าให้สลับ Groq/Cerebras ขึ้นเป็นตัวหลัก (ข) HexStrike รันเครื่องมือโจมตีจริง ใช้ยิงได้เฉพาะเป้าหมายที่คุณมีสิทธิ์ทดสอบ (lab ของตัวเอง / เป้าที่ได้รับอนุญาตเป็นลายลักษณ์อักษร) และควรตั้ง `alwaysAllow: []` ไว้เพื่อไม่ให้รันเองอัตโนมัติ

## ทำไมสามตัวนี้ไม่ทับกัน (สรุปสั้น)
- HarnessRouter route **ข้าม harness** ไม่ได้ route ข้าม provider และ**ยังไม่มี fallback ในตัว**
- LiteLLM route **ข้าม provider** — เป็นชั้นที่เติม fallback ให้ ซึ่ง HarnessRouter ขาด
- HexStrike ไม่เกี่ยวกับสองเรื่องบน มันคือ **แหล่ง tools** ที่เสียบเข้า harness ผ่าน MCP

จึงต่อกันเป็นสายเดียวได้ ไม่ต้องเลือกตัวใดตัวหนึ่ง
