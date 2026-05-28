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
    event_dedupe_key,
    display_url,
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
    select_review_rows,
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
    filter_service_context_profile_links,
    public_coverage_label,
    public_lp_type,
    read_lp_directory_items,
    read_lp_alias_patterns,
    read_lp_profile_codes,
)
from build_service_site import editorial_section
from build_service_site import article_payload_rows
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


def test_dealsite_category_suffix_url_normalizes_to_article() -> None:
    assert normalize_url("https://dealsite.co.kr/articles/162589/075023") == "https://dealsite.co.kr/articles/162589"
    assert normalize_url("https://www.dealsite.co.kr/articles/162589") == "https://dealsite.co.kr/articles/162589"


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
                    (44, "아이엠엠인베스트먼트"),
                    (45, "도미누스인베스트먼트"),
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

        imm_matches = match_gp_entities(
            "KIC 첫 국내 출자 펀드, 내달 베일 벗는다",
            "KIC는 IMM인베스트먼트와 도미누스인베스트먼트와 손잡고 펀드 조성을 완료할 예정이다.",
            "",
            aliases,
        )
        imm_names = {str(match["entity_name"]) for match in imm_matches}
        assert "아이엠엠인베스트먼트" in imm_names
        assert "도미누스인베스트먼트" in imm_names


def test_lp_directory_includes_seed_only_profiles_without_empty_profile_pages() -> None:
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

        assert read_lp_profile_codes(db_path) == ["active"]
        directory_codes = [str(row["lp_code"]) for row in read_lp_directory_items(db_path)]
        assert directory_codes == ["seed", "active"]


def test_lp_public_labels_do_not_expose_internal_taxonomy() -> None:
    assert public_lp_type("Policy Bank") == "정책금융기관"
    assert public_lp_type("Mutual Aid Association") == "공제회"
    assert display_asset_classes("PEF;VC;Private Credit;Real Estate;Mother Fund") == "PEF · VC · 사모대출 · 부동산 · 모태펀드"
    assert public_coverage_label(0, 0) == "0개"


def test_article_payload_does_not_render_lp_as_gp_chip() -> None:
    url = "https://dealsite.co.kr/articles/162599"
    rows = [
        {
            "title": "국민성장펀드 2차 출자사업 개시",
            "source": "딜사이트",
            "url": url,
            "section": "국민성장펀드",
        }
    ]
    payload = article_payload_rows(
        rows,
        {
            url: {
                "gpNames": ["한국산업은행", "아이엠엠프라이빗에쿼티"],
                "lpNames": ["한국산업은행"],
                "lpProfileLinks": [{"code": "kdb", "name": "한국산업은행", "url": "lp-kdb.html"}],
                "peopleCount": 0,
                "searchTerms": [],
            }
        },
    )
    assert payload[0]["gpNames"] == ["아이엠엠프라이빗에쿼티"]
    assert payload[0]["lpNames"] == ["한국산업은행"]


def test_kic_lp_alias_seed_feeds_article_context() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "lp.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE lp_institution(
                    lp_code TEXT,
                    lp_name TEXT,
                    aliases TEXT,
                    service_priority INTEGER
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        patterns = read_lp_alias_patterns(db_path)

    kic = next(pattern for pattern in patterns if pattern["lp_code"] == "kic")
    assert kic["lp_name"] == "한국투자공사"
    assert "KIC" in kic["aliases"]
    assert "한국투자공사" in kic["aliases"]

    url = "https://www.sedaily.com/article/test-kic"
    payload = article_payload_rows(
        [
            {
                "title": "KIC 첫 국내 출자 펀드, 내달 베일 벗는다[시그널]",
                "source": "서울경제",
                "url": url,
                "section": "LP",
            }
        ],
        {
            url: {
                "gpNames": ["도미누스인베스트먼트", "아이엠엠인베스트먼트"],
                "lpNames": [kic["lp_name"]],
                "lpProfileLinks": [{"code": "kic", "name": kic["lp_name"], "url": "lp-kic.html"}],
                "peopleCount": 0,
                "searchTerms": kic["aliases"],
            }
        },
    )
    assert payload[0]["lpNames"] == ["한국투자공사"]
    assert payload[0]["gpNames"] == ["도미누스인베스트먼트", "아이엠엠인베스트먼트"]


