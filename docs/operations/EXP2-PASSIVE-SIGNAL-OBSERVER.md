# Exp 02 passive signal observer — proposed source only

This internal build is based on exact R2 source `14ada7104a82052f7f966da4f7b745890781d553`.
It has not been installed, used natively or deployed. Exact-head Claude approval
is required before those operations. Existing R2, A1/BD28, the frozen local
campaign and desktop release bytes remain unchanged.

The observer is a no-op on real accounts and in Tester, optimization and forward
testing. On the live DEMO runtime it appends local `MQL5/Files/GOATExp2Signals/*.csv`.
It records each false-to-true indicator-side conjunction edge at the existing
signal-entry evaluation, using independent observer state per strategy, symbol
and side. A true condition held for multiple ticks writes one gate row; a false
evaluation resets that side. Repeated evaluations keep the episode ID for later
actual order joins without repeating gate or no-order records. Trading signal
flags and counters are untouched. It uses the gate booleans/state consumed by the
existing minute update. It does not call GetState, WebRequest, OrderSend or
HistoryDealSelect. It does not alter any gate, risk, size, order argument, return
value or global control. A file-write failure reports a logging failure and never
returns into a trading decision. File I/O adds latency and can affect platform
error diagnostics; source tests do not establish runtime equivalence.

When the entry evaluator is not called (for example paused or Friday/December
outer gates), no false observation is invented. A true signal across that gap is
one episode; this can undercount but cannot inflate observed signal episodes.

AI TAKE/VETO is derived from the already-consumed wire's verification,
availability, actionability and indicator-side direction. Combined bias flags
can also include rescue suppression; `non_ai_suppression=BIAS_RESCUE_ACTIVE`
records that separately, including when the AI itself would TAKE. Such a record
is not an executable counterfactual. The actual combined gate is not changed.
The signal gate row also records `combined_bias_allowed`, the actual raw
Sequence_New_Bias_B/S boolean passed by the EA. Derived-permission disagreement
can therefore be counted in both directions; neither value changes trading.

The separate proposed timing change changes only DEMO HTTP503 failure cooldown to
60 seconds. Retry runs at the first existing minute/tick evaluation at or after
that elapsed interval; tickless runtime has no exact wall-clock retry guarantee.
Every attempt still clears old state, and failed state remains unverified. Other
HTTP, authentication, transport, parse and verification failures keep the compiled
10-minute policy. No new input, timer, wire schema, model or permissive fallback is
added. This may recover valid permission earlier; it does not enable failed wire.
The EURJPY1003 origin remains unproven and its cadence is unchanged.
The shorter cooldown is behind the experiment entrypoint-only
`GOAT_EXP2_DEMO_503_NEXT_MINUTE` compile define. Older entrypoints including the
shared wire header retain their original retry behavior on future rebuilds.

Any approved native rollout must land the same build on BOTH Exp02 DEMO arms
before the preregistration boundary2026-10-05T00:00Z, with dated per-arm change-log
entries and first CSV-row readbacks. If that cannot happen, hold native rollout
for a separately agreed boundary amendment. This is separate from the unchanged
local1518 campaign deadline. No real-account install or use is permitted.

`TAKE`, `VETO` and `NO_WIRE` describe the AI gate permission. Control records TAKE
with `CONTROL_AI_DISABLED`; that does **not** mean other entry gates passed or a
trade filled. News blocking is explicit; later exposure, sequence, side, opposite
sequence, spread, stop and volume gates remain in their original order. A signal
with no OrderSend result records `NO_ORDER_SEND_OBSERVED`. Other blocks must not
be counted as causal Astra vetoes. Existing bias-rescue state can also suppress
the bias gate. The observer does not recompute those conditions.

Order-result records distinguish accepted sends from fills. Deal-add records
use the deal the original callback already selected and join via the observed
order/position handles. Partial exits with magic zero can join a logging-era
opening position. Unjoined pre-existing orders/positions remain unjoined.
The current frozen 35 members all have Delay_Trade=0 and Reverse_Seq=false;
delayed/virtual starts outside the immediate signal context remain unjoined.
Fill rows do not attribute the current wire cache to a past signal. Only the
signal-gate row holds the already-consumed lean/probability/authority/read/expiry.
Wire freshness is labelled verified/unverified **at gate update**, with that UTC
time, not refreshed or claimed current at a later event.

UTC is the live platform TimeGMT clock at whole-second precision, explicitly
labelled. Tester paths are disabled. Broker time and deal server milliseconds are
separate fields; no broker-to-UTC conversion is invented. Actual source-host clock
and first-event persistence checks remain required after exact approval. No
first-logged-signal timestamp is claimed by a compile or fixture.

## Cross-arm strategy identity is a required collector mapping

The retained exact R2 receipts prove 35 unique magics per arm and **zero of 35**
matching index/symbol rows with equal raw magic. SHA256 of raw magic therefore
does not directly match the two arms. The CSV preserves the requested hashed
magic key, but `(bucket,symbol,hashedMagic,side)` is not a proven cross-arm key.

The existing normal status/audit rows already map each arm's index/symbol/magic
to its frozen member. The collector can map the hash to that same private row
and common frozen source SET identity, without another RPC or account identifier.
The frozen matched EA_Desc values are identical. Keep this mapping's source and
version in the private delivery manifest. Never join on symbol alone, fabricate
an event ID from a historic missing record or infer a veto from a missing trade.
Even matched signals do not prove an exact causal counterfactual when positions,
eligibility or later sequence paths differ; retain the observed gate and fill
stages, unmatched events and capture gaps.

Prospective signal/event IDs are assigned by the emitting EA instance and its
monotonic observation ordinal. They are not reconstructed historical IDs. The
collector must tail complete lines only, preserve source offsets/hashes and
deduplicate event IDs on the existing cadence. No collector source or native
probe is changed in this source proposal. No raw account, magic, ticket, credential
or wire payload is written; tickets/orders/positions are namespace-hashed.
