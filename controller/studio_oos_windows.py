"""OOS window formula (goat-oos-windows-v1): every research date from O and the export Friday.

Decided by Vince on 2026-10-05 (goatai#1885, comment 6004797676). It replaces "whatever gap
the export happens to leave". O is the optimization period, SAMPLE + FWD. Oldest to newest:

    BOOS    1/2 O, immediately before SAMPLE     pass/fail only
    SAMPLE  2/3 O                                the optimizer fits here
    FWD     1/3 O                                ranks and picks passes
    FOOS    1/4 O, ending at the export Friday   pass/fail only, never used for ranking

Optimization end = export Friday - FOOS. Every date comes from O and the export Friday.

Units and rounding (deterministic, no month-length rounding)
------------------------------------------------------------
O is counted in whole trading weeks. A plan may give ``optimization_weeks`` or
``optimization_months``; a month is exactly 13/3 weeks (52 weeks a year), rounded half up,
so 3, 6, 12 and 24 months are exactly 13, 26, 52 and 104 weeks. Every window is a whole
number of weeks. BOOS, FWD and FOOS, the windows that judge, are rounded UP, so none is ever
shorter than its exact share of O; SAMPLE = O - FWD takes the rounding, so SAMPLE + FWD = O
exactly. Weeks make every boundary fall on the FX week close and make leap years and month
lengths irrelevant.

Day alignment (studio_evidence_end conventions)
-----------------------------------------------
Dates are broker server calendar days. A week ends at the Friday close (server Saturday
00:00). Every window therefore runs from a Saturday (no FX trading) through a Friday,
inclusive, and every MT5 boundary is a Saturday: MT5 ``FromDate`` is inclusive and
``ToDate`` is exclusive, so ``ToDate`` = the Saturday after the optimization end, exactly
like ``tester_to_date`` = evidence end + 1 day in studio_evidence_end. The export Friday
defaults to AUTO = the latest fully closed Friday (``studio_evidence_end.resolve``).

Holding FOOS out with the EA's existing inputs (no EA change)
-------------------------------------------------------------
The EA's export search ranks and trims sets on metrics measured over the WHOLE export test,
from ``BackOOSDate`` to the export end (GOAT V1.49.mq5 StartExporter: MinSR/MinARF pass test
and SortAndTrimExports). FOOS must never reach that ranking, so a formula batch stages
``EvidenceEnd`` = ``ToDate`` (the Saturday after the optimization end, the earliest end the
EA accepts): its exports stop at the optimization end and contain no FOOS day. FOOS is then
judged by the controller-side held-out replay that already exists, OOS catch-up
(``catchup-prepare`` with ``evidence_end`` = the export Friday): one non-optimized pass of
the frozen exported values, judged only on the days after the export's end. ``judge_retest``
scores that replay with this rule; catch-up weeks after the export Friday count toward FOOS.
Only EA builds that report ``goat-evidence-end-v1`` (FU35+) can stop exports there, so
prepare refuses the formula on older builds.

Pass bar (``judge`` / ``judge_window``): the source of truth
-------------------------------------------------------------
Claude-Mac ruled (goatai#1885 comment 6005864453) that this evaluator is the source of truth;
the desktop sift (goatai#2274) uses the same constants, result names and ``DEFINITIONS``, and
the shared fixture ``controller/fixtures/oos-holdout-gate-cases.json`` pins both to identical
results. Each OOS window needs at least 30 trades (positions opened in the window). Fewer is
``not_eligible_yet``; a window is never shortened to reach the floor. With the floor met a
window passes on PF >= 1.0 AND DD <= 1.5 x in-sample DD (SAMPLE). Results:
``pass | fail | not_eligible_yet | no_data | not_measured``; a missing measurement is
``no_data`` or ``not_measured``, never a pass.

Demo (live test after export) continues FOOS but does not scale with O: see ``DEMO_RULE``.
This module only documents it; nothing here automates demo.

Pure: nothing here reads or writes MT5, terminals or controller state, except
``judge_retest``, which reads the bounded evidence files it is given.
"""
from datetime import date, datetime, timedelta
from fractions import Fraction
import math

