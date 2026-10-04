"""Trial journal and trial counter: library scoring v1, phase 1 (goatai#2221 §5).

``trial-journal`` emits one normalized entry per member of every native batch, seed
hunt and catch-up this controller prepared, read only from its own retained
journals (change 4): queue rows, ``packages/``, ``attempts/*/result.json``,
``retired-starts/``, native evidence histories (read through
``studio_evidence_log.read`` so a compacted history reads the same), ``seeds/`` and
``catchups/``. Nothing here writes, launches or touches MT5, and the output carries
no clock: ``compact-evidence --apply`` and retiring an unactivated start leave it
byte-identical.

Counting (``trial-count``; Claude-Mac answers 4-7):

* a peek is one dispatched member-run, counted on each OOS window it covered
  (forward, back-oos, front-oos = ToDate to the export end, catch-up, held-out);
  in-sample is never a peek;
* failed, cancelled and abandoned dispatches count, unless the journal proves no OOS
  output existed (zero paired rows, no report or export, no metric log line);
* never-dispatched members (retired starts, members cancelled before they started)
  are ``not_dispatched`` and do not count;
* one optimization member is one variant; optimizer passes are only
  ``optimizer_candidates_seen`` (paired rows);
* an unattributed member counts against every key's exposure, and makes every key's
  count on its symbol and overlapping window non-reconstructable (worst case).
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from campaign_ledger import sha
from studio_heldout import canonical, iso_day, legacy_export_end, overlaps
from studio_strategy_attribution import Library, set_values, stable, variant_id

SCHEMA = 'goat-trial-journal-v1'
COUNT_SCHEMA = 'goat-trial-count-v1'
CAPABILITY = 'trial-journal'
OOS_ROLES = ('forward', 'back-oos', 'front-oos', 'catch-up', 'held-out')
WORST_CASE = dict(trial_worst_case_n=1000, rule='per-window-v1', applied_in_phase_1=False)
MAX_RESULT = 512 * 1024 * 1024
MAX_SMALL = 64 * 1024 * 1024
STARTED = ('native_ongoing', 'native_completed', 'native_error')
SEED_DISPATCHED = ('starting', 'running', 'closing', 'cancel_requested', 'timeout_requested', 'completed', 'failed',
                   'timeout', 'missing_output', 'reconcile_required')


def _read(path, limit=MAX_SMALL):
    """(bytes, parsed JSON) or (None, None); never raises for a missing or bad file."""
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > limit:
            return None, None
        raw = path.read_bytes()
        return raw, json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None, None


def _digest(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _day(value):
    found = iso_day(value) if value not in (None, '') else None
    return found


def _iso(day_value):
    return day_value.isoformat() if isinstance(day_value, date) else None


def _truthy(value):
    return value is True or value == 1 or (isinstance(value, str) and value.strip().lower() in ('true', '1', 'yes'))


def _window(role, start, end, **extra):
    if start is None or end is None or not start < end:
        return None
    return dict(role=role, start=start.isoformat(), end=end.isoformat(), **extra)


def _unix_iso(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _legacy_end(at):
    """Exclusive export end of an EA without EvidenceEnd: its last Friday when it exported."""
    return legacy_export_end(at) if at else None


# ---------------------------------------------------------------------------
# Native batches
# ---------------------------------------------------------------------------

def queue_rows(root):
    """Every retained queue row of every binding, read-only (older sessions' jobs ran too)."""
    database = Path(root) / 'studio.sqlite'
    if not database.is_file():
        return [], ['no studio.sqlite under the controller state root']
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT binding, jobs FROM studio_queues ORDER BY binding').fetchall()
    except sqlite3.Error as exc:
        return [], ['studio queue unreadable: ' + str(exc)]
    jobs, seen = [], set()
    for _, text in rows:
        try:
            values = json.loads(text)
        except ValueError:
            continue
        for job in values if isinstance(values, list) else []:
            if isinstance(job, dict) and isinstance(job.get('job_id'), str) and job['job_id'] not in seen:
                seen.add(job['job_id'])
                jobs.append(job)
    return jobs, []


def _history(root, job):
    """Indices of members ever observed started, or None when the history is unavailable."""
    from studio_evidence_log import read
    observations = list(job.get('native_evidence_history') or [])
    available = bool(observations)
    for key in ('native_evidence_archive', 'native_evidence_log'):
        reference = job.get(key)
        if isinstance(reference, dict) and isinstance(reference.get('path'), str):
            path = Path(reference['path'])
            if not path.is_absolute():
                path = Path(root) / path
            try:
                observations.extend(read(path))
                available = True
            except (OSError, ValueError):
                return None
    for archive in job.get('native_evidence_history_archives') or []:
        # History a triage tool moved outside the controller root, each slice bound by its
        # sha256 in the row. A missing or changed slice means the start cannot be proven.
        raw, value = _read((archive or {}).get('path') or '', MAX_RESULT)
        if raw is None or _digest(raw) != (archive or {}).get('sha256') or not isinstance(value, list):
            return None
        observations.extend(value)
        available = True
    if not available:
        return None
    started = set()
    for observation in observations:
        native = (observation or {}).get('native') if isinstance(observation, dict) else None
        for member in (native or {}).get('members') or []:
            if isinstance(member, dict) and member.get('status') in STARTED and type(member.get('index')) is int:
                started.add(member['index'])
    return started


def _report_member(reports, index, count):
    if not isinstance(reports, dict):
        return {}
    if isinstance(reports.get('members'), list):
        found = reports['members'][index] if index < len(reports['members']) else {}
        return found if isinstance(found, dict) else {}
    return reports if count == 1 else {}


def _oos_output(report, outcome, alias, error_lines):
    """observed | possible | proven_absent for one dispatched member (Claude-Mac answer 7)."""
    evidence = report.get('evidence') if isinstance(report.get('evidence'), dict) else None
    files = ((report.get('exports') or {}).get('files')) if isinstance(report.get('exports'), dict) else None
    if report.get('status') in ('report_pair_verified',) or files:
        return 'observed'
    if evidence is None or evidence.get('paired_rows') != 0 or evidence.get('forward_rows') not in (0, None):
        return 'possible'
    if outcome is not None and outcome.get('forward_rows') not in (0, None):
        return 'possible'
    if any(alias and alias in str(line) for line in error_lines):
        return 'possible'
    return 'proven_absent'


def _native_entries(root, suite_id, job, library):
    job_id = job['job_id']
    configuration = job.get('configuration') or {}
    members = configuration.get('batch_members') or ([configuration] if configuration.get('tester') else [])
    plan_raw, plan = _read(Path(root) / 'packages' / job_id / 'studio-plan.json')
    _, manifest = _read(Path(root) / 'packages' / job_id / 'manifest.json')
    _, sources = _read(Path(root) / 'packages' / (job_id + '.source.json'))
    plan = plan if isinstance(plan, dict) else {}
    refs = plan.get('strategy_refs') if isinstance(plan.get('strategy_refs'), list) else []
    source_members = (sources or {}).get('members') or []
    manifest_jobs = (manifest or {}).get('jobs') or []
    launch = job.get('launch_intent') or {}
    completion = job.get('completion') or {}
    attempt_id = launch.get('attempt_id') or completion.get('attempt_id')
    result_raw, result = (None, None)
    if attempt_id:
        result_raw, result = _read(Path(root) / 'attempts' / attempt_id / 'result.json', MAX_RESULT)
    if not isinstance(result, dict) and completion.get('member_outcomes'):
        result = completion
    gaps_job = []
    retired = completion.get('kind') == 'retired_never_activated' or (result or {}).get('classification') == 'retired_never_started'
    observation = job.get('native_observation') or {}
    in_flight = (not retired and not (result or {}).get('member_outcomes') and attempt_id is not None and (
        job.get('status') in ('running', 'reconcile_required', 'verifying')
        or ((observation.get('dispatch') or {}).get('status') in ('awaiting_receipt', 'receipt_observed'))))
    outcomes = {o.get('index'): o for o in (result or {}).get('member_outcomes') or [] if isinstance(o, dict)}
    no_edge = {o.get('index'): o for o in (result or {}).get('research_outcomes') or [] if isinstance(o, dict)}
    error_lines = [(l or {}).get('line') for l in ((result or {}).get('native_error_evidence') or {}).get('lines') or []
                   if isinstance(l, dict)]
    reports = (result or {}).get('reports')
    native = (plan.get('native_batch') or {})
    evidence = native.get('evidence_end') if isinstance(native.get('evidence_end'), dict) else None
    if evidence and 'ea_setting' in evidence and _day(evidence.get('target')):
        export_end, end_basis = _day(evidence['target']) + timedelta(days=1), 'evidence_end_setting'
    else:
        # The EA ends each export at its own last Friday when it exports: bounded by the
        # last native observation (finish), else the dispatch time.
        live = observation.get('native') if isinstance(observation.get('native'), dict) else {}
        stamp = ((result or {}).get('native') or {}).get('observed_at') or live.get('observed_at') or launch.get('recorded_at')
        export_end, end_basis = (_legacy_end(stamp), 'ea_last_friday_estimate') if stamp else (None, 'unknown')
    started = None
    needs_history = any((o or {}).get('status') == 'native_cancelled' for o in outcomes.values()) or in_flight
    if needs_history:
        started = _history(root, job)
        if in_flight and isinstance(observation.get('native'), dict):
            started = set(started or ()) | {m.get('index') for m in observation['native'].get('members') or []
                                            if isinstance(m, dict) and m.get('status') in STARTED}
    # A retirement adds a result or retired-start file but never a dispatch, so entries of
    # a job that never reached MT5 keep naming its frozen plan (byte-identical journal).
    if result_raw is not None and outcomes and not retired:
        source = dict(kind='attempt-result', sha256=_digest(result_raw))
    else:
        source = dict(kind='batch-plan', sha256=_digest(plan_raw))
    entries = []
    for index, member in enumerate(members):
        tester, export = member.get('tester') or {}, member.get('export') or {}
        values = (member.get('strategy') or {}).get('values')
        outcome_row = outcomes.get(index) or {}
        report = _report_member(reports, index, len(members))
        alias = outcome_row.get('run_alias') or (manifest_jobs[index].get('run_alias') if index < len(manifest_jobs) and isinstance(manifest_jobs[index], dict) else None)
        gaps = list(gaps_job)
        status = outcome_row.get('status')
        if retired:
            dispatched, outcome = False, 'not-dispatched'
        elif not outcomes and not in_flight:
            if isinstance(result, dict):
                # An attempt result without per-member outcomes: never assume it did not run.
                dispatched, outcome = True, 'unknown'
                gaps.append('attempt result has no member outcomes, counted as dispatched')
            else:
                dispatched, outcome = False, 'not-dispatched'
        elif in_flight:
            if started is not None and index in started:
                dispatched, outcome = True, 'running'
            else:
                dispatched, outcome = False, 'not-dispatched'
        elif status == 'native_completed':
            dispatched = True
            count = ((report.get('exports') or {}).get('native_threshold_candidate_count')) if isinstance(report.get('exports'), dict) else None
            outcome = 'no-qualifying-exports' if count == 0 else 'completed'
        elif status == 'native_error':
            dispatched, outcome = True, ('no-edge' if index in no_edge else 'failed')
        elif status == 'native_cancelled':
            if started is None:
                dispatched, outcome = True, 'cancelled'
                gaps.append('member start unknown: no retained native evidence history, counted as dispatched')
            elif index in started:
                dispatched, outcome = True, 'cancelled'
            else:
                dispatched, outcome = False, 'cancelled-before-start'
        elif status is None and result is not None:
            dispatched, outcome = True, 'unknown'
            gaps.append('result has no outcome for this member, counted as dispatched')
        else:
            dispatched, outcome = False, 'not-dispatched'
        start, forward, to = _day(tester.get('FromDate')), _day(tester.get('ForwardDate')), _day(tester.get('ToDate'))
        windows = [w for w in (_window('in-sample', start, forward), _window('forward', forward, to)) if w]
        back = _day(export.get('BackOOSDate'))
        if _truthy(export.get('IncludeBackOOS')) and back and start and back < start:
            windows.append(_window('back-oos', back, start))
        if export_end and to and export_end > to:
            windows.append(_window('front-oos', to, export_end, end_basis=end_basis))
        exposure_start = min([d for d in (start, back) if d] or [None]) if start else None
        exposure_end = max([d for d in (to, export_end) if d] or [None]) if to else None
        if end_basis != 'evidence_end_setting':
            gaps.append('export end ' + ('estimated from the EA last-Friday rule' if export_end else 'unknown'))
        oos_output = None
        if dispatched and outcome not in ('running',):
            oos_output = 'observed' if outcome in ('completed', 'no-qualifying-exports') else \
                _oos_output(report, no_edge.get(index), alias, error_lines)
        elif dispatched:
            oos_output = 'possible'
        declared = refs[index] if index < len(refs) and isinstance(refs[index], dict) else None
        source_member = source_members[index] if index < len(source_members) and isinstance(source_members[index], dict) else {}
        attribution = library.attribute(
            declared=stable(declared) if declared else None, set_sha256=source_member.get('set_sha256'), values=values,
            configuration_sha256=sha(member) if member else None,
            result_sha256s=[source['sha256']] if source['kind'] == 'attempt-result' else (),
            attempt_key=(attempt_id + '-m' + str(index)) if attempt_id else None)
        evidence_row = report.get('evidence') if isinstance(report.get('evidence'), dict) else {}
        entries.append(_entry(
            suite_id, 'optimization', job_id, attempt_id, index, alias, source, attribution,
            variant=variant_id(values) if isinstance(values, dict) else None, set_sha256=source_member.get('set_sha256'),
            input_artifact=(outcome_row.get('input_artifact') or {}).get('sha256'),
            symbol=tester.get('Symbol'), timeframe=tester.get('Period'), model=tester.get('Model'), windows=windows,
            exposure=(exposure_start, exposure_end), dispatched=dispatched, outcome=outcome, oos_output=oos_output,
            candidates=evidence_row.get('paired_rows') if type(evidence_row.get('paired_rows')) is int else None,
            dispatched_at=launch.get('recorded_at') if dispatched else None, gaps=gaps))
    return entries


# ---------------------------------------------------------------------------
# Seed hunts and catch-ups (SeedRunner state)
# ---------------------------------------------------------------------------

def _runner_entries(root, suite_id, folder, kind, library):
    manifest_raw, manifest = _read(folder / 'manifest.json', MAX_RESULT)
    _, state = _read(folder / 'state.json', MAX_RESULT)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('members'), list):
        return [], ['%s %s: manifest unreadable' % (kind, folder.name)]
    states = {m.get('member_id'): m for m in (state or {}).get('members') or [] if isinstance(m, dict)}
    plan = manifest.get('plan') or {}
    reveal = manifest.get('heldout_reveal') if isinstance(manifest.get('heldout_reveal'), dict) else None
    entries = []
    for spec in manifest['members']:
        if not isinstance(spec, dict):
            continue
        item = states.get(spec.get('member_id')) or {}
        tester = spec.get('tester') or {}
        status = item.get('status') or 'pending'
        dispatched = (item.get('attempts') or 0) >= 1 or status in SEED_DISPATCHED
        outcome = {'completed': 'completed', 'failed': 'failed', 'timeout': 'failed', 'missing_output': 'failed',
                   'cancelled': 'cancelled', 'reconcile_required': 'unknown'}.get(status, 'running' if dispatched else 'pending')
        if not dispatched:
            outcome = 'not-dispatched'
        start, to = _day(tester.get('FromDate')), _day(tester.get('ToDate'))
        gaps = []
        result_raw, result = (None, None)
        if isinstance(item.get('result'), dict) and item['result'].get('path'):
            result_raw, result = _read(item['result']['path'], MAX_RESULT)
        if kind == 'seed':
            windows = [w for w in (_window('in-sample', start, to),) if w]
            source = dict(kind='seed-result', sha256=_digest(result_raw)) if result_raw else dict(kind='seed-manifest', sha256=_digest(manifest_raw))
            candidates = None
            oos_output = None
        else:
            new = spec.get('new_window') or {}
            first, last = _day(new.get('first_day')), _day(new.get('last_day'))
            windows = [w for w in (_window('catch-up', first, last + timedelta(days=1) if last else None),) if w]
            if reveal:
                windows = [w for w in (_window('held-out', _day(reveal.get('start')), _day(reveal.get('end')),
                                               lock_id=reveal.get('lock_id')),) if w]
            source = dict(kind='catchup-result', sha256=_digest(result_raw)) if result_raw else dict(kind='catchup-manifest', sha256=_digest(manifest_raw))
            candidates = None
            oos_output = None if not dispatched else ('observed' if status == 'completed' else 'possible')
        if status == 'reconcile_required':
            gaps.append('member settles by reconcile; counted as dispatched')
        raw, values = None, spec.get('values')
        if not isinstance(values, dict):
            raw = None
            for candidate in (spec.get('set_path'), (spec.get('original') or {}).get('set_path')):
                try:
                    if candidate and Path(candidate).is_file() and Path(candidate).stat().st_size <= 4 * 1024 * 1024:
                        raw = Path(candidate).read_bytes()
                        break
                except OSError:
                    continue
            try:
                values = set_values(raw) if raw is not None else None
            except (ValueError, UnicodeError):
                values = None
            if values is None:
                gaps.append('frozen SET unreadable: variant unknown')
        declared = spec.get('strategy_ref') if isinstance(spec.get('strategy_ref'), dict) else None
        attribution = library.attribute(declared=stable(declared) if declared else None, set_sha256=spec.get('source_sha256'),
                                        values=values)
        alias = spec.get('alias')
        entries.append(_entry(
            suite_id, 'seed' if kind == 'seed' else ('held-out-reveal' if reveal else 'catch-up'), manifest.get('batch_id') or folder.name,
            (manifest.get('batch_id') or folder.name) + '-' + str(alias), spec.get('index'), alias, source, attribution,
            variant=variant_id(values) if isinstance(values, dict) else None, set_sha256=spec.get('source_sha256'),
            input_artifact=spec.get('set_sha256'), symbol=tester.get('Symbol'), timeframe=tester.get('Period'),
            model=tester.get('Model'), windows=windows, exposure=(start, to), dispatched=dispatched, outcome=outcome,
            oos_output=oos_output, candidates=candidates, dispatched_at=_unix_iso(item.get('started_unix')) if dispatched else None,
            gaps=gaps, in_sample_candidates=((result or {}).get('summary') or {}).get('actual_frames') if kind == 'seed' else None))
    return entries, []


