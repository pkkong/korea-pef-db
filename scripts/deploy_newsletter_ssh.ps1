$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $RepoRoot "services/newsletter/scripts/deploy_newsletter_ssh.ps1") @args
exit $LASTEXITCODE
