from datetime import datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_history_bars as hb
from studio_refusal import Refusal


def secs(dt):
    return int((dt - hb.EPOCH).total_seconds())


class FakeMT5:
    """The MetaTrader5 adapter as the history check reads it: attach, terminal_info, copy_rates_from_pos, shutdown."""
    TIMEFRAME_M1 = 1

    def __init__(self, bars, data_path, attach=True):
        self.bars, self.data_path, self.attach, self.calls = bars, data_path, attach, []

    def initialize(self, path, timeout=None):
        self.calls.append(('initialize', path))
        return self.attach

    def terminal_info(self):
        return SimpleNamespace(data_path=self.data_path, path=str(Path(self.data_path).parent))

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.calls.append(('rates', symbol, timeframe, start, count))
        t = self.bars.get(symbol)
        return None if t is None else [dict(time=secs(t))]

    def shutdown(self):
        self.calls.append('shutdown')


class HistoryBarsTests(unittest.TestCase):
    """INV-CATCHUP-01 (goatai#2750 6880394220): a catch-up starts only when MT5 holds its evidence end's last trading bar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data = root / 'terminal'
        self.controller = SimpleNamespace(root=root / 'state', install=dict(terminal_executable=str(self.data / 'terminal64.exe'),
                                                                              terminal_data_root=str(self.data)))
        self.controller.root.mkdir()
        self.running = dict(pid=10, created_utc='t0')

    def process(self, *states):
        seq = iter(states)
        return SimpleNamespace(inspect=lambda: next(seq))

    def manifest(self, end='2026-11-13', symbols=('EURUSD', 'WS30')):
        return dict(evidence_end=dict(iso=end), members=[dict(tester=dict(Symbol=s)) for s in symbols])

    def test_todays_case_plan_end_11_13_last_bar_11_12_is_refused(self):
        # Saturday 2026-11-14 early: MT5 had no Friday 11-13 bar yet.
        bars = {'EURUSD': datetime(2026, 11, 12, 23, 59), 'WS30': datetime(2026, 11, 13, 23, 14)}
        self.assertEqual(hb.missing(bars, '2026-11-13'), [('EURUSD', datetime(2026, 11, 12, 23, 59))])
        with self.assertRaises(Refusal) as caught:
            hb.check_start(self.controller, None, self.manifest(), read=lambda c, p, s: bars)
        self.assertEqual(caught.exception.code, hb.CODE)
        self.assertIn("does not yet hold 2026-11-13's last trading bar for EURUSD (last bar 2026-11-12 23:59)", str(caught.exception))
        self.assertEqual(caught.exception.fields, dict(evidence_end='2026-11-13', symbols={'EURUSD': '2026-11-12 23:59'}))

    def test_the_rule(self):
        end = '2026-11-13'
        self.assertEqual(hb.missing({'A': datetime(2026, 11, 13, 19, 0)}, end), [])           # the floor itself
        self.assertEqual(hb.missing({'A': datetime(2026, 11, 16, 0, 5)}, end), [])            # a later day
        self.assertEqual(hb.missing({'A': datetime(2026, 11, 13, 18, 59)}, end), [('A', datetime(2026, 11, 13, 18, 59))])
        self.assertEqual(hb.missing({'A': None}, end), [('A', None)])                          # no bar at all
        ok = hb.check_start(self.controller, None, self.manifest(),
                            read=lambda c, p, s: {x: datetime(2026, 11, 13, 23, 55) for x in s})
        self.assertEqual(ok, dict(evidence_end=end, symbols={'EURUSD': '2026-11-13 23:55', 'WS30': '2026-11-13 23:55'}))
        with self.assertRaises(Refusal) as caught:
            hb.check_start(self.controller, None, self.manifest(), read=lambda c, p, s: {'WS30': datetime(2026, 11, 16)})
        self.assertIn('for EURUSD (last bar none)', str(caught.exception))
        self.assertIn('EURUSD has no bar at all: add the symbol to Market Watch in MT5, then start again.', str(caught.exception))
        self.assertEqual(caught.exception.fields['symbols'], {'EURUSD': None})
        with self.assertRaises(Refusal) as caught:                                   # a late bar alone: no Market Watch hint
            hb.check_start(self.controller, None, self.manifest(), read=lambda c, p, s: {x: datetime(2026, 11, 12, 23, 59) for x in s})
        self.assertNotIn('Market Watch', str(caught.exception))

    def test_reader_attaches_only_to_the_running_terminal_and_reads_m1_bars(self):
        mt5 = FakeMT5({'EURUSD': datetime(2026, 11, 13, 23, 59), 'WS30': datetime(2026, 11, 13, 23, 14)}, str(self.data))
        bars = hb.last_bars(self.controller, self.process(self.running, self.running), ['EURUSD', 'WS30', 'XYZ'], mt5=mt5)
        self.assertEqual(bars, {'EURUSD': datetime(2026, 11, 13, 23, 59), 'WS30': datetime(2026, 11, 13, 23, 14), 'XYZ': None})
        self.assertEqual(mt5.calls[0], ('initialize', self.controller.install['terminal_executable']))
        self.assertIn(('rates', 'EURUSD', 1, 0, 1), mt5.calls)
        self.assertEqual(mt5.calls[-1], 'shutdown')

    def test_reader_refuses_without_a_running_terminal_and_never_calls_initialize(self):
        mt5 = FakeMT5({}, str(self.data))
        with self.assertRaises(Refusal) as caught:
            hb.last_bars(self.controller, self.process(None), ['EURUSD'], mt5=mt5)
        self.assertEqual(caught.exception.code, 'MT5_NOT_RUNNING')
        self.assertEqual(mt5.calls, [])

    def test_reader_refuses_when_attaching_started_another_terminal_or_reads_the_wrong_one(self):
        mt5 = FakeMT5({'EURUSD': datetime(2026, 11, 13, 23, 59)}, str(self.data))
        with self.assertRaises(Refusal) as caught:
            hb.last_bars(self.controller, self.process(self.running, dict(pid=11, created_utc='t1')), ['EURUSD'], mt5=mt5)
        self.assertEqual(caught.exception.code, 'MT5_STARTED_BY_CHECK')
        self.assertEqual(mt5.calls[-1], 'shutdown')
        other = FakeMT5({'EURUSD': datetime(2026, 11, 13, 23, 59)}, str(self.data.parent / 'other-terminal'))
        with self.assertRaisesRegex(Refusal, 'not the selected installation'):
            hb.last_bars(self.controller, self.process(self.running, self.running), ['EURUSD'], mt5=other)
        self.assertEqual(other.calls[-1], 'shutdown')
        with self.assertRaises(Refusal) as caught:
            hb.last_bars(self.controller, self.process(self.running, self.running), ['EURUSD'], mt5=FakeMT5({}, str(self.data), attach=False))
        self.assertEqual(caught.exception.code, hb.UNCHECKED)

    def test_reader_refuses_without_the_adapter(self):
        with patch.dict(sys.modules, {'MetaTrader5': None}), self.assertRaises(Refusal) as caught:
            hb.last_bars(self.controller, self.process(self.running), ['EURUSD'])
        self.assertEqual(caught.exception.code, hb.UNCHECKED)

    def test_reader_waits_for_nobody_when_another_process_holds_the_terminal(self):
        from studio_terminal_lease import foreign_holder
        mt5 = FakeMT5({}, str(self.data))
        with foreign_holder(self.controller.root), self.assertRaises(Refusal) as caught:
            hb.last_bars(self.controller, self.process(self.running, self.running), ['EURUSD'], mt5=mt5)
        self.assertEqual(caught.exception.code, 'CATCHUP_HISTORY_DEFERRED')
        self.assertEqual(mt5.calls, [])


if __name__ == '__main__':
    unittest.main()
