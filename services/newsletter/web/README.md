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

`newsletter_ui.py` owns newsletter HTML for Vercel and the GitHub Pages mirror.
Pure CSS/JS/icon functions live once in `services/shared/web/service_assets.py`
and are re-exported by the newsletter renderer. Each deployment includes its
own copy and serves `/assets/service.css` and `/assets/service.js` locally.
Do not add a separate template or duplicate stylesheet source.

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

## Independent deployment

`Deploy newsletter Vercel app` runs only newsletter checks and packages only
this app plus shared pure assets. LP and GP have their own apps, Vercel projects
and deployment workflows. Menu links use `LP_PUBLIC_URL` and `GP_PUBLIC_URL`,
which default to `https://kpef-lp.vercel.app` and `https://kpef-gp.vercel.app`.
Old LP/GP routes return redirects without importing or querying either service.

To inspect the deployable package without the rest of the repository:

```bash
python3 scripts/build_service_runtime.py --service newsletter --output /tmp/newsletter-package
```

The generated app is under `/tmp/newsletter-package/services/newsletter/web/`.
Production deployment uses `scripts/deploy_service_runtime.py --service newsletter`
inside the workflow. No database writer credentials enter the app package.
