B44 (`V1.49-BETA17-44`) is B43 plus the B44 items Claude-Mac approved on goatai#2350 (6126836633, 6126880655; item 11
in 6127147178) and his four conditions on GOAT-EA#227 (6127809765). Base: `codex/v148-research-planning` at `4329429b`
(#226 added `GOATDeployProfileWriter.mqh`, which nothing includes); the compile closure is B43's 41 files, and only six
differ. There is no item 8. See **Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-44`, marker `B44`.
- Compiled once from `7469846` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`): 0 errors, 0 warnings
  (`Result: 0 errors, 0 warnings, 35297 ms elapsed`). A `/portable` copy outside every terminal folder, Idle priority;
  exit code 1 with a clean `Result:` line, as in B40, B41 and B43. Output written 16:33:40Z, after the 16:33:05Z start.
  The stage (label `b44-20261012T163301Z`) was a scratch copy outside every terminal folder, moved off afterwards; its
  307 includes and `MACD - GOAT 2.ex5` are hash-equal to the B43 compile root (308 files, 0 mismatches). No terminal's
  runtime output was touched.
- `GOAT V1.49.ex5`: sha256 `31f800057e303970b0c7fddf1f7289c53504545e8c36be9dadaed2af0b370b7a`, 2,462,300 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `0bd7512c…`, pinned in `controller/contracts/v149/dependencies.json`.
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B43's; bound to the receipt (`5f20f41a…`).
- Superseded or withdrawn, never admitted: `b44-20261012T163055Z` (`dcce2ba1…`, a comment cut short),
  `b44-20261012T161325Z` (`b730c935…`, before the key:value stamp), `b44-20261012T154732Z` (`7a91ee97…`, before the
  conditions), `b44-20261012T154547Z` (1 error, then a dry run). MetaEditor output is not byte-reproducible across
  stages, so admit only this binary.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-44`; the item 9
native check above.