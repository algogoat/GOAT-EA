# OOS window formula: every research date from O and the export Friday

Decided by Vince on 2026-10-05 (goatai#1885, comment 6004797676; the demo rule was corrected the
same day in comment 6004826858). It replaces "whatever gap the export happens to leave".
Code: `controller/studio_oos_windows.py` (rule `goat-oos-windows-v1`, evaluation
`goat-oos-window-rule-v1`). Tests: `controller/test_studio_oos_windows.py` and the mutation check
`scripts/test_oos_windows_controller_mutations.py`.

## The windows

O is the optimization period: SAMPLE + FWD. From oldest to newest:

| Window | Length | Role |
|---|---|---|
| BOOS | 1/2 O, immediately before SAMPLE | pass/fail only |
| SAMPLE | 2/3 O | the optimizer fits here |
| FWD | 1/3 O | ranks and picks passes |
| FOOS | 1/4 O, ending at the export Friday | held out: pass/fail only, **never used for ranking** |

Optimization end = export Friday − FOOS. The controller computes every date from O and the export
Friday; nobody types FromDate, ForwardDate, ToDate or BackOOSDate by hand for a formula plan.

## Units, rounding and day alignment

- **O is counted in whole trading weeks.** A plan gives `optimization_months` or
  `optimization_weeks`. A month is exactly 13/3 weeks (52 weeks a year), rounded half up, so 3, 6,
  12 and 24 months are exactly 13, 26, 52 and 104 weeks (1 month = 4 weeks, 2 = 9, 18 = 78).
  Weeks make leap years and month lengths irrelevant and keep every window a whole number of
  trading weeks, comparable with the weekly evidence files.
- **Rounding.** BOOS, FWD and FOOS, the windows that judge, are rounded **up**, so none is ever
  shorter than its exact share of O. SAMPLE = O − FWD absorbs the rounding, so SAMPLE + FWD = O
  exactly.
- **Day alignment** follows `studio_evidence_end` (goat-closed-week-v1). Broker server days; a
  week ends at the Friday close (server Saturday 00:00). Every window runs Saturday through
  Friday inclusive, and every MT5 boundary is a Saturday: `FromDate` is inclusive and `ToDate`
  is exclusive, so `ToDate` = the Saturday after the optimization end, just like
  `tester_to_date` = evidence end + 1 day.
- **The export Friday** defaults to AUTO = the latest fully closed Friday, resolved exactly as
  `evidence-end` resolves it (before the Friday close it is still last Friday). An explicit value
  must be a closed Friday; any other day is refused, never moved.

| O (months) | O (weeks) | BOOS | SAMPLE | FWD | FOOS |
|---|---|---|---|---|---|
| 3 | 13 | 7 | 8 | 5 | 4 |
| 6 | 26 | 13 | 17 | 9 | 7 |
| 12 | 52 | 26 | 34 | 18 | 13 |
| 24 | 104 | 52 | 69 | 35 | 26 |

## Worked example: O = 12 months, export Friday 2026-10-02

O = 52 weeks: BOOS 26, SAMPLE 34, FWD 18, FOOS 13 weeks.

| Window | First day | Last day (inclusive) |
|---|---|---|
| BOOS | Sat 2025-01-04 | Fri 2025-07-04 |
| SAMPLE | Sat 2025-07-05 | Fri 2026-02-27 |
| FWD | Sat 2026-02-28 | Fri 2026-07-03 |
| FOOS (held out) | Sat 2026-07-04 | Fri 2026-10-02 |

- Optimization end: Fri 2026-07-03.
- Tester: `FromDate=2025.07.05`, `ForwardMode=4`, `ForwardDate=2026.02.28`, `ToDate=2026.07.04`.
- Export: `BackOOSDate=2025.01.04`, `IncludeBackOOS=1`, `EvidenceEnd=2026.07.04`.
- FOOS replay: OOS catch-up with `evidence_end` 2026-10-02.
- Seed hunts with the same O read SAMPLE only: `FromDate=2025.07.05`, `ToDate=2026.02.28`, `ForwardMode=0`.

The table above is pinned in `test_studio_oos_windows.py`; so are O = 3, 6 and 24 months and
a FOOS that spans the 2024-02-29 leap day.

