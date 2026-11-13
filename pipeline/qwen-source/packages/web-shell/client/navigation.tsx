/**
 * @license
 * Copyright 2026 Qwen Team
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { DaemonProductSessionContext } from '@qwen-code/web-shell/daemon-react-sdk';
import type { WebShellProps } from './App';
import {
  buildNavigationUrl,
  normalizeNavigationBasePath,
  readNavigationUrl,
  type SessionUrlTarget,
  type WebShellPage,
  type WebShellRoute,
} from './utils/navigationUrl';

export type { WebShellPage } from './utils/navigationUrl';
export interface WebShellUrlNavigationOptions {
  /** URL pathname containing the shell, e.g. /agentic-code. Defaults to root. */
  basePath?: string;
}
export interface WebShellHostNavigationOptions {
  /** Module-local path supplied by the surrounding application. */
  path: string;
  /** Route callback owned by the surrounding application. */
  onNavigate: (path: string, replace?: boolean) => void;
}
export interface NavigationSessionProps {
  sessionId?: string;
  workspaceId?: string;
  workspaceCwd?: string;
  sessionContext?: DaemonProductSessionContext;
}
interface NavigationState {
  route: WebShellRoute;
  target: NavigationSessionProps;
  revision: number;
  historyRevision?: number;
}
interface NavigationController {
  route: WebShellRoute;
  revision: number;
  historyRevision?: number;
  openPage: (page: WebShellPage) => void;
  returnToChat: () => void;
  reconcilePage: (page: WebShellPage | undefined) => void;
  beginSessionNavigation: (
    sessionId?: string,
    workspaceId?: string,
    sessionContext?: DaemonProductSessionContext,
  ) => void;
  cancelSessionNavigation: () => void;
  finishNewChat: (context?: DaemonProductSessionContext) => void;
}
const NavigationContext = createContext<NavigationController | undefined>(
  undefined,
);
export const useWebShellNavigation = () => useContext(NavigationContext);
const STATE_KEY = '__qwenWebShellNavigation';

function sessionTarget(route: SessionUrlTarget): NavigationSessionProps {
  return {
    sessionId: route.sessionId,
    workspaceId: route.workspaceId,
    sessionContext: route.context ? { kind: route.context } : undefined,
  };
}
function sessionRoute(target: NavigationSessionProps): WebShellRoute {
  const kind = target.sessionContext?.kind;
  return {
    page: 'chat',
    sessionId: target.sessionId,
    workspaceId: target.workspaceId,
    context: kind === 'standalone' || kind === 'live' ? kind : undefined,
  };
}
function returnTarget(basePath: string): NavigationSessionProps | undefined {
  const value: unknown = window.history.state?.[STATE_KEY];
  if (!value || typeof value !== 'object') return undefined;
  const entry = value as { basePath?: unknown; source?: unknown };
  if (entry.basePath !== basePath || typeof entry.source !== 'string') {
    return undefined;
  }
  try {
    const source = new URL(entry.source, window.location.origin);
    if (source.origin !== window.location.origin) return undefined;
    const route = readNavigationUrl(source, basePath);
    return route?.page === 'chat' ? sessionTarget(route) : undefined;
  } catch {
    return undefined;
  }
}

