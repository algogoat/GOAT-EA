"""settle-refused-start, then restore-lane (goatai#1885, tester a649295d "Jan").

Jan's exact shape: a customer-lane terminal (studio bootstrap) that a beta.15 EA update moved
to demo_direct; his agent then ran demo prepare-batch/run-batch. The config start reached
restart phase controls_installed (attempt folder, installed controls owned by the attempt,
report folders, the copied native queue), issued the arm_restart request and its permit, and
the EA answered START_PROTOCOL_NOT_QUALIFIED without consuming it. The driver shows
start_uncertain and the queue reconcile_required; an older batch settled by an earlier
self-repair (ticket a4611b65) is still in the queue.

retire-unactivated refuses this shape (controls were installed). settle-refused-start settles
it with the reviewed self-repair proof and settlement, then restore-lane accepts the logged
demo-lane work because every batch it touched is proven never started for its exact attempt.
Real controller store and files; MT5, the broker SDK and the terminal lock are mocked.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from demo_agent import DemoAgent, digest
from native_control_transaction import NAMES
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import operation
from studio_self_repair import refused_start_action_id
import test_studio_self_repair as repair_fixtures

OLD = 'atlas-0929'                      # the batch an earlier self-repair retired (a4611b65)


class JanRefusedStartTests(repair_fixtures.SelfRepairFixture):
    def setUp(self):
        super().setUp()
        c = self.c
        # The 10-01 restart arm: controls installed, arm issued with its permit, the EA refused it.
        job = c.job('original')
        self.startup = 'e' * 64
        job['restart_intent'] = dict(attempt_id=self.attempt, phase='controls_installed', startup_sha256=self.startup,
                                     history=[dict(phase='prepared', at=1.0), dict(phase='controls_installed', at=2.0)])
        job['status'] = 'reconcile_required'
        old = {k: v for k, v in job.items() if k not in ('launch_intent', 'reservation', 'restart_intent')} | dict(
            job_id=OLD, status='failed', completion_path='retained',
            completion=dict(classification='retired_never_started', executed_members=0, attempt_id='d' * 64))
        self.store_queue([old, job])
        start = read_json(self.gate / ('issued-' + self.attempt + '.json'))['request']
        for identity in (self.attempt, self.cancel):
            for prefix in ('issued-', 'result-'):
                (self.gate / (prefix + identity + '.json')).unlink(missing_ok=True)
        (self.gate / 'permit.json').unlink(missing_ok=True)
        self.issue(self.attempt, start | dict(action='arm_restart', startup_sha256=self.startup))
        self.set_arm_status('START_PROTOCOL_NOT_QUALIFIED')
        issued = read_json(self.gate / ('issued-' + self.attempt + '.json'))
        write_json(self.gate / 'permit.json', dict(request_sha256=issued['request_sha256']))
        drivers = c.root / 'batch-drivers'; drivers.mkdir(exist_ok=True)
        write_json(drivers / 'original.json', dict(schema_version=2, binding=dict(job_id='original'),
                   status='start_uncertain', start_issued=True, attempt_id=self.attempt, cancel_issued=False,
                   stopped=False, last_error='Native arming refused; preserve receipt and do not relaunch'))
        self.before = c.job('original')
        self.old_before = c.job(OLD)
        # The lane: customer bootstrap session retained by the beta.15 update, then moved to demo_direct.
        # The tester's receipt lives in the controller state root, where the demo scope reads it.
        self.receipt = c.root / 'installation.json'
        self.receipt.write_bytes(Path(self.f.fixture.path).read_bytes())
        self.agent = DemoAgent(self.receipt, process=self.process)
        backups = self.agent.state_root / 'backups'; backups.mkdir(parents=True)
        staged = backups / 'staged.json'; staged.write_bytes((c.root / 'session.json').read_bytes())
        staged.rename(backups / ('session-' + digest(staged) + '.json'))
        session = read_json(c.root / 'session.json') | dict(authority_kind='demo_direct')
        (c.root / 'session.json').write_text(json.dumps(session), encoding='utf-8')
        self.agent.session = c.session = session
        self.agent._append('install_build', 'local_identity_verified', authority_kind='demo_direct')
        self.agent._append('studio_prepare_batch', 'intent', batch_id='original')
        self.agent._append('studio_prepare_batch', 'verified', batch_id='original')
        self.agent._append('studio_run_batch', 'worker_reserved', batch_id='original')
        self.agent._append('studio_run_batch', 'supervising', batch_id='original')
        self.agent._append('studio_run_batch', 'returned', batch_id='original', status='start_uncertain',
                           attempt_id=self.attempt)
        patch.object(self.agent, '_broker', return_value=dict(process=self.native['process'], login='123456',
                                                              server='Customer-Demo', demo=True)).start()

    # ------------------------------------------------------------------ helpers

    def state(self):
        with operation('state'):                    # a read; the demo lane refuses raw mutations
            return self.c.state()

    def job(self, job_id):
        with operation('state'):
            return self.c.job(job_id)

    def store_queue(self, jobs):
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(jobs), binding))
        self.c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
        self.c.store.db.commit()

    def update_job(self, job_id, **fields):
        state = self.state()
        self.store_queue([row | fields if row['job_id'] == job_id else row for row in state['queue']])

    def set_arm_status(self, status):
        path = self.gate / ('result-' + self.attempt + '.json')
        write_json(path, read_json(path) | dict(status=status))

    def lane(self):
        return read_json(self.c.root / 'session.json')['authority_kind']

    def log(self):
        return [json.loads(line) for line in (self.agent.state_root / 'actions.jsonl').read_text().splitlines()]

    def assert_settle_refused(self, reason):
        with self.assertRaisesRegex(ValueError, reason):
            self.agent.settle_refused_start('original')
        self.process.close.assert_not_called(); self.process.start.assert_not_called()
        self.assertEqual(self.job('original'), self.before)
        self.assertTrue((self.gate / 'request.json').exists())
        self.assertTrue((self.base / 'agent-native-control-owner.json').exists())
        last = self.log()[-1]
        self.assertEqual((last['operation'], last['phase'], last['native_action']), ('settle_refused_start', 'refused', False))
        # Nothing settled, so restore-lane still refuses (the batch is unproven and still active).
        with self.assertRaisesRegex(ValueError, 'not proven never-started'):
            self.agent.restore_lane()
        self.assertEqual(self.lane(), 'demo_direct')

    def settle(self):
        result = self.agent.settle_refused_start('original')
        self.assertEqual(result['status'], 'settled_never_started', result)
        return result

    # ------------------------------------------------------------------ Jan end to end

    def test_jan_shape_settles_then_restore_lane_previews_and_applies(self):
        # Ground truth: retire-unactivated (#123) refuses this shape. Its logged intent changes nothing.
        with self.assertRaisesRegex(ValueError, 'restart phase controls_installed'):
            self.agent.retire_unactivated('original')
        self.assertEqual(self.job('original'), self.before)
        with self.assertRaisesRegex(ValueError, 'original is not proven never-started'):
            self.agent.restore_lane()

        result = self.settle()
        self.assertEqual(result['receipt_evidence'], 'refused:START_PROTOCOL_NOT_QUALIFIED')
        self.assertFalse(result['native_cancellation_claimed'])
        self.assertIn('launch-terminal', result['next_action'])
        self.process.close.assert_called_once_with(self.native['process']); self.process.start.assert_not_called()
        job = self.job('original')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual((job['completion']['classification'], job['completion']['executed_members']),
                         ('retired_never_started', 0))
        self.assertEqual(job['launch_intent'], self.before['launch_intent'])          # evidence kept
        self.assertEqual(self.job(OLD), self.old_before)                           # the older row is untouched
        self.assertFalse(any((self.base / n).exists() for n in NAMES))
        self.assertFalse((self.base / 'agent-native-control-owner.json').exists())
        self.assertFalse((self.gate / 'request.json').exists()); self.assertFalse((self.gate / 'permit.json').exists())
        for prefix in ('issued-', 'result-'):
            self.assertTrue((self.gate / (prefix + self.attempt + '.json')).exists())
        self.assertEqual((self.common / 'queue.GOAT').read_bytes(), self.queue_raw)
        record = read_json(Path(result['record_path']))
        self.assertEqual(Path(result['record_path']).name, 'original-' + self.attempt[:16] + '.json')
        self.assertEqual((record['kind'], record['attempt_id'], record['action_id']),
                         ('settled_refused_start', self.attempt, refused_start_action_id('original', self.attempt)))
        self.assertEqual([row['phase'] for row in self.log() if row['operation'] == 'settle_refused_start'],
                         ['intent', 'settled'])
        # Replay-safe: the retained outcome, no second close.
        self.assertEqual(self.agent.settle_refused_start('original')['record_path'], result['record_path'])
        self.process.close.assert_called_once()

        flipped = (self.c.root / 'session.json').read_bytes()
        preview = self.agent.restore_lane()
        self.assertEqual((preview['status'], preview['restores_to']), ('ready_to_restore', 'native_human_control'))
        self.assertEqual(preview['never_started_batches'], {'original': 'settled_refused_start'})
        self.assertEqual((self.c.root / 'session.json').read_bytes(), flipped, 'a preview writes nothing')
        applied = self.agent.restore_lane(apply=True)
        self.assertEqual(applied['status'], 'restored')
        self.assertEqual(self.lane(), 'native_human_control')
        self.assertEqual(self.agent.restore_lane(apply=True)['status'], 'already_customer_lane')

    def test_cli_settles_by_batch_id(self):
        import demo_agent
        with patch('demo_agent.DemoAgent', return_value=self.agent), patch('builtins.print') as printed:
            self.assertEqual(demo_agent.main(['--installation', str(self.receipt),
                                              'settle-refused-start', '--batch-id', 'original']), 0)
        self.assertEqual(json.loads(printed.call_args.args[0])['result']['status'], 'settled_never_started')

    # ------------------------------------------------------------------ settle refusals

    def test_a_consumed_start_refuses(self):
        (self.gate / ('consumed-' + self.attempt + '.json')).write_bytes((self.gate / 'request.json').read_bytes())
        self.assert_settle_refused('consum')

    def test_a_receipt_that_is_not_a_pre_consumption_refusal_refuses(self):
        for status in ('RESTART_ARMED_RECONCILE', 'HUMAN_CANCEL_RETAINED', 'NATIVE_CONTROL_DRIFT', 'SOMETHING_NEW'):
            with self.subTest(status):
                self.set_arm_status(status)
                self.assert_settle_refused('pre-consumption refusal')

    def test_a_second_unsettled_batch_refuses(self):
        self.update_job(OLD, status='reconcile_required')
        self.before = self.job('original')
        self.assert_settle_refused('only unsettled batch')

    def test_owner_stop_refuses_and_a_refused_attempt_never_blocks_the_later_restore(self):
        stop = self.agent.state_root / 'STOP'; stop.write_text('{"actor":"demo_agent"}')
        self.assert_settle_refused('Owner STOP')
        self.assertTrue(stop.exists())
        stop.unlink()
        self.settle()
        self.assertEqual([row['phase'] for row in self.log() if row['operation'] == 'settle_refused_start'],
                         ['intent', 'refused', 'intent', 'settled'])
        self.assertEqual(self.agent.restore_lane()['status'], 'ready_to_restore')

    def test_a_start_without_a_restart_arm_is_not_a_refused_start(self):
        state = self.state()
        self.store_queue([{k: v for k, v in row.items() if k != 'restart_intent'} for row in state['queue']])
        with self.assertRaisesRegex(ValueError, 'no restart-arm start attempt'):
            self.agent.settle_refused_start('original')
        self.process.close.assert_not_called()

    # ------------------------------------------------------------------ restore-lane allowance

    def test_a_batch_that_activated_still_refuses(self):
        self.settle()
        state = self.state()
        done = dict(state['queue'][1], job_id='activated-batch', status='completed',
                    completion=dict(status='completed', attempt_id=self.attempt))
        self.store_queue(state['queue'] + [done])
        self.agent._append('studio_run_batch', 'returned', batch_id='activated-batch', status='completed')
        with self.assertRaisesRegex(ValueError, 'activated-batch is not proven never-started'):
            self.agent.restore_lane()
        self.assertEqual(self.lane(), 'demo_direct')

    def test_a_settled_batch_plus_any_other_demo_operation_still_refuses(self):
        self.settle()
        log = self.agent.state_root / 'actions.jsonl'
        settled = log.read_bytes()
        for operation, fields in (('seed_promote', dict(batch_id='original')), ('stop_batch', dict(batch_id='original')),
                                  ('clear_stop', {}), ('continue_batch', dict(batch_id='original')),
                                  ('studio_cancel_pending', dict(batch_id='original')), ('deploy_load', {}),
                                  ('studio_run_batch', {}), ('studio_run_batch', dict(batch_id='../escape'))):
            with self.subTest(operation=operation, fields=fields):
                log.write_bytes(settled)
                self.agent._append(operation, 'done', **fields)
                with self.assertRaisesRegex(ValueError, 'owner demo-lane work'):
                    self.agent.restore_lane()
        log.write_bytes(settled)
        self.assertEqual(self.agent.restore_lane()['status'], 'ready_to_restore')
        self.assertEqual(self.lane(), 'demo_direct')

    def test_a_settlement_record_for_another_attempt_refuses(self):
        result = self.settle()
        path = Path(result['record_path'])
        record = read_json(path)
        for change in (dict(attempt_id='f' * 64), dict(action_id='0' * 8 + record['action_id'][8:]),
                       dict(kind='retired_never_activated'), dict(job_id=OLD)):
            with self.subTest(change):
                write_json(path, record | change)
                with self.assertRaisesRegex(ValueError, 'original is not proven never-started'):
                    self.agent.restore_lane()
        write_json(path, record)
        journal = self.c.root / 'self-repair' / record['action_id'] / 'transaction.json'
        complete = read_json(journal)
        write_json(journal, complete | dict(phase='controls_restored'))
        with self.assertRaisesRegex(ValueError, 'original is not proven never-started'):
            self.agent.restore_lane()
        write_json(journal, complete)
        path.rename(path.with_name('original-' + 'f' * 16 + '.json'))
        with self.assertRaisesRegex(ValueError, 'original is not proven never-started'):
            self.agent.restore_lane()
        self.assertEqual(self.lane(), 'demo_direct')

    def retired_old_batch(self, attempt):
        """The older batch as retire-unactivated leaves it: cancelled, with its retired-starts record."""
        self.update_job(OLD, status='cancelled', launch_intent=dict(self.before['launch_intent'], attempt_id=attempt),
                        completion=dict(kind='retired_never_activated', attempt_id=attempt, executed_members=0))
        folder = self.c.root / 'retired-starts'; folder.mkdir(exist_ok=True)
        path = folder / (OLD + '-' + attempt[:16] + '.json')
        write_json(path, dict(schema_version=1, kind='retired_never_activated', status='cancelled', job_id=OLD,
                              attempt_id=attempt, executed_members=0))
        self.agent._append('studio_run_batch', 'returned', batch_id=OLD, status='start_uncertain')
        self.agent._append('retire_unactivated', 'intent', batch_id=OLD)
        self.agent._append('retire_unactivated', 'retired', batch_id=OLD, attempt_id=attempt)
        return path

    def test_a_retired_unactivated_batch_is_accepted_only_for_its_exact_attempt(self):
        self.settle()
        attempt = 'b' * 64
        path = self.retired_old_batch(attempt)
        preview = self.agent.restore_lane()
        self.assertEqual(preview['never_started_batches'],
                         {OLD: 'retired_unactivated', 'original': 'settled_refused_start'})
        record = read_json(path)
        for change in (dict(attempt_id='c' * 64), dict(job_id='original'), dict(kind='retired_never_started'),
                       dict(executed_members=1)):
            with self.subTest(change):
                write_json(path, record | change)
                with self.assertRaisesRegex(ValueError, OLD + ' is not proven never-started'):
                    self.agent.restore_lane()
        write_json(path, record)
        self.update_job(OLD, status='completed')
        with self.assertRaisesRegex(ValueError, OLD + ' is not proven never-started'):
            self.agent.restore_lane()
        self.assertEqual(self.lane(), 'demo_direct')

    def test_a_refused_retire_intent_alone_is_ignored_but_a_logged_retirement_needs_its_record(self):
        self.settle()
        self.agent._append('retire_unactivated', 'intent', batch_id='never-retired')
        self.assertEqual(self.agent.restore_lane()['status'], 'ready_to_restore')
        self.agent._append('retire_unactivated', 'retired', batch_id='never-retired', attempt_id='a' * 64)
        with self.assertRaisesRegex(ValueError, 'never-retired is not proven never-started'):
            self.agent.restore_lane()

    def test_an_unresolved_settle_intent_needs_the_settlement_record(self):
        self.agent._append('settle_refused_start', 'intent', batch_id=OLD)
        self.settle()
        with self.assertRaisesRegex(ValueError, OLD + ' is not proven never-started'):
            self.agent.restore_lane()
        self.agent._append('settle_refused_start', 'refused', batch_id=OLD, native_action=False)
        self.assertEqual(self.agent.restore_lane()['status'], 'ready_to_restore')
        self.agent._append('settle_refused_start', 'failed', batch_id=OLD, native_action=True)
        with self.assertRaisesRegex(ValueError, OLD + ' is not proven never-started'):
            self.agent.restore_lane()


if __name__ == '__main__':
    unittest.main()
