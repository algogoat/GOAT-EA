"""Evidence end date: the last broker day that exported evidence covers ("front OOS" end).

AUTO is the most recent fully closed trading week, ending at the broker's last
Friday close. MT5 FX servers (Darwinex and most brokers) keep New York close
time: UTC+2 while New York is on standard time and UTC+3 during US daylight
saving, so the FX week closes at server Saturday 00:00 (Friday 17:00 New York).
A broker day is closed once the server date has rolled over. On a Friday, before
that rollover, AUTO is therefore the previous Friday. A Friday that is a full
market holiday closes with Thursday, so on that Friday AUTO is the same day.

Evidence end dates are inclusive broker server calendar dates. MT5 tester
``ToDate`` is exclusive (a test with ToDate=2026.09.18 ends at 2026.09.17
23:59:58 server time), so a test whose evidence ends on day D uses ToDate D+1.
Current EA builds have no EvidenceEnd export setting: a batch export uses
ToDate = the EA's own "last Friday" (GetLastFridayDate, today when today is
Friday), so its evidence ends on a Thursday. OOS catch-up (studio_catchup) sets
ToDate itself, so it reaches any closed day with the current EA.

AUTO_DAY (``auto_day``, rule goat-closed-day-v1) is the latest closed trading day: evidence for
live decisions runs to the latest closed day (goatai#1885 comment 6008215775). Only OOS
catch-up accepts it (``resolve(..., allow_day=True)``); exports and optimization windows stay
Friday-anchored and refuse it.

Nothing here reads or changes MT5 or controller state, except ``ea_capability``
and ``history_check``, which only read bounded local files.
"""
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path, PureWindowsPath
import re

RULE = 'goat-closed-week-v1'
# Evidence for live decisions runs to the latest CLOSED DAY (Vince via Claude-Mac, goatai#1885 comment
# 6008215775): OOS catch-up only may end on the last closed trading day (``auto_day``). Exports and the
# optimization windows stay Friday-anchored, so ``resolve`` refuses ``auto_day`` unless ``allow_day``.
DAY_RULE = 'goat-closed-day-v1'
AUTO_DAY = 'auto_day'
CAPABILITY = 'goat-evidence-end-v1'
DEFAULT_CLOCK = 'ny-close'
FRIDAY = 4
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
_CLOCK = re.compile(r'utc(?:([+-])(\d{1,2})(?::?(\d{2}))?)?')


def _utc(now):
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise ValueError('Current time must be a datetime')
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def parse_date(text):
    """Explicit ``YYYY-MM-DD`` or MT5 ``YYYY.MM.DD`` broker date."""
    if isinstance(text, date) and not isinstance(text, datetime):
        return text
    if not isinstance(text, str) or not re.fullmatch(r'\d{4}[-.]\d{2}[-.]\d{2}', text.strip()) or text.count('-') not in (0, 2) or text.count('.') not in (0, 2):
        raise ValueError('Evidence end must be auto or a date such as 2026-09-25')
    try:
        return datetime.strptime(text.strip().replace('-', '.'), '%Y.%m.%d').date()
    except ValueError as exc:
        raise ValueError('Evidence end must be a real calendar date such as 2026-09-25') from exc


def mt5(day):
    return day.strftime('%Y.%m.%d')


def label(day):
    return WEEKDAYS[day.weekday()] + ' ' + day.strftime('%b ') + str(day.day)


def _nth_sunday(year, month, nth):
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))


def us_daylight(now_utc):
    """US daylight saving: second Sunday of March 07:00 UTC to first Sunday of November 06:00 UTC."""
    now_utc = _utc(now_utc)
    start = datetime.combine(_nth_sunday(now_utc.year, 3, 2), time(7), tzinfo=timezone.utc)
    end = datetime.combine(_nth_sunday(now_utc.year, 11, 1), time(6), tzinfo=timezone.utc)
    return start <= now_utc < end


