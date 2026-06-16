"""Standalone newsletter web app for Vercel."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from newsletter_data import filter_articles, grouped_sections, load_archive, select_issue


WEB_ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(WEB_ROOT / "static"), template_folder=str(WEB_ROOT / "templates"))


@app.get("/")
@app.get("/index.html")
@app.get("/daily-news")
@app.get("/daily-news.html")
def daily_news():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    active_issue = select_issue(archive, request.args.get("date", ""))
    query = request.args.get("q", "").strip()
    articles = filter_articles(active_issue, query)
    return render_template(
        "daily_news.html",
        archive=archive,
        active_issue=active_issue,
        query=query,
        articles=articles,
        sections=grouped_sections(articles),
        data_source=data_source,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


@app.get("/archive.json")
def archive_json():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    response = jsonify(archive)
    response.headers["X-Newsletter-Data-Source"] = data_source
    return response


@app.get("/health.json")
def health_json():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    active_issue = select_issue(archive)
    articles = active_issue.get("articles") or []
    return jsonify(
        {
            "status": "ok" if active_issue.get("reportDate") and articles else "empty",
            "service": "newsletter",
            "runtime": "vercel-flask",
            "data_source": data_source,
            "report_date": active_issue.get("reportDate", ""),
            "article_count": len(articles),
            "issue_count": len(archive),
        }
    )


@app.get("/api/newsletter/archive")
def api_archive():
    return archive_json()
