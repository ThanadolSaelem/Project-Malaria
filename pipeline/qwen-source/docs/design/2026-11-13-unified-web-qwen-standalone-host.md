# Unified Web Qwen Standalone Host Design

[English](2026-11-13-unified-web-qwen-standalone-host.md) | [简体中文](2026-11-13-unified-web-qwen-standalone-host.zh-CN.md)

## Status

Source implementation completed within the Qwen worker ownership boundary on 2026-11-13. Runtime behavior, dependency resolution, packaging, gateway routing, and feature parity remain unverified because the approved task forbids installs, builds, typechecks, tests, application runs, and real daemon/model calls.

## Problem and current state

The supplied Qwen Web Shell is a full standalone application, not an abbreviated chat widget. `client/main.tsx` supplies the standalone context, browser notifications, daemon/session providers, workspace hosts, full sidebar/footer, native page navigation, pairing/auth, and the complete `App`. `App.tsx` also owns full-page and hidden surfaces such as settings, sessions, workspaces, agents, plugins, Skills/MCP/Extensions, channels/events, Live, workflows, goals, scheduled tasks, PR watches, split view, files, terminal, review, preview, artifacts, media, and capability gates.

The unified application owns browser history and must mount Qwen at `/ai` without allowing Qwen to write the document pathname or compete with ARTEX/Vue routing. Default and same-origin Qwen daemon REST/SSE/WebSocket traffic uses the namespaced gateway base `/qwen-api`. An explicitly selected remote target retains the native target provider's validated-origin and deployment CSP behavior; this design does not claim that every remote request is rewritten through the local gateway. Qwen branding must be host-controlled while legal notices and technical Qwen identifiers remain intact.

## Goals

1. Publish a real public `@qwen-code/web-shell/standalone-host` entry that mounts the full standalone provider/session/App composition.
2. Accept the unified host contract (`active`, `theme`, `path`, and `onNavigate`) through `unified-web/src/modules/qwen/index.tsx`.
3. Keep the complete Qwen tree mounted while inactive using a hidden wrapper; never pass `viewHidden` and never unmount `App` or its providers during module switching.
4. Route local Qwen navigation through the host callback without writing `window.history`, `window.location.pathname`, or a shared global pathname.
5. Resolve default/same-origin Qwen daemon HTTP/SSE/WS URLs below `/qwen-api`; preserve explicitly selected native multi-host targets and keep each Qwen credential inside the Qwen provider boundary.
6. Use `Project-Malaria` as the default product brand without blanket-renaming Qwen technical IDs, API routes, daemon settings, legal notices, or attribution.

## Scope boundaries

This section describes the Qwen worker contribution only. In scope are `packages/web-shell` public entry/build configuration, the narrow host navigation adapter, same-origin pairing exchange support, the unified Qwen module adapter, bilingual design documentation, and an unrun E2E test plan. Native `main.tsx` behavior is not rewritten. Core/auth-provider/model/tool/runtime policy is not refactored. No Qwen worker gateway/server, runtime Docker file, lockfile, or unrelated worker file is edited by this Qwen-specific contribution; this boundary is not a statement that the separate unified integration has no gateway or Docker changes.

The host does not invent managed-agent behavior, permission policy, model/tool policy, or a second session implementation. Native capability checks and the native `WorkspaceSessionProvider` remain authoritative.

## Proposed and implemented solution

### Public full-shell entry

`client/standalone-host.tsx` is a library entry exported as `@qwen-code/web-shell/standalone-host`. It imports the scoped Web Shell/global/standalone styles, mounts `StandaloneContext`, `WorkspaceHostsEnabled`, `DaemonTargetProvider`, `DaemonWorkspaceProvider`, `WorkspaceSessionProvider`, `BrowserTurnNotifications`, and the complete `App` composition selected by `WorkspaceSessionProvider`. It uses the native default primary and footer navigation instead of `sidebar={false}` or a reduced navigation list. Header, right-panel, environment-panel, composer, media, artifacts, file, terminal, review, preview, notification, session, settings, and capability-gated pages remain delegated to native props/components.

A `brand` prop defaults to `{ name: 'Project-Malaria' }`, which removes the Qwen logo node and changes product chrome without changing technical data. A caller may provide a host-owned brand. The resolved unified theme is passed to the shell and chrome. The inactive host wrapper uses `hidden` and `aria-hidden` but remains mounted, so React state, drafts, active streams, and provider lifecycle are not reset by module switching.

### Host-owned navigation

`WebShellHostNavigationBoundary` parses the module-local `path` with the existing navigation URL parser and maintains the native route/session target in React state. Native `openPage`, session creation/switching, `returnToChat`, and page reconciliation are translated into local paths and sent to `onNavigate(path, replace)`. External path changes update the boundary state. The adapter never calls `pushState`, `replaceState`, `assign`, or a global pathname setter. The existing native `WebShellNavigationBoundary` and normal standalone `main.tsx` behavior are unchanged.

### Same-origin transport and auth

