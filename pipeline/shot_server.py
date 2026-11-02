#!/usr/bin/env python3
"""
shot — headless web screenshot/evidence service (Playwright + Chromium)
=============================================================================
Tiny HTTP service the hexstrike router proxies to (tool: web_screenshot). Runs
headless Chromium via Playwright (which bundles a matching arm64/amd64 build, so
it works on Apple Silicon where Selenium+ChromeDriver is fragile) and saves PNG
evidence into /evidence — the shared bind mount the report assembler reads.

Why a separate container: keeps the browser out of the slim hexstrike-mcp image
(shared by memory/search/specialist). The router stays thin and calls us over HTTP.

POST /screenshot  {url, out?, full_page?, wait_until?, wait_selector?,
                   timeout_ms?, width?, height?, headers?}
                  -> {ok, path, status, title, bytes} | {ok:false, error}
GET  /healthz     -> 200 ok

env: SHOT_HOST (0.0.0.0), SHOT_PORT (9000), OUT_DIR (/evidence),
     CHROME_PATH (optional explicit chromium binary; default = Playwright's)
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT_DIR = os.environ.get("OUT_DIR", "/evidence")
CHROME_PATH = os.environ.get("CHROME_PATH", "") or None
# local vision model (Qwen2.5-VL via LiteLLM) — used when describe=True so a
# text-only orchestrator gets the page's actual content. Local = no cloud leak.
LITELLM_BASE = os.environ.get("LITELLM_BASE", "http://litellm:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "sk-local")
VISION_MODEL = os.environ.get("VISION_MODEL", "vision")
_DESCRIBE_PROMPT = (
    "You are reading a screenshot of a web page during an authorized security "
    "assessment. Describe FACTUALLY what this page is so a text-only operator can "
    "decide how to test it. State: (1) page type (login/auth form, dashboard, "
    "landing, error/404, API/JSON, game, file listing, admin panel, ...); "
    "(2) every visible form field, button, and link label; (3) any version / "
    "framework / technology hints or banners; (4) notable text. Be concise and "
    "literal — do not speculate beyond what is visible."
)
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str) -> str:
    """Reduce to a safe basename ending in .png, under OUT_DIR only."""
    base = os.path.basename(name or "").strip() or f"shot_{int(time.time())}.png"
    base = _SAFE.sub("_", base)
    if not base.lower().endswith(".png"):
        base += ".png"
    return base


def describe_image(path: str, prompt: str = "") -> str:
    """Ask the LOCAL vision model (via LiteLLM) to describe a screenshot. Returns
    the description text, or an 'ERROR: ...' string (never raises). Local only —
    the image never leaves this stack."""
    try:
        raw = open(path, "rb").read()
        uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        body = json.dumps({
            "model": VISION_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": uri}},
                {"type": "text", "text": prompt or _DESCRIBE_PROMPT},
            ]}],
            "temperature": 0.1, "max_tokens": 1024,
        }).encode()
        req = urllib.request.Request(
            LITELLM_BASE.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {LITELLM_KEY}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: vision describe failed ({type(e).__name__}: {e})"


def capture(url: str, out: str = "", full_page: bool = True,
            wait_until: str = "load", wait_selector: str = "",
            timeout_ms: int = 20000, width: int = 1280, height: int = 800,
            headers: dict | None = None, describe: bool = False,
            describe_prompt: str = "") -> dict:
    """Screenshot `url` to OUT_DIR/<out>. Returns a result dict. Pure function so
    it can be unit-tested outside the container. When describe=True, also runs the
    local vision model on the PNG and includes a 'description' field."""
    from playwright.sync_api import sync_playwright

    name = _safe_name(out)
    path = os.path.join(OUT_DIR, name)
    os.makedirs(OUT_DIR, exist_ok=True)

    launch = {"headless": True,
              "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if CHROME_PATH:
        launch["executable_path"] = CHROME_PATH

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        try:
            ctx = browser.new_context(
                viewport={"width": int(width), "height": int(height)},
                ignore_https_errors=True,
                extra_http_headers=headers or {},
            )
            page = ctx.new_page()
            resp = page.goto(url, wait_until=wait_until, timeout=int(timeout_ms))
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=int(timeout_ms))
            title = page.title()
            page.screenshot(path=path, full_page=bool(full_page))
            status = resp.status if resp else None
        finally:
            browser.close()

    result = {
        "ok": True,
        "path": path,
        "status": status,
        "title": title,
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
    }
    if describe:
        result["description"] = describe_image(path, describe_prompt)
    return result


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/healthz", "/health"):
            self._send(200, {"ok": True, "service": "shot"})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/screenshot":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, {"ok": False, "error": f"bad json: {e}"})
            return
        url = req.get("url")
        if not url:
            self._send(400, {"ok": False, "error": "missing 'url'"})
            return
        try:
            result = capture(
                url=url,
                out=req.get("out", ""),
                full_page=req.get("full_page", True),
                wait_until=req.get("wait_until", "load"),
                wait_selector=req.get("wait_selector", ""),
                timeout_ms=req.get("timeout_ms", 20000),
                width=req.get("width", 1280),
                height=req.get("height", 800),
                headers=req.get("headers") or {},
                describe=req.get("describe", False),
                describe_prompt=req.get("describe_prompt", ""),
            )
            self._send(200, result)
        except Exception as e:
            self._send(200, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def log_message(self, *a):  # quiet
        pass


def main():
    host = os.environ.get("SHOT_HOST", "0.0.0.0")
    port = int(os.environ.get("SHOT_PORT", "9000"))
    print(f"[shot] serving on http://{host}:{port}  (OUT_DIR={OUT_DIR})",
          file=sys.stderr)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