RULE = 'goat-oos-windows-v1'
EVALUATION = 'goat-oos-window-rule-v1'
SPEC_KEY = 'oos_windows'
WEEKS_PER_MONTH = Fraction(13, 3)       # 52 weeks a year
MIN_TRADES = 30                         # per OOS window (BOOS and FOOS)
MIN_PF = 1.0                            # PF >= 1.0
MAX_DD_RATIO = Fraction(3, 2)           # DD <= 1.5 x in-sample DD
MONTHS_RANGE = (1, 120)
WEEKS_RANGE = (4, 520)
FRIDAY, SATURDAY = 4, 5
# The gate result names the desktop sift shares (goatai#2274, Claude-Mac #1885 6005864453).
STATUSES = ('pass', 'fail', 'not_eligible_yet', 'no_data', 'not_measured')
FRACTIONS = dict(boos='1/2', sample='2/3', fwd='1/3', foos='1/4')
FIXTURE = 'fixtures/oos-holdout-gate-cases.json'
# The measurement definitions the desktop must match exactly (this controller is the source of truth).
DEFINITIONS = dict(
    days='Broker server calendar days; a window is [first_day 00:00, last_day + 1 day 00:00).',
    trades='Positions opened in the window: entry deals (deal_entry 0) whose time is inside the window; the same count '
           'the EA writes as Trades= in its BOOS/SAMPLE/FWD/FOOS header lines.',
    pl='Net result of the positions opened in the window: the sum of profit + swap + commission + fee over their deals '
       'inside the window (all costs included; a position still open at the window end counts only its deals so far).',
    pf='Those deal results summed where positive, divided by the absolute sum where not positive (deal level). '
       'PF >= 1.0 is exactly pl >= 0, which is what the gate tests; no negative deal result = no losing trades = pass.',
    dd='Equity drawdown in account money: the deepest fall of the sampled equity (one-minute equity rows of the export '
       'or re-test CSV, floating P/L included, not balance) below its running peak, where the peak starts at the '
       'window\'s opening equity (the last sample before the window, else its first sample). The same definition for '
       'SAMPLE (in-sample), BOOS and FOOS.',
    dd_bar='DD <= 1.5 x SAMPLE DD, compared exactly (2 x DD <= 3 x SAMPLE DD). A SAMPLE DD of 0 or unknown leaves no '
           'limit: not_measured.',
    foos='FOOS runs from the Saturday after the optimization end through the export Friday; a catch-up re-test that '
         'runs later extends it to the re-test end (catch-up weeks count toward the 30-trade floor). FOOS is never '
         'judged before its full 1/4 O has been tested.')

DEMO_RULE = dict(
    rule='goat-demo-continuation-v2',
    decided='Vince 2026-10-05, corrected the same day (goatai#1885 comment 6004826858): demo length is calendar time, not '
            'trade count.',
    minimum_weeks=4, minimum_trades=30, decision_due_weeks=6,
    plain=('Demo is the live test after export and continues FOOS, but it does not scale with O. It lasts at least 4 weeks '
           'AND at least 30 trades, and a decision is due by 6 weeks. A set still under 30 trades at 6 weeks is "too slow '
           'to judge here": never promote it on thin data. The 4-week floor makes every set see several weekly cycles and '
           'major releases (NFP, CPI, a central-bank meeting). For M1 and other high-frequency sets the main demo check is '
           'execution parity: live vs backtest over the same weeks, with real spread, slippage and commission. Demo is '
           'judged on PF >= 1.0 plus live vs backtest over the same weeks, at the PORTFOLIO level.'),
    too_slow='too_slow_to_judge_here', judged_at='portfolio', automated=False)


# ---------------------------------------------------------------------------
# Date math
# ---------------------------------------------------------------------------

def _ceil(value):
    return math.ceil(Fraction(value))


def _half_up(value):
    return math.floor(Fraction(value) + Fraction(1, 2))


