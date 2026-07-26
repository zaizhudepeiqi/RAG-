$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$excludedDirectories = [System.Collections.Generic.HashSet[string]]::new(
  [System.StringComparer]::OrdinalIgnoreCase
)
@(
  ".git", ".worktrees", ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", "dist",
  "node_modules", ".venv", "playwright-report", "test-results"
) | ForEach-Object {
  [void]$excludedDirectories.Add($_)
}

function Test-TextFile {
  param([Parameter(Mandatory)][System.IO.FileInfo]$File)

  if ($File.Length -eq 0) {
    return $true
  }

  $length = [Math]::Min(8192, $File.Length)
  $buffer = [byte[]]::new($length)
  $stream = [IO.File]::OpenRead($File.FullName)
  try {
    $count = $stream.Read($buffer, 0, $buffer.Length)
  }
  finally {
    $stream.Dispose()
  }

  $hasUtf16Bom =
    $count -ge 2 -and
    (($buffer[0] -eq 0xFF -and $buffer[1] -eq 0xFE) -or
      ($buffer[0] -eq 0xFE -and $buffer[1] -eq 0xFF))
  if (-not $hasUtf16Bom -and $buffer[0..($count - 1)].Contains([byte]0)) {
    return $false
  }

  if (-not $hasUtf16Bom) {
    try {
      $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
      $decoder = $strictUtf8.GetDecoder()
      $characters = [char[]]::new($strictUtf8.GetMaxCharCount($count))
      $bytesUsed = 0
      $charactersUsed = 0
      $completed = $false
      $decoder.Convert(
        $buffer,
        0,
        $count,
        $characters,
        0,
        $characters.Length,
        $false,
        [ref]$bytesUsed,
        [ref]$charactersUsed,
        [ref]$completed
      )
    }
    catch [Text.DecoderFallbackException] {
      return $false
    }
  }

  $controlBytes = @(
    $buffer[0..($count - 1)] | Where-Object {
      $_ -lt 0x20 -and $_ -notin @(0x09, 0x0A, 0x0C, 0x0D)
    }
  ).Count
  return $hasUtf16Bom -or $controlBytes -le [Math]::Max(1, [Math]::Floor($count * 0.01))
}

$files = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
$repositoryPaths = @(
  git -c core.quotepath=false ls-files --cached --others --exclude-standard
)
if ($LASTEXITCODE -ne 0) {
  throw "git ls-files failed with exit code $LASTEXITCODE"
}
foreach ($repositoryPath in $repositoryPaths) {
  $normalizedPath = $repositoryPath.Replace("/", [IO.Path]::DirectorySeparatorChar)
  $segments = @($normalizedPath -split '[\\/]')
  if ($segments | Where-Object { $excludedDirectories.Contains($_) }) {
    continue
  }

  $item = Get-Item -LiteralPath (Join-Path $repositoryRoot $normalizedPath) -ErrorAction SilentlyContinue
  if ($item -is [System.IO.FileInfo] -and (Test-TextFile $item)) {
    $files.Add($item)
  }
}

$findings = [System.Collections.Generic.List[object]]::new()
function Add-Finding {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][int]$Line,
    [Parameter(Mandatory)][string]$Message
  )

  $findings.Add([pscustomobject]@{ Path = $Path; Line = $Line; Message = $Message })
}

function Test-LocalLink {
  param(
    [Parameter(Mandatory)][string]$Target,
    [Parameter(Mandatory)][System.IO.FileInfo]$Source,
    [Parameter(Mandatory)][int]$LineNumber
  )

  $targetValue = $Target.Trim().Trim("<", ">")
  if (
    [string]::IsNullOrWhiteSpace($targetValue) -or
    $targetValue.StartsWith("#") -or
    $targetValue -match '^(?i:https?://|mailto:)'
  ) {
    return
  }

  $targetValue = ($targetValue -split "#", 2)[0]
  $targetValue = ($targetValue -split "\?", 2)[0]
  if ([string]::IsNullOrWhiteSpace($targetValue) -or [IO.Path]::IsPathRooted($targetValue)) {
    return
  }

  $relativeSource = [IO.Path]::GetRelativePath($repositoryRoot, $Source.FullName).Replace(
    [IO.Path]::DirectorySeparatorChar,
    [char]"/"
  )
  try {
    $decodedTarget = [Uri]::UnescapeDataString($targetValue).Replace("/", [IO.Path]::DirectorySeparatorChar)
    $resolvedTarget = [IO.Path]::GetFullPath((Join-Path $Source.DirectoryName $decodedTarget))
    if (-not (Test-Path -LiteralPath $resolvedTarget)) {
      Add-Finding $relativeSource $LineNumber "relative link does not resolve: $Target"
    }
  }
  catch {
    Add-Finding $relativeSource $LineNumber "relative link is invalid: $Target"
  }
}

