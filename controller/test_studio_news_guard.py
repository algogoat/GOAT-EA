"""News-file guard on resume (studio_news_guard, goatai#2350 ruling (c) on GOAT-EA#200).

A start records the sha256 of Common\\Files\\GOAT\\GOAT_News.csv; a news-on run (a SET with Mode_News 2-5)
refuses to resume on a changed file, or with no record, unless --accept-news-change starts a labelled news
lineage. News-off runs (Mode_News 0 Display, 1 Disabled, or missing) are never blocked.
Real controller store and packages for native batches, the SeedRunner fixture for seed hunts; no MT5.
"""
import copy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import studio_news_guard as guard
from studio_batch import resume_batch
from studio_fast_lane import continue_batch
from studio_installation import read_json
from studio_refusal import Refusal
from test_studio_batch_pause import NOW, PauseFixture
import test_studio_seed as seed_fixtures

FILE_A = b'\xff\xfe' + 'Time,Currency\r\n2026.07.07 12:30:00,USD\r\n'.encode('utf-16-le')
FILE_B = b'\xff\xfe' + 'Time,Currency\r\n2026.10.07 08:55:00,EUR\r\n'.encode('utf-16-le')
SHA_A, SHA_B = hashlib.sha256(FILE_A).hexdigest(), hashlib.sha256(FILE_B).hexdigest()
IDLE = ({'runtime': dict(tester_state='idle', batch_ongoing=False, account_demo=True)}, {})


class ModeNewsTests(unittest.TestCase):
    """ENUM_ACTION_NEWS: 0 Display, 1 Disabled, 2 Avoid, 3 Pause, 4 Close, 5 Only."""
    def test_only_values_that_change_trades_are_news_on(self):
        for value, on in ((None, False), ('0', False), ('1', False), ('2', True), ('3', True), ('4', True), ('5', True),
                          (' 2 ', True), ('1||1||1||4||Y', True), ('1||0||1||2||Y', True), ('0||0||1||1||Y', False),
                          ('1||1||1||4||N', False), ('2||0||1||1||N', True), ('0||2||1||0||Y', True),
                          ('Avoid', True), ('', True)):
            with self.subTest(value=value):
                self.assertIs(guard.mode_news_on(value), on)

    def test_runs_are_news_on_when_any_set_is(self):
        self.assertFalse(guard.values_news_on([{}, {'Mode_News': '1'}, {'Mode_News': '0'}]))
        self.assertTrue(guard.values_news_on([{'Mode_News': '1'}, {'Mode_News': '1||1||1||5||Y'}]))
        job = dict(configuration=dict(batch_members=[dict(strategy=dict(values={'Mode_News': '1'})),
                                                     dict(strategy=dict(values={'Mode_News': '2'}))]))
        self.assertTrue(guard.job_news_on(job))
        self.assertFalse(guard.job_news_on(dict(configuration=dict(batch_members=[dict(strategy=dict(values={}))]))))


# ---------------------------------------------------------------------------------------------- native batches

class NativeBase(PauseFixture):
    """Banker's shape: g6 paused after one member; the news file is A."""
    EXTRA_INPUTS = {'Mode_News': dict(type='int', optimizable=True)}

    def setUp(self):
        super().setUp()
        runtime = patch.object(self.c, 'runtime', return_value=IDLE)
        runtime.start(); self.addCleanup(runtime.stop)
        self.request()
        self.finish_natively(['Completed', 'Cancelled', 'Cancelled'])
        self.assertEqual(__import__('studio_batch_pause').complete(self.c, 'g6', now=NOW)['state'], 'paused')
        self.news = Path(self.c.install['common_files_root']) / 'GOAT' / 'GOAT_News.csv'
        self.news.parent.mkdir(parents=True, exist_ok=True)
        self.news.write_bytes(FILE_A)

    def started(self, job_id='g6'):
        """What every native start route does (before_native_dispatch): record the file the batch starts on."""
        return guard.check_native_start(self.c, self.c.job(job_id), now=NOW)


