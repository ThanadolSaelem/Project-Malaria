#!/usr/bin/env python3
"""
HexStrike MCP ROUTER — tool-RAG / progressive tool disclosure (over HTTP)
=============================================================================
ปัญหา: hexstrike_mcp.py expose 150+ tools → schema รวมกัน ~45-65k tokens ถูกแนบ
ไปทุก request กิน context เกือบเต็มตั้งแต่ยังไม่เริ่มงาน (local llama ctx 65k เต็มง่าย)

วิธีแก้ (ไฟล์นี้): แทนที่จะ expose ครบ 150 → expose แค่ "3 meta-tools"
    hexstrike_search_tools(query)   → ค้นชื่อ + คำอธิบายสั้น (always-on, ถูก)
    hexstrike_describe_tool(name)   → schema เต็มของ tool นั้น (โหลดตอนต้องใช้)
    hexstrike_run(name, arguments)  → ยิง tool จริงผ่าน tool manager ของตัวเต็ม
→ always-on เหลือ ~2k tokens แต่ยังเข้าถึงครบทั้ง 150 tool (โหลด schema แบบ on-demand)

reuse โค้ด vendor เดิมทั้งหมด (HexStrikeClient + setup_mcp_server) ไม่แก้ของเดิม
แค่สร้าง FastMCP ใหม่หุ้ม _tool_manager ของตัวเต็มไว้ แล้วเสิร์ฟ streamable-http
ที่ endpoint เดิม (/mcp) — ใน OpenCode ไม่ต้องเปลี่ยน URL แค่ refresh ก็เห็น 3 tool

env (เหมือน hexstrike_mcp_http.py):
    HEXSTRIKE_SERVER   URL ของ hexstrike_server.py (ค่าเริ่ม http://127.0.0.1:8888)
    HEXSTRIKE_TIMEOUT  timeout ต่อ request (วินาที, ค่าเริ่ม 300)
    MCP_HOST / MCP_PORT host:port ที่จะ bind (ค่าเริ่ม 0.0.0.0:8001)
    HEXSTRIKE_SEARCH_LIMIT  จำนวนผลลัพธ์สูงสุดของ search (ค่าเริ่ม 15)
"""
import os
import re
import sys

# ให้ import โมดูล vendor เดิมได้ ไม่ว่าจะรันจากที่ไหน
HEXSTRIKE_DIR = os.environ.get(
    "HEXSTRIKE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hexstrike-ai-main"),
)
sys.path.insert(0, os.path.abspath(HEXSTRIKE_DIR))

from hexstrike_mcp import HexStrikeClient, setup_mcp_server  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402


def _get_tool_manager(full: FastMCP):
    """หา ToolManager ภายในของ FastMCP (รองรับหลายเวอร์ชันของ mcp SDK)."""
    for attr in ("_tool_manager", "tool_manager"):
        tm = getattr(full, attr, None)
        if tm is not None:
            return tm
    raise RuntimeError(
        "หา tool manager ของ FastMCP ไม่เจอ — เวอร์ชัน mcp SDK อาจเปลี่ยนโครงสร้าง"
    )


def _first_line(text: str, limit: int = 220) -> str:
    """เอาบรรทัดแรกของ docstring มาเป็นคำอธิบายสั้น (ให้ search result เบา)."""
    if not text:
        return ""
    line = text.strip().splitlines()[0].strip()
    return (line[: limit - 1] + "…") if len(line) > limit else line


def build_catalog(tm) -> dict:
    """ดึง name / description / parameters(JSON schema) ของทุก tool จาก tool manager."""
    catalog = {}
    for t in tm.list_tools():
        name = getattr(t, "name", None)
        if not name:
            continue
        desc = getattr(t, "description", "") or ""
        params = getattr(t, "parameters", None) or {}
        catalog[name] = {
            "name": name,
            "description": desc,
            "brief": _first_line(desc),
            "parameters": params,
        }
    return catalog


def _score(query: str, entry: dict) -> int:
    """keyword match ง่ายๆ (ไม่ต้อง embedding) — พอสำหรับ 150 คำอธิบายสั้น."""
    q = query.lower().strip()
    if not q:
        return 0
    name_l = entry["name"].lower()
    hay = (entry["name"] + " " + entry["description"]).lower()
    s = 0
    for term in [w for w in re.split(r"\s+", q) if w]:
        if term in name_l:
            s += 5          # ตรงชื่อ tool = น้ำหนักมาก
        if term in hay:
            s += 1          # ตรงใน description
    if q in hay:
        s += 2              # โบนัสถ้าทั้ง query เป็น substring
    return s


