# Approved source implementation — Project-Malaria

ผู้ใช้อนุมัติให้เริ่มแก้ source ตามข้อเสนอด้านล่าง โดยห้ามตัดฟีเจอร์โดยไม่ถาม เมื่อ 13 พฤศจิกายน 2026

สถานะข้อเสนอต้นฉบับด้านล่างเป็นประวัติก่อนอนุมัติ; สถานะงานปัจจุบันติดตามใน TODO.md งานนี้ source-only ยังไม่ install/build/typecheck/test/run และไม่ commit/push/publish

Diagnostics: webdev.config GET runtime/post-edit returned “No active project for post-edit processing”. ไม่ initialize/attach/security-repo hosting เพียงเพื่อเปิด diagnostics และยังไม่ใช้ check-only commands เนื่องจาก scope การรันยังไม่อนุมัติ จึงไม่กล่าวว่าผ่าน compiler/runtime checks

---

# แผนเสนออนุมัติ: เว็บเดียวสำหรับ Qwen, ARTEX, ScopeSentry และ Observer

สถานะ: **ข้อเสนอเท่านั้น ยังไม่ได้แก้ source/config ใน Project-Malaria หรือติดตั้ง/build/run/test ระบบ**

## ผลลัพธ์และข้อกำหนดที่ยืนยันแล้ว

รวมทั้งสี่ระบบเป็น Web application เดียว ใช้ธีมและ color palette จาก source Qwen ที่ผู้ใช้แนบ และเอาโลโก้ Qwen/ARTEX ออกจาก UI โดยเก็บ license, notices, Terms และ attribution ที่เกี่ยวข้องไว้ครบ ไม่ใช้ iframe หรือเพียงลิงก์ไปเปิดอีกเว็บเป็นผลลัพธ์สุดท้าย

ต้องคงฟีเจอร์ทุกฝั่ง ไม่แทนแชต ARTEX ด้วย Qwen ไม่ลด Qwen เหลือเพียงกล่องแชต ไม่ลด ScopeSentry เหลือ Asset Sync และไม่ลด Observer เหลือการ์ดสรุปบางใบ รายการอ้างอิงอยู่ใน [ข้อกำหนดการรักษาฟีเจอร์](/home/ubuntu/unified-ui-proposal/feature-inventory.md) รายการนี้เป็นผลตรวจ source ไม่ใช่ผลยืนยันการทำงานจริง

ยึด `main` commit `605e7bdfcce81a9b7042d3d35a9f7e843386c92a` เป็นฐาน ไม่เขียนทับ working tree เดิมบน `pipeline-deepseek` ซึ่งมีงานค้างอยู่ หากอนุมัติจะสร้าง worktree แยกจากฐานนี้ ไม่มี commit, push หรือ public deployment ในขอบเขตที่ขออนุมัติ

## แนวทางรวมที่เสนอ

สร้าง frontend กลางแบบ Next.js/React โดยใช้หน้าและ components ของ ARTEX บน main เป็นฐาน เพื่อลดการเขียนใหม่และรักษาหน้าฟังก์ชันเดิม ใช้หน้าตา Qwen เป็น design system ของแอป ไม่จำเป็นต้องย้าย ARTEX ทุกหน้าไป Vite เพียงเพื่อให้ใช้ธีม Qwen

ฝั่ง Qwen จะใช้ source ที่แนบทั้ง CLI/runtime และ Web Shell เต็มรูปแบบ เพิ่ม embedding entry/adapter ที่คง provider composition, native pages, sidebar/footer, workspace/session catalog และความสามารถ standalone ที่เกี่ยวข้องไว้ ไม่ใช้ `WebShellWithProviders sidebar={false}` แล้วอ้างว่าเก็บฟีเจอร์ครบ

ฝั่ง ScopeSentry จะใช้ Vue components/router/store เดิมผ่าน mount adapter ภายใน document เดียว ไม่แปลงทุกหน้าเป็น React ใหม่โดยไม่จำเป็น Router ย่อยต้องผูกกับ navigation กลางผ่าน adapter ไม่ให้หลาย router แย่งกันแก้ URL การแยก React/Vue ภายในเป็นรายละเอียด implementation ไม่ใช่การเปิดสองเว็บไซต์

ฝั่ง Observer จะย้ายเฉพาะ presentation มาเป็นหน้าใน frontend กลาง โดยยังเรียก backend Python เดิม ไม่ย้ายการอ่าน Docker logs, memory หรือการเรียก LiteLLM มาไว้ใน browser

