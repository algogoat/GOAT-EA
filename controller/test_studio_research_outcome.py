"""Members tested with no profitable or no qualifying settings are research results for their window, never failures.

The EA keeps their native queue status ``Error`` (no wire change) and writes one
``NoProfitablePasses`` row to ``item_stats.tsv``. These fixtures replay the g6
shape: USDCAD M1, 175 passes, none profitable, best -1,261.09, score 0.05.

``NoQualifyingRows`` rows replay the Banker g6-r1b shape (EX33): 158 passes, 7
profitable with 50+ trades, forward report merged (151 discarded), best combined
score 48.1 below the export score 60. Before, the combine logged ``No Rows!``
and the member was counted as failed.
"""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_pause as pause
from studio_batch import resume_batch
from studio_finish import _research_outcomes
from studio_research_status import (ITEM_STATS_HEADER, batch_progress, end_state, headline, item_outcomes, no_edge_members,
                                    no_edge_summary, pace, research_status)
import test_studio_batch_pause as pause_fixtures

NOW = 1_800_000_000
DETAILS = ('outcome=no_profitable_passes;passes=175;profitable=0;traded=175;malformed=0;complete=1;forward_rows=175;'
           'best_profit=-1261.09;best_score=0.0500;min_trades=50;'
           'window_start=2024.01.08;window_end=2025.01.06;forward_end=2025.03.15')
QDETAILS = ('outcome=no_qualifying_rows;passes=158;profitable=7;traded=158;malformed=0;complete=1;forward_rows=158;'
            'best_profit=660.00;best_score=0.5600;min_trades=50;'
            'window_start=2024.01.08;window_end=2025.01.06;forward_end=2025.03.15;'
            'back_rows=7;forward_matched=7;forward_discarded=151;forward_mismatches=0;forward_malformed=0;'
            'best_combined_score=48.1;score_threshold=60.0')
TIMING = dict(started={0: NOW - 3600, 1: NOW - 3600, 2: NOW - 3600}, ended={}, outcome={})


def local(epoch):
    return time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(epoch))


def stats_row(alias, symbol, *, at=NOW - 600, status='NoProfitablePasses', details=DETAILS):
    return '\t'.join([local(at), symbol, alias, status, '0', '0', '0.0', '0', details])


def q_row(alias, symbol, *, at=NOW - 600, details=QDETAILS):
    return '\t'.join([local(at), symbol, alias, 'NoQualifyingRows', '7', '0', '48.1', '0', details])


def write_stats(folder, rows, *, encoding='utf-16'):
    text = '\r\n'.join([ITEM_STATS_HEADER] + rows) + '\r\n'
    Path(folder, 'item_stats.tsv').write_bytes(text.encode(encoding))


def write_timeline(folder, events):
    rows = ['LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails']
    rows += ['\t'.join([local(at), local(at), 'QUEUE_STATE', status + '_x:' + alias, status, '']) for alias, status, at in events]
    Path(folder, 'timeline.tsv').write_text('\n'.join(rows) + '\n', encoding='utf-8')


class ItemStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.members = [('A0', 'USDCAD'), ('A1', 'USDCHF'), ('A2', 'EURUSD')]

    def test_g6_row_is_read_with_its_window_and_numbers(self):
        write_stats(self.run, [stats_row('A0', 'USDCAD')])
        found = item_outcomes(self.run, self.members, TIMING)
        self.assertEqual(list(found), [0])
        outcome = found[0]
        self.assertEqual((outcome['traded'], outcome['malformed'], outcome['complete'], outcome['forward_rows']), (175, 0, '1', 175))
        self.assertEqual((outcome['outcome'], outcome['passes'], outcome['profitable'], outcome['best_profit'], outcome['best_score']),
                         ('no_profitable_passes', 175, 0, -1261.09, 0.05))
        self.assertEqual(outcome['window'], dict(start='2024.01.08', end='2025.01.06', forward_end='2025.03.15'))

    def test_only_matching_alias_symbol_and_well_formed_rows_count(self):
        write_stats(self.run, [
            stats_row('A0', 'USDJPY'),                                      # same alias, other symbol
            stats_row('A9', 'USDCAD'),                                      # unknown alias
            stats_row('A1', 'USDCHF', status='Completed'),                  # an ordinary completed item
            stats_row('A2', 'EURUSD', details=DETAILS.replace('passes=175', 'passes=0')),
            stats_row('A2', 'EURUSD', details=DETAILS.replace('window_end=2025.01.06', 'window_end=2026.01.06')),
            stats_row('A2', 'EURUSD', details=DETAILS.replace('outcome=no_profitable_passes', 'outcome=other')),
            stats_row('A2', 'EURUSD', details=DETAILS.replace('profitable=0', 'profitable=900')),
            stats_row('A2', 'EURUSD', details='outcome=no_profitable_passes'),
        ])
        self.assertEqual(item_outcomes(self.run, self.members, TIMING), {})

    def test_mirrors_the_ea_guard_never_traded_unreadable_or_partial_stays_an_error(self):
        """Review HIGH/MEDIUM: only proof of trading and a whole report make a no-edge result."""
        for label, details in [
                ('no pass traded (EA never traded)', DETAILS.replace('traded=175', 'traded=0')),
                ('more traded passes than passes', DETAILS.replace('traded=175', 'traded=176')),
                ('a row did not parse', DETAILS.replace('malformed=0', 'malformed=3')),
                ('results table never closed', DETAILS.replace('complete=1', 'complete=0')),
                ('forward report empty or unreadable', DETAILS.replace('forward_rows=175', 'forward_rows=0')),
                ('forward rows exceed passes', DETAILS.replace('forward_rows=175', 'forward_rows=176')),
                ('no losses yet best profit is positive', DETAILS.replace('best_profit=-1261.09', 'best_profit=12.00')),
                ('older build without trade proof', DETAILS.replace('traded=175;malformed=0;complete=1;forward_rows=175;', ''))]:
            with self.subTest(label):
                write_stats(self.run, [stats_row('A0', 'USDCAD', details=details)])
                self.assertEqual(item_outcomes(self.run, self.members, TIMING), {}, label)
        write_stats(self.run, [stats_row('A0', 'USDCAD', details=DETAILS.replace('traded=175', 'traded=1'))])
        self.assertEqual(list(item_outcomes(self.run, self.members, TIMING)), [0], 'one traded pass is enough proof')

    def test_without_timeline_evidence_nothing_is_relabelled(self):
        write_stats(self.run, [stats_row('A0', 'USDCAD')])
        self.assertEqual(item_outcomes(self.run, self.members), {})
        self.assertEqual(item_outcomes(self.run, self.members, dict(started={1: NOW - 3600})), {})

    def test_a_row_from_an_older_attempt_never_relabels_a_later_failure(self):
        write_stats(self.run, [stats_row('A0', 'USDCAD', at=NOW - 3000)])
        write_timeline(self.run, [('A0', 'OnGoing', NOW - 3600), ('A0', 'Error', NOW - 2990), ('A0', 'OnGoing', NOW - 1200),
                                  ('A0', 'Error', NOW - 600)])
        from studio_research_status import timeline
        timing = timeline(self.run, ['A0', 'A1', 'A2'])
        self.assertEqual(item_outcomes(self.run, self.members, timing), {})
        write_stats(self.run, [stats_row('A0', 'USDCAD', at=NOW - 3000), stats_row('A0', 'USDCAD', at=NOW - 605)])
        self.assertEqual(list(item_outcomes(self.run, self.members, timing)), [0])

    def test_missing_unreadable_or_foreign_files_are_unknown_not_errors(self):
        self.assertEqual(item_outcomes(self.run, self.members, TIMING), {})
        Path(self.run, 'item_stats.tsv').write_bytes(b'\xff\xfe\x00')
        self.assertEqual(item_outcomes(self.run, self.members, TIMING), {})
        Path(self.run, 'item_stats.tsv').write_text('Other\theader\n' + stats_row('A0', 'USDCAD'), encoding='utf-8')
        self.assertEqual(item_outcomes(self.run, self.members, TIMING), {})
        write_stats(self.run, [stats_row('A0', 'USDCAD')], encoding='utf-8-sig')
        self.assertEqual(list(item_outcomes(self.run, self.members, TIMING)), [0])

    def test_only_native_error_members_are_relabelled(self):
        write_stats(self.run, [stats_row('A0', 'USDCAD'), stats_row('A1', 'USDCHF')])
        found = no_edge_members(self.run, self.members, ['native_error', 'native_completed', 'native_error'], TIMING)
        self.assertEqual(list(found), [0])

    def test_summary_states_the_window_and_is_not_a_verdict(self):
        write_stats(self.run, [stats_row('A0', 'USDCAD', details=DETAILS.replace('profitable=0', 'profitable=3'))])
        text = no_edge_summary('USDCAD', 'M1', item_outcomes(self.run, self.members, TIMING)[0])
        self.assertEqual(text, 'USDCAD M1: tested, no edge in 2024.01.08 to 2025.01.06 — 175 settings, none profitable '
                               'with 50+ trades (3 profitable on fewer trades), best profit -1,261.09. '
                               'A result for this window only, not a verdict on the strategy.')
        self.assertNotIn('never', text.lower())


