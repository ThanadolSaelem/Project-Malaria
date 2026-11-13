/**
 * @license
 * Copyright 2026 Qwen Team
 * SPDX-License-Identifier: Apache-2.0
 */

import './styles/globals.css';
import 'katex/dist/katex.min.css';
import './styles/standalone.css';

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { DaemonWorkspaceProvider } from '@qwen-code/web-shell/daemon-react-sdk';
import { BrowserTurnNotifications } from './browser-turn-notifications';
import { ErrorBoundary } from './components/ErrorBoundary';
import { RootErrorFallback } from './components/RootErrorFallback';
import { WorkspaceSessionProvider } from './components/WorkspaceSessionProvider';
import AppStyles from './App.module.css';
import { StandaloneContext } from './config/standalone';
import { WorkspaceHostsEnabled } from './config/workspace-hosts';
import { createDaemonRestRequest } from './daemon/rest-request';
import {
  exchangePairingCode,
  type PairingNavigationOptions,
} from './config/pairing';
import {
  getAllowedDaemonOrigin,
  getDaemonToken,
  persistDaemonToken,
} from './config/daemon';
import {
  DaemonTargetProvider,
  useDaemonTarget,
  useFanoutUrlSync,
  type DaemonTargetNavigation,
} from './config/daemon-target';
import {
  WebShellHostNavigationBoundary,
  type WebShellHostNavigationOptions,
} from './navigation';
import { normalizeLanguage, type WebShellLanguage } from './i18n';
import { WebShellThemeId, type WebShellTheme } from './themeContext';
import { type WebShellBrand } from './brandContext';
import {
  DEFAULT_FOOTER_ITEMS,
  DEFAULT_PRIMARY_NAV_ITEMS,
} from './components/sidebar/WebShellSidebar';

const QWEN_API_PATH = '/qwen-api';
const HOST_BRAND: WebShellBrand = { name: 'Project-Malaria' };
const STANDALONE_COMPOSER_TOOLBAR_ADDITIONS = ['addMenu', 'plan'] as const;

export interface StandaloneHostProps {
  /** Visual activity only; the complete native tree and background work stay mounted. */
  active: boolean;
  /** Resolved theme owned by the surrounding unified application. */
  theme: WebShellTheme;
  /** Qwen-local route, without the unified application's module prefix. */
  path: string;
  /** Host-owned route callback. This entry never writes browser history itself. */
  onNavigate: WebShellHostNavigationOptions['onNavigate'];
  /** Optional Qwen daemon credential supplied by a trusted host. */
  token?: string;
  /** Optional host language; omitted values follow the browser locale. */
  language?: WebShellLanguage;
  /** Optional host product branding. The default removes Qwen product chrome. */
  brand?: WebShellBrand;
  /** Optional ancestor-owned portal mount; omitted portals remain under document.body. */
  portalContainer?: HTMLElement | null;
}

type HostAuthState =
  | { status: 'checking'; token?: string }
  | { status: 'ready'; token?: string }
  | { status: 'token'; pairingFailed?: boolean }
  | { status: 'error'; message: string };

function resolveQwenBaseUrl(targetOrigin?: string): string {
  if (typeof window === 'undefined') return QWEN_API_PATH;
  const origin = targetOrigin || window.location.origin;
  return origin === window.location.origin
    ? `${window.location.origin}${QWEN_API_PATH}`
    : origin;
}

function initialTargetOrigin(path: string): string | undefined {
  try {
    const raw = new URL(
      path || '/',
      'http://qwen-host.invalid',
    ).searchParams.get('daemon');
    return raw ? getAllowedDaemonOrigin(raw) || undefined : undefined;
  } catch {
    return undefined;
  }
}

function replacePairingPath(
  path: string,
  url: URL,
  onNavigate: WebShellHostNavigationOptions['onNavigate'],
): void {
  const next = new URL(path || '/', 'http://qwen-host.invalid');
  next.hash = url.hash;
  onNavigate(`${next.pathname}${next.search}${next.hash}`, true);
}

function authMessage(
  state: HostAuthState,
  language: WebShellLanguage,
): string {
  if (state.status === 'error') return state.message;
  if (state.status === 'token') {
    return state.pairingFailed
      ? language === 'zh-CN'
        ? '配对未完成。请输入 Qwen daemon token。'
        : 'Pairing did not complete. Enter the Qwen daemon token.'
      : language === 'zh-CN'
        ? '请输入 Qwen daemon token。'
        : 'Enter the Qwen daemon token.';
  }
  return language === 'zh-CN' ? '正在连接 Qwen…' : 'Connecting to Qwen…';
}