## How FOOS is held out with the EA's existing inputs (no EA change)

The EA's export search ranks and trims sets on metrics measured over the **whole export test**,
from `BackOOSDate` to the export end (`StartExporter`: the MinSR/MinARF pass test and
`SortAndTrimExports`). If the export ran to the export Friday, FOOS would be part of that ranking.
So a formula batch uses only existing inputs:

1. The optimization is `FromDate`..`ToDate` with `ForwardMode=4`/`ForwardDate` (SAMPLE + FWD).
2. The export includes BOOS (`IncludeBackOOS=1`, `BackOOSDate`) and stops at the optimization end:
   `EvidenceEnd` = `ToDate`, the earliest end the EA accepts (it refuses an EvidenceEnd before the
   optimization window end). That day is the Saturday after the last optimization Friday, with no
   FX trading, so no FOOS trading day reaches the export or its ranking.
3. FOOS is judged afterwards by the controller-side held-out replay that already exists, **OOS
   catch-up**: one non-optimized pass of the frozen exported values from the export's start to
   the export Friday, judged only on the days after the export's end. Each catch-up verdict now
   carries `oos_rule` (below).

Only EA builds whose monitor reports `goat-evidence-end-v1` (FU35+) can stop exports there, so
`prepare-batch` refuses a formula plan on older builds instead of letting FOOS leak. Activation
and preparation re-derive every date from the recorded O and export Friday and refuse any
difference, including an export end that reaches FOOS. The record also carries a
`heldout_lock` window (`start` = FOOS first day, `end` = export Friday + 1, `revealableAfter` =
export Friday) in the shape the desktop's held-out lock registry uses; the controller never
writes that registry.

### Known limits of v1 (accepted by Claude-Mac, goatai#1885 comment 6007861974)

**BOOS is only partly out of sample (`boosContaminatedBy: "ea_trim"`).** The batch export includes
BOOS (`IncludeBackOOS=1`), and the current EA measures each export's SR and ARF, applies the
MinSR/MinARF pass test and runs `SortAndTrimExports` over the whole export test, BOOS start through
the optimization end. So BOOS partly selects which passes the EA keeps: a real leak, accepted for
v1. Every `oos_rule` the controller writes carries `boosContaminatedBy: "ea_trim"` (also on
`not_applicable` and `no_data` results), so the desktop and the house manifest can show
**"BOOS: partial"**. A BOOS pass is weaker evidence than a FOOS pass: **v1 house portfolios rest
mainly on FOOS**, which never reaches any ranking. The planned fix (the next EA bundle measures
export SR/ARF and the trim on SAMPLE + FWD only) is Claude-Mac's to admit; when it ships, exports
from that EA will carry no stamp (`boosContaminatedBy: null`).

**Saturday-trading symbols (crypto): one FOOS day sits inside the export.** The EA refuses an
EvidenceEnd before the optimization window end, so the export ends on the first FOOS day, a
Saturday. FX, metals and index CFDs do not trade then; for a symbol that does, that is one day of
FOOS's 4 or more weeks (13 weeks at O = 12 months), judged in FOOS as usual. Accepted.
## The pass rule (`judge`, `goat-oos-window-rule-v1`): the source of truth

