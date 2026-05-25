$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python -m py_compile `
    scripts\run_daily_news_pipeline.py `
    scripts\backtest_daily_news.py `
    scripts\build_service_site.py `
    scripts\build_public_service_data.py `
    scripts\validate_daily_news_pipeline.py `
    scripts\daily_news_review_server.py `
    scripts\finalize_daily_news_review.py `
    scripts\test_daily_news_logic.py

python scripts\test_daily_news_logic.py
python scripts\validate_daily_news_pipeline.py --date $ReportDate
