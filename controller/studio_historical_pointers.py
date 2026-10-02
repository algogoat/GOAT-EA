"""Reviewed retirement of settled, unowned pre-controller UI run pointers.

No historical run data, native flags, controller queues or grants are changed.
All MT5/controller writers must be stopped. Positively identified independent
Windows tester services use the same strict retirement classification as setup.
"""
from contextlib import ExitStack,closing,contextmanager
import configparser
import hashlib
import json
import os
from pathlib import Path,PureWindowsPath
import re
import sqlite3
import subprocess
from studio_subprocess import background_creationflags
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import paths,safe_path,tree,database_view,guard
from studio_installation import read_json,load_installation
from studio_native_gate import exclusive_gate,assert_clear_controls
from studio_seed_slot import guard_active_seed
from studio_build_upgrade import retain

CONTROLS=('active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini','agent-native-control-owner.json')


def pending_path(c):
    return safe_path(c.root/'historical-pointer-retirement.pending.json')


def guard_pending(c, review_id=None):
    pending=pending_path(c)
    if pending.exists() and (review_id is None or read_json(pending)!={'review_id':review_id}):
        raise ValueError('Interrupted historical pointer retirement; reconcile its exact retained review')


def parse_ini(raw):
    parser=configparser.ConfigParser(interpolation=None,strict=True);parser.optionxform=str
    parser.read_string(raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig'))
    if parser.defaults():raise ValueError('Historical INI defaults are unsupported')
    return {section:dict(parser[section]) for section in parser.sections()}


def pointer_view(c, folder, raw):
    common=safe_path(c.install['common_files_root']);folder=safe_path(folder)
    match=re.fullmatch(r'GOAT V([0-9]+\.[0-9]+)-([A-Za-z0-9_. -]+)',folder.name)
    if not match or tuple(map(int,match[1].split('.'))) >= tuple(map(int,c.install['ea_version'].split('.'))):
        raise ValueError('Only an older version historical UI pointer can be retired')
    parsed=parse_ini(raw)
    if set(parsed)!={'ActiveOptimizationRun'} or set(parsed['ActiveOptimizationRun'])!={'RunPath','UpdatedAt'}:
        raise ValueError('Only the historical UI RunPath/UpdatedAt pointer schema is supported')
    pointer=parsed['ActiveOptimizationRun'];relative=PureWindowsPath(pointer['RunPath'])
    if relative.drive or relative.root or '..' in relative.parts or len(relative.parts)!=3 or relative.parts[:2]!=('GOAT',folder.name):
        raise ValueError('Historical pointer must name one run inside its own version folder')
    run=safe_path(common.joinpath(*relative.parts))
    if run.parent!=folder or not run.is_dir():raise ValueError('Historical pointer run is missing or escapes its version')
    manifest=parse_ini(safe_path(run/'manifest.ini').read_bytes())
    if set(manifest)!={'OptimizationRun'}:raise ValueError('Historical Version 1 run manifest required')
    record=manifest['OptimizationRun']
    if (set(record)!={'Version','RunName','RunPath','ParentRunPath','EA','Server','CreatedAt'}
        or record['Version']!='1' or not record['RunName'] or record['RunPath']!=pointer['RunPath']
        or record['EA']!='GOAT V'+match[1] or record['Server']!=match[2] or record['ParentRunPath']!=''):
        raise ValueError('Historical run manifest does not bind this pointer/version/server')
    for timestamp in (pointer['UpdatedAt'],record['CreatedAt']):
        try:time.strptime(timestamp,'%Y.%m.%d %H:%M:%S')
        except ValueError as error:raise ValueError('Historical run timestamp is invalid') from error
    queue=safe_path(run/'queue.GOAT').read_bytes()
    text=queue.decode('utf-16' if queue.startswith(b'\xff\xfe') else 'utf-8-sig')
    entries=[part.strip() for part in text.split('\x1f') if part.strip()]
    if not entries or len(entries)>10000:raise ValueError('Bounded nonempty historical queue required')
    counts={}
    for entry in entries:
        lines=entry.splitlines();header=re.fullmatch(r';(Completed|Error|Cancelled)_[^;\r\n]+;',lines[0])
        if not header:raise ValueError('Historical queue has pending, paused, active or unknown work')
        config=parse_ini('\n'.join(lines[1:]).encode('utf-8'))
        if set(config)!={'Tester'} or not config['Tester']:raise ValueError('Historical queue tester block is malformed')
        counts[header[1]]=counts.get(header[1],0)+1
    return dict(pointer=str(folder/CONTROLS[0]),pointer_sha256=hashlib.sha256(raw).hexdigest(),version=match[1],
                run=str(run),run_relative=pointer['RunPath'],run_tree=tree(run),queue_counts=counts)


def inventory(c, retired=None):
    """retired maps only journal-owned moved pointers to exact archived bytes."""
    common=safe_path(Path(c.install['common_files_root'])/'GOAT')
    if not common.is_dir():raise ValueError('GOAT Common Files inventory unavailable')
    retired=retired or {};seen=set();result=[]
    folders=list(common.iterdir())
    if len(folders)>10000:raise ValueError('Common root inventory exceeds supported size')
    from studio_terminal_isolation import controller_base_name, foreign_namespace
    own_name=controller_base_name(c)
    for folder in sorted(folders):
        safe_path(folder)
        # Another terminal's own batch state is never a historical UI pointer here.
        if foreign_namespace(folder.name,own_name):continue
        if folder.name=='Workers':
            for item in folder.rglob('*'):
                safe_path(item)
                if item.name in CONTROLS:raise ValueError('Scoped worker native controls remain')
        if not folder.name.lower().startswith('goat v'):continue
        if not folder.is_dir():raise ValueError('Unexpected GOAT version entry')
        for name in CONTROLS[1:]:
            target=safe_path(folder/name)
            if target.exists():raise ValueError('Native config, launch or owner controls remain; use their original controller')
        pointer=safe_path(folder/CONTROLS[0]);key=str(pointer)
        if pointer.exists():
            if key in retired:raise ValueError('Retired pointer reappeared; preserve both copies')
            raw=pointer.read_bytes()
        elif key in retired:
            raw=retired[key];seen.add(key)
        else:continue
        result.append(pointer_view(c,folder,raw))
    if seen!=set(retired):raise ValueError('Retired pointer version folder disappeared')
    return result


def known_sources(c):
    """Known durable bindings only, never caller-supplied database paths."""
    # Windows Path identity is case-insensitive. Retained registry/handover
    # strings may spell one SQLite file differently; locking every spelling
    # would deadlock against our own first BEGIN IMMEDIATE.
    root,_,archive,_=paths(c);databases={safe_path(root/'studio.sqlite')};evidence={};registries=set()
    from studio_bootstrap_retirement import legacy_registration
    registration=legacy_registration(c)
    if registration:
        registries.add(safe_path(registration['registry']));databases.add(safe_path(registration['database']))
    if archive.exists():
        for folder in archive.iterdir():
            safe_path(folder)
            if not re.fullmatch('[a-f0-9]{32}',folder.name):continue
            receipt=safe_path(folder/'receipt.json')
            if not receipt.is_file():continue
            raw=receipt.read_bytes();record=read_json(receipt)
            if record.get('status')!='complete' or record.get('action')!='park':continue
            old=read_json(safe_path(folder/'state/installation.json'))
            if (old.get('terminal_data_root')!=c.install['terminal_data_root']
                or old.get('common_files_root')!=c.install['common_files_root']
                or record.get('observation',{}).get('installation_sha256')!=sha(old)):
                raise ValueError('Historical handover belongs to a different installation')
            evidence[str(receipt)]=hashlib.sha256(raw).hexdigest()
            for view in record['after_ownership']:databases.add(safe_path(view['path']))
    for registry in list(registries):
        p=safe_path(registry)
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
            for raw, in db.execute('SELECT configuration FROM workers'):
                worker=json.loads(raw)
                if safe_path(worker['common_root'])==safe_path(c.install['common_files_root']):
                    databases.add(safe_path(worker['controller']))
    return dict(databases=[str(p) for p in sorted(databases)],registries=[str(p) for p in sorted(registries)],handover_evidence=evidence)


def writer_check(c, databases):
    # Current monitor must be stopped too. No protected-terminal exception for
    # shared Common Files maintenance; no process is closed by this operation.
    from studio_handover import stopped
    from studio_bootstrap_retirement import require_no_testers
    command="ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(terminal64|terminal|metaeditor64|metaeditor)\\.exe$'} | Select-Object ProcessId,Name)"
    rows=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True,encoding='utf-8-sig',timeout=20, creationflags=background_creationflags()))
    if not isinstance(rows,list) or rows:raise ValueError('Stop every MT5 terminal and MetaEditor before historical pointer maintenance')
    stopped(c,databases)
    proof=require_no_testers(c,require_idle_services=True)
    return dict(status=proof['status'],independent_service_agents=proof['independent_service_agents'])


