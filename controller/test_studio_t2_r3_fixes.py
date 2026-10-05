"""beta.17 T2 QA round 3 gaps: relaunch readback, transient process rows, seed reconcile/reopen, Stop latency.

Fixture-only: no MT5 terminal, broker or native run is touched.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from demo_agent import DemoAgent, digest, read_json
from studio_research_authority import READ_OPERATIONS, authority, operation
import studio_seed_process
from studio_seed_process import UNKNOWN_EXECUTABLE, WindowsSeedProcess
# Fixture modules, not their TestCase classes: importing a class here would run its suite twice.
import test_demo_agent as demo_fixture
import test_demo_seed_agent as seed_agent_fixture
import test_studio_batch_driver as driver_fixture
import test_studio_seed as seed_fixture


def iso(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%S.%f') + '0Z'


class RelaunchProcess:
    """The selected MT5: a process GOAT (or a person) started, with its command line."""
    def __init__(self, identity, line):
        self.identity, self.line, self.closed = identity, line, False

    def inspect(self):
        return None if self.closed else dict(self.identity)

    def command_line(self, identity):
        if identity != self.identity:
            raise ValueError('Selected terminal process changed before its command line was read')
        return self.line

    def close(self, identity):
        self.closed = True

    def start(self, config):
        self.closed = False
        return dict(self.identity)


class RelaunchReadbackTests(unittest.TestCase):
    """P1: after GOAT's own MT5 relaunch the next prepare/start re-reads the build by itself."""
    def setUp(self):
        demo_fixture.DemoAgentTests.setUp(self)
        now = datetime.now(timezone.utc)
        self.old = dict(pid=11716, executable=str(self.exe), created_utc=iso(now - timedelta(hours=1)))
        self.new = dict(pid=45732, executable=str(self.exe), created_utc=iso(now - timedelta(seconds=60)))
        startup = self.root / 'attempts' / ('a' * 64) / 'startup.ini'
        self.process = RelaunchProcess(self.new, '"' + str(self.exe) + '" /config:"' + str(startup) + '"')
        self.agent = DemoAgent(self.installation, process=self.process, mt5=self.mt5)
        self.agent._adopt_installed_binary(digest(self.binary), enter_demo_lane=True)
        self.verified_path = self.agent.state_root / 'verified-build.json'
        self.verified_path.write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=self.old)))
        self.ui.write_text(json.dumps(dict(owner='agent', run_id='session-one', loaded=True,
            runtime=dict(account_demo=True, account_login='3000082754', account_server='Darwinex-Demo',
                         program_path=str(self.binary)))))
        self.idle = patch('demo_agent.tester_state', return_value='idle'); self.idle.start(); self.addCleanup(self.idle.stop)

    def studio(self):
        opened = types.SimpleNamespace(store=types.SimpleNamespace(close=lambda: None))
        opened.open = lambda recovery=False: opened
        with patch('goat_studio.Controller', side_effect=lambda path: opened):
            with self.agent._studio('prepare-batch', idle=True, job_id='r3-happy-2') as (controller, broker):
                return broker

    def test_goat_config_relaunch_refreshes_readback_before_the_next_batch(self):
        preflight = self.agent.preflight()
        self.assertTrue(preflight['readback_refresh_on_start'])
        self.assertTrue(preflight['ready_for_batch'])
        broker = self.studio()
        self.assertEqual(broker['process'], self.new)
        verified = read_json(self.verified_path)
        self.assertEqual((verified['process'], verified['ea_sha256']), (self.new, digest(self.binary)))
        phases = [(row['operation'], row['phase']) for row in map(json.loads, (self.agent.state_root / 'actions.jsonl').read_text().splitlines())]
        self.assertIn(('readback_refresh', 'goat_relaunch'), phases)
        self.assertIn(('launch_terminal', 'verified'), phases)
        self.assertFalse(self.agent.preflight()['readback_refresh_on_start'])   # now current, nothing to refresh

    def test_ea_member_restart_and_seed_configs_also_qualify(self):
        self.process.line = '"' + str(self.exe) + '" /config:' + str(self.common / 'GOATStudio' / 'restart.ini')
        self.assertEqual(self.studio()['process'], self.new)                 # the EA's own member restart
        self.verified_path.write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=self.old)))
        self.process.line = '"' + str(self.exe) + '" /config:"' + str(self.data / 'config/GOATStudio/Seeds/S1_00001.ini') + '"'
        self.assertEqual(self.studio()['process'], self.new)                 # a seed / catch-up member

    def test_real_windows_command_line_with_quote_before_config_qualifies(self):
        # T2 round 4: Windows wrote `"...terminal64.exe" "/config:C:\path with spaces\startup.ini`
        # (a quote before /config, spaces in the path, no closing quote) and the old pattern missed it.
        spaced = self.root / 'attempts with space' / ('b' * 64) / 'startup.ini'
        for line in ('"' + str(self.exe) + '" "/config:' + str(spaced),
                     '"' + str(self.exe) + '" "/config:' + str(spaced) + '"'):
            self.verified_path.write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=self.old)))
            self.process.line = line
            self.assertEqual(self.studio()['process'], self.new)

    def test_quoted_config_outside_goat_folders_still_refuses(self):
        self.process.line = '"' + str(self.exe) + '" "/config:' + str(self.base / 'else where' / 'start.ini') + '"'
        self.refuses()

    def refuses(self):
        before = self.verified_path.read_bytes()
        self.assertFalse(self.agent.preflight()['ready_for_batch'])
        with self.assertRaisesRegex(ValueError, 'lacks native readback for this terminal process'):
            self.studio()
        self.assertEqual(self.verified_path.read_bytes(), before)

    def test_human_reopen_without_goat_config_is_never_refreshed_silently(self):
        self.process.line = '"' + str(self.exe) + '"'
        self.refuses()

    def test_config_outside_goat_folders_refuses(self):
        self.process.line = '"' + str(self.exe) + '" /config:"' + str(self.base / 'elsewhere' / 'start.ini') + '"'
        self.refuses()

    def test_changed_build_bytes_or_older_process_refuse(self):
        self.verified_path.write_text(json.dumps(dict(ea_sha256='0' * 64, process=self.old)))
        self.refuses()
        self.verified_path.write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=dict(
            self.old, created_utc=iso(datetime.now(timezone.utc) + timedelta(hours=1))))))
        self.refuses()

    def test_other_executable_refuses(self):
        self.verified_path.write_text(json.dumps(dict(ea_sha256=digest(self.binary), process=dict(
            self.old, executable=str(self.base / 'other' / 'terminal64.exe')))))
        self.refuses()

    def test_process_without_command_line_reader_refuses(self):
        class NoReader(RelaunchProcess):
            command_line = None
        self.agent.process = NoReader(self.new, self.process.line)
        self.refuses()


