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

Source regression checks: `python -B scripts/test_goat_deployment_liveness.py`.
These guard the removed interference, human navigation, identity and diagnostic
boundaries; they are not native execution tests. Before operational acceptance,
compile the reviewed source, qualify native attachment without enabling trades,
audit all children, and prove restart restoration. Preserve failed attempts and
inspect actual process exit before any separately authorized partial recovery.

Primary references: [Runtime error codes](https://www.mql5.com/en/docs/constants/errorswarnings/errorcodes),
[ObjectFind queue semantics](https://www.mql5.com/en/docs/objects/objectfind),
[ChartApplyTemplate asynchronous request semantics](https://www.mql5.com/en/docs/chart_operations/chartapplytemplate),
[ChartSetSymbolPeriod refresh semantics](https://www.mql5.com/en/docs/chart_operations/chartsetsymbolperiod).

## Open question: the dashboard's own template applies (do not re-add)

From October 2026 (beta.25, build `V1.49-BETA17-43`) children are no longer attached
with `ChartApplyTemplate`. The controller writes them into the staged deploy profile,
and MT5 loads them at start-up. The dashboard only adopts the children it finds
(goatai#1885 6033175337, approved in 6033450916). The template path described above
(`ApplyTemplate`, `BuildTemplate`, the copied template and the agent's `deploy_next`)
is deleted, not kept dormant: `deploy_next` now gets the refusal
`rejected_deploy_next_retired`, and the dashboard's Activate and Deploy All buttons show
"Use Next in the app to deploy; dashboard deploy returns in the next update".

The reason is recorded here so the old path is not re-added. On T3 (V1.49 builds
B41.1 to B41.3, October 6-7, 2026), every `ChartApplyTemplate` that the GOAT
dashboard program issued for a child returned success, and MT5 never performed it:
the child chart stayed bare. Every other caller tested in the same terminal loaded
the same GOAT template in 3 ms to 1.9 s. That included scripts, a diagnostic EA,
a template-loaded EA, and a diagnostic EA running next to a live dashboard
(`attach-mechanism-experiment\phase4`, goatai#1885 6033149769). So a running
dashboard does not block templates. Only applies issued by the dashboard program
itself fail. V1.48-R1 applied children from the dashboard successfully on
September 23, 2026, with a different child ex5.

**The cause is unknown.** The untested candidates are the dashboard applying a template whose
expert is its own (large, protected) ex5, and the exact production template name.
Until a native experiment explains it, do not add any path where the dashboard
applies a template to a chart (agent deploy, human Deploy All or Activate, or a
diagnostic). Children reach charts only through a profile that MT5 loads.

Evidence, all read-only and on the Claude-PC build share (`G:\GOAT-Build-Artifacts\claude-pc-ops\`):

- `attach-mechanism-experiment\`: the caller matrix (phases 2 to 4, `arm-summary.csv`,
  journal excerpts and `SHA256SUMS.csv`). `results\saved-native-E1.tpl` is MT5's save of
  a script-applied BuildTemplate `.tpl` on T3.
- `b41-3-t3-proof\`: the B41.3 deploy-load on T3 that ended in `child_attach_failed`
  (`03-deploy-load.out.json`) and its deploy-stop.
- On T3 itself, `MQL5\Profiles\Charts\GOAT-Deploy-56a46a8a85a446b9.stopped-20261006T235344Z\chart02.chr`
  is a B41 child chart (its `id=` is that deployment's TSV cid) that MT5 saved with no
  expert: MT5's own record of the failure.
- algogoat/GOAT-EA#186 (B41.1 to B41.3: asynchronous agent attach, pending-chart
  refresh, attach diagnostics) is superseded by beta.25 and closed without merging.
  Only its settingsMatch exemptions (CA41, `4f3f2f9`) were ported.
