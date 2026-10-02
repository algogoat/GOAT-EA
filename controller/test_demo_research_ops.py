"""Broker-verified demo lane: research-status, batch-pause and batch-resume entry points.

Native pause rules are covered by test_studio_batch_pause; these fixtures check
the demo tool never takes the terminal lock to request a pause, starts exactly
one bounded supervisor when none is alive, and refuses resume in plain words.
"""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from studio_bridge import write_json
import studio_batch_pause as pause
from studio_durable_driver import validate
import test_demo_agent as demo_fixtures
import test_studio_seed as seed_fixtures

ATTEMPT = 'a' * 64


class DemoResearchOpsTests(unittest.TestCase):
    def setUp(self):
        self.f = demo_fixtures.DemoAgentTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.agent = self.f.agent
        self.job = dict(job_id='g6', status='running', configuration_sha256='c' * 64,
                        configuration=dict(batch_members=[{}, {}]), launch_intent=dict(attempt_id=ATTEMPT))
        journal = self.agent.root / 'batch-drivers' / 'g6.json'
        journal.parent.mkdir(parents=True)
        write_json(journal, dict(schema_version=2, attempt_id=ATTEMPT, binding=dict(job_id='g6', generation=4),
                                 cancel_issued=True, stopped=False, status='stop_unconfirmed', max_seconds=172800,
                                 cancel_reason='owner_stop'))
        self.jobs = patch.object(type(self.agent), '_jobs_readonly', lambda agent: [copy.deepcopy(self.job)]); self.jobs.start()
        self.addCleanup(self.jobs.stop)

    def actions(self, operation):
        path = self.agent.state_root / 'actions.jsonl'
        return [row for row in map(json.loads, path.read_text().splitlines()) if row['operation'] == operation] if path.is_file() else []

    def test_pause_without_live_driver_adopts_the_stop_and_starts_one_supervisor(self):
        with patch.object(self.agent, '_spawn_driver', return_value=dict(status='driver_journal_recorded')) as spawn, \
                patch.object(self.agent, '_exclusive', side_effect=AssertionError('pause request took the terminal lock')):
            result = self.agent.batch_pause('g6')
            again = self.agent.batch_pause('g6')
        spawn.assert_called_with('g6', resume=True, pause_seconds=self.agent.PAUSE_SUPERVISION_SECONDS)
        self.assertEqual((result['state'], result['adopted_stop'], result['supervisor']['supervising']), ('pausing', True, True))
        self.assertEqual(result['pause_id'], again['pause_id'])
        self.assertEqual(len(self.actions('batch_pause')), 1)
        self.assertIn('Waiting for a safe point', result['plain'])

    def test_live_driver_keeps_supervising_and_no_second_supervisor_starts(self):
        worker = self.agent.state_root / 'workers' / 'g6.json'
        worker.parent.mkdir(parents=True)
        write_json(worker, dict(batch_id='g6', nonce='n' * 32, pid=5))
        with patch.object(self.agent, '_worker_alive', return_value=True), \
                patch.object(self.agent, '_spawn_driver', side_effect=AssertionError('duplicate supervisor')):
            result = self.agent.batch_pause('g6', immediate=True)
        self.assertEqual((result['supervisor']['status'], result['mode']), ('driver_supervising', 'immediate'))

    def test_closed_terminal_names_the_supervisor_blocker_instead_of_waiting_silently(self):
        with patch.object(self.agent, '_spawn_driver', side_effect=ValueError('Selected MT5 is not running; broker demo mode cannot be proven')):
            result = self.agent.batch_pause('g6')
        self.assertEqual((result['state'], result['supervisor']['supervising']), ('pausing', False))
        self.assertIn('Open this MT5 terminal', result['supervisor']['fix'])

    def test_unknown_finished_or_unjournalled_batches_refuse_plainly(self):
        with self.assertRaisesRegex(pause.PauseRefused, 'Unknown batch other'):
            self.agent.batch_pause('other')
        self.job['status'] = 'completed'
        with self.assertRaisesRegex(pause.PauseRefused, 'nothing to pause'):
            self.agent.batch_pause('g6')
        self.job['status'] = 'running'
        (self.agent.root / 'batch-drivers' / 'g6.json').unlink()
        with self.assertRaisesRegex(pause.PauseRefused, 'no bounded GOAT driver journal'):
            self.agent.batch_pause('g6')

    def test_resume_refuses_in_plain_words_before_any_terminal_effect(self):
        with patch.object(self.agent, '_exclusive', side_effect=AssertionError('resume reached the terminal')):
            with self.assertRaisesRegex(pause.PauseRefused, 'pause it first'):
                self.agent.batch_resume('g6')
            with patch.object(self.agent, '_spawn_driver', return_value=dict(status='driver_journal_recorded')):
                self.agent.batch_pause('g6')
            with self.assertRaisesRegex(pause.PauseRefused, 'still pausing'):
                self.agent.batch_resume('g6')
            record = pause.load(self.agent.root, 'g6')
            record.update(state='paused', phase='paused', resume_token='t' * 64)
            write_json(pause.path(self.agent.root, 'g6'), record)
            # Banker tonight: the monitor is signed out, so resume names the re-pair step.
            ui = self.agent.local / 'ui-observation.json'
            os.utime(ui, (1, 1))
            token = Path(self.agent.install['terminal_data_root']).name
            status = Path(self.agent.install['common_files_root']) / 'GOAT'; status.mkdir(exist_ok=True)
            (status / ('activation-status-' + token + '.json')).write_text(json.dumps(dict(reason='awaiting_approval', observedAtUtc=2)))
            with self.assertRaisesRegex(pause.PauseRefused, 're-pair it'):
                self.agent.batch_resume('g6')
            (status / ('activation-status-' + token + '.json')).unlink()
            write_json(ui, json.loads(ui.read_text()) | dict(bound=True, loaded=True))
            (self.agent.state_root / 'STOP').write_text(json.dumps(dict(actor='demo_agent')))
            with self.assertRaisesRegex(pause.PauseRefused, 'Owner STOP is on'):
                self.agent.batch_resume('g6')

    def test_research_status_is_read_only_and_reports_the_driverless_batch(self):
        with patch.object(self.agent, '_worker_alive', side_effect=AssertionError('no worker file, nothing to inspect')):
            value = self.agent.research_status()
        self.assertEqual(value['activity']['batch_id'], 'g6')
        self.assertEqual(value['account']['login'], '3000082754')
        self.assertTrue(value['read_only'])

    def test_pause_supervisor_task_budget_is_its_own_and_exact(self):
        root = self.agent.root / 'demo-agent' / 'workers'; root.mkdir(parents=True, exist_ok=True)
        nonce = 'b' * 32; worker = root / 'g6.json'
        write_json(worker, dict(status='reserved', batch_id='g6', nonce=nonce, resume=True, max_seconds=None, pause_seconds=21600))
        argv = ['python.exe', str(Path(demo_fixtures.__file__).with_name('demo_agent.py')), '--installation',
                str(self.agent.installation_path), '_drive-batch', '--batch-id', 'g6', '--nonce', nonce]
        log = root / ('g6-' + nonce + '.log')
        _, remaining = validate(argv + ['--pause-seconds', '21600'], log, worker)
        self.assertEqual(remaining, 21600)
        with self.assertRaisesRegex(ValueError, 'Pause supervision budget changed'):
            validate(argv + ['--pause-seconds', '99999'], log, worker)
        with self.assertRaisesRegex(ValueError, 'Pause supervision budget changed'):
            validate(argv, log, worker)


