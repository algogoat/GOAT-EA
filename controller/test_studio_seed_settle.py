"""beta.17 T2 QA round 4: settle a seed member stranded by a stale "unknown executable" observation.

Replays r3-seed-121 exactly: the seed INI was launched, the inventory then refused a terminal64
row with no executable path, the member stayed reconcile_required with that error, MT5 ran the
member, wrote its XML and exited, and a person reopened MT5 on the idle monitor. Fixture-only.
"""
import copy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from demo_agent import DemoAgent
from studio_installation import read_json
from studio_research_status import headline, seed_progress
from studio_seed_process import UNKNOWN_EXECUTABLE, WindowsSeedProcess
from studio_seed_slot import guard_active_seed, refuse_prepare_while_seed_owns
# Fixture modules, not their TestCase classes: importing a class here would run its suite twice.
import test_demo_seed_agent as seed_agent_fixture
import test_studio_seed as seed_fixture

MONITOR = dict(pid=40260, executable='terminal64.exe', created_utc='2026-10-03T13:34:27.6440440Z')


class StrandedSeedTests(unittest.TestCase):
    """The customer-lane runner (goat.exe studio seed-*); the demo lane drives the same SeedRunner."""
    def setUp(self):
        seed_fixture.SeedTests.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        self.users = []                      # terminal64 processes naming a member INI right now
        self.line = '"terminal64.exe"'       # the reopened monitor: a person's normal open
        self.runtime_error = None
        self.process.command_line = lambda identity: self.line
        self.process.config_users = lambda names: list(self.users)
        def runtime(**kwargs):
            if self.runtime_error:
                raise ValueError(self.runtime_error)
            return {'loaded': True, 'owner': self.owner['owner'], 'generation': self.owner['generation']}, {}
        self.controller.runtime = runtime

    close, start, sleep, prepare, member, output = (seed_fixture.SeedTests.close, seed_fixture.SeedTests.start,
                                                    seed_fixture.SeedTests.sleep, seed_fixture.SeedTests.prepare,
                                                    seed_fixture.SeedTests.member, seed_fixture.SeedTests.output)

    def strand(self, *, output=True):
        self.prepare()
        real = self.start
        def start(config):
            real(config)
            raise ValueError(UNKNOWN_EXECUTABLE)
        self.process.start = start
        with self.assertRaisesRegex(ValueError, 'Unknown terminal executable'):
            self.runner.start('batch', 1)
        self.process.start = self.start
        if output:
            self.output(self.member())                 # MT5 ran the frozen INI and wrote its XML ...
        self.process_state = copy.deepcopy(MONITOR)    # ... exited, and a person reopened MT5 on the monitor

    def state(self):
        return read_json(self.runner.path('batch') / 'state.json')

    def test_status_and_report_reinspect_instead_of_replaying_the_old_refusal(self):
        self.strand()
        status = self.runner.status('batch')
        self.assertEqual(status['status'], 'reconcile_required')               # open MT5: only seed-reconcile settles
        self.assertEqual(status['last_inspection']['process'], MONITOR)       # the CURRENT inventory, recorded
        report = self.runner.report('batch')
        self.assertEqual(report['status'], 'reconcile_required')
        self.assertEqual(len(self.starts), 1)

    def test_seed_reconcile_collects_the_members_own_output_and_releases_the_terminal(self):
        self.strand()
        with self.assertRaisesRegex(ValueError, 'Seed runner owns this terminal'):
            guard_active_seed(self.controller.root)
        result = self.runner.reconcile('batch')
        self.assertTrue(result['settled'])
        self.assertEqual((result['status'], result['close_sent'], result['launch_sent']), ('completed', False, False))
        member = result['members'][0]
        self.assertEqual((member['status'], member['attempts']), ('completed', 1))
        self.assertEqual(member['reconciled']['prior_error'], UNKNOWN_EXECUTABLE)
        self.assertEqual(member['reconciled']['process'], MONITOR)
        self.assertNotIn('error', member)
        self.assertTrue(guard_active_seed(self.controller.root))              # terminal released
        self.assertEqual(self.runner.report('batch')['members'][0]['actual_frames'], 2)
        self.assertEqual((len(self.starts), len(self.closes)), (1, 1))         # never re-run, MT5 never closed again
        again = self.runner.status('batch')                                    # stays settled with MT5 open
        self.assertEqual(again['status'], 'completed')

    def unsettled(self, reason):
        result = self.runner.reconcile('batch')
        self.assertFalse(result['settled'])
        self.assertEqual(result['status'], 'reconcile_required')
        self.assertRegex(result['reasons'][0], reason)
        self.assertIsNone(self.state()['members'][0]['result'])
        self.assertFalse(Path(self.runner.path('batch') / (self.member()['alias'] + '.result.json')).exists())
        with self.assertRaises(ValueError):
            guard_active_seed(self.controller.root)

    def test_an_mt5_still_running_the_member_is_never_settled(self):
        self.strand()
        self.users = [dict(pid=777, executable='terminal64.exe')]
        self.unsettled('still running a member')

    def test_a_terminal_started_for_the_member_is_never_settled(self):
        self.strand()
        self.line = '"terminal64.exe" /config:"' + self.member()['config_path'] + '"'
        self.unsettled('started for a member')

    def test_a_tester_that_is_not_idle_is_never_settled(self):
        self.strand()
        self.runtime_error = 'Runtime policy mismatch: tester_state'
        self.unsettled('idle tester')

    def test_the_next_action_names_the_lanes_own_cancel(self):
        # goatai#2350 6092518750: a catch-up's reconcile said "seed-cancel settles the batch", and seed-cancel looks only in
        # seeds/ ("Unknown seed batch"). Each lane names its own cancel and reconcile: catchup-, holdup- or seed-.
        from studio_catchup import CatchupRunner
        from studio_holdup import HoldupRunner
        self.strand()
        self.runtime_error = 'Runtime policy mismatch: tester_state'
        self.assertIn('seed-cancel settles the batch', self.runner.reconcile('batch')['next_action'])
        for lane in (CatchupRunner, HoldupRunner):
            self.runner.COMMAND_PREFIX = lane.COMMAND_PREFIX
            text = self.runner.reconcile('batch')['next_action']
            self.assertIn(lane.COMMAND_PREFIX + '-cancel settles the batch', text)
            self.assertNotIn('seed-cancel', text)

    def test_a_process_tool_without_inventory_proof_is_never_settled(self):
        self.strand()
        del self.process.config_users
        self.unsettled('cannot prove')

    def test_customer_lane_adds_the_broker_process_check(self):
        self.strand()
        self.controller.session['authority_kind'] = 'native_human_control'
        with patch('studio_config_start.sdk_idle_demo', side_effect=ValueError('SDK-observed MT5 differs from the selected process')) as sdk:
            self.unsettled('broker check')
        self.assertEqual(sdk.call_args.args[1], MONITOR)
        with patch('studio_config_start.sdk_idle_demo', return_value=dict(process=MONITOR)):
            self.assertTrue(self.runner.reconcile('batch')['settled'])
    def test_output_that_fails_the_completion_checks_stays_with_its_reason(self):
        self.strand(output=False)
        self.output(self.member(), suffix='_N2_AvgFit=2.000_Health=50.00_Zero=1_AvgTrades=5.0_Best=4.000.xml')
        self.unsettled('did not pass the completion checks')
        self.assertFalse(self.state()['members'][0]['observed_xml']['accepted'])

    def test_no_output_is_never_synthesised(self):
        self.strand(output=False)
        self.unsettled('No output')

    def test_seed_cancel_settles_an_idle_terminal_with_no_output(self):
        self.strand(output=False)
        result = self.runner.cancel('batch')
        self.assertEqual((result['status'], result['settled'], result['close_sent']), ('stopped', 'idle_terminal', False))
        member = result['members'][0]
        self.assertEqual(member['status'], 'cancelled')
        self.assertEqual(member['reconciled']['prior_error'], UNKNOWN_EXECUTABLE)
        self.assertIsNone(member['result'])
        self.assertTrue(guard_active_seed(self.controller.root))
        self.assertEqual(len(self.closes), 1)

    def test_seed_cancel_keeps_a_members_verified_output(self):
        self.strand()
        result = self.runner.cancel('batch')
        self.assertEqual((result['status'], result['settled']), ('completed', 'reconciled_from_output'))
        self.assertTrue(guard_active_seed(self.controller.root))

    def test_seed_cancel_still_refuses_when_mt5_is_not_idle(self):
        self.strand(output=False)
        self.users = [dict(pid=777, executable='terminal64.exe')]
        with self.assertRaisesRegex(ValueError, 'Uncertain process provenance requires human inspection; no close sent'):
            self.runner.cancel('batch')
        self.assertEqual(self.state()['status'], 'reconcile_required')
        self.assertEqual(len(self.closes), 1)

    def test_closed_mt5_settles_on_status_as_before(self):
        self.strand()
        self.process_state = None
        self.assertEqual(self.runner.status('batch')['status'], 'completed')

    def test_prepare_batch_refuses_early_with_the_next_command(self):
        self.strand()
        with self.assertRaisesRegex(ValueError, 'Seed hunt batch still holds this terminal, so nothing was prepared; '
                                                'settle it first with seed-reconcile --batch-id batch'):
            refuse_prepare_while_seed_owns(self.controller.root)
        self.runner.reconcile('batch')
        refuse_prepare_while_seed_owns(self.controller.root)

    def test_pause_refusal_and_research_status_point_at_settle(self):
        self.strand()
        with self.assertRaisesRegex(ValueError, 'nothing to pause; settle it with seed-reconcile --batch-id batch'):
            self.runner.request_pause('batch', now=self.now)
        activity = seed_progress(self.controller.root, 'batch', now=self.now, kind='seed')
        self.assertTrue(activity['needs_settle'])
        self.assertEqual((activity['settle']['command'], activity['settle']['argument']), ('seed-reconcile', '--batch-id batch'))
        self.assertIn('needs settling', headline(activity))
        self.assertNotIn('Running', headline(activity))