def parse_clock(clock):
    """'ny-close' (default) or a fixed broker offset such as 'utc+2', 'utc+3:00', 'utc-5', 'utc'."""
    clock = DEFAULT_CLOCK if clock in (None, '') else clock
    if not isinstance(clock, str):
        raise ValueError('Broker clock must be ny-close or utc+H')
    clock = clock.strip().lower()
    if clock == DEFAULT_CLOCK:
        return dict(kind='ny-close', name=DEFAULT_CLOCK)
    match = _CLOCK.fullmatch(clock)
    if not match:
        raise ValueError('Broker clock must be ny-close or a fixed offset such as utc+2')
    sign, hours, minutes = match.groups()
    offset = 0 if sign is None else (1 if sign == '+' else -1) * (int(hours) * 60 + int(minutes or 0))
    if not -14 * 60 <= offset <= 14 * 60:
        raise ValueError('Broker clock offset must be within UTC-14..UTC+14')
    return dict(kind='fixed', name=clock, offset_minutes=offset)


def offset_minutes(now_utc, clock=DEFAULT_CLOCK):
    clock = parse_clock(clock)
    if clock['kind'] == 'fixed':
        return clock['offset_minutes']
    return 180 if us_daylight(now_utc) else 120


def server_now(now_utc=None, clock=DEFAULT_CLOCK):
    """Broker server wall clock as a naive datetime."""
    now_utc = _utc(now_utc)
    return (now_utc + timedelta(minutes=offset_minutes(now_utc, clock))).replace(tzinfo=None)


def server_to_utc(wall, clock=DEFAULT_CLOCK):
    """UTC instant of a broker server wall time (naive)."""
    guess = (wall - timedelta(minutes=offset_minutes(wall.replace(tzinfo=timezone.utc) - timedelta(hours=2), clock))).replace(tzinfo=timezone.utc)
    return (wall - timedelta(minutes=offset_minutes(guess, clock))).replace(tzinfo=timezone.utc)


def _holidays(values):
    return frozenset(parse_date(value) for value in (values or ()))


def friday_days_back(weekday, friday_holiday=False):
    """Days from broker today back to the Friday that ends the last fully closed week.

    Takes Python's Monday=0..Sunday=6. An EA-side mirror (MQL day_of_week is
    Sunday=0..Saturday=6) must give the same answer; see test_studio_evidence_end.
    """
    back = (weekday - FRIDAY) % 7
    return 7 if back == 0 and not friday_holiday else back


def auto(now_utc=None, *, clock=DEFAULT_CLOCK, holidays=()):
    """The inclusive evidence end of the most recent fully closed trading week."""
    now_utc = _utc(now_utc)
    closed_days = _holidays(holidays)
    wall = server_now(now_utc, clock)
    today = wall.date()
    friday = today - timedelta(days=friday_days_back(today.weekday(), today in closed_days))
    last_session = friday
    while last_session in closed_days or last_session.weekday() >= 5:
        last_session -= timedelta(days=1)
    upcoming = friday + timedelta(days=7)
    switch = server_to_utc(datetime.combine(upcoming + timedelta(days=1), time(0)), clock)
    if upcoming in closed_days:
        switch = server_to_utc(datetime.combine(upcoming, time(0)), clock)
    return dict(date=mt5(friday), iso=friday.isoformat(), weekday=WEEKDAYS[friday.weekday()], rule=RULE,
                broker_clock=parse_clock(clock)['name'], server_now=wall.strftime('%Y-%m-%d %H:%M'),
                last_session=mt5(last_session), friday_holiday=friday in closed_days,
                tester_to_date=mt5(friday + timedelta(days=1)),
                next_date=mt5(upcoming), next_switch_utc=switch.isoformat(timespec='minutes').replace('+00:00', 'Z'),
                hint='auto: ' + WEEKDAYS[friday.weekday()] + ' ' + mt5(friday))


def _trading_day(day, closed_days):
    return day.weekday() < 5 and day not in closed_days


