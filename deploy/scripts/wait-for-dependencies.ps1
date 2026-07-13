param(
  [string]$EnvFile = "deploy/env/.env.development",
  [ValidateRange(1, 600)]
  [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$composeFile = "deploy/compose/compose.deps.yml"
$requiredServices = @("postgres", "redis", "chroma")

function Invoke-Compose {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

  $output = & docker compose --env-file $EnvFile -f $composeFile @Arguments 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed: $($output -join [Environment]::NewLine)"
  }
  return $output
}

function Write-Diagnostics {
  Write-Output "Dependency status:"
  & docker compose --env-file $EnvFile -f $composeFile ps 2>&1 | Write-Output
  Write-Output "Recent dependency logs:"
  & docker compose --env-file $EnvFile -f $composeFile logs --tail 100 2>&1 | Write-Output
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
  throw "Environment file does not exist: $EnvFile"
}
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
  throw "Compose file does not exist: $composeFile"
}

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTimeOffset]::UtcNow -lt $deadline) {
  $jsonLines = @(Invoke-Compose ps --format json)
  $containers = if ($jsonLines.Count -eq 0) {
    @()
  }
  else {
    @(
      $jsonLines |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json }
    )
  }

  $failed = @(
    $containers | Where-Object {
      $_.State -in @("exited", "dead", "removing") -or $_.Health -eq "unhealthy"
    }
  )
  if ($failed.Count -gt 0) {
    Write-Diagnostics
    exit 2
  }

  $healthyServices = @(
    $containers | Where-Object {
      $_.Service -in $requiredServices -and $_.State -eq "running" -and $_.Health -eq "healthy"
    } | Select-Object -ExpandProperty Service -Unique
  )
  if ($healthyServices.Count -eq $requiredServices.Count) {
    Write-Output "PostgreSQL, Redis, and Chroma are healthy."
    exit 0
  }

  Start-Sleep -Seconds 2
}

Write-Diagnostics
exit 2
