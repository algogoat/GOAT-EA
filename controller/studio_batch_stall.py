"""A native batch that stopped advancing: plain words and the supported recovery (goatai#1885).

Banker, 2026-10-05: member 34 (CADCHF) hit the EA's 500 s tester-idle timeout at
16:42:25Z while the Strategy Tester was still busy. The EA queued member 35 and
deferred its own MT5 restart "until the Strategy Tester is idle", but only the
finishing batch EA retries that restart, and it had already deinitialised; the
read-only monitor chart does not retry it. MT5 never restarted
(``restart_pending`` stayed true, tester idle, member 35 queued), no member ran
for 4.5 h, and research-status still read ``running``.

Nothing in the controller can restart the EA's member sequence, and batch-pause
cannot settle this shape: its safe point and ``--immediate`` both wait for
``restart_pending`` to clear. The supported recovery is the ordinary Stop, then
Continue. The monitor chart answers the cancel (it clears the EA's batch and its
deferred restart), finish keeps every finished member, and continue prepares the
remaining members as ``<id>-rN`` and starts them.

Read-only helpers; nothing here signals MT5 or changes state.
"""
from datetime import datetime

# Longer than an ordinary member-boundary relaunch (seconds to a few minutes) and
# than the EA's own 500 s tester-idle timeout, so a slow relaunch never reads stalled.
STALL_SECONDS = 15 * 60
FINISHED = frozenset(('native_completed', 'native_cancelled', 'native_error'))
WAITING = ('native_queued', 'native_pending')


def recovery(session, job_id):
    """The lane's exact Stop-then-Continue commands for a stalled batch."""
    if (session or {}).get('authority_kind') == 'demo_direct':
        prefix = 'goat.exe demo --installation <receipt> '
        steps = [['stop'], ['continue', '--batch-id', job_id, '--clear-stop']]
        note = ('Add --include-failed to the continue to retry the failed member. If stop answers stop_unconfirmed, '
                'run batch-pause --batch-id ' + job_id + ' (it adopts that stop), then continue.')
    else:
        prefix = 'goat.exe studio --installation <receipt> '
        steps = [['batch-stop', '--job-id', job_id], ['batch-continue', '--job-id', job_id]]
        note = ('batch-continue prepares <id>-rN; start it with Start-Batch after the user\'s yes '
                '(--mt5-restart-consent).')
    return dict(commands=[prefix + ' '.join(step) for step in steps], args=steps, note=note)


def plain(job_id, minutes, *, last=None, restart_pending=None, session=None):
    """One sentence a person or an agent can act on."""
    fix = recovery(session, job_id)
    ended = ''
    if isinstance(last, dict) and last.get('number') is not None:
        ended = (' since member ' + str(last['number']) + (' (' + str(last.get('symbol')) + ')' if last.get('symbol') else '')
                 + ' ended' + (' as ' + str(last['status']) if last.get('status') else '')
                 + (' at ' + str(last['finished_utc']) if last.get('finished_utc') else ''))
    cause = (' MT5 is waiting for its own between-member restart, which did not happen.' if restart_pending is True else '')
    return ('Stalled: no member has run for ' + str(int(minutes)) + ' min' + ended + '; the tester is idle and the native '
            'queue still has members waiting, so it needs reconcile.' + cause + ' Run ' + fix['commands'][0]
            + ', then ' + fix['commands'][1] + ' (finished members are kept; the rest run as ' + job_id + '-rN).')


def refusal_recovery(session, job_id):
    """The only recovery for a batch the EA refused before any test ran: stop it, fix the SET, prepare anew.

    Never continue --clear-stop: the EA refuses the same inputs again, and clear-stop only clears the
    owner STOP file (Banker, 2026-10-13)."""
    if (session or {}).get('authority_kind') == 'demo_direct':
        prefix, steps = 'goat.exe demo --installation <receipt> ', [['stop']]
    else:
        prefix, steps = 'goat.exe studio --installation <receipt> ', [['batch-stop', '--job-id', job_id]]
    return dict(commands=[prefix + ' '.join(step) for step in steps], args=steps,
                note='Then rebuild the SET (fix the input the EA names), prepare a new batch from it and start that. '
                     'Do not continue ' + job_id + ': an unchanged retry refuses again, and clear-stop only clears '
                     'the owner STOP file.')