class StudioCliContractTests(unittest.TestCase):
    def setUp(self):
        import test_seed_cli
        self.f = test_seed_cli.SeedCliTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)

    def test_discovery_exposes_pause_resume_and_status_with_effects(self):
        code, result = self.f.cli('discover')
        contracts = result['result']['operation_contracts']
        for operation in ('batch-pause', 'batch-resume', 'research-status'):
            self.assertIn(operation, result['result']['operations'])
            self.assertIn(operation, contracts)
        self.assertIn('CANCEL_REJECTED', contracts['batch-pause']['effect'])
        self.assertIn('never records cancel_issued', contracts['batch-pause']['effect'])
        self.assertIn('goat.exe demo batch-pause', contracts['batch-pause']['demo_lane'])
        self.assertIn('lineage', contracts['batch-resume']['effect'])
        self.assertIn('read-only', contracts['research-status']['effect'])

    def test_cli_research_status_is_read_only(self):
        state = Path(self.f.fixture.receipt['controller_state_root'])
        before = sorted((str(p), p.stat().st_mtime_ns) for p in state.rglob('*') if p.is_file())
        code, result = self.f.cli('research-status')
        self.assertEqual(code, 0)
        self.assertEqual(result['result']['activity']['kind'], 'idle')
        self.assertEqual(result['result']['monitor']['blocker']['code'], 'terminal_closed')
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in state.rglob('*') if p.is_file()), before)


class SeedPauseTests(unittest.TestCase):
    def setUp(self):
        self.f = seed_fixtures.SeedTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        second = copy.deepcopy(self.f.plan['jobs'][0]); second['tester']['Symbol'] = 'GBPUSD'
        self.f.plan['jobs'].append(second)

    def test_pause_finishes_the_running_member_keeps_pending_and_resume_continues(self):
        runner = self.f.runner
        self.f.prepare(); self.f.auto = True
        original = self.f.sleep
        def pause_after_first_start(seconds):
            if len(self.f.starts) == 1 and not runner.paused('batch'):
                runner.request_pause('batch', now=self.f.now)
            original(seconds)
        self.f.runner.sleep = pause_after_first_start
        state = runner.start('batch', 30)
        self.assertTrue(state['paused'])
        self.assertEqual(len(self.f.starts), 1)
        members = runner.status('batch')['members']
        self.assertEqual([m['status'] for m in members], ['completed', 'pending'])
        self.assertTrue(runner.status('batch')['pause_requested'])
        # A plain seed-resume never undoes the pause.
        self.assertTrue(runner.resume('batch', 5)['paused'])
        self.assertEqual(len(self.f.starts), 1)
        self.assertTrue(runner.release_pause('batch', now=self.f.now))
        self.assertFalse(runner.release_pause('batch', now=self.f.now))
        self.assertTrue(list(runner.path('batch').glob('pause-released-*.json')))
        state = runner.resume('batch', 30)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(self.f.starts), 2)

    def test_only_a_running_seed_hunt_can_be_paused(self):
        self.f.prepare()
        with self.assertRaisesRegex(ValueError, 'not running'):
            self.f.runner.request_pause('batch', now=self.f.now)


if __name__ == '__main__':
    unittest.main()