Claude-Mac ruled (goatai#1885 comment 6005864453) that this controller evaluator is the source of
truth. The desktop sift (goatai#2274) uses the same constants, result names and definitions, and
the shared fixture `controller/fixtures/oos-holdout-gate-cases.json` pins both to identical
results (see "Shared fixture" below).

For each OOS window (BOOS and FOOS):

1. **At least 30 trades.** Fewer is `not_eligible_yet`: too few to judge either way, never a
   failure. A window is **never shortened** to reach the floor, and a window under the floor is
   never judged on PF or DD.
2. With the floor met it passes on **PF ≥ 1.0 AND DD ≤ 1.5 × in-sample (SAMPLE) DD**, the DD bar
   computed exactly (2·DD ≤ 3·SAMPLE DD, no float rounding at the bar).

Window results, in this order:

| Result | When |
|---|---|
| `no_data` | No such window, the window has not been tested, or there is no trade count for it. |
| `not_eligible_yet` | Fewer than 30 trades, or FOOS not tested through the export Friday yet. |
| `fail` | 30+ trades and a measured PF below 1.0 (net below 0) or a measured DD above 1.5 × SAMPLE DD. |
| `not_measured` | 30+ trades, nothing measured failed, but PF, the window DD or the SAMPLE DD (> 0) is missing. |
| `pass` | 30+ trades, PF ≥ 1.0 and DD ≤ 1.5 × SAMPLE DD, all measured. |

A set takes the first of `fail`, `not_eligible_yet`, `not_measured`, `no_data`, `pass` that either
window has, so it passes only when both pass, and a set with fewer than 30 FOOS trades is not
eligible yet. `not_applicable` (outside the five) means the dates were not formula dates or the
export already contained FOOS days. FWD and SAMPLE never change the verdict except through the
in-sample drawdown, and every result says `used_for_ranking: false`.

### Definitions (the desktop must match these exactly)

- **Days**: broker server calendar days; a window is `[first_day 00:00, last_day + 1 day 00:00)`.
- **Trades**: positions opened in the window (entry deals inside it), the count the EA writes as
  `Trades=` in its BOOS/SAMPLE/FWD/FOOS header lines.
- **PL**: the net result of those positions: profit + swap + commission + fee over their deals
  inside the window. All costs are included; a position still open at the window end counts only
  its deals so far.
- **PF**: those deal results summed where positive, over the absolute sum where not positive
  (deal level). PF ≥ 1.0 is exactly PL ≥ 0, which is what the gate tests; no negative deal result
  (no losing trades) passes.
- **DD**: an **equity** drawdown (not balance) in account money: the deepest fall of the sampled
  equity (the one-minute equity rows of the export or re-test CSV, floating P/L included) below
  its running peak, the peak starting at the window's opening equity (the last sample before the
  window, else its first sample). The same definition for SAMPLE, BOOS and FOOS. A SAMPLE DD of 0
  or unknown leaves no limit: `not_measured`.
- **FOOS with catch-up weeks**: FOOS runs from the Saturday after the optimization end through the
  export Friday. A catch-up re-test that runs later extends FOOS to the re-test's end: those weeks
  follow the optimization end and are never ranked, so they **count toward the 30-trade floor**
  (and PF and DD are measured over the same extended window). FOOS is never judged before its full
  1/4 O has been tested.

In the controller, trades, PL and PF come from the re-test's complete deal capture (Model 4
sequence capture); without it the window is `no_data`. DD comes from the re-test's equity CSV.

### Shared fixture

`controller/fixtures/oos-holdout-gate-cases.json` (schema `goat-oos-holdout-gate-cases-v1`)
holds the rules, the definitions, 25 window cases, 8 set cases and 5 date cases.
`controller/test_studio_oos_windows.py` runs every case and checks the file's rules against the
module constants. The same bytes live at goatai `docs/fixtures/oos-holdout-gate-cases.json`, where
the desktop gate test runs every case. Change it in GOAT-EA first, then copy the identical file to
goatai in a paired PR; never edit one copy alone.
Where it is reported (additive; nothing already reported changed):

- `catchup-report` rows and each catch-up result: `oos_rule` with the per-window numbers and
  reasons; the result summary and `evidence-version.json` carry it too. The catch-up verdict
  (`held_up`, `weakened`, ...) and the export qualification stamp (`goat-export-qualification-v1`)
  are unchanged and stay separate: qualification says which sets passed the run's export
  thresholds, `oos_rule` says whether a formula set passed its BOOS and FOOS.
- `batch-status` of a formula batch: `oos_windows` with every window and the FOOS replay to run.

## Evidence for live decisions: the latest closed day (catch-up only)

Vince's rule (goatai#1885 comment 6008215775): evidence for a live decision runs to the latest
**closed day**, not the last Friday. The optimization windows and exports are unchanged: they stay
Friday-anchored and the weekly date math above does not move.

