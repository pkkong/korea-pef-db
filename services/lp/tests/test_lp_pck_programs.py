import copy
import unittest
from xml.sax.saxutils import escape
from urllib.parse import parse_qs, urlsplit

from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import lp_pck_programs as pck
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.src.lp_program_service import validate
from services.lp.tests.test_lp_board_adapter_pck import CONFIG, TITLE, detail_url, listing, detail, docx

OFFERING = '''2026년도 하반기 대체투자 위탁운용사 선정 공고
1. 선정개요
선정 유형 대체투자 (PE, VC, Infra), 인프라에 한해 프로젝트형 포함
선정 운용사 수 유형별 O개사
운용 규모 (예정) 최대 500억원
선정 절차 및 일정
10/22 (목) 모집 공고
10/29 (목) 지원서류 접수 마감 (17:00)
11/6 (금) 1차 평가(정량) 결과 발표
11/10 (화) 2차 평가 (정성, PT) 및 최종 선정
※ 상기 일정은 변경될 수 있음.
2. 지원자격 및 유의사항
기관전용 사모집합투자기구 및 업무집행사원
[블라인드형] 운용규모 3,000억원 이상
1개 운용사가 복수 자산군(PE/VC/Infra)에 중복 지원 가능하며, 이 경우 자산군별로 제안서 및 제출서류 일체를 각각 별도 제출함
3. 제출자료 및 접수처
접수마감 2026. 10. 29. (목) 17:00까지
4. 제안서 작성 안내
주목적과 실적은 운용사가 자유 기재
'''


def document(text):
    return docx('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
                ''.join('<w:p><w:r><w:t>'+escape(line)+'</w:t></w:r></w:p>' for line in text.splitlines()) + '</w:body></w:document>')


def collect(text=OFFERING, extra=None):
    docs = {
        '991001': (TITLE, '2026-07-08', '7월 모집'),
        '991002': (TITLE, '2026-10-22', '10월 모집'),
        '991003': ('총회연금재단 2026 위탁운용사 최종 선정 결과 공지', '2026-08-11', '기존 확정된 PE 선정 결과'),
    }
    if extra:
        docs.update(extra)
    rows = [(i,t,d,False) for i,(t,d,b) in docs.items()]
    rows.sort(key=lambda x:x[2],reverse=True)
    config={**CONFIG,'pages':1}
    def fetch(url,referer=None):
        if 'download.asp' in url:return document(text)
        if 'read.asp' not in url:return listing(rows,last=1).encode()
        ident=parse_qs(urlsplit(url).query)['seq'][0]
        title,stamp,body=docs[ident]
        return detail(ident,stamp,title,body,filename='위탁운용사 선정 계획.docx' if ident=='991002' else None).encode()
    r=boards.collect({'pck_pension':config},fetch_factory=lambda c:fetch,checked_at='2026-11-11T00:00:00+00:00')
    assert not r['holds'],r['holds']
    return r, config


def old_program():
    return {'id':'old-pck-pe','institution_id':'pck_pension','institution_name':'총회연금재단','title':TITLE,
            'asset_scope':'PE','status':'선정 완료','selected_gps':[{'name':'기존 검증 GP','source_url':detail_url(991003),'asset_scope':'PE'}],
            'events':[{'type':'모집 공고','date':'2026-07-08','title':TITLE,'url':detail_url(991001)},
                      {'type':'최종 선정','date':'2026-08-11','title':'기존 결과','url':detail_url(991003)}]}


