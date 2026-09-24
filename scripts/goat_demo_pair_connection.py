"""Bounded same-account reconnect; no order, close, config-write or Algo commands."""
import argparse
import configparser
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from goat_demo_pair_builds import BUILDS

CONNECTION_SERVER = 'Darwinex-Demo'
EXPERT_RELATIVE = 'MQL5/Experts/GOAT Experiment/GOAT V1.48.ex5'
CREDENTIAL_RELATIVE = 'GOAT/Credentials/api-bearer-balanced35-ai-20260923.token'
BUILD_ID = 'V1.48-DASHBOARD-AI-PAIR-R1'
PAIR_ACCOUNTS = {7: 3000109427, 8: 3000109421}


class Refused(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def canonical(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def decode(raw):
    require(0 < len(raw) <= 65536, 'input_size')
    return json.loads(raw, object_pairs_hook=unique_object)


def validate_manifest(value):
    require(type(value) is dict and set(value) == {'schema', 'terminals'}
            and value['schema'] == 'goat-demo-pair-connection-v1', 'manifest_schema')
    require(type(value['terminals']) is list and len(value['terminals']) == 2, 'exact_pair_required')
    fields = {'terminal', 'directory', 'login', 'server', 'currency', 'leverage', 'terminalSha256',
              'profile', 'profileSha256', 'commonIniSha256', 'savedAlgoEnabled', 'eaSha256',
              'expertRelativePath', 'credentialRelativePath', 'buildId'}
    roots = []
    for row in value['terminals']:
        require(type(row) is dict and set(row) == fields, 'terminal_schema')
        require(type(row['terminal']) is int and row['terminal'] in PAIR_ACCOUNTS
                and type(row['login']) is int and row['login'] == PAIR_ACCOUNTS[row['terminal']], 'account_binding')
        require(ntpath.isabs(row['directory']) and '..' not in row['directory'].replace('/', '\\').split('\\')
                and ntpath.basename(row['directory']).startswith(str(row['terminal']).zfill(2)+' - '), 'directory_binding')
        require(row['server'] == 'Darwinex-Demo' and row['currency'] == 'USD'
                and type(row['leverage']) is int and row['leverage'] == 200, 'account_policy')
        require(type(row['savedAlgoEnabled']) is bool, 'saved_algo_required')
        require(row['profile'] == 'Default', 'profile_name')
        require(row['expertRelativePath'] == EXPERT_RELATIVE and row['credentialRelativePath'] == CREDENTIAL_RELATIVE
                and row['buildId'] in BUILDS, 'build_paths')
        for key in ('terminalSha256', 'profileSha256', 'commonIniSha256', 'eaSha256'):
            require(isinstance(row[key], str) and re.fullmatch('[a-f0-9]{64}', row[key])
                    and row[key] != '0'*64, 'qualified_hash_required')
        require(row['eaSha256']==BUILDS[row['buildId']]['artifactSHA256'],'reviewed_build_hash')
        roots.append(canonical(row['directory']))
    require({r['terminal'] for r in value['terminals']} == {7, 8} and len(set(roots)) == 2
            and not any(a.startswith(b+'\\') for a in roots for b in roots if a != b), 'pair_paths_overlap')
    return sorted(value['terminals'], key=lambda r: r['terminal'])


def validate_pair_manifest(value):
    return [dict(row, id=('control' if row['terminal']==7 else 'ai')) for row in validate_manifest(value)]


def validate_vault(value, rows):
    require(type(value) is list and len(value) == 2, 'vault_pair_required')
    for account, row in zip(value, rows):
        require(type(account) is dict and str(account.get('login')) == str(row['login'])
                and account.get('server') == row['server'], 'vault_account_binding')
        require(isinstance(account.get('master'), str) and 0 < len(account['master']) <= 512, 'vault_credential_missing')
    return value


def file_hash(path, limit):
    require(path.is_file() and not path.is_symlink() and not path.is_junction(), 'unsafe_file')
    require(path.stat().st_nlink == 1, 'hardlink_refused')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as handle:
        while block := handle.read(1024 * 1024):
            count += len(block)
            require(count <= limit, 'file_too_large')
            digest.update(block)
    require(count > 0, 'empty_file')
    return digest.hexdigest()


def verify_files(row, closed=False):
    directory = Path(row['directory'])
    require(not directory.is_symlink() and not directory.is_junction(), 'directory_alias')
    require(file_hash(directory / 'terminal64.exe', 128 * 1024 * 1024) == row['terminalSha256'], 'terminal_hash')
    require(file_hash(directory / row['expertRelativePath'], 32 * 1024 * 1024) == row['eaSha256'], 'ea_hash')
    if not closed:
        return
    config = directory / 'config/common.ini'
    require(file_hash(config, 1024 * 1024) == row['commonIniSha256'], 'common_ini_hash')
    raw = config.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == row['commonIniSha256'], 'common_ini_changed')
    text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
    settings = configparser.ConfigParser(interpolation=None, strict=True)
    settings.read_string(text)
    require(settings.get('Common', 'Login', fallback='') == str(row['login'])
            and settings.get('Common', 'Server', fallback='') == row['server'], 'saved_account_mismatch')
    require(settings.get('Experts', 'Enabled', fallback='') == ('1' if row['savedAlgoEnabled'] else '0'), 'saved_algo_mismatch')
    # Freeze the entire profile, including filenames, rather than just a .chr.
    profile = directory / 'MQL5/Profiles/Charts' / row['profile']
    require(profile.is_dir() and not profile.is_symlink() and not profile.is_junction(), 'profile_missing_or_alias')
    claims = []
    paths = []
    for path in profile.rglob('*'):
        require(len(paths) < 1024, 'profile_entry_limit')
        paths.append(path)
    for path in sorted(paths):
        require(not path.is_symlink() and not path.is_junction(), 'profile_alias')
        if path.is_file():
            require(len(claims) < 512, 'profile_file_limit')
            claims.append([path.relative_to(profile).as_posix(), file_hash(path, 2 * 1024 * 1024)])
    require(bool(claims), 'empty_profile')
    digest = hashlib.sha256(json.dumps(claims, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    require(digest == row['profileSha256'], 'profile_hash')


class WindowsHost:
    @staticmethod
    def powershell(script):
        import base64
        encoded = base64.b64encode(script.encode('utf-16-le')).decode()
        completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                   capture_output=True, timeout=20, creationflags=0x08000000)
        require(completed.returncode == 0 and len(completed.stdout) <= 65536, 'process_probe_failed')
        return completed.stdout.decode('utf-8-sig').strip()

    def processes(self, row):
        raw = self.powershell("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
            "@(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | ForEach-Object { "
            "if(-not $_.ExecutablePath){throw 'unobservable process'}; "
            "@{pid=[int]$_.ProcessId;path=$_.ExecutablePath;created=$_.CreationDate.ToUniversalTime().ToString('o')} }) | ConvertTo-Json -Compress")
        values = json.loads(raw) if raw else []
        if isinstance(values, dict):
            values = [values]
        return [item for item in values if canonical(item['path']) == canonical(ntpath.join(row['directory'], 'terminal64.exe'))]

    def launch(self, row):
        # Every interpolated path/name was bound by the exact manifest validator.
        directory = row['directory'].replace("'", "''")
        profile = row['profile'].replace("'", "''")
        raw = self.powershell("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $launched=Start-Process -PassThru -FilePath '" + directory
            + "\\terminal64.exe' -WorkingDirectory '" + directory
            + "' -ArgumentList '/portable','/profile:\"" + profile + "\"' -WindowStyle Hidden; "
            + "$native=Get-CimInstance Win32_Process -Filter ('ProcessId='+$launched.Id); "
            + "if($launched.HasExited -or -not $native -or -not $native.ExecutablePath){throw 'launch unobservable'}; "
            + "@{pid=[int]$native.ProcessId;path=$native.ExecutablePath;created=$native.CreationDate.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress")
        identity = json.loads(raw)
        require(type(identity) is dict and type(identity.get('pid')) is int
                and isinstance(identity.get('created'), str) and bool(identity['created'])
                and canonical(identity.get('path', '')) == canonical(ntpath.join(row['directory'], 'terminal64.exe')),
                'launch_identity_invalid')
        require(self.processes(row) == [identity], 'launch_process_changed')
        return identity


def snapshot(mt5, row):
    info, runtime = mt5.account_info(), mt5.terminal_info()
    require(info is not None and runtime is not None, 'unobservable_account')
    require(info.login == row['login'] and info.server == row['server'], 'wrong_account')
    require(canonical(runtime.data_path) == canonical(row['directory'])
            and canonical(runtime.path) == canonical(row['directory']), 'wrong_runtime_path')
    require(info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            and info.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
            and info.currency == row['currency'] and info.leverage == row['leverage'], 'wrong_account_policy')
    require(type(runtime.trade_allowed) is bool and type(runtime.connected) is bool, 'unobservable_algo')
    positions, orders = mt5.positions_get(), mt5.orders_get()
    require(positions is not None and orders is not None, 'unobservable_positions_orders')
    return {'login': info.login, 'server': info.server, 'dataPath': runtime.data_path,
            'tradeMode': info.trade_mode, 'marginMode': info.margin_mode, 'currency': info.currency,
            'leverage': info.leverage, 'connected': runtime.connected, 'algoEnabled': runtime.trade_allowed,
            'balance': float(info.balance), 'equity': float(info.equity), 'brokerTradeAllowed': bool(info.trade_allowed),
            'positionTickets': sorted(item.ticket for item in positions), 'orderTickets': sorted(item.ticket for item in orders)}


def reconnect(mt5, host, row, account, allow_closed=False, verifier=verify_files, audit=None, initial=False,
              persistence_proof=None, persistence_sha256=None):
    audit = {} if audit is None else audit
    verifier(row, False)
    observed = host.processes(row)
    require(len(observed) <= 1, 'duplicate_terminal_process')
    started = not observed
    require(not initial or (started and row['savedAlgoEnabled'] is False), 'initial_requires_cold_inert_launch')
    if started:
        require(allow_closed, 'closed_launch_not_requested')
        verifier(row, True)
        if row['savedAlgoEnabled']:
            from goat_demo_pair_profile import verify_enabled_persistence
            verify_enabled_persistence(row,persistence_proof,persistence_sha256)
            audit['enabledPersistenceSha256']=persistence_sha256
        require(not host.processes(row), 'startup_race')
        audit['stage']='launch_terminal_once'
        launched_identity = host.launch(row)
        observed = host.processes(row)
        require(observed == [launched_identity], 'launch_process_changed')
    require(len(observed) == 1, 'terminal_process_missing')
    identity = observed[0]
    audit['process'] = identity
    audit['launched'] = started
    audit['credentialedInitialize'] = False
    audit['startedWithAlgoEnabled']=started and row['savedAlgoEnabled']
    before = None
    try:
        # A cold process has no cached password. Only this invocation's explicit,
        # file-bound launch may receive its pre-authorized same-account credential.
        # Existing processes always attach without credentials, with no fallback.
        require(host.processes(row) == [identity], 'process_changed_before_attach')
        options = dict(timeout=15000, portable=True)
        if started:
            options.update(login=row['login'], password=account['master'], server=CONNECTION_SERVER)
            audit['credentialedInitialize'] = True
        try:
            audit['stage']='initialize_sdk_once'
            attached = mt5.initialize(ntpath.join(row['directory'], 'terminal64.exe'), **options)
        finally:
            options.clear()
        require(host.processes(row) == [identity], 'process_changed_during_attach')
        require(attached, 'cold_initialize_failed' if started else 'attach_failed')
        before = snapshot(mt5, row)
        audit['before'] = before
        if started:
            require(before['algoEnabled'] == row['savedAlgoEnabled'], 'startup_algo_differs')
            require(before['connected'], 'cold_initialize_disconnected')
        used_login = False
        if not before['connected']:
            require(host.processes(row) == [identity], 'process_changed_before_login')
            # Re-read identity immediately before a same-account reconnect.
            require(snapshot(mt5, row) == before, 'state_changed_before_login')
            used_login = True
            require(mt5.login(row['login'], password=account['master'], server=CONNECTION_SERVER, timeout=15000), 'same_account_login_failed')
        after = snapshot(mt5, row)
        audit['after'] = after
        if initial:
            require(after['balance']==100000 and after['equity']==100000 and after['brokerTradeAllowed']
                    and not after['algoEnabled'] and not after['positionTickets'] and not after['orderTickets'],
                    'fresh_demo_conditions_not_met')
        require(host.processes(row) == [identity], 'process_changed_after_readback')
        require(after['connected'], 'still_disconnected')
        require(after['algoEnabled'] == before['algoEnabled'], 'algo_state_changed')
        require(after['positionTickets'] == before['positionTickets'] and after['orderTickets'] == before['orderTickets'], 'positions_or_orders_changed')
        return {'terminal': row['terminal'], 'status': 'verified_same_account', 'launched': started,
                'credentialedInitialize': started,
                'sameAccountLogin': used_login, 'process': identity, 'before': before, 'after': after}
    finally:
        mt5.shutdown()  # Python IPC disconnect only; never terminal termination.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--terminal', type=int, choices=(7,8), required=True)
    parser.add_argument('--allow-closed', action='store_true')
    parser.add_argument('--sdk-path', type=Path, required=True)
    parser.add_argument('--attempt-dir', type=Path, required=True)
    parser.add_argument('--protected-witness', type=Path, required=True)
    parser.add_argument('--initial-login', action='store_true')
    parser.add_argument('--admission-proof', type=Path)
    parser.add_argument('--admission-sha256')
    parser.add_argument('--persistence-proof', type=Path)
    parser.add_argument('--persistence-sha256')
    args = parser.parse_args()
    report = {'schema': 1, 'status': 'needs_review', 'tradingEnabledByScript': False,'stage':'validate_inputs'}
    vault = None
    try:
        rows = validate_manifest(decode(args.manifest.read_bytes()))
        vault = validate_vault(decode(sys.stdin.buffer.read(65537)), rows)
        require(os.name == 'nt', 'windows_required')
        from goat_demo_pair_guard import checked_witness, claim_once, lifecycle_lock, assert_new_pair_paths
        host = WindowsHost()
        witness = checked_witness(args.protected_witness, host)
        row = next(r for r in rows if r['terminal'] == args.terminal)
        account = vault[rows.index(row)]
        verify_files(row, not host.processes(row))
        if args.initial_login:
            for chart in (Path(row['directory'])/'MQL5/Profiles/Charts/Default').glob('*.chr'):
                raw_chart=chart.read_bytes()
                text=raw_chart.decode('utf16') if raw_chart.startswith(b'\xff\xfe') else raw_chart.decode('utf-8-sig')
                require('<expert>' not in text, 'initial_profile_must_be_bare')
        else:
            from goat_demo_pair_guard import verify_admission
            verify_admission(args.admission_proof,args.admission_sha256,row)
        args.attempt_dir.mkdir(parents=True, exist_ok=False)
        # Account/path claim survives unknown failure. A different output directory
        # must not provide an accidental retry of an unresolved startup intent.
        report['stage']='load_sdk'
        sys.path.insert(0, str(args.sdk_path))
        import MetaTrader5 as mt5
        assert_new_pair_paths(rows, witness)
        report['stage']='acquire_lifecycle_lock'
        with lifecycle_lock(witness):
            report['stage']='validate_locked_startup'
            checked_witness(args.protected_witness, host, expected=witness)
            verify_files(row,not host.processes(row))
            if not host.processes(row) and row['savedAlgoEnabled']:
                from goat_demo_pair_profile import verify_enabled_persistence
                verify_enabled_persistence(row,args.persistence_proof,args.persistence_sha256)
            report['stage']='claim_startup_once'
            claim = claim_once(Path(row['directory'])/'GOAT-startup-intent.json',
                               {'account':row['login'], 'attempt':str(args.attempt_dir),
                                'manifestSha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest()})
            report['stage']='reconnect'
            report.update(reconnect(mt5, host, row, account, args.allow_closed, audit=report,initial=args.initial_login,
                                    persistence_proof=args.persistence_proof,persistence_sha256=args.persistence_sha256))
            report['initialLogin']=args.initial_login
            report['observedAtUtc']=time.time()
        checked_witness(args.protected_witness, host, expected=witness)
        report['stage']='persist_verification'
        (args.attempt_dir/'verification.json').write_text(json.dumps(report), encoding='utf-8')
        # Successful proof permits a later explicit restart; retain completed claim.
        report['stage']='retire_startup_claim'
        claim.rename(claim.with_name('GOAT-startup-complete-'+uuid.uuid4().hex+'.json'))
        report['stage']='completed'
    except Refused as error:
        report['status'] = 'needs_review'
        report['reason'] = str(error)
    except Exception as error:
        report['status'] = 'needs_review'
        report['reason'] = 'unexpected_error_inspect_retained_intent'
        report['exceptionType']=type(error).__name__
        if isinstance(error,OSError):
            report['errno']=error.errno
            report['winerror']=getattr(error,'winerror',None)
    finally:
        vault = None
    if args.attempt_dir.is_dir() and not (args.attempt_dir/'result.json').exists():
        with (args.attempt_dir/'result.json').open('x', encoding='utf8') as f: json.dump(report, f)
    print(json.dumps(report))
    return 0 if report['status'] == 'verified_same_account' else 2


if __name__ == '__main__':
    # Guards/profile import this module by name. Keep their Refused type identical
    # to the CLI's rather than loading a second copy beside __main__.
    sys.modules['goat_demo_pair_connection']=sys.modules[__name__]
    raise SystemExit(main())
