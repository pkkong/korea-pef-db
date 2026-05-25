#!/usr/bin/env python
"""Fast no-network checks for daily news clipping business rules."""

from __future__ import annotations

from run_daily_news_pipeline import (
    EXPORT_MIN_QUALITY_SCORE,
    coverage_window_label,
    editorial_quality,
    google_query_for_report_date,
    is_in_coverage_window,
    primary_section,
    render_markdown,
    select_brief_rows,
    should_export_row,
)
from daily_news_common import to_iso_datetime


def test_coverage_window() -> None:
    assert "2026-04-29 08:30 ~ 2026-04-30 08:30" in coverage_window_label("2026-04-30")
    assert is_in_coverage_window("2026-04-29T14:00:00+09:00", "", "2026-04-30")
    assert not is_in_coverage_window("2026-04-30T09:00:00+09:00", "", "2026-04-30")


def test_google_backtest_window() -> None:
    query = google_query_for_report_date("사모펀드 when:1d", "2026-04-30")
    assert "after:2026-04-29" in query
    assert "before:2026-05-01" in query
    assert "when:1d" not in query


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
        test_google_backtest_window,
        test_weak_context_quality_penalty,
        test_strong_headline_quality,
        test_allocator_section_priority,
        test_gp_fundraising_and_deal_financing_sections,
        test_ai_pe_section_priority,
        test_ai_pe_reserved_in_brief_selection,
        test_lp_and_gp_reserved_in_full_brief_selection,
        test_gp_fundraising_beats_deal_word_when_title_is_fund_build,
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
