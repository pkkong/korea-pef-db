# Private Equity DB

This workspace is being structured as a Korea private equity database.

## Local Repository Setup

This repository is intended to track source code, schemas, documentation, and
small maintained CSV inputs only. Runtime secrets, SQLite databases, downloaded
source files, generated exports, logs, and deploy bundles are local artifacts
and are ignored by git.

Ignored local artifacts that may be produced during diagnostics or rebuilds:

- `db/private_equity.db`
- `data/raw/fss_pef/*`
- `data/raw/daily_news/*`
- `exports/*`
- `logs/*`

Newsletter production secrets live in GitHub Actions repository secrets. Local
`.env` files are not part of the operating path and must not be committed.

To rebuild from public FSS source files in a clean checkout:

```powershell
python scripts/fetch_fss_pef_sources.py
python scripts/run_pipeline.py --with-rebuild-db
```

Current focus:

- FSS quarterly PEF status files
- GP/house master
- LP commitment notice monitor
- PEF fund master
- fund-by-quarter snapshots
- conservative fund events such as `first_seen`, `established`, and `liquidated`

The product-level service menu and entity roadmap are tracked in
`docs/service_information_architecture.md`.
The practical entity data dictionary and future schema plan are tracked in
`docs/entity_data_model.md`.
Project-level Codex/team operating rules are tracked in `AGENTS.md`, with
role-specific operating briefs in `docs/agent_operating_briefs.md`.

## Service Layout

The newsletter service is separated under `services/newsletter/`:

- `services/newsletter/src/`: collection, review, validation, delivery, and deploy builders
- `services/newsletter/data/`: source lists, keyword rules, manual overrides, GP alias overrides
- `services/newsletter/schema/`: newsletter SQLite schema
- `services/newsletter/scripts/`: manual diagnostics and compatibility helpers
- `services/newsletter/deploy/`: Docker/Nginx files and generated static site bundle
- `services/newsletter/docs/`: newsletter-specific operating and deployment docs

The LP notice monitor is being separated under `services/lp/`:

- `services/lp/src/`: LP official notice/news candidate collection and export implementation
- `services/lp/docs/`: LP-specific operating notes

The old `scripts/run_daily_news_pipeline.py` style commands remain as
compatibility wrappers, but new automation should call the service path directly.
The old `scripts/build_lp_commitment_monitor.py` command is also kept as a
compatibility wrapper while new LP work moves under `services/lp/`.

## FSS PEF Pipeline

1. Fetch FSS source files and update the registry:

```powershell
python scripts/fetch_fss_pef_sources.py
```

Raw source reproducibility health check:

```powershell
python scripts/check_fss_raw_sources.py
```

This checks that every registry `local_file` exists under `data/raw/fss_pef/`,
reports file size and SHA-256, and compares SHA-256 to `source_document` when
the local DB is available. Missing raw files fail non-zero; missing DB metadata
only warns.

2. If needed, manually put additional raw FSS quarterly Excel files in `data/raw/fss_pef/`.
3. Register each manual source in `data/source_registry_fss_pef.csv`.
4. Initialize the DB:

```powershell
python scripts/ingest_fss_pef.py init-db
```

5. Inspect a workbook before importing:

```powershell
python scripts/ingest_fss_pef.py inspect data/raw/fss_pef/PEF통합현황(210930).xlsx
```

6. Import all registered local files:

```powershell
python scripts/ingest_fss_pef.py ingest
```

If fund-name normalization rules change, rebuild the generated DB from raw source files:

```powershell
python scripts/ingest_fss_pef.py rebuild
```

7. Check row counts and GP aggregates:

```powershell
python scripts/ingest_fss_pef.py summary
```

8. Export review CSVs:

```powershell
python scripts/export_fss_pef_views.py
```

9. Build reviewable GP master candidates:

```powershell
python scripts/build_gp_master_candidates.py
```

This creates:

- `exports/gp_master_candidates.xlsx`
- `exports/gp_master_candidates.csv`
- `exports/gp_name_variants.csv`
- `exports/gp_alias_review_candidates.csv`

The GP master candidate export intentionally does not merge similar GP names.
Possible duplicates are listed separately in `gp_alias_review_candidates` and
should be confirmed with a business registration number, corporate registration,
DART/FSS registration record, or official company source before merging.

10. Apply externally verified GP alias merges:

```powershell
python scripts/apply_gp_alias_merges.py
python scripts/build_gp_master_candidates.py
```

Verified aliases are preserved in the `gp_house_alias` table. Raw FSS GP names
remain available in `fund_period_snapshot.gp_name_raw`.
The stable merge source is `data/gp_alias_merge_rules.csv`; it is name-based,
not dependent on temporary review group IDs.

11. Build fund master and AUM-style analytics:

```powershell
python scripts/build_fund_master.py
python scripts/build_aum_analytics.py
```

These exports use FSS commitment amount as the AUM-style proxy, not NAV.

12. Build and preview the generated public service bundle:

The public website is generated under `services/newsletter/deploy/site/` and
published to GitHub Pages by GitHub Actions. To preview the already generated
bundle locally, double-click:

```text
open_public_dashboard.bat
```

This opens `http://127.0.0.1:8010/` and serves the generated bundle from
`services/newsletter/deploy/site/`. It is only a local smoke preview; it is not
the production publishing path.
Shared typography, color, and layout rules for the public dashboard and daily
news outputs are tracked in `docs/design_system.md`.

For normal use, double-click:

```text
open_dashboard.bat
```

This starts the internal operator console and opens `http://127.0.0.1:8000/`.
Keep the server window open while using the console.

Manual command flow:

```powershell
python scripts/build_lp_commitment_monitor.py
python scripts/build_dashboard_data.py
python scripts/build_public_service_data.py
python scripts/build_standalone_dashboard.py
python scripts/build_site_bundle.py --services newsletter,lp,gp
python scripts/serve_dashboard.py
```

Then open `http://127.0.0.1:8000/`.

The operator console is an internal app shell:
`dashboard/index.html` is a small app shell,
`dashboard/assets/app.css` and `dashboard/assets/app.js` hold the presentation
code, and `dashboard/data/dashboard_data.json` holds generated data plus
operator-only work queues. It is designed for service operation: market summary,
GP ranking, DB quality checks, source documents, and news-driven GP update
queues. Open it through a static server rather than by double-clicking the
file. See `docs/dashboard_design_notes.md` for the reference-driven layout
direction. For a one-file offline review build only, run:

```powershell
python scripts/build_standalone_dashboard.py --embed-data --out dashboard/pef_dashboard_standalone.html
```

13. Build GP profile master and the top-priority legal-entity research list:

```powershell
python scripts/build_gp_profile_master.py
```

This creates:

- `exports/gp_profile_master.xlsx`
- `exports/gp_profile_master.csv`
- `exports/gp_identifier.csv`
- `exports/gp_profile_sources.csv`
- `exports/gp_profile_research_worklist_top50.csv`

Legal identifiers and company profile fields are intentionally blank until
confirmed from official company, regulatory, registry, or equivalent sources.

14. Apply source-backed GP profile evidence, then rebuild the exports:

```powershell
python scripts/apply_gp_profile_evidence.py
python scripts/build_gp_profile_master.py
```

The maintainable source file is `data/gp_profile_evidence.csv`. Add new GP
profile facts there as field-level evidence rows, with `source_url`,
`source_grade`, and notes. The apply script updates `gp_profile`, mirrors
business/corporate/financial registration numbers into `gp_identifier`, and
keeps field-level evidence in `gp_profile_source`. This keeps the DB
regenerable instead of relying on one-off manual SQLite edits.

15. Initialize and import People DB inputs:

```powershell
python scripts/apply_people_schema.py
python scripts/import_people_csv.py
python scripts/export_people_views.py
```

The People DB schema is `schema/people.sql`. The maintained input files are:

- `data/people_input.csv`
- `data/person_role_input.csv`
- `data/person_education_input.csv`

Example templates with sample rows are:

- `data/people_import_template.csv`
- `data/person_role_import_template.csv`
- `data/person_education_import_template.csv`

The normal end-to-end pipeline now runs `import_people_csv.py` automatically.
Empty input files are safe and do not insert sample people.
The first loaded People DB samples are Premier Partners and MBK Partners,
sourced from their official team pages.

People review exports are:

- `exports/people_profile_summary.csv`
- `exports/people_current_gp.csv`
- `exports/people_roles.csv`
- `exports/people_education.csv`

16. Build the DB quality report:

```powershell
python scripts/build_db_quality_report.py
```

This creates:

- `exports/db_quality_report.xlsx`
- `exports/db_quality_overview.csv`
- `exports/db_quality_gp_profile_coverage.csv`
- `exports/db_quality_verification_summary.csv`
- `exports/db_quality_source_grade_summary.csv`
- `exports/db_quality_top_gp_gaps.csv`
- `exports/db_quality_service_ready_top50.csv`
- `exports/db_quality_identifier_duplicates.csv`

17. Build a user-facing operational status report:

```powershell
python scripts/build_operational_status_report.py
```

This creates:

- `exports/operational_status_latest.md`
- `exports/operational_status_YYYYMMDD_HHMMSS.md`

Use this as the quick non-technical checkpoint for what is currently available,
what the dashboard is loading, and which GP profiles need news-driven updates.

18. Run the maintainable refresh pipeline end-to-end:

```powershell
python scripts/run_pipeline.py
```

This is the safe default for refreshing derived tables and exports from the
current DB. It writes run logs to `logs/`, refreshes the news-driven GP update
queue when news rows are already in the DB, and updates
`exports/operational_status_latest.md`.

If new FSS files were added to the registry and the SQLite DB should be rebuilt
from raw sources first:

```powershell
python scripts/run_pipeline.py --with-rebuild-db
```

If FSS sources should also be fetched before the rebuild:

```powershell
python scripts/run_pipeline.py --with-fetch-sources --with-rebuild-db
```

See `docs/fss_pef_ingestion_plan.md` and `schema/fss_pef.sql` for details.

## Daily News / GP Update Workflow

Run the daily news MVP:

```powershell
python services/newsletter/src/run_daily_news_pipeline.py
```

This exports daily clipping files under `exports/daily_news/`. It also creates
a GP update worklist so news-visible houses can be prioritized for profile
maintenance:

- `exports/daily_news/news_gp_update_worklist_latest.csv`
- `exports/daily_news/news_gp_update_worklist_YYYYMMDD.csv`

If news fetching is blocked by the local network/sandbox but the DB already has
recent news rows, rebuild only the GP update worklist:

```powershell
python services/newsletter/src/build_news_gp_update_worklist.py --days 7
```

The worklist separates `프로필 우선 보강`, `식별자 보강`, `선택정보 보강`, and
`유지`, so coverage work follows market visibility instead of trying to fill
every long-tail GP upfront.

To keep the newsletter and People DB work aligned, build the cross-service
operating worklist:

```powershell
python scripts/build_service_integration_worklist.py
```

This creates:

- `exports/service_integration_worklist_latest.csv`
- `exports/service_integration_worklist_YYYYMMDD.csv`

The integrated worklist joins news-visible GPs, GP profile coverage, People DB
coverage, and the next owner/action. The normal `run_pipeline.py` and
newsletter pipeline flows refresh it automatically.
