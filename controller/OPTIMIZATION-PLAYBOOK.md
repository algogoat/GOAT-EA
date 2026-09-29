# GOAT optimization playbook for customer agents

Use this alongside `AGENT-START-HERE.md` and the command reference in `README.md`.
It is part of the product agent kit. No developer checkout, private skill,
developer machine paths or copied account credentials are required.

## Choose the model and compute budget

**GOAT's standard for optimization is 1 minute OHLC (`Model=1`).** It is the
starting recommendation for broad searches, including large batches. Preserve an
explicit customer choice; explain a proposed change before replacing a saved run.
Never silently change a frozen batch or present runs with different models as
equivalent. The optimization model and the fixed export/replay model are separate.

| Model | When to recommend it | Cost and interpretation |
| --- | --- | --- |
| 1 minute OHLC (`1`) | Default broad optimization and quick screening | Four modeled prices per minute; generally far less work than tick processing. Intraminute price paths are simplified. |
| Every tick based on real ticks / ETWRT (`4`) | Focused validation where tick order, spreads, short holding periods or intraminute stops materially matter | Uses broker tick history; larger downloads and processing demand. Benchmark the exact workload. A faster machine does not remove the need to choose based on strategy behavior. |

These model definitions follow [MetaQuotes' optimization documentation](https://www.metatrader5.com/en/terminal/help/algotrading/strategy_optimization).
An effective workflow is OHLC search followed by an explicitly scoped real-tick
check of selected candidates. Do not automatically run the whole search twice.
Do not alter costs, leverage, dates, ranges or export policy merely to improve speed.

1. Run `discover` and `resource-profile` using the customer's installation receipt.
   Inspect CPU, physical/logical cores, available RAM and free disk. Logical cores
   do **not** prove that the same number of MT5 workers is enabled.
2. Inspect actual local worker availability and native tester state through the
   installed controller. Report unavailable observations as unknown. Keep paid
   cloud/remote workers off unless separately authorized.
3. Recommend OHLC when broad coverage, limited memory/disk or a short compute
   window favors speed. Recommend a small ETWRT comparison when the strategy's
   execution sensitivity warrants the additional cost. State the tradeoff and
   the chosen model in the plan.
4. Within the user's authorized budget, time representative members, including
   export/forward work. Use `benchmark-report` on a completed verified pilot.
   Separate initial data downloads, cached reruns, native compute, exports and
   between-member restarts. Record the sample count and observed range.
5. Estimate remaining time from comparable observed members, not CPU names or
   the theoretical parameter count. Genetic passes, forward passes, cached
   results and retained report rows are different quantities. No universal
   "1280 passes in seconds" estimate applies.

## Prepare and run through the controller

Discover the exact selected terminal, data directory, paired account, installed
EA identity and supported commands. Read current owner/STOP state and outstanding
attempts before mutation. Preserve the user's actual grant and account; agents
cannot invent pairing or click a human-only grant on their behalf.

Use validated templates and explicit tester/export settings. Check broker symbols,
active optimization axes, date/forward ordering, model, local workers, free disk
and output paths. Prepare a new immutable batch identity for changed conditions.
Use the installed bounded driver and its retained deadline. Observe before retrying
any timeout; a timeout does not prove that a native command failed.

During a batch, show its ID, total, active member, each member's symbol/strategy/model,
completed, failed, cancelled and remaining counts. Include observation freshness.
Keep progress available under both human and agent ownership. A completed native
optimization is not the same as verified exports or successful portfolio import.

## Diagnose and repair, then report

Use the installed supported diagnosis/recovery tools first. Collect the exact
failure, native logs, request receipt and affected paths. For XML failures check
the effective `Report` value, main and forward files, report timing, and which
directory MT5 actually writes to. [MetaQuotes documents Report as relative to the
platform directory and requires its subdirectory to exist](https://www.metatrader5.com/en/terminal/help/start_advanced/start).
Do not assume that an in-UI settings paste and a `/config` launch honor every key
the same way. Stop repeated systematic failures rather than burn the remaining batch.

Repairs must preserve inputs, results, grants and exact ownership. Back up the
affected files, apply a supported bounded repair, verify the actual native result,
and resume only after readiness is established. Never wipe Common Files, history,
the vault or an uncertain attempt to make a check pass. Keep Algo Trading off.
If a needed repair is unsupported, preserve evidence and report the precise gap;
do not pretend a source patch is an installed or qualified fix.

Give the user a concise repair receipt: symptom, diagnosis, files/settings changed,
before/after identities, verification, remaining limitation and rollback location.
With the customer's authorized support submission, send a redacted diagnostic
report and patch/proposal through the product support path. Exclude credentials,
tokens, account secrets and unrelated private files. Local agent fixes are not
automatically trusted as product releases; retain review and reproducible tests.
