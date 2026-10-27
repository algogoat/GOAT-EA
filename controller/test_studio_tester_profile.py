"""The terminal's MT5 tester profile holds the run's own pinned inputs before every controller launch (F-01, 2026-10-20).

Banker's hold-up f01-starter-delay-20261020: the config's [TesterInputs] pinned ``Sequence_Export_Id=`` (empty), but MT5
does not apply an empty value from [TesterInputs] and kept ``export-1792494888-574031589-4`` from MQL5\\Profiles\\Tester\\
GOAT V1.49.set, the previous exporting batch's id; studio_tester_report.check() then refused both members. Claude-Mac
(goatai#2587 6298549893, ruling 1): before every tester launch the controller writes that profile with the same pinned
values, empty strings included, and never invents one.

Each fixture terminal here starts with a stale profile. ``mt5_runs`` models the observed MT5 behaviour: each
[TesterInputs] line sets its input, except an empty value, which leaves the profile's last-used value in place. The
hold-up, catch-up, seed and native (config start) launch paths run for real; only the MT5 process is a fixture.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_config_start
import studio_tester_profile as tp
import studio_tester_report as tr
from studio_installation import read_json
from studio_strategy_settings import read_values

REAL_NATIVE_PROFILE = getattr(studio_config_start, '_tester_profile', None)
STALE_ID = 'export-stale-1'


def stale_profile(path, **values):
    """A tester profile MT5 left behind after an exporting batch (UTF-16LE, BOM, CRLF), plus ``values``."""
    lines = dict({'Sequence_Export_Enabled': 'false', 'Sequence_Export_Id': STALE_ID, 'Studio_MonitorRunPath': 'C:\\stale\\run',
                  'GOAT_FitnessRunNonce': '88123||1||1||99999||Y'}, **values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\xff\xfe' + ''.join('%s=%s\r\n' % kv for kv in lines.items()).encode('utf-16-le'))
    return path


def mt5_runs(profile, config):
    """What MT5 runs for a /config launch (Banker, 2026-10-20): the profile's last-used values, then each [TesterInputs]
    value over it, except an empty value, which MT5 does not apply. Values as MT5's report prints them (no tuple tail)."""
    ran = {name: value.split('||')[0] for name, value in (read_values(profile) if profile else {}).items()}
    for name, value in tp.tester_inputs(config):
        if value == '':
            ran.setdefault(name, '')            # kept: the last-used value, or the EA default when the profile has none
            continue
        ran[name] = value if '||' not in value else value.split('||')[0]
    return ran


def profile_lines(raw):
    return raw[2:].decode('utf-16-le').split('\r\n')[:-1]


class Recorder:
    """Wraps a fixture's MT5 start: records the profile and config bytes MT5 would read at that moment."""

    def __init__(self, start):
        self.path, self.start, self.launches = None, start, []

    def __call__(self, config):
        profile = self.path.read_bytes() if self.path.is_file() else None
        raw = Path(config).read_bytes()
        self.launches.append(dict(config=raw, profile=profile, ran=mt5_runs(profile, raw)))
        return self.start(config)


