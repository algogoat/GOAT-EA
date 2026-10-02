# GOAT agent start page: the golden path

You are helping one person run GOAT on their own Windows PC: optimize GOAT strategy templates on their own MT5 **demo** account, collect the exports and record every result. This page is the exact procedure from a fresh install to one finished batch. Read [GOAT-OPERATING-MODEL.md](GOAT-OPERATING-MODEL.md) once for the rules and the feedback loop. Never assume another person's paths, account, broker or results exist here.

## How to run commands (Claude Code on Windows and every other agent)

- Use **PowerShell only**. Do not use Git Bash or WSL for GOAT work: GOAT inspects every running Windows process before it touches MT5.
- Never use `Read-Host` or anything interactive. When you need a value or a click, ask the user in chat and wait.
- Each PowerShell call starts fresh. Begin **every** call with `. "<work folder>\goat.ps1"` (step 0).
- Studio prints `{"ok":true,"result":...}` or `{"ok":false,"error":"...","recovery":"..."}` (exit code 2). Desktop methods return `{ok:true,data}` or `{ok:false,error}`. Quote any error to the user word for word.
- Never delete, edit or "reset" receipts, the controller state folder, `MQL5\Files\GOATStudio`, queues or result files. Never kill MT5.

## What the human does first

1. Installs GOAT desktop, opens it and signs in with their own GOAT account (beta access is granted by GOAT, not by you).
2. Has their broker's MT5 with a **demo** account and has opened it once. GOAT's own research uses Darwinex demo accounts; any suitable demo broker is fine.
3. Clicks **Copy setup instructions** (sign-in screen or Get started), or after a terminal is installed **Copy instructions for my agent**, and pastes it to you. It contains the real `goat.exe` path (inside the GOAT app folder at `resources\goat-suite\goat.exe`) and, for the second button, the receipt path.

Later you will ask them, one thing at a time, to: sign in to the demo in MT5, turn Algo Trading off, close MT5, approve DLL imports and the WebRequest URL, read you the pairing code, click Approve, click GIVE TO AGENT, and say yes to your batch plan.

## Step 0: work folder and goat.ps1 (once)

Create `%LOCALAPPDATA%\GOAT Agent Work\<name>` and write this file into it as `goat.ps1`. Fill in `$goat` now and `$receipt` in step 3.

```powershell
# goat.ps1 - dot-source at the start of EVERY PowerShell call: . "<work folder>\goat.ps1"
$goat    = 'C:\FILL\resources\goat-suite\goat.exe'
$receipt = 'C:\FILL\installation.json'
$work    = $PSScriptRoot
$logs    = Join-Path $work 'logs'; [void](New-Item -ItemType Directory -Force -Path $logs)
$utf8    = New-Object System.Text.UTF8Encoding($false)
function Save-Json([string]$Name, $Value) {
  $p = Join-Path $work $Name; [IO.File]::WriteAllText($p, (ConvertTo-Json -InputObject $Value -Depth 60), $utf8); $p }
function Keep([string]$Label, [string]$Text, [switch]$NoHistory) {
  $s = $Label -replace '[^A-Za-z0-9_.-]', '_'
  if (-not $NoHistory) { [IO.File]::WriteAllText((Join-Path $logs ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + "-$s.json")), $Text, $utf8) }
  [IO.File]::WriteAllText((Join-Path $logs "last-$s.json"), $Text, $utf8) }
function Last([string]$Label) {   # re-read the last reply of an operation in a later call
  $o = Get-Content -Raw -LiteralPath (Join-Path $logs "last-$Label.json") | ConvertFrom-Json
  if ($o.jsonrpc) { $o.result } else { $o } }
function Studio([string[]]$A, [switch]$NoHistory) {   # Studio @('batch-status','--batch-id','pilot-1')
  $text = (& $goat studio --installation $receipt @A) -join "`n"; $code = $LASTEXITCODE
  Keep $A[0] $text -NoHistory:$NoHistory
  if (-not $text) { throw "goat.exe studio $($A[0]) printed nothing (exit $code); report the error shown above" }
  $r = $text | ConvertFrom-Json
  if (-not $r.ok) { Write-Warning "studio $($A[0]) refused (exit $code): $($r.error)" }; $r }
