"""Controller-generated tester inputs must not depend on MT5's saved tester profile.

Regression for T2 seed hunt seedhunt-t2-1 (2026-10-02): the seed startup INI wrote
ADX_Level=22.0 as a plain value, MT5 kept ADX_Level=22.0||27||3||33||Y from
MQL5\\Profiles\\Tester\\GOAT V1.49.set and searched 27/30/33, and the controller
refused the XML with "Seed XML axes differ from frozen template".
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_installation import read_json
from studio_optimization_inputs import explicit_optimization_inputs, verify_explicit_inputs
from studio_process_check import StoppedRootProcess, stopped_candidates
from studio_seed import SeedRunner
from studio_seed_results import collect, HEADERS
from studio_strategy_settings import read_values
from studio_template_tools import validate_raw
from test_studio_seed import xml_result

ROOT = Path(__file__).resolve().parent


def mt5_load(profile, inputs):
    """Model of how MT5 merges [TesterInputs] into its saved tester profile.

    Observed on build 6230: a five-part tuple replaces value, range and flag; a
    plain value replaces only the value and keeps the remembered range and flag.
    MT5 then writes the merged result back to the profile.
    """
    merged = {name: list(parts) for name, parts in profile.items()}
    for name, value in inputs.items():
        parts = value.split('||')
        old = merged.get(name, [value, value, '0', value, 'N'])
        merged[name] = parts if len(parts) == 5 else [parts[0]] + old[1:]
    return merged


def effective_axes(merged):
    return {name for name, parts in merged.items() if parts[4] == 'Y'}


def contaminated_profile():
    """The Banker plan (ADX_Level 27/30/33 among its axes) last used this tester."""
    text = (ROOT/'fixtures/tester-roundtrip/wanted.ini').read_text(encoding='utf-8')
    inputs = text.split('[TesterInputs]', 1)[1]
    return mt5_load({}, {k: v for k, v in (line.split('=', 1) for line in inputs.splitlines() if '=' in line)})


def compass_like_template(schema):
    """A complete V1.49 template: the fixture's axes except ADX_Level, every other input plain."""
    text = (ROOT/'fixtures/tester-roundtrip/wanted.ini').read_text(encoding='utf-8').split('[TesterInputs]', 1)[1]
    lines = []
    for line in text.splitlines():
        if '=' not in line or line.lstrip().startswith(';'):
            lines.append(line); continue
        name, value = line.split('=', 1)
        if schema['inputs'][name]['type'] != 'string':
            parts = value.split('||')
            if name == 'ADX_Level':
                value = '22.0'
            elif len(parts) == 5 and parts[4] == 'N':
                value = parts[0]
        lines.append(name+'='+value)
    return '\r\n'.join(line for line in lines if line.strip())+'\r\n'


class RealSchemaPinningTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT/'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        self.policy = json.loads((ROOT/'contracts/v149/dependencies.json').read_text(encoding='utf-8-sig'))
        self.template = compass_like_template(self.schema)
        self.axes = {'Grid_Size', 'Lock_Profit_Size', 'Lock_Profit_Flexibility', 'RSI_Period', 'RSI_Level', 'BB_Deviation'}

    def test_template_fixture_is_a_valid_template_with_plain_non_axis_inputs(self):
        raw = b'\xff\xfe'+self.template.encode('utf-16-le')
        self.assertEqual(set(validate_raw(raw, self.schema, self.policy, require_optimization=True)['active_axes']), self.axes)
        self.assertIn('ADX_Level=22.0\r\n', self.template)

    def test_plain_values_let_a_contaminated_profile_add_the_stale_axis(self):
        # The bug: what the controller used to write for seeds.
        merged = mt5_load(contaminated_profile(), read_values(self.template.encode('utf-16')))
        self.assertEqual(effective_axes(merged), self.axes | {'ADX_Level'})
        self.assertEqual(merged['ADX_Level'], ['22.0', '27', '3', '33', 'Y'])

    def test_pinned_values_keep_the_frozen_axes_under_a_contaminated_profile(self):
        pinned = read_values(explicit_optimization_inputs(self.template, self.schema).encode('utf-16'))
        profile = contaminated_profile()
        for _ in range(3):  # MT5 writes the merge back; repeated launches must stay clean.
            profile = mt5_load(profile, pinned)
            self.assertEqual(effective_axes(profile), self.axes)
        self.assertEqual(profile['ADX_Level'], ['22.0', '22.0', '0', '22.0', 'N'])
        source = read_values(self.template.encode('utf-16'))
        for name in self.axes:
            self.assertEqual(profile[name], source[name].split('||'), 'axis keeps its exact frozen range and Y')

    def test_pinned_values_keep_every_trading_value_and_validate(self):
        rendered = explicit_optimization_inputs(self.template, self.schema)
        source, pinned = read_values(self.template.encode('utf-16')), read_values(rendered.encode('utf-16'))
        self.assertEqual(set(source), set(pinned))
        for name in source:
            if self.schema['inputs'][name]['type'] == 'string':
                self.assertEqual(pinned[name], source[name])
            else:
                self.assertEqual(pinned[name].split('||')[0], source[name].split('||')[0], name)
        raw = b'\xff\xfe'+rendered.encode('utf-16-le')
        self.assertEqual(set(validate_raw(raw, self.schema, self.policy, require_optimization=True)['active_axes']), self.axes)
        verify_explicit_inputs(pinned, self.schema, self.axes)
        self.assertEqual(explicit_optimization_inputs(rendered, self.schema), rendered, 'idempotent')

    def test_byte_level_lines(self):
        rendered = explicit_optimization_inputs(self.template, self.schema)
        for line in ('ADX_Level=22.0||22.0||0||22.0||N\r\n', 'EMA_Period=30||30||0||30||N\r\n',
                     'EMA_MustCheck=false||false||0||false||N\r\n', 'Mode_Operation=9\r\n',
                     'Grid_Size=-4.0||-5||1||-3||Y\r\n', 'Signal_Sample_Period=99\r\n',
                     'RSI_Level=70.0||65||5||75||Y\r\n', 'EA_Desc=FixtureStrategy\r\n'):
            self.assertIn(line, rendered)
        self.assertNotIn('\nADX_Level=22.0\r\n', '\n'+rendered)

    def test_verify_refuses_plain_or_wrongly_flagged_inputs(self):
        pinned = read_values(explicit_optimization_inputs(self.template, self.schema).encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'no explicit optimization flag: ADX_Level'):
            verify_explicit_inputs(pinned | {'ADX_Level': '22.0'}, self.schema, self.axes)
        with self.assertRaisesRegex(ValueError, 'differs from the frozen axes: ADX_Level'):
            verify_explicit_inputs(pinned | {'ADX_Level': '22.0||27||3||33||Y'}, self.schema, self.axes)
        with self.assertRaisesRegex(ValueError, 'differs from the frozen axes: RSI_Level'):
            verify_explicit_inputs(pinned | {'RSI_Level': '70.0||65||5||75||N'}, self.schema, self.axes)


