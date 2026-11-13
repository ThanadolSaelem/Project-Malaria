#!/usr/bin/env python3
"""
vFlat tool pack — Document dewarp / enhance + Vision OCR (router & n8n side)
=============================================================================
Pluggable tool module exposing `vflat_scan_document` and `vision_read_image` so
any harness (n8n, DeepSeek-Harness, HarnessRouter) or HexStrike router can turn
document scanning & Vision OCR on or off as a node without touching code.
"""
from __future__ import annotations

import base64
import inspect
import json
import mimetypes
import os
import urllib.error
import urllib.request

VFLAT_URL = os.environ.get("VFLAT_URL", "http://vflat-scan:8000")
LITELLM_BASE = os.environ.get("LITELLM_BASE", "http://litellm:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_KEY", "sk-local")
VISION_MODEL = os.environ.get("VISION_MODEL", "vision")
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", "/evidence")


def _resolve_path(path: str, default_dir: str = EVIDENCE_DIR) -> str:
    if os.path.isabs(path) and os.path.exists(path):
        return path
    cand = os.path.join(default_dir, os.path.basename(path))
    if os.path.exists(cand):
        return cand
    local_ev = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence", os.path.basename(path))
    if os.path.exists(local_ev):
        return local_ev
    return path


def _find_vflat_base() -> str | None:
    for b in [VFLAT_URL, "http://vflat-scan:8000", "http://host.docker.internal:8006", "http://localhost:8006"]:
        if not b:
            continue
        b = b.rstrip("/")
        try:
            urllib.request.urlopen(b + "/healthz", timeout=3)
            return b
        except Exception:
            continue
    return None


def _find_litellm_base() -> str | None:
    for b in [LITELLM_BASE, "http://litellm:4000/v1", "http://host.docker.internal:4000/v1", "http://localhost:4000/v1"]:
        if not b:
            continue
        b = b.rstrip("/")
        try:
            urllib.request.urlopen(b + "/models", timeout=3)
            return b
        except urllib.error.HTTPError:
            return b
        except Exception:
            continue
    return None


def vflat_scan_document(
    image_path: str,
    out_filename: str = "",
    dewarp: bool = True,
    ocr_with_vision: bool = False,
    vision_prompt: str = "อ่านทุกข้อความที่เห็นในภาพให้ครบ แล้วสรุปสาระสำคัญเป็นภาษาไทย",
) -> str:
    """[EVIDENCE/OCR] Flatten, dewarp, remove shadows, and sharpen a document photo/PDF via vFlat, optionally running Vision OCR.

    Args:
      image_path: filename under /evidence or absolute path to a photo (.jpg/.png) or .pdf.
      out_filename: output filename under /evidence (default: <name>.scanned.jpg).
      dewarp: True for full 3D page dewarping + shadow removal; False for shadow/contrast enhance only.
      ocr_with_vision: if True, sends the cleaned image to the local Vision model (Qwen2.5-VL) to read text.
      vision_prompt: question/instruction for the Vision model when ocr_with_vision=True.
    """
    src = _resolve_path(image_path)
    if not os.path.exists(src):
        return f"ERROR: file not found: {image_path} (checked {src})"

    base = _find_vflat_base()
    if not base:
        return "ERROR: vflat-scan service is not reachable (:8000 / :8006). Enable/start the vflat node first."

    with open(src, "rb") as f:
        raw = f.read()

    q = "?dewarp=true" if dewarp else "?dewarp=false"
    boundary = "----vflatboundary7f3a"
    fname = os.path.basename(src)
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + raw + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{base}/scan{q}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            cleaned = r.read()
    except Exception as e:
        return f"ERROR: vFlat scan failed ({type(e).__name__}: {e})"

    out_dir = EVIDENCE_DIR if os.path.isdir(EVIDENCE_DIR) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
    os.makedirs(out_dir, exist_ok=True)
    if not out_filename:
        stem, ext = os.path.splitext(fname)
        out_filename = f"{stem}.scanned.pdf" if ext.lower() == ".pdf" else f"{stem}.scanned.jpg"
    out_path = os.path.join(out_dir, os.path.basename(out_filename))
    with open(out_path, "wb") as f:
        f.write(cleaned)

    msg = f"saved scanned document to {out_path} ({len(cleaned)} bytes, dewarp={dewarp})"
    if ocr_with_vision and not out_path.lower().endswith(".pdf"):
        ocr_text = vision_read_image(image_path=out_path, prompt=vision_prompt)
        msg += f"\n--- vision OCR ---\n{ocr_text}"
    return msg


def vision_read_image(
    image_path: str,
    prompt: str = "อ่านทุกข้อความที่เห็นในภาพให้ครบ แล้วสรุปสาระสำคัญเป็นภาษาไทย",
) -> str:
    """[VISION/OCR] Read text, layout, UI elements, or Thai/English documents from an image using the local Vision model (Qwen2.5-VL).

    Args:
      image_path: filename under /evidence or absolute path to an image (.png/.jpg).
      prompt: question or OCR instruction for the vision model.
    """
    src = _resolve_path(image_path)
    if not os.path.exists(src):
        return f"ERROR: image not found: {image_path} (checked {src})"

    gw = _find_litellm_base()
    if not gw:
        return "ERROR: LiteLLM gateway (:4000) not reachable."

    with open(src, "rb") as f:
        raw = f.read()
    mime = mimetypes.guess_type(src)[0] or "image/png"
    durl = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You read and understand images for an authorized security investigation. "
                    "Read ALL visible text verbatim (including Thai), describe layout/UI/evidence "
                    "faithfully, and do not invent anything not present in the image."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": durl}},
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        f"{gw}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LITELLM_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read())
        return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: vision model call failed ({type(e).__name__}: {e}). Is vision llama-server (:8093) running with --mmproj?"


TOOLS = [vflat_scan_document, vision_read_image]
DISPATCH = {fn.__name__: fn for fn in TOOLS}

_PY_JSON_TYPE = {
    int: "integer", "int": "integer",
    bool: "boolean", "bool": "boolean",
    float: "number", "float": "number",
    str: "string", "str": "string",
}


def json_schema(fn) -> dict:
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        entry = {"type": _PY_JSON_TYPE.get(p.annotation, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
        else:
            entry["default"] = p.default
        props[name] = entry
    return {"type": "object", "properties": props, "required": required}


def catalog_entries() -> list[tuple[str, str, dict, callable]]:
    return [(fn.__name__, inspect.getdoc(fn) or "", json_schema(fn), fn) for fn in TOOLS]


def register(mcp) -> int:
    for fn in TOOLS:
        mcp.tool()(fn)
    return len(TOOLS)
