#!/usr/bin/env bash
# =============================================================================
# deploy.sh — ยก stack เดิม + launch deepseek-harness ชี้มา (รันบน host/Mac)
# -----------------------------------------------------------------------------
# เป้าหมาย: ลอง deepseek-harness "ขนาน" กับ HarnessRouter เดิม (คนละพอร์ต: 3080 vs 3000)
# stack ส่วนใหญ่ (LiteLLM/HexStrike/REA/llama) ใช้ร่วมกัน — ไฟล์นี้แค่ต่อ harness ใหม่เข้าไป
#
# ⚠️ deepseek-harness = developer preview → อาจต้องปรับ config ตอนรันจริง (ดู README)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPE="$(cd "$HERE/.." && pwd)"

# ── env ──────────────────────────────────────────────────────────────────────
export LITELLM_KEY="${LITELLM_KEY:-sk-local}"
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
# NVIDIA_API_KEY ส่งผ่านถ้าจะใช้โมเดล nim (งาน non-sensitive) — อ่านจาก pipeline/.env ถ้ามี
[ -f "$PIPE/.env" ] && set -a && . "$PIPE/.env" && set +a || true

# ── 1) llama.cpp native (host) — Tiel:8090 / vision:8093 ─────────────────────
#    deepseek-harness → LiteLLM:4000 → llama บน host. ถ้า llama ยังไม่รัน LiteLLM จะตอบ error
if ! curl -sf http://localhost:8090/health >/dev/null 2>&1; then
  echo "⚠️  ไม่พบ llama.cpp (Tiel) ที่ :8090 — รัน pipeline/mac/start.command ก่อน แล้วค่อยมาต่อ"
  echo "    (ดำเนินการต่อได้ แต่โมเดลจะยังตอบไม่ได้จนกว่า llama จะขึ้น)"
fi

# ── 2) docker stack (LiteLLM + HexStrike + REA ...) profile full ─────────────
echo "→ ยก docker stack (profile full) ..."
( cd "$PIPE" && docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d )

# ── 3) วาง config ของ deepseek-harness ───────────────────────────────────────
mkdir -p "$DSH_HOME/profiles/web"
cp "$HERE/cordis.patch.yml" "$DSH_HOME/profiles/web/cordis.patch.yml"
echo "✓ วาง cordis.patch.yml → $DSH_HOME/profiles/web/"

# system prompt: วางสำเนาไว้ให้ wire เข้า harness (ดู README — กลไกโหลด prompt ยัง verify)
cp "$PIPE/cyber-operator.system.md" "$DSH_HOME/cyber-operator.system.md"
echo "✓ วาง cyber-operator.system.md → $DSH_HOME/ (ต้อง wire เป็น system prompt ใน DSH เอง — ดู README)"

# ── 4) launch harness (web UI :3080 — ไม่ชนกับ HarnessRouter :3000) ──────────
echo "→ launching deepseek-harness (web UI → http://127.0.0.1:3080) ..."
echo "   (ครั้งแรก npx จะดาวน์โหลด package; ถ้าช้า/พัง ดู README หัวข้อ troubleshooting)"
exec npx @deepseek-ai/dsh web