function HostAuthGate({
  baseUrl,
  suppliedToken,
  theme,
  language,
  pairingNavigation,
  children,
}: {
  baseUrl: string;
  suppliedToken?: string;
  theme: WebShellTheme;
  language: WebShellLanguage;
  pairingNavigation?: PairingNavigationOptions;
  children: (token: string | undefined) => ReactNode;
}) {
  const [manualToken, setManualToken] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<HostAuthState>(() => ({
    status: 'checking',
    token: suppliedToken ?? getDaemonToken(baseUrl),
  }));
  const [input, setInput] = useState('');

  useEffect(() => {
    setManualToken(undefined);
    setInput('');
  }, [baseUrl, suppliedToken]);

  const candidate = manualToken ?? suppliedToken ?? getDaemonToken(baseUrl);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    setState({ status: 'checking', token: candidate });
    void (async () => {
      const pairing = await exchangePairingCode(baseUrl, pairingNavigation);
      const token =
        candidate ?? pairing?.token ?? getDaemonToken(baseUrl);
      if (pairing?.failed && !token) {
        if (!disposed) setState({ status: 'token', pairingFailed: true });
        return;
      }
      try {
        const response = await createDaemonRestRequest(
          baseUrl,
          token,
          undefined,
          true,
        )('/capabilities', {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
          cache: 'no-store',
          redirect: 'error',
        });
        if (disposed) return;
        if (response.ok) {
          if (token) persistDaemonToken(token, baseUrl);
          setState({ status: 'ready', token });
        } else if (response.status === 401) {
          setState({
            status: 'token',
            pairingFailed: pairing?.failed,
          });
        } else {
          setState({
            status: 'error',
            message:
              language === 'zh-CN'
                ? `Qwen gateway 返回 HTTP ${response.status}。`
                : `The Qwen gateway returned HTTP ${response.status}.`,
          });
        }
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setState({
          status: 'error',
          message:
            error instanceof Error
              ? error.message
              : language === 'zh-CN'
                ? '无法连接 Qwen gateway。'
                : 'The Qwen gateway could not be reached.',
        });
      }
    })();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [attempt, baseUrl, candidate, language, pairingNavigation]);

  if (state.status === 'ready') return children(state.token);

  return (
    <div
      data-web-shell-root
      data-web-shell-shadcn
      data-web-shell-gate
      className={`flex min-h-screen items-center justify-center bg-background p-6 text-foreground ${
        theme === WebShellThemeId.Light
          ? AppStyles.themeLight
          : `${AppStyles.themeDark} dark`
      }`}
    >
      <div className="flex w-full max-w-md flex-col gap-4 rounded-lg border bg-card p-6 shadow-sm">
        <h1 className="text-xl font-semibold">Project-Malaria</h1>
        <p role="status" className="text-sm text-muted-foreground">
          {authMessage(state, language)}
        </p>
        {state.status === 'token' && (
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              const next = input.trim();
              if (!next) return;
              setManualToken(next);
              setAttempt((value) => value + 1);
            }}
          >
            <label className="text-sm" htmlFor="qwen-host-token">
              Bearer token
            </label>
            <input
              id="qwen-host-token"
              className="rounded-md border bg-background px-3 py-2 font-mono text-sm"
              type="password"
              autoComplete="off"
              value={input}
              onChange={(event) => setInput(event.target.value)}
            />
            <button
              className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground"
              type="submit"
            >
              {language === 'zh-CN' ? '连接' : 'Connect'}
            </button>
          </form>
        )}
        {state.status === 'error' && (
          <button
            className="rounded-md border px-3 py-2 text-sm"
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            {language === 'zh-CN' ? '重试' : 'Retry'}
          </button>
        )}
      </div>
    </div>
  );
}

function FocusedHostWorkspaceProvider({
  bootToken,
  navigation,
  children,
}: {
  bootToken?: string;
  navigation: DaemonTargetNavigation;
  children: ReactNode;
}) {
  useFanoutUrlSync(navigation);
  const { activeOrigin, activeToken } = useDaemonTarget();
  const baseUrl = useMemo(
    () => resolveQwenBaseUrl(activeOrigin),
    [activeOrigin],
  );
  const pageOrigin =
    typeof window === 'undefined' ? '' : window.location.origin;
  return (
    <DaemonWorkspaceProvider
      key={activeOrigin}
      baseUrl={baseUrl}
      token={activeToken ?? (activeOrigin === pageOrigin ? bootToken : undefined)}
    >
      {children}
    </DaemonWorkspaceProvider>
  );
}

