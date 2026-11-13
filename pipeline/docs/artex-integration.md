# คู่มือการบูรณาการระบบ ARTEX เข้าสู่ Project-Malaria
=============================================================================

ระบบ **ARTEX (AI Autonomous Penetration Testing Platform)** ได้รับการบูรณาการเข้าสู่สถาปัตยกรรมของ **Project-Malaria** อย่างสมบูรณ์ เพื่อให้คุณสามารถใช้งานฟีเจอร์ระดับองค์กรทั้งหมด ทั้ง Web UI Dashboard, กราฟจำลองการทดสอบเจาะระบบ, ระบบดักจับและอนุมัติคำสั่งอันตราย (Human-in-the-loop Interception), ส่วนขยายเบราว์เซอร์สำหรับอัด Traffic และคลังทักษะการโจมตีเชิงรุก

---

## 1. ฟีเจอร์หลักของ ARTEX ที่เพิ่มเข้ามาในระบบ

| ฟีเจอร์ | รายละเอียด | พอร์ต / ตำแหน่งไฟล์ |
|---|---|---|
| **Web UI & Exploration Graph** | หน้าแดชบอร์ด Next.js แสดงผังกราฟการสำรวจเป้าหมาย (Force-directed Asset Coverage Graph), สถานะเซสชัน, Token Usage และ Activity Stream แบบเรียลไทม์ | `http://localhost:8787` |
| **PostgreSQL Database** | ฐานข้อมูล PostgreSQL 16 สำหรับเก็บ Assets, Findings, Sessions, Evidence และ Traffic | `127.0.0.1:5433` (service `artex-db`) |
| **Interception & Approvals** | ระบบตรวจจับและพักรอการอนุมัติคำสั่งที่มีความเสี่ยงสูง/ออกนอกขอบเขต แสดงรายละเอียด Payload แบบ AegisHook ให้กดยืนยันหรือปฏิเสธได้ | หน้าจอ **Interception Approvals** ใน UI |
| **Traffic Capture Extension** | Chrome/Edge Extension บันทึก Network Traffic จากเบราว์เซอร์ของผู้ใช้ (รวมช่วงล็อกอินผ่าน CAPTCHA / 2FA / OTP) ส่งตรงเข้า Traffic Store | `pipeline/extension/` |
| **Asset Sync (ScopeSentry)** | เชื่อมโยงและซิงก์รายการ Subdomain, IP, Port, URL จากระบบ ScopeSentry เข้าสู่ Asset Graph อัตโนมัติ | เมนู **Asset Sync** ใน UI |
| **Finding Workflow & Retest** | กระบวนการบันทึกช่องโหว่ที่มีการกำจัดความซ้ำซ้อน (Dedup), ตรวจสอบคุณภาพหลักฐาน (Provenance) และลูปทดสอบซ้ำอัตโนมัติ (Retest) | เมนู **Findings** ใน UI |
| **RSI & Lesson Engine** | บันทึกบทเรียนและสถิติจากภารกิจ (`/api/tasks/{id}/outcome` และ `/api/skill-gaps`) สอดคล้องกับกรอบ PPC ใน `prompt-tuning-ppc.md` | `pipeline/artex/RSI.md` |
| **Specialized Skills Catalog** | คลังทักษะเฉพาะทาง 9 ทักษะที่เชื่อมทั้ง ARTEX และ Qwen Code (`/workspace/.qwen/skills/`) | `pipeline/skills/` |

---

## 2. ทักษะเฉพาะทางใหม่ (Specialized Skills)

ทักษะทั้งหมดได้รับการติดตั้งไว้ใน `pipeline/skills/` และส่งผ่านเข้าคอนเทนเนอร์ Qwen Code (`:3080`) และ ARTEX (`:8787`) อัตโนมัติ:

1. **`api-recon`**: สำรวจโครงสร้าง Frontend API, วิธีการ (Methods), พารามิเตอร์ และ Mock Client-side Auth Bypass สำหรับ SPA
2. **`api-security`**: ตรวจสอบช่องโหว่ API เชิงลึก (BOLA/IDOR, BFLA, JWT, OAuth, GraphQL Introspection Abuse, Mass Assignment)
3. **`bbot-recon`**: รัน recursive reconnaissance แบบ event-graph ด้วย bbot ภายใต้นโยบายความปลอดภัย
4. **`codeaudit`**: ตรวจสอบช่องโหว่ใน Source Code สำหรับ white-box assessment
5. **`patch-diff`**: วิเคราะห์ Git Commit Diff และ Security Patch เพื่อหาจุดบกพร่องที่ซ่อนอยู่
6. **`playwright-cli`**: ควบคุมเบราว์เซอร์อัตโนมัติและจำลองการคลิก/กรอกข้อมูลหน้าเว็บ
7. **`scopesentry`**: บริหารจัดการและซิงก์สินทรัพย์จาก ScopeSentry แพลตฟอร์ม
8. **`php2shell`**: อาวุธทดสอบช่องโหว่ PHP Upload Progress (CVE-2026-109618 / 109619)
9. **`rea`**: แกะและทำ Reverse Engineering ไฟล์ไบนารี, APK, WASM, Firmware ผ่าน REA MCP
10. **`edr-bypass-re`**: วิเคราะห์กลไก EDR Telemetry (User-mode Hooking, ETW/AMSI, Kernel Callbacks) และเทคนิค Bypass ในสภาพแวดล้อมแล็บที่ได้รับอนุญาต (MITRE ATT&CK T1562)