ทุก module มี navigation ระดับแอปชุดเดียวและเมนูตาม context เพื่อให้ฟีเจอร์จำนวนมากยังเข้าถึงได้ เช่น AI Workspace, ARTEX Workspace, ScopeSentry และ Observer ชื่อเหล่านี้เป็นป้ายบอกเจ้าของงาน ไม่ได้เปลี่ยนชื่อ ID, API, JWT subject, MCP row หรือข้อมูลภายใน ระบบตั้งค่าที่หน้าตาคล้ายกันยังคงแยกตามเจ้าของ ไม่รวม semantics เข้าด้วยกัน

Qwen provider และ state ต้องคงอยู่ขณะสลับ module ไม่เริ่ม session ใหม่ ไม่หยุดงานหรือทิ้ง draft เพียงเพราะเปิดหน้าอื่น ความสามารถที่เดิมมี capability/permission gate ยังคง gate เดิม ไม่เปิด managed mode, agent team หรือเครื่องมือเพิ่มโดยอัตโนมัติ

## Gateway และ backend

เพิ่ม gateway สำหรับ frontend และการเรียก API ผ่าน origin กลาง เสนอเส้นทาง module `/ai`, `/artex`, `/scopesentry`, `/observer` โดยรักษา deep links เดิมผ่าน route adapter หรือ compatibility redirect ไม่ลบ deep links เงียบ ๆ รายละเอียด prefix ของ API/static assets ต้องถูกตรวจใน implementation ก่อนผูกใช้งาน หากต้องเปลี่ยน contract หรือพฤติกรรมนอกที่ระบุนี้จะหยุดถามใหม่

Gateway ต้อง namespace API ของแต่ละบริการ ไม่ส่ง Bearer token ของ Qwen ไปแทน JWT ของ ARTEX หรือ ScopeSentry และไม่ให้ LiteLLM/API keys ฝั่ง backend หลุดไป browser ไม่มี SSO, token exchange, account merge หรือ database merge ในแผนนี้ ผู้ใช้ยัง authenticate แต่ละ module ตามระบบเดิม เพียงทำจากหน้าในเว็บเดียวกัน

ต้องรักษา streaming ที่มีอยู่จริง รวมถึง SSE และ WebSocket ของความสามารถที่ใช้มัน ตลอดจน multipart uploads, binary/range downloads, Content-Disposition, status/error envelopes และ long-running requests ไม่ buffer stream เป็น JSON และไม่ retry คำสั่งที่เขียนข้อมูลหรือเริ่มงานโดยไม่ทราบผล

ScopeSentry มี root-oriented paths เช่น `/api`, `/images`, `/map`, `/mcp` และ static assets จึงต้องมี mapping ครบ ไม่เปลี่ยนเพียง API base แล้วปล่อยให้ map, screenshot หรือ export เสีย Observer ยังคง `GET /state` และ polling behavior เดิมภายใต้ adapter

Backend ยังคงแยก: Qwen daemon/runtime; ARTEX Go/PostgreSQL/traffic proxy; ScopeSentry server/scanner/MongoDB/Redis/plugin runtime; Observer host Python/LiteLLM งานรวม UI จะไม่เริ่ม scan, run plugin, approve tool, ติดตั้ง CA หรือควบคุม process จริงเพื่อทดสอบ

ไม่ลดหรือเพิ่มการเข้าถึงจาก LAN โดยปริยาย Qwen มี LAN behavior เดิม แต่ Observer เดิมฟัง loopback และไม่มี auth จึงต้องรักษาขอบเขตนี้ใน gateway ไม่เปิด Observer ให้ LAN ใช้เพียงเพราะอยู่ในเว็บเดียวกัน หากการออกแบบพบว่าคงขอบเขตเดิมไม่ได้ จะเสนอการเปลี่ยนให้อนุมัติก่อน

## หน้าตาที่เสนอ

ใช้ utility-first developer workspace ตาม Qwen เดิม ไม่ทำ landing page หรือเพิ่มภาพตกแต่ง มี sidebar/context navigation, content workspace และ detail/right panel ตามความเหมาะสม คงการแสดงข้อมูล ตาราง code/evidence และ diff ไม่ลดรายละเอียดเพื่อความสวยงาม

ใช้ light/dark tokens จาก Qwen source โดยตรง ตัวอย่างพื้นหลัง dark `#0d0d0d`, ข้อความ `#fafafa`, accent blue `#6785ff`; light ใช้พื้นขาว ข้อความเข้ม `#0a0a0b` และ accent `#0033ff` ร่วมกับ semantic shadcn tokens ของ source ไม่เหมารวมว่าสี primary ของทุก component ต้องเป็นน้ำเงิน สีระดับความเสี่ยงและสถานะยังคงความหมายเดิม

มี theme owner เดียวและส่ง resolved theme ให้ทุก module รักษา scoped CSS และ portal roots ของ Qwen พร้อม adapter tokens สำหรับ ARTEX/ScopeSentry ใช้ font preferences และ code typography เดิม ไม่เพิ่ม dependency ฟอนต์ใหม่โดยไม่จำเป็น การเคลื่อนไหวสั้นและไม่รบกวนงาน เคารพ reduced-motion และรักษา keyboard focus/dialog behavior

