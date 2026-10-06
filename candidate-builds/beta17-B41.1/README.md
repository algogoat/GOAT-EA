B41.1 is B41 plus six input names on the deploy audit's exemption list, as Claude-Mac specified on
goatai#1885 (6008656907). It is a hotfix: there is no trade-logic, input, default or SET-writer change. See
**Build**.

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

**Build**

- Compile pending.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's pin and no-drift check and the internal admission of `V1.49-BETA17-41.1`, then a
native deploy-load on a non-Exp demo that reads `settingsMatch` true for one V1.49-writer SET and one
Balanced35 SET.
