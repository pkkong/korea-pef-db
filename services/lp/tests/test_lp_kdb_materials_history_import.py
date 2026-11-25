"""Keep the KDB press board and the sourced joint fund boundaries explicit."""

import json
from urllib.parse import parse_qs, urlsplit

from services.lp.src import lp_board_adapters_banks as banks
from services.lp.src import lp_kdb_materials_history_import as materials


def test_press_board_does_not_replace_the_regular_kdb_notices():
    default = {'institution_id': 'kdb'}
    press = {**default, 'listing_url': banks.KDB_PRESS_BOARD}
    press_listing = banks.listing_requests(press)[0]
    request = json.loads(parse_qs(urlsplit(press_listing['url']).query)['_JSON_'][0])
    assert request['ITR_BLB_ID'] == 'SMR024'
    assert press_listing['referer'] == banks.KDB_PRESS_BOARD
    body = json.dumps({
        'ITR_BLB_ID': 'SMR024', 'COMMON_HEAD': {'ERROR': False}, 'HEADER_STD_WEB': {'TOT_PAG_ROW_CNT': 1},
        'STDLIST_REC': [{'ITR_NAC_ID_MNG_SNO': '123456', 'FST_ENR_DTM': '20210521175717',
                        'NAC_CONE_TTL': '소재·부품·장비 블라인드 펀드(2차) 운용사 최종 선정'}]})
    notice, = banks.parse_listing(body, press_listing['url'], press)
    assert materials.source_key(notice['url']) == ('kdb_press', '123456')
    assert materials.source_key(banks._kdb_detail_url('123456')) is None
    for url, config in ((press_listing['url'], default), (banks.listing_requests(default)[0]['url'], default)):
        try:
            banks.parse_listing(body, url, config)
        except ValueError:
            pass
        else:
            raise AssertionError('KDB press evidence entered the ordinary notice board')


def test_team_rosters_match_across_reports_with_one_row_per_co_gp():
    reports = {
        '접수 결과': ('별첨 선정 접수 현황\n일반\n소부장\n3개사\n( 2개사 )\n'
                    '유안타인베스트먼트\n킹고투자파트너스, 한국투자파트너스\n신영증권\n'
                    '반도체\n소부장\n1개사\n( 1개사 )\n미래에셋벤처투자, 위벤처스'),
        '1차 심사 결과': ('운용사 (가나다순)\n유안타인베스트먼트\n미래에셋벤처투자 &\n위벤처스\n'
                     '한국투자파트너스 &\n킹고투자파트너스\n□ 산은은 이후 절차를 진행합니다'),
        '선정 결과': ('< 최종 선정 운용사 명단 >\n지원분야\n운용사 (가나다순)\n일반\n소부장\n'
                  '유안타인베스트먼트\n한국투자파트너스 / 킹고투자파트너스\n반도체\n소부장\n미래에셋벤처투자 / 위벤처스'),
    }
    applied, screened, selected = materials._teams_by_league(reports)
    assert [list(map(len, x.values())) for x in (applied, screened, selected)] == [[3, 1], [2, 1], [2, 1]]
    assert selected['일반'][-1] == ('한국투자파트너스', '킹고투자파트너스')
    assert selected['반도체'][0] == ('미래에셋벤처투자', '위벤처스')
    for event, alteration in (
        ('1차 심사 결과', reports['1차 심사 결과'].replace('위벤처스', '신영증권')),
        ('선정 결과', reports['선정 결과'].replace('유안타인베스트먼트', '신영증권')),
        ('선정 결과', reports['선정 결과'].replace('반도체\n소부장', '프로젝트\n소부장')),
    ):
        try:
            materials._teams_by_league({**reports, event: alteration})
        except ValueError:
            pass
        else:
            raise AssertionError('An unrelated roster entered the KDB blind fund')