def _refused(refusal_fn):
    """The EA's refusal of this attempt (studio_ea_refusal), read only once a stall holds; None on any error."""
    if refusal_fn is None:
        return None
    try:
        refusal = refusal_fn()
    except Exception:
        return None
    return refusal if isinstance(refusal, dict) and refusal.get('plain') else None


def _verdict(job_id, minutes, since, restart_pending, session, last, refusal):
    if refusal is not None:
        fix = refusal_recovery(session, job_id)
        return dict(since_wall=since, minutes=round(minutes), restart_pending=restart_pending, ea_refusal=refusal,
                    plain='Stalled: no member has run for ' + str(int(minutes)) + ' min. ' + refusal['plain']
                          + ' Run ' + fix['commands'][0] + ' first.',
                    fix=fix)
    return dict(since_wall=since, minutes=round(minutes), restart_pending=restart_pending,
                plain=plain(job_id, minutes, last=last, restart_pending=restart_pending, session=session),
                fix=recovery(session, job_id))


def _wall(text):
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def research_stall(activity, monitor, journal, *, now, session, refusal_fn=None):
    """research-status: a running batch whose MT5 has run nothing for STALL_SECONDS, else None.

    Every condition is read from evidence research-status already holds: no member
    ongoing, members still waiting in an unfinished native queue, a ticking monitor
    whose tester is idle, and no member start or end for STALL_SECONDS (the last
    member's end, or the driver start when none has ended yet). Only then is
    ``refusal_fn()`` read: when the EA refused the attempt (its Experts log), the
    verdict quotes that reason and drops continue --clear-stop, which cannot fix it.
    """
    if not isinstance(activity, dict) or activity.get('kind') != 'batch' or activity.get('status') != 'running':
        return None
    if activity.get('evidence') != 'native_queue' or activity.get('current_member') is not None:
        return None
    counts = activity.get('status_counts') or {}
    if activity.get('native_status') in FINISHED or not any(counts.get(name) for name in WAITING):
        return None
    if not isinstance(monitor, dict) or monitor.get('ticking') is not True or monitor.get('tester_state') != 'idle':
        return None
    last = activity.get('last_member') if isinstance(activity.get('last_member'), dict) else None
    since = _wall(last.get('finished_utc')) if last else None
    if since is None and isinstance(journal, dict) and type(journal.get('started_wall')) in (int, float):
        since = journal['started_wall']
    if since is None or now - since < STALL_SECONDS:
        return None
    minutes = (now - since) / 60
    return _verdict(activity.get('batch_id'), minutes, since, monitor.get('restart_pending'), session, last,
                    _refused(refusal_fn))


def driver_stall(observed, record, *, quiet_since, now, session, job_id, monitor_fn, refusal_fn=None):
    """The driver's own view: reconcile reports nothing running, the native queue is not
    finished, nothing changed for STALL_SECONDS and the monitor shows an idle tester.

    ``observed`` is the reconcile reply with its retained native observation. The tester
    state comes from ``monitor_fn()`` (research-status's monitor classification), read
    only once every other condition holds: in this exact shape reconcile drops the runtime
    feedback, because ``restart_pending`` fails its policy check. Missing evidence never
    reads stalled.
    """
    if not isinstance(observed, dict) or observed.get('status') != 'reconcile_required':
        return None
    if not str(record.get('last_error') or '').startswith('Native queue is not finished'):
        return None
    if quiet_since is None or now - quiet_since < STALL_SECONDS:
        return None
    job = observed.get('job') if isinstance(observed.get('job'), dict) else {}
    evidence = job.get('native_observation') if isinstance(job.get('native_observation'), dict) else {}
    native = evidence.get('native') if isinstance(evidence.get('native'), dict) else {}
    members = native.get('members') if isinstance(native.get('members'), list) else []
    statuses = [member.get('status') for member in members if isinstance(member, dict)]
    if not statuses or 'native_ongoing' in statuses or not any(status in WAITING for status in statuses):
        return None
    try:
        monitor = monitor_fn()
    except Exception:
        return None
    if not isinstance(monitor, dict) or monitor.get('ticking') is not True or monitor.get('tester_state') != 'idle':
        return None
    minutes = (now - quiet_since) / 60
    return _verdict(job_id, minutes, quiet_since, monitor.get('restart_pending'), session, None, _refused(refusal_fn))
