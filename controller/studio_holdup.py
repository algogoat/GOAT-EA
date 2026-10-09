"""Hold-up test, the Prove step (goatai#1885, Claude-Mac APPROVE 5989126739): one frozen SET, one MT5 pass.

"Does round 3's exact winning SET hold on weeks it never saw?" A hold-up test runs each frozen SET as one
MT5 tester pass (Optimization=0, ForwardMode=0) over a chosen window ``[start, end)`` and reads the
result from MT5's own single-test report (studio_tester_report), never from EA output:

* **Frozen and hash-bound.** The plan names each SET by path and ``set_sha256``; prepare refuses other
  bytes. The frozen copy differs only in ``EA_Desc=<alias>`` (no ``@{mode=...}``, so the EA runs a plain
  test and writes no export, SeedFarming XML or batch state). The report's inputs must equal the frozen
  values one by one, so the result proves MT5 ran the bound bytes.
* **Refused before any effect:** a SET with an active search axis, ``RISK_NOT_CHOSEN`` and the
  risk-per-sequence rule (``validate_raw``), not standard operation (``Mode_Operation=9``), a GOAT starter,
  AI bias on (``Mode_Bias`` not ``Bias_Disabled``; rule 5), ``heldout_reveal`` (v1: the reveal waits for
  the native T3 proof), a window into the unfinished week, and any member that overlaps an active
  held-out lock of its strategy (GOAT-EA#145, again before every launch).
* **Demo lane only (v1).** It runs through ``goat.exe demo holdup-*`` on the broker-verified demo lane
  (demo account, Algo off, no positions or orders, owner STOP/TAKE, disk), with the seed lane's close,
  ``/config`` launch, one terminal slot and member-failure rules (studio_seed).
* **Writes nothing else.** No export, promotion, library, ledger or catalog write. Each member keeps
  ``<alias>.result.json`` (``goat-holdup-result-v1``), a copy of MT5's report and ``<alias>.deals.json``.
* **Evidence hint, never a ledger write.** ``relation`` says where the window sits against the SET's own
  selection exposure (the export header's BOOS/SAMPLE/FWD/FOOS, or a seed promotion's seed window):
  after -> catch-up L3 clean, before -> back-oos L2 clean, overlaps -> in-sample L0 contaminated,
  unknown -> back-oos L2 with contamination ``unknown`` (the phase-2 scorer treats unknown exactly like
  contaminated). Below 90 % MT5 history quality the result is kept with ``evidence: null`` and a reason.

``native_launch_qualified: false`` until the owner-lane T3 proof.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_evidence import parse_header, parse_stem, read_json_bounded
from studio_heldout import HeldOutRefused
from studio_seed import SeedRunner, digest
from studio_seed_results import MAX_MANIFEST_BYTES, MAX_RESULT_BYTES, read_seed_json
from studio_strategy_attribution import variant_id
from studio_strategy_settings import read_values
from studio_template_tools import is_starter, source_bytes, validate_raw
import studio_tester_report as tester_report

MODE = 'HoldupTest'
RESULT_SCHEMA = 'goat-holdup-result-v1'
PLAN_KEYS = frozenset(('schema_version', 'job_timeout_seconds', 'tests'))
TEST_KEYS = frozenset(('set_path', 'set_sha256', 'window', 'tester'))
TEST_OPTIONAL = frozenset(('symbol', 'period', 'strategy_ref'))
TESTER_KEYS = frozenset(('Model', 'ExecutionMode', 'Deposit', 'Currency', 'Leverage'))
MAX_TESTS = 50
MAX_PUBLIC = 100
QUALITY_FLOOR = 90.0       # no evidence hint below this MT5 history quality (Claude-Mac; catch-up has no threshold)
OP_STANDARD = '9'
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
REVEAL_CODE = 'HELDOUT_REVEAL_NOT_IN_V1'
BIAS_CODE = 'HOLDUP_AI_BIAS_ON'
ROLES = dict(after_selection=('catch-up', 'L3', 'clean', []), before_selection=('back-oos', 'L2', 'clean', []),
             overlaps_selection=('in-sample', 'L0', 'contaminated', ['in-sample']), unknown=('back-oos', 'L2', 'unknown', []))
SAMPLING = {0: 'tick', 4: 'tick', 1: '1m-events'}
SCOPE = ('Hold-up test: one frozen SET, one MT5 pass on the chosen window. Not an export, never imported into the '
         'library by this command; record it with evidence.record. A few weeks is a small sample.')


def _day(value, label):
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError(label + ' must be a broker day YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(label + ' is not a real day: ' + value) from None


def _mt5(day):
    return day.strftime('%Y.%m.%d')


def relation_of(window_start, window_end, exposure):
    """Where ``[window_start, window_end)`` sits against the SET's selection exposure ``[start, end)``."""
    if exposure is None:
        return 'unknown'
    if window_end <= exposure['start']:
        return 'before_selection'
    if window_start >= exposure['end']:
        return 'after_selection'
    return 'overlaps_selection'


