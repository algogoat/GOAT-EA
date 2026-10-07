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
Later timer ticks wait for the child's registration, for at most
`GOAT_AGENT_ATTACH_BUDGET_MS` (75 s). That is above the child's license startup, which
retries for up to 60 s inside `OnInit`, before the child writes its handshake. The
template is deleted only once the attach settles, either linked or timed out.

When the attach settles, inertness is checked again. If Algo Trading was switched on, or
a position or order opened, a child that registered is not kept: the attach answers
`rejected_not_inert` and is unwound exactly like a timeout.

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
child. The diagnostics log `child_chart_closed`, `child_chart_close_failed` or
`child_chart_not_found`. The in-flight attach itself (which row, which template, when it
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

**Controller wait.** beta.23's `deploy-load` waits 60 s for each `deploy_next` receipt,
but an attach can take up to 75 s. If it times out with `receipt_timeout`, run
`deploy-load` again. If the final receipt has landed by then, deploy-load continues. If
the receipt still reads `started`, follow the recovery above. A controller that waits
90 s (the maximum its request validation allows) removes this case.

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
