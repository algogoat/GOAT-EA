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
| AUTH-148-02 | Confirm activation reload actually leaves activation-only mode | Native gap observed; follow-up, no binary change | After approved activation and token installation, prove one successful OnInit and ordinary inert dashboard readiness; preserve idempotency and show an honest recovery state if reload does not occur |
| AUTH-148-03 | Renew finite demo authorization without reinitializing strategy charts | Design only; required before a multiweek experiment outlasts admission | Reviewed overlapping admission records, explicit approval, atomic pair-only credential replacement, unchanged chart/process identities and observed native consumption; never extend old credentials implicitly |
| OPS-148-01 | Reduce deployment work for reviewed EA admission changes | Measured workflow limitation; not implemented | A protected admission-only or exactly affected API release proves source identity, preserves other codebases and retains publication/canary/rollback checks; never bypass the current coupled lane |
| CTRL-001 | Controller-driven fresh local terminal/bootstrap | In progress; not qualified | Exact manifest, bounded startup, account/symbol/native readiness, retained failure receipts; no setup clicks |
| CTRL-001A | Manifest-driven secure demo connection | Contract tests, native login and encrypted-provider reconnection passed | Explicit role, exact process/account readback, stdin-only secrets, retained attempts, no automatic retry |
| CTRL-002 | Registered frozen portfolio import | Planned | Immutable source hashes, human names separate from strategy identity, no duplicate children on resume |
| CTRL-003 | Version-aware inventory and identity-based audit | Version-aware paths implemented/tested; sorted-row identity work pending | Inspect selected V1.48 path; handle display sorting without weakening member/input validation |
| CTRL-004 | Customer and agent Optimization Studio controller coverage | [Control/workflow audit documented](docs/operations/OPTIMIZATION-STUDIO-CONTROLLER.md); V1.48 version-aware launch and packaged controller qualification pending | Every supported control/workflow discoverable with exact schema, defaults, persistence and effect; explicit human/agent authority scopes, idempotent requests, durable receipts and recovery; version-correct source/path/binary binding, optional sequence setting round-trip, fresh-install native start/cancel/restart/completion E2E; unsupported operations reported honestly, no implicit launch |
| DOC-001 | Agent entry point and skill/tool routing | Written and validated | New agent can find supported commands and distinguish prototype/preview/deployment states |

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