class ProgressTests(unittest.TestCase):
    """research-status over a real package manifest, timeline and item_stats; the queue is simulated."""
    SYMBOLS = ('EURUSD', 'USDCAD', 'USDCHF', 'NZDUSD')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'state'; self.common = base / 'common'
        self.aliases = ['R' + str(i) * 20 for i in range(len(self.SYMBOLS))]
        package = self.root / 'packages' / 'g6'; package.mkdir(parents=True)
        jobs = [dict(run_alias=alias, tester=dict(Symbol=symbol, Period='M1')) for alias, symbol in zip(self.aliases, self.SYMBOLS)]
        write_json(package / 'manifest.json', dict(native_run_relative='GOAT\\Rabcdef012345', jobs=jobs))
        self.run = self.common / 'GOAT' / 'Rabcdef012345'; self.run.mkdir(parents=True)
        self.install = dict(common_files_root=str(self.common))
        self.job = dict(job_id='g6', launch_intent={}, configuration=dict(batch_members=[{}] * len(self.SYMBOLS)))
        # Every member started an hour ago (the EA's QUEUE_STATE OnGoing evidence).
        write_timeline(self.run, [(alias, 'OnGoing', NOW - 3600) for alias in self.aliases])

    def progress(self, statuses, now=NOW):
        native = dict(status='native_ongoing' if 'native_ongoing' in statuses else 'native_error',
                      members=[dict(status=s) for s in statuses], completed_count=statuses.count('native_completed'),
                      finished_count=sum(s in ('native_completed', 'native_error', 'native_cancelled') for s in statuses),
                      status_counts={s: statuses.count(s) for s in set(statuses)})
        with patch('studio_native_observe.observe', return_value=native):
            return batch_progress(self.root, self.install, self.job, now=now, journal=dict(started_wall=now - 4 * 600))

    def finish_member(self, index, status, start, end):
        return [(self.aliases[index], 'OnGoing', start), (self.aliases[index], status, end)]

    def test_g6_shape_reports_no_edge_apart_from_failures_with_the_window(self):
        events = []
        for index, status in enumerate(['Completed', 'Error', 'Error']):
            events += self.finish_member(index, status, NOW - 2400 + index * 600, NOW - 1800 + index * 600)
        events.append((self.aliases[3], 'OnGoing', NOW - 300))
        write_timeline(self.run, events)
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD', at=NOW - 1220), stats_row(self.aliases[2], 'USDCHF', at=NOW - 620)])
        folder = self.run / 'deploy' / self.aliases[0] / 'EURUSD'; folder.mkdir(parents=True)
        (self.run / 'export_settings.GOAT').write_text('[Export]\nMinARF=0.2\nMinSR=2.5\n', encoding='utf-8')
        (folder / 'GOAT V1.49 EURUSD,M1_Trds=406_Prf=278_DD=91_PF=1.57_SR=2.92_ARF=0.315.set').write_text('x')
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_ongoing'])
        self.assertEqual((value['members_done'], value['qualifying'], value['members_no_edge'], value['members_failed']), (1, 1, 2, 0))
        self.assertEqual(value['no_edge_window'], dict(start='2024.01.08', end='2025.01.06'))
        self.assertEqual([item['symbol'] for item in value['no_edge']], ['USDCAD', 'USDCHF'])
        self.assertIn('tested, no edge in 2024.01.08 to 2025.01.06', value['no_edge'][0]['summary'])
        last = value['last_member']
        self.assertEqual((last['symbol'], last['status'], last['qualifies']), ('USDCHF', 'no_profitable_passes', False))
        self.assertIn('not a verdict on the strategy', last['summary'])
        # Pace counts all three tested members, so the ETA is not inflated by "errors".
        self.assertEqual(value['pace']['minutes_per_member'], 10.0)
        activity = dict(kind='batch', status='running', **value, _now=NOW)
        self.assertEqual(headline(activity), 'Running on NZDUSD M1; 1 of 4 members done, 1 qualifying (SR ≥ 2.5, ARF ≥ 0.2), '
                                             '2 tested with no edge in 2024.01.08 to 2025.01.06, about 5 min left.')

    def test_a_real_error_stays_a_failure(self):
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD')])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual((value['members_no_edge'], value['members_failed']), (1, 2))
        text = headline(dict(kind='batch', status='failed', **value))
        self.assertTrue(text.startswith('Batch failed;'), text)
        self.assertIn('1 tested with no edge in 2024.01.08 to 2025.01.06, 2 failed', text)

    def test_finished_batch_whose_only_errors_are_no_edge_reads_finished(self):
        write_stats(self.run, [stats_row(alias, symbol) for alias, symbol in zip(self.aliases[1:], self.SYMBOLS[1:])])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual(headline(dict(kind='batch', status='failed', **value)),
                         'Batch finished; 1 of 4 members done, 0 qualifying, 3 tested with no edge in 2024.01.08 to 2025.01.06.')

    def test_cancelled_members_are_named_and_never_called_finished(self):
        """Review MEDIUM: one no-edge member plus two cancelled ones stopped early."""
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD')])
        value = self.progress(['native_cancelled', 'native_error', 'native_cancelled', 'native_completed'])
        self.assertEqual(value['members_cancelled'], 2)
        self.assertEqual(headline(dict(kind='batch', status='failed', **value)),
                         'Batch stopped early; 1 of 4 members done, 0 qualifying, 1 tested with no edge in '
                         '2024.01.08 to 2025.01.06, 2 cancelled.')
        paused = headline(dict(kind='batch', status='paused', **value))
        self.assertNotIn('cancelled', paused)   # a pause cancels the rest by design

    def test_different_windows_are_never_merged_into_one(self):
        other = DETAILS.replace('window_start=2024.01.08', 'window_start=2023.06.01')
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD'), stats_row(self.aliases[2], 'USDCHF', details=other)])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_pending'])
        self.assertIsNone(value['no_edge_window'])
        self.assertIn('2 tested with no edge in their test window', headline(dict(kind='batch', status='running', **value)))

    def test_without_item_stats_nothing_changes(self):
        value = self.progress(['native_completed', 'native_error', 'native_pending', 'native_pending'])
        self.assertEqual((value['members_no_edge'], value['members_failed'], value['no_edge']), (0, 1, []))
        self.assertEqual(pace(None, ['native_completed', 'native_error', 'native_pending'], now=NOW, fallback_started=NOW - 3600)['minutes_per_member'], 60.0)
        self.assertEqual(pace(None, ['native_completed', 'native_error', 'native_pending'], now=NOW, fallback_started=NOW - 3600,
                              tested={1})['minutes_per_member'], 30.0)

    # goatai#1885: a finished batch whose members ended native_error read "failed", then the
    # status fell back to its older parent's pause and the watcher reported "paused".
    def test_end_state_tells_finished_with_errors_from_failed(self):
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD')])
        finished = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual((finished['members_failed'], finished['members_no_edge'], finished['members_native_error']), (2, 1, 3))
        self.assertEqual(end_state('failed', finished), 'finished_with_errors')
        self.assertEqual(headline(dict(kind='batch', status='finished_with_errors', **finished)),
                         'Batch finished with errors; 1 of 4 members done, 0 qualifying, 1 tested with no edge in '
                         '2024.01.08 to 2025.01.06, 2 failed.')
        self.assertEqual(end_state('completed', finished), 'finished_with_errors')
        # Members never reached an end, or some were cancelled: the batch really failed / stopped early.
        for statuses in (['native_completed', 'native_error', 'native_pending', 'native_pending'],
                         ['native_completed', 'native_error', 'native_cancelled', 'native_cancelled']):
            with self.subTest(statuses=statuses):
                self.assertEqual(end_state('failed', self.progress(statuses)), 'failed')
        # Native evidence unreadable: never relabelled.
        self.assertEqual(end_state('failed', dict(finished, evidence='native_unreadable')), 'failed')
        # Only no-edge errors: finished, with no failures.
        write_stats(self.run, [stats_row(alias, symbol) for alias, symbol in zip(self.aliases[1:], self.SYMBOLS[1:])])
        no_edge = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual(end_state('failed', no_edge), 'finished')
        self.assertEqual(headline(dict(kind='batch', status='finished', **no_edge)),
                         'Batch finished; 1 of 4 members done, 0 qualifying, 3 tested with no edge in 2024.01.08 to 2025.01.06.')
        clean = self.progress(['native_completed'] * 4)
        self.assertEqual(end_state('completed', clean), 'completed')

    def status(self, jobs, statuses):
        install = dict(common_files_root=str(self.common), terminal_data_root=str(self.root.parent / 'data'),
                       terminal_executable='terminal64.exe', ea_version='1.49', ea_sha256='e' * 64)
        session = dict(run_id='r', terminal_id='t', account=dict(login='1', server='Demo'))
        native = dict(status='native_error', members=[dict(status=s) for s in statuses],
                      completed_count=statuses.count('native_completed'),
                      finished_count=sum(s in ('native_completed', 'native_error', 'native_cancelled') for s in statuses),
                      status_counts={s: statuses.count(s) for s in set(statuses)})
        with patch('studio_native_observe.observe', return_value=native):
            return research_status(root=self.root, install=install, session=session, local=self.root / 'local', now=NOW,
                                   process=None, jobs=jobs)['activity']

    def paused_parent(self, successor='g6'):
        record = dict(schema_version=pause.SCHEMA_VERSION, job_id='g5', pause_id='p1', state='paused', phase='paused',
                      successor_batch_id=successor, members_completed=2, members_remaining=4)
        (self.root / pause.FOLDER).mkdir(exist_ok=True)
        write_json(self.root / pause.FOLDER / 'g5.json', record)
        return dict(job_id='g5', status='cancelled', launch_intent={}, configuration=dict(batch_members=[{}] * 6))

    def test_newer_finished_batch_is_never_reported_as_its_parents_pause(self):
        write_stats(self.run, [stats_row(self.aliases[1], 'USDCAD')])
        statuses = ['native_completed', 'native_error', 'native_error', 'native_error']
        activity = self.status([self.paused_parent(), dict(self.job, status='failed')], statuses)
        self.assertEqual((activity['batch_id'], activity['status'], activity['queue_status']), ('g6', 'finished_with_errors', 'failed'))
        self.assertIsNone(activity['pause'])
        self.assertTrue(activity['headline'].startswith('Batch finished with errors; 1 of 4 members done'), activity['headline'])
        self.assertNotIn('aused', activity['headline'])
        # A batch that stopped with members left still reads failed, and still not paused.
        activity = self.status([self.paused_parent(), dict(self.job, status='failed')],
                               ['native_completed', 'native_error', 'native_pending', 'native_pending'])
        self.assertEqual((activity['batch_id'], activity['status']), ('g6', 'failed'))
        self.assertEqual(activity['headline'], 'Batch failed; 1 of 4 members done, 0 qualifying, 1 tested with no edge in '
                                               '2024.01.08 to 2025.01.06, 2 never ran.')

    def test_pause_still_shows_while_it_is_the_latest_work(self):
        # Successor prepared but never started: the parent's pause is the current state.
        pending = dict(job_id='g6', status='pending', configuration=dict(batch_members=[{}] * 4))
        activity = self.status([self.paused_parent(), pending], ['native_pending'] * 4)
        self.assertEqual((activity['batch_id'], activity['status']), ('g5', 'paused'))
        self.assertIn('Resume continues', activity['headline'])
        # Alone, the paused batch is current too.
        activity = self.status([self.paused_parent(successor=None)], ['native_pending'] * 4)
        self.assertEqual((activity['batch_id'], activity['status']), ('g5', 'paused'))


