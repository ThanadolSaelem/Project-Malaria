#!/usr/bin/env bash
# =============================================================================
# "สแกนเอกสาร" — รีดรูปถ่าย/PDF ให้แบน ลบเงา ทำพื้นขาว คมขึ้น (vFlat) แล้วเซฟไฟล์
# -----------------------------------------------------------------------------
#   ./scan-doc.sh in.jpg [out.jpg]        รูปถ่ายเอกสาร → ภาพสแกนสวย (dewarp เต็ม)
#   ./scan-doc.sh in.pdf [out.pdf]        PDF ทุกหน้า → PDF ที่สแกนแล้ว
#   ./scan-doc.sh --enhance in.jpg out.jpg   แค่ลบเงา/คม ไม่ดัดทรง (ภาพที่แบนอยู่แล้ว)
#
# ต่างจาก ask-vision.sh: ตัวนี้ "เซฟไฟล์" เฉยๆ ไม่ได้ถาม LLM — ใช้ทำความสะอาด
# รูปหลักฐานก่อนแปะใน report หรือก่อนเก็บเข้าแฟ้ม
#
# ต้องมี service vflat-scan รันอยู่ (docker compose) — ภายใน :8000 / จาก host :8006
# env: VFLAT_BASE (บังคับ endpoint เอง)
# =============================================================================
set -uo pipefail

MODE_Q="?dewarp=true"
if [ "${1:-}" = "--enhance" ]; then MODE_Q="?dewarp=false"; shift; fi

IN="${1:-}"
OUT="${2:-}"
if [ -z "$IN" ] || [ ! -f "$IN" ]; then
  echo "usage: $0 [--enhance] <in.jpg|in.pdf> [out]" >&2
  exit 1
fi

# เดา output: ถ้า PDF → .scanned.pdf, ไม่งั้น → .scanned.jpg
if [ -z "$OUT" ]; then
  case "$(printf '%s' "$IN" | tr '[:upper:]' '[:lower:]')" in
    *.pdf) OUT="${IN%.*}.scanned.pdf" ;;
    *)     OUT="${IN%.*}.scanned.jpg" ;;
  esac
fi

# หา endpoint vFlat ที่ต่อติด
pick_base() {
  for b in "${VFLAT_BASE:-}" "http://vflat-scan:8000" "http://host.docker.internal:8006" "http://localhost:8006"; do
    [ -z "$b" ] && continue
    if curl -s -o /dev/null -m 3 "${b%/}/healthz" 2>/dev/null; then echo "${b%/}"; return; fi
  done
}
BASE="$(pick_base)"
if [ -z "$BASE" ]; then
  echo "error: ไม่พบ service vflat-scan (:8000/:8006) — สตาร์ท stack ก่อน (start.command / docker compose up)" >&2
  exit 2
fi

echo "… สแกน $IN ผ่าน $BASE/scan$MODE_Q" >&2
HTTP=$(curl -s -w '%{http_code}' -o "$OUT" -m 300 \
        -F "file=@${IN}" "${BASE}/scan${MODE_Q}" 2>/dev/null)
if [ "$HTTP" = "200" ]; then
  echo "✓ เซฟ: $OUT  ($(du -h "$OUT" 2>/dev/null | awk '{print $1}'))"
else
  echo "✗ สแกนไม่สำเร็จ (HTTP $HTTP)" >&2
  echo "  (422 = vFlat ไม่เจอขอบเอกสารในรูป — ลอง --enhance แทน หรือรูปนี้ไม่ใช่รูปถ่ายเอกสาร)" >&2
  [ -f "$OUT" ] && head -c 300 "$OUT" >&2 && echo "" >&2
  rm -f "$OUT"
  exit 1
fi
