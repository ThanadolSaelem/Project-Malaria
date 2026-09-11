"""
แยกตัวเลขที่เป็น "สถานะ" (enum) ออกจากตัวเลขที่เป็น "ตัวระบุ" (identifier)

⚠️ values_first_half / values_second_half ต้องแบ่งตาม "เวลา" เสมอ (ครึ่งแรก
ของช่วงเวลาที่เก็บข้อมูล vs ครึ่งหลัง) ห้ามแบ่งแบบสุ่ม — ถ้าสุ่มแบ่ง enum ที่
ค่าหายากจะดูเหมือน identifier เพราะแต่ละครึ่งบังเอิญได้ค่าคนละชุด

ต้องมีข้อมูลยาวพอ (แนะนำ >= 2 สัปดาห์) ถ้าช่วงข้อมูลคาบเกี่ยวกับเหตุการณ์
ผิดปกติ (เช่น HTTP status 500 โผล่มาตอนเกิดเหตุ) churn จะสูงผิดปกติ ให้แบ่ง
เป็น 3 ช่วงเวลาแล้วโหวตแทน 2 ช่วง

⚠️ ปัญหากลับด้านก็เกิดได้: กลุ่มตัวอย่างที่ "น้อยเกินไป" ทำให้ identifier
ตัวจริง (เช่น rule ID ที่มีค่าได้ 1-400) ดูเหมือน enum ไปเลย เพราะบังเอิญ
สุ่มเจอค่าซ้ำน้อยแบบ (พบจริงตอนทดสอบ end-to-end: cluster ย่อยที่มีแค่ 60
บรรทัด บังเอิญมีแต่ rule id ค่า 1,2,3 — churn=0%, distinct=3 → ถูกตัดสินเป็น
ENUM ทั้งที่จริงเป็น identifier เต็มช่วง 1-400 — เกิดจาก KMeans แยก cluster
ย่อยตามความถี่ของเลขตัวเล็กที่ใช้ร่วมกับ field อื่น (เช่น PacketResponder ID
ที่ก็มีค่า 0-3 เหมือนกัน) ทำให้ embedding ของเลขตัวเล็กเบี่ยงไปกลุ่มเดียวกัน
โดยไม่เกี่ยวกับความหมายจริงเลย) จึงต้องมี min_sample_size กันไว้เสมอ
"""

from typing import List, Optional, Set

# field ที่รู้อยู่แล้วว่าเป็น enum แน่นอน ไม่ต้องพึ่ง churn เลย
# สำคัญกับ Windows Event Log ที่บางครั้งดึงมาแค่ EventID ไม่มี message text
# ติดมา (ถ้ามี message text อยู่แล้ว 4624/4625 จะมีข้อความต่างกันชัดเจน
# ปัญหานี้ไม่เกิด — เช็คก่อนว่า field นี้จำเป็นสำหรับข้อมูลของคุณจริงไหม)
KNOWN_ENUM_FIELDS: Set[str] = {
    "eventid", "event_id",
}


def classify_numeric(
    values_first_half: List[str],
    values_second_half: List[str],
    field_name: Optional[str] = None,
    churn_threshold: float = 0.01,
    distinct_threshold: int = 64,
    min_sample_size: int = 100,
) -> str:
    """
    คืนค่า "ENUM" / "IDENTIFIER" / "REVIEW"

    - ENUM        → ห้าม mask อัตโนมัติ ต้องแยกเป็นคนละ log key
    - IDENTIFIER  → mask เป็น <NUM> ได้อัตโนมัติ
    - REVIEW      → "โซนสีเทา" (churn ต่ำแต่ distinct สูง เช่น firewall rule
                    ID ที่มี 400 ค่าแต่เป็นเซ็ตปิดจาก config) หรือข้อมูลน้อย
                    เกินจะเชื่อได้ ต้องถามคนเสมอว่าอยากให้โมเดลรู้ว่ากฎข้อไหน
                    ถูก trigger หรือแค่รู้ว่ามีการ trigger — ห้ามตัดสินอัตโนมัติ
    """
    if field_name and field_name.lower() in KNOWN_ENUM_FIELDS:
        return "ENUM"

    a: Set[str] = set(values_first_half)
    b: Set[str] = set(values_second_half)

    if len(values_second_half) < min_sample_size:
        return "REVIEW"  # ข้อมูลน้อยเกินจะเชื่อ churn/distinct ได้

    if not b:
        return "REVIEW"

    churn = len(b - a) / len(b)
    distinct = len(a | b)

    if churn < churn_threshold and distinct <= distinct_threshold:
        return "ENUM"
    if churn < churn_threshold and distinct > distinct_threshold:
        return "REVIEW"
    return "IDENTIFIER"