"""Verify MT5 back/forward XML pairing; does not qualify exports or prove fixed inputs."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

SS = 'urn:schemas-microsoft-com:office:spreadsheet'
OFFICE = 'urn:schemas-microsoft-com:office:office'


def normalized(value):
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError('Nonfinite optimized value')
        return number
    except InvalidOperation:
        return value


def read_report(path, expected_title, axes, forward):
    raw = Path(path).read_bytes()
    root = ET.fromstring(raw)  # Truncated/partial XML is a failure, never zero qualifiers.
    if root.tag != '{'+SS+'}Workbook':
        raise ValueError('Expected MT5 spreadsheet workbook')
    title = root.find('.//{'+OFFICE+'}Title')
    if title is None or title.text != expected_title:
        raise ValueError('Native report title mismatch')
    tables = root.findall('.//{'+SS+'}Table')
    if len(tables) != 1:
        raise ValueError('Expected one native results table')
    rows = []
    for row in tables[0].findall('{'+SS+'}Row'):
        values = []
        for cell in row.findall('{'+SS+'}Cell'):
            index = int(cell.get('{'+SS+'}Index', len(values)+1))
            if index <= len(values) or index > 10000:
                raise ValueError('Invalid sparse cell index')
            values.extend([''] * (index-len(values)-1))
            data = cell.find('{'+SS+'}Data')
            values.append('' if data is None or data.text is None else data.text)
        if values:
            rows.append(values)
    if not rows or len(set(rows[0])) != len(rows[0]):
        raise ValueError('Missing or duplicate report headers')
    header = rows[0]
    required = {'Pass', 'Profit', 'Trades', *axes, 'Forward Result' if forward else 'Result'}
    if not required.issubset(header):
        raise ValueError('Missing required native columns')
    passes = {}
    for values in rows[1:]:
        if len(values) != len(header):
            raise ValueError('Incomplete result row')
        record = dict(zip(header, values))
        pass_number = Decimal(record['Pass'])
        if not pass_number.is_finite() or pass_number < 0 or pass_number != int(pass_number):
            raise ValueError('Invalid pass number')
        identity = int(pass_number)
        if identity in passes:
            raise ValueError('Duplicate pass identity')
        passes[identity] = record
    if not passes:
        raise ValueError('Empty optimization report needs explicit native outcome evidence')
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), passes=passes)


def verify_pair(back, forward, title, axes):
    if not axes or len(axes) != len(set(axes)):
        raise ValueError('Explicit unique optimized-axis names required')
    b = read_report(back, title, axes, False)
    f = read_report(forward, title, axes, True)
    for number, row in f['passes'].items():
        if number not in b['passes']:
            raise ValueError('Forward pass absent from back report')
        for key in axes:
            if normalized(row[key]) != normalized(b['passes'][number][key]):
                raise ValueError(f'Back/forward input mismatch: pass {number}, {key}')
    return dict(status='PAIR_STRUCTURE_AND_OPTIMIZED_VALUES_VERIFIED', title=title,
                back_rows=len(b['passes']), forward_rows=len(f['passes']), paired_rows=len(f['passes']),
                optimized_axes=axes, artifacts=[{k:r[k] for k in ('path','sha256')} for r in (b,f)],
                export_qualification='not_evaluated', fixed_inputs_verified=False,
                binary_and_tick_coverage_verified=False,
                limits='Requires separate runtime/config binding, journal coverage and export verification. Metrics may differ by period; this checks optimized inputs, not fitness equality.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--back',type=Path,required=True)
    parser.add_argument('--forward',type=Path,required=True)
    parser.add_argument('--title',required=True)
    parser.add_argument('--axes',nargs='+',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    if args.receipt.resolve() in (args.back.resolve(),args.forward.resolve()):
        raise ValueError('Cannot overwrite input report')
    result=verify_pair(args.back,args.forward,args.title,args.axes)
    args.receipt.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','back_rows','forward_rows','paired_rows')}))
