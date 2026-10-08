#!/usr/bin/env bash
# =============================================================================
# "ให้โมเดลอ่านภาพ" — ส่งรูป + คำถาม เข้า vision model (Qwen2.5-VL) แล้วได้คำตอบ
# -----------------------------------------------------------------------------
#   ./ask-vision.sh รูป.png ["คำถาม — ดีฟอลต์: อ่าน/สรุปสิ่งที่เห็นเป็นภาษาไทย"]
#   ./ask-vision.sh scan.pdf "ในเอกสารนี้เขียนว่าอะไร"      ← PDF แปลงเป็นรูปให้อัตโนมัติ
#   ./ask-vision.sh a.png b.png c.png "เปรียบเทียบ 3 ภาพนี้"  ← หลายรูปได้ (รูปทั้งหมดก่อน ตามด้วยคำถาม)
#
# ใช้ได้ทั้งบน Mac host และจาก harness sandbox (probe หา gateway ที่ต่อติดเอง เหมือน
# ask-specialist.sh). ต้องสตาร์ท vision llama-server :8093 ด้วย --mmproj ก่อน (ดู llama.env)
#
# env (override ได้): LITELLM_BASE (บังคับ gateway เอง), VISION_MODEL (default vision),
#                     LITELLM_API_KEY (default sk-local)
#
# PDF: แปลงหน้าเป็น PNG ด้วย pdftoppm (poppler) ถ้าไม่มีลองใช้ sips (มากับ macOS)
#      ดีฟอลต์แปลงสูงสุด 5 หน้าแรก — ตั้ง VISION_PDF_MAXPAGES เปลี่ยนได้
# =============================================================================
set -uo pipefail

MODEL="${VISION_MODEL:-vision}"
KEY="${LITELLM_API_KEY:-sk-local}"
PDF_MAXPAGES="${VISION_PDF_MAXPAGES:-5}"

# แยก argv: ทุกตัวที่เป็น "ไฟล์ที่มีอยู่จริง" = รูป, ตัวสุดท้ายที่ไม่ใช่ไฟล์ = คำถาม
IMAGES=()
QUESTION=""
for arg in "$@"; do
  if [ -f "$arg" ]; then
    IMAGES+=("$arg")
  else
    QUESTION="$arg"
  fi
done

if [ "${#IMAGES[@]}" -eq 0 ]; then
  echo "usage: $0 <รูป.png|scan.pdf> [\"คำถาม\"]" >&2
  echo "  (ต้องชี้ไปที่ไฟล์ภาพที่มีอยู่จริง — ตรวจ path อีกที)" >&2
  exit 1
fi
[ -z "$QUESTION" ] && QUESTION="อ่านทุกข้อความที่เห็นในภาพให้ครบ แล้วสรุปสาระสำคัญเป็นภาษาไทย"

# ── แปลง PDF → PNG (ถ้ามี) ก่อนส่ง ─────────────────────────────────────────────
TMPDIR_CONV="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_CONV"' EXIT
EXPANDED=()
for f in "${IMAGES[@]}"; do
  case "$(printf '%s' "$f" | tr '[:upper:]' '[:lower:]')" in
    *.pdf)
      if command -v pdftoppm >/dev/null 2>&1; then
        pdftoppm -png -r 150 -l "$PDF_MAXPAGES" "$f" "$TMPDIR_CONV/page" >/dev/null 2>&1
        for p in "$TMPDIR_CONV"/page*.png; do [ -f "$p" ] && EXPANDED+=("$p"); done
        echo "  [pdf] แปลง $(basename "$f") → $(ls "$TMPDIR_CONV"/page*.png 2>/dev/null | wc -l | tr -d ' ') หน้า (สูงสุด $PDF_MAXPAGES)" >&2
      elif command -v sips >/dev/null 2>&1; then
        sips -s format png "$f" --out "$TMPDIR_CONV/page.png" >/dev/null 2>&1 \
          && EXPANDED+=("$TMPDIR_CONV/page.png") \
          && echo "  [pdf] แปลงด้วย sips (หน้าแรกเท่านั้น) — ลง poppler เพื่อแปลงหลายหน้า: brew install poppler" >&2
      else
        echo "error: ไฟล์ PDF แต่ไม่มีตัวแปลง (pdftoppm/sips). ลง: brew install poppler" >&2
        exit 2
      fi
      ;;
    *) EXPANDED+=("$f") ;;
  esac
done
[ "${#EXPANDED[@]}" -eq 0 ] && { echo "error: ไม่มีรูปให้ส่งหลังแปลง" >&2; exit 2; }

# ส่ง argv ให้ python: model, key, question, จำนวนรูป, แล้วรูปทั้งหมด, แล้ว override gateway
python3 - "$MODEL" "$KEY" "$QUESTION" "${LITELLM_BASE:-}" "${EXPANDED[@]}" <<'PY'
import sys, json, base64, mimetypes, urllib.request, urllib.error
model, key, question, override = sys.argv[1:5]
image_paths = sys.argv[5:]

# gateway เดียวกับ ask-specialist.sh: override → litellm ใน compose → ผ่าน host →
# localhost → vision llama ตรงๆ (:8093). ตัวแรกที่ต่อติดชนะ
bases = []
if override.strip():
    bases.append(override.strip().rstrip("/"))
bases += [
    "http://litellm:4000/v1",
    "http://host.docker.internal:4000/v1",
    "http://localhost:4000/v1",
    "http://host.docker.internal:8093/v1",
    "http://localhost:8093/v1",
]

def reachable(b):
    try:
        urllib.request.urlopen(b + "/models", timeout=3); return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

base = next((b for b in bases if reachable(b)), None)
if not base:
    print("error: ไม่พบ vision gateway ที่ต่อติด ลองมาแล้ว:\n  " + "\n  ".join(bases) +
          "\nเช็กว่า litellm (:4000) หรือ vision llama (:8093) รันอยู่ "
          "(vision ต้องสตาร์ทด้วย --mmproj ไม่งั้นอ่านภาพไม่ได้)", file=sys.stderr)
    sys.exit(2)

def data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"

# content = รูปทั้งหมดก่อน แล้วตามด้วยคำถาม (รูปแบบ OpenAI vision messages)
content = [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in image_paths]
content.append({"type": "text", "text": question})

system = ("You read and understand images for an authorized security investigation. "
          "Read ALL visible text verbatim (including Thai), describe layout/UI/evidence "
          "faithfully, and do not invent anything not present in the image. "
          "Answer in the language the user asked in.")
body = json.dumps({
    "model": model,
    "messages": [{"role": "system", "content": system},
                 {"role": "user", "content": content}],
    "temperature": 0.1,
    "max_tokens": 2048,
}).encode()
req = urllib.request.Request(
    base.rstrip("/") + "/chat/completions", data=body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    print(d["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")[:500]
    print(f"error calling vision via {base}: HTTP {e.code} {detail}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"error calling vision via {base}: {e}", file=sys.stderr)
    sys.exit(1)
PY
