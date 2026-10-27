# B44 dashboard Deploy All: design

Register: `P-beta25-D5-dashboard-deploy-all`. Reviewer: Claude-Mac.

**Promise.** The dashboard's own Deploy All returns, through an MQL profile writer that is byte-equal to
`controller/studio_deploy_profile.py` on golden fixtures.

**Branch.** `claude-pc/b44-deploy-all`, from `codex/v148-research-planning` @ `c708cae4`.

## Summary

- **Bytes: done.** The writer core, `GOATDeployProfileWriter.mqh`, is pure MQL. Run offline, the production source
  reproduces every G2 golden and three new whole-portfolio G4 goldens byte for byte. It also refuses all 49 refusal
  cases with the Python writer's code.
- **Where the bytes go: needs kernel32.** MQL's own file API cannot reach `MQL5\Profiles\Charts`; it is outside the
  file sandbox. The only route is kernel32, which the EA closure already imports (through `MTTester.mqh`) and the
  dashboard already requires (DLL imports must be allowed at init). No new `#import` is needed.
- **Loading: the open risk.** MT5 reads a profile's charts only at start-up or on a profile switch. No MQL API
  switches profiles or restarts the terminal. The dashboard-only path therefore ends with the person choosing
  **File > Profiles > GOAT-Deploy-…**, and this needs a T3 proof (section 3).
- **Recommendation: B44.1.** The core, goldens and tests can merge now as source and tests only, outside the B44
  compile closure. The button, native shell, adoption binding and T3 proof ship as B44.1.

## 1. What is written, and whether MQL can write it

### 1.1 What `studio_deploy_profile.py` writes (profile-staged-v1)

