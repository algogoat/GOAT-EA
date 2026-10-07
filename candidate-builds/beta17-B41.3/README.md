B41.3 is B41.2 (`../beta17-B41.2/README.md`) plus a NULL-safe expert check and attach diagnostics. It is a
**diagnostic-grade tester build for the T3 proof** (goatai#1885; Claude-Mac 6031532401). Deploy path only: there is no
trade-logic, input, default or SET-writer change.

**Why.** B41.2 failed natively on T3. It sent one refresh, then logged a false `attach_nudge_stopped expert=""`, and
the child EA never loaded.

- `ChartGetString(cid, CHART_EXPERT_NAME)` returns a **NULL string** (StringLen 0, error 0) on a chart with no
  expert. In MQL5, `NULL != ""` is true, which explains B41.2's false stop.
- A native experiment (`G:\GOAT-Build-Artifacts\claude-pc-ops\attach-mechanism-experiment\`, phase 2 included)
  found that MT5 loads a template's EA in every case we can reproduce: 17 + 6 arms, including an exact B41.2 replica
  launched the controller's way. **So the root cause is still unknown** and lies in the real dashboard or its launch.
  B41.3 records what the dashboard sees on every tick.

**What changes from B41.2**

| Where | What it does |
|---|---|
| `Dashboard.mqh`: NULL fix (ships regardless) | The refresh stops only when `StringLen(child_expert)>0 && child_expert==EA_Name_`, which is the dashboard's own EA name (`GOAT V1.49`, as the experiment measured). `ResetLastError` and `GetLastError` wrap the read. An EA put on the chart by MT5's default template does not count. |
| `Dashboard.mqh`: per-tick probe (permanent) | On every poll tick while the handshake is pending, the dashboard logs one short line to the deployment diagnostics: `phase=attach_probe control=t=<ms since enqueue> exists=<chart in ChartFirst/ChartNext> sym=<ChartSymbol> per=<ChartPeriod> en_len=<StringLen> en_null=<0/1> en_err=<error> en_ms=<call ms> tpl=<copied template present> nudges=<n>`. The `tpl` check uses `GetFileAttributesW` on the same `\\?\` path the copy and delete use; `FileIsExist` is not valid outside the sandbox. |
| `Dashboard.mqh`: `template_apply_result` (permanent) | Right after `ChartApplyTemplate`: `ok=<0/1> err=<GetLastError>`. |
| `Dashboard.mqh`: `attach_reapply_probe` (**T3 diagnostic only**) | Behind `#define GOAT_ATTACH_REAPPLY_PROBE 1` (ON in B41.3). If our expert is not on the chart 5 s after the template was queued, `ChartApplyTemplate` is re-issued **once**, with the explicit path `"\\Profiles\\Templates\\"+tplName`, and the result is logged as `ok=<0/1> err=<error>`. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-41.3`, marker `B41.3`, one `#define` each. |

The 2 s refresh (only while pending and until our expert is on the chart, using the stored chart period), the 75 s
budget, the per-tick inert check, the unwind, the failed marker, the on-load proof and the receipt are unchanged.

**`GOAT_ATTACH_REAPPLY_PROBE` is removed before beta.25** (Claude-Mac 6031532401). The one exception: if T3 proves
the re-apply is the fix, it becomes a designed, tested, bounded single retry instead.

**Reading a T3 run.** The `attach_probe` lines tell the failure modes apart:
- the chart disappearing (`exists=0`);
- the template file missing (`tpl=0`);
- `ChartGetString` stalling (`en_ms`) or failing (`en_err`);
- the expert never appearing (`en_null=1` throughout, refreshes still counting up).

`attach_reapply_probe` then shows whether a second apply with an explicit path loads the EA.

**Tests**

- `scripts/test_dashboard_async_attach.cjs` (28 cases). The model's `CHART_EXPERT_NAME` returns NULL on a chart with
  no expert, MT5's default template can put another EA on a new chart, and MT5 can silently drop a queued apply.
  - Case 24: a NULL expert never stops the refresh. The re-apply probe runs once at 5 s and the child attaches.
  - Case 25: only our EA's name stops the refresh.
  - Case 26: the probe-line format, one probe per pending tick, `template_apply_result`, and no re-apply probe
    when the expert loads early.
  - Case 27: the probe reports a removed template as `tpl=0` and a closed chart as `exists=0`.
- `scripts/test_dashboard_async_attach_mutations.cjs`: 55 of 55 mutants killed. They include B41.2's `x != ""`, a
  name-less check, the probe dropped, `tpl` or NULL misreported, a chart-list probe that is always true,
  `template_apply_result` dropped, and the re-apply probe dropped, repeated, or run while our expert is loaded.
- No-drift against B41 (`278ec109`): only `Dashboard.mqh`, `GOATPortfolioSetupControl.mqh` and
  `GOATPortfolioChildAudit.mqh` differ. The trade path is identical. Against B41.2 only `Dashboard.mqh` and the
  build-ID lines differ.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41.3`, marker `B41.3`. `GOAT_ATTACH_REAPPLY_PROBE` is ON (T3 diagnostic).
- Compiled once from `84a07aa2` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39 through
  B41.2): 0 errors, 0 warnings. The compiler was a copy outside every terminal folder, run `/portable` at Idle
  priority. MetaEditor's process exit code was 1 with a clean `Result:` line, as in the B40 and B41 compiles; the
  `Result:` line and the output are the success criteria. The stage was a scratch copy outside every terminal
  folder. Its 307 standard includes and the `MACD - GOAT 2.ex5` resource are copied from the B41 compile root and
  hash-equal to it. `externals.json` records the same per-name hashes as B41's, and the same `consumed_sha256`
  (`ced68559…`). The new `GetFileAttributesW` import is a `kernel32.dll` system import, compared by name, so it adds
  no hashed external.
- `GOAT V1.49.ex5`: sha256 `83967693e0e3ef9bd18c810faaac66672f4cf3228be83d370495e82797060c2d`, 2,441,904 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `cb434c9b…1facd7e`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `84a07aa2`: the 41 `.mq5`/`.mqh` files in the entrypoint's include closure are exactly the 41
  sources in `identity.json`, and each matches the tree and the staged copy. The input header is still `1408e1ee…`.
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.
- The retained B41.2 candidate (`../beta17-B41.2`) keeps its binary, which failed natively. Do not install it.

**Not done.** Native qualification has not been performed, and nothing was installed. The root `GOAT V1.49.ex5` is
unchanged.

**Controller.** B41.3 ships together with GOAT-EA#188 (beta.23.1, 90 s `deploy_next` wait).
