"""Validate fresh Studio runtime feedback; this is not launch authorization."""
from datetime import datetime, timezone
from pathlib import PureWindowsPath
import time

STALE = 'Runtime feedback is stale or future-dated'
# A batch start's first runtime read may land in the EA's reporting gap (GOAT-EA#323, T2 2026-11-12: a successor's
# driver started 50 s after its parent's pause settled, read a sample older than 20 s and refused 0.5 s into the
# start; the monitor ticked normally minutes before and after). The bound below is unchanged. A start whose first
# read is stale reads again, every START_FRESH_POLL_SECONDS for up to START_FRESH_WAIT_SECONDS, before it refuses.
START_FRESH_WAIT_SECONDS = 60
START_FRESH_POLL_SECONDS = 1


def await_fresh(read, *, between=None, note=None, seconds=None, poll=None):
    """``read()`` (a full runtime check), repeated while its only refusal is a stale sample.

    For the first read of a batch start only, before anything is reserved, recorded or sent to MT5. Every repeat is
    the whole check again on a newly read sample: the freshness bound is never widened, and any other refusal (wrong
    account, Algo Trading on, tester busy, unbound monitor) is raised at once. ``between()`` runs before each repeat
    (the start's own ownership/STOP/deadline checkpoint). A sample still stale at the deadline raises the same error.
    ``note(dict)`` receives how long the start waited when it waited at all.
    """
    seconds = START_FRESH_WAIT_SECONDS if seconds is None else seconds
    poll = START_FRESH_POLL_SECONDS if poll is None else poll
    started = time.monotonic(); polls = 0
    def report(fresh):
        if polls and note is not None:
            note(dict(polls=polls, waited_seconds=round(time.monotonic() - started, 1), fresh=fresh))
    while True:
        try:
            value = read()
        except ValueError as error:
            if str(error) != STALE or time.monotonic() - started >= seconds:
                report(False)
                raise
        else:
            report(True)
            return value
        polls += 1
        time.sleep(poll)
        if between is not None:
            between()


def check_runtime(observation, *, now, modified, data_path, installation_path,
                  program_path, account_login, account_server, max_age=20, require_idle=False,
                  expected_batch_ongoing=False):
    stamp=datetime.strptime(observation['observed_terminal_utc'],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    if not 0 <= now-modified <= max_age or not -2 <= now-stamp <= max_age:
        raise ValueError(STALE)
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
