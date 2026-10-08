"""Is a seed-start/seed-resume call driving this run right now? Read-only proof, never a guess (support 64f1c5ae).

The seed lane has no background driver by design: each ``seed-start``/``seed-resume`` call drives for at most its
``--max-seconds`` and nothing advances between calls. A tester's run read "active, N pending, none running"
after the caller's loop had ended on a transient error, and nothing said that the run waits for the next call.

Each call of the foreground (``goat.exe studio``) lane records itself in ``<run folder>/driver.json`` (the
last ``MAX_CALLS`` calls: its PID and the process creation time read from Windows itself, the command, its
budget, and on return the outcome). A status read never writes. It reports:

* ``running``: a recorded call has not returned and exactly that process (PID and creation time) is alive now;
* ``none``: every recorded call has returned, or the process of each call still open is gone (it was killed,
  for example by a tool timeout, before it could record its return), or no call was ever recorded;
* ``unknown``: Windows could not answer the process check, the shared CHECK_SECONDS deadline ran out before an
  entry was checked, or the record cannot be read. Nothing is inferred.

The process check is native first (OpenProcess + GetProcessTimes, exact to the microsecond the record holds);
CIM is only its fallback. Each new call closes (``gone``) the earlier open entries whose process Windows proves
is no longer running, so killed calls do not pile up.

The owner demo lane (``goat.exe demo``) has its own detached driver record (``demo-agent/lane-workers``) and
passes that liveness in instead (demo_agent._lane_liveness).
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import time
import uuid

RECORD = 'driver.json'
MAX_CALLS = 20
# The whole driver check of one status call (all entries together), well under an agent's tool timeout. The process
# check is native and instant; only an entry Windows will not answer for natively reaches the bounded CIM query.
CHECK_SECONDS = 8
MAX_RECORD_BYTES = 256 * 1024
RUNNING, NONE, UNKNOWN = 'running', 'none', 'unknown'


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds') if type(epoch) in (int, float) else None


def read(folder):
    """(record, error): the driver record, or None with no error when no call was ever recorded."""
    path = Path(folder) / RECORD
    try:
        if not path.exists():
            return None, None
        if path.is_symlink() or path.stat().st_size > MAX_RECORD_BYTES:
            return None, 'the driver record is a link or too large'
        import json
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return None, 'the driver record cannot be read (' + str(error)[:200] + ')'
    if not isinstance(value, dict) or not isinstance(value.get('calls'), list):
        return None, 'the driver record is not a driver record'
    return value, None


def begin(folder, *, command, max_seconds, now, identity, gone=None):
    """Record one call before it drives; returns its token. The caller holds the runner gate (one writer).

    ``gone(identity)`` (native and instant: WindowsSeedProcess.process_gone) closes every earlier entry still
    'driving' whose process Windows proves is no longer running (a call killed before it could record its
    return), so such entries never pile up for status reads to check. Anything not proven gone stays open."""
    from studio_bridge import write_json
    record, error = read(folder)
    calls = [] if record is None else [call for call in record['calls'] if isinstance(call, dict)]
    if gone is not None:
        for call in calls:
            if call.get('status') != 'driving':
                continue
            try:
                proven = gone(dict(pid=call.get('pid'), created_utc=call.get('created_utc'))) is True
            except Exception:
                proven = False                 # an unanswered check closes nothing
            if proven:
                call.update(status='gone', ended_unix=now,
                            error='Its process was gone when a later call began; it ended without recording its return')
    token = uuid.uuid4().hex
    calls.append(dict(token=token, command=command, pid=identity.get('pid'), created_utc=identity.get('created_utc'),
                      started_unix=now, deadline_unix=now + max_seconds, max_seconds=max_seconds, status='driving'))
    write_json(Path(folder) / RECORD, dict(schema_version=1, calls=calls[-MAX_CALLS:],
                                           **({} if error is None else dict(replaced_unreadable=error))))
    return token


def end(folder, token, *, now, outcome, result_status=None, error=None):
    """Record this call's return ('returned' or 'failed', with its plain error). The caller holds the runner gate."""
    from studio_bridge import write_json
    record, _ = read(folder)
    if record is None:
        return
    for call in record['calls']:
        if isinstance(call, dict) and call.get('token') == token:
            call.update(status=outcome, ended_unix=now, result_status=result_status,
                        **({} if error is None else dict(error=str(error)[:500])))
            write_json(Path(folder) / RECORD, record)
            return


