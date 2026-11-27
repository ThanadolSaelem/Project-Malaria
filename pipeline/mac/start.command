#!/usr/bin/env bash
# =============================================================================
# "ปุ่มเดียว" บน Mac (Apple Silicon) — ดับเบิลคลิกไฟล์นี้ใน Finder ก็ start ทุกอย่างครบ
# -----------------------------------------------------------------------------
# Host Services (macOS Native — Metal GPU / Host Control):
#   • control_plane.py    (:8010) Model Studio API & Node Bridge
#   • llama-server        (:8090) Orchestrator (Inkling-2-Mini Q4_K_M + Spec)
#   • llama-server        (:8091) Cyber-Model (Security Specialist + Sandbox)
#   • llama-server        (:8092) Summarizer (Observer & Intent Classifier)
#   • llama-server        (:8093) Vision & OCR (Qwen2.5-VL + mmproj)
#   • summarize-watch.py  (:8005) Observer Real-Time Dashboard
#   • mobile-link.sh              LAN IP Watcher สำหรับมือถือ/แท็บเล็ต
#
# Docker Compose Full Stack (--profile full):
#   • unified-gateway (:3000), unified-web, litellm (:4000), qwen-code (:3080),
#     artex (:8787) + artex-db, scope-sentry (:8082) + mongodb + redis + scan,
#     hexstrike-server (:8888) + hexstrike-mcp (:8001), memory-mcp (:8002),
#     specialist-mcp (:8003), search-mcp (:8004) + searxng, vflat-scan (:8006),
#     rea-mcp (:8007), cve-mcp (:8009), shot (:9000)
#
# ตัวเลือก:
#   ./start.command --build     บังคับ rebuild Docker images ด้วย
#   MALARIA_NO_OPEN=1           ไม่เปิด browser อัตโนมัติ (เหมาะสำหรับรันจาก CLI/สคริปต์)
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PIPELINE="$(cd "$HERE/.." && pwd)"
CONTROL_PORT="${CONTROL_PORT:-8010}"
WATCH_PORT="${WATCH_PORT:-8005}"
LLAMA_PORT="${LLAMA_PORT:-8090}"
LLAMA_PORT_SPECIALIST="${LLAMA_PORT_SPECIALIST:-8091}"
LLAMA_PORT_SUMMARIZER="${LLAMA_PORT_SUMMARIZER:-8092}"
LLAMA_PORT_VISION="${LLAMA_PORT_VISION:-8093}"

DO_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) DO_BUILD=1 ;;
  esac
done

mkdir -p "$HERE/logs"

http_code() {
  curl -sS -m 2 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || echo "000"
}

wait_http() {
  local url="$1" max_secs="$2" pattern="$3"
  local code
  for _ in $(seq 1 "$max_secs"); do
    code="$(http_code "$url")"
    if echo "$code" | grep -qE "$pattern"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

check_status_line() {
  local name="$1" url="$2" pattern="$3"
  local code
  code="$(http_code "$url")"
  if echo "$code" | grep -qE "$pattern"; then
    printf "  [OK]   %-34s %s (HTTP %s)\n" "$name" "$url" "$code"
  else
    printf "  [WARN] %-34s %s (HTTP %s)\n" "$name" "$url" "$code"
  fi
}

echo "════════════════════════════════════════════════════════════"
echo "  Project-Malaria — Start ทุก Service ครบทั้ง Host + Docker"
echo "════════════════════════════════════════════════════════════"

# ── [1/5] ตรวจสอบ Docker Desktop + ซิงก์ config ─────────────────────────────
echo "[1/5] ตรวจสอบ Docker Desktop และซิงก์ Config กลาง…"
if ! docker info >/dev/null 2>&1; then
  echo "      … Docker Desktop ยังไม่พร้อม — กำลังเปิด Docker Desktop และรอสูงสุด 90 วินาที"
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 90); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
  if ! docker info >/dev/null 2>&1; then
    echo "      [FAIL] Docker Desktop ยังไม่พร้อมภายใน 90 วินาที — กรุณาเปิด Docker Desktop แล้วลองใหม่"
    exit 1
  fi
fi
echo "      [OK] Docker Desktop พร้อมใช้งาน"

