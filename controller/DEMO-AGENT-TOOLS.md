# Demo agent tools (owner and maintainer lane)

**Customers and their agents: do not use these tools.** Follow [AGENT-START-HERE.md](AGENT-START-HERE.md) (`goat.exe studio ...`) and [GOAT-OPERATING-MODEL.md](GOAT-OPERATING-MODEL.md). This lane exists for GOAT's own demo research and for reviewed build installs; its commands refuse to drive Studio until `install-build` has converted the selected session to this lane.

`demo_agent.py` (installed as `goat.exe demo --installation <receipt> <command>`) operates one selected MT5 installation from its existing `installation.json`. It never sends trades or turns on Algo Trading. It drives the EA's existing Studio queue and optimizer; there is no second tester or portfolio engine.

The account is the demo login and server already paired in that installation's controller session (from `bootstrap`); there is no built-in account. Every command that can change the terminal or its files requires a fresh broker-reported demo account matching that pairing, the selected process, Algo Trading off, an idle native tester, at least 5 GiB free on the terminal-data, Common Files and controller-state volumes, and no owner STOP or pending human TAKE CONTROL. A real account always refuses. `demo-agent/actions.jsonl` records intent and readback events.

Output: success prints `{"ok":true,"result":...}` to stdout (exit 0). Errors print `{"ok":false,"code":"REFUSED"|"IO_ERROR"|"INTERNAL_ERROR","error":"..."}` to stderr (exit 1). `stop` that cannot confirm the stop prints `code: STOP_UNCONFIRMED` (exit 2).

```powershell
& $goat demo --installation $receipt status          # process, broker, EA hash, owner feedback age, driver journals
& $goat demo --installation $receipt disk-status     # free bytes against the 5 GiB reserve
& $goat demo --installation $receipt preflight       # read-only; reports ready_for_install and ready_for_batch
& $goat demo --installation $receipt install-build --candidate '<reviewed .ex5>' --sha256 '<64 hex>' --monitor-config '<existing monitor-only .ini>'
& $goat demo --installation $receipt launch-terminal --monitor-config '<existing monitor-only .ini>'
& $goat demo --installation $receipt prepare-batch --batch-id '<new id>' --plan '<plan.json>'
& $goat demo --installation $receipt run-batch --batch-id '<id>' --max-seconds 172800
& $goat demo --installation $receipt resume-batch --batch-id '<id>'
& $goat demo --installation $receipt batch-status --batch-id '<id>'
& $goat demo --installation $receipt batch-driver-status --batch-id '<id>'
& $goat demo --installation $receipt stop            # optional: --monitor-config '<monitor-only .ini>'
& $goat demo --installation $receipt clear-stop
& $goat demo --installation $receipt recover-orphan  # optional: --review-id '<id>' to observe only
& $goat demo --installation $receipt research-status # read-only lane: activity, pace/ETA, pause, driver, disk, monitor
& $goat demo --installation $receipt batch-pause --batch-id '<id>'    # optional: --immediate
& $goat demo --installation $receipt batch-resume --batch-id '<id>'   # optional: --new-batch-id, --resume-token, --max-seconds, --clear-stop, --include-failed
& $goat demo --installation $receipt compact-evidence   # preview; --apply moves finished in-row evidence history to verified logs
& $goat demo --installation $receipt compact-receipts   # preview; --apply archives legacy full-queue receipts and keeps their queue digest
```

- `compact-evidence` and `compact-receipts` are local store maintenance with no native effect. Each previews by default and, with `--apply`, refuses while any batch is starting or running (checked before any archive and again inside each transaction). Archives are temp-written, fsynced, sha256-verified and atomically renamed, and are never deleted. Run `compact-evidence --apply` first, then `compact-receipts --apply`. Neither shrinks `studio.sqlite` on disk: that needs a separate reviewed `VACUUM`. Both change the store's content hash, so prepare a handover or owner-maintenance record after compacting, not before.