def references_target(value, needles, *, _raw_negative_safe=None):
    if _raw_negative_safe is None:
        # Real Windows run paths cannot contain quotes or control characters.
        # Keep the original decoder for callers with such synthetic targets.
        _raw_negative_safe=all(re.search(r'["\x00-\x1f]',needle) is None for needle in needles)
    if isinstance(value,str):
        normalized=value.replace('\\','/').casefold()
        while '//' in normalized:normalized=normalized.replace('//','/')
        if any(n in normalized for n in needles):return True
        # JSON escaped slash/backslash sequences normalize to the same slash;
        # structural quotes and control escapes cannot hide a valid target.
        # Only Unicode escapes can conceal path characters from the raw scan.
        # Avoid decoding and walking large unrelated retained audit payloads.
        if _raw_negative_safe and '\\u' not in value:return False
        try:decoded=json.loads(value)
        except (ValueError,TypeError):return False
        if isinstance(decoded,(dict,list)):return references_target(decoded,needles,_raw_negative_safe=_raw_negative_safe)
    elif isinstance(value,dict):
        return any(references_target(k,needles,_raw_negative_safe=_raw_negative_safe)
                   or references_target(v,needles,_raw_negative_safe=_raw_negative_safe) for k,v in value.items())
    elif isinstance(value,(list,tuple)):
        return any(references_target(v,needles,_raw_negative_safe=_raw_negative_safe) for v in value)
    return False


