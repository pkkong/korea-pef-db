param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$User = "root",
    [int]$SshPort = 22,
    [string]$KeyPath = "",
    [string]$RemoteDir = "/opt/kpef-newsletter",
    [int]$PublishPort = 80,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ServiceRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ServiceRoot)
$DeployDir = Join-Path $ServiceRoot "deploy"
$ZipPath = Join-Path $DeployDir "kpef-newsletter-site.zip"
$DockerfilePath = Join-Path $DeployDir "Dockerfile"
$NginxPath = Join-Path $DeployDir "nginx.conf"

if (-not $SkipBuild) {
    python (Join-Path $ServiceRoot "src/build_newsletter_deploy.py")
}

if (-not (Test-Path $ZipPath)) {
    throw "Missing deployment zip: $ZipPath"
}

$sshBase = @("-p", "$SshPort")
$scpBase = @("-P", "$SshPort")
if ($KeyPath) {
    $sshBase += @("-i", $KeyPath)
    $scpBase += @("-i", $KeyPath)
}

$Target = "$User@$HostName"

ssh @sshBase $Target "mkdir -p '$RemoteDir'"
scp @scpBase $ZipPath $DockerfilePath $NginxPath "${Target}:$RemoteDir/"

$remoteCommand = @"
set -e
cd '$RemoteDir'
rm -rf site
mkdir -p site
unzip -q -o kpef-newsletter-site.zip -d site
docker build -t kpef-newsletter:latest .
docker rm -f kpef-newsletter >/dev/null 2>&1 || true
docker run -d --name kpef-newsletter --restart unless-stopped -p ${PublishPort}:80 kpef-newsletter:latest
curl -fsS http://127.0.0.1:${PublishPort}/health.json
"@

ssh @sshBase $Target $remoteCommand
Write-Host "Newsletter deployed: http://$HostName`:$PublishPort/"
