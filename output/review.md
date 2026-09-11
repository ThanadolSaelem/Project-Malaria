# รายการรอรีวิว

ทั้งหมด 2 รายการ เรียงตามจำนวนบรรทัดจากมากไปน้อย

## 1. cluster 3 (length=5, count=2172)

ตัวอย่างจริง: `service nginx restarted on host19`

Template ร่าง: `service text-ambiguous restarted on <STR>`

- ตำแหน่ง 1: text-ambiguous — ค่าที่พบ: cron, nginx

## 2. cluster 13 (length=15, count=41)

ตัวอย่างจริง: `connection from 10.0.0.100 to 10.0.0.49 denied by rule 3 for user user171 on host host05`

Template ร่าง: `connection from <IP> to <IP> {allowed|denied} by rule numeric-gray-zone for user <STR> on host <STR>`

- ตำแหน่ง 8: numeric-gray-zone — ค่าที่พบ: 1, 2, 3

--- ตำแหน่งที่ระบบตัดสิน split เอง (ให้ sanity-check เพิ่มเติม) ---
- ตำแหน่ง 5: sensitive_word — ค่า: allowed, denied
