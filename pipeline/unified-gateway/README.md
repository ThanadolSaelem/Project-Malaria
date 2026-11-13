# Project-Malaria unified gateway

This service is a dependency-free Node.js 22+ ESM reverse proxy for the unified web origin. It uses native `http`/`https` request streams and native WebSocket upgrade tunnels. Request bodies, SSE frames, multipart data, binary/range responses, status/error envelopes, `Set-Cookie`, and `Content-Disposition` are forwarded without JSON conversion or buffering. There are no retries: a request is sent once, and an upstream failure is returned or the active stream is closed.

## Canonical routes

The gateway selects one of the fixed startup targets below. The browser cannot provide a target URL.

| Gateway path | Upstream path | Service |
| --- | --- | --- |
| `/qwen-api/*` | `/*` | Qwen daemon |
| `/artex-api/*` | `/*` | ARTEX backend |
| `/scopesentry-api/*` | `/*` | ScopeSentry server, including `/api`, `/images`, `/map`, `/mcp`, `/Swagger`, and `/static` |
| `/observer-api/state` | `/state` | Native host Observer, only through a proven loopback-only topology |
| `/_modules/scopesentry/*` | unchanged | Unified frontend static output |
| `/ai`, `/artex`, `/scopesentry`, `/observer`, and host assets | unchanged | Unified frontend |

The namespace is stripped byte-for-byte from the raw path; the raw query string is kept unchanged. For example, `/artex-api/api/report?task=a%2Fb` reaches ARTEX as `/api/report?task=a%2Fb`.

The legacy root `/api` path is intentionally rejected as `400 ambiguous_api_path`; it must not guess whether ARTEX or Qwen credentials should be used. Module-local legacy aliases such as `/artex/api/*` and `/scopesentry/images/*` are accepted only where the owner is unambiguous. Legacy Qwen document/static aliases preserve GET/HEAD refreshes for `/settings`, `/session/*`, `/assets/*`, `/manifest.webmanifest`, `/sw.js`, `/qwen/*`, and token-bearing `/?token=...`; non-namespaced Qwen writes return `400 ambiguous_qwen_path` and must use `/qwen-api/*`.

## Startup environment

All service targets are parsed once at startup and must be absolute `http://` or `https://` URLs without credentials, query strings, or fragments. Defaults match the existing compose service names:

```text
PORT=3000
BIND=0.0.0.0
FRONTEND_TARGET=http://unified-web:3000
QWEN_TARGET=http://qwen-code:3080
ARTEX_TARGET=http://artex:8787
SCOPESENTRY_TARGET=http://scope-sentry:8082
OBSERVER_TARGET=http://127.0.0.1:8005
OBSERVER_ENABLED=0
```

The gateway rewrites `Host` to the fixed upstream authority and discards inbound `Forwarded`, `Via`, `X-Forwarded-*`, and `X-Real-IP` values. It sends a new `X-Forwarded-For` containing only the direct TCP peer and a new `X-Forwarded-Proto` based on the gateway socket. `Host` and forwarded headers are never used as proof of local access. Normal HTTP hop-by-hop headers are removed; WebSocket handshake headers are retained as required for the upgrade.

`GET /healthz` is a gateway-local, unauthenticated readiness response. It does not probe or start any upstream process.

## Observer boundary

The native Observer is unauthenticated and listens on host `127.0.0.1:8005`. A normal Docker bridge cannot prove that a browser client is local to the host, and `host.docker.internal` is not treated as loopback proof. Therefore Observer proxying is disabled by default and returns `503 observer_topology_unverified` with `X-Gateway-Feature: observer-pending`. This keeps the Observer feature present but pending rather than silently widening exposure.

The source only allows Observer traffic when all of the following are true:

1. `OBSERVER_ENABLED=1` was explicitly configured.
2. `OBSERVER_TARGET` is the literal loopback URL `http://127.0.0.1:8005` or `http://[::1]:8005`.
3. `BIND` is literal loopback (`127.0.0.1` or `::1`).
4. The direct TCP peer is loopback. `X-Forwarded-For` is ignored for this decision.

That combination requires a topology where gateway and Observer share a host network namespace and the gateway itself is bound to host loopback, or an equivalent user-approved local-only bridge. The ordinary Docker-container-to-host-loopback arrangement is not claimed to work. Enabling it therefore requires a runtime/compose decision from the integrator; this gateway source does not change compose mappings or Observer binding.

## Runtime connection contract

The runtime worker must provide the `unified-web`, `qwen-code`, `artex`, and `scope-sentry` DNS names or override the four target variables. It must also choose how the gateway is published; this source does not add or alter compose port mappings. Qwen’s native bearer token, ARTEX JWT/cookie, ScopeSentry JWT/keys, and Observer state remain in their existing service boundaries. The gateway does not exchange, merge, or synthesize credentials.

The focused route regression source is in `test/router.test.mjs`. It is intentionally not executed in the source-only phase.