ชื่อแอปด้านนอกใช้ข้อความ `Project-Malaria` ไม่เพิ่มโลโก้ใหม่ เอาเฉพาะโลโก้/เครื่องหมายแบรนด์ Qwen และ ARTEX ใน UI/product chrome ออก ไม่ลบชื่อที่เป็น technical identifier หรือ legal attribution และไม่ลบโลโก้ ScopeSentry/Observer โดยอนุมานจากคำขอ

## ตำแหน่งไฟล์และขอบเขตเปลี่ยนแปลงที่เสนอ

รายการต่อไปนี้เป็นขอบเขตที่ขออนุมัติ ไม่ใช่รายการไฟล์ที่แก้แล้ว หากต้องแตะนอกขอบเขตนี้จะถามใหม่

- `pipeline/qwen-source/`: นำ source จาก ZIP ที่ตรวจไว้เข้า repository โดยเก็บ licenses/notices เป็นฐานสำหรับ build ไม่ fallback ไปติดตั้ง Qwen npm คนละ source
- Qwen ภายใต้ `pipeline/qwen-source/packages/web-shell/`: เพิ่ม standalone-host embedding/navigation/theme/branding adapter และ build/export ที่จำเป็น ไม่ refactor core, model providers, tools หรือ permission engine เพื่อรวม UI
- `pipeline/unified-web/`: frontend กลางและหน้าจอ ARTEX ที่นำจาก main มา reuse พร้อม navigation, module adapters, scoped API clients, theme และ metadata ทั้งนี้ source/backend ARTEX เดิมยังเป็น reference และไม่ถูกลบ
- `pipeline/scopesentry/frontend/`: embedding entry, router/base-path, API/static-path และ theme adapter ที่จำเป็น หรือ patch ที่ถูกติดตามใน unified frontend ไม่ rewrite scan/plugin/business logic ของ backend
- `pipeline/unified-web/src/modules/observer/`: presentation ที่รักษา state schema, summary, alerts และ timeline ของ Observer; ไม่เปลี่ยน `summarize-watch.py` model/prompt/regex/interval/state retention
- `pipeline/unified-gateway/` และ Dockerfile ที่เกี่ยวข้อง: route/stream/auth-boundary adapters สำหรับบริการเดิม โดยไม่รวม credential หรือฐานข้อมูล
- `pipeline/Dockerfile.qwen-code`: เปลี่ยนจาก npm-installed runtime เป็น build จาก supplied source แต่คง runtime tools, reporting/evidence/workspace mounts และฟีเจอร์ที่ใช้อยู่
- `pipeline/qwen-code/entrypoint.sh`: เปลี่ยนเฉพาะ bootstrap/asset path ที่ source build จำเป็นต้องใช้ คง settings, agents, skills, system prompt และ LAN capability เดิม หาก LAN compiled-chunk patch เดิมใช้กับ source ใหม่ไม่ได้ ต้องเสนอ compatibility patch ให้อนุมัติเฉพาะก่อน ไม่ถอดออกเงียบ ๆ
- `pipeline/docker-compose.yml`, `pipeline/docker-compose.mac.yml`: เพิ่ม frontend/gateway service และการ route ที่ต้องใช้ คง backend services, scanner, volumes, model/MCP ports และ operational features ไม่เปลี่ยน image version หรือ network exposure โดยไม่ถาม
- `pipeline/mac/start.command`: หลังอนุมัติจะเปลี่ยนเฉพาะการเปิด browser ให้เปิดเว็บกลางครั้งเดียว แทนหลายแท็บ โดยคงการ start โมเดล/stack/observer เดิม ไม่เปลี่ยนคำสั่ง start/stop process
- เอกสารและ focused regression tests สำหรับ integration ที่เพิ่ม ไม่แก้ข้อมูลจริงหรือยิงเป้าหมายจริงในการทดสอบ

ไฟล์ Go/backend business logic, `control_plane.py`, model/MCP/agent/skill policy, scanner/plugin logic, ฐานข้อมูล, `.env` ที่มี secrets และเครื่องมือ/PoC เดิมไม่อยู่ในขอบเขตแก้โดยอัตโนมัติ พบปัญหาได้และรายงานได้ แต่ไม่แก้เอง

## การคงฟีเจอร์ที่เป็นจุดเสี่ยง

Qwen ต้องคง full standalone pages, workspace/multi-host, session/source/search/archive/split, composer/approvals/Plan, agents/plugins/skills/MCP/extensions, channels/Live, schedules/PR watches/workflows/goals, settings/files/terminal/review/preview/artifacts/notifications และ capability gates ตาม source ไม่เปิดฟีเจอร์ที่เดิมไม่ได้เปิดใช้งานเพื่อให้รายการดูครบ