- **Catch-up only** may end on any closed trading day. `evidence_end: "auto_day"` resolves like
  `auto`, but to the latest closed trading day (rule `goat-closed-day-v1`). That is the newest
  Mon–Fri broker day, not a full market holiday, whose server date has rolled over (D-1 close). On
  Wednesday at 18:00 broker time it is Tuesday; on Saturday, Sunday and Monday it is Friday. An
  explicit closed weekday works too. Today and future days are refused.
  `evidence-end --value auto_day` shows it.
- Use it for decisions that need the newest evidence: a candidate's gate check, the basket FOOS
  test when adding or swapping a member, a manual re-optimize, a hard-stop replacement.
- **One decision, one date.** `auto_day` is resolved once, at `catchup-prepare`, and recorded in
  the catch-up manifest (`evidence_end: {mode: "auto_day", iso: ...}`). Every other run in the same
  decision passes that **explicit date**, never `auto_day` again, because `auto_day` moves every
  day. A re-prepared catch-up keeps its recorded date.
- **Stamped everywhere** for the version changelog:
  - `evidenceEnd` and `evidenceEndMode` on every catch-up result (the verdict, the result
    summary and `evidence-version.json`) and on the desktop `catch_up` import stamp;
  - `evidenceEnd` on every `oos_rule` and on each `catchup-report` row;
  - `qualification.evidence_end.rule` reads `goat-closed-day-v1` for an `auto_day` end.
- **FOOS floor:** catch-up days after the export Friday, through a mid-week closed day, count
  toward FOOS's 30 trades; FOOS is judged through the catch-up's `evidenceEnd` (or the earlier
  re-test end), never further.
- **Exports refuse `auto_day`.** `prepare-batch` `evidence_end` and `oos_windows.export_friday`
  refuse it, and `oos_windows.export_friday` still refuses any non-Friday. Batch plans with an
  explicit, non-Friday `evidence_end` keep working with their existing warning, for backward
  compatibility. A formula batch's own export end is a Saturday by design.
## Exact pre-FOOS metrics at export (`goat-export-window-metrics-v1`)

Claude-Mac's ruling (goatai#1885 comment 6006565005): the desktop estimated pre-FOOS ARF and
Sharpe by scaling the EA's full-period header values. The EA writes its header and file-name
metrics over the whole export test and is not changed here, so the **controller** computes exact
values from what each export unit already holds: the equity CSV and, when the export carries a
complete sequence capture, its `deals.csv` (`controller/studio_window_metrics.py`).

Where: the report pipeline. `finish` → `reports` → each member's `exports.files[]` item (the
per-set records the agent imports into the matrix) carries `window_metrics`:

```json
"window_metrics": {
  "schema": "goat-export-window-metrics-v1",
  "basis": "controller_replay_of_export_csv_and_capture",
  "preFoos":         {"from": "...", "to": "...", "days": 0, "profit": 0, "pf": 0, "pfNote": null, "trades": 0,
                      "tradeSource": "capture_deals", "maxDd": 0, "ddPct": 0, "arf": 0, "sharpe": 0,
                      "recoveryFactor": 0, "equityNet": 0},
  "selectionWindow": {"...": "same fields"},
  "fullExport":      {"...": "same fields"},
  "optimizationEnd": "YYYY-MM-DD", "foosStart": "YYYY-MM-DD", "tradeSource": "capture_deals | set_header_or_none"
}
```

- `preFoos`: everything the export holds before FOOS, from the export start (BOOS start when the
  export includes BOOS, else SAMPLE start) through the optimization end (MT5 `ToDate` − 1 day).
- `selectionWindow`: SAMPLE + FWD only, `FromDate` through the optimization end (house portfolios
  rank on this span).
- `fullExport`: the whole export with the same definitions, so the desktop compares like with like.
- `from`/`to` are inclusive broker days; `days` counts Mon–Fri days.
- `trades`, `profit`, `pf`, `pfNote`: the OOS evaluator's definitions (positions opened in the
  window; net of profit + swap + commission + fee; deal-level PF, `pfNote: "no losing deals"` when
  nothing lost). Without a complete capture, `trades` and `profit` are the sums of the EA's SET
  header window lines (`tradeSource: "set_header"`) when they cover the window exactly, and `pf` is
  null; otherwise all three are null.
- `maxDd`, `ddPct`: the evaluator's equity drawdown (peak starting at the window's opening
  equity); `ddPct` is the deepest fall as a percent of the running peak at that moment.
