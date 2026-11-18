"""The swap a tester run was charged, read from its capture's deals.csv (goat-swap-inputs-v1; INV-SWAP-01).

Why (Ops, 2026-11-18): MT5's Strategy Tester charges swap from the symbol specification it has cached from the
broker. Twice that cached specification held zero swap on JPY pairs (Banker 2026-10-09..10-27, and runs made
2026-09-19/20), so those runs paid no swap at all and every result judged on them is optimistic. Nothing recorded
the swap a run was given (studio_catchup_verdict.SYMBOL_SPEC), and the only swap check (studio_catchup_rebase,
cause ``swap_or_spec``) bounds the DIFFERENCE between an original and its re-test, which two swap-free runs pass.

The rule is the read-only research sweep's (Ops research/swap-guard-1118/swap_free_sweep.py), ported unchanged; this
module only adds ``swap_free_by_design`` and ``unmeasured``. The tester books swap at each server rollover (00:00 server time) on an open
position and records it on the position's closing deal(s) (deal_entry 1, 2 or 3). ``server_time_msc`` is broker
server time stored as epoch milliseconds, so the UTC date of that epoch is the server date.

* A position is *held over a rollover* when the server date of its last closing deal is later than the server date
  of its opening deal (deal_entry 0). A position without an opening deal or without a closing deal is not counted.
* ``swap_charged``: at least one held position carries non-zero swap on its closing deals.
* ``not_exercised``: fewer than ``min_roll`` (3) held positions; too few to tell. Never a flag.
* ``swap_free_inputs``: at least ``min_roll`` held positions and every one of them closed with swap exactly 0.
* ``swap_free_by_design``: the same deals as ``swap_free_inputs``, and the caller's live symbol spec has
  ``swap_long == 0`` and ``swap_short == 0`` (a symbol that is swap-free at the broker). Kept apart from
  ``swap_free_inputs`` so a reader can tell them apart; both are held back (``HELD_BACK``).
* ``unmeasured``: no deals.csv, or one that cannot be read. Never a flag, and never an exception for the caller.

A run whose verdict is in ``HELD_BACK`` produces no qualifier: its catch-up OOS rule reads ``not_judged``
(studio_catchup.CatchupRunner._oos_rule) and the hunt board does not count it (hunt_board_count).

Pure: reads the one deals.csv it is given; never a terminal, MT5 or controller state.
"""
import csv
import math
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'goat-swap-inputs-v1'
MIN_ROLL = 3
SWAP_CHARGED = 'swap_charged'
NOT_EXERCISED = 'not_exercised'
SWAP_FREE_INPUTS = 'swap_free_inputs'
SWAP_FREE_BY_DESIGN = 'swap_free_by_design'
UNMEASURED = 'unmeasured'
VERDICTS = (SWAP_CHARGED, NOT_EXERCISED, SWAP_FREE_INPUTS, SWAP_FREE_BY_DESIGN, UNMEASURED)
HELD_BACK = frozenset((SWAP_FREE_INPUTS, SWAP_FREE_BY_DESIGN))
# The OOS-rule status of a held-back run (CatchupRunner._oos_rule): not judged, never a pass.
NOT_JUDGED = 'not_judged'
COLUMNS = ('server_time_msc', 'position_id', 'deal_entry', 'swap')
MAX_DEALS_BYTES = 256 * 1024 * 1024   # studio_catchup_verdict.MAX_DEALS_CSV


def server_day(msc):
    """The broker server date of a ``server_time_msc`` value."""
    return datetime.fromtimestamp(int(msc) / 1000.0, tz=timezone.utc).date()


def capture_deals(export):
    """The deals.csv of an export record's complete capture (studio_evidence.read_export), else None."""
    capture = (export or {}).get('capture') or {}
    if not capture.get('complete') or not capture.get('path'):
        return None
    path = Path(capture['path']).parent / 'deals.csv'
    return str(path) if _io(path).is_file() else None


def verdict_of(value):
    """The verdict of a ``swapInputs`` / ``swap_inputs`` value: its ``verdict`` (a dict), the value itself (a string)."""
    if isinstance(value, dict):
        value = value.get('verdict')
    return value if isinstance(value, str) else None


def held_back(value):
    """True when a ``swapInputs`` / ``swap_inputs`` value holds the run back (``HELD_BACK``)."""
    return verdict_of(value) in HELD_BACK


def _io(path):
    text = os.path.abspath(str(path))
    if os.name == 'nt' and len(text) > 240 and not text.startswith('\\\\'):
        return Path('\\\\?\\' + text)
    return Path(text)


def _swap_free_spec(spec):
    return isinstance(spec, dict) and all(type(spec.get(key)) in (int, float) and spec[key] == 0
                                          for key in ('swap_long', 'swap_short'))


