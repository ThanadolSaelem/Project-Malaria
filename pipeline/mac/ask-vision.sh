#!/usr/bin/env bash
# =============================================================================
# "ให้โมเดลอ่านภาพ" — ส่งรูป + คำถาม เข้า vision model (Qwen2.5-VL) แล้วได้คำตอบ
# -----------------------------------------------------------------------------
#   ./ask-vision.sh รูป.png ["คำถาม — ดีฟอลต์: อ่าน/สรุปสิ่งที่เห็นเป็นภาษาไทย"]
#   ./ask-vision.sh scan.pdf "ในเอกสารนี้เขียนว่าอะไร"      ← PDF แปลงเป็นรูปให้อัตโนมัติ
#   ./ask-vision.sh a.png b.png c.png "เปรียบเทียบ 3 ภาพนี้"  ← หลายรูปได้
#
#   --scan          รีดรูปถ่ายเอกสารให้แบน+ลบเงา+คม (vFlat) ก่อนอ่าน → OCR แม่นขึ้น
#                   (ใช้กับ "รูปถ่าย" เอกสารที่เบี้ยว/แสงไม่ดี)
#   --scan-enhance  แค่ลบเงา/ทำพื้นขาว/คม ไม่ดัดรูปทรง (ใช้กับภาพที่แบนอยู่แล้วแต่หม่น
#                   เช่น scan เก่าๆ — ไม่เหมาะกับ screenshot ที่คมอยู่แล้ว)
#   ถ้า vFlat ดัดไม่สำเร็จ (ไม่เจอขอบเอกสาร) จะถอยไปใช้รูปเดิมให้เอง ไม่ล้ม
#
# ใช้ได้ทั้งบน Mac host และจาก harness sandbox (probe หา gateway ที่ต่อติดเอง)
# ต้องสตาร์ท vision llama-server :8093 ด้วย --mmproj ก่อน (ดู llama.env)
# --scan ต้องมี service vflat-scan รันอยู่ (docker compose — ภายใน :8000 / host :8006)
#
# env (override ได้): LITELLM_BASE, VISION_MODEL (default vision),
#                     LITELLM_API_KEY (default sk-local), VFLAT_BASE (บังคับ vflat เอง),
#                     VISION_PDF_MAXPAGES (default 5)
# =============================================================================
set -uo pipefail

MODEL="${VISION_MODEL:-vision}"
KEY="${LITELLM_API_KEY:-sk-local}"
PDF_MAXPAGES="${VISION_PDF_MAXPAGES:-5}"
SCAN_MODE=""   # "", "full" (--scan), "enhance" (--scan-enhance)

# แยก argv: flag / ไฟล์ที่มีอยู่จริง = รูป / ที่เหลือ = คำถาม
IMAGES=()
QUESTION=""
for arg in "$@"; do
  case "$arg" in
    --scan)         SCAN_MODE="full";    continue ;;
    --scan-enhance) SCAN_MODE="enhance"; continue ;;
  esac
  if [ -f "$arg" ]; then IMAGES+=("$arg"); else QUESTION="$arg"; fi
done

if [ "${#IMAGES[@]}" -eq 0 ]; then
  echo "usage: $0 [--scan|--scan-enhance] <รูป.png|scan.pdf> [\"คำถาม\"]" >&2
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

# ส่ง argv ให้ python: model, key, question, override gateway, scan_mode, vflat_base, แล้วรูปทั้งหมด
python3 - "$MODEL" "$KEY" "$QUESTION" "${LITELLM_BASE:-}" "$SCAN_MODE" "${VFLAT_BASE:-}" "${EXPANDED[@]}" <<'PY'
import sys, json, base64, mimetypes, urllib.request, urllib.error
model, key, question, override, scan_mode, vflat_override = sys.argv[1:7]
image_paths = sys.argv[7:]

def reachable(b, path="/models"):
    try:
        urllib.request.urlopen(b + path, timeout=3); return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

# ── (ออปชัน) preprocess ผ่าน vFlat: รีดเอกสารให้แบน/ลบเงา ก่อนอ่าน ──
def vflat_base():
    bases = []
    if vflat_override.strip():
        bases.append(vflat_override.strip().rstrip("/"))
    bases += [
        "http://vflat-scan:8000",            # ภายใน compose (Tiel's sandbox)
        "http://host.docker.internal:8006",  # จาก container ผ่าน host
        "http://localhost:8006",             # Mac host
    ]
    return next((b for b in bases if reachable(b, "/healthz")), None)

def vflat_scan(raw, base, mode):
    # mode "full" = dewarp+sharpen+enhance ; "enhance" = ไม่ดัดทรง (dewarp=false)
    q = "?dewarp=true" if mode == "full" else "?dewarp=false"
    # multipart ง่ายๆ ด้วยมือ (field name ต้องเป็น "file")
    boundary = "----vflatboundary7f3a"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"in.jpg\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
            + raw + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(base.rstrip("/") + "/scan" + q, data=body,
          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

vbase = vflat_base() if scan_mode else None
if scan_mode and not vbase:
    print("  [vflat] ⚠️  ไม่พบ service vflat-scan (:8000/:8006) — ข้ามการสแกน ใช้รูปเดิม", file=sys.stderr)

def load_image_bytes(path):
    with open(path, "rb") as f:
        raw = f.read()
    if scan_mode and vbase:
        try:
            cleaned = vflat_scan(raw, vbase, scan_mode)
            print(f"  [vflat] ✓ สแกน {path} ({scan_mode}) แล้ว", file=sys.stderr)
            return cleaned, "image/jpeg"
        except urllib.error.HTTPError as e:
            print(f"  [vflat] ⚠️  สแกน {path} ไม่สำเร็จ (HTTP {e.code} — อาจไม่เจอขอบเอกสาร) ใช้รูปเดิม", file=sys.stderr)
        except Exception as e:
            print(f"  [vflat] ⚠️  สแกน {path} ไม่สำเร็จ ({e}) ใช้รูปเดิม", file=sys.stderr)
    return raw, (mimetypes.guess_type(path)[0] or "image/png")

# ── vision gateway (เหมือน ask-specialist.sh) ──
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
base = next((b for b in bases if reachable(b)), None)
if not base:
    print("error: ไม่พบ vision gateway ที่ต่อติด ลองมาแล้ว:\n  " + "\n  ".join(bases) +
          "\nเช็กว่า litellm (:4000) หรือ vision llama (:8093) รันอยู่ "
          "(vision ต้องสตาร์ทด้วย --mmproj ไม่งั้นอ่านภาพไม่ได้)", file=sys.stderr)
    sys.exit(2)

def data_url(raw, mime):
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

content = []
for p in image_paths:
    raw, mime = load_image_bytes(p)
    content.append({"type": "image_url", "image_url": {"url": data_url(raw, mime)}})
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
