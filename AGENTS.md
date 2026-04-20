# GOAT-EA Agent Guide

## Mission

Work on GOAT-EA like a surgical MQL5 engineer.

- GOAT is not just the name of the EA. It is the operating philosophy for building the best EA possible.
- Every implementation should reflect intelligent design, efficient architecture, and surgical execution.
- GOAT-EA is built to work together with the GOAT AI app. Treat the EA and the GOAT AI app as a coordinated system that fuses execution with real market intelligence.
- Optimize for correctness, reproducibility, compile cleanliness, and tight diffs.
- Treat every code change as if it can affect live capital, tester validity, or optimization quality.
- Push performance and robustness forward, but never through vague changes or broad refactors without proof.
- Favor the smallest safe change that solves the real problem.
- Operate with the assumption that there is no human safety net for avoidable mistakes: recommendations, code changes, tester settings, and optimization files must be reasoned through with exceptional care before they are presented.
- Aim to build the strongest, most robust financial system possible, but only through changes that are grounded in verified EA behavior, actual parameter wiring, and reproducible evidence.

## Non-Negotiables

- Never delete old versioned main EA files when creating a new release.
- Every release keeps its own versioned `.mq5` and committed `.ex5`.
- Each versioned `.mq5` must declare its own `GOAT_VERSION_LABEL` before including `GOAT_Inputs_Definitions.mqh`.
- `GOAT_Inputs_Definitions.mqh` must carry the newest default `GOAT_VERSION_LABEL` used by the current release.
- Track and preserve all GOAT `.mq5`, `.mqh`, `.ex5`, `.ico`, and `.png` files used by the project.
- `AGENTS.md` is a tracked repo file, not a local-only scratch note.
- Do not commit logs, tester caches, reports, or other transient artifacts unless the user explicitly asks.
- Do not assume a compile succeeded just because MetaEditor was launched. Always verify the log, the error count, warning count, and output binary timestamp.
- Do not assume MT5 loaded the newest binary. Re-attach the EA when needed and verify via runtime evidence.
- Never propose, tune, or serialize a setting unless it makes sense in the EA's actual working logic. If a mode is disabled or a parameter is not materially used by the active branch, do not spend optimization budget on it.
- Never rely on "looks right" for optimization inputs, feature ideas, or risk logic. Trace the real code path, confirm the dependency chain, and remove contradictions before presenting work as ready.
- Do not modify GOAT-EA implementation without a plan. Propose the intended change first, explain the reasoning and expected impact, and only implement after explicit user agreement.

## Repo Truths

- This repo intentionally keeps multiple versioned main entrypoints side by side.
- Unless the user specifies otherwise, treat the highest versioned tracked `GOAT V*.mq5` file as the default current release target.
- Shared logic lives in `.mqh` files and can affect multiple versioned mains at once.
- `README.md` is the source of truth for release workflow details. If this guide disagrees with `README.md` or the actual repo state, follow `README.md` and the repo.
- The repo root may also contain local operational files such as `compile-codex.log`, `compile-codex-*.log`, `scripts/`, and `tools/`. Treat these as workspace aids unless the user explicitly asks to edit or version them.
- Version-specific examples in this guide are illustrative only. Prefer durable rules over hard-coded version numbers wherever possible.

## Working Style

- Start by reading the smallest relevant surface area.
- Search first, reason second, propose third, patch fourth, compile fifth, verify sixth.
- Keep diffs narrow. Avoid whole-file rewrites of large MQL files unless there is no safer option.
- Preserve file encoding and line endings. Current tracked source files are UTF-8 with BOM and CRLF; do not normalize them away.
- Avoid mass formatting and whitespace churn in large `.mq5` and `.mqh` files.
- Respect existing user changes in a dirty worktree. Do not revert unrelated edits.
- If a task touches optimization, tester orchestration, file export, or news/bias data, trace the full path before editing.
- If a task touches strategy logic, sequence sizing, risk controls, or signal filters, review it as capital-critical engineering rather than ordinary application code.
- Before implementation work on the EA, present the proposed change set clearly enough that the user can approve or redirect it.
- Treat planning as mandatory for EA modifications, not optional ceremony.