class FinishTests(unittest.TestCase):
    def test_finish_records_no_edge_members_for_the_scoreboard(self):
        with tempfile.TemporaryDirectory() as folder:
            write_stats(folder, [stats_row('A1', 'USDCAD')])
            write_timeline(folder, [('A0', 'OnGoing', NOW - 3600), ('A1', 'OnGoing', NOW - 3600)])
            members = [dict(run_alias='A0', symbol='EURUSD', status='native_completed', tester=dict(Period='M1')),
                       dict(run_alias='A1', symbol='USDCAD', status='native_error', tester=dict(Period='M1'))]
            outcomes, error = _research_outcomes(dict(native_run=folder, members=members))
        self.assertIsNone(error)
        self.assertEqual([(o['index'], o['run_alias'], o['outcome'], o['passes']) for o in outcomes], [(1, 'A1', 'no_profitable_passes', 175)])
        self.assertIn('not a verdict', outcomes[0]['summary'])
        self.assertEqual(_research_outcomes(dict(members=members))[0], [])  # unreadable evidence never blocks finish

    def test_finish_writes_the_outcomes_into_the_retained_result(self):
        source = Path(__file__).with_name('studio_finish.py').read_text(encoding='utf-8')
        self.assertLess(source.index("result['research_outcomes']=research_outcomes"), source.index("write_json(result_path,result)"))


