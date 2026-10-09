"""Every controller mutation check runs in exactly one CI shard.

Reads .github/workflows/controller-tests.yml as text (CI has no YAML library) and computes which
mutation steps each `controller-mutations` matrix shard runs. It never runs the mutation suite.
"""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parent.parent / '.github' / 'workflows' / 'controller-tests.yml'

# Every mutation step the controller-mutations job ran with 3 shards (the full set). A new mutation
# step is added here and to one shard of the workflow.
EXPECTED = frozenset({
    'node scripts/test_bias_reader_parity_mutations.cjs',
    'node scripts/test_research_outcome_mutations.cjs',
    'python scripts/test_research_outcome_controller_mutations.py',
    'node scripts/test_studio_steady_panel_mutations.cjs',
    'node scripts/test_ea_followups_mutations.cjs',
    'python scripts/test_evidence_end_export_controller_mutations.py',
    'node scripts/test_terminal_isolation_mutations.cjs',
    'python scripts/test_terminal_isolation_controller_mutations.py',
    'python scripts/test_catchup_rebase_controller_mutations.py',
    'python scripts/test_lane_final_write_mutations.py',
    'python scripts/test_switch_hold_mutations.py',
    'python scripts/test_process_query_mutations.py',
    'python scripts/test_lane_driver_mutations.py',
    'python scripts/test_research_launch_mutations.py',
    'python scripts/test_oos_windows_controller_mutations.py',
    'python scripts/test_restore_lane_never_started_mutations.py',
    'python scripts/test_holdup_mutations.py',
    'python scripts/test_peer_restart_mutations.py',
    'python scripts/test_peer_roster_mutations.py',
    'python scripts/test_seed_member_failure_mutations.py',
    'python scripts/test_export_qualification_mutations.py',
    'python scripts/test_driver_backoff_mutations.py',
    'python scripts/test_setup_registration_mutations.py',
    'node scripts/test_profile_staged_adoption_mutations.cjs',
    'python scripts/test_profile_staged_deploy_mutations.py',
})

# The 3-shard layout this replaced (base da9e953), kept for comparison.
THREE_SHARD_LAYOUT = {
    1: ['node scripts/test_bias_reader_parity_mutations.cjs',
        'node scripts/test_research_outcome_mutations.cjs',
        'python scripts/test_research_outcome_controller_mutations.py',
        'node scripts/test_studio_steady_panel_mutations.cjs',
        'node scripts/test_ea_followups_mutations.cjs',
        'python scripts/test_evidence_end_export_controller_mutations.py',
        'node scripts/test_terminal_isolation_mutations.cjs',
        'python scripts/test_terminal_isolation_controller_mutations.py',
        'python scripts/test_catchup_rebase_controller_mutations.py',
        'python scripts/test_lane_final_write_mutations.py',
        'python scripts/test_switch_hold_mutations.py'],
    2: ['python scripts/test_process_query_mutations.py',
        'python scripts/test_lane_driver_mutations.py',
        'python scripts/test_research_launch_mutations.py',
        'python scripts/test_oos_windows_controller_mutations.py'],
    3: ['python scripts/test_restore_lane_never_started_mutations.py',
        'python scripts/test_holdup_mutations.py',
        'python scripts/test_peer_restart_mutations.py',
        'python scripts/test_peer_roster_mutations.py',
        'python scripts/test_seed_member_failure_mutations.py',
        'python scripts/test_export_qualification_mutations.py',
        'python scripts/test_driver_backoff_mutations.py',
        'python scripts/test_setup_registration_mutations.py',
        'node scripts/test_profile_staged_adoption_mutations.cjs',
        'python scripts/test_profile_staged_deploy_mutations.py'],
}


def mutation_job(text):
    """The controller-mutations job block: its lines up to the next job or the end."""
    lines = text.splitlines()
    start = lines.index('  controller-mutations:')
    end = next((i for i in range(start + 1, len(lines)) if re.fullmatch(r'  [A-Za-z0-9_-]+:', lines[i])),
               len(lines))
    return lines[start:end]


