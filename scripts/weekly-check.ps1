<#
.SYNOPSIS
  Weekly drift pass for the AI architecture map. Runs from Windows Task Scheduler.

.DESCRIPTION
  0. preflight: branch is main, its upstream is origin/main, the local branch is not ahead of it;
     then git pull --ff-only and HEAD must equal the upstream
  1. python -m drift check       (read-only compare; writes reports\<run_id>.md + .json)
  2. python -m drift triage      (only if the check flagged something, even if other claims errored;
                                  needs .env with the API key; budget-capped)
  3. python -m drift auto        (renew routine claims from this run's report; build and render a new
                                  map version when content changed or the published one is near its
                                  re-check deadline; anything else waits for the owner's decision)
  4. python -m drift map check   (is the newest map still valid?)
  5. publish: commit only reports\, registry\claims.yaml, maps\, README.md, MAP.md and CHANGELOG.md,
     and push with an explicit refspec HEAD:main

  Each stage gets its own status (ok | flagged | failed | skipped | nothing), written to
  logs\weekly-status-YYYY-MM-DD.json. The last fully successful run's timestamp is written to
  logs\weekly-last-success.txt. Logs go to logs\weekly-YYYY-MM-DD.log (gitignored). No secrets are read
  or written by this script.

  Exit code: 1 if any stage failed; 2 if preflight refused to run; 3 if something was flagged and
  nothing failed; 0 otherwise.

  Alert: when any stage failed, the owner is told through a GitHub issue opened with `gh issue create`
  (label weekly-run-failed, title "Weekly run failed <date>", body = stage statuses and the log file
  name; never log contents or secrets). No duplicate is opened while an open issue carries that label or
  the stable title marker "Weekly run failed " (so an unlabelled fallback issue is found too). If gh is
  missing or not authenticated, that is logged and the exit code is unchanged. Create the label once:
  gh label create weekly-run-failed (without it the issue is opened unlabelled).

  README sections "How a claim is checked" and "Security posture" describe the rules this job follows.

  Register (from the repo folder, PowerShell, no admin needed):
    $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + (Resolve-Path .\scripts\weekly-check.ps1) + '"')
    $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 8:00am
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName 'ai-architecture-map weekly drift check' -Action $a -Trigger $t -Settings $s -Description 'Weekly drift check for the 12-layer AI architecture map (github.com/Double00kevin/ai-security-architecture-map)'
#>

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$stamp = Get-Date -Format 'yyyy-MM-dd'
$logDir = Join-Path $repo 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "weekly-$stamp.log"
$statusFile = Join-Path $logDir "weekly-status-$stamp.json"
$successFile = Join-Path $logDir 'weekly-last-success.txt'

$status = [ordered]@{ preflight = 'skipped'; check = 'skipped'; triage = 'skipped'; auto = 'skipped'; map = 'skipped'; publish = 'skipped' }

# Helper names must not collide with a built-in alias: PowerShell resolves an alias before a function,
# so a function called `Tee` is silently replaced by `tee` -> Tee-Object on Windows. The guard below
# refuses to run if any helper resolves to anything but this script's own function.
function Write-RunLog {
  param([Parameter(ValueFromPipeline = $true)] $Line)
  process {
    $s = "$Line"
    Write-Host $s
    # UTF-8 on purpose: Tee-Object writes UTF-16 on Windows PowerShell 5.1.
    Add-Content -LiteralPath $log -Value $s -Encoding UTF8
  }
}
function Write-Stamped([string]$msg) {
  Write-RunLog ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}