def test_context_only_lp_keeps_name_without_broken_profile_link() -> None:
    context = {
        "https://www.sedaily.com/article/test-kic": {
            "lpNames": ["한국투자공사", "한국산업은행"],
            "lpProfileLinks": [
                {"code": "kic", "name": "한국투자공사", "url": "lp-kic.html"},
                {"code": "kdb", "name": "한국산업은행", "url": "lp-kdb.html"},
            ],
            "gpNames": [],
            "searchTerms": [],
        }
    }

    filter_service_context_profile_links(context, {"kdb"})

    assert context["https://www.sedaily.com/article/test-kic"]["lpNames"] == ["한국투자공사", "한국산업은행"]
    assert context["https://www.sedaily.com/article/test-kic"]["lpProfileLinks"] == [
        {"code": "kdb", "name": "한국산업은행", "url": "lp-kdb.html"}
    ]


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
    assert primary_section(credit_row) == "Market"


def test_specific_credit_transaction_stays_deal() -> None:
    row = {
        "publisher": "조선비즈",
        "title": "VAC, 회생기업 코다코에 500억 DIP 대출 집행",
        "summary_text": "특정 기업에 대한 구조화 대출 집행 기사다.",
        "relevance_score": 8,
        "section_tags": "Credit",
        "topic_tags": "Credit,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://biz.chosun.com/test",
        "review_status": "auto",
    }
    assert primary_section(row) == "Deal"
    assert editorial_section({"title": str(row["title"]), "section": "Credit"}) == "Deal"


def test_private_credit_market_commentary_is_market() -> None:
    rows = [
        {
            "publisher": "한국경제",
            "title": "고금리 뉴노멀 시대…오크트리 \"위기 속 스페셜 시추에이션이 기회\"",
            "summary_text": "사모크레딧 부실과 PEF 유동성 부족 등 시장 환경을 진단했다.",
            "section_tags": "Market",
            "topic_tags": "Deal,GP,LP,PEF,daily,market_news",
        },
        {
            "publisher": "한국경제",
            "title": "\"은행이 못 채운 공백, 사모대출이 메울 것\"",
            "summary_text": "글로벌 운용사가 한국 사모대출 시장 기회를 설명했다.",
            "section_tags": "Market",
            "topic_tags": "LP,PEF,daily,market_news",
        },
        {
            "publisher": "한국경제",
            "title": "사모대출은 불안하다? 파트너스그룹 \"구조와 투자자를 봐야\"",
            "summary_text": "기관 전용 사모대출 펀드와 BDC를 비교했다.",
            "section_tags": "Market",
            "topic_tags": "PEF,daily,market_news",
        },
        {
            "publisher": "더벨",
            "title": "샘 패짓 딜로이트 AP PE 총괄 “불확실성은 상수”",
            "summary_text": "국내 PE 시장 전망 인터뷰다.",
            "section_tags": "Market",
            "topic_tags": "PEF,daily,publisher_watch",
        },
    ]
    for row in rows:
        assert primary_section({**row, "document_type_tags": "", "gp_names": "", "source_url": "https://example.com", "review_status": "auto"}) == "Market"
        assert editorial_section({"title": str(row["title"]), "section": str(row["section_tags"])}) == "Market"


