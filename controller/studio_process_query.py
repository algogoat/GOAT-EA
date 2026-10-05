"""Read-only Windows inventory queries (WMI through PowerShell) that survive a transient stall.

``Get-CimInstance Win32_Process`` normally answers in about 0.3 s, but WMI stalls intermittently on
loaded PCs. A single 20 s ``check_output`` then raised ``TimeoutExpired`` and killed whichever driver
asked (T2 and Banker, 2026-10-05, goatai#1885). Every inventory call site uses ``powershell_text``:

* up to ``ATTEMPTS`` tries, each with its own timeout, with ``PAUSES`` between them (worst case about
  100 s), and only for ``TimeoutExpired`` and ``CalledProcessError`` (a CIM error under
  ``$ErrorActionPreference='Stop'``). Each pause is jittered by up to ``JITTER`` either way, so two GOAT
  drivers hit by the same stall (it clusters at an MT5 launch) do not retry in lockstep. That full
  policy is for one-shot inventories that gate a launch or close. A caller with its own loop or
  deadline (status reads, polls) passes ``budget`` (seconds, at most ``POLL_BUDGET`` for pollers),
  and no attempt or pause runs past it (Claude-Mac, #1885);
* only this read-only query is repeated: no close, launch or other effect is ever retried here;
* it still fails closed: after the last attempt the *same* exception is raised again (with the
  attempt history as a note), so an unreadable inventory is never read as "no MT5";
* every failed attempt and the outcome are appended to the configured JSON-lines log, which is
  rotated at ``MAX_LOG_BYTES`` (one previous generation is kept).
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import time

ATTEMPTS = 4
PAUSES = (2, 5, 10)            # seconds between attempts, before jitter
JITTER = .25                   # each pause is scaled by a random factor in [1 - JITTER, 1 + JITTER]
TIMEOUT = 20                   # seconds per attempt
POLL_BUDGET = 25               # seconds, the most a status read or poll may spend on one inventory
MAX_LOG_BYTES = 1024 * 1024
RETRIED = (subprocess.TimeoutExpired, subprocess.CalledProcessError)
_LOG = {'path': None}
sleep = time.sleep             # injectable for tests
monotonic = time.monotonic
uniform = random.uniform


def configure(log_path):
    """Where failed attempts are recorded (``<controller state>\\process-query.jsonl``); None disables it."""
    _LOG['path'] = None if log_path is None else Path(log_path)


def _record(entry):
    path = _LOG['path']
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size >= MAX_LOG_BYTES:
            os.replace(path, path.with_name(path.stem + '.1' + path.suffix))     # bounded: one older generation
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(dict(entry, at=datetime.now(timezone.utc).isoformat(timespec='seconds')), sort_keys=True) + '\n')
    except OSError:
        pass                    # the log never decides an outcome


def _describe(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return 'timed out after %ss' % error.timeout
    return 'exited %s' % getattr(error, 'returncode', '?')


def powershell_text(command, *, purpose, timeout=TIMEOUT, attempts=ATTEMPTS, pauses=PAUSES, budget=None):
    """stdout of one read-only PowerShell inventory command, retried through a transient WMI stall."""
    from studio_subprocess import background_creationflags
    history, started = [], monotonic()
    deadline = None if budget is None else started + budget
    for attempt in range(1, attempts + 1):
        allowed = timeout if deadline is None else max(.1, min(timeout, deadline - monotonic()))
        try:
            output = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True, encoding='utf-8-sig',
                                             timeout=allowed, creationflags=background_creationflags())
        except RETRIED as error:
            history.append('attempt %d %s' % (attempt, _describe(error)))
            _record(dict(purpose=purpose, attempt=attempt, of=attempts, error=_describe(error), elapsed=round(monotonic() - started, 1)))
            pause = pauses[min(attempt - 1, len(pauses) - 1)] * uniform(1 - JITTER, 1 + JITTER)
            if attempt == attempts or (deadline is not None and monotonic() + pause + .1 >= deadline):
                _record(dict(purpose=purpose, outcome='gave_up', attempts=attempt, elapsed=round(monotonic() - started, 1)))
                note = ('Windows process inventory (%s) did not answer in %d attempts over %.0f s: %s. Nothing was inferred '
                        'from it.' % (purpose, attempt, monotonic() - started, '; '.join(history)))
                if hasattr(error, 'add_note'):
                    error.add_note(note)
                raise
            sleep(pause)
            continue
        if history:
            _record(dict(purpose=purpose, outcome='recovered_after', attempts=attempt, elapsed=round(monotonic() - started, 1)))
        return output
