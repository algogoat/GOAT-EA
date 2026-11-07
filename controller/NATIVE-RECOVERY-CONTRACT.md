# V1.49 orphan continuation recovery

Status: controller/native source implemented and compiled; native qualification
and matched monitor delivery remain required. Historical V1.47/V1.48 binaries
are unchanged. This document never grants permission to reset a user's session.

## Public reviewed workflow

`native-recovery-status` is a diagnosis. On a matching V1.49 monitor,
`orphan-recovery-prepare` freezes a ten-minute review. Explain it to the user,
then use `orphan-recovery-apply --review-id <id> --confirm-reviewed` only after
their explicit approval. That command reports publication, not recovery.
`orphan-recovery-status --review-id <id>` requires matching issued/consumed/result
receipts and fresh same-process/monitor/account/state readback before reporting
`recovered`. Future work requires its own explicit start.

Apply fences ordinary commands and session switching. A missing, rejected or
ambiguous native outcome remains `reconcile_required`; no command silently
resends an issued request. Interrupted cleanup after durable success can complete
on the next exact status call. Keep every review and native receipt.

The separate `orphan-recovery-reconcile-rejection --review-id <original-id>
--confirm-reviewed` command can settle one expired `ORPHAN_REVIEW_REJECTED`,
`ORPHAN_RUNTIME_REJECTED` or `ORPHAN_FOREIGN_CONTROL`
receipt with no native consumption. This is controller transport reconciliation,
not another native action or approval to retry. It requires originally absent
controls and exact issued/request/permit/result bytes. The default running mode
requires fresh unchanged process,
monitor, account, grant, state and idle `BatchOnGoing=true` evidence under the
session and native gates. Any consumed artifact in the selected local Studio
tree, different status, missing evidence or changed identity remains fenced.

Recovery publication uses a 45-second expiry inside the EA's unchanged 60-second
ceiling. Before writing transport, the controller requires a valid terminal UTC
observation whose timestamp differs from its file write time by at most five
seconds. This compares both clocks when feedback was written; fifteen-second-old
feedback with matching clocks remains valid under the separate, unchanged
20-second runtime freshness check. Check clock synchronization for a skew refusal
or fresh monitor feedback for a freshness refusal, then retry only an unissued,
still-valid review. Issued or uncertain requests are never resent. This prevents
a zero-margin expiry rejection; it does not prove the cause of any tester report.

ORPHAN_REVIEW_REJECTED is an initial native request-validation refusal, before
the runtime and foreign-control checks. It does not identify which schema,
identity, path or expiry predicate failed. Preserve the original request and
native result to diagnose that difference; do not attribute it to a runtime
script or foreign file without evidence. Settlement only retires the expired
transport after all existing checks, and leaves BatchOnGoing unchanged.

Older installed controllers may refuse this status. Use a released controller
that explicitly supports it; do not edit the allowlist or install loose Python
files in a signed/hash-verified bundle. Authorization is either explicit human
approval of this exact settlement (`--confirm-reviewed`) or the separately
audited, owner-scoped `--owner-research` route, including its typed research
authority checks. The latter does not represent human confirmation; its original
grant, account/session and operation scope must still verify. Neither route
authorizes a new recovery attempt. If process/account/state has changed, the
preserving checks still refuse: retain evidence for supported recovery.

The command fsyncs immutable evidence and a cleanup intent before retiring the
exact permit and request, persists `rejected_settled` before removing its own
fence, and retains the native result so the original request cannot execute
again. Interrupted cleanup resumes only against that exact journal; ordinary
status/apply never resume this cleanup or resend recovery. A settled historical
status cannot touch a later fence or transport. No flag, queue, session, grant,
EA binary or native wire field changes. Files are fsynced; this does not claim
directory-metadata power-loss durability. Native qualification remains pending.

### Explicit stopped-terminal rejection settlement

A released controller that includes this feature can use
`orphan-recovery-reconcile-rejection --review-id <original-id> --confirm-reviewed
--terminal-stopped` after the user approves this exact stopped cleanup. This is
an explicit alternative to the default same-process route, never an automatic
fallback. It does not stop or reopen MT5. Native qualification and matched
packaged delivery remain required; source tests alone do not make it available
in an older installed beta.

