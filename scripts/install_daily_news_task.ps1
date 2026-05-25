$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/install_daily_news_task.ps1") @args
exit $LASTEXITCODE
