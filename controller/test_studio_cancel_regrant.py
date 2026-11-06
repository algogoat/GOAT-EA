"""The stranded-batch deadlock: real store, bridge, gate, runtime check and finish; the EA is simulated.

Replayed facts: a reboot interrupted a batch, a cancel was rejected, one cancellation
successor was issued, the human took control. Tester idle, native queue 2 completed /
1 error / 1 ongoing / 4 pending, owner=human, generation=2. No MT5 process is inspected,
launched or signalled here; the broker SDK and report verification are the only fakes,
and this is not a Windows or MT5 replay.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from demo_agent import DemoAgent, main as demo_main
from studio_bridge import write_json
from studio_cancel_successor import cancel_id
from studio_dispatch_observe import observe_dispatch
from studio_finish import finish
from studio_handover import database_view
from studio_installation import read_json
from studio_native_gate import assert_clear_controls, exclusive_gate
from studio_refusal import Refusal
from studio_research_authority import demo_agent_scope, operation
import studio_batch_pause as pause
import test_demo_agent as demo_fixtures
from test_studio_batch_pause import PauseFixture, native_base, ticking, utc

STATES = ['Completed', 'Completed', 'Error', 'OnGoing', 'Pending', 'Pending', 'Pending', 'Pending']
STOP_LIFE = 120


def regrant():
    """Imported late so the replay reaches the missing path, not an import error, on a build without it."""
    import studio_cancel_regrant
    return studio_cancel_regrant


class StrandedFixture(PauseFixture):
    MEMBERS = ('EURUSD.c', 'GBPUSD.c', 'USDJPY.c', 'AUDUSD.c', 'USDCAD.c', 'NZDUSD.c', 'EURJPY.c', 'GBPJPY.c')

    def setUp(self):
        super().setUp()
        self.job_id = 'g6'
        self.now = int(time.time())
        self.batch_ongoing, self.tester, self.ea_demo = True, 'idle', True
        session = read_json(self.c.root / 'session.json') | dict(authority_kind='demo_direct', demo_only=True)
        write_json(self.c.root / 'session.json', session)
        write_json(self.c.root / 'installation.json', self.c.install)
        self.c.session = session
        # The monitor's serve loop, the only unscoped reader a demo_direct session allows.
        serving = operation('serve'); serving.__enter__(); self.addCleanup(serving.__exit__, None, None, None)
        self.base = native_base(self.c)
        # Results a completed member already produced: they must survive byte for byte.
        self.kept = self.run / 'reports' / 'member-1.xml'
        self.kept.parent.mkdir(parents=True); self.kept.write_bytes(b'<kept/>')
        self.queue(STATES)
        journal = dict(self.journal, max_seconds=172800)
        (self.c.root / 'batch-drivers').mkdir(exist_ok=True)
        self.journal = journal
        write_json(self.c.root / 'batch-drivers' / 'g6.json', journal)
        verified = patch('studio_finish.observe_reports', return_value=dict(status='report_batch_verified')); verified.start()
        self.addCleanup(verified.stop)
        self.mt5 = demo_fixtures.MetaTrader(Path(self.c.install['terminal_executable']), Path(self.c.install['terminal_data_root']))
        self.mt5.login, self.mt5.server = int(self.c.session['account']['login']), self.c.session['account']['server']
        self.mt5.__version__ = 'test'
        self.mt5.account_trade_allowed = False
        for target, value in (('studio_monitor_probe.inspect_processes', dict(research=dict(pid=91), protected=None)),
                              ('studio_monitor_probe.process_binding', dict()), ('studio_monitor_probe.role_unchanged', True),
                              ('studio_monitor_probe.tester_state', 'idle')):
            active = patch(target, return_value=value); active.start(); self.addCleanup(active.stop)
        module = patch.dict(sys.modules, MetaTrader5=self.mt5); module.start(); self.addCleanup(module.stop)
        self.ea_tick()

    # ---- the EA, simulated from GOATStudioDispatch.mqh -------------------------------------
    def ea_tick(self):
        """A monitor tick: publish the runtime sample, then answer a permitted request exactly once."""
        state = self.c.state()
        i = self.c.install
        write_json(self.c.local / 'ui-observation.json', dict(
            schema_version=1, bound=True, loaded=True, owner=state['owner'], revision=state['revision'], generation=state['generation'],
            observed_terminal_utc=time.strftime('%Y.%m.%d %H:%M:%S', time.gmtime()),
            runtime=dict(data_path=i['terminal_data_root'], installation_path=str(Path(i['terminal_executable']).parent),
                         program_path=str(self.c.native_args()['monitor_path'].resolve()),
                         account_login=str(self.c.session['account']['login']), account_server=self.c.session['account']['server'],
                         connected=True, account_demo=self.ea_demo, terminal_trade_allowed=False,
                         batch_ongoing=self.batch_ongoing, restart_pending=False, tester_state=self.tester)))
        gate = self.gate
        if not (gate / 'permit.json').exists():
            return None
        permit = read_json(gate / 'permit.json')
        body = (gate / 'request.json').read_bytes()
        if hashlib.sha256(body).hexdigest() != permit['request_sha256']:
            return None
        request = json.loads(body)
        receipt = gate / ('result-' + request['request_id'] + '.json')
        if receipt.exists():
            return None
        status = self.ea_cancel(request, body)
        write_json(receipt, dict(request_id=request['request_id'], request_sha256=permit['request_sha256'],
                                 status=status, observed_utc=utc(self.now)))
        return status

    def ea_cancel(self, request, body):
        snapshot = read_json(self.c.bridge.root / 'snapshot.json')['state']
        if (request.get('action') != 'cancel' or request['expires_utc'] <= self.now or request['expires_utc'] > self.now + STOP_LIFE
                or request['owner'] != 'agent' or not self.ea_demo
                or request['account_login'] != str(self.c.session['account']['login'])):
            return 'CANCEL_REJECTED'
        if any(snapshot[key] != request[key] for key in ('owner', 'revision', 'generation')):
            return 'CANCEL_CONTROL_REVOKED'
        matched = any(item['job_id'] == request['job_id'] and item['configuration_sha256'] == request['configuration_sha256']
                      and item['status'] in ('starting', 'running', 'verifying', 'reconcile_required') for item in snapshot['queue'])
        digest = lambda name: hashlib.sha256((self.base / name).read_bytes()).hexdigest()
        if (not matched or digest('agent-native-control-owner.json') != request['native_owner_sha256']
                or digest('active_optimization_run.ini') != request['pointer_sha256']):
            return 'CANCEL_NATIVE_OWNER_CHANGED'
        consumed = self.gate / ('consumed-' + request['request_id'] + '.json')
        if consumed.exists():
            return 'CANCEL_ALREADY_CONSUMED'
        consumed.write_bytes(body)
        self.batch_ongoing = False
        raw = (self.run / 'queue.GOAT').read_bytes().decode('utf-16')
        for state in ('Pending', 'Queued', 'OnGoing'):
            raw = raw.replace(';' + state + '_', ';Cancelled_')
        (self.run / 'queue.GOAT').write_bytes(raw.encode('utf-16'))
        return 'CANCELLED_RECONCILE'

    # ---- human channel, through the real bridge ------------------------------------------------
    def human(self, command, *, through_bridge=True):
        state = self.c.state()
        request_id = 'ui-' + command.replace('.', '-').replace('_', '-') + '-' + str(state['generation'])
        request = dict(schema_version=1, request_id=request_id, terminal_id=self.c.terminal, run_id=self.c.run,
                       expected_revision=state['revision'], generation=state['generation'], command=command, payload={})
        if through_bridge:
            inbox = self.c.bridge.root / 'human' / 'inbox'; inbox.mkdir(parents=True, exist_ok=True)
            write_json(inbox / (request_id + '.json'), request)
            results = self.c.bridge.pump()
            self.assertEqual([(item['request_id'], item['ok']) for item in results], [(request_id, True)])
        else:
            self.c.store.submit(request, actor='human')
            self.c.bridge.pump()
        return request

    # ---- the incident ----------------------------------------------------------------------------
    def rejected_and_successor(self, *, successor_age=600):
        """Cancel rejected after expiry, one successor issued; returns its identity."""
        record, _ = self.request()
        started = self.now
        self.now = started - 1800
        self.c.cancel('g6', expected_generation=record['generation'])
        original = sha([self.attempt, 'cancel'])
        self.answer(original, 'CANCEL_REJECTED', consumed=False, observed=self.now + 200)
        self.now = started - successor_age
        successor = pause.create_successor(self.c, 'g6', record, now=self.now)
        self.c.cancel('g6', expected_generation=record['generation'])
        self.now = started
        return successor

    def stranded(self, *, granted=True, **kwargs):
        """Owner=human at generation 2, then (by default) one new human grant at generation 3."""
        successor = self.rejected_and_successor(**kwargs)
        self.assertEqual((self.c.state()['generation'], self.c.state()['owner']), (1, 'agent'))
        self.human('control.takeover')
        self.assertEqual((self.c.state()['generation'], self.c.state()['owner']), (2, 'human'))
        self.ea_tick()
        if granted:
            self.human('control.grant_agent')
            self.assertEqual((self.c.state()['generation'], self.c.state()['owner']), (3, 'agent'))
            self.ea_tick()
        return successor

    def counts(self):
        from studio_native_observe import observe
        return observe(self.package)['status_counts']

    def publish(self):
        return regrant().publish(self.c, 'g6', now=self.now)

    def settle(self):
        return regrant().settle(self.c, 'g6', now=self.now, monitor=ticking(self.now, tester_state='idle'))

    def assertRefused(self, code, call=None):
        before = self.issued(), sorted(p.name for p in (self.c.root / 'cancel-successors').glob('*')) if (self.c.root / 'cancel-successors').exists() else []
        request = (self.gate / 'request.json').read_bytes() if (self.gate / 'request.json').exists() else None
        with self.assertRaises(Refusal) as caught:
            (call or self.publish)()
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        after = self.issued(), sorted(p.name for p in (self.c.root / 'cancel-successors').glob('*')) if (self.c.root / 'cancel-successors').exists() else []
        self.assertEqual(after, before)
        self.assertEqual((self.gate / 'request.json').read_bytes() if (self.gate / 'request.json').exists() else None, request)


class DeadlockTests(StrandedFixture):
    def test_the_incident_state_is_a_deadlock_without_a_regrant_stop(self):
        """These refusals hold on every build; each must still fire after this change."""
        successor = self.stranded(granted=False)
        self.assertEqual(self.counts(), dict(native_completed=2, native_error=1, native_ongoing=1, native_pending=4))
        self.assertFalse((self.gate / 'permit.json').exists(), 'the takeover revoked the unanswered stop')
        with self.assertRaisesRegex(ValueError, 'Current agent ownership'):
            self.c.cancel('g6')
        with self.assertRaisesRegex(ValueError, 'Successor cancellation requires'):
            finish(self.c, 'g6')
        with self.assertRaisesRegex(ValueError, 'Unresolved native attempt'):
            database_view(self.c.root / 'studio.sqlite')
        # The grant alone changes nothing: the one-shot successor is returned, never resent.
        self.human('control.grant_agent'); self.ea_tick()
        issued = self.issued()
        self.assertEqual(self.c.cancel('g6')['request_id'], successor)
        self.assertEqual(self.issued(), issued)
        self.assertIsNone(self.ea_tick())
        with self.assertRaisesRegex(ValueError, 'Successor cancellation requires'):
            finish(self.c, 'g6')
        self.assertEqual(self.counts(), dict(native_completed=2, native_error=1, native_ongoing=1, native_pending=4))


class ReplayTests(StrandedFixture):
    def test_incident_replay_reaches_a_settled_queue_an_idle_monitor_and_resumable_members(self):
        successor = self.stranded()
        kept = {path: path.read_bytes() for path in self.gate.glob('*-*.json')}
        report = self.kept.read_bytes()
        published = self.publish()
        identity = published['request_id']
        self.assertEqual(identity, sha([self.attempt, 'cancel-successor-regrant', hashlib.sha256(
            (self.gate / ('issued-' + successor + '.json')).read_bytes()).hexdigest(), 3]))
        self.assertEqual(cancel_id(self.c.root, self.c.job('g6'), self.gate), identity)
        request = read_json(self.gate / 'request.json')
        self.assertEqual((request['action'], request['generation'], request['owner']), ('cancel', 3, 'agent'))
        # Not settled by publication.
        self.assertEqual(self.settle()['status'], 'regrant_waiting')
        with self.assertRaisesRegex(ValueError, 'Successor cancellation requires'):
            finish(self.c, 'g6')
        self.assertEqual(self.ea_tick(), 'CANCELLED_RECONCILE')
        self.ea_tick()
        self.assertEqual(self.counts(), dict(native_cancelled=5, native_completed=2, native_error=1))
        result = self.settle()
        self.assertEqual((result['status'], result['batch_status']), ('paused', 'failed'))
        self.assertEqual(self.c.job('g6')['status'], 'failed')
        self.assertEqual(self.c.job('g6')['completion']['cancellation_dispatch']['receipt']['request_id'], identity)
        record = pause.load(self.c.root, 'g6')
        self.assertEqual((record['members_completed'], record['members_failed'], record['members_remaining']), (2, 1, 5))
        self.assertFalse((self.gate / 'permit.json').exists())
        # Idle monitor: every gate that needed a settled job now passes, on the real checks.
        self.c.runtime(require_idle=True, expected_batch_ongoing=False)
        self.assertEqual(database_view(self.c.root / 'studio.sqlite')['counts'], dict(failed=1))
        with exclusive_gate(self.gate):
            self.assertEqual(assert_clear_controls(self.c.store.db, self.gate)['request_id'], identity)
        # Nothing was deleted, nothing new started.
        for path, raw in kept.items():
            self.assertEqual(path.read_bytes(), raw, path.name)
        self.assertEqual(self.kept.read_bytes(), report)
        self.assertEqual(len(self.issued()), 3)
        self.assertTrue(all(read_json(self.gate / name)['request']['action'] == 'cancel' for name in self.issued()))
        self.assertEqual(self.c.state()['queue'][0]['job_id'], 'g6')
        self.assertEqual(len(self.c.state()['queue']), 1)
        # Unfinished members stay resumable: exactly the five that never ran.
        pause.verify_resumable(self.c, 'g6', record['resume_token'])
        from studio_batch import resume_batch
        from studio_fast_lane import binding_changed
        write_json(self.c.root / 'monitor-profile.json', dict(profile_name='GOAT-Studio-test'))
        preset = Path(self.c.install['terminal_data_root']) / 'MQL5/Presets/GOAT Studio Agent.set'
        preset.parent.mkdir(parents=True, exist_ok=True)
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))
        with demo_agent_scope(root=self.c.root, installation_sha256=self.c.session['installation_sha256'],
                              account=self.c.session['account'], job_id='g6-r1'), operation('prepare-batch'):
            prepared = resume_batch(self.c, 'g6', 'g6-r1', allow_peer_refresh=True,   # as batch_resume calls it
                                    allow_binding_change=bool(binding_changed(self.c, 'g6')))
        self.assertEqual(prepared['member_count'], 5)
        self.assertEqual(self.c.job('g6-r1')['status'], 'pending')
        self.assertNotIn('launch_intent', self.c.job('g6-r1'))
        self.assertTrue(read_json(self.c.root / 'batch-drivers' / 'g6.json')['stopped'])
        self.assertEqual(self.settle()['status'], 'paused')   # a repeat reuses the verified finish

    def test_a_failed_pause_is_rearmed_and_reaches_paused_keeping_its_failure(self):
        successor = self.rejected_and_successor()
        self.answer(successor, 'CANCEL_CONTROL_REVOKED', consumed=False, observed=self.now)
        self.assertEqual(self.step()['state'], 'pause_failed')
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        published = self.publish()
        self.assertEqual(published['pause']['state'], 'pausing')
        self.assertEqual(published['pause']['generation'], 3)
        self.assertEqual(published['pause']['rearmed_failures'][0]['failure']['code'], 'receipt_cancel_control_revoked')
        self.ea_tick(); self.ea_tick()
        self.assertEqual(self.settle()['status'], 'paused')
        record = pause.load(self.c.root, 'g6')
        self.assertEqual(record['rearmed_failures'][0]['generation'], 1)
        self.assertEqual([item['receipt'] for item in record['cancels'] if item['request_id'] == published['request_id']], ['CANCELLED_RECONCILE'])

    def test_a_batch_with_no_pause_gets_one_so_its_members_stay_resumable(self):
        self.stranded()
        pause.path(self.c.root, 'g6').unlink()   # the owner route issues a successor without any pause record
        self.publish()
        self.assertEqual(pause.load(self.c.root, 'g6')['requested_by'], 'cancel_regrant')
        self.ea_tick(); self.ea_tick()
        self.assertEqual(self.settle()['status'], 'paused')

    def test_each_later_grant_gets_one_stop_chained_from_the_last_and_finish_binds_the_newest(self):
        self.stranded()
        first = self.publish()['request_id']
        self.human('control.takeover'); self.ea_tick()   # the permit is revoked before MT5 answered
        self.human('control.grant_agent'); self.ea_tick()
        self.assertRefused('REGRANT_PRIOR_STOP_LIVE')
        self.now += STOP_LIFE + 1
        second = self.publish()['request_id']
        self.assertNotEqual(second, first)
        self.assertEqual(read_json(self.c.root / 'cancel-successors' / (self.attempt + '.regrant-5.json'))['prior_request_id'], first)
        self.assertEqual(cancel_id(self.c.root, self.c.job('g6'), self.gate), second)
        self.ea_tick(); self.ea_tick()
        self.assertEqual(self.settle()['status'], 'paused')
        self.assertEqual(self.c.job('g6')['completion']['cancellation_dispatch']['receipt']['request_id'], second)

    def test_an_interrupted_publication_retries_the_same_stop_and_never_under_a_later_grant(self):
        self.stranded()
        with patch('studio_cancel.issue_stop', side_effect=OSError('host died')):
            with self.assertRaisesRegex(OSError, 'host died'):
                self.publish()
        link = read_json(self.c.root / 'cancel-successors' / (self.attempt + '.regrant-3.json'))
        self.assertEqual(len(self.issued()), 2)
        # A later grant: the stranded link can never publish under it.
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        self.assertEqual(cancel_id(self.c.root, self.c.job('g6'), self.gate), link['request_id'])
        self.assertRefused('REGRANT_GENERATION_CHANGED', lambda: self.c.cancel('g6'))
        fresh = self.publish()
        self.assertNotEqual(fresh['request_id'], link['request_id'])
        self.assertEqual(read_json(self.c.root / 'cancel-successors' / (self.attempt + '.regrant-5.json'))['prior_request_id'], link['prior_request_id'])
        self.assertEqual(len(self.issued()), 3)

    def test_a_retry_at_the_same_generation_publishes_the_same_linked_stop_once(self):
        self.stranded()
        with patch('studio_cancel.issue_stop', side_effect=OSError('host died')):
            with self.assertRaisesRegex(OSError, 'host died'):
                self.publish()
        link = read_json(self.c.root / 'cancel-successors' / (self.attempt + '.regrant-3.json'))
        self.assertEqual(self.publish()['request_id'], link['request_id'])
        self.assertRefused('REGRANT_ALREADY_ISSUED')


class AdmissionRefusalTests(StrandedFixture):
    def test_real_account_refuses_at_the_broker(self):
        self.stranded()
        self.mt5.trade_mode = 2
        self.assertRefused('REGRANT_BROKER_NOT_DEMO')

    def test_real_account_refuses_on_the_ea_sample(self):
        self.stranded()
        self.ea_demo = False; self.ea_tick()
        self.assertRefused('REGRANT_BROKER_NOT_DEMO')

    def test_not_the_demo_lane_refuses(self):
        self.stranded()
        self.c.session = dict(self.c.session, authority_kind='native_human_control')
        self.assertRefused('REGRANT_NOT_DEMO_LANE')

    def test_tester_busy_refuses_on_the_ea_sample_and_on_the_tester_caption(self):
        self.stranded()
        self.tester = 'running'; self.ea_tick()
        self.assertRefused('REGRANT_TESTER_NOT_IDLE')
        self.tester = 'idle'; self.ea_tick()
        with patch('studio_monitor_probe.tester_state', return_value='running'):
            self.assertRefused('REGRANT_TESTER_NOT_IDLE')

    def test_same_generation_without_a_human_cycle_refuses(self):
        self.rejected_and_successor(); self.ea_tick()
        self.assertRefused('REGRANT_SAME_GENERATION')

    def test_human_still_in_control_refuses(self):
        self.stranded(granted=False)
        self.assertRefused('REGRANT_OWNER_NOT_AGENT')

    def test_prior_stop_consumed_refuses(self):
        successor = self.stranded()
        issued = read_json(self.gate / ('issued-' + successor + '.json'))['request']
        (self.gate / ('consumed-' + successor + '.json')).write_bytes((json.dumps(issued, ensure_ascii=False, allow_nan=False) + '\n').encode())
        self.assertRefused('REGRANT_PRIOR_STOP_CONSUMED')

    def test_prior_stop_still_live_refuses(self):
        self.stranded(successor_age=10)
        self.assertRefused('REGRANT_PRIOR_STOP_LIVE')

    def test_no_archived_grant_refuses(self):
        self.rejected_and_successor()
        self.human('control.takeover')
        self.human('control.grant_agent', through_bridge=False)   # a receipt with no human archive
        self.ea_tick()
        self.assertRefused('REGRANT_NO_ARCHIVED_GRANT')

    def test_changed_archived_grant_refuses(self):
        self.stranded()
        archive = next((self.c.bridge.root / 'human/archive').glob('ui-control-grant-agent-2.*.json'))
        write_json(archive, read_json(archive) | dict(payload=dict(forged=True)))
        self.assertRefused('REGRANT_NO_ARCHIVED_GRANT')

    def test_an_archive_that_does_not_hash_to_its_human_receipt_refuses(self):
        self.stranded()
        archive = next((self.c.bridge.root / 'human/archive').glob('ui-control-grant-agent-2.*.json'))
        write_json(archive, read_json(archive) | dict(extra=1))   # every named field still matches
        self.assertRefused('REGRANT_NO_ARCHIVED_GRANT')

    def test_changed_native_owner_refuses(self):
        self.stranded()
        path = self.base / 'agent-native-control-owner.json'
        write_json(path, read_json(path) | dict(extra=1))
        self.assertRefused('REGRANT_NATIVE_OWNER_CHANGED')

    def test_foreign_native_owner_refuses(self):
        self.stranded()
        path = self.base / 'agent-native-control-owner.json'
        write_json(path, read_json(path) | dict(owner='f' * 64))
        self.assertRefused('REGRANT_NATIVE_OWNER_CHANGED')

    def test_changed_pointer_refuses(self):
        self.stranded()
        path = self.base / 'active_optimization_run.ini'
        path.write_bytes(path.read_bytes() + ' '.encode('utf-16-le'))
        self.assertRefused('REGRANT_POINTER_CHANGED')

    def test_no_successor_refuses(self):
        record, _ = self.request()
        self.c.cancel('g6', expected_generation=record['generation'])
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        self.assertRefused('REGRANT_NO_PRIOR_SUCCESSOR')

    def test_an_unpublished_successor_refuses_and_ordinary_cancel_still_publishes_it(self):
        started = self.now
        record, _ = self.request()
        self.now = started - 1800
        self.c.cancel('g6', expected_generation=record['generation'])
        self.answer(sha([self.attempt, 'cancel']), 'CANCEL_REJECTED', consumed=False, observed=self.now + 200)
        self.now = started
        successor = pause.create_successor(self.c, 'g6', record, now=self.now)
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        self.assertRefused('REGRANT_NO_PRIOR_SUCCESSOR')
        self.assertEqual(self.c.cancel('g6')['request_id'], successor)

    def test_a_receipt_a_grant_cannot_change_refuses(self):
        successor = self.stranded()
        self.answer(successor, 'CANCEL_RUN_CHANGED', consumed=False, observed=self.now)
        self.assertRefused('REGRANT_PRIOR_RECEIPT_NOT_RECOVERABLE')

    def test_a_grant_the_ea_has_not_seen_refuses(self):
        self.rejected_and_successor()
        self.human('control.takeover'); self.ea_tick()
        self.human('control.grant_agent')   # no monitor tick since
        self.assertRefused('REGRANT_GRANT_NOT_OBSERVED')

    def test_a_pending_restart_refuses(self):
        self.stranded()
        path = self.c.local / 'ui-observation.json'
        value = read_json(path); value['runtime']['restart_pending'] = True; write_json(path, value)
        self.assertRefused('REGRANT_RUNTIME_NOT_VERIFIED')

    def test_settled_job_refuses(self):
        self.stranded()
        self.publish(); self.ea_tick(); self.ea_tick(); self.settle()
        self.assertRefused('REGRANT_JOB_NOT_ACTIVE')

    def test_a_held_driver_gate_refuses(self):
        self.stranded()
        driver = self.c.root / 'batch-driver-gate'; driver.mkdir(exist_ok=True)
        with exclusive_gate(driver):
            self.assertRefused('REGRANT_BATCH_BUSY')

    def test_a_pause_that_cannot_rearm_refuses_before_any_effect(self):
        self.stranded()
        record = pause.load(self.c.root, 'g6'); record.update(attempt_id='f' * 64); write_json(pause.path(self.c.root, 'g6'), record)
        self.assertRefused('REGRANT_PAUSE_NOT_REARMABLE')


class OneStopTests(StrandedFixture):
    def test_a_second_regrant_at_the_same_generation_refuses_and_changes_nothing(self):
        self.stranded()
        identity = self.publish()['request_id']
        self.assertRefused('REGRANT_ALREADY_ISSUED')
        self.ea_tick()
        self.assertRefused('REGRANT_ALREADY_ISSUED')
        self.assertEqual(cancel_id(self.c.root, self.c.job('g6'), self.gate), identity)
        self.assertEqual(self.c.cancel('g6')['request_id'], identity)   # ordinary cancel returns it, never resends
        self.assertEqual(len(self.issued()), 3)

    def test_a_consumed_regrant_cannot_be_replaced_by_a_later_grant(self):
        self.stranded()
        self.publish(); self.ea_tick()
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        self.now += STOP_LIFE + 1
        self.assertRefused('REGRANT_PRIOR_STOP_CONSUMED')
        self.assertEqual(self.settle()['status'], 'paused')

    def test_a_refused_regrant_fails_the_pause_and_settle_never_resends_or_rearms(self):
        self.stranded()
        identity = self.publish()['request_id']
        self.now += STOP_LIFE + 1
        self.assertEqual(self.ea_tick(), 'CANCEL_REJECTED')
        result = self.settle()
        self.assertEqual(result['status'], 'pause_failed')
        issued = self.issued()
        self.assertEqual(self.settle()['status'], 'pause_failed')
        self.assertEqual(self.issued(), issued)
        with self.assertRaisesRegex(pause.PauseRefused, 'Pause failed'):
            pause.rearm_for_regrant(self.c.root, self.c.job('g6'), self.journal, now=self.now, generation=3, request_id=identity)
        # A new human cycle is the only way on, and it still reaches paused.
        self.human('control.takeover'); self.human('control.grant_agent'); self.ea_tick()
        self.publish(); self.ea_tick(); self.ea_tick()
        self.assertEqual(self.settle()['status'], 'paused')

    def test_settle_publishes_nothing(self):
        self.stranded()
        self.assertRefused('REGRANT_NOT_PUBLISHED', self.settle)
        self.assertFalse(list((self.c.root / 'cancel-successors').glob('*.regrant-*')))

    def test_settle_refuses_a_human_owner(self):
        self.stranded()
        self.publish()
        self.human('control.takeover')
        self.assertRefused('REGRANT_OWNER_NOT_AGENT', self.settle)


class OldRefusalTests(StrandedFixture):
    def test_finish_still_needs_a_consumed_stop_a_settled_queue_and_an_idle_tester(self):
        self.stranded()
        identity = self.publish()['request_id']
        with self.assertRaisesRegex(ValueError, 'Successor cancellation requires'):
            finish(self.c, 'g6')
        raw = (self.gate / 'request.json').read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        (self.gate / ('consumed-' + identity + '.json')).write_bytes(raw)
        write_json(self.gate / ('result-' + identity + '.json'), dict(request_id=identity, request_sha256=digest, status='CANCEL_RUN_CHANGED'))
        with self.assertRaisesRegex(ValueError, 'Successor cancellation requires'):
            finish(self.c, 'g6')
        write_json(self.gate / ('result-' + identity + '.json'), dict(request_id=identity, request_sha256=digest, status='CANCEL_SIGNAL_SENT_RECONCILE'))
        with self.assertRaisesRegex(ValueError, 'Native queue is not finished'):
            finish(self.c, 'g6')
        self.queue(['Completed', 'Completed', 'Error', 'Cancelled', 'Cancelled', 'Cancelled', 'Cancelled', 'Cancelled'])
        self.batch_ongoing = False; self.tester = 'running'; self.ea_tick()
        with self.assertRaisesRegex(ValueError, 'Tester idleness not confirmed'):
            finish(self.c, 'g6')
        self.assertNotIn(self.c.job('g6')['status'], ('completed', 'cancelled', 'failed'))

    def test_tampered_evidence_refuses_every_reader(self):
        successor = self.stranded()
        self.publish()
        path = self.gate / ('issued-' + successor + '.json')
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            cancel_id(self.c.root, self.c.job('g6'), self.gate)
        path.write_bytes(raw)
        link = self.c.root / 'cancel-successors' / (self.attempt + '.regrant-3.json')
        value = read_json(link)
        write_json(link, value | dict(request_id='f' * 64))
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            cancel_id(self.c.root, self.c.job('g6'), self.gate)
        write_json(link, value | dict(generation=4))
        with self.assertRaisesRegex(ValueError, 'link changed'):
            cancel_id(self.c.root, self.c.job('g6'), self.gate)

    def test_the_first_successor_rules_are_unchanged(self):
        successor = self.stranded()
        self.assertEqual(cancel_id(self.c.root, self.c.job('g6'), self.gate), successor)
        from studio_cancel_successor import create
        with self.assertRaisesRegex(ValueError, 'successor already exists'):
            create(self.c, 'g6')
        self.answer(successor, 'CANCEL_REJECTED', consumed=False, observed=self.now)
        record = self.step()
        self.assertEqual(record['failure']['code'], 'successor_rejected')   # the pause never replaces it by itself
        self.assertEqual(len(self.issued()), 2)

    def test_the_ea_checks_stay_in_place(self):
        source = (Path(__file__).resolve().parent.parent / 'GOATStudioDispatch.mqh').read_text(encoding='utf-8', errors='replace')
        for needle in ('AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO', '"CANCEL_CONTROL_REVOKED"',
                       '"CANCEL_NATIVE_OWNER_CHANGED"', 'expires<=(long)TimeGMT()'):
            self.assertIn(needle, source)


class VerbTests(StrandedFixture):
    def agent(self):
        class Terminal(demo_fixtures.Process):
            identity = dict(pid=91, executable=self.c.install['terminal_executable'], created_utc='2026-09-28T00:00:00Z')
        return DemoAgent(self.f.path, process=Terminal(), mt5=self.mt5, clock=lambda: self.now)

    def test_the_verb_runs_the_incident_from_publication_to_paused(self):
        self.stranded()
        agent = self.agent()
        published = agent.cancel_regrant('g6')
        self.assertEqual(published['status'], 'regrant_published_not_confirmed')
        self.assertEqual(self.ea_tick(), 'CANCELLED_RECONCILE'); self.ea_tick()
        with patch('studio_batch_pause.observe_monitor', return_value=ticking(self.now, tester_state='idle')):
            settled = agent.cancel_regrant('g6', settle=True)
        self.assertEqual((settled['status'], settled['batch_status'], settled['request_id']), ('paused', 'failed', published['request_id']))
        rows = [json.loads(line) for line in (agent.state_root / 'actions.jsonl').read_text().splitlines()]
        self.assertEqual([row['phase'] for row in rows if row['operation'] == 'cancel_regrant'],
                         ['intent', 'regrant_published_not_confirmed', 'paused'])

    def test_the_verb_is_allowed_under_owner_stop(self):
        self.stranded()
        agent = self.agent()
        agent.state_root.mkdir(parents=True, exist_ok=True)
        write_json(agent.state_root / 'STOP', dict(actor='demo_agent'))
        self.assertEqual(agent.cancel_regrant('g6')['status'], 'regrant_published_not_confirmed')

    def test_a_real_account_refuses_at_the_verb(self):
        self.stranded()
        self.mt5.trade_mode = 2
        with self.assertRaises(Refusal) as caught:
            self.agent().cancel_regrant('g6')
        self.assertEqual(caught.exception.code, 'REGRANT_BROKER_NOT_DEMO')
        self.assertEqual(len(self.issued()), 2)

    def test_an_unprocessed_human_request_refuses_and_is_not_touched(self):
        self.stranded()
        inbox = self.c.bridge.root / 'human' / 'inbox'; inbox.mkdir(parents=True, exist_ok=True)
        waiting = inbox / 'ui-take.json'; write_json(waiting, dict(request_id='ui-take'))
        with self.assertRaises(Refusal) as caught:
            self.agent().cancel_regrant('g6')
        self.assertEqual(caught.exception.code, 'REGRANT_HUMAN_PENDING')
        self.assertTrue(waiting.exists())
        self.assertEqual(len(self.issued()), 2)

    def test_a_live_driver_refuses(self):
        self.stranded()
        agent = self.agent()
        worker = agent.state_root / 'workers' / 'g6.json'; worker.parent.mkdir(parents=True, exist_ok=True)
        write_json(worker, dict(batch_id='g6', nonce='n' * 32, pid=5))
        with patch.object(DemoAgent, '_worker_alive', return_value=True), self.assertRaises(Refusal) as caught:
            agent.cancel_regrant('g6')
        self.assertEqual(caught.exception.code, 'REGRANT_LIVE_DRIVER')

    def test_cli_exposes_the_verb(self):
        with patch.object(DemoAgent, '__init__', return_value=None), \
                patch.object(DemoAgent, 'cancel_regrant', return_value=dict(status='paused')) as verb, patch('builtins.print'):
            demo_main(['--installation', 'x', 'cancel-regrant', '--batch-id', 'g6', '--settle'])
            verb.assert_called_once_with('g6', settle=True)
            verb.reset_mock()
            demo_main(['--installation', 'x', 'cancel-regrant', '--batch-id', 'g6'])
            verb.assert_called_once_with('g6', settle=False)


if __name__ == '__main__':
    unittest.main()