The selected terminal must be positively absent from a complete process
inventory at every cleanup boundary. Unmapped or ambiguous processes, changed
protected peers, pending human commands, changed installation/session/account
bindings or local state, and any native consumption refuse cleanup. The original
byte-exact rejected result stays in place as the EA's one-shot replay barrier.
An initially absent `permit.json` is accepted only in this explicit stopped mode
with the same exact issued record, retained request bytes, expired supported
native rejection and no consumption. The existing settlement intent records
the absence without creating permit bytes. Absence alone never proves an
unissued or unconsumed request. Missing issuance/request/result, malformed or
foreign permits, uncertain outcomes and a permit appearing during inspection
remain fenced. No native permission or launch authorization is created.
No old monitor feedback is represented as a current idle/account/flag readback,
and no normal-exit receipt is invented. The existing local ownership, transport,
consumption, archive and permit-before-request checks still apply under the same
locks. No native flag, history, queue, file outside this transport, or grant is
changed.

The journal records this stopped mode and the actual process-absence observation.
Interrupted cleanup must resume with the same mode and review ID. Historical
status cannot retire a later fence. The offline route requires explicit human
confirmation; neither `--owner-research` nor typed research-continuation authority
is accepted offline. After settlement, reopen through a supported path and obtain
a fresh native observation and new recovery review. Never reuse the rejected
request or its old observation, and never treat settlement as recovery or start.

This first implementation deliberately accepts only one known controller binding,
database and native gate. Any retained legacy/foreign owner fails closed. Native
checks reject other chart EAs/scripts, other-version active controls, a nonzero
TerminalRunning flag and deferred restart state. Only BatchOnGoing is cleared.
The Python review excludes other controller processes; the native action validates
its exact snapshot/active/owner hashes under the existing native gate. As with
existing launch operations this coordinates trusted local tools, not hostile
same-user writers or filesystem tampering.

The installed public process binding currently does not support mapping a second
protected terminal. A running peer Terminal 2 is therefore rejected as unmapped;
preserve that terminal and qualify an appropriate supported binding separately.
Installing V1.49 alone does not make that multi-terminal host ready.

## Existing lifecycle is insufficient

`Optimizer.mqh::ResolveBatchRunningState(true)` clears stale globals only through
`OnClickStart`, after run-context preparation and before checking tester idleness.
The same handler can proceed to launch work. Display refresh uses `false`.
`OnClickStop` confirms and cancels the native queue, deletes controls and stops the
tester. Neither is a controller recovery API. V1.48 native `cancel` requires an
owned active job and exact Common Files owner/pointer hashes. `finish` needs an
observed finished attempt with idle runtime and `batch_ongoing:false`. An orphan
has none of those identities; constructing them would fabricate ownership.

### Cancel stop confirmation (FU35)

A consumed V1.49 `cancel` answers `CANCELLED_RECONCILE` only when its queue rows
were saved, its launch files removed and the tester was confirmed idle. Before
FU35 the idle check was one 100 ms read after the Stop click (`ClickStop(1)`),
which raced MT5's tester shutdown and answered `CANCEL_SIGNAL_SENT_RECONCILE` for
batches that did stop. FU35 (`GOATTesterStopConfirm.mqh`) reads the passive tester
caption up to 40 times, 250 ms apart (10 s bound, inside the 20 s monitor
freshness window), and confirms idle only after three consecutive "Start"
captions; a blank or unknown caption never counts. Stop is sent only right after
a "running" read, once per run observed (at most three in total), because Start
and Stop share one MT5 toggle. The Experts journal records
`GOAT_CANCEL_STOP_CONFIRM ... idle_confirmed= polls= stop_clicks= elapsed_ms=`.
The receipt format and controller semantics are unchanged: `CANCEL_SIGNAL_SENT_RECONCILE`
still means stop was not proven, and finish still requires native idle evidence.
The EA holds the native gate for that bound; controller transactions that meet
the busy gate retry on their next tick, as they already do during a Start.

### Stranded batch after a human takeover (cancel re-grant)

The state: a reboot interrupted a batch, its cancel was rejected, one cancellation
successor was issued, then the human took control. Tester idle, native queue still
holding OnGoing and Pending rows, `owner=human`. Only `finish` settles the job, and
monitor setup, orphan recovery and handover all need it settled. `finish` needs a
consumed stop, a settled native queue and `owner=agent`. Only an EA-consumed cancel
rewrites `queue.GOAT` and clears `BatchOnGoing`. The takeover revoked the unconsumed
successor's permit and the epoch it was issued under, and `publish_cancel` returns an
already-issued stop rather than resending it. A new grant alone does not change that.

