#!/usr/bin/env python3
"""
Project-Malaria — Headless n8n Backend Bridge & Dual-Brain Relay Engine (:8010)
=============================================================================
ไม่มีหน้า Dashboard แยก (ทุกอย่างทำผ่านผังโหนดใน n8n จริงที่ http://localhost:5678):
  1) Dual-Brain Auto-Relay & Watchdog Engine (/api/relay/*):
     - ประสานงานระหว่าง 2 โมเดลใน Session เดียวกัน:
         • Brain A: Orchestrator (:8090) — Coding, Scripting & Report Synthesis
         • Brain B: Cyber-Model (:8091) — Cyber Security, WSTG, Recon, Pentest & Exploitation
     - Hybrid Task Dispatcher: ใช้ป้าย Handover + โมเดลเล็ก summarizer (:8092) + กฎวิเคราะห์งาน
       เพื่อตัดสินว่าก้าวต่อไปต้องส่งให้ Cyber-Model หรือ Orchestrator
     - Anti-Stall Completion Gate: บังคับตรวจ Checklist + ตรวจไฟล์จริงบนดิสก์ (/evidence, /reports)
       ถ้า AI หยุดพูดไปเองกลางคัน ระบบจะคืนค่า is_done=false เพื่อให้โหนด IF ใน n8n วนลูปกระตุ้นต่ออัตโนมัติ
     - Cross-Brain Rescue: ถ้าโมเดลตัวเดิมติด Error หรือย่ำอยู่กับที่ครบ 2 รอบ จะสลับให้อีกตัวมาแก้ทางทันที
  2) REST Tool & Config Bridge (/api/bridge/*, /api/node/*, /api/topology):
     - ให้โหนดใน n8n สั่งเปิด/ปิด Tool-RAG, ถอด/เสียบปลั๊กอิน (php2shell, shot, vflat, reporting),
       ซิงก์ไฟล์ config และสั่ง Start/Stop/Restart บริการทั้งหมดได้จากใน n8n โดยตรง
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAC_DIR = HERE / "mac"
LOGS_DIR = MAC_DIR / "logs"
NODE_CONFIG_FILE = HERE / "node-config.json"
LITELLM_CONFIG_FILE = HERE / "litellm-config.yaml"
CORDIS_PATCH_FILE = HERE / "deepseek-harness" / "cordis.patch.yml"
QWEN_SETTINGS_FILE = HERE / "qwen-code" / "settings.json"
RELAY_STATE_FILE = HERE / "dsh-workspace" / "relay_session.json"

CONTROL_HOST = os.environ.get("CONTROL_HOST", "0.0.0.0")
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "8010"))

for _extra_p in ("/opt/homebrew/bin", "/usr/local/bin", "/Applications/Docker.app/Contents/Resources/bin"):
    if _extra_p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{_extra_p}:{os.environ.get('PATH', '')}"

sys.path.insert(0, str(HERE))
_LOCK = threading.Lock()


def load_node_config() -> dict:
    with _LOCK:
        try:
            with open(NODE_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def save_node_config(cfg: dict) -> None:
    cfg["updated_at"] = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    with _LOCK:
        tmp = NODE_CONFIG_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, NODE_CONFIG_FILE)


# ── Auto-Sync Generators (litellm-config.yaml & cordis.patch.yml) ───────────

def sync_litellm_config(cfg: dict) -> str:
    models = cfg.get("models") or {}
    gw = (cfg.get("gateway") or {}).get("litellm") or {}
    timeout = int(gw.get("timeout", 1200))
    retries = int(gw.get("num_retries", 1))
    drop_params = "true" if gw.get("drop_params", True) else "false"

    lines = [
        "# =============================================================================",
        "# LiteLLM — AUTO-SYNCED BY PROJECT-MALARIA n8n BACKEND BRIDGE",
        "# =============================================================================",
        "",
        "model_list:",
    ]

    for mkey, m in models.items():
        if not m.get("enabled", True):
            continue
        aliases = m.get("aliases") or [m.get("alias") or mkey]
        target = m.get("target_model") or f"openai/{mkey}"
        api_base = m.get("api_base")
        api_key = m.get("api_key")
        api_key_env = m.get("api_key_env")

        lines.append(f"  # ---- {m.get('label', mkey)} ----")
        for alias in aliases:
            lines.append(f"  - model_name: {alias}")
            lines.append("    litellm_params:")
            lines.append(f"      model: {target}")
            if api_base:
                lines.append(f"      api_base: {api_base}")
            if api_key_env:
                lines.append(f"      api_key: os.environ/{api_key_env}")
            elif api_key:
                lines.append(f'      api_key: "{api_key}"')
            lines.append("")

    lines.extend([
        "general_settings:",
        "  dangerously_permit_weak_or_unset_master_key: true",
        "",
        "litellm_settings:",
        f"  drop_params: {drop_params}",
        "",
        "router_settings:",
        f"  timeout: {timeout}",
        f"  num_retries: {retries}",
    ])

    fallbacks = gw.get("fallbacks") or []
    if fallbacks:
        lines.append("  fallbacks:")
        for fb in fallbacks:
            if isinstance(fb, dict):
                for src, targets in fb.items():
                    t_list = ", ".join(f'"{t}"' for t in targets)
                    lines.append(f"    - {src}: [{t_list}]")

    content = "\n".join(lines) + "\n"
    with open(LITELLM_CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return str(LITELLM_CONFIG_FILE)


def sync_cordis_patch(cfg: dict) -> str:
    dsh = (cfg.get("harnesses") or {}).get("deepseek-harness") or {}
    default_model = dsh.get("default_model", "cybermodel")
    connected_mcps = dsh.get("connected_mcps") or []
    models = cfg.get("models") or {}
    mcps = cfg.get("mcp_servers") or {}

    lines = [
        "# =============================================================================",
        "# deepseek-harness config layer — AUTO-SYNCED BY n8n BACKEND BRIDGE",
        "# =============================================================================",
        "",
        "- id: llm-pi-ai",
        '  name: "@deepseek-ai/dsh-llm-pi-ai"',
        "  config:",
        "    providers:",
        "      litellm-local:",
        "        displayName: LiteLLM (local)",
        "        apiKeyEnv: LITELLM_KEY",
        "        api: openai-completions",
        "        baseURL: http://litellm:4000/v1",
        "        models:",
    ]

    exposed_count = 0
    for mkey, m in models.items():
        if not m.get("enabled", True):
            continue
        if m.get("expose_in_dsh", True):
            alias = m.get("alias") or mkey
            dname = (m.get("dsh_display_name") or m.get("label") or alias).replace('"', '\\"')
            lines.append(f"          - id: {alias}")
            lines.append(f'            name: "{dname}"')
            if m.get("supports_vision") or alias in ("cyber-model", "cyber-tiel", "vision", "nim", "n8n-dual-brain"):
                lines.append("            input: [text, image]")
            exposed_count += 1
    if exposed_count == 0:
        lines.append("          - id: orchestrator")
        lines.append("            name: orchestrator")

    lines.extend([
        "        compat:",
        "          supportsDeveloperRole: false",
        "          maxTokensField: max_tokens",
        "",
        "- id: agent-default-model",
        '  name: "@deepseek-ai/dsh-agent-default-model"',
        "  config:",
        "    provider: litellm-local",
        f"    model: {default_model}",
        "",
    ])

    active_mcp_rows = []
    for mcp_id in connected_mcps:
        m = mcps.get(mcp_id)
        if not m or not m.get("enabled", True):
            continue
        active_mcp_rows.append((mcp_id, m))

    if active_mcp_rows:
        lines.append("- insert:")
        for mcp_id, m in active_mcp_rows:
            url = m.get("internal_url") or f"http://{m.get('service', mcp_id + '-mcp')}:{m.get('port', 8001)}/mcp"
            timeout_ms = int(m.get("timeout_ms", 120000))
            lines.extend([
                f"    - id: mcp-{mcp_id}",
                '      name: "@deepseek-ai/dsh-mcp-client"',
                "      config:",
                f"        serverName: {mcp_id}",
                "        transport: streamable-http",
                f"        url: {url}",
                "        headers: {}",
                f"        toolCallTimeoutMs: {timeout_ms}",
                "        failOnStartupError: false",
            ])

    content = "\n".join(lines) + "\n"
    CORDIS_PATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CORDIS_PATCH_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return str(CORDIS_PATCH_FILE)


def sync_qwen_settings(cfg: dict) -> str:
    qw = (cfg.get("harnesses") or {}).get("qwen-code") or {}
    default_model = qw.get("default_model", "flint")
    connected_mcps = qw.get("connected_mcps") or ["hexstrike", "rea", "cve", "memory", "search", "specialist"]
    models = cfg.get("models") or {}
    mcps = cfg.get("mcp_servers") or {}

    openai_models = []
    seen_ids = {"flint", "orchestrator", "gpt-oss-120b"}

    orch_m = models.get("gpt-oss-120b") or {}
    orch_name = orch_m.get("dsh_display_name") or orch_m.get("label") or "Orchestrator (Coding & Synthesis)"
    openai_models.append({
        "id": default_model,
        "name": orch_name,
        "baseUrl": "http://litellm:4000/v1",
        "envKey": "OPENAI_API_KEY",
    })

    for mkey, m in models.items():
        if not m.get("enabled", True):
            continue
        alias = m.get("alias") or mkey
        if alias in seen_ids or mkey in seen_ids:
            continue
        seen_ids.add(alias)
        seen_ids.add(mkey)
        dname = m.get("dsh_display_name") or m.get("label") or alias
        openai_models.append({
            "id": alias,
            "name": dname,
            "baseUrl": "http://litellm:4000/v1",
            "envKey": "OPENAI_API_KEY",
        })

    mcp_servers = {}
    for mcp_id in connected_mcps:
        m = mcps.get(mcp_id)
        if m and not m.get("enabled", True):
            continue
        url = (m.get("internal_url") if m else None) or f"http://{mcp_id}-mcp:{m.get('port', 8001) if m else 8001}/mcp"
        mcp_servers[mcp_id] = {
            "httpUrl": url,
            "trust": True,
        }

    settings = {
        "$schema": "https://json.schemastore.org/qwen-settings.json",
        "modelProviders": {
            "openai": openai_models
        },
        "model": {
            "name": default_model
        },
        "mcpServers": mcp_servers,
        "security": {
            "auth": {
                "selectedType": "openai"
            }
        },
        "tools": {
            "approvalMode": "auto"
        },
        "experimental": {
            "agentTeam": True
        },
        "$version": 4
    }

    QWEN_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QWEN_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

    ws_qwen = HERE / "dsh-workspace" / ".qwen" / "settings.json"
    if ws_qwen.parent.exists():
        ws_settings = {k: v for k, v in settings.items() if k != "mcpServers"}
        with open(ws_qwen, "w", encoding="utf-8") as f:
            json.dump(ws_settings, f, ensure_ascii=False, indent=2)

    agents_src = HERE / "qwen-code" / "agents"
    ws_agents_dir = HERE / "dsh-workspace" / ".qwen" / "agents"
    if agents_src.is_dir():
        ws_agents_dir.mkdir(parents=True, exist_ok=True)
        for md_file in agents_src.glob("*.md"):
            shutil.copy2(md_file, ws_agents_dir / md_file.name)

    return str(QWEN_SETTINGS_FILE)


def sync_all_configs(cfg: dict) -> dict:
    save_node_config(cfg)
    p1 = sync_litellm_config(cfg)
    p2 = sync_cordis_patch(cfg)
    p3 = sync_qwen_settings(cfg)
    return {
        "ok": True,
        "synced_files": [str(NODE_CONFIG_FILE), p1, p2, p3],
        "updated_at": cfg.get("updated_at"),
    }


# ── Dual-Brain Auto-Relay & Watchdog Engine (Orchestrator ⇄ Cyber-Model) ────

def _call_llm_quick(model: str, system_prompt: str, user_prompt: str, max_tokens: int = 600, timeout: int = 25) -> str | None:
    """เรียกโมเดลผ่าน LiteLLM (:4000) หรือ llama-server ตรงๆ แบบมี timeout สั้น."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    endpoints = [
        "http://127.0.0.1:4000/v1/chat/completions",
        "http://litellm:4000/v1/chat/completions",
        "http://host.docker.internal:4000/v1/chat/completions",
    ]
    if model == "summarizer":
        endpoints.insert(0, "http://127.0.0.1:8092/v1/chat/completions")
        endpoints.append("http://127.0.0.1:8090/v1/chat/completions")
        endpoints.append("http://127.0.0.1:8091/v1/chat/completions")
    elif model in ("orchestrator", "flint", "gpt-oss-120b", "cybermodel", "qwen2.5-coder-32b", "qwen2.5-coder-14b", "qwen2.5-coder", "qwen"):
        endpoints.append("http://127.0.0.1:8090/v1/chat/completions")
    elif model in ("cyber-model", "cyber-tiel", "exploit-specialist"):
        endpoints.append("http://127.0.0.1:8091/v1/chat/completions")

    for url in endpoints:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer sk-local"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            return (d["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            continue
    return None


