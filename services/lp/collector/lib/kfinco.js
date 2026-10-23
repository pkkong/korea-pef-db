'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');
const tls = require('node:tls');
const fail = (status, code) => Object.assign(new Error(code), {status, code});
const FINGERPRINT = '72A34AC2B424AED3F6B0B04755B88CC027DCCC806FDDB22B4CD7C47773973EC0';

function certificateAuthorities(now = Date.now()) {
  const pem = fs.readFileSync(__dirname + '/../certs/sectigo-rsa-organization-validation.pem', 'utf8');
  const blocks = pem.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) || [];
  if (blocks.length !== 1 || pem.trim() !== blocks[0].trim()) throw fail(502, 'source_certificate_invalid');
  const certificate = new crypto.X509Certificate(blocks[0]);
  if (pem.includes('TRUSTED CERTIFICATE') || !certificate.ca || certificate.subject === certificate.issuer ||
      certificate.fingerprint256.replaceAll(':', '') !== FINGERPRINT ||
      now < Date.parse(certificate.validFrom) || now > Date.parse(certificate.validTo)) throw fail(502, 'source_certificate_invalid');
  return [...tls.rootCertificates, certificate.toString()];
}

function officialUrl(value, referer = false) {
  if (typeof value !== 'string' || value.length > 4096 || /[\x00-\x20\x7f\\#]/.test(value) ||
      !/^https:\/\/www\.kfinco\.co\.kr(?::443)?\//.test(value)) throw fail(400, 'invalid_source_url');
  const url = new URL(value);
  const path = value.replace(/^https:\/\/www\.kfinco\.co\.kr(?::443)?/, '').split('?')[0];
  if (url.hostname !== 'www.kfinco.co.kr' || url.username || url.password || url.hash ||
      (url.port && url.port !== '443') || path !== url.pathname) throw fail(400, 'invalid_source_url');
  const entries = [...url.searchParams.entries()];
  if (new Set(entries.map(([key]) => key)).size !== entries.length) throw fail(400, 'invalid_source_query');
  if (referer) {
    if (entries.length || !/^\/pr\/notice(?:\/detail\/NT\d{14})?$/.test(path)) throw fail(400, 'invalid_source_path');
  } else if (path === '/api/pr/notice/list') {
    if (entries.length !== 3 || url.searchParams.get('page') !== '1' || url.searchParams.get('size') !== '10' ||
        url.searchParams.get('searchKeyword') !== '위탁운용사') throw fail(400, 'invalid_source_query');
  } else if (/^\/api\/pr\/notice\/detail\/NT\d{14}$/.test(path)) {
    if (entries.length) throw fail(400, 'invalid_source_query');
  } else if (path === '/util/download') {
    const file = url.searchParams.get('filePath') || '', name = url.searchParams.get('downloadName') || '';
    if (entries.length !== 2 || !/^\/pds\/notice\/\d{4}-\d{2}\/[A-Za-z0-9_-]+\.(?:hwp|hwpx|pdf)$/i.test(file) ||
        !name || name.length > 255 || /[%/\\\x00-\x1f\x7f?#:]/.test(name) || name.includes('..') ||
        !/\.(?:hwp|hwpx|pdf)$/i.test(name) || !/공고|RFP|제안요청서/i.test(name)) throw fail(400, 'invalid_source_query');
  } else throw fail(400, 'invalid_source_path');
  return url.href;
}

function sourceBytes(url, referer, limit, signal) {
  officialUrl(url);
  if (referer) officialUrl(referer, true);
  return new Promise((resolve, reject) => {
    const headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'};
    if (referer) headers.Referer = referer;
    const request = https.request(url, {method: 'GET', headers, signal,
      ca: certificateAuthorities(), rejectUnauthorized: true, allowPartialTrustChain: false}, response => {
      if (response.statusCode !== 200 || !response.socket.authorized) {
        response.destroy(); reject(fail(502, 'upstream_status')); return;
      }
      const parts = []; let size = 0;
      response.on('data', part => {
        size += part.length;
        if (size > limit) { response.destroy(); reject(fail(413, 'source_too_large')); }
        else parts.push(part);
      });
      response.on('error', reject);
      response.on('aborted', () => reject(fail(502, 'source_fetch_failed')));
      response.on('end', () => resolve(Buffer.concat(parts, size)));
    });
    request.on('error', reject);
    request.end();
  });
}
module.exports = {officialUrl, certificateAuthorities, sourceBytes, FINGERPRINT};
