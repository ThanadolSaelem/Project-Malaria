#!/usr/bin/env bash
# =============================================================================
# รัน HexStrike server แบบ native บน Mac (Apple Silicon / arm64)
# ครั้งแรกจะสร้าง venv + ลง python deps ให้อัตโนมัติ ครั้งถัดไปรันเลย
# ใช้: bash pipeline/mac/2-run-hexstrike.sh
#
# ทำไม native ไม่ใช้ docker: Kali image เป็น amd64 บน arm64 รันผ่าน emulation
# ช้าเกินไปสำหรับ tool สแกน — รัน native เร็วกว่ามาก
# hexstrike-mcp (docker) จะต่อมาที่ server นี้ผ่าน host.docker.internal:8888
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/../../hexstrike-ai-main" && pwd)"
VENV="$HERE/hexstrike-env"

if [ ! -d "$VENV" ]; then
  echo "[setup] สร้าง venv + ลง python deps (ครั้งเดียว)…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  # ตัด angr/pwntools: เช็คซอร์สแล้วอยู่ใน f-string (server เขียนเป็นไฟล์ให้ผู้ใช้)
  # ไม่ใช่ import จริงตอนรัน — หนัก/เปราะบน arm64 ตัดได้ไม่กระทบ endpoint
  grep -viE '^(angr|pwntools)([><=~ ]|$)' "$SRC/requirements.txt" > "$HERE/.reqs.txt"
  echo "[setup] pip install (อาจใช้เวลาสักครู่)…"
  "$VENV/bin/pip" install -r "$HERE/.reqs.txt"
fi

echo "[run] เริ่ม hexstrike server บน :8888 (native arm64) — Ctrl+C เพื่อหยุด"
exec "$VENV/bin/python" "$SRC/hexstrike_server.py" --port 8888
