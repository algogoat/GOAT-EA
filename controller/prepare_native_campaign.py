"""Stage registry-bound MT5 configs outside terminals; never activate native batch state."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import argparse

from campaign_ledger import sha
from strategy_registry import inspect_set
from studio_settings import validate_export, serialize_export


def native_run_relative(plan):
    """Bind native storage to the whole plan, excluding its derived path only."""
    frozen = json.loads(json.dumps(plan))
    frozen['native_batch'].pop('run_relative', None)
    return 'GOAT\\R' + sha(frozen)[:12]

def safe_token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_. -]+', value):
        raise ValueError('Unsafe native config token')
    return value


def prepare(plan_path, registry_path, output):
    plan_path, registry_path, output = map(Path, (plan_path, registry_path, output))
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    if plan.get('execution_authorized') is not False or plan.get('schema_version') != 1:
        raise ValueError('Expected non-executing version 1 plan')
    binding = plan['research_binding']
    native = plan.get('native_batch')
    export_settings = None
    if native:
        if native.get('export_end_policy') != 'native_last_friday_record_actual':
            raise ValueError('Native export end is dynamic; declare and record actual dates')
        for field in ('back_oos_date', 'forward_start'):
            datetime.strptime(native[field], '%Y.%m.%d')
        if native.get('run_relative') != native_run_relative(plan):
            raise ValueError('Expected deterministic short run directory')
        export_settings = validate_export(native.get('export_settings',dict(
            SetsToExport=2,MinScore=60.0,TargetDD=100,AdjustLots=False,
            BackOOSDate=native['back_oos_date'],MinARF=0.2,MinSR=2.5,IncludeBackOOS=True)))
        if export_settings['BackOOSDate'] != native['back_oos_date']:
            raise ValueError('Export BOOS date differs from native window')
    # The packer is never allowed to write into either terminal or Common Files.
    out = output.resolve()
    roots = [Path(binding['research_data_root']).resolve(),
             Path(binding['research_terminal']).resolve().parent]
    if binding.get('protected_terminal'): roots.append(Path(binding['protected_terminal']).resolve().parent)
    roots.extend(Path(root).resolve() for root in binding['protected_data_roots'])
    roots.append(Path(binding['common_files_root']).resolve())
    if any(out.is_relative_to(root) for root in roots):
        raise ValueError('Preparation output must be outside terminal/shared state')
    if output.exists():
        raise ValueError('Output already exists; inspect preserved package instead of overwriting')
    binary = roots[0] / 'MQL5' / 'Experts' / binding['ea_relative_path'].replace('\\', '/')
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    if binary_hash.lower() != binding['ea_sha256'].lower():
        raise ValueError('Installed research EA differs from frozen binding')
    staged = []
    with closing(sqlite3.connect(registry_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for job in plan['jobs']:
            row = db.execute('SELECT template_id,sha256,source_bytes FROM revisions WHERE revision_id=?', (job['revision_id'],)).fetchone()
            if not row or row[0] != job['template_id'] or row[1] != job['source_sha256']:
                raise ValueError('Registry lineage mismatch')
            original = row[2]
            before = inspect_set(original)
            if before['sha256'] != job['source_sha256'] or not before['axes']:
                raise ValueError('Bad retained bytes or zero-axis optimization input')
            if before['encoding'] != 'utf-16-le-bom' or not before['crlf']:
                raise ValueError('Expected frozen UTF-16 LE CRLF template')
            c = job['conditions']
            if c.get('ea_sha256', '').lower() != binary_hash.lower():
                raise ValueError('Job/binary mismatch')
            start = datetime.strptime(c['from_date'], '%Y.%m.%d')
            end = datetime.strptime(c['to_date'], '%Y.%m.%d')
            if end <= start or c['algorithm'] != 'FG' or type(c['model']) is not int or c['model'] not in (0, 1, 2, 4):
                raise ValueError('Unsupported dates/algorithm/model')
            if c.get('remote_agents') is not False or c.get('cloud_agents') is not False:
                raise ValueError('This rehearsal requires local agents only')
            if not re.fullmatch(r'1:[1-9][0-9]*', c['leverage']):
                raise ValueError('Leverage ratio required')
            import math
            if type(c['deposit']) not in (int, float) or not math.isfinite(c['deposit']) or c['deposit'] <= 0:
                raise ValueError('Positive deposit required')
            tag = 'R' + sha(job)[:20]
            text = original.decode('utf-16')
            updated, count = re.subn(r'(?m)^EA_Desc=[^\r\n]*', 'EA_Desc=' + tag, text)
            if count != 1:
                raise ValueError('Unique description required')
            raw = b'\xff\xfe' + updated.encode('utf-16-le')
            after = inspect_set(raw)
            if before['canonical_sha256'] != after['canonical_sha256']:
                raise ValueError('Trading input/range changed during staging')
            expert = binding['ea_relative_path']
            if '\n' in expert or '\r' in expert or '..' in Path(expert.replace('\\','/')).parts:
                raise ValueError('Unsafe expert path')
            tester = dict(Expert=expert, Symbol=safe_token(job['symbol']), Period=safe_token(c['timeframe']),
                          Model=c['model'], Optimization=2, OptimizationCriterion=6,
                          FromDate=c['from_date'], ToDate=c['to_date'], ForwardMode=c.get('forward_mode', 0),
                          Deposit=c['deposit'], Currency=safe_token(c['currency']), Leverage=c['leverage'],
                          UseLocal=1, UseRemote=0, UseCloud=0, Visual=0,
                          Report='MQL5\\Files\\GOATResearch\\' + tag, ReplaceReport=0, ShutdownTerminal=1)
            if native:
                forward = datetime.strptime(native['forward_start'], '%Y.%m.%d')
                if not datetime.strptime(native['back_oos_date'], '%Y.%m.%d') < start < forward < end:
                    raise ValueError('Native BOOS/start/forward/end ordering invalid')
                tester['ForwardMode'] = 4
                tester['ForwardDate'] = native['forward_start']
                tester['ShutdownTerminal'] = 0
                delay = c.get('execution_mode', 0)
                if type(delay) is not int or not -1 <= delay <= 600000:
                    raise ValueError('Invalid explicit execution delay')
                tester['ExecutionMode'] = delay
                tester['Report'] = (native['run_relative'] + '\\reports\\' + tag + '\\' + job['symbol'] +
                    '\\GOAT V'+binding['ea_version']+' ' + job['symbol'] + ',' + c['timeframe'] + ' ' + c['from_date'] + '-' +
                    c['to_date'] + '_(' + native['forward_start'] + ').xml')
                tester['Report'] = 'MQL5\\Files\\' + tester['Report']
                longest = str(roots[0]) + '\\' + tester['Report'][:-4] + '.forward.xml'
                if len(longest) >= 260:
                    raise ValueError('Native forward report exceeds legacy path budget')
            elif tester['ForwardMode'] != 0:
                raise ValueError('Initial engineering package supports standalone discovery only')
            ini = '[Charts]\r\nProfileLast=GOAT Research\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n[Tester]\r\n'
            ini += ''.join(f'{key}={value}\r\n' for key,value in tester.items())
            ini += '[TesterInputs]\r\n' + updated
            staged.append((tag, raw, ini.encode('utf-16'), dict(job=job, run_alias=tag, tester=tester,
                           source_sha256=before['sha256'], staged_sha256=after['sha256'],
                           canonical_sha256=before['canonical_sha256'], report_relative=tester['Report'])))
    if len({r[0] for r in staged}) != len(staged) or not staged:
        raise ValueError('Empty or colliding staged job identities')
    # Validate everything before creating the output. Partial filesystem failure
    # remains visibly incomplete without a manifest; never overwrite/retry in place.
    output.mkdir(parents=True)
    receipt = dict(schema_version=1, campaign_id=sha(plan), ea_sha256=binary_hash,
                   native_batch_activated=False, launch_permitted=False,
                   stage='native_batch_package_unactivated' if native else 'standalone_discovery_package_not_native_export_pipeline', jobs=[])
    for tag, raw, ini, meta in staged:
        (output / (tag + '.set')).write_bytes(raw)
        (output / (tag + '.ini')).write_bytes(ini)
        meta['ini_sha256'] = hashlib.sha256(ini).hexdigest()
        receipt['jobs'].append(meta)
    if native:
        # Native queue uses the same schema as BuildQueueTitle/BuildReportValue.
        # Package remains outside Common Files; no active pointer is changed.
        queue_parts = []
        for tag, raw, ini, meta in staged:
            t = meta['tester']
            # Matches GoatOptModelShortFromCode in Optimizer.mqh.
            model_tag = {0:'ET',1:'OHLC',2:'OP',4:'ETWRT'}[t['Model']]
            title = f';Pending_{t["Symbol"]},{t["Period"]} {t["FromDate"]}-{t["ToDate"]}_{model_tag}:{tag};'
            queue_parts.append(title + '\r\n[Tester]\r\n' + ''.join(f'{k}={v}\r\n' for k,v in t.items()))
            folder = output / 'inputs' / tag
            folder.mkdir(parents=True)
            (folder/'Inputs.GOAT').write_bytes(raw)
            (folder/'Queue.GOAT').write_bytes((queue_parts[-1]+'\x1f\r\n').encode('utf-16'))
        queue = '\x1f\r\n'.join(queue_parts) + '\x1f\r\n'
        export = serialize_export(export_settings)
        manifest = ('[OptimizationRun]\r\nVersion=1\r\nRunName=GOAT Studio\r\nRunPath=' +
                    native['run_relative'] + '\r\nEA=GOAT V'+binding['ea_version']+'\r\nServer='+safe_token(binding['account_server'])+'\r\n')
        package = manifest.replace('[OptimizationRun]', '[GOATBATCH]') + '[GOAT_EXPORT_SETTINGS]\r\n' + export + '[/GOAT_EXPORT_SETTINGS]\r\n[GOAT_QUEUE]\r\n' + queue + '[/GOAT_QUEUE]\r\n[GOAT_INPUTS]\r\n'
        for tag,raw,_,_ in staged:
            package += '[GOAT_INPUT:'+tag+']\r\n'+raw.decode('utf-16')+'\r\n[/GOAT_INPUT]\r\n'
        package += '[/GOAT_INPUTS]\r\n'
        for filename,text in [('queue.GOAT',queue),('export_settings.GOAT',export),('manifest.ini',manifest),('portfolio.goatbatch',package)]:
            (output/filename).write_bytes(text.encode('utf-16'))
        receipt['native_run_relative'] = native['run_relative']
        receipt['export_end_policy'] = native['export_end_policy']
        receipt['export_settings'] = export_settings
    (output / 'manifest.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = prepare(a.plan, a.registry, a.output)
    print(json.dumps(dict(jobs=len(r['jobs']), launch_permitted=False, stage=r['stage'])))
