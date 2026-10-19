# Prompt tuning: Propose–Probe–Compose (PPC)

แนวทาง **ปรับ `pipeline/cyber-operator.system.md` ด้วยมือ** อย่างมีระบบ ถอดวิธีมาจาก
Propose–Probe–Compose ของ Harness² (google-research/harness2) แต่ตัดส่วนอันตรายทิ้ง:
**คนเป็นผู้ compose เสมอ ไม่ให้ Tiel แก้ prompt/guardrails ตัวเอง** (ดู "กฎความปลอดภัย"
ด้านล่าง — กฎนี้ถูกบังคับไว้ใน system prompt ด้วยแล้ว section "Prompt & guardrail changes")

หลักคิดเดียวที่ต้องจำ: **ตัดสินจาก "การเปลี่ยนนี้ทำให้พฤติกรรมดีขึ้นจริงไหม" (behavioral
contrast) ไม่ใช่ "คำอธิบายฟังดูดีไหม"** — prompt ที่อ่านแล้วสวยไม่ได้แปลว่า Tiel ทำได้ดีขึ้น

---

## แก่นของวิธี

ลูป 3 เฟสบน **task เดียวกัน** โดย **ไม่ต้องมีเฉลย (ground-truth)**:

| เฟส | ทำอะไร |
|---|---|
| **Propose** | เสนอ "edit" ของ prompt หลายตัว — ทั้ง *general* (ใช้ได้ทุกงาน) และ *domain-specific* (เฉพาะงานนี้) |
| **Probe**   | เอา candidate ไปรันจริงบน **task เดิม โมเดลเดิม env เดิม** แล้วดู**พฤติกรรมที่ต่างกัน** |
| **Compose** | รวมเฉพาะ edit ที่พิสูจน์แล้วว่าช่วยจริง → เป็น `cyber-operator.system.md` ตัวใหม่ |

ลูปที่ 2 (persistence): จดบทเรียนที่มีหลักฐานลง `pipeline/prompt-lessons.md` ให้งานหน้า
เริ่มแบบรู้แล้ว — แต่ทุกงานยังเริ่มจาก base เดิม ไม่ auto-สืบทอดทุกการแก้

---

## 8 ส่วนที่แก้ได้ → แมปกับ stack เรา

| ส่วนของ Harness² | ในระบบเราคือ |
|---|---|
| system prompt | `pipeline/cyber-operator.system.md` (ตัวหลัก) |
| guardrails    | กฎความปลอดภัย: ห้ามส่งหลักฐาน/มัลแวร์ขึ้น cloud, passive OSINT only |
| tool guidance | section REA / HexStrike / vision / pcap / WPA |
| subagents     | `ask_exploit_specialist`, vision, summarizer |
| skills        | section "Threat verdict", "Read images (vision)" |
| scripts       | `pipeline/mac/ask-vision.sh`, `pipeline/mac/scan-doc.sh` |
| memory        | `pipeline/prompt-lessons.md` (คลังบทเรียน) + MCP memory |
| plugins       | MCP servers ที่ต่อ (HexStrike router, REA) |

---

## Playbook ทีละสเต็ป (manual, Console-aware)

> ⚠️ Console ของ HarnessRouter: การ paste prompt ใหม่ **มีผลเฉพาะ session ใหม่**
> session ที่รันอยู่ยังถือ prompt เดิม → ทุก Probe ต้อง **เปิด session ใหม่** หลัง paste

**สเต็ป 0 — ตรึง "task ทดสอบ" ให้นิ่ง**
เลือกเคสตัวแทน 1 อันแล้วอย่าเปลี่ยนระหว่างรอบ เช่น
"วิเคราะห์ `/work/targets/<ไฟล์>` แล้วสรุป threat verdict" — ไฟล์ input คงที่ (วางใน
`pipeline/rea-targets/` → เห็นที่ `/work/targets`), คำสั่งคงที่, โมเดลเดิม (Tiel)
*ต้องนิ่งเพราะเราวัด "ความต่างจากการแก้ prompt" ไม่ใช่ความต่างจากการเปลี่ยนโจทย์*

**สเต็ป 1 — Baseline**
รัน task นี้ด้วย prompt ปัจจุบัน **3 session** (Tiel ไม่ deterministic) จดผลตามเกณฑ์ข้อถัดไป

