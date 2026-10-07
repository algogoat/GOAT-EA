"""A transient Windows sharing error never fails a detached lane driver (goatai#1885).

Banker 2026-10-07: seed driver release-190check-202610071054 was recorded ``failed`` with
"[WinError 32] ... being used by another process" (no file name: the native gate's
CreateFileW), while two concurrent seed-status calls hit the same error and a third succeeded.
The runner's gate now waits the sharing-retry bound for another operation, a driver pass that
still finds it busy is skipped instead of failing, and record reads and writes retry WinError
5/32/33 (40 x 25 ms) before failing loudly. Real Windows handles where it matters.
"""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_agent
import studio_bridge
import studio_installation
import studio_seed_results
import test_studio_seed as seed_fixture
from studio_agent_mailbox import SHARING_RETRY_ATTEMPTS, transient_sharing_error
from studio_native_gate import GateBusy, exclusive_gate


def sharing_violation():
    return PermissionError(13, 'The process cannot access the file because it is being used by another process', None, 32)


def hold_exclusively(path, seconds):
    """Open ``path`` with no sharing (as an EA FileOpen or a non-sharing reader does) for ``seconds``."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    timer = threading.Timer(seconds, lambda: kernel.CloseHandle(handle))
    timer.start()
    return timer


def hold_gate(gate, seconds):
    holding = threading.Event()
    def hold():
        with exclusive_gate(gate):
            holding.set()
            time.sleep(seconds)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    holding.wait(5)
    return thread


@unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gate = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_still_refuses_at_once_and_names_the_lock(self):
        thread = hold_gate(self.gate, .5)
        started = time.monotonic()
        with self.assertRaises(GateBusy) as raised:
            with exclusive_gate(self.gate):
                pass
        self.assertLess(time.monotonic() - started, .3)
        self.assertIsInstance(raised.exception, PermissionError)       # what ctypes.WinError(32) raised before
        self.assertEqual(raised.exception.winerror, 32)
        self.assertIn('launch.lock', str(raised.exception))
        thread.join()

    def test_a_bounded_wait_gets_the_gate_once_released(self):
        thread = hold_gate(self.gate, .3)
        with exclusive_gate(self.gate, wait_seconds=1):
            pass
        thread.join()

    def test_a_gate_held_past_the_wait_fails_loudly(self):
        thread = hold_gate(self.gate, 1.5)
        started = time.monotonic()
        with self.assertRaisesRegex(GateBusy, 'still held after 0.2 s.*launch.lock'):
            with exclusive_gate(self.gate, wait_seconds=.2):
                pass
        self.assertLess(time.monotonic() - started, 1)
        thread.join()

    def test_wait_is_bounded(self):
        for bad in (-1, 601, float('nan'), '1'):
            with self.assertRaises(ValueError):
                with exclusive_gate(self.gate, wait_seconds=bad):
                    pass


@unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
class RecordRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'record.json'
        self.path.write_text(json.dumps(dict(status='supervising')), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_demo_record_write_retries_two_sharing_violations(self):
        real, calls = os.replace, []
        def flaky(source, target):
            calls.append(target)
            if len(calls) <= 2:
                raise sharing_violation()
            return real(source, target)
        with patch.object(demo_agent.os, 'replace', flaky):
            demo_agent.write_json(self.path, dict(status='returned'))
        self.assertEqual((len(calls), demo_agent.read_json(self.path)), (3, dict(status='returned')))

    def test_demo_record_write_fails_loudly_after_the_bound_and_leaves_no_temporary(self):
        calls = []
        def denied(source, target):
            calls.append(target)
            raise sharing_violation()
        with patch.object(demo_agent.os, 'replace', denied), self.assertRaises(PermissionError):
            demo_agent.write_json(self.path, dict(status='returned'))
        self.assertEqual(len(calls), SHARING_RETRY_ATTEMPTS)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['record.json'])
        self.assertEqual(demo_agent.read_json(self.path), dict(status='supervising'))

    def test_an_open_sharing_violation_is_transient(self):
        # open() reports a sharing violation through the C runtime: errno 13 and no winerror.
        self.assertTrue(transient_sharing_error(PermissionError(13, 'Permission denied', 'x')))
        self.assertTrue(transient_sharing_error(sharing_violation()))
        self.assertFalse(transient_sharing_error(PermissionError(13, 'The network name cannot be found', 'x', 67)))
        self.assertFalse(transient_sharing_error(FileNotFoundError(2, 'missing', 'x')))

    def test_writes_and_reads_wait_out_a_real_exclusive_holder(self):
        for write in (demo_agent.write_json, studio_bridge.write_json):
            with self.subTest(write=write.__module__):
                timer = hold_exclusively(self.path, .2)
                try:
                    write(self.path, dict(status='returned', by=write.__module__))
                finally:
                    timer.join()
                self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['by'], write.__module__)
        for read in (demo_agent.read_json, studio_installation.read_json, studio_seed_results.read_seed_json):
            with self.subTest(read=read.__module__):
                timer = hold_exclusively(self.path, .2)
                try:
                    self.assertEqual(read(self.path)['status'], 'returned')
                finally:
                    timer.join()


class LaneDriverFinalRecordTests(unittest.TestCase):
    """demo_agent._drive_lane, the shared detached seed/catch-up/hold-up driver."""

    def drive(self, kind, failures, result=None, error=None):
        with tempfile.TemporaryDirectory() as work:
            worker_path = Path(work) / (kind + '-b1.json')
            nonce = 'a' * 32
            demo_agent.write_json(worker_path, dict(kind=kind, batch_id='b1', nonce=nonce, initial=False, max_seconds=120,
                                                    status='spawned'))
            rows = []
            def lane(*args, **kwargs):
                if error:
                    raise error
                return result
            agent = SimpleNamespace(_lane_worker_path=lambda k, b: worker_path, _exclusive=lambda wait_seconds=0: nullcontext(),
                                    DRIVER_LOCK_WAIT_SECONDS=120, UNSTARTED_WORKER=demo_agent.DemoAgent.UNSTARTED_WORKER,
                                    _mark_worker_failed=lambda *a: None, _lane_resume=lane, _lane_start=lane,
                                    _append=lambda operation, phase, **details: rows.append(phase))
            real, writes = os.replace, []
            def flaky(source, target):
                writes.append(target)
                if 1 < len(writes) <= 1 + failures:     # the supervising write lands; the final one is denied
                    raise sharing_violation()
                return real(source, target)
            with patch.object(demo_agent.os, 'replace', flaky):
                try:
                    returned = demo_agent.DemoAgent._drive_lane(agent, kind, 'b1', nonce, 120, False)
                except Exception as exc:
                    returned = exc
            return returned, demo_agent.read_json(worker_path), rows

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_a_completed_job_is_recorded_completed_through_two_sharing_violations(self):
        for kind in ('seed', 'catchup', 'holdup'):
            with self.subTest(kind=kind):
                returned, record, rows = self.drive(kind, 2, result=dict(status='completed'))
                self.assertEqual(returned, dict(status='completed'))
                self.assertEqual((record['status'], record['result_status']), ('returned', 'completed'))
                self.assertNotIn('error', record)
                self.assertEqual(rows, ['supervising', 'returned'])

    def test_a_real_driver_error_is_still_recorded_failed(self):
        returned, record, rows = self.drive('catchup', 0, error=ValueError('member identity changed'))
        self.assertIsInstance(returned, ValueError)
        self.assertEqual((record['status'], record['error']), ('failed', 'member identity changed'))
        self.assertEqual(rows, ['supervising', 'failed'])


@unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
class RunnerGateTests(unittest.TestCase):
    """The seed/catch-up/hold-up runner on the seed fixture's fake MT5, with a real gate held by another 'process'."""
    setUp = seed_fixture.SeedTests.setUp
    tearDown = seed_fixture.SeedTests.tearDown
    close = seed_fixture.SeedTests.close
    start = seed_fixture.SeedTests.start
    sleep = seed_fixture.SeedTests.sleep
    prepare = seed_fixture.SeedTests.prepare

    def test_a_concurrent_status_read_is_retried(self):
        self.prepare()
        thread = hold_gate(self.runner.gate, .3)
        self.assertEqual(self.runner.status('batch')['status'], 'prepared')
        thread.join()

    def test_a_status_read_still_blocked_after_the_bound_fails_loudly(self):
        self.prepare()
        thread = hold_gate(self.runner.gate, 2)
        with self.assertRaisesRegex(GateBusy, 'still held after'):
            self.runner.status('batch')
        thread.join()

    def test_a_driver_pass_that_finds_the_gate_busy_is_skipped_not_failed(self):
        self.prepare()
        thread = hold_gate(self.runner.gate, 1.5)       # longer than one gate wait: the first pass is skipped
        self.runner.start('batch', 10)
        thread.join()
        self.assertEqual(len(self.starts), 1)

    def test_the_drivers_closing_status_never_raises_on_a_busy_gate(self):
        self.prepare()
        thread = hold_gate(self.runner.gate, 2)
        result = self.runner._status_or_busy('batch', driver_budget_exhausted=True)
        thread.join()
        self.assertEqual((result['status'], result['driver_budget_exhausted']), ('status_busy', True))
        self.assertIn('launch.lock', result['gate_busy'])


if __name__ == '__main__':
    unittest.main()
