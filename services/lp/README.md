# LP Notice Service

This folder owns the LP commitment notice monitor service.

## Current Split State

This first split moves the implementation for `build_lp_commitment_monitor.py`
under `services/lp/src/` while keeping existing runtime defaults intact.

The service still reads and writes the legacy root-level project paths:

- `db/private_equity.db`
- `schema/lp_commitments.sql`
- `data/lp_institutions.csv`
- `data/lp_commitment_sources.csv`
- `exports/lp_commitment_monitor_*.csv`

The root script at `scripts/build_lp_commitment_monitor.py` is a compatibility
wrapper. Existing jobs can keep calling it while new service docs and jobs can
prefer the service path.

## Layout

- `src/`: Python implementation for collecting, normalizing, storing, and exporting LP notice candidates
- `scripts/`: macOS/background runners for recurring LP collection and publishing
- `docs/`: service-specific operating notes

## Common Commands

```bash
python3 scripts/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_profile_backlog.py
```

## Background Collection

LP profiles should not stop at the current public sample set. The background
collector refreshes official LP notices, writes a prioritized profile research
backlog, rebuilds the newsletter/LP/GP static bundle, and can push the GitHub
Pages mirror.

Run one local validation without pushing:

```bash
services/lp/scripts/run_lp_background_collector.sh --no-push
```

Install the recurring macOS job:

```bash
services/lp/scripts/install_lp_background_collector_launchd.sh --interval-hours 6
```

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
