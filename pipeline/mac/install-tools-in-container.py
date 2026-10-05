#!/usr/bin/env python3
"""
Install missing security tools into the hexstrike-server container (arm64) by
downloading prebuilt release binaries from GitHub — no Go toolchain needed.

The arm64 image's Go/clone layers can silently skip tools when the build host's
network to github/go-proxy is flaky (the Dockerfile uses `|| echo skip`). This
re-installs them at runtime, where the container does have network.

Run INSIDE the container:
    docker cp install-tools-in-container.py pipeline-hexstrike-server-1:/tmp/
    docker exec pipeline-hexstrike-server-1 python3 /tmp/install-tools-in-container.py

Picks the right asset by matching linux + arm64/aarch64 in the release asset
names, so it survives naming differences between projects.
"""
import io
import json
import os
import stat
import sys
import tarfile
import urllib.request
import zipfile

DEST = "/usr/local/bin"

# repo on GitHub -> the binary name(s) we want out of its latest release
TOOLS = {
    "projectdiscovery/nuclei":    ["nuclei"],
    "projectdiscovery/httpx":     ["httpx"],
    "projectdiscovery/katana":    ["katana"],
    "projectdiscovery/dnsx":      ["dnsx"],
    "projectdiscovery/subfinder": ["subfinder"],
    "projectdiscovery/naabu":     ["naabu"],
    "hahwul/dalfox":              ["dalfox"],
    "OJ/gobuster":                ["gobuster"],
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "hexstrike-installer"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _pick_asset(assets: list) -> dict | None:
    for a in assets:
        n = a["name"].lower()
        if "linux" not in n:
            continue
        if ("arm64" not in n) and ("aarch64" not in n):
            continue
        if n.endswith(".zip") or n.endswith(".tar.gz") or n.endswith(".tgz"):
            return a
    return None


def _extract_and_install(blob: bytes, name: str, wanted: list) -> list:
    done = []
    if name.endswith(".zip"):
        zf = zipfile.ZipFile(io.BytesIO(blob))
        members = zf.namelist()
        for w in wanted:
            hit = next((m for m in members if os.path.basename(m) == w), None)
            if hit:
                data = zf.read(hit)
                _write_bin(w, data)
                done.append(w)
    else:  # tar.gz / tgz
        tf = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
        members = tf.getmembers()
        for w in wanted:
            hit = next((m for m in members if os.path.basename(m.name) == w), None)
            if hit:
                data = tf.extractfile(hit).read()
                _write_bin(w, data)
                done.append(w)
    return done


def _write_bin(name: str, data: bytes) -> None:
    path = os.path.join(DEST, name)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    ok, fail = [], []
    for repo, wanted in TOOLS.items():
        try:
            rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
            asset = _pick_asset(rel.get("assets", []))
            if not asset:
                print(f"[-] {repo}: no linux/arm64 asset in latest release")
                fail.append(repo)
                continue
            blob = _get(asset["browser_download_url"])
            got = _extract_and_install(blob, asset["name"].lower(), wanted)
            if got:
                print(f"[+] {repo}: installed {', '.join(got)} ({rel.get('tag_name','?')})")
                ok.extend(got)
            else:
                print(f"[-] {repo}: binary {wanted} not found inside {asset['name']}")
                fail.append(repo)
        except Exception as e:
            print(f"[-] {repo}: {type(e).__name__}: {e}")
            fail.append(repo)
    print(f"\nDONE. installed={ok}  failed={fail}")
    print("note: install nikto separately with apt (`apt-get install -y nikto`).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