def _entry(suite_id, kind, batch_id, attempt_id, index, alias, source, attribution, *, variant, set_sha256, input_artifact,
           symbol, timeframe, model, windows, exposure, dispatched, outcome, oos_output, candidates, dispatched_at, gaps,
           in_sample_candidates=None):
    oos = [w for w in windows if w['role'] in OOS_ROLES]
    peek = bool(dispatched and oos and oos_output != 'proven_absent')
    ref = {key: attribution.get(key) for key in ('strategy_key', 'template_id', 'template_revision', 'template_sha256', 'catalog_revision')}
    return dict(
        entry_id=hashlib.sha256(canonical([SCHEMA, suite_id, kind, batch_id, index]).encode('utf-8')).hexdigest(),
        suite_id=suite_id, kind=kind, source=source, batch_id=batch_id, attempt_id=attempt_id, member_index=index,
        attempt_key=(attempt_id + '-m' + str(index)) if kind == 'optimization' and attempt_id else attempt_id,
        run_alias=alias, strategy_ref=ref if ref['strategy_key'] else None, attribution=attribution.get('attribution'),
        strategy_keys=attribution.get('keys') or [], variant_id=variant, set_sha256=set_sha256,
        input_artifact_sha256=input_artifact, symbol=symbol, timeframe=timeframe, model=model, windows=windows,
        exposure=dict(start=_iso(exposure[0]), end=None if exposure[1] == date.max else _iso(exposure[1])),
        dispatched=bool(dispatched), dispatched_at=dispatched_at, outcome=outcome, oos_output=oos_output,
        counts_as_peek=peek, optimizer_candidates_seen=candidates, in_sample_candidates_seen=in_sample_candidates,
        gaps=sorted(set(gaps)))


