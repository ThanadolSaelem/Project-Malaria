import warnings
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence

import pandas as pd

# ============================================================
# Track A: วัดคุณภาพ parser (purity / fragmentation / coverage)
# ของเดิมไม่มีฟังก์ชันกลุ่มนี้เลย ทั้งที่เป็น metric หลักที่ใช้ตัดสินคุณภาพ
# กฎตลอดขั้นตอนออกแบบ — ห้ามวัดด้วยจำนวน template อย่างเดียว
# ============================================================

def purity(pred_ids: Sequence[str], true_labels: Sequence[str]) -> float:
    """
    สัดส่วนที่ pred cluster หนึ่งมี true label ปนกันน้อยที่สุด (ยิ่งใกล้ 1 ยิ่งดี)
    ต่ำ = มีการยุบ template ผิด (เช่น allow กับ deny ไปอยู่ log key เดียวกัน)
    นี่คืออันตรายที่มองไม่เห็นตรง ๆ ต้องวัดคู่กับ fragmentation เสมอ
    """
    groups: Dict[str, Counter] = defaultdict(Counter)
    for pred, true in zip(pred_ids, true_labels):
        groups[pred][true] += 1
    correct = sum(c.most_common(1)[0][1] for c in groups.values())
    return correct / max(len(pred_ids), 1)


def fragmentation(pred_ids: Sequence[str], true_labels: Sequence[str]) -> float:
    """
    true label เดียวกัน กระจายไปกี่ pred cluster โดยเฉลี่ย (ยิ่งใกล้ 1 ยิ่งดี)
    สูง = เหตุการณ์เดียวกันถูกแยกเป็นหลาย log key โดยไม่จำเป็น — แก้ทีหลังได้
    (ต่างจาก purity ต่ำที่ข้อมูลอาจหายถาวรและมักไม่มีสัญญาณเตือน)
    """
    true_to_preds: Dict[str, set] = defaultdict(set)
    for pred, true in zip(pred_ids, true_labels):
        true_to_preds[true].add(pred)
    n_labels = max(len(true_to_preds), 1)
    return sum(len(v) for v in true_to_preds.values()) / n_labels


def coverage(pred_ids: Sequence[str], unk_id: str = "unk_00000000") -> float:
    """สัดส่วนบรรทัดที่ parser รู้จัก (ไม่ใช่ <UNK>)"""
    if not pred_ids:
        return 0.0
    known = sum(1 for p in pred_ids if p != unk_id)
    return known / len(pred_ids)


def detect_missed_masking(
    templates: Sequence[str],
    min_bucket_variants: int = 8,
    max_count_per_variant: int = 5,
) -> List[str]:
    """
    ตัวเตือนกฎที่ขาด: จัดกลุ่ม template ด้วย shape signature
    (W=คำ, D=ตัวเลข, X=ปนตัวเลข, S=อื่นๆ) ถ้า shape เดียวกันมี template
    ต่างกันเยอะและ count ต่ำทุกอัน = สัญญาณว่าลืม mask field ใดฟิลด์หนึ่ง
    (พบจริงตอนทดสอบ: ลืมกฎ mask ข้อเดียวทำให้ template พุ่งจาก 15 -> 318)
    """
    def shape(tpl: str) -> str:
        out = []
        for tok in tpl.split():
            if tok.isdigit():
                out.append("D")
            elif any(c.isdigit() for c in tok):
                out.append("X")
            elif tok.isalpha():
                out.append("W")
            else:
                out.append("S")
        return "".join(out)

    buckets: Dict[str, Counter] = defaultdict(Counter)
    for t in templates:
        buckets[shape(t)][t] += 1

    findings = []
    for shp, counter in buckets.items():
        if len(counter) >= min_bucket_variants and max(counter.values()) <= max_count_per_variant:
            findings.append(
                f"shape '{shp}': {len(counter)} template ต่างกัน count ต่ำทุกอัน "
                f"— น่าจะลืม mask field ตัวอย่าง: {list(counter)[:3]}"
            )
    return findings


# ============================================================
# Track B: alert budget (B2) / per-category tracking (B5)
# ============================================================

def generate_alert_budget_report(
    normal_scores: List[float],
    target_thresholds: List[float],
    daily_log_volume: int,
    labeled_anomaly_scores: Optional[List[float]] = None,
) -> None:
    """
    รายงานหลาย threshold ให้เลือกตาม budget แทนพ่นค่า F1 ตัวเดียว
    labeled_anomaly_scores: ใส่ถ้ามี D3 (ชุดที่มีเหตุการณ์จริงติด label) จะได้
    คอลัมน์ recall ด้วย — ถ้าไม่มี (กรณีส่วนใหญ่) recall จะโชว์ "-"
    threshold ต้องเลือกจาก normal_scores (validation ที่เป็น normal ล้วน)
    ไม่ใช่จากการไล่หา F1 สูงสุดบน labeled_anomaly_scores (P3 — test set leakage)
    """
    header = f"{'Threshold':<12} | {'FP Rate(%)':<11} | {'Alert/วัน(ประมาณ)':<18} | {'Recall(%)':<10}"
    print(header)
    print("-" * len(header))
    for th in target_thresholds:
        fp_count = sum(1 for s in normal_scores if s > th)
        fp_rate = fp_count / max(len(normal_scores), 1)
        est_alerts_per_day = int(fp_rate * daily_log_volume)

        if labeled_anomaly_scores:
            tp = sum(1 for s in labeled_anomaly_scores if s > th)
            recall_str = f"{tp / max(len(labeled_anomaly_scores), 1) * 100:.1f}"
        else:
            recall_str = "-"

        print(f"{th:<12.4f} | {fp_rate * 100:<11.4f} | {est_alerts_per_day:<18} | {recall_str:<10}")