class SeedProcessInventoryTests(unittest.TestCase):
    """P1: a terminal64 row with no executable path for a moment is re-read, never assumed."""
    def setUp(self):
        self.exe = r'G:\MetaTrader5 Data\Terminals\Terminal 2 - GOAT\terminal64.exe'
        self.clock = [0.0]
        controller = types.SimpleNamespace(install=dict(terminal_executable=self.exe))
        self.process = WindowsSeedProcess(controller, sleep=self.sleep, monotonic=lambda: self.clock[0])
        self.process.image_path = lambda row: None          # the process-API fill (PR D) is tested on its own
        self.row = dict(ProcessId=23164, ExecutablePath=self.exe, CreatedUtc='2026-10-03T13:23:56.1234560Z')

    def sleep(self, seconds):
        self.clock[0] += seconds

    def test_transient_missing_path_is_reread(self):
        banker = dict(ProcessId=9001, ExecutablePath=None, CreatedUtc='2026-10-03T13:22:30.0000000Z')
        reads = iter([[self.row, banker], [self.row, banker], [self.row, dict(banker, ExecutablePath=r'C:\Banker\terminal64.exe')]])
        with patch.object(WindowsSeedProcess, '_rows', side_effect=lambda timeout, budget=None: next(reads)):
            found = self.process.inspect()
        self.assertEqual(found, dict(pid=23164, executable=self.exe, created_utc=self.row['CreatedUtc']))
        self.assertEqual(self.clock[0], 2 * studio_seed_process.UNKNOWN_RETRY_SECONDS)

    def test_persistent_missing_path_still_refuses_after_the_bounded_window(self):
        unknown = dict(ProcessId=9001, ExecutablePath='', CreatedUtc='x')
        with patch.object(WindowsSeedProcess, '_rows', return_value=[unknown]):
            with self.assertRaisesRegex(ValueError, UNKNOWN_EXECUTABLE):
                self.process.inspect()
        self.assertGreaterEqual(self.clock[0], studio_seed_process.UNKNOWN_SETTLE_SECONDS)

    def test_command_line_is_bound_to_the_exact_process(self):
        identity = dict(pid=23164, executable=self.exe, created_utc=self.row['CreatedUtc'])
        row = dict(self.row, CommandLine='"' + self.exe + '" /config:"C:\\state\\attempts\\x\\startup.ini"')
        with patch('studio_seed_process.subprocess.check_output', return_value=json.dumps([row])):
            self.assertIn('/config:', self.process.command_line(identity))
        with patch('studio_seed_process.subprocess.check_output', return_value=json.dumps([dict(row, CreatedUtc='other')])):
            with self.assertRaisesRegex(ValueError, 'changed before its command line'):
                self.process.command_line(identity)


