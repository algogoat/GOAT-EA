"""One terminal lease per installation, for both lanes (goatai#2350, Claude-Mac 6098964146 / 6099078698).

The MetaTrader5 adapter's ``initialize(path)`` STARTS the terminal when it is not running, and a seed, catch-up or
hold-up driver closes MT5 after every member and relaunches it for the next. A read that attached in that gap
launched a plain MT5 beside the driver's own launch and stopped the run (Banker, 2026-10-10 05:04Z and 08:21Z).

The lease says "someone owns this MT5's lifecycle right now". It is the byte-0 lock on
``<controller state>\\demo-agent\\terminal.lock``: the same file and byte DemoAgent._exclusive and
studio_agent_setup.demo_terminal_lock have always locked, so a controller process from an older bundle and one from
a newer bundle still exclude each other while an update installs. Every driver that closes or relaunches MT5 holds
it for its whole run; every read that can reach ``initialize`` takes it without waiting and, when it is busy,
refuses with a named code or answers from retained state.

The lease is re-entrant within a process (``nested='join'``): a driver that holds it reaches code paths that take it
again (run-batch -> start_config -> inspect_idle_demo, deploy-load -> close_terminal). ``nested='refuse'`` keeps the
demo agent's historical rule that its own nested ``_exclusive`` refuses. Another thread of the same process holding
it reads as busy. The OS drops the lock when the holding process exits, however it exits.

Lock order (one, everywhere): L1 this lease -> L2 session_lock -> L3 batch-driver-gate -> L4 native-gate. A process
may only wait for a lock while it holds none at that level or later; anything taken out of order is taken without
waiting, so it refuses and never deadlocks.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time

from studio_refusal import Refusal

LEASE_FOLDER = 'demo-agent'
LEASE_NAME = 'terminal.lock'
MAX_WAIT_SECONDS = 600
_HELD = {}                      # normalized lease path -> dict(depth, thread, purpose, handle)
_GUARD = threading.Lock()


class TerminalBusy(Refusal):
    """The terminal lease is held elsewhere (another process, or another thread of this one). A ValueError."""


def lease_path(state_root):
    return Path(state_root) / LEASE_FOLDER / LEASE_NAME


def _key(path):
    return os.path.normcase(os.path.realpath(str(path)))


def held(state_root):
    """True when THIS thread holds the lease of this installation."""
    with _GUARD:
        entry = _HELD.get(_key(lease_path(state_root)))
        return bool(entry) and entry['thread'] == threading.get_ident()


def _try_lock(handle):
    try:
        import msvcrt
    except ImportError:                                      # the studio tests also run off Windows
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock(handle):
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def foreign_holder(state_root):
    """Tests: hold the OS lock through a separate handle and without this process's registry, exactly as a driver in
    another process would. Yields; releases on exit."""
    path = lease_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        if not _try_lock(handle):
            raise RuntimeError('the terminal lease is already held')
        try:
            yield
        finally:
            _unlock(handle)


@contextmanager
def terminal_lease(state_root, *, purpose, wait_seconds=0, nested='join', busy_message=None,
                   busy_code='TERMINAL_LEASE_BUSY', **busy_fields):
    """Hold this installation's terminal lease for the block.

    ``wait_seconds`` (0..600): how long to retry while another holder has it (0: a read, never waits). ``nested``:
    'join' when this thread already holds it (no OS call; released when the outermost holder leaves), or 'refuse'.
    Busy raises TerminalBusy(busy_message, busy_code, **busy_fields)."""
    if nested not in ('join', 'refuse'):
        raise ValueError('nested must be join or refuse')
    if type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError('wait_seconds must be between 0 and %d' % MAX_WAIT_SECONDS)
    message = busy_message or ('Another GOAT operation owns this terminal now (' + str(purpose) + ' was refused); '
                               'nothing was changed.')
    path = lease_path(state_root)
    key = _key(path)
    me = threading.get_ident()
    with _GUARD:
        entry = _HELD.get(key)
        if entry is not None:
            if entry['thread'] != me or nested == 'refuse':
                raise TerminalBusy(message, busy_code, holder=entry['purpose'], **busy_fields)
            entry['depth'] += 1
            joined = True
        else:
            joined = False
    if joined:
        try:
            yield
        finally:
            with _GUARD:
                _HELD[key]['depth'] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    try:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        deadline = time.monotonic() + wait_seconds
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise TerminalBusy(message, busy_code, **busy_fields)
            time.sleep(.1)
        with _GUARD:
            if key in _HELD:                                   # another thread won the lock in this process meanwhile
                _unlock(handle)
                raise TerminalBusy(message, busy_code, holder=_HELD[key]['purpose'], **busy_fields)
            _HELD[key] = dict(depth=1, thread=me, purpose=str(purpose), handle=handle)
        try:
            yield
        finally:
            with _GUARD:
                _HELD.pop(key, None)
            _unlock(handle)
    finally:
        handle.close()
