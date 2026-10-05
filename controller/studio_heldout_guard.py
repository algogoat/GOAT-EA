"""Held-out lock enforcement points and output redaction (goatai#2221 §4.3, acceptance #4).

Enforcement: ``prepare-batch`` (and every path through ``studio_batch.read_plan``:
load-batch, resume-batch, batch-resume, batch-continue), ``seed-prepare``,
``catchup-validate``/``catchup-prepare``, and again at every start (``run-batch``,
``start``, the /config start, ``seed-start`` and ``catchup-start`` before each
member launch) refuse a member whose data span overlaps an active lock of its
strategy, unless the plan is that lock's reveal.

Redaction: every reply the CLIs print passes ``guard_output``. While a lock is
active, any part of a reply that describes a run or export whose span overlaps a
lock of its strategy (an unattributed one: any lock) loses every value derived from
it: metrics, verdicts, qualifying counts, research outcomes, plain sentences, log
lines, and the metric tokens in export, seed and combiner file names
(``_Prf=1990`` becomes ``_Prf=locked``). The value becomes
``{locked: true, lock_id, reveal_after, plain}`` and the reply lists
``locked_windows``. When the registry cannot be verified, every such value in every
reply is redacted. With no active lock a reply is returned unchanged.
"""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing

from campaign_ledger import sha
from studio_heldout import (HeldOutRefused, LOCKED, PLAN_MISMATCH, UNAVAILABLE, active_locks, canonical, enforce, iso_day, legacy_export_end,
                            member_span, native_export_end, overlaps, public_window, read_registry, reveal_lock, window)
from studio_strategy_attribution import Library, set_values, stable, suggestion, validate_ref

# Keys whose value is derived from a member's tested window: replaced whole.
METRIC_KEYS = frozenset((
    'metrics', 'native_filename_metrics', 'threshold', 'threshold_passing', 'export_thresholds', 'equity_samples',
    'research_outcomes', 'member_outcomes', 'outcome', 'best_profit', 'best_score', 'best_fitness', 'best_combined_score',
    'best', 'top_score', 'TopScore', 'score', 'qualifying', 'qualifying_count', 'qualifying_candidates', 'qualifies',
    'exported_sets', 'native_threshold_candidate_count', 'qualified_count', 'held_up', 'verdict', 'verdicts', 'confidence',
    'net', 'realized', 'dd', 'dd_pct', 'pf', 'sr', 'arf', 'profit', 'pl', 'trades', 'signals', 'new_weeks', 'forward_pace',
    'prior_dd', 'reproduction', 'original_foos', 'windows', 'catch_up', 'qualification', 'candidates', 'candidate_values',
    'seed_metrics', 'seed_qualifies', 'average_fitness', 'health_percent', 'zero_trade_count', 'average_trades',
    'actual_frames', 'no_edge', 'members_no_edge', 'no_edge_window', 'counts', 'comparability', 'comparable', 'reproduced',
    'passes', 'profitable', 'traded', 'forward_rows', 'back_rows', 'paired_rows', 'actual_back_report_rows',
    'actual_forward_report_rows', 'matching_pass_ids', 'performance_qualification', 'export_qualification',
    # Hold-up test results (studio_holdup): MT5 report figures, weekly/daily realised P/L, split segments, deals.
    'per_week', 'daily', 'segments', 'deals',
    # Export qualification (studio_export_qualification): pass/fail per set and per member, the metric values
    # each check read and which thresholds a set missed are all derived from the tested window.
    'passing_sets', 'below_threshold_members', 'below_threshold_sets', 'unknown_members', 'unknown_sets',
    'checks', 'missed', 'ea_native_passed', 'log_crosscheck', 'stamps', 'unproven_members'))
# Sentences and log lines that quote such values: replaced whole inside a locked part.
SENTENCE_KEYS = frozenset(('plain', 'summary', 'headline', 'reasons', 'sentence', 'line', 'note', 'title'))
METRIC_STATUSES = frozenset(('native_threshold_candidate', 'below_native_thresholds', 'native_threshold_unknown',
                             'held_up', 'weakened', 'too_few_trades'))
