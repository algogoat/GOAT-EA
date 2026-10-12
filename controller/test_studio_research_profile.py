"""Batches run on GOAT Research, never on the GOAT Studio monitor profile (Claude-Mac goatai#2350 6120004490).

Fixture-only: no MT5 is launched, closed or attached (a fixture MT5 stands in for it), and the MetaTrader5 adapter is
never imported for real. MT5 adds the auto-tested symbol's bare chart (id=0) to the chart profile it has open and saves
it there on close; batches used to run on the monitor profile, so every batch left charts there and monitor-launch,
the fix-B record and goatai#2479's restore refused it (extra_charts). Covered here: GOAT Research's reset (prepare),
the ProfileLast restore, the one-time monitor-profile migration (T3's 12-chart shape, Banker's shape, a person-added
EA chart), the [StartUp] shape and member INIs, fix B on a two-chart profile, the config-start end state, and a
fixture-MT5 run of a config start, a seed hunt and a catch-up that never changes the monitor profile's bytes.
"""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import packed
import studio_research_profile as rp
from studio_config_start import RESTART_CONSENT_SCOPE, restart_recovery
from studio_onboarding import (HEALTHY_CHART_RECORD, MONITOR_PROFILE_REFUSAL, monitor_chart, monitor_launch,
                               onboarding_status, pre_close_health, record_post_close_chart, session_state)
from studio_refusal import Refusal
from studio_startup_config import startup_config
import test_studio_monitor_preserved_chart as preserved

FIXTURES = Path(__file__).parent/'fixtures'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def chr_bytes(text):
    return text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-16')


def bare_chart(symbol, *, moving_averages=0, objects=1, period_type=1):
    """The auto-tested symbol's chart as MT5 saves it (id=0): no expert, the Main window, optional Moving Average
    indicators with their <graph> blocks and trade-arrow objects. Reduced from T3's and Banker's saved shapes."""
    lines = ['<chart>', 'id=0', 'symbol='+symbol, 'description='+symbol, 'period_type=%d' % period_type, 'period_size=1',
             'digits=5', 'scale=16', 'mode=1', 'windows_total=1', '', '<window>', 'height=100.000000', 'objects=%d' % objects, '',
             '<indicator>', 'name=Main', 'path=', 'apply=1', 'show_data=1', 'expertmode=0', 'fixed_height=-1', '</indicator>']
    for index in range(moving_averages):
        lines += ['', '<indicator>', 'name=Moving Average', 'path=', 'apply=1', 'show_data=1', 'expertmode=0', 'fixed_height=-1', '',
                  '<graph>', 'name=', 'draw=129', 'style=0', 'width=1', 'color=255', '</graph>', 'period=%d' % (23+13*index),
                  'method=1', '</indicator>']
    for index in range(objects):
        lines += ['<object>', 'type=31', 'name=autotrade #%d buy 0.09 %s at 1.17224, %s' % (index+2, symbol, symbol), 'hidden=1',
                  'selectable=0', 'date1=1759424400', 'value1=1.172240', '</object>', '']
    return chr_bytes('\n'.join(lines+['</window>', '</chart>', '']))


def expert_chart(symbol, name='MACD Sample', path='Experts\\Examples\\MACD\\MACD Sample.ex5'):
    """A chart a person added with another EA on it."""
    return chr_bytes('\n'.join(['<chart>', 'id=133', 'symbol='+symbol, 'period_type=0', 'period_size=1', 'windows_total=1', '',
                                '<expert>', 'name='+name, 'path='+path, 'expertmode=5', '<inputs>', 'Lots=0.1', '</inputs>', '</expert>',
                                '', '<window>', 'height=100.000000', 'objects=0', '<indicator>', 'name=Main', 'path=', 'apply=1',
                                'show_data=1', '</indicator>', '</window>', '</chart>', '']))


def t3_monitor_chart():
    """T3's chart01: the GOAT monitor with saved input groups and DLL imports approved (expertmode=4)."""
    text = (FIXTURES/'saved-monitor-input-groups.chr.txt').read_text(encoding='utf-8').replace('GOAT V1.49', 'GOAT V1.48')
    return chr_bytes(text)


def snapshot(folder):
    folder = Path(folder)
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else None


def ini_sections(raw):
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    sections, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            current = sections.setdefault(line[1:-1], {})
        elif current is not None and '=' in line:
            key, value = line.split('=', 1)
            current[key] = value
    return sections


class FixtureMT5:
    """A fixture MT5 for one data folder (never a real process).

    start(config) opens the chart profile the /config INI names in [Charts] ProfileLast, else the one common.ini names
    (as MT5 does); when the INI has a [Tester] section MT5 auto-tests that symbol and adds its bare chart (id=0) to the
    open profile. Closing saves the open profile as MT5 does: it rewrites the profile's charts (their metadata), writes
    the added chart file and names that profile as ProfileLast in common.ini."""

    def __init__(self, data, *, identity, profile, login='123456', server='Customer-Demo'):
        self.data, self.login, self.server = Path(data), login, server
        self.running, self.profile, self.added = dict(identity), profile, []
        self.pid = identity['pid']
        self.opened, self.starts, self.closes = [profile], [], []

    def profiles(self):
        return self.data/'MQL5'/'Profiles'/'Charts'

    def inspect(self):
        return copy.deepcopy(self.running)

    def close(self, identity):
        if identity != self.running:
            raise ValueError('changed')
        self.closes.append(identity)
        self.exit()

    def exit(self):
        """MT5 closing (GOAT's normal close, the EA's TerminalClose, or ShutdownTerminal=1 after a test)."""
        folder = self.profiles()/self.profile
        for chart in sorted(folder.glob('*.chr')):
            text = chart.read_bytes().decode('utf-16')
            chart.write_bytes(re.sub(r'(?m)^scale=\d+', 'scale=4', text).encode('utf-16'))
        for symbol in self.added:
            used = {p.name.lower() for p in folder.glob('*.chr')}
            name = next('chart%02d.chr' % n for n in range(1, 100) if 'chart%02d.chr' % n not in used)
            (folder/name).write_bytes(bare_chart(symbol))
        self.added = []
        (self.data/'config').mkdir(exist_ok=True)
        (self.data/'config'/'common.ini').write_bytes(('[Common]\r\nLogin='+self.login+'\r\nServer='+self.server+'\r\n[Charts]\r\n'
                                                      'ProfileLast='+self.profile+'\r\n[Experts]\r\nEnabled=0\r\n').encode('utf-16'))
        self.running = None

    def saved_profile(self):
        ini = self.data/'config'/'common.ini'
        return ini_sections(ini.read_bytes()).get('Charts', {}).get('ProfileLast') if ini.exists() else None

    def start(self, config):
        if self.running is not None:
            raise ValueError('MT5 already running')
        sections = ini_sections(Path(config).read_bytes())
        self.profile = sections.get('Charts', {}).get('ProfileLast') or self.saved_profile()
        (self.profiles()/self.profile).mkdir(parents=True, exist_ok=True)   # MT5 creates a profile it does not have
        symbol = sections.get('Tester', {}).get('Symbol')
        self.added = [symbol] if symbol else []
        self.opened.append(self.profile)
        self.starts.append((Path(config).name, self.profile, symbol))
        self.pid += 1
        self.running = dict(pid=self.pid, executable='terminal64.exe', created_utc='2020-01-01T00:%02d:00Z' % (self.pid % 60))
        return copy.deepcopy(self.running)


