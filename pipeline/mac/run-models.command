#!/usr/bin/env bash
# =============================================================================
# "ปุ่มเดียว เฉพาะโมเดล" — ดับเบิลคลิกเพื่อรัน llama-server 2 ตัวพร้อมกัน
#   • orchestrator         :8090
#   • cyber-model          :8091  (SHA256-verified + sandbox ห้ามออกเน็ต)
# ไม่แตะ docker/console เลย (ต่างจาก start.command ที่ขึ้นทั้ง stack)
#
# ใช้ครั้งเดียว: แก้ path โมเดลใน pipeline/mac/llama.env  แล้วดับเบิลคลิกไฟล์นี้
# ปิดโมเดลทั้งคู่:  pkill -f llama-server
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LLAMA_PORT="${LLAMA_PORT:-8090}"
LLAMA_PORT_SPECIALIST="${LLAMA_PORT_SPECIALIST:-8091}"
LLAMA_PORT_SUMMARIZER="${LLAMA_PORT_SUMMARIZER:-8092}"
LLAMA_PORT_VISION="${LLAMA_PORT_VISION:-8093}"
CONTROL_PORT="${CONTROL_PORT:-8010}"
PIPELINE="$(cd "$HERE/.." && pwd)"

echo "════════════════════════════════════════════════════════════"
echo "  Project-Malaria — รันโมเดล + Model Studio API (:8010)"
echo "════════════════════════════════════════════════════════════"

if [ ! -f "$HERE/llama.env" ]; then
  echo "[WARN] ไม่พบ pipeline/mac/llama.env"
  echo "       cp pipeline/mac/llama.env.example pipeline/mac/llama.env แล้วแก้ path gguf ก่อน"
  exit 1
fi
source "$HERE/llama.env"

mkdir -p "$HERE/logs"

# ให้ control_plane.py (:8010) ขึ้นด้วยเสมอเพื่อให้ Model Studio API ใช้งานได้
if [ -f "$PIPELINE/control_plane.py" ] && command -v python3 >/dev/null 2>&1; then
  if curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${CONTROL_PORT}/healthz" 2>/dev/null | grep -q '^200$'; then
    echo "[OK] Model Studio API (:8010) ทำงานอยู่แล้ว"
  else
    nohup python3 "$PIPELINE/control_plane.py" >> "$HERE/logs/control-plane.log" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    for _ in $(seq 1 10); do
      curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${CONTROL_PORT}/healthz" 2>/dev/null | grep -q '^200$' && break
      sleep 1
    done
    if curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${CONTROL_PORT}/healthz" 2>/dev/null | grep -q '^200$'; then
      echo "[OK] Model Studio API (:8010) พร้อม"
    else
      echo "[WARN] Model Studio API (:8010) ยังไม่ตอบ — เช็ค logs/control-plane.log"
    fi
  fi
fi

# สตาร์ท llama-server หนึ่งตัว (ข้ามถ้าพอร์ตมีคนฟังอยู่แล้ว)
start_llama() {
  local port="$1" cmd="$2" label="$3" logf="$4"
  if curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/health" 2>/dev/null | grep -q '^200$' || \
     curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
    echo "[OK] ${label} ตอบอยู่แล้วบน :${port} — ข้าม"; return
  fi
  if [ -z "$cmd" ]; then
    echo "• ${label}: ไม่มีคำสั่งใน llama.env — ข้าม"; return
  fi
  nohup bash -c "$cmd" >> "$HERE/logs/${logf}" 2>&1 < /dev/null &
  disown 2>/dev/null || true
  echo "… กำลังรอ ${label} ขึ้นบน :${port} (log: pipeline/mac/logs/${logf})"
  for _ in $(seq 1 120); do
    if curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/health" 2>/dev/null | grep -q '^200$' || \
       curl -sS -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/v1/models" 2>/dev/null | grep -qE '^(200|401)$'; then
      echo "[OK] ${label} พร้อม"
      return
    fi
    sleep 1
  done
  echo "[WARN] ${label} ยังไม่ตอบใน 120 วิ — เช็ค logs/${logf} (โมเดลใหญ่โหลด/prefill นานได้)"
}

verify_sha256() {
  local file="$1" expected="$2" label="$3"
  [ -z "$expected" ] && { echo "• ${label}: ไม่ได้ตั้ง SHA256 — ข้ามการเช็ก (แนะนำให้ตั้ง)"; return 0; }
  [ ! -f "$file" ] && { echo "[FAIL] ${label}: ไม่พบไฟล์ $file"; return 1; }
  echo "… เช็ก SHA256 ของ ${label} (ไฟล์ใหญ่ รอสักครู่)"
  local got; got="$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}')"
  [ "$got" = "$expected" ] && { echo "[OK] ${label}: SHA256 ตรง"; return 0; }
  echo "[FAIL] ${label}: SHA256 ไม่ตรง! expected=$expected got=${got:-<อ่านไม่ได้>}"; return 1
}

