PS37 is an inert forward V1.49 candidate: EX33 plus one fix, a steady Studio panel.

**The bug.** On EX33, Banker's Studio panel alternated "GIVE TO AGENT" (grey) and "AGENT CONNECTED" (lime).
Each timer refresh runs `ManagedControls` up to three times: in both `ManagedResize` passes and in the
final call. `ManagedControls` first painted the default handoff state and then overwrote it with the real
one, and MT5 can draw the chart between those two object writes. The read-only stage also painted
"READ-ONLY VIEW" and disabled controls that `ManagedControls` re-enabled straight away. SM31 overwrote the
same text but kept the same colour, so the transient state was much less visible there.

**The fix** (`GOATStudioUI.mqh`, `Optimizer.mqh`):
- `ManagedControls` works out the handoff buttons' final text, enabled state and colours first, then
  writes each one once at the end.
- Control writes go through `GoatStudioSteadyText`, `GoatStudioSteadyColors` and
  `GoatStudioSteadyEnabled`, which write only when the value differs. A refresh that changes nothing
  writes nothing.
- The compact agent-connection card no longer hides and then re-shows the controls it keeps.
- The managed read-only stage leaves the controls that `ManagedControls` owns alone.
- `ManagedRefresh` writes its status line once, after the draft and receipt checks.

The final state of every control is unchanged. There are no changes to trading, risk, sizing, orders or
the controller wire. The input header is still SM32's, so SM32 batch packages stay valid.

Harness `scripts/test_studio_steady_panel.cjs` (20 checks) runs the production `ManagedControls` and the
read-only stage against recording controls, covering eight owner, pending and layout states. It checks:
- one write per property in a pass;
- no write in a settled pass or refresh;
- the exact final text, enabled state and colours.

`scripts/test_studio_steady_panel_mutations.cjs` kills all 14 mutations, including restoring the
EX33 pre-paint.

`GOAT_BUILD_ID` is `V1.49-PANEL-STEADY-37`, marker `PS37`. **Compiled** from `650db584` with MetaEditor
5.0.0.6230: 0 errors, 0 warnings. The output is `GOAT V1.49.ex5`, sha256 `4ed8ec4d…`, 2,388,424 bytes.
The sanitized `compile-receipt.json` is in this folder.

Native qualification has NOT been performed, including the visual check that the panel no longer
flashes. The new build ID needs server admission before activation. EX33, SM32, SM31 and SP30 stay in
`candidate-builds/` unchanged, and the root `GOAT V1.49.ex5` is unchanged.
