#!/usr/bin/env python3
"""
HexStrike MCP over HTTP  —  ตัวห่อ (wrapper) ให้ HarnessRouter ต่อได้ด้วย url

ทำไมต้องมีไฟล์นี้:
    hexstrike_mcp.py เดิมเรียก mcp.run() แบบเปล่า = พูด stdio อย่างเดียว
    ซึ่งเหมาะกับ Claude Desktop/Cursor ที่ spawn โปรเซสเอง แต่ HarnessRouter
    รัน harness ใน sandbox แยกต่อ session การจะยัด python+mcp เข้าไปทุก sandbox
    ยุ่งและเปราะ ทางที่สะอาดกว่าคือเปิด HexStrike MCP เป็น "remote HTTP MCP"
    แล้วให้ HarnessRouter ลงทะเบียนด้วย url เดียว (ดู pipeline/README.md)

ตัวไฟล์นี้ reuse โค้ดเดิมทั้งหมด (HexStrikeClient + setup_mcp_server) ไม่ได้
แก้ของ vendor เลย แค่เปลี่ยน transport เป็น streamable-http

env:
    HEXSTRIKE_SERVER   URL ของ hexstrike_server.py (ค่าเริ่ม http://127.0.0.1:8888)
    HEXSTRIKE_TIMEOUT  timeout ต่อ request (วินาที, ค่าเริ่ม 300)
    MCP_HOST           host ที่จะ bind (ค่าเริ่ม 0.0.0.0)
    MCP_PORT           port ที่จะ bind (ค่าเริ่ม 8001)

endpoint ที่ได้:  http://<host>:<MCP_PORT>/mcp
"""
import os
import sys

# ให้ import โมดูล vendor เดิมได้ ไม่ว่าจะรันจากที่ไหน
HEXSTRIKE_DIR = os.environ.get(
    "HEXSTRIKE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hexstrike-ai-main"),
)
sys.path.insert(0, os.path.abspath(HEXSTRIKE_DIR))

from hexstrike_mcp import HexStrikeClient, setup_mcp_server  # noqa: E402


def main() -> None:
    server = os.environ.get("HEXSTRIKE_SERVER", "http://127.0.0.1:8888")
    timeout = int(os.environ.get("HEXSTRIKE_TIMEOUT", "300"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8001"))

    client = HexStrikeClient(server, timeout)

    health = client.check_health()
    if "error" in health:
        # ไม่ตายทันที — server อาจยังบูตไม่เสร็จ tool จะ error ทีหลังถ้าจริงๆ ต่อไม่ได้
        print(f"[hexstrike-mcp-http] WARN: ต่อ {server} ไม่ได้: {health['error']}",
              file=sys.stderr)
    else:
        print(f"[hexstrike-mcp-http] connected to {server} "
              f"(status={health.get('status')})", file=sys.stderr)

    mcp = setup_mcp_server(client)

    # ตั้ง host/port ให้ FastMCP (รองรับหลายเวอร์ชันของ mcp SDK)
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))

    # ปิด DNS-rebinding protection ของ streamable-http:
    # ค่าเริ่มต้นของ mcp SDK คือ enable_dns_rebinding_protection=True + allowed_hosts=[]
    # พอ client (HarnessRouter gateway) เข้ามาด้วย Host เป็นชื่อ service ในเครือข่าย docker
    # เช่น "hexstrike-mcp:8001" ที่ไม่อยู่ใน allowlist มันจะตอบ HTTP 421 Misdirected Request
    # ตัวนี้เป็น service ภายในเครือข่าย docker (พอร์ตบน host ก็ bind 127.0.0.1) จึงปิดได้ปลอดภัย
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    except Exception as e:
        print(f"[hexstrike-mcp-http] WARN: ตั้ง transport_security ไม่ได้ ({e}) "
              f"— ถ้าเจอ HTTP 421 ให้เช็คเวอร์ชัน mcp SDK", file=sys.stderr)

    print(f"[hexstrike-mcp-http] serving MCP at http://{host}:{port}/mcp",
          file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
