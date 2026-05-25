$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

python scripts\send_daily_news.py `
    --markdown exports\daily_news\daily_news_final_latest.md `
    --html exports\daily_news\daily_news_final_latest.html `
    --subject "Daily PEF News Clipping"
