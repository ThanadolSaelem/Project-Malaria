#!/usr/bin/env python3
"""
Knowledge-graph memory — MCP over HTTP (streamable-http)  [non-vector]
=============================================================================
ความจำแบบ "knowledge graph" ให้โมเดลจำข้ามรอบ/ข้าม session ได้ — เก็บเป็น
entities (โหนด) + observations (ข้อเท็จจริงของโหนด) + relations (เส้นเชื่อม)
ลง JSON ไฟล์เดียวบน volume → persist, ไม่มี embedding/vector → **ไม่มีปัญหา
dimension ตอนเปลี่ยนโมเดล** และไม่ต้องรัน embedding model เพิ่ม

เหมาะกับงาน pentest ที่ข้อมูลมีโครงสร้าง (host/port/service/vuln):
  memory_add("scanme.nmap.org", "host", ["80/tcp open http", "22/tcp open ssh"])
  memory_relate("scanme.nmap.org", "CVE-XXXX", "affected_by")
  memory_search("scanme")   → คืนโหนด + observations + relations ที่ match (keyword)

env:
  MEMORY_FILE   path ไฟล์ JSON (ค่าเริ่ม /data/memory.json — ควร mount volume)
  MCP_HOST / MCP_PORT   host:port ที่ bind (ค่าเริ่ม 0.0.0.0:8002)
endpoint: http://<host>:<MCP_PORT>/mcp
"""
import json
import os
import re
import sys
import tempfile
import threading

from mcp.server.fastmcp import FastMCP

MEMORY_FILE = os.environ.get("MEMORY_FILE", "/data/memory.json")
_LOCK = threading.Lock()


def _empty() -> dict:
    return {"entities": {}, "relations": []}


def _load() -> dict:
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("entities", {})
        data.setdefault("relations", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _save(data: dict) -> None:
    """เขียนแบบ atomic (temp + replace) กันไฟล์พังถ้าดับกลางคัน."""
    os.makedirs(os.path.dirname(MEMORY_FILE) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(MEMORY_FILE) or ".",
                               prefix=".memory.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MEMORY_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _score(query: str, name: str, etype: str, obs: list) -> int:
    q = query.lower().strip()
    if not q:
        return 0
    terms = [w for w in re.split(r"\s+", q) if w]
    name_l, type_l = name.lower(), (etype or "").lower()
    hay = (name_l + " " + type_l + " " + " ".join(obs)).lower()
    s = 0
    for t in terms:
        if t in name_l:
            s += 5
        if t in type_l:
            s += 2
        if t in hay:
            s += 1
    if q in hay:
        s += 2
    return s


def _relations_of(data: dict, name: str) -> list:
    return [r for r in data["relations"]
            if r.get("from") == name or r.get("to") == name]


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8002"))

    mcp = FastMCP("memory")

    @mcp.tool()
    def memory_add(name: str, entity_type: str = "",
                   observations: list[str] | None = None) -> dict:
        """บันทึก/อัปเดต entity (โหนดความจำ) หนึ่งตัว พร้อม observations (ข้อเท็จจริง).
        ถ้ามี entity ชื่อนี้อยู่แล้ว จะ "เพิ่ม" observations ใหม่ต่อท้าย (ไม่ซ้ำ) และ
        อัปเดต type ถ้าส่งมา. ใช้บันทึก finding เช่น
        memory_add("scanme.nmap.org", "host", ["80/tcp open http", "title: Go ..."])."""
        observations = observations or []
        with _LOCK:
            data = _load()
            ent = data["entities"].get(name, {"type": "", "observations": []})
            if entity_type:
                ent["type"] = entity_type
            seen = set(ent["observations"])
            for o in observations:
                if o not in seen:
                    ent["observations"].append(o)
                    seen.add(o)
            data["entities"][name] = ent
            _save(data)
            return {"saved": name, "type": ent["type"],
                    "observation_count": len(ent["observations"])}

    @mcp.tool()
    def memory_relate(source: str, target: str, relation: str) -> dict:
        """เชื่อมความสัมพันธ์ระหว่าง entity สองตัว (มีทิศทาง source → target).
        เช่น memory_relate("scanme.nmap.org", "CVE-2023-XXXX", "affected_by").
        สร้าง entity ปลายทางอัตโนมัติถ้ายังไม่มี (type ว่าง)."""
        with _LOCK:
            data = _load()
            for n in (source, target):
                data["entities"].setdefault(n, {"type": "", "observations": []})
            rel = {"from": source, "to": target, "type": relation}
            if rel not in data["relations"]:
                data["relations"].append(rel)
            _save(data)
            return {"related": f"{source} -[{relation}]-> {target}"}

    @mcp.tool()
    def memory_search(query: str, limit: int = 10) -> dict:
        """ค้นความจำด้วย keyword (ชื่อ/type/observations) — คืน entity ที่ match
        พร้อม observations และ relations ของมัน. ใช้ "ก่อนเริ่มงาน" เพื่อเรียกคืน
        สิ่งที่เคยรู้เกี่ยวกับเป้าหมาย/หัวข้อ."""
        data = _load()
        scored = []
        for name, ent in data["entities"].items():
            sc = _score(query, name, ent.get("type", ""), ent.get("observations", []))
            if sc > 0:
                scored.append((sc, name, ent))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for _, name, ent in scored[:limit]:
            hits.append({
                "name": name,
                "type": ent.get("type", ""),
                "observations": ent.get("observations", []),
                "relations": _relations_of(data, name),
            })
        return {"query": query, "count": len(hits), "results": hits}

    @mcp.tool()
    def memory_read(limit: int = 50) -> dict:
        """คืนภาพรวมกราฟความจำ (entities + relations) จำกัดจำนวน entity ด้วย limit.
        ใช้ดูว่ามีอะไรเก็บไว้บ้างทั้งหมด."""
        data = _load()
        names = list(data["entities"].keys())[:limit]
        return {
            "entity_count": len(data["entities"]),
            "relation_count": len(data["relations"]),
            "entities": [{"name": n, **data["entities"][n]} for n in names],
            "relations": data["relations"][: limit * 4],
        }

    @mcp.tool()
    def memory_delete(name: str) -> dict:
        """ลบ entity ชื่อ name และ relations ที่เกี่ยวข้องทั้งหมด."""
        with _LOCK:
            data = _load()
            existed = data["entities"].pop(name, None) is not None
            before = len(data["relations"])
            data["relations"] = [r for r in data["relations"]
                                 if r.get("from") != name and r.get("to") != name]
            _save(data)
            return {"deleted": name, "existed": existed,
                    "relations_removed": before - len(data["relations"])}

    # host/port + ปิด DNS-rebinding (เหมือน hexstrike_mcp_router.py — ดูเหตุผลที่นั่น)
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    except Exception as e:
        print(f"[memory-mcp] WARN: ตั้ง transport_security ไม่ได้ ({e})",
              file=sys.stderr)

    n = len(_load()["entities"])
    print(f"[memory-mcp] serving at http://{host}:{port}/mcp "
          f"— file={MEMORY_FILE} ({n} entities loaded)", file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
