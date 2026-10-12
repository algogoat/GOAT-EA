B44 (`V1.49-BETA17-44`) is B43 plus the B44 items Claude-Mac approved on goatai#2350 (6126836633, 6126880655; item 11
in 6127147178). Base: `codex/v148-research-planning` at `c708cae4`, whose compile closure is B43's (`e38791d6`) byte for
byte. There is no item 8. See **Build**.

**What changes from B43**

| Item | Where | What it does |
|---|---|---|
| 1 Child magic | `GOAT V1.49.mq5:243-276` (`GoatChildMagicCandidate`, `GoatChildMagicHeld`, `GoatDeriveChildMagic`), `:3621`; `GOATPortfolioSetupControl.mqh:167` | A new live child's `MAGIC1` comes from `ChartID()` alone and steps on while another chart's CID record holds it (never 0). A magic restored from the chart's own CID record still wins. Adoption names a held magic once: `magic_held`. Exp 03 (2026-10-12): two children drew the same `MathRand()+9+ChartWindowsHandle(0)` with HWND 0. |
| 2 AI wire retry | `GOATAIWireV2.mqh:709-729`, `:935` | After a failed or unverified live fetch, retry at 30 s, 60 s, 120 s, ... (capped at the refresh interval) plus a fixed per-chart jitter (a hash of the chart id). Verified refresh and the tester are unchanged. |
| 3 Child adoption refusals | `GOATPortfolioChildAudit.mqh:246-336` (`GoatChildAuditExpertBlock`), `:338`; `GOATPortfolioSetupControl.mqh:212`, `:234` | The snapshot audit streams the saved template with no whole-file 65,536-line / 8 MB cap: the whole tag structure is still checked, only the `<expert>` block is kept and audited. Adoption names `snapshot_too_large`, `snapshot_nul` or `snapshot_unreadable` (and `magic_held`, item 1) instead of a silent `child_unmatched`. |
| 4 AI gate log | `GOAT V1.49.mq5:2345` (`GoatGateLog`), `:6432`/`:6437`, `:6467`/`:6472`, `:5525` | Print only, live only: `GOAT AI gate v1: decision=VETO\|ALLOW side magic symbol direction probability cutoff authority availability reason code wire_read_at mode protocol`. VETO at the `Sequence_Skipped_Bias_*++` onset sites, ALLOW when the signal starts a sequence. Fields are the wire state after the demo-raw rewrite. Trading unchanged (tested against B43's `SignalEntryTrigger`). |
| 5 BlindExport | `GOAT V1.49.mq5:2828` (input), `:2859-2938`, `:3058`, `:4486`, `:4786`, `:4963`, `:5362`; `GOATPortfolioChildAudit.mqh:190` | Input `BlindExport=false`, declared last (append-only; WriteSet never writes it; the input header is unchanged). On: the export run measures the fit+FWD (SAMPLE) window and writes `; EXPORT: blind=1 ranked=fit+fwd` and a `; RANKED:` line; the profit floor, SR, ARF and the SetsToExport trim use it. Off: `; EXPORT: blind=0 ranked=full_span`, otherwise byte-identical (StartExporter and RunAndStoreSet minus the B44 lines are B43's). |
| 6 Trace cap | `GOAT_SequenceExport.mqh:26`, `:52`, `:282`, `:437`, `:485` | No 2,000,000-row stop. Past 1,000,000 rows the minute marks go to every 5 minutes; deals and event frames stay complete; recorded as `marks_downsampled` and `marks_interval_changed_at`. Controller fixture `controller/test_studio_trace_marks_downsampled.py`: the readers take it unchanged. |
| 7 Licence retry | `GOATLicenseInitRetry.mqh:20-73` (`:47`), `GOAT V1.49.mq5:2393`, `:3455` | Already present since `5e7a5cc`: at init, up to 3 retries in 60 s for 5xx/408/429/1003 and WebRequest 5201-5203, and a 5xx or -1 never counts as "not licensed". Now pinned for V1.49 and in CI. No EA change. |
| 9 Panel and Alerts | `GOAT V1.49.mq5:2941` (`GoatPanelCreate`), `:3428`, `:7596`, `:7609`, `:5201`; `:21` and `:7833-7850` (`GoatDeployMode`, `GoatDeployNotice`) | Panel creation tried 3 times (250 ms, 500 ms); then the chart stays alive headless (`panel_unavailable`) instead of `INIT_FAILED`. Every `Alert()` in the compile closure goes through `GoatDeployNotice`: in deploy mode a Print plus a journal line, never a modal window. |
| 10 HWND | `GOAT V1.49.mq5:3624` | No `ChartWindowsHandle` read is left in the entrypoint (the tester magic is `MathRand()+9`; the unused `MAGIC2` is no longer seeded). The HWND dependency is gone, so no 4102 retry is needed. |
| 11 Mailbox share | `GOATSetupControl.mqh:27`; `scripts/lint_ea_mailbox_share.py` | Mailbox reads no longer lock request.json against the controller (FILE_SHARE_READ). Lint `EA-MAILBOX-SHARE-01`. |
| Build | `GOAT V1.49.mq5:22`, `:37`; `controller/contracts/v149/dependencies.json` | Build ID `V1.49-BETA17-44`, marker `B44`; the main pin follows the entrypoint, the header pin is unchanged. |

**Not changed.** The input header (`1408e1ee…`, SM32's), every other closure file (only the six above differ from
B43), `WriteSet`, Astra's inputs, the trade-event policy and the model route. On the trade path only item 1 changes
what a new live child draws as its magic; items 4, 5 and 6 measure or log; item 9 changes only what happens when the
panel or an Alert would have stopped a chart. `scripts/test_b44_no_drift.cjs` pins it.

**Native check owed for item 9.** Compile a separate test build with `#define GOAT_PANEL_FAIL_INJECT` on a demo
terminal (never a release). Stage one child with it: the journal shows three `panel_retry` lines and
`panel_unavailable`; `link_children` adopts it; it opens its sequence when the signal fires; closing the terminal
completes without any modal window.

**Tests.** `test_child_magic_unique.cjs`, `test_ai_wire_retry.cjs`, `test_child_snapshot_stream.cjs`,
`test_ai_gate_log.cjs`, `test_blind_export.cjs`, `test_trace_marks_downsample.cjs`, `test_license_init_retry.cjs`,
`test_panel_headless.cjs`, `test_lint_ea_mailbox_share.py`, `test_b44_no_drift.cjs`, the adoption harness and its
mutations, `test_portfolio_child_audit.cjs`, and `controller/test_studio_trace_marks_downsampled.py`.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-44`, marker `B44`.
- Compile pending.
