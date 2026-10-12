# REA — Reverse Engineer Anything (MCP service)

ให้ Tiel (และคุณ) แกะ **binary / APK / firmware / JS·Electron / .NET / WASM / เว็บไซต์ /
พฤติกรรม runtime** ผ่าน MCP โดยใช้ [REA](https://github.com/morluto/rea) (`rea-agents`)

เหมาะกับงานสืบสวนของเรา: แกะ **APK แอปมิจฉาชีพ**, วิเคราะห์ malware/firmware,
ดูโครงสร้าง JS ของเว็บหลอกลวง ฯลฯ

## สถาปัตยกรรม

```
HarnessRouter ──(http://rea-mcp:8007/mcp)──► supergateway ──(stdio)──► rea mcp
                                                                         │
                         Ghidra · apktool · JADX · binwalk · unblob · chromium · wabt
```
REA พูด MCP แบบ **stdio** เท่านั้น → ครอบด้วย **supergateway** แปลงเป็น streamable-HTTP
ให้ HarnessRouter ต่อด้วย url เดียว (pattern เดียวกับ hexstrike-mcp)

## เครื่องมือในคอนเทนเนอร์ (ตาม provider ของ REA)

| provider | tool ที่ลงให้ | env ที่ REA ใช้ |
|---|---|---|
| Native binary | **Ghidra** (+ JDK 21) | `GHIDRA_INSTALL_DIR=/opt/ghidra` |
| Android/APK | **apktool** (ทรัพยากร) + **JADX** (Java source) | `REA_APKTOOL_COMMAND` |
| Firmware | **binwalk 3.x** + **unblob** | `REA_BINWALK_COMMAND` / `REA_UNBLOB_COMMAND` |
| เว็บไซต์ | **chromium** (CDP) | `CHROME_BIN` |
| WASM | **wabt** | — |
| JS/Electron/.NET | Node ในตัว | — |

> **IDA/Hopper ไม่ลง** (commercial/GUI) — ใช้ Ghidra แทนสำหรับ native binary

## วิธีใช้

1. วางไฟล์เป้าหมายที่ `pipeline/rea-targets/` → คอนเทนเนอร์เห็นที่ `/work/targets/`
2. สตาร์ท (profile full):
   ```bash
   cd pipeline
   docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile full up -d --build rea-mcp
   ```
3. ลงทะเบียนใน HarnessRouter Console เป็น **remote HTTP MCP**: `http://rea-mcp:8007/mcp`
4. เช็ก provider ไหนพร้อม (tool ไหนลงสำเร็จ):
   ```bash
   docker compose ... exec rea-mcp rea doctor
   docker compose ... exec rea-mcp rea inspect-apktool-client
   ```

## หมายเหตุ build (อ่านก่อน)

- ⚠️ **image ใหญ่ + build นาน** (Ghidra ~400MB, JDK, chromium, unblob deps) → profile `full`
- ออกแบบ **ทนพลาด**: tool ไหนโหลด/ลงไม่สำเร็จจะ **ข้าม** (WARN) ไม่ล้ม build — REA จะ
  รายงาน provider นั้น unavailable เอง (`rea doctor`) ส่วน provider อื่นยังใช้ได้
- `binwalk` prebuilt arm64 อาจไม่มีในบาง release — ถ้าข้าม ใส่ `REA_BINWALK_COMMAND`
  ชี้ไป binary ที่คุณ build เองได้
- `rea-agents` **pin ที่ 6.4.0** (กัน supply-chain) — อยากอัปเดตแก้เลขใน Dockerfile แล้ว rebuild
- การแกะเว็บ: REA **attach เข้า chromium ที่รันค้างไว้** (ไม่ได้เปิดเอง) — ต้องสตาร์ท
  chromium ด้วย `--remote-debugging-port` ก่อน (ดู docs/browser-observation.md ของ REA)

## ความปลอดภัย

- ไฟล์ใน `rea-targets/` อาจเป็น **malware** — REA แค่ "อ่าน/วิเคราะห์" (static เป็นหลัก)
  แต่ฟีเจอร์ runtime capture จะ "รัน" target ด้วยสิทธิ์ของ process → ระวัง, จำกัด network
  ของคอนเทนเนอร์เมื่อแกะตัวอย่างที่ไม่ไว้ใจ
- โมเดล `rea-agents` ลงจาก npm (ไม่มี postinstall, prepare ไม่รันตอนลง published package)
- `.gitignore` กันไม่ให้ commit ไฟล์เป้าหมายจริง (เก็บแค่ README)
