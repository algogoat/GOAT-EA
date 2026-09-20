# V1.47 DG1 asset sequence guard

The existing dashboard Exposure control cycles Allow / Asset / Currency. Asset mode now claims one terminal-global owner per account/server/exact broker symbol/direction immediately before the first real OrderSend, after local validation. Virtual tracking does not reserve ownership. Simultaneous charts arbitrate by atomic compare-and-swap: first eligible claimant wins; no global signal-timestamp ordering is claimed.

The owner keeps its reservation across adds, partial closes and temporarily flat logical sequence state. End_Sequence releases immediately once positions, orders and unresolved requests are absent. There is no cooldown. Buy and Sell are separate; enabling asset mode requires a hedging account and fresh DG1 telemetry from every linked child. Currency mode retains its existing behavior.

Existing sequences when the user enables the filter continue management and show Live; ownership is not retroactively redistributed. All actual same-symbol/direction positions and pending orders, including manual/unregistered trades, conservatively block new admission. This is a single-terminal mechanism, not coordination across separate terminals or VPSs. No setting is automatically enabled and no strategy input is changed.

The status column shows B/S Ready, Own, Wait, Check or Live. Its tooltip explains the states and shows the child's instance token. Check means an unresolved broker request or late fill requires manual reconciliation; there is no timeout that silently frees it. The build marker is DG1 and startup reports V1.47-ASSET-SEQUENCE-GUARD-R1 plus the loaded path.

## Durable uncertainty and restart boundary

An exclusive per-instance pending file under terminal-local MQL5/Files/GOATGuard is written and flushed before each guarded request. It records exact account, server, symbol, direction and instance identity. Any pending file in the same account/server/symbol/direction scope blocks fresh admission after terminal restart. A write failure prevents the send; incomplete evidence remains fail closed. Only a definite rejection, settled broker result or matching accepted order's deal resolves the current instance's marker. Owner metadata and CAS globals are temporary, but uncertain request evidence is durable.

Known accepted partial fills (DONE_PARTIAL) enter the normal sequence-success path only when their position maps safely into the existing int-ticket sequence state, recording actual standing volume and price. An unresolved or out-of-range ticket retains broker-reported volume/price as evidence and the durable Check marker; it requires manual sequence reconciliation. A false/uncertain send followed by a late fill does not reconstruct missing sequence levels automatically: the Check state and durable marker remain. The existing EA also does not reconstruct full sequence state on restart. Surviving positions/orders prevent duplicate admission; this patch does not claim recovery of lost sequence management state.

Before manually clearing a pending marker, independently reconcile the exact request/order/deal, all positions and orders, and the EA's sequence state. Keep the evidence and prevent new starts during that operation. Restarting, toggling off/on or deleting a file is not broker reconciliation. No automatic marker-clear control is included.

## Verification and rollout boundary

scripts/test_direction_guard.cjs executes the production MQL core and selected adapter functions after syntax-only translation; its concurrency rounds use independent workers and native Atomics. This validates transitions and CAS contention, not a broker or MT5 scheduler. scripts/mql5/GOATDirectionGuardSmoke.mq5 contains a no-trade native API harness restricted to an isolated directory named guard-native-portable.

The isolated baseline ed64535 snapshots current Desktop source/include dependencies over 3b89e2c. Its main source matches the prior Banker FE46683 build receipt, but unchanged control recompiles do not reproduce that binary. Source-closure equivalence to installed builds is unproven; review the baseline separately from the guard patch. Protected Terminal 2 must not receive the candidate solely on the basis of a successful compile. Preserve its exact binary as rollback, verify loaded build/path after an approved installation, and retain the existing process/profile safety workflow.
