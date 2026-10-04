"""Public CLI routes for evidence ends and OOS catch-up, against private synthetic receipts."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import goat_studio
import studio_evidence_end
import test_goat_studio as fixtures

FIXTURES = Path(__file__).parent / 'fixtures' / 'oosc'
SATURDAY = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)


class CatchupCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        c = self.fixture.bound(); self.schema, self.policy = c.schema, c.policy
        c.store.close(); c.store = None
        self.exports = self.fixture.root / 'GOAT'
        shutil.copytree(FIXTURES, self.exports)
        self.process = SimpleNamespace(inspect=Mock(return_value=None),
                                       start=Mock(side_effect=AssertionError('No native launch allowed in CLI test')),
                                       close=Mock(side_effect=AssertionError('No native close allowed in CLI test')))
        real_utc = studio_evidence_end._utc
        self.clock = patch('studio_evidence_end._utc', side_effect=lambda now: SATURDAY if now is None else real_utc(now))
        self.clock.start(); self.addCleanup(self.clock.stop)

    def tearDown(self):
        self.fixture.tearDown()

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.schema, self.policy)), \
                patch('studio_seed_process.WindowsSeedProcess', return_value=self.process), redirect_stdout(output):
            code = goat_studio.main(['--installation', str(self.fixture.path), *args])
        return code, json.loads(output.getvalue())

    def test_discovery_lists_every_catchup_operation(self):
        code, result = self.cli('discover')
        self.assertEqual(code, 0)
        info = result['result']
        for operation in ('evidence-end', 'evidence-scan', 'evidence-versions', 'catchup-validate', 'catchup-prepare',
                          'catchup-start', 'catchup-resume', 'catchup-status', 'catchup-cancel', 'catchup-report',
                          'equivalence-certificate', 'equivalence-status', 'equivalence-canary-plan', 'equivalence-canary-ingest'):
            self.assertIn(operation, info['operations'])
            self.assertIn(operation, info['operation_contracts'])
        self.assertEqual(info['operation_contracts']['catchup-start']['limits']['max-seconds'], [1, 3600])
        self.assertIn('read-only', info['operation_contracts']['evidence-scan']['effect'])

    def test_evidence_end_resolves_auto_and_reports_the_native_end(self):
        code, result = self.cli('evidence-end')
        self.assertEqual(code, 0, result)
        value = result['result']
        self.assertEqual((value['mode'], value['iso'], value['tester_to_date']), ('auto', '2026-10-02', '2026.10.03'))
        self.assertEqual(value['batch_exports_now']['iso'], '2026-10-01')
        self.assertFalse(value['ea_evidence_end_setting']['supported'])
        code, result = self.cli('evidence-end', '--value', '2026-10-05')
        self.assertEqual(code, 2)
        self.assertIn('not a closed broker day', result['error'])

    def test_evidence_scan_reads_real_exports_without_writing(self):
        before = sorted(str(p) for p in self.exports.rglob('*'))
        code, result = self.cli('evidence-scan', '--source', str(self.exports / 'g6'), '--source', str(self.exports / 'r8'))
        self.assertEqual(code, 0, result)
        scan = result['result']
        self.assertEqual(scan['target']['iso'], '2026-10-02')
        self.assertEqual(scan['summary']['counts'], dict(behind=4, current=0, ahead=0, caught_up=0, ineligible=2))
        self.assertEqual(scan['summary']['evidence_ends'], {'2026-09-24': 1, '2026-09-30': 1, '2026-10-01': 2})
        self.assertEqual(sorted(str(p) for p in self.exports.rglob('*')), before)
        self.process.start.assert_not_called(); self.process.close.assert_not_called()

    def test_validate_previews_members_and_prepare_routes_to_the_runner(self):
        plan = self.fixture.root / 'catchup.json'
        sets = [str(p) for p in sorted((self.exports / 'g6').rglob('*.set')) if '.goatseq' not in str(p.parent)]
        plan.write_text(json.dumps(dict(schema_version=1, evidence_end='auto', sets=sets, job_timeout_seconds=900)))
        code, result = self.cli('catchup-validate', '--plan', str(plan))
        self.assertEqual(code, 0, result)
        preview = result['result']
        self.assertEqual((preview['writes'], preview['native_launch_qualified']), (False, False))
        self.assertFalse((Path(self.fixture.receipt['controller_state_root']) / 'catchups').exists())
        reasons = ' '.join(' '.join(row.get('reasons', [])) for row in preview['exports'])
        self.assertIn('Below the batch export thresholds', reasons)
        runner = Mock()
        runner.prepare.return_value = {'synthetic_route_only': True}
        runner.start.return_value = {'synthetic_route_only': True}
        runner.report.return_value = {'synthetic_route_only': True}
        with patch('studio_catchup.CatchupRunner', return_value=runner):
            self.assertEqual(self.cli('catchup-prepare', '--catchup-id', 'cu1', '--plan', str(plan))[0], 0)
            self.assertEqual(self.cli('catchup-start', '--catchup-id', 'cu1')[0], 0)
            self.assertEqual(self.cli('catchup-report', '--catchup-id', 'cu1')[0], 0)
        self.assertEqual(runner.prepare.call_args[0][0], 'cu1')
        self.assertEqual(runner.prepare.call_args[0][1]['evidence_end'], 'auto')
        runner.start.assert_called_once_with('cu1', max_seconds=60)
        runner.report.assert_called_once_with('cu1')

    def test_equivalence_routes_store_and_read_a_certificate_without_a_terminal(self):
        from test_studio_equivalence import FILES, tree
        import subprocess
        repo = self.fixture.root / 'ea-repo'
        tree(repo)
        (repo / 'GOAT V1.49.ex5').write_bytes(b'old-binary')
        for args in (('init', '-q'), ('config', 'user.email', 't@example.invalid'), ('config', 'user.name', 't'), ('config', 'core.autocrlf', 'false'),
                     ('add', '-A'), ('commit', '-q', '-m', 'old')):
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
        head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
        import hashlib
        old_sha = hashlib.sha256(b'old-binary').hexdigest()
        code, result = self.cli('equivalence-certificate', '--repo', str(repo), '--export-ea-sha256', old_sha, '--installed-commit', head)
        self.assertEqual(code, 0, result)
        self.assertEqual(result['result']['status'], 'not_comparable')   # fail closed: no compiler or external hashes
        self.assertIn('compiler identity unknown', ' '.join(result['result']['problems']))
        from test_studio_equivalence import EXTERNALS
        externals = self.fixture.root / 'externals.json'
        externals.write_text(json.dumps({name: 'e' * 64 for name in EXTERNALS}), encoding='utf-8')
        code, result = self.cli('equivalence-certificate', '--repo', str(repo), '--export-ea-sha256', old_sha, '--installed-commit', head,
                                '--export-externals', str(externals), '--installed-externals', str(externals),
                                '--export-compiler-sha256', 'c' * 64, '--installed-compiler-sha256', 'c' * 64)
        self.assertEqual(code, 0, result)
        cert = result['result']
        self.assertEqual((cert['status'], cert['active'], cert['compiler_equal']), ('pending_canary', False, True))   # same source; no canary yet
        code, refused = self.cli('equivalence-canary-ingest', '--certificate', cert['digest'], '--pairs', str(externals), '--min-sets', '1')
        self.assertEqual(code, 2)
        self.assertIn('hard floor', refused['error'])
        self.assertEqual(cert['export_build']['provenance'], 'git_ex5_blob')
        code, status = self.cli('equivalence-status', '--certificate', cert['digest'])
        self.assertEqual((code, status['result']['digest']), (0, cert['digest']))
        code, refused = self.cli('equivalence-canary-ingest', '--certificate', cert['digest'])
        self.assertEqual(code, 2)
        self.assertIn('exactly one of --catchup-id or --pairs', refused['error'])
        self.process.start.assert_not_called(); self.process.close.assert_not_called()

    def test_versions_listing_is_empty_until_a_catchup_completes(self):
        code, result = self.cli('evidence-versions')
        self.assertEqual((code, result['result']['count']), (0, 0))


if __name__ == '__main__':
    unittest.main()
