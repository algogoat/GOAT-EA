B56 (`V1.49-BETA17-56`) is **B55 plus swap-spec**: B55 (the demo candidate for the dashboard bus fixes, `V1.49-BETA17-55`,
`candidate-builds/beta17-B55/`) plus GOAT-EA#354, which makes every sequence capture record the symbol spec the tester ran on.
Nothing else rides on it (Claude-Mac goatai#2750 6980043568): the breakout start path (`BRK_Start_Seq`, spec GOAT-EA#311) is
B57. It supersedes no candidate: B55 stays the demo candidate, B54 the research build and B53 the experiments' final build.

**Why (swap guard step 3, INV-SWAP-01).**
- The Strategy Tester charges swap from the symbol spec it has cached from the broker. Twice that spec held zero swap on JPY
  pairs (Banker 2026-10-09..10-27, and runs made 2026-09-19/20), so those runs paid no swap and every result judged on them is
  optimistic. Nothing recorded the spec a run was given.
- Until B56 the controller infers it from the deals alone (`controller/studio_swap_inputs.py`): a run with 3 or more positions
  held over a rollover, all at zero swap, is held back. That inference has two known false hold-backs (a strategy holding only
  a side whose broker swap is truly zero; overnight positions so small that each night rounds to 0.00).

**What changes.** One marked block (`B56:begin swap-spec`) in `GOAT_SequenceExport.mqh` writes seven keys into the capture's
`run.csv`, after `initial_orders`, read once at capture start:

| key | written from |
|---|---|
| `symbol_swap_mode` | `SymbolInfoInteger(_Symbol,SYMBOL_SWAP_MODE)` |
| `symbol_swap_long` | `DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_SWAP_LONG),-16)` |
| `symbol_swap_short` | `DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_SWAP_SHORT),-16)` |
| `symbol_swap_rollover3days` | `SymbolInfoInteger(_Symbol,SYMBOL_SWAP_ROLLOVER3DAYS)` |
| `symbol_contract_size` | `DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),-16)` |
| `symbol_digits` | `SymbolInfoInteger(_Symbol,SYMBOL_DIGITS)` |
| `symbol_point` | `DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_POINT),-16)` |

- Integers as the terminal returns them; every double at 17 significant digits, which reads back exactly (-7.35 is written
  `-7.3499999999999996e+00`).
- No trading path reads them. Every reader takes `run.csv` by key and tolerates new keys (the controller's
  `studio_evidence._key_values`; the desktop's `compileNativeSequenceTrace.ts` and `sequencePackageService.ts`), and the schema
  string stays `goat-native-sequence-capture-v1`.
- The controller reads the recorded spec beside each capture's `deals.csv` and judges each side on its own (GOAT-EA#355, merged
  into `claude-mac/b50-alpha`); a capture without the keys is judged from its deals exactly as before.

**Build**
- `GOAT_BUILD_ID` is `V1.49-BETA17-56`, marker `B56` (GOAT-EA#356, merged as `98be56c4` into `claude-pc/b56-line`: the two
  defines and the tests bound to them).
- **Compiled once** from `98be56c4` (tree `719a333f`) with the pinned portable MetaEditor (sha256 `cf2750bd…`, 5.0.0.6230),
  Idle, outside every terminal folder, with B47's include root copied hash-equal (308 files):
  `Result: 0 errors, 0 warnings, 81477 ms elapsed, cpu='X64 Regular'`, 42-file closure.
- `GOAT V1.49.ex5`: sha256 **`e467c3b8889861f31b2d1674993f627d3afe51528be1156f57806a8b0663b148`**, 2,706,206 bytes. MetaEditor
  output is not byte-reproducible, so this is the one binary to use.
- Entrypoint `GOAT V1.49.mq5` sha256 `067fe63c…` (pinned in `controller/contracts/v149/dependencies.json`), input header
  `e3490885…` (B55's: 160 inputs, unchanged).
- Against B55 the closure differs in exactly two files: `GOAT V1.49.mq5` (the two identity lines, the one unmarked change) and
  `GOAT_SequenceExport.mqh` (the swap-spec block) (`scripts/test_b56_no_drift.cjs`).
- `controller/studio_installed_build.py` pins this binary as `V1.49-BETA17-56`. B55's, B54's and B53's rows stay.

**It trades as B55.** The only source change outside the identity lines writes seven `run.csv` keys during a capture.

**Not done.** No native qualification, no externals manifest, no admission row; the root `GOAT V1.49.ex5` is unchanged. Owed
before any tester lane runs B56 (Claude-Mac 6980043568) and before any install, with Claude-Mac's APPROVE, a pin check and
server admission:
1. **The B55/B56 parity proof against B54 on the pool SETs.** Saturday's w13 stays on B54, guarded by the read-only swap sweep.
2. A first native capture on B56, to see the seven keys written by the terminal itself and read back by the controller.
