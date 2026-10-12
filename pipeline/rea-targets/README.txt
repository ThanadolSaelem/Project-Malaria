# วางไฟล์เป้าหมายที่จะให้ REA แกะที่นี่ (.apk / binary / .bin firmware / .exe / .dll / .wasm ฯลฯ)
# คอนเทนเนอร์ rea-mcp เห็นที่ /work/targets
# ตัวอย่างสั่งผ่าน Tiel/REA (ชื่อ tool ดูใน HarnessRouter หลัง register):
#   analyze APK:      /work/targets/app.apk
#   firmware regions: /work/targets/firmware.bin
# ⚠️ ไฟล์ตัวอย่างอาจเป็น malware — คอนเทนเนอร์นี้แยก network ได้ ควรรันแบบ sandbox
