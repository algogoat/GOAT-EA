"""The installation's terminal lease (studio_terminal_lease; goatai#2350 6098964146)."""
import tempfile
import threading
import time
import unittest

from studio_terminal_lease import TerminalBusy, foreign_holder, held, lease_path, terminal_lease


class TerminalLeaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = temp.name

    def test_same_file_and_byte_as_the_demo_agent_lock(self):
        self.assertEqual(lease_path(self.root).parts[-2:], ('demo-agent', 'terminal.lock'))

    def test_join_in_the_holding_thread_and_release_with_the_outermost_holder(self):
        with terminal_lease(self.root, purpose='driver'):
            self.assertTrue(held(self.root))
            with terminal_lease(self.root, purpose='reader'):       # joined, no second OS lock
                self.assertTrue(held(self.root))
            self.assertTrue(held(self.root), 'an inner join never releases the outer holder')
            with self.assertRaises(RuntimeError):                    # still locked at the OS level
                with foreign_holder(self.root):
                    pass
        self.assertFalse(held(self.root))
        with foreign_holder(self.root):                              # released at the OS level too
            pass

    def test_refuse_mode_and_another_process_are_busy_with_the_named_code(self):
        with terminal_lease(self.root, purpose='driver'):
            with self.assertRaises(TerminalBusy) as caught:
                with terminal_lease(self.root, purpose='demo agent', nested='refuse'):
                    pass
            self.assertEqual((caught.exception.code, caught.exception.fields['holder']), ('TERMINAL_LEASE_BUSY', 'driver'))
        with foreign_holder(self.root):
            with self.assertRaises(TerminalBusy) as caught:
                with terminal_lease(self.root, purpose='status', busy_code='BROKER_READ_DEFERRED', broker_reason='terminal_busy'):
                    pass
            self.assertEqual((caught.exception.code, caught.exception.fields), ('BROKER_READ_DEFERRED', dict(broker_reason='terminal_busy')))
            self.assertIsInstance(caught.exception, ValueError, 'existing callers catch ValueError')

    def test_a_wait_succeeds_once_the_other_holder_lets_go(self):
        released = threading.Event()
        def other():
            with foreign_holder(self.root):
                released.wait(5); time.sleep(.3)
        thread = threading.Thread(target=other); thread.start()
        time.sleep(.2); released.set()
        start = time.monotonic()
        with terminal_lease(self.root, purpose='driver', wait_seconds=5):
            self.assertTrue(held(self.root))
        self.assertGreater(time.monotonic() - start, .1)
        thread.join()

    def test_released_when_the_body_raises_and_another_thread_reads_busy(self):
        with self.assertRaises(KeyError):
            with terminal_lease(self.root, purpose='driver'):
                raise KeyError('boom')
        self.assertFalse(held(self.root))
        errors = []
        with terminal_lease(self.root, purpose='driver'):
            def reader():
                try:
                    with terminal_lease(self.root, purpose='reader'):
                        pass
                except TerminalBusy as exc:
                    errors.append(exc.code)
            thread = threading.Thread(target=reader); thread.start(); thread.join()
        self.assertEqual(errors, ['TERMINAL_LEASE_BUSY'], 'a join is only for the holding thread')

    def test_bad_arguments_refuse(self):
        for kwargs in (dict(nested='maybe'), dict(wait_seconds=-1), dict(wait_seconds=601), dict(wait_seconds='5')):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}), self.assertRaises(ValueError):
                with terminal_lease(self.root, purpose='x', **kwargs):
                    pass


if __name__ == '__main__':
    unittest.main()
