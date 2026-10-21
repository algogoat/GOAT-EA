"""Member switch hold: start the next member's MT5 in a publisher quiet slot (goatai#1885).

Claude-Mac's mechanism (#1885 6022613005, approved 6036112715): the end of one member and
the MT5 launch of the next are the I/O-heavy moment, and on the PC that runs the public
experiment publishers they caused three publisher overruns on 2026-10-07 (6036060067).
Exp 02 starts a cycle at :01 of every odd minute (45 s budget) and Exp 01 at every even
minute (90 s budget), so the quiet slot is seconds QUIET_SLOT_OPEN..QUIET_SLOT_CLOSE of an
odd minute, once Exp 02's cycle has ended.

Wide slots (goatai#2350 6094434583, Claude-Mac 6094451003): with Exp 01's cycle log configured
too (``exp01_state_path``), a member may start from WIDE_ODD_OPEN of an odd minute or
WIDE_EVEN_OPEN of an even minute until QUIET_SLOT_CLOSE, and only once BOTH publishers' newest
cycles have their END row, so an Exp 01 cycle that overruns into the odd minute blocks the odd
slot too. Without ``exp01_state_path`` the narrow odd slot above is unchanged: dropping that one
setting is the rollback.

Throughput only, so every rule fails open:
* Off unless configured. Testers have no publishers and never hold. A PC enables it with
  ``GOAT_SWITCH_HOLD=exp02`` or a ``switch-hold.json`` lane config beside the demo agent's
  state (``{"mode": "exp02", "state_path": "...", "exp01_state_path": "...", "max_seconds": 90}``);
  the variable wins. ``exp01_state_path`` (``GOAT_SWITCH_HOLD_STATE_EXP01``) needs ``state_path``.
* A hold never lasts longer than MAX_HOLD_SECONDS from the moment the member was ready.
* With ``state_path`` (the Exp 02 publisher's own ``cycle-identities.jsonl``), the slot also
  waits for that cycle's END row; its tail is read only, never written or locked. A state
  that cannot be read means no hold. Without ``state_path`` the clock slot alone decides.
* A publisher whose newest cycle started over PUBLISHER_IDLE_SECONDS ago is not cycling, so
  nothing is held for it.
* Any other doubt (bad config, a clock that went back, a malformed retained hold) starts now.

The caller (studio_seed's member loop) re-checks stop, cancel and pause on every pass of
the hold, so a hold never delays them.
"""
import json
import math
import os
from pathlib import Path

ENV_MODE = 'GOAT_SWITCH_HOLD'
ENV_STATE = 'GOAT_SWITCH_HOLD_STATE'
ENV_MAX = 'GOAT_SWITCH_HOLD_MAX_SECONDS'
ENV_STATE_EXP01 = 'GOAT_SWITCH_HOLD_STATE_EXP01'
CONFIG_NAME = 'switch-hold.json'
MODES = ('exp02',)
OFF = ('', '0', 'off', 'none', 'false')
MAX_HOLD_SECONDS = 90
QUIET_SLOT_OPEN = 35
QUIET_SLOT_CLOSE = 55
WIDE_ODD_OPEN = 20      # wide slots: never before :20 of an odd minute or :40 of an even one
WIDE_EVEN_OPEN = 40
PUBLISHER_IDLE_SECONDS = 300
# A retained hold older than its bound plus this was interrupted (pause, stop, driver gone):
# the next ready member gets a fresh, equally bounded hold.
STALE_HOLD_SECONDS = 30
TAIL_BYTES = 16384
MAX_CONFIG_BYTES = 4096


def _max_seconds(value):
    if value is None:
        return MAX_HOLD_SECONDS
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('max_seconds must be a positive number')
    return min(number, MAX_HOLD_SECONDS)


def load_config(env=None, config_path=None):
    """The hold configuration, or None (off). Never raises: a bad setting is off (fail open)."""
    env = os.environ if env is None else env
    try:
        mode = env.get(ENV_MODE)
        if mode is not None:
            mode = mode.strip().lower()
            if mode in OFF or mode not in MODES:
                return None
            state = (env.get(ENV_STATE) or '').strip() or None
            exp01 = (env.get(ENV_STATE_EXP01) or '').strip() or None
            if exp01 and not state:
                return None
            return dict(mode=mode, state_path=state, exp01_state_path=exp01, max_seconds=_max_seconds(env.get(ENV_MAX) or None),
                        source='environment')
        if config_path is None or not Path(config_path).is_file():
            return None
        with Path(config_path).open('rb') as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            return None
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data, dict) or data.get('mode') not in MODES:
            return None
        state, exp01 = data.get('state_path'), data.get('exp01_state_path')
        for path in (state, exp01):
            if path is not None and (not isinstance(path, str) or not path.strip()):
                return None
        if exp01 is not None and state is None:
            return None
        return dict(mode=data['mode'], state_path=state, exp01_state_path=exp01, max_seconds=_max_seconds(data.get('max_seconds')),
                    source=str(config_path))
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
        return None


