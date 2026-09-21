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

### Internal R2 portfolio setup candidate

`scripts/goat_portfolio_setup.py` adds a separate opt-in registration under
`GOAT/AgentPortfolio/<terminal>/`. It binds the installed EX5, full terminal/account
identity, exact ordered Common Files SET hashes and AI/exposure policy. Commands
are `configure`, `deploy_next`, `apply_policy`, `status` and `audit`. Registration
and request issuance share an exclusive producer lock; retained native mutation
intent prevents blind reissuance after interruption. Rejections exit nonzero.

The controller operates portfolio rows already loaded into the dashboard. It
does not import arbitrary folders, enable trading, send orders or close positions.
Mutations require a connected demo with trading OFF and no orders/positions.
`deploy_next` attaches one pending row through the existing UI handler; any partial
child identity stops further deployment. Child binding checks symbol and full
chart identity, not just the first pending registration. Common Files paths are
normalized before native sandbox file access.

`audit` saves each existing child chart's template to a unique local temporary,
compares the actual expert and complete effective input map against the frozen
SET bytes, then removes only that owned temporary. It exposes a boolean, not input
contents. UTC child observations bound freshness even if broker ticks stop.
`verify_ready` additionally requires every policy ACK, effective child AI inputs
and fresh verified AI state on AI arms. A valid withheld directive need not allow
a trade. Dashboard mode0 means **As Optimized**; the experiment requires observed
Mode_Bias1 before labeling such an arm AI OFF.

This section describes the candidate contract. Native installation, full child
audits, account access, restart and resource checks remain separate evidence.
Passing Python/source tests or compiling is not deployment readiness.

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

## R3 explicit persistent dashboard resume

`Dashboard_Resume_Saved` defaults to false. Set it to true on an intentionally prepared dashboard chart to resume its existing saved state without confirmation dialogs. It requires the dashboard to be the first chart and saved state to exist; otherwise initialization fails with a journal reason. It never closes other charts, opens the SET selector, deletes state or resets tracking. Manual startup remains unchanged when false. Children must keep this input false; the complete input audit verifies that default even for older SET exports.

This is a startup choice, not portfolio validation. Preserve source/effective SET hashes and verify all expected children, account identity, policies and actual inputs before enabling trading. Do not require a flat account or disabled trading merely to resume an already deployed portfolio after a later restart.

Observed setup defects: the R2 native dashboard blocked on chart-order and saved-state dialogs after license verification; the operator recovered only six verified inert demo processes and preserved their profiles before removing empty non-EA charts. The R3 change addresses saved-state prompts; first-chart ordering is still a required prepared-profile property. Native R3 qualification remains pending.

Separate activation follow-up: same-symbol/timeframe `ChartSetSymbolPeriod` did not reinitialize the activated EA in this pilot. A stored credential and successful queueing are not proof of initialized runtime. Use the verified orderly terminal restart and fresh native status. Future onboarding should expose a truthful restart-required state and automatically orchestrate safe restart, preserving existing position management; do not toggle chart timeframe or recursively call OnInit.
