# Management-only R4 qualification (R5, R6 and R2)

Follow-up to backend goatai #1669 and EA PR #21. This document supersedes the R3
candidate's AI behavior, build scope and retry timing. **Draft, not released.**

## Exact build scope

`scripts/build_management_variants.py --output <new-directory>` reconstructs each
original source tree and applies the current, assertion-checked management delta.
It refuses missing/ambiguous anchors. It never installs or starts a terminal.

| Original | Pinned source | Candidate build ID |
|---|---|---|
| V1.47 R5 | `5e7a5cc0a6da997bf2a1ff9bd07ff169ae90ec68` | `V1.47-ASSET-SEQUENCE-GUARD-R5-MANAGEMENT-R4` |
| V1.47 R6 | `5b5ce7a268c970e13ce4d1ea52391e9278253525` | `V1.47-ASSET-SEQUENCE-GUARD-R6-MANAGEMENT-R4` |
| V1.48 R2 | `6705df944f0354f397b403bb3b53431de4c9cd54` | `V1.48-DASHBOARD-AI-PAIR-R2-MANAGEMENT-R4` |

The repository's V1.48 entrypoint is identical to the generated R2 entrypoint.
Historical binaries remain unchanged. New binaries need their own explicit
server admission; these IDs must never impersonate the original admission.
Each variant keeps its original credential namespace. No credential rotation or
re-pairing is performed here. Each manifest records the original revision and
generated main hash; the review manifest separately pins shared source hashes alongside compile receipts.

## Failure behavior

| State | Existing owned positions | New positions / positive additions |
|---|---|---|
| Boot pending, missing/rejected auth | Restore and manage to exit | Blocked |
| Entitlement expired or explicitly revoked | Continue configured management | Blocked |
| Backend down, timeout, malformed reply, HTTP429/5xx | Continue configured management | Blocked on observed failure; no failure grace |
| Build revoked/denied | Manage to exit, no forced liquidation | Blocked |
| Authorization recovers | Continue configured management | Eligible without reinit, subject to existing strategy controls |
| AI stale/unavailable while auth is healthy | Existing AI and non-AI behavior retained | **Existing AI policy retained**, including configured sequence-start-only scope |
| AI protocol self-test fails | Management remains active | Blocked; integrity failure shown |
| Checkpoint invalid/missing or volume mismatch | Degraded broker-fact recovery | Blocked until uncertain basket is flat |

The requested change does **not** alter AI bias entry decisions, confidence,
threshold, scope, transport timeout or refresh scheduling. Each variant's
`GOATAIWireV2.mqh` is compared to its original source. R3's additional feed-freshness
gate and network scheduling change have been removed. Auth rejection blocks all
new risk regardless of the AI policy; an AI-only outage is a different condition.

Trading charts skip auth-driven activation-only initialization and complete
ordinary initialization/recovery. Strategy-parameter or unrelated native resource
errors still fail initialization. Management handlers, final positive sends,
sequence starts and negative-lot unwinds have separate gates. Management never
adopts another magic or another symbol. Broker disconnection cannot execute an
exit; broker SL/TP remain at the broker while client management retries normally.

Chart/log status is `MANAGEMENT-ONLY: <reason>`. Auth starts pending, with no saved
authorization grace. Initial polling is staggered 1–4 seconds. Failed attempts
back off 5, 10, 20, 40, 80, 160, then 300 seconds (plus <1 second chart jitter).
Successful polling resets the backoff, refreshes every 30–40 seconds and grants
at most 45 seconds of monotonic entry permission. Expired permission blocks the
final send even if timers stall. Revocation is observed through polling, not an
instant push channel. The bearer reader and HTTPS endpoint are unchanged.

There is no compiled calendar expiry in any generated target. The legacy date
remains only in historical, non-management include branches for unreleased old
entrypoints. Runtime permission freshness is separate from calendar build expiry.

## Recovery limitation and rollout

