"""GOAT-EA#323: a successor whose first driver start is refused before MT5 is touched.

T2, 2026-11-12: cancel-regrant --settle paused replay288-a1-r1, batch-resume created replay288-a1-r2 and
spawned its driver, and the driver's first runtime read was a sample older than 20 s, so the start ended
``start_uncertain`` with no attempt 0.5 s later. batch-resume, resume-batch, retire-unactivated and batch-pause
then each refused r2 for a different reason, none named a way on, and research-status said it needed nothing.

These fixtures prove, on the retained state that sequence leaves:
* the start's first read waits for a fresh sample (the 20 s bound itself unchanged), and only that read;
* the same start again under the same batch ID (run-batch) is the one command, and it runs the batch;
* research-status and every one of those refusals name it.
"""
from contextlib import contextmanager, nullcontext
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_pause as pause
import studio_runtime_check as runtime_check
from studio_runtime_check import STALE, await_fresh, check_runtime
from studio_batch_driver import refused_before_dispatch, refused_start_hint, restart_command, run
import test_demo_agent as demo_fixtures
import test_studio_batch_driver as driver_fixtures
import test_studio_config_start as config_fixtures

PARENT, SUCCESSOR = 'replay288-a1-r1', 'replay288-a1-r2'
ATTEMPT = 'a' * 64


class FakeTime:
    """studio_runtime_check's clock: sleep advances it and runs ``on_sleep``; a runaway wait fails the test."""

    def __init__(self, start=1_794_461_664.0):
        self.now, self.sleeps, self.on_sleep = start, [], None

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) > 500:
            raise AssertionError('the wait never ended')
        self.now += seconds
        if self.on_sleep:
            self.on_sleep()


def refused_journal(job_id, **overrides):
    """The driver journal the T2 start left (d7-bds.out): start issued, no attempt, nothing dispatched."""
    record = dict(schema_version=2, binding=dict(job_id=job_id, generation=4), max_seconds=7200,
                  min_free_bytes=5 * 1024**3, started_wall=1794461664.44, deadline_wall=1794468864.44,
                  last_wall=1794461664.96, start_issued=True, attempt_id=None, cancel_issued=False, stopped=False,
                  status='start_uncertain', cancel_grace_seconds=120, start_route='config_restart', last_error=STALE,
                  recovery=dict(phase=None, mt5='not_touched'))
    record.update(overrides)
    return record


