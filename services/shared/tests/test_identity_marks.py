"""GP·LP identity tiles: readable labels and no squeezed wordmarks."""
from __future__ import annotations

import unittest

from services.shared.web.identity_marks import logo_is_symbol, mark_css, mark_label, mark_tone


class Labels(unittest.TestCase):
    def test_spelled_acronyms(self) -> None:
        for name, label in [
            ("엠비케이파트너스", "MBK"), ("아이엠엠프라이빗에쿼티", "IMM"), ("브이아이지파트너스", "VIG"),
            ("이앤에프프라이빗에퀴티", "E&F"), ("에이치앤큐코리아파트너스", "H&Q"), ("엔에이치투자증권", "NH"),
            ("에스케이에스프라이빗에쿼티", "SKS"), ("케이비자산운용", "KB"),
        ]:
            self.assertEqual(mark_label(name), label, name)

    def test_ordinary_syllables_are_not_acronyms(self) -> None:
        # 이지스 and 지오 are names, not E-G or G-O.
        self.assertEqual(mark_label("이지스투자파트너스"), "이지")
        self.assertEqual(mark_label("지오투자파트너스"), "지오")
        self.assertEqual(mark_label("유진프라이빗에쿼티"), "유진")

    def test_press_short_forms_and_letter_syllables(self) -> None:
        self.assertEqual(mark_label("한국투자프라이빗에쿼티"), "한투")
        self.assertEqual(mark_label("한국산업은행"), "산은")
        self.assertEqual(mark_label("케이스톤파트너스"), "케이스")
        self.assertEqual(mark_label("NH투자증권"), "NH")
        self.assertEqual(mark_label("스틱인베스트먼트"), "스틱")
        self.assertEqual(mark_label("에이스에쿼티파트너스", curated="ACE"), "ACE")

    def test_tone_is_stable_and_in_range(self) -> None:
        self.assertEqual(mark_tone("엠비케이파트너스"), mark_tone("엠비케이파트너스"))
        self.assertTrue(all(1 <= mark_tone(str(i)) <= 8 for i in range(50)))


class Logos(unittest.TestCase):
    def test_wide_wordmarks_are_not_used_as_icons(self) -> None:
        self.assertFalse(logo_is_symbol("https://a/logo.png", "31px", "7px"))
        self.assertTrue(logo_is_symbol("https://a/symbol.png", "30px", "27px"))

    def test_unsized_logos_need_an_icon_like_file(self) -> None:
        self.assertTrue(logo_is_symbol("https://a/assets/img/icon/favicon.png"))
        self.assertTrue(logo_is_symbol("https://a/img/common/ic_bm_ios.png"))
        self.assertFalse(logo_is_symbol("https://a/images/common/logo.png"))
        self.assertFalse(logo_is_symbol(""))

    def test_css_is_scoped_and_keeps_tone_after_logo_failure(self) -> None:
        css = mark_css(".lp-mark", scope=".lp-sample")
        self.assertTrue(css.startswith(".lp-sample .lp-mark{"))
        self.assertIn('.lp-sample .lp-mark.fallback-only[data-tone="1"]', css)
        self.assertNotIn("}.lp-mark", css)


if __name__ == "__main__":
    unittest.main()