RUN_KEYS = ('job_id', 'batch_id', 'catchup_id', 'holdup_id')
PATH_KEYS = ('set_path', 'original_set', 'version_set_path', 'xml_path')

_TOKENS = (
    (re.compile(r'(?<![A-Za-z])(Trds|Prf|DD|PF|RF|SR|ARF|AvgFit|Health|Zero|AvgTrades|Best|Score|Return|MonthlyRet|Trades)'
                r'=-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'), r'\1=locked'),
    (re.compile(r'(best(?:_combined)?(?:[ _]profit|[ _]score)?[ =:]+)-?\d[\d.,]*', re.IGNORECASE), r'\1[locked]'),
    (re.compile(r'(\bPL=)-?\d[\d.]*'), r'\1locked'),
    (re.compile(r'(Found rows = )\d+'), r'\1[locked]'),
)


def scrub(text):
    """Metric tokens out of a string (file names, log lines, sentences)."""
    for pattern, replacement in _TOKENS:
        text = pattern.sub(replacement, text)
    return text


def marker(lock=None):
    if lock is None:
        return dict(locked=True, lock_id=None, reveal_after=None, code=UNAVAILABLE,
                    plain='Redacted: the held-out lock registry cannot be verified, so no tested value is shown.')
    return dict(locked=True, lock_id=lock['lock_id'], reveal_after=lock['reveal_after'], plain=lock['plain'])


# ---------------------------------------------------------------------------
# Members of a plan, for enforcement
# ---------------------------------------------------------------------------

class Context:
    """One verified registry read plus the run/export facts a reply refers to."""

    def __init__(self, install, root=None, *, now=None, registry=None):
        self.install, self.root, self.now = install, Path(root or install['controller_state_root']), now
        self.registry = registry or read_registry(install, now=now)
        self.active = active_locks(self.registry) if self.registry['state'] != 'unavailable' else []
        self._library, self._runs, self._exports = None, {}, {}

    @property
    def library(self):
        if self._library is None:
            self._library = Library.for_install(self.install)
        return self._library

    def touches(self, span):
        """Does this span overlap any active lock (an unknown span: assume it does)?"""
        return span is None or any(overlaps(span['start'], span['end'], *window(lock)) for lock in self.active)

    def member(self, label, span, declared, *, set_sha256=None, values=None, reveal=False, symbol=None, timeframe=None):
        # Attribution reads the desktop library: only for a member that could meet a lock.
        if self.touches(span):
            attribution = self.library.attribute(declared=declared, set_sha256=set_sha256, values=values)
        else:
            attribution = dict(attribution='declared' if declared else 'unattributed',
                               keys=[] if declared is None else [declared['strategy_key']])
        keys = list(attribution.get('keys') or [])
        return dict(label=label, span=span, declared=declared, keys=keys, reveal=reveal, symbol=symbol, timeframe=timeframe,
                    set_sha256=set_sha256, suggestion=suggestion(attribution) if declared is None else None,
                    attribution=attribution.get('attribution'))


def _registry_or_refuse(context):
    if context.registry['state'] == 'unavailable':
        raise HeldOutRefused(UNAVAILABLE, 'The held-out lock registry cannot be verified (%s), so nothing may be prepared or '
                             'started until the desktop repairs it.' % context.registry['error'])


def check_batch_plan(controller, spec, config, retained, *, evidence=None, now=None):
    """prepare-batch (via read_plan): members with optional strategy_ref, before anything is written."""
    refs = [validate_ref(m.get('strategy_ref'), 'Member %d' % (i + 1)) for i, m in enumerate(spec['members'])]
    context = Context(controller.install, controller.root, now=now)
    _registry_or_refuse(context)
    if not context.active:
        return refs
    export_end, open_end = native_export_end(dict(evidence_end=evidence) if evidence else None)
    members = []
    for index, (member, (_, raw, info)) in enumerate(zip(config['batch_members'], retained)):
        tester = member['tester']
        span = member_span(tester, back_oos_date=member['export'].get('BackOOSDate'), export_end=export_end, open_end=open_end)
        members.append(context.member('%d (%s %s)' % (index + 1, tester.get('Symbol'), tester.get('Period')), span, refs[index],
                                      set_sha256=info['sha256'], values=member['strategy']['values']))
    enforce(controller.install, members, registry=context.registry)
    return refs


