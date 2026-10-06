#!/usr/bin/env python3
"""
Web search + fetch — MCP over HTTP (streamable-http), backed by self-hosted SearXNG
=============================================================================
Gives the orchestrator (Tiel) two tools for gathering external information:
  web_search(query, max_results) -> ranked [{title, url, snippet}]
  fetch_url(url, max_chars)      -> a page's text (HTML stripped, truncated)

Why this instead of the model's built-in webfetch:
  - There is no general web-search tool otherwise (webfetch only pulls a known URL).
  - Both tools run INSIDE this container, which has outbound internet (same as the
    hexstrike-server that fetches nuclei templates), so the orchestrator does not
    need internet inside its own sandbox.

Flow:
  Tiel -> web_search / fetch_url -> this MCP (:8004) -> SearXNG (self-hosted) / the web
                                 <- results / page text

env:
  SEARXNG_BASE        base URL of the SearXNG service (default http://searxng:8080)
  SEARCH_MAX_RESULTS  default number of results (default 8, hard cap 20)
  FETCH_MAX_CHARS     max characters returned by fetch_url (default 6000, cap 20000)
  HTTP_TIMEOUT        per-request timeout seconds (default 30)
  MCP_HOST / MCP_PORT host:port to bind (default 0.0.0.0:8004)
endpoint: http://<host>:<MCP_PORT>/mcp
"""
import html
import os
import re
import sys

import requests
from mcp.server.fastmcp import FastMCP

SEARXNG_BASE = os.environ.get("SEARXNG_BASE", "http://searxng:8080").rstrip("/")
MAX_RESULTS = int(os.environ.get("SEARCH_MAX_RESULTS", "8"))
FETCH_MAX_CHARS = int(os.environ.get("FETCH_MAX_CHARS", "6000"))
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
UA = "Mozilla/5.0 (pipeline-search-mcp)"


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8004"))

    mcp = FastMCP("search")

    @mcp.tool()
    def web_search(query: str, max_results: int = MAX_RESULTS) -> dict:
        """Search the web and return ranked results (title, url, snippet).

        Use this for open-ended lookups you cannot resolve from a URL you already
        know: CVE research, exploit techniques, default credentials, a product/
        version's behaviour, vendor advisories, config/file formats. Then call
        fetch_url on the most relevant hit for the full detail.

        This is for INFORMATION GATHERING only — it touches no engagement target.
        For anything inside the authorized scope, use the HexStrike tools instead.
        """
        if not query or not query.strip():
            return {"error": "query is required"}
        try:
            r = requests.get(
                f"{SEARXNG_BASE}/search",
                params={"q": query.strip(), "format": "json"},
                headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}",
                    "hint": f"is SearXNG up at {SEARXNG_BASE} with json format enabled?"}
        n = max(1, min(int(max_results or MAX_RESULTS), 20))
        results = [{"title": it.get("title", ""),
                    "url": it.get("url", ""),
                    "snippet": (it.get("content") or "")[:300]}
                   for it in (data.get("results") or [])[:n]]
        return {"query": query.strip(), "count": len(results), "results": results}

    @mcp.tool()
    def fetch_url(url: str, max_chars: int = FETCH_MAX_CHARS) -> dict:
        """Fetch a URL and return its text (HTML tags stripped, truncated).

        Use after web_search, or directly on a page you already know (an NVD/CVE
        page, exploit-db, official docs, a vendor advisory). Runs in-container, so
        it works even when your own sandbox has no internet.

        INFORMATION GATHERING only — never point this at an engagement target; use
        the HexStrike tools for anything that touches the authorized scope.
        """
        if not url or not url.strip():
            return {"error": "url is required"}
        u = url.strip()
        if not u.startswith(("http://", "https://")):
            return {"error": "url must start with http:// or https://"}
        try:
            r = requests.get(u, headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
        ctype = r.headers.get("Content-Type", "")
        body = _strip_html(r.text) if "html" in ctype.lower() else r.text
        lim = max(500, min(int(max_chars or FETCH_MAX_CHARS), 20000))
        return {"url": u, "status": r.status_code, "content_type": ctype,
                "truncated": len(body) > lim, "content": body[:lim]}

    # host/port + disable DNS-rebinding protection (internal compose service only —
    # same reasoning as specialist_mcp_http.py / memory_mcp_http.py)
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False)
    except Exception as e:
        print(f"[search-mcp] WARN: could not set transport_security ({e})",
              file=sys.stderr)

    print(f"[search-mcp] serving at http://{host}:{port}/mcp "
          f"— SearXNG={SEARXNG_BASE}", file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