$markdownFiles = @($files | Where-Object { $_.Extension -ieq ".md" })
foreach ($file in $markdownFiles) {
  $relativePath = [IO.Path]::GetRelativePath($repositoryRoot, $file.FullName).Replace(
    [IO.Path]::DirectorySeparatorChar,
    [char]"/"
  )
  $lines = @(Get-Content -LiteralPath $file.FullName)
  $h1Lines = [System.Collections.Generic.List[int]]::new()
  $inFence = $false
  $fenceCharacter = ""
  $fenceLength = 0
  $fenceOpeningLine = 0

  for ($index = 0; $index -lt $lines.Count; $index++) {
    $line = $lines[$index]
    $lineNumber = $index + 1

    if ($inFence) {
      $closingPattern = '^\s*' + [regex]::Escape($fenceCharacter) + "{$fenceLength,}\s*$"
      if ($line -match $closingPattern) {
        $inFence = $false
      }
      continue
    }

    $fenceMatch = [regex]::Match($line, '^\s*(?<fence>`{3,}|~{3,})')
    if ($fenceMatch.Success) {
      $inFence = $true
      $fenceCharacter = $fenceMatch.Groups["fence"].Value.Substring(0, 1)
      $fenceLength = $fenceMatch.Groups["fence"].Value.Length
      $fenceOpeningLine = $lineNumber
      continue
    }

    if ($line -match '^#(?!#)\s+\S') {
      $h1Lines.Add($lineNumber)
    }
    elseif (
      $line -match '^\s*=+\s*$' -and
      $index -gt 0 -and
      -not [string]::IsNullOrWhiteSpace($lines[$index - 1])
    ) {
      $h1Lines.Add($lineNumber - 1)
    }

    $visibleLine = [regex]::Replace($line, '`[^`]*`', '')
    foreach ($match in [regex]::Matches($visibleLine, '!?\[[^\]]*\]\(\s*(?<target><[^>]+>|[^\s\)]+)')) {
      Test-LocalLink $match.Groups["target"].Value $file $lineNumber
    }
    $referenceMatch = [regex]::Match($visibleLine, '^\s*\[[^\]]+\]:\s*(?<target><[^>]+>|\S+)')
    if ($referenceMatch.Success) {
      Test-LocalLink $referenceMatch.Groups["target"].Value $file $lineNumber
    }

    $documentedMarkerPattern = switch ($relativePath) {
      'docs/acceptance/v1-acceptance.md' { '仓库无\s+TBD/TODO\s+核心需求'; break }
      'docs/requirements/13-engineering-quality-source.md' { '文档链接/冲突/TBD\s+扫描'; break }
      'docs/requirements/90-decision-register.md' { '明确延期，不是待确认'; break }
      default { $null }
    }
    $documentedSpan = if ($documentedMarkerPattern) {
      [regex]::Match($visibleLine, $documentedMarkerPattern)
    }
    else {
      $null
    }
    foreach ($markerMatch in [regex]::Matches($visibleLine, '(?i)\b(TODO|TBD|FIXME)\b|\bplaceholder\b|待确认|待补充')) {
      $markerEnd = $markerMatch.Index + $markerMatch.Length
      $documentedEnd = if ($documentedSpan) {
        $documentedSpan.Index + $documentedSpan.Length
      }
      else {
        0
      }
      $documentsMarkerRule =
        $documentedSpan -and
        $documentedSpan.Success -and
        $markerMatch.Index -ge $documentedSpan.Index -and
        $markerEnd -le $documentedEnd
      if (-not $documentsMarkerRule) {
        Add-Finding $relativePath $lineNumber "unresolved placeholder marker: $($markerMatch.Value)"
        break
      }
    }
  }

  if ($inFence) {
    Add-Finding $relativePath $fenceOpeningLine "unclosed fenced code block"
  }
  if ($h1Lines.Count -ne 1) {
    Add-Finding $relativePath 1 "expected exactly one H1; found $($h1Lines.Count)"
  }
}

