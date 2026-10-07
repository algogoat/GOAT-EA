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
| `Dashboard.mqh` | `AgentPollDeployRow`, on the poll tick, **only while that row's handshake is pending**: every 2 s, `ChartSetSymbolPeriod(cid, row symbol, row timeframe)` then `ChartRedraw(cid)`. This is the pre-`ebb9958` form, now between timer ticks instead of inside a blocked handler. The row's timeframe is kept from `AgentBeginDeployRow` (`m_agent_attach_tf`). The nudge stops when the row links or the attach unwinds. The symbol and timeframe passed are the row's own, so the chart is refreshed, not changed. **No template re-apply.** The 75 s budget, the per-tick inert check, the unwind, the failed marker, the on-load proof and the receipt are unchanged. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-41.2`, marker `B41.2`, one `#define` each. `GOAT_VERSION_LABEL` stays `1.49`. |

**Not changed.** The human Activate / Deploy All path keeps its B41.1 form: an in-handler wait with no refresh. It
needs the same queued design (beta.24). Also unchanged: trade, risk, signal and bias logic, every input and
default, the input header (`1408e1ee…`), `WriteSet`, `StartExporter`, the bias wire and the model route.

**Tests**

- `scripts/test_dashboard_async_attach.cjs` (22 cases). In the model, a queued template applies only after the
  handler returns **and** the chart gets an update (`ChartSetSymbolPeriod` or `ChartRedraw` on that chart). Ticks
  are deliberately not an update, as T3 showed.
  - Case 21 runs **B41.1's source (`0cfdfacf`)**: it reproduces T3. The template is never applied, the attach times
    out at 75 s, the chart closes and no child runs.
  - Case 2 runs B41.2: **all 35 members attach**. Every nudge hits a row while its handshake is pending, with that
    row's symbol and timeframe. Nudges stop once the row links, and every chart keeps its symbol and timeframe.
- `scripts/test_dashboard_async_attach_mutations.cjs`: 41 of 41 mutants killed. They include the nudge dropped
  (the B41.1 behaviour), the nudge hitting non-pending rows (linked or failed), a changed timeframe, a timeframe
  not remembered, and nudging with no 2 s cadence.
- `scripts/test_b41_1_no_drift.cjs` (against B41, `278ec109`, normalised): only `Dashboard.mqh`,
  `GOATPortfolioSetupControl.mqh` and `GOATPortfolioChildAudit.mqh` differ. `StartExporter`, `OnTick`,
  `OnTradeTransaction`, `OnTimer` and `GoatTimerBody` are identical. Against B41.1 only `Dashboard.mqh` and the
  build-ID lines differ.

**Build.** Compile pending. Entrypoint `GOAT V1.49.mq5` is pinned in `controller/contracts/v149/dependencies.json`.
The retained B41.1 candidate (`../beta17-B41.1`) keeps its own binary, which failed native qualification. Do not
install it.

**Controller.** B41.2 ships together with GOAT-EA#188 (beta.23.1), whose `deploy_next` wait is 90 s, above the
75 s attach budget.

**Still owed:** Claude-Mac's review, then the compile, the pin check and the admission of `V1.49-BETA17-41.2`, then
the native deploy-load on T3. That run must attach every child, starting with the first, and read
`settingsMatch` true.
