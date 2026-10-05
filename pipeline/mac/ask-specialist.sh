#!/usr/bin/env bash
# =============================================================================
# เรียก exploit specialist แบบ "direct" (ไม่ผ่าน MCP) — ใช้ได้ทั้ง:
#   • คุณรันเองบน Mac host                → เจอ gateway ที่ localhost
#   • Tiel รันผ่าน bash tool ใน harness   → เจอ gateway ที่ litellm / host.docker.internal
# สคริปต์ probe หา gateway ที่ "ต่อติด" เองอัตโนมัติ (ตัวแรกที่ตอบชนะ) จึงไม่ต้องตั้ง env
#
#   ./ask-specialist.sh "สิ่งที่อยากให้เขียน" ["context: ข้อเท็จจริงที่ยืนยันแล้ว"]
#
# ทำไมไม่ผ่าน MCP: tool call ของ OpenCode ถูก cap ~60s (-32001) + บางที MCP ไม่ connect
#   ส่วน bash มี timeout ยาวกว่ามาก → งาน PoC ที่ specialist คิดนานจึงเสร็จได้
# output = เฉพาะ code ที่ specialist เขียน (review ก่อนรันเสมอ — อย่ารัน code ที่ยังไม่อ่าน)
#
# env (override ได้): LITELLM_BASE (บังคับ gateway เอง, ข้าม auto-detect),
#                     SPECIALIST_MODEL (default exploit-specialist),
#                     LITELLM_API_KEY (default sk-local)
# =============================================================================
set -uo pipefail

MODEL="${SPECIALIST_MODEL:-exploit-specialist}"
KEY="${LITELLM_API_KEY:-sk-local}"
TASK="${1:-}"
CONTEXT="${2:-}"

if [ -z "$TASK" ]; then
  echo "usage: $0 \"task\" [\"context\"]" >&2
  exit 1
fi

# ส่ง task/context เป็น argv ให้ python (กันปัญหา quote/escape ใน JSON โดยสิ้นเชิง)
python3 - "$MODEL" "$KEY" "$TASK" "$CONTEXT" "${LITELLM_BASE:-}" <<'PY'
import sys, json, urllib.request, urllib.error
model, key, task, context, override = sys.argv[1:6]

# รายชื่อ gateway ที่จะลอง (ตามลำดับ): override ก่อน แล้ว litellm ใน compose,
# litellm ผ่าน host, localhost, สุดท้าย llama specialist ตรงๆ (alias เดียวกันใช้ได้)
# → ตัวแรกที่ "ต่อติด" ชนะ ทำให้รันจาก host หรือจากใน sandbox ได้โดยไม่ต้องแก้อะไร
bases = []
if override.strip():
    bases.append(override.strip().rstrip("/"))
bases += [
    "http://litellm:4000/v1",              # จากใน compose network (Tiel's sandbox)
    "http://host.docker.internal:4000/v1", # litellm ผ่าน host จาก container
    "http://localhost:4000/v1",            # Mac host ตรงไป litellm
    "http://host.docker.internal:8091/v1", # llama specialist ตรงๆ (ข้าม litellm)
    "http://localhost:8091/v1",            # llama specialist บน host
]

def reachable(b):
    try:
        urllib.request.urlopen(b + "/models", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True          # server ตอบ (เช่น 401 ต้อง key) = มันอยู่ตรงนั้น
    except Exception:
        return False

base = next((b for b in bases if reachable(b)), None)
if not base:
    print("error: ไม่พบ specialist gateway ที่ต่อติดเลย ลองมาแล้ว:\n  " +
          "\n  ".join(bases) +
          "\nเช็กว่า litellm (:4000) หรือ specialist llama (:8091) รันอยู่", file=sys.stderr)
    sys.exit(2)

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
    with urllib.request.urlopen(req, timeout=1200) as r:      # direct: รอได้เต็มที่
        d = json.load(r)
    print(d["choices"][0]["message"]["content"])
except Exception as e:
    print(f"error calling specialist via {base}: {e}", file=sys.stderr)
    sys.exit(1)
PY