$credentialPatterns = @(
  @{ Name = "GitHub credential"; Pattern = '(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{20,}' },
  @{ Name = "GitHub fine-grained credential"; Pattern = '(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,}' },
  @{ Name = "OpenAI credential"; Pattern = '(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}' },
  @{ Name = "Google credential"; Pattern = '(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}' },
  @{ Name = "private key header"; Pattern = '-{5}BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-{5}' }
)
$secretAssignmentPattern = '(?i)(?<key>"[A-Za-z_][A-Za-z0-9_-]*"|''[A-Za-z_][A-Za-z0-9_-]*''|[A-Za-z_][A-Za-z0-9_-]*)\s*[:=]\s*(?<value>SecretStr\("[^"]*"\)|"[^"]*"|''[^'']*''|\$\{[^}]+\}|[^\s#,;\}\]]+)'
$configurationExtensions = @(".cfg", ".conf", ".env", ".example", ".ini", ".json", ".properties", ".toml", ".yaml", ".yml")

function Test-CredentialAssignment {
  param(
    [Parameter(Mandatory)][string]$Key,
    [Parameter(Mandatory)][string]$Extension
  )

  if ($Key -ieq "token") {
    return $configurationExtensions -contains $Extension
  }

  return (
    $Key -match '(?i)(password|secret)$' -or
    $Key -match '(?i)[_-]token$' -or
    $Key -match '(?i)(^|[_-])api[_-]?key$' -or
    $Key -match '(?i)^(jwt[_-]?signing[_-]?key|credential[_-]?encryption[_-]?key)$'
  )
}

@(
  @{ Key = "tiktoken"; Extension = ".toml"; Expected = $false },
  @{ Key = "token"; Extension = ".py"; Expected = $false },
  @{ Key = "token"; Extension = ".env"; Expected = $true },
  @{ Key = "access_token"; Extension = ".py"; Expected = $true },
  @{ Key = "api_token"; Extension = ".py"; Expected = $true },
  @{ Key = "password"; Extension = ".py"; Expected = $true }
) | ForEach-Object {
  $actual = Test-CredentialAssignment -Key $_.Key -Extension $_.Extension
  if ($actual -ne $_.Expected) {
    throw "Credential assignment classifier contract failed for '$($_.Key)'"
  }
}

$localDevelopmentValues = @{
  POSTGRES_PASSWORD = "local-dev-only-change-before-sharing"
  JWT_SIGNING_KEY = "local-development-jwt-key-32-bytes-minimum"
  CREDENTIAL_ENCRYPTION_KEY = "bG9jYWwtZGV2LWNyZWRlbnRpYWwta2V5LTAwMDAwMDE="
  INITIAL_ADMIN_PASSWORD = "Local-Development-Admin-Password-01!"
}
$openApiExampleValues = [System.Collections.Generic.HashSet[string]]::new(
  [System.StringComparer]::Ordinal
)
@(
  "openapi-export-only-jwt-key-0001",
  "b3BlbmFwaS1leHBvcnQtY3JlZGVudGlhbC1rZXktMDE=",
  "OpenAPI-Export-Only-Password-03!"
) | ForEach-Object { [void]$openApiExampleValues.Add($_) }
$testFixtureValues = [System.Collections.Generic.HashSet[string]]::new(
  [System.StringComparer]::Ordinal
)
@(
  "j",
  "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M=",
  "Initial-Admin-Password-01!",
  "Different-Admin-Password-02!",
  "Wrong-Password-01!",
  "openapi-test-only-jwt-signing-key",
  "OpenAPI-Test-Only-Password-03!",
  "enterprise-知识库-42",
  "admin123"
) | ForEach-Object { [void]$testFixtureValues.Add($_) }

