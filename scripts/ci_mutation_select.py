"""Pick the controller mutation steps a pull request needs (goatai#2350, Claude-Mac 6089452823 / 6089458580).

The mutation steps live in .github/workflows/controller-mutation-shard.yml, one shard per job. On a
pull request this script diffs the PR against its merge base and selects only the steps whose files
the PR changes, plus every step that depends on a changed file. Anything it is unsure about runs the
FULL suite:

  * the event is not a pull request, or the diff cannot be computed;
  * a changed file is a core file (CI wiring, this selector, requirements, the shared controller
    modules in CORE_MODULES or any module HUB_FANIN or more controller files import);
  * the PR deletes a file (outside docs/);
  * a changed file is in no step's dependency set and is not a known test-only file (unmapped).

A step's dependency set is its seed files (STEP_SEEDS: the mutation script, the tests it runs and
the files it mutates) plus what they read: the controller/scripts modules a Python file imports,
the files a Node file requires, the .mqh files an EA file includes, and every repository file (or
wildcard test pattern) a test or mutation script names. Test helpers, harnesses, fixtures and EA
includes are followed transitively; a production controller module is a dependent one hop deep
(see is_production_module). The nightly/per-push full run is the backstop for anything deeper.

Subcommands (stdlib only; runs on the hosted Ubuntu runner and on Windows):
  select   compute the plan, print it, write GitHub step outputs
  explain  print which steps of one shard run and which are skipped
  verdict  decide a required aggregate check from the selection and shard job results
  record   write the per-commit JSON record of a full run; exit 1 unless it passed
"""
import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARD_WORKFLOW = '.github/workflows/controller-mutation-shard.yml'
FULL = 'all'

# Any change here runs the full suite: CI wiring, the selector and its map, pinned requirements and
# the controller modules most of the controller imports (a change there reaches nearly every step,
# and a wrong guess would be expensive).
CORE_PATTERNS = (
    '.github/*',
    'scripts/ci_mutation_select.py',
    'controller/test_ci_mutation_shards.py',
    'controller/ci-requirements.txt',
    '*requirements*.txt',
    '.gitattributes',
)
# Shared controller modules: the ones 20 or more controller files import directly (measured on
# 155ed01; goat_studio and demo_agent also import 74 and 42 modules). Any other module that reaches
# HUB_FANIN importers later is treated the same way at runtime.
CORE_MODULES = (
    'controller/campaign_ledger.py',            # imported by 112 controller files
    'controller/studio_installation.py',        # 88
    'controller/studio_bridge.py',              # 88
    'controller/studio_native_gate.py',         # 54
    'controller/studio_handover.py',            # 49
    'controller/studio_research_authority.py',  # 37
    'controller/goat_studio.py',                # 35
    'controller/studio_batch.py',               # 34
    'controller/demo_agent.py',                 # 33
    'controller/studio_strategy_settings.py',   # 27
    'controller/studio_terminal_isolation.py',  # 25
    'controller/studio_seed_slot.py',           # 23
    'controller/studio_seed_process.py',        # 22
    'controller/studio_process_check.py',       # 22
)

# Files a PR may change without touching any mutation step: unit tests and fixture scripts that no
# mutation step runs, imports or names (checked against the dependency sets at runtime, so a test
# a mutation step does use still selects that step), plus documentation outside controller/.
TEST_ONLY_PATTERNS = (
    'controller/test_*.py',
    'scripts/test_*.cjs',
    'scripts/test_*.py',
    'docs/*',
    'BACKLOG.md',
    'README.md',
)