class ResearchCase(unittest.TestCase):
    """The bound onboarding controller of PreservedChartTests (monitor-prepare done: chart01 EURUSD, expertmode=0)."""

    def setUp(self):
        self.p = preserved.PreservedChartTests('test_the_shared_list_holds_every_open_lab_login')
        self.p.setUp()
        self.addCleanup(self.p.doCleanups)
        self.c = self.p.c
        self.chart = self.p.chart
        self.monitor = self.chart.parent
        self.data = Path(self.c.install['terminal_data_root'])
        self.common_ini = self.p.fixture.common_ini

    def history(self, symbols, kind='seeds', run='earlier', started=True):
        """A seed hunt / catch-up / hold-up record of this installation that tested ``symbols``."""
        folder = self.c.root/kind/run
        folder.mkdir(parents=True)
        members = [dict(member_id=str(i), alias='S%d' % i, tester=dict(Symbol=s)) for i, s in enumerate(symbols)]
        (folder/'manifest.json').write_text(json.dumps(dict(batch_id=run, members=members)))
        (folder/'state.json').write_text(json.dumps(dict(batch_id=run, generation=1 if started else None, status='completed' if started else 'prepared',
                                                         members=[dict(member_id=m['member_id'], attempts=1 if started else 0) for m in members])))

    def native_history(self, rows):
        """Native batch queue rows: (job_id, [symbols], started)."""
        jobs = []
        for job_id, symbols, started in rows:
            job = dict(job_id=job_id, status='completed' if started else 'pending',
                       configuration=dict(batch_members=[dict(tester=dict(Symbol=s)) for s in symbols]))
            if started:
                job['launch_intent'] = dict(attempt_id='a'*64)
            jobs.append(job)
        self.set_queue(jobs)

    def set_queue(self, jobs):
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)', (binding, packed(jobs)))
        self.c.store.db.commit()

    def pollute(self, charts, monitor=None):
        if monitor is not None:
            self.chart.write_bytes(monitor)
        for name, raw in charts.items():
            (self.monitor/name).write_bytes(raw)

    def set_profile_last(self, name, encoding='utf-16'):
        self.common_ini.write_bytes(('[Common]\r\nLogin=123456\r\nServer=Customer-Demo\r\n[Charts]\r\nProfileLast='+name+
                                     '\r\nMaxBars=100000\r\n[Experts]\r\nEnabled=0\r\n').encode(encoding))

    def migrate(self, running=None):
        return rp.migrate_monitor_profile(self.c, 'test-migration', inspect=lambda: running)

    def t3_shape(self):
        """T3's 12-chart monitor profile: chart01 (GOAT V1.48 monitor, expertmode=4) + bare EURUSD x2 (H1 with Moving
        Averages, which may predate batches), GBPJPY x6 and GBPUSD x3 (chart10 is missing, as on T3)."""
        names = ['chart%02d.chr' % n for n in (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13)]
        symbols = ['EURUSD']*2+['GBPJPY']*6+['GBPUSD']*3
        charts = {name: bare_chart(symbol, moving_averages=3 if symbol == 'EURUSD' else 0, objects=3 if symbol == 'EURUSD' else 0)
                  for name, symbol in zip(names, symbols)}
        self.pollute(charts, monitor=t3_monitor_chart())
        return charts


