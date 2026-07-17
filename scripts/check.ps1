$ErrorActionPreference = "Stop"

function Invoke-Checked {
  param(
    [Parameter(Mandatory)]
    [string]$Name,

    [Parameter(Mandatory)]
    [scriptblock]$Command
  )

  Write-Output "==> $Name"
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Name failed with exit code $LASTEXITCODE"
  }
}

$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
Push-Location $repositoryRoot
try {
  Invoke-Checked "Repository checks" { pwsh -NoProfile -File scripts/check-repository.ps1 }
  Invoke-Checked "Documentation checks" { pwsh -NoProfile -File scripts/check-docs.ps1 }
  Invoke-Checked "Compose contract checks" { pwsh -NoProfile -File deploy/tests/test-compose.ps1 }
  Invoke-Checked "Backend locked dependency sync" { uv sync --project backend --frozen --all-groups }
  Invoke-Checked "Ruff format check" {
    uv run --project backend ruff format --check backend/app backend/tests
  }
  Invoke-Checked "Ruff lint" { uv run --project backend ruff check backend/app backend/tests }
  Invoke-Checked "Strict mypy" { uv run --project backend mypy backend/app }
  Invoke-Checked "Backend non-integration tests" {
    uv run --project backend pytest backend/tests -m "not integration"
  }
  Invoke-Checked "Frontend locked dependency install" { npm --prefix frontend ci }
  Invoke-Checked "Frontend checks" { npm --prefix frontend run check }
  Invoke-Checked "OpenAPI export" {
    uv run --project backend python backend/scripts/export_openapi.py
  }
  Invoke-Checked "Frontend API generation" { npm --prefix frontend run generate:api }
  Invoke-Checked "Generated API drift check" {
    git diff --exit-code -- docs/api/openapi.json frontend/src/services/ragApi
  }
}
finally {
  Pop-Location
}