def test_company_gap_titles_keep_expected_sections_and_quality() -> None:
    cases = [
        (
            {
                "publisher": "딜사이트",
                "title": "스톤브릿지 AI펀드 러브콜…3400억으로 70% 증액",
                "summary_text": "교공 앵커 출자 이후 AI 분야 펀드레이징 수요가 늘었다.",
                "relevance_score": 9,
                "section_tags": "LP",
                "topic_tags": "GP,LP,Market,allocator,daily,lp_watch",
                "document_type_tags": "",
                "gp_names": "스톤브릿지벤처스",
                "source_url": "https://dealsite.co.kr/articles/162433",
                "review_status": "auto",
            },
            "GP",
        ),
        (
            {
                "publisher": "딜사이트",
                "title": "[LP Scope] 李정부 발맞춘 IBK…하반기도 1500억 더 푼다",
                "summary_text": "정책금융 LP의 하반기 출자 계획과 운용사 선정 가능성을 다룬다.",
                "relevance_score": 9,
                "section_tags": "LP",
                "topic_tags": "LP,PEF,allocator,daily,lp_watch",
                "document_type_tags": "",
                "gp_names": "",
                "source_url": "https://dealsite.co.kr/articles/162555",
                "review_status": "auto",
            },
            "LP",
        ),
        (
            {
                "publisher": "헤럴드경제",
                "title": "사모펀드 VIG, 헬스테크기업 미니쉬에 300억 투자",
                "summary_text": "VIG파트너스가 성장자본 투자로 지분을 확보했다.",
                "relevance_score": 8,
                "section_tags": "Deal",
                "topic_tags": "Deal,PEF,daily,deal_watch",
                "document_type_tags": "",
                "gp_names": "브이아이지파트너스",
                "source_url": "https://biz.heraldcorp.com/article/10757779",
                "review_status": "auto",
            },
            "Deal",
        ),
        (
            {
                "publisher": "매일경제",
                "title": "KIC, 새 CIO 뽑는다…다음달 11일까지 공개모집",
                "summary_text": "한국투자공사가 투자운용부문장 공개모집에 들어갔다.",
                "relevance_score": 7,
                "section_tags": "LP",
                "topic_tags": "LP,people,daily,lp_watch",
                "document_type_tags": "",
                "gp_names": "",
                "source_url": "https://www.mk.co.kr/news/stock/12059723",
                "review_status": "auto",
            },
            "LP",
        ),
    ]
    for row, expected in cases:
        assert primary_section(row) == expected
        score, reason = editorial_quality(row)
        assert score >= EXPORT_MIN_QUALITY_SCORE, reason


def test_company_gap_keyword_rules_cover_ai_fund_lp_scope_and_private_debt() -> None:
    rules = load_rules(DEFAULT_RULES)
    samples = [
        ("스톤브릿지 AI펀드 러브콜…3400억으로 70% 증액", "AI_PE"),
        ("[LP Scope] 李정부 발맞춘 IBK…하반기도 1500억 더 푼다", "LP"),
        ("금융권 해외 사모대출 30조원···당국 리스크 관리 가능한 수준", "Credit"),
    ]
    for title, expected_tag in samples:
        scored = score_document(title, "", "", rules, [])
        tags = {tag["tag_value"] for tag in scored["tags"]}
        assert expected_tag in tags


def test_gpu_or_etf_text_does_not_match_gp_or_pe_tokens() -> None:
    row = {
        "publisher": "딜사이트",
        "title": "엔비디아 GPU로 임대사업 투자…美ETF 나온다",
        "summary_text": "GPU 임대가격 선물로 추종하는 ETF 구조를 설명한다.",
        "relevance_score": 4,
        "section_tags": "Deal",
        "topic_tags": "Market,daily,deal_watch,publisher_watch",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://dealsite.co.kr/articles/162421",
        "review_status": "auto",
    }
    score, reason = editorial_quality(row)
    assert score < EXPORT_MIN_QUALITY_SCORE, reason
    assert primary_section(row) != "AI_PE"


def test_render_markdown_uses_canonical_article_url() -> None:
    rows = [
        {
            "publisher": "서울경제",
            "title": "KIC 첫 국내 출자 펀드, 내달 베일 벗는다[시그널]",
            "summary_text": "한국투자공사 국내 출자 펀드 기사다.",
            "relevance_score": 10,
            "quality_score": 15,
            "section_tags": "LP",
            "topic_tags": "LP,PEF",
            "document_type_tags": "",
            "gp_names": "",
            "source_url": "https://www.sedaily.com/article/20048749?ref=naver",
            "normalized_source_url": "https://www.sedaily.com/article/20048749",
            "review_status": "auto",
        }
    ]
    markdown = render_markdown("2026-05-28", rows)
    assert "https://www.sedaily.com/article/20048749)" in markdown
    assert "ref=naver" not in markdown