class MigrationTests(ResearchCase):
    def assert_untouched(self, before):
        self.assertEqual(snapshot(self.monitor), before, 'nothing in the monitor profile was moved or changed')
        self.assertFalse((self.c.root/rp.STATE_FOLDER/rp.MIGRATION_RECORD).exists())

    def test_t3_twelve_chart_shape_leaves_only_the_monitor_chart_when_every_symbol_is_in_batch_history(self):
        charts = self.t3_shape()
        self.history(['GBPJPY', 'GBPUSD'], kind='seeds')
        self.native_history([('batch-eurusd', ['EURUSD'], True)])
        before = snapshot(self.monitor)
        self.assertEqual(len(before), 12)
        result = self.migrate()
        self.assertEqual(result['status'], 'migrated', result)
        self.assertEqual(sorted(snapshot(self.monitor)), ['chart01.chr'], 'T3 12 -> 1')
        self.assertEqual(self.chart.read_bytes(), before['chart01.chr'], 'the monitor chart is kept byte for byte')
        self.assertEqual(len(result['moved']), 11)
        for item in result['moved']:
            self.assertEqual(Path(item['to_path']).read_bytes(), charts[item['file']], 'moved aside, never deleted')
        self.assertEqual({i['file']: i['sha256'] for i in result['before']}, {k: digest(v) for k, v in before.items()})
        self.assertEqual([i['file'] for i in result['after']], ['chart01.chr'])
        self.assertEqual(result['kept']['sha256'], digest(before['chart01.chr']))
        self.assertEqual(result['batch_history']['symbols'], ['EURUSD', 'GBPJPY', 'GBPUSD'])
        manifest = json.loads((Path(result['move_aside_folder']).parent/'manifest.json').read_text())
        self.assertEqual((manifest['before_sha256'], manifest['after_sha256']), (result['before_sha256'], result['after_sha256']))
        # One-time: recorded, never run again.
        self.assertEqual(self.migrate()['status'], 'already')
        # The profile now fails only on the DLL permission (no fix-B record yet), never on structure.
        with self.assertRaises(Refusal) as caught:
            monitor_launch(self.c, 'after-migration')
        self.assertEqual(caught.exception.fields['failed_checks'], ['permissions'])

    def test_t3_shape_refuses_untouched_when_its_bare_eurusd_charts_predate_batch_history(self):
        self.t3_shape()
        self.history(['GBPJPY', 'GBPUSD'])      # EURUSD was never tested by a batch: its H1 charts were a person's
        before = snapshot(self.monitor)
        result = self.migrate()
        self.assertEqual(result['status'], 'refused')
        self.assertEqual({r['check'] for r in result['reasons']}, {'symbol_not_in_batch_history'})
        self.assertEqual(sorted(r['file'] for r in result['reasons']), ['chart02.chr', 'chart03.chr'])
        self.assertIn('EURUSD', result['plain'])
        self.assertIn('Nothing in the monitor profile was moved', result['plain'])
        self.assert_untouched(before)
        journal = (self.c.root/rp.STATE_FOLDER/rp.MIGRATION_JOURNAL).read_text().splitlines()
        self.assertEqual(json.loads(journal[-1])['status'], 'refused')
        # A prepared batch that never started is not batch history either.
        self.history(['EURUSD'], kind='catchups', run='never-started', started=False)
        self.assertEqual(self.migrate()['status'], 'refused')
        self.native_history([('pending-eurusd', ['EURUSD'], False)])
        self.assertEqual(self.migrate()['status'], 'refused')
        self.assert_untouched(before)

    def test_banker_shape_leaves_only_the_monitor_chart(self):
        names = dict(zip(['chart02.chr', 'chart03.chr', 'chart04.chr', 'chart05.chr', 'chart06.chr'],
                         ['USDJPY', 'AUDUSD', 'EURUSD', 'EURGBP', 'WS30']))
        self.pollute({name: bare_chart(symbol) for name, symbol in names.items()})
        self.history(['USDJPY', 'AUDUSD'], kind='catchups', run='cu-1')
        self.history(['EURGBP'], kind='holdups', run='h-1')
        self.history(['WS30'], kind='seeds', run='ws30-hunt')
        self.native_history([('g17', ['EURUSD', 'GBPUSD'], True)])
        monitor = self.chart.read_bytes()
        result = self.migrate()
        self.assertEqual(result['status'], 'migrated', result)
        self.assertEqual(sorted(snapshot(self.monitor)), ['chart01.chr'], 'Banker 6 -> 1')
        self.assertEqual(self.chart.read_bytes(), monitor)
        self.assertEqual(result['batch_history']['runs'], dict(native=1, seed=1, catchup=1, holdup=1))

    def test_a_person_added_chart_with_another_ea_refuses_and_nothing_moves(self):
        self.pollute({'chart02.chr': bare_chart('GBPJPY'), 'chart03.chr': expert_chart('GBPJPY')})
        self.history(['GBPJPY'])
        before = snapshot(self.monitor)
        result = self.migrate()
        self.assertEqual(result['status'], 'refused')
        self.assertEqual([r['check'] for r in result['reasons']], ['chart_with_program'])
        self.assertIn('MACD Sample', result['plain'])
        self.assert_untouched(before)

    def test_anything_unexpected_refuses_and_nothing_moves(self):
        self.history(['GBPJPY'])
        cases = {
            'a monitor chart without the GOAT EA': dict(monitor=bare_chart('EURUSD')),
            'a file MT5 does not save there': dict(charts={'notes.txt': b'hello'}),
            'an unreadable chart': dict(charts={'chart02.chr': chr_bytes('<chart>\nsymbol=GBPJPY\n<window>\n</chart>\n')}),
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                monitor = self.chart.read_bytes()
                self.pollute(dict(case.get('charts', {}), **{'chart09.chr': bare_chart('GBPJPY')}), monitor=case.get('monitor'))
                before = snapshot(self.monitor)
                self.assertEqual(self.migrate()['status'], 'refused')
                self.assert_untouched(before)
                for extra in list(case.get('charts', {}))+['chart09.chr']:
                    (self.monitor/extra).unlink()
                self.chart.write_bytes(monitor)

    def test_the_migration_runs_only_with_mt5_stopped(self):
        self.pollute({'chart02.chr': bare_chart('GBPJPY')})
        self.history(['GBPJPY'])
        before = snapshot(self.monitor)
        result = self.migrate(running=dict(pid=5))
        self.assertEqual((result['status'], result['reasons'][0]['check']), ('refused', 'terminal_running'))
        self.assert_untouched(before)

    def test_a_clean_profile_is_recorded_once(self):
        self.assertEqual(self.migrate()['status'], 'clean')
        self.assertTrue(rp.migration_done(self.c))
        self.assertEqual(self.migrate()['status'], 'already')


class PrepareTests(ResearchCase):
    def test_goat_research_is_moved_aside_whole_and_recreated_with_the_monitor_chart(self):
        folder = rp.research_folder(self.c)
        folder.mkdir()
        old = {'chart01.chr': bare_chart('EURUSD'), 'chart02.chr': bare_chart('GBPJPY'), 'order.wnd': b'mt5 order'}
        for name, raw in old.items():
            (folder/name).write_bytes(raw)
        result = rp.prepare(self.c, 'batch-1', inspect=lambda: None)
        expected = monitor_chart(self.c, 'EURUSD')
        self.assertEqual(snapshot(folder), {'chart01.chr': expected}, 'one chart: the monitor chart bytes, expertmode=0')
        self.assertIn('expertmode=0', expected.decode('utf-16'))
        self.assertEqual((result['chart_symbol'], result['chart_symbol_source'], result['chart_sha256']),
                         ('EURUSD', 'monitor_profile', digest(expected)))
        aside = Path(result['moved_aside']['to_path'])
        self.assertEqual(snapshot(aside), old, 'the previous GOAT Research is kept whole, never deleted')
        self.assertTrue(aside.is_relative_to(self.c.root/rp.STATE_FOLDER))
        self.assertEqual({f['path']: f['sha256'] for f in result['moved_aside']['files']}, {k: digest(v) for k, v in old.items()})
        manifest = json.loads(Path(result['manifest_path']).read_text())
        self.assertEqual(manifest['moved_aside']['files'], result['moved_aside']['files'])
        # Reset every batch: the next prepare moves this one aside into its own record folder.
        again = rp.prepare(self.c, 'batch-1', inspect=lambda: None)
        self.assertNotEqual(Path(again['manifest_path']).parent, Path(result['manifest_path']).parent)
        self.assertEqual(snapshot(Path(again['moved_aside']['to_path'])), {'chart01.chr': expected})

    def test_nothing_is_prepared_while_mt5_runs_or_when_goat_research_is_not_a_plain_folder(self):
        folder = rp.research_folder(self.c)
        folder.mkdir(); (folder/'chart01.chr').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'MT5 is running'):
            rp.prepare(self.c, 'running', inspect=lambda: dict(pid=1))
        self.assertEqual(snapshot(folder), {'chart01.chr': b'keep'})
        (folder/'chart01.chr').unlink(); folder.rmdir(); folder.write_bytes(b'a file')
        with self.assertRaisesRegex(ValueError, 'not a plain folder'):
            rp.prepare(self.c, 'file', inspect=lambda: None)
        self.assertEqual(folder.read_bytes(), b'a file')

    def test_a_move_across_volumes_copies_verifies_then_moves(self):
        folder = rp.research_folder(self.c)
        folder.mkdir(); (folder/'chart01.chr').write_bytes(bare_chart('GBPUSD'))
        real = os.replace
        def cross_volume(source, target):
            if Path(source).is_dir():
                raise OSError(errno.EXDEV, 'not the same device')
            return real(source, target)
        with patch('studio_research_profile.os.replace', side_effect=cross_volume):
            result = rp.prepare(self.c, 'cross', inspect=lambda: None)
        self.assertEqual(snapshot(Path(result['moved_aside']['to_path'])), {'chart01.chr': bare_chart('GBPUSD')})
        self.assertEqual(sorted(snapshot(folder)), ['chart01.chr'])

    def test_without_a_monitor_receipt_the_first_member_symbol_is_used(self):
        (self.c.root/'monitor-profile.json').rename(self.c.root/'monitor-profile.kept')
        result = rp.prepare(self.c, 'fallback', inspect=lambda: None, fallback_symbol='WS30')
        self.assertEqual((result['chart_symbol'], result['chart_symbol_source']), ('WS30', 'first_member'))
        with self.assertRaisesRegex(ValueError, 'No monitor profile receipt'):
            rp.prepare(self.c, 'nothing', inspect=lambda: None)


