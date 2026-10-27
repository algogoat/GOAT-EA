B49a (`V1.49-BETA17-49`) is B47 plus WEEKEND-1031 (goatai#2587 6427654059 / 6427772701). Each item had its own
reviewed PR into `claude-pc/b49a`, plus the review fixes from GOAT-EA#267 (Codex). Base: B47's source `ccb0a07`. The compile closure is B47's 41 files. Five differ from
B47: `GOAT V1.49.mq5`, `GOAT_Inputs_Definitions.mqh`, `GOATStudioSettingTypes.mqh`, `GOATStudioSettingCompare.mqh` and `GOATPortfolioChildAudit.mqh`.
Every changed line is marked `B49a` (`scripts/test_b49a_no_drift.cjs`). See **Build**.

- **B49a.1 64-bit tickets** (GOAT-EA#263): no `int` holds a ticket. `LastOrderTicket`, `LastDealTicket`,
  `LastBuyTicket` and `LastSellTicket` are `long`.
- **B49a.2 B48, the daily CID touch** (GOAT-EA#264): a live chart rewrites its own CID GlobalVariable once per UTC
  day, so MT5's 4-week expiry never drops a running chart's record.
- **B49a.3 F2, `Ledger_Mode`** (GOAT-EA#265): an appended input, default `Ledger_Legacy`, which is B47.
  `Ledger_PositionJoin` books an exit, with fees, by the position it closes.
- **B49a.4 F1-lite, restart adoption** (GOAT-EA#266):
  - a live real sequence keeps a restart record, and OnInit adopts a matching open basket manage-only;
  - stops are only ever tightened;
  - adds stay frozen until the basket ends.
- **Review fixes** (GOAT-EA#267, Codex):
  - `WriteSet` writes `Ledger_Mode` when it isn't Legacy, so a Legacy SET is B47's bytes;
  - the child audit treats `Ledger_Mode` like `BlindExport` (a child must hold Legacy against a SET without it);
  - the restart record keeps the trade count (`C`) that the lock flexibility reads.

**Inputs.** The input header gains `Ledger_Mode` after `BlindExport`; B47's 114 inputs are unchanged.
- A SET written before B49a still validates: the controller completes an omitted `Ledger_Mode` with its default, and
  the EA Studio accepts it only at 0.
- B49a batch packages carry B49a's header pin. SM32-header packages match B47, not B49a.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-49`, marker `B49a`.
- **Compiled once** from `693cad05` (label `b49a-candidate-20261027T014537Z`): **0 errors, 0 warnings**
  (`Result: 0 errors, 0 warnings, 29750 ms elapsed`).
  - **Compiler:** MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`), a `/portable` copy hash-equal to B47's compiler, Idle priority. Exit code 1 with a clean `Result:` line, as in B40–B47.
  - **Include root:** B47's compile root, copied hash-equal file by file.
  - **Stage:** the 41-source closure and 3 resources, copied from the clean head outside every terminal folder, then moved aside.
- `GOAT V1.49.ex5`: sha256 **`220a87257300c32c354243c8208f08f58dba90dcdd26b78c4472d385e56c1cd7`**, 2,509,504 bytes.
  It supersedes `e43ed98e…` (from `f681ad6`, before the #267 review fixes), which was never installed or admitted.
- Entrypoint `GOAT V1.49.mq5`: sha256 `eab5f1f4…`, pinned in `controller/contracts/v149/dependencies.json`. Input header
  `38b3270e…` (B47's 114 inputs plus `Ledger_Mode`).
- `externals.json`: no problems; `consumed_sha256` (`ced68559…`) equals B47's; bound to the receipt (`e20ebef0…`).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Gate (Ops, goatai#2587):**
1. Banker tester parity with the new input at its default: B49a against B47, byte-identical on the 48 templates and on
   sampled exports. The no-drift guard proves every change is visible, not that it is neutral.
2. An internal admission row for this binary.
3. The restart drill (cases A–D) on T2.

**Deploy note:** B49a's restart record and CID touch run on live charts only. A B47 terminal on the same login behaves
as before: it never adopts and never touches its CID.

**Not done.** Not installed, no native qualification, no admission row yet (goatai, for T2 `3000107825`). The root
`GOAT V1.49.ex5` is unchanged.