## Version Targeting

- Determine first whether the task is for the current release, an older release, or shared include logic.
- For current-release work, edit the highest versioned tracked `GOAT V*.mq5` unless the user names a different version.
- For shared `.mqh` work, assume every versioned main that includes that file may be affected until proven otherwise.
- Do not casually patch older versioned entrypoints just because they appear in older prompts, examples, or comments.
- Before release work, identify the current version, the target new version, and whether shared includes are intentionally changing with the release.

## Optimization File Discipline

- Craft GOAT optimization `.set` files with the highest degree of care. Assume a bad range, stray `Y`, wrong enum ladder, or mismatched mode can waste large amounts of tester time or produce false conclusions.
- Every optimized field must have a clear justification in the live EA logic. Confirm the controlling mode is active, the parameter is actually consumed by that branch, and the search range matches the intended behavior.
- Prefer fewer, meaningful optimization dimensions over broad noisy searches. Remove dead parameters, contradictory toggles, and inactive indicator settings before widening any search space.
- Treat `EA_Desc`, encoding, line endings, enum values, and start-step-stop geometry as correctness-sensitive parts of the optimization artifact, not clerical details.
- When reviewing or creating optimization suites, sanity-check not only file format but also whether the search space is coherent, efficient, and aligned with how GOAT actually trades.

## Recommendation Standard

- Apply the same rigor to recommendations as to code. Do not suggest features, parameter changes, or architectural ideas unless they are grounded in the EA's present design, known constraints, and likely trading impact.
- Be explicit about what is verified versus inferred. When certainty is not possible, state the uncertainty and avoid presenting the idea as production-ready.
- Favor robust, explainable improvements over clever but weakly validated ideas. In this repo, "powerful" means durable, logically consistent, and testable under real GOAT conditions.

## Repo Layout

At the time of writing, the tracked core files live at repo root:

- Versioned entrypoints: `GOAT V*.mq5`
- Matching binaries: `GOAT V*.ex5`
- Shared includes: `GOAT_Inputs_Definitions.mqh`, `Optimizer.mqh`, `Dashboard.mqh`, `NewsBiasFilter.mqh`, `Tester.mqh`, `MTTester.mqh`, `XmlProcessor.mqh`
- Docs and assets: `README.md`, `AGENTS.md`, `GOAT.ico`, `GOAT Gradient Logo.png`

Before committing, confirm the tracked file set with:

```powershell
git ls-files
```

## Where To Look First

Use search instead of scrolling.

- Current entrypoint: the newest tracked `GOAT V*.mq5` unless the user names a different version.
- Version metadata: search `GOAT_VERSION_LABEL` and `#property version` in the versioned mains and `GOAT_Inputs_Definitions.mqh`.
- Main lifecycle: search `OnInit`, `OnTick`, `OnDeinit` in the active versioned main.
- Include graph: search `^#include` across `.mq5` and `.mqh`.
- Inputs and enum changes: start in `GOAT_Inputs_Definitions.mqh`, then search for every usage before renaming anything.
- Optimization/export issues: search `EA_Desc`, `RunAndStoreSet`, `Mode_Opti`, `Optimization`, `TesterInputs`.
- Dashboard/UI issues: search `CGOATDashboard`, `Create`, `UpdateRowMetrics`, `UpdatePortfolioRow`.
- News/bias issues: search `GOATNewsFilter`, `Mode_News`, `Mode_Bias`, `NEWS_FILE`, `BIAS_FILE`.
- Tester automation issues: search `InitializeTester`, `StartTester`, `VerifyTesterSettings`, `SetSettings`.

## Preferred Tools

Prefer the installed fast tools over slower shell defaults:

- `rg`: text search
- `fd`: filename search
- `fzf`: fuzzy picking
- `bat`: readable file preview
- `delta`: readable diff rendering
- `uv`: Python tool runner when repo utilities are added later
- `WinMerge`: visual side-by-side file or folder diff when a GUI compare is useful

## Repo Helpers

If the PowerShell profile has loaded, these repo helpers are available:

