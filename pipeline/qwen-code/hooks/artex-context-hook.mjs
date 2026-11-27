#!/usr/bin/env node
/**
 * Project-Malaria — Zero-Touch Auto-Pipeline & Lean Continuity Hook
 * =================================================================
 * Subcommands:
 *   prompt  (UserPromptSubmit) —
 *     1) Automatically calls ensure_auto_pipeline when no active ARTEX task exists
 *        and the operator submits a security/audit/code/report request (with URL/IP,
 *        /workspace folder, or assessment intent) so the user NEVER needs to manually
 *        say "create task".
 *     2) Fetches compact shared briefing and uses SHA-256 delta deduplication per
 *        session so unchanged briefings cost ~0 extra prefill tokens (cooler Mac,
 *        higher KV-cache hit rate, faster tok/s).
 *   stop    (Stop) — posts concise Q&A / execution summary back to linked /chat.
 *
 * Strictly fail-open: any network/parse error exits 0 with {}.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";

const mode = (process.argv[2] || "prompt").trim().toLowerCase();
const ARTEX_HOST = process.env.ARTEX_MCP_HOST || "artex";
const ARTEX_PORT = Number(process.env.ARTEX_MCP_PORT || 8787);
const ARTEX_KEY = (process.env.ARTEX_MCP_KEY || "ak_project_malaria_artex_mcp_key_2026").trim();

function safeOut(obj = {}) {
  process.stdout.write(JSON.stringify(obj) + "\n");
  process.exit(0);
}

function readStdin() {
  return new Promise((resolve) => {
    let buf = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      buf += chunk;
    });
    process.stdin.on("end", () => resolve(buf));
    process.stdin.on("error", () => resolve(buf));
    setTimeout(() => resolve(buf), 1500);
  });
}

function callArtexMcp(toolName, args, timeoutMs = 4500) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: toolName, arguments: args || {} },
    });
    const req = http.request(
      {
        hostname: ARTEX_HOST,
        port: ARTEX_PORT,
        path: "/mcp",
        method: "POST",
        timeout: timeoutMs,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
          "X-API-Key": ARTEX_KEY,
        },
      },
      (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (c) => {
          data += c;
        });
        res.on("end", () => {
          if (res.statusCode !== 200) {
            return reject(new Error(`HTTP ${res.statusCode}`));
          }
          try {
            const rpc = JSON.parse(data);
            const text = rpc?.result?.content?.[0]?.text || "";
            if (!text) return resolve(null);
            resolve(JSON.parse(text));
          } catch (err) {
            reject(err);
          }
        });
      },
    );
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

function safeSessionKey(raw) {
  const cleaned = String(raw || "default").replace(/[^a-zA-Z0-9_-]/g, "_");
  return cleaned.slice(0, 80) || "default";
}

function firstLine(str, maxLen = 120) {
  const line = String(str || "")
    .trim()
    .split(/\r?\n/)[0]
    .trim();
  return line.length > maxLen ? line.slice(0, maxLen) + "..." : line;
}

function truncate(str, maxLen) {
  const s = String(str || "").trim();
  return s.length > maxLen ? s.slice(0, maxLen) + "..." : s;
}

function looksLikeActionablePipelinePrompt(prompt) {
  const p = String(prompt || "").trim();
  if (p.length < 10) return false;
  // Ignore pure short greetings
  if (/^(hi|hello|hey|สวัสดี|หวัดดี|ขอบคุณ|thanks|ok|โอเค)[!.\s]*$/i.test(p)) {
    return false;
  }
  const hasUrlOrIp = /(?:https?:\/\/\S+|\b(?:\d{1,3}\.){3}\d{1,3}\b|\/workspace\S*)/i.test(p);
  const hasAuditIntent = /(?:ตรวจ|สแกน|วิเคราะห์|เจาะ|หาช่องโหว่|รายงาน|โฟลเดอร์|ไฟล์|สคริปต์|scan|audit|pentest|assess|analy[sz]e|inspect|vuln|exploit|report|script|folder)/i.test(p);
  return hasUrlOrIp || (hasAuditIntent && p.length >= 18);
}

const IGNORED_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "host.docker.internal",
  "artex",
  "litellm",
  "scope-sentry",
  "github.com",
  "raw.githubusercontent.com",
  "nvd.nist.gov",
  "cisa.gov",
  "www.cisa.gov",
  "cve.org",
  "www.cve.org",
  "owasp.org",
  "www.owasp.org",
  "exploit-db.com",
  "www.exploit-db.com",
  "google.com",
  "www.google.com",
  "stackoverflow.com",
  "en.wikipedia.org",
]);

function extractExplicitTargetHosts(prompt) {
  const hosts = new Set();
  const text = String(prompt || "");
  for (const m of text.matchAll(/https?:\/\/([^\s/"'<>:?#]+)/gi)) {
    const h = String(m[1] || "").toLowerCase().trim();
    if (h && !IGNORED_HOSTS.has(h)) hosts.add(h);
  }
  for (const m of text.matchAll(/\b((?:\d{1,3}\.){3}\d{1,3})\b/g)) {
    const ip = String(m[1] || "").trim();
    if (ip && !IGNORED_HOSTS.has(ip)) hosts.add(ip);
  }
  return [...hosts];
}

function sameTargetHost(a, b) {
  const ha = String(a || "").toLowerCase().trim();
  const hb = String(b || "").toLowerCase().trim();
  if (!ha || !hb) return false;
  if (ha === hb || hb.includes(ha) || ha.includes(hb)) return true;
  const pa = ha.split(".");
  const pb = hb.split(".");
  if (pa.length >= 2 && pb.length >= 2 && !/^\d+$/.test(pa[pa.length - 1])) {
    const ra = pa.slice(-2).join(".");
    const rb = pb.slice(-2).join(".");
    if (ra === rb) return true;
  }
  return false;
}

function hasUnboundNewTarget(prompt, briefing) {
  const promptHosts = extractExplicitTargetHosts(prompt);
  if (promptHosts.length === 0) return false;
  const activeHaystack = `${briefing?.target || ""} ${briefing?.task_description || ""} ${(briefing?.assets || []).map((a) => a?.label || "").join(" ")}`.toLowerCase();
  for (const h of promptHosts) {
    if (!sameTargetHost(h, activeHaystack)) {
      return true;
    }
  }
  return false;
}

async function handlePrompt(input) {
  const sessionKey = safeSessionKey(input?.session_id);
  const userPrompt = String(input?.submitted_prompt || input?.prompt || "").trim();

  let briefing = await callArtexMcp("get_shared_briefing", { max_turns: 6 }, 4000);
  let taskId = Number(briefing?.task_id || 0);
  let convId = Number(briefing?.conversation_id || 0);
  const wsPath = String(briefing?.workspace_path || "").trim();

  // Zero-Touch Auto-Pipeline:
  //   1) If no active task exists yet and user submits an actionable prompt -> auto-create Task.
  //   2) If an older task is active, BUT user pasted a NEW explicit URL/IP for a different target -> auto-create/attach dedicated Task!
  const isNewTarget = taskId > 0 && hasUnboundNewTarget(userPrompt, briefing);
  if ((taskId <= 0 && looksLikeActionablePipelinePrompt(userPrompt)) || isNewTarget) {
    try {
      const autoRes = await callArtexMcp(
        "ensure_auto_pipeline",
        {
          prompt: userPrompt,
          workspace_path: isNewTarget ? "" : wsPath,
          conversation_id: !isNewTarget && convId > 0 ? convId : undefined,
        },
        7000,
      );
      if (autoRes?.task_id > 0) {
        briefing = await callArtexMcp("get_shared_briefing", { task_id: autoRes.task_id, max_turns: 6 }, 4000);
        taskId = Number(briefing?.task_id || autoRes.task_id || 0);
        convId = Number(briefing?.conversation_id || autoRes.conversation_id || convId || 0);
      }
    } catch {
      /* fail-open if auto-pipeline skipped */
    }
  }

  const md = String(briefing?.briefing_markdown || "").trim();

  if (userPrompt) {
    try {
      fs.writeFileSync(
        `/tmp/artex-last-prompt-${sessionKey}.json`,
        JSON.stringify({
          prompt: userPrompt,
          task_id: taskId,
          conversation_id: convId,
          ts: Date.now(),
        }),
        "utf8",
      );
    } catch {
      /* ignore tmp write errors */
    }
  }

  if (!md || (taskId <= 0 && convId <= 0 && !wsPath)) {
    return safeOut({});
  }

  // Delta-deduplicate unchanged briefing within the same Qwen session to save prefill tokens & heat
  const briefSig = crypto.createHash("sha256").update(`${taskId}:${convId}:${md}`).digest("hex");
  const briefSigPath = `/tmp/artex-brief-sig-${sessionKey}.sha`;
  let prevSig = "";
  try {
    if (fs.existsSync(briefSigPath)) {
      prevSig = fs.readFileSync(briefSigPath, "utf8").trim();
    }
  } catch {
    prevSig = "";
  }

  if (prevSig === briefSig && taskId > 0) {
    return safeOut({
      hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext: `[ACTIVE SHARED ARTEX TASK #${taskId} (${briefing?.target || briefing?.workspace_path || "active"}) — context unchanged from prior turn; continue recording intents/facts/findings on Task #${taskId} and call generate_task_report when producing a formal report.]`,
      },
    });
  }

  try {
    fs.writeFileSync(briefSigPath, briefSig, "utf8");
  } catch {
    /* ignore */
  }

  return safeOut({
    hookSpecificOutput: {
      hookEventName: "UserPromptSubmit",
      additionalContext: md,
    },
  });
}

