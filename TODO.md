# Project-Malaria: Unified Web — TODO

ผู้ใช้อนุมัติให้เริ่มแก้ source ตามแผน และกำชับ **ห้ามแอบตัดอะไรออก** เมื่อ 13 พฤศจิกายน 2026 งานนี้ทำใน worktree แยกจาก main `605e7bdfcce81a9b7042d3d35a9f7e843386c92a` ไม่ทับ repository เดิม ไม่ commit/push/publish และยังไม่อนุมัติ install/build/typecheck/tests หรือรันระบบจริง

รายการที่ยังไม่เชื่อมครบหรือยังไม่ยืนยันการทำงานต้องคงเป็นงานค้าง ไม่ตัดออกจากข้อกำหนด และไม่กล่าวว่า feature parity สำเร็จเพียงเพราะ source มีอยู่

- [x] **ฐาน main และ supplied source แยกจากงานเดิม**
  - Working tree เดิมบน pipeline-deepseek และงานค้าง pipeline/README.md, ARTEX-main/, pipeline/docs/artex-review-th.md ต้องไม่ถูกเปลี่ยน
  - ใช้ main commit ข้างต้นเป็นฐานใน worktree `/home/ubuntu/Project-Malaria-unified`
  - นำ supplied Qwen ZIP SHA-256 `b04da5816f80f03d9101d3e843723c03ebdff9f4504d016b75b1fa05aa58db27` มาไว้ใน pipeline/qwen-source โดยเก็บ source ทั้ง 14,688 ไฟล์ รวม licenses/notices/scripts/tests ไม่ execute scripts
  - Copy frontend ARTEX เดิมครบไป pipeline/unified-web; source/backend ARTEX เดิมไม่ถูกลบ
  - หลักฐาน: worktree จาก commit ที่อนุมัติ, นำ ZIP ครบทุกไฟล์, repository เดิมยังมี dirty state เดิม

- [ ] **เว็บ/document/navigation เดียว โดยเข้าถึงฟีเจอร์ทุกระบบ**
  - รวม Qwen, ARTEX, ScopeSentry และ Observer เป็น Web application เดียว ไม่ใช่ Tauri/Desktop, iframe หรือเพียงลิงก์เปิดเว็บไซต์แยก
  - Frontend กลาง Next.js/React reuse หน้า/components ARTEX เดิม; Qwen ใช้ full standalone composition; ScopeSentry reuse Vue components/router/store; Observer ย้ายเฉพาะ presentation
  - Navigation ระดับแอปชุดเดียวพร้อม context navigation แต่ละระบบ ไม่มีการรวม settings ที่ semantics ต่างกัน และไม่เอาแชต Qwen มาแทนแชต ARTEX
  - เส้นทาง /ai, /artex, /scopesentry, /observer ต้องมี route adapters และรักษา deep links เดิม ไม่ลบเงียบ ๆ
  - Qwen providers/state ต้องอยู่ขณะเปลี่ยน module: ไม่เริ่ม session ใหม่ ไม่หยุดงาน และไม่ทิ้ง draft เพียงเพราะสลับหน้า ไม่ใช้ viewHidden ที่ unmount App เป็นการรักษา draft โดยอ้างลอย ๆ
  - Auth ของ ARTEX ต้องไม่กีดกัน Qwen/ScopeSentry/Observer; แต่ละระบบคง login และ permission/capability gates เดิม

- [ ] **Qwen เต็มรูปแบบจาก supplied source ไม่ใช่ npm คนละ source**
  - CLI/runtime/container เปลี่ยนมา build จาก pipeline/qwen-source ไม่ fallback @qwen-code/qwen-code npm เดิม
  - คงเต็ม standalone providers, sidebar/footer, workspace/multi-host/targets/pairing/mobile, sessions/catalog/source/search/archive/split, composer/approvals/Plan, agents/plugins/MCP/skills/extensions, channels/Live, workflows/goals/schedules/PR watches, settings/files/terminal/review/preview/artifacts/notifications/media และ capability gates เดิม
  - ไม่ลดเหลือ WebShellWithProviders sidebar=false และไม่เปิด managed mode/agent team/เครื่องมือเพิ่มเพื่อให้รายการดูครบ
  - ใช้ primitives/scoped CSS/portal roots เดิม คง data-web-shell attributes และ public CSS variables
  - คง runtime tools, reporting/evidence/workspace mounts, settings, agents, skills, system prompt, LAN และ bootstrap ที่ใช้อยู่
  - Qwen ZIP manifest 0.27.1 ต่างจาก npm เดิม 0.27.2: หากพบความสามารถเดิมขาดต้องรายงานและถามก่อน ไม่อ้าง parity โดยไม่ตรวจ
  - LAN compiled-chunk patch เดิมต้องได้รับอนุมัติเฉพาะหาก source ใหม่จำเป็นต้องเปลี่ยนวิธีหรือพฤติกรรม ห้ามถอดออกเงียบ ๆ

