B50 (`V1.49-BETA17-50`) is B49a plus B50-alpha (goatai#2587; design `docs/b50/B50_ALPHA_DESIGN.md`). **Research
only:** no admission row and no live arm. Each item had its own reviewed PR into `claude-mac/b50-alpha`, integrated by
GOAT-EA#277 (`a86e5775`). Base: B49a's source `65fde12`. The compile closure is B49a's 41 files plus
`GOAT_NYClock.mqh`. Six B49a files differ:
- `GOAT V1.49.mq5`
- `GOAT_Inputs_Definitions.mqh`
- `GOATStudioSettingTypes.mqh`
- `GOATStudioSettingCompare.mqh`
- `GOATPortfolioChildAudit.mqh`
- `GOATOptimizationInputs.mqh`

Every changed line is marked `B50` (`scripts/test_b50_no_drift.cjs`). See **Build**.

**Items:**
- **B50.0 A0 scaffold** (GOAT-EA#269):
  - the 12 B50-alpha inputs appended after `Ledger_Mode`;
  - `TF_D1` appended to `ENUM_MODE_TFs`;
  - the NY clock and single-trade stubs;
  - OnTesterInit writes an omitted B50 axis at its default.
- **B50.0b A0 follow-up** (GOAT-EA#275):
  - the entry block holds through the `Delay_Trade` virtual-to-real promotion;
  - the NY clock refuses pre-2007 tester history for the Fixed and EUDST models.
- **B50.1 A1 single core** (GOAT-EA#272): under `Engine_Single`, `GoatSingleOpen` opens one ATR-stopped position per signal episode.
  - `RiskperSeq` lots come from tick value / tick size, floored to the step, and refused below the minimum.
  - The TP comes from R or ATR.
  - The stop and the TP clear the stops level.
  - It re-arms on the signal's false edge.
- **B50.2 A2 New York clock** (GOAT-EA#273):
  - DST, and the NY-close, fixed and EU-DST server-clock models;
  - the NY session, the rollover block and the live self-check;
  - the Friday close at the earlier of the session end or Friday 16:55 NY;
  - the FX trade-date convention.
- **B50.3 A3 single exits** (GOAT-EA#274): the opposite-signal exit, the time stop (retried every tick until it closes) and the FastSpeed bypass under `Engine_Single`.

**Inputs.** The input header gains 12 inputs after `Ledger_Mode` (`Engine_Mode` … `Rollover_Block_Minutes`), and every
`ENUM_MODE_TFs` input gains `TF_D1`. B49a's 115 inputs keep their order, type, default and choices.
- Every new input defaults to B49a's behaviour: `Engine_Grid`, `Clock_Server`, and zero sizes and minutes. With every flag off, B50 is B49a: `scripts/test_b50_parity.cjs` checks this on the converted OnTick region and on the `WriteSet` golden.
- B50 batch packages carry B50's header pin. B49a-header packages match B49a, not B50.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-50`, marker `B50`. The build ID line is the guard's one unmarked change (`IDENTITY_LINES`).
- **Compile pending.** `identity.json` binds the sources, and `binary` is `null` until the compile commit.

**Gate (goatai#2587):**
1. Banker tester parity, Sun 11-01 06:00–10:00Z: B50 with `Engine_Mode=Grid` (the default) against B49a `220a8725`, on 50 seeded exports. The no-drift guard proves that every change is visible; it does not prove neutrality.
2. Research use only after that parity passes. There is no admission row or live arm in B50-alpha.

**Not done.** Not installed, no native qualification, no admission row. The root `GOAT V1.49.ex5` is unchanged.
