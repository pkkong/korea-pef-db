$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python scripts\validate_daily_news_pipeline.py --date $ReportDate
