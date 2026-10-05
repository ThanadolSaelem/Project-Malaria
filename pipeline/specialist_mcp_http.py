#!/usr/bin/env python3
"""
Exploit specialist — MCP over HTTP (streamable-http)
=============================================================================
Gives the orchestrator model (Cyber-Tiel-Coder-35B-A3B) a single tool,
`ask_exploit_specialist`, that delegates heavy offensive code-writing to a
second, offensive-tuned model (default: BugTraceAI-CORE-Ultra-27B) served by
its own llama.cpp instance and reached through LiteLLM.

Why a separate model as a *tool* instead of a second "agent":
  - The specialist is pure text-in / text-out — it only writes code; it never
    calls tools. So the Qwen2.5-Coder-family tool-calling quirk (unreliable
    <tool_call> emission) is irrelevant here: only the orchestrator calls tools.
  - The orchestrator stays in charge of scope/authorization and tool execution;
    this tool just returns exploit/PoC/payload *source* for it to review and run.

Flow:
  Tiel (orchestrator)
    -> ask_exploit_specialist(task, context)
      -> LiteLLM  (model alias: exploit-specialist)
        -> llama.cpp :8091  (BugTraceAI-CORE-Ultra-27B)
      <- code / notes (text)
    <- returned to Tiel to review, adapt, and run via HexStrike

env:
  LITELLM_BASE     OpenAI-compatible base URL of the gateway
                   (default http://litellm:4000/v1 — the compose service)
  SPECIALIST_MODEL LiteLLM model alias to call (default "exploit-specialist")
  LITELLM_API_KEY  key sent as Bearer (default "sk-local"; llama ignores it)
  SPECIALIST_TIMEOUT  per-request timeout in seconds (default 900)
  SPECIALIST_MAX_TOKENS  max output tokens (default 4096)
  MCP_HOST / MCP_PORT host:port to bind (default 0.0.0.0:8003)
endpoint: http://<host>:<MCP_PORT>/mcp
"""
import os
import sys

import requests
from mcp.server.fastmcp import FastMCP

LITELLM_BASE = os.environ.get("LITELLM_BASE", "http://litellm:4000/v1").rstrip("/")
SPECIALIST_MODEL = os.environ.get("SPECIALIST_MODEL", "exploit-specialist")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "sk-local")
TIMEOUT = int(os.environ.get("SPECIALIST_TIMEOUT", "900"))
MAX_TOKENS = int(os.environ.get("SPECIALIST_MAX_TOKENS", "4096"))

# The specialist assumes authorization/scope were already verified by the
# orchestrator (it has no tools and touches no targets — it only writes code).
SPECIALIST_SYSTEM = (
    "You are an exploit-development specialist supporting an AUTHORIZED "
    "penetration-testing engagement. The orchestrator has already verified that "
    "the target and action are inside the written, authorized scope before "
    "delegating to you.\n\n"
    "Your job: given a task and the orchestrator's context (host / service / "
    "version / observed behaviour), write complete, correct, well-commented "
    "offensive code — proof-of-concept exploits, payloads, Nuclei templates, "
    "fuzzing/enumeration scripts, or code-audit findings — ready for the "
    "orchestrator to review and run.\n\n"
    "Rules:\n"
    "- Output the code first, in a single fenced block with the right language, "
    "then a few short usage notes (how to run, required args, expected result).\n"
    "- Be precise and minimal: solve exactly the task; do not add unrelated steps.\n"
    "- Clearly flag any step that is destructive or disruptive (data loss, "
    "service crash, account lockout) so the orchestrator can gate it.\n"
    "- You have no tools and run nothing yourself. Never claim you executed "
    "anything — you only produce source for the orchestrator to run.\n"
    "- Do not restate the scope rules; assume authorization is handled upstream."
)


def _call_gateway(messages: list[dict]) -> str:
    url = f"{LITELLM_BASE}/chat/completions"
    payload = {
        "model": SPECIALIST_MODEL,
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
        """Delegate heavy offensive code-writing to the exploit specialist model
        and return its code. Use this when you need working exploit / PoC /
        payload / Nuclei-template / offensive-script source — not for planning,
        recon, or reading scan output (do those yourself).

        Pass a clear `task` (what to build) and `context` with the concrete
        facts you already confirmed (target host/URL, service + version, the
        vulnerability or behaviour, any constraints). The specialist returns
        source code for YOU to review and run via HexStrike — it does not run
        anything itself. Only call it for targets already inside the authorized
        scope.

        e.g. ask_exploit_specialist(
               task="Write a Python PoC for the detected SSTI on the /greet name param",
               context="target=http://10.0.0.5/greet?name=  engine=Jinja2  "
                       "reflects {{7*7}} as 49  GET param 'name'")
        """
        if not task or not task.strip():
            return {"error": "task is required — describe what to build"}
        user = task.strip()
        if context and context.strip():
            user += "\n\n## Context (confirmed facts from the engagement)\n" + context.strip()
        messages = [
            {"role": "system", "content": SPECIALIST_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            answer = _call_gateway(messages)
            return {"model": SPECIALIST_MODEL, "answer": answer}
        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            return {"error": f"gateway HTTP {e.response.status_code}: {body}",
                    "hint": "is the specialist llama-server up on :8091 and the "
                            "'exploit-specialist' alias in litellm-config.yaml?"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}",
                    "hint": f"could not reach LiteLLM at {LITELLM_BASE}"}

    # host/port + disable DNS-rebinding protection (internal loopback/compose
    # service only — same reasoning as hexstrike_mcp_router.py / memory_mcp_http.py)
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
        print(f"[specialist-mcp] WARN: could not set transport_security ({e})",
              file=sys.stderr)

    print(f"[specialist-mcp] serving at http://{host}:{port}/mcp "
          f"— model='{SPECIALIST_MODEL}' via {LITELLM_BASE}", file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
