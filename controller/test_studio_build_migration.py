"""Build-migration re-tests (goatai#2350, Claude-Mac 6069755001): plan guard, record kind, drift, .goatseq, output root."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import unittest

import studio_build_migration as bm
import studio_catchup as sc
from studio_installation import read_json
from test_studio_catchup import AFTER_CLOSE, CatchupCase
from test_studio_catchup_verdict import daily, make_unit, trading

TARGET = 'V1.49-BETA17-43'
SOURCE = 'V1.49-BETA17-40'
OLD_EA = 'f' * 64
V147_EA = 'e' * 64


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MigrationCase(CatchupCase):
    """Exports of an older build (B40, and a V1.47 export without a .goatseq); the installed EA reports B43."""

    def setUp(self):
        super().setUp()
        self.retest_build = TARGET
        self.behind = self.export('Rmig00001', 'EURUSD', self.history, build_id=SOURCE)
        self.v147 = self.export('Rv1470001', 'AUDUSD', self.history, capture=False)
        self.write_run_manifest(aliases=('Rmig00001', 'Rahead001', 'Rweak0001', 'Rv1470001'), ea_sha256=OLD_EA)
        self.activation(TARGET)

    def originals(self, sets, **change):
        entries = []
        for p in sets:
            csv_path, deals_path = bm.baseline_paths(p)
            entry = dict(original_path=str(p), original_sha256=sha(p), original_csv_sha256=sha(csv_path),
                         source_build=SOURCE if p != self.v147 else 'V1.47')
            if deals_path.is_file():
                entry['original_deals_sha256'] = sha(deals_path)
            entries.append(entry | change)
        return entries

    def mplan(self, sets=None, *, originals=None, **extra):
        sets = sets or [self.behind]
        block = dict(target_build=TARGET, target_ea_sha256=self.controller.install['ea_sha256'],
                     originals=self.originals(sets) if originals is None else originals)
        return self.plan(sets=sets, include_below_threshold=True, build_migration=block, **extra)

    def native_retest(self, member, *, new_per_day=10):
        """The EA's single-pass unit, written by the installed (target) build."""
        tester = member['tester']
        to_date = datetime.strptime(tester['ToDate'], '%Y.%m.%d').date()
        base = self.histories.get(tester['Symbol'], self.history)
        first = base[-1][0].date() + timedelta(days=1)
        rows = base + daily(first, to_date - timedelta(days=1), base[-1][2], new_per_day)
        deals = getattr(self, 'deals_by', {}).get(tester['Symbol'], self.deals) + trading(first, to_date - timedelta(days=1), 2, 6.0)
        windows = [('BOOS', date(2026, 1, 5), date(2026, 1, 19), 20, 100), ('FWD', date(2026, 7, 17), date(2026, 8, 28), 60, 300),
                   ('FOOS', date(2026, 8, 29), to_date - timedelta(days=1), 54, 270)]
        folder = Path(self.controller.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']
        (folder / 'attempt-issued.json').parent.mkdir(parents=True, exist_ok=True)
        (folder / 'attempt-issued.json').write_text('{}', encoding='utf-8')
        return make_unit(folder, rows=rows, deals=deals, alias=member['alias'], symbol=tester['Symbol'], run_id=member['capture_id'],
                         start=datetime.strptime(tester['FromDate'], '%Y.%m.%d').date(), requested_to=to_date, windows=windows,
                         build_id=self.retest_build, capture=member['capture'])

    def run_all(self, catchup_id, plan):
        self.catchup_id = catchup_id
        self.runner.prepare(catchup_id, plan)
        self.auto = True
        state = self.runner.start(catchup_id, 60)
        self.auto = False
        manifest = read_json(self.runner.path(catchup_id) / 'manifest.json')
        return state, manifest


class GuardTests(MigrationCase):
    def test_a_normal_catchup_across_builds_still_refuses(self):
        result = self.runner.validate(self.plan(sets=[self.behind]))
        self.assertEqual(result['member_count'], 0)
        self.assertIn('another EA binary', ' '.join(result['exports'][0]['reasons']))
        self.assertNotIn('build_migration', result)

    def test_b_installed_build_other_than_the_target_refuses(self):
        self.activation(SOURCE)
        with self.assertRaisesRegex(ValueError, 'targets V1.49-BETA17-43, but the installed EA reports V1.49-BETA17-40'):
            self.runner.validate(self.mplan())
        self.activation(None)
        with self.assertRaisesRegex(ValueError, 'installed EA build cannot be read'):
            self.runner.validate(self.mplan())
        self.activation(TARGET)
        plan = self.mplan()
        plan['build_migration']['target_ea_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pins target EA'):
            self.runner.validate(plan)
        del plan['build_migration']['target_ea_sha256']   # required (Mac review 6070262354)
        with self.assertRaisesRegex(ValueError, 'requires target_build, target_ea_sha256 and originals'):
            self.runner.validate(plan)
        self.assertFalse(self.runner.base.exists())

    def test_b_a_prepared_member_never_starts_after_the_build_changes(self):
        self.runner.prepare('bm1', self.mplan())
        self.activation(SOURCE)
        with self.assertRaisesRegex(ValueError, 'installed EA now reports V1.49-BETA17-40; nothing was started'):
            self.runner.start('bm1', 1)
        self.assertFalse(self.starts)

    def test_c_a_set_without_a_recorded_original_refuses_naming_it(self):
        with self.assertRaisesRegex(ValueError, 'no recorded original for SET ' + __import__('re').escape(str(self.v147))):
            self.runner.validate(self.mplan(sets=[self.behind, self.v147], originals=self.originals([self.behind])))
        changed = self.originals([self.behind], original_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'no longer matches its recorded original'):
            self.runner.validate(self.mplan(originals=changed))
        missing = self.root / 'gone.set'
        with self.assertRaisesRegex(ValueError, 'cannot be read'):
            self.runner.validate(self.mplan(sets=[missing], originals=[dict(original_path=str(missing), original_sha256='0' * 64,
                                                                             original_csv_sha256='0' * 64, source_build=SOURCE)]))
        for broken in ([dict(original_path=str(self.behind), source_build=SOURCE)],
                       [dict(original_path=str(self.behind), original_sha256=sha(self.behind), source_build='')],
                       self.originals([self.behind]) + self.originals([self.v147])):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                self.runner.validate(self.mplan(originals=broken))

    def test_c_the_drift_baseline_is_pinned_csv_and_deals(self):
        """Mac review 6070262354: an edited original CSV must never flip reproduced/drifted silently."""
        import re
        name = re.escape(str(self.behind))
        csv_path, deals_path = bm.baseline_paths(self.behind)
        with self.assertRaisesRegex(ValueError, 'the equity CSV of SET %s no longer matches' % name):
            self.runner.validate(self.mplan(originals=self.originals([self.behind], original_csv_sha256='0' * 64)))
        with self.assertRaisesRegex(ValueError, 'the deals.csv of SET %s no longer matches' % name):
            self.runner.validate(self.mplan(originals=self.originals([self.behind], original_deals_sha256='0' * 64)))
        unpinned = self.originals([self.behind])
        del unpinned[0]['original_deals_sha256']
        with self.assertRaisesRegex(ValueError, 'SET %s has a capture deals.csv; pin it' % name):
            self.runner.validate(self.mplan(originals=unpinned))
        with self.assertRaisesRegex(ValueError, 'has no capture deals.csv, but the plan pins one'):
            self.runner.validate(self.mplan(sets=[self.v147], originals=self.originals([self.v147], original_deals_sha256='0' * 64)))
        # Prepared, then the CSV is edited before collection: the member fails and nothing is moved.
        self.runner.prepare('bm1', self.mplan())
        csv_path.write_bytes(csv_path.read_bytes() + '\r\n'.encode('utf-16-le'))
        self.catchup_id = 'bm1'
        self.auto = True
        state = self.runner.start('bm1', 60)
        self.assertEqual(state['members'][0]['status'], 'failed')
        self.assertIn('the equity CSV of SET %s no longer matches' % self.behind, state['members'][0]['error'])
        member = read_json(self.runner.path('bm1') / 'manifest.json')['members'][0]
        self.assertFalse(Path(member['evidence_dir']).exists())

    def test_no_heldout_reveal_with_a_migration(self):
        with self.assertRaisesRegex(ValueError, 'never reveals a held-out lock'):
            self.runner.validate(self.mplan(heldout_reveal=dict(lock_id='alpha')))

    def test_the_recorded_source_build_must_match_the_export(self):
        with self.assertRaisesRegex(ValueError, 'made by EA build V1.49-BETA17-40 \\(its capture\\), but the plan names source_build B28'):
            self.runner.validate(self.mplan(originals=self.originals([self.behind], source_build='B28')))

    def test_no_certificate_with_a_migration(self):
        plan = self.mplan(canary_certificate='a' * 64)
        with self.assertRaisesRegex(ValueError, 'names no equivalence or canary certificate'):
            self.runner.validate(plan)

    def test_accepted_on_the_target_build(self):
        result = self.runner.validate(self.mplan(sets=[self.behind, self.v147]))
        self.assertEqual(result['member_count'], 2)
        self.assertEqual((result['build_migration']['kind'], result['build_migration']['provenance']),
                         ('build_migration_retest', 'build-migration-retest:B43'))
        self.assertEqual([m['source_build'] for m in result['members']], [SOURCE, 'V1.47'])


class RecordTests(MigrationCase):
    def test_d_records_carry_kind_and_provenance_and_consumers_refuse_them(self):
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        state, manifest = self.run_all('bm1', self.mplan())
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(manifest['build_migration']['provenance'], 'build-migration-retest:B43')
        member = manifest['members'][0]
        evidence = Path(member['evidence_dir'])
        self.assertFalse((evidence / 'evidence-version.json').exists())
        record = read_json(evidence / bm.RECORD_FILE)
        self.assertEqual((record['schema'], record['kind'], record['provenance'], record['source_build'], record['target_build']),
                         ('goat-build-migration-retest-v1', 'build_migration_retest', 'build-migration-retest:B43', SOURCE, TARGET))
        for absent in ('verdict', 'catch_up', 'comparison', 'comparability'):
            self.assertNotIn(absent, record)
        self.assertEqual(record['original']['sha256'], sha(self.behind))
        self.assertEqual(record['drift']['verdict'], 'reproduced', record['drift'])
        self.assertEqual(record['drift']['span'], dict(first_day='2026-01-05', last_day='2026-09-24'))
        self.assertEqual((record['drift']['delta']['trades'], record['drift']['delta']['pf'], record['drift']['delta']['max_dd']), (0.0, 0.0, 0.0))
        self.assertEqual((record['windows']['basis'], record['windows']['FOOS']['to']), ('retest', '2026-10-02'))
        self.assertEqual((record['new_weeks']['from'], record['new_weeks']['to'], record['new_weeks']['trades']), ('2026-09-25', '2026-10-02', 12))
        # The unseen weeks are measured, never judged in-tool (Mac review 6070262354).
        self.assertNotIn('oos_rule', record)
        self.assertFalse(record['new_weeks_judged'])
        self.assertIn('measured only', record['judgement'])
        self.assertEqual((record['original']['csv_sha256'], record['original']['deals_sha256']),
                         (sha(bm.baseline_paths(self.behind)[0]), sha(bm.baseline_paths(self.behind)[1])))
        self.assertEqual(record['drift']['baseline'], 'capture_deals')
        self.assertEqual({p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}, before)
        result = read_json(self.runner.path('bm1') / (member['alias'] + '.result.json'))
        self.assertEqual((result['status'], result['kind'], result['summary']['drift']), ('verified_build_migration_retest', 'build_migration_retest', 'reproduced'))
        self.assertNotIn('verdict', result['summary'])
        self.assertNotIn('oos_rule', result['summary'])
        self.assertFalse(result['summary']['new_weeks_judged'])
        self.assertEqual(result['summary']['new_weeks']['trades'], 12)
        for verdictish in ('pass', 'fail', 'held_up', 'weakened', 'failed', 'status'):
            self.assertNotIn(verdictish, result['summary']['new_weeks'])
        # catchup-report handles the kind explicitly: drift counts, no verdict counts.
        report = self.runner.report('bm1')
        self.assertEqual((report['kind'], report['provenance'], report['drift_counts'], report['counts']),
                         ('build_migration_retest', 'build-migration-retest:B43', dict(reproduced=1), dict(completed=1)))
        self.assertNotIn('verdict_rules', report)
        # Evidence versions and the caught-up status ignore it by type: the original is still behind.
        self.assertEqual(sc.versions(self.controller.root), [])
        self.assertEqual(sc.classify(__import__('studio_evidence').read_export(self.behind), '2026-10-02',
                                     known_versions=[dict(record, version_path='x')])['status'], 'behind')
        # Every verdict consumer refuses the record by type.
        with self.assertRaises(bm.NotAVerdict):
            sc.catch_up_stamp(member, manifest, record, record['created_utc'])
        with self.assertRaises(bm.NotAVerdict):
            sc.catch_up_stamp(member, manifest, dict(verdict='held_up'), record['created_utc'])
        with self.assertRaises(bm.NotAVerdict):
            sc.CatchupRunner._oos_rule({}, {}, member, dict(verdict='held_up'))
        with self.assertRaises(bm.NotAVerdict):
            __import__('studio_oos_windows').judge_retest(record, record, tester=None)
        import studio_equivalence as eq
        with self.assertRaisesRegex(bm.NotAVerdict, 'equivalence-canary-ingest'):
            eq.catchup_pairs(self.controller.root, 'bm1', 'a' * 64)
        from studio_gate_calibration import load_verdicts
        found, rejected = load_verdicts(evidence / bm.RECORD_FILE)
        self.assertEqual(found, {})
        self.assertEqual(list(rejected), ['build-migration re-test record (kind build_migration_retest), never a verdict'])
        # A catch-up report over normal manifests refuses a migration result it meets.
        with self.assertRaisesRegex(bm.NotAVerdict, 'catchup-report'):
            bm.refuse(result, 'catchup-report')

    def test_drifted_retest_is_recorded_as_drifted(self):
        self.deals_by = dict(EURUSD=trading(date(2026, 1, 5), date(2026, 9, 24), 2, 4.0))   # the new build trades the same entries, worse
        _, manifest = self.run_all('bm1', self.mplan())
        record = read_json(Path(manifest['members'][0]['evidence_dir']) / bm.RECORD_FILE)
        self.assertEqual(record['drift']['verdict'], 'drifted')
        self.assertIn('pf', ' '.join(record['drift']['reasons']))
        self.assertEqual(self.runner.report('bm1')['drift_counts'], dict(drifted=1))

    def test_a_retest_on_another_build_is_never_collected(self):
        self.retest_build = SOURCE
        state, manifest = self.run_all('bm1', self.mplan())
        item = state['members'][0]
        self.assertEqual(item['status'], 'failed')
        self.assertIn('not the build-migration target V1.49-BETA17-43', item['error'])
        self.assertFalse(Path(manifest['members'][0]['evidence_dir']).exists())

    def test_e_a_v147_set_gets_a_goatseq_and_keeps_its_bytes(self):
        original = self.v147.read_bytes()
        self.assertFalse(self.v147.with_name(self.v147.name[:-4] + '.goatseq').exists())
        plan = self.mplan(sets=[self.v147], originals=self.originals([self.v147], source_ea_sha256=V147_EA))
        self.write_run_manifest(aliases=('Rv1470001',), ea_sha256=V147_EA)
        self.catchup_id = 'bm1'
        self.runner.prepare('bm1', plan)
        member = read_json(self.runner.path('bm1') / 'manifest.json')['members'][0]
        self.assertTrue(member['capture'])
        self.assertEqual((member['source_inputs_origin'], member['build_migration']['goatseq_from']), ('original_set', 'original_set'))
        self.assertEqual(Path(member['source_inputs_path']).read_bytes(), original)
        self.assertEqual(member['source_inputs_sha256'], hashlib.sha256(original).hexdigest())
        ini = Path(member['config_path']).read_bytes().decode('utf-16')
        self.assertIn('Sequence_Export_Enabled=true\r\n', ini)
        self.assertIn('Sequence_Export_Model=4\r\n', ini)
        self.auto = True
        self.runner.start('bm1', 60)
        pending = Path(self.controller.install['common_files_root']) / 'GOATSequencePending' / member['capture_id'] / 'source-inputs.set'
        self.assertEqual(pending.read_bytes(), original)
        evidence = Path(member['evidence_dir'])
        self.assertEqual(len(list(evidence.glob('*.goatseq'))), 1)
        record = read_json(evidence / bm.RECORD_FILE)
        self.assertEqual((record['retest']['goatseq'], record['retest']['goatseq_from'], record['source_build']), (True, 'original_set', 'V1.47'))
        self.assertEqual(record['retest']['values_sha256'], record['original']['values_sha256'])
        self.assertTrue(record['inputs_unchanged'] and record['original_set_unchanged'])
        self.assertEqual(self.v147.read_bytes(), original)
        self.assertEqual(sha(self.v147), plan['build_migration']['originals'][0]['original_sha256'])
        self.assertEqual(record['source_inputs_sha256'], record['original']['sha256'])
        # No capture on the V1.47 original: PF (and here trades) come from the rounded file name, and say so.
        self.assertEqual((record['drift']['original']['pf_source'], record['drift']['baseline']), ('filename_rounded', 'filename_rounded'))
        self.assertIsNone(record['original']['deals_sha256'])

    def test_a_v147_source_binary_mismatch_refuses(self):
        plan = self.mplan(sets=[self.v147], originals=self.originals([self.v147], source_ea_sha256='1' * 64))
        with self.assertRaisesRegex(ValueError, 'made by EA binary ffffffffffff \\(its run manifest\\)'):
            self.runner.validate(plan)


class ChainedCatchupTests(MigrationCase):
    """Mac review 6070262354 BLOCKER: a normal B43 catch-up of a migrated re-test must never carry the B40 original."""

    def test_blocker_an_original_never_inherits_a_new_build_verdict(self):
        from studio_evidence import read_export
        _, manifest = self.run_all('bm1', self.mplan())
        migrated = next(Path(manifest['members'][0]['evidence_dir']).glob('*.set'))
        # A week later, an ordinary catch-up of the migrated re-test SET on B43 (the same build that made it).
        week_later = datetime(2026, 10, 10, 8, tzinfo=AFTER_CLOSE.tzinfo)
        self.runner = sc.CatchupRunner(self.controller, process=self.process, clock=lambda: self.now, sleep=self.sleep, now=week_later)
        self.starts.clear()
        self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='monitor')
        state, manifest2 = self.run_all('cu2', self.plan(sets=[migrated], include_below_threshold=True, assume=dict(ExecutionMode=0)))
        self.assertEqual(state['status'], 'completed')
        found = sc.versions(self.controller.root)
        self.assertEqual(len(found), 1)
        version = found[0]
        self.assertNotIn(version['verdict']['verdict'], sc.UNCARRIED)   # a carried verdict, so the test means something
        self.assertEqual((version['kind'], version['original']['build']), ('oos_catchup', TARGET))
        original = read_export(self.behind)
        # The pre-fix key (values, symbol, period, start) is shared: this is exactly the inheritance Mac reproduced.
        self.assertEqual((version['values_sha256'], version['symbol'], version['period'], version['evidence_start']),
                         (original['values_sha256'], original['symbol'], original['period'], original['evidence_start']))
        row = sc.classify(original, '2026-10-09', include_below_threshold=True, known_versions=found)
        self.assertEqual(row['status'], 'behind')
        self.assertNotIn('verdict', row)
        self.assertEqual(row['build'], SOURCE)
        # The migrated SET itself (made by B43) is caught up by its own B43 version.
        self.assertEqual(sc.classify(read_export(migrated), '2026-10-09', include_below_threshold=True, known_versions=found)['status'],
                         'caught_up')
        scan = sc.evidence_scan([self.behind], value='2026-10-09', now=week_later, controller_root=self.controller.root,
                                include_below_threshold=True)
        self.assertEqual(scan['exports'][0]['status'], 'behind')

    def test_versions_without_a_build_carry_only_their_exact_set(self):
        from studio_evidence import read_export
        original = read_export(self.behind)
        legacy = dict(schema=sc.VERSION_SCHEMA, values_sha256=original['values_sha256'], symbol='EURUSD', period='M1',
                      evidence_start=original['evidence_start'], evidence_end='2026-10-02', version_path='x',
                      verdict=dict(verdict='held_up'), original=dict(set_sha256='0' * 64))
        self.assertEqual(sc.classify(original, '2026-10-02', known_versions=[legacy])['status'], 'behind')
        exact = dict(legacy, original=dict(set_sha256=original['set_sha256']))
        self.assertEqual(sc.classify(original, '2026-10-02', known_versions=[exact])['status'], 'caught_up')
        other_build = dict(legacy, original=dict(set_sha256=original['set_sha256'], build=TARGET))
        self.assertEqual(sc.classify(original, '2026-10-02', known_versions=[other_build])['status'], 'behind')
        same_build = dict(legacy, original=dict(build=SOURCE))
        self.assertEqual(sc.classify(original, '2026-10-02', known_versions=[same_build])['status'], 'caught_up')
        for kinded in (dict(same_build, kind='build_migration_retest'), dict(same_build, kind='something_else')):
            self.assertEqual(sc.classify(original, '2026-10-02', known_versions=[kinded])['status'], 'behind')


class OutputRootTests(MigrationCase):
    def test_f_output_root_writes_under_the_given_root(self):
        out = self.root / 'evidence-out'
        state, manifest = self.run_all('bm1', self.mplan(output_root=str(out)))
        self.assertEqual(state['status'], 'completed')
        member = manifest['members'][0]
        self.assertTrue(sc.plain(member['evidence_dir']).startswith(str(out)))
        self.assertTrue((Path(member['evidence_dir']) / bm.RECORD_FILE).is_file())
        self.assertEqual(manifest['output_root'], str(out))
        self.assertFalse((self.controller.root / 'evidence').exists())
        self.assertEqual(read_json(out / sc.evidence_key('bm1') / 'catchup.json')['catchup_id'], 'bm1')
        self.assertEqual(sc.evidence_roots(self.controller.root)[1:], [out])
        self.assertFalse(list(out.rglob('*~')))   # the staging folder was renamed into place

    def test_f_a_normal_catchup_under_an_output_root_is_still_found(self):
        self.retest_build = 'TEST'
        self.behind = self.export('Rbehind02', 'EURUSD', self.history)
        self.write_run_manifest(aliases=('Rbehind02',))
        out = self.root / 'evidence-out'
        state, manifest = self.run_all('cu1', self.plan(sets=[self.behind], output_root=str(out)))
        self.assertEqual(state['status'], 'completed')
        found = sc.versions(self.controller.root)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]['version_path'].startswith(str(out)) or sc.plain(found[0]['version_path']).startswith(str(out)))
        self.assertEqual(sc.evidence_folder(self.controller.root, 'cu1').name, sc.evidence_key('cu1'))

    def test_f_default_is_unchanged(self):
        _, manifest = self.run_all('bm1', self.mplan())
        member = manifest['members'][0]
        self.assertEqual(Path(sc.plain(member['evidence_dir'])).parent.parent, self.controller.root / 'evidence')
        self.assertNotIn('output_root', manifest)
        self.assertFalse((self.controller.root / sc.EVIDENCE_ROOTS).exists())
        self.assertEqual(self.runner.validate(self.mplan())['paths']['evidence_root_source'], 'controller_state')

    def test_f_output_root_must_be_an_absolute_local_path(self):
        for bad in ('\\\\server\\share\\evidence', '//server/share/evidence', '\\\\?\\C:\\evidence', 'relative\\evidence',
                    '\\evidence', 'C:evidence', 'C:\\a\\..\\b', '', 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.runner.validate(self.mplan(output_root=bad))
        with self.assertRaisesRegex(ValueError, 'UNC'):
            bm.output_root('\\\\nas\\goat\\evidence', windows=True)
        self.assertEqual(bm.output_root('/srv/goat/evidence', windows=False), Path('/srv/goat/evidence'))
        afile = self.root / 'afile'
        afile.write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'is a file'):
            self.runner.validate(self.mplan(output_root=str(afile)))

    def test_f_links_unknown_drives_and_free_space(self):
        from unittest.mock import patch
        out = str(self.root / 'linked')
        with patch('studio_build_migration.os.path.realpath', return_value='\\\\nas\\share\\evidence'):
            with self.assertRaisesRegex(ValueError, 'resolves to .*not a local drive path'):
                bm.output_root(out, windows=True)
        for kind, word in ((0, 'unknown type'), (4, 'network drive'), (5, 'CD-ROM'), (1, 'does not exist')):
            with patch('studio_build_migration._drive_type', return_value=kind), self.assertRaisesRegex(ValueError, word):
                bm.output_root(out, windows=True)
        with patch('shutil.disk_usage', return_value=SimpleUsage(free=bm.FREE_MARGIN_BYTES)):
            with self.assertRaisesRegex(ValueError, 're-test units need about'):
                self.runner.validate(self.mplan(output_root=out))
        self.assertEqual(self.runner.validate(self.mplan(output_root=out))['member_count'], 1)

    def test_f_default_root_named_explicitly_is_not_recorded_twice(self):
        self.run_all('bm1', self.mplan(output_root=str(self.controller.root / 'evidence')))
        self.assertFalse((self.controller.root / sc.EVIDENCE_ROOTS).exists())
        self.assertEqual(sc.evidence_roots(self.controller.root), [self.controller.root / 'evidence'])

    def test_f_versions_fail_closed_when_a_recorded_root_is_gone(self):
        self.retest_build = 'TEST'
        self.behind = self.export('Rbehind02', 'EURUSD', self.history)
        self.write_run_manifest(aliases=('Rbehind02',))
        out = self.root / 'evidence-out'
        self.run_all('cu1', self.plan(sets=[self.behind], output_root=str(out)))
        self.assertEqual(sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)['exports'][0]['status'],
                         'caught_up')
        out.rename(self.root / 'unplugged')   # G: unplugged
        with self.assertRaisesRegex(ValueError, 'is unavailable; reconnect it'):
            sc.evidence_scan([self.behind], now=AFTER_CLOSE, controller_root=self.controller.root)
        with self.assertRaisesRegex(ValueError, 'is unavailable'):
            self.runner.validate(self.plan(sets=[self.behind]))
        (self.controller.root / sc.EVIDENCE_ROOTS).write_text('{not json', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'cannot be read'):
            sc.versions(self.controller.root)

    def test_f_cross_drive_copy_is_verified_and_removes_the_temp_unit(self):
        from unittest.mock import patch
        out = self.root / 'evidence-out'
        temp = str(Path(self.controller.install['common_files_root']) / 'TEMP' / 'SQ')
        real = sc.os.rename

        def cross_device(source, target):
            if str(source).startswith(temp):
                raise OSError(18, 'Not the same device')
            return real(source, target)
        with patch.object(sc.os, 'rename', cross_device):
            state, manifest = self.run_all('bm1', self.mplan(output_root=str(out)))
        self.assertEqual(state['status'], 'completed')
        member = manifest['members'][0]
        evidence = Path(member['evidence_dir'])
        self.assertEqual(len(list(evidence.glob('*.goatseq'))), 1)
        self.assertTrue((evidence / bm.RECORD_FILE).is_file())
        attempt = Path(temp) / member['attempt_token']
        self.assertEqual(sorted(p.name for p in attempt.iterdir()), ['attempt-issued.json'])


class SimpleUsage:
    def __init__(self, free):
        self.total, self.used, self.free = free * 2, free, free


class DriftTests(unittest.TestCase):
    def verdict(self, original, retest):
        base = dict(trades=100, pf=1.5, max_dd=100)
        return bm.judge_drift(base | original, base | retest)['verdict']

    def test_g_tolerances_are_one_constant_citing_the_ruling(self):
        self.assertEqual((str(bm.TOLERANCES['pf_abs']), str(bm.TOLERANCES['trades_rel']), str(bm.TOLERANCES['max_dd_rel'])), ('0.15', '0.10', '0.20'))
        self.assertIn('6069528877', bm.TOLERANCES['source'])

    def test_g_boundaries_are_inclusive(self):
        cases = [
            (dict(), dict(trades=110), 'reproduced'), (dict(), dict(trades=111), 'drifted'),
            (dict(), dict(trades=90), 'reproduced'), (dict(), dict(trades=89), 'drifted'),
            (dict(), dict(pf=1.65), 'reproduced'), (dict(), dict(pf=1.66), 'drifted'),
            (dict(), dict(pf=1.35), 'reproduced'), (dict(), dict(pf=1.34), 'drifted'),
            (dict(pf=2.0), dict(pf=1.85), 'reproduced'), (dict(pf=2.0), dict(pf=2.1500001), 'drifted'),
            (dict(), dict(max_dd=120), 'reproduced'), (dict(), dict(max_dd=120.01), 'drifted'),
            (dict(), dict(max_dd=80), 'reproduced'), (dict(), dict(max_dd=79.99), 'drifted'),
            (dict(trades=0), dict(trades=0), 'reproduced'), (dict(trades=0), dict(trades=1), 'drifted'),
            (dict(max_dd=0), dict(max_dd=0), 'reproduced'), (dict(max_dd=0), dict(max_dd=0.5), 'drifted'),
            (dict(), dict(pf=None), 'drifted'), (dict(), dict(trades=None), 'drifted'), (dict(), dict(max_dd=None), 'drifted'),
            (dict(pf=None, pf_note='no losing deals'), dict(pf=None, pf_note='no losing deals'), 'reproduced'),
        ]
        for original, retest, expected in cases:
            with self.subTest(original=original, retest=retest):
                self.assertEqual(self.verdict(original, retest), expected)

    def test_g_reasons_name_each_failed_metric(self):
        result = bm.judge_drift(dict(trades=100, pf=1.5, max_dd=100), dict(trades=120, pf=1.2, max_dd=130))
        self.assertEqual([c['metric'] for c in result['checks'] if not c['ok']], ['trades', 'pf', 'max_dd'])
        self.assertEqual((result['delta']['trades_rel'], result['delta']['max_dd_rel']), (0.2, 0.3))

    def test_short_build_and_provenance(self):
        self.assertEqual(bm.provenance('V1.49-BETA17-43'), 'build-migration-retest:B43')
        self.assertEqual(bm.short_build('V1.49-EXPORT-BACK-BOUNDARY-28'), 'B28')
        self.assertEqual(bm.short_build('V1.47'), 'V1.47')
        self.assertTrue(bm.is_record(dict(kind='build_migration_retest')))
        self.assertTrue(bm.is_record(dict(summary=dict(kind='build_migration_retest'))))
        self.assertFalse(bm.is_record(dict(schema='goat-evidence-version-v1', verdict=dict(verdict='held_up'))))


if __name__ == '__main__':
    unittest.main()
