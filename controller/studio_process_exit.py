"""Kernel proof that an exact former Windows process exited; no process effects."""
import ctypes
from ctypes import wintypes as W
from datetime import datetime, timedelta, timezone


def prove_exited(identity):
    if (not isinstance(identity, dict) or set(identity) != {'pid', 'created_utc', 'executable'}
            or type(identity['pid']) is not int or identity['pid'] <= 0):
        raise ValueError('Exact previous process identity required')
    expected = datetime.fromisoformat(identity['created_utc'].replace('Z', '+00:00'))
    if expected.tzinfo is None:
        raise ValueError('Process creation time requires timezone')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]; k.CloseHandle.restype = W.BOOL
    k.GetProcessTimes.argtypes = [W.HANDLE, *[ctypes.POINTER(W.FILETIME)]*4]
    k.GetProcessTimes.restype = W.BOOL
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]; k.WaitForSingleObject.restype = W.DWORD
    handle = k.OpenProcess(0x101000, False, identity['pid'])
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return dict(identity=identity, proof='pid_absent')
        raise ctypes.WinError(error)
    try:
        creation, exited, kernel, user = (W.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        actual = datetime(1601, 1, 1, tzinfo=timezone.utc)+timedelta(microseconds=ticks//10)
        if actual != expected:
            return dict(identity=identity, proof='pid_reused', observed_creation_utc=actual.isoformat())
        result = k.WaitForSingleObject(handle, 0)
        if result == 0:
            return dict(identity=identity, proof='exact_process_signaled')
        if result == 258:
            raise ValueError('Exact previous process is still alive')
        raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(handle)