if command -v python3 >/dev/null 2>&1 && [ -f "$PIPELINE/control_plane.py" ]; then
  if python3 -c "import sys; sys.path.insert(0, '$PIPELINE'); import control_plane as cp; cp.sync_all_configs(cp.load_node_config())" >/dev/null 2>&1; then
    echo "      [OK] ซิงก์ node-config.json → litellm-config.yaml / settings.json แล้ว"
  else
    echo "      [WARN] ซิงก์ config ไม่สำเร็จ (ดำเนินการต่อ)"
  fi
fi

# ── [2/5] สตาร์ท Model Studio API (:8010) บน Host ก่อนเสมอ ─────────────────
echo "[2/5] Model Studio API & Control Plane (:8010)…"
if [ -f "$PIPELINE/control_plane.py" ] && command -v python3 >/dev/null 2>&1; then
  if wait_http "http://127.0.0.1:${CONTROL_PORT}/healthz" 1 '^200$'; then
    echo "      [OK] control_plane.py ทำงานอยู่แล้วบน :${CONTROL_PORT}"
  else
    nohup python3 "$PIPELINE/control_plane.py" >> "$HERE/logs/control-plane.log" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    if wait_http "http://127.0.0.1:${CONTROL_PORT}/healthz" 15 '^200$'; then
      echo "      [OK] control_plane.py พร้อมใช้งานบน :${CONTROL_PORT}"
    else
      echo "      [WARN] control_plane.py ยังไม่ตอบบน :${CONTROL_PORT} — เช็ค logs/control-plane.log"
    fi
  fi
else
  echo "      [WARN] ไม่พบ control_plane.py หรือ python3"
fi

# ── [3/5] สตาร์ท Local GGUF Models (:8090–:8093) บน Metal GPU ─────────────────
echo "[3/5] Local GGUF Models บน Metal GPU (อ่านค่าจาก llama.env + llama.studio.env)…"
if [ -f "$HERE/llama.env" ]; then
  # shellcheck disable=SC1091
  source "$HERE/llama.env"
else
  echo "      [WARN] ไม่พบ pipeline/mac/llama.env — ใช้คำสั่ง Inkling-2-Mini เริ่มต้นสำหรับ :${LLAMA_PORT}"
fi

start_llama() {
  local port="$1" cmd="$2" label="$3" logf="$4"
  if wait_http "http://127.0.0.1:${port}/health" 1 '^200$' || wait_http "http://127.0.0.1:${port}/v1/models" 1 '^(200|401)$'; then
    echo "      [OK] ${label} ตอบอยู่แล้วบน :${port} — ข้าม"
    return
  fi
  if [ -z "$cmd" ]; then
    echo "      • ${label}: ไม่มีคำสั่งใน config (ข้าม)"
    return
  fi
  nohup bash -c "$cmd" >> "$HERE/logs/${logf}" 2>&1 < /dev/null &
  disown 2>/dev/null || true
  echo "      … กำลังโหลด ${label} บน :${port} (log: pipeline/mac/logs/${logf})"
  for _ in $(seq 1 120); do
    if wait_http "http://127.0.0.1:${port}/health" 1 '^200$' || wait_http "http://127.0.0.1:${port}/v1/models" 1 '^(200|401)$'; then
      echo "      [OK] ${label} พร้อมใช้งานบน :${port}"
      return
    fi
    sleep 1
  done
  echo "      [WARN] ${label} ยังไม่ตอบภายใน 120 วิ — เช็ค logs/${logf} (โมเดลใหญ่โหลดนานได้)"
}

verify_sha256() {
  local file="$1" expected="$2" label="$3"
  [ -z "$expected" ] && return 0
  if [ ! -f "$file" ]; then
    echo "      [FAIL] ${label}: ไม่พบไฟล์โมเดล — $file"
    return 1
  fi
  echo "      … กำลังเช็ก SHA256 ของ ${label}…"
  local got
  got="$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}')"
  if [ "$got" = "$expected" ]; then
    echo "      [OK] ${label}: SHA256 ตรง"
    return 0
  fi
  echo "      [FAIL] ${label}: SHA256 ไม่ตรง (expected=$expected got=${got:-<error>})"
  return 1
}

