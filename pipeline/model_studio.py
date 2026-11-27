#!/usr/bin/env python3
"""
Project-Malaria — Model Studio Backend (Unsloth-style GGUF & Cloud Manager)
===========================================================================
Pure stdlib module imported by control_plane.py (:8010) and exposed through
unified-gateway at /model-studio-api/*.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
MAC_DIR = HERE / "mac"
LOGS_DIR = MAC_DIR / "logs"
STUDIO_CONFIG_FILE = HERE / "model-studio.json"
STUDIO_ENV_FILE = MAC_DIR / "llama.studio.env"
SANDBOX_PROFILE = MAC_DIR / "specialist-sandbox.sb"

_STUDIO_LOCK = threading.RLock()
_GGUF_CACHE: dict[str, tuple[float, int, dict[str, Any]]] = {}

def _default_path_if_exists(p: Path) -> str:
    return str(p) if p.exists() else ""


ENGINE_CANDIDATES = [
    {
        "id": "unsloth",
        "label": "Unsloth llama.cpp (~/.unsloth · Graph Fold + DSpark)",
        "path": str(Path.home() / ".unsloth" / "llama.cpp" / "build" / "bin" / "llama-server"),
    },
    {
        "id": "local-master",
        "label": "Local Source Build (~/.local/src/llama.cpp)",
        "path": str(Path.home() / ".local" / "src" / "llama.cpp" / "build" / "bin" / "llama-server"),
    },
    {
        "id": "homebrew",
        "label": "Homebrew Apple Silicon (/opt/homebrew/bin/llama-server)",
        "path": "/opt/homebrew/bin/llama-server",
    },
    {
        "id": "usr-local",
        "label": "System Local (/usr/local/bin/llama-server)",
        "path": "/usr/local/bin/llama-server",
    },
    {
        "id": "usr-bin",
        "label": "System Package (/usr/bin/llama-server)",
        "path": "/usr/bin/llama-server",
    },
]

SCAN_DIRS = [
    Path.home() / "Downloads",
    Path.home() / "Downloads" / "model",
    Path.home() / "Downloads" / "model" / "vision",
    Path.home() / "models",
    Path.home() / ".cache" / "huggingface" / "hub",
]


def _is_under_default_scan_dir(dir_path: Path) -> bool:
    try:
        resolved = dir_path.resolve()
    except OSError:
        resolved = dir_path
    for base in SCAN_DIRS:
        try:
            base_res = base.resolve()
        except OSError:
            base_res = base
        if resolved == base_res or base_res in resolved.parents:
            return True
    return False


def _remember_extra_scan_dir(data: dict[str, Any], path_str: str) -> bool:
    raw = (path_str or "").strip()
    if not raw:
        return False
    p = Path(raw).expanduser()
    parent = p if p.is_dir() else p.parent
    if not parent.is_dir():
        return False
    if _is_under_default_scan_dir(parent):
        return False
    norm = str(parent)
    extra = data.setdefault("extra_scan_dirs", [])
    if not isinstance(extra, list):
        extra = []
        data["extra_scan_dirs"] = extra
    if norm in extra:
        return False
    extra.append(norm)
    if len(extra) > 40:
        del extra[:-40]
    return True

FILE_TYPE_MAP = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    19: "IQ2_XXS",
    20: "IQ2_XS",
    21: "IQ3_XXS",
    22: "IQ1_S",
    23: "IQ4_NL",
    24: "IQ3_S",
    25: "IQ3_M",
    26: "IQ2_S",
    27: "IQ2_M",
    28: "IQ4_XS",
    29: "IQ1_M",
    30: "BF16",
    36: "MXFP4",
}

_QUANT_NAME_RE = re.compile(
    r"(UD-?(?:I?Q\d+(?:_[A-Z0-9]+)*)|(?:I?Q\d+(?:_[A-Z0-9]+)*)|MXFP4|NVFP4|BF16|F16|F32)",
    re.IGNORECASE,
)


def _default_binary() -> str:
    for eng in ENGINE_CANDIDATES:
        p = Path(eng["path"])
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which("llama-server") or "llama-server"


def _default_slots() -> list[dict[str, Any]]:
    default_bin = _default_binary()
    return [
        {
            "id": "orchestrator",
            "node_config_key": "gpt-oss-120b",
            "label": "Orchestrator (Coding & Agent)",
            "role": "orchestrator",
            "port": 8090,
            "alias": "orchestrator",
            "target_alias": "cybermodel",
            "aliases": [
                "orchestrator",
                "inkling",
                "inkling2",
                "inkling-2-mini",
                "Inkling-2-Mini",
                "cybermodel",
                "qwen2.5-coder-32b",
                "qwen2.5-coder-14b",
                "qwen2.5-coder",
                "gpt-oss-120b",
                "big-brain",
                "local-cybertiel",
                "flint",
            ],
            "log_file": "llama.log",
            "enabled": True,
            "binary": default_bin,
            "model_path": _default_path_if_exists(Path.home() / "Downloads" / "Inkling-2-Mini-Q4_K_M.gguf"),
            "mmproj_enabled": False,
            "mmproj_path": "",
            "ctx_size": 49152,
            "gpu_layers": 99,
            "kv_cache_type": "q8_0",
            "speculative_mode": "auto",
            "draft_model_path": _default_path_if_exists(Path.home() / "Downloads" / "dspark-Inkling-2-Mini-Q8_0.gguf"),
            "draft_n_max": 2,
            "parallel_slots": 1,
            "batch_size": 1024,
            "ubatch_size": 512,
            "threads": 6,
            "threads_batch": 8,
            "reasoning_effort": "medium",
            "reasoning_preserve": False,
            "reasoning_budget": -1,
            "ctx_checkpoints": 6,
            "context_shift": False,
            "flash_attn": True,
            "sandbox": False,
            "n_predict": -1,
            "extra_args": "",
            "presets": {},
        },
        {
            "id": "specialist",
            "node_config_key": "cyber-tiel",
            "label": "Cyber-Model (Security Specialist)",
            "role": "specialist",
            "port": 8091,
            "alias": "cyber-model",
            "target_alias": "exploit-specialist",
            "aliases": ["cyber-model", "cyber-tiel", "exploit-specialist"],
            "log_file": "llama-specialist.log",
            "enabled": True,
            "binary": default_bin,
            "model_path": _default_path_if_exists(Path.home() / "Downloads" / "model" / "Cyber-Tiel-Coder-35B-A3B-MTP-UD-Q8_K_XL.gguf"),
            "mmproj_enabled": True,
            "mmproj_path": _default_path_if_exists(Path.home() / "Downloads" / "model" / "mmproj-BF16.gguf"),
            "ctx_size": 65536,
            "gpu_layers": 99,
            "kv_cache_type": "q8_0",
            "speculative_mode": "auto",
            "draft_model_path": "",
            "draft_n_max": 2,
            "parallel_slots": 1,
            "batch_size": 512,
            "ubatch_size": 256,
            "threads": 6,
            "threads_batch": 8,
            "reasoning_effort": "",
            "reasoning_preserve": False,
            "reasoning_budget": -1,
            "ctx_checkpoints": 20,
            "context_shift": False,
            "flash_attn": True,
            "sandbox": True,
            "n_predict": -1,
            "extra_args": "",
            "presets": {},
        },
        {
            "id": "summarizer",
            "node_config_key": "summarizer",
            "label": "Summarizer (Intent & Observer)",
            "role": "summarizer",
            "port": 8092,
            "alias": "summarizer",
            "target_alias": "summarizer",
            "aliases": ["summarizer"],
            "log_file": "llama-summarizer.log",
            "enabled": True,
            "binary": default_bin,
            "model_path": _default_path_if_exists(Path.home() / "Downloads" / "model" / "qwen2.5-3b-instruct-q8_0.gguf"),
            "mmproj_enabled": False,
            "mmproj_path": "",
            "ctx_size": 8192,
            "gpu_layers": 99,
            "kv_cache_type": "q8_0",
            "speculative_mode": "auto",
            "draft_model_path": "",
            "draft_n_max": 2,
            "parallel_slots": 1,
            "batch_size": 512,
            "ubatch_size": 256,
            "threads": 4,
            "threads_batch": 4,
            "reasoning_effort": "",
            "reasoning_preserve": True,
            "reasoning_budget": -1,
            "ctx_checkpoints": 8,
            "context_shift": False,
            "flash_attn": True,
            "sandbox": False,
            "n_predict": 1024,
            "extra_args": "",
            "presets": {},
        },
        {
            "id": "vision",
            "node_config_key": "vision",
            "label": "Vision & OCR (Multimodal)",
            "role": "vision",
            "port": 8093,
            "alias": "vision",
            "target_alias": "vision",
            "aliases": ["vision"],
            "log_file": "llama-vision.log",
            "enabled": True,
            "binary": default_bin,
            "model_path": _default_path_if_exists(Path.home() / "Downloads" / "model" / "vision" / "Qwen2.5-VL-7B-Instruct-UD-Q5_K_XL.gguf"),
            "mmproj_enabled": True,
            "mmproj_path": _default_path_if_exists(Path.home() / "Downloads" / "model" / "vision" / "mmproj-F16.gguf"),
            "ctx_size": 8192,
            "gpu_layers": 99,
            "kv_cache_type": "q8_0",
            "speculative_mode": "auto",
            "draft_model_path": "",
            "draft_n_max": 2,
            "parallel_slots": 1,
            "batch_size": 512,
            "ubatch_size": 256,
            "threads": 4,
            "threads_batch": 4,
            "reasoning_effort": "",
            "reasoning_preserve": True,
            "reasoning_budget": -1,
            "ctx_checkpoints": 8,
            "context_shift": False,
            "flash_attn": True,
            "sandbox": False,
            "n_predict": 2048,
            "extra_args": "",
            "presets": {},
        },
    ]


def load_studio_config() -> dict[str, Any]:
    with _STUDIO_LOCK:
        if STUDIO_CONFIG_FILE.is_file():
            try:
                data = json.loads(STUDIO_CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("slots"), list):
                    defaults_by_id = {s["id"]: s for s in _default_slots()}
                    merged_slots = []
                    seen = set()
                    for s in data["slots"]:
                        sid = s.get("id")
                        if sid in defaults_by_id:
                            merged = {**defaults_by_id[sid], **s}
                            merged_slots.append(merged)
                            seen.add(sid)
                        else:
                            merged_slots.append(s)
                    for sid, ds in defaults_by_id.items():
                        if sid not in seen:
                            merged_slots.append(ds)
                    data["slots"] = merged_slots
                    return data
            except Exception:
                pass
        data = {"version": 1, "slots": _default_slots()}
        _write_studio_config_unlocked(data)
        return data


def _write_studio_config_unlocked(data: dict[str, Any]) -> None:
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tmp = STUDIO_CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STUDIO_CONFIG_FILE)


def save_studio_config(data: dict[str, Any]) -> None:
    with _STUDIO_LOCK:
        _write_studio_config_unlocked(data)


# ── GGUF Binary Header Parser (stdlib struct only) ───────────────────────────

_GGUF_SCALAR_FMTS = {
    0: ("<B", 1),   # UINT8
    1: ("<b", 1),   # INT8
    2: ("<H", 2),   # UINT16
    3: ("<h", 2),   # INT16
    4: ("<I", 4),   # UINT32
    5: ("<i", 4),   # INT32
    6: ("<f", 4),   # FLOAT32
    7: ("<?", 1),   # BOOL
    10: ("<Q", 8),  # UINT64
    11: ("<q", 8),  # INT64
    12: ("<d", 8),  # FLOAT64
}


def _read_gguf_string(f) -> str:
    raw_len = f.read(8)
    if len(raw_len) < 8:
        raise EOFError("truncated string length")
    (length,) = struct.unpack("<Q", raw_len)
    if length > 4096:
        # Skip huge strings (e.g., chat_template) without keeping them
        f.seek(length, os.SEEK_CUR)
        return ""
    raw = f.read(length)
    if len(raw) < length:
        raise EOFError("truncated string")
    return raw.decode("utf-8", errors="replace")


def _skip_or_read_gguf_val(f, vtype: int) -> Any:
    if vtype == 8:  # STRING
        return _read_gguf_string(f)
    if vtype in _GGUF_SCALAR_FMTS:
        fmt, sz = _GGUF_SCALAR_FMTS[vtype]
        raw = f.read(sz)
        if len(raw) < sz:
            raise EOFError("truncated scalar")
        return struct.unpack(fmt, raw)[0]
    if vtype == 9:  # ARRAY
        hdr = f.read(12)
        if len(hdr) < 12:
            raise EOFError("truncated array header")
        elem_type, arr_len = struct.unpack("<IQ", hdr)
        if elem_type in _GGUF_SCALAR_FMTS:
            _, esz = _GGUF_SCALAR_FMTS[elem_type]
            f.seek(arr_len * esz, os.SEEK_CUR)
            return f"<array[{arr_len}]>"
        if elem_type == 8:
            # Tokenizer vocab arrays can have 200k strings; stop scanning KV beyond large string arrays
            if arr_len > 256:
                raise StopIteration("large_string_array")
            for _ in range(arr_len):
                _read_gguf_string(f)
            return f"<str_array[{arr_len}]>"
        raise StopIteration("nested_array")
    raise ValueError(f"unknown gguf type {vtype}")


def read_gguf_metadata(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    info: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "exists": path.is_file(),
        "size_bytes": 0,
        "size_gib": 0.0,
        "kind": _classify_gguf_kind(path.name),
        "architecture": "",
        "model_name": "",
        "block_count": None,
        "context_length": None,
        "file_type": None,
        "quant_label": _guess_quant_from_name(path.name),
        "expert_count": None,
        "expert_used_count": None,
    }
    if not path.is_file():
        return info

    try:
        st = path.stat()
    except OSError:
        return info

    info["size_bytes"] = st.st_size
    info["size_gib"] = round(st.st_size / (1024 ** 3), 2)
    cached = _GGUF_CACHE.get(str(path))
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return dict(cached[2])

    kv: dict[str, Any] = {}
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"GGUF":
                return info
            hdr = f.read(20)
            if len(hdr) < 20:
                return info
            version, _tensor_count, kv_count = struct.unpack("<IQQ", hdr)
            if version not in (2, 3):
                return info
            for _ in range(min(kv_count, 96)):
                key = _read_gguf_string(f)
                vtype_raw = f.read(4)
                if len(vtype_raw) < 4:
                    break
                (vtype,) = struct.unpack("<I", vtype_raw)
                val = _skip_or_read_gguf_val(f, vtype)
                if key:
                    kv[key] = val
    except (StopIteration, EOFError, OSError, ValueError):
        pass

    arch = str(kv.get("general.architecture") or "")
    info["architecture"] = arch
    info["model_name"] = str(kv.get("general.name") or "")
    ft = kv.get("general.file_type")
    if isinstance(ft, int):
        info["file_type"] = FILE_TYPE_MAP.get(ft, f"type_{ft}")
        if not info["quant_label"]:
            info["quant_label"] = info["file_type"]
    if arch:
        bc = kv.get(f"{arch}.block_count")
        cl = kv.get(f"{arch}.context_length")
        ec = kv.get(f"{arch}.expert_count")
        euc = kv.get(f"{arch}.expert_used_count")
        info["block_count"] = int(bc) if isinstance(bc, int) else None
        info["context_length"] = int(cl) if isinstance(cl, int) else None
        info["expert_count"] = int(ec) if isinstance(ec, int) else None
        info["expert_used_count"] = int(euc) if isinstance(euc, int) else None
        if arch in ("clip", "projector"):
            info["kind"] = "mmproj"
        elif arch in ("dflash", "dspark"):
            info["kind"] = "drafter"

    _GGUF_CACHE[str(path)] = (st.st_mtime, st.st_size, dict(info))
    return info


def _classify_gguf_kind(filename: str) -> str:
    low = filename.lower()
    if "mmproj" in low:
        return "mmproj"
    if any(tok in low for tok in ("dspark", "dflash", "eagle")):
        return "drafter"
    return "model"


def _guess_quant_from_name(filename: str) -> str:
    m = _QUANT_NAME_RE.search(filename)
    return m.group(1) if m else ""


def scan_gguf_files() -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    studio = load_studio_config()

    def _add_gguf(fpath: Path) -> None:
        fname = fpath.name
        lower = fname.lower()
        if not lower.endswith(".gguf") or ".inprogress" in lower:
            return
        try:
            real = os.path.realpath(fpath)
        except OSError:
            return
        if real in found or not os.path.isfile(real):
            return
        meta = read_gguf_metadata(real)
        meta["display_path"] = str(fpath)
        try:
            meta["mtime"] = fpath.stat().st_mtime
        except OSError:
            meta["mtime"] = 0.0
        found[real] = meta

    for base in SCAN_DIRS:
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for root, dirs, files in os.walk(base, followlinks=True):
            cur = Path(root)
            if len(cur.parts) - base_depth >= 5:
                dirs[:] = []
            for fname in files:
                _add_gguf(cur / fname)

    for raw_dir in (studio.get("extra_scan_dirs") or []):
        if not isinstance(raw_dir, str) or not raw_dir.strip():
            continue
        d = Path(raw_dir.strip()).expanduser()
        if not d.is_dir():
            continue
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=True):
                        _add_gguf(Path(entry.path))
        except OSError:
            continue

    for slot in (studio.get("slots") or []):
        for key in ("model_path", "mmproj_path", "draft_model_path"):
            val = str(slot.get(key) or "").strip()
            if val and val.lower().endswith(".gguf"):
                p = Path(val).expanduser()
                if p.is_file():
                    _add_gguf(p)

    items = list(found.values())
    kind_rank = {"model": 0, "mmproj": 1, "drafter": 2}
    items.sort(key=lambda x: (kind_rank.get(x["kind"], 9), -float(x.get("mtime", 0))))
    return items


def _filesystem_roots(studio: dict[str, Any]) -> list[dict[str, str]]:
    candidates = [
        ("Home", str(Path.home())),
        ("Downloads", str(Path.home() / "Downloads")),
        ("Desktop", str(Path.home() / "Desktop")),
        ("Documents", str(Path.home() / "Documents")),
        ("Models", str(Path.home() / "models")),
        ("HuggingFace", str(Path.home() / ".cache" / "huggingface" / "hub")),
        ("Unsloth", str(Path.home() / ".unsloth")),
        ("Volumes", "/Volumes"),
        ("Root /", "/"),
    ]
    seen: set[str] = set()
    roots: list[dict[str, str]] = []
    for label, pstr in candidates:
        p = Path(pstr)
        if p.is_dir() and pstr not in seen:
            seen.add(pstr)
            roots.append({"label": label, "path": pstr})
    for raw_dir in (studio.get("extra_scan_dirs") or []):
        if not isinstance(raw_dir, str) or not raw_dir.strip():
            continue
        p = Path(raw_dir.strip()).expanduser()
        pstr = str(p)
        if p.is_dir() and pstr not in seen:
            seen.add(pstr)
            roots.append({"label": p.name or pstr, "path": pstr})
    return roots


def list_directory(dir_path: str = "", filter_mode: str = ".gguf") -> dict[str, Any]:
    studio = load_studio_config()
    roots = _filesystem_roots(studio)
    raw = (dir_path or "").strip()
    target = Path(raw).expanduser() if raw else Path.home()
    if target.is_file():
        target = target.parent

    if not target.is_dir():
        parent_guess = str(target.parent) if target.parent != target else str(Path.home())
        return {
            "ok": False,
            "error": f"Directory not found: {target}",
            "path": str(target),
            "parent": parent_guess,
            "roots": roots,
            "entries": [],
        }

    try:
        resolved = target.resolve()
    except OSError:
        resolved = target

    parent = str(resolved.parent) if resolved.parent != resolved else ""
    mode = (filter_mode or ".gguf").strip().lower()
    dirs_list: list[dict[str, Any]] = []
    files_list: list[dict[str, Any]] = []

    try:
        with os.scandir(resolved) as it:
            for entry in it:
                name = entry.name
                if name == ".DS_Store":
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    st = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
                if is_dir:
                    dirs_list.append({
                        "name": name,
                        "path": str(resolved / name),
                        "is_dir": True,
                        "size_bytes": 0,
                        "mtime": st.st_mtime,
                    })
                else:
                    lower = name.lower()
                    is_exec = os.access(entry.path, os.X_OK)
                    if mode == ".gguf":
                        if not lower.endswith(".gguf") or ".inprogress" in lower:
                            continue
                    elif mode == "binary":
                        if not (is_exec or "llama-server" in lower):
                            continue
                        if lower.endswith((".dylib", ".so", ".a", ".o", ".txt", ".md", ".cmake")):
                            continue
                    files_list.append({
                        "name": name,
                        "path": str(resolved / name),
                        "is_dir": False,
                        "size_bytes": st.st_size,
                        "size_gib": round(st.st_size / (1024 ** 3), 2),
                        "mtime": st.st_mtime,
                        "is_gguf": lower.endswith(".gguf"),
                        "executable": is_exec,
                    })
    except PermissionError:
        return {
            "ok": False,
            "error": f"Permission denied: {resolved}",
            "path": str(resolved),
            "parent": parent,
            "roots": roots,
            "entries": [],
        }
    except OSError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": str(resolved),
            "parent": parent,
            "roots": roots,
            "entries": [],
        }

    dirs_list.sort(key=lambda x: (x["name"].startswith("."), x["name"].lower()))
    files_list.sort(key=lambda x: (-float(x["mtime"]), x["name"].lower()))

    combined = dirs_list + files_list
    max_entries = 500
    truncated = len(combined) > max_entries
    return {
        "ok": True,
        "path": str(resolved),
        "parent": parent,
        "roots": roots,
        "entries": combined[:max_entries],
        "truncated": truncated,
    }


def inspect_gguf_path(path_str: str) -> dict[str, Any]:
    raw = (path_str or "").strip()
    if not raw:
        return {"ok": False, "error": "Missing path"}
    p = Path(raw).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {p}"}
    meta = read_gguf_metadata(str(p))
    meta["display_path"] = str(p)
    if p.name.lower().endswith(".gguf"):
        with _STUDIO_LOCK:
            data = load_studio_config()
            if _remember_extra_scan_dir(data, str(p)):
                save_studio_config(data)
    return {"ok": True, "info": meta}


def pick_native_file(filter_mode: str = ".gguf") -> dict[str, Any]:
    mode = (filter_mode or ".gguf").strip().lower()
    prompt_text = "Select GGUF File (.gguf)" if mode == ".gguf" else "Select Inference Engine Binary"
    if sys.platform != "darwin":
        if shutil.which("zenity"):
            try:
                res = subprocess.run(
                    ["zenity", "--file-selection", f"--title={prompt_text}"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if res.returncode != 0:
                    return {"ok": False, "canceled": True, "error": "Selection canceled"}
                picked = (res.stdout or "").strip()
                if not picked:
                    return {"ok": False, "canceled": True, "error": "No file selected"}
                out_z: dict[str, Any] = {"ok": True, "path": picked}
                if picked.lower().endswith(".gguf"):
                    inspected = inspect_gguf_path(picked)
                    if inspected.get("ok"):
                        out_z["info"] = inspected["info"]
                return out_z
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "Native OS file dialog requires macOS or zenity; please use the built-in Browse Files modal."}

    script = f'POSIX path of (choose file with prompt "{prompt_text}")'
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Finder dialog timed out"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if res.returncode != 0:
        err = (res.stderr or "").strip()
        if "User canceled" in err or "-128" in err:
            return {"ok": False, "canceled": True, "error": "Selection canceled"}
        return {"ok": False, "error": err or "Finder selection failed"}

    picked = (res.stdout or "").strip()
    if not picked:
        return {"ok": False, "canceled": True, "error": "No file selected"}

    out: dict[str, Any] = {"ok": True, "path": picked}
    if picked.lower().endswith(".gguf"):
        inspected = inspect_gguf_path(picked)
        if inspected.get("ok"):
            out["info"] = inspected["info"]
    return out


_ENGINE_CACHE: Optional[list[dict[str, Any]]] = None


def discover_engines(refresh: bool = False) -> list[dict[str, Any]]:
    global _ENGINE_CACHE
    if _ENGINE_CACHE is not None and not refresh:
        return _ENGINE_CACHE
    engines = []
    for cand in ENGINE_CANDIDATES:
        p = Path(cand["path"])
        available = p.is_file() and os.access(p, os.X_OK)
        version = ""
        if available:
            try:
                res = subprocess.run([str(p), "--version"], capture_output=True, text=True, timeout=3)
                out = (res.stdout or res.stderr or "").strip().splitlines()
                version = out[0] if out else "available"
            except Exception:
                version = "available"
        engines.append({
            "id": cand["id"],
            "label": cand["label"],
            "path": cand["path"],
            "available": available,
            "version": version,
        })
    _ENGINE_CACHE = engines
    return engines


# ── Memory Estimation & Command Builder ──────────────────────────────────────

def get_total_ram_gib() -> float:
    if sys.platform == "darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return round(int(res.stdout.strip()) / (1024 ** 3), 1)
        except Exception:
            pass
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(re.findall(r"\d+", line)[0])
                    return round((kb * 1024) / (1024 ** 3), 1)
        except Exception:
            pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
            return round((pages * page_size) / (1024 ** 3), 1)
    except Exception:
        pass
    return 64.0


def estimate_slot_memory(slot: dict[str, Any], meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if meta is None:
        meta = read_gguf_metadata(slot.get("model_path", ""))
    weights_gib = float(meta.get("size_gib") or 0.0)
    if weights_gib == 0.0:
        weights_gib = 16.0

    mmproj_gib = 0.0
    if slot.get("mmproj_enabled") and slot.get("mmproj_path"):
        mp = Path(slot["mmproj_path"])
        if mp.is_file():
            mmproj_gib = round(mp.stat().st_size / (1024 ** 3), 2)

    draft_gib = 0.0
    if slot.get("speculative_mode") == "dspark" and slot.get("draft_model_path"):
        dp = Path(slot["draft_model_path"])
        if dp.is_file():
            draft_gib = round(dp.stat().st_size / (1024 ** 3), 2)

    ctx = int(slot.get("ctx_size") or 32768)
    slots_n = max(1, int(slot.get("parallel_slots") or 1))
    kv_dtype = str(slot.get("kv_cache_type") or "f16").lower()
    dtype_mult = 1.0 if kv_dtype == "f16" else (0.55 if kv_dtype == "q8_0" else 0.30)

    arch = str(meta.get("architecture") or "").lower()
    if "inkling2" in arch:
        # 8 global full-attn layers (GQA-8, head_dim 128) + 40 SWA-1024 layers (~0.24 GiB)
        kv_base_64k = 2.24
    else:
        blocks = int(meta.get("block_count") or 32)
        # Typical GQA-8/head_dim=128 F16 KV ~ 0.125 MiB per token per 32 layers -> ~8 GiB @ 64k
        kv_base_64k = max(1.0, (blocks / 32.0) * 6.0)

    kv_cache_gib = round(kv_base_64k * (ctx / 65536.0) * slots_n * dtype_mult, 2)
    compute_gib = round(1.5 + (2.5 if "inkling2" in arch else 0.8) * min(2.0, ctx / 65536.0), 2)
    total_gib = round(weights_gib + mmproj_gib + draft_gib + kv_cache_gib + compute_gib, 2)

    return {
        "weights_gib": round(weights_gib, 2),
        "mmproj_gib": mmproj_gib,
        "draft_gib": draft_gib,
        "kv_cache_gib": kv_cache_gib,
        "compute_gib": compute_gib,
        "total_gib": total_gib,
    }


def build_slot_argv(slot: dict[str, Any], include_sandbox: bool = True) -> list[str]:
    binary = str(slot.get("binary") or _default_binary()).strip()
    if not (Path(binary).is_file() and os.access(binary, os.X_OK)):
        binary = _default_binary()

    argv: list[str] = [
        binary,
        "-m", str(slot.get("model_path") or ""),
    ]

    if slot.get("mmproj_enabled") and slot.get("mmproj_path"):
        argv.extend(["--mmproj", str(slot["mmproj_path"])])

    spec_mode = str(slot.get("speculative_mode") or "auto")
    if spec_mode == "dspark" and slot.get("draft_model_path"):
        argv.extend([
            "--model-draft", str(slot["draft_model_path"]),
            "--spec-type", "draft-dspark",
            "--spec-draft-n-max", str(int(slot.get("draft_n_max") or 2)),
            "--spec-draft-p-min", "0",
            "-ngld", str(int(slot.get("gpu_layers") or 99)),
        ])
    elif spec_mode == "auto":
        argv.append("--spec-default")

    argv.extend([
        "--host", "0.0.0.0",
        "--port", str(int(slot.get("port") or 8090)),
        "--alias", str(slot.get("target_alias") or slot.get("alias") or slot.get("id") or "model"),
        "-ngl", str(int(slot.get("gpu_layers") if slot.get("gpu_layers") is not None else 99)),
        "-fa", "on" if slot.get("flash_attn", True) else "off",
    ])

    kv_type = str(slot.get("kv_cache_type") or "f16").lower()
    if kv_type in ("q8_0", "q4_0"):
        argv.extend(["-ctk", kv_type, "-ctv", kv_type])

    argv.append("--context-shift" if slot.get("context_shift") else "--no-context-shift")

    ckpt = int(slot.get("ctx_checkpoints") if slot.get("ctx_checkpoints") is not None else 20)
    if ckpt >= 0:
        argv.extend(["--ctx-checkpoints", str(ckpt)])

    argv.append("--reasoning-preserve" if slot.get("reasoning_preserve") else "--no-reasoning-preserve")

    rb = int(slot.get("reasoning_budget") if slot.get("reasoning_budget") is not None else -1)
    if rb >= 0:
        argv.extend(["--reasoning-budget", str(rb)])

    argv.extend([
        "-c", str(int(slot.get("ctx_size") or 65536)),
        "-np", str(max(1, int(slot.get("parallel_slots") or 1))),
        "-t", str(max(1, int(slot.get("threads") or 8))),
        "-tb", str(max(1, int(slot.get("threads_batch") or 10))),
    ])

    bs = int(slot.get("batch_size") or 0)
    ubs = int(slot.get("ubatch_size") or 0)
    if bs > 0:
        argv.extend(["-b", str(bs)])
    if ubs > 0:
        argv.extend(["-ub", str(ubs)])

    n_pred = int(slot.get("n_predict") if slot.get("n_predict") is not None else -1)
    if n_pred > 0:
        argv.extend(["--n-predict", str(n_pred)])

    argv.append("--jinja")

    effort = str(slot.get("reasoning_effort") or "").strip()
    if effort:
        argv.extend(["--chat-template-kwargs", json.dumps({"reasoning_effort": effort})])

    extra = str(slot.get("extra_args") or "").strip()
    if extra:
        try:
            argv.extend(shlex.split(extra))
        except ValueError:
            pass

    if include_sandbox and slot.get("sandbox") and SANDBOX_PROFILE.is_file() and shutil.which("sandbox-exec"):
        argv = ["sandbox-exec", "-f", str(SANDBOX_PROFILE)] + argv

    return argv


def build_shell_command(slot: dict[str, Any], include_sandbox: bool = False) -> str:
    return " ".join(shlex.quote(arg) for arg in build_slot_argv(slot, include_sandbox=include_sandbox))


# ── Telemetry & Log Parsing ──────────────────────────────────────────────────

def _listening_pids(port: int) -> list[int]:
    if shutil.which("lsof"):
        try:
            res = subprocess.run(
                ["lsof", "-sTCP:LISTEN", "-ti", f":{int(port)}"],
                capture_output=True, text=True, timeout=2,
            )
            pids = [int(ln.strip()) for ln in (res.stdout or "").splitlines() if ln.strip().isdigit()]
            if pids:
                return pids
        except Exception:
            pass
    if shutil.which("ss"):
        try:
            res = subprocess.run(
                ["ss", "-ltnp", f"sport = :{int(port)}"],
                capture_output=True, text=True, timeout=2,
            )
            return sorted({int(m) for m in re.findall(r"pid=(\d+)", res.stdout or "")})
        except Exception:
            pass
    return []


def _probe_health(port: int) -> str:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{int(port)}/health", method="GET")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            if resp.status == 200:
                return "running"
            return "loading"
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return "loading"
        return "running"
    except Exception:
        return "stopped"


def _parse_log_timings(log_path: Path, max_entries: int = 8) -> dict[str, Any]:
    out: dict[str, Any] = {
        "last_tg_tok_s": None,
        "last_pp_tok_s": None,
        "last_e2e_tok_s": None,
        "last_draft_acc": None,
        "history": [],
    }
    if not log_path.is_file():
        return out
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            if size > 131072:
                f.seek(size - 131072)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return out

    pp_re = re.compile(r"prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens\s*\([^,]+,\s*([\d.]+)\s*tokens per second")
    tg_re = re.compile(r"\beval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens\s*\([^,]+,\s*([\d.]+)\s*tokens per second")
    live_tg_re = re.compile(r"n_gen\s*=\s*\d+,\s*tg\s*=\s*([\d.]+)\s*t/s")
    draft_re = re.compile(r"draft acceptance\s*=\s*([\d.]+)\s*\(([^)]+)\)")

    history = []
    last_pp = None
    last_pp_ms = 0.0
    for line in text.splitlines():
        mp = pp_re.search(line)
        if mp:
            last_pp_ms = float(mp.group(1))
            last_pp = round(float(mp.group(3)), 1)
            out["last_pp_tok_s"] = last_pp
            continue
        mt = tg_re.search(line)
        if mt:
            tg_ms = float(mt.group(1))
            toks = int(mt.group(2))
            tg = round(float(mt.group(3)), 1)
            total_s = max(0.001, (last_pp_ms + tg_ms) / 1000.0)
            e2e = round(toks / total_s, 1)
            out["last_tg_tok_s"] = tg
            out["last_e2e_tok_s"] = e2e
            history.append({"tokens": toks, "tg_tok_s": tg, "pp_tok_s": last_pp, "e2e_tok_s": e2e})
            last_pp_ms = 0.0
        else:
            ml = live_tg_re.search(line)
            if ml:
                out["last_tg_tok_s"] = round(float(ml.group(1)), 1)
        md = draft_re.search(line)
        if md:
            out["last_draft_acc"] = round(float(md.group(1)) * 100, 1)

    out["history"] = history[-max_entries:]
    return out


def get_slot_live_info(slot: dict[str, Any]) -> dict[str, Any]:
    port = int(slot.get("port") or 8090)
    pids = _listening_pids(port)
    rss_gib = 0.0
    cpu_pct = 0.0
    uptime = ""
    cmd_line = ""
    if pids:
        try:
            res = subprocess.run(
                ["ps", "-o", "pid=,rss=,pcpu=,etime=,command=", "-p", str(pids[0])],
                capture_output=True, text=True, timeout=2,
            )
            line = (res.stdout or "").strip()
            parts = line.split(None, 4)
            if len(parts) >= 4:
                rss_gib = round(int(parts[1]) / (1024 * 1024), 2)
                cpu_pct = float(parts[2])
                uptime = parts[3]
                cmd_line = parts[4] if len(parts) > 4 else ""
        except Exception:
            pass
    health = _probe_health(port) if pids else "stopped"
    if pids and health == "stopped":
        health = "loading"
    log_path = LOGS_DIR / str(slot.get("log_file") or f"llama-{slot['id']}.log")
    timings = _parse_log_timings(log_path)
    meta = read_gguf_metadata(slot.get("model_path", ""))
    mem_est = estimate_slot_memory(slot, meta)
    return {
        "status": health,
        "pid": pids[0] if pids else None,
        "rss_gib": rss_gib,
        "cpu_pct": cpu_pct,
        "uptime": uptime,
        "running_cmd": cmd_line,
        "timings": timings,
        "model_meta": meta,
        "memory_estimate": mem_est,
        "command_preview": build_shell_command(slot, include_sandbox=True),
    }


def _sync_studio_env(slots: list[dict[str, Any]]) -> None:
    lines = [
        "# AUTO-GENERATED BY PROJECT-MALARIA MODEL STUDIO (pipeline/model_studio.py)",
        "# Sourced at the end of pipeline/mac/llama.env so start.command / run-models.command",
        "# always use the exact settings saved in http://localhost:3000/models.",
        "",
    ]
    by_id = {s["id"]: s for s in slots}
    if "orchestrator" in by_id:
        s = by_id["orchestrator"]
        lines.append(f"export ORCHESTRATOR_MODEL_FILE={shlex.quote(str(s.get('model_path') or ''))}")
        lines.append(f"export LLAMA_PORT={int(s.get('port') or 8090)}")
        lines.append(f"export LLAMA_CMD={shlex.quote(build_shell_command(s, include_sandbox=False))}")
    if "specialist" in by_id:
        s = by_id["specialist"]
        lines.append(f"export SPECIALIST_MODEL_FILE={shlex.quote(str(s.get('model_path') or ''))}")
        lines.append(f"export LLAMA_PORT_SPECIALIST={int(s.get('port') or 8091)}")
        lines.append(f"export SPECIALIST_SANDBOX={'1' if s.get('sandbox') else '0'}")
        lines.append(f"export LLAMA_CMD_SPECIALIST={shlex.quote(build_shell_command(s, include_sandbox=False))}")
    if "summarizer" in by_id:
        s = by_id["summarizer"]
        lines.append(f"export SUMMARIZER_MODEL_FILE={shlex.quote(str(s.get('model_path') or ''))}")
        lines.append(f"export LLAMA_PORT_SUMMARIZER={int(s.get('port') or 8092)}")
        lines.append(f"export LLAMA_CMD_SUMMARIZER={shlex.quote(build_shell_command(s, include_sandbox=False))}")
    if "vision" in by_id:
        s = by_id["vision"]
        lines.append(f"export VISION_MODEL_FILE={shlex.quote(str(s.get('model_path') or ''))}")
        lines.append(f"export VISION_MMPROJ_FILE={shlex.quote(str(s.get('mmproj_path') or ''))}")
        lines.append(f"export LLAMA_PORT_VISION={int(s.get('port') or 8093)}")
        lines.append(f"export LLAMA_CMD_VISION={shlex.quote(build_shell_command(s, include_sandbox=False))}")

    STUDIO_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sync_downstream(slots: list[dict[str, Any]]) -> dict[str, Any]:
    import control_plane

    cfg = control_plane.load_node_config()
    models = cfg.setdefault("models", {})
    for s in slots:
        nkey = s.get("node_config_key") or s["id"]
        entry = models.get(nkey) or {}
        entry["enabled"] = bool(s.get("enabled", True))
        entry["label"] = s.get("label") or entry.get("label") or nkey
        entry["type"] = "local_llama"
        entry["alias"] = s.get("alias") or entry.get("alias") or nkey
        if s.get("aliases"):
            entry["aliases"] = list(s["aliases"])
        entry["port"] = int(s.get("port") or 8090)
        entry["api_base"] = f"http://host.docker.internal:{entry['port']}/v1"
        entry["api_key"] = entry.get("api_key") or "sk-local"
        talias = s.get("target_alias") or entry["alias"]
        entry["target_model"] = f"openai/{talias}"
        if s.get("mmproj_enabled"):
            entry["supports_vision"] = True
        elif s["id"] != "vision":
            entry["supports_vision"] = False
        if s["id"] == "orchestrator":
            mname = Path(str(s.get("model_path") or "")).stem or "Orchestrator"
            entry["dsh_display_name"] = f"{mname} (:{entry['port']})"
        models[nkey] = entry

    harnesses = cfg.setdefault("harnesses", {})
    if "qwen-code" in harnesses and harnesses["qwen-code"].get("default_model") == "flint":
        harnesses["qwen-code"]["default_model"] = "orchestrator"

    res = control_plane.sync_all_configs(cfg)
    _sync_studio_env(slots)
    return res


def get_full_state() -> dict[str, Any]:
    import control_plane

    studio = load_studio_config()
    node_cfg = control_plane.load_node_config()
    slots_out = []
    total_live_rss = 0.0
    total_est_gib = 0.0
    for s in studio.get("slots", []):
        live = get_slot_live_info(s)
        total_live_rss += live["rss_gib"]
        if live["status"] in ("running", "loading"):
            total_est_gib += live["memory_estimate"]["total_gib"]
        slots_out.append({**s, "live": live})

    cloud_models = []
    for k, m in (node_cfg.get("models") or {}).items():
        if m.get("type") == "cloud":
            env_name = str(m.get("api_key_env") or "")
            has_key = bool(os.environ.get(env_name) or m.get("api_key") or _env_file_has_key(env_name))
            cloud_models.append({
                "id": k,
                "enabled": bool(m.get("enabled", True)),
                "label": m.get("label") or k,
                "alias": m.get("alias") or k,
                "aliases": m.get("aliases") or [m.get("alias") or k],
                "api_base": m.get("api_base") or "",
                "api_key_env": env_name,
                "target_model": m.get("target_model") or "",
                "supports_vision": bool(m.get("supports_vision", False)),
                "sensitive_safe": bool(m.get("sensitive_safe", False)),
                "has_key": has_key,
            })

    total_ram = get_total_ram_gib()
    return {
        "ok": True,
        "system": {
            "total_ram_gib": total_ram,
            "active_rss_gib": round(total_live_rss, 2),
            "active_estimated_gib": round(total_est_gib, 2),
        },
        "engines": discover_engines(),
        "ggufs": scan_gguf_files(),
        "slots": slots_out,
        "cloud_models": cloud_models,
        "harnesses": node_cfg.get("harnesses") or {},
        "gateway": node_cfg.get("gateway") or {},
    }


def _env_file_has_key(env_name: str) -> bool:
    if not env_name:
        return False
    env_file = HERE / ".env"
    if not env_file.is_file():
        return False
    try:
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(f"{env_name}="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return bool(val)
    except OSError:
        pass
    return False


_EDITABLE_SLOT_FIELDS = {
    "label",
    "enabled",
    "binary",
    "model_path",
    "mmproj_enabled",
    "mmproj_path",
    "ctx_size",
    "gpu_layers",
    "kv_cache_type",
    "speculative_mode",
    "draft_model_path",
    "draft_n_max",
    "parallel_slots",
    "batch_size",
    "ubatch_size",
    "threads",
    "threads_batch",
    "reasoning_effort",
    "reasoning_preserve",
    "reasoning_budget",
    "ctx_checkpoints",
    "context_shift",
    "flash_attn",
    "sandbox",
    "n_predict",
    "extra_args",
    "alias",
    "target_alias",
    "aliases",
}


def _normalize_aliases(val: Any) -> list[str]:
    if isinstance(val, str):
        raw_items = [x.strip() for x in val.split(",")]
    elif isinstance(val, list):
        raw_items = [str(x).strip() for x in val]
    else:
        return []
    return list(dict.fromkeys(x for x in raw_items if x))


def save_slot(slot_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _STUDIO_LOCK:
        data = load_studio_config()
        target = None
        for s in data["slots"]:
            if s["id"] == slot_id:
                target = s
                break
        if target is None:
            return {"ok": False, "error": f"Unknown slot: {slot_id}"}

        old_aliases = list(target.get("aliases") or [])
        old_alias = str(target.get("alias") or "")
        old_enabled = bool(target.get("enabled", True))

        for k, v in (patch or {}).items():
            if k not in _EDITABLE_SLOT_FIELDS:
                continue
            if k == "aliases":
                target[k] = _normalize_aliases(v)
            else:
                target[k] = v

        for pkey in ("model_path", "mmproj_path", "draft_model_path"):
            pval = str(target.get(pkey) or "").strip()
            if pval and pval.lower().endswith(".gguf"):
                _remember_extra_scan_dir(data, pval)

        save_studio_config(data)
        slots_snapshot = list(data["slots"])

    sync_res = _sync_downstream(slots_snapshot)
    aliases_changed = (
        old_aliases != list(target.get("aliases") or [])
        or old_alias != str(target.get("alias") or "")
        or old_enabled != bool(target.get("enabled", True))
        or bool((patch or {}).get("restart_litellm"))
    )
    litellm_status = _restart_litellm_best_effort() if aliases_changed else "unchanged"
    return {
        "ok": True,
        "slot": {**target, "live": get_slot_live_info(target)},
        "sync": sync_res,
        "litellm": litellm_status,
    }


def slot_preset(slot_id: str, action: str, name: str, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data = load_studio_config()
    target = next((s for s in data["slots"] if s["id"] == slot_id), None)
    if target is None:
        return {"ok": False, "error": f"Unknown slot: {slot_id}"}
    presets = target.setdefault("presets", {})
    clean_name = str(name or "").strip()
    if not clean_name:
        return {"ok": False, "error": "Preset name is required"}

    if action == "save":
        snap = {k: (config or target).get(k, target.get(k)) for k in _EDITABLE_SLOT_FIELDS if k != "presets"}
        presets[clean_name] = snap
        save_studio_config(data)
        return {"ok": True, "presets": presets}
    if action == "delete":
        presets.pop(clean_name, None)
        save_studio_config(data)
        return {"ok": True, "presets": presets}
    if action == "apply":
        snap = presets.get(clean_name)
        if not snap:
            return {"ok": False, "error": f"Preset not found: {clean_name}"}
        return save_slot(slot_id, snap)
    return {"ok": False, "error": f"Unknown preset action: {action}"}


def _stop_port(port: int) -> list[int]:
    pids = _listening_pids(port)
    if not pids:
        return []
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(12):
        if not _listening_pids(port):
            return pids
        time.sleep(0.25)
    for pid in _listening_pids(port):
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    time.sleep(0.5)
    return pids


def slot_action(slot_id: str, action: str) -> dict[str, Any]:
    data = load_studio_config()
    target = next((s for s in data["slots"] if s["id"] == slot_id), None)
    if target is None:
        return {"ok": False, "error": f"Unknown slot: {slot_id}"}

    port = int(target.get("port") or 8090)
    log_path = LOGS_DIR / str(target.get("log_file") or f"llama-{slot_id}.log")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if action == "stop":
        killed = _stop_port(port)
        return {"ok": True, "action": "stop", "killed": killed, "live": get_slot_live_info(target)}

    if action in ("start", "reload"):
        if action == "reload":
            _stop_port(port)
        elif _listening_pids(port):
            return {"ok": True, "action": "start", "note": "already_running", "live": get_slot_live_info(target)}

        mpath = Path(str(target.get("model_path") or ""))
        if not mpath.is_file():
            return {"ok": False, "error": f"Model file not found: {mpath}"}

        argv = build_slot_argv(target, include_sandbox=True)
        lf = open(log_path, "w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                argv,
                stdout=lf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            lf.close()

        # Poll briefly so fast models report "running" and early crashes are caught immediately
        for _ in range(16):
            rc = proc.poll()
            if rc is not None:
                tail = ""
                try:
                    tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
                except OSError:
                    pass
                return {
                    "ok": False,
                    "error": f"llama-server exited early (code {rc})",
                    "log_tail": tail,
                    "live": get_slot_live_info(target),
                }
            if _probe_health(port) == "running":
                break
            time.sleep(0.25)

        return {"ok": True, "action": action, "pid": proc.pid, "live": get_slot_live_info(target)}

    return {"ok": False, "error": f"Unknown action: {action}"}


def get_slot_logs(slot_id: str, lines: int = 120) -> dict[str, Any]:
    data = load_studio_config()
    target = next((s for s in data["slots"] if s["id"] == slot_id), None)
    if target is None:
        return {"ok": False, "error": f"Unknown slot: {slot_id}"}
    log_path = LOGS_DIR / str(target.get("log_file") or f"llama-{slot_id}.log")
    timings = _parse_log_timings(log_path, max_entries=12)
    text = ""
    if log_path.is_file():
        try:
            all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            text = "\n".join(all_lines[-max(10, min(500, lines)):])
        except OSError as e:
            text = f"Error reading log: {e}"
    return {"ok": True, "log_file": str(log_path), "text": text, "timings": timings}


def test_slot(slot_id: str, prompt: Optional[str] = None) -> dict[str, Any]:
    data = load_studio_config()
    target = next((s for s in data["slots"] if s["id"] == slot_id), None)
    if target is None:
        return {"ok": False, "error": f"Unknown slot: {slot_id}"}
    port = int(target.get("port") or 8090)
    alias = str(target.get("target_alias") or target.get("alias") or slot_id)
    user_prompt = (prompt or "").strip() or "ตอบสั้นๆ 1 ประโยคว่าพร้อมทำงานแล้ว"
    payload = json.dumps({
        "model": alias,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": 160,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        wall_s = round(time.time() - t0, 2)
        timings = res.get("timings") or {}
        choice = (res.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return {
            "ok": True,
            "wall_s": wall_s,
            "pp_tok_s": round(float(timings.get("prompt_per_second") or 0), 1),
            "tg_tok_s": round(float(timings.get("predicted_per_second") or 0), 1),
            "predicted_n": timings.get("predicted_n"),
            "content": (msg.get("content") or "").strip(),
            "reasoning": (msg.get("reasoning_content") or "").strip(),
            "live": get_slot_live_info(target),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "wall_s": round(time.time() - t0, 2)}


def _restart_litellm_best_effort() -> str:
    try:
        res = subprocess.run(
            ["docker", "restart", "pipeline-litellm-1"],
            capture_output=True, text=True, timeout=15,
        )
        return "restarted" if res.returncode == 0 else (res.stderr or "").strip()
    except Exception as e:
        return str(e)


def save_cloud_model(body: dict[str, Any]) -> dict[str, Any]:
    import control_plane

    key = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(body.get("id") or body.get("alias") or "").strip()).strip("-")
    if not key:
        return {"ok": False, "error": "Provider ID/alias is required"}

    cfg = control_plane.load_node_config()
    models = cfg.setdefault("models", {})
    existing = models.get(key) or {}
    alias = str(body.get("alias") or key).strip()
    aliases = body.get("aliases")
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.split(",") if a.strip()]
    if not aliases:
        aliases = [alias]

    entry = {
        **existing,
        "enabled": bool(body.get("enabled", True)),
        "label": str(body.get("label") or key),
        "type": "cloud",
        "alias": alias,
        "aliases": aliases,
        "api_base": str(body.get("api_base") or "").strip(),
        "target_model": str(body.get("target_model") or f"openai/{alias}").strip(),
        "expose_in_dsh": True,
        "dsh_display_name": str(body.get("label") or key),
        "supports_vision": bool(body.get("supports_vision", False)),
        "sensitive_safe": bool(body.get("sensitive_safe", False)),
    }
    if not entry["api_base"]:
        entry.pop("api_base", None)

    api_key_env = str(body.get("api_key_env") or "").strip()
    api_key_val = str(body.get("api_key") or "").strip()
    if api_key_env:
        entry["api_key_env"] = api_key_env
        entry.pop("api_key", None)
    elif api_key_val:
        entry["api_key"] = api_key_val
        entry.pop("api_key_env", None)

    models[key] = entry
    sync_res = control_plane.sync_all_configs(cfg)
    litellm_status = _restart_litellm_best_effort()
    return {"ok": True, "id": key, "sync": sync_res, "litellm": litellm_status}


def delete_cloud_model(model_id: str) -> dict[str, Any]:
    import control_plane

    cfg = control_plane.load_node_config()
    models = cfg.get("models") or {}
    if model_id not in models or models[model_id].get("type") != "cloud":
        return {"ok": False, "error": f"Cloud provider not found: {model_id}"}
    del models[model_id]
    sync_res = control_plane.sync_all_configs(cfg)
    litellm_status = _restart_litellm_best_effort()
    return {"ok": True, "deleted": model_id, "sync": sync_res, "litellm": litellm_status}