def _load_relay_state() -> dict:
    with _LOCK:
        try:
            with open(RELAY_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _save_relay_state(state: dict) -> None:
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    RELAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = RELAY_STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RELAY_STATE_FILE)


def _classify_intent_and_brain_llm(user_text: str, last_output: str = "") -> dict:
    """
    ใช้ LLM (summarizer :8092 หรือ fallback :8090/:8091) จำแนกเจตนา (Intent) และเลือกสมองโดยไม่พึ่งการดัก Keyword:
      - intent:
          1) 'conversational'     — ทักทาย, พูดคุยทั่วไป, ถามความรู้/ทฤษฎี, แปลภาษา, อธิบายแนวคิด (ไม่ต้องรัน Tool สแกน)
          2) 'direct_task'        — สั่งงานเดี่ยวที่ทำจบได้ในสมองเดียว (เช่น เขียนโค้ดชิ้นเดียว, รันคำสั่งเช็กจุดเดียว)
          3) 'continuous_mission' — ภารกิจต่อเนื่องหลายขั้นตอนที่ต้องสำรวจ/เจาะระบบและเขียนโค้ด/ทำรายงานร่วมกัน
      - brain: 'orchestrator' หรือ 'cyber-model'
      - reason: เหตุผลสั้นๆ
    """
    clean_txt = (user_text or "").strip()
    if not clean_txt:
        return {"intent": "conversational", "brain": "orchestrator", "reason": "empty_input"}

    sys_msg = (
        "You are an AI Intent Classifier and Task Router for a Dual-Brain system:\n"
        "- 'orchestrator': Master Architect, software engineering, coding/scripting (Python/Bash/JS), general Q&A, explanations, and report synthesis.\n"
        "- 'cyber-model': Offensive Cyber Security specialist, penetration testing, recon, vulnerability scanning, WSTG, CVE/vuln-intel lookup, and binary analysis.\n\n"
        "Classify the user's message into EXACTLY ONE intent:\n"
        "1. 'conversational': ONLY for short greetings (e.g. 'hello', 'hi', 'สวัสดี') or pure casual chitchat that needs NO tools and NO factual/CVE/web lookup.\n"
        "2. 'direct_task': Any request to search/find/look up information (e.g. 'หาข้อมูล CVE ใหม่...', 'find latest unpatched CVEs', web/OSINT lookup), write code/scripts, inspect files, or run a single check using tools.\n"
        "3. 'continuous_mission': A multi-step security/engineering mission requiring multiple phases or collaboration between both brains (e.g. 'scan target X for vulnerabilities, write a PoC exploit, and generate a report').\n\n"
        "Examples:\n"
        "- 'Hello' -> {\"intent\": \"conversational\", \"brain\": \"gpt-oss-120b\", \"reason\": \"greeting\"}\n"
        "- 'หาข้อมูล CVE ใหม่ที่ส่งผลกระทบเป็นวงกว้าง โดยฉันต้องการอันใหม่ล่าสุดและยังไม่มีการ patch' -> {\"intent\": \"direct_task\", \"brain\": \"cyber-tiel\", \"reason\": \"CVE and advisory lookup via tools\"}\n"
        "- 'เขียนสคริปต์ Python แปลงไฟล์ JSON เป็น CSV' -> {\"intent\": \"direct_task\", \"brain\": \"gpt-oss-120b\", \"reason\": \"single coding task\"}\n\n"
        "Respond with ONLY a valid JSON object:\n"
        "{\"intent\": \"conversational\" | \"direct_task\" | \"continuous_mission\", \"brain\": \"gpt-oss-120b\" | \"cyber-tiel\", \"reason\": \"short reason\"}"
    )
    user_prompt = f"User Message: {clean_txt}"
    if last_output:
        user_prompt += f"\nRecent Context: {last_output[-500:]}"

    # ใช้สมองใหญ่ (:8090/:8091) หรือ summarizer จำแนกเจตนา
    ans = _call_llm_quick("summarizer", sys_msg, user_prompt, max_tokens=160, timeout=10)
    if ans:
        try:
            j_match = re.search(r"\{.*\}", ans, re.S)
            if j_match:
                parsed = json.loads(j_match.group(0))
                raw_intent = str(parsed.get("intent") or "").lower().strip()
                if "mission" in raw_intent or "continuous" in raw_intent:
                    intent = "continuous_mission"
                elif "direct" in raw_intent or "single" in raw_intent or "task" in raw_intent:
                    intent = "direct_task"
                else:
                    intent = "conversational"

                raw_brain = str(parsed.get("brain") or "").lower().strip()
                brain = "cyber-model" if ("tiel" in raw_brain or "cyber" in raw_brain) else "orchestrator"
                reason = str(parsed.get("reason") or intent).strip()

                # ป้องกันโมเดลเล็ก (3B) จัดงานยาว/งานค้นหาไปเป็น conversational จนถูกตัด Tool ออก
                if intent == "conversational" and len(clean_txt) > 25:
                    intent = "direct_task"
                    reason = f"{reason} -> upgraded_to_direct_task_with_tools"

                return {"intent": intent, "brain": brain, "reason": f"llm_intent ({reason})"}
        except Exception:
            pass

    # กรณี LLM ทุกพอร์ตออฟไลน์ (เช่น รันเทสต์แบบไม่ต่อโมเดล) ให้ปลอดภัยไว้ก่อนโดยไม่เผลอเปิดสแกนจากข้อความสั้น
    if len(clean_txt) < 20:
        return {"intent": "conversational", "brain": "orchestrator", "reason": "offline_fallback_short"}
    return {"intent": "direct_task", "brain": "orchestrator", "reason": "offline_fallback"}


def _classify_with_hybrid(task_text: str, last_output: str = "") -> tuple[str, str]:
    """
    Task Dispatcher สำหรับเลือกสมอง (cyber-tiel vs gpt-oss-120b):
      1) เช็กป้ายส่งไม้ต่อชัดเจนจากคำตอบล่าสุด (HANDOVER_TO: cyber-tiel | gpt-oss-120b)
      2) ใช้ LLM Intent & Brain Classifier ประเมินเนื้อหางานโดยตรง
    """
    combined_last = last_output or ""
    m_handover = re.search(
        r"(?i)(?:HANDOVER_TO|NEXT_BRAIN|NEXT_AGENT)\s*[:=]\s*['\"]?(cyber-tiel|gpt-oss-120b|cyber|coding)['\"]?",
        combined_last,
    )
    if m_handover:
        raw_target = m_handover.group(1).lower()
        brain = "cyber-model" if "cyber" in raw_target or "tiel" in raw_target else "orchestrator"
        return brain, f"explicit_handover_tag ({raw_target})"

    res = _classify_intent_and_brain_llm(task_text, last_output)
    return res["brain"], res["reason"]


def _build_default_checklist(goal: str, target_url: str = "", require_report: bool = False) -> list[dict]:
    """สร้าง Checklist จากโจทย์จริงด้วย LLM (โดยตัด Timestamp ออกแล้ว)."""
    sys_msg = (
        "Break the user's explicit mission goal into 2 to 5 concrete, sequential checklist steps for two collaborating AI agents:\n"
        "- 'cyber-model': handles recon, scanning, vulnerability verification, CVE/REA analysis, evidence screenshots.\n"
        "- 'orchestrator': handles coding, writing custom Python/Bash scripts/PoCs, debugging, and final report synthesis.\n"
        "IMPORTANT: Only create steps that the user actually asked for. Ignore any timestamps or timezone strings.\n"
        "Output ONLY a JSON array of objects: "
        "[{\"id\": 1, \"title\": \"...\", \"owner\": \"cyber-tiel\" or \"gpt-oss-120b\"}]"
    )
    prompt = f"User Mission Goal: {goal}\nTarget: {target_url or 'As specified in goal'}\nRequire DOCX Report: {require_report}"
    ans = _call_llm_quick("summarizer", sys_msg, prompt, max_tokens=500, timeout=12)
    if ans:
        try:
            arr_match = re.search(r"\[.*\]", ans, re.S)
            if arr_match:
                items = json.loads(arr_match.group(0))
                if isinstance(items, list) and len(items) >= 1:
                    cleaned = []
                    for idx, it in enumerate(items, 1):
                        owner = str(it.get("owner", "")).lower()
                        owner = "orchestrator" if ("orch" in owner or "gpt" in owner or "cod" in owner) else "cyber-model"
                        cleaned.append({
                            "id": idx,
                            "title": str(it.get("title") or f"Step {idx}"),
                            "owner": owner,
                            "status": "pending",
                        })
                    return cleaned
        except Exception:
            pass

    cls_res = _classify_intent_and_brain_llm(goal)
    initial_owner = cls_res["brain"]
    other_owner = "orchestrator" if initial_owner in ("cyber-model", "cyber-tiel") else "cyber-model"
    steps = [
        {
            "id": 1,
            "title": f"ดำเนินการขั้นต้นตามโจทย์: {goal[:120]}",
            "owner": initial_owner,
            "status": "pending",
        },
        {
            "id": 2,
            "title": "พัฒนาสคริปต์/ตรวจสอบเชิงลึกร่วมกับผลลัพธ์จากขั้นตอนแรก",
            "owner": other_owner,
            "status": "pending",
        },
    ]
    if require_report:
        steps.append({
            "id": 3,
            "title": "เรียบเรียงผลลัพธ์และประกอบไฟล์รายงาน .docx ลงใน /reports",
            "owner": "orchestrator",
            "status": "pending",
        })
    return steps


def relay_init_session(body: dict) -> dict:
    """เริ่มต้น Session สำหรับวงจร Dual-Brain Auto-Relay."""
    raw_goal = (body.get("goal") or body.get("chatInput") or body.get("mission_goal") or "").strip()
    goal = _extract_clean_user_text(raw_goal) if "_extract_clean_user_text" in globals() else raw_goal
    if not goal:
        goal = "ตรวจสอบความปลอดภัยของเป้าหมายและสรุปผลพร้อมโค้ดทดสอบ"
    target_url = (body.get("target_url") or "").strip()
    max_iterations = int(body.get("max_iterations") or 30)
    require_report = bool(body.get("require_report_docx") or ("report" in goal.lower()) or ("รายงาน" in goal))

    custom_checklist = body.get("checklist")
    if isinstance(custom_checklist, list) and custom_checklist:
        checklist = custom_checklist
    else:
        checklist = _build_default_checklist(goal, target_url, require_report)

    session_id = body.get("session_id") or f"relay-{int(time.time())}"
    reports_dir = HERE / "reports"
    existing_docx = set(p.name for p in reports_dir.glob("*.docx")) if reports_dir.exists() else set()

    state = {
        "session_id": session_id,
        "goal": goal,
        "target_url": target_url,
        "max_iterations": max_iterations,
        "require_report_docx": require_report,
        "existing_docx_at_start": sorted(existing_docx),
        "turn": 0,
        "consecutive_stalls": 0,
        "last_brain": None,
        "last_output": "",
        "handover_note": "เริ่มต้นภารกิจใหม่",
        "checklist": checklist,
        "history": [],
        "is_done": False,
        "status": "running",
    }
    _save_relay_state(state)
    return {"ok": True, "session_id": session_id, "state": state}


