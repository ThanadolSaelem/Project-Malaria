import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request as httpRequest } from 'node:http';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createGateway } from '../src/server.mjs';
import { loadGatewayConfig } from '../src/router.mjs';

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return `http://127.0.0.1:${server.address().port}`;
}

function trackSockets(server) {
  const sockets = new Set();
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });
  return () => {
    for (const socket of sockets) socket.destroy();
  };
}

async function fixture(t, handler, onUpgrade) {
  const upstream = createServer(handler);
  if (onUpgrade) upstream.on('upgrade', onUpgrade);
  const closeUpstreamSockets = trackSockets(upstream);
  const upstreamOrigin = await listen(upstream);
  const config = loadGatewayConfig({
    BIND: '127.0.0.1',
    FRONTEND_TARGET: upstreamOrigin,
    QWEN_TARGET: upstreamOrigin,
    ARTEX_TARGET: upstreamOrigin,
    SCOPESENTRY_TARGET: upstreamOrigin,
    OBSERVER_ENABLED: '0',
  });
  const { server: gateway } = createGateway({ config });
  const closeGatewaySockets = trackSockets(gateway);
  const origin = await listen(gateway);
  t.after(async () => {
    closeGatewaySockets();
    closeUpstreamSockets();
    await Promise.all([
      new Promise((resolve) => gateway.close(resolve)),
      new Promise((resolve) => upstream.close(resolve)),
    ]);
  });
  return { origin, upstream };
}

function call(url, options = {}, body) {
  return new Promise((resolve, reject) => {
    const request = httpRequest(url, options, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.once('error', reject);
      response.once('end', () => resolve({
        status: response.statusCode,
        headers: response.headers,
        body: Buffer.concat(chunks),
      }));
    });
    request.once('error', reject);
    request.end(body);
  });
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

test('multipart, query, auth, binary range and download headers are preserved', { timeout: 5_000 }, async (t) => {
  const upload = Buffer.from('--mock-boundary\r\nContent-Disposition: form-data; name="file"; filename="mock.bin"\r\n\r\nmock-data\r\n--mock-boundary--\r\n');
  const binary = Buffer.from([0, 255, 42, 128]);
  const { origin } = await fixture(t, async (request, response) => {
    assert.equal(request.method, 'POST');
    assert.equal(request.url, '/api/upload?task=a%2Fb&name=x%20y');
    assert.equal(request.headers.authorization, 'Bearer artex-mock-token');
    assert.equal(request.headers.range, 'bytes=0-3');
    assert.equal(request.headers['content-type'], 'multipart/form-data; boundary=mock-boundary');
    assert.equal(request.headers['x-forwarded-for'], '127.0.0.1');
    assert.equal(request.headers['x-forwarded-host'], undefined);
    assert.equal(request.headers['proxy-authorization'], undefined);
    assert.deepEqual(await readBody(request), upload);
    response.writeHead(206, {
      'Content-Type': 'application/octet-stream',
      'Content-Length': binary.length,
      'Content-Range': 'bytes 0-3/4',
      'Content-Disposition': 'attachment; filename="mock.bin"',
      'Set-Cookie': ['artex_mock=1; Path=/; SameSite=Lax'],
    });
    response.end(binary);
  });
  const result = await call(`${origin}/artex-api/api/upload?task=a%2Fb&name=x%20y`, {
    method: 'POST',
    headers: {
      Authorization: 'Bearer artex-mock-token',
      Range: 'bytes=0-3',
      'Content-Type': 'multipart/form-data; boundary=mock-boundary',
      'Content-Length': upload.length,
      'X-Forwarded-For': '203.0.113.1',
      'X-Forwarded-Host': 'attacker.invalid',
      'Proxy-Authorization': 'Basic mock-proxy-secret',
    },
  }, upload);
  assert.equal(result.status, 206);
  assert.deepEqual(result.body, binary);
  assert.equal(result.headers['content-range'], 'bytes 0-3/4');
  assert.equal(result.headers['content-disposition'], 'attachment; filename="mock.bin"');
  assert.deepEqual(result.headers['set-cookie'], ['artex_mock=1; Path=/; SameSite=Lax']);
});

