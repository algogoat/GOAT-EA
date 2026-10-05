"""MT5's own single-test report (Strategy Tester Report HTML), read and checked without trusting the EA.

A hold-up test (studio_holdup) runs one frozen SET as one MT5 tester pass with ``Report=...htm``. MT5 then
writes its usual report: a Settings table (Expert, Symbol, Period with dates, every input as
``name=value``, Company, Currency, Initial Deposit, Leverage), Results, Orders and Deals. This module
reads that file (UTF-16 or UTF-8), checks it against what was frozen, and reconciles it with itself:

* the report's inputs are exactly the frozen SET's inputs, value for value (so MT5 ran the bound bytes);
* Expert, Symbol, Period, dates, deposit, currency and leverage are the frozen tester settings;
* every deal's balance is the previous balance plus its commission, swap and profit; the deal totals
  equal the totals row and Total Net Profit; the last balance is the deposit plus the net; the trading
  deal count is Total Deals and the closing deals are Total Trades.

Drawdown is MT5's own (equity and balance, over the tested model's ticks), never the EA CSV. Only
English reports are read: another MT5 language refuses with a plain reason (as CTRL-046).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re

MAX_REPORT_BYTES = 64 * 1024 * 1024
DEAL_COLUMNS = ['Time', 'Deal', 'Symbol', 'Type', 'Direction', 'Volume', 'Price', 'Order', 'Commission', 'Swap', 'Profit',
                'Balance', 'Comment']
TRADING_TYPES = frozenset(('buy', 'sell'))
CLOSING = frozenset(('out', 'in/out', 'out by'))
DIRECTIONS = frozenset(('in', 'out', 'in/out', 'out by'))
CENT = Decimal('0.01')
TOLERANCE = Decimal('0.011')        # report money is printed to the cent
SETTINGS = ('Expert:', 'Symbol:', 'Period:', 'Company:', 'Currency:', 'Initial Deposit:', 'Leverage:')
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
NOT_ENGLISH = ('This MT5 report is not in English (its labels were not found), so GOAT cannot read it. Switch MT5 to '
               'English (View > Languages > English), restart MT5 and run the test again.')


class _Rows(HTMLParser):
    """Every table row as a list of cell texts (entities decoded, whitespace trimmed)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(''.join(self.cell).replace('\xa0', ' ').strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def money(text):
    """'100 000.00' -> Decimal; '' -> None."""
    cleaned = (text or '').replace(' ', '').replace('\xa0', '')
    if cleaned == '':
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError('MT5 report number unreadable: ' + repr(text)) from None
    if not value.is_finite():
        raise ValueError('MT5 report number unreadable: ' + repr(text))
    return value


def pair(text):
    """'1 960.36 (1.96%)' or '1.96% (1 960.36)' or '55 (42.97%)' -> (first, second) without the % signs."""
    match = re.fullmatch(r'\s*([-\d .]+?)%?\s*\(\s*([-\d .]+?)%?\s*\)\s*', text or '')
    if not match:
        raise ValueError('MT5 report value unreadable: ' + repr(text))
    return money(match[1]), money(match[2])


def _f(value):
    return None if value is None else float(value)


def _int(value):
    if value is None or value != value.to_integral_value():
        raise ValueError('MT5 report count unreadable: ' + repr(value))
    return int(value)


def _labels(rows):
    """label -> value for every 'Label:' cell followed by a value cell (first occurrence wins)."""
    found = {}
    for row in rows:
        for index in range(len(row) - 1):
            if row[index].endswith(':') and row[index] not in found:
                found[row[index]] = row[index + 1]
    return found


def _inputs(rows):
    """The Settings table's inputs, in order: the 'Inputs:' row, then rows with an empty label until 'Company:'."""
    start = next((i for i, row in enumerate(rows) if row and row[0] == 'Inputs:'), None)
    if start is None:
        raise ValueError(NOT_ENGLISH)
    entries = [rows[start][1] if len(rows[start]) > 1 else '']
    for row in rows[start + 1:]:
        if not row or row[0] != '' or len(row) != 2:
            break
        entries.append(row[1])
    values = {}
    for entry in entries:
        name, sep, value = entry.partition('=')
        if not sep or not NAME.fullmatch(name):
            continue        # group separators such as '=====GENERAL SETTINGS=====   ='
        if name in values:
            raise ValueError('MT5 report lists input ' + name + ' twice')
        values[name] = value
    return values


def _deals(rows):
    start = next((i for i, row in enumerate(rows) if row == ['Deals']), None)
    if start is None or start + 1 >= len(rows) or rows[start + 1] != DEAL_COLUMNS:
        raise ValueError('MT5 report has no Deals table with the expected columns')
    deals, totals = [], None
    for row in rows[start + 2:]:
        if len(row) != len(DEAL_COLUMNS):
            totals = row
            break
        record = dict(zip(DEAL_COLUMNS, row))
        try:
            when = datetime.strptime(record['Time'], '%Y.%m.%d %H:%M:%S')
            number = int(record['Deal'])
        except ValueError:
            raise ValueError('MT5 report deal row unreadable: ' + ' | '.join(row)) from None
        kind, direction = record['Type'], record['Direction']
        if kind in TRADING_TYPES and direction not in DIRECTIONS:
            raise ValueError('MT5 report deal %d has an unknown direction %r' % (number, direction))
        deals.append(dict(time=when.strftime('%Y-%m-%d %H:%M:%S'), deal=number, symbol=record['Symbol'], type=kind,
                          direction=direction, volume=money(record['Volume']), price=money(record['Price']),
                          order=record['Order'], commission=money(record['Commission']) or Decimal(0),
                          swap=money(record['Swap']) or Decimal(0), profit=money(record['Profit']) or Decimal(0),
                          balance=money(record['Balance']), comment=record['Comment']))
    if totals is None or len([c for c in totals if c != '']) < 4:
        raise ValueError('MT5 report Deals table has no totals row')
    numbers = [money(c) for c in totals if c != '']
    return deals, dict(commission=numbers[0], swap=numbers[1], profit=numbers[2], balance=numbers[3])


def read_report(path, *, limit=MAX_REPORT_BYTES):
    """Parse one MT5 single-test report. Raises ValueError with a plain reason; never guesses a value."""
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('MT5 report exceeds %d MiB' % (limit // (1024 * 1024)))
    try:
        text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('MT5 report is not UTF-16 or UTF-8 text') from None
    parser = _Rows()
    parser.feed(text)
    parser.close()
    rows = parser.rows
    if not any(row == ['Strategy Tester Report'] for row in rows[:3]):
        raise ValueError(NOT_ENGLISH if '<html' in text[:4096].lower() else 'Not an MT5 Strategy Tester report')
    labels = _labels(rows)
    missing = [key for key in SETTINGS + ('Total Net Profit:', 'Total Trades:', 'Total Deals:', 'History Quality:') if key not in labels]
    if missing:
        raise ValueError(NOT_ENGLISH + ' Missing: ' + ', '.join(missing))
    period = re.fullmatch(r'(\S+) \((\d{4}\.\d{2}\.\d{2}) - (\d{4}\.\d{2}\.\d{2})\)', labels['Period:'])
    if not period:
        raise ValueError('MT5 report Period unreadable: ' + labels['Period:'])
    server = next((m for m in (re.fullmatch(r'(.+) \(Build (\d+)\)', row[0]) for row in rows[:4] if len(row) == 1) if m), None)
    quality = re.match(r'\s*(\d+(?:\.\d+)?)\s*%', labels['History Quality:'])
    deals, totals = _deals(rows)
    equity_max, balance_max = pair(labels.get('Equity Drawdown Maximal:')), pair(labels.get('Balance Drawdown Maximal:'))
    equity_rel, balance_rel = pair(labels.get('Equity Drawdown Relative:')), pair(labels.get('Balance Drawdown Relative:'))
    won = pair(labels.get('Profit Trades (% of total):'))
    short, long_ = pair(labels.get('Short Trades (won %):')), pair(labels.get('Long Trades (won %):'))
    results = dict(
        net=money(labels['Total Net Profit:']), gross_profit=money(labels.get('Gross Profit:')), gross_loss=money(labels.get('Gross Loss:')),
        profit_factor=money(labels.get('Profit Factor:')), expected_payoff=money(labels.get('Expected Payoff:')),
        recovery_factor=money(labels.get('Recovery Factor:')), sharpe_ratio=money(labels.get('Sharpe Ratio:')),
        trades=_int(money(labels['Total Trades:'])), deals=_int(money(labels['Total Deals:'])),
        profit_trades=_int(won[0]), win_rate_pct=won[1], short_trades=_int(short[0]), short_won_pct=short[1],
        long_trades=_int(long_[0]), long_won_pct=long_[1],
        largest_profit_trade=money(labels.get('Largest profit trade:')), largest_loss_trade=money(labels.get('Largest loss trade:')),
        equity_dd_max_money=equity_max[0], equity_dd_max_pct=equity_max[1], equity_dd_relative_pct=equity_rel[0],
        equity_dd_relative_money=equity_rel[1], balance_dd_max_money=balance_max[0], balance_dd_max_pct=balance_max[1],
        balance_dd_relative_pct=balance_rel[0], balance_dd_relative_money=balance_rel[1],
        balance_dd_absolute=money(labels.get('Balance Drawdown Absolute:')), equity_dd_absolute=money(labels.get('Equity Drawdown Absolute:')),
        bars=_int(money(labels['Bars:'])) if labels.get('Bars:') else None, ticks=_int(money(labels['Ticks:'])) if labels.get('Ticks:') else None)
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
                server=server[1] if server else None, mt5_build=int(server[2]) if server else None,
                settings=dict(expert=labels['Expert:'], symbol=labels['Symbol:'], period=period[1],
                              from_date=period[2], to_date=period[3], company=labels['Company:'], currency=labels['Currency:'],
                              deposit=money(labels['Initial Deposit:']), leverage=labels['Leverage:']),
                inputs=_inputs(rows), results=results, deals=deals, totals=totals,
                history_quality_text=labels['History Quality:'],
                history_quality_pct=float(quality[1]) if quality else None)


# ---------------------------------------------------------------------------
# Checks against the frozen member, and the report's own arithmetic
# ---------------------------------------------------------------------------

def _same_input(name, frozen, reported, definition):
    """Does MT5's printed value equal the frozen SET value? Only the value field of a SET tuple counts."""
    kind = (definition or {}).get('type')
    if kind == 'string' or definition is None:
        return frozen.strip() == reported.strip()
    value = frozen.split('||')[0].strip()
    reported = reported.strip()
    if kind == 'bool':
        truth = {'true': True, '1': True, 'false': False, '0': False}
        return value.lower() in truth and reported.lower() in truth and truth[value.lower()] == truth[reported.lower()]
    if kind == 'datetime':
        def moment(text):
            for fmt in ('%Y.%m.%d %H:%M:%S', '%Y.%m.%d %H:%M', '%Y.%m.%d'):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            return None
        return moment(value) is not None and moment(value) == moment(reported)
    try:
        a, b = Decimal(value), Decimal(reported)
    except InvalidOperation:
        return False
    if kind in ('double', 'float'):
        # MT5 prints doubles with up to 8 decimals; a difference beyond that is a different value.
        return abs(a - b) <= Decimal('0.000000005') * max(Decimal(1), abs(a))
    return a == b


def check(report, *, values, schema, expert, symbol, period, from_date, to_date, deposit, currency, leverage):
    """Every check of one report against its frozen member. Returns the checks; raises one ValueError naming
    every failure (a member with a failed check keeps no result: it fails with this reason)."""
    problems = []
    definitions = schema.get('inputs') or {}
    reported = report['inputs']
    missing = sorted(set(values) - set(reported))
    extra = sorted(set(reported) - set(values))
    if missing:
        problems.append('the report does not list frozen input(s) ' + ', '.join(missing[:8]))
    if extra:
        problems.append('MT5 ran input(s) the frozen SET does not set: ' + ', '.join(extra[:8]))
    differ = [name for name in values if name in reported and not _same_input(name, values[name], reported[name], definitions.get(name))]
    if differ:
        problems.append('MT5 ran different inputs than the frozen SET: ' + '; '.join(
            '%s frozen %s, ran %s' % (name, values[name].split('||')[0], reported[name]) for name in differ[:8]))
    settings = report['settings']
    expected = dict(expert=expert, symbol=symbol, period=period, from_date=from_date, to_date=to_date, currency=currency,
                    leverage=leverage)
    for key, value in expected.items():
        if str(settings[key]) != str(value):
            problems.append('report %s is %s, the frozen test ran %s' % (key.replace('_', ' '), settings[key], value))
    if settings['deposit'] is None or abs(settings['deposit'] - Decimal(str(deposit))) > TOLERANCE:
        problems.append('report initial deposit is %s, the frozen test used %s' % (settings['deposit'], deposit))
    deals, totals, results = report['deals'], report['totals'], report['results']
    if not deals or deals[0]['type'] != 'balance':
        problems.append('the report\'s first deal is not the initial balance')
    cash = [d for d in deals[1:] if d['type'] not in TRADING_TYPES]
    if cash:
        problems.append('the report has non-trading cash deals (%s); GOAT reads only a plain deposit and trades'
                        % ', '.join(sorted({d['type'] for d in cash})))
    trading = [d for d in deals if d['type'] in TRADING_TYPES]
    chain = True
    previous = deals[0]['balance'] if deals else None
    for deal in deals[1:]:
        if previous is None or deal['balance'] is None or abs(previous + deal['commission'] + deal['swap'] + deal['profit']
                                                                 - deal['balance']) > TOLERANCE:
            chain = False
            break
        previous = deal['balance']
    if not chain:
        problems.append('deal %s balance does not follow from the previous balance' % deal['deal'])
    sums = dict(commission=sum((d['commission'] for d in trading), Decimal(0)), swap=sum((d['swap'] for d in trading), Decimal(0)),
                profit=sum((d['profit'] for d in trading), Decimal(0)))
    net = sums['commission'] + sums['swap'] + sums['profit']
    totals_match = all(abs(sums[k] - totals[k]) <= TOLERANCE for k in sums) and deals and abs(deals[-1]['balance'] - totals['balance']) <= TOLERANCE
    if not totals_match:
        problems.append('the deal rows do not add up to the report\'s totals row')
    net_reconciles = abs(net - results['net']) <= TOLERANCE
    if not net_reconciles:
        problems.append('the deals add up to %s, the report says Total Net Profit %s' % (net.quantize(CENT), results['net']))
    balance_reconciles = bool(deals) and settings['deposit'] is not None and abs(deals[-1]['balance'] - settings['deposit'] - results['net']) <= TOLERANCE
    if not balance_reconciles:
        problems.append('the last balance is not the deposit plus Total Net Profit')
    deals_match = len(trading) == results['deals']
    if not deals_match:
        problems.append('%d trading deals listed, the report says Total Deals %d' % (len(trading), results['deals']))
    closes = sum(d['direction'] in CLOSING for d in trading)
    trades_match = closes == results['trades']
    if not trades_match:
        problems.append('%d closing deals listed, the report says Total Trades %d' % (closes, results['trades']))
    if problems:
        raise ValueError('The MT5 report did not pass the hold-up checks: ' + '; '.join(problems) + '.')
    return dict(inputs_match=True, inputs_checked=len(values), settings_match=True, balance_chain=True, totals_match=True,
                net_reconciles=True, balance_reconciles=True, deals_match=True, trades_match=True)


# ---------------------------------------------------------------------------
# Derived views of the deal list (realised P/L by broker day and week; segments)
# ---------------------------------------------------------------------------

def _deal_net(deal):
    return deal['commission'] + deal['swap'] + deal['profit']


def _segment(deals, opening_balance):
    gains = sum((_deal_net(d) for d in deals if _deal_net(d) > 0), Decimal(0))
    losses = -sum((_deal_net(d) for d in deals if _deal_net(d) < 0), Decimal(0))
    peak, worst, worst_pct = opening_balance, Decimal(0), Decimal(0)
    for deal in deals:
        peak = max(peak, deal['balance'])
        drop = peak - deal['balance']
        if drop > worst:
            worst, worst_pct = drop, (drop / peak * 100 if peak > 0 else Decimal(0))
    return dict(net=_f(sum((_deal_net(d) for d in deals), Decimal(0)).quantize(CENT)), deals=len(deals),
                closed_trades=sum(d['direction'] in CLOSING for d in deals),
                pf=None if losses == 0 else round(float(gains / losses), 4), pf_basis='deal net (commission + swap + profit)',
                balance_dd_money=_f(worst.quantize(CENT)), balance_dd_pct=round(float(worst_pct), 4),
                dd_basis='closed balance only (MT5 equity drawdown needs the whole test)')


def deal_views(report, *, split=None):
    """per_week, daily and (with ``split``, a date) segments, from the trading deals. Realised P/L only."""
    deals = [d for d in report['deals'] if d['type'] in TRADING_TYPES]
    opening = report['deals'][0]['balance'] if report['deals'] else Decimal(0)
    weeks, days = {}, {}
    for deal in deals:
        day = date.fromisoformat(deal['time'][:10])
        monday = (day - timedelta(days=day.weekday())).isoformat()
        week = weeks.setdefault(monday, dict(week_start=monday, net=Decimal(0), deals=0, closed_trades=0))
        week['net'] += _deal_net(deal); week['deals'] += 1; week['closed_trades'] += deal['direction'] in CLOSING
        entry = days.setdefault(day.isoformat(), dict(day=day.isoformat(), net=Decimal(0), balance_close=None))
        entry['net'] += _deal_net(deal); entry['balance_close'] = deal['balance']
    per_week = [dict(w, net=_f(w['net'].quantize(CENT))) for _, w in sorted(weeks.items())]
    daily = [dict(d, net=_f(d['net'].quantize(CENT)), balance_close=_f(d['balance_close'])) for _, d in sorted(days.items())]
    segments = None
    if split is not None:
        cut = split.isoformat() if isinstance(split, date) else str(split)
        before = [d for d in deals if d['time'][:10] < cut]
        after = [d for d in deals if d['time'][:10] >= cut]
        opening_after = before[-1]['balance'] if before else opening
        segments = dict(split=cut, before=_segment(before, opening), after=_segment(after, opening_after))
    return per_week, daily, segments


def metrics(report):
    """MT5's own result figures as plain numbers (drawdown from MT5's equity/balance, never the EA CSV)."""
    return {key: (_f(value) if isinstance(value, Decimal) else value) for key, value in report['results'].items()}


def deal_rows(report):
    """The full deal list as JSON-safe rows (money as strings to the cent, exactly as MT5 printed it)."""
    def text(value):
        return None if value is None else str(value)
    return [dict(d, volume=text(d['volume']), price=text(d['price']), commission=text(d['commission']), swap=text(d['swap']),
                 profit=text(d['profit']), balance=text(d['balance'])) for d in report['deals']]
