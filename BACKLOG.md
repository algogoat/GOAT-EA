# GOAT EA and controller work

This branch starts from the retained R5 build. Entries below cover the agreed
V1.48/dashboard work; they do not replace other branches' historical backlog.

| ID | Work | State | Acceptance |
|---|---|---|---|
| UI-148-01 | Restore **Dashboard** chart navigation | Implemented; native QA pending | Exact dashboard is brought forward after ordinary restart; missing/ambiguous target handled |
| UI-148-02 | Clear AI/exposure summaries and grouped controls | Implemented; native QA pending | Readable at supported window sizes; all controls reachable; unknown/mixed policy never presented as confirmed |
| UI-148-03 | Remove noisy overview stale column and fair child polling | Source tests passed | Diagnostics retains useful age; one silent child cannot starve the remaining fleet |
| AUTH-148-01 | Isolate new pair credential and pending paths | Compile/source tests passed | Separate legitimate admission and real activation work; existing six credentials remain valid |
| CTRL-001 | Controller-driven fresh local terminal/bootstrap | In progress; not qualified | Exact manifest, bounded startup, account/symbol/native readiness, retained failure receipts; no setup clicks |
| CTRL-001A | Manifest-driven secure demo connection | Contract tests, native login and encrypted-provider reconnection passed | Explicit role, exact process/account readback, stdin-only secrets, retained attempts, no automatic retry |
| CTRL-002 | Registered frozen portfolio import | Planned | Immutable source hashes, human names separate from strategy identity, no duplicate children on resume |
| CTRL-003 | Version-aware inventory and identity-based audit | Version-aware paths implemented/tested; sorted-row identity work pending | Inspect selected V1.48 path; handle display sorting without weakening member/input validation |
| DOC-001 | Agent entry point and skill/tool routing | Written and validated | New agent can find supported commands and distinguish prototype/preview/deployment states |

Evidence and current limitations: [V1.48 verification](docs/operations/V1.48-DASHBOARD-VERIFICATION.md).
Operating entry point: [agent guide](docs/operations/AGENT-START-HERE.md).
