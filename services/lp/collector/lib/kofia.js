'use strict';
const fail = (code) => Object.assign(new Error(code), {status: 400, code});
// Only the public, unfiltered board17 listing and its observed first three pages.
function officialUrl(value) {
  if (typeof value !== 'string' || value.length > 4096 || /[\x00-\x20\x7f\\#]/.test(value) ||
      !/^https:\/\/www\.kofia\.or\.kr(?::443)?\//.test(value)) throw fail('invalid_source_url');
  const url = new URL(value);
  const path = value.replace(/^https:\/\/www\.kofia\.or\.kr(?::443)?/, '').split('?')[0];
  if (url.hostname !== 'www.kofia.or.kr' || url.username || url.password || url.hash ||
      (url.port && url.port !== '443') || path !== '/brd/m_17/list.do' || path !== url.pathname) throw fail('invalid_source_url');
  const entries = [...url.searchParams.entries()];
  if (!entries.length) return url.href;
  const expected = {page: '', srchFr: '', srchTo: '', srchWord: '', srchTp: '',
    multi_itm_seq: '0', itm_seq_1: '0', itm_seq_2: '0', company_cd: '', company_nm: ''};
  if (entries.length !== Object.keys(expected).length ||
      new Set(entries.map(([key]) => key)).size !== entries.length ||
      !/^[1-3]$/.test(url.searchParams.get('page') || '') ||
      entries.some(([key, value]) => !Object.hasOwn(expected, key) || (key !== 'page' && value !== expected[key]))) {
    throw fail('invalid_source_query');
  }
  return url.href;
}
module.exports = {officialUrl};