def _plan_members(context, plan, *, export_bound=None):
    """Members of a frozen native plan. ``export_bound`` closes the open export end of an EA
    build without EvidenceEnd once the run's exports exist (redaction only, never a start)."""
    native = plan.get('native_batch') or {}
    export_end, open_end = native_export_end(native)
    if open_end and export_bound is not None:
        export_end, open_end = export_bound, False
    refs = plan.get('strategy_refs') if isinstance(plan.get('strategy_refs'), list) else []
    members = []
    for index, job in enumerate(plan.get('jobs') or []):
        conditions = job.get('conditions') or {}
        tester = dict(FromDate=conditions.get('from_date'), ToDate=conditions.get('to_date'))
        span = member_span(tester, back_oos_date=native.get('back_oos_date'), export_end=export_end, open_end=open_end)
        declared = refs[index] if index < len(refs) and isinstance(refs[index], dict) else None
        members.append(context.member('%d (%s %s)' % (index + 1, job.get('symbol'), conditions.get('timeframe')), span,
                                      stable(declared) if declared else None, set_sha256=job.get('source_sha256')))
    return members


def hashed_plan(root, job_id):
    """The frozen plan a start may trust: ``studio-plan.json`` exactly as its manifest
    hashed it at prepare (``campaign_id = sha(plan)``). Returns None when either file is
    missing or unreadable; refuses when the plan no longer matches its manifest, so an
    edited ``strategy_ref`` can never move a member out from under a lock."""
    package = Path(root) / 'packages' / job_id
    plan, manifest = _json_file(package / 'studio-plan.json'), _json_file(package / 'manifest.json')
    if not isinstance(plan, dict) or not isinstance(manifest, dict):
        return None
    if manifest.get('campaign_id') != sha(plan):
        raise HeldOutRefused(PLAN_MISMATCH, 'Prepared batch installation or plan identity changed: batch %s\'s frozen plan '
                             'no longer matches the hash its manifest recorded at prepare, so its strategy_ref and dates '
                             'cannot be trusted. Nothing was started; prepare the plan again under a new batch ID.' % job_id)
    return plan


def check_native_start(controller, job_id, *, now=None):
    """run-batch / start / config start: re-check the frozen plan (a lock declared after prepare
    refuses it). Its dates and strategy_ref are read only through the manifest hash: an edited
    plan is refused here. With no active lock nothing here reads the plan; the package check
    that follows (``_verify_package``) refuses the same mismatch before any journal."""
    context = Context(controller.install, controller.root, now=now)
    _registry_or_refuse(context)
    if not context.active:
        return None
    plan = hashed_plan(controller.root, job_id)
    if not isinstance(plan, dict):
        members = [dict(label='(frozen plan unreadable)', span=None, declared=None, keys=[], reveal=False)]
    else:
        members = _plan_members(context, plan)
    return enforce(controller.install, members, registry=context.registry)


def _runner_members(context, manifest):
    reveal = manifest.get('heldout_reveal') if isinstance(manifest.get('heldout_reveal'), dict) else None
    members = []
    for spec in manifest.get('members') or []:
        tester = spec.get('tester') or {}
        declared = spec.get('strategy_ref') if isinstance(spec.get('strategy_ref'), dict) else None
        members.append(context.member('%s (%s %s)' % (spec.get('alias'), tester.get('Symbol'), tester.get('Period')),
                                      member_span(tester), stable(declared) if declared else None,
                                      set_sha256=spec.get('source_sha256'), values=spec.get('values'),
                                      reveal=reveal is not None, symbol=tester.get('Symbol'), timeframe=tester.get('Period')))
    return members, (reveal or {}).get('lock_id')