ARTEX ต้องคงแชตเดิมและทุกหน้า พร้อม task detail ทั้งสิบเอ็ดแท็บ ได้แก่ Overview, Sessions, Broadcast, Graph, Coverage Graph, Assets, Findings, Intercept, Credentials, Retests และ Report รวมทั้ง quality gate/evidence/retest, traffic/MITM/extension, admin settings, ScopeSentry Sync และ RSI/lessons ที่มีอยู่

ScopeSentry ต้องคง full UI: dashboard, asset categories ทั้งสิบสี่รวม map, projects/detail, tasks/schedules/templates, plugins/market/update, nodes, POCs/fingerprints/sensitive rules, dictionaries/export/download, configurations/notifications/dedup/API keys และ MCP ไม่ใช้ Asset Sync มาแทน

Observer ต้องคง EN/TH summaries, online/updated state, credential/critical alerts, English timeline, process-local state, bounds/regex/dedup และ polling intervals เดิม ส่วน control-plane lifecycle/log/toggle ที่มีอยู่ต้องไม่ถูกลบหรือเปลี่ยน แต่การเพิ่มปุ่มใหม่ใน Observer จะไม่ทำโดยไม่ขออนุมัติ

## ข้อจำกัดที่ต้องไม่ซ่อน

ผู้ใช้เลือก supplied Qwen source แล้ว จึงใช้ ZIP นี้เป็นฐาน ไม่ถามให้เลือกใหม่เพียงเพราะเลข version ต่ำกว่า ZIP SHA-256 คือ `b04da5816f80f03d9101d3e843723c03ebdff9f4504d016b75b1fa05aa58db27` และ manifest ระบุ `0.27.1`; pipeline เดิมติดตั้ง npm `0.27.2` ต้องตรวจ compatibility กับของเดิม หากพบฟีเจอร์เดิมไม่มีใน supplied source จะหยุดเสนอวิธีรักษาและถามก่อน ไม่ลบฟีเจอร์หรืออ้างว่า parity แล้ว

ScopeSentry มี editable frontend source ใน main แต่ compose ใช้ server/scanner images `latest` ยังไม่ทราบ actual image digest และความตรงกันกับ source metadata ที่ระบุ server `1.9.4`/scan `1.9.1` ไม่ pin, pull หรือเปลี่ยน image เอง และไม่รับรอง runtime parity จาก source เพียงอย่างเดียว

ยังไม่ได้ตรวจ live database/configured credentials, enabled plugins/agents/tools, model output, CA/extension/browser permissions หรือ runtime capability จริง Source ที่มีฟีเจอร์ไม่ได้พิสูจน์ว่าฟีเจอร์นั้นเปิดใช้ได้ในระบบปัจจุบัน ไม่อ้างว่าทดสอบแล้ว

การแก้ source กับการ install/build/test เป็นคนละขอบเขตที่ผู้ใช้เลือกอนุมัติได้ การทดสอบที่ขอได้ในขั้นนี้จำกัด dependency/build/typecheck และ mocked regression tests ใน worktree/sandbox แยก ไม่ใช้ข้อมูลหรือระบบจริง ไม่เรียกโมเดลเสียค่าใช้จ่าย ไม่ scan/pentest ไม่ install system toolchains และไม่มี Docker stack startup, commit/push หรือ deployment

## สิ่งที่ต้องอนุมัติก่อนเริ่ม

ขออนุมัติแนวทางและขอบเขตไฟล์ข้างต้น: frontend/document/navigation/theme กลาง, lossless module adapters, same-origin transport gateway ที่คง auth/data/backend boundaries, source-built Qwen, และ browser launcher ที่เปิดเว็บกลางครั้งเดียว

ข้อกำหนดที่ไม่เปลี่ยนคือเก็บฟีเจอร์ทั้งสี่ครบ และห้ามปิด telemetry/updater/LAN, ลบ scripts/tools/plugins, เปลี่ยน model/MCP/agent/approval/scan policy, รวม credential/database หรือแก้ business logic นอกขอบเขตโดยไม่ถามใหม่ หากพบว่าจำเป็นต้องเปลี่ยนส่วนเหล่านี้ งานส่วนนั้นจะรอการตัดสินใจ ไม่ถือว่าได้รับอนุญาตตามแผนนี้

หลังอนุมัติจึงสร้าง worktree และ TODO ของผลลัพธ์ที่ต้องส่งมอบ ฟีเจอร์ที่ยังเชื่อมไม่ครบหรือยังยืนยัน parity ไม่ได้จะถูกระบุเป็นงานค้าง ไม่ตัดออกจากข้อกำหนดและไม่ประกาศว่าเว็บรวมเสร็จแล้ว