def main() -> None:
    server = os.environ.get("HEXSTRIKE_SERVER", "http://127.0.0.1:8888")
    timeout = int(os.environ.get("HEXSTRIKE_TIMEOUT", "300"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8001"))
    max_results = int(os.environ.get("HEXSTRIKE_SEARCH_LIMIT", "15"))

    client = HexStrikeClient(server, timeout)
    health = client.check_health()
    if "error" in health:
        print(f"[hexstrike-router] WARN: ต่อ {server} ไม่ได้: {health['error']}",
              file=sys.stderr)
    else:
        print(f"[hexstrike-router] connected to {server} "
              f"(status={health.get('status')})", file=sys.stderr)

    # สร้างตัวเต็ม (150 tools) ไว้ "ภายใน" เพื่อยืม tool manager — ไม่ได้เสิร์ฟมันออกไป
    full = setup_mcp_server(client)
    tm = _get_tool_manager(full)
    catalog = build_catalog(tm)
    names = sorted(catalog)
    print(f"[hexstrike-router] indexed {len(names)} tools", file=sys.stderr)

    router = FastMCP("hexstrike-router")

    @router.tool()
    async def hexstrike_search_tools(query: str) -> dict:
        """ค้นหา HexStrike security tool ที่ตรงกับงาน — คืนชื่อ + คำอธิบายสั้น (ยังไม่โหลด
        schema เต็ม เพื่อประหยัด context). ใช้ "ก่อนเสมอ" เพื่อหา tool ที่ต้องการ แล้วค่อย
        เรียก hexstrike_run. query เป็นคำค้นภาษาอังกฤษ เช่น "port scan", "sql injection",
        "subdomain enumeration", "directory brute force", "web vulnerability nuclei"."""
        ranked = sorted(names, key=lambda n: _score(query, catalog[n]), reverse=True)
        hits = [n for n in ranked if _score(query, catalog[n]) > 0][:max_results]
        if not hits:                                  # ไม่ match เลย → คืนตัวแรกๆ กันมือเปล่า
            hits = ranked[:max_results]
        return {
            "query": query,
            "count": len(hits),
            "tools": [{"name": n, "description": catalog[n]["brief"]} for n in hits],
            "next": "ถ้าไม่แน่ใจ args เรียก hexstrike_describe_tool(name) ก่อน แล้ว "
                    "hexstrike_run(name, arguments) เพื่อรันจริง",
        }

    @router.tool()
    async def hexstrike_describe_tool(name: str) -> dict:
        """คืน schema เต็ม (พารามิเตอร์ทั้งหมดที่ tool รับ) ของ HexStrike tool ชื่อ name.
        เรียกก่อน hexstrike_run เมื่อไม่แน่ใจว่า tool ต้องส่ง argument อะไรบ้าง."""
        entry = catalog.get(name)
        if not entry:
            sugg = sorted(names, key=lambda n: _score(name, catalog[n]),
                          reverse=True)[:8]
            return {"error": f"ไม่พบ tool '{name}'", "did_you_mean": sugg}
        return {
            "name": name,
            "description": entry["description"],
            "parameters": entry["parameters"],
        }

    @router.tool()
    async def hexstrike_run(name: str, arguments: dict | None = None) -> dict:
        """รัน HexStrike tool ชื่อ name พร้อม arguments (dict ตาม schema จาก
        hexstrike_describe_tool). ตัวอย่าง:
          hexstrike_run("nmap_scan", {"target": "example.com",
                                       "additional_args": "-T4 -F -Pn"})
        คืนผลลัพธ์ดิบจาก tool นั้น (output อาจยาว — ถ้างานใหญ่ให้แบ่งรันทีละน้อย)."""
        arguments = arguments or {}
        if name not in catalog:
            sugg = sorted(names, key=lambda n: _score(name, catalog[n]),
                          reverse=True)[:8]
            return {"error": f"ไม่พบ tool '{name}'", "did_you_mean": sugg}
        try:
            result = await tm.call_tool(name, arguments)
            return {"tool": name, "result": result}
        except Exception as e:                        # คืน error สะอาด ไม่ให้ทั้ง turn ล้ม
            return {"tool": name, "error": f"{type(e).__name__}: {e}"}

    # host/port + ปิด DNS-rebinding protection (เหมือน hexstrike_mcp_http.py — ดูเหตุผลที่นั่น)
    try:
        router.settings.host = host
        router.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        router.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    except Exception as e:
        print(f"[hexstrike-router] WARN: ตั้ง transport_security ไม่ได้ ({e})",
              file=sys.stderr)

    print(f"[hexstrike-router] serving at http://{host}:{port}/mcp "
          f"— 3 meta-tools, {len(names)} tools indexed", file=sys.stderr)
    router.run(transport="streamable-http")


if __name__ == "__main__":
    main()
