"""Controller mutation CI: shards, the three required aggregate checks, PR-scoped selection, full run.

Reads the workflows as text (CI has no YAML library) and exercises scripts/ci_mutation_select.py on
the real repository and on a small fixture repository. It never runs the mutation suite.
(GOAT-EA#204; Claude-Mac, goatai#2350 6089452823 + 6089458580.)
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / '.github' / 'workflows'
PR_WORKFLOW = WORKFLOWS / 'controller-tests.yml'
SHARD_WORKFLOW = WORKFLOWS / 'controller-mutation-shard.yml'
FULL_WORKFLOW = WORKFLOWS / 'controller-mutations-full.yml'

_spec = importlib.util.spec_from_file_location('ci_mutation_select', ROOT / 'scripts' / 'ci_mutation_select.py')
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)

# Every mutation step the controller-mutations job ran with 3 shards (the full set). A new mutation
# step is added here, to one shard of controller-mutation-shard.yml and to STEP_SEEDS.
EXPECTED = frozenset({
    'test_bias_reader_parity_mutations',
    'test_research_outcome_mutations',
    'test_research_outcome_controller_mutations',
    'test_studio_steady_panel_mutations',
    'test_ea_followups_mutations',
    'test_evidence_end_export_controller_mutations',
    'test_terminal_isolation_mutations',
    'test_terminal_isolation_controller_mutations',
    'test_catchup_rebase_controller_mutations',
    'test_lane_final_write_mutations',
    'test_switch_hold_mutations',
    'test_process_query_mutations',
    'test_lane_driver_mutations',
    'test_research_launch_mutations',
    'test_oos_windows_controller_mutations',
    'test_restore_lane_never_started_mutations',
    'test_holdup_mutations',
    'test_peer_restart_mutations',
    'test_peer_roster_mutations',
    'test_seed_member_failure_mutations',
    'test_export_qualification_mutations',
    'test_driver_backoff_mutations',
    'test_setup_registration_mutations',
    'test_profile_staged_adoption_mutations',
    'test_profile_staged_deploy_mutations',
})

# The 3-shard layout this replaced (base da9e953), kept for comparison.
THREE_SHARD_LAYOUT = {
    1: ['test_bias_reader_parity_mutations', 'test_research_outcome_mutations',
        'test_research_outcome_controller_mutations', 'test_studio_steady_panel_mutations',
        'test_ea_followups_mutations', 'test_evidence_end_export_controller_mutations',
        'test_terminal_isolation_mutations', 'test_terminal_isolation_controller_mutations',
        'test_catchup_rebase_controller_mutations', 'test_lane_final_write_mutations',
        'test_switch_hold_mutations'],
    2: ['test_process_query_mutations', 'test_lane_driver_mutations', 'test_research_launch_mutations',
        'test_oos_windows_controller_mutations'],
    3: ['test_restore_lane_never_started_mutations', 'test_holdup_mutations', 'test_peer_restart_mutations',
        'test_peer_roster_mutations', 'test_seed_member_failure_mutations', 'test_export_qualification_mutations',
        'test_driver_backoff_mutations', 'test_setup_registration_mutations',
        'test_profile_staged_adoption_mutations', 'test_profile_staged_deploy_mutations'],
}

def quiet(argv):
    """sel.main(argv) with its printout captured: (exit code, text)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = sel.main(argv)
    return code, buffer.getvalue()


REQUIRED = ('controller-mutations (1/3)', 'controller-mutations (2/3)', 'controller-mutations (3/3)')


