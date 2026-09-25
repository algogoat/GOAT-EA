# Template creation and seed research

Use this user's installed catalog and local results. A new template is a new
research candidate, even when it descends from a previously successful file.
Do not transfer the parent's performance claims to changed inputs or ranges.

## Validate an existing SET

```powershell
& '<agent kit>\goat.exe' studio --installation '<receipt.json>' validate-set --set '<template.set>' --require-optimization
```

This reads the file only. It checks UTF-16 LE BOM, CRLF, the complete installed
input interface, current values, declared enum values and every enabled numeric
ladder. It reports active axes and Cartesian combination count. The count is not
a promised genetic pass count. `--require-optimization` rejects fixed exports
with no active search axes; omit it when inspecting fixed settings.

The shipped dependency policy covers indicator-mode gates. It rejects a searched
indicator input whose controlling mode is disabled for the entire search and
reports conditionally inactive modes. **Unchecked axes require further review.**
A pass does not establish initialization compatibility for every combination,
broker constraints, useful economic effects, profitability or native readiness.
Use `discover` to inspect each input's own enum; never reuse numeric meanings
from a different enum or assume every integer between valid endpoints is valid.

## Build a documented variant

Clone a real compatible SET; never hand-author a replacement file from scratch.
Choose a new local output path outside the publisher catalog. Existing outputs,
source paths and existing support/provenance files are never overwritten.

```powershell
& '<agent kit>\goat.exe' studio --installation '<receipt.json>' build-set --source '<parent.set>' --output '<My variants>\Candidate.set' --spec '<changes.json>'
```

The JSON spec contains exactly these fields:

```json
{
  "ea_desc": "RSI Sampling Candidate",
  "changes": { "RSI_Period": "7||3||2||9||Y" },
  "rationale": { "RSI_Period": "Compare the declared RSI sampling periods on development data; only meaningful with primary RSI enabled." },
  "summary": "Untested range variant of the selected parent.",
  "entry_logic": "Describe every enabled entry filter in this actual parent, including fixed gates and how the change affects it.",
  "ladder_exits": "Describe the actual sizing, additions, partial closes, stops and exits; review interactions with this edit.",
  "intended_role": "Describe the proposed role and intended assets; no performance claim before testing."
}
```

The sample range is illustrative. Use it only when justified by the selected
parent's active logic and current installed schema. Replace the prose with real
source-aware descriptions. Every changed input needs a rationale; unchanged or
unknown replacements, multiline SET injection, unsupported enums, inactive axes
and invalid ladders fail before writing.

`changes` supplies exact scalar or `value||start||step||stop||Y/N` strings.
`ea_desc` is a readable prefix; the builder appends a unique variant suffix.
The parent bytes, comments, section order, blank lines, untouched inputs, BOM and
CRLF remain preserved. The new output must retain at least one active axis.

The result includes three files: the new `.set`, same-stem `.md` support notes
and `.build.json` provenance receipt. Notes distinguish author-supplied design
claims from automated checks. The receipt binds parent/new/support hashes,
schema, versions, exact input changes, reasons and limitations. It is published
last; missing receipt means an incomplete write requiring inspection. Never
overwrite a partial output to hide the failure.

Register the validated result with the desktop's `strategy.forkTemplate`
operation, using the selected parent template ID and exact output bytes. Keep
the support notes and build receipt with the fork. Fork storage does not perform
this typed construction/validation itself. Record the candidate as **untested**
in the living matrix. Catalog updates must preserve this local fork.

## Run bounded research and retain every outcome

1. Freeze a development plan before execution: templates/hashes, exact broker
   symbols, windows/forward split, model, sizing/costs, candidate/pass budget,
   selection rule and untouched validation periods. Obtain the user's scope
   and resource budget. Use the installed batch commands and their discovered
   constraints; file construction itself never starts MT5.
2. Confirm each active axis changes the intended logic. Disabled branches,
   derived distances, lot-mode interactions and initialization constraints need
   semantic review beyond the partial validator. Document fixed policy controls
   as carefully as optimized fields. Keep temporary screening/fitness settings
   distinct from the final template's settings.
3. Preserve raw native runs and actual counts. Genetic search can converge below
   a requested count; normal completion with fewer samples is not automatically
   a failure. Technical failures, zero candidates, missing exports, cancellations
   and unknown completion must remain visible, with separate retry identities.
4. Choose a bounded, deduplicated set of fixed candidates by exact canonical
   trading inputs, not by pass number or filename. More trials and wider ranges
   do not establish robustness. Freeze chosen inputs before held-out validation;
   repeated tuning against that period makes it development data.
5. Verify runtime inputs, history quality and actual reports before interpreting
   results. Preserve forced end-of-test liquidation and all trading costs. Keep
   partial-close counts separate from independent completed sequences. Never
   delete losing cycles to improve reported performance.
6. Record every outcome in local matrix history, including preparation failures.
   Tie observations to template revision/hash, variant receipt, job/attempt,
   model, dates, sizing and broker symbol. Record source-reference evidence and
   new variant evidence separately. Promote only after the stated gates pass.

Native Seed Finder/Seed Farming modes have their own output/cleanup requirements.
Do not silently treat ordinary portfolio-export batch controls as proof of a
qualified seed campaign runner. Discover installed mode support and select the
documented route. Before returning from seed work to ordinary batches, inspect
owned local report leftovers and completion receipts. Never clear source SETs,
shared evidence or tester caches while their owning process is active. There is
no automatic destructive cleanup in these template commands.