function Invoke-Native([string]$exe, [string[]]$argv) {
  # Runs a native command, logs every output line, and returns its exit code. A command that never
  # started (not found, pipeline failed to bind, threw) returns a negative code, never 0.
  $global:LASTEXITCODE = -999999
  try {
    & $exe @argv 2>&1 | ForEach-Object { Write-RunLog "$_" }
  } catch {
    Write-Stamped "ERROR: '$exe $($argv -join ' ')' did not run: $_"
    return -999998
  }
  $code = $global:LASTEXITCODE
  if ($code -eq -999999) {
    Write-Stamped "ERROR: '$exe $($argv -join ' ')' did not run (no exit code)"
    return -999997
  }
  return $code
}
function Save-Status {
  $doc = [ordered]@{ date = $stamp; finished = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); stages = $status }
  ($doc | ConvertTo-Json -Depth 3) | Set-Content -LiteralPath $statusFile -Encoding UTF8
}
function Open-FailureIssue {
  # Tell the owner. One open issue per failure streak; the body carries statuses and a file name only.
  $label = 'weekly-run-failed'
  $titleMarker = 'Weekly run failed '  # stable prefix: finds an unlabelled issue opened by the fallback below
  $gh = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $gh) { Write-Stamped 'alert: gh not found on PATH; no issue opened (exit code unchanged)'; return }
  $ghExe = $gh.Source
  $global:LASTEXITCODE = -999999
  & $ghExe auth status *> $null  # its output names the account; never logged
  if ($LASTEXITCODE -ne 0) { Write-Stamped "alert: gh is not usable (auth status exit $LASTEXITCODE); no issue opened (exit code unchanged)"; return }
  $global:LASTEXITCODE = -999999
  $raw = (& $ghExe issue list --state open --limit 200 --json number,title,labels 2>$null) | Out-String
  if ($LASTEXITCODE -ne 0) { Write-Stamped "alert: cannot list open issues (exit $LASTEXITCODE); no issue opened"; return }
  try { $parsed = $raw | ConvertFrom-Json } catch { Write-Stamped 'alert: cannot read the open-issue list; no issue opened'; return }
  $open = 0
  foreach ($issue in $parsed) {  # foreach enumerates the array on Windows PowerShell 5.1 and 7 alike
    $names = @($issue.labels | ForEach-Object { $_.name })
    if (("$($issue.title)".StartsWith($titleMarker)) -or ($names -contains $label)) { $open++ }
  }
  if ($open -gt 0) { Write-Stamped "alert: an open '$label' issue (or one titled '$($titleMarker.Trim())') already exists; not opening a duplicate"; return }
  $bodyFile = Join-Path $logDir "weekly-issue-$stamp.md"
  $lines = @("The weekly drift run on $stamp failed.", '', 'Stage statuses:', '') +
    @($status.Keys | ForEach-Object { "- ${_}: $($status[$_])" }) +
    @('', "Log file: logs/$(Split-Path -Leaf $log) on the machine that runs the job. It is not attached; this issue carries no log contents.",
      '', 'Opened by scripts/weekly-check.ps1. Close it once a weekly run succeeds.')
  [System.IO.File]::WriteAllLines($bodyFile, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
  $title = "$titleMarker$stamp"
  $global:LASTEXITCODE = -999999
  & $ghExe issue create --title $title --label $label --body-file $bodyFile 2>&1 | ForEach-Object { Write-RunLog "$_" }
  if ($LASTEXITCODE -eq 0) { Write-Stamped "alert: opened '$title'"; return }
  Write-Stamped "alert: gh issue create with label '$label' failed (exit $LASTEXITCODE; does the label exist?); retrying without it"
  $global:LASTEXITCODE = -999999
  & $ghExe issue create --title $title --body-file $bodyFile 2>&1 | ForEach-Object { Write-RunLog "$_" }
  if ($LASTEXITCODE -eq 0) { Write-Stamped "alert: opened '$title' (unlabelled)" }
  else { Write-Stamped "alert: could not open an issue (exit $LASTEXITCODE); exit code unchanged" }
}
function Complete-Run([int]$code) {
  Save-Status
  if (@($status.Values) -contains 'failed') {
    try { Open-FailureIssue } catch { Write-Stamped "alert: failed to open an issue: $($_.Exception.Message)" }
  }
  Write-Stamped ("stages: " + (($status.Keys | ForEach-Object { "$_=$($status[$_])" }) -join ' '))
  Write-Stamped "=== done (exit $code) ==="
  exit $code
}
function Get-GitOutput([string[]]$gitArgs) {
  $global:LASTEXITCODE = -999999
  $out = & git @gitArgs 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  return ("$out").Trim()
}

foreach ($helper in 'Write-RunLog', 'Write-Stamped', 'Invoke-Native', 'Save-Status', 'Complete-Run', 'Get-GitOutput', 'Open-FailureIssue') {
  $resolved = Get-Command $helper -ErrorAction SilentlyContinue
  if (-not $resolved -or $resolved.CommandType -ne 'Function') {
    Write-Error "helper '$helper' resolves to $($resolved.CommandType) '$($resolved.Definition)', not this script's function; refusing to run"
    exit 2
  }
}
$startUtc = (Get-Date).ToUniversalTime()

Write-Stamped "=== weekly drift check start (repo: $(Split-Path -Leaf $repo)) ==="

# ---- 0. preflight ------------------------------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Stamped "ERROR: python not found on PATH"; $status.preflight = 'failed'; Complete-Run 2 }
$code = Invoke-Native python @('-c', 'import yaml')
if ($code -ne 0) { Write-Stamped "ERROR: PyYAML missing. Run: python -m pip install --require-hashes -r requirements.txt"; $status.preflight = 'failed'; Complete-Run 2 }