---

## 3. สถาปัตยกรรมการเชื่อมต่อ (Integration Architecture)

```
[ Browser / User ] ─── Port 8787 ───> [ ARTEX Web Platform (Go + Next.js) ]
                                                │
       ┌────────────────────────────────────────┼────────────────────────┐
       ▼                                        ▼                        ▼
[ artex-db (:5433) ]                [ LiteLLM Gateway (:4000) ]     [ MCP Microservices ]
  PostgreSQL 16                       - cyber-model (:8091)           - HexStrike (:8001)
                                      - flint / orchestrator (:8090)  - REA (:8007)
                                      - vision (:8093)                - CVE (:8009)
                                      - nim / or-glm (cloud)          - Search (:8004)
                                                                      - Specialist (:8003)
```

- **LLM Engine**: ARTEX ถูกตั้งค่าชี้ไปที่ `http://litellm:4000/v1` ใช้ Model `cyber-model` หรือ `flint` ที่รันบน Mac โดยตรง
- **MCP Microservices**: สามารถเชื่อมต่อ MCP ทั้งหมดของ Project-Malaria ได้ทาง Streamable HTTP
- **Qwen Code Studio**: มี Qwen Code Studio ทำงานควบคู่กันบนพอร์ต `:3080` โดยแบ่งปัน Evidence, Reports และ Skills ร่วมกัน

---

## 4. วิธีเริ่มใช้งานระบบ

### วิธีที่ 1: รันผ่านปุ่มเดียวบน Mac (แนะนำ)
ดับเบิลคลิกไฟล์:
```bash
pipeline/mac/start.command
```
สคริปต์จะสตาร์ทโมเดลบน Mac (`:8090`, `:8091`, `:8093`) และรัน Docker Stack ทั้งหมดรวมถึง ARTEX (`:8787`), Qwen Code (`:3080`), n8n (`:5678`) และ MCP Microservices

### วิธีที่ 2: รันเฉพาะ ARTEX ผ่าน Docker Compose
```bash
cd pipeline
docker compose -f docker-compose.yml -f docker-compose.mac.yml --profile artex up -d --build
```

### การตั้งค่า Admin ครั้งแรก (First-run Setup)
1. เปิดเบราว์เซอร์ไปที่: `http://localhost:8787/setup`
2. ดูรหัส Setup Token ครั้งแรกจาก log:
   ```bash
   docker compose logs artex | grep "Setup token"
   ```
3. กำหนดรหัสผ่านของระบบ Admin เพื่อเข้าสู่แดชบอร์ดหลัก

---

## 5. วิธีติดตั้ง Traffic Capture Browser Extension

1. เปิดเบราว์เซอร์ **Google Chrome** หรือ **Microsoft Edge**
2. ไปที่ URL: `chrome://extensions/`
3. เปิดสวิตช์ **Developer mode** ที่มุมขวาบน
4. คลิกปุ่ม **Load unpacked** (โหลดส่วนขยายที่ยังไม่ได้แพ็กเกจ)
5. เลือกโฟลเดอร์:
   ```text
   /Users/thanadol/Desktop/Project-Malaria/pipeline/extension
   ```
6. คลิกไอคอนส่วนขยาย ARTEX ที่แถบเครื่องมือ กรอก URL `http://localhost:8787` และ Token ของคุณ แล้วกด **Start capture** เพื่อบันทึกทราฟฟิกหน้าเว็บ

---

## 6. การติดตั้งและเชื่อถือ Mitmproxy Root CA Certificate (Proxy Capture)

ARTEX มีระบบ MITM Proxy ดักจับ HTTPS Traffic ในตัว ทำงานบนพอร์ต `8788` โดยเมื่อเริ่มทำงานครั้งแรก ระบบจะสร้างใบรับรอง Root CA อัตโนมัติไว้ที่ `pipeline/artex/data/traffic/_ca/`:
- `mitmproxy-ca-cert.pem`
- `mitmproxy-ca-cert.cer`

### 6.1 ติดตั้งและเชื่อถือบน macOS (คลิกเดียว)
ดับเบิลคลิกไฟล์สคริปต์:
```bash
pipeline/mac/install-mitm-ca.command
```
สคริปต์จะนำไฟล์ CA Certificate เพิ่มเข้าสู่ **macOS Login Keychain** พร้อมตั้งค่า **Always Trust** ให้อัตโนมัติ

