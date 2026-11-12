#!/bin/sh
# =============================================================================
# entrypoint — Run Qwen Code Studio daemon inside container
# =============================================================================
set -eu

mkdir -p /root/.qwen /workspace
cd /workspace

# ── Load persistent Qwen Code settings ───────────────────────────────────────
# Keep mcpServers only in user-scope (/root/.qwen/settings.json). Putting mcpServers
# in workspace-scope (/workspace/.qwen/settings.json) triggers Qwen Code's
# isGatedMcpScope() check and forces manual approval after every recreate.
if [ -f /config/settings.json ]; then
  cp /config/settings.json /root/.qwen/settings.json
  mkdir -p /workspace/.qwen
  node -e '
    const fs = require("node:fs");
    const cfg = JSON.parse(fs.readFileSync("/config/settings.json", "utf8"));
    delete cfg.mcpServers;
    fs.writeFileSync("/workspace/.qwen/settings.json", JSON.stringify(cfg, null, 2));
  '
  echo "entrypoint: synced settings.json -> /root/.qwen/settings.json (full) and /workspace/.qwen/settings.json (no gated mcpServers)"
fi

# ── Install project-scoped named subagents for the native agent tool ──────────
if [ -d /config/agents ]; then
  mkdir -p /workspace/.qwen/agents
  cp -f /config/agents/*.md /workspace/.qwen/agents/ 2>/dev/null || true
  echo "entrypoint: installed project subagents -> /workspace/.qwen/agents"
fi

# ── Extract and inject baseline cyber-operator system prompt ─────────────────
if [ -f /config/cyber-operator.system.md ]; then
  awk 'BEGIN { f=0 } /^## SYSTEM PROMPT$/ { f=1; next } f { print }' \
    /config/cyber-operator.system.md > /workspace/AGENTS.md
  echo "entrypoint: extracted project instructions -> /workspace/AGENTS.md ($(wc -c < /workspace/AGENTS.md) bytes)"
fi

# ── Patch Qwen Code listLanCandidates() to use mounted Mac host IP live ──────
patch_qwen_lan_candidates() {
  node - <<'EOF'
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const chunksDir = "/usr/local/lib/node_modules/@qwen-code/qwen-code/chunks";
if (!fs.existsSync(chunksDir)) process.exit(0);

const files = fs.readdirSync(chunksDir).filter((f) => f.endsWith(".js") && !f.endsWith(".orig"));
let patchedAny = false;

for (const file of files) {
  const fullPath = path.join(chunksDir, file);
  const origPath = fullPath + ".orig";
  const src = fs.existsSync(origPath)
    ? fs.readFileSync(origPath, "utf8")
    : fs.readFileSync(fullPath, "utf8");

  if (!src.includes("function listLanCandidates(")) continue;
  if (!fs.existsSync(origPath)) fs.writeFileSync(origPath, src, "utf8");

  const importStmt = 'import{readFileSync as __qwenReadHostFile}from"node:fs";';
  const helperFn =
    'function __qwenReadHostLanIp(){' +
    'const sources=[];' +
    'try{sources.push(__qwenReadHostFile("/host-net/host-lan-ip.txt","utf8"));}catch{}' +
    'if(process.env.HOST_LAN_IP)sources.push(process.env.HOST_LAN_IP);' +
    'for(const raw of sources){' +
    'const ip=String(raw||"").trim();' +
    'const parts=ip.split(".");' +
    'if(parts.length===4&&parts.every(p=>/^\\d+$/.test(p)&&Number(p)>=0&&Number(p)<=255)&&Number(parts[0])!==127&&Number(parts[0])!==0){' +
    'return ip;' +
    '}}return "";}';

  let out = src;
  if (out.includes('"use strict";')) {
    out = out.replace('"use strict";', '"use strict";' + importStmt);
  } else {
    out = importStmt + "\n" + out;
  }

  const sig = "function listLanCandidates(";
  const sigIdx = out.indexOf(sig);
  if (sigIdx === -1) continue;
  let depth = 1;
  let pos = sigIdx + sig.length;
  while (pos < out.length && depth > 0) {
    if (out[pos] === "(") depth++;
    else if (out[pos] === ")") depth--;
    pos++;
  }
  const openBrace = out.indexOf("{", pos);
  if (depth !== 0 || openBrace === -1) continue;

  const inject = 'const __hostIp=__qwenReadHostLanIp();if(__hostIp)return[{interfaceName:"mac-lan",address:__hostIp}];';
  out =
    out.slice(0, sigIdx) +
    helperFn +
    out.slice(sigIdx, openBrace + 1) +
    inject +
    out.slice(openBrace + 1);

  fs.writeFileSync(fullPath, out, "utf8");
  try {
    execFileSync(process.execPath, ["--check", fullPath], { stdio: "pipe" });
    patchedAny = true;
    console.log("entrypoint: patched listLanCandidates in " + file + " -> live /host-net/host-lan-ip.txt");
  } catch (err) {
    fs.writeFileSync(fullPath, src, "utf8");
    console.error("entrypoint: patch rollback on " + file + ": " + err.message);
  }
}

if (!patchedAny) {
  console.log("entrypoint: listLanCandidates chunk not found; using default network behavior");
}
EOF
}

patch_qwen_lan_candidates || true

# ── Configure LLM endpoints for LiteLLM ─────────────────────────────────────
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://litellm:4000/v1}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${LITELLM_KEY:-sk-local}}"
export OPENAI_MODEL="${OPENAI_MODEL:-flint}"
export QWEN_SERVER_TOKEN="${QWEN_SERVER_TOKEN:-malaria-qwen-token}"
export QWEN_CODE_ENABLE_AGENT_TEAM="${QWEN_CODE_ENABLE_AGENT_TEAM:-0}"

LIVE_HOST_IP="${HOST_LAN_IP:-}"
if [ -f /host-net/host-lan-ip.txt ]; then
  FILE_IP="$(tr -d '[:space:]' < /host-net/host-lan-ip.txt 2>/dev/null || true)"
  [ -n "$FILE_IP" ] && LIVE_HOST_IP="$FILE_IP"
fi

echo "============================================================================="
echo "Qwen Code Studio starting on port 3080"
echo "Open on Mac browser: http://localhost:3080/?token=${QWEN_SERVER_TOKEN}"
if [ -n "${LIVE_HOST_IP:-}" ]; then
  echo "Open from phone (Mac LAN): http://${LIVE_HOST_IP}:3080/?token=${QWEN_SERVER_TOKEN}"
fi
echo "Model: ${OPENAI_MODEL} via ${OPENAI_BASE_URL}"
echo "============================================================================="

exec qwen serve --hostname 0.0.0.0 --port 3080 --token "${QWEN_SERVER_TOKEN}"
