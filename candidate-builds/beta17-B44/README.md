B44 (`V1.49-BETA17-44`) is B43 plus the B44 items Claude-Mac approved on goatai#2350 (6126836633, 6126880655; item 11
in 6127147178) and his four conditions on GOAT-EA#227 (6127809765). Base: `codex/v148-research-planning` at `4329429b`
(#226 added `GOATDeployProfileWriter.mqh`, which nothing includes); the compile closure is B43's 41 files, and only six
differ. There is no item 8. See **Build**.

**What changes from B43**

| Item | Where | What it does |
|---|---|---|
| 1 Child magic | `GOAT V1.49.mq5:243-286` (`GoatChildMagicCandidate`, `GoatChildMagicHeld` `:252`, `GoatDeriveChildMagic` `:273`), `:3679`; `GOATPortfolioSetupControl.mqh:167` | A new live child's `MAGIC1` comes from `ChartID()` alone and steps on while the candidate is held: by another chart's CID record, or (condition 3) by an open position or pending order of the account. A magic restored from the chart's own CID record still wins. Adoption names a held magic once: `magic_held`. |
| 2 AI wire retry | `GOATAIWireV2.mqh:709-729`, `:935` | After a failed or unverified live fetch, retry at 30 s, 60 s, 120 s, ... (capped at the refresh interval) plus a fixed per-chart jitter. Verified refresh and the tester are unchanged. |
| 3 Child adoption refusals | `GOATPortfolioChildAudit.mqh:246-336`, `:338`; `GOATPortfolioSetupControl.mqh:212`, `:234` | The snapshot audit streams the saved template with no whole-file 65,536-line / 8 MB cap; the whole tag structure is checked, only the `<expert>` block is audited. Adoption names `snapshot_too_large`, `snapshot_nul` or `snapshot_unreadable`. |
| 4 AI gate log | `GOAT V1.49.mq5:2351`, `:6492`/`:6497`, `:6527`/`:6532`, `:5585` | Print only, live only: `GOAT AI gate v1: decision=VETO\|ALLOW side magic symbol direction probability cutoff authority availability reason code wire_read_at mode protocol`. Trading unchanged (tested against B43's `SignalEntryTrigger`). |
| 5 BlindExport | `GOAT V1.49.mq5:2834` (input), `:2865-2962`, `:3116`, `:4528`, `:4546`, `:4846`, `:5023`, `:5422`; `GOATPortfolioChildAudit.mqh:190` | Input `BlindExport=false`, declared last (WriteSet never writes it). On, the export is blind (condition 1): its file name (`_Trds _Prf _DD _PF _SR _ARF`), so the exporter's record and AdjustLots, and its SET header are fit+FWD only; the header keeps only the BOOS, SAMPLE and FWD window lines plus `; EXPORT: blind=1 ranked=fit+fwd sr=daily_ann` and a `; RANKED:` line. A changed FOOS gives byte-identical name and content, lots included. Off: `; EXPORT: blind=0 ranked=full_span sr=mt5_stat`, otherwise unchanged. |
| 6 Trace cap | `GOAT_SequenceExport.mqh:26`, `:52`, `:282`, `:437`, `:485` | No 2,000,000-row stop. Past 1,000,000 rows the minute marks go to every 5 minutes; deals and event frames stay complete; recorded as `marks_downsampled` and `marks_interval_changed_at`. The controller's readers take it unchanged. |
| 7 Licence retry | `GOATLicenseInitRetry.mqh:20-73`, `GOAT V1.49.mq5:2399`, `:3513` | Already present since `5e7a5cc`; now pinned for V1.49 and in CI. No EA change. |
| 9 Panel and Alerts | `GOAT V1.49.mq5:2999`, `:3486`, `:7656`, `:7671`, `:5261`; `:21` and `:7893-7910` | Panel creation tried 3 times; then headless (`panel_unavailable`) instead of `INIT_FAILED`. Every `Alert()` in the compile closure goes through `GoatDeployNotice` (deploy mode: Print plus a journal line). Condition 4: `scripts/test_alert_guard.cjs` walks the closure in include order and fails on any `Alert(` outside the redirection. |
| 10 HWND | `GOAT V1.49.mq5:3682` | No `ChartWindowsHandle` read left in the entrypoint; no 4102 retry needed. |
| 11 Mailbox share | `GOATSetupControl.mqh:27`; `scripts/lint_ea_mailbox_share.py` | Mailbox reads no longer lock request.json against the controller (FILE_SHARE_READ). Lint `EA-MAILBOX-SHARE-01`. |
| Condition 2 | `controller/studio_deploy_profile.py:112`; `GOATDeployProfileWriter.mqh:197` (not in the closure) | Both deploy writers drop the `; EXPORT:` stamp line, so a stamped B44 SET deploys byte for byte as its B43 twin. Identity (values, canonical hash, fingerprint) never depended on comment lines. |
| Build | `GOAT V1.49.mq5:22`, `:37`; `controller/contracts/v149/dependencies.json`; `controller/studio_installed_build.py` | Build ID `V1.49-BETA17-44`, marker `B44`; main pin follows, header pin unchanged; `PINNED_BUILDS` names this binary. |

**Not changed.** The input header (`1408e1ee…`), every other closure file, `WriteSet`, Astra's inputs, the trade-event
policy and the model route. On the trade path only item 1 changes what a new live child draws as its magic.
`scripts/test_b44_no_drift.cjs` pins it.

**Native check owed for item 9.** A separate test build with `#define GOAT_PANEL_FAIL_INJECT` on a demo terminal (never a
release): the journal shows three `panel_retry` lines and `panel_unavailable`; `link_children` adopts the child; it
opens its sequence when the signal fires; closing the terminal completes without a modal window.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-44`, marker `B44`.
- Compiled once from `bfbb3e13` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`): 0 errors, 0 warnings
  (`Result: 0 errors, 0 warnings, 34955 ms elapsed`). A `/portable` copy outside every terminal folder, Idle priority;
  exit code 1 with a clean `Result:` line, as in B40, B41 and B43. Output written 16:14:05Z, after the 16:13:29Z start.
  The stage (label `b44-20261012T161325Z`) was a scratch copy outside every terminal folder, moved off afterwards; its
  307 includes and `MACD - GOAT 2.ex5` are hash-equal to the B43 compile root (308 files, 0 mismatches). No terminal's
  runtime output was touched.
- `GOAT V1.49.ex5`: sha256 `b730c935f58ebb2f36db655909f2726be6b0040e337ac55bd6722bb69175cdcf`, 2,462,648 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `e7c1a2c7…`, pinned in `controller/contracts/v149/dependencies.json`.
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B43's; bound to the receipt (`0afd231e…`).
- Superseded: `b44-20261012T154732Z` (`7a91ee97…`, before the conditions; never admitted) and `b44-20261012T154547Z`
  (1 error, then a dry run). MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-44`; the item 9
native check above.