class SeedReconcileTests(unittest.TestCase):
    """P1: a member MT5 finished while its start was unconfirmed is collected, not stranded."""
    def setUp(self):
        seed_fixture.SeedTests.setUp(self)
        self.addCleanup(self.tmp.cleanup)

    close, start, sleep, prepare, member, output = (seed_fixture.SeedTests.close, seed_fixture.SeedTests.start, seed_fixture.SeedTests.sleep,
                                                    seed_fixture.SeedTests.prepare, seed_fixture.SeedTests.member, seed_fixture.SeedTests.output)

    def strand(self):
        """The QA sequence: the seed INI was launched, then the inventory refused a row with no path."""
        self.prepare()
        real = self.start
        def start(config):
            real(config)
            raise ValueError(UNKNOWN_EXECUTABLE)
        self.process.start = start
        with self.assertRaisesRegex(ValueError, 'Unknown terminal executable'):
            self.runner.start('batch', 1)
        state = self.runner.status('batch')
        self.assertEqual((state['status'], state['members'][0]['status']), ('reconcile_required', 'reconcile_required'))

    def test_finished_member_output_is_collected_after_mt5_exits(self):
        self.strand()
        self.output(self.member()); self.process_state = None          # MT5 ran the INI and shut down
        state = self.runner.status('batch')
        self.assertEqual(state['status'], 'completed')
        member = state['members'][0]
        self.assertEqual((member['status'], member['attempts']), ('completed', 1))
        self.assertEqual(member['reconciled']['prior_error'], UNKNOWN_EXECUTABLE)
        self.assertNotIn('error', member)
        report = self.runner.report('batch')
        self.assertEqual(report['members'][0]['actual_frames'], 2)
        self.assertEqual(len(self.starts), 1)                          # never re-run

    def test_resume_reconciles_then_continues_pending_members_without_retry(self):
        second = dict(self.plan['jobs'][0], tester=dict(self.plan['jobs'][0]['tester'], Symbol='GBPUSD'))
        self.plan['jobs'].append(second)
        self.strand()
        self.output(self.member()); self.process_state = None
        self.process.start = self.start; self.auto = True
        state = self.runner.resume('batch', 10)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual([m['attempts'] for m in state['members']], [1, 1])
        self.assertEqual(len(self.starts), 2)

    def test_no_output_or_running_terminal_stays_reconcile_required(self):
        self.strand()
        self.assertEqual(self.runner.status('batch')['status'], 'reconcile_required')   # MT5 still running
        self.process_state = None
        self.assertEqual(self.runner.status('batch')['status'], 'reconcile_required')   # closed, nothing written
        self.assertEqual(len(self.starts), 1)

    def test_batch_level_doubt_is_never_reconciled_away(self):
        self.strand()
        state = read_json(self.runner.path('batch') / 'state.json')
        state['error'] = 'Unowned selected-terminal process appeared between seed members'
        (self.runner.path('batch') / 'state.json').write_text(json.dumps(state))
        self.output(self.member()); self.process_state = None
        state = self.runner.status('batch')
        self.assertEqual(state['status'], 'reconcile_required')                         # state-level doubt stays
        self.assertEqual(state['members'][0]['status'], 'reconcile_required')            # nothing collected under that doubt


