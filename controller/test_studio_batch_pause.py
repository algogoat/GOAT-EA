"""Batch pause on real packages, a real gate and real stop identities; the EA is simulated.

The failure these fixtures replay: an owner stop issued while the terminal was
relaunching between members expired unconsumed, the controller could only return
the same expired request, and the driver journal ended stop_unconfirmed with
nothing supervising. No MT5 process is inspected, launched or signalled here.
"""
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_launch_intent import record_intent
from native_control_transaction import begin, NAMES
from studio_batch import prepare_batch, resume_batch
from studio_cancel_successor import cancel_id
from studio_dispatch_observe import observe_dispatch
import studio_batch_pause as pause
from studio_research_status import monitor_state
import test_goat_studio as fixtures

NOW = 1_800_000_000


class HostDeath(BaseException):
    pass


def local(epoch):
    return time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(epoch))


def utc(epoch):
    return time.strftime('%Y.%m.%d %H:%M:%S', time.gmtime(epoch))


def native_base(c):
    """The batch base exactly as publish_cancel resolves it, before and after per-terminal isolation."""
    try:
        from studio_terminal_isolation import controller_base
    except ImportError:
        return Path(c.install['common_files_root']) / 'GOAT' / ('GOAT V' + c.install['ea_version'] + '-' + c.session['account']['server'])
    return controller_base(c)


def launched(epoch):
    """A WindowsSeedProcess-shaped MT5 process started at epoch."""
    return dict(pid=4242, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch)))


def ticking(now=NOW, **extra):
    return dict(state='ticking', ticking=True, transient=False, heartbeat_wall=now, heartbeat_age_seconds=0,
                tester_state='running', restart_pending=False, blocker=None, process=None) | extra


