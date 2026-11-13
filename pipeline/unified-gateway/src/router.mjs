/*
 * Project-Malaria unified gateway route table.
 *
 * This module is deliberately dependency-free and side-effect-free. It maps
 * request paths to a finite set of startup-configured services; it never
 * accepts a target URL from the request.
 */

import net from 'node:net';

export const DEFAULTS = Object.freeze({
  port: 3000,
  bind: '0.0.0.0',
  frontendTarget: 'http://unified-web:3000',
  qwenTarget: 'http://qwen-code:3080',
  artexTarget: 'http://artex:8787',
  scopesentryTarget: 'http://scope-sentry:8082',
  // The native Observer listens on the host loopback. A normal Docker bridge
  // cannot prove that a browser client is local to that host, so this target
  // stays disabled unless a later, explicitly approved host-network topology
  // supplies a loopback-only path.
  observerTarget: 'http://127.0.0.1:8005',
  observerEnabled: false,
});

const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on']);
const FALSE_VALUES = new Set(['0', 'false', 'no', 'off', '']);

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

export const FORWARDED_HEADER_NAMES = Object.freeze([
  'forwarded',
  'via',
  'x-forwarded-for',
  'x-forwarded-host',
  'x-forwarded-port',
  'x-forwarded-proto',
  'x-real-ip',
]);

const FORWARDED_HEADERS = new Set(FORWARDED_HEADER_NAMES);

const QWEN_DOCUMENT_PAGES = Object.freeze([
  '/settings',
  '/plugins',
  '/channels',
  '/channel-events',
  '/live',
  '/scheduled-tasks',
  '/pr-watches',
  '/goals',
]);

const QWEN_DOCUMENT_PREFIXES = Object.freeze([
  '/session/',
  '/standalone/',
]);

function envValue(env, name, fallback) {
  const value = env[name];
  return value === undefined || value === '' ? fallback : value;
}

function parseBoolean(value, fallback) {
  if (value === undefined) return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (TRUE_VALUES.has(normalized)) return true;
  if (FALSE_VALUES.has(normalized)) return false;
  throw new Error(`Invalid boolean environment value: ${value}`);
}

function parsePort(value, name) {
  const port = Number.parseInt(String(value), 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535`);
  }
  return port;
}

export function parseTarget(value, name) {
  let target;
  try {
    target = new URL(value);
  } catch (error) {
    throw new Error(`${name} must be an absolute http(s) URL: ${error.message}`);
  }
  if (target.protocol !== 'http:' && target.protocol !== 'https:') {
    throw new Error(`${name} must use http:// or https://`);
  }
  if (target.username || target.password || target.search || target.hash) {
    throw new Error(`${name} must not contain credentials, query, or fragment`);
  }
  if (!target.hostname) throw new Error(`${name} must include a hostname`);
  return target;
}

export function loadGatewayConfig(env = process.env) {
  const observerEnabled = parseBoolean(
    env.OBSERVER_ENABLED,
    DEFAULTS.observerEnabled,
  );
  const observerAllowBridge = parseBoolean(
    env.OBSERVER_ALLOW_DOCKER_BRIDGE,
    false,
  );
  const targets = {
    frontend: parseTarget(
      envValue(env, 'FRONTEND_TARGET', DEFAULTS.frontendTarget),
      'FRONTEND_TARGET',
    ),
    qwen: parseTarget(
      envValue(env, 'QWEN_TARGET', DEFAULTS.qwenTarget),
      'QWEN_TARGET',
    ),
    artex: parseTarget(
      envValue(env, 'ARTEX_TARGET', DEFAULTS.artexTarget),
      'ARTEX_TARGET',
    ),
    scopesentry: parseTarget(
      envValue(env, 'SCOPESENTRY_TARGET', DEFAULTS.scopesentryTarget),
      'SCOPESENTRY_TARGET',
    ),
    observer: parseTarget(
      envValue(env, 'OBSERVER_TARGET', DEFAULTS.observerTarget),
      'OBSERVER_TARGET',
    ),
  };

  return Object.freeze({
    port: parsePort(envValue(env, 'PORT', DEFAULTS.port), 'PORT'),
    bind: envValue(env, 'BIND', DEFAULTS.bind),
    targets: Object.freeze(targets),
    observer: Object.freeze({
      enabled: observerEnabled,
      allowDockerBridge: observerAllowBridge,
      targetIsLiteralLoopback: isLiteralLoopbackHostname(targets.observer.hostname),
      targetIsHostOrLoopback: isHostOrLoopbackHostname(targets.observer.hostname),
      listenerIsLiteralLoopback: isLiteralLoopbackHostname(envValue(env, 'BIND', DEFAULTS.bind)),
    }),
  });
}

