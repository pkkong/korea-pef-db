"""Keep the regional and rookie tracks separate in the official 2022 New Deal round."""

from services.lp.src import lp_enterprise_newdeal_2022 as enterprise


def test_stage_requires_the_second_enterprise_round():
    title = '【성장금융】「혁신성장뉴딜펀드」2022년 2차(기업투자) 위탁운용사 선정 결과'
    assert enterprise._stage(title) == '선정 결과'
    for altered in (title.replace('2차', '1차'), title.replace('기업투자', '인프라투자')):
        try:
            enterprise._stage(altered)
        except ValueError:
            pass
        else:
            raise AssertionError('A different round or fund type entered the enterprise program')


def test_2022_result_tracks_require_the_same_teams_in_recruitment_stages():
    plan = {'count': 1, 'per_fund': 400, 'other_count': 1, 'other_size': 350}
    texts = {
        '접수 결과': {
            'hwp': '지역혁신\n(1)\n400\n3\n가투자-나투자\n다투자\n라투자\n혁신루키\n(1)\n350\n2\n마투자\n바투자',
            'pdf': '지역혁신 (1) 400 3 가투자-나투자 다투자 라투자\n혁신루키 (1) 350 2 마투자 바투자',
        },
        '1차 심사 결과': {'hwp': '지역혁신\n(1)\n400\n가투자-나투자\n다투자\n혁신루키\n(1)\n350\n마투자'},
    }
    selected = '지원분야\n운용사\n지역혁신\n가투자-나투자\n혁신루키\n마투자\n○ 주관기관'
    assert enterprise._rosters(texts, selected, plan) == [
        ['가투자-나투자', '다투자', '라투자'], ['가투자-나투자', '다투자'], ['가투자-나투자'],
    ]
    alternatives = (
        (texts, selected.replace('가투자-나투자', '마투자')),
        (texts, selected.replace('가투자-나투자', '가투자')),
        (texts, selected.replace('가투자-나투자', '라투자')),
        ({**texts, '접수 결과': {**texts['접수 결과'], 'pdf': texts['접수 결과']['pdf'].replace('라투자', '마투자')}}, selected),
    )
    for documents, result in alternatives:
        try:
            enterprise._rosters(documents, result, plan)
        except ValueError:
            pass
        else:
            raise AssertionError('A mismatched team crossed a stage or track boundary')