def test_ai_pe_strategy_is_not_demoted_by_opportunity_language() -> None:
    row = {
        "publisher": "한국경제",
        "title": "베인캐피탈 “유럽, 지금이 좋은 진입기회…AI·에너지·방위 등 메가트렌드”",
        "summary_text": "글로벌 PE 운용사가 AI 투자 전략과 사모시장 진입 기회를 설명했다.",
        "section_tags": "AI & PE",
        "topic_tags": "AI,PEF,daily,market_news",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.hankyung.com/test",
        "review_status": "auto",
    }
    assert primary_section(row) == "AI_PE"
    assert editorial_section({"title": str(row["title"]), "section": "AI & PE"}) == "AI & PE"


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


def test_ai_fundraising_story_stays_gp() -> None:
    row = {
        "publisher": "딜사이트",
        "title": "스톤브릿지 AI펀드 러브콜…3400억으로 70% 증액",
        "summary_text": "스톤브릿지벤처스가 AI 글로벌 레벨업 펀드를 확대 조성하고 GP로 선정된 뒤 펀드레이징에 나섰다.",
        "relevance_score": 8,
        "section_tags": "Fundraising",
        "topic_tags": "GP,AI_PE,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://dealsite.co.kr/articles/162433",
        "review_status": "auto",
    }
    assert primary_section(row) == "GP"
    score, reason = editorial_quality(row)
    assert score >= EXPORT_MIN_QUALITY_SCORE, reason


def test_incidental_body_ai_does_not_promote_market_conference_to_ai_pe() -> None:
    row = {
        "publisher": "한국경제",
        "title": "\"산업·자본흐름 자체가 바뀌는 시대 미래에도 살아남을 자산 찾아내야\"",
        "summary_text": (
            "ASK 2026 글로벌 대체투자 콘퍼런스에서 자산군별 선별투자가 중요하다고 논의했고 "
            "AI 혁신 등으로 투자 공식이 바뀌고 있다고 언급했다."
        ),
        "relevance_score": 10,
        "section_tags": "Market",
        "topic_tags": "LP,PEF,daily,market_news",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.hankyung.com/article/2026052724941",
        "review_status": "auto",
    }
    assert primary_section(row) == "Market"
    assert editorial_section({"title": str(row["title"]), "section": "Market"}) == "Market"


def test_lp_title_is_not_promoted_to_ai_by_body_context() -> None:
    row = {
        "publisher": "한국경제",
        "title": "LP들 “시장 타이밍보다 선별투자”…해외 사모시장 공식 바뀐다",
        "summary_text": "KIC와 국민연금, 군인공제회가 해외 사모시장 선별투자를 논의했고 AI 방어력도 일부 언급했다.",
        "relevance_score": 8,
        "section_tags": "LP",
        "topic_tags": "LP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.hankyung.com/article/202605272626r",
        "review_status": "auto",
    }
    assert primary_section(row) == "LP"
    assert editorial_section({"title": str(row["title"]), "section": "AI & PE"}) == "LP"


def test_lp_ai_agent_title_stays_lp() -> None:
    row = {
        "publisher": "연합인포맥스",
        "title": "LP들도 'AI 에이전트' 열공 모드",
        "summary_text": "연기금과 공제회 등 LP들이 AI 에이전트 활용 방안을 논의했다.",
        "relevance_score": 6,
        "section_tags": "LP",
        "topic_tags": "LP,AI_PE,daily",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://news.einfomax.co.kr/news/articleView.html?idxno=test",
        "review_status": "auto",
    }
    assert primary_section(row) == "LP"


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
    assert editorial_section({"title": str(row["title"]), "section": "GP"}) == "GP"


def test_national_growth_fund_named_in_gp_strategy_is_not_dedicated_section() -> None:
    row = {
        "publisher": "딜사이트",
        "title": "국민성장펀드 노리는 IMM…레버리지는 없다",
        "summary_text": "시지바이오·이화다이아몬드 인수에 금융 없는 에쿼티 구조를 쓴 드라이 파우더 전략이다.",
        "relevance_score": 7,
        "section_tags": "Deal",
        "topic_tags": "Deal,GP,LP,NationalGrowthFund,PEF,daily,deal_watch",
        "document_type_tags": "",
        "gp_names": "아이엠엠프라이빗에쿼티",
        "source_url": "https://dealsite.co.kr/articles/162427",
        "review_status": "auto",
    }
    assert primary_section(row) == "GP"
    assert editorial_section({"title": str(row["title"]), "section": "GP"}) == "GP"


