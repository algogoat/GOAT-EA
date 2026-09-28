"""Journaled retirement of one rejected original attempt after native re-grant.

Retains its actual queued native members and rejection receipts. No fabricated
native cancellation, no queue deletion, and no research start are performed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time

from campaign_ledger import packed,sha
from studio_bridge import write_json
from studio_handover import safe_path
from studio_installation import read_json
from studio_native_gate import exclusive_gate
from studio_seed_process import WindowsSeedProcess
from studio_driver_suspend import require_no_publishers
from studio_seed_slot import guard_active_seed
from studio_research_authority import authority
from studio_research_regrant import original,native
from studio_rejected_monitor import unstarted_material
from studio_derived_report_recovery import _profile,_fresh,_no_human_pending,retain
from native_control_transaction import NAMES,contents,digest,restore


def clean_legacy_draft(value,c,job):
    """Only the derived Report root changes when original controls are restored."""
    if (value.get('schema_version')!=1 or value.get('terminal_id')!=c.terminal or value.get('run_id')!=c.run
            or value.get('submitted')!='' or value.get('baseline')!=value.get('tester_ini','')+value.get('export_ini','')):
        raise ValueError('Clean bound editor required before retirement')
    manifest=read_json(c.root/'packages'/job['job_id']/'manifest.json')
    scoped='MQL5\\Files\\'+manifest['native_run_relative']+'\\reports\\'
    legacy='MQL5\\Files\\GOAT\\GOAT V'+c.install['ea_version']+'-'+c.session['account']['server']+'\\'
    matches=list(re.finditer(r'(?m)^Report=([^\r\n]+)',value['tester_ini']))
    if len(matches)!=1 or not matches[0][1].startswith(scoped):
        raise ValueError('Exact original derived Report path required')
    m=matches[0];suffix=m[1][len(scoped):]
    if not suffix or any(p in ('','.','..') for p in suffix.split('\\')) or '/' in suffix or ':' in suffix:
        raise ValueError('Invalid derived report suffix')
    tester=value['tester_ini'][:m.start(1)]+legacy+suffix+value['tester_ini'][m.end(1):]
    return value|dict(tester_ini=tester,baseline=tester+value['export_ini'])


def _scope(c):
    state=c.state();binding=packed(dict(terminal_id=c.terminal,run_id=c.run))
    scope=authority(c.store.db,binding,state);_,base=original(c.store.db,binding)
    if (not scope or 'renewal' not in scope or state['owner']!='agent'
            or state['generation']!=scope['generation'] or not scope['created_utc']<=time.time()<scope['expires_utc']):
        raise ValueError('Fresh genuine native research epoch required')
    return state,scope,base


def _folder(c,job):
    return safe_path(c.root/'attempts'/job['launch_intent']['attempt_id']/'never-started-retirement')


def _verify(c,record,folder,*,historical=True,require_released=True):
    state,scope,base=_scope(c)
    if sha(scope)!=record['authority_sha256'] or sha(base)!=record['original_authority_sha256']:
        raise ValueError('Retirement authority changed')
    _no_human_pending(c);require_no_publishers(c);guard_active_seed(c.root)
    for name,expected in record['archive_sha256'].items():
        if not re.fullmatch(r'[a-z-]+\.(json|ini|chr)',name) or digest(safe_path(folder/name).read_bytes())!=expected:
            raise ValueError('Retirement archive changed')
    old=read_json(folder/'job-before.json')
    if record['job_id']!=old['job_id'] or record['attempt_id']!=old['launch_intent']['attempt_id'] or _folder(c,old)!=folder:
        raise ValueError('Retirement attempt binding changed')
    current=next((j for j in state['queue'] if j['job_id']==old['job_id']),None)
    if current is None or {k:v for k,v in current.items() if k not in ('status','completion','completion_path')}!={k:v for k,v in old.items() if k not in ('status','completion','completion_path')}:
        raise ValueError('Retirement original job changed')
    if historical:unstarted_material(c,old,base,request_path=folder/'request-before.json')
    _profile(c,record)
    restart=c.root/'rejected-monitor-restarts'/record['attempt_id']
    publisher=read_json(restart/'publisher-stopped.json')
    if (publisher.get('supervisor_exited') is not True
            or publisher['journal_sha256']!=record['archive_sha256']['driver-before.json']
            or digest((c.root/'batch-drivers'/(old['job_id']+'.json')).read_bytes())!=publisher['journal_sha256']):
        raise ValueError('Original stopped publisher evidence changed')
    if digest(Path(record['startup_config']).read_bytes())!=record['archive_sha256']['startup-before.ini']:
        raise ValueError('Inert startup config changed')
    if require_released and record['phase'] in ('controls_restored','draft_repaired','settled','launch_issued','started_unverified','reverified'):
        tx=read_json(c.root/'attempts'/record['attempt_id']/'transaction.json');prior=read_json(folder/'transaction-before.json')
        root=safe_path(tx['base'])
        if (tx['phase']!='restored' or {k:v for k,v in tx.items() if k!='phase'}!={k:v for k,v in prior.items() if k!='phase'}
                or (root/'agent-native-control-owner.json').exists()
                or any(digest(contents(root/n))!=prior['files'][n]['before_sha256'] for n in NAMES)):
            raise ValueError('Retired native controls changed')
        if any((c.local/'native-gate'/n).exists() for n in ('request.json','permit.json')):
            raise ValueError('New native request appeared after retirement')
    return state,scope,base,old


def replacement_proof(db,state,scope,*,successor_id=None,require_released=True):
    from types import SimpleNamespace
    from studio_research_regrant import context
    c=context(db);c.store=SimpleNamespace(db=db);c.state=lambda:state
    c.bridge=SimpleNamespace(root=c.local/c.session['directory_id'])
    if (successor_id is None and len(state['queue'])!=1) or (successor_id is not None and
            (len(state['queue'])!=2 or state['queue'][1]['job_id']!=successor_id)):
        raise ValueError('Only one new-epoch replacement of the original job is allowed')
    old=state['queue'][0];folder=_folder(c,old);record=read_json(folder/'retirement.json')
    if record['phase']!='reverified' or old['status']!='failed':raise ValueError('Original never-started retirement is not verified')
    _,current_scope,_,archived=_verify(c,record,folder,require_released=require_released)
    if current_scope!=scope or old['configuration_sha256']!=scope['configuration_sha256']:
        raise ValueError('Replacement plan or native grant differs')
    result_path=c.root/'attempts'/record['attempt_id']/'result.json';result=read_json(result_path)
    if (old.get('completion')!=result or old.get('completion_path')!=str(result_path)
            or result.get('classification')!='retired_never_started' or result.get('executed_members')!=0
            or result.get('authority_sha256')!=sha(scope) or result.get('native_cancellation_claimed') is not False
            or result.get('reports') is not None or result['configuration']!=archived['configuration']
            or result['package_sha256']!=archived['launch_intent']['package_sha256']):
        raise ValueError('Retirement completion proof differs')
    if successor_id is not None and state['queue'][1]['configuration_sha256']!=scope['configuration_sha256']:
        raise ValueError('Replacement configuration differs')
    tx=read_json(c.root/'attempts'/record['attempt_id']/'transaction.json')
    if tx['phase']!='restored' or tx['owner']!=record['attempt_id']:raise ValueError('Original controls are not retired')
    return dict(fresh_native_epoch=True,authority_sha256=sha(scope),generation=scope['generation'],
        predecessor_job_id=old['job_id'],predecessor_attempt_id=record['attempt_id'],
        predecessor_result_sha256=digest(result_path.read_bytes()),retirement_sha256=digest((folder/'retirement.json').read_bytes()),
        max_seconds=scope['renewal']['max_seconds'],min_free_bytes=scope['renewal']['min_free_bytes'])


def retire(c,job_id,*,process=None,clock=time):
    process=process or WindowsSeedProcess(c)
    c.bridge.pump()
    with exclusive_gate(c.root/'batch-driver-gate'),exclusive_gate(c.local/'native-gate'):
        state,scope,base=_scope(c)
        if len(state['queue'])!=1 or state['queue'][0]['job_id']!=job_id:
            raise ValueError('Retirement requires the original job alone')
        job=state['queue'][0];folder=_folder(c,job);path=folder/'retirement.json'
        draft_path=c.bridge.root/'human/ui-draft.json';gate=c.local/'native-gate'
        attempt=job['launch_intent']['attempt_id'];evidence=c.root/'attempts'/attempt
        if not path.exists():
            if folder.exists():raise ValueError('Partial retirement preparation retained; inspect before effects')
            unstarted_material(c,job,base);_no_human_pending(c);require_no_publishers(c);guard_active_seed(c.root)
            seen=native(c,state);identity=process.inspect()
            if identity!=seen['process']:raise ValueError('Selected monitor identity changed')
            restart=read_json(c.root/'rejected-monitor-restarts'/attempt/'restart.json')
            repair_path=c.root/'rejected-monitor-restarts'/attempt/'derived-report-recovery/transaction.json'
            if Path(restart['controller_derived_report_recovery']['path'])!=repair_path:raise ValueError('Baseline repair belongs to another attempt')
            repair=read_json(safe_path(repair_path))
            if repair['phase']!='reverified' or repair['expected_recovery']!=restart or repair['authority_sha256']!=sha(base):
                raise ValueError('Verified baseline maintenance required before retirement')
            chart,common,chart_raw,common_raw,flags=_profile(c,repair)
            config=safe_path(Path(restart['launch']['startup_config']))
            if digest(config.read_bytes())!=restart['launch']['startup_sha256']:raise ValueError('Original startup changed')
            transaction=read_json(evidence/'transaction.json')
            if transaction['owner']!=attempt or transaction['phase']!='installed':raise ValueError('Original installed control transaction required')
            control_root=safe_path(transaction['base'])
            if any(digest(contents(control_root/n))!=transaction['files'][n]['after_sha256'] for n in NAMES):
                raise ValueError('Unstarted native controls changed')
            if any(transaction['files'][n]['before'] is not None for n in NAMES):
                raise ValueError('Retirement requires originally absent controls; preserve other prior work')
            if (gate/'permit.json').exists():raise ValueError('An active permit remains')
            draft=read_json(draft_path);after=clean_legacy_draft(draft,c,job)
            files={'job-before.json':(packed(job)+'\n').encode(),'request-before.json':(gate/'request.json').read_bytes(),
                'transaction-before.json':(evidence/'transaction.json').read_bytes(),
                'driver-before.json':(c.root/'batch-drivers'/(job_id+'.json')).read_bytes(),
                'draft-before.json':draft_path.read_bytes(),'draft-after.json':(packed(after)+'\n').encode(),
                'chart-before.chr':chart_raw,'common-before.ini':common_raw,'startup-before.ini':config.read_bytes()}
            record=dict(schema_version=1,job_id=job_id,attempt_id=attempt,authority_sha256=sha(scope),
                original_authority_sha256=sha(base),generation=scope['generation'],phase='prepared',
                created_utc=clock.time(),prior_process=identity,permission_bytes=flags,startup_config=str(config),
                archive_sha256={n:digest(raw) for n,raw in files.items()},starts_research=False,creates_grant=False,
                classification='retired_never_started',native_cancellation_claimed=False)
            folder.mkdir()
            for name,raw in files.items():retain(folder/name,raw)
            write_json(path,record)
        record=read_json(path)
        if record['phase'] not in ('prepared','close_issued','stopped','controls_restored','draft_repaired','settled','launch_issued','started_unverified','reverified'):
            raise ValueError('Unknown retirement phase')
        state,scope,base,old=_verify(c,record,folder)
        if clean_legacy_draft(read_json(folder/'draft-before.json'),c,old)!=read_json(folder/'draft-after.json'):
            raise ValueError('Retirement derived draft transformation changed')
        if record['phase']=='prepared':
            seen=native(c,state)
            if seen['process']!=record['prior_process'] or process.inspect()!=record['prior_process']:
                raise ValueError('Monitor changed before retirement close')
            if digest(draft_path.read_bytes())!=record['archive_sha256']['draft-before.json']:raise ValueError('Editor changed before close')
            record['phase']='close_issued';write_json(path,record);process.close(record['prior_process'])
        if record['phase']=='close_issued':
            deadline=clock.monotonic()+20
            while process.inspect() is not None:
                if process.inspect()!=record['prior_process'] or clock.monotonic()>=deadline:raise ValueError('Retirement close not confirmed; no repeated close')
                clock.sleep(.2)
            record['phase']='stopped';write_json(path,record)
        if record['phase']=='stopped':
            if process.inspect() is not None:raise ValueError('Terminal reappeared before settlement')
            _verify(c,record,folder)
            tx=read_json(evidence/'transaction.json');prior=read_json(folder/'transaction-before.json');root=safe_path(tx['base'])
            if {k:v for k,v in tx.items() if k!='phase'}!={k:v for k,v in prior.items() if k!='phase'}:
                raise ValueError('Control transaction changed')
            expected={n:digest(contents(root/n)) for n in NAMES}
            if any(expected[n] not in (prior['files'][n]['before_sha256'],prior['files'][n]['after_sha256']) for n in NAMES):
                raise ValueError('New native control bytes refuse restoration')
            if tx['phase']!='restored' or (root/'agent-native-control-owner.json').exists():restore(evidence,expected)
            if any(digest(contents(root/n))!=prior['files'][n]['before_sha256'] for n in NAMES):raise ValueError('Restored controls differ')
            for name in ('request.json','permit.json'):
                target=gate/name
                if name=='permit.json' and target.exists():raise ValueError('Unexpected permit during settlement')
                if name=='request.json' and target.exists():
                    if target.read_bytes()!=(folder/'request-before.json').read_bytes():raise ValueError('Another native request appeared')
                    target.unlink() # Exact expired request is durably archived, not acknowledged as consumed.
            record['phase']='controls_restored';write_json(path,record)
        if record['phase']=='controls_restored':
            if process.inspect() is not None:raise ValueError('Terminal reappeared before derived draft reconciliation')
            actual=digest(draft_path.read_bytes())
            if actual not in (record['archive_sha256']['draft-before.json'],record['archive_sha256']['draft-after.json']):
                raise ValueError('Editor changed during stopped retirement')
            if actual==record['archive_sha256']['draft-before.json']:
                temporary=safe_path(draft_path.with_name('ui-draft.retirement.tmp'))
                retain(temporary,(folder/'draft-after.json').read_bytes());os.replace(temporary,draft_path)
            record['phase']='draft_repaired';write_json(path,record)
        if record['phase']=='draft_repaired':
            if process.inspect() is not None:raise ValueError('Terminal reappeared before canonical settlement')
            state,scope,base,old=_verify(c,record,folder)
            result=dict(schema_version=1,status='failed',classification='retired_never_started',job_id=job_id,attempt_id=attempt,
                configuration=old['configuration'],configuration_sha256=old['configuration_sha256'],
                package_sha256=old['launch_intent']['package_sha256'],reports=None,executed_members=0,
                authority_sha256=sha(scope),retirement_path=str(path),native_cancellation_claimed=False)
            result_path=evidence/'result.json'
            if result_path.exists() and read_json(result_path)!=result:raise ValueError('Another completion exists')
            write_json(result_path,result)
            c.store.db.execute('BEGIN IMMEDIATE')
            try:
                state=c.state();current=state['queue'][0]
                if current==old:
                    current.update(status='failed',completion=result,completion_path=str(result_path))
                    binding=packed(dict(terminal_id=c.terminal,run_id=c.run))
                    c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
                    c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
                elif current.get('completion')!=result:raise ValueError('Canonical completion changed')
                c.store.db.execute('COMMIT')
            except BaseException:c.store.db.execute('ROLLBACK');raise
            record['phase']='settled';write_json(path,record)
        if record['phase']=='settled':
            if process.inspect() is not None:raise ValueError('Terminal reappeared before controller relaunch')
            _verify(c,record,folder)
            if read_json(draft_path)!=read_json(folder/'draft-after.json'):raise ValueError('Draft changed before relaunch')
            record['phase']='launch_issued';write_json(path,record)
            record['process']=process.start(Path(record['startup_config']))
            record['phase']='started_unverified';write_json(path,record)
        if record['phase']=='launch_issued':raise ValueError('Retirement relaunch uncertain; do not repeat')
    # Publish canonical settlement outside the non-reentrant native gate.
    c.bridge.pump()
    with exclusive_gate(c.local/'native-gate'):
        _verify(c,record,folder)
        deadline=clock.monotonic()+30
        while True:
            try:_fresh(c,record['process'],aligned=True);break
            except ValueError:
                if clock.monotonic()>=deadline:raise
                clock.sleep(.2)
        record['phase']='reverified';write_json(path,record)
    return dict(status='retired_never_started',operation_path=str(path),native_started=False,original_evidence_preserved=True)
