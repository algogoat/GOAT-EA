B46 (`V1.49-BETA17-46`) is B45 plus the P1 Claude-Mac raised in his review of GOAT-EA#243 (B45 at `1cd2ca91`,
goatai#2350 6186284858). Base: `claude-pc/b44-blind-followup` at `1cd2ca91`; the compile closure is B45's 41 files, and
only the entrypoint `GOAT V1.49.mq5` differs. The input header (contract pin) is unchanged. See **Build**.

- B46.1 A missing CID record fails closed. An open position or pending order on `Symbol()` with a GOAT magic other than
  the chart's own, that no valid CID record of this terminal maps and no other terminal on this login has claimed,
  refuses new sequences (`orphan_suspected`, with the magics and tickets) until it is resolved.
- B46.2 A duplicate CID record fails closed. Two CID records for this chart and symbol, or one naming a magic other than
  the chart's own, refuse new sequences (`cid_duplicate`) instead of `GoatFindMagicByCid`'s first match.

Both refuse at `DashboardEntryAllowed` only (new real or virtual sequences, virtual-to-real promotion); adds, trailing,
stops, MLPS and closes of running sequences are untouched. Shown as a `GOAT CID guard v1:` journal line, on the panel
and as the dashboard row status. Live charts only: tester, optimization and forward passes never evaluate it.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-46`, marker `B46`.
- Compiled once from `ae2e9b3` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`): 0 errors, 0 warnings
  (`Result: 0 errors, 0 warnings, 33900 ms elapsed`). A `/portable` copy outside every terminal folder (copied from the
  B45 compile, hash-equal), Idle priority; exit code 1 with a clean `Result:` line, as in B40, B41, B43, B44 and B45.
  Output written 07:20:12Z, after the 07:19:37Z start. The stage (label `b46-20261015T071920Z`) was a scratch copy
  outside every terminal folder, moved off afterwards. Its include root (307 includes and `MACD - GOAT 2.ex5`) is
  hash-equal to the B45 compile root (308 files, 0 mismatches). Of the 44 staged files (41 sources, 2 PNG, ICO) only
  `GOAT V1.49.mq5` differs from the B45 stage; all 44 equal the source head. No terminal's runtime output was touched.
- One invocation, with only the path after each switch's colon quoted. It is the only compile.
- `GOAT V1.49.ex5`: sha256 `33d81ad7e3a1f7e4a68654d7fba721bdb43704369e75590f59504ab5aa2e17bd`, 2,480,720 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `3a1c137e…`, pinned in `controller/contracts/v149/dependencies.json`.
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B45's; bound to the receipt (`6b82d719…`).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-46`.
