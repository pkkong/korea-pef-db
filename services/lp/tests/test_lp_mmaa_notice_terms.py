import unittest

from services.lp.src.lp_mmaa_notice_terms import pe_share


def notice(body):
    return {'institution_id': 'mmaa', 'url': 'https://www.mmaa.or.kr/x', 'sha256': 'a' * 64, 'body': body,
            'attachment_texts': {}}


class MmaaPeShareTests(unittest.TestCase):
    def test_2020_prose_layout(self):
        r = pe_share(notice('○ 위탁운용규모 : 총 1,500억원 이내 · PE 분야 : 600억원 내외 - 일반리그 : 400억원 내외(2개 내외) '
                            '- 루키리그 : 200억원 내외(1개 내외) · VC 분야 : 900억원 내외'))
        self.assertEqual((r['commitment_label'], r['manager_count'], r['amount_scope']), ('PE 부문 600억원', 3, 'pe_only'))

    def test_table_with_league_subtotals(self):
        r = pe_share(notice('구 분 계 PE VC 소계 일반리그 루키리그 소계 일반리그 루키리그 '
                            '출자규모 ( 억원 ) 2,000 1,200 1,020 180 800 720 80 운용사 ( 개 ) 22 11 9 2 11 9 2'))
        self.assertEqual((r['commitment_amount_krw'], r['manager_count']), (120_000_000_000, 11))

    def test_pe_league_equal_to_vc_subtotal_reads_the_right_columns(self):
        r = pe_share(notice('구 분 계 PE VC 소계 대형 중형 소형 소계 대형 중형 이하 '
                            '출자규모(내외) 3,900 2,700 1,200 900 600 1,200 800 400 운용사(내외) 17 9 3 3 3 8 4 4'))
        self.assertEqual((r['commitment_label'], r['manager_count']), ('PE 부문 2,700억원', 9))

    def test_simple_three_column_table(self):
        r = pe_share(notice('구 분 계 PE VC 출자 규모(내외) 4,800 3,400 1,400 운용사(내외) 20 10 10'))
        self.assertEqual((r['commitment_label'], r['manager_count']), ('PE 부문 3,400억원', 10))

    def test_columns_that_do_not_add_up_give_nothing(self):
        self.assertEqual(pe_share(notice('구 분 계 PE VC 출자 규모(내외) 4,800 3,000 1,400 운용사(내외) 20 10 10')), {})
        self.assertEqual(pe_share({**notice('구 분 계 PE VC 출자 규모(내외) 4,800 3,400 1,400 운용사'), 'institution_id': 'sema'}), {})


if __name__ == '__main__':
    unittest.main()
