#!/usr/bin/env bash
# =============================================================================
# deploy.sh — ยก stack เดิม + launch deepseek-harness ชี้มา (รันบน host/Mac)
# -----------------------------------------------------------------------------
# เป้าหมาย: ลอง deepseek-harness "ขนาน" กับ HarnessRouter เดิม (คนละพอร์ต: 3080 vs 3000)
# stack ส่วนใหญ่ (LiteLLM/HexStrike/REA/llama) ใช้ร่วมกัน — ไฟล์นี้แค่ต่อ harness ใหม่เข้าไป
#
# ⚠️ deepseek-harness = developer preview → อาจต้องปรับ config ตอนรันจริง (ดู README)
#
# ‼️ LEGACY (รันบน host) — แนะนำให้ใช้ "วิธี container" แทน:
#       docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build
#    (หรือดับเบิลคลิก pipeline/mac/start.command) → service deepseek-harness เปิด :3080
#    วิธี container = bash ของ Tiel อยู่ใน container (isolation) + ไม่ต้องลง node/pnpm บน host
#    ไฟล์นี้เก็บไว้สำหรับ "ลองเล่นเร็ว ๆ บน host" เท่านั้น (ดู README หัวข้อ legacy)
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

# ── 3) วาง config ของ deepseek-harness (NON-CLOBBER = "จำ" config เดิม) ──────
#   ครั้งแรก: วางให้  |  ครั้งต่อไป: เก็บของเดิมไว้ (ไม่ทับ) → ที่แก้ผ่าน UI/มือไม่หาย
#   อยากเอา config ล่าสุดจากรีโปมา "ทับ" (เช่นหลัง pull ที่แก้ config): DSH_APPLY_CONFIG=1 bash deploy.sh
mkdir -p "$DSH_HOME/profiles/web"
TARGET="$DSH_HOME/profiles/web/cordis.patch.yml"
if [ ! -f "$TARGET" ] || [ "${DSH_APPLY_CONFIG:-0}" = "1" ]; then
  # config ในรีโปใช้ "ชื่อ service" (สำหรับรันใน container) — บน host ต้องแปลงเป็น localhost
  sed -e 's#http://litellm:4000#http://localhost:4000#' \
      -e 's#http://hexstrike-mcp:8001#http://localhost:8001#' \
      -e 's#http://rea-mcp:8007#http://localhost:8007#' \
      "$HERE/cordis.patch.yml" > "$TARGET"
  echo "✓ วาง cordis.patch.yml (แปลง service→localhost สำหรับ host) → $TARGET"
  echo "  ⚠️ host path: ต้องติดตั้ง MCP plugin เองก่อน (เวอร์ชันต้องตรง runtime):"
  echo "     npx @deepseek-ai/dsh plugin --profile web add @deepseek-ai/dsh-mcp-client@0.2.1-rc.2"
else
  echo "• เก็บ config เดิมไว้ ($TARGET) — เอาของรีโปมาทับ: DSH_APPLY_CONFIG=1 bash deploy.sh"
fi

# system prompt: วางครั้งแรกให้ (ไม่ทับของเดิมเช่นกัน)
PROMPT="$DSH_HOME/cyber-operator.system.md"
if [ ! -f "$PROMPT" ] || [ "${DSH_APPLY_CONFIG:-0}" = "1" ]; then
  cp "$PIPE/cyber-operator.system.md" "$PROMPT"
  echo "✓ วาง cyber-operator.system.md → $DSH_HOME/ (wire เป็น system prompt ใน DSH เอง — ดู README)"
fi

# ── 4) launch harness (web UI :3080 — ไม่ชนกับ HarnessRouter :3000) ──────────
#   2 โหมด:
#     npx (ดีฟอลต์)  = ดึง package @deepseek-ai/dsh จาก npm มารัน → "ไม่ต้อง clone repo"
#     source         = clone + pnpm build เอง (ได้ bleeding-edge ของ dev-preview / แก้โค้ดได้)
#   เลือกด้วย env:  DSH_MODE=source bash deploy.sh
MODE="${DSH_MODE:-npx}"
if [ "$MODE" = "source" ]; then
  SRC="${DSH_SRC:-$HOME/deepseek-harness}"
  if [ ! -d "$SRC/.git" ]; then
    echo "→ clone deepseek-harness → $SRC"
    git clone https://github.com/deepseek-ai/deepseek-harness.git "$SRC"
  else
    echo "→ อัปเดต deepseek-harness ($SRC)"; ( cd "$SRC" && git pull --ff-only || true )
  fi
  echo "→ pnpm install && build (ครั้งแรกนาน) ..."
  ( cd "$SRC" && pnpm install && pnpm run build )
  echo "→ launching from source (web UI → http://127.0.0.1:3080) ..."
  exec sh -c "cd '$SRC' && pnpm dsh web"
else
  echo "→ launching via npx (ดึง @deepseek-ai/dsh จาก npm — ไม่ต้อง clone) → http://127.0.0.1:3080 ..."
  echo "   (ครั้งแรก npx จะดาวน์โหลด package; ถ้าช้า/พัง ดู README)"
  exec npx @deepseek-ai/dsh web
fi