# ── orchestrator (:8090) ─────────────────────────────────────────────────────
DEFAULT_INKLING_CMD="${HOME}/.unsloth/llama.cpp/build/bin/llama-server -m ${HOME}/Downloads/Inkling-2-Mini-Q4_K_M.gguf --host 0.0.0.0 --port 8090 --alias cybermodel -ngl 99 -fa on --spec-default --no-context-shift --ctx-checkpoints 20 --no-reasoning-preserve -c 65536 -np 1 -t 8 -tb 10 --jinja --chat-template-kwargs '{\"reasoning_effort\": \"medium\"}'"
if [ "${ORCHESTRATOR_PROFILE:-inkling2}" = "inkling2" ]; then
  SPEC_LABEL="ngram-mod"; [ "${INKLING2_USE_DSPARK:-0}" = "1" ] && SPEC_LABEL="DSpark Q8_0"
  echo "• Orchestrator Config: Profile=inkling2 (Unsloth Engine, Spec=${SPEC_LABEL}) | FlashAttn=on | Effort=${INKLING2_REASONING_EFFORT:-medium} | Threads=8/10 | Ctx=${LLAMA_CTX_MAIN:-65536} (1 slot)"
else
  echo "• Thermal Config: Profile=${ORCHESTRATOR_PROFILE:-orchestrator} (Unsloth Engine + Spec) | FlashAttn=on | KV=${LLAMA_KV_TYPE:-q8_0} | Threads=${LLAMA_THREADS:-6}/${LLAMA_THREADS_BATCH:-8} | Ctx=${LLAMA_CTX_MAIN:-65536} (1 slot)"
fi
start_llama "${LLAMA_PORT}" "${LLAMA_CMD:-$DEFAULT_INKLING_CMD}" "orchestrator (${ORCHESTRATOR_PROFILE:-inkling2})" "llama.log"

# ── specialist: SHA256 → sandbox → สตาร์ท ────────────────────────────────────
SPEC_CMD="${LLAMA_CMD_SPECIALIST:-}"
if [ -n "$SPEC_CMD" ]; then
  if ! verify_sha256 "${SPECIALIST_MODEL_FILE:-}" "${SPECIALIST_MODEL_SHA256:-}" "specialist model"; then
    echo "[WARN] ข้ามการสตาร์ท specialist — ไฟล์ไม่ผ่านการตรวจ"
    SPEC_CMD=""
  fi
fi
if [ -n "$SPEC_CMD" ] && [ "${SPECIALIST_SANDBOX:-1}" = "1" ]; then
  case "$SPEC_CMD" in
    *sandbox-exec*) ;;
    *)
      if command -v sandbox-exec >/dev/null 2>&1 && [ -f "${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}" ]; then
        SPEC_CMD="sandbox-exec -f \"${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}\" $SPEC_CMD"
        echo "• specialist: ขังใน sandbox ห้ามออกเน็ต (ปิดด้วย SPECIALIST_SANDBOX=0)"
      else
        echo "• specialist: ข้าม sandbox (ไม่พบ sandbox-exec หรือ profile)"
      fi
      ;;
  esac
fi
start_llama "${LLAMA_PORT_SPECIALIST}" "$SPEC_CMD" "cyber-model (exploit model)" "llama-specialist.log"

# ── summarizer (:8092) — โมเดลเล็กสำหรับ dashboard (SHA เช็กถ้าตั้งไว้, ไม่ sandbox) ──
SUM_CMD="${LLAMA_CMD_SUMMARIZER:-}"
if [ -n "$SUM_CMD" ] && ! verify_sha256 "${SUMMARIZER_MODEL_FILE:-}" "${SUMMARIZER_MODEL_SHA256:-}" "summarizer model"; then
  echo "[WARN] ข้ามการสตาร์ท summarizer — ไฟล์ไม่ผ่านการตรวจ"
  SUM_CMD=""
fi
start_llama "${LLAMA_PORT_SUMMARIZER:-8092}" "$SUM_CMD" "summarizer (Qwen2.5-3B)" "llama-summarizer.log"

# ── vision: SHA เช็กถ้าตั้ง + ต้องมี mmproj → สตาร์ท ─────────────────────────
VIS_CMD="${LLAMA_CMD_VISION:-}"
if [ -n "$VIS_CMD" ] && ! verify_sha256 "${VISION_MODEL_FILE:-}" "${VISION_MODEL_SHA256:-}" "vision model"; then
  echo "[WARN] ข้ามการสตาร์ท vision — ไฟล์ไม่ผ่านการตรวจ"
  VIS_CMD=""
fi
if [ -n "$VIS_CMD" ] && [ ! -f "${VISION_MMPROJ_FILE:-}" ]; then
  echo "[WARN] ข้ามการสตาร์ท vision — ไม่พบไฟล์ mmproj (จำเป็นสำหรับอ่านภาพ): ${VISION_MMPROJ_FILE:-<ไม่ได้ตั้ง>}"
  VIS_CMD=""
fi
start_llama "${LLAMA_PORT_VISION:-8093}" "$VIS_CMD" "vision (Qwen2.5-VL-7B)" "llama-vision.log"

echo ""
echo "──────────────────────────────────────────────────────────────"
echo "โมเดลพร้อม:"
echo "  • Orchestrator : http://localhost:${LLAMA_PORT}/v1/models"
echo "  • Cyber-Model  : http://localhost:${LLAMA_PORT_SPECIALIST}/v1/models"
echo "  • summarizer   : http://localhost:${LLAMA_PORT_SUMMARIZER:-8092}/v1/models"
echo "  • vision       : http://localhost:${LLAMA_PORT_VISION:-8093}/v1/models"
echo "ปิดทั้งหมด: pkill -f llama-server"
echo "──────────────────────────────────────────────────────────────"