def relay_dispatch_turn(body: dict) -> dict:
    """
    เลือกสมอง (cyber-tiel vs gpt-oss-120b) สำหรับรอบปัจจุบัน และสร้าง Prompt กระตุ้นอัตโนมัติ
    """
    state = _load_relay_state()
    if not state or (body.get("session_id") and body.get("session_id") != state.get("session_id")):
        init_res = relay_init_session(body)
        state = init_res["state"]

    state["turn"] = int(state.get("turn", 0)) + 1
    turn = state["turn"]
    checklist = state.get("checklist") or []
    pending = [item for item in checklist if item.get("status") != "done"]
    active_item = pending[0] if pending else {
        "id": len(checklist) + 1,
        "title": "ตรวจสอบความสมบูรณ์สุดท้ายและยืนยันหลักฐานทั้งหมด",
        "owner": "orchestrator",
        "status": "pending",
    }

    last_brain = state.get("last_brain")
    last_output = body.get("last_output") or state.get("last_output") or ""
    stalls = int(state.get("consecutive_stalls", 0))

    # 1. Cross-Brain Rescue if stalled or repeated errors >= 2
    if stalls >= 2 and last_brain in ("cyber-model", "cyber-tiel", "orchestrator", "gpt-oss-120b"):
        selected_brain = "orchestrator" if last_brain in ("cyber-model", "cyber-tiel") else "cyber-model"
        dispatch_reason = f"cross_brain_rescue (สลับสมองอัตโนมัติเนื่องจาก {last_brain} ติดหล่ม/ไม่คืบหน้า {stalls} รอบ)"
        state["consecutive_stalls"] = 0
    else:
        # 2. Hybrid Task Dispatcher
        task_desc = f"[Step {active_item.get('id')}] {active_item.get('title')} (Suggested owner: {active_item.get('owner')})"
        selected_brain, dispatch_reason = _classify_with_hybrid(task_desc, last_output)
        # If no explicit handover tag overrode it, respect the checklist item's designated specialist owner
        if dispatch_reason.startswith("offline_fallback") and active_item.get("owner") in ("cyber-model", "cyber-tiel", "orchestrator", "gpt-oss-120b"):
            selected_brain = active_item["owner"]
            dispatch_reason = f"checklist_owner ({selected_brain})"

    checklist_summary = "\n".join(
        f"  - [{'x' if it.get('status') == 'done' else ' '}] Step {it.get('id')}: {it.get('title')} (Owner: {it.get('owner')})"
        for it in checklist
    )

    partner_brain = "orchestrator" if selected_brain in ("cyber-model", "cyber-tiel") else "cyber-model"
    role_desc = (
        "คุณคือ **Cyber-Model (Brain B — Cyber Security & Pentest Specialist)** เชี่ยวชาญด้าน Offensive Security, "
        "Reconnaissance, WSTG, การใช้เครื่องมือ HexStrike / REA / CVE / Web Screenshot และการตรวจสอบช่องโหว่จริง"
        if selected_brain in ("cyber-model", "cyber-tiel")
        else "คุณคือ **Orchestrator (Brain A — Master Architect, Coding & Synthesis Specialist)** เชี่ยวชาญด้านการเขียนโค้ด Python/Bash/JS, "
             "การสร้างสคริปต์ Exploit/PoC, การแก้บั๊ก, การวิเคราะห์โครงสร้างระบบ และการประกอบรายงาน TLP:AMBER (.docx)"
    )

    agent_prompt = (
        f"=== DUAL-BRAIN AUTO-RELAY SESSION (Turn #{turn}/{state.get('max_iterations', 30)}) ===\n"
        f"{role_desc}\n"
        f"คุณกำลังทำงานร่วมกับพาร์ทเนอร์ของคุณคือ **{partner_brain}** ภายใน Session เดียวกัน\n\n"
        f"**เป้าหมายหลัก (Mission Goal)**: {state.get('goal')}\n"
        f"**Target URL**: {state.get('target_url') or '(ดูในรายละเอียดโจทย์)'}\n\n"
        f"**สถานะสมุดคุมงาน (Session Checklist)**:\n{checklist_summary}\n\n"
        f"**งานที่ต้องทำในรอบนี้ (Active Step #{active_item.get('id')})**:\n"
        f"- {active_item.get('title')}\n\n"
        f"**ข้อความส่งไม้ต่อจากรอบก่อนหน้า ({last_brain or 'System Init'})**:\n"
        f"{state.get('handover_note') or '(เพิ่งเริ่มรอบแรก)'}\n\n"
        f"**กติกาสำคัญ (ห้ามหยุดงานกลางคัน)**:\n"
        f"1. ลงมือเรียกใช้ Tool เพื่อทำงานใน Active Step #{active_item.get('id')} ให้สำเร็จจริง ห้ามพูดว่าจะทำเฉยๆ โดยไม่เรียก Tool\n"
        f"2. เมื่อทำงานในส่วนของคุณเสร็จแล้ว ให้ปิดท้ายคำตอบด้วยบล็อกส่งไม้ต่อตามรูปแบบนี้เสมอ:\n"
        f"   DONE_STEP: {active_item.get('id')} (ใส่หมายเลข Step ถ้าข้อนี้ทำสำเร็จครบถ้วนแล้ว หรือใส่ NONE ถ้ายังต้องทำข้อเดิมต่อ)\n"
        f"   HANDOVER_TO: cyber-tiel หรือ gpt-oss-120b (เลือกโมเดลที่เหมาะกับก้าวต่อไป: งานเจาะระบบ/สแกน=cyber-tiel, งานเขียนโค้ด/สคริปต์/ทำรายงาน=gpt-oss-120b)\n"
        f"   HANDOVER_NOTE: สรุปสิ่งที่ค้นพบ/ไฟล์ที่สร้างไว้ และสั่งงานก้าวต่อไปให้อีกโมเดลอย่างชัดเจน\n"
        f"   MISSION_STATUS: CONTINUE หรือ COMPLETE (ใส่ COMPLETE เฉพาะเมื่อ Checklist ทุกข้อเป็น [x] ครบหมดแล้วเท่านั้น)"
    )

    state["current_brain"] = selected_brain
    state["active_step_id"] = active_item.get("id")
    state["dispatch_reason"] = dispatch_reason
    _save_relay_state(state)

    return {
        "ok": True,
        "session_id": state["session_id"],
        "turn": turn,
        "selected_brain": selected_brain,
        "dispatch_reason": dispatch_reason,
        "active_step": active_item,
        "agent_prompt": agent_prompt,
        "checklist": checklist,
    }


def relay_complete_step(body: dict) -> dict:
    """
    รับผลลัพธ์จาก Agent ที่เพิ่งทำงานเสร็จ -> อัปเดต Checklist -> ตรวจ Completion Gate
    ถ้ายังไม่เสร็จ (แม้ AI จะหยุดพูดเอง) จะคืน is_done=False เพื่อให้ n8n วนลูปกระตุ้นตัวถัดไปทันที!
    """
    state = _load_relay_state()
    if not state:
        return {"ok": False, "error": "No active relay session"}

    agent_output = str(
        body.get("output")
        or body.get("text")
        or body.get("response")
        or body.get("agent_output")
        or ""
    ).strip()
    brain_used = body.get("brain") or state.get("current_brain") or "cyber-tiel"
    active_id = state.get("active_step_id")
    checklist = state.get("checklist") or []

    # Check if output looks stalled / empty / error
    is_stall = len(agent_output) < 25 or "error:" in agent_output.lower()[:120]
    if is_stall:
        state["consecutive_stalls"] = int(state.get("consecutive_stalls", 0)) + 1
    else:
        state["consecutive_stalls"] = 0

    # Parse DONE_STEP tag or auto-mark active step if substantial progress was made
    done_match = re.search(r"(?i)DONE_STEP\s*[:=]\s*(\d+|ALL)", agent_output)
    marked_any = False
    if done_match:
        val = done_match.group(1).upper()
        if val == "ALL":
            for it in checklist:
                it["status"] = "done"
            marked_any = True
        else:
            step_num = int(val)
            for it in checklist:
                if int(it.get("id", -1)) == step_num:
                    it["status"] = "done"
                    marked_any = True
    elif not is_stall and active_id is not None:
        # Even if model forgot DONE_STEP tag, advance active step so it doesn't get stuck repeating forever
        for it in checklist:
            if int(it.get("id", -1)) == int(active_id):
                it["status"] = "done"
                marked_any = True
                break

    # Extract handover note
    note_match = re.search(r"(?i)HANDOVER_NOTE\s*[:=]\s*(.+)", agent_output, re.S)
    if note_match:
        handover_note = note_match.group(1).strip()[:1500]
    else:
        handover_note = agent_output[-1200:] if agent_output else "(โมเดลหยุดตอบโดยไม่มีข้อความ — กระตุ้นต่ออัตโนมัติ)"

    state["last_brain"] = brain_used
    state["last_output"] = agent_output[-3000:]
    state["handover_note"] = f"[จาก {brain_used} ในรอบที่ #{state.get('turn')}]:\n{handover_note}"
    state.setdefault("history", []).append({
        "turn": state.get("turn"),
        "brain": brain_used,
        "step_id": active_id,
        "marked_done": marked_any,
        "output_preview": agent_output[:500],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
    })

    # ── Completion Gate & Anti-Stall Watchdog ────────────────────────────────
    pending = [it for it in checklist if it.get("status") != "done"]
    turn = int(state.get("turn", 1))
    max_iter = int(state.get("max_iterations", 30))

    # Check if DOCX artifact is required and actually created on disk
    missing_artifact = None
    if state.get("require_report_docx") and len(pending) == 0:
        reports_dir = HERE / "reports"
        current_docx = set(p.name for p in reports_dir.glob("*.docx")) if reports_dir.exists() else set()
        before_docx = set(state.get("existing_docx_at_start") or [])
        if not (current_docx - before_docx) and not current_docx:
            missing_artifact = "ยังตรวจไม่พบไฟล์รายงาน .docx ใน /reports — กรุณาใช้ Report Assembler สร้างไฟล์จริงก่อนจบงาน"
            # Re-open or add report verification step
            checklist.append({
                "id": len(checklist) + 1,
                "title": "สร้างไฟล์รายงาน .docx จริงลงใน /reports ด้วยเครื่องมือ assemble_tlp_report",
                "owner": "orchestrator",
                "status": "pending",
            })
            pending = [checklist[-1]]

    if len(pending) == 0 and not missing_artifact:
        is_done = True
        stop_reason = "all_checklist_steps_verified_complete"
        state["status"] = "completed"
    elif turn >= max_iter:
        is_done = True
        stop_reason = f"reached_safety_cap ({turn}/{max_iter} turns)"
        state["status"] = "stopped_max_iterations"
    else:
        is_done = False
        next_step = pending[0]
        stop_reason = (
            f"auto_continue: เหลืออีก {len(pending)} งานใน Checklist "
            f"(งานถัดไป: Step #{next_step.get('id')} -> {next_step.get('owner')})"
        )
        state["status"] = "running"

    state["is_done"] = is_done
    state["stop_reason"] = stop_reason
    _save_relay_state(state)

    return {
        "ok": True,
        "session_id": state.get("session_id"),
        "turn": turn,
        "brain_used": brain_used,
        "is_done": is_done,
        "stop_reason": stop_reason,
        "remaining_steps": len(pending),
        "checklist": checklist,
        "handover_note": state["handover_note"],
        "last_output": agent_output,
    }


# ── Live Health & Process/Docker Inspection ─────────────────────────────────

def _probe_port(host: str, port: int, timeout: float = 0.8) -> tuple[bool, int]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = int((time.monotonic() - t0) * 1000)
            return True, ms
    except Exception:
        return False, -1


def _probe_http(url: str, timeout: float = 1.2) -> tuple[bool, int, int]:
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ms = int((time.monotonic() - t0) * 1000)
            return True, r.status, ms
    except urllib.error.HTTPError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return True, e.code, ms
    except Exception:
        return False, 0, -1


