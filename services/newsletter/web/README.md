# Newsletter Vercel Web App

This folder is the standalone Vercel-facing newsletter app.

## Production Shape

```text
GitHub Actions daily collector
-> services/newsletter/deploy/site/archive.json
-> publish and verify GitHub Pages mirror
-> sync_newsletter_supabase.py
-> Supabase public read model
-> Vercel Flask app
```

The Vercel app does not crawl news and does not import LP/GP/Wiki modules. If
Supabase is unavailable, empty, or stale, it falls back to the current public
`archive.json`.

Supabase keeps the same recent rolling archive depth as the static mirror
(default: 30 issues). This keeps date navigation consistent between Vercel and
GitHub Pages instead of showing only the latest issue in the official app.
The app reads `newsletter_issues` for the 30-issue date skeleton and
`newsletter_public_issue_articles` for article content/order. Do not collapse
this into the article view only, because dates with zero articles would
disappear. Preserve numeric order values exactly, including `section_order=0`.

`newsletter_ui.py` is the single newsletter UI source for both Vercel and the
GitHub Pages mirror. Do not add a separate Jinja template or standalone
`static/service.css`; Vercel serves `/assets/service.css` and
`/assets/service.js` from the same module the static builder imports.

## Required Vercel Environment

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`

Optional:

- `NEWSLETTER_ARCHIVE_URL`
- `NEWSLETTER_CACHE_SECONDS`
- `NEWSLETTER_SUPABASE_ROW_LIMIT`

## Local Run

```bash
python3 -m venv .venv-newsletter-web
. .venv-newsletter-web/bin/activate
pip install -r services/newsletter/web/requirements.txt
FLASK_APP=services/newsletter/web/app.py flask run --port 5050
```
