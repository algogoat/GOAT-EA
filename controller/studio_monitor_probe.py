"""Read native state before repairing an idle demo monitor, without trading calls."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path

from studio_process_check import inspect_processes
from studio_protected_peer import process_binding

def tester_caption_state(caption):
    # Only captions observed for this exact MT5 tester control may certify a
    # state. Unknown localizations remain a refusal rather than a guess.
    return {'Start': 'idle', 'Старт': 'idle', 'Test starten': 'idle',
            'Stop': 'running', 'Стоп': 'running'}.get(caption.strip(), 'unknown')


def tester_state(pid, build):
    u = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    u.EnumWindows.argtypes = [callback_type, w.LPARAM]; u.EnumWindows.restype = w.BOOL
    u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]; u.GetDlgItem.restype = w.HWND
    u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u.GetWindow.argtypes = [w.HWND, w.UINT]; u.GetWindow.restype = w.HWND
    frames = []

    @callback_type
    def visit(window, unused):
        actual = w.DWORD(); name = ctypes.create_unicode_buffer(256)
        u.GetWindowThreadProcessId(window, ctypes.byref(actual))
        u.GetClassNameW(window, name, 256)
        if actual.value == pid and name.value.startswith('MetaQuotes::MetaTrader::') and not u.GetWindow(window, 4):
            frames.append(window)
        return True

    if not u.EnumWindows(visit, 0) or len(frames) != 1:
        raise ValueError('Unique selected MT5 frame required for passive tester observation')
    window = frames[0]
    ids = (0x804e, 0x2712, 0x4196) if build > 5000 else (0xe81e, 0x804e, 0x2712, 0x4196)
    for control in ids:
        window = u.GetDlgItem(window, control)
        if not window:
            raise ValueError('Native tester state unavailable; no close performed')
    caption = ctypes.create_unicode_buffer(64)
    if u.GetWindowTextW(window, caption, 64) <= 0:
        raise ValueError('Native tester state unavailable; no close performed')
    return tester_caption_state(caption.value)


def inspect_idle_demo(controller, *, tester='require'):
    """Same bound demo, Algo OFF, zero positions/orders; tester per ``tester``.

    ``tester='require'`` (default, every repair path) needs a recognised idle
    caption. ``tester='advisory'`` is for callers that already hold a fresh EA
    runtime sample proving the tester idle: a recognised running caption still
    refuses, but an unreadable or unrecognised caption (any MT5 UI language
    outside the table above) defers to the EA instead of refusing.
    """
    if tester not in ('require', 'advisory'):
        raise ValueError('Explicit tester observation mode required')
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise ValueError('Monitor repair requires the official MetaTrader5 Python adapter; no native effect performed') from exc
    binding = process_binding(controller)
    before = inspect_processes(binding)
    session = controller.session
    try:
        # Explicit existing executable only; never broker login/password or trading APIs.
        if not mt5.initialize(controller.install['terminal_executable'], timeout=5000):
            raise ValueError('Unable to read the selected MT5 terminal')
        terminal, account = mt5.terminal_info(), mt5.account_info()
        positions, orders = mt5.positions_get(), mt5.orders_get()
        if any(value is None for value in (terminal, account, positions, orders)):
            raise ValueError('Incomplete native account/terminal observation')
        current = inspect_processes(binding)
        if any(current[k] != before[k] for k in ('research', 'protected')):
            raise ValueError('Native process changed during inspection; no adoption')
        if (Path(terminal.path) != Path(controller.install['terminal_executable']).parent
                or Path(terminal.data_path) != Path(controller.install['terminal_data_root'])
                or str(account.login) != session['account']['login'] or account.server != session['account']['server']):
            raise ValueError('Native terminal/account differs from the installation')
        if account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO or not terminal.connected or terminal.trade_allowed or positions or orders:
            raise ValueError('Repair requires a connected demo, Algo Trading off and no positions/orders')
        if tester == 'require':
            state = tester_state(current['research']['pid'], terminal.build)
            if state != 'idle':
                raise ValueError('Repair requires positively observed idle native tester')
        else:
            try:
                state = tester_state(current['research']['pid'], terminal.build)
            except (ValueError, OSError):
                state = 'unknown'
            if state == 'running':
                raise ValueError('The MT5 Strategy Tester is running; no close performed')
        return dict(process=current['research'], protected=current['protected'], account_matches=True,
                    demo=True, connected=True, algo_trading=False, positions=0, orders=0,
                    tester_state=state, tester_source='window_caption' if state != 'unknown' else 'ea_runtime',
                    build=terminal.build, sdk_version=mt5.__version__)
    finally:
        mt5.shutdown()
