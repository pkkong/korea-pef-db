"""Two MOEL funds share one board; title and source receipts must isolate them."""
import unittest
from urllib.parse import urlencode

from services.lp.src import lp_board_adapter_moel as moel


EIF = '2026년 고용보험기금 대체투자상품(PEF, VC) 선정 공고'
IACI = '2026년 산재보험기금 대체투자상품(PEF, VC) 선정 공고'
ROOT = 'https://www.moel.go.kr'
BOARD = ROOT + moel.LIST_PATH
EIF_ID = '20260800274'
IACI_ID = '20260700049'


def config(institution):
    return {'institution_id': institution, 'listing_url': BOARD}


def row(ident, title, stamp):
    return (f'<tr><td aria-label="번호">181</td><td aria-label="제목"><strong class="b_tit">'
            f'<a href="{moel.DETAIL_PATH}?bbs_seq={ident}" '
            f'onclick="scEventListener.fnView(\'{ident}\');return false;">{title}</a></strong></td>'
            f'<td aria-label="담당부서">자산운용팀</td><td>첨부파일 있음</td>'
            f'<td aria-label="등록일">{stamp}</td><td aria-label="조회">20</td></tr>')


def listing(*, page=1, last=1, title_search='', rows=None):
    rows = rows if rows is not None else [row(EIF_ID, EIF, '2026.08.07'), row(IACI_ID, IACI, '2026.07.01')]
    selected_all = '' if title_search else ' selected'
    selected_title = ' selected' if title_search else ''
    return ('<html><form id="frm" name="frm" action="'+moel.LIST_PATH+'" method="post">'
            f'<input type="hidden" name="pageIndex" value="{page}">'
            '<select name="searchField"><option value="4"'+selected_all+'>전체</option>'
            '<option value="1"'+selected_title+'>제목</option></select>'
            f'<input name="searchText" value="{title_search}">'
            f'<span class="total">전체 <b>{len(rows)}</b></span>'
            '<table class="tstyle_list"><thead><tr>'
            + ''.join('<th>'+label+'</th>' for label in moel.HEADERS)
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
            f'<div class="board_pager"><a title="현재 페이지" class="active">{page}</a>'
            f'<a class="arr last" href="?pageIndex={last}">마지막</a></div>'
            f'<span class="page-total">/ {last}</span></form></html>')


def detail(ident=EIF_ID, title=EIF, *, body=None, files=True):
    body = body or ('2026년 고용보험기금 대체투자상품 선정 계획을 공고합니다. '
                    '선정 유형: 블라인드 PEF, VC. PEF 600억원 2건, VC 600억원 3건.')
    def file_link(seq, name):
        params = urlencode({'file_seq':seq,'bbs_seq':ident,'bbs_id':'27','file_ext':'hwpx'})
        return f'<li><em>{name}</em><a href="{moel.FILE_PATH}?{params}">다운로드</a></li>'
    attachments = (file_link('20260800467','1. (공고) 고용보험기금 대체투자상품(PEF, VC) 선정 공고문.hwpx')
                   + file_link('20260800468','2. 고용보험기금 제안요청서(RFP)_PEF.hwpx')
                   + file_link('20260800470','4. 고용보험기금 제안요청서(RFP)_VC.hwpx')
                   if files else '')
    return ('<html><div class="board_view_wrap"><dl><dt>제목</dt><dd>'+title+'</dd>'
            '<dt>등록일</dt><dd>2026.08.07</dd></dl><div class="board_view_con">'
            +body+'</div><ul>'+attachments+'</ul></div></html>')


