"""Small demo-only MT5 agent surface. Never submits trades or enables Algo Trading.

The legacy Studio ledger remains readable, but demo operations use a separate
terminal lock and action log. A broker-reported demo account is required before
every operation that can change the selected terminal or its files.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time

# The embedded GOAT Python may list its installed controller ahead of the
# script directory. Keep this reviewed checkout coherent for both the CLI and
# its detached child instead of mixing controller revisions.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from campaign_ledger import packed, sha
from studio_installation import load_installation
from studio_monitor_probe import tester_state
from studio_native_request import ini_sections
from studio_seed_process import WindowsSeedProcess


MIN_FREE_BYTES = 5 * 1024 ** 3
# Readback windows. A running terminal answers within 2 minutes; a cold MT5 start after an
# update took ~3 minutes on beta.17 T2 QA (process 09:44:19Z, EA loaded 09:47:18Z), so a
# relaunch gets 7 minutes before GOAT calls the readback unconfirmed.
RUNNING_READBACK_SECONDS = 120
COLD_START_READBACK_SECONDS = 420
# Seed hunts and OOS catch-ups share one runner driver, one terminal slot and one
# broker-verified start discipline; only their state folders and wording differ.
LANES = {'seed': dict(folder='seeds', starts='seed-starts', word='seed', title='Seed', unit='seed hunt'),
         'catchup': dict(folder='catchups', starts='catchup-starts', word='catch-up', title='Catch-up', unit='catch-up')}
ACTIVE_NATIVE_STATUSES = ('reserved', 'starting', 'running', 'reconcile_required', 'verifying')
# What an app update (install-build and its relaunch) writes to the demo action log. Any other
# operation there is owner demo-lane work, which restore-lane never undoes.
UPDATE_OPERATIONS = frozenset(('install_build', 'launch_terminal', 'readback_refresh', 'recover_orphan', 'restore_lane'))
LANE_IDENTITY_EXCLUDED = ('authority_kind', 'installation_sha256')
# Credential recovery (goatai#1885, T2 2026-10-04): the broker servers on which an app update may
# replace the EA without fresh EA feedback. Exact names only; a demo-looking name is not enough.
RECOVERY_DEMO_SERVERS = frozenset(('Darwinex-Demo',))
# Credential recoveries that reach the MT5 close, per paired login per UTC day (Claude-Mac, #1885).
RECOVERY_DAILY_LIMIT = 2


class FeedbackUnavailable(ValueError):
    """The EA has not reported recently (or ever) for this terminal: no fresh ``ui-observation.json``.

    Typically its GOAT sign-in was rejected and it waits for a new connection, so its Studio UI never
    loads. Still a ValueError (a refusal) everywhere; the CLI adds ``reason`` so the desktop can offer
    credential recovery for exactly this refusal and no other.
    """
    reason = 'ea_feedback_unavailable'


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + secrets.token_hex(8))
    with temporary.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, sort_keys=True, separators=(',', ':'))
        output.write('\n')
        output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)


class DemoAgent:
    def __init__(self, installation, *, process=None, mt5=None, clock=time.time, sleep=time.sleep):
        self.installation_path = Path(installation).resolve()
        # Validate every path/version before deriving a writable target. The
        # binary check is deferred only so an interrupted swap can be resumed.
        self.install = load_installation(self.installation_path, verify_binary=False)
        self.root = Path(self.install['controller_state_root'])
        self.session = read_json(self.root / 'session.json')
        self.local = Path(self.install['terminal_data_root']) / 'MQL5/Files/GOATStudio'
        self.state_root = self.root / 'demo-agent'
        self.process = process or WindowsSeedProcess(self)
        self.mt5 = mt5
        self.clock = clock
        self.sleep = sleep
        self.binary = (Path(self.install['terminal_data_root']) / 'MQL5/Experts'
                       / self.install['ea_relative_path'].replace('\\', '/')).resolve()

    def _append(self, operation, phase, **details):
        self.state_root.mkdir(parents=True, exist_ok=True)
        row = dict(at=datetime.now(timezone.utc).isoformat(), operation=operation, phase=phase, **details)
        with (self.state_root / 'actions.jsonl').open('a', encoding='utf-8', newline='\n') as output:
            output.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
            output.flush(); os.fsync(output.fileno())
        return row

    @contextmanager
    def _exclusive(self, *, wait_seconds=0):
        self.state_root.mkdir(parents=True, exist_ok=True)
        with (self.state_root / 'terminal.lock').open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            deadline = time.monotonic() + wait_seconds
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ValueError('Another demo agent operation owns this terminal') from exc
                    time.sleep(.1)
            try:
                yield
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def _owner_clear(self, *, require_fresh=True, settling_stop=False):
        if (self.state_root / 'STOP').exists() and not settling_stop:
            raise ValueError('Owner STOP is set')
        if settling_stop and read_json(self.state_root / 'STOP').get('actor') != 'demo_agent':
            raise ValueError('Stop settlement requires the retained demo-agent STOP')
        human = self.local / self.session['directory_id'] / 'human'
        for channel in ('inbox', 'processing'):
            if any((human / channel).glob('*.json')):
                raise ValueError('Pending human TAKE CONTROL')
        observation = self.local / 'ui-observation.json'
        if not observation.is_file() or (require_fresh and self.clock() - observation.stat().st_mtime > 300):
            raise FeedbackUnavailable('Fresh EA owner feedback unavailable')
        ui = read_json(observation)
        if ui.get('owner') != 'agent' or ui.get('run_id', self.session['run_id']) != self.session['run_id']:
            raise ValueError('Human owns the EA or native session changed')
        if not require_fresh:
            active = read_json(self.local / 'active.json')
            if (self.session != read_json(self.root / 'session.json')
                    or active != dict(directory_id=self.session['directory_id'],
                                      terminal_id=self.session['terminal_id'],
                                      run_id=self.session['run_id'],
                                      terminal_data_path=self.install['terminal_data_root'])
                    or self.session.get('demo_only') is not True
                    or ui.get('runtime', {}).get('account_demo') is not True
                    or ui['runtime'].get('account_login') != self._paired_account()['login']
                    or ui['runtime'].get('account_server') != self.session['account']['server']):
                raise ValueError('Recovery without fresh EA feedback lacks exact prior demo/owner identity')
            binding = packed(dict(terminal_id=self.session['terminal_id'], run_id=self.session['run_id']))
            db_path = self.root / 'studio.sqlite'
            with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as db:
                row = db.execute('SELECT owner FROM studio_state WHERE binding=?', (binding,)).fetchone()
            if row is None or row[0] != 'agent':
                raise ValueError('Controller ownership changed while terminal was stopped')
        return ui

    def _space(self):
        volumes = {}
        for role, path in (('terminal_data', self.install['terminal_data_root']),
                           ('common_files', self.install['common_files_root']),
                           ('controller_state', self.root)):
            free = shutil.disk_usage(path).free
            volumes[role] = free
            if free < MIN_FREE_BYTES:
                raise ValueError(role + ' has less than 5 GiB free')
        return volumes

    def _paired_account(self):
        expected = self.session.get('account')
        if (self.session.get('demo_only') is not True or not isinstance(expected, dict)
                or set(expected) != {'login', 'server'}
                or not isinstance(expected['login'], str)
                or not re.fullmatch(r'[1-9][0-9]{0,19}', expected['login'])
                or not isinstance(expected['server'], str) or not 1 <= len(expected['server']) <= 256
                or any(ch in expected['server'] for ch in '\x00\r\n\t')):
            raise ValueError('Exact paired demo account and server required')
        return expected

    def _broker(self, *, idle=True):
        expected = self._paired_account()
        identity = self.process.inspect()
        if identity is None:
            raise ValueError('Selected MT5 is not running; broker demo mode cannot be proven')
        mt5 = self.mt5
        if mt5 is None:
            import MetaTrader5 as mt5
        if not mt5.initialize(self.install['terminal_executable'], timeout=5000):
            raise ValueError('Selected MT5 broker state unavailable')
        try:
            terminal, account = mt5.terminal_info(), mt5.account_info()
            if terminal is None or account is None:
                raise ValueError('Incomplete native broker state')
            positions, orders = (mt5.positions_get(), mt5.orders_get()) if idle else (None, None)
            if idle and (positions is None or orders is None):
                raise ValueError('Idle demo research requires a complete position and order readback')
            if self.process.inspect() != identity:
                raise ValueError('Selected MT5 process changed during broker check')
            if (account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
                    or str(account.login) != expected['login']
                    or account.server != expected['server']
                    or not terminal.connected
                    or PureWindowsPath(terminal.path) != PureWindowsPath(self.install['terminal_executable']).parent
                    or PureWindowsPath(terminal.data_path) != PureWindowsPath(self.install['terminal_data_root'])):
                raise ValueError('Broker-reported demo and exact paired account required')
            if terminal.trade_allowed:
                raise ValueError('Algo Trading is on; this demo research lane leaves it off')
            account_trade_allowed = getattr(account, 'trade_allowed', None)
            # Position/order snapshots are account-wide. An investor terminal
            # cannot manage the positions held by a different trading terminal
            # on the same demo login; retain the flat-account gate for every
            # trade-capable or unproven account.
            if idle and (positions or orders) and account_trade_allowed is not False:
                raise ValueError('Idle trade-capable demo research requires no open positions or orders')
            state = tester_state(identity['pid'], terminal.build) if idle else None
            if idle and state != 'idle':
                raise ValueError('Selected native tester is not positively idle')
            return dict(process=identity, login=str(account.login), server=account.server,
                        demo=True, connected=True, algo_trading=False, tester_state=state,
                        dlls_allowed=(terminal.dlls_allowed
                                      if type(getattr(terminal, 'dlls_allowed', None)) is bool else None),
                        account_trade_allowed=(account_trade_allowed
                                               if type(account_trade_allowed) is bool else None),
                        positions=len(positions) if idle else None,
                        orders=len(orders) if idle else None, build=terminal.build)
        finally:
            mt5.shutdown()

    def status(self):
        journals = []
        for path in sorted((self.root / 'batch-drivers').glob('*.json')):
            record = read_json(path)
            journals.append(dict(batch_id=path.stem, status=record.get('status'),
                                 attempt_id=record.get('attempt_id'),
                                 started_wall=record.get('started_wall'),
                                 stopped=record.get('stopped')))
        feedback_path = self.local / 'ui-observation.json'
        result = dict(terminal=self.process.inspect(), owner_stop=(self.state_root / 'STOP').exists(),
                      binary_sha256=digest(self.binary) if self.binary.is_file() else None,
                      driver_journals=journals,
                      owner_feedback=(dict(observed_age_seconds=max(0, self.clock()-feedback_path.stat().st_mtime),
                                           observation=read_json(feedback_path))
                                      if feedback_path.is_file() else None))
        try:
            result['broker'] = self._broker(idle=False)
        except (ValueError, OSError) as exc:
            result['broker_error'] = str(exc)
        return result

    def preflight(self):
        owner = self._owner_clear()
        space = self._space()
        broker = self._broker()
        physical = digest(self.binary)
        verified_path = self.state_root / 'verified-build.json'
        verified = read_json(verified_path) if verified_path.is_file() else {}
        lane_ready = (self.session.get('authority_kind') == 'demo_direct'
                      and physical == self.install['ea_sha256']
                      and self.session.get('installation_sha256') == sha(self.install))
        current = verified.get('ea_sha256') == physical and verified.get('process') == broker['process']
        # After GOAT's own relaunch the next prepare/start re-reads the build on the new
        # process by itself (_relaunch_readback); preflight only reports it, read-only.
        refresh = lane_ready and not current and self._relaunch_qualifies(verified, broker['process'], physical)
        return dict(broker=broker, owner=owner['owner'], free_bytes=space,
                    binary_sha256=physical,
                    ready_for_install=physical == self.install['ea_sha256'],
                    ready_for_batch=lane_ready and (current or refresh),
                    readback_refresh_on_start=refresh)

    def _last_placed_ns(self, sha256):
        """When GOAT last swapped these EX5 bytes in (the latest ``binary_replaced`` row), in ns; 0 if never."""
        log = self.state_root / 'actions.jsonl'
        latest = 0
        if not log.is_file():
            return latest
        with log.open(encoding='utf-8') as rows:
            for line in rows:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if (isinstance(row, dict) and row.get('operation') == 'install_build'
                            and row.get('phase') == 'binary_replaced' and row.get('new_sha256') == sha256):
                        at = datetime.fromisoformat(str(row['at']).replace('Z', '+00:00'))
                        latest = max(latest, int(at.timestamp() * 1_000_000_000))
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError('Demo action log unreadable; credential recovery refuses') from exc
        return latest

    def _recovery_owner(self):
        """Owner proof for credential recovery: everything ``_owner_clear`` proves except freshness.

        No owner STOP or pending TAKE CONTROL; the last EA observation (any age) says the agent owns
        this session with the exact paired demo login and server; the session and active.json are
        unchanged; and the controller store's owner for this binding is the agent.

        The stale observation must also come from the installed build (Claude-Mac, #1885), so one left
        over from a previous install can never vouch for the current one: it names the installed EX5
        file, it was written after GOAT last placed these exact bytes (the EX5's own write time and the
        latest ``binary_replaced`` row), and when GOAT's verified readback recorded this build's marker,
        the observation's ``build`` is that marker.
        """
        ui = self._owner_clear(require_fresh=False)
        physical = digest(self.binary)
        if physical != self.install['ea_sha256']:
            raise ValueError('Installed EA differs from registered receipt; credential recovery refuses')
        runtime = ui.get('runtime') if isinstance(ui.get('runtime'), dict) else {}
        if PureWindowsPath(str(runtime.get('program_path', ''))) != PureWindowsPath(self.binary):
            raise ValueError('The last EA observation is not from the installed EA file; credential recovery refuses')
        observed_ns = (self.local / 'ui-observation.json').stat().st_mtime_ns
        if observed_ns <= max(self.binary.stat().st_mtime_ns, self._last_placed_ns(physical)):
            raise ValueError('The last EA observation predates the installed EA build, so it cannot vouch for it; '
                             'credential recovery refuses')
        verified_path = self.state_root / 'verified-build.json'
        verified = read_json(verified_path) if verified_path.is_file() else {}
        marker = verified.get('build') if verified.get('ea_sha256') == physical else None
        if isinstance(marker, str) and ui.get('build') != marker:
            raise ValueError('The last EA observation names build ' + str(ui.get('build')) + ', not the installed build '
                             + marker + '; credential recovery refuses')
        return ui

    def _recovery_attempts_today(self):
        """Credential-recovery installs that reached the MT5 close for this paired login today (UTC)."""
        login, today = self._paired_account()['login'], datetime.now(timezone.utc).date().isoformat()
        log = self.state_root / 'actions.jsonl'
        count = 0
        if not log.is_file():
            return count
        with log.open(encoding='utf-8') as rows:
            for line in rows:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise ValueError('Demo action log unreadable; credential recovery refuses') from exc
                if (isinstance(row, dict) and row.get('operation') == 'install_build' and row.get('phase') == 'before_close'
                        and row.get('credential_recovery') is True and row.get('login') == login
                        and str(row.get('at', ''))[:10] == today):
                    count += 1
        return count

    def _require_recovery_budget(self):
        """At most RECOVERY_DAILY_LIMIT credential recoveries per login per UTC day (Claude-Mac, #1885): no loop
        can close and reopen MT5 again and again without the EA's own word."""
        if self._recovery_attempts_today() >= RECOVERY_DAILY_LIMIT:
            raise ValueError('Credential recovery already ran ' + str(RECOVERY_DAILY_LIMIT)
                             + ' times today (UTC) for this login; a person should look at this terminal')

    def _recovery_broker(self):
        """The paired demo read from MT5 itself (MetaTrader5 account_info/terminal_info), on an allowlisted
        server and strictly flat: no read-only allowance without the EA's own word (Claude-Mac, #1885)."""
        broker = self._broker()
        if broker['server'] not in RECOVERY_DEMO_SERVERS:
            raise ValueError('Credential recovery updates only a demo on ' + ', '.join(sorted(RECOVERY_DEMO_SERVERS))
                             + '; MT5 shows ' + str(broker['server']))
        if broker.get('positions') != 0 or broker.get('orders') != 0:
            raise ValueError('Credential recovery needs a flat demo: 0 open positions and 0 pending orders')
        return broker

    def _sign_in_status(self):
        """What the EA last wrote about its own GOAT sign-in for this terminal, or None. Read-only, informational."""
        from studio_research_status import terminal_token
        path = Path(self.install['common_files_root']) / 'GOAT' / ('activation-status-' + terminal_token(self.install) + '.json')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
                return None
            value = read_json(path)
        except (OSError, ValueError, UnicodeError):
            return None
        if not isinstance(value, dict):
            return None
        reason, build_id, observed = value.get('reason'), value.get('buildId'), value.get('observedAtUtc')
        return dict(reason=reason if isinstance(reason, str) and re.fullmatch(r'[a-z_]{1,60}', reason) else None,
                    build_id=build_id if isinstance(build_id, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,96}', build_id) else None,
                    observed_utc=observed if type(observed) is int else None,
                    this_login=value.get('accountId') == self._paired_account()['login'])

    def credential_recovery_preflight(self):
        """Read-only: may an app update replace the EA here although the EA cannot report?

        For a terminal whose EA lost its GOAT sign-in (goatai#1885, T2 2026-10-04): its Studio UI
        never loads, so ``preflight`` refuses with FeedbackUnavailable and no update could be planned.
        This proves the same things from MT5 itself instead: the broker reports the exact paired
        demo on an allowlisted server (MetaTrader5, not the EA licence), the agent still owns the
        session by an observation from the installed build, MT5 is idle and strictly flat (0
        positions, 0 orders) with Algo Trading off, the installed EA is the registered one, and fewer
        than RECOVERY_DAILY_LIMIT recoveries reached the close for this login today (UTC). It refuses
        when the EA *is* reporting: then the normal path applies.
        """
        try:
            self._owner_clear()
        except FeedbackUnavailable:
            pass
        else:
            raise ValueError('The EA is reporting; use preflight and a normal install-build')
        owner = self._recovery_owner()
        self._require_recovery_budget()
        space = self._space()
        broker = self._recovery_broker()
        physical = digest(self.binary)
        observation = self.local / 'ui-observation.json'
        build = owner.get('build')
        return dict(broker=broker, owner=owner['owner'], free_bytes=space, binary_sha256=physical,
                    ready_for_install=physical == self.install['ea_sha256'], ready_for_batch=False,
                    credential_recovery=dict(reason=FeedbackUnavailable.reason, server=broker['server'],
                                             feedback_age_seconds=max(0, int(self.clock() - observation.stat().st_mtime)),
                                             observed_build=build if isinstance(build, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,40}', build) else None,
                                             attempts_today=self._recovery_attempts_today(), daily_limit=RECOVERY_DAILY_LIMIT,
                                             ea_sign_in=self._sign_in_status()))

    def disk_status(self):
        return {role:dict(path=str(path), free_bytes=shutil.disk_usage(path).free,
                          minimum_bytes=MIN_FREE_BYTES)
                for role, path in (('terminal_data', self.install['terminal_data_root']),
                                   ('common_files', self.install['common_files_root']),
                                   ('controller_state', self.root))}

    def _native_active_batches(self):
        binding = packed(dict(terminal_id=self.session['terminal_id'], run_id=self.session['run_id']))
        with closing(sqlite3.connect((self.root / 'studio.sqlite').as_uri() + '?mode=ro',
                                     uri=True)) as db:
            row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
        if row is None:
            raise ValueError('Selected Studio queue is unavailable')
        jobs = json.loads(row[0])
        return [job['job_id'] for job in jobs if job['status'] in ACTIVE_NATIVE_STATUSES]

    def stop(self, monitor_config=None, batch_id=None):
        # This intentionally does not need the terminal lock: owner STOP wins
        # even while a driver holds it. A dead driver is reattached below.
        if batch_id is not None and batch_id not in self._native_active_batches():
            # A batch that never left the queue is cancelled alone; owner STOP is not set.
            return self._stop_unstarted(batch_id)
        self.state_root.mkdir(parents=True, exist_ok=True)
        marker = self.state_root / 'STOP'
        if not marker.exists():
            try:
                with marker.open('x', encoding='utf-8') as output:
                    json.dump(dict(actor='demo_agent', at=datetime.now(timezone.utc).isoformat()), output)
                    output.write('\n'); output.flush(); os.fsync(output.fileno())
            except FileExistsError:
                pass
        active = [self.root / 'batch-drivers' / (batch_id + '.json')
                  for batch_id in self._native_active_batches()]
        seed = self._active_seed()
        if not active and seed is not None:
            return self._stop_seed(seed)
        if not active:
            return dict(status='no_active_batch', owner_stop=True)
        if len(active) != 1:
            return dict(status='stop_unconfirmed', reason='Multiple active journals require exact inspection',
                        journals=[str(path) for path in active])
        batch_id = active[0].stem
        if self._unactivated(batch_id):
            # A start refused before MT5 was touched has nothing to cancel natively.
            try:
                retired = self.retire_unactivated(batch_id)
                return dict(status='cancelled', batch_id=batch_id, attempt_id=retired.get('attempt_id'),
                            retired='retired_never_activated', owner_stop=True)
            except ValueError as exc:
                if not active[0].is_file():
                    return dict(status='stop_unconfirmed', batch_id=batch_id, owner_stop=True,
                                reason='Start never activated, but retirement refused: ' + str(exc))
        if not active[0].is_file():
            return dict(status='stop_unconfirmed', batch_id=batch_id,
                        reason='Active native job has no bounded driver journal', owner_stop=True)
        if self.process.inspect() is None and monitor_config is not None:
            self._recover_stop_monitor(batch_id, monitor_config)
        deadline = time.monotonic() + 130
        last_error = None
        while time.monotonic() < deadline:
            record = read_json(active[0])
            if record.get('stopped') is True:
                return dict(status=record['status'], batch_id=batch_id,
                            attempt_id=record.get('attempt_id'), owner_stop=True)
            try:
                with self._exclusive():
                    with self._studio('run-batch', idle=False, owner_required=False,
                                      job_id=batch_id) as (controller, broker):
                        from studio_batch_driver import run
                        result = run(controller, batch_id, resume=True, poll_seconds=1)
                        if result.get('stopped') is True:
                            return dict(status=result['status'], batch_id=batch_id,
                                        attempt_id=result.get('attempt_id'), owner_stop=True)
                        return dict(status='stop_unconfirmed', batch_id=batch_id,
                                    driver=result, owner_stop=True)
            except ValueError as exc:
                last_error = str(exc)
                if 'Another demo agent operation owns this terminal' not in last_error:
                    return dict(status='stop_unconfirmed', batch_id=batch_id,
                                reason=last_error, owner_stop=True)
            time.sleep(.5)
        return dict(status='stop_unconfirmed', batch_id=batch_id,
                    reason=last_error or 'No exact stop readback within 130 seconds', owner_stop=True)

    def _recover_stop_monitor(self, batch_id, monitor_config):
        """Open only the exact monitor to consume an owned cancellation after MT5 exits.

        STOP remains set. No tester config, start permit, grant or new attempt is
        created. The EA checks the live demo account before applying the cancel.
        """
        monitor_config = self._validate_monitor_config(monitor_config)
        from studio_strategy_settings import read_values
        preset = Path(self.install['terminal_data_root']) / 'MQL5/Presets/GOAT Studio Agent.set'
        if read_values(preset.read_bytes()) != dict(Mode_Operation='11', Studio_ReadOnlyMonitor='true',
                                                   Studio_MonitorRunPath='', EA_Desc='Studio Monitor'):
            raise ValueError('Exact passive monitor preset required for stop settlement')
        with self._exclusive():
            self._owner_clear(require_fresh=False, settling_stop=True); self._space()
            if self.process.inspect() is not None:
                raise ValueError('Terminal appeared during stopped cancellation recovery')
            if self._native_active_batches() != [batch_id]:
                raise ValueError('Exact sole active batch required for stop recovery')
            worker = self.state_root / 'workers' / (batch_id + '.json')
            if worker.is_file() and self._worker_alive(read_json(worker)):
                raise ValueError('Existing supervisor must settle STOP; no duplicate recovery')
            physical = digest(self.binary)
            verified = read_json(self.state_root / 'verified-build.json')
            if physical != self.install['ea_sha256'] or verified.get('ea_sha256') != physical:
                raise ValueError('Stopped monitor lacks exact previously verified installed build')
            from goat_studio import Controller
            from studio_batch_driver import _owned_attempt
            from studio_research_authority import operation
            # Read-only policy context: no broker scope is fabricated while MT5 is absent.
            # publish_cancel itself checks the exact native owner/attempt; all store
            # mutations remain forbidden until a real broker check after monitor launch.
            with operation('stopped-cancel-observation'):
                controller = Controller(self.installation_path).open()
                try:
                    record = read_json(self.root / 'batch-drivers' / (batch_id + '.json'))
                    if record.get('stopped') or not record.get('start_issued') or not record.get('attempt_id'):
                        raise ValueError('Retained started unresolved attempt required')
                    _owned_attempt(controller, record)
                    cancel = controller.cancel(batch_id, expected_generation=record['binding']['generation'])
                    # Never relaunch against an expired/consumed/refused cancellation.
                    gate = self.local / 'native-gate'
                    request = read_json(gate / 'request.json')
                    permit = read_json(gate / 'permit.json')
                    request_id = cancel['request_id']
                    if (request.get('action') != 'cancel' or request.get('request_id') != request_id
                            or request.get('attempt_id') != record['attempt_id']
                            or request.get('job_id') != batch_id
                            or request.get('expires_utc',0) < self.clock()+30
                            or permit.get('request_sha256') != digest(gate/'request.json')
                            or (gate / ('consumed-'+request_id+'.json')).exists()):
                        raise ValueError('Fresh exact unconsumed cancellation required; no replay')
                    self._append('recover_stop', 'cancel_published_before_monitor_launch',
                                 batch_id=batch_id, attempt_id=record['attempt_id'],
                                 request_id=request_id, monitor_config=str(monitor_config),
                                 monitor_sha256=digest(monitor_config), ea_sha256=physical)
                    # This checked fixed monitor INI has no [Tester] section and has
                    # both Algo Trading flags OFF. Preserve the stop marker throughout.
                    before = (self.local / 'ui-observation.json').stat().st_mtime_ns
                    self.process.start(monitor_config)
                    return self._readback_current(physical, after_observation_ns=before,
                                                  seconds=COLD_START_READBACK_SECONDS)
                finally:
                    controller.store.close()

    def retire_unactivated(self, batch_id):
        """Settle a start refused before MT5 was touched to cancelled (studio_retire_unactivated).

        Allowed while owner STOP is set: it sends nothing to MT5. A fresh broker
        readback proves the paired demo; the EA runtime sample proves the tester
        idle with no batch ongoing. A human TAKE CONTROL still refuses it.
        """
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid prepared batch ID')
        from studio_retire_unactivated import retire
        with self._exclusive(wait_seconds=5), self._studio('retire-unactivated', idle=False, owner_required=False,
                                                           job_id=batch_id) as (controller, broker):
            human = self.local / self.session['directory_id'] / 'human'
            if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
                raise ValueError('A human TAKE CONTROL is pending; nothing was retired.')
            self._append('retire_unactivated', 'intent', batch_id=batch_id, broker=broker)
            result = retire(controller, batch_id)
            self._append('retire_unactivated', 'retired', batch_id=batch_id, attempt_id=result.get('attempt_id'),
                         result_path=result.get('result_path'), reused=result.get('reused'))
            return result

    def _unactivated(self, batch_id):
        from studio_retire_unactivated import unactivated_hint
        from studio_research_status import queue_jobs
        job = next((item for item in queue_jobs(self.root, self.session) if item['job_id'] == batch_id), None)
        return job is not None and unactivated_hint(self.root, job)

    def _stop_unstarted(self, batch_id):
        from studio_fast_lane import stop as fast_stop
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid prepared batch ID')
        with self._exclusive(wait_seconds=5), self._studio('run-batch', idle=False, owner_required=False,
                                                           job_id=batch_id) as (controller, broker):
            result = fast_stop(controller, batch_id)
            self._append('stop_batch', 'settled', batch_id=batch_id, result=result, broker=broker)
            return result

    def start(self, batch_id, max_seconds=None):
        """One start for any prepared batch: the bounded driver, default 48 h budget."""
        if (self.state_root / 'STOP').exists():
            raise ValueError('Owner STOP is on; run clear-stop, then start again.')
        return self.run_batch(batch_id, max_seconds or 172800)

    def continue_batch(self, batch_id, *, new_batch_id=None, max_seconds=None, clear_stop=False,
                       include_failed=False, include_no_edge=False):
        """Continue a stopped, paused or finished batch: prepare the remaining work, then start it.

        A start refused before activation is retired first. Across an EA build change
        the members are re-prepared under the current installation (never by relaxing
        a check on the old package: it is only read, never launched).
        """
        from studio_fast_lane import continue_batch
        from studio_protected_peer import refresh_process
        from studio_research_status import lineage, monitor_state
        from studio_retire_unactivated import unactivated_hint
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid batch ID')
        if max_seconds is not None and (type(max_seconds) is not int or not 1 <= max_seconds <= 172800):
            raise ValueError('max_seconds must be 1..172800')
        kind = self._lane_kind(batch_id)
        if kind:
            return self._seed_unpause(batch_id, kind)
        job = next((item for item in self._jobs_readonly() if item['job_id'] == batch_id), None)
        if job is None:
            raise ValueError('Unknown batch ' + batch_id + '; research-status lists the batches of this terminal.')
        if unactivated_hint(self.root, job):
            self.retire_unactivated(batch_id)
        monitor = monitor_state(self.install, self.session, self.local, now=self.clock(), process=self._process_or_unknown())
        if monitor.get('blocker'):
            raise ValueError(monitor['blocker']['message'] + ' ' + monitor['blocker']['fix'])
        if (self.state_root / 'STOP').exists():
            if clear_stop is not True:
                raise ValueError('Owner STOP is on; continue with --clear-stop to lift it.')
            self.clear_stop()
        readback = self._refresh_readback()
        # The core's resolver: a retained, never-started successor of this batch (for
        # example after the driver failed to spawn) is reused instead of a new -rN, and
        # an explicit ID that collides with an unrelated batch refuses.
        from studio_fast_lane import resolve_successor
        queue = {item['job_id']: item for item in self._jobs_readonly()}
        new_id = resolve_successor(self.root, queue, batch_id, new_batch_id)
        with self._exclusive(), self._studio('prepare-batch', idle=True, job_id=new_id) as (controller, broker):
            peer = refresh_process(controller)
            prepared = continue_batch(controller, batch_id, new_batch_id=new_id, include_failed=include_failed,
                                      include_no_edge=include_no_edge)
            self._append('continue_batch', 'prepared', batch_id=batch_id, successor_batch_id=new_id,
                         members=prepared.get('members'), binding_changed_keys=prepared.get('binding_changed_keys'),
                         broker=broker)
        driver = self._spawn_driver(new_id, max_seconds=max_seconds or self._resume_budget(batch_id))
        return dict(prepared, peer=peer, readback=readback, driver=driver, lineage=lineage(self.root, new_id))

    def compact_evidence(self, apply=False):
        """Move finished jobs' in-row evidence history to verified logs (studio_evidence_log)."""
        from studio_evidence_log import compact
        with self._exclusive(wait_seconds=5), self._studio('compact-evidence', idle=False, owner_required=False) as (controller, broker):
            result = compact(controller, apply=apply)
            if result.get('applied'):
                self._append('compact_evidence', 'applied', jobs=[job['job_id'] for job in result['jobs']],
                             queue_bytes_before=result['queue_bytes_before'], queue_bytes_after=result['queue_bytes_after'])
            return result

    def compact_receipts(self, apply=False):
        """Archive legacy full-queue receipts and store their queue digest (studio_receipt_digest)."""
        from studio_receipt_digest import compact
        with self._exclusive(wait_seconds=5), self._studio('compact-receipts', idle=False, owner_required=False) as (controller, broker):
            result = compact(controller, apply=apply)
            if result.get('applied'):
                self._append('compact_receipts', 'applied', receipts=[item['request_id'] for item in result['receipts']],
                             receipt_bytes_before=result['receipt_bytes_before'],
                             receipt_bytes_after=result['receipt_bytes_after'])
            return result

    def cancel_pending(self, batch_id):
        """Cancel one batch that never started (pending, no launch intent).

        Uses the controller's own pending-job cancel under that exact job's scope;
        a started, reserved or running job is refused and must be stopped instead.
        """
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid prepared batch ID')
        with self._exclusive(), self._studio('run-batch', idle=True, job_id=batch_id) as (controller, broker):
            job = controller.job(batch_id)
            if job['status'] != 'pending' or 'launch_intent' in job:
                raise ValueError('Only a never-started pending batch can be cancelled here; use stop for running work')
            controller.cancel(batch_id, expected_generation=controller.state()['generation'])
            self._append('studio_cancel_pending', 'cancelled', batch_id=batch_id, broker=broker)
            return dict(status=controller.job(batch_id)['status'], batch_id=batch_id)

    def clear_stop(self):
        marker = self.state_root / 'STOP'
        if not marker.exists():
            return dict(status='already_clear')
        try:
            record = read_json(marker)
        except (ValueError, json.JSONDecodeError):
            raise ValueError('STOP was not written by this demo tool')
        if record.get('actor') != 'demo_agent':
            raise ValueError('Only this tool can clear its own STOP')
        with self._exclusive():
            broker = self._broker()
            if self._native_active_batches():
                raise ValueError('Active batch must reach a verified terminal state before clearing STOP')
            if self._active_seed() is not None:
                raise ValueError('Active seed run must reach a verified terminal state before clearing STOP')
            human = self.local / self.session['directory_id'] / 'human'
            if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
                raise ValueError('Pending human TAKE CONTROL')
            if read_json(self.local / 'ui-observation.json').get('owner') != 'agent':
                raise ValueError('Agent does not own the EA')
            marker.unlink()
            return self._append('clear_stop', 'verified', broker=broker)

    def _stop_requested(self):
        if (self.state_root / 'STOP').exists():
            return 'owner_stop'
        human = self.local / self.session['directory_id'] / 'human'
        if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
            return 'human_take_control'
        return None

    def _profile_monitor_config(self):
        """The saved GOAT Studio monitor profile as a monitor-only INI, GOAT-owned and content-addressed.

        Byte for byte what monitor-launch writes for the same profile: [Charts] ProfileLast,
        Algo Trading off, the registered EA with the passive monitor preset. No DLL grant
        and no [Tester] section; MT5 keeps its own saved DLL setting, which the readback checks.
        """
        from studio_strategy_settings import read_values
        profile = read_json(self.root / 'monitor-profile.json')
        name = profile.get('profile_name', '') if isinstance(profile, dict) else ''
        if not isinstance(name, str) or not re.fullmatch(r'GOAT-Studio-[A-Za-z0-9_-]{1,100}', name):
            raise ValueError('Saved GOAT Studio monitor profile required (monitor-profile.json)')
        preset = Path(self.install['terminal_data_root']) / 'MQL5/Presets/GOAT Studio Agent.set'
        if read_values(preset.read_bytes()) != dict(Mode_Operation='11', Studio_ReadOnlyMonitor='true',
                                                   Studio_MonitorRunPath='', EA_Desc='Studio Monitor'):
            raise ValueError('Exact passive monitor preset required')
        raw = ('[Charts]\r\nProfileLast=' + name + '\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n'
               '[StartUp]\r\nExpert=' + self.install['ea_relative_path'] + '\r\nExpertParameters=' + preset.name
               + '\r\nPeriod=M1\r\n').encode('utf-16')
        return self._retained_config('monitor-', raw)

    def _retained_config(self, prefix, raw):
        folder = self.state_root / 'monitor-restarts'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (prefix + hashlib.sha256(raw).hexdigest() + '.ini')
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('Existing verified monitor configuration changed')
        else:
            with target.open('xb') as output:
                output.write(raw)
                output.flush(); os.fsync(output.fileno())
        return target

    def _base_of_dll_granted(self, monitor_config):
        """A GOAT-retained DLL restart INI, read back as the monitor-only INI it was derived from.

        install-build derives monitor-restarts/dll-granted-<sha>.ini by inserting exactly one
        AllowDllImport=1 line. A later reopen never re-asserts that grant: it removes that one
        line again (content hash and shape checked) and launches the original monitor INI.
        """
        folder = (self.state_root / 'monitor-restarts').resolve()
        if monitor_config.parent != folder or not re.fullmatch(r'dll-granted-[0-9a-f]{64}\.ini', monitor_config.name):
            return monitor_config
        raw = monitor_config.read_bytes()
        if 'dll-granted-' + hashlib.sha256(raw).hexdigest() + '.ini' != monitor_config.name:
            raise ValueError('Retained DLL restart configuration changed')
        encoding = 'utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'
        text = raw.decode(encoding)
        newline = '\r\n' if '\r\n' in text else '\n'
        grant = 'AllowLiveTrading=0' + newline + 'AllowDllImport=1' + newline
        if text.count(grant) != 1 or len(re.findall(r'(?im)^\s*AllowDllImport\s*=', text)) != 1:
            raise ValueError('Exact retained DLL restart configuration required')
        return self._retained_config('monitor-', text.replace(grant, 'AllowLiveTrading=0' + newline, 1).encode(encoding))

    def _validate_monitor_config(self, monitor_config=None):
        if monitor_config is None:
            monitor_config = self._profile_monitor_config()
        monitor_config = self._base_of_dll_granted(Path(monitor_config).resolve()).resolve()
        sections = ini_sections(monitor_config.read_bytes())
        profile = read_json(self.root / 'monitor-profile.json')
        if (set(sections) != {'Charts', 'Experts', 'StartUp'}
                or set(sections['Charts']) != {'ProfileLast'}
                or set(sections['Experts']) != {'Enabled', 'AllowLiveTrading'}
                or set(sections['StartUp']) != {'Expert', 'ExpertParameters', 'Period'}
                or sections.get('Experts', {}).get('Enabled') != '0'
                or sections['Experts'].get('AllowLiveTrading') != '0'
                or sections.get('StartUp', {}).get('Expert') != self.install['ea_relative_path']
                or sections['StartUp'].get('ExpertParameters') != 'GOAT Studio Agent.set'
                or sections.get('Charts', {}).get('ProfileLast') != profile['profile_name']):
            raise ValueError('Monitor restart must keep Algo Trading off and exact EA path')
        return monitor_config

    def _dll_granted_restart_config(self, monitor_config, broker):
        # The V1.49 EA imports Windows DLLs. Carry only a *fresh native* MT5
        # permission through its restart; never infer a grant from agent text.
        if broker.get('dlls_allowed') is not True:
            raise ValueError('Human must enable DLL imports in the selected MT5 before EA update')
        raw = monitor_config.read_bytes()
        encoding = 'utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'
        text = raw.decode(encoding)
        if re.search(r'(?im)^\s*AllowDllImport\s*=', text):
            raise ValueError('Monitor startup already declares DLL import permission')
        newline = '\r\n' if '\r\n' in text else '\n'
        marker = 'AllowLiveTrading=0' + newline
        if text.count(marker) != 1:
            raise ValueError('Exact inert monitor startup configuration required')
        updated = text.replace(marker, marker + 'AllowDllImport=1' + newline, 1).encode(encoding)
        folder = self.state_root / 'monitor-restarts'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ('dll-granted-' + hashlib.sha256(updated).hexdigest() + '.ini')
        if target.exists():
            if target.read_bytes() != updated:
                raise ValueError('Existing verified DLL restart configuration changed')
        else:
            with target.open('xb') as output:
                output.write(updated)
                output.flush(); os.fsync(output.fileno())
        self._append('install_build', 'native_dll_grant_carried',
                     original_config_sha256=hashlib.sha256(raw).hexdigest(),
                     restart_config_sha256=hashlib.sha256(updated).hexdigest(), broker=broker)
        return target

    def _pairing_pending(self, expected_sha256, process_started_ns):
        """The relaunched EA asked GOAT for sign-in and waits for the person's approval.

        A build the account has not paired yet cannot send owner feedback, so the owner readback
        can never pass before pairing. This is proven from the EA's own sign-in status for this
        terminal (``GOAT/activation-status-<data folder>.json``), written by the new process for
        exactly the paired demo login, while the physical EX5 is the expected build. Read-only.
        """
        from studio_research_status import terminal_token
        path = Path(self.install['common_files_root']) / 'GOAT' / ('activation-status-' + terminal_token(self.install) + '.json')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
                return None
            value = read_json(path)
        except (OSError, ValueError, UnicodeError):
            return None
        observed = value.get('observedAtUtc') if isinstance(value, dict) else None
        if (not isinstance(value, dict) or value.get('reason') != 'awaiting_approval'
                or value.get('accountId') != self._paired_account()['login']
                or type(observed) is not int or observed * 1_000_000_000 < process_started_ns
                or observed > self.clock() + 5 or digest(self.binary) != expected_sha256):
            return None
        build_id = value.get('buildId')
        return dict(reason='awaiting_approval', observed_utc=observed,
                    build_id=build_id if isinstance(build_id, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,96}', build_id) else None)

    def _readback_current(self, expected_sha256, *, after_observation_ns=0,
                          expected_process=None, seconds=RUNNING_READBACK_SECONDS, pairing_ok=False):
        observation = self.local / 'ui-observation.json'
        deadline = time.monotonic() + seconds
        last_error = 'EA feedback unavailable'
        while time.monotonic() < deadline:
            try:
                selected = self.process.inspect()
                if selected is None or (expected_process is not None
                                        and selected != expected_process):
                    raise ValueError('Selected terminal process changed during launch')
                process_started_ns = int(datetime.fromisoformat(
                    selected['created_utc'].replace('Z', '+00:00')).timestamp() * 1_000_000_000)
                if (observation.stat().st_mtime_ns <= max(after_observation_ns, process_started_ns)
                        or self.clock() - observation.stat().st_mtime >= 300):
                    last_error = 'Fresh EA owner feedback unavailable'
                    pending = self._pairing_pending(expected_sha256, process_started_ns) if pairing_ok else None
                    if pending is not None:
                        # Updated, and the new build waits for the person to approve its connection. Not a
                        # verified owner readback: no verified-build record, so research still refuses until
                        # a fresh readback after pairing.
                        verified = self._broker()
                        if verified['process'] != selected:
                            raise ValueError('Selected terminal process changed during broker readback')
                        self._append('launch_terminal', 'pairing_required', ea_sha256=expected_sha256,
                                     broker=verified, activation=pending)
                        return dict(sha256=expected_sha256, broker=verified, terminal=verified['process'],
                                    pairing_required=True, activation=pending)
                    time.sleep(.5)
                    continue
                ui = read_json(observation)
                if (digest(self.binary) == expected_sha256
                        and ui.get('loaded') is True and ui.get('owner') == 'agent'
                        and ui.get('runtime', {}).get('account_demo') is True
                        and ui['runtime'].get('account_login') == self._paired_account()['login']
                        and ui['runtime'].get('account_server') == self.session['account']['server']
                        and PureWindowsPath(ui['runtime']['program_path']) == PureWindowsPath(self.binary)):
                    verified = self._broker()
                    if verified['process'] != selected:
                        raise ValueError('Selected terminal process changed during broker readback')
                    if verified['dlls_allowed'] is not True:
                        raise ValueError('Selected MT5 lost DLL imports on relaunch')
                    # The EA's own build marker is kept with the bytes it was verified for, so a later
                    # credential recovery can tell an observation of this build from an older one.
                    marker = ui.get('build')
                    write_json(self.state_root / 'verified-build.json', dict(
                        ea_sha256=expected_sha256, process=verified['process'],
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        **(dict(build=marker) if isinstance(marker, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,40}', marker) else {})))
                    self._append('launch_terminal', 'verified', ea_sha256=expected_sha256,
                                 broker=verified)
                    return dict(sha256=expected_sha256, broker=verified, terminal=verified['process'])
                last_error = 'EA/build/owner feedback has not caught up with the selected MT5 process'
            except (ValueError, KeyError, OSError, TypeError) as exc:
                last_error = str(exc)
            time.sleep(.5)
        self._append('launch_terminal', 'readback_failed', ea_sha256=expected_sha256,
                     error=last_error)
        raise ValueError('Terminal launch/readback unconfirmed after ' + str(seconds) + ' seconds: ' + last_error)

    def _launch_terminal(self, monitor_config, expected_sha256, *, adopt=False, metadata=None, pairing_ok=False,
                         enter_demo_lane=False):
        self._owner_clear(require_fresh=False); self._space()
        if self.process.inspect() is not None:
            raise ValueError('Selected terminal already runs; use status or retry readback')
        if digest(self.binary) != expected_sha256:
            raise ValueError('Physical EA differs from requested launch SHA-256')
        if adopt:
            self._adopt_installed_binary(expected_sha256, metadata=metadata, enter_demo_lane=enter_demo_lane)
        elif self.install['ea_sha256'] != expected_sha256:
            raise ValueError('Stopped-terminal launch requires the registered EA hash')
        observation = self.local / 'ui-observation.json'
        before = observation.stat().st_mtime_ns
        self._append('launch_terminal', 'before_start', ea_sha256=expected_sha256,
                     monitor_config=str(monitor_config))
        started = self.process.start(monitor_config)
        return self._readback_current(expected_sha256, after_observation_ns=before,
                                      expected_process=started, seconds=COLD_START_READBACK_SECONDS,
                                      pairing_ok=pairing_ok)

    def launch_terminal(self, monitor_config=None):
        """Reopen a stopped terminal on its monitor (default: the saved GOAT Studio profile),
        or re-read the build on a running one; either way the full owner readback runs."""
        monitor_config = self._validate_monitor_config(monitor_config)
        with self._exclusive():
            physical = digest(self.binary)
            if physical != self.install['ea_sha256']:
                raise ValueError('Installed EA differs from registered receipt; retry install-build')
            if self.process.inspect() is None:
                return self._launch_terminal(monitor_config, physical)
            self._owner_clear(); self._space()
            return dict(already_running=True, **self._readback_current(physical))

    def install_build(self, candidate, expected_sha256, monitor_config, *, require_running=False,
                      linked_login=None, bundle_version=None, agent_guide_path=None, enter_demo_lane=False,
                      credential_recovery=False):
        """Install a verified EX5 into the selected running demo and read it back.

        The session keeps its lane. A customer session (``native_human_control``, written by
        ``studio bootstrap``) stays on the customer lane, so its ``goat.exe studio`` tools keep
        working after the desktop app's update with MT5 open; an owner ``demo_direct`` session stays
        demo_direct. Only ``enter_demo_lane`` (``--enter-demo-lane``, the owner enrolling one of
        GOAT's own demo terminals) moves a session into the owner demo lane, and never together with
        the app's bundle metadata: an app update never changes a lane (goatai#1885, Terminal 3).

        ``credential_recovery`` (``--credential-recovery``, the desktop app only, after its own linked,
        consented and broker-verified demo checks): the EA lost its GOAT sign-in and cannot report, so
        the owner checks before the close accept the last EA observation at any age when it comes from
        the installed build (``_recovery_owner``), the broker must show an allowlisted, strictly flat
        demo (``_recovery_broker``) and the daily limit holds. Only for a running terminal, the linked
        login and a different build; the readback after the relaunch is unchanged.
        """
        expected_sha256 = expected_sha256.lower()
        candidate = Path(candidate).resolve()
        monitor_config = self._validate_monitor_config(monitor_config)
        if (candidate.suffix.lower() != '.ex5' or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
                or digest(candidate) != expected_sha256):
            raise ValueError('Candidate SHA-256 mismatch')
        if type(require_running) is not bool:
            raise ValueError('Running-terminal requirement must be boolean')
        if type(enter_demo_lane) is not bool:
            raise ValueError('Demo-lane enrollment must be boolean')
        if type(credential_recovery) is not bool:
            raise ValueError('Credential recovery must be boolean')
        if credential_recovery and (not require_running or linked_login is None or enter_demo_lane):
            raise ValueError('Credential recovery updates only a running terminal on the linked login, '
                             'with --require-running and --linked-login and never --enter-demo-lane')
        if enter_demo_lane and (bundle_version is not None or agent_guide_path is not None):
            raise ValueError('An app update keeps the session lane; enroll a GOAT demo terminal '
                             'with install-build --enter-demo-lane and no bundle metadata')
        if linked_login is not None and (not isinstance(linked_login,str)
                or not re.fullmatch(r'[1-9][0-9]{0,19}',linked_login)):
            raise ValueError('Exact linked login required')
        # Before the close: the EA's fresh feedback, or (credential recovery) everything but its freshness.
        owner_clear = self._recovery_owner if credential_recovery else self._owner_clear
        broker_read = self._recovery_broker if credential_recovery else self._broker
        metadata={}
        if bundle_version is not None or agent_guide_path is not None:
            if (not isinstance(bundle_version,str)
                    or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-beta\.[0-9]+)?',bundle_version)
                    or len(bundle_version)>60 or agent_guide_path is None
                    or Path(agent_guide_path).resolve()!=Path(__file__).with_name('AGENT-START-HERE.md').resolve()
                    or not Path(agent_guide_path).is_file()):
                raise ValueError('Verified running controller bundle metadata required')
            metadata=dict(bundle_version=bundle_version,agent_guide_path=str(Path(agent_guide_path).resolve()))
        def finish(result):
            if metadata:
                # A build waiting for its pairing approval cannot send owner feedback yet; the
                # receipt was already written whole (EA hash and bundle identity in one write).
                if not result.get('pairing_required'):
                    self._owner_clear()
                self._broker()
                self._adopt_installed_binary(expected_sha256,metadata=metadata,enter_demo_lane=enter_demo_lane)
                self._append('install_build','bundle_identity_verified',**metadata)
            return result
        with self._exclusive():
            if linked_login is not None and self._paired_account()['login']!=linked_login:
                raise ValueError('Selected linked login differs from paired terminal')
            if self.process.inspect() is None:
                if require_running:
                    raise ValueError('Selected terminal stopped before demo update; no launch issued')
                physical = digest(self.binary)
                if physical not in (self.install['ea_sha256'], expected_sha256):
                    raise ValueError('Stopped terminal contains an unknown EA build')
                recovered = self._launch_terminal(monitor_config, physical,
                                                  adopt=(physical == expected_sha256),
                                                  metadata=metadata if physical == expected_sha256 else None,
                                                  pairing_ok=physical == expected_sha256,
                                                  enter_demo_lane=enter_demo_lane)
                if physical == expected_sha256:
                    return finish(dict(installed=True, recovered=True, **recovered))
            owner_clear(); self._space(); native = broker_read()
            old_sha = digest(self.binary)
            if old_sha != self.install['ea_sha256']:
                raise ValueError('Running EA differs from registered receipt; no close or swap')
            if credential_recovery:
                if old_sha == expected_sha256:
                    # Reinstalling the build whose sign-in was rejected fixes nothing: it needs a new connection.
                    raise ValueError('Credential recovery installs a different build; this one is already installed, '
                                     'so approve its connection code instead')
                self._require_recovery_budget()
            # The same bytes already run here: verify them where they run instead of closing MT5.
            # An owner enrollment still takes the full path below unless the session is already
            # demo_direct; every other install keeps the session's lane.
            if (old_sha == expected_sha256
                    and self.install['ea_sha256'] == expected_sha256
                    and (not enter_demo_lane or self.session.get('authority_kind') == 'demo_direct')
                    and self.session.get('installation_sha256') == sha(self.install)):
                ui = read_json(self.local / 'ui-observation.json')
                verified_path = self.state_root / 'verified-build.json'
                prior = read_json(verified_path) if verified_path.is_file() else {}
                if (ui.get('loaded') is True and ui.get('owner') == 'agent'
                        and ui.get('runtime', {}).get('account_demo') is True
                        and PureWindowsPath(ui['runtime'].get('program_path', '')) == PureWindowsPath(self.binary)
                        and prior.get('ea_sha256') == expected_sha256
                        and prior.get('process') == native['process']):
                    return finish(dict(already_installed=True, sha256=old_sha, broker=native))
                if (ui.get('loaded') is True and ui.get('owner') == 'agent'
                        and ui.get('runtime', {}).get('account_demo') is True
                        and PureWindowsPath(ui['runtime'].get('program_path', '')) == PureWindowsPath(self.binary)):
                    # Installed earlier (for example while its pairing was pending) and answering now:
                    # verify it where it runs instead of closing MT5 for the same bytes again.
                    verified = self._readback_current(expected_sha256, expected_process=native['process'])
                    return finish(dict(already_installed=True, **verified))
            backup = self.state_root / 'backups' / (old_sha + '.ex5')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and digest(backup) != old_sha:
                raise ValueError('Existing backup has changed')
            if not backup.exists():
                with backup.open('xb') as output, self.binary.open('rb') as source:
                    shutil.copyfileobj(source, output)
                    output.flush(); os.fsync(output.fileno())
            self._append('install_build', 'before_close', old_sha256=old_sha,
                         new_sha256=expected_sha256, broker=native, backup=str(backup),
                         **(dict(credential_recovery=True, login=native['login']) if credential_recovery else {}))
            owner_clear()
            restart_broker = broker_read()
            if restart_broker['process'] != native['process']:
                raise ValueError('Selected MT5 changed before restart')
            restart_config = self._dll_granted_restart_config(monitor_config, restart_broker)
            self.process.close(native['process'])
            # MT5 can take more than a minute to flush and exit after SC_CLOSE.
            # Wait for that exact process to exit normally; never force-kill it.
            deadline = time.monotonic() + 150
            while self.process.inspect() is not None and time.monotonic() < deadline:
                time.sleep(.25)
            if self.process.inspect() is not None:
                raise ValueError('Selected terminal did not close normally; build unchanged')
            temporary = self.binary.with_name(self.binary.name + '.demo-agent-' + str(os.getpid()))
            try:
                shutil.copyfile(candidate, temporary)
                if digest(temporary) != expected_sha256:
                    raise ValueError('Staged candidate SHA-256 mismatch')
                os.replace(temporary, self.binary)
            finally:
                temporary.unlink(missing_ok=True)
            self._append('install_build', 'binary_replaced', old_sha256=old_sha,
                         new_sha256=expected_sha256)
            # One receipt write: the new EA hash together with this bundle's identity, so the
            # receipt never names the new EA under the previous app version.
            self._adopt_installed_binary(expected_sha256, metadata=metadata, enter_demo_lane=enter_demo_lane)
            verified = self._launch_terminal(restart_config, expected_sha256, pairing_ok=True)
            self._append('install_build', 'pairing_required' if verified.get('pairing_required') else 'verified',
                         new_sha256=expected_sha256, broker=verified['broker'])
            return finish(dict(installed=True, **verified))

    def _adopt_installed_binary(self, expected_sha256, *, metadata=None, enter_demo_lane=False):
        """Keep local app/controller identity aligned with the physical EX5.

        The old research proof remains archived in place; demo tools use the
        broker check and owner STOP instead of treating that proof as a gate.

        The session is rebound to the new receipt and keeps its lane (authority_kind):
        only ``enter_demo_lane`` moves it into the owner demo lane (demo_direct).
        """
        if digest(self.binary) != expected_sha256:
            raise ValueError('Physical EA changed before local identity update')
        backup = self.state_root / 'backups'
        backup.mkdir(parents=True, exist_ok=True)
        for name, path in (('installation', self.installation_path),
                           ('session', self.root / 'session.json')):
            saved = backup / (name + '-' + digest(path) + '.json')
            if not saved.exists():
                with saved.open('xb') as output, path.open('rb') as source:
                    shutil.copyfileobj(source, output)
                    output.flush(); os.fsync(output.fileno())
        installed = read_json(self.installation_path)
        if installed['ea_sha256'] != expected_sha256 or any(installed.get(k)!=v for k,v in (metadata or {}).items()):
            installed['ea_sha256'] = expected_sha256
            installed.update(metadata or {})
            installed['demo_installed_at'] = datetime.now(timezone.utc).isoformat()
            write_json(self.installation_path, installed)
        checked = load_installation(self.installation_path)
        session = read_json(self.root / 'session.json')
        lane = session.get('authority_kind')
        if (enter_demo_lane and lane != 'demo_direct') or session.get('installation_sha256') != sha(checked):
            if enter_demo_lane:
                session['authority_kind'] = 'demo_direct'
            session['installation_sha256'] = sha(checked)
            write_json(self.root / 'session.json', session)
        self.install, self.session = checked, session
        self._append('install_build', 'local_identity_verified', ea_sha256=expected_sha256,
                     installation_sha256=sha(checked), session_sha256=sha(session),
                     authority_kind=session.get('authority_kind'), previous_authority_kind=lane)

    def _lane_restore_review(self):
        """Read-only: prove this demo_direct session is a customer session an app update moved.

        Before this fix every install-build moved the session it updated into the owner demo lane,
        including the desktop app's update with MT5 open (goatai#1885: Terminal 3, 2026-10-04).
        The proof needs all of: this tool's own retained backup of this exact session on the
        customer lane (native_human_control), the session bound to the current receipt, the
        controller store still holding the customer lane's native_human_control authority for this
        binding, no typed research continuation, an action log that shows only update and relaunch
        steps (never owner demo-lane work), and no owner STOP, batch, driver or seed in flight.
        """
        session = read_json(self.root / 'session.json')
        lane = session.get('authority_kind')
        if lane == 'native_human_control':
            return dict(status='already_customer_lane', authority_kind=lane)
        if lane != 'demo_direct':
            raise ValueError('restore-lane returns only a demo_direct session to the customer lane')
        if session.get('installation_sha256') != sha(self.install):
            raise ValueError('Session is not bound to the current receipt; finish or retry the update first')
        identity = {key: value for key, value in session.items() if key not in LANE_IDENTITY_EXCLUDED}
        evidence = None
        for path in sorted((self.state_root / 'backups').glob('session-*.json')):
            try:
                if path.is_symlink() or path.name != 'session-' + digest(path) + '.json':
                    continue
                saved = read_json(path)
            except (OSError, ValueError, UnicodeError):
                continue
            if (isinstance(saved, dict) and saved.get('authority_kind') == 'native_human_control'
                    and {key: value for key, value in saved.items() if key not in LANE_IDENTITY_EXCLUDED} == identity):
                evidence = path
                break
        if evidence is None:
            raise ValueError('No retained customer-lane backup of this exact session; restore-lane changes nothing')
        if (self.root / 'research-authority.json').exists():
            raise ValueError('A typed research continuation is bound here; restore-lane changes nothing')
        binding = packed(dict(terminal_id=session['terminal_id'], run_id=session['run_id']))
        try:
            with closing(sqlite3.connect((self.root / 'studio.sqlite').as_uri() + '?mode=ro', uri=True)) as db:
                row = db.execute('SELECT kind,provenance FROM studio_authorities WHERE binding=?', (binding,)).fetchone()
                queue = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
        except sqlite3.Error as exc:
            raise ValueError('Controller store unreadable; restore-lane changes nothing') from exc
        if (row is None or row[0] != 'native_human_control'
                or json.loads(row[1]) != dict(kind='native_human_control', binding=json.loads(binding))):
            raise ValueError('The controller store holds no customer-lane authority for this session; restore-lane changes nothing')
        updates, work = 0, set()
        log = self.state_root / 'actions.jsonl'
        if log.is_file():
            with log.open(encoding='utf-8') as rows:
                for line in rows:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError as exc:
                        raise ValueError('Demo action log unreadable; restore-lane changes nothing') from exc
                    operation = entry.get('operation') if isinstance(entry, dict) else None
                    if operation not in UPDATE_OPERATIONS:
                        work.add(str(operation))
                    elif operation == 'install_build' and entry.get('phase') == 'local_identity_verified':
                        updates += 1
        if not updates:
            raise ValueError('No retained install-build record for this session; restore-lane changes nothing')
        if work:
            raise ValueError('This session has done owner demo-lane work (' + ', '.join(sorted(work))
                             + '); restore-lane only undoes an app update\'s lane change')
        if (self.state_root / 'STOP').exists():
            raise ValueError('Owner STOP is set; restore-lane changes nothing')
        active = [job['job_id'] for job in (json.loads(queue[0]) if queue else [])
                  if job['status'] in ACTIVE_NATIVE_STATUSES]
        if active:
            raise ValueError('Batch ' + ', '.join(active) + ' is active; restore-lane waits for it to finish')
        for worker in (self.state_root / 'workers').glob('*.json'):
            if self._worker_alive(read_json(worker)):
                raise ValueError('A live demo batch driver owns this terminal; restore-lane waits')
        if self._active_seed() is not None:
            raise ValueError('A seed or catch-up run holds this terminal; restore-lane waits for it to finish')
        return dict(status='ready_to_restore', authority_kind=lane, restores_to='native_human_control',
                    evidence=str(evidence), session_sha256=sha(session),
                    next_action='Run restore-lane --apply. It rewrites only this session\'s lane; MT5, the EA and the queue are untouched.')

    def restore_lane(self, apply=False):
        """Preview, then with ``apply`` return a customer session an app update moved into the owner
        demo lane (demo_direct) to native_human_control. Local session file only: never touches MT5,
        the EA, the receipt or the controller store. The previous session bytes are kept in backups."""
        if type(apply) is not bool:
            raise ValueError('restore-lane --apply must be boolean')
        review = self._lane_restore_review()
        if not apply or review['status'] == 'already_customer_lane':
            return review
        with self._exclusive():
            review = self._lane_restore_review()
            if review['status'] == 'already_customer_lane':
                return review
            current = self.root / 'session.json'
            backup = self.state_root / 'backups' / ('session-' + digest(current) + '.json')
            if not backup.exists():
                with backup.open('xb') as output, current.open('rb') as source:
                    shutil.copyfileobj(source, output)
                    output.flush(); os.fsync(output.fileno())
            restored = dict(read_json(current), authority_kind='native_human_control')
            write_json(current, restored)
            self.session = restored
            self._append('restore_lane', 'restored', previous_authority_kind=review['authority_kind'],
                         authority_kind='native_human_control', evidence=review['evidence'],
                         demo_direct_backup=str(backup), session_sha256=sha(restored))
            return dict(status='restored', authority_kind='native_human_control',
                        previous_authority_kind=review['authority_kind'], evidence=review['evidence'],
                        demo_direct_backup=str(backup), session_sha256=sha(restored),
                        next_action='Customer-lane tools (goat.exe studio, suite.closeTerminal) work again. Nothing in MT5 changed.')

    def _goat_relaunched(self, process):
        """True when GOAT itself started this MT5 process: a /config file in a GOAT-owned folder.

        Every GOAT relaunch passes /config: the batch config start (controller state
        attempts/<id>/startup.ini), the EA's own member-boundary restart (Common Files),
        a seed or catch-up member (<data root>/config/GOATStudio) and a monitor reopen
        (controller state monitor-restarts or monitor-launches). A person's shortcut or a manual
        reopen has no such /config, so it never qualifies. Read-only; any doubt is False.
        """
        reader = getattr(self.process, 'command_line', None)
        if reader is None:
            return False
        try:
            line = reader(process)
        except (ValueError, OSError, subprocess.SubprocessError):
            return False
        # Windows writes GOAT's own launch as `"...\terminal64.exe" "/config:C:\path with
        # spaces\startup.ini"`: the quote comes before /config and the path has spaces. Accept
        # /config after start, whitespace or a quote; a quoted value, or an unquoted path up to .ini.
        match = re.search(r'(?i)(?:^|\s|")/config:(?:"([^"]+)"|(.+?\.ini)(?="|\s|$))', line or '')
        if match is None:
            return False
        try:
            config = Path(match.group(1) or match.group(2)).resolve()
            roots = [Path(self.install['controller_state_root']).resolve(),
                     Path(self.install['common_files_root']).resolve(),
                     (Path(self.install['terminal_data_root']) / 'config' / 'GOATStudio').resolve()]
        except (OSError, ValueError, KeyError):
            return False
        return config.suffix.lower() == '.ini' and any(config.is_relative_to(root) for root in roots)

    def _relaunch_readback(self, verified, broker, physical):
        """Re-prove the build after GOAT's own MT5 relaunch instead of stranding the next batch.

        Only when the last verified proof is for these exact EA bytes, the new process
        runs the same terminal executable (the broker proves the same data root and the
        paired demo), it started after the verified one, and GOAT launched it. The full
        owner readback still runs on the new process; nothing is relaxed.
        """
        if not self._relaunch_qualifies(verified, broker.get('process'), physical):
            return False
        current = broker['process']
        self._append('readback_refresh', 'goat_relaunch', ea_sha256=physical,
                     prior_process=verified['process'], process=current)
        self._readback_current(physical, expected_process=current)
        return True

    def _relaunch_qualifies(self, verified, current, physical):
        prior = verified.get('process')
        if (verified.get('ea_sha256') != physical or physical != self.install['ea_sha256']
                or not isinstance(prior, dict) or not isinstance(current, dict)
                or not prior.get('executable') or not current.get('executable')
                or PureWindowsPath(prior['executable']) != PureWindowsPath(current['executable'])
                or PureWindowsPath(current['executable']) != PureWindowsPath(self.install['terminal_executable'])):
            return False
        try:
            started = [datetime.fromisoformat(item['created_utc'].replace('Z', '+00:00')) for item in (prior, current)]
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        return started[1] > started[0] and self._goat_relaunched(current)

    @contextmanager
    def _studio(self, operation_name, *, idle, owner_required=True, job_id=None, recovery=False):
        # The local adapter is the only entry to the demo policy. The broker
        # supplies the demo bit; the saved session cannot assert it by itself.
        if owner_required:
            self._owner_clear(); self._space()
        broker = self._broker(idle=idle)
        legacy_recovery = (operation_name == 'demo-recover-orphan'
                           and self.session.get('authority_kind') in (None, 'native_human_control'))
        if self.session.get('authority_kind') != 'demo_direct' and not legacy_recovery:
            raise ValueError('Install and verify the selected V1.49 build before demo Studio control')
        physical = digest(self.binary)
        if physical != self.install['ea_sha256']:
            raise ValueError('Installed demo EA hash changed')
        if owner_required:
            if legacy_recovery:
                # Verify the already-running installed monitor without upgrading
                # its binary or rewriting the session bound by the old review.
                self._readback_current(physical)
            verified_path = self.state_root / 'verified-build.json'
            verified = read_json(verified_path) if verified_path.is_file() else {}
            if (verified.get('ea_sha256') != physical
                    or verified.get('process') != broker['process']):
                if not self._relaunch_readback(verified, broker, physical):
                    raise ValueError('Selected build lacks native readback for this terminal process')
        from goat_studio import Controller
        from studio_research_authority import demo_agent_scope, operation
        with operation(operation_name), demo_agent_scope(
                root=self.root, installation_sha256=sha(self.install),
                account=dict(login=broker['login'], server=broker['server']),
                job_id=job_id, legacy_recovery=legacy_recovery):
            controller = Controller(self.installation_path).open(recovery=recovery)
            try:
                yield controller, broker
            finally:
                controller.store.close()

    def recover_orphan(self, review_id=None, *, wait_seconds=15):
        """Publish one proven idle orphan recovery, or observe its retained result.

        Never grants control, pretends human confirmation, replays an uncertain
        request, or starts research. The EA remains the only flag writer.
        """
        from studio_orphan_recovery import prepare, apply, status
        from studio_demo_orphan_successor import active as active_successor, recover as recover_successor, completed as complete_successor
        explicit_observation = review_id is not None
        if type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= 60:
            raise ValueError('Recovery observation wait must be between 0 and 60 seconds')
        with self._exclusive(), self._studio('demo-recover-orphan', idle=True, recovery=True) as (controller, broker):
            for worker in (self.root / 'demo-agent/workers').glob('*.json'):
                if self._worker_alive(read_json(worker)):
                    raise ValueError('A live demo driver/worker must finish before orphan recovery')
            pending = self.root / 'orphan-recovery-pending.json'
            retained = active_successor(self.root)
            if review_id is None and pending.exists():
                review_id = read_json(pending)['review_id']
            if retained is not None and not explicit_observation:
                result = recover_successor(controller, retained)
                review_id = result['review_id']
            elif review_id is not None:
                result = status(controller, review_id)
                evidence = result.get('evidence', {})
                # An explicit review-id remains observation-only. Only the known
                # pre-consumption review refusal may gain a fresh successor.
                if (not explicit_observation and result['status'] == 'reconcile_required'
                        and evidence.get('status') == 'receipt_observed'
                        and evidence.get('consumed') is False
                        and evidence.get('receipt', {}).get('status') == 'ORPHAN_REVIEW_REJECTED'):
                    result = recover_successor(controller, original_review_id=review_id, evidence=evidence)
                    review_id = result['review_id']
            else:
                review = prepare(controller)
                review_id = review['review_id']
                self._append('recover_orphan', 'reviewed', broker=broker, review=review)
                result = apply(controller, review_id, owner_research=True)
                self._append('recover_orphan', 'published', result=result)
            deadline = time.monotonic() + wait_seconds
            while result['status'] in ('published_not_recovered', 'reconcile_required') and time.monotonic() < deadline:
                time.sleep(.5)
                try:
                    result = status(controller, review_id)
                except ValueError as exc:
                    if str(exc) != 'Runtime policy mismatch: batch_ongoing':
                        raise
                    # A consumed recovery receipt may precede the next UI sample.
                    # Retry that read only; never publish another native action.
                    result = dict(result, last_readback_error=str(exc))
            self._append('recover_orphan', 'observed', broker=broker, result=result)
            if result['status'] == 'recovered':
                complete_successor(self.root, review_id)
            return result

    def prepare_batch(self, batch_id, plan):
        from studio_batch import prepare_batch
        from studio_seed_slot import refuse_prepare_while_seed_owns
        refuse_prepare_while_seed_owns(self.root)   # before any broker or terminal check
        with self._exclusive(), self._studio('prepare-batch', idle=True, job_id=batch_id) as (controller, broker):
            self._append('studio_prepare_batch', 'intent', batch_id=batch_id,
                         plan=str(Path(plan).resolve()), plan_sha256=digest(plan), broker=broker)
            result = prepare_batch(controller, batch_id, plan)
            observed = controller.job(batch_id)
            member_count = len(observed['configuration']['batch_members'])
            if (observed['status'] != 'pending' or
                    member_count != result.get('member_count', member_count)):
                raise ValueError('Studio batch queue readback differs after preparation')
            self._append('studio_prepare_batch', 'verified', batch_id=batch_id,
                         member_count=member_count, configuration_sha256=observed['configuration_sha256'])
            return dict(result, member_count=member_count)

    def _worker_alive(self, record):
        envelope_path = record.get('launch_envelope')
        if envelope_path:
            envelope = read_json(envelope_path)
            finished = Path(envelope['finished'])
            if finished.is_file():
                if read_json(finished).get('nonce') != record.get('nonce'):
                    raise ValueError('Persistent driver completion identity changed')
                return False
            started = Path(envelope['started'])
            if not started.is_file():
                raise ValueError('Persistent driver launch unresolved; inspect its existing task, never duplicate')
            native = read_json(started)
            if native.get('nonce') != record.get('nonce'):
                raise ValueError('Persistent driver bootstrap identity changed')
            record = dict(record, pid=native['pid'])
        pid = record.get('pid')
        nonce = record.get('nonce')
        if type(pid) is not int or pid <= 0 or not isinstance(nonce, str):
            return False
        script = ('[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
                  'Get-CimInstance Win32_Process -Filter "ProcessId = ' + str(pid) +
                  '" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress')
        try:
            raw = subprocess.check_output(['powershell', '-NoProfile', '-Command', script],
                                          text=True, encoding='utf-8-sig', timeout=10,
                                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Cannot verify detached driver process; no duplicate launch') from exc
        row = json.loads(raw) if raw else None
        return bool(row and row.get('ProcessId') == pid and nonce in (row.get('CommandLine') or ''))

    def _spawn_driver(self, batch_id, *, max_seconds=None, resume=False, pause_seconds=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid prepared batch ID')
        if not resume and (type(max_seconds) is not int or not 1 <= max_seconds <= 172800):
            raise ValueError('Batch deadline must be 1..172800 seconds')
        if pause_seconds is not None and (not resume or type(pause_seconds) is not int
                                          or not 1 <= pause_seconds <= 172800):
            raise ValueError('A pause supervisor resumes a retained journal for 1..172800 seconds')
        journal = self.root / 'batch-drivers' / (batch_id + '.json')
        worker_path = self.state_root / 'workers' / (batch_id + '.json')
        if worker_path.is_file():
            prior_worker = read_json(worker_path)
            if self._worker_alive(prior_worker):
                return dict(status='already_supervising', worker=prior_worker,
                            driver_status=read_json(journal).get('status') if journal.is_file() else None,
                            native_running_unverified=True)
        with self._exclusive(), self._studio('run-batch', idle=not resume,
                owner_required=not resume, job_id=batch_id) as (controller, broker):
            if journal.is_file():
                from studio_batch_driver import status, refused_before_dispatch
                previous = status(controller, batch_id)
                retry = not resume and refused_before_dispatch(read_json(journal), controller.job(batch_id))
                if not retry and (previous.get('stopped') is True or not resume):
                    return dict(status='existing_driver', driver=previous)
                if retry:
                    # Archive the refused journal now, so the wait below only sees the new worker's.
                    from studio_batch_driver import _retire_refused_journal
                    from studio_native_gate import exclusive_gate
                    with exclusive_gate(self.root / 'batch-driver-gate'):
                        _retire_refused_journal(controller, batch_id, journal, time)
            elif resume:
                raise ValueError('No retained driver journal exists to resume')
            else:
                job = controller.job(batch_id)
                if job['status'] != 'pending' or 'launch_intent' in job:
                    raise ValueError('Only the exact unstarted prepared batch can be launched')
            if worker_path.is_file() and self._worker_alive(read_json(worker_path)):
                return dict(status='already_supervising', worker=read_json(worker_path))
            nonce = secrets.token_hex(16)
            worker = dict(schema_version=1, batch_id=batch_id, nonce=nonce,
                          status='reserved', resume=resume, max_seconds=max_seconds,
                          created_at=datetime.now(timezone.utc).isoformat())
            if pause_seconds is not None:
                worker['pause_seconds'] = pause_seconds
            worker_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(worker_path, worker)
            self._append('studio_run_batch', 'worker_reserved', batch_id=batch_id,
                         resume=resume, max_seconds=max_seconds, broker=broker, nonce=nonce,
                         pause_seconds=pause_seconds)
            log_path = worker_path.with_name(batch_id + '-' + nonce + '.log')
            argv = [sys.executable, str(Path(__file__).resolve()), '--installation',
                    str(self.installation_path), '_drive-batch', '--batch-id', batch_id,
                    '--nonce', nonce]
            if not resume:
                argv += ['--max-seconds', str(max_seconds)]
            elif pause_seconds is not None:
                argv += ['--pause-seconds', str(pause_seconds)]
            flags = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                     | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                     | getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                if os.name == 'nt':
                    from studio_durable_driver import launch
                    child = launch(argv, log_path=log_path, worker_path=worker_path)
                    worker = read_json(worker_path)
                else:
                    with log_path.open('ab') as log:
                        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                            creationflags=flags)
            except OSError as exc:
                worker.update(status='spawn_failed', error=str(exc))
                write_json(worker_path, worker)
                raise ValueError('Detached batch driver did not start; no native dispatch') from exc
            worker.update(status='spawned', pid=child.pid, log=str(log_path))
            write_json(worker_path, worker)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if journal.is_file():
                record = read_json(journal)
                return dict(status='driver_journal_recorded', worker=worker,
                            driver_status=record.get('status'),
                            attempt_id=record.get('attempt_id'),
                            native_running_unverified=True)
            if child.poll() is not None:
                raise ValueError('Detached driver exited before a journal was recorded; inspect ' + str(log_path))
            time.sleep(.2)
        return dict(status='driver_starting', worker=worker,
                    native_running_unverified=True)

    def run_batch(self, batch_id, max_seconds):
        return self._spawn_driver(batch_id, max_seconds=max_seconds)

    def resume_batch(self, batch_id):
        return self._spawn_driver(batch_id, resume=True)

    def _drive_batch(self, batch_id, nonce, max_seconds, pause_seconds=None):
        from studio_batch_driver import run
        worker_path = self.state_root / 'workers' / (batch_id + '.json')
        worker = read_json(worker_path)
        if worker.get('nonce') != nonce or worker.get('batch_id') != batch_id:
            raise ValueError('Detached worker identity changed')
        resume = worker['resume']
        if (max_seconds != worker.get('max_seconds') or pause_seconds != worker.get('pause_seconds')
                or worker.get('status') not in ('reserved', 'spawned')):
            raise ValueError('Detached worker budget or launch state changed')
        with self._exclusive(wait_seconds=20), self._studio('run-batch', idle=not resume,
                owner_required=not resume, job_id=batch_id) as (controller, broker):
            worker.update(status='supervising', pid=os.getpid())
            write_json(worker_path, worker)
            self._append('studio_run_batch', 'supervising', batch_id=batch_id,
                         resume=resume, broker=broker, nonce=nonce, pause_seconds=pause_seconds)
            result = (run(controller, batch_id, resume=True, pause_seconds=pause_seconds) if resume else
                      run(controller, batch_id, max_seconds=max_seconds,
                          min_free_bytes=MIN_FREE_BYTES))
            worker.update(status='returned', result_status=result['status'])
            write_json(worker_path, worker)
            self._append('studio_run_batch', 'returned', batch_id=batch_id,
                         status=result['status'], attempt_id=result.get('attempt_id'))
            return result

    def batch_driver_status(self, batch_id):
        from studio_batch_driver import status
        with self._studio('batch-driver-status', idle=False, owner_required=False, job_id=batch_id) as (controller, broker):
            return dict(broker=broker, driver=status(controller, batch_id))

    def batch_status(self, batch_id):
        from studio_batch import batch_status
        with self._studio('batch-status', idle=False, owner_required=False, job_id=batch_id) as (controller, broker):
            result = batch_status(controller, batch_id)
            return dict(broker=broker, studio=result)

    # ------------------------------------------------------------ research operations
    #
    # research-status is one read-only call for a UI lane or an agent. batch-pause
    # and batch-resume are the supported way to stop and continue research without
    # losing work; see studio_batch_pause for the safety rules.

    PAUSE_SUPERVISION_SECONDS = 6 * 3600

    def _jobs_readonly(self):
        from studio_research_status import queue_jobs
        return queue_jobs(self.root, self.session)

    def _process_or_unknown(self):
        try:
            return self.process.inspect()
        except (ValueError, OSError, subprocess.SubprocessError):
            return 'unknown'

    def research_status(self):
        """Read-only: terminal, account, build, activity, pace/ETA, pause, driver, disk, monitor."""
        from studio_research_status import research_status
        try:
            jobs = self._jobs_readonly()
        except (OSError, sqlite3.Error, ValueError):
            jobs = None   # research_status reports the queue error itself
        return research_status(root=self.root, install=self.install, session=self.session, local=self.local,
                               now=self.clock(), process=self._process_or_unknown(), jobs=jobs,
                               worker_alive=self._worker_alive, owner_stop=(self.state_root / 'STOP').exists())

    def _lane_kind(self, batch_id):
        """'seed' or 'catchup' when this ID names a runner batch (not a native queue job), else None."""
        for kind, lane in LANES.items():
            if ((self.root / lane['folder'] / batch_id / 'state.json').is_file()
                    and not any(job['job_id'] == batch_id for job in self._jobs_readonly())):
                return kind
        return None

    def _ensure_pause_supervisor(self, batch_id):
        """A live driver keeps supervising; otherwise start one bounded pause supervisor."""
        worker_path = self.state_root / 'workers' / (batch_id + '.json')
        try:
            if worker_path.is_file() and self._worker_alive(read_json(worker_path)):
                return dict(status='driver_supervising', supervising=True)
        except ValueError as exc:
            return dict(status='supervisor_unknown', supervising=None, reason=str(exc))
        try:
            spawned = self._spawn_driver(batch_id, resume=True, pause_seconds=self.PAUSE_SUPERVISION_SECONDS)
        except ValueError as exc:
            return dict(status='not_supervising', supervising=False, reason=str(exc),
                        fix='Open this MT5 terminal so its demo account can be verified, then pause again.')
        return dict(status=spawned['status'], supervising=spawned['status'] in (
            'already_supervising', 'driver_journal_recorded', 'driver_starting'),
            budget_seconds=self.PAUSE_SUPERVISION_SECONDS)

    def batch_pause(self, batch_id, *, immediate=False):
        """Pause a running batch (or seed hunt) at its next safe point; idempotent.

        Like STOP this takes no terminal lock: a live driver honours the pause on
        its next tick. Without a live driver a bounded pause supervisor starts.
        """
        from studio_batch_pause import PauseRefused, load, public, request
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid batch ID')
        if type(immediate) is not bool:
            raise ValueError('immediate must be a boolean')
        kind = self._lane_kind(batch_id)
        if kind:
            return self._seed_pause(batch_id, kind)
        job = next((item for item in self._jobs_readonly() if item['job_id'] == batch_id), None)
        if job is None:
            raise PauseRefused('Unknown batch ' + batch_id + '; research-status lists this terminal\'s batches.')
        journal_path = self.root / 'batch-drivers' / (batch_id + '.json')
        journal = read_json(journal_path) if journal_path.is_file() else None
        before = load(self.root, batch_id)
        record, created = request(self.root, job, journal, now=self.clock(), requested_by='agent', immediate=immediate)
        if created or before is None:
            self._append('batch_pause', 'requested', batch_id=batch_id, pause_id=record['pause_id'],
                         immediate=immediate, adopted_stop=record.get('adopted_stop'))
        if record['state'] != 'pausing':
            return dict(public(record), supervisor=None)
        supervisor = self._ensure_pause_supervisor(batch_id)
        return dict(public(load(self.root, batch_id)), supervisor=supervisor)

    def _seed_pause(self, batch_id, kind='seed'):
        word = LANES[kind]['word']
        with self._seed_scope(kind + '-status', batch_id, kind) as (controller, evidence):
            result = self._seed_runner(controller, kind).request_pause(batch_id, now=self.clock())
        self._append(kind + '_pause', 'requested', batch_id=batch_id)
        return dict(kind=kind, job_id=batch_id, state='pausing', seed=result,
                    plain='The running ' + word + ' member finishes and is kept; no new member starts until you resume.')

    def _refresh_readback(self):
        """After a terminal restart, re-read the build/owner proof the start gate requires."""
        from studio_batch_pause import PauseRefused
        current = self.process.inspect()
        if current is None:
            raise PauseRefused('MT5 for this terminal is closed; open it, then resume.')
        physical = digest(self.binary)
        if physical != self.install['ea_sha256']:
            raise PauseRefused('The installed EA differs from this installation receipt; reinstall the build before resuming.')
        verified_path = self.state_root / 'verified-build.json'
        verified = read_json(verified_path) if verified_path.is_file() else {}
        if verified.get('process') == current and verified.get('ea_sha256') == physical:
            return 'unchanged'
        with self._exclusive():
            self._readback_current(physical, expected_process=current)
        return 'refreshed'

    def batch_resume(self, batch_id, *, new_batch_id=None, resume_token=None, max_seconds=None,
                     clear_stop=False, include_failed=False, include_no_edge=False):
        """Continue a paused batch: remaining work under a new ID, started under the bounded driver."""
        from studio_batch import resume_batch
        from studio_batch_pause import (PauseRefused, load, mark_resumed, plan_resume, refusal, successor_id,
                                        verify_resumable)
        from studio_protected_peer import refresh_process
        from studio_research_status import lineage, monitor_state
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Invalid batch ID')
        if max_seconds is not None and (type(max_seconds) is not int or not 1 <= max_seconds <= 172800):
            raise ValueError('max_seconds must be 1..172800')
        kind = self._lane_kind(batch_id)
        if kind:
            return self._seed_unpause(batch_id, kind)
        record = load(self.root, batch_id)
        if record is None:
            raise PauseRefused('No pause is recorded for batch ' + batch_id + '; pause it first.')
        # A reserved successor that never ran (retired unactivated / never started, or
        # cancelled before its start) releases the lineage, recorded append-only.
        from studio_batch_pause import release_unactivated
        released = release_unactivated(self.root, batch_id, {item['job_id']: item for item in self._jobs_readonly()},
                                       now=self.clock())
        if released:
            self._append('batch_resume', 'successor_released', batch_id=batch_id,
                         successor_batch_id=released['successor_batch_id'], proof=released['proof'])
            record = load(self.root, batch_id)
        if record['state'] == 'resumed':
            new_id = record['successor_batch_id']
            job = next((item for item in self._jobs_readonly() if item['job_id'] == new_id), None)
            journal = self.root / 'batch-drivers' / (new_id + '.json')
            driver = None
            if job is not None and job['status'] == 'pending' and not journal.is_file():
                driver = self._spawn_driver(new_id, max_seconds=max_seconds or self._resume_budget(batch_id))
            return dict(state='resumed', source_batch_id=batch_id, batch_id=new_id, reused=True, driver=driver,
                        lineage=lineage(self.root, new_id))
        if record['state'] != 'paused':
            raise refusal(record)
        monitor = monitor_state(self.install, self.session, self.local, now=self.clock(), process=self._process_or_unknown())
        if monitor.get('blocker'):
            raise PauseRefused(monitor['blocker']['message'] + ' ' + monitor['blocker']['fix'])
        if (self.state_root / 'STOP').exists():
            if clear_stop is not True:
                raise PauseRefused('Owner STOP is on for this terminal. Resume with clear_stop to lift it '
                                   '(only a STOP written by GOAT can be lifted).')
            self.clear_stop()
        readback = self._refresh_readback()
        existing = {item['job_id'] for item in self._jobs_readonly()}
        new_id = new_batch_id or record.get('resume_batch_id') or successor_id(batch_id, existing)
        if not isinstance(new_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', new_id):
            raise ValueError('Invalid successor batch ID')
        plan_resume(self.root, batch_id, new_id, now=self.clock())
        with self._exclusive(), self._studio('prepare-batch', idle=True, job_id=new_id) as (controller, broker):
            verify_resumable(controller, batch_id, resume_token)
            peer = refresh_process(controller)
            self._append('batch_resume', 'intent', batch_id=batch_id, successor_batch_id=new_id,
                         peer=peer.get('status'), broker=broker)
            from studio_fast_lane import binding_changed
            prepared = resume_batch(controller, batch_id, new_id, include_failed=include_failed,
                                    include_no_edge=include_no_edge, allow_peer_refresh=True,
                                    allow_binding_change=bool(binding_changed(controller, batch_id)))
            job = controller.job(new_id)
            if job['status'] != 'pending' or 'launch_intent' in job:
                raise ValueError('Successor batch is not an unstarted prepared batch')
            mark_resumed(self.root, batch_id, new_id, now=self.clock(), selected=prepared.get('member_count'))
            self._append('batch_resume', 'prepared', batch_id=batch_id, successor_batch_id=new_id,
                         members=prepared.get('member_count'), configuration_sha256=job['configuration_sha256'])
        driver = self._spawn_driver(new_id, max_seconds=max_seconds or self._resume_budget(batch_id))
        return dict(state='resumed', source_batch_id=batch_id, batch_id=new_id, members=prepared.get('member_count'),
                    peer=peer, readback=readback, driver=driver, lineage=lineage(self.root, new_id))

    def _resume_budget(self, batch_id):
        journal = self.root / 'batch-drivers' / (batch_id + '.json')
        value = read_json(journal).get('max_seconds') if journal.is_file() else None
        return value if type(value) is int and 1 <= value <= 172800 else 172800

    def _seed_unpause(self, batch_id, kind='seed'):
        with self._exclusive(), self._seed_scope(kind + '-resume', batch_id, kind) as (controller, evidence):
            released = self._seed_runner(controller, kind).release_pause(batch_id, now=self.clock())
        self._append(kind + '_pause', 'released', batch_id=batch_id, released=released)
        result = self._lane_resume(kind, batch_id, 60)
        return dict(kind=kind, source_batch_id=batch_id, batch_id=batch_id, state='resumed', released=released, seed=result,
                    next_action='Keep calling ' + kind + '-resume until the ' + LANES[kind]['unit'] + ' reports completed or stopped')

    # ------------------------------------------------------------------ SeedFarming
    #
    # The raw Studio CLI keeps refusing demo_direct mutations. These tools are the
    # broker-verified demo path for the existing SeedRunner: every effect runs under
    # the terminal lock and the same fresh demo/owner/STOP/TAKE/disk/build checks as
    # batches. A seed run closes the selected MT5 and relaunches it per member, so a
    # resume between members continues only the original attempt whose start record
    # carries a fresh broker readback of this exact paired demo login and server.

    SEED_SLICE_SECONDS = 5

    def _seed_budget(self, max_seconds, kind='seed'):
        if type(max_seconds) is not int or not 1 <= max_seconds <= 3600:
            raise ValueError(LANES[kind]['title'] + ' driver budget must be 1..3600 seconds')

    def _seed_start_path(self, batch_id, kind='seed'):
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError(LANES[kind]['title'] + ' batch ID must use 1..80 letters/digits/underscore/hyphen')
        return self.state_root / LANES[kind]['starts'] / (batch_id + '.json')

    def _seed_start_record(self, batch_id, kind='seed'):
        path = self._seed_start_path(batch_id, kind)
        if not path.is_file():
            raise ValueError('No broker-verified demo ' + LANES[kind]['word'] + ' start exists for this batch; use ' + kind + '-start')
        record = read_json(path)
        if (record.get('batch_id') != batch_id or record.get('installation_sha256') != sha(self.install)
                or record.get('account') != self._paired_account()
                or record.get('broker', {}).get('demo') is not True):
            raise ValueError(LANES[kind]['title'] + ' start record differs from this installation or paired demo account')
        return record

    def _active_seed(self):
        slot = self.root / 'seed-active.json'
        if not slot.is_file():
            return None
        value = read_json(slot)
        return value if value.get('status') != 'released' else None

    def _seed_unoccupied(self, kind='seed'):
        if self._native_active_batches():
            raise ValueError('An ordinary native batch is active; ' + LANES[kind]['word'] + ' work waits for it to finish')
        for worker in (self.state_root / 'workers').glob('*.json'):
            if self._worker_alive(read_json(worker)):
                raise ValueError('A live demo batch driver owns this terminal; ' + LANES[kind]['word'] + ' work waits')

    def _seed_runner(self, controller, kind='seed'):
        if kind == 'catchup':
            from studio_catchup import CatchupRunner
            return CatchupRunner(controller, process=self.process, clock=self.clock, sleep=self.sleep)
        from studio_seed import SeedRunner
        return SeedRunner(controller, process=self.process, clock=self.clock, sleep=self.sleep)

    @contextmanager
    def _seed_scope(self, operation_name, batch_id, kind='seed'):
        """Policy scope for observing, cancelling or continuing a demo seed batch.

        While MT5 runs, a fresh broker readback is taken. A batch still 'prepared'
        has had no native effect, so it needs no start record for status, cancel
        or report; any batch that has left 'prepared' must have its start record.
        """
        lane = LANES[kind]
        record = self._seed_start_record(batch_id, kind) if self._seed_start_path(batch_id, kind).exists() else None
        if record is None and not (self.root / lane['folder'] / batch_id / 'state.json').is_file():
            raise ValueError('Unknown ' + lane['word'] + ' batch; use ' + kind + '-prepare')
        if self.process.inspect() is not None:
            # Without a start record only a provably never-started batch is managed,
            # and only under this fresh broker readback; nothing offline is granted.
            if record is None and not self._seed_never_started(batch_id, kind):
                raise ValueError(lane['title'] + ' batch has native effects but no broker-verified demo start record')
            with self._studio(operation_name, idle=False, owner_required=False,
                              job_id=batch_id) as (controller, broker):
                yield controller, dict(broker=broker, start=record)
            return
        if record is None:
            raise ValueError('No broker-verified demo ' + lane['word'] + ' start exists for this batch; '
                             'open the selected MT5 for a fresh demo check, or use ' + kind + '-start')
        # MT5 is closed between seed members, so no live broker can answer now.
        # Nothing is inferred from the session: the retained start readback must
        # match this installation, registered EA and exact paired demo account.
        if self.session.get('authority_kind') != 'demo_direct':
            raise ValueError('Install and verify the selected V1.49 build before demo Studio control')
        if digest(self.binary) != self.install['ea_sha256']:
            raise ValueError('Installed demo EA hash changed')
        from goat_studio import Controller
        from studio_research_authority import demo_agent_scope, operation
        with operation(operation_name), demo_agent_scope(
                root=self.root, installation_sha256=sha(self.install),
                account=dict(record['account']), job_id=batch_id):
            controller = Controller(self.installation_path).open()
            try:
                yield controller, dict(broker=None, start=record)
            finally:
                controller.store.close()

    def _seed_stop_reason(self):
        reason = self._stop_requested()
        if reason:
            return reason
        try:
            self._space()
        except ValueError:
            return 'low_disk'
        return None

    def _seed_drive(self, runner, batch_id, max_seconds, *, initial, kind='seed'):
        deadline = self.clock() + max_seconds
        while True:
            reason = self._seed_stop_reason()
            if reason:
                result = runner.cancel(batch_id)
                self._append(kind + '_drive', 'stopped', batch_id=batch_id, reason=reason,
                             status=result['status'], stop_verified=result.get('stop_verified'))
                return dict(result, stopped_by=reason)
            remaining = deadline - self.clock()
            if remaining < 1:
                break
            slice_seconds = int(min(self.SEED_SLICE_SECONDS, remaining))
            result = (runner.start if initial else runner.resume)(batch_id, max_seconds=slice_seconds)
            initial = False
            self._append(kind + '_drive', 'slice', batch_id=batch_id, status=result['status'])
            if result['status'] in ('completed', 'stopped', 'reconcile_required') or result.get('paused'):
                return result
        return dict(runner.status(batch_id), driver_budget_exhausted=True,
                    next_action=kind + '-resume continues the retained original attempt; no retry')

    def _lane_validate(self, kind, plan):
        """Non-executing plan and SET validation: no file, process, broker or terminal effect."""
        from goat_studio import Controller
        plan_path = Path(plan).resolve()
        value = read_json(plan_path)
        if kind == 'catchup':
            from studio_catchup import CatchupRunner as Runner
        else:
            from studio_seed import SeedRunner as Runner
        controller = Controller(self.installation_path)   # installation and input contracts only; no store
        controller.session = self.session
        result = Runner(controller, process=_NoTerminal()).validate(value)
        self._append(kind + '_validate', 'checked', plan=str(plan_path), plan_sha256=digest(plan_path),
                     job_count=result.get('job_count', result.get('member_count')))
        return result

    def seed_validate(self, plan):
        return self._lane_validate('seed', plan)

    def _lane_prepare(self, kind, batch_id, plan):
        plan_path = Path(plan).resolve()
        value = read_json(plan_path)
        self._seed_start_path(batch_id, kind)
        with self._exclusive(), self._studio(kind + '-prepare', idle=True, job_id=batch_id) as (controller, broker):
            self._seed_unoccupied(kind)
            self._append(kind + '_prepare', 'intent', batch_id=batch_id, plan=str(plan_path),
                         plan_sha256=digest(plan_path), broker=broker)
            result = self._seed_runner(controller, kind).prepare(batch_id, value)
            self._append(kind + '_prepare', 'verified', batch_id=batch_id, status=result['status'],
                         manifest_sha256=result.get('manifest_sha256'))
            return result

    def seed_prepare(self, batch_id, plan):
        return self._lane_prepare('seed', batch_id, plan)

    def _seed_left_prepared(self, batch_id, kind='seed'):
        """Read-only: has this runner batch moved past 'prepared' (any native effect recorded)?"""
        state = self.root / LANES[kind]['folder'] / batch_id / 'state.json'
        return state.is_file() and read_json(state).get('status') != 'prepared'

    def _seed_never_started(self, batch_id, kind='seed'):
        """Read-only proof that a seed (or catch-up) batch never had a native effect.

        True only for a batch still 'prepared', or 'stopped' by cancelling it before
        any start: the manifest hash matches, no generation, preflight or process was
        ever recorded, every member is unattempted with no result, the seed slot never
        named this batch, and no runner output exists for any member.
        """
        root = self.root / LANES[kind]['folder'] / batch_id
        state_path, manifest_path = root / 'state.json', root / 'manifest.json'
        if not state_path.is_file() or not manifest_path.is_file():
            return False
        state, manifest = read_json(state_path), read_json(manifest_path)
        if state.get('manifest_sha256') != digest(manifest_path) or state.get('batch_id') != batch_id:
            return False
        member_status = {'prepared': 'pending', 'stopped': 'cancelled'}.get(state.get('status'))
        if member_status is None or state.get('generation') is not None:
            return False
        if any(key in state for key in ('preflight', 'initial_process', 'error')):
            return False
        members, specs = state.get('members'), manifest.get('members')
        if not isinstance(members, list) or not isinstance(specs, list) or len(members) != len(specs):
            return False
        for item in members:
            if (item.get('status') != member_status or item.get('attempts') != 0 or item.get('result') is not None
                    or any(key in item for key in ('process', 'started_unix', 'finished_unix', 'error'))):
                return False
        slot = self.root / 'seed-active.json'
        if slot.is_file() and read_json(slot).get('batch_id') == batch_id:
            return False
        if kind == 'catchup':
            attempts = Path(self.install['common_files_root']) / 'TEMP' / 'SQ'
            if any(any((attempts / spec['attempt_token']).glob('*.set')) for spec in specs):
                return False
            return True
        outputs = Path(self.install['common_files_root']) / 'GOAT/SeedFarmingXML'
        if outputs.is_dir() and any(any(outputs.glob(spec['output_base'] + '_N*.xml')) for spec in specs):
            return False
        return True

    def _lane_start(self, kind, batch_id, max_seconds):
        lane = LANES[kind]
        self._seed_budget(max_seconds, kind)
        path = self._seed_start_path(batch_id, kind)
        if path.exists() and self._seed_left_prepared(batch_id, kind):
            raise ValueError(lane['title'] + ' batch already started; use ' + kind + '-resume for the original attempt')
        with self._exclusive(), self._studio(kind + '-start', idle=True, job_id=batch_id) as (controller, broker):
            self._seed_unoccupied(kind)
            runner = self._seed_runner(controller, kind)
            current = runner.status(batch_id)
            if path.exists():
                # Only an attempt that never left 'prepared' may re-run its start, and only
                # under this fresh broker check; anything later is the original attempt.
                record = self._seed_start_record(batch_id, kind)
                if current['status'] != 'prepared' or record['manifest_sha256'] != current['manifest_sha256']:
                    raise ValueError(lane['title'] + ' batch already started; use ' + kind + '-resume for the original attempt')
                self._append(kind + '_start', 'start_record_reused', batch_id=batch_id, broker=broker)
            else:
                if current['status'] != 'prepared':
                    raise ValueError('Only a prepared ' + lane['word'] + ' batch can start')
                record = dict(schema_version=1, batch_id=batch_id, manifest_sha256=current['manifest_sha256'],
                              installation_sha256=sha(self.install), account=self._paired_account(),
                              generation=controller.state()['generation'], broker=broker,
                              started_at=datetime.now(timezone.utc).isoformat())
                path.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive create: the start record is written once, before any effect.
                with path.open('x', encoding='utf-8', newline='\n') as output:
                    json.dump(record, output, sort_keys=True, separators=(',', ':'))
                    output.write('\n'); output.flush(); os.fsync(output.fileno())
                self._append(kind + '_start', 'start_recorded', batch_id=batch_id,
                             manifest_sha256=record['manifest_sha256'], broker=broker)
            return self._reopen_after_lane(kind, batch_id,
                                           self._seed_drive(runner, batch_id, max_seconds, initial=True, kind=kind))

    def _reopen_after_lane(self, kind, batch_id, result):
        """MT5 stays closed after the last seed or catch-up member: reopen it on the saved GOAT Studio profile.

        Only for a batch that ended by itself (completed, or stopped by a member outcome, not by
        owner STOP, a pause or a human), with the selected MT5 closed and the terminal slot released.
        The launch is the monitor-only INI (Algo off, no tester) and the full owner readback runs.
        A failure never changes the batch result; it is reported with the one-step fix.
        """
        if (not isinstance(result, dict) or result.get('status') not in ('completed', 'stopped')
                or result.get('stopped_by') or result.get('paused') or result.get('generation') is None):
            return result
        try:
            if self.process.inspect() is not None:
                return result
            slot = self.root / 'seed-active.json'
            if slot.is_file() and read_json(slot).get('status') == 'active':
                return result
            config = self._validate_monitor_config()
            physical = digest(self.binary)
            if physical != self.install['ea_sha256']:
                raise ValueError('Installed EA differs from registered receipt; retry install-build')
            self._append(kind + '_reopen', 'intent', batch_id=batch_id, monitor_config=str(config))
            reopened = self._launch_terminal(config, physical)
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            self._append(kind + '_reopen', 'unconfirmed', batch_id=batch_id, error=str(exc))
            return dict(result, monitor_reopen=dict(status='unconfirmed', error=str(exc)),
                        next_action='MT5 did not reopen by itself. Run demo launch-terminal: it reopens MT5 on the '
                                    'saved GOAT Studio profile and re-reads the build.')
        self._append(kind + '_reopen', 'verified', batch_id=batch_id, process=reopened.get('terminal'))
        return dict(result, monitor_reopen=dict(status='verified', process=reopened.get('terminal')),
                    next_action='MT5 was reopened on the GOAT Studio profile and the build was re-read; '
                                'the next batch can start.')

    def seed_start(self, batch_id, max_seconds):
        return self._lane_start('seed', batch_id, max_seconds)

    def _lane_resume(self, kind, batch_id, max_seconds):
        lane = LANES[kind]
        self._seed_budget(max_seconds, kind)
        with self._exclusive(), self._seed_scope(kind + '-resume', batch_id, kind) as (controller, evidence):
            runner = self._seed_runner(controller, kind)
            current = runner.status(batch_id)
            if current['status'] == 'prepared':
                raise ValueError(lane['title'] + ' batch has no native effect yet; use ' + kind + '-start with a fresh broker check')
            if evidence['start'] is None:
                raise ValueError(lane['title'] + ' batch was cancelled before any native effect; prepare a new batch ID')
            if current['manifest_sha256'] != evidence['start']['manifest_sha256']:
                raise ValueError(lane['title'] + ' state differs from its broker-verified start record')
            self._append(kind + '_resume', 'continue', batch_id=batch_id, status=current['status'],
                         broker=evidence['broker'], retained_start=evidence['broker'] is None)
            # A batch that ended while MT5 stayed closed (including a member reconciled from its
            # retained output) also reopens here: seed-resume is the one-step recovery.
            return self._reopen_after_lane(kind, batch_id,
                                           self._seed_drive(runner, batch_id, max_seconds, initial=False, kind=kind))

    def seed_resume(self, batch_id, max_seconds):
        return self._lane_resume('seed', batch_id, max_seconds)

    def _lane_status(self, kind, batch_id):
        with self._seed_scope(kind + '-status', batch_id, kind) as (controller, evidence):
            return dict(broker=evidence['broker'], retained_start=evidence['broker'] is None,
                        **{'seed' if kind == 'seed' else 'catchup': self._seed_runner(controller, kind).status(batch_id)})

    def seed_status(self, batch_id):
        return self._lane_status('seed', batch_id)

    def _lane_cancel(self, kind, batch_id):
        with self._exclusive(), self._seed_scope(kind + '-cancel', batch_id, kind) as (controller, evidence):
            result = self._seed_runner(controller, kind).cancel(batch_id)
            self._append(kind + '_cancel', 'requested', batch_id=batch_id, status=result['status'],
                         stop_verified=result.get('stop_verified'))
            return result

    def seed_cancel(self, batch_id):
        return self._lane_cancel('seed', batch_id)

    def _lane_report(self, kind, batch_id):
        with self._seed_scope(kind + '-report', batch_id, kind) as (controller, evidence):
            result = self._seed_runner(controller, kind).report(batch_id)
            self._append(kind + '_report', 'written', batch_id=batch_id, status=result['status'],
                         report_sha256=result.get('report_sha256'))
            return result

    def seed_report(self, batch_id):
        return self._lane_report('seed', batch_id)

    def _lane_reconcile(self, kind, batch_id):
        """Settle a reconcile_required member from its own verified output once MT5 is proven idle NOW.

        With MT5 open, the broker readback of _seed_scope and a fresh inventory must name the same
        process; the runner then proves no MT5 runs a member (command lines, idle monitor). Sends
        no close or launch and never synthesises a result (studio_seed.reconcile).
        """
        with self._exclusive(), self._seed_scope(kind + '-reconcile', batch_id, kind) as (controller, evidence):
            broker = evidence['broker']
            if broker is not None and broker.get('process') != self.process.inspect():
                raise ValueError('The selected MT5 changed during the broker check; nothing was settled')
            result = self._seed_runner(controller, kind).reconcile(batch_id)
            self._append(kind + '_reconcile', 'settled' if result.get('settled') else 'unsettled', batch_id=batch_id,
                         status=result['status'], reasons=result.get('reasons'), broker=broker)
            return result

    def seed_reconcile(self, batch_id):
        return self._lane_reconcile('seed', batch_id)

    def catchup_reconcile(self, catchup_id):
        return self._lane_reconcile('catchup', catchup_id)

    # ------------------------------------------------------------------ OOS catch-up
    #
    # One non-optimized pass per stale exported SET, from its original start to a
    # new evidence end (studio_catchup). Same lane as seeds: MT5 closes and
    # relaunches per member, under the same broker-verified start record rules.

    def catchup_validate(self, plan):
        return self._lane_validate('catchup', plan)

    def catchup_prepare(self, catchup_id, plan):
        return self._lane_prepare('catchup', catchup_id, plan)

    def catchup_start(self, catchup_id, max_seconds):
        return self._lane_start('catchup', catchup_id, max_seconds)

    def catchup_resume(self, catchup_id, max_seconds):
        return self._lane_resume('catchup', catchup_id, max_seconds)

    def catchup_status(self, catchup_id):
        return self._lane_status('catchup', catchup_id)

    def catchup_cancel(self, catchup_id):
        return self._lane_cancel('catchup', catchup_id)

    def catchup_report(self, catchup_id):
        return self._lane_report('catchup', catchup_id)

    def evidence_scan(self, sources, value='auto', *, broker_clock=None, include_below_threshold=False):
        """Read-only: every kept export under ``sources`` against one evidence end; no terminal effect."""
        from studio_catchup import evidence_scan
        return evidence_scan(sources, value=value, broker_clock=broker_clock, controller_root=self.root,
                             include_below_threshold=include_below_threshold)

    def evidence_end(self, value='auto', *, broker_clock=None):
        """Read-only: resolve AUTO / an explicit evidence end, and what this EA build's batch exports end at."""
        from studio_evidence_end import DEFAULT_CLOCK, ea_capability, legacy_end, resolve
        clock = broker_clock or DEFAULT_CLOCK
        return dict(resolve(value, clock=clock), batch_exports_now=legacy_end(clock=clock),
                    ea_evidence_end_setting=ea_capability(self.install, self.local / 'ui-observation.json'))

    def seed_promote(self, batch_id, candidate, name, neighborhood=1, member=None):
        """Freeze one verified seed candidate as fixed + robustness SETs; local files only, same scope as seed-report."""
        with self._seed_scope('seed-report', batch_id) as (controller, evidence):
            from studio_seed_promote import promote
            result = promote(controller, batch_id, candidate, name, neighborhood=neighborhood, member=member,
                             runner=self._seed_runner(controller))
            # `written` for a new promotion, `retained` when a repeat returns the existing receipt.
            self._append('seed_promote', result['status'], batch_id=batch_id, candidate_sha256=candidate,
                         robustness_sha256=result['robustness_set']['sha256'])
            return result

    def _slot_kind(self, slot):
        """Which runner holds the shared terminal slot: the catch-up whose manifest the slot names, else seed."""
        batch_id = slot.get('batch_id')
        state = self.root / LANES['catchup']['folder'] / str(batch_id) / 'state.json'
        if isinstance(batch_id, str) and state.is_file() and read_json(state).get('manifest_sha256') == slot.get('manifest_sha256'):
            return 'catchup'
        return 'seed'

    def _stop_seed(self, seed):
        batch_id = seed.get('batch_id')
        kind = self._slot_kind(seed)
        if kind != 'seed':
            try:
                result = self._lane_cancel(kind, batch_id)
            except ValueError as exc:
                if 'Another demo agent operation owns this terminal' in str(exc):
                    return dict(status=kind + '_stop_requested', batch_id=batch_id, owner_stop=True,
                                reason='Live catch-up driver settles STOP within one slice')
                return dict(status='stop_unconfirmed', batch_id=batch_id, owner_stop=True, reason=str(exc))
            return dict(status=kind + '_' + result['status'], batch_id=batch_id, owner_stop=True,
                        stop_verified=result.get('stop_verified'))
        try:
            result = self.seed_cancel(batch_id)
        except ValueError as exc:
            if 'Another demo agent operation owns this terminal' in str(exc):
                # A live seed driver holds the lock; it sees STOP before its next slice.
                return dict(status='seed_stop_requested', batch_id=batch_id, owner_stop=True,
                            reason='Live seed driver settles STOP within one slice')
            return dict(status='stop_unconfirmed', batch_id=batch_id, owner_stop=True, reason=str(exc))
        return dict(status='seed_' + result['status'], batch_id=batch_id, owner_stop=True,
                    stop_verified=result.get('stop_verified'))


class _NoTerminal:
    """Process stand-in for validation: any terminal effect is a defect, not a fallback."""
    def inspect(self):
        raise ValueError('Seed validation never inspects the terminal')
    def start(self, config):
        raise ValueError('Seed validation never starts the terminal')
    def close(self, identity):
        raise ValueError('Seed validation never closes the terminal')



def _gate_command(args):
    import studio_gate_calibration as gates
    if args.command == 'gate-recommend':
        if args.output is not None and Path(args.output).exists():
            raise ValueError('Recommendation output already exists; choose a new path')
        runs = [run.strip() for run in args.runs.split(',') if run.strip()] if args.runs else None
        result = gates.gate_recommend(common_root=args.common_root, runs=runs, target=args.target,
                                      min_survival=args.min_survival, min_sets=args.min_sets,
                                      min_members=args.min_members, min_trades=args.min_trades,
                                      min_clusters=args.min_clusters, cluster=args.cluster,
                                      verdicts=args.verdicts, curves=args.curves)
        if args.output is not None:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, sort_keys=True, indent=1, default=str)
                stream.write('\n')
            result = dict(result, output=str(output))
        return result
    recommendation = read_json(args.recommendation)
    recommendation = recommendation.get('result', recommendation)
    generated = args.generated_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return gates.stamp_plan(args.plan, recommendation, args.output, generated_at=generated)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status'); commands.add_parser('preflight')
    commands.add_parser('credential-recovery-preflight',
                        help='Read-only: whether an app update may replace an EA that cannot report (lost GOAT sign-in), '
                             'proven from MT5 itself on an allowlisted demo server')
    commands.add_parser('disk-status')
    cancel_pending = commands.add_parser('cancel-pending')
    cancel_pending.add_argument('--batch-id', required=True)
    retire = commands.add_parser('retire-unactivated',
                                 help='Settle a start refused before MT5 was touched to cancelled; allowed under owner STOP')
    retire.add_argument('--batch-id', required=True)
    stop = commands.add_parser('stop', help='Stop: settle the active batch (or --batch-id for one unstarted batch) to a verified terminal state')
    stop.add_argument('--monitor-config', type=Path, help='Exact monitor-only INI for cancellation recovery after MT5 exits; STOP remains set')
    stop.add_argument('--batch-id', help='Cancel this pending or reserved-not-started batch without setting owner STOP')
    compact = commands.add_parser('compact-evidence', help='Preview, then --apply: move finished in-row evidence history to verified logs')
    compact.add_argument('--apply', action='store_true')
    receipts = commands.add_parser('compact-receipts',
                                   help='Preview, then --apply: archive legacy full-queue receipts and keep only their queue digest')
    receipts.add_argument('--apply', action='store_true')
    begin =commands.add_parser('start', help='Start any prepared batch under the bounded driver')
    begin.add_argument('--batch-id', required=True)
    begin.add_argument('--max-seconds', type=int)
    onward = commands.add_parser('continue', help='Continue a stopped, paused or finished batch as a successor and start it')
    onward.add_argument('--batch-id', required=True)
    onward.add_argument('--new-batch-id')
    onward.add_argument('--max-seconds', type=int)
    onward.add_argument('--clear-stop', action='store_true')
    onward.add_argument('--include-failed', action='store_true')
    onward.add_argument('--include-no-edge', action='store_true')
    commands.add_parser('clear-stop')
    orphan = commands.add_parser('recover-orphan')
    orphan.add_argument('--review-id', help='Observe this retained recovery only; never resend')
    launch = commands.add_parser('launch-terminal', help='Reopen MT5 on the saved GOAT Studio monitor profile, '
                                 'or re-read the build on a running terminal')
    launch.add_argument('--monitor-config', type=Path,
                        help='Monitor-only INI; default: the saved GOAT Studio profile (monitor-profile.json)')
    install = commands.add_parser('install-build')
    install.add_argument('--candidate', type=Path, required=True)
    install.add_argument('--sha256', required=True)
    install.add_argument('--monitor-config', type=Path, required=True)
    install.add_argument('--require-running', action='store_true')
    install.add_argument('--linked-login')
    install.add_argument('--bundle-version')
    install.add_argument('--agent-guide-path', type=Path)
    install.add_argument('--enter-demo-lane', action='store_true',
                         help='Owner only: also move this session into the owner demo lane (demo_direct). '
                              'Without it the session keeps its lane; an app update never passes it')
    install.add_argument('--credential-recovery', action='store_true',
                         help='Desktop app only, after credential-recovery-preflight and its own linked/consent checks: '
                              'the EA cannot report (lost GOAT sign-in), so the owner checks accept its last observation '
                              'at any age; needs --require-running and --linked-login')
    restore = commands.add_parser('restore-lane', help='Preview, then --apply: return a customer session an app update '
                                  'moved into the owner demo lane back to native_human_control; nothing native runs')
    restore.add_argument('--apply', action='store_true')
    prepared = commands.add_parser('prepare-batch')
    prepared.add_argument('--batch-id', required=True)
    prepared.add_argument('--plan', type=Path, required=True)
    run = commands.add_parser('run-batch')
    run.add_argument('--batch-id', required=True)
    run.add_argument('--max-seconds', type=int, required=True)
    resume = commands.add_parser('resume-batch')
    resume.add_argument('--batch-id', required=True)
    worker = commands.add_parser('_drive-batch')
    worker.add_argument('--batch-id', required=True)
    worker.add_argument('--nonce', required=True)
    worker.add_argument('--max-seconds', type=int)
    worker.add_argument('--pause-seconds', type=int)
    commands.add_parser('research-status', help='Read-only lane status: activity, pace/ETA, pause, driver, disk, monitor')
    pause = commands.add_parser('batch-pause', help='Pause a running batch or seed hunt at its next safe point')
    pause.add_argument('--batch-id', required=True)
    pause.add_argument('--immediate', action='store_true', help='Skip the member-start wait; the monitor must still be reporting')
    resumed = commands.add_parser('batch-resume', help='Continue a paused batch as a successor batch')
    resumed.add_argument('--batch-id', required=True)
    resumed.add_argument('--new-batch-id')
    resumed.add_argument('--resume-token')
    resumed.add_argument('--max-seconds', type=int)
    resumed.add_argument('--clear-stop', action='store_true', help='Lift an owner STOP written by GOAT before resuming')
    resumed.add_argument('--include-failed', action='store_true')
    resumed.add_argument('--include-no-edge', action='store_true',
                         help='Also re-run members tested with no profitable settings (results, not failures)')
    batch = commands.add_parser('batch-status')
    batch.add_argument('--batch-id', required=True)
    driver = commands.add_parser('batch-driver-status')
    driver.add_argument('--batch-id', required=True)
    seed_check = commands.add_parser('seed-validate', help='Non-executing seed plan/SET validation')
    seed_check.add_argument('--plan', type=Path, required=True)
    seed_prep = commands.add_parser('seed-prepare')
    seed_prep.add_argument('--batch-id', required=True)
    seed_prep.add_argument('--plan', type=Path, required=True)
    for name in ('seed-start', 'seed-resume'):
        seed_drive = commands.add_parser(name)
        seed_drive.add_argument('--batch-id', required=True)
        seed_drive.add_argument('--max-seconds', type=int, default=60)
    for name in ('seed-status', 'seed-cancel', 'seed-report', 'seed-reconcile'):
        commands.add_parser(name).add_argument('--batch-id', required=True)
    seed_promote = commands.add_parser('seed-promote', help='Freeze one seed candidate as fixed + robustness SETs')
    seed_promote.add_argument('--batch-id', required=True)
    seed_promote.add_argument('--candidate', required=True)
    seed_promote.add_argument('--name', required=True)
    seed_promote.add_argument('--neighborhood', type=int, default=1, help='Robustness ladder steps either side, 1..5 (default 1)')
    seed_promote.add_argument('--member')
    gate = commands.add_parser('gate-recommend', help='Read-only: recommend qualification gates for a new run from our own export evidence')
    gate.add_argument('--target', choices=('forward', 'post', 'held_up'), default='forward',
                      help='held_up (catch-up verdicts) is the only actionable target; forward and post are diagnostics')
    gate.add_argument('--min-survival', type=float, default=0.6, help='Required share of kept sets that survive (lower 95%% bound by default)')
    gate.add_argument('--min-sets', type=int, default=20, help='Fewest sets a gate must keep')
    gate.add_argument('--min-members', type=int, default=8, help='Fewest distinct optimization members a gate must keep')
    gate.add_argument('--min-trades', type=int, default=5, help='Fewest trades in the target window for a set to be judged (forward/post)')
    gate.add_argument('--min-clusters', type=int, default=4, help='Fewest independent runs (or periods) for any recommendation')
    gate.add_argument('--cluster', choices=('run', 'period'), default='run', help='Independent unit for bootstraps and leave-one-out')
    gate.add_argument('--runs', help='Comma-separated run folders (R...); default: every run with sequence exports')
    gate.add_argument('--common-root', type=Path, help='GOAT Common Files folder; default %%APPDATA%%\\MetaQuotes\\Terminal\\Common\\Files\\GOAT')
    gate.add_argument('--verdicts', type=Path, help='Catch-up verdict JSON/JSONL file or folder (comparable goat-catchup-verdict-v2 only)')
    gate.add_argument('--curves', action='store_true', help='Include every threshold point, not only the qualifying ones')
    gate.add_argument('--output', type=Path, help='Also write the recommendation JSON to this new file')
    stamp = commands.add_parser('gate-stamp', help='Write a new batch plan that only tightens to a held_up recommendation, plus a <plan>.gates.json stamp')
    stamp.add_argument('--plan', type=Path, required=True)
    stamp.add_argument('--recommendation', type=Path, required=True, help='JSON written by gate-recommend --output')
    stamp.add_argument('--output', type=Path, required=True, help='New plan path; never the source plan')
    stamp.add_argument('--generated-at', help='UTC time to stamp (YYYY-MM-DDTHH:MM:SSZ); default now')
    end = commands.add_parser('evidence-end', help='Read-only: resolve AUTO (latest closed Friday) or an explicit evidence end')
    end.add_argument('--value', default='auto')
    end.add_argument('--broker-clock')
    scan = commands.add_parser('evidence-scan', help='Read-only: kept exports and their evidence ends against one target')
    scan.add_argument('--source', type=Path, action='append', required=True, help='Run, deploy or member folder, or a .set; repeatable')
    scan.add_argument('--evidence-end', default='auto')
    scan.add_argument('--broker-clock')
    scan.add_argument('--include-below-threshold', action='store_true')
    commands.add_parser('catchup-validate', help='Non-executing catch-up plan preview').add_argument('--plan', type=Path, required=True)
    catchup_prep = commands.add_parser('catchup-prepare', help='Freeze one single-pass re-test per stale export; no launch')
    catchup_prep.add_argument('--catchup-id', required=True)
    catchup_prep.add_argument('--plan', type=Path, required=True)
    for name in ('catchup-start', 'catchup-resume'):
        catchup_drive = commands.add_parser(name)
        catchup_drive.add_argument('--catchup-id', required=True)
        catchup_drive.add_argument('--max-seconds', type=int, default=60)
    for name in ('catchup-status', 'catchup-cancel', 'catchup-report', 'catchup-reconcile'):
        commands.add_parser(name).add_argument('--catchup-id', required=True)
    args = parser.parse_args(argv)
    if args.command in ('gate-recommend', 'gate-stamp'):
        # Evidence-only commands: no terminal, session or controller state is read or written.
        try:
            result = _gate_command(args)
            print(json.dumps(dict(ok=True, result=result), sort_keys=True, default=str))
            return 0
        except Exception as exc:
            code = 'REFUSED' if isinstance(exc, ValueError) else 'IO_ERROR' if isinstance(exc, OSError) else 'INTERNAL_ERROR'
            print(json.dumps(dict(ok=False, code=code, error=str(exc)), sort_keys=True), file=sys.stderr)
            return 1
    try:
        agent = DemoAgent(args.installation)
        if args.command == 'status': result = agent.status()
        elif args.command == 'preflight': result = agent.preflight()
        elif args.command == 'credential-recovery-preflight': result = agent.credential_recovery_preflight()
        elif args.command == 'disk-status': result = agent.disk_status()
        elif args.command == 'cancel-pending': result = agent.cancel_pending(args.batch_id)
        elif args.command == 'stop': result = agent.stop(args.monitor_config, args.batch_id)
        elif args.command == 'start': result = agent.start(args.batch_id, args.max_seconds)
        elif args.command == 'compact-evidence': result = agent.compact_evidence(args.apply)
        elif args.command == 'compact-receipts': result = agent.compact_receipts(args.apply)
        elif args.command == 'continue': result = agent.continue_batch(args.batch_id, new_batch_id=args.new_batch_id,
            max_seconds=args.max_seconds, clear_stop=args.clear_stop, include_failed=args.include_failed,
            include_no_edge=args.include_no_edge)
        elif args.command == 'retire-unactivated': result = agent.retire_unactivated(args.batch_id)
        elif args.command == 'clear-stop': result = agent.clear_stop()
        elif args.command == 'recover-orphan': result = agent.recover_orphan(args.review_id)
        elif args.command == 'launch-terminal': result = agent.launch_terminal(args.monitor_config)
        elif args.command == 'install-build': result = agent.install_build(args.candidate, args.sha256, args.monitor_config,
            require_running=args.require_running,linked_login=args.linked_login,
            bundle_version=args.bundle_version,agent_guide_path=args.agent_guide_path,
            enter_demo_lane=args.enter_demo_lane,credential_recovery=args.credential_recovery)
        elif args.command == 'restore-lane': result = agent.restore_lane(args.apply)
        elif args.command == 'prepare-batch': result = agent.prepare_batch(args.batch_id, args.plan)
        elif args.command == 'run-batch': result = agent.run_batch(args.batch_id, args.max_seconds)
        elif args.command == 'resume-batch': result = agent.resume_batch(args.batch_id)
        elif args.command == '_drive-batch': result = agent._drive_batch(args.batch_id, args.nonce, args.max_seconds, args.pause_seconds)
        elif args.command == 'research-status': result = agent.research_status()
        elif args.command == 'batch-pause': result = agent.batch_pause(args.batch_id, immediate=args.immediate)
        elif args.command == 'batch-resume': result = agent.batch_resume(args.batch_id, new_batch_id=args.new_batch_id,
            resume_token=args.resume_token, max_seconds=args.max_seconds, clear_stop=args.clear_stop,
            include_failed=args.include_failed, include_no_edge=args.include_no_edge)
        elif args.command == 'batch-status': result = agent.batch_status(args.batch_id)
        elif args.command == 'batch-driver-status': result = agent.batch_driver_status(args.batch_id)
        elif args.command == 'seed-validate': result = agent.seed_validate(args.plan)
        elif args.command == 'seed-prepare': result = agent.seed_prepare(args.batch_id, args.plan)
        elif args.command == 'seed-start': result = agent.seed_start(args.batch_id, args.max_seconds)
        elif args.command == 'seed-resume': result = agent.seed_resume(args.batch_id, args.max_seconds)
        elif args.command == 'seed-status': result = agent.seed_status(args.batch_id)
        elif args.command == 'seed-cancel': result = agent.seed_cancel(args.batch_id)
        elif args.command == 'seed-report': result = agent.seed_report(args.batch_id)
        elif args.command == 'seed-reconcile': result = agent.seed_reconcile(args.batch_id)
        elif args.command == 'seed-promote': result = agent.seed_promote(args.batch_id, args.candidate, args.name, args.neighborhood, args.member)
        elif args.command == 'evidence-end': result = agent.evidence_end(args.value, broker_clock=args.broker_clock)
        elif args.command == 'evidence-scan': result = agent.evidence_scan([str(p) for p in args.source], args.evidence_end,
            broker_clock=args.broker_clock, include_below_threshold=args.include_below_threshold)
        elif args.command == 'catchup-validate': result = agent.catchup_validate(args.plan)
        elif args.command == 'catchup-prepare': result = agent.catchup_prepare(args.catchup_id, args.plan)
        elif args.command == 'catchup-start': result = agent.catchup_start(args.catchup_id, args.max_seconds)
        elif args.command == 'catchup-resume': result = agent.catchup_resume(args.catchup_id, args.max_seconds)
        elif args.command == 'catchup-status': result = agent.catchup_status(args.catchup_id)
        elif args.command == 'catchup-cancel': result = agent.catchup_cancel(args.catchup_id)
        elif args.command == 'catchup-reconcile': result = agent.catchup_reconcile(args.catchup_id)
        elif args.command == 'catchup-report': result = agent.catchup_report(args.catchup_id)
        if args.command == 'stop' and result.get('status') == 'stop_unconfirmed':
            print(json.dumps(dict(ok=False, code='STOP_UNCONFIRMED', result=result),
                             sort_keys=True, default=str), file=sys.stderr)
            return 2
        # Held-out lock (goatai#2221 §4.3): a reply is unchanged unless a lock binds part of it.
        from studio_heldout_guard import guard_output
        result = guard_output(agent.install, result, root=agent.root)
        print(json.dumps(dict(ok=True, result=result), sort_keys=True, default=str))
        return 0
    except Exception as exc:
        code = 'REFUSED' if isinstance(exc, ValueError) else 'IO_ERROR' if isinstance(exc, OSError) else 'INTERNAL_ERROR'
        error = dict(ok=False, code=code, error=str(exc))
        if isinstance(exc, FeedbackUnavailable):
            # The one refusal the desktop may answer with credential recovery; `code` stays REFUSED.
            error.update(reason=FeedbackUnavailable.reason)
        from studio_heldout import HeldOutRefused
        if isinstance(exc, HeldOutRefused):
            error.update(code=exc.code, plain=exc.plain, locked_windows=exc.locked_windows)
        print(json.dumps(error, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