function splitRawUrl(rawUrl) {
  const raw = rawUrl || '/';
  const queryStart = raw.indexOf('?');
  if (queryStart === -1) return { path: raw || '/', search: '' };
  return {
    path: raw.slice(0, queryStart) || '/',
    search: raw.slice(queryStart),
  };
}

export function requestParts(rawUrl) {
  return splitRawUrl(rawUrl);
}

function stripPrefix(path, prefix) {
  if (path === prefix) return '/';
  if (path.startsWith(`${prefix}/`)) return path.slice(prefix.length) || '/';
  return null;
}

function namespaced(path, prefix, service) {
  const nativePath = stripPrefix(path, prefix);
  return nativePath === null
    ? null
    : { kind: 'proxy', service, nativePath };
}

function isQwenDocumentPath(path) {
  return (
    QWEN_DOCUMENT_PAGES.includes(path) ||
    QWEN_DOCUMENT_PREFIXES.some((prefix) => path.startsWith(prefix))
  );
}

function isQwenWritePath(path) {
  return [
    '/session',
    '/sessions',
    '/standalone',
    '/workspace',
    '/workspaces',
    '/file',
    '/upload',
    '/permission',
    '/mcp',
    '/live',
    '/goals',
    '/extensions',
    '/channels',
    '/auth',
    '/web-shell',
    '/language',
    '/memory',
    '/remote-access',
  ].some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

function hasQueryParameter(search, parameter) {
  if (!search) return false;
  try {
    return new URLSearchParams(search.slice(1)).has(parameter);
  } catch {
    return false;
  }
}

function legacyQwen(path, method, search) {
  const nativePath = stripPrefix(path, '/qwen') ?? stripPrefix(path, '/qwen-code');
  if (nativePath !== null) {
    return { kind: 'proxy', service: 'qwen', nativePath, compatibility: 'qwen-prefix' };
  }

  // The old standalone daemon served its document at /. Preserve that exact
  // entry only when the old token-bearing URL is recognizable. A query string
  // is forwarded byte-for-byte; its value is never logged or copied elsewhere.
  if (path === '/' && hasQueryParameter(search, 'token') && (method === 'GET' || method === 'HEAD')) {
    return { kind: 'proxy', service: 'qwen', nativePath: '/', compatibility: 'qwen-root' };
  }

  // Qwen's static shell uses root /assets, /manifest.webmanifest, and /sw.js.
  // These paths have no counterpart in the current unified host, so retain
  // them for old root deployments without treating generic /api as Qwen.
  if (
    (path.startsWith('/assets/') ||
      path === '/manifest.webmanifest' ||
      path === '/sw.js') &&
    (method === 'GET' || method === 'HEAD')
  ) {
    return { kind: 'proxy', service: 'qwen', nativePath: path, compatibility: 'qwen-static' };
  }

  if ((method === 'GET' || method === 'HEAD') && isQwenDocumentPath(path)) {
    return { kind: 'proxy', service: 'qwen', nativePath: path, compatibility: 'qwen-document' };
  }

  if (method !== 'GET' && method !== 'HEAD' && isQwenWritePath(path)) {
    return {
      kind: 'ambiguous-qwen',
      message: 'The legacy non-namespaced Qwen write path is intentionally not routed. Use /qwen-api/<native-path> explicitly.',
    };
  }

  return null;
}

function legacyModuleApi(path, modulePrefix, service) {
  const nativePath = stripPrefix(path, modulePrefix);
  if (nativePath === null) return null;
  const firstSegment = nativePath.split('/')[1] || '';
  if (
    firstSegment === 'api' ||
    firstSegment === 'images' ||
    firstSegment === 'map' ||
    firstSegment === 'mcp' ||
    firstSegment === 'Swagger' ||
    firstSegment === 'static'
  ) {
    return {
      kind: 'proxy',
      service,
      nativePath,
      compatibility: `${service}-module-root-path`,
    };
  }
  return null;
}

export function routeRequest({ path, method = 'GET', search = '' }, config) {
  const qwenApi = namespaced(path, '/qwen-api', 'qwen');
  if (qwenApi) return qwenApi;

  const artexApi = namespaced(path, '/artex-api', 'artex');
  if (artexApi) return artexApi;

  const scopesentryApi = namespaced(path, '/scopesentry-api', 'scopesentry');
  if (scopesentryApi) return scopesentryApi;

  if (path === '/observer-api/state') {
    return {
      kind: 'observer',
      service: 'observer',
      nativePath: '/state',
      enabled: config?.observer?.enabled === true,
    };
  }

  // A module-local API alias is unambiguous and helps legacy embedded Vue/ARTEX
  // code migrate without making the root /api path choose a credential domain.
  // Map itself is a full native application mounted through the Vue route in
  // the unified document. Only /scopesentry-api/map serves its legacy document.
  const scopesentryModuleApi = path === '/scopesentry/map' || path.startsWith('/scopesentry/map/')
    ? null
    : legacyModuleApi(path, '/scopesentry', 'scopesentry');
  if (scopesentryModuleApi) return scopesentryModuleApi;
  const artexModuleApi = legacyModuleApi(path, '/artex', 'artex');
  if (artexModuleApi) return artexModuleApi;

  const oldQwen = legacyQwen(path, method, search);
  if (oldQwen) return oldQwen;

  if (path === '/api' || path.startsWith('/api/')) {
    return {
      kind: 'ambiguous-api',
      message:
        'The legacy /api path is intentionally not routed. Use /artex-api/<native-path> or /qwen-api/<native-path> explicitly.',
    };
  }

  if (
    path === '/' ||
    path === '/ai' ||
    path.startsWith('/ai/') ||
    path === '/artex' ||
    path.startsWith('/artex/') ||
    path === '/scopesentry' ||
    path.startsWith('/scopesentry/') ||
    path === '/observer' ||
    path.startsWith('/observer/') ||
    path.startsWith('/_next/') ||
    path === '/_next' ||
    path.startsWith('/_modules/scopesentry/') ||
    path === '/_modules/scopesentry' ||
    path === '/favicon.ico' ||
    path.startsWith('/dashboard') ||
    path.startsWith('/chat') ||
    path.startsWith('/function/') ||
    path.startsWith('/system/') ||
    path === '/login' ||
    path.startsWith('/login/') ||
    path === '/setup' ||
    path.startsWith('/setup/')
  ) {
    return { kind: 'proxy', service: 'frontend', nativePath: path };
  }

  // Preserve frontend deep links by default. The explicit Qwen document list
  // above is evaluated first, so a root Qwen refresh does not get mistaken for
  // an ARTEX or ScopeSentry route. No unknown request can select a backend.
  return { kind: 'proxy', service: 'frontend', nativePath: path };
}

export function isHopByHopHeader(name, connectionHeader = '') {
  const lower = name.toLowerCase();
  if (HOP_BY_HOP_HEADERS.has(lower)) return true;
  return connectionHeader
    .split(',')
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean)
    .includes(lower);
}

