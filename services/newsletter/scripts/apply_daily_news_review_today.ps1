$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python services\newsletter\src\apply_daily_news_review.py `
    --review-file exports\daily_news\daily_news_review_actions_latest.csv

python services\newsletter\src\finalize_daily_news_review.py `
    --date $ReportDate `
    --apply-overrides
