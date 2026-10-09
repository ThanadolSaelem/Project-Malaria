# วางไฟล์ handshake ที่จับมาที่นี่ (.cap / .pcap / .hccapx)
# aircrack-ng/hashcat ในคอนเทนเนอร์ hexstrike-server อ่านได้ที่ /captures
#
# ⚠️ การ "จับ" handshake (airodump-ng + monitor mode) ทำในคอนเทนเนอร์ไม่ได้ —
#    ต้องจับบนเครื่อง/การ์ด WiFi จริง แล้วเอาไฟล์ .cap มาวางที่โฟลเดอร์นี้
# ตัวอย่างแครก (ผ่าน Tiel/HexStrike execute_command หรือรันเองในคอนเทนเนอร์):
#   aircrack-ng -w /usr/share/wordlists/rockyou.txt -b <BSSID> /captures/handshake.cap
