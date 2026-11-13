#!/usr/bin/env bash
# =============================================================================
# install-mitm-ca.command — ติดตั้งและเชื่อถือ Mitmproxy Root CA ของ ARTEX บน macOS
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PIPELINE="$(cd "$HERE/.." && pwd)"
CA_DIR="$PIPELINE/artex/data/traffic/_ca"
CA_CER="$CA_DIR/mitmproxy-ca-cert.cer"
CA_PEM="$CA_DIR/mitmproxy-ca-cert.pem"

echo "════════════════════════════════════════════════════════════════"
echo "  ARTEX — ติดตั้งและเชื่อถือ Mitmproxy Root CA Certificate"
echo "════════════════════════════════════════════════════════════════"

if [ ! -f "$CA_CER" ] && [ ! -f "$CA_PEM" ]; then
  echo "[!] ไม่พบไฟล์ Root CA ใน $CA_DIR"
  echo "    กรุณาสตาร์ท ARTEX อย่างน้อย 1 ครั้ง เพื่อให้ระบบสร้างไฟล์ CA อัตโนมัติ"
  echo "    (คำสั่ง: cd pipeline && docker compose --profile artex up -d)"
  exit 1
fi

if [ ! -f "$CA_CER" ] && [ -f "$CA_PEM" ]; then
  echo "[*] กำลังแปลง $CA_PEM เป็น DER .cer..."
  openssl x509 -outform der -in "$CA_PEM" -out "$CA_CER" 2>/dev/null || true
fi

TARGET_CERT="$CA_CER"
[ ! -f "$TARGET_CERT" ] && TARGET_CERT="$CA_PEM"

echo "[*] พบไฟล์ใบรับรอง:"
[ -f "$CA_CER" ] && echo "    - CER: $CA_CER"
[ -f "$CA_PEM" ] && echo "    - PEM: $CA_PEM"
echo "    - Target to Trust: $TARGET_CERT"
echo ""

# ตรวจสอบว่ามีใบรับรอง mitmproxy ใน Keychain แล้วหรือยัง
if security find-certificate -c "mitmproxy" ~/Library/Keychains/login.keychain-db >/dev/null 2>&1 || \
   security find-certificate -c "mitmproxy" /Library/Keychains/System.keychain >/dev/null 2>&1; then
  echo "[OK] ใบรับรอง 'mitmproxy' ถูกติดตั้งใน macOS Keychain อยู่แล้ว"
else
  echo "[+] กำลังติดตั้งใบรับรองเข้าสู่ Login Keychain ของคุณ..."
  security add-trusted-cert -d -r trustRoot -k ~/Library/Keychains/login.keychain-db "$TARGET_CERT"
  echo "[OK] ติดตั้งใบรับรองและตั้งค่า Always Trust เรียบร้อยแล้ว!"
fi

echo ""
echo "────────────────────────────────────────────────────────────────"
echo "การตั้งค่าให้อุปกรณ์อื่น (มือถือ iOS / Android / คอมเครื่องอื่น) วิ่งผ่าน Proxy:"
echo "────────────────────────────────────────────────────────────────"

# ดึง IP เครื่อง Mac ในวง Wi-Fi
MAC_IP="$("$HERE/mobile-link.sh" --ip-only 2>/dev/null || true)"
[ -z "$MAC_IP" ] && MAC_IP="<IP_เครื่อง_Mac_ของคุณ>"

echo "1. นำไฟล์ใบรับรอง $CA_CER หรือ $CA_PEM ส่งไปติดตั้งในมือถือ:"
echo "   - iOS: ส่งผ่าน AirDrop -> ไปที่ Settings -> Profile Downloaded -> Install"
echo "          จากนั้นไปที่ Settings -> General -> About -> Certificate Trust Settings -> เปิด Full Trust"
echo "   - Android: Settings -> Security -> Install from storage -> CA Certificate"
echo ""
echo "2. ตั้งค่า Wi-Fi Proxy บนอุปกรณ์ของคุณ:"
echo "   - Proxy Host : $MAC_IP"
echo "   - Proxy Port : 8788 (หรือพอร์ต Proxy ที่ตั้งไว้ใน ARTEX)"
echo "────────────────────────────────────────────────────────────────"
read -n 1 -s -r -p "กดปุ่มใดๆ เพื่อเสร็จสิ้น..."
echo ""