- `install-build` verifies the candidate hash and the inert monitor INI (only Charts/Experts/StartUp monitor keys; account, tester and script directives refuse before MT5 closes), archives the old EX5 and identity files, closes only the selected idle demo terminal, copies the EX5, relaunches its monitor and reads back the physical hash, demo account, EA feedback and Algo-off state within 120 seconds. Repeating it with the same candidate and hash returns `already_installed` or completes an interrupted swap; an uncertain relaunch never dispatches a batch.
- `launch-terminal` reopens a stopped registered demo terminal with its exact monitor INI and requires fresh broker, Algo-off, idle-tester and EA feedback afterwards.
- `run-batch` (`--max-seconds` required, 1..172800) starts a detached Windows worker and returns when its journal exists; that is not proof that native work runs. Repeating it returns the original worker and never resets the deadline. `resume-batch` attaches a new worker to the retained attempt and original deadline and never starts a pending job.
- `stop` writes the owner STOP marker and waits for the exact cancellation readback; it returns `cancelled`, another verified terminal result or `stop_unconfirmed`. `clear-stop` removes only a STOP written by this tool, after a verified idle demo and a terminal batch state.
- Treat `start_uncertain` or `stop_unconfirmed` as "inspect the native state", never as completion. A `stop_unconfirmed` batch is settled with `batch-pause`, which adopts its outstanding stop.

## Research operations: status, pause and resume

`research-status` is one read-only call per installation, built for a UI lane or
an agent loop. It never takes the terminal lock, opens the mutable store,
launches, closes or signals MT5. It returns the terminal (process, build), the
paired account, the EA build, the current batch or seed hunt (`status`,
`members_done`/`members_total`, `qualifying` = completed members with at least
one exported SET that passed the batch's export gates, `last_member`,
`current_member`, `pace.minutes_per_member`, `pace.eta_utc`, `lineage`,
`pause`, a one-sentence `headline`), driver health (`unsupervised` when a running
batch has no live driver), disk headroom against the driver's reserve, owner
STOP, and the monitor: `ticking`, `relaunching` (an ordinary member-boundary
restart), or a `blocker` with `code`, `message` and `fix`. Codes include
`terminal_closed`, `monitor_unlicensed` (the EA's sign-in status is newer than
its last heartbeat; when another terminal's sign-in was approved after it, the
message is "This terminal's GOAT sign-in was replaced by another terminal —
re-pair it."), `monitor_build_not_admitted`, `monitor_webrequest_permission_required`,
`monitor_unbound`, `human_took_control` and `monitor_silent`.

A member whose optimization ran (at least one pass traded) and whose back and forward
reports are whole, but had no pass profitable with 50+ trades, is a research result for its
tested window, not a failure. A report whose EA never traded, that cannot be read, or that is
partial stays a real error and `--include-failed` retries it. The EA keeps its native
queue status `Error` (no protocol change) and writes a `NoProfitablePasses` row to
the run's `item_stats.tsv` (passes, profitable count, best profit, best score and
the back-test window). `research-status` reports these as `members_no_edge` (with
`no_edge` details and `no_edge_window`) apart from `members_failed`; the headline
says `N tested with no edge in <window>`, and `last_member.status` is
`no_profitable_passes` with a one-line `summary`. `finish` records them as
`research_outcomes` for the scoreboard, a pause whose only errors are no-edge members
is `finished`, and `--include-failed` never re-runs them; `--include-no-edge` (`batch-resume`,
or `resume-batch` for a batch already recorded finished) deliberately re-runs them. Always quote the window:
"no profitable settings in this window" never means "this strategy never works".

`batch-pause` needs no terminal lock (like `stop`): it writes one durable pause
intent (`batch-pauses/<id>.json`) and returns `state: pausing`. A live driver
honours it on its next tick; otherwise one bounded pause supervisor starts
(`_drive-batch ... --pause-seconds 21600`, its own Windows demand task). The
safety rules, in `studio_batch_pause.py`:

- One stop is published only at a safe point while the bound monitor reports:
  within the first 5 minutes of a member that just turned OnGoing (never inside
  its last 3 minutes once the pace is known), or with no member active and the
  tester idle after the between-member relaunch. Owner STOP, a pending human
  TAKE, low disk, a clock rollback or the driver deadline drop the member-age
  rule, never the reporting-monitor rule.
- An expired, unconsumed stop is never replaced while unanswered. The EA answers
  it with `CANCEL_REJECTED` on its first bound tick; only that exact receipt,
  observed after expiry, admits exactly one successor identity, linked first in
  `cancel-successors/<attempt>.json` under the `cancel-rejected-successor`
  identity rules, so `finish` binds it. Both stop receipts are kept. A rejection
  observed before expiry (an identity check), a rejected successor or any other
  refusal ends in `pause_failed` with one sentence and its fix.
- The driver never records `cancel_issued` for a pause, so its journal is never
  poisoned. It keeps the disk guard and finish throughout, and a resumed driver
  keeps supervising. A journal an owner STOP left at `stop_unconfirmed` is
  adopted: its outstanding stop becomes the pause's (`adopted_stop: true`).
- After MT5 confirms, finish harvests the completed members and the pause records
  `paused` with `resume_token`; a batch that completed every member first records
  `finished`. A failed pause hands the batch back to normal supervision.