function Desktop([string]$Method, [hashtable]$Params = @{}, [string]$RequestId = '') {
  if (-not $RequestId) { $RequestId = [guid]::NewGuid().ToString() }   # same id ONLY when the outcome is unknown (timeout/interrupted); after a clear refusal, fix the cause and use a NEW id (refusals are cached per id)
  $file = Save-Json "params-$Method.json" $Params
  $text = (& $goat desktop $Method --params $file --request-id $RequestId --timeout-ms 600000) -join "`n"
  Keep $Method $text
  if (-not $text) { throw "goat.exe desktop $Method failed (exit $LASTEXITCODE); is GOAT desktop open?" }
  $r = ($text | ConvertFrom-Json).result
  if (-not $r.ok) { Write-Warning "desktop $Method refused: $($r.error)" }; $r }
function Wait-Batch([string]$BatchId, [int]$MaxMinutes = 110) {
  $end = (Get-Date).AddMinutes($MaxMinutes); $fails = 0
  while ((Get-Date) -lt $end) {
    $r = Studio @('batch-status', '--batch-id', $BatchId) -NoHistory
    if (-not $r.ok) { $fails++; if ($fails -ge 5) { return 'STOPPED: batch-status keeps refusing; see the warning' } }
    else { $fails = 0; $n = $r.result.native.native
      "{0:HH:mm} job={1} native={2} finished={3}/{4}" -f (Get-Date), $r.result.status, $n.status, $n.finished_count, $n.member_count
      if ($n.status -in @('native_completed', 'native_cancelled', 'native_error')) { return 'NATIVE QUEUE FINISHED: run finish' } }
    $low = @((Studio @('resource-profile') -NoHistory).result.disks | Where-Object { $_.free_bytes -ne $null -and $_.free_bytes -lt 5GB })
    if ($low.Count) { return 'DISK BELOW 5 GiB: cancel the batch now' }
    Start-Sleep -Seconds 60 }
  'STILL RUNNING: run Wait-Batch again' }