# ---------------------------------------------------------------------------
# Public reads
# ---------------------------------------------------------------------------

def entries_for(root, install, *, library=None):
    root = Path(root)
    library = library or Library.for_install(install)
    suite_id = root.name
    gaps, entries = [], []
    jobs, problems = queue_rows(root)
    gaps.extend(problems)
    for job in jobs:
        try:
            entries.extend(_native_entries(root, suite_id, job, library))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            gaps.append('batch %s unreadable: %s' % (job.get('job_id'), exc))
    for kind, name in (('seed', 'seeds'), ('catchup', 'catchups')):
        base = root / name
        for folder in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            found, problems = _runner_entries(root, suite_id, folder, kind, library)
            entries.extend(found)
            gaps.extend(problems)
    order = dict(optimization=0, seed=1, **{'catch-up': 2, 'held-out-reveal': 3})
    entries.sort(key=lambda e: (order.get(e['kind'], 9), e['batch_id'] or '', e['member_index'] if type(e['member_index']) is int else -1))
    return entries, gaps


def _matches(entry, strategy):
    return strategy is None or strategy in entry['strategy_keys'] or entry['attribution'] == 'unattributed'


def journal(root, install, *, since=None, strategy=None, library=None):
    """``trial-journal [--since] [--strategy]``: entries plus a digest of exactly those entries."""
    entries, gaps = entries_for(root, install, library=library)
    if since:
        entries = [e for e in entries if not e['dispatched'] or (e['dispatched_at'] or '') >= since]
    entries = [e for e in entries if _matches(e, strategy)]
    dispatched = [e['dispatched_at'] for e in entries if e['dispatched_at']]
    coverage = dict(suite_id=Path(root).name, entries=len(entries), dispatched=sum(e['dispatched'] for e in entries),
                    first_dispatch_at=min(dispatched) if dispatched else None, last_dispatch_at=max(dispatched) if dispatched else None,
                    sources=sorted({e['source']['kind'] for e in entries}))
    return dict(schema=SCHEMA, capability=CAPABILITY, suite_id=Path(root).name, filter=dict(since=since, strategy=strategy),
                entries=entries, digest=hashlib.sha256(canonical(entries).encode('utf-8')).hexdigest(),
                journal_coverage=coverage, gaps=sorted(set(gaps)))


