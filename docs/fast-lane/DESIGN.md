# Fast lane: Stop / Start / Continue, the EA Studio path vs the controller path

## Finding first: does a manual Studio Start produce the XML that exports need?

**Yes.** The difference from the agent's direct `GOATStudioDispatch` Start is the `/config` relaunch.

- **Manual Start.** `Optimizer.mqh` `OnClickStart` runs `UpdateBatchQueueAndWriteConfigFile`, which calls `ActivatePending`.
  - `ActivatePending` writes `active_optimization_config.ini`: the queue item's `[Tester]` with `Report=…` (`Optimizer.mqh` 3749) and `[TesterInputs]`. It also writes a launch guard.
  - It then calls `AddCommand` (`Tester.mqh` 29). That starts a hidden PowerShell which waits for **this terminal** to exit and launches `terminal64.exe /config:<ini>`.
  - `GoatBatchTryCloseTerminalWhenTesterIdle` then sends `TerminalClose`.
  - MT5 writes the main and `.forward` reports only for a test started by a `/config` launch with `Report=`. `OnTesterDeinit` then migrates both into the run's `reports` root and exports.
- **Agent `start` action.** `GoatStudioExecuteRequest` pastes settings over the clipboard (`SetSettings2`) and sends `MTTESTER::ClickStart(false,1)` inside the running terminal. There is no `/config` launch, so MT5 writes no report. DEINIT then logs `XML Migration incomplete … files=0` (T2, 2026-10-02).
- **Every later member.** Both paths are identical from member 2 on. The EA's own `ActivatePending` → `AddCommand` → `TerminalClose` relaunches with `/config`. Only the first member differs.

So a report-producing start needs the MT5 restart; the manual Studio restarts too. The controller's config start (`arm_restart` → `RESTART_ARMED_RECONCILE` → normal close → `/config` launch) is that same mechanism with retained phases. **PR #120's route stands.** The smaller fix is not to avoid the restart. It is to stop the controller's own start overhead from outgrowing its 120 s process window, as tonight.

## What the start overhead really was (measured)

| Measurement | Number |
|---|---|
| Banker g6-r1, 1122 members: baseline taken → first re-check | 206 s (121 s reserve + intent, 85 s launch material), so it failed `Process baseline is stale` |
| Banker `studio.sqlite` size | **7.8 GB** |
| Synthetic 1200 members, one full per-member pass (this PC) | `_verify_package` 2.1 s, `record_intent` 1.6 s, `_validate_material` 2.0 s |
| Store with 8 retained 300-member jobs (19 MB queue row) | `state()` 0.22 s, `queue.reserve` 1.7 s, `record_intent` 0.9 s |
| Sealed 1200-member passes (CI test) | `_verify_package` 0.9–1.0 s, `record_intent` 0.3 s, `_validate_material` 0.2 s; **total 1.4–1.6 s vs 3.0–5.9 s unsealed** |
| `stop` of a never-activated 1200-member start (CI test) | **3.1 s** |

The member checks cost seconds. Banker's minutes came from the **queue row**. Every `state()`/`job()` call parses it, and reconcile appended every changed native observation to `native_evidence_history` inside it: per-member statuses, input artifacts, report pairs and runtime feedback. Nothing reads that history back. A start makes dozens of state reads.

## Per operation: EA Studio path vs controller path

Reliability evidence is from tonight's Banker run unless marked with a date.