class NativeNewsTests(NativeBase):
    TEMPLATE = PauseFixture.TEMPLATE + 'Mode_News=2\r\n'

    def test_start_records_the_file_and_a_fresh_batch_is_never_refused(self):
        label = self.started()
        record = guard.load_record(self.c.root, 'g6')
        self.assertEqual((record['sha256'], record['news_on'], record['lineage']), (SHA_A, True, 'original'))
        self.assertEqual(label['sha256'], SHA_A)
        self.news.write_bytes(FILE_B)
        self.assertEqual(self.started()['sha256'], SHA_A)        # a start validates more than once: kept as recorded

    def test_resume_on_the_same_file_continues_the_lineage(self):
        self.started()
        prepared = resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True)
        self.assertEqual((prepared['news_file']['lineage'], prepared['news_file']['sha256']), ('continued', SHA_A))
        self.assertEqual(self.started('g6-r1')['sha256'], SHA_A)

    def test_a_changed_file_refuses_the_resume_before_anything_is_prepared(self):
        self.started()
        self.news.write_bytes(FILE_B)
        with self.assertRaises(Refusal) as caught:
            resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True)
        refusal = caught.exception
        self.assertEqual((refusal.code, refusal.fields['recorded_sha256'], refusal.fields['current_sha256']),
                         ('NEWS_FILE_CHANGED', SHA_A, SHA_B))
        for words in ('Batch g6 trades on news', SHA_A[:12] + ' then', SHA_B[:12] + ' now', 'nothing was started',
                      'GOAT_News.csv.bak', '--accept-news-change', 'labelled'):
            self.assertIn(words, str(refusal))
        self.assertNotIn('g6-r1', {row['job_id'] for row in self.c.state()['queue']})
        self.assertIsNone(guard.load_record(self.c.root, 'g6-r1'))

    def test_accept_news_change_starts_a_labelled_lineage_with_both_shas(self):
        self.started()
        self.news.write_bytes(FILE_B)
        prepared = resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True, accept_news_change=True)
        news = prepared['news_file']
        self.assertEqual((news['lineage'], news['predecessor_batch_id'], news['predecessor_sha256']), ('news_changed', 'g6', SHA_A))
        self.assertEqual(news['accepted_change'], dict(from_sha256=SHA_A, to_sha256=SHA_B, reason='news_file_changed'))
        self.assertEqual(self.started('g6-r1')['sha256'], SHA_B)
        # research-queue marks the successor's results apart from the predecessor's.
        from studio_research_queue import batch_row
        row = batch_row(self.c.root, self.c.install, self.c.job('g6-r1'), now=NOW, with_progress=False)
        self.assertEqual((row['news_file']['lineage'], row['news_file']['sha256']), ('news_changed', SHA_B))
        self.assertEqual(batch_row(self.c.root, self.c.install, self.c.job('g6'), now=NOW, with_progress=False)
                         ['news_file']['sha256'], SHA_A)

    def test_a_prepared_successor_refuses_to_start_on_a_changed_file_until_accepted(self):
        self.started()
        continue_batch(self.c, 'g6')
        self.news.write_bytes(FILE_B)
        with self.assertRaises(Refusal) as caught:
            self.started('g6-r1')
        self.assertEqual(caught.exception.code, 'NEWS_FILE_CHANGED')
        self.assertIn('continue --batch-id g6 --accept-news-change', str(caught.exception))
        again = continue_batch(self.c, 'g6', accept_news_change=True)        # reuses the prepared successor
        self.assertEqual((again['reused'], again['news_file']['lineage']), (True, 'news_changed'))
        self.assertEqual(self.started('g6-r1')['sha256'], SHA_B)

    def test_a_legacy_news_on_batch_with_no_record_refuses_until_accepted(self):
        self.news.write_bytes(FILE_B)          # g6 started before the guard: nothing was recorded
        with self.assertRaises(Refusal) as caught:
            continue_batch(self.c, 'g6')
        self.assertEqual(caught.exception.code, 'NEWS_FILE_UNRECORDED')
        self.assertIn('started before GOAT recorded which GOAT_News.csv', str(caught.exception))
        self.assertIn('--accept-news-change', str(caught.exception))
        result = continue_batch(self.c, 'g6', accept_news_change=True)
        self.assertEqual(result['news_file']['accepted_change'],
                         dict(from_sha256=None, to_sha256=SHA_B, reason='predecessor_unrecorded'))

    def test_a_legacy_successor_prepared_before_the_guard_is_checked_at_its_start(self):
        self.started()
        continue_batch(self.c, 'g6')
        (self.c.root / 'news-file' / 'batch-g6-r1.json').unlink()          # prepared by an older controller
        self.news.write_bytes(FILE_B)
        with self.assertRaisesRegex(Refusal, 'GOAT_News.csv changed'):
            self.started('g6-r1')