def _positions(path):
    """{position_id: {open, outs}} as the research sweep builds it; raises on an unreadable or malformed file."""
    source = _io(path)
    if source.stat().st_size > MAX_DEALS_BYTES:
        raise ValueError('deals.csv exceeds its byte bound')
    positions = {}
    with source.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError('deals.csv has no %s column' % ', '.join(missing))
        has_lots = 'lots' in (reader.fieldnames or [])   # optional: a capture without it keeps the verdict, held_lots None
        for row in reader:
            p = positions.setdefault(row['position_id'], dict(open=None, outs=[], lots=None))
            entry = int(row['deal_entry'])
            if entry == 0 and p['open'] is None:
                p['open'] = int(row['server_time_msc'])
                if has_lots:
                    lots = float(row['lots'])
                    if not math.isfinite(lots):
                        raise ValueError('lots is not a finite number: %r' % row['lots'])
                    p['lots'] = lots
            elif entry in (1, 2, 3):
                swap = float(row['swap'])
                if not math.isfinite(swap):
                    raise ValueError('swap is not a finite number: %r' % row['swap'])
                p['outs'].append((int(row['server_time_msc']), swap))
    return positions


def _lots_text(held_lots):
    return '' if held_lots is None else ' (%.2f lots opened in all)' % held_lots


def _plain(verdict, held, charged, total, min_roll, reason=None, held_lots=None):
    if verdict == UNMEASURED:
        return 'Swap inputs unmeasured (%s); not a flag.' % reason
    if verdict == NOT_EXERCISED:
        what = ('no position was' if held == 0 else 'only 1 position was' if held == 1 else 'only %d positions were' % held)
        return ('Swap inputs not exercised: %s held over a server rollover (%d needed to tell); not a flag.' % (what, min_roll))
    if verdict == SWAP_CHARGED:
        return ('Swap charged: %d of the %d positions held over a server rollover closed with swap (%+.2f in all).'
                % (charged, held, total))
    if verdict == SWAP_FREE_INPUTS:
        return ('Swap-free inputs: all %d positions held over a server rollover%s closed with zero swap, so the tester ran '
                'on a symbol spec that charged no swap and the result is optimistic. Held back until re-run on a spec '
                'that charges the broker\'s swap.' % (held, _lots_text(held_lots)))
    return ('Swap-free by design: all %d positions held over a server rollover%s closed with zero swap, and the live '
            'symbol spec has swap long 0 and swap short 0. Held back until re-run or reviewed: the deals alone cannot '
            'tell a swap-free symbol from a stale spec.' % (held, _lots_text(held_lots)))


def classify(deals_csv_path, *, min_roll=MIN_ROLL, live_spec=None):
    """The swap verdict of one run from its deals.csv (module docstring). Never raises for a missing or unreadable
    file: that is ``unmeasured``. ``live_spec``: the symbol's live spec ({swap_long, swap_short, ...}) when the
    caller has one; echoed back, and only a spec with both swaps 0 turns ``swap_free_inputs`` into
    ``swap_free_by_design``."""
    if type(min_roll) is not int or min_roll < 1:
        raise ValueError('min_roll must be a whole number of at least 1')
    echo = dict(live_spec) if isinstance(live_spec, dict) else None
    result = dict(schema=SCHEMA, verdict=UNMEASURED, positions=None, held_over_rollover=None, with_swap=None,
                  swap_total=None, held_lots=None, min_roll=min_roll, live_spec=echo)
    if not deals_csv_path:
        return dict(result, plain=_plain(UNMEASURED, 0, 0, 0, min_roll, 'no complete capture deals.csv'))
    try:
        positions = _positions(deals_csv_path)
    except OSError as exc:
        return dict(result, plain=_plain(UNMEASURED, 0, 0, 0, min_roll, 'deals.csv could not be read: %s'
                                         % (exc.strerror or type(exc).__name__)))
    except (ValueError, KeyError, TypeError, csv.Error, UnicodeError) as exc:
        return dict(result, plain=_plain(UNMEASURED, 0, 0, 0, min_roll, 'deals.csv is malformed: %s: %s'
                                         % (type(exc).__name__, str(exc)[:120])))
    held, charged, total, lots, lots_known = 0, 0, 0.0, 0.0, True
    for p in positions.values():
        if p['open'] is None or not p['outs']:
            continue
        last = max(t for t, _ in p['outs'])
        if server_day(last) > server_day(p['open']):
            held += 1
            total += sum(x for _, x in p['outs'])
            if sum(abs(x) for _, x in p['outs']) > 0:
                charged += 1
            if p['lots'] is None:
                lots_known = False
            else:
                lots += p['lots']
    if held < min_roll:
        verdict = NOT_EXERCISED
    elif charged == 0:
        verdict = SWAP_FREE_BY_DESIGN if _swap_free_spec(live_spec) else SWAP_FREE_INPUTS
    else:
        verdict = SWAP_CHARGED
    total = round(total, 2) + 0.0   # money in cents; + 0.0 turns -0.0 into 0.0
    # held_lots (Claude-Mac's review on GOAT-EA#351): the opening lots of the held positions, so a reader can see the two
    # known false hold-backs (tiny overnight positions whose swap rounds to 0.00; a strategy holding only a zero-swap side).
    held_lots = round(lots, 2) + 0.0 if lots_known else None
    return dict(result, verdict=verdict, positions=len(positions), held_over_rollover=held, with_swap=charged,
                swap_total=total, held_lots=held_lots,
                plain=_plain(verdict, held, charged, total, min_roll, held_lots=held_lots))