def optimization_weeks(*, months=None, weeks=None):
    """O in whole weeks from exactly one of ``months`` (x 13/3, half up) or ``weeks``."""
    if (months is None) == (weeks is None):
        raise ValueError('Give O as exactly one of optimization_months or optimization_weeks')
    if weeks is not None:
        if type(weeks) is not int or not WEEKS_RANGE[0] <= weeks <= WEEKS_RANGE[1]:
            raise ValueError('optimization_weeks must be a whole number %d..%d' % WEEKS_RANGE)
        return weeks
    if type(months) is not int or not MONTHS_RANGE[0] <= months <= MONTHS_RANGE[1]:
        raise ValueError('optimization_months must be a whole number %d..%d' % MONTHS_RANGE)
    return _half_up(months * WEEKS_PER_MONTH)


def split(o_weeks):
    """Window lengths in weeks: judging windows rounded up, SAMPLE = O - FWD."""
    if type(o_weeks) is not int or o_weeks < 2:
        raise ValueError('O must be at least 2 whole weeks')
    fwd = _ceil(Fraction(o_weeks, 3))
    return dict(boos=_ceil(Fraction(o_weeks, 2)), sample=o_weeks - fwd, fwd=fwd, foos=_ceil(Fraction(o_weeks, 4)))


def _day(value):
    if isinstance(value, datetime):
        raise ValueError('A broker day (date) is required, not a time')
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value.strip()) == 10:
        return date.fromisoformat(value.strip().replace('.', '-'))
    raise ValueError('A broker day such as 2026-10-02 is required')


def mt5(day):
    return day.strftime('%Y.%m.%d')


def _window(name, role, first, weeks):
    last = first + timedelta(days=7 * weeks - 1)
    return dict(name=name, role=role, weeks=weeks, days=7 * weeks, first_day=first.isoformat(), last_day=last.isoformat(),
                mt5_from=mt5(first), mt5_to_exclusive=mt5(last + timedelta(days=1)))


def compute(o_weeks, export_friday):
    """Every window for O weeks and an export Friday (a date). Pure: no clock, no closed-day check."""
    friday = _day(export_friday)
    if friday.weekday() != FRIDAY:
        raise ValueError('The export Friday must be a Friday; %s is a %s' % (friday.isoformat(), friday.strftime('%A')))
    weeks = split(o_weeks)
    to_date = friday + timedelta(days=1) - timedelta(days=7 * weeks['foos'])      # Saturday, MT5-exclusive optimization end
    forward = to_date - timedelta(days=7 * weeks['fwd'])
    start = to_date - timedelta(days=7 * o_weeks)
    back = start - timedelta(days=7 * weeks['boos'])
    windows = dict(boos=_window('BOOS', 'pass/fail only', back, weeks['boos']),
                   sample=_window('SAMPLE', 'the optimizer fits here', start, weeks['sample']),
                   fwd=_window('FWD', 'ranks and picks passes', forward, weeks['fwd']),
                   foos=_window('FOOS', 'held-out pass/fail only, never used for ranking', to_date, weeks['foos']))
    optimization_end = to_date - timedelta(days=1)
    return dict(rule=RULE, o_weeks=o_weeks, weeks=weeks, export_friday=friday.isoformat(), **windows,
                optimization=dict(first_day=start.isoformat(), last_day=optimization_end.isoformat(), weeks=o_weeks),
                optimization_end=optimization_end.isoformat(),
                tester=dict(FromDate=mt5(start), ToDate=mt5(to_date), ForwardMode=4, ForwardDate=mt5(forward)),
                export=dict(BackOOSDate=mt5(back), IncludeBackOOS=True),
                # The batch export stops here (EvidenceEnd): the earliest end the EA accepts, a Saturday with no FX trading.
                export_evidence_end=to_date.isoformat(),
                seed_tester=dict(FromDate=mt5(start), ToDate=mt5(forward), ForwardMode=0, ForwardDate=''),
                heldout_lock=dict(start=to_date.isoformat(), end=(friday + timedelta(days=1)).isoformat(),
                                  revealableAfter=friday.isoformat()),
                foos_replay=dict(evidence_end=friday.isoformat(), command='catchup-prepare',
                                 plain=('FOOS %s to %s is held out: the batch exports stop at the optimization end %s. After '
                                        'the batch, re-test the kept exports with an OOS catch-up whose evidence_end is %s; '
                                        'its oos_rule judges BOOS and FOOS (30-trade floor, PF >= 1.0, DD <= 1.5x in-sample).'
                                        % (to_date.isoformat(), friday.isoformat(), optimization_end.isoformat(),
                                           friday.isoformat()))))


