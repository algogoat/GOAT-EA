# Child deployment startup investigation

September 24, 2026: two separate child attachments failed on an inert demo
terminal. The first recorded a successful license check followed by a panel
creation failure. The second had no completed child initialization in the
available buffered journal. Its failed deployment receipt was produced before
later controller requests timed out. Neither establishes one common root cause.
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

Primary references: [ObjectFind queue semantics](https://www.mql5.com/en/docs/objects/objectfind),
[ChartApplyTemplate asynchronous request semantics](https://www.mql5.com/en/docs/chart_operations/chartapplytemplate),
[ChartSetSymbolPeriod refresh semantics](https://www.mql5.com/en/docs/chart_operations/chartsetsymbolperiod).
