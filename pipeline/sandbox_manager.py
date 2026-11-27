#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project-Malaria — Per-Task Isolated Ephemeral Kali Sandbox Manager
==================================================================
Inspired by PentAGI's per-flow Kali isolation, hardened WITHOUT exposing
docker.sock to any untrusted AI agent container:
  - Runs on the macOS Control Plane (:8010) behind structured REST endpoints.
  - Spawns one lightweight, resource-capped Kali container per ARTEX Task
    (`malaria-kali-task-<task_id>`) reusing local `pipeline-hexstrike-server:latest`
    (fallback `artex:local`) with 0 MB extra pull.
  - Drops dangerous Linux capabilities (--cap-drop ALL --cap-add NET_RAW
    --cap-add NET_BIND_SERVICE --security-opt no-new-privileges), caps CPU/RAM/PIDs,
    isolates scratch workspace per task (`pipeline/sandboxes/task_<id>` -> `/sandbox`),
    and mounts shared `/workspace` read-only (`/workspace:ro`).
  - Background reaper cleans up idle sandboxes automatically after TTL expiry.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
SANDBOX_ROOT = HERE / "sandboxes"
SHARED_WORKSPACE_DIR = HERE / "dsh-workspace"
CONTAINER_PREFIX = "malaria-kali-task-"
PREFERRED_IMAGES = [
    "pipeline-hexstrike-server:latest",
    "kalilinux/kali-rolling:latest",
    "artex:local",
]
DEFAULT_TTL_MINUTES = 90

_LOCK = threading.RLock()
_META: dict[int, dict[str, Any]] = {}


def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def _container_name(task_id: int) -> str:
    return f"{CONTAINER_PREFIX}{int(task_id)}"