class RestoreTests(ResearchCase):
    def restore(self, running=None):
        return rp.restore(self.c, 'test', inspect=lambda: running)

    def test_one_line_profile_last_edit_back_to_the_monitor_profile(self):
        for encoding in ('utf-16', 'utf-8'):
            with self.subTest(encoding=encoding):
                self.set_profile_last('GOAT Research', encoding)
                raw = self.common_ini.read_bytes()
                result = self.restore()
                self.assertEqual(result['status'], 'restored', result)
                after = self.common_ini.read_bytes()
                self.assertEqual(after, raw.replace('ProfileLast=GOAT Research'.encode(encoding).removeprefix(b'\xff\xfe'),
                                                    ('ProfileLast='+self.monitor.name).encode(encoding).removeprefix(b'\xff\xfe')),
                                 'only the ProfileLast value changed')
                self.assertEqual(Path(result['common_ini_before']).read_bytes(), raw, 'before bytes kept')
                self.assertEqual(Path(result['common_ini_after']).read_bytes(), after, 'after bytes kept')
                self.assertEqual((result['common_ini_before_sha256'], result['common_ini_after_sha256']), (digest(raw), digest(after)))
                self.assertEqual(self.restore()['status'], 'not_needed')

    def test_never_while_mt5_runs_a_batch_is_active_or_another_profile_is_named(self):
        self.set_profile_last('GOAT Research')
        raw = self.common_ini.read_bytes()
        self.assertEqual(self.restore(running=dict(pid=9))['reason'], 'terminal_running')
        (self.c.root/'seed-active.json').write_text(json.dumps(dict(status='active', batch_id='x')))
        self.assertEqual(self.restore()['reason'], 'seed_slot_active')
        (self.c.root/'seed-active.json').write_text(json.dumps(dict(status='released', batch_id='x')))
        self.native_history([('running-batch', ['EURUSD'], True)])
        jobs = [dict(job_id='running-batch', status='running')]
        self.set_queue(jobs)
        self.assertEqual(self.restore()['reason'], 'native_batch_active')
        self.set_queue([])
        self.assertEqual(self.common_ini.read_bytes(), raw, 'nothing was edited while refused')
        for other in ('Default', 'GOAT-Deploy-1'):
            self.set_profile_last(other)
            raw = self.common_ini.read_bytes()
            result = self.restore()
            self.assertEqual((result['status'], result['reason'], result['profile_last']), ('not_restored', 'profile_last_not_research', other))
            self.assertEqual(self.common_ini.read_bytes(), raw)


