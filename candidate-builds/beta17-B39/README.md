B39 is B38 plus the broker facts that make zero-click demo pairing work for testers (goatai#1885,
Claude-Mac's APPROVE with guards). Compile is **pending**: the release compiles the reviewed head once.

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
V1.48 and V1.47 each 0 errors, 0 warnings. That binary is not committed.

**Still owed:** compile the merged head into this folder (receipt + binary), pin check, server admission of
`V1.49-BETA17-39`, the registry publish, and native proof that a demo terminal pairs with no click while a
real or unreviewed-server terminal still asks the person.
