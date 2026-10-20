#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx_to_contentjson.py — แปลงรายงาน TLP:AMBER (.docx) → content JSON (best-effort)

ใช้ทำ "ฝั่ง output" ของ dataset สำหรับ finetune LoRA (content/style):
แกะโครงของรายงานเฉลยออกมาเป็น block JSON ตาม pipeline/reporting/report_contract.md
แล้วคน review/แก้ให้เป๊ะ (extractor เป็น heuristic — ของเริ่มต้น ไม่ใช่ของสำเร็จ)

⚠️ รันบนเครื่องคุณเอง (local) กับไฟล์ TLP:AMBER ของจริง — ไม่ต้องอัปขึ้น cloud
   สคริปต์ตัดรูป/ฟอนต์ที่ฝังทิ้ง เก็บแค่ข้อความ+โครง → output เป็น text เล็ก

ใช้:
    python3 docx_to_contentjson.py report.docx -o out.json
    python3 docx_to_contentjson.py gold_dir/ -O json_dir/        # ทั้งโฟลเดอร์
"""
import sys, os, re, json, zipfile, argparse
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _ln(el):
    return el.tag.split("}")[-1]


def _text(p):
    return "".join(t.text or "" for t in p.iter(W + "t"))


def _is_bold(p):
    # ถือว่า bold ถ้ามี <w:b> ใน run ใด ๆ (หัวข้อในเฉลยทำด้วย bold ทั้งย่อหน้า)
    for b in p.iter(W + "b"):
        v = b.get(W + "val")
        if v not in ("0", "false"):
            return True
    return False


def _has_drawing(el):
    return el.find(".//" + W + "drawing") is not None or el.find(".//" + W + "pict") is not None


def _table_rows(tbl):
    rows = []
    for tr in tbl.findall(W + "tr"):
        row = []
        for tc in tr.findall(W + "tc"):
            cell = " ".join(_text(p).strip() for p in tc.findall(W + "p")).strip()
            row.append(cell)
        if any(c for c in row):
            rows.append(row)
    return rows


CAPTION_RE = re.compile(r"^\s*รูปภาพที่\s*[\d\s\-]+\s*")
HEADING_RE = re.compile(r"^\s*\d+\.\s+\S")          # 1. 2. 3.
SUB_RE = re.compile(r"^\s*\d+\.\d+\s")              # 2.1 2.2


def convert(path):
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml")
    root = ET.fromstring(doc)
    body = root.find(W + "body")

    blocks = []
    titles = []
    date = None
    pending_fig = False          # เพิ่งเจอรูป กำลังรอ caption
    seen_body = False            # ผ่านส่วนหัว (title/date) แล้วหรือยัง

    for child in list(body):
        tag = _ln(child)

        if tag == "tbl":
            if _has_drawing(child):                    # ตารางกรอบรูป = figure
                pending_fig = True
                continue
            rows = _table_rows(child)
            if rows:
                blocks.append({"type": "table", "rows": rows})
                seen_body = True
            continue

        if tag != "p":
            continue

        if _has_drawing(child):                        # รูปแทรกในย่อหน้า
            pending_fig = True
            continue

        txt = _text(child).strip()
        if not txt:
            continue

        # caption ของรูปที่เพิ่งเจอ
        if pending_fig and CAPTION_RE.match(txt):
            cap = CAPTION_RE.sub("", txt).strip()
            blocks.append({"type": "figure", "image": "<ใส่ชื่อไฟล์รูป>", "caption": cap})
            pending_fig = False
            seen_body = True
            continue
        if pending_fig:            # มีรูปแต่ caption หาย → placeholder
            blocks.append({"type": "placeholder", "caption": txt if CAPTION_RE.match(txt) else ""})
            pending_fig = False

        bold = _is_bold(child)

        # ส่วนหัว: title (bold) + date ก่อนเข้าหัวข้อ "1."
        if not seen_body and not HEADING_RE.match(txt):
            if txt.startswith("วันที่") or "จัดทำรายงาน" in txt:
                date = txt
                continue
            if bold:
                titles.append(txt)
                continue

        if HEADING_RE.match(txt) and bold:
            blocks.append({"type": "heading", "text": txt})
            seen_body = True
        elif SUB_RE.match(txt) and bold:
            blocks.append({"type": "sub", "text": txt})
            seen_body = True
        elif txt.startswith("สถานะ:"):
            blocks.append({"type": "status", "value": txt.replace("สถานะ:", "").strip()})
        elif txt.startswith("หมายเหตุ"):
            blocks.append({"type": "note", "text": "<ใส่เนื้อหาหมายเหตุ — ดูย่อหน้าถัดไปในเฉลย>"})
        elif re.match(r"^\s*[•●]\s*", txt):
            blocks.append({"type": "bullet", "text": re.sub(r"^\s*[•●]\s*", "", txt)})
        elif re.match(r"^\s*[-–]\s+", txt):
            blocks.append({"type": "dash", "text": re.sub(r"^\s*[-–]\s+", "", txt)})
        elif txt.startswith("ฝ่ายปฏิบัติการ"):
            blocks.append({"type": "signature", "text_seen": txt})   # คน review ใส่ date ให้
        else:
            blocks.append({"type": "plain", "text": txt})
            seen_body = True

    return {"titles": titles, "date": date, "blocks": blocks}


def main():
    ap = argparse.ArgumentParser(description="แปลง TLP:AMBER .docx → content JSON (best-effort)")
    ap.add_argument("src", help="ไฟล์ .docx หรือโฟลเดอร์ที่มี .docx หลายไฟล์")
    ap.add_argument("-o", "--out", help="ไฟล์ JSON ออก (กรณี src เป็นไฟล์เดียว)")
    ap.add_argument("-O", "--outdir", help="โฟลเดอร์ JSON ออก (กรณี src เป็นโฟลเดอร์)")
    a = ap.parse_args()

    if os.path.isdir(a.src):
        outdir = a.outdir or (a.src.rstrip("/") + "_json")
        os.makedirs(outdir, exist_ok=True)
        n = 0
        for fn in sorted(os.listdir(a.src)):
            if fn.lower().endswith(".docx") and not fn.startswith("~$"):
                spec = convert(os.path.join(a.src, fn))
                out = os.path.join(outdir, os.path.splitext(fn)[0] + ".json")
                json.dump(spec, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"✓ {fn} → {out}  ({len(spec['blocks'])} blocks)")
                n += 1
        print(f"เสร็จ {n} ไฟล์ → {outdir}  (คน review/แก้ให้เป๊ะก่อนใช้เทรน)")
    else:
        spec = convert(a.src)
        out = a.out or (os.path.splitext(a.src)[0] + ".json")
        json.dump(spec, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"✓ {out}  ({len(spec['blocks'])} blocks, {len(spec['titles'])} titles)")


if __name__ == "__main__":
    main()