def test_partner_suffix_does_not_turn_specific_investment_into_gp() -> None:
    row = {
        "publisher": "이투데이",
        "title": "VIG파트너스, 미니쉬테크놀로지에 300억 투자…지분 20% 확보",
        "summary_text": "국내 사모펀드운용사 VIG파트너스가 미니쉬테크놀로지에 투자했다.",
        "relevance_score": 8,
        "section_tags": "Deal",
        "topic_tags": "Deal,PEF,daily,deal_watch",
        "document_type_tags": "press_release",
        "gp_names": "브이아이지파트너스",
        "source_url": "https://www.etoday.co.kr/news/view/2588431",
        "review_status": "auto",
    }
    assert primary_section(row) == "Deal"
    assert editorial_section({"title": str(row["title"]), "section": "Deal"}) == "Deal"


def test_acquisition_profile_title_with_pumneun_stays_deal() -> None:
    row = {
        "publisher": "매일경제",
        "title": "피자헛 품는 前 현대차 부사장…\"마케팅 경험 살려 승부할 것\"",
        "summary_text": "조원홍 윈터골드PE 대표가 과거 브랜드 파워를 회복시키겠다는 포부를 밝혔다.",
        "relevance_score": 14,
        "section_tags": "Market",
        "topic_tags": "Market,PEF,daily,market_news",
        "document_type_tags": "",
        "gp_names": "윈터골드",
        "source_url": "https://www.mk.co.kr/news/stock/12059131",
        "review_status": "auto",
    }
    assert primary_section(row) == "Deal"
    assert editorial_section({"title": str(row["title"]), "section": "Deal"}) == "Deal"


def test_allocator_cio_governance_is_lp_not_market() -> None:
    row = {
        "publisher": "파이낸셜뉴스",
        "title": "'자본시장 큰손들' 거취 촉각…하반기 CIO인선 큰장 열린다",
        "summary_text": "연기금·공제회 최고 운용 총괄 책임자들의 임기 만료와 후임 인선이 이어진다.",
        "relevance_score": 7,
        "section_tags": "LP",
        "topic_tags": "LP,PEF,allocator,daily,lp_watch",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.fnnews.com/news/202605271026381801",
        "review_status": "auto",
    }
    assert primary_section(row) == "LP"
    assert editorial_section({"title": str(row["title"]), "section": "LP"}) == "LP"


def test_court_investment_document_stays_market_not_lp() -> None:
    row = {
        "publisher": "서울경제",
        "title": "법원, 고려아연에 원아시아 펀드 투자 문서 제출 명령 [시그널]",
        "summary_text": "고려아연이 원아시아파트너스 펀드에 출자했지만 법원 문서제출 명령과 이해관계가 핵심이다.",
        "relevance_score": 10,
        "section_tags": "GP",
        "topic_tags": "PEF,daily,gp_watch",
        "document_type_tags": "",
        "gp_names": "원아시아파트너스,엠비케이파트너스",
        "source_url": "https://www.sedaily.com/article/20048680",
        "review_status": "auto",
    }
    assert primary_section(row) == "Market"
    assert editorial_section({"title": str(row["title"]), "section": "LP"}) == "Market"


def test_gp_stake_belongs_to_market_structure() -> None:
    row = {
        "publisher": "한국경제",
        "title": "보나코드 “GP 스테이크, 단순 자금 조달 넘어선 기업 성장 핵심 전략”",
        "summary_text": "PEF 운용사 지분 투자와 GP 스테이크 시장 구조를 다룬다.",
        "relevance_score": 6,
        "section_tags": "Market",
        "topic_tags": "PEF,daily,market_news",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.hankyung.com/article/202605272317r",
        "review_status": "auto",
    }
    assert primary_section(row) == "Market"
    assert editorial_section({"title": str(row["title"]), "section": "GP"}) == "Market"


