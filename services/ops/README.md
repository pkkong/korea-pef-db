# Operations Service

Cross-service operating scripts live here when the job touches more than one
product area.

## Nightly Data Refresh

The nightly refresh keeps GP, LP, People, dashboard, and public-safe service
data moving even when the newsletter is not being actively edited.

Install the macOS job:

```bash
services/ops/scripts/install_data_nightly_refresh_launchd.sh --hour 1 --minute 30
```

Run once without installing:

```bash
services/ops/scripts/run_data_nightly_refresh.sh
```

By default this job does not push the public newsletter mirror. It refreshes
local DB-derived outputs and rebuilds the deploy bundle so the scheduled
newsletter publisher can publish one consistent site.