class PauseFixture(unittest.TestCase):
    MEMBERS = ('EURUSD.c', 'GBPUSD.c', 'USDJPY.c')
    TEMPLATE = 'EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'   # subclasses may add inputs (news guard)
    EXTRA_INPUTS = {}                                                          # ... declared here for the schema

    def setUp(self):
        self.f = fixtures.PortableControllerTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.c = self.f.bound()
        if self.EXTRA_INPUTS:
            from campaign_ledger import sha as _sha
            self.c.schema['inputs'].update(self.EXTRA_INPUTS); self.c.store.input_schema_hash = _sha(self.c.schema)
        self.f.grant(self.c)
        source = self.f.root / 'Template.set'
        source.write_bytes(self.TEMPLATE.encode('utf-16'))
        spec = dict(schema_version=1, export=self.f.exports,
                    members=[dict(set_path=str(source), tester=self.f.tester | {'Symbol': symbol}) for symbol in self.MEMBERS])
        plan = self.f.root / 'plan.json'; plan.write_text(json.dumps(spec), encoding='utf-8')
        prepared = prepare_batch(self.c, 'g6', plan)
        self.package = Path(prepared['package']); self.manifest = prepared['manifest']
        job = self.c.job('g6')
        digest = hashlib.sha256((self.package / 'manifest.json').read_bytes()).hexdigest()
        self.c.submit('queue.reserve', dict(job_id='g6', configuration_sha256=job['configuration_sha256'], package_sha256=digest), 'g6-reserve')
        state = self.c.state()
        self.attempt = record_intent(self.c.store, self.c.terminal, self.c.run, 'g6', self.package, actor='agent',
                                     revision=state['revision'], generation=state['generation'])['attempt_id']
        self.gate = self.c.local / 'native-gate'
        self.run = self.f.common / self.manifest['native_run_relative'].replace('\\', '/')
        for item in self.manifest['jobs']:
            folder = self.run / 'inputs' / item['run_alias']; folder.mkdir(parents=True)
            (folder / 'Inputs.GOAT').write_bytes((self.package / (item['run_alias'] + '.set')).read_bytes())
        self.queue(['Queued', 'Pending', 'Pending'])
        base = native_base(self.c)
        base.mkdir(parents=True)
        pointer = ('[ActiveOptimizationRun]\r\nRunPath=' + self.manifest['native_run_relative'] + '\r\n').encode('utf-16')
        begin(base, self.c.root / 'attempts' / self.attempt, dict(zip(NAMES, [pointer, b'config', b'guard'])),
              {name: None for name in NAMES}, self.attempt)
        self.journal = dict(schema_version=2, attempt_id=self.attempt, binding=dict(job_id='g6', generation=state['generation']),
                            cancel_issued=False, stopped=False, status='observing', started_wall=NOW - 7200)
        self.timeline_rows = []
        self.clock = patch('studio_cancel.time', SimpleNamespace(time=lambda: self.now)); self.clock.start()
        self.addCleanup(self.clock.stop)
        self.now = NOW

    # ---- simulated native evidence -------------------------------------------------
    def queue(self, states):
        blocks = [block for block in (self.package / 'queue.GOAT').read_bytes().decode('utf-16').split('\x1f') if block.strip()]
        text = '\x1f'.join(block.replace(';Pending_', ';' + state + '_', 1) for block, state in zip(blocks, states)) + '\x1f'
        (self.run / 'queue.GOAT').write_bytes(text.encode('utf-16'))

    def event(self, index, status, at):
        alias = self.manifest['jobs'][index]['run_alias']
        self.timeline_rows.append('\t'.join([local(at), local(at), 'QUEUE_STATE', status + '_member:' + alias, status, '']))
        (self.run / 'timeline.tsv').write_text('LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails\n'
                                               + '\n'.join(self.timeline_rows) + '\n', encoding='utf-8')

    def answer(self, request_id, status, *, consumed, observed):
        issued = read_json(self.gate / ('issued-' + request_id + '.json'))
        if consumed:
            (self.gate / ('consumed-' + request_id + '.json')).write_bytes(
                (json.dumps(issued['request'], ensure_ascii=False, allow_nan=False) + '\n').encode())
        write_json(self.gate / ('result-' + request_id + '.json'), dict(
            request_id=request_id, request_sha256=issued['request_sha256'], status=status, observed_utc=utc(observed)))

    def issued(self):
        return sorted(path.name for path in self.gate.glob('issued-*.json'))

    # ---- driver-equivalent calls ---------------------------------------------------
    def request(self, **kwargs):
        return pause.request(self.c.root, self.c.job('g6'), self.journal, now=self.now, **kwargs)

    def step(self, monitor=None, **kwargs):
        return pause.step(self.c, 'g6', now=self.now, monitor=monitor or ticking(self.now), **kwargs)

    def finish_natively(self, states):
        """What studio_finish records once MT5 confirmed the stop (finish has its own suite)."""
        self.queue(states)
        result = self.c.root / 'attempts' / self.attempt / 'result.json'
        outcomes = [dict(status='native_' + state.lower()) for state in states]
        completion = dict(member_outcomes=outcomes, attempt_id=self.attempt)
        write_json(result, completion)
        state = self.c.state(); job = next(j for j in state['queue'] if j['job_id'] == 'g6')
        job.update(status='cancelled', completion=completion, completion_path=str(result))
        from campaign_ledger import packed
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.c.store.db.commit()


