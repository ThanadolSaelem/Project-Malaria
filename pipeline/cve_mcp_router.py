#!/usr/bin/env python3
"""
CVE MCP ROUTER — tool-RAG over cve-mcp-server (28 tools → 3 meta-tools)
=============================================================================
cve-mcp-server (github.com/mukul975/cve-mcp-server) = MCP ให้ข้อมูล vuln-intel
จาก NVD/EPSS/KEV/CWE/MITRE/CAPEC/OSV ฯลฯ รวม 28 tools → schema รวมกิน context เยอะ
ของ Tiel (local llama). แก้แบบเดียวกับ rea_mcp_router.py: เป็น MCP proxy ที่ expose
แค่ 3 meta-tool (search/describe/run) ที่ภายในเป็น MCP client ต่อ cve-mcp-server (stdio)

⚠️ กฎความปลอดภัยของระบบ (passive OSINT, ห้ามส่ง target/evidence/IOC ไปบริการบุคคลที่สาม):
   router นี้ "กรอง" tool กลุ่ม network/threat-intel ที่ส่ง IP/domain/hash/URL ออกไปยัง
   VirusTotal/Shodan/GreyNoise/AbuseIPDB/urlscan/ThreatFox/MalwareBazaar ฯลฯ ออกจาก
   catalog (search ไม่เจอ + run ปฏิเสธ) — เหลือเฉพาะ "CVE/vuln-intel แบบ lookup สาธารณะ"
   (NVD/EPSS/KEV/CWE/CVSS/MITRE/CAPEC/OSV/PoC/advisory) ที่เทียบเท่า web_search

env: CVE_MCP_CMD (ค่าเริ่ม "python -m cve_mcp.server") · MCP_HOST/MCP_PORT (0.0.0.0:8009)
     CVE_SEARCH_LIMIT (15) · CVE_TOOL_DENY (comma-separated override ของ denylist)
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

# tool ที่ "ส่ง target/IOC ออกไปบริการบุคคลที่สาม / ยิง scan จริง" → กันออก (ขัดกฎ passive OSINT)
_DEFAULT_DENY = {
    "lookup_ip_reputation", "check_ip_noise", "shodan_host_lookup", "passive_dns_lookup",
    "virustotal_lookup", "search_malware", "search_iocs", "check_ransomware", "urlscan_check",
}
_DENY = set(
    x.strip() for x in os.environ.get("CVE_TOOL_DENY", "").split(",") if x.strip()
) or _DEFAULT_DENY


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


class CveBackend:
    """MCP client ต่อ cve-mcp-server (stdio) ค้างไว้ใน dedicated background task เดียว
    (ห้ามใช้ FastMCP lifespan กับ streamable-http — ทับ session_manager → Task group error)."""

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
                    if t.name in _DENY:                 # กรอง tool ที่ขัดกฎออกจาก catalog
                        continue
                    desc = t.description or ""
                    self.catalog[t.name] = {
                        "name": t.name,
                        "description": desc,
                        "brief": _first_line(desc),
                        "parameters": t.inputSchema or {},
                    }
                self.names = sorted(self.catalog)
                print("[cve-router] indexed %d tools (กัน %d ตัวตามกฎ)"
                      % (len(self.names), len(_DENY)), file=sys.stderr)
                self.ready.set()
                await self._stop.wait()
        except Exception as e:
            self.error = e
            print("[cve-router] backend FAILED: %r" % e, file=sys.stderr)
            self.ready.set()

    async def wait_ready(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        await self.ready.wait()
        if self.error is not None:
            raise RuntimeError("cve backend not available: %s" % self.error)

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


_CMD = shlex.split(os.environ.get("CVE_MCP_CMD", "python -m cve_mcp.server"))
_BACKEND = CveBackend(_CMD[0], _CMD[1:])
_MAX_RESULTS = int(os.environ.get("CVE_SEARCH_LIMIT", "15"))

router = FastMCP("cve-router")


@router.tool()
async def cve_search_tools(query: str) -> dict:
    """ค้นหา CVE / vulnerability-intelligence tool ที่ตรงกับงาน — คืนชื่อ + คำอธิบายสั้น
    (ยังไม่โหลด schema เต็ม). ใช้ "ก่อนเสมอ" แล้วค่อยเรียก cve_run. query ภาษาอังกฤษ เช่น
    "cve lookup", "search cves by product", "epss score", "kev exploited", "cwe info",
    "cvss vector", "mitre technique", "exploit poc", "capec attack pattern",
    "dependency osv", "github advisory", "triage", "risk report". (tool กลุ่ม network/
    threat-intel ที่ส่ง IP/hash/URL ออกไปบริการภายนอก ถูกกันไว้ตามกฎ passive OSINT)"""
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
        "next": "ถ้าไม่แน่ใจ args เรียก cve_describe_tool(name) ก่อน แล้ว cve_run(name, arguments)",
    }


@router.tool()
async def cve_describe_tool(name: str) -> dict:
    """คืน schema เต็ม (พารามิเตอร์ทั้งหมด) ของ CVE tool ชื่อ name. เรียกก่อน cve_run
    เมื่อไม่แน่ใจว่าต้องส่ง argument อะไร."""
    await _BACKEND.wait_ready()
    cat, names = _BACKEND.catalog, _BACKEND.names
    entry = cat.get(name)
    if not entry:
        sugg = sorted(names, key=lambda n: _score(name, cat[n]), reverse=True)[:8]
        return {"error": "ไม่พบ tool '%s' (อาจถูกกันตามกฎ)" % name, "did_you_mean": sugg}
    return {"name": name, "description": entry["description"], "parameters": entry["parameters"]}


@router.tool()
async def cve_run(name: str, arguments: dict | None = None) -> dict:
    """รัน CVE / vuln-intel tool ชื่อ name พร้อม arguments (dict ตาม schema จาก
    cve_describe_tool). เช่น cve_run("lookup_cve", {"cve_id": "CVE-2024-3400"})."""
    await _BACKEND.wait_ready()
    cat, names = _BACKEND.catalog, _BACKEND.names
    if name in _DENY:
        return {"error": "tool '%s' ถูกกันตามกฎ passive OSINT (ส่ง target/IOC ออกภายนอก)" % name}
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
    port = int(os.environ.get("MCP_PORT", "8009"))
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
        print("[cve-router] WARN transport_security: %s" % e, file=sys.stderr)

    print("[cve-router] serving at http://%s:%d/mcp — 3 meta-tools (backend เชื่อมตอน tool แรก)"
          % (host, port), file=sys.stderr)
    router.run(transport="streamable-http")


if __name__ == "__main__":
    main()
