'use strict';
const {test, beforeEach, afterEach} = require('node:test');
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {Readable} = require('node:stream');
const https = require('node:https');
const tls = require('node:tls');
const crypto = require('node:crypto');
const kfinco = require('../lib/kfinco');
const handler = require('../api/fetch');
const LIST = 'https://www.kfinco.co.kr/api/pr/notice/list?page=1&size=10&searchKeyword='+encodeURIComponent('위탁운용사');
const DETAIL = 'https://www.kfinco.co.kr/api/pr/notice/detail/NT20990101000123';
const FILE = 'https://www.kfinco.co.kr/util/download?filePath=%2Fpds%2Fnotice%2F2026-09/a_file.hwp&downloadName='+encodeURIComponent('2026 공고문.hwp');
let originalRequest, originalFetch, originalEnv, calls, status, body, authorized, error;
beforeEach(() => {
  originalRequest=https.request;originalFetch=global.fetch;originalEnv={...process.env};
  process.env.LP_SOURCE_WORKER_TOKEN='test-key';process.env.VERCEL_REGION='icn1';
  calls=[];status=200;body=Buffer.from('official bytes');authorized=true;error=null;
  global.fetch=async()=>{throw Error('KFINCO must use strict https.request');};
  https.request=(url,options,callback)=>{
    calls.push({url,options});const request=new EventEmitter();
    request.end=()=>queueMicrotask(()=>{
      if(error){request.emit('error',error);return;}
      const response=Readable.from([body]);response.statusCode=status;response.socket={authorized};callback(response);
    });
    options.signal?.addEventListener('abort',()=>request.emit('error',Error('aborted')),{once:true});
    return request;
  };
});
afterEach(()=>{https.request=originalRequest;global.fetch=originalFetch;process.env=originalEnv;});
async function invoke(url, extras={}) {
  const res={headers:{},setHeader(k,v){this.headers[k]=v;},end(body){this.body=body;}};
  await handler({method:'POST',headers:{authorization:'Bearer test-key'},body:{url,...extras}},res);
  return res;
}

test('official KFINCO API and attachment routes return unchanged bytes through the strict HTTPS client',async()=>{
  body=Buffer.from([0,255,128,10]);
  for(const url of [LIST,DETAIL,FILE]){
    const result=await invoke(url);assert.equal(result.statusCode,200);assert.deepEqual(result.body,body);
    assert.equal(result.headers['X-LP-Upstream-SHA256'],crypto.createHash('sha256').update(body).digest('hex'));
  }
  for(const {options} of calls){
    assert.equal(options.rejectUnauthorized,true);assert.equal(options.allowPartialTrustChain,false);
    assert.deepEqual(options.ca.slice(0,-1),[...tls.rootCertificates]);
    assert.equal(new crypto.X509Certificate(options.ca.at(-1)).fingerprint256.replaceAll(':',''),kfinco.FINGERPRINT);
    assert.equal(options.checkServerIdentity,undefined);assert.equal(options.headers.Authorization,undefined);
    assert.equal(options.signal.aborted,false);
  }
});

test('private hosts, lookalikes, alternate queries, redirects and encoded paths never reach HTTPS',async()=>{
  const invalid=[LIST.replace('https:','http:'),LIST.replace('www.kfinco.co.kr','127.0.0.1'),
    LIST.replace('www.kfinco.co.kr','www.kfinco.co.kr.evil.example'),LIST.replace('www.kfinco.co.kr','u:p@www.kfinco.co.kr'),
    LIST.replace('www.kfinco.co.kr','www.kfinco.co.kr:444'),LIST+'#x',LIST+'&page=2',LIST.replace('size=10','size=100'),
    LIST.replace('page=1','page=2'),LIST+'&redirect=https://evil.example',LIST.replace('searchKeyword=','keyword='),
    DETAIL+'?x=1',DETAIL.replace('NT20990101000123','NT123'),DETAIL.replace('/api/','/private/../api/'),
    FILE.replace('%2Fpds','%252Fpds'),FILE.replace('a_file.hwp','../a_file.hwp'),
    FILE.replace('a_file.hwp','a%2Ffile.hwp'),FILE.replace('a_file.hwp','a.exe'),FILE+'&filePath=x',
    FILE.replace('downloadName=','name=')];
  for(const url of invalid)assert.equal((await invoke(url)).statusCode,400,url);
  assert.equal(calls.length,0);
});