def evidence_hint(relation, *, quality, model, held_out_lock_id=None):
    """The ledger mapping the desktop's evidence.record applies (Claude-Mac answer 6), or (None, reason)."""
    if quality is None:
        return None, 'MT5 did not report its history quality, so this result is not offered as evidence.'
    if quality < QUALITY_FLOOR:
        return None, ('MT5 history quality was %g%%, below the %g%% floor, so this result is kept but not offered as '
                      'evidence.' % (quality, QUALITY_FLOOR))
    role, level, status, reasons = ROLES[relation]
    return dict(kind='prove', run_kind='single-pass', role=role, level=level,
                contamination=dict(status=status, reasons=list(reasons)), held_out_lock_id=held_out_lock_id,
                selection_used=relation == 'overlaps_selection', journal_ref_kind='holdup-result',
                metrics_source='tester-report', drawdown_sampling=SAMPLING.get(model), ai_trust='not-applicable',
                scorer_rule='contamination unknown is treated exactly like contaminated, never as clean'), None


class HoldupRunner(SeedRunner):
    """SeedRunner driver with hold-up members: one non-optimized MT5 pass of one frozen SET each."""
    OUTPUT_NOUN = 'Strategy Tester report'
    COMMAND_PREFIX = 'holdup'
    MEMBER_NOUN = 'test'
    ID_FLAG = '--holdup-id'

    def __init__(self, controller, *, process=None, clock=time.time, sleep=time.sleep, now=None):
        super().__init__(controller, process=process, clock=clock, sleep=sleep)
        self.base = controller.root / 'holdups'
        self.now = now
        # Hold-up tests run on the owner demo lane only (v1): next_step names goat.exe demo, never a studio
        # holdup-* command, which does not exist (Claude-Mac nit on GOAT-EA#197).
        self.cli_lane, self.next_step_budget = 'demo', 3600

    def path(self, batch_id):
        if not isinstance(batch_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Hold-up test ID must use 1..80 letters/digits/underscore/hyphen')
        return self.base / batch_id

    def report_dir(self):
        return Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/HoldupReports'

    # ---- plan ----------------------------------------------------------------------------------------
    def _plan(self, plan):
        if isinstance(plan, dict) and 'heldout_reveal' in plan:
            raise HeldOutRefused(REVEAL_CODE, 'A held-out reveal does not run through hold-up test v1: the reveal is the most '
                                 'valuable held-out test and its runner must first pass the native T3 proof '
                                 '(native_launch_qualified). Remove heldout_reveal; v1.1 enables it.')
        if not isinstance(plan, dict) or set(plan) != PLAN_KEYS or plan['schema_version'] != 1:
            raise ValueError('Hold-up plan requires exactly schema_version:1, job_timeout_seconds and tests')
        if type(plan['job_timeout_seconds']) is not int or not 60 <= plan['job_timeout_seconds'] <= 86400:
            raise ValueError('job_timeout_seconds must be 60..86400')
        tests = plan['tests']
        if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_TESTS:
            raise ValueError('tests must list 1..%d hold-up tests' % MAX_TESTS)
        return tests

    def _bias_off(self, values, label):
        definition = self.c.schema['inputs'].get('Mode_Bias')
        if definition is None:
            return
        disabled = (definition.get('enum_choices') or {}).get('Bias_Disabled')
        if disabled is None:
            raise ValueError(BIAS_CODE + ': the installed input schema has Mode_Bias but no Bias_Disabled choice, so AI '
                             'bias cannot be proven off; nothing is accepted')
        try:
            current = Decimal(values['Mode_Bias'].split('||')[0])
        except (KeyError, InvalidOperation):
            current = None
        if current != disabled:
            raise ValueError(BIAS_CODE + ': ' + label + ' runs with AI bias on (Mode_Bias=' + str(values.get('Mode_Bias')) + '). A '
                             'tester window with AI bias on is never verdict evidence, so hold-up test v1 runs only '
                             'Mode_Bias=Bias_Disabled (' + str(disabled) + ').')

    def _named(self, source, raw, label, test):
        """Symbol and period from the SET (export file name, or a seed promotion beside it) and the plan; they must agree."""
        sources = []
        stem = source.name[:-4] if source.name.lower().endswith('.set') else source.name
        named = parse_stem(stem)
        if named:
            sources.append(('export file name', named['symbol'], named['period']))
        promotion = self._promotion(source, raw)
        if promotion:
            window = promotion.get('seed_window') or {}
            sources.append(('seed promotion', window.get('symbol'), window.get('period')))
        if test.get('symbol') is not None or test.get('period') is not None:
            sources.append(('plan', test.get('symbol'), test.get('period')))
        if not sources:
            raise ValueError(label + ': the SET does not name its symbol and period (not an export or a seed promotion); give '
                             'symbol and period in the plan')
        symbols = {s for _, s, _ in sources if s is not None}
        periods = {p for _, _, p in sources if p is not None}
        if len(symbols) != 1 or len(periods) != 1:
            raise ValueError(label + ': symbol/period disagree between ' + '; '.join('%s %s %s' % item for item in sources))
        symbol, period = symbols.pop(), periods.pop()
        if not re.fullmatch(r'[A-Za-z0-9_.# -]{1,64}', symbol):
            raise ValueError(label + ': symbol cannot be used in a tester file name')
        return symbol, period, [name for name, _, _ in sources]

    @staticmethod
    def _promotion(source, raw):
        receipt = source.parent / 'promotion.json'
        try:
            value = read_json_bounded(receipt) if receipt.is_file() else None
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict) or (value.get('fixed_set') or {}).get('sha256') != hashlib.sha256(raw).hexdigest():
            return None   # the receipt describes another file
        return value

    def _exposure(self, source, text, raw):
        """The SET's own selection exposure [start, end), or None when it cannot be known."""
        try:
            windows = parse_header(text)
        except ValueError:
            windows = {}
        if windows:
            start = min(date.fromisoformat(w['start']) for w in windows.values())
            end = max(date.fromisoformat(w['end']) for w in windows.values()) + timedelta(days=1)
            return dict(start=start, end=end, basis='export SET header (' + '/'.join(sorted(windows)) + ')',
                        windows={k: dict(start=w['start'], end=w['end']) for k, w in sorted(windows.items())})
        promotion = self._promotion(source, raw)
        window = (promotion or {}).get('seed_window') or {}
        try:
            start = date.fromisoformat(window['from_date'].replace('.', '-'))
            end = date.fromisoformat(window['to_date'].replace('.', '-'))
        except (KeyError, AttributeError, ValueError):
            return None
        return dict(start=start, end=end, basis='seed promotion (seed window)',
                    windows=dict(SEED=dict(start=start.isoformat(), end=end.isoformat())))

    def _freeze(self, root, plan):
        tests = self._plan(plan)
        from studio_installed_build import refuse_pre_b38
        refuse_pre_b38(self.c.install)   # a pre-B38 EA: update it first (goatai#2350 6089668580)
        from studio_catchup import _validate_single_pass
        from studio_evidence_end import auto
        from studio_strategy_attribution import validate_ref
        install, account = self.c.install, self.c.session['account']
        latest_end = date.fromisoformat(auto(self.now)['iso']) + timedelta(days=1)
        nonce = uuid.uuid4().hex[:16]
        members, payloads, identities = [], [], set()
        # An export of a batch closed with exclude (studio_batch_close) is never re-tested, as in catch-up.
        from studio_batch_close import excluded_source, exclusions
        from studio_refusal import Refusal
        markers = exclusions(self.c.root)
        for index, test in enumerate(tests):
            label = 'Test %d' % (index + 1)
            if not isinstance(test, dict) or not TEST_KEYS <= set(test) or set(test) - TEST_KEYS - TEST_OPTIONAL:
                raise ValueError(label + ' requires set_path, set_sha256, window and tester (optional: symbol, period, strategy_ref)')
            strategy_ref = validate_ref(test.get('strategy_ref'), label)
            if not isinstance(test['set_path'], str) or not Path(test['set_path']).is_absolute():
                raise ValueError(label + ': set_path must be an absolute .set path')
            if not isinstance(test['set_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', test['set_sha256']):
                raise ValueError(label + ': set_sha256 must be the 64-hex sha256 of the frozen SET')
            source, raw, text = source_bytes(test['set_path'])
            actual = hashlib.sha256(raw).hexdigest()
            if actual != test['set_sha256']:
                raise ValueError(label + ': ' + str(source) + ' is not the frozen SET: its sha256 is ' + actual + ', the plan binds '
                                 + test['set_sha256'] + '. Nothing was prepared.')
            excluded = excluded_source(markers, source, actual)
            if excluded is not None:
                raise Refusal(label + ': ' + str(source) + ' is an export of batch ' + excluded['batch_id'] + ', closed with exclude ('
                              + str(excluded['reason']) + '); an excluded export is never re-tested. Nothing was prepared.',
                              'HOLDUP_SOURCE_EXCLUDED', batch_id=excluded['batch_id'], set_sha256=actual)
            valid = validate_raw(raw, self.c.schema, self.c.policy)       # RISK_NOT_CHOSEN, risk per sequence, schema
            if valid['active_axes']:
                raise ValueError(label + ': a hold-up test runs one frozen SET, but this SET still searches ' + ', '.join(
                    sorted(valid['active_axes'])) + '. Freeze one candidate first (seed-promote fixed.set or an export).')
            values = read_values(raw)
            if values.get('Mode_Operation') != OP_STANDARD:
                raise ValueError(label + ': the SET is not in standard operation mode (Mode_Operation=9)')
            if is_starter(values):
                raise ValueError(label + ': a GOAT starter SET is a blank, not a strategy; build the idea with build-set first')
            self._bias_off(values, label)
            symbol, period, named_by = self._named(source, raw, label, test)
            window = test['window']
            if not isinstance(window, dict) or not {'start', 'end'} <= set(window) or set(window) - {'start', 'end', 'split'}:
                raise ValueError(label + ': window is {start, end[, split]} in broker days, half-open [start, end)')
            start = _day(window['start'], label + ' window.start')
            end = latest_end if window['end'] == 'auto' else _day(window['end'], label + ' window.end')
            if not start < end:
                raise ValueError(label + ': window.start must be before window.end')
            if end > latest_end:
                raise ValueError(label + ': window.end %s reaches into the unfinished week; the latest end is %s (the day after '
                                 'the last closed Friday), or use "auto"' % (end.isoformat(), latest_end.isoformat()))
            split = None
            if window.get('split') is not None:
                split = _day(window['split'], label + ' window.split')
                if not start < split < end:
                    raise ValueError(label + ': window.split must fall inside the window')
            facts = test['tester']
            if not isinstance(facts, dict) or set(facts) != TESTER_KEYS:
                raise ValueError(label + ': tester must give exactly Model, ExecutionMode, Deposit, Currency and Leverage')
            if type(facts['ExecutionMode']) is not int or not 0 <= facts['ExecutionMode'] <= 600000:
                raise ValueError(label + ': ExecutionMode must be a fixed delay 0..600000 ms (a random delay cannot reproduce)')
            if type(facts['Deposit']) not in (int, float) or not facts['Deposit'] > 0:
                raise ValueError(label + ': Deposit must be a positive number')
            alias = 'H' + nonce + '_' + str(index + 1).zfill(5)
            tester = dict(Expert=install['ea_relative_path'], Symbol=symbol, Period=period, Model=facts['Model'],
                          ExecutionMode=facts['ExecutionMode'], Optimization=0, FromDate=_mt5(start), ToDate=_mt5(end), ForwardMode=0,
                          Deposit=facts['Deposit'], Currency=facts['Currency'], Leverage=facts['Leverage'], UseLocal=1, UseRemote=0,
                          UseCloud=0, Visual=0, ShutdownTerminal=1, ReplaceReport=0,
                          Report='MQL5\\Files\\GOATStudio\\HoldupReports\\' + alias + '.htm')
            _validate_single_pass(tester)
            frozen_text, count = re.subn(r'(?m)^EA_Desc=[^\r\n]*', lambda _: 'EA_Desc=' + alias, text)
            if count != 1:
                raise ValueError(label + ': the SET needs exactly one EA_Desc line')
            frozen = b'\xff\xfe' + frozen_text.encode('utf-16-le')
            frozen_values = read_values(frozen)
            if {k: v for k, v in frozen_values.items() if k != 'EA_Desc'} != {k: v for k, v in values.items() if k != 'EA_Desc'}:
                raise ValueError(label + ': freezing changed a trading value')
            identity = sha([variant_id(values), symbol, period, tester['FromDate'], tester['ToDate'], split and split.isoformat(), facts])
            if identity in identities:
                raise ValueError(label + ' repeats another test (same values, symbol, period, window and tester)')
            identities.add(identity)
            sections = {'Common': {'Login': account['login'], 'Server': account['server']}, 'Experts': {'Enabled': 0, 'AllowLiveTrading': 0},
                        'Tester': tester, 'TesterInputs': frozen_values}
            ini = ''
            for section, items in sections.items():
                ini += '[' + section + ']\r\n'
                for key, value in items.items():
                    if any(c in str(value) for c in '\r\n\x00'):
                        raise ValueError(label + ': unsafe startup value ' + key)
                    ini += key + '=' + str(value) + '\r\n'
            config = ini.encode('utf-16')
            exposure = self._exposure(source, text, raw)
            relation = relation_of(start, end, exposure)
            set_path = root / (alias + '.set')
            config_path = Path(install['terminal_data_root']) / 'config/GOATStudio/Holdups' / (alias + '.ini')
            member = dict(member_id=identity, index=index, alias=alias, account=account, tester=tester, frame_target=1,
                          source_path=str(source), source_sha256=actual, set_path=str(set_path),
                          set_sha256=hashlib.sha256(frozen).hexdigest(), config_path=str(config_path),
                          config_sha256=hashlib.sha256(config).hexdigest(), values=frozen_values, variant_id=variant_id(values),
                          window=dict(start=start.isoformat(), end=end.isoformat(), split=split and split.isoformat(),
                                      end_requested=window['end']),
                          named_by=named_by,
                          relation=dict(relation=relation, basis=(exposure or {}).get('basis'),
                                        exposure=None if exposure is None else dict(start=exposure['start'].isoformat(),
                                                                                    end=exposure['end'].isoformat()),
                                        windows=(exposure or {}).get('windows')))
            if strategy_ref is not None:
                member['strategy_ref'] = strategy_ref
            members.append(member)
            payloads.extend([(set_path, frozen), (config_path, config)])
        # Held-out lock (GOAT-EA#145): no member of a locked strategy may read its window (again before each launch).
        from studio_heldout_guard import check_seed_jobs
        check_seed_jobs(self.c, plan, members)
        return members, payloads

    def validate(self, plan):
        """Non-executing check of a hold-up plan and every SET it names: no file, process or terminal effect."""
        members, _ = self._freeze(self.base / 'validation-only', plan)
        return dict(schema_version=1, valid=True, writes=False, native_launch_qualified=False, mode=MODE, plan_sha256=sha(plan),
                    test_count=len(members), tests=[self._preview(m) for m in members[:MAX_PUBLIC]])

    @staticmethod
    def _preview(member):
        tester = member['tester']
        return dict(alias=member['alias'], symbol=tester['Symbol'], period=tester['Period'], model=tester['Model'],
                    window=member['window'], relation=member['relation']['relation'], relation_basis=member['relation']['basis'],
                    source_path=member['source_path'], source_sha256=member['source_sha256'], named_by=member['named_by'])

    def prepare(self, batch_id, plan):
        root = self.path(batch_id)
        if root.exists():
            _, old, _ = self._read(batch_id)
            if old['plan_sha256'] != sha(plan):
                raise ValueError('Hold-up test ID already belongs to a different plan; choose a new ID')
            return self.status(batch_id)
        members, payloads = self._freeze(root, plan)
        manifest = dict(schema_version=1, batch_id=batch_id, installation_sha256=sha(self.c.install), schema_sha256=sha(self.c.schema),
                        plan_sha256=sha(plan), plan=plan, created_unix=self.clock(), members=members, mode=MODE,
                        native_launch_qualified=False)
        if len(json.dumps(manifest).encode('utf-8')) > MAX_MANIFEST_BYTES:
            raise ValueError('Hold-up manifest exceeds 128 MiB; split the plan')
        root.mkdir(parents=True, exist_ok=False)
        self.report_dir().mkdir(parents=True, exist_ok=True)
        for path, raw in payloads:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        write_json(root / 'manifest.json', manifest)
        state = dict(schema_version=1, batch_id=batch_id, manifest_sha256=digest(root / 'manifest.json'), status='prepared', generation=None,
                     members=[dict(member_id=m['member_id'], alias=m['alias'], status='pending', attempts=0, result=None) for m in members])
        self._save(root, state)
        return self.status(batch_id) | dict(preview=[self._preview(m) for m in members[:MAX_PUBLIC]])

    # ---- native hooks ---------------------------------------------------------------------------------
    def _verify_prepared(self, batch_id, manifest):
        """Hold-up members are single Optimization=0 passes with no axes; nothing to refuse here."""

    def _outputs(self, member):
        path = self.report_dir() / (member['alias'] + '.htm')
        return [path] if path.is_file() else []

    def _own_output(self, spec, item):
        """The member's own report, in HoldupReports, not a link, written after its start. (path, reason)."""
        paths = self._outputs(spec)
        if not paths:
            return None, 'No report from this test exists; nothing is inferred'
        path = paths[0]
        try:
            if path.is_symlink() or not path.is_file():
                return None, 'The test report is a link or not a regular file'
            if path.resolve().parent != self.report_dir().resolve():
                return None, 'The test report is outside its report folder'
            if path.stat().st_mtime < item.get('started_unix', 0) - 2:
                return None, 'The test report predates its start'
        except OSError as exc:
            return None, 'The test report cannot be read (' + str(exc) + ')'
        return path, None

    @staticmethod
    def _retain(raw, target):
        """Create-only write into the hold-up folder; an existing file must be exactly these bytes."""
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('A different retained copy already exists: ' + target.name)
            return
        with target.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())

    def _read(self, batch_id):
        """The seed checks, plus each completed test's retained deal list (Codex P2 on GOAT-EA#161)."""
        root, manifest, state = super()._read(batch_id)
        for item in state['members']:
            if item.get('result'):
                result = read_seed_json(item['result']['path'], MAX_RESULT_BYTES)
                deals = Path(result['deals_path'])
                if deals.parent != root or not deals.is_file() or digest(deals) != result['deals_sha256']:
                    raise ValueError('Retained hold-up deal list changed: ' + item['alias'])
        return root, manifest, state

    def _before_start(self, spec):
        """A pre-B38 EA never starts a hold-up member (goatai#2350 6089668580); otherwise the seed checks."""
        from studio_installed_build import refuse_pre_b38
        refuse_pre_b38(self.c.install)
        return super()._before_start(spec)

    def _installed_build_id(self):
        """The one installed-build resolver (studio_installed_build via CatchupRunner): the build of the installed
        binary, or None when it cannot be stated (an unpinned binary, or a fresh activation status that disagrees).
        A hold-up result records it as identity; it never decides comparability, so it never fails a collection."""
        from studio_catchup import CatchupRunner
        return CatchupRunner._installed_build_id(self, strict=False)

    def _collect(self, path, spec, manifest):
        """Parse and check MT5's report, keep its copy and the deal list, and build the hold-up result."""
        from studio_catchup_verdict import model_tag
        root = self.path(manifest['batch_id'])
        report = tester_report.read_report(path)
        tester = spec['tester']
        checks = tester_report.check(report, values=spec['values'], schema=self.c.schema,
                                     expert=Path(self.c.install['ea_relative_path'].replace('\\', '/')).stem,
                                     symbol=tester['Symbol'], period=tester['Period'], from_date=tester['FromDate'],
                                     to_date=tester['ToDate'], deposit=tester['Deposit'], currency=tester['Currency'],
                                     leverage=tester['Leverage'])
        copy = root / (spec['alias'] + '.report.htm')
        self._retain(Path(path).read_bytes(), copy)
        if digest(copy) != report['sha256']:
            raise ValueError('The retained report copy differs from the report that was checked')
        deals_path = root / (spec['alias'] + '.deals.json')
        # Derived from the checked report and written create-only: an earlier interrupted collection must have
        # left exactly these bytes, never a stale or edited deal list.
        self._retain((json.dumps(dict(schema='goat-holdup-deals-v1', alias=spec['alias'], report_sha256=report['sha256'],
                                      deals=tester_report.deal_rows(report)), sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8'),
                     deals_path)
        per_week, daily, segments = tester_report.deal_views(report, split=spec['window'].get('split'))
        figures = tester_report.metrics(report)
        quality = report['history_quality_pct']
        relation = spec['relation']['relation']
        evidence, evidence_reason = evidence_hint(relation, quality=quality, model=tester['Model'])
        tag = model_tag(tester['Model'], tester['Period'], source='holdup_plan')
        summary = dict(net=figures['net'], trades=figures['trades'], pf=figures['profit_factor'], win_rate_pct=figures['win_rate_pct'],
                       equity_dd_relative_pct=figures['equity_dd_relative_pct'], equity_dd_max_money=figures['equity_dd_max_money'],
                       history_quality_pct=quality, relation=relation, evidence_role=(evidence or {}).get('role'),
                       evidence_offered=evidence is not None, model=tester['Model'], model_rung=tag['model_rung'],
                       plain='%s %s %s to %s: net %s over %d trades, PF %s, max equity drawdown %s%% (MT5, %s). %s' % (
                           tester['Symbol'], tester['Period'], spec['window']['start'], spec['window']['end'], figures['net'],
                           figures['trades'], figures['profit_factor'], figures['equity_dd_relative_pct'],
                           report['history_quality_text'], evidence_reason or ('Offered as %s evidence (%s).' % (evidence['role'], evidence['level']))))
        return dict(schema=RESULT_SCHEMA, schema_version=1, status='verified_holdup_test', holdup_id=manifest['batch_id'],
                    alias=spec['alias'], member_id=spec['member_id'], path=str(copy), sha256=report['sha256'],
                    mt5_report_path=str(path), deals_path=str(deals_path), deals_sha256=digest(deals_path),
                    identity=dict(set_path=spec['source_path'], set_sha256=spec['source_sha256'], variant_id=spec['variant_id'],
                                  frozen_set_sha256=spec['set_sha256'], config_sha256=spec['config_sha256'],
                                  installed_ea_sha256=self.c.install['ea_sha256'], installed_build_id=self._installed_build_id(),
                                  mt5_build=report['mt5_build'], report_server=report['server'], server=spec['account']['server']),
                    conditions=dict(symbol=tester['Symbol'], period=tester['Period'], model=tester['Model'], model_tag=tag,
                                    window=dict(start=spec['window']['start'], end=spec['window']['end']), split=spec['window'].get('split'),
                                    deposit=tester['Deposit'], currency=tester['Currency'], leverage=tester['Leverage'],
                                    execution_mode=tester['ExecutionMode'], history_quality_pct=quality,
                                    history_quality_text=report['history_quality_text'], company=report['settings']['company']),
                    metrics=figures, per_week=per_week, daily=daily, segments=segments, checks=checks,
                    relation=spec['relation'], evidence=evidence, evidence_reason=evidence_reason, strategy_ref=spec.get('strategy_ref'),
                    writes=dict(export=False, promotion=False, library=False, ledger=False, catalog=False),
                    native_launch_qualified=False, scope=SCOPE, summary=summary)

    # ---- reports --------------------------------------------------------------------------------------
    def report(self, batch_id):
        self.status(batch_id)
        root, manifest, state = self._read(batch_id)
        rows = []
        for spec, item in zip(manifest['members'], state['members']):
            result = read_seed_json(item['result']['path']) if item.get('result') else None
            rows.append(dict(alias=spec['alias'], status=item['status'], symbol=spec['tester']['Symbol'], period=spec['tester']['Period'],
                             model=spec['tester']['Model'], window=spec['window'], set_path=spec['source_path'],
                             set_sha256=spec['source_sha256'], relation=spec['relation']['relation'],
                             summary=result['summary'] if result else None, metrics=result['metrics'] if result else None,
                             segments=result['segments'] if result else None, per_week=result['per_week'] if result else None,
                             evidence=result['evidence'] if result else None, evidence_reason=result['evidence_reason'] if result else None,
                             result_path=item['result']['path'] if result else None, report_path=result['path'] if result else None,
                             deals_path=result['deals_path'] if result else None, error=item.get('error')))
        value = dict(schema_version=1, batch_id=batch_id, mode=MODE, status=state['status'], members=rows,
                     stopped_reason=state.get('stopped_reason'), failed_members=state.get('failed_members'),
                     native_launch_qualified=False, scope=SCOPE)
        write_json(root / 'report.json', value)
        if len(rows) > MAX_PUBLIC:
            return {k: v for k, v in value.items() if k != 'members'} | dict(member_count=len(rows), members_omitted=True,
                                                                             report_path=str(root / 'report.json'))
        return value | dict(report_path=str(root / 'report.json'))
