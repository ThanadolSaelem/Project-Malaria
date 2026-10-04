#!/usr/bin/env python3
"""
Knowledge-graph memory — MCP over HTTP (streamable-http)  [non-vector]
=============================================================================
Gives the model memory that persists across turns/sessions as a knowledge
graph: entities (nodes) + observations (facts about a node) + relations
(directed edges). Stored in a single JSON file on a volume -> persistent, with
no embeddings/vectors, so there is **no dimension problem when the chat model
changes** and nothing extra to run.

Well suited to pentest work where data is structured (host/port/service/vuln):
  memory_add("scanme.nmap.org", "host", ["80/tcp open http", "22/tcp open ssh"])
  memory_relate("scanme.nmap.org", "CVE-XXXX", "affected_by")
  memory_search("scanme")   -> matching nodes + observations + relations (keyword)

env:
  MEMORY_FILE   path to the JSON file (default /data/memory.json — mount a volume)
  MCP_HOST / MCP_PORT   host:port to bind (default 0.0.0.0:8002)
endpoint: http://<host>:<MCP_PORT>/mcp
"""
import json
import os
import re
import sys
import tempfile
import threading

from mcp.server.fastmcp import FastMCP

MEMORY_FILE = os.environ.get("MEMORY_FILE", "/data/memory.json")
_LOCK = threading.Lock()


def _empty() -> dict:
    return {"entities": {}, "relations": []}


def _load() -> dict:
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("entities", {})
        data.setdefault("relations", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _save(data: dict) -> None:
    """Write atomically (temp + replace) so the file is never left corrupt."""
    os.makedirs(os.path.dirname(MEMORY_FILE) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(MEMORY_FILE) or ".",
                               prefix=".memory.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MEMORY_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _score(query: str, name: str, etype: str, obs: list) -> int:
    q = query.lower().strip()
    if not q:
        return 0
    terms = [w for w in re.split(r"\s+", q) if w]
    name_l, type_l = name.lower(), (etype or "").lower()
    hay = (name_l + " " + type_l + " " + " ".join(obs)).lower()
    s = 0
    for t in terms:
        if t in name_l:
            s += 5
        if t in type_l:
            s += 2
        if t in hay:
            s += 1
    if q in hay:
        s += 2
    return s


def _relations_of(data: dict, name: str) -> list:
    return [r for r in data["relations"]
            if r.get("from") == name or r.get("to") == name]


def main() -> None:
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8002"))

    mcp = FastMCP("memory")

    @mcp.tool()
    def memory_add(name: str, entity_type: str = "",
                   observations: list[str] | None = None) -> dict:
        """Create or update one entity (memory node) with observations (facts).
        If the entity already exists, new observations are appended (deduped) and
        the type is updated when provided. Use it to record findings, e.g.
        memory_add("scanme.nmap.org", "host", ["80/tcp open http", "title: Go ..."])."""
        observations = observations or []
        with _LOCK:
            data = _load()
            ent = data["entities"].get(name, {"type": "", "observations": []})
            if entity_type:
                ent["type"] = entity_type
            seen = set(ent["observations"])
            for o in observations:
                if o not in seen:
                    ent["observations"].append(o)
                    seen.add(o)
            data["entities"][name] = ent
            _save(data)
            return {"saved": name, "type": ent["type"],
                    "observation_count": len(ent["observations"])}

    @mcp.tool()
    def memory_relate(source: str, target: str, relation: str) -> dict:
        """Link two entities with a directed relation (source -> target).
        e.g. memory_relate("scanme.nmap.org", "CVE-2023-XXXX", "affected_by").
        The target entity is created automatically if it does not exist yet
        (with an empty type)."""
        with _LOCK:
            data = _load()
            for n in (source, target):
                data["entities"].setdefault(n, {"type": "", "observations": []})
            rel = {"from": source, "to": target, "type": relation}
            if rel not in data["relations"]:
                data["relations"].append(rel)
            _save(data)
            return {"related": f"{source} -[{relation}]-> {target}"}

    @mcp.tool()
    def memory_search(query: str, limit: int = 10) -> dict:
        """Search memory by keyword (name/type/observations) and return the
        matching entities with their observations and relations. Call this at the
        start of a task to recall what is already known about a target/topic."""
        data = _load()
        scored = []
        for name, ent in data["entities"].items():
            sc = _score(query, name, ent.get("type", ""), ent.get("observations", []))
            if sc > 0:
                scored.append((sc, name, ent))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for _, name, ent in scored[:limit]:
            hits.append({
                "name": name,
                "type": ent.get("type", ""),
                "observations": ent.get("observations", []),
                "relations": _relations_of(data, name),
            })
        return {"query": query, "count": len(hits), "results": hits}

    @mcp.tool()
    def memory_read(limit: int = 50) -> dict:
        """Return an overview of the whole memory graph (entities + relations),
        capping the number of entities with `limit`. Use it to see everything
        that is stored."""
        data = _load()
        names = list(data["entities"].keys())[:limit]
        return {
            "entity_count": len(data["entities"]),
            "relation_count": len(data["relations"]),
            "entities": [{"name": n, **data["entities"][n]} for n in names],
            "relations": data["relations"][: limit * 4],
        }

    @mcp.tool()
    def memory_delete(name: str) -> dict:
        """Delete the entity named `name` and every relation that touches it."""
        with _LOCK:
            data = _load()
            existed = data["entities"].pop(name, None) is not None
            before = len(data["relations"])
            data["relations"] = [r for r in data["relations"]
                                 if r.get("from") != name and r.get("to") != name]
            _save(data)
            return {"deleted": name, "existed": existed,
                    "relations_removed": before - len(data["relations"])}

    # host/port + disable DNS-rebinding protection (same as hexstrike_mcp_router.py
    # — see the reasoning there: this is an internal loopback/compose service)
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    except Exception as e:
        print(f"[memory-mcp] WARN: could not set transport_security ({e})",
              file=sys.stderr)

    n = len(_load()["entities"])
    print(f"[memory-mcp] serving at http://{host}:{port}/mcp "
          f"— file={MEMORY_FILE} ({n} entities loaded)", file=sys.stderr)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
