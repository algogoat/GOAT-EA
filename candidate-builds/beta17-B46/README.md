B46 (`V1.49-BETA17-46`) is B45 plus the P1 Claude-Mac raised in his review of GOAT-EA#243 (B45 at `1cd2ca91`,
goatai#2350 6186284858). Base: `claude-pc/b44-blind-followup` at `1cd2ca91`; the compile closure is B45's 41 files, and
only the entrypoint `GOAT V1.49.mq5` differs. The input header (contract pin) is unchanged.

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
- Compile pending: no binary, receipt or `PINNED_BUILDS` row yet.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** the compile; Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-46`.