**Human step:** after TAKE CONTROL, GIVE TO AGENT in the Studio panel, with `serve`
running so the grant is processed. Ask the user first: this stops the batch.

**Agent steps:** `goat.exe demo cancel-regrant --batch-id <id>` on the owner demo
lane, or `goat.exe studio cancel-regrant --job-id <id>` on the customer lane, publishes
one stop. Then run the same command with `--settle` until it answers `paused` or
`finished`; it publishes nothing, and finishes the batch and completes its pause once
MT5 consumed the stop. On V1.49, `batch-resume` then continues the unfinished members.
After a V1.48 stop it cannot (below), and `--settle` says so instead. Finished members keep their
results and every earlier stop keeps its receipts. Nothing is deleted, and neither step
starts work. Both are allowed under owner STOP, which cannot clear while the batch is
unresolved.

**Both lanes, both EA versions.** Publication on both entries runs every admission
clause below and both demo proofs: the EA sample and the broker read through the
MetaTrader5 adapter. `--settle` reads no broker on either entry. `finish` proves the
EA's demo flag, Algo off and the idle tester under the native gate. Both entries check
the demo-only lane on publish and on settle. Both refuse while a human request waits
(`REGRANT_HUMAN_PENDING`), with one shared check (`human_waiting`): a request in the
bridge's inbox or processing folder, or the panel's `pending_id`. The customer entry also refuses an Open Lab experiment login
(`REGRANT_PROTECTED_ACCOUNT`), like this lane's close-terminal, monitor-launch and
monitor-repair; the owner verb has no such check. The installed EA is the receipt's,
because loading the receipt hashes it for every studio command. The customer entry runs
under the terminal lease, which a live `run-batch` holds for its whole run, so that
driver refuses `TERMINAL_LEASE_BUSY` before any check here. `REGRANT_BATCH_BUSY` is any
other holder of the driver gate. V1.48 (`f771b36`) and V1.49 consume a valid stop the
same way and answer with the same receipts. Only the batch base folder differs:
`GOAT V1.48-<server>`, or V1.49's per-terminal and per-login folder. `controller_base`
resolves it by version, so the stop's owner and pointer hashes are the ones that EA reads.

**V1.48 after the stop.** V1.48's stop sets MT5's persistent batch-cancelled flag,
`GOAT_BatchCancelled` (`f771b36` GOATStudioDispatch.mqh:70). Its report-capable start,
for any batch, writes its consumed claim, then refuses `RESTART_RUNTIME_CHANGED` while
that flag is set (:178-188). Only two things clear it:
- an in-place start (:216), which GOAT never sends on a report-capable lane;
- the panel's Batch Start (Optimizer.mqh `OnClickStart`, :3089).

In managed mode that button reads TAKE CONTROL (GOATStudioUI.mqh:279, Optimizer.mqh:217-227),
and `OnClickStart` needs a Pending row, which the stop turned Cancelled
(GOATStudioDispatch.mqh:83-84). V1.49 keeps value 1 as a person's or legacy stop
(GOATBatchCancelOrigin.mqh, `HUMAN_CANCEL_RETAINED`). No remedy is proven from source, so
none is offered. When the EA that consumed the stop was V1.48 (`ea_version` in the
finish result), the reply says what is known:
- the finished members are kept;
- GOAT cannot run this batch's remaining members, or start another batch on that MT5;
- the next step is the V1.49 upgrade in GOAT > Terminals, then a support report naming
  the batch, with `RESUME_V148_CANCEL_LATCHED` in `errorCodes`.

`--settle` says this in `next_action` and `escalate_to`. `batch-resume` and `continue`
(both lanes) refuse `RESUME_V148_CANCEL_LATCHED` with the same sentence before they write
anything, rather than spend a start MT5 would claim and refuse.

**Known limit:** on a V1.48 EA a controller stop leaves `GOAT_BatchCancelled` set; GOAT
cannot resume that batch's remaining members. This predates the re-grant and holds for
every V1.48 pause→resume. Only re-grant-stopped batches are refused up front.

