"""Continue after a reserved successor was retired before it ever ran (Banker g6, 2026-10-03).

g6 was paused and its pause record reserved successor g6-r1. g6-r1's start was
refused before MT5 was touched and retire-unactivated settled it to cancelled.
Then nothing could continue g6:

* ``continue --batch-id g6``: "Successor g6-r1 already exists as cancelled; pass a new --new-batch-id."
* ``continue --batch-id g6 --new-batch-id g6-r2``: "Batch g6 is already resuming as g6-r1; ..."

Real controller store, prepared packages and the real retire-unactivated proof; no MT5.
"""
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from studio_batch import resume_batch
from studio_batch_pause import (PauseRefused, RELEASES, load, plan_resume, release_unactivated,
                                unactivated_proof)
from studio_fast_lane import continue_batch, resolve_successor
from studio_launch_intent import record_intent
from studio_retire_unactivated import retire
from test_studio_batch_pause import NOW, PauseFixture

IDLE = ({'runtime': dict(tester_state='idle', batch_ongoing=False, account_demo=True)}, {})


class ContinueAfterRetireTests(PauseFixture):
    def setUp(self):
        super().setUp()
        runtime = patch.object(self.c, 'runtime', return_value=IDLE)
        runtime.start(); self.addCleanup(runtime.stop)
        self.request()
        self.finish_natively(['Completed', 'Cancelled', 'Cancelled'])
        self.assertEqual(__import__('studio_batch_pause').complete(self.c, 'g6', now=NOW)['state'], 'paused')

    # ---- the Banker shape -------------------------------------------------------------
    def reserve_successor(self, new_id='g6-r1'):
        """The pause fixes the successor ID, then its package is prepared (state stays paused)."""
        plan_resume(self.c.root, 'g6', new_id, now=NOW)
        resume_batch(self.c, 'g6', new_id, allow_peer_refresh=True)
        self.assertEqual(self.c.job(new_id)['status'], 'pending')

    def refused_start(self, job_id='g6-r1'):
        """Reservation + launch intent + restart phase 'prepared', as a config start refused before MT5."""
        c = self.c
        package = c.root / 'packages' / job_id
        job = c.job(job_id)
        digest = hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest()
        c.submit('queue.reserve', dict(job_id=job_id, configuration_sha256=job['configuration_sha256'],
                                       package_sha256=digest), job_id + '-reserve')
        state = c.state()
        intent = record_intent(c.store, c.terminal, c.run, job_id, package, actor='agent',
                               revision=state['revision'], generation=state['generation'])
        self.rewrite(job_id, lambda row: row.update(
            status='reconcile_required',
            restart_intent=dict(attempt_id=intent['attempt_id'], phase='prepared', history=[dict(phase='prepared', at=NOW)])))
        return intent['attempt_id']

    def rewrite(self, job_id, change):
        state = self.c.state()
        change(next(row for row in state['queue'] if row['job_id'] == job_id))
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        with self.c.store.transaction():
            self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
            self.c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))

    def retired_successor(self):
        self.reserve_successor()
        self.refused_start()
        result = retire(self.c, 'g6-r1')
        self.assertEqual((result['status'], result['kind']), ('cancelled', 'retired_never_activated'))
        return result

    def releases(self):
        path = self.c.root / RELEASES / 'g6.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def rows(self):
        return {row['job_id']: row for row in self.c.state()['queue']}

    # ---- the deadlock ------------------------------------------------------------------
    def test_banker_deadlock_continue_allocates_the_next_successor_itself(self):
        self.retired_successor()
        record = load(self.c.root, 'g6')
        self.assertEqual((record['state'], record['resume_batch_id']), ('paused', 'g6-r1'))
        retired_row = self.c.job('g6-r1')
        # Read-only preview (the demo agent resolves before it opens the controller).
        self.assertEqual(resolve_successor(self.c.root, self.rows(), 'g6'), 'g6-r2')
        self.assertEqual(load(self.c.root, 'g6'), record)
        result = continue_batch(self.c, 'g6')
        self.assertEqual((result['batch_id'], result['members']), ('g6-r2', 2))
        self.assertEqual(result['released_successor']['batch_id'], 'g6-r1')
        self.assertEqual(result['released_successor']['proof'], 'retired_never_activated')
        record = load(self.c.root, 'g6')
        self.assertEqual((record['state'], record['successor_batch_id'], record['resume_batch_id']),
                         ('resumed', 'g6-r2', 'g6-r2'))
        self.assertEqual([item['batch_id'] for item in record['released_successors']], ['g6-r1'])
        [line] = self.releases()
        self.assertEqual((line['event'], line['successor_batch_id'], line['previous_state']),
                         ('successor_released', 'g6-r1', 'paused'))
        self.assertEqual(line['proof']['kind'], 'retired_never_activated')
        self.assertEqual(line['proof']['attempt_id'], retired_row['completion']['attempt_id'])
        self.assertEqual(line['proof']['completion_sha256'], sha(retired_row['completion']))
        self.assertEqual(self.c.job('g6-r1'), retired_row)            # the retired successor is kept as is
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r2')['configuration']['batch_members']],
                         ['GBPUSD.c', 'USDJPY.c'])
        again = continue_batch(self.c, 'g6')                          # idempotent: reuses g6-r2
        self.assertEqual((again['batch_id'], again.get('reused')), ('g6-r2', True))
        self.assertEqual(len(self.releases()), 1)

    def test_explicit_new_id_is_accepted_once_the_successor_never_ran(self):
        self.retired_successor()
        result = continue_batch(self.c, 'g6', new_batch_id='g6-r2')
        self.assertEqual(result['batch_id'], 'g6-r2')
        self.assertEqual(load(self.c.root, 'g6')['successor_batch_id'], 'g6-r2')

    def test_the_retired_id_itself_is_still_refused_plainly(self):
        self.retired_successor()
        with self.assertRaisesRegex(ValueError, r'^Successor g6-r1 already exists as cancelled; pass a new --new-batch-id\.$'):
            continue_batch(self.c, 'g6', new_batch_id='g6-r1')

    def test_resumed_record_whose_successor_was_retired_is_released(self):
        first = continue_batch(self.c, 'g6')
        self.assertEqual(first['batch_id'], 'g6-r1')
        self.assertEqual(load(self.c.root, 'g6')['state'], 'resumed')
        self.refused_start()
        retire(self.c, 'g6-r1')
        result = continue_batch(self.c, 'g6')
        self.assertEqual(result['batch_id'], 'g6-r2')
        self.assertEqual(self.releases()[0]['previous_state'], 'resumed')

    def test_a_successor_cancelled_while_pending_is_released(self):
        self.reserve_successor()
        self.c.cancel('g6-r1', expected_generation=self.c.state()['generation'])
        self.assertEqual(unactivated_proof(self.c.job('g6-r1'))['kind'], 'cancelled_before_start')
        self.assertEqual(continue_batch(self.c, 'g6')['batch_id'], 'g6-r2')

    def test_a_successor_that_ran_keeps_the_existing_rules(self):
        self.reserve_successor()
        attempt = self.refused_start()
        # It reached MT5 and ran a member before it was cancelled: finish recorded native outcomes.
        result_path = self.c.root / 'attempts' / attempt / 'result.json'
        completion = dict(member_outcomes=[dict(status='native_completed'), dict(status='native_cancelled')],
                          attempt_id=attempt)
        result_path.parent.mkdir(parents=True); result_path.write_text(json.dumps(completion), encoding='utf-8')
        self.rewrite('g6-r1', lambda row: row.update(status='cancelled', completion=completion,
                                                     completion_path=str(result_path)))
        before = load(self.c.root, 'g6')
        self.assertIsNone(unactivated_proof(self.c.job('g6-r1')))
        with self.assertRaisesRegex(ValueError, r'^Successor g6-r1 already ran and is cancelled; continue it instead: '
                                                r'continue --batch-id g6-r1\.$'):
            continue_batch(self.c, 'g6')
        with self.assertRaisesRegex(PauseRefused, 'already resuming as g6-r1'):
            continue_batch(self.c, 'g6', new_batch_id='g6-r2')
        self.assertEqual(load(self.c.root, 'g6'), before)
        self.assertEqual(self.releases(), [])
        self.assertNotIn('g6-r2', self.rows())

    def test_release_is_append_only_and_idempotent(self):
        self.retired_successor()
        queue = self.rows()
        line = release_unactivated(self.c.root, 'g6', queue, now=NOW + 1)
        self.assertEqual(line['successor_batch_id'], 'g6-r1')
        self.assertIsNone(release_unactivated(self.c.root, 'g6', queue, now=NOW + 2))
        self.assertEqual(len(self.releases()), 1)
        # Interrupted after the journal line, before the pause record: no duplicate line.
        record = load(self.c.root, 'g6')
        record.update(resume_batch_id='g6-r1')
        Path(self.c.root / 'batch-pauses' / 'g6.json').write_text(json.dumps(record), encoding='utf-8')
        self.assertIsNotNone(release_unactivated(self.c.root, 'g6', queue, now=NOW + 3))
        self.assertEqual(len(self.releases()), 1)
        self.assertEqual(len(load(self.c.root, 'g6')['released_successors']), 1)


