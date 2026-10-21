B47 (`V1.49-BETA17-47`) is B46 plus the items Claude-Mac raised when he approved B46 (GOAT-EA#244 at `93af5722`,
goatai#2350 6186931676). Base: `claude-pc/b46-orphan-fail-closed` at `93af5722`; the compile closure is B46's 41 files,
and only the entrypoint `GOAT V1.49.mq5` differs. The input header (contract pin) is unchanged. See **Build**.

- B47.1 A CID record maps its magic only while its chart is open in this terminal with an EA on it.
- B47.2 Claims carry a `TimeGMT` heartbeat (every 5 s from OnTimer); older than 180 s is unowned.
- B47.3 Under `cid_duplicate` the running sequence's adds (grid and rescue) are frozen; closes, stops and trailing run.
- B47.4 An unreadable claim refuses; it never counts as "no claim".
- B47.5 No claim is written while the login is 0.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-47`, marker `B47`.
- Compiled once from `ccb0a07` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`): 0 errors, 0 warnings
  (`Result: 0 errors, 0 warnings, 33539 ms elapsed`). A `/portable` copy outside every terminal folder (copied from the
  B46 compile, hash-equal), Idle priority; exit code 1 with a clean `Result:` line, as in B40-B46. Output written
  07:56:04Z, after the 07:55:30Z start. The stage (label `b47-20261015T075522Z`) was a scratch copy outside every
  terminal folder, moved off afterwards. Its include root (307 includes and `MACD - GOAT 2.ex5`) is hash-equal to the
  B46 compile root (308 files, 0 mismatches). Of the 44 staged files (41 sources, 2 PNG, ICO) only `GOAT V1.49.mq5`
  differs from the B46 stage; all 44 equal the source head. No terminal's runtime output was touched.
- One invocation, with only the path after each switch's colon quoted. It is the only compile.
- `GOAT V1.49.ex5`: sha256 `49fb34b037c24ffb54b98e77c9d156eea81ac1cfae69b6bbf61ae82185111a8d`, 2,485,858 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `390b7fcd…`, pinned in `controller/contracts/v149/dependencies.json`.
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B46's; bound to the receipt (`186fa6ba…`).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Deploy note (Claude-Mac, goatai#2350 6187450687): upgrade every terminal on one login together.** A B46 terminal
never re-stamps its claim, so from B47's point of view its claims go stale after 180 s. B47 terminals on the same login
then refuse new sequences (`orphan_suspected`) on every symbol they share with a B46 terminal, until all of that
login's terminals run B47. The refusal is the fail-closed design, not a fault, but a mixed B46/B47 login trades
nothing on its shared symbols.

**Known, for a later build (non-blocking per Claude-Mac 6187450687):**
- The "Sequence Levels Viewer" MessageBox blocks the chart thread. Left open for more than 180 s, it lets the chart's
  claim go stale, so other terminals refuse on that symbol. Replace it with a non-modal panel.
- After a symbol switch, a live chart still owns the old record that names it. Clear the old record on the switch.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-47`.