class DemoSeedReopenTests(unittest.TestCase):
    """P2: after the last seed member the demo lane reopens MT5 on the GOAT Studio profile itself."""
    def setUp(self):
        seed_agent_fixture.DemoSeedAgentTests.setUp(self)
        (self.root / 'monitor-profile.json').write_text(json.dumps(dict(profile_name='GOAT-Studio-test')))
        preset = self.data / 'MQL5/Presets/GOAT Studio Agent.set'; preset.parent.mkdir(parents=True)
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))
        (self.ui.parent / 'active.json').write_text(json.dumps(dict(directory_id='session-one', terminal_id='terminal-one',
            run_id='session-one', terminal_data_path=str(self.data))))

    database, new_agent, sleep, manifest, finish_member, actions = (
        seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent, seed_agent_fixture.DemoSeedAgentTests.sleep,
        seed_agent_fixture.DemoSeedAgentTests.manifest, seed_agent_fixture.DemoSeedAgentTests.finish_member, seed_agent_fixture.DemoSeedAgentTests.actions)

    def test_completed_seed_reopens_the_monitor_profile_and_reads_back(self):
        self.agent.seed_prepare('batch', self.plan)
        self.auto = True
        with patch.object(DemoAgent, '_readback_current', return_value=dict(terminal=dict(pid=7))) as readback:
            result = self.agent.seed_start('batch', 60)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['monitor_reopen'], dict(status='verified', process=dict(pid=7)))
        self.assertEqual(len(self.process.starts), 3)
        config = Path(self.process.starts[-1])
        self.assertEqual(config.parent, self.root / 'demo-agent/monitor-restarts')
        text = config.read_bytes().decode('utf-16')
        self.assertIn('ProfileLast=GOAT-Studio-test', text)
        self.assertIn('Enabled=0\r\nAllowLiveTrading=0\r\n', text)
        self.assertNotIn('AllowDllImport', text); self.assertNotIn('[Tester]', text)
        self.assertEqual(readback.call_count, 1)
        self.assertIn(('seed_reopen', 'verified'), [(a['operation'], a['phase']) for a in self.actions()])

    def test_owner_stop_never_reopens(self):
        self.agent.seed_prepare('batch', self.plan)
        self.agent.seed_start('batch', 6)
        (self.root / 'demo-agent/STOP').write_text(json.dumps(dict(actor='demo_agent')))
        self.process.current = None
        result = self.agent.seed_resume('batch', 6)
        self.assertNotIn('monitor_reopen', result)
        self.assertEqual(len(self.process.starts), 1)


class MonitorConfigTests(unittest.TestCase):
    """P2: `demo launch-terminal` works from the saved profile or the retained DLL restart INI."""
    def setUp(self):
        demo_fixture.DemoAgentTests.setUp(self)
        preset = self.data / 'MQL5/Presets/GOAT Studio Agent.set'; preset.parent.mkdir(parents=True)
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))

    def test_default_is_the_saved_profile_monitor_ini(self):
        config = self.agent._validate_monitor_config()
        self.assertEqual(config, self.agent._validate_monitor_config(None))           # content-addressed, reused
        self.assertTrue(config.name.startswith('monitor-'))
        self.assertIn('ProfileLast=GOAT-Studio-test', config.read_bytes().decode('utf-16'))

    def test_retained_dll_granted_ini_launches_its_monitor_only_base(self):
        base = self.agent._validate_monitor_config()
        granted = self.agent._dll_granted_restart_config(base, dict(dlls_allowed=True))
        self.assertIn('AllowDllImport=1', granted.read_bytes().decode('utf-16'))
        self.assertEqual(self.agent._validate_monitor_config(granted), base)           # the grant is never re-asserted

    def test_changed_dll_granted_ini_refuses(self):
        granted = self.agent._dll_granted_restart_config(self.agent._validate_monitor_config(), dict(dlls_allowed=True))
        granted.write_bytes(granted.read_bytes() + 'Extra=1\r\n'.encode('utf-16-le'))
        with self.assertRaisesRegex(ValueError, 'Retained DLL restart configuration changed'):
            self.agent._validate_monitor_config(granted)

    def test_launch_terminal_without_a_path_reopens_on_the_profile(self):
        self.agent._adopt_installed_binary(digest(self.binary), enter_demo_lane=True)
        self.process.closed = True
        starts = []
        self.process.on_start = lambda: starts.append(True)
        with patch.object(DemoAgent, '_owner_clear'), patch.object(DemoAgent, '_readback_current',
                return_value=dict(terminal=self.process.identity)) as readback:
            self.agent.launch_terminal()
        self.assertEqual(len(starts), 1)
        self.assertEqual(readback.call_args.kwargs['expected_process'], self.process.identity)

    def test_running_terminal_launch_terminal_is_the_readback_refresh(self):
        self.agent._adopt_installed_binary(digest(self.binary), enter_demo_lane=True)
        with patch.object(DemoAgent, '_readback_current', return_value=dict(terminal=self.process.identity)) as readback:
            result = self.agent.launch_terminal()
        self.assertTrue(result['already_running'])
        self.assertEqual(readback.call_count, 1)