class UnactivatedProofTests(unittest.TestCase):
    attempt = 'a' * 64
    retired = dict(job_id='x-r1', status='cancelled', launch_intent=dict(attempt_id=attempt),
                   completion=dict(kind='retired_never_activated', job_id='x-r1', attempt_id=attempt,
                                   executed_members=0, native_cancellation_claimed=False))
    never_started = dict(job_id='x-r1', status='failed', launch_intent=dict(attempt_id=attempt),
                         completion=dict(classification='retired_never_started', job_id='x-r1', attempt_id=attempt,
                                         executed_members=0, native_cancellation_claimed=False))

    def test_only_retained_never_ran_proofs_release(self):
        self.assertEqual(unactivated_proof(self.retired)['kind'], 'retired_never_activated')
        self.assertEqual(unactivated_proof(self.never_started)['kind'], 'retired_never_started')
        self.assertEqual(unactivated_proof(dict(job_id='x-r1', status='cancelled'))['kind'], 'cancelled_before_start')
        completion = self.retired['completion']
        for row in (dict(self.retired, completion=dict(completion, executed_members=1)),
                    dict(self.retired, completion=dict(completion, native_cancellation_claimed=True)),
                    dict(self.retired, completion=dict(completion, attempt_id='b' * 64)),
                    dict(self.retired, completion=dict(completion, job_id='other')),
                    dict(self.retired, completion=dict(completion, kind='native_cancelled')),
                    dict(self.retired, status='completed'),
                    dict(self.retired, completion={}),
                    dict(job_id='x-r1', status='cancelled', launch_intent=dict(attempt_id=self.attempt)),
                    dict(job_id='x-r1', status='pending'),
                    dict(self.never_started, completion=dict(self.never_started['completion'], executed_members=2)),
                    dict(self.never_started, status='cancelled'),
                    None):
            with self.subTest(row=row):
                self.assertIsNone(unactivated_proof(row))


if __name__ == '__main__':
    unittest.main()
