$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/apply_daily_news_review_today.ps1") @args
exit $LASTEXITCODE