For the default daemon and explicitly selected same-origin targets, the client base is `${window.location.origin}/qwen-api`. The existing SDK concatenates `/capabilities`, `/session/...`, SSE `/events`, and ACP `/acp` below this base, so gateway routing must preserve HTTP, long-lived SSE, and WebSocket upgrade semantics. The native `DaemonTargetProvider` and focused `DaemonWorkspaceProvider` remain mounted; saved/fan-out workspace hosts, focus changes, session handoff, and per-target Qwen tokens continue through the host-owned route callback. An explicitly selected remote daemon origin retains the native validated-origin/CSP behavior and is not incorrectly described as a local `/qwen-api` request. An optional trusted host token or the Qwen-specific stored token is used only by the Qwen provider boundary; no ARTEX JWT, ScopeSentry key, or unrelated module token is read or sent. The host performs a narrow `/capabilities` probe, supports same-origin pairing exchange, and provides a fixed-Qwen token recovery form without exposing a remote-origin input.

`config/pairing.ts` now accepts a same-origin base URL with a path while retaining its existing origin-only behavior for normal standalone boot. This allows pairing requests to remain under `/qwen-api` without widening the target origin.

## Design decisions and rationale

- **Separate public entry:** importing `client/main.tsx` would execute native bootstrap side effects and would not be a safe library component. A dedicated entry reuses the native target/workspace/session providers and App without executing the document bootstrap; its target navigation delegates URL ownership to the host.
- **Host callback instead of browser history:** the unified router is the only owner of the document URL. Qwen-local route state still supports native page/session deep links.
- **Namespaced same-origin base plus native targets:** a path-qualified default base gives the gateway an explicit Qwen namespace; explicitly selected native Qwen targets retain their target behavior and never receive credentials from other modules.
- **Hidden, not unmounted:** inactive module switching must preserve drafts, streams, session state, and provider lifecycle.
- **No technical-ID rename:** visible product branding is host-owned, while API subjects, daemon setting keys, MCP rows, session metadata, and license/notice text stay native.

## Constraints and risks

The browser cannot attach an Authorization header to a native WebSocket, and the current SDK ACP browser transport constructs its socket without the daemon's bearer subprotocol. A UI-only change cannot safely invent tokenless, cookie, query-token, or cross-module authentication; ACP-over-WebSocket remains a compatibility blocker until an SDK-supported transport or explicitly approved authenticated proxy contract exists. Same-origin gateway routing and the CSP/remote-origin behavior of selected external daemons also require runtime verification; no CORS or credential policy is silently widened here. Desktop-only local file, terminal, updater, media, and screen-capture behavior still depends on browser capability, daemon capability, CSP, and deployment topology.

The native `App` initializes non-`WebShellPage` `mainView` surfaces (workflows, scheduled tasks, goals, PR watches, and split/cockpit state) through internal actions and some global URL conventions. The host preserves access through native sidebar and slash-command actions, but does not claim every `mainView` variant has a module-local deep-link adapter; that would require an approved narrow App route-input patch.

The package entry is source-declared but its generated `dist` artifacts and declarations are not produced in this task. The unified host package must declare the file dependency and route the dynamic module to the built entry later. The supplied ZIP/package version distinction remains unresolved until an approved exact-version verification.

## Validation plan

The accompanying `.qwen/e2e-tests/qwen-standalone-host.md` lists the required checks. They were not run. Later authorized validation must build the public entry, inspect generated CSS/declarations, mount the module with a controlled route host, verify inactive persistence, exercise `/qwen-api` HTTP/SSE/WS requests, verify pairing/token isolation, and exercise every capability-gated native page against an approved daemon fixture. It must separately test route ownership with ARTEX and Vue modules.

## Acceptance criteria

- The package exposes `@qwen-code/web-shell/standalone-host` and the compatible Vite entry emits its JS/CSS/declaration surfaces.
- `unified-web/src/modules/qwen/index.tsx` is a default `UnifiedModuleProps` adapter.
- Qwen App/providers remain mounted when `active` is false; no `viewHidden` or abbreviated sidebar is used.
- Native Qwen navigation calls the host callback and does not mutate shared browser history.
- Default and same-origin Qwen REST/SSE/WS requests resolve under `/qwen-api`; explicitly selected native targets retain validated target behavior; unrelated module credentials are not attached.
- Pairing, session, settings, workspace, sidebar/footer, composer, media, artifact, and capability-gated native pages remain delegated to source-native composition.
- Branding defaults to Project-Malaria while legal notices, licenses, and technical identifiers remain present.
- Native multi-host/workspace target providers remain mounted and host-routed; ACP browser authentication, gateway/CSP behavior, and runtime parity remain open blockers rather than presented as verified.

## Open questions

1. What exact gateway authentication mechanism will authorize browser WebSocket upgrades when the browser cannot set `Authorization` headers?
2. What approved gateway/CSP deployment contract should verify same-origin routing alongside the preserved native remote-daemon target behavior?
3. Which unified-web dependency declaration and dynamic import configuration will the integrator use for the built Qwen library entry?
4. Which exact supplied Qwen version is the runtime baseline: the ZIP inventory version `0.27.1` or the package metadata version `0.27.2`?
5. Which browser/runtime capabilities are approved for local file, terminal, media, screen sharing, mobile access, and updater surfaces in the deployed web topology?
