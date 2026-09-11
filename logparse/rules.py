"""
rules.py — โหลด/บันทึก/ใช้กฎจาก rules.yaml (ผลลัพธ์ของ discover.py หลังคนรีวิวแล้ว)

ไฟล์นี้ต้อง production-safe: ห้าม import gensim/sklearn เด็ดขาด (เทียบกับ
discover.py ที่ใช้ ML ได้เต็มที่เพราะรันแค่ตอนออกแบบกฎ) apply_rules() คือ
ฟังก์ชันเดียวที่ถูกเรียกตอน production จริง ต้อง deterministic 100%
"""

from typing import Dict, List, Optional

import yaml


def save_rules(rules: List[Dict], filepath: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.safe_dump({"rules": rules}, f, allow_unicode=True, sort_keys=False)


def load_rules(filepath: str) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("rules", [])


def save_review(review_items: List[Dict], filepath: str) -> None:
    """เขียน review.md อ่านง่าย เรียงตาม volume (มาก -> น้อย) ให้คนดูของสำคัญก่อน"""
    lines = [
        "# รายการรอรีวิว\n\n",
        f"ทั้งหมด {len(review_items)} รายการ เรียงตามจำนวนบรรทัดจากมากไปน้อย\n",
    ]
    for i, item in enumerate(review_items, 1):
        lines.append(
            f"\n## {i}. cluster {item['cluster_id']} "
            f"(length={item['length']}, count={item['count']})\n\n"
        )
        lines.append(f"ตัวอย่างจริง: `{item['example_line']}`\n\n")
        lines.append(f"Template ร่าง: `{item['template_draft']}`\n\n")
        for amb in item["ambiguous_positions"]:
            lines.append(
                f"- ตำแหน่ง {amb['position']}: {amb['reason']} — ค่าที่พบ: "
                f"{', '.join(amb['sample_values'])}\n"
            )
        # แสดง auto-split ที่ระบบตัดสินเองใน cluster นี้ (เพื่อ context)
        auto_splits = item.get("auto_split_positions", [])
        if auto_splits:
            lines.append("\n--- ตำแหน่งที่ระบบตัดสิน split เอง (ให้ sanity-check เพิ่มเติม) ---\n")
            for sp in auto_splits:
                lines.append(
                    f"- ตำแหน่ง {sp['position']}: {sp['reason']} — ค่า: "
                    f"{', '.join(sp['split_values'])}\n"
                )
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


def save_auto_splits(auto_splits: List[Dict], filepath: str) -> None:
    """เขียน auto_splits.md สำหรับ sanity-check แยกจาก review.md"""
    lines = [
        "# Auto-split positions (ตัดสินโดยระบบอัตโนมัติ)\n\n",
        f"ทั้งหมด {len(auto_splits)} รูปแบบ template เรียงตาม volume\n",
        "รายการเหล่านี้คือตำแหน่งที่ระบบตัดสิน split เอง (sensitive word หรือ numeric enum)\n"
        "ไม่ต้องตอบคำถาม — แต่อาจต้องการ sanity-check ว่าตรงกับความคาดหวังไหม\n\n",
    ]
    for i, item in enumerate(auto_splits, 1):
        lines.append(
            f"\n## {i}. cluster {item['cluster_id']} "
            f"(length={item['length']}, count={item['count']})\n\n"
        )
        lines.append(f"Template: `{item['template']}`\n\n")
        lines.append(
            f"- ตำแหน่ง {item['position']}: {item['reason']} — ค่าที่พบ: "
            f"{', '.join(item['split_values'])}\n"
        )
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


def resolve_review_item(item: Dict, position_decisions: Dict[int, str]) -> Dict:
    """
    หลังคนตัดสินใจตำแหน่งกำกวมแล้ว (ดู review.md) เรียกฟังก์ชันนี้เพื่อประกอบ
    เป็น rule พร้อมใช้ — ยังไม่บันทึกไฟล์ ต้องเอาผลไป append เข้า rules list
    แล้ว save_rules() เอง

    position_decisions: {position: decision_string} เช่น
      {3: "<STR>"}              -> mask ด้วยชนิดนี้
      {3: "{nginx|sshd|cron}"}  -> แยกเป็นคนละ log key (ใช้ค่าจาก sample_values)
    """
    parts = item["template_draft"].split()
    for amb in item["ambiguous_positions"]:
        p = amb["position"]
        if p not in position_decisions:
            raise ValueError(
                f"ยังไม่มีคำตอบสำหรับตำแหน่ง {p} ใน cluster {item['cluster_id']}"
            )
        parts[p] = position_decisions[p]
    return {
        "cluster_id": item["cluster_id"],
        "length": item["length"],
        "count": item["count"],
        "template": " ".join(parts),
        "auto_split_positions": item.get("auto_split_positions", []),
    }


def apply_rules(line_tokens: List[str], rules: List[Dict]) -> Optional[str]:
    """
    ใช้ตอน production — จับคู่ token กับ rule ที่ length เท่ากัน แล้วคืน
    normalized template string (ยัง "ไม่ใช่" log key ID สุดท้าย ตัว hash ทำใน
    vocab.py) คืน None ถ้าไม่มี rule ไหน match เลย (ทางไป <UNK>)

    สำคัญมาก: ตำแหน่งที่เป็น split marker {a|b|c} จะถูกแทนด้วย "ค่าจริงที่พบ"
    ในบรรทัดนั้น ไม่ใช่ marker เดิม — ถ้าคืน marker เดิมตรง ๆ "allowed" กับ
    "denied" จะ hash ได้ log key เดียวกัน ซึ่งเป็นบั๊กเดียวกับที่ sensitive.py
    ถูกออกแบบมาป้องกัน ส่วนตำแหน่งที่เป็น mask <NUM>/<IP>/... จะคง label
    เดิมไว้ (ไม่ใส่ค่าจริง) เพราะนั่นคือจุดประสงค์ของการ mask

    การจับคู่เป็นแบบ exact-length + exact-literal เท่านั้น ไม่มี fuzzy
    matching ใด ๆ — สอดคล้องกับหลักการ "production ต้อง deterministic"
    """
    length = len(line_tokens)
    for rule in rules:
        if rule.get("length") != length:
            continue
        rule_tokens = rule["template"].split()
        if len(rule_tokens) != length:
            continue

        out: List[str] = []
        ok = True
        for lt, rt in zip(line_tokens, rule_tokens):
            if rt.startswith("<") and rt.endswith(">"):
                out.append(rt)
            elif rt.startswith("{") and rt.endswith("}"):
                options = rt[1:-1].split("|")
                if lt not in options:
                    ok = False
                    break
                out.append(lt)
            else:
                if lt != rt:
                    ok = False
                    break
                out.append(rt)

        if ok:
            return " ".join(out)

    return None