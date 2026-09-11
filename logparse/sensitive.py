"""
ตรวจจับตำแหน่งที่มีคำสถานะ/ผลลัพธ์ที่ตรงข้ามกันปนอยู่ (เช่น allow/deny)
ห้ามยุบตำแหน่งเหล่านี้เป็นพารามิเตอร์เดียวกัน ต้องแยกเป็นคนละ log key เสมอ

อ้างอิงผลทดสอบ: purity 1.000 บนชุดทดสอบ 30,000 บรรทัดที่มีคู่ allow/deny และ
Failed/Accepted ต่างกันแค่คำเดียว เกิดขึ้นได้เพราะเงื่อนไข >= 1 คำ ไม่ใช่ > 1
"""

from typing import Iterable, List, Set

SENSITIVE_WORDS: Set[str] = {
    # ผล/สถานะการอนุญาต-ปฏิเสธ
    "allow", "allowed", "deny", "denied", "accept", "accepted",
    "reject", "rejected", "permit", "permitted", "drop", "dropped",
    "block", "blocked", "pass", "passed",
    # ผลสำเร็จ/ล้มเหลว
    "success", "succeeded", "successful", "fail", "failed", "failure", "error",
    # สิทธิ์
    "grant", "granted", "revoke", "revoked",
    "authorized", "unauthorized", "valid", "invalid",
    "expired", "verified", "unverified",
    # สถานะระบบ
    "enable", "enabled", "disable", "disabled", "up", "down",
    "start", "started", "stop", "stopped",
    "open", "opened", "close", "closed",
    "add", "added", "delete", "deleted",
    "create", "created", "remove", "removed",
    "mount", "unmount", "connect", "disconnect",
    "login", "logout",
}


def contains_sensitive_conflict(values: Iterable[str]) -> bool:
    """
    True ถ้าค่าที่พบในตำแหน่งนี้มีคำอ่อนไหวปนอยู่ "อย่างน้อย 1 คำ"

    เดิมโค้ดเช็ค `len(intersection) > 1` ซึ่งต้องการคำอ่อนไหว 2 คำขึ้นไป
    ถึงจะ trigger — พังทันทีถ้าตำแหน่งเดียวกันมีค่าเป็น
    {"allowed", "user123", "user456", "user789"} เพราะ intersection มีแค่
    {"allowed"} (len=1) จะไม่ถูก flag แล้วโดน mask เป็น <STR> ไปเงียบ ๆ

    เป้าหมายของฟังก์ชันนี้คือ "ห้ามพลาด" ไม่ใช่ "ต้องเจอครบคู่ก่อนถึงจะเชื่อ"
    จึงต้องเป็น >= 1 เสมอ
    """
    intersection = {v.lower() for v in values} & SENSITIVE_WORDS
    return len(intersection) >= 1


def split_marker(values: Iterable[str]) -> str:
    """
    สร้าง marker สำหรับตำแหน่งที่ต้องแยก ไม่ใช่ mask
    เช่น {"allowed", "denied"} -> "{allowed|denied}"
    ให้ discover.py เอาไปแทนตำแหน่งนั้นใน template แทนการใส่ <STR>
    """
    unique_sorted: List[str] = sorted(set(values))
    return "{" + "|".join(unique_sorted) + "}"
