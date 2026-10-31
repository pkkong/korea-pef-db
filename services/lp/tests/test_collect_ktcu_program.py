import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import collect_ktcu_program as ktcu
import ktcu_listing


def listing(rows, page=1, last=1, term='운용사'):
    items=''.join(f'<li><span class="num">{num}</span><a href="javascript:fn_view(\'{ident}\');">{title}</a><span>{day}</span></li>'
                  for ident,title,day,num in rows)
    return f'<html><input name="srchText" value="{term}"><input name="curPage" value="{page}"><div class="sort-tit">총 {len(rows)} 건 ({page}/{last} 페이지)</div><ul id="ulList">{items}</ul></html>'


class KtcuProgramCollectionTest(unittest.TestCase):
    def test_listing_contract_and_empty_scope(self):
        url=ktcu.BASE+'/PPW-CSB-000101?srchKey=sj&srchText=운용사&curPage=1'
        html=listing([('987','연도 없는 펀드 운용사 선정','2026-10-31','1')])
        self.assertEqual(ktcu_listing.parse_rows(html,url)[0]['source_id'],'ktcu:987')
        self.assertEqual(ktcu_listing.last_page(html,url),1)
        for bad in [html.replace('</html>',''),html.replace('value="1"','value="2"'),
                    html.replace('value="운용사"','value="다름"'),html.replace('2026-10-31','2026-99-31'),
                    html.replace('id="ulList"','id="footer"'),html.replace('(1/1','(2/1')]:
            with self.assertRaises(ValueError):ktcu_listing.parse_rows(bad,url)
        empty=listing([]).replace('<ul id="ulList"></ul>','<ul id="ulList"><li>등록된 게시물이 없습니다.</li></ul>')
        self.assertEqual(ktcu_listing.parse_rows(empty,url),[])
        with self.assertRaises(ValueError):ktcu_listing.parse_rows(empty.replace('총 0','총 1'),url)

    def test_rolling_dates_generic_titles_dedup_and_old_approved_retracking(self):
        rows=[('90001','펀드 운용사 선정 공고','2026-11-01','5'),
              ('90002','연도 없는 펀드 운용사 선정 공고','2026-10-31','4'),
              ('90003','2025년 펀드 모집 공고','2025-11-01','3'),
              ('90004','오래된 펀드 모집 공고','2025-10-31','2')]
        calls=[]
        def fetch(url):
            calls.append(url)
            if '?' in url:
                q=parse_qs(urlsplit(url).query)
                return listing(rows,term=q['srchText'][0],last=1).encode()
            return b'detail'
        def parse(ident,raw):
            if ident=='61742':return {**self.notice,'attachments':[],'date':'2020-01-01'}
            r=next(r for r in rows if r[0]==ident)
            return {'source_id':ident,'url':ktcu.BASE+'/PPW-CSB-000101/'+ident,'title':r[1],'date':r[2],
                    'body':'unverified','sha256':'a'*64,'attachments':[]}
        with patch.object(ktcu,'parse_notice',side_effect=parse),patch.object(ktcu,'project',return_value=([],[])):
            result=ktcu.collect(self.seed,'2026-10-30T15:30:00+00:00',fetch)
        self.assertEqual([n['source_id'] for n in result['notices']],['61742','90002','90003'])
        self.assertEqual(len([u for u in calls if '?' not in u]),3)
        self.assertEqual(len(result['holds']),2)
        self.assertFalse(result['programs'])

    def test_unbounded_listing_fails_explicitly(self):
        def fetch(url):
            q=parse_qs(urlsplit(url).query);page=int(q['curPage'][0])
            return listing([(str(90000+page),'펀드 운용사 선정','2026-10-31',str(page))],
                           page=page,last=11,term=q['srchText'][0]).encode()
        with self.assertRaisesRegex(ValueError,'exceeded 10 pages'):
            ktcu.collect(self.seed,'2026-10-31T00:00:00+00:00',fetch)

    def test_mixed_date_page_does_not_hide_following_recent_notice(self):
        pages={1:[('90001','오래된 펀드 모집','2025-10-31','3'),
                  ('90002','최근 펀드 모집','2026-10-20','2')],
               2:[('90003','다음 페이지 펀드 모집','2026-09-01','1')],
               3:[('90004','과거 펀드 모집','2025-10-30','1')]}
        calls=[]
        def fetch(url):
            calls.append(url)
            if '?' in url:
                q=parse_qs(urlsplit(url).query);page=int(q['curPage'][0])
                return listing(pages[page],page=page,last=8,term=q['srchText'][0]).encode()
            return b'detail'
        def parse(ident,raw):
            if ident=='61742':return {**self.notice,'attachments':[]}
            r=next(r for rows in pages.values() for r in rows if r[0]==ident)
            return {'source_id':ident,'url':ktcu.BASE+'/PPW-CSB-000101/'+ident,'title':r[1],
                    'date':r[2],'body':'unverified','sha256':'a'*64,'attachments':[]}
        with patch.object(ktcu,'parse_notice',side_effect=parse),patch.object(ktcu,'project',return_value=([],[])):
            result=ktcu.collect(self.seed,'2026-10-31T00:00:00+00:00',fetch)
        self.assertEqual([n['source_id'] for n in result['notices']],['61742','90002','90003'])
        self.assertEqual(len([u for u in calls if '?' in u]),len(ktcu.SEARCH_TERMS)*3)

    def test_official_timeout_is_retried_but_missing_notice_is_not(self):
        class Response(BytesIO):
            def geturl(self): return ktcu.BASE+'/official'
        with patch.object(ktcu,'urlopen',side_effect=[URLError('timed out'),TimeoutError(),Response(b'official')]) as opened, \
             patch.object(ktcu.time,'sleep'):
            self.assertEqual(ktcu._get(ktcu.BASE+'/official'),b'official')
            self.assertEqual(opened.call_count,3)
        with patch.object(ktcu,'urlopen',side_effect=HTTPError(ktcu.BASE+'/missing',404,'missing',{},None)) as opened:
            with self.assertRaises(HTTPError): ktcu._get(ktcu.BASE+'/missing')
            self.assertEqual(opened.call_count,1)

    def setUp(self):
        self.seed = next(p for p in json.loads((ktcu.ROOT / "data/lp_programs_pilot.json").read_text())["programs"]
                         if p["id"] == ktcu.PROGRAM_ID)
        self.notice = {"source_id": "61742", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/61742",
                       "title": "2026년 블라인드 PEF 모집", "date": "2026-09-04",
                       "body": "출자규모 3,000억원, 선정 9개사, 접수 9월 11일 15시",
                       "attachment_hashes": {"공고.pdf": "reviewed-pdf"},
                       "attachment_text": "국내 소재 기업에 펀드 70% 이상 투자"}
        self.notice["sha256"] = hashlib.sha256(json.dumps(
            [self.notice["title"], self.notice["date"], self.notice["body"]], ensure_ascii=False).encode()).hexdigest()
        self.recipe = {"sources": [{"source_id": "61742", "event": "모집 공고",
                                     **{k: self.notice[k] for k in ("url", "title", "date", "sha256")},
                                     "body_quotes": ["3,000억원", "9월 11일"],
                                     "attachment_hashes": {"공고.pdf": "reviewed-pdf"},
                                     "attachment_quotes": ["70% 이상"]}]}
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "recipe.json"
        self.path.write_text(json.dumps(self.recipe, ensure_ascii=False))
        patcher = patch.object(ktcu, "REVIEW", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reviewed_notice_closes_recruitment_without_inventing_gps(self):
        programs, holds = ktcu.project([self.notice], "2026-10-03T00:00:00+00:00", self.seed)
        self.assertEqual([], holds)
        self.assertEqual("접수 마감", programs[0]["status"])
        self.assertEqual([], programs[0]["selected_gps"])
        self.assertNotIn("공고상 접수 마감", [e["type"] for e in programs[0]["events"]])

    def test_changed_source_or_pdf_preserves_previous_publication(self):
        edited = copy.deepcopy(self.notice)
        edited["body"] += " 변경"
        self.assertEqual([], ktcu.project([edited], "2026-10-03T00:00:00+00:00", self.seed)[0])
        edited = copy.deepcopy(self.notice)
        edited["attachment_hashes"]["공고.pdf"] = "changed-pdf"
        self.assertEqual([], ktcu.project([edited], "2026-10-03T00:00:00+00:00", self.seed)[0])

    def test_unreviewed_result_is_only_a_link_candidate(self):
        result = {"source_id": "62000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/62000",
                  "title": "2026년 블라인드 PEF 선정 결과", "date": "2026-10-30",
                  "body": "A운용사 최종 선정", "sha256": "candidate"}
        programs, holds = ktcu.project([self.notice, result], "2026-10-31T00:00:00+00:00", self.seed)
        self.assertEqual([], programs)
        self.assertIn("검토 필요", holds[0]["reason"])
        self.assertEqual("62000", ktcu.link_suggestions([self.notice, result], self.seed["title"])[0]["source_id"])

    def test_next_year_pef_is_a_new_program_candidate_without_holding_2026(self):
        later = {"source_id": "70000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/70000",
                 "title": "2027년 블라인드 PEF 위탁운용사 선정 공고", "date": "2026-12-01",
                 "body": "별도 출자사업 모집 공고", "sha256": "candidate"}
        programs, holds = ktcu.project([self.notice, later], "2026-12-02T00:00:00+00:00", self.seed)
        self.assertEqual([], holds)
        self.assertEqual(ktcu.PROGRAM_ID, programs[0]["id"])
        self.assertEqual([], ktcu.link_suggestions([self.notice, later], self.seed["title"]))
        self.assertEqual("70000", ktcu.discovery_candidates([self.notice, later])[0]["source_id"])

    def test_result_review_requires_names_in_official_source(self):
        result = {"source_id": "62000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/62000",
                  "title": "2026년 블라인드 PEF 선정 결과", "date": "2026-10-30",
                  "body": "B운용사 최종 선정", "attachment_hashes": {}}
        result["sha256"] = hashlib.sha256(json.dumps(
            [result["title"], result["date"], result["body"]], ensure_ascii=False).encode()).hexdigest()
        self.recipe["sources"].append({"source_id": "62000", "event": "최종 선정",
                                        **{k: result[k] for k in ("url", "title", "date", "sha256")},
                                        "manager_names": ["A운용사"]})
        self.path.write_text(json.dumps(self.recipe, ensure_ascii=False))
        programs, holds = ktcu.project([self.notice, result], "2026-10-31T00:00:00+00:00", self.seed)
        self.assertEqual([], programs)
        self.assertIn("명단", holds[0]["reason"])


if __name__ == "__main__":
    unittest.main()
