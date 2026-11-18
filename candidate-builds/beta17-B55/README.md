B55 (`V1.49-BETA17-55`) is the **demo candidate for the dashboard bus fixes**: B54 (the research build, `V1.49-BETA17-54`,
`candidate-builds/beta17-B54/`) plus PR A0 (GOAT-EA#314: `BRK_Start_Seq` declared and refused as not built) and the dashboard
fixes of GOAT-EA#330. **Demo candidate: the T2 reading, then the two kept Exp 01 terminals; no live admission** (Claude-Mac
goatai#2750 6853274219). Nothing else rides on it: `BRK_Start_Seq`, the EA status push and anything new go to B56. It supersedes
no candidate: B54 stays the research build and B53 the experiments' final build until B55 is proven.

**What it fixes (GOAT-EA#328).**
- On B54 and earlier, every child chart's one-second timer acknowledged its stored dashboard command again, every second, for
  ever. Each acknowledgement ended in `GlobalVariablesFlush`, a rewrite of the terminal's whole global-variable store. That was
  about 33 rewrites a second on a 36-chart terminal, of `bases\gvariables.dat` (164 KB).
- B55 gives each command id **one** final acknowledgement: APPLIED, EXPIRED or REJECTED. A close that leaves positions open
  (FAILED) is retried every 5 s until flat or expired, as in B49b, and its FAILED acknowledgement is written only when its
  counts change.
- The three policy variables that OnInit restores from are kept alive by an hourly **read** (a read renews a global variable's
  4-week lifetime; it never writes a value back).
- Each dashboard publish clears the child's command id first and writes it last, and the child reads the id again after the
  fields (Codex 4559573813). **The two changes are a pair:** acknowledge-once is only safe because no poll can see a torn
  command.

**The one thing a B55 user must know: the first second after an upgrade from B43 or B54.**
- The terminal's store still holds each chart's last command id. B43 and B54 acknowledged it every second, so it normally
  already carries a final acknowledgement. OnInit seeds that, and **the first second writes nothing**.
- A stored command with no final acknowledgement gets **one**: EXPIRED, or APPLIED if it is still inside its 30 s and not yet
  applied. Then silence.
- A close still in progress (FAILED) is not final. It is retried until flat or expired, as before.
- The policy a command set (paused, trade mask, exposure mode) comes back from its own variables at OnInit; a command is never
  applied a second time.
- Proven by the restart cases (b1) to (b7) of `scripts/test_dash_ack_once.cjs`.

**Build**
- `GOAT_BUILD_ID` is `V1.49-BETA17-55`, marker `B55` (commit 43a7495: the two defines and the tests bound to them).
- **Compiled once** from 43a7495b with the pinned portable MetaEditor (sha256 `cf2750bd…`), Idle, outside every terminal folder,
  with B47's include root copied hash-equal: `Result: 0 errors, 0 warnings, 35965 ms elapsed, cpu='X64 Regular'`, 42-file closure.
- `GOAT V1.49.ex5`: sha256 **`a94a5104e28801873cb5983dca85c154850160e22b3dec183cf9240da2bb086a`**, 2,705,394 bytes. MetaEditor
  output is not byte-reproducible, so this is the one binary to use.
- Entrypoint `GOAT V1.49.mq5` sha256 `ce5256c7…` (pinned in `controller/contracts/v149/dependencies.json`), input header
  `e3490885…`: B54's 159 header inputs unchanged and in order, then `BRK_Start_Seq` (160).
- Against B54 the closure differs in exactly five files: `GOAT V1.49.mq5`, `Dashboard.mqh`, `GOAT_Inputs_Definitions.mqh`,
  `GOATPortfolioChildAudit.mqh` and `GOATStudioSettingTypes.mqh`. Every changed line carries the marker `B55` or sits in a marked
  block; the two identity lines are the one unmarked change (`scripts/test_b55_no_drift.cjs`).
- `controller/studio_installed_build.py` pins this binary as `V1.49-BETA17-55`. B54's and B53's rows stay.

**With `BRK_Start_Seq` off (its default) it trades as B54.** On, OnInit refuses: not built. Gate 0 on every pool SET:
`scripts/test_b55_gate0.cjs` and `controller/test_b55_gate0.py`. The dashboard bus runs only on a live child chart, never in the
tester or an optimisation.

**Not done.** No native qualification, no externals manifest, no admission row; the root `GOAT V1.49.ex5` is unchanged. Owed
before any install, with Claude-Mac's APPROVE, a pin check and server admission:
1. **The T2 reading (Claude-Mac 6850347247).** The same dashboard with 36 children, on B54 for 15 minutes, then on B55: the
   `gvariables.dat` write rate and its rewrites per minute. The claim: about 33 rewrites a second become about none, on one
   terminal, with the same charts. Then B55 at 1 h and 6 h. T2 cannot show the lag; that proof is the two kept Exp 01 terminals
   when the next experiment deploys B55 (against the 2.0 h and 1.3 h lags measured on 11-12).
2. Edward's rehearsal on the installed beta.44 needs T2 too, and it goes first.
