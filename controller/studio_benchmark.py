"""Read verified completed batch evidence, never reconcile, grant or launch."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from campaign_ledger import packed,sha
from studio_batch import _json,_verify_package
from studio_batch_contract import configuration_members
from studio_onboarding import session_state
from studio_native_observe import observe
from studio_report_observe import observe_reports
from studio_report_paths import report_paths

MAX_FILE_BYTES=64*1024*1024
MAX_TOTAL_BYTES=512*1024*1024
MAX_FILES=40050
MAX_INLINE_MEMBERS=100


def artifact(path,root):
    path=Path(path);root=Path(root).resolve()
    if path.resolve()!=path or not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Benchmark artifact is missing, linked or outside its exact evidence root')
    before=path.stat()
    if before.st_size>MAX_FILE_BYTES:raise ValueError('Benchmark artifact exceeds 64 MiB read bound')
    digest=hashlib.sha256();count=0
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):
            count+=len(block)
            if count>MAX_FILE_BYTES:raise ValueError('Benchmark artifact exceeds 64 MiB read bound')
            digest.update(block)
    after=path.stat()
    if count!=before.st_size or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('Benchmark artifact changed while reading')
    return dict(path=str(path),sha256=digest.hexdigest(),size_bytes=count)


def package_inventory(package):
    package=Path(package)
    if package.resolve()!=package:raise ValueError('Linked benchmark package is unsupported')
    entries=[];total=0
    for entry in package.rglob('*'):
        if entry.resolve()!=entry:raise ValueError('Linked benchmark package entry is unsupported')
        if entry.is_file():
            row=artifact(entry,package);entries.append(row);total+=row['size_bytes']
            if len(entries)>MAX_FILES or total>MAX_TOTAL_BYTES:raise ValueError('Benchmark package exceeds bounded inventory')
    return entries,total


def timeline_timings(raw,titles):
    if len(raw)>MAX_FILE_BYTES:raise ValueError('Timeline exceeds 64 MiB')
    text=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    lines=text.splitlines()
    if not lines or lines[0]!='LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails':
        raise ValueError('Native timeline header differs')
    if len(lines)>200000:raise ValueError('Timeline exceeds row bound')
    expected={}
    for index,title in enumerate(titles):
        if not title.startswith('Pending_'):raise ValueError('Frozen timeline title must start Pending_')
        base=title[len('Pending_'):]
        for status in ('Queued','OnGoing','Completed','Pending','Error','Cancelled'):
            expected[status+'_'+base]=(index,status)
    pairs=[[] for _ in titles];previous=None;sequence=[];queued=set()
    for line in lines[1:]:
        if not line:continue
        fields=line.split('\t')
        if len(fields)!=6:raise ValueError('Malformed timeline row')
        local,server,event,item,status,details=fields
        if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}',local):raise ValueError('Invalid native local timestamp')
        stamp=datetime.strptime(local,'%Y.%m.%d %H:%M:%S')
        if previous is not None and stamp<previous:raise ValueError('Native local timestamps regress')
        previous=stamp
        if event in ('BATCH_TERMINATED','STALE_STARTUP','RUN_REHOME'):raise ValueError('Timeline contains cancellation, rejected startup or relocated evidence')
        if event!='QUEUE_STATE':continue
        match=expected.get(item)
        if match is None or match[1]!=status:raise ValueError('Timeline queue identity/status differs from exact frozen member')
        index,_=match
        if status in ('Pending','Error','Cancelled'):raise ValueError('Timeline member contains retry or unsuccessful state')
        if status=='Queued':
            if pairs[index] or index in queued:raise ValueError('Timeline duplicates or queues an already-started member')
            queued.add(index)
            continue
        pairs[index].append((status,stamp,local));sequence.append((index,status))
    wanted=[(index,status) for index in range(len(titles)) for status in ('OnGoing','Completed')]
    if sequence!=wanted:raise ValueError('Timeline needs exactly one ordered start/completion pair per member')
    timings=[]
    for index,pair in enumerate(pairs):
        seconds=int((pair[1][1]-pair[0][1]).total_seconds())
        if seconds<=0:raise ValueError('Nonpositive or ambiguous member elapsed time')
        timings.append(dict(index=index,elapsed_seconds=seconds,native_local_start=pair[0][2],native_local_end=pair[1][2]))
    span=int((pairs[-1][1][1]-pairs[0][0][1]).total_seconds())
    processing=sum(row['elapsed_seconds'] for row in timings)
    if span<processing:raise ValueError('Overlapping native timeline members')
    return dict(status='native_timeline_observed',members=timings,member_processing_seconds=processing,
        observed_batch_span_seconds=span,between_member_seconds=span-processing,timestamp_resolution_seconds=1,
        duration_scope='Native OnGoing to Completed, including report migration and selected exports; initial launch and final controller finish excluded',
        clock_scope='Reported local wall-clock timestamps; timezone, DST and forward clock adjustments are not attested')


def benchmark_report(controller,batch_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',batch_id):raise ValueError('Invalid batch ID')
    session,_=session_state(controller)
    controller.session=session;controller.terminal=session['terminal_id'];controller.run=session['run_id']
    with closing(sqlite3.connect((controller.root/'studio.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT jobs FROM studio_queues WHERE binding=?',(packed(dict(terminal_id=controller.terminal,run_id=controller.run)),)).fetchone()
    if row is None or len(row[0].encode('utf-8'))>MAX_FILE_BYTES:raise ValueError('Missing or oversized retained queue')
    matches=[job for job in json.loads(row[0]) if job.get('job_id')==batch_id]
    if len(matches)!=1 or matches[0].get('status')!='completed':raise ValueError('Exactly one completed retained batch required; this command never finishes or reconciles work')
    job=matches[0];intent=job.get('launch_intent',{});attempt=intent.get('attempt_id','')
    if not re.fullmatch('[a-f0-9]{64}',attempt):raise ValueError('Retained native attempt identity required')
    package=controller.root/'packages'/batch_id
    if intent.get('package')!=str(package) or attempt!=sha([job['reservation']['reservation_id'],intent['package_sha256']]):
        raise ValueError('Retained attempt/package identity differs from reservation')
    inventory,package_bytes=package_inventory(package)
    _,plan,manifest=_verify_package(controller,job)
    result_path=controller.root/'attempts'/attempt/'result.json'
    if job.get('completion_path')!=str(result_path):raise ValueError('Completion path differs from exact retained attempt')
    result_artifact=artifact(result_path,result_path.parent)
    completion=_json(result_path)
    if completion!=job.get('completion') or any(completion.get(key)!=value for key,value in dict(
            status='completed',attempt_id=attempt,job_id=batch_id,configuration_sha256=job['configuration_sha256'],
            configuration=job['configuration'],package_sha256=intent['package_sha256'],ea_sha256=controller.install['ea_sha256'],
            account_server=session['account']['server']).items()):
        raise ValueError('Completed result identity differs from frozen batch')
    # Bound native files before observers read them; never inventory the whole run.
    if not re.fullmatch(r'GOAT\\R[0-9a-f]{12}',manifest['native_run_relative']):raise ValueError('Invalid native run path')
    native_run=Path(plan['research_binding']['common_files_root'])/manifest['native_run_relative'].replace('\\','/')
    native_paths=[native_run/'queue.GOAT']+[native_run/'inputs'/item['run_alias']/'Inputs.GOAT' for item in manifest['jobs']]
    native_before=[artifact(path,native_run) for path in native_paths]
    if sum(item['size_bytes'] for item in native_before)>MAX_TOTAL_BYTES:raise ValueError('Native files exceed 512 MiB bound')
    native=observe(package)
    if native['status']!='native_completed' or native['members']!=completion.get('member_outcomes') or native['artifacts']!=completion.get('native',{}).get('artifacts'):
        raise ValueError('Native completed queue or input evidence changed')
    members=configuration_members(job['configuration'])
    # Prebound exact report files only; no history/cache/drive searches.
    report_artifacts=[];known=[];export_artifacts=[];export_roots=[];export_bytes=0
    for index in range(len(members)):
        paths=report_paths(plan,manifest,index)
        for key in ('common_back','common_forward'):
            report_artifacts.append(artifact(paths[key],paths['common_run']))
            if sum(item['size_bytes'] for item in report_artifacts)>MAX_TOTAL_BYTES:raise ValueError('Benchmark reports exceed 512 MiB bound')
        export_root=paths['common_run']/'deploy'/manifest['jobs'][index]['run_alias']/members[index]['tester']['Symbol']
        export_roots.append(export_root)
        if export_root.exists():
            if export_root.resolve()!=export_root:raise ValueError('Linked export root is unsupported')
            for entry in export_root.iterdir():
                if entry.suffix.lower() in ('.set','.csv'):
                    checked=artifact(entry,export_root);export_artifacts.append(checked);export_bytes+=checked['size_bytes']
                    if len(export_artifacts)>MAX_FILES or export_bytes>MAX_TOTAL_BYTES:raise ValueError('Exports exceed bounded read budget')
    reports=observe_reports(package,job['configuration'],controller.schema,member_statuses=['native_completed']*len(members))
    if reports.get('status') not in ('report_pair_verified','report_batch_verified') or reports!=completion.get('reports'):
        raise ValueError('Verified completion reports changed or no longer verify')
    for item in native['artifacts']:
        checked=artifact(Path(item['path']),Path(native['native_run']))
        if checked['sha256']!=item['sha256']:raise ValueError('Native evidence changed during benchmark read')
        known.append(checked)
    timeline=Path(native['native_run'])/'timeline.tsv'
    timing_artifact=None
    try:
        timing_artifact=artifact(timeline,Path(native['native_run']))
        raw=timeline.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=timing_artifact['sha256']:raise ValueError('Timeline changed while reading')
        queue=(package/'queue.GOAT').read_bytes().decode('utf-16')
        titles=[entry.strip().splitlines()[0].strip(';') for entry in queue.split('\x1f') if entry.strip()]
        timing=timeline_timings(raw,titles)
    except (OSError,ValueError,UnicodeError) as exc:
        timing=dict(status='timing_unknown',reason=str(exc),members=[],observed_batch_span_seconds=None,member_processing_seconds=None,between_member_seconds=None)
    observed_rows=reports['members'] if 'members' in reports else [reports]
    time_rows={row['index']:row for row in timing.pop('members')}
    rows=[]
    for index,(member,observed) in enumerate(zip(members,observed_rows)):
        strategy={key:value for key,value in member['strategy']['values'].items() if key!='EA_Desc'}
        signature=dict(ea_sha256=controller.install['ea_sha256'],broker_server=session['account']['server'],
                       tester=member['tester'],export=member['export'],strategy_values=strategy)
        rows.append(dict(index=index,run_alias=manifest['jobs'][index]['run_alias'],
            symbol=member['tester']['Symbol'],timeframe=member['tester']['Period'],tester=member['tester'],export=member['export'],
            workload_sha256=sha(signature),strategy_values_sha256=sha(strategy),active_axes=member['strategy']['axes'],
            actual_back_report_rows=observed['evidence']['back_rows'],actual_forward_report_rows=observed['evidence']['forward_rows'],
            elapsed_seconds=time_rows.get(index,{}).get('elapsed_seconds'),
            timing=time_rows.get(index),report_xml_bytes=sum(a['size_bytes'] for a in report_artifacts[index*2:index*2+2])))
    # Recheck the exact files after parsing; never promote a changing evidence read.
    for item in inventory+report_artifacts+export_artifacts+[result_artifact]+native_before+known+([timing_artifact] if timing_artifact else []):
        current=artifact(Path(item['path']),Path(item['path']).parent)
        if current!=item:raise ValueError('Benchmark artifact changed during verification')
    after_package={str(p) for p in package.rglob('*') if p.is_file()}
    if after_package!={row['path'] for row in inventory}:raise ValueError('Package inventory changed during verification')
    with closing(sqlite3.connect((controller.root/'studio.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        after=db.execute('SELECT jobs FROM studio_queues WHERE binding=?',(packed(dict(terminal_id=controller.terminal,run_id=controller.run)),)).fetchone()
    if after!=row:raise ValueError('Retained queue changed during verification')
    after_exports={str(p) for root in export_roots if root.exists() for p in root.iterdir() if p.suffix.lower() in ('.set','.csv')}
    if after_exports!={row['path'] for row in export_artifacts}:raise ValueError('Export inventory changed during verification')
    return dict(schema_version=1,observed_at=datetime.now(timezone.utc).isoformat(),batch_id=batch_id,attempt_id=attempt,
        status='completed_evidence_verified',configuration_sha256=job['configuration_sha256'],member_count=len(rows),
        members=rows[:MAX_INLINE_MEMBERS],members_omitted=len(rows)>MAX_INLINE_MEMBERS,
        timing=timing,timeline_artifact=timing_artifact,completion_artifact=result_artifact,
        package=dict(path=str(package),manifest_sha256=intent['package_sha256'],frozen_file_count=len(inventory)),
        artifact_bytes=dict(frozen_package=package_bytes,report_xml=sum(a['size_bytes'] for a in report_artifacts),
            completion=result_artifact['size_bytes'],export_set_csv=export_bytes,native_queue_and_inputs=sum(a['size_bytes'] for a in known),
            timeline=timing_artifact['size_bytes'] if timing_artifact else None,
            scope='Listed retained artifacts only; excludes tick/history caches, tester agents and temporary storage; not a future disk requirement'),
        historical_environment=dict(hardware=None,enabled_mt5_workers=None,background_load=None,cache_state=None),
        execution_ready=False,launch_permitted=False,estimate=None,
        limitations=['Reported elapsed times are observations, not forecasts or performance qualification',
            'Optimization report row counts do not prove all executed genetic passes or worker throughput',
            'A current resource-profile does not prove historical machine or worker conditions',
            'Different assets, timeframes, dates, models, strategy inputs or export settings need their own measured pilot',
            'SeedFarming is a separate workload and is not extrapolated to full optimization batches'])
