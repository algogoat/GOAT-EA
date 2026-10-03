"""Agent-safe setup helpers: read the pending pairing code, close an inert terminal.

pairing-code  Returns the short-lived public challenge the activation dialog shows, so
              the user no longer reads it out. It first reads the code the EA shares in
              GOAT/activation-code-<data folder>.json (LC36 and later, any chart); then it
              registers the EA's 15-minute (here 5-minute) pairing-read capability on the
              setup mailbox (Portfolio Dashboard, MH34 Studio monitor). Either way only on a
              connected demo with Algo Trading off and no positions or orders.
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

from studio_agent_mailbox import identity, setup_register, setup_request, setup_retire
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


def activation_reason(controller, login):
    """This terminal's EA sign-in reason from ``GOAT/activation-status-<data folder>.json``.

    Operational metadata only (the EA never writes the code there; LC36 shares it in the
    sibling ``activation-code-<data folder>.json``, see ``shared_code``). With per-login
    activation (SM32/EX33) the file is still keyed by the data folder token, and a
    status written for another login is ignored.
    """
    from studio_research_status import activation
    mine, _ = activation(controller.install, login)
    return (mine or {}).get('reason')


def saved_login(controller):
    """(login, server) MT5 saved in ``<data root>\\config\\common.ini``, or (None, None). Read-only."""
    import configparser
    try:
        raw = (Path(controller.install['terminal_data_root']) / 'config' / 'common.ini').read_bytes()[:1 << 20]
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        ini = configparser.ConfigParser(interpolation=None, strict=False)
        ini.read_string(text)
        return ini.get('Common', 'Login', fallback=None), ini.get('Common', 'Server', fallback=None)
    except (OSError, UnicodeError, configparser.Error):
        return None, None


def account_facts(controller, proof):
    """Where the login and server came from: the broker readback, never typed input.

    ``savedLoginMatches`` is the common.ini cross-check (None when MT5 saved none).
    """
    login, server = saved_login(controller)
    matches = None if login is None else (login == proof['login'] and server == proof['server'])
    return dict(source='mt5_broker_readback', login=proof['login'], server=proof['server'],
                demo=proof['demo'] is True, savedLoginMatches=matches)


SHARED_CODE = re.compile(r'[A-Z2-9]{4}-[A-Z2-9]{4}')
SHARED_ACTIVATION = re.compile(r'[A-Za-z0-9_-]{32}')
SHARED_CODE_MAX_BYTES = 4096


def shared_code(controller, login, server, build_id, *, now=None):
    """The connection code the EA shares locally (LC36): ``GOAT/activation-code-<data folder>.json``.

    The file lives in this Windows user's Common Files and holds only the short-lived public
    challenge MT5 is showing (never a credential). It counts only when it names exactly this
    login, server and build, is well formed and has 15 s to 15 min left; anything else is
    ignored, never repaired. The code is returned to the caller only, never logged.

    Known limit: the file is named by the data folder's name, so two terminals whose data folders
    share a name write the same file. The exact login, server and build match above refuses a
    code from the other terminal unless both are signed in to the same account on the same build.
    """
    from studio_research_status import terminal_token
    path = Path(controller.install['common_files_root']) / 'GOAT' / ('activation-code-' + terminal_token(controller.install) + '.json')
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open('rb') as handle:
            raw = handle.read(SHARED_CODE_MAX_BYTES + 1)
        if len(raw) > SHARED_CODE_MAX_BYTES:
            return None
        value = json.loads(raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None
    now_ms = int((time.time() if now is None else now) * 1000)
    if not isinstance(value, dict) or value.get('schema') != 1:
        return None
    code, activation, expires, observed = (value.get('userCode'), value.get('activationId'),
                                           value.get('expiresAtMs'), value.get('observedAtUtc'))
    if (value.get('accountId') != str(login) or value.get('server') != server or value.get('buildId') != build_id
            or not isinstance(code, str) or not SHARED_CODE.fullmatch(code)
            or not isinstance(activation, str) or not SHARED_ACTIVATION.fullmatch(activation)
            or type(expires) is not int or not now_ms + 15000 < expires <= now_ms + 900000
            or type(observed) is not int or observed * 1000 > now_ms + 5000 or observed * 1000 > expires):
        return None
    return dict(userCode=code, activationId=activation, pairingExpiresAtMs=expires, observedAtUtc=observed)


ENTER_CODE = 'Enter the 8-character code MT5 shows in its GOAT window under Connect the EA.'
NO_SHARED_CODE = 'This EA build does not share its connection code with GOAT (SM31 and earlier). ' + ENTER_CODE


def _no_code_action(reason):
    if reason == 'approved':
        return 'This terminal is already connected to GOAT; there is nothing to approve.'
    if reason == 'build_not_admitted':
        return 'GOAT refused this EA build at sign-in, so it shows no code. Install the approved GOAT build, then reopen MT5.'
    if reason == 'webrequest_permission_required':
        return 'MT5 is blocking the GOAT sign-in request. Allow WebRequest for https://goatedge.ai, then reload the GOAT chart.'
    return 'This EA has no pending connection code: it is already paired or has not asked for one.'


def pairing_code(controller, build_id, *, timeout=30, mt5=None, request=None):
    session, _ = session_state(controller)
    login = session['account']['login']
    require_unprotected(login)
    from studio_seed_process import WindowsSeedProcess
    if WindowsSeedProcess(controller).inspect() is None:
        return dict(status='terminal_stopped', userCodeReturned=False,
                    next_action='Open the selected MT5 so GOAT can show and read its connection code.')
    ident = identity(controller, session, build_id)
    # A fresh broker readback, not the binding, proves demo before any request; the EA
    # itself also answers only on ACCOUNT_TRADE_MODE_DEMO.
    proof = broker_proof(controller, session, mt5=mt5, require_flat=False)
    reason = activation_reason(controller, login)
    # Screenshot-free path first: the code the EA shares locally (LC36 and later, any chart).
    shared = shared_code(controller, login, proof['server'], ident['buildId'])
    if shared is not None:
        # The same inert rule the EA applies to a mailbox read, from the fresh broker readback.
        if proof['algo_trading'] or proof['positions'] or proof['orders']:
            raise ValueError('MT5 is not inert: turn Algo Trading off and close demo positions before pairing')
        return dict(status='pairing_available', source='activation_code_file', userCode=shared['userCode'],
                    activationId=shared['activationId'], pairingExpiresAtMs=shared['pairingExpiresAtMs'],
                    responseExpiresAtUtc=min(int(time.time()) + 60, shared['pairingExpiresAtMs'] // 1000),
                    observedAtUtc=shared['observedAtUtc'], accountLogin=login, accountLast4=login[-4:],
                    server=proof['server'], buildId=ident['buildId'], demo=proof['demo'] is True, tradingAllowed=False,
                    activationReason=reason, accountFacts=account_facts(controller, proof), receiptId=None)
    setup_register(controller, ident, allow_pairing=True)
    result = (request or setup_request)(controller, ident, 'pairing', timeout=timeout)
    outcome = result['result']
    if outcome == 'pairing_available':
        return dict(status='pairing_available', source='setup_mailbox', userCode=result['userCode'], activationId=result['activationId'],
                    pairingExpiresAtMs=result['pairingExpiresAtMs'], responseExpiresAtUtc=result['responseExpiresAtUtc'],
                    observedAtUtc=result['observedAtUtc'], accountLogin=login, accountLast4=login[-4:],
                    server=proof['server'], buildId=ident['buildId'], demo=proof['demo'] is True, tradingAllowed=False,
                    activationReason=reason, accountFacts=account_facts(controller, proof), receiptId=result['id'])
    if outcome == 'pairing_unavailable':
        return dict(status='no_pending_pairing', userCodeReturned=False, activationReason=reason,
                    next_action=_no_code_action(reason))
    if outcome == 'rejected_not_inert':
        raise ValueError('MT5 is not inert: turn Algo Trading off and close demo positions before pairing')
    if outcome == 'receipt_timeout':
        waiting = reason == 'awaiting_approval'
        return dict(status='no_native_answer', userCodeReturned=False, requestId=result['id'], activationReason=reason,
                    next_action=('The EA is waiting for approval and shows a connection code, but this build does not share it with GOAT. '
                                 + ENTER_CODE if waiting else NO_SHARED_CODE))
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


def close_terminal(controller, attempt_id, *, build_id=None, process=None, inspect=None, request=None, retire=None, wait_seconds=30):
    """Inert-only normal close of the selected terminal. Retained; never repeated."""
    from studio_monitor_probe import inspect_idle_demo
    from studio_seed_process import WindowsSeedProcess
    session, _ = session_state(controller)
    require_unprotected(session['account']['login'])
    process = process or WindowsSeedProcess(controller)
    inspect = inspect or inspect_idle_demo
    request = request or setup_request
    path = _journal(controller, 'terminal-closes', attempt_id)
    gate = controller.local / 'native-gate'

    def refuse_pending_native():
        # A native-gate request or permit means a batch start or control is in flight; the
        # controller cannot read the EA's BatchOnGoing flag, so this is a hard refusal.
        if any((gate / name).exists() or (gate / name).is_symlink() for name in ('request.json', 'permit.json')):
            raise ValueError('A native Studio request or permit is pending on this terminal; GOAT will not close MT5 during it')

    # The terminal lock is held throughout. The native gate (launch.lock, opened with no
    # sharing) is held only for the controller's own checks and its own fallback close:
    # the EA's inert shutdown takes launch.lock itself from its idle check through
    # TerminalClose (GOAT-EA #112), so holding it across that request would make every
    # monitor close refuse.
    with demo_terminal_lock(controller):
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
        with exclusive_gate(gate):
            require_idle_control(controller, session)
            if (Path(controller.root) / 'demo-agent' / 'STOP').exists():
                raise ValueError('Owner STOP is set on this terminal; clear it deliberately before agents act')
            refuse_pending_native()
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
            if receipt['result'] == 'receipt_timeout':
                # Withdraw the unanswered shutdown so no EA can act on it during or after our
                # own close; an EA that answered before the withdrawal wins and is honoured.
                answered = (retire or setup_retire)(controller, ident, receipt['id'])
                if answered is not None:
                    receipt = answered
                else:
                    record['withdrawn_request_id'] = receipt['id']
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
            # No mailbox host answered (for example an older Studio monitor chart). Under
            # the native gate, re-prove inert state immediately before the single normal close.
            with exclusive_gate(gate):
                try:
                    refuse_pending_native()
                except ValueError:
                    record.update(phase='refused', status='native_request_pending'); write_json(path, record)
                    raise
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