class StartupShapeTests(unittest.TestCase):
    def material(self, profile, startup):
        return dict(sections={'Charts': {'ProfileLast': profile}, 'Experts': {'Enabled': '0', 'AllowLiveTrading': '0'},
                              'Tester': dict(UseLocal='1', UseRemote='0', UseCloud='0', Visual='0', ReplaceReport='0', ShutdownTerminal='0',
                                             Leverage='1:100', Symbol='GBPJPY', Period='H1',
                                             Report='MQL5\\Files\\GOAT\\R1\\reports\\main.xml'),
                              'TesterInputs': {}},
                    paste_inputs={'EA_Desc': 'R1'}, manifest=dict(native_run_relative='GOAT\\R1', campaign_id='c'),
                    plan=dict(research_binding=dict(research_profile=profile)), startup_monitor=startup)

    def test_goat_research_first_launch_has_the_monitor_launch_shape(self):
        startup = dict(Expert='GOAT-EA\\GOAT V1.49.ex5', ExpertParameters='GOAT Studio Agent.set', Period='M1')
        raw, receipt = startup_config(self.material('GOAT Research', startup))
        sections = ini_sections(raw)
        self.assertEqual(sections['Charts'], {'ProfileLast': 'GOAT Research'})
        self.assertEqual(sections['StartUp'], startup, 'Expert + ExpertParameters + Period=M1, no Symbol')
        self.assertEqual(receipt['sha256'], digest(raw))
        for profile, changed in (('GOAT-Studio-'+'a'*32, {}), ('GOAT Research', dict(Period='H1'))):
            with self.subTest(profile=profile, changed=changed), self.assertRaisesRegex(ValueError, 'GOAT Research profile'):
                startup_config(self.material(profile, dict(startup, **changed)))
        legacy = dict(startup, Symbol='GBPJPY', Period='H1')
        self.assertEqual(ini_sections(startup_config(self.material('GOAT Research', legacy))[0])['StartUp'], legacy)

    def test_a_real_goat_research_package_launches_without_a_startup_symbol(self):
        from test_studio_native_batch import NativeBatchTests
        from prepare_native_campaign import prepare as package_prepare, native_run_relative
        from studio_native_request import _validate_material
        fixture = NativeBatchTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        c = fixture.c; plan = copy.deepcopy(fixture.plan)
        preset = Path(plan['research_binding']['research_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        preset.parent.mkdir(parents=True, exist_ok=True)
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))
        plan['research_binding'].update(research_profile='GOAT Research', report_location_bridge='installation_to_data_v1',
                                        startup_monitor=dict(expert=plan['research_binding']['ea_relative_path'], preset=preset.name,
                                                             preset_sha256=digest(preset.read_bytes())))
        plan['native_batch']['run_relative'] = native_run_relative(plan)
        plan_path = c.root/'config-plan.json'; plan_path.write_text(json.dumps(plan))
        package = c.root/'packages/config-route'
        package_prepare(plan_path, c.root/'templates.sqlite', package)
        (package/'studio-plan.json').write_text(json.dumps(plan))
        job = c.job('beta-job'); job['launch_intent'].update(package=str(package), package_sha256=digest((package/'manifest.json').read_bytes()))
        args = c.native_args(); args.pop('observation_path')
        sections = ini_sections(_validate_material(c.state(), job, **args)['startup_raw'])
        self.assertEqual(sections['Charts'], {'ProfileLast': 'GOAT Research'})
        self.assertEqual(sections['StartUp'], dict(Expert=plan['research_binding']['ea_relative_path'], ExpertParameters=preset.name, Period='M1'))


