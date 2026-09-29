# GOAT EA and controller work

This branch starts from the retained R5 build. Entries below cover the agreed
V1.48/dashboard work; they do not replace other branches' historical backlog.

| ID | Work | State | Acceptance |
|---|---|---|---|
| EXPORT-148-01 | Capture native sequence evidence within selected batch export backtests and import it for exposure-filter construction | Implemented; native and service qualification passed | Exact final SET/CSV binding, original/adjusted sizing, complete native lifecycle/costs, atomic package retention, generic pool import/search, no extra capture run for matching future exports; [evidence](docs/operations/V1.48-SEQUENCE-EXPORT.md) |
| UI-148-01 | Restore **Dashboard** chart navigation | Implemented; native QA pending | Exact dashboard is brought forward after ordinary restart; missing/ambiguous target handled |
| UI-148-02 | Clear AI/exposure summaries and grouped controls | Implemented; native QA pending | Readable at supported window sizes; all controls reachable; unknown/mixed policy never presented as confirmed |
| UI-148-03 | Remove noisy overview stale column and fair child polling | Source tests passed | Diagnostics retains useful age; one silent child cannot starve the remaining fleet |
| AUTH-148-01 | Isolate new pair credential and pending paths | Compile/source tests passed | Separate legitimate admission and real activation work; existing six credentials remain valid |
| AUTH-148-02 | Confirm activation reload actually leaves activation-only mode | Forward V1.49 MONITOR-ONBOARDING-4 source implemented; bounded two-period reload, retained-global reset and monotonic completion status; native qualification pending | After approved activation and token installation, prove one successful OnInit and ordinary inert dashboard readiness; preserve idempotency and show an honest recovery state if reload does not occur |
| AUTH-148-03 | Renew finite demo authorization without reinitializing strategy charts | Design only; required before a multiweek experiment outlasts admission | Reviewed overlapping admission records, explicit approval, atomic pair-only credential replacement, unchanged chart/process identities and observed native consumption; never extend old credentials implicitly |
| OPS-148-01 | Reduce deployment work for reviewed EA admission changes | Measured workflow limitation; not implemented | A protected admission-only or exactly affected API release proves source identity, preserves other codebases and retains publication/canary/rollback checks; never bypass the current coupled lane |
| CTRL-001 | Controller-driven fresh local terminal/bootstrap | In progress; not qualified | Exact manifest, bounded startup, account/symbol/native readiness, retained failure receipts; no setup clicks |
| CTRL-001A | Manifest-driven secure demo connection | Contract tests, native login and encrypted-provider reconnection passed | Explicit role, exact process/account readback, stdin-only secrets, retained attempts, no automatic retry |
| CTRL-002 | Registered frozen portfolio import | Planned | Immutable source hashes, human names separate from strategy identity, no duplicate children on resume |
| CTRL-003 | Version-aware inventory and identity-based audit | Version-aware paths implemented/tested; sorted-row identity work pending | Inspect selected V1.48 path; handle display sorting without weakening member/input validation |
| CTRL-004 | Customer and agent Optimization Studio controller coverage | [Control/workflow audit documented](docs/operations/OPTIMIZATION-STUDIO-CONTROLLER.md); V1.48 version-aware launch and packaged controller qualification pending | Every supported control/workflow discoverable with exact schema, defaults, persistence and effect; explicit human/agent authority scopes, idempotent requests, durable receipts and recovery; version-correct source/path/binary binding, optional sequence setting round-trip, fresh-install native start/cancel/restart/completion E2E; unsupported operations reported honestly, no implicit launch |
| DOC-001 | Agent entry point and skill/tool routing | Written and validated | New agent can find supported commands and distinguish prototype/preview/deployment states |
| DIST-001 | One-download EA, controller, builder, optimization suites and strategy/asset matrix | Packaged 0.5.0-beta.2 candidate verified; protected publication and real MT5 qualification pending | Selected-terminal discovery/install/repair; bundled runtimes and portable guide; exact suite/matrix identity; clean Windows first-use research-to-portfolio workflow; preserve user state. Owner explicitly permits unsigned private beta; public stable signing remains required. [Companion PR](https://github.com/algogoat/goatai/pull/1827) |
| MATRIX-001 | Living strategy/asset matrix and independent GOAT strategy-library updates | Implemented in companion desktop; signed catalog/import/replay checks passed; native results workflow pending | Append verified local outcomes including failures; exact settings/run/evidence identities; separate publisher and user provenance; compatible atomic catalog updates preserve variants and frozen jobs; no implicit result upload or new optimization. [Companion PR](https://github.com/algogoat/goatai/pull/1827) |
| CTRL-005 | Agent-led customer onboarding and combined readiness | Implemented and fixture-tested; authenticated/native acceptance pending | Read-only onboarding status, retained inert monitor profile/launch attempts, exact account and release binding, fresh evidence expiry; actual pairing approval and Give to Agent remain human actions. `controller/test_studio_onboarding.py` has 15 passing tests within the 107-test controller suite; companion desktop/backend integration tests do not constitute live MT5 proof. |

| CTRL-006 | Read-only machine resource profile and completed optimization pilot evidence | Implemented; 13 focused fixture tests pass; actual Windows CIM observation passed with empty PATH; native elapsed qualification pending | `resource-profile` reports current CPU/RAM/filesystem observations without worker/speed inference. `benchmark-report --batch-id` verifies production-finished batch/result/report identities and exact monotonic alias timeline pairs, with explicit unknown timing and bounded exact artifact bytes. `controller/test_studio_benchmark.py` proves no state/inbox/grant/process effects and rejects drift/ambiguous/noncompleted evidence. No predictive engine, auto-launch, EA source or binary change. |

Evidence and current limitations: [V1.48 verification](docs/operations/V1.48-DASHBOARD-VERIFICATION.md).
Operating entry point: [agent guide](docs/operations/AGENT-START-HERE.md).

AUTH-148-02 evidence: during the September 24 pair qualification, the portal and
native activation status reported approval (HTTP 200), but both inert dashboards
remained activation-only for more than a minute. `GOATDeviceActivationRequestReload`
in `GOATEADeviceActivation.mqh` calls `ChartSetSymbolPeriod` with the current symbol
and period; acceptance of that request is not evidence that OnInit ran. Root is
qualifying an actual cold restart after retained native shutdowns. The bounded
[dashboard recapture procedure](docs/operations/PAIRED-DEMO-SETUP.md) is a
pre-attachment recovery aid, not a fix to the automatic reload path. A future
change must verify the native transition and bound retries without restarting or
altering any unrelated terminal or already attached strategy.

| CTRL-004 | Safe terminal session switching and restoration (goatai#1880) | Controller/desktop source implemented; Windows filesystem/SQLite fixture tests passed; native MT5 qualification pending | Review both active and gate owners, preserve pending research, revoke grants, retain exact recovery IDs, block live/unresolved work, restore without launching |
| CTRL-007 | Reviewed orphan continuation recovery | V1.49 source and controller implemented; isolated new/previous-version compile passes; native Windows qualification and matched delivery pending | Single-owner idle demo evidence, exact monitor/process/revision, cross-version control absence, consumed/result/readback, sole native orphan-flag clear; refuse legacy gates and unmapped peers; no launch/stop/grant changes |
| CTRL-008 | Pending queue cleanup and bounded batch execution | Source and host tests implemented; native deadline cancellation/readback qualification pending | Preserve history and completed results, retained fixed deadline, exact original generation/attempt, no uncertain reissue or force-kill; cancellation request is not confirmed stop |
| CTRL-009 | Protected peers and interrupted passive startup migration | Source tests passed; actual retirement and user-confirmed session parking completed September 26; fresh batch unstarted | Exact peer identity survives session switching; verify legacy completion without discarding history; retain dirty editor; retire original claim/slot atomically only after selected process absence; no flag edits, process adoption, new grant or uncertain close retry. [Migration guide](controller/LEGACY-MONITOR-MIGRATION.md) |
| CTRL-010 | Recover monitor profile after MT5 self-update | Source and fixture tests implemented; exact idle-demo repair successfully reattached installed V1.48; full readiness blocked by empty draft/native orphan flag | MT5 build6230 updater dropped the monitor-launch /profile argument and reopened the selected terminal with only /skipupdate. Preserve the intended inert profile across the supported update lifecycle, prove exact process/data identity and native profile readback, retain uncertain outcomes and protect other terminals. Never retry native optimization, inherit a control grant or enable permissions as recovery. Test update success, failure, discarded arguments and unrelated process replacement before qualification. |

| CTRL-011 | Empty-session handoff and compact connection view | Native -4 layout defect reproduced; -5 source fix, 34 production-layout fixture cases and clean compile pass; native visual qualification pending | Null tester/export drafts with empty queue and strategy permit genuine human handoff; no fabricated defaults/grant; partial state and retained edits remain blocked; controls stay visible on narrow charts |
| CTRL-012 | Agent-driven MT5 permissions and setup | Authorized; exact URL guidance available, automated permission preparation/navigation not implemented | Agent opens/prepares the selected inert EA and exact WebRequest/DLL permission step; preserve unrelated URLs/settings, verify native permission readback, keep Algo Trading separate; no screen-coordinate macros or silent account/pairing grant |
| CTRL-013 | Recognize the waiting desktop setup client during receipt upgrade | Source fix and Windows guard tests; packaged native requalification pending | The standard goat.exe desktop caller falsely blocked completed-PARK verification. Allow only one exact bundle-hashed launcher/Python pair executing same-target internal qualification; reject changed files, other methods, ambiguous callers and all native runners. Ordinary session switching remains fenced. |
| CTRL-014 | Recover reviewed PARK and restoration across Windows volumes | Source interruption/preservation tests and isolated real G-to-C-to-G filesystem/SQLite fixture passed; installed canary recovery pending | WinError17 from direct directory rename must resume the original review. Publish only a fully hashed destination copy; retire only matching source files and known empty directories; preserve unexpected/changed data and external journals. No session, grant, process or EA behavior changes; no power-loss durability claim. `controller/test_studio_handover_transfer.py` and `controller/test_studio_handover.py` enforce recovery boundaries. |
| CTRL-015 | Recognize the waiting public desktop migration client during receipt upgrade | Source fix; 41 Windows controller tests pass; packaged public canary pending | Admit only the explicit suite.migrateInstallation caller with the selected registered receipt and exact parameter schema, preserving runtime hashes, one launcher/child pair and completed-PARK-only scope. Reject wrong targets/methods, changed runtime, extra flags and duplicate callers. No pairing, permission, trading, EA binary or wire change. |
| CTRL-016 | Parse MT5-saved input group headings during monitor profile verification | Source regression reproduced before fix; focused fixture qualification, native relaunch pending | Accept only bounded equals-framed empty group rows inside expert inputs; preserve duplicate-key, EA identity, inert-mode, script and permission checks. Reduced sanitized native chart fixture retains observed expertmode4 rejection; no permission approval, chart rewrite, EA binary or wire change. |
| CTRL-017 | Settle an expired, proven pre-consumption orphan recovery rejection | Controller implementation and interruption/race fixtures; native qualification pending | Exact ORPHAN_RUNTIME_REJECTED only, no consumption, originally absent controls, unchanged live identity and idle orphan flag under both locks; immutable evidence and intent before exact transport retirement, durable rejected status before fence cleanup. No recovery retry, native flag, grant, queue, EA binary or wire change. |


| CTRL-018 | Journal-only orphan runtime diagnostics | V1.49-ORPHAN-DIAGNOSTIC-6 source and nine source contracts pass; clean source 94cf75f compiled with zero errors/warnings; candidate tracked, not admitted/installed, native qualification pending | Preserve ordered fail-closed runtime guards and unchanged recovery action/status/wire; log fixed first-failure reasons with unreset chart-query error observations. Current bound read-only monitor observations explicitly say NO_ACTION and never claim the original rejection cause. Deduplicate and cap at 16 messages per EA load; no identifiers, replay, flag/grant/trading changes. Preserve admitted -5 artifact. |
| CTRL-020 | Identify the chart behind persistent `SCRIPT_PRESENT` | V1.49-ORPHAN-DIAGNOSTIC-7 compiled with zero errors/warnings; native qualification pending | Print only the chart ID, own-chart marker, and MT5 script name on the existing rejection path. Keep all recovery predicates and the refusal unchanged; preserve the earlier -5 and -6 binaries in Git history. |
| CTRL-019 | Read-only Windows controller pull-request CI | Workflow and pinned wheel inputs implemented; hosted run required | Run the complete controller fixture suite on Windows x64 Python 3.13 with the existing publisher's SHA-256-pinned MetaTrader5 and NumPy wheels; read-only token, no secrets, deployment, native initialization or test exclusions. CI is source/fixture evidence, not MT5 qualification. |

| CTRL-021 | Recognize absent MT5 script/expert names represented by NULL | Native Banker build6230 probe reproduced false SCRIPT_PRESENT; V1.49-ORPHAN-EMPTY-NAME-8 correction prepared, full corrected-EA native qualification pending | Use nonzero string length after successful chart queries; retain refusal for query errors and every actual program name, all scalar guards, exact reviewed recovery effects and unchanged wire. Preserve prior binaries in Git history. |

| CTRL-RECOVERY-009 | Normalize native directory enumeration in orphan recovery | V1.49-ORPHAN-DIRECTORY-9 source implemented; native inventory fixture27/27 passed; compiled EA and Banker recovery pending | Real FileFindFirst trailing-separator reproduction, valid single-owner tree accepted, foreign/pending controls rejected; exact pre-consumption settlement retains refusal and native state |

- OWNER-RESEARCH-001: finite owner-demo recovery authorization from the existing
  native human grant (request: goatai#1885 comment5860941567). First slice permits
  reviewed orphan recovery/negative-request settlement only, with exact account,
  terminal, build, session and revocation pins plus native idle/no-trades checks.
  No new grant, human command, wire field or trading behavior. Twelve focused source
  tests pass; full controller CI and Claude review required before use. Upgrade
  continuity and native Banker qualification remain separate work.

- **OWNER-MAINT-002 (2026-09-27, in review):** one-use four-hour original-grant maintenance record and exact offline PARK route for Banker's owner demo. Preserves existing stopped-writer, native-control, journal/CAS and archive guards; pending takeover permanently revokes the chain. Exact target build, frozen-plan SHA and planned replacement session retained. No install/bootstrap/dispatch authority in this slice. Acceptance: negative scope/revocation/time/stop cases and interrupted PARK reconciliation; native qualification remains pending review/use.
- **OWNER-MAINT-003 (2026-09-28, in review):** exact authenticated install/CAS continuation and pre-bound restricted session, with immutable authority_kind/provenance, central default-deny operation/store guards, pinned frozen plan/member/configuration identities, original grant evidence, no human-grant fabrication, and permanent takeover revocation. Saved Algo OFF at offline bootstrap and real SDK demo/Algo OFF/zero positions before dispatch. Existing wire and trading unchanged; owner-only native qualification pending.

- **OWNER-MAINT-004 (2026-09-28):** Fresh frozen queue snapshot publishes complete settings from its hash-verified first active/pending configuration when both editor drafts are absent. Existing drafts and persisted state remain unchanged; no native wire schema, EA behavior, grant or retry change. Native snapshot regression from Banker recovered9 run; source and native qualification pending.

- **OWNER-MAINT-005 (2026-09-28):** Bounded owner-demo rejected-monitor restart and one cancellation successor. Exact pre-consumption rejection, untouched frozen queue/output checks, identified controller-console graceful suspension, original budget retention, normal exact-PID monitor close/relaunch and SDK revalidation; no grant/draft edits. Cancel successor requires immutable native unconsumed rejection and binds observer/finish. Source fixtures only until native qualification. Follow-up before tester rollout: fix native empty-draft flag becoming true on a rejected queued snapshot, which can trap refresh when a saved UI draft exists.

- **OWNER-MAINT-006 (2026-09-28):** One exact-plan replacement after fully verified pre-start cancellation. Central prepare/reserve/dispatch guards require unchanged frozen plan and configuration, pre-consumption start rejection, consumed exact cancellation, all members cancelled, canonical finish/restored controls, no output and stopped original driver. Inherits original deadline and minimum disk reserve, retains all jobs/evidence, refuses a second replacement. Source fixtures pending native use; not a generic retry loop.
- **OWNER-MAINT-007 (2026-09-28):** Reconcile an issued monitor close when Windows transiently drops exiting process metadata. Same retained recovery only; verify publisher suspension/journal and terminal absence before its never-issued first relaunch. No repeated close/launch, unchanged protected draft/session/config and SDK checks. Actual Banker close exited normally; relaunch pending corrected controller qualification.
OWNER-MAINT-007 review follow-up: full publisher inventory before close/relaunch, active-seed guard restored on close reconciliation, write-once record rechecked inside gates, and hidden read-only PowerShell inspection. Console preflight/signal-sent receipt refinements remain a follow-up; this actual supervisor already exited normally. Draft hash mismatches remain explicit refusals.

- **OWNER-MAINT-008 (2026-09-28):** Serialize resident bridge and concurrent CLI pump acquisition with a bounded one-second exclusive-lock wait. No operation retry; persistent contention still refuses before work. Actual multi-process wait/timeout and concurrent CLI coverage; fixes CI-discovered status race.

- **OWNER-MAINT-010 (2026-09-28):** Audited profile-pointer-only preparation and one-time observation of a human-reopened, exact owner-demo monitor after recorded stop. No launch/close/grant/permission changes. Full SDK/native-session/protected-evidence/process checks; retain adopted_unverified for same-process re-verification. Fresh onboarding still refuses opaque saved permission flags. Source fixture qualification pending native use.

OWNER-MAINT-010 review follow-up: record and reverify Explorer parent/active console/plain executable argv; reject feedback older than the adopted process; resume only the immutable pointer-only CAS after interrupted publication, preserving original audit and all native line endings. Negative process/argv/session/freshness and interrupted-publication fixtures cover these boundaries. Banker pointer preparation alone has run; native adoption and batch remain unqualified.

OWNER-MAINT-010 publication-integrity follow-up: preserve complete schema-2 receipt bytes as original intent before publication; reject changed timestamp/schema/permission/launch fields or whitespace on resumption and new-receipt adoption. Interrupted receipt-copy recovery uses that exact intent. Completed legacy receipt adoption is unchanged, while legacy pointer replay without intent refuses. No retroactive intent creation or native operation retry.

OWNER-MAINT-010 accepted Banker review follow-ups before tester rollout: use retained parent evidence after Explorer loss while rechecking the target session/argv; recover an early crash during before/after artifact writes with fsync and exact-byte comparison; bind native observed_terminal_utc to process birth (in addition to mtime); add missing/duplicate parent, creation mismatch, altered temporary bytes and third-state common.ini regressions. Current console-only/parent-alive limits and same-user corroboration boundary are documented. Any separate Windows account/IAM change belongs to Vince.

OWNER-MAINT-010 timestamp follow-up: adoption and same-process re-verification reject embedded native observation timestamps older than process creation minus one second, even with freshly updated file mtime. Source regressions exercise copied prior-process feedback and retained interrupted-adoption refusal; native qualification remains separate. Parent-loss and early-artifact crash follow-ups remain open.

OWNER-MAINT-010 parent-loss follow-up: re-verification validates retained original Explorer evidence and the unchanged live target against the current console instead of requiring the parent to remain alive. First adoption still requires the parent present; changed process creation, target session/argv/parent identity and console refuse. Missing/duplicate-parent and creation-mismatch source cases added. Early-artifact crash recovery remains open; native qualification is separate.

- **RECOVERY-REVIEW-001 (2026-09-28):** Extend exact expired pre-consumption
  rejection settlement to ORPHAN_REVIEW_REJECTED, reported by a public beta tester.
  Keep all original evidence, confirmation, consumption, state and identity gates;
  no recovery retry, native flag, grant, wire or EA binary change. Run the complete
  settlement preservation/refusal/interruption matrix for both review and runtime
  refusals. Source tests and matched installed delivery remain distinct; the
  particular native validation predicate still needs the tester request/receipt.

- **RECOVERY-CLOCK-001 (2026-09-28):** Leave 15 seconds under the unchanged native
  recovery expiry ceiling; refuse publication on missing/invalid or over-five-second
  difference between terminal UTC and observation file write time. Retain the
  separate 20-second runtime freshness check. Source regression for a one-second-ahead controller and
  no-publication refusals; tester-specific cause and native qualification pending.

- **RECOVERY-STOPPED-001 (2026-09-28):** Explicit human-confirmed settlement of
  an expired pre-consumption rejection while the selected terminal is absent.
  Retain exact result replay barrier, local binding/state checks, archives, locks,
  consumed scan, ordered transport cleanup and durable mode. No offline owner
  authority, native flag edits, launch or old-observation reuse. Source tests and
  installed/native qualification required before customer delivery.

RECOVERY-STOPPED-001 inventory follow-up: scan all Windows-visible executable
paths under the selected install/data roots, regardless of process name; retain
named-terminal ambiguity and protected-peer checks. Record unreadable-system-path
limits explicitly. Restart during cleanup retains the fence and requires another
stop before same-review resumption. Source cases and real PowerShell/helper
qualification are separate from full native EA/installed-package qualification.

- **CONTROLLER-REPORT-RECOVERY-001 (2026-09-28):** Controller-owned recovery of
  the exact legacy-to-scoped generated Report baseline mismatch. Archive the
  original draft/restart and saved permission bytes, gracefully close the selected
  idle demo once, change baseline only while stopped, relaunch the existing inert
  monitor once, and require actual fresh EA/session alignment. Never discard user
  settings, manufacture a human reopen/grant, change permissions or start research.
  Fourteen focused fixtures pass, including actual MT5 expertmode=4 structure,
  unchanged permissions, refusals and interrupted transaction resumption. Full
  controller CI and native execution remain separate qualification requirements.

- **RESEARCH-BUDGET-48H-001 (2026-09-28):** Support172800-second bounded research driver. Preserve no-reset resume and disk guards. Fresh window after takeover requires genuine native re-grant; no amendment to revoked authority.

- **AGENT-SELF-REPAIR-001 (2026-09-28, Vince):** Customer agents should diagnose and repair stale-state mismatches, failed idle restarts and interrupted research locally through reusable evidence-preserving controller capabilities. Surface check/apply/reverify results, resumable transaction IDs and exact blockers; no bespoke support patch for each occurrence. Preserve actual connection/revocation and trading-permission boundaries. First qualification: Banker native re-grant and never-started-attempt recovery; then general customer coverage.
  The consumed `SETTINGS_NOT_VERIFIED` plus canonical cancelled/no-work case now
  has a read-only one-successor proof in the controller branch. Its synthetic
  regression and read-only Banker evidence check pass; reviewed packaging and
  native successor start remain pending. It cannot replay a consumed request,
  silently extend a grant, or treat source tests as batch qualification.
  Expanded owner requirement: simple goal-level tools for GOAT, builder and MT5;
  agent-managed WebRequest/DLL setup under retained user authorization; local
  troubleshooting and clear repair receipts; customer-controlled redacted reports
  that turn recurring fixes into tested shared recovery capabilities. No repeated
  manual reopen or routine approval loop. Acceptance and delivery order:
  [agent recovery tool contract](docs/operations/AGENT-RECOVERY-TOOLS.md).

- **TESTER-SEMANTIC-ROUNDTRIP-001 (2026-09-28):** Compare native MT5 tester
  readback using explicit V1.49 input types and exact active optimization ranges.
  Accept equivalent numeric, datetime and inactive-range serialization; allow only
  named startup fields and fixed native additions. Preserve all worker, grant,
  request and trading gates. Candidate V1.49-TESTER-SEMANTIC-14 compiled with zero
  errors and warnings, SHA-256
  56b8be6891cbcb54c806e59ead210c3a4a5d951e146b7cc113d22c8bf2b97abb.
  266 production-flow/schema fixture checks and exact-head Windows CI pass; admission and
  fresh native readback qualification are still required. Regression provenance
  and limitations: [tester fixture](controller/fixtures/tester-roundtrip/README.md).
- **TESTER-WORKER-CAPABILITY-001 (2026-09-28):** Replace MT5 build 6182 equality
  with a live owned-Agents-control/menu capability readback. Require local, remote
  and cloud commands and matching captions; close the owned popup on success or
  refusal. Candidate V1.49-WORKER-CAPABILITY-15R1 adds an independent
  6182/6230 Start-message gate before intent or arming. MetaEditor 6230 compiled
  with zero errors/warnings, SHA-256 8907841d7a1003a0abdec5bdbf2c84e4d7efbdc35e375153d7f6c2abf94d9366. This is source/compile proof only;
  Banker 6230 native menu readback and admission remain required. Unknown/localized
  menu labels fail closed and require a reviewed capability adapter.
- **TESTER-WORKER-IDLE-READBACK-002 (2026-09-28):** The 15R1 menu readback was
  reachable only inside Start after request consumption, so Claude's idle-only
  diagnostic approval could not be exercised. V1.49-WORKER-IDLE-DIAGNOSTIC-15R2
  adds one bounded readback from the existing read-only monitor after it opens,
  only on an idle connected demo with DLL permission, Algo Trading OFF, no batch
  flag and no pending native request. It logs the build/PID/account/tester state
  and local/remote/cloud menu result without reserving or starting a job.
  MetaEditor 6230 compiled with zero errors/warnings, SHA-256
  75d00db5865e4b0311faf91523504632ceb1d2269d8788622844955a541f4991.
  This is source/compile proof only; exact-head review, admission and native
  Banker readback remain required before the batch path.
- **TESTER-WORKER-FARM-CAPTION-003 (2026-09-28):** Banker build 6230 consumed
  an exact 115-member request and returned `WORKER_POLICY_NOT_VERIFIED` before
  start intent or tester execution. An owned, read-only menu probe observed
  command 33521 `Use Local Agents` checked, 33522 `Use Local Network Farm`
  unchecked, and 33525 `Use MQL5 Cloud Network` unchecked. The existing reader
  required 33522's caption to contain `remote`, so it refused the correct native
  local-only state. Recognize only the observed 6230 caption as an additional
  name for that same remote/LAN command; keep all IDs, checked-state checks,
  popup closure, and unknown-caption refusal. The consumed attempt was
  cancelled with its evidence retained; a new reviewed build and attempt need
  native qualification before calling the batch running. Candidate
  V1.49-WORKER-FARM-CAPTION-17 compiled on MetaEditor 6230 with 0 errors and
  0 warnings, EX5 SHA-256
  9c90b1493406e1cf849641d8eb1095ed9ea106767bb102fce520797ffdf32ffe.

| CTRL-022 | Visible native Give/Take control feedback | Source implementation; qualification pending | Immediate pending button/status, Take Control Yes/No warning, 30-second delayed acknowledgement with original request retained, receipt-confirmed current owner, Give Control Back action, persistent actionable refusal; a later save/queue clears old feedback. The derived Report-only difference is ignored in refresh, enqueue and grant while all other settings still compare exactly. No fabricated grant, retry, permission or trading change. User requested September 28. |

## CTRL-024 — Visible agent batch and OHLC standard (2026-09-28)

Owner-approved: show complete active batch in agent view, per-member model/status and total/completed/failed/cancelled/remaining counts. Child rows are read-only and cannot cancel/remove their parent. New optimization plans use 1-minute OHLC; explicit historical jobs remain immutable. Prevent background helper consoles and reduce expensive driver observations to 30 seconds. Focused visibility/process/driver tests pass; compile/native qualification tracked in PR. XML diagnostics name the scanned report root and file count. Report path/recovery fix remains a separate follow-up, not claimed complete here.

## CTRL-025 — Report-capable first-member launch

Vince-authorized EA/controller correction: direct-demo bounded run-batch uses a retained native arm → normal close → verified exit → exact /config launch. Preserve the existing passive-monitor profile and native owner grant, retain the original budget/attempt before any close, refuse replay or identity drift, and use a per-run installation-to-data report junction. The V1.49 arm action clears an old cancellation latch only after validating and durably consuming the newly authorized start; old versions retain their behavior. Native next-member restart helpers launch headlessly and report launch failure without closing MT5. Source tests/compile are recorded in the PR; first real OHLC report/export qualification is still pending.

CTRL-025 native qualification follow-up: the actual arm transport requires `restart_intent.arm_request_fields`; the initial runner omitted that retained proof and refused before native arming. Retain the exact validated fields from control installation, test against the real publication transport, and allow only bounded read retries for the known one-timer lag between the arm receipt and the runtime batch flag. Other policy mismatches still refuse immediately. EX5 and admission unchanged; failed pilot retained/cancelled normally, fresh pilot identity required.

## CTRL-026 — Export datetime readback and compact batch visibility

Native CR19 qualification produced the first paired OHLC reports. EURUSD Willow had no candidates above the frozen score threshold; USDJPY Phoenix completed optimization in 1m40s with qualifying candidates, then refused exports because MT5 rendered Sequence_Export_Start as epoch 1750896000 instead of 2025.06.26. V1.49-EXPORT-DATE-20 compares both explicit sequence dates by exact typed datetime in the actual fixed-export comparator. Missing, duplicate, invalid, changed or optimized dates refuse; no dates, thresholds, capture policy, trading logic or wire fields change. Ordinary non-capture comparisons keep their behavior. Compact agent view now retains the batch counters and sizes visible member rows to the available space.

277 executable comparison checks and MetaEditor 6230 compile (0 errors, 0 warnings) pass. Candidate EX5 SHA-256 b57aa3a65aa0f302db0142e6a43de32c602233b1c7476d449dd9eee4760ddd1e. Native SET/CSV/sequence export and compact UI qualification remain pending; paired XML alone is not full completion. Preserve the failed pilot, use a new attempt and the original retained batch deadline. Telemetry remains deferred.
