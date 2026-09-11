#!/usr/bin/env python3
"""
end_to_end_test.py — รันทุกขั้นตอนจริง: discover → review → resolve → apply_rules → vocab

สร้าง log สังเคราะห์ 24,000 บรรทัด มี:
  - connection allowed/denied (sensitive word)
  - EventID 4624/4625 (numeric enum)
  - rule_id 1-400 (numeric gray zone -> REVIEW)
  - service enum (text ambiguous -> REVIEW)
  - PacketResponder 0-3 (auto ENUM)
  - IP, blk_, UUID, path, username, host (mask)
"""

import os
import sys
import yaml

sys.path.insert(0, os.path.dirname(__file__))

from logparse.discover import discover, DiscoverConfig
from logparse.rules import (
    save_rules, load_rules, save_review, save_auto_splits, resolve_review_item, apply_rules
)
from logparse.vocab import DeterministicVocab


# ============================================================
# 1. สร้าง log สังเคราะห์ (24,000 บรรทัด)
# ============================================================
def generate_logs(n: int = 24000):
    import random
    random.seed(42)

    users = [f"user{i:03d}" for i in range(300)]
    hosts = [f"host{i:02d}" for i in range(50)]
    ips = [f"10.0.{i//256}.{i%256}" for i in range(200)]
    blks = [f"blk_{random.randint(10**17, 10**18-1)}" for _ in range(100)]

    logs = []

    # connection allowed/denied by rule 1-400 (sensitive word + gray zone)
    for _ in range(5107):
        action = random.choice(["allowed", "denied"])
        rule_id = random.randint(1, 400)
        logs.append(f"connection from {random.choice(ips)} to {random.choice(ips)} {action} by rule {rule_id} for user {random.choice(users)} on host {random.choice(hosts)}")

    # EventID 4624/4625 (numeric enum)
    for eid in [4624, 4625]:
        for _ in range(1418 // 2):
            logs.append(f"EventID {eid} for user {random.choice(users)} on host {random.choice(hosts)}")

    # service enum (text ambiguous)
    for svc in ["nginx", "sshd", "cron"]:
        for _ in range(2173 // 3):
            logs.append(f"service {svc} restarted on {random.choice(hosts)}")

    # PacketResponder 0-3 (auto ENUM - small closed set of numbers)
    for rid in [0, 1, 2, 3]:
        for _ in range(2345 // 4):
            logs.append(f"PacketResponder {rid} for block {random.choice(blks)} terminating")

    # auth log with mfa (text ambiguous on "with mfa")
    for _ in range(2112):
        logs.append(f"user {random.choice(users)} logged in from host {random.choice(hosts)}")
    for _ in range(670):
        logs.append(f"user {random.choice(users)} logged in from host {random.choice(hosts)} with mfa")

    # other types for coverage
    for _ in range(1000):
        logs.append(f"Received block {random.choice(blks)} from {random.choice(ips)}")
    for _ in range(800):
        logs.append(f"BLOCK* NameSystem.addStoredBlock: block {random.choice(blks)} size 67108864")
    for _ in range(500):
        u = random.choice(users)
        logs.append(f"user {u} authenticated via ssh from {random.choice(ips)}")

    random.shuffle(logs)
    return logs


# ============================================================
# 2. จำลองคำตอบมนุษย์สำหรับ review items
# ============================================================
HUMAN_DECISIONS = {
    # rule_id (position 8 in connection log) -> mask as <NUM>
    "rule_id": "<NUM>",
    # service name (position 1 in service log) -> split enum
    "service_enum": "{nginx|sshd|cron}",
    # "with mfa" suffix (position 7 in login log) -> mask as <STR>
    "mfa_suffix": "<STR>",
}


def main():
    print("=" * 60)
    print("END-TO-END TEST: discover → review → resolve → vocab")
    print("=" * 60)

    # ---- สร้าง log ----
    print("\n[1/6] สร้าง log สังเคราะห์...")
    logs = generate_logs(24000)
    print(f"    สร้าง {len(logs)} บรรทัด")

    # ---- discover ----
    print("\n[2/6] รัน discover() ...")
    cfg = DiscoverConfig(
        expected_templates=15,
        k_multiplier=2.5,
        card_threshold=5,
        numeric_distinct_threshold=60,
        min_cluster_size=10,
        seed=42,
    )
    result = discover(logs, cfg)

    rules = result["rules"]
    review_items = result["review_items"]
    auto_splits = result["auto_splits"]

    print(f"    rules: {len(rules)}")
    print(f"    review_items: {len(review_items)}")
    print(f"    auto_splits: {len(auto_splits)}")

    for r in rules:
        print(f"      rule: count={r['count']:5d}  template={r['template'][:80]}")
    for r in review_items:
        print(f"      review: count={r['count']:5d}  draft={r['template_draft'][:80]}")
        for amb in r["ambiguous_positions"]:
            print(f"        pos={amb['position']} reason={amb['reason']} vals={amb['sample_values'][:5]}")

    # ---- บันทึกไฟล์ review/auto_splits ----
    print("\n[3/6] บันทึก review.md และ auto_splits.md ...")
    os.makedirs("output", exist_ok=True)
    save_review(review_items, "output/review.md")
    save_auto_splits(auto_splits, "output/auto_splits.md")
    print("    เขียน output/review.md, output/auto_splits.md แล้ว")

    # ---- จำลองมนุษย์ตอบ review ----
    print("\n[4/6] จำลองมนุษย์ตอบ review items...")
    resolved_rules = []
    for item in review_items:
        # ตัดสินจาก template_draft pattern
        draft = item["template_draft"]
        decisions = {}

        if "by rule" in draft:  # rule_id position
            for amb in item["ambiguous_positions"]:
                if amb["reason"] == "numeric-gray-zone":
                    decisions[amb["position"]] = HUMAN_DECISIONS["rule_id"]

        if "service" in draft and "restarted" in draft:  # service enum
            for amb in item["ambiguous_positions"]:
                if amb["reason"] == "text-ambiguous":
                    decisions[amb["position"]] = HUMAN_DECISIONS["service_enum"]

        if "logged in" in draft and "with" in draft:  # mfa suffix
            for amb in item["ambiguous_positions"]:
                if amb["reason"] == "text-ambiguous":
                    decisions[amb["position"]] = HUMAN_DECISIONS["mfa_suffix"]

        if decisions:
            resolved = resolve_review_item(item, decisions)
            resolved_rules.append(resolved)
            print(f"    resolved: {resolved['template'][:80]}")

    # ---- รวม rules ทั้งหมด ----
    print("\n[5/6] รวม rules และบันทึก rules.yaml ...")
    all_rules = rules + resolved_rules
    save_rules(all_rules, "output/rules.yaml")
    print(f"    รวม {len(all_rules)} rules → output/rules.yaml")

    # ---- โหลด rules กลับมาใช้จริง + vocab ----
    print("\n[6/6] ทดสอบ apply_rules + vocab (production path)...")
    loaded_rules = load_rules("output/rules.yaml")

    vocab = DeterministicVocab(version="test-v1")
    for rule in loaded_rules:
        vocab.add_template(rule["template"], rule.get("category", "unknown"), rule.get("cluster_id", -1))
    vocab.freeze()
    vocab.save("output/vocab.json")
    print(f"    vocab size: {len(vocab.template_to_id)}")

    # ทดสอบ apply_rules บน log ทั้งชุด
    unk_count = 0
    key_counts = {}
    for line in logs:
        tokens = line.split()
        template = apply_rules(tokens, loaded_rules)
        if template is None:
            unk_count += 1
            key = "<UNK>"
        else:
            key = vocab.lookup(template)
        key_counts[key] = key_counts.get(key, 0) + 1

    print(f"    <UNK> rate: {unk_count}/{len(logs)} = {unk_count/len(logs)*100:.2f}%")
    print(f"    unique log keys: {len(key_counts)}")

    # วัด purity/fragmentation ตาม ground truth types
    print("\n=== METRICS ===")

    # สร้าง ground truth type map จาก log generation logic
    def ground_truth_type(line: str) -> str:
        if "connection from" in line and "allowed by rule" in line:
            return "conn_allowed"
        if "connection from" in line and "denied by rule" in line:
            return "conn_denied"
        if line.startswith("EventID 4624"):
            return "eventid_4624"
        if line.startswith("EventID 4625"):
            return "eventid_4625"
        if "service nginx restarted" in line:
            return "svc_nginx"
        if "service sshd restarted" in line:
            return "svc_sshd"
        if "service cron restarted" in line:
            return "svc_cron"
        if "PacketResponder" in line and "terminating" in line:
            return "packet_responder"
        if "logged in from host" in line and "with mfa" in line:
            return "login_mfa"
        if "logged in from host" in line:
            return "login_plain"
        if "Received block" in line:
            return "received_block"
        if "NameSystem.addStoredBlock" in line:
            return "add_stored_block"
        if "authenticated via ssh" in line:
            return "ssh_auth"
        return "unknown"

    # map log key -> set of ground truth types
    key_to_types = defaultdict(set)
    for line in logs:
        tokens = line.split()
        template = apply_rules(tokens, loaded_rules)
        key = vocab.lookup(template) if template else "<UNK>"
        key_to_types[key].add(ground_truth_type(line))

    # purity: แต่ละ key มี type เดียวหรือไม่
    pure_keys = sum(1 for types in key_to_types.values() if len(types) == 1)
    total_keys = len(key_to_types)
    purity = pure_keys / total_keys if total_keys else 0

    # fragmentation: แต่ละ type แตกเป็นกี่ key
    type_to_keys = defaultdict(set)
    for key, types in key_to_types.items():
        for t in types:
            type_to_keys[t].add(key)
    frag = sum(len(keys) for keys in type_to_keys.values()) / len(type_to_keys)

    print(f"purity:        {purity:.4f}  ({pure_keys}/{total_keys} keys pure)")
    print(f"fragmentation: {frag:.4f}  ({len(type_to_keys)} types, avg {frag:.2f} keys/type)")

    # แสดง breakdown
    for t, keys in sorted(type_to_keys.items()):
        if len(keys) > 1:
            print(f"  FRAG: {t} -> {len(keys)} keys: {keys}")

    coverage = sum(1 for k in key_counts if k != "<UNK>") / len(logs)
    print(f"coverage:      {coverage:.4f}  (non-UNK lines)")

    print("\n✅ END-TO-END TEST COMPLETE")
    print("   ไฟล์ output/: rules.yaml, review.md, auto_splits.md, vocab.json")


if __name__ == "__main__":
    from collections import defaultdict
    main()