B43 (`V1.49-BETA17-43`) is B41 plus the EA half of the beta.25 profile-staged deploy, as Claude-Mac approved on
goatai#1885 (design 6033442072, rulings 6033450916, APPROVE of `54aac277` in 6034810079 with the deployment-nonce
follow-up), plus CA41 ported from `4f3f2f9`. B41.1 to B41.3 (#186) are not merged. The proposal names no build ID, so
this uses the one Release specified for that case (B43; B42 is not used here). See **Build**.

**Why.** On every V1.49 build, MT5 accepted (`ok=1`) and never performed the `ChartApplyTemplate` the GOAT dashboard
issued for a child; scripts and other EAs applying the same template succeed. The template attach path is therefore
retired, not kept dormant. The controller now writes every child into the staged deploy profile and MT5 loads them
at start-up; the dashboard only adopts what it finds. `docs/operations/DEPLOYMENT-STARTUP-LIVENESS.md` (last section)
records the open question and links the native evidence.

**What changes from B41**

| Where | What it does |
|---|---|
| `GOATPortfolioSetupControl.mqh` | New `link_children` action: one adoption pass, then the normal snapshot (`children_linked` or `children_pending`). Adoption tries the TSV cid first, otherwise walks every chart, fingerprints each candidate once and links only a one-to-one match of symbol, period (full SET-name token: `M15` is M15), this EA (`CHART_EXPERT_NAME`), a CID record naming a magic no other row holds, and a saved-template snapshot that reproduces the row's frozen SET at its registered sha256 (the `settingsMatch` rule) **plus this deployment's nonce**. The registration may carry `deploymentId` (32 lowercase hex). Adoption requires it, so a registration without one adopts nothing (`child_deploy_unbound`). Inert demo only. Never opens, closes or applies anything to a chart. `deploy_next` gets the refusal `rejected_deploy_next_retired` and changes nothing. An unadopted row reports `chartId 0, magic 0`; receipt envelope and row fields are unchanged. Diagnostics: `child_unmatched`, `child_identity_ambiguous`, `child_not_started` (after 240 s). |
| `Dashboard.mqh` | `AdoptChild` persists the identity (`SaveDashboardConfig`) before it counts, consumes the child's pending registration, writes the AI launch audit (`ADOPTED`). Deleted: `DoActivate`, `TF`, `BuildTemplate`, `SaveTemplateAndCopy`, `DeleteCopiedTemplate`, `ApplyTemplate` (ChartOpen, ChartApplyTemplate, 20 s in-handler wait), `NewSingleInstance`, `AgentDeployRow`, `DeployAll` and the kernel32 copy/delete imports. Activate and Deploy All show "Use Next in the app to deploy; dashboard deploy returns in the next update" (labels "Pending" and "Deploy in app"). A child status event no longer assigns a magic. Navigate, pause, risk, exposure, currency rules, views and statistics are unchanged. |
| `GOATPortfolioChildAudit.mqh` | `settingsMatch` split into `GoatChildChartSnapshot` (by chart id), `GoatChildSetSource` and `GoatChildSnapshotMatchesSet`, used by both the audit and adoption; same rules. CA41: six WriteSet-omitted inputs accepted only at their declared defaults. **Deployment nonce:** with the registration's `deploymentId`, the WriteSet-omitted sinput `Studio_MonitorRunPath` must hold exactly `deploy=<deploymentId>`; without one it keeps its `""` default. Everything else is compared exactly. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-43`, marker `B43`, and **one trade-path line**: the staged-child gate at the top of `DashboardEntryAllowed` (below). Nothing else. |

**Live-before-adoption gate (goatai#1885 6035859714).** A profile-staged child starts with `expertmode=5`. If someone
turned Algo Trading on during the start-up window, it could trade before the dashboard had adopted it and applied its
exposure policy. Now a child whose `Studio_MonitorRunPath` carries a `deploy=` nonce opens nothing new until the dashboard
has written its marker:

- **The marker:** `<Key>_ID_<magic>_<symbol>_PDEPLOY`, a GlobalVariable whose value is the deployment id's first 13 hex
  digits, exact in a double.
- **What stays shut until then:** no sequence start (real or virtual) and no virtual-to-real promotion. That is every
  path through `DashboardEntryAllowed`, the existing single entry gate.
- **When the dashboard writes it** (`GoatPortfolioMarkPolicyApplied`, on every poll with a registration that binds a
  deployment, before the request is handled): only after it has read that child's acknowledgement of the exposure
  policy that `apply_policy` dispatched, with the matching command ID, ACK status applied, and the registered mode.
- **Not gated:** adding levels to an existing sequence, closes, trailing and stops never pass through the gate.
- **Every other child:** a child without the `deploy=` prefix (every normal SET, tester runs, the Exp terminals) returns
  `true` at the gate's first line and reads no GlobalVariable. Its `DashboardEntryAllowed` answers are B41's (tested
  across every input).
- **Restarts:** the marker persists with the terminal's GlobalVariables, so a restarted live portfolio opens as before.

**Why `Studio_MonitorRunPath` carries the nonce, not `EA_Desc`.** `EA_Desc` is on the trade path. It becomes `Strat`,
then each sequence's `Desc`, which is the order comment, and the fill lookup matches positions by that comment
(`GOAT V1.49.mq5:366`, `:6310-6312`). A longer `EA_Desc` would also be cut at MT5's comment length.
Two kinds of code read `Studio_MonitorRunPath`. The Studio reads it only when `Studio_ReadOnlyMonitor=true`
(`GOAT V1.49.mq5:2749-2751`, `Optimizer.mqh:418-420`, `:2830-2834`), which the audit pins to `false` for every child. The
staged-child gate reads it too, and acts only on the `deploy=` prefix. `WriteSet` omits it, so no frozen SET carries it,
and the audit already compares it as exact text. It is an existing sinput, so no input is added and the input header is
unchanged. A test pins every reader of it.

**Not changed.** Every input and default, the input header (`1408e1ee…`, SM32's), `WriteSet`, Astra's inputs, the
trade-event policy, the bias wire and the model route. On the trade path the only change is the gate line, guarded by the
nonce. `scripts/test_b43_no_drift.cjs` proves that the entrypoint, with its build ID, marker and gate line restored, is
B41's exact bytes. `StartExporter`, `OnTick`, `GoatTickBody`, `OnTradeTransaction`, `OnTimer`, `SignalEntryTrigger` and
`DashboardTradeAllowed` are byte-identical to B41. Every other closure file except the three above is byte-identical
to B41.

**Tests.** `scripts/test_profile_staged_adoption.cjs` covers production adoption, the real settingsMatch parser with
the nonce, AdoptChild, the registration binding, the dispatch, the receipt rows and the buttons against a modelled
terminal, plus the retired-path grep and the warning-62 guard. Also `scripts/test_profile_staged_adoption_mutations.cjs`,
`scripts/test_b43_no_drift.cjs`, `scripts/test_portfolio_child_audit.cjs` (CA41 and the nonce), and the rewritten
deploy-path, binding, overview and liveness tests.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-43`, marker `B43`.
- Compiled once from `e38791d6` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39 to B41.3):
  0 errors, 0 warnings. The compiler was a copy outside every terminal folder, run `/portable` at Idle priority.
  MetaEditor's process exit code was 1 with a clean `Result:` line, as in the B40 and B41 compiles; the `Result:`
  line and the output are the success criteria. The stage was a scratch copy outside every terminal folder. Its 307
  standard includes and the `MACD - GOAT 2.ex5` resource are copied from the B41 compile root and hash-equal to it.
- `GOAT V1.49.ex5`: sha256 `e630ee34cb04c26513f16860a927074ec745f3c62869d984260230a89fd4dc24`, 2,426,134 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `8b980f0c…8bed2ca1`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `e38791d6`: the 41 `.mq5`/`.mqh` files in the entrypoint's include closure are exactly the 41
  sources in `identity.json`, and each matches the tree and the staged copy. The input header is still `1408e1ee…`.
- `externals.json`: no problems, and the same per-name hashes and `consumed_sha256` (`ced68559…`) as B41's. Removing
  `Dashboard.mqh`'s kernel32 copy/delete import block does not change the hashed externals: DLL imports are compared
  by name, and `kernel32.dll` is still imported by `MTTester.mqh` and `Tester.mqh`, so the by-name import set
  (`kernel32`, `shell32`, `user32`) equals B41's.
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.
- `54aac277` and `b3e7cedb` were each compiled with 0 errors and 0 warnings. The deployment nonce and the
  live-before-adoption gate changed the sources since then (including the entrypoint), so neither binary is carried
  here.

**Not done.** Not installed, no native qualification. The root `GOAT V1.49.ex5` is unchanged.

**Still owed:**
- Claude-Mac's review of this binary, pin and no-drift check, and a new admission row for `V1.49-BETA17-43`;
- the T3 proof P0 to P7 with the matching controller (`claude-pc/profile-staged-controller`, algogoat/GOAT-EA#193). That
  controller must stage `Studio_MonitorRunPath=deploy=<deploymentId>` in each child and register `deploymentId`.