class SafePointTests(PauseFixture):
    def test_request_is_durable_idempotent_and_has_no_native_effect(self):
        first, created = self.request()
        again, repeated = self.request()
        self.assertTrue(created); self.assertFalse(repeated)
        self.assertEqual(first['pause_id'], again['pause_id'])
        self.assertEqual((first['state'], first['phase'], first['mode']), ('pausing', 'waiting_safe_point', 'safe_point'))
        self.assertEqual(self.issued(), [])
        escalated, _ = self.request(immediate=True)
        self.assertEqual((escalated['pause_id'], escalated['mode']), (first['pause_id'], 'immediate'))
        self.assertFalse(list(self.c.root.glob('batch-pauses/*.tmp')))

    def test_running_or_unstarted_batch_without_driver_journal_is_refused_plainly(self):
        with self.assertRaisesRegex(pause.PauseRefused, 'no bounded GOAT driver journal'):
            pause.request(self.c.root, self.c.job('g6'), None, now=NOW)
        job = dict(self.c.job('g6'), status='pending')
        with self.assertRaisesRegex(pause.PauseRefused, 'not running'):
            pause.request(self.c.root, job, self.journal, now=NOW)
        self.assertIsNone(pause.load(self.c.root, 'g6'))

    def test_waits_through_a_member_already_running_and_cancels_right_after_the_next_starts(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending'])
        self.event(0, 'OnGoing', NOW - 5000); self.event(0, 'Completed', NOW - 2600)
        self.event(1, 'OnGoing', NOW - 1200)
        record = self.step()
        self.assertEqual(record['phase'], 'waiting_safe_point')
        self.assertEqual(record['safe_point']['reason'], 'waiting_next_member')
        self.assertEqual(self.issued(), [])
        # The running member finishes and is kept; the next one starts.
        self.now = NOW + 1300
        self.queue(['Completed', 'Completed', 'OnGoing'])
        self.event(1, 'Completed', NOW + 1250); self.event(2, 'OnGoing', NOW + 1280)
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'cancel_published')
        self.assertEqual(record['safe_point']['kind'], 'member_started')
        original = sha([self.attempt, 'cancel'])
        self.assertEqual(self.issued(), ['issued-' + original + '.json'])
        request = read_json(self.gate / 'request.json')
        self.assertEqual((request['action'], request['expires_utc']), ('cancel', self.now + 120))
        # Waiting for MT5 inside the 120 s life never republishes.
        self.now += 30
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'cancel_published')
        self.assertEqual(self.issued(), ['issued-' + original + '.json'])
        journal = self.journal
        self.assertFalse(journal['cancel_issued'])

    def test_never_publishes_inside_a_members_last_minutes_or_without_a_ticking_monitor(self):
        self.request()
        for index in range(2):
            self.event(index, 'OnGoing', NOW - 4000 + index * 1000); self.event(index, 'Completed', NOW - 3700 + index * 1000)
        # Members take ~5 minutes; a member 2.5 minutes in has under 3 minutes left.
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW - 150)
        record = self.step()
        self.assertEqual(record['safe_point']['reason'], 'member_too_close_to_end')
        self.event(2, 'OnGoing', NOW - 20)
        relaunching = dict(ticking(), state='relaunching', ticking=False, transient=True)
        record = self.step(relaunching)
        self.assertEqual(record['safe_point']['reason'], 'monitor_not_ticking')
        self.assertIsNone(record['blocker'])
        self.assertEqual(self.issued(), [])

    def test_a_pace_too_fast_for_any_safe_window_is_a_named_blocker(self):
        self.request()
        # Members take 3 minutes: "180 s still to run" can never hold at a member start.
        for index in range(2):
            self.event(index, 'OnGoing', NOW - 4000 + index * 1000); self.event(index, 'Completed', NOW - 3820 + index * 1000)
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW - 5)
        record = self.step()
        self.assertEqual(record['safe_point']['reason'], 'pace_leaves_no_safe_window')
        self.assertEqual(record['blocker']['code'], 'pace_leaves_no_safe_window')
        self.assertIn('about 3.0 min', record['blocker']['message'])
        self.assertIn('STOP in the GOAT Studio panel', record['blocker']['fix'])
        self.assertEqual(self.issued(), [])
        # A monitor blocker explains the wait first and is never overwritten.
        closed = dict(ticking(), blocker=dict(code='monitor_closed', message='m', fix='f'))
        self.assertEqual(self.step(closed)['blocker']['code'], 'monitor_closed')

    def test_large_package_manifest_is_read_not_refused(self):
        """g6 live (15:56Z): a 1,265-member manifest (~2.8 MB) hit read_json's 2 MB cap on every step."""
        path = self.package / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['padding'] = 'x' * 2_100_000
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.assertGreater(path.stat().st_size, 2_000_000)
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending'])
        self.event(0, 'Completed', NOW - 400); self.event(1, 'OnGoing', NOW - 30)
        record = self.step()
        self.assertEqual((record['phase'], record['safe_point']['kind']), ('cancel_published', 'member_started'))
        self.assertEqual(len(self.issued()), 1)

    def test_member_start_seen_between_polls_counts_without_a_timeline(self):
        self.request()
        self.queue(['OnGoing', 'Pending', 'Pending'])
        self.assertEqual(self.step()['safe_point']['reason'], 'waiting_next_member')
        self.now = NOW + 60
        self.queue(['Completed', 'OnGoing', 'Pending'])
        record = self.step(ticking(self.now))
        self.assertEqual((record['phase'], record['safe_point']['source']), ('cancel_published', 'observed_transition'))

    def test_escalation_drops_the_member_age_rule_but_never_the_ticking_rule(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending']); self.event(1, 'OnGoing', NOW - 1200)
        stale = dict(ticking(), state='silent', ticking=False, blocker=dict(code='monitor_silent', message='m', fix='f'))
        record = self.step(stale, escalation='disk_low')
        self.assertEqual((record['mode'], record['escalation']), ('immediate', 'disk_low'))
        self.assertEqual(self.issued(), [])
        self.assertEqual(record['blocker']['code'], 'monitor_silent')
        record = self.step(ticking(process=launched(NOW - 600)), escalation='disk_low')
        self.assertEqual((record['phase'], record['safe_point']['kind']), ('cancel_published', 'immediate'))

    def test_immediate_still_refuses_a_pending_restart_and_a_monitor_older_than_mt5(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending']); self.event(1, 'OnGoing', NOW - 1200)
        cases = [
            (ticking(restart_pending=True, process=launched(NOW - 600)), 'restart_pending'),
            (ticking(restart_pending=None, process=launched(NOW - 600)), 'restart_pending'),
            (ticking(process=None), 'monitor_not_ticked_since_process_start'),
            (ticking(heartbeat_wall=NOW - 900, process=launched(NOW - 600)), 'monitor_not_ticked_since_process_start'),
        ]
        for monitor, reason in cases:
            with self.subTest(reason=reason, monitor=monitor):
                record = self.step(monitor, escalation='disk_low')
                self.assertEqual(record['mode'], 'immediate')
                self.assertEqual(record['safe_point']['reason'], reason)
                self.assertEqual(self.issued(), [])
        record = self.step(ticking(process=launched(NOW - 600)), escalation='disk_low')
        self.assertEqual(record['phase'], 'cancel_published')


class RelaunchWindowTests(PauseFixture):
    """Tonight's failure: the cancel expires unconsumed while MT5 relaunches."""

    def publish_original(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending'])
        self.event(0, 'Completed', NOW - 400); self.event(1, 'OnGoing', NOW - 30)
        record = self.step()
        self.assertEqual(record['phase'], 'cancel_published')
        return sha([self.attempt, 'cancel'])

    def test_expired_cancel_waits_for_the_rejection_then_exactly_one_successor(self):
        original = self.publish_original()
        before = {name: (self.gate / name).read_bytes() for name in ('issued-' + original + '.json',)}
        # MT5 relaunches at the member boundary: no tick inside the 120 s window.
        self.now = NOW + 200
        relaunching = dict(ticking(self.now), state='relaunching', ticking=False, transient=True, heartbeat_wall=NOW + 5)
        record = self.step(relaunching)
        self.assertEqual(record['phase'], 'cancel_expired_awaiting_receipt')
        self.assertEqual(self.issued(), ['issued-' + original + '.json'])
        self.assertFalse((self.c.root / 'cancel-successors').exists())
        # First bound tick after the relaunch: the EA answers the expired cancel.
        self.now = NOW + 260
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW + 255)
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(1, 'Completed', NOW + 240); self.event(2, 'OnGoing', NOW + 250)
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'successor_published')
        successor = cancel_id(self.c.root, self.c.job('g6'), self.gate)
        self.assertNotEqual(successor, original)
        self.assertEqual(self.issued(), sorted(['issued-' + original + '.json', 'issued-' + successor + '.json']))
        self.assertEqual([item['kind'] for item in record['cancels']], ['original', 'successor'])
        self.assertEqual((self.gate / ('issued-' + original + '.json')).read_bytes(), before['issued-' + original + '.json'])
        linkage = read_json(self.c.root / 'cancel-successors' / (self.attempt + '.json'))
        self.assertEqual((linkage['origin'], linkage['prior_request_id']), ('batch_pause', original))
        # Finish binds the successor: it refuses until that exact stop is consumed.
        from studio_finish import finish
        with self.assertRaisesRegex(ValueError, 'Successor cancellation'):
            finish(self.c, 'g6')
        # Repeated steps never issue a third identity.
        self.now += 10
        self.step(ticking(self.now))
        self.assertEqual(len(self.issued()), 2)
        self.answer(successor, 'CANCELLED_RECONCILE', consumed=True, observed=self.now)
        self.queue(['Completed', 'Completed', 'Cancelled'])
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'finishing')
        self.finish_natively(['Completed', 'Completed', 'Cancelled'])
        record = pause.complete(self.c, 'g6', now=self.now)
        self.assertEqual((record['state'], record['members_completed'], record['members_remaining']), ('paused', 2, 1))
        self.assertEqual(record['resume_token'], pause.resume_token('g6', self.attempt, record['result_sha256']))
        self.assertEqual(pause.verify_resumable(self.c, 'g6', record['resume_token'])['state'], 'paused')

    def test_identity_rejection_before_expiry_fails_plainly_without_a_successor(self):
        original = self.publish_original()
        self.now = NOW + 20
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW + 10)
        record = self.step(ticking(self.now))
        self.assertEqual((record['state'], record['failure']['code']), ('pause_failed', 'cancel_refused'))
        self.assertIn('not because it arrived late', pause.plain(record))
        self.assertFalse((self.c.root / 'cancel-successors').exists())
        self.assertEqual(len(self.issued()), 1)

    def test_successor_rejection_fails_without_a_third_stop(self):
        original = self.publish_original()
        self.now = NOW + 300
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW + 290)
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW + 280)
        self.step(ticking(self.now))
        successor = cancel_id(self.c.root, self.c.job('g6'), self.gate)
        self.now = NOW + 500
        self.answer(successor, 'CANCEL_REJECTED', consumed=False, observed=NOW + 490)
        record = self.step(ticking(self.now))
        self.assertEqual((record['state'], record['failure']['code']), ('pause_failed', 'successor_rejected'))
        self.assertEqual(len(self.issued()), 2)

    def test_consumed_rejection_or_other_native_refusal_is_never_replayed(self):
        original = self.publish_original()
        self.now = NOW + 30
        self.answer(original, 'CANCEL_NATIVE_OWNER_CHANGED', consumed=False, observed=NOW + 20)
        record = self.step(ticking(self.now))
        self.assertEqual(record['failure']['code'], 'receipt_cancel_native_owner_changed')
        self.assertEqual(len(self.issued()), 1)


