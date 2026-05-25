$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python scripts\apply_daily_news_review.py `
    --review-file exports\daily_news\daily_news_review_actions_latest.csv

python scripts\finalize_daily_news_review.py `
    --date $ReportDate `
    --apply-overrides
