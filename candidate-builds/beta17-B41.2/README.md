**Superseded by B41.3 (`../beta17-B41.3`). Native proof FAILED on T3** (goatai#1885): there was one refresh, then a false
`attach_nudge_stopped expert=""` (`CHART_EXPERT_NAME` is a NULL string, and `NULL != ""` is true), and the child EA never loaded.
Do not install this binary. It is retained as a candidate record.

B41.2 is B41.1 (AA41 + CA41, see `../beta17-B41.1/README.md`) plus a refresh of the pending child chart. It is a
hotfix: there is no trade-logic, input, default or SET-writer change.

**Why.** The B41.1 native proof on T3 failed (goatai#1885 6030127717; deploy `b5dd2889`, 03:10Z, B41.1 `cb03c0b6`).

- The dashboard opened the child chart (`target=67068748718970`), queued its template and returned at once
  (`handshake_begin` at 03:10:20).
- The MT5 journal shows the template copied to `Profiles\Templates` and queued, but **no child
  `Initialization Start` in 76 s**, although EURUSD was ticking.
- At 03:11:36 the attach hit `handshake_timeout`. The unwind then worked natively: `child_chart_closed`, then
  `child_attach_failed`.

So a template queued on a newly opened chart is not processed until that chart gets an update. Ticks are not
enough. From V1.37 (`83a26f7`) until `ebb9958`, the old in-handler wait called `ChartSetSymbolPeriod(cid,symbol,tf)`
and `ChartRedraw(cid)` every 2 s, and with that refresh the 2026-09-23 pair rollouts attached children. `ebb9958`
removed it as "refresh interference", and no attach has succeeded since.

**What changes from B41.1** (Claude-Mac's rulings, 6030140212)

| Where | What it does |
|---|---|
| `Dashboard.mqh` | `AgentPollDeployRow`, on the poll tick, **only while that row's handshake is pending and no expert is on its chart yet**: every 2 s, `ChartSetSymbolPeriod(cid, row symbol, chart period)` then `ChartRedraw(cid)`. This is the pre-`ebb9958` form, now between timer ticks instead of inside a blocked handler. **It stops once `ChartGetString(cid, CHART_EXPERT_NAME)` is non-empty**, so a loaded child is never refreshed. A refresh could re-run its `OnInit` license check, and the handshake is written only from `OnTimer` (Mac 6030329907). `ChartGetString` is synchronous (it waits for the chart's queued commands), so it is asked only after the first refresh; before that, the new chart cannot carry an expert. **The period is `ChartPeriod(cid)`, read right after `ChartOpen`**, never `PERIOD_CURRENT`. Without a concrete period there is no refresh (`attach_nudge_disabled`). **Each refresh is logged** as `phase=attach_nudge control=n=<count> expert=""`, and **the stop** as `attach_nudge_stopped control=expert="<name>"`. **No template re-apply.** The 75 s budget, the per-tick inert check, the unwind, the failed marker, the on-load proof and the receipt are unchanged. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-41.2`, marker `B41.2`, one `#define` each. `GOAT_VERSION_LABEL` stays `1.49`. |

**Not changed.** The human Activate / Deploy All path keeps its B41.1 form: an in-handler wait with no refresh. It
needs the same queued design (beta.24). Also unchanged: trade, risk, signal and bias logic, every input and
default, the input header (`1408e1ee…`), `WriteSet`, `StartExporter`, the bias wire and the model route.

**Tests**

- `scripts/test_dashboard_async_attach.cjs` (24 cases). In the model, a queued template applies only after the
  handler returns **and** the chart gets an update (`ChartSetSymbolPeriod` or `ChartRedraw` on that chart). Ticks
  are deliberately not an update, as T3 showed.
  - Case 21 runs **B41.1's source (`0cfdfacf`)**: it reproduces T3. The template is never applied, the attach times
    out at 75 s, the chart closes and no child runs.
  - Case 2 runs B41.2: **all 35 members attach**. Every nudge hits a row while its handshake is pending, with that
    row's symbol and timeframe. Nudges stop once the row links, and every chart keeps its symbol and timeframe.
  - Case 22, the worst case (a refresh of a chart running the EA re-runs `OnInit`, with a 5 s license startup): all 35 attach with **zero re-inits and zero synchronous chart queries against an unprocessed queue**. Each member gets exactly one `attach_nudge n=1 expert=""` and one `attach_nudge_stopped expert="GOAT V1.49"`, before `handshake_linked`.
  - Case 23: a requested timeframe that resolves to `PERIOD_CURRENT` still refreshes with the chart's stored period (M1).
- `scripts/test_dashboard_async_attach_mutations.cjs`: 47 of 47 mutants killed. They include the nudge dropped
  (the B41.1 behaviour), the nudge hitting non-pending rows (linked or failed), a changed timeframe, no 2 s cadence,
  **nudging after the expert appears**, the gate never closing, the expert queried before the first refresh, the
  requested timeframe used instead of the stored period, the period not read after `ChartOpen`, and either log line removed.
- `scripts/test_b41_1_no_drift.cjs` (against B41, `278ec109`, normalised): only `Dashboard.mqh`,
  `GOATPortfolioSetupControl.mqh` and `GOATPortfolioChildAudit.mqh` differ. `StartExporter`, `OnTick`,
  `OnTradeTransaction`, `OnTimer` and `GoatTimerBody` are identical. Against B41.1 only `Dashboard.mqh` and the
  build-ID lines differ.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41.2`, marker `B41.2`.
- Compiled once from `d3324e9f` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39, B40,
  B41 and B41.1): 0 errors, 0 warnings. The compiler was a copy outside every terminal folder, run `/portable` at
  Idle priority. MetaEditor's process exit code was 1 with a clean `Result:` line, as in the B40 and B41 compiles;
  the `Result:` line and the output are the success criteria. The stage was a scratch copy outside every terminal
  folder. Its 307 standard includes and the `MACD - GOAT 2.ex5` resource are copied from the B41 compile root and
  hash-equal to it. `externals.json` records the same per-name hashes as B41's, and the same `consumed_sha256`
  (`ced68559…`).
- `GOAT V1.49.ex5`: sha256 `19ce944ab43ce5e779a6ecf498c8577bdc4f724f63028e054ff05741184472ee`, 2,439,044 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `fef16750…3d7335`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `d3324e9f`: the 41 `.mq5`/`.mqh` files in the entrypoint's include closure are exactly the 41
  sources in `identity.json`, and each matches the tree and the staged copy. The input header is still `1408e1ee…`.
- MetaEditor output is not byte-reproducible across stages, so admit only this binary. A compile of the earlier
  `6d8e092b` (`1bb7dcff…`) was withdrawn on review (6030329907) and never committed.
- The retained B41.1 candidate (`../beta17-B41.1`) keeps its own binary, which failed native qualification. Do not
  install it.

**Not done.** Native qualification has not been performed, and nothing was installed. The root `GOAT V1.49.ex5` is
unchanged.

**Controller.** B41.2 ships together with GOAT-EA#188 (beta.23.1), whose `deploy_next` wait is 90 s, above the
75 s attach budget.

**Still owed:** Claude-Mac's review of this source and binary, the pin check and the admission of `V1.49-BETA17-41.2`, then
the native deploy-load on T3. That run must attach every child, starting with the first, and read
`settingsMatch` true.
