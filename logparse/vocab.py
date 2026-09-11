import datetime
import json
from typing import Dict

import xxhash

# ID พิเศษสำหรับ template ที่ไม่รู้จัก (หลัง freeze แล้วเจอ template ใหม่)
# ยาว 12 ตัวอักษรเท่ากับ log key ID ปกติ เพื่อไม่ให้ downstream code ที่คาดหวัง
# ความยาวคงที่พัง
UNK_ID = "unk_00000000"


class DeterministicVocab:
    """
    Mapping ระหว่าง template <-> log key ID ที่ deterministic เสมอ
    (ID มาจาก hash ของข้อความ template ไม่ใช่ลำดับหรือความถี่ — แก้ปัญหาเดียว
    กับที่โค้ดเดิมเจอตอน mapping() เรียงตาม Occurrences แล้วรันคนละรอบได้
    เลข log key คนละชุด)

    วงจรชีวิตที่ตั้งใจให้ใช้:
      1. ตอนออกแบบกฎ (discover.py): add_template() ไปเรื่อย ๆ จนกฎนิ่ง
      2. freeze() ครั้งเดียว แล้ว save()
      3. ตอน production: load() แล้วใช้ lookup() อย่างเดียว ห้าม add_template()
         อีก — ถ้ามี template ใหม่โผล่มาจริงจะได้ UNK_ID กลับมาแทน ไม่ทำให้ ID
         ของ template เดิมขยับ ถ้าจะเพิ่มต้องขึ้น vocab version ใหม่และ
         พิจารณา retrain ไม่ใช่แก้ไฟล์นี้เงียบ ๆ
    """

    def __init__(self, version: str):
        self.version = version
        self.template_to_id: Dict[str, str] = {}
        self.id_to_meta: Dict[str, dict] = {}
        self._frozen = False

    def add_template(self, normalized_template: str, category: str, cluster_id: int) -> str:
        if self._frozen:
            raise RuntimeError(
                "Vocab นี้ freeze แล้ว ห้าม add_template เพิ่ม — ถ้ามี template ใหม่ "
                "จริงต้องขึ้น vocab version ใหม่และพิจารณา retrain"
            )
        if normalized_template in self.template_to_id:
            return self.template_to_id[normalized_template]

        template_id = xxhash.xxh64(normalized_template.encode("utf-8")).hexdigest()[:12]
        self.template_to_id[normalized_template] = template_id
        self.id_to_meta[template_id] = {
            "template": normalized_template,
            "category": category,
            "cluster_id": cluster_id,
        }
        return template_id

    def freeze(self) -> None:
        self._frozen = True

    def lookup(self, normalized_template: str) -> str:
        """ใช้ตอน production เท่านั้น — template ที่ไม่รู้จักคืน UNK_ID เสมอ"""
        return self.template_to_id.get(normalized_template, UNK_ID)

    def save(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": self.version,
                    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "frozen": self._frozen,
                    "mappings": self.id_to_meta,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    @classmethod
    def load(cls, filepath: str) -> "DeterministicVocab":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        vocab = cls(version=data["version"])
        for template_id, meta in data["mappings"].items():
            vocab.template_to_id[meta["template"]] = template_id
            vocab.id_to_meta[template_id] = meta
        # โหลดจากไฟล์แล้วถือว่า freeze โดย default (ป้องกันการแก้ในหน่วยความจำ
        # โดยไม่ตั้งใจ) — override ได้ด้วย vocab._frozen = False ถ้าตั้งใจแก้จริง
        vocab._frozen = data.get("frozen", True)
        return vocab