def test_new_gp_fund_start_is_export_quality_gp() -> None:
    row = {
        "publisher": "뉴스톱",
        "title": "'고위드' 업은 고넥스PE, 500억 펀드 시동",
        "summary_text": "신생 사모펀드 운용사가 기관전용 사모펀드 라이선스를 확보하고 펀드 조성에 나섰다.",
        "relevance_score": 2,
        "section_tags": "GP",
        "topic_tags": "GP,PEF,fundraising",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45169",
        "normalized_source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45169",
        "review_status": "auto",
    }
    quality_score, _reason = editorial_quality(row)
    assert primary_section(row) == "GP"
    assert quality_score >= EXPORT_MIN_QUALITY_SCORE


def test_kic_cio_people_story_is_lp() -> None:
    row = {
        "publisher": "매일경제",
        "title": "KIC, 새 CIO 뽑는다…다음달 11일까지 공개모집",
        "summary_text": "한국투자공사가 투자 책임자인 CIO 공개모집에 나섰다.",
        "relevance_score": 4,
        "section_tags": "LP",
        "topic_tags": "LP,allocator,people",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.mk.co.kr/news/stock/12059723",
        "normalized_source_url": "https://www.mk.co.kr/news/stock/12059723",
        "review_status": "auto",
    }
    quality_score, _reason = editorial_quality(row)
    assert primary_section(row) == "LP"
    assert quality_score >= EXPORT_MIN_QUALITY_SCORE


def test_display_url_prefers_normalized_clean_article_url() -> None:
    row = {
        "source_url": "https://www.sedaily.com/article/20048749?ref=naver&utm_source=naver",
        "normalized_source_url": "https://www.sedaily.com/article/20048749",
    }
    assert display_url(row) == "https://www.sedaily.com/article/20048749"


def test_pef_association_belongs_to_market_structure() -> None:
    row = {
        "publisher": "매일경제",
        "title": "세 불리는 PEF협의회 … 웰투시 등 7곳 승선",
        "summary_text": "사모펀드 업계 단체와 시장 네트워크 확대를 다룬다.",
        "relevance_score": 7,
        "section_tags": "GP",
        "topic_tags": "GP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.mk.co.kr/news/stock/12059126",
        "review_status": "auto",
    }
    assert primary_section(row) == "Market"
    assert editorial_section({"title": str(row["title"]), "section": "GP"}) == "Market"


def test_same_publisher_near_duplicate_title_is_selected_once() -> None:
    duplicate_a = {
        "news_id": 11557,
        "publisher": "매일경제",
        "title": "국민성장펀드 대형 위탁운용사에 스카이레이크·에이티넘",
        "summary_text": "국민성장펀드 운용사 선정 기사",
        "quality_score": 22,
        "relevance_score": 14,
        "section_tags": "NationalGrowthFund",
        "topic_tags": "NationalGrowthFund,LP,PEF",
        "source_url": "https://www.mk.co.kr/news/stock/12059148",
        "normalized_source_url": "https://www.mk.co.kr/news/stock/12059148",
    }
    duplicate_b = {
        **duplicate_a,
        "news_id": 11556,
        "title": "국민성장펀드 대형 위탁운용사…스카이레이크·에이티넘 선정",
        "source_url": "https://www.mk.co.kr/news/stock/12059233",
        "normalized_source_url": "https://www.mk.co.kr/news/stock/12059233",
    }
    other = {
        **duplicate_a,
        "news_id": 1,
        "publisher": "서울경제",
        "title": "KIC 첫 국내 출자 펀드, 내달 베일 벗는다",
        "summary_text": "LP 출자사업 기사",
        "quality_score": 15,
        "relevance_score": 10,
        "section_tags": "LP",
        "topic_tags": "LP,PEF",
        "source_url": "https://www.sedaily.com/article/test",
        "normalized_source_url": "https://www.sedaily.com/article/test",
    }
    selected = select_brief_rows([duplicate_a, duplicate_b, other], 3)
    selected_titles = [str(row["title"]) for row in selected]
    assert duplicate_a["title"] in selected_titles
    assert duplicate_b["title"] not in selected_titles


