#!/usr/bin/env python
"""Targeted checks for LP notice lifecycle dedupe behavior."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.lp.src.build_lp_commitment_monitor import apply_schema, dedupe_stored_notices, infer_event_type, make_notice_row
from services.lp.src.lp_notice_identity import infer_notice_program_name, infer_notice_round_name, notice_business_key
from services.lp.src.lp_notice_view import (
    consolidate_lp_notice_display_items,
    lp_notice_business_round_name,
    lp_notice_display_group_key,
    lp_notice_effective_deadline_value,
    lp_notice_program_label,
    lp_notice_public_status,
    lp_notice_status,
    lp_notice_specific_program_name,
)


def test_dedupe_stored_notices_merges_lifecycle_events_into_one_business_card() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
        conn.execute("CREATE TABLE news_document(news_id INTEGER PRIMARY KEY, normalized_source_url TEXT)")
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        conn.execute("INSERT INTO lp_institution(lp_code, lp_name) VALUES (?, ?)", ("LP_TEST", "테스트 LP"))
        conn.execute(
            "INSERT INTO lp_commitment_source(source_code, lp_code, source_name, source_kind, locator) VALUES (?, ?, ?, ?, ?)",
            ("official", "LP_TEST", "official", "official", "https://example.test"),
        )
        rows = [
            (
                1,
                "LP_TEST",
                "official",
                "official",
                "https://example.test/notices/notice-001",
                "https://example.test/notices/notice-001",
                "[서울자치] 은행권 중견기업 밸류업펀드 3차 출자공고",
                "new_notice",
                "2026-06-01",
                "2026-06-01",
                "국민성장펀드",
                "3차",
                "중요한 공고입니다",
                "high",
                "최종 출자 공고",
                "",
                1,
                "candidate",
            ),
            (
                2,
                "LP_TEST",
                "official",
                "official",
                "https://example.test/notices/notice-002",
                "https://example.test/notices/notice-002",
                "은행권 중견기업 밸류업펀드 3차 서류심사 결과",
                "shortlist",
                "2026-06-02",
                "2026-06-16",
                "국민성장펀드",
                "3차",
                "서류심사 진행",
                "medium",
                "후보 GP 공지",
                "IMM PE",
                1,
                "candidate",
            ),
            (
                3,
                "LP_TEST",
                "official",
                "official",
                "https://example.test/notices/notice-003",
                "https://example.test/notices/notice-003",
                "은행권 중견기업 밸류업펀드 3차 최종 선정 결과",
                "final_selection",
                "2026-06-03",
                "2026-06-16",
                "은행권 중견기업 밸류업펀드",
                "3차",
                "최종 선정 결과",
                "low",
                "최종 선정",
                "",
                1,
                "candidate",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO lp_commitment_notice(
                    notice_id, lp_code, source_code, source_type,
                    notice_url, normalized_notice_url, title, event_type,
                    event_date, application_deadline, program_name, round_name,
                    raw_excerpt, confidence, confidence_note,
                    selected_gp_names, public_visible, monitor_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()

        hidden = dedupe_stored_notices(conn)

        visible_rows = conn.execute(
            "SELECT notice_id, program_name, round_name, public_visible, selected_gp_names "
            "FROM lp_commitment_notice WHERE lp_code='LP_TEST' ORDER BY notice_id"
        ).fetchall()
    finally:
        conn.close()

    assert hidden == 2
    assert visible_rows[0] == (1, "은행권 중견기업 밸류업펀드", "3차", 1, "IMM PE")
    assert visible_rows[1][3] == 0
    assert visible_rows[2][3] == 0


def test_past_deadline_notice_does_not_get_new_closed_event_date() -> None:
    event_type = infer_event_type(
        "2025 하반기 중소중견기업 해외진출 펀드 출자사업 공고",
        "notice",
        "2025-09-03",
        "2026-06-07",
    )

    assert event_type == "new_notice"


def test_official_notice_without_announced_date_does_not_sort_as_today_when_deadline_is_past() -> None:
    row = make_notice_row(
        lp_code="kobc",
        source_code="kobc_notice",
        source_type="official",
        notice_url="https://example.test/kobc",
        title="2026년 해운산업 ESG지원펀드 사업 공모 시행 안내",
        announced_date="",
        fallback_year=2026,
        report_date="2026-06-07",
        text="홍보센터 ESG경영 주요사업 공지사항 2026년 해운산업 ESG지원펀드 사업 공모 시행 안내 접수마감: 2026-05-22",
        gp_names="",
        raw_excerpt="",
    )

    assert row["event_date"] == "2026-05-22"
    assert row["program_name"] == "2026년 해운산업 ESG지원펀드"


def test_stale_shortlist_is_public_history_not_current_shortlist() -> None:
    item = {
        "businessStatus": "shortlist",
        "latestEventDate": "2025-09-17",
        "applicationDeadline": "2025-09-04",
    }

    assert lp_notice_public_status(item, "2026-06-07") == "history"


def test_future_deadline_overrides_stale_business_status() -> None:
    item = {
        "businessStatus": "history",
        "eventType": "deadline_soon",
        "eventDate": "2026-05-27",
        "applicationDeadline": "2026-06-10",
    }

    assert lp_notice_public_status(item, "2026-06-07") == "open"


def test_deadline_soon_notice_consolidates_as_open_business_card() -> None:
    notices = [
        {
            "noticeId": "15925",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "title": "【선정공고】「국민성장펀드(간접투자분야) 정책성펀드」2026년 2차 위탁운용사 선정계획 공고",
            "programName": "국민성장펀드",
            "roundName": "2차",
            "eventType": "deadline_soon",
            "eventDate": "2026-05-27",
            "applicationDeadline": "2026-06-10",
            "stage": "notice",
            "events": [
                {
                    "noticeId": "15925",
                    "title": "【선정공고】「국민성장펀드(간접투자분야) 정책성펀드」2026년 2차 위탁운용사 선정계획 공고",
                    "eventType": "deadline_soon",
                    "eventDate": "2026-05-27",
                    "stage": "notice",
                }
            ],
        }
    ]

    [item] = consolidate_lp_notice_display_items(notices, "2026-06-07")

    assert item["businessStatus"] == "open"
    assert item["businessStageLabel"] == "공고중"
    assert lp_notice_public_status(item, "2026-06-07") == "open"
    assert item["events"][0]["status"] == "open"
    assert item["events"][0]["applicationDeadline"] == "2026-06-10"


def test_selection_status_beats_future_deadline_on_business_card() -> None:
    notices = [
        {
            "noticeId": "notice",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "title": "은행권 중견기업 밸류업펀드 3차 출자공고",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
            "eventType": "new_notice",
            "eventDate": "2026-06-01",
            "applicationDeadline": "2026-06-30",
        },
        {
            "noticeId": "result",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "title": "은행권 중견기업 밸류업펀드 3차 최종 선정 결과",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
            "eventType": "final_selection",
            "eventDate": "2026-06-10",
            "applicationDeadline": "2026-06-30",
        },
    ]

    [item] = consolidate_lp_notice_display_items(notices, "2026-06-12")

    assert item["businessStatus"] == "result"
    assert item["businessStageLabel"] == "선정완료"
    assert lp_notice_public_status(item, "2026-06-12") == "result"


def test_shortlist_status_beats_future_deadline_on_business_card() -> None:
    notices = [
        {
            "noticeId": "notice",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "title": "은행권 중견기업 밸류업펀드 3차 출자공고",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
            "eventType": "new_notice",
            "eventDate": "2026-06-01",
            "applicationDeadline": "2026-06-30",
        },
        {
            "noticeId": "shortlist",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "title": "은행권 중견기업 밸류업펀드 3차 서류심사 결과",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
            "eventType": "shortlist",
            "eventDate": "2026-06-10",
            "applicationDeadline": "2026-06-30",
        },
    ]

    [item] = consolidate_lp_notice_display_items(notices, "2026-06-12")

    assert item["businessStatus"] == "shortlist"
    assert item["businessStageLabel"] == "1차 선정"
    assert lp_notice_public_status(item, "2026-06-12") == "shortlist"


def test_stale_deadline_does_not_close_recent_notice_card() -> None:
    item = {
        "eventType": "new_notice",
        "eventDate": "2026-06-04",
        "applicationDeadline": "2024-05-30",
    }

    assert lp_notice_effective_deadline_value(item) == ""
    assert lp_notice_status(item, "2026-06-07") == "open"
    assert lp_notice_public_status(item, "2026-06-07") == "open"


def test_consolidation_drops_cross_year_stale_lifecycle_event() -> None:
    notices = [
        {
            "noticeId": "new",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2026-06-04",
            "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
        },
        {
            "noticeId": "old",
            "lpCode": "kgrowth",
            "lpName": "한국성장금융",
            "sourceType": "official",
            "eventType": "new_notice",
            "eventDate": "2024-05-08",
            "applicationDeadline": "2024-05-30",
            "title": "은행권 중견기업 밸류업펀드 위탁운용사 선정계획 공고",
            "programName": "은행권 중견기업 밸류업펀드",
            "roundName": "3차",
        },
    ]

    [item] = consolidate_lp_notice_display_items(notices, "2026-06-07")

    assert item["businessStatus"] == "open"
    assert [event["noticeId"] for event in item["events"]] == ["new"]


def test_dedupe_normalizes_no_space_round_notation_as_same_business() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
        conn.execute("CREATE TABLE news_document(news_id INTEGER PRIMARY KEY, normalized_source_url TEXT)")
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        conn.execute("INSERT INTO lp_institution(lp_code, lp_name) VALUES (?, ?)", ("LP_TEST", "테스트 LP"))
        conn.execute(
            "INSERT INTO lp_commitment_source(source_code, lp_code, source_name, source_kind, locator) VALUES (?, ?, ?, ?, ?)",
            ("official", "LP_TEST", "official", "official", "https://example.test"),
        )
        rows = [
            (
                1,
                "LP_TEST",
                "official",
                "official",
                "https://example.test/notices/notice-001",
                "https://example.test/notices/notice-001",
                "[서울자치]은행권 중견기업 밸류업펀드3차 출자공고",
                "new_notice",
                "2026-06-01",
                "2026-06-01",
                "국민성장펀드",
                "",
                "무식별 공고",
                "high",
                "최종 출자 공고",
                "",
                1,
                "candidate",
            ),
            (
                2,
                "LP_TEST",
                "official",
                "official",
                "https://example.test/notices/notice-002",
                "https://example.test/notices/notice-002",
                "은행권 중견기업 밸류업펀드3차 서류심사 결과",
                "shortlist",
                "2026-06-10",
                "2026-06-16",
                "모태펀드",
                "",
                "서류심사 진행",
                "medium",
                "후보 GP 공지",
                "IMM PE",
                1,
                "candidate",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO lp_commitment_notice(
                    notice_id, lp_code, source_code, source_type,
                    notice_url, normalized_notice_url, title, event_type,
                    event_date, application_deadline, program_name, round_name,
                    raw_excerpt, confidence, confidence_note,
                    selected_gp_names, public_visible, monitor_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()

        hidden = dedupe_stored_notices(conn)

        visible_rows = conn.execute(
            """
            SELECT notice_id, program_name, round_name, public_visible, selected_gp_names
            FROM lp_commitment_notice
            WHERE lp_code='LP_TEST'
            ORDER BY notice_id
            """
        ).fetchall()
    finally:
        conn.close()

    assert hidden == 1
    assert visible_rows[0] == (1, "은행권 중견기업 밸류업펀드", "3차", 1, "IMM PE")
    assert visible_rows[1][3] == 0


def test_identity_module_and_display_grouping_share_business_key() -> None:
    stored_row = {
        "lp_code": "kgrowth",
        "title": "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
        "program_name": "국민성장펀드",
        "round_name": "3차",
        "raw_excerpt": "",
    }
    display_row = {
        "lpCode": "kgrowth",
        "title": stored_row["title"],
        "programName": "국민성장펀드",
        "roundName": "3차",
    }

    assert infer_notice_program_name(stored_row) == "은행권 중견기업 밸류업펀드"
    assert infer_notice_round_name(stored_row) == "3차"
    assert lp_notice_specific_program_name(display_row) == "은행권 중견기업 밸류업펀드"
    assert lp_notice_business_round_name(display_row) == "3차"
    assert lp_notice_program_label(display_row) == "은행권 중견기업 밸류업펀드 3차"
    assert lp_notice_display_group_key(display_row) == ("kgrowth", notice_business_key(stored_row))


def test_notice_identity_prefers_clean_stored_program_over_noisy_body_candidate() -> None:
    display_row = {
        "lpCode": "kobc",
        "title": "2026년 해운산업 ESG지원펀드 사업 공모 시행 안내",
        "programName": "2026년 해운산업 ESG지원펀드",
        "rawExcerpt": "한국해양진흥공사 알림사항 목록에서 발견",
    }

    assert lp_notice_specific_program_name(display_row) == "2026년 해운산업 ESG지원펀드"
    assert lp_notice_program_label(display_row) == "2026년 해운산업 ESG지원펀드"


def test_notice_identity_uses_title_when_stored_program_is_body_sentence() -> None:
    display_row = {
        "lpCode": "post",
        "title": "(우정사업본부 공고 제2026-62호)2026년 우체국예금 해외주식 신흥국형 신규 운용사 선정 공고",
        "programName": "운용계획상 투자하고자 하는 운용유형과 동일하거나 유사한 펀드를 보유하고 최근 3년간 해당펀드",
        "roundName": "62호",
        "rawExcerpt": "우정사업본부 자산운용 거래기관 선정공고 목록에서 발견",
    }

    assert lp_notice_specific_program_name(display_row) == "2026년 우체국예금 해외주식 신흥국형 신규 운용사"
    assert lp_notice_program_label(display_row) == "2026년 우체국예금 해외주식 신흥국형 신규 운용사"


def test_notice_identity_rejects_crawler_sentence_and_uses_title_program() -> None:
    display_row = {
        "lpCode": "comwel",
        "title": "2024년 산재보험기금 대체투자상품(PEF, VC) 선정 공고",
        "programName": "고 목록에서 발견 을 통해 사실상 법령을 위반한 상태라고 판단되는 경우 최근 3년 내 자산건전성이 취약하거나 도덕적 해이 등으로 사회적 물의를 일으킨 운용사로서 펀드",
        "roundName": "1호",
        "rawExcerpt": "벤처투자종합포털 출자공고 목록에서 발견",
    }

    assert lp_notice_specific_program_name(display_row) == "2024년 산재보험기금 대체투자상품(PEF, VC)"
    assert lp_notice_program_label(display_row) == "2024년 산재보험기금 대체투자상품(PEF, VC)"


def test_notice_identity_rejects_rfp_criteria_sentences() -> None:
    cases = [
        (
            {
                "lpCode": "comwel",
                "title": "(수정공고)2025년 산재보험기금 하위운용사 유니버스 선정공고",
                "programName": "및 일임자산의 경우 운용성과를 제출하지 못할 경우 상세한 이유를 기재 - 추후 성과 미제출 사유가 고의·과실로 사실과 다른 것으로 밝혀질 경우",
                "roundName": "1호",
            },
            "2025년 산재보험기금 하위운용사 유니버스",
        ),
        (
            {
                "lpCode": "comwel",
                "title": "2025년 산재보험기금 대체투자상품(PEF) 선정 공고",
                "programName": "청산펀드(2020년 1월 1일 이후 청산펀드 기준",
                "roundName": "1호",
            },
            "2025년 산재보험기금 대체투자상품(PEF)",
        ),
    ]

    for display_row, expected_label in cases:
        assert lp_notice_program_label(display_row) == expected_label


def test_lifecycle_view_rolls_up_by_business_identity() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
        conn.execute("CREATE TABLE news_document(news_id INTEGER PRIMARY KEY, normalized_source_url TEXT)")
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        conn.execute("INSERT INTO lp_institution(lp_code, lp_name) VALUES (?, ?)", ("kgrowth", "한국성장금융"))
        conn.execute(
            "INSERT INTO lp_commitment_source(source_code, lp_code, source_name, source_kind, locator) VALUES (?, ?, ?, ?, ?)",
            ("official", "kgrowth", "official", "official", "https://example.test"),
        )
        rows = [
            (
                1,
                "kgrowth",
                "official",
                "official",
                "https://example.test/value-up-3-notice",
                "https://example.test/value-up-3-notice",
                "【선정공고】「은행권 중견기업 밸류업펀드(3차)」 위탁운용사 선정계획 공고",
                "new_notice",
                "2026-06-01",
                "2099-06-01",
                "국민성장펀드",
                "3차",
                "high",
                1,
                "candidate",
            ),
            (
                2,
                "kgrowth",
                "official",
                "official",
                "https://example.test/value-up-3-result",
                "https://example.test/value-up-3-result",
                "은행권 중견기업 밸류업펀드 3차 위탁운용사 선정 결과",
                "final_selection",
                "2026-06-20",
                "2099-06-01",
                "은행권 중견기업 밸류업펀드",
                "3차",
                "high",
                1,
                "candidate",
            ),
        ]
        for row in rows:
            conn.execute(
                """
                INSERT INTO lp_commitment_notice(
                    notice_id, lp_code, source_code, source_type,
                    notice_url, normalized_notice_url, title, event_type,
                    event_date, application_deadline, program_name, round_name,
                    confidence, public_visible, monitor_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()

        rollups = conn.execute(
            """
            SELECT program_name, round_name, notice_count, open_count, final_selection_count, deadline_status
            FROM v_lp_commitment_lifecycle_compare
            WHERE lp_code = 'kgrowth'
            """
        ).fetchall()
    finally:
        conn.close()

    assert rollups == [("은행권 중견기업 밸류업펀드", "3차", 2, 1, 1, "final_selection")]



def test_missing_round_does_not_borrow_from_another_year_or_asset() -> None:
    base = {"lpCode": "kgrowth", "sourceType": "official", "eventType": "new_notice", "programName": "은행권 중견기업 밸류업펀드", "title": "은행권 중견기업 밸류업펀드 위탁운용사 선정 공고"}
    for second in [
        {"eventDate": "2026-06-01", "assetClass": "PE"},
        {"eventDate": "2025-06-01", "assetClass": "VC"},
    ]:
        rows = [{**base, "noticeId": "old", "eventDate": "2025-06-01", "assetClass": "PE", "roundName": "3차"}, {**base, **second, "noticeId": "new", "roundName": "수시"}]
        merged = consolidate_lp_notice_display_items(rows, "2026-06-05")
        target = next(row for row in merged if row["noticeId"] == "new")
        assert lp_notice_business_round_name(target) == ""


if __name__ == "__main__":
    from scripts.run_regression_tests import run_module_tests
    raise SystemExit(run_module_tests(sys.modules[__name__]))
