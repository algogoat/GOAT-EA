"""Validate exported equity samples without claiming full tester/tick coverage."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import re


def inspect_equity_csv(raw):
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise ValueError('Empty or oversized equity CSV')
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    lines = text.splitlines()
    if not lines or lines[0] != '<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>':
        raise ValueError('Unexpected equity CSV header')
    previous = None
    first = last = None
    peak = None
    drawdown = Decimal(0)
    duplicates = 0
    for index, line in enumerate(lines[1:], 2):
        parts = line.split('\t')
        if len(parts) != 4 or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}', parts[0]):
            raise ValueError(f'Invalid equity row {index}')
        stamp = datetime.strptime(parts[0], '%Y.%m.%d %H:%M')
        if previous is not None and stamp < previous:
            raise ValueError(f'Equity timestamps go backwards at row {index}')
        duplicates += int(stamp == previous)
        previous = stamp
        try:
            balance, equity, load = map(Decimal, parts[1:])
        except InvalidOperation as exc:
            raise ValueError(f'Invalid equity number at row {index}') from exc
        if any(not x.is_finite() or abs(x) > Decimal('1e100') for x in (balance, equity, load)) or load < 0:
            raise ValueError(f'Nonfinite or invalid equity metrics at row {index}')
        peak = equity if peak is None else max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        record = dict(timestamp=parts[0], balance=str(balance), equity=str(equity))
        if first is None:
            first = record
        last = record
    if len(lines) < 3:
        raise ValueError('At least two equity samples required')
    return dict(status='EQUITY_SAMPLES_VALID', sha256=hashlib.sha256(raw).hexdigest(),
                samples=len(lines)-1, repeated_minute_timestamps=duplicates, first=first, last=last,
                sampled_balance_change=str(Decimal(last['balance'])-Decimal(first['balance'])),
                sampled_equity_drawdown=str(drawdown), full_replay_coverage_verified=False,
                limits='Sample endpoints and drawdown describe stored observations only; final settlement and between-sample extrema may be absent.')
