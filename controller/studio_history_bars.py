"""A catch-up starts only when the terminal holds its evidence end's last trading bar (Claude-Mac, goatai#2750 6880394220).

Catch-ups started early Saturday 2026-11-14 (``w12q-t3-a/b-1113``, most of ``w12q-banker-a-1113``) ran before the
terminal had Friday's history: 113 re-tests ended 11-12 under plans that said 11-13, and the shortfall was only a flag
(EVIDENCE_END_SHORT) on results that still stamped a verdict. Banker hit the same on 10-10. So a first start now
refuses, before any effect, when a member's symbol lacks the evidence end's last trading bar (INV-CATCHUP-01).

**The source** is the history the tester re-tests on: the running, selected MT5's own bars, read through the
MetaTrader5 adapter ATTACH-ONLY (as ``studio_broker_fit.read_broker``), under the installation's terminal lease (the
drive already holds it: joined). It refuses MT5_NOT_RUNNING and never lets ``initialize()`` start a closed MT5: the
exact terminal64.exe must already run, and a different process after attaching drops the link and refuses. For each
symbol it reads the last M1 bar (``copy_rates_from_pos(symbol, M1, 0, 1)``), never ticks, never a trading call, never
``symbol_select``. A first start always finds MT5 running: the monitor is closed only after these checks.

**The rule:** the symbol's last M1 bar opens on the evidence end's server day at or after LAST_BAR_FLOOR (19:00 server,
12:00 New York, before any early close of a listed market), or on a later day. A missing bar, an unreadable symbol, a
closed MT5 or a missing adapter refuses the start; nothing falls through on doubt. A market holiday on the evidence end
refuses too: give the plan the last trading day as its evidence end. A partial day that stops after 19:00 server is not
caught here; the collection check (studio_catchup.evidence_end_short refusing the stamp) is the second line.
"""
from datetime import datetime, time, timedelta

from studio_refusal import Refusal

CODE = 'CATCHUP_HISTORY_MISSING'
UNCHECKED = 'CATCHUP_HISTORY_UNCHECKED'
LAST_BAR_FLOOR = time(19, 0)
EPOCH = datetime(1970, 1, 1)


def bar_time(seconds):
    """The naive server wall time of an MT5 bar's ``time`` (seconds, server clock)."""
    return EPOCH + timedelta(seconds=int(seconds))


def missing(bars, end_iso):
    """[(symbol, last bar or None)] whose last bar is short of ``end_iso``'s last trading bar (the rule above)."""
    end = datetime.fromisoformat(end_iso).date()
    floor = datetime.combine(end, LAST_BAR_FLOOR)
    return [(symbol, last) for symbol, last in sorted(bars.items()) if last is None or last < floor]


def last_bars(controller, process, symbols, *, mt5=None):
    """{symbol: last M1 bar open (naive server time) or None}, read ATTACH-ONLY from the running selected MT5."""
    from pathlib import Path
    from studio_broker_fit import MT5_NOT_RUNNING, MT5_STARTED_BY_CHECK
    from studio_terminal_lease import BUSY_READ, terminal_lease
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            raise Refusal('GOAT could not read this terminal\'s history (the MetaTrader5 adapter is unavailable), so the '
                          'catch-up was not started.', UNCHECKED) from None
    with terminal_lease(controller.root, purpose='catchup-history-check', busy_code='CATCHUP_HISTORY_DEFERRED',
                        busy_message=BUSY_READ):
        before = process.inspect()
        if before is None:
            raise Refusal('MT5 is not running, so GOAT could not check that it holds the evidence end\'s history; start '
                          'MT5 and start the catch-up again. Nothing was started.', MT5_NOT_RUNNING)
        attached = mt5.initialize(controller.install['terminal_executable'], timeout=5000)
        after = process.inspect()
        if not after or after.get('pid') != before.get('pid') or after.get('created_utc') != before.get('created_utc'):
            mt5.shutdown()
            raise Refusal('GOAT started MT5 by accident while checking its history; close it and start again.',
                          MT5_STARTED_BY_CHECK, pidBefore=before.get('pid'), pidAfter=(after or {}).get('pid'))
        if not attached:
            raise Refusal('The selected MT5 could not be read, so its history was not checked; nothing was started.', UNCHECKED)
        try:
            terminal = mt5.terminal_info()
            if terminal is None or Path(terminal.data_path) != Path(controller.install['terminal_data_root']):
                raise Refusal('The running MT5 is not the selected installation, so its history was not checked.', UNCHECKED)
            out = {}
            for symbol in symbols:
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
                out[symbol] = bar_time(rates[0]['time']) if rates is not None and len(rates) else None
            return out
        finally:
            mt5.shutdown()


def check_start(controller, process, manifest, *, read=None):
    """Refuse a first start (CATCHUP_HISTORY_MISSING) naming each symbol whose last bar is short of the evidence end."""
    end_iso = manifest['evidence_end']['iso']
    symbols = sorted({member['tester']['Symbol'] for member in manifest['members']})
    bars = (read or last_bars)(controller, process, symbols)
    short = missing({s: bars.get(s) for s in symbols}, end_iso)
    if short:
        named = ', '.join('%s (last bar %s)' % (s, last.strftime('%Y-%m-%d %H:%M') if last else 'none') for s, last in short)
        no_bar = [s for s, last in short if last is None]
        # A symbol with no bar at all is usually not in Market Watch: MT5 serves no history for it (Claude-Mac 6880752410).
        hint = (' %s has no bar at all: add the symbol to Market Watch in MT5, then start again.' % ', '.join(no_bar)
                if no_bar else '')
        raise Refusal('This terminal does not yet hold %s\'s last trading bar for %s, so the catch-up was not started: its '
                      're-tests would stop short of %s. Start it again once MT5 has that history.%s'
                      % (end_iso, named, end_iso, hint), CODE, evidence_end=end_iso,
                      symbols={s: last.strftime('%Y-%m-%d %H:%M') if last else None for s, last in short})
    return dict(evidence_end=end_iso, symbols={s: bars[s].strftime('%Y-%m-%d %H:%M') for s in symbols})