function Start-Batch([string]$BatchId, [int]$MaxSeconds = 0) {   # bounded driver in its own process; no -MaxSeconds = resume
  $a = @('studio', '--installation', "`"$receipt`"", 'run-batch', '--job-id', $BatchId)
  if ($MaxSeconds -gt 0) { $a += @('--max-seconds', "$MaxSeconds") } else { $a += '--resume' }
  $log = Join-Path $logs ("driver-$BatchId-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
  $p = Start-Process -FilePath $goat -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  "driver pid $($p.Id); log $log" }
```

Check it: `. "<work>\goat.ps1"; Desktop 'app.info'`. Long-running commands (`serve` up to 1 hour, `Wait-Batch`, `seed-start`/`seed-resume` up to 1 hour): in Claude Code use the PowerShell tool with `run_in_background: true` (you are re-invoked when it exits); otherwise use `Start-Process` as in step 11.

## Steps 1-4: account link, terminal, receipt

1. `Desktop 'onboarding.status'`; follow `data.steps` / `data.nextStep`. Sign-in, beta access and the published release are for the user and GOAT.
2. Ask for the demo **login number** (never a password): `Desktop 'onboarding.accounts' @{operation='add'; accountId='<login>'} -RequestId 'link-<login>'`.
3. `Desktop 'suite.discover'` and show the terminals; the user picks one. With `$sel = @{terminalExecutable='<exe>'; terminalDataRoot='<data folder>'; portable=$false}` run `Desktop 'suite.validate' $sel`, then `Desktop 'suite.install' $sel -RequestId 'install-1'`. Put `data.receipt_path` into `$receipt` in goat.ps1. (Already installed? `Desktop 'suite.status'` lists `data.installations[].receipt_path`.)
4. `Studio @('discover')`. Note `result.installation.ea_relative_path` and `terminal_data_root`.

## Steps 5-8: the monitor chart (order matters)

5. Ask the user to open the selected MT5, sign in to the demo account, turn **Algo Trading off**, then close MT5 normally (File > Exit). Also close MetaEditor and every other MT5 (to keep one running, see "Keep another MT5 running"). Ask for the server name exactly as MT5 shows it; after MT5 is closed you can confirm `Login=` and `Server=` in `<terminal_data_root>\config\common.ini`.
6. `Studio @('bootstrap','--account-login','<login>','--account-server','<server>')`
7. Ask for one exact broker symbol from Market Watch (with any suffix), then `Studio @('monitor-prepare','--symbol','<symbol>')`.
8. `Studio @('monitor-launch','--attempt-id','monitor-1')`. It opens MT5 with the GOAT Studio chart **once**. Do not run it again: once the user approves DLL imports, MT5 saves new chart permissions and another launch is refused. From now on the user opens MT5 normally (it shows the `GOAT-Studio-...` chart profile).

## Steps 9-12: approvals, pairing, control

9. Ask the user, in MT5: allow DLL imports in the GOAT EA's properties dialog; add `https://goatedge.ai` under Tools > Options > Expert Advisors > Allow WebRequest for listed URL; keep Algo Trading off.
10. The EA shows "Enter pairing code: ...". Ask the user to read it to you, then `Desktop 'onboarding.preparePairing' @{userCode='<code>'}`. Ask them to check the account and build in GOAT desktop and click **Approve this connection**. You cannot approve it.
11. Start `serve` in the background: Claude Code: `. "<work>\goat.ps1"; & $goat studio --installation $receipt serve --watch-seconds 3600` with `run_in_background: true`. Others: `Start-Process -FilePath $goat -ArgumentList @('studio','--installation',"""$receipt""",'serve','--watch-seconds','3600') -WindowStyle Hidden`. It stops after at most 3600 s; restart it whenever the user needs to click in Studio.
12. Ask the user to click **GIVE TO AGENT** in the Studio panel on the GOAT chart. Repeat `Studio @('onboarding-status')` until `result.status` is `local_monitor_ready` (otherwise do its `next_action`), and `Desktop 'onboarding.status' @{receiptPath=$receipt}` until `data.ready` is true. If a step reports `ACTIVATION_RELOAD_REQUIRED`, ask the user to change the chart timeframe once.

## Steps 13-16: plan and prepare one small batch

13. `Desktop 'strategy.status'`; if there is no `activeRevision`, `Desktop 'strategy.importBundled' -RequestId 'catalog-1'`. Then `Desktop 'strategy.matrix'` and pick candidates in the order the operating model gives (proven first, then exploration). Agree with the user: for the first batch, 1 template on 1 symbol; dates; deposit, currency and leverage; time and disk budget.
14. `Desktop 'strategy.freezeSelection' @{selectionId='sel-1'; templateIds=@('<template id>')} -RequestId 'sel-1'`
15. Write the plan and its lineage, then prepare (the values are examples; use the agreed ones):

```powershell
. "<work>\goat.ps1"; $id = 'pilot-1'; $sel = (Last 'strategy.freezeSelection').data; $tpl = $sel.templates[0]
$tester = @{Expert=(Last 'discover').result.installation.ea_relative_path; Symbol='EURUSD'; Period='H1'; Model=1; ExecutionMode=0
  Optimization=2; OptimizationCriterion=6; FromDate='2023.01.01'; ToDate='2025.01.01'; ForwardMode=4; ForwardDate='2024.07.01'
  Deposit=10000; Currency='USD'; Leverage='1:100'; UseLocal=1; UseRemote=0; UseCloud=0; Visual=0}
$export = @{SetsToExport=2; MinScore=60; TargetDD=100; AdjustLots=$false; BackOOSDate='2022.01.01'; MinARF=0.2; MinSR=2.5; IncludeBackOOS=$true; IncludeSequenceData=$true}
$plan = Save-Json "plan-$id.json" @{schema_version=1; export=$export; members=@(@{set_path=$tpl.filePath; tester=$tester})}
[void](Save-Json "lineage-$id.json" @(@{index=0; templateId=$tpl.id; templateRevision=$tpl.revision; templateSha256=$tpl.sha256; catalogRevision=$sel.catalogRevision}))
Studio @('prepare-batch','--batch-id',$id,'--plan',$plan)
```

The controller enforces: 1 to 10,000 members; all 18 tester fields; `Optimization=2` (genetic), `OptimizationCriterion=6` (custom), `ForwardMode=4`, local workers only, `Model` 0/1/2/4 (use `1`, 1-minute OHLC, unless the user chooses otherwise); `BackOOSDate < FromDate < ForwardDate < ToDate` (BOOS = the "back out-of-sample" period before the optimization window); `SetsToExport >= 2`, `MinScore >= 60`, `TargetDD >= 100`, `MinARF >= 0.2`, `MinSR >= 2.5`; one export policy and forward date per batch; every SET must have at least one optimization axis. Members run in the order listed. A batch ID can never be reused for different inputs.

16. `Studio @('batch-status','--batch-id','pilot-1')`. Show the user every member and the settings and get an explicit "yes, start".

## Steps 17-19: start once, watch, finish

17. Check first: every `result.disks[].free_bytes` from `Studio @('resource-profile')` is at least 5 GiB; `onboarding-status` is `local_monitor_ready`; only the selected MT5 is running, plus the one peer you protected with `peer-apply` (see "Keep another MT5 running"), if any. Then start the **bounded driver once** with the agreed budget in seconds: `Start-Batch 'pilot-1' -MaxSeconds 14400`. It starts the batch, refuses when an output disk is below 5 GiB, cancels by itself when the budget runs out, and keeps a journal that survives restarts. `Studio @('batch-driver-status','--job-id','pilot-1')` shows its view.
    - Never call `start`, or `Start-Batch` with `-MaxSeconds`, again for a batch that started. If the driver process is gone (PC restart, closed shell), `Start-Batch 'pilot-1'` without `-MaxSeconds` resumes it against its original deadline.
    - If the driver reports `start_uncertain` with no `attempt_id`, the start was refused before anything reached MT5: fix the cause it names, then run the same `Start-Batch 'pilot-1' -MaxSeconds ...` again. The controller allows that retry only when nothing was dispatched.
18. Run `Wait-Batch 'pilot-1'` in the background and tell the user the progress lines. To stop: `Studio @('cancel','--job-id','pilot-1')`, then keep polling; a cancel request is not proof that MT5 stopped.
19. On `NATIVE QUEUE FINISHED`: `Studio @('finish','--job-id','pilot-1')`. If it refuses with a runtime or tester-idle error, wait a minute and repeat. `finish` is safe to repeat.

## Step 20: results go into the matrix

The finish reply holds `result.result.member_outcomes`, the frozen `configuration.batch_members` and `reports` (one member: the object itself; several: `reports.members[i]`). Each completed member's `exports` has `native_threshold_candidate_count` and `files[]` (status `native_threshold_candidate` or `below_native_thresholds`, with SET and CSV paths). Record **every** member:

```powershell
. "<work>\goat.ps1"; $id = 'pilot-1'; $fin = (Studio @('finish','--job-id',$id)).result; $res = $fin.result
$cfg = (Studio @('batch-status','--batch-id',$id)).result.members; $lin = (Get-Content -Raw "$work\lineage-$id.json" | ConvertFrom-Json)
$state = (Studio @('state')).result; $path = $fin.result_path; if (-not $path) { $path = ($state.queue | Where-Object job_id -eq $id).completion_path }
$sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
foreach ($m in $res.member_outcomes) { $i = $m.index; $t = $res.configuration.batch_members[$i].tester; $L = $lin[$i]
  $rep = if ($res.reports.members) { $res.reports.members[$i] } else { $res.reports }; $n = $rep.exports.native_threshold_candidate_count
  $status = @{native_completed='completed'; native_error='failed'}[$m.status]; if (-not $status) { $status = 'interrupted' }
  if ($status -eq 'completed' -and $rep.exports.status -eq 'export_inventory_observed' -and $n -eq 0) { $status = 'no-qualifying-exports' }
  $att = "$($res.attempt_id)-m$i"
  Desktop 'strategy.recordResult' @{result=@{runId=$state.run_id; attemptId=$att; templateId=$L.templateId; templateRevision=$L.templateRevision
    templateSha256=$L.templateSha256; catalogRevision=$L.catalogRevision; status=$status; observedAt=(Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    conditions=@{eaVersion=$res.ea_version; controllerVersion=$res.controller_version; broker='unavailable'; server=$res.account_server; symbol=$t.Symbol
      timeframe=$t.Period; from=$t.FromDate; to=$t.ToDate; forward=$t.ForwardDate; testerModel=[string]$t.Model; deposit=[double]$t.Deposit
      currency=$t.Currency; sizing='unavailable'; costs='unavailable'; effectiveSettingsSha256=$cfg[$i].configuration_sha256}
    metrics=@{nativeThresholdCandidates=$n}; qualityGates=@{}; artifacts=@(@{name='native-result.json'; sha256=$sha})
    summary='<one or two sentences: what ran, what qualified, limits>'}} -RequestId "rec-$att" }
```

Replace `unavailable` with real facts when known. Then `Studio @('benchmark-report','--batch-id','pilot-1')` gives the measured timing; use it to size the next batch with the user. A `failed` or `interrupted` result is a technical outcome, not evidence that the strategy is bad. To build a portfolio, import the export folders with `library.prepareImport` / `library.finalizeImport` as described in the installed `goat-beta-agent-guide.md` (sections 7 and 8).

## Seed loop (find candidates before spending full batches)

Seed farming runs fast in-sample searches with no forward window and no exports. Its real-MT5 close/relaunch cycle is **not yet qualified** (`native_launch_qualified: false`): start with a tiny run the user approved. Needs: monitor ready, GIVE TO AGENT done, no unfinished batch.

1. Plan file: `{schema_version:1, max_attempts_per_job:1, job_timeout_seconds:<30..86400>, cutoff:{min_fitness:<number>, min_trades:<whole number, 0 or more>}, jobs:[{set_path, tester, frame_target:<1..1000000>}]}` with 1 to 10,000 jobs. Each `tester` is the step-15 object with `ForwardMode=0` and `ForwardDate=''`. Save lineage per job index as in step 15.
2. `Studio @('seed-prepare','--batch-id','seed-1','--plan',$planPath)`. Tell the user GOAT will close their MT5 and restart it for each job.
3. `Studio @('seed-start','--batch-id','seed-1','--max-seconds','3600')` (1..3600, default 60; background), then `seed-resume` with the same arguments until `result.status` is `completed`, `stopped` or `reconcile_required`. `driver_budget_exhausted: true` only means "call seed-resume again". Stop with `seed-cancel`, then `seed-status` until stopped.
4. `Studio @('seed-report','--batch-id','seed-1')`. A member **qualifies** when `summary.qualifying_count >= 1` (rows meeting both cutoffs). Missing output has `actual_frames: null`, which is not zero.
5. Record every member with `strategy.recordResult` as in step 20, but: `attemptId = "seed-1-<alias>"`; map seed status `completed` to `completed`, `failed`/`missing_output` to `failed`, `cancelled`/`timeout`/`pending` to `interrupted`, `reconcile_required` to `unknown`; `forward=$null`; `effectiveSettingsSha256 = config_sha256`; `metrics=@{seedQualifyingCount; seedBestFitness; seedActualFrames}`; `qualityGates=@{seedCutoffMet=(qualifying_count -ge 1)}`; artifact = `report_path` with `report_sha256`; say "seed search, in-sample only" in the summary.
6. Promote the best candidates. Pick a candidate from the member's `result_path` (highest `metrics.Result` among `qualifies: true`), then `Studio @('seed-promote','--batch-id','seed-1','--candidate','<candidate_sha256>','--name','<plain name>','--member','<member alias>')` (demo lane: `& $goat demo ... seed-promote` with the same arguments). It writes `fixed.set` (exact values) and `robustness.set` (each optimized input one ladder step either side, `--neighborhood 1..5`), both with your plain name, and returns their paths and hashes (`status: written`, or `retained` on a repeat). The robustness SET is a local stability check around the candidate; only the forward window is out-of-sample. Run it in an ordinary batch (steps 15-19) on dates after `seed_window.to_date`, with a forward window, and judge it on the forward result. A seed result alone is in-sample evidence only. If it refuses with `Incomplete promotion folder`, tell the user; do not delete the folder yourself.
7. Order the next ordinary batch: promoted discoveries and qualifying template/symbol pairs first, then exploration (see the operating model).
8. After seeds MT5 is closed. Ask the user to open it normally with the GOAT Studio chart and run `onboarding-status` before the next batch.

Not in this beta: automatic recording of seed or batch results, automatic ordering of the next batch, a background seed driver. You do these steps. Details: [SEED-WORKFLOW.md](SEED-WORKFLOW.md).

## Several MT5 terminals on one PC

Terminals are independent. With the SM32 EA (V1.49 terminal isolation), every terminal and
account keeps its own batch state in `Common\Files\GOAT\GOAT V1.49-<server>-<login>-<hash>`
and its own GOAT sign-in in `GOAT\Credentials\api-bearer-v149-<login>.token`. A batch or seed
on one terminal never reads or changes another terminal's queue, pointer, config or sign-in,
even when both use the same EA, server and account. Do not copy these files between terminals.
The first time the updated EA chart loads, it moves this terminal's shared pre-isolation files
into its own folder and writes `terminal-isolation.ini`; a batch that another terminal ran is
left where it is. Only one terminal can take the old shared state (a claim file decides), so load
the updated EA on the terminal that ran it first; a copied terminal must come second. Older EA
builds still share the old folder, so update every terminal on the PC before running batches on
more than one. Details: [INVARIANTS.md](../docs/operations/INVARIANTS.md).

## Keep another MT5 running

Only the selected MT5 and at most **one** reviewed peer may run during GOAT work. With that peer running and no batch active: `Studio @('peer-prepare','--terminal-executable','<its terminal64.exe>','--data-root','<its data folder>')`. Show the user the returned paths and PID. With their yes, within 10 minutes: `Studio @('peer-apply','--review-id','<review_id>','--confirm-reviewed')`. If the peer restarts, repeat the review.

## If stuck

Report the exact error text, the command and the IDs. Never delete state to get past an error.

| Error text (exact start) | Next safe action |
|---|---|
| `Human must Give to Agent in Studio first` / `Current controller required: human must Give to Agent first` | Make sure `serve` runs; ask the user to click GIVE TO AGENT; check `Studio @('state')` shows `owner: agent`. |
| `Runtime feedback is stale or future-dated` | The GOAT chart is not reporting. Ask the user to open MT5 normally with the GOAT Studio chart; run `onboarding-status`. |
| `Runtime policy mismatch: terminal_trade_allowed` | Algo Trading is on. Ask the user to turn it off. |
| `Runtime policy mismatch: account_demo` / `Runtime account mismatch` | Not the bound demo account. Stop and ask the user to sign in to the demo used in `bootstrap`. |
| `Runtime policy mismatch: connected` | MT5 lost its broker connection. Ask the user to reconnect. |
| `Tester idleness not confirmed: ...` | The MT5 tester is busy. Wait and retry; never press Stop for the user. |
| `Unmapped terminal process requires ownership inspection` | Another MT5 is running. Ask the user to close it, or protect it (section above). |
| `Executable is running under a stopped terminal root` | The selected MT5, MetaEditor or a tester agent from that folder is still running. Ask the user to close it. |
| `Human must turn Algo Trading off and close the selected terminal normally before monitor launch` | Step 5 is incomplete. Ask the user to do it, then retry `monitor-launch` with the same ID. |
| `Saved broker login/server differs; ...` | Login/server in MT5 differs from `bootstrap`. Ask the user to sign in to that demo, Algo off, close MT5. |
| `Saved monitor symbol, EA identity or permissions changed; ...` | Expected after the first launch. Do not relaunch; ask the user to open MT5 normally. |
| `Unresolved monitor launch intent; ...` | Stop. Report the `monitor-launches` record to support. |
| `Monitor and controller revision/generation/owner differ; run serve and recheck` / `Monitor has not loaded controller state` | Start `serve`, wait a minute, rerun `onboarding-status`. |
| `Native queue is not finished; reconcile, do not reset` | Keep polling `batch-status`; run `finish` only after the native queue finishes. |
| `Only pending job can start; reconcile existing attempt` | It already started. Never start again; poll `batch-status`. |
| `Batch ID already belongs to different members/settings; ...` / `Unqueued preparation artifacts exist; ...` / `Prior batch request retained; ...` | Use a new batch ID. Keep the old files. |
| `Unresolved native batch must finish before seed workflow` | Finish the current batch first. |
| `Fresh loaded licensed Studio dialog and matching human grant required` | Monitor not ready or GIVE TO AGENT missing: redo step 12. |
| `Existing Studio activation requires reconciliation; ...` / `Installation changed since bootstrap; ...` | Stop. Do not re-bootstrap. Prepare a support report. |
| `Desktop discovery unavailable. Start GOAT or select its data directory.` | Ask the user to open GOAT desktop. |
| seed status `reconcile_required` | Stop. Do not start or cancel again; report it with `seed-status` output. |
| `The GOAT EA running on this terminal predates terminal isolation. ...` | The chart still runs the old EA. Ask the user to remove and re-add the GOAT Studio chart (or restart MT5) so the installed EA loads, then retry. |
| `The GOAT EA on this terminal uses batch folder ..., but this controller expects ...` | The terminal is signed in to a different account or folder than `bootstrap`. Ask the user to sign in to the bound demo account. |
| `Another running MT5 terminal (...) resolves to this terminal's batch folder ...` | Two MT5 processes share this terminal's data folder. Ask the user to close the named one. |
| `A running MT5 terminal (PID ...) cannot be matched to a data folder, ...` | GOAT cannot see which folder that MT5 uses (often another Windows user or an elevated MT5). Ask the user to close it, or start it normally as this user. |
| `Batch state move stopped: the shared folder ... is claimed by another MT5 terminal ...` | Stop. Another terminal owns the old shared state; this terminal keeps its own folder. Report both folder listings to support. |
| `Batch state was not moved: both the shared folder ... and this terminal's folder ... hold batch state. ...` | Stop. Never delete either folder. Report both folder listings to support; a human chooses which to keep. |
| `Batch state was not moved: the shared folder ... still holds controls of an unfinished attempt from this controller. ...` | Run `status`/`finish` for that attempt first, then retry. |

To report a product problem: `Desktop 'support.prepareReport' @{category='studio'; summary='...'; reproduction='...'; expected='...'; actual='...'; errorCodes=@()}`, show the user the returned preview, and only after their yes send it with `support.submitReport` (`reportId`, `previewSha256`, `reviewed=$true`).