The old R5/R6/R2 binaries did not save full sequence checkpoints. A new binary
cannot reconstruct lost virtual levels, historical ATR sizing or realized partial
exit history from standing broker tickets. First migration must therefore occur
flat, with no virtual sequence, **after the week's cumulative trade/signal export**.
Weekend alone is insufficient when positions remain. Do not close experiment
positions just to install this change.

Future checkpoints bind account, broker server, symbol, chart, magic and inputs;
they include the real sequence state and are checked against broker tickets and
volumes. Missing/mismatched state is labelled degraded, never called exact recovery.
Crash gaps, offline partial fills and all exit variants still need native demo
qualification before a universal exact-continuation claim is justified.

An EA reload is required. Vince coordinates a flat maintenance window after the
export; Claude reviews the code/release. Preserve each original binary, profile,
SET and magic, approve each new artifact, qualify on an isolated demo first, then
update matched ON/OFF arms together and record an experiment version boundary.
Do not change AI/exposure/sizing settings. Verify input hashes and runtime build,
management mode, authorized recovery and account identity after reload. Rollback
is also a coordinated flat-account operation. **This PR does not deploy.**

## Repeatable verification

```
node scripts/test_management_boot.cjs
python scripts/test_management_variants.py
```

The portable suite currently passes 59 production-function simulations per
variant (177 across R5/R6/R2), plus licensing, activation, credential namespace,
dashboard and direction-guard regressions. It covers auth recovery/backoff,
revocation, stale permissions, owned loss exits and trailing, checkpoint binding
and IO failures. It is not an MT5 execution emulator.

`prepare_management_native_test.py` generates a separate **tester-only** binary.
It refuses attachment outside Strategy Tester. MT5 disallows WebRequest in the
tester and cannot retain positions between separate tests, so this harness injects
the auth transport, allows tester identity in recovery, and calls the production
initialization/management code around a simulated reinitialization. Orders,
position selection, checkpoint IO and closes use native MT5 execution. It never
qualifies a cold terminal restart or a real broker fill. The production binaries
have no test transport or authorization override.

Retain the test-only binary/source hash, full agent journal, inputs and result.
Count only explicit `NATIVE_ASSERT PASS` and the final zero-failure summary; a
terminal exit code or MT5's generic “test passed” message is insufficient. Retain
failed setup attempts separately. Live expert trading remains disabled in the
isolated tester terminal. Do not copy its test binary to a demo or customer folder.

Remaining release gates: isolated demo cold restart in each failure state with
actual open positions; trailing, break-even, partial/basket/time exits; mid-session
recovery with real new-entry execution; healthy baseline trade equivalence; final
independent reviewer approval. No experiment account may serve as the test fixture.

## September 25 native evidence

All three production candidates compiled with MetaEditor 5.0.0.6182, zero errors
and zero warnings. All three separately compiled tester-only harnesses passed
six cases each: server down, rejected, pending, entitlement expired, revoked and
healthy. **18 native cases, zero assertion failures.** Production initialization
returned success with owned positions; real tester orders closed through MLPS;
failed authorization prevented final positive sends; recovered authorization
restored permission without a second initialization. These deliberately losing
fixtures test exits, not strategy profitability.

The original R2 and candidate production binaries were additionally tested on
EURUSD M1 OHLC, September 14–19, 2026, with identical inputs. Their ten native
deal records (five round trips) matched exactly, including timestamps, direction,
volume and price. Both ended at 100012.32 USD from 100000 USD. This establishes
that bounded tester comparison only: tester auth bypass means it is not a live
healthy-auth equivalence test, and AI was disabled in this comparison.

Review artifacts, hashes and assertion extracts are in
`review-builds/management-r4`. Full evidence is retained on the operator machine
under `G:/GOAT-Build-Artifacts/management-only-boot-20260924/native-evidence`
and `healthy-evidence`. The isolated terminal was stopped and its copied broker
credential store removed. No experiment terminal, binary, settings, API credential
or open broker position was changed. No native demo cold-restart evidence exists
yet; the requested separate demo account identity is still outstanding.