class NoQualifyingRowsItemStatsTests(unittest.TestCase):
    """Kept profitable passes, none scoring 60+ with the forward period: a result, never a failure."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.members = [('A0', 'USDCAD'), ('A1', 'USDCHF'), ('A2', 'EURUSD')]

    def read(self, details, status='NoQualifyingRows'):
        row = q_row('A0', 'USDCAD', details=details) if status == 'NoQualifyingRows' else stats_row('A0', 'USDCAD', status=status, details=details)
        write_stats(self.run, [row])
        return item_outcomes(self.run, self.members, TIMING)

    def test_banker_row_is_read_with_its_forward_evidence(self):
        found = self.read(QDETAILS)
        self.assertEqual(list(found), [0])
        outcome = found[0]
        self.assertEqual((outcome['outcome'], outcome['passes'], outcome['profitable'], outcome['back_rows']),
                         ('no_qualifying_rows', 158, 7, 7))
        self.assertEqual((outcome['forward_rows'], outcome['forward_matched'], outcome['forward_discarded']), (158, 7, 151))
        self.assertEqual((outcome['best_combined_score'], outcome['score_threshold']), (48.1, 60.0))
        self.assertEqual(outcome['window'], dict(start='2024.01.08', end='2025.01.06', forward_end='2025.03.15'))

    def test_status_and_outcome_must_agree(self):
        self.assertEqual(self.read(QDETAILS, status='NoProfitablePasses'), {})
        self.assertEqual(self.read(DETAILS), {}, 'a NoQualifyingRows row without forward evidence')
        self.assertEqual(self.read(QDETAILS.replace('outcome=no_qualifying_rows', 'outcome=no_profitable_passes')), {},
                         'a no_profitable_passes outcome under the NoQualifyingRows status')
        self.assertEqual(self.read(QDETAILS, status='Error'), {})

    def test_mirrors_the_ea_guard_real_failures_stay_errors(self):
        for label, details in [
                ('nothing kept (that is no_profitable_passes)',
                 QDETAILS.replace('back_rows=7', 'back_rows=0').replace('forward_matched=7', 'forward_matched=0')
                 .replace('forward_discarded=151', 'forward_discarded=158')),
                ('more kept than profitable', QDETAILS.replace('back_rows=7', 'back_rows=8').replace('forward_matched=7', 'forward_matched=8')
                 .replace('forward_discarded=151', 'forward_discarded=150')),
                ('more profitable than passes', QDETAILS.replace('profitable=7', 'profitable=159')),
                ('kept passes did not trade', QDETAILS.replace('traded=158', 'traded=6')),
                ('more traded than passes', QDETAILS.replace('traded=158', 'traded=159')),
                ('a back row did not parse', QDETAILS.replace('malformed=0;complete', 'malformed=1;complete')),
                ('back table never closed', QDETAILS.replace('complete=1', 'complete=0')),
                ('forward report empty or unreadable', QDETAILS.replace('forward_rows=158', 'forward_rows=0')),
                ('forward rows exceed passes', QDETAILS.replace('forward_rows=158', 'forward_rows=159').replace('forward_discarded=151', 'forward_discarded=152')),
                ('a kept pass missing from the forward report', QDETAILS.replace('forward_matched=7', 'forward_matched=6')
                 .replace('forward_discarded=151', 'forward_discarded=152')),
                ('forward disagrees with back', QDETAILS.replace('forward_mismatches=0', 'forward_mismatches=1')),
                ('a forward row did not parse', QDETAILS.replace('forward_malformed=0', 'forward_malformed=2')),
                ('discarded count inconsistent', QDETAILS.replace('forward_discarded=151', 'forward_discarded=150')),
                ('best score reaches the threshold', QDETAILS.replace('best_combined_score=48.1', 'best_combined_score=60.0')),
                ('best score above the threshold', QDETAILS.replace('best_combined_score=48.1', 'best_combined_score=72.5')),
                ('negative score', QDETAILS.replace('best_combined_score=48.1', 'best_combined_score=-1.0')),
                ('score not a number', QDETAILS.replace('best_combined_score=48.1', 'best_combined_score=nan')),
                ('no threshold', QDETAILS.replace('score_threshold=60.0', 'score_threshold=0.0')),
                ('unbounded threshold', QDETAILS.replace('score_threshold=60.0', 'score_threshold=inf')),
                ('kept passes yet no profit', QDETAILS.replace('best_profit=660.00', 'best_profit=-5.00')),
                ('window out of order', QDETAILS.replace('window_end=2025.01.06', 'window_end=2026.01.06')),
                ('older build without forward evidence', QDETAILS.split(';back_rows=')[0])]:
            with self.subTest(label):
                self.assertEqual(self.read(details), {}, label)

    def test_summary_says_what_was_kept_and_how_far_it_fell_short(self):
        text = no_edge_summary('USDCAD', 'M1', self.read(QDETAILS)[0])
        self.assertEqual(text, 'USDCAD M1: tested, nothing qualified in 2024.01.08 to 2025.01.06 — 158 settings, 7 were profitable '
                               'with 50+ trades but none scored 60+ once the forward period to 2025.03.15 was included (best 48.1). '
                               'A result for this window only, not a verdict on the strategy.')
        one = self.read(QDETAILS.replace('profitable=7', 'profitable=1').replace('back_rows=7', 'back_rows=1')
                        .replace('forward_matched=7', 'forward_matched=1').replace('forward_discarded=151', 'forward_discarded=157'))
        self.assertIn('1 was profitable', no_edge_summary('USDCAD', 'M1', one[0]))
        self.assertNotIn('scored zero', text)
        zero = self.read(QDETAILS.replace('best_combined_score=48.1', 'best_combined_score=0.0'))
        self.assertIn('(best 0.0: the forward period scored zero). A result', no_edge_summary('USDCAD', 'M1', zero[0]))

    def test_unreadable_score_cells_carried_by_the_ea_stay_errors(self):
        """Codex P1 mirror: the EA counts an unreadable PF/RF/SR/profit/trades cell as malformed."""
        for details in (QDETAILS.replace('malformed=0;complete', 'malformed=1;complete'),
                        QDETAILS.replace('forward_malformed=0', 'forward_malformed=1')):
            self.assertEqual(self.read(details), {})


class NoQualifyingRowsProgressTests(unittest.TestCase):
    # The ProgressTests fixture, without re-running its tests.
    SYMBOLS, setUp, progress, finish_member = ProgressTests.SYMBOLS, ProgressTests.setUp, ProgressTests.progress, ProgressTests.finish_member

    def test_banker_shape_counts_nothing_qualified_with_no_edge_apart_from_failures(self):
        events = []
        for index, status in enumerate(['Completed', 'Error', 'Error', 'Error']):
            events += self.finish_member(index, status, NOW - 2400 + index * 600, NOW - 1800 + index * 600)
        write_timeline(self.run, events)
        # Member 1: nothing qualified; member 2: no profitable passes; member 3: a real Error (no row).
        write_stats(self.run, [q_row(self.aliases[1], 'USDCAD', at=NOW - 1220), stats_row(self.aliases[2], 'USDCHF', at=NOW - 620)])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual((value['members_no_edge'], value['members_failed']), (2, 1))
        self.assertEqual([(item['symbol'], item['outcome']) for item in value['no_edge']],
                         [('USDCAD', 'no_qualifying_rows'), ('USDCHF', 'no_profitable_passes')])
        self.assertIn('tested, nothing qualified in 2024.01.08 to 2025.01.06', value['no_edge'][0]['summary'])
        text = headline(dict(kind='batch', status='failed', **value))
        self.assertTrue(text.startswith('Batch failed;'), text)
        self.assertIn('2 tested, nothing qualified in 2024.01.08 to 2025.01.06 (1 with no profitable settings, '
                      '1 none scored 60+ once the forward period was included), 1 failed', text)
        self.assertEqual(value['no_edge_counts'], dict(no_profitable_passes=1, no_qualifying_rows=1))

    def test_last_member_names_the_outcome(self):
        events = self.finish_member(0, 'Completed', NOW - 2400, NOW - 1800) + self.finish_member(1, 'Error', NOW - 1800, NOW - 1200)
        write_timeline(self.run, events)
        write_stats(self.run, [q_row(self.aliases[1], 'USDCAD', at=NOW - 1220)])
        value = self.progress(['native_completed', 'native_error', 'native_pending', 'native_pending'])
        last = value['last_member']
        self.assertEqual((last['symbol'], last['status'], last['qualifies']), ('USDCAD', 'no_qualifying_rows', False))
        self.assertIn('none scored 60+', last['summary'])

    def test_only_errors_are_nothing_qualified_reads_finished(self):
        write_stats(self.run, [q_row(alias, symbol) for alias, symbol in zip(self.aliases[1:], self.SYMBOLS[1:])])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual(headline(dict(kind='batch', status='failed', **value)),
                         'Batch finished; 1 of 4 members done, 0 qualifying, 3 tested, nothing qualified in 2024.01.08 to 2025.01.06 '
                         '(3 none scored 60+ once the forward period was included).')

    def test_a_real_error_is_still_a_failure(self):
        """Negative: an Error whose row lacks the forward proof, or has no row at all, stays failed."""
        broken = QDETAILS.replace('forward_mismatches=0', 'forward_mismatches=3')
        write_stats(self.run, [q_row(self.aliases[1], 'USDCAD', details=broken)])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_pending'])
        self.assertEqual((value['members_no_edge'], value['members_failed'], value['no_edge']), (0, 2, []))
        self.assertIn('2 failed', headline(dict(kind='batch', status='running', **value)))
        self.assertNotIn('no edge', headline(dict(kind='batch', status='running', **value)))


class NoQualifyingRowsFinishTests(unittest.TestCase):
    def test_finish_records_nothing_qualified_for_the_scoreboard(self):
        with tempfile.TemporaryDirectory() as folder:
            write_stats(folder, [q_row('A1', 'USDCAD'), stats_row('A2', 'USDCHF')])
            write_timeline(folder, [(alias, 'OnGoing', NOW - 3600) for alias in ('A0', 'A1', 'A2', 'A3')])
            members = [dict(run_alias='A0', symbol='EURUSD', status='native_completed', tester=dict(Period='M1')),
                       dict(run_alias='A1', symbol='USDCAD', status='native_error', tester=dict(Period='M1')),
                       dict(run_alias='A2', symbol='USDCHF', status='native_error', tester=dict(Period='M1')),
                       dict(run_alias='A3', symbol='NZDUSD', status='native_error', tester=dict(Period='M1'))]
            outcomes, error = _research_outcomes(dict(native_run=folder, members=members))
        self.assertIsNone(error)
        self.assertEqual([(o['index'], o['outcome']) for o in outcomes], [(1, 'no_qualifying_rows'), (2, 'no_profitable_passes')])
        self.assertIn('nothing qualified', outcomes[0]['summary'])
        # Member 3 has no row: it stays a real failure, with native error evidence.
        from studio_native_diagnostics import for_job
        evidence = for_job(None, dict(launch_intent=dict(package='missing')), dict(status='native_error', members=members),
                           [o['index'] for o in outcomes])
        self.assertEqual((evidence['members_no_edge'], evidence['members_failed']), ([1, 2], [3]))


class PauseAndResumeTests(pause_fixtures.PauseFixture):
    def finish_with_outcomes(self, states, no_edge, outcome='no_profitable_passes'):
        self.finish_natively(states)
        state = self.c.state(); job = next(j for j in state['queue'] if j['job_id'] == 'g6')
        job['completion']['research_outcomes'] = [dict(index=i, outcome=outcome) for i in no_edge]
        Path(job['completion_path']).write_text(json.dumps(job['completion']), encoding='utf-8')
        from campaign_ledger import packed
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.c.store.db.commit()

    def test_pause_counts_no_edge_apart_and_finishes_when_nothing_failed(self):
        self.request()
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1, 2])
        record = pause.complete(self.c, 'g6', now=NOW)
        self.assertEqual((record['state'], record['members_failed'], record['members_no_edge'], record['members_remaining']),
                         ('finished', 0, 2, 0))
        self.assertEqual(pause.public(record)['members_no_edge'], 2)

    def test_pause_counts_nothing_qualified_apart_and_keeps_real_failures(self):
        self.request()
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1], outcome='no_qualifying_rows')
        record = pause.complete(self.c, 'g6', now=NOW)
        self.assertEqual((record['state'], record['members_failed'], record['members_no_edge']), ('paused', 1, 1))

    def test_retrying_failures_never_reruns_nothing_qualified_members(self):
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1], outcome='no_qualifying_rows')
        prepared = resume_batch(self.c, 'g6', 'g6-r1', include_failed=True)
        self.assertEqual(prepared['member_count'], 1)
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r1')['configuration']['batch_members']], ['USDJPY.c'])

    def test_pause_keeps_real_failures_resumable(self):
        self.request()
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1])
        record = pause.complete(self.c, 'g6', now=NOW)
        self.assertEqual((record['state'], record['members_failed'], record['members_no_edge']), ('paused', 1, 1))

    def test_retrying_failures_never_reruns_no_edge_members(self):
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1])
        prepared = resume_batch(self.c, 'g6', 'g6-r1', include_failed=True)
        self.assertEqual(prepared['member_count'], 1)
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r1')['configuration']['batch_members']], ['USDJPY.c'])

    def test_include_no_edge_deliberately_reruns_them(self):
        """Review HIGH: an explicit override re-runs no-edge members, alone or with failures."""
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1])
        only = resume_batch(self.c, 'g6', 'g6-r1', include_no_edge=True)
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r1')['configuration']['batch_members']], ['GBPUSD.c'])
        both = resume_batch(self.c, 'g6', 'g6-r2', include_failed=True, include_no_edge=True)
        self.assertEqual((only['member_count'], both['member_count']), (1, 2))
        with self.assertRaisesRegex(ValueError, 'No unfinished members selected'):
            resume_batch(self.c, 'g6', 'g6-r3')

    def test_resume_cli_and_demo_lane_expose_the_override(self):
        for name in ('goat_studio.py', 'demo_agent.py'):
            source = Path(__file__).with_name(name).read_text(encoding='utf-8')
            self.assertIn('--include-no-edge', source, name)
            self.assertIn('include_no_edge=args.include_no_edge', source, name)

    def test_retrying_failures_never_reruns_export_loss_members(self):
        """Banker r1c-b40-r2: --include-failed retries the timeouts, never the sets that lost money."""
        self.finish_with_outcomes(['Completed', 'Error', 'Error'], [1], outcome='no_profitable_exports')
        prepared = resume_batch(self.c, 'g6', 'g6-r1', include_failed=True)
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r1')['configuration']['batch_members']], ['USDJPY.c'])
        both = resume_batch(self.c, 'g6', 'g6-r2', include_failed=True, include_no_edge=True)
        self.assertEqual((prepared['member_count'], both['member_count']), (1, 2))


# ---------------------------------------------------------------------------
# Every re-tested set lost money over the export window (Banker r1c-b40-r2)
# ---------------------------------------------------------------------------

ITEM = 'NZDCAD,M1 2025.10.17-2026.08.28_OHLC:'
LOSS = [
    'DEINIT: Optimization Ended, NZDCAD',
    'DEINIT: ✅ XML Migration completed successfully!',
    'Forward Date Extracted: 2026.07.17',
    'Extracted Back Test range: 2025.10.17 - 2026.08.28',
    'No further back <Row> Found. Rows Saved=57/163 (profitable=57, min trades=50)',
    'No further forward <Row> Found. Discarded=106/163',
    'SXmlData::WriteTopToXml: wrote 1 distinct row(s) (Score≥60) to GOAT V1.49 NZDCAD,M1 2025.10.17-2026.08.28_(2026.07.17)_CombinedRows_Score=72.2.xml',
    'SXmlData::WriteUniqueRowsToXml: 1 unique rows written to GOAT V1.49 NZDCAD,M1 2025.10.17-2026.08.28_(2026.07.17)_UniqueRows_Score=72.2.xml',
    'Finished reading & matching Back/Forward data. Found rows = 57',
    'DEINIT: ✅ XML files Combined and Analyzed.',
    'TESTER: Tester Settings Initialized.',
    '⚠️ No EvidenceEnd in the export settings: exports end before 2026.10.02 (the legacy last-Friday end).',
    'DEINIT: Running top Score Set on back history only',
    'Attempt 1/3: Settings verified – starting tester',
    'Export found in 19s: GOAT V1.49 NZDCAD,M1_Trds=386_Prf=503_DD=3784_PF=1.04_SR=0.22_ARF=0.015.csv',
    'DEINIT: ✅ Top Set Export Verified, Export Profit=503 Back Profit=503, Export Trades=386 Back Trades=386',
    '⚠️ Back Out-Of-Sample (OOS) history is enabled.',
    'Adjusting Test Dates, StartDate=2025.10.03 EndDate=2026.10.02',
    'Modelling set to ETWRT',
    '▶ Running unique set # (1). With Score=72.2 Set Exports stored=0/0 Above Threshold=0',
    'Attempt 1/3: Settings verified – starting tester',
    'Export found in 53s: GOAT V1.49 NZDCAD,M1_Trds=515_Prf=-732_DD=5312_PF=0.96_SR=-0.24_ARF=-0.012.csv',
    '⚠️ Export Profit=-732<0, Discarding completed Set (incomplete evidence retained)',
    '⚠️ No more sets available to run.',
    '✅✅✅✅✅ Export sequence complete: 1 attempts – 0 profitable, 1 losses, 0 errors, 0 duplicates, 0 passed thresholds.',
    '❌ zero exports available after the export cycle.',
]
EXPORT_FOUND = 'Export found in 53s: GOAT V1.49 NZDCAD,M1_Trds=515_Prf=-732_DD=5312_PF=0.96_SR=-0.24_ARF=-0.012.csv'
DISCARDED = '⚠️ Export Profit=-732<0, Discarding completed Set (incomplete evidence retained)'
SEQUENCE = '✅✅✅✅✅ Export sequence complete: 1 attempts – 0 profitable, 1 losses, 0 errors, 0 duplicates, 0 passed thresholds.'
# CADCHF (member 34): the re-test never finished; MT5 timed out. A real failure.
TIMEOUT = [line for line in LOSS if line not in (EXPORT_FOUND, DISCARDED, SEQUENCE)][:-1] + [
    '❌ Strategy Tester running for 500 seconds timed out waiting to become idle – aborting this set',
    '⚠️ No more sets available to run.',
    '✅✅✅✅✅ Export sequence complete: 1 attempts – 0 profitable, 0 losses, 1 errors, 0 duplicates, 0 passed thresholds.',
    '❌ zero exports available after the export cycle.']


def swap(body, old, new):
    """The body with ``old`` replaced by ``new`` lines (None removes it)."""
    assert old in body, old
    k = body.index(old)
    return body[:k] + ([] if new is None else ([new] if isinstance(new, str) else list(new))) + body[k + 1:]


def export_row(alias, symbol, *, at, status='Error', xml='57', unique='1', top='72.2', exports='0', details='Export cycle finished'):
    return '\t'.join([local(at), symbol, alias, status, xml, unique, top, exports, details])


def write_log(folder, members, *, encoding='utf-16'):
    """members: (alias, start, end, body, end status) in run order, as the EA's WriteLog writes them."""
    def line(at, text):
        return local(at) + ' ' + local(at)[11:] + '  GOAT V1.49: ' + text
    rows = []
    for alias, start, end, body, status in members:
        rows.append(line(start, 'Queued->OnGoing: ;OnGoing_' + ITEM + alias + ';'))
        rows += [line(start + 60, text) for text in body]
        rows.append(line(end, 'OnGoing->' + status + ': ;' + status + '_' + ITEM + alias + ';'))
    Path(folder, 'log.GOAT').write_bytes(('\r\n'.join(rows) + '\r\n').encode(encoding))


