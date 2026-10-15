"""News-file guard for resumes (goatai#2350, Claude-Mac ruling (c) on GOAT-EA#200).

``news-history-sync`` may replace ``Common\\Files\\GOAT\\GOAT_News.csv`` between the members of a paused or
stopped run. A run whose SETs trade on news must not quietly continue on a different news file: its results
would mix two news histories. So:

* **Start records the file.** Every start records the sha256 of the news file's bytes as they are on disk
  (``None`` when there is no file):
  - a native batch at every native start route (``studio_research_authority.before_native_dispatch``), in
    ``<controller state>\\news-file\\batch-<id>.json`` (the queue row lives in the store, so the record sits
    beside it, keyed by batch ID);
  - a seed hunt, catch-up or hold-up test at its first start (``SeedRunner._activate``), in the run's own
    ``state.json`` as ``news_file``. Every member launch then records the sha it ran with.
* **Resume compares.** A news-on run refuses to resume when the file now differs from the recorded one, and
  a news-on run that has no record (it started before this guard) refuses too, because GOAT cannot prove the
  file is the same. The resumes are: a successor batch (``resume_batch``: batch-continue, batch-resume,
  resume-batch, and the demo lane's continue/batch-resume) and its start, the release of a paused seed /
  catch-up / hold-up (``release_pause``), and the re-activation of a stopped one (``_activate(reactivate)``).
  A run whose record exists also re-checks before every member launch.
* **``--accept-news-change``** continues anyway as a new, labelled news lineage. Both shas are recorded and
  the results are marked: a successor batch's record says ``lineage: news_changed`` with
  ``predecessor_sha256`` and ``accepted.to_sha256``; a runner's ``news_file.changes`` lists each accepted change
  and every member carries ``news_sha256`` and ``news_lineage`` (0 = the file it started with). research-queue
  rows carry the same label, so results from different news files are never merged.
* **Scope: only SETs that trade on news.** ``Mode_News`` is ``ENUM_ACTION_NEWS`` (GOAT_Inputs_Definitions.mqh):
  0 Display, 1 Disabled (the default), 2 Avoid, 3 Pause, 4 Close, 5 Only. Display reads the file but never
  changes a trade, so a SET is news-on only when ``Mode_News`` can be 2 or more: its value, or for an optimised
  input (``value||start||step||stop||Y``) any value of the range. A missing ``Mode_News`` is the default
  (Disabled). A value GOAT cannot read as a whole number counts as news-on (fail closed). A run is news-on when
  any of its SETs is; news-off runs are never blocked and never asked to accept anything.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from studio_refusal import Refusal

RECORD_SCHEMA = 'goat-news-file-record-v1'
RECORD_FOLDER = 'news-file'
ACCEPT_FLAG = '--accept-news-change'
NEWS_RELATIVE = ('GOAT', 'GOAT_News.csv')
NEWS_ON_MINIMUM = 2          # News_Avoid; 0 Display and 1 Disabled never change a trade
ORIGINAL, CONTINUED, CHANGED = 'original', 'continued', 'news_changed'
_INTEGER = re.compile(r'\s*-?\d+\s*')


# ------------------------------------------------------------------ the file

def news_path(install):
    return Path(install['common_files_root']).joinpath(*NEWS_RELATIVE)


def news_sha256(install):
    """sha256 of GOAT_News.csv's bytes as on disk, or None when there is no file."""
    path = news_path(install)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _short(value):
    return 'no file' if value is None else value[:12]


