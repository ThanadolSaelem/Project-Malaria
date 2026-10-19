#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assemble.py — ประกอบรายงาน TLP:AMBER (.docx ฟอร์แมตบ้าน สกมช.) จาก "เนื้อหา JSON"

แนวคิด: โมเดล (Tiel) ผลิต *เนื้อหา* เป็น JSON + เซฟรูปหลักฐานลง pipeline/evidence/
สคริปต์นี้เอา JSON มาประกอบเป็น .docx โดย *format มาจาก template.docx* ทั้งหมด
(โมเดลไม่แตะ font/ขอบ/heading/ตาราง เลย — กันพลาดแบบที่เคยได้ Times New Roman)

ใช้:  python3 assemble.py content.json -o /path/report.docx
สคีมา JSON ดู report_contract.md
"""
import sys, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_report import Report, CONTENT_W   # engine ฟอร์แมตบ้าน (จาก ncsa-tlp-report skill)

HERE = os.path.dirname(os.path.abspath(__file__))


def build(spec_path, out_path, template=None, evidence_dir=None):
    spec = json.load(open(spec_path, encoding="utf-8"))
    template = template or spec.get("template") or os.path.join(HERE, "template.docx")
    evidence_dir = evidence_dir or spec.get("evidence_dir") or os.path.join(HERE, "..", "evidence")
    r = Report(template, fig_numbering=spec.get("fig_numbering", "continuous"))
    warnings = []

    for t in spec.get("titles", []):
        r.title(t)
    if spec.get("date"):
        r.date(spec["date"])

    for i, b in enumerate(spec.get("blocks", [])):
        ty = b.get("type")
        try:
            if ty == "heading":
                r.heading(b["text"], new_page=b.get("new_page", False))
            elif ty == "sub":
                r.sub(b["text"], new_page=b.get("new_page", False))
            elif ty == "plain":
                r.plain(b["text"], tab=b.get("tab", True))
            elif ty == "bullet":
                r.bullet(b["text"])
            elif ty == "dash":
                r.dash(b["text"])
            elif ty == "numbered":
                r.numbered(b["n"], b["text"])
            elif ty == "lead":
                r.lead(b["label"], b["text"])
            elif ty == "status":
                r.status(b["value"])
            elif ty == "note":
                r.note(b["text"])
            elif ty == "signature":
                r.signature(b.get("date", ""),
                            unit=b.get("unit", "ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ"))
            elif ty == "page_break":
                r.page_break()
            elif ty == "spacer":
                r.spacer()
            elif ty == "code":
                r.code_block(b["lines"], sz=b.get("sz", 18))
            elif ty == "table":
                rows = b["rows"]
                widths = b.get("widths")
                if not widths:                       # แบ่งคอลัมน์เท่า ๆ กันให้ครบ 9071 twips
                    ncol = max(len(x) for x in rows)
                    base = CONTENT_W // ncol
                    widths = [base] * (ncol - 1) + [CONTENT_W - base * (ncol - 1)]
                r.table(rows, widths, header=b.get("header", True))
            elif ty == "figure":
                img = b["image"]
                if not os.path.isabs(img):
                    img = os.path.join(evidence_dir, img)
                if os.path.exists(img):
                    r.figure(img, b.get("caption", ""),
                             width_cm=b.get("width_cm"), border=b.get("border", True))
                else:                                # ไม่พบรูป → ใส่กรอบ placeholder ไม่ให้ fail
                    warnings.append(f"block {i}: ไม่พบรูป {img} → ใส่ placeholder แทน")
                    r.placeholder(b.get("caption", ""))
            elif ty == "placeholder":
                r.placeholder(b.get("caption", ""))
            else:
                warnings.append(f"block {i}: ไม่รู้จัก type '{ty}' — ข้าม")
        except KeyError as e:
            warnings.append(f"block {i} ({ty}): ขาด field {e} — ข้าม")

    r.save(out_path)
    return out_path, warnings


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ประกอบ TLP:AMBER .docx จาก JSON content spec")
    ap.add_argument("spec", help="ไฟล์ JSON เนื้อหา (ดู report_contract.md)")
    ap.add_argument("-o", "--out", required=True, help="path ไฟล์ .docx ที่จะเขียนออก")
    ap.add_argument("--template", help="override path ของ template.docx")
    ap.add_argument("--evidence-dir", help="override โฟลเดอร์รูปหลักฐาน")
    a = ap.parse_args()
    out, warns = build(a.spec, a.out, a.template, a.evidence_dir)
    for w in warns:
        print("WARN:", w)
    print("OK:", out)