class MoelBoardTests(unittest.TestCase):
    def test_cached_listing_shape_assigns_only_explicit_fund(self):
        html = listing()
        for institution in ('moel_eif', 'moel_iaci'):
            rows = moel.parse_listing(html, BOARD+'?pageIndex=1', config(institution))
            self.assertEqual([(r['source_id'], r['institution_id'], r['title']) for r in rows], [
                ('moel_eif:'+EIF_ID, 'moel_eif', EIF),
                ('moel_iaci:'+IACI_ID, 'moel_iaci', IACI)])
            self.assertEqual(moel.last_page(html, BOARD+'?pageIndex=1', config(institution)), 1)

    def test_other_fund_and_unassigned_rows_remain_for_page_boundary(self):
        html = listing(rows=[row(IACI_ID, IACI, '2026.07.01'),
                             row('20260400043', '고용보험기금 자산운용규정', '2026.04.01'),
                             row('20260300001', '기금 운용현황', '2026.03.01')])
        rows = moel.parse_listing(html, BOARD+'?pageIndex=1', config('moel_eif'))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['institution_id'] for r in rows], ['moel_iaci', 'moel_eif', None])
        self.assertEqual(rows[2]['source_id'], 'moel_board:20260300001')
        self.assertEqual([r['date'] for r in rows], ['2026-07-01', '2026-04-01', '2026-03-01'])

    def test_mismatched_board_page_script_or_issuer_fails_closed(self):
        html = listing()
        bad_urls = [BOARD.replace('imchaeBbsList','imchaeBbsView')+'?pageIndex=1',
                    BOARD+'?pageIndex=2', BOARD+'?pageIndex=1&pageIndex=2',
                    BOARD+'?pageIndex=1&searchField=4&searchText=PEF']
        for url in bad_urls:
            with self.assertRaises(ValueError): moel.parse_listing(html, url, config('moel_eif'))
        with self.assertRaises(ValueError):
            moel.parse_listing(html.replace("fnView('20260800274')", "fnView('20260700049')"),
                               BOARD+'?pageIndex=1', config('moel_eif'))
        with self.assertRaises(ValueError):
            moel.parse_listing(listing(rows=[row(EIF_ID,'고용보험기금 및 산재보험기금 공동 공고','2026.08.07')]),
                               BOARD+'?pageIndex=1', config('moel_eif'))

    def test_title_search_and_pager_echo(self):
        url = BOARD+'?pageIndex=1&searchField=1&searchText=고용보험기금'
        html = listing(title_search='고용보험기금', rows=[row(EIF_ID, EIF, '2026.08.07')])
        self.assertEqual(len(moel.parse_listing(html, url, config('moel_eif'))),1)
        for bad in [html.replace('value="고용보험기금"','value="산재보험기금"'),
                    html.replace('href="?pageIndex=1"','href="?pageIndex=2"'),
                    html.replace('/ 1</span>','/ 2</span>')]:
            with self.assertRaises(ValueError):moel.last_page(bad,url,config('moel_eif'))

    def test_detail_keeps_pe_source_documents_and_rejects_cross_fund_files(self):
        url = ROOT + moel.DETAIL_PATH + '?bbs_seq=' + EIF_ID
        record = moel.parse_detail(detail(), url, config('moel_eif'))
        self.assertEqual(record['source_id'],'moel_eif:'+EIF_ID)
        self.assertEqual(record['date'],'2026-08-07')
        self.assertEqual(len(record['attachments']),2)
        self.assertTrue(all('_VC' not in a['name'] for a in record['attachments']))
        with self.assertRaises(ValueError):moel.parse_detail(detail(title=IACI),url,config('moel_eif'))
        with self.assertRaises(ValueError):
            moel.parse_detail(detail().replace('bbs_seq='+EIF_ID,'bbs_seq='+IACI_ID),url,config('moel_eif'))

    def test_blind_pe_is_offering_evidence_not_legal_or_past_experience(self):
        self.assertTrue(moel.has_pe_blind_offering('선정 유형: 블라인드 PEF, VC. PEF 출자액 확인 전.'))
        self.assertTrue(moel.has_pe_blind_offering('투자 유형: 블라인드 PEF 및 VC.'))
        self.assertFalse(moel.has_pe_blind_offering('PEF 운용경력 3년. 기관전용 사모집합투자기구에 해당'))
        self.assertFalse(moel.has_pe_blind_offering('선정 유형 VC, 과거 운용한 블라인드 PEF 경력'))
        self.assertFalse(moel.has_pe_blind_offering('투자 유형: PEF 및 VC.'))


if __name__ == '__main__':
    unittest.main()