# Seed files per mutation step (step id = the script's stem). Each entry names the mutation script,
# the test modules or harness it runs and the production files it mutates; imports, requires,
# includes and file names are followed from these at runtime. test_ci_mutation_shards.py checks
# every step of the shard workflow has an entry and every file a mutation script names is covered.
STEP_SEEDS = {
    'test_bias_reader_parity_mutations': (
        'scripts/test_bias_reader_parity_mutations.cjs', 'scripts/test_bias_reader_parity.cjs',
        'NewsBiasFilter.mqh', 'GOATAIWireV2.mqh', 'GOATStudioUI.mqh', 'GOAT_Inputs_Definitions.mqh',
        'GOAT V1.47.mq5', 'GOAT V1.48.mq5', 'GOAT V1.49.mq5'),
    'test_research_outcome_mutations': (
        'scripts/test_research_outcome_mutations.cjs', 'scripts/test_research_outcome.cjs',
        'Optimizer.mqh', 'XmlProcessor.mqh', 'GOATEADeviceActivation.mqh', 'GOAT V1.49.mq5'),
    'test_research_outcome_controller_mutations': (
        'scripts/test_research_outcome_controller_mutations.py', 'controller/test_studio_research_outcome.py',
        'controller/studio_batch.py', 'controller/studio_batch_pause.py', 'controller/studio_finish.py',
        'controller/studio_research_status.py'),
    'test_studio_steady_panel_mutations': (
        'scripts/test_studio_steady_panel_mutations.cjs', 'scripts/test_studio_steady_panel.cjs',
        'GOATStudioUI.mqh', 'Optimizer.mqh'),
    'test_ea_followups_mutations': (
        'scripts/test_ea_followups_mutations.cjs', 'scripts/test_ea_followups.cjs',
        'GOATEvidenceEnd.mqh', 'GOATStudioDispatch.mqh', 'GOATStudioUI.mqh', 'GOATTesterStopConfirm.mqh',
        'Optimizer.mqh', 'GOAT V1.47.mq5', 'GOAT V1.48.mq5', 'GOAT V1.49.mq5'),
    'test_evidence_end_export_controller_mutations': (
        'scripts/test_evidence_end_export_controller_mutations.py',
        'controller/test_studio_evidence_end_export.py', 'controller/studio_evidence_end_export.py',
        'controller/studio_batch.py', 'controller/activate_research_campaign.py',
        'controller/prepare_native_campaign.py'),
    'test_terminal_isolation_mutations': (
        'scripts/test_terminal_isolation_mutations.cjs', 'scripts/test_terminal_isolation.cjs',
        'GOATEADeviceActivation.mqh', 'GOATStudioSettingCompare.mqh', 'GOAT_Inputs_Definitions.mqh',
        'GOAT V1.49.mq5'),
    'test_terminal_isolation_controller_mutations': (
        'scripts/test_terminal_isolation_controller_mutations.py', 'controller/test_studio_terminal_isolation.py',
        'controller/studio_terminal_isolation.py'),
    'test_switch_hold_mutations': (
        'scripts/test_switch_hold_mutations.py', 'controller/studio_switch_hold.py', 'controller/studio_seed.py',
        'controller/demo_agent.py'),
    'test_process_query_mutations': (
        'scripts/test_process_query_mutations.py', 'controller/studio_process_query.py',
        'controller/studio_seed.py', 'controller/studio_seed_driver.py', 'controller/studio_seed_process.py',
        'controller/studio_catchup.py', 'controller/studio_durable_driver.py', 'controller/demo_agent.py',
        'controller/test_studio_process_query.py', 'controller/test_studio_seed.py',
        'controller/test_studio_seed_driver.py'),
    'test_lane_driver_mutations': (
        'scripts/test_lane_driver_mutations.py', 'controller/test_demo_lane_driver.py',
        'controller/studio_durable_driver.py', 'controller/demo_agent.py'),
    'test_research_launch_mutations': (
        'scripts/test_research_launch_mutations.py', 'controller/test_studio_research_launch.py',
        'controller/studio_research_launch.py', 'controller/studio_config_start.py',
        'controller/studio_seed.py', 'controller/studio_seed_process.py'),
    'test_restore_lane_never_started_mutations': (
        'scripts/test_restore_lane_never_started_mutations.py', 'controller/test_demo_settle_refused_start.py',
        'controller/test_demo_update_keeps_lane.py', 'controller/demo_agent.py',
        'controller/studio_self_repair.py'),
    'test_holdup_mutations': (
        'scripts/test_holdup_mutations.py', 'controller/test_studio_holdup.py',
        'controller/test_demo_holdup_agent.py', 'controller/test_studio_tester_report.py',
        'controller/studio_holdup.py', 'controller/studio_heldout_guard.py', 'controller/studio_tester_report.py',
        'controller/studio_trial_journal.py'),
    'test_peer_restart_mutations': (
        'scripts/test_peer_restart_mutations.py', 'controller/test_studio_peer_restart.py',
        'controller/studio_protected_peer.py', 'controller/studio_process_check.py'),
    'test_peer_roster_mutations': (
        'scripts/test_peer_roster_mutations.py', 'controller/test_studio_peer_roster.py',
        'controller/studio_peer_roster.py', 'controller/studio_process_check.py'),
    'test_seed_member_failure_mutations': (
        'scripts/test_seed_member_failure_mutations.py', 'controller/test_studio_seed.py',
        'controller/test_demo_seed_agent.py', 'controller/studio_seed.py', 'controller/demo_agent.py'),
    'test_export_qualification_mutations': (
        'scripts/test_export_qualification_mutations.py', 'controller/test_studio_export_qualification.py',
        'controller/studio_export_qualification.py', 'controller/studio_heldout_guard.py',
        'controller/studio_research_status.py', 'controller/demo_agent.py'),
    'test_driver_backoff_mutations': (
        'scripts/test_driver_backoff_mutations.py', 'controller/studio_batch_driver.py',
        'controller/studio_batch_stall.py', 'controller/studio_durable_driver.py',
        'controller/studio_research_status.py'),
    'test_catchup_rebase_controller_mutations': (
        'scripts/test_catchup_rebase_controller_mutations.py', 'controller/test_studio_catchup_rebase.py',
        'controller/test_studio_catchup_verdict.py', 'controller/studio_catchup.py',
        'controller/studio_catchup_rebase.py', 'controller/studio_catchup_verdict.py',
        'controller/studio_heldout_guard.py'),
    'test_lane_final_write_mutations': (
        'scripts/test_lane_final_write_mutations.py', 'controller/demo_agent.py',
        'controller/studio_agent_mailbox.py', 'controller/studio_bridge.py', 'controller/studio_installation.py',
        'controller/studio_native_gate.py', 'controller/studio_seed.py', 'controller/studio_seed_results.py'),
    'test_oos_windows_controller_mutations': (
        'scripts/test_oos_windows_controller_mutations.py', 'controller/test_studio_oos_windows.py',
        'controller/test_studio_window_metrics.py', 'controller/studio_oos_windows.py',
        'controller/studio_window_metrics.py', 'controller/studio_evidence_end.py',
        'controller/studio_evidence_end_export.py', 'controller/studio_export_scan.py',
        'controller/studio_heldout_guard.py', 'controller/studio_batch.py', 'controller/studio_catchup.py',
        'controller/studio_seed.py', 'controller/activate_research_campaign.py'),
    'test_setup_registration_mutations': (
        'scripts/test_setup_registration_mutations.py', 'controller/test_studio_setup_registration.py',
        'controller/studio_agent_setup.py', 'controller/studio_agent_mailbox.py', 'controller/studio_refusal.py',
        'controller/goat_studio.py'),
    'test_profile_staged_adoption_mutations': (
        'scripts/test_profile_staged_adoption_mutations.cjs', 'scripts/test_profile_staged_adoption.cjs',
        'GOATPortfolioSetupControl.mqh'),
    'test_profile_staged_deploy_mutations': (
        'scripts/test_profile_staged_deploy_mutations.py', 'controller/test_studio_deploy_profile.py',
        'controller/test_studio_profile_staged_deploy.py', 'controller/studio_deploy_profile.py',
        'controller/studio_demo_deploy.py', 'controller/studio_agent_mailbox.py'),
}

