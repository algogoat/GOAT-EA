"""Read-only broker-fit report tools (GOAT-EA#228 round 5, goatai#2350 6133583699 / 6133766503). Never writes a file,
never touches MT5, never reads outside the paths it is given.

  python studio_broker_fit_impact.py start-lots --traces <folder> --member-reference <json>
      The reference start lot of each member from its reference backtest traces: the opening lot of the first trade of
      every sequence of that member's strategy, in every trace its `<NN>-<sha12>/trace-ref.json` pointer lists (each
      trace file sha256-verified), de-duplicated across traces. Same shape as Ops' Exp 03 arms file, one source per
      member ('trace'), with `startLotSource: 'trace:<traceSha256>[,...]'`; members with no trace are listed.

  python studio_broker_fit_impact.py impact --member-reference <json> --sets <folder | .goatportfolio>
                                            --start-lots <json> --equities 25000,50000,75000
      Counts members per outcome under the round 5 rules (F1 band and quantization margin) at each equity, on the
      reference broker itself (its volume facts, contract ratio 1, value ratio 1, rate 1): fit / BELOW_MIN_LOT /
      MARGIN_UNKNOWN for want of a start lot (not enough live data yet) / MARGIN_UNKNOWN otherwise / other. Spread,
      server clock, symbol mapping and margin per lot (MARGIN_TOO_HIGH) need a live broker and are not assessed.
      `portfolio` per equity (cent accounts round 2): the portfolio floor as build_result finds it (>= 90% of the risk,
      raised by --min-equity / --min-equity-by-contract for the contract class), offered or the refusal; `coverage` is
      the most risk weight any equity can make tradable (below 0.9 no equity offers the portfolio).
      Per member: the start lot used (the larger median when two sources differ), n, min, max, and whether the
      observed max / median sits inside the F1 band's top (1.6 for an ATR grid, 1.05 for a point grid).
"""
import argparse
import base64
import hashlib
from decimal import Decimal
import json
from pathlib import Path
import statistics
import sys

import studio_broker_fit as bf

OUTCOMES = ('fit', 'BELOW_MIN_LOT', 'MARGIN_UNKNOWN_NO_START_LOT', 'MARGIN_UNKNOWN', 'other')
NOT_ASSESSED = ('spread', 'server clock', 'symbol mapping', 'margin per lot (MARGIN_TOO_HIGH)')


def read_json(path):
    return json.loads(Path(path).read_bytes().decode('utf-8-sig'))


def _member_suffix(member_id):
    return member_id.rsplit('.', 1)[-1]


# ------------------------------------------------------------------ start lots

def _summary(starts):
    lots = [start['lot'] for start in starts]
    times = sorted(start['timeUtc'] for start in starts)
    return dict(n=len(lots), median=round(statistics.median(lots), 8), min=min(lots), max=max(lots), first=times[0], last=times[-1],
                sequences=starts)


