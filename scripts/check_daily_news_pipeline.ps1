$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/check_daily_news_pipeline.ps1") @args
exit $LASTEXITCODE
