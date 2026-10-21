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