test('source referer must belong to the same official institution and allowed notice route',async()=>{
  for(const referer of ['https://www.kfcc.co.kr/mgNotice/mgNoticeList.do','https://www.kfinco.co.kr/admin',FILE]){
    assert.equal((await invoke(LIST,{referer})).statusCode,400);
  }
  assert.equal(calls.length,0);
  const referer='https://www.kfinco.co.kr/pr/notice';
  assert.equal((await invoke(DETAIL,{referer})).statusCode,200);assert.equal(calls[0].options.headers.Referer,referer);
});

test('upstream errors, redirects and unverified sockets cannot become official bytes',async()=>{
  for(const code of [201,206,301,302,400,403,404,500]){
    status=code;const result=await invoke(LIST);assert.equal(result.statusCode,502);
    assert.equal(result.headers['X-LP-Upstream-SHA256'],undefined);assert.equal(result.body.includes('official bytes'),false);
  }
  status=200;authorized=false;assert.equal((await invoke(LIST)).statusCode,502);
});

test('TLS failures fail closed and preserve private error details',async()=>{
  for(const code of ['UNABLE_TO_VERIFY_LEAF_SIGNATURE','ERR_TLS_CERT_ALTNAME_INVALID','CERT_HAS_EXPIRED']){
    error=Object.assign(Error('private diagnostic'),{code});const result=await invoke(LIST);
    assert.equal(result.statusCode,502);assert.deepEqual(JSON.parse(result.body),{error:'source_fetch_failed'});
  }
});

test('actual bytes enforce the 3 MiB source limit',async()=>{
  body=Buffer.alloc(handler.SOURCE_LIMIT+1);const result=await invoke(FILE);
  assert.equal(result.statusCode,413);assert.equal(result.headers['X-LP-Upstream-SHA256'],undefined);
});

test('expired intermediate fails before requesting the upstream',()=>{
  assert.throws(()=>kfinco.certificateAuthorities(Date.UTC(2031,0,1)),/source_certificate_invalid/);
  assert.throws(()=>kfinco.certificateAuthorities(Date.UTC(2018,0,1)),/source_certificate_invalid/);
});

test('KFINCO timeout uses the same 20 second cancellation and cleans up',async()=>{
  const originalSet=global.setTimeout,originalClear=global.clearTimeout;let delay,cleared=false;
  global.setTimeout=(fn,ms)=>{delay=ms;queueMicrotask(fn);return 1;};global.clearTimeout=()=>{cleared=true;};
  https.request=(url,options)=>{
    const request=new EventEmitter();request.end=()=>{};
    options.signal.addEventListener('abort',()=>request.emit('error',Error('aborted')));return request;
  };
  try{assert.equal((await invoke(LIST)).statusCode,502);assert.equal(delay,20000);assert.equal(cleared,true);}
  finally{global.setTimeout=originalSet;global.clearTimeout=originalClear;}
});


test('appending another root or replacing the pinned intermediate is rejected before network',()=>{
  const fs=require('node:fs');const original=fs.readFileSync;
  const pem=kfinco.certificateAuthorities().at(-1);
  try{
    for(const changed of [pem+'\n'+tls.rootCertificates[0],tls.rootCertificates[0],pem.replace('BEGIN CERTIFICATE','BEGIN TRUSTED CERTIFICATE')]){
      fs.readFileSync=()=>changed;
      assert.throws(()=>kfinco.certificateAuthorities());
    }
    assert.equal(calls.length,0);
  }finally{fs.readFileSync=original;}
});