class NativeNewsOffTests(NativeBase):
    """The same batch with news off (Disabled): never blocked, whatever the file does."""
    TEMPLATE = PauseFixture.TEMPLATE + 'Mode_News=1\r\n'

    def test_a_changed_file_never_blocks_a_news_off_resume(self):
        self.started()
        self.news.write_bytes(FILE_B)
        prepared = resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True)
        self.assertEqual((prepared['news_file']['news_on'], prepared['news_file']['lineage']), (False, 'continued'))
        self.assertEqual(self.started('g6-r1')['sha256'], SHA_B)

    def test_a_legacy_news_off_batch_is_allowed(self):
        self.news.unlink()
        self.assertEqual(continue_batch(self.c, 'g6')['batch_id'], 'g6-r1')

    def test_a_prepared_news_off_successor_starts_on_a_changed_file(self):
        self.started()
        continue_batch(self.c, 'g6')
        self.news.write_bytes(FILE_B)
        self.assertEqual(self.started('g6-r1')['sha256'], SHA_B)


class NativeDisplayTests(NativeNewsOffTests):
    """Display (0) reads the news file but never changes a trade: news-off for the guard."""
    TEMPLATE = PauseFixture.TEMPLATE + 'Mode_News=0\r\n'


class NativeRangeTests(NativeNewsTests):
    """An optimised Mode_News range that reaches 2 (Avoid) is news-on."""
    TEMPLATE = PauseFixture.TEMPLATE + 'Mode_News=1||1||1||2||Y\r\n'


# ---------------------------------------------------------------------------------------------- seed hunts

class SeedNewsTests(unittest.TestCase):
    MODE = '2'

    def setUp(self):
        self.f = seed_fixtures.SeedTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.f.controller.schema['inputs']['Mode_News'] = dict(type='int', optimizable=False)
        self.f.source.write_bytes(('; Source header\r\nEA_Desc=Original\r\nPeriod=10||10||5||20||Y\r\nSize=1.5\r\nMode_News='
                                   + self.MODE + '\r\n').encode('utf-16'))
        second = copy.deepcopy(self.f.plan['jobs'][0]); second['tester']['Symbol'] = 'GBPUSD'
        self.f.plan['jobs'].append(second)
        self.news = Path(self.f.controller.install['common_files_root']) / 'GOAT' / 'GOAT_News.csv'
        self.news.parent.mkdir(parents=True, exist_ok=True)
        self.news.write_bytes(FILE_A)
        self.runner = self.f.runner

    def paused_after_first_member(self):
        self.f.prepare(); self.f.auto = True
        original = self.f.sleep
        def pause_after_first_start(seconds):
            if len(self.f.starts) == 1 and not self.runner.paused('batch'):
                self.runner.request_pause('batch', now=self.f.now)
            original(seconds)
        self.runner.sleep = pause_after_first_start
        self.assertTrue(self.runner.start('batch', 30)['paused'])
        self.runner.sleep = original

    def state(self):
        return read_json(self.runner.path('batch') / 'state.json')

    def test_start_records_the_file_and_tags_each_member(self):
        self.paused_after_first_member()
        state = self.state()
        self.assertEqual((state['news_file']['sha256'], state['news_file']['news_on'], state['news_file']['changes']),
                         (SHA_A, self.MODE >= '2', []))
        self.assertEqual((state['members'][0]['news_sha256'], state['members'][0]['news_lineage']), (SHA_A, 0))

    def test_a_changed_file_refuses_the_unpause_and_accept_starts_a_new_lineage(self):
        self.paused_after_first_member()
        self.news.write_bytes(FILE_B)
        with self.assertRaises(Refusal) as caught:
            self.runner.release_pause('batch', now=self.f.now)
        self.assertEqual(caught.exception.code, 'NEWS_FILE_CHANGED')
        self.assertIn('Seed hunt batch trades on news', str(caught.exception))
        self.assertTrue(self.runner.paused('batch'))                       # the pause stays in place
        change = self.runner.accept_news_change('batch')
        pending = self.state()['members'][1]['alias']
        self.assertEqual({k: change[k] for k in ('from_sha256', 'to_sha256', 'reason', 'lineage', 'first_member')},
                         dict(from_sha256=SHA_A, to_sha256=SHA_B, reason='news_file_changed', lineage=1, first_member=pending))
        self.assertIsNone(self.runner.accept_news_change('batch'))          # the same file: nothing more to accept
        self.assertTrue(self.runner.release_pause('batch', now=self.f.now))
        self.assertEqual(self.runner.resume('batch', 30)['status'], 'completed')
        members = self.state()['members']
        self.assertEqual([(m['news_sha256'], m['news_lineage']) for m in members], [(SHA_A, 0), (SHA_B, 1)])
        from studio_news_guard import runner_label
        label = runner_label(self.state())
        self.assertEqual((label['lineage'], label['started_sha256'], label['sha256'], label['news_lineages']),
                         ('news_changed', SHA_A, SHA_B, 2))

    def test_a_file_change_between_members_never_launches_the_next_member(self):
        self.f.prepare()
        self.assertTrue(self.runner.start('batch', 1)['driver_budget_exhausted'])   # member 1 is running
        self.f.output(self.f.member(0)); self.f.process_state = None
        self.news.write_bytes(FILE_B)
        with self.assertRaisesRegex(Refusal, 'GOAT_News.csv changed'):
            self.runner.resume('batch', 5)
        self.assertEqual(len(self.f.starts), 1)
        self.assertEqual(self.state()['members'][1]['status'], 'pending')

    def test_a_legacy_run_with_no_record_refuses_the_unpause_until_accepted(self):
        self.paused_after_first_member()
        path = self.runner.path('batch') / 'state.json'
        state = read_json(path); state.pop('news_file')
        from studio_bridge import write_json
        write_json(path, state)                                             # started before the guard
        with self.assertRaises(Refusal) as caught:
            self.runner.release_pause('batch', now=self.f.now)
        self.assertEqual(caught.exception.code, 'NEWS_FILE_UNRECORDED')
        change = self.runner.accept_news_change('batch')
        self.assertEqual((change['from_sha256'], change['to_sha256'], change['reason']), (None, SHA_A, 'started_unrecorded'))
        self.assertTrue(self.state()['news_file']['legacy_unrecorded'])
        self.assertTrue(self.runner.release_pause('batch', now=self.f.now))