async function handleStop(input) {
  if (input?.stop_hook_active) {
    return safeOut({});
  }
  const reply = String(input?.last_assistant_message || "").trim();
  if (reply.length < 15) {
    return safeOut({});
  }

  const sessionKey = safeSessionKey(input?.session_id);
  const promptCachePath = `/tmp/artex-last-prompt-${sessionKey}.json`;
  let cached = null;
  try {
    if (fs.existsSync(promptCachePath)) {
      cached = JSON.parse(fs.readFileSync(promptCachePath, "utf8"));
    }
  } catch {
    cached = null;
  }

  let taskId = Number(cached?.task_id || 0);
  let convId = Number(cached?.conversation_id || 0);
  const userPrompt = String(cached?.prompt || "").trim();

  if (taskId <= 0 && convId <= 0) {
    const active = await callArtexMcp("get_active_context", {}, 3000);
    taskId = Number(active?.task_id || 0);
    convId = Number(active?.conversation_id || 0);
  }
  if (taskId <= 0 && convId <= 0) {
    return safeOut({});
  }

  const sig = crypto
    .createHash("sha256")
    .update(`${taskId}:${convId}:${userPrompt}:${reply}`)
    .digest("hex");
  const sigPath = `/tmp/artex-last-stop-${sessionKey}.sha`;
  try {
    if (fs.existsSync(sigPath) && fs.readFileSync(sigPath, "utf8").trim() === sig) {
      return safeOut({});
    }
  } catch {
    /* ignore */
  }

  const summary = userPrompt
    ? `[Deep Agent IDE] Q: ${firstLine(userPrompt, 110)}`
    : `[Deep Agent IDE] ${firstLine(reply, 120)}`;
  const message = userPrompt
    ? `**Operator (in Deep Agent IDE):** ${truncate(userPrompt, 500)}\n\n**Deep Agent IDE:**\n${truncate(reply, 1800)}`
    : `**Deep Agent IDE:**\n${truncate(reply, 2200)}`;

  const payload = { summary, message };
  if (taskId > 0) payload.task_id = String(taskId);
  if (convId > 0) payload.conversation_id = convId;

  await callArtexMcp("post_chat_note", payload, 4000);
  try {
    fs.writeFileSync(sigPath, sig, "utf8");
  } catch {
    /* ignore */
  }
  return safeOut({});
}

(async () => {
  try {
    const raw = await readStdin();
    const input = raw.trim() ? JSON.parse(raw) : {};
    if (mode === "stop") {
      await handleStop(input);
    } else {
      await handlePrompt(input);
    }
  } catch {
    safeOut({});
  }
})();
