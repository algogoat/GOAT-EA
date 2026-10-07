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

On a timeout (Claude-Mac's review, 6028209095):

- The row goes back to Pending and the template is deleted, as before.
- **The child chart is closed**, which unloads a child that is still starting. Its chart ID stays as the
  partial-deployment lock.
- Any magic that a status event adopted early is dropped. A late `GOAT_EVENT_CHILD_STATUS` for that chart is
  ignored, so a failed row can never become a live member while the receipt says `child_attach_failed`.
- The failed step is named in the deployment diagnostics (`phase=child_attach_failed control=handshake_timeout`,
  `template_enqueue`, `chart_open`, …), followed by `child_chart_closed` or `child_chart_close_failed`.

`GoatPortfolioSetupPoll` keeps the request's `started` receipt until the attach settles, and reads no other
request meanwhile. **It re-checks inertness when the attach settles.** If Algo Trading was switched on, or a
position or order opened, during the attach, a linked child answers `rejected_not_inert`. The receipt schema and
its result values are unchanged.

**Startup sweep.** When a saved dashboard loads, a copied template left for a row that has a chart ID but no
linked child (an interrupted attach) is deleted. The row itself stays as the lock.

The human Activate / Deploy All path keeps its 20 s in-handler wait, and on a timeout it leaves the chart open for
inspection.

**Controller wait (beta.23).** `studio_demo_deploy.py` waits 60 s for the `deploy_next` receipt. An attach that
settles between 60 and 75 s therefore reaches the controller as `receipt_timeout`, and deploy-load stops. Until the
controller waits 90 s (a separate controller change), re-run deploy-load. If the final receipt has landed by
then, deploy-load continues; if it is still `started`, the controller refuses with "unresolved dashboard
mutation". Recovery is in `docs/operations/DEPLOYMENT-STARTUP-LIVENESS.md`.

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

`scripts/test_dashboard_async_attach.cjs` (17 cases) runs the production attach code against a modelled MT5. In
the model, chart queues drain after the handler returns, and a child's `OnInit` can be delayed.

- B41's in-handler wait reproduces T3.
- The async path attaches all 35 members.
- Children that register at 25 s and at 70 s are linked. A child due after the budget is unloaded when its
  chart closes.
- An unclosable chart's late status is ignored, and the row never links.
- Inertness is re-checked at settle.
- Stale templates are overwritten before queueing, a failed copy queues nothing, and the startup sweep removes a
  partial row's template.
- The timeout, enqueue-failure, busy-lock and failed-write paths all unwind.

`scripts/test_dashboard_async_attach_mutations.cjs` removes or weakens each guard and requires the harness to
fail: 21 of 21 mutants are killed. `scripts/test_b41_1_no_drift.cjs` checks the source against B41 (`278ec109`), normalised: only
`Dashboard.mqh`, `GOATPortfolioSetupControl.mqh` and `GOATPortfolioChildAudit.mqh` differ, and `StartExporter`,
`OnTick`, `OnTradeTransaction` and `OnTimer` are identical.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41.1`, marker `B41.1`, on top of B41 (`278ec109`, GOAT-EA#147, compiled in #150).
- **Compile pending for this source.** It carries CA41, AA41 and the fixes from Claude-Mac's review (6028209095).
  No binary in this folder belongs to it.
- Superseded, do not install either:
  - `d496884a…` (from `c8355f66`, AA41 with the 20 s budget and no chart close). It stays in history at
    `5510bbb5`.
  - The CA41-only `b3650d96…` (from `4f3f2f99`). It stays in history at `f00cc8ad`.
- Entrypoint `GOAT V1.49.mq5`: sha256 `dee033a8…7e8fa56b`, pinned in `controller/contracts/v149/dependencies.json`.
- Only `GOAT V1.49.mq5`, `GOATPortfolioChildAudit.mqh`, `Dashboard.mqh` and `GOATPortfolioSetupControl.mqh`
  differ from B41. The input header is still `1408e1ee…`.
- No drift: `scripts/test_b41_1_no_drift.cjs` (see **Tests**).
- MetaEditor output is not byte-reproducible across stages, so admit only the binary compiled from this source.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:**

1. Claude-Mac's review of this source, then the compile.
2. Claude-Mac's pin check, no-drift check and internal admission of `V1.49-BETA17-41.1`.
3. A native deploy-load on a non-Exp demo. It must attach the child charts, the first one included, and read
   `settingsMatch` true for one V1.49-writer SET and one Balanced35 SET.