export function StandaloneHost({
  active,
  theme,
  path,
  onNavigate,
  token,
  language: providedLanguage,
  brand = HOST_BRAND,
  portalContainer = null,
}: StandaloneHostProps) {
  const baseUrl = useMemo(
    () => resolveQwenBaseUrl(initialTargetOrigin(path)),
    [],
  );
  const language =
    providedLanguage ??
    normalizeLanguage(typeof navigator === 'undefined' ? 'en' : navigator.language);
  const navigationOptions = useMemo(
    () => ({ path, onNavigate }) satisfies DaemonTargetNavigation,
    [onNavigate, path],
  );
  const pathRef = useRef(path);
  pathRef.current = path;
  const onNavigateRef = useRef(onNavigate);
  onNavigateRef.current = onNavigate;
  const pairingNavigation = useMemo<PairingNavigationOptions>(
    () => ({
      replaceUrl: (url) =>
        replacePairingPath(pathRef.current, url, onNavigateRef.current),
    }),
    [],
  );

  return (
    <div
      data-project-malaria-module="qwen"
      data-web-shell-host
      hidden={!active}
      aria-hidden={!active}
      style={{ minHeight: '100%', width: '100%' }}
    >
      <ErrorBoundary
        label="web-shell-root"
        fallback={(error, reset) => (
          <RootErrorFallback error={error} onRetry={reset} language={language} />
        )}
      >
        <HostAuthGate
          baseUrl={baseUrl}
          suppliedToken={token}
          theme={theme}
          language={language}
          pairingNavigation={pairingNavigation}
        >
          {(daemonToken) => (
            /* Notification activity is intentionally independent from visual
             * module activity so background Qwen turns remain notifying. */
            <BrowserTurnNotifications
              language={language}
              options={{
                defaultEnabled: true,
                appName: brand.name || 'Project-Malaria',
              }}
              active
            >
              <StandaloneContext.Provider value>
                <WorkspaceHostsEnabled.Provider value>
                  <DaemonTargetProvider navigation={navigationOptions}>
                    <FocusedHostWorkspaceProvider
                      bootToken={daemonToken}
                      navigation={navigationOptions}
                    >
                      <WebShellHostNavigationBoundary
                        options={navigationOptions}
                        externalTarget={{}}
                      >
                        {(target, onSessionIdChange) => (
                          <WorkspaceSessionProvider
                            sessionId={target.sessionId}
                            workspaceId={target.workspaceId}
                            workspaceCwd={target.workspaceCwd}
                            sessionContext={target.sessionContext}
                            chromeTheme={theme}
                            chromeLanguage={language}
                            webShellProps={{
                              theme,
                              language,
                              brand,
                              uiActivity: { active, portalContainer },
                              onSessionIdChange,
                              sidebar: {
                                enabled: true,
                                showLive: true,
                                primaryNav: { items: DEFAULT_PRIMARY_NAV_ITEMS },
                                footer: { items: DEFAULT_FOOTER_ITEMS },
                              },
                              showToolCalls: true,
                              header: {
                                showMobileAccess: true,
                                items: [
                                  'title',
                                  'environment',
                                  'rightPanel',
                                  'tokenUsage',
                                  'contextUsage',
                                ],
                              },
                              rightPanel: {
                                items: [
                                  'files',
                                  'review',
                                  'sideTask',
                                  'terminal',
                                  'webPreview',
                                  'trajectory',
                                ],
                              },
                              environmentPanel: {
                                items: [
                                  'environment',
                                  'sources',
                                  'subagents',
                                  'backgroundTasks',
                                  'attachments',
                                  'artifacts',
                                ],
                              },
                              compactThinking: true,
                              markdownTableMode: 'advanced',
                              composerToolbarAdditionalActions:
                                STANDALONE_COMPOSER_TOOLBAR_ADDITIONS,
                            }}
                          />
                        )}
                      </WebShellHostNavigationBoundary>
                    </FocusedHostWorkspaceProvider>
                  </DaemonTargetProvider>
                </WorkspaceHostsEnabled.Provider>
              </StandaloneContext.Provider>
            </BrowserTurnNotifications>
          )}
        </HostAuthGate>
      </ErrorBoundary>
    </div>
  );
}

export default StandaloneHost;
