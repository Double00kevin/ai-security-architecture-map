<#
.SYNOPSIS
  End-to-end test of scripts/weekly-check.ps1 under the PowerShell that runs this file.

.DESCRIPTION
  For each scenario: a throwaway repo with a local bare `origin`, a copy of the real weekly script,
  and a fake `python` (tests/weekly/fakepy.py) first on PATH. The script is then run in a child
  process of the same PowerShell (Windows PowerShell 5.1 when invoked with `powershell`), with the
  standard alias table intact. On Linux, where PowerShell has no `tee` alias, the Windows alias is
  added so the alias-over-function collision is still exercised.

  Assertions cover the exit code, every stage status, the last-success marker, the UTF-8 log, which
  fake-python calls actually ran, and what reached `origin`. Exit 0 when every scenario passes.

  Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tests\weekly\harness.ps1   (Windows 5.1)
          pwsh -NoProfile -File tests/weekly/harness.ps1                                   (7.x)
          add -Script <path> to test another copy of the weekly script (e.g. an older commit's).
#>
param([string]$Script, [string]$Python)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
if (-not $Script) { $Script = Join-Path $root 'scripts/weekly-check.ps1' }
$Script = (Resolve-Path -LiteralPath $Script).Path
$fakepy = Join-Path $here 'fakepy.py'
$fakegh = Join-Path $here 'fakegh.py'
$onWindows = [System.IO.Path]::DirectorySeparatorChar -eq '\'
$psExe = (Get-Process -Id $PID).Path
$realPy = $Python
foreach ($cand in 'python', 'python3') {
  if ($realPy) { break }
  $c = Get-Command $cand -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { $realPy = $c.Source; break }
}
if (-not $realPy) { throw 'no real python found for the fake python shim' }

"PowerShell $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition)); tee alias present natively: $([bool](Get-Alias tee -ErrorAction SilentlyContinue))"

$failures = New-Object System.Collections.Generic.List[string]
function Assert-That([string]$scenario, [bool]$ok, [string]$what) {
  if ($ok) { "  ok   $what" } else { "  FAIL $what"; $failures.Add("${scenario}: $what") }
}

function Invoke-Git {
  # Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop'; git writes
  # progress and warnings to stderr, so judge it by its exit code only.
  $ErrorActionPreference = 'Continue'
  $out = & git @args 2>&1
  if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed: $out" }
  $out
}

function New-Fixture([string]$dir) {
  if (Test-Path -LiteralPath $dir) { throw 'fixture directory unexpectedly exists' }
  New-Item -ItemType Directory -Path $dir | Out-Null
  $origin = Join-Path $dir 'origin.git'
  $repo = Join-Path $dir 'repo'
  $bin = Join-Path $dir 'bin'
  Invoke-Git init -q --bare -b main $origin | Out-Null
  Invoke-Git clone -q $origin $repo 2>$null | Out-Null
  Invoke-Git -C $repo config user.email 'harness@example.invalid' | Out-Null
  Invoke-Git -C $repo config user.name 'harness' | Out-Null
  Invoke-Git -C $repo config core.autocrlf false | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $repo 'scripts'), $bin | Out-Null
  Copy-Item -LiteralPath $Script -Destination (Join-Path $repo 'scripts/weekly-check.ps1')
  Set-Content -LiteralPath (Join-Path $repo '.gitignore') -Value "logs/`n.env" -Encoding ASCII
  New-Item -ItemType Directory -Path (Join-Path $repo 'registry') | Out-Null
  Set-Content -LiteralPath (Join-Path $repo 'registry/claims.yaml') -Value 'claims: []' -Encoding ASCII
  Invoke-Git -C $repo add -A | Out-Null
  Invoke-Git -C $repo commit -q -m init | Out-Null
  Invoke-Git -C $repo push -q origin main 2>$null | Out-Null
  if ($onWindows) {
    Set-Content -LiteralPath (Join-Path $bin 'python.cmd') -Encoding ASCII -Value "@`"$realPy`" `"$fakepy`" %*`r`n@exit /b %ERRORLEVEL%"
    Set-Content -LiteralPath (Join-Path $bin 'gh.cmd') -Encoding ASCII -Value "@`"$realPy`" `"$fakegh`" %*`r`n@exit /b %ERRORLEVEL%"
  } else {
    foreach ($pair in @(@('python', $fakepy), @('gh', $fakegh))) {
      $shim = Join-Path $bin $pair[0]
      Set-Content -LiteralPath $shim -Encoding ASCII -Value "#!/bin/sh`nexec `"$realPy`" `"$($pair[1])`" `"`$@`""
      & chmod +x $shim
    }
  }
  @{ dir = $dir; origin = $origin; repo = $repo; bin = $bin; markers = (Join-Path $dir 'markers') }
}

function Invoke-Weekly($fx, [hashtable]$envs) {
  $ErrorActionPreference = 'Continue'  # see Invoke-Git
  $saved = @{}
  $keys = @('PATH', 'FAKEPY_MARKERS', 'FAKEPY_CHECK_EXIT', 'FAKEPY_FLAGGED', 'FAKEPY_NOREPORT', 'FAKEPY_MAP_EXIT', 'FAKEPY_TRIAGE_EXIT', 'FAKEPY_AUTO_EXIT', 'FAKEPY_VERIFY_EXIT', 'FAKEPY_PARTIAL_WRITE', 'FAKEGH_UNAVAILABLE', 'FAKEGH_OPEN', 'FAKEGH_LABEL_MISSING', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')
  foreach ($k in $keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k) }
  try {
    $emptyCfg = Join-Path $fx.dir 'empty.gitconfig'
    Set-Content -LiteralPath $emptyCfg -Value '' -Encoding ASCII
    [Environment]::SetEnvironmentVariable('GIT_CONFIG_GLOBAL', $emptyCfg)
    [Environment]::SetEnvironmentVariable('GIT_CONFIG_NOSYSTEM', '1')
    [Environment]::SetEnvironmentVariable('PATH', $fx.bin + [System.IO.Path]::PathSeparator + $saved['PATH'])
    [Environment]::SetEnvironmentVariable('FAKEPY_MARKERS', $fx.markers)
    foreach ($k in $envs.Keys) { [Environment]::SetEnvironmentVariable($k, [string]$envs[$k]) }
    $target = Join-Path $fx.repo 'scripts/weekly-check.ps1'
    if ($onWindows) {
      $out = & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $target 2>&1
    } else {
      $cmd = "Set-Alias -Name tee -Value Tee-Object -Scope Global -Option AllScope; & '$target'; exit `$LASTEXITCODE"
      $out = & $psExe -NoProfile -NonInteractive -Command $cmd 2>&1
    }
    $code = $LASTEXITCODE
  } finally {
    foreach ($k in $keys) {
      if ($null -eq $saved[$k]) { Remove-Item -LiteralPath "Env:$k" -ErrorAction SilentlyContinue }
      else { Set-Item -LiteralPath "Env:$k" -Value $saved[$k] }
    }
  }
  $logs = Join-Path $fx.repo 'logs'
  $statusFile = Get-ChildItem -LiteralPath $logs -Filter 'weekly-status-*.json' -ErrorAction SilentlyContinue | Select-Object -First 1
  $logFile = Get-ChildItem -LiteralPath $logs -Filter 'weekly-2*.log' -ErrorAction SilentlyContinue | Select-Object -First 1
  $stages = $null
  if ($statusFile) { $stages = (Get-Content -Raw -LiteralPath $statusFile.FullName | ConvertFrom-Json).stages }
  $logText = ''
  $logUtf16 = $false
  if ($logFile) {
    $bytes = [System.IO.File]::ReadAllBytes($logFile.FullName)
    $logUtf16 = $bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE
    $logText = [System.IO.File]::ReadAllText($logFile.FullName, [System.Text.Encoding]::UTF8)
  }
  $marks = @()
  $issueBodies = @()
  if (Test-Path -LiteralPath $fx.markers) {
    $marks = @(Get-ChildItem -LiteralPath $fx.markers | ForEach-Object { $_.Name.Substring(3) })
    $issueBodies = @(Get-ChildItem -LiteralPath $fx.markers -Filter '*_gh-issue-create' | ForEach-Object { [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8) })
  }
  @{
    code = $code; out = ($out | Out-String); stages = $stages; logText = $logText; logUtf16 = $logUtf16
    success = Test-Path -LiteralPath (Join-Path $logs 'weekly-last-success.txt')
    marks = $marks
    issues = $issueBodies
    originCommits = [int]((& git --git-dir $fx.origin rev-list --count main) | Out-String).Trim()
    originFiles = ((& git --git-dir $fx.origin show --name-only --format= main) | Out-String)
  }
}