def read_cycles(path, tail_bytes=TAIL_BYTES):
    """The newest publisher cycle rows from the end of its append-only log; read only."""
    with Path(path).open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        start = max(0, size - tail_bytes)
        stream.seek(start)
        raw = stream.read(tail_bytes)
    lines = raw.decode('utf-8', errors='replace').splitlines()
    if start > 0 and lines:
        lines = lines[1:]   # the first line may be cut
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and type(row.get('startedAt')) is int and row.get('event') in ('START', 'END', 'LAUNCHER_EXCEPTION'):
            rows.append(row)
    if not rows:
        raise ValueError('No publisher cycle rows')
    return rows


def _in_clock_slot(now, wide=False):
    minute, second = divmod(now, 60)
    if int(minute) % 2 == 1:
        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second < QUIET_SLOT_CLOSE
    return wide and WIDE_EVEN_OPEN <= second < QUIET_SLOT_CLOSE


def quiet(now, config, read=read_cycles):
    """(quiet, reason, source) for a member launch at ``now`` (wall seconds). Raises only on an
    unreadable publisher state; the caller treats that as no hold."""
    if not config.get('state_path'):
        return (True, 'clock_slot', 'clock') if _in_clock_slot(now) else (False, 'outside_clock_slot', 'clock')
    publishers = [('exp02', config['state_path'])]
    if config.get('exp01_state_path'):
        publishers.insert(0, ('exp01', config['exp01_state_path']))
    wide = len(publishers) == 2
    cycling = []
    for name, path in publishers:
        rows = read(path)
        newest = max(rows, key=lambda row: row['startedAt'])
        if now - newest['startedAt'] / 1000 <= PUBLISHER_IDLE_SECONDS:   # an idle publisher is not waited for
            cycling.append((name, rows, newest))
    if not cycling:
        return True, 'publisher_idle', 'publisher_state'
    if not _in_clock_slot(now, wide):
        return False, 'outside_clock_slot', 'publisher_state'
    for name, rows, newest in cycling:
        ended = any(row['event'] != 'START' and row['startedAt'] == newest['startedAt']
                    and row.get('pid') == newest.get('pid') for row in rows)
        if not ended:
            return False, name + '_cycle_running', 'publisher_state'
    return True, ('exp01_exp02_cycles_ended' if wide else 'exp02_cycle_ended'), 'publisher_state'


def decide(config, retained, *, member_id, now, read=read_cycles):
    """One pass of the hold for the member ready to start.

    Returns dict(start=bool, hold=<record to retain while holding, else None>,
    journal=(event, details) or None). ``retained`` is the hold this batch retained.
    """
    if config is None:
        return dict(start=True, hold=None, journal=None)
    try:
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError('clock not finite')
        hold = None
        if isinstance(retained, dict) and retained.get('member_id') == member_id:
            since, until = retained.get('since_unix'), retained.get('deadline_unix')
            if (type(since) not in (int, float) or type(until) not in (int, float) or not math.isfinite(since)
                    or not math.isfinite(until) or not 0 <= until - since <= MAX_HOLD_SECONDS):
                return _release(None, now, 'fail_open: retained hold unreadable', 'none')
            if now < since:
                return _release(None, now, 'fail_open: clock went back', 'none')
            if now <= until + STALE_HOLD_SECONDS:
                hold = retained
        new = hold is None
        if new:
            hold = dict(member_id=member_id, since_unix=now, deadline_unix=now + config['max_seconds'],
                        mode=config['mode'])
        if now >= hold['deadline_unix']:
            return _release(hold, now, 'bound', hold.get('source', 'clock'))
        try:
            ok, reason, source = quiet(now, config, read)
        except Exception as error:
            return _release(hold, now, 'fail_open: publisher state unreadable (' + type(error).__name__ + ')', 'publisher_state')
        if ok:
            return _release(hold, now, reason, source)
        hold = dict(hold, reason=reason, source=source)
        journal = ('switch_hold', dict(member_id=member_id, phase='holding', reason=reason, source=source,
                                       bound_seconds=round(hold['deadline_unix'] - hold['since_unix'], 3))) if new else None
        return dict(start=False, hold=hold, journal=journal)
    except Exception as error:
        return _release(None, now if isinstance(now, (int, float)) else 0, 'fail_open: ' + type(error).__name__, 'none')


def _release(hold, now, reason, source):
    waited = 0 if hold is None else max(0, now - hold['since_unix'])   # actual, never rounded down to the bound
    details = dict(phase='released', waited_ms=int(round(waited * 1000)), reason=reason, source=source)
    if hold is not None:
        details['member_id'] = hold['member_id']
    return dict(start=True, hold=None, journal=('switch_hold', details))