`batch-resume` refuses in plain words while the batch is still pausing, failed,
finished, its monitor has a blocker, or an owner STOP is set (pass `--clear-stop`
to lift a STOP written by this tool). Otherwise it re-verifies the paused result
and token, refreshes `verified-build.json` after a terminal restart, refreshes the
protected peer when only its process instance restarted (same reviewed executable
bytes, data root and origin; anything else still needs `peer-prepare`/`peer-apply`),
builds the remaining members from per-member native evidence, prepares them as a
successor (`<id>-rN`, fixed in the pause record before preparation so a retry
reuses it), records `batch-lineage/<successor>.json`, and starts the successor
under the bounded driver with the original budget (or `--max-seconds`). Repeating
it returns the same successor.

A seed hunt pauses between members: `batch-pause` writes `seeds/<id>/pause.json`,
the running member finishes and is kept, no new member starts and pending members
stay pending (never cancelled). `seed-resume` honours the pause; `batch-resume`
releases it (the marker is retained as `pause-released-<ms>.json`) and continues.

## Gate calibration: qualification gates from our own evidence

The export gates (`MinScore 60`, `MinSR 2.5`, `MinARF 0.2`, `SetsToExport 2`,
`TargetDD 100`) and the EA back-row filter (in-sample profit > 0.001, >= 50
trades) were fixed by hand. `gate-recommend` replaces "fixed" with "chosen per run
from what our past exports actually did". It is read only: it opens the export
folders under Common Files for reading and writes nothing except `--output`. It
needs no terminal, lock, session or broker; `--installation` is accepted as for
every command and not read.

```powershell
& $py $tool --installation $install gate-recommend --target forward --min-survival 0.8
& $py $tool --installation $install gate-recommend --target post --min-survival 0.75 --runs 'Rad870a22d237,Re7e282f93d41' --output 'C:/gates/rec.json'
& $py $tool --installation $install gate-recommend --target held_up --verdicts 'C:/catchup/verdicts' --output 'C:/gates/held.json'
& $py $tool --installation $install gate-stamp --plan 'C:/plan.json' --recommendation 'C:/gates/held.json' --output 'C:/plan-gated.json'
```

How it decides (`studio_gate_calibration.py`, schema `goat-gate-calibration-v2`):

- Every finished sequence capture in `<run>/deploy` and `<run>/exports` is split by
  server date into back OOS `[BackOOSDate, FromDate)`, in-sample `[FromDate,
  ForwardDate)`, forward `[ForwardDate, ToDate)` and post `[ToDate, end of the
  export run]`, from `deals.csv` (trades = positions opened in the window; PF over
  only those positions, as in `goat-catchup-verdict-v2`) and the exported equity
  CSV (net, drawdown, recovery, daily Sharpe, monthly ARF-style ratio). The
  optimizer's own in-sample columns and Score come from the member's `UniqueRows`
  XML. A capture that hit its row limit keeps its equity numbers; its trades and PF
  after the cut are unknown, never partial. Only byte-identical evidence (same
  inputs AND same deals and equity files) collapses across runs.
- Survival: `forward`/`post` need at least `--min-trades` (default 5) positions in
  the window and then net > 0 (post also >= 10 weekdays); fewer trades = not
  judged. `held_up` uses catch-up verdicts matched by the exported SET's SHA-256,
  accepted only as schema `goat-catchup-verdict-v2`, `comparability.comparable`
  true and default rules (`rules.id` v2, nothing `overridden`); for one SET the
  newest evidence end wins. `too_few_trades`/`not_comparable` are not judged.
- **Only `held_up` is actionable.** Forward and post lie inside the export run the
  EA already judged, so they are diagnostics: they report what would validate but
  never move a plan field, and `gate-stamp` refuses them.
- Leakage rule: a predictor may only use data the target window could not have
  influenced. Forward: in-sample, back OOS and the optimizer's in-sample columns;
  never the forward window, the Score (built from in-sample and forward results)
  or the file-name metrics (measured over the whole export run). Post also allows
  forward and Score; held_up also allows the file-name metrics, so `MinScore`,
  `MinSR` and `MinARF` can only move on held_up; every other gate is a portfolio
  qualification gate. Plan fields never drop below the controller floors.
