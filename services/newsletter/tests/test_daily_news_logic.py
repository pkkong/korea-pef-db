#!/usr/bin/env python
"""Fast no-network checks for daily news clipping business rules."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
LEGACY_SCRIPTS_DIR = SERVICE_ROOT.parents[1] / "scripts"
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))

from run_daily_news_pipeline import (
    EXPORT_MIN_QUALITY_SCORE,
    assert_source_family_readiness,
    build_scoring_excerpt,
    coverage_window_label,
    editorial_quality,
    event_dedupe_key,
    display_url,
    extract_google_news_decode_params,
    google_query_for_report_date,
    google_news_encoded_id,
    infer_publisher,
    is_in_coverage_window,
    is_previous_export,
    load_previous_export_keys,
    normalize_export_classification,
    normalize_title_key,
    parse_google_news_batch_response,
    primary_section,
    render_markdown,
    select_brief_rows,
    select_review_rows,
    should_skip_previous_export,
    should_export_row,
)
from news_taxonomy import TAG_TAXONOMY_VERSION
from daily_news_common import (
    DEFAULT_SOURCES,
    DEFAULT_RULES,
    load_gp_aliases,
    load_sources,
    load_rules,
    match_gp_entities,
    normalize_url,
    score_document,
    to_iso_datetime,
)
from build_newsletter_deploy import (
    consolidate_lp_notice_display_items,
    display_asset_classes,
    filter_service_context_profile_links,
    lp_notice_business_round_name,
    lp_notice_program_label,
    lp_notice_specific_program_name,
    public_coverage_label,
    public_lp_type,
    read_lp_directory_items,
    read_lp_alias_patterns,
    read_lp_profile_codes,
    render_lp_notice_card,
)
from build_service_site import editorial_section
from build_service_site import editorial_subtype
from build_service_site import article_payload_rows
from build_service_site import public_article_summary_lines
from build_service_site import read_ai_enrichment_context
from apply_daily_news_review import normalize_category
from brand_assets import brand_logo_url
from lp_public_visibility import is_public_lp_notice_row
from validate_daily_news_pipeline import Validation, check_classification_quality
from enrich_daily_news_ai import audit_rows, enrichment_prompt, memo_summary_lines, normalize_ai_articles
from backtest_newsletter_ai import summarize_date
from evaluate_news_classification_goldens import evaluate as evaluate_classification_goldens, read_csv_rows as read_golden_csv_rows


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


def test_force_include_previous_export_only_repeats_inside_current_window() -> None:
    previous_keys = {
        "urls": {"https://view.asiae.co.kr/article/2026052611385718194"},
        "titles": set(),
    }
    old_manual = {
        "source_url": "https://view.asiae.co.kr/article/2026052611385718194",
        "normalized_source_url": "https://view.asiae.co.kr/article/2026052611385718194",
        "title": "국내 금융권 등 해외 사모대출 56조…당국 시스템 리스크 가능성 낮아",
        "published_at": "2026-05-26T11:38:00+09:00",
        "review_status": "force_include",
    }
    current_manual = {
        **old_manual,
        "source_url": "https://www.pinpointnews.co.kr/news/articleView.html?idxno=458008",
        "normalized_source_url": "https://www.pinpointnews.co.kr/news/articleView.html?idxno=458008",
        "published_at": "2026-06-06T13:59:57+09:00",
    }
    current_previous_keys = {
        "urls": {"https://www.pinpointnews.co.kr/news/articleView.html?idxno=458008"},
        "titles": set(),
    }
    assert should_skip_previous_export(old_manual, previous_keys, "2026-06-07")
    assert not should_skip_previous_export(current_manual, current_previous_keys, "2026-06-07")


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


def test_common_news_tracking_params_are_removed() -> None:
    assert (
        normalize_url("https://www.edaily.co.kr/News/Read?newsId=04759286645477456&mediaCodeNo=257&OutLnkChk=Y")
        == "https://www.edaily.co.kr/News/Read?mediaCodeNo=257&newsId=04759286645477456"
    )
    assert normalize_url("https://view.asiae.co.kr/article/2026052611385718194?input=1195m") == (
        "https://view.asiae.co.kr/article/2026052611385718194"
    )
    assert normalize_url("https://www.thebell.co.kr/front/newsview.asp?click=F&key=202605280841565440103110") == (
        "https://www.thebell.co.kr/front/newsview.asp?key=202605280841565440103110"
    )
    assert normalize_url("http://www.enewstoday.co.kr/news/articleView.html?idxno=2434987") == (
        "https://www.enewstoday.co.kr/news/articleView.html?idxno=2434987"
    )


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
                    (46, "키움인베스트먼트"),
                    (47, "에이치앤큐코리아파트너스"),
                    (48, "이앤에프프라이빗에퀴티"),
                    (49, "고넥스프라이빗에쿼티"),
                    (50, "파라투스인베스트먼트"),
                    (51, "골든루트인베스트먼트"),
                    (52, "대신프라이빗에쿼티"),
                    (53, "에스케이에스프라이빗에쿼티"),
                    (54, "미래에셋자산운용"),
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
            "KIC는 IMM인베스트와 도미누스와 손잡고 펀드 조성을 완료할 예정이다.",
            "",
            aliases,
        )
        imm_names = {str(match["entity_name"]) for match in imm_matches}
        assert "아이엠엠인베스트먼트" in imm_names
        assert "도미누스인베스트먼트" in imm_names

        named_gp_matches = match_gp_entities(
            "키움인베 600억 벤처모펀드 출격",
            "H&Q와 E&F프라이빗PE도 신규 블라인드펀드 전략을 검토한다.",
            "'고위드' 업은 고넥스PE, 500억 펀드 시동",
            aliases,
        )
        named_gp_names = {str(match["entity_name"]) for match in named_gp_matches}
        assert "키움인베스트먼트" in named_gp_names
        assert "에이치앤큐코리아파트너스" in named_gp_names
        assert "이앤에프프라이빗에퀴티" in named_gp_names
        assert "고넥스프라이빗에쿼티" in named_gp_names

        paratus_matches = match_gp_entities(
            "국민성장펀드 잡은 파라투스, 최대 3000억 펀딩 탄력",
            "파라투스인베스트먼트가 국민성장펀드 운용사로 선정됐다.",
            " ".join(["골든루트인베스트먼트와 아주아이비투자 등도 선정 명단에 포함됐다."] * 8),
            aliases,
        )
        assert [str(match["entity_name"]) for match in paratus_matches] == ["파라투스인베스트먼트"]

        daishin_matches = match_gp_entities(
            "2000억대 체급 깬 대신PE, AI·반도체 4000억 펀드 시동",
            "대신프라이빗에쿼티가 블라인드펀드 조성에 나섰다.",
            " ".join(["에스케이에스프라이빗에쿼티와 인터베스트도 관련 리그에 이름을 올렸다."] * 8),
            aliases,
        )
        assert [str(match["entity_name"]) for match in daishin_matches] == ["대신프라이빗에쿼티"]

        prior_role_matches = match_gp_entities(
            "美 VC 500글로벌, 韓 총괄에 안성우 미래에셋PE 대표 선임",
            "미국 벤처캐피털 500 글로벌은 안성우 전 미래에셋자산운용 사모펀드(PE) 부문 대표를 한국 사무소 총괄 파트너로 선임했다고 밝혔다.",
            "",
            aliases,
        )
        prior_role_names = {str(match["entity_name"]) for match in prior_role_matches}
        assert "미래에셋자산운용" not in prior_role_names


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
                    coverage_tier TEXT,
                    display_enabled INTEGER,
                    notice_tracking_enabled INTEGER,
                    profile_status TEXT,
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


def test_official_lp_candidates_require_explicit_public_notice_allowance() -> None:
    official_candidate = {
        "source_type": "official",
        "source_code": "kgrowth_notice",
        "event_type": "new_notice",
        "monitor_status": "candidate",
        "confidence": "medium",
        "public_visible": "1",
    }
    assert not is_public_lp_notice_row(official_candidate, require_official=True)
    assert is_public_lp_notice_row(
        official_candidate,
        require_official=True,
        allow_official_candidates=True,
    )
    assert not is_public_lp_notice_row(official_candidate, require_official=False)
    assert not is_public_lp_notice_row({**official_candidate, "confidence": "low"}, require_official=True)
    assert not is_public_lp_notice_row({**official_candidate, "event_type": "candidate"}, require_official=True)
    assert not is_public_lp_notice_row(
        {**official_candidate, "source_code": "vcs_investment_notice"},
        require_official=True,
        allow_official_candidates=True,
    )
    assert not is_public_lp_notice_row(
        {**official_candidate, "source_type": "news", "monitor_status": "candidate"},
        require_official=True,
    )


def test_lp_notice_title_program_beats_generic_platform() -> None:
    row = {
        "noticeId": "27100",
        "lpCode": "kgrowth",
        "lpName": "한국성장금융",
        "sourceType": "official",
        "eventType": "new_notice",
        "eventDate": "2026-06-04",
        "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
        "programName": "국민성장펀드",
        "roundName": "3차",
        "strategy": "국민성장펀드",
        "url": "https://www.kgrowth.or.kr/notice/value-up-3",
    }

    assert lp_notice_specific_program_name(row) == "은행권 중견기업 밸류업펀드"
    merged = consolidate_lp_notice_display_items([row])
    assert len(merged) == 1
    assert lp_notice_program_label(merged[0]) == "은행권 중견기업 밸류업펀드 3차"
    rendered = render_lp_notice_card(merged[0], "2026-06-05")
    assert "은행권 중견기업 밸류업펀드 3차" in rendered
    assert 'data-program="국민성장펀드 3차"' not in rendered
    assert '<p class="lp-notice-program">국민성장펀드 3차</p>' not in rendered


def test_lp_notice_no_space_round_still_finds_specific_program() -> None:
    row = {
        "noticeId": "space-less-round",
        "lpCode": "kgrowth",
        "lpName": "한국성장금융",
        "sourceType": "official",
        "eventType": "new_notice",
        "eventDate": "2026-06-04",
        "title": "[서울자치]은행권 중견기업 밸류업펀드3차 서류심사 결과",
        "programName": "국민성장펀드",
        "roundName": "",
        "url": "https://www.kgrowth.or.kr/notice/value-up-space-3",
    }

    assert lp_notice_specific_program_name(row) == "은행권 중견기업 밸류업펀드"
    assert lp_notice_business_round_name(row) == "3차"
    merged = consolidate_lp_notice_display_items([row])
    assert len(merged) == 1
    assert lp_notice_program_label(merged[0]) == "은행권 중견기업 밸류업펀드 3차"


def test_lp_notice_fund_series_round_beats_generic_page_round() -> None:
    row = {
        "noticeId": "content",
        "lpCode": "kgrowth",
        "lpName": "한국성장금융",
        "sourceType": "official",
        "eventType": "new_notice",
        "eventDate": "2026-05-29",
        "title": "【선정공고】「K-콘텐츠 미디어 전략펀드 3호」위탁운용사 선정계획 공고",
        "programName": "국민성장펀드",
        "roundName": "2차",
        "strategy": "국민성장펀드",
    }

    merged = consolidate_lp_notice_display_items([row])
    assert lp_notice_program_label(merged[0]) == "K-콘텐츠 미디어 전략펀드 3호"
    assert "3호 2차" not in render_lp_notice_card(merged[0], "2026-06-05")


def test_lp_notice_specific_program_wins_when_qualities_are_tied() -> None:
    rows = [
        {
            "noticeId": "generic",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2026-06-04",
            "title": "【선정공고】「국민성장펀드」 위탁운용사 선정 계획 공고",
            "programName": "국민성장펀드",
            "roundName": "3차",
        },
        {
            "noticeId": "specific",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2026-06-04",
            "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
            "programName": "국민성장펀드",
            "roundName": "3차",
        },
    ]
    merged = consolidate_lp_notice_display_items(rows)
    assert len(merged) == 1
    assert lp_notice_program_label(merged[0]) == "은행권 중견기업 밸류업펀드 3차"


def test_lp_notice_round_not_duplicated_when_program_already_includes_round() -> None:
    row = {
        "noticeId": "round-dup",
        "lpCode": "kvic",
        "lpName": "한국벤처투자",
        "sourceType": "official",
        "eventType": "new_notice",
        "eventDate": "2026-04-10",
        "title": "모태펀드(우주항공청 등) 2026년 2차 정시 출자사업 계획 공고",
        "programName": "모태펀드(우주항공청 등)",
    }

    assert lp_notice_specific_program_name(row) == "모태펀드(우주항공청 등) 2026년 2차 정시 출자사업"
    assert lp_notice_business_round_name(row) == "2차"
    assert lp_notice_program_label(row) == "모태펀드(우주항공청 등) 2026년 2차 정시 출자사업"


def test_lp_notice_placeholder_round_is_not_a_new_business_card() -> None:
    rows = [
        {
            "noticeId": "notice-1",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2026-06-04",
            "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
            "programName": "국민성장펀드",
            "roundName": "3차",
            "url": "https://www.kgrowth.or.kr/notice/value-up-3",
        },
        {
            "noticeId": "notice-2",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "deadline_closed",
            "eventDate": "2026-05-08",
            "title": "은행권 중견기업 밸류업펀드 위탁운용사 선정계획 공고",
            "programName": "모태펀드",
            "roundName": "수시",
            "url": "https://www.vcs.go.kr/web/portal/bbs/invtnotice/12810",
        },
    ]

    merged = consolidate_lp_notice_display_items(rows)
    assert len(merged) == 1
    assert lp_notice_business_round_name(merged[0]) == "3차"
    assert lp_notice_program_label(merged[0]) == "은행권 중견기업 밸류업펀드 3차"
    rendered = render_lp_notice_card(merged[0], "2026-06-05")
    assert "수시" not in rendered


def test_lp_notice_placeholder_round_value_is_normalized_to_empty() -> None:
    assert lp_notice_business_round_name({"title": "은행권 중견기업 밸류업펀드 공고", "roundName": "수시"}) == ""
    assert lp_notice_business_round_name({"title": "서울회생펀드 상반기 공고", "roundName": ""}) == ""


def test_lp_notice_lifecycle_events_roll_into_one_business_card() -> None:
    rows = [
        {
            "noticeId": "notice",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2026-06-01",
            "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
        },
        {
            "noticeId": "shortlist",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "shortlist",
            "eventDate": "2026-06-10",
            "title": "은행권 중견기업 밸류업펀드 3차 서류심사 결과",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
        },
        {
            "noticeId": "result",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "final_selection",
            "eventDate": "2026-06-20",
            "title": "은행권 중견기업 밸류업펀드 3차 위탁운용사 선정 결과",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
            "selectedGpNames": ["A운용", "B운용"],
        },
    ]

    merged = consolidate_lp_notice_display_items(rows)
    assert len(merged) == 1
    assert merged[0]["businessStatus"] == "result"
    assert merged[0]["businessStageLabel"] == "선정완료"
    assert len(merged[0]["events"]) == 3
    rendered = render_lp_notice_card(merged[0], "2026-06-21")
    assert rendered.count("<article class=\"lp-notice-row\"") == 1
    assert "진행 이력" in rendered


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


def test_article_summary_lines_use_investment_memo_tone() -> None:
    lines = public_article_summary_lines(
        "성장금융이 국민성장펀드 매칭 출자를 개시했다. 블라인드 GP당 최대 300억원을 지원한다. 선정 GP의 민간 펀딩 부담이 완화될 전망이다.",
        "성장금융, 국민성장펀드 매칭 출자",
    )
    assert 2 <= len(lines) <= 3
    assert lines == [
        "성장금융이 국민성장펀드 매칭 출자를 개시",
        "블라인드 GP당 최대 300억원을 지원",
        "선정 GP의 민간 펀딩 부담이 완화될 전망",
    ]
    forbidden = ["했어요", "해요", "입니다", "했다", "전망이다", "사례다", ".", "。"]
    assert not any(token in line for line in lines for token in forbidden)


def test_article_summary_lines_strip_newsroom_boilerplate() -> None:
    lines = public_article_summary_lines(
        "<앵커>공정거래위원회의 불허로 무산됐던 롯데렌탈의 매각 작업이 재개됐습니다.여러 사모펀드와 대기업이 인수 의향을 전하고 실사도 진행 중인 것으로 한국경제TV 취재 결과 확인됐습니다.사안 단독 취재한 산업부 기자 연결합니다.",
        "롯데렌탈 재매각 착수",
    )
    joined = " ".join(lines)
    assert lines[0] == "공정거래위원회의 불허로 무산됐던 롯데렌탈의 매각 작업이 재개"
    assert lines[1].startswith("여러 사모펀드와 대기업이 인수 의향을 전하고 실사도 진행 중인")
    assert "<앵커>" not in joined
    assert "됐습니다" not in joined


def test_ai_local_summary_falls_back_when_source_text_is_title_echo() -> None:
    auction_lines = memo_summary_lines(
        "애큐온캐피탈 매각 본입찰에 메리츠·한화생명 참여-인베스트조선",
        "애큐온캐피탈 매각 본입찰에 메리츠·한화생명 참여",
    )
    private_credit_lines = memo_summary_lines(
        "美 사모대출 운용사 대출 기준 강화한다, 박신영 기자, 국제",
        "美 사모대출 운용사 대출 기준 강화한다",
    )
    assert auction_lines == ["애큐온캐피탈 매각 본입찰 경쟁 구도"]
    assert private_credit_lines == ["사모대출 운용사 대출 심사 기준 강화"]


def test_article_payload_carries_summary_lines_contract() -> None:
    url = "https://dealsite.co.kr/articles/summary-test"
    payload = article_payload_rows(
        [
            {
                "title": "성장금융, 국민성장펀드 매칭 출자",
                "source": "딜사이트",
                "url": url,
                "section": "국민성장펀드",
            }
        ],
        {
            url: {
                "summaryText": "성장금융이 국민성장펀드 매칭 출자를 개시했다. 블라인드 GP당 최대 300억원을 지원한다. 선정 GP의 민간 펀딩 부담이 완화될 전망이다.",
                "gpNames": [],
                "lpNames": [],
                "peopleCount": 0,
                "searchTerms": [],
            }
        },
    )
    assert payload[0]["summaryText"]
    assert payload[0]["summaryLines"] == [
        "성장금융이 국민성장펀드 매칭 출자를 개시",
        "블라인드 GP당 최대 300억원을 지원",
        "선정 GP의 민간 펀딩 부담이 완화될 전망",
    ]


def test_ai_enrichment_summary_lines_override_review_summary() -> None:
    url = "https://dealsite.co.kr/articles/ai-enrichment-test"
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        (out_dir / "daily_news_ai_enrichment_20260611.json").write_text(
            json.dumps(
                {
                    "report_date": "2026-06-11",
                    "provider": "local-rule",
                    "articles": [
                        {
                            "source_url": url,
                            "normalized_source_url": url,
                            "summary_text": "기존 요약문은 보강 파일에서 내려온 문장입니다",
                            "summary_lines": ["출자사업 이벤트 확정", "GP 선정 절차 진행", "LP 관점 후속 추적 필요"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        context = read_ai_enrichment_context(out_dir)
    payload = article_payload_rows(
        [{"title": "AI 보강 테스트", "source": "딜사이트", "url": url, "section": "LP"}],
        context,
    )
    assert payload[0]["summaryLines"] == ["출자사업 이벤트 확정", "GP 선정 절차 진행", "LP 관점 후속 추적 필요"]
    assert payload[0]["summaryText"] == "기존 요약문은 보강 파일에서 내려온 문장입니다"


def test_ai_enrichment_summary_lines_reject_public_tone_violations() -> None:
    url = "https://dealsite.co.kr/articles/ai-summary-sanitize-test"
    title = "성장금융, 국민성장펀드 매칭 출자"
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        (out_dir / "daily_news_ai_enrichment_20260611.json").write_text(
            json.dumps(
                {
                    "report_date": "2026-06-11",
                    "provider": "command",
                    "articles": [
                        {
                            "title": title,
                            "source_url": url,
                            "normalized_source_url": url,
                            "summary_lines": [
                                title,
                                "오늘 좋은 기사가 나왔어요",
                                "source evidence 확인 필요",
                                "블라인드 GP당 최대 300억원 매칭",
                                "민간 펀딩 부담 완화 포인트",
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        context = read_ai_enrichment_context(out_dir)
    payload = article_payload_rows(
        [{"title": title, "source": "딜사이트", "url": url, "section": "국민성장펀드"}],
        context,
    )
    assert payload[0]["summaryLines"] == [
        "블라인드 GP당 최대 300억원 매칭",
        "민간 펀딩 부담 완화 포인트",
    ]
    rejected_text = " ".join(payload[0]["summaryLines"])
    assert title not in rejected_text
    assert "나왔어요" not in rejected_text
    assert "source evidence" not in rejected_text


def test_ai_enrichment_section_suggestion_is_optional_public_override() -> None:
    url = "https://dealsite.co.kr/articles/ai-section-override-test"
    title = "국민성장펀드 잡은 IMM…레버리지는 없다"
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        (out_dir / "daily_news_ai_enrichment_20260611.json").write_text(
            json.dumps(
                {
                    "report_date": "2026-06-11",
                    "provider": "notebooklm-cli",
                    "articles": [
                        {
                            "title": title,
                            "source_url": url,
                            "normalized_source_url": url,
                            "section_suggestion": "GP",
                            "summary_lines": ["IMM의 국민성장펀드 출자 기반 펀드레이징 전략"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        context = read_ai_enrichment_context(out_dir)
    row = {"title": title, "source": "딜사이트", "url": url, "section": "국민성장펀드"}
    previous = os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS")
    try:
        os.environ.pop("NEWSLETTER_AI_APPLY_SECTIONS", None)
        default_payload = article_payload_rows([row], context)
        assert default_payload[0]["section"] == "국민성장펀드"

        os.environ["NEWSLETTER_AI_APPLY_SECTIONS"] = "1"
        applied_payload = article_payload_rows([row], context)
        assert applied_payload[0]["section"] == "GP"
        assert applied_payload[0]["subCategory"] == "Strategy"
    finally:
        if previous is None:
            os.environ.pop("NEWSLETTER_AI_APPLY_SECTIONS", None)
        else:
            os.environ["NEWSLETTER_AI_APPLY_SECTIONS"] = previous


def test_ai_enrichment_audit_marks_category_conflicts() -> None:
    rows = audit_rows(
        [
            {
                "news_id": "n1",
                "title": "국민성장펀드 잡은 IMM…레버리지는 없다",
                "current_category": "국민성장펀드",
                "section_tags": "NationalGrowthFund",
                "section_suggestion": "GP",
                "confidence": 0.82,
                "source_url": "https://example.com/imm",
            }
        ]
    )
    assert rows[0]["status"] == "conflict"
    assert rows[0]["current_section"] == "NationalGrowthFund"
    assert rows[0]["section_suggestion"] == "GP"


def test_ai_enrichment_prompt_contains_classification_boundaries() -> None:
    prompt = enrichment_prompt(
        "2026-06-11",
        [
            {
                "news_id": "n1",
                "title": "국민성장펀드 잡은 IMM…레버리지는 없다",
                "section_tags": "NationalGrowthFund",
                "summary_text": "IMM의 펀드레이징 전략이 핵심이다",
            }
        ],
    )
    assert "Classify by the article's main subject" in prompt
    assert "choose GP" in prompt
    assert "국민성장펀드 잡은 IMM" in prompt
    assert "investment professional scanning deal flow" in prompt
    assert "Do not repeat the article title" in prompt
    assert "event, line 2 numbers/parties/status, line 3 why it matters" in prompt


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


def test_national_growth_section_does_not_attach_kdb_context() -> None:
    patterns = read_lp_alias_patterns()
    kdb = next(pattern for pattern in patterns if pattern["lp_code"] == "kdb")
    moel_iaci = next(pattern for pattern in patterns if pattern["lp_code"] == "moel_iaci")
    assert "국민성장펀드" not in kdb["aliases"]
    assert "산재기금" in moel_iaci["aliases"]


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


def test_private_credit_conference_is_market_not_lp() -> None:
    row = {
        "publisher": "한국경제",
        "title": "먼로캐피탈 \"자산유동화대출은 일시적 유행 아닌 대체투자 핵심 대안\"[ASK 2026]",
        "summary_text": (
            "먼로캐피탈 매니징 디렉터가 자산 담보 대출과 사모대출 시장을 설명하고 "
            "글로벌 운용사의 저신용자 소비자금융 투자를 경계해야 한다고 말했다."
        ),
        "relevance_score": 7,
        "section_tags": "Credit",
        "topic_tags": "Credit,LP,Market,daily,private_credit",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://marketinsight.hankyung.com/article/202605271565r",
        "review_status": "auto",
    }
    assert primary_section(row) == "Market"


def test_gp_named_venture_mother_fund_start_is_gp() -> None:
    row = {
        "publisher": "딜사이트",
        "title": "키움인베 600억 벤처모펀드 출격",
        "summary_text": "12개 GP에 600억 중 400억 출자하고 프로젝트펀드에도 자금을 배정한다.",
        "relevance_score": 6,
        "section_tags": "Market",
        "topic_tags": "GP,LP,daily,publisher_watch",
        "document_type_tags": "",
        "gp_names": "키움인베스트먼트",
        "source_url": "https://dealsite.co.kr/articles/162594",
        "review_status": "auto",
    }
    assert primary_section(row) == "GP"


def test_finalized_markdown_section_is_preserved_for_public_site() -> None:
    assert editorial_section(
        {
            "title": "먼로캐피탈 \"자산유동화대출은 일시적 유행 아닌 대체투자 핵심 대안\"[ASK 2026]",
            "section": "Market",
            "finalized": "1",
        }
    ) == "Market"
    assert editorial_section(
        {
            "title": "키움인베 600억 벤처모펀드 출격",
            "section": "GP",
            "finalized": "1",
        }
    ) == "GP"


def test_public_payload_uses_brief_section_as_canonical() -> None:
    title = "[150조 머니무브] 에이티넘, '1조 펀드' 도전…관건은 하드캡"
    payload = article_payload_rows(
        [
            {
                "title": title,
                "source": "블로터",
                "url": "https://www.bloter.net/news/articleView.html?idxno=664361",
                "section": "GP",
            }
        ]
    )
    assert payload[0]["section"] == "GP"
    assert payload[0]["rawSection"] == "GP"
    assert payload[0]["subCategory"] == "Fundraising"


def test_deal_value_reassessment_subtype_is_not_acquisition() -> None:
    row = {
        "title": "F&F 숨겨진 가치...테일러메이드에서 터질까",
        "section": "Deal",
    }
    assert editorial_subtype(row, "Deal") == "Ownership"


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


def test_meta_description_pef_signal_feeds_scoring_excerpt() -> None:
    rules = load_rules(DEFAULT_RULES)
    scoring_excerpt = build_scoring_excerpt(
        "",
        "국내 사모펀드(PEF) 운용사가 인수 후 첫 밸류업 과제로 광고 수익성 개선을 설정했다.",
        "사모펀드 운용사의 포트폴리오 밸류업 기사다.",
    )
    scored = score_document("에이치PE, 디시인사이드 광고 수익성 손본다", scoring_excerpt, "", rules, [])
    tags = {tag["tag_value"] for tag in scored["tags"] if tag["tag_type"] == "topic"}

    assert scored["score"] >= 8
    assert "PEF" in tags
    assert "Deal" in tags


def test_recent_gap_publishers_and_sources_are_configured() -> None:
    assert infer_publisher("https://www.sentv.co.kr/article/view/sentv202606050046") == "서울경제TV"
    assert infer_publisher("https://www.kbanker.co.kr/news/articleView.html?idxno=225136") == "대한금융신문"
    assert infer_publisher("https://www.autodaily.co.kr/news/articleView.html?idxno=544665") == "엠투데이"
    assert infer_publisher("https://www.pinpointnews.co.kr/news/articleView.html?idxno=458008") == "핀포인트뉴스"

    sources = {source.source_code: source for source in load_sources(DEFAULT_SOURCES)}
    for source_code in [
        "naver_publisher_4th_pef",
        "naver_publisher_ebn_hahn",
        "naver_publisher_kbanker_pef",
        "naver_publisher_newstof_imm",
        "naver_pef_blockdeal",
        "naver_pef_portfolio_rental",
    ]:
        assert source_code in sources
        assert sources[source_code].is_active
    assert "인베스트조선" in sources["naver_pef_growth_fund"].allowed_publishers


def test_recent_gap_publishers_have_brand_icons() -> None:
    urls = [
        "https://www.pinpointnews.co.kr/news/articleView.html?idxno=458008",
        "https://www.ebn.co.kr/news/articleView.html?idxno=1711446",
        "https://www.autodaily.co.kr/news/articleView.html?idxno=544665",
        "https://www.junggi.co.kr/news/articleView.html?idxno=36670",
        "https://www.4th.kr/news/articleView.html?idxno=2112782",
        "https://www.kbanker.co.kr/news/articleView.html?idxno=225136",
        "https://www.hani.co.kr/arti/society/labor/1262172.html",
        "https://www.mt.co.kr/world/2026/06/07/2026060115404184841",
        "https://www.asiae.co.kr/article/2026060823584349025",
    ]
    icons = [brand_logo_url(url) for url in urls]
    assert all(icons)
    assert not any(icon.lower().endswith(".ico") for icon in icons)


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


def test_quoted_fund_challenge_is_gp_fundraising() -> None:
    title = "[150조 머니무브] 에이티넘, '1조 펀드' 도전…관건은 하드캡"
    row = {
        "publisher": "블로터",
        "title": title,
        "summary_text": "에이티넘인베스트먼트가 신규 블라인드펀드 조성과 펀드레이징에 나선다.",
        "relevance_score": 9,
        "section_tags": "LP",
        "topic_tags": "LP,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.bloter.net/news/articleView.html?idxno=664361",
        "review_status": "auto",
    }
    rules = load_rules(DEFAULT_RULES)
    scored = score_document(title, row["summary_text"], "", rules, [])
    topics = {str(tag["tag_value"]) for tag in scored["tags"] if str(tag["tag_type"]) == "topic"}
    assert "GP" in topics
    assert "Fundraising" in topics
    assert primary_section(row) == "GP"
    assert editorial_section({"title": title, "section": "LP"}) == "GP"
    assert editorial_subtype({"title": title, "section": "GP"}, "GP") == "Fundraising"


def test_retirement_plan_private_equity_access_is_lp_not_deal() -> None:
    title = "트럼프식 '투자의 민주화'...퇴직연금을 사모펀드에 개방하면?"
    row = {
        "publisher": "머니투데이",
        "title": title,
        "summary_text": "401k 퇴직연금의 사모펀드 접근 허용과 개인 투자자 자산배분 변화를 다룬다.",
        "relevance_score": 8,
        "section_tags": "Deal",
        "topic_tags": "Deal,PEF",
        "document_type_tags": "report",
        "gp_names": "",
        "source_url": "https://www.mt.co.kr/stock/test",
        "review_status": "auto",
    }
    rules = load_rules(DEFAULT_RULES)
    scored = score_document(title, row["summary_text"], "", rules, [])
    topics = {str(tag["tag_value"]) for tag in scored["tags"] if str(tag["tag_type"]) == "topic"}
    assert "LP" in topics
    assert primary_section(row) == "LP"
    assert editorial_section({"title": title, "section": "Deal"}) == "LP"
    assert editorial_subtype({"title": title, "section": "LP"}, "LP") == "Allocation"


def test_20260608_category_regressions() -> None:
    rows = [
        (
            {
                "publisher": "딜사이트",
                "title": "3년 만의 귀환…스카이레이크 5000+α 펀드레이징",
                "summary_text": "국민성장펀드서 2000억 확보하며 하반기까지 멀티 클로징 전략을 세웠다.",
                "section_tags": "LP",
                "topic_tags": "GP,NationalGrowthFund,PEF",
                "document_type_tags": "",
                "gp_names": "스카이레이크에쿼티파트너스",
                "source_url": "https://dealsite.co.kr/articles/163035",
                "review_status": "auto",
            },
            "GP",
            "Fundraising",
        ),
        (
            {
                "publisher": "딜사이트",
                "title": "[2026 농모태펀드] 농금원 GP 도전하는 송현…연패 사슬 끊는다",
                "summary_text": "송현인베스트먼트가 농업정책보험금융원 출자 사업에 지원하며 신규 펀드 결성에 도전한다.",
                "section_tags": "Market",
                "topic_tags": "GP,LP,PEF",
                "document_type_tags": "",
                "gp_names": "송현인베스트먼트",
                "source_url": "https://dealsite.co.kr/articles/163079",
                "review_status": "auto",
            },
            "GP",
            "Fundraising",
        ),
        (
            {
                "publisher": "딜사이트",
                "title": "[2026 농모태펀드] 비전벤처스 티인베와 손잡고…첫 200억 블라인드",
                "summary_text": "비전벤처스가 티인베스트먼트와 함께 농모태펀드 출자사업에 도전하며 200억원 규모 블라인드펀드 결성을 추진한다.",
                "section_tags": "LP",
                "topic_tags": "GP,LP,PEF",
                "document_type_tags": "",
                "gp_names": "비전벤처스, 티인베스트먼트",
                "source_url": "https://dealsite.co.kr/articles/163015",
                "review_status": "auto",
            },
            "GP",
            "Fundraising",
        ),
        (
            {
                "publisher": "블로터",
                "title": "미래에셋벤처, 3000억 펀딩 목표…프리IPO·메자닌 '5대5' 배분",
                "summary_text": "국민성장펀드 위탁운용사로 선정되며 3000억원 규모의 자펀드를 조성한다는 목표다.",
                "section_tags": "LP",
                "topic_tags": "Credit,Deal,PEF",
                "document_type_tags": "",
                "gp_names": "미래에셋벤처투자",
                "source_url": "https://www.bloter.net/news/articleView.html?idxno=664499",
                "review_status": "auto",
            },
            "GP",
            "Fundraising",
        ),
        (
            {
                "publisher": "뉴스톱",
                "title": "스틱인베스트, 랩지노믹스 CB 200억 투입",
                "summary_text": "스틱인베스트먼트가 랩지노믹스 전환사채(CB)를 인수했다.",
                "section_tags": "GP",
                "topic_tags": "Credit",
                "document_type_tags": "",
                "gp_names": "스틱인베스트먼트",
                "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45377",
                "review_status": "auto",
            },
            "Deal",
            "Financing",
        ),
        (
            {
                "publisher": "이투데이",
                "title": "[단독] 장외파생상품 진출 노리는 한양증권, 연내 라이선스 획득 '청신호'",
                "summary_text": "금감원 사전 협의 등 인프라 구축에 나섰다.",
                "section_tags": "Deal",
                "topic_tags": "GP,PEF",
                "document_type_tags": "press_release",
                "gp_names": "케이씨지아이",
                "source_url": "https://www.etoday.co.kr/news/view/2590880",
                "review_status": "auto",
            },
            "Market",
            "Regulation",
        ),
    ]
    for row, expected_section, expected_subtype in rows:
        assert primary_section(row) == expected_section
        public_section = editorial_section({"title": str(row["title"]), "section": expected_section})
        assert public_section == {"NationalGrowthFund": "국민성장펀드"}.get(expected_section, expected_section)
        assert editorial_subtype({"title": str(row["title"]), "section": public_section}, public_section) == expected_subtype
        normalized = dict(row)
        normalize_export_classification(normalized)
        assert normalized["section_tags"] == expected_section
        topics = {value for value in str(normalized["topic_tags"]).split(",") if value}
        if expected_section in {"Deal", "GP", "LP", "NationalGrowthFund"}:
            assert expected_section in topics
        if expected_section == "GP":
            assert "LP" not in topics
        if expected_section == "Deal":
            assert "GP" not in topics

    ownership = {"title": "에이치PE, 디시인사이드 ‘광고 수익성’ 손본다", "section": "Deal"}
    assert editorial_subtype(ownership, "Deal") == "Ownership"
    assert (
        editorial_subtype({"title": "1조원대 애큐온 매각 본입찰에 메리츠·한화생명 참여 [시그널]", "section": "Deal"}, "Deal")
        == "Auction"
    )
    assert (
        editorial_subtype({"title": "현대모비스 범퍼사업부 매각, '통인수 제안' 막판 변수로", "section": "Deal"}, "Deal")
        == "Auction"
    )


def test_20260609_editorial_quality_regressions() -> None:
    insurance = {
        "publisher": "한국경제",
        "title": '"계약 맺은후가 더 무서워"…M&A 보험 시장 커진다',
        "summary_text": "매도인 진술·보장 허위 때 보험사가 배상하는 시장 동향을 다룬다.",
        "relevance_score": 16,
        "section_tags": "Deal",
        "topic_tags": "Deal,PEF",
        "document_type_tags": "",
        "gp_names": "한국투자증권",
        "source_url": "https://www.hankyung.com/article/2026060840731",
        "review_status": "auto",
    }
    assert primary_section(insurance) == "Market"
    normalized_insurance = dict(insurance)
    normalize_export_classification(normalized_insurance)
    assert normalized_insurance["section_tags"] == "Market"
    assert "Deal" not in str(normalized_insurance["topic_tags"]).split(",")
    assert editorial_section({"title": str(insurance["title"]), "section": "Deal"}) == "Market"

    ai_market = {
        "publisher": "이데일리",
        "title": "AI 공포에 얼어붙은 PE…소프트웨어 M&A, 팬데믹 이후 '최저'",
        "summary_text": "AI가 소프트웨어 PE 인수 시장을 위축시켰다는 시장 통계 기사다.",
        "relevance_score": 10,
        "section_tags": "Deal",
        "topic_tags": "Deal,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.edaily.co.kr/News/Read?newsId=03578486645479752&mediaCodeNo=257",
        "review_status": "auto",
    }
    assert primary_section(ai_market) == "AI_PE"
    assert editorial_section({"title": str(ai_market["title"]), "section": "Deal"}) == "AI & PE"

    renaissance = {
        "publisher": "연합인포맥스",
        "title": "르네상스운용, '천보비엘에스' 800억 베팅…기관전용 PEF확장 '신호탄'",
        "summary_text": "르네상스자산운용이 천보비엘에스에 800억원을 투자했다.",
        "relevance_score": 18,
        "section_tags": "Market",
        "topic_tags": "",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://news.einfomax.co.kr/news/articleView.html?idxno=4418967",
        "review_status": "auto",
    }
    assert primary_section(renaissance) == "Deal"
    assert editorial_section({"title": str(renaissance["title"]), "section": "Market"}) == "Deal"

    law_firm = {
        "publisher": "조선비즈",
        "title": "법무법인 광장, 최대현 전 산업은행 수석부행장 영입",
        "summary_text": "기업금융·사모펀드(PEF)·해외투자 자문 역량 강화를 위한 고문 영입 기사다.",
        "relevance_score": 14,
        "section_tags": "GP",
        "topic_tags": "GP,PEF",
        "document_type_tags": "",
        "gp_names": "한국산업은행",
        "source_url": "https://biz.chosun.com/topics/law_firm/2026/06/08/example",
        "review_status": "auto",
    }
    quality_score, quality_reason = editorial_quality(law_firm)
    assert primary_section(law_firm) == "Market"
    assert quality_score < EXPORT_MIN_QUALITY_SCORE, quality_reason
    assert not should_export_row({**law_firm, "quality_score": quality_score})
    normalized_law_firm = dict(law_firm)
    normalize_export_classification(normalized_law_firm)
    assert normalized_law_firm["section_tags"] == "Market"
    assert "GP" not in str(normalized_law_firm["topic_tags"]).split(",")

    pwc = {
        "publisher": "더벨",
        "title": "삼일PwC, 곽윤구·최창윤·홍진오 앞세워 딜 리더십 재편",
        "summary_text": "대형 사모펀드(PEF) 대상 자문 조직 리더십 개편 기사다.",
        "relevance_score": 10,
        "section_tags": "Deal",
        "topic_tags": "Deal,PEF",
        "document_type_tags": "",
        "gp_names": "",
        "source_url": "https://www.thebell.co.kr/free/content/ArticleView.asp?key=202606051433525040104894",
        "review_status": "auto",
    }
    pwc_quality, pwc_reason = editorial_quality(pwc)
    assert primary_section(pwc) == "Market"
    assert pwc_quality < EXPORT_MIN_QUALITY_SCORE, pwc_reason

    bkl = {
        "publisher": "이투데이",
        "title": "태평양, 해외투자·M&A 자문 전력 보강…강형석·이진욱 변호사 영입",
        "summary_text": "법무법인 태평양이 기업 자문 및 인수·합병 분야 전력을 보강했다.",
        "relevance_score": 19,
        "section_tags": "Market",
        "topic_tags": "",
        "document_type_tags": "press_release",
        "gp_names": "",
        "source_url": "https://www.etoday.co.kr/news/view/2592500",
        "review_status": "auto",
    }
    bkl_quality, bkl_reason = editorial_quality(bkl)
    assert primary_section(bkl) == "Market"
    assert bkl_quality < EXPORT_MIN_QUALITY_SCORE, bkl_reason
    assert not should_export_row({**bkl, "quality_score": bkl_quality})

    kakao_lp = {"title": "카카오인베, 미국서 정용진 맞손 '이마트 주도 사모펀드 출자'", "section": "LP"}
    assert editorial_section(kakao_lp) == "LP"
    assert editorial_subtype(kakao_lp, "LP") == "Allocation"


def test_advisory_people_event_dedupe_key() -> None:
    chosun = {
        "title": "법무법인 광장, 최대현 전 산업은행 수석부행장 영입",
        "summary_text": "KDB인베스트먼트 대표를 역임한 최대현 고문 영입",
        "section_tags": "GP",
    }
    mk = {
        "title": "최대현 前 산은 수석부행장, 법무법인 광장 고문으로 합류",
        "summary_text": "기업금융·사모펀드(PEF)·해외투자 등 역량 강화",
        "section_tags": "Deal",
    }
    assert event_dedupe_key(chosun) == "advisory_people:gwangjang_choi_daehyun"
    assert event_dedupe_key(chosun) == event_dedupe_key(mk)


def test_gp_continuation_fund_drops_conflicting_deal_topic() -> None:
    row = {
        "publisher": "블로터",
        "title": "큐캐피탈, 두산건설 장기보유로 가닥…'컨티뉴에이션 펀드' 이관",
        "summary_text": "큐캐피탈파트너스가 포트폴리오인 두산건설을 장기 보유하기 위해 컨티뉴에이션 펀드로 이관하는 방안을 고려하고 있다.",
        "relevance_score": 10,
        "section_tags": "GP",
        "topic_tags": "Deal,GP,PEF,Fundraising",
        "document_type_tags": "",
        "gp_names": "큐캐피탈파트너스",
        "source_url": "https://www.bloter.net/news/articleView.html?idxno=664856",
        "review_status": "auto",
    }
    assert primary_section(row) == "GP"
    normalized = dict(row)
    normalize_export_classification(normalized)
    topic_tags = set(str(normalized["topic_tags"]).split(","))
    assert normalized["section_tags"] == "GP"
    assert normalized["tag_version"] == TAG_TAXONOMY_VERSION
    assert "GP" in topic_tags
    assert "Fundraising" in topic_tags
    assert "Deal" not in topic_tags


def test_article_payload_carries_gp_profile_link_contract() -> None:
    payload = article_payload_rows(
        [
            {
                "section": "GP",
                "title": "스톤브릿지, 블라인드펀드 결성",
                "source": "더벨",
                "url": "https://example.com/article",
            }
        ],
        {
            "https://example.com/article": {
                "gpNames": ["스톤브릿지캐피탈"],
                "gpProfileLinks": [
                    {"id": "42", "name": "스톤브릿지캐피탈", "url": "gp-42.html"},
                ],
                "lpNames": [],
                "lpProfileLinks": [],
                "searchTerms": [],
            }
        },
    )
    assert payload[0]["tagVersion"] == TAG_TAXONOMY_VERSION
    assert payload[0]["gpNames"] == ["스톤브릿지캐피탈"]
    assert payload[0]["gpProfileLinks"] == [{"id": "42", "name": "스톤브릿지캐피탈", "url": "gp-42.html"}]


def test_naver_source_readiness_requires_credentials() -> None:
    old_id = os.environ.pop("NAVER_CLIENT_ID", None)
    old_secret = os.environ.pop("NAVER_CLIENT_SECRET", None)
    try:
        try:
            assert_source_family_readiness(
                [SimpleNamespace(source_kind="naver_news_api", source_code="naver_pef_core_samo")]
            )
        except RuntimeError as exc:
            assert "NAVER_CLIENT_ID" in str(exc)
        else:
            raise AssertionError("Naver readiness check did not fail without credentials")
    finally:
        if old_id is not None:
            os.environ["NAVER_CLIENT_ID"] = old_id
        if old_secret is not None:
            os.environ["NAVER_CLIENT_SECRET"] = old_secret


def test_validation_quality_gate_catches_category_tag_and_archive_mismatches() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "exports"
        site_dir = root / "site"
        out_dir.mkdir()
        site_dir.mkdir()
        report_date = "2026-06-08"
        dated = report_date.replace("-", "")
        gp_title = "미래에셋벤처, 3000억 펀딩 목표…프리IPO·메자닌 '5대5' 배분"
        deal_title = "1조원대 애큐온 매각 본입찰에 메리츠·한화생명 참여 [시그널]"

        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join(
                [
                    f"일자 : {report_date}",
                    "",
                    "[GP]",
                    f"- [{gp_title}](https://example.com/gp)",
                    "  출처: 블로터",
                    "",
                    "[Deal]",
                    f"- [{deal_title}](https://example.com/deal)",
                    "  출처: 서울경제",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"블로터,\"{gp_title}\",https://example.com/gp,https://example.com/gp,GP,LP,\"GP,LP,PEF\"",
                    f"서울경제,\"{deal_title}\",https://example.com/deal,https://example.com/deal,Deal,Deal,\"Deal,PEF\"",
                ]
            ),
            encoding="utf-8-sig",
        )
        (site_dir / "health.json").write_text(
            json.dumps({"report_date": report_date, "article_count": 2}, ensure_ascii=False),
            encoding="utf-8",
        )
        (site_dir / "archive.json").write_text(
            json.dumps(
                [
                    {
                        "reportDate": report_date,
                        "articles": [
                            {"title": gp_title, "url": "https://example.com/gp", "section": "GP", "subCategory": "Fundraising"},
                            {"title": deal_title, "url": "https://example.com/deal", "section": "Deal", "subCategory": "Exit"},
                        ],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = Validation()
        check_classification_quality(result, out_dir, report_date, site_dir)
        assert any("classification mismatch" in error for error in result.errors)
        assert any("topic tag conflicts" in error for error in result.errors)
        assert any("subCategory mismatch" in error and "expected=Auction" in error for error in result.errors)


def test_validation_warns_on_ai_category_conflicts() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "exports"
        out_dir.mkdir()
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        title = "국민성장펀드 잡은 IMM…레버리지는 없다"
        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join([f"일자 : {report_date}", "", "[국민성장펀드]", f"- [{title}](https://example.com/imm)", "  출처: 딜사이트", ""]),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"딜사이트,\"{title}\",https://example.com/imm,https://example.com/imm,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps(
                {
                    "report_date": report_date,
                    "provider": "command",
                    "articles": [
                        {
                            "news_id": "n1",
                            "title": title,
                            "source_url": "https://example.com/imm",
                            "normalized_source_url": "https://example.com/imm",
                            "section_suggestion": "GP",
                            "summary_lines": ["IMM의 국민성장펀드 출자 기반 펀드레이징 전략", "레버리지 없이 민간 매칭 부담을 관리"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = Validation()
        check_classification_quality(result, out_dir, report_date, None)
        assert not result.errors
        assert any("AI category conflict" in warning for warning in result.warnings)


def test_ai_enrichment_invalid_category_is_preserved_and_validation_errors() -> None:
    source_rows = [
        {
            "news_id": "n1",
            "title": "국민성장펀드 잡은 IMM…레버리지는 없다",
            "source_url": "https://example.com/imm",
            "normalized_source_url": "https://example.com/imm",
            "current_category": "국민성장펀드",
            "section_tags": "NationalGrowthFund",
            "summary_text": "IMM의 펀드레이징 전략이 핵심이다",
        }
    ]
    articles = normalize_ai_articles(
        {"articles": [{"news_id": "n1", "section_suggestion": "WrongCategory", "summary_lines": ["IMM 펀드레이징 전략"]}]},
        source_rows,
        "notebooklm-cli",
    )
    assert articles[0]["section_suggestion"] == ""
    assert articles[0]["section_suggestion_raw"] == "WrongCategory"
    assert articles[0]["suggestion_status"] == "invalid"

    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        title = source_rows[0]["title"]
        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join([f"일자 : {report_date}", "", "[국민성장펀드]", f"- [{title}](https://example.com/imm)", ""]),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "news_id,publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"n1,딜사이트,\"{title}\",https://example.com/imm,https://example.com/imm,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps({"report_date": report_date, "provider": "notebooklm-cli", "articles": articles}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = Validation()
        check_classification_quality(result, out_dir, report_date, None)
        assert any("invalid category" in error for error in result.errors)


def test_ai_enrichment_partial_external_output_is_validation_error() -> None:
    source_rows = [
        {
            "news_id": "n1",
            "title": "국민성장펀드 잡은 IMM…레버리지는 없다",
            "source_url": "https://example.com/imm",
            "normalized_source_url": "https://example.com/imm",
            "current_category": "국민성장펀드",
            "section_tags": "NationalGrowthFund",
            "summary_text": "IMM의 펀드레이징 전략이 핵심이다",
        },
        {
            "news_id": "n2",
            "title": "사모대출 시장 경고등",
            "source_url": "https://example.com/credit",
            "normalized_source_url": "https://example.com/credit",
            "current_category": "Market",
            "section_tags": "Market",
            "summary_text": "사모대출 시장 리스크가 커지고 있다",
        },
    ]
    articles = normalize_ai_articles(
        {"articles": [{"news_id": "n1", "section_suggestion": "GP", "summary_lines": ["IMM 펀드레이징 전략"]}]},
        source_rows,
        "notebooklm-cli",
    )
    assert len(articles) == 2
    assert articles[1]["suggestion_status"] == "missing"

    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join(
                [
                    f"일자 : {report_date}",
                    "",
                    "[국민성장펀드]",
                    "- [국민성장펀드 잡은 IMM…레버리지는 없다](https://example.com/imm)",
                    "[Market]",
                    "- [사모대출 시장 경고등](https://example.com/credit)",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "news_id,publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    "n1,딜사이트,\"국민성장펀드 잡은 IMM…레버리지는 없다\",https://example.com/imm,https://example.com/imm,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                    "n2,한국경제,\"사모대출 시장 경고등\",https://example.com/credit,https://example.com/credit,Market,Market,Market",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps({"report_date": report_date, "provider": "notebooklm-cli", "articles": articles}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = Validation()
        check_classification_quality(result, out_dir, report_date, None)
        assert any("missing category suggestion" in error for error in result.errors)


def test_validation_allows_archive_ai_section_when_apply_mode_is_enabled() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "exports"
        site_dir = root / "site"
        out_dir.mkdir()
        site_dir.mkdir()
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        title = "국민성장펀드 잡은 IMM…레버리지는 없다"
        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join([f"일자 : {report_date}", "", "[국민성장펀드]", f"- [{title}](https://example.com/imm)", "  출처: 딜사이트", ""]),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"딜사이트,\"{title}\",https://example.com/imm,https://example.com/imm,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps(
                {
                    "report_date": report_date,
                    "provider": "notebooklm-cli",
                    "articles": [
                        {
                            "title": title,
                            "source_url": "https://example.com/imm",
                            "normalized_source_url": "https://example.com/imm",
                            "section_suggestion": "GP",
                            "summary_lines": ["IMM의 국민성장펀드 출자 기반 펀드레이징 전략"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (site_dir / "health.json").write_text(
            json.dumps({"report_date": report_date, "article_count": 1}, ensure_ascii=False),
            encoding="utf-8",
        )
        (site_dir / "archive.json").write_text(
            json.dumps(
                [
                    {
                        "reportDate": report_date,
                        "articles": [
                            {"title": title, "url": "https://example.com/imm", "section": "GP", "subCategory": "Strategy"}
                        ],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        previous = os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS")
        try:
            os.environ["NEWSLETTER_AI_APPLY_SECTIONS"] = "1"
            result = Validation()
            check_classification_quality(result, out_dir, report_date, site_dir)
            assert not result.errors
            assert any("AI category conflict" in warning for warning in result.warnings)
        finally:
            if previous is None:
                os.environ.pop("NEWSLETTER_AI_APPLY_SECTIONS", None)
            else:
                os.environ["NEWSLETTER_AI_APPLY_SECTIONS"] = previous


def test_validation_blocks_archive_ai_field_and_summary_leakage() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "exports"
        site_dir = root / "site"
        out_dir.mkdir()
        site_dir.mkdir()
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        title = "성장금융, 국민성장펀드 매칭 출자"
        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join([f"일자 : {report_date}", "", "[국민성장펀드]", f"- [{title}](https://example.com/ngf)", ""]),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"딜사이트,\"{title}\",https://example.com/ngf,https://example.com/ngf,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps(
                {
                    "report_date": report_date,
                    "provider": "local-rule",
                    "articles": [
                        {
                            "title": title,
                            "source_url": "https://example.com/ngf",
                            "normalized_source_url": "https://example.com/ngf",
                            "section_suggestion": "NationalGrowthFund",
                            "summary_lines": ["성장금융 매칭 출자"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (site_dir / "health.json").write_text(
            json.dumps({"report_date": report_date, "article_count": 1}, ensure_ascii=False),
            encoding="utf-8",
        )
        (site_dir / "archive.json").write_text(
            json.dumps(
                [
                    {
                        "reportDate": report_date,
                        "articles": [
                            {
                                "title": title,
                                "url": "https://example.com/ngf",
                                "section": "국민성장펀드",
                                "subCategory": "정책펀드",
                                "provider": "notebooklm-cli",
                                "summaryLines": [title, "오늘 좋은 기사가 나왔어요"],
                            }
                        ],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = Validation()
        check_classification_quality(result, out_dir, report_date, site_dir)
        assert any("leaks internal AI fields" in error for error in result.errors)
        assert any("unusable public summaryLines" in error for error in result.errors)


def test_ai_backtest_summary_counts_audit_statuses() -> None:
    with TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        report_date = "2026-06-11"
        dated = report_date.replace("-", "")
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "news_id,publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    "n1,딜사이트,\"국민성장펀드 잡은 IMM…레버리지는 없다\",https://example.com/imm,https://example.com/imm,국민성장펀드,NationalGrowthFund,NationalGrowthFund",
                    "n2,한국경제,\"사모대출 시장 경고등\",https://example.com/credit,https://example.com/credit,Market,Market,Market",
                ]
            ),
            encoding="utf-8-sig",
        )
        (out_dir / f"daily_news_ai_enrichment_{dated}.json").write_text(
            json.dumps(
                {
                    "report_date": report_date,
                    "provider": "notebooklm-cli",
                    "article_count": 2,
                    "articles": [
                        {
                            "title": "국민성장펀드 잡은 IMM…레버리지는 없다",
                            "source_url": "https://example.com/imm",
                            "section_suggestion": "GP",
                            "summary_lines": ["IMM의 국민성장펀드 기반 펀드레이징 전략"],
                        },
                        {
                            "title": "사모대출 시장 경고등",
                            "source_url": "https://example.com/credit",
                            "section_suggestion": "Market",
                            "summary_lines": ["사모대출 시장 리스크 확대"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_ai_enrichment_audit_{dated}.csv").write_text(
            "\n".join(
                [
                    "news_id,title,current_section,section_suggestion,section_suggestion_raw,suggestion_status,status,confidence,notes,source_url",
                    "n1,\"국민성장펀드 잡은 IMM…레버리지는 없다\",NationalGrowthFund,GP,GP,conflict,conflict,0.8,,https://example.com/imm",
                    "n2,\"사모대출 시장 경고등\",Market,Market,Market,ok,ok,0.9,,https://example.com/credit",
                ]
            ),
            encoding="utf-8-sig",
        )
        row = summarize_date(report_date, out_dir)
        assert row["provider"] == "notebooklm-cli"
        assert row["review_count"] == 2
        assert row["article_count"] == 2
        assert row["status_ok"] == 1
        assert row["status_conflict"] == 1
        assert row["summary_missing"] == 0


def test_news_classification_golden_cases_pass_local_rules() -> None:
    golden_path = SERVICE_ROOT / "data" / "news_classification_golden.csv"
    rows = evaluate_classification_goldens(read_golden_csv_rows(golden_path), [])
    failures = [row for row in rows if row["local_status"] != "pass"]
    assert not failures


def test_validation_quality_gate_blocks_low_value_editorial_patterns() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_dir = root / "exports"
        site_dir = root / "site"
        out_dir.mkdir()
        site_dir.mkdir()
        report_date = "2026-06-09"
        dated = report_date.replace("-", "")
        advisory_title = "법무법인 광장, 최대현 전 산업은행 수석부행장 영입"
        market_title = '"계약 맺은후가 더 무서워"…M&A 보험 시장 커진다'

        (out_dir / f"daily_news_brief_{dated}.md").write_text(
            "\n".join(
                [
                    f"일자 : {report_date}",
                    "",
                    "[Market]",
                    f"- [{advisory_title}](https://example.com/advisory)",
                    "  출처: 조선비즈",
                    "",
                    "[Deal]",
                    f"- [{market_title}](https://example.com/insurance)",
                    "  출처: 한국경제",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (out_dir / f"daily_news_review_queue_{dated}.csv").write_text(
            "\n".join(
                [
                    "include_in_brief,publisher,title,source_url,normalized_source_url,current_category,section_tags,topic_tags",
                    f"Y,조선비즈,\"{advisory_title}\",https://example.com/advisory,https://example.com/advisory,Market,Market,\"\"",
                    f"Y,한국경제,\"{market_title}\",https://example.com/insurance,https://example.com/insurance,Deal,Deal,\"Deal,PEF\"",
                ]
            ),
            encoding="utf-8-sig",
        )
        (site_dir / "health.json").write_text(
            json.dumps({"report_date": report_date, "article_count": 2}, ensure_ascii=False),
            encoding="utf-8",
        )
        (site_dir / "archive.json").write_text(
            json.dumps(
                [
                    {
                        "reportDate": report_date,
                        "articles": [
                            {"title": advisory_title, "url": "https://example.com/advisory", "section": "Market", "subCategory": "Market View"},
                            {"title": market_title, "url": "https://example.com/insurance", "section": "Deal", "subCategory": "Acquisition"},
                        ],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = Validation()
        check_classification_quality(result, out_dir, report_date, site_dir)
        assert any("advisory people story" in error for error in result.errors)
        assert any("M&A market commentary" in error for error in result.errors)


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


def test_company_clipping_manual_corrections_for_20260602() -> None:
    cases = [
        (
            {
                "publisher": "이투데이",
                "title": "2000억대 체급 깬 대신PE, AI·반도체 4000억 펀드 시동…역대 최대 블라인드 도전",
                "summary_text": "대신프라이빗에쿼티가 블라인드펀드 조성에 나섰다.",
                "section_tags": "",
                "section_override_tags": "GP",
                "topic_tags": "GP,Fundraising,NationalGrowthFund",
                "document_type_tags": "",
                "gp_names": "대신프라이빗에쿼티",
                "source_url": "https://www.etoday.co.kr/news/view/2589138",
                "review_status": "force_include",
            },
            "GP",
        ),
        (
            {
                "publisher": "뉴스톱",
                "title": "국민성장펀드 잡은 파라투스, 최대 3000억 펀딩 탄력",
                "summary_text": "파라투스인베스트먼트의 펀드레이징 기사다.",
                "section_tags": "GP",
                "section_override_tags": "NationalGrowthFund",
                "topic_tags": "NationalGrowthFund,LP,GP",
                "document_type_tags": "",
                "gp_names": "파라투스인베스트먼트",
                "source_url": "https://www.newstopkorea.com/news/articleView.html?idxno=45256",
                "review_status": "force_include",
            },
            "NationalGrowthFund",
        ),
        (
            {
                "publisher": "아시아경제",
                "title": "국내 금융권 등 해외 사모대출 56조…당국 시스템 리스크 가능성 낮아",
                "summary_text": "해외 사모대출 시장과 금융권 리스크를 점검한다.",
                "section_tags": "LP",
                "section_override_tags": "Market",
                "topic_tags": "Credit,Market",
                "document_type_tags": "",
                "gp_names": "",
                "source_url": "https://view.asiae.co.kr/article/2026052611385718194",
                "review_status": "force_include",
            },
            "Market",
        ),
        (
            {
                "publisher": "조선비즈",
                "title": "“목표액 2배로 모았다” 엑시나, 2000억 투자유치… 신규 FI 10곳 이상",
                "summary_text": "엑시나 투자유치와 신규 재무적투자자 참여 기사다.",
                "section_tags": "Deal",
                "section_override_tags": "Deal",
                "topic_tags": "Deal",
                "document_type_tags": "",
                "gp_names": "",
                "source_url": "https://biz.chosun.com/stock/market_trend/2026/06/01/NZIEO2HXAZG5PGY4YH4KW2PFCA",
                "review_status": "force_include",
            },
            "Deal",
        ),
    ]
    for row, expected in cases:
        assert primary_section(row) == expected


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
        ("티케하우캐피탈 사모대출 시장 경고등…세컨더리 투자 주목해야", 3, "Credit"),
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
        test_force_include_previous_export_only_repeats_inside_current_window,
        test_google_news_decode_helpers,
        test_sedaily_mobile_amp_url_normalizes_to_desktop_article,
        test_common_news_tracking_params_are_removed,
        test_dealsite_category_suffix_url_normalizes_to_article,
        test_truncated_media_suffix_does_not_split_title_duplicates,
        test_gp_alias_overrides_cover_common_short_names,
        test_lp_directory_includes_seed_only_profiles_without_empty_profile_pages,
        test_lp_public_labels_do_not_expose_internal_taxonomy,
        test_official_lp_candidates_require_explicit_public_notice_allowance,
        test_lp_notice_title_program_beats_generic_platform,
        test_lp_notice_fund_series_round_beats_generic_page_round,
        test_lp_notice_lifecycle_events_roll_into_one_business_card,
        test_article_payload_does_not_render_lp_as_gp_chip,
        test_article_summary_lines_use_investment_memo_tone,
        test_article_summary_lines_strip_newsroom_boilerplate,
        test_article_payload_carries_summary_lines_contract,
        test_ai_enrichment_summary_lines_override_review_summary,
        test_ai_enrichment_summary_lines_reject_public_tone_violations,
        test_ai_enrichment_section_suggestion_is_optional_public_override,
        test_ai_enrichment_audit_marks_category_conflicts,
        test_ai_enrichment_prompt_contains_classification_boundaries,
        test_kic_lp_alias_seed_feeds_article_context,
        test_national_growth_section_does_not_attach_kdb_context,
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
        test_private_credit_conference_is_market_not_lp,
        test_gp_named_venture_mother_fund_start_is_gp,
        test_finalized_markdown_section_is_preserved_for_public_site,
        test_public_payload_uses_brief_section_as_canonical,
        test_deal_value_reassessment_subtype_is_not_acquisition,
        test_company_gap_titles_keep_expected_sections_and_quality,
        test_company_gap_keyword_rules_cover_ai_fund_lp_scope_and_private_debt,
        test_meta_description_pef_signal_feeds_scoring_excerpt,
        test_recent_gap_publishers_and_sources_are_configured,
        test_recent_gap_publishers_have_brand_icons,
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
        test_quoted_fund_challenge_is_gp_fundraising,
        test_retirement_plan_private_equity_access_is_lp_not_deal,
        test_20260608_category_regressions,
        test_20260609_editorial_quality_regressions,
        test_advisory_people_event_dedupe_key,
        test_gp_continuation_fund_drops_conflicting_deal_topic,
        test_article_payload_carries_gp_profile_link_contract,
        test_naver_source_readiness_requires_credentials,
        test_validation_quality_gate_catches_category_tag_and_archive_mismatches,
        test_validation_warns_on_ai_category_conflicts,
        test_ai_enrichment_invalid_category_is_preserved_and_validation_errors,
        test_ai_enrichment_partial_external_output_is_validation_error,
        test_validation_allows_archive_ai_section_when_apply_mode_is_enabled,
        test_validation_blocks_archive_ai_field_and_summary_leakage,
        test_ai_backtest_summary_counts_audit_statuses,
        test_news_classification_golden_cases_pass_local_rules,
        test_validation_quality_gate_blocks_low_value_editorial_patterns,
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