TEXT_SUFFIXES = {'.py', '.cjs', '.js', '.mjs', '.mq5', '.mqh', '.json', '.csv', '.md', '.txt', '.set', '.ini',
                 '.html', '.xml', '.yml', '.yaml', '.ps1'}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'candidate-builds'}


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def is_core(path):
    return matches(path, CORE_PATTERNS) or path in CORE_MODULES


# ---- step table ---------------------------------------------------------------------------------

def parse_shard_workflow(text):
    """{shard: [step id, ...]} from the shard workflow's `if: inputs.shard == N && ...` steps."""
    shards = {}
    pending_if = None
    for line in text.splitlines():
        m = re.fullmatch(r'      - (?:name|uses): .*', line)
        if m:
            pending_if = None
            continue
        m = re.fullmatch(r'        if: (.*)', line)
        if m:
            pending_if = m[1]
            continue
        m = re.fullmatch(r'        run: (node|python) scripts/(test_[\w]+_mutations)\.(cjs|py)', line)
        if not m:
            continue
        step = m[2]
        cond = re.fullmatch(r"inputs\.shard == (\d+) && \(inputs\.steps == 'all' \|\| contains\(inputs\.steps, '\|"
                            + re.escape(step) + r"\|'\)\)", pending_if or '')
        if not cond:
            raise ValueError(f'mutation step {step} has no exact shard/selection condition: {pending_if!r}')
        shards.setdefault(int(cond[1]), []).append(step)
        pending_if = None
    if not shards:
        raise ValueError('no mutation steps found in the shard workflow')
    seen = [step for steps in shards.values() for step in steps]
    if len(seen) != len(set(seen)):
        raise ValueError('a mutation step runs in more than one shard')
    return dict(sorted(shards.items()))


