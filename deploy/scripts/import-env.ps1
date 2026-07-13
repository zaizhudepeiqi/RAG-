param(
  [Parameter(Mandatory = $true)]
  [string]$Path
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
  throw "Environment file does not exist: $Path"
}

$values = [Collections.Generic.Dictionary[string, string]]::new(
  [StringComparer]::OrdinalIgnoreCase
)
$lineNumber = 0

foreach ($line in [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $Path))) {
  $lineNumber += 1
  $trimmed = $line.Trim()
  if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
    continue
  }

  $separatorIndex = $line.IndexOf("=")
  if ($separatorIndex -lt 1) {
    throw "Invalid environment line $lineNumber in ${Path}: expected KEY=VALUE"
  }

  $key = $line.Substring(0, $separatorIndex).Trim()
  $value = $line.Substring($separatorIndex + 1)
  if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid environment key '$key' on line $lineNumber in $Path"
  }
  if ($values.ContainsKey($key)) {
    throw "Duplicate environment key '$key' in $Path"
  }
  $values.Add($key, $value)
}

if (-not $values.ContainsKey("APP_ENV") -or $values["APP_ENV"] -ne "development") {
  throw "APP_ENV must be development in local environment files"
}

foreach ($entry in $values.GetEnumerator()) {
  [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
}
