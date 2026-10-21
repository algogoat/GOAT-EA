"""One binding lock per installation: bootstrap, switch-verify-park and switch-apply never overlap
(Claude-Mac goatai#2587 6304681152).

The shared ``session_lock`` (studio_handover.session_lock) lets two bootstraps run together, and an app-side
process scan cannot be the guard (killed launchers, OEM code pages, elevated processes). So each of these three
commands holds an exclusive OS lock owned by its own Python process for the whole command:

* Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` on byte 0 of the lock file. A byte-range lock belongs to the handle,
  so a second handle (another process, or another thread of this one) is refused, while an antivirus or indexer
  that merely opens the file is not mistaken for a holder (an exclusive-share CreateFile would be).
* Elsewhere (macOS/Linux dev and CI runs): ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.

The OS drops either lock when the holding process exits, however it exits. Only the OS lock counts: the file's
existence means nothing, and nothing ever deletes it. Nothing waits: a busy lock refuses at once with
BINDING_IN_PROGRESS, so this lock can never take part in a deadlock whatever else the command holds.

The file is ``<parent of controller_state_root>/.studio-binding/<state root name>/binding.lock``, derived only from
the installation's own ``controller_state_root``. It sits beside the state root, like the handover archive
(``.studio-handover``), because switch-apply moves the whole state root into the archive and back, and a held
handle inside it would block that rename on Windows and change the parked tree.

Re-entrant within a thread: the CLI takes it before any state read, and the functions it calls take it again.
"""
from contextlib import contextmanager
import errno
import functools
import os
from pathlib import Path
import threading

from studio_refusal import Refusal

BINDING_OPERATIONS = frozenset(('bootstrap', 'switch-verify-park', 'switch-apply'))
LOCK_FOLDER = '.studio-binding'
LOCK_NAME = 'binding.lock'
BUSY_CODE = 'BINDING_IN_PROGRESS'
BUSY = 'GOAT is still finishing an earlier step on this terminal; wait, then check again. Nothing was changed.'
_HELD = {}                      # normalized lock path -> dict(depth, thread, purpose)
_GUARD = threading.Lock()
_BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN, getattr(errno, 'EDEADLOCK', errno.EDEADLK), errno.EDEADLK}


class BindingInProgress(Refusal):
    """Another bootstrap, switch-verify-park or switch-apply holds this installation's binding lock."""


def lock_path(c):
    """The lock file of this installation, from its controller_state_root only (never from a command argument)."""
    root = Path(os.path.abspath(c.install['controller_state_root']))
    return root.parent / LOCK_FOLDER / root.name / LOCK_NAME


def _try_lock(fd):
    try:
        import msvcrt
    except ImportError:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError as error:
        if error.errno in _BUSY_ERRNOS:
            return False
        raise


def _unlock(fd):
    try:
        import msvcrt
    except ImportError:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _busy(purpose, holder=None):
    fields = dict(operation=str(purpose))
    if holder is not None:
        fields['holder'] = holder
    return BindingInProgress(BUSY, BUSY_CODE, **fields)


@contextmanager
def binding_lock(c, *, purpose):
    """Hold this installation's binding lock for the block, or raise BindingInProgress at once."""
    path = lock_path(c)
    key = os.path.normcase(str(path))
    me = threading.get_ident()
    with _GUARD:
        entry = _HELD.get(key)
        if entry is not None:
            if entry['thread'] != me:
                raise _busy(purpose, entry['purpose'])
            entry['depth'] += 1
    if entry is not None:
        try:
            yield
        finally:
            with _GUARD:
                _HELD[key]['depth'] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open handles are not inherited by child processes (PEP 446): a PowerShell or MT5 child never keeps it.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        if not _try_lock(fd):
            raise _busy(purpose)
        try:
            with _GUARD:
                if key in _HELD:                       # another thread of this process won meanwhile
                    raise _busy(purpose, _HELD[key]['purpose'])
                _HELD[key] = dict(depth=1, thread=me, purpose=str(purpose))
            try:
                yield
            finally:
                with _GUARD:
                    _HELD.pop(key, None)
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def holds_binding_lock(purpose):
    """Decorator: the wrapped function (first argument: the controller) runs under binding_lock."""
    def decorate(function):
        @functools.wraps(function)
        def held(c, *args, **kwargs):
            with binding_lock(c, purpose=purpose):
                return function(c, *args, **kwargs)
        return held
    return decorate
