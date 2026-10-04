"""Trial journal and counter (library scoring v1 phase 1, goatai#2221 §5; acceptance #6).

A private synthetic installation with real prepare-batch packages and queue rows shaped
like this PC's journals (attempts/<id>/result.json, native evidence histories,
retired-starts, seeds, catchups) and a desktop strategy library beside the evidence root.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import goat_studio
import studio_evidence_end
import test_goat_studio as fixtures
from campaign_ledger import packed, sha
from studio_batch import prepare_batch
from studio_trial_journal import _oos_output, count, journal
from test_studio_heldout import NOW, NOW_AT, REAL_UTC, declaration, write_registry

ATTEMPT = '1' * 64
RETIRED_ATTEMPT = '2' * 64
SETS = {
    'alpha': 'EA_Desc=Alpha\r\nLots=0.1||0.1||0.1||0.3||Y\r\nMode=1\r\n',      # the catalog template, byte for byte
    'variant': 'EA_Desc=Variant\r\nLots=0.2||0.1||0.1||0.5||Y\r\nMode=1\r\n',  # same non-axis values + axis names
    'gamma': 'EA_Desc=Gamma\r\nLots=0.1||0.1||0.1||0.3||Y\r\nMode=2\r\n',      # named by a v0 record only
    'loose': 'EA_Desc=Loose\r\nLots=0.1||0.1||0.1||0.3||Y\r\nMode=3\r\n',      # nothing knows it
}


def utf16(text):
    return text.encode('utf-16')


class TrialJournalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.desktop = self.fixture.root / 'desktop'
        self.fixture.receipt['evidence_root'] = str(self.desktop / 'evidence')
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        c = self.c = self.fixture.bound()
        c.schema = dict(schema_version=1, source_sha256='a' * 64, inputs={
            'EA_Desc': dict(type='string', optimizable=False), 'Lots': dict(type='double', optimizable=True),
            'Mode': dict(type='int', optimizable=False)})
        c.store.input_schema = c.schema; c.store.input_schema_hash = sha(c.schema)
        self.fixture.grant(c)
        clock = patch('studio_evidence_end._utc', side_effect=lambda now: NOW if now is None else REAL_UTC(now))
        clock.start(); self.addCleanup(clock.stop)
        self.paths = {}
        for name, text in SETS.items():
            self.paths[name] = self.fixture.root / (name + '.set'); self.paths[name].write_bytes(utf16(text))
        self.library()
        self.prepare('tj', ['alpha', 'variant', 'gamma', 'loose', 'alpha'])
        self.prepare('tj-retired', ['alpha'])
        self.dispatch_and_finish()
        self.runners()

    # ---- fixture ---------------------------------------------------------------------------------
    def library(self):
        root = self.desktop / 'strategy-library-1.49'
        alpha = utf16(SETS['alpha']); digest = hashlib.sha256(alpha).hexdigest()
        catalog = root / 'revisions' / 'cat-1'; (catalog / 'templates').mkdir(parents=True)
        (catalog / 'templates' / 'Alpha.set').write_bytes(alpha)
        (catalog / 'catalog.json').write_text(json.dumps(dict(schema='goat-strategy-catalog-v1', revision='cat-1',
            publishedAt='2026-09-26T19:23:52Z', templates=[dict(id='alpha', revision=digest, sha256=digest,
            file='templates/Alpha.set', optimizedAxes=['Lots'])])), encoding='utf-8')
        selection = root / 'selections' / 'sel-1'; selection.mkdir(parents=True)
        (selection / 'receipt.json').write_text(json.dumps(dict(selectionId='sel-1', catalogRevision='cat-1', templates=[
            dict(id='alpha', revision=digest, sha256=digest)])), encoding='utf-8')
        (root / 'results').mkdir()
        (root / 'results' / 'gamma.json').write_text(json.dumps(dict(attemptId=ATTEMPT + '-m2', templateId='gamma',
            templateRevision='rg', templateSha256='f' * 64, catalogRevision='cat-1', artifacts=[], conditions={})), encoding='utf-8')

    def prepare(self, name, sources):
        members = [dict(set_path=str(self.paths[source]), tester=self.fixture.tester | {'Symbol': 'SYM%d' % index})
                   for index, source in enumerate(sources)]
        plan = self.fixture.root / (name + '.json')
        plan.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=members)), encoding='utf-8')
        prepare_batch(self.c, name, plan)

    def rows(self, change):
        state = self.c.state()
        for job in state['queue']:
            change(job)
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.c.store.db.commit()

    def dispatch_and_finish(self):
        statuses = ['native_completed', 'native_error', 'native_cancelled', 'native_error', 'native_cancelled']
        # The EA runs members one after another; member 4 was still queued when the batch was cancelled.
        observed = (['native_ongoing', 'native_pending', 'native_pending', 'native_pending', 'native_pending'],
                    ['native_completed', 'native_error', 'native_ongoing', 'native_pending', 'native_pending'],
                    ['native_completed', 'native_error', 'native_cancelled', 'native_ongoing', 'native_queued'])
        observations = [dict(native=dict(members=[dict(index=i, status=s) for i, s in enumerate(states)])) for states in observed]
        reports = [dict(status='member_not_completed', index=i, native_status=statuses[i]) for i in range(5)]
        reports[0] = dict(status='report_pair_verified', index=0, evidence=dict(paired_rows=159, forward_rows=159, back_rows=200),
                          exports=dict(files=[dict(name='GOAT V1.48 SYM0,M15_Trds=1_Prf=1_DD=1_PF=1.00_SR=1.00_ARF=0.100')],
                                       native_threshold_candidate_count=1))
        job = self.c.job('tj')
        result = dict(schema_version=1, attempt_id=ATTEMPT, job_id='tj', status='cancelled',
                      member_outcomes=[dict(index=i, run_alias='R%020d' % i, status=s, symbol='SYM%d' % i,
                                            input_artifact=dict(sha256='%064x' % (i + 1))) for i, s in enumerate(statuses)],
                      configuration=job['configuration'], configuration_sha256=job['configuration_sha256'],
                      native=dict(observed_at='2026-09-10T12:00:00Z', status='native_cancelled'),
                      reports=dict(status='report_batch_verified', members=reports), research_outcomes=[])
        folder = self.c.root / 'attempts' / ATTEMPT; folder.mkdir(parents=True)
        (folder / 'result.json').write_text(json.dumps(result), encoding='utf-8')

        def change(row):
            if row['job_id'] == 'tj':
                row.update(status='cancelled', launch_intent=dict(attempt_id=ATTEMPT, recorded_at='2026-09-08T09:00:00Z'),
                           native_evidence_history=observations, completion=result,
                           completion_path=str(folder / 'result.json'))
            elif row['job_id'] == 'tj-retired':
                row.update(status='starting', launch_intent=dict(attempt_id=RETIRED_ATTEMPT, recorded_at='2026-09-20T09:00:00Z'),
                           native_observation=dict(dispatch=dict(status='not_issued')))
        self.rows(change)

    def runners(self):
        tester = dict(Symbol='EURUSD', Period='H1', FromDate='2025.06.01', ToDate='2026.06.01', ForwardMode=0, Model=1)
        seed = self.c.root / 'seeds' / 'seed-1'; seed.mkdir(parents=True)
        result = seed / 'S1.result.json'; result.write_text(json.dumps(dict(summary=dict(actual_frames=500))), encoding='utf-8')
        values = dict(EA_Desc='S1@{mode=SeedFarming}', Lots='0.1||0.1||0.1||0.3||Y', Mode='2')
        (seed / 'manifest.json').write_text(json.dumps(dict(batch_id='seed-1', plan={}, members=[
            dict(member_id='s1', index=0, alias='S1', tester=tester, source_sha256='9' * 64, values=values),
            dict(member_id='s2', index=1, alias='S2', tester=tester | dict(Symbol='GBPUSD'), source_sha256='9' * 64, values=values)])),
            encoding='utf-8')
        (seed / 'state.json').write_text(json.dumps(dict(status='active', members=[
            dict(member_id='s1', status='completed', attempts=1, started_unix=1790000000, result=dict(path=str(result))),
            dict(member_id='s2', status='pending', attempts=0)])), encoding='utf-8')
        catchup = self.c.root / 'catchups' / 'cu-1'; catchup.mkdir(parents=True)
        frozen = catchup / 'C1.set'; frozen.write_bytes(utf16('EA_Desc=C1\r\nLots=0.15\r\nMode=1\r\n'))
        (catchup / 'manifest.json').write_text(json.dumps(dict(batch_id='cu-1', plan={}, members=[dict(
            member_id='c1', index=0, alias='C1', set_path=str(frozen), source_sha256=hashlib.sha256(utf16(SETS['alpha'])).hexdigest(),
            tester=dict(Symbol='EURUSD', Period='H1', FromDate='2025.01.01', ToDate='2026.10.03', Model=4),
            new_window=dict(first_day='2026-09-04', last_day='2026-10-02'))])), encoding='utf-8')
        (catchup / 'state.json').write_text(json.dumps(dict(status='completed', members=[
            dict(member_id='c1', status='completed', attempts=1, started_unix=1790500000)])), encoding='utf-8')

    def entries(self, **kwargs):
        return {(e['batch_id'], e['member_index']): e for e in journal(self.c.root, self.c.install, **kwargs)['entries']}

    # ---- tests ---------------------------------------------------------------------------------
    def test_one_entry_per_member_with_spec_fields_and_attribution(self):
        entries = self.entries()
        self.assertEqual(len(entries), 5 + 1 + 2 + 1)
        first = entries[('tj', 0)]
        for key in ('entry_id', 'suite_id', 'source', 'batch_id', 'attempt_id', 'member_index', 'run_alias', 'strategy_ref',
                    'attribution', 'variant_id', 'set_sha256', 'input_artifact_sha256', 'symbol', 'timeframe', 'model', 'windows',
                    'dispatched', 'outcome', 'optimizer_candidates_seen'):
            self.assertIn(key, first)
        self.assertEqual(first['source']['kind'], 'attempt-result')
        self.assertEqual(first['attempt_key'], ATTEMPT + '-m0')
        self.assertEqual([entries[('tj', i)]['attribution'] for i in range(5)],
                         ['selection-receipt', 'fingerprint', 'ledger-record', 'unattributed', 'selection-receipt'])
        self.assertEqual([entries[('tj', i)]['strategy_keys'] for i in range(5)], [['alpha'], ['alpha'], ['gamma'], [], ['alpha']])
        self.assertEqual(first['strategy_ref']['catalog_revision'], 'cat-1')
        self.assertEqual(first['optimizer_candidates_seen'], 159)
        self.assertEqual([w['role'] for w in first['windows']], ['in-sample', 'forward', 'back-oos', 'front-oos'])
        self.assertEqual(first['windows'][3], dict(role='front-oos', start='2026-09-01', end='2026-09-04', end_basis='ea_last_friday_estimate'))
        self.assertEqual(first['exposure'], dict(start='2026-01-01', end='2026-09-04'))
        self.assertNotEqual(entries[('tj', 0)]['variant_id'], entries[('tj', 1)]['variant_id'])
        self.assertEqual(entries[('tj', 0)]['variant_id'], entries[('tj', 4)]['variant_id'])

    def test_failed_and_cancelled_dispatches_count_and_unstarted_ones_do_not(self):
        """Acceptance #6, first half."""
        entries = self.entries()
        expected = {0: (True, 'completed', True), 1: (True, 'failed', True), 2: (True, 'cancelled', True),
                    3: (True, 'failed', True), 4: (False, 'cancelled-before-start', False)}
        for index, (dispatched, outcome, peek) in expected.items():
            entry = entries[('tj', index)]
            self.assertEqual((entry['dispatched'], entry['outcome'], entry['counts_as_peek']), (dispatched, outcome, peek), index)
        retired = entries[('tj-retired', 0)]
        self.assertEqual((retired['dispatched'], retired['outcome'], retired['counts_as_peek']), (False, 'not-dispatched', False))
        seed_done, seed_pending = entries[('seed-1', 0)], entries[('seed-1', 1)]
        self.assertEqual((seed_done['dispatched'], seed_done['counts_as_peek'], seed_done['in_sample_candidates_seen']), (True, False, 500))
        self.assertEqual((seed_pending['dispatched'], seed_pending['outcome']), (False, 'not-dispatched'))
        catchup = entries[('cu-1', 0)]
        self.assertEqual((catchup['kind'], catchup['windows'], catchup['counts_as_peek']),
                         ('catch-up', [dict(role='catch-up', start='2026-09-04', end='2026-10-03')], True))

    def test_retirement_and_compaction_leave_the_journal_byte_identical(self):
        """Acceptance #6, second half: retire-unactivated, then compact-evidence --apply."""
        before = json.dumps(journal(self.c.root, self.c.install), sort_keys=True)
        retired = dict(schema_version=1, kind='retired_never_activated', status='cancelled', job_id='tj-retired',
                       attempt_id=RETIRED_ATTEMPT, member_count=1, executed_members=0, native_cancellation_claimed=False)
        folder = self.c.root / 'retired-starts'; folder.mkdir()
        (folder / ('tj-retired-' + RETIRED_ATTEMPT[:16] + '.json')).write_text(json.dumps(retired), encoding='utf-8')
        self.rows(lambda row: row.update(status='cancelled', completion=retired) if row['job_id'] == 'tj-retired' else None)
        self.assertEqual(json.dumps(journal(self.c.root, self.c.install), sort_keys=True), before)
        from studio_evidence_log import compact
        done = compact(self.c, apply=True)
        self.assertTrue(done['applied'])
        self.assertIn('native_evidence_archive', self.c.job('tj'))
        self.assertNotIn('native_evidence_history', self.c.job('tj'))
        self.assertEqual(json.dumps(journal(self.c.root, self.c.install), sort_keys=True), before)

    def test_a_member_whose_start_cannot_be_proven_counts(self):
        self.rows(lambda row: row.pop('native_evidence_history', None) if row['job_id'] == 'tj' else None)
        entry = self.entries()[('tj', 4)]
        self.assertEqual((entry['dispatched'], entry['outcome'], entry['counts_as_peek']), (True, 'cancelled', True))
        self.assertIn('member start unknown: no retained native evidence history, counted as dispatched', entry['gaps'])

    def test_no_oos_output_needs_proof_from_the_journal(self):
        proven = dict(status='member_not_completed', evidence=dict(paired_rows=0, forward_rows=0))
        self.assertEqual(_oos_output(proven, None, 'R1', []), 'proven_absent')
        self.assertEqual(_oos_output(dict(status='member_not_completed'), None, 'R1', []), 'possible')
        self.assertEqual(_oos_output(proven, dict(forward_rows=12), 'R1', []), 'possible')
        self.assertEqual(_oos_output(proven, None, 'R1', ['GOAT: R1 (best 61.7)']), 'possible')
        self.assertEqual(_oos_output(dict(proven, evidence=dict(paired_rows=3, forward_rows=0)), None, 'R1', []), 'possible')

    def test_trial_count_per_strategy_window_and_cell(self):
        counted = count(self.c.root, self.c.install, 'alpha')
        self.assertEqual(counted['strategy'], dict(peeks=3, variants=3, optimizer_candidates_seen=159, not_dispatched=2))
        windows = {(w['start'], w['end']): w for w in counted['windows']}
        self.assertEqual(sorted(windows), [('2026-01-01', '2026-02-01'), ('2026-07-01', '2026-09-01'),
                                           ('2026-09-01', '2026-09-04'), ('2026-09-04', '2026-10-03')])
        forward = windows[('2026-07-01', '2026-09-01')]
        self.assertEqual((forward['peeks'], forward['variants'], forward['reconstructable'], forward['worst_case']), (2, 2, False, True))
        self.assertEqual(forward['worst_case_rule']['trial_worst_case_n'], 1000)
        self.assertIn('1 unattributed dispatched member(s) on SYM3 overlap this window', forward['gaps'])
        catchup = windows[('2026-09-04', '2026-10-03')]
        self.assertEqual((catchup['peeks'], catchup['reconstructable']), (1, True))
        self.assertEqual((counted['reconstructable'], counted['worst_case']), (False, True))
        self.assertEqual(counted['exposure_end'], '2026-10-03')
        cells = {(c['symbol'], c['timeframe']): c for c in counted['cells']}
        self.assertFalse(cells[('SYM3', 'M15')]['reconstructable'])
        self.assertEqual(cells[('SYM4', 'M15')]['not_dispatched'], 1)
        one = count(self.c.root, self.c.install, 'alpha', window=(datetime(2026, 9, 4).date(), datetime(2026, 10, 3).date()))
        self.assertEqual((one['strategy']['peeks'], one['windows'][0]['reconstructable']), (1, True))
        gamma = count(self.c.root, self.c.install, 'gamma')
        self.assertEqual(gamma['strategy']['peeks'], 1)

    def test_ambiguous_fingerprint_stays_unattributed(self):
        root = self.desktop / 'strategy-library-1.49' / 'revisions' / 'cat-2'; (root / 'templates').mkdir(parents=True)
        twin = utf16('EA_Desc=Twin\r\nLots=0.3||0.1||0.1||0.9||Y\r\nMode=1\r\n')
        (root / 'templates' / 'Twin.set').write_bytes(twin)
        (root / 'catalog.json').write_text(json.dumps(dict(revision='cat-2', templates=[dict(
            id='twin', revision='rt', sha256=hashlib.sha256(twin).hexdigest(), file='templates/Twin.set')])), encoding='utf-8')
        self.assertEqual(self.entries()[('tj', 1)]['attribution'], 'unattributed')

    def test_cli_filters_and_redacts_a_locked_entrys_outcome(self):
        def cli(*args):
            output = io.StringIO()
            with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), redirect_stdout(output):
                self.assertEqual(goat_studio.main(['--installation', str(self.fixture.path), *args]), 0)
            return json.loads(output.getvalue())['result']
        whole = cli('trial-journal')
        self.assertEqual(len(whole['entries']), 9)
        gamma = cli('trial-journal', '--strategy', 'gamma')      # unattributed members count for every key
        self.assertEqual({(e['batch_id'], e['member_index']) for e in gamma['entries']},
                         {('tj', 2), ('tj', 3), ('seed-1', 0), ('seed-1', 1)})
        since = cli('trial-journal', '--since', '2026-09-09T00:00:00Z')
        self.assertNotIn(('tj', 0), {(e['batch_id'], e['member_index']) for e in since['entries']})
        counted = cli('trial-count', '--strategy', 'alpha', '--window-start', '2026-09-04', '--window-end', '2026-10-03')
        self.assertEqual(counted['strategy']['peeks'], 1)
        write_registry(self.desktop / 'evidence', [('declare', declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30'), NOW_AT)])
        locked = {(e['batch_id'], e['member_index']): e for e in cli('trial-journal')['entries']}
        self.assertEqual(locked[('tj', 0)]['outcome']['locked'], True)
        self.assertEqual(locked[('tj', 0)]['optimizer_candidates_seen']['locked'], True)
        self.assertEqual(locked[('tj', 0)]['windows'], whole['entries'][0]['windows'])   # the counter keeps its dates
        self.assertEqual(locked[('seed-1', 0)]['outcome'], 'completed')                  # ends before the lock


if __name__ == '__main__':
    unittest.main()
