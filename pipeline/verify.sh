#!/usr/bin/env bash
# =============================================================================
# verify.sh — เช็คว่าไปป์ไลน์ทั้งสามชั้นพร้อมก่อนไปเปิด HarnessRouter Console
#   1) LiteLLM ตอบและ "big-brain" ทะลุถึง provider จริง
#   2) HexStrike server (:8888) มีชีวิต
#   3) HexStrike MCP (:8001) endpoint ตอบ
# ใช้: bash pipeline/verify.sh
# อ่านค่าจาก pipeline/.env ถ้ามี
# =============================================================================
set -u
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

LITELLM_URL="${LITELLM_URL:-http://localhost:4000}"
MCP_URL="${MCP_URL:-http://localhost:8001/mcp}"
# แปลง HEXSTRIKE_SERVER (มุมมองจาก container) ให้เป็น URL เช็คจาก host
HX_HEALTH="${HX_HEALTH:-http://localhost:8888/health}"

pass=0; fail=0
ok(){ echo "  ✅ $1"; pass=$((pass+1)); }
no(){ echo "  ❌ $1"; fail=$((fail+1)); }

echo "── 1. LiteLLM (provider switch) ─────────────────────────"
if curl -fsS --max-time 5 "$LITELLM_URL/health/liveliness" >/dev/null 2>&1 \
   || curl -fsS --max-time 5 "$LITELLM_URL/v1/models" >/dev/null 2>&1; then
  ok "LiteLLM ตอบที่ $LITELLM_URL"
  echo "  → ยิง big-brain ผ่าน provider จริง (ใช้ key ใน .env)…"
  # max_tokens สูงหน่อย: deepseek-v4-flash เป็น reasoning model ถ้าน้อยไปจะใช้ token
  # ไปกับการคิดจนหมดก่อนพ่น content -> content ว่างทั้งที่ provider ตอบสำเร็จ
  resp=$(curl -sS --max-time 90 "$LITELLM_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"big-brain","messages":[{"role":"user","content":"reply with the single word: ok"}],"max_tokens":256}')
  # ผ่านถ้าได้ completion object (มี "choices") — content จะว่างก็ได้ (reasoning model)
  if echo "$resp" | grep -qE '"choices"[[:space:]]*:'; then
    ok "big-brain ทะลุถึง provider (ได้ completion กลับมา)"
    echo "     $(echo "$resp" | tr -d '\n' | cut -c1-200)…"
  else
    no "big-brain ยังไม่ทะลุ — เช็คชื่อโมเดลใน litellm-config.yaml / key"
    echo "     $(echo "$resp" | tr -d '\n' | cut -c1-200)"
  fi
else
  no "LiteLLM ไม่ตอบที่ $LITELLM_URL (ยังไม่ได้ up? port ผิด?)"
fi

echo "── 2. HexStrike server (tools) ──────────────────────────"
h=$(curl -sS --max-time 8 "$HX_HEALTH" 2>/dev/null)
if echo "$h" | grep -qiE '"status"|healthy|version'; then
  ok "server :8888 มีชีวิต"
  miss=$(echo "$h" | grep -o '"all_essential_tools_available"[^,]*')
  [ -n "$miss" ] && echo "     $miss"
else
  no "server ไม่ตอบที่ $HX_HEALTH (โหมด A: รันบน Kali หรือยัง? โหมด B: ใช้ --profile full หรือยัง?)"
fi

echo "── 3. HexStrike MCP endpoint ────────────────────────────"
# MCP streamable-http ต้องมี Accept ทั้ง json และ event-stream; แค่เช็คว่า port ตอบ
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' "$MCP_URL" 2>/dev/null)
if [ "$code" != "000" ] && [ -n "$code" ]; then
  ok "MCP endpoint ตอบ (HTTP $code) ที่ $MCP_URL"
else
  no "MCP endpoint ไม่ตอบที่ $MCP_URL (hexstrike-mcp container ขึ้นหรือยัง?)"
fi

echo "─────────────────────────────────────────────────────────"
echo "ผ่าน $pass / ล้มเหลว $fail"
[ "$fail" -eq 0 ] && echo "พร้อมไปเปิด Console: http://localhost:3000" || echo "แก้ที่ ❌ ก่อน แล้วรันซ้ำ"
exit "$fail"