def _docker_ps_status() -> dict[str, str]:
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.mac.yml", "--profile", "full", "ps", "--format", "json"],
            cwd=str(HERE),
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = {}
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, list):
                    for item in obj:
                        svc = item.get("Service") or item.get("Name")
                        if svc:
                            out[svc] = item.get("State", "unknown")
                elif isinstance(obj, dict):
                    svc = obj.get("Service") or item.get("Name")
                    if svc:
                        out[svc] = obj.get("State", "unknown")
            except Exception:
                continue
        return out
    except Exception:
        return {}


def collect_live_status(cfg: dict) -> dict:
    docker_states = _docker_ps_status()
    statuses: dict[str, dict] = {}
    probe_host = "127.0.0.1"

    for hid, h in (cfg.get("harnesses") or {}).items():
        port = int(h.get("port", 0))
        svc = h.get("service", hid)
        alive, ms = _probe_port(probe_host, port) if port else (False, -1)
        statuses[f"harness:{hid}"] = {
            "online": alive,
            "latency_ms": ms,
            "docker_state": docker_states.get(svc, "running" if alive else "stopped"),
            "port": port,
        }

    for gid, g in (cfg.get("gateway") or {}).items():
        port = int(g.get("port", 4000))
        svc = g.get("service", gid)
        alive, code, ms = _probe_http(f"http://{probe_host}:{port}/v1/models")
        statuses[f"gateway:{gid}"] = {
            "online": alive,
            "http_code": code,
            "latency_ms": ms,
            "docker_state": docker_states.get(svc, "running" if alive else "stopped"),
            "port": port,
        }

    for mid, m in (cfg.get("models") or {}).items():
        mtype = m.get("type", "local_llama")
        port = int(m.get("port", 0))
        if mtype == "local_llama" and port:
            alive, code, ms = _probe_http(f"http://{probe_host}:{port}/v1/models")
            statuses[f"model:{mid}"] = {
                "online": alive,
                "http_code": code,
                "latency_ms": ms,
                "port": port,
                "mode": "local_metal",
            }
        else:
            key_env = m.get("api_key_env", "")
            has_key = bool(os.environ.get(key_env))
            if not has_key and (HERE / ".env").exists():
                try:
                    env_txt = (HERE / ".env").read_text(encoding="utf-8", errors="ignore")
                    match = re.search(rf"^{re.escape(key_env)}=(.+)$", env_txt, re.M)
                    if match:
                        val = match.group(1).strip()
                        has_key = bool(val and "REPLACE_ME" not in val)
                except Exception:
                    pass
            statuses[f"model:{mid}"] = {
                "online": has_key and bool(m.get("enabled", True)),
                "latency_ms": 0,
                "mode": "cloud_api",
                "key_configured": has_key,
            }

    for mcp_id, m in (cfg.get("mcp_servers") or {}).items():
        port = int(m.get("port", 0))
        svc = m.get("service", f"{mcp_id}-mcp")
        alive, code, ms = _probe_http(f"http://{probe_host}:{port}/mcp") if port else (False, 0, -1)
        statuses[f"mcp:{mcp_id}"] = {
            "online": alive,
            "http_code": code,
            "latency_ms": ms,
            "docker_state": docker_states.get(svc, "running" if alive else "stopped"),
            "port": port,
        }

    for pid, p in (cfg.get("plugins") or {}).items():
        port = int(p.get("port", 0))
        svc = p.get("service", "")
        if port:
            alive, ms = _probe_port(probe_host, port)
            statuses[f"plugin:{pid}"] = {
                "online": alive,
                "latency_ms": ms,
                "docker_state": docker_states.get(svc, "running" if alive else "stopped"),
                "port": port,
            }
        else:
            hx_online = statuses.get("mcp:hexstrike", {}).get("online", False)
            statuses[f"plugin:{pid}"] = {
                "online": bool(p.get("enabled", True)) and hx_online,
                "latency_ms": 0,
                "mode": "embedded_pack",
            }

    for aid, a in (cfg.get("auxiliary_services") or {}).items():
        port = int(a.get("port", 0))
        svc = a.get("service", aid)
        alive, ms = _probe_port(probe_host, port) if port else (False, -1)
        statuses[f"aux:{aid}"] = {
            "online": alive,
            "latency_ms": ms,
            "docker_state": docker_states.get(svc, "running" if alive else "stopped"),
            "port": port,
        }

    return statuses


# ── Start / Stop / Restart Actions & Logs ───────────────────────────────────

def _compose_cmd() -> list[str]:
    cmd = ["docker", "compose", "-f", str(HERE / "docker-compose.yml")]
    if platform.system() == "Darwin" and (HERE / "docker-compose.mac.yml").exists():
        cmd.extend(["-f", str(HERE / "docker-compose.mac.yml")])
    cmd.extend(["--profile", "full"])
    return cmd


def _control_llama(model_id: str, action: str, port: int) -> dict:
    if action in ("stop", "restart"):
        subprocess.run(["pkill", "-f", f"llama-server.*--port {port}"], capture_output=True)
        time.sleep(1)
        if action == "stop":
            return {"ok": True, "message": f"Stopped llama-server on :{port}"}

    llama_env = MAC_DIR / "llama.env"
    if not llama_env.exists():
        return {"ok": False, "error": f"ไม่พบไฟล์ {llama_env} — กรุณาคัดลอกจาก llama.env.example ก่อน"}

    var_map = {
        "orchestrator": ("LLAMA_CMD", "llama.log"),
        "gpt-oss-120b": ("LLAMA_CMD", "llama.log"),
        "cybermodel": ("LLAMA_CMD", "llama.log"),
        "cyber-model": ("LLAMA_CMD_SPECIALIST", "llama-specialist.log"),
        "cyber-tiel": ("LLAMA_CMD_SPECIALIST", "llama-specialist.log"),
        "exploit-specialist": ("LLAMA_CMD_SPECIALIST", "llama-specialist.log"),
        "summarizer": ("LLAMA_CMD_SUMMARIZER", "llama-summarizer.log"),
        "vision": ("LLAMA_CMD_VISION", "llama-vision.log"),
    }
    cmd_var, log_name = var_map.get(model_id, ("", f"llama-{model_id}.log"))
    if not cmd_var:
        return {"ok": False, "error": f"Model {model_id} ไม่ใช่ local llama-server"}

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / log_name
    shell_cmd = f'source "{llama_env}" && eval "${{{cmd_var}:-}}"'
    subprocess.Popen(
        ["bash", "-c", shell_cmd],
        stdout=open(log_path, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"ok": True, "message": f"Started {model_id} on :{port} (log: pipeline/mac/logs/{log_name})"}


def execute_node_action(node_key: str, action: str) -> dict:
    cfg = load_node_config()
    kind, _, ident = node_key.partition(":")
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "error": f"Unsupported action: {action}"}

    if kind == "model":
        m = (cfg.get("models") or {}).get(ident) or {}
        if m.get("type") == "local_llama" or ident in ("gpt-oss-120b", "cybermodel", "cyber-tiel", "exploit-specialist"):
            port = int(m.get("port", 8091 if "tiel" in ident or "specialist" in ident else 8090))
            return _control_llama(ident, action, port)
        return {"ok": False, "error": "Cloud model ไม่ต้องรันโปรเซสบนเครื่อง"}

    if node_key == "aux:observer":
        port = int(((cfg.get("auxiliary_services") or {}).get("observer") or {}).get("port", 8005))
        if action in ("stop", "restart"):
            subprocess.run(["pkill", "-f", "summarize-watch.py"], capture_output=True)
            time.sleep(0.5)
            if action == "stop":
                return {"ok": True, "message": "Stopped observer dashboard"}
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOGS_DIR / "summarize-watch.log"
        subprocess.Popen(
            [sys.executable or "python3", str(MAC_DIR / "summarize-watch.py")],
            stdout=open(log_path, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return {"ok": True, "message": f"Started observer dashboard on :{port}"}

    service_map = {
        "harness:n8n": "n8n",
        "harness:qwen-code": "qwen-code",
        "harness:deepseek-harness": "qwen-code",
        "harness:harnessrouter": "qwen-code",
        "gateway:litellm": "litellm",
        "mcp:hexstrike": "hexstrike-mcp",
        "mcp:rea": "rea-mcp",
        "mcp:cve": "cve-mcp",
        "mcp:search": "search-mcp",
        "mcp:memory": "memory-mcp",
        "mcp:specialist": "specialist-mcp",
        "plugin:shot": "shot",
        "plugin:vflat": "vflat-scan",
        "aux:hexstrike-server": "hexstrike-server",
    }
    svc = service_map.get(node_key)
    if not svc:
        return {"ok": True, "message": f"Node {node_key} เป็นปลั๊กอินภายใน (ซิงก์ผ่าน node-config.json ทันที)"}

    base = _compose_cmd()
    if action == "start":
        cmd = base + ["up", "-d", svc]
    elif action == "stop":
        cmd = base + ["stop", svc]
    else:
        cmd = base + ["restart", svc]

    try:
        r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=120)
        output = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return {"ok": r.returncode == 0, "service": svc, "action": action, "output": output}
    except Exception as e:
        return {"ok": False, "service": svc, "action": action, "error": str(e)}


def fetch_node_logs(node_key: str, lines: int = 100) -> dict:
    log_files = {
        "model:orchestrator": LOGS_DIR / "llama.log",
        "model:gpt-oss-120b": LOGS_DIR / "llama.log",
        "model:cybermodel": LOGS_DIR / "llama.log",
        "model:cyber-model": LOGS_DIR / "llama-specialist.log",
        "model:cyber-tiel": LOGS_DIR / "llama-specialist.log",
        "model:exploit-specialist": LOGS_DIR / "llama-specialist.log",
        "model:summarizer": LOGS_DIR / "llama-summarizer.log",
        "model:vision": LOGS_DIR / "llama-vision.log",
        "aux:observer": LOGS_DIR / "summarize-watch.log",
    }
    if node_key in log_files:
        p = log_files[node_key]
        if not p.exists():
            return {"ok": True, "node": node_key, "logs": f"(ยังไม่มีไฟล์ log ที่ {p})"}
        try:
            content = p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            return {"ok": True, "node": node_key, "logs": "\n".join(content)}
        except Exception as e:
            return {"ok": False, "node": node_key, "logs": str(e)}

    service_map = {
        "harness:n8n": "n8n",
        "harness:qwen-code": "qwen-code",
        "harness:deepseek-harness": "qwen-code",
        "harness:harnessrouter": "qwen-code",
        "gateway:litellm": "litellm",
        "mcp:hexstrike": "hexstrike-mcp",
        "mcp:rea": "rea-mcp",
        "mcp:cve": "cve-mcp",
        "mcp:search": "search-mcp",
        "mcp:memory": "memory-mcp",
        "mcp:specialist": "specialist-mcp",
        "plugin:shot": "shot",
        "plugin:vflat": "vflat-scan",
        "aux:hexstrike-server": "hexstrike-server",
    }
    svc = service_map.get(node_key)
    if not svc:
        return {"ok": True, "node": node_key, "logs": f"Node {node_key} เป็นโมดูลภายใน hexstrike-mcp"}

    cmd = _compose_cmd() + ["logs", "--tail", str(lines), "--no-color", svc]
    try:
        r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=15)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return {"ok": True, "node": node_key, "service": svc, "logs": out or "(no log output yet)"}
    except Exception as e:
        return {"ok": False, "node": node_key, "logs": str(e)}


# ── REST Bridge for n8n Workflows (/api/bridge/*) ───────────────────────────

def _parse_mcp_body(raw_bytes: bytes) -> dict:
    txt = raw_bytes.decode("utf-8", errors="replace").strip()
    if not txt:
        return {}
    if txt.startswith("{"):
        try:
            return json.loads(txt)
        except Exception:
            pass
    # Parse SSE streamable-http format ("event: message\ndata: {...}")
    last_json = {}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload.startswith("{"):
                try:
                    last_json = json.loads(payload)
                except Exception:
                    pass
    return last_json