def jobs(text):
    """{job id: {'name', 'needs': [...], 'if', 'uses', 'with': {...}, 'body'}} from a workflow."""
    lines = text.splitlines()
    start = lines.index('jobs:')
    result, current = {}, None
    for line in lines[start + 1:]:
        m = re.fullmatch(r'  ([A-Za-z0-9_-]+):', line)
        if m:
            current = result.setdefault(m[1], {'needs': [], 'with': {}, 'body': []})
            continue
        if current is None:
            continue
        current['body'].append(line)
        m = re.fullmatch(r'    (name|if|uses|runs-on): (.*)', line)
        if m:
            current[m[1]] = m[2]
        m = re.fullmatch(r'    needs: (.*)', line)
        if m:
            value = m[1].strip()
            current['needs'] = [v.strip() for v in value.strip('[]').split(',')] if value.startswith('[') else [value]
        m = re.fullmatch(r'      (shard|steps|ref): (.*)', line)
        if m and current.get('uses'):
            current['with'][m[1]] = m[2]
    for job in result.values():
        job['body'] = '\n'.join(job['body'])
    return result


def coverage_problems(selection, expected):
    """Every expected step in exactly one shard, nothing extra, and no empty shard."""
    problems = []
    seen = {}
    for shard, runs in sorted(selection.items()):
        if not runs:
            problems.append(f'shard {shard} runs no mutation step')
        for run in runs:
            seen.setdefault(run, []).append(shard)
    for run, shards in sorted(seen.items()):
        if len(shards) > 1:
            problems.append(f'{run} runs in shards {shards}')
    for run in sorted(expected - set(seen)):
        problems.append(f'{run} runs in no shard')
    for run in sorted(set(seen) - expected):
        problems.append(f'{run} is not in the expected set')
    return problems


class ShardTableTests(unittest.TestCase):
    def setUp(self):
        self.text = SHARD_WORKFLOW.read_text(encoding='utf-8')
        self.shards = sel.parse_shard_workflow(self.text)

    def test_four_shards_cover_every_step_once_with_the_unchanged_45_minute_timeout(self):
        self.assertEqual(sorted(self.shards), [1, 2, 3, 4])
        self.assertEqual(coverage_problems(self.shards, EXPECTED), [])
        self.assertIn('    timeout-minutes: 45\n', self.text)
        self.assertEqual(coverage_problems(THREE_SHARD_LAYOUT, EXPECTED), [])

    def test_every_step_runs_its_own_script(self):
        for step in EXPECTED:
            self.assertEqual(len(re.findall(rf'run: (?:node|python) scripts/{step}\.(?:cjs|py)\n', self.text)), 1, step)

    def test_checker_catches_a_duplicated_or_unconditioned_step(self):
        step = 'test_holdup_mutations'
        duplicated = self.text.replace(
            '        run: python scripts/test_switch_hold_mutations.py\n',
            '        run: python scripts/test_switch_hold_mutations.py\n'
            '      - name: duplicate\n'
            f"        if: inputs.shard == 2 && (inputs.steps == 'all' || contains(inputs.steps, '|{step}|'))\n"
            f'        run: python scripts/{step}.py\n')
        with self.assertRaises(ValueError):
            sel.parse_shard_workflow(duplicated)
        unconditioned = re.sub(r"        if: inputs\.shard == 3 && [^\n]*\n(        run: python scripts/test_holdup)", r'\1',
                               self.text)
        self.assertNotEqual(unconditioned, self.text)
        with self.assertRaises(ValueError):
            sel.parse_shard_workflow(unconditioned)
        wrong_id = self.text.replace("contains(inputs.steps, '|test_holdup_mutations|')",
                                     "contains(inputs.steps, '|test_peer_restart_mutations|')")
        with self.assertRaises(ValueError):
            sel.parse_shard_workflow(wrong_id)
        dropped = re.sub(r'      - name: [^\n]*\n        if: [^\n]*\n        run: python scripts/test_holdup_mutations\.py\n',
                         '', self.text)
        self.assertIn('test_holdup_mutations runs in no shard',
                      coverage_problems(sel.parse_shard_workflow(dropped), EXPECTED))

    def test_shard_log_lists_run_and_skip(self):
        self.assertIn('python scripts/ci_mutation_select.py explain --shard', self.text)


