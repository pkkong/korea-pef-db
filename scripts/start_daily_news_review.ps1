$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/start_daily_news_review.ps1") @args
exit $LASTEXITCODE
