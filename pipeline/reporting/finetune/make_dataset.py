#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_dataset.py — content JSON (จาก gold) → คู่ training (input → output) สำหรับ SFT

แก้ปัญหา "ไม่มี findings มาเป็น input": เรา *derive input จาก gold เอง*
  input  = โครงข้อเท็จจริง (เป้าหมาย + ตาราง IOC/hash + รายการรูป + ประเด็นที่พบ)
  output = content JSON เต็ม (ร้อยแก้ว + โครง + อ้างรูป + status/note/signature)
โมเดลเรียน "เอาข้อเท็จจริง → เรียบเรียงเป็นรายงานราชการ" ซึ่งตรงกับตอน inference
(Tiel วิเคราะห์เสร็จก็มี IOC/hash/finding/รูป อยู่แล้ว เหลือแค่แปลงเป็นรายงาน)

ออก chat jsonl (sharegpt-ish) + decompose 1 ฉบับ → หลายตัวอย่าง (ทั้งฉบับ + ราย section)

ใช้:
    python3 make_dataset.py gold_json/ -o train.jsonl          # ทั้งโฟลเดอร์
    python3 make_dataset.py one.json --show                    # โชว์ตัวอย่าง 1 คู่ (ไม่เขียนไฟล์)
"""
import sys, os, re, json, argparse

SYS = ("คุณคือผู้ช่วยเขียนรายงาน TLP:AMBER ของ สกมช. "
       "รับ 'โครงข้อเท็จจริง' แล้วเรียบเรียงเป็น content JSON ตามฟอร์แมตบ้าน "
       "(ภาษาราชการสมบูรณ์, โครงหัวข้อ 1/2/3, อ้างรูปในเนื้อก่อน 'ตามรูปภาพที่ N', "
       "ปิดบังค่าอ่อนไหว, ปิดท้ายด้วย status/หมายเหตุ/ลงชื่อ). ตอบเป็น JSON เท่านั้น")

HEADING = re.compile(r"^\s*\d+\.\s")
SUB = re.compile(r"^\s*\d+\.\d")


def _render_table(rows):
    if not rows:
        return ""
    head = rows[0]
    out = ["  [ตาราง] " + " | ".join(head)]
    for r in rows[1:]:
        out.append("   - " + " : ".join(c for c in r if c))
    return "\n".join(out)


def build_brief(spec, blocks=None):
    """สร้าง 'โครงข้อเท็จจริง' (input) จาก block ที่เป็นข้อเท็จจริงล้วน"""
    blocks = spec["blocks"] if blocks is None else blocks
    titles = spec.get("titles", [])
    rtype = "OSINT/เว็บหลอกลวง" if any("OSINT" in t or "เว็บไซต์" in t for t in titles) else "วิเคราะห์มัลแวร์"
    lines = [f"ชนิดรายงาน: {rtype}"]
    if len(titles) > 1:
        lines.append(f"เป้าหมาย: {titles[1]}")

    tables = [b for b in blocks if b["type"] == "table"]
    figs = [b for b in blocks if b["type"] in ("figure", "placeholder")]
    bullets = [b for b in blocks if b["type"] in ("bullet", "dash")]
    status = [b for b in blocks if b["type"] == "status"]

    if tables:
        lines.append("\nข้อเท็จจริง (ตาราง):")
        for t in tables:
            lines.append(_render_table(t["rows"]))
    if figs:
        lines.append("\nหลักฐาน (รูป ตามลำดับ):")
        for i, f in enumerate(figs, 1):
            lines.append(f"  - รูป {i}: {f.get('caption','')}")
    if bullets:
        lines.append("\nประเด็น/ข้อค้นพบ:")
        for b in bullets:
            lines.append(f"  - {b['text']}")
    if status:
        lines.append("\nสถานะการทดสอบ: " + status[0]["value"])
    return "\n".join(lines)


def to_example(spec, blocks=None):
    """คู่ (system, user=brief, assistant=content JSON)"""
    sub = spec if blocks is None else {"titles": spec.get("titles", []),
                                       "date": spec.get("date"), "blocks": blocks}
    return {"messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": build_brief(spec, blocks)},
        {"role": "assistant", "content": json.dumps(sub, ensure_ascii=False)},
    ]}


def split_sections(spec):
    """แบ่ง blocks เป็นช่วงตามหัวข้อหลัก (1. / 2. / 3.) → ใช้ decompose"""
    secs, cur = [], []
    for b in spec["blocks"]:
        if b["type"] == "heading" and cur:
            secs.append(cur); cur = [b]
        else:
            cur.append(b)
    if cur:
        secs.append(cur)
    return secs


def examples_from(spec):
    out = [to_example(spec)]                       # ทั้งฉบับ (1)
    for sec in split_sections(spec):               # ราย section (หลายตัว)
        # เอาเฉพาะ section ที่มีเนื้อ (มี table/figure/bullet อย่างน้อย 1 = พอมี facts ให้ derive)
        if any(b["type"] in ("table", "figure", "bullet", "dash", "status") for b in sec):
            out.append(to_example(spec, sec))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="ไฟล์ .json หรือโฟลเดอร์ของ content JSON")
    ap.add_argument("-o", "--out", help="ไฟล์ jsonl ออก")
    ap.add_argument("--show", action="store_true", help="โชว์ตัวอย่าง 1 คู่ แล้วจบ (ไม่เขียนไฟล์)")
    a = ap.parse_args()

    files = []
    if os.path.isdir(a.src):
        files = [os.path.join(a.src, f) for f in sorted(os.listdir(a.src)) if f.endswith(".json")]
    else:
        files = [a.src]

    all_ex = []
    for f in files:
        spec = json.load(open(f, encoding="utf-8"))
        all_ex.extend(examples_from(spec))

    if a.show:
        ex = all_ex[0]
        print("=" * 70, "\nINPUT (user) = โครงข้อเท็จจริงที่ derive จาก gold:\n", "=" * 70)
        print(ex["messages"][1]["content"])
        print("\n" + "=" * 70, "\nOUTPUT (assistant) = content JSON เต็ม (ตัดให้ดู 600 ตัว):\n", "=" * 70)
        print(ex["messages"][2]["content"][:600], "...")
        print(f"\n[รวมได้ {len(all_ex)} ตัวอย่างจาก {len(files)} ไฟล์]")
        return

    out = a.out or "train.jsonl"
    with open(out, "w", encoding="utf-8") as w:
        for ex in all_ex:
            w.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"✓ {out}: {len(all_ex)} ตัวอย่าง จาก {len(files)} gold")


if __name__ == "__main__":
    main()
