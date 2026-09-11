import re
import warnings
from typing import Dict, List, Optional, Tuple


class ExtractStats:
    def __init__(self) -> None:
        self.total_lines: int = 0
        self.matched: int = 0
        self.unmatched: int = 0
        self.continued: int = 0
        self.unmatched_samples: List[str] = []


def extract(
    log_lines: List[str],
    log_format: str,
    continuation_pattern: Optional[str] = None,
    content_key: str = "Content",
    strict: bool = True,
) -> Tuple[List[Dict], ExtractStats]:
    """
    strict=True (ค่าเริ่มต้น): raise ทันทีถ้า unmatched เกิน 1% ของทั้งหมด
    strict=False: แค่ warn — ใช้เฉพาะตอน explore ข้อมูลเบื้องต้น ไม่ควรใช้ใน
    production pipeline เพราะ warning หายเงียบได้ง่ายเวลารันเป็น batch job
    (เช่น -W ignore หรือ logging framework บางตัวกลืน warning ทิ้ง)

    continuation_pattern: regex สำหรับบรรทัดที่เป็นส่วนต่อของบรรทัดก่อนหน้า
    (เช่น stack trace, JSON หลายบรรทัด) — บรรทัดที่ตรงกับ pattern นี้จะถูกต่อ
    เข้ากับ content_key ของ record ก่อนหน้า แทนที่จะนับเป็น unmatched
    """
    stats = ExtractStats()
    extracted_data: List[Dict] = []
    regex = re.compile(log_format)
    cont_regex = re.compile(continuation_pattern) if continuation_pattern else None

    for line in log_lines:
        stats.total_lines += 1
        stripped = line.rstrip("\n")
        match = regex.match(stripped)

        if match:
            extracted_data.append(match.groupdict())
            stats.matched += 1
            continue

        if cont_regex and cont_regex.match(stripped) and extracted_data:
            extracted_data[-1][content_key] = (
                extracted_data[-1].get(content_key, "") + " " + stripped.strip()
            )
            stats.continued += 1
            continue

        stats.unmatched += 1
        if len(stats.unmatched_samples) < 20:
            stats.unmatched_samples.append(stripped)

    unmatched_ratio = stats.unmatched / max(stats.total_lines, 1)
    if unmatched_ratio > 0.01:
        msg = (
            f"Unmatched lines เกิน 1% ({unmatched_ratio:.2%}, "
            f"{stats.unmatched}/{stats.total_lines}) — ตรวจ log_format หรือเพิ่ม "
            f"continuation_pattern ตัวอย่างที่ไม่ match: {stats.unmatched_samples[:3]}"
        )
        if strict:
            raise ValueError(msg)
        warnings.warn(msg)

    return extracted_data, stats