**สเต็ป 2 — Propose** (คุณเป็นคนเสนอ ไม่ใช่ Tiel)
ทำ candidate 2–4 แบบ **แยกคนละสำเนาไฟล์** (`cyber-operator.A.md`, `.B.md` …)
- 1–2 แบบ *general* (เช่น "ก่อนสรุปต้องขึ้น verdict + ความมั่นใจเป็นหัวข้อแรกเสมอ")
- 1–2 แบบ *domain* (เช่น "APK: เช็ก signer + endpoint ก่อน แล้วค่อย decompile")
- **แก้ทีละเรื่องต่อสำเนา** ไม่งั้นแยกไม่ออกว่าอันไหนช่วย

**สเต็ป 3 — Probe**
paste ทีละสำเนาเข้า Console → เปิด session ใหม่ → รัน task เดิม 2–3 รอบ → จดด้วยเกณฑ์ข้อถัดไป

**สเต็ป 4 — Compose** (คุณรวมเอง)
หยิบเฉพาะ edit ที่ชนะตามพฤติกรรมจริงมารวมเป็น `cyber-operator.system.md` ตัวใหม่ →
รันยืนยันอีก 2 รอบว่าดีกว่า baseline จริง (กัน regression) → commit

---

## Behavioral contrast — เกณฑ์ตัดสินแบบไม่มีเฉลย

Tiel ไม่มีเฉลย → ตัดสินจากสัญญาณที่ **สังเกตได้จริงจากการรัน** (ให้ +1 / 0 / −1 ต่อรอบ แล้วเทียบ):

- ✅ **ไปถึง verdict ชัดไหม** (เป้าหลัก — อย่าหยุดแค่ list facts)
- ✅ **เรียก tool ถูกตัว/ลำดับถูกไหม** (เช่น `.exe` ที่เป็น PyInstaller ต้อง pyinstxtractor-ng → pycdc, ไม่ใช่ Ghidra)
- ✅ **เคารพ guardrail ไหม** (ไม่พยายามส่งไฟล์/หลักฐานขึ้น `nim`/cloud)
- ✅ **เลี่ยง anti-pattern ไหม** (ไม่คาย output >10MB ผ่าน harness, ไม่แนบ log ยาวจนชน TTFT)
- ✅ **จำนวน step กว่าจะเสร็จ** (น้อยลง = prompt ชี้ทางดีขึ้น)
- ❌ อย่าตัดสินจาก "prompt อ่านแล้วดูดี" — ต้องเห็นพฤติกรรมเปลี่ยนในรอบจริง

**กฎชี้ขาด:** candidate ชนะเมื่อ *ส่วนใหญ่ของรอบดีขึ้นในสัญญาณที่เล็ง โดยไม่ทำสัญญาณอื่นแย่ลง*
ถ้าดีด้านหนึ่งแต่พังอีกด้าน = ไม่รับ

---

## Parallel vs Sequential — ใช้เมื่อไหร่

- **Parallel (สำรวจกว้าง):** มีหลายไอเดีย ไม่รู้อันไหนดี → เสนอหลาย candidate พร้อมกัน เทียบรอบเดียว
  เหมาะตอน **เริ่มปรับส่วนใหม่** (เช่นเพิ่ม section ใหม่ครั้งแรก)
- **Sequential (ขุดลึก):** รู้ทิศแล้ว อยากขัดให้คม → แก้ทีละสเต็ป เอาผลรอบก่อนมาต่อยอด
  เหมาะตอน **จูน section ที่มีอยู่** (เช่นทำ threat verdict ให้คมขึ้นเรื่อยๆ)

---

## กฎความปลอดภัยตอนจูน (ต่างจาก Harness² ตรงนี้)

1. **คนเป็นผู้ compose เสมอ** — ห้ามให้ Tiel แก้ `cyber-operator.system.md` ตัวเอง
   (บังคับไว้ใน system prompt แล้ว: section "Prompt & guardrail changes")
2. **guardrails แตะได้เฉพาะให้เข้มขึ้น** — candidate ไหนทำให้กฎ "ห้ามส่ง cloud / passive-only"
   อ่อนลง = ตัดทิ้งทันที ไม่ว่าคะแนนอื่นดีแค่ไหน
3. **task ทดสอบใช้ไฟล์ที่ควบคุมได้** — อย่าเอาเคสหลักฐานจริงที่ยังเปิดอยู่มา probe ซ้ำๆ
   (เสี่ยง + สิ้นเปลือง); ใช้ตัวอย่างที่คุณถือสิทธิ์วิเคราะห์
4. **version control ทีละ compose** — commit แต่ละรอบแยก จะ rollback ง่ายถ้า regression

---

## อ้างอิง

- Harness² README: https://github.com/google-research/harness2
- docs/EXPERIMENTS.md: https://github.com/google-research/harness2/blob/main/docs/EXPERIMENTS.md
- คลังบทเรียนของเรา: `pipeline/prompt-lessons.md`