def _call_mcp_streamable_http(port: int, service: str, tool_name: str, arguments: dict, timeout: int = 180) -> dict:
    """เรียก MCP Server ที่ใช้ transport streamable-http (:8001, :8002, :8004, :8007, :8009) แทน n8n SSE."""
    urls = [
        f"http://127.0.0.1:{port}/mcp",
        f"http://{service}:{port}/mcp",
        f"http://host.docker.internal:{port}/mcp",
    ]
    base_Headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    init_body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "n8n-http-bridge", "version": "1.0"},
        },
    }).encode("utf-8")

    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(url, data=init_body, headers=dict(base_Headers), method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
                _ = r.read()

            call_headers = dict(base_Headers)
            if sid:
                call_headers["mcp-session-id"] = sid

            # Send initialized notification
            notif_body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
            try:
                req_n = urllib.request.Request(url, data=notif_body, headers=dict(call_headers), method="POST")
                with urllib.request.urlopen(req_n, timeout=5) as rn:
                    _ = rn.read()
            except Exception:
                pass

            # Call tool
            call_body = json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
            }).encode("utf-8")
            req_c = urllib.request.Request(url, data=call_body, headers=dict(call_headers), method="POST")
            with urllib.request.urlopen(req_c, timeout=timeout) as rc:
                resp_obj = _parse_mcp_body(rc.read())

            if "error" in resp_obj:
                return {"ok": False, "tool": tool_name, "error": resp_obj["error"]}
            res = resp_obj.get("result") or resp_obj
            if isinstance(res, dict) and "content" in res and isinstance(res["content"], list):
                texts = [c.get("text", "") for c in res["content"] if isinstance(c, dict) and c.get("type") == "text"]
                if texts:
                    joined = "\n".join(texts)
                    try:
                        return {"ok": not res.get("isError", False), "tool": tool_name, "result": json.loads(joined)}
                    except Exception:
                        return {"ok": not res.get("isError", False), "tool": tool_name, "result": joined}
            return {"ok": True, "tool": tool_name, "result": res}
        except Exception as e:
            last_err = e
            continue

    return {
        "ok": False,
        "tool": tool_name,
        "error": f"บริการ MCP ({service}:{port}) ยังไม่ได้เปิดใช้งานหรือติดต่อไม่ได้ ({last_err}) — สามารถข้ามไปใช้เครื่องมืออื่นต่อได้",
    }


def _parse_args_field(raw_args) -> dict:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def handle_bridge_call(tool_group: str, payload: dict) -> dict:
    cfg = load_node_config()
    plugins_cfg = cfg.get("plugins") or {}
    mcps_cfg = cfg.get("mcp_servers") or {}
    hx_plugins = (mcps_cfg.get("hexstrike") or {}).get("plugins") or {}

    if tool_group in ("hexstrike", "rea", "cve"):
        m_cfg = mcps_cfg.get(tool_group) or {}
        if not m_cfg.get("enabled", True):
            return {"ok": False, "error": f"MCP Node '{tool_group}' ถูกปิดไว้ในระบบ"}
        port = int(m_cfg.get("port", {"hexstrike": 8001, "rea": 8007, "cve": 8009}[tool_group]))
        svc = m_cfg.get("service", f"{tool_group}-mcp")
        action = str(payload.get("action") or "search").lower().strip()
        target = str(payload.get("query_or_tool") or payload.get("query") or payload.get("name") or payload.get("tool") or payload.get("keyword") or payload.get("cve_id") or "").strip()
        args = _parse_args_field(payload.get("arguments") or payload.get("args"))

        if action in ("search", "search_tools"):
            return _call_mcp_streamable_http(port, svc, f"{tool_group}_search_tools", {"query": target or "scan"})
        if action in ("describe", "describe_tool"):
            return _call_mcp_streamable_http(port, svc, f"{tool_group}_describe_tool", {"name": target})
        return _call_mcp_streamable_http(port, svc, f"{tool_group}_run", {"name": target, "arguments": args}, timeout=300)

    if tool_group == "memory":
        m_cfg = mcps_cfg.get("memory") or {}
        if not m_cfg.get("enabled", True):
            return {"ok": False, "error": "MCP Node 'memory' ถูกปิดไว้ในระบบ"}
        action = str(payload.get("action") or "search").lower().strip()
        if action == "add":
            obs = payload.get("observations")
            if isinstance(obs, str):
                obs = [x.strip() for x in obs.split("\n") if x.strip()] if "\n" in obs else [obs]
            return _call_mcp_streamable_http(8002, "memory-mcp", "memory_add", {
                "name": str(payload.get("name") or payload.get("query") or "finding"),
                "entity_type": str(payload.get("entity_type") or "finding"),
                "observations": obs or [],
            })
        if action == "relate":
            return _call_mcp_streamable_http(8002, "memory-mcp", "memory_relate", {
                "source": str(payload.get("source") or payload.get("name") or ""),
                "target": str(payload.get("target") or ""),
                "relation": str(payload.get("relation") or "related_to"),
            })
        if action == "read":
            return _call_mcp_streamable_http(8002, "memory-mcp", "memory_read", {"limit": int(payload.get("limit") or 50)})
        if action == "delete":
            return _call_mcp_streamable_http(8002, "memory-mcp", "memory_delete", {"name": str(payload.get("name") or "")})
        return _call_mcp_streamable_http(8002, "memory-mcp", "memory_search", {
            "query": str(payload.get("query") or payload.get("name") or ""),
            "limit": int(payload.get("limit") or 10),
        })

    if tool_group == "search":
        m_cfg = mcps_cfg.get("search") or {}
        if not m_cfg.get("enabled", True):
            return {"ok": False, "error": "MCP Node 'search' ถูกปิดไว้ในระบบ"}
        action = str(payload.get("action") or "web_search").lower().strip()
        q_or_u = str(payload.get("query_or_url") or payload.get("query") or payload.get("url") or "").strip()
        if action == "fetch_url" or q_or_u.startswith(("http://", "https://")):
            return _call_mcp_streamable_http(8004, "search-mcp", "fetch_url", {"url": q_or_u})
        return _call_mcp_streamable_http(8004, "search-mcp", "web_search", {"query": q_or_u})

    if tool_group == "screenshot":
        if not plugins_cfg.get("shot", {}).get("enabled", True) or not hx_plugins.get("shot", True):
            return {"ok": False, "error": "Plugin 'shot' (Web Screenshot) ถูกถอด/ปิดไว้"}
        import shot_tools
        res = shot_tools.web_screenshot(
            url=payload.get("url", ""),
            out=payload.get("out", ""),
            full_page=bool(payload.get("full_page", True)),
            describe=bool(payload.get("describe", False)),
            wait_until=payload.get("wait_until", "load"),
            wait_selector=payload.get("wait_selector", ""),
            timeout_ms=int(payload.get("timeout_ms", 20000)),
        )
        return {"ok": not res.startswith("ERROR"), "tool": "web_screenshot", "result": res}

    if tool_group == "vflat":
        if not plugins_cfg.get("vflat", {}).get("enabled", True) or not hx_plugins.get("vflat", True):
            return {"ok": False, "error": "Plugin 'vflat' (Document Scanner) ถูกถอด/ปิดไว้"}
        import vflat_tools
        res = vflat_tools.vflat_scan_document(
            image_path=payload.get("image_path", ""),
            out_filename=payload.get("out_filename", ""),
            dewarp=bool(payload.get("dewarp", True)),
            ocr_with_vision=bool(payload.get("ocr_with_vision", False)),
            vision_prompt=payload.get("vision_prompt", "อ่านทุกข้อความที่เห็นในภาพให้ครบ แล้วสรุปสาระสำคัญเป็นภาษาไทย"),
        )
        return {"ok": not res.startswith("ERROR"), "tool": "vflat_scan_document", "result": res}

    if tool_group == "vision":
        import vflat_tools
        res = vflat_tools.vision_read_image(
            image_path=payload.get("image_path", ""),
            prompt=payload.get("prompt", "อ่านทุกข้อความที่เห็นในภาพให้ครบ แล้วสรุปสาระสำคัญเป็นภาษาไทย"),
        )
        return {"ok": not res.startswith("ERROR"), "tool": "vision_read_image", "result": res}

    if tool_group == "php2shell":
        if not plugins_cfg.get("php2shell", {}).get("enabled", True) or not hx_plugins.get("php2shell", True):
            return {"ok": False, "error": "Plugin 'php2shell' ถูกถอด/ปิดไว้"}
        import php2shell_tools
        fn_name = payload.get("action") or payload.get("tool") or "php2shell_scan_vulnerability"
        fn = php2shell_tools.DISPATCH.get(fn_name)
        if not fn:
            return {"ok": False, "error": f"Unknown php2shell tool: {fn_name}", "available": list(php2shell_tools.DISPATCH)}
        args = payload.get("arguments") or {k: v for k, v in payload.items() if k not in ("action", "tool")}
        return {"ok": True, "tool": fn_name, "result": fn(**args)}

    if tool_group == "report":
        if not plugins_cfg.get("reporting", {}).get("enabled", True) or not hx_plugins.get("reporting", True):
            return {"ok": False, "error": "Plugin 'reporting' ถูกถอด/ปิดไว้"}
        import report_tools
        res = report_tools.assemble_tlp_report(
            report_name=payload.get("report_name", "assessment_report"),
            content_json=payload.get("content_json", ""),
            json_file_path=payload.get("json_file_path", ""),
        )
        return {"ok": res.startswith("OK:"), "tool": "assemble_tlp_report", "result": res}

    if tool_group == "specialist":
        spec_cfg = (cfg.get("mcp_servers") or {}).get("specialist") or {}
        if not spec_cfg.get("enabled", True):
            return {"ok": False, "error": "Node 'specialist' ถูกถอด/ปิดไว้"}
        task = payload.get("task", "")
        context = payload.get("context", "")
        model = payload.get("model") or spec_cfg.get("model", "cyber-tiel")
        from specialist_mcp_http import SPECIALIST_SYSTEM
        user_msg = task.strip()
        if context.strip():
            user_msg += "\n\n## Context\n" + context.strip()
        ans = _call_llm_quick(model, SPECIALIST_SYSTEM, user_msg, max_tokens=4096, timeout=600)
        if ans is not None:
            return {"ok": True, "model": model, "answer": ans}
        return {"ok": False, "error": f"ไม่สามารถติดต่อ LiteLLM (:4000) หรือโมเดล {model} (:8091) ได้"}

    return {"ok": False, "error": f"Unknown bridge tool_group: {tool_group}"}


# ── OpenAI-Compatible Bridge for DeepSeek Harness (:3080) ⇄ n8n (:5678) ─────

def _trigger_n8n_canvas_webhook(goal: str, target_url: str = "http://host.docker.internal:18056", max_iterations: int = 30) -> dict | None:
    """ยิงคำสั่งจากแชท DeepSeek Harness เข้า Webhook ของผัง n8n (0_Dual_Brain_Auto_Relay_Loop) โดยตรง."""
    payload = json.dumps({
        "goal": goal,
        "chatInput": goal,
        "target_url": target_url,
        "max_iterations": max_iterations,
    }).encode("utf-8")
    urls = [
        "http://127.0.0.1:5678/webhook/dsh-dual-brain",
        "http://n8n:5678/webhook/dsh-dual-brain",
        "http://host.docker.internal:5678/webhook/dsh-dual-brain",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1800) as r:
                raw = r.read().decode("utf-8", errors="replace").strip()
                if raw.startswith("{") or raw.startswith("["):
                    parsed = json.loads(raw)
                    if isinstance(parsed, list) and parsed:
                        parsed = parsed[0]
                    if isinstance(parsed, dict):
                        return parsed
                return {"output": raw}
        except Exception:
            continue
    return None