def start_lots_from_traces(traces, member_reference):
    """The extractor (see the module docstring). `traces` is the folder of `<NN>-<sha12>/trace-ref.json` pointers;
    their `path`s are relative to its parent."""
    from datetime import datetime, timezone
    traces = Path(traces)
    root = traces.parent
    by_suffix = {_member_suffix(member_id): member_id for member_id in member_reference}
    members, covered, unverified, loaded = [], set(), [], {}
    for folder in sorted(path for path in traces.iterdir() if path.is_dir() and (path / 'trace-ref.json').is_file()):
        pointer = read_json(folder / 'trace-ref.json')
        member_id = by_suffix.get(str(pointer.get('setSha256', ''))[:16])
        if member_id is None:
            continue
        starts, used = {}, []
        for trace in pointer.get('traces') or ():
            if trace['traceSha256'] not in loaded:
                raw = (root / trace['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest() != trace['traceSha256']:
                    unverified.append(dict(memberId=member_id, traceSha256=trace['traceSha256']))
                    continue
                loaded[trace['traceSha256']] = json.loads(raw.decode('utf-8-sig'))
            used.append(trace['traceSha256'])
            for sequence in loaded[trace['traceSha256']]['sequences']:
                if sequence.get('strategyId') != trace['strategyIdInTrace']:
                    continue
                entry = next((event for event in sequence.get('events') or () if event.get('kind') == 'entry'), None)
                if entry is None or not entry.get('lotsAfter'):
                    continue
                when = datetime.fromtimestamp(entry['time'] / 1000, timezone.utc).isoformat()
                starts[(entry['time'], round(entry['lotsAfter'], 8), sequence.get('direction'))] = dict(
                    timeUtc=when, lot=round(entry['lotsAfter'], 8), direction=sequence.get('direction'))
        if not starts:
            continue
        covered.add(member_id)
        members.append(dict(memberId=member_id, arms=dict(trace=_summary(sorted(starts.values(), key=lambda s: s['timeUtc']))),
                            armMediansDiffer=False, sourceArms=['trace'], startLotSource='trace:' + ','.join(used)))
    return dict(schema='goat-start-lots-v1', source='reference backtest traces', members=members,
                missingMembers=sorted(set(member_reference) - covered), unverifiedTraces=unverified)


def read_start_lots(path):
    """{memberId: dict} from Ops' arms file (or the extractor's, the same shape), or a flat
    {memberId: {startLot, n, ...}} file. Where two sources' medians differ, the LARGER one is used and flagged."""
    data = read_json(path)
    entries = data['members'] if isinstance(data, dict) and isinstance(data.get('members'), list) else [
        dict(value, memberId=key) for key, value in data.items() if isinstance(value, dict)]
    out = {}
    for entry in entries:
        sources = {name: arm for name, arm in (entry.get('arms') or {}).items() if arm and arm.get('n')}
        if sources:
            chosen = max(sources, key=lambda name: sources[name]['median'])
            medians = {sources[name]['median'] for name in sources}
            out[entry['memberId']] = dict(
                startLot=sources[chosen]['median'], n=sources[chosen]['n'], min=min(arm['min'] for arm in sources.values()),
                max=max(arm['max'] for arm in sources.values()), source=entry.get('startLotSource') or 'arm:' + chosen,
                armMediansDiffer=bool(entry.get('armMediansDiffer')) or len(medians) > 1,
                sources={name: dict(n=arm['n'], median=arm['median'], min=arm['min'], max=arm['max']) for name, arm in sources.items()})
        elif entry.get('startLot'):
            out[entry['memberId']] = dict(startLot=entry['startLot'], n=entry.get('n'), min=entry.get('min', entry['startLot']),
                                          max=entry.get('max', entry['startLot']), source=entry.get('startLotSource') or entry.get('sourceArm'),
                                          armMediansDiffer=bool(entry.get('armMediansDiffer')), sources={})
    return out


# ------------------------------------------------------------------ impact

def load_sets(source, member_ids):
    """{memberId: SET bytes} from a folder of SET files or a .goatportfolio export (memberSetFilesBinary), each matched
    by the 16-hex sha256 prefix in its memberId (SYMBOL.TF.<sha16>)."""
    source = Path(source)
    if source.is_file():
        blobs = [base64.b64decode(value) for value in read_json(source)['memberSetFilesBinary'].values()]
    else:
        blobs = [path.read_bytes() for path in sorted(source.iterdir()) if path.is_file()]
    by_prefix = {}
    for raw in blobs:
        by_prefix.setdefault(hashlib.sha256(raw).hexdigest()[:16], raw)
    return {member_id: by_prefix.get(_member_suffix(member_id)) for member_id in member_ids}


def _not_scalable(values, defaults, lot):
    """(outcome, code, detail) for a member excluded whatever the equity; None when the equity rules decide."""
    if bf.unreadable_money(values, defaults):
        return 'other', bf.MONEY_VALUE_UNREADABLE, None
    if bf.ladder_inputs(values, defaults) is None:
        return 'MARGIN_UNKNOWN', bf.MARGIN_UNKNOWN, 'lot_ladder_unknown'
    if bf._number(values, defaults, 'Mode_Lots') == bf.MODE_LOTS['RiskperSeq']:
        if lot is None:
            return 'MARGIN_UNKNOWN_NO_START_LOT', bf.MARGIN_UNKNOWN, 'start_lot_unknown'
        if bf.grid_shape(values, defaults) is None:
            return 'MARGIN_UNKNOWN', bf.MARGIN_UNKNOWN, 'loss_unknown'
    return None


def _rules(reference, lot, contract_ratio):
    return dict(volume_min=reference['volumeMin'], volume_step=reference['volumeStep'], volume_max=reference['volumeMax'],
                contract_ratio=contract_ratio, reference_volume_min=reference['volumeMin'], reference_volume_step=reference['volumeStep'],
                reference_volume_max=reference['volumeMax'], start_lot=None if lot is None else Decimal(repr(float(lot))),
                value_ratio=Decimal(1), memo={})


def _member_min_equity(values, defaults, reference, lot, reference_equity, *, rate, contract_ratio):
    """The member's minimum equity in account units, as studio_broker_fit._member finds it (min_equity over the same
    rules); None for a member no equity makes tradable (excluded whatever the equity, or a fixed money limit)."""
    if _not_scalable(values, defaults, lot) or any(bf._number(values, defaults, name) != 0 for name in bf.FIXED_MONEY_INPUTS):
        return None
    rules = _rules(reference, lot, contract_ratio)
    return bf.min_equity(lambda trial: bf.rules_at(values, defaults, rules, equity=trial, reference_equity=reference_equity, rate=rate,
                                                   decide=True)['code'] is None)


def _member_outcome(values, defaults, reference, lot, equity, reference_equity, *, rate=Decimal(1), contract_ratio=Decimal(1)):
    """(outcome, code, detail) of one member at one equity under the round 5 rules on the reference broker."""
    excluded = _not_scalable(values, defaults, lot)
    if excluded:
        return excluded
    if bf.fixed_money_off_reference(values, defaults, equity, reference_equity):
        return 'other', bf.CONTRACT_MISMATCH, 'fixed money limit'
    outcome = bf.rules_at(values, defaults, _rules(reference, lot, contract_ratio), equity=equity, reference_equity=reference_equity,
                          rate=rate)
    if outcome['code'] is None:
        scaled = outcome['scaled']
        return 'fit', None, dict(Risk=bf.num(scaled['Risk']), riskSearched=bf.num(scaled['riskSearched']),
                                 startLot=bf.num(scaled['startLot']), plannedLossMax=bf.num(scaled['plannedLossMax']))
    return ('BELOW_MIN_LOT' if outcome['code'] == bf.BELOW_MIN_LOT else 'other'), outcome['code'], None


def impact(member_reference, sets, start_lots, equities, *, schema, reference_equity=Decimal(100000), account_currency=None,
           min_equity=None, min_equity_by_contract=None):
    """The report (see the module docstring). member_reference: {memberId: {canonicalSymbol, reference}}; sets:
    {memberId: bytes or None}; start_lots: read_start_lots(...); equities: Decimals, in the account's own units.
    account_currency: a cent currency of the reference currency (USC for USD; P-beta38-cent-accounts) evaluates a cent
    account on the reference broker's specs scaled to a cent contract: rate 0.01, contract 1/100 of the reference's.
    min_equity / min_equity_by_contract: the manifest's floors; `portfolio` applies them per equity exactly as
    build_result does (studio_broker_fit.portfolio_floor), except margin, which needs a live broker."""
    if min_equity_by_contract is not None and not bf.valid_min_equity_by_contract(min_equity_by_contract):
        raise ValueError('minEquityByContract must be an object of standard and/or cent, each a positive number')
    defaults = bf.schema_defaults(schema)
    rate, contract_ratio = Decimal(1), Decimal(1)
    # Only a cent account of the reference currency itself (USC for USD) has a fixed rate; EUC and the other cent
    # currencies need a live base/USD quote this report does not have (Codex P2 on #236), so they are refused below.
    if account_currency and bf.CENT_CURRENCIES.get(account_currency) == 'USD':
        rate, contract_ratio = bf.CENT_FACTOR, Decimal(100)
    elif account_currency and account_currency != 'USD':
        raise ValueError('impact evaluates the reference currency (USD) or its cent account (USC) only')
    counts = {str(equity): {name: 0 for name in OUTCOMES} for equity in equities}
    members, weights, floors = [], [], []
    for member_id in sorted(member_reference):
        facts = bf.reference_facts(member_reference[member_id]['reference'])
        lots = start_lots.get(member_id)
        raw = sets.get(member_id)
        row = dict(memberId=member_id, mode=None, gridKind=None, startLot=None, n=None, min=None, max=None, maxOverMedian=None,
                   bandTop=None, withinBandTop=None, armMediansDiffer=None, startLotSource=None, outcomes={})
        if lots:
            row.update(startLot=lots['startLot'], n=lots['n'], min=lots['min'], max=lots['max'], armMediansDiffer=lots['armMediansDiffer'],
                       startLotSource=lots['source'], sources=lots['sources'])
        values = bf.set_values(raw, schema) if raw is not None else None
        weight = floor = None
        if values is not None:
            mode = bf._number(values, defaults, 'Mode_Lots')
            risk = bf._number(values, defaults, 'Risk')
            weight = risk if mode == bf.MODE_LOTS['RiskperSeq'] and risk and risk > 0 else None
            if facts is not None:
                floor = _member_min_equity(values, defaults, facts, lots and lots['startLot'], reference_equity, rate=rate,
                                           contract_ratio=contract_ratio)
            row['minEquity'] = bf.num(floor)
            row['mode'] = {value: name for name, value in bf.MODE_LOTS.items()}.get(int(mode) if mode is not None else None)
            atr = (bf._number(values, defaults, 'Grid_Size') or Decimal(0)) < 0
            row['gridKind'], row['bandTop'] = ('atr', 1.6) if atr else ('points', 1.05)
            if lots and lots['startLot']:
                row['maxOverMedian'] = round(lots['max'] / lots['startLot'], 4)
                row['withinBandTop'] = row['maxOverMedian'] <= row['bandTop']
        for equity in equities:
            if values is None or facts is None:
                outcome, code, detail = 'other', 'SET_OR_REFERENCE_MISSING', None
            else:
                outcome, code, detail = _member_outcome(values, defaults, facts, lots and lots['startLot'], equity, reference_equity,
                                                        rate=rate, contract_ratio=contract_ratio)
            counts[str(equity)][outcome] += 1
            row['outcomes'][str(equity)] = dict(outcome=outcome, code=code, detail=detail)
        members.append(row); weights.append(weight); floors.append(floor)
    # The portfolio level, as studio_broker_fit._portfolio: risk weights when every member has one, else equal; the
    # floor = the smallest equity where >= 90% of the weight trades (members excluded whatever the equity never count),
    # raised by the manifest floors that apply to this contract class.
    risk_weighted = all(weight is not None for weight in weights)
    weights = weights if risk_weighted else [Decimal(1)] * len(weights)
    total = sum(weights)
    klass = bf.contract_class(account_currency or 'USD', [contract_ratio])
    manifest = dict(minEquity=min_equity, minEquityByContract=min_equity_by_contract)
    coverage = sum(weight for weight, floor in zip(weights, floors) if floor is not None) / total if total else Decimal(0)
    portfolio = {}
    for equity in equities:
        at = [row['outcomes'][str(equity)]['outcome'] for row in members]
        needed = bf.needed_equity([(floor, weight) for floor, weight, outcome in zip(floors, weights, at)
                                   if floor is not None and outcome in ('fit', 'BELOW_MIN_LOT')], total)
        value, source = bf.portfolio_floor(needed, klass=klass, rate=rate, manifest=manifest)
        share = sum(weight for weight, outcome in zip(weights, at) if outcome == 'fit') / total if total else Decimal(0)
        code = (bf.PORTFOLIO_BROKER_UNFIT if value is None else bf.PORTFOLIO_NEEDS_LARGER_ACCOUNT if equity < value
                else bf.PORTFOLIO_BROKER_UNFIT if share < bf.TRADABLE_SHARE else None)
        portfolio[str(equity)] = dict(offered=code is None, refusal=code, minEquity=bf.num(value), minEquitySource=source,
                                      minEquityComputed=bf.num(needed), tradableRiskShare=bf.num(share.quantize(Decimal('0.0001'))))
    return dict(schema='goat-broker-fit-impact-v1', rule='round 5 F1 (band + quantization margin) on the reference broker',
                notAssessed=list(NOT_ASSESSED), referenceEquity=bf.num(reference_equity), counts=counts,
                contractClass=klass, riskWeighting='risk' if risk_weighted else 'equal',
                # The most weight any equity could make tradable: below 90%, no equity offers the portfolio.
                coverage=bf.num(coverage.quantize(Decimal('0.0001'))), portfolio=portfolio,
                accountUnit=bf.account_unit(account_currency or 'USD'),
                contract='reference contract / 100 (cent)' if contract_ratio != 1 else 'reference contract',
                membersWithStartLots=sum(1 for row in members if row['startLot']), members=members)


def main(argv=None):
    from studio_installation import contracts
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    lots = sub.add_parser('start-lots')
    lots.add_argument('--traces', type=Path, required=True)
    lots.add_argument('--member-reference', type=Path, required=True)
    run = sub.add_parser('impact')
    run.add_argument('--member-reference', type=Path, required=True)
    run.add_argument('--sets', type=Path, required=True)
    run.add_argument('--start-lots', type=Path)
    run.add_argument('--equities', default='25000,50000,75000')
    run.add_argument('--reference-equity', default='100000')
    run.add_argument('--ea-version', default='1.49')
    run.add_argument('--account-currency', default=None, help='USC: a cent account (equities in cents, cent contract)')
    run.add_argument('--min-equity', default=None, help="the manifest's minEquity (reference currency, standard contract)")
    run.add_argument('--min-equity-by-contract', default=None, help='the manifest\'s minEquityByContract as JSON, e.g. {"cent": 30000}')
    args = parser.parse_args(argv)
    reference = read_json(args.member_reference)
    if args.command == 'start-lots':
        result = start_lots_from_traces(args.traces, reference)
    else:
        schema, _ = contracts(args.ea_version)
        equities = [Decimal(text.strip()) for text in args.equities.split(',') if text.strip()]
        result = impact(reference, load_sets(args.sets, reference), read_start_lots(args.start_lots) if args.start_lots else {},
                        equities, schema=schema, reference_equity=Decimal(args.reference_equity), account_currency=args.account_currency,
                        min_equity=Decimal(args.min_equity) if args.min_equity else None,
                        min_equity_by_contract=json.loads(args.min_equity_by_contract) if args.min_equity_by_contract else None)
    json.dump(result, sys.stdout, indent=1, default=str)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
