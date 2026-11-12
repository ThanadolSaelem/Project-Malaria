#!/usr/bin/env python3
"""
report tool pack — TLP:AMBER .docx Report Assembler (router & n8n side)
=============================================================================
Pluggable tool module exposing `assemble_tlp_report` so any harness (n8n,
DeepSeek-Harness, HarnessRouter) or HexStrike router can assemble formatted
NCSA/TLP:AMBER .docx reports from JSON content + /evidence images without
touching code.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTING_DIR = os.environ.get(
    "REPORTING_DIR",
    "/reporting" if os.path.isdir("/reporting") else os.path.join(HERE, "reporting"),
)
REPORTS_DIR = os.environ.get(
    "REPORTS_DIR",
    "/reports" if os.path.isdir("/reports") else os.path.join(HERE, "reports"),
)
EVIDENCE_DIR = os.environ.get(
    "EVIDENCE_DIR",
    "/evidence" if os.path.isdir("/evidence") else os.path.join(HERE, "evidence"),
)


def assemble_tlp_report(
    report_name: str = "assessment_report",
    content_json: str = "",
    json_file_path: str = "",
) -> str:
    """[REPORTING] Assemble a formatted TLP:AMBER (.docx) security assessment report from JSON content and /evidence images.

    Provide EITHER `content_json` (a JSON string matching report_contract.md with `titles`, `date`, `blocks`)
    OR `json_file_path` (path to an existing .json file in /reports).
    Saves both `/reports/<report_name>.json` and `/reports/<report_name>.docx`.

    Args:
      report_name: output base filename (without extension, e.g. 'target_va_report').
      content_json: optional JSON string containing the report specification (`titles`, `date`, `blocks`).
      json_file_path: optional path to an existing JSON specification file.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    safe_name = os.path.basename(report_name or "assessment_report")
    for ext in (".docx", ".json"):
        if safe_name.lower().endswith(ext):
            safe_name = safe_name[: -len(ext)]

    spec_path = os.path.join(REPORTS_DIR, f"{safe_name}.json")
    out_docx = os.path.join(REPORTS_DIR, f"{safe_name}.docx")

    if content_json and content_json.strip():
        try:
            parsed = json.loads(content_json)
        except Exception as e:
            return f"ERROR: invalid content_json ({type(e).__name__}: {e})"
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
    elif json_file_path and json_file_path.strip():
        cand = json_file_path.strip()
        if not os.path.isabs(cand):
            cand = os.path.join(REPORTS_DIR, cand)
        if not os.path.exists(cand):
            return f"ERROR: json_file_path not found: {cand}"
        spec_path = cand
    elif not os.path.exists(spec_path):
        return (
            f"ERROR: neither content_json nor existing {spec_path} provided. "
            "Pass content_json with titles/date/blocks or write the JSON file to /reports first."
        )

    assemble_py = os.path.join(REPORTING_DIR, "assemble.py")
    if not os.path.exists(assemble_py):
        return f"ERROR: assemble.py not found at {assemble_py} (mount ./reporting:/reporting:ro)"

    try:
        sys.path.insert(0, REPORTING_DIR)
        import assemble as _asm  # type: ignore

        saved_path, warnings = _asm.build(
            spec_path,
            out_docx,
            template=os.path.join(REPORTING_DIR, "template.docx"),
            evidence_dir=EVIDENCE_DIR,
        )
        warn_str = ("\nWarnings:\n- " + "\n- ".join(warnings)) if warnings else ""
        return f"OK: assembled TLP report -> {saved_path} (spec: {spec_path}){warn_str}"
    except Exception:
        # Fallback to subprocess if python-docx/pillow lives in system python3
        cmd = [
            sys.executable or "python3",
            assemble_py,
            spec_path,
            "-o",
            out_docx,
            "--evidence",
            EVIDENCE_DIR,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        if r.returncode != 0:
            return f"ERROR assembling report (exit {r.returncode}): {out.strip()}"
        return f"OK: assembled TLP report -> {out_docx}\n{out.strip()}"


TOOLS = [assemble_tlp_report]
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
