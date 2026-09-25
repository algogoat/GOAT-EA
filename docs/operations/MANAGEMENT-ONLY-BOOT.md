> Historical R3 record. The current R4 scope, unchanged AI policy, three-build backports and qualification status are in [MANAGEMENT-ONLY-R4-QUALIFICATION.md](MANAGEMENT-ONLY-R4-QUALIFICATION.md). This document does not establish release readiness.

# V1.48 R3 management-only boot — review candidate

Follow-up to [backend authorization PR1669](https://github.com/algogoat/goatai/pull/1669).
Target: `GOAT V1.48.mq5`, build `V1.48-MANAGEMENT-BOOT-R3`. This is an EA change:
installing the binary and reinitializing the affected charts **is required**.
No terminal has been reloaded or deployed by this PR.

## Runtime contract

Trading charts finish initialization and restore their owned sequences before
requesting authorization. Authentication does not return `INIT_FAILED`, remove
the trading EA, start credential replacement, or put that chart into activation-only
mode. The existing Dashboard/Studio activation workflow remains the pairing route.
Invalid strategy parameters and unrelated native initialization failures remain errors.

| Condition | Existing owned positions | New sequences and positive additions |
|---|---|---|
| Missing/rejected credential, HTTP401 | Manage to exit | Blocked; credential preserved |
| Entitlement expired/denied, including HTTP200 `no` | Manage to exit | Blocked |
| Auth service unavailable, timeout, malformed response, rate limit | Manage to exit | Blocked when observed; no failure grace |
| AI feed missing, stale, unverified or unavailable | Non-AI exits/trailing/partial exits continue; no exit invented from a missing AI signal | Blocked for an active AI filter, including start-only AI scope |
| Build denied/revoked by the authorization endpoint | Manage to exit; no forced liquidation or `ExpertRemove` | Blocked |
| Authorization and required AI feed recover | Same strategy rules | Eligible again, subject to all existing strategy, risk, dashboard and exposure controls |

AI-OFF and display-only AI do not require a feed to authorize entries. Neutral or
below-threshold **available** AI remains subject to the existing direction/threshold
policy. Demo-raw authority retains its existing demo-only, verified-wire restrictions.
Revocation/entitlement denial share a generic denial response; the chart does not
pretend to know which server-side policy rejected it.

“Manage” means continue attempting the configured management actions. MT5 must
remain running, the broker must accept requests, AutoTrading/EA trading permission
must allow them, and charts must retain the correct strategy identity. A lost broker
connection cannot execute client-side exits; existing broker SL/TP remain at the broker.
No global switch, licensing outage or missing feed in this implementation deliberately
disables the management handlers. The entry guard covers the final `OpenPosition`
path as well as new sequence generation. Risk-reducing negative-lot unwinds remain
before the positive-exposure gate. Uncertain legacy recovery is the exception below.

## Fresh authorization and network timing

No authorization grant is loaded from disk. Startup is management-only. The first
timer poll is staggered 1–4 seconds; subsequent polls are staggered 30–40 seconds
per chart. Each success must be exactly HTTP200 with the current account's
`<id> - yes` body. The current bearer reader and HTTPS endpoint remain unchanged.
A successful in-memory grant lasts at most 45 seconds and refreshes automatically.
A failed refresh clears it immediately. Account/server drift also blocks entries.
This is a renewable runtime permission check, not a build-expiry date.

Revocation is enforced on the next observed denial; this client does **not** have
push revocation. Under normal timer delivery the observation interval is 30–40
seconds. If timers are delayed, the final send guard rejects an overdue grant.
The backend must keep entitlement and build-approval checks separate, as in #1669.
The existing bearer-to-admission binding is still the server authority: the EA does
not claim its build-ID string is cryptographic binary attestation.

Trading initialization performs no licensing network retry loop. Management runs
before timer-side auth/AI refresh; each request has a 1-second requested timeout.
AI retrieval in the tick handler reads verified cached state without making a new
network request. MT5 WebRequest is synchronous: up to two requested seconds of
network waiting per refresh cycle remain possible, plus native scheduling latency.
There is no claim of zero latency. A native slow-network rehearsal is a release gate.
Timer-driven management cannot open trades against a stale quote.

The compiled calendar expiry is removed from V1.48 and its selected input branch.
Historical versioned mains and binaries are not rewritten or backported.

## Restart state and limitations

R5/R6/R2 recovered a magic/chart binding but did not persist the complete in-memory
sequence. R3 checkpoints each real sequence's levels, ticket IDs, sizing arrays,
trailing/retrace state and partial-close/rescue ledger. The terminal-local
`MQL5/Files/GOAT/Recovery/<identity hash>.state` is scoped to account, server,
symbol, chart and magic. It is bound to the inputs, SHA256 checked, size bounded,
written through a temporary file, flushed, replaced and read back. Do not edit it.
No credentials or cached permission grants are included.

Checkpoint writes occur after management changes and orderly deinitialization;
unchanged state does not rewrite disk. A write/readback failure blocks new exposure
but leaves management active. Never overwrite a checkpoint from a disconnected
broker view. Broker identity/connection recovery is retried without failing EA init.
Restoration checks ticket ownership, direction and standing volume before use.

**First migration and crash-gap limitation:** older binaries have no complete
checkpoint. A missing/corrupt/input-mismatched checkpoint or an offline volume
change cannot recreate vanished virtual levels, historic ATR sizing or realized
partial-close history exactly. The fallback recovers broker-owned tickets and
existing SL/TP, configured loss/session exits, and trailing using current sizing;
it blocks new exposure and level additions until the uncertain basket is flat.
It does not invent retrace levels or a realized ledger. This is explicitly degraded
recovery, not proof of identical continuation of the old sequence. Virtual-only
sequences are not resumed. A crash between a fill and durable checkpoint can also
enter this fallback. Exact crash/partial-fill reconciliation is a remaining release
qualification concern; do not advertise this candidate as a universal recovery guarantee.

Chart text displays `MANAGEMENT ONLY / <reason>` and logs state transitions.
The dashboard child status also reports Management Only. `RECOVERY_REVIEW_REQUIRED`
identifies a degraded basket; it must not be mistaken for a licensing problem.

## Validation

Run from the repository root:

```text
node scripts/test_management_boot.cjs
node scripts/test_v148_credential_namespace.cjs
node scripts/test_license_init_retry.cjs
node scripts/test_activation_retry.cjs
node scripts/test_direction_guard.cjs
```

The management test executes production MQL functions through explicit syntax
adaptation with deterministic MT5 adapters. For each requested failure state it
serializes an open buy/sell sequence, recreates it after simulated restart, verifies
entry denial and executes the production MLPS exit and trailing modification paths.
It also exercises storage failures, stale grants, account drift and input integrity.
These tests are not native terminal, broker-fill or full OnInit/OnTick integration tests.
Compile evidence is retained outside the repository under the management-boot artifact
folder. The final candidate compiled with MetaEditor 5.0.0.6182: **0 errors, 0 warnings**.
The 60 management simulations and related regression suites passed. Candidate EX5
SHA256: `d6ceb3fafb1066f3293be8acea304381f3fec6a5cdb02212f8a1ede76c7e1435`. A clean native compile is necessary but is not a native restart rehearsal.

Before release, on an isolated demo with the exact candidate binary:

1. Capture inputs, chart/magic bindings, checkpoint and broker ticket state for a
   multi-level long and short, including partial-retrace and rescue configurations.
2. Independently inject missing credential, rejected auth, expired entitlement,
   auth timeout/5xx, stale/missing AI, and revoked build. Keep the broker connection
   available so exits can actually execute. Use a test server/admission, not the
   experiment credentials or live backend policy.
3. Restart cold in each state. Verify INIT_SUCCEEDED, owned ticket restoration,
   Management Only text, unchanged settings, no new orders/adds, and actual SL/TP,
   trailing, partial-close, session and loss exits as their triggers are reached.
4. Repeat with disk-write failure, corrupt checkpoint, partial fill immediately
   before termination, broker reconnect and an offline partial/full exit. Verify
   documented degraded behavior and no accidental ownership adoption.
5. Restore authorization/feed; verify automatic recovery, unchanged AI ON/OFF and
   exposure policy, and no entry during a timer-only management pass.

**This native rehearsal has not been performed by the PR author. Keep the PR in
draft and do not release until it passes or the remaining limitations are resolved.**

## Coordinated experiment rollout

Claude reviews this PR and the server-side release; Vince coordinates EA binary
rollout. This document is a plan, not deployment authorization.

1. Land/verify the persistent backend migration first. Explicitly approve R3's
   artifact and plan legitimate credential/admission binding migration. Never
   reuse a different account's bearer or edit its expiry/digest in place.
   The R3 source preserves the V1.48 credential namespace; the six R5/R6 terminals
   have a different legacy namespace. Audit each actual path/binding and use a
   reviewed account-specific migration before authorizing entries. No silent re-pairing.
2. Complete the isolated native rehearsal above and archive source/compiler/binary
   hashes. Preserve each existing EA binary/profile for rollback.
3. Schedule after the relevant markets close, preferably a weekend **when every
   affected account is flat and has no active virtual sequence**. Weekend alone
   is insufficient if positions remain open. Do not force-close experiment trades
   just to install. If necessary defer that paired arm's rollout until flat.
4. Export the cumulative experiment data and snapshot every SET, chart/magic,
   account/arm, AI threshold/protocol, direction filter and sizing value. Record
   the transition time as a new experiment version segment.
5. Under Vince's release coordination, update matched ON/OFF arms in the same
   maintenance window. Reinitialize the charts once, preserve their identity and
   settings, and verify all children, permissions and backend identity. Never mix
   versions within a pair and treat the result as a clean AI-only comparison.
6. Inspect runtime mode and checkpoint receipts before the next market open.
   Compare full settings to the pre-upgrade snapshots. Resume the same experiment
   policies; do not opportunistically retune or replace portfolios.
7. Roll back only under the same flat-account guard. An older binary cannot read
   R3's checkpoint and retains its original expiry/startup limitation. Preserve
   failure evidence and new checkpoints; do not blindly replace a managing binary
   while it holds positions.

This PR does not merge, publish, install, reload, re-pair, change trading settings,
or activate any account. The candidate is stacked on the V1.48 dashboard branch;
its prerequisite PR must be reconciled before a main-branch release.