class FreshSampleWaitTests(unittest.TestCase):
    """await_fresh over the real check_runtime and a real observation file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'ui-observation.json'
        self.clock = FakeTime()
        clock = patch.object(runtime_check, 'time', self.clock); clock.start(); self.addCleanup(clock.stop)
        self.args = dict(data_path=r'C:\data', installation_path=r'C:\mt5', program_path=r'C:\data\GOAT.ex5',
                         account_login='123', account_server='Demo', require_idle=True, expected_batch_ongoing=False)
        self.reads = 0

    def sample(self, age, **runtime):
        """The EA writes a sample observed ``age`` seconds ago."""
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(self.clock.now - age, timezone.utc).strftime('%Y.%m.%d %H:%M:%S')
        write_json(self.file, dict(schema_version=1, bound=True, observed_terminal_utc=stamp, runtime=dict(dict(
            data_path=r'C:\data', installation_path=r'C:\mt5', program_path=r'C:\data\GOAT.ex5', account_login='123',
            account_server='Demo', connected=True, account_demo=True, terminal_trade_allowed=False, batch_ongoing=False,
            restart_pending=False, tester_state='idle'), **runtime)))
        os.utime(self.file, (self.clock.now - age, self.clock.now - age))

    def read(self):
        self.reads += 1
        return check_runtime(json.loads(self.file.read_text()), now=self.clock.now,
                             modified=self.file.stat().st_mtime, **self.args)

    def test_the_twenty_second_bound_is_unchanged(self):
        self.sample(19)
        self.assertEqual(self.read()['status'], 'research_binding_and_flags_match')
        self.sample(21)
        with self.assertRaisesRegex(ValueError, STALE):
            self.read()

    def test_a_stale_first_sample_is_read_again_until_the_ea_reports(self):
        self.sample(30)
        def ea_reports_after_three_polls():
            if len(self.clock.sleeps) == 3:
                self.sample(1)
        self.clock.on_sleep = ea_reports_after_three_polls
        notes, between = [], []
        result = await_fresh(self.read, between=lambda: between.append(self.reads), note=notes.append)
        self.assertEqual(result['status'], 'research_binding_and_flags_match')
        self.assertEqual((self.reads, len(self.clock.sleeps), between), (4, 3, [1, 2, 3]))
        self.assertEqual(notes, [dict(polls=3, waited_seconds=3.0, fresh=True)])

    def test_a_sample_that_stays_stale_still_refuses_with_the_same_error_after_the_wait(self):
        self.sample(30)
        notes = []
        with self.assertRaises(ValueError) as caught:
            await_fresh(self.read, note=notes.append)
        self.assertEqual(str(caught.exception), 'Runtime feedback is stale or future-dated')
        waited = sum(self.clock.sleeps)
        self.assertEqual((waited, notes[0]['fresh']), (runtime_check.START_FRESH_WAIT_SECONDS, False))
        self.assertGreaterEqual(self.reads, 2, 'every repeat is the whole check again')

    def test_a_fresh_sample_never_waits_and_any_other_refusal_is_raised_at_once(self):
        self.sample(2)
        notes = []
        await_fresh(self.read, note=notes.append)
        self.assertEqual((self.clock.sleeps, notes), ([], []))
        for runtime, message in ((dict(terminal_trade_allowed=True), 'terminal_trade_allowed'),
                                 (dict(account_login='999'), 'Runtime account mismatch'),
                                 (dict(tester_state='running'), 'Tester idleness not confirmed'),
                                 (dict(batch_ongoing=True), 'batch_ongoing')):
            with self.subTest(message=message):
                self.sample(2, **runtime)
                with self.assertRaisesRegex(ValueError, message):
                    await_fresh(self.read)
                self.assertEqual(self.clock.sleeps, [], 'only a stale sample is waited for')

    def test_a_stale_sample_that_turns_fresh_but_wrong_refuses_on_the_wrong_part(self):
        self.sample(30)
        self.clock.on_sleep = lambda: self.sample(1, terminal_trade_allowed=True)
        with self.assertRaisesRegex(ValueError, 'terminal_trade_allowed'):
            await_fresh(self.read)
        self.assertEqual(len(self.clock.sleeps), 1)

    def test_the_checkpoint_between_reads_ends_the_wait(self):
        self.sample(30)
        def stop():
            raise ValueError('Owner STOP during config start')
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            await_fresh(self.read, between=stop)
        self.assertEqual((self.reads, len(self.clock.sleeps)), (1, 1))


class ConfigStartWaitTests(config_fixtures.ConfigStartTests):
    """The /config start: its first runtime read waits; every later read refuses a stale sample at once."""

    def setUp(self):
        super().setUp()
        self.clock = FakeTime()
        clock = patch.object(runtime_check, 'time', self.clock); clock.start(); self.addCleanup(clock.stop)

    def test_stale_then_fresh_first_read_starts_the_batch_after_waiting(self):
        self.c.runtime.side_effect = [ValueError(STALE), ValueError(STALE), None, None]
        result = self.run_start()
        self.assertEqual(result['status'], 'config_process_started_unverified')
        self.assertEqual(self.events, ['reserve', 'install', 'arm', 'close', 'launch'])
        self.assertEqual((len(self.clock.sleeps), self.c.start_runtime_wait['polls'], self.c.start_runtime_wait['fresh']),
                         (2, 2, True))

    def test_permanently_stale_first_read_refuses_after_the_wait_with_nothing_reserved_or_sent(self):
        self.c.runtime.side_effect = ValueError(STALE)
        with self.assertRaises(ValueError) as caught:
            self.run_start()
        self.assertEqual(str(caught.exception), 'Runtime feedback is stale or future-dated')
        self.assertEqual(sum(self.clock.sleeps), runtime_check.START_FRESH_WAIT_SECONDS)
        self.assertEqual(self.events, [])
        self.assertEqual(self.c.job('batch')['status'], 'pending')
        self.assertNotIn('launch_intent', self.c.job('batch'))
        for name in ('record_intent', '_install_controls', 'publish_restart_arm'):
            self.mocks[name].assert_not_called()
        self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_owner_stop_during_the_wait_ends_it_with_nothing_reserved(self):
        self.c.runtime.side_effect = ValueError(STALE)
        folder = self.c.root / 'demo-agent'; folder.mkdir()
        self.clock.on_sleep = lambda: (folder / 'STOP').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.run_start()
        self.assertEqual((len(self.clock.sleeps), self.events), (1, []))

    def test_a_stale_armed_sample_after_the_arm_refuses_at_once_and_never_closes(self):
        # After the arm MT5 holds a batch flag: a monitor that stopped reporting then must stop the start, not be
        # waited for. Only 'Runtime policy mismatch: batch_ongoing' is retried there (its own 15 s loop).
        self.c.runtime.side_effect = [None, ValueError(STALE)]
        with self.assertRaisesRegex(ValueError, STALE):
            self.run_start()
        self.assertEqual(self.clock.sleeps, [])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()


class RefusedSuccessorDriverTests(unittest.TestCase):
    """The bounded driver on the /config route (demo lane), with the stale read at the start."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.c = driver_fixtures.Controller(self.temp.name)
        self.c.session.update(authority_kind='demo_direct')
        write_json(self.c.root / 'session.json', self.c.session)
        self.c.bridge = SimpleNamespace(root=self.c.local / self.c.run)
        self.clock = FakeTime()
        clock = patch.object(runtime_check, 'time', self.clock); clock.start(); self.addCleanup(clock.stop)
        for target in ('studio_batch_driver._verify_package',):
            patcher = patch(target); patcher.start(); self.addCleanup(patcher.stop)
        disk = patch('studio_batch_driver.shutil.disk_usage', return_value=SimpleNamespace(free=100 * 1024**3))
        disk.start(); self.addCleanup(disk.stop)
        end = patch('studio_research_profile.batch_end_state', return_value=dict(status='monitor_relaunched'))
        end.start(); self.addCleanup(end.stop)
        self.samples = []          # what each runtime read of the start sees: 'stale' or 'fresh'
        def config_start(job_id, *, expected_generation, on_attempt):
            # studio_config_start.start's own first step: the awaited runtime read, then the reservation.
            def read():
                if (self.samples.pop(0) if self.samples else 'stale') == 'stale':
                    raise ValueError(STALE)
            await_fresh(read, note=lambda waited: setattr(self.c, 'start_runtime_wait', waited))
            self.c.start(job_id, expected_generation=expected_generation)
            on_attempt(self.c.current['launch_intent'])
        self.c.start_config = config_start
        self.journal = self.c.root / 'batch-drivers' / 'batch.json'

    def drive(self, **kwargs):
        return run(self.c, 'batch', poll_seconds=1, cancel_grace_seconds=2, clock=self.c.clock, finish_fn=self.c.finish,
                   **kwargs)

    def refuse(self):
        self.samples = []          # every read stale
        first = self.drive(max_seconds=7200)
        self.assertEqual((first['status'], first['attempt_id'], first['start_issued'], first['start_route'],
                          first['last_error'], first['recovery']['mt5']),
                         ('start_uncertain', None, True, 'config_restart', STALE, 'not_touched'))
        self.assertEqual((self.c.starts, self.c.current['status']), (0, 'pending'))
        self.assertNotIn('launch_intent', self.c.current)
        return first

    def test_stale_then_fresh_start_succeeds_after_waiting_and_the_journal_says_how_long(self):
        self.samples = ['stale', 'stale', 'stale', 'fresh']
        self.c.finished = True
        result = self.drive(max_seconds=7200)
        self.assertEqual((result['status'], self.c.starts), ('completed', 1))
        self.assertEqual(json.loads(self.journal.read_text())['start_runtime_wait'],
                         dict(polls=3, waited_seconds=3.0, fresh=True))
        self.assertFalse((self.c.root / 'batch-driver-refusals').exists(), 'no refused journal: the race never strands it')

    def test_permanently_stale_start_still_fails_the_same_way_after_the_wait_with_nothing_dispatched(self):
        first = self.refuse()
        saved = json.loads(self.journal.read_text())
        self.assertEqual(saved['start_runtime_wait']['fresh'], False)
        self.assertEqual(sum(self.clock.sleeps), runtime_check.START_FRESH_WAIT_SECONDS)
        self.assertTrue(refused_before_dispatch(saved, self.c.current))
        # The driver's own recovery text no longer points at retire-unactivated for this state.
        self.assertIn('start this batch again under the same batch ID with run-batch', first['recovery']['next_safe_action'])
        self.assertNotIn('retire-unactivated settles', first['recovery']['next_safe_action'])

    def test_the_same_start_again_is_the_supported_command_and_the_batch_runs(self):
        self.refuse()
        self.samples = ['fresh']
        self.c.finished = True
        result = self.drive(max_seconds=7200)
        self.assertEqual((result['status'], self.c.starts), ('completed', 1))
        archived = sorted(item.name for item in (self.c.root / 'batch-driver-refusals').iterdir())
        self.assertEqual(archived, ['batch.refused-1.json'], 'the refused journal is kept as evidence')
        kept = json.loads((self.c.root / 'batch-driver-refusals' / 'batch.refused-1.json').read_text())
        self.assertEqual((kept['status'], kept['last_error']), ('start_uncertain', STALE))

    def test_resume_never_starts_it_leaves_the_journal_alone_and_names_the_command(self):
        self.refuse()
        before = self.journal.read_bytes()
        self.c.snapshot['generation'] += 1      # T2: the binding no longer matched by the time resume-batch ran
        result = self.drive(resume=True)
        self.assertEqual((result['status'], result['attempt_id'], self.c.starts), ('start_uncertain', None, 0))
        self.assertIn('run-batch --batch-id batch --max-seconds <budget>', result['next_action'])
        self.assertEqual(self.journal.read_bytes(), before)

    def test_resume_of_a_start_that_reached_mt5_keeps_its_binding_refusal(self):
        # Negative for the hint: an attempt was bound, so this is not the refused-before-dispatch state.
        self.samples = ['fresh']
        self.c.start_error = True               # the native start reply is lost after the attempt is recorded
        original = self.c.start
        def start(job_id, *, expected_generation):
            self.c.current.update(status='starting', launch_intent=dict(
                attempt_id=ATTEMPT, package=str(self.c.root / 'packages' / 'batch'), package_sha256=self.c.package_hash))
            original(job_id, expected_generation=expected_generation)
        self.c.start = start
        first = self.drive(max_seconds=7200)
        self.assertEqual(first['status'], 'start_uncertain')
        self.assertIsNone(refused_start_hint(self.c.root, self.c.current))
        self.c.snapshot['generation'] += 1
        with self.assertRaisesRegex(ValueError, 'Batch/session/ownership changed; resume refused'):
            self.drive(resume=True)

    def test_pause_and_studio_batch_resume_each_name_the_commands(self):
        self.refuse()
        command = 'run-batch --batch-id batch --max-seconds <budget>'
        self.assertIn('retire-unactivated --batch-id batch', refused_start_hint(self.c.root, self.c.current))
        with self.assertRaises(pause.PauseRefused) as paused:
            pause.request(self.c.root, self.c.current, json.loads(self.journal.read_text()), now=1.0)
        self.assertIn('not running, so there is nothing to pause.', str(paused.exception))
        self.assertIn(command, str(paused.exception))
        with self.assertRaises(pause.PauseRefused) as resumed:
            pause.verify_resumable(self.c, 'batch')
        self.assertIn('No pause is recorded for batch batch, and it needs none.', str(resumed.exception))
        self.assertIn(command, str(resumed.exception))
        self.assertEqual((self.c.starts, self.c.current['status']), (0, 'pending'), 'a refusal changes nothing')

    def test_the_same_refusals_keep_their_own_words_for_a_batch_that_is_not_in_this_state(self):
        from studio_retire_unactivated import retire
        # A pending batch that was never started (no journal): nothing to name.
        for call, expected in ((lambda: retire(self.c, 'batch'),
                                'Batch batch is pending with no unactivated start to retire; research-status shows what it needs.'),
                               (lambda: pause.request(self.c.root, self.c.current, None, now=1.0),
                                'Batch batch is pending, not running, so there is nothing to pause.'),
                               (lambda: pause.verify_resumable(self.c, 'batch'),
                                'No pause is recorded for batch batch; pause it first.')):
            with self.assertRaises(ValueError) as caught:
                call()
            self.assertEqual(str(caught.exception), expected)

    def test_the_hint_is_only_for_the_exact_refused_state_and_is_worded_per_lane(self):
        pending = dict(job_id='b', status='pending')
        refused = refused_journal('b')
        self.assertIn('run-batch --batch-id b --max-seconds <budget>',
                      refused_start_hint(self.c.root, pending, refused, dict(authority_kind='demo_direct')))
        self.assertIn(STALE, refused_start_hint(self.c.root, pending, refused, {}))
        for journal, job in ((dict(refused, attempt_id=ATTEMPT), pending), (dict(refused, cancel_issued=True), pending),
                             (dict(refused, stopped=True), pending), (dict(refused, status='observing'), pending),
                             (refused, dict(pending, launch_intent=dict(attempt_id=ATTEMPT))),
                             (refused, dict(pending, status='starting')), (refused, dict(pending, status='cancelled')),
                             (None, pending), (refused, None)):
            with self.subTest(journal=journal, job=job):
                self.assertIsNone(refused_start_hint(self.c.root / 'absent', job, journal, {}))
        self.assertEqual(restart_command('b', dict(authority_kind='demo_direct')), 'run-batch --batch-id b --max-seconds <budget>')
        self.assertEqual(restart_command('b', None), 'run-batch --job-id b --max-seconds <budget>')
        self.assertIn('--job-id b --max-seconds <budget> --mt5-restart-consent',
                      restart_command('b', dict(authority_kind='native_human_control')))

    def test_recovery_text_separates_nothing_recorded_from_an_attempt_at_phase_prepared(self):
        from studio_config_start import restart_recovery
        nothing = restart_recovery(dict(job_id='b', status='pending'))
        prepared = restart_recovery(dict(job_id='b', status='starting', launch_intent=dict(attempt_id=ATTEMPT),
                                         restart_intent=dict(phase='prepared')))
        self.assertEqual((nothing['mt5'], prepared['mt5']), ('not_touched', 'not_touched'))
        self.assertIn('run-batch', nothing['next_safe_action'])
        self.assertIn('or settle it as cancelled with retire-unactivated', nothing['next_safe_action'])
        self.assertNotIn('batch-continue', nothing['next_safe_action'])
        self.assertIn('retire-unactivated settles this start', prepared['next_safe_action'])


