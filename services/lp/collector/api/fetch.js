'use strict';
const crypto = require('node:crypto');
const kfinco = require('../lib/kfinco');
const cu = require('../lib/cu');
const REQUEST_LIMIT = 8 * 1024;
const SOURCE_LIMIT = 3 * 1024 * 1024;
const fail = (status, code) => Object.assign(new Error(code), {status, code});

function authorized(req) {
  const token = process.env.LP_SOURCE_WORKER_TOKEN;
  const value = req.headers && req.headers.authorization;
  if (!token || typeof value !== 'string' || !value.startsWith('Bearer ')) return false;
  const digest = value => crypto.createHash('sha256').update(value).digest();
  return crypto.timingSafeEqual(digest(value.slice(7)), digest(token));
}

function officialUrl(value, referer = false) {
  if (typeof value === 'string' && /^https:\/\/www\.cu\.co\.kr(?::443)?\//.test(value)) return cu.officialUrl(value, referer);
  if (typeof value === 'string' && /^https:\/\/www\.kfinco\.co\.kr(?::443)?\//.test(value)) return kfinco.officialUrl(value, referer);
  if (typeof value !== 'string' || value.length > 4096 || /[\x00-\x20\x7f\\#]/.test(value) ||
      !/^https:\/\/www\.kfcc\.co\.kr(?::443)?\//.test(value)) throw fail(400, 'invalid_source_url');
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== 'www.kfcc.co.kr' || url.username || url.password ||
      (url.port && url.port !== '443') || url.hash) throw fail(400, 'invalid_source_url');
  // Validate the original path, before URL dot-segment normalization can hide it.
  const path = value.replace(/^https:\/\/www\.kfcc\.co\.kr(?::443)?/, '').split('?')[0];
  if (path !== url.pathname) throw fail(400, 'invalid_source_path');
  const entries = [...url.searchParams.entries()];
  if (new Set(entries.map(([key]) => key)).size !== entries.length) throw fail(400, 'invalid_source_query');
  if (path === '/mgNotice/mgNoticeList.do') {
    if (referer && (!entries.length || (entries.length === 1 && url.searchParams.get('schType') === 'subject'))) return url.href;
    if (entries.length !== 3 || url.searchParams.get('schType') !== 'subject' ||
        !url.searchParams.get('schValue')?.trim() || url.searchParams.get('schValue').length > 50 ||
        !/^\d{1,8}$/.test(url.searchParams.get('pageNo') || '') ||
        entries.some(([key]) => !['schType', 'schValue', 'pageNo'].includes(key))) throw fail(400, 'invalid_source_query');
  } else if (path === '/mgNotice/mgNoticeDetail.do') {
    if (entries.length !== 1 || entries[0][0] !== 'no' || !/^\d{1,12}$/.test(entries[0][1])) throw fail(400, 'invalid_source_query');
  } else if (!referer && path.startsWith('/upload/neoboard/A01/')) {
    let name;
    try { name = decodeURIComponent(path.slice('/upload/neoboard/A01/'.length)); }
    catch { throw fail(400, 'invalid_source_filename'); }
    if (entries.length || !name || name.length > 255 || name.startsWith('.') || name.includes('..') ||
        /[%/\\\x00-\x1f\x7f?#:]/.test(name) || !/^[\p{L}\p{N}_. ()\[\]+-]+$/u.test(name)) throw fail(400, 'invalid_source_filename');
  } else throw fail(400, 'invalid_source_path');
  return url.href;
}

async function readRequest(req) {
  let body = req.body;
  if (body === undefined) {
    const parts = []; let length = 0;
    for await (const part of req) {
      const bytes = Buffer.isBuffer(part) ? part : Buffer.from(part);
      length += bytes.length;
      if (length > REQUEST_LIMIT) throw fail(413, 'request_too_large');
      parts.push(bytes);
    }
    body = Buffer.concat(parts);
  }
  try {
    if (Buffer.isBuffer(body) || typeof body === 'string') {
      if (Buffer.byteLength(body) > REQUEST_LIMIT) throw fail(413, 'request_too_large');
      body = JSON.parse(body.toString());
    } else if (Buffer.byteLength(JSON.stringify(body) || '') > REQUEST_LIMIT) throw fail(413, 'request_too_large');
  } catch (error) { throw error.status ? error : fail(400, 'invalid_json'); }
  if (!body || typeof body !== 'object' || Array.isArray(body) ||
      Object.keys(body).some(key => !['url', 'referer'].includes(key)) || !Object.hasOwn(body, 'url')) throw fail(400, 'invalid_request');
  const url = officialUrl(body.url), referer = Object.hasOwn(body, 'referer') ? officialUrl(body.referer, true) : undefined;
  if (referer && new URL(url).hostname !== new URL(referer).hostname) throw fail(400, 'invalid_source_url');
  return {url, referer};
}

async function sourceBytes(response) {
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader();
  const parts = []; let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > SOURCE_LIMIT) { await reader.cancel(); throw fail(413, 'source_too_large'); }
      parts.push(Buffer.from(value));
    }
  } finally { reader.releaseLock(); }
  return Buffer.concat(parts, size);
}

async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-LP-Source-Region', process.env.VERCEL_REGION || '');
  try {
    if (!authorized(req)) throw fail(401, 'unauthorized');
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); throw fail(405, 'method_not_allowed'); }
    const {url, referer} = await readRequest(req);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'};
      if (referer) headers.Referer = referer;
      let bytes;
      if (new URL(url).hostname === 'www.kfinco.co.kr') {
        bytes = await kfinco.sourceBytes(url, referer, SOURCE_LIMIT, controller.signal);
      } else {
      const response = await fetch(url, {method: 'GET', headers, redirect: 'error', signal: controller.signal});
      if (response.status !== 200 || response.redirected) {
        await response.body?.cancel(); throw fail(502, 'upstream_status');
      }
      bytes = await sourceBytes(response);
      }
      res.statusCode = 200;
      res.setHeader('Content-Type', 'application/octet-stream');
      res.setHeader('X-LP-Upstream-SHA256', crypto.createHash('sha256').update(bytes).digest('hex'));
      res.end(bytes);
    } finally { clearTimeout(timer); }
  } catch (error) {
    res.statusCode = error.status || 502;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.end(JSON.stringify({error: error.code && error.status ? error.code : 'source_fetch_failed'}));
  }
}
module.exports = handler;
Object.assign(module.exports, {officialUrl, authorized, readRequest, sourceBytes, REQUEST_LIMIT, SOURCE_LIMIT});
