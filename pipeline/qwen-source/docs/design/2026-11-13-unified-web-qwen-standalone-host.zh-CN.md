# Unified Web Qwen 独立主机设计

[English](2026-11-13-unified-web-qwen-standalone-host.md) | [简体中文](2026-11-13-unified-web-qwen-standalone-host.zh-CN.md)

## 状态

Qwen worker 的授权范围内已于 2026-11-13 完成 source implementation。由于本任务明确禁止安装、构建、typecheck、测试、应用运行和真实 daemon/model 调用，运行时行为、依赖解析、打包、gateway 路由与 feature parity 仍未验证。

## 问题与当前状态

所提供的 Qwen Web Shell 是完整 standalone application，不是缩减版聊天 widget。`client/main.tsx` 提供 standalone context、浏览器通知、daemon/session provider、workspace hosts、完整 sidebar/footer、native 页面导航、pairing/auth 和完整 `App`。`App.tsx` 还拥有 settings、sessions、workspaces、agents、plugins、Skills/MCP/Extensions、channels/events、Live、workflows、goals、scheduled tasks、PR watches、split view、files、terminal、review、preview、artifacts、media 和 capability gates 等完整页面及隐藏 surface。

Unified application 拥有浏览器 history，因此 Qwen 挂载在 `/ai` 时不能写 document pathname，也不能与 ARTEX/Vue routing 竞争。默认及 same-origin Qwen daemon REST/SSE/WebSocket traffic 使用 namespaced gateway base `/qwen-api`。用户明确选择的 remote target 保留 native target provider 的 validated-origin 与部署 CSP 行为；本文不声称所有 remote request 都会重写到本地 gateway。Qwen branding 必须由 host 控制，同时保留 legal notices 和技术性的 Qwen identifiers。

## 目标

1. 发布真正的 `@qwen-code/web-shell/standalone-host` public entry，挂载完整 standalone provider/session/App composition。
2. 通过 `unified-web/src/modules/qwen/index.tsx` 接受 unified host contract（`active`、`theme`、`path`、`onNavigate`）。
3. inactive 时使用 hidden wrapper 保持完整 Qwen tree mounted；不传 `viewHidden`，切换 module 时不卸载 `App` 或 provider。
4. 通过 host callback 路由 Qwen 本地导航，不写 `window.history`、`window.location.pathname` 或共享的 global pathname。
5. 默认及 same-origin Qwen daemon HTTP/SSE/WS URL 使用 `/qwen-api`；保留用户明确选择的 native multi-host target，并将各 Qwen credential 限定在 Qwen provider 边界内。
6. 默认使用 `Project-Malaria` 产品 brand，不批量重命名 Qwen technical IDs、API route、daemon settings、legal notices 或 attribution。

## 范围边界

本节仅描述 Qwen worker 的贡献范围。范围包括 `packages/web-shell` 的 public entry/build configuration、窄范围 host navigation adapter、same-origin pairing exchange 支持、unified Qwen module adapter、双语设计文档和未运行的 E2E test plan。native `main.tsx` 行为不重写。不重构 core/auth-provider/model/tool/runtime policy。此 Qwen 专项改动没有编辑 Qwen worker gateway/server、runtime Docker 文件、lockfile 或无关 worker 文件；这不代表独立的 unified integration 没有 gateway 或 Docker 改动。

Host 不虚构 managed-agent 行为、permission policy、model/tool policy，也不创建第二套 session implementation。native capability checks 和 native `WorkspaceSessionProvider` 仍是权威来源。

## 方案（已实现的 source 边界）

### 完整 standalone public entry

`client/standalone-host.tsx` 作为 library entry 发布为 `@qwen-code/web-shell/standalone-host`。它导入 scoped Web Shell/global/standalone styles，挂载 `StandaloneContext`、`WorkspaceHostsEnabled`、`DaemonTargetProvider`、`DaemonWorkspaceProvider`、`WorkspaceSessionProvider`、`BrowserTurnNotifications`，并使用 `WorkspaceSessionProvider` 选择的完整 native `App` composition。它使用 native 默认 primary/footer navigation，而不是 `sidebar={false}` 或缩减后的 navigation list。Header、right-panel、environment-panel、composer、media、artifacts、file、terminal、review、preview、notification、session、settings 和 capability-gated page 均继续交给 native props/components。

`brand` 默认值为 `{ name: 'Project-Malaria' }`，移除 Qwen logo node 并改变产品 chrome，但不改变技术数据。调用方可以提供 host-owned brand。Unified resolved theme 会传给 shell 和 chrome。inactive host wrapper 使用 `hidden` 和 `aria-hidden`，但仍保持 mounted，因此 module 切换不会重置 React state、draft、active stream 或 provider lifecycle。

### Host-owned navigation

`WebShellHostNavigationBoundary` 使用既有 navigation URL parser 解析 module-local `path`，在 React state 中维护 native route/session target。Native `openPage`、session 创建/切换、`returnToChat` 和 page reconciliation 会被翻译成本地 path 并发送给 `onNavigate(path, replace)`。外部 path 变化会更新 boundary state。Adapter 不调用 `pushState`、`replaceState`、`assign` 或 global pathname setter。既有 native `WebShellNavigationBoundary` 与普通 standalone `main.tsx` 行为不变。

### Same-origin transport 与 auth

