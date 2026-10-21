'use strict';
const {test, beforeEach, afterEach} = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {Readable} = require('node:stream');
const handler = require('../api/fetch');
const health = require('../api/health');
const LIST = 'https://www.kfcc.co.kr/mgNotice/mgNoticeList.do?schType=subject&schValue=PEF&pageNo=1';
const DETAIL = 'https://www.kfcc.co.kr/mgNotice/mgNoticeDetail.do?no=12345';
const FILE = 'https://www.kfcc.co.kr/upload/neoboard/A01/2026_%EA%B3%B5%EA%B3%A0%EB%AC%B8.pdf';
let originalFetch, originalEnv, calls;
beforeEach(() => {
  originalFetch = global.fetch;
  originalEnv = {...process.env};
  process.env.LP_SOURCE_WORKER_TOKEN = 'test-only-not-a-real-secret';
  process.env.VERCEL_REGION = 'icn1';
  process.env.SERVICE_RELEASE = 'test-release';
  calls = [];
  global.fetch = async (...args) => { calls.push(args); return new Response('official bytes'); };
});
afterEach(() => { global.fetch = originalFetch; process.env = originalEnv; });
function response() {
  return {headers: {}, setHeader(key, value) { this.headers[key] = value; }, end(body) { this.body = body; }};
}
async function invoke(body = {url: LIST}, options = {}) {
  const req = {method: 'POST', headers: {authorization: `Bearer ${process.env.LP_SOURCE_WORKER_TOKEN}`}, body, ...options};
  const res = response();
  await handler(req, res);
  return res;
}

test('missing, empty, incorrect and malformed authentication never reaches network', async () => {
  for (const headers of [{}, {authorization: ''}, {authorization: 'Bearer '}, {authorization: 'Bearer wrong'}, {authorization: ['Bearer wrong']}]) {
    assert.equal((await invoke({url: LIST}, {headers})).statusCode, 401);
  }
  delete process.env.LP_SOURCE_WORKER_TOKEN;
  assert.equal((await invoke({url: LIST})).statusCode, 401);
  assert.equal(calls.length, 0);
});

test('only authenticated POST is accepted', async () => {
  for (const method of ['GET', 'PUT', 'DELETE']) {
    const res = await invoke({url: LIST}, {method});
    assert.equal(res.statusCode, 405);
    assert.equal(res.headers.Allow, 'POST');
  }
  assert.equal(calls.length, 0);
});

test('listing, detail and PDF preserve binary bytes and verified hash', async () => {
  const bytes = Buffer.from([0x25, 0x50, 0x44, 0x46, 0, 255, 128, 10]);
  global.fetch = async (...args) => { calls.push(args); return new Response(bytes); };
  for (const url of [LIST, DETAIL, FILE]) {
    const res = await invoke({url, referer: LIST});
    assert.equal(res.statusCode, 200);
    assert.deepEqual(res.body, bytes);
    assert.equal(res.headers['Content-Type'], 'application/octet-stream');
    assert.equal(res.headers['Cache-Control'], 'no-store');
    assert.equal(res.headers['X-LP-Source-Region'], 'icn1');
    assert.equal(res.headers['X-LP-Upstream-SHA256'], crypto.createHash('sha256').update(bytes).digest('hex'));
  }
  assert.equal(calls.length, 3);
  assert.equal(calls[0][1].redirect, 'error');
  assert.equal(calls[0][1].headers.Referer, LIST);
  assert.equal(calls[0][1].signal.aborted, false);
});

test('foreign, private, HTTP, credential, port and fragment URLs are denied', async () => {
  for (const url of ['http://www.kfcc.co.kr/mgNotice/mgNoticeDetail.do?no=1',
    'https://127.0.0.1/mgNotice/mgNoticeDetail.do?no=1', 'https://www.kfcc.co.kr.evil.example/a',
    'https://user:pass@www.kfcc.co.kr/mgNotice/mgNoticeDetail.do?no=1',
    'https://www.kfcc.co.kr:444/mgNotice/mgNoticeDetail.do?no=1', `${DETAIL}#section`,
    'https://www.kfcc.co.kr./mgNotice/mgNoticeDetail.do?no=1', 'https://www.kfcc.co.kr\\@evil.example/a']) {
    assert.equal((await invoke({url})).statusCode, 400, url);
  }
  assert.equal(calls.length, 0);
});

test('unobserved routes, dot segments and encoded or double-encoded traversal are denied', async () => {
  for (const path of ['/admin', '/mgNotice/../mgNotice/mgNoticeDetail.do?no=1',
    '/upload/neoboard/A01/../secret.pdf', '/upload/neoboard/A01/%2e%2e%2fsecret.pdf',
    '/upload/neoboard/A01/%252e%252e%252fsecret.pdf', '/upload/neoboard/A01/a%2fb.pdf',
    '/upload/neoboard/A01/a%255cb.pdf', '/upload/neoboard/A02/file.pdf',
    '/upload/neoboard/A01/.hidden', '/upload/neoboard/A01/%zz.pdf']) {
    assert.equal((await invoke({url: `https://www.kfcc.co.kr${path}`})).statusCode, 400, path);
  }
  assert.equal(calls.length, 0);
});

test('strict query keys, unique keys, numeric IDs and bounded search text', async () => {
  for (const url of [DETAIL + '&extra=1', DETAIL + '&no=2', DETAIL.replace('12345', '-1'),
    DETAIL.replace('12345', '1x'), LIST.replace('subject', 'body'), LIST.replace('PEF', ''),
    LIST.replace('PEF', 'x'.repeat(51)), LIST.replace('pageNo=1', 'pageNo=a'),
    LIST + '&redirect=https://evil.example', FILE + '?download=1']) {
    assert.equal((await invoke({url})).statusCode, 400, url);
  }
  assert.equal(calls.length, 0);
});

test('referer is restricted to official MG routes and never forwarded otherwise', async () => {
  for (const referer of ['https://evil.example/', FILE, 'http://www.kfcc.co.kr/mgNotice/mgNoticeList.do', null]) {
    assert.equal((await invoke({url: DETAIL, referer})).statusCode, 400);
  }
  assert.equal(calls.length, 0);
  assert.equal((await invoke({url: DETAIL, referer: 'https://www.kfcc.co.kr/mgNotice/mgNoticeList.do'})).statusCode, 200);
});

test('malformed JSON, unknown body keys, arrays and missing URL are rejected', async () => {
  for (const body of ['{', '', 'null', '[]', {}, [], null, {url: LIST, token: 'x'}, {url: 1}]) {
    assert.equal((await invoke(body)).statusCode, 400);
  }
  assert.equal(calls.length, 0);
});

test('Vercel parsed objects, string and Buffer bodies behave identically', async () => {
  for (const body of [{url: LIST}, JSON.stringify({url: LIST}), Buffer.from(JSON.stringify({url: LIST}))]) {
    assert.equal((await invoke(body)).statusCode, 200);
  }
});

test('request stream parses incrementally and enforces the 8 KiB bound', async () => {
  const req = Readable.from([Buffer.from('{"url":"'), Buffer.from(LIST), Buffer.from('"}')]);
  req.method = 'POST'; req.headers = {authorization: `Bearer ${process.env.LP_SOURCE_WORKER_TOKEN}`};
  const res = response(); await handler(req, res); assert.equal(res.statusCode, 200);
  const oversized = Readable.from([Buffer.alloc(handler.REQUEST_LIMIT + 1, 32)]);
  oversized.method = 'POST'; oversized.headers = req.headers;
  const rejected = response(); await handler(oversized, rejected); assert.equal(rejected.statusCode, 413);
  for (const body of [' '.repeat(handler.REQUEST_LIMIT + 1), {url: LIST, x: 'x'.repeat(handler.REQUEST_LIMIT)}]) {
    assert.equal((await invoke(body)).statusCode, 413);
  }
  assert.equal(calls.length, 1);
});

test('source size is enforced on actual decoded bytes and stream is canceled', async () => {
  let canceled = false;
  global.fetch = async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(handler.SOURCE_LIMIT)); controller.enqueue(new Uint8Array(1)); },
    cancel() { canceled = true; }
  }), {headers: {'content-length': '1', 'content-encoding': 'gzip'}});
  const res = await invoke();
  assert.equal(res.statusCode, 413);
  assert.equal(canceled, true);
  assert.equal(JSON.parse(res.body).error, 'source_too_large');
});

test('every non-200 upstream status is rejected without copying its body', async () => {
  for (const status of [201, 206, 302, 400, 401, 403, 404, 500]) {
    global.fetch = async () => new Response('private upstream body', {status});
    const res = await invoke();
    assert.equal(res.statusCode, 502);
    assert.equal(res.body.includes('private upstream body'), false);
    assert.equal(res.headers['X-LP-Upstream-SHA256'], undefined);
  }
});

test('redirect exceptions and source errors return generic 502 without details', async () => {
  for (const error of [new TypeError('redirect blocked private details'), new Error('secret detail'), Object.assign(new Error('timeout'), {name: 'AbortError'})]) {
    global.fetch = async () => { throw error; };
    const res = await invoke();
    assert.equal(res.statusCode, 502);
    assert.deepEqual(JSON.parse(res.body), {error: 'source_fetch_failed'});
  }
});

test('20 second abort covers source fetching and body reading', async () => {
  const originalSet = global.setTimeout, originalClear = global.clearTimeout;
  let delay, aborted = false, cleared = false;
  global.setTimeout = (fn, ms) => { delay = ms; queueMicrotask(fn); return 1; };
  global.clearTimeout = () => { cleared = true; };
  global.fetch = async (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => { aborted = true; reject(Object.assign(new Error(), {name: 'AbortError'})); });
  });
  try {
    assert.equal((await invoke()).statusCode, 502);
    assert.equal(delay, 20000); assert.equal(aborted, true); assert.equal(cleared, true);
  } finally { global.setTimeout = originalSet; global.clearTimeout = originalClear; }
});

test('health exposes only service, region and release without fetching or secrets', () => {
  const res = response(); health({}, res);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(JSON.parse(res.body), {service: 'lp-source-worker', region: 'icn1', release: 'test-release'});
  assert.equal(res.body.includes(process.env.LP_SOURCE_WORKER_TOKEN), false);
  assert.equal(res.headers['Cache-Control'], 'no-store');
  assert.equal(calls.length, 0);
});

test('configured listing-base referer is allowed without inventing search parameters', async () => {
  const res = await invoke({url:LIST, referer:'https://www.kfcc.co.kr/mgNotice/mgNoticeList.do?schType=subject'});
  assert.equal(res.statusCode,200);
  assert.equal(calls.length,1);
});
