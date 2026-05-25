$ErrorActionPreference = "Stop"

$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "exports\daily_news\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ReportDate = Get-Date -Format "yyyy-MM-dd"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "daily_news_$Timestamp.log"

python services\newsletter\src\run_daily_news_pipeline.py `
    --date $ReportDate `
    --limit-per-source 30 `
    --brief-limit 30 `
    --review-limit 80 `
    --allow-insecure-ssl *>&1 | Tee-Object -FilePath $LogFile

$PipelineExitCode = $LASTEXITCODE
if ($PipelineExitCode -ne 0) {
    exit $PipelineExitCode
}

python services\newsletter\src\build_newsletter_source_audit.py `
    --date $ReportDate *>&1 | Tee-Object -FilePath $LogFile -Append

$NewsletterAuditExitCode = $LASTEXITCODE
if ($NewsletterAuditExitCode -ne 0) {
    exit $NewsletterAuditExitCode
}

python scripts\build_lp_commitment_monitor.py `
    --date $ReportDate `
    --days 180 `
    --limit-per-source 50 *>&1 | Tee-Object -FilePath $LogFile -Append

$LpMonitorExitCode = $LASTEXITCODE
if ($LpMonitorExitCode -ne 0) {
    exit $LpMonitorExitCode
}

python scripts\build_dashboard_data.py *>&1 | Tee-Object -FilePath $LogFile -Append

$DashboardDataExitCode = $LASTEXITCODE
if ($DashboardDataExitCode -ne 0) {
    exit $DashboardDataExitCode
}

python scripts\build_service_site.py `
    --date $ReportDate *>&1 | Tee-Object -FilePath $LogFile -Append

$SiteBuildExitCode = $LASTEXITCODE
if ($SiteBuildExitCode -ne 0) {
    exit $SiteBuildExitCode
}

python scripts\build_public_service_data.py *>&1 | Tee-Object -FilePath $LogFile -Append

$PublicDataExitCode = $LASTEXITCODE
if ($PublicDataExitCode -ne 0) {
    exit $PublicDataExitCode
}

python services\newsletter\src\validate_daily_news_pipeline.py `
    --date $ReportDate *>&1 | Tee-Object -FilePath $LogFile -Append

exit $LASTEXITCODE
