'use strict';
module.exports = function health(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify({service: 'lp-source-worker', region: process.env.VERCEL_REGION || '', release: process.env.SERVICE_RELEASE || ''}));
};
