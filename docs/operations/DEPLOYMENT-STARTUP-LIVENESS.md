# Child deployment startup investigation

September 24, 2026: two separate child attachments failed on an inert demo
terminal. The first recorded a successful license check followed by a panel
creation failure. The second initially had no child initialization in the buffered
journal. The later flushed record shows NZDUSD `OnInit` at 11:31:21.688 (UTC+5),
license HTTP 200 at 11:31:27.943, dashboard `APPLY_FAILED` at 11:31:40.569, then
`ChartWindowsHandle` error 4102 (`ERR_CHART_NO_REPLY`) at 11:31:48.581. That chart
query occurs after panel creation, before the final magic registration. No final
`INIT_FAILED` was observed. The dashboard's polling deadline therefore expired
while the child was still initializing; this is distinct from the first known
panel failure. The timed-out read-only status later completed. Neither failure
establishes one common root cause or a permanent native deadlock.
Observed GUI resource counts did not approach the usual per-process limit.

The dashboard previously refreshed the target chart every two seconds while
waiting for its child registration. The child was simultaneously creating
ControlsPlus objects. `CEdit::Create` reaches `CChartObject::Attach`, which calls
`ObjectFind`; that query waits for preceding chart commands. This is a plausible
interference path, not proof of an MT5 circular wait. A blank saved chart from a
running process does not prove that chart creation failed.

The narrow source change removes those refreshes, and omits agent-only
post-handshake focus/redraw sleeps. Human focus/navigation remains available.
It retains the same single template request, full chart-ID/magic handshake,
pre-launch dashboard persistence and partial-deployment refusal. It changes no
strategy, sizing, permission or AI policy. No binary or build ID is changed by
this source patch; compile and runtime qualification are separate release steps.

V1.48 demo startup records phase and checked control-failure diagnostics in
terminal-local `MQL5/Files/GOAT/Diagnostics/deployment_<chartId>.log`. They contain
UTC, tick counter, chart IDs, operation/control names and immediate error codes,
without account IDs, credentials or SET paths. Records append and flush, capped
at 4 MiB per chart; existing evidence is never truncated. A file write can itself
block or fail. Diagnostics are therefore best-effort evidence, not a watchdog.

The 20-second deadline bounds registration polling between returned calls only.
It cannot interrupt a blocked `ChartOpen`, template operation, redraw, synchronous
chart/object query or file I/O. The dashboard's regular timer still redraws its
own chart after processing controller work; removing attachment refreshes does
not establish general controller responsiveness. An event-driven attachment
state machine and independent watchdog would be a separate, larger change.

## Dashboard restart during an agent attach (B41.1)

