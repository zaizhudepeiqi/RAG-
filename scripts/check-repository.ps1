$ErrorActionPreference = "Stop"

$requiredPaths = @(
  ".python-version",
  ".node-version",
  "package.json",
  "backend/pyproject.toml",
  "frontend/package.json",
  "deploy/compose/compose.deps.yml"
)

$missingPaths = @(
  $requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingPaths.Count -gt 0) {
  throw "Missing required repository paths: $($missingPaths -join ', ')"
}

if ((Get-Content -Raw -LiteralPath ".python-version").Trim() -ne "3.13.9") {
  throw ".python-version must be 3.13.9"
}

if ((Get-Content -Raw -LiteralPath ".node-version").Trim() -ne "24.16.0") {
  throw ".node-version must be 24.16.0"
}

$npmVersion = (npm --version).Trim()
if ($LASTEXITCODE -ne 0 -or $npmVersion -ne "11.13.0") {
  throw "npm must be 11.13.0; found $npmVersion"
}

$rootPackage = Get-Content -Raw -LiteralPath "package.json" | ConvertFrom-Json
if ($rootPackage.packageManager -ne "npm@11.13.0") {
  throw "Root packageManager must be npm@11.13.0"
}

Write-Output "Repository structure and runtime locks are valid."
