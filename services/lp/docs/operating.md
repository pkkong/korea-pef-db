# LP Notice Operating Notes

The LP notice monitor tracks official LP commitment notices and related news
candidates, stores them in the existing SQLite database, and exports the latest
CSV monitor for downstream site builders.

## Entrypoints

- Compatibility path: `python3 scripts/build_lp_commitment_monitor.py`
- Service path: `python3 services/lp/src/build_lp_commitment_monitor.py`

Both entrypoints call the same implementation in
`services/lp/src/build_lp_commitment_monitor.py`.

## Local Validation

Use `--skip-source-fetch` for fast no-network validation of the split and
database/schema integration:

```bash
python3 scripts/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_commitment_monitor.py --skip-source-fetch
```

Run without `--skip-source-fetch` only when official source fetching is expected.

## CSV Review Queue

The monitor stores review state in `lp_commitment_notice.monitor_status`:

- `candidate`: needs human review
- `validated`: reviewed in and preserved across future monitor rebuilds
- `dismissed`: reviewed out, hidden from public exports with `public_visible=0`,
  and preserved across future monitor rebuilds

Export the queue:

```bash
python3 scripts/lp_commitment_notice_review.py export
```

This writes:

- `exports/lp_commitment_notice_review_queue_YYYYMMDD.csv`
- `exports/lp_commitment_notice_review_queue_latest.csv`

Reviewers should edit `review_action` only for rows they want to change. Blank,
`skip`, and `keep` are ignored. Accepted actions are `validated`, `dismissed`,
and `candidate`; common aliases such as `approve`, `reject`, `승인`, and `제외`
are also accepted.

Preview before writing:

```bash
python3 scripts/lp_commitment_notice_review.py apply exports/lp_commitment_notice_review_queue_latest.csv --dry-run
```

Apply the reviewed CSV:

```bash
python3 scripts/lp_commitment_notice_review.py apply exports/lp_commitment_notice_review_queue_latest.csv
```

The apply step identifies rows by `normalized_notice_url` first, then
`notice_id`, so a queue can still be applied after an automatic rebuild recreates
candidate rows with new IDs. Use `--require-current-status-match` when you want
the apply step to fail if a row's current database status differs from the
exported `monitor_status`.