def data_view(c, sources, targets):
    needles=[item['run_relative'].replace('\\','/').casefold() for item in targets]+[item['run'].replace('\\','/').casefold() for item in targets]
    databases=[];registries=[]
    for name in sources['databases']:
        p=safe_path(name);guard_active_seed(p.parent);view=database_view(p)
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            for raw, in db.execute('SELECT jobs FROM studio_queues'):
                if any(j.get('status')=='pending' and j.get('launch_intent') for j in json.loads(raw)):
                    raise ValueError('Pending controller launch intent requires original reconciliation')
            for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                quoted='"'+table.replace('"','""')+'"'
                for row in db.execute('SELECT * FROM '+quoted):
                    if references_target(row,needles):
                        raise ValueError('A known controller references this historical run; use its owned completion path')
        databases.append(view)
    for name in sources['registries']:
        p=safe_path(name)
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            if db.execute('SELECT 1 FROM attempts WHERE released=0').fetchone() or db.execute('SELECT 1 FROM startup_slot').fetchone():
                raise ValueError('A worker claim or startup slot remains active')
            tables={}
            for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                quoted='"'+table.replace('"','""')+'"'
                rows=list(db.execute('SELECT * FROM '+quoted))
                if references_target(rows,needles):
                    raise ValueError('A worker registry references this historical run')
                tables[table]=sha(sorted(sha(list(row)) for row in rows))
            registries.append(dict(path=str(p),tables=tables))
    # Current live gates are not inferred from stale archive paths. Any present
    # gate must name one of the inspected databases and have settled controls.
    gates={}
    for owner in c.local.rglob('controller.json') if c.local.exists() else []:
        safe_path(owner)
        if owner.parent.name!='native-gate':raise ValueError('Unknown controller owner file')
        database=read_json(owner).get('database')
        if safe_path(database) not in {safe_path(p) for p in sources['databases']}:raise ValueError('Unregistered native gate remains')
        with exclusive_gate(owner.parent),closing(sqlite3.connect(safe_path(database).as_uri()+'?mode=ro',uri=True)) as db:
            assert_clear_controls(db,owner.parent)
        gates[str(owner.parent)]=tree(owner.parent)
    return dict(databases=databases,registries=registries,gates=gates)


@contextmanager
def maintenance(c):
    root,_,_,session=paths(c)
    common=safe_path(Path(c.install['common_files_root'])/'GOAT/.historical-control-maintenance')
    session.mkdir(parents=True,exist_ok=True);common.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(session),exclusive_gate(common),ExitStack() as stack:
        sources=known_sources(c)
        for p in sorted({safe_path(name) for name in sources['databases']+sources['registries']}):
            if not p.is_file():raise ValueError('Known controller database is missing')
            db=stack.enter_context(closing(sqlite3.connect(p,timeout=1,isolation_level=None)))
            db.execute('BEGIN IMMEDIATE')
        yield sources


def inspect(c, sources, retired=None, review_id=None):
    guard(c,historical_review=review_id)
    if load_installation(c.root/'installation.json')!=c.install:raise ValueError('Installation changed')
    if known_sources(c)!=sources:raise ValueError('Known controller/handover bindings changed')
    writers=writer_check(c,sources['databases'])
    targets=inventory(c,retired)
    view=data_view(c,sources,targets)
    return dict(installation_sha256=sha(c.install),sources=sources,writers=writers,targets=targets,data=view)