function Test-Common([string]$name, $r) {
  Assert-That $name ($null -ne $r.stages) 'status file written'
  Assert-That $name ($r.logText -match '=== done \(exit') 'UTF-8 log written and finished'
  Assert-That $name (-not $r.logUtf16) 'log is not UTF-16'
  Assert-That $name ($r.out -notmatch 'missing mandatory parameters') 'no pipeline binding errors'
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("weekly-harness-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  # 1. clean run: everything runs, report reaches origin, success recorded
  $n = 'clean'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{}
  Test-Common $n $r
  Assert-That $n ($r.code -eq 0) "exit 0 (got $($r.code))"
  Assert-That $n ($r.stages.check -eq 'ok' -and $r.stages.map -eq 'ok' -and $r.stages.publish -eq 'ok') "check/map/publish ok (got $($r.stages | ConvertTo-Json -Compress))"
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift-check*' }).Count -eq 1) 'drift check actually ran'
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift-map-check*' }).Count -eq 1) 'map check actually ran'
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift-map-verify*' }).Count -eq 1) 'map verify actually ran before publication'
  Assert-That $n ($r.success) 'last-success written'
  Assert-That $n ($r.originCommits -eq 2) "report pushed to origin (origin has $($r.originCommits) commits)"
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift-auto*' }).Count -eq 1) 'drift auto actually ran'
  Assert-That $n ($r.stages.auto -eq 'ok') "auto stage ok (got $($r.stages.auto))"
  Assert-That $n ($r.originFiles -match 'registry/claims.yaml' -and $r.originFiles -match 'maps/v2099.01.01/map.json' -and $r.originFiles -match '-auto.json') 'renewed registry, new map version and auto report pushed'
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'gh-*' }).Count -eq 0) 'no alert issue on a clean run'

  # 2. map check fails: failure must be reported, never success
  $n = 'map-fails'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_MAP_EXIT = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.stages.map -eq 'failed') "map stage failed (got $($r.stages.map))"
  Assert-That $n ($r.originCommits -eq 1) 'failed map never published'
  Assert-That $n (-not $r.success) 'no last-success marker'
  Assert-That $n ($r.issues.Count -eq 1) "one alert issue opened (got $($r.issues.Count))"
  $body = "$($r.issues)"
  Assert-That $n ($body -match '--label\s+weekly-run-failed' -and $body -match "Weekly run failed \d{4}-\d{2}-\d{2}") 'issue has the label and a dated title'
  Assert-That $n ($body -match '- map: failed' -and $body -match '- check: ok' -and $body -match 'weekly-\d{4}-\d{2}-\d{2}\.log') 'issue body lists stage statuses and the log file name'
  Assert-That $n ($body -notmatch 'fake map check' -and $body -notmatch 'fake drift check') 'issue body carries no log contents'
  Assert-That $n ($r.logText -match 'alert: opened') 'alert logged'

  # 2b. an open alert issue already exists: no duplicate, exit code unchanged
  $n = 'map-fails-open-issue'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_MAP_EXIT = 1; FAKEGH_OPEN = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.issues.Count -eq 0 -and $r.logText -match 'not opening a duplicate') 'no duplicate issue'

  # 2c. gh unavailable: logged, exit code unchanged
  $n = 'map-fails-no-gh'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_MAP_EXIT = 1; FAKEGH_UNAVAILABLE = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.issues.Count -eq 0 -and $r.logText -match 'gh is not usable') 'unavailable gh logged, no issue'

  # 2d. the label does not exist yet: the alert still goes out, without the label
  $n = 'map-fails-no-label'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_MAP_EXIT = 1; FAKEGH_LABEL_MISSING = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.issues.Count -eq 2 -and "$($r.issues[1])" -notmatch '--label') 'retried without the label'

  # 3. flagged, no .env: triage skipped, exit 3, report still published
  $n = 'flagged'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_CHECK_EXIT = 3; FAKEPY_FLAGGED = 2 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 3) "exit 3 (got $($r.code))"
  Assert-That $n ($r.stages.check -eq 'flagged' -and $r.stages.triage -eq 'skipped') "check flagged, triage skipped (got $($r.stages | ConvertTo-Json -Compress))"
  Assert-That $n ($r.issues.Count -eq 0) 'flagged is not a failure: no alert issue'
  Assert-That $n ($r.originCommits -eq 2) 'report pushed'

  # 4. check exits 0 but writes no report: not evidence the check ran
  $n = 'no-report'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_NOREPORT = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.stages.check -eq 'failed') "check failed (got $($r.stages.check))"
  Assert-That $n (-not $r.success) 'no last-success marker'

  # 4b. auto leaves something for the owner's decision: not a failure, exit 3, still published
  $n = 'needs-owner'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_AUTO_EXIT = 3 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 3) "exit 3 (got $($r.code))"
  Assert-That $n ($r.stages.auto -eq 'needs_owner') "auto needs_owner (got $($r.stages.auto))"
  Assert-That $n ($r.success) 'last-success written (nothing failed)'
  Assert-That $n ($r.originCommits -eq 2) 'published'

  # 4c. auto fails: the run fails and nothing claims success
  $n = 'auto-fails'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_AUTO_EXIT = 1; FAKEPY_PARTIAL_WRITE = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1) "exit 1 (got $($r.code))"
  Assert-That $n ($r.stages.auto -eq 'failed') "auto failed (got $($r.stages.auto))"
  Assert-That $n (-not $r.success) 'no last-success marker'
  Assert-That $n ($r.originCommits -eq 1) 'partially written artifacts never published after auto failure'

  $n = 'verify-fails'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n); $r = Invoke-Weekly $fx @{ FAKEPY_VERIFY_EXIT = 1 }
  Test-Common $n $r
  Assert-That $n ($r.code -eq 1 -and $r.stages.map -eq 'failed') 'verification failure fails the run'
  Assert-That $n ($r.originCommits -eq 1 -and -not $r.success) 'verification failure never publishes or records success'

  foreach ($folder in 'maps', 'reports') {
    $n = "draft-$folder"; "scenario: $n"
    $fx = New-Fixture (Join-Path $tmp $n)
    New-Item -ItemType Directory -Path (Join-Path $fx.repo $folder) | Out-Null
    Set-Content -LiteralPath (Join-Path $fx.repo "$folder/unpublished-draft.txt") -Value 'synthetic private draft' -Encoding ASCII
    $r = Invoke-Weekly $fx @{}
    Assert-That $n ($r.code -eq 2 -and $r.stages.preflight -eq 'failed') 'pre-existing draft blocks publication'
    Assert-That $n ($r.originCommits -eq 1) 'draft never reaches the local origin'
    Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift*' }).Count -eq 0) 'no renewal ran on a dirty baseline'
  }

  # 5. local main ahead of origin: refuse before running anything
  $n = 'ahead'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n)
  Set-Content -LiteralPath (Join-Path $fx.repo 'extra.txt') -Value 'local only' -Encoding ASCII
  Invoke-Git -C $fx.repo add extra.txt | Out-Null
  Invoke-Git -C $fx.repo commit -q -m 'local only' | Out-Null
  $r = Invoke-Weekly $fx @{}
  Assert-That $n ($r.code -eq 2) "exit 2 (got $($r.code))"
  Assert-That $n ($r.stages.preflight -eq 'failed') 'preflight failed'
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift*' }).Count -eq 0) 'no drift command ran'
  Assert-That $n ($r.originCommits -eq 1) 'nothing pushed'
  Assert-That $n (-not $r.success) 'no last-success marker'
  Assert-That $n ($r.issues.Count -eq 1 -and "$($r.issues)" -match '- preflight: failed') 'preflight failure alerts too'

  # 6. off main: refuse
  $n = 'off-main'; "scenario: $n"
  $fx = New-Fixture (Join-Path $tmp $n)
  Invoke-Git -C $fx.repo checkout -q -b feature | Out-Null
  $r = Invoke-Weekly $fx @{}
  Assert-That $n ($r.code -eq 2) "exit 2 (got $($r.code))"
  Assert-That $n (@($r.marks | Where-Object { $_ -like 'm-drift*' }).Count -eq 0) 'no drift command ran'
} finally {
  $resolved = [System.IO.Path]::GetFullPath($tmp)
  $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
      (Split-Path -Leaf $resolved) -notmatch '^weekly-harness-[a-f0-9]{8}$') { throw 'unsafe fixture cleanup path' }
  Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failures.Count -gt 0) {
  "FAILED: $($failures.Count) assertion(s)"
  $failures | ForEach-Object { "  - $_" }
  exit 1
}
'weekly harness: all scenarios passed'
exit 0
