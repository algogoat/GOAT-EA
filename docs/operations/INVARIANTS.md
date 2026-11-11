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

## INV-CONTRACT-01: order-bearing contract data is never read from a key-sorted copy

**Incident (GOAT-EA#317, hunt round 13a wave 3, 2026-11-11).** Seed SETs used the EMA trend
term as an axis, `EMA_Mode=1||0||1||2||Y`. `ENUM_MODE_TRADE` is declared 0, 1, 2, 3, 4, 5
(`GOAT_Inputs_Definitions.mqh`), so 0..2 by 1 is a native ladder. The seed lane accepted it and
MT5 walked 0, 1, 2. `prepare-batch` accepted it in its own plan check and then refused it at
the store's queue check, after the batch was staged: `ENUM_LADDER_NOT_NATIVE ... declared in
order 5, 4, 0, 3, 1, 2`, leaving a retained package and a burnt batch ID. The store held
`json.loads(packed(schema))`, and `packed` sorts keys, so every enum's choices were in name
order. 34 optimizable enums had another order in that copy: native ladders were refused on 29
of them, and a ladder that is not native was allowed on five (`Trailing_Sample_Period` and the
four `*_Price` inputs) wherever only the store's copy was read (the draft check).

**Statement.** An enum's declaration order is the order of its `enum_choices` in the input
contract, and every check that depends on it (`check_enum_ladders`) reads a schema in that
order. The store's copy of a contract is in the order it was given, and a copy whose order
differs is refused, not judged by. A contract's hash is the hash of its canonical packed form
and does not depend on order, so no store, seal or receipt identity changes with it. The seed
lane and `prepare-batch` run one set of SET validators on one order, so they give the same
answer on the same SET.

**Enforcement.**
- `studio_command_store.held_contract`: `StudioStore` holds the input schema and the dependency
  policy as detached copies in the given order and compares each copy with what it was given,
  key order included (`CONTRACT_ORDER_LOST`). `input_schema_hash` is `sha` of the copy, the
  value it always was. The dependency policy has no order in its keys (its rules are a list);
  it is held the same way so there is one rule.
- The store's copy feeds `validate_strategy` for `draft.replace_strategy`, `change_queue`
  (`queue.enqueue`, `queue.revise`, `queue.enqueue_batch`), the launch-intent member check
  (`studio_launch_intent`) and the report check at reconcile (`studio_reconcile`).
- `studio_batch.prepare_batch` runs the store-side queue check (`studio_queue.change_queue`, on
  the store's own schema and policy) before anything is staged, so a member the store refuses is
  refused before a package exists and the batch ID stays usable. After staging, `store.submit`
  can still refuse for state only: a stale revision or generation, another owner, the research
  authority scope, a batch ID taken meanwhile.
- The contract is loaded in file order (`studio_installation.contracts`, `read_json`); the seed
  lane (`studio_seed._freeze`) and `prepare-batch`'s plan check (`studio_batch.read_plan`) read
  that object.
- One set of SET validators. Both lanes call `validate_raw(..., require_optimization=True)`
  (structure and axes, `check_risk_sizing`, `check_pretrade_caps`, `check_enum_ladders`,
  `check_ea_init`, `check_risk_chosen`, the dependency audit) and `check_tester_init` with the
  run's own `FromDate` (`studio_batch.prepare_batch`; `studio_seed._freeze`, for
  `seed-validate` and `seed-prepare`). Not shared, because they cannot apply to the other
  lane: the batch shape (`studio_queue.validate_batch_members`: custom forward, one export
  policy and forward boundary) and the seed's exact axis precision and `ForwardMode=0`.

**Tests.** `controller/test_studio_store_schema_order.py`, on the real v149 contract and a
controller opened as production opens it: the store holds every enum in the contract's order
and `EMA_Mode` as 0..5; the schema hash is the value the sorted copy gave; the sorted copy's
refusal of the wave 3 ladder, reproduced; a copy that loses the order is refused;
`prepare-batch` accepts, stages and queues `EMA_Mode=1||0||1||2||Y`; the seed lane and
`prepare-batch` both accept it and both refuse `RSI_TF_=15||5||10||15||Y` before anything is
staged; a member only the store refuses is refused before staging and keeps its batch ID; the
five ladders the sorted copy allowed are refused through the draft path, and native ones pass;
the three store paths without prepare-batch's plan check (the single-job `prepare`, a raw
`submit`, a bridge request) each refuse `RSI_Price=5||5||1||6||Y` and accept the wave 3 ladder.
`controller/test_studio_enum_ladder_native.py` `CompactControllerPaths` now builds the store's
copy as production does and prepares the native `RSI_TF_=1||0||1||1||Y` through it.
`controller/test_studio_ea_init_rules.py` `SeedLaneTesterTests`: a tester-refused job fails at
`seed-validate` and `seed-prepare` naming the job, and nothing is prepared; allowed jobs
validate; the rule that reads the test start uses the seed job's own `FromDate`.

**Not covered.** A schema that is already key-sorted when it is handed to the store cannot be
told from the contract there; `contracts()` is the only loader. Other test fixtures still
assign the schema object straight onto the store (`test_goat_studio.PortableControllerTests`).
A seed batch prepared before `check_tester_init` joined the seed lane is not checked again
when it starts or resumes. On the v149 contract the seed lane refuses a SET that omits the
appended optimization axes (`Pinned seed inputs changed a template trading value`,
`studio_seed._freeze`), which `prepare-batch` accepts: the lanes still differ there.
Whether the EA's `OnTesterInit` range check accepts `EMA_Mode` 0..2 in a Prove batch is not
shown by a run; it is the form the rule calls native.

## INV-LINEAGE-01: a promoted SET and its fork are linked by SHA-256, never by name

**Incident (hunt round 13a close, 2026-11-11).** 22 migrated October files traced to their seed
job only by design, symbol and a fork name containing "seed 1013": none of the seed batch's
promotion receipts carried a fork's SHA-256 (Claude-Mac goatai#2750 6793727135).

**Statement.** A promotion receipt names every SET it writes by SHA-256 and by the SHA-256 of
its canonical inputs. The strategy-library fork made from a promoted SET is recorded on that
promotion by its own SET SHA-256 when it is made, and any SET can be looked up to its
promotion from its bytes alone.

**Enforcement.**
- `controller/studio_seed_promote.py`: `promote` writes `sha256` and `canonical_sha256` for
  `fixed_set` and `robustness_set` into `promotion.json`. `record_fork` (`seed-promote-fork`)
  reads the fork SET and writes `promoted\<alias>\<candidate>\forks\<fork set sha256>.json`,
  create-only, with the fork id, the relation (`exact`, `same_inputs`, or `edited` with the
  changed inputs) and the receipt's SHA-256; `promotion.json` is never rewritten. `lookup`
  (`promotion-lookup`) is read-only and matches a SET as `promoted_set`, `recorded_fork` or
  `same_inputs`.
- The fork itself is created by the desktop (`strategy.forkTemplate`); the controller has no
  register command. The desktop half is to call `seed-promote-fork` with the fork's SET and id
  right after it creates a fork from a promoted SET, or to store the promotion's
  `candidate_sha256` and receipt SHA-256 in the fork's own record.

**Tests.** `controller/test_studio_seed_promote.py`: the receipt names each SET by both
hashes; a fork is recorded on its promotion and found again by its SHA-256 alone (before the
record, the same SHA-256 finds nothing); lookup matches a promoted SET and a renamed copy by
its inputs, and nothing for other inputs; an edited fork is recorded as edited with the inputs
it changed; an older receipt and an unreadable one. `controller/test_demo_seed_agent.py`: both
verbs through the demo lane.

**Not covered.** A fork nobody records is found only while its inputs are unchanged
(`same_inputs`, with the SET file). Forks made before this exist only in the desktop's library;
their records can be added with `seed-promote-fork` from the fork SETs. `goat_studio.py` has no
copy of the two verbs.
