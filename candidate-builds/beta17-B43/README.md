B43 (`V1.49-BETA17-43`) is B41 plus the EA half of the beta.25 profile-staged deploy, as Claude-Mac approved on
goatai#1885 (design 6033442072, rulings 6033450916), plus CA41 ported from `4f3f2f9`. B41.1 to B41.3 (#186) are not
merged. The proposal names no build ID, so this uses the one Release specified for that case (B43; B42 is not
used here). See **Build**.

**Why.** On every V1.49 build, MT5 accepted (`ok=1`) and never performed the `ChartApplyTemplate` the GOAT dashboard
issued for a child; scripts and other EAs applying the same template succeed. The template attach path is therefore
retired, not kept dormant. The controller now writes every child into the staged deploy profile and MT5 loads them
at start-up; the dashboard only adopts what it finds. `docs/operations/DEPLOYMENT-STARTUP-LIVENESS.md` (last section)
records the open question and links the native evidence.

**What changes from B41**

| Where | What it does |
|---|---|
| `GOATPortfolioSetupControl.mqh` | New `link_children` action: one adoption pass, then the normal snapshot (`children_linked` or `children_pending`). Adoption tries the TSV cid first, otherwise walks every chart, fingerprints each candidate once and links only a one-to-one match of symbol, period (full SET-name token: `M15` is M15), this EA (`CHART_EXPERT_NAME`), a CID record naming a magic no other row holds, and a saved-template snapshot that reproduces the row's frozen SET at its registered sha256 (the `settingsMatch` rule). Inert demo only. Never opens, closes or applies anything to a chart. `deploy_next` gets the refusal `rejected_deploy_next_retired` and changes nothing. An unadopted row reports `chartId 0, magic 0`; receipt envelope and row fields are unchanged. Diagnostics: `child_unmatched`, `child_identity_ambiguous`, `child_not_started` (after 240 s). |
| `Dashboard.mqh` | `AdoptChild` persists the identity (`SaveDashboardConfig`) before it counts, consumes the child's pending registration, writes the AI launch audit (`ADOPTED`). Deleted: `DoActivate`, `TF`, `BuildTemplate`, `SaveTemplateAndCopy`, `DeleteCopiedTemplate`, `ApplyTemplate` (ChartOpen, ChartApplyTemplate, 20 s in-handler wait), `NewSingleInstance`, `AgentDeployRow`, `DeployAll` and the kernel32 copy/delete imports. Activate and Deploy All show "Use Next in the app to deploy; dashboard deploy returns in the next update" (labels "Pending" and "Deploy in app"). A child status event no longer assigns a magic. Navigate, pause, risk, exposure, currency rules, views and statistics are unchanged. |
| `GOATPortfolioChildAudit.mqh` | `settingsMatch` split into `GoatChildChartSnapshot` (by chart id), `GoatChildSetSource` and `GoatChildSnapshotMatchesSet`, used by both the audit and adoption; same rules. CA41: six WriteSet-omitted inputs accepted only at their declared defaults. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-43`, marker `B43`. Nothing else. |

**Not changed.** Trade, risk, signal and bias logic, every input and default, the input header (`1408e1ee…`, SM32's),
`WriteSet`, Astra's inputs, the trade-event policy, the bias wire and the model route. `scripts/test_b43_no_drift.cjs`
proves the entrypoint differs from B41 only in its two identity lines and every other closure file except the three
above is byte-identical to B41.

**Tests.** `scripts/test_profile_staged_adoption.cjs` (production adoption, AdoptChild, dispatch, receipt rows and
buttons against a modelled terminal; the retired-path grep; the warning-62 guard),
`scripts/test_profile_staged_adoption_mutations.cjs`, `scripts/test_b43_no_drift.cjs`,
`scripts/test_portfolio_child_audit.cjs` (CA41), and the rewritten deploy-path, binding, overview and liveness tests.

**Build**

- Compile pending.

**Not done.** Not compiled, not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:** the compile (0 errors, 0 warnings) by Release, Claude-Mac's pin and no-drift check, a new admission row
for `V1.49-BETA17-43`, then the T3 proof P0 to P7 with the matching controller (`claude-pc/profile-staged-controller`).
