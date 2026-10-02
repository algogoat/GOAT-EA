"""OOS catch-up: bring kept exports to one evidence end with one non-optimized pass each.

An export's evidence ends where its export test ended. Exports made in different
weeks therefore end on different dates, and a portfolio built from them mixes
timelines. Catch-up re-tests each stale export's frozen values (its exact kept SET,
no optimization) from the export's original start to the new evidence end, then
judges only the newly added days (studio_catchup_verdict).

Never overwrites the original export. The re-test is a new evidence version with
the same values identity (``values_sha256``) and a later end date, stored under
``<controller state>\\evidence\\<catch-up id>\\<member alias>\\`` with its own
``evidence-version.json`` that links back to the original.

How it runs natively (no EA change): the native Studio queue only runs
optimizations, so catch-up reuses the SeedRunner process driver. Each member is
one MT5 start with a /config INI (Optimization=0, Model=4, ShutdownTerminal=1,
ToDate = evidence end + 1 day) whose [TesterInputs] are the frozen values plus
the EA's own export metadata (``EA_Desc=<alias>@{mode=EXPORT,...}`` and the
``Sequence_Export_*`` inputs the EA's RunAndStoreSet passes). The EA then writes
the same SET/CSV/.goatseq unit it writes for a batch export, into
``Common Files\\TEMP\\SQ\\<token>``; the runner moves it into the evidence store.
The close/relaunch cycle is the seed driver's and shares its terminal slot, so it
is ``native_launch_qualified: false`` until a native proof run.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_evidence import RunContext, read_export, read_json_bounded, scan, server_date, server_msc, weekdays
from studio_catchup_verdict import validate_rules
import studio_evidence_end as evidence_end
from studio_seed import SeedRunner, digest
from studio_seed_results import MAX_MANIFEST_BYTES, read_seed_json
from studio_strategy_settings import read_values
from studio_template_tools import validate_raw

MODE = 'OOSCatchup'
VERSION_SCHEMA = 'goat-evidence-version-v1'
PLAN_KEYS = {'schema_version', 'evidence_end', 'sets', 'job_timeout_seconds'}
PLAN_OPTIONAL = {'broker_clock', 'assume', 'include_below_threshold', 'verdict_rules'}
MAX_MEMBERS = 2000
MAX_PUBLIC = 100
OUTPUT_PATH_ROOM = 140  # longest EA export file name below a member folder, plus margin
OP_STANDARD = '9'
SAFE_SYMBOL = re.compile(r'[A-Za-z0-9_.# -]{1,64}')
STATUSES = ('behind', 'current', 'ahead', 'caught_up', 'ineligible')


def attempt_token(capture_id):
    """GoatSeqAttemptRoot: first 8 bytes of SHA-256(id) in hex, under Common Files\\TEMP\\SQ."""
    return hashlib.sha256(capture_id.encode('utf-8')).hexdigest()[:16]


def _date(text):
    return datetime.strptime(text, '%Y.%m.%d').date()


def _mt5(day):
    return day.strftime('%Y.%m.%d')


def versions(controller_root, limit=20000):
    """Catch-up evidence versions retained under the controller state, newest end first."""
    base = Path(controller_root) / 'evidence'
    found = []
    if base.is_dir():
        for path in sorted(base.glob('*/*/evidence-version.json')):
            try:
                record = read_json_bounded(path)
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get('schema') == VERSION_SCHEMA:
                found.append(record | dict(version_path=str(path)))
            if len(found) >= limit:
                break
    return sorted(found, key=lambda r: (r.get('evidence_end') or '', r.get('created_utc') or ''), reverse=True)


def _version_key(record):
    return (record.get('values_sha256'), record.get('symbol'), record.get('period'), record.get('evidence_start'))


def classify(export, target, *, include_below_threshold=False, known_versions=()):
    """Where one export stands against the target evidence end."""
    problems = list(export.get('problems') or [])
    end = export.get('evidence_end')
    row = dict(set_path=export['set_path'], member=export.get('member'), run_id=(export.get('run') or {}).get('run_id'),
               symbol=export.get('symbol'), period=export.get('period'), values_sha256=export['values_sha256'],
               evidence_start=export.get('evidence_start'), evidence_end=end, evidence_end_source=export.get('evidence_end_source'),
               threshold_passing=export['threshold']['passing'], threshold=export['threshold'], metrics=export.get('metrics'),
               capture_status=(export.get('capture') or {}).get('status'), history_short=export.get('history_short', False))
    if not export['threshold']['passing'] and not include_below_threshold:
        problems.append('Below the batch export thresholds (profit > 0, ARF >= %g, SR >= %g)'
                        % (export['threshold']['min_arf'], export['threshold']['min_sr']))
    if not end or not export.get('evidence_start'):
        problems.append('Evidence start or end unknown')
    if problems:
        return row | dict(status='ineligible', reasons=problems)
    target_day, end_day = date.fromisoformat(target), date.fromisoformat(end)
    match = [v for v in known_versions if _version_key(v) == _version_key(row) and (v.get('evidence_end') or '') >= target]
    if end_day < target_day and match:
        # A retained catch-up version already carries this export to (or past) the target.
        best = min(match, key=lambda v: v['evidence_end'])
        status = 'caught_up' if best['evidence_end'] == target else 'ahead'
        return row | dict(status=status, effective_end=best['evidence_end'], version_path=best['version_path'],
                          version_set_path=(best.get('retest') or {}).get('set_path'), verdict=(best.get('verdict') or {}).get('verdict'))
    if end_day < target_day:
        return row | dict(status='behind', effective_end=end, new_first_day=(end_day + timedelta(days=1)).isoformat(),
                          new_weekdays=weekdays(end_day + timedelta(days=1), target_day))
    if end_day == target_day:
        return row | dict(status='current', effective_end=end)
    return row | dict(status='ahead', effective_end=end, note='Ends after the target; the portfolio clips it to the shared end, no re-test needed')


def _n(count, noun):
    return '%d %s%s' % (count, noun, '' if count == 1 else 's')


def summarize(rows, target, *, resolved=None):
    """Counts per status, the distinct evidence ends, and one plain paragraph."""
    counts = {status: sum(r['status'] == status for r in rows) for status in STATUSES}
    ends = {}
    for row in rows:
        if row['status'] != 'ineligible':
            end = row.get('effective_end') or row['evidence_end']
            ends[end] = ends.get(end, 0) + 1
    consistent = counts['behind'] == 0 and counts['ahead'] == 0
    eligible = sum(counts[s] for s in STATUSES if s != 'ineligible')
    if consistent:
        plain = 'All %s end on %s.' % (_n(eligible, 'eligible export'), target) if eligible else 'No eligible exports.'
    else:
        plain = ('%s end before %s and need a catch-up re-test; %d already end there; %d end later and are clipped to it, not re-tested.'
                 % (_n(counts['behind'], 'export'), target, counts['current'] + counts['caught_up'], counts['ahead']))
    auto = (resolved or {}).get('auto') if (resolved or {}).get('mode') == 'auto' else None
    if counts['ahead'] and auto:
        plain += (' The exports that end later already include days of the unfinished week; after this week closes (%s, %s UTC) '
                  'auto moves to %s and everything can be brought there.' % (auto['next_date'], auto['next_switch_utc'], auto['next_date']))
    if counts['ineligible']:
        plain += ' %s ineligible (see reasons).' % ('1 is' if counts['ineligible'] == 1 else '%d are' % counts['ineligible'])
    return dict(counts=counts, evidence_ends=dict(sorted(ends.items())), consistent=consistent, plain=plain)


def resolve_target(value='auto', *, broker_clock=None, now=None):
    return evidence_end.resolve(value, now, clock=broker_clock or evidence_end.DEFAULT_CLOCK)


def evidence_scan(sources, *, value='auto', broker_clock=None, now=None, controller_root=None, include_below_threshold=False):
    """Read-only inventory: every kept export under ``sources`` against one target end."""
    target = resolve_target(value, broker_clock=broker_clock, now=now)
    exports, unreadable = scan(sources)
    known = versions(controller_root) if controller_root else ()
    rows = [classify(e, target['iso'], include_below_threshold=include_below_threshold, known_versions=known) for e in exports]
    return dict(schema_version=1, target=target, summary=summarize(rows, target['iso'], resolved=target), exports=rows, unreadable=unreadable,
                rules=dict(evidence_end=target['rule'], thresholds_applied_to_eligibility=not include_below_threshold,
                           thresholds='each export carries its own threshold, basis and margins'),
                writes=False, native_launch_qualified=False,
                next_action='catchup-prepare with the behind SETs re-tests them to %s; nothing runs until catchup-start' % target['iso'])


QUALIFICATION_SCHEMA = 'goat-qualification-inputs-v1'


def qualification_inputs(spec, manifest, verdict):
    """Everything a later scored, explained qualification needs, with the rules that produced it.

    Nothing is scored here: the export thresholds (and how far the export sits from each),
    the evidence-end rule, the verdict rules and the raw signals are recorded so another
    rule set can re-judge the same evidence without re-running MT5.
    """
    target = manifest['evidence_end']
    return dict(schema=QUALIFICATION_SCHEMA, scored=False,
                evidence_end=dict(rule=target['rule'], mode=target['mode'], requested=target['requested'], date=target['iso']),
                export_thresholds=spec['original'].get('threshold'),
                thresholds_applied_to_eligibility=not manifest.get('include_below_threshold', False),
                verdict_rules=verdict.get('rules') or manifest.get('verdict_rules'),
                signals=verdict.get('signals'), verdict=verdict.get('verdict'), confidence=verdict.get('confidence'),
                assumed=spec.get('assumed', []))


class _NoProcess:
    """Process stand-in for previews: any terminal effect is a defect."""
    def inspect(self):
        raise ValueError('Catch-up preview never inspects the terminal')

    def start(self, config):
        raise ValueError('Catch-up preview never starts the terminal')

    def close(self, identity):
        raise ValueError('Catch-up preview never closes the terminal')


def read_operation(controller, args, *, now=None):
    """The read-only CLI operations: evidence-end, evidence-scan, evidence-versions, catchup-validate."""
    clock = getattr(args, 'broker_clock', None)
    if args.operation == 'evidence-end':
        result = resolve_target(args.value, broker_clock=clock, now=now)
        local = getattr(controller, 'local', None)
        return result | dict(batch_exports_now=evidence_end.legacy_end(now, clock=clock or evidence_end.DEFAULT_CLOCK),
                             ea_evidence_end_setting=evidence_end.ea_capability(controller.install, Path(local) / 'ui-observation.json')
                             if local else None)
    if args.operation == 'evidence-scan':
        return evidence_scan([str(p) for p in args.source], value=args.evidence_end, broker_clock=clock, now=now,
                             controller_root=controller.root, include_below_threshold=args.include_below_threshold)
    if args.operation == 'evidence-versions':
        rows = versions(controller.root)
        if args.values_sha256:
            rows = [r for r in rows if r.get('values_sha256') == args.values_sha256]
        return dict(schema_version=1, count=len(rows), versions=rows[:MAX_PUBLIC], versions_omitted=max(0, len(rows) - MAX_PUBLIC))
    if args.operation == 'catchup-validate':
        from studio_batch import _json
        from studio_installation import read_json
        controller.session = read_json(Path(controller.root) / 'session.json')
        return CatchupRunner(controller, process=_NoProcess(), now=now).validate(_json(args.plan))
    raise ValueError('Not a read-only evidence operation: ' + args.operation)


def _tester_conditions(export, assume):
    """Original tester conditions for a single re-test, with provenance per field."""
    capture, tester, windows = export.get('capture') or {}, export.get('tester') or {}, export.get('windows') or {}
    facts, assumed, missing = {}, [], []
    for key, from_capture in (('Deposit', capture.get('initial_equity')), ('Currency', capture.get('currency')),
                              ('Leverage', '1:%d' % capture['leverage'] if type(capture.get('leverage')) is int else None)):
        value = tester.get(key, from_capture)
        if value is None:
            missing.append(key)
        facts[key] = value
    if 'ExecutionMode' in tester:
        facts['ExecutionMode'] = tester['ExecutionMode']
    elif isinstance(assume, dict) and type(assume.get('ExecutionMode')) is int:
        facts['ExecutionMode'] = assume['ExecutionMode']
        assumed.append('ExecutionMode')
    else:
        missing.append('ExecutionMode')
    window = dict(FromDate=tester.get('FromDate'), ToDate=tester.get('ToDate'), ForwardDate=tester.get('ForwardDate'), source='run_manifest')
    if not all(window[k] for k in ('FromDate', 'ToDate', 'ForwardDate')):
        sample, fwd = windows.get('SAMPLE'), windows.get('FWD')
        window = dict(FromDate=sample and _mt5(date.fromisoformat(sample['start'])), ToDate=fwd and _mt5(date.fromisoformat(fwd['end'])),
                      ForwardDate=fwd and _mt5(date.fromisoformat(fwd['start'])), source='set_header')
        if not all(window[k] for k in ('FromDate', 'ToDate', 'ForwardDate')):
            window = dict(FromDate=None, ToDate=None, ForwardDate=None, source='unknown')
    return facts, window, assumed, missing


def _export_desc(alias, window):
    """EA_Desc metadata the EA's StartExporter passes, so the re-test SET header has the same windows."""
    if window['source'] == 'unknown':
        return alias + '@{mode=EXPORT}'
    foos = _mt5(_date(window['ToDate']) + timedelta(days=1))
    return (alias + '@{mode=EXPORT,dt_BOOS_end=' + window['FromDate'] + ',dt_FOOS_start=' + foos
            + ',dt_FWD_start=' + window['ForwardDate'] + ',dt_FWD_end=' + window['ToDate'] + '}')