def auto_day(now_utc=None, *, clock=DEFAULT_CLOCK, holidays=()):
    """AUTO_DAY: the latest closed trading day (D-1 close), for OOS catch-up only.

    Resolved like AUTO but to the last closed day instead of the last closed Friday: the
    newest Mon-Fri broker day, not a full market holiday, whose server date has rolled over.
    On a Saturday, Sunday or Monday that is the Friday (or the day before a holiday).
    """
    now_utc = _utc(now_utc)
    closed_days = _holidays(holidays)
    wall = server_now(now_utc, clock)
    today = wall.date()
    day = today - timedelta(days=1)
    while not _trading_day(day, closed_days):
        day -= timedelta(days=1)
    upcoming = today if _trading_day(today, closed_days) else today + timedelta(days=1)
    while not _trading_day(upcoming, closed_days):
        upcoming += timedelta(days=1)
    switch = server_to_utc(datetime.combine(upcoming + timedelta(days=1), time(0)), clock)
    return dict(date=mt5(day), iso=day.isoformat(), weekday=WEEKDAYS[day.weekday()], rule=DAY_RULE,
                broker_clock=parse_clock(clock)['name'], server_now=wall.strftime('%Y-%m-%d %H:%M'),
                tester_to_date=mt5(day + timedelta(days=1)), next_date=mt5(upcoming),
                next_switch_utc=switch.isoformat(timespec='minutes').replace('+00:00', 'Z'),
                hint='auto_day: ' + WEEKDAYS[day.weekday()] + ' ' + mt5(day))


def resolve(value=None, now_utc=None, *, clock=DEFAULT_CLOCK, holidays=(), not_before=(), allow_day=False):
    """Resolve ``auto`` (or, with ``allow_day``, ``auto_day``) or validate one explicit evidence end.

    ``not_before`` is a sequence of (date, plain reason) pairs the end may not precede,
    for example each member's optimization end. Explicit overrides must already be
    closed broker days: never today and never in the future. ``auto_day`` (the latest
    closed trading day) is accepted only with ``allow_day`` (OOS catch-up); exports refuse it.
    """
    now_utc = _utc(now_utc)
    automatic = auto(now_utc, clock=clock, holidays=holidays)
    requested = 'auto' if value in (None, '', 'auto', 'AUTO', 'Auto') else value
    warnings = []
    rule = RULE
    day_value = isinstance(requested, str) and requested.strip().lower().replace('-', '_') == AUTO_DAY
    if day_value and not allow_day:
        raise ValueError('auto_day (the latest closed trading day) is for OOS catch-up only. Exports and optimization '
                         'windows end on a closed Friday: use auto (%s) or an explicit Friday.' % automatic['hint'])
    extra = {}
    if requested == 'auto':
        chosen, mode = parse_date(automatic['date']), 'auto'
    elif day_value:
        latest = auto_day(now_utc, clock=clock, holidays=holidays)
        chosen, mode, requested, rule = parse_date(latest['date']), AUTO_DAY, AUTO_DAY, DAY_RULE
        extra['auto_day'] = latest
    else:
        chosen, mode = parse_date(requested), 'explicit'
        today = server_now(now_utc, clock).date()
        if chosen >= today:
            latest = today - timedelta(days=1)
            raise ValueError('Evidence end %s is not a closed broker day yet (broker time %s). The latest closed day is %s; '
                             'auto is %s.' % (chosen.isoformat(), automatic['server_now'], latest.isoformat(), automatic['hint']))
        if chosen.weekday() != FRIDAY:
            warnings.append('%s is not a Friday; evidence ending mid-week compares poorly with weekly files.' % label(chosen))
        if chosen > parse_date(automatic['date']):
            warnings.append('Ends inside the current, unfinished week; the next full week closes %s.' % automatic['next_date'])
    for limit, reason in not_before or ():
        limit = parse_date(limit)
        if chosen < limit:
            raise ValueError('Evidence end %s is before %s (%s); nothing new would be tested.'
                             % (chosen.isoformat(), reason, limit.isoformat()))
    return dict(requested=requested, mode=mode, date=mt5(chosen), iso=chosen.isoformat(), weekday=WEEKDAYS[chosen.weekday()],
                label=label(chosen), tester_to_date=mt5(chosen + timedelta(days=1)), rule=rule, auto=automatic,
                warnings=warnings, **extra)


def effective_end(tester_to_date):
    """``evidenceEndEffective``: the last day an MT5 test actually covers, its exclusive ToDate minus one day (ISO).

    The nominal evidence end is what was asked for; this is what the test covered (Claude-Mac, goatai#1885
    6008626040). A legacy batch export passes the EA's "last Friday" as ToDate, so it really ends on Thursday.
    """
    return (parse_date(tester_to_date) - timedelta(days=1)).isoformat()


