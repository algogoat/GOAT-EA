# GOAT V1 to V2 Delta Register

## Reference anchor

- V2 reference commit: `d775d48b09d6fe65a946f65a8b14f430d854a593`
- V1 entrypoint: `GOAT V1.42.mq5`
- V1 source SHA-256: `7E39DB6DC533A71E30D96A64C9CAFEE7C67629A20CF049AEAF0D51AD0EC54E8C`
- V1 binary SHA-256: `7AD7B7910D0AA4C2AB5790D852A6131A75F5E1892E718525702A7B2EA3DD925D`
- Shared-input SHA-256: `7F746A73FF30D4CDEC5439AA0F30BC92A05591D717A328AECAD3C17117ECE10B`
- MetaTrader/MetaEditor build: `5.0.0.5833`
- Reference compile: `0 errors, 0 warnings`
- Selected: 2026-07-11

This commit is a comparison anchor only. V1 remains a living product. V2 never modifies a V1 entrypoint or shared V1 include.

## Current V2 product boundary

The V2.0 candidate is a single-symbol, single-member Phase 0/1 development foundation. It is not represented as a complete V1 port, certified live release, or internally complete multi-symbol portfolio engine. New exposure is compile-time locked by `GOAT2_PHASE1_EXECUTION_CERTIFIED=0` while the open dispositions and evidence gates below remain unresolved.

The runtime experiment manifest stores a normalized hash of trading/runtime inputs while excluding expected and external lineage fields. This avoids a circular self-hash. The literal SHA-256 of the `.set` artifact is retained separately in the external certification evidence bundle; both identities are required for a certified result.

## Disposition vocabulary

- `PORT`: preserve verified economics and behavior unless an approved defect requires correction.
- `REDESIGN`: preserve the product purpose while replacing an unsafe or unsuitable implementation.
- `NOT_APPLICABLE`: intentionally excluded from the fresh V2 product.
- `DEFER`: accepted for later V2 intake after the current phase gate.

## Initial delta register

| V1 capability | V2 disposition | V2 owner | Verification |
|---|---|---|---|
| Seven lot-progression models | PORT | `Core_Sequence.mqh` | Property tests plus V1 golden traces |
| Grid geometry and ATR-relative negative-input convention | PORT | `Core_Sequence.mqh` | Level-by-level trace comparison |
| VWAP basket Lock/TP/SL and trailing | PORT | `Core_Sequence.mqh` | Exit-price and event-trace comparison |
| CumPartial and PeakSmart retrace harvesting | PORT | `Core_Sequence.mqh` | Standing-lot and realized-P/L invariants |
| MLPS/Risk-per-sequence solver | REDESIGN | `Core_Risk.mqh` | Cost-complete adverse-path fixtures |
| Ticket arrays and direction-wide ownership | REDESIGN | Domain + StateDB | Event-sourced identity/recovery tests |
| Direct raw broker mutations | REDESIGN | Broker Gateway | Static bypass audit must return zero |
| In-memory-only sequence recovery | REDESIGN | StateDB | Crash/restart and idempotent replay tests |
| Process-memory-only broker submission fallback | NOT_APPLICABLE | StateDB + Broker Gateway | Every broker submission requires durable intent/receipt persistence; write failure enters `MANAGE_ONLY` |
| Virtual and delayed sequence execution | DEFER | Execution Core | Port/redesign contract and trace fixtures required before any dependent parity case can pass |
| MustCheck add/start revalidation | DEFER | Policy + Execution Core | Complete V1 semantic trace and approved direction-parameterized implementation |
| Bias/state rescue behavior | DEFER | Policy + Intelligence Bus | Phase-2 typed-state contract, deterministic rescue mapping, and replay evidence |
| Complete active V1 signal surface | DEFER | Features + Policy | Recorded V1 command/signal traces; generic EMA/RSI adapter is explicitly non-parity |
| Multi-symbol/member portfolio scheduling and risk | DEFER | Domain + Scheduler + Portfolio Manager | Phase-4 containers, aggregate exposure/MLPS, recovery, and portfolio canary |
| Legacy news/bias CSV/API behavior | DEFER | Intelligence Bus | Phase 2 typed-feed/replay gate |
| Custom binary-only MACD resource | NOT_APPLICABLE | Features | Native, source-controlled features only |
| V1 CDialog dashboard/object farm | NOT_APPLICABLE | Chart HUD/platform | Canvas HUD and platform-side operations |
| Optimization Studio and batch UI | DEFER | GOAT Ops | Phase 5 orchestration gate |
| Hard release expiry blocking management | NOT_APPLICABLE | Safety Kernel | Protective management always available |
| Fleet-wide embedded bearer material | NOT_APPLICABLE | Platform token contract | Per-customer rotated credentials only |
| V1.42 stale/invalid bias fail-safe | REDESIGN | Policy | Typed `NO_STATE`; block new risk, preserve management |

## Intake rule

Every later material V1 change must be added here before entering V2. No V1 behavior is absorbed merely because it is newer.
