# Mac (Apple Silicon / arm64) setup

บน Apple Silicon ตัว Kali `hexstrike-server` image เป็น **amd64** → รันผ่าน emulation
(QEMU) ช้าเกินไปสำหรับ tool สแกน ดังนั้นบน Mac ให้:

- **โมเดล** → รัน `llama.cpp` native (Metal) บน `:8080`
- **HexStrike server** → รัน **native** (สคริปต์ในโฟลเดอร์นี้) บน `:8888` — ไม่ใช้ docker
- **harnessrouter + hexstrike-mcp** → docker ตามปกติ (ไม่ต้อง `--profile full`)

```
llama.cpp (native :8080) ◄── litellm (docker) ◄── harnessrouter (docker)
                                                        │
hexstrike-server (native :8888) ◄── hexstrike-mcp (docker) ◄┘
         ▲ ต่อผ่าน host.docker.internal:8888
```

## ขั้นตอน

1. **เครื่องมือความปลอดภัย** (ครั้งเดียว):
   ```bash
   bash pipeline/mac/1-install-tools.sh
   ```

2. **รัน HexStrike server** (native, เปิดค้างไว้ 1 terminal):
   ```bash
   bash pipeline/mac/2-run-hexstrike.sh
   ```
   ครั้งแรกจะสร้าง venv + ลง deps ให้เอง รอจนเห็น server ฟังที่ `:8888`

3. **container อื่น** (harnessrouter + hexstrike-mcp + litellm):
   ```bash
   cd pipeline
   docker compose up -d --build          # ไม่ต้อง --profile full บน Mac
   ```
   ตั้ง `.env`: `HEXSTRIKE_SERVER=http://host.docker.internal:8888` (ค่าเริ่มต้นอยู่แล้ว)
   → hexstrike-mcp ใน docker จะวิ่งออกมาหา server native บน host

4. **เช็ค**:
   ```bash
   curl http://localhost:8888/health          # hexstrike server native
   curl http://localhost:4000/v1/models       # litellm
   # harnessrouter: เปิด http://localhost:3000
   ```

## หมายเหตุ
- ถ้า `pip install` ล้มเรื่อง `mitmproxy` (Python ใหม่เกิน) ลองสร้าง venv ด้วย Python 3.12:
  `brew install python@3.12` แล้วแก้บรรทัด `python3 -m venv` ในสคริปต์เป็น `python3.12`
- `hexstrike-env/` (venv) ถูก gitignore ไว้ ไม่ขึ้น git
- เครื่องมือที่ไม่มีใน brew (metasploit ฯลฯ) ติดตั้งแยกได้ — ที่ขาด hexstrike รายงาน
  ว่า unavailable เฉยๆ ไม่ crash