def evidence_end_mode(target, *, catch_up=False):
    """The ``evidenceEndMode`` stamp for a resolved end (``resolve``'s result).

    ``auto``, ``auto_day`` and an explicit Friday keep their mode. An explicit NON-Friday is
    ``legacy_explicit`` for an export (kept with its warning for old plans and saved batches,
    never refused; Claude-Mac, goatai#1885 6008569394) and ``explicit_day`` for a catch-up, where
    a closed weekday is the sanctioned latest-closed-day rule (one decision's date, re-used).
    """
    mode = (target or {}).get('mode')
    if mode == 'explicit' and parse_date(target['iso']).weekday() != FRIDAY:
        return 'explicit_day' if catch_up else 'legacy_explicit'
    return mode


def legacy_end(now_utc=None, *, clock=DEFAULT_CLOCK):
    """Inclusive end an EA without EvidenceEnd produces now: ToDate = its last Friday (today if Friday)."""
    today = server_now(now_utc, clock).date()
    to_date = today - timedelta(days=(today.weekday() - FRIDAY) % 7)
    end = to_date - timedelta(days=1)
    return dict(date=mt5(end), iso=end.isoformat(), weekday=WEEKDAYS[end.weekday()], tester_to_date=mt5(to_date),
                basis='ea_clock_last_friday_exclusive',
                note='This EA build ends exports at its own last Friday, which MT5 excludes, so evidence ends on Thursday.')


def ea_capability(install, observation_path):
    """Whether the installed EA's monitor reported the EvidenceEnd capability.

    Reads the bound monitor's last observation (any age: capability is a property of the
    build). The program path must be this installation's EA. Missing or unreadable
    evidence is reported as unsupported, never assumed.
    """
    result = dict(supported=False, capability=CAPABILITY, basis='monitor_observation_missing')
    try:
        path = Path(observation_path)
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            return result
        raw = path.read_bytes()
        observation = json.loads(raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return result | dict(basis='monitor_observation_unreadable')
    runtime = observation.get('runtime') if isinstance(observation, dict) else None
    expected = PureWindowsPath(str(Path(install['terminal_data_root']) / 'MQL5' / 'Experts')) / PureWindowsPath(install['ea_relative_path'])
    if not isinstance(runtime, dict) or not isinstance(runtime.get('program_path'), str) or PureWindowsPath(runtime['program_path']) != expected:
        return result | dict(basis='monitor_program_differs')
    if observation.get('evidence_end') != CAPABILITY:
        return result | dict(basis='monitor_build_lacks_evidence_end')
    return dict(supported=True, capability=CAPABILITY, basis='monitor_observation')


def history_check(install, server, symbol, end_day):
    """Advisory local tick-cache probe for the month that contains the evidence end.

    MT5 downloads missing history when a test starts, so this never refuses work; it
    tells the user the first file may run slower. Reads directory metadata only.
    """
    end_day = parse_date(end_day)
    if not isinstance(server, str) or not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z0-9_. #-]{1,64}', symbol) \
            or not re.fullmatch(r'[A-Za-z0-9_. -]{1,96}', server):
        return dict(status='unknown', symbol=symbol, reason='unsafe server or symbol name')
    folder = Path(install['terminal_data_root']) / 'bases' / server / 'ticks' / symbol
    month = folder / (end_day.strftime('%Y%m') + '.tkc')
    try:
        if not folder.is_dir():
            return dict(status='missing', symbol=symbol, note='No local ticks yet; MT5 downloads them when the test starts (slower first file).')
        if not month.is_file():
            return dict(status='missing', symbol=symbol, note='No local ticks for %s yet; MT5 downloads them when the test starts.' % end_day.strftime('%Y-%m'))
        modified = datetime.fromtimestamp(month.stat().st_mtime, timezone.utc)
    except OSError:
        return dict(status='unknown', symbol=symbol, reason='tick cache unreadable')
    return dict(status='present', symbol=symbol, month=end_day.strftime('%Y-%m'),
                cache_modified_utc=modified.isoformat(timespec='minutes').replace('+00:00', 'Z'),
                note='Local ticks exist for the end month; MT5 still syncs newer ticks at test start.')