**Identity.** One stop per new grant recorded in the human channel:
`sha([attempt, 'cancel-successor-regrant', prior_issued_sha256, generation])`, linked
first in `cancel-successors/<attempt>.regrant-<generation>.json`. `cancel_id` resolves
to the newest link and verifies the chain, so `finish`, the settled-gate checks and
reconcile bind that stop. An unpublished link can only publish through `cancel-regrant`,
at its own generation and after every check again: ordinary cancel refuses it with
`REGRANT_LINK_NEEDS_ADMISSION`, and a later grant starts from the newest stop issued.

**Admission.** All of these, under the driver gate and the native gate. Anything else
refuses with its reason code and sends nothing:

| Clause | Refusal |
| --- | --- |
| Demo-only session on the owner demo lane or the customer lane | `REGRANT_NOT_DEMO_LANE` |
| An unresolved native attempt in the exact frozen configuration | `REGRANT_JOB_NOT_ACTIVE`, `REGRANT_CONFIG_CHANGED` |
| `owner=agent` | `REGRANT_OWNER_NOT_AGENT` |
| One issued cancellation successor exists, with verified evidence | `REGRANT_NO_PRIOR_SUCCESSOR`, `REGRANT_STOP_IDENTITY_CHANGED` |
| This generation has not issued its stop | `REGRANT_ALREADY_ISSUED`, `REGRANT_STOP_UNDELIVERED` |
| Generation above the prior stop's | `REGRANT_SAME_GENERATION` |
| Prior stop unconsumed | `REGRANT_PRIOR_STOP_CONSUMED` (run `--settle`), `REGRANT_ESCALATE_CLAIM_WITHOUT_OUTCOME` |
| Prior stop expired | `REGRANT_PRIOR_STOP_LIVE` |
| Prior stop unanswered, `CANCEL_REJECTED` or `CANCEL_CONTROL_REVOKED` | `REGRANT_PRIOR_RECEIPT_NOT_RECOVERABLE` |
| Exactly one grant in the human channel created this generation: receipt, archive and actor-bound hash agree | `REGRANT_NO_ARCHIVED_GRANT` |
| The attempt still matches its driver journal, apart from the generation | `REGRANT_ATTEMPT_CHANGED`, `REGRANT_NO_DRIVER_JOURNAL` |
| `finish` would accept the batch after this stop | `REGRANT_REPORTS_NOT_VERIFIED` (retry), `REGRANT_ESCALATE_REPORTS_LOST`, `REGRANT_FINISH_WOULD_REFUSE` |
| 256 MB free on every volume, all readable | `REGRANT_DISK_TOO_LOW`, `REGRANT_DISK_UNREADABLE` |
| Native owner file names this attempt, same hash as the prior stop; a file cut mid-write refuses too | `REGRANT_NATIVE_OWNER_CHANGED` |
| Run pointer addresses this run, same hash as the prior stop | `REGRANT_POINTER_CHANGED` |
| Fresh bound EA sample, tester idle, no pending restart, Algo off | `REGRANT_TESTER_NOT_IDLE`, `REGRANT_RUNTIME_NOT_VERIFIED` |
| The EA reported this grant's owner and generation | `REGRANT_GRANT_NOT_OBSERVED` |
| Broker and EA both report the connected, flat, paired demo with Algo off; a running tester caption refuses | `REGRANT_BROKER_NOT_IDLE_DEMO`, `REGRANT_TESTER_NOT_IDLE` |
| No other GOAT process holds the batch (a customer `run-batch` holds the terminal lease: `TERMINAL_LEASE_BUSY`); no human request waits, also as the panel's `pending_id` | `REGRANT_BATCH_BUSY`, `REGRANT_LIVE_DRIVER`, `REGRANT_HUMAN_PENDING` |
| Customer entry, publish and settle: not an Open Lab experiment login (the EA hash is checked when the receipt loads) | `REGRANT_PROTECTED_ACCOUNT` |
| The pause can re-arm | `REGRANT_PAUSE_NOT_REARMABLE` |

An unanswered prior stop is accepted because every controller commit revokes its
permit, so it may never get a receipt. It is only ever accepted expired and
unconsumed under the gate the EA takes before consuming anything, and the EA refuses
an expired request regardless.

