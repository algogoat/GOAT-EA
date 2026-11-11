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

## INV-EVID-01: a finished run keeps its own tester journal

**Incident (GOAT-EA#315, 2026-11-10/11).** MT5 cleared the tester's older day logs
(`Tester\logs\<yyyymmdd>.log`) when a later optimisation started. Banker's and T3's 11-10 logs
were gone when hunt round 13a's close needed the journal blocks of a finished catch-up, so
Banker's 33 catch-up blocks were held apart until their MT5 reports could stand in (Claude-Mac
GOAT-EA#315 6791427047 item 3, goatai#2750 6791842328).

**What MT5 does (read on T3 by Ops, 2026-11-11).** MT5 rewrites the tester's day log at every
optimisation start, today's file included, and removes the older ones: during a running Prove
batch the day log held only the lines since the current member's optimisation started, and a
234 MB log of the day before vanished when a batch started. A catch-up member is a single test,
not an optimisation: the day log survived all 83 members of a catch-up. So the copy exists
because the next optimisation start on that terminal destroys the log.

**Statement.** When a catch-up member ends, the controller copies that member's own lines of
the terminal's tester journal into its evidence before it launches anything else or returns
control, and records the copy (path, SHA-256, bytes, first and last line time) in the member's
stored result. A journal that is gone is recorded as missing with the reason, never invented.
The journal itself is only read. A round close counts a catch-up only when
`tester-journal-check` says every member's copy is in place and unchanged (`ok`) and is the
member's whole journal (`complete`): a copy cut at the bound, or one that lacks a day of its
run, is intact and still not complete. A Prove batch's
journal cannot be kept whole: the copy made at its finish holds its last member only, is
recorded as `covers: last_member_only`, and is never called complete. A Prove member's proof
stays its report, its `effective-inputs.set` and its capture (Claude-Mac goatai#2750
6792752258).

**Enforcement.**
- `controller/studio_tester_journal.py`: `keep` finds the run's block by the lines' own time
  stamps and copies it byte for byte (a member: plain, bounded; a batch: gzip); `verify`,
  `check_catchup` and `check_batch` re-hash every recorded copy and write nothing.
- Catch-up: `CatchupRunner._keep_journals` (`controller/studio_catchup.py`), called from
  `SeedRunner._settle_slot` (`controller/studio_seed.py`) before every settled save, so the copy
  is made in the pass that sees a member end and before the next member's launch. The record is
  the member's `tester_journal` in `catchups\<id>\state.json`.
- Prove batch: `studio_finish.finish`, under the native gate after the tester is proven idle and
  before `result.json` is written, copies what is left (`keep_batch`). The record is
  `tester_journal` in the result and in the job's completion, with `covers: last_member_only`
  and the first line's time in `covers_plain`.
- `demo_agent.py tester-journal-check --catchup-id <id> | --batch-id <id>`: exit 2 and
  `ok:false` (`TESTER_JOURNAL_MISSING`) when a copy is missing, changed, or the run is not
  finished. `complete` is computed apart from integrity (`coverage`): true only for a catch-up
  whose every copy is intact, not truncated and without a day of its run missing; each member
  row states its coverage and `partial` names the members that are not whole. For a batch it is
  always false and the sentence says the copy is not the batch's journal.

**Tests.** `controller/test_studio_tester_journal.py`: the block is copied byte for byte and
recorded, the journal untouched; found by halving in a log many blocks long; a day log that is
gone, or without a line of the run, is recorded missing and nothing is written; a run over
midnight; a line MT5 is still writing; the bound; a batch launched the day before whose day
log holds only its last member (copied, `covers: last_member_only`, the launch day listed as
gone); the real demo catch-up lane end to end (each member's block in its evidence folder, the
check passes and is complete; a member cut at the bound, and a member over midnight whose next
day's log is gone: intact, `ok`, and not complete, with the coverage stated per member; no
journal: recorded missing and the check refuses with exit 2; a
copy altered or removed afterwards: the check refuses); the real batch finish (copied and
recorded in `result.json`, the check intact but never complete; no journal: the batch still
finishes and the check refuses).

**Not covered.**
- Every Prove member but the last has no journal copy. Copying each member's block would have
  to happen between the terminal's exit and its relaunch at a member boundary. The EA drives
  that (`GoatBatchRequestDeferredRestart`, `TerminalClose` in `Tester.mqh`; the relaunch command
  in `AddCommand` waits for the exit and 500 ms); the batch driver only polls
  (`studio_batch_driver.run`, every `poll_seconds`, 30 s by default), so it cannot be made from
  the controller without a watcher. The place that is closed-and-not-yet-relaunched is the EA's
  relaunch command.
- A Prove batch's copy is made while MT5 is still open. Lines MT5 has not written to disk yet
  are not in it; the record's `last_line_time` shows where the copy ends.
- Seed hunts and hold-up tests keep no journal copy.
- Batches settled without `finish` (retired before activation, self-repair) keep none: they
  never ran a test.
- The block search relies on a day log being in time order. One real T3 day log (17,414 lines,
  read by Ops on 2026-11-11) had no line earlier than the running maximum. A log that is not in
  order gives a `missing` record, never a wrong block.
- Runs that ended before this controller version have no record; the check reports them missing.
