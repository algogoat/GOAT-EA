"""Exclusive file gate shared with MQL FileOpen without FILE_SHARE_* flags.

Serializes cooperating controller commits and terminal launch consumption. It
does not coordinate legacy EA writers or establish native tester ownership.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path


@contextmanager
def exclusive_gate(root):
    path=Path(root)/'launch.lock'
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                         wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        close=kernel.CloseHandle
        close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
        handle=create(str(path),0xC0000000,0,None,4,0x80,None)
        if handle==ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:yield
        finally:close(handle)
    else:
        import fcntl
        with path.open('a+b') as handle:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def configure_gate(store, root):
    """One-time installation; callers must quiesce controller clients first."""
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    database=str(Path(store.db.execute('PRAGMA database_list').fetchone()[2]).resolve())
    with exclusive_gate(root):
        owner=root/'controller.json'
        if owner.exists():
            if json.loads(owner.read_text())!={'database':database}:
                raise ValueError('Native gate belongs to another controller')
        else:
            with owner.open('x',encoding='utf-8') as handle:
                json.dump({'database':database},handle);handle.flush();os.fsync(handle.fileno())
        store.db.execute('BEGIN IMMEDIATE')
        try:
            current=store.db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
            if current and Path(current[0])!=root:raise ValueError('Native gate cannot be rebound')
            for row in store.db.execute('SELECT jobs FROM studio_queues'):
                if any(j['status'] in ('reserved','starting','running','reconcile_required','verifying') for j in json.loads(row[0])):
                    raise ValueError('Cannot install native gate while an attempt is unresolved')
            store.db.execute('INSERT OR IGNORE INTO studio_native_gate VALUES(1,?)',(str(root),))
            store.db.execute('COMMIT')
        except BaseException:
            store.db.execute('ROLLBACK');raise


@contextmanager
def mutation_gate(db):
    row=db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
    if row is None:
        yield
        return
    root=Path(row[0])
    with exclusive_gate(root):
        # Invalidating an unconsumed permit before any database mutation is
        # conservative on rollback: stale requests cannot launch afterward.
        (root/'permit.json').unlink(missing_ok=True)
        yield