def evaluate_per_category(
    evidence_logs: List[Dict],
    min_sample_size: int = 500,
) -> Optional[pd.DataFrame]:
    """
    ระดับ micro (log key / position) — top-g hit rate ต่อ category

    evidence_logs ตาม schema จาก B4:
      {"session_id","position","observed","category","top_g_predicted","rank"}
      rank เป็น None ถ้า observed ไม่อยู่ใน top_g_predicted เลย (ตำแหน่งที่
      "ผิดคาด") ดังนั้น hit = rank ไม่ใช่ None ไม่ต้องเทียบ threshold ซ้ำ
      เพราะ rank ที่บันทึกมาถูกกรองให้อยู่ใน top-g แล้วตั้งแต่ตอน detect

    หมายเหตุ: นี่คือ metric ระดับตำแหน่ง (micro) เท่านั้น ไม่ใช่ FP rate ระดับ
    sequence (macro) — ถ้าต้องการ FP/flag-rate ระดับ sequence ต่อ category
    ให้ใช้ evaluate_sequence_level() แทน เพราะต้องรู้เกณฑ์ threshold ของแต่ละ
    session ด้วย ไม่ใช่แค่นับ hit/miss รายตำแหน่ง
    """
    df = pd.DataFrame(evidence_logs)
    if df.empty:
        warnings.warn("ไม่มีข้อมูล evidence log สำหรับประเมินผล")
        return None

    df["hit"] = df["rank"].notna()
    summary = df.groupby("category").agg(
        n_obs=("observed", "count"),
        top_g_hits=("hit", "sum"),
    ).reset_index()
    summary["top_g_hit_rate"] = summary["top_g_hits"] / summary["n_obs"] * 100

    header = f"{'หมวดหมู่':<20} | {'จำนวน':<10} | {'Top-g Hit Rate':<15}"
    print(header)
    print("-" * len(header))
    for _, row in summary.iterrows():
        cat, n = row["category"], row["n_obs"]
        if n < min_sample_size:
            print(f"{cat:<20} | {n:<10} | ข้อมูลไม่พอประเมิน (< {min_sample_size})")
            continue
        print(f"{cat:<20} | {n:<10} | {row['top_g_hit_rate']:.2f}%")
        if row["top_g_hit_rate"] < 80.0:
            warnings.warn(f"หมวดหมู่ '{cat}' top-g hit rate ต่ำ ({row['top_g_hit_rate']:.1f}%) — ตรวจการยุบ template")
    return summary


def evaluate_sequence_level(
    evidence_logs: List[Dict],
    r_threshold: float,
    min_sample_size: int = 500,
) -> Optional[pd.DataFrame]:
    """
    ระดับ macro (sequence) — สัดส่วน session ที่ถูก flag เป็น anomaly ต่อ category

    ต้องใช้เกณฑ์เดียวกับ compute_anomaly() ตอน detect จริง คือ "สัดส่วน"
    ตำแหน่งที่ผิดคาดต่อจำนวน mask ทั้งหมดใน session (โค้ดในรีโปใช้สัดส่วน
    ไม่ใช่จำนวนนับ r ตามที่เปเปอร์เขียน — ดู CONFIG.md)

    category ของ sequence = category ของ key ที่พบมากที่สุดใน session นั้น
    (many-to-one จาก log key -> sequence ไม่ทำ multi-label ในรอบแรก)

    รันบน D2 (normal ล้วน) -> flag_rate_pct คือ FP rate ต่อ category
    รันบน D3 (มี label จริง) -> ใช้ประกอบกับ label เพื่อคำนวณ recall แยกต่างหาก
    """
    df = pd.DataFrame(evidence_logs)
    if df.empty:
        warnings.warn("ไม่มีข้อมูล evidence log สำหรับประเมินผล")
        return None

    df["miss"] = df["rank"].isna()
    per_session = df.groupby("session_id").agg(
        category=("category", lambda x: x.value_counts().idxmax()),
        n_masks=("observed", "count"),
        n_miss=("miss", "sum"),
    )
    per_session["flagged"] = per_session["n_miss"] / per_session["n_masks"] > r_threshold

    summary = per_session.groupby("category").agg(
        n_sessions=("flagged", "count"),
        n_flagged=("flagged", "sum"),
    )
    summary["flag_rate_pct"] = summary["n_flagged"] / summary["n_sessions"] * 100

    header = f"{'หมวดหมู่':<20} | {'จำนวน session':<14} | {'Flag rate (%)':<14}"
    print(header)
    print("-" * len(header))
    for cat, row in summary.iterrows():
        if row["n_sessions"] < min_sample_size:
            print(f"{cat:<20} | {row['n_sessions']:<14} | ข้อมูลไม่พอประเมิน")
            continue
        print(f"{cat:<20} | {row['n_sessions']:<14} | {row['flag_rate_pct']:.2f}%")
    return summary