class MemberIniTests(unittest.TestCase):
    """Seed, catch-up and hold-up members run MT5 on GOAT Research: [Charts] ProfileLast=GOAT Research."""

    def charts(self, member):
        return ini_sections(Path(member['config_path']).read_bytes()).get('Charts')

    def test_seed_catchup_and_holdup_member_inis_name_goat_research(self):
        import test_studio_seed as seeds
        import test_studio_catchup as catchups
        import test_studio_holdup as holdups
        s = seeds.SeedTests('test_matrix_complete_with_exact_candidate_values'); s.setUp(); self.addCleanup(s.tearDown)
        s.prepare()
        self.assertEqual(self.charts(s.member()), {'ProfileLast': 'GOAT Research'})
        n = catchups.NativeCycleTests('test_full_cycle_moves_the_retest_and_judges_the_new_weeks'); n.setUp(); self.addCleanup(n.tearDown); self.addCleanup(n.doCleanups)
        n.runner.prepare('cu1', n.plan())
        for member in json.loads((n.runner.path('cu1')/'manifest.json').read_text())['members']:
            self.assertEqual(self.charts(member), {'ProfileLast': 'GOAT Research'})
        h = holdups.HoldupTests('test_prepare_freezes_exact_bytes_and_one_single_pass_config'); h.setUp(); self.addCleanup(h.doCleanups)
        h.runner.prepare('h1', h.plan())
        member = json.loads((h.runner.path('h1')/'manifest.json').read_text())['members'][0]
        self.assertEqual(self.charts(member), {'ProfileLast': 'GOAT Research'})

    def test_a_seed_prepared_before_goat_research_is_refused_at_start_before_the_monitor_closes(self):
        import test_studio_seed as seeds
        s = seeds.SeedTests('test_matrix_complete_with_exact_candidate_values'); s.setUp(); self.addCleanup(s.tearDown)
        s.prepare()
        root = s.runner.path('batch')
        manifest = json.loads((root/'manifest.json').read_text())
        for member in manifest['members']:
            legacy = Path(member['config_path']).read_bytes().decode('utf-16').replace('[Charts]\r\nProfileLast=GOAT Research\r\n', '')
            Path(member['config_path']).write_bytes(legacy.encode('utf-16'))
            member['config_sha256'] = digest(Path(member['config_path']).read_bytes())
        (root/'manifest.json').write_text(json.dumps(manifest))
        state = json.loads((root/'state.json').read_text()); state['manifest_sha256'] = digest((root/'manifest.json').read_bytes())
        (root/'state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'Seed hunt batch: .*GOAT Research chart profile.*new batch ID'):
            s.runner.start('batch', 10)
        self.assertEqual((s.closes, s.starts), ([], []), 'refused before the monitor closed')


class FixBInteractionTests(ResearchCase):
    """Fix B (GOAT-EA#222) is unchanged: a two-chart monitor profile is never recorded."""

    def setUp(self):
        super().setUp()
        self.p.fixture.observe()
        self.session, self.state = session_state(self.c)
        self.identity = dict(self.p.identity)

    def test_record_post_close_chart_and_pre_close_health_on_a_two_chart_monitor_profile(self):
        self.pollute({'chart02.chr': bare_chart('GBPJPY')})
        health = pre_close_health(self.c, self.session, self.state, self.p.native(), self.identity)
        self.assertEqual((health['healthy'], health['reason'], health['failed_checks']), (False, MONITOR_PROFILE_REFUSAL, ['extra_charts']))
        terminal = preserved.FakeTerminal(None)
        record = record_post_close_chart(self.c, health, attempt_id='two-charts', method='test', stopped_utc='now', process=terminal)
        self.assertEqual((record['status'], record['pre_close_failed_checks']), ('not_recorded', ['extra_charts']))
        # A healthy read from a one-chart profile, then a second chart appears before the record: still not recorded.
        (self.monitor/'chart02.chr').unlink()
        healthy = pre_close_health(self.c, self.session, self.state, self.p.native(), self.identity)
        self.assertTrue(healthy['healthy'], healthy)
        self.pollute({'chart02.chr': bare_chart('GBPJPY')})
        self.p.mt5_saves_on_close(None)
        record = record_post_close_chart(self.c, healthy, attempt_id='two-charts-2', method='test', stopped_utc='now', process=terminal)
        self.assertEqual((record['status'], record['reason'], record['failed_checks']), ('not_recorded', MONITOR_PROFILE_REFUSAL, ['extra_charts']))
        self.assertFalse((self.c.root/HEALTHY_CHART_RECORD).exists())

    def test_the_first_close_before_the_migration_records_only_after_it_really_moved_the_charts(self):
        self.pollute({'chart02.chr': bare_chart('GBPJPY'), 'chart03.chr': bare_chart('GBPJPY')})
        self.history(['GBPJPY'])
        aside = rp.pending_set_aside(self.c)
        self.assertEqual(aside, ('chart02.chr', 'chart03.chr'))
        health = pre_close_health(self.c, self.session, self.state, self.p.native(), self.identity, set_aside=aside)
        self.assertTrue(health['healthy'], health)
        self.assertEqual(health['set_aside_by_migration'], ['chart02.chr', 'chart03.chr'])
        self.p.mt5_saves_on_close(None)
        terminal = preserved.FakeTerminal(None)
        record = record_post_close_chart(self.c, health, attempt_id='before-migration', method='test', stopped_utc='now', process=terminal)
        self.assertEqual((record['status'], record['failed_checks']), ('not_recorded', ['extra_charts']), 'the record reads the real folder')
        self.assertEqual(self.migrate()['status'], 'migrated')
        record = record_post_close_chart(self.c, health, attempt_id='after-migration', method='test', stopped_utc='now', process=terminal)
        self.assertEqual(record['status'], 'recorded', record)
        self.assertEqual(rp.pending_set_aside(self.c), (), 'nothing is set aside once the migration ran')


class WordingTests(ResearchCase):
    def test_goat_research_as_saved_profile_never_sends_the_user_to_file_profiles(self):
        self.set_profile_last('GOAT Research')
        step = next(s for s in onboarding_status(self.c)['steps'] if s['id'] == 'native_monitor')
        self.assertEqual(step['state'], 'blocked')
        self.assertIn('GOAT Research', step['action'])
        self.assertNotIn('File > Profiles', step['action'])
        self.set_profile_last('Default')
        step = next(s for s in onboarding_status(self.c)['steps'] if s['id'] == 'native_monitor')
        self.assertIn('File > Profiles > '+self.monitor.name, step['action'], 'a person-selected profile keeps its step')

    def test_restart_recovery_never_asks_for_a_profile_choice(self):
        for phase in ('prepared', 'controls_installed', 'close_issued', 'research_exited', 'launch_issued', 'process_started_unverified'):
            with self.subTest(phase=phase):
                answer = restart_recovery(dict(restart_intent=dict(phase=phase)))
                self.assertNotRegex(answer['next_safe_action'], r'choose File > Profiles')

    def test_seed_restore_hint_never_asks_for_a_profile_choice(self):
        from studio_seed import SeedRunner
        runner = SeedRunner(SimpleNamespace(root=self.c.root, local=self.c.local, session=self.c.session), process=SimpleNamespace())
        hint = runner._restore_hint(dict(status='completed', generation=1))
        self.assertNotIn('File > Profiles', hint['next_action'])
        self.assertIn('GOAT Research', hint['next_action'])


class EndStateTests(ResearchCase):
    """The config-start end state's refusals (its success path runs in IntegrationTests)."""

    def setUp(self):
        super().setUp()
        self.p.fixture.observe()
        self.mt5 = FixtureMT5(self.data, identity=dict(pid=70, executable='terminal64.exe', created_utc='x'), profile='GOAT Research')
        self.record = dict(attempt_id='b'*64, mt5_restart_consent=dict(granted=True, scope=RESTART_CONSENT_SCOPE))

    def native(self, **changes):
        return dict(dict(process=self.mt5.inspect(), account_matches=True, demo=True, connected=True, algo_trading=False, positions=0,
                         orders=0, tester_state='idle'), **changes)

    def end(self, record=None, inspect=None):
        return rp.batch_end_state(self.c, 'batch', record or self.record, process=self.mt5, inspect=inspect or (lambda c: self.native()))

    def test_a_monitor_that_cannot_be_reopened_leaves_mt5_open_with_the_plain_reason(self):
        self.p.save(self.p.chart_bytes())          # DLL approved (expertmode=4) and no fix-B record
        result = self.end()
        self.assertEqual((result['status'], result['reason'], result['failed_checks']), ('left_as_is', 'monitor_not_launchable', ['permissions']))
        self.assertIn('GOAT Research', result['plain'])
        self.assertEqual(self.mt5.closes, [], 'MT5 was not closed')
        self.p.start.assert_not_called()

    def test_the_closes_own_checks_refuse_and_nothing_is_launched(self):
        def algo_on(c):
            raise ValueError('Repair requires a connected demo, Algo Trading off and no positions/orders')
        result = self.end(inspect=algo_on)
        self.assertEqual((result['status'], result['reason']), ('left_as_is', 'close_refused'))
        self.assertEqual(self.mt5.closes, [])
        self.p.start.assert_not_called()

    def test_a_consent_without_the_end_scope_or_another_lane_never_closes(self):
        old = dict(self.record, mt5_restart_consent=dict(granted=True, scope='close_and_reopen_selected_mt5_for_this_batch_start'))
        self.assertEqual(self.end(record=old)['reason'], 'consent_scope')
        self.c.session['authority_kind'] = 'research_continuation'
        self.assertEqual(self.end()['status'], 'not_applicable')
        self.assertEqual(self.mt5.closes, [])
        self.p.start.assert_not_called()


class IntegrationTests(ResearchCase):
    """A fixture MT5 that opens the profile its INI (or common.ini) names, adds the tested symbol's bare chart there and
    saves into it on close. Across a config start (with the finish's close + monitor-launch), a seed hunt and a catch-up,
    the monitor profile's bytes never change after GOAT's first close except for the migration's move-aside, stray
    charts land only in GOAT Research, and the post-batch monitor-launch is accepted through the fix-B record."""

    def setUp(self):
        super().setUp()
        self.running = self.p.save(self.p.chart_bytes(scale='8'))      # the monitor runs with DLL imports approved
        self.strays = {'chart02.chr': bare_chart('EURUSD', moving_averages=2), 'chart03.chr': bare_chart('GBPJPY')}
        self.pollute(self.strays)                                        # left by earlier batches on the monitor profile
        self.history(['EURUSD', 'GBPJPY'])
        self.set_profile_last(self.monitor.name)
        import studio_onboarding
        self.real_health, self.real_record = studio_onboarding.driver_pre_close_health, studio_onboarding.record_post_close_chart
        self.health_kw = []

    def routed(self, *, batch_ongoing):
        """The drivers' health read and record run for real on this bound controller (as DriverFirstCloseTests does)."""
        self.p.fixture.observe()
        sample = json.loads((self.c.local/'ui-observation.json').read_text())['runtime']
        self.p.fixture.observe(runtime=dict(sample, batch_ongoing=batch_ongoing))
        def health(c, current, **kw):
            self.health_kw.append(sorted(kw))
            kw = dict(kw, native=self.p.native(), sdk_read=None, set_aside=rp.pending_set_aside(self.c))
            return self.real_health(self.c, dict(self.p.identity), **kw)
        return patch.multiple('studio_onboarding', driver_pre_close_health=health,
                              record_post_close_chart=lambda c, h, **kw: self.real_record(self.c, h, **kw))

    def popen_to(self, mt5):
        self.p.start.side_effect = lambda arguments, **kw: SimpleNamespace(pid=mt5.start(arguments[1].removeprefix('/config:'))['pid'])

    def assert_after_batch(self, mt5, monitor_after_first_close, record_sha):
        self.assertEqual(snapshot(self.monitor), monitor_after_first_close, 'the monitor profile never changed during the batch')
        self.assertEqual(sorted(snapshot(self.monitor)), ['chart01.chr'])
        self.assertEqual(digest(self.chart.read_bytes()), record_sha, 'the recorded post-close chart')
        moved = json.loads((self.c.root/rp.STATE_FOLDER/rp.MIGRATION_RECORD).read_text())['moved']
        self.assertEqual(sorted(m['file'] for m in moved), ['chart02.chr', 'chart03.chr'], 'only the migration moved anything')
        research = snapshot(rp.research_folder(self.c))
        self.assertGreater(len(research), 1, 'the tested symbols\' bare charts landed in GOAT Research')
        for name, raw in research.items():
            if name != 'chart01.chr':
                self.assertIn('id=0', raw.decode('utf-16'))
        self.assertEqual([p for p in mt5.opened[1:-1]], ['GOAT Research']*(len(mt5.opened)-2), 'every batch launch opened GOAT Research')
        self.assertEqual(mt5.opened[-1], self.monitor.name, 'the post-batch monitor-launch opened the monitor profile')

    def test_config_start_batch_ends_back_on_the_monitor_with_no_human_step(self):
        import test_studio_tester_config_start as tester
        cfg = tester.CustomerConfigStartTests('test_one_arm_close_config_launch_and_retained_phases')
        cfg.setUp(); self.addCleanup(cfg.doCleanups)
        mt5 = FixtureMT5(self.data, identity=cfg.identity, profile=self.monitor.name)
        cfg.process.inspect.side_effect = mt5.inspect
        cfg.process.close.side_effect = mt5.close
        cfg.process.start.side_effect = mt5.start
        material = dict(StartupShapeTests().material('GOAT Research', dict(Expert=self.c.install['ea_relative_path'],
                                                     ExpertParameters='GOAT Studio Agent.set', Period='M1')))
        raw, receipt = startup_config(material)
        cfg.material.update(startup_raw=raw, startup_receipt=receipt)
        cfg.mocks['_migrate'].side_effect = lambda c, attempt, process: rp.migrate_monitor_profile(self.c, 'config-start-'+attempt, inspect=process.inspect)
        cfg.mocks['_research_profile'].side_effect = lambda c, attempt, process: rp.prepare(self.c, 'config-start-'+attempt, inspect=process.inspect)
        with self.routed(batch_ongoing=True):
            started = cfg.run_start()
        self.assertEqual(self.health_kw[0][-1], 'set_aside', 'the start passes the migration\'s set-aside charts')
        self.assertEqual(started['monitor_profile_migration']['status'], 'migrated')
        self.assertEqual(started['monitor_chart_record']['status'], 'recorded', started['monitor_chart_record'])
        monitor_after_first_close = snapshot(self.monitor)
        record_sha = started['monitor_chart_record']['chart_sha256']
        self.assertEqual(mt5.starts[0][1:], ('GOAT Research', 'GBPJPY'))
        # The EA's own member relaunch: TerminalClose, then a [Tester]-only /config (MT5 reopens its saved profile).
        member = self.c.root/'member-2.ini'
        member.write_bytes('[Tester]\r\nSymbol=GBPUSD\r\nPeriod=H1\r\n[TesterInputs]\r\nEA_Desc=R2\r\n'.encode('utf-16'))
        mt5.exit(); mt5.start(member)
        self.assertEqual(mt5.starts[-1][1:], ('GOAT Research', 'GBPUSD'))
        # The batch driver's finish: the end state (Mac option (i)).
        self.popen_to(mt5)
        self.p.fixture.observe()
        end = rp.batch_end_state(self.c, 'batch', dict(attempt_id=cfg.attempt, mt5_restart_consent=dict(granted=True, scope=RESTART_CONSENT_SCOPE)),
                                 process=mt5, inspect=lambda c: dict(process=mt5.inspect(), account_matches=True, demo=True, connected=True,
                                                                     algo_trading=False, positions=0, orders=0, tester_state='idle'))
        self.assertEqual(end['status'], 'monitor_relaunched', end)
        self.assertEqual(end['close']['phase'], 'stopped')
        self.assertEqual(end['close']['monitor_chart_record']['reason'], 'foreign_profile', 'a GOAT Research close never records')
        self.assertEqual(end['restore']['status'], 'restored')
        self.assertEqual(end['launch']['observed_healthy_chart']['chart_sha256'], record_sha, 'accepted through the fix-B record, no click')
        self.assertEqual(len(mt5.closes), 2, 'the start close and the one end close')
        self.assert_after_batch(mt5, monitor_after_first_close, record_sha)

    def seed_runner(self, mt5):
        import test_studio_seed as seeds
        from studio_seed import SeedRunner
        s = seeds.SeedTests('test_matrix_complete_with_exact_candidate_values')
        s.setUp(); self.addCleanup(s.tearDown)
        c = s.controller
        c.root, c.local, c.install, c.session = self.c.root, self.c.local, self.c.install, dict(self.c.session)
        first = s.plan['jobs'][0]
        first['tester']['Expert'] = self.c.install['ea_relative_path']
        second = copy.deepcopy(first); second['tester']['Symbol'] = 'GBPUSD'; s.plan['jobs'].append(second)
        def sleep(seconds):
            s.now += seconds
            if mt5.running and mt5.starts:
                manifest = json.loads((runner.path('batch')/'manifest.json').read_text())
                s.output(manifest['members'][len(mt5.starts)-1])
                mt5.exit()                                  # ShutdownTerminal=1 after the member's single test
        runner = SeedRunner(c, process=mt5, clock=lambda: s.now, sleep=sleep)
        runner.prepare('batch', s.plan)
        return runner

    def test_seed_hunt_runs_on_goat_research_and_restores_the_monitor_profile(self):
        mt5 = FixtureMT5(self.data, identity=dict(pid=10, executable='terminal64.exe', created_utc='first'), profile=self.monitor.name)
        runner = self.seed_runner(mt5)
        with self.routed(batch_ongoing=False):
            state = runner.start('batch', 30)
        self.assertEqual(state['status'], 'completed', state)
        self.assertEqual(state['monitor_profile_migration']['status'], 'migrated')
        self.assertEqual(state['monitor_chart_record']['status'], 'recorded', state['monitor_chart_record'])
        self.assertEqual(state['research_profile']['chart_symbol'], 'EURUSD')
        self.assertEqual(state['research_profile_restore']['status'], 'restored', state['research_profile_restore'])
        self.assertEqual([s[1:] for s in mt5.starts], [('GOAT Research', 'EURUSD'), ('GOAT Research', 'GBPUSD')])
        self.assertEqual(mt5.saved_profile(), self.monitor.name, 'ProfileLast is back on the monitor profile')
        monitor_after = snapshot(self.monitor)
        self.popen_to(mt5)
        launch = monitor_launch(self.c, 'after-seed')
        self.assertEqual(launch['observed_healthy_chart']['chart_sha256'], state['monitor_chart_record']['chart_sha256'])
        self.assert_after_batch(mt5, monitor_after, state['monitor_chart_record']['chart_sha256'])

    def test_catchup_runs_on_goat_research_and_restores_the_monitor_profile(self):
        import test_studio_catchup as catchups
        from studio_catchup import CatchupRunner
        n = catchups.NativeCycleTests('test_full_cycle_moves_the_retest_and_judges_the_new_weeks')
        n.setUp(); self.addCleanup(n.tearDown); self.addCleanup(n.doCleanups)
        c = n.controller
        # This fixture's own installation (V1.49) with its own GOAT Studio monitor profile and saved MT5 settings.
        c.session = dict(c.session, run_id='session-'+'c'*32)
        name = 'GOAT-Studio-'+'c'*32
        data = Path(c.install['terminal_data_root'])
        monitor = data/'MQL5/Profiles/Charts'/name
        monitor.mkdir(parents=True)
        (monitor/'chart01.chr').write_bytes(monitor_chart(c, 'EURUSD'))
        (c.root/'monitor-profile.json').write_text(json.dumps(dict(symbol='EURUSD', profile_name=name)))
        mt5 = FixtureMT5(data, identity=dict(pid=10, executable='terminal64.exe', created_utc='monitor'), profile=name, login='123', server='Test-Demo')
        mt5.exit(); mt5.running = dict(pid=10, executable='terminal64.exe', created_utc='monitor')   # saved settings, monitor open
        monitor_after_first_close = None
        def sleep(seconds):
            n.now += seconds
            if mt5.running and mt5.starts:
                manifest = json.loads((runner.path('cu1')/'manifest.json').read_text())
                n.native_retest(manifest['members'][len(mt5.starts)-1])
                mt5.exit()
        runner = CatchupRunner(c, process=mt5, clock=lambda: n.now, sleep=sleep, now=catchups.AFTER_CLOSE)
        runner.prepare('cu1', n.plan())
        state = runner.start('cu1', 60)
        self.assertEqual(state['status'], 'completed', state.get('stopped_reason') or state)
        self.assertEqual(state['research_profile_restore']['status'], 'restored', state['research_profile_restore'])
        self.assertEqual(state['monitor_profile_migration']['status'], 'clean')
        self.assertTrue(all(profile == 'GOAT Research' for _, profile, _ in mt5.starts), mt5.starts)
        self.assertEqual(len(mt5.starts), 2)
        self.assertEqual(mt5.saved_profile(), name)
        monitor_after_first_close = {'chart01.chr': re.sub(r'(?m)^scale=\d+', 'scale=4', monitor_chart(c, 'EURUSD').decode('utf-16')).encode('utf-16')}
        self.assertEqual(snapshot(monitor), monitor_after_first_close, 'only GOAT\'s first close saved the monitor profile')
        research = snapshot(data/'MQL5/Profiles/Charts/GOAT Research')
        self.assertEqual(len(research), 1+len(mt5.starts), 'every tested symbol\'s bare chart landed in GOAT Research')

    def test_negative_control_a_member_without_charts_section_pollutes_the_monitor_profile(self):
        # The fixture MT5 reproduces the bug: an INI that names no profile reopens common.ini's, the monitor profile.
        mt5 = FixtureMT5(self.data, identity=dict(pid=10, executable='terminal64.exe', created_utc='first'), profile=self.monitor.name)
        mt5.close(mt5.running)
        legacy = self.c.root/'legacy.ini'
        legacy.write_bytes('[Tester]\r\nSymbol=WS30\r\nShutdownTerminal=1\r\n'.encode('utf-16'))
        mt5.start(legacy); mt5.exit()
        added = [raw for name, raw in snapshot(self.monitor).items() if name not in ('chart01.chr', 'chart02.chr', 'chart03.chr')]
        self.assertEqual(len(added), 1)
        self.assertIn('symbol=WS30', added[0].decode('utf-16'))


if __name__ == '__main__':
    unittest.main()
