"""Small demo-only MT5 agent surface. Never submits trades or enables Algo Trading.

The legacy Studio ledger remains readable, but demo operations use a separate
terminal lock and action log. A broker-reported demo account is required before
every operation that can change the selected terminal or its files.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import sys
import time

from campaign_ledger import sha
from studio_installation import load_installation
from studio_monitor_probe import tester_state
from studio_native_request import ini_sections
from studio_seed_process import WindowsSeedProcess


BANKER_LOGIN = '3000082754'
MIN_FREE_BYTES = 5 * 1024 ** 3


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
    def __init__(self, installation, *, process=None, mt5=None, clock=time.time):
        self.installation_path = Path(installation).resolve()
        self.install = read_json(installation)
        self.root = Path(self.install['controller_state_root'])
        self.session = read_json(self.root / 'session.json')
        self.local = Path(self.install['terminal_data_root']) / 'MQL5/Files/GOATStudio'
        self.state_root = self.root / 'demo-agent'
        self.process = process or WindowsSeedProcess(self)
        self.mt5 = mt5
        self.clock = clock
        self.binary = Path(self.install['terminal_data_root']) / 'MQL5/Experts' / self.install['ea_relative_path'].replace('\\', '/')

    def _append(self, operation, phase, **details):
        self.state_root.mkdir(parents=True, exist_ok=True)
        row = dict(at=datetime.now(timezone.utc).isoformat(), operation=operation, phase=phase, **details)
        with (self.state_root / 'actions.jsonl').open('a', encoding='utf-8', newline='\n') as output:
            output.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
            output.flush(); os.fsync(output.fileno())
        return row

    @contextmanager
    def _exclusive(self):
        self.state_root.mkdir(parents=True, exist_ok=True)
        with (self.state_root / 'terminal.lock').open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('Another demo agent operation owns this terminal') from exc
            try:
                yield
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def _owner_clear(self):
        if (self.state_root / 'STOP').exists():
            raise ValueError('Owner STOP is set')
        human = self.local / self.session['directory_id'] / 'human'
        for channel in ('inbox', 'processing'):
            if any((human / channel).glob('*.json')):
                raise ValueError('Pending human TAKE CONTROL')
        observation = self.local / 'ui-observation.json'
        if not observation.is_file() or self.clock() - observation.stat().st_mtime > 300:
            raise ValueError('Fresh EA owner feedback unavailable')
        ui = read_json(observation)
        if ui.get('owner') != 'agent' or ui.get('run_id', self.session['run_id']) != self.session['run_id']:
            raise ValueError('Human owns the EA or native session changed')
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

    def _broker(self, *, idle=True):
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
            if idle and (positions is None or orders is None or positions or orders):
                raise ValueError('Idle demo research requires no open positions or orders')
            if self.process.inspect() != identity:
                raise ValueError('Selected MT5 process changed during broker check')
            expected = self.session['account']
            if (account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
                    or str(account.login) != BANKER_LOGIN
                    or str(account.login) != expected['login']
                    or account.server != expected['server']
                    or not terminal.connected
                    or PureWindowsPath(terminal.path) != PureWindowsPath(self.install['terminal_executable']).parent
                    or PureWindowsPath(terminal.data_path) != PureWindowsPath(self.install['terminal_data_root'])):
                raise ValueError('Broker-reported demo and allowlisted account required')
            if terminal.trade_allowed:
                raise ValueError('Algo Trading is on; this demo research lane leaves it off')
            state = tester_state(identity['pid'], terminal.build) if idle else None
            if idle and state != 'idle':
                raise ValueError('Selected native tester is not positively idle')
            return dict(process=identity, login=str(account.login), server=account.server,
                        demo=True, connected=True, algo_trading=False, tester_state=state,
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
        batch_ready = (self.session.get('authority_kind') == 'demo_direct'
                       and physical == self.install['ea_sha256']
                       and self.session.get('installation_sha256') == sha(self.install)
                       and verified.get('ea_sha256') == physical
                       and verified.get('process') == broker['process'])
        return dict(broker=broker, owner=owner['owner'], free_bytes=space,
                    binary_sha256=physical, ready_for_install=True,
                    ready_for_batch=batch_ready)

    def disk_status(self):
        return {role:dict(path=str(path), free_bytes=shutil.disk_usage(path).free,
                          minimum_bytes=MIN_FREE_BYTES)
                for role, path in (('terminal_data', self.install['terminal_data_root']),
                                   ('common_files', self.install['common_files_root']),
                                   ('controller_state', self.root))}

    def stop(self):
        # This intentionally does not need the terminal lock: owner STOP wins
        # even while a driver holds it. The driver never starts another member.
        self.state_root.mkdir(parents=True, exist_ok=True)
        marker = self.state_root / 'STOP'
        if marker.exists():
            return dict(already_stopped=True, requested_at=marker.read_text(encoding='utf-8').strip())
        with marker.open('x', encoding='utf-8') as output:
            output.write(datetime.now(timezone.utc).isoformat() + '\n')
            output.flush(); os.fsync(output.fileno())
        return self._append('stop', 'requested')

    def _stop_requested(self):
        if (self.state_root / 'STOP').exists():
            return 'owner_stop'
        human = self.local / self.session['directory_id'] / 'human'
        if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):
            return 'human_take_control'
        return None

    def install_build(self, candidate, expected_sha256, monitor_config):
        expected_sha256 = expected_sha256.lower()
        candidate = Path(candidate).resolve(); monitor_config = Path(monitor_config).resolve()
        if (candidate.suffix.lower() != '.ex5' or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
                or digest(candidate) != expected_sha256):
            raise ValueError('Candidate SHA-256 mismatch')
        sections = ini_sections(monitor_config.read_bytes())
        profile = read_json(self.root / 'monitor-profile.json')
        if (sections.get('Experts', {}).get('Enabled') != '0'
                or sections['Experts'].get('AllowLiveTrading') != '0'
                or sections.get('StartUp', {}).get('Expert') != self.install['ea_relative_path']
                or sections['StartUp'].get('Script')
                or sections.get('Charts', {}).get('ProfileLast') != profile['profile_name']):
            raise ValueError('Monitor restart must keep Algo Trading off and exact EA path')
        with self._exclusive():
            self._owner_clear(); self._space(); native = self._broker()
            old_sha = digest(self.binary)
            if (old_sha == expected_sha256
                    and self.install['ea_sha256'] == expected_sha256
                    and self.session.get('authority_kind') == 'demo_direct'
                    and self.session.get('installation_sha256') == sha(self.install)):
                ui = read_json(self.local / 'ui-observation.json')
                verified_path = self.state_root / 'verified-build.json'
                prior = read_json(verified_path) if verified_path.is_file() else {}
                if (ui.get('loaded') is True and ui.get('owner') == 'agent'
                        and ui.get('runtime', {}).get('account_demo') is True
                        and PureWindowsPath(ui['runtime'].get('program_path', '')) == PureWindowsPath(self.binary)
                        and prior.get('ea_sha256') == expected_sha256
                        and prior.get('process') == native['process']):
                    return dict(already_installed=True, sha256=old_sha, broker=native)
            backup = self.state_root / 'backups' / (old_sha + '.ex5')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and digest(backup) != old_sha:
                raise ValueError('Existing backup has changed')
            if not backup.exists():
                with backup.open('xb') as output, self.binary.open('rb') as source:
                    shutil.copyfileobj(source, output)
                    output.flush(); os.fsync(output.fileno())
            self._append('install_build', 'before_close', old_sha256=old_sha,
                         new_sha256=expected_sha256, broker=native, backup=str(backup))
            self._owner_clear(); self._broker()
            self.process.close(native['process'])
            deadline = time.monotonic() + 30
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
            self._adopt_installed_binary(expected_sha256)
            observation = self.local / 'ui-observation.json'
            before_observation = observation.stat().st_mtime_ns if observation.exists() else 0
            self.process.start(monitor_config)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    verified = self._broker()
                    ui = read_json(observation)
                    if (digest(self.binary) == expected_sha256
                            and observation.stat().st_mtime_ns > before_observation
                            and ui.get('loaded') is True
                            and ui.get('owner') == 'agent'
                            and ui.get('runtime', {}).get('account_demo') is True
                            and PureWindowsPath(ui['runtime']['program_path']) == PureWindowsPath(self.binary)):
                        write_json(self.state_root / 'verified-build.json', dict(
                            ea_sha256=expected_sha256, process=verified['process'],
                            observed_at=datetime.now(timezone.utc).isoformat()))
                        self._append('install_build', 'verified', new_sha256=expected_sha256,
                                     broker=verified)
                        return dict(installed=True, sha256=expected_sha256, broker=verified)
                except (ValueError, KeyError, OSError):
                    time.sleep(.5)
            self._append('install_build', 'readback_failed', new_sha256=expected_sha256)
            raise ValueError('New build was copied but native demo readback failed; inspect log before retry')

    def _adopt_installed_binary(self, expected_sha256):
        """Keep local app/controller identity aligned with the physical EX5.

        The old research proof remains archived in place; demo tools use the
        broker check and owner STOP instead of treating that proof as a gate.
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
        if installed['ea_sha256'] != expected_sha256:
            installed['ea_sha256'] = expected_sha256
            installed['demo_installed_at'] = datetime.now(timezone.utc).isoformat()
            write_json(self.installation_path, installed)
        checked = load_installation(self.installation_path)
        session = read_json(self.root / 'session.json')
        if session.get('authority_kind') != 'demo_direct' or session.get('installation_sha256') != sha(checked):
            session['authority_kind'] = 'demo_direct'
            session['installation_sha256'] = sha(checked)
            write_json(self.root / 'session.json', session)
        self.install, self.session = checked, session
        self._append('install_build', 'local_identity_verified', ea_sha256=expected_sha256,
                     installation_sha256=sha(checked), session_sha256=sha(session))

    @contextmanager
    def _studio(self, operation_name, *, idle, owner_required=True):
        # The local adapter is the only entry to the demo policy. The broker
        # supplies the demo bit; the saved session cannot assert it by itself.
        if owner_required:
            self._owner_clear(); self._space()
        broker = self._broker(idle=idle)
        if self.session.get('authority_kind') != 'demo_direct':
            raise ValueError('Install and verify the selected V1.49 build before demo Studio control')
        physical = digest(self.binary)
        if physical != self.install['ea_sha256']:
            raise ValueError('Installed demo EA hash changed')
        if owner_required:
            verified_path = self.state_root / 'verified-build.json'
            verified = read_json(verified_path) if verified_path.is_file() else {}
            if (verified.get('ea_sha256') != physical
                    or verified.get('process') != broker['process']):
                raise ValueError('Selected build lacks native readback for this terminal process')
        from goat_studio import Controller
        from studio_research_authority import demo_agent_scope, operation
        with operation(operation_name), demo_agent_scope(
                root=self.root, installation_sha256=sha(self.install),
                account=dict(login=broker['login'], server=broker['server'])):
            controller = Controller(self.installation_path).open()
            try:
                yield controller, broker
            finally:
                controller.store.close()

    def prepare_batch(self, batch_id, plan):
        from studio_batch import prepare_batch
        with self._exclusive(), self._studio('prepare-batch', idle=True) as (controller, broker):
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

    def run_batch(self, batch_id, max_seconds):
        from studio_batch_driver import run
        if (self.root / 'batch-drivers' / (batch_id + '.json')).exists():
            return self.batch_driver_status(batch_id)
        with self._exclusive(), self._studio('run-batch', idle=True) as (controller, broker):
            self._append('studio_run_batch', 'intent', batch_id=batch_id,
                         max_seconds=max_seconds, broker=broker)
            result = run(controller, batch_id, max_seconds=max_seconds,
                         min_free_bytes=MIN_FREE_BYTES)
            self._append('studio_run_batch', 'returned', batch_id=batch_id,
                         status=result['status'], attempt_id=result.get('attempt_id'))
            return result

    def batch_driver_status(self, batch_id):
        from studio_batch_driver import status
        with self._studio('batch-driver-status', idle=False, owner_required=False) as (controller, broker):
            return dict(broker=broker, driver=status(controller, batch_id))

    def batch_status(self, batch_id):
        from studio_batch import batch_status
        with self._studio('batch-status', idle=False, owner_required=False) as (controller, broker):
            result = batch_status(controller, batch_id)
            return dict(broker=broker, studio=result)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status'); commands.add_parser('preflight')
    commands.add_parser('disk-status'); commands.add_parser('stop')
    install = commands.add_parser('install-build')
    install.add_argument('--candidate', type=Path, required=True)
    install.add_argument('--sha256', required=True)
    install.add_argument('--monitor-config', type=Path, required=True)
    prepared = commands.add_parser('prepare-batch')
    prepared.add_argument('--batch-id', required=True)
    prepared.add_argument('--plan', type=Path, required=True)
    run = commands.add_parser('run-batch')
    run.add_argument('--batch-id', required=True)
    run.add_argument('--max-seconds', type=int, required=True)
    batch = commands.add_parser('batch-status')
    batch.add_argument('--batch-id', required=True)
    driver = commands.add_parser('batch-driver-status')
    driver.add_argument('--batch-id', required=True)
    args = parser.parse_args(argv)
    try:
        agent = DemoAgent(args.installation)
        if args.command == 'status': result = agent.status()
        elif args.command == 'preflight': result = agent.preflight()
        elif args.command == 'disk-status': result = agent.disk_status()
        elif args.command == 'stop': result = agent.stop()
        elif args.command == 'install-build': result = agent.install_build(args.candidate, args.sha256, args.monitor_config)
        elif args.command == 'prepare-batch': result = agent.prepare_batch(args.batch_id, args.plan)
        elif args.command == 'run-batch': result = agent.run_batch(args.batch_id, args.max_seconds)
        elif args.command == 'batch-status': result = agent.batch_status(args.batch_id)
        elif args.command == 'batch-driver-status': result = agent.batch_driver_status(args.batch_id)
        print(json.dumps(dict(ok=True, result=result), sort_keys=True, default=str))
        return 0
    except Exception as exc:
        code = 'REFUSED' if isinstance(exc, ValueError) else 'IO_ERROR' if isinstance(exc, OSError) else 'INTERNAL_ERROR'
        print(json.dumps(dict(ok=False, code=code, error=str(exc)), sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
