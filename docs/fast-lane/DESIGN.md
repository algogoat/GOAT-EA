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
- **Protected peer: identity, not PID.** The rolling baseline compares the research terminal exactly at every check. The reviewed peer (for example QA next to Banker) is compared by identity: its executable, data root and origin binding, re-proved from the files on every binding read. When the lane's EA is isolated (V1.49 per-terminal/login batch folder) and the peer's data root hashes to a different folder, a peer that restarts, closes or reopens before or during a start is accepted and journaled (`peer-instances.jsonl`, old and new PID), never re-reviewed. `continue` / `batch-resume` no longer re-review a restarted peer, so the policy hash and every package binding stay the same and nothing prepared is invalidated. Unknown MT5 processes, a second peer process and a changed peer executable or data root still refuse. A running driver never inventories terminals (the EA advances members), so a peer restart cannot affect a running batch.

## One command per intent

| Intent | Agent (demo lane) | Controller CLI | Refusal shape |
|---|---|---|---|
| Stop | `demo_agent.py stop` (active batch; owner STOP set) or `stop --batch-id <id>` (one unstarted batch, no STOP) | `goat_studio batch-stop --job-id <id>` | one sentence plus the next command |
| Start | `demo_agent.py start --batch-id <id> [--max-seconds N]` | `goat_studio run-batch --job-id <id> --max-seconds N` | "Owner STOP is on; run clear-stop, then start again." |
| Continue | `demo_agent.py continue --batch-id <id> [--include-failed] [--clear-stop]` (prepares and starts) | `goat_studio batch-continue --job-id <id>` (prepares only) | "Batch X is still running; stop it first: stop --batch-id X." |
| Keep reads fast | `demo_agent.py compact-evidence [--apply]` | `goat_studio compact-evidence [--apply]` | refuses while a batch is active (checked before any archive and again inside the queue transaction); skips a job whose never-started retirement proof compares the whole row |
| Shrink legacy receipts | `demo_agent.py compact-receipts [--apply]` | `goat_studio compact-receipts [--apply]` | refuses while any batch is active (checked before any archive and again inside each row's transaction); skips a row that is not in the canonical layout; see "Receipts" below |

Evidence log and compaction details:

- **Idempotent appends.** Each log line carries a deterministic identity (job, attempt, sequence, evidence hash). The row records the committed byte length. If a crash lands between the fsync and the queue commit, the retry adopts an identical uncommitted tail. A different tail moves to `<log>.uncommitted` first. Lines are never duplicated and the entry count stays exact.
- **Compaction memory.** The size comes from `SELECT length(jobs)`. Archives are serialised one entry at a time, written to a temp file, fsynced, verified by sha256 and atomically renamed. The first parsed copy is dropped before the transaction parses the row again. Inside the transaction, each archived history is re-hashed against the current row. The result and the `native-evidence/compactions.jsonl` journal come from the transaction, with no read after the commit.
- **Scale test.** `LargeQueueRowTests` builds Banker's shape scaled down: 29 jobs, about 42 MB of history and 4 MB of other data. The real row is 818 MB, 770 MB of it history. Compaction must shrink the row to about the non-history size, and a state read must stay bounded.

## Receipts: a queue digest, not the queue

Every `studio_receipts` row used to embed the full `state`, queue included. On Banker (`studio.sqlite` 11.4 GB) the queue row was 818 MB, so each reserve/batch/cancel receipt was 818 MB too: 62 receipts held 9.78 GB. Each start attempt wrote about 1.6 GB of receipts. Every renewed-epoch authority check (the regrant `takeover` scan plus the grant read) parsed every receipt in Python, about 9.8 GB per check, even after `compact-evidence` shrank the queue row.

What reads a receipt (verified in code):

| Reader | Fields |
|---|---|
| Replay (`StudioStore.submit`, same request ID) | compares `payload_hash` only, then returns the stored receipt |
| "Request ID content changed" (`Controller.submit`) | the saved request file, not the receipt |
| Bridge outbox (`studio_bridge.py`) | `state.terminal_id/run_id/revision/generation/owner` plus `request_id`, `command`, `status`, `execution_effect`; the MQL side reads `state.revision`, also on replay |
| Regrant `takeover`/`active`, owner-research, owner-maintenance, legacy grant classification | `request_id`, `command`, `status`, `execution_effect` and the same five state fields |
| CLI results (`clear-queue --apply`, `submit`) | printed as output only |

Nothing reads `receipt.state.queue`. So:

- **New receipts** store `state.queue_digest = {"sha256", "job_count"}` in place of `state.queue`; every other state field is unchanged. `sha256` is over the queue's canonical JSON (`campaign_ledger.packed`), so it equals `campaign_ledger.sha(queue)`. It is computed once per command: a queue command hashes the same packed string it writes to `studio_queues`, any other command packs the observed queue once. The fresh result and every replay are the same stored bytes. Anything that needs the queue reads current state.
- **Scans** call `studio_receipt_digest.receipt_views`. SQLite checks `json_valid` and drops `state.queue` with `json_remove` before Python parses anything, so a legacy row costs one C-level JSON pass and no Python objects for its queue. Every other field comes back exactly as stored, duplicates included, so `unique_object` still refuses duplicate fields where it did before. Invalid JSON raises `ValueError`, as `json.loads` did. Measured on this PC: about 85 ms for a 45 MB receipt against 460 ms for `json.loads`, with no Python memory for the queue. Tests cover new-format and legacy-format receipts for the regrant, owner-research and legacy-grant decisions.
- **`compact-receipts`** migrates legacy rows. Preview by default; `--apply` acts. It processes one receipt at a time:
  1. SQLite returns the receipt without its queue (small), and the canonical bytes before and after the queue are rebuilt from it.
  2. The stored bytes are streamed from the row (`blobopen`, 1 MiB chunks; never the whole receipt in Python) into `native-evidence/receipt-archive/<request_id>.<binding12>.receipt.json`: temp file, fsync, sha256 readback, `os.replace`. The same pass checks that the bytes around the queue equal the canonical frame and hashes the bytes in between, which is `sha256(packed(queue))`. A row that is not in the canonical layout is skipped and left as is. An identical archive from an interrupted run is reused; a different one refuses and is kept.
  3. One `BEGIN IMMEDIATE` transaction under the mutation gate re-checks that no batch is active (SQLite `json_each` over every queue), re-checks the session authority, re-streams the row and requires its sha256 to equal the archive's (re-read from disk), takes the job count from the locked row, and rewrites only that row. The journal line (`native-evidence/receipt-compactions.jsonl`) comes from that transaction's result.

  It refuses while any batch is starting or running, never deletes an archive (the only copy of the original queue snapshot), and never runs `VACUUM`. Rerunning it finds no candidates. A migrated receipt has exactly the new-receipt shape, so its replay returns the digest form; the original bytes are in its archive.
- **Scale test.** `LargeReceiptTests` puts 10 legacy receipts of about 5 MB each into a renewed epoch. The authority check must return the same scope, Python must never receive more than 100 kB of JSON at once, and after `compact-receipts` the receipts total under 50 kB and the check stays under 1 s and faster than before. On this PC: 50 MB of receipts became 4.2 kB; the check went from 74 ms (legacy, SQLite-cut) to 6 ms. `json.loads` of one of those receipts alone took 46 ms.

## Follow-ups

- Desktop buttons (goatai, `claude-pc/fast-lane-buttons`): Stop / Start / Continue on the lane card, calling these commands.
- Banker: after #123, run `compact-evidence --apply` once while idle, then `compact-receipts --apply`. The first shrinks the parsed queue row; the second shrinks the 62 receipts to their digest form, so starts stop writing ~1.6 GB and authority checks stop scanning ~9.8 GB. The SQLite file stays the same size until a separate reviewed `VACUUM`. Both change the store content hash, so prepare a handover or owner-maintenance record afterwards.
- The open-terminal `start` route (non-demo, `Controller.start`) keeps its single baseline; #120 replaces that route with config start.
- Replay of an *unmigrated* legacy receipt still loads that receipt whole (it returns the stored bytes). `compact-receipts` removes that cost.
- **Typed research continuation + Continue.** `batch-continue` refuses in a `research_continuation` session with one sentence, because that authority covers only the exact frozen plan (`members_sha256`). Authorizing a generated remaining-members plan needs its own reviewed provenance.
- **Seal binding.** Bind the seal or manifest digest into the job row at enqueue and require it in `sealed()` (see the seal note above).
