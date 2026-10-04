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
from studio_research_status import (ITEM_STATS_HEADER, batch_progress, headline, item_outcomes, no_edge_members,
                                    no_edge_summary, pace)
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
        folder = self.run / 'deploy' / self.aliases[0] / 'EURUSD'; folder.mkdir(parents=True); (folder / 'a.set').write_text('x')
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
        self.assertEqual(headline(activity), 'Running on NZDUSD M1; 1 of 4 members done, 1 qualifying, '
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
        self.assertIn('2 tested with no edge in 2024.01.08 to 2025.01.06, 1 failed', text)

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
                         'Batch finished; 1 of 4 members done, 0 qualifying, 3 tested with no edge in 2024.01.08 to 2025.01.06.')

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


if __name__ == '__main__':
    unittest.main()