def check_runner_start(controller, manifest, spec=None, *, now=None):
    """seed-start / catchup-start: before activation (``spec`` None) and before each
    member launch (``spec`` = that member). A reveal must still be its lock's reveal."""
    context = Context(controller.install, controller.root, now=now)
    _registry_or_refuse(context)
    if not context.active:
        return None
    members, reveal_id = _runner_members(context, manifest)
    if reveal_id:
        reveal_lock(controller.install, reveal_id, members, registry=context.registry)
    if spec is not None:
        members = [m for m, s in zip(members, manifest.get('members') or []) if s.get('member_id') == spec.get('member_id')]
    return enforce(controller.install, members, reveal_lock_id=reveal_id, registry=context.registry)


def check_seed_jobs(controller, plan, members, *, now=None):
    """seed-prepare / seed validate: frozen members in memory, before any write."""
    context = Context(controller.install, controller.root, now=now)
    _registry_or_refuse(context)
    if not context.active:
        return
    view = [context.member('%s (%s %s)' % (m['alias'], m['tester']['Symbol'], m['tester']['Period']), member_span(m['tester']),
                           m.get('strategy_ref'), set_sha256=m['source_sha256'], values=m.get('values')) for m in members]
    enforce(controller.install, view, registry=context.registry)


def check_catchup(controller, plan, members, target, *, now=None):
    """catchup-validate / catchup-prepare: members in memory, before any write. A plan with
    ``heldout_reveal`` must be that lock's reveal of its frozen candidate."""
    context = Context(controller.install, controller.root, now=now)
    reveal = plan.get('heldout_reveal')
    if reveal is None:
        _registry_or_refuse(context)
        if not context.active:
            return None
    view = [context.member('%s (%s %s)' % (m['alias'], m['tester']['Symbol'], m['tester']['Period']), member_span(m['tester']),
                           m.get('strategy_ref'), set_sha256=m['source_sha256'], reveal=reveal is not None,
                           symbol=m['tester']['Symbol'], timeframe=m['tester']['Period']) for m in members]
    lock = None
    if reveal is not None:
        if not isinstance(reveal, dict) or set(reveal) != {'lock_id'}:
            raise HeldOutRefused('HELDOUT_REVEAL_MISMATCH', 'heldout_reveal is {lock_id} of the lock being revealed.')
        lock = reveal_lock(controller.install, reveal['lock_id'], view, evidence_end=target['iso'], registry=context.registry)
    enforce(controller.install, view, reveal_lock_id=lock and lock['lock_id'], registry=context.registry)
    return lock and dict(lock_id=lock['lock_id'], strategy_key=lock['strategy_key'], start=lock['start'], end=lock['end'])


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def _json_file(path, limit=512 * 1024 * 1024):
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > limit:
            return None
        raw = path.read_bytes()
        return json.loads(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None


def _run_members(context, run_id):
    """Exposure of a native batch, seed hunt or catch-up named in a reply; None when unknown."""
    if run_id in context._runs:
        return context._runs[run_id]
    members = None
    if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id or ''):
        try:
            plan = hashed_plan(context.root, run_id)
        except HeldOutRefused:
            plan = False        # an edited plan is unknown: locked while any lock is active
        if plan is False:
            pass
        elif isinstance(plan, dict):
            bound = None
            if native_export_end(plan.get('native_batch'))[1]:
                bound = _export_bound(context, run_id)
            members = [] if bound == 'nothing-ran' else _plan_members(context, plan, export_bound=bound)
            if not plan.get('strategy_refs') and any(context.touches(m['span']) for m in members):
                # A legacy plan that meets a lock: attribute from the frozen member values
                # (fingerprint) too, read from the queue row only in this rare case.
                sources = (_json_file(context.root / 'packages' / (run_id + '.source.json')) or {}).get('members') or []
                values = _queue_values(context, run_id)
                for index, member in enumerate(members):
                    if not context.touches(member['span']) or member['keys']:
                        continue
                    source = sources[index] if index < len(sources) and isinstance(sources[index], dict) else {}
                    attribution = context.library.attribute(set_sha256=source.get('set_sha256') or None,
                                                            values=values[index] if index < len(values) else None)
                    member['keys'] = list(attribution.get('keys') or [])
        else:
            for folder in ('seeds', 'catchups', 'holdups'):
                manifest = _json_file(context.root / folder / run_id / 'manifest.json')
                if isinstance(manifest, dict):
                    members, _ = _runner_members(context, manifest)
                    reveal = manifest.get('heldout_reveal')
                    for member in members:
                        member['reveal_lock_id'] = (reveal or {}).get('lock_id')
                    break
    context._runs[run_id] = members
    return members