class DemoLaneSettleTests(unittest.TestCase):
    """`goat.exe demo seed-reconcile`: the broker process check, then the same runner settle."""
    def setUp(self):
        seed_agent_fixture.DemoSeedAgentTests.setUp(self)
        self.process.command_line = lambda identity: '"terminal64.exe"'
        self.process.config_users = lambda names: []

    database, new_agent, sleep, manifest, finish_member, actions = (
        seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent,
        seed_agent_fixture.DemoSeedAgentTests.sleep, seed_agent_fixture.DemoSeedAgentTests.manifest,
        seed_agent_fixture.DemoSeedAgentTests.finish_member, seed_agent_fixture.DemoSeedAgentTests.actions)

    def test_r3_seed_121_replay_settles_and_frees_the_terminal_for_a_batch(self):
        self.agent.seed_prepare('batch', self.plan)
        real = self.process.start
        def start(config):
            real(config)
            raise ValueError(UNKNOWN_EXECUTABLE)
        self.process.start = start
        with self.assertRaisesRegex(ValueError, 'Unknown terminal executable'):
            self.agent.seed_start('batch', 30)
        self.finish_member(0)                                                   # MT5 wrote the XML and exited
        self.process.current = dict(pid=40260, executable='terminal64.exe', created_utc='reopened')
        status = self.agent.seed_status('batch')['seed']
        self.assertEqual(status['status'], 'reconcile_required')
        self.assertEqual(status['last_inspection']['process']['pid'], 40260)
        with self.assertRaisesRegex(ValueError, 'seed-reconcile --batch-id batch'):
            self.agent.prepare_batch('r4-a', self.plan)
        result = self.agent.seed_reconcile('batch')
        self.assertTrue(result['settled'])                                      # the uncertain member is settled
        self.assertEqual([m['status'] for m in result['members']], ['completed', 'pending'])
        self.assertIn('seed-cancel', result['next_action'])                     # MT5 open: pending members wait
        self.assertIn(('seed_reconcile', 'settled'), [(a['operation'], a['phase']) for a in self.actions()])
        stopped = self.agent.seed_cancel('batch')                               # idle MT5, nothing left to consume
        self.assertEqual([m['status'] for m in stopped['members']], ['completed', 'cancelled'])
        self.assertEqual(stopped['status'], 'stopped')
        self.assertTrue(guard_active_seed(self.root))                           # free for r4-a
        self.assertEqual(len(self.process.starts), 1)

    def test_single_member_replay_releases_the_slot(self):
        plan = json.loads(self.plan.read_text()); plan['jobs'] = plan['jobs'][:1]; self.plan.write_text(json.dumps(plan))
        self.agent.seed_prepare('batch', self.plan)
        real = self.process.start
        def start(config):
            real(config)
            raise ValueError(UNKNOWN_EXECUTABLE)
        self.process.start = start
        with self.assertRaises(ValueError):
            self.agent.seed_start('batch', 30)
        self.finish_member(0)
        self.process.current = dict(pid=40260, executable='terminal64.exe', created_utc='reopened')
        result = self.agent.seed_reconcile('batch')
        self.assertEqual((result['settled'], result['status']), (True, 'completed'))
        self.assertTrue(guard_active_seed(self.root))
        self.assertEqual(self.agent.seed_report('batch')['members'][0]['actual_frames'], 2)

    def test_broker_process_mismatch_settles_nothing(self):
        self.agent.seed_prepare('batch', self.plan)
        real = self.process.start
        def start(config):
            real(config)
            raise ValueError(UNKNOWN_EXECUTABLE)
        self.process.start = start
        with self.assertRaises(ValueError):
            self.agent.seed_start('batch', 30)
        self.finish_member(0)
        self.process.current = dict(pid=40260, executable='terminal64.exe', created_utc='reopened')
        calls = iter([dict(self.process.current), dict(self.process.current), dict(self.process.current, pid=1)])
        with patch.object(self.process, 'inspect', side_effect=lambda: next(calls, dict(self.process.current, pid=1))):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.agent.seed_reconcile('batch')
        self.assertEqual(read_json(self.root / 'seeds/batch/state.json')['status'], 'reconcile_required')


class ConfigUsersTests(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        self.process = WindowsSeedProcess(types.SimpleNamespace(install=dict(terminal_executable='x')),
                                          sleep=lambda s: self.clock.__setitem__(0, self.clock[0] + s),
                                          monotonic=lambda: self.clock[0])

    def test_lists_only_terminals_naming_a_member(self):
        rows = [dict(ProcessId=1, ExecutablePath='a', CommandLine='"a" /config:"C:\\d\\config\\GOATStudio\\Seeds\\Se4_00001.ini"'),
                dict(ProcessId=2, ExecutablePath='b', CommandLine='"b"')]
        with patch('studio_seed_process.subprocess.check_output', return_value=json.dumps(rows)):
            self.assertEqual(self.process.config_users(['se4_00001.ini']), [dict(pid=1, executable='a')])

    def test_unreadable_command_line_is_no_proof(self):
        with patch('studio_seed_process.subprocess.check_output', return_value=json.dumps([dict(ProcessId=1, ExecutablePath='a', CommandLine=None)])):
            with self.assertRaisesRegex(ValueError, 'command line cannot be read'):
                self.process.config_users(['x'])


if __name__ == '__main__':
    unittest.main()
