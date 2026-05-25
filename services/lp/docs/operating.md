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
