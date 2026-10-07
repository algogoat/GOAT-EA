B41.1 is B41 plus two deploy-path fixes, both on goatai#1885. It is a hotfix: there is no trade-logic,
input, default or SET-writer change. See **Build**.

- **CA41:** six input names on the deploy audit's exemption list, as Claude-Mac specified (6008656907).
- **AA41:** the agent's child attach is asynchronous (6027754245). On B41 no agent deploy could attach a child.

**AA41: why.** The agent's `deploy_next` ran the dashboard attach inside its timer handler:
`ChartOpen`, then `ChartApplyTemplate` (which only adds the template to the chart's queue), then a wait of up to
20 s for the child's handshake, still inside the same handler. On T3 (deploy `56a46a8a`, 2026-10-06 23:50Z)
the template was queued at 23:50:04.151. No child EA loaded in the 20 s, and the dashboard deleted the template
at 23:50:24.197, inside that same handler. The terminal saved the child chart at shutdown (23:53:42) with no
expert. The controller reported `child_attach_failed`.

**AA41: what changes.** `AgentBeginDeployRow` opens the chart, persists the child identity, queues the template
and returns. `AgentPollDeployRow` runs the same `NewSingleInstance` handshake on later timer ticks, with the
same 20 s budget. On success it links the child and only then deletes the template. On failure it unwinds as
before: the row goes back to Pending, the template is deleted, and the chart identity stays as the
partial-deployment lock. The failed step is named in the deployment diagnostics
(`phase=child_attach_failed control=handshake_timeout`, `template_enqueue`, `chart_open`, …).
`GoatPortfolioSetupPoll` keeps the request's `started` receipt until the attach settles, and reads no other
request meanwhile. The receipt schema and its result values are unchanged, so beta.23's controller reads
B41.1 as it read B41. The human Activate / Deploy All path keeps its in-handler wait.

**Why.** On a deploy-load, `GoatPortfolioChildSettingsMatch` saves the child chart's template, and
`GoatChildAuditMaps` requires the frozen SET's input names to equal the template's, apart from three
exempt live sinputs. V1.49 declares six inputs that no SET carries, because `WriteSet`
(`GOAT_Inputs_Definitions.mqh`) omits them:

- `Sequence_Export_Enabled`, `Sequence_Export_Id`, `Sequence_Export_Start`, `Sequence_Export_End` and
  `Sequence_Export_Model` (`GOAT_SequencePackage.mqh`, from V1.48);
- `GOAT_FitnessRunNonce` (`GOAT V1.49.mq5`, from SM32).

MT5 writes declared inputs into the chart template. When it writes these six, the name counts differ, and the
audit refuses every B41 deploy-load with "child inputs differ from the frozen SET".

**What changes from B41**

| Where | What it does |
|---|---|
| `GOATPortfolioChildAudit.mqh` | `GoatChildAuditMaps`: after the three existing exemptions, a second list of six names with their declared defaults (`false`, empty, `0`, `0`, `4`, `0`). If the child template carries one of them and the SET does not, the audit adds it at its default. The existing value check then requires the template to hold exactly that default. A SET that carries one still compares it value for value. A name in neither is skipped, so a V1.47 child, which declares none of them, audits exactly as before (V1.48 declares the five `Sequence_Export_*` and would get the same relief if rebuilt; its committed binary is untouched). Any other unknown name still fails. |
| `Dashboard.mqh` (AA41) | `AgentDeployRow` becomes `AgentBeginDeployRow` plus `AgentPollDeployRow`. `ApplyTemplate` is split into `BeginChildAttach`, `FailChildAttachTimeout` and `CompleteChildAttach`, with the same statements. `DoActivate`'s prelude becomes `PrepareChildLaunch`, shared by both paths, and it refuses while an agent attach is in flight. |
| `GOATPortfolioSetupControl.mqh` (AA41) | `deploy_next` starts the attach and returns. `GoatPortfolioAttachContinue` settles it on later ticks and writes the final receipt. A busy owner lock or a failed write is retried on the next tick. |
| `GOAT V1.49.mq5` | Build ID `V1.49-BETA17-41.1`, marker `B41.1`. `GOAT_VERSION_LABEL` stays `1.49`, so `GOAT V1.49 …` SET filenames and the input header stay valid. |

**Not changed.** Trade, risk, signal and bias logic, every input and default, the input header
(`1408e1ee…`, SM32's), `WriteSet`, the deploy-load SET bytes, the three existing exemptions, Astra's inputs,
the trade-event policy, the bias wire and the model route. Deploy-load does not fill defaults into the SET,
which would change SET bytes and break the hash chain.

**Why default-pinned, not ignored.** The existing exemptions require the inert default rather than ignore the
value, and these six follow suit: a child running with `Sequence_Export_Enabled=true` or a stray nonce is not
the frozen strategy, and the audit still refuses it.

**Tests.** `scripts/test_portfolio_child_audit.cjs` runs the production parser: a V1.49 template carrying the
six at their defaults passes; any one at a non-default value fails, as does a SET/template disagreement on one
the SET carries, or an extra unknown name. B41's audit fails the first case, which reproduces the bug.
`scripts/test_dashboard_async_attach.cjs` runs the production attach code against a modelled MT5 that drains chart
queues after the handler returns. B41's in-handler wait reproduces T3, and the async path attaches all 35
members. The timeout, enqueue-failure, busy-lock and failed-write paths all unwind, and 8 of 8 mutants are
killed. `scripts/test_b41_1_no_drift.cjs` checks the source against B41 (`278ec109`), normalised: only
`Dashboard.mqh`, `GOATPortfolioSetupControl.mqh` and `GOATPortfolioChildAudit.mqh` differ, and `StartExporter`,
`OnTick`, `OnTradeTransaction` and `OnTimer` are identical.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41.1`, marker `B41.1`, on top of B41 (`278ec109`, GOAT-EA#147, compiled in #150).
- **Compile pending for this source (CA41 + AA41).** Nothing below is a binary of it. The earlier CA41-only
  binary (`b3650d96…`, from `4f3f2f99`) is superseded and has been removed from this folder, together with its
  receipt and `externals.json`. They stay in history at `f00cc8ad`. Do not install it.
- History, CA41 only: compiled once from `4f3f2f99` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`,
  the same compiler as B39, B40 and B41): 0 errors, 0 warnings. The compiler was a copy outside every
  terminal folder, run `/portable` at Idle priority. The stage was a scratch copy outside every terminal folder. Its 307 standard includes and the
  `MACD - GOAT 2.ex5` resource are copied from the B41 compile root and hash-equal to it. `externals.json` records
  the same per-name hashes as B41's, and the same `consumed_sha256` (`ced68559…`).
- `GOAT V1.49.ex5`: sha256 `b3650d96f7d12b22a76d9905989f62fa95967cee204a89d83d0d1a4f7f9abb38`, 2,429,020 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `dee033a8…7e8fa56b`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `4f3f2f99`: all 41 sources in `identity.json` match the tree and the staged copy; only
  `GOAT V1.49.mq5` and `GOATPortfolioChildAudit.mqh` differ from B41. The input header is still `1408e1ee…`.
- No drift: under `studio_equivalence`'s normalization (CRLF to LF, and the `GOAT_BUILD_ID`/`GOAT_BUILD_MARKER`
  defines), the entrypoint is byte-identical to B41's (`261f0c9e…`). `studio_function_units units-diff
  278ec109 → 4f3f2f99` reports `GOAT V1.49.mq5: identical`, `Optimizer.mqh: identical`. The only normalized
  closure change is `GOATPortfolioChildAudit.mqh` (`5d275540…` → `180986e4…`).
- MetaEditor output is not byte-reproducible across stages, so admit only this binary.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:**

1. Claude-Mac's review and the compile of this source.
2. Claude-Mac's pin check, no-drift check and internal admission of `V1.49-BETA17-41.1`.
3. A native deploy-load on a non-Exp demo. It must attach the child charts, the first one included, and read
   `settingsMatch` true for one V1.49-writer SET and one Balanced35 SET.
