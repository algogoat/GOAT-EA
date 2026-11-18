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
* ``unmeasured``: no capture, or no deals.csv (models other than 4 have none). Never a flag, never an exception.
* ``unreadable``: a deals.csv that is present but cannot be read, or is malformed (a non-integer time or entry, a
  non-finite swap, a missing column). Held back (``HELD_BACK``): the catch-up's own verdict parsers tolerate some of
  these (a non-integer ``deal_entry``, an ``inf`` swap), so the swap check must not let such a run through unmeasured
  (Claude-Mac goatai#2750 6976984165). Never an exception for the caller either.

**The recorded spec (B56 swap-spec, GOAT-EA#354; Claude-Mac goatai#2750 6978371254).** From B56 the EA writes the
symbol spec the tester ran on into the capture's run.csv (``symbol_swap_mode``, ``symbol_swap_long``,
``symbol_swap_short``, ``symbol_swap_rollover3days``, ``symbol_contract_size``, ``symbol_digits``, ``symbol_point``).
``classify`` reads it from the run.csv beside the deals.csv it is given (``tester_spec``). With no recorded spec (every
capture before B56) the verdict is exactly the deal inference above. With one, each side is judged on its own, from the
opening deal's ``deal_type`` (0 long, 1 short) of every held position:

* the spec charges no swap on a side (mode 0, or that side's rate 0) and a position was held there: that side ran
  swap-free by its spec, from the first held position (no 3-position floor: the spec says it, the deals need not show
  it). ``swap_free_by_design`` when the caller's live spec has that side's rate 0, else ``swap_free_inputs``;
* the spec charges a side: ``swap_charged`` when a held position there paid swap; ``swap_free_inputs`` when 3 or more
  were held there and none paid (the spec and the booked swap disagree); ``not_exercised`` below 3;
* the run's verdict is the first of ``swap_free_inputs``, ``swap_free_by_design``, ``swap_charged`` any side has, else
  ``not_exercised``. ``sides`` records each side's counts and verdict, so a reader sees which case it is.

The recorded spec is the terminal's claim; the booked swap is what happened. Where they disagree (a charging side with
3 or more zero-swap held positions, or a non-charging side whose held positions paid swap) the verdict follows the
deals and ``notes`` carries ``spec_contradiction``. A run.csv that cannot be read, or a spec that is partial, duplicated
or out of range, or a held position whose side cannot be read while a spec is recorded, is ``unreadable``.

A run whose verdict is in ``HELD_BACK`` produces no qualifier: its catch-up OOS rule reads ``not_judged``
(studio_catchup.CatchupRunner._oos_rule) and the hunt board does not count it (hunt_board_count).

Pure: reads the one deals.csv it is given and the run.csv beside it; never a terminal, MT5 or controller state.
"""
import csv
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'goat-swap-inputs-v1'
MIN_ROLL = 3
SWAP_CHARGED = 'swap_charged'
NOT_EXERCISED = 'not_exercised'
SWAP_FREE_INPUTS = 'swap_free_inputs'
SWAP_FREE_BY_DESIGN = 'swap_free_by_design'
UNMEASURED = 'unmeasured'
UNREADABLE = 'unreadable'
VERDICTS = (SWAP_CHARGED, NOT_EXERCISED, SWAP_FREE_INPUTS, SWAP_FREE_BY_DESIGN, UNMEASURED, UNREADABLE)
HELD_BACK = frozenset((SWAP_FREE_INPUTS, SWAP_FREE_BY_DESIGN, UNREADABLE))
# The OOS-rule status of a held-back run (CatchupRunner._oos_rule): not judged, never a pass.
NOT_JUDGED = 'not_judged'
COLUMNS = ('server_time_msc', 'position_id', 'deal_entry', 'swap')
MAX_DEALS_BYTES = 256 * 1024 * 1024   # studio_catchup_verdict.MAX_DEALS_CSV
# The recorded spec (B56 swap-spec, GOAT_SequenceExport.mqh): the run.csv keys, in the order the EA writes them.
SPEC_KEYS = ('symbol_swap_mode', 'symbol_swap_long', 'symbol_swap_short', 'symbol_swap_rollover3days',
             'symbol_contract_size', 'symbol_digits', 'symbol_point')
SWAP_MODE_DISABLED = 0                # ENUM_SYMBOL_SWAP_MODE: SYMBOL_SWAP_MODE_DISABLED
MAX_RUN_BYTES = 64 * 1024             # studio_evidence._key_values
SIDES = ('long', 'short')
DEAL_SIDES = {'0': 'long', '1': 'short'}   # the opening deal's deal_type: DEAL_TYPE_BUY, DEAL_TYPE_SELL
NOT_HELD = 'not_held'                 # a side's verdict when no position was held over a rollover on it
SPEC_CONTRADICTION = 'spec_contradiction'


def server_day(msc):
    """The broker server date of a ``server_time_msc`` value."""
    return datetime.fromtimestamp(int(msc) / 1000.0, tz=timezone.utc).date()


def capture_deals(export):
    """The deals.csv path of an export record's complete capture (studio_evidence.read_export), else None. No existence
    probe here either: classify() reads it, and a missing file reads `unmeasured`, an unreadable one `unreadable`."""
    capture = (export or {}).get('capture') or {}
    if not capture.get('complete') or not capture.get('path'):
        return None
    return str(Path(capture['path']).parent / 'deals.csv')


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


def _live_zero(spec, side):
    """The caller's live spec charges no swap on ``side`` (its rate is a number and exactly 0)."""
    return isinstance(spec, dict) and type(spec.get('swap_' + side)) in (int, float) and spec['swap_' + side] == 0


def _whole(text):
    text = (text or '').strip()
    if not re.fullmatch(r'-?[0-9]{1,18}', text):
        raise ValueError('not a whole number: %r' % text[:40])
    return int(text)


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('not a finite number: %r' % (text or '')[:40])
    return value


def tester_spec(deals_csv_path):
    """The symbol spec the run was charged from, as the EA recorded it in the run.csv beside ``deals_csv_path`` (B56
    swap-spec), or None when the capture records none (no run.csv, or a run.csv without the keys: every capture before
    B56). Raises OSError when the run.csv is present but cannot be read, ValueError when the spec is partial, duplicated,
    not a number where a number belongs, or out of range. No existence probe (Codex P2 on GOAT-EA#353)."""
    source = _io(Path(str(deals_csv_path)).parent / 'run.csv')
    try:
        with source.open('rb') as stream:
            raw = stream.read(MAX_RUN_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_RUN_BYTES:
        raise ValueError('run.csv exceeds its byte bound')
    values = {}
    for line in raw.decode('utf-8-sig').splitlines()[1:]:
        key, sep, value = line.partition(',')
        if sep and key in SPEC_KEYS:
            if key in values:
                raise ValueError('run.csv records %s twice' % key)
            values[key] = value
    if not values:
        return None
    missing = [key for key in SPEC_KEYS if key not in values]
    if missing:
        raise ValueError('run.csv records only part of the symbol spec (no %s)' % ', '.join(missing))
    spec = dict(swap_mode=_whole(values['symbol_swap_mode']), swap_long=_finite(values['symbol_swap_long']),
                swap_short=_finite(values['symbol_swap_short']),
                swap_rollover3days=_whole(values['symbol_swap_rollover3days']),
                contract_size=_finite(values['symbol_contract_size']), digits=_whole(values['symbol_digits']),
                point=_finite(values['symbol_point']))
    if (spec['swap_mode'] < 0 or not 0 <= spec['swap_rollover3days'] <= 6 or spec['contract_size'] <= 0
            or not 0 <= spec['digits'] <= 16 or spec['point'] <= 0):
        raise ValueError('the recorded symbol spec is out of range')
    return spec


def _charges(spec, side):
    """The recorded spec charges swap on ``side``: swap is enabled (mode not 0) and that side's rate is not 0."""
    return spec['swap_mode'] != SWAP_MODE_DISABLED and spec['swap_' + side] != 0


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
        has_type = 'deal_type' in (reader.fieldnames or [])   # the side; read only when a spec is recorded (classify)
        for row in reader:
            p = positions.setdefault(row['position_id'], dict(open=None, outs=[], lots=None, side=None))
            entry = int(row['deal_entry'])
            if entry == 0 and p['open'] is None:
                p['open'] = int(row['server_time_msc'])
                if has_type:   # lenient here: an unknown side never changes a verdict made without a recorded spec
                    p['side'] = DEAL_SIDES.get((row['deal_type'] or '').strip())
                if has_lots:   # diagnostic only: an unreadable value is unknown (held_lots None), never a verdict change
                    try:
                        lots = float(row['lots'])
                    except (TypeError, ValueError):
                        lots = None
                    p['lots'] = lots if lots is not None and math.isfinite(lots) else None
            elif entry in (1, 2, 3):
                swap = float(row['swap'])
                if not math.isfinite(swap):
                    raise ValueError('swap is not a finite number: %r' % row['swap'])
                p['outs'].append((int(row['server_time_msc']), swap))
    return positions


def _plain(verdict, held, charged, total, min_roll, reason=None, held_lots=None):
    lots = '' if held_lots is None else ' (%.2f lots opened in all)' % held_lots
    if verdict == UNMEASURED:
        return 'Swap inputs unmeasured (%s); not a flag.' % reason
    if verdict == UNREADABLE:
        return ('Swap inputs unreadable (%s): the capture is present but could not be read whole, so the swap the tester '
                'charged is unknown. Held back until the capture is re-read or the member is re-run.' % reason)
    if verdict == NOT_EXERCISED:
        what = ('no position was' if held == 0 else 'only 1 position was' if held == 1 else 'only %d positions were' % held)
        return ('Swap inputs not exercised: %s held over a server rollover (%d needed to tell); not a flag.' % (what, min_roll))
    if verdict == SWAP_CHARGED:
        return ('Swap charged: %d of the %d positions held over a server rollover closed with swap (%+.2f in all).'
                % (charged, held, total))
    if verdict == SWAP_FREE_INPUTS:
        return ('Swap-free inputs: all %d positions held over a server rollover%s closed with zero swap, so the tester ran '
                'on a symbol spec that charged no swap and the result is optimistic. Held back until re-run on a spec '
                'that charges the broker\'s swap.' % (held, lots))
    return ('Swap-free by design: all %d positions held over a server rollover%s closed with zero swap, and the live '
            'symbol spec has swap long 0 and swap short 0. Held back until re-run or reviewed: the deals alone cannot '
            'tell a swap-free symbol from a stale spec.' % (held, lots))


def _side_plain(side, view, spec, min_roll):
    rate = '%s %g' % ('swap ' + side, spec['swap_' + side])
    held, paid, verdict = view['held'], view['with_swap'], view['verdict']
    positions = '%d held position%s' % (held, '' if held == 1 else 's')
    if verdict == NOT_HELD:
        return '%s: no position held over a rollover' % side
    if not view['tester_charges']:
        what = 'the spec charges no swap (mode %d, %s)' % (spec['swap_mode'], rate)
        if verdict == SWAP_CHARGED:
            return '%s: %s, yet %d of the %s paid swap' % (side, what, paid, positions)
        agrees = 'the live spec agrees' if verdict == SWAP_FREE_BY_DESIGN else 'no live spec shows this side swap-free'
        return '%s: %s and the %s closed with zero swap, as the spec says; %s' % (side, what, positions, agrees)
    if verdict == SWAP_CHARGED:
        return '%s: the spec charges %s and %d of the %s paid swap' % (side, rate, paid, positions)
    if verdict == SWAP_FREE_INPUTS:
        return '%s: the spec charges %s, but all %s closed with zero swap' % (side, rate, positions)
    return '%s: the spec charges %s; only %s, none with swap (%d needed to tell)' % (side, rate, positions, min_roll)


def _plain_spec(verdict, sides, spec, notes, total, min_roll):
    """The plain text of a run with a recorded spec: the run's verdict, then each side's case."""
    lead = {SWAP_FREE_INPUTS: 'Swap-free inputs', SWAP_FREE_BY_DESIGN: 'Swap-free by design', SWAP_CHARGED: 'Swap charged',
            NOT_EXERCISED: 'Swap inputs not exercised'}[verdict]
    text = '%s, by the recorded symbol spec: %s.' % (lead, '; '.join(_side_plain(s, sides[s], spec, min_roll) for s in SIDES))
    if SPEC_CONTRADICTION in notes:
        text += (' The recorded spec and the booked swap disagree (%s); the booked swap decides.' % SPEC_CONTRADICTION)
    if verdict == SWAP_CHARGED:
        return text + ' Swap %+.2f in all.' % total
    if verdict == NOT_EXERCISED:
        return text + ' Not a flag.'
    if verdict == SWAP_FREE_INPUTS:
        return text + (' The result is optimistic. Held back until re-run on a spec that charges the broker\'s swap.')
    return text + ' Held back until re-run or reviewed.'


def classify(deals_csv_path, *, min_roll=MIN_ROLL, live_spec=None):
    """The swap verdict of one run from its deals.csv (module docstring). Never raises for the file: no path or no
    file is ``unmeasured`` (not a flag); a file that is present but unreadable or malformed is ``unreadable`` (held
    back). ``live_spec``: the symbol's live spec ({swap_long, swap_short, ...}) when the caller has one; echoed back.
    Without a recorded spec only a live spec with both swaps 0 turns ``swap_free_inputs`` into ``swap_free_by_design``;
    with one, a side the recorded spec does not charge is by design when the live spec's rate for that side is 0.
    ``tester_spec``, ``sides`` and ``notes``: the recorded spec, each side's counts and verdict, ``spec_contradiction``."""
    if type(min_roll) is not int or min_roll < 1:
        raise ValueError('min_roll must be a whole number of at least 1')
    echo = dict(live_spec) if isinstance(live_spec, dict) else None
    result = dict(schema=SCHEMA, verdict=UNMEASURED, positions=None, held_over_rollover=None, with_swap=None,
                  swap_total=None, held_lots=None, min_roll=min_roll, live_spec=echo, tester_spec=None, sides=None, notes=[])
    if not deals_csv_path:
        return dict(result, plain=_plain(UNMEASURED, 0, 0, 0, min_roll, 'no complete capture deals.csv'))
    # No existence probe before the read (Codex P2 on GOAT-EA#353): exists()/is_file() raise PermissionError on Python
    # <= 3.13 and return False on 3.14 for a file in a directory we may not read, which would turn an unreadable capture
    # into "unmeasured". The read itself tells the two apart: FileNotFoundError is "no deals.csv", any other OSError is
    # a file we could not read.
    try:
        positions = _positions(deals_csv_path)
    except FileNotFoundError:
        return dict(result, plain=_plain(UNMEASURED, 0, 0, 0, min_roll, 'no complete capture deals.csv'))
    except OSError as exc:
        return dict(result, verdict=UNREADABLE, plain=_plain(UNREADABLE, 0, 0, 0, min_roll, 'deals.csv could not be read: %s'
                                                              % (exc.strerror or type(exc).__name__)))
    except (ValueError, KeyError, TypeError, csv.Error, UnicodeError) as exc:
        return dict(result, verdict=UNREADABLE, plain=_plain(UNREADABLE, 0, 0, 0, min_roll, 'deals.csv is malformed: %s: %s'
                                                              % (type(exc).__name__, str(exc)[:120])))
    # The recorded spec (B56 swap-spec), from the run.csv beside deals.csv; None for every capture before B56.
    try:
        spec = tester_spec(deals_csv_path)
    except OSError as exc:
        return dict(result, verdict=UNREADABLE, plain=_plain(UNREADABLE, 0, 0, 0, min_roll, 'run.csv could not be read: %s'
                                                              % (exc.strerror or type(exc).__name__)))
    except (ValueError, UnicodeError) as exc:
        return dict(result, verdict=UNREADABLE, plain=_plain(UNREADABLE, 0, 0, 0, min_roll,
                                                              'the symbol spec in run.csv is malformed: %s' % str(exc)[:120]))
    held, charged, total, lots, lots_known = 0, 0, 0.0, 0.0, True
    sides, unknown_side = {side: dict(held=0, with_swap=0) for side in SIDES}, 0
    for p in positions.values():
        if p['open'] is None or not p['outs']:
            continue
        last = max(t for t, _ in p['outs'])
        if server_day(last) > server_day(p['open']):
            held += 1
            total += sum(x for _, x in p['outs'])
            paid = sum(abs(x) for _, x in p['outs']) > 0
            if paid:
                charged += 1
            if p['side'] in sides:
                sides[p['side']]['held'] += 1
                sides[p['side']]['with_swap'] += int(paid)
            else:
                unknown_side += 1
            if p['lots'] is None:
                lots_known = False
            else:
                lots += p['lots']
    if spec is not None and unknown_side:
        return dict(result, tester_spec=spec, verdict=UNREADABLE,
                    plain=_plain(UNREADABLE, 0, 0, 0, min_roll, 'the side of %d held position(s) in deals.csv could not be '
                                 'read, so the recorded spec cannot be applied per side' % unknown_side))
    notes, side_view = [], None
    if spec is None:
        if held < min_roll:
            verdict = NOT_EXERCISED
        elif charged == 0:
            verdict = SWAP_FREE_BY_DESIGN if _swap_free_spec(live_spec) else SWAP_FREE_INPUTS
        else:
            verdict = SWAP_CHARGED
    else:
        # Per side (Claude-Mac goatai#2750 6978371254 notes 2 and 3): the spec says what the tester could charge on each
        # side, the deals what it booked; where they disagree the deals decide and the note says so.
        side_view = {}
        for side in SIDES:
            count, paid = sides[side]['held'], sides[side]['with_swap']
            charges = _charges(spec, side)
            if count == 0:
                status = NOT_HELD
            elif not charges:
                if paid:
                    status = SWAP_CHARGED
                    notes.append(SPEC_CONTRADICTION)
                else:
                    status = SWAP_FREE_BY_DESIGN if _live_zero(live_spec, side) else SWAP_FREE_INPUTS
            elif paid:
                status = SWAP_CHARGED
            elif count >= min_roll:
                status = SWAP_FREE_INPUTS
                notes.append(SPEC_CONTRADICTION)
            else:
                status = NOT_EXERCISED
            side_view[side] = dict(held=count, with_swap=paid, tester_charges=charges, verdict=status)
        found = [view['verdict'] for view in side_view.values()]
        verdict = next((v for v in (SWAP_FREE_INPUTS, SWAP_FREE_BY_DESIGN, SWAP_CHARGED) if v in found), NOT_EXERCISED)
        notes = sorted(set(notes))
    total = round(total, 2) + 0.0   # money in cents; + 0.0 turns -0.0 into 0.0
    # held_lots (Claude-Mac's review on GOAT-EA#351): the opening lots of the held positions, so a reader can see the two
    # known false hold-backs (tiny overnight positions whose swap rounds to 0.00; a strategy holding only a zero-swap side).
    held_lots = round(lots, 2) + 0.0 if lots_known else None
    plain = (_plain(verdict, held, charged, total, min_roll, held_lots=held_lots) if spec is None
             else _plain_spec(verdict, side_view, spec, notes, total, min_roll))
    return dict(result, verdict=verdict, positions=len(positions), held_over_rollover=held, with_swap=charged,
                swap_total=total, held_lots=held_lots, tester_spec=spec, sides=side_view, notes=notes, plain=plain)
