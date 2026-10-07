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
Later timer ticks wait for the child's registration, for 20 seconds at most. The
template is deleted only once the attach settles, either linked or timed out. The
attach state lives only in the running dashboard EA.

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
   The chart itself may be bare, or, if MT5 drained the queue before stopping, it may
   carry a child that started but was never linked.
3. **A leftover template** in `MQL5\Profiles\Templates`. GOAT never queues it
   again on its own, and it is not MT5's `default.tpl`, because GOAT names templates
   after member SETs. A later attach of the same member rewrites the file, by
   overwriting copy, before it queues the template. If that copy fails, the attach
   stops before any chart is opened. So a later session never queues stale bytes.
   `scripts/test_dashboard_async_attach.cjs` cases 8 to 10 pin this down.

**Recovery.** Every step is controller-driven and keeps Algo Trading off. Nothing is
deleted.

1. Run `deploy-status`. Note the deployment ID, its phase, and the rows with
   `linkedFresh` false. Save the `started` receipt and the request it answers, as
   evidence. Then look at the newest `MQL5\Files\GOAT\Diagnostics\deployment_<dashboard
   chart id>.log`: its last `handshake_begin` without a matching `handshake_linked` or
   `child_attach_failed` is the interrupted attach.
2. Check that the terminal is inert (Algo Trading off, no positions or orders). Then
   run `deploy-stop` with a new attempt ID. It closes MT5 normally once and renames
   aside the saved dashboard state, the deploy chart profile, `request.json` and
   `registration.json`. This also means a bare or unlinked child chart is not reopened
   on the next launch, because its profile is archived.
3. Optional: archive the leftover template. Rename
   `MQL5\Profiles\Templates\<member SET name>.tpl` to `....tpl.stopped-<UTC stamp>`.
   This is not required for safety (see point 3 above).
4. Redeploy with `deploy-load` and a plan that has a new `deploymentId`. Each member is
   staged, copied and queued again from its hash-checked SET.

If `deploy-status` shows the terminal still running with Algo Trading on, or with open
positions or orders, stop here. `deploy-stop` refuses in that state, and the human
decides what happens next.

Source regression checks: `python -B scripts/test_goat_deployment_liveness.py` and
`node scripts/test_dashboard_async_attach.cjs`.
These guard the removed interference, human navigation, identity and diagnostic
boundaries; they are not native execution tests. Before operational acceptance,
compile the reviewed source, qualify native attachment without enabling trades,
audit all children, and prove restart restoration. Preserve failed attempts and
inspect actual process exit before any separately authorized partial recovery.

Primary references: [Runtime error codes](https://www.mql5.com/en/docs/constants/errorswarnings/errorcodes),
[ObjectFind queue semantics](https://www.mql5.com/en/docs/objects/objectfind),
[ChartApplyTemplate asynchronous request semantics](https://www.mql5.com/en/docs/chart_operations/chartapplytemplate),
[ChartSetSymbolPeriod refresh semantics](https://www.mql5.com/en/docs/chart_operations/chartsetsymbolperiod).
