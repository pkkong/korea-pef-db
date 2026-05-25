$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "exports\daily_news\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$LogFile = Join-Path $LogDir "daily_news_review_server.log"
$ServerCommand = "Set-Location '$RepoRoot'; python scripts\daily_news_review_server.py *> '$LogFile'"

Start-Process powershell.exe `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $ServerCommand `
    -WindowStyle Hidden

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8765/"