# ---- dependency sets ----------------------------------------------------------------------------

def repo_index(root):
    """Every repository file (posix relative paths), and a basename -> paths map."""
    files = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            files.add(rel)
    by_name = {}
    for rel in files:
        by_name.setdefault(rel.rsplit('/', 1)[-1], set()).add(rel)
    return files, by_name


def _read(root, rel):
    if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
        return ''
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return ''
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):  # MetaEditor can save UTF-16
        return data.decode('utf-16', errors='replace')
    return data.decode('utf-8', errors='replace')


def _python_imports(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split('.')[0])
    return names


def direct_dependencies(root, rel, files, by_name):
    """Repository files `rel` reads: imports, requires, includes, and (for tests) named files."""
    text = _read(root, rel)
    if not text:
        return set()
    deps = set()
    folder = rel.rsplit('/', 1)[0] if '/' in rel else ''
    base = rel.rsplit('/', 1)[-1]
    suffix = Path(rel).suffix.lower()
    if suffix == '.py':
        imports = _python_imports(text)
        if imports is None:
            raise ValueError(f'cannot parse {rel}')
        for name in imports:
            for candidate in (f'{folder}/{name}.py' if folder else f'{name}.py', f'controller/{name}.py',
                              f'scripts/{name}.py'):
                if candidate in files:
                    deps.add(candidate)
    elif suffix in ('.cjs', '.js', '.mjs'):
        for spec in re.findall(r"require\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)", text):
            target = os.path.normpath(os.path.join(folder, spec)).replace('\\', '/')
            for candidate in (target, target + '.cjs', target + '.js'):
                if candidate in files:
                    deps.add(candidate)
    elif suffix in ('.mq5', '.mqh'):
        for name in re.findall(r'#include\s*[<"]([^>"]+)[>"]', text):
            deps.update(by_name.get(name.replace('\\', '/').rsplit('/', 1)[-1], ()))
    if base.startswith('test_'):
        # Tests and mutation scripts read files by name (EA sources, fixtures, test modules), and
        # some discover tests by wildcard (pattern="test_studio_catchup_*.py").
        for name, paths in by_name.items():
            if name != base and name in text:
                deps.update(paths)
        for stem in set(re.findall(r'\btest_\w+', text)):
            for candidate in (f'controller/{stem}.py', f'scripts/{stem}.py', f'scripts/{stem}.cjs'):
                if candidate in files:
                    deps.add(candidate)
        for pattern in set(re.findall(r'[\w*?.-]*[*?][\w*?.-]*\.(?:py|cjs|js)\b', text)):
            for name, paths in by_name.items():
                if fnmatch.fnmatchcase(name, pattern):
                    deps.update(p for p in paths if p.startswith(('controller/', 'scripts/')))
    deps.discard(rel)
    return deps


