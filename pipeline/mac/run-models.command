#!/usr/bin/env bash
# =============================================================================
# "ปุ่มเดียว เฉพาะโมเดล" — ดับเบิลคลิกเพื่อรัน llama-server 2 ตัวพร้อมกัน
#   • orchestrator (Tiel)  :8090
#   • specialist           :8091  (SHA256-verified + sandbox ห้ามออกเน็ต)
# ไม่แตะ docker/console เลย (ต่างจาก start.command ที่ขึ้นทั้ง stack)
#
# ใช้ครั้งเดียว: แก้ path โมเดลใน pipeline/mac/llama.env  แล้วดับเบิลคลิกไฟล์นี้
# ปิดโมเดลทั้งคู่:  pkill -f llama-server
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LLAMA_PORT="${LLAMA_PORT:-8090}"
LLAMA_PORT_SPECIALIST="${LLAMA_PORT_SPECIALIST:-8091}"

echo "════════════════════════════════════════════════════════════"
echo "  Project-Malaria — รันโมเดล 2 ตัว (Tiel :8090 + specialist :8091)"
echo "════════════════════════════════════════════════════════════"

if [ ! -f "$HERE/llama.env" ]; then
  echo "⚠️  ไม่พบ pipeline/mac/llama.env"
  echo "    cp pipeline/mac/llama.env.example pipeline/mac/llama.env แล้วแก้ path gguf ก่อน"
  exit 1
fi
source "$HERE/llama.env"

# สตาร์ท llama-server หนึ่งตัว (ข้ามถ้าพอร์ตมีคนฟังอยู่แล้ว)
start_llama() {
  local port="$1" cmd="$2" label="$3" logf="$4"
  if curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
    echo "✓ ${label} ตอบอยู่แล้วบน :${port} — ข้าม"; return
  fi
  if [ -z "$cmd" ]; then
    echo "• ${label}: ไม่มีคำสั่งใน llama.env — ข้าม"; return
  fi
  mkdir -p "$HERE/logs"
  nohup bash -c "$cmd" > "$HERE/logs/${logf}" 2>&1 &
  echo "… กำลังรอ ${label} ขึ้นบน :${port} (log: pipeline/mac/logs/${logf})"
  for _ in $(seq 1 120); do
    curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$' && break
    sleep 1
  done
  if curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
    echo "✓ ${label} พร้อม"
  else
    echo "⚠️  ${label} ยังไม่ตอบใน 120 วิ — เช็ค logs/${logf} (โมเดลใหญ่โหลด/prefill นานได้)"
  fi
}

verify_sha256() {
  local file="$1" expected="$2" label="$3"
  [ -z "$expected" ] && { echo "• ${label}: ไม่ได้ตั้ง SHA256 — ข้ามการเช็ก (แนะนำให้ตั้ง)"; return 0; }
  [ ! -f "$file" ] && { echo "✗ ${label}: ไม่พบไฟล์ $file"; return 1; }
  echo "… เช็ก SHA256 ของ ${label} (ไฟล์ใหญ่ รอสักครู่)"
  local got; got="$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}')"
  [ "$got" = "$expected" ] && { echo "✓ ${label}: SHA256 ตรง"; return 0; }
  echo "✗ ${label}: SHA256 ไม่ตรง! expected=$expected got=${got:-<อ่านไม่ได้>}"; return 1
}

# ── orchestrator (Tiel) ──────────────────────────────────────────────────────
start_llama "${LLAMA_PORT}" "${LLAMA_CMD:-}" "orchestrator (Tiel-35B)" "llama.log"

# ── specialist: SHA256 → sandbox → สตาร์ท ────────────────────────────────────
SPEC_CMD="${LLAMA_CMD_SPECIALIST:-}"
if [ -n "$SPEC_CMD" ]; then
  if ! verify_sha256 "${SPECIALIST_MODEL_FILE:-}" "${SPECIALIST_MODEL_SHA256:-}" "specialist model"; then
    echo "⚠️  ข้ามการสตาร์ท specialist — ไฟล์ไม่ผ่านการตรวจ"
    SPEC_CMD=""
  fi
fi
if [ -n "$SPEC_CMD" ] && [ "${SPECIALIST_SANDBOX:-1}" = "1" ]; then
  if command -v sandbox-exec >/dev/null 2>&1 && [ -f "${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}" ]; then
    SPEC_CMD="sandbox-exec -f \"${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}\" $SPEC_CMD"
    echo "• specialist: ขังใน sandbox ห้ามออกเน็ต (ปิดด้วย SPECIALIST_SANDBOX=0)"
  else
    echo "• specialist: ข้าม sandbox (ไม่พบ sandbox-exec หรือ profile)"
  fi
fi
start_llama "${LLAMA_PORT_SPECIALIST}" "$SPEC_CMD" "specialist (exploit model)" "llama-specialist.log"

# ── summarizer (:8092) — โมเดลเล็กสำหรับ dashboard (SHA เช็กถ้าตั้งไว้, ไม่ sandbox) ──
SUM_CMD="${LLAMA_CMD_SUMMARIZER:-}"
if [ -n "$SUM_CMD" ] && ! verify_sha256 "${SUMMARIZER_MODEL_FILE:-}" "${SUMMARIZER_MODEL_SHA256:-}" "summarizer model"; then
  echo "⚠️  ข้ามการสตาร์ท summarizer — ไฟล์ไม่ผ่านการตรวจ"
  SUM_CMD=""
fi
start_llama "${LLAMA_PORT_SUMMARIZER:-8092}" "$SUM_CMD" "summarizer (Qwen2.5-3B)" "llama-summarizer.log"

# ── vision: SHA เช็กถ้าตั้ง + ต้องมี mmproj → สตาร์ท ─────────────────────────
VIS_CMD="${LLAMA_CMD_VISION:-}"
if [ -n "$VIS_CMD" ] && ! verify_sha256 "${VISION_MODEL_FILE:-}" "${VISION_MODEL_SHA256:-}" "vision model"; then
  echo "⚠️  ข้ามการสตาร์ท vision — ไฟล์ไม่ผ่านการตรวจ"
  VIS_CMD=""
fi
if [ -n "$VIS_CMD" ] && [ ! -f "${VISION_MMPROJ_FILE:-}" ]; then
  echo "⚠️  ข้ามการสตาร์ท vision — ไม่พบไฟล์ mmproj (จำเป็นสำหรับอ่านภาพ): ${VISION_MMPROJ_FILE:-<ไม่ได้ตั้ง>}"
  VIS_CMD=""
fi
start_llama "${LLAMA_PORT_VISION:-8093}" "$VIS_CMD" "vision (Qwen2.5-VL-7B)" "llama-vision.log"

echo ""
echo "──────────────────────────────────────────────────────────────"
echo "โมเดลพร้อม:"
echo "  • Tiel       : http://localhost:${LLAMA_PORT}/v1/models"
echo "  • specialist : http://localhost:${LLAMA_PORT_SPECIALIST}/v1/models"
echo "  • summarizer : http://localhost:${LLAMA_PORT_SUMMARIZER:-8092}/v1/models"
echo "  • vision     : http://localhost:${LLAMA_PORT_VISION:-8093}/v1/models"
echo "ปิดทั้งหมด: pkill -f llama-server"
echo "──────────────────────────────────────────────────────────────"
