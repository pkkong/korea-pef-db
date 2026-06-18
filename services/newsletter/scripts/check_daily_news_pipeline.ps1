$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python -m py_compile `
    services\shared\src\daily_news_common.py `
    services\newsletter\src\daily_news_common.py `
    services\newsletter\src\run_daily_news_pipeline.py `
    services\newsletter\src\backtest_daily_news.py `
    services\newsletter\src\build_newsletter_source_audit.py `
    services\newsletter\src\validate_daily_news_pipeline.py `
    services\newsletter\src\daily_news_review_server.py `
    services\newsletter\src\finalize_daily_news_review.py `
    services\newsletter\src\newsletter_renderer.py `
    services\newsletter\src\newsletter_site_support.py `
    scripts\build_newsletter_bundle.py `
    services\newsletter\tests\test_daily_news_logic.py `
    services\newsletter\web\newsletter_ui.py `
    services\newsletter\web\newsletter_data.py `
    services\newsletter\web\app.py

python services\newsletter\tests\test_daily_news_logic.py
python services\newsletter\src\validate_daily_news_pipeline.py --date $ReportDate
