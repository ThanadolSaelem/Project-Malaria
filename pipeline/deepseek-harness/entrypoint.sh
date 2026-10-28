#!/bin/sh
# =============================================================================
# entrypoint — รัน deepseek-harness web UI ใน container
# =============================================================================
set -eu

# ── config (patch): copy จาก /config (:ro mount จาก repo) → profile (เขียนได้) ──
#   ทำไมต้อง copy ไม่ mount ตรง: UI persist settings (เช่น ack ของ Preview Notice,
#   ui-settings-general) โดย "เขียนทับ" cordis.patch.yml. ถ้า mount ไฟล์เดี่ยวแบบ :ro
#   จะเขียนไม่ได้ → EBUSY (rename ทับ bind-mount ของไฟล์ไม่ได้). copy เป็นไฟล์ปกติใน
#   /dsh (RW layer) แทน → UI เซฟได้ และ config ยังมาจาก repo (reproducible)
if [ -f /config/cordis.patch.yml ]; then
  mkdir -p /dsh/profiles/web
  cp /config/cordis.patch.yml /dsh/profiles/web/cordis.patch.yml
  echo "entrypoint: วาง cordis.patch.yml จาก repo → /dsh/profiles/web (เขียนได้)"
else
  echo "entrypoint: ⚠️ ไม่พบ /config/cordis.patch.yml (ไม่ได้ mount?) — ใช้ของเดิมใน image ถ้ามี"
fi

# ── bind IP ของ container (dsh --host ไม่รับ wildcard 0.0.0.0) ──
IP="$(node -e "const n=require('os').networkInterfaces();for(const k in n)for(const a of n[k])if(a.family==='IPv4'&&!a.internal){console.log(a.address);process.exit(0)}")"
if [ -z "$IP" ]; then
  echo "entrypoint: หา IPv4 ของ container ไม่เจอ — ยกเลิก" >&2
  exit 1
fi

echo "deepseek-harness: bind ${IP}:3080  →  เปิดจาก host ที่ http://localhost:3080"
echo "deepseek-harness: token อยู่ใน log บรรทัดด้านล่าง (docker compose logs deepseek-harness)"

exec dsh web --no-open \
  --host "$IP" --port 3080 \
  --public-url "${DSH_PUBLIC_URL:-http://localhost:3080/}" \
  --trusted-host localhost:3080 \
  --trusted-host 127.0.0.1:3080
