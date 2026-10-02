MH34 is an inert forward V1.49 candidate. It is EX33 (EA experience, PR #116, on SM32 terminal isolation, PR #113) plus one change (PR #112):

- **The read-only Studio monitor answers the local setup mailbox** (`GOATSetupControl.mqh`), which
  before only a Portfolio Dashboard chart did. It answers `status`, the demo-only `pairing` read (the
  connection code the EA is already showing, so an agent no longer asks the user to read it out) and
  an inert `shutdown`. The shutdown holds `GOATStudio\native-gate\launch.lock` from the research-idle
  check through `TerminalClose`; if the lock cannot be opened it refuses instead of closing. The
  account, server, data folder, build, demo-only and inert (Algo Trading off, no positions or orders)
  gates are unchanged.

No trading, risk, sizing, order or controller wire behaviour changes. The pinned input header
(`GOAT_Inputs_Definitions.mqh`) is SM32's, unchanged by EX33 and MH34, so SM32 batch packages stay valid.

Its `GOAT_BUILD_ID` is `V1.49-SETUP-MONITOR-HOST-34`, with marker `MH34`. `identity.json` binds the
exact forward source. **Compile is pending**: there is no binary or compile receipt yet, and none may
be implied. The new build ID needs server admission before activation.

MH34 supersedes `ea-experience-EX33`, which stays retained unchanged with its compiled binary, as do
SM32, SM31 and SP30. The root `GOAT V1.49.ex5` and all installed artifacts remain unchanged.
Compilation does not qualify native use: exact-head review, a MetaEditor compile, isolated native
DEMO/owner/STOP/Algo-off qualification and a separately reviewed customer delivery remain required.