"""An export its Prove batch left unverified is said once for the batch and is never planned for a catch-up without a
disclosed tag (GOAT-EA#315).

Hunt round 13a: after the first member whose SET set ``Ledger_Mode=1``, every later member of the batch exported with
``Ledger_Mode=1`` although its own SET omitted it (61 exports). Each was marked ``unverified`` in its member's report
(``Fixed export input mismatch: Ledger_Mode``); the batch result did not say so and evidence-scan never read it.
The exports here are fixture units in the EA's own layout; the scan, the finish and the catch-up planner are real."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import studio_catchup as sc
import studio_finish
from studio_export_scan import scan_exports, unverified_summary
from studio_bridge import write_json
import test_studio_benchmark
import test_studio_catchup as catchup_fixtures
from test_studio_catchup_verdict import VALUES

ROOT = Path(__file__).resolve().parent
LEDGER_MODE = json.loads((ROOT / 'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))['inputs']['Ledger_Mode']
SCHEMA = dict(catchup_fixtures.SCHEMA, inputs=dict(catchup_fixtures.SCHEMA['inputs'], Ledger_Mode=LEDGER_MODE))
MISMATCH = 'Fixed export input mismatch: Ledger_Mode'
TAG = 'ledger PositionJoin, inherited'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def member_set(alias, **more):
    """A member's own SET as the native run keeps it (inputs\\<alias>\\Inputs.GOAT): one axis, Ledger_Mode only if given."""
    values = dict(EA_Desc=alias, Mode_Operation='9', Lots_Input='0.05||0.01||0.01||0.09||Y', Grid_Size='-2.25', **more)
    return ('\r\n'.join(name + '=' + value for name, value in values.items()) + '\r\n').encode('utf-16')


class UnverifiedCase(catchup_fixtures.CatchupCase):
    """CatchupCase's run folder, on a build that declares Ledger_Mode, with one export that inherited Ledger_Mode=1."""

    def setUp(self):
        super().setUp()
        self.controller.schema = SCHEMA
        # The member's SET omits Ledger_Mode; the export the EA wrote records the 1 the tester still held.
        self.inherited = self.export('Rinherit1', 'AUDUSD', self.history, values=dict(VALUES, Ledger_Mode='1'))
        self.write_run_manifest(aliases=('Rbehind01', 'Rahead001', 'Rweak0001', 'Rinherit1'))

    def scan(self, alias, symbol, source):
        """The Prove report's own scan of one member's export folder (studio_report_observe calls it the same way)."""
        passes = {'7': dict(Lots_Input='0.05')}
        return scan_exports(self.run / 'deploy' / alias / symbol, source, SCHEMA, passes, dict(passes), alias=alias, symbol=symbol,
                            period='M1', expert_name='GOAT V1.49', min_arf=0.2, min_sr=2.5)

    def reports(self):
        """The batch report: member 0's export matches its SET, member 1's inherited Ledger_Mode=1."""
        return dict(status='report_batch_verified', members=[
            dict(index=0, run_alias='Rbehind01', symbol='EURUSD', status='report_pair_verified',
                 exports=self.scan('Rbehind01', 'EURUSD', member_set('Rbehind01'))),
            dict(index=1, run_alias='Rinherit1', symbol='AUDUSD', status='report_pair_verified',
                 exports=self.scan('Rinherit1', 'AUDUSD', member_set('Rinherit1')))])

    def write_result(self, reports=None, *, attempt='a' * 64, batch_id='hunt-13a', run=None, activation=True):
        folder = self.controller.root / 'attempts' / attempt
        folder.mkdir(parents=True, exist_ok=True)
        reports = self.reports() if reports is None else reports
        write_json(folder / 'result.json', dict(schema_version=1, job_id=batch_id, status='completed', native=dict(native_run=str(run or self.run)),
                                                reports=reports, unverified_exports=unverified_summary(reports)))
        if activation:
            write_json(folder / 'activation.json', dict(stage='CONTROLS_INSTALLED_NOT_ARMED', run=str(run or self.run)))
        return folder

    def rows(self, sources=None, **options):
        scan = sc.evidence_scan(sources or [self.run], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root, **options)
        return {Path(row['set_path']).parent.parent.name: row for row in scan['exports']}, scan


class ProveReportTests(UnverifiedCase):
    def test_an_export_that_inherited_ledger_mode_is_unverified_and_one_that_matches_its_set_is_not(self):
        inherited = self.scan('Rinherit1', 'AUDUSD', member_set('Rinherit1'))        # the real positive
        (item,) = inherited['files']
        self.assertEqual((item['status'], item['reason']), ('unverified', MISMATCH))
        self.assertEqual(item['artifacts'][0], dict(path=str(self.inherited.resolve()), sha256=sha256(self.inherited)))
        self.assertEqual((inherited['unverified_count'], inherited['native_threshold_candidate_count']), (1, 0))
        clean = self.scan('Rbehind01', 'EURUSD', member_set('Rbehind01'))            # a real negative: neither names it
        self.assertEqual((clean['files'][0]['input_identity']['status'], clean['unverified_count']), ('SET_INPUTS_MATCH_PAIRED_PASSES', 0))
        self.assertNotEqual(clean['files'][0]['status'], 'unverified')
        asked = self.scan('Rinherit1', 'AUDUSD', member_set('Rinherit1', Ledger_Mode='1'))   # a real negative: the SET asked for 1
        self.assertEqual((asked['files'][0]['input_identity']['status'], asked['unverified_count']), ('SET_INPUTS_MATCH_PAIRED_PASSES', 0))

    def test_the_batch_summary_counts_them_and_names_the_input(self):
        summary = unverified_summary(self.reports())
        self.assertEqual((summary['count'], summary['member_count'], summary['inputs'], summary['files_omitted']), (1, 1, dict(Ledger_Mode=1), 0))
        self.assertEqual(summary['reasons'], [dict(reason=MISMATCH, count=1)])
        self.assertEqual(summary['files'], [dict(index=1, run_alias='Rinherit1', symbol='AUDUSD', name=self.inherited.name[:-4], reason=MISMATCH,
                                                 set_path=str(self.inherited.resolve()), set_sha256=sha256(self.inherited))])
        self.assertEqual(summary['plain'], '1 export of 1 member is unverified: Ledger_Mode differs from the member\'s own SET in 1 (an input '
                                           'the SET omits counts at its default). An unverified export is not what its member asked for; '
                                           'do not count it or re-test it without saying so.')
        # A one-member batch's report is the member itself; a clean batch says so; no report is no summary.
        single = dict(self.reports()['members'][1])
        self.assertEqual(unverified_summary(single)['count'], 1)
        clean = unverified_summary(dict(status='report_batch_verified', members=self.reports()['members'][:1]))
        self.assertEqual((clean['count'], clean['inputs'], clean['plain']), (0, {}, 'No export of this batch is unverified.'))
        self.assertIsNone(unverified_summary(None))
        # Other reasons are counted and said too.
        other = dict(members=[dict(index=0, exports=dict(files=[dict(name='x', status='unverified', reason='Incomplete SET/CSV pair')] * 2))])
        said = unverified_summary(other)
        self.assertEqual((said['count'], said['inputs'], said['files'][0]['set_sha256']), (2, {}, None))
        self.assertIn('2 exports of 1 member are unverified: Incomplete SET/CSV pair (2).', said['plain'])


class FinishTests(unittest.TestCase):
    """The real finish of a native batch stores the summary in result.json and in the job's completion."""

    def finished(self, reports=None):
        fixture = test_studio_benchmark.BenchmarkTests()
        real = studio_finish.observe_reports
        with patch.object(studio_finish, 'observe_reports', side_effect=lambda *a, **k: real(*a, **k) if reports is None else reports):
            fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture, json.loads(fixture.result_path.read_text(encoding='utf-8'))

    def test_a_clean_batch_says_none_and_a_batch_with_inherited_exports_says_how_many_and_which_input(self):
        fixture, result = self.finished()
        self.assertEqual((result['unverified_exports']['count'], result['unverified_exports']['plain']), (0, 'No export of this batch is unverified.'))
        self.assertEqual(fixture.c.job('customer-batch')['completion']['unverified_exports'], result['unverified_exports'])
        case = ProveReportTests('test_the_batch_summary_counts_them_and_names_the_input'); case.setUp(); self.addCleanup(case.tearDown)
        fixture, result = self.finished(case.reports())
        self.assertEqual((result['unverified_exports']['count'], result['unverified_exports']['inputs']), (1, dict(Ledger_Mode=1)))
        self.assertIn('Ledger_Mode differs from the member\'s own SET in 1', result['unverified_exports']['plain'])
        self.assertEqual(fixture.c.job('customer-batch')['completion']['unverified_exports'], result['unverified_exports'])


class EvidenceScanTests(UnverifiedCase):
    def test_the_scan_marks_the_unverified_export_ineligible_with_the_reason_and_leaves_the_clean_one(self):
        rows, scan = self.rows()
        self.assertEqual((rows['Rinherit1']['status'], rows['Rbehind01']['status']), ('behind', 'behind'))   # before: nothing read the report
        result = self.write_result()
        rows, scan = self.rows()
        row = rows['Rinherit1']
        self.assertEqual((row['status'], row['code'], row['unverified'], row['unverified_batch_id'], row['unverified_reason']),
                         ('ineligible', sc.UNVERIFIED_EXPORT, True, 'hunt-13a', MISMATCH))
        self.assertEqual(row['reasons'], ['Unverified by its Prove batch hunt-13a (%s): it is not what its member asked for, and is '
                                          're-tested only when the plan discloses it' % MISMATCH])
        self.assertEqual(row['unverified_result_path'], str(result / 'result.json'))
        self.assertEqual(rows['Rbehind01']['status'], 'behind')                    # the real negative, same run, same result
        self.assertNotIn('unverified', rows['Rbehind01'])
        self.assertIn('Unverified by its Prove batch hunt-13a', scan['summary']['plain'])
        self.assertFalse(scan['writes'])
        # Without the controller state there is no Prove report to read, as before.
        plain = sc.evidence_scan([self.run], now=catchup_fixtures.AFTER_CLOSE)
        self.assertEqual({r['status'] for r in plain['exports'] if 'Rinherit1' in r['set_path']}, {'behind'})

    def test_a_disclosed_export_stays_eligible_and_carries_its_tag(self):
        self.write_result()
        rows, _ = self.rows(disclosed={sha256(self.inherited): TAG})
        row = rows['Rinherit1']
        self.assertEqual((row['status'], row['unverified'], row['unverified_disclosed'], row['unverified_reason']), ('behind', True, TAG, MISMATCH))
        # A tag for an export no report left unverified changes nothing; a malformed disclosure refuses.
        rows, _ = self.rows(disclosed={sha256(self.behind): TAG})
        self.assertEqual((rows['Rbehind01']['status'], 'unverified_disclosed' in rows['Rbehind01'], rows['Rinherit1']['status']),
                         ('behind', False, 'ineligible'))
        for bad in ({'not-a-sha': TAG}, {sha256(self.inherited): ''}, {sha256(self.inherited): 'two\nlines'}, [sha256(self.inherited)]):
            with self.assertRaisesRegex(ValueError, 'disclosed_unverified maps the SHA-256'):
                self.rows(disclosed=bad)

    def test_a_report_that_verified_every_export_marks_none(self):
        clean = dict(status='report_batch_verified', members=self.reports()['members'][:1])
        self.write_result(clean)
        rows, _ = self.rows()
        self.assertEqual((rows['Rinherit1']['status'], rows['Rbehind01']['status']), ('behind', 'behind'))

    def test_a_library_copy_outside_its_run_folder_is_found_by_its_sha256(self):
        self.write_result()
        library = self.root / 'library' / 'AUDUSD'
        shutil.copytree(self.inherited.parent, library)
        copy = library / self.inherited.name
        rows = sc.evidence_scan([copy], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root)['exports']
        self.assertEqual((rows[0]['run_id'], rows[0]['status'], rows[0]['unverified_batch_id']), (None, 'ineligible', 'hunt-13a'))

    def test_only_the_exports_own_run_is_read_and_an_unreadable_result_of_it_refuses(self):
        # Another run's attempt with a broken result is never opened for exports of this run ...
        other = self.write_result(attempt='b' * 64, batch_id='other', run=self.root / 'GOAT' / 'Rother')
        (other / 'result.json').write_text('{broken', encoding='utf-8')
        self.write_result()
        rows, _ = self.rows()
        self.assertEqual(rows['Rinherit1']['status'], 'ineligible')
        # ... but a library copy has no run, so every result is read, and an unreadable one refuses the scan.
        library = self.root / 'library' / 'AUDUSD'
        shutil.copytree(self.inherited.parent, library)
        with self.assertRaisesRegex(ValueError, 'cannot be read .* its unverified exports are unknown; nothing is classified'):
            sc.evidence_scan([library / self.inherited.name], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root)
        # This run's own result unreadable: refused too, never one unverified export fewer.
        (other / 'result.json').unlink()
        (self.controller.root / 'attempts' / ('a' * 64) / 'result.json').write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'its unverified exports are unknown'):
            self.rows()
        # An attempt whose activation.json does not name its run is read for every run.
        self.write_result(activation=False)
        (self.controller.root / 'attempts' / ('a' * 64) / 'activation.json').unlink()
        rows, _ = self.rows()
        self.assertEqual(rows['Rinherit1']['status'], 'ineligible')


class CatchupPlanTests(UnverifiedCase):
    def plan_for(self, **extra):
        return self.plan(sets=[self.behind, self.inherited], **extra)

    def test_the_planner_never_plans_an_unverified_export_and_plans_the_clean_one(self):
        both = self.runner.validate(self.plan_for())
        self.assertEqual(both['member_count'], 2)                                   # before: it would have been re-tested
        self.write_result()
        preview = self.runner.validate(self.plan_for())
        self.assertEqual(preview['member_count'], 1)
        prepared = self.runner.prepare('cu1', self.plan_for())
        manifest = catchup_fixtures.read_json(self.runner.path('cu1') / 'manifest.json')
        self.assertEqual([m['source_path'] for m in manifest['members']], [str(self.behind)])
        rows = {Path(row['set_path']).parent.parent.name: row for row in manifest['exports']}
        self.assertEqual((rows['Rinherit1']['status'], rows['Rinherit1']['code'], rows['Rinherit1']['unverified_reason']),
                         ('ineligible', sc.UNVERIFIED_EXPORT, MISMATCH))
        self.assertNotIn('alias', rows['Rinherit1'])
        self.assertEqual(prepared['status'], 'prepared')
        # Only the unverified export in the plan: nothing to catch up, and the sentence says why.
        with self.assertRaisesRegex(ValueError, 'Nothing to catch up .*Unverified by its Prove batch hunt-13a'):
            self.runner.prepare('cu2', self.plan(sets=[self.inherited]))

    def test_a_disclosed_unverified_export_is_planned_and_its_member_carries_the_tag(self):
        self.write_result()
        plan = self.plan_for(disclosed_unverified={sha256(self.inherited): TAG})
        self.runner.prepare('cu1', plan)
        manifest = catchup_fixtures.read_json(self.runner.path('cu1') / 'manifest.json')
        members = {m['source_path']: m for m in manifest['members']}
        self.assertEqual(sorted(members), sorted([str(self.behind), str(self.inherited)]))
        self.assertEqual(members[str(self.inherited)]['original']['unverified_disclosed'], dict(batch_id='hunt-13a', reason=MISMATCH, tag=TAG))
        self.assertNotIn('unverified_disclosed', members[str(self.behind)]['original'])
        rows = {Path(row['set_path']).parent.parent.name: row for row in manifest['exports']}
        self.assertEqual((rows['Rinherit1']['status'], rows['Rinherit1']['unverified_disclosed']), ('behind', TAG))
        # Its re-test runs the export's own inputs: the config pins the Ledger_Mode=1 the export records.
        config = sc._tester_inputs_section(Path(members[str(self.inherited)]['config_path']).read_bytes())
        self.assertEqual((config['Ledger_Mode'], sc._tester_inputs_section(Path(members[str(self.behind)]['config_path']).read_bytes())['Ledger_Mode']),
                         ('1', '0'))
        with self.assertRaisesRegex(ValueError, 'disclosed_unverified maps the SHA-256'):
            self.runner.validate(self.plan_for(disclosed_unverified={sha256(self.inherited): 7}))


if __name__ == '__main__':
    unittest.main()
