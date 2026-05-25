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
