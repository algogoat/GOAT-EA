"""Detached seed, catch-up and hold-up drivers (goatai#1885 PR C, Claude-Mac answer 4).

seed-start/seed-resume used to drive in the caller's process, with MT5 as that process's child, so a
tool timeout that killed the caller killed MT5 mid-member (T2 seedhunt-t2-4-b41). They now hand the
drive to the run-batch demand-task host (studio_durable_driver). The real DemoAgent and SeedRunner run;
the Windows task launch is replaced by a fake that still passes the durable host's own validator.
"""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_agent
from demo_agent import DemoAgent, read_json, write_json
import studio_durable_driver
import test_demo_catchup_agent as catchup_fixture
import test_demo_holdup_agent as holdup_fixture
import test_demo_seed_agent as seed_fixture
from test_demo_seed_agent import MONITOR


class DurableReceipts:
    """The durable host's files beside a lane record, as Windows leaves them, and Windows' view of their processes.

    studio_durable_driver.launch retains <kind>-<id>-<nonce>.launch.json, then the bootstrap retains
    <kind>-<id>-<nonce>.started.json with ITS OWN pid and nonce and runs demo_agent.main in that same process, so the
    started receipt names the running driver itself (goatai#1885, Claude-PC Ops comment 6029461500).
    """

    def detached(self):
        """studio_durable_driver.launch as Windows runs it: the validated envelope, then the bootstrap's started receipt.
        The driver is this test process (it calls _drive_lane in-process), so the receipt carries os.getpid()."""
        def fake(argv, *, log_path, worker_path):
            worker, _ = studio_durable_driver.validate(argv, log_path, worker_path)
            self.receipts(Path(worker_path), Path(log_path), worker['nonce'], pid=os.getpid(), argv=argv)
            return SimpleNamespace(pid=os.getpid())
        return patch('studio_durable_driver.launch', side_effect=fake)

    @staticmethod
    def receipts(worker_path, log_path, nonce, *, pid, finished=False, argv=()):
        prefix = Path(log_path).with_suffix('')
        envelope, started, done = (Path(str(prefix) + '.' + name + '.json') for name in ('launch', 'started', 'finished'))
        write_json(envelope, dict(schema_version=1, argv=list(argv), log_path=str(log_path), worker_path=str(worker_path),
                                  started=str(started), finished=str(done), task_name='GOAT-Demo-' + 'd' * 16 + '-' + nonce))
        write_json(worker_path, dict(read_json(worker_path), launch_envelope=str(envelope), launch_mechanism='windows_demand_task'))
        write_json(started, dict(pid=pid, nonce=nonce, at='2026-10-06T00:00:00+00:00', native_running_verified=False))
        if finished:
            write_json(done, dict(exit_code=0, nonce=nonce))
        return envelope

    def lane_record(self, kind, batch_id, *, pid, status='supervising', finished=False):
        """A detached lane driver record with its launch envelope and started (optionally finished) receipt."""
        nonce = secrets.token_hex(16)
        path = self.root / 'demo-agent/lane-workers' / (kind + '-' + batch_id + '.json')
        write_json(path, dict(schema_version=1, kind=kind, batch_id=batch_id, nonce=nonce, status=status, initial=True,
                              max_seconds=600, pid=pid))
        self.receipts(path, path.with_name(kind + '-' + batch_id + '-' + nonce + '.log'), nonce, pid=pid, finished=finished)
        return read_json(path)

    @staticmethod
    def bootstrap_command(record):
        """The command line Windows shows for a running bootstrap: its envelope path carries the driver's nonce."""
        return 'C:\\GOAT\\python\\pythonw.exe studio_durable_driver.py --envelope "' + record['launch_envelope'] + '"'

    @staticmethod
    def processes(table):
        """Windows' process view for _worker_alive ({pid: command line}); any other PowerShell query is a test error."""
        def query(script, **kwargs):
            match = re.search(r'ProcessId = (\d+)"', script)
            if 'Win32_Process' not in script or match is None:
                raise AssertionError('unexpected PowerShell query: ' + script[:120])
            pid = int(match.group(1))
            return json.dumps(dict(ProcessId=pid, CommandLine=table[pid])) if pid in table else ''
        return patch('studio_process_query.powershell_text', side_effect=query)

    def drive_detached(self, kind, batch_id, start, max_seconds):
        """Start detached with the real receipts on disk, then run the demand task's drive with its own receipt live."""
        with self.detached():
            self.assertEqual(start(batch_id, max_seconds, detach=True)['status'], 'driver_starting')
        folder = self.root / 'demo-agent/lane-workers'
        worker = read_json(folder / (kind + '-' + batch_id + '.json'))
        stem = kind + '-' + batch_id + '-' + worker['nonce']
        self.assertEqual(sorted(p.name for p in folder.glob('*.json')),
                         sorted([kind + '-' + batch_id + '.json', stem + '.launch.json', stem + '.started.json']))
        self.auto = True
        with self.processes({os.getpid(): self.bootstrap_command(worker)}):
            driven = self.agent._drive_lane(kind, batch_id, worker['nonce'], max_seconds, True)
        self.assertEqual(driven['status'], 'completed')
        self.assertEqual(read_json(folder / (kind + '-' + batch_id + '.json'))['status'], 'returned')
        return driven


