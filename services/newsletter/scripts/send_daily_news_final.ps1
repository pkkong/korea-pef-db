$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

python services\newsletter\src\send_daily_news.py `
    --markdown exports\daily_news\daily_news_final_latest.md `
    --html exports\daily_news\daily_news_final_latest.html `
    --subject "Daily PEF News Clipping"
