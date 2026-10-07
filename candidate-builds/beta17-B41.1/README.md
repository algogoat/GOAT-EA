**Superseded by B41.2 (`../beta17-B41.2`). Native proof FAILED on T3** (goatai#1885 6030127717, deploy `b5dd2889`):
the queued child template was never applied (no child `Initialization Start` in 76 s), and the attach timed out and unwound.
Do not install this binary. It is retained as a candidate record, like B41 and earlier.

B41.1 is B41 plus two deploy-path fixes, both on goatai#1885. It is a hotfix: there is no trade-logic,
input, default or SET-writer change. See **Build**.

- **CA41:** six input names on the deploy audit's exemption list, as Claude-Mac specified (6008656907).
- **AA41:** the agent's child attach is asynchronous (6027754245). On B41 no agent deploy could attach a child.

**AA41: why.** The agent's `deploy_next` ran the dashboard attach inside its timer handler:
`ChartOpen`, then `ChartApplyTemplate` (which only adds the template to the chart's queue), then a wait of up to
20 s for the child's handshake, still inside the same handler. On T3 (deploy `56a46a8a`, 2026-10-06 23:50Z)
the template was queued at 23:50:04.151. No child EA loaded in the 20 s, and the dashboard deleted the template
at 23:50:24.197, inside that same handler. The terminal saved the child chart at shutdown (23:53:42) with no
expert. The controller reported `child_attach_failed`.

**AA41: what changes.** `AgentBeginDeployRow` opens the chart, persists the child identity, queues the template
and returns. `AgentPollDeployRow` runs the same `NewSingleInstance` handshake on later timer ticks, within
`GOAT_AGENT_ATTACH_BUDGET_MS` (75 s). The budget has to stay above a child's license startup: the child writes its
handshake only after `OnInit`, and the license check in `OnInit` retries for up to 60 s
(`GOATLicenseInitRetry.mqh`). On success the dashboard links the child and only then deletes the template.

**Inertness is re-checked on every tick of the attach** (Claude-Mac, 6028472101, 6028711169). Once Algo Trading is
on, or a position or order is open, the attach is unwound at the next tick, exactly like a timeout, and answers
`rejected_not_inert`. The receipt schema is fixed, so the child's own positions and orders (by its magic) go to the
deployment diagnostics as `not_inert_child_trades` (see **Controller follow-up**).

**One unwind for every failed agent attach** (`AgentUnwindFailedAttach`; 6028209095, 6028472101):

- The row goes back to Pending and the template is deleted, as before.
- **The child chart is closed**, which unloads a child that is still starting. The close happens only while
  `ChartSymbol(cid)` still names the row's symbol. The chart ID stays as the partial-deployment lock.
- The row is **saved** with the failed marker `GOAT_ATTACH_FAILED_MAGIC` (`-2`; rows that were never deployed hold
  `-1`). The marker replaces any magic a status event adopted early.
- `GOAT_EVENT_CHILD_STATUS` from a marked chart is ignored, so a failed row can never become a live member while
  the receipt says `child_attach_failed` or `rejected_not_inert`.
- Because the marker is saved, it survives a restart. When the dashboard loads, it closes a marked row's chart
  again, in case MT5 restored the chart with its child, but only if that chart is provably our child: the GOAT EA
  is on it (`CHART_EXPERT_NAME`), and its chart-ID record and `SETUP_CID` handshake match the row. Otherwise it logs
  `child_chart_not_ours`. The state file keeps its nine columns.
- The failed step is named in the deployment diagnostics (`phase=child_attach_failed
  control=handshake_timeout|not_inert|template_enqueue|chart_open|…`). Then comes `child_chart_closed`,
  `child_chart_close_failed` or `child_chart_not_found`.

`GoatPortfolioSetupPoll` keeps the request's `started` receipt until the attach settles, and reads no other
request meanwhile. The receipt schema and its result values are unchanged.

**Startup sweep.** When a saved dashboard loads, a copied template left for a row that has a chart ID but no
linked child (an interrupted or failed attach) is deleted. The row itself stays as the lock.

The human Activate / Deploy All path keeps its 20 s in-handler wait, and on a timeout it leaves the chart open for
inspection.

**Controller follow-up (receipt detail).** beta.23's controller accepts an exact receipt field set
(`portfolio_receipt`), so a `rejected_not_inert` receipt cannot name the child's trades. The receipt's account-wide
`positions` and `orders` counts are already there. A later controller and EA pair can add per-row `childPositions`
and `childOrders`. Until then, the tickets are in `MQL5\Files\GOAT\Diagnostics\deployment_<dashboard chart id>.log`.

**Controller wait.** beta.23's controller waits 60 s for each `deploy_next` receipt. From beta.23.1 (GOAT-EA#188) it
waits 90 s, above the EA's 75 s attach budget, and the request expires at 95 s. **B41.1 ships only together with #188.**
On a beta.23 controller, an attach that takes longer than 60 s ends deploy-load with `receipt_timeout`. Re-running
deploy-load continues if the final receipt has landed. Recovery is in `docs/operations/DEPLOYMENT-STARTUP-LIVENESS.md`.

**Why.** On a deploy-load, `GoatPortfolioChildSettingsMatch` saves the child chart's template, and
`GoatChildAuditMaps` requires the frozen SET's input names to equal the template's, apart from three
exempt live sinputs. V1.49 declares six inputs that no SET carries, because `WriteSet`
(`GOAT_Inputs_Definitions.mqh`) omits them:

- `Sequence_Export_Enabled`, `Sequence_Export_Id`, `Sequence_Export_Start`, `Sequence_Export_End` and
  `Sequence_Export_Model` (`GOAT_SequencePackage.mqh`, from V1.48);
- `GOAT_FitnessRunNonce` (`GOAT V1.49.mq5`, from SM32).

MT5 writes declared inputs into the chart template. When it writes these six, the name counts differ, and the
audit refuses every B41 deploy-load with "child inputs differ from the frozen SET".

**What changes from B41**

| Where | What it does |
|---|---|
| `GOATPortfolioChildAudit.mqh` | `GoatChildAuditMaps`: after the three existing exemptions, a second list of six names with their declared defaults (`false`, empty, `0`, `0`, `4`, `0`). If the child template carries one of them and the SET does not, the audit adds it at its default. The existing value check then requires the template to hold exactly that default. A SET that carries one still compares it value for value. A name in neither is skipped, so a V1.47 child, which declares none of them, audits exactly as before (V1.48 declares the five `Sequence_Export_*` and would get the same relief if rebuilt; its committed binary is untouched). Any other unknown name still fails. |
| `Dashboard.mqh` (AA41) | `AgentDeployRow` becomes `AgentBeginDeployRow` plus `AgentPollDeployRow`, with the 75 s `GOAT_AGENT_ATTACH_BUDGET_MS`. On an agent timeout, `AgentPollDeployRow` closes the chart, drops early magic and records the chart in `m_agent_attach_failed_cids`, and the child-status handler ignores those charts. `ApplyTemplate` is split into `BeginChildAttach`, `FailChildAttachTimeout` and `CompleteChildAttach`, with the same statements. `DoActivate`'s prelude becomes `PrepareChildLaunch`, shared by both paths, and it refuses while an agent attach is in flight. `LoadDashboardConfig` calls `SweepStaleChildTemplates`. |
| `GOATPortfolioSetupControl.mqh` (AA41) | `deploy_next` starts the attach and returns. `GoatPortfolioAttachContinue` settles it on later ticks, re-checks inertness and writes the final receipt. A busy owner lock or a failed write is retried on the next tick. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-41.1`, marker `B41.1`. `GOAT_VERSION_LABEL` stays `1.49`, so `GOAT V1.49 …` SET filenames and the input header stay valid. |

**Not changed.** Trade, risk, signal and bias logic, every input and default, the input header
(`1408e1ee…`, SM32's), `WriteSet`, the deploy-load SET bytes, the three existing exemptions, Astra's inputs,
the trade-event policy, the bias wire and the model route. Deploy-load does not fill defaults into the SET,
which would change SET bytes and break the hash chain.

**Why default-pinned, not ignored.** The existing exemptions require the inert default rather than ignore the
value, and these six follow suit: a child running with `Sequence_Export_Enabled=true` or a stray nonce is not
the frozen strategy, and the audit still refuses it.

**Tests.** `scripts/test_portfolio_child_audit.cjs` runs the production parser: a V1.49 template carrying the
six at their defaults passes; any one at a non-default value fails, as does a SET/template disagreement on one
the SET carries, or an extra unknown name. B41's audit fails the first case, which reproduces the bug.

`scripts/test_dashboard_async_attach.cjs` (21 cases) runs the production attach code against a modelled MT5. In
the model, chart queues drain after the handler returns, and a child's `OnInit` can be delayed.

- B41's in-handler wait reproduces T3.
- The async path attaches all 35 members.
- Children that register at 25 s and at 70 s are linked. A child due after the budget is unloaded when its
  chart closes.
- An unclosable chart's late status is ignored, and the row never links.
- After a restart, a restored marked chart is closed on load. If it can't be closed, its child still never adopts the row, and a chart ID now showing another symbol is left alone.
- When inertness fails at settle (Algo on, or a position open), the chart is closed, no child runs, the row is not linked, and the marker is saved.
- Stale templates are overwritten before queueing, a failed copy queues nothing, and the startup sweep removes a
  partial row's template.
- The timeout, enqueue-failure, busy-lock and failed-write paths all unwind.

`scripts/test_dashboard_async_attach_mutations.cjs` removes or weakens each guard and requires the harness to
fail: 36 of 36 mutants are killed. They include the not-inert path skipping the close, the 0db8aea receipt-only behaviour, an unsaved marker, a missing symbol check and no close on load. `scripts/test_b41_1_no_drift.cjs` checks the source against B41 (`278ec109`), normalised: only
`Dashboard.mqh`, `GOATPortfolioSetupControl.mqh` and `GOATPortfolioChildAudit.mqh` differ, and `StartExporter`,
`OnTick`, `OnTradeTransaction` and `OnTimer` are identical.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41.1`, marker `B41.1`, on top of B41 (`278ec109`, GOAT-EA#147, compiled in #150).
- Compiled once from `0cfdfacf` (CA41, AA41 and the fixes from Claude-Mac's reviews 6028209095, 6028472101 and
  6028711169) with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39, B40 and B41): 0 errors,
  0 warnings. The compiler was a copy outside every terminal folder, run `/portable` at Idle priority.
  MetaEditor's process exit code was 1 with a clean `Result:` line, as in the B40 and B41 compiles; the `Result:`
  line and the output are the success criteria. The stage was a scratch copy outside every terminal folder. Its
  307 standard includes and the `MACD - GOAT 2.ex5` resource are copied from the B41 compile root and hash-equal
  to it. `externals.json` records the same per-name hashes as B41's, and the same `consumed_sha256` (`ced68559…`).
- `GOAT V1.49.ex5`: sha256 `cb03c0b6e818331f53ad2c9ad7559ded0ab61d6636c1f02a36f4449ba4ae7b09`, 2,438,734 bytes.
  It ships only together with GOAT-EA#188 (beta.23.1's 90 s controller wait; see **Controller wait**).
- Pin check at `0cfdfacf`: the 41 `.mq5`/`.mqh` files in the entrypoint's include closure are exactly the 41
  sources in `identity.json`, and each matches the tree and the staged copy.
- Superseded, do not install any of them:
  - A compile of `dab89304` stopped on MetaEditor warning 62 (a local `orders` hid the global trade counter,
    renamed in `0cfdfacf`). Its output was never a candidate.
  - The uncommitted `09d69e98` build (no per-tick inert check, no ours-check), which the compile agent moved out of the worktree.
  - `6d1963c4…` (from `278ef0af`, not inert answered by receipt only, no persisted marker). It was compiled but never committed, and was set aside outside the repository.
  - `d496884a…` (from `c8355f66`, AA41 with the 20 s budget and no chart close). It stays in history at
    `5510bbb5`.
  - The CA41-only `b3650d96…` (from `4f3f2f99`). It stays in history at `f00cc8ad`.
  - A compile of `0db8aea3` stopped on MetaEditor warning 62 (a local `closed`, renamed in `278ef0af`).
- Entrypoint `GOAT V1.49.mq5`: sha256 `dee033a8…7e8fa56b`, pinned in `controller/contracts/v149/dependencies.json`.
- Only `GOAT V1.49.mq5`, `GOATPortfolioChildAudit.mqh`, `Dashboard.mqh` and `GOATPortfolioSetupControl.mqh`
  differ from B41. The input header is still `1408e1ee…`.
- No drift: `scripts/test_b41_1_no_drift.cjs` (see **Tests**).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:**

1. Claude-Mac's review of this source and binary.
2. Claude-Mac's pin check, no-drift check and internal admission of `V1.49-BETA17-41.1`.
3. A native deploy-load on a non-Exp demo. It must attach the child charts, the first one included, and read
   `settingsMatch` true for one V1.49-writer SET and one Balanced35 SET.