class CrashTests(PauseFixture):
    def test_crash_after_publication_before_the_record_never_publishes_twice(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending']); self.event(1, 'OnGoing', NOW - 30)
        real = self.c.cancel
        def publish_then_die(job_id, *, expected_generation):
            real(job_id, expected_generation=expected_generation)
            raise HostDeath()
        with patch.object(self.c, 'cancel', side_effect=publish_then_die), self.assertRaises(HostDeath):
            self.step()
        self.assertEqual(pause.load(self.c.root, 'g6')['phase'], 'cancel_publishing')
        request = (self.gate / 'request.json').read_bytes()
        with patch.object(self.c, 'cancel', side_effect=AssertionError('republished')):
            record = self.step()
        self.assertEqual(record['phase'], 'cancel_published')
        self.assertEqual(record['cancels'][0]['expires_utc'], NOW + 120)
        self.assertEqual((self.gate / 'request.json').read_bytes(), request)
        self.assertEqual(len(self.issued()), 1)

    def test_crash_after_successor_linkage_publishes_only_that_successor(self):
        self.request()
        self.queue(['Completed', 'OnGoing', 'Pending']); self.event(1, 'OnGoing', NOW - 30)
        self.step()
        original = sha([self.attempt, 'cancel'])
        self.now = NOW + 300
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW + 290)
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW + 280)
        with patch.object(self.c, 'cancel', side_effect=HostDeath()), self.assertRaises(HostDeath):
            self.step(ticking(self.now))
        linked = cancel_id(self.c.root, self.c.job('g6'), self.gate)
        self.assertNotEqual(linked, original)
        self.assertEqual(observe_dispatch(self.gate, linked)['status'], 'not_issued')
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'successor_published')
        self.assertEqual(self.issued(), sorted(['issued-' + original + '.json', 'issued-' + linked + '.json']))

    def test_complete_is_replayable_and_records_paused_once(self):
        self.request()
        self.finish_natively(['Completed', 'Cancelled', 'Cancelled'])
        first = pause.complete(self.c, 'g6', now=NOW)
        second = pause.complete(self.c, 'g6', now=NOW + 5)
        self.assertEqual(first['state'], 'paused'); self.assertEqual(second['paused_utc'], NOW)
        self.assertEqual(second['resume_token'], first['resume_token'])

    def test_batch_that_finished_every_member_records_finished_not_paused(self):
        self.request()
        self.finish_natively(['Completed', 'Completed', 'Completed'])
        record = pause.complete(self.c, 'g6', now=NOW)
        self.assertEqual(record['state'], 'finished')
        with self.assertRaisesRegex(pause.PauseRefused, 'nothing left to resume'):
            pause.verify_resumable(self.c, 'g6')


