/**
 * @license
 * Copyright 2026 Qwen Team
 * SPDX-License-Identifier: Apache-2.0
 */

export const WEB_SHELL_PAGES = [
  'plugins',
  'channels',
  'channel-events',
  'live',
  'scheduled-tasks',
  'pr-watches',
  'goals',
  'workflows',
  'cockpit',
  'split',
  'settings',
] as const;
export type WebShellPage = (typeof WEB_SHELL_PAGES)[number];
export interface SessionUrlTarget {
  sessionId?: string;
  workspaceId?: string;
  context?: 'standalone' | 'live';
}
export type WebShellRoute =
  | { page: WebShellPage; splitSessionIds?: string[] }
  | ({ page: 'chat' } & SessionUrlTarget);

export function normalizeNavigationBasePath(basePath = ''): string {
  const base = basePath.replace(/\/+$/, '');
  if (base && (!base.startsWith('/') || /[?#]/.test(base))) {
    throw new Error('Web Shell basePath must be an absolute URL pathname');
  }
  return base;
}

export function isWebShellPage(value: string): value is WebShellPage {
  return WEB_SHELL_PAGES.some((page) => page === value);
}

export function readNavigationUrl(
  url: URL,
  basePath = '',
): WebShellRoute | undefined {
  const base = normalizeNavigationBasePath(basePath);
  if (url.pathname !== base && !url.pathname.startsWith(`${base}/`)) {
    return undefined;
  }
  const path = url.pathname.slice(base.length).replace(/\/$/, '');
  const context = url.searchParams.get('context');
  const workspaceId = url.searchParams.get('workspace') || undefined;
  const scope: SessionUrlTarget =
    context === 'standalone' || context === 'live'
      ? { context }
      : workspaceId
        ? { workspaceId }
        : {};
  const splitSessionIds = (url.searchParams.get('split') ?? '')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean);
  if (!path) {
    if (url.searchParams.get('view') === 'cockpit') return { page: 'cockpit' };
    if (splitSessionIds.length > 0) {
      return { page: 'split', splitSessionIds };
    }
    return { page: 'chat', ...scope };
  }
  if (isWebShellPage(path.slice(1))) {
    return {
      page: path.slice(1) as WebShellPage,
      ...(path.slice(1) === 'split' && splitSessionIds.length > 0
        ? { splitSessionIds }
        : {}),
    };
  }
  const match = path.match(/^\/session\/([^/]+)$/);
  if (!match) return undefined;
  let sessionId: string;
  try {
    sessionId = decodeURIComponent(match[1]);
  } catch {
    return undefined;
  }
  return { page: 'chat', sessionId, ...scope };
}

export function buildNavigationUrl(
  current: URL,
  route: WebShellRoute,
  basePath = '',
): URL {
  const url = new URL(current);
  const base = normalizeNavigationBasePath(basePath);
  url.pathname =
    route.page !== 'chat'
      ? `${base}/${route.page}`
      : route.sessionId
        ? `${base}/session/${encodeURIComponent(route.sessionId)}`
        : base || '/';
  url.searchParams.delete('workspace');
  url.searchParams.delete('context');
  url.searchParams.delete('split');
  url.searchParams.delete('view');
  if (route.page === 'chat' && route.sessionId) {
    if (route.context) url.searchParams.set('context', route.context);
    else if (route.workspaceId) {
      url.searchParams.set('workspace', route.workspaceId);
    }
  }
  if (route.page === 'split' && route.splitSessionIds?.length) {
    url.searchParams.set('split', route.splitSessionIds.join(','));
  }
  if (route.page === 'cockpit') {
    url.searchParams.set('view', 'cockpit');
  }
  return url;
}
