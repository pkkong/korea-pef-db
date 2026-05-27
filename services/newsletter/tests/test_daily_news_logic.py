#!/usr/bin/env python
"""Fast no-network checks for daily news clipping business rules."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
LEGACY_SCRIPTS_DIR = SERVICE_ROOT.parents[1] / "scripts"
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))

from run_daily_news_pipeline import (
    EXPORT_MIN_QUALITY_SCORE,
    coverage_window_label,
    editorial_quality,
    extract_google_news_decode_params,
    google_query_for_report_date,
    google_news_encoded_id,
    is_in_coverage_window,
    is_previous_export,
    load_previous_export_keys,
    normalize_title_key,
    parse_google_news_batch_response,
    primary_section,
    render_markdown,
    select_brief_rows,
    should_export_row,
)
from daily_news_common import (
    DEFAULT_RULES,
    load_gp_aliases,
    load_rules,
    match_gp_entities,
    normalize_url,
    score_document,
    to_iso_datetime,
)
from build_newsletter_deploy import (
    display_asset_classes,
    public_coverage_label,
    public_lp_type,
    read_lp_directory_items,
    read_lp_profile_codes,
)
from build_service_site import editorial_section
from apply_daily_news_review import normalize_category


def test_coverage_window() -> None:
    assert "2026-04-29 08:30 ~ 2026-04-30 08:30" in coverage_window_label("2026-04-30")
    assert is_in_coverage_window("2026-04-29T14:00:00+09:00", "", "2026-04-30")
    assert not is_in_coverage_window("2026-04-30T09:00:00+09:00", "", "2026-04-30")


def test_monday_coverage_window_catches_weekend() -> None:
    label = coverage_window_label("2026-05-25")
    assert "주말 포함 최근 72시간 브리핑" in label
    assert "2026-05-22 08:30 ~ 2026-05-25 08:30" in label
    assert is_in_coverage_window("2026-05-22T09:00:00+09:00", "", "2026-05-25")
    assert is_in_coverage_window("2026-05-24T23:00:00+09:00", "", "2026-05-25")
    assert not is_in_coverage_window("2026-05-22T08:00:00+09:00", "", "2026-05-25")


def test_google_backtest_window() -> None:
    query = google_query_for_report_date("사모펀드 when:1d", "2026-04-30")
    assert "after:2026-04-29" in query
    assert "before:2026-05-01" in query
    assert "when:1d" not in query


def test_google_backtest_window_catches_weekend_on_monday() -> None:
    query = google_query_for_report_date("사모펀드 when:1d", "2026-05-25")
    assert "after:2026-05-22" in query
    assert "before:2026-05-26" in query
    assert "when:1d" not in query


def test_previous_export_keys_ignore_review_candidates() -> None:
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        (out_dir / "daily_news_brief_20260522.md").write_text(
            "- [Exported Title](https://example.com/exported)\n",
            encoding="utf-8",
        )
        (out_dir / "daily_news_review_actions_20260522.csv").write_text(
            "normalized_source_url,title\nhttps://example.com/review,Review Candidate\n",
            encoding="utf-8",
        )

        previous_keys = load_previous_export_keys(out_dir, "2026-05-25")
        assert is_previous_export(
            {"source_url": "https://example.com/exported", "normalized_source_url": "", "title": "Exported Title"},
            previous_keys,
        )
        assert not is_previous_export(
            {"source_url": "https://example.com/review", "normalized_source_url": "", "title": "Review Candidate"},
            previous_keys,
        )


def test_google_news_decode_helpers() -> None:
    url = "https://news.google.com/rss/articles/abc123?oc=5"
    assert google_news_encoded_id(url) == "abc123"
    html = '<div jscontroller="x" data-n-a-id="abc123" data-n-a-ts="1779720518" data-n-a-sg="sig"></div>'
    assert extract_google_news_decode_params(html, "abc123") == ("sig", "1779720518")
    response = ")]}'\n\n" + json.dumps(
        [["wrb.fr", "Fbv4je", json.dumps(["garturlres", "https://example.com/original", 1]), None, None, None, ""]]
    )
    assert parse_google_news_batch_response(response) == "https://example.com/original"


def test_sedaily_mobile_amp_url_normalizes_to_desktop_article() -> None:
    assert normalize_url("https://m.sedaily.com/amparticle/20047971") == "https://www.sedaily.com/article/20047971"
    assert normalize_url("https://m.sedaily.com/article/2004797120047971") == "https://www.sedaily.com/article/20047971"
    assert normalize_url("https://www.sedaily.com/article/20047971?ref=naver") == "https://www.sedaily.com/article/20047971"


def test_truncated_media_suffix_does_not_split_title_duplicates() -> None:
    truncated = "대형 PEF, 롯데렌탈 눈독…공정위 기조·몸값 격차에 M&A는 안갯속[시그..."
    full = "대형 PEF, 롯데렌탈 눈독…공정위 기조·몸값 격차에 M&A는 안갯속[시그널]"
    assert normalize_title_key(truncated) == normalize_title_key(full)


def test_gp_alias_overrides_cover_common_short_names() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "gp.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
            conn.executemany(
                "INSERT INTO gp_house(gp_id, gp_name) VALUES (?, ?)",
                [
                    (7987, "어펄마캐피탈매니져스코리아"),
                    (6358, "헬리오스프라이빗에쿼티"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        aliases = load_gp_aliases(db_path)
        matches = match_gp_entities(
            "어펄마, 화성코스메틱 해외 매각 노린다",
            "헬리오스PE는 서울전선 인수 우선협상대상자로 선정됐다.",
            "",
            aliases,
        )
        names = {str(match["entity_name"]) for match in matches}
        assert "어펄마캐피탈매니져스코리아" in names
        assert "헬리오스프라이빗에쿼티" in names


def test_lp_directory_includes_seed_only_profiles() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "lp.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE v_lp_profile_summary(
                    lp_code TEXT,
                    lp_name TEXT,
                    lp_name_en TEXT,
                    lp_type TEXT,
                    ownership_type TEXT,
                    homepage_url TEXT,
                    notice_url TEXT,
                    default_team TEXT,
                    focus_asset_classes TEXT,
                    service_priority INTEGER,
                    aliases TEXT,
                    notes TEXT,
                    notice_count INTEGER,
                    allocation_amount_krw_100mn REAL,
                    commitment_amount_krw_100mn REAL,
                    latest_event_date TEXT,
                    latest_announced_date TEXT,
                    fact_count INTEGER,
                    source_count INTEGER
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO v_lp_profile_summary(
                    lp_code, lp_name, lp_type, ownership_type, homepage_url, notice_url,
                    default_team, focus_asset_classes, service_priority, notice_count,
                    allocation_amount_krw_100mn, latest_event_date, fact_count, source_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("seed", "Seed LP", "Mutual Aid", "mutual_aid", "", "", "대체투자", "PEF", 20, 0, 0, "", 0, 0),
                    ("active", "Active LP", "Public Pension", "public", "", "", "대체투자", "PEF", 10, 1, 100, "2026-05-01", 3, 2),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        assert read_lp_profile_codes(db_path) == ["seed", "active"]
        directory_codes = [str(row["lp_code"]) for row in read_lp_directory_items(db_path)]
        assert directory_codes == ["seed", "active"]


def test_lp_public_labels_do_not_expose_internal_taxonomy() -> None:
    assert public_lp_type("Policy Bank") == "정책금융기관"
    assert public_lp_type("Mutual Aid Association") == "공제회"
    assert display_asset_classes("PEF;VC;Private Credit;Real Estate;Mother Fund") == "PEF · VC · 사모대출 · 부동산 · 모태펀드"
    assert public_coverage_label(0, 0) == "자료 없음"


def test_national_growth_fund_has_dedicated_section() -> None:
    row = {
        "publisher": "딜사이트",
        "title": "[150조 국민성장펀드] 간접투자 1차 결승만 남았다",
        "summary_text": "국민성장펀드 출자사업에서 운용사 선정 절차가 진행 중이다.",
        "relevance_score": 8,
        "section_tags": "LP",
        "topic_tags": "LP,NationalGrowthFund",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://dealsite.co.kr/articles/test",
        "review_status": "auto",
    }
    assert primary_section(row) == "NationalGrowthFund"
    score, reason = editorial_quality(row)
    assert score >= EXPORT_MIN_QUALITY_SCORE, reason
    assert "[국민성장펀드]" in render_markdown("2026-05-27", [row])


def test_national_growth_fund_title_beats_ai_keyword() -> None:
    row = {
        "publisher": "뉴스톱",
        "title": "[국민성장펀드] 중소형 GP도 각축...AI·코스닥 리그 승자는?",
        "summary_text": "국민성장펀드 중소형·테마형 리그에서 AI·반도체와 코스닥 리그 경쟁이 이어진다.",
        "relevance_score": 8,
        "section_tags": "LP",
        "topic_tags": "LP,NationalGrowthFund,AI_PE",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45146",
        "review_status": "auto",
    }
    assert primary_section(row) == "NationalGrowthFund"


def test_ai_pe_keeps_priority_when_national_growth_fund_is_body_context() -> None:
    row = {
        "publisher": "이데일리",
        "title": "[GAIC 2026] AI 인프라 투자 기회 본다",
        "summary_text": "사모펀드와 LP의 AI 인프라 투자 전략을 다루며 국민성장펀드도 언급했다.",
        "relevance_score": 8,
        "section_tags": "AI & PE",
        "topic_tags": "LP,NationalGrowthFund,AI_PE",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.edaily.co.kr/News/Read?newsId=test",
        "review_status": "auto",
    }
    assert primary_section(row) == "AI_PE"


def test_web_renderer_maps_national_growth_fund_section() -> None:
    assert editorial_section(
        {
            "title": "[150조 국민성장펀드] UTC 업력에 포레스트의 패기",
            "section": "LP",
        }
    ) == "국민성장펀드"
    assert editorial_section(
        {
            "title": "[국민성장펀드] 중소형 GP도 각축...AI·코스닥 리그 승자는?",
            "section": "AI & PE",
        }
    ) == "국민성장펀드"


def test_review_category_accepts_national_growth_fund_aliases() -> None:
    assert normalize_category("국민성장펀드") == "NationalGrowthFund"
    assert normalize_category("National Growth Fund") == "NationalGrowthFund"
    assert normalize_category("NGF") == "NationalGrowthFund"


def test_weak_context_quality_penalty() -> None:
    weak_row = {
        "publisher": "더벨",
        "title": "[더벨]우리증권, 장외파생 인가 TF 가동…종합 IB '마지막 퍼즐'",
        "summary_text": "복합적인 금융 수요를 가진 대기업과 사모펀드 고객을 유인할 수 있다.",
        "relevance_score": 9,
        "section_tags": "Market",
        "topic_tags": "PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=test",
        "review_status": "auto",
    }
    score, reason = editorial_quality(weak_row)
    assert score < EXPORT_MIN_QUALITY_SCORE, reason


def test_strong_headline_quality() -> None:
    strong_row = {
        "publisher": "더벨",
        "title": "[더벨]방산기술혁신펀드 GP에 이앤인베·에임인베 선정",
        "summary_text": "성장금융 출자사업을 통해 GP를 선정했다.",
        "relevance_score": 8,
        "section_tags": "LP",
        "topic_tags": "LP,PEF",
        "document_type_tags": "",
        "gp_names": "에임인베스트먼트",
        "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=test",
        "review_status": "auto",
    }
    score, reason = editorial_quality(strong_row)
    assert score >= EXPORT_MIN_QUALITY_SCORE, reason


def test_allocator_section_priority() -> None:
    row = {
        "publisher": "더벨",
        "title": "국민연금, PEF 위탁운용사 선정 착수",
        "summary_text": "대체투자 출자사업과 커밋먼트 확대가 핵심이다.",
        "relevance_score": 8,
        "section_tags": "",
        "topic_tags": "LP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=test",
        "review_status": "auto",
    }
    assert primary_section(row) == "LP"
    score, reason = editorial_quality(row)
    assert score >= EXPORT_MIN_QUALITY_SCORE, reason


def test_gp_fundraising_and_deal_financing_sections() -> None:
    fundraising_row = {
        "publisher": "딜사이트",
        "title": "국내 PEF, 1차 클로징으로 블라인드펀드 결성",
        "summary_text": "약정총액과 앵커 출자가 관건이다.",
        "relevance_score": 7,
        "section_tags": "",
        "topic_tags": "Fundraising,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://dealsite.co.kr/articles/test",
        "review_status": "auto",
    }
    credit_row = {
        "publisher": "연합인포맥스",
        "title": "프라이빗크레딧 펀드, 인수금융 리파이낸싱 확대",
        "summary_text": "PEF 포트폴리오 차입 구조가 바뀌고 있다.",
        "relevance_score": 7,
        "section_tags": "",
        "topic_tags": "Credit,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://news.einfomax.co.kr/news/articleView.html?idxno=test",
        "review_status": "auto",
    }
    assert primary_section(fundraising_row) == "GP"
    assert primary_section(credit_row) == "Deal"


def test_ai_pe_section_priority() -> None:
    row = {
        "publisher": "더벨",
        "title": "PEF, AI 데이터센터 투자 검토",
        "summary_text": "AI 인프라 투자 thesis가 사모펀드 운용 전략으로 부상했다.",
        "relevance_score": 8,
        "section_tags": "",
        "topic_tags": "Deal,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=test",
        "review_status": "auto",
    }
    assert primary_section(row) == "AI_PE"


def test_ai_pe_reserved_in_brief_selection() -> None:
    rows = [
        {
            "news_id": 1,
            "publisher": "더벨",
            "title": "MBK, 대형 포트폴리오 매각 추진",
            "summary_text": "사모펀드 딜 기사",
            "relevance_score": 12,
            "quality_score": 15,
            "section_tags": "Deal",
            "topic_tags": "Deal,PEF",
            "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=deal",
            "normalized_source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=deal",
        },
        {
            "news_id": 2,
            "publisher": "이데일리",
            "title": "[GAIC 2026] AI 피해입는 기업, 사모펀드엔 인수 기회",
            "summary_text": "AI 시대 private equity 투자전략 기사",
            "relevance_score": 8,
            "quality_score": 10,
            "section_tags": "AI_PE",
            "topic_tags": "AI_PE,PEF",
            "source_url": "https://www.edaily.co.kr/News/Read?newsId=test",
            "normalized_source_url": "https://www.edaily.co.kr/News/Read?newsId=test",
        },
    ]
    selected = select_brief_rows(rows, 1)
    assert selected[0]["source_url"].startswith("https://www.edaily.co.kr/")


def test_lp_and_gp_reserved_in_full_brief_selection() -> None:
    rows = []
    for index in range(8):
        rows.append(
            {
                "news_id": index,
                "publisher": "더벨",
                "title": f"대형 PEF 포트폴리오 매각 추진 {index}",
                "summary_text": "사모펀드 딜 기사",
                "relevance_score": 12 - index * 0.1,
                "quality_score": 20 - index * 0.1,
                "section_tags": "Deal",
                "topic_tags": "Deal,PEF",
                "source_url": f"https://www.thebell.co.kr/free/content/ArticleView.asp?key=deal{index}",
                "normalized_source_url": f"https://www.thebell.co.kr/free/content/ArticleView.asp?key=deal{index}",
            }
        )
    rows.extend(
        [
            {
                "news_id": 20,
                "publisher": "경기신문",
                "title": "중소기업중앙회 자산운용본부장 공개 모집",
                "summary_text": "공제사업 자산운용 조직 기사",
                "relevance_score": 6,
                "quality_score": 12,
                "section_tags": "LP",
                "topic_tags": "LP",
                "source_url": "https://www.kgnews.co.kr/news/article.html?no=test",
                "normalized_source_url": "https://www.kgnews.co.kr/news/article.html?no=test",
            },
            {
                "news_id": 21,
                "publisher": "블로터",
                "title": "연기금 대체투자 자산배분 확대",
                "summary_text": "LP allocator 기사",
                "relevance_score": 6,
                "quality_score": 11,
                "section_tags": "LP",
                "topic_tags": "LP",
                "source_url": "https://www.bloter.net/news/articleView.html?idxno=test",
                "normalized_source_url": "https://www.bloter.net/news/articleView.html?idxno=test",
            },
            {
                "news_id": 30,
                "publisher": "뉴스톱",
                "title": "코엔텍 회수한 E&F PE, 연내 3000억 펀드 도전",
                "summary_text": "블라인드펀드 조성 기사",
                "relevance_score": 6,
                "quality_score": 13,
                "section_tags": "GP",
                "topic_tags": "GP",
                "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=test",
                "normalized_source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=test",
            },
            {
                "news_id": 31,
                "publisher": "더벨",
                "title": "이지스운용, 코벤펀드 소진 속속 모집",
                "summary_text": "펀드 모집 기사",
                "relevance_score": 6,
                "quality_score": 12.5,
                "section_tags": "GP",
                "topic_tags": "GP",
                "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=gp",
                "normalized_source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=gp",
            },
        ]
    )
    selected = select_brief_rows(rows, 8)
    sections = [primary_section(row) for row in selected]
    assert sections.count("LP") == 2
    assert sections.count("GP") == 2


def test_gp_fundraising_beats_deal_word_when_title_is_fund_build() -> None:
    row = {
        "publisher": "뉴스톱",
        "title": "코엔텍 회수한 E&F PE, 연내 3000억 펀드 도전",
        "summary_text": "블라인드펀드 조성과 펀드레이징을 추진한다.",
        "relevance_score": 9,
        "section_tags": "GP",
        "topic_tags": "GP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45098",
        "review_status": "auto",
    }
    assert primary_section(row) == "GP"


def test_company_clipping_keyword_gaps_are_scored() -> None:
    rules = load_rules(DEFAULT_RULES)
    cases = [
        ("헬리오스PE, 서울전선 인수 우선협상대상자로 선정", 7, "GP"),
        ("방산 수혜 '엠앤씨솔루션', SPA 체결 임박", 3, "Deal"),
        ("신생 PE 페트리코, 카카오게임즈 빅딜 소싱 배경은", 4, "GP"),
        ("[150조 국민성장펀드] 그로쓰 투자 대가 도미누스", 3, "LP"),
        ("행정공제회 신임 이사장에 김기영 전 충남 행정부지사", 4, "LP"),
        ("KCGI자산운용, AUM 6조원 돌파", 3, "GP"),
    ]
    for title, minimum_score, expected_topic in cases:
        result = score_document(title, "", "", rules, [])
        topics = {str(tag["tag_value"]) for tag in result["tags"] if str(tag["tag_type"]) == "topic"}
        assert result["score"] >= minimum_score, title
        assert expected_topic in topics, title

    etf_lp = score_document("금감원, 증권사 ETF LP '선행매매' 정조준", "", "", rules, [])
    assert etf_lp["score"] < 0


def test_dot_datetime_to_iso() -> None:
    assert to_iso_datetime("2026.05.21 14:58:33") == "2026-05-21T14:58:33+09:00"


def test_google_news_redirect_not_auto_exported() -> None:
    row = {
        "review_status": "auto",
        "source_url": "https://news.google.com/rss/articles/example",
        "quality_score": 99,
    }
    assert not should_export_row(row)
    row["review_status"] = "force_include"
    assert should_export_row(row)


def test_render_markdown_coverage() -> None:
    text = render_markdown("2026-04-30", [])
    assert "기준 : 최근 24시간 브리핑" in text
    assert "2026-04-29 08:30 ~ 2026-04-30 08:30" in text


def main() -> int:
    tests = [
        test_coverage_window,
        test_monday_coverage_window_catches_weekend,
        test_google_backtest_window,
        test_google_backtest_window_catches_weekend_on_monday,
        test_previous_export_keys_ignore_review_candidates,
        test_google_news_decode_helpers,
        test_sedaily_mobile_amp_url_normalizes_to_desktop_article,
        test_truncated_media_suffix_does_not_split_title_duplicates,
        test_gp_alias_overrides_cover_common_short_names,
        test_lp_directory_includes_seed_only_profiles,
        test_lp_public_labels_do_not_expose_internal_taxonomy,
        test_national_growth_fund_has_dedicated_section,
        test_national_growth_fund_title_beats_ai_keyword,
        test_ai_pe_keeps_priority_when_national_growth_fund_is_body_context,
        test_web_renderer_maps_national_growth_fund_section,
        test_review_category_accepts_national_growth_fund_aliases,
        test_weak_context_quality_penalty,
        test_strong_headline_quality,
        test_allocator_section_priority,
        test_gp_fundraising_and_deal_financing_sections,
        test_ai_pe_section_priority,
        test_ai_pe_reserved_in_brief_selection,
        test_lp_and_gp_reserved_in_full_brief_selection,
        test_gp_fundraising_beats_deal_word_when_title_is_fund_build,
        test_company_clipping_keyword_gaps_are_scored,
        test_dot_datetime_to_iso,
        test_google_news_redirect_not_auto_exported,
        test_render_markdown_coverage,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
