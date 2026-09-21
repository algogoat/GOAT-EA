# Agent-driven multi-terminal setup

## Implemented diagnostic contract

`scripts/goat_setup_status.py` inspects a local installation manifest and the
native activation observations in Common Files. It never starts terminals,
reads credential contents, changes permissions or enables trading.

```powershell
python scripts/goat_setup_status.py --installation installation.json --common-files '<MT5 Common Files>' --hash-installed-ea
```

The manifest lists `terminals`, each with an absolute `directory` and preferably
the expected `accountId`. The default observation age limit is 1,800 seconds;
use `--max-age-seconds` to narrow it. An installed binary hash is disk evidence,
not proof of the loaded program. An approved observation or a present credential
is not proof that the account is entitled or ready to trade.

The EA emits credential-free activation status per terminal. HTTP 429 backs off
15 minutes. Other permanent 4xx failures stop automatic requests. Start and poll
409 errors have different meanings. Activation-start requests share an exclusive
Common Files cooldown, reserved and read back before network IO. Invalid storage
halts requests rather than resetting the shared cooldown. Each chart writes a
unique temporary status file; the final terminal observation is last-writer data,
not an inventory of all charts. These behaviors need native multi-process tests
before a general release, in addition to the source regression tests.

## Supported setup sequence

1. Discover terminal paths, account identities, connection and position state.
2. Verify the exact EA artifact's release admission before requesting activation.
   Never claim an experimental binary is a different admitted release.
3. Check linked accounts, entitlement and account capacity. One user credential
   can serve multiple linked accounts; it does not grant unlimited account slots.
4. Obtain one legitimate portal approval, install its credential securely, and
   verify authenticated access separately for every account.
5. Verify native network access. A saved `common.ini` setting is not proof of
   runtime WebRequest permission. Do not repeatedly ask a user to change settings
   when the real failure is server admission or rate limiting.
6. Stage exact portfolio membership and effective settings, then verify child
   attachments, policy acknowledgements, AI feed readiness and capacity.
7. Keep trading disabled until setup validation and the user's launch instruction.

## Native setup command interface

`GOATSetupControl.mqh` is polled by the V1.47 dashboard timer, including activation
mode. It is disabled unless a valid local registration exists. The Python client
is `scripts/goat_setup_control.py`. Its manifest requires the exact installation
directory, broker account/server, build ID, installed EA SHA256 and Common Files
directory. Registration is valid for one hour and binds the full native data path;
equal directory basenames cannot authorize another installation.

The default schema-1 registration permits only `status` and `shutdown`. Shutdown requires a
connected demo account, AlgoTrading off and zero orders/positions. It does not
close trades, install credentials, change AI/exposure settings or enable trading.
Request and receipt IDs are retained. A pending request without a validated receipt
prevents a new request. Receipt acceptance does not prove shutdown completion;
inspect the exact process identity independently.

Native pilot verification on September 21: live status returned, wrong account,
wrong full directory and expired commands rejected, replay receipts unchanged,
native shutdown followed by process exit verified, normal restart restored the
dashboard and returned a fresh RPC status. Account remained connected, trading
disabled, zero positions/orders. This is not evidence of licensed initialization
or successful portfolio deployment. Source review and 32 Python setup tests passed.

### Pairing handoff candidate (not runtime-qualified)

The new source adds `register --allow-pairing-read`, an explicit schema-2 capability
limited to 15 minutes. `pairing` uses a schema-2 request and returns only the actual
pending public challenge, activation ID and expiry, bound to the same terminal,
account, broker and build. It requires connected demo, trading OFF and no exposure.
Status never includes pairing data; schema 1 cannot request it. A response expires
within 60 seconds and no later than its request, registration or activation.

The client validates the exact response and atomically replaces its stored pairing
payload with a code-free consumed receipt before returning it. Retain that receipt
to prevent replay. Interrupted clients can leave expired payloads or native temporary
files; these must not be reported as memory-only or fully cleaned up. The client
rejects expired responses, and the server independently expires pairing challenges.
Complete a bounded expired-payload cleanup policy before customer release.

The agent must compare native activation ID, build, expiry and account against the
portal's inspected request and recheck inert state before approval. Use the existing
authenticated inspect/approve flow; no auto-approval endpoint, private credential
export or build-ID substitution is provided. Private candidates stay in MT5.

Local checks cover the client capability, freshness, wrong identity, unexpected
payloads and consumed receipts, plus the actual native pairing predicate. They are
not a completed VPS pairing test. The published R9 currently installed on VPS does
not contain this command. A legitimate reviewed release/admission is still required
before this candidate can initiate its own pairing request.

## Persistent bootstrap

`scripts/mql5/GOATSetupBootstrap.mq5` is a one-shot demo setup script. It requires
the expected account, no positions/orders and trading disabled. It retains phase
receipts before creating a normal chart and applying the prepared dashboard
template. The disposable startup chart must not count as an existing persistent
dashboard. A retained receipt blocks blind repeats. The script requests orderly
native shutdown; the caller verifies exit and restoration using a normal launch.

The pilot proved a saved dashboard survives `/portable` restart without `/config`.
Do not repeat the bootstrap on each launch. Default common.ini `[StartUp]` edits
alone were not sufficient; retain the native-created profile. Custom startup
configuration is for the one-shot script only, not ongoing user operation.

## Remaining product work

Product requirement SETUP-001: [Secure agent-driven onboarding plan](SECURE-AGENT-ONBOARDING-PLAN.md).
One sign-in and scoped authorization must support agent-led setup without weakening
authentication, entitlement, native permissions or the separate trading launch gate.
The plan defines implementation phases and acceptance checks; it is not shipped capability.

This diagnostic patch is not an end-to-end provisioning controller. A unified
setup surface still needs full deployment phase receipts, supported permission setup,
account-link/capacity handling, one portal approval, per-account access probes,
deployment acknowledgement and restart recovery. Native WebRequest remains the
transport; no alternate DLL transport or allowlist manipulation was added.

Do not expose broker passwords, bearer tokens, pairing candidates or response
bodies in ordinary agent logs. Report redacted reasons and timestamps instead.
