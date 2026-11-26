"""Joint New Deal notices must agree by league and by team."""

import unittest

from services.lp.src import lp_kdb_policy_newdeal_first_2022 as policy


class PolicyFirstRostersTests(unittest.TestCase):
    def test_final_teams_keep_their_league_and_the_joint_members(self):
        tracks = {'중형': {'amount': 640, 'target': 1600, 'per_fund': 1600, 'count': 1},
                  '대형': {'amount': 1050, 'target': 3500, 'per_fund': 3500, 'count': 1}}
        texts = {
            'applications': ('지원 운용사 명 (가나다순)\n소형\n금강벤처스\n'
                             '중형\n(1)\n1,600\n(총 1,600)\n2\n(총 3,200)\n가람증권/나래파트너스\n마루투자\n'
                             '대형\n(1)\n3,500\n(총 3,500)\n2\n(총 7,000)\n누리캐피탈\n새롬투자\n* 주석'),
            'screening': ('중형 640 1,600 1 2 1 산은\n대형 1,050 3,500 1 2 1 산은\n'
                          '지원 운용사 명(가나다순)\n소형\n금강벤처스\n'
                          '중형\n(1)\n1,600\n가람증권/나래파트너스\n대형\n(1)\n3,500\n누리캐피탈\n* 주석'),
            'selection': ('중형(1,600) 1,600 640 960 2 1 산은\n대형(3,500) 3,500 1,050 2,450 2 1\n'
                          '운용사 명(가나다순)\n소형\n금강벤처스\n중형\n1,600억원\n가람증권/나래파트너스*\n'
                          '대형\n3,500억원\n누리캐피탈\n* 탄소중립 우선 선정'),
        }
        parsed = policy._rosters(texts, tracks)
        self.assertEqual(parsed['중형'][-1], [('가람증권', '나래파트너스')])
        self.assertEqual(parsed['대형'][-1], [('누리캐피탈',)])
        for changed in (
            texts['selection'].replace('가람증권/나래파트너스*', '누리캐피탈'),
            texts['selection'].replace('가람증권/나래파트너스*', '가람증권'),
            texts['selection'].replace('가람증권/나래파트너스*', '마루투자'),
            texts['selection'].replace('640 960', '639 961'),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                policy._rosters({**texts, 'selection': changed}, tracks)