**Pre-check, because a consumed stop cannot be replaced.** The stop rewrites only
Pending, Queued and OnGoing rows, so publication first runs `finish`'s own report gate
on the queue as it will be, with the tester already proven idle. It also reads native
evidence and the source record, and runs the checks `finish`'s restore and report-alias
retirement run on the transaction and the alias, without changing them. Any refusal
leaves everything as it was. Report files are not recreated by anything here, so a
missing or unreadable pair is `REGRANT_ESCALATE_REPORTS_LOST`; a report whose bytes are
still changing is `REGRANT_REPORTS_NOT_VERIFIED`, a retry.

**Disk.** `ReconstructFile` opens `queue.GOAT` for writing, which truncates it, before
it writes, so a full disk could lose the queue. Publication needs 256 MB free on every
volume (`REGRANT_DISK_TOO_LOW`) and gives the reading in `next_action`; a volume
that cannot be read is `REGRANT_DISK_UNREADABLE`, never "free disk space". That floor is
deliberately far below a batch's own disk guard, so a batch stopping for low disk can
still stop. It narrows the risk; only the EA could close it.

**Where this ends in an escalation.** Each of these says what is known, sends nothing,
and needs a person. No check is weakened to get past them. Each names its destination
in the sentence and in `escalate_to`: a GOAT support report (`support.prepareReport`,
category `studio`, the code in `errorCodes`, the whole reply unedited as `actual`),
sent with `support.submitReport` only after the user approved the preview.

| Code | State | Why nothing automatic is safe |
| --- | --- | --- |
| `REGRANT_ESCALATE_REPORTS_LOST` | Before any stop: a completed member has no verified pair | `finish` would refuse for good. Restoring the exact pair lets `cancel-regrant` run again. |
| `REGRANT_ESCALATE_CLAIM_WITHOUT_OUTCOME` | `consumed-` exists with no receipt, or with a receipt that does not report a stop | A reboot between the EA's claim and its receipt. Its retry answers `CANCEL_REJECTED` or `CANCEL_ALREADY_CONSUMED`, or nothing if the permit is gone. Flags and queue may be unchanged, partly changed or fully changed. `finish` rightly refuses, and another stop could double-apply. The refusal gives the claim, the receipt, the queue counts and `BatchOnGoing`. |
| `REGRANT_ESCALATE_FINISH_REFUSED` | After a consumed stop, `finish` kept refusing for 15 minutes while the monitor ticked with a fresh EA sample. With MT5 closed or its monitor silent, the answer is `REGRANT_MONITOR_NOT_REPORTING` (open MT5 and settle again) instead | A report lost after publication, or `CANCEL_SIGNAL_SENT_RECONCILE` with the queue unsaved or truncated. The stop cannot be replaced. `--settle` still retries, so fixing the cause finishes. |

The claim check holds the native gate, which the EA holds from its claim to its receipt,
so a stop still being processed is never mistaken for a dead one.

**A stop that never reached MT5.** A crash after `issued-` is written but before the
permit, or a later commit revoking the permit, leaves a stop MT5 will never answer.
`cancel-regrant` and `--settle` both refuse with `REGRANT_STOP_UNDELIVERED` instead of
waiting. It is not resent. Next step: once it expires, TAKE CONTROL and GIVE TO AGENT,
then `cancel-regrant` publishes one stop for that grant.

**`--settle` and the revoked driver.** It does what that driver does after its finish:
binds the attempt to the driver journal in everything except the generation
(`REGRANT_ATTEMPT_CHANGED`, `REGRANT_NO_DRIVER_JOURNAL`), reconciles, finishes, completes
the pause, closes the journal, runs its one end state and runs the idle-point maintenance.
The disk guard is recorded and blocks nothing: a driver's disk guard stops a batch, so
it never holds a stop back. The end state keeps its rule of closing only the MT5 this
batch launched. After a reboot that usually answers `skipped`: MT5 stays open on its
current profile until GOAT next stops it. The result's `end_state` says which happened.

**What "human grant" proves.** `actor` comes from the bridge folder a request arrived
in, and nothing signs it. An archived grant shows the request came through `human/`
with a matching receipt. It tells the human channel from the agent channel between
cooperating local tools. It does not prove a person clicked, and a same-user process
writing into that folder is out of scope, as for every other control in this document.