def _select_sandbox_image() -> str:
    for img in PREFERRED_IMAGES:
        res = subprocess.run(
            ["docker", "image", "inspect", img],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if res.returncode == 0:
            return img
    return PREFERRED_IMAGES[-1]


def _inspect_container(cname: str) -> Optional[dict[str, Any]]:
    res = subprocess.run(
        ["docker", "inspect", cname],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 or not res.stdout.strip():
        return None
    try:
        arr = json.loads(res.stdout)
        return arr[0] if arr else None
    except Exception:
        return None


def get_sandbox_status(task_id: int) -> dict[str, Any]:
    tid = int(task_id or 0)
    if tid <= 0:
        return {"ok": False, "error": "task_id must be > 0"}
    cname = _container_name(tid)
    task_dir = SANDBOX_ROOT / f"task_{tid}"
    info = _inspect_container(cname)
    with _LOCK:
        meta = dict(_META.get(tid) or {})

    if not info:
        files_cnt = len(list(task_dir.rglob("*"))) if task_dir.is_dir() else 0
        return {
            "ok": True,
            "task_id": tid,
            "container": cname,
            "running": False,
            "status": "not_spawned",
            "image": _select_sandbox_image(),
            "limits": {"cpus": "2.0", "memory": "2g", "pids": 256},
            "sandbox_dir": str(task_dir),
            "scratch_files": files_cnt,
            "ttl_minutes": meta.get("ttl_minutes", DEFAULT_TTL_MINUTES),
        }

    state = info.get("State") or {}
    running = bool(state.get("Running"))
    img = (info.get("Config") or {}).get("Image") or _select_sandbox_image()
    files_cnt = len([p for p in task_dir.rglob("*") if p.is_file()]) if task_dir.is_dir() else 0
    last_used = float(meta.get("last_used_ts") or _now_ts())
    ttl_min = int(meta.get("ttl_minutes") or DEFAULT_TTL_MINUTES)
    idle_min = round(max(0.0, (_now_ts() - last_used) / 60.0), 1)

    return {
        "ok": True,
        "task_id": tid,
        "container": cname,
        "running": running,
        "status": "running" if running else str(state.get("Status") or "stopped"),
        "image": img,
        "started_at": state.get("StartedAt", ""),
        "limits": {"cpus": "2.0", "memory": "2g", "pids": 256},
        "sandbox_dir": str(task_dir),
        "scratch_files": files_cnt,
        "idle_minutes": idle_min,
        "ttl_minutes": ttl_min,
        "exec_count": int(meta.get("exec_count") or 0),
        "last_command": str(meta.get("last_command") or ""),
    }


def list_sandboxes(task_id: Optional[int] = None) -> dict[str, Any]:
    if task_id is not None and int(task_id) > 0:
        st = get_sandbox_status(int(task_id))
        return {"ok": True, "sandbox": st, "sandboxes": [st] if st.get("running") else []}

    res = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    items = []
    for ln in (res.stdout or "").splitlines():
        m = re.match(rf"^{re.escape(CONTAINER_PREFIX)}(\d+)$", ln.strip())
        if m:
            items.append(get_sandbox_status(int(m.group(1))))
    items.sort(key=lambda x: x.get("task_id", 0), reverse=True)
    return {"ok": True, "sandboxes": items}


def spawn_sandbox(task_id: int, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict[str, Any]:
    tid = int(task_id or 0)
    if tid <= 0:
        return {"ok": False, "error": "task_id is required"}

    cname = _container_name(tid)
    task_dir = SANDBOX_ROOT / f"task_{tid}"
    task_dir.mkdir(parents=True, exist_ok=True)
    SHARED_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    info = _inspect_container(cname)
    if info and (info.get("State") or {}).get("Running"):
        with _LOCK:
            m = _META.setdefault(tid, {})
            m["last_used_ts"] = _now_ts()
            m["ttl_minutes"] = max(5, int(ttl_minutes or DEFAULT_TTL_MINUTES))
        st = get_sandbox_status(tid)
        st["reused"] = True
        return st

    if info:
        subprocess.run(["docker", "rm", "-f", cname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    image = _select_sandbox_image()
    cmd = [
        "docker", "run", "-d",
        "--name", cname,
        "--hostname", f"kali-task-{tid}",
        "--cpus", "2.0",
        "--memory", "2g",
        "--pids-limit", "256",
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--cap-add", "NET_RAW",
        "--cap-add", "NET_BIND_SERVICE",
        "--add-host", "host.docker.internal:host-gateway",
        "-e", "DEBIAN_FRONTEND=noninteractive",
        "-e", "PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "-v", f"{task_dir}:/sandbox",
        "-v", f"{SHARED_WORKSPACE_DIR}:/workspace:ro",
        "-w", "/sandbox",
        "--entrypoint", "sh",
        image,
        "-c", "trap 'exit 0' TERM INT; while true; do sleep 3600; done",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "docker run failed").strip()}

    with _LOCK:
        _META[tid] = {
            "created_at": _now_iso(),
            "last_used_ts": _now_ts(),
            "ttl_minutes": max(5, int(ttl_minutes or DEFAULT_TTL_MINUTES)),
            "exec_count": 0,
            "last_command": "",
        }
    st = get_sandbox_status(tid)
    st["reused"] = False
    return st


def exec_in_sandbox(
    task_id: int,
    command: str,
    timeout_sec: int = 120,
    workdir: str = "/sandbox",
) -> dict[str, Any]:
    tid = int(task_id or 0)
    cmd_str = (command or "").strip()
    if tid <= 0:
        return {"ok": False, "error": "task_id is required"}
    if not cmd_str:
        return {"ok": False, "error": "command is required"}

    timeout_bounded = max(5, min(600, int(timeout_sec or 120)))
    wdir = (workdir or "/sandbox").strip()
    if not wdir.startswith("/"):
        wdir = "/sandbox"

    spawn_res = spawn_sandbox(tid)
    if not spawn_res.get("ok"):
        return spawn_res

    cname = _container_name(tid)
    t0 = time.time()
    try:
        proc = subprocess.run(
            [
                "docker", "exec",
                "-w", wdir,
                cname,
                "sh", "-c", cmd_str,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_bounded,
        )
        dur_ms = int((time.time() - t0) * 1000)
        stdout = (proc.stdout or "")[-16000:]
        stderr = (proc.stderr or "")[-8000:]
        with _LOCK:
            m = _META.setdefault(tid, {})
            m["last_used_ts"] = _now_ts()
            m["exec_count"] = int(m.get("exec_count") or 0) + 1
            m["last_command"] = cmd_str[:180]
        return {
            "ok": True,
            "task_id": tid,
            "container": cname,
            "exit_code": proc.returncode,
            "duration_ms": dur_ms,
            "stdout": stdout,
            "stderr": stderr,
            "sandbox_dir": f"/sandbox (host: sandboxes/task_{tid})",
        }
    except subprocess.TimeoutExpired as te:
        dur_ms = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "task_id": tid,
            "container": cname,
            "exit_code": 124,
            "duration_ms": dur_ms,
            "error": f"Command timed out after {timeout_bounded}s",
            "stdout": (te.stdout.decode("utf-8", errors="replace") if isinstance(te.stdout, bytes) else (te.stdout or ""))[-8000:],
            "stderr": (te.stderr.decode("utf-8", errors="replace") if isinstance(te.stderr, bytes) else (te.stderr or ""))[-4000:],
        }
    except Exception as e:
        return {"ok": False, "task_id": tid, "container": cname, "error": str(e)}


def destroy_sandbox(task_id: int, wipe_files: bool = False) -> dict[str, Any]:
    tid = int(task_id or 0)
    if tid <= 0:
        return {"ok": False, "error": "task_id is required"}
    cname = _container_name(tid)
    subprocess.run(["docker", "rm", "-f", cname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    task_dir = SANDBOX_ROOT / f"task_{tid}"
    if wipe_files and task_dir.is_dir():
        shutil.rmtree(task_dir, ignore_errors=True)
    with _LOCK:
        _META.pop(tid, None)
    return {
        "ok": True,
        "task_id": tid,
        "container": cname,
        "destroyed": True,
        "wiped_files": bool(wipe_files),
    }


def _idle_reaper_loop() -> None:
    while True:
        time.sleep(120)
        try:
            now = _now_ts()
            to_reap: list[int] = []
            with _LOCK:
                for tid, m in list(_META.items()):
                    ttl_sec = float(m.get("ttl_minutes") or DEFAULT_TTL_MINUTES) * 60.0
                    last_ts = float(m.get("last_used_ts") or now)
                    if (now - last_ts) > ttl_sec:
                        to_reap.append(tid)
            for tid in to_reap:
                destroy_sandbox(tid, wipe_files=False)
        except Exception:
            pass


_REAPER_THREAD = threading.Thread(target=_idle_reaper_loop, daemon=True)
_REAPER_THREAD.start()