def request(value):
    """Validate a plan's ``oos_windows`` request: O plus an optional export Friday (default auto)."""
    if not isinstance(value, dict) or not value or set(value) - {'optimization_months', 'optimization_weeks', 'export_friday'}:
        raise ValueError('oos_windows takes optimization_months or optimization_weeks, and optionally export_friday '
                         '("auto" or a closed Friday such as 2026-10-02)')
    weeks = optimization_weeks(months=value.get('optimization_months'), weeks=value.get('optimization_weeks'))
    friday = value.get('export_friday', 'auto')
    if not isinstance(friday, str):
        raise ValueError('oos_windows.export_friday must be "auto" or a date such as 2026-10-02')
    return dict(value, export_friday=friday), weeks


def windows(o, export_friday='auto', *, unit='months', now=None, clock=None, holidays=()):
    """``windows(O, export_friday)``: resolve the export Friday (AUTO = latest closed Friday) and compute every date.

    ``unit`` is 'months' (13/3 weeks each) or 'weeks'. An explicit export Friday must be a
    closed broker Friday (studio_evidence_end.resolve); a non-Friday is refused, never moved.
    """
    from studio_evidence_end import DEFAULT_CLOCK, resolve
    if unit not in ('months', 'weeks'):
        raise ValueError("unit must be 'months' or 'weeks'")
    o_weeks = optimization_weeks(**{unit: o})
    target = resolve(export_friday, now, clock=clock or DEFAULT_CLOCK, holidays=holidays)
    result = compute(o_weeks, date.fromisoformat(target['iso']))
    result['requested'] = {('optimization_' + unit): o, 'export_friday': export_friday}
    result['export_friday_resolution'] = dict(requested=target['requested'], mode=target['mode'], rule=target['rule'],
                                              auto=target['auto']['iso'])
    return result


def from_request(value, *, now=None, clock=None):
    """``windows`` for a validated plan request (``request``)."""
    value, o_weeks = request(value)
    unit, o = (('months', value['optimization_months']) if 'optimization_months' in value
               else ('weeks', value['optimization_weeks']))
    result = windows(o, value['export_friday'], unit=unit, now=now, clock=clock)
    if result['o_weeks'] != o_weeks:
        raise ValueError('O changed while resolving the windows')
    result['requested'] = value
    return result


def same(record):
    """Recompute a recorded window set from its own O and export Friday; refuse any difference."""
    if not isinstance(record, dict) or record.get('rule') != RULE:
        raise ValueError('oos_windows record is not ' + RULE)
    fresh = compute(record.get('o_weeks'), record.get('export_friday'))
    for key, value in fresh.items():
        if record.get(key) != value:
            raise ValueError('oos_windows.%s differs from the formula for O=%s weeks and export Friday %s'
                             % (key, record.get('o_weeks'), record.get('export_friday')))
    return fresh


def tester_from_mt5(tester):
    """FromDate/ForwardDate/ToDate of a tester (MT5 dates) as dates, or None when any is missing."""
    try:
        return tuple(datetime.strptime(tester[key], '%Y.%m.%d').date() for key in ('FromDate', 'ForwardDate', 'ToDate'))
    except (KeyError, TypeError, ValueError):
        return None


