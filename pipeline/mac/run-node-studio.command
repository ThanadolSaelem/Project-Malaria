#!/usr/bin/env bash
# =============================================================================
# สคริปต์เปิด Qwen Code Studio
#   1) ซิงค์ไฟล์ตั้งค่า (node-config.json -> litellm-config.yaml + qwen settings.json)
#   2) รีสตาร์ท litellm (:4000), specialist-mcp (:8003), qwen-code (:3080)
#   3) เปิดหน้าแชท Qwen Code Studio (:3080 พร้อม token)
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PIPELINE="$(cd "$HERE/.." && pwd)"

mkdir -p "$HERE/logs"

python3 -c "import sys; sys.path.insert(0, '$PIPELINE'); import control_plane; control_plane.sync_all_configs(control_plane.load_node_config())" 2>/dev/null || true

export HOST_LAN_IP="$("$HERE/mobile-link.sh" --ip-only 2>/dev/null || true)"
"$HERE/mobile-link.sh" --start-watcher 2>/dev/null || true

cd "$PIPELINE"
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d litellm specialist-mcp qwen-code 2>/dev/null || \
  docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d litellm specialist-mcp 2>/dev/null || true

docker compose -f docker-compose.yml -f docker-compose.mac.yml restart litellm specialist-mcp 2>/dev/null || true
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --force-recreate qwen-code 2>/dev/null || true

echo "กำลังเปิด Qwen Code Studio (:3080)..."
QWEN_URL="http://localhost:3080/?token=malaria-qwen-token"
echo "[OK] Qwen Code Studio -> $QWEN_URL"
if [ -n "${HOST_LAN_IP:-}" ]; then
  echo "[OK] เข้าจากมือถือใน Wi-Fi เดียวกัน -> http://${HOST_LAN_IP}:3080/?token=malaria-qwen-token"
fi
open "$QWEN_URL" 2>/dev/null || true