def review_path(c, review_id):
    if not isinstance(review_id,str) or not re.fullmatch('[a-f0-9]{32}',review_id):raise ValueError('Exact historical-pointer review ID required')
    return safe_path(c.root/'historical-pointer-retirement'/review_id/'review.json')


def public(plan):
    return dict(review_id=plan['review_id'],status=plan['status'],expires_at=plan['expires_at'],
                pointers=[dict(version=t['version'],run=Path(t['run']).name,queue_counts=t['queue_counts'],pointer_sha256=t['pointer_sha256']) for t in plan['observation']['targets']],
                effect='Archive only exact settled historical UI pointers; preserve every run file, queue, grant and native flag',
                launches=False,clears_native_flags=False,next_action='Review these exact historical runs before applying; native orphan recovery remains a separate operation')


def prepare(c):
    with maintenance(c) as sources:
        observed=inspect(c,sources)
        if not observed['targets']:raise ValueError('No eligible historical pointers exist')
        review_id=uuid.uuid4().hex
        plan=dict(schema_version=1,review_id=review_id,status='review',expires_at=time.time()+600,observation=observed)
        path=review_path(c,review_id);path.parent.mkdir(parents=True,exist_ok=False)
        write_json(path,plan)
        return public(plan)


def apply(c, review_id, *, confirmed=False):
    if not confirmed:raise ValueError('Explicit review confirmation required for historical pointer retirement')
    with maintenance(c) as sources:
        path=review_path(c,review_id);plan=read_json(path)
        if (plan.get('schema_version')!=1 or plan.get('review_id')!=review_id or plan.get('status') not in ('review','archiving','retired')
            or plan['observation']['installation_sha256']!=sha(c.install)):
            raise ValueError('Historical pointer review changed or belongs to another installation')
        targets=plan['observation']['targets'];retired={}
        moved_root=safe_path(Path(c.install['common_files_root'])/'GOAT/.historical-control-maintenance/retired'/review_id)
        for index,target in enumerate(targets):
            source=safe_path(target['pointer']);saved=safe_path(path.parent/(str(index)+'.pointer'))
            if saved.exists():
                raw=saved.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=target['pointer_sha256']:raise ValueError('Archived pointer changed')
                if not source.exists():
                    moved=safe_path(moved_root/(str(index)+'.pointer'))
                    if not moved.is_file() or moved.read_bytes()!=raw:raise ValueError('Historical pointer missing without exact archived move')
                    retired[str(source)]=raw
        fence=pending_path(c)
        if plan['status']=='review' and ((time.time()>plan['expires_at'] and not fence.exists()) or retired):
            raise ValueError('Historical review expired or pointer moved without publication intent')
        if inspect(c,sources,retired,review_id)!=plan['observation']:raise ValueError('Historical pointer review evidence changed')
        if plan['status']=='review':
            # Backup bytes and publication intent precede the first removal.
            for index,target in enumerate(targets):
                raw=safe_path(target['pointer']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=target['pointer_sha256']:raise ValueError('Pointer changed before backup')
                retain(path.parent/(str(index)+'.pointer'),raw)
            write_json(fence,dict(review_id=review_id));plan['status']='archiving';write_json(path,plan)
        elif plan['status']=='archiving' and (not fence.exists() or read_json(fence)!={'review_id':review_id}):
            raise ValueError('Interrupted retirement is missing its exact fence')
        moved_root.mkdir(parents=True,exist_ok=True)
        for index,target in enumerate(targets):
            source=safe_path(target['pointer']);saved=safe_path(path.parent/(str(index)+'.pointer'))
            moved=safe_path(moved_root/(str(index)+'.pointer'))
            if source.exists():
                if moved.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=target['pointer_sha256']:
                    raise ValueError('New or changed historical pointer detected; preserve both copies')
                if inspect(c,sources,retired,review_id)!=plan['observation']:raise ValueError('Historical evidence changed before pointer move')
                # This rename stays inside Common Files (same volume). A second
                # durable copy stays beside the review, even on another volume.
                if source.read_bytes()!=saved.read_bytes():raise ValueError('Historical pointer compare-and-remove failed')
                source.rename(moved);retired[str(source)]=saved.read_bytes()
            elif str(source) not in retired:raise ValueError('Historical pointer disappeared without exact archived bytes')
        if inspect(c,sources,retired,review_id)!=plan['observation']:raise ValueError('Historical retirement final readback changed')
        plan['status']='retired';write_json(path,plan)
        if fence.exists():
            if read_json(fence)!={'review_id':review_id}:raise ValueError('Historical retirement fence changed')
            fence.unlink()
        return public(plan)