export function WebShellNavigationBoundary({
  options,
  externalTarget,
  onSessionIdChange,
  children,
}: {
  options?: WebShellUrlNavigationOptions;
  externalTarget: NavigationSessionProps;
  onSessionIdChange?: WebShellProps['onSessionIdChange'];
  children: (
    target: NavigationSessionProps,
    onChange: NonNullable<WebShellProps['onSessionIdChange']>,
  ) => ReactNode;
}) {
  const enabled = options !== undefined;
  const basePath = normalizeNavigationBasePath(options?.basePath);
  const [state, setState] = useState<NavigationState>(() => {
    const urlRoute = enabled
      ? readNavigationUrl(new URL(window.location.href), basePath)
      : undefined;
    const explicit = Object.values(externalTarget).some(
      (value) => value !== undefined,
    );
    const target = explicit
      ? externalTarget
      : urlRoute?.page === 'chat'
        ? sessionTarget(urlRoute)
        : enabled
          ? (returnTarget(basePath) ?? {})
          : externalTarget;
    return {
      route: explicit ? sessionRoute(target) : (urlRoute ?? { page: 'chat' }),
      target,
      revision: 0,
    };
  });
  const current = useRef(state);
  current.current = state;
  const pendingSession = useRef<{ sessionId?: string } | undefined>({
    sessionId: state.target.sessionId,
  });
  const userSessionNavigation = useRef(false);
  const restoringHistory = useRef(false);
  const externalKey = JSON.stringify(externalTarget);
  const previousExternalKey = useRef(externalKey);

  const commit = useCallback(
    (
      route: WebShellRoute,
      target: NavigationSessionProps,
      mode: 'push' | 'replace' | 'replay',
    ) => {
      if (!enabled) return;
      const pathname = window.location.pathname;
      if (pathname !== basePath && !pathname.startsWith(`${basePath}/`)) return;
      if (mode !== 'replay') {
        const before = new URL(window.location.href);
        const url = buildNavigationUrl(before, route, basePath);
        if (route.page !== 'chat') {
          if (url.searchParams.get('view') === 'cockpit') {
            url.searchParams.delete('view');
          }
        }
        const existing = window.history.state;
        const historyState = {
          ...(existing && typeof existing === 'object' ? existing : {}),
          [STATE_KEY]: {
            basePath,
            source:
              route.page !== 'chat'
                ? buildNavigationUrl(
                    before,
                    current.current.route.page === 'chat'
                      ? current.current.route
                      : sessionRoute(returnTarget(basePath) ?? {}),
                    basePath,
                  ).href
                : undefined,
          },
        };
        if (url.href !== before.href) {
          window.history[mode === 'push' ? 'pushState' : 'replaceState'](
            historyState,
            '',
            url,
          );
        }
      }
      const next: NavigationState = {
        route,
        target,
        revision:
          current.current.revision +
          (mode === 'replay' || route.page !== current.current.route.page
            ? 1
            : 0),
      };
      const historyRevision =
        mode === 'replay' ? next.revision : current.current.historyRevision;
      next.historyRevision = historyRevision;
      current.current = next;
      setState(next);
    },
    [basePath, enabled],
  );

  useEffect(() => {
    if (!enabled) return;
    commit(current.current.route, current.current.target, 'replace');
  }, [commit, enabled]);

  useEffect(() => {
    if (!enabled) return;
    if (previousExternalKey.current !== externalKey) {
      previousExternalKey.current = externalKey;
      if (
        JSON.stringify(sessionRoute(externalTarget)) ===
          JSON.stringify(sessionRoute(current.current.target)) &&
        (externalTarget.workspaceCwd === undefined ||
          externalTarget.workspaceCwd === current.current.target.workspaceCwd)
      )
        return;
      pendingSession.current = { sessionId: externalTarget.sessionId };
      commit(sessionRoute(externalTarget), externalTarget, 'replace');
    }
  }, [commit, enabled, externalKey, externalTarget]);

  useEffect(() => {
    if (!enabled) return;
    const handlePopState = () => {
      const route = readNavigationUrl(new URL(window.location.href), basePath);
      userSessionNavigation.current = false;
      restoringHistory.current = true;
      if (!route) return;
      const target =
        route.page === 'chat'
          ? sessionTarget(route)
          : (returnTarget(basePath) ?? {});
      const changed =
        JSON.stringify(sessionRoute(target)) !==
        JSON.stringify(sessionRoute(current.current.target));
      pendingSession.current = changed
        ? { sessionId: target.sessionId }
        : undefined;
      restoringHistory.current = changed;
      commit(route, target, 'replay');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [basePath, commit, enabled]);

  const handleSessionChange = useCallback<
    NonNullable<WebShellProps['onSessionIdChange']>
  >(
    (sessionId, workspaceId, workspaceCwd, sessionContext) => {
      if (enabled) {
        if (
          pendingSession.current &&
          pendingSession.current.sessionId !== sessionId
        ) {
          return;
        }
        const wasPending = pendingSession.current !== undefined;
        pendingSession.current = undefined;
        const target = { sessionId, workspaceId, workspaceCwd, sessionContext };
        if (
          current.current.route.page === 'chat' ||
          userSessionNavigation.current
        ) {
          const nextRoute = sessionRoute(target);
          const before = current.current.route;
          const sameSession =
            before.page === 'chat' && before.sessionId === sessionId;
          commit(
            nextRoute,
            target,
            restoringHistory.current
              ? 'replay'
              : wasPending || (sameSession && !userSessionNavigation.current)
                ? 'replace'
                : 'push',
          );
        } else {
          current.current = { ...current.current, target };
          setState(current.current);
        }
      }
      userSessionNavigation.current = false;
      restoringHistory.current = false;
      if (sessionContext)
        onSessionIdChange?.(
          sessionId,
          workspaceId,
          workspaceCwd,
          sessionContext,
        );
      else onSessionIdChange?.(sessionId, workspaceId, workspaceCwd);
    },
    [commit, enabled, onSessionIdChange],
  );
  const controller = useMemo<NavigationController | undefined>(
    () =>
      enabled
        ? {
            route: state.route,
            revision: state.revision,
            historyRevision: state.historyRevision,
            openPage: (page) => {
              restoringHistory.current = false;
              userSessionNavigation.current = false;
              if (current.current.route.page === page) return;
              commit({ page }, current.current.target, 'push');
            },
            returnToChat: () => {
              restoringHistory.current = false;
              userSessionNavigation.current = false;
              const target = returnTarget(basePath) ?? {};
              pendingSession.current =
                JSON.stringify(sessionRoute(target)) !==
                JSON.stringify(sessionRoute(current.current.target))
                  ? { sessionId: target.sessionId }
                  : undefined;
              commit(sessionRoute(target), target, 'push');
            },
            reconcilePage: (page) => {
              if (userSessionNavigation.current) return;
              if (
                current.current.route.page === 'chat' ||
                (page ?? 'chat') === current.current.route.page
              )
                return;
              commit(
                page ? { page } : sessionRoute(current.current.target),
                current.current.target,
                'replace',
              );
            },
            cancelSessionNavigation: () => {
              userSessionNavigation.current = false;
              pendingSession.current = undefined;
            },
            finishNewChat: (sessionContext) => {
              if (!userSessionNavigation.current) return;
              userSessionNavigation.current = false;
              pendingSession.current = undefined;
              const target = {
                sessionId: undefined,
                workspaceId: undefined,
                workspaceCwd: undefined,
                sessionContext,
              };
              commit(sessionRoute(target), target, 'push');
            },
            beginSessionNavigation: (
              sessionId,
              workspaceId,
              sessionContext,
            ) => {
              restoringHistory.current = false;
              userSessionNavigation.current = true;
              pendingSession.current = { sessionId };
              commit(
                sessionRoute({ sessionId, workspaceId, sessionContext }),
                current.current.target,
                'push',
              );
            },
          }
        : undefined,
    [
      basePath,
      commit,
      enabled,
      state.revision,
      state.route,
      state.historyRevision,
    ],
  );
  return (
    <NavigationContext.Provider value={controller}>
      {children(enabled ? state.target : externalTarget, handleSessionChange)}
    </NavigationContext.Provider>
  );
}

function hostPathUrl(path: string): URL {
  return new URL(path || '/', 'http://qwen-host.invalid');
}

function hostRoutePath(route: WebShellRoute, currentPath: string): string {
  const url = buildNavigationUrl(hostPathUrl(currentPath), route);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Navigation boundary for an application that already owns browser history.
 * Unlike WebShellNavigationBoundary, this adapter never reads or writes the
 * page URL and reports local route changes through the host callback.
 */
export function WebShellHostNavigationBoundary({
  options,
  externalTarget,
  onSessionIdChange,
  children,
}: {
  options: WebShellHostNavigationOptions;
  externalTarget: NavigationSessionProps;
  onSessionIdChange?: WebShellProps['onSessionIdChange'];
  children: (
    target: NavigationSessionProps,
    onChange: NonNullable<WebShellProps['onSessionIdChange']>,
  ) => ReactNode;
}) {
  const { path, onNavigate } = options;
  const parsedRoute = useMemo(() => {
    const route = readNavigationUrl(hostPathUrl(path));
    return route;
  }, [path]);
  const parsed = parsedRoute ?? { page: 'chat' as const };
  const initialTarget = useMemo(
    () =>
      parsed.page === 'chat'
        ? sessionTarget(parsed)
        : externalTarget,
    [externalTarget, parsed],
  );
  const [state, setState] = useState<NavigationState>(() => ({
    route: parsed,
    target: initialTarget,
    revision: 0,
  }));
  const current = useRef(state);
  current.current = state;
  const lastChatTarget = useRef<NavigationSessionProps>(initialTarget);
  const pendingSession = useRef<{ sessionId?: string } | undefined>();
  const userSessionNavigation = useRef(false);
  const pathRef = useRef(path);
  pathRef.current = path;

  useEffect(() => {
    if (parsedRoute) return;
    const nextPath = hostRoutePath({ page: 'chat' }, path);
    if (nextPath !== path) onNavigate(nextPath, true);
  }, [onNavigate, parsedRoute, path]);

  useEffect(() => {
    if (pathRef.current !== path) pathRef.current = path;
    const nextTarget =
      parsed.page === 'chat' ? sessionTarget(parsed) : current.current.target;
    if (parsed.page === 'chat') lastChatTarget.current = nextTarget;
    if (
      JSON.stringify(current.current.route) === JSON.stringify(parsed) &&
      JSON.stringify(current.current.target) === JSON.stringify(nextTarget)
    )
      return;
    const next: NavigationState = {
      route: parsed,
      target: nextTarget,
      revision: current.current.revision + 1,
      historyRevision: current.current.revision + 1,
    };
    current.current = next;
    setState(next);
  }, [parsed, path]);

  const commit = useCallback(
    (
      route: WebShellRoute,
      target: NavigationSessionProps,
      mode: 'push' | 'replace' | 'replay',
    ) => {
      const nextPath = hostRoutePath(route, pathRef.current);
      if (nextPath !== pathRef.current && mode !== 'replay') {
        onNavigate(nextPath, mode === 'replace');
      }
      if (route.page === 'chat') lastChatTarget.current = target;
      const next: NavigationState = {
        route,
        target,
        revision:
          current.current.revision +
          (route.page !== current.current.route.page ? 1 : 0),
        historyRevision: current.current.revision + 1,
      };
      current.current = next;
      setState(next);
    },
    [onNavigate],
  );

  useEffect(() => {
    if (parsed.page !== 'chat') return;
    const target = sessionTarget(parsed);
    if (
      JSON.stringify(target) === JSON.stringify(current.current.target) ||
      userSessionNavigation.current
    )
      return;
    current.current = {
      ...current.current,
      target,
      historyRevision: current.current.historyRevision,
    };
    setState(current.current);
  }, [parsed]);

  const handleSessionChange = useCallback<
    NonNullable<WebShellProps['onSessionIdChange']>
  >(
    (sessionId, workspaceId, workspaceCwd, sessionContext) => {
      const target = { sessionId, workspaceId, workspaceCwd, sessionContext };
      if (current.current.route.page === 'chat' || userSessionNavigation.current) {
        const sameSession =
          current.current.route.page === 'chat' &&
          current.current.route.sessionId === sessionId;
        commit(
          sessionRoute(target),
          target,
          sameSession && !userSessionNavigation.current ? 'replace' : 'push',
        );
      } else {
        current.current = { ...current.current, target };
        setState(current.current);
      }
      userSessionNavigation.current = false;
      pendingSession.current = undefined;
      onSessionIdChange?.(
        sessionId,
        workspaceId,
        workspaceCwd,
        sessionContext,
      );
    },
    [commit, onSessionIdChange],
  );

  const controller = useMemo<NavigationController>(
    () => ({
      route: state.route,
      revision: state.revision,
      historyRevision: state.historyRevision,
      openPage: (page) => {
        userSessionNavigation.current = false;
        if (current.current.route.page === page) return;
        commit({ page }, current.current.target, 'push');
      },
      returnToChat: () => {
        userSessionNavigation.current = false;
        const target = lastChatTarget.current;
        pendingSession.current = { sessionId: target.sessionId };
        commit(sessionRoute(target), target, 'push');
      },
      reconcilePage: (page) => {
        if (userSessionNavigation.current) return;
        if (
          current.current.route.page === 'chat' ||
          (page ?? 'chat') === current.current.route.page
        )
          return;
        commit(
          page ? { page } : sessionRoute(current.current.target),
          current.current.target,
          'replace',
        );
      },
      cancelSessionNavigation: () => {
        userSessionNavigation.current = false;
        pendingSession.current = undefined;
      },
      finishNewChat: (sessionContext) => {
        if (!userSessionNavigation.current) return;
        userSessionNavigation.current = false;
        pendingSession.current = undefined;
        const target = {
          sessionId: undefined,
          workspaceId: undefined,
          workspaceCwd: undefined,
          sessionContext,
        };
        commit(sessionRoute(target), target, 'push');
      },
      beginSessionNavigation: (sessionId, workspaceId, sessionContext) => {
        userSessionNavigation.current = true;
        pendingSession.current = { sessionId };
        commit(
          sessionRoute({ sessionId, workspaceId, sessionContext }),
          current.current.target,
          'push',
        );
      },
    }),
    [commit, state.historyRevision, state.revision, state.route],
  );

  return (
    <NavigationContext.Provider value={controller}>
      {children(state.target, handleSessionChange)}
    </NavigationContext.Provider>
  );
}
