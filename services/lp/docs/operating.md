# LP Notice Operating Notes

The LP notice monitor tracks official LP commitment notices and related news
candidates, stores them in the existing SQLite database, and exports the latest
CSV monitor for downstream site builders.

## Entrypoints

- Compatibility path: `python3 scripts/build_lp_commitment_monitor.py`
- Service path: `python3 services/lp/src/build_lp_commitment_monitor.py`
- Profile backlog: `python3 services/lp/src/build_lp_profile_backlog.py`

Both entrypoints call the same implementation in
`services/lp/src/build_lp_commitment_monitor.py`.

## Local Validation

Use `--skip-source-fetch` only for fast no-network validation of the split and
database/schema integration:

```bash
python3 scripts/build_lp_commitment_monitor.py --skip-source-fetch
python3 services/lp/src/build_lp_commitment_monitor.py --skip-source-fetch
```

Run without `--skip-source-fetch` for operating builds. Official notice rows are
preserved across builds and updated by normalized URL, while news candidates are
refreshed. This prevents a temporary source-fetch failure or a skip-source
validation run from deleting the historical official notice set.

## Profile Expansion Model

The public LP service does not show every tracked LP institution. Public
directory visibility requires `display_enabled=1`, a direct GP/manager selection
role or an explicit strategic exception, and enough public facts to avoid an
empty profile. Thin or unproven institutions stay in the candidate/OCIO pool and
grow through a separate backlog:

- `profile_ready`: enough public facts and at least one notice signal
- `profile_gap`: some public facts exist, but one or more target sections are missing
- `notice_only`: official/news notices exist, but the profile facts are not built yet
- `seed_only`: the LP is in the tracked universe, but facts and notices are still empty; keep hidden unless explicitly approved

Build the profile backlog:

```bash
python3 services/lp/src/build_lp_profile_backlog.py
```

This writes `exports/lp_profile_backlog_latest.csv` and
`exports/lp_profile_backlog_latest.json`. The queue should be used by a human
reviewer or a research agent to add source-backed rows to
`data/lp_profile_facts.csv`.

## Operating Schedule

Recurring LP collection and public publishing should be handled by GitHub-managed workflows, not a local Mac scheduler.
The operating sequence is:

1. LP commitment notice monitor
2. LP profile research backlog builder
3. LP static bundle rebuild
4. GitHub Pages mirror publish through the central deployment workflow

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