def test_same_national_growth_fund_selection_event_is_selected_once() -> None:
    sedaily = {
        "news_id": 11478,
        "publisher": "서울경제",
        "title": "국민성장펀드 간접투자 운용사 명단 확정…11곳 PE·VC 선정",
        "summary_text": "국민성장펀드 간접투자 위탁운용사 11곳이 선정됐다.",
        "quality_score": 25,
        "relevance_score": 16,
        "section_tags": "NationalGrowthFund",
        "topic_tags": "NationalGrowthFund,LP,PEF",
        "source_url": "https://www.sedaily.com/article/20048957",
        "normalized_source_url": "https://www.sedaily.com/article/20048957",
    }
    dealsite = {
        "news_id": 11840,
        "publisher": "딜사이트",
        "title": "[150조 국민성장펀드] [간접투자 1차] 2.4조 운용할 GP 선정…에이티넘·웰투시 등 11곳",
        "summary_text": "국민성장펀드 1차 위탁운용사 11곳이 선정됐다.",
        "quality_score": 22,
        "relevance_score": 13,
        "section_tags": "NationalGrowthFund",
        "topic_tags": "NationalGrowthFund,LP,PEF",
        "source_url": "https://dealsite.co.kr/articles/162589/075023",
        "normalized_source_url": "https://dealsite.co.kr/articles/162589",
    }
    second_round = {
        **dealsite,
        "news_id": 11838,
        "title": "[150조 국민성장펀드] [간접투자 2차] 1차 끝나자마자 1.6조 규모 출자사업 개시",
        "summary_text": "국민성장펀드 2차 출자사업이 개시됐다.",
        "source_url": "https://dealsite.co.kr/articles/162599/075023",
        "normalized_source_url": "https://dealsite.co.kr/articles/162599",
    }
    assert event_dedupe_key(sedaily) == event_dedupe_key(dealsite)
    selected = select_brief_rows([sedaily, dealsite, second_round], 3)
    assert [int(row["news_id"]) for row in selected] == [11478, 11838]


def test_review_selection_dedupes_event_and_google_redirect() -> None:
    direct = {
        "news_id": 11840,
        "publisher": "딜사이트",
        "title": "[150조 국민성장펀드] [간접투자 1차] 2.4조 운용할 GP 선정…에이티넘·웰투시 등 11곳",
        "summary_text": "국민성장펀드 1차 위탁운용사 11곳이 선정됐다.",
        "quality_score": 26,
        "relevance_score": 16,
        "section_tags": "NationalGrowthFund",
        "topic_tags": "NationalGrowthFund,LP,PEF",
        "source_url": "https://dealsite.co.kr/articles/162589/075023",
        "normalized_source_url": "https://dealsite.co.kr/articles/162589",
        "review_status": "auto",
    }
    google_redirect = {
        **direct,
        "news_id": 11841,
        "quality_score": 13,
        "source_url": "https://news.google.com/rss/articles/example",
        "normalized_source_url": "https://news.google.com/rss/articles/example",
    }
    selected = select_review_rows([direct, google_redirect], 10)
    assert [int(row["news_id"]) for row in selected] == [11840]


