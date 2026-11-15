import unittest

from services.lp.src.lp_nps_notice_terms import pe_share


def notice(body):
    return {'institution_id': 'nps', 'url': 'https://fund.nps.or.kr/x', 'sha256': 'a' * 64, 'body': body, 'attachment_texts': {}}


class NpsPeShareTests(unittest.TestCase):
    def test_pef_section_budget_count_and_range(self):
        r = pe_share(notice('Ⅰ. 일괄심사방식 1. 선정 개요 (1) PEF 항 목 내 용 위탁운용금액 ․총 8,000억원 이내 선정운용사 수 및 배정금액 '
                            '․5개사 이내, 펀드별 800~2,000억원 범위 이내에서 자율적으로 제안 (2) 벤처펀드 항 목 내 용 위탁운용금액 ․총 1,500억원 이내'))
        self.assertEqual((r['commitment_label'], r['manager_count'], r['per_fund_range_krw']),
                         ('PE 부문 8,000억원 이내', 5, [80_000_000_000, 200_000_000_000]))

    def test_trillion_won_label(self):
        r = pe_share(notice('(1) PEF 항 목 내 용 위탁운용금액 ․총 1조원 이하 선정운용사 수 및 배정금액 ․4개사 이하, 펀드별 1,000~3,500억원'))
        self.assertEqual(r['commitment_label'], 'PE 부문 1조원 이하')

    def test_tracked_change_garbage_and_vc_only_give_nothing(self):
        self.assertEqual(pe_share(notice('(1) PEF 항 목 내 용 위탁운용금액 ․총 3,524,000억원 이하 선정운용사 수 ․346개사 이하')), {})
        self.assertEqual(pe_share(notice('(1) 벤처펀드 항 목 내 용 위탁운용금액 ․총 1,500억원 이내 4개사')), {})


if __name__ == '__main__':
    unittest.main()
