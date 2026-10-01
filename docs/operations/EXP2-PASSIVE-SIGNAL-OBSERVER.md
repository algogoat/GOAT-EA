# Exp 02 passive signal observer — proposed source only

This internal build is based on exact R2 source `14ada7104a82052f7f966da4f7b745890781d553`.
It has not been installed, used natively or deployed. Exact-head Claude approval
is required before those operations. Existing R2, A1/BD28, the frozen local
campaign and desktop release bytes remain unchanged.

The observer is a no-op on real accounts and in Tester, optimization and forward
testing. On the live DEMO runtime it appends local `MQL5/Files/GOATExp2Signals/*.csv`.
It records each true indicator-side conjunction at the existing signal-entry
evaluation, using the AI gate booleans and wire state already consumed by the
existing minute update. It does not call GetState, WebRequest, OrderSend or
HistoryDealSelect. It does not alter any gate, risk, size, order argument, return
value or global control. A file-write failure reports a logging failure and never
returns into a trading decision. File I/O adds latency and can affect platform
error diagnostics; source tests do not establish runtime equivalence.

The separate proposed timing change changes only DEMO HTTP503 failure cooldown to
60 seconds. Retry runs at the first existing minute/tick evaluation at or after
that elapsed interval; tickless runtime has no exact wall-clock retry guarantee.
Every attempt still clears old state, and failed state remains unverified. Other
HTTP, authentication, transport, parse and verification failures keep the compiled
10-minute policy. No new input, timer, wire schema, model or permissive fallback is
added. This may recover valid permission earlier; it does not enable failed wire.
The EURJPY1003 origin remains unproven and its cadence is unchanged.

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