class PckProgramTests(unittest.TestCase):
    def test_independent_pe_track_publishes_without_combined_budget_or_invented_count(self):
        r,_=collect()
        programs,holds=publish_basic_notices({'programs':[old_program()],'institution_notices':r['notices']},[],r['checked_at'])
        self.assertEqual(len(programs),2);self.assertFalse(holds)
        new=next(p for p in programs if p['id']!='old-pck-pe')
        self.assertEqual(new['deadline'],'2026-10-29T17:00:00+09:00')
        self.assertNotIn('commitment_amount_krw',new);self.assertNotIn('manager_count',new)
        self.assertNotIn('primary_investment',new);self.assertEqual(new['selected_gps'],[])
        self.assertEqual({s['date'] for s in new['schedule_stages'] if s['status']=='planned'},{'2026-11-06','2026-11-10'})
        self.assertEqual([e['url'] for e in new['events']],[detail_url(991002)])
        old=next(p for p in programs if p['id']=='old-pck-pe')
        self.assertEqual(old['selected_gps'],old_program()['selected_gps']);self.assertEqual(old['status'],'선정 완료')
        self.assertNotIn(detail_url(991002),[e['url'] for e in old['events']])
        validate({'as_of':r['checked_at'][:10],'programs':programs})
        self.assertEqual(next(e['type'] for e in old['events'] if e['url']==detail_url(991003)), '최종 선정')

    def test_missing_separate_track_or_form_only_evidence_never_qualifies_pe(self):
        for raw in [OFFERING.replace('각각 별도 제출함','함께 제출함'),
                    '2026년도 공고\n<별첨>\n'+OFFERING,
                    OFFERING.replace('인프라에 한해 프로젝트형 포함','PE 프로젝트형 포함')]:
            with self.subTest(text=raw[:40]):
                r,_=collect(raw);n=next(n for n in r['notices'] if n['url']==detail_url(991002))
                self.assertFalse(pck.offering_sources(n))
                programs,_=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],r['checked_at'])
                self.assertFalse(programs)

    def test_unknown_result_is_held_and_never_attached_by_nearest_date(self):
        extra={'991004':('총회연금재단 2026 위탁운용사 최종 선정 결과 공지','2026-11-10','2026년 결과. 선정 GP 새이름')}
        r,_=collect(extra=extra)
        programs,holds=publish_basic_notices({'programs':[old_program()],'institution_notices':r['notices']},[],r['checked_at'])
        new=next(p for p in programs if p['id']!='old-pck-pe')
        self.assertEqual(new['status'],'접수 마감');self.assertEqual(len(new['events']),1)
        self.assertTrue(any(h['stage']=='pck_stage_link' and h['url']==detail_url(991004) for h in holds))

    def test_explicit_source_reference_advances_stage_without_copying_gp_names(self):
        link=f'<a href="{detail_url(991002)}">모집 원공고</a>'
        extra={'991004':('총회연금재단 2026 위탁운용사 최종 선정 결과 공지','2026-11-10',link+'결과 안내')}
        r,_=collect(extra=extra)
        programs,holds=publish_basic_notices({'programs':[old_program()],'institution_notices':r['notices']},[],r['checked_at'])
        self.assertFalse(holds)
        new=next(p for p in programs if p['id']!='old-pck-pe')
        self.assertEqual(new['status'],'선정 결과 발표');self.assertEqual(new['selected_gps'],[])
        self.assertEqual(len(new['events']),2)

    def test_forged_related_url_cannot_grant_lifecycle_link(self):
        r,config=collect();n=copy.deepcopy(r['notices'][0]);n['related_notice_urls']=[detail_url(991001)]
        with self.assertRaises(ValueError):boards.validate_notice(n,r['checked_at'],config)

    def test_conflicting_deadline_does_not_emit_stale_date_or_planned_schedule(self):
        r,_=collect(OFFERING.replace('접수마감 2026. 10. 29.','접수마감 2026. 10. 30.'))
        programs,holds=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],r['checked_at'])
        new=programs[0]
        self.assertNotIn('deadline',new);self.assertFalse(any(s['status']=='planned' for s in new['schedule_stages']))
        self.assertTrue(any(h['stage']=='basic_deadline' for h in holds))

    def test_short_schedule_dates_never_guess_year_from_execution_time(self):
        r,_=collect(OFFERING.replace('2026년도 하반기','2027년도 하반기'))
        n=next(n for n in r['notices'] if n['url']==detail_url(991002))
        self.assertNotIn('deadline',pck.terms(n));self.assertEqual(pck.terms(n)['planned_schedule'],[])

    def test_first_round_label_in_official_body_is_not_final_selection(self):
        self.assertEqual(pck.stage({'title':'2025 위탁운용사 선정결과 공지','body':'2025년 위탁운용사 1차(정량평가) 선정결과 공지'}),'1차 심사 결과')
        self.assertEqual(pck.stage({'title':'위탁운용사 최종 선정결과 공지','body':'이전 위탁운용사 1차(정량평가) 선정결과 참조'}),'선정 결과')

    def test_explicit_overseas_title_does_not_qualify_through_shared_template(self):
        r,_=collect();n=next(n for n in r['notices'] if n['url']==detail_url(991002))
        n['title']='해외 대체투자 위탁운용사 선정 공고'
        self.assertFalse(pck.offering_sources(n))


if __name__=='__main__':unittest.main()
