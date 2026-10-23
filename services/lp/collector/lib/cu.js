'use strict';
const fail = (code) => Object.assign(new Error(code), {status: 400, code});
function officialUrl(value, referer = false) {
  if (typeof value !== 'string' || value.length > 4096 || /[\x00-\x20\x7f\\#]/.test(value) ||
      !/^https:\/\/www\.cu\.co\.kr(?::443)?\//.test(value)) throw fail('invalid_source_url');
  const url = new URL(value);
  const path = value.replace(/^https:\/\/www\.cu\.co\.kr(?::443)?/, '').split('?')[0];
  if (url.hostname !== 'www.cu.co.kr' || url.username || url.password || url.hash ||
      (url.port && url.port !== '443') || path !== url.pathname) throw fail('invalid_source_url');
  const entries = [...url.searchParams.entries()], query = url.searchParams;
  if (new Set(entries.map(([key]) => key)).size !== entries.length) throw fail('invalid_source_query');
  if (path === '/cu/na/ntt/selectNttList.do') {
    const base = ['bbsId', 'mi', 'searchType', 'listCo'];
    if (query.get('bbsId') !== '1020' || query.get('mi') !== '100007' ||
        query.get('searchType') !== 'sj' || query.get('listCo') !== '50') throw fail('invalid_source_query');
    if (referer && entries.length === 4 && entries.every(([key]) => base.includes(key))) return url.href;
    const page = query.get('currPage') || '';
    if (entries.length !== 6 || entries.some(([key]) => ![...base, 'searchValue', 'currPage'].includes(key)) ||
        !['블라인드', '위탁운용사'].includes(query.get('searchValue')) || !/^[1-9]\d{0,3}$/.test(page) || Number(page) > 1000) throw fail('invalid_source_query');
  } else if (path === '/cu/na/ntt/selectNttInfo.do') {
    if (![2, 3].includes(entries.length) || !/^\d{1,12}$/.test(query.get('nttSn') || '') ||
        query.get('mi') !== '100007' || (query.has('bbsId') && query.get('bbsId') !== '1020') ||
        entries.some(([key]) => !['nttSn', 'mi', 'bbsId'].includes(key))) throw fail('invalid_source_query');
  } else if (!referer && path === '/common/nttFileDownload.do') {
    if (entries.length !== 1 || entries[0][0] !== 'fileKey' || !/^[a-fA-F0-9]{32}$/.test(entries[0][1])) throw fail('invalid_source_query');
  } else throw fail('invalid_source_path');
  return url.href;
}
module.exports = {officialUrl};