DEFAULT_INKLING_CMD="${HOME}/.unsloth/llama.cpp/build/bin/llama-server -m ${HOME}/Downloads/Inkling-2-Mini-Q4_K_M.gguf --spec-default --host 0.0.0.0 --port 8090 --alias cybermodel -ngl 99 -fa on --no-context-shift --ctx-checkpoints 20 --no-reasoning-preserve -c 65536 -np 1 -t 8 -tb 10 --jinja --chat-template-kwargs '{\"reasoning_effort\": \"medium\"}'"
start_llama "${LLAMA_PORT}" "${LLAMA_CMD:-$DEFAULT_INKLING_CMD}" "Orchestrator (Inkling-2-Mini)" "llama.log"

SPEC_CMD="${LLAMA_CMD_SPECIALIST:-}"
if [ -n "$SPEC_CMD" ] && ! verify_sha256 "${SPECIALIST_MODEL_FILE:-}" "${SPECIALIST_MODEL_SHA256:-}" "Cyber-Model"; then
  SPEC_CMD=""
fi
if [ -n "$SPEC_CMD" ] && [ "${SPECIALIST_SANDBOX:-1}" = "1" ]; then
  case "$SPEC_CMD" in
    *sandbox-exec*) ;;
    *)
      if command -v sandbox-exec >/dev/null 2>&1 && [ -f "${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}" ]; then
        SPEC_CMD="sandbox-exec -f \"${SPECIALIST_SANDBOX_PROFILE:-$HERE/specialist-sandbox.sb}\" $SPEC_CMD"
        echo "      • Cyber-Model: เปิด sandbox ห้ามออกเน็ต (SPECIALIST_SANDBOX=1)"
      fi
      ;;
  esac
fi
start_llama "${LLAMA_PORT_SPECIALIST}" "$SPEC_CMD" "Cyber-Model (Specialist)" "llama-specialist.log"

SUM_CMD="${LLAMA_CMD_SUMMARIZER:-}"
if [ -n "$SUM_CMD" ] && ! verify_sha256 "${SUMMARIZER_MODEL_FILE:-}" "${SUMMARIZER_MODEL_SHA256:-}" "Summarizer"; then
  SUM_CMD=""
fi
start_llama "${LLAMA_PORT_SUMMARIZER}" "$SUM_CMD" "Summarizer (Qwen2.5-3B)" "llama-summarizer.log"

VIS_CMD="${LLAMA_CMD_VISION:-}"
if [ -n "$VIS_CMD" ] && ! verify_sha256 "${VISION_MODEL_FILE:-}" "${VISION_MODEL_SHA256:-}" "Vision"; then
  VIS_CMD=""
fi
if [ -n "$VIS_CMD" ] && [ -n "${VISION_MMPROJ_FILE:-}" ] && [ ! -f "${VISION_MMPROJ_FILE}" ]; then
  echo "      [WARN] ข้าม Vision — ไม่พบไฟล์ mmproj (${VISION_MMPROJ_FILE})"
  VIS_CMD=""
fi
start_llama "${LLAMA_PORT_VISION}" "$VIS_CMD" "Vision (Qwen2.5-VL-7B)" "llama-vision.log"

# ── [4/5] สตาร์ท Docker Stack ครบทั้ง Profile + Seed + Observer ─────────────
echo "[4/5] Docker Compose Full Stack (--profile full) + ScopeSentry Seed + Observer…"
cd "$PIPELINE" || { echo "เข้า $PIPELINE ไม่ได้"; exit 1; }
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env 2>/dev/null || true
fi

export HOST_LAN_IP="$("$HERE/mobile-link.sh" --ip-only 2>/dev/null || true)"
"$HERE/mobile-link.sh" --start-watcher 2>/dev/null || true

COMPOSE_ARGS=(docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d)
if [ "$DO_BUILD" = "1" ]; then
  COMPOSE_ARGS+=(--build)
fi
"${COMPOSE_ARGS[@]}"

SEED_JS='
  const hash = "72600f667c8500f32ed88ad8c098b68854cedea75715d572b0498436a97ebaa4";
  if (!db.api_key.findOne({ key_hash: hash })) {
    db.api_key.insertOne({
      name: "Malaria-MCP",
      key_hash: hash,
      key_prefix: "ssk_projec...",
      enabled: true,
      created_at: new Date(),
      last_used_at: null
    });
  }
  const ssoPwdHash = "51abb11ddcbf0147f04fa374e5af3bdd72335cec46d155b9cadaf697b547c575";
  db.user.updateOne(
    { username: "ScopeSentry" },
    { $set: { password: ssoPwdHash, role: "admin" }, $setOnInsert: { username: "ScopeSentry", created_at: new Date() } },
    { upsert: true }
  );