- Selection is paid for. Outcomes are averaged per optimization member first (a
  member's sets are near copies), and runs (`--cluster run`, or the stricter
  `period`) are the independent unit. A metric is a candidate only when survivors
  beat failures **inside the same run** (run-bootstrap AUC range above 0.5), so a
  difference between runs cannot fake a signal. A threshold is chosen (loosest,
  most sets kept) only where a **simultaneous** lower band over the whole
  threshold grid (sup-t over a run bootstrap, also capped by the member Wilson
  bound) clears `--min-survival`, with `--min-sets` sets from `--min-members`
  members in at least two runs.
- **Leave one run out:** the whole selection is repeated without each run and the
  gate it picks is judged on that run. The gate validates only when the pooled
  held-out lower bound (the lowest of a cluster t interval, Wilson and a bootstrap
  over held-out runs) clears the target, at least `--min-clusters` (default 4)
  runs were judged, and no run with enough members clearly misses (its Wilson
  upper bound under the target). The recommended threshold is the strictest one any
  fold chose for that metric. If that threshold does not clear the full-data band,
  the result is `fallback_not_validated` (fail closed); the looser full-data
  threshold is never stamped in its place.
- Status: `validated`, `defaults_already_meet_target`,
  `fallback_no_qualifying_gate`, `fallback_not_validated` or
  `fallback_thin_evidence` (fewer than `--min-sets` judged sets, `--min-members`
  members or `--min-clusters` runs). Every fallback keeps today's values and says
  why in `summary`. Symbol classes and run designs are calibrated alone with the
  same procedure and only get their own gate when they validate.
- Fillers (sets the EA exported below its run's own MinSR/MinARF to fill
  `SetsToExport`) are labelled `filler`, never excluded. `fillers` in the result
  compares passed and filler sets inside each run and symbol on held_up only
  (Mantel-Haenszel risk difference, run bootstrap); the pooled gap is confounded by
  construction.
- Simulation (`CoverageSimulationTests`): when a gate validates, its true survival
  clears the target at the nominal 97.5% one-sided rate, also with run-level shocks.
- **"Validated" is per draw, not per gate.** Across evidence draws, few validate a
  gate that really misses the target. Among the gates that do validate, a larger
  share is still slightly under it (correlated proxies, judged on fresh periods).
  `scripts/gate_calibration_coverage.py` measures both; the numbers live in
  `VALIDATED_GATE_MISS` and travel as `validation_meaning` in every recommendation,
  summary, `<plan>.gates.json` stamp and report. A miss over-tightens, never loosens.
- `evidence_digest` is a SHA-256 over the judged sets, outcomes and features, so
  the same evidence gives the same digest in any order.

`gate-stamp` writes a NEW plan (never the source, never an existing file) and
**only tightens**: it accepts only a `held_up` recommendation; each recommended
field becomes `max(plan value, recommended value)`, every other field keeps the
plan's own value, and when nothing tightens (or the recommendation is a fallback)
the plan is copied byte for byte. The new plan is validated by the same
`validate_export` as preparation; `<plan>.gates.json` holds
`gates={values (with export_applied), method, evidence_digest, generated_at,
plan_sha256, source_plan_sha256}`. The stamp is a sidecar because `prepare-batch`
accepts only `schema_version`, `export` and `members`; the plan itself stays a
normal plan. Pass `--generated-at` for a byte-identical repeat. `apply_qualify`
checks one exported set against the stamped qualification gates (a missing number
fails).

`scripts/gate_calibration_report.py --out-dir <new folder>` writes the full
evidence report (`report.md`, `report.json`) for several targets;
`scripts/test_gate_calibration_mutations.py` checks that the guards above are
each covered by a failing test.

## Seed Farming on the demo lane

On a `demo_direct` installation the raw `goat.exe studio seed-*` mutations
refuse with `Demo mutation requires the broker-verified agent tool`. Use these
tools instead. They drive the same `SeedRunner` and the same frozen plan format
as [SEED-WORKFLOW.md](SEED-WORKFLOW.md); nothing about seed evidence changes.

```powershell
& $py $tool --installation $install seed-validate --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-prepare --batch-id 'seed-weekend-01' --plan 'C:/seed-plan.json'
& $py $tool --installation $install seed-start --batch-id 'seed-weekend-01' --max-seconds 600
& $py $tool --installation $install seed-resume --batch-id 'seed-weekend-01' --max-seconds 600
& $py $tool --installation $install seed-status --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-cancel --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-report --batch-id 'seed-weekend-01'
& $py $tool --installation $install seed-promote --batch-id 'seed-weekend-01' --candidate '<candidate_sha256>' --name 'My EURUSD discovery'
```

`seed-validate` checks the whole plan and every SET it names (tester rules,
frame target, exact axis precision, duplicates, size limits) and writes nothing:
no SET, startup INI or seed folder, and no terminal, process or broker access.
Only the validation itself is appended to `actions.jsonl`.

