# Repeatable demo connection

`scripts/goat_demo_connection.py` and `scripts/Connect-GoatDemo.ps1` replace
hard-coded account/password login snippets. Run them on the terminal host,
locally or through authorized SSH. This is a connection stage, not an installer.

Qualification: contract tests, real Windows process/hash preflight, broker login,
and encrypted-provider reconnection after an owned local restart passed on
September 24. Fresh inspect verified the exact demo account, server and data
path, Algo OFF, and zero positions/orders. This qualifies the connection stage
on the tested Windows host, not production EA initialization or deployment.

## Scope

Use an explicitly owned, already-running, isolated demo setup terminal with Algo
Trading disabled. Do not switch accounts on a terminal managing positions or
trading EAs. Pin its current executable hash, PID and creation time. The helper
does not deliberately launch, stop, restart, install, attach EAs, enable trading
or submit orders. SDK initialization can launch a terminal if it exits during
attachment; identity checks before and after detect that race, not prevent it.

Install the official MetaTrader5 Python package on Windows. `--sdk-path` can
select a directory containing an already-installed private copy. Every expected
account/server/currency/margin-mode value must come from the intended setup.

Example **nonsecret** manifest; replace all example identities before use:

```json
{
  "schemaVersion": "goat-demo-connection-v1",
  "purpose": "isolated-demo-setup",
  "directory": "C:/GOAT Demo/Control",
  "account": 123456,
  "server": "Broker-Demo",
  "loginServer": "Broker-Demo",
  "currency": "USD",
  "marginMode": 2,
  "credentialRole": "investor",
  "symbols": ["EURUSD"],
  "terminalSha256": "REPLACE_WITH_ACTUAL_SHA256",
  "process": {"pid": 1234, "startedUtc": "REPLACE_WITH_CURRENT_UTC_TIMESTAMP"}
}
```

Margin mode 2 is retail hedging; the tool verifies, never converts it. Investor
role requires account trading permission false; trader requires it true. Both
require DEMO, terminal Algo OFF, the exact account/server/data path and zero
orders/positions. There is no fallback between password roles.

## Commands

Check ownership and disk bytes without contacting the broker:

```powershell
python -B scripts/goat_demo_connection.py preflight --manifest connection.json --receipt preflight-01.json
```

Observe an already connected terminal using its saved login; no password is
passed and Market Watch is unchanged:

```powershell
python -B scripts/goat_demo_connection.py inspect --manifest connection.json --receipt inspection-01.json
```

For initial authorized login, use PowerShell 7 and a current-user DPAPI store:

```powershell
./scripts/Connect-GoatDemo.ps1 -Manifest connection.json -Receipt connection-01.json -CredentialStore 'C:/Private/demo-credentials.dpapi' -Python 'C:/Python/python.exe'
```

The encrypted store is a `ConvertFrom-SecureString` encoding of a JSON array
with `login`, `masterPassword` and/or `investorPassword`. Provision it securely
outside Git, accessible only to the operating user and SYSTEM. Current-user
DPAPI is host/user bound; copying it to a VPS does not make it decryptable there.
The wrapper selects exactly one account and one explicitly requested role and
sends `{account, role, password}` through child stdin. No password is put in
argv, logs, terminal configs or receipts. Never put credentials in manifests,
chat, scripts or shell command text. Clearing references is not guaranteed
erasure from managed runtime memory. Other secure providers can supply the same
stdin envelope; do not add a password command-line option.

## Results and recovery

- `preflight_passed`: process and disk executable only; no login claim.
- `connected_inert_demo`: live identity/connection/flat-account/Algo OFF checks
  passed. Connect also selects and verifies each requested symbol is visible.
  EA readiness and portfolio deployment still need separate proof.
- `native_attach_failed`, native code `-6`: broker rejected the login. Verify
  platform, server and broker-issued credential. Do not retry automatically or
  silently change credential role.
- Timeout, missing readback, process drift or unexpected exception: inspect
  native journals, process and current account before recovery. A retained lock
  blocks another attempt even with a new receipt filename.

Receipts are created exclusively. Final results replace the retained intent
only after a separate file is flushed. Authentication is attempted once. The
per-terminal `GOAT-demo-connection.lock` is released automatically only after a
verified inert connection or explicit credential rejection; ambiguous failures
remain blocked. Preserve the receipt and archive an owned lock only after its
outcome has been reconciled. A new receipt name is not retry authorization.

After connection, use the native setup controller for activation and registered
portfolio controller for attachment and input audit. Require exact membership,
effective policy acknowledgements and restart proof. See [the runbook](NATIVE-CONTROLLER-RUNBOOK.md).

## September 24 lesson

The user later supplied the broker-issued credentials. One bounded attempt
connected successfully. The encrypted provider then reconnected after an owned
preview restart; a separate inspect confirmed the resulting native state.
The corrected credentials were stored in a separate restricted DPAPI vault,
preserving prior failed evidence. The historical failures below are superseded
for the verified AI account; the replacement control account remains unverified.

Darwinex's website confirms both new accounts as MT5 demos. The local control
account's stored investor password was rejected using both known server names;
its stored trader password was rejected too. The previous VPS success involved
different accounts. Neither the website listing nor the terminal title proves
authentication. No dashboard readiness receipt was produced. Resolve connection
before claiming a loaded portfolio or changing account security settings.

The user subsequently authorized a reset. Darwinex's form enforced an 8–20
character limit; a four-character-class candidate passed local validation, but
the website returned **Password change failed**. One explicit MT5 verification
with that staged candidate returned `-6` as well. The encrypted current vault was
not replaced. Do not treat a submitted form or dismissed dialog as reset success.
Keep a replacement credential encrypted and separate until broker confirmation
and native login agree; preserve the previous encrypted credential for recovery.
This is observed Darwinex behavior, not a universal password rule for brokers.