def _estimate_tokens(obj) -> int:
    """ประเมินจำนวนโทเคนคร่าวๆ จากความยาวข้อความ/JSON (เฉลี่ย ~3.2 ตัวอักษรต่อโทเคนสำหรับโค้ด+ไทย+อังกฤษ)."""
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj or "")
    return max(1, len(s) // 3)


def _group_atomic_turns(non_sys_messages: list[dict]) -> list[list[dict]]:
    """จัดกลุ่มข้อความเป็น Atomic Turn เพื่อไม่ให้ตัดแยกคู่ assistant (tool_calls) ออกจาก tool (tool_call_id)."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for m in non_sys_messages:
        role = m.get("role")
        if role == "user":
            if cur:
                groups.append(cur)
            cur = [m]
        elif role == "assistant":
            if cur and cur[-1].get("role") not in ("user",):
                groups.append(cur)
                cur = [m]
            else:
                cur.append(m)
        elif role == "tool":
            cur.append(m)
        else:
            cur.append(m)
    if cur:
        groups.append(cur)
    return groups


def _auto_compact_messages(
    messages: list[dict],
    tools: list[dict] | None = None,
    max_ctx: int = 32768,
    reserve_tokens: int = 4096,
    force: bool = False,
) -> list[dict]:
    """
    บีบอัดประวัติแชทอัตโนมัติ (Server-Side Auto-Compaction) ก่อนส่งเข้า llama-server:
      1) ย่อผลลัพธ์ Tool หรือข้อความเก่าที่ยาวเกินไปในเทิร์นก่อนหน้า
      2) หากจำนวนโทเคนรวม (System + Tools + Messages + Reserve) เกินเพดาน (หรือ force=True เมื่อชน HTTP 400)
         จะยุบเทิร์นเก่าเป็น [Auto-Compacted Session Summary] ด้วย summarizer (:8092) โดยรักษาคู่ tool_calls เสมอ
    """
    if not messages:
        return messages

    sys_msgs = [dict(m) for m in messages if m.get("role") == "system"]
    non_sys = [dict(m) for m in messages if m.get("role") != "system"]
    if len(non_sys) <= 1 and not force:
        return messages

    # ขั้นที่ 1: ย่อข้อความเก่าในประวัติที่ยาวผิดปกติ (เช่น ผลสแกนเก่า หรือข้อความที่เคยเจนค้างยาว 5,000 โทเคน)
    trimmed_non_sys = []
    for idx, m in enumerate(non_sys):
        mc = dict(m)
        is_recent = idx >= len(non_sys) - 2
        txt = _extract_text_from_msg_content(mc.get("content"))
        max_chars = 6000 if is_recent else 2200
        if txt and len(txt) > max_chars:
            head = txt[: int(max_chars * 0.65)]
            tail = txt[-int(max_chars * 0.25) :]
            mc["content"] = f"{head}\n...[auto-trimmed {len(txt) - len(head) - len(tail)} chars]...\n{tail}"
        trimmed_non_sys.append(mc)

    candidate = sys_msgs + trimmed_non_sys
    tools_tokens = _estimate_tokens(tools or [])
    total_est = _estimate_tokens(candidate) + tools_tokens + reserve_tokens

    if not force and total_est <= int(max_ctx * 0.85):
        return candidate

    # ขั้นที่ 2: ยุบกลุ่มเทิร์นเก่า (Atomic Turn Groups) เป็นบทสรุปย่อ
    groups = _group_atomic_turns(trimmed_non_sys)
    if len(groups) <= 1:
        return candidate

    keep_count = 1 if force else min(2, len(groups) - 1)
    old_groups = groups[:-keep_count]
    recent_groups = groups[-keep_count:]

    transcript_lines = []
    for g in old_groups:
        for m in g:
            r = m.get("role", "unknown")
            t = _extract_text_from_msg_content(m.get("content")).strip()
            if t:
                transcript_lines.append(f"[{r.upper()}]: {t[:600]}")
    raw_old = "\n".join(transcript_lines)[-6000:]

    summary_text = _call_llm_quick(
        "summarizer",
        (
            "You are a session context compactor. Summarize the earlier conversation turns concisely "
            "(key user goals, findings, targets, files created, and current status) in 5-8 bullet points. "
            "Keep technical details (URLs, CVEs, file paths) intact."
        ),
        raw_old or "No prior text.",
        max_tokens=450,
        timeout=12,
    )
    if not summary_text:
        summary_text = "\n".join(f"- {line[:220]}" for line in transcript_lines[-10:])

    compacted_note = (
        f"\n\n## [Auto-Compacted Earlier Session History ({len(old_groups)} turns compacted)]\n"
        f"{summary_text.strip()}\n"
    )
    if sys_msgs:
        sys_msgs[0] = dict(sys_msgs[0])
        sys_msgs[0]["content"] = _extract_text_from_msg_content(sys_msgs[0].get("content")) + compacted_note
    else:
        sys_msgs = [{"role": "system", "content": compacted_note.strip()}]

    recent_flat = [m for g in recent_groups for m in g]
    return sys_msgs + recent_flat


def _call_upstream_chat_completion(brain: str, body: dict, messages: list[dict]) -> dict | None:
    """เรียกโมเดลจริง (:8090 gpt-oss-120b หรือ :8091 cyber-tiel) แบบไม่จำกัด Output Token (-1 unlimited) พร้อม Auto-Compaction."""
    max_ctx = int(os.environ.get("LLAMA_CTX_MAIN", "65536"))
    tools_list = body.get("tools") or []

    compacted_messages = _auto_compact_messages(
        messages,
        tools=tools_list,
        max_ctx=max_ctx,
        reserve_tokens=4096,
        force=False,
    )

    req_payload = dict(body)
    # ถอดการจำกัด max_tokens ที่ DeepSeek Harness แนบมาออก และส่ง n_predict = -1 ตรงเข้า llama-server
    req_payload.pop("max_tokens", None)
    req_payload.pop("max_completion_tokens", None)
    req_payload["n_predict"] = -1
    req_payload["repeat_penalty"] = 1.12
    req_payload["model"] = "exploit-specialist" if brain in ("cyber-model", "cyber-tiel", "exploit-specialist") else "cybermodel"
    req_payload["messages"] = compacted_messages
    req_payload["stream"] = False  # รับก้อนเต็มมาตรวจ Checklist/Handover ก่อนแปลงเป็น SSE ส่งกลับ DeepSeek Harness

    # ยิงตรงเข้า llama-server (:8090 / :8091) ก่อนเป็นอันดับแรก เพื่อไม่ให้ LiteLLM (:4000) ตัดพารามิเตอร์ n_predict=-1 ทิ้ง
    if brain in ("cyber-model", "cyber-tiel", "exploit-specialist"):
        endpoints = [
            "http://127.0.0.1:8091/v1/chat/completions",
            "http://host.docker.internal:8091/v1/chat/completions",
            "http://127.0.0.1:4000/v1/chat/completions",
            "http://litellm:4000/v1/chat/completions",
        ]
    else:
        endpoints = [
            "http://127.0.0.1:8090/v1/chat/completions",
            "http://host.docker.internal:8090/v1/chat/completions",
            "http://127.0.0.1:4000/v1/chat/completions",
            "http://litellm:4000/v1/chat/completions",
        ]

    for attempt in range(2):
        raw_data = json.dumps(req_payload, ensure_ascii=False).encode("utf-8")
        hit_ctx_overflow = False
        for url in endpoints:
            try:
                req = urllib.request.Request(
                    url,
                    data=raw_data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer sk-local",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=900) as r:
                    return json.loads(r.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                if e.code == 400 and ("exceeds the available context size" in err_body or "context" in err_body.lower()):
                    hit_ctx_overflow = True
                    break
                continue
            except Exception:
                continue

        if hit_ctx_overflow and attempt == 0:
            # กรณีชนเพดาน Context ของ llama-server ให้บังคับ Auto-Compact ขั้นสูงสุดแล้วลองใหม่ทันทีโดยยังเปิด n_predict = -1
            req_payload["messages"] = _auto_compact_messages(
                compacted_messages,
                tools=tools_list,
                max_ctx=max_ctx,
                reserve_tokens=4096,
                force=True,
            )
            req_payload.pop("max_tokens", None)
            req_payload["n_predict"] = -1
            continue
        break
    return None


def _load_operator_system_prompt() -> str:
    """โหลด System Prompt หลักจาก pipeline/cyber-operator.system.md (หลังหัวข้อ ## SYSTEM PROMPT)."""
    sys_file = HERE / "cyber-operator.system.md"
    if not sys_file.exists():
        return ""
    try:
        raw = sys_file.read_text(encoding="utf-8", errors="replace")
        marker = "## SYSTEM PROMPT"
        if marker in raw:
            raw = raw.split(marker, 1)[1]
        return raw.strip()
    except Exception:
        return ""


def _strip_stale_php2shell_section(text: str) -> str:
    """ตัดส่วน php2shell exploit toolkit เก่าที่อาจติดมาจาก /dsh/AGENTS.md ใน container ออก เพื่อไม่ให้ชี้นำโมเดลไปหา PHP."""
    if not text or "php2shell exploit toolkit" not in text:
        return text
    return re.sub(
        r"(?is)###\s+php2shell\s+exploit\s+toolkit.*?(?=\n###\s+|\Z)",
        "",
        text,
    )


def _ensure_operator_system_prompt(messages: list[dict], extra_directive: str = "") -> list[dict]:
    """
    รับประกันว่าทุกคำขอที่ส่งเข้าโมเดลมี System Prompt (cyber-operator.system.md) ที่สอนวิธีใช้ Tools & MCP ครบถ้วน
    และล้างบล็อก php2shell เก่าที่อาจค้างอยู่ใน /dsh/AGENTS.md ออกโดยอัตโนมัติ
    """
    op_prompt = _load_operator_system_prompt()
    cleaned_msgs: list[dict] = []
    has_operator_prompt = False

    for m in messages:
        mc = dict(m)
        content = mc.get("content")
        if isinstance(content, str):
            if "php2shell exploit toolkit" in content:
                content = _strip_stale_php2shell_section(content)
                mc["content"] = content
            if "security assessment operator" in content.lower():
                has_operator_prompt = True
        elif isinstance(content, list):
            new_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = str(item.get("text") or "")
                    if "php2shell exploit toolkit" in t:
                        t = _strip_stale_php2shell_section(t)
                    if "security assessment operator" in t.lower():
                        has_operator_prompt = True
                    new_parts.append({**item, "text": t})
                else:
                    new_parts.append(item)
            mc["content"] = new_parts
        cleaned_msgs.append(mc)

    out_msgs: list[dict] = []
    injected = False
    for mc in cleaned_msgs:
        if mc.get("role") == "system" and not injected:
            base_sys = _extract_text_from_msg_content(mc.get("content")).strip()
            if not has_operator_prompt and op_prompt:
                base_sys = f"{op_prompt}\n\n{base_sys}" if base_sys else op_prompt
            if extra_directive:
                base_sys = f"{base_sys}\n\n{extra_directive.strip()}"
            mc["content"] = base_sys
            injected = True
        out_msgs.append(mc)

    if not injected:
        sys_Parts = []
        if not has_operator_prompt and op_prompt:
            sys_Parts.append(op_prompt)
        if extra_directive:
            sys_Parts.append(extra_directive.strip())
        if sys_Parts:
            out_msgs.insert(0, {"role": "system", "content": "\n\n".join(sys_Parts)})

    return out_msgs


def _extract_text_from_msg_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")


_DSH_METADATA_LINE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"current\s+time\s*:|"
    r"the\s+provided\s+time\s+is|"
    r"timezone\s*:|"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?:\s*\([^)]+\))?\s*$|"
    r"\[system[^\]]*\]"
    r")"
)