def _export_bound(context, job_id):
    """What a run without EvidenceEnd can have exported so far: nothing before it started,
    its last Friday when it finished, else the last Friday now (a reply holds no later value)."""
    row = _queue_job(context, job_id)
    if row is not None:
        completion = row.get('completion') or {}
        if ('launch_intent' not in row or completion.get('kind') == 'retired_never_activated'
                or completion.get('classification') == 'retired_never_started'):
            return 'nothing-ran'
        if row.get('status') in ('completed', 'cancelled', 'failed'):
            stamp = (completion.get('native') or {}).get('observed_at')
            if stamp:
                return legacy_export_end(stamp) or legacy_export_end(context.now)
    return legacy_export_end(context.now)


def _queue_job(context, job_id):
    _queue_values(context, job_id)
    return context._queue.get(job_id)


def _queue_values(context, job_id):
    if not hasattr(context, '_queue'):
        context._queue = {}
        database = context.root / 'studio.sqlite'
        try:
            if database.is_file():
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                    for (text,) in db.execute('SELECT jobs FROM studio_queues'):
                        for job in json.loads(text) or []:
                            if isinstance(job, dict) and isinstance(job.get('job_id'), str):
                                context._queue.setdefault(job['job_id'], job)
        except (sqlite3.Error, ValueError):
            context._queue = {}
    job = context._queue.get(job_id) or {}
    configuration = job.get('configuration') or {}
    members = configuration.get('batch_members') or ([configuration] if configuration else [])
    return [(m.get('strategy') or {}).get('values') for m in members]


def _export_members(context, set_path, span=None):
    if span is not None and not context.touches(span):
        return [dict(label=Path(set_path).name, span=span, declared=None, keys=[], reveal=False)]
    if set_path in context._exports:
        return context._exports[set_path]
    members = None
    try:
        from studio_evidence import read_export
        export = read_export(set_path)
        start, end = iso_day(export.get('evidence_start')), iso_day(export.get('evidence_end'))
        span = dict(start=start, end=end + timedelta(days=1), open_end=False) if start and end else None
        raw = Path(set_path).read_bytes()
        attribution = context.library.attribute(set_sha256=export.get('set_sha256'), values=set_values(raw))
        if attribution['attribution'] == 'unattributed':
            attribution = _export_fingerprint(context, set_values(raw)) or attribution
        members = [dict(label=Path(set_path).name, span=span, declared=None, keys=list(attribution.get('keys') or []), reveal=False)]
    except (OSError, ValueError, UnicodeError, KeyError, TypeError):
        members = None
    context._exports[set_path] = members
    return members


def _export_fingerprint(context, values):
    """An export has no axes: match a template whose non-axis values it keeps exactly and
    whose axis names it has. Exactly one key, or nothing."""
    from studio_strategy_attribution import _split
    library = context.library.load()
    if not hasattr(library, '_templates'):
        library._templates = []
        for root in library.roots:
            for path in sorted((root / 'revisions').glob('*/catalog.json')) if (root / 'revisions').is_dir() else []:
                catalog = _json_file(path, 8 * 1024 * 1024) or {}
                for template in catalog.get('templates') or []:
                    try:
                        raw = (path.parent / template['file']).read_bytes()
                        axes, fixed = _split(set_values(raw))
                        library._templates.append((template['id'], set(axes), fixed))
                    except (OSError, KeyError, TypeError, ValueError, UnicodeError):
                        continue
    _, exported = _split(values)
    keys = {library.key(tid) for tid, axes, fixed in library._templates
            if axes <= set(exported) and all(exported.get(k) == v for k, v in fixed.items() if k not in axes)}
    return dict(attribution='fingerprint', keys=sorted(keys)) if len(keys) == 1 else None


