# Operations Service

Cross-service operating scripts live here when the job touches more than one
product area.

## Nightly Data Refresh

The refresh script is a manual source rebuild utility. It is not a scheduler and
does not publish to GitHub Pages. Recurring operation belongs in GitHub Actions.

Run once without installing:

```bash
services/ops/scripts/run_data_nightly_refresh.sh
```

It refreshes DB-derived outputs and rebuilds the deploy bundle for validation.
Use the central GitHub Actions workflow for publication.
