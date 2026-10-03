FU35 is an inert forward V1.49 candidate. It is EX33 (PR #116, on SM32 terminal isolation) plus two EA follow-ups:

- **Cancel answers `CANCELLED_RECONCILE` reliably.** A controller `cancel` used to check the tester
  once, 100 ms after the Stop click (`ClickStop(1)`), which raced MT5's tester shutdown and answered
  `CANCEL_SIGNAL_SENT_RECONCILE` for batches that did stop. `GOATTesterStopConfirm.mqh`
  (`GOAT_STOP_CONFIRM_V149`) reads the passive tester caption up to 40 times, 250 ms apart (10 s
  bound), and confirms idle only after 3 consecutive "Start" captions; a blank caption never counts.
  Stop is sent only right after a "running" read, once per run observed and at most 3 times, because
  Start and Stop share one MT5 toggle. The journal line `GOAT_CANCEL_STOP_CONFIRM` records polls,
  clicks and elapsed ms. Receipt format and controller semantics are unchanged.
- **EvidenceEnd export setting.** `GOATEvidenceEnd.mqh` (`GOAT_EVIDENCE_END_V149`) reads
  `EvidenceEnd` from the run's export settings: `AUTO` (the last fully closed Friday on the server
  clock) or an explicit closed server day `YYYY.MM.DD`, never before the optimization window end.
  Every export then runs to that day + 1 (MT5 `ToDate` is exclusive), so deals, equity rows and
  sequence frames end on the same day for every member. A refused value stops the export search with
  a plain reason and never falls back. Absent or empty keeps the legacy last-Friday end. The monitor
  observation advertises `evidence_end: goat-evidence-end-v1`, which `studio_evidence_end.ea_capability`
  (PR #118) reads; the controller then stages the batch's one resolved date (never `AUTO`).

No trading, risk, sizing, order or receipt-format change. The pinned input header
(`GOAT_Inputs_Definitions.mqh`) is unchanged, so SM32/EX33 batch packages stay valid.

Its `GOAT_BUILD_ID` is `V1.49-EA-FOLLOWUPS-35`, with marker `FU35`. `identity.json` binds the
exact forward source. **Compile pending.** Native qualification has NOT been performed. The new
build ID needs server admission before activation.

FU35 supersedes `ea-experience-EX33`. EX33, SM32, SM31 and SP30 stay retained unchanged in
`candidate-builds/`. The root `GOAT V1.49.ex5` and all installed artifacts remain unchanged.
Compilation does not qualify native use: exact-head review, isolated native DEMO/owner/STOP/Algo-off
qualification (including a real cancel of a running batch and a batch export with EvidenceEnd) and a
separately reviewed customer delivery remain required.
