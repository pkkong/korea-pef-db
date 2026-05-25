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
- `docs/`: service-specific operating notes

## Common Commands

```bash
python3 scripts/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_commitment_monitor.py --skip-source-fetch
```

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