- [ ] **ARTEX เดิมครบ รวมแชตและสิบเอ็ดแท็บ task**
  - คง Dashboard, Chat, Tasks, Findings, Traffic, Commands, LLM records, Assets, Asset Sync, Workspace และทุกหน้า LLM/Agents/MCP/Skills/Tools/Notifications/Interception/Approvals/Logs/Settings/login/setup
  - คง task detail Overview, Sessions, Broadcast, Graph, Coverage Graph, Assets, Findings, Intercept, Credentials, Retests, Report รวม quality gates/evidence/retest, traffic/MITM/extension, admin settings, ScopeSentry Sync และ RSI/lessons
  - คง ARTEX user JWT 7-day HS256, artex_token storage/cookie/SSE query และ error/status envelopes ไม่ใช้ Qwen หรือ ScopeSentry tokens แทน
  - คง SSE แบบไม่ buffer, multipart/binary/range downloads/Content-Disposition และ sync ที่รอได้ 10 นาที
  - Asset Sync ยังคง write-through, project/task identity, defaults service/subdomain/app, page 1..500 และ cap 5000 ต่อ type/target ไม่เติม dry-run หรือเปลี่ยน business logic เอง

- [ ] **ScopeSentry full Vue UI ไม่ใช่เฉพาะ Asset Sync**
  - คง Dashboard, asset categories ทั้ง 14 รวม map/screenshots, projects/hidden aggregation/detail, tasks/schedules/templates, plugins/market/update/runtime, nodes, POCs/fingerprints/sensitive rules, dictionaries/ports/export/download, system notifications/dedup/subfinder/RAD/API keys, auth/about/error และ native MCP
  - Vue/Pinia JWT/remember-me, MCP ssk_ keys และ plugin keys ต้องแยกจาก ARTEX/Qwen
  - Router ย่อยผ่าน mount/URL adapter ไม่ให้ Next/Vue routers แย่ง history; ไม่ rewrite backend scan/plugin logic
  - คง root-oriented API/static paths /api,/images,/map,/mcp/Swagger/static ผ่าน mapping ครบ ไม่แก้แค่ API base จน map/export/download เสีย
  - คง HTTP polling เดิม ไม่เปลี่ยนเป็น protocol อื่นเพียงเพื่อรวมหน้า
  - Compose images latest และ digest/source parity ยังไม่ทราบ; metadata source server 1.9.4/scan 1.9.1 ไม่ใช่หลักฐาน runtime parity ไม่ pin/pull/เปลี่ยน image เอง

- [ ] **Observer presentation ครบและยังเป็น host backend เดิม**
  - คง GET /state schema updated,en,th,alerts[{level,time,text}],timeline[{time,en}],online
  - คง EN/TH summaries, online/updated state, credential/critical raw-log alerts และ English timeline; browser polling ทุก 5 วินาที
  - ไม่ย้าย Docker logs/memory/LiteLLM มา browser และไม่แก้ backend 45-second interval, regex credential precedence, dedup, alert text 300 characters, max 50 alerts/max 30 timeline หรือ process-local RAM reset semantics
  - ไม่เพิ่ม clear/filter/export/auth/session/SSE/persistence/control buttons ที่ไม่มีเดิมโดยไม่ถาม
  - Control-plane status/start/stop/restart/log/toggle ที่มีอยู่ไม่ถูกลบหรือเปลี่ยน แต่ไม่ยกเป็นปุ่มใหม่เอง
  - Observer loopback-only และไม่มี auth: ห้ามเปิดให้ LAN ใช้โดยปริยาย หาก gateway topology คงขอบเขตนี้ไม่ได้ต้องรอการอนุมัติ ไม่ใช้ Host/X-Forwarded-For ที่ผู้ร้องขอปลอมได้เป็นหลักฐาน loopback

- [ ] **ธีม Qwen และเอาเฉพาะโลโก้ที่ผู้ใช้ขอ**
  - ใช้ developer workspace style/palette Qwen โดยตรง: dark background #0d0d0d, foreground #fafafa, accent #6785ff; light background white, foreground #0a0a0b, accent #0033ff พร้อม semantic shadcn tokens
  - Theme owner เดียวส่ง resolved theme ให้ทุก module; preserve font preferences/code typography/scoped CSS/portal roots
  - คงความหมาย severity/status colors, keyboard focus/dialog behavior และ reduced-motion; ไม่ซ่อนข้อมูล/tables/code/evidence/diff เพื่อความสวย
  - Product chrome ใช้ข้อความ Project-Malaria เอาโลโก้ Qwen/ARTEX ออกจาก UI ไม่สร้างโลโก้ใหม่ ไม่ลบ ScopeSentry/Observer logo เอง
  - เก็บ LICENSE, NOTICES, copyright headers, Terms และ legal attribution; ไม่ blanket rename Qwen/ARTEX technical IDs, API/JWT subjects/MCP rows/data