def _intersects(window, start, end):
    return overlaps(date.fromisoformat(window['start']), date.fromisoformat(window['end']), start, end)


def count(root, install, strategy, *, window=None, library=None):
    """``trial-count --strategy KEY [--window-start --window-end]`` for this suite (spec §5)."""
    entries, gaps = entries_for(root, install, library=library)
    mine = [e for e in entries if strategy in e['strategy_keys']]
    loose = [e for e in entries if e['attribution'] == 'unattributed' and e['counts_as_peek']]
    peeks = [e for e in mine if e['counts_as_peek']]
    if window is not None:
        start, end = window
        peeks = [e for e in peeks if any(_intersects(w, start, end) for w in e['windows'] if w['role'] in OOS_ROLES)]
    distinct = {}
    for entry in peeks:
        for item in entry['windows']:
            if item['role'] in OOS_ROLES and (window is None or _intersects(item, *window)):
                distinct.setdefault((item['start'], item['end']), None)
    if window is not None:
        distinct = {(window[0].isoformat(), window[1].isoformat()): None}
    rows = []
    for (start_text, end_text) in sorted(distinct):
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        hits = [e for e in mine if e['counts_as_peek'] and any(_intersects(w, start, end) for w in e['windows'] if w['role'] in OOS_ROLES)]
        symbols = {e['symbol'] for e in mine} | {e['symbol'] for e in loose}
        blind = [e for e in loose if any(_intersects(w, start, end) for w in e['windows'] if w['role'] in OOS_ROLES)]
        row_gaps = sorted({'%d unattributed dispatched member(s) on %s overlap this window' % (
            sum(b['symbol'] == symbol for b in blind), symbol) for symbol in sorted(s for s in symbols if s)
            if any(b['symbol'] == symbol for b in blind)})
        reconstructable = not blind
        rows.append(dict(start=start_text, end=end_text, peeks=len(hits), variants=len({e['variant_id'] for e in hits if e['variant_id']}),
                         optimizer_candidates_seen=sum(e['optimizer_candidates_seen'] or 0 for e in hits),
                         optimizer_candidates_unknown=sum(e['optimizer_candidates_seen'] is None and e['kind'] == 'optimization' for e in hits),
                         reconstructable=reconstructable, worst_case=not reconstructable, gaps=row_gaps,
                         **({} if reconstructable else dict(worst_case_rule=WORST_CASE))))
    cells = {}
    for entry in mine + loose:
        key = (entry['symbol'], entry['timeframe'])
        cell = cells.setdefault(key, dict(symbol=key[0], timeframe=key[1], peeks=0, variants=set(), not_dispatched=0,
                                          optimizer_candidates_seen=0, reconstructable=True))
        if entry in loose:
            cell['reconstructable'] = False
            continue
        if entry in peeks:
            cell['peeks'] += 1
            if entry['variant_id']:
                cell['variants'].add(entry['variant_id'])
            cell['optimizer_candidates_seen'] += entry['optimizer_candidates_seen'] or 0
        if not entry['dispatched']:
            cell['not_dispatched'] += 1
    cell_rows = [dict(value, variants=len(value['variants'])) for _, value in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))]
    reconstructable = all(r['reconstructable'] for r in rows)
    exposure = [e['exposure']['end'] for e in mine + [x for x in entries if x['attribution'] == 'unattributed']
                if e['dispatched'] and e['exposure']['end']]
    open_ended = [e for e in mine if e['dispatched'] and e['exposure']['start'] and e['exposure']['end'] is None]
    return dict(schema=COUNT_SCHEMA, capability=CAPABILITY, suite_id=Path(root).name, strategy_key=strategy,
                window=None if window is None else dict(start=window[0].isoformat(), end=window[1].isoformat()),
                strategy=dict(peeks=len(peeks), variants=len({e['variant_id'] for e in peeks if e['variant_id']}),
                              optimizer_candidates_seen=sum(e['optimizer_candidates_seen'] or 0 for e in peeks),
                              not_dispatched=sum(not e['dispatched'] for e in mine)),
                cells=cell_rows, windows=rows, reconstructable=reconstructable, worst_case=not reconstructable,
                worst_case_rule=WORST_CASE, exposure_end=max(exposure) if exposure else None,
                exposure_open_ended=len(open_ended), gaps=sorted(set(gaps)),
                journal_coverage=dict(suite_id=Path(root).name, entries=len(entries),
                                      attributed_to_key=len(mine), unattributed_dispatched=len(loose)),
                plain=_plain(strategy, peeks, rows))


def _plain(strategy, peeks, rows):
    worst = sum(not r['reconstructable'] for r in rows)
    text = '%s: %d OOS peek%s from %d variant%s on this PC.' % (
        strategy, len(peeks), '' if len(peeks) == 1 else 's', len({e['variant_id'] for e in peeks if e['variant_id']}),
        '' if len({e['variant_id'] for e in peeks if e['variant_id']}) == 1 else 's')
    if worst:
        text += (' %d window%s cannot be reconstructed (unattributed members overlap), so a scorer uses the worst case '
                 '(%d per window) there; phase 1 applies no penalty.' % (worst, '' if worst == 1 else 's', WORST_CASE['trial_worst_case_n']))
    return text
