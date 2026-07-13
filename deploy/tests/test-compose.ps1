$ErrorActionPreference = "Stop"

$composePath = "deploy/compose/compose.deps.yml"
if (-not (Test-Path -LiteralPath $composePath)) {
  throw "Compose file is missing: $composePath"
}

$compose = Get-Content -Raw -LiteralPath $composePath
$expectations = @(
  "postgres:17.10-bookworm@sha256:5530681ea5d3e2ed4ce396f9b5cb443efbac6baf2a8a19c0c0635e40ae7eadce",
  "redis:7.4.9-bookworm@sha256:b2b95679e3b46fb51864949ed25ea976fc3a6bcc00a40a1bc00d568cb2822e50",
  "chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6",
  '127.0.0.1:${POSTGRES_PORT:-5432}:5432',
  '127.0.0.1:${REDIS_PORT:-6379}:6379',
  '127.0.0.1:${CHROMA_PORT:-8000}:8000',
  'exec 3<>/dev/tcp/127.0.0.1/8000'
)

foreach ($expected in $expectations) {
  if (-not $compose.Contains($expected)) {
    throw "Compose contract missing: $expected"
  }
}

if ($compose -match '(?m)^\s*image:\s*[^\r\n]*:latest') {
  throw "Floating latest image is forbidden"
}

if ($compose.Contains('["CMD", "curl"')) {
  throw "Chroma 1.5.9 does not contain curl; its healthcheck must use an available executable"
}

Write-Output "Compose image and port contracts are valid."
