"""Detached seed, catch-up and hold-up drivers (goatai#1885 PR C, Claude-Mac answer 4).

seed-start/seed-resume used to drive in the caller's process, with MT5 as that process's child, so a
tool timeout that killed the caller killed MT5 mid-member (T2 seedhunt-t2-4-b41). They now hand the
drive to the run-batch demand-task host (studio_durable_driver). The real DemoAgent and SeedRunner run;
the Windows task launch is replaced by a fake that still passes the durable host's own validator.
"""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_agent
from demo_agent import DemoAgent, read_json, write_json
import studio_durable_driver
import test_demo_seed_agent as seed_fixture
from test_demo_seed_agent import MONITOR



class LaneDriverTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