class CatchupRunner(SeedRunner):
    """SeedRunner driver with catch-up members: one non-optimized MT5 pass each."""

    def __init__(self, controller, *, process=None, clock=time.time, sleep=time.sleep, now=None):
        super().__init__(controller, process=process, clock=clock, sleep=sleep)
        self.base = controller.root / 'catchups'
        self.evidence = controller.root / 'evidence'
        self.now = now

    def path(self, batch_id):
        if not isinstance(batch_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
        return self.base / batch_id

    # ---- plan --------------------------------------------------------------------------
    def _plan(self, plan):
        if not isinstance(plan, dict) or not PLAN_KEYS <= set(plan) or set(plan) - PLAN_KEYS - PLAN_OPTIONAL or plan['schema_version'] != 1:
            raise ValueError('Catch-up plan requires schema_version:1, evidence_end, sets and job_timeout_seconds '
                             '(optional: broker_clock, assume, include_below_threshold, verdict_rules)')
        if type(plan['job_timeout_seconds']) is not int or not 60 <= plan['job_timeout_seconds'] <= 86400:
            raise ValueError('job_timeout_seconds must be 60..86400')
        sets = plan['sets']
        if not isinstance(sets, list) or not 1 <= len(sets) <= MAX_MEMBERS or any(not isinstance(p, str) or not Path(p).is_absolute() for p in sets):
            raise ValueError('sets must list 1..%d absolute exported .set paths' % MAX_MEMBERS)
        if len({str(Path(p)).lower() for p in sets}) != len(sets):
            raise ValueError('Duplicate SET path in catch-up plan')
        assume = plan.get('assume', {})
        if not isinstance(assume, dict) or set(assume) - {'ExecutionMode'} or ('ExecutionMode' in assume and (
                type(assume['ExecutionMode']) is not int or not -1 < assume['ExecutionMode'] <= 600000)):
            raise ValueError('assume may only give a fixed ExecutionMode delay 0..600000 (random delay -1 cannot reproduce)')
        if type(plan.get('include_below_threshold', False)) is not bool:
            raise ValueError('include_below_threshold must be true or false')
        validate_rules(plan.get('verdict_rules'))
        return assume

    def _freeze(self, root, plan):
        members, payloads, _, _ = self._build(root, plan)
        return members, payloads

    def _build(self, root, plan):
        """Validate the plan and build every member in memory. Writes nothing."""
        assume = self._plan(plan)
        target = resolve_target(plan['evidence_end'], broker_clock=plan.get('broker_clock'), now=self.now)
        install, account = self.c.install, self.c.session['account']
        expert = install['ea_relative_path']
        runs, rows, members, payloads = RunContext(), [], [], []
        nonce = uuid.uuid4().hex[:16]
        known = versions(self.c.root)
        for path in plan['sets']:
            try:
                export = read_export(path, runs=runs)
            except (OSError, ValueError, UnicodeError) as exc:
                rows.append(dict(set_path=path, status='ineligible', reasons=['Unreadable export: ' + str(exc)]))
                continue
            row = classify(export, target['iso'], include_below_threshold=plan.get('include_below_threshold', False), known_versions=known)
            if row['status'] == 'behind':
                reasons = self._member_problems(export, account)
                facts, window, assumed, missing = _tester_conditions(export, assume)
                if missing:
                    reasons.append('Unknown original tester settings: ' + ', '.join(missing)
                                   + ('; keep the export next to its run folder, or pass assume.ExecutionMode' if 'ExecutionMode' in missing else ''))
                if reasons:
                    row = row | dict(status='ineligible', reasons=reasons)
                else:
                    member, files = self._member(root, export, target, facts, window, assumed, account, expert, nonce, len(members))
                    members.append(member)
                    payloads.extend(files)
                    row = row | dict(alias=member['alias'])
            rows.append(row)
        if len({m['member_id'] for m in members}) != len(members):
            raise ValueError('Duplicate export values/window in catch-up plan')
        return members, payloads, rows, target

    def _member_problems(self, export, account):
        problems = []
        capture = export.get('capture') or {}
        if not export.get('symbol') or not SAFE_SYMBOL.fullmatch(export['symbol']):
            problems.append('Symbol cannot be used in a tester file name')
        if capture.get('server') and capture['server'] != account['server']:
            problems.append('Export came from broker server %s; this terminal is on %s, so ticks and symbols differ'
                            % (capture['server'], account['server']))
        if capture.get('model') not in (None, 4):
            problems.append('Export was not tested with real ticks (Model 4)')
        if capture.get('asset') and capture['asset'] != export.get('symbol'):
            problems.append('Capture symbol differs from the export file name')
        values = read_values(Path(export['set_path']).read_bytes())
        if values.get('Mode_Operation') != OP_STANDARD:
            problems.append('Exported SET is not in standard operation mode (Mode_Operation=9)')
        try:
            validate_raw(Path(export['set_path']).read_bytes(), self.c.schema, self.c.policy)
        except ValueError as exc:
            problems.append('SET does not match the installed EA inputs: ' + str(exc))
        return problems

    def _member(self, root, export, target, facts, window, assumed, account, expert, nonce, index):
        alias = 'C' + nonce + '_' + str(index + 1).zfill(5)
        capture_id = 'catchup-' + nonce + '-' + str(index + 1).zfill(5)
        start, to_date = date.fromisoformat(export['evidence_start']), _date(target['tester_to_date'])
        deposit = facts['Deposit']
        if type(deposit) is float and deposit.is_integer():
            deposit = int(deposit)
        if type(deposit) not in (int, float) or deposit <= 0:
            raise ValueError('Original deposit must be a positive number: ' + export['set_path'])
        tester = dict(Expert=expert, Symbol=export['symbol'], Period=export['period'], Model=4, ExecutionMode=facts['ExecutionMode'],
                      Optimization=0, FromDate=_mt5(start), ToDate=_mt5(to_date), ForwardMode=0, Deposit=deposit,
                      Currency=facts['Currency'], Leverage=facts['Leverage'], UseLocal=1, UseRemote=0, UseCloud=0, Visual=0,
                      ShutdownTerminal=1, ReplaceReport=0, Report='MQL5\\Files\\GOATStudio\\CatchupReports\\' + alias)
        raw = Path(export['set_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != export['set_sha256']:
            raise ValueError('Export SET changed while planning: ' + export['set_path'])
        text = raw.decode('utf-16')
        frozen_text, count = re.subn(r'(?m)^EA_Desc=[^\r\n]*', 'EA_Desc=' + alias, text)
        if count != 1:
            raise ValueError('Exported SET needs exactly one EA_Desc line: ' + export['set_path'])
        frozen = b'\xff\xfe' + frozen_text.encode('utf-16-le')
        capture = export.get('capture')
        source_inputs = None
        if capture:
            candidate = Path(capture['path']).parent / 'source-inputs.set'
            if candidate.is_file() and candidate.stat().st_size <= 1024 * 1024:
                source_inputs = candidate.read_bytes()
        values = read_values(frozen)
        inputs = dict(values, EA_Desc=_export_desc(alias, window), Sequence_Export_Enabled='true' if source_inputs is not None else 'false',
                      Sequence_Export_Id=capture_id, Sequence_Export_Start=tester['FromDate'], Sequence_Export_End=tester['ToDate'],
                      Sequence_Export_Model='4')
        sections = {'Common': {'Login': account['login'], 'Server': account['server']}, 'Experts': {'Enabled': 0, 'AllowLiveTrading': 0},
                    'Tester': tester, 'TesterInputs': inputs}
        ini = ''
        for section, items in sections.items():
            ini += '[' + section + ']\r\n'
            for key, value in items.items():
                if any(c in str(value) for c in '\r\n\x00'):
                    raise ValueError('Unsafe startup value: ' + key)
                ini += key + '=' + str(value) + '\r\n'
        config = ini.encode('utf-16')
        set_path = root / (alias + '.set')
        config_path = Path(self.c.install['terminal_data_root']) / 'config/GOATStudio/Catchups' / (alias + '.ini')
        evidence_dir = self.evidence / root.name / alias
        if len(str(evidence_dir)) + OUTPUT_PATH_ROOM > 259:
            raise ValueError('Controller state path is too long for catch-up evidence folders (Windows 260-character limit)')
        files = [(set_path, frozen), (config_path, config)]
        member = dict(member_id=sha([export['values_sha256'], export['symbol'], export['period'], tester['FromDate'], tester['ToDate'],
                                     deposit, facts['Currency'], facts['Leverage'], facts['ExecutionMode']]),
                      index=index, alias=alias, account=account, tester=tester, frame_target=1, capture_id=capture_id,
                      attempt_token=attempt_token(capture_id), capture=source_inputs is not None,
                      source_path=export['set_path'], source_sha256=export['set_sha256'],
                      set_path=str(set_path), set_sha256=hashlib.sha256(frozen).hexdigest(),
                      config_path=str(config_path), config_sha256=hashlib.sha256(config).hexdigest(),
                      evidence_dir=str(evidence_dir), assumed=assumed, optimization_window=window,
                      original=dict(set_path=export['set_path'], set_sha256=export['set_sha256'], values_sha256=export['values_sha256'],
                                    member=export.get('member'), run_id=(export.get('run') or {}).get('run_id'),
                                    evidence_start=export['evidence_start'], evidence_end=export['evidence_end'],
                                    evidence_end_source=export['evidence_end_source'], metrics=export.get('metrics'),
                                    tester=export.get('tester'), threshold=export['threshold']),
                      new_window=dict(first_day=(date.fromisoformat(export['evidence_end']) + timedelta(days=1)).isoformat(),
                                      last_day=target['iso'], weekdays=weekdays(date.fromisoformat(export['evidence_end']) + timedelta(days=1),
                                                                                date.fromisoformat(target['iso']))))
        if source_inputs is not None:
            staged = root / (alias + '.source-inputs.set')
            files.append((staged, source_inputs))
            member.update(source_inputs_path=str(staged), source_inputs_sha256=hashlib.sha256(source_inputs).hexdigest())
        return member, files

    def validate(self, plan):
        """Non-executing preview of a catch-up plan: no file, process or terminal effect."""
        members, _, rows, target = self._build(self.base / 'validation-only', plan)
        return self._preview(members, rows, target, plan, writes=False)

    @staticmethod
    def _preview(members, rows, target, plan, *, writes):
        return dict(schema_version=1, valid=True, writes=writes, native_launch_qualified=False, mode=MODE,
                    target=target, plan_sha256=sha(plan), member_count=len(members), summary=summarize(rows, target['iso'], resolved=target),
                    exports=rows[:MAX_PUBLIC], exports_omitted=max(0, len(rows) - MAX_PUBLIC),
                    members=[dict(alias=m['alias'], symbol=m['tester']['Symbol'], period=m['tester']['Period'], from_date=m['tester']['FromDate'],
                                  to_date=m['tester']['ToDate'], original_end=m['original']['evidence_end'], new_weekdays=m['new_window']['weekdays'],
                                  assumed=m['assumed'], capture=m['capture']) for m in members[:MAX_PUBLIC]])

    def prepare(self, batch_id, plan):
        root = self.path(batch_id)
        if root.exists():
            _, old, _ = self._read(batch_id)
            if old['plan_sha256'] != sha(plan):
                raise ValueError('Catch-up ID already belongs to a different plan; choose a new ID')
            return self.status(batch_id)
        members, payloads, rows, target = self._build(root, plan)
        if not members:
            raise ValueError('Nothing to catch up to %s. %s' % (target['iso'], summarize(rows, target['iso'], resolved=target)['plain']))
        manifest = dict(schema_version=1, batch_id=batch_id, installation_sha256=sha(self.c.install), schema_sha256=sha(self.c.schema),
                        plan_sha256=sha(plan), plan=plan, created_unix=self.clock(), members=members, mode=MODE,
                        evidence_end=target, exports=rows, verdict_rules=validate_rules(plan.get('verdict_rules')),
                        include_below_threshold=plan.get('include_below_threshold', False), native_launch_qualified=False)
        if len(json.dumps(manifest).encode('utf-8')) > MAX_MANIFEST_BYTES:
            raise ValueError('Catch-up manifest exceeds 128 MiB; split the plan')
        root.mkdir(parents=True, exist_ok=False)
        (Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/CatchupReports').mkdir(parents=True, exist_ok=True)
        for path, raw in payloads:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        write_json(root / 'manifest.json', manifest)
        state = dict(schema_version=1, batch_id=batch_id, manifest_sha256=digest(root / 'manifest.json'), status='prepared', generation=None,
                     members=[dict(member_id=m['member_id'], alias=m['alias'], status='pending', attempts=0, result=None) for m in members])
        self._save(root, state)
        return self.status(batch_id) | dict(preview=self._preview(members, rows, target, plan, writes=True))

    # ---- native hooks ------------------------------------------------------------------
    def _attempt_dir(self, member):
        return Path(self.c.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']

    def _outputs(self, member):
        folder = self._attempt_dir(member)
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.glob('*.set') if p.is_file())

    def _before_start(self, spec):
        """Stage the EA's capture input snapshot (GoatTraceInit refuses without it). Create-only."""
        if not spec['capture']:
            return
        raw = Path(spec['source_inputs_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['source_inputs_sha256']:
            raise ValueError('Frozen catch-up capture inputs changed')
        pending = Path(self.c.install['common_files_root']) / 'GOATSequencePending' / spec['capture_id']
        target = pending / 'source-inputs.set'
        if (pending / 'run.csv').exists():
            raise ValueError('Capture namespace already holds a native capture; no restart')
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('Capture namespace already holds different inputs')
            return
        pending.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)

    def _collect(self, path, spec, manifest):
        """Verify the EA's re-test unit, move it into the evidence store and judge the new weeks."""
        from studio_catchup_verdict import evaluate
        if len(self._outputs(spec)) != 1:
            raise ValueError('Expected exactly one exported SET from a single catch-up pass')
        retest = read_export(path)
        tester = spec['tester']
        if (retest['symbol'], retest['period']) != (tester['Symbol'], tester['Period']) or retest['alias'] != spec['alias']:
            raise ValueError('Re-test export identity differs from the frozen member')
        capture = retest.get('capture')
        if spec['capture']:
            if not capture or capture['run_id'] != spec['capture_id']:
                raise ValueError('Re-test capture is missing or belongs to another attempt')
            if (capture['requested_start_msc'], capture['requested_end_msc']) != (server_msc(_date(tester['FromDate'])), server_msc(_date(tester['ToDate']))):
                raise ValueError('Re-test capture window differs from the frozen member')
        original = read_export(spec['original']['set_path'])
        if original['set_sha256'] != spec['original']['set_sha256'] or original['evidence_end'] != spec['original']['evidence_end']:
            raise ValueError('Original export changed since the catch-up was prepared')
        moved = self._move(path, Path(spec['evidence_dir']))
        retest = read_export(moved)
        if not retest['evidence_end']:
            raise ValueError('Re-test export has no evidence end')
        try:
            verdict = evaluate(original, retest, new_end=min(retest['evidence_end'], manifest['evidence_end']['iso']),
                               tester=spec['original'].get('tester'), rules=manifest.get('verdict_rules'))
        except (OSError, ValueError, KeyError, ArithmeticError) as exc:
            # The re-test evidence is kept either way; only the judgement is unavailable.
            reason = 'Could not judge the new weeks: ' + str(exc)
            verdict = dict(verdict='unjudged', confidence='none', reasons=[reason], plain=reason,
                           new_weeks=dict(first_day=spec['new_window']['first_day'], last_day=retest['evidence_end'], weekdays=None,
                                          trades=None, net=None, dd=None, pf=None),
                           reproduction=dict(reproduced=None))
        version = dict(schema=VERSION_SCHEMA, values_sha256=retest['values_sha256'], symbol=retest['symbol'], period=retest['period'],
                       evidence_start=retest['evidence_start'], evidence_end=retest['evidence_end'], evidence_end_source=retest['evidence_end_source'],
                       target_end=manifest['evidence_end']['iso'], catchup_id=manifest['batch_id'], alias=spec['alias'],
                       created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                       original=dict(spec['original'], csv_path=original['csv_path']),
                       retest=dict(set_path=retest['set_path'], set_sha256=retest['set_sha256'], csv_path=retest['csv_path'],
                                   capture=retest.get('capture') and dict(path=retest['capture']['path'], status=retest['capture']['status'],
                                                                         manifest_sha256=retest['capture']['manifest_sha256'])),
                       tester=tester, assumed=spec['assumed'],
                       verdict={k: verdict[k] for k in ('verdict', 'confidence', 'plain', 'reasons')},
                       qualification=qualification_inputs(spec, manifest, verdict),
                       history_short=retest['history_short'], ea_desc_metadata=spec['optimization_window']['source'])
        version_path = Path(spec['evidence_dir']) / 'evidence-version.json'
        with version_path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(version, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
        window = verdict['new_weeks']
        summary = dict(verdict=verdict['verdict'], confidence=verdict['confidence'], new_first_day=window['first_day'],
                       new_last_day=window['last_day'], weekdays=window['weekdays'], trades=window['trades'], net=window['net'],
                       dd=window['dd'], pf=window.get('pf'), reproduced=verdict['reproduction']['reproduced'], plain=verdict['plain'],
                       history_short=retest['history_short'])
        return dict(status='verified_catchup_retest', path=retest['set_path'], sha256=retest['set_sha256'], schema_version=1,
                    member_id=spec['member_id'], summary=summary, verdict=verdict, version_path=str(version_path),
                    native_launch_qualification=False)

    def _move(self, set_path, destination):
        """Move the EA's SET/CSV/.goatseq unit out of TEMP into the evidence folder. Never overwrites."""
        stem = set_path.name[:-4]
        parts = [(set_path, destination / set_path.name), (set_path.with_name(stem + '.csv'), destination / (stem + '.csv'))]
        package = set_path.with_name(stem + '.goatseq')
        if package.is_dir():
            parts.append((package, destination / package.name))
        if destination.exists():
            raise ValueError('Catch-up evidence folder already exists; inspect it, nothing was moved')
        destination.mkdir(parents=True)
        for source, target in parts:
            if not source.exists():
                raise ValueError('Re-test unit incomplete: ' + source.name)
            try:
                os.rename(source, target)
            except OSError:
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
                if source.is_file() and digest(source) != digest(target):
                    raise ValueError('Copied re-test file differs: ' + source.name)
        return destination / set_path.name

    # ---- reports -----------------------------------------------------------------------
    def report(self, batch_id):
        self.status(batch_id)
        root, manifest, state = self._read(batch_id)
        rows, counts = [], {}
        for spec, item in zip(manifest['members'], state['members']):
            result = read_seed_json(item['result']['path']) if item.get('result') else None
            verdict = result['summary']['verdict'] if result else None
            counts[verdict or item['status']] = counts.get(verdict or item['status'], 0) + 1
            rows.append(dict(alias=spec['alias'], status=item['status'], symbol=spec['tester']['Symbol'], period=spec['tester']['Period'],
                             original_set=spec['original']['set_path'], original_end=spec['original']['evidence_end'],
                             new_end=manifest['evidence_end']['iso'], summary=result['summary'] if result else None,
                             version_path=result['version_path'] if result else None, error=item.get('error'),
                             export_thresholds=spec['original'].get('threshold'),
                             signals=(result.get('verdict') or {}).get('signals') if result else None))
        value = dict(schema_version=1, batch_id=batch_id, mode=MODE, status=state['status'], evidence_end=manifest['evidence_end'],
                     counts=counts, members=rows, verdict_rules=manifest.get('verdict_rules') or validate_rules(),
                     thresholds_applied_to_eligibility=not manifest.get('include_below_threshold', False),
                     qualification_schema=QUALIFICATION_SCHEMA, scored=False, native_launch_qualified=False,
                     scope='New-weeks-only verdicts on unseen data; a few weeks is a small sample.')
        write_json(root / 'report.json', value)
        if len(rows) > MAX_PUBLIC:
            return {k: v for k, v in value.items() if k != 'members'} | dict(member_count=len(rows), members_omitted=True,
                                                                             report_path=str(root / 'report.json'))
        return value | dict(report_path=str(root / 'report.json'))