**Folder.** `<data>\MQL5\Profiles\Charts\GOAT-Deploy-<deploymentId[:16]>\`, created fresh.

- `chart01.chr` is the dashboard. `chart02.chr` … `chart(N+1).chr` are members 0 … N-1 in plan order.
- The folder has 1 to 100 members, and there is nothing else in it: no `order.wnd` and no objects. MT5 adds those
  itself (`profile-deploy.md` §1).

**Encoding.** Each chart file starts with the UTF-16LE BOM `FF FE`, then the text in UTF-16LE. Every line, including
the last, ends in CRLF (`encode_chart`). Characters outside the BMP are written as surrogate pairs.

**Chart text.** These lines, in this order:

| Line | Value |
|---|---|
| `<chart>` | |
| `symbol=` | member symbol; must match `[A-Za-z0-9_.#-]{1,64}` |
| `period_type=` / `period_size=` | `0/1` M1, `0/5` M5, `1/1` H1, `1/4` H4, `1/24` D1. M15, M30 and everything else are refused (`SET_PERIOD_UNSUPPORTED`) |
| `scale=8`, `mode=1`, `grid=0`, `scroll=1`, `one_click=0`, `windows_total=1` | fixed |
| `<expert>` | |
| `name=` | stem of the EA file (`GOAT V1.49`) |
| `path=` | `Experts\` + the EA path relative to `MQL5\Experts` |
| `expertmode=5` | fixed (D1) |
| `<inputs>` … `</inputs>` | the input lines below |
| `</expert>` | |
| `<window>`, `height=100.000000`, `objects=0`, `<indicator>`, `name=Main`, `path=`, `apply=1`, `show_data=1`, `</indicator>`, `</window>`, `</chart>` | fixed |

There is no `id=`, and no `Enabled` or `AllowLiveTrading` key anywhere.

**Child inputs.** Built in this order (`profile-deploy.md` §2.2):

1. **Decode.** `FF FE` means UTF-16LE. Anything else is UTF-8, and a single UTF-8 BOM is dropped. Both decodes are
   strict.
2. **Split** on CRLF or LF. A lone CR is refused, and so is a file of more than 4097 pieces.
3. **Refuse** any line that holds a Cc, Zl or Zp character other than tab.
4. **Trim** spaces and tabs from both ends.
5. **Keep** a line when its first `=` is after position 0.
   - A kept line is refused when it starts or ends with any other Python `isspace` character, or contains `<` or `>`.
   - A SET with no kept line is refused.
6. **AI policy** (`GoatApplyAILaunchPolicy`, modes 1 and 2).
   - `Mode_Bias`, `Bias_threshold`, `Bias_Protocol` and `Mode_Bias_Trades` are replaced in place.
   - Any of them that is missing is appended, in that order.
7. **Nonce.** The line `Studio_MonitorRunPath=deploy=<deploymentId>` either replaces a single
   `Studio_MonitorRunPath=` line in place or is appended last.
   - Any other value is refused, and so is a second occurrence (`SET_RUN_PATH_UNSUPPORTED`).

**Dashboard (chart01).** The same frame on `M1`, on member 0's symbol. Its inputs, in this order:
`Mode_Operation=8`, `Dashboard_Resume_Saved=true`, `Mode_Bias=1`, `Bias_Protocol=2`, `Bias_threshold=50`,
`EA_Desc=GOAT Dashboard`. It carries no nonce.

**Duplicates.** Two members with the same symbol, period and audit-equal effective inputs are refused before anything
is written (`refuse_duplicates`).

**Written beside the profile by `studio_demo_deploy.py`.** These files are outside the writer module:

- **The state TSV** `Common\Files\GOAT\dashboard_state_<data folder>.tsv`. Python's `utf-16` codec writes BOM + LE.
  It holds a `#GOAT_AI_LAUNCH_V147_2\t<aiMode>\t<aiThreshold>\t<aiProtocol>` header, then one row per member:
  `path, name, symbol, strategy, As SET, As optimized, As SET, 0, 0`, with CRLF line ends.
- **The frozen SETs** under `Common\Files\GOAT\Deployments\<id>\`.
- **The namespace claim.**
- **The `/config:` start-up ini.**

The MQL core also produces the state TSV bytes, because a writer that stages the profile must stage its rows too.

### 1.2 What the MQL writer reproduces, and how

`GOATDeployProfileWriter.mqh` is a pure-string core. It makes no file, chart, terminal, DLL or trade call.

| Python | MQL core |
|---|---|
| `decode_set` | `GoatProfileWriterDecodeSet`: strict UTF-16LE (odd length or an unpaired surrogate is refused) and strict UTF-8 per Unicode table 3-7 (overlong, surrogate, above U+10FFFF, truncated or stray bytes are refused). A NUL is refused after a complete decode, in Python's order. |
| `set_input_lines` | `GoatProfileWriterSetInputLines`: works on UTF-16 units. Python's `isspace` set is copied exactly; it was enumerated with Python 3.13.16. |
| `apply_ai_policy`, `_ai_value` | `GoatProfileWriterApplyAIPolicy`, `GoatProfileWriterAIValue` |
| `with_deploy_nonce` | `GoatProfileWriterWithNonce` |
| `period_token`, `PERIODS` | `GoatProfileWriterPeriodToken`, `…PeriodUnit`, `…PeriodCount` |
| `expert_identity` | `GoatProfileWriterExpertOk/Name/Path` |
| `chart_text_lines` + `encode_chart` | `GoatProfileWriterChartText` + `GoatProfileWriterEncodeUtf16` |
| `dashboard_chart`, `child_chart` | `GoatProfileWriterDashboardChart`, `GoatProfileWriterChildChart`. Both return `uchar[]`. Refusals come in Python's order: period, then SET, then symbol, then EA path. |
| `profile_name`, `chart_file_name`, the member count | `GoatProfileWriterProfileName`, `…ChartFileName`, `…MemberCountOk` |
| `studio_demo_deploy.state_bytes` | `GoatProfileWriterStateFile` |

**Refusal codes.** The core uses Python's codes. Python has no code of its own in two cases, so the core adds two:

- `SET_ENCODING_UNSUPPORTED`, where Python raises `UnicodeDecodeError`;
- `PROFILE_VALUE_UNSUPPORTED`, where Python raises a bare `ValueError` for the symbol, EA path or deployment ID.

**Where MQL is stricter, by design.** Being stricter never changes the bytes of an input that both writers accept.

- **EA paths:** only the canonical form is accepted, with no `.` segment, empty segment, drive or leading `\`. For
  those paths `PureWindowsPath` leaves the text unchanged.
- **TSV fields:** a field holding a tab or a line break is refused.

### 1.3 The crux: can an EA write into `Profiles\Charts\<profile>`?

**Not with MQL's own file functions.** The MQL5 file functions (`FileOpen`, `FolderCreate`, `FileCopy`, `FileMove`,
`FileDelete`) work only inside the file sandbox:

- `<data>\MQL5\Files\`, or `<agent>\MQL5\Files\` in the tester;
- `<Common>\Files\` with `FILE_COMMON`.

The MQL5 documentation says: "For security reasons, work with files is strictly controlled in the MQL5 language.
Files with which file operations are conducted using MQL5 means cannot be outside the file sandbox." A name that
climbs out with `..` is rejected.

`<data>\MQL5\Profiles\Charts\` is a sibling of `MQL5\Files`, so no flag reaches it. `FILE_UNICODE`, `FILE_ANSI`,
`FILE_BIN` and `FILE_COMMON` only choose the encoding and which sandbox root is used.

The repo's own history shows the same limit:

- **The old template copy needed kernel32.** `Dashboard.mqh@78f3b30:3084-3106` (`SaveTemplateAndCopy`) wrote the
  template into the Common sandbox with `FileOpen(...FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON)`. It then needed
  `kernel32::CopyFileW` with a `\\?\` path to reach `MQL5\Profiles\Templates\`; the import is at
  `Dashboard.mqh@78f3b30:18-24`. `DeleteCopiedTemplate` needed `DeleteFileW` for the same reason.
- **B43 removed that import.** `candidate-builds/beta17-B43/README.md` deleted it together with the template path.
- **The tester-profile writer also uses kernel32.** `MTTester.mqh` writes `MQL5\Profiles\Tester\` only through
  `kernel32::CreateDirectoryW`, `CopyFileW`, `CreateFileW` and `WriteFile` (`MTTester.mqh:1486-1534`, `:1566-1610`).
- **`GoatDashboardCommonSetPath` refuses `..` and `:` itself** (`Dashboard.mqh`; same rule at `@78f3b30:30-36`).

**`ChartSaveTemplate` is not a way round it.** The audit uses it with a `\Files\…` path relative to `MQL5`
(`GOATPortfolioChildAudit.mqh:254`). It cannot produce our bytes:

- it forces a `.tpl` extension, so it cannot write `chart02.chr`;
- it serialises an existing chart in MT5's own format, so it is not byte-equal;
- it needs the chart to exist already, which is the problem we are solving.

**What does work.** kernel32, which is already in the build:

- `MTTester.mqh:64-71` imports `CopyFileW`, `ReadFile` and `WriteFile`.
- `MTTester.mqh:9` includes `<WinAPI\WinAPI.mqh>`, which declares `CreateDirectoryW`, `CreateFileW`, `DeleteFileW`,
  `MoveFileW`, `GetFileAttributesW` and the `FindFirstFileW` family. `MTTester.mqh` calls these at `:326`, `:512`,
  `:1456-1610`.
- `MTTester.mqh` is in the closure through `Optimizer.mqh:12` → `Tester.mqh:1`.
- The dashboard already refuses to start without DLL imports (`GOAT V1.49.mq5:3046-3047`).

So the native shell adds **no new `#import` and no new DLL name**. B43's `externals.json` compares imports by DLL
name, and `kernel32`, `shell32` and `user32` stay the set.

**What the native shell will do (B44.1, not written yet).** All of it lives in `GOATDeployProfileWriter.mqh`, so
`Dashboard.mqh` stays DLL-free, as the B43 guards require (`test_profile_staged_adoption.cjs:454-457`,
`test_dashboard_deploy_paths.cjs:45-46`).

1. **Stage in the sandbox.** Write each chart to `MQL5\Files\GOAT\DeployStage\<id>\chartNN.chr` with
   `FILE_WRITE|FILE_BIN` and `FileWriteArray(uchar[])`, so the BOM and CRLF come from the core. This avoids any
   `FILE_TXT`/`FILE_UNICODE` BOM or newline handling. Read each file back and compare it to the core's bytes.
2. **Create the profile folder.** Call `kernel32::CreateDirectoryW("\\?\<data>\MQL5\Profiles\Charts\GOAT-Deploy-<id16>")`.
   It must create the folder; `ERROR_ALREADY_EXISTS` is a refusal. Nothing is ever overwritten.
3. **Copy each chart.** Call `kernel32::CopyFileW(stage, target, bFailIfExists=TRUE)` for each file. Read the copy
   back with `CreateFileW` + `ReadFile` and compare it byte for byte. Then enumerate the folder: it must hold exactly
   N+1 files.
4. **Clean up the sandbox only.** Delete the stage copies with `FileDelete`. GOAT never deletes anything outside its
   own new folder.

SETs are read with `FILE_READ|FILE_BIN|FILE_COMMON` and `FileReadArray`, and the core decodes them. The old
`BuildTemplate` read SETs as `FILE_TXT|FILE_ANSI`. Its handling of a UTF-16 SET is not proven, and the core removes
the question.

### 1.4 How a written profile gets loaded

- **When MT5 reads charts.** MT5 reads a profile's `chartNN.chr` files at start-up, from `config\common.ini`
  `[Charts] ProfileLast` or a `/config:`/`/profile:` argument, and when the person switches profiles in the running
  terminal. The B43 lesson stands: a running EA cannot make MT5 load a chart. `ChartApplyTemplate` was accepted and
  never performed on every V1.49 build (`DEPLOYMENT-STARTUP-LIVENESS.md`).
- **No MQL API helps.** Nothing in MQL selects a profile or restarts the terminal.
- **Writing `common.ini` from the EA does not help.** It is outside the sandbox, and MT5 rewrites `ProfileLast` when it
  exits (`studio_demo_deploy.py:820`).
- **`/profile:` is fragile.** The build-6230 updater dropped it (`BACKLOG.md` CTRL-010). That is why the controller
  uses `/config:` with `ProfileLast`.

| Option | What happens | Verdict |
|---|---|---|
| **L1: the person switches profile** | The dashboard writes everything, then shows one step: "In MT5 choose File > Profiles > GOAT-Deploy-xxxxxxxxxxxxxxxx." MT5 saves the current profile, closes its charts and opens the new one: chart01 is the dashboard and the children follow. If the menu does not list a folder created while MT5 was running, the step becomes "restart MT5, then choose …" (same mechanism). | **Recommended** for the dashboard-only path. **Unproven**: T3 proof P1-P6 (section 3). |
| **L2: the app launches** | The dashboard is the writer. The app's deploy-load runs its existing `staged → closed → launch_intent → launched` phases, with `[Experts] Enabled=0`, rollback and unwind. Byte-equality means `verify_staged` passes on EA-written files with no controller change. | Keep it as the app path. It still needs the app, so on its own it does not deliver "the dashboard's own Deploy All". |
| **L3: the EA relaunches MT5** | A `ShellExecuteW` helper plus `TerminalClose`. | **Rejected.** It duplicates the journal, rollback and unwind outside any review. It depends on the `/profile` argument the updater drops. A terminal that closes itself while a detached process edits its state contradicts the inert-only posture. |

## 2. Proving byte-equality without MT5 on this PC

**Chosen method: run the production MQL source offline against goldens that the Python writer emits.** A native
check follows in the B44.1 T3 window.

1. **G4 goldens.** `controller/deploy_profile_goldens.py` builds three whole fixture portfolios with the live Python
   writer. It writes every chart, the state TSV, the input SETs and `g4/cases.json` (with hashes).
   - **`p1-m1-ai-off`:** the real B35-01 Kestrel SET (UTF-16) and a UTF-8 SET whose `Studio_MonitorRunPath=` the nonce
     replaces in place.
   - **`p2-h1-d1-ai-on`:** H1 and D1 members plus an H1 index (`US30.cash`). AI protocol 2, with replace-in-place and
     append. Covers a UTF-8 BOM with LF, padding, blank and keyless lines, and no final line end.
   - **`p3-unicode-mixed`:** M5, H4, D1 and M1 members. AI protocol 1. Non-ASCII and astral characters (U+1F410) in
     UTF-8 and UTF-16, with U+200D and U+FEFF kept. Includes a `BTCUSD#` symbol and two members on EURUSD.
   - **34 refusal cases**, each with Python's verdict: encodings, the nonce input, periods, symbols, EA paths and the
     deployment ID. They add to the 15 in `g2/refused.json`.
2. **Python pin.** `controller/test_deploy_profile_goldens.py` fails when the committed G4 bytes differ from what the
   Python writer emits now. It also checks the matrix: all five periods, AI off and on, both protocols, three
   encodings, and the nonce replaced in place at least twice. It requires every profile file to be hash-pinned,
   free of `Enabled=` and `AllowLiveTrading`, with chart01 nonce-free and every row starting `0 0`.
3. **MQL execution.** `scripts/test_profile_writer_goldens.cjs` converts `GOATDeployProfileWriter.mqh` syntactically
   to JavaScript, the same technique as `test_portfolio_child_audit.cjs`, and runs it on Node.
   - **Byte-equality:** every G2 child, the dashboard, the G2 profile and its state file, and all three G4 profiles
     (12 chart files and 3 state files) must be byte-equal.
   - **Refusals:** every refusal case must be refused with Python's code.
   - **Source rules:** they keep the conversion honest. No division, no call outside an allow-list of string and array
     builtins, no file, chart, terminal, account, order, position, GV, DLL or `StringFormat` use. Every narrowing cast
     is masked and every name carries the `pw_` prefix.
   - **Mutations:** 12 source mutations (CR handling, the window height, AI append order, nonce placement, D1 as unit
     2, the BOM, UTF-8 BOM skipping, astral characters, `isspace`, protocol 1, the trailing tab, state cid/magic) must
     each fail at least one golden.
   - **Result now:** `{"passed":73,"mutations":12,"productionSourceExecuted":true,"nativeCompileAndFileIoVerified":false}`.
   - **CI:** it is a step of the `controller` job (`controller-tests.yml`). The Python pin runs under that job's
     `unittest discover`.
4. **Native check (B44.1, needs a T3 window; ask Release).** A small script compiled with the B44.1 closure runs the
   real core with `FILE_BIN` into `MQL5\Files\GOAT\pw-check\` and prints SHA-256s. They must equal `g2/cases.json`
   and `g4/cases.json`.

**Why this method rather than a separate reference port.** A hand-written port in another language could share a bug
with the MQL source or silently diverge from it. This method executes the source that ships. Python stays the single
reference, through the same goldens beta.25 froze.

**What it leaves to the native check:**

- whether MetaEditor accepts the code (written to a conservative subset, but not compiled here; the other agent owns
  B44's compile);
- MQL's run-time string and `uchar` behaviour, which the source rules keep to operations where MQL and JavaScript
  agree: UTF-16 units, `StringLen`, `StringFind` and masked integers;
- the sandbox write and the kernel32 copy.

## 3. User flow and safety gates (L1)

**Flow:**

1. The person loads the portfolio rows in the dashboard, as today, on a demo account with Algo Trading off.
2. They click **Deploy All**. The dashboard checks every gate below and refuses in plain English with the typed code.
3. It creates a fresh `deploymentId` (32 lowercase hex): SHA-256 via `CryptEncode` over account, server, data path,
   `TimeGMT`, `GetMicrosecondCount` and the row SET hashes.
4. It freezes each SET into `Common\Files\GOAT\Deployments\<id>\` (create-only, hash read back).
5. It writes the profile (section 1.3 steps 1-4), the state TSV with `cid=0 magic=0` rows, and the adoption binding
   (Q2).
6. It shows: "Deploy profile ready. In MT5 choose File > Profiles > GOAT-Deploy-…. Algo Trading stays off; GOAT links
   each chart, then you can switch Algo Trading on."
7. After the switch, chart01 resumes (`Dashboard_Resume_Saved=true`) and adopts each child: an inert-only link pass
   with symbol, period, `CHART_EXPERT_NAME`, a unique magic, the nonce and `settingsMatch`, all unchanged. It then
   applies the exposure policy and writes the PDEPLOY marker for each child that acknowledges it.

**Gates.** All are checked before anything is written. Most are already on the B43 adoption path:

- **Demo only.** `ACCOUNT_TRADE_MODE_DEMO`. Not in the tester. Connected.
- **Algo off and inert.** `TERMINAL_TRADE_ALLOWED` is false, with `PositionsTotal()==0` and `OrdersTotal()==0`.
  - A profile switch does not change the terminal-wide Algo Trading button.
  - `expertmode=5` is a per-chart permission only, as on the controller path (D1, D2).
  - Real-money accounts are refused outright. B44 adds nothing on live.
- **DLL imports allowed.** Already an init requirement for the dashboard.
- **Inputs valid.**
  - 1 to 100 rows.
  - Every period is M1, M5, H1, H4 or D1.
  - No duplicate members, using the existing `GoatChildAuditInputs`/`GoatChildAuditValue`, which are the rules
    `refuse_duplicates` ports.
- **Create-only.** No existing `GOAT-Deploy-<id16>` folder, and no other staged deployment for this data folder.
  GOAT never writes `common.ini`, another profile, or anything outside its own new folder and its sandbox stage.
- **The nonce.** Every child carries `Studio_MonitorRunPath=deploy=<id>`. Adoption and `settingsMatch` pin it, so a
  hand-added chart with the same SET is never adopted.
- **The live-before-adoption gate is unchanged.** It is the first line of `DashboardEntryAllowed`: a `deploy=` child
  opens nothing new until its PDEPLOY marker exists. If someone switched Algo Trading on during the window, nothing
  could still open without the dashboard's exposure, risk and AI policy.
- **No `Enabled` and no `AllowLiveTrading`.** The core contains neither, and the harness bans both in the source.
- **Undo.** File > Profiles back to the previous profile. MT5 saved it at the switch and GOAT never writes it.
  Removing the deploy profile itself is left to the person (or `deploy-stop` when the app is present). GOAT never
  deletes a profile folder.

**T3 proof for L1** (needs a Release window; nothing here runs MT5):

- **P1.** A folder created while MT5 runs: does File > Profiles list it, or only after a restart?
- **P2.** After the switch:
  - chart01 starts with DLL imports allowed and its six inputs;
  - every child starts with `expertmode=5` and its inputs, the nonce included;
  - a `ChartSaveTemplate` readback is audit-equal to the SET.
- **P3.** The Algo Trading button is unchanged across the switch, and no child opens a trade before its marker.
- **P4.** The previous profile's manifest, before and after the switch, differs only by MT5's own save.
- **P5.** MT5's save of the deploy profile assigns `id=`, and the TSV `cid` equals it (the G3 invariant).
- **P6.** Switching back restores the previous charts.
- **P7.** The native byte check from section 2.

## 4. Scope and risk for a Thu 10-15 PR

**Done on this branch:**

- this design;
- the pure core, `GOATDeployProfileWriter.mqh` (no caller, not in any compile closure);
- the G4 goldens, generator and Python pin;
- the Node harness with mutations;
- a G4 row in `profile-deploy.md` §8.

**Still owed for a user-facing Deploy All:**

| Item | Size | Risk |
|---|---|---|
| Native shell: stage, create-only copy, readback, exact-folder check | ½ day | Low. The kernel32 calls are already in the closure. |
| Dashboard wiring: button, gates, ID, SET freeze, TSV, binding, plain-English refusals; guard tests updated deliberately (`DeployAll` and the retired-path greps) | 1-1½ days | **High merge risk.** It touches `Dashboard.mqh` and `GOATPortfolioSetupControl.mqh`, which the other B44 agent is editing now. |
| Adoption binding without a controller registration, plus the dashboard dispatching `apply_policy` itself for PDEPLOY markers (Q2, Q3) | ½ day of code plus at least one review round | **Contract change.** It needs Mac's ruling first. |
| Compile, by the B44 compile owner | | No compile has run for this code. |
| T3 proof P1-P7 | 1 window | **The load step is unproven.** |

**Recommendation: ship Deploy All as B44.1, not in B44.** By Thursday the bytes are proven. The load step and the
binding are not, and B43's lesson is not to ship a deploy path that has never been seen performing. Cutting the T3
proof to make Thursday would repeat that mistake.

Merging the core, goldens and tests now changes no binary: the core is not included anywhere, so B44's `identity.json`
closure is unaffected. B44.1 then adds the shell and wiring on top, after Mac's rulings and once B44's other items have
landed in the shared files.

## 5. Questions for the reviewer

1. **The load step.** Accept L1 (the person picks File > Profiles) as the dashboard's own path, subject to P1-P6? Or
   is the dashboard only the writer, with L2 (the app launches) as the only load path?
2. **The adoption binding.** B43 adoption takes `deploymentId` only from the controller's `registration.json`
   (`GOATPortfolioSetupControl.mqh:345-362`, which expires within 4 h). Without the app, which binding should replace
   it?
   - (a) an EA-owned `Common\Files\GOAT\Deployments\<id>\dashboard-deploy.json` read on resume;
   - (b) a `#GOAT_AI_LAUNCH_V147_3` TSV header that carries the ID. `saved_profile_links` already accepts any
     `#GOAT_AI_LAUNCH_V147_` prefix.
   - (c) the dashboard writing a registration itself. This mixes the owners, and the controller would then refuse its
     own deploys as "registration retained".
3. **PDEPLOY markers without the app.** May the dashboard dispatch `apply_policy` to its children itself, so the
   markers are written exactly as today (same command ID, ack and exposure mode), with no controller involved?
4. **kernel32 in the new include.** The shell would call the kernel32 functions already imported through
   `MTTester.mqh`/`WinAPI.mqh`, with no new `#import`. The guards would then pin that only `GOATDeployProfileWriter.mqh`
   and `MTTester.mqh` touch `Profiles\`, and that `Dashboard.mqh` stays DLL-free. Is that acceptable?
5. **Typed refusals in Python.** Should Python adopt `SET_ENCODING_UNSUPPORTED` and `PROFILE_VALUE_UNSUPPORTED` as
   typed refusals, so both writers return identical codes?
6. **Stricter MQL inputs.** Are the canonical-EA-path rule and the tab-free TSV field rule acceptable?
7. **M15 and M30** (the B42 list). If they land first, both writers and new goldens change together. Any objection to
   holding them until after B44.1?