```powershell
ghelp
groot
gfd <pattern>
grg <pattern>
glogs [count]
glog [name]
gtail [name]
gdf [git diff args...]
gst
grecent [count]
gpick
goat-open-diff
```

Use them whenever they save time. They are the fastest way to stay oriented in this repo.

## Raw Command Cookbook

Use these when helper aliases are unavailable or when a more exact command is needed.

### Find files and current version

```powershell
fd -HI -g "GOAT V*.mq5" .
fd -HI -g "GOAT V*.ex5" .
Get-ChildItem "GOAT V*.mq5" | Sort-Object { [version](($_.BaseName -replace '^GOAT V','')) } | Select-Object Name
rg -n "^#define\\s+GOAT_VERSION_LABEL|^#property version" --glob "GOAT V*.mq5" --glob "GOAT_Inputs_Definitions.mqh" .
```

### Search code

```powershell
rg -n --glob "*.mq5" --glob "*.mqh" "OnInit|OnTick|OnDeinit" .
rg -n --glob "*.mq5" --glob "*.mqh" "^#include|^#property" .
rg -n --glob "*.mq5" --glob "*.mqh" "EA_Desc|Mode_Opti|RunAndStoreSet|Optimization" .
rg -n --glob "*.mq5" --glob "*.mqh" "GOATNewsFilter|Mode_News|Mode_Bias|NEWS_FILE|BIAS_FILE" .
rg -n --glob "*.mq5" --glob "*.mqh" "CGOATDashboard|UpdateRowMetrics|UpdatePortfolioRow" .
rg -n --glob "*.mq5" --glob "*.mqh" "input\\s+|sinput\\s+|enum " GOAT_Inputs_Definitions.mqh
```

### Preview files

```powershell
$latest = Get-ChildItem "GOAT V*.mq5" | Sort-Object { [version](($_.BaseName -replace '^GOAT V','')) } | Select-Object -Last 1
bat --style=numbers --paging=never $latest.FullName
bat --style=numbers --paging=never "Optimizer.mqh"
bat --style=numbers --paging=never "compile-codex.log"
```

### Fuzzy navigation

```powershell
fd -HI -e mq5 -e mqh . | fzf
fd -HI -e mq5 -e mqh . | fzf --preview "bat --style=numbers --color=always {}"
```

### Git and diffs

```powershell
$latest = Get-ChildItem "GOAT V*.mq5" | Sort-Object { [version](($_.BaseName -replace '^GOAT V','')) } | Select-Object -Last 1
git status --short
git diff --stat
git diff -- $latest.Name
git diff -- "GOAT_Inputs_Definitions.mqh"
git log --oneline --decorate -n 15
```

If repo-local delta paging is active, plain `git diff` is already improved. If not:

```powershell
git -c core.pager=delta diff -- "GOAT_Inputs_Definitions.mqh"
```

### Logs and recent work

```powershell
fd -HI -e log .
Get-ChildItem -File "compile-codex*.log" | Sort-Object LastWriteTime -Descending | Select-Object FullName,LastWriteTime,Length
Get-Content ".\compile-codex.log" -Tail 80
```

### Diff against backup or historical copy

Use WinMerge when the user wants a visual compare. Use git or a repo-local diff script when the user wants a patch. If the `goat-folder-diff` skill is available and the required local script exists, prefer that workflow instead of rebuilding it ad hoc.

## MQL5-Specific Editing Rules

- When changing an input name, enum, version label, or serialization field, search for every read-write site before editing.
- If an input participates in `.set` generation or tester settings replacement, update all linked code paths together.
- Keep `EA_Desc` handling stable. It is part of tester, export, and strategy selection flows.
- Keep `GOAT_VERSION_LABEL` stable per entrypoint. Do not change an older versioned main's label unless the user explicitly wants that historical entrypoint modified.
- Be extremely cautious around global arrays, order management, sequence sizing, and anything that changes lot progression or safety limits.
- Avoid introducing hidden behavior changes inside helper modules without tracing the call sites from the active versioned main.
- When touching UI code in `Dashboard.mqh`, verify layout changes do not break chart controls or row updates.
- When touching news or bias logic, verify both live and backtest paths conceptually. This code can branch differently by mode.