class SeedPinningTests(unittest.TestCase):
    """Seed prepare writes pinned SET and INI bytes; the XML axis check stays strict."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.now = 1000000.0; self.process_state = dict(pid=10, executable='terminal64.exe', created_utc='first'); self.starts = []
        c = SimpleNamespace(root=self.root/'controller', local=self.root/'local')
        c.root.mkdir(); (c.local/'native-gate').mkdir(parents=True)
        data = self.root/'terminal'; binary = data/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'; binary.parent.mkdir(parents=True); binary.write_bytes(b'ex5')
        c.install = dict(terminal_data_root=str(data), common_files_root=str(self.root/'common'), terminal_executable=str(data/'terminal64.exe'),
                         ea_relative_path='GOAT-EA\\GOAT V1.49.ex5', ea_version='1.49', ea_sha256=hashlib.sha256(b'ex5').hexdigest())
        c.session = dict(account={'login': '123', 'server': 'Test-Demo'}, run_id='session-'+'f'*32)
        c.schema = {'source_sha256': 'a'*64, 'inputs': {
            'EA_Desc': dict(type='string', optimizable=False), 'Period': dict(type='int', optimizable=True),
            'Size': dict(type='double', optimizable=True), 'ADX_Level': dict(type='double', optimizable=True),
            'UseTrail': dict(type='bool', optimizable=True), 'Note': dict(type='string', optimizable=False),
            'Fixed_Mode': dict(type='int', optimizable=False)}}
        c.policy = dict(header_sha256='a'*64, main_sha256='b'*64, coverage='indicator_mode_gates_only', rules=[])
        self.owner = dict(owner='agent', generation=1, queue=[])
        c.state = lambda: copy.deepcopy(self.owner)
        c.bridge = SimpleNamespace(pump=lambda: None)
        c.runtime = lambda **kw: ({'loaded': True, 'owner': 'agent', 'generation': 1}, {})
        self.c = c
        # Terminal isolation preflight is covered elsewhere; this fixture has no live EA.
        isolation = patch('studio_seed.controller_preflight', lambda controller, observation: None)
        isolation.start(); self.addCleanup(isolation.stop)
        process = SimpleNamespace(inspect=lambda: copy.deepcopy(self.process_state), close=self.close, start=self.start)
        self.runner = SeedRunner(c, process=process, clock=lambda: self.now, sleep=self.sleep)
        self.source = self.root/'source.set'
        self.source.write_bytes(('; Source header\r\nEA_Desc=Original\r\nPeriod=10||10||5||20||Y\r\nSize=1.5\r\nADX_Level=22.0\r\n'
                                 'UseTrail=false\r\nNote=a||b\r\nFixed_Mode=3\r\n').encode('utf-16'))
        tester = dict(Expert=c.install['ea_relative_path'], Symbol='EURUSD', Period='M1', Model=1, ExecutionMode=0, Optimization=2,
                      OptimizationCriterion=6, FromDate='2025.04.01', ToDate='2026.06.30', ForwardMode=0, ForwardDate='', Deposit=10000,
                      Currency='USD', Leverage='1:100', UseLocal=1, UseRemote=0, UseCloud=0, Visual=0)
        self.plan = dict(schema_version=1, max_attempts_per_job=1, job_timeout_seconds=30, cutoff=dict(min_fitness=0, min_trades=1),
                         jobs=[dict(set_path=str(self.source), tester=tester, frame_target=2)])
        self.mt5_profile = {'ADX_Level': ['22.0', '27', '3', '33', 'Y'], 'Size': ['1.5', '1', '0.5', '2', 'Y']}

    def tearDown(self): self.tmp.cleanup()

    def close(self, identity): self.process_state = None

    def start(self, config):
        self.starts.append(config)
        # MT5 reads the startup INI against its contaminated saved tester profile.
        inputs = Path(config).read_bytes().decode('utf-16').split('[TesterInputs]\r\n', 1)[1]
        self.mt5_profile = mt5_load(self.mt5_profile, dict(line.split('=', 1) for line in inputs.splitlines()))
        self.process_state = dict(pid=10+len(self.starts), executable='terminal64.exe', created_utc='run'+str(len(self.starts)))
        return copy.deepcopy(self.process_state)

    def sleep(self, seconds):
        self.now += seconds
        if self.starts and self.process_state:
            member = read_json(self.runner.path('batch')/'manifest.json')['members'][0]
            searched = sorted(effective_axes(self.mt5_profile))
            self.output(member, searched); self.process_state = None

    def output(self, member, searched, rows=None):
        spec = member | dict(axes={name: 1 for name in searched})
        rows = rows or [[1, 4, 10, 2, 2, 2, 2, 4, 1, 10]+[10 if n == 'Period' else 1.5 for n in searched],
                        [2, -2, 0, 0, 0, 0, 0, -2, 0, 0]+[15 if n == 'Period' else 1.5 for n in searched]]
        path = Path(self.c.install['common_files_root'])/'GOAT/SeedFarmingXML'/(member['output_base']+'_N2_AvgFit=1.000_Health=50.00_Zero=1_AvgTrades=5.0_Best=4.000.xml')
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(xml_result(spec, rows)); return path

    def member(self): return read_json(self.runner.path('batch')/'manifest.json')['members'][0]

    def test_frozen_set_and_startup_ini_bytes_pin_every_non_axis_input(self):
        self.runner.prepare('batch', self.plan); m = self.member()
        frozen = Path(m['set_path']).read_bytes()
        self.assertTrue(frozen.startswith(b'\xff\xfe'))
        expected_inputs = ('Period=10||10||5||20||Y\r\nSize=1.5||1.5||0||1.5||N\r\nADX_Level=22.0||22.0||0||22.0||N\r\n'
                           'UseTrail=false||false||0||false||N\r\nNote=a||b\r\nFixed_Mode=3\r\n')
        self.assertEqual(frozen, b'\xff\xfe'+('; Source header\r\nEA_Desc='+m['alias']+'@{mode=SeedFarming,n=2,from=2025.04.01,to=2026.06.30}\r\n'
                                              +expected_inputs).encode('utf-16-le'))
        ini = Path(m['config_path']).read_bytes()
        self.assertTrue(ini.startswith(b'\xff\xfe'))
        text = ini.decode('utf-16')
        self.assertTrue(text.endswith('[TesterInputs]\r\nEA_Desc='+m['alias']+'@{mode=SeedFarming,n=2,from=2025.04.01,to=2026.06.30}\r\n'+expected_inputs), text)
        self.assertEqual(hashlib.sha256(ini).hexdigest(), m['config_sha256'])
        self.assertEqual(m['axes'], {'Period': 3})
        self.assertEqual(m['values']['Note'], 'a||b', 'literal strings are never tuple-rewritten')

    def test_contaminated_tester_profile_no_longer_adds_axes_and_seed_completes(self):
        self.runner.prepare('batch', self.plan)
        state = self.runner.start('batch', 10)
        self.assertEqual(effective_axes(self.mt5_profile), {'Period'})
        self.assertEqual(self.mt5_profile['ADX_Level'], ['22.0', '22.0', '0', '22.0', 'N'])
        self.assertEqual(state['status'], 'completed', state)
        self.assertIn('monitor-launch', state['next_action'])
        self.assertEqual(state['monitor_profile'], 'GOAT-Studio-'+'f'*32)
        report = self.runner.report('batch')['members'][0]
        self.assertEqual(report['actual_frames'], 2)
        result = read_json(report['result_path'])
        self.assertEqual(result['base_values']['ADX_Level'], '22.0', 'candidate values keep the plain trading value')

    def test_extra_varying_axis_is_still_refused_and_reported_with_its_xml(self):
        self.runner.prepare('batch', self.plan); m = self.member()
        # An MT5 that still searched ADX_Level (e.g. an EA/tester ignoring the flag) is refused.
        produced = []
        def contaminated(seconds):
            self.now += seconds
            if self.starts and self.process_state:
                produced.append(self.output(m, ['ADX_Level', 'Period'])); self.process_state = None
        self.runner.sleep = contaminated
        state = self.runner.start('batch', 10)
        path = produced[0]
        with self.assertRaisesRegex(ValueError, 'Seed XML axes differ from frozen template'):
            collect(path, m, self.c.schema, self.plan['cutoff'])
        self.assertEqual(state['status'], 'stopped')
        row = self.runner.report('batch')['members'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['error'], 'Seed XML axes differ from frozen template')
        self.assertIsNone(row['xml_path'], 'xml_path stays reserved for accepted evidence')
        self.assertIsNone(row['actual_frames'])
        self.assertEqual(row['observed_xml']['path'], str(path))
        self.assertEqual(row['observed_xml']['frames_from_filename'], 2)
        self.assertFalse(row['observed_xml']['accepted'])
        self.assertEqual(row['observed_xml']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_report_finds_xml_for_a_member_failed_before_this_fix(self):
        self.runner.prepare('batch', self.plan); m = self.member()
        root = self.runner.path('batch'); state = read_json(root/'state.json')
        state['members'][0].update(status='failed', attempts=1, error='Seed XML axes differ from frozen template')
        state['status'] = 'stopped'; state['generation'] = 1
        (root/'state.json').write_text(json.dumps(state), encoding='utf-8')
        path = self.output(m, ['ADX_Level', 'Period'])
        row = self.runner.report('batch')['members'][0]
        self.assertEqual(row['error'], 'Seed XML axes differ from frozen template')
        self.assertEqual(row['observed_xml']['path'], str(path))

    def test_prepared_batch_has_no_restore_hint(self):
        state = self.runner.prepare('batch', self.plan)
        self.assertNotIn('monitor_profile', state)

    def make_pre_fix(self, **state_changes):
        """Rewrite the prepared package as a pre-fix one: plain non-axis values in the manifest."""
        from studio_bridge import write_json
        from studio_seed import digest
        self.runner.prepare('batch', self.plan)
        root = self.runner.path('batch'); manifest = read_json(root/'manifest.json')
        for member in manifest['members']:
            member['values'] = {k: (v.split('||')[0] if v.endswith('||N') else v) for k, v in member['values'].items()}
        write_json(root/'manifest.json', manifest)
        state = read_json(root/'state.json'); state['manifest_sha256'] = digest(root/'manifest.json'); state.update(state_changes)
        write_json(root/'state.json', state)
        self.closes = []
        self.runner.process.close = lambda identity: self.closes.append(identity)
        return root

    def test_pre_fix_package_is_refused_by_prepare_with_the_same_id(self):
        self.make_pre_fix()
        with self.assertRaisesRegex(ValueError, r'prepared before explicit optimization flags \(.*no explicit optimization flag: Size\); prepare a new batch ID'):
            self.runner.prepare('batch', self.plan)

    def test_pre_fix_package_is_refused_by_start_before_any_process_effect(self):
        root = self.make_pre_fix()
        with self.assertRaisesRegex(ValueError, 'prepared before explicit optimization flags'):
            self.runner.start('batch', 10)
        self.assertEqual((self.starts, self.closes), ([], []), 'monitor never closed, no member started')
        self.assertEqual(read_json(root/'state.json')['status'], 'prepared')
        self.assertFalse(self.runner.slot.exists())

    def test_pre_fix_package_is_refused_by_resume_before_the_next_launch(self):
        root = self.make_pre_fix(status='active', generation=1)
        from studio_bridge import write_json
        write_json(self.runner.slot, dict(status='active', batch_id='batch', manifest_sha256=read_json(root/'state.json')['manifest_sha256'], generation=1))
        self.process_state = None
        with self.assertRaisesRegex(ValueError, 'prepared before explicit optimization flags'):
            self.runner.resume('batch', 10)
        self.assertEqual(self.starts, [])
        self.assertEqual(read_json(root/'state.json')['members'][0]['status'], 'pending', 'member is not consumed')

    def test_fresh_package_passes_the_pre_fix_guard(self):
        self.runner.prepare('batch', self.plan)
        self.assertEqual(self.runner.prepare('batch', self.plan)['status'], 'prepared')

    def test_oversized_refused_xml_is_recorded_without_hashing(self):
        path = self.root/'x_N7_big.xml'; path.write_bytes(b'0123456789')
        with patch('studio_seed.MAX_XML_BYTES', 5):
            row = SeedRunner._observed_xml(path)
        self.assertEqual((row['sha256'], row['size_bytes'], row['frames_from_filename'], row['accepted']), (None, 10, 7, False))
        row = SeedRunner._observed_xml(path)
        self.assertEqual(row['sha256'], hashlib.sha256(b'0123456789').hexdigest())


class StoppedRootMessageTests(unittest.TestCase):
    def test_names_program_pid_and_metaeditor_action(self):
        root = 'G:\\MetaTrader5 Data\\Terminals\\Terminal 2 - GOAT'
        rows = [dict(ProcessId=13624, Name='MetaEditor64.exe', ExecutablePath=root+'\\MetaEditor64.exe')]
        with self.assertRaises(StoppedRootProcess) as caught:
            stopped_candidates(rows, [root])
        error = caught.exception
        self.assertIsInstance(error, ValueError)
        self.assertTrue(str(error).startswith('Executable is running under a stopped terminal root: MetaEditor64.exe (PID 13624'))
        self.assertIn('File > Exit', error.next_action())
        self.assertNotRegex(error.next_action(), r'(?<!not use )monitor-prepare then')
        self.assertEqual((error.program, error.pid), ('MetaEditor64.exe', 13624))

    def test_other_program_action_names_it(self):
        error = StoppedRootProcess('C:\\T\\metatester64.exe', 7)
        self.assertIn('metatester64.exe (PID 7)', error.next_action())
        self.assertTrue(re.search('force-kill', error.next_action()))


class ChartProfileHintTests(unittest.TestCase):
    def test_names_saved_profile_only_when_it_is_not_the_monitor_profile(self):
        from studio_onboarding import wrong_chart_profile
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            controller = SimpleNamespace(install=dict(terminal_data_root=str(data)))
            session = dict(run_id='session-'+'f0'*16)
            monitor = 'GOAT-Studio-'+'f0'*16
            (data/'MQL5/Profiles/Charts'/monitor).mkdir(parents=True); (data/'config').mkdir()
            common = data/'config/common.ini'
            common.write_bytes('[Common]\r\nLogin=1\r\n[Charts]\r\nProfileLast=GOAT-DemoRaw-20260831\r\n'.encode('utf-16'))
            self.assertEqual(wrong_chart_profile(controller, session), dict(profile_last='GOAT-DemoRaw-20260831', monitor_profile=monitor))
            common.write_bytes(('[Charts]\r\nProfileLast='+monitor+'\r\n').encode('utf-16'))
            self.assertIsNone(wrong_chart_profile(controller, session))
            common.unlink()
            self.assertIsNone(wrong_chart_profile(controller, session), 'unreadable evidence is no hint, never an error')


if __name__ == '__main__':
    unittest.main()
