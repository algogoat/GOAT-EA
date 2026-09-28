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
controls, exact issued/request/permit/result bytes, and fresh unchanged process,
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
  version's directory is not proof that another version has no work.
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