def test_company_clipping_keyword_gaps_are_scored() -> None:
    rules = load_rules(DEFAULT_RULES)
    cases = [
        ("헬리오스PE, 서울전선 인수 우선협상대상자로 선정", 7, "GP"),
        ("방산 수혜 '엠앤씨솔루션', SPA 체결 임박", 3, "Deal"),
        ("신생 PE 페트리코, 카카오게임즈 빅딜 소싱 배경은", 4, "GP"),
        ("[150조 국민성장펀드] 그로쓰 투자 대가 도미누스", 3, "LP"),
        ("행정공제회 신임 이사장에 김기영 전 충남 행정부지사", 4, "LP"),
        ("KCGI자산운용, AUM 6조원 돌파", 3, "GP"),
        ("'고위드' 업은 고넥스PE, 500억 펀드 시동", 7, "GP"),
        ("키움인베 600억 벤처모펀드 출격", 3, "LP"),
        ("KIC, 새 CIO 뽑는다…다음달 11일까지 공개모집", 6, "LP"),
        ("[카카오게임즈 매각] 3000억 수혈의 그늘…다가올 변수는", 3, "Deal"),
        ("[LP Scope] 李정부 발맞춘 IBK…하반기도 1500억 더 푼다", 4, "LP"),
        ("스톤브릿지 AI펀드 러브콜…3400억으로 70% 증액", 6, "GP"),
        ("티케하우캐피탈 사모대출 시장 경고등…세컨더리 투자 주목해야", 3, "Market"),
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


def test_render_markdown_uses_clean_display_url() -> None:
    row = {
        "publisher": "서울경제",
        "title": "KIC 첫 국내 출자 펀드",
        "summary_text": "한국투자공사 출자 펀드 기사",
        "relevance_score": 10,
        "section_tags": "LP",
        "topic_tags": "LP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.sedaily.com/article/20048749?ref=naver&utm_source=naver",
        "normalized_source_url": "https://www.sedaily.com/article/20048749",
        "quality_score": 12,
        "review_status": "auto",
    }
    text = render_markdown("2026-05-28", [row])
    assert "https://www.sedaily.com/article/20048749)" in text
    assert "ref=naver" not in text


def main() -> int:
    tests = [
        test_coverage_window,
        test_monday_coverage_window_catches_weekend,
        test_google_backtest_window,
        test_google_backtest_window_catches_weekend_on_monday,
        test_previous_export_keys_ignore_review_candidates,
        test_google_news_decode_helpers,
        test_sedaily_mobile_amp_url_normalizes_to_desktop_article,
        test_dealsite_category_suffix_url_normalizes_to_article,
        test_truncated_media_suffix_does_not_split_title_duplicates,
        test_gp_alias_overrides_cover_common_short_names,
        test_lp_directory_includes_seed_only_profiles_without_empty_profile_pages,
        test_lp_public_labels_do_not_expose_internal_taxonomy,
        test_article_payload_does_not_render_lp_as_gp_chip,
        test_kic_lp_alias_seed_feeds_article_context,
        test_context_only_lp_keeps_name_without_broken_profile_link,
        test_national_growth_fund_has_dedicated_section,
        test_national_growth_fund_title_beats_ai_keyword,
        test_ai_pe_keeps_priority_when_national_growth_fund_is_body_context,
        test_web_renderer_maps_national_growth_fund_section,
        test_review_category_accepts_national_growth_fund_aliases,
        test_weak_context_quality_penalty,
        test_strong_headline_quality,
        test_allocator_section_priority,
        test_gp_fundraising_and_deal_financing_sections,
        test_specific_credit_transaction_stays_deal,
        test_private_credit_market_commentary_is_market,
        test_company_gap_titles_keep_expected_sections_and_quality,
        test_company_gap_keyword_rules_cover_ai_fund_lp_scope_and_private_debt,
        test_render_markdown_uses_canonical_article_url,
        test_ai_pe_strategy_is_not_demoted_by_opportunity_language,
        test_ai_pe_section_priority,
        test_ai_fundraising_story_stays_gp,
        test_incidental_body_ai_does_not_promote_market_conference_to_ai_pe,
        test_lp_title_is_not_promoted_to_ai_by_body_context,
        test_lp_ai_agent_title_stays_lp,
        test_ai_pe_reserved_in_brief_selection,
        test_lp_and_gp_reserved_in_full_brief_selection,
        test_gp_fundraising_beats_deal_word_when_title_is_fund_build,
        test_national_growth_fund_named_in_gp_strategy_is_not_dedicated_section,
        test_partner_suffix_does_not_turn_specific_investment_into_gp,
        test_acquisition_profile_title_with_pumneun_stays_deal,
        test_allocator_cio_governance_is_lp_not_market,
        test_court_investment_document_stays_market_not_lp,
        test_gp_stake_belongs_to_market_structure,
        test_new_gp_fund_start_is_export_quality_gp,
        test_kic_cio_people_story_is_lp,
        test_display_url_prefers_normalized_clean_article_url,
        test_pef_association_belongs_to_market_structure,
        test_same_publisher_near_duplicate_title_is_selected_once,
        test_same_national_growth_fund_selection_event_is_selected_once,
        test_review_selection_dedupes_event_and_google_redirect,
        test_company_clipping_keyword_gaps_are_scored,
        test_dot_datetime_to_iso,
        test_google_news_redirect_not_auto_exported,
        test_render_markdown_coverage,
        test_render_markdown_uses_clean_display_url,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