def formula_of(tester, back_oos_date):
    """The formula record whose dates these are, or None when they are not formula dates.

    Reads O from ToDate - FromDate and checks FWD and BOOS against the formula; the export
    Friday follows from ToDate and FOOS (it is not checked against any clock).
    """
    days = tester_from_mt5(tester or {})
    try:
        back = datetime.strptime(back_oos_date, '%Y.%m.%d').date()
    except (TypeError, ValueError):
        return None
    if days is None:
        return None
    start, forward, to_date = days
    span = (to_date - start).days
    if to_date.weekday() != SATURDAY or span <= 0 or span % 7:
        return None
    try:
        weeks = split(span // 7)
    except ValueError:
        return None
    friday = to_date - timedelta(days=1) + timedelta(days=7 * weeks['foos'])
    record = compute(span // 7, friday)
    if record['tester'] != dict(FromDate=mt5(start), ToDate=mt5(to_date), ForwardMode=4, ForwardDate=mt5(forward)) \
            or record['export']['BackOOSDate'] != mt5(back):
        return None
    return record


# ---------------------------------------------------------------------------
# Plans: fill explicit dates from the formula (old explicit-date plans are untouched)
# ---------------------------------------------------------------------------

def _fill(target, wanted, where):
    """Set each wanted key; a value the plan already gives must be exactly the formula's."""
    out = dict(target)
    for key, value in wanted.items():
        if key in out and out[key] != value:
            raise ValueError('%s.%s is %r but the OOS window formula gives %r; remove it or use the formula date'
                             % (where, key, out[key], value))
        out[key] = value
    return out


def apply_to_batch_spec(spec, *, now=None, clock=None):
    """(spec with every date explicit, record) for a batch plan carrying ``oos_windows``.

    Members' testers get FromDate, ToDate, ForwardMode=4 and ForwardDate; the export gets
    BackOOSDate and IncludeBackOOS=true; ``evidence_end`` becomes the optimization end's
    exclusive Saturday so the EA's export ranking never sees FOOS. Anything the plan already
    states must equal the formula. A plan without ``oos_windows`` is returned unchanged.
    """
    if SPEC_KEY not in spec:
        return spec, None
    record = from_request(spec[SPEC_KEY], now=now, clock=clock)
    filled = dict(spec)
    filled['export'] = _fill(spec['export'] if isinstance(spec.get('export'), dict) else {}, record['export'], 'export')
    members = []
    for index, member in enumerate(spec.get('members') or []):
        if not isinstance(member, dict) or not isinstance(member.get('tester'), dict):
            raise ValueError('Every member requires set_path and tester settings (optional: strategy_ref)')
        members.append(dict(member, tester=_fill(member['tester'], record['tester'], 'members[%d].tester' % index)))
    filled['members'] = members
    if 'evidence_end' in spec:
        given = spec['evidence_end']
        try:
            same_day = isinstance(given, str) and _day(given) == _day(record['export_evidence_end'])
        except ValueError:
            same_day = False
        if not same_day:
            raise ValueError('evidence_end %r conflicts with oos_windows: a formula batch ends its exports at the '
                             'optimization end (%s) and judges FOOS (%s to %s) with an OOS catch-up; leave evidence_end out'
                             % (given, record['export_evidence_end'], record['foos']['first_day'], record['foos']['last_day']))
    filled['evidence_end'] = record['export_evidence_end']
    return filled, record


def apply_to_seed_plan(plan, *, now=None, clock=None):
    """(plan with explicit dates, record) for a seed plan carrying ``oos_windows``.

    Seed hunts fit candidates, so they read SAMPLE only: FromDate = SAMPLE start, ToDate =
    ForwardDate (exclusive), ForwardMode=0. FWD, BOOS and FOOS stay unseen for the batch
    that ranks and judges the promoted candidates.
    """
    if not isinstance(plan, dict) or SPEC_KEY not in plan:
        return plan, None
    record = from_request(plan[SPEC_KEY], now=now, clock=clock)
    filled = {key: value for key, value in plan.items() if key != SPEC_KEY}
    jobs = []
    for index, job in enumerate(plan.get('jobs') or []):
        if not isinstance(job, dict) or not isinstance(job.get('tester'), dict):
            raise ValueError('Each seed job requires set_path, full tester and frame_target (optional: strategy_ref)')
        jobs.append(dict(job, tester=_fill(job['tester'], record['seed_tester'], 'jobs[%d].tester' % index)))
    filled['jobs'] = jobs
    return filled, record


def verify_native(native, jobs):
    """A frozen native plan's dates must be exactly its recorded formula (prepare and activation)."""
    record = native.get(SPEC_KEY) if isinstance(native, dict) else None
    if record is None:
        return None
    same(record)
    if native.get('back_oos_date') != record['export']['BackOOSDate'] or native.get('forward_start') != record['tester']['ForwardDate']:
        raise ValueError('Native BOOS/forward dates differ from the OOS window formula')
    settings = native.get('export_settings')
    if isinstance(settings, dict) and (settings.get('BackOOSDate') != record['export']['BackOOSDate']
                                       or settings.get('IncludeBackOOS') is not True):
        raise ValueError('Export BOOS settings differ from the OOS window formula')
    for job in jobs or []:
        conditions = job.get('conditions') or {}
        if (conditions.get('from_date'), conditions.get('to_date'), conditions.get('forward_mode')) != (
                record['tester']['FromDate'], record['tester']['ToDate'], 4):
            raise ValueError('A job window differs from the OOS window formula')
    assert_foos_held_out(record, native.get('evidence_end'))
    return record


def assert_foos_held_out(record, evidence_policy):
    """The batch export must stop at the optimization end: EvidenceEnd = ToDate, so no FOOS day is ranked."""
    setting = (evidence_policy or {}).get('ea_setting') if isinstance(evidence_policy, dict) else None
    wanted = mt5(_day(record['export_evidence_end']))
    if not isinstance(setting, dict) or setting.get('value') != wanted or evidence_policy.get('target') != record['export_evidence_end']:
        raise ValueError('FOOS is not held out: a formula batch must stage EvidenceEnd=%s (the optimization end) so the '
                         'EA export ranking never reads FOOS %s to %s'
                         % (wanted, record['foos']['first_day'], record['foos']['last_day']))
    if _day(record['export_evidence_end']) >= _day(record['foos']['first_day']) + timedelta(days=1):
        raise ValueError('The export end reaches into FOOS')
    return True


# ---------------------------------------------------------------------------
# Evaluation: BOOS and FOOS, 30-trade floor, PF and DD bar
# ---------------------------------------------------------------------------

def _pf_test(window):
    """(passes PF >= 1.0, printable PF) or (None, None) when PF cannot be measured.

    PF = gross profit / gross loss of the positions opened in the window, each position's result
    being profit + swap + commission + fee of its deals (costs included). PF >= 1.0 is the same
    test as the net of those results >= 0, so a window with ``pl`` (that net) but no PF is still
    judged; no losing position (PF infinite) passes.
    """
    pf = window.get('pf')
    if pf is None and window.get('pf_note') == 'no losing deals':
        return True, 'no losing trades'
    if isinstance(pf, (int, float)) and not isinstance(pf, bool):
        return pf >= MIN_PF, '%.2f' % pf
    pl = window.get('pl')
    if isinstance(pl, (int, float)) and not isinstance(pl, bool):
        return pl >= 0, ('net %+.2f' % pl)
    return None, None


def _positive(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def judge_window(name, window, in_sample_dd):
    """One OOS window's gate: ``pass | fail | not_eligible_yet | no_data | not_measured`` with reasons.

    ``window``: ``trades`` (positions opened in the window), ``pf`` (or ``pf_note`` 'no losing
    deals', or ``pl``, the net of those positions), ``dd`` (equity drawdown in money), optional
    ``complete`` (False while the window has not fully elapsed or been tested) and
    ``first_day``/``last_day``. In order:

    * no_data: no such window, or no trade count for it.
    * not_eligible_yet: not complete yet, or fewer than 30 trades. Never judged on PF or DD,
      never shortened to reach the floor.
    * fail: a measured PF below 1.0 (net below 0), or a measured DD above 1.5x the in-sample DD.
    * not_measured: PF, the window DD or the in-sample DD (> 0) could not be measured, and
      nothing that was measured failed.
    * pass: PF >= 1.0 and DD <= 1.5x in-sample, both measured.
    """
    result = dict(window=name, status='no_data', reasons=[], min_trades=MIN_TRADES, min_pf=MIN_PF,
                  max_dd_ratio=float(MAX_DD_RATIO), in_sample_dd=in_sample_dd, dd_limit=None)
    if not isinstance(window, dict) or window.get('present') is False:
        result['reasons'] = ['No %s result: the window has not been tested' % name]
        return result
    result.update({key: window.get(key) for key in ('first_day', 'last_day', 'trades', 'pf', 'pf_note', 'pl', 'dd')})
    if window.get('complete') is False:
        result.update(status='not_eligible_yet', reasons=['%s is not complete yet (tested through %s of %s)'
                                                          % (name, window.get('tested_through'), window.get('last_day'))])
        return result
    trades = window.get('trades')
    if type(trades) is not int or trades < 0:
        result['reasons'] = ['No %s trade count (needs a complete deal capture)' % name]
        return result
    if trades < MIN_TRADES:
        result.update(status='not_eligible_yet',
                      reasons=['%d of %d %s trades: too few to judge, so it has not passed or failed yet; the window is '
                               'never shortened to reach the floor' % (trades, MIN_TRADES, name)])
        return result
    pf_ok, pf_text = _pf_test(window)
    dd, base = _number(window.get('dd')), _positive(in_sample_dd)
    failed, missing = [], []
    if pf_ok is False:
        failed.append('%s profit factor below 1.0 (%s) over %d trades' % (name, pf_text, trades))
    elif pf_ok is None:
        missing.append('%s profit factor not measured (needs a complete deal capture)' % name)
    if base is not None:
        result['dd_limit'] = float(MAX_DD_RATIO) * base
    if dd is not None and base is not None:
        # Exact: dd <= 1.5 x in-sample  <=>  2 dd <= 3 in-sample (no float rounding at the bar).
        if not Fraction(dd) * MAX_DD_RATIO.denominator <= Fraction(base) * MAX_DD_RATIO.numerator:
            failed.append('%s drawdown %.2f is above %.2f, 1.5x the in-sample %.2f' % (name, dd, result['dd_limit'], base))
    else:
        missing.append('%s drawdown not measured' % name if dd is None else 'no in-sample (SAMPLE) drawdown to compare with')
    if failed:
        result.update(status='fail', reasons=failed)
    elif missing:
        result.update(status='not_measured', reasons=missing)
    else:
        result.update(status='pass', reasons=['%s passed: %d trades, PF %s, drawdown %.2f within %.2f (1.5x in-sample)'
                                              % (name, trades, pf_text, dd, result['dd_limit'])])
    return result


SET_ORDER = ('fail', 'not_eligible_yet', 'not_measured', 'no_data', 'pass')


def judge(boos, foos, *, in_sample_dd):
    """A set's OOS verdict from its BOOS and FOOS gates (``SET_ORDER``: the first status either window has).

    pass only when both windows pass. A set with fewer than 30 FOOS trades is not eligible yet.
    FWD and SAMPLE never change this verdict except through the in-sample drawdown, and FOOS is
    never a ranking input.
    """
    parts = dict(boos=judge_window('BOOS', boos, in_sample_dd), foos=judge_window('FOOS', foos, in_sample_dd))
    states = [parts['boos']['status'], parts['foos']['status']]
    status = next(s for s in SET_ORDER if s in states)
    reasons = [reason for part in parts.values() if part['status'] == status for reason in part['reasons']]
    words = {'pass': 'Passes', 'fail': 'Fails', 'not_eligible_yet': 'Not eligible yet',
             'not_measured': 'Not measured', 'no_data': 'No hold-out data'}
    return dict(schema=EVALUATION, status=status, reasons=reasons, windows=parts, in_sample_dd=in_sample_dd,
                bar=dict(min_trades=MIN_TRADES, min_pf=MIN_PF, max_dd_ratio=float(MAX_DD_RATIO), in_sample='SAMPLE'),
                used_for_ranking=False, plain=words[status] + ' (OOS window rule): ' + '; '.join(reasons) + '.')


def judge_case(case):
    """Run one shared fixture case (``fixtures/oos-holdout-gate-cases.json``) through the evaluator."""
    def window(raw):
        if raw is None:
            return None
        return dict(present=raw.get('present', True), trades=raw.get('trades'), pf=raw.get('pf'), pf_note=raw.get('pf_note'),
                    pl=raw.get('pl'), dd=raw.get('max_drawdown'), complete=raw.get('complete'))
    if 'window' in case:
        return judge_window(case['window'].upper(), window(case['input']), case.get('in_sample_max_drawdown'))
    return judge(window(case.get('boos')), window(case.get('foos')), in_sample_dd=case.get('in_sample_max_drawdown'))


def not_applicable(reason):
    return dict(schema=EVALUATION, status='not_applicable', reasons=[reason], used_for_ranking=False,
                plain='The OOS window rule does not apply: ' + reason + '.')


def judge_retest(original, retest, *, tester):
    """Score one OOS catch-up re-test (the FOOS held-out replay) with the window rule.

    ``original``/``retest``: studio_evidence.read_export records; ``tester``: the original
    optimization window (FromDate/ForwardDate/ToDate). Applies only when those dates are
    formula dates and the original export stopped at the optimization end (FOOS unseen).

    Measured on the re-test (one non-optimized pass from the BOOS start), with the shared
    definitions (``DEFINITIONS``): trades and PF from its complete deal capture, DD from its
    equity CSV. FOOS is judged from its first day through the re-test's last day: catch-up weeks
    after the export Friday count toward FOOS (they follow the optimization end and are never
    ranked), but FOOS is never judged before its full 1/4 O has been tested.
    """
    from pathlib import Path
    from studio_catchup_verdict import deal_window, equity_rows, equity_window
    # BOOS start: the run's own BackOOSDate, else the export's evidence start (capture request or header).
    back = (original.get('run') or {}).get('back_oos_date') or original.get('evidence_start')
    try:
        back = mt5(_day(back)) if back else None
    except ValueError:
        back = None
    record = formula_of(tester, back)
    if record is None:
        return not_applicable('the optimization dates were not set by the OOS window formula')
    original_end = _day(original['evidence_end'])
    if original_end >= _day(record['foos']['first_day']) + timedelta(days=1):
        return not_applicable('the original export already contained FOOS days (it ends %s), so FOOS was not held out'
                              % original_end.isoformat())
    rows = equity_rows(retest['csv_path'])
    capture = retest.get('capture') or {}
    deals = str(Path(capture['path']).parent / 'deals.csv') if capture.get('complete') and capture.get('path') else None
    if deals and not Path(deals).is_file():
        deals = None
    tested_through = _day(retest['evidence_end'])

    def measure(key, extend=False):
        part = record[key]
        first, last = _day(part['first_day']), _day(part['last_day'])
        complete = tested_through >= last
        if extend and complete:
            last = tested_through        # catch-up weeks count toward FOOS
        window = equity_window(rows, first, last, carry_peak=False)
        out = dict(first_day=first.isoformat(), last_day=last.isoformat(), formula_last_day=part['last_day'], dd=window['dd'],
                   equity_net=window['net'], complete=complete, tested_through=tested_through.isoformat())
        if deals:
            counted = deal_window(deals, first, last)
            out.update(trades=counted['entries'], pf=counted['pf'], pf_note=counted['pf_note'],
                       pl=round(counted['gross_win'] - counted['gross_loss'], 8))
        else:
            out.update(trades=None, pf=None, pf_note='needs a complete capture', pl=None)
        return out

    sample = measure('sample')
    result = judge(measure('boos'), measure('foos', extend=True), in_sample_dd=sample['dd'] if sample['complete'] else None)
    result.update(o_weeks=record['o_weeks'], export_friday=record['export_friday'], trade_source='capture_deals' if deals else 'unavailable',
                  windows_dates={key: dict(first_day=record[key]['first_day'], last_day=record[key]['last_day'])
                                 for key in ('boos', 'sample', 'fwd', 'foos')},
                  foos_judged_through=result['windows']['foos'].get('last_day'), definitions=DEFINITIONS)
    return result
