"""Backfill of late-distributed stories into published briefs (no network)."""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
for path in (SERVICE_ROOT / "src", REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import backfill_late_distributed_articles as backfill  # noqa: E402
from daily_news_common import DEFAULT_SCHEMA  # noqa: E402

NAVER = "Sun, 22 Nov 2026 13:33:00 +0900"


def database(rows):
    conn = sqlite3.connect(":memory:")
    conn.executescript(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO news_source(source_code, source_name, source_kind, locator) VALUES ('naver','N','naver_news_api','q')")
    conn.execute("INSERT INTO news_run(run_id, run_date, started_at, status) VALUES ('r','2026-11-23','2026-11-23T00:05:00+00:00','completed')")
    for news_id, url, publisher, title, published, feed, created, summary in rows:
        conn.execute(
            "INSERT INTO news_document(news_id, run_id, source_code, source_url, normalized_source_url, publisher, title,"
            " published_at, discovered_at, excerpt_text, relevance_score, relevance_label, is_pe_relevant, raw_payload_json, created_at)"
            " VALUES (?, 'r', 'naver', ?, ?, ?, ?, ?, '2026-11-23', ?, 0.95, 'high', 1, ?, ?)",
            (news_id, url, url, publisher, title, published, summary,
             json.dumps({"feed_item": {"published_at": feed}} if feed else {}), created),
        )
    return conn


def archive_article(index, title, url, section="GP", order=4):
    return {"id": f"clip-20261122-{index}", "rank": index, "section": section, "sectionOrder": order,
            "title": title, "url": url, "source": "더벨", "summaryText": "", "summaryLines": []}


STORY = (
    1, "https://www.sedaily.com/article/20116956", "서울경제",
    "제네시스PE, 8500억 2호 블라인드펀드 결성[시그널]", "2026-11-20T14:35:38+09:00", NAVER,
    "2026-11-22 05:07:38",
    "국내 사모펀드 운용사 제네시스프라이빗에쿼티가 8500억 원 규모로 2호 블라인드펀드를 결성했다. 경찰공제회와 고용보험기금 등이 출자했다.",
)


class LateDistributionBackfillTests(unittest.TestCase):
    def setUp(self):
        # The window of the 11/23 brief holds the Naver time; first seen on the 11/23 run.
        self.story = (STORY[0], STORY[1], STORY[2], STORY[3], STORY[4], NAVER, "2026-11-23 00:07:38", STORY[7])
        self.archive = [
            {"reportDate": "2026-11-23", "visibleDate": "2026.11.23", "basis": "", "articleCount": 2,
             "articles": [archive_article(0, "MBK, 日 와콤 인수 추진", "https://a.example/1", "Deal", 2),
                          archive_article(1, "시장 동향", "https://a.example/2", "Market", 5)]},
            {"reportDate": "2026-11-22", "visibleDate": "2026.11.22", "basis": "", "articleCount": 1,
             "articles": [archive_article(0, "다른 기사", "https://a.example/3")]},
        ]

    def test_story_goes_to_the_brief_of_its_distribution_window_once(self):
        with database([self.story]) as conn:
            updated, report = backfill.backfill(conn, self.archive, "2026-11-01", "2026-11-23")
        by_date = {item["report_date"]: item for item in report}
        self.assertEqual([a["title"] for a in by_date["2026-11-23"]["added"]],
                         ["제네시스PE, 8500억 2호 블라인드펀드 결성[시그널]"])
        self.assertEqual(by_date["2026-11-22"]["added"], [])
        entry = updated[0]
        self.assertEqual(entry["articleCount"], 3)
        self.assertEqual([a["rank"] for a in entry["articles"]], [0, 1, 2])
        self.assertEqual(entry["articles"][0]["title"], "MBK, 日 와콤 인수 추진")  # existing order kept
        added = next(a for a in entry["articles"] if "제네시스" in a["title"])
        self.assertEqual(added["id"], "clip-20261123-2")
        self.assertEqual(added["url"], STORY[1])
        self.assertTrue(added["summaryText"])
        self.assertIs(updated[1], self.archive[1])

    def test_story_already_in_any_brief_is_not_added_again(self):
        self.archive[1]["articles"].append(archive_article(1, STORY[3], STORY[1]))
        with database([self.story]) as conn:
            _, report = backfill.backfill(conn, self.archive, "2026-11-01", "2026-11-23")
        self.assertEqual(sum(len(item["added"]) for item in report), 0)

    def test_story_seen_by_an_earlier_run_or_outside_dates_is_left_out(self):
        earlier = self.story[:6] + ("2026-11-13 00:06:54",) + self.story[7:]
        with database([earlier]) as conn:
            _, report = backfill.backfill(conn, self.archive, "2026-11-01", "2026-11-23")
        self.assertEqual(sum(len(item["added"]) for item in report), 0)
        with database([self.story]) as conn:
            updated, report = backfill.backfill(conn, self.archive, "2026-11-01", "2026-11-22")
        self.assertEqual(sum(len(item["added"]) for item in report), 0)
        self.assertEqual(updated, self.archive)

    def test_write_site_rewrites_archive_file_and_both_embeds(self):
        with database([self.story]) as conn:
            updated, _ = backfill.backfill(conn, self.archive, "2026-11-01", "2026-11-23")
        with TemporaryDirectory() as folder:
            site = Path(folder)
            for name in backfill.ARCHIVE_HTML_FILES:
                (site / name).write_text(
                    "<html><body><div id=app></div>\n  <script>window.KPEF_DAILY_ARCHIVE = [];</script>"
                    "<script>window.KPEF_DAILY_ARCHIVE = [{\"reportDate\": \"x\"}];</script></body></html>",
                    encoding="utf-8",
                )
            with mock.patch.object(backfill, "apply_display_tags", side_effect=lambda entries, previous: entries):
                with self.assertRaises(RuntimeError):  # two embeds: refuse to guess
                    backfill.write_site(site, updated, self.archive)
                for name in backfill.ARCHIVE_HTML_FILES:
                    (site / name).write_text(
                        "<html><body>\n  <script>window.KPEF_DAILY_ARCHIVE = [{\"reportDate\": \"x\"}];</script></body></html>",
                        encoding="utf-8",
                    )
                backfill.write_site(site, updated, self.archive)
            self.assertEqual(json.loads((site / "archive.json").read_text(encoding="utf-8")), updated)
            for name in backfill.ARCHIVE_HTML_FILES:
                html = (site / name).read_text(encoding="utf-8")
                self.assertIn("제네시스PE, 8500억 2호 블라인드펀드 결성", html)
                self.assertEqual(html.count("window.KPEF_DAILY_ARCHIVE"), 1)


if __name__ == "__main__":
    unittest.main()