class WriterTests(unittest.TestCase):
    """studio_tester_profile itself: path, bytes, refusals, atomic replace."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'terminal'
        self.install = dict(terminal_data_root=str(self.data), ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        self.profile = self.data / 'MQL5/Profiles/Tester/GOAT V1.49.set'
        self.inputs = ('EA_Desc=H0123_00001\r\nGrid_Size=-4.0||-5||1||-3||Y\r\nADX_Level=22.0||22.0||0||22.0||N\r\nNote=a||b\r\n'
                       'Mode_Operation=9\r\nSequence_Export_Enabled=false\r\nSequence_Export_Id=\r\nStudio_MonitorRunPath=\r\n'
                       'GOAT_FitnessRunNonce=0||0||0||0||N\r\n')
        self.config = self.write_config('[Common]\r\nLogin=1\r\n[Tester]\r\nModel=4\r\nOptimization=0\r\n[TesterInputs]\r\n' + self.inputs)

    def write_config(self, text, name='run.ini'):
        path = Path(self.tmp.name) / name
        path.write_bytes(text.encode('utf-16'))
        return path

    def test_the_profile_path_is_the_experts_stem_under_profiles_tester(self):
        self.assertEqual(tp.profile_path(self.install), self.profile)
        self.assertEqual(tp.profile_path(dict(self.install, ea_relative_path='GOAT V1.47.ex5')).name, 'GOAT V1.47.set')

    def test_byte_format_bom_utf16le_crlf_and_every_tail_kept(self):
        stale_profile(self.profile)
        receipt = tp.write_profile(self.install, self.config, config_sha256=hashlib.sha256(self.config.read_bytes()).hexdigest())
        raw = self.profile.read_bytes()
        self.assertTrue(raw.startswith(b'\xff\xfe'))
        self.assertNotIn(b'\xfe\xff', raw[:2])
        text = raw[2:].decode('utf-16-le')
        self.assertEqual(text, self.inputs)                                     # exactly the config's lines, in order
        self.assertEqual(text.count('\r\n'), text.count('\n'))                  # CRLF only
        self.assertEqual(raw, b'\xff\xfe' + self.inputs.encode('utf-16-le'))
        for line in ('Grid_Size=-4.0||-5||1||-3||Y', 'ADX_Level=22.0||22.0||0||22.0||N', 'Note=a||b', 'Sequence_Export_Id=',
                     'Studio_MonitorRunPath=', 'GOAT_FitnessRunNonce=0||0||0||0||N'):
            self.assertIn(line, profile_lines(raw))
        self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['config_sha256'], hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertEqual((receipt['path'], receipt['inputs'], receipt['bytes']), (str(self.profile), 9, len(raw)))
        self.assertIsNotNone(receipt['previous_sha256'])
        self.assertIn('Sequence_Export_Id', receipt['changed'])
        self.assertIn('Studio_MonitorRunPath', receipt['changed'])

    def test_comments_and_blank_lines_are_not_inputs(self):
        config = self.write_config('[Tester]\r\nModel=1\r\n[TesterInputs]\r\n; ===== GENERAL =====\r\n\r\nGrid_Size=-4.0||-5||1||-3||Y\r\n'
                                   'EA_Desc=x\r\n', 'native.ini')
        tp.write_profile(self.install, config)
        self.assertEqual(profile_lines(self.profile.read_bytes()), ['Grid_Size=-4.0||-5||1||-3||Y', 'EA_Desc=x'])

    def test_other_profiles_in_the_folder_are_never_touched(self):
        stale_profile(self.profile)
        others = {self.profile.with_name('Other EA.set'): b'\xff\xfeo\x00', self.profile.with_name('GOAT V1.49.set.bak'): b'keep',
                  self.profile.with_name('GOAT V1.48.set'): b'\xff\xfeA\x00=\x001\x00'}
        for path, raw in others.items():
            path.write_bytes(raw)
        tp.write_profile(self.install, self.config)
        self.assertEqual({p: p.read_bytes() for p in others}, others)
        self.assertEqual(sorted(p.name for p in self.profile.parent.iterdir()),
                         sorted(['GOAT V1.49.set'] + [p.name for p in others]))                # no temporary file left

    def test_a_missing_folder_is_created_and_an_absent_profile_is_written(self):
        receipt = tp.write_profile(self.install, self.config)
        self.assertEqual(self.profile.read_bytes(), b'\xff\xfe' + self.inputs.encode('utf-16-le'))
        self.assertEqual((receipt['previous_sha256'], receipt['changed']), (None, None))

    def refused(self, pattern, **kwargs):
        stale = stale_profile(self.profile).read_bytes()
        with self.assertRaisesRegex(ValueError, pattern):
            tp.write_profile(self.install, kwargs.pop('config', self.config), **kwargs)
        self.assertEqual(self.profile.read_bytes(), stale, 'a refusal leaves the profile as it was')
        self.assertEqual([p.name for p in self.profile.parent.iterdir()], ['GOAT V1.49.set'])

    def test_refusals_write_nothing(self):
        self.refused('changed since it was written', config_sha256='0' * 64)
        self.refused('MT5 is running', inspect=lambda: dict(pid=1))
        self.refused(r'exactly one \[TesterInputs\] section \(found 0\)', config=self.write_config('[Tester]\r\nModel=1\r\n', 'none.ini'))
        self.refused('sets no input', config=self.write_config('[Tester]\r\nModel=1\r\n[TesterInputs]\r\n', 'empty.ini'))
        self.refused('twice', config=self.write_config('[TesterInputs]\r\nA=1\r\nA=2\r\n', 'twice.ini'))
        self.refused('not name=value', config=self.write_config('[TesterInputs]\r\nA\r\n', 'bare.ini'))
        bad = Path(self.tmp.name) / 'utf8.ini'; bad.write_bytes(b'[TesterInputs]\r\nA=1\r\n')
        self.refused('not UTF-16', config=bad)

    def test_a_profile_that_is_a_folder_is_refused(self):
        self.profile.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'is not a file'):
            tp.write_profile(self.install, self.config)
        self.assertTrue(self.profile.is_dir())

    def test_a_failed_replace_keeps_the_old_profile_and_removes_only_its_own_temporary_file(self):
        stale = stale_profile(self.profile).read_bytes()
        with patch('studio_tester_profile.os.replace', side_effect=OSError(22, 'replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                tp.write_profile(self.install, self.config)
        self.assertEqual(self.profile.read_bytes(), stale)
        self.assertEqual([p.name for p in self.profile.parent.iterdir()], ['GOAT V1.49.set'])

    def test_the_mt5_model_reproduces_the_banker_refusal_only_without_the_profile(self):
        """The fixture model itself: an empty pin over a stale profile runs the stale value; over the written one, ''."""
        config = self.config.read_bytes()
        stale = stale_profile(self.profile).read_bytes()
        self.assertEqual(mt5_runs(stale, config)['Sequence_Export_Id'], STALE_ID)
        tp.write_profile(self.install, self.config)
        ran = mt5_runs(self.profile.read_bytes(), config)
        self.assertEqual((ran['Sequence_Export_Id'], ran['Studio_MonitorRunPath'], ran['GOAT_FitnessRunNonce']), ('', '', '0'))


class HoldupProfileTests(unittest.TestCase):
    """Hold-up (studio_holdup -> SeedRunner launch): the F-01 shape end to end, report check included."""

    def setUp(self):
        from test_studio_holdup import HoldupTests
        fixture = HoldupTests()
        self.recorder = Recorder(lambda config: HoldupTests.start(fixture, config))
        fixture.start = self.recorder
        fixture.mt5_writes_report = self.report_with_runtime_inputs
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.recorder.path = Path(fixture.c.install['terminal_data_root']) / 'MQL5/Profiles/Tester/GOAT V1.47.set'
        stale_profile(self.recorder.path)

    def report_with_runtime_inputs(self, index):
        """MT5's report also prints the runtime inputs it ran (the B43+ report); the recorded fixture predates them."""
        from test_studio_holdup import HoldupTests
        HoldupTests.mt5_writes_report(self.fixture, index)
        member = read_json(self.fixture.runner.path('h1') / 'manifest.json')['members'][index]
        path = Path(self.fixture.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/HoldupReports' / (member['alias'] + '.htm')
        text = path.read_bytes()[2:].decode('utf-16-le')
        ran = self.recorder.launches[index]['ran']
        rows = ''.join('\r\n   <tr align="right">\r\n      <td nowrap colspan="3"></td>\r\n      <td nowrap colspan="10" align="left">'
                       '<b>%s=%s</b></td>\r\n   </tr>' % (name, ran[name]) for name in tr.RUNTIME_INPUT_DEFAULTS if name in ran)
        end = text.index('</tr>', text.index('<b>EA_Desc=')) + len('</tr>')
        path.write_bytes(b'\xff\xfe' + (text[:end] + rows + text[end:]).encode('utf-16-le'))

    def test_a_stale_export_id_in_the_profile_no_longer_refuses_the_hold_up(self):
        state = self.fixture.run_plan()
        # check() passes: the report's ran inputs now match, so the member completes (before: Banker's refusal).
        self.assertEqual(state['status'], 'completed', json.dumps(state['members'][0].get('error')))
        launch = self.recorder.launches[0]
        member = read_json(self.fixture.runner.path('h1') / 'manifest.json')['members'][0]
        # The profile MT5 read at the launch is exactly the member's [TesterInputs], empty strings included.
        self.assertEqual(launch['profile'], tp.profile_for_config(launch['config']))
        lines = profile_lines(launch['profile'])
        for line in ('Sequence_Export_Id=', 'Sequence_Export_Enabled=false', 'Studio_MonitorRunPath=', 'GOAT_FitnessRunNonce=0'):
            self.assertIn(line, lines)
        self.assertNotIn(STALE_ID, launch['profile'].decode('utf-16'))
        self.assertEqual(dict(tp.tester_inputs(launch['config'])), read_values(launch['profile']))
        for name, value in member['values'].items():
            self.assertIn('%s=%s' % (name, value), lines)
        self.assertEqual(launch['ran']['Sequence_Export_Id'], '')
        item = state['members'][0]
        result = read_json(item['result']['path'])
        self.assertTrue(all(result['checks'].values()))
        # The receipt sits next to the config sha on the member, and proves the bytes MT5 was given.
        self.assertEqual(item['tester_profile']['sha256'], hashlib.sha256(launch['profile']).hexdigest())
        self.assertEqual(item['tester_profile']['config_sha256'], member['config_sha256'])
        self.assertEqual(item['tester_profile']['path'], str(self.recorder.path))
        self.assertIn('Sequence_Export_Id', item['tester_profile']['changed'])

    def test_check_passes_on_the_report_mt5_wrote_and_refuses_the_stale_profiles_run(self):
        """studio_tester_report.check() on the member's own retained report: it passes, and the same report as MT5 would
        have printed it over the stale profile (the F-01 run) is refused with Banker's reason."""
        state = self.fixture.run_plan()
        self.assertEqual(state['status'], 'completed', json.dumps(state['members'][0].get('error')))
        launch = self.recorder.launches[0]
        member = read_json(self.fixture.runner.path('h1') / 'manifest.json')['members'][0]
        report = tr.read_report(read_json(state['members'][0]['result']['path'])['path'])
        tester = member['tester']
        arguments = dict(values=member['values'], schema=self.fixture.c.schema, expert='GOAT V1.47', symbol=tester['Symbol'],
                         period=tester['Period'], from_date=tester['FromDate'], to_date=tester['ToDate'],
                         deposit=tester['Deposit'], currency=tester['Currency'], leverage=tester['Leverage'])
        self.assertEqual(report['inputs']['Sequence_Export_Id'], '')                 # read from the report MT5 printed
        self.assertTrue(tr.check(report, **arguments)['inputs_match'])
        stale = mt5_runs(stale_profile(Path(self.fixture.root) / 'stale' / 'GOAT V1.47.set').read_bytes(), launch['config'])
        self.assertEqual(stale['Sequence_Export_Id'], STALE_ID)
        report['inputs'] = dict(report['inputs'], Sequence_Export_Id=stale['Sequence_Export_Id'])
        with self.assertRaisesRegex(ValueError, 'MT5 ran input\\(s\\) the frozen SET does not set, not at their default: '
                                                'Sequence_Export_Id ran ' + STALE_ID + ', default '):
            tr.check(report, **arguments)


class CatchupProfileTests(unittest.TestCase):
    """Catch-up (studio_catchup -> SeedRunner launch): the profile is the config's pins; the report cross-check passes."""

    def setUp(self):
        from test_studio_catchup import CatchupCase
        fixture = CatchupCase()
        self.recorder = Recorder(self.start)
        fixture.start = self.recorder
        fixture.setUp(); self.addCleanup(fixture.doCleanups); self.addCleanup(fixture.tearDown)
        self.fixture, self.CatchupCase = fixture, CatchupCase
        self.recorder.path = Path(fixture.controller.install['terminal_data_root']) / 'MQL5/Profiles/Tester/GOAT V1.49.set'
        stale_profile(self.recorder.path)

    def start(self, config):
        """MT5 writes its report (the runtime inputs it ran) next to the EA's re-test export."""
        identity = self.CatchupCase.start(self.fixture, config)
        manifest = read_json(self.fixture.runner.path('cu1') / 'manifest.json')
        member = manifest['members'][len(self.fixture.starts) - 1]
        ran = self.recorder.launches[-1]['ran']
        inputs = {name: ran[name] for name in tr.RUNTIME_INPUT_DEFAULTS if name in ran}
        path = Path(self.fixture.controller.install['terminal_data_root']) / (member['tester']['Report'] + '.htm')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(minimal_report(inputs))
        return identity

    def test_a_stale_profile_no_longer_refuses_the_catch_up(self):
        self.fixture.runner.prepare('cu1', self.fixture.plan(sets=[self.fixture.behind]))
        self.fixture.auto = True
        state = self.fixture.runner.start('cu1', 30)
        # The re-test's report cross-check passes (before: "MT5's report shows input(s) off the config's pin").
        self.assertEqual(state['status'], 'completed', json.dumps(state['members'][0].get('error')))
        launch = self.recorder.launches[0]
        member = read_json(self.fixture.runner.path('cu1') / 'manifest.json')['members'][0]
        self.assertEqual(launch['profile'], tp.profile_for_config(launch['config']))
        self.assertEqual(read_values(launch['profile']), dict(tp.tester_inputs(launch['config'])))
        lines = profile_lines(launch['profile'])
        self.assertIn('Sequence_Export_Id=' + member['capture_id'], lines)           # catch-up's own id, never the stale one
        self.assertIn('Studio_MonitorRunPath=', lines)
        self.assertNotIn(STALE_ID, launch['profile'].decode('utf-16'))
        self.assertEqual(launch['ran']['Studio_MonitorRunPath'], '')
        item = state['members'][0]
        self.assertEqual(item['status'], 'completed')
        self.assertEqual(item['tester_profile']['sha256'], hashlib.sha256(launch['profile']).hexdigest())
        self.assertEqual(item['tester_profile']['config_sha256'], member['config_sha256'])


class SeedProfileTests(unittest.TestCase):
    """Seed (studio_seed): the same protection, though seeds never call check()."""

    def setUp(self):
        from test_studio_pinned_tester_inputs import SeedPinningTests
        fixture = SeedPinningTests()
        self.recorder = Recorder(lambda config: SeedPinningTests.start(fixture, config))
        fixture.start = self.recorder
        fixture.setUp(); self.addCleanup(fixture.doCleanups); self.addCleanup(fixture.tearDown)
        self.fixture = fixture
        self.recorder.path = Path(fixture.c.install['terminal_data_root']) / 'MQL5/Profiles/Tester/GOAT V1.49.set'
        stale_profile(self.recorder.path, ADX_Level='22.0||27||3||33||Y')
        self.other = self.recorder.path.with_name('Other EA.set'); self.other.write_bytes(b'\xff\xfeo\x00')

    def test_the_seed_launch_writes_the_profile_from_its_own_config(self):
        self.fixture.runner.prepare('batch', self.fixture.plan)
        state = self.fixture.runner.start('batch', 10)
        self.assertEqual(state['status'], 'completed', state)
        launch = self.recorder.launches[0]
        member = read_json(self.fixture.runner.path('batch') / 'manifest.json')['members'][0]
        self.assertEqual(launch['profile'], tp.profile_for_config(Path(member['config_path']).read_bytes()))
        lines = profile_lines(launch['profile'])
        for line in ('Period=10||10||5||20||Y', 'ADX_Level=22.0||22.0||0||22.0||N', 'Size=1.5||1.5||0||1.5||N', 'Note=a||b',
                     'Sequence_Export_Id=', 'Studio_MonitorRunPath=', 'GOAT_FitnessRunNonce=0||0||0||0||N'):
            self.assertIn(line, lines)
        self.assertNotIn(STALE_ID, launch['profile'].decode('utf-16'))
        self.assertEqual(launch['ran']['Sequence_Export_Id'], '')
        self.assertEqual(self.other.read_bytes(), b'\xff\xfeo\x00')
        self.assertEqual(sorted(p.name for p in self.recorder.path.parent.iterdir()), ['GOAT V1.49.set', 'Other EA.set'])
        item = state['members'][0]
        self.assertEqual(item['tester_profile']['sha256'], hashlib.sha256(launch['profile']).hexdigest())
        self.assertEqual(item['tester_profile']['config_sha256'], member['config_sha256'])

    def test_a_profile_that_cannot_be_written_launches_nothing_and_keeps_the_member_pending(self):
        self.fixture.runner.prepare('batch', self.fixture.plan)
        stale = self.recorder.path.read_bytes()
        real = os.replace
        def replace(source, target, *args, **kwargs):
            if Path(target) == self.recorder.path:              # only the profile's own replace fails
                raise OSError(22, 'profile replace failed')
            return real(source, target, *args, **kwargs)
        with patch('os.replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'profile replace failed'):
                self.fixture.runner.start('batch', 10)
        self.assertEqual(self.recorder.launches, [])
        self.assertEqual(self.recorder.path.read_bytes(), stale)
        item = read_json(self.fixture.runner.path('batch') / 'state.json')['members'][0]
        self.assertEqual((item['status'], item['attempts']), ('pending', 0))


class NativeConfigStartProfileTests(unittest.TestCase):
    """Native batches (studio_config_start): the first /config launch gets the profile of its own startup bytes."""

    def setUp(self):
        from test_studio_config_start import ConfigStartTests
        from test_studio_pinned_tester_inputs import NativeStartupRuntimePinTests
        from studio_startup_config import startup_config
        fixture = ConfigStartTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        if REAL_NATIVE_PROFILE is not None:
            fixture.stack.enter_context(patch.object(studio_config_start, '_tester_profile', REAL_NATIVE_PROFILE))
        data = fixture.c.root / 'data'
        fixture.c.install = dict(terminal_data_root=str(data), ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        raw, receipt = startup_config(NativeStartupRuntimePinTests().material(startup_runtime_pins=1))
        fixture.material['startup_raw'] = raw
        fixture.material['startup_receipt']['sha256'] = receipt['sha256']
        fixture.arm_fields['startup_sha256'] = receipt['sha256']
        self.fixture, self.raw = fixture, raw
        self.profile = data / 'MQL5/Profiles/Tester/GOAT V1.49.set'
        stale_profile(self.profile)
        self.launches = []
        def launch(config):
            self.launches.append(dict(inspect=fixture.process.inspect(), config=Path(config).read_bytes(),
                                      profile=self.profile.read_bytes()))
            return dict(pid=22, executable=fixture.binding['research_terminal'], created_utc='2026-09-29T01:00:00Z')
        fixture.process.start.side_effect = launch

    def test_the_first_native_launch_reads_its_own_pins_from_the_profile(self):
        result = self.fixture.run_start()
        self.assertEqual(len(self.launches), 1)
        launch = self.launches[0]
        self.assertIsNone(launch['inspect'])
        self.assertEqual(launch['config'], self.raw)
        self.assertEqual(launch['profile'], tp.profile_for_config(self.raw))
        lines = profile_lines(launch['profile'])
        for line in ('Grid_Size=10.0||10.0||0||10.0||N', 'Sequence_Export_Id=', 'Studio_MonitorRunPath=',
                     'GOAT_FitnessRunNonce=0||0||0||0||N'):
            self.assertIn(line, lines)
        self.assertEqual(mt5_runs(launch['profile'], self.raw)['Sequence_Export_Id'], '')
        receipt = self.fixture.c.job('batch')['restart_intent']['tester_profile']
        self.assertEqual(receipt['sha256'], hashlib.sha256(launch['profile']).hexdigest())
        self.assertEqual(receipt['config_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(result['tester_profile'], receipt)

    def test_an_mt5_running_again_before_the_launch_refuses_the_write_and_the_launch(self):
        def select(*args):
            self.fixture.process.inspect.return_value = self.fixture.identity       # someone opened MT5 after the close
            return dict(status='selected')
        self.fixture.mocks['_select_research_profile'].side_effect = select
        stale = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, 'MT5 is running'):
            self.fixture.run_start()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.profile.read_bytes(), stale)
        self.fixture.mocks['_rollback_profile_last'].assert_called_once()


def minimal_report(inputs):
    """The smallest MT5 single-test report studio_tester_report.read_report accepts, listing ``inputs``."""
    def row(*cells):
        return '<tr>' + ''.join('<td>%s</td>' % cell for cell in cells) + '</tr>\r\n'
    labels = [('Expert:', 'GOAT V1.49'), ('Symbol:', 'EURUSD'), ('Period:', 'M1 (2026.08.29 - 2026.10.03)')]
    body = row('Strategy Tester Report') + row('Test-Demo (Build 6182)')
    body += ''.join(row(k, v) for k, v in labels)
    names = list(inputs.items())
    body += row('Inputs:', '%s=%s' % names[0]) + ''.join(row('', '%s=%s' % kv) for kv in names[1:])
    for key, value in (('Company:', 'Fixture'), ('Currency:', 'USD'), ('Initial Deposit:', '10 000.00'), ('Leverage:', '1:100'),
                       ('History Quality:', '100%'), ('Bars:', '1'), ('Total Net Profit:', '0.00'), ('Total Trades:', '0'),
                       ('Total Deals:', '0'), ('Equity Drawdown Maximal:', '0.00 (0.00%)'),
                       ('Balance Drawdown Maximal:', '0.00 (0.00%)'), ('Equity Drawdown Relative:', '0.00% (0.00)'),
                       ('Balance Drawdown Relative:', '0.00% (0.00)'), ('Profit Trades (% of total):', '0 (0.00%)'),
                       ('Short Trades (won %):', '0 (0.00%)'), ('Long Trades (won %):', '0 (0.00%)')):
        body += row(key, value)
    body += row('Deals') + row(*tr.DEAL_COLUMNS)
    body += row('2026.08.29 00:00:00', '1', '', 'balance', '', '', '', '', '0.00', '0.00', '10 000.00', '10 000.00', '')
    body += row('', '0.00', '0.00', '0.00', '10 000.00')
    return b'\xff\xfe' + ('<html><body><table>\r\n' + body + '</table></body></html>\r\n').encode('utf-16-le')


if __name__ == '__main__':
    unittest.main()
