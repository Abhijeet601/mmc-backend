param(
  [string]$Environment = "",
  [string]$Service = ""
)

$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $backendRoot ".env"
$keys = @(
  "CCAVENUE_MERCHANT_ID",
  "CCAVENUE_ACCESS_CODE",
  "CCAVENUE_WORKING_KEY",
  "CCAVENUE_GATEWAY_URL",
  "CCAVENUE_REDIRECT_URL",
  "CCAVENUE_CANCEL_URL",
  "CCAVENUE_WEBHOOK_URL"
)

if (!(Test-Path -LiteralPath $envPath)) {
  throw "Backend .env file not found: $envPath"
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $envPath) {
  if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
  $parts = $line.Split("=", 2)
  $name = $parts[0].Trim()
  if ($keys -contains $name) {
    $values[$name] = $parts[1].Trim()
  }
}

$missing = @()
foreach ($key in $keys) {
  if (!$values.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($values[$key])) {
    $missing += $key
  }
}
if ($missing.Count -gt 0) {
  throw "Missing CCAvenue values in backend .env: $($missing -join ', ')"
}

railway whoami | Out-Host
railway status | Out-Host

$commonArgs = @()
if ($Environment) { $commonArgs += @("--environment", $Environment) }
if ($Service) { $commonArgs += @("--service", $Service) }

foreach ($key in $keys) {
  Write-Host "Setting $key in Railway..."
  railway variable set @commonArgs "$key=$($values[$key])" | Out-Host
}

Write-Host "CCAvenue Railway variables have been set."
