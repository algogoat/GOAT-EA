"""batch-pause-close (goatai#2350 6083618615): close a paused batch for good, deleting nothing.

The g20 fixture has the real shape: driver journal ``stopped: true, status: paused``, the studio.sqlite
queue job ``cancelled``, and a ``paused`` pause record with 1 of 19 members done. Every file is a
temporary fixture; nothing touches MT5, a terminal or a live state folder.
"""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from studio_bridge import write_json as _write_json
import studio_batch_close as close_module
import studio_batch_pause as pause
from studio_refusal import Refusal
import test_demo_agent as demo_fixtures
import test_studio_catchup as catchup_fixtures
import test_studio_holdup as holdup_fixtures

JOB = 'g20-rest1'
ATTEMPT = 'a' * 64
RUN = 'R0123456789ab'
MEMBERS = 19
NOW = 1_791_500_000.0
SYMBOLS = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD')


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, value)


def member(index):
    return dict(tester=dict(Symbol=SYMBOLS[index % len(SYMBOLS)], Period='M1', FromDate='2025.01.01', ToDate='2026.06.01'),
                export=dict(IncludeBackOOS='true'), strategy=dict(values=dict(Grid_Size=float(index))))


class G20Fixture(unittest.TestCase):
    """The demo agent fixture plus a g20-shaped paused batch."""

    def setUp(self):
        self.f = demo_fixtures.DemoAgentTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.agent = self.f.agent
        self.agent.clock = lambda: NOW
        self.root = self.agent.root
        self.common = Path(self.agent.install['common_files_root'])
        self.started = {0}
        self.job = self.g20_job()
        self.queue = [self.job]
        self.write_queue()
        # Driver journal exactly as g20's: stopped by the pause.
        write_json(self.root / 'batch-drivers' / (JOB + '.json'),
                   dict(schema_version=2, attempt_id=ATTEMPT, binding=dict(job_id=JOB, generation=4), stopped=True,
                        status='paused', cancel_issued=False, max_seconds=172800))
        result = self.root / 'attempts' / ATTEMPT / 'result.json'
        write_json(result, self.job['completion'])
        digest = hashlib.sha256(result.read_bytes()).hexdigest()
        self.record = dict(schema_version=1, job_id=JOB, pause_id='p' * 32, attempt_id=ATTEMPT, configuration_sha256='c' * 64,
                           generation=4, state='paused', phase='paused', mode='safe_point', escalation=None,
                           requested_utc=NOW - 7200, requested_by='agent', cancels=[], blocker=None, failure=None,
                           member_watch={}, adopted_stop=False, history=[dict(at=NOW - 7200, phase='paused')],
                           result_path=str(result), result_sha256=digest, members_completed=1, members_remaining=MEMBERS - 1,
                           members_failed=0, members_no_edge=0, paused_utc=NOW - 3600, batch_status='cancelled',
                           resume_token=pause.resume_token(JOB, ATTEMPT, digest))
        self.write_record()
        # The package: native run folder and the source SET shas (what finish and the trial journal read).
        package = self.root / 'packages' / JOB
        write_json(package / 'manifest.json', dict(native_run_relative='GOAT\\' + RUN, jobs=[
            dict(run_alias='m%02d' % i) for i in range(MEMBERS)]))
        write_json(self.root / 'packages' / (JOB + '.source.json'),
                   dict(members=[dict(set_sha256=('%02d' % i) * 32) for i in range(MEMBERS)]))
        export = self.common / 'GOAT' / RUN / 'deploy' / 'm00' / 'EURUSD' / 'GOAT EURUSD,M1_Trds=40_Prf=120.set'
        export.parent.mkdir(parents=True)
        export.write_bytes('Grid_Size=0\r\n'.encode('utf-16'))
        self.export = export
        self.export_sha = hashlib.sha256(export.read_bytes()).hexdigest()

    def g20_job(self):
        outcomes = [dict(index=i, run_alias='m%02d' % i, symbol=SYMBOLS[i % len(SYMBOLS)],
                         status='native_completed' if i == 0 else 'native_cancelled') for i in range(MEMBERS)]
        history = [dict(native=dict(members=[dict(index=i, status='native_ongoing' if i in self.started else 'native_queued')
                                             for i in range(MEMBERS)]))]
        completion = dict(schema_version=1, job_id=JOB, attempt_id=ATTEMPT, status='cancelled', member_outcomes=outcomes,
                          research_outcomes=[], configuration_sha256='c' * 64)
        return dict(job_id=JOB, status='cancelled', configuration_sha256='c' * 64,
                    configuration=dict(batch_members=[member(i) for i in range(MEMBERS)]),
                    launch_intent=dict(attempt_id=ATTEMPT, package=str(self.root / 'packages' / JOB), recorded_at='2026-10-09T12:00:00Z'),
                    completion=completion, completion_path=str(self.root / 'attempts' / ATTEMPT / 'result.json'),
                    native_evidence_history=history)

    def write_queue(self, fixed_task=None):
        binding = packed(dict(terminal_id=self.agent.session['terminal_id'], run_id=self.agent.session['run_id']))
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            db.execute('CREATE TABLE IF NOT EXISTS studio_queues(binding TEXT PRIMARY KEY, jobs TEXT)')
            db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', (binding, json.dumps(self.queue)))
            if fixed_task is not None:
                db.execute('CREATE TABLE IF NOT EXISTS studio_fixed_tasks(released INTEGER)')
                db.execute('INSERT INTO studio_fixed_tasks VALUES(?)', (fixed_task,))
            db.commit()

    def write_record(self, **changes):
        write_json(pause.path(self.root, JOB), dict(self.record, **changes))

    def files(self):
        return {str(p): p.read_bytes() for base in (self.root, self.common) for p in base.rglob('*') if p.is_file() and p.name != 'terminal.lock'}

    def close(self, **kw):
        kw.setdefault('confirm', True)
        return self.agent.batch_pause_close(JOB, **kw)

    def refused(self, code, **kw):
        before = self.files()
        with self.assertRaises(Refusal) as caught:
            self.close(**kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        after = self.files()
        self.assertEqual(after, before, 'a refusal wrote something')
        return caught.exception


class FinishTests(G20Fixture):
    def test_finish_closes_g20_keeps_every_file_and_lists_the_unrun_members(self):
        before = self.files()
        result = self.close()
        self.assertTrue(result['changed'])
        self.assertEqual((result['state'], result['closed_mode'], result['closed_by']), ('closed', 'finish', 'demo_agent'))
        self.assertEqual(result['closed_at'], '2026-10-08T22:53:20Z')
        self.assertEqual((result['members_done_count'], result['members_unrun_count']), (1, 18))
        self.assertEqual([m['index'] for m in result['members_unrun']], list(range(1, 19)))
        self.assertEqual({m['started'] for m in result['members_unrun']}, {False})
        self.assertEqual(result['members_done'], [dict(index=0, member_id='m00', configuration_sha256=sha(member(0)),
                                                       set_sha256='00' * 32, symbol='EURUSD', timeframe='M1',
                                                       outcome='completed', start_known=True)])
        record = pause.load(self.root, JOB)
        self.assertEqual(record['state'], 'closed')
        self.assertNotIn('reason', record)
        # Deletes nothing: every file that existed is byte-identical, except the pause record and the action log.
        after = self.files()
        changed = {path for path in before if after.get(path) != before[path]}
        self.assertEqual(changed, {str(pause.path(self.root, JOB))})
        self.assertFalse((self.root / close_module.EXCLUSIONS).exists())
        # Kept fields of the paused record: the result binding, the resume token and the history.
        for key in ('result_path', 'result_sha256', 'resume_token', 'members_completed', 'pause_id'):
            self.assertEqual(record[key], self.record[key])
        self.assertEqual(record['history'][-1]['phase'], 'closed')
        actions = [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]
        self.assertEqual([(a['operation'], a['mode'], a['members_done'], a['members_unrun']) for a in actions],
                         [('batch_pause_close', 'finish', 1, 18)])

    def test_finish_is_the_default_and_a_later_resume_or_continue_refuses(self):
        self.close()
        with self.assertRaises(Refusal) as caught:
            self.agent.batch_resume(JOB)
        self.assertEqual(caught.exception.code, 'BATCH_CLOSED')
        self.assertIn('never resumes', str(caught.exception))
        with self.assertRaises(Refusal) as caught:
            self.agent.continue_batch(JOB)
        self.assertEqual(caught.exception.code, 'BATCH_CLOSED')
        self.assertIn('never resumes', str(pause.refusal(pause.load(self.root, JOB))))
        # The core resume entry point refuses too (batch-continue, batch-resume, resume-batch all reach it).
        from studio_batch import resume_batch
        from types import SimpleNamespace
        with self.assertRaises(Refusal):
            resume_batch(SimpleNamespace(root=self.root, job=lambda _: self.fail('read past the refusal')), JOB, JOB + '-r1')
        self.assertFalse((self.root / 'batch-lineage').exists())

    def test_a_started_then_cancelled_member_is_a_trial_and_unknown_starts_count(self):
        self.started = {0, 1}
        self.queue = [self.g20_job()]; self.write_queue()
        result = self.close()
        self.assertEqual([(m['index'], m['outcome']) for m in result['members_done']], [(0, 'completed'), (1, 'cancelled')])
        self.assertEqual(result['members_unrun'][0]['started'], True)
        job = self.g20_job(); job.pop('native_evidence_history')
        done, unrun = close_module.member_identities(self.root, job, job['completion']['member_outcomes'])
        self.assertEqual(len(done), MEMBERS)          # no history: every cancelled member counts (worst case)
        self.assertEqual({m['start_known'] for m in done[1:]}, {False})
        self.assertEqual({m['started'] for m in unrun}, {None})


class IdempotencyTests(G20Fixture):
    def test_same_mode_is_a_no_op_and_another_mode_refuses(self):
        first = self.close(mode='finish')
        record = pause.path(self.root, JOB).read_bytes()
        again = self.close(mode='finish')
        self.assertFalse(again['changed'])
        self.assertEqual(again['closed_at'], first['closed_at'])
        self.assertEqual(pause.path(self.root, JOB).read_bytes(), record)
        error = self.refused('CLOSE_MODE_CONFLICT', mode='exclude', reason='late change of mind')
        self.assertEqual(error.fields['closed_mode'], 'finish')

    def test_exclude_twice_is_a_no_op_and_repairs_a_lost_marker(self):
        self.close(mode='exclude', reason='broker feed gap on 10-08')
        marker = close_module.exclusion_path(self.root, JOB)
        content = marker.read_bytes()
        self.assertFalse(self.close(mode='exclude', reason='other words')['changed'])
        self.assertEqual(pause.load(self.root, JOB)['reason'], 'broker feed gap on 10-08')
        marker.unlink()             # an interruption between the record and the marker
        self.assertFalse(self.close(mode='exclude', reason='broker feed gap on 10-08')['changed'])
        self.assertEqual(json.loads(marker.read_bytes()), json.loads(content))
        self.refused('CLOSE_MODE_CONFLICT', mode='finish')


class RefusalTests(G20Fixture):
    def test_missing_confirm_refuses_first(self):
        self.refused('CLOSE_CONFIRM_REQUIRED', confirm=False)

    def test_running_pausing_and_pause_failed_refuse(self):
        self.queue = [dict(self.job, status='running')]; self.write_queue()
        self.write_record(state='pausing', phase='waiting_safe_point')
        self.refused('CLOSE_TERMINAL_BUSY')
        self.queue = [self.job]; self.write_queue()
        error = self.refused('CLOSE_NOT_PAUSED')
        self.assertEqual(error.fields['pause_state'], 'pausing')
        self.write_record(state='pause_failed', phase='pause_failed', failure=dict(code='x', message='m', fix='f'))
        self.assertEqual(self.refused('CLOSE_NOT_PAUSED').fields['pause_state'], 'pause_failed')
        self.write_record(state='resumed', phase='resumed', successor_batch_id=JOB + '-r1')
        self.refused('CLOSE_NOT_PAUSED')

    def test_no_pause_unknown_batch_and_a_driver_that_has_not_stopped_refuse(self):
        pause.path(self.root, JOB).unlink()
        self.refused('CLOSE_NO_PAUSE')
        self.write_record()
        with self.assertRaises(Refusal) as caught:
            self.agent.batch_pause_close('other', confirm=True)
        self.assertEqual(caught.exception.code, 'CLOSE_UNKNOWN_BATCH')
        journal = self.root / 'batch-drivers' / (JOB + '.json')
        write_json(journal, dict(json.loads(journal.read_text()), stopped=False, status='running'))
        self.refused('CLOSE_DRIVER_NOT_STOPPED')

    def test_changed_result_refuses(self):
        self.write_record(result_sha256='0' * 64)
        self.refused('CLOSE_RESULT_CHANGED')

    def test_terminal_busy_seed_slot_fixed_task_another_batch_or_the_lock(self):
        write_json(self.root / 'seed-active.json', dict(status='active', batch_id='seedhunt-1'))
        self.assertIn('seed slot', str(self.refused('CLOSE_TERMINAL_BUSY')))
        (self.root / 'seed-active.json').unlink()
        self.write_queue(fixed_task=0)
        self.assertIn('fixed task', str(self.refused('CLOSE_TERMINAL_BUSY')))
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            db.execute('UPDATE studio_fixed_tasks SET released=1'); db.commit()
        self.queue = [self.job, dict(self.g20_job(), job_id='g21', status='pending', launch_intent=dict(attempt_id='b' * 64))]
        self.write_queue()
        self.assertIn('g21', str(self.refused('CLOSE_TERMINAL_BUSY')))
        self.queue = [self.job]; self.write_queue()
        with self.agent._exclusive():
            self.refused('CLOSE_TERMINAL_BUSY')
        self.assertTrue(self.close()['changed'])

    def test_live_driver_refuses(self):
        worker = self.root / 'demo-agent' / 'workers' / 'g21.json'
        write_json(worker, dict(batch_id='g21', nonce='n' * 32, pid=5))
        with patch.object(self.agent, '_worker_alive', return_value=True):
            self.assertIn('live GOAT batch driver', str(self.refused('CLOSE_TERMINAL_BUSY')))

    def test_planned_successor_that_may_have_run_refuses(self):
        self.write_record(resume_batch_id=JOB + '-r1')
        self.queue = [self.job, dict(self.g20_job(), job_id=JOB + '-r1', status='cancelled')]; self.write_queue()
        self.refused('CLOSE_SUCCESSOR_PLANNED')
        # A successor cancelled before it ever started never ran: the close proceeds.
        self.queue = [self.job, dict(job_id=JOB + '-r1', status='cancelled', configuration_sha256='d' * 64)]; self.write_queue()
        self.assertTrue(self.close()['changed'])

    def test_non_demo_session_refuses(self):
        self.agent.session['demo_only'] = False
        self.refused('CLOSE_NOT_DEMO')


class ExcludeTests(G20Fixture):
    def test_exclude_needs_a_reason(self):
        self.refused('CLOSE_REASON_REQUIRED', mode='exclude')
        self.refused('CLOSE_REASON_REQUIRED', mode='exclude', reason='   ')

    def test_exclude_writes_the_marker_and_deletes_nothing(self):
        before = self.files()
        result = self.close(mode='exclude', reason='Data feed gap on 10-08')
        self.assertEqual((result['closed_mode'], result['reason'], result['members_done_count']), ('exclude', 'Data feed gap on 10-08', 1))
        self.assertEqual(result['exclusion']['run_id'], RUN)
        marker = json.loads(close_module.exclusion_path(self.root, JOB).read_text())
        self.assertEqual(marker['exports'], [dict(set_path=str(self.export), set_sha256=self.export_sha)])
        after = self.files()
        self.assertTrue(all(path in after for path in before))
        self.assertTrue(self.export.is_file())
        rows = close_module.apply_exclusions([dict(run_id=RUN, status='behind', set_sha256='x'),
                                              dict(run_id=None, status='current', set_sha256=self.export_sha),
                                              dict(run_id='Rother', status='behind', set_sha256='y')],
                                             close_module.exclusions(self.root))
        self.assertEqual([r['status'] for r in rows], ['ineligible', 'ineligible', 'behind'])
        self.assertTrue(rows[0]['excluded'] and rows[1]['excluded'])
        self.assertIn('Data feed gap on 10-08', rows[0]['reasons'][-1])

    def test_exclude_refuses_after_a_foos_read(self):
        write_json(self.root / 'catchups' / 'cu-g20' / 'manifest.json',
                   dict(members=[dict(source_path=str(self.export), source_sha256=self.export_sha)]))
        error = self.refused('CLOSE_EXCLUDE_AFTER_FOOS_READ', mode='exclude', reason='late')
        self.assertEqual(error.fields['reads'][0]['run_id'], 'cu-g20')
        # A hold-up test of a library copy (outside the run folder) is matched by the SET sha256.
        (self.root / 'catchups' / 'cu-g20' / 'manifest.json').unlink()
        write_json(self.root / 'holdups' / 'h1' / 'manifest.json',
                   dict(members=[dict(source_path='C:\\library\\copy.set', source_sha256=self.export_sha)]))
        self.refused('CLOSE_EXCLUDE_AFTER_FOOS_READ', mode='exclude', reason='late')
        # finish stays available: the results are part of the record.
        self.assertTrue(self.close(mode='finish')['changed'])

    def test_exclude_refuses_after_a_selection_or_when_it_cannot_check(self):
        locks = [dict(lock_id='l' * 64, strategy_key='banker', candidate=[dict(symbol='EURUSD', timeframe='M1', set_sha256=self.export_sha)])]
        with patch('studio_heldout.read_registry', return_value=dict(state='ok', locks=locks)):
            self.refused('CLOSE_EXCLUDE_AFTER_SELECTION', mode='exclude', reason='late')
        with patch('studio_heldout.read_registry', return_value=dict(state='unavailable', error='broken chain', locks=[])):
            self.refused('CLOSE_EXCLUDE_UNVERIFIABLE', mode='exclude', reason='late')
        (self.root / 'catchups' / 'bad').mkdir(parents=True)
        (self.root / 'catchups' / 'bad' / 'manifest.json').write_text('{not json')
        self.refused('CLOSE_EXCLUDE_UNVERIFIABLE', mode='exclude', reason='late')


class StatusTests(G20Fixture):
    def test_research_status_and_queue_read_closed_as_terminal_history(self):
        with patch.object(self.agent, '_worker_alive', side_effect=AssertionError('no worker file')):
            before = self.agent.research_status()['activity']
        self.assertEqual(before['status'], 'paused')
        self.close()
        with patch.object(self.agent, '_worker_alive', side_effect=AssertionError('no worker file')):
            activity = self.agent.research_status()['activity']
        self.assertEqual(activity['status'], 'closed')
        self.assertEqual((activity['pause']['state'], activity['pause']['closed_mode'], activity['pause']['members_unrun_count']),
                         ('closed', 'finish', 18))
        self.assertIn('closed', activity['headline'])
        self.assertIn('never resumes', activity['headline'])
        self.assertNotIn('Paused', activity['headline'])
        row = next(r for r in self.agent.research_queue()['rows'] if r['batch_id'] == JOB)
        self.assertEqual(row['state'], 'stopped')
        self.assertIn('18 unrun members', row['note'])

    def test_a_closed_parent_is_not_held_and_a_later_batch_is_current(self):
        self.close()
        later = dict(job_id='g21', status='completed', configuration_sha256='e' * 64, configuration=dict(batch_members=[member(0)]))
        self.queue = [self.job, later]; self.write_queue()
        with patch.object(self.agent, '_worker_alive', side_effect=AssertionError('no worker file')):
            activity = self.agent.research_status()['activity']
        self.assertEqual(activity['batch_id'], 'g21')


class SameShapeTests(unittest.TestCase):
    """The finish record (attempts/<attempt>/result.json) and the close record carry one members_done shape."""

    def test_finished_batch_record_carries_members_done(self):
        import test_studio_benchmark
        fixture = test_studio_benchmark.BenchmarkTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        result = json.loads(fixture.result_path.read_text(encoding='utf-8'))
        config = fixture.c.job('customer-batch')['configuration']
        self.assertEqual([(m['index'], m['outcome'], m['configuration_sha256']) for m in result['members_done']],
                         [(i, 'completed', sha(config['batch_members'][i])) for i in range(2)])
        self.assertEqual(fixture.c.job('customer-batch')['completion']['members_done'], result['members_done'])
        g20 = G20Fixture(); g20.setUp(); self.addCleanup(g20.doCleanups)
        closed = g20.close()['members_done']
        self.assertEqual({tuple(sorted(m)) for m in result['members_done']}, {tuple(sorted(m)) for m in closed})
        # On the g20 fixture, the finish record would carry exactly what the close record carries.
        completion = g20.job['completion']
        self.assertEqual(close_module.member_identities(g20.root, g20.job, completion['member_outcomes'],
                                                        completion['research_outcomes'])[0], closed)


class EvidenceScanExclusionTests(catchup_fixtures.CatchupCase):
    def test_scan_marks_every_export_of_an_excluded_run_and_catchup_never_retests_it(self):
        base = catchup_fixtures.sc.evidence_scan([self.run], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root)
        self.assertEqual(base['summary']['counts']['behind'], 2)
        write_json(self.controller.root / close_module.EXCLUSIONS / 'g20-rest1.json',
                   dict(schema=close_module.EXCLUSION_SCHEMA, batch_id='g20-rest1', reason='feed gap', run_id='Rrun1',
                        closed_at='2026-10-09T20:30:00Z', exports=[]))
        scan = catchup_fixtures.sc.evidence_scan([self.run], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root)
        self.assertEqual({row['status'] for row in scan['exports']}, {'ineligible'})
        self.assertTrue(all(row['excluded'] and row['excluded_batch_id'] == 'g20-rest1' for row in scan['exports']))
        # Without a controller root (no markers to read) the scan is unchanged.
        self.assertEqual(catchup_fixtures.sc.evidence_scan([self.run], now=catchup_fixtures.AFTER_CLOSE)['summary']['counts']['behind'], 2)
        with self.assertRaisesRegex(ValueError, 'Nothing to catch up'):
            self.runner.prepare('cu1', self.plan())
        (self.controller.root / close_module.EXCLUSIONS / 'g20-rest1.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'goat-batch-exclusion-v1'):
            catchup_fixtures.sc.evidence_scan([self.run], now=catchup_fixtures.AFTER_CLOSE, controller_root=self.controller.root)


class HoldupExclusionTests(unittest.TestCase):
    """Hold-up prepare honours batch-exclusions/<id>.json like evidence-scan and catchup-prepare (Mac, #203)."""

    def setUp(self):
        # The hold-up fixture as an instance (not a base class), so its own tests are not collected twice.
        f = holdup_fixtures.HoldupTests(); f.setUp(); self.addCleanup(f.doCleanups); self.addCleanup(f.tearDown)
        self.f, self.c, self.root, self.runner, self.source, self.plan = f, f.c, f.root, f.runner, f.source, f.plan

    def marker(self, **fields):
        write_json(self.c.root / close_module.EXCLUSIONS / 'g20-rest1.json',
                   dict(dict(schema=close_module.EXCLUSION_SCHEMA, batch_id='g20-rest1', reason='feed gap', run_id='Rnone',
                             run_root=str(self.root / 'elsewhere'), closed_at='2026-10-09T20:30:00Z', exports=[]), **fields))

    def test_hold_up_prepare_sourced_from_an_excluded_export_refuses(self):
        self.assertEqual(self.runner.validate(self.plan())['valid'], True)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.marker(exports=[dict(set_path='C:\\copy.set', set_sha256=digest)])          # by the exact SET sha256
        for call in (self.runner.validate, lambda plan: self.runner.prepare('h1', plan)):
            with self.assertRaises(Refusal) as caught:
                call(self.plan())
            self.assertEqual((caught.exception.code, caught.exception.fields['batch_id']), ('HOLDUP_SOURCE_EXCLUDED', 'g20-rest1'))
            self.assertIn('feed gap', str(caught.exception))
        self.assertFalse(self.runner.path('h1').exists())
        self.marker(run_root=str(self.source.parent))                                     # by a path inside the run folder
        with self.assertRaises(Refusal):
            self.runner.prepare('h1', self.plan())
        self.assertFalse(self.runner.path('h1').exists())
        self.marker()                                                                     # another batch's exclusion
        self.assertEqual(self.runner.prepare('h1', self.plan())['status'], 'prepared')


if __name__ == '__main__':
    unittest.main()
