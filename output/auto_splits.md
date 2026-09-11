# Auto-split positions (ตัดสินโดยระบบอัตโนมัติ)

ทั้งหมด 4 รูปแบบ template เรียงตาม volume
รายการเหล่านี้คือตำแหน่งที่ระบบตัดสิน split เอง (sensitive word หรือ numeric enum)
ไม่ต้องตอบคำถาม — แต่อาจต้องการ sanity-check ว่าตรงกับความคาดหวังไหม


## 1. cluster 17 (length=15, count=5066)

Template: `connection from <IP> to <IP> {allowed|denied} by rule <NUM> for user <STR> on host <STR>`

- ตำแหน่ง 5: sensitive_word — ค่าที่พบ: allowed, denied

## 2. cluster 29 (length=6, count=2344)

Template: `PacketResponder {0|1|2|3} for block <BLK> terminating`

- ตำแหน่ง 1: numeric_enum — ค่าที่พบ: 0, 1, 2, 3

## 3. cluster 28 (length=8, count=854)

Template: `EventID {4624|4625} for user <STR> on host <STR>`

- ตำแหน่ง 1: numeric_enum — ค่าที่พบ: 4624, 4625

## 4. cluster 13 (length=15, count=41)

Template: `connection from <IP> to <IP> {allowed|denied} by rule numeric-gray-zone for user <STR> on host <STR>`

- ตำแหน่ง 5: sensitive_word — ค่าที่พบ: allowed, denied
