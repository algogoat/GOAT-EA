# GOAT operating invariants

Each invariant names a property the EA and controller must always keep, where it is
enforced, and the tests that pin it. A change that touches an enforcement point must keep
its tests passing and say so in the pull request. Exact-head review is required.

## INV-BATCH-01: every MT5 terminal/account runs its batch state independently

**Statement.** Two MT5 terminals on one PC never share an active run pointer, optimization
config, launch guard, controller owner marker, queue, export settings, log or tester fitness
file. Each terminal and account keeps its own Common batch folder:

`Common\Files\GOAT\<EA>-<server>-<login>-<terminal hash>`

The terminal hash is the first 8 hex characters of SHA-256 over the terminal's data path
(separators `\`, no trailing `\`, ASCII `A`-`Z` lowered). Example:
`GOAT\GOAT V1.49-Darwinex-Demo-3000082754-c2408708`. V1.48 and older builds keep the shared
pre-isolation folder `GOAT\<EA>-<server>`.

**Why the hash as well as the login.** MT5 allows one account to be signed in on several
terminals at once, and a copied portable terminal keeps its saved login. A login-only folder
would still be shared by those terminals. The login stays in the name so an operator can see
which account a folder belongs to, and so an account switch inside one terminal gets its own
state.

**Enforcement.**
- EA: `GoatOptBasePath` and its run/queue/export/log/report helpers
  (`GOAT_Inputs_Definitions.mqh`, `GOAT_TERMINAL_ISOLATION_V149`). Native dispatch and cancel
  (`GOATStudioDispatch.mqh`) use the same helper after verifying login and server.
- EA, tester side: agents never resolve the namespace. The running fitness file is one per
  optimization run: OnTesterInit draws a nonce and hands it to every agent through the
  `GOAT_FitnessRunNonce` input (`ParameterSetRange`), and it refuses the optimization before any
  batch state changes if that fails. The file is keyed by EA, `EA_Desc`, symbol and the nonce
  (`GoatOptTesterFitnessFile`), so two terminals optimizing the same strategy never share it.
  Agent waits are bounded by `GetTickCount64` (`Sleep` returns at once in the tester), and the
  running maximum is rewritten only after it was actually read. The native readback accepts the
  nonce only as a plain, non-optimized integer.
- EA: the Studio observation publishes `state_base`; `GoatStudioRecoveryCommonClear` ignores
  other terminals' folders but still blocks on this terminal's folder and every shared one.
  "Other terminal" is decided by the terminal hash alone, case-insensitively: this terminal's
  folder under any login, its `-0-` folder and case variants always block.
- Controller: `controller/studio_terminal_isolation.py` resolves the same name. `preflight`
  runs before controls are installed (`studio_open_activation._install_controls`, used by
  open and config/restart starts) and before seed starts (`studio_seed._activate`). In one
  plain sentence it refuses when the running EA reports another folder, when the running EA
  predates isolation, when any other live MT5 terminal resolves to this terminal's folder,
  when a live terminal's program path or data folder cannot be read (fails closed), or when
  the one-time move below cannot complete.
- One-time move of shared pre-isolation state (EA `GoatOptMigrateLegacyBatchState`, controller
  `migrate_legacy`, identical rules). Files are moved, never discarded or overwritten:
  - controller-owned controls (`agent-native-control-owner.json`) are never moved;
  - an in-flight batch moves only to the terminal holding its batch flags, and an idle pointer
    only to the terminal whose local Files hold the pointed run;
  - if the shared folder and this terminal's folder both hold state, nothing moves and the user
    is told to keep one and archive the other;
  - only the terminal named by the shared folder's create-only claim
    (`terminal-isolation-claim.ini`, login and terminal hash) moves anything. Chart locks and native
    gates are per terminal; the claim decides across terminals, including a copied portable
    terminal that carries the original's batch flags and local runs. **Rollout: load SM32 on the
    original terminal (Banker) first**, so it claims its own shared state;
  - an interrupted move resumes from its `moving` receipt: names are validated against the
    known files, a guard already in place is only completed, and staged writes land by create-only
    rename and are rewritten (EA) or freshly named (controller) on a retry, so a crash never leaves
    a permanent refusal;
  - the launch guard's `ConfigPath` follows the moved config, and its old value is recorded;
  - `terminal-isolation.ini` in the new folder records the decision once, and
    `migrated-to-<login>-<hash>.ini` in the shared folder records where state went.

**Tests.** `controller/test_studio_terminal_isolation.py` (formula pins, two terminals on one
EA+server, same-folder refusal, fail-closed inventory, migration, the both-exist refusal, the claim,
crash resume and a two-terminal interleaving at every file operation);
`scripts/test_terminal_isolation.cjs` (the production MQL functions in a JS VM, same pins: the mover
and its wrapper, the claim, every interleaving of two terminals moving at once, resume, the
fitness block and the OnTesterInit nonce); `scripts/test_terminal_isolation_mutations.cjs` and
`scripts/test_terminal_isolation_controller_mutations.py` (each guard removed must fail the tests);
`controller/test_studio_orphan_recovery.py`
`test_other_terminal_batch_state_never_blocks_but_own_and_shared_folders_do`.

**Not covered.** `GOAT\SeedFarmingXML` file names include the strategy alias but not the
terminal; controller seeds use unique aliases, so only two hand-run seed farms with the same
`EA_Desc`, symbol, timeframe and dates collide. The manual-export fallback
`TEMP\<EA>-<server>` and the `_export_read`/`_export_delete` temporary names are shared but
named per attempt.

## INV-CRED-01: each MT5 login keeps its own GOAT credential

**Statement.** Pairing one terminal never replaces or reads another account's credential.
V1.49 isolation builds store the GOAT user credential at
`Common\Files\GOAT\Credentials\api-bearer-v149-<login>.token`.

**Enforcement.**
- The login comes only from the terminal's own `AccountInfoInteger(ACCOUNT_LOGIN)`
  (`GOATAccountLoginDigits`) or, in the controller, the verified session receipt
  (`credential_relative_path`). It must be digits; anything else yields no path. With no
  account the EA uses an unwritable placeholder, never the shared file.
- `GOATDeviceActivationWriteCredential` refuses unless the terminal's login equals the account
  the user just approved.
- `GOATDeviceActivationWriteCredential` computes the path once from the approved account, so a
  login that reads 0 mid-write can never redirect it.
- Copy-only migration (`GOATCredentialMigrateLegacyOnce`): the shared
  `api-bearer-v149.token` is copied to this login's file only when an `approved` activation status
  for this login, from a V1.49 build, is no older than the shared file and no such status exists for
  another login. Only `approved` is proof: `activation_reload_pending`, `ACTIVATION_RELOAD_REQUIRED`
  and `activation_oninit_observed` also follow a credential merely found on disk (older builds write
  them too), so they never count. Because the reload statuses usually replace `approved` within
  seconds, most terminals pair once after the upgrade. The shared file is never deleted or changed,
  the copy is create-only, and the shared file is never opened unless it is proven to be this login's.
- The activation request cooldown (`activation-admission.bin`) stays shared on purpose: it holds
  no account data and is the per-host request budget.

**Tests.** `scripts/test_terminal_isolation.cjs` (two terminals licensed at once, A pairs while
B stays licensed and the reverse, account mismatch refused, a login reading 0 mid-write, migration
proof cases including every non-`approved` status);
`controller/test_studio_terminal_isolation.py` `CredentialPathTests`.

## INV-PROVE-01: a Prove member runs only the inputs its own SET states

**Incident (GOAT-EA#315, hunt round 13a, found at the close on 2026-11-11).** In three Prove
batches on B54, every member after the first one whose SET set `Ledger_Mode=1` exported with
`Ledger_Mode=1`, although its own SET omitted it: 61 exports were proved on
`Ledger_PositionJoin` unasked. The Prove report marked each of them `unverified`
(`Fixed export input mismatch: Ledger_Mode`), but the batch result did not say so and
`evidence-scan` never read it, so the exports were re-tested as they were.

**Statement.**
1. No Prove member runs a value the tester kept from the member before it. Until the EA names
   every declared input in every member's config itself (the SET's own values, and every input
   the SET omits at its compiled default; due with B55), a batch whose members do not all state
   the same inputs is refused at `prepare-batch`.
2. An export the Prove report marks `unverified` is never planned for a catch-up, or counted,
   without a disclosed tag.

**Enforcement.**
- Part 2, controller. `studio_export_scan.unverified_summary` puts the count, the members and
  the inputs involved into the batch result (`unverified_exports`, written by
  `studio_finish.finish`). `studio_catchup.UnverifiedExports` reads the retained results;
  `apply_unverified` marks such an export `ineligible` (`UNVERIFIED_EXPORT`) in `evidence_scan`
  and in `CatchupRunner._build`, unless the plan's `disclosed_unverified` names its SET SHA-256
  with the tag it is counted under. The tag is carried on the row, the member and its evidence
  version (`original.unverified_disclosed`). What `unverified` means is unchanged
  (`studio_export_scan.scan_exports`, `studio_export_inputs.verify_export_inputs`).
- Part 1, controller: enforced by refusal. `studio_batch.check_member_inputs`, called by
  `prepare_batch` for new staging before anything is staged, refuses `BATCH_MIXED_INPUTS` when
  an input is stated by some members' SETs and omitted by others, and lists each such input
  with the members that state it. `EA_Desc` (set per member by the batch) and the appended
  optimization axes the EA writes itself (`studio_optimization_inputs.self_named_inputs`) are
  not compared. A batch whose members all state the same inputs is safe after any other batch,
  because its first member starts from a complete config. The refusal does not apply on a
  build listed in `studio_batch.BUILDS_NAMING_EVERY_INPUT` (none today).
- Part 1, EA: the fix itself goes into `GoatStudioExplicitOptimizationInputs`
  (`GOATOptimizationInputs.mqh`), which must write every declared input a member's SET omits,
  not only the appended optimization axes. `Inputs.GOAT` stays the frozen SET bytes. When a
  build does this, its build ID is added to `BUILDS_NAMING_EVERY_INPUT`.
- Why pinning the member inis the controller stages would not have reached the members that
  leaked:
  - The first member is complete. Its startup config is built from the paste inputs, which carry
    every contract input (`studio_input_readback.explicit_paste_inputs`), plus the runtime pins
    (`studio_startup_config.startup_config`), and the tester profile is written from those bytes
    (`studio_config_start`, `studio_tester_profile`). Only member 0 feeds that payload
    (`studio_native_request._validate_material`).
  - Every later member is launched by the EA, not the controller. `ActivatePending`
    (`Optimizer.mqh`) reads the member's `inputs\<alias>\Inputs.GOAT`, passes it through
    `GoatStudioExplicitOptimizationInputs` (`GOATOptimizationInputs.mqh`), writes that as
    `[TesterInputs]` into `inputs\<alias>\config.ini` and the active config, and relaunches MT5 on
    it (`AddCommand`, `Tester.mqh`). The `<alias>.ini` the controller staged is overwritten.
  - `Inputs.GOAT` is the member's frozen SET, byte for byte
    (`prepare_native_campaign.prepare`), and `GoatStudioExplicitOptimizationInputs` adds only the
    appended optimization axes a SET omits. So an omitted appended `sinput` or string is never
    named: `Ledger_Mode`, `Engine_Mode`, `Clock_Mode`, `Server_Clock_Model`,
    `Server_UTC_Offset`, `NY_Session`, the nine B49b inputs, `Random_Direction`,
    `Single_Flat_Only`, `BRK_Mode`, `ORB_Mode` and `ORB_Clock`, and the inputs declared outside
    the contract (`studio_tester_report.RUNTIME_INPUT_DEFAULTS`).
  - The rule that a batch never mixes members that state one of those inputs with members that
    omit it (Claude-Mac GOAT-EA#315 6791427047 item 4a) was applied by hand before
    `check_member_inputs`.

**Tests.** `controller/test_studio_unverified_exports.py`: the real scan marks an export that
inherited `Ledger_Mode=1` `unverified` and passes one that matches its SET (omitted on both
sides, and stated as 1 on both); the batch summary counts them and names the input; the real
`finish` stores it in `result.json` and the job's completion; `evidence_scan` marks the
unverified export `ineligible` with the reason and leaves the clean export of the same batch;
a disclosed export stays eligible and carries its tag; a library copy is found by its SHA-256;
only the export's own run is read, and an unreadable result refuses; the planner never plans an
unverified export, plans the clean one, and plans a disclosed one with the tag on its member.
`controller/test_studio_batch_mixed_inputs.py`: `prepare-batch` refuses a member that sets
`Ledger_Mode=1` before one that omits it (either order), names the input and both members and
stages nothing; round 13a's real p1 composition
(`controller/fixtures/round13a-t3-prove-p1-member-inputs.json`: the names each of the 28
members of `hunt-t3-depth-prove-13a-p1` states) is refused naming the eight inputs and members
17, 20 and 25, and the same plan without those three members is prepared; members that all
omit or all state an input (same or different values), a single member, and an omitted
appended optimization axis are prepared; a build listed in `BUILDS_NAMING_EVERY_INPUT` is not
refused and any other build is; on the real contract every appended input the EA does not name
is refused when mixed, and the exempt set equals what `GOATStudioSettingTypes.mqh` gives
`GoatStudioExplicitOptimizationInputs`.
`controller/test_studio_appended_inputs.py`
`test_a_set_without_it_is_prepared_staged_reused_and_read_back` pins that the staged member ini
does not name an omitted `Ledger_Mode`.

**Not covered.** A batch prepared before `check_member_inputs` existed is not refused when it
starts, and a repeated `prepare-batch` of it is reused as before. The refusal compares the
names a SET states, not what MT5 ran; what ran is part 2's report check. An `unverified`
export with no readable SET (an incomplete SET/CSV pair) is counted in the batch summary but
has no SHA-256 to match in a scan. The board counter that reads `unverified` lives outside the
controller.
