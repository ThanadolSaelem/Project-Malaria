"""
discover.py — offline pipeline สร้างกฎ parsing จาก log ตัวอย่าง

รันเฉพาะตอนออกแบบกฎเท่านั้น ห้ามเรียกใน production path (ใช้ gensim/sklearn
ซึ่งช้าและมี state) ตามลำดับ:

  1. word2vec + KMeans จัดกลุ่มหยาบ (K สูงเกินจริง 2-3 เท่า — แตกเกินแก้ได้
     ยุบเกินแก้ไม่ได้)
  2. ในแต่ละ (cluster, ความยาว) เทียบ token ทีละตำแหน่ง
  3. ตัดสินแต่ละตำแหน่งตามลำดับความสำคัญนี้เท่านั้น (ห้ามสลับลำดับ):
       a) sensitive word conflict (sensitive.py)     -> บังคับแยก เสมอ
       b) เป็นตัวเลขล้วน -> classify_numeric() (numeric.py, churn rule)
            ENUM       -> แยก (เซ็ตปิดเล็ก ปลอดภัยพอจะ enumerate)
            REVIEW     -> ส่งคนตัดสิน (โซนสีเทา เช่น firewall rule id)
            IDENTIFIER -> mask <NUM>
       c) ข้อความทั่วไป -> cardinality
            1                  -> literal
            >= card_threshold  -> mask ตามชนิดที่เดาได้ (<IP>/<BLK>/<UUID>/<PATH>/<STR>)
            2..threshold-1     -> ส่งคนตัดสิน
  4. คืนกฎที่ชัดเจนแล้ว (rules) แยกจากรายการที่ต้องให้คนตอบ (review_items)
     พร้อมรายการ auto-split ที่ระบบตัดสินเอง (ให้คน sanity-check เพิ่มเติมได้)

สมมติฐานสำคัญ: `lines` ต้องเรียงตามเวลาจริงของ log (ไฟล์ log ปกติเรียงแบบนี้
อยู่แล้ว) เพราะ classify_numeric() แบ่งครึ่งแรก/หลังจากตำแหน่งในลิสต์ ไม่ได้
อ่าน timestamp field โดยตรง — ถ้า lines ถูก shuffle มาก่อนผลลัพธ์ churn จะผิด
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from gensim.models import Word2Vec
from sklearn.cluster import KMeans

from .numeric import classify_numeric
from .sensitive import contains_sensitive_conflict, split_marker

IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
NUM_RE = re.compile(r"^-?\d+$")


@dataclass
class DiscoverConfig:
    expected_templates: int = 30
    k_multiplier: float = 2.5
    card_threshold: int = 5
    numeric_distinct_threshold: int = 60
    min_cluster_size: int = 10
    w2v_vector_size: int = 50
    w2v_window: int = 5
    w2v_min_count: int = 2
    seed: int = 42


@dataclass
class Decision:
    position: int
    kind: str
    detail: str
    reason: str = ""
    sample_values: List[str] = field(default_factory=list)


def _infer_kind(values: List[str]) -> str:
    if all(IP_RE.match(v) for v in values):
        return "<IP>"
    if all(UUID_RE.match(v) for v in values):
        return "<UUID>"
    if all(v.startswith("blk_") for v in values):
        return "<BLK>"
    if all("/" in v for v in values):
        return "<PATH>"
    return "<STR>"


def _decide_position(values: List[str], cfg: DiscoverConfig) -> Decision:
    unique_values = sorted(set(values))

    if len(unique_values) == 1:
        return Decision(position=-1, kind="literal", detail=unique_values[0], reason="single_value")

    if contains_sensitive_conflict(unique_values):
        return Decision(position=-1, kind="split", detail=split_marker(unique_values),
                         reason="sensitive_word", sample_values=unique_values[:10])

    if all(NUM_RE.match(v) for v in unique_values):
        mid = len(values) // 2
        first_half, second_half = values[:mid], values[mid:]
        verdict = classify_numeric(
            first_half, second_half,
            distinct_threshold=cfg.numeric_distinct_threshold,
        )
        if verdict == "ENUM":
            return Decision(position=-1, kind="split", detail=split_marker(unique_values),
                             reason="numeric_enum", sample_values=unique_values[:10])
        if verdict == "REVIEW":
            return Decision(position=-1, kind="review", detail="numeric-gray-zone",
                             reason="numeric_gray_zone", sample_values=unique_values[:10])
        return Decision(position=-1, kind="mask", detail="<NUM>", reason="numeric_identifier", sample_values=unique_values[:5])

    if len(unique_values) >= cfg.card_threshold:
        return Decision(position=-1, kind="mask", detail=_infer_kind(unique_values),
                         reason="high_cardinality", sample_values=unique_values[:5])

    return Decision(position=-1, kind="review", detail="text-ambiguous",
                     reason="text_ambiguous", sample_values=unique_values)


def _merge_by_key(items: List[Dict], key: str) -> List[Dict]:
    merged: Dict[str, Dict] = {}
    for item in items:
        k = item[key]
        if k in merged:
            merged[k]["count"] += item["count"]
        else:
            merged[k] = dict(item)
    return sorted(merged.values(), key=lambda x: -x["count"])


def _extract_auto_splits(decisions: List[Decision]) -> List[Dict]:
    splits = []
    for d in decisions:
        if d.kind == "split":
            splits.append({
                "position": d.position,
                "reason": d.reason,
                "split_values": d.sample_values,
            })
    return splits


def discover(lines: List[str], cfg: Optional[DiscoverConfig] = None) -> Dict:
    """
    คืน {"rules": [...], "review_items": [...], "auto_splits": [...], "cluster_report": [...]}

    rules           พร้อมเอาไปเรียก rules.save_rules() ได้ทันที (ไม่มีตำแหน่ง
                      กำกวมเหลืออยู่) แต่พร้อม field auto_split_positions สำหรับ sanity-check
    review_items    ต้องให้คนตัดสินก่อน แล้วเรียก rules.resolve_review_item()
                      ทีละอันแล้ว append เข้า rules เอง
    auto_splits     สรุปทุกตำแหน่งที่ระบบตัดสิน split เอง (sensitive word / numeric enum)
                      ให้คนตัดสินใจว่าเห็นด้วยไหม — ไม่ใช่ review item ที่ต้องตอบ
    cluster_report  สรุปทุก cluster ไว้ดูภาพรวม (รวมทั้งที่เป็น rule และ review)
    """
    cfg = cfg or DiscoverConfig()
    sents = [l.split() for l in lines]

    model = Word2Vec(
        sents, vector_size=cfg.w2v_vector_size, window=cfg.w2v_window,
        min_count=cfg.w2v_min_count, sg=1, epochs=5, seed=cfg.seed, workers=1,
    )
    vecs = np.zeros((len(sents), cfg.w2v_vector_size), dtype=np.float32)
    for i, s in enumerate(sents):
        tok_vecs = [model.wv[w] for w in s if w in model.wv]
        if tok_vecs:
            vecs[i] = np.mean(tok_vecs, axis=0)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / np.where(norms == 0, 1, norms)

    k = max(2, min(int(cfg.expected_templates * cfg.k_multiplier), len(sents)))
    clusters = KMeans(n_clusters=k, n_init=4, random_state=cfg.seed).fit_predict(vecs)

    groups: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i, s in enumerate(sents):
        groups[(int(clusters[i]), len(s))].append(i)

    rules: List[Dict] = []
    review_items: List[Dict] = []
    auto_splits: List[Dict] = []
    cluster_report: List[Dict] = []

    for (cluster_id, length), idxs in groups.items():
        if len(idxs) < cfg.min_cluster_size:
            continue

        decisions: List[Decision] = []
        has_review = False
        for p in range(length):
            values_at_p = [sents[i][p] for i in idxs]
            d = _decide_position(values_at_p, cfg)
            d.position = p
            decisions.append(d)
            if d.kind == "review":
                has_review = True

        template = " ".join(d.detail for d in decisions)
        auto_split_positions = _extract_auto_splits(decisions)

        cluster_report.append({
            "cluster_id": cluster_id, "length": length, "count": len(idxs),
            "template_preview": template,
            "example_line": lines[idxs[0]].rstrip("\n"),
            "has_review": has_review,
            "auto_split_positions": auto_split_positions,
        })

        if has_review:
            review_items.append({
                "cluster_id": cluster_id, "length": length, "count": len(idxs),
                "template_draft": template,
                "example_line": lines[idxs[0]].rstrip("\n"),
                "ambiguous_positions": [
                    {"position": d.position, "reason": d.detail, "sample_values": d.sample_values}
                    for d in decisions if d.kind == "review"
                ],
                "auto_split_positions": auto_split_positions,
            })
        else:
            rules.append({
                "cluster_id": cluster_id, "length": length, "count": len(idxs),
                "template": template,
                "auto_split_positions": auto_split_positions,
            })

    rules = _merge_by_key(rules, key="template")
    review_items = _merge_by_key(review_items, key="template_draft")
    review_items.sort(key=lambda r: -r["count"])

    all_auto_splits = []
    for item in rules + review_items:
        for sp in item.get("auto_split_positions", []):
            all_auto_splits.append({
                "cluster_id": item["cluster_id"],
                "length": item["length"],
                "count": item["count"],
                "template": item.get("template") or item.get("template_draft"),
                **sp,
            })

    # merge ด้วย (template, position) ไม่ใช่ template อย่างเดียว — ถ้า template
    # เดียวมี auto-split หลายตำแหน่ง (เช่น "connection {allowed|denied} status
    # {failed|success}") การ merge ด้วย template อย่างเดียวจะรวมสองตำแหน่งเข้า
    # เป็นรายการเดียว ทำให้ count บวกซ้ำเป็น 2 เท่าและตำแหน่งที่สองหายไปจาก
    # รายงานเงียบ ๆ (พบจากการทดสอบตรง ๆ กับเคสที่มี sensitive word 2 ตำแหน่ง)
    for entry in all_auto_splits:
        entry["_merge_key"] = f"{entry['template']}\x1f{entry['position']}"
    auto_splits = _merge_by_key(all_auto_splits, key="_merge_key")
    for entry in auto_splits:
        entry.pop("_merge_key", None)
    auto_splits.sort(key=lambda x: -x["count"])

    return {"rules": rules, "review_items": review_items, "auto_splits": auto_splits, "cluster_report": cluster_report}