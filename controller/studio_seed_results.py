"""Read native SeedFarming SpreadsheetML, binding each row to frozen inputs."""
import hashlib
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from campaign_ledger import sha
from studio_strategy_settings import numeric

SS='urn:schemas-microsoft-com:office:spreadsheet'
OFFICE='urn:schemas-microsoft-com:office:office'
HEADERS=['Pass','Result','Profit','Expected Payoff','Profit Factor','Recovery Factor','Sharpe Ratio','Custom','Equity DD %','Trades']


def collect(path, member, schema, cutoff):
    path=Path(path)
    if path.stat().st_size>100_000_000:raise ValueError('Oversized seed XML')
    raw=path.read_bytes()
    if len(raw)>100_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsafe or oversized seed XML')
    match=re.fullmatch(re.escape(member['output_base'])+r'_N(\d+)_AvgFit=([-\d.]+)_Health=([-\d.]+)_Zero=(\d+)_AvgTrades=([-\d.]+)_Best=([-\d.]+)\.xml',path.name)
    if not match:raise ValueError('Final seed filename does not match frozen member')
    try:root=ET.fromstring(raw)
    except ET.ParseError as exc:raise ValueError('Incomplete or invalid seed XML') from exc
    if root.tag!='{'+SS+'}Workbook':raise ValueError('Expected native SpreadsheetML workbook')
    props=root.findall('{'+OFFICE+'}DocumentProperties')
    if len(props)!=1:raise ValueError('Unique seed metadata required')
    metadata={}
    for item in props[0]:
        key=item.tag.removeprefix('{'+OFFICE+'}')
        if key in metadata:raise ValueError('Duplicate seed metadata')
        metadata[key]=item.text or ''
    expected=dict(Title=member['output_base'],Author='GOAT SeedFarming',Server=member['account']['server'],Mode='SeedFarming',Target=str(member['frame_target']),Strategy=member['alias'])
    if any(metadata.get(k)!=v for k,v in expected.items()):raise ValueError('Seed XML metadata differs from frozen identity')
    sheets=root.findall('{'+SS+'}Worksheet')
    if len(sheets)!=1 or sheets[0].get('{'+SS+'}Name')!='Tester Optimizator Results':raise ValueError('Unexpected seed worksheets')
    tables=sheets[0].findall('{'+SS+'}Table')
    if len(tables)!=1:raise ValueError('Unique seed table required')
    rows=[]
    for row in tables[0].findall('{'+SS+'}Row'):
        cells=[]
        if row.attrib:raise ValueError('Sparse/attributed seed rows unsupported')
        for cell in row:
            if cell.tag!='{'+SS+'}Cell' or cell.attrib:raise ValueError('Sparse/attributed seed cells unsupported')
            data=cell.findall('{'+SS+'}Data')
            if len(data)!=1 or list(data[0]):raise ValueError('Invalid seed cell')
            cells.append(data[0].text or '')
        rows.append(cells)
    if not rows:raise ValueError('Seed header missing')
    header=rows.pop(0)
    axes=member['axes']
    # Native zero-frame finalization has no optimized-input headers.
    if header[:10]!=HEADERS or len(header)!=len(set(header)) or (rows and set(header[10:])!=set(axes)) or (not rows and header[10:] and set(header[10:])!=set(axes)):
        raise ValueError('Seed XML axes differ from frozen template')
    if len(rows)>member['frame_target'] or len(rows)!=int(match[1]):raise ValueError('Actual seed row count/target mismatch')
    candidates=[];seen=set()
    for row in rows:
        if len(row)!=len(header):raise ValueError('Seed row width mismatch')
        values=dict(zip(header,row));metrics={}
        for key in HEADERS:
            number=float(values[key])
            if not math.isfinite(number):raise ValueError('Nonfinite seed result')
            metrics[key]=number
        if metrics['Pass']<0 or metrics['Pass']!=int(metrics['Pass']) or metrics['Pass'] in seen:raise ValueError('Invalid/duplicate seed pass')
        seen.add(metrics['Pass'])
        if metrics['Trades']<0 or metrics['Trades']!=int(metrics['Trades']):raise ValueError('Invalid seed trades')
        exact={key:value if schema['inputs'][key]['type']=='string' else value.split('||')[0] for key,value in member['values'].items()}
        for name in header[10:]:
            definition=schema['inputs'][name]
            encoded=values[name]
            # EA writes integer/bool axes as eight-decimal numeric cells.
            if definition['type']=='bool':encoded=str(int(float(encoded))) if float(encoded) in (0,1) else encoded
            number=numeric(encoded,definition)
            parts=member['values'][name].split('||')
            start=numeric(parts[1],definition);step=numeric(parts[2],definition,step=True);stop=numeric(parts[3],definition)
            if number<start or number>stop or ((number-start)/step).denominator!=1:raise ValueError('Seed axis value outside frozen ladder: '+name)
            exact[name]=str(int(number)) if number.denominator==1 else encoded
        canonical={k:(v if schema['inputs'][k]['type'] in ('string','datetime') else str(numeric(v,schema['inputs'][k]))) for k,v in exact.items() if k!='EA_Desc'}
        candidates.append(dict(pass_number=int(metrics['Pass']),metrics=metrics,values=exact,values_require_new_ea_desc=True,
            candidate_sha256=sha(canonical),candidate_hash_scheme='goat-seed-fixed-values-v1',source_sha256=member['source_sha256'],frozen_sha256=member['set_sha256'],
            qualifies=metrics['Result']>=cutoff['min_fitness'] and metrics['Trades']>=cutoff['min_trades']))
    n=len(candidates);fits=[c['metrics']['Result'] for c in candidates];trades=[c['metrics']['Trades'] for c in candidates]
    summary=dict(actual_frames=n,requested_frames=member['frame_target'],average_fitness=sum(fits)/n if n else 0,
        health_percent=100*sum(t>0 for t in trades)/n if n else 0,
        zero_trade_count=sum(t==0 for t in trades),average_trades=sum(trades)/n if n else 0,best_fitness=max(fits) if n else 0,
        qualifying_count=sum(c['qualifies'] for c in candidates))
    for group,key,tolerance in [(2,'average_fitness',.00051),(3,'health_percent',.0051),(4,'zero_trade_count',0),(5,'average_trades',.051),(6,'best_fitness',.00051)]:
        if abs(float(match[group])-summary[key])>tolerance:raise ValueError('Seed filename metrics disagree with rows: '+key)
    return dict(status='verified_seed_xml',path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),
        member_id=member['member_id'],summary=summary,candidates=candidates,cutoff=cutoff,
        performance_scope='in_sample_seed_search_only',native_launch_qualification=False)
