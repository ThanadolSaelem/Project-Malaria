import test from 'node:test';
import assert from 'node:assert/strict';
import {
  isForwardedHeader,
  isHopByHopHeader,
  isLoopbackAddress,
  loadGatewayConfig,
  observerRequestAllowed,
  requestParts,
  routeRequest,
  targetPath,
} from '../src/router.mjs';

test('namespaced APIs strip only their namespace and preserve raw query text', () => {
  const config = loadGatewayConfig({});
  const parts = requestParts('/artex-api/api/report?task=a%2Fb&download=1');
  const route = routeRequest({ ...parts, method: 'GET' }, config);
  assert.deepEqual(route, { kind: 'proxy', service: 'artex', nativePath: '/api/report' });
  assert.equal(targetPath(config.targets.artex, route.nativePath, parts.search), '/api/report?task=a%2Fb&download=1');
});

test('root /api is rejected instead of guessing ARTEX versus Qwen credentials', () => {
  const route = routeRequest({ path: '/api/chat/completions', method: 'POST', search: '' }, loadGatewayConfig({}));
  assert.equal(route.kind, 'ambiguous-api');
});

test('legacy Qwen document aliases are GET-only and do not turn POST writes into guesses', () => {
  const config = loadGatewayConfig({});
  assert.equal(routeRequest({ path: '/settings', method: 'GET', search: '' }, config).service, 'qwen');
  assert.equal(routeRequest({ path: '/session', method: 'POST', search: '' }, config).kind, 'ambiguous-qwen');
});

test('forwarded headers and connection tokens are explicit boundary inputs', () => {
  assert.equal(isForwardedHeader('X-Forwarded-For'), true);
  assert.equal(isForwardedHeader('Authorization'), false);
  assert.equal(isHopByHopHeader('x-hop', 'keep-alive, x-hop'), true);
  assert.equal(isHopByHopHeader('content-disposition', ''), false);
});

test('Observer is disabled by default and remains unavailable through Docker bridge peers', () => {
  const config = loadGatewayConfig({});
  const route = routeRequest({ path: '/observer-api/state', method: 'GET', search: '' }, config);
  assert.equal(route.kind, 'observer');
  assert.equal(route.enabled, false);
  assert.equal(observerRequestAllowed(config, '127.0.0.1'), false);
  assert.equal(observerRequestAllowed(config, '172.17.0.1'), false);
});

test('Observer can only be enabled when both listener and target are literal loopback', () => {
  const config = loadGatewayConfig({
    BIND: '127.0.0.1',
    OBSERVER_ENABLED: '1',
    OBSERVER_TARGET: 'http://127.0.0.1:8005',
  });
  assert.equal(observerRequestAllowed(config, '127.0.0.1'), true);
  assert.equal(observerRequestAllowed(config, '::ffff:127.0.0.1'), true);
  assert.equal(observerRequestAllowed(config, '192.168.1.10'), false);
});

test('Observer allows Docker bridge peers when OBSERVER_ALLOW_DOCKER_BRIDGE=1', () => {
  const config = loadGatewayConfig({
    OBSERVER_ENABLED: '1',
    OBSERVER_ALLOW_DOCKER_BRIDGE: '1',
    OBSERVER_TARGET: 'http://host.docker.internal:8005',
  });
  assert.equal(observerRequestAllowed(config, '127.0.0.1'), true);
  assert.equal(observerRequestAllowed(config, '172.18.0.1'), true);
  assert.equal(observerRequestAllowed(config, '192.168.1.10'), true);
  assert.equal(observerRequestAllowed(config, '8.8.8.8'), false);
});

test('loopback detection does not trust Host or X-Forwarded-For values', () => {
  assert.equal(isLoopbackAddress('127.0.0.1'), true);
  assert.equal(isLoopbackAddress('::ffff:127.0.0.1'), true);
  assert.equal(isLoopbackAddress('192.168.1.10'), false);
});

test('the embedded Map route stays in the unified document', () => {
  const config = loadGatewayConfig({});
  assert.deepEqual(
    routeRequest({ path: '/scopesentry/map', method: 'GET', search: '' }, config),
    { kind: 'proxy', service: 'frontend', nativePath: '/scopesentry/map' },
  );
});

test('native Map API, scripts and styles use the ScopeSentry namespace', () => {
  const config = loadGatewayConfig({});
  for (const nativePath of ['/map', '/js/map.js', '/css/map.css', '/api/asset']) {
    assert.deepEqual(
      routeRequest({ path: `/scopesentry-api${nativePath}`, method: 'GET', search: '' }, config),
      { kind: 'proxy', service: 'scopesentry', nativePath },
    );
  }
});
