#!/usr/bin/env bash
# =============================================================================
# Project-Malaria — Cross-Platform Linux / WSL2 Startup Script
# =============================================================================
# For macOS Apple Silicon, use `pipeline/mac/start.command` (which adds
# `-f docker-compose.mac.yml` for native arm64 builds).
# For Linux / Ubuntu / Kali / Windows WSL2 (x86_64 or arm64), run:
#   ./pipeline/start-linux.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/mac/logs"
mkdir -p "$LOG_DIR"

echo "[1/2] Starting Control Plane & Model/Report/Sandbox Bridge on :8010..."
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -sTCP:LISTEN -ti :8010 || true)"
  [ -n "$PIDS" ] && kill $PIDS || true
elif command -v fuser >/dev/null 2>&1; then
  fuser -k 8010/tcp >/dev/null 2>&1 || true
fi
nohup python3 "$SCRIPT_DIR/control_plane.py" >> "$LOG_DIR/control-plane.log" 2>&1 < /dev/null &

echo "[2/2] Building and starting Docker stack (Unified Web on http://127.0.0.1:3000)..."
cd "$SCRIPT_DIR"
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
  docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build
else
  docker compose -f docker-compose.yml --profile full up -d --build
fi

echo ""
echo "Project-Malaria is UP -> http://127.0.0.1:3000"
echo "Configure local GGUF models or cloud keys at -> http://127.0.0.1:3000/models"