def is_production_module(rel):
    """A controller module (not a test). Dependency sets stop one hop past these: the controller's
    import graph is one big cycle through goat_studio/demo_agent, so following it transitively
    would make every step depend on every module and the selection would always be FULL. Hubs
    (CORE_MODULES, and any module HUB_FANIN or more controller files import) run FULL instead."""
    return rel.startswith('controller/') and rel.endswith('.py') and '/' not in rel[len('controller/'):] \
        and not rel.rsplit('/', 1)[-1].startswith('test_')


HUB_FANIN = 20


def controller_fanin(root, files, by_name, cache=None):
    """{controller module: number of controller .py files that import it directly}."""
    cache = {} if cache is None else cache
    fanin = {}
    for rel in sorted(files):
        if rel.startswith('controller/') and rel.endswith('.py') and rel.count('/') == 1:
            if rel not in cache:
                cache[rel] = direct_dependencies(root, rel, files, by_name)
            for dep in cache[rel]:
                if is_production_module(dep):
                    fanin[dep] = fanin.get(dep, 0) + 1
    return fanin


def step_dependencies(root=REPO, seeds=None, index=None, cache=None):
    """{step: set of repository files the step's result depends on}.

    Seeds are always expanded; so is every non-production file reached (test helpers, fixtures,
    harnesses, EA includes). A production controller module reached through an import is a
    dependent and is included, but its own imports are not followed (see is_production_module)."""
    seeds = STEP_SEEDS if seeds is None else seeds
    files, by_name = index or repo_index(root)
    cache = {} if cache is None else cache
    result = {}
    for step, seed_files in seeds.items():
        missing = [path for path in seed_files if path not in files]
        if missing:
            raise ValueError(f'{step}: seed files not in the repository: {missing}')
        seen = set(seed_files)
        todo = list(seed_files)
        while todo:
            rel = todo.pop()
            if rel not in cache:
                cache[rel] = direct_dependencies(root, rel, files, by_name)
            for dep in cache[rel]:
                if dep not in seen:
                    seen.add(dep)
                    if not is_production_module(dep):
                        todo.append(dep)
        result[step] = seen
    return result


# ---- selection ----------------------------------------------------------------------------------

def plan(changed, shards, deps, hubs=None, deleted=()):
    """Decide which steps run: dict(full, reasons, steps, files).

    changed: changed paths; deps: step_dependencies(); hubs: {module: importer count} for modules
    at or above HUB_FANIN; deleted: the changed paths the PR deletes."""
    hubs = hubs or {}
    all_steps = [step for steps in shards.values() for step in steps]
    unknown = sorted(set(all_steps) - set(deps))
    if unknown:
        return dict(full=True, reasons=[f'steps without a dependency map: {unknown}'], steps=all_steps, files={})
    reasons, picked, per_file = [], set(), {}
    deleted = set(deleted)
    for path in sorted(set(changed)):
        if is_core(path):
            reasons.append(f'core file changed: {path}')
            continue
        if path in hubs:
            reasons.append(f'shared controller module changed: {path} (imported by {hubs[path]} controller files)')
            continue
        if path in deleted and not matches(path, ('docs/*',)):
            reasons.append(f'file deleted: {path}')
            continue
        hit = sorted(step for step in all_steps if path in deps[step])
        if hit:
            picked.update(hit)
            per_file[path] = hit
        elif matches(path, TEST_ONLY_PATTERNS):
            per_file[path] = []
        else:
            reasons.append(f'unmapped file changed: {path}')
    if reasons:
        return dict(full=True, reasons=reasons, steps=all_steps, files=per_file)
    return dict(full=False, reasons=[], steps=[step for step in all_steps if step in picked], files=per_file)


