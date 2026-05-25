# Daily News Clipping MVP

## Goal

Build the first maintainable `daily news clipping` layer for the Korea private equity workspace.

The first version focuses only on:

- daily article/report collection
- source URL based storage
- rule-based relevance scoring
- GP tagging against the existing Private Equity DB
- daily brief export in Markdown, HTML, and CSV

This intentionally does **not** include weekly deep-dives, LP org charts, people DB, or long-form editorial workflow.

## Design Principles

- Reuse the existing project pattern: `source list CSV -> SQLite -> exports`.
- Keep the first version dependency-light: standard library only.
- Treat `source_url` as the durable record key, with normalization that strips common tracking parameters.
- Keep editorial control in CSV files so maintenance does not require code edits.
- Preserve raw HTML under `data/raw/daily_news/` for later review and parser improvements.

## Files

- `services/newsletter/schema/daily_news.sql`
- `services/newsletter/data/news_sources.csv`
- `services/newsletter/data/news_keyword_rules.csv`
- `services/newsletter/data/news_manual_overrides.csv`
- `services/newsletter/data/news_gp_alias_overrides.csv`
- `services/newsletter/src/daily_news_common.py`
- `services/newsletter/src/run_daily_news_pipeline.py`

## Initial Source Strategy

The MVP mixes two source styles:

1. Query-based bootstrap feeds for broad coverage
2. Direct source pages for advisory/legal materials

Initial sources include:

- Google News Korea query feeds for core PEF, deals, and LP-related items
- FSC targeted press release search for private fund topics
- Yulchon newsletter page
- Shin & Kim newsletter page
- Kim & Chang private equity practice insights page
- Samjong KPMG press releases
- Samil PwC press room
- Deloitte Korea press room
- EY Korea newsroom

The query-based feeds are a pragmatic bootstrap for daily coverage, not the final source architecture.
As direct source pages become stable enough, move coverage away from aggregator-style feeds and into direct firm or publisher pages.

## Data Model

Main tables:

- `news_source`: editable source registry synced from CSV
- `news_run`: pipeline run log
- `news_document`: normalized article/report records
- `news_tag`: topic and document-type tags
- `news_entity_link`: links from content to existing DB entities such as GP

## First Version Workflow

1. Sync source definitions from `services/newsletter/data/news_sources.csv`
2. Fetch item candidates from each source
3. Resolve article URLs and fetch article pages
4. Store normalized URL, metadata, summary text, body text, and raw HTML
5. Score PEF relevance using `services/newsletter/data/news_keyword_rules.csv`
6. Tag related GPs using existing `gp_house` and `gp_house_alias`
7. Apply manual overrides from `services/newsletter/data/news_manual_overrides.csv`
8. Export a daily brief and review queue

## Commands

Run the end-to-end pipeline:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py
```

Run for a specific report date:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py --date 2026-04-27
```

Useful tuning options:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py --brief-limit 15 --limit-per-source 40 --min-score 3
```

Run only selected sources while tuning:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py --source-code kimchang_private_equity,yulchon_newsletter
```

If some public pages fail because of local Windows certificate issues:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py --allow-insecure-ssl
```

The pipeline continues when one source fails, so a single broken site does not stop the full daily run.

## Outputs

Daily outputs are written to:

- `exports/daily_news/daily_news_brief_YYYYMMDD.md`
- `exports/daily_news/daily_news_brief_YYYYMMDD.html`
- `exports/daily_news/daily_news_review_queue_YYYYMMDD.csv`

Raw captured HTML is written to:

- `data/raw/daily_news/YYYY-MM-DD/`

## Maintenance

To expand or tune the system, edit CSV files first:

- Add or disable sources in `services/newsletter/data/news_sources.csv`
- Tune scoring logic in `services/newsletter/data/news_keyword_rules.csv`
- Force include/exclude or add comments in `services/newsletter/data/news_manual_overrides.csv`
- Add short-form or English GP aliases in `services/newsletter/data/news_gp_alias_overrides.csv`

This keeps the first version usable even for a non-developer operator.
