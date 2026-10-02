#!/usr/bin/env bash
# =============================================================================
# "ปุ่มเดียว" บน Mac (Apple Silicon) — ดับเบิลคลิกไฟล์นี้ใน Finder ก็ start ทุกอย่าง
# -----------------------------------------------------------------------------
# ลำดับที่ทำ:
#   1) เช็ค/สตาร์ท llama.cpp (โมเดล) แบบ native บน :8090  ← ต้อง native เพราะ GPU
#   2) docker compose up ทั้ง stack (litellm + hexstrike-server arm64 +
#      hexstrike-mcp + harnessrouter) ด้วย override ของ Mac
#   3) เปิดหน้า HarnessRouter ให้ (http://localhost:3000)
#
# ตั้งค่าคำสั่ง llama.cpp ของคุณได้ที่ pipeline/mac/llama.env (ดู llama.env.example)
# ถ้าไม่ตั้ง สคริปต์จะแค่เช็คว่าพอร์ต 8090 มีคนฟังอยู่แล้วหรือยัง แล้วบอกวิธีสตาร์ท
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PIPELINE="$(cd "$HERE/.." && pwd)"
LLAMA_PORT="${LLAMA_PORT:-8090}"

echo "════════════════════════════════════════════════════════════"
echo "  Project-Malaria — start ทุกอย่าง (Mac / Apple Silicon)"
echo "════════════════════════════════════════════════════════════"

# ── 1) โมเดล: llama.cpp native ───────────────────────────────────────────────
llama_up() { curl -s -o /dev/null -w '%{http_code}' "http://localhost:${LLAMA_PORT}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; }

if llama_up; then
  echo "[1/3] ✓ llama.cpp ตอบอยู่แล้วบน :${LLAMA_PORT} — ข้าม"
else
  if [ -f "$HERE/llama.env" ]; then
    # llama.env ต้อง export ตัวแปร LLAMA_CMD เป็นคำสั่งเต็มของ llama-server
    echo "[1/3] สตาร์ท llama.cpp จาก pipeline/mac/llama.env …"
    # shellcheck disable=SC1091
    source "$HERE/llama.env"
    if [ -z "${LLAMA_CMD:-}" ]; then
      echo "      ⚠️  llama.env ไม่ได้ตั้ง LLAMA_CMD — ข้ามการสตาร์ทโมเดล"
    else
      mkdir -p "$HERE/logs"
      # รัน background, log ไว้ที่ logs/llama.log
      nohup bash -c "$LLAMA_CMD" > "$HERE/logs/llama.log" 2>&1 &
      echo "      กำลังรอ llama.cpp ขึ้นบน :${LLAMA_PORT} (ดู log: pipeline/mac/logs/llama.log)…"
      for _ in $(seq 1 60); do llama_up && break; sleep 1; done
      llama_up && echo "      ✓ llama.cpp พร้อม" || echo "      ⚠️  ยังไม่ตอบใน 60 วิ — เช็ค logs/llama.log"
    fi
  else
    echo "[1/3] ⚠️  ไม่พบ llama.cpp บน :${LLAMA_PORT} และไม่มี pipeline/mac/llama.env"
    echo "      → สตาร์ทโมเดลเองก่อน เช่น:"
    echo "          llama-server -m <model.gguf> --port ${LLAMA_PORT} --host 0.0.0.0 \\"
    echo "                       --alias cybermodel -ngl 99 --jinja"
    echo "      หรือ cp pipeline/mac/llama.env.example pipeline/mac/llama.env แล้วแก้ให้ตรงเครื่อง"
    echo "      (จะ start container ต่อไปให้ แต่ task โมเดลจะยังไม่ทำงานจนกว่า llama.cpp จะขึ้น)"
  fi
fi

# ── 2) container ทั้ง stack ──────────────────────────────────────────────────
echo "[2/3] docker compose up (litellm + hexstrike-server arm64 + hexstrike-mcp + harnessrouter)…"
cd "$PIPELINE" || { echo "เข้า $PIPELINE ไม่ได้"; exit 1; }
if [ ! -f .env ]; then
  echo "      (ไม่มี .env — ก็อปจาก .env.example ให้ก่อน)"
  cp .env.example .env 2>/dev/null || true
fi
docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d --build

# ── 3) เปิดหน้า console ───────────────────────────────────────────────────────
echo "[3/3] เปิด HarnessRouter → http://localhost:3000"
open "http://localhost:3000" 2>/dev/null || true

echo ""
echo "เสร็จ. เช็คสถานะ: docker compose -f docker-compose.yml -f docker-compose.mac.yml ps"
echo "ปิดทั้งหมด:      docker compose -f docker-compose.yml -f docker-compose.mac.yml down"
echo "(llama.cpp ที่สตาร์ทจากสคริปต์นี้รัน background — ปิดด้วย: pkill -f llama-server)"
