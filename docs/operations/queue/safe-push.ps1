# safe-push.ps1: every Release push goes through this (Claude-Mac goatai#2587 6442086007: a mechanism, not care).
# It refuses to push unless the tree is clean, the repo's own pre-push checks pass, and the inbox has no new post
# from Claude-Mac since -SinceId. Any non-zero exit means nothing was pushed.
#   goatai : docs\ops\claude-pc\tools\pin-check.ps1 -Repo <wt> must exit 0 (V79 pins, era, doc gate).
#   GOAT-EA: pin-v149-contract.py must leave the tree unchanged (contract pins current), and test_b49b_no_drift.cjs
#            and test_studio_ea_init_rules.py must pass (init-rule anchors follow the entrypoint).
# Also: never main/master (CLAUDE.md), and git diff --check from the merge base with -Base (default main; CI's arena-guard
# hygiene, which pin-check doesn't catch: CRLF or trailing whitespace). Both from Ops' ops-safe-push.ps1 (10-27).
# Usage: safe-push.ps1 -Repo <worktree> -Branch <name> -SinceId <inbox comment id> [-Base <pr base branch>] [-LeaseSha <sha>] [-SetUpstream]
param([Parameter(Mandatory)][string]$Repo, [Parameter(Mandatory)][string]$Branch, [Parameter(Mandatory)][long]$SinceId,
      [string]$Base = 'main', [string]$LeaseSha = '', [switch]$SetUpstream, [switch]$DryRun)
$ErrorActionPreference = 'Continue'   # PS 5.1: native stderr under 'Stop' throws; every check uses exit codes
$sp = Split-Path $MyInvocation.MyCommand.Path
function Refuse([string]$why) { "REFUSED: $why. Nothing was pushed."; exit 2 }

if ($Branch -in @('main','master')) { Refuse 'never push to main' }
if (@(git -C $Repo status --porcelain).Count -gt 0) { Refuse 'the tree has uncommitted changes' }
if ((git -C $Repo branch --show-current).Trim() -ne $Branch) { Refuse "the worktree is not on $Branch" }
$remote = (git -C $Repo remote get-url origin).Trim()
git -C $Repo fetch -q origin $Base
$mb = (git -C $Repo merge-base "origin/$Base" HEAD)
if ($LASTEXITCODE -ne 0 -or -not $mb) { Refuse "no merge base with origin/$Base" }
git -C $Repo diff --check $mb.Trim() HEAD | Select-Object -First 5
if ($LASTEXITCODE -ne 0) { Refuse "git diff --check from origin/$Base's merge base found whitespace/CRLF errors" }

if ($remote -match 'algogoat/goatai') {
  & (Join-Path $Repo 'docs\ops\claude-pc\tools\pin-check.ps1') -Repo $Repo | Select-Object -Last 1
  if ($LASTEXITCODE -ne 0) { Refuse "pin-check exited $LASTEXITCODE" }
} elseif ($remote -match 'algogoat/GOAT-EA') {
  & 'C:\GOAT\python313-3.13.16\python.exe' (Join-Path $sp 'pin-v149-contract.py') $Repo | Out-Null
  if (@(git -C $Repo status --porcelain).Count -gt 0) { git -C $Repo checkout -- . ; Refuse 'the v149 contract pins were stale (re-pin, commit, retry)' }
  Push-Location $Repo
  try {
    node scripts/test_b49b_no_drift.cjs *> $null; if ($LASTEXITCODE -ne 0) { Refuse 'test_b49b_no_drift failed' }
    $code = "import sys,runpy; sys.path.insert(0,'controller'); sys.argv=['t']; runpy.run_path('controller/test_studio_ea_init_rules.py', run_name='__main__')"
    & 'C:\GOAT\python313-3.13.16\python.exe' -c $code *> $null; if ($LASTEXITCODE -ne 0) { Refuse 'test_studio_ea_init_rules failed (run remap-init-rules.cjs)' }
  } finally { Pop-Location }
} else { Refuse "unknown remote $remote" }

$issue = ((Get-Content 'G:\GOAT-Build-Artifacts\claude-pc-ops\state\inbox-issue.txt' | Select-Object -First 1).Trim()).TrimStart('#')
# 11-12 (goatai#2750 6831947464): every page. One page of 100 is the OLDEST 100 of the window, so on a busy day the newest Claude-Mac posts were outside it.
$raw = gh api "repos/algogoat/goatai/issues/$issue/comments?per_page=100&since=$((Get-Date).ToUniversalTime().AddHours(-6).ToString('yyyy-MM-ddTHH:mm:ssZ'))" --paginate
if ($LASTEXITCODE -ne 0 -or $null -eq $raw) { Refuse 'the inbox could not be read' }
# 10-28 (merge-gate slip 6465568246, Ops 6466025852): under 'Continue' a bad parse ends only its statement, $mac stays
# unset and .Count reads 0, so the push went ahead. Parse with -ErrorAction Stop and refuse on any failure.
try { $parsed = @(($raw | ConvertFrom-Json -ErrorAction Stop) | ForEach-Object { $_ }) } catch { Refuse "the inbox read did not parse ($($_.Exception.Message))" }
if (@($parsed | Where-Object { $null -eq $_.id -or $null -eq $_.body }).Count) { Refuse 'the inbox read has rows without id/body' }
$mac = @($parsed | Where-Object { $_.id -gt $SinceId -and ($_.body -match '^Claude-Mac' -or $_.body -cmatch 'HOLD Release') })   # a Mac post, or any post holding Release (Ops 10-27)
if ($mac.Count -gt 0) { $mac | ForEach-Object { "NEW Claude-Mac/HOLD $($_.id): $($_.body.Substring(0,[Math]::Min(300,$_.body.Length)))" }; Refuse 'read the new Claude-Mac or HOLD Release post(s) first' }

if ($DryRun) { "DRY RUN: every check passed; nothing was pushed."; exit 0 }
$args2 = @('-C', $Repo, 'push')
if ($LeaseSha) { $args2 += "--force-with-lease=${Branch}:$LeaseSha" }
if ($SetUpstream) { $args2 += '-u' }
$args2 += @('origin', $Branch)
& git @args2 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { "PUSH FAILED (git exit $LASTEXITCODE)"; exit 3 }
"PUSHED $Branch at $((git -C $Repo rev-parse --short HEAD).Trim())"