def _public_call(call):
    return dict(command=call.get('command'), pid=call.get('pid'), status=call.get('status'),
                started_utc=_iso(call.get('started_unix')), deadline_utc=_iso(call.get('deadline_unix')),
                ended_utc=_iso(call.get('ended_unix')), result_status=call.get('result_status'), error=call.get('error'))


def liveness(folder, *, alive, own_pid=None, budget=None, deadline=None, command_prefix='seed', monotonic=None):
    """dict(state, basis, call, last_call) for this run. ``alive(identity, budget)`` returns True or False, or
    raises when Windows cannot answer; None means this process tool cannot check processes (unknown).

    Every check shares ONE deadline (``deadline``, a ``monotonic`` time; else now + ``budget``, at most
    CHECK_SECONDS): each gets only what is left, and an entry reached after it reads unknown, never running or
    stopped (Claude-Mac on GOAT-EA#197: 19 stale entries at 25 s each outlasted the agent's tool timeout)."""
    own_pid = os.getpid() if own_pid is None else own_pid
    monotonic = monotonic or time.monotonic
    if deadline is None:
        deadline = monotonic() + min(CHECK_SECONDS, budget if type(budget) in (int, float) and budget > 0 else CHECK_SECONDS)
    words = command_prefix + '-start or ' + command_prefix + '-resume call'
    record, error = read(folder)
    if error is not None:
        return dict(state=UNKNOWN, basis='GOAT cannot tell whether a ' + words + ' is driving this run: ' + error + '.',
                    call=None, last_call=None)
    calls = [] if record is None else [call for call in record['calls'] if isinstance(call, dict)]
    last = _public_call(calls[-1]) if calls else None
    # A call by this very process is the one asking (its closing status read): it is returning, not driving.
    open_calls = [call for call in calls if call.get('status') == 'driving' and call.get('pid') != own_pid]
    if not open_calls:
        basis = ('No ' + words + ' has been recorded for this run.' if not calls else
                 'No ' + words + ' is in progress: every recorded call has ended.')
        return dict(state=NONE, basis=basis, call=None, last_call=last)
    unknown, gone = [], []
    for call in reversed(open_calls):
        identity = dict(pid=call.get('pid'), created_utc=call.get('created_utc'))
        if alive is None:
            unknown.append('this process tool cannot check processes')
            continue
        remaining = deadline - monotonic()
        if remaining <= 0:
            unknown.append('the status check ran out of its time before this call could be checked')
            continue
        try:
            running = alive(identity, remaining)
        except Exception as exc:                 # any failure to check is "unknown", never stopped or running
            unknown.append(str(exc)[:200] or type(exc).__name__)
            continue
        if running is not True and running is not False:
            unknown.append('the process check gave no answer')
            continue
        if running is True:
            return dict(state=RUNNING, basis=('A ' + call.get('command', command_prefix + '-resume') + ' call (pid ' + str(call.get('pid'))
                                               + ', started ' + str(_iso(call.get('started_unix'))) + ') is driving this run now: its process is alive '
                                               'with the same PID and creation time it recorded.'),
                        call=_public_call(call), last_call=last)
        gone.append(call)
    if unknown:
        return dict(state=UNKNOWN, basis=('GOAT cannot tell whether the ' + words + ' recorded as in progress is still running ('
                                          + unknown[0] + '). Nothing is inferred.'),
                    call=_public_call(open_calls[-1]), last_call=last)
    call = gone[0]
    return dict(state=NONE, basis=('No ' + words + ' is in progress. The last one (' + str(call.get('command')) + ', pid ' + str(call.get('pid'))
                                   + ', started ' + str(_iso(call.get('started_unix'))) + ') ended without recording its return; its process '
                                   'is gone (for example a tool timeout or a crash ended it).'),
                call=None, last_call=last)
