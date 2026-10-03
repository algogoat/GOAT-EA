LC36 is an inert forward V1.49 candidate. It is MH34 (Studio monitor setup mailbox host, PR #112, on EX33 and SM32) plus one change:

- **Local pairing read** (`GOATEADeviceActivation.mqh`). While MT5 shows a pending connection code on a
  demo account, the EA writes that code to `GOAT\activation-code-<data folder>.json` in this Windows
  user's Common Files: `schema`, `accountId`, `server`, `buildId`, `activationId`, `userCode`,
  `expiresAtMs`, `observedAtUtc` and `chart`. It is written atomically right after the card shows the
  code and withdrawn (this chart's record only) as soon as the code is cleared, expires, is approved or
  the chart closes, including on the read-only Studio monitor. `studio pairing-code` (GOAT-EA #111) reads
  it first, so the desktop and its agent get the code without a screenshot and without a Portfolio
  Dashboard or monitor chart answering the setup mailbox.
- It is the short-lived public challenge the card already shows, never the credential candidate. It is
  never printed or logged, never in a URL, and reaches GOAT's server only through the existing
  `device/inspect` call. Real-money accounts and the Strategy Tester never write it. The operational
  `activation-status-*.json` file is unchanged and still carries no code.

No trading, risk, sizing, order or controller wire behaviour changes. The pinned input header
(`GOAT_Inputs_Definitions.mqh`) is SM32's, unchanged by EX33, MH34 and LC36, so SM32 batch packages stay valid.

Its `GOAT_BUILD_ID` is `V1.49-LOCAL-PAIRING-CODE-36`, with marker `LC36` (MH34 is #112, FU35 is #122).
`identity.json` binds the exact forward source. **Compiled** from `49e7f359` with MetaEditor 5.0.0.6230 (0 errors, 0 warnings):
`GOAT V1.49.ex5` sha256 `59325061…` (2,397,574 bytes) with its sanitized `compile-receipt.json`.
Native qualification has NOT been performed. The new build ID needs server admission before activation.

LC36 supersedes `setup-monitor-host-MH34`, which stays retained unchanged (compile pending, never compiled
on its own), as do EX33, SM32, SM31 and SP30. The root `GOAT V1.49.ex5` and all installed artifacts
remain unchanged. Compilation does not qualify native use: exact-head review, isolated native
DEMO/owner/STOP/Algo-off qualification and a separately reviewed customer delivery remain required.