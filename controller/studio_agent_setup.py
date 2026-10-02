"""Agent-safe setup helpers: read the pending pairing code, close an inert terminal.

pairing-code  Registers the EA's 15-minute (here 5-minute) pairing-read capability and
              returns the short-lived public challenge the activation dialog shows, so
              the user no longer reads it out. The EA answers only on a connected demo
              with Algo Trading off and no positions or orders.
close-terminal Normal close of the selected MT5, never a kill, and only when inert:
              broker-reported demo, connected, Algo Trading off, no positions or orders,
              idle Strategy Tester, no batch, seed or unresolved native job. The EA's
              own inert shutdown is used when the running chart hosts the setup mailbox
              (Portfolio Dashboard); otherwise the controller sends one normal close
              after the same native proof. A close is never repeated.

Neither command enables trading, types credentials or changes MT5 permissions.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from studio_agent_mailbox import identity, setup_register, setup_request
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate
from studio_onboarding import session_state, require_idle_control

# Experiment 02 runs live research on these demo logins. Agent setup and deploy never touch them.
PROTECTED_ACCOUNTS = frozenset(('3000109427', '3000109421'))
ATTEMPT_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')


def require_unprotected(login):
    if str(login) in PROTECTED_ACCOUNTS:
        raise ValueError('This demo account belongs to a running GOAT experiment; agents never change it')


@contextmanager
def demo_terminal_lock(controller):
    """Share the demo agent's terminal lock so batches and closes never race."""
    import msvcrt
    root = Path(controller.root) / 'demo-agent'
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'terminal.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('Another demo operation owns this terminal; wait for it to finish') from exc
        try:
            yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def broker_proof(controller, session, *, mt5=None, require_flat=True):
    """Fresh MT5 SDK readback of the selected terminal. Never a trading call."""
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise ValueError('The MetaTrader5 adapter is unavailable; no native effect performed') from exc
    if not mt5.initialize(controller.install['terminal_executable'], timeout=5000):
        raise ValueError('The selected MT5 terminal could not be read; start it and sign in to the demo account')
    try:
        terminal, account = mt5.terminal_info(), mt5.account_info()
        positions, orders = mt5.positions_get(), mt5.orders_get()
        if terminal is None or account is None or positions is None or orders is None:
            raise ValueError('Incomplete native account and terminal readback')
        if (Path(terminal.path) != Path(controller.install['terminal_executable']).parent
                or Path(terminal.data_path) != Path(controller.install['terminal_data_root'])):
            raise ValueError('The running MT5 is not the selected installation')
        proof = dict(login=str(account.login), server=account.server,
                     demo=account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
                     connected=bool(terminal.connected), algo_trading=bool(terminal.trade_allowed),
                     positions=len(positions), orders=len(orders), build=terminal.build)
    finally:
        mt5.shutdown()
    if proof['login'] != session['account']['login'] or proof['server'] != session['account']['server']:
        raise ValueError('MT5 is signed in to a different account than this installation is bound to')
    if not proof['demo']:
        raise ValueError('MT5 reports a real-money account; GOAT agents only operate demo accounts')
    if not proof['connected']:
        raise ValueError('MT5 is not connected to the demo server')
    if require_flat and (proof['positions'] or proof['orders']):
        raise ValueError('The demo account has open positions or orders; GOAT never closes them automatically')
    return proof


def pairing_code(controller, build_id, *, timeout=30):
    session, _ = session_state(controller)
    require_unprotected(session['account']['login'])
    from studio_seed_process import WindowsSeedProcess
    if WindowsSeedProcess(controller).inspect() is None:
        return dict(status='terminal_stopped', userCodeReturned=False,
                    next_action='Open the selected MT5 so GOAT can show and read its connection code.')
    ident = identity(controller, session, build_id)
    setup_register(controller, ident, allow_pairing=True)
    result = setup_request(controller, ident, 'pairing', timeout=timeout)
    outcome = result['result']
    if outcome == 'pairing_available':
        login = session['account']['login']
        return dict(status='pairing_available', userCode=result['userCode'], activationId=result['activationId'],
                    pairingExpiresAtMs=result['pairingExpiresAtMs'], responseExpiresAtUtc=result['responseExpiresAtUtc'],
                    observedAtUtc=result['observedAtUtc'], accountLogin=login, accountLast4=login[-4:],
                    server=ident['server'], buildId=ident['buildId'], demo=True, tradingAllowed=False,
                    receiptId=result['id'])
    if outcome == 'pairing_unavailable':
        return dict(status='no_pending_pairing', userCodeReturned=False,
                    next_action='This EA has no pending connection code: it is already paired or has not asked for one.')
    if outcome == 'rejected_not_inert':
        raise ValueError('MT5 is not inert: turn Algo Trading off and close demo positions before pairing')
    if outcome == 'receipt_timeout':
        return dict(status='no_native_answer', userCodeReturned=False, requestId=result['id'],
                    next_action='No GOAT chart answered the local request. This build answers from the Portfolio Dashboard; read the code shown in MT5 instead.')
    raise ValueError('The EA refused the pairing request (' + outcome + ')')


def _journal(controller, folder, attempt_id):
    if not isinstance(attempt_id, str) or not ATTEMPT_ID.fullmatch(attempt_id):
        raise ValueError('Attempt ID must be 1..80 letters, digits, underscore or hyphen')
    root = Path(controller.root) / folder
    root.mkdir(parents=True, exist_ok=True)
    return root / (attempt_id + '.json')


def _wait_exit(process, identity_value, seconds, *, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + seconds
    current = process.inspect()
    while current is not None and clock() < deadline:
        if current != identity_value:
            raise ValueError('The terminal was replaced during close; nothing else was done')
        sleep(0.25)
        current = process.inspect()
    return current is None


def close_terminal(controller, attempt_id, *, build_id=None, process=None, inspect=None, request=None, wait_seconds=30):
    """Inert-only normal close of the selected terminal. Retained; never repeated."""
    from studio_monitor_probe import inspect_idle_demo
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    require_unprotected(session['account']['login'])
    process = process or WindowsSeedProcess(controller)
    inspect = inspect or inspect_idle_demo
    request = request or setup_request
    path = _journal(controller, 'terminal-closes', attempt_id)
    with exclusive_gate(controller.local / 'native-gate'), demo_terminal_lock(controller):
        if path.exists():
            record = read_json(path)
            if record.get('phase') in ('stopped', 'already_stopped'):
                return record
            if record.get('phase') == 'close_issued':
                stopped = _wait_exit(process, record['process'], wait_seconds)
                if stopped:
                    record.update(phase='stopped', status='stopped', stopped_utc=datetime.now(timezone.utc).isoformat())
                    write_json(path, record)
                    return record
                return record | dict(status='close_outcome_unresolved', close_will_not_be_repeated=True)
            raise ValueError('Retained close attempt is unresolved; inspect it before another close')
        require_idle_control(controller, session)
        if (Path(controller.root) / 'demo-agent' / 'STOP').exists():
            raise ValueError('Owner STOP is set on this terminal; clear it deliberately before agents act')
        running = process.inspect()
        if running is None:
            record = dict(schema_version=1, attempt_id=attempt_id, phase='already_stopped', status='already_stopped')
            write_json(path, record)
            return record
        native = inspect(controller)
        if native.get('process') != running:
            raise ValueError('The terminal changed while it was inspected; nothing was closed')
        record = dict(schema_version=1, attempt_id=attempt_id, phase='close_intent', process=running,
                      native=native, created_utc=datetime.now(timezone.utc).isoformat(), trading_changed=False,
                      positions_closed=False)
        write_json(path, record)
        method = None
        if build_id:
            ident = identity(controller, session, build_id)
            setup_register(controller, ident)
            receipt = request(controller, ident, 'shutdown', timeout=10)
            if receipt['result'] == 'shutdown_requested':
                method = 'ea_inert_shutdown'
                record['ea_receipt'] = {k: receipt[k] for k in ('id', 'result', 'tradingAllowed', 'positions', 'orders', 'observedAtUtc')}
            elif receipt['result'] == 'rejected_not_inert':
                record.update(phase='refused', status='rejected_not_inert'); write_json(path, record)
                raise ValueError('The EA refused to close MT5: Algo Trading is on or the demo account has positions or orders')
            elif receipt['result'] != 'receipt_timeout':
                record.update(phase='refused', status=receipt['result']); write_json(path, record)
                raise ValueError('The EA refused the close request (' + receipt['result'] + ')')
        if method is None:
            # No mailbox host answered (for example a Studio monitor chart). Re-prove
            # inert state immediately before the single normal close.
            again = inspect(controller)
            if again.get('process') != running:
                raise ValueError('The terminal changed before close; nothing was closed')
            method = 'controller_normal_close'
            record['phase'] = 'close_issued'; record['method'] = method; write_json(path, record)
            process.close(running)
        else:
            record['phase'] = 'close_issued'; record['method'] = method; write_json(path, record)
        stopped = _wait_exit(process, running, wait_seconds)
        if not stopped:
            return record | dict(status='close_outcome_unresolved', close_will_not_be_repeated=True)
        record.update(phase='stopped', status='stopped', stopped_utc=datetime.now(timezone.utc).isoformat())
        write_json(path, record)
        return record
