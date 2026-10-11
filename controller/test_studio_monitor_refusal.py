"""monitor-launch refusals name the exact failed check (Claude-Mac, goatai#2350 6095158688).

Fixture-only: no installed terminal is touched or launched. Each saved-monitor check refuses with one
plain sentence (what is wrong, the one step the person takes), the stable refusal code
MONITOR_PROFILE_CHANGED and ``failed_check``; several failed checks are each named. Nothing is repaired.
"""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio_onboarding import monitor_prepare, monitor_launch, verify_saved_monitor, MONITOR_PROFILE_REFUSAL
from studio_refusal import Refusal
import test_goat_studio as fixtures

EA = 'GOAT V1.48.ex5'
PRESET = 'in MT5, open the EA\'s settings on the monitor chart and load the GOAT Studio Agent preset on the Inputs tab.'
INDICATOR = 'The monitor chart has an indicator GOAT did not add; in MT5, remove it from the monitor chart (Charts > Indicators List).'


class MonitorLaunchRefusalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound()
        self.data = self.fixture.data
        patcher = patch('studio_onboarding.inspect_processes', return_value={
            'research': {'created_utc': '2020-01-01T00:00:00+00:00', 'pid': 55}})
        patcher.start(); self.addCleanup(patcher.stop)
        launch = patch('studio_onboarding.subprocess.Popen', return_value=SimpleNamespace(pid=42))
        self.start = launch.start(); self.addCleanup(launch.stop)
        (self.data/'origin.txt').write_text(str(self.fixture.bin.parent))
        (self.data/'config').mkdir()
        (self.data/'config/common.ini').write_text('[Common]\nLogin=123456\nServer=Customer-Demo\n[Experts]\nEnabled=0\n')
        prepared = monitor_prepare(self.c, 'EURUSD')
        self.name = prepared['profile_name']
        self.menu = 'File > Profiles > '+self.name
        self.folder = Path(prepared['profile_path'])
        self.chart = self.folder/'chart01.chr'
        self.original = self.chart.read_text(encoding='utf-16')

    def save(self, text):
        self.chart.write_text(text, encoding='utf-16')

    def refused(self, attempt='refused'):
        """The monitor-launch refusal; nothing was launched and the saved chart is untouched."""
        before = self.chart.read_bytes() if self.chart.exists() else None
        with self.assertRaises(Refusal) as caught:
            monitor_launch(self.c, attempt)
        refusal = caught.exception
        self.assertIsInstance(refusal, ValueError, 'still a refusal: the CLI top-level code stays REFUSED')
        self.assertEqual(refusal.code, MONITOR_PROFILE_REFUSAL)
        self.assertEqual(refusal.fields['monitor_profile'], self.name)
        self.assertEqual(refusal.fields['failed_check'], refusal.fields['failed_checks'][0])
        self.start.assert_not_called()
        if before is not None:
            self.assertEqual(self.chart.read_bytes(), before, 'never auto-fixed')
        return refusal

    def assertRefusal(self, refusal, check, sentence):
        self.assertEqual(str(refusal), sentence)
        self.assertEqual(refusal.fields['failed_check'], check)
        self.assertEqual(refusal.fields['failed_checks'], [check])

    # ---- the saved chart's EA, symbol, permissions, inputs and indicator

    def test_chart_permissions_changed(self):
        # The tester case: Allow Algo Trading changed on the chart, so MT5 saved expertmode=4 (GOAT requires 0).
        self.save(self.original.replace('expertmode=0', 'expertmode=4'))
        refusal = self.refused()
        self.assertRefusal(refusal, 'permissions',
            'The EA\'s chart permissions changed (Allow Algo Trading or DLL imports on the chart); '
            'reopen the saved monitor profile in MT5 yourself ('+self.menu+').')
        self.assertEqual(refusal.fields['observed'], {'expertmode': '4', 'required_expertmode': '0'})

    def test_symbol_changed(self):
        self.save(self.original.replace('symbol=EURUSD', 'symbol=GBPUSD'))
        refusal = self.refused()
        self.assertRefusal(refusal, 'symbol',
            'The monitor chart shows GBPUSD instead of EURUSD; in MT5, choose '+self.menu+' and switch that chart back to EURUSD.')
        self.assertEqual(refusal.fields['observed'], {'symbol': 'GBPUSD', 'required_symbol': 'EURUSD'})

    def test_ea_identity_or_build_changed(self):
        self.save(self.original.replace(EA, 'GOAT V1.47.ex5'))
        self.assertRefusal(self.refused(), 'ea_identity',
            'The monitor chart runs GOAT V1.47.ex5 instead of the installed '+EA+'; in MT5, choose '+self.menu+
            ' and attach '+EA+' to the monitor chart with the GOAT Studio Agent preset.')

    def test_inputs_changed(self):
        self.save(self.original.replace('Mode_Operation=11', 'Mode_Operation=8'))
        refusal = self.refused()
        self.assertRefusal(refusal, 'inputs',
            'The monitor EA\'s inputs changed (Mode_Operation is 8 but GOAT needs 11); '+PRESET)
        self.assertEqual(refusal.fields['observed']['inputs'],
                         {'Mode_Operation': '8', 'Studio_ReadOnlyMonitor': 'true', 'Studio_MonitorRunPath': ''})

    def test_every_changed_input_is_named(self):
        self.save(self.original.replace('Studio_ReadOnlyMonitor=true', 'Studio_ReadOnlyMonitor=false')
                  .replace('Studio_MonitorRunPath=', 'Studio_MonitorRunPath=GOAT/another'))
        self.assertRefusal(self.refused(), 'inputs',
            'The monitor EA\'s inputs changed (Studio_ReadOnlyMonitor is false but GOAT needs true, '
            'and Studio_MonitorRunPath is GOAT/another but GOAT needs it empty); '+PRESET)

    def test_input_listed_twice(self):
        self.save(self.original.replace('Mode_Operation=11', 'Mode_Operation=11\r\nMode_Operation=8'))
        self.assertRefusal(self.refused(), 'inputs_duplicated',
            'The monitor EA lists the input Mode_Operation more than once; '+PRESET)

    def test_inputs_missing(self):
        start = self.original.index('<inputs>'); end = self.original.index('</inputs>')+len('</inputs>')
        self.save(self.original[:start]+self.original[end:])
        self.assertRefusal(self.refused(), 'inputs_missing', 'The monitor EA\'s saved inputs are missing; '+PRESET)

    def test_ea_missing(self):
        start = self.original.index('<expert>'); end = self.original.index('</expert>')+len('</expert>')
        self.save(self.original[:start]+self.original[end:])
        self.assertRefusal(self.refused(), 'ea_missing',
            'The GOAT EA is no longer on the monitor chart; in MT5, choose '+self.menu+
            ' and attach '+EA+' to the monitor chart with the GOAT Studio Agent preset.')

    def test_more_than_one_ea(self):
        block = self.original[self.original.index('<expert>'):self.original.index('</expert>')+len('</expert>')]
        sentence = 'The monitor chart has more than one EA; in MT5, remove every EA except '+EA+' from the monitor chart.'
        for text in (self.original.replace('</expert>', '</expert>\r\n'+block),          # a second full EA block
                     self.original.replace('</expert>', '</expert>\r\n<expert>\r\n</expert>')):  # an empty one
            with self.subTest(text=text):
                self.save(text)
                self.assertRefusal(self.refused(), 'extra_ea', sentence)

    def test_unexpected_indicator(self):
        self.save(self.original.replace('name=Main', 'name=CustomIndicator'))
        refusal = self.refused()
        self.assertRefusal(refusal, 'indicator', INDICATOR)
        self.assertEqual(refusal.fields['observed'], {'indicator': 'CustomIndicator'})
        window = self.original[self.original.index('<window>'):self.original.index('</window>')+len('</window>')]
        self.save(self.original.replace('</window>', '</window>\r\n'+window))
        self.assertRefusal(self.refused(), 'indicator', INDICATOR)

    def test_chart_runs_a_script(self):
        self.save(self.original.replace('</expert>', '</expert>\r\n<script>\r\n</script>'))
        self.assertRefusal(self.refused(), 'chart_runs_script',
            'The monitor chart runs a script; in MT5, remove the script from the monitor chart.')

    def test_unreadable_chart_keeps_the_technical_detail(self):
        self.chart.write_bytes(b'MT5 changed saved profile')
        refusal = self.refused()
        self.assertRefusal(refusal, 'chart_unreadable',
            'The saved monitor chart file is damaged or not in MT5\'s chart format, so GOAT cannot check it; ask GOAT support to review it.')
        self.assertEqual(refusal.fields['observed'], {'detail': 'Invalid saved monitor chart content'})

    # ---- the saved profile folder

    def test_chart_missing(self):
        self.chart.unlink()
        self.assertRefusal(self.refused(), 'chart_missing',
            'The saved monitor profile '+self.name+' has no chart left (the monitor chart was closed in MT5); in MT5, choose '+
            self.menu+', open a EURUSD chart and attach '+EA+' with the GOAT Studio Agent preset.')

    def test_extra_charts(self):
        shutil.copyfile(self.chart, self.folder/'chart02.chr')
        self.assertRefusal(self.refused(), 'extra_charts',
            'The saved monitor profile '+self.name+' has 2 charts and GOAT needs exactly one; in MT5, choose '+
            self.menu+' and close every chart except the EURUSD monitor chart.')

    def test_extra_files(self):
        (self.folder/'notes.txt').write_text('fixture')
        refusal = self.refused()
        self.assertRefusal(refusal, 'extra_files',
            'The saved monitor profile folder holds items MT5 does not save there (notes.txt); move them out of '+str(self.folder)+'.')
        self.assertEqual(refusal.fields['observed'], {'unexpected_items': ['notes.txt']})

    def test_mt5_order_file_is_still_accepted(self):
        (self.folder/'order.wnd').write_bytes(b'fixture ordering')
        monitor_launch(self.c, 'with-order')
        self.start.assert_called_once()

    def test_chart_too_large(self):
        self.chart.write_bytes(b' '*2_000_001)
        self.assertRefusal(self.refused(), 'chart_too_large',
            'The saved monitor chart file is over 2 MB, far bigger than a monitor chart; ask GOAT support to review it.')

    def test_profile_missing(self):
        shutil.rmtree(self.folder)
        self.assertRefusal(self.refused(), 'profile_missing',
            'The saved monitor profile '+self.name+' is no longer in MT5; '
            'ask GOAT support to restore it, because GOAT never recreates a prepared profile on its own.')

    def test_profile_alias(self):
        moved = self.folder.with_name('moved-profile')
        self.folder.rename(moved)
        try:
            import _winapi
            _winapi.CreateJunction(str(moved), str(self.folder))
        except (ImportError, OSError):
            os.symlink(moved, self.folder, target_is_directory=True)
        self.addCleanup(lambda: os.rmdir(self.folder) if os.path.lexists(self.folder) else None)
        self.assertRefusal(self.refused(), 'profile_alias',
            'The saved monitor profile folder '+self.name+' is a link to another folder; '
            'ask GOAT support to review it, because GOAT never follows a link there.')

    def test_profile_of_another_installation_or_session(self):
        target = self.c.root/'monitor-profile.json'
        target.write_text(json.dumps(json.loads(target.read_text()) | dict(installation_sha256='f'*64)))
        self.assertRefusal(self.refused(), 'profile_other_session',
            'The saved monitor profile was prepared for another GOAT installation or session; '
            'ask GOAT support to review it, because GOAT never reuses it.')

    # ---- several failed checks, the CLI shape, and the human-reopen exception

    def test_several_failed_checks_are_each_named(self):
        self.save(self.original.replace('symbol=EURUSD', 'symbol=GBPUSD').replace('expertmode=0', 'expertmode=4')
                  .replace('Mode_Operation=11', 'Mode_Operation=8').replace('name=Main', 'name=CustomIndicator'))
        refusal = self.refused()
        self.assertEqual(refusal.fields['failed_check'], 'symbol')
        self.assertEqual(refusal.fields['failed_checks'], ['symbol', 'permissions', 'inputs', 'indicator'])
        self.assertEqual(str(refusal), ' '.join((
            'The monitor chart shows GBPUSD instead of EURUSD; in MT5, choose '+self.menu+' and switch that chart back to EURUSD.',
            'The EA\'s chart permissions changed (Allow Algo Trading or DLL imports on the chart); '
            'reopen the saved monitor profile in MT5 yourself ('+self.menu+').',
            'The monitor EA\'s inputs changed (Mode_Operation is 8 but GOAT needs 11); '+PRESET,
            INDICATOR)))

    def test_several_profile_folder_failures_are_each_named(self):
        self.chart.unlink(); (self.folder/'notes.txt').write_text('fixture')
        refusal = self.refused()
        self.assertEqual(refusal.fields['failed_checks'], ['chart_missing', 'extra_files'])
        self.assertIn('has no chart left', str(refusal)); self.assertIn('(notes.txt)', str(refusal))

    def test_cli_reply_carries_the_code_and_failed_check(self):
        from goat_studio import main
        self.save(self.original.replace('expertmode=0', 'expertmode=4'))
        self.c.store.close(); self.c.store = None; self.fixture.controller = None
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['--installation', str(self.fixture.path), 'monitor-launch', '--attempt-id', 'cli-refused'])
        reply = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 2)
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['refusal_code'], MONITOR_PROFILE_REFUSAL)
        self.assertEqual((reply['failed_check'], reply['failed_checks']), ('permissions', ['permissions']))
        self.assertEqual(reply['error'], 'The EA\'s chart permissions changed (Allow Algo Trading or DLL imports on the chart); '
                                         'reopen the saved monitor profile in MT5 yourself ('+self.menu+').')
        self.start.assert_not_called()

    def test_human_reopen_still_accepts_saved_permissions_only(self):
        # The observational exception is unchanged: a human reopen accepts MT5's saved permission bits,
        # never another failed check.
        text = self.original.replace('expertmode=0', 'expertmode=4')
        verify_saved_monitor(text.encode('utf-16'), 'GOAT-EA\\'+EA, 'EURUSD', str(self.data), observed_human_reopen=True)
        with self.assertRaises(Refusal) as caught:
            verify_saved_monitor(text.replace('symbol=EURUSD', 'symbol=GBPUSD').encode('utf-16'), 'GOAT-EA\\'+EA, 'EURUSD',
                                 str(self.data), observed_human_reopen=True)
        self.assertEqual(caught.exception.fields['failed_checks'], ['symbol'])
        self.assertNotIn('monitor_profile', caught.exception.fields, 'no profile name was supplied')
        self.assertIn('File > Profiles > GOAT-Studio-...', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