class UnlicensedMonitorTests(PauseFixture):
    """g6 tonight: an owner STOP's cancel expired unanswered because Banker lost its sign-in."""

    def test_adopted_unconfirmed_stop_names_the_re_pair_blocker_and_never_replaces_it(self):
        # The driver's own STOP cancel, published ten minutes ago and expired with no receipt.
        self.queue(['Completed', 'OnGoing', 'Pending'])
        self.now = NOW - 600
        self.c.cancel('g6', expected_generation=self.c.state()['generation'])
        original = sha([self.attempt, 'cancel'])
        self.journal.update(cancel_issued=True, status='stop_unconfirmed', cancel_reason='owner_stop')
        record, _ = self.request()
        self.assertTrue(record['adopted_stop'])
        ui = self.c.local / 'ui-observation.json'
        write_json(ui, dict(schema_version=1, bound=True, loaded=True, owner='agent', runtime={}))
        os.utime(ui, (NOW - 3600, NOW - 3600))
        status = self.f.common / 'GOAT'
        token = Path(self.c.install['terminal_data_root']).name
        (status / ('activation-status-' + token + '.json')).write_text(json.dumps(dict(reason='awaiting_approval', observedAtUtc=NOW - 60)))
        (status / 'activation-status-OTHERTERMINAL.json').write_text(json.dumps(dict(reason='approved', observedAtUtc=NOW - 1800)))
        self.now = NOW
        monitor = monitor_state(self.c.install, self.c.session, self.c.local, now=NOW, process=dict(pid=1, created_utc='2026-10-01T00:00:00Z'))
        self.assertEqual((monitor['state'], monitor['blocker']['code']), ('unlicensed', 'monitor_unlicensed'))
        record = self.step(monitor)
        self.assertEqual(record['phase'], 'cancel_expired_awaiting_receipt')
        self.assertEqual(record['cancels'][0]['request_id'], original)
        self.assertTrue(record['cancels'][0]['adopted'])
        self.assertIn('replaced by another terminal', record['blocker']['message'])
        self.assertIn('re-pair', pause.plain(record))
        self.assertEqual(len(self.issued()), 1)
        self.assertFalse((self.c.root / 'cancel-successors').exists())
        # After the re-pair the EA answers the expired cancel; then one successor.
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW + 30)
        self.now = NOW + 40
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW + 20)
        record = self.step(ticking(self.now))
        self.assertEqual(record['phase'], 'successor_published')
        self.assertEqual(len(self.issued()), 2)

    def test_g6_shaped_successor_waits_at_a_member_end_with_restart_pending(self):
        """Owner STOP plus an expired driver deadline: the one successor must still wait."""
        self.queue(['Completed', 'OnGoing', 'Pending'])
        self.now = NOW - 600
        self.c.cancel('g6', expected_generation=self.c.state()['generation'])
        original = sha([self.attempt, 'cancel'])
        self.journal.update(cancel_issued=True, status='stop_unconfirmed', cancel_reason='owner_stop')
        self.request()
        self.now = NOW
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=NOW - 10)
        # ~400 s members; this one is 390 s in and MT5 already queued its restart.
        for index in range(2):
            self.event(index, 'OnGoing', NOW - 1600 + index * 800); self.event(index, 'Completed', NOW - 1200 + index * 800)
        self.queue(['Completed', 'Completed', 'OnGoing']); self.event(2, 'OnGoing', NOW - 390)
        ending = ticking(restart_pending=True, process=launched(NOW - 395))
        for escalation in (None, 'disk_low'):
            with self.subTest(escalation=escalation):
                record = self.step(ending, escalation=escalation)
                self.assertEqual(record['phase'], 'cancel_rejected_waiting_safe_point')
                self.assertEqual(self.issued(), ['issued-' + original + '.json'])
                self.assertFalse((self.c.root / 'cancel-successors').exists())


