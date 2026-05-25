$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python -m py_compile `
    services\newsletter\src\daily_news_common.py `
    services\newsletter\src\run_daily_news_pipeline.py `
    services\newsletter\src\backtest_daily_news.py `
    services\newsletter\src\build_newsletter_deploy.py `
    services\newsletter\src\build_newsletter_source_audit.py `
    services\newsletter\src\validate_daily_news_pipeline.py `
    services\newsletter\src\daily_news_review_server.py `
    services\newsletter\src\finalize_daily_news_review.py `
    services\newsletter\tests\test_daily_news_logic.py `
    scripts\build_service_site.py `
    scripts\build_public_service_data.py

python services\newsletter\tests\test_daily_news_logic.py
python services\newsletter\src\validate_daily_news_pipeline.py --date $ReportDate