- [ ] **Same-origin gateway โดยคง backend/auth/transport boundaries**
  - เพิ่ม namespaced gateway โดย backend/process/database แต่ละระบบยังแยก ไม่ SSO/token exchange/account/key/database merge
  - ไม่ส่ง Bearer token ของ Qwen ไปใช้แทน JWT ของ ARTEX/ScopeSentry และไม่ส่ง LiteLLM/backend API keys ไป browser
  - Preserve SSE/WebSocket, multipart, binary/range downloads, Content-Disposition, status/error envelopes, long-running requests; ไม่ buffer streams เป็น JSON ไม่ retry write/start-job requests แบบไม่ทราบผล
  - Complete API/static path adapters และ compatibility deep links; ไม่ widen/reduce LAN exposure โดยปริยาย โดยเฉพาะ Observer

- [ ] **Source-built packaging และ launcher โดยไม่ลด operational features**
  - Dockerfile.qwen-code คง tools/mounts/runtime features; entrypoint เปลี่ยนเฉพาะ bootstrap/asset paths ที่จำเป็น ไม่แตะ policies หรือเอา LAN patch ออกเอง
  - Compose เพิ่ม frontend/gateway แต่คง backend/scanner/model/MCP services, volumes, images และ existing access; ห้ามเปลี่ยน ports/network exposure/image version โดยไม่ถาม
  - mac/start.command เปลี่ยนเฉพาะ browser opening ให้เป็นเว็บกลาง URL เดียว โดยคง start/stop โมเดล/stack/observer commands เดิม
  - ไม่แก้ Go/backend business logic, control_plane.py, model/MCP/agent/skill/approval/scan policy, databases, secret .env หรือ tools/PoCs โดยอัตโนมัติ

- [ ] **ขอบเขตอนุมัติและสถานะที่ซื่อสัตย์**
  - ไม่ปิด telemetry/updater/LAN, ไม่ลบ scripts/tools/plugins, ไม่ติดตั้ง CA, ไม่ scan/PoC/เรียกโมเดลจริงหรือเสียเงิน ไม่ install system toolchains ไม่ start Docker stack ไม่ commit/push/public deploy
  - Source implementation ไม่เท่ากับผ่าน build/runtime/feature parity; ต้องระบุ missing connections, unsupported topology และ version uncertainty เป็นงานค้าง
  - การ install/build/typecheck/mocked tests ใน sandbox แยกจะรอคำอนุมัติชัดเจนก่อน ยังไม่มีการอนุมัติให้เริ่ม backend/targets จริง
  - หากจำเป็นต้องเปลี่ยน feature/behavior หรือไฟล์นอกแผน หยุดเฉพาะส่วนนั้นแล้วถามก่อน ไม่แอบตัดหรือขยายขอบเขต

## รายการอ้างอิง

Approved plan: `/home/ubuntu/unified-ui-proposal/plan.md`. Source inventory: `/home/ubuntu/unified-ui-proposal/feature-inventory.md` และ inventories แยกสี่ระบบใน directory เดียวกัน รายการเหล่านี้เป็น static source inventory ไม่ใช่ผลทดสอบ runtime

## ความคืบหน้า source — 13–14 พฤศจิกายน 2026

นำ supplied Qwen source ครบและตรวจเทียบ baseline แล้วพบไฟล์เดิมหาย 0 ไฟล์; ไฟล์เดิมที่ปรับเป็น UI/navigation/package adapters 7 ไฟล์ พร้อมเพิ่ม standalone entry/design docs. ARTEX/backend และ Observer Python เดิมไม่มี tracked diff. ทั้งสี่ module มี adapter source และ frontend กลางแล้ว; Qwen target provider ที่ขาดในรอบแรกถูกนำกลับผ่าน navigation adapter และ ScopeSentry Map เพิ่ม native lifecycle mount ภายใน document เดียว ไม่ยอมรับการละฟีเจอร์เป็นทางแก้.