class ResumeTests(PauseFixture):
    def paused(self):
        self.request()
        self.finish_natively(['Completed', 'Cancelled', 'Cancelled'])
        return pause.complete(self.c, 'g6', now=NOW)

    def test_resume_builds_remaining_work_after_the_protected_peer_restarted(self):
        record = self.paused()
        restarted = dict(protected_terminal='C:/peer/terminal64.exe', protected_data_roots=['C:/peer-data'],
                         protected_process=dict(pid=4321, executable='C:/peer/terminal64.exe', created_utc='later'),
                         protected_policy_sha256='b' * 64, protected_may_be_stopped=True)
        with patch('studio_protected_peer.binding_fields', return_value=restarted):
            with self.assertRaisesRegex(ValueError, 'installation or plan identity changed'):
                resume_batch(self.c, 'g6', 'g6-r1')
            new_id = pause.successor_id('g6', {job['job_id'] for job in self.c.state()['queue']})
            self.assertEqual(new_id, 'g6-r1')
            pause.plan_resume(self.c.root, 'g6', new_id, now=NOW)
            prepared = resume_batch(self.c, 'g6', new_id, allow_peer_refresh=True)
            self.assertEqual(prepared['member_count'], 2)
            plan = read_json(Path(prepared['package']) / 'studio-plan.json')
            self.assertEqual(plan['research_binding']['protected_process']['pid'], 4321)
        self.assertEqual([m['tester']['Symbol'] for m in self.c.job('g6-r1')['configuration']['batch_members']],
                         ['GBPUSD.c', 'USDJPY.c'])
        done = pause.mark_resumed(self.c.root, 'g6', new_id, now=NOW, selected=2)
        self.assertEqual((done['state'], done['successor_batch_id']), ('resumed', 'g6-r1'))
        lineage = read_json(self.c.root / 'batch-lineage' / 'g6-r1.json')
        self.assertEqual((lineage['predecessor_batch_id'], lineage['resume_token']), ('g6', record['resume_token']))
        from studio_research_status import lineage as chain
        self.assertEqual(chain(self.c.root, 'g6-r1'), ['g6', 'g6-r1'])
        self.assertEqual(chain(self.c.root, 'g6'), ['g6', 'g6-r1'])
        # Idempotent: the planned successor is reused, a different one refuses.
        self.assertEqual(pause.plan_resume(self.c.root, 'g6', 'g6-r1', now=NOW)['resume_batch_id'], 'g6-r1')
        with self.assertRaisesRegex(pause.PauseRefused, 'already resuming as g6-r1'):
            pause.plan_resume(self.c.root, 'g6', 'other', now=NOW)

    def test_peer_tolerance_never_relaxes_other_binding_fields_or_running_packages(self):
        self.paused()
        original = type(self.c).binding
        with patch.object(type(self.c), 'binding', lambda c: dict(original(c), ea_sha256='f' * 64)):
            with self.assertRaisesRegex(ValueError, 'installation or plan identity changed'):
                resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True)
        from studio_batch import _verify_package
        with self.assertRaisesRegex(ValueError, 'only reads a finished package'):
            _verify_package(self.c, dict(self.c.job('g6'), status='running'), allow_peer_refresh=True)

    def test_changed_result_or_token_refuses_resume(self):
        record = self.paused()
        with self.assertRaisesRegex(pause.PauseRefused, 'token does not match'):
            pause.verify_resumable(self.c, 'g6', 'x' * 64)
        Path(record['result_path']).write_text('{"tampered":true}')
        with self.assertRaisesRegex(pause.PauseRefused, 'changed'):
            pause.verify_resumable(self.c, 'g6')

    def test_successor_ids_count_up_and_stay_within_limits(self):
        self.assertEqual(pause.successor_id('g6', set()), 'g6-r1')
        self.assertEqual(pause.successor_id('g6-r1', {'g6-r2'}), 'g6-r3')
        long = 'b' * 80
        self.assertEqual(len(pause.successor_id(long, set())), 80)


if __name__ == '__main__':
    unittest.main()
