# pipeline-deepseek — รัน stack เราบน deepseek-harness

ชั้น config ที่ทำให้ **deepseek-harness** (ตัวใหม่ แทน HarnessRouter) ขับ **Tiel ผ่าน LiteLLM**
และต่อ **MCP tools เดิม** (HexStrike/REA) ได้ โดย **ใช้ stack เดิมทั้งหมดร่วมกัน** (compose/llama/litellm
ไม่ต้องแก้) — รันขนานกับ HarnessRouter ได้ (deepseek-harness UI = `:3080`, ของเดิม = `:3000`)

> branch นี้ = main (pipeline เต็ม) + โฟลเดอร์ `pipeline/deepseek-harness/` นี้
> deploy: `git checkout pipeline-deepseek && git pull` แล้วรัน `deploy.sh`

## ⚠️ ความจริงที่ต้องรู้ก่อน (อ่านก่อนคาดหวัง)

- **deepseek-harness = developer preview** — ทีมมันเตือนเองว่า breaking changes รัวๆ
- ผม (ผู้สร้างไฟล์นี้) **รันทดสอบไม่ได้** ในที่ที่สร้าง → config นี้อิง **เอกสารทางการเท่าที่อ่านได้**
  บางจุดจึง **"ต้อง verify ตอนรันจริง"** (ดูตารางล่าง) — **ไม่ใช่ pull แล้วเดินเป๊ะ 100%**
- **ความลื่น = ตัว Tiel (โมเดล) ไม่ใช่ harness** — deepseek-harness จูนมาเพื่อโมเดล DeepSeek
  อาจลื่นกับ DeepSeek มากกว่า Tiel (local 35B) → อย่าคาดหวังว่าเปลี่ยน harness แล้ว Tiel = Claude

## สถานะแต่ละส่วน

| ส่วน | สถานะ | อ้างอิง |
|---|---|---|
| provider ชี้ LiteLLM (`baseURL/api/compat`) | ✅ **confirmed** รูปแบบ | docs/user/guide/providers.md ของ deepseek-harness |
| พอร์ต host (LiteLLM 4000 / HexStrike 8001 / REA 8007) | ✅ confirmed | docker-compose.yml ของเรา |
| MCP รองรับ | ✅ confirmed (มี `dsh-mcp-client`) | packages/mcp/mcp-client |
| โครง key ของบล็อก MCP ใน `cordis.patch.yml` | ⚠️ **verify** | อิงรูปแบบ — เช็ก key เป๊ะกับ dsh-mcp-client |
| วิธี wire system prompt เข้า harness | ⚠️ **verify** | ยังไม่รู้กลไกเป๊ะ (plugin prompt/agent หรือ Settings) |
| server ไม่มี key ใช้ได้ไหม / compat flags จำเป็นไหม | ⚠️ **verify** | ทดสอบจริง |

## Deploy (ขั้นตอนที่คุณทำ)

```bash
# 1. ดึง branch นี้
git fetch origin && git checkout pipeline-deepseek && git pull origin pipeline-deepseek

# 2. ตั้ง env (ครั้งเดียว)
cp pipeline/deepseek-harness/.env.example pipeline/deepseek-harness/.env
#   แก้ค่าถ้าต้องการ (ดีฟอลต์ LITELLM_KEY=sk-local, DSH_HOME=~/.dsh)
source pipeline/deepseek-harness/.env

# 3. ให้ llama.cpp (Tiel:8090, vision:8093) รันอยู่ก่อน
#    ถ้ายัง: รัน pipeline/mac/start.command

# 4. deploy (ยก docker stack + วาง config + launch harness)
bash pipeline/deepseek-harness/deploy.sh
#    → เปิด http://127.0.0.1:3080
```

`deploy.sh` ทำให้: ยก docker stack (`--profile full`), วาง `cordis.patch.yml` → `$DSH_HOME/profiles/web/`,
วางสำเนา system prompt → `$DSH_HOME/`, แล้ว `npx @deepseek-ai/dsh web`

## สิ่งที่ต้องทำเองในหน้า harness (จุด verify)

1. **เลือกโมเดล `cybermodel`** (= Tiel) ใน UI หลัง provider โหลด (ดู Settings → Models)
2. **wire system prompt**: เอาเนื้อหา `$DSH_HOME/cyber-operator.system.md` ใส่เป็น system prompt/agent
   instructions ของ harness (กลไกเป๊ะยัง verify — น่าจะอยู่ใน Settings หรือ prompt plugin)
3. **เช็ก MCP** ว่า tool `mcp__hexstrike__*` / `mcp__rea__*` โผล่ไหม — ถ้าไม่โผล่ แก้ key ในบล็อก MCP
   ของ `cordis.patch.yml` ให้ตรง dsh-mcp-client (แล้วไฟล์ hot-reload)

## Troubleshooting

- **โมเดลตอบ error ทั้งที่ url/key ถูก** → `compat.supportsDeveloperRole: false` + `maxTokensField: max_tokens`
  ใส่ไว้ให้แล้ว (llama.cpp มักต้องการ) ถ้ายังพัง ดู log ว่า field ไหนไม่รองรับ
- **llama ไม่ขึ้น** → LiteLLM:4000 ตอบ error; รัน `pipeline/mac/start.command`
- **REA ไม่มา** → ต้อง `--profile full` (deploy.sh ใส่ให้แล้ว) + rebuild ถ้าเพิ่ง pull

## ต้อง clone deepseek-harness ไหม? — ไม่ต้อง (เป็น dependency)

ตัว harness **ไม่ได้ถูก vendor เข้า repo นี้** (มันคือ codebase 22,000+ commit — เอาเข้ามา =
บวม + drift ตามเขาไม่ทัน) มันเป็น **dependency** เหมือน docker/llama.cpp — เหมือน HarnessRouter
เดิมก็เป็น app แยกที่ไม่ได้อยู่ใน repo คุณ **4 ไฟล์ในโฟลเดอร์นี้ = ชั้น config เชื่อมเท่านั้น**

deploy.sh มี 2 โหมด:
| โหมด | ได้ harness มายังไง | ใช้เมื่อ |
|---|---|---|
| **`npx` (ดีฟอลต์)** | `npx @deepseek-ai/dsh` ดึง package จาก npm | ปกติ — **ไม่ต้อง clone** |
| **`source`** | `git clone` + `pnpm build` เอง (`DSH_MODE=source bash deploy.sh`) | อยาก bleeding-edge ของ dev-preview / แก้โค้ด harness เอง |

```bash
# ปกติ (npx, ไม่ clone):
bash pipeline/deepseek-harness/deploy.sh
# จาก source (clone + build):
DSH_MODE=source bash pipeline/deepseek-harness/deploy.sh
```
> dev-preview → package npm อาจตามโค้ด repo ไม่ทัน ถ้าเจอบั๊กที่ repo แก้แล้วแต่ npm ยังไม่อัป ใช้โหมด `source`

## ทำไมไม่ copy ทั้ง pipeline เป็น repo ใหม่
เลือก "branch แยก" → pipeline เต็มมากับ main อยู่แล้ว ชั้น deepseek แค่เสริมบน branch นี้
→ **ไม่มี 2 สำเนา drift กัน** อยากได้อะไรใหม่จาก main ก็ `git merge origin/main` เข้า branch นี้ได้