默认 daemon 及明确选定的 same-origin target 使用 `${window.location.origin}/qwen-api` 作为 client base。既有 SDK 会在该 base 下拼接 `/capabilities`、`/session/...`、SSE `/events` 与 ACP `/acp`，因此 gateway 必须保留 HTTP、长连接 SSE 和 WebSocket upgrade 语义。Native `DaemonTargetProvider` 与 focused `DaemonWorkspaceProvider` 仍保持挂载；saved/fan-out workspace hosts、focus 切换、session handoff 和 per-target Qwen token 继续通过 host-owned route callback。用户明确选择 remote daemon origin 时，保留 native validated-origin/CSP 行为，不把该 target 错误描述成 local `/qwen-api` request。Optional trusted host token 或 Qwen-specific stored token 只用于 Qwen provider 边界；不会读取或发送 ARTEX JWT、ScopeSentry key 或其他 module token。Host 执行窄范围 `/capabilities` probe，支持 same-origin pairing exchange，并提供固定 Qwen token recovery form，不暴露 remote-origin input。

`config/pairing.ts` 现在允许 same-origin 且带 path 的 base URL，同时保留普通 standalone boot 的原有 origin-only 行为。这样 pairing request 仍位于 `/qwen-api` 下，不会扩大 target origin。

## 设计决策与理由

- **独立 public entry：** import `client/main.tsx` 会执行 native bootstrap side effects，不能作为安全的 library component。独立 entry 复用 native target/workspace/session provider 和 App，但不执行 document bootstrap；target navigation 将 URL ownership 交给 host。
- **Host callback 代替浏览器 history：** unified router 是 document URL 的唯一 owner。Qwen 本地 route state 仍支持 native page/session deep links。
- **Namespaced same-origin base 加 native target：** 带 path 的默认 base 给 gateway 明确的 Qwen namespace；用户明确选择的 native Qwen target 保留原有 target 行为，且不会接收其他 module credential。
- **Hidden 而非 unmounted：** inactive module 切换必须保持 draft、stream、session state 和 provider lifecycle。
- **不重命名 technical ID：** 可见产品 branding 由 host 所有；API subject、daemon setting key、MCP row、session metadata 和 license/notice 文本保持 native。

## 约束与风险

浏览器不能为 native WebSocket 附加 Authorization header；当前 SDK 的 ACP browser transport 建立 socket 时也没有 daemon bearer subprotocol。仅修改 UI 不能安全地自行引入无 token、cookie、query-token 或跨 module authentication；ACP-over-WebSocket 在 SDK 提供受支持 transport 或用户明确批准 authenticated proxy contract 前仍是兼容性 blocker。Same-origin gateway routing 及所选外部 daemon 的 CSP/remote-origin 行为也仍需 runtime 验证；此处不会静默扩大 CORS 或 credential policy。Desktop-only local file、terminal、updater、media 与 screen-capture 行为仍依赖 browser capability、daemon capability、CSP 和部署 topology。

Native `App` 通过内部 action 和部分 global URL convention 初始化非 `WebShellPage` 的 `mainView` surface（workflows、scheduled tasks、goals、PR watches 以及 split/cockpit state）。Host 保留通过 native sidebar 与 slash-command action 访问这些功能，但不声称每一种 `mainView` variant 都已有 module-local deep-link adapter；这需要获准的窄范围 App route-input patch。

Package entry 只完成 source declaration，本任务不会生成 `dist` artifact 或 declaration。Unified host package 后续必须声明 file dependency，并将 dynamic module 指向构建后的 entry。提供的 ZIP/package version 差异仍待获准后按精确版本验证。

## 验证计划

配套的 `.qwen/e2e-tests/qwen-standalone-host.md` 列出所需检查，但没有运行。后续获准验证必须构建 public entry，检查生成的 CSS/declaration，在受控 route host 中挂载 module，验证 inactive persistence，测试 `/qwen-api` HTTP/SSE/WS request，验证 pairing/token isolation，并针对 approved daemon fixture 运行全部 capability-gated native page。还必须单独验证 ARTEX 与 Vue module 的 route ownership。

## 验收标准

- Package 暴露 `@qwen-code/web-shell/standalone-host`，兼容的 Vite entry 输出 JS/CSS/declaration surface。
- `unified-web/src/modules/qwen/index.tsx` 是默认的 `UnifiedModuleProps` adapter。
- `active` 为 false 时 Qwen App/provider 仍 mounted；不使用 `viewHidden`，不使用缩减 sidebar。
- Native Qwen navigation 调用 host callback，不修改共享浏览器 history。
- 默认及 same-origin Qwen REST/SSE/WS request 使用 `/qwen-api`；用户明确选择的 native target 保留 validated target 行为；不附带其他 module credential。
- Pairing、session、settings、workspace、sidebar/footer、composer、media、artifact 和 capability-gated native page 继续由 source-native composition 提供。
- Branding 默认是 Project-Malaria，同时保留 legal notices、licenses 和 technical identifiers。
- Native multi-host/workspace target provider 保持挂载并由 host 路由；ACP browser authentication、gateway/CSP 行为和 runtime parity 仍作为 open blocker 报告，不伪装成已验证。

## 待决问题

1. 当 browser 不能设置 `Authorization` header 时，gateway 将采用什么精确机制授权 browser WebSocket upgrade？
2. 应采用什么获准的 gateway/CSP deployment contract，以验证 same-origin routing 和保留的 native remote-daemon target 行为？
3. Unified-web integrator 将采用哪一个 dependency declaration 和 dynamic import configuration 来消费构建后的 Qwen library entry？
4. 精确的 supplied Qwen version baseline 是 ZIP inventory 的 `0.27.1`，还是 package metadata 的 `0.27.2`？
5. 部署 web topology 允许哪些 local file、terminal、media、screen sharing、mobile access 和 updater browser/runtime capability？
