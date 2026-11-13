"""Brief GP·LP display tags: precision and failure isolation."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.newsletter.src import newsletter_entity_tags as tags


def card(name: str, gp_id: str = "", active: bool = True) -> str:
    return (
        f'<article class="gp-card"\n        data-url="{f"gp-{gp_id}.html" if gp_id else ""}"\n'
        f'        data-profile="{"detail" if gp_id else ""}"\n        data-active="{1 if active else 0}"\n'
        f'        data-period-metrics="{{&quot;2025Q4&quot;:{{&quot;funds&quot;:1}}}}"\n        data-name="{name}">\n'
        f"        <h2>{name}</h2></article>"
    )


DIRECTORY = "".join(
    [
        card("엠비케이파트너스", "2"),
        card("어펄마캐피탈", "7361"),
        card("제네시스프라이빗에쿼티"),
        card("이앤에프프라이빗에퀴티", "291"),
        card("NH투자증권", "44"),
        card("키움증권"),
        card("산은캐피탈"),
        card("티스톤"),
        card("메티스톤에퀴티파트너스"),
        card("중소기업은행", "26"),
        card("에스케이에너지", active=False),
        card("에이치앤큐코리아파트너스", active=False),
        card("뉴젠인베스트먼트"),
        card("디인베스트먼트"),
    ]
)


def catalog(gp_html: str = DIRECTORY) -> tags.TagCatalog:
    return tags.load_catalog(fetch_gp_html=lambda: gp_html)


class TagPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = catalog()

    def tag(self, title: str, summary: str = "") -> dict[str, list[str]]:
        return tags.tag_text(title, summary, self.catalog)

    def test_both_sources_load(self) -> None:
        self.assertTrue(self.catalog.available("GP"))
        self.assertTrue(self.catalog.available("LP"))

    def test_press_forms_of_managers(self) -> None:
        self.assertEqual(self.tag("최윤범 법원서 막혀", "사모펀드 운용사 MBK파트너스가 사과를 요구했다.")["gpNames"], ["엠비케이파트너스"])
        self.assertEqual(self.tag("제네시스PE, 크레딧 법인 세운다")["gpNames"], ["제네시스프라이빗에쿼티"])
        self.assertEqual(self.tag("E&F PE-IS동서 코어엔텍 매각 재개", "E&F프라이빗에쿼티 컨소시엄")["gpNames"], ["이앤에프프라이빗에퀴티"])
        # A reviewed alias may point at a directory card that is no longer active.
        self.assertEqual(self.tag("H&Q·헬리오스, 큐럭스 투자")["gpNames"], ["에이치앤큐코리아파트너스"])

    def test_investment_shorthand(self) -> None:
        self.assertEqual(self.tag("뉴젠인베, 제이앤티지 엑시트")["gpNames"], ["뉴젠인베스트먼트"])
        # A one-syllable stem (디인베) is too vague to tag.
        self.assertEqual(self.tag("디인베·IMM인베, 투자 연기")["gpNames"], [])

    def test_reviewed_alias_reaches_shorter_directory_name(self) -> None:
        result = self.tag("총회연금 GP, 크레센도·어펄마 낙점", "총회연금재단이 위탁운용사(GP) 선정을 마무리했다.")
        self.assertEqual(result["gpNames"], ["어펄마캐피탈"])
        self.assertEqual(result["lpNames"], ["총회연금재단"])

    def test_institutions_are_lp_not_gp(self) -> None:
        result = self.tag("노앤파트너스, 과기공·수은 연속 선정", "중소기업은행 출자사업에서도 선정됐다.")
        self.assertEqual(result["lpNames"], ["과학기술인공제회", "한국수출입은행", "IBK기업은행"])
        self.assertNotIn("중소기업은행", result["gpNames"])

    def test_securities_firm_needs_pe_word_next_to_it(self) -> None:
        self.assertEqual(self.tag("NH투자증권 PE본부, 2호 블라인드 결성")["gpNames"], ["NH투자증권"])
        self.assertEqual(self.tag("'증권대상'에 키움증권", "키움증권이 증권사 부문 대상을 받았다. 사모펀드 시장은 위축")["gpNames"], [])

    def test_short_names_need_word_boundaries(self) -> None:
        result = self.tag("산은캐피탈, 신규 펀드 결성…자산은 2조", "운용 자산은 2조원")
        self.assertEqual(result["gpNames"], ["산은캐피탈"])
        self.assertEqual(result["lpNames"], [])
        self.assertEqual(self.tag("산은이 남부권 운용사 선정")["lpNames"], ["한국산업은행"])
        self.assertEqual(self.tag("캠코는 구조조정 펀드를 늘린다")["lpNames"], ["한국자산관리공사"])
        # 티스톤 inside 메티스톤에퀴티파트너스 is not 티스톤.
        self.assertEqual(self.tag("메티스톤에퀴티파트너스, 4호 결성")["gpNames"], ["메티스톤에퀴티파트너스"])

    def test_former_employer_is_not_tagged(self) -> None:
        self.assertEqual(self.tag("전 MBK파트너스 부사장이 세운 고도파트너스", "MBK파트너스 출신이 설립했다.")["gpNames"], [])

    def test_generic_words_and_dissolved_houses_are_not_tags(self) -> None:
        self.assertEqual(self.tag("모태펀드 예산 늘어", "국부펀드들이 AI에 투자한다")["lpNames"], [])
        self.assertEqual(self.tag("SK에너지 정제마진 개선", "에스케이에너지 실적")["gpNames"], [])
        self.assertEqual(self.tag("한국모태펀드 2차 정시")["lpNames"], ["한국벤처투자"])

    def test_order_follows_first_mention_and_caps(self) -> None:
        result = self.tag("어펄마 7호 펀딩", "과학기술인공제회와 군인공제회, 중소기업중앙회, 행정공제회 등")
        self.assertEqual(result["lpNames"], ["과학기술인공제회", "군인공제회", "중소기업중앙회"])


class FailureIsolation(unittest.TestCase):
    """One source failing must never block the Brief or the other kind of tag."""

    entry = [{"reportDate": "2026-11-13", "articles": [
        {"url": "https://a/1", "title": "MBK파트너스, 국민연금 출자 확보", "summaryText": "", "gpNames": [], "lpNames": []},
    ]}]
    previous = [{"reportDate": "2026-11-13", "articles": [
        {"url": "https://a/1", "title": "", "gpNames": ["엠비케이파트너스"], "lpNames": ["옛 LP"]},
    ]}]

    def test_gp_source_down_keeps_previous_gp_tags_and_still_tags_lp(self) -> None:
        def down() -> str:
            raise OSError("supabase down")

        broken = tags.load_catalog(fetch_gp_html=down)
        self.assertEqual(broken.status["GP"], "unavailable:OSError")
        self.assertTrue(broken.available("LP"))
        tagged, report = tags.tag_archive_entries(self.entry, broken, self.previous)
        article = tagged[0]["articles"][0]
        self.assertEqual(article["gpNames"], ["엠비케이파트너스"])
        self.assertEqual(article["lpNames"], ["국민연금기금"])
        self.assertEqual(report["status"]["GP"], "unavailable:OSError")

    def test_lp_master_missing_still_tags_gp(self) -> None:
        broken = tags.load_catalog(fetch_gp_html=lambda: DIRECTORY, lp_institutions=Path("/nonexistent.csv"))
        self.assertFalse(broken.available("LP"))
        tagged, _ = tags.tag_archive_entries(self.entry, broken, self.previous)
        article = tagged[0]["articles"][0]
        self.assertEqual(article["gpNames"], ["엠비케이파트너스"])
        self.assertEqual(article["lpNames"], ["옛 LP"])

    def test_empty_directory_counts_as_unavailable(self) -> None:
        self.assertFalse(tags.load_catalog(fetch_gp_html=lambda: "<html></html>").available("GP"))

    def test_no_credentials_means_no_network_call(self) -> None:
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": "", "SUPABASE_ANON_KEY": ""}), \
                mock.patch.object(tags, "urlopen") as opener:
            result = tags.load_catalog()
        opener.assert_not_called()
        self.assertEqual(result.status["GP"], "unavailable:no_credentials")

    def test_unexpected_error_returns_archive_unchanged(self) -> None:
        bad = tags.TagCatalog(aliases=[object()], status={"GP": "ok:1", "LP": "ok:1"})  # type: ignore[list-item]
        with mock.patch("builtins.print"):
            self.assertIs(tags.apply_display_tags(self.entry, self.previous, catalog=bad), self.entry)

    def test_renderer_publishes_with_tags_even_when_gp_is_down(self) -> None:
        from services.newsletter.src import newsletter_renderer

        def down() -> str:
            raise OSError("down")

        broken = tags.load_catalog(fetch_gp_html=down)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(tags, "_CATALOG", broken), mock.patch("builtins.print"):
            public, out = Path(folder) / "site", Path(folder) / "out"
            public.mkdir()
            out.mkdir()
            newsletter_renderer.rewrite_newsletter_archive(public, out, "2026-11-13", self.previous[:0] + self.entry)
            archive = (public / "archive.json").read_text(encoding="utf-8")
        self.assertIn("국민연금기금", archive)


if __name__ == "__main__":
    unittest.main()