def _extract_clean_user_text(content) -> str:
    """ดึงเฉพาะข้อความจริงที่ผู้ใช้พิมพ์ โดยตัด <system-reminder> และ Timestamp ที่ DeepSeek Harness แนบมาออก."""
    raw_parts = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = str(item.get("text") or "").strip()
                if t and not _DSH_METADATA_LINE_RE.match(t):
                    raw_parts.append(t)
        raw = "\n".join(raw_parts)
    else:
        raw = str(content or "")

    # ลบแท็กเมตาดาต้าที่ Harness แทรกมาเบื้องหลัง
    raw = re.sub(
        r"(?is)<(?:system-reminder|environment_details|context|user-prompt-submit-hook)>.*?</(?:system-reminder|environment_details|context|user-prompt-submit-hook)>",
        "",
        raw,
    )
    cleaned_lines = []
    for line in raw.splitlines():
        if _DSH_METADATA_LINE_RE.match(line.strip()):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def handle_openai_chat_completions(body: dict) -> dict:
    """
    OpenAI-compatible `/v1/chat/completions` สำหรับ DeepSeek Harness (:3080) โดยใช้ LLM Intent Classifier:
      1) `conversational`     — คุยทั่วไป / ทักทาย / ถามทฤษฎี -> ตอบตรงใน 1 เทิร์น (ถอด Tool ออกเพื่อไม่ให้ไปรัน ls/scan เอง)
      2) `direct_task`        — สั่งงานเดี่ยว (เช่น เขียนโค้ดชิ้นเดียว หรือรันเช็กจุดเดียว) -> ใช้สมองที่ตรงสายพร้อม Tool ปกติ แต่ไม่เปิดลูปส่งไม้ต่อข้ามสมอง
      3) `continuous_mission` — ภารกิจหลายขั้นตอน (เช่น สำรวจ+เจาะระบบ+เขียน PoC+ทำรายงาน) -> เปิดวงจร Dual-Brain Auto-Relay เต็มรูปแบบ
    """
    req_model = str(body.get("model") or "n8n-dual-brain").strip()
    messages = list(body.get("messages") or [])
    tools = list(body.get("tools") or [])

    non_sys = [m for m in messages if m.get("role") != "system"]
    last_msg = non_sys[-1] if non_sys else {}
    last_role = str(last_msg.get("role") or "user")

    last_user_text = ""
    for m in reversed(non_sys):
        if m.get("role") == "user":
            last_user_text = _extract_clean_user_text(m.get("content"))
            if last_user_text:
                break

    # ── โหมด พิเศษ: n8n-canvas-runner (ยิงเข้า Webhook ของผัง n8n :5678 โดยตรง) ──
    if "canvas" in req_model or "webhook" in req_model:
        n8n_res = _trigger_n8n_canvas_webhook(last_user_text or "ดำเนินการตามภารกิจ")
        if n8n_res and (n8n_res.get("output") or n8n_res.get("last_output")):
            out_txt = n8n_res.get("output") or n8n_res.get("last_output") or ""
            turns = n8n_res.get("total_turns") or n8n_res.get("turn") or 1
            ck = n8n_res.get("completed_checklist") or n8n_res.get("checklist") or []
            ck_md = "\n".join(
                f"- [{'x' if c.get('status') == 'done' else ' '}] #{c.get('id')}: {c.get('title')} (`{c.get('owner') or c.get('domain')}`)"
                for c in ck if isinstance(c, dict)
            )
            full_reply = (
                f"**[รันผ่านผังโหนด n8n (0. Dual-Brain Auto-Relay Loop) สำเร็จ · {turns} รอบผลัดไม้]**\n\n"
                + (f"### สมุดคุมงาน (Checklist)\n{ck_md}\n\n" if ck_md else "")
                + str(out_txt)
            )
            return {
                "id": f"chatcmpl-n8n-{uuid.uuid4().hex[:10]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req_model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": full_reply},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": len(full_reply) // 4, "total_tokens": 100 + len(full_reply) // 4},
            }

    state = _load_relay_state()

    # ── กรณีเป็น Background Title / Summary Request จาก DeepSeek Harness (ไม่มี tools แนบมา) ──
    sys_text_all = "\n".join(
        _extract_text_from_msg_content(m.get("content"))
        for m in messages if m.get("role") == "system"
    )
    if not tools and "security assessment operator" not in sys_text_all.lower():
        bg_body = dict(body)
        bg_body.pop("max_tokens", None)
        upstream = _call_upstream_chat_completion("gpt-oss-120b", bg_body, messages)
        if not upstream or "choices" not in upstream or not upstream["choices"]:
            upstream = _call_upstream_chat_completion("cyber-tiel", bg_body, messages)
        if upstream and "choices" in upstream and upstream["choices"]:
            upstream["model"] = req_model
            return upstream

    # ── ประเมิน Intent ด้วย LLM เมื่อผู้ใช้ส่งข้อความใหม่ (last_role == 'user') ──
    if last_role == "user":
        intent_info = _classify_intent_and_brain_llm(last_user_text)
        intent_mode = intent_info["intent"]
        classified_brain = intent_info["brain"]
        classified_reason = intent_info["reason"]
    else:
        # กรณีเป็นเทิร์นต่อเนื่องหลังจากรัน Tool ('tool' role) ให้ยึดโหมดของเทิร์นปัจจุบัน
        intent_mode = state.get("intent_mode") or "direct_task"
        classified_brain = state.get("current_brain") or "gpt-oss-120b"
        classified_reason = state.get("dispatch_reason") or "tool_continuation"

    # ── โหมด 1: Conversational (พูดคุยทั่วไป / ทักทาย / ถามความรู้ทฤษฎี — ไม่เรียก Tool) ──
    if intent_mode == "conversational":
        if state and not state.get("is_done"):
            state["is_done"] = True
            state["intent_mode"] = "conversational"
            state["status"] = "completed"
            _save_relay_state(state)

        chat_body = dict(body)
        chat_body.pop("tools", None)
        chat_body.pop("tool_choice", None)
        chat_body.pop("max_tokens", None)
        # ใช้ System Prompt เฉพาะสำหรับคุยทั่วไปแทน AGENTS.md (545 บรรทัด) เพื่อไม่ให้โมเดลคิดวนเรื่อง WSTG ตอนทักทาย
        chat_sys = (
            "You are a helpful AI assistant in the Project-Malaria Dual-Brain studio "
            "(pairing Orchestrator for Coding/Architecture and Cyber-Model for Cyber Security). "
            "The user is chatting or asking a general question. Answer directly, accurately, and naturally in the user's language. "
            "Keep your internal reasoning brief and do NOT initiate any security scan or checklist."
        )
        chat_msgs = [{"role": "system", "content": chat_sys}]
        for m in messages:
            if m.get("role") != "system":
                chat_msgs.append(dict(m))

        target_brain = (
            "cyber-model" if req_model in ("cyber-model", "cyber-tiel", "exploit-specialist")
            else ("orchestrator" if req_model in ("orchestrator", "flint", "gpt-oss-120b", "cybermodel", "qwen2.5-coder-32b", "qwen2.5-coder-14b", "qwen2.5-coder", "qwen") else classified_brain)
        )
        upstream = _call_upstream_chat_completion(target_brain, chat_body, chat_msgs)
        if not upstream or "choices" not in upstream or not upstream["choices"]:
            alt = "cyber-model" if target_brain in ("orchestrator", "gpt-oss-120b") else "orchestrator"
            upstream = _call_upstream_chat_completion(alt, chat_body, chat_msgs)
        if upstream and "choices" in upstream and upstream["choices"]:
            upstream["model"] = req_model
            return upstream

    # ── โหมด 2: Direct Task (งานเดี่ยวจบในสมองเดียว — มี Tool ปกติ แต่ไม่วนลูป Handover ข้ามสมอง) ──
    if intent_mode == "direct_task":
        target_brain = (
            "cyber-model" if req_model in ("cyber-model", "cyber-tiel", "exploit-specialist")
            else ("orchestrator" if req_model in ("orchestrator", "flint", "gpt-oss-120b", "cybermodel", "qwen2.5-coder-32b", "qwen2.5-coder-14b", "qwen2.5-coder", "qwen") else classified_brain)
        )
        state["intent_mode"] = "direct_task"
        state["current_brain"] = target_brain
        state["dispatch_reason"] = classified_reason
        state["is_done"] = True
        _save_relay_state(state)

        direct_body = dict(body)
        direct_body.pop("max_tokens", None)
        if tools:
            # ถอดเฉพาะ tool ส่งไม้ต่อ (n8n_relay_handover) ออก เพื่อไม่ให้วนลูปข้ามสมองโดยไม่จำเป็น
            filtered_tools = [
                t for t in tools
                if "n8n_relay_handover" not in ((t.get("function") or {}).get("name") or "")
            ]
            if filtered_tools:
                direct_body["tools"] = filtered_tools
            else:
                direct_body.pop("tools", None)
                direct_body.pop("tool_choice", None)

        direct_directive = (
            "## [DIRECT TASK & TOOL-FIRST DIRECTIVE]\n"
            "- This is a focused Direct Task. Passive intelligence queries (searching CVEs, NVD/KEV, advisories, or public web info) "
            "are ALWAYS authorized and do NOT require an `<ENGAGEMENT SCOPE>` target IP.\n"
            "- BROAD/GENERAL QUERIES: If the user asks a broad or general question (e.g. 'หา CVE ใหม่ล่าสุดที่มีผลกระทบวงกว้าง' without specifying a software/target), "
            "do NOT anchor to or assume PHP or any past chat subject! Instead, search broadly using `web_search` (`mcp__search__web_search`) "
            "(e.g., query 'latest unpatched zero-day CVE critical widespread 2025 2026' or 'CISA KEV catalog recent') "
            "and `fetch_url` (`mcp__search__fetch_url`), or `cve_search_tools` for KEV/NVD. Do NOT call single-package tools like OSV with an arbitrary package name.\n"
            "- NEVER guess, extrapolate, or repeat sequential CVE numbers or future dates from training memory.\n"
        )
        direct_msgs = _ensure_operator_system_prompt(messages, direct_directive)

        upstream = _call_upstream_chat_completion(target_brain, direct_body, direct_msgs)
        if not upstream or "choices" not in upstream or not upstream["choices"]:
            alt = "cyber-model" if target_brain in ("orchestrator", "gpt-oss-120b") else "orchestrator"
            target_brain = alt
            upstream = _call_upstream_chat_completion(alt, direct_body, direct_msgs)

        if upstream and "choices" in upstream and upstream["choices"]:
            choice = dict(upstream["choices"][0])
            msg = dict(choice.get("message") or {"role": "assistant", "content": ""})
            content = str(msg.get("content") or "")
            if content.strip() and not content.lstrip().startswith("**[Brain"):
                badge = (
                    f"**[Brain B: Cyber-Model · Direct Task · `{classified_reason}`]**\n\n"
                    if target_brain in ("cyber-model", "cyber-tiel")
                    else f"**[Brain A: Orchestrator · Direct Task · `{classified_reason}`]**\n\n"
                )
                msg["content"] = badge + content
            choice["message"] = msg
            upstream["choices"] = [choice]
            upstream["model"] = req_model
            return upstream

    # ── โหมด 3: Continuous Mission (ภารกิจต่อเนื่องหลายขั้นตอน — เปิดวงจร Dual-Brain Auto-Relay) ──
    if last_role == "user" and last_user_text:
        if len(non_sys) == 1 or not state.get("session_id") or state.get("is_done") or state.get("goal") != last_user_text:
            init_res = relay_init_session({"goal": last_user_text})
            state = init_res.get("state") or _load_relay_state()
            state["intent_mode"] = "continuous_mission"
            state["auto_handover_streak"] = 0
            _save_relay_state(state)
    elif last_role == "tool":
        tool_content = _extract_text_from_msg_content(last_msg.get("content"))
        if "mission_complete\": false" not in tool_content.lower():
            state["auto_handover_streak"] = 0
            _save_relay_state(state)

    last_hint = ""
    for m in reversed(non_sys):
        r = m.get("role")
        txt = _extract_text_from_msg_content(m.get("content"))
        if r == "assistant" and txt:
            last_hint = txt
            break
        if r == "tool" and "selected_brain" in txt:
            try:
                td = json.loads(txt)
                if td.get("selected_brain"):
                    last_hint = f"HANDOVER_TO: {td['selected_brain']}"
                    break
            except Exception:
                pass

    disp = relay_dispatch_turn({"last_output": last_hint})
    if req_model in ("cyber-model", "cyber-tiel", "exploit-specialist"):
        selected_brain = "cyber-model"
        reason = "manual_model_select"
    elif req_model in ("orchestrator", "flint", "gpt-oss-120b", "cybermodel", "big-brain", "local-cybertiel", "qwen2.5-coder-32b", "qwen2.5-coder-14b", "qwen2.5-coder", "qwen"):
        selected_brain = "orchestrator"
        reason = "manual_model_select"
    else:
        selected_brain = disp.get("selected_brain") or classified_brain
        reason = disp.get("dispatch_reason") or classified_reason

    turn_num = int(disp.get("turn") or 1)
    max_iter = int(disp.get("max_iterations") or 30)
    active_step = disp.get("active_step") or {}
    checklist = disp.get("checklist") or []
    checklist_md = "\n".join(
        f"  - [{'x' if c.get('status') == 'done' else ' '}] Step #{c.get('id')} ({c.get('owner') or c.get('domain')}): {c.get('title')}"
        for c in checklist
    )

    brain_desc = (
        "Brain B: Cyber-Tiel-35B (:8091) — Cyber Security, Recon, WSTG, Exploitation, REA & CVE Specialist"
        if selected_brain in ("cyber-model", "cyber-tiel")
        else "Brain A: gpt-oss-120b (:8090) — Master Architect, Coding, Python/Bash Scripting & Report Specialist"
    )
    partner_brain = "orchestrator" if selected_brain in ("cyber-model", "cyber-tiel") else "cyber-model"

    relay_addendum = (
        f"## [n8n Dual-Brain Auto-Relay Active in DeepSeek Harness]\n"
        f"- **User Goal**: {last_user_text}\n"
        f"- **Active Brain This Turn**: `{selected_brain}` ({brain_desc})\n"
        f"- **Partner Brain**: `{partner_brain}`\n"
        f"- **Relay Turn**: #{turn_num} / {max_iter} (Routed via: `{reason}`)\n"
        f"- **Current Active Step**: #{active_step.get('id', 1)} — {active_step.get('title', 'Execute user task')}\n"
        f"- **Mission Checklist**:\n{checklist_md}\n\n"
        f"### Relay Rules (Proportional & Non-Stop until Goal is Met):\n"
        f"1. Focus strictly on what the user actually asked for in **User Goal** (ignore any system timestamps).\n"
        f"2. If the user's request is already completely answered in this turn, end with `MISSION_STATUS: COMPLETE` and do NOT call `n8n_relay_handover`.\n"
        f"3. If and only if the next step of the user's goal requires `{partner_brain}` (e.g. switching between Security Testing and Coding/Report Writing) or more checklist steps remain, call `n8n_relay_handover` (or write `HANDOVER_TO: {partner_brain}` + `MISSION_STATUS: IN_PROGRESS`).\n"
    )

    aug_messages = _ensure_operator_system_prompt(messages, relay_addendum)

    mission_body = dict(body)
    mission_body.pop("max_tokens", None)

    upstream = _call_upstream_chat_completion(selected_brain, mission_body, aug_messages)
    if not upstream or "choices" not in upstream or not upstream["choices"]:
        selected_brain = partner_brain
        reason = f"cross_brain_rescue_from_{'cyber-model' if partner_brain in ('orchestrator', 'gpt-oss-120b') else 'orchestrator'}"
        upstream = _call_upstream_chat_completion(selected_brain, mission_body, aug_messages)

    if not upstream or "choices" not in upstream or not upstream["choices"]:
        err_msg = (
            "[WARN] ไม่สามารถติดต่อโมเดลบนพอร์ต `:8090` (`orchestrator`) หรือ `:8091` (`cyber-model`) ได้ "
            "กรุณาตรวจสอบว่า `llama-server` และ `litellm (:4000)` ทำงานอยู่"
        )
        return {
            "id": f"chatcmpl-err-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": err_msg}, "finish_reason": "stop"}],
        }

    choice = dict(upstream["choices"][0])
    msg = dict(choice.get("message") or {"role": "assistant", "content": ""})
    content = str(msg.get("content") or "")
    tool_calls = list(msg.get("tool_calls") or [])

    step_res = {}
    if content.strip():
        step_res = relay_complete_step({"output": content})
        badge = (
            f"**[Brain B: Cyber-Model · รอบที่ {turn_num} · `{reason}`]**\n\n"
            if selected_brain in ("cyber-model", "cyber-tiel")
            else f"**[Brain A: Orchestrator · รอบที่ {turn_num} · `{reason}`]**\n\n"
        )
        if not content.lstrip().startswith("**[Brain"):
            content = badge + content
            msg["content"] = content

    # ── Anti-Stall Auto-Handover: กระตุ้นอัตโนมัติเฉพาะเมื่อโมเดลส่งสัญญาณ HANDOVER_TO ชัดเจนและภารกิจยังไม่ COMPLETE ──
    if not tool_calls and req_model == "n8n-dual-brain":
        handover_tool_name = None
        for t in tools:
            fn_name = (t.get("function") or {}).get("name") or ""
            if "n8n_relay_handover" in fn_name:
                handover_tool_name = fn_name
                break

        cur_state = _load_relay_state()
        streak = int(cur_state.get("auto_handover_streak") or 0)
        is_done = bool(step_res.get("is_done") or cur_state.get("is_done"))
        explicit_complete = bool(re.search(r"(?i)MISSION_STATUS\s*[:=]\s*['\"]?COMPLETE", content))
        m_handover = re.search(r"(?i)(?:HANDOVER_TO|NEXT_BRAIN)\s*[:=]\s*['\"]?(cyber-tiel|gpt-oss-120b)", content)

        if handover_tool_name and m_handover and not is_done and not explicit_complete and streak < 3:
            cur_state["auto_handover_streak"] = streak + 1
            _save_relay_state(cur_state)
            next_b = m_handover.group(1).lower()
            done_id = str(active_step.get("id") or "NONE")
            tool_calls = [{
                "id": f"call_relay_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": handover_tool_name,
                    "arguments": json.dumps({
                        "done_step": done_id,
                        "next_brain": next_b,
                        "handover_note": f"Auto-relay from {selected_brain} to {next_b} after turn #{turn_num}",
                        "mission_status": "IN_PROGRESS",
                    }, ensure_ascii=False),
                },
            }]
            msg["tool_calls"] = tool_calls
            choice["finish_reason"] = "tool_calls"

    choice["message"] = msg
    upstream["choices"] = [choice]
    upstream["model"] = req_model
    return upstream



class ControlPlaneHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data: dict, status: int = 200):
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_openai_sse(self, completion: dict):
        """แปลงผลลัพธ์ chat.completion เป็น OpenAI SSE chunks สำหรับ DeepSeek Harness (stream=True)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        cid = completion.get("id") or f"chatcmpl-{uuid.uuid4().hex[:10]}"
        created = int(completion.get("created") or time.time())
        model = completion.get("model") or "n8n-dual-brain"
        choices = completion.get("choices") or [{}]
        choice0 = choices[0] if choices else {}
        msg = choice0.get("message") or {}
        content = str(msg.get("content") or "")
        tool_calls = msg.get("tool_calls") or []
        finish_reason = choice0.get("finish_reason") or ("tool_calls" if tool_calls else "stop")

        def _emit(delta: dict, fin=None):
            chunk = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
            }
            line = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        _emit({"role": "assistant", "content": ""})
        if content:
            step = 500
            for idx in range(0, len(content), step):
                _emit({"content": content[idx:idx + step]})
        if tool_calls:
            tc_deltas = []
            for i, tc in enumerate(tool_calls):
                tc_deltas.append({
                    "index": i,
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": (tc.get("function") or {}).get("name") or "",
                        "arguments": (tc.get("function") or {}).get("arguments") or "{}",
                    },
                })
            _emit({"tool_calls": tc_deltas})
        _emit({}, fin=finish_reason)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            # Redirect directly to real n8n (:5678) — no custom dashboard
            self.send_response(302)
            self.send_header("Location", "http://localhost:5678")
            self.end_headers()
            return

        if path == "/healthz":
            self._send_json({"ok": True, "service": "n8n-backend-bridge"})
            return

        if path in ("/v1/models", "/api/v1/models"):
            self._send_json({
                "object": "list",
                "data": [
                    {"id": "n8n-dual-brain", "object": "model", "owned_by": "project-malaria"},
                    {"id": "n8n-canvas-runner", "object": "model", "owned_by": "project-malaria"},
                    {"id": "orchestrator", "object": "model", "owned_by": "project-malaria"},
                    {"id": "flint", "object": "model", "owned_by": "project-malaria"},
                    {"id": "cyber-model", "object": "model", "owned_by": "project-malaria"},
                    {"id": "qwen2.5-coder-32b", "object": "model", "owned_by": "project-malaria"},
                    {"id": "qwen2.5-coder-14b", "object": "model", "owned_by": "project-malaria"},
                    {"id": "gpt-oss-120b", "object": "model", "owned_by": "project-malaria"},
                    {"id": "cybermodel", "object": "model", "owned_by": "project-malaria"},
                    {"id": "cyber-tiel", "object": "model", "owned_by": "project-malaria"},
                    {"id": "exploit-specialist", "object": "model", "owned_by": "project-malaria"},
                ],
            })
            return

        if path == "/api/topology":
            cfg = load_node_config()
            status = collect_live_status(cfg)
            self._send_json({"config": cfg, "status": status, "relay_session": _load_relay_state()})
            return

        if path == "/api/relay/state":
            self._send_json({"ok": True, "state": _load_relay_state()})
            return

        if path == "/api/node/logs":
            node_id = (qs.get("id") or ["mcp:hexstrike"])[0]
            lines = int((qs.get("lines") or ["100"])[0])
            self._send_json(fetch_node_logs(node_id, lines))
            return

        self._send_json({"error": f"Not found: {path}"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
        except Exception as e:
            self._send_json({"ok": False, "error": f"Invalid JSON: {e}"}, status=400)
            return

        if path in ("/v1/chat/completions", "/api/v1/chat/completions", "/chat/completions"):
            comp = handle_openai_chat_completions(body)
            if body.get("stream"):
                self._send_openai_sse(comp)
            else:
                self._send_json(comp)
            return

        if path == "/api/relay/init":
            self._send_json(relay_init_session(body))
            return

        if path == "/api/relay/dispatch":
            self._send_json(relay_dispatch_turn(body))
            return

        if path == "/api/relay/step-complete":
            self._send_json(relay_complete_step(body))
            return

        if path == "/api/topology":
            res = sync_all_configs(body)
            self._send_json(res)
            return

        if path == "/api/node/toggle":
            cfg = load_node_config()
            target = body.get("target", "")
            field = body.get("field", "enabled")
            value = body.get("value")
            kind, _, key = target.partition(":")
            section_map = {
                "harness": "harnesses",
                "gateway": "gateway",
                "mcp": "mcp_servers",
                "plugin": "plugins",
                "model": "models",
                "aux": "auxiliary_services",
            }
            sec = section_map.get(kind)
            if sec and key in (cfg.get(sec) or {}):
                cur = cfg[sec][key].get(field, True)
                new_val = (not cur) if value is None else bool(value)
                cfg[sec][key][field] = new_val
                if kind == "plugin" and field == "enabled":
                    cfg.setdefault("mcp_servers", {}).setdefault("hexstrike", {}).setdefault("plugins", {})[key] = new_val
                sync_all_configs(cfg)
                self._send_json({"ok": True, "target": target, "field": field, "value": new_val})
            else:
                self._send_json({"ok": False, "error": f"Unknown target {target}"}, status=400)
            return

        if path == "/api/node/action":
            node_id = body.get("id", "")
            action = body.get("action", "restart")
            self._send_json(execute_node_action(node_id, action))
            return

        if path.startswith("/api/bridge/"):
            tool_group = path.split("/api/bridge/", 1)[1].strip("/")
            self._send_json(handle_bridge_call(tool_group, body))
            return

        self._send_json({"ok": False, "error": f"Not found: {path}"}, status=404)


def main():
    print(
        f"[n8n-bridge] Headless n8n Backend Bridge & Dual-Brain Relay API listening on :{CONTROL_PORT} (UI -> http://localhost:5678)",
        file=sys.stderr,
    )
    server = ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), ControlPlaneHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
