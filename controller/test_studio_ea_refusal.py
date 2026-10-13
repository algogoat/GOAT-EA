"""The EA's refusal reason, read from the Experts log, and continue/clear-stop telling the truth (Banker 2026-10-13)."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_ea_refusal
from studio_batch_stall import driver_stall, research_stall
from studio_ea_refusal import attempt_window, ea_refusal, for_job
from studio_refusal import Refusal
import test_demo_agent

# Banker's Experts log, MQL5\Logs\20261013.log (UTF-16LE with BOM), copied verbatim: the prove batch at 07:03
# and its -r1 successor at 07:59, both refused at OnTesterInit; EURUSD is the GOAT Studio monitor chart.
EXPERTS_20261013 = [
    'FS\t0\t07:03:27.328\tGOAT V1.49 (EURUSD,M1)\tSymbol=EURUSD GOAT_Symbol=EURUSD',
    'KK\t0\t07:03:27.337\tGOAT V1.49 (EURUSD,M1)\tStrategy: Studio Monitor',
    'KR\t0\t07:03:27.338\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: WS30 Optimization Initialization.',
    'IL\t0\t07:03:27.369\tGOAT V1.49 (EURUSD,M1)\tMon:01:30-22:30',
    'NM\t0\t07:03:27.369\tGOAT V1.49 (EURUSD,M1)\tExpiry: 2027.08.01 22:00:00',
    'RG\t0\t07:03:27.369\tGOAT V1.49 (EURUSD,M1)\tFont Size=8',
    'PP\t0\t07:03:27.463\tGOAT V1.49 (WS30,M1)\tGOAT optimization refused before passes: Native optimization '
    'flag/value/range differs: RSI_TF_',
    'NL\t0\t07:03:27.463\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: WS30 Optimization Ended',
    'NF\t0\t07:03:27.800\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: DEINIT: ❌ Skipping batch XML migration/export because '
    'tester startup was not accepted for the active queue item.',
    'NR\t0\t07:03:29.043\tGOAT V1.49 (EURUSD,M1)\tResponse Code: 200',
    'DG\t0\t07:03:29.161\tGOAT V1.49 (EURUSD,M1)\tLicense verified.',
    'CO\t0\t07:59:24.340\tGOAT V1.49 (EURUSD,M1)\tFont Size=8',
    'LH\t0\t07:59:24.342\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: WS30 Optimization Initialization.',
    'PR\t0\t07:59:24.449\tGOAT V1.49 (WS30,M1)\tGOAT optimization refused before passes: Native optimization '
    'flag/value/range differs: RSI_TF_',
    'NN\t0\t07:59:24.449\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: WS30 Optimization Ended',
    'PP\t0\t07:59:24.789\tGOAT V1.49 (WS30,M1)\tGOAT V1.49: DEINIT: ❌ Skipping batch XML migration/export because '
    'tester startup was not accepted for the active queue item.',
    'PI\t0\t07:59:26.152\tGOAT V1.49 (EURUSD,M1)\tLicense verified.',
]
# The tester journal's only words for the same refusal (Tester\logs\20261013.log; MT5 rewrote that file later
# the same day, so this line is reconstructed from the incident report in the same journal format).
TESTER_20261013 = [
    'HM\t0\t07:03:27.120\tTester\t"GOAT-EA\\GOAT V1.49.ex5" X64',
    'OK\t2\t07:03:27.464\tTester\tOnTesterInit failed. Optimization cannot be started.',
]
REASON = 'Native optimization flag/value/range differs: RSI_TF_'


def local_wall(hour, minute, second=0, micro=0):
    """A 2026-10-13 local time as epoch seconds, the way MT5 stamps its journals."""
    return datetime(2026, 10, 13, hour, minute, second, micro).timestamp()


def iso(wall):
    return datetime.fromtimestamp(wall, timezone.utc).isoformat()


def write_log(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le'))


def job(job_id, attempt_wall, symbol='WS30', attempt='a'):
    return dict(job_id=job_id, status='cancelled',
                configuration=dict(batch_members=[dict(tester=dict(Symbol=symbol, Period='M1'))]),
                launch_intent=dict(attempt_id=attempt * 64, recorded_at=iso(attempt_wall)))


class ExpertsLogRefusalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.experts = self.data / 'MQL5/Logs/20261013.log'
        self.tester = self.data / 'Tester/logs/20261013.log'
        write_log(self.experts, EXPERTS_20261013)
        write_log(self.tester, TESTER_20261013)
        self.now = local_wall(9, 0)

    def test_real_10_13_lines_yield_the_reason(self):
        found = ea_refusal(self.data, local_wall(7, 3, 0), until_wall=local_wall(7, 59), now=self.now)
        self.assertEqual(found['reason'], REASON)
        self.assertEqual(found['kind'], 'input_verification')
        self.assertEqual(found['source'], 'GOAT V1.49 (WS30,M1)')
        self.assertEqual(found['at_local'], '2026-10-13 07:03:27.463')
        self.assertEqual(found['at_wall'], local_wall(7, 3, 27, 463000))
        self.assertEqual(found['log'], 'MQL5\\Logs\\20261013.log')
        self.assertIn('WS30 Optimization Initialization', found['context'])
        self.assertEqual(found['tester_journal']['line'], TESTER_20261013[1])
        self.assertTrue(found['retry_unchanged_refuses'])
        self.assertTrue(found['plain'].startswith('The EA refused this batch before any test ran: ' + REASON
                                                  + '. Retrying unchanged will refuse again'))
        self.assertIn('clear-stop only clears the owner STOP file', found['plain'])

    def test_no_matching_line_is_null(self):
        write_log(self.experts, [line for line in EXPERTS_20261013 if 'refused' not in line])
        self.assertIsNone(ea_refusal(self.data, local_wall(7, 0), now=self.now))

    def test_a_line_before_the_attempt_start_is_ignored(self):
        # The -r1 attempt started at 07:59:00: the 07:03 refusal belongs to the original attempt.
        found = ea_refusal(self.data, local_wall(7, 59), now=self.now)
        self.assertEqual(found['at_local'], '2026-10-13 07:59:24.449')
        self.assertEqual(found['matches'], 1)
        self.assertIsNone(found['tester_journal'])
        self.assertIsNone(ea_refusal(self.data, local_wall(7, 59, 25), now=self.now))
        # One millisecond after the refusal is already too late.
        self.assertIsNone(ea_refusal(self.data, local_wall(7, 59, 24, 450000), now=self.now))

    def test_missing_log_is_null_never_an_error(self):
        self.assertIsNone(ea_refusal(self.data / 'nowhere', local_wall(7, 0), now=self.now))
        self.experts.unlink()
        self.assertIsNone(ea_refusal(self.data, local_wall(7, 0), now=self.now))

    def test_unreadable_log_is_null_never_an_error(self):
        with patch('studio_ea_refusal._tail', side_effect=PermissionError(32, 'sharing violation')):
            self.assertIsNone(ea_refusal(self.data, local_wall(7, 0), now=self.now))

    @unittest.skipUnless(os.name == 'nt', 'Windows share modes')
    def test_locked_log_is_null_and_a_shared_open_reads(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # MT5 keeps its journal open for writing and shares read: the controller's plain read still works.
        shared = kernel.CreateFileW(str(self.experts), 0x40000000, 0x1 | 0x2, None, 3, 0x80, None)
        self.assertNotEqual(shared, wintypes.HANDLE(-1).value)
        try:
            self.assertEqual(ea_refusal(self.data, local_wall(7, 0), until_wall=local_wall(7, 59), now=self.now)['reason'], REASON)
        finally:
            kernel.CloseHandle(shared)
        # Opened with no sharing at all: the read fails with a sharing violation and the answer is null.
        exclusive = kernel.CreateFileW(str(self.experts), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(exclusive, wintypes.HANDLE(-1).value)
        try:
            self.assertIsNone(ea_refusal(self.data, local_wall(7, 0), now=self.now))
        finally:
            kernel.CloseHandle(exclusive)

    def test_only_the_tail_is_read_and_a_cut_first_line_is_dropped(self):
        filler = ['AA\t0\t06:00:00.000\tGOAT V1.49 (EURUSD,M1)\t' + 'x' * 80] * 400
        write_log(self.experts, filler + EXPERTS_20261013)
        # The bound reaches 20 characters into the 07:03:29.161 line: everything from 07:59 on, a cut line before it.
        tail = len(('\r\n'.join(EXPERTS_20261013[11:]) + '\r\n').encode('utf-16-le')) + 40
        with patch.object(studio_ea_refusal, 'MAX_TAIL_BYTES', tail):
            found = ea_refusal(self.data, local_wall(7, 0), now=self.now)
        self.assertEqual(found['at_local'], '2026-10-13 07:59:24.449')   # 07:03 is beyond the bounded tail

    def test_matches_are_bounded(self):
        line = 'PP\t0\t07:03:27.463\tGOAT V1.49 (WS30,M1)\tGOAT optimization refused before passes: ' + REASON
        write_log(self.experts, [line] * 250)
        self.assertEqual(ea_refusal(self.data, local_wall(7, 0), now=self.now)['matches'], studio_ea_refusal.MAX_MATCHES)

    def test_another_charts_refusal_is_never_quoted(self):
        write_log(self.experts, EXPERTS_20261013[:2] + [
            'AB\t1\t07:03:28.000\tGOAT V1.49 (EURUSD,M1)\tAlert: Initialization Failed: Pip Gap Size too small or zero'])
        self.assertIsNone(ea_refusal(self.data, local_wall(7, 0), symbols={'WS30'}, now=self.now))
        found = ea_refusal(self.data, local_wall(7, 0), symbols={'EURUSD'}, now=self.now)
        self.assertEqual((found['kind'], found['reason']), ('initialization_failed', 'Pip Gap Size too small or zero'))

    def test_studio_settings_refusal_is_reported_but_not_an_input_refusal(self):
        write_log(self.experts, ['ZZ\t0\t07:03:28.000\tGOAT V1.49 (WS30,M1)\tStudio settings refused: fresh native readback unavailable'])
        found = ea_refusal(self.data, local_wall(7, 0), now=self.now)
        self.assertEqual((found['kind'], found['reason']), ('studio_settings_refused', 'fresh native readback unavailable'))
        self.assertFalse(found['retry_unchanged_refuses'])
        self.assertFalse(studio_ea_refusal.blocks_retry(found))

    def test_each_attempt_sees_only_its_own_window(self):
        original, successor = job('prove-a', local_wall(7, 2)), job('prove-a-r1', local_wall(7, 58), attempt='b')
        jobs = [original, successor]
        self.assertEqual(attempt_window(original, jobs), (local_wall(7, 2), local_wall(7, 58)))
        self.assertEqual(for_job(dict(terminal_data_root=str(self.data)), original, jobs, now=self.now)['at_local'],
                         '2026-10-13 07:03:27.463')
        self.assertEqual(for_job(dict(terminal_data_root=str(self.data)), successor, jobs, now=self.now)['at_local'],
                         '2026-10-13 07:59:24.449')
        self.assertIsNone(for_job(dict(terminal_data_root=str(self.data)), dict(job_id='never', status='pending'), jobs))


class BatchStatusFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        write_log(self.data / 'MQL5/Logs/20261013.log', EXPERTS_20261013)

    def controller(self, *jobs):
        from types import SimpleNamespace
        for item in jobs:
            member = item['configuration']['batch_members'][0]
            member.update(strategy=dict(values=dict(EA_Desc='member')))
            item['configuration_sha256'] = 'f' * 64
        by_id = {item['job_id']: item for item in jobs}
        return SimpleNamespace(root=self.data / 'state', install=dict(terminal_data_root=str(self.data)),
                               job=lambda job_id: by_id[job_id], state=lambda: dict(queue=list(jobs)))

    def test_a_settled_attempt_ends_at_its_completion(self):
        # GOAT-EA#234 review: a refusal printed after the attempt settled (another run) is never this attempt's.
        settled = dict(job('prove-a', local_wall(7, 2)), completion=dict(native=dict(observed_at=iso(local_wall(7, 30)))))
        install = dict(terminal_data_root=str(self.data))
        self.assertEqual(attempt_window(settled, [settled]), (local_wall(7, 2), local_wall(7, 30)))
        self.assertEqual(for_job(install, settled, [settled], now=local_wall(9, 0))['at_local'], '2026-10-13 07:03:27.463')
        early = dict(settled, completion=dict(native=dict(observed_at=iso(local_wall(7, 3)))))
        self.assertIsNone(for_job(install, early, [early], now=local_wall(9, 0)))
        # Unsettled: open-ended, as before.
        running = dict(settled, status='running')
        self.assertEqual(attempt_window(running, [running]), (local_wall(7, 2), None))

    def test_the_launch_day_is_read_however_late_the_retry(self):
        # GOAT-EA#234 review: a continue a week later still sees the launch day's refusal.
        refused = job('prove-a', local_wall(7, 2))
        week_later = datetime(2026, 10, 20, 9, 0).timestamp()
        found = for_job(dict(terminal_data_root=str(self.data)), refused, [refused], now=week_later)
        self.assertEqual(found['reason'], REASON)
        days = studio_ea_refusal._days(local_wall(7, 2), week_later)
        self.assertEqual([day.day for day in days], [13, 14, 15, 18, 19, 20])

    def test_research_status_names_the_refusal_when_nothing_runs(self):
        from studio_research_status import research_status
        local = self.data / 'MQL5/Files/GOATStudio'; local.mkdir(parents=True)
        (self.data / 'common').mkdir(); (self.data / 'state').mkdir()
        install = dict(terminal_data_root=str(self.data), common_files_root=str(self.data / 'common'),
                       terminal_executable='t.exe', ea_version='1.49', ea_sha256='e' * 64)
        session = dict(run_id='r', terminal_id='t', account=dict(login='3000082754', server='Darwinex-Demo'), demo_only=True)
        refused, clean = job('prove-a', local_wall(7, 2)), job('clean', local_wall(8, 10), attempt='c')
        progress = dict(evidence='native_queue', current_member=None)
        with patch('studio_research_status.batch_progress', return_value=progress):
            stopped = research_status(root=self.data / 'state', install=install, session=session, local=local,
                                      now=local_wall(9, 0), process=None, jobs=[refused])
            ran = research_status(root=self.data / 'state', install=install, session=session, local=local,
                                  now=local_wall(9, 0), process=None, jobs=[refused, clean])
        self.assertEqual(stopped['activity']['ea_refusal']['reason'], REASON)
        self.assertIn('The EA refused this batch before any test ran: ' + REASON, stopped['activity']['headline'])
        self.assertIsNone(ran['activity']['ea_refusal'])

    def test_batch_status_carries_the_ea_refusal_or_null(self):
        from studio_batch import batch_status
        refused, clean = job('prove-a', local_wall(7, 2)), job('clean', local_wall(8, 10), attempt='c')
        controller = self.controller(refused, job('prove-a-r1', local_wall(7, 58), attempt='b'), clean)
        self.assertEqual(batch_status(controller, 'prove-a')['ea_refusal']['reason'], REASON)
        self.assertIsNone(batch_status(controller, 'clean')['ea_refusal'])
        self.assertEqual(studio_ea_refusal.for_controller(controller, 'prove-a')['at_local'], '2026-10-13 07:03:27.463')
        self.assertIsNone(studio_ea_refusal.for_controller(controller, 'unknown'))   # never an error


class StallVerdictTests(unittest.TestCase):
    SESSION = dict(authority_kind='demo_direct')
    REFUSAL = dict(reason=REASON, kind='input_verification', log='MQL5\\Logs\\20261013.log',
                   at_local='2026-10-13 07:03:27.463', plain='The EA refused this batch before any test ran: ' + REASON
                   + '. Retrying unchanged will refuse again; rebuild the SET.')

    def stalled(self, refusal_fn=None):
        observed = dict(status='reconcile_required', job=dict(native_observation=dict(native=dict(
            members=[dict(status='native_queued')]))))
        return driver_stall(observed, dict(last_error='Native queue is not finished'), quiet_since=0, now=3600,
                            session=self.SESSION, job_id='prove-a',
                            monitor_fn=lambda: dict(ticking=True, tester_state='idle'), refusal_fn=refusal_fn)

    def test_an_ea_refusal_replaces_continue_clear_stop_in_the_verdict(self):
        stall = self.stalled(lambda: self.REFUSAL)
        self.assertEqual(stall['ea_refusal'], self.REFUSAL)
        self.assertIn('The EA refused this batch before any test ran: ' + REASON, stall['plain'])
        self.assertNotIn('--clear-stop', stall['plain'])
        self.assertEqual(stall['fix']['commands'], ['goat.exe demo --installation <receipt> stop'])
        self.assertIn('clear-stop only clears the owner STOP file', stall['fix']['note'])

    def test_a_stall_without_an_ea_refusal_keeps_its_recovery(self):
        for refusal_fn in (None, lambda: None, lambda: 1 / 0):
            stall = self.stalled(refusal_fn)
            self.assertNotIn('ea_refusal', stall)
            self.assertIn('continue --batch-id prove-a --clear-stop', stall['plain'])

    def test_research_stall_reads_the_refusal_only_once_stalled(self):
        calls = []
        activity = dict(kind='batch', status='running', evidence='native_queue', current_member=None,
                        status_counts=dict(native_queued=1), batch_id='prove-a')
        self.assertIsNone(research_stall(dict(activity, current_member=0), dict(ticking=True, tester_state='idle'),
                                         dict(started_wall=0), now=3600, session=self.SESSION,
                                         refusal_fn=lambda: calls.append(1)))
        self.assertEqual(calls, [])
        stall = research_stall(activity, dict(ticking=True, tester_state='idle'), dict(started_wall=0), now=3600,
                               session=self.SESSION, refusal_fn=lambda: self.REFUSAL)
        self.assertEqual(stall['ea_refusal']['reason'], REASON)


@contextmanager
def fake_studio(*args, **kwargs):
    yield object(), dict(login='3000082754', server='Darwinex-Demo')


class ContinueClearStopTests(unittest.TestCase):
    def setUp(self):
        base = test_demo_agent.DemoAgentTests('test_broker_reported_demo_and_exact_allowlist_required')
        base.setUp(); self.addCleanup(base.doCleanups)
        self.agent, self.data = base.agent, base.data
        self.agent.clock = lambda: local_wall(9, 0)
        write_log(self.data / 'MQL5/Logs/20261013.log', EXPERTS_20261013)
        self.refused = job('prove-a', local_wall(7, 2))
        self.clean = job('clean', local_wall(8, 10), attempt='c')

    def owner_stop(self):
        with patch.object(self.agent, '_native_active_batches', return_value=[]):
            self.agent.stop()
        self.assertTrue((self.agent.state_root / 'STOP').exists())

    def continue_(self, batch, jobs, **kwargs):
        prepared = dict(status='prepared', batch_id=batch + '-r1', members=1)
        with patch.object(self.agent, '_jobs_readonly', return_value=jobs), \
                patch.object(self.agent, '_lane_kind', return_value=None), \
                patch.object(self.agent, '_native_active_batches', return_value=[]), \
                patch.object(self.agent, '_refresh_readback', return_value=dict(status='verified')), \
                patch.object(self.agent, '_studio', fake_studio), \
                patch.object(self.agent, '_spawn_driver', return_value=dict(status='driver_starting')) as spawn, \
                patch.object(self.agent, '_resume_budget', return_value=3600), \
                patch('demo_agent.tester_state', return_value='idle'), \
                patch('studio_batch_close.refuse_closed'), \
                patch('studio_retire_unactivated.unactivated_hint', return_value=False), \
                patch('studio_research_status.monitor_state', return_value={}), \
                patch('studio_research_status.lineage', return_value=[]), \
                patch('studio_fast_lane.resolve_successor', return_value=batch + '-r1'), \
                patch('studio_protected_peer.refresh_process', return_value=None), \
                patch('studio_fast_lane.continue_batch', return_value=prepared) as prepare:
            return self.agent.continue_batch(batch, **kwargs), spawn, prepare

    def test_plain_clear_stop_reports_owner_stop_file_only(self):
        already = self.agent.clear_stop()
        self.assertEqual((already['status'], already['clears']), ('already_clear', 'owner_stop_file_only'))
        self.owner_stop()
        with patch.object(self.agent, '_native_active_batches', return_value=[]), \
                patch('demo_agent.tester_state', return_value='idle'):
            cleared = self.agent.clear_stop()
        self.assertEqual((cleared['phase'], cleared['clears']), ('verified', 'owner_stop_file_only'))
        self.assertIn('does not change the EA\'s inputs, a human cancel, TAKE CONTROL or any EA latch', cleared['note'])
        self.assertFalse((self.agent.state_root / 'STOP').exists())

    def test_clear_stop_still_never_clears_a_human_take_control(self):
        self.owner_stop()
        inbox = self.agent.local / 'session-one/human/inbox'; inbox.mkdir(parents=True)
        (inbox / 'take.json').write_text('{}')
        with patch.object(self.agent, '_native_active_batches', return_value=[]), \
                patch('demo_agent.tester_state', return_value='idle'):
            with self.assertRaisesRegex(ValueError, 'Pending human TAKE CONTROL'):
                self.agent.clear_stop()
        self.assertTrue((self.agent.state_root / 'STOP').exists())

    def test_continue_after_an_ea_input_refusal_refuses_with_the_reason(self):
        self.owner_stop()
        with self.assertRaises(Refusal) as caught:
            self.continue_('prove-a', [self.refused], clear_stop=True)
        refusal = caught.exception
        self.assertEqual(refusal.code, 'EA_REFUSED_INPUTS')
        self.assertIn('the EA refused prove-a before any test ran: ' + REASON, str(refusal))
        self.assertIn('Rebuild the SET', str(refusal))
        self.assertIn('clear-stop only clears the owner STOP file', str(refusal))
        self.assertEqual(refusal.fields['ea_refusal']['reason'], REASON)
        self.assertTrue((self.agent.state_root / 'STOP').exists())    # nothing was changed, the STOP included

    def test_continue_after_a_retained_human_cancel_refuses(self):
        gate = self.agent.local / 'native-gate'; gate.mkdir(parents=True)
        attempt = 'c' * 64
        request = dict(request_id=attempt, action='start', job_id='clean')
        body = json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n'
        digest = hashlib.sha256(body.encode()).hexdigest()
        (gate / ('issued-' + attempt + '.json')).write_text(json.dumps(dict(request=request, request_sha256=digest)))
        (gate / ('result-' + attempt + '.json')).write_text(json.dumps(dict(request_id=attempt, request_sha256=digest,
                                                                             status='HUMAN_CANCEL_RETAINED')))
        with self.assertRaises(Refusal) as caught:
            self.continue_('clean', [self.clean])
        self.assertEqual(caught.exception.code, 'HUMAN_CANCEL_RETAINED')
        self.assertIn('Have the person press Start', str(caught.exception))

    def test_continue_after_a_normal_owner_stop_works_as_before(self):
        self.owner_stop()
        result, spawn, prepare = self.continue_('clean', [self.refused, self.clean], clear_stop=True)
        self.assertFalse((self.agent.state_root / 'STOP').exists())
        self.assertEqual(result['clears'], 'owner_stop_file_only')
        self.assertEqual(result['stop_cleared']['phase'], 'verified')
        self.assertEqual(result['previous_attempt'], dict(attempt_id='c' * 64, dispatch_status=None, ea_refusal=None))
        self.assertEqual((result['status'], result['driver']), ('prepared', dict(status='driver_starting')))
        spawn.assert_called_once_with('clean-r1', max_seconds=3600)
        prepare.assert_called_once()

    def test_continue_without_a_stop_clears_nothing(self):
        result, _spawn, _prepare = self.continue_('clean', [self.clean])
        self.assertIsNone(result['clears'])
        self.assertIsNone(result['stop_cleared'])


if __name__ == '__main__':
    unittest.main()
