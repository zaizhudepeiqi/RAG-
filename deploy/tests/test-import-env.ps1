$ErrorActionPreference = "Stop"

$scriptPath = "deploy/scripts/import-env.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw "Environment import script is missing: $scriptPath"
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) "rag-import-env-$([Guid]::NewGuid())"
New-Item -ItemType Directory -Path $testRoot -ErrorAction Stop | Out-Null

try {
  $validPath = Join-Path $testRoot "valid.env"
  [IO.File]::WriteAllLines(
    $validPath,
    @(
      "# comment",
      "APP_ENV=development",
      "RAG_TEST_SIMPLE=value",
      "RAG_TEST_EQUALS=value=with=equals"
    ),
    [Text.UTF8Encoding]::new($false)
  )

  $output = @(. $scriptPath -Path $validPath)
  if ($output.Count -ne 0) {
    throw "Environment import must not print imported values"
  }
  if ($env:RAG_TEST_SIMPLE -ne "value") {
    throw "Simple environment value was not imported"
  }
  if ($env:RAG_TEST_EQUALS -ne "value=with=equals") {
    throw "Environment value must split only on the first equals sign"
  }

  $duplicatePath = Join-Path $testRoot "duplicate.env"
  [IO.File]::WriteAllLines(
    $duplicatePath,
    @("APP_ENV=development", "RAG_TEST_DUP=one", "RAG_TEST_DUP=two"),
    [Text.UTF8Encoding]::new($false)
  )
  $duplicateRejected = $false
  try {
    . $scriptPath -Path $duplicatePath
  }
  catch {
    $duplicateRejected = $_.Exception.Message.Contains("Duplicate environment key")
  }
  if (-not $duplicateRejected) {
    throw "Duplicate environment keys must be rejected"
  }

  $invalidPath = Join-Path $testRoot "invalid.env"
  [IO.File]::WriteAllText(
    $invalidPath,
    "APP_ENV=development`nINVALID_LINE`n",
    [Text.UTF8Encoding]::new($false)
  )
  $invalidRejected = $false
  try {
    . $scriptPath -Path $invalidPath
  }
  catch {
    $invalidRejected = $_.Exception.Message.Contains("Invalid environment line")
  }
  if (-not $invalidRejected) {
    throw "Environment lines without equals signs must be rejected"
  }
}
finally {
  Remove-Item Env:RAG_TEST_SIMPLE -ErrorAction SilentlyContinue
  Remove-Item Env:RAG_TEST_EQUALS -ErrorAction SilentlyContinue
  Remove-Item Env:RAG_TEST_DUP -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $testRoot) {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
  }
}

Write-Output "Environment import behavior is valid."