foreach ($file in $files) {
  $relativePath = [IO.Path]::GetRelativePath($repositoryRoot, $file.FullName).Replace(
    [IO.Path]::DirectorySeparatorChar,
    [char]"/"
  )
  try {
    $lines = @(Get-Content -LiteralPath $file.FullName)
  }
  catch {
    Add-Finding $relativePath 1 "could not read text file"
    continue
  }

  for ($index = 0; $index -lt $lines.Count; $index++) {
    $line = $lines[$index]
    $lineNumber = $index + 1
    foreach ($credentialPattern in $credentialPatterns) {
      if ($line -match $credentialPattern.Pattern) {
        Add-Finding $relativePath $lineNumber "possible $($credentialPattern.Name)"
      }
    }

    if ($file.FullName -eq $PSCommandPath) {
      continue
    }
    foreach ($assignment in [regex]::Matches($line, $secretAssignmentPattern)) {
      $key = $assignment.Groups["key"].Value.Trim('"', "'")
      $rawValue = $assignment.Groups["value"].Value.Trim()
      $isCredentialKey = Test-CredentialAssignment `
        -Key $key `
        -Extension $file.Extension
      if (-not $isCredentialKey) {
        continue
      }

      $secretStrMatch = [regex]::Match($rawValue, '^SecretStr\("(?<value>[^"]*)"\)$')
      $isQuoted = $rawValue.StartsWith('"') -or $rawValue.StartsWith("'") -or $secretStrMatch.Success
      $value = if ($secretStrMatch.Success) {
        $secretStrMatch.Groups["value"].Value
      }
      else {
        $rawValue.Trim('"', "'")
      }
      $isPlaceholder =
        [string]::IsNullOrWhiteSpace($value) -or
        $value -match '^<[^>]+>$|^\$\{[^}]+\}$|^\{\{.+\}\}$|^\$env:[A-Za-z_][A-Za-z0-9_]*$|^(?i:null|none|nil|\{|\[)$'
      $isVariableReference =
        -not $isQuoted -and
        -not ($configurationExtensions -contains $file.Extension) -and
        ($value -match '^[A-Za-z_$][A-Za-z0-9_.$\[\]\(\)-]*$' -or
          $value -match '^requiredEnvironment\(' -or
          $value -match '^base64\.b64encode\(' -or
          $value -match '^[A-Za-z_$][A-Za-z0-9_.$\[\]\("''-]*\)$' -or
          ($value -eq '...' -and $line -match '^\s*(?:async\s+)?def\s+'))

      $isLocalDevelopmentExample = $false
      if (
        $relativePath -in @(
          'deploy/env/.env.development.example',
          'docs/implementation/01-foundation-implementation-plan.md'
        ) -and
        $localDevelopmentValues.ContainsKey($key)
      ) {
        $isLocalDevelopmentExample = $value -ceq $localDevelopmentValues[$key]
      }

      $isOpenApiExample =
        $relativePath -in @(
          'backend/scripts/export_openapi.py',
          'docs/implementation/01-foundation-implementation-plan.md'
        ) -and
        $openApiExampleValues.Contains($value)
      $isKnownTestFixture =
        $relativePath -match '^backend/tests/' -and
        $testFixtureValues.Contains($value)
      $isDocumentedWeakPasswordTest =
        $relativePath -eq 'docs/implementation/01-foundation-implementation-plan.md' -and
        $key -eq 'INITIAL_ADMIN_PASSWORD' -and
        $value -ceq 'admin123'
      $isKnownCsrfFixture =
        $relativePath -eq 'frontend/tests/features/request.test.ts' -and
        $key -eq 'X-CSRF-Token' -and
        $value -ceq 'csrf value'

      if (-not (
        $isPlaceholder -or
        $isVariableReference -or
        $isLocalDevelopmentExample -or
        $isOpenApiExample -or
        $isKnownTestFixture -or
        $isDocumentedWeakPasswordTest -or
        $isKnownCsrfFixture
      )) {
        Add-Finding $relativePath $lineNumber "secret-like assignment '$key' contains a literal value"
      }
    }
  }
}

if ($findings.Count -gt 0) {
  $findings |
    Sort-Object Path, Line, Message -Unique |
    ForEach-Object { Write-Output "$($_.Path):$($_.Line): $($_.Message)" }
  exit 1
}

Write-Output "Documentation and repository secret checks passed for $($markdownFiles.Count) Markdown files."