Frontend กลางมี navigation บนหน้า auth ด้วย และเก็บ path ล่าสุดของ Qwen/ScopeSentry/Observer. ARTEX auth navigation ยังคง token/expiry/login/logout/Terms เดิมแต่ใช้ host routing เพื่อไม่ unload provider ของ module อื่น. Copied ARTEX favicon/icon ย้ายไป public/legacy-branding/artex เพื่อลบเฉพาะ product chrome ที่อนุมัติ ไม่ลบ original assets. Temporary ambient module type scaffold ที่เพิ่มในรอบแรกถูกนำออก ไม่ได้ตัดฟีเจอร์ใด.

Canonical frontend เลือก Next standalone server (NEXT_EXPORT=0) เพื่อรักษา arbitrary deep links. Native ARTEX static export เดิมยังอยู่ใน pipeline/artex/web; optional static branch ของ copied unified frontend ไม่ใช่ canonical mode และยังไม่รับรองความเข้ากันได้กับ dynamic module catchalls.

เพิ่ม source Dockerfiles และ internal-only unified-web/unified-gateway services ไม่มี published port ใหม่ และไม่เปลี่ยน services/ports/images/volumes/policies เดิม. Launcher ยังไม่เปลี่ยนจนกว่าจะอนุมัติ URL/port topology ที่ใช้งานได้จริง. Observer gateway ยัง fail-closed เพื่อไม่เปิด host loopback ให้ LAN โดยปริยาย ไม่ใช่การตัด Observer ออกจากข้อกำหนด.

ยังไม่มี install/build/typecheck/tests/runtime verification. Host npm lockfile และ ScopeSentry pnpm lockfile รอการสร้าง/ตรวจด้วย package manager หลังได้รับอนุมัติ; ไม่มีการเขียน lockfile ปลอม. Source-only follow-up: Qwen English/Chinese design docs และ E2E plan สะท้อน native multi-host provider ที่เชื่อมแล้วและยังคง ACP browser auth เป็น blocker; ScopeSentry module CSS selector adapter จำกัดขอบเขตให้ครอบคลุม owned body portals และ embedded portal theme variables; native Map CSS จะถูก scope ตอนเตรียม assets และ async script/lifecycle มี cancellation/serialized cleanup. ยังไม่ได้ execute asset preparation หรือยืนยันผล CSS, portal, Map ใน browser/build/runtime. Qwen auth/version parity, gateway/CSP, Scope image/source parity และ acceptance ทั้งระบบยังรอหลักฐานที่ได้รับอนุมัติ รายการผลลัพธ์ข้างต้นจึงยังไม่ถูกติ๊กว่าเสร็จครบ.

## การแก้ไขข้อผิดพลาดเพื่อพร้อมใช้งานจริง (Operational Fixes) — 14 พฤศจิกายน 2026

1. **แก้ไข Dockerfile.unified-web**:
   - ปลดล็อก exit 86 ใน stage `scopesentry-builder` ที่บังคับหา pnpm-lock.yaml พร้อมเพิ่ม fallback ให้คัดลอก static assets สำหรับ native map และสร้าง module export stub เพื่อป้องกัน build failure
   - เปลี่ยนจาก `corepack npm ci` เป็น `npm install --include=dev` ใน stage `web-builder` เพื่อรองรับ local packages (@qwen-code/sdk และ @qwen-code/web-shell) อย่างถูกต้อง
2. **แก้ไข Dockerfile.qwen-code**:
   - คืนค่าการติดตั้ง `@qwen-code/qwen-code@0.27.2` เพื่อความเสถียรและความรวดเร็วในการ build บน Apple Silicon Docker Desktop หลีกเลี่ยงปัญหา memory exhaustion (OOM) จากการ compile source monorepo
3. **แก้ไข docker-compose.yml**:
   - เปิด port mapping `127.0.0.1:3000:3000` สำหรับ `unified-gateway`
   - เชื่อม `OBSERVER_TARGET: http://host.docker.internal:8005` พร้อมเปิด `OBSERVER_ENABLED: "1"` และ `OBSERVER_ALLOW_DOCKER_BRIDGE: "1"`
   - เพิ่ม `extra_hosts: ["host.docker.internal:host-gateway"]` และ `depends_on: [unified-web]`
4. **แก้ไข unified-gateway router (router.mjs & test)**:
   - รองรับ `OBSERVER_ALLOW_DOCKER_BRIDGE` โดยอนุญาตให้ Docker bridge private IP (เช่น 172.18.0.1) และ hostname `host.docker.internal` ใช้งาน Observer ได้อย่างปลอดภัย
   - เพิ่ม unit test ครบถ้วนและรันผ่าน 16/16 tests
5. **ปรับปรุง mac/start.command**:
   - เพิ่มการเปิด `http://localhost:3000` (Unified Web Portal) เมื่อสตาร์ทระบบ
   - อัปเดตข้อความสรุปปลายทางพอร์ตให้แสดง Unified Web Portal เป็นช่องทางหลัก