### 6.2 การตั้งค่าบนอุปกรณ์ภายนอก (มือถือ iOS / Android)
1. ส่งไฟล์ `pipeline/artex/data/traffic/_ca/mitmproxy-ca-cert.cer` หรือ `.pem` ไปยังอุปกรณ์
   - **iOS**: ส่งผ่าน AirDrop -> ไปที่ **Settings -> Profile Downloaded -> Install** -> จากนั้นไปที่ **Settings -> General -> About -> Certificate Trust Settings** -> เปิดสวิตช์ **Enable Full Trust for Root Certificates**
   - **Android**: ไปที่ **Settings -> Security -> Encryption & credentials -> Install a certificate -> CA certificate**
2. ตั้งค่า Wi-Fi Proxy บนอุปกรณ์:
   - **Proxy Host**: IP ของเครื่อง Mac ในวง Wi-Fi (สามารถดูได้จากสคริปต์ `install-mitm-ca.command` หรือรัน `pipeline/mac/mobile-link.sh --ip-only`)
   - **Proxy Port**: `8788`

---

## 7. การเชื่อมต่อและการใช้งาน ScopeSentry (Local Deployment)

ScopeSentry เป็นแพลตฟอร์มบริหารจัดการสินทรัพย์ (Attack Surface Management - ASM) และสแกนหาช่องโหว่อัตโนมัติ ถูกผนวกรวมเข้ากับ Docker Compose ของ Project-Malaria:

### 7.1 บริการของ ScopeSentry ใน Docker Stack
| คอนเทนเนอร์ | อิมเมจ | บทบาท / พอร์ต |
|---|---|---|
| `scopesentry-mongodb` | `mongo:7.0.4` | เก็บข้อมูลโปรเจกต์ สินทรัพย์ และผลการสแกน (`127.0.0.1:27017`) |
| `scopesentry-redis` | `redis:7.0.11` | คิวงานและระบบสื่อสารระหว่างโหนดสแกน (`127.0.0.1:6379`) |
| `scope-sentry` | `autumn27/scopesentry:latest` | แดชบอร์ดหลัก Web UI (`:8082`) และ Native MCP Server (`/mcp`) |
| `scopesentry-scan` | `autumn27/scopesentry-scan:latest` | โหนดสแกนเนอร์แจกจ่ายงาน (`node-malaria`) |

### 7.2 คำสั่งสตาร์ท ScopeSentry
รันผ่าน profile `scopesentry`:
```bash
cd pipeline
docker compose --profile scopesentry up -d
```
หรือหากต้องการรันร่วมกับ ARTEX และเครื่องมืออื่นๆ ทั้งหมด:
```bash
docker compose --profile full up -d
```

### 7.3 การดึงรหัสผ่านเริ่มต้นและสร้าง API Key
1. ดูรหัสผ่านผู้ดูแลระบบ (Admin) จากคอนเทนเนอร์ `scope-sentry`:
   ```bash
   docker logs scope-sentry | grep -i password
   ```
2. เปิดเบราว์เซอร์ไปที่: `http://localhost:8082` แล้วล็อกอินด้วยผู้ใช้ `admin` และรหัสผ่านที่ได้
3. ไปที่เมนู **API Key** ใน ScopeSentry Web UI แล้วคลิก **Create API Key**
4. คัดลอกรหัสคีย์ที่ขึ้นต้นด้วย `ssk_...` (คีย์นี้จะแสดงเพียงครั้งเดียว)

### 7.4 การเชื่อมต่อ ScopeSentry เข้ากับ ARTEX (Asset Sync)
1. เปิด ARTEX แดชบอร์ดที่ `http://localhost:8787`
2. ไปที่เมนู **Asset Sync**
3. กำหนดค่าการเชื่อมต่อ:
   - **MCP Server URL**: `http://scope-sentry:8082/mcp`
   - **API Key**: `ssk_...` ที่สร้างไว้
4. กด **Save & Test Connection** เมื่อสถานะขึ้น Reachable คุณสามารถเลือกดึงรายการโปรเจกต์และสินทรัพย์ (Subdomain, Web Application, Port, URL) ซิงก์เข้าสู่ผังกราฟการสำรวจ (Exploration Graph) ของ ARTEX ได้ทันที

### 7.5 การเชื่อมต่อ ScopeSentry กับ Qwen Code Studio / LLM Agent
ScopeSentry MCP ได้รับการลงทะเบียนใน `pipeline/node-config.json` และ `pipeline/qwen-code/settings.json` เรียบร้อยแล้ว โมเดลสามารถเรียกใช้ชุดเครื่องมือ:
- `list_projects`: แสดงโครงสร้างโปรเจกต์
- `create_project`: สร้างโปรเจกต์เป้าหมายใหม่
- `list_assets`: ค้นหาและกรองรายการสินทรัพย์
- `count_assets`: นับจำนวนสินทรัพย์
- `create_scan_task`: สั่งเริ่มภารกิจสแกนหาช่องโหว่
- `list_tasks` / `get_task`: ตรวจสอบสถานะการทำงานของสแกนเนอร์

