B39 is B38 plus the broker facts that make zero-click demo pairing work for testers (goatai#1885,
Claude-Mac's APPROVE with guards). Compiled once from `a56febe8` (the #136 merge plus the #138 controller fix,
which touches no EA source); see **Build**.

**What changes from B38**

| Where | What it does |
|---|---|
| `GOATEADeviceActivation.mqh` | `GOATBrokerFactsTradeMode()` maps `ACCOUNT_TRADE_MODE` to `demo`, `contest` or `real` (anything unknown is `real`). `GOATBrokerFactsJson()` builds `{source?, tradeMode, server}` with the existing JSON quote helper. `device/start` now sends `brokerFacts: {source: "ea-device-start", tradeMode, server}`. |
| `GOAT V1.49.mq5` | The license check (`/api/ea/check`) sends `brokerFacts: {tradeMode, server}` next to `id`, so the server can compare every later start of this EA with the facts an agent approval stood on. Build ID `V1.49-BETA17-39`, marker `B39`. |

Payload only: no trading, risk, sizing, order, trade-event, AI-wire, model-route or input-header change.
The input header is still SM32's (`1408e1ee…`), so SM32 batch packages stay valid.

**Server side** (goatai `claude-pc/broker-facts-server`): an agent may approve only `tradeMode == demo` on a
reviewed demo server (`Darwinex-Demo`, `MetaQuotes-Demo`, exact names). A later license check that reports
another trade mode or server revokes an agent-approved credential, records an alert and holds the login for
the person's own pairing. The server must be deployed before this build is admitted; an older server
ignores the nested `brokerFacts` and keeps every pairing manual.

**Verified here:** MetaEditor 5.0.0.6230 compile of a staged copy outside every terminal folder: V1.49,
V1.48 and V1.47 each 0 errors, 0 warnings. That review binary is not committed.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-39`, marker `B39`.
- Compiled once from `a56febe8` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B38):
  0 errors, 0 warnings. The stage was a scratch copy outside every terminal folder; its standard includes and
  the `MACD - GOAT 2.ex5` resource are hash-equal to Terminal 2's, which B38 compiled against.
- `GOAT V1.49.ex5`: sha256 `27226cfb61c02d066c7eabc0a598b0762b0ed055752ea9f14c5a7e2a01d5f517`, 2,417,426 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `f82f5800…81fc4c`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `a56febe8`: all 41 sources in `identity.json` match the tree and the staged copy; the input
  header is still `1408e1ee…`. #138 changed only controller Python files, so no source or dependency pin moved.
  The sanitized `compile-receipt.json` is in this folder.
- MetaEditor output is not byte-reproducible across stages: an earlier compile of the same sources from
  `e222b9cc` (`94ce0bb1…`) is superseded and must not be admitted.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:** server admission of `V1.49-BETA17-39` (after the broker-facts server is deployed), the registry
publish, and native proof that a demo terminal pairs with no click while a real or unreviewed-server terminal
still asks the person.
