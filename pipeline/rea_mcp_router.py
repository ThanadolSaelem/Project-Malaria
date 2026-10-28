#!/usr/bin/env python3
"""
REA MCP ROUTER — tool-RAG / progressive tool disclosure over `rea mcp`
=============================================================================
ปัญหา: `rea mcp` expose ~139 tools → schema รวม ~140k tokens ถูกแนบไปทุก request
กิน context ของ Tiel (local llama) จนล้น (เคยเกิน 87k ตั้งแต่ยังไม่เริ่มงาน)

วิธีแก้ (ไฟล์นี้ — แนวเดียวกับ hexstrike_mcp_router.py): expose แค่ "3 meta-tools"
    rea_search_tools(query)   → ค้นชื่อ + คำอธิบายสั้น (always-on, ถูก)
    rea_describe_tool(name)   → schema เต็มของ tool นั้น (โหลดตอนต้องใช้)
    rea_run(name, arguments)  → ยิง tool จริงผ่าน `rea mcp`
→ always-on เหลือ ~2k tokens แต่ยังเข้าถึงครบทั้ง 139 tool (schema โหลด on-demand)

ต่างจาก hexstrike (ยืม tool manager Python ในตัว): REA เป็น MCP server แยก (stdio,
rea-agents node) → router นี้เป็น "MCP proxy" = เป็น **MCP server** (3 meta-tool) ที่
ภายในเป็น **MCP client** ต่อ `rea mcp` จริงอีกที แล้ว proxy การ list/call ให้

⚠️ สำคัญ: ห้ามใช้ FastMCP(lifespan=...) กับ streamable-http — มันไปทับ lifespan ของ
   session_manager (ตัว init task group) → "RuntimeError: Task group is not
   initialized". จึงเชื่อม backend แบบ lazy ผ่าน "dedicated background task" แทน:
   task เดียวที่เปิด stdio+session ค้างไว้ตลอดอายุ process ส่วน tool handler (คนละ task)
   เรียก session.call_tool ได้ (MCP ClientSession multiplex ด้วย request id)

แทนที่ supergateway: router spawn `rea mcp` (stdio) เองแล้วเสิร์ฟ streamable-http ที่
:8007/mcp (endpoint เดิม — harness ไม่ต้องเปลี่ยน url, แค่เห็น 3 tool แทน 139)

env: REA_MCP_CMD (ค่าเริ่ม "rea mcp") · MCP_HOST/MCP_PORT (0.0.0.0:8007) · REA_SEARCH_LIMIT (15)
"""
import os
import re
import sys
import shlex
import asyncio
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP


def _first_line(text: str, limit: int = 220) -> str:
    if not text:
        return ""
    line = text.strip().splitlines()[0].strip()
    return (line[: limit - 1] + "…") if len(line) > limit else line


def _score(query: str, entry: dict) -> int:
    q = query.lower().strip()
    if not q:
        return 0
    name_l = entry["name"].lower()
    hay = (entry["name"] + " " + entry["description"]).lower()
    s = 0
    for term in [w for w in re.split(r"\s+", q) if w]:
        if term in name_l:
            s += 5
        if term in hay:
            s += 1
    if q in hay:
        s += 2
    return s


class ReaBackend:
    """MCP client ต่อ `rea mcp` (stdio) ค้างไว้ใน 'dedicated background task' เดียว
    แล้ว proxy ให้ meta-tools. เชื่อมแบบ lazy ตอน tool แรกถูกเรียก (ในลูปของ server)."""

    def __init__(self, command: str, args: list):
        self.command = command
        self.args = args
        self.session = None
        self.catalog = {}
        self.names = []
        self.ready = asyncio.Event()
        self.error = None
        self._task = None
        self._stop = asyncio.Event()

    async def _run(self):
        """เปิด stdio+session, index tools, แล้วค้างไว้ (await _stop) ตลอดอายุ process."""
        try:
            async with AsyncExitStack() as stack:
                params = StdioServerParameters(
                    command=self.command, args=self.args, env=os.environ.copy()
                )
                read, write = await stack.enter_async_context(stdio_client(params))
                self.session = await stack.enter_async_context(ClientSession(read, write))
                await self.session.initialize()
                resp = await self.session.list_tools()
                for t in resp.tools:
                    desc = t.description or ""
                    self.catalog[t.name] = {
                        "name": t.name,
                        "description": desc,
                        "brief": _first_line(desc),
                        "parameters": t.inputSchema or {},
                    }
                self.names = sorted(self.catalog)
                print("[rea-router] indexed %d tools" % len(self.names), file=sys.stderr)
                self.ready.set()
                await self._stop.wait()          # คงสโคป stdio+session ไว้ตลอด
        except Exception as e:                   # เชื่อมไม่ได้ → ปลดล็อกคนที่รอ ให้เห็น error
            self.error = e
            print("[rea-router] backend FAILED: %r" % e, file=sys.stderr)
            self.ready.set()

    async def wait_ready(self):
        if self._task is None:                   # ไม่มี await คั่นระหว่างเช็ก+assign → ปลอดภัยในลูปเดี่ยว
            self._task = asyncio.create_task(self._run())
        await self.ready.wait()
        if self.error is not None:
            raise RuntimeError("rea backend not available: %s" % self.error)

    async def call(self, name: str, arguments: dict) -> dict:
        res = await self.session.call_tool(name, arguments or {})
        parts = []
        for c in (getattr(res, "content", None) or []):
            if getattr(c, "type", None) == "text":
                parts.append(c.text)
            else:
                parts.append(repr(c))
        out = {"isError": bool(getattr(res, "isError", False))}
        structured = getattr(res, "structuredContent", None)
        if structured is not None:
            out["structured"] = structured
        out["content"] = "\n".join(parts)
        return out