From B41.1 the agent's `deploy_next` attaches a child asynchronously (goatai#1885
6027754245). The timer handler opens the chart, saves the child chart ID, copies the
template to `MQL5\Profiles\Templates\<member SET name>.tpl` and queues it, then returns.
Later timer ticks wait for the child's registration. From B41.2, while the row's handshake
is pending, every 2 s the tick also calls `ChartSetSymbolPeriod(cid, row symbol, row
timeframe)` and `ChartRedraw(cid)`. On T3 (B41.1, goatai#1885 6030127717), a template
queued on a newly opened chart was not applied in 76 s without such an update, although
the symbol was ticking. The registration wait lasts at most
`GOAT_AGENT_ATTACH_BUDGET_MS` (75 s). That is above the child's license startup, which
retries for up to 60 s inside `OnInit`, before the child writes its handshake. The
template is deleted only once the attach settles, either linked or timed out.

Inertness is checked again on every tick of the attach, not only when the request
arrives. Once Algo Trading is on, or a position or order is open, the attach is unwound
at the next tick, exactly like a timeout, and answers `rejected_not_inert`. Closing the
chart unloads a child that has not registered yet, so it cannot trade while the attach
is waiting. The receipt's schema is fixed, so the child's own positions and orders (by
its magic) are listed in the deployment diagnostics instead, as
`phase=not_inert_child_trades control=magic=<n> positions=<n> orders=<n>
tickets=p<ticket>,o<ticket>`. The magic reads `unknown` when the child had not written
its chart-ID record yet. Close or keep those trades in MT5 before running `deploy-stop`,
which refuses while anything is open.

On a timeout, or when the terminal is no longer inert, the dashboard unwinds the attach
the same way:

- it closes the child chart, but only while that chart still shows the row's symbol, and
  the close unloads a child that is still starting;
- it keeps the chart ID as the partial-deployment lock;
- it saves the row with the failed marker (`GOAT_ATTACH_FAILED_MAGIC`, magic `-2`) in
  place of any magic adopted early;
- it ignores status events from that chart, so the failed row never becomes a live
  member.

The marker is in the saved dashboard state, so it survives a restart. When the dashboard
loads, it closes a marked row's chart again, in case MT5 restored the chart with its
child. It does this only when the chart is provably our child: the GOAT EA runs on it,
and its chart-ID record and `SETUP_CID` handshake match the row. Otherwise it logs
`child_chart_not_ours` and leaves the chart alone, and the marker still keeps the row
from ever being adopted. The diagnostics log `child_chart_closed`,
`child_chart_close_failed`, `child_chart_not_found` or `child_chart_not_ours`. The in-flight attach itself (which row, which template, when it
started) lives only in the running dashboard EA.

If the dashboard EA stops in that window (MT5 closed or crashed, the EA reloaded, or
the chart closed), three things are left behind. This is accepted by design (goatai#1885
6028113003).

1. **A `started` receipt.** `GOAT\AgentPortfolio\<terminal>\<request id>.json` still
   reads `started`, because only the stopped session could have answered it. The EA
   never re-runs a request that already has a receipt. The controller refuses every
   further dashboard command with `An unresolved dashboard mutation is retained;
   inspect deploy-status before continuing`. `deploy-load` stops there and does not
   resume on its own.
2. **A partial row.** The child chart ID was saved before the template was queued,
   so after a restart the row has a chart ID but no linked child. `deploy_next` then
   answers `rejected_partial_deployment` before it opens a chart or queues a template.
   The chart itself may be bare. Or, if MT5 drained the queue before stopping, it may
   carry a child that started but was never linked. An attach that was in flight, and
   not yet failed, has no saved marker, so a new dashboard session can adopt such a child
   from its status events. It still cannot become a deployment: the `started` receipt
   blocks every command until `deploy-stop`.
3. **A leftover template** in `MQL5\Profiles\Templates`. When the saved dashboard loads
   again, `SweepStaleChildTemplates` deletes the template of every row that has a chart
   ID but no linked child, and logs `phase=stale_template_removed` in the deployment
   diagnostics. Anything the sweep cannot reach is still never applied: GOAT never
   queues a leftover on its own, and the file is not MT5's `default.tpl`, because GOAT
   names templates after member SETs. A later attach of the same member rewrites the
   file, by overwriting copy, before it queues the template. If that copy fails, the
   attach stops before any chart is opened. So a later session never queues stale
   bytes. `scripts/test_dashboard_async_attach.cjs` cases 8 to 10 pin this down.

**Recovery.** After a dashboard restart in the middle of an attach, run `deploy-stop`
before anything else.

Every step is controller-driven and keeps Algo Trading off. Nothing is deleted.

1. Run `deploy-stop` with a new attempt ID, before any other dashboard or deploy
   command. It closes MT5 normally once, and renames aside the saved dashboard state, the
   deploy chart profile, `request.json` and `registration.json`. A bare or unlinked
   child chart is therefore not reopened on the next launch, because its profile is
   archived. `deploy-stop` refuses if Algo Trading is on or there are open positions or
   orders. In that case stop here; the human decides what happens next.
2. Keep the evidence. Nothing in this step changes state. Save the `started` receipt and
   the request it answers (renamed aside, not deleted). In the newest
   `MQL5\Files\GOAT\Diagnostics\deployment_<dashboard chart id>.log`, the last
   `handshake_begin` without a matching `handshake_linked` or `child_attach_failed` is
   the interrupted attach.
3. The leftover template needs no manual step. A redeploy overwrites it before queueing,
   and the sweep removes it whenever that saved dashboard loads (see point 3 above). If
   the saved dashboard is never reloaded, a file can remain. It is harmless, and it may
   be renamed to `....tpl.stopped-<UTC stamp>` for tidiness.
4. Redeploy with `deploy-load` and a plan that has a new `deploymentId`. Each member is
   staged, copied and queued again from its hash-checked SET.

**Controller wait.** beta.23's controller waits 60 s for each `deploy_next` receipt.
From beta.23.1 (GOAT-EA#188) it waits 90 s, above the EA's 75 s attach budget, and the
request expires at 95 s. B41.1 ships only together with #188. On a beta.23 controller, an
attach that takes longer than 60 s ends deploy-load with `receipt_timeout`. Run
`deploy-load` again: it continues if the final receipt has landed. If the receipt still
reads `started`, follow the recovery above.

Source regression checks: `python -B scripts/test_goat_deployment_liveness.py`,
`node scripts/test_dashboard_async_attach.cjs` and its mutation check
`node scripts/test_dashboard_async_attach_mutations.cjs`.
These guard the removed interference, human navigation, identity and diagnostic
boundaries; they are not native execution tests. Before operational acceptance,
compile the reviewed source, qualify native attachment without enabling trades,
audit all children, and prove restart restoration. Preserve failed attempts and
inspect actual process exit before any separately authorized partial recovery.

Primary references: [Runtime error codes](https://www.mql5.com/en/docs/constants/errorswarnings/errorcodes),
[ObjectFind queue semantics](https://www.mql5.com/en/docs/objects/objectfind),
[ChartApplyTemplate asynchronous request semantics](https://www.mql5.com/en/docs/chart_operations/chartapplytemplate),
[ChartSetSymbolPeriod refresh semantics](https://www.mql5.com/en/docs/chart_operations/chartsetsymbolperiod).