class LaneDriverTests(DurableReceipts, unittest.TestCase):
    # Borrowed fixture methods (through the module, so its own tests are not collected again here).
    setUp = seed_fixture.DemoSeedAgentTests.setUp
    database = seed_fixture.DemoSeedAgentTests.database
    new_agent = seed_fixture.DemoSeedAgentTests.new_agent
    sleep = seed_fixture.DemoSeedAgentTests.sleep
    manifest = seed_fixture.DemoSeedAgentTests.manifest
    finish_member = seed_fixture.DemoSeedAgentTests.finish_member
    actions = seed_fixture.DemoSeedAgentTests.actions

    def launched(self):
        """The demand-task launch, as studio_durable_driver.launch would see it: the host validator must accept it."""
        calls = []

        def fake(argv, *, log_path, worker_path):
            worker, remaining = studio_durable_driver.validate(argv, log_path, worker_path)
            calls.append(dict(argv=argv, log_path=str(log_path), worker_path=str(worker_path), remaining=remaining))
            return SimpleNamespace(pid=4242)
        return calls, patch('studio_durable_driver.launch', side_effect=fake)

    def worker(self, kind='seed', batch_id='batch'):
        return read_json(self.root / 'demo-agent/lane-workers' / (kind + '-' + batch_id + '.json'))

    def test_start_takes_its_checks_and_start_record_here_then_detaches(self):
        self.agent.seed_prepare('batch', self.plan)
        calls, launch = self.launched()
        with launch:
            result = self.agent.seed_start('batch', 600, detach=True)
        self.assertEqual((result['status'], result['native_running_unverified']), ('driver_starting', True))
        self.assertTrue((self.root / 'demo-agent/seed-starts/batch.json').is_file())        # written before the detach
        self.assertEqual((self.process.starts, self.process.closes), ([], []))              # MT5 untouched by the caller
        worker = self.worker()
        self.assertEqual((worker['status'], worker['pid'], worker['initial'], worker['max_seconds']), ('spawned', 4242, True, 600))
        self.assertEqual(calls[0]['argv'][4:], ['_drive-lane', '--kind', 'seed', '--batch-id', 'batch', '--nonce', worker['nonce'],
                                                '--max-seconds', '600', '--initial'])
        self.assertEqual(calls[0]['remaining'], 600)
        phases = [(a['operation'], a['phase']) for a in self.actions()]
        self.assertIn(('seed_start', 'start_recorded'), phases)
        self.assertEqual(phases[-2:], [('seed_driver', 'worker_reserved'), ('seed_driver', 'spawned')])
        # The demand task: the worker re-checks everything and drives exactly like the foreground command.
        self.auto = True
        driven = self.agent._drive_lane('seed', 'batch', worker['nonce'], 600, True)
        self.assertEqual(driven['status'], 'completed')
        self.assertEqual((self.process.closes, len(self.process.starts)), ([MONITOR], 2))
        self.assertEqual((self.worker()['status'], self.worker()['result_status']), ('returned', 'completed'))

    def test_refusals_stay_immediate_and_leave_nothing_behind(self):
        self.agent.seed_prepare('batch', self.plan)
        (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))
        calls, launch = self.launched()
        with launch, self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent.seed_start('batch', 60, detach=True)
        self.assertFalse((self.root / 'demo-agent/seed-starts/batch.json').exists())
        self.assertFalse((self.root / 'demo-agent/lane-workers').exists())
        self.assertEqual(calls, [])
        with launch, self.assertRaisesRegex(ValueError, 'no native effect yet; use seed-start'):
            self.agent.seed_resume('batch', 60, detach=True)
        self.assertEqual(calls, [])

    def test_one_detached_driver_owns_the_terminal(self):
        self.agent.seed_prepare('batch', self.plan)
        calls, launch = self.launched()
        with launch:
            self.agent.seed_start('batch', 60, detach=True)
        with patch.object(DemoAgent, '_worker_alive', return_value=True), launch:
            again = self.agent.seed_start('batch', 60, detach=True)
            self.assertEqual(again['status'], 'already_supervising')
            with self.assertRaisesRegex(ValueError, 'A live seed driver \\(batch\\) owns this terminal'):
                self.agent.seed_prepare('other', self.plan)
            status = self.agent.seed_status('batch')
            self.assertEqual((status['driver']['alive'], status['driver']['status']), (True, 'spawned'))
        self.assertEqual(len(calls), 1)                                                    # never a second driver

    def test_a_detached_resume_continues_the_original_attempt(self):
        self.agent.seed_prepare('batch', self.plan)
        self.agent.seed_start('batch', 6)                                                   # member 1 running
        calls, launch = self.launched()
        with launch:
            result = self.agent.seed_resume('batch', 300, detach=True)
        self.assertEqual(result['status'], 'driver_starting')
        worker = self.worker()
        self.assertEqual((worker['initial'], calls[0]['argv'][-1]), (False, '--resume'))
        self.assertEqual(len(self.process.starts), 1)                                       # the caller launched nothing
        self.auto = True
        self.finish_member(0)
        driven = self.agent._drive_lane('seed', 'batch', worker['nonce'], 300, False)
        self.assertEqual(driven['status'], 'completed')
        self.assertEqual(len(self.process.starts), 2)                                       # member 1 never retried

    def test_a_worker_that_refuses_records_why_and_a_changed_reservation_never_drives(self):
        self.agent.seed_prepare('batch', self.plan)
        calls, launch = self.launched()
        with launch:
            self.agent.seed_start('batch', 60, detach=True)
        nonce = self.worker()['nonce']
        with self.assertRaisesRegex(ValueError, 'identity, budget or launch state changed'):
            self.agent._drive_lane('seed', 'batch', 'f' * 32, 60, True)
        with self.assertRaisesRegex(ValueError, 'identity, budget or launch state changed'):
            self.agent._drive_lane('seed', 'batch', nonce, 61, True)
        (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))
        with self.assertRaisesRegex(ValueError, 'Owner STOP'):
            self.agent._drive_lane('seed', 'batch', nonce, 60, True)
        self.assertEqual(self.worker()['status'], 'failed')
        self.assertIn('Owner STOP', self.worker()['error'])
        self.assertEqual(self.process.closes, [])

    # ---- Codex review of GOAT-EA#162 -------------------------------------------------------------------
    def test_the_reservation_and_launch_hold_the_terminal_lock(self):
        # P1: the live check, the reservation and the launch are one locked operation, so overlapping calls serialize.
        self.agent.seed_prepare('batch', self.plan)
        seen = []

        def fake(argv, *, log_path, worker_path):
            seen.append(read_json(worker_path)['status'])
            with self.assertRaisesRegex(ValueError, 'Another demo agent operation owns this terminal'):
                with self.new_agent()._exclusive():
                    pass
            return SimpleNamespace(pid=4242)
        with patch('studio_durable_driver.launch', side_effect=fake):
            self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual(seen, ['reserved'])
        with self.new_agent()._exclusive():                                                  # released afterwards
            pass

    def test_an_unconfirmed_launch_keeps_its_envelope_and_blocks_a_second_driver(self):
        # P1: launch() already retained its envelope; the caller must not overwrite it with a stale record.
        self.agent.seed_prepare('batch', self.plan)

        def unconfirmed(argv, *, log_path, worker_path):
            envelope = Path(str(log_path)[:-4] + '.launch.json')
            write_json(envelope, dict(started=str(envelope.with_name('never.started.json')),
                                      finished=str(envelope.with_name('never.finished.json'))))
            write_json(worker_path, dict(read_json(worker_path), launch_envelope=str(envelope), launch_mechanism='windows_demand_task'))
            raise ValueError('Persistent bootstrap unconfirmed; inspect the same launch/task, never issue another')
        with patch('studio_durable_driver.launch', side_effect=unconfirmed):
            with self.assertRaisesRegex(ValueError, 'could not be confirmed .* never start another driver'):
                self.agent.seed_start('batch', 60, detach=True)
        worker = self.worker()
        self.assertEqual(worker['status'], 'launch_unconfirmed')
        self.assertTrue(worker['launch_envelope'].endswith('.launch.json'))
        calls, launch = self.launched()
        with launch, self.assertRaisesRegex(ValueError, 'launch unresolved'):
            self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual(calls, [])
        self.assertIn('unknown', str(self.agent.seed_status('batch')['driver']['alive']))

    def test_the_caller_never_regresses_the_workers_own_state(self):
        # P2: only a still-reserved record becomes 'spawned'.
        self.agent.seed_prepare('batch', self.plan)

        def raced(argv, *, log_path, worker_path):
            write_json(worker_path, dict(read_json(worker_path), status='supervising', pid=777))
            return SimpleNamespace(pid=4242)
        with patch('studio_durable_driver.launch', side_effect=raced):
            result = self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual((self.worker()['status'], self.worker()['pid'], result['worker']['status']), ('supervising', 777, 'supervising'))

    def test_a_failure_before_the_task_exists_points_back_to_start(self):
        # P2: the batch is still prepared, so the retry is start (it reuses the start record), never resume.
        self.agent.seed_prepare('batch', self.plan)
        with patch('studio_durable_driver.launch', side_effect=ValueError('The installed windowless Python runtime is missing')):
            with self.assertRaisesRegex(ValueError, 'run seed-start again \\(it reuses the start record\\)'):
                self.agent.seed_start('batch', 60, detach=True)
        self.assertEqual(self.worker()['status'], 'spawn_failed')
        calls, launch = self.launched()
        with launch:
            self.assertEqual(self.agent.seed_start('batch', 60, detach=True)['status'], 'driver_starting')
        self.assertIn(('seed_start', 'start_record_reused'), [(a['operation'], a['phase']) for a in self.actions()])

    def test_the_durable_host_accepts_only_the_exact_lane_reservation(self):
        path = self.root / 'demo-agent/lane-workers/seed-batch.json'
        path.parent.mkdir(parents=True)
        nonce = 'a' * 32
        write_json(path, dict(schema_version=1, kind='seed', batch_id='batch', nonce=nonce, status='reserved', initial=True, max_seconds=900))
        argv = ['python.exe', str(Path(demo_agent.__file__).resolve()), '--installation', str(self.installation), '_drive-lane',
                '--kind', 'seed', '--batch-id', 'batch', '--nonce', nonce, '--max-seconds', '900', '--initial']
        log = path.with_name('seed-batch-' + nonce + '.log')
        worker, remaining = studio_durable_driver.validate(argv, log, path)
        self.assertEqual((worker['batch_id'], remaining), ('batch', 900))
        for label, change in (('budget', lambda a: a.__setitem__(12, '901')), ('kind', lambda a: a.__setitem__(6, 'batch')),
                              ('mode', lambda a: a.__setitem__(13, '--resume')), ('nonce', lambda a: a.__setitem__(10, 'b' * 32)),
                              ('script', lambda a: a.__setitem__(1, str(self.root / 'demo_agent.py')))):
            with self.subTest(label):
                bad = list(argv); change(bad)
                with self.assertRaises(ValueError):
                    studio_durable_driver.validate(bad, log, path)
        with self.assertRaisesRegex(ValueError, 'not canonical'):
            studio_durable_driver.validate(argv, log, path.with_name('catchup-batch.json'))
        write_json(path, dict(read_json(path), status='spawned'))
        with self.assertRaisesRegex(ValueError, 'reserved lane driver'):
            studio_durable_driver.validate(argv, log, path)

    # ---- goatai#1885: a detached driver refused itself on its own started receipt -------------------------
    def test_a_detached_seed_driver_with_its_own_started_receipt_drives(self):
        # beta.23: lane-workers/*.json included <nonce>.started.json, whose pid and nonce are the running driver's own,
        # so every detached driver refused itself with "A live seed driver (None) owns this terminal".
        self.agent.seed_prepare('batch', self.plan)
        self.drive_detached('seed', 'batch', self.agent.seed_start, 600)
        self.assertEqual((self.process.closes, len(self.process.starts)), ([MONITOR], 2))

    def test_receipts_are_never_driver_records(self):
        # A catch-up driver that has finished while its bootstrap is still exiting: the record is done (finished
        # receipt), but its started receipt still names a live process carrying its nonce. Only records count.
        old = self.lane_record('catchup', 'old', pid=5150, finished=True)
        workers = self.root / 'demo-agent/workers'
        write_json(workers / 'g6.json', dict(batch_id='g6', nonce='e' * 32, status='returned'))
        for name in ('launch', 'started', 'finished'):
            write_json(workers / ('g6-' + 'e' * 32 + '.' + name + '.json'), dict(pid=5150, nonce='e' * 32))
        self.assertEqual([p.name for p in self.agent._worker_records()], ['g6.json'])
        self.assertEqual([p.name for p in self.agent._worker_records(lane=True)], ['catchup-old.json'])
        with self.processes({5150: self.bootstrap_command(old)}):
            self.assertIsNone(self.agent._live_lane_worker())
            self.assertEqual(self.agent.seed_prepare('batch', self.plan)['status'], 'prepared')

    def test_only_another_live_lane_driver_refuses(self):
        mine = self.lane_record('holdup', 'h1', pid=os.getpid())          # this process's own detached driver
        self.lane_record('seed', 'stale', pid=6006)                         # its process is gone
        table = {os.getpid(): self.bootstrap_command(mine)}
        with self.processes(table):
            self.assertIsNone(self.agent._live_lane_worker())                   # no exclude needed to recognise itself
            self.assertEqual(self.agent.seed_prepare('batch', self.plan)['status'], 'prepared')
        other = self.lane_record('catchup', 'cu2', pid=7007)                # a truly live driver on this terminal
        table[7007] = self.bootstrap_command(other)
        with self.processes(table):
            path, record = self.agent._live_lane_worker()
            self.assertEqual((Path(path).name, record['batch_id']), ('catchup-cu2.json', 'cu2'))
            with self.assertRaisesRegex(ValueError, 'A live catch-up driver \\(cu2\\) owns this terminal'):
                self.agent._seed_unoccupied('holdup', exclude=self.root / 'demo-agent/lane-workers/holdup-h1.json')
            with self.assertRaisesRegex(ValueError, 'A live catch-up driver \\(cu2\\) owns this terminal'):
                self.agent.seed_start('batch', 60, detach=True)

    def test_the_cli_detaches_by_default_and_caps_a_foreground_drive(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = demo_agent.main(['--installation', str(self.installation), 'seed-start', '--batch-id', 'batch',
                                    '--max-seconds', '600', '--foreground'])
        self.assertEqual(code, 1)
        self.assertIn('allows at most 120 s', json.loads(stderr.getvalue())['error'])
        args = SimpleNamespace(foreground=False, max_seconds=3600)
        self.assertTrue(demo_agent._lane_detached(args))
        self.assertFalse(demo_agent._lane_detached(SimpleNamespace(foreground=True, max_seconds=60)))


class DetachedCatchupTests(DurableReceipts, unittest.TestCase):
    """The Saturday catch-up path: a detached catch-up driver drives with its own started receipt live."""
    setUp = catchup_fixture.DemoCatchupAgentTests.setUp
    write_exports = catchup_fixture.DemoCatchupAgentTests.write_exports
    sleep = catchup_fixture.DemoCatchupAgentTests.sleep
    manifest = catchup_fixture.DemoCatchupAgentTests.manifest
    finish_member = catchup_fixture.DemoCatchupAgentTests.finish_member

    def test_a_detached_catchup_driver_never_refuses_itself(self):
        self.assertEqual(self.agent.catchup_prepare('cu1', self.plan)['status'], 'prepared')
        self.drive_detached('catchup', 'cu1', self.agent.catchup_start, 60)
        self.assertEqual(len(self.process.starts), 2)


class DetachedHoldupTests(DurableReceipts, unittest.TestCase):
    """The Prove step: a detached hold-up driver drives with its own started receipt live."""
    setUp = holdup_fixture.DemoHoldupAgentTests.setUp
    write_plan = holdup_fixture.DemoHoldupAgentTests.write_plan
    sleep = holdup_fixture.DemoHoldupAgentTests.sleep
    mt5_writes_report = holdup_fixture.DemoHoldupAgentTests.mt5_writes_report

    def test_a_detached_holdup_driver_never_refuses_itself(self):
        self.assertEqual(self.agent.holdup_prepare('h1', self.plan)['status'], 'prepared')
        self.drive_detached('holdup', 'h1', self.agent.holdup_start, 60)
        self.assertEqual(len(self.process.starts), 1)


if __name__ == '__main__':
    unittest.main()
