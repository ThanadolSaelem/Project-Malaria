#!/usr/bin/env python3
"""
Observer dashboard — สรุปงานของ Tiel แบบ real-time (EN + TH) + แจ้งเตือน credential/critical
=============================================================================
รันบน host (ไม่กวน Tiel / ไม่ใช่ tool ของมัน). ทุก INTERVAL วินาที:
  1) อ่านกิจกรรมล่าสุด: `docker logs hexstrike-server` (ทำอะไรอยู่)
     + memory.json จาก memory-mcp (ได้อะไรบ้าง)
  2) ส่งให้โมเดลเล็ก `summarizer` (Qwen2.5-3B ผ่าน LiteLLM) สรุปเป็น EN + TH
  3) สแกน keyword หา credential / critical → ขึ้น alert
  4) เสิร์ฟ dashboard ที่ http://localhost:<PORT> (auto-refresh)

env (override ได้):
  SUMMARIZER_BASE   default http://localhost:4000/v1   (LiteLLM)
  SUMMARIZER_MODEL  default summarizer
  LITELLM_API_KEY   default sk-local
  WATCH_INTERVAL    วินาทีต่อรอบ (default 45)
  WATCH_PORT        พอร์ต dashboard (default 8005)
  HEXSTRIKE_CONTAINER  default pipeline-hexstrike-server-1
  MEMORY_CONTAINER     default pipeline-memory-mcp-1
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ.get("SUMMARIZER_BASE", "http://localhost:4000/v1").rstrip("/")
MODEL = os.environ.get("SUMMARIZER_MODEL", "summarizer")
KEY = os.environ.get("LITELLM_API_KEY", "sk-local")
INTERVAL = int(os.environ.get("WATCH_INTERVAL", "45"))
PORT = int(os.environ.get("WATCH_PORT", "8005"))
HEXSTRIKE = os.environ.get("HEXSTRIKE_CONTAINER", "pipeline-hexstrike-server-1")
MEMORY = os.environ.get("MEMORY_CONTAINER", "pipeline-memory-mcp-1")

# ── keyword alerts (สแกนบน log ดิบ) ──────────────────────────────────────────
CRED_RE = re.compile(
    r"(?i)(valid (?:password|credential|login)|login (?:successful|succeeded)|"
    r"password found|credentials?\s*[:=]|\badmin:\S+|\broot:\S+|"
    r"\[\d+\]\[\w+\]\s+host:.*login:.*password:|\$[0-9a-z]{1,3}\$[^\s]{6,})")
CRIT_RE = re.compile(
    r"(?i)(\[critical\]|severity[\"'\s:=]+critical|\bRCE\b|remote code execution|"
    r"unauthenticated\s+\w+\s+execution|sql injection.*(dump|--os-shell))")

STATE = {
    "updated": None, "en": "(กำลังเริ่ม…)", "th": "(กำลังเริ่ม…)",
    "alerts": [], "timeline": [], "online": False,
}
_LOCK = threading.Lock()
_seen_alerts = set()

SYS_PROMPT = (
    "You are a real-time monitoring assistant for an AUTHORIZED penetration test. "
    "You are given recent tool logs and the operator's recorded findings. Summarize "
    "for a human watching a dashboard: what the agent is doing now, how far it has "
    "got, and what it has found so far. Be concise and factual — do not invent "
    "anything not present in the input. Respond with ONLY a JSON object: "
    '{"en": "<3-5 short English lines>", "th": "<สรุปภาษาไทย 2-4 ประโยค>"} — '
    "no markdown, no extra text.")


def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"[watch] cannot run {' '.join(cmd)}: {e}"


def gather_context():
    logs = _run(["docker", "logs", "--since", f"{INTERVAL * 4}s", "--tail", "200", HEXSTRIKE])
    mem_raw = _run(["docker", "exec", MEMORY, "cat", "/data/memory.json"])
    mem = ""
    try:
        d = json.loads(mem_raw)
        ents = d.get("entities", d) if isinstance(d, dict) else d
        mem = json.dumps(ents, ensure_ascii=False)[-2500:]
    except Exception:
        mem = mem_raw[-2000:]
    return logs[-4500:], mem


def call_summarizer(logs, mem):
    user = (f"## Recent tool activity (hexstrike-server log)\n{logs or '(none)'}\n\n"
            f"## Recorded findings (memory)\n{mem or '(none)'}")
    body = json.dumps({"model": MODEL, "messages": [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": user}],
        "temperature": 0.2, "max_tokens": 700}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = json.load(r)["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            o = json.loads(m.group(0))
            return str(o.get("en", "")).strip(), str(o.get("th", "")).strip()
        except Exception:
            pass
    return txt.strip(), txt.strip()


def scan_alerts(logs):
    new = []
    for line in logs.splitlines():
        line = line.strip()
        if not line:
            continue
        lvl = "credential" if CRED_RE.search(line) else ("critical" if CRIT_RE.search(line) else None)
        if not lvl:
            continue
        key = lvl + "|" + line[:160]
        if key in _seen_alerts:
            continue
        _seen_alerts.add(key)
        new.append({"level": lvl, "time": datetime.now().strftime("%H:%M:%S"),
                    "text": line[:300]})
    return new


def loop():
    while True:
        try:
            logs, mem = gather_context()
            en, th = call_summarizer(logs, mem)
            new_alerts = scan_alerts(logs)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with _LOCK:
                STATE["updated"], STATE["en"], STATE["th"], STATE["online"] = now, en, th, True
                STATE["timeline"] = ([{"time": now, "en": en}] + STATE["timeline"])[:30]
                if new_alerts:
                    STATE["alerts"] = (new_alerts + STATE["alerts"])[:50]
        except Exception as e:
            with _LOCK:
                STATE["online"] = False
                STATE["en"] = f"(summarizer unreachable: {e})"
        time.sleep(INTERVAL)


INDEX_HTML = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pentest Monitor</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mut:#8b949e;--red:#f85149;--amber:#d29922;--grn:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(--grn)}.dot.off{background:var(--red)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:720px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:13px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin:0 0 8px}
.body{white-space:pre-wrap}
.alerts{margin:14px 0}.alert{border-left:3px solid var(--amber);background:#1c1a10;padding:8px 12px;border-radius:6px;margin-bottom:8px}
.alert.credential{border-color:var(--red);background:#2a1215}.alert .tag{font-weight:700;margin-right:8px}
.alert.credential .tag{color:var(--red)}.alert.critical .tag{color:var(--amber)}.alert .t{color:var(--mut);font-size:12px}
.tl{margin-top:14px}.tl .row{border-top:1px solid var(--line);padding:8px 0;font-size:13px}.tl .t{color:var(--mut);font-size:12px}
.empty{color:var(--mut)}
</style></head><body>
<h1><span id="dot" class="dot"></span>Pentest Monitor <span style="color:var(--mut);font-weight:400">— Tiel</span></h1>
<div class="sub">อัปเดตล่าสุด: <span id="upd">—</span> · auto-refresh</div>
<div id="alerts" class="alerts"></div>
<div class="grid">
  <div class="card"><h2>🇬🇧 Summary (EN)</h2><div id="en" class="body empty">…</div></div>
  <div class="card"><h2>🇹🇭 สรุป (ไทย)</h2><div id="th" class="body empty">…</div></div>
</div>
<div class="card tl"><h2>Timeline</h2><div id="tl"></div></div>
<script>
async function tick(){
 try{const s=await (await fetch('/state',{cache:'no-store'})).json();
  document.getElementById('dot').className='dot'+(s.online?'':' off');
  document.getElementById('upd').textContent=s.updated||'—';
  document.getElementById('en').textContent=s.en||'—';document.getElementById('en').className='body';
  document.getElementById('th').textContent=s.th||'—';document.getElementById('th').className='body';
  document.getElementById('alerts').innerHTML=(s.alerts||[]).map(a=>
   `<div class="alert ${a.level}"><span class="tag">${a.level==='credential'?'🔑 CREDENTIAL':'🚨 CRITICAL'}</span><span class="t">${a.time}</span><div>${esc(a.text)}</div></div>`).join('');
  document.getElementById('tl').innerHTML=(s.timeline||[]).map(r=>
   `<div class="row"><span class="t">${r.time}</span><div>${esc(r.en)}</div></div>`).join('')||'<div class="empty">—</div>';
 }catch(e){document.getElementById('dot').className='dot off';}
}
function esc(t){const d=document.createElement('div');d.textContent=t||'';return d.innerHTML;}
tick();setInterval(tick,5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            with _LOCK:
                payload = json.dumps(STATE, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            page = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)


def main():
    threading.Thread(target=loop, daemon=True).start()
    print(f"[watch] dashboard: http://localhost:{PORT}  (summarizer={MODEL} via {BASE}, "
          f"every {INTERVAL}s)", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