## Compile And Verification Discipline

When a change affects runtime behavior, compile before claiming success.

Minimum compile checklist:

1. Build the relevant `.mq5`.
2. Confirm the compile log exists and ends with a result line.
3. Prefer `Result: 0 errors, 0 warnings`. If warnings remain, identify whether they are new or pre-existing before treating the build as clean.
4. Confirm the expected repo-root `.ex5` exists in the intended location.
5. Confirm the target `.ex5` timestamp changed.
6. If shared `.mqh` files changed, compile every versioned main that is supposed to remain working, or at minimum the target release plus the adjacent release during a version cut.

If MetaTrader still appears stale after compile:

- Remove the EA from the chart and attach it again.
- Check the `Experts` tab for the latest initialization logs.
- Print or inspect `MQL_PROGRAM_PATH` when proving which binary MT5 loaded.
- Remember there may be duplicate `.ex5` files in root, subfolders, profiles, or backups.
- If `compile-codex.log` is absent, search `compile-codex*.log` instead of assuming one fixed log path.

If the `mt5-goat-compile` skill is available, use it for MT5 compile and stale-binary troubleshooting. Before following any skill path literally, verify the source and output paths match the current repo layout.

## Optimization And Diff Skills

When the task clearly matches them, prefer the local skills:

- `mt5-goat-compile`: compile, verify `.ex5`, and troubleshoot stale MT5 loads.
- `mt5-goat-optimize`: launch and review optimization runs safely.
- `goat-folder-diff`: generate a stable local diff report against the sibling backup folder.

Use the skill workflow, but reconcile it with the actual files present in this workspace before running commands.

## Git Rules For This Repo

- Keep all historical versioned `.mq5` files side by side.
- Commit the matching `.ex5` for any released or actively used version.
- Commit new or changed `.mqh`, `.ico`, and `.png` files that belong to the EA.
- Commit `AGENTS.md` when it changes meaningfully because it is part of the repo operating contract.
- Do not commit `.log`, tester cache, reports, or scratch outputs unless explicitly requested.
- Before any commit, review `git status --short` and make sure no required binary or asset was forgotten.
- When cutting a new release in Codex, use a version-named branch such as `codex/GOAT-V1.38`.

## New Version Workflow

When creating a new EA version:

1. Create a dedicated release branch for the target version before merging to `main`.
2. Copy the current modified main entrypoint into the new versioned `.mq5` file.
3. Restore the previous versioned main file back to its tracked baseline content after the copy is made.
4. Set the new entrypoint's `GOAT_VERSION_LABEL` before including `GOAT_Inputs_Definitions.mqh`.
5. Update `GOAT_Inputs_Definitions.mqh` so its default `GOAT_VERSION_LABEL` matches the newest release.
6. Leave shared `.mqh` improvements in place only when they intentionally belong to the new release.
7. Compile and verify the new release, and compile the previous entrypoint too when shared includes changed.
8. Commit the new `.mq5`, new `.ex5`, and any changed shared includes or assets together.

## Session Checklist

At the start of a coding task:

```powershell
git status --short
git ls-files
Get-ChildItem "GOAT V*.mq5" | Sort-Object { [version](($_.BaseName -replace '^GOAT V','')) } | Select-Object Name
rg -n "^#include" --glob "GOAT V*.mq5" .
```

Before editing:

- Identify the narrowest set of files to touch.
- Confirm whether the task is version-specific or shared-module-wide.
- Confirm which versioned entrypoint is the target.
- Check for duplicate or local-only artifacts that could confuse compile verification.
- If the task changes EA behavior, draft the proposed implementation first and wait for explicit user approval before editing code.

Before finishing:

- Re-read the diff.
- Compile if behavior changed.
- Verify the target `.ex5` and compile log.
- Summarize any assumptions that were not directly verified.

## What Good Looks Like

A strong GOAT-EA session leaves the repo more reliable, not just more changed:

- the right file was edited
- the target version was chosen intentionally
- the implementation was proposed and agreed before code changed
- the diff is tight and explainable
- compile status is proven
- version history is preserved
- no source, binary, or asset needed for reproducibility was dropped