export function isForwardedHeader(name) {
  return FORWARDED_HEADERS.has(name.toLowerCase());
}

export function isLiteralLoopbackHostname(hostname) {
  const host = String(hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
  if (host === '127.0.0.1' || host === '::1' || host === 'localhost') return true;
  return false;
}

export function isHostOrLoopbackHostname(hostname) {
  const host = String(hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
  return isLiteralLoopbackHostname(host) || host === 'host.docker.internal';
}

export function isLoopbackAddress(address) {
  const normalized = String(address || '').replace(/^::ffff:/i, '').toLowerCase();
  return normalized === '127.0.0.1' || normalized === '::1';
}

export function isPrivateOrDockerAddress(address) {
  const normalized = String(address || '').replace(/^::ffff:/i, '').toLowerCase();
  if (isLoopbackAddress(normalized)) return true;
  const parts = normalized.split('.').map((p) => Number.parseInt(p, 10));
  if (parts.length === 4 && parts.every((p) => !Number.isNaN(p) && p >= 0 && p <= 255)) {
    if (parts[0] === 10) return true;
    if (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) return true;
    if (parts[0] === 192 && parts[1] === 168) return true;
  }
  if (normalized.startsWith('fc') || normalized.startsWith('fd') || normalized.startsWith('fe80')) return true;
  return false;
}

export function observerRequestAllowed(config, remoteAddress) {
  if (config?.observer?.enabled !== true) return false;

  if (config.observer.allowDockerBridge === true) {
    const validTarget = config.observer.targetIsLiteralLoopback || config.observer.targetIsHostOrLoopback;
    return validTarget && (isLoopbackAddress(remoteAddress) || isPrivateOrDockerAddress(remoteAddress));
  }

  return (
    config.observer.targetIsLiteralLoopback === true &&
    config.observer.listenerIsLiteralLoopback === true &&
    isLoopbackAddress(remoteAddress)
  );
}

export function targetPath(target, nativePath, search = '') {
  const basePath = target.pathname === '/' ? '' : target.pathname.replace(/\/+$/u, '');
  const path = nativePath.startsWith('/') ? nativePath : `/${nativePath}`;
  return `${basePath}${path}${search}`;
}

export function targetHost(target) {
  return target.host;
}

export function targetHostname(target) {
  return target.hostname.replace(/^\[|\]$/g, '');
}

export function isIpLiteral(hostname) {
  return net.isIP(String(hostname).replace(/^\[|\]$/g, '')) !== 0;
}
