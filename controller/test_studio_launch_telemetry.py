"""MT5 relaunch telemetry (goatai#1885): describes the Popen call and timing, never values. Fixture-only."""
import json
import subprocess
from types import SimpleNamespace
import unittest

import studio_launch_telemetry as telemetry

EXE = r'C:\MT5 Demo\terminal64.exe'
ARGV = [EXE, r'/config:C:\GOAT Studio\demo-deployments\x.ini', '/portable']
DEPLOY_OPTIONS = dict(cwd=r'C:\MT5 Demo', stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      creationflags=0x08000000)
ENV = {'PATH': r'C:\secret-ish\bin', 'GOAT_TOKEN_HINT': 'value-never-logged-123', 'SystemRoot': r'C:\Windows'}
LOGON = {'Path', 'SystemRoot', 'TEMP'}


class PopenFactsTests(unittest.TestCase):
    def test_the_deploy_launch_is_described_exactly(self):
        facts = telemetry.popen_facts(ARGV, DEPLOY_OPTIONS, environ=ENV, logon_names=LOGON)
        self.assertEqual(facts['argv'], ARGV)
        self.assertEqual(facts['command_line'], '"C:\\MT5 Demo\\terminal64.exe" "/config:C:\\GOAT Studio\\demo-deployments\\x.ini" /portable')
        self.assertEqual((facts['executable'], facts['cwd']), (EXE, r'C:\MT5 Demo'))
        self.assertEqual((facts['creationflags'], facts['creationflags_names']), (0x08000000, ['CREATE_NO_WINDOW']))
        self.assertEqual((facts['startupinfo'], facts['startupinfo_flags']), ('default (none passed)', ['STARTF_USESTDHANDLES']))
        self.assertTrue(facts['show_window'].startswith('not set'))
        self.assertEqual((facts['stdin'], facts['stdout'], facts['stderr']), ('DEVNULL',) * 3)
        self.assertEqual(facts['close_fds'], 'default (True)')
        self.assertEqual(facts['inherited_handles'], 'only the redirected std handles (PROC_THREAD_ATTRIBUTE_HANDLE_LIST)')
        self.assertEqual(facts['env_child_vs_controller'], dict(added=[], removed=[]))
        logon = facts['env_controller_vs_logon']
        self.assertEqual((logon['added'], logon['removed']), (['GOAT_TOKEN_HINT'], ['TEMP']), 'case-insensitive, names only')
        self.assertNotIn('value-never-logged-123', json.dumps(facts)); self.assertNotIn('secret-ish', json.dumps(facts))

    def test_other_launch_shapes_are_named(self):
        info = SimpleNamespace(dwFlags=0x1, wShowWindow=0)
        flags = 0x00000008 | 0x00000200 | 0x08000000 | 0x00000040
        env = dict(ENV, EXTRA='1'); del env['PATH']
        facts = telemetry.popen_facts([EXE], dict(creationflags=flags, startupinfo=info, close_fds=False, env=env),
                                      environ=ENV, logon_names=LOGON)
        self.assertEqual(facts['creationflags_names'], ['DETACHED_PROCESS', 'IDLE_PRIORITY_CLASS', 'CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW'])
        self.assertEqual((facts['startupinfo'], facts['startupinfo_flags'], facts['show_window']), ('passed', ['STARTF_USESHOWWINDOW'], 'SW_HIDE'))
        self.assertEqual((facts['stdin'], facts['close_fds'], facts['inherited_handles']), ('inherit', False, 'every inheritable handle'))
        self.assertEqual(facts['env'], 'explicit')
        self.assertEqual(facts['env_child_vs_controller'], dict(added=['EXTRA'], removed=['PATH']))
        self.assertEqual(telemetry.named_flags(0x08002000, telemetry.CREATION_FLAGS), ['CREATE_NO_WINDOW', '0x00002000'], 'unknown bits stay visible')
        self.assertEqual(telemetry.named_flags(0x2000 | 0x800, telemetry.JOB_LIMIT_FLAGS), ['BREAKAWAY_OK', 'KILL_ON_JOB_CLOSE'])

    def test_an_unreadable_logon_baseline_is_recorded_not_raised(self):
        def broken():
            raise OSError('registry denied')
        original = telemetry.logon_env_names
        telemetry.logon_env_names = broken
        try:
            facts = telemetry.popen_facts(ARGV, DEPLOY_OPTIONS, environ=ENV)
        finally:
            telemetry.logon_env_names = original
        self.assertEqual(facts['env_controller_vs_logon'], dict(error='OSError: registry denied'))

    def test_the_real_logon_baseline_is_names(self):
        names = telemetry.logon_env_names()
        self.assertIn('systemroot', {name.casefold() for name in names})
        self.assertTrue(all(isinstance(name, str) and '=' not in name for name in names))


class LaunchRecordTests(unittest.TestCase):
    def record(self, previous, check):
        return telemetry.launch_record(arguments=ARGV, options=DEPLOY_OPTIONS, previous=previous, pre_launch_check=check,
                                       launch_started_utc='2026-10-06T10:00:03.000000+00:00',
                                       popen_returned_utc='2026-10-06T10:00:03.040000+00:00', pid=77,
                                       environ=ENV, logon_names=LOGON, context=dict(pid=1))

    def test_gaps_in_ms_between_the_exit_window_the_last_check_and_the_launch(self):
        previous = dict(present_at_stage=True, exit_after_utc='2026-10-06T09:59:59.500000+00:00',
                        observed_gone_utc='2026-10-06T10:00:00.750000+00:00')
        check = dict(started_utc='2026-10-06T10:00:01+00:00', finished_utc='2026-10-06T10:00:02.200000+00:00', present=False)
        record = self.record(previous, check)
        self.assertEqual(record['gap_ms'], dict(exit_to_launch_at_least=2250, exit_to_launch_at_most=3500, pre_launch_check_to_launch=800))
        self.assertEqual((record['popen_ms'], record['pid'], record['previous_present_at_launch']), (40, 77, False))
        self.assertEqual((record['schema'], record['controller']), (1, dict(pid=1)))
        json.dumps(record)  # the journal is JSON

    def test_unknown_bounds_stay_none(self):
        record = self.record(dict(present_at_stage=False, observed_gone_utc='2026-10-06T10:00:00+00:00', exit_after_utc=None), None)
        self.assertEqual(record['gap_ms'], dict(exit_to_launch_at_least=3000, exit_to_launch_at_most=None, pre_launch_check_to_launch=None))
        self.assertIsNone(record['previous_present_at_launch'])

    def test_controller_context_reports_session_desktop_and_job(self):
        context = telemetry.controller_context()
        self.assertNotIn('error', context)
        self.assertIsInstance(context['session_id'], int)
        self.assertIsInstance(context['in_job'], bool)
        self.assertIsInstance(context['window_station'], str); self.assertIsInstance(context['desktop'], str)
        if context['in_job']:
            self.assertIsInstance(context['job_limit_flags'], list)


if __name__ == '__main__':
    unittest.main()