def full_plan(reason, shards):
    return dict(full=True, reasons=[reason], steps=[s for steps in shards.values() for s in steps], files={})


def shard_outputs(result, shards):
    """GitHub outputs: run_N ('true'/'false') and steps_N ('all' or '|a|b|') per shard."""
    out = {'mode': 'full' if result['full'] else 'selected'}
    for shard, steps in shards.items():
        chosen = [step for step in steps if step in result['steps']]
        out[f'run_{shard}'] = 'true' if chosen else 'false'
        out[f'steps_{shard}'] = FULL if result['full'] else ('|' + '|'.join(chosen) + '|' if chosen else '')
    return out


def render(result, shards):
    lines = ['Mutation selection: ' + ('FULL suite' if result['full'] else 'PR-scoped')]
    for reason in result['reasons']:
        lines.append(f'  reason: {reason}')
    for path, steps in sorted(result['files'].items()):
        lines.append(f'  changed {path} -> ' + (', '.join(steps) if steps else 'no mutation step (test-only)'))
    for shard, steps in shards.items():
        lines.append(f'shard {shard}/{len(shards)}:')
        for step in steps:
            lines.append(f"  {'RUN ' if step in result['steps'] else 'SKIP'} {step}")
    run = len(result['steps'])
    total = sum(len(steps) for steps in shards.values())
    lines.append(f'{run} of {total} mutation steps run, {total - run} skipped')
    return '\n'.join(lines)


def changed_files(base, head, cwd=REPO):
    """(merge base, changed paths, deleted paths) of head against its merge base with base."""
    def git(*args):
        return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True,
                              encoding='utf-8').stdout
    merge_base = git('merge-base', base, head).strip()
    fields = [field for field in git('diff', '--name-status', '--no-renames', '-z', merge_base, head).split('\0')]
    changed, deleted = [], []
    for status, path in zip(fields[0::2], fields[1::2]):
        if not status:
            break
        changed.append(path)
        if status.startswith('D'):
            deleted.append(path)
    return merge_base, changed, deleted


def compute_plan(changed, deleted, root=REPO, shards=None):
    shards = shards or parse_shard_workflow((root / SHARD_WORKFLOW).read_text(encoding='utf-8'))
    index = repo_index(root)
    cache = {}
    deps = step_dependencies(root, index=index, cache=cache)
    hubs = {m: n for m, n in controller_fanin(root, *index, cache=cache).items() if n >= HUB_FANIN}
    return plan(changed, shards, deps, hubs, deleted)


def write_outputs(path, outputs):
    with open(path, 'a', encoding='utf-8') as handle:
        for key, value in outputs.items():
            handle.write(f'{key}={value}\n')


def cmd_select(args):
    shards = parse_shard_workflow((REPO / SHARD_WORKFLOW).read_text(encoding='utf-8'))
    if args.event != 'pull_request':
        result = full_plan(f'event {args.event!r} always runs the full suite', shards)
    elif not args.base or not args.head:
        result = full_plan('no base/head sha to diff', shards)
    else:
        try:
            merge_base, changed, deleted = changed_files(args.base, args.head)
            print(f'diff {merge_base[:12]}..{args.head[:12]}: {len(changed)} changed files')
            result = compute_plan(changed, deleted, shards=shards) if changed else full_plan('empty diff', shards)
        except Exception as error:  # fail safe: any doubt runs everything
            result = full_plan(f'selection error ({type(error).__name__}: {error})', shards)
    print(render(result, shards))
    outputs = shard_outputs(result, shards)
    print(json.dumps(outputs, indent=1))
    if args.github_output:
        write_outputs(args.github_output, outputs)
    return 0