_CMD = shlex.split(os.environ.get("REA_MCP_CMD", "rea mcp"))
_BACKEND = ReaBackend(_CMD[0], _CMD[1:])
_MAX_RESULTS = int(os.environ.get("REA_SEARCH_LIMIT", "15"))

router = FastMCP("rea-router")


@router.tool()
async def rea_search_tools(query: str) -> dict:
    """ค้นหา REA reverse-engineering tool ที่ตรงกับงาน — คืนชื่อ + คำอธิบายสั้น (ยังไม่โหลด
    schema เต็ม เพื่อประหยัด context). ใช้ "ก่อนเสมอ" เพื่อหา tool ที่ต้องการ แล้วค่อยเรียก
    rea_run. query เป็นคำค้นภาษาอังกฤษ เช่น "decompile function", "android package",
    "pe resources", "pyinstaller extract", "javascript bundle", "evidence bundle"."""
    await _BACKEND.wait_ready()
    cat, names = _BACKEND.catalog, _BACKEND.names
    ranked = sorted(names, key=lambda n: _score(query, cat[n]), reverse=True)
    hits = [n for n in ranked if _score(query, cat[n]) > 0][:_MAX_RESULTS]
    if not hits:
        hits = ranked[:_MAX_RESULTS]
    return {
        "query": query,
        "count": len(hits),
        "tools": [{"name": n, "description": cat[n]["brief"]} for n in hits],
        "next": "ถ้าไม่แน่ใจ args เรียก rea_describe_tool(name) ก่อน แล้ว rea_run(name, arguments)",
    }


@router.tool()
async def rea_describe_tool(name: str) -> dict:
    """คืน schema เต็ม (พารามิเตอร์ทั้งหมดที่ tool รับ) ของ REA tool ชื่อ name.
    เรียกก่อน rea_run เมื่อไม่แน่ใจว่า tool ต้องส่ง argument อะไรบ้าง."""
    await _BACKEND.wait_ready()
    cat, names = _BACKEND.catalog, _BACKEND.names
    entry = cat.get(name)
    if not entry:
        sugg = sorted(names, key=lambda n: _score(name, cat[n]), reverse=True)[:8]
        return {"error": "ไม่พบ tool '%s'" % name, "did_you_mean": sugg}
    return {"name": name, "description": entry["description"], "parameters": entry["parameters"]}


@router.tool()
async def rea_run(name: str, arguments: dict | None = None) -> dict:
    """รัน REA tool ชื่อ name พร้อม arguments (dict ตาม schema จาก rea_describe_tool).
    คืนผลลัพธ์จาก tool นั้น (output อาจยาว — งานใหญ่ให้แบ่งทำทีละน้อย)."""
    await _BACKEND.wait_ready()
    cat, names = _BACKEND.catalog, _BACKEND.names
    if name not in cat:
        sugg = sorted(names, key=lambda n: _score(name, cat[n]), reverse=True)[:8]
        return {"error": "ไม่พบ tool '%s'" % name, "did_you_mean": sugg}
    try:
        res = await _BACKEND.call(name, arguments or {})
        return {"tool": name, "result": res}
    except Exception as e:
        return {"tool": name, "error": "%s: %s" % (type(e).__name__, e)}


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8007"))
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
        print("[rea-router] WARN transport_security: %s" % e, file=sys.stderr)

    print("[rea-router] serving at http://%s:%d/mcp — 3 meta-tools (backend เชื่อมตอน tool แรก)"
          % (host, port), file=sys.stderr)
    router.run(transport="streamable-http")


if __name__ == "__main__":
    main()