def _utc(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds')


# ------------------------------------------------------------------ news-on

def mode_news_on(value):
    """Can this Mode_News SET value make news change a trade (2..5)? None (missing) is the default Disabled."""
    if value is None:
        return False
    parts = str(value).split('||')
    numbers = []
    for part in parts[:4]:
        if not _INTEGER.fullmatch(part):
            return True                      # unreadable: fail closed
        numbers.append(int(part))
    if numbers[0] >= NEWS_ON_MINIMUM:
        return True
    optimised = len(parts) >= 5 and parts[4].strip().upper() == 'Y'
    if optimised:
        if len(numbers) < 4:
            return True
        return max(numbers[1], numbers[3]) >= NEWS_ON_MINIMUM
    return False


def values_news_on(values_list):
    return any(mode_news_on((values or {}).get('Mode_News')) for values in values_list)


def job_news_on(job):
    """A queue row: every member's frozen strategy values (a batch's members, or a single prepared job)."""
    configuration = job.get('configuration') or {}
    members = configuration.get('batch_members')
    members = members if isinstance(members, list) else [configuration]
    return values_news_on((((member or {}).get('strategy') or {}).get('values') or {}) for member in members)


def manifest_news_on(manifest):
    """A seed / catch-up / hold-up manifest: the frozen member values, else the frozen (hash-verified) SET."""
    from studio_strategy_settings import read_values
    for member in manifest.get('members') or []:
        values = member.get('values')
        if not isinstance(values, dict):
            values = read_values(Path(member['set_path']).read_bytes())
        if mode_news_on(values.get('Mode_News')):
            return True
    return False


# ------------------------------------------------------------------ refusals

def _accept_how(how):
    return how or ('run the same command again with ' + ACCEPT_FLAG)


def _changed(what, recorded, current, how=None):
    return Refusal(what + ' trades on news (Mode_News 2-5), and GOAT_News.csv changed since it started (sha256 '
                   + _short(recorded) + ' then, ' + _short(current) + ' now). Continuing would mix results from two news '
                   'files, so nothing was started. Restore the previous file (GOAT_News.csv.bak) to continue on it, or '
                   + _accept_how(how) + ' to continue as a new news lineage that is labelled '
                   'and kept apart from the earlier results.', 'NEWS_FILE_CHANGED',
                   recorded_sha256=recorded, current_sha256=current, accept_flag=ACCEPT_FLAG)


def _unrecorded(what, current, how=None):
    return Refusal(what + ' trades on news (Mode_News 2-5) and started before GOAT recorded which GOAT_News.csv a run '
                   'uses, so GOAT cannot prove it would continue on the same news file. Nothing was started; '
                   + _accept_how(how) + ' to continue as a new news lineage that is labelled and kept '
                   'apart from the earlier results.', 'NEWS_FILE_UNRECORDED',
                   recorded_sha256=None, current_sha256=current, accept_flag=ACCEPT_FLAG)


# ------------------------------------------------------------------ native batches

def record_path(root, batch_id):
    return Path(root) / RECORD_FOLDER / ('batch-' + batch_id + '.json')


def load_record(root, batch_id):
    path = record_path(root, batch_id)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema') != RECORD_SCHEMA or value.get('batch_id') != batch_id:
        raise ValueError('The news-file record ' + str(path) + ' is not recognised; preserve it for review')
    return value


def _write(root, record):
    from studio_bridge import write_json
    path = record_path(root, record['batch_id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)


def _started_sha(record):
    """(known, sha) of a batch's start: known is False for a batch with no record of its start."""
    if record is None or 'sha256' not in record:
        return False, None
    return True, record['sha256']


def _lineage_predecessor(root, batch_id):
    """The predecessor named by batch-lineage (continue and batch-resume write it), or None."""
    path = Path(root) / 'batch-lineage' / (batch_id + '.json')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    previous = value.get('predecessor_batch_id') if isinstance(value, dict) else None
    return previous if isinstance(previous, str) else None


def _successor(root, batch_id, predecessor_id, news_on, current, *, ran, accept, now, how=None):
    """A successor's record (not yet started); refuses a news-on change without acceptance."""
    known, previous = _started_sha(load_record(root, predecessor_id))
    record = dict(schema=RECORD_SCHEMA, kind='batch', batch_id=batch_id, news_on=news_on,
                  predecessor_batch_id=predecessor_id, predecessor_recorded=known, predecessor_sha256=previous,
                  prepared_sha256=current, prepared_utc=_utc(now), lineage=CONTINUED, expected_sha256=None, accepted=None)
    if not news_on or not ran:
        return record                        # nothing to compare: news-off, or the predecessor never ran a member
    what = 'Batch ' + predecessor_id
    if known and current == previous:
        record['expected_sha256'] = previous
        return record
    if not accept:
        raise _changed(what, previous, current, how) if known else _unrecorded(what, current, how)
    record.update(lineage=CHANGED, expected_sha256=current,
                  accepted=dict(from_sha256=previous if known else None, to_sha256=current, accepted_utc=_utc(now),
                                reason='news_file_changed' if known else 'predecessor_unrecorded'))
    return record


def prepare_successor(controller, previous_job, batch_id, selected_values, *, ran, accept, now):
    """Check a successor before it is prepared (resume_batch). Returns its record; write it with save_record."""
    news_on = values_news_on(selected_values)
    return _successor(controller.root, batch_id, previous_job['job_id'], news_on, news_sha256(controller.install),
                      ran=ran, accept=accept, now=now)


def save_record(controller, record):
    prior = load_record(controller.root, record['batch_id'])
    if prior is not None and 'sha256' in prior:
        return public(prior)                 # already started: its start record stays as it is
    _write(controller.root, record)
    return public(record)


def accept_successor(root, install, job, *, now):
    """--accept-news-change for a successor that is already prepared and not started (a reused successor)."""
    batch_id = job['job_id']
    record = load_record(root, batch_id)
    if record is not None and 'sha256' in record:
        return public(record)                # started: its file is recorded; nothing to accept
    news_on = job_news_on(job) or bool(record and record.get('news_on'))
    predecessor = (record or {}).get('predecessor_batch_id') or _lineage_predecessor(root, batch_id)
    if predecessor is None or not news_on:
        return public(record)
    if record is not None and record.get('expected_sha256') is None and record.get('lineage') == CONTINUED:
        return public(record)                # its predecessor never ran a member: nothing to compare
    record = _successor(root, batch_id, predecessor, news_on, news_sha256(install), ran=True, accept=True, now=now)
    _write(root, record)
    return public(record)


def _start_how(predecessor):
    return ('accept it for this prepared batch with continue --batch-id ' + str(predecessor) + ' ' + ACCEPT_FLAG
            + ' on the demo lane (batch-continue --job-id ' + str(predecessor) + ' ' + ACCEPT_FLAG + ' in the Studio CLI; '
            'batch-resume with ' + ACCEPT_FLAG + ' for a paused batch), then start it again')


def check_native_start(controller, job, *, now):
    """Every native start route: refuse a news-on successor on a changed or unproven file, else record the start."""
    install, root = getattr(controller, 'install', None), getattr(controller, 'root', None)
    if not isinstance(install, dict) or 'common_files_root' not in install or root is None:
        return None                          # not an installed controller (no Common Files): nothing to record
    batch_id = job['job_id']
    record = load_record(root, batch_id)
    if record is not None and 'sha256' in record:
        return public(record)                # this start already recorded (a start validates more than once)
    news_on = job_news_on(job)
    current = news_sha256(install)
    if record is None:
        predecessor = _lineage_predecessor(root, batch_id)
        if predecessor is None:
            record = dict(schema=RECORD_SCHEMA, kind='batch', batch_id=batch_id, news_on=news_on, lineage=ORIGINAL,
                          predecessor_batch_id=None, expected_sha256=None, accepted=None)
        else:
            # A successor prepared before this guard existed: the same check as at preparation, no acceptance.
            record = _successor(root, batch_id, predecessor, news_on, current, ran=True, accept=False, now=now,
                                how=_start_how(predecessor))
    else:
        # Prepared by resume_batch: expected_sha256 is the file it may start on (the predecessor's, or the accepted
        # one); None means nothing to compare (news-off, or a predecessor that never ran a member).
        record['news_on'] = news_on = news_on or bool(record.get('news_on'))
        expected = record.get('expected_sha256')
        if news_on and expected is not None and current != expected:
            raise _changed('Batch ' + batch_id + ' (prepared to continue ' + str(record.get('predecessor_batch_id')) + ')',
                           expected, current, _start_how(record.get('predecessor_batch_id')))
    record.update(sha256=current, started_utc=_utc(now))
    _write(root, record)
    return public(record)


def public(record):
    """The label every reader shows: the file a run used and whether its news lineage changed."""
    if not isinstance(record, dict):
        return None
    accepted = record.get('accepted') or None
    return dict(sha256=record.get('sha256', record.get('expected_sha256')), news_on=record.get('news_on'),
                lineage=record.get('lineage'), predecessor_batch_id=record.get('predecessor_batch_id'),
                predecessor_sha256=record.get('predecessor_sha256'),
                accepted_change=None if accepted is None else dict(from_sha256=accepted.get('from_sha256'),
                                                                  to_sha256=accepted.get('to_sha256'),
                                                                  reason=accepted.get('reason')))


def batch_label(root, batch_id):
    """research-queue: the batch's news label, or None when it has no record (never raises)."""
    try:
        return public(load_record(root, batch_id))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ seed / catch-up / hold-up runs

def _active(record):
    changes = record.get('changes') or []
    return changes[-1]['to_sha256'] if changes else record.get('sha256')


def runner_record_start(install, state, manifest, *, now):
    """First start of a run: record the file in state['news_file'] (kept if a record exists)."""
    if isinstance(state.get('news_file'), dict):
        return state['news_file']
    state['news_file'] = dict(schema=RECORD_SCHEMA, path=str(news_path(install)), sha256=news_sha256(install),
                              recorded_utc=_utc(now), news_on=manifest_news_on(manifest), changes=[])
    return state['news_file']


def runner_news_on(state, manifest):
    record = state.get('news_file')
    if isinstance(record, dict) and type(record.get('news_on')) is bool:
        return record['news_on']
    return manifest_news_on(manifest)


def runner_check(install, state, manifest, *, what, legacy_refuses):
    """Refuse a news-on run on a changed file, or (``legacy_refuses``, a resume) one with no record."""
    if not runner_news_on(state, manifest):
        return None
    record = state.get('news_file')
    current = news_sha256(install)
    if not isinstance(record, dict):
        if legacy_refuses:
            raise _unrecorded(what, current)
        return None
    if current != _active(record):
        raise _changed(what, _active(record), current)
    return current


def runner_accept(install, state, manifest, *, now, first_alias=None):
    """--accept-news-change for a run: record the change (or the missing start record) as a new lineage."""
    if not runner_news_on(state, manifest):
        return None
    current = news_sha256(install)
    record = state.get('news_file')
    if not isinstance(record, dict):
        record = state['news_file'] = dict(schema=RECORD_SCHEMA, path=str(news_path(install)), sha256=None,
                                           recorded_utc=_utc(now), news_on=True, legacy_unrecorded=True, changes=[])
        reason = 'started_unrecorded'
    elif current != _active(record):
        reason = 'news_file_changed'
    else:
        return None                          # the same file: nothing to accept
    change = dict(from_sha256=_active(record) if reason == 'news_file_changed' else None, to_sha256=current,
                  accepted_utc=_utc(now), reason=reason, lineage=len(record['changes']) + 1, first_member=first_alias)
    record['changes'].append(change)
    return change


def runner_tag(install, state, item):
    """Before a member launch: the file sha and news lineage it runs with (runs that have a record only)."""
    record = state.get('news_file')
    if isinstance(record, dict):
        item['news_sha256'] = news_sha256(install)
        item['news_lineage'] = len(record.get('changes') or [])


def runner_label(state):
    record = state.get('news_file') if isinstance(state, dict) else None
    if not isinstance(record, dict):
        return None
    changes = record.get('changes') or []
    return dict(sha256=_active(record), news_on=record.get('news_on'), started_sha256=record.get('sha256'),
                lineage=CHANGED if changes else ORIGINAL, news_lineages=len(changes) + 1,
                accepted_changes=[dict(from_sha256=c.get('from_sha256'), to_sha256=c.get('to_sha256'),
                                       reason=c.get('reason'), first_member=c.get('first_member')) for c in changes])