| Operation | EA Studio (manual / native) | Controller (agent) | Recommendation |
|---|---|---|---|
| **Queue / prepare** | The dialog edits `queue.GOAT`. In managed mode the dialog only sends `queue.*` commands to the controller store (`ManagedQueueSubmit`), so it is already a front end to the controller queue. `PreflightQueueInputs` checks inputs at Start. | `prepare-batch` validates every member against the shipped schema and dependency policy, then freezes configuration, SET, INI and manifest by hash. This takes 50–70 s for 1200 members and is done once. | **Controller.** The EA has no frozen provenance or schema validation at the scale of 1000+ members. Fast lane adds the seal here. |
| **Start** | `OnClickStart` needs a **MessageBox OK** (human only), then a `/config` relaunch via `AddCommand` and `TerminalClose`. Reports: yes. | Config start: precheck, reserve and intent, then arm, normal close, `/config` launch, all with retained phases. It never replays an uncertain phase. Reports: yes. Failure seen: the O(members) work plus store parsing outlived the 120 s baseline. | **Controller primitive** once fixed: it is journaled, observation-only on interruption, and needs no dialog. Fix: seal (O(1) identity plus one byte-hash pass), baseline taken after the controller-only work, rolling 120 s checks, evidence log. 1200-member verification goes from about 13 s across all passes (Banker: 206 s) to 1.6 s. |
| **Cancel / stop (dispatched)** | `OnClickStop`: cancel GV, delete guard and config, `ClickStop`, mark the queue Cancelled. | `GoatStudioCancelRequest` makes **the same effects** as the STOP button, with exact owner, pointer and account checks. The controller then observes it and finishes. | **EA primitive via the existing mailbox.** Already the case; unchanged. |
| **Stop (never dispatched)** | Nothing to stop: the EA never saw it. | Before: no settlement, so `STOP_UNCONFIRMED` / "reconcile, do not reset" left a dead end. | **Controller.** `retire-unactivated` (#123) proves no native contact, then settles to `cancelled`. `stop` routes to it. 3.1 s at 1200 members. |
| **Stop (pending / reserved)** | Remove or Delete All on the queue. | `queue.cancel`; `queue.release_reservation` when the reservation was never permitted. | **Controller** (same store). One `stop` now covers both. |
| **Continue / resume** | Start again on the remaining Pending rows. Cancelled rows need a manual edit. No lineage. | `resume-batch` / `batch-resume`: selection from per-member native evidence (no-edge results are kept), new ID, lineage. Failure seen: it refused after an EA build change, so the remaining plan was rebuilt by hand. | **Controller.** `continue` reads the finished package under its own recorded binding (it is never launched again), then re-prepares and **fully verifies** the members under the current build. Never-run members come first, then failures if asked. |
| **Export reports** | `OnTesterDeinit`: migrate main and forward XML, combine, export. | Same EA code; the controller only verifies report pairs at finish. | **EA.** It requires the `/config` start above. |
| **Crash recovery** | EA INIT recovers a matching OnGoing/Queued item and resets a mismatch to Pending (`STALE_STARTUP`). | Driver journal, retained restart phases, reconcile, observation-only on uncertainty; the journal survives an MT5 restart. | **Both.** The EA recovers the native queue; the controller journal decides what the agent may do next. |
| **Provenance** | `queue.GOAT`, per-strategy `Inputs`, audit `config.ini`, timeline. Nothing binds them to a frozen request. | Frozen configuration hash, staged hash per member, manifest, seal. `observe()` re-hashes **every** member's `Inputs.GOAT` at each reconcile and at finish. Evidence log. | **Controller.** |
| **Scale to 1000+ members** | File reads are fine; the human dialog is the limit. | Fixed in this PR: verification is O(1) plus a hash pass, and the queue row no longer grows with observations. | **Controller**, with this PR. |

Result: a hybrid. The controller keeps planning, provenance, research and the first-member config start. The EA keeps member progression, native cancel and exports. The faster and more reliable start primitive is the controller's once its O(members) start verification and store growth are fixed. The numbers above are the evidence.

## Checks kept, and why

- **Kept at every start:**
  - fresh process identity, with every gap ≤ 120 s and identity unchanged from the precheck;
  - EA runtime: demo, Algo off, idle, not `batch_ongoing`, bound account;
  - ownership and generation, human inbox (TAKE CONTROL), owner STOP and deadline at every checkpoint;
  - research authority, disk guard, EA and monitor binary hashes;
  - byte identity of **every** member's staged SET and INI (hash pass) and of every preparation file;
  - the full semantic check of member 0, whose bytes feed the native paste and startup payload.
- **Replaced by the seal:** the semantic re-parse of members 1..N, roughly seven times per start. It is a pure function of bytes, configuration, schema, EA version and the checking code. The seal binds all five: `checker_sha256` hashes the checking modules (including `studio_batch.py`, `studio_launch_intent.py` and `studio_batch_contract.py`), so a controller upgrade such as #121's input pinning invalidates older seals and forces one full pass. A missing or foreign seal, or any changed byte, falls back to the full checks, which raise the precise error.
- **The seal is a cache / performance aid, not a safety boundary.** `seal_sha256` only hashes the seal itself, and the manifest it binds is also a local file. Someone who can rewrite a staged SET and the manifest can write a matching seal, and then members 1..N skip their semantic re-check. Member 0, every byte hash against the manifest, and the frozen configuration hash are still checked. Follow-up (TODO in `studio_batch_seal.py`): bind the seal or manifest digest into the job row at enqueue and require it in `sealed()`. That changes the `queue.enqueue_batch` contract, so it is not in this PR.
- **Not weakened:**
  - Continue reads an old package across a build change only when it is **finished**. That package is never launched again. Its successor is prepared and verified under the current installation, and prepare still checks the physical EA hash. A schema change that invalidates old inputs still refuses.
  - `retire-unactivated` sends nothing to MT5 and proves no contact under the native gate.

## One command per intent

| Intent | Agent (demo lane) | Controller CLI | Refusal shape |
|---|---|---|---|
| Stop | `demo_agent.py stop` (active batch; owner STOP set) or `stop --batch-id <id>` (one unstarted batch, no STOP) | `goat_studio batch-stop --job-id <id>` | one sentence plus the next command |
| Start | `demo_agent.py start --batch-id <id> [--max-seconds N]` | `goat_studio run-batch --job-id <id> --max-seconds N` | "Owner STOP is on; run clear-stop, then start again." |
| Continue | `demo_agent.py continue --batch-id <id> [--include-failed] [--clear-stop]` (prepares and starts) | `goat_studio batch-continue --job-id <id>` (prepares only) | "Batch X is still running; stop it first: stop --batch-id X." |
| Keep reads fast | — | `goat_studio compact-evidence [--apply]` | refuses while a batch is active (checked before any archive and again inside the queue transaction); skips a job whose never-started retirement proof compares the whole row |

Evidence log and compaction details:

- **Idempotent appends.** Each log line carries a deterministic identity (job, attempt, sequence, evidence hash). The row records the committed byte length. If a crash lands between the fsync and the queue commit, the retry adopts an identical uncommitted tail. A different tail moves to `<log>.uncommitted` first. Lines are never duplicated and the entry count stays exact.
- **Compaction memory.** The size comes from `SELECT length(jobs)`. Archives are serialised one entry at a time, written to a temp file, fsynced, verified by sha256 and atomically renamed. The first parsed copy is dropped before the transaction parses the row again. Inside the transaction, each archived history is re-hashed against the current row. The result and the `native-evidence/compactions.jsonl` journal come from the transaction, with no read after the commit.
- **Scale test.** `LargeQueueRowTests` builds Banker's shape scaled down: 29 jobs, about 42 MB of history and 4 MB of other data. The real row is 818 MB, 770 MB of it history. Compaction must shrink the row to about the non-history size, and a state read must stay bounded.

## Follow-ups

- Desktop buttons (goatai, `claude-pc/fast-lane-buttons`): Stop / Start / Continue on the lane card, calling these commands.
- Banker: after #123, run `compact-evidence --apply` once while idle. It moves the retained in-row history to verified logs and shrinks the parsed queue row. The SQLite file stays the same size until a separate reviewed `VACUUM`.
- The open-terminal `start` route (non-demo, `Controller.start`) keeps its single baseline; #120 replaces that route with config start.
- **Receipts store a queue digest, not the queue.** Every `studio_receipts` row embeds the full `state`, queue included. On Banker each receipt is 818 MB (62 receipts = 9.78 GB of an 11.4 GB DB), which is why each start attempt grows the DB by ~1.6 GB and reserve + intent takes ~121 s. Nothing reads `receipt.state.queue` back: the bridge outbox and the authority/regrant/owner-research scans read only `owner`, `generation`, `revision`, `terminal_id` and `run_id`. Idempotent replay compares only `payload_hash`. Replacing the queue with `{sha256, job_count}` is safe. Legacy rows must be migrated, or the scans must stop parsing whole receipts.
- **Typed research continuation + Continue.** `batch-continue` refuses in a `research_continuation` session with one sentence, because that authority covers only the exact frozen plan (`members_sha256`). Authorizing a generated remaining-members plan needs its own reviewed provenance.
- **Seal binding.** Bind the seal or manifest digest into the job row at enqueue and require it in `sealed()` (see the seal note above).
