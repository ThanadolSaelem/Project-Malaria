#!/usr/bin/env bash
# =============================================================================
# ติดตั้งเครื่องมือความปลอดภัย "core" ผ่าน Homebrew (Apple Silicon / arm64)
# รันครั้งเดียวพอ — ตัวที่ไม่มีใน brew จะข้ามไป ไม่ทำให้ทั้งชุดหยุด
# ใช้: bash pipeline/mac/1-install-tools.sh
# =============================================================================
set -uo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "ไม่พบ Homebrew — ติดตั้งก่อน: https://brew.sh"
  exit 1
fi

echo "[brew] ติดตั้งเครื่องมือ core (arm64)…"
TOOLS=(nmap masscan nuclei ffuf gobuster feroxbuster sqlmap nikto
       subfinder amass hydra john dirb whatweb)
for t in "${TOOLS[@]}"; do
  if brew list "$t" >/dev/null 2>&1; then
    echo "  ✓ $t (มีแล้ว)"
  else
    brew install "$t" && echo "  ✓ $t" || echo "  ⚠️  ข้าม $t (ไม่มีใน brew/ error — เพิ่มทีหลังได้)"
  fi
done

echo ""
echo "เสร็จ — เครื่องมือที่ไม่มีใน brew (เช่น metasploit, httpx ของ projectdiscovery)"
echo "ติดตั้งแยกภายหลังได้ ตัวที่ขาด hexstrike จะรายงานว่า unavailable เฉยๆ ไม่ crash"
echo "(ถ้าต้องการ browser automation: brew install --cask chromium)"
