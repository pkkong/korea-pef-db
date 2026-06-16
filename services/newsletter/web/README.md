# Newsletter Vercel Web App

This folder is the standalone Vercel-facing newsletter app.

## Production Shape

```text
GitHub Actions daily collector
-> services/newsletter/deploy/site/archive.json
-> sync_newsletter_supabase.py
-> Supabase public read model
-> Vercel Flask app
```

The Vercel app does not crawl news and does not import LP/GP/Wiki modules. If
Supabase is not configured yet, it falls back to the current public
`archive.json` so the UI can still run during migration.

## Required Vercel Environment

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`

Optional:

- `NEWSLETTER_ARCHIVE_URL`
- `NEWSLETTER_CACHE_SECONDS`

## Local Run

```bash
python3 -m venv .venv-newsletter-web
. .venv-newsletter-web/bin/activate
pip install -r services/newsletter/web/requirements.txt
FLASK_APP=services/newsletter/web/app.py flask run --port 5050
```
