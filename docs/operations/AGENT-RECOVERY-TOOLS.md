# Simple, powerful agent tools

Product direction agreed with Vince on 2026-09-28. This is the implementation
contract for AGENT-SELF-REPAIR-001, not a claim that the proposed tools below
already ship. Banker research is the first end-to-end acceptance case.

## User outcome

The customer gives their agent an objective. The agent operates GOAT, the
portfolio builder and the selected MT5 terminal, including setup and ordinary
recovery. The customer should not need to navigate MT5 settings, reopen a stuck
application, understand controller revisions or translate an error into a long
sequence of commands. An agent should not need our private instructions or a
support engineer to perform a known repair.

The controller owns the detailed steps: inspect, reconcile, apply, restart when
needed, verify and continue. A guard that detects a known recoverable condition
must lead to its supported recovery, rather than merely ending the operation.

## Proposed agent surface

Names are provisional and must be advertised as unavailable until implemented.

| Tool intent | Agent supplies | Controller delivers |
|---|---|---|
| Inspect | Selected installation | Fresh app, controller, terminal, account, tester, permissions and active-operation state; precise uncertainty |
| Ensure ready | Goal and existing authorized scope | One resumable operation that performs applicable setup/recovery and verifies readiness for that goal |
| Configure MT5 | Exact required WebRequest origins and DLL settings, with the user's authorization | Smallest settings change, preserved unrelated entries, necessary orderly restart and effective runtime readback |
| Run research | Frozen plan and time/storage budget | Prepare, launch, observe actual execution, collect results and stop within the budget |
| Recover operation | Retained operation ID | Reconcile its actual outcome, finish interrupted phases, and resume only the same authorized work |
| Explain/report | Operation ID | Plain-language before/after summary and a locally generated redacted diagnostic bundle |

Expose these through the supported local API/CLI with machine-readable schemas.
Keep lower-level tools available for diagnosis, but do not require an agent to
discover and sequence dozens of them for ordinary operation.

## Recovery behavior

Each operation has one durable ID and a bounded state machine. Repeating a call
with that ID resumes or returns the existing result; it must not duplicate a
start, reinstall, repair or trade. Concurrent calls serialize on the selected
resource. Slow work reports a phase and progress while remaining cancellable.

Return `completed`, `in_progress`, `needs_user_action` or `unsupported_fault`,
with an exact cause, current phase, evidence reference and next supported action.
Distinguish readiness from execution: a queued job or an open MT5 window is not
proof that a batch started. Confirm a consumed start and actual tester activity.

Initial reusable recoveries cover stale snapshots and derived-setting
mismatches, interrupted idle restarts, stale controller transports, proven
never-started attempts, app processes left running without a usable window,
sidecar reconnects and interrupted transfers. Preserve user settings, sign-in,
vault contents, active work and unrelated terminals. An unknown outcome is
reconciled from evidence before another effect is issued.

Use goal-specific checks: observations can run while research is active; an
idle restart cannot. Do not apply every possible gate to every read or repair.
Recheck identities and relevant state at the point of mutation.

## MT5 settings are part of setup

Provide controller-managed WebRequest allowlist and DLL configuration. Inspect
terminal-wide and EA-specific settings separately. Explain the required origins
and DLL capability once, obtain authorization when absent, and retain its scope.
Do not ask again for an unchanged setting within that authorization.

Preserve existing URLs and unrelated permission bits; never infer undocumented
bit meanings or overwrite the entire settings file. Detect concurrent edits and
live terminal ownership. Use a supported, verified configuration method and
restart only the selected terminal when required. Confirm effective native
settings after restart, rather than reporting success from saved bytes alone.

This product request authorizes implementing the capability; it does not itself
change permissions on any customer's installation. Algo Trading, real account
access, pairing and an intentional human takeover remain separate explicit
decisions. Routine recovery must not be implemented as fabricated consent.

## Agents fix locally and explain the result

A repair receipt states the symptom, observed cause, tool/recipe and build
versions, changes made, verification performed, unresolved uncertainty and
whether the original work actually resumed. Keep detailed evidence locally.

Prepare a shareable bundle with tokens, credentials, account identifiers, paths,
user strategies and private URLs removed by default. Preview the exact outgoing
bundle. Upload only under the customer's enabled diagnostic-sharing preference
or explicit request. Diagnose and repair locally even when sharing is disabled.
Deduplicate submitted incidents by fault signature and repair revision; do not
send customer emails as part of this flow.

Unknown bugs produce an actionable local report and a proposed fix. Agent-authored
code changes can be exercised in a disposable reproduction with regression
tests; they are not automatically trusted patches to a customer's trading EA.
Reviewed, tested repairs become versioned recovery capabilities distributed to
all installations. Publish capability and fault schemas so third-party agents
can operate the tools without our internal context. This does not decide the
repository's license or make private source public.

## Acceptance and measurements

- A fresh agent using only shipped discovery/docs can recover each supported
  fault and explain the verified result without developer assistance.
- Already-authorized routine recovery requires zero repeated approval prompts
  and zero manual window-opening steps.
- WebRequest/DLL setup reaches verified native readiness after the one required
  authorization; Algo Trading remains unchanged.
- Crash injection at every phase, repeated calls, concurrent agents and changed
  native state preserve data and never duplicate execution.
- Run the same scenarios on clean and existing Windows installations, with
  multiple MT5 terminals and an RDP session. Source tests alone do not qualify
  native behavior or establish support for every broker/build.
- Measure time to first useful diagnosis, time to verified repair, tool-call
  count, human interventions, automatic recovery rate and recurrence. Set
  performance targets from measured baselines, not guessed timings.

Implementation order: complete Banker's native grant/recovery/start path;
consolidate its verified mechanisms behind goal-level tools; add MT5 permission
setup and app/sidecar recovery; qualify the customer environment matrix and
diagnostic-sharing loop. Avoid another bespoke support procedure for each fault.
