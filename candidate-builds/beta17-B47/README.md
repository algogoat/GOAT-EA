B47 (`V1.49-BETA17-47`) is B46 plus the items Claude-Mac raised when he approved B46 (GOAT-EA#244 at `93af5722`,
goatai#2350 6186931676). Base: `claude-pc/b46-orphan-fail-closed` at `93af5722`; the compile closure is B46's 41 files,
and only the entrypoint `GOAT V1.49.mq5` differs. The input header (contract pin) is unchanged.

- B47.1 A CID record maps its magic only while its chart is open in this terminal with an EA on it.
- B47.2 Claims carry a `TimeGMT` heartbeat (every 5 s from OnTimer); older than 180 s is unowned.
- B47.3 Under `cid_duplicate` the running sequence's adds (grid and rescue) are frozen; closes, stops and trailing run.
- B47.4 An unreadable claim refuses; it never counts as "no claim".
- B47.5 No claim is written while the login is 0.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-47`, marker `B47`.
- Compile pending: no binary, receipt or `PINNED_BUILDS` row yet.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** the compile; Claude-Mac's review of this binary and pins; a new admission row for `V1.49-BETA17-47`.
