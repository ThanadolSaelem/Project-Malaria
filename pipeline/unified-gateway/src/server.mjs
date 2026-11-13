/*
 * Project-Malaria unified gateway.
 *
 * Native Node HTTP primitives are used intentionally: request and response
 * bodies are connected with stream pipes, never accumulated in memory, and no
 * request is retried after it has been sent. The gateway owns only route
 * selection and transport; authentication, cookies, status envelopes, and
 * application policy remain with each upstream service.
 */

import { createServer } from 'node:http';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { isMainThread } from 'node:worker_threads';
import {
  FORWARDED_HEADER_NAMES,
  isForwardedHeader,
  isHopByHopHeader,
  isLoopbackAddress,
  loadGatewayConfig,
  observerRequestAllowed,
  requestParts,
  routeRequest,
  targetHost,
  targetHostname,
  targetPath,
} from './router.mjs';

const gatewayForwardedHeaders = new Set(FORWARDED_HEADER_NAMES);
const JSON_TYPE = 'application/json; charset=utf-8';

function remoteAddress(request) {
  return request.socket?.remoteAddress || '';
}

function safeStatusMessage(message) {
  return String(message || '').replace(/[\r\n]/gu, ' ');
}

function jsonError(response, status, code, message, extraHeaders = {}) {
  if (response.headersSent) {
    response.destroy();
    return;
  }
  const body = Buffer.from(JSON.stringify({ error: code, message }), 'utf8');
  response.writeHead(status, {
    'Content-Type': JSON_TYPE,
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  response.end(body);
}

function socketError(socket, status, code, message) {
  if (!socket || socket.destroyed) return;
  const body = JSON.stringify({ error: code, message });
  const reason = status === 400 ? 'Bad Request' : status === 404 ? 'Not Found' : status === 503 ? 'Service Unavailable' : 'Bad Gateway';
  socket.end(
    `HTTP/1.1 ${status} ${reason}\r\n` +
      'Connection: close\r\n' +
      'Content-Type: application/json; charset=utf-8\r\n' +
      `Content-Length: ${Buffer.byteLength(body)}\r\n` +
      'Cache-Control: no-store\r\n' +
      '\r\n' +
      body,
  );
}

function requestHeaders(request, target, { upgrade = false } = {}) {
  const connection = String(request.headers.connection || '');
  const headers = {};

  for (const [name, value] of Object.entries(request.headers)) {
    if (value === undefined) continue;
    const lower = name.toLowerCase();
    // Host is replaced with the fixed upstream authority. Forwarded headers
    // are never accepted from a browser or intermediary as identity evidence.
    if (lower === 'host' || gatewayForwardedHeaders.has(lower)) continue;
    if (isHopByHopHeader(lower, connection) &&
      !(upgrade && (lower === 'connection' || lower === 'upgrade'))) continue;
    headers[lower] = value;
  }

  headers.host = targetHost(target);
  // This is the gateway's direct TCP peer only. It intentionally does not
  // append or inspect X-Forwarded-For supplied by the client.
  headers['x-forwarded-for'] = remoteAddress(request);
  headers['x-forwarded-proto'] = request.socket?.encrypted ? 'https' : 'http';

  if (upgrade) {
    // `connection`, `upgrade`, and Sec-WebSocket-* headers are retained from
    // the client above so the upstream sees the original handshake contract.
    // `headers.host` remains the fixed upstream host, not the client Host.
  }
  return headers;
}

function responseHeaders(headers, connectionHeader = '') {
  const copied = {};
  for (const [name, value] of Object.entries(headers || {})) {
    if (value === undefined) continue;
    const lower = name.toLowerCase();
    if (isHopByHopHeader(lower, connectionHeader) || isForwardedHeader(lower)) continue;
    copied[lower] = value;
  }
  return copied;
}

function makeRequestOptions(target, request, nativePath, search, upgrade = false) {
  return {
    protocol: target.protocol,
    hostname: targetHostname(target),
    port: target.port || undefined,
    method: request.method,
    path: targetPath(target, nativePath, search),
    headers: requestHeaders(request, target, { upgrade }),
    agent: false,
    // Long-running ARTEX/Qwen work must not be shortened by a proxy timeout.
    timeout: 0,
  };
}

function transportFor(target) {
  return target.protocol === 'https:' ? httpsRequest : httpRequest;
}

function attachAbort(request, upstream) {
  const abort = () => {
    if (!upstream.destroyed) upstream.destroy();
  };
  request.once('aborted', abort);
  request.once('error', abort);
  return abort;
}

function pipeHttpRequest(request, response, route, config, search) {
  const target = config.targets[route.service];
  const options = makeRequestOptions(target, request, route.nativePath, search);
  const transport = transportFor(target);
  let responseStarted = false;

  const upstream = transport(options, (upstreamResponse) => {
    responseStarted = true;
    const headers = responseHeaders(
      upstreamResponse.headers,
      String(upstreamResponse.headers.connection || ''),
    );
    const statusCode = upstreamResponse.statusCode || 502;
    if (upstreamResponse.statusMessage) {
      response.writeHead(statusCode, safeStatusMessage(upstreamResponse.statusMessage), headers);
    } else {
      response.writeHead(statusCode, headers);
    }
    // Flush headers before the first byte so SSE and long responses are
    // observable immediately. The body itself remains a native pipe.
    if (typeof response.flushHeaders === 'function') response.flushHeaders();
    upstreamResponse.once('aborted', () => response.destroy());
    upstreamResponse.once('error', (error) => response.destroy(error));
    upstreamResponse.pipe(response);
  });

  upstream.setTimeout(0);
  response.once('close', () => {
    if (!response.writableFinished && !upstream.destroyed) upstream.destroy();
  });
  const detachAbort = attachAbort(request, upstream);
  upstream.once('close', () => request.removeListener('aborted', detachAbort));
  upstream.once('error', (error) => {
    if (responseStarted || response.headersSent) {
      response.destroy(error);
      return;
    }
    jsonError(response, 502, 'upstream_unavailable', `Unable to reach ${route.service} upstream`);
  });

  const expectsContinue = String(request.headers.expect || '').toLowerCase() === '100-continue';
  if (expectsContinue) {
    // The client may be waiting for 100 Continue. Ask the upstream first, then
    // relay the interim response and begin the request-body pipe exactly once.
    let bodyStarted = false;
    upstream.once('continue', () => {
      if (bodyStarted || request.destroyed) return;
      bodyStarted = true;
      if (!response.headersSent) response.writeContinue();
      request.pipe(upstream);
    });
    upstream.once('response', () => {
      // A final response (for example 417) wins without sending the body.
    });
    upstream.flushHeaders();
  } else {
    request.pipe(upstream);
  }
}

function writeRawUpgradeResponse(socket, response, bodyStream = response) {
  const status = response.statusCode || 502;
  const statusMessage = safeStatusMessage(response.statusMessage || '');
  const headerLines = [];
  for (let index = 0; index < response.rawHeaders.length; index += 2) {
    headerLines.push(`${response.rawHeaders[index]}: ${response.rawHeaders[index + 1]}`);
  }
  socket.write(
    `HTTP/${response.httpVersion} ${status} ${statusMessage}\r\n` +
      `${headerLines.join('\r\n')}\r\n\r\n`,
  );
  bodyStream.pipe(socket);
}

function pipeWebSocket(request, socket, head, route, config, search) {
  if (route.kind === 'observer') {
    socketError(socket, 503, 'observer_topology_unverified', 'Observer WebSocket access is disabled until a loopback-only host topology is configured');
    return;
  }
  if (route.kind !== 'proxy' || !config.targets[route.service]) {
    socketError(socket, 404, 'route_not_found', 'No WebSocket route is registered for this path');
    return;
  }

  const target = config.targets[route.service];
  const options = makeRequestOptions(target, request, route.nativePath, search, true);
  const transport = transportFor(target);
  let settled = false;
  const upstreamRequest = transport(options);
  upstreamRequest.setTimeout(0);

  const fail = () => {
    if (!settled) socketError(socket, 502, 'upstream_unavailable', `Unable to reach ${route.service} upstream`);
    else socket.destroy();
  };
  upstreamRequest.once('error', fail);
  socket.once('error', () => upstreamRequest.destroy());

  upstreamRequest.once('upgrade', (upstreamResponse, upstreamSocket, upstreamHead) => {
    settled = true;
    upstreamSocket.setTimeout(0);
    socket.write(
      `HTTP/${upstreamResponse.httpVersion} ${upstreamResponse.statusCode || 101} ${safeStatusMessage(upstreamResponse.statusMessage || '')}\r\n` +
        upstreamResponse.rawHeaders
          .reduce((lines, value, index, all) => {
            if (index % 2 === 0) lines.push(`${value}: ${all[index + 1]}`);
            return lines;
          }, [])
          .join('\r\n') +
        '\r\n\r\n',
    );
    if (upstreamResponse.statusCode === 101 && upstreamResponse.statusCode !== undefined) {
      if (upstreamHead?.length) socket.write(upstreamHead);
      if (head?.length) upstreamSocket.write(head);
      socket.pipe(upstreamSocket).pipe(socket);
      upstreamSocket.once('error', () => socket.destroy());
      socket.once('close', () => upstreamSocket.destroy());
    } else {
      upstreamSocket.pipe(socket);
    }
  });

  // A server can reject an upgrade with a normal HTTP response. Preserve that
  // response status and raw headers rather than converting it to JSON.
  upstreamRequest.once('response', (upstreamResponse) => {
    if (settled) return;
    settled = true;
    writeRawUpgradeResponse(socket, upstreamResponse);
  });

  // There is normally no request body on a WebSocket upgrade. `head` contains
  // any bytes Node read beyond the HTTP headers and is written only after the
  // upstream handshake succeeds, without inspecting or buffering frame data.
  upstreamRequest.end();
}

function handleHttpRequest(request, response, config) {
  const { path, search } = requestParts(request.url);
  const route = routeRequest({ path, method: request.method || 'GET', search }, config);

  if (path === '/healthz') {
    const body = Buffer.from(JSON.stringify({ ok: true, service: 'unified-gateway' }), 'utf8');
    response.writeHead(200, {
      'Content-Type': JSON_TYPE,
      'Content-Length': body.length,
      'Cache-Control': 'no-store',
    });
    response.end(body);
    return;
  }

  if (route.kind === 'ambiguous-api') {
    jsonError(response, 400, 'ambiguous_api_path', route.message);
    return;
  }

  if (route.kind === 'ambiguous-qwen') {
    jsonError(response, 400, 'ambiguous_qwen_path', route.message);
    return;
  }

  if (route.kind === 'observer') {
    if (!observerRequestAllowed(config, remoteAddress(request))) {
      jsonError(
        response,
        503,
        'observer_topology_unverified',
        'Observer is pending: the unauthenticated host service is only reachable through a loopback-only gateway topology',
        { 'X-Gateway-Feature': 'observer-pending' },
      );
      return;
    }
  }

  if (route.kind !== 'proxy' && route.kind !== 'observer') {
    jsonError(response, 404, 'route_not_found', 'No route is registered for this path');
    return;
  }

  pipeHttpRequest(request, response, route, config, search);
}

export function createGateway(options = {}) {
  const config = options.config || loadGatewayConfig(options.env || process.env);
  const server = createServer(
    {
      // Disable Node's finite request timeout so upstream long waits and SSE
      // streams retain their native lifetime. This is not a retry policy.
      requestTimeout: 0,
      headersTimeout: 0,
      keepAliveTimeout: 5_000,
    },
    (request, response) => handleHttpRequest(request, response, config),
  );

  server.on('checkContinue', (request, response) => handleHttpRequest(request, response, config));
  server.on('upgrade', (request, socket, head) => {
    const { path, search } = requestParts(request.url);
    const route = routeRequest({ path, method: request.method || 'GET', search }, config);
    if (route.kind === 'observer' && !observerRequestAllowed(config, remoteAddress(request))) {
      socketError(socket, 503, 'observer_topology_unverified', 'Observer WebSocket access is disabled until a loopback-only host topology is configured');
      return;
    }
    if (route.kind === 'ambiguous-api') {
      socketError(socket, 400, 'ambiguous_api_path', route.message);
      return;
    }
    if (route.kind === 'ambiguous-qwen') {
      socketError(socket, 400, 'ambiguous_qwen_path', route.message);
      return;
    }
    pipeWebSocket(request, socket, head, route, config, search);
  });
  server.on('clientError', (_error, socket) => {
    if (!socket.destroyed) socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n');
  });
  return { server, config };
}

export { handleHttpRequest, requestHeaders, responseHeaders, pipeHttpRequest, pipeWebSocket, isLoopbackAddress };

if (isMainThread && import.meta.url === `file://${process.argv[1]}`) {
  const { server, config } = createGateway();
  server.listen(config.port, config.bind, () => {
    console.error(`[unified-gateway] listening on ${config.bind}:${config.port}`);
    console.error('[unified-gateway] targets fixed at startup; Observer remains fail-closed unless loopback-only topology is proven');
  });
}