class StopLatencyTests(unittest.TestCase):
    """P2: verified Stop no longer waits out two 30 s driver polls (r3-speed-2: 33.3 s / 37.8 s)."""
    def setUp(self):
        driver_fixture.BatchDriverTests.setUp(self)

    def run_driver(self):
        from studio_batch_driver import run
        return run(self.c, 'batch', poll_seconds=30, cancel_grace_seconds=120, clock=self.c.clock,
                   finish_fn=self.c.finish, max_seconds=3600)

    def test_owner_stop_is_seen_and_settled_within_seconds(self):
        self.c.session['authority_kind'] = 'demo_direct'
        driver_fixture.write_json(self.c.root / 'session.json', self.c.session)
        self.c.bridge = types.SimpleNamespace(root=self.c.local / self.c.run)
        self.c.finish_on_cancel = False
        marker = self.c.root / 'demo-agent/STOP'
        def tick():
            if self.c.clock.mono >= 10 and not marker.exists():
                marker.parent.mkdir(exist_ok=True); marker.write_text('owner stop')
                self.stop_at = self.c.clock.mono
            if self.c.cancels and self.c.clock.mono >= self.cancel_at + 1.5:
                self.c.finished = True                                   # the EA settles ~1.4 s after the cancel
        original_cancel = self.c.cancel
        def cancel(job_id, *, expected_generation):
            self.cancel_at = self.c.clock.mono
            return original_cancel(job_id, expected_generation=expected_generation)
        self.c.cancel = cancel
        self.c.clock.on_sleep = tick
        result = self.run_driver()
        self.assertEqual((result['status'], result['cancel_reason']), ('cancelled', 'owner_stop'))
        self.assertLessEqual(self.cancel_at - self.stop_at, .5)            # was up to 30 s
        self.assertLessEqual(self.c.clock.mono - self.stop_at, 4)           # was 33-38 s
        self.assertEqual((self.c.starts, self.c.cancels), (1, 1))

    def test_cancel_published_by_batch_stop_wakes_the_customer_driver(self):
        gate = self.c.local / 'native-gate'; gate.mkdir()
        def tick():
            if self.c.clock.mono >= 10 and not (gate / 'request.json').exists():
                (gate / 'request.json').write_text(json.dumps(dict(action='cancel', attempt_id='a' * 64,
                                                                   expires_utc=self.c.clock.wall + 120)))
                self.published_at = self.c.clock.mono
                self.c.finished = True
        self.c.clock.on_sleep = tick
        result = self.run_driver()
        self.assertEqual(result['status'], 'cancelled' if self.c.cancels else 'completed')
        self.assertEqual(self.c.cancels, 0)                                  # the driver never cancels on its own
        self.assertLessEqual(self.c.clock.mono - self.published_at, .5)

    def test_quiet_batch_keeps_its_normal_poll(self):
        passes = []
        self.c.reconcile = lambda job_id: passes.append(self.c.clock.mono) or {'status': 'running'}
        def tick():
            if self.c.clock.mono >= 95:
                self.c.finished = True
        self.c.clock.on_sleep = tick
        self.run_driver()
        self.assertEqual(passes[:4], [0.0, 30.0, 60.0, 90.0])               # no extra passes without a stop


class ReadOnlyOnDemoLaneTests(unittest.TestCase):
    """P3: read-only studio commands run on demo_direct; mutations still refuse."""
    def setUp(self):
        seed_agent_fixture.DemoSeedAgentTests.setUp(self)

    database, new_agent, sleep = (seed_agent_fixture.DemoSeedAgentTests.database, seed_agent_fixture.DemoSeedAgentTests.new_agent,
                                  seed_agent_fixture.DemoSeedAgentTests.sleep)

    def test_validate_set_and_benchmark_report_are_reads(self):
        self.assertTrue({'validate-set', 'benchmark-report'} <= READ_OPERATIONS)
        with self.database() as db:
            for name in ('validate-set', 'benchmark-report'):
                with operation(name):
                    self.assertIsNone(authority(db, self.binding, dict(owner='agent', generation=1)))
            for name in ('prepare-batch', 'run-batch'):     # build-set is a local file write since goatai#1885 (test_studio_starter_set)
                with operation(name), self.assertRaisesRegex(ValueError, 'Demo mutation requires the broker-verified agent tool'):
                    authority(db, self.binding, dict(owner='agent', generation=1))

    def test_validate_set_cli_runs_on_a_demo_direct_installation(self):
        from goat_studio import main
        from io import StringIO
        from contextlib import redirect_stdout
        self.patches[-1].stop()                                             # the real Controller for the CLI
        output = StringIO()
        with patch('studio_template_tools.validate_set', return_value=dict(valid=True)) as validate, redirect_stdout(output):
            code = main(['--installation', str(self.installation), 'validate-set', '--set', str(self.source)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['result'], dict(valid=True))
        self.assertEqual(validate.call_count, 1)


if __name__ == '__main__':
    unittest.main()
