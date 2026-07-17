$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$composeFile = Join-Path $repositoryRoot "deploy/compose/compose.deps.yml"
$developmentEnv = Join-Path $repositoryRoot "deploy/env/.env.development"
$exampleEnv = Join-Path $repositoryRoot "deploy/env/.env.development.example"
$envFile = if (Test-Path -LiteralPath $developmentEnv) { $developmentEnv } else { $exampleEnv }
$failed = $false

function Invoke-StatusCheck {
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][scriptblock]$Check
  )

  Write-Output "==> $Name"
  try {
    & $Check
  }
  catch {
    $script:failed = $true
    Write-Warning "$Name unavailable: $($_.Exception.Message)"
  }
}

Push-Location $repositoryRoot
try {
  Invoke-StatusCheck "Docker Compose dependencies" {
    $composeJson = @(docker compose --env-file $envFile -f $composeFile ps --format json)
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose ps returned exit code $LASTEXITCODE"
    }
    try {
      $services = @(ConvertFrom-Json ($composeJson -join "`n"))
    }
    catch {
      throw "docker compose ps returned invalid JSON"
    }
    foreach ($serviceName in @("postgres", "redis", "chroma")) {
      $service = @($services | Where-Object { $_.Service -eq $serviceName })
      if ($service.Count -ne 1) {
        throw "$serviceName is missing from Docker Compose status"
      }
      if ($service[0].State -ne "running" -or $service[0].Health -ne "healthy") {
        throw "$serviceName is not running and healthy"
      }
      Write-Output "$serviceName`: running (healthy)"
    }
  }

  foreach ($endpoint in @("live", "ready", "dependencies")) {
    Invoke-StatusCheck "API /api/v1/health/$endpoint" {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:8001/api/v1/health/$endpoint" -Method Get -TimeoutSec 5 -UseBasicParsing
      if ($response.StatusCode -ne 200) {
        throw "HTTP $($response.StatusCode)"
      }
      Write-Output "HTTP $($response.StatusCode)"
    }
  }

  Invoke-StatusCheck "Celery worker ping" {
    $redisLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^REDIS_URL=' } | Select-Object -First 1
    if (-not $redisLine) {
      throw "REDIS_URL is not configured"
    }
    $hadRedisUrl = Test-Path Env:REDIS_URL
    $originalRedisUrl = $env:REDIS_URL
    Push-Location (Join-Path $repositoryRoot "backend")
    try {
      $env:REDIS_URL = $redisLine.Substring("REDIS_URL=".Length)
      uv run --project . celery -A app.bootstrap.celery_app:celery_app inspect ping --timeout 5
      if ($LASTEXITCODE -ne 0) {
        throw "Celery inspect ping returned exit code $LASTEXITCODE"
      }
    }
    finally {
      Pop-Location
      if ($hadRedisUrl) {
        $env:REDIS_URL = $originalRedisUrl
      }
      else {
        Remove-Item Env:REDIS_URL -ErrorAction SilentlyContinue
      }
    }
  }
}
finally {
  Pop-Location
}

if ($failed) {
  Write-Error "One or more development services are unavailable. No services were changed." -ErrorAction Continue
  exit 1
}

Write-Output "All development service status checks passed."
