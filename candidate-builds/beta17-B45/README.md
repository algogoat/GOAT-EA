B45 (`V1.49-BETA17-45`) is B44 plus the follow-ups Claude-Mac raised in his review of GOAT-EA#227 (B44 at `9d48236b`).
Base: `claude-pc/b44-magic-wire-retry` at `9d48236b`; the compile closure is B44's 41 files, and only the entrypoint
`GOAT V1.49.mq5` differs. The input header (contract pin) is unchanged. See **Build**.

- B45.1 BlindExport window parity with `controller/studio_window_metrics.py` `equity_metrics`: the window opens on the last
  equity before it, each Mon-Fri day returns on its close (carried forward), ARF over the window's Mon-Fri days.
- B45.2 Blind outputs are BOOS-free: no BOOS line in a blind SET, the window measured on the equity less the BOOS P/L;
  `trd_FOOS` counts from `dt_Fwrd_OOS` (`>=`), the RANKED window's bound.
- B45.3 Blind + AdjustLots: the blind file name's `DD` is the drawdown over every non-FOOS tick.
- B45.4 Child magic salted with the account login and a hash of `TERMINAL_DATA_PATH` (`GoatChildMagicSalt`); a chart with
  a CID record restores its magic first, so running children keep their magic and their open positions.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-45`, marker `B45`.
- Compiled once from `ac02183` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`): 0 errors, 0 warnings
  (`Result: 0 errors, 0 warnings, 34673 ms elapsed`). A `/portable` copy outside every terminal folder (copied from the
  B44 compile, hash-equal), Idle priority; exit code 1 with a clean `Result:` line, as in B40, B41, B43 and B44. Output
  written 06:40:24Z, after the 06:39:48Z start. The stage (label `b45-20261015T063839Z`) was a scratch copy outside every
  terminal folder, moved off afterwards. Its include root (307 includes and `MACD - GOAT 2.ex5`) is hash-equal to the B44
  compile root (308 files, 0 mismatches). Of the 44 staged files (41 sources, 2 PNG, ICO) only `GOAT V1.49.mq5` differs
  from the B44 stage; all 44 equal the source head. No terminal's runtime output was touched.
- A first invocation (06:39:14Z) quoted each switch whole and was not a compile: MetaEditor exited 0 with no log and no
  output. The compile above is the only one.
- `GOAT V1.49.ex5`: sha256 `666eee58f118fe91bda50eaf79942341d0a72d163aee7d59766b08cb76cd1024`, 2,465,104 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `06aa70a1…`, pinned in `controller/contracts/v149/dependencies.json`.
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B44's; bound to the receipt (`faea2277…`).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-45`.
