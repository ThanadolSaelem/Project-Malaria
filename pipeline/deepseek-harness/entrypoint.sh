#!/bin/sh
# =============================================================================
# entrypoint — รัน deepseek-harness web UI ใน container
# -----------------------------------------------------------------------------
# dsh web --host รับ "IP ของ interface จริง" เท่านั้น — wildcard (0.0.0.0/::) ถูก reject
# ใน container จึงต้อง bind IP ของ container เอง (eth0) แล้ว Docker map :3080 ออก host
# (ดึง IP ด้วย node เพราะ image ไม่มี hostname/ip command แน่นอน)
# =============================================================================
set -eu

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
