---
name: goat-optimize
description: Plan, benchmark, run and monitor GOAT MT5 optimization batches using the installed controller, including OHLC versus real-tick recommendations and verified report recovery.
---

Use the customer's installation receipt and installed `goat.exe studio` commands.
Read [the optimization playbook](../../OPTIMIZATION-PLAYBOOK.md) for model selection,
timing and report diagnosis; consult [the command reference](../../README.md) only
for the operation being used.

Start with `discover`, `resource-profile`, current batch/attempt status and actual
native worker observations. **1-minute OHLC is the standard for new searches.**
Recommend ETWRT selectively when the strategy's tick sensitivity warrants it and
the measured compute budget supports it. CPU count alone is neither enabled-worker
count nor a throughput estimate. Keep the optimization model separate from export
replay settings; preserve the user's explicit choice.

Freeze exact templates, symbols, periods, forward split, model and export policy.
Use a representative authorized timing pilot and `benchmark-report` before a large
estimate. Distinguish parameter combinations, genetic passes, forward passes and
retained report rows. Never promise a duration solely from a pass count.

Use the bounded controller driver for execution. Show the active member, model,
total/completed/failed/cancelled/remaining counts and observation freshness. Inspect
the existing attempt after a timeout before issuing another command. A revision
of the plan gets a new immutable batch; it does not rewrite the running job.

Verify a main/forward report pair, exported input identity and progression to the
next member. Stop repeated systematic export failures instead of exhausting the
batch. Preserve reports and failed attempts. Readiness, start acknowledgement,
native completion, verified exports and portfolio import are separate outcomes.
