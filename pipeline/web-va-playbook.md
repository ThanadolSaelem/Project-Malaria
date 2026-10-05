# Web Application VA Playbook

> Attach this file in the HarnessRouter "add file" field (or append it to the
> cyber-operator system prompt). It tells the model *how to think* when assessing
> a web target — the way an analyst reads browser DevTools, but driven through
> HexStrike tools. Only act on targets inside the authorized scope.

Work a web target like a methodical analyst reading DevTools, but through tools,
and keep your own context lean — not because it won't fit (the window is large)
but because a fuller context makes each turn slower. Summarize as you go.

## 1. Snapshot the app first — one browser-agent pass
Find the browser tool via the router (`hexstrike_search_tools("browser inspect")`)
and run it on the in-scope URL. From that single response, read these signals
**together** (this is your DevTools in one call):
- **scripts / inline JS** → endpoints, API paths, hidden params, client-side
  logic, leaked secrets or keys
- **network_requests** → XHR/fetch URLs, methods, parameters, content types
- **cookies / local_storage / session_storage** → tokens, feature flags, session
  design; note cookie flags (HttpOnly, Secure, SameSite)
- **forms / inputs** → parameters and sinks worth testing
- **console_errors** → stack traces, framework/version hints
- **security_analysis** → the agent's passive findings (verify, don't trust)

Then run httpx (`hexstrike_search_tools("http probe tech detect")`) for status,
response headers (CSP, HSTS, CORS, Cache-Control/ETag), and tech + versions.

Distill each run to a few facts in your findings ledger (host / path / param /
service / observation). Do **not** paste raw page source or full logs into your
reasoning — summarize, then discard; re-fetch a detail if you need it later.

## 2. Reason across the signals — don't test blindly
Correlate before you touch anything. A parameter seen in JS + its XHR in the
network list + how its value is stored (cookie vs localStorage) is one
hypothesis. Map each to a likely class: IDOR / broken authz, injection
(SQLi/XSS/SSTI/command), SSRF, secret exposure, insecure session/CORS/CSP,
sensitive data in storage. Write the hypothesis and the evidence for it.

## 3. Mock / replay to confirm — least-invasive proof first
Reconstruct the exact request (method, path, headers, cookies, body) from what
you observed and replay it:
- general replay: curl / httpx
- class-specific: ffuf (params/paths), sqlmap (detection mode first), nuclei
  (a targeted template), dalfox (XSS)
Confirm with the smallest possible proof. Capture the request/response that
proves it as evidence. Never run anything destructive without a separate go-ahead.

## 4. Build an exploit only when needed
When a finding needs a working PoC / payload, delegate the code-writing to
`ask_exploit_specialist(task, context)` with the confirmed facts in `context`.
Review the returned code before running it (never run code you have not read),
then run it via the HexStrike tools.

## 5. Record and carry over
Store confirmed, in-scope facts in memory (`memory_add` / `memory_relate`): host,
endpoints, params, session design, findings. Keep observations concise; never
store secrets — reference where they live. Start later tasks with
`memory_search(<target>)` so you build on prior work instead of re-scanning.

## Order of operations (quick reference)
browser-agent snapshot + httpx  →  correlate signals  →  hypothesis per class
→  mock/replay to confirm  →  (if needed) specialist writes PoC → you review+run
→  record facts in memory  →  report with evidence, impact, repro, fix.
