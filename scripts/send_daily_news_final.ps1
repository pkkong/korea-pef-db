$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/send_daily_news_final.ps1") @args
exit $LASTEXITCODE