class SeedNewsOffTests(SeedNewsTests):
    """Disabled (1): the unpause and the next member are never blocked by a changed file."""
    MODE = '1'

    def test_a_changed_file_never_blocks_a_news_off_run(self):
        self.paused_after_first_member()
        self.news.write_bytes(FILE_B)
        self.assertTrue(self.runner.release_pause('batch', now=self.f.now))
        self.assertEqual(self.runner.resume('batch', 30)['status'], 'completed')
        self.assertIsNone(self.runner.accept_news_change('batch'))

    def test_a_legacy_news_off_run_is_allowed(self):
        self.paused_after_first_member()
        path = self.runner.path('batch') / 'state.json'
        state = read_json(path); state.pop('news_file')
        from studio_bridge import write_json
        write_json(path, state)
        self.news.write_bytes(FILE_B)
        self.assertTrue(self.runner.release_pause('batch', now=self.f.now))

    test_a_changed_file_refuses_the_unpause_and_accept_starts_a_new_lineage = None
    test_a_file_change_between_members_never_launches_the_next_member = None
    test_a_legacy_run_with_no_record_refuses_the_unpause_until_accepted = None


# ---------------------------------------------------------------------------------------------- the flags

class FlagTests(unittest.TestCase):
    def test_studio_contracts_offer_the_flag_on_every_resume(self):
        from goat_studio import OPERATION_CONTRACTS
        for name in ('batch-continue', 'batch-resume', 'resume-batch', 'seed-resume', 'catchup-resume'):
            self.assertIn('accept-news-change', OPERATION_CONTRACTS[name]['optional'], name)
            self.assertIn('Mode_News 2-5', OPERATION_CONTRACTS[name]['news_file_guard'])

    def test_demo_lane_passes_the_flag_through(self):
        import demo_agent
        cases = (('continue', ['--batch-id', 'b'], 'continue_batch'), ('batch-resume', ['--batch-id', 'b'], 'batch_resume'),
                 ('seed-resume', ['--batch-id', 'b'], 'seed_resume'), ('catchup-resume', ['--catchup-id', 'b'], 'catchup_resume'),
                 ('holdup-resume', ['--holdup-id', 'b'], 'holdup_resume'))
        for command, argv, method in cases:
            for flag in (True, False):
                with self.subTest(command=command, flag=flag), patch('demo_agent.DemoAgent') as agent, redirect_stdout(StringIO()):
                    getattr(agent.return_value, method).return_value = {}
                    demo_agent.main(['--installation', 'x.json', command, *argv] + (['--accept-news-change'] if flag else []))
                    self.assertIs(getattr(agent.return_value, method).call_args.kwargs['accept_news_change'], flag)


if __name__ == '__main__':
    unittest.main()
