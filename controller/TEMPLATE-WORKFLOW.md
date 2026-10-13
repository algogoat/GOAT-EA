# Template creation and seed research

Use this user's installed catalog and local results. A new template is a new
research candidate, even when it descends from a previously successful file.
Do not transfer the parent's performance claims to changed inputs or ranges.

## Catalog templates and library variants need no retest

- **The 48 catalog templates and the library's variant SETs are already-validated
  research.** They don't need re-testing before use. Use them as they are.
- **`catchup-validate` is for exported research files**: the GOAT export pattern, a
  SET with its equity CSVs from a batch export. Its refusal on a catalog SET is
  expected. It doesn't mean the SET needs a retest.
- **SeedFarming is a search for NEW candidates**, not a re-test of proven files.
  Seed a template only to look for new settings or assets
  ([SEED-WORKFLOW.md](SEED-WORKFLOW.md)).
- **Equity for a library variant comes from the library evidence**, not from
  catch-up.

What this page covers is new work: a changed file is a new, untested candidate.

## A new strategy, start to finish

Every new strategy follows the same order: the user's own idea
([goat-strategy-create](skills/goat-strategy-create/SKILL.md)), a fork of a catalog
template ([goat-template-create](skills/goat-template-create/SKILL.md)) and designs an
agent drafts to fill a gap. Each step is one of GOAT's own tools, so any agent can
repeat it exactly. The installed agent guide (`goat-beta-agent-guide.md`, "A new
strategy, start to finish") gives the same order for the desktop side.

**Never put hand-written SETs or unseeded ranges into a production batch** (house
research, a FAT run or a customer batch). Don't skip the seed hunt: ranges that were
never hunted mostly measure the guess. In GOAT's own house research on 2026-10-13,
designs sent with hand-picked ranges straight into full runs found no profitable
setting at all in 18 of their first 31 runs. A design that skipped this order goes
back to step 1 as a new variant.

1. **Build from a real parent.** Clone the closest catalog template, or a blank from
   `starter-set --shape single|sequence` ("Start from blank" below). Never hand-write a
   SET. Write the spec ("Build a documented variant" below) with **wide, purposeful
   hunt ranges**: where the strategy uses them, open the inputs that change its
   behaviour most (ATR periods, indicator timeframes, lock-profit size and flexibility,
   and for sequences the progression inputs).
   ```powershell
   & '<agent kit>\goat.exe' studio --installation '<receipt.json>' build-set --source '<parent.set>' --output '<My strategies>\<name>.set' --spec '<variant-spec.json>'
   & '<agent kit>\goat.exe' studio --installation '<receipt.json>' validate-set --set '<My strategies>\<name>.set' --require-optimization
   ```
   Read `cartesian_combinations` in the reply to size the hunt before preparing it.
2. **Register it** with the desktop: `strategy.forkTemplate` (`templateId` for a
   catalog parent, `starter` for a blank), so it appears in Research as the user's
   untested strategy. The controller has no register command of its own: build-set's
   `.build.json` receipt is local provenance only.
3. **Seed hunt** ([SEED-WORKFLOW.md](SEED-WORKFLOW.md); "Seed loop" in
   AGENT-START-HERE.md): `seed-prepare`, `seed-start`, then `seed-resume` until it
   ends, then `seed-report`.
   - **Window:** in-sample only, ending **before** the earliest date the later proof
     reads (its `BackOOSDate`). Give the seed jobs explicit `FromDate`/`ToDate`. A seed
     plan with `oos_windows` reads that O's SAMPLE, which lies inside a proof batch on
     the same O and export Friday, so don't share one `oos_windows` between the seed
     and the proof.
   - **Size:** about 400 frames per member (`frame_target`), on the strategy's 3 most
     likely assets first.
4. **Read the seed honestly.** `summary.qualifying_count` counts rows that meet the
   plan's cutoff (`min_fitness`, `min_trades`); that cutoff admits net losers, and
   health only means "traded". Open each member's `result_path` file and count the
   candidates whose `metrics` have `Profit` > 0 **and** `Profit Factor` ≥ 1.05. A
   strategy with no such candidate on any asset is dropped and recorded, not re-hunted
   with small tweaks. Record every member, failures included.
5. **Promote the winners only.** For each member that has one, `seed-promote` the
   profitable candidate (step 4) with the highest `Result`:
   `seed-promote --batch-id <id> --candidate <candidate_sha256> --name <plain name> [--member <alias>]`.
   It writes `fixed.set` and `robustness.set` (the candidate's neighbourhood).
6. **Prove in an ordinary batch.** Put the promoted SETs in a `prepare-batch` plan with
   a forward window, on dates after the seed window (`seed_window.to_date` in
   `promotion.json`), and judge them like any template: forward, then FOOS. Declare
   the held-out lock (`heldOut.declare`) as it enters Prove. Only then can its files
   enter a portfolio pool. Each promoted or changed version counts as its own variant.

The controller checks each file (validate-set, `EA_INIT_REFUSED`, the
risk rules), but it does not check this order: `prepare-batch` accepts any validated
SET and does not compare a promoted SET's seed window with the batch dates. Following
the order is the agent's job.

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
It refuses any reachable combination the EA's own `OnInit` refuses from input values
(`EA_INIT_REFUSED`, below). A pass does not establish broker constraints, useful
economic effects, profitability or native readiness.
Use `discover` to inspect each input's own enum; never reuse numeric meanings
from a different enum or assume every integer between valid endpoints is valid.

## Start from blank

To build a new strategy from an idea rather than from a catalog template, follow
the [goat-strategy-create skill](skills/goat-strategy-create/SKILL.md). Check the
catalog first: when a template is already close, start from it instead.

```powershell
& '<agent kit>\goat.exe' studio --installation '<receipt.json>' starter-set --shape single --output '<My strategies>\Starter.set'
```

`--shape single` or `--shape sequence`. The starter is generated from the installed
input schema, so it always matches the EA's input interface: UTF-16 LE BOM and CRLF,
every input at its declared default except what the same-stem `.starter.json`
receipt lists in `fixes`. Every indicator signal mode of the dependency policy
(RSI, EMA, ADX, BB, MACD, RSI2) and its MustCheck are off, the AI bias filter is
`Bias_Disabled` and news is `News_Disabled`; nothing is searched. `single` sets
`Max_Seq_Trades=1` and `CloseAtMaxLevels=true` (the next gap against the trade
closes it; fixed lots). `sequence` sets `Max_Seq_Trades=5`, `CloseAtMaxLevels=true`,
`Mode_Lots=RiskperSeq` and `Sequence_MLPS_Hard_Close=true`, keeping the default
`Grid_*` gaps and lot growth. The receipt binds shape, schema hash, controller and
EA versions and the SET's SHA-256. Existing outputs or receipts are never
overwritten and the publisher catalog is refused. It never opens MT5.

A starter is structurally valid with no entry rule, but it is a blank, not a
strategy: the EA treats a disabled signal mode as "pass", so an unchanged starter
would open a new sequence at every signal check whenever none is open (both
directions with the default `Long_and_Short` and `Allow_Opposite_Seq=true`).
`validate-set` accepts it as `fixed_settings`; `build-set` takes it as `--source`,
adds the idea and must still leave at least one search axis. Its `.build.json`
records `parent: "starter:single"` (or `starter:sequence`) and `starter` with the
receipt hash, the entry signals enabled and any warnings. A starter whose bytes or
schema no longer match its receipt, or an unmodified starter without its receipt,
is refused; a starter is recognised by its `EA_Desc` even after an MT5 re-save
drops its comments. Both starters keep `Risk` at the schema value only as a
placeholder, listed in the receipt's `user_choices_required` and marked by a
`; GOAT Risk not chosen:` comment line. build-set keeps that marker on every
descendant until a change sets `Risk` (stating the placeholder amount counts as the
user's choice) and records `risk.never_chosen` in each `.build.json`. Any
descendant that sizes by `RiskperSeq` or hard-closes at Risk while the marker is
still there is refused with `RISK_NOT_CHOSEN`, by build-set and by every
`validate-set`/batch/seed/catch-up check of its bytes. The marker is a comment, so
a file re-saved by MT5 loses it; build-set restores it from a matching
`.build.json` when one is beside the file.

**Risk-per-sequence needs at least 2 trades, for every strategy.** The rule lives in
the shared strategy validator, so every controller path that accepts a strategy
applies it: `validate-set`, `build-set`, `prepare`, `prepare-batch`, raw
`queue.enqueue_batch`, the EA panel's strategy draft, seeds, catch-ups, promotions
and `deploy-load` (checked on each member's exact bytes before anything is
written). It refuses any reachable combination of `Mode_Lots=RiskperSeq` and
`Max_Seq_Trades<=1`: current values, every value of an active ladder and the first
field of a dormant `N` tuple, which MT5 runs; an input a partial SET leaves out is
the EA's declared default. A schema with `Mode_Lots` but no `RiskperSeq` choice or
no `Max_Seq_Trades` is refused (`RISK_SIZING_SCHEMA_UNRECOGNISED`) instead of
switching the rule off. Reason code
`RISK_PER_SEQUENCE_NEEDS_TWO_TRADES`: "Risk-per-sequence sizing needs at least 2
sequence trades; use fixed lots or raise Max_Seq_Trades. Single-trade risk sizing
isn't available yet. We'll say so in the release notes when it ships." With fewer than 2 trades the EA's planned loss path
is empty, so its lot solver climbs to the broker's maximum volume.

**The EA's own init refusals, for every strategy (`EA_INIT_REFUSED`).** The same
shared validator mirrors every `OnInit` refusal of the EA that depends only on input
values (`controller/studio_ea_init_rules.py`, `EA_INIT_RULES`, each with its
`GOAT V1.49.mq5` line and the EA's own alert text): for example Smart Rescue
(`Mode_Bias_Exit=BiasExit_SmartRescue`) without `Mode_Lots=RiskperSeq` and `Risk>0`,
`Risk<10` with risk sizing, MLPS hard close or Smart Peak, Smart Peak percentages
outside 0-100, RRR on with `RRR<=0` or an inconsistent SL/TP or SL/LP pair,
`|Grid_Size|<0.5`, LP and TP both disabled, malformed `Active_Time_*` sessions and
inconsistent export dates in `EA_Desc @{mode=EXPORT,...}`. It is checked over every
value MT5 can run: the current value, every value of an active ladder and the first
field of a dormant `N` tuple. **Any failing combination refuses**, for fixed SETs
and optimization ranges alike, because an init-failing pass produces nothing and an
exported or template SET must never fail init. The message names the rule, the
first failing combination and quotes the EA's alert; fix the SET (narrow the
range), never the rule. More than 10,000 combinations for one rule is refused as
uncheckable; narrow the named ladders. A GOAT schema that lost an input or enum label
a rule reads is refused (`EA_INIT_SCHEMA_UNRECOGNISED`). Refusals that depend on the
symbol, account, files or run context (tester vs live) are listed in `NOT_PORTED`
with the reason, and a test keeps both tables complete against the EA source.

## Build a documented variant

Clone a real compatible SET (or a starter from `starter-set`); never hand-author a
replacement file from scratch.
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
operation, using the selected parent template ID and exact output bytes
(`{templateId, name, contentBase64}`; for a starter parent
`{starter: 'single' | 'sequence', name, contentBase64}` instead). Keep
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
