B45 (`V1.49-BETA17-45`) is B44 plus the follow-ups Claude-Mac raised in his review of GOAT-EA#227 (B44 at
`9d48236b`). Only the entrypoint `GOAT V1.49.mq5` differs from B44; the compile closure is B44's 41 files and the input
header (contract pin) is unchanged.

- B45.1 BlindExport window parity with `controller/studio_window_metrics.py` `equity_metrics`: the window opens on the last
  equity before it (B44: the first tick inside it), each Mon-Fri day returns on its close carried forward (B44: each
  day's first tick), ARF over the window's Mon-Fri days. `scripts/test_blind_export.cjs` runs the Python reference.
- B45.2 Blind outputs are BOOS-free: no BOOS line in a blind SET, and the window is measured on the equity less the
  BOOS P/L, so no return or ARF denominator holds a BOOS result. `trd_FOOS` counts from `dt_Fwrd_OOS` (`>=`), the
  RANKED window's bound (B44: `>`, so an entry at that second was counted in `trd_IS`).
- B45.3 Blind + AdjustLots: the blind file name's `DD` is the drawdown over every non-FOOS tick, never the window's
  alone, so AdjustLots can no longer size a blind export larger than its non-FOOS history allows.
- B45.4 Child magic salt: `GoatChildMagicSalt()` = account login + hash of `TERMINAL_DATA_PATH`, so two terminals on
  one login loaded from one saved profile (same `id=` chart ids) no longer draw the same magic. A chart with a CID
  record restores its magic before any derivation, so a running child keeps its magic and its open positions.

**Compile: pending.** `identity.json` has `binary: null` and `compile: pending`; no binary or receipt is implied and
`PINNED_BUILDS` has no B45 row. The documented EA compile stages into a terminal data folder under
`%APPDATA%\MetaQuotes`, which this follow-up was not allowed to touch. The compile, receipt, `externals.json`, the
binary pin and Claude-Mac's review of them are still owed. Not installed, no native qualification.
