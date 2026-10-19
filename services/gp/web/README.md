# GP runtime

This Flask application owns the GP directory, market page, GP/person profiles,
and ranking download. It reads only the GP public snapshot from Supabase. It
does not import or call the newsletter or LP application.

Run from the repository root after installing `requirements.txt`:

```sh
flask --app services.gp.web.app run --port 8773
```

Configure `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (or `SUPABASE_ANON_KEY`)
for this application independently. `NEWSLETTER_PUBLIC_URL`, `LP_PUBLIC_URL`, and
`GP_PUBLIC_URL` configure navigation only. No service-role key is needed for
public reads. See `env.example` for non-secret defaults.

Deploy this directory with the pure shared `service_assets.py` copied beside
`app.py`. The deployment bundle must include
`downloads/gp_ranking_datapack_2025YE.xlsx` to preserve the ranking download;
the runtime never fetches it from another service. Source generation and bundle
preparation belong to the GP pipeline, independently of newsletter publication.

Stored page hashes are verified before navigation links are rewritten. Per-page
caches expire after five minutes by default and may retain the last successful
page for up to an additional hour during read failures. A newly observed
snapshot invalidates all pages from the previous snapshot. `/health.json`
checks only GP data and reports stale delivery as degraded.
