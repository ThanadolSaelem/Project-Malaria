#!/usr/bin/env bash
# =============================================================================
# mobile-link.sh — ดึง IP เครื่อง Mac ในวง Wi-Fi อัตโนมัติและสร้างลิงก์สำหรับมือถือ
# =============================================================================
set -uo pipefail

TOKEN="${QWEN_SERVER_TOKEN:-malaria-qwen-token}"
PORT="${QWEN_PORT:-3080}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PIPELINE="$(cd "$HERE/.." && pwd)"
IP_DIR="$PIPELINE/qwen-code/runtime"
IP_FILE="$IP_DIR/host-lan-ip.txt"
WATCH_PID_FILE="$HERE/logs/lan-ip-watch.pid"

sync_host_ip_file() {
  local ip="$1"
  [ -f /.dockerenv ] && return 0
  [ -n "$ip" ] || return 0
  mkdir -p "$IP_DIR"
  local cur=""
  [ -f "$IP_FILE" ] && cur="$(cat "$IP_FILE" 2>/dev/null || true)"
  if [ "$cur" != "$ip" ]; then
    printf '%s\n' "$ip" > "$IP_FILE"
  fi
}

# เช็ค IP ของเครื่อง Mac แบบ dynamic (ไม่ดึง IP ภายใน Docker 172.x.x.x หรือ VPN tunnel)
detect_lan_ip() {
  if [ -f /.dockerenv ]; then
    if [ -n "${HOST_LAN_IP:-}" ]; then
      echo "$HOST_LAN_IP"
      return 0
    fi
    return 1
  fi

  local iface ip
  if command -v route >/dev/null 2>&1; then
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
    if [ -n "$iface" ] && [[ "$iface" =~ ^en[0-9]+$ ]]; then
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      if [ -n "$ip" ]; then
        echo "$ip"
        return 0
      fi
    fi
  fi

  if command -v scutil >/dev/null 2>&1; then
    ip="$(scutil --nwi 2>/dev/null | awk '
      /IPv4 network interface information/,/IPv6 network interface information/{
        if ($1 ~ /^en[0-9]+$/ && $2 == ":") { cur=$1 }
        if ($1 == "address" && cur != "") { print $3; exit }
        if ($1 == "REACH") { cur="" }
      }')"
    if [ -n "$ip" ]; then
      echo "$ip"
      return 0
    fi
  fi

  for iface in en0 en1 en2 en3 en4 en5 en6 en7 en8; do
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    if [ -n "$ip" ]; then
      echo "$ip"
      return 0
    fi
  done

  ifconfig 2>/dev/null | awk '
    /^[a-zA-Z0-9]+:/ {
      sub(/:.*/, "", $1)
      skip = ($1 ~ /^(lo|gif|stf|utun|awdl|llw|ap|anpi|bridge|docker|veth|br-|tun|tap)/)
    }
    !skip && $1 == "inet" && $2 != "127.0.0.1" { print $2; exit }'
}

case "${1:-}" in
  --watch)
    [ -f /.dockerenv ] && exit 1
    mkdir -p "$HERE/logs"
    echo $$ > "$WATCH_PID_FILE"
    trap 'rm -f "$WATCH_PID_FILE"' EXIT INT TERM
    while true; do
      sync_host_ip_file "$(detect_lan_ip || true)"
      sleep "${LAN_IP_WATCH_INTERVAL:-10}"
    done
    ;;
  --start-watcher)
    [ -f /.dockerenv ] && exit 0
    mkdir -p "$HERE/logs"
    sync_host_ip_file "$(detect_lan_ip || true)"
    if [ -f "$WATCH_PID_FILE" ]; then
      old_pid="$(cat "$WATCH_PID_FILE" 2>/dev/null || true)"
      if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null && ps -p "$old_pid" -o command= 2>/dev/null | grep -q "mobile-link.sh"; then
        exit 0
      fi
    fi
    nohup "$HERE/mobile-link.sh" --watch </dev/null >/dev/null 2>&1 &
    echo $! > "$WATCH_PID_FILE"
    exit 0
    ;;
esac

LAN_IP="$(detect_lan_ip || true)"
sync_host_ip_file "$LAN_IP"

if [ "${1:-}" = "--ip-only" ]; then
  [ -n "$LAN_IP" ] || exit 1
  echo "$LAN_IP"
  exit 0
fi

if [ -z "$LAN_IP" ]; then
  if [ -f /.dockerenv ]; then
    echo "[WARN] สคริปต์นี้รันอยู่ภายใน Docker container จึงเห็นแต่ IP ภายใน (172.x.x.x)"
    echo "       กรุณารันใน Terminal ของ macOS โดยตรง หรือเช็คตัวแปร HOST_LAN_IP"
  else
    echo "[WARN] ไม่พบ IP ของเครื่อง Mac ในวง LAN/Wi-Fi — กรุณาตรวจสอบการเชื่อมต่อเครือข่าย"
  fi
  exit 1
fi

MOBILE_URL="http://${LAN_IP}:${PORT}/?token=${TOKEN}"

echo "=============================================================="
echo "  Qwen Code Studio - Mobile Connection Link"
echo "=============================================================="
echo "IP เครื่อง Mac ในวง Wi-Fi ปัจจุบัน: $LAN_IP"
echo ""
echo "ลิงก์เข้าใช้งานจากโทรศัพท์มือถือ (และใช้เปิดบน Mac เพื่อให้ QR/Pairing ไม่ติด 172.x.x.x):"
echo "  $MOBILE_URL"
echo "=============================================================="

# คัดลอกลิงก์เข้า Clipboard ของ macOS ทันที
if command -v pbcopy >/dev/null 2>&1; then
  echo -n "$MOBILE_URL" | pbcopy
  echo "คัดลอกลิงก์เข้า Clipboard ให้แล้ว (กด Cmd+V เพื่อวางได้ทันที)"
fi