class RequiredCheckTests(unittest.TestCase):
    def setUp(self):
        self.text = PR_WORKFLOW.read_text(encoding='utf-8')
        self.jobs = jobs(self.text)
        self.shards = sel.parse_shard_workflow(SHARD_WORKFLOW.read_text(encoding='utf-8'))

    def shard_jobs(self):
        """{job id: shard number} for the jobs that call the shard workflow."""
        return {job_id: int(job['with']['shard']) for job_id, job in self.jobs.items()
                if job.get('uses') == './.github/workflows/controller-mutation-shard.yml'}

    def test_the_three_required_names_aggregate_disjoint_shards_covering_every_step(self):
        names = {job['name']: job_id for job_id, job in self.jobs.items() if 'name' in job}
        for required in REQUIRED:
            self.assertIn(required, names)
        shard_jobs = self.shard_jobs()
        self.assertEqual(sorted(shard_jobs.values()), [1, 2, 3, 4])
        covered = []
        for required in REQUIRED:
            job = self.jobs[names[required]]
            self.assertEqual(job['if'], 'always()', required)
            self.assertIn('mutation-selection', job['needs'], required)
            mine = [shard_jobs[need] for need in job['needs'] if need in shard_jobs]
            self.assertTrue(mine, required)
            # The verdict sees exactly the shards this check needs, each with its own planned flag.
            specs = re.findall(r'SHARD_(\d): (\d):\$\{\{ needs\.mutation-selection\.outputs\.run_(\d) \}\}:'
                               r'\$\{\{ needs\.([\w-]+)\.result \}\}', job['body'])
            self.assertEqual(sorted(int(a) for a, _, _, _ in specs), sorted(mine), required)
            for a, b, c, need in specs:
                self.assertTrue(a == b == c, required)
                self.assertEqual(shard_jobs[need], int(a), required)
            self.assertIn('ci_mutation_select.py verdict --selection "$SELECTION"', job['body'])
            self.assertEqual(len(re.findall(r'--shard "\$SHARD_\d"', job['body'])), len(mine), required)
            covered.extend(mine)
        self.assertEqual(sorted(covered), [1, 2, 3, 4], 'disjoint, and every shard is aggregated')
        steps = [step for shard in covered for step in self.shards[shard]]
        self.assertEqual(len(steps), len(set(steps)))
        self.assertEqual(set(steps), EXPECTED)

    def test_no_single_aggregate_and_no_name_collisions(self):
        self.assertNotIn('controller-mutations-all', self.jobs)
        names = [job.get('name') for job in self.jobs.values()]
        self.assertNotIn('controller-mutations', names)
        self.assertEqual(len(names), len(set(names)))
        for job_id in self.shard_jobs():
            self.assertNotIn(self.jobs[job_id]['name'], REQUIRED)
            self.assertFalse(self.jobs[job_id]['name'].startswith('controller-mutations'), job_id)
        self.assertEqual(self.jobs['controller'].get('name', 'controller'), 'controller')

    def test_shards_run_only_when_selected_and_take_the_selected_steps(self):
        for job_id, shard in self.shard_jobs().items():
            job = self.jobs[job_id]
            self.assertEqual(job['needs'], ['mutation-selection'])
            self.assertEqual(job['if'], f"needs.mutation-selection.outputs.run_{shard} == 'true'")
            self.assertEqual(job['with']['steps'], f'${{{{ needs.mutation-selection.outputs.steps_{shard} }}}}')
        selection = self.jobs['mutation-selection']
        self.assertIn('fetch-depth: 0', selection['body'])
        self.assertIn('ci_mutation_select.py select --event "$EVENT" --base "$BASE_SHA" --head "$HEAD_SHA"',
                      selection['body'])
        for shard in range(1, 5):
            self.assertIn(f'run_{shard}: ${{{{ steps.select.outputs.run_{shard} }}}}', selection['body'])
            self.assertIn(f'steps_{shard}: ${{{{ steps.select.outputs.steps_{shard} }}}}', selection['body'])

    def test_verdict(self):
        ok = sel.verdict
        self.assertEqual(ok('success', [('1', 'true', 'success'), ('2', 'false', 'skipped')]), [])
        self.assertEqual(ok('success', [('3', 'false', 'skipped')]), [])
        self.assertTrue(ok('success', [('1', 'true', 'skipped')]))        # selected but never ran
        self.assertTrue(ok('success', [('1', 'true', 'failure')]))
        self.assertTrue(ok('success', [('1', 'true', 'cancelled')]))
        self.assertTrue(ok('failure', [('1', '', 'skipped')]))           # selection failed: never green
        self.assertTrue(ok('cancelled', [('1', 'false', 'skipped')]))
        self.assertTrue(ok('success', [('1', '', 'skipped')]))           # no output: not a deliberate skip
        self.assertTrue(ok('success', [('1', 'false', 'failure')]))
        self.assertEqual(quiet(['verdict', '--selection', 'success', '--shard', '1:true:success',
                                   '--shard', '2:false:skipped'])[0], 0)
        self.assertEqual(quiet(['verdict', '--selection', 'success', '--shard', '1:true:skipped'])[0], 1)


class RealRepositorySelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shards = sel.parse_shard_workflow(SHARD_WORKFLOW.read_text(encoding='utf-8'))
        cls.index = sel.repo_index(ROOT)
        cls.cache = {}
        cls.deps = sel.step_dependencies(ROOT, index=cls.index, cache=cls.cache)
        fanin = sel.controller_fanin(ROOT, *cls.index, cache=cls.cache)
        cls.hubs = {m: n for m, n in fanin.items() if n >= sel.HUB_FANIN}

    def plan(self, changed, deleted=()):
        return sel.plan(changed, self.shards, self.deps, self.hubs, deleted)

    def test_every_step_has_a_seed_map_whose_files_exist_and_cover_what_its_script_names(self):
        self.assertEqual(set(sel.STEP_SEEDS), EXPECTED)
        self.assertEqual(set(self.deps), EXPECTED)
        files, by_name = self.index
        for step, seeds in sel.STEP_SEEDS.items():
            self.assertTrue(seeds[0].startswith(f'scripts/{step}.'), step)
            for path in seeds:
                self.assertIn(path, files, (step, path))
            named = sel.direct_dependencies(ROOT, seeds[0], files, by_name)
            production = {p for p in named if sel.is_production_module(p) or ('/' not in p and p.endswith(('.mqh', '.mq5')))}
            self.assertEqual(sorted(production - set(seeds)), [], f'{step}: named by its script but not seeded')

    def test_an_unmapped_file_selects_the_full_suite(self):
        for path in ('controller/new_unreferenced_module.py', 'controller/NEW-UNREFERENCED-GUIDE.md', 'tests/anything.ps1',
                     'candidate-builds/x.zip'):
            result = self.plan([path])
            self.assertTrue(result['full'], path)
            self.assertIn(f'unmapped file changed: {path}', result['reasons'])
            self.assertEqual(result['steps'], [s for steps in self.shards.values() for s in steps])
        # One unmapped file makes the whole PR full, whatever else it maps.
        self.assertTrue(self.plan(['controller/studio_switch_hold.py', 'controller/brand_new.json'])['full'])

    def test_a_core_file_selects_the_full_suite(self):
        core = ['.github/workflows/controller-tests.yml', '.github/workflows/controller-mutation-shard.yml',
                '.github/workflows/controller-mutations-full.yml', 'scripts/ci_mutation_select.py',
                'controller/test_ci_mutation_shards.py', 'controller/ci-requirements.txt',
                'controller/goat_studio.py', 'controller/demo_agent.py', 'controller/campaign_ledger.py']
        for path in core + list(sel.CORE_MODULES):
            result = self.plan([path])
            self.assertTrue(result['full'], path)
            self.assertTrue(any(path in reason for reason in result['reasons']), path)
        for path in sel.CORE_MODULES:
            self.assertIn(path, self.index[0])
        # A module that many controller files import is shared even when CORE_MODULES misses it.
        result = sel.plan(['controller/studio_switch_hold.py'], self.shards, self.deps,
                          {'controller/studio_switch_hold.py': 99})
        self.assertTrue(result['full'])
        self.assertIn('shared controller module', result['reasons'][0])

    def test_a_deleted_file_selects_the_full_suite(self):
        result = self.plan(['controller/studio_switch_hold.py'], deleted=['controller/studio_switch_hold.py'])
        self.assertTrue(result['full'])

    def test_a_single_mapped_module_selects_only_its_steps_and_dependents(self):
        result = self.plan(['controller/studio_switch_hold.py'])
        self.assertFalse(result['full'], result['reasons'])
        steps = set(result['steps'])
        self.assertIn('test_switch_hold_mutations', steps)
        expected = {step for step, deps in self.deps.items() if 'controller/studio_switch_hold.py' in deps}
        self.assertEqual(steps, expected)
        self.assertLess(len(steps), len(EXPECTED))
        for step in ('test_bias_reader_parity_mutations', 'test_studio_steady_panel_mutations',
                     'test_profile_staged_adoption_mutations', 'test_holdup_mutations'):
            self.assertNotIn(step, steps)
        # An EA source maps too (wide: Python tests name the EA entry files, whose includes follow).
        result = self.plan(['GOATPortfolioSetupControl.mqh'])
        self.assertFalse(result['full'], result['reasons'])
        self.assertIn('test_profile_staged_adoption_mutations', result['steps'])
        self.assertLess(len(result['steps']), len(EXPECTED))

    def test_wildcard_discovery_is_a_dependency(self):
        # test_catchup_rebase_controller_mutations discovers pattern="test_studio_catchup_*.py".
        self.assertIn('controller/test_studio_catchup_verdict.py', self.deps['test_catchup_rebase_controller_mutations'])

    def test_outputs_per_shard(self):
        result = self.plan(['controller/studio_switch_hold.py'])
        out = sel.shard_outputs(result, self.shards)
        self.assertEqual(out['mode'], 'selected')
        self.assertEqual(out['run_1'], 'true')
        self.assertIn('|test_switch_hold_mutations|', out['steps_1'])
        self.assertNotIn('test_bias_reader_parity_mutations', out['steps_1'])
        for shard, steps in self.shards.items():
            chosen = [s for s in steps if s in result['steps']]
            self.assertEqual(out[f'run_{shard}'], 'true' if chosen else 'false')
            self.assertEqual(out[f'steps_{shard}'], '|' + '|'.join(chosen) + '|' if chosen else '')
        full = sel.shard_outputs(self.plan(['controller/goat_studio.py']), self.shards)
        self.assertEqual(full['mode'], 'full')
        for shard in self.shards:
            self.assertEqual((full[f'run_{shard}'], full[f'steps_{shard}']), ('true', 'all'))
        text = sel.render(result, self.shards)
        self.assertIn('SKIP test_bias_reader_parity_mutations', text)
        self.assertIn('RUN  test_switch_hold_mutations', text)

    def test_select_command_fails_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            for argv in (['--event', 'push'],
                         ['--event', 'pull_request'],
                         ['--event', 'pull_request', '--base', 'no-such-ref-1', '--head', 'no-such-ref-2']):
                out = Path(tmp) / 'out.txt'
                out.write_text('', encoding='utf-8')
                self.assertEqual(quiet(['select', *argv, '--github-output', str(out)])[0], 0)
                values = dict(line.split('=', 1) for line in out.read_text(encoding='utf-8').splitlines())
                self.assertEqual(values['mode'], 'full', argv)
                for shard in self.shards:
                    self.assertEqual((values[f'run_{shard}'], values[f'steps_{shard}']), ('true', 'all'), argv)

    def test_explain_lists_run_and_skip(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(sel.main(['explain', '--shard', '3', '--steps', '|test_holdup_mutations|']), 0)
        text = buffer.getvalue()
        self.assertIn('RUN  test_holdup_mutations', text)
        self.assertIn('SKIP test_peer_restart_mutations', text)


class FixtureRepositorySelectionTests(unittest.TestCase):
    """Dependents, test-only files and unmapped files on a small repository with known imports."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        files = {
            'controller/alpha.py': 'X = 1\n',
            'controller/beta.py': 'import alpha\nY = alpha.X\n',
            'controller/gamma.py': 'Z = 3\n',
            'controller/orphan.py': 'W = 4\n',
            'controller/test_alpha.py': 'import alpha\n',
            'controller/test_beta.py': 'import beta\nimport test_support_fixture\n',
            'controller/test_support_fixture.py': 'DATA = "fixture-data.json"\n',
            'controller/fixture-data.json': '{}\n',
            'controller/test_unused.py': 'import gamma\n',
            'scripts/test_alpha_mutations.py': 'TESTS = ["test_alpha"]\nTARGET = "alpha.py"\n',
            'scripts/test_beta_mutations.py': 'TESTS = ["test_beta"]\nTARGET = "beta.py"\n',
            'scripts/test_gamma_mutations.py': 'TARGET = "gamma.py"\n',
            'docs/notes.md': 'notes\n',
        }
        for rel, text in files.items():
            (self.tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / rel).write_text(text, encoding='utf-8')
        self.seeds = {
            'test_alpha_mutations': ('scripts/test_alpha_mutations.py', 'controller/test_alpha.py', 'controller/alpha.py'),
            'test_beta_mutations': ('scripts/test_beta_mutations.py', 'controller/test_beta.py', 'controller/beta.py'),
            'test_gamma_mutations': ('scripts/test_gamma_mutations.py', 'controller/gamma.py'),
        }
        self.shards = {1: ['test_alpha_mutations', 'test_beta_mutations'], 2: ['test_gamma_mutations']}
        self.deps = sel.step_dependencies(self.tmp, seeds=self.seeds)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, changed):
        return sel.plan(changed, self.shards, self.deps)

    def test_a_module_selects_its_steps_plus_dependents_only(self):
        result = self.plan(['controller/alpha.py'])
        self.assertFalse(result['full'])
        self.assertEqual(result['steps'], ['test_alpha_mutations', 'test_beta_mutations'])  # beta imports alpha
        out = sel.shard_outputs(result, self.shards)
        self.assertEqual((out['run_1'], out['run_2']), ('true', 'false'))
        self.assertEqual(out['steps_1'], '|test_alpha_mutations|test_beta_mutations|')
        self.assertEqual(self.plan(['controller/beta.py'])['steps'], ['test_beta_mutations'])
        self.assertEqual(self.plan(['controller/gamma.py'])['steps'], ['test_gamma_mutations'])

    def test_test_helpers_and_fixtures_are_followed(self):
        self.assertEqual(self.plan(['controller/test_support_fixture.py'])['steps'], ['test_beta_mutations'])
        self.assertEqual(self.plan(['controller/fixture-data.json'])['steps'], ['test_beta_mutations'])

    def test_test_only_files_select_nothing_and_unmapped_files_select_full(self):
        result = self.plan(['controller/test_unused.py', 'docs/notes.md'])
        self.assertFalse(result['full'])
        self.assertEqual(result['steps'], [])
        out = sel.shard_outputs(result, self.shards)
        self.assertEqual((out['run_1'], out['run_2'], out['steps_1']), ('false', 'false', ''))
        self.assertTrue(self.plan(['controller/orphan.py'])['full'])
        self.assertTrue(self.plan(['controller/alpha.py', 'controller/orphan.py'])['full'])
        self.assertTrue(self.plan(['somewhere/else.txt'])['full'])

    def test_a_step_without_a_map_selects_full(self):
        shards = {1: ['test_alpha_mutations', 'test_new_mutations']}
        self.assertTrue(sel.plan(['controller/alpha.py'], shards, self.deps)['full'])


class FullRunTests(unittest.TestCase):
    def setUp(self):
        self.text = FULL_WORKFLOW.read_text(encoding='utf-8')
        self.jobs = jobs(self.text)

    def test_full_run_triggers_on_the_base_branch_daily_and_by_hand(self):
        self.assertIn('on:\n  push:\n    branches: [codex/v148-research-planning]\n', self.text)
        self.assertRegex(self.text, r"\n  schedule:\n    - cron: '[0-9]+ [0-9]+ \* \* \*'\n")
        self.assertIn('\n  workflow_dispatch:\n', self.text)
        self.assertNotIn('pull_request', self.text.split('\njobs:\n')[0])
        self.assertIn('cancel-in-progress: false', self.text)
        self.assertIn("run-name: controller-mutations full ${{ github.event_name == 'push' && github.sha", self.text)

    def test_full_run_runs_every_step_of_every_shard_on_the_target_sha(self):
        shards = sel.parse_shard_workflow(SHARD_WORKFLOW.read_text(encoding='utf-8'))
        calls = {job_id: job for job_id, job in self.jobs.items()
                 if job.get('uses') == './.github/workflows/controller-mutation-shard.yml'}
        self.assertEqual(sorted(int(job['with']['shard']) for job in calls.values()), sorted(shards))
        for job in calls.values():
            self.assertEqual(job['with']['steps'], 'all')
            self.assertEqual(job['with']['ref'], '${{ needs.target.outputs.sha }}')
            self.assertEqual(job['needs'], ['target'])
            self.assertNotIn('if', job)
        steps = [step for shard in shards for step in shards[shard]]
        self.assertEqual(set(steps), EXPECTED)
        # 'all' runs every step: every step condition accepts inputs.steps == 'all'.
        full = sel.shard_outputs(sel.full_plan('nightly', shards), shards)
        self.assertTrue(all(full[f'steps_{s}'] == 'all' for s in shards))

    def test_record_is_named_by_sha_and_fails_unless_every_shard_passed(self):
        record = self.jobs['record']
        self.assertEqual(record['if'], 'always()')
        self.assertEqual(sorted(record['needs']), sorted(['target', 'shard-1', 'shard-2', 'shard-3', 'shard-4']))
        self.assertIn('name: controller-mutations-full-${{ needs.target.outputs.sha }}', record['body'])
        self.assertIn('path: controller-mutations-full.json', record['body'])
        self.assertIn('retention-days: 90', record['body'])
        ok = sel.full_run_record('a' * 40, '2026-10-09T20:00:00Z', 'success',
                                 {'1': 'success', '2': 'success', '3': 'success', '4': 'success'}, '7', '1', 'push')
        self.assertEqual((ok['sha'], ok['result'], ok['startedAt']), ('a' * 40, 'success', '2026-10-09T20:00:00Z'))
        self.assertEqual(sel.full_run_record('a' * 40, 't', 'success', {'1': 'success', '2': 'failure'})['result'],
                         'failure')
        self.assertEqual(sel.full_run_record('a' * 40, 't', 'success', {'1': 'success', '2': 'skipped'})['result'],
                         'failure')
        self.assertEqual(sel.full_run_record('a' * 40, 't', 'success', {'1': 'cancelled'})['result'], 'cancelled')
        self.assertEqual(sel.full_run_record('', 't', 'failure', {})['result'], 'failure')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'r.json'
            self.assertEqual(quiet(['record', '--out', str(out), '--sha', 'b' * 40, '--started-at', 't',
                                       '--target', 'success', '--shard', '1:success', '--shard', '2:success',
                                       '--shard', '3:success', '--shard', '4:failure'])[0], 1)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['result'], 'failure')


if __name__ == '__main__':
    unittest.main()