def _lock_for(context, members):
    """The first active lock a part's members overlap (any lock for unattributed ones)."""
    if members is None:
        return context.active[0] if context.active else None
    for member in members:
        for lock in context.active:
            start, end = window(lock)
            span = member.get('span')
            if span is not None and not overlaps(span['start'], span['end'], start, end):
                continue
            if member.get('reveal_lock_id') == lock['lock_id'] and lock['status'] in ('revealing', 'revealed'):
                continue
            if not member.get('keys') or lock['strategy_key'] in member['keys']:
                return lock
    return None


def _identity_lock(context, node):
    for key in RUN_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value:
            return True, _lock_for(context, _run_members(context, value))
    for key in PATH_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value.lower().endswith('.set') and Path(value).is_absolute():
            return True, _lock_for(context, _export_members(context, value, _node_span(node)))
    return False, None


def _node_span(node):
    """Days an export row speaks for: its own window, plus any catch-up version it reports
    (``effective_end``; a refused earlier attempt's window is open-ended)."""
    start = iso_day(node.get('evidence_start'))
    ends = [d for d in (iso_day(node.get('evidence_end')), iso_day(node.get('effective_end'))) if d]
    if start is None or not ends:
        return None
    if node.get('previous_attempt') or node.get('version_path'):
        return dict(start=start, end=date.max)
    return dict(start=start, end=max(ends) + timedelta(days=1))


def _redact(node, lock, found):
    """Replace every derived value under a locked part; scrub its strings."""
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in METRIC_KEYS or (key in SENTENCE_KEYS and value is not None and not isinstance(value, bool)):
                result[key] = marker(lock)
            elif key == 'status' and isinstance(value, str) and value in METRIC_STATUSES:
                result[key] = marker(lock)
            else:
                result[key] = _redact(value, lock, found)
        return result
    if isinstance(node, list):
        return [_redact(item, lock, found) for item in node]
    if isinstance(node, str):
        return scrub(node)
    return node


def _walk(context, node, found):
    if isinstance(node, dict):
        identified, lock = _identity_lock(context, node)
        if identified and lock is not None:
            found.setdefault(lock['lock_id'], lock)
            return _redact(node, lock, found)
        return {key: _walk(context, value, found) for key, value in node.items()}
    if isinstance(node, list):
        return [_walk(context, item, found) for item in node]
    return node