def parse_job(text):
    """Return (job header fields, steps); each step is a dict of its name/if/run lines."""
    job = mutation_job(text)
    header = {}
    for line in job:
        m = re.fullmatch(r'    name: controller-mutations \(\$\{\{ matrix\.shard \}\}/(\d+)\)', line)
        if m:
            header['label_total'] = int(m[1])
        m = re.fullmatch(r'    timeout-minutes: (\d+)', line)
        if m:
            header['timeout'] = int(m[1])
        m = re.fullmatch(r'        shard: \[([0-9, ]+)\]', line)
        if m:
            header['matrix'] = [int(v) for v in m[1].split(',')]
    steps = []
    for line in job:
        m = re.fullmatch(r'      - (name|uses): (.*)', line)
        if m:
            steps.append({m[1]: m[2]})
            continue
        m = re.fullmatch(r'        (if|run|uses): (.*)', line)
        if m and steps:
            if m[1] in steps[-1]:
                raise AssertionError(f'duplicate {m[1]!r} in step {steps[-1]}')
            steps[-1][m[1]] = m[2]
    return header, steps


def shard_selection(text):
    """{shard: [run command, ...]} for the mutation steps, plus the matrix shard list."""
    header, steps = parse_job(text)
    shards = header['matrix']
    selection = {shard: [] for shard in shards}
    for step in steps:
        run = step.get('run', '')
        if 'mutations' not in run:
            if 'if' in step:
                raise AssertionError(f'setup step must run in every shard: {step}')
            continue
        m = re.fullmatch(r'matrix\.shard == (\d+)', step.get('if', ''))
        if not m:
            raise AssertionError(f'mutation step without a single-shard condition: {step}')
        shard = int(m[1])
        if shard not in selection:
            raise AssertionError(f'step assigned to shard {shard}, matrix is {shards}: {run}')
        selection[shard].append(run)
    return header, selection


def coverage_problems(selection, expected):
    """Every expected command in exactly one shard, nothing extra, and no empty shard."""
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
    union = set(seen)
    for run in sorted(expected - union):
        problems.append(f'{run} runs in no shard')
    for run in sorted(union - expected):
        problems.append(f'{run} is not in the expected set')
    return problems


class CiMutationShardTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')

    def test_four_shards_with_the_unchanged_45_minute_timeout(self):
        header, _ = parse_job(self.text)
        self.assertEqual(header['matrix'], [1, 2, 3, 4])
        self.assertEqual(header['label_total'], 4)
        self.assertEqual(header['timeout'], 45)

    def test_four_shard_union_is_the_full_set_and_shards_are_disjoint(self):
        _, selection = shard_selection(self.text)
        self.assertEqual(sorted(selection), [1, 2, 3, 4])
        self.assertEqual(coverage_problems(selection, EXPECTED), [])
        runs = [run for shard_runs in selection.values() for run in shard_runs]
        self.assertEqual(len(runs), len(EXPECTED))
        for a in selection:
            for b in selection:
                if a < b:
                    self.assertEqual(set(selection[a]) & set(selection[b]), set(), (a, b))

    def test_three_shard_layout_covered_the_same_set(self):
        self.assertEqual(coverage_problems(THREE_SHARD_LAYOUT, EXPECTED), [])
        _, selection = shard_selection(self.text)
        four = {run for runs in selection.values() for run in runs}
        three = {run for runs in THREE_SHARD_LAYOUT.values() for run in runs}
        self.assertEqual(four, three)

    def test_checker_catches_a_dropped_duplicated_or_unassigned_step(self):
        run = 'python scripts/test_holdup_mutations.py'
        dropped = re.sub(r'      - name: [^\n]*\n        if: matrix\.shard == \d+\n'
                         + re.escape(f'        run: {run}\n'), '', self.text)
        self.assertNotEqual(dropped, self.text)
        _, selection = shard_selection(dropped)
        self.assertIn(f'{run} runs in no shard', coverage_problems(selection, EXPECTED))
        duplicated = self.text.replace(
            '        run: python scripts/test_switch_hold_mutations.py\n',
            '        run: python scripts/test_switch_hold_mutations.py\n'
            '      - name: duplicate\n        if: matrix.shard == 2\n'
            f'        run: {run}\n')
        _, selection = shard_selection(duplicated)
        self.assertTrue(any(p.startswith(f'{run} runs in shards') for p in coverage_problems(selection, EXPECTED)))
        unassigned = re.sub(r'(        )if: matrix\.shard == \d+\n(        run: python scripts/test_holdup)',
                            r'\2', self.text)
        with self.assertRaises(AssertionError):
            shard_selection(unassigned)
        out_of_range = self.text.replace('        shard: [1, 2, 3, 4]', '        shard: [1, 2, 3]')
        with self.assertRaises(AssertionError):
            shard_selection(out_of_range)


if __name__ == '__main__':
    unittest.main()