- `recoveryFactor` = `profit` / `maxDd`; `equityNet` = closing − opening equity.
- `arf`: the EA's header ARF (monthly ARF from `OnTester`) replayed on the one-minute samples:
  Return / (EA MeanDD of the five deepest drawdown episodes / opening equity) / (days / 21.7). The
  EA measures on ticks and counts days with ticks, so it can differ slightly from a header ARF over
  the same span.
- `sharpe`: daily equity returns (Mon–Fri closes, carried forward), mean / sample standard
  deviation × √252. It is **not** MT5's `STAT_SHARPE_RATIO` (the header SR); compare it only with
  `fullExport.sharpe`.
- A unit whose CSV cannot be read gets `window_metrics: {status: "unavailable", reason}`; the
  export's status and qualification never change because of it. For a held-out-locked export the
  whole `window_metrics` (and `oos_rule`) is redacted like every other tested value.
## Plans

Batch plan (`prepare-batch`): add `"oos_windows": {"optimization_months": 12}` (or
`"optimization_weeks": 52`, and optionally `"export_friday": "2026-10-02"`; default `auto`).
Members may omit `FromDate`, `ToDate`, `ForwardMode` and `ForwardDate`, and the export may omit
`BackOOSDate` and `IncludeBackOOS`; leave out `evidence_end` too. Any of them you do give must equal
the formula exactly, or prepare refuses and names the difference. The frozen plan records every
resulting date explicitly plus the whole window record (`native_batch.oos_windows`), hash-bound
with the plan. `batch-resume` successors keep the same O and the same resolved export Friday.

Seed plan (`seed-prepare`/`seed-validate`): the same `oos_windows` key. Seed jobs read SAMPLE
only (`FromDate` = SAMPLE start, `ToDate` = `ForwardDate`, `ForwardMode=0`), so FWD, BOOS and FOOS
stay unseen for the batch that ranks and judges the promoted candidates.

Backward compatibility: a plan without `oos_windows` is unchanged byte for byte in what it stages,
and existing SETs, saved `.goatbatch` files and explicit-date plans work exactly as before. No
EA input, enum or MQL file changed.

## Demo: FOOS's continuation, not scaled with O

Demo is the live test after export. It continues FOOS but does not scale with O:

- It lasts **at least 4 weeks AND at least 30 trades**, and a decision is due by **6 weeks**.
- A set still under 30 trades at 6 weeks is **"too slow to judge here"**: never promote it on thin
  data.
- The 4-week floor makes every set see several weekly cycles and major releases (NFP, CPI, a
  central-bank meeting).
- For M1 and other high-frequency sets the main demo check is **execution parity**: live vs
  backtest over the same weeks, with real spread, slippage and commission.
- It is judged on **PF ≥ 1.0** plus live vs backtest over the same weeks, at the **portfolio**
  level.

This is documented (`studio_oos_windows.DEMO_RULE`); nothing in the controller automates demo yet.

## How agents talk about it

- Say the windows with their dates: "O is 12 months. The optimizer fits on 5 Jul 2025 to 27 Feb
  2026 and ranks on 28 Feb to 3 Jul 2026. BOOS (4 Jan to 4 Jul 2025) and the held-out FOOS
  (4 Jul to 2 Oct 2026) are pass/fail checks only."
- FOOS is held out: never describe it as part of the ranking, never pick or sort sets by FOOS
  results, and never show FOOS numbers as a reason a set was chosen.
- `not_eligible_yet` is not a failure: "it has 22 trades in FOOS; it needs 30 (catch-up weeks count) before it can be
  judged". Never suggest shortening a window or picking a different O to get past the floor.
- `no_data` and `not_measured` are not passes: say which measurement is missing (usually the deal capture,
  or a drawdown that was not measured).
- Say "BOOS: partial" whenever you report a BOOS result: the current EA's export trim partly selected on\n  BOOS (`boosContaminatedBy: "ea_trim"`). Lead with FOOS; v1 house portfolios rest mainly on it.\n- A pass is a pass of two checks on held-out data (FOOS fully, BOOS partly), not proof of an edge; demo comes next.
