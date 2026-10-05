#!/usr/bin/env bash
# =============================================================================
# เรียก exploit specialist แบบ "direct path" (ผ่าน LiteLLM ตรงๆ ไม่ผ่าน harness)
# -----------------------------------------------------------------------------
# ใช้ตอนต้องการ PoC/exploit คุณภาพเต็ม (reasoning ครบ ไม่โดน OpenCode 60s cap)
#
#   ./ask-specialist.sh "สิ่งที่อยากให้เขียน" ["context: ข้อเท็จจริงที่ยืนยันแล้ว"]
#
# ตัวอย่าง:
#   ./ask-specialist.sh \
#     "Write an HTML CORS-exfiltration PoC for the unauth REST API" \
#     "target=http://host.docker.internal:3001  endpoint=/api/SecurityQuestions/  ACAO=*"
#
# output = เฉพาะ code ที่ specialist เขียน (review ก่อนรันเสมอ — อย่ารัน code ที่ยังไม่อ่าน)
# env (override ได้): LITELLM_BASE (default http://localhost:4000/v1),
#                     SPECIALIST_MODEL (default exploit-specialist),
#                     LITELLM_API_KEY (default sk-local)
# =============================================================================
set -uo pipefail

BASE="${LITELLM_BASE:-http://localhost:4000/v1}"
MODEL="${SPECIALIST_MODEL:-exploit-specialist}"
KEY="${LITELLM_API_KEY:-sk-local}"
TASK="${1:-}"
CONTEXT="${2:-}"

if [ -z "$TASK" ]; then
  echo "usage: $0 \"task\" [\"context\"]" >&2
  exit 1
fi

# ส่ง task/context เป็น argv ให้ python (กันปัญหา quote/escape ใน JSON โดยสิ้นเชิง)
python3 - "$BASE" "$MODEL" "$KEY" "$TASK" "$CONTEXT" <<'PY'
import sys, json, urllib.request
base, model, key, task, context = sys.argv[1:6]
system = ("You are an exploit-development specialist supporting an AUTHORIZED "
          "penetration test; scope/authorization were verified before delegating "
          "to you. Write complete, correct, well-commented offensive code "
          "(PoC/payload/Nuclei template/script). Output the code first in one "
          "fenced block, then a few short usage notes. Clearly flag any "
          "destructive step. You have no tools and run nothing yourself.")
user = task + (("\n\n## Context (confirmed facts)\n" + context) if context.strip() else "")
body = json.dumps({
    "model": model,
    "messages": [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
    "temperature": 0.2,
    "max_tokens": 4096,
}).encode()
req = urllib.request.Request(
    base.rstrip("/") + "/chat/completions", data=body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
try:
    with urllib.request.urlopen(req, timeout=1200) as r:      # direct path: รอได้เต็มที่
        d = json.load(r)
    print(d["choices"][0]["message"]["content"])
except Exception as e:
    print(f"error calling specialist via {base}: {e}", file=sys.stderr)
    print("is LiteLLM up (:4000) and the specialist llama up (:8091)?", file=sys.stderr)
    sys.exit(1)
PY