$branch = Get-GitOutput @('rev-parse', '--abbrev-ref', 'HEAD')
if ($branch -ne 'main') { Write-Stamped "ERROR: on branch '$branch', not main; refusing to run"; $status.preflight = 'failed'; Complete-Run 2 }
$upstream = Get-GitOutput @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
if ($upstream -ne 'origin/main') { Write-Stamped "ERROR: upstream is '$upstream', not origin/main; refusing to run"; $status.preflight = 'failed'; Complete-Run 2 }
$code = Invoke-Native git @('fetch', '--quiet', 'origin', 'main')
if ($code -ne 0) { Write-Stamped "ERROR: git fetch failed; not running on a stale tree"; $status.preflight = 'failed'; Complete-Run 2 }
$ahead = Get-GitOutput @('rev-list', '--count', '@{u}..HEAD')
if ($ahead -ne '0') { Write-Stamped "ERROR: local main is $ahead commit(s) ahead of origin/main; push or reset by hand first. Refusing to run."; $status.preflight = 'failed'; Complete-Run 2 }
$dirtyAtStart = (& git status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { Write-Stamped 'ERROR: cannot establish a clean working tree'; $status.preflight = 'failed'; Complete-Run 2 }
if ($dirtyAtStart) { Write-Stamped "ERROR: modified or untracked files exist; refusing to publish pre-existing work:"; $dirtyAtStart | Write-RunLog; $status.preflight = 'failed'; Complete-Run 2 }
Write-Stamped "git pull --ff-only"
$code = Invoke-Native git @('pull', '--ff-only', '--quiet')
if ($code -ne 0) { Write-Stamped "ERROR: git pull failed (exit $code); not running check on a stale tree"; $status.preflight = 'failed'; Complete-Run 2 }
$head = Get-GitOutput @('rev-parse', 'HEAD'); $up = Get-GitOutput @('rev-parse', '@{u}')
if (-not $head -or $head -ne $up) { Write-Stamped "ERROR: HEAD ($head) != origin/main ($up) after pull; refusing to run"; $status.preflight = 'failed'; Complete-Run 2 }
$status.preflight = 'ok'

# ---- 1. check ----------------------------------------------------------------------------------
Write-Stamped "python -m drift check"
$check = Invoke-Native python @('-m', 'drift', 'check')
Write-Stamped "drift check exit code: $check"
switch ($check) { 0 { $status.check = 'ok' } 3 { $status.check = 'flagged' } default { $status.check = 'failed' } }

# The exit code alone is not evidence the check ran: it must also have written a report during this run
# (exit 0 clean, 1 errors, 3 flagged all write one; 2 is a setup failure and writes none).
$newest = Get-ChildItem -LiteralPath (Join-Path $repo 'reports') -Filter '*.json' -ErrorAction SilentlyContinue |
  Where-Object { $_.BaseName -match '^\d{4}-\d{2}-\d{2}T\d{6}Z' -and $_.BaseName -notmatch '-(triage|auto)$' -and $_.LastWriteTimeUtc -ge $startUtc } |
  Sort-Object Name | Select-Object -Last 1
if (($check -in @(0, 1, 3)) -and (-not $newest)) {
  Write-Stamped "ERROR: drift check exited $check but wrote no report during this run"
  $status.check = 'failed'
}

# ---- 2. triage: runs whenever anything was flagged, even if other claims errored ----------------
$flagged = 0
if ($newest) {
  try { $flagged = [int]((Get-Content -Raw -Encoding UTF8 $newest.FullName | ConvertFrom-Json).summary.flagged) } catch { $flagged = 0 }
}
if ($flagged -gt 0 -and $check -ne 2) {
  if (Test-Path (Join-Path $repo '.env')) {
    Write-Stamped "python -m drift triage --report reports\$($newest.Name) ($flagged flagged; budget-capped; key read from .env, never logged)"
    $code = Invoke-Native python @('-m', 'drift', 'triage', '--report', $newest.FullName)
    if ($code -eq 0) { $status.triage = 'ok' } else { $status.triage = 'failed'; Write-Stamped "triage exit code: $code" }
  } else {
    Write-Stamped "triage skipped: no .env (flagged findings stay untriaged for the owner's decision)"
    $status.triage = 'skipped'
  }
} else {
  $status.triage = 'nothing'
}

# ---- 3. auto: renew routine claims, publish a new version when needed ----------------------------
# Runs on this run's full report even when some sources errored: those claims wait for the owner's decision.
if ($newest) {
  Write-Stamped "python -m drift auto --report reports\$($newest.Name)"
  $code = Invoke-Native python @('-m', 'drift', 'auto', '--report', $newest.FullName)
  switch ($code) {
    0 { $status.auto = 'ok' }
    3 { $status.auto = 'needs_owner'; Write-Stamped "some claims wait for the owner's decision; see reports\*-auto.md" }
    default { $status.auto = 'failed'; Write-Stamped "drift auto exit code: $code" }
  }
}

# ---- 4. map validity ----------------------------------------------------------------------------
Write-Stamped "python -m drift map check"
$code = Invoke-Native python @('-m', 'drift', 'map', 'check')
if ($code -eq 0) { $status.map = 'ok' } else { $status.map = 'failed'; Write-Stamped "map check failed: the newest map is expired or missing; ship a new version (README, 'How a claim is checked')" }
if ($status.map -eq 'ok') {
  Write-Stamped 'python -m drift map verify'
  $code = Invoke-Native python @('-m', 'drift', 'map', 'verify')
  if ($code -ne 0) { $status.map = 'failed'; Write-Stamped 'map verification failed; publication refused' }
}

# Failed stages may leave useful reports and diagnostic files. Keep them local, never publish
# partial artifacts or registry edits. An interrupted run is also blocked by the next clean-tree gate.
$failed = @($status.Keys | Where-Object { $status[$_] -eq 'failed' })
if ($failed.Count -gt 0) {
  Write-Stamped ('publication skipped because stages failed: ' + ($failed -join ', '))
  Complete-Run 1
}

# ---- 5. publish: only what the job writes, only onto an unchanged origin/main --------------------
$publishPaths = @('reports', 'registry/claims.yaml', 'maps', 'README.md', 'MAP.md', 'CHANGELOG.md')
$pathRe = '^(reports/|registry/claims\.yaml$|maps/|README\.md$|MAP\.md$|CHANGELOG\.md$)'
$dirty = (& git status --porcelain --untracked-files=all) | Where-Object { $_.Length -gt 3 -and ($_.Substring(3).Trim('"') -notmatch $pathRe) }
if ($LASTEXITCODE -ne 0) { $status.publish = 'failed'; Write-Stamped 'cannot inspect publication paths'; Complete-Run 1 }
if ($dirty) {
  Write-Stamped "publish failed: working tree has unrelated changes; report left uncommitted:"
  $dirty | Write-RunLog
  $status.publish = 'failed'
} else {
  $present = @($publishPaths | Where-Object { Test-Path -LiteralPath (Join-Path $repo $_) })
  if ($present.Count -gt 0) {
    $code = Invoke-Native git (@('add', '--') + $present)
    if ($code -ne 0) { $status.publish = 'failed'; Write-Stamped 'git add failed'; Complete-Run 1 }
  }
  $staged = (& git diff --cached --name-only)
  if ($LASTEXITCODE -ne 0) { $status.publish = 'failed'; Write-Stamped 'cannot inspect staged files'; Complete-Run 1 }
  if (-not $staged) {
    Write-Stamped "nothing new to commit"
    $status.publish = 'nothing'
  } else {
    $code = Invoke-Native git @('fetch', '--quiet', 'origin', 'main')
    if ($code -ne 0) { $status.publish = 'failed'; Write-Stamped 'cannot refresh origin before publication'; Complete-Run 1 }
    $head = Get-GitOutput @('rev-parse', 'HEAD'); $up = Get-GitOutput @('rev-parse', 'origin/main')
    $branch = Get-GitOutput @('rev-parse', '--abbrev-ref', 'HEAD')
    if ($branch -ne 'main' -or $head -ne $up) {
      Write-Stamped "publish failed: branch '$branch' or origin/main moved during the run (HEAD $head, origin/main $up); report left staged"
      $status.publish = 'failed'
    } else {
      $code = Invoke-Native git @('commit', '-q', '-m', "Weekly drift run $stamp (check $($status.check), triage $($status.triage), auto $($status.auto), map $($status.map))")
      if ($code -ne 0) {
        Write-Stamped "publish failed: commit failed (is gitleaks installed? the pre-commit hook requires it)"
        $status.publish = 'failed'
      } else {
        $code = Invoke-Native git @('push', 'origin', 'HEAD:main')
        if ($code -ne 0) { Write-Stamped "publish failed: push failed (exit $code); commit is local, push it by hand"; $status.publish = 'failed' }
        else { $status.publish = 'ok' }
      }
    }
  }
}

# ---- result -------------------------------------------------------------------------------------
$failed = @($status.Keys | Where-Object { $status[$_] -eq 'failed' })
if ($failed.Count -gt 0) { Write-Stamped ("FAILED stage(s): " + ($failed -join ', ')); Complete-Run 1 }
(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') | Set-Content -Path $successFile -Encoding UTF8
Write-Stamped "last success recorded in logs\$(Split-Path -Leaf $successFile)"
if ($status.check -eq 'flagged' -or $status.auto -eq 'needs_owner') { Complete-Run 3 }
Complete-Run 0
