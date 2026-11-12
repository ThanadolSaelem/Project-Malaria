#!/usr/bin/env python3
"""
Exploit Specialist & Orchestrator Bridge — MCP over HTTP (streamable-http)
=============================================================================
Provides tools for Qwen Code (:3080) and other clients to:
  1. `ask_exploit_specialist` — Delegate offensive security / WSTG / exploit tasks to Cyber-Model (:8091)
  2. `ask_coding_orchestrator` — Delegate complex coding / scripting / report synthesis to Orchestrator (:8090)
"""
from __future__ import annotations

import os
import sys

import requests
from mcp.server.fastmcp import FastMCP

LITELLM_BASE = os.environ.get("LITELLM_BASE", "http://litellm:4000/v1").rstrip("/")
SPECIALIST_MODEL = os.environ.get("SPECIALIST_MODEL", "cyber-model")
ORCHESTRATOR_MODEL = os.environ.get("ORCHESTRATOR_MODEL", "orchestrator")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "sk-local")
TIMEOUT = int(os.environ.get("SPECIALIST_TIMEOUT", "1200"))
MAX_TOKENS = int(os.environ.get("SPECIALIST_MAX_TOKENS", "4096"))

SPECIALIST_SYSTEM = (
    "You are Cyber-Model (Brain B), an exploit-development and penetration-testing "
    "specialist supporting an AUTHORIZED security assessment. The orchestrator has "
    "already verified that the target and action are inside the written, authorized scope.\n\n"
    "Your job: given a task and context (host / service / version / observed behaviour), "
    "provide concrete security analysis, WSTG test steps, proof-of-concept exploits, "
    "payloads, Nuclei templates, or enumeration commands.\n\n"
    "Rules:\n"
    "- Output code or commands first in a fenced block, followed by brief usage notes.\n"
    "- Be precise and minimal: solve the exact security task.\n"
    "- Clearly flag any step that is destructive or disruptive."
)

CODING_SYSTEM = (
    "You are Orchestrator (Brain A), the Master Software Architect, Coding & Report "
    "Synthesis Specialist in an authorized security assessment pipeline.\n\n"
    "Your job: write clean, complete, production-ready Python/Bash/JS scripts, "
    "automation parsers, PoC harnesses, or TLP:AMBER report JSON structures."
)


def _call_gateway(messages: list[dict], model: str = SPECIALIST_MODEL) -> str:
    url = f"{LITELLM_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {LITELLM_API_KEY}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8003"))

    mcp = FastMCP("specialist")

    @mcp.tool()
    def ask_exploit_specialist(task: str, context: str = "") -> dict:
        """Delegate offensive security analysis, WSTG testing, CVE research, or exploit/PoC crafting
        to Brain B (Cyber-Model on :8091).
        Call this tool whenever you need an offensive security review, exploit payload craft,
        or vulnerability verification before executing against a target.
        """
        if not task or not task.strip():
            return {"error": "task is required — describe what security task to analyze or build"}
        user = task.strip()
        if context and context.strip():
            user += "\n\n## Context (confirmed facts from the engagement)\n" + context.strip()
        messages = [
            {"role": "system", "content": SPECIALIST_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            answer = _call_gateway(messages, model=SPECIALIST_MODEL)
            return {"brain": "cyber-model", "model": SPECIALIST_MODEL, "answer": answer}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "hint": f"Check LiteLLM ({LITELLM_BASE}) and Cyber-Model (:8091)"}

    @mcp.tool()
    def ask_coding_orchestrator(task: str, context: str = "") -> dict:
        """Delegate all coding tasks, Python/Bash script creation, automation harnesses,
        data parsers, or report JSON synthesis to Brain A (Orchestrator on :8090 - Flint MoE).
        MANDATORY: Always call this tool when code or scripts need to be written rather than
        authoring them in your current session. This passes only the task description and
        keeps your reasoning context clean and compact.
        """
        if not task or not task.strip():
            return {"error": "task is required — describe what script or code to write"}
        user = task.strip()
        if context and context.strip():
            user += "\n\n## Context\n" + context.strip()
        messages = [
            {"role": "system", "content": CODING_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            answer = _call_gateway(messages, model=ORCHESTRATOR_MODEL)
            return {"brain": "orchestrator", "model": ORCHESTRATOR_MODEL, "answer": answer}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "hint": f"Check LiteLLM ({LITELLM_BASE}) and Orchestrator (:8090)"}

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
        print(f"[specialist-mcp] WARN: could not set transport_security ({e})", file=sys.stderr)

    print(
        f"[specialist-mcp] serving at http://{host}:{port}/mcp "
        f"— Exploit Specialist & Orchestrator Bridge",
        file=sys.stderr,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