def cmd_explain(args):
    shards = parse_shard_workflow((REPO / SHARD_WORKFLOW).read_text(encoding='utf-8'))
    steps = shards.get(args.shard)
    if not steps:
        print(f'shard {args.shard} has no mutation steps')
        return 1
    selected = args.steps.strip()
    print(f"shard {args.shard}/{len(shards)}: {'FULL suite' if selected == FULL else 'PR-scoped selection'}")
    for step in steps:
        run = selected == FULL or f'|{step}|' in selected
        print(f"  {'RUN ' if run else 'SKIP'} {step}" + ('' if run else '  (not affected by this PR)'))
    return 0


def verdict(selection_result, shards):
    """Required-check verdict. shards = [(shard, planned 'true'/'false', job result), ...]."""
    problems = []
    if selection_result != 'success':
        problems.append(f'mutation selection job ended {selection_result!r}')
    for shard, planned, result in shards:
        if planned == 'true':
            if result != 'success':
                problems.append(f'shard {shard} was selected and ended {result!r}')
        elif planned == 'false' and selection_result == 'success':
            if result not in ('skipped', 'success'):
                problems.append(f'shard {shard} was deliberately skipped but ended {result!r}')
        elif selection_result == 'success':
            problems.append(f'shard {shard} has no selection output ({planned!r})')
    return problems


def cmd_verdict(args):
    shards = []
    for spec in args.shard:
        shard, planned, result = spec.split(':', 2)
        shards.append((shard, planned, result))
    for shard, planned, result in shards:
        state = 'selected' if planned == 'true' else 'deliberately skipped' if planned == 'false' else planned
        print(f'shard {shard}: {state}, job {result}')
    problems = verdict(args.selection, shards)
    for problem in problems:
        print(f'FAIL: {problem}')
    print('PASS' if not problems else 'FAILED')
    return 1 if problems else 0


def full_run_record(sha, started_at, target, shard_results, run_id='', run_attempt='', event=''):
    """The per-commit record of a full run: result is 'success' only when the target commit
    resolved and every shard of the full suite succeeded."""
    results = dict(shard_results)
    if not sha or target != 'success':
        result = 'failure'
    elif all(value == 'success' for value in results.values()) and results:
        result = 'success'
    elif any(value == 'cancelled' for value in results.values()):
        result = 'cancelled'
    else:
        result = 'failure'
    return dict(sha=sha, result=result, startedAt=started_at, shards=results, runId=run_id,
                runAttempt=run_attempt, event=event)


def cmd_record(args):
    shards = dict(spec.split(':', 1) for spec in args.shard)
    record = full_run_record(args.sha, args.started_at, args.target, shards, args.run_id, args.run_attempt,
                             args.event)
    Path(args.out).write_text(json.dumps(record, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=1))
    return 0 if record['result'] == 'success' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('select')
    p.add_argument('--event', default='pull_request')
    p.add_argument('--base', default='')
    p.add_argument('--head', default='')
    p.add_argument('--github-output', default='')
    p.set_defaults(func=cmd_select)
    p = sub.add_parser('explain')
    p.add_argument('--shard', type=int, required=True)
    p.add_argument('--steps', default=FULL)
    p.set_defaults(func=cmd_explain)
    p = sub.add_parser('verdict')
    p.add_argument('--selection', required=True)
    p.add_argument('--shard', action='append', default=[], help='N:planned:result')
    p.set_defaults(func=cmd_verdict)
    p = sub.add_parser('record')
    p.add_argument('--out', required=True)
    p.add_argument('--sha', default='')
    p.add_argument('--started-at', default='')
    p.add_argument('--target', required=True)
    p.add_argument('--shard', action='append', default=[], help='N:result')
    p.add_argument('--run-id', default='')
    p.add_argument('--run-attempt', default='')
    p.add_argument('--event', default='')
    p.set_defaults(func=cmd_record)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