'
docker exec scopesentry-mongodb mongosh -u "${SCOPESENTRY_MONGO_USER:-admin}" -p "${SCOPESENTRY_MONGO_PASSWORD:-scopesentry_mongo_malaria_2026}" --authenticationDatabase admin ScopeSentry --quiet --eval "$SEED_JS" >/dev/null 2>&1 || \
docker exec scopesentry-mongodb mongosh -u root -p scopesentry_mongo_pass --authenticationDatabase admin ScopeSentry --quiet --eval "$SEED_JS" >/dev/null 2>&1 || true

if [ -f "$HERE/summarize-watch.py" ] && command -v python3 >/dev/null 2>&1; then
  if wait_http "http://127.0.0.1:${WATCH_PORT}/state" 1 '^200$'; then
    echo "      [OK] Observer Dashboard ทำงานอยู่แล้วบน :${WATCH_PORT}"
  else
    nohup python3 "$HERE/summarize-watch.py" >> "$HERE/logs/summarize-watch.log" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    if wait_http "http://127.0.0.1:${WATCH_PORT}/state" 10 '^200$'; then
      echo "      [OK] Observer Dashboard พร้อมใช้งานบน :${WATCH_PORT}"
    else
      echo "      [WARN] Observer Dashboard ยังไม่ตอบบน :${WATCH_PORT} — เช็ค logs/summarize-watch.log"
    fi
  fi
fi

# ── [5/5] ตรวจสอบความพร้อมทุก Service และเปิด Unified Portal ───────────────
echo "[5/5] ตรวจสอบ Health ของระบบทั้งหมด…"
wait_http "http://127.0.0.1:3000" 20 '^(200|302|307)$' || true

echo ""
echo "─── Host Services (macOS Native) ───────────────────────────────"
check_status_line "Model Studio API (control_plane)" "http://127.0.0.1:${CONTROL_PORT}/healthz" '^200$'
check_status_line "Orchestrator (Inkling-2-Mini)"    "http://127.0.0.1:${LLAMA_PORT}/health" '^200$'
check_status_line "Cyber-Model (Specialist)"         "http://127.0.0.1:${LLAMA_PORT_SPECIALIST}/health" '^200$'
check_status_line "Summarizer (Qwen2.5-3B)"          "http://127.0.0.1:${LLAMA_PORT_SUMMARIZER}/health" '^200$'
check_status_line "Vision (Qwen2.5-VL-7B)"           "http://127.0.0.1:${LLAMA_PORT_VISION}/health" '^200$'
check_status_line "Observer Dashboard"               "http://127.0.0.1:${WATCH_PORT}/state" '^200$'

echo ""
echo "─── Docker Stack & Gateway Endpoints ───────────────────────────"
check_status_line "Unified Web Portal (:3000)"       "http://127.0.0.1:3000/" '^(200|302|307)$'
check_status_line "Model Studio via Gateway"         "http://127.0.0.1:3000/model-studio-api/state" '^200$'
check_status_line "LiteLLM Router (:4000)"           "http://127.0.0.1:4000/health/liveliness" '^200$'
check_status_line "Deep Agent IDE (:3080)"           "http://127.0.0.1:3080/" '^(200|302|401)$'
check_status_line "ARTEX Pentest Core (:8787)"       "http://127.0.0.1:8787/api/health" '^200$'
check_status_line "ScopeSentry ASM (:8082)"          "http://127.0.0.1:8082/" '^(200|302)$'

if [ -n "${HOST_LAN_IP:-}" ]; then
  echo ""
  echo "  • เข้าจากมือถือ/แท็บเล็ต (Wi-Fi LAN): http://${HOST_LAN_IP}:3000"
fi
echo ""
echo "  • ปิดระบบทั้งหมด: $HERE/stop.command"
echo "  • Force rebuild:  $HERE/start.command --build"
echo "════════════════════════════════════════════════════════════"

if [ "${MALARIA_NO_OPEN:-0}" != "1" ]; then
  open "http://localhost:3000" 2>/dev/null || true
fi