**Pause.** The verb re-arms the pause before publication: `pause_failed` or `pausing`
returns to `pausing` at the new generation, any failure moves to `rearmed_failures`,
and a batch with no pause gets one so its members stay resumable. One stop identity
re-arms a failed pause only once. The old driver's epoch is revoked and stays refused.

**Nothing relaxed.** The EA is unchanged and keeps every check, including its demo-only
check and `CANCEL_CONTROL_REVOKED`. `finish` still requires a consumed receipt, a
settled native queue and, under the gate, an idle tester with no batch ongoing. No real
account can enter: both entries are demo-only and prove demo from the EA and the broker.
A refused re-grant stop is never replaced without another human TAKE CONTROL and GIVE
TO AGENT. A batch whose first cancel never got a successor still refuses
(`REGRANT_NO_PRIOR_SUCCESSOR`).

Status: source and simulated-EA tests only, on both lanes and with both the V1.48
(`f771b36`) and the V1.49 cancel handler simulated. No Windows or MT5 replay has been done.

## Native protocol requirements

The versioned native action is `recover_orphan_continuation`, advertised
by the running monitor's runtime capability and the controller discovery contract.
Use the existing native gate with a separate durable review/commit/consumption
receipt, never a fake start/cancel. An explicit user-approved review freezes all
observations. Native consumption must repeat every check under its gate:

- Exact installed EA hash/source/receipt, compatible protocol capability, selected
  executable/process creation identity, terminal data path, bound demo account and
  server, fresh runtime, Algo Trading off and tester demonstrably idle.
- Exact controller binding, agent owner, revision and generation. Review all
  bindings and retained gate owners, including legacy gate databases, so no
  starting/running/reserved/verifying/reconcile-required or unknown work exists.
  Pending jobs remain untouched. Missing/ambiguous ownership fails closed.
- No active seed slot, outstanding start/cancel permit or request, deferred restart,
  native run pointer, native config, launch guard or owner file. Inspect relevant
  EA versions in Common Files as well as terminal-local state; absence in one
  version's directory is not proof that another version has no work. With V1.49
  terminal isolation (INV-BATCH-01), another terminal/account's own folder
  (`GOAT V<ver>-<server>-<login>-<hash>`) is independent and never blocks; this
  terminal's folder and every shared pre-isolation folder still do.
- Freeze native control/global observations, then recheck immediately before the
  effect. Refuse changed state, non-idle tester, process restart or ownership drift.

The sole effect is clearing the positively identified orphan continuation flag
inside MT5, followed by GlobalVariablesFlush and fresh readback. If ancillary
flags are included, name each in the versioned contract and refuse any unexplained
active restart state. Never alter queues, account/session grants, trading settings,
result files, pointer/config files or start/stop a process/tester. Preserve all
before/after observations and a native consumed receipt. Repeated delivery returns
the original receipt; uncertain effects require receipt/readback reconciliation.
The public controller must report `recovered` only after exact native receipt and
runtime evidence agree, and require a separate explicit start for future work.

Native cannot directly attest a SQLite snapshot. The design must bind the full
controller review digest into its frozen snapshot and exclude all participating
writers with native/session gates; legacy writers or unreviewed databases block
recovery. Runtime program path alone is not loaded-binary attestation: deployment
must verify the running monitor's capability/version and immutable installed hash,
plus the normal exact process/account binding checks.

## Delivery and qualification dependencies

V1.49 has its own entrypoint, forward-only capability guard, schema/dependency
contracts and compiled EX5. Preserve previous version files and binaries. Review
the native dispatch/observation/controller changes together. Build a matched
desktop suite with exact EA and controller source/hash pins and release activation.
The selected legacy monitor must be upgraded through the supported installer and
monitor prepare/launch workflow, with required human permissions/Give to Agent;
a Python-only change cannot add an action to a running V1.47 monitor.

Qualify native Windows cases: genuine orphan idle recovery; active/pending native
attempt refusal; other-version controls; seed owner; changed process/account or
generation; missing feedback; Algo-on/non-demo refusal; delivery replay and crash
after native effect before receipt/readback; preserved pending/history/results;
then a separately authorized fresh batch start/cancel/completion. Mocked tests and
compile success do not substitute for these native checks. This capability cannot
be advertised as shipped until the compatible monitor and controller are installed
and the complete release evidence is accepted.
