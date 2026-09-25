"""Validate fresh Studio runtime feedback; this is not launch authorization."""
from datetime import datetime, timezone
from pathlib import PureWindowsPath


def check_runtime(observation, *, now, modified, data_path, installation_path,
                  program_path, account_login, account_server, max_age=20, require_idle=False,
                  expected_batch_ongoing=False):
    stamp=datetime.strptime(observation['observed_terminal_utc'],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    if not 0 <= now-modified <= max_age or not -2 <= now-stamp <= max_age:
        raise ValueError('Runtime feedback is stale or future-dated')
    if observation.get('schema_version')!=1 or observation.get('bound') is not True:
        raise ValueError('Bound Studio runtime feedback required')
    runtime=observation.get('runtime')
    if not isinstance(runtime,dict):raise ValueError('Runtime feedback unavailable in this build')
    for key,expected in [('data_path',data_path),('installation_path',installation_path),('program_path',program_path)]:
        actual=runtime.get(key)
        if not isinstance(actual,str) or PureWindowsPath(actual)!=PureWindowsPath(expected):
            raise ValueError('Runtime '+key+' mismatch')
    if runtime.get('account_login')!=str(account_login) or runtime.get('account_server')!=account_server:
        raise ValueError('Runtime account mismatch')
    required={'connected':True,'account_demo':True,'terminal_trade_allowed':False,
              'batch_ongoing':expected_batch_ongoing,'restart_pending':False}
    for key,expected in required.items():
        if runtime.get(key) is not expected:raise ValueError('Runtime policy mismatch: '+key)
    tester=runtime.get('tester_state','unknown')
    if tester not in ('idle','running','unknown'):raise ValueError('Invalid tester state')
    if require_idle and tester!='idle':raise ValueError('Tester idleness not confirmed: '+tester)
    return dict(status='research_binding_and_flags_match',launch_permitted=False,
                tester_state=tester,
                limitations=['Tester button state is a point-in-time observation, not an execution lock','Program path is not binary hash attestation',
                             'Cross-terminal Common Files ownership not verified'])
