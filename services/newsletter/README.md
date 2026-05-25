# Newsletter Service

This folder owns the standalone Korea PEF daily newsletter service.

## Layout

- `src/`: Python implementation for collection, review, validation, delivery, source audit, and static deploy bundle generation
- `data/`: maintained newsletter inputs such as source definitions, keyword rules, manual overrides, and GP alias overrides
- `schema/`: SQLite schema for newsletter tables
- `scripts/`: PowerShell operating entrypoints for local Windows automation
- `deploy/`: Docker/Nginx runtime files plus ignored generated site artifacts
- `docs/`: service-specific operating, cloud migration, MVP, and deployment notes
- `tests/`: no-network business rule checks

Root-level `scripts/*daily_news*.py` files are compatibility wrappers. New jobs
and docs should prefer the paths in this service folder.

## Common Commands

```powershell
python services/newsletter/src/run_daily_news_pipeline.py
python services/newsletter/src/build_newsletter_deploy.py
python services/newsletter/src/validate_daily_news_pipeline.py
python services/newsletter/tests/test_daily_news_logic.py
```
