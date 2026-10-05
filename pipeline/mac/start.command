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
LLAMA_PORT_SPECIALIST="${LLAMA_PORT_SPECIALIST:-8091}"

echo "════════════════════════════════════════════════════════════"
echo "  Project-Malaria — start ทุกอย่าง (Mac / Apple Silicon)"
echo "════════════════════════════════════════════════════════════"

# โหลด llama.env ก่อน (มีคำสั่งของทั้ง orchestrator + specialist) เพื่อให้สตาร์ท
# ได้ทั้งคู่ แม้ตัวใดตัวหนึ่งจะขึ้นอยู่แล้ว
[ -f "$HERE/llama.env" ] && { echo "[1/3] อ่าน pipeline/mac/llama.env"; source "$HERE/llama.env"; }

# สตาร์ท llama-server หนึ่งตัว: port, คำสั่ง, ป้ายชื่อ
start_llama() {
  local port="$1" cmd="$2" label="$3" logf="$4"
  if curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
    echo "      ✓ ${label} ตอบอยู่แล้วบน :${port} — ข้าม"; return
  fi
  if [ -z "$cmd" ]; then
    echo "      • ${label}: ไม่มีคำสั่งใน llama.env (ข้าม) — ถ้าต้องใช้ ตั้ง LLAMA_CMD ให้ครบ"
    return
  fi
  mkdir -p "$HERE/logs"
  nohup bash -c "$cmd" > "$HERE/logs/${logf}" 2>&1 &
  echo "      กำลังรอ ${label} ขึ้นบน :${port} (log: pipeline/mac/logs/${logf})…"
  for _ in $(seq 1 90); do
    curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$' && break
    sleep 1
  done
  if curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
    echo "      ✓ ${label} พร้อม"
  else
    echo "      ⚠️  ${label} ยังไม่ตอบใน 90 วิ — เช็ค logs/${logf} (โมเดลใหญ่ prefill นานได้)"
  fi
}

# เช็ก SHA256 ของไฟล์โมเดลกับค่าที่คาดหวัง — คืน 0 = ผ่าน/ข้าม, 1 = ไม่ผ่าน (ห้ามสตาร์ท)
verify_sha256() {
  local file="$1" expected="$2" label="$3"
  if [ -z "$expected" ]; then
    echo "      • ${label}: ไม่ได้ตั้ง SHA256 — ข้ามการเช็ก (แนะนำให้ตั้งใน llama.env)"
    return 0
  fi
  if [ ! -f "$file" ]; then
    echo "      ✗ ${label}: ไม่พบไฟล์โมเดล — $file"
    return 1
  fi
  echo "      กำลังเช็ก SHA256 ของ ${label} (ไฟล์ใหญ่ อาจใช้เวลาสักครู่)…"
  local got
  got="$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}')"
  if [ "$got" = "$expected" ]; then
    echo "      ✓ ${label}: SHA256 ตรงกับที่ประกาศไว้"
    return 0
  fi
  echo "      ✗ ${label}: SHA256 ไม่ตรง!"
  echo "          expected = $expected"
  echo "          got      = ${got:-<อ่านไฟล์ไม่ได้>}"
  return 1
}

# ── 1) โมเดล: llama.cpp native (orchestrator :8090 + specialist :8091) ───────
echo "[1/3] โมเดล llama.cpp (native — ต้องใช้ Metal GPU)…"
if [ ! -f "$HERE/llama.env" ]; then
  echo "      ⚠️  ไม่มี pipeline/mac/llama.env — คัดลอกจาก example แล้วแก้ path gguf:"
  echo "          cp pipeline/mac/llama.env.example pipeline/mac/llama.env"
  echo "      (จะ start container ต่อ แต่ task โมเดลจะยังไม่ทำงานจนกว่า llama.cpp จะขึ้น)"
fi
start_llama "${LLAMA_PORT}" "${LLAMA_CMD:-}" "orchestrator (Tiel-35B)" "llama.log"

# ── specialist (:8091) — hardening: เช็ก SHA256 → ขังไม่ให้ออกเน็ต → สตาร์ท ──
SPEC_CMD="${LLAMA_CMD_SPECIALIST:-}"
if [ -n "$SPEC_CMD" ]; then
  # (3) ไฟล์ต้องผ่าน SHA256 ก่อน ไม่งั้นไม่สตาร์ท (กันไฟล์ถูกแก้/โหลดผิดตัว)
  if ! verify_sha256 "${SPECIALIST_MODEL_FILE:-}" "${SPECIALIST_MODEL_SHA256:-}" "specialist model"; then
    echo "      ⚠️  ข้ามการสตาร์ท specialist — ไฟล์ไม่ผ่านการตรวจ (ตั้ง SHA256 ให้ตรง หรือโหลดใหม่จาก repo ทางการ)"
    SPEC_CMD=""
  fi
fi
if [ -n "$SPEC_CMD" ] && [ "${SPECIALIST_SANDBOX:-1}" = "1" ]; then
  # (1b) ขัง process ไม่ให้เปิด connection ออกเน็ต (ยัง listen :8091 ให้ LiteLLM ได้)
  if command -v sandbox-exec >/dev/null 2>&1 && [ -f "${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}" ]; then
    SPEC_CMD="sandbox-exec -f \"${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}\" $SPEC_CMD"
    echo "      • specialist: ขังใน sandbox ห้ามออกเน็ต (ปิดด้วย SPECIALIST_SANDBOX=0 ถ้า llama ไม่ขึ้น)"
  else
    echo "      • specialist: ข้าม sandbox (ไม่พบ sandbox-exec หรือ profile) — พึ่ง SHA256 + review output แทน"
  fi
fi
start_llama "${LLAMA_PORT_SPECIALIST}" "$SPEC_CMD" "specialist (exploit model)" "llama-specialist.log"

# ── 2) container ทั้ง stack ──────────────────────────────────────────────────
echo "[2/3] docker compose up (litellm + hexstrike-server arm64 + hexstrike-mcp + harnessrouter)…"
cd "$PIPELINE" || { echo "เข้า $PIPELINE ไม่ได้"; exit 1; }
if [ ! -f .env ]; then
  echo "      (ไม่มี .env — ก็อปจาก .env.example ให้ก่อน)"
  cp .env.example .env 2>/dev/null || true
fi
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build

# ── 3) เปิดหน้า console ───────────────────────────────────────────────────────
echo "[3/3] เปิด HarnessRouter → http://localhost:3000"
open "http://localhost:3000" 2>/dev/null || true

echo ""
echo "เสร็จ. เช็คสถานะ: docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full ps"
echo "ปิดทั้งหมด:      docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full down"
echo "(llama.cpp ที่สตาร์ทจากสคริปต์นี้รัน background — ปิดด้วย: pkill -f llama-server)"
