#!/usr/bin/env python3
"""
shot tool pack — web screenshot / evidence capture (router side)
=============================================================================
Thin proxy the hexstrike router exposes as `web_screenshot`. It POSTs to the
`shot` service (shot_server.py, Playwright+Chromium in its own container) which
saves a PNG into /evidence. The browser lives in the shot container, NOT in the
slim router image — the router only forwards an HTTP request here.

Tiel calls it via the hexstrike router:
    hexstrike_run("web_screenshot", {"url": "http://host.docker.internal:18056/",
                                      "out": "lab_home.png"})

env: SHOT_URL (default http://shot:9000)
"""
import inspect
import json
import os
import urllib.request

SHOT_URL = os.environ.get("SHOT_URL", "http://shot:9000")


def web_screenshot(
    url: str,
    out: str = "",
    full_page: bool = True,
    wait_until: str = "load",
    wait_selector: str = "",
    timeout_ms: int = 20000,
    width: int = 1280,
    height: int = 800,
) -> str:
    """[EVIDENCE] Headless-Chromium screenshot of a URL, saved into /evidence.

    Renders `url` in headless Chromium (via the shot service) and writes a PNG to
    /evidence/<out> — the shared mount the TLP report assembler reads. Use it to
    capture visual evidence of a finding (a vulnerable page, an RCE proof page, a
    login screen). Authorized in-scope targets only.

    Args:
      url: page to capture (e.g. http://host.docker.internal:18056/).
      out: output filename under /evidence (sanitized, .png forced; default auto).
      full_page: capture the full scrollable page (True) or just the viewport.
      wait_until: 'load' | 'domcontentloaded' | 'networkidle' | 'commit'.
      wait_selector: optional CSS selector to wait for before shooting.
      timeout_ms: navigation/selector timeout.
      width/height: viewport size.

    Returns the saved path, HTTP status and page <title>, or an error line.
    Redact secrets/tokens visible on the page before citing the image in a report.
    """
    payload = {
        "url": url, "out": out, "full_page": full_page,
        "wait_until": wait_until, "wait_selector": wait_selector,
        "timeout_ms": timeout_ms, "width": width, "height": height,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SHOT_URL.rstrip("/") + "/screenshot", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(timeout_ms) / 1000 + 30) as r:
            res = json.loads(r.read())
    except Exception as e:
        return (f"ERROR: could not reach shot service at {SHOT_URL} "
                f"({type(e).__name__}: {e}). Is the 'shot' container up (profile full)?")
    if not res.get("ok"):
        return f"screenshot FAILED: {res.get('error', 'unknown error')}"
    return (f"saved {res['path']} (status={res.get('status')}, "
            f"title={res.get('title')!r}, {res.get('bytes')} bytes)")


TOOLS = [web_screenshot]
DISPATCH = {fn.__name__: fn for fn in TOOLS}

_PY_JSON_TYPE = {int: "integer", bool: "boolean", float: "number", str: "string"}


def json_schema(fn) -> dict:
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        entry = {"type": _PY_JSON_TYPE.get(p.annotation, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
        else:
            entry["default"] = p.default
        props[name] = entry
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def catalog_entries():
    """Yield (name, description, parameters-schema, callable) for every tool."""
    for fn in TOOLS:
        yield (fn.__name__, (fn.__doc__ or "").strip(), json_schema(fn), fn)