class ExportLossTests(unittest.TestCase):
    """A plain Error row is a result only when the EA log proves every re-tested set lost money."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.members = [('A0', 'NZDCAD'), ('A1', 'CADCHF'), ('A2', 'AUDJPY')]
        self.spans = [(NOW - 3600, NOW - 3000), (NOW - 2400, NOW - 1800), (NOW - 1200, NOW - 600)]

    def read(self, bodies, *, rows=None, ends=('Error', 'Error', 'Error'), log_ends=None, shift=0, end_shift=0):
        from studio_research_status import timeline
        events = []
        for (alias, _), (start, end), status in zip(self.members, self.spans, ends):
            events += [(alias, 'OnGoing', start), (alias, status, end)]
        write_timeline(self.run, events)
        write_log(self.run, [(alias, start + shift, end + end_shift, body, status) for (alias, _), (start, end), body, status
                             in zip(self.members, self.spans, bodies, log_ends or ends)])
        write_stats(self.run, rows if rows is not None else
                    [export_row(alias, symbol, at=end - 1) for (alias, symbol), (_, end) in zip(self.members, self.spans)])
        return item_outcomes(self.run, self.members, timeline(self.run, [alias for alias, _ in self.members]))

    def test_banker_loss_is_a_result_and_timeouts_stay_failures(self):
        export_timeout = swap(TIMEOUT, TIMEOUT[-4], '❌ Export timeout 250 seconds – aborting this set')
        found = self.read([LOSS, TIMEOUT, export_timeout])
        self.assertEqual(list(found), [0])
        outcome = found[0]
        self.assertEqual((outcome['outcome'], outcome['sets_retested'], outcome['export_losses'], outcome['best_export_profit']),
                         ('no_profitable_exports', 1, 1, -732.0))
        self.assertEqual((outcome['back_rows'], outcome['unique_sets'], outcome['best_combined_score'], outcome['score_threshold']),
                         (57, 1, 72.2, 60.0))
        self.assertEqual(outcome['window'], dict(start='2025.10.17', end='2026.07.17', forward_end='2026.08.28'))
        self.assertEqual(outcome['export_window'], dict(start='2025.10.03', end='2026.10.02'))

    def test_summary_says_what_scored_and_what_the_re_test_lost(self):
        text = no_edge_summary('NZDCAD', 'M1', self.read([LOSS, TIMEOUT, TIMEOUT])[0])
        self.assertEqual(text, 'NZDCAD M1: tested, nothing held up in 2025.10.17 to 2026.07.17 — 1 set scored 60+ once the forward '
                               'period to 2026.08.28 was included (best 72.2), but the 1 set re-tested over 2025.10.03 to 2026.10.02 '
                               'lost money (best -732.00). A result for this window only, not a verdict on the strategy.')
        many = swap(swap(swap(LOSS, SEQUENCE, SEQUENCE.replace('1 attempts', '2 attempts').replace('1 losses', '2 losses')),
                         DISCARDED, [DISCARDED, DISCARDED.replace('-732', '-41')]), EXPORT_FOUND, [EXPORT_FOUND, EXPORT_FOUND])
        outcome = self.read([many, TIMEOUT, TIMEOUT], rows=[export_row('A0', 'NZDCAD', at=NOW - 3001, unique='2')])[0]
        self.assertEqual((outcome['sets_retested'], outcome['best_export_profit']), (2, -41.0))
        self.assertIn('2 sets scored 60+', no_edge_summary('NZDCAD', 'M1', outcome))
        self.assertIn('but all 2 sets re-tested', no_edge_summary('NZDCAD', 'M1', outcome))

    def test_anything_but_completed_losing_re_tests_stays_a_real_failure(self):
        combined = 'DEINIT: ✅ XML files Combined and Analyzed.'
        verified = LOSS[15]
        for label, body in [
                ('an export error', swap(LOSS, SEQUENCE, SEQUENCE.replace('1 losses, 0 errors', '0 losses, 1 errors'))),
                ('losses and errors mixed', swap(LOSS, SEQUENCE, SEQUENCE.replace('1 attempts', '2 attempts').replace('0 errors', '1 errors'))),
                ('a profitable set', swap(LOSS, SEQUENCE, SEQUENCE.replace('0 profitable', '1 profitable'))),
                ('a set passed thresholds', swap(LOSS, SEQUENCE, SEQUENCE.replace('0 passed', '1 passed'))),
                ('not every attempt lost', swap(LOSS, SEQUENCE, SEQUENCE.replace('1 attempts', '2 attempts'))),
                ('an attempt neither lost nor failed', swap(swap(LOSS, SEQUENCE, SEQUENCE.replace('1 attempts', '2 attempts')),
                                                            EXPORT_FOUND, [EXPORT_FOUND, EXPORT_FOUND])),
                ('counts that do not add up', swap(LOSS, SEQUENCE, SEQUENCE.replace('0 errors', '1 errors'))),
                ('no export ran at all', swap(swap(swap(LOSS, SEQUENCE, SEQUENCE.replace('1 attempts', '0 attempts').replace('1 losses', '0 losses')),
                                               EXPORT_FOUND, None), DISCARDED, None)),
                ('a tester timeout line', swap(LOSS, DISCARDED, [DISCARDED, '❌ Export timeout 250 seconds – aborting this set'])),
                ('a start failure line', swap(LOSS, DISCARDED, [DISCARDED, '❌ Failed to Configure and/or Start the Strategy Tester after 3 start attempt(s). Skipping...'])),
                ('top set never verified', swap(LOSS, verified, None)),
                ('top set verification failed', swap(LOSS, verified, 'DEINIT: ❌ Export verification failed, Export Profit=1 Back Profit=503, Export Trades=3 Back Trades=386')),
                ('reports never combined', swap(LOSS, combined, None)),
                ('the optimization ended twice', swap(LOSS, LOSS[0], [LOSS[0], LOSS[0]])),
                ('lot adjustment ran', swap(LOSS, SEQUENCE, [SEQUENCE, '✅✅✅✅✅ Export Adjustment sequence complete: 1 attempts – 0 profitable, 1 losses, 0 errors, 0 passed thresholds'])),
                ('no zero-exports line', swap(LOSS, LOSS[-1], None)),
                ('two export sequences', swap(LOSS, SEQUENCE, [SEQUENCE, SEQUENCE])),
                ('loss not logged', swap(LOSS, DISCARDED, None)),
                ('zero-profit set', swap(LOSS, DISCARDED, DISCARDED.replace('-732', '0'))),
                ('an export file missing', swap(LOSS, EXPORT_FOUND, None)),
                ('window out of order', swap(LOSS, LOSS[3], 'Extracted Back Test range: 2025.10.17 - 2026.06.28')),
                ('export window out of order', swap(LOSS, LOSS[17], 'Adjusting Test Dates, StartDate=2026.10.02 EndDate=2025.10.03')),
                ('no score threshold', swap(LOSS, LOSS[6], None)),
                ('another member started inside', swap(LOSS, DISCARDED, [DISCARDED, 'Queued->OnGoing: ;OnGoing_' + ITEM + 'A9;']))]:
            with self.subTest(label):
                self.assertEqual(self.read([body, TIMEOUT, TIMEOUT]), {}, label)

    def test_row_and_timeline_must_belong_to_the_last_attempt(self):
        for label, kwargs in [
                ('an export was kept', dict(rows=[export_row('A0', 'NZDCAD', at=NOW - 3001, exports='1')])),
                ('no unique set', dict(rows=[export_row('A0', 'NZDCAD', at=NOW - 3001, unique='0')])),
                ('another error detail', dict(rows=[export_row('A0', 'NZDCAD', at=NOW - 3001, details='Failed')])),
                ('top score below the export score', dict(rows=[export_row('A0', 'NZDCAD', at=NOW - 3001, top='48.0')])),
                ('row from an older attempt', dict(rows=[export_row('A0', 'NZDCAD', at=NOW - 3700)])),
                ('the member completed', dict(ends=('Completed', 'Error', 'Error'))),
                ('the timeline says completed', dict(ends=('Completed', 'Error', 'Error'), log_ends=('Error', 'Error', 'Error'))),
                ('the log ends another way', dict(log_ends=('Completed', 'Error', 'Error'))),
                ('log start is another attempt', dict(shift=30)),
                ('log end is another attempt', dict(end_shift=-30))]:
            with self.subTest(label):
                self.assertEqual(self.read([LOSS, TIMEOUT, TIMEOUT], **kwargs), {}, label)
        self.assertEqual(list(self.read([LOSS, TIMEOUT, TIMEOUT])), [0], 'the control case is a result')
        self.assertEqual(item_outcomes(self.run, self.members), {}, 'no timeline evidence, nothing relabelled')
        (self.run / 'log.GOAT').write_bytes(b'\xff\xfe\x00')
        self.assertEqual(item_outcomes(self.run, self.members, dict(started={0: NOW - 3600}, ended={0: NOW - 3000},
                                                                    outcome={0: 'Error'})), {}, 'unreadable log')
        (self.run / 'log.GOAT').unlink()
        self.assertEqual(item_outcomes(self.run, self.members, dict(started={0: NOW - 3600}, ended={0: NOW - 3000},
                                                                    outcome={0: 'Error'})), {}, 'missing log')

    def test_a_utf8_log_reads_the_same(self):
        self.read([LOSS, TIMEOUT, TIMEOUT])
        write_log(self.run, [(alias, start, end, body, 'Error') for (alias, _), (start, end), body
                             in zip(self.members, self.spans, [LOSS, TIMEOUT, TIMEOUT])], encoding='utf-8-sig')
        from studio_research_status import timeline
        self.assertEqual(list(item_outcomes(self.run, self.members, timeline(self.run, ['A0', 'A1', 'A2']))), [0])


class ExportLossProgressTests(unittest.TestCase):
    SYMBOLS, setUp, progress, finish_member = ProgressTests.SYMBOLS, ProgressTests.setUp, ProgressTests.progress, ProgressTests.finish_member

    def test_banker_mix_counts_results_apart_and_keeps_the_timeout_failed(self):
        events = []
        for index, status in enumerate(['Completed', 'Error', 'Error', 'Error']):
            events += self.finish_member(index, status, NOW - 2400 + index * 600, NOW - 1800 + index * 600)
        write_timeline(self.run, events)
        # Member 1: nothing qualified; member 2: the re-tested set lost money; member 3: MT5 timed out.
        write_log(self.run, [(self.aliases[2], NOW - 1200, NOW - 600, LOSS, 'Error'), (self.aliases[3], NOW - 600, NOW, TIMEOUT, 'Error')])
        write_stats(self.run, [q_row(self.aliases[1], 'USDCAD', at=NOW - 1220), export_row(self.aliases[2], 'USDCHF', at=NOW - 601),
                               export_row(self.aliases[3], 'NZDUSD', at=NOW - 1, top='72.4', xml='111')])
        value = self.progress(['native_completed', 'native_error', 'native_error', 'native_error'])
        self.assertEqual((value['members_no_edge'], value['members_failed']), (2, 1))
        self.assertEqual(value['no_edge_counts'], dict(no_qualifying_rows=1, no_profitable_exports=1))
        self.assertEqual([(item['symbol'], item['outcome']) for item in value['no_edge']],
                         [('USDCAD', 'no_qualifying_rows'), ('USDCHF', 'no_profitable_exports')])
        self.assertEqual(value['no_edge_window'], None, 'the two outcomes come from different test windows')
        self.assertEqual(value['last_member']['status'], 'error', 'the timeout stays an error')
        text = headline(dict(kind='batch', status='failed', **value))
        self.assertEqual(text, 'Batch failed; 1 of 4 members done, 0 qualifying, 2 tested, nothing qualified in their test window '
                               '(1 none scored 60+ once the forward period was included, 1 lost money on the export re-test), 1 failed.')

    def test_only_export_losses_read_finished_and_name_the_re_test(self):
        write_timeline(self.run, self.finish_member(0, 'Completed', NOW - 2400, NOW - 1800) + self.finish_member(1, 'Error', NOW - 1800, NOW - 1200))
        write_log(self.run, [(self.aliases[1], NOW - 1800, NOW - 1200, LOSS, 'Error')])
        write_stats(self.run, [export_row(self.aliases[1], 'USDCAD', at=NOW - 1201)])
        value = self.progress(['native_completed', 'native_error', 'native_cancelled', 'native_cancelled'])
        self.assertEqual((value['members_no_edge'], value['members_failed'], value['last_member']['status']),
                         (1, 0, 'no_profitable_exports'))
        self.assertIn('lost money', value['last_member']['summary'])
        self.assertEqual(headline(dict(kind='batch', status='failed', **value)),
                         'Batch stopped early; 1 of 4 members done, 0 qualifying, 1 tested, nothing qualified in 2025.10.17 to '
                         '2026.07.17 (1 lost money on the export re-test), 2 cancelled.')

    def test_finish_records_export_losses_for_resume_selection(self):
        events = self.finish_member(0, 'Completed', NOW - 2400, NOW - 1800) + self.finish_member(1, 'Error', NOW - 1800, NOW - 1200)
        write_timeline(self.run, events)
        write_log(self.run, [(self.aliases[1], NOW - 1800, NOW - 1200, LOSS, 'Error')])
        write_stats(self.run, [export_row(self.aliases[1], 'USDCAD', at=NOW - 1201)])
        members = [dict(run_alias=alias, symbol=symbol, status=status, tester=dict(Period='M1'))
                   for alias, symbol, status in zip(self.aliases, self.SYMBOLS, ['native_completed', 'native_error', 'native_error', 'native_error'])]
        outcomes, error = _research_outcomes(dict(native_run=str(self.run), members=members))
        self.assertIsNone(error)
        self.assertEqual([(o['index'], o['outcome']) for o in outcomes], [(1, 'no_profitable_exports')])
        self.assertIn('lost money', outcomes[0]['summary'])


if __name__ == '__main__':
    unittest.main()
