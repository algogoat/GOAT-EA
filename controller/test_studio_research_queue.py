"""research-queue: every batch, seed hunt and catch-up of one installation, one row each (goatai#2240).

Rows come from the controller's own retained state, read only; a run that cannot be read whole is
skipped, never guessed; ETAs exist only while running and only from finished members; and the
held-out guard redacts each row's results per strategy key and window, as it does for research-status.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_pause as pause
from studio_research_queue import FINISHED_MAX, research_queue, runner_row

NOW = 1_800_000_000
TESTER = dict(Symbol='EURUSD', Period='H1', FromDate='2026.01.01', ToDate='2026.09.25')


def write_run(root, kind, batch_id, status, members, *, symbols=None, tester=None, pause_file=False, manifest_id=None):
    """A SeedRunner run folder as studio_seed writes it: frozen manifest members and their live state."""
    folder = Path(root) / ('seeds' if kind == 'seed' else 'catchups') / batch_id
    folder.mkdir(parents=True)
    symbols = symbols or ['EURUSD'] * len(members)
    write_json(folder / 'manifest.json', dict(schema_version=1, batch_id=manifest_id or batch_id, plan={}, members=[
        dict(member_id='m%d' % i, alias='S%d' % i, tester=dict(tester or TESTER, Symbol=symbol)) for i, symbol in enumerate(symbols)]))
    write_json(folder / 'state.json', dict(schema_version=1, batch_id=batch_id, status=status, updated_unix=NOW - 5,
                                           members=[dict(member_id='m%d' % i, alias='S%d' % i, **m) for i, m in enumerate(members)]))
    if pause_file:
        write_json(folder / 'pause.json', dict(batch_id=batch_id))
    return folder


def done(minutes_ago, minutes, qualifying=0, **summary):
    return dict(status='completed', started_unix=NOW - minutes_ago * 60, finished_unix=NOW - (minutes_ago - minutes) * 60,
                result=dict(summary=dict(qualifying_count=qualifying, best_fitness=0.5, **summary)))


class RunnerRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def row(self, batch_id, kind='seed'):
        row, reason = runner_row(self.root, kind, batch_id, now=NOW)
        self.assertIsNone(reason)
        return row

    def test_a_running_hunt_counts_candidates_and_measures_its_eta(self):
        write_run(self.root, 'seed', 'hunt', 'active', [done(40, 10, qualifying=28), done(30, 10), dict(status='failed', started_unix=NOW - 1200,
                  finished_unix=NOW - 600), dict(status='running', started_unix=NOW - 120), dict(status='pending')],
                  symbols=['SP500', 'NDX', 'SP500', 'WS30', 'XAUUSD'])
        row = self.row('hunt')
        self.assertEqual((row['kind'], row['stage'], row['state'], row['status']), ('seed', 'explore', 'running', 'active'))
        self.assertEqual((row['members_done'], row['members_total'], row['qualifying']), (3, 5, 1))
        self.assertEqual(row['symbols'], ['SP500', 'NDX', 'WS30', 'XAUUSD'])
        self.assertEqual(row['timeframes'], ['H1'])
        self.assertEqual(row['note'], '1 candidate failed.')
        self.assertEqual(row['started_utc'], '2027-01-15T07:20:00+00:00')
        self.assertIsNone(row['finished_utc'])
        self.assertIsNotNone(row['eta_utc'])        # seed_progress's own measured pace

    def test_no_eta_before_a_member_finishes_or_while_not_running(self):
        write_run(self.root, 'seed', 'fresh', 'active', [dict(status='running', started_unix=NOW - 60), dict(status='pending')])
        self.assertEqual((self.row('fresh')['eta_utc'], self.row('fresh')['qualifying']), (None, None))
        write_run(self.root, 'seed', 'between', 'active', [done(30, 10), dict(status='pending')], pause_file=True)
        row = self.row('between')
        self.assertEqual((row['state'], row['eta_utc']), ('paused', None))
        write_run(self.root, 'seed', 'pausing', 'active', [done(30, 10), dict(status='running', started_unix=NOW - 60), dict(status='pending')],
                  pause_file=True)
        row = self.row('pausing')
        self.assertEqual((row['state'], row['eta_utc'], row['note']), ('pausing', None, 'Pausing after the current candidate.'))

    def test_every_run_status_maps_to_one_queue_state(self):
        write_run(self.root, 'seed', 'prepared', 'prepared', [dict(status='pending'), dict(status='pending')])
        write_run(self.root, 'seed', 'finished', 'completed', [done(30, 10, qualifying=4), done(20, 10)])
        write_run(self.root, 'seed', 'stopped', 'stopped', [done(30, 10), dict(status='cancelled'), dict(status='cancelled')])
        write_run(self.root, 'seed', 'failed', 'stopped', [dict(status='failed', started_unix=NOW - 600, finished_unix=NOW - 500),
                                                           dict(status='missing_output', started_unix=NOW - 500, finished_unix=NOW - 400)])
        write_run(self.root, 'seed', 'r3-seed-121', 'reconcile_required', [dict(status='reconcile_required', started_unix=NOW - 600)])
        states = {name: (self.row(name)['state'], self.row(name)['note']) for name in ('prepared', 'finished', 'stopped', 'failed', 'r3-seed-121')}
        self.assertEqual(states['prepared'], ('queued', None))
        self.assertEqual(states['finished'], ('finished', None))
        self.assertEqual(states['stopped'], ('stopped', 'Stopped before 2 candidates ran.'))
        self.assertEqual(states['failed'], ('failed', 'Every candidate failed.'))
        self.assertEqual(states['r3-seed-121'][0], 'blocked')
        self.assertIn('seed-reconcile --batch-id r3-seed-121', states['r3-seed-121'][1])
        finished = self.row('finished')
        self.assertEqual((finished['qualifying'], finished['members_done'], finished['finished_utc']), (1, 2, '2027-01-15T07:50:00+00:00'))

    def test_a_hunt_stopped_by_failures_with_pending_members_is_stopped_with_its_reason(self):
        # goatai#1885: the breaker stops a hunt with members pending; seed-resume continues them.
        folder = write_run(self.root, 'seed', 'breaker', 'stopped', [
            dict(status='missing_output', started_unix=NOW - 900, finished_unix=NOW - 800, attempts=1),
            dict(status='missing_output', started_unix=NOW - 800, finished_unix=NOW - 700, attempts=1),
            dict(status='missing_output', started_unix=NOW - 700, finished_unix=NOW - 600, attempts=1),
            dict(status='pending', attempts=0)])
        state = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
        state['stopped_reason'] = dict(rules=['in_a_row'], plain='Stopped because 3 members in a row failed. Fix the cause, then '
                                       'seed-resume continues the 1 pending member.')
        write_json(folder / 'state.json', state)
        row = self.row('breaker')
        self.assertEqual((row['state'], row['members_done'], row['members_total']), ('stopped', 3, 4))
        self.assertTrue(row['note'].startswith('Stopped because 3 members in a row failed'))
        self.assertIn('3 candidates failed.', row['note'])
        # Stopped by the old rule (seedhunt-t2-4-b41's shape): no stopped_reason, members still pending.
        write_run(self.root, 'seed', 'legacy-stop', 'stopped', [
            dict(status='missing_output', started_unix=NOW - 900, finished_unix=NOW - 800, attempts=1), dict(status='pending', attempts=0)])
        self.assertEqual(self.row('legacy-stop')['state'], 'stopped')
        self.assertIn('seed-resume continues the 1 pending candidate', self.row('legacy-stop')['note'])

    def test_a_catch_up_is_prove_and_counts_what_held_up(self):
        write_run(self.root, 'catchup', 'oos-1', 'completed', [done(30, 5, verdict='held_up'), done(20, 5, verdict='weakened')])
        row = self.row('oos-1', 'catchup')
        self.assertEqual((row['stage'], row['held_up'], row['members_done']), ('prove', 1, 2))
        self.assertNotIn('qualifying', row)

    def test_torn_partial_or_inconsistent_runs_give_no_row(self):
        folder = write_run(self.root, 'seed', 'torn', 'active', [dict(status='pending')])
        (folder / 'state.json').write_text('{"schema_version": 1, "batch_id": "to', encoding='utf-8')
        (write_run(self.root, 'seed', 'no-manifest', 'active', [dict(status='pending')]) / 'manifest.json').unlink()
        write_run(self.root, 'seed', 'other', 'active', [dict(status='pending')], manifest_id='someone-else')
        short = write_run(self.root, 'seed', 'short', 'active', [dict(status='pending'), dict(status='pending')])
        write_json(short / 'manifest.json', dict(batch_id='short', members=[dict(member_id='m0', tester=TESTER)]))
        write_run(self.root, 'seed', 'strange', 'exploded', [dict(status='pending')])
        for name in ('torn', 'no-manifest', 'other', 'short', 'strange'):
            row, reason = runner_row(self.root, 'seed', name, now=NOW)
            self.assertIsNone(row, name)
            self.assertTrue(reason, name)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.install = dict(controller_state_root=str(self.root), terminal_data_root=str(self.root / 'data'), common_files_root=str(self.root / 'common'))

    def job(self, job_id, status, *, launched=True, symbols=('EURUSD', 'XAUUSD')):
        job = dict(job_id=job_id, status=status, configuration=dict(batch_members=[dict(tester=dict(TESTER, Symbol=s)) for s in symbols]))
        if launched:
            job['launch_intent'] = dict(attempt_id='a' * 64, recorded_at='2027-01-15T06:00:00Z')
        return job

    def queue(self, jobs, **options):
        return research_queue(root=self.root, install=self.install, session=dict(terminal_id='t', run_id='r'), now=NOW, jobs=jobs, **options)

    def test_batches_hunts_and_catch_ups_in_one_queue_running_first(self):
        write_run(self.root, 'seed', 'hunt', 'active', [done(30, 10, qualifying=3), dict(status='running', started_unix=NOW - 60)])
        write_run(self.root, 'seed', 'next-hunt', 'prepared', [dict(status='pending')])
        write_run(self.root, 'catchup', 'oos-1', 'completed', [done(30, 5, verdict='held_up')])
        pause.path(self.root, 'paused-batch').parent.mkdir(parents=True)
        write_json(pause.path(self.root, 'paused-batch'), dict(schema_version=pause.SCHEMA_VERSION, job_id='paused-batch', state='paused'))
        jobs = [self.job('old-batch', 'completed'), self.job('paused-batch', 'cancelled'), self.job('prepared-batch', 'pending', launched=False),
                self.job('live-batch', 'running')]
        value = self.queue(jobs)
        order = [(row['kind'], row['batch_id'], row['state']) for row in value['rows']]
        self.assertEqual(order, [('batch', 'live-batch', 'running'), ('seed', 'hunt', 'running'), ('batch', 'paused-batch', 'paused'),
                                 ('batch', 'prepared-batch', 'queued'), ('seed', 'next-hunt', 'queued'),
                                 ('catchup', 'oos-1', 'finished'), ('batch', 'old-batch', 'finished')])
        live = value['rows'][0]
        self.assertEqual((live['stage'], live['symbols'], live['members_total'], live['started_utc']), ('refine', ['EURUSD', 'XAUUSD'], 2, '2027-01-15T06:00:00Z'))
        self.assertEqual(value['rows'][3]['note'], 'Prepared; not started.')
        self.assertTrue(value['read_only'])
        self.assertFalse(value['launch_permitted'])
        self.assertEqual(value['skipped'], [])

    def test_ended_jobs_are_trimmed_to_the_most_recent_and_unfinished_ones_always_stay(self):
        for index in range(7):
            write_run(self.root, 'seed', 'old-%d' % index, 'completed', [done(60 * 24 * (index + 1), 10)])
        write_run(self.root, 'seed', 'live', 'active', [dict(status='running', started_unix=NOW - 60)])
        value = self.queue([])
        self.assertEqual([row['batch_id'] for row in value['rows']], ['live', 'old-0', 'old-1', 'old-2', 'old-3', 'old-4'])
        self.assertEqual([row['batch_id'] for row in self.queue([], finished=0)['rows']], ['live'])
        self.assertEqual(len(self.queue([], finished=FINISHED_MAX)['rows']), 8)
        for bad in (-1, FINISHED_MAX + 1, True):
            with self.assertRaises(ValueError):
                self.queue([], finished=bad)

    def test_job_ids_list_an_older_ended_batch_without_displacing_the_kept_ends(self):
        # goatai#2272: restore-lane can name a batch that ended long before the 5 newest ends.
        jobs = []
        for index in range(8):
            job = self.job('b%d' % index, 'completed')
            job['launch_intent']['recorded_at'] = '2027-01-%02dT06:00:00Z' % (index + 1)
            jobs.append(job)
        newest = ['b7', 'b6', 'b5', 'b4', 'b3']
        self.assertEqual([row['batch_id'] for row in self.queue(jobs)['rows']], newest)
        value = self.queue(jobs, job_ids=['b0', 'b5', 'nowhere', 'b0'])
        self.assertEqual([row['batch_id'] for row in value['rows']], newest + ['b0'])
        self.assertEqual((value['job_ids'], value['job_ids_missing']), (['b0', 'b5', 'nowhere'], ['nowhere']))
        self.assertEqual(value['rows'][-1]['state'], 'finished')
        self.assertEqual([row['batch_id'] for row in self.queue(jobs, finished=0, job_ids=['b1'])['rows']], ['b1'])
        self.assertNotIn('job_ids', self.queue(jobs))
        for bad in (['../x'], [''], ['b%d' % i for i in range(21)], [7]):
            with self.assertRaises(ValueError):
                self.queue(jobs, job_ids=bad)

    def test_the_queue_reads_only(self):
        write_run(self.root, 'seed', 'hunt', 'active', [done(30, 10), dict(status='running', started_unix=NOW - 60)], pause_file=True)
        torn = write_run(self.root, 'seed', 'torn', 'active', [dict(status='pending')])
        (torn / 'state.json').write_text('{', encoding='utf-8')
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob('*'))
        value = self.queue([self.job('live-batch', 'running')])
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob('*')), before)
        self.assertEqual(value['skipped'], [dict(batch_id='torn', kind='seed', reason='state.json or manifest.json is missing, too large or not whole JSON')])

    def test_a_start_refused_before_activation_and_a_no_edge_batch_say_what_they_are(self):
        unactivated = self.job('never-ran', 'starting')     # an intent, but no attempt folder was ever made
        with patch('studio_research_queue.batch_progress', return_value=dict(members_total=2, evidence='native_evidence_missing')):
            row = self.queue([unactivated])['rows'][0]
        self.assertEqual(row['state'], 'blocked')
        self.assertIn('retire-unactivated --job-id never-ran', row['note'])
        no_edge = dict(members_total=2, evidence='native_queue', status_counts=dict(native_error=2), members_no_edge=2, members_failed=0,
                       members_cancelled=0, qualifying=0)
        with patch('studio_research_queue.batch_progress', return_value=no_edge):
            row = self.queue([self.job('tested', 'failed')])['rows'][0]
        self.assertEqual((row['state'], row['members_done'], row['members_no_edge']), ('finished', 2, 2))


class CliTests(unittest.TestCase):
    def setUp(self):
        import test_seed_cli
        self.f = test_seed_cli.SeedCliTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)

    def test_discovery_lists_research_queue_as_read_only(self):
        from studio_research_authority import READ_OPERATIONS
        code, result = self.f.cli('discover')
        self.assertIn('research-queue', result['result']['operations'])
        contract = result['result']['operation_contracts']['research-queue']
        self.assertIn('read-only', contract['effect'])
        self.assertIn('redacts per strategy key and window', contract['effect'])
        self.assertIn('research-queue', READ_OPERATIONS)

    def test_cli_research_queue_is_read_only(self):
        state = Path(self.f.fixture.receipt['controller_state_root'])
        write_run(state, 'seed', 'hunt', 'active', [done(30, 10, qualifying=2), dict(status='running', started_unix=NOW - 60)])
        before = sorted((str(p), p.stat().st_mtime_ns) for p in state.rglob('*') if p.is_file())
        code, result = self.f.cli('research-queue')
        self.assertEqual(code, 0, result)
        self.assertEqual([(row['batch_id'], row['stage']) for row in result['result']['rows']], [('hunt', 'explore')])
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in state.rglob('*') if p.is_file()), before)


class DemoLaneTests(unittest.TestCase):
    def setUp(self):
        import test_demo_agent as demo_fixtures
        self.f = demo_fixtures.DemoAgentTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.agent = self.f.agent
        job = dict(job_id='g6', status='running', configuration=dict(batch_members=[dict(tester=TESTER), dict(tester=TESTER)]),
                   launch_intent=dict(attempt_id='a' * 64, recorded_at='2027-01-15T06:00:00Z'))
        jobs = patch.object(type(self.agent), '_jobs_readonly', lambda agent: [copy.deepcopy(job)]); jobs.start(); self.addCleanup(jobs.stop)

    def test_the_demo_lane_lists_the_batch_and_the_hunt(self):
        write_run(self.agent.root, 'seed', 'hunt', 'completed', [done(30, 10, qualifying=1)])
        value = self.agent.research_queue()
        self.assertEqual([(row['batch_id'], row['state']) for row in value['rows']], [('g6', 'running'), ('hunt', 'finished')])
        self.assertEqual(len(self.agent.research_queue(finished=0)['rows']), 1)

    def test_cli_job_id_is_passed_through(self):
        import demo_agent
        with patch('demo_agent.DemoAgent', return_value=self.agent), patch('builtins.print') as printed:
            self.assertEqual(demo_agent.main(['--installation', str(self.f.installation), 'research-queue', '--finished', '0',
                                              '--job-id', 'g6', '--job-id', 'gone']), 0)
        value = json.loads(printed.call_args.args[0])['result']
        self.assertEqual((value['job_ids'], value['job_ids_missing']), (['g6', 'gone'], ['gone']))


class HeldOutQueueTests(unittest.TestCase):
    """Each row's results are redacted per strategy key and window; progress and dates stay readable."""

    def setUp(self):
        import test_studio_heldout as heldout_fixtures
        self.h = heldout_fixtures
        self.f = heldout_fixtures.LeakWalkTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        root = self.f.c.root
        # seed-locked (manifest from the fixture: EURUSD H1 2026.06.01-2026.09.26, no strategy named) gets its state;
        # seed-free tested days before any lock.
        write_json(root / 'seeds' / 'seed-locked' / 'state.json', dict(schema_version=1, batch_id='seed-locked', status='completed', members=[
            dict(member_id='m1', alias='S1', status='completed', started_unix=NOW - 600, finished_unix=NOW - 300,
                 result=dict(summary=dict(qualifying_count=4, best_fitness=2.47)))]))
        write_run(root, 'seed', 'seed-free', 'completed', [done(30, 10, qualifying=3)], tester=dict(TESTER, FromDate='2025.01.01', ToDate='2025.06.30'))

    def rows(self):
        code, reply = self.f.cli('research-queue', '--finished', '10')
        self.assertEqual(code, 0, reply)
        return reply['result'], {row['batch_id']: row for row in reply['result']['rows']}

    def test_without_a_lock_every_result_is_readable(self):
        _, rows = self.rows()
        self.assertEqual((rows['seed-locked']['qualifying'], rows['seed-free']['qualifying']), (1, 1))
        self.assertIn('locked-batch', rows)

    def test_a_lock_redacts_the_rows_it_binds_and_keeps_the_free_ones(self):
        self.f.lock('alpha')
        result, rows = self.rows()
        locked = rows['seed-locked']
        self.assertEqual(locked['qualifying']['locked'], True)
        self.assertEqual(locked['qualifying_candidates']['locked'], True)
        self.assertEqual((locked['members_done'], locked['members_total'], locked['state'], locked['stage']), (1, 1, 'finished', 'explore'))
        self.assertEqual(rows['seed-free']['qualifying'], 1)
        self.assertEqual(self.h.leaks(rows['locked-batch']), [])
        self.assertEqual(result['locked_windows'][0]['strategy_key'], 'alpha')
        self.assertIn('never work around them', result['heldout']['plain'])

    def test_an_unverifiable_registry_redacts_every_result(self):
        self.f.lock('alpha')
        path = self.f.evidence / 'heldout' / 'locks.jsonl'
        path.write_bytes(path.read_bytes()[:-1])
        result, rows = self.rows()
        self.assertEqual(result['heldout']['code'], 'HELDOUT_REGISTRY_UNAVAILABLE')
        self.assertEqual(rows['seed-free']['qualifying']['locked'], True)
        self.assertEqual(rows['seed-free']['members_done'], 1)


if __name__ == '__main__':
    unittest.main()