`seed-promote` (`--neighborhood` 1..5, default 1; add `--member <alias>` when
the candidate appears in several members) writes `fixed.set` and
`robustness.set` for one verified candidate under the same checks as
`seed-report`, with no terminal effect, and appends `written`, or `retained`
when a repeat returns the existing receipt. The robustness SET is a local
stability check around the candidate; only the forward window is out-of-sample.

`seed-prepare` and `seed-start` need the same fresh checks as batches: the
terminal lock, a broker-reported demo account on the exact paired login and
server, Algo Trading off, an idle tester, no open positions or orders on a
trade-capable account, no owner STOP or pending human TAKE, 5 GiB free on every
volume, and the registered EA with its native readback. They also refuse while
any ordinary native batch is active or a live batch worker exists. While a seed
run owns the terminal, ordinary batches stay blocked by `seed-active.json`.

`seed-start` writes `demo-agent/seed-starts/<batch-id>.json` once, before any
effect: the manifest hash, generation, paired account and the broker readback.
A second `seed-start` for a started batch refuses; continue with `seed-resume`.
A seed run closes the selected MT5 and relaunches it per member, so between
members no live broker can answer. `seed-resume`, `seed-status`,
`seed-cancel` and `seed-report` then continue only that original attempt, and
only when its start record matches this installation, the registered EA and the
exact paired demo account. When MT5 is running they take a fresh broker readback
instead. Completed or attempted members are never retried. A batch that is still
`prepared` has had no native effect: `seed-status`, `seed-cancel` and
`seed-report` work on it with a fresh broker readback while MT5 runs. They keep
working after it is cancelled before any start, and a repeated cancel is
idempotent, but only while the retained files prove no native effect ever
happened: no start record, slot, generation, process, attempt, result or seed
output. Anything else without a start record refuses.

Start and resume drive in short slices of a few seconds within `--max-seconds`
(1..3600, default 60). Before every slice they check owner STOP, a pending human
TAKE and free disk. If any appears, they request a normal close of the exact
owned member, cancel the pending members and return `stopped_by` with the
reason. `stop` also settles a seed run that no command is currently driving.

Nothing supervises a member between commands. After `driver_budget_exhausted`,
the member's job timeout, a human TAKE and the disk check are only acted on by
the next `seed-resume`. `--max-seconds` is the budget for that one call, not an
autonomous hard stop, and no background service enforces anything between calls.
Owner STOP is a separate explicit path: `stop` works at any time. Keep calling
`seed-resume` until the batch reports `completed` or `stopped`, or holds
`reconcile_required` for inspection.
STOP is never cleared by these tools, and `clear-stop` refuses until the seed
run has reached a verified terminal state. Real native qualification of this
lane is still pending; every seed result keeps `native_launch_qualified: false`.

## OOS catch-up on the demo lane

Bring kept exports to one evidence end before building a portfolio (rules and
verdicts: [README.md](README.md#evidence-end-and-oos-catch-up)). The read-only
tools need no broker; the rest use the seed lane's checks, start record
(`demo-agent/catchup-starts/<id>.json`), slot, STOP, pause and slices unchanged.

```powershell
& $py $tool --installation $install evidence-end                       # auto = latest closed Friday
& $py $tool --installation $install evidence-scan --source 'C:/.../Common/Files/GOAT/Re7e282f93d41' --source 'C:/.../GOAT/Rad870a22d237'
& $py $tool --installation $install catchup-validate --plan 'C:/catchup-plan.json'
& $py $tool --installation $install catchup-prepare --catchup-id 'catchup-20261002' --plan 'C:/catchup-plan.json'
& $py $tool --installation $install catchup-start --catchup-id 'catchup-20261002' --max-seconds 600
& $py $tool --installation $install catchup-resume --catchup-id 'catchup-20261002' --max-seconds 600
& $py $tool --installation $install catchup-report --catchup-id 'catchup-20261002'
```

The plan is `{"schema_version":1,"evidence_end":"auto","sets":[<absolute .set
paths of the behind exports>],"job_timeout_seconds":1800}`. A catch-up closes the
selected MT5 and relaunches it once per member like a seed run; tell the owner
first. `batch-pause --batch-id <catchup id>` pauses between members and
`batch-resume` continues. `research-status` shows it as an OOS catch-up.

This is the first Tier A slice. Terminal discovery, compile, SET editing,
report parsing and exports will be separate tools wrapping existing MT5/EA
features. Native smoke evidence is required before calling this lane qualified.