class RefusedSuccessorDemoToolTests(unittest.TestCase):
    """The demo tool on the retained T2 state: parent paused and resumed, successor pending, its start refused."""

    def setUp(self):
        self.f = demo_fixtures.DemoAgentTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.agent = self.f.agent
        self.agent.session['authority_kind'] = 'demo_direct'
        write_json(self.agent.root / 'session.json', self.agent.session)
        members = dict(batch_members=[{}, {}, {}])
        self.parent = dict(job_id=PARENT, status='running', configuration_sha256='c' * 64, configuration=members,
                           launch_intent=dict(attempt_id=ATTEMPT))
        self.successor = dict(job_id=SUCCESSOR, status='pending', configuration_sha256='d' * 64, configuration=members)
        self.queue = [self.parent]
        jobs = patch.object(type(self.agent), '_jobs_readonly', lambda agent: copy.deepcopy(self.queue))
        jobs.start(); self.addCleanup(jobs.stop)
        drivers = self.agent.root / 'batch-drivers'; drivers.mkdir(parents=True)
        write_json(drivers / (PARENT + '.json'), dict(schema_version=2, attempt_id=ATTEMPT, max_seconds=7200,
                   binding=dict(job_id=PARENT, generation=4), cancel_issued=True, stopped=False, status='stop_unconfirmed',
                   cancel_reason='owner_stop'))
        # Pause settled, successor created (batch-resume's own records), first driver start refused.
        with patch.object(self.agent, '_spawn_driver', return_value=dict(status='driver_journal_recorded')):
            self.agent.batch_pause(PARENT)
        record = pause.load(self.agent.root, PARENT)
        record.update(state='resumed', phase='resumed', resume_token='t' * 64, successor_batch_id=SUCCESSOR,
                      resume_batch_id=SUCCESSOR)
        write_json(pause.path(self.agent.root, PARENT), record)
        self.parent.update(status='cancelled')
        self.queue.append(self.successor)
        self.journal = drivers / (SUCCESSOR + '.json')
        write_json(self.journal, refused_journal(SUCCESSOR))
        self.command = 'run-batch --batch-id ' + SUCCESSOR + ' --max-seconds <budget>'

    @contextmanager
    def terminal(self):
        """The broker-verified scope with a queue-only controller: no MT5, no store."""
        controller = SimpleNamespace(root=self.agent.root, job=lambda job_id: copy.deepcopy(
            next(item for item in self.queue if item['job_id'] == job_id)), state=lambda: dict(generation=4))
        @contextmanager
        def studio(*args, **kwargs):
            yield controller, dict(login='3000082754', server='Darwinex-Demo')
        with patch.object(self.agent, '_exclusive', lambda **kwargs: nullcontext()), \
                patch.object(self.agent, '_studio', studio), patch('studio_batch_driver.status', return_value={}):
            yield

    def test_research_status_names_the_command_in_next_action(self):
        value = self.agent.research_status()
        activity = value['activity']
        self.assertEqual((activity['batch_id'], activity['status'], activity['queue_status']), (SUCCESSOR, 'pending', 'pending'))
        self.assertIn(self.command, activity['next_action'])
        self.assertIn('retire-unactivated --batch-id ' + SUCCESSOR, activity['next_action'])
        self.assertIn('Runtime feedback is stale or future-dated', activity['next_action'])
        self.assertEqual(activity['headline'], activity['next_action'])
        self.assertEqual((value['driver']['journal_status'], value['driver']['fix']), ('start_uncertain', activity['next_action']))
        self.assertTrue(value['read_only'])

    def test_research_status_next_action_is_null_for_a_batch_that_is_not_in_this_state(self):
        for journal in (None, refused_journal(SUCCESSOR, status='start_issued'), refused_journal(SUCCESSOR, attempt_id=ATTEMPT)):
            with self.subTest(journal=journal):
                if journal is None:
                    self.journal.unlink()
                else:
                    write_json(self.journal, journal)
                value = self.agent.research_status()
                self.assertIsNone(value['activity']['next_action'])
                self.assertEqual(value['activity']['headline'], 'Batch pending; 0 of 3 members done.')
                self.assertNotIn('fix', value['driver'])

    def test_batch_resume_on_the_successor_names_the_command_instead_of_pause_it_first(self):
        with patch.object(self.agent, '_exclusive', side_effect=AssertionError('reached the terminal')), \
                self.assertRaises(pause.PauseRefused) as caught:
            self.agent.batch_resume(SUCCESSOR)
        self.assertIn(self.command, str(caught.exception))
        self.assertNotIn('pause it first', str(caught.exception))

    def test_batch_resume_on_the_parent_starts_nothing_and_names_the_command(self):
        with patch.object(self.agent, '_spawn_driver', side_effect=AssertionError('a second start path')), \
                patch.object(self.agent, '_exclusive', side_effect=AssertionError('reached the terminal')):
            result = self.agent.batch_resume(PARENT)
        self.assertEqual((result['state'], result['batch_id'], result['driver']), ('resumed', SUCCESSOR, None))
        self.assertIn(self.command, result['next_action'])
        self.assertEqual(pause.load(self.agent.root, PARENT)['state'], 'resumed', 'the lineage is not released')

    def test_batch_pause_on_the_successor_names_the_command(self):
        with self.assertRaises(pause.PauseRefused) as caught:
            self.agent.batch_pause(SUCCESSOR)
        self.assertIn('is pending, not running, so there is nothing to pause.', str(caught.exception))
        self.assertIn(self.command, str(caught.exception))

    def test_resume_batch_refuses_with_the_command_and_launches_no_worker(self):
        with self.terminal(), patch('studio_durable_driver.launch', side_effect=AssertionError('a worker was launched')), \
                patch('demo_agent.subprocess.Popen', side_effect=AssertionError('a worker was launched')), \
                self.assertRaises(ValueError) as caught:
            self.agent.resume_batch(SUCCESSOR)
        self.assertIn('resume-batch has no attempt to resume', str(caught.exception))
        self.assertIn(self.command, str(caught.exception))
        self.assertFalse((self.agent.state_root / 'workers' / (SUCCESSOR + '.json')).exists())
        self.assertEqual(json.loads(self.journal.read_text()), refused_journal(SUCCESSOR))

    def launched(self, spawned):
        """A detached driver that records its journal, as the real one does before any dispatch."""
        def launch(argv, **kwargs):
            spawned.append(argv)
            write_json(self.journal, refused_journal(SUCCESSOR, status='start_issued', last_error=None))
            return SimpleNamespace(pid=4242, poll=lambda: None)
        return launch

    def test_run_batch_is_accepted_in_this_state_archives_the_refusal_and_starts_one_driver(self):
        (self.agent.root / 'batch-driver-gate').mkdir()
        spawned = []
        with self.terminal(), patch('studio_durable_driver.launch', side_effect=self.launched(spawned)), \
                patch('demo_agent.subprocess.Popen', side_effect=lambda argv, **kwargs: self.launched(spawned)(argv)):
            result = self.agent.run_batch(SUCCESSOR, 7200)
        self.assertEqual((result['status'], result['driver_status'], len(spawned)), ('driver_journal_recorded', 'start_issued', 1))
        self.assertIn('--max-seconds', spawned[0])
        self.assertNotIn('--pause-seconds', spawned[0])
        archive = self.agent.root / 'batch-driver-refusals' / (SUCCESSOR + '.refused-1.json')
        self.assertEqual(json.loads(archive.read_text()), refused_journal(SUCCESSOR))

    def test_a_dead_worker_still_recorded_supervising_reads_exited(self):
        from studio_research_status import worker_status_now
        self.assertEqual([worker_status_now('supervising', alive) for alive in (False, True, None)],
                         ['exited', 'supervising', 'supervising'])
        self.assertEqual(worker_status_now('returned', False), 'returned')
        workers = self.agent.state_root / 'workers'; workers.mkdir(parents=True, exist_ok=True)
        write_json(workers / (SUCCESSOR + '.json'), dict(schema_version=1, batch_id=SUCCESSOR, nonce='c' * 32, pid=46212,
                                                         resume=True, max_seconds=None, status='supervising'))
        for alive, expected in ((False, 'exited'), (True, 'supervising')):
            with self.subTest(alive=alive), patch.object(self.agent, '_worker_alive', return_value=alive):
                self.assertEqual(self.agent.research_status()['driver']['worker_status'], expected)
                shown = self.agent._batch_worker(SUCCESSOR)
                self.assertEqual((shown['status'], shown.get('recorded_status')),
                                 (expected, 'supervising' if not alive else None))

    def test_run_batch_never_restarts_a_journal_that_bound_an_attempt(self):
        write_json(self.journal, refused_journal(SUCCESSOR, attempt_id=ATTEMPT))
        with self.terminal(), patch('studio_durable_driver.launch', side_effect=AssertionError('restarted')), \
                patch('demo_agent.subprocess.Popen', side_effect=AssertionError('restarted')):
            result = self.agent.run_batch(SUCCESSOR, 7200)
        self.assertEqual(result['status'], 'existing_driver')
        self.assertFalse((self.agent.root / 'batch-driver-refusals').exists())


