$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

$ReportDate = Get-Date -Format "yyyy-MM-dd"

python services\newsletter\src\validate_daily_news_pipeline.py --date $ReportDate