test('SSE headers and the first event arrive before upstream completion', { timeout: 5_000 }, async (t) => {
  let upstreamCompleted = false;
  const { origin } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    response.flushHeaders();
    response.write('event: update\ndata: first\n\n');
    const timer = setTimeout(() => {
      upstreamCompleted = true;
      response.end('data: second\n\n');
    }, 100);
    response.once('close', () => clearTimeout(timer));
  });
  await new Promise((resolve, reject) => {
    const request = httpRequest(`${origin}/qwen-api/events`, (response) => {
      assert.equal(response.headers['content-type'], 'text/event-stream');
      let first = true;
      let body = '';
      response.on('data', (chunk) => {
        if (first) {
          first = false;
          assert.equal(upstreamCompleted, false);
        }
        body += chunk.toString();
      });
      response.once('error', reject);
      response.once('end', () => {
        assert.ok(body.includes('data: first'));
        assert.ok(body.includes('data: second'));
        resolve();
      });
    });
    request.once('error', reject);
    request.end();
  });
});

test('disconnecting a downstream SSE client closes its upstream stream', { timeout: 5_000 }, async (t) => {
  let markClosed;
  const closed = new Promise((resolve) => { markClosed = resolve; });
  const { origin } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    response.write('data: ready\n\n');
    response.once('close', () => markClosed());
  });
  const request = httpRequest(`${origin}/qwen-api/events`, (response) => {
    response.once('data', () => request.destroy());
  });
  request.on('error', () => {});
  request.end();
  await closed;
});

test('Expect 100-continue does not deadlock or duplicate the upload body', { timeout: 5_000 }, async (t) => {
  const upload = Buffer.from('mock-upload');
  let received;
  const { origin } = await fixture(t, async (request, response) => {
    received = await readBody(request);
    response.end('accepted');
  });
  const result = await new Promise((resolve, reject) => {
    const request = httpRequest(`${origin}/artex-api/api/upload`, {
      method: 'POST',
      headers: { Expect: '100-continue', 'Content-Length': upload.length },
    }, (response) => {
      response.resume();
      response.once('end', () => resolve(response.statusCode));
    });
    request.once('error', reject);
    request.once('continue', () => request.end(upload));
    request.flushHeaders();
  });
  assert.equal(result, 200);
  assert.deepEqual(received, upload);
});

test('failed upstream writes are not automatically retried', { timeout: 5_000 }, async (t) => {
  let writes = 0;
  const { origin } = await fixture(t, async (request) => {
    writes += 1;
    await readBody(request);
    request.socket.destroy();
  });
  const result = await call(`${origin}/artex-api/api/task`, { method: 'POST' }, 'mock-write');
  assert.equal(result.status, 502);
  assert.equal(JSON.parse(result.body.toString()).error, 'upstream_unavailable');
  assert.equal(writes, 1);
});

test('WebSocket preserves native credential subprotocols, raw query and upgrade head', { timeout: 5_000 }, async (t) => {
  const greeting = Buffer.from('mock-stream');
  const { origin } = await fixture(t, (_request, response) => response.end(), (request, socket) => {
    assert.equal(request.url, '/acp?workspace=mock%2Fworkspace');
    assert.equal(request.headers['sec-websocket-protocol'], 'qwen-ws, qwen-bearer.bW9jaw');
    const accept = createHash('sha1')
      .update(`${request.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest('base64');
    socket.write('HTTP/1.1 101 Switching Protocols\r\n' +
      'Upgrade: websocket\r\nConnection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${accept}\r\nSec-WebSocket-Protocol: qwen-ws\r\n\r\n`);
    socket.write(Buffer.concat([Buffer.from([0x81, greeting.length]), greeting]));
  });
  await new Promise((resolve, reject) => {
    const client = new WebSocket(
      `${origin.replace('http:', 'ws:')}/qwen-api/acp?workspace=mock%2Fworkspace`,
      ['qwen-ws', 'qwen-bearer.bW9jaw'],
    );
    client.addEventListener('error', reject, { once: true });
    client.addEventListener('message', (event) => {
      assert.equal(event.data, greeting.toString());
      assert.equal(client.protocol, 'qwen-ws');
      client.close();
      resolve();
    }, { once: true });
  });
});
