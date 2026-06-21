# LP Notice Service

This folder owns the LP commitment notice monitor service.

## Current Service State

LP owns commitment notice collection, LP profile facts, public LP directory
pages, official notice pages, and LP notice detail pages. New LP code belongs in
`services/lp/src/` and should use `services/shared/src/` for shared helpers.

The service still reads and writes the legacy root-level project paths:

- `db/private_equity.db`
- `schema/lp_commitments.sql`
- `data/lp_institutions.csv`
- `data/lp_commitment_sources.csv`
- `exports/lp_commitment_monitor_*.csv`

The root script at `scripts/build_lp_commitment_monitor.py` is a compatibility
wrapper. Existing jobs can keep calling it while new service docs and jobs can
prefer the service path.

`services/lp/src/lp_legacy_service_pages.py` remains a compatibility renderer
for current public URLs. Importing LP service entrypoints must not load GP, Wiki,
or the old public-site monolith; `scripts/check_architecture_contracts.py`
enforces that boundary.

## Layout

- `src/`: Python implementation for collecting, normalizing, storing, and exporting LP notice candidates
- `scripts/`: reserved for service-level utilities. Recurring collection and publishing run through GitHub-managed workflows, not a local Mac.
- `docs/`: service-specific operating notes

## Common Commands

```bash
python3 scripts/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_profile_backlog.py
python3 scripts/check_architecture_contracts.py
```

## Profile Backlog

LP profiles should not stop at the current public sample set. The profile
backlog builder writes a prioritized research queue. Recurring collection and
publication are GitHub workflow responsibilities; this service does not ship a
local Mac scheduler or publisher.

The generated backlog files are:

- `exports/lp_profile_backlog_latest.csv`
- `exports/lp_profile_backlog_latest.json`

Use these files as the queue for human or agent research: high-priority rows
identify which LP profile sections are missing and which official sources should
be checked next.

## CSV Review Workflow

Export the current `candidate` queue for human review:

```bash
python3 scripts/lp_commitment_notice_review.py export
```

Fill `review_action` in the exported CSV with one of:

- `validated`: keep the notice and mark it reviewed
- `dismissed`: hide the notice and mark it reviewed out
- `candidate`: reset the notice to the review queue

Preview and apply the completed CSV:

```bash
python3 scripts/lp_commitment_notice_review.py apply exports/lp_commitment_notice_review_queue_latest.csv --dry-run
python3 scripts/lp_commitment_notice_review.py apply exports/lp_commitment_notice_review_queue_latest.csv
```

The review tool updates `lp_commitment_notice.monitor_status`. By default,
`validated` sets `public_visible=1`, `dismissed` sets `public_visible=0`, and
`candidate` keeps the current visibility unless `review_public_visible` is set.