def _scrub_all(node):
    if isinstance(node, dict):
        return {key: _scrub_all(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub_all(item) for item in node]
    return scrub(node) if isinstance(node, str) else node


def _unverified(result, error):
    """Every derived value redacted: the locks could not be checked, so any part may be locked."""
    redacted = _redact(result, None, {})
    if isinstance(redacted, dict):
        redacted['heldout'] = dict(redacted=True, code=UNAVAILABLE, plain=marker()['plain'], error=error)
        redacted['locked_windows'] = []
    return redacted


def require_no_active_lock(install, *, command, root=None, now=None):
    """For a command whose reply aggregates every export on this PC (gate-recommend, gate-stamp).

    Its numbers (survival curves, recommended gates, a stamped plan) cannot be attributed to one strategy
    or window, so no part of it can be redacted selectively. It runs only when the registry verifies and
    no held-out lock is active; otherwise it refuses before reading or writing anything."""
    try:
        context = Context(install, root, now=now)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise HeldOutRefused(UNAVAILABLE, '%s cannot check the held-out locks (%s), so it does not run.'
                             % (command, str(error)[:200] or type(error).__name__))
    _registry_or_refuse(context)
    if context.active:
        raise HeldOutRefused(LOCKED, '%s reads every export on this PC and cannot tell which ones fall in a held-out window, so it does '
                             'not run while %d held-out lock(s) are active: %s' % (command, len(context.active),
                                                                                  ' '.join(l['plain'] for l in context.active)),
                             [public_window(l) for l in context.active])
    return context


def guard_output(install, result, *, root=None, now=None, context=None):
    """The reply an agent may see. Unchanged when no lock is active."""
    try:
        context = context or Context(install, root, now=now)
    except (KeyError, TypeError, ValueError, OSError) as error:
        # Fail closed (Claude-Mac, goatai#1885): without a context nothing can say which parts are locked,
        # so the reply is redacted exactly as when the registry cannot be verified. It used to pass unchanged.
        return _unverified(result, 'the held-out guard could not start: %s' % (str(error)[:200] or type(error).__name__))
    if context.registry['state'] == 'unavailable':
        return _unverified(result, context.registry['error'])
    if not context.active:
        return result
    found = {}
    try:
        redacted = _walk(context, result, found)
    except Exception:   # a guard defect must fail closed, never leak: redact the whole reply
        lock = context.active[0]
        found = {lock['lock_id']: lock}
        redacted = _redact(result, lock, found)
    if not found:
        return result
    redacted = _scrub_all(redacted)
    if isinstance(redacted, dict):
        redacted['locked_windows'] = [public_window(l) for l in found.values()]
        redacted['heldout'] = dict(redacted=True, plain=' '.join(l['plain'] for l in found.values())
                                   + ' Locked values are neither missing data nor a failure; never work around them.')
    return redacted


def run_locks(install, root, run_id, *, now=None):
    """research-status: the active locks of the current batch's strategies (all of them when
    the batch names none, since an unattributed member counts against every lock)."""
    context = Context(install, root, now=now)
    state = context.registry['state']
    if state == 'unavailable':
        return dict(registry=state, active_locks=[], plain='The held-out lock registry cannot be verified (%s): nothing may be '
                    'prepared or started and every tested value is redacted.' % context.registry['error'])
    members = _run_members(context, run_id) if isinstance(run_id, str) and run_id else None
    keys = set()
    for member in members or []:
        keys.update(member.get('keys') or [])
    unattributed = members is None or any(not member.get('keys') for member in members)
    locks = [public_window(l) for l in context.active if unattributed or l['strategy_key'] in keys]
    plain = (' '.join(l['plain'] for l in locks) + ' Locked is neither missing data nor a failure; never work around it.'
             if locks else 'No held-out lock binds this activity.')
    return dict(registry=state, active_locks=locks, plain=plain)


TRIAL_RESULT_KEYS =('outcome', 'oos_output', 'optimizer_candidates_seen', 'in_sample_candidates_seen')


def guard_trial_journal(install, result, *, root=None, now=None):
    """trial-journal keeps every entry's dates and dispatch facts (the counter needs them),
    but the outcome of an entry whose exposure overlaps a lock it may belong to is redacted."""
    context = Context(install, root, now=now)
    unavailable = context.registry['state'] == 'unavailable'
    if not unavailable and not context.active:
        return result
    found = {}
    for entry in result.get('entries') or []:
        lock = None
        if not unavailable:
            exposure = entry.get('exposure') or {}
            start, end = iso_day(exposure.get('start')), iso_day(exposure.get('end'))
            span = dict(start=start, end=end or date.max) if start else None
            lock = _lock_for(context, [dict(span=span, keys=entry.get('strategy_keys') or [])])
            if lock is None:
                continue
            found.setdefault(lock['lock_id'], lock)
        for key in TRIAL_RESULT_KEYS:
            if key in entry:
                entry[key] = marker(lock)
    if unavailable:
        result['heldout'] = dict(redacted=True, code=UNAVAILABLE, plain=marker()['plain'])
    elif found:
        result['locked_windows'] = [public_window(l) for l in found.values()]
    if unavailable or found:
        # The digest covers what is shown: a digest of the hidden outcomes could be brute-forced.
        result['digest'] = hashlib.sha256(canonical(result.get('entries') or []).encode('utf-8')).hexdigest()
    return result


def guard_error(install, text, *, root=None, now=None):
    """Refusal and error sentences may name an export file: scrub its metric tokens while a lock binds."""
    try:
        context = Context(install, root, now=now)
    except (KeyError, TypeError, ValueError):
        return text
    if context.registry['state'] == 'unavailable' or context.active:
        return scrub(text)
    return text