class RetireRefusedStartTests(unittest.TestCase):
    """retire-unactivated on a real controller store and prepared package: it settles exactly the refused state
    (modelled on replay288-a1-r2's records) and still refuses whatever may have reached MT5."""

    def setUp(self):
        import test_studio_retire_unactivated as retire_fixtures
        self.f = retire_fixtures.RetireUnactivatedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.c = self.f.c
        self.journal = self.c.root / 'batch-drivers' / 'g6-r1.json'
        self.journal.parent.mkdir(exist_ok=True)

    def refused(self, **overrides):
        write_json(self.journal, refused_journal('g6-r1', **overrides))

    def retire(self):
        from studio_retire_unactivated import retire
        return retire(self.c, 'g6-r1')

    def test_it_settles_the_refused_successor_needs_no_fresh_sample_and_frees_the_lineage(self):
        from studio_retire_unactivated import REFUSED_KIND
        self.refused()
        original = json.loads(self.journal.read_text())
        parent = dict(state='resumed', successor_batch_id='g6-r1', resume_batch_id='g6-r1')
        self.assertIsNone(pause.releasable(parent, {'g6-r1': self.c.job('g6-r1')}), 'a pending successor holds the lineage')
        # The cause of the refusal may still be there: the settlement sends nothing and reads no runtime sample.
        with patch.object(self.c, 'runtime', side_effect=ValueError(STALE)):
            result = self.retire()
        self.assertEqual((result['status'], result['kind'], result['attempt_id'], result['executed_members'],
                          result['native_cancellation_claimed'], result['reused']),
                         ('cancelled', REFUSED_KIND, None, 0, False, False))
        job = self.c.job('g6-r1')
        self.assertEqual(job['status'], 'cancelled')
        self.assertNotIn('launch_intent', job)
        saved = json.loads(self.journal.read_text())
        self.assertEqual((saved['status'], saved['stopped'], saved['retired'], saved['last_error'], saved['attempt_id']),
                         ('cancelled', True, REFUSED_KIND, STALE, None))
        self.assertEqual(json.loads(Path(result['driver_journal']['previous']).read_text()), original)
        successor, proof = pause.releasable(parent, {'g6-r1': job})
        self.assertEqual((successor, proof['kind']), ('g6-r1', 'cancelled_before_start'),
                         'batch-resume on the parent now prepares a new successor')
        again = self.retire()
        self.assertEqual((again['status'], again['kind'], again['reused']), ('cancelled', REFUSED_KIND, True))
        self.assertIsNone(refused_start_hint(self.c.root, job), 'a settled batch is no longer told to start again')

    def test_a_human_owner_refuses_and_nothing_changes(self):
        self.refused()
        state = self.c.state()
        with patch.object(self.c, 'state', return_value=dict(state, owner='human')), \
                self.assertRaisesRegex(ValueError, 'A human has taken control'):
            self.retire()
        self.assertEqual(self.c.job('g6-r1')['status'], 'pending')
        self.assertEqual(json.loads(self.journal.read_text()), refused_journal('g6-r1'))

    def test_a_start_that_recorded_an_attempt_goes_through_the_full_proof_and_is_refused_when_it_reached_mt5(self):
        # Negative 1: controls were installed (restart phase past 'prepared').
        self.f.unactivated(phase='controls_installed')
        with self.assertRaisesRegex(ValueError, 'reached restart phase controls_installed'):
            self.retire()
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')

    def test_a_refused_looking_journal_never_settles_a_job_with_a_launch_intent_and_activation_evidence(self):
        # Negative 2: the journal reads exactly like r2's, but the queue recorded an attempt and its evidence folder
        # exists, so MT5 may have been reached.
        attempt = self.f.unactivated(phase='prepared')
        self.refused()
        (self.c.root / 'attempts' / attempt).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Activation evidence exists'):
            self.retire()
        self.assertEqual(self.c.job('g6-r1')['status'], 'reconcile_required')
        self.assertEqual(json.loads(self.journal.read_text()), refused_journal('g6-r1'))

    def test_journals_that_are_not_the_refused_state_keep_the_old_refusal_and_the_job_stays_pending(self):
        for overrides in (dict(attempt_id=ATTEMPT), dict(cancel_issued=True), dict(status='observing'),
                          dict(start_issued=False), dict(binding=dict(job_id='another'))):
            with self.subTest(overrides=overrides):
                self.refused(**overrides)
                with self.assertRaisesRegex(ValueError, 'is pending with no unactivated start to retire; research-status'):
                    self.retire()
                self.assertEqual(self.c.job('g6-r1')['status'], 'pending')
                self.assertEqual(json.loads(self.journal.read_text()), refused_journal('g6-r1', **overrides))


if __name__ == '__main__':
    unittest.main()
