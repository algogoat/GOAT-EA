"""Exact paired native evidence: historical settings audit plus fresh live status.

Never constructs a synthetic native receipt. Caller owns the orchestration lock.
"""
from datetime import datetime
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import re
import time

SCHEMA = 'paired-native-readiness-v2'
BUILD_ID = 'V1.48-DASHBOARD-AI-PAIR-R1'
PAIR_ACCOUNTS = {3000109427,3000109421}
API_PINS = {}


def configure_pins(pins):
    global API_PINS
    need(type(pins) is dict and set(pins)=={'goat_portfolio_setup.py','goat_setup_control.py'}
         and all(re.fullmatch('[a-f0-9]{64}',v) for v in pins.values()),'api_pins_schema')
    need(not API_PINS or API_PINS==pins,'api_pins_changed')
    API_PINS=dict(pins)


class Refused(ValueError): pass
class FreshnessPending(Refused): pass


def need(condition, reason):
    if not condition: raise Refused(reason)


def raw(path, cap=131072):
    path=Path(path)
    need(re.fullmatch(r'api-bearer(?:-[A-Za-z0-9_-]+)?\.token(?:\.pending)?',path.name,re.I) is None and not path.is_symlink()
         and not path.is_junction(),'unsafe_evidence')
    with path.open('rb') as handle: value=handle.read(cap+1)
    need(0<len(value)<=cap,'evidence_size')
    return value


def sha(value): return hashlib.sha256(value).hexdigest()
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def decode(api,value): return json.loads(value.decode('utf8'),object_pairs_hook=api.setup.unique_object)


def native_raw(path,*,sleep=time.sleep):
    """Same UUID receipt only, including reads after the RPC reader returns."""
    path=Path(path)
    need(re.fullmatch('[a-f0-9]{32}\\.json',path.name) is not None,'native_receipt_path')
    for attempt in range(5):
        try:return raw(path)
        except OSError as error:
            if getattr(error,'winerror',None) not in (32,33) or attempt==4:raise
            sleep(0.025)


def assert_api(api):
    need(len(API_PINS)==2,'api_pins_unset')
    need(sha(raw(api.__file__))==API_PINS['goat_portfolio_setup.py'],'portfolio_source_pin')
    need(sha(raw(api.setup.__file__))==API_PINS['goat_setup_control.py'],'setup_source_pin')


def process_created(process,installation):
    need(type(process) is dict and set(process)=={'pid','created','path'}
         and type(process['pid']) is int and process['pid']>0
         and type(process['created']) is str and type(process['path']) is str,'process_schema')
    expected=ntpath.join(installation['directory'],'terminal64.exe')
    need(ntpath.normcase(process['path'].replace('/','\\'))==ntpath.normcase(expected),'process_path')
    created=datetime.fromisoformat(process['created'])
    need(created.utcoffset() is not None,'process_timezone')
    return created.timestamp()


def verify_pair(api,audit,status,registration,installation,captured_at,process):
    need(type(captured_at) in (int,float) and math.isfinite(captured_at),'capture_time')
    need(installation['buildId']==BUILD_ID and re.fullmatch('[a-f0-9]{64}',installation['eaSha256']) is not None,'reviewed_build')
    need(type(installation['account']) is int and installation['account'] in PAIR_ACCOUNTS
         and installation['server']=='Darwinex-Demo','pair_demo_scope')
    need(len(registration['members'])==35,'exact_35_members')
    for value,action in ((audit,'audit'),(status,'status')):
        need(type(value) is dict and type(value.get('id')) is str
             and re.fullmatch('[a-f0-9]{32}',value['id']) is not None,'receipt_id')
        api.verify_receipt(value,{'id':value['id'],'action':action,
                           'registrationSha256':audit['registrationSha256']},installation,registration['members'])
        need(value['action']==action and value['result']=='observed','observed_receipt_required')
        need(value['connected'] and not value['tradingAllowed'] and value['positions']==0
             and value['orders']==0 and not value['commandPending'],'inert_connected_required')
        need(all(value[k]==registration[k] for k in ('aiMode','aiThreshold','aiProtocol')),'portfolio_policy_changed')
        need(value['commandId']>0,'policy_command_required')
    need(audit['id']!=status['id'] and audit['commandId']==status['commandId'],'paired_command_or_id')
    need(process_created(process,installation)<=audit['observedAtUtc']<=status['observedAtUtc']<=captured_at,
         'paired_chronology')
    need(0<=captured_at-audit['observedAtUtc']<=120,'audit_settings_expired')
    # Structural/security failures take precedence over retryable timing alone.
    expected_mode=2 if registration['aiMode']==2 else 1
    charts=set();magics=set()
    for old,live in zip(audit['rows'],status['rows']):
        need(old['settingsMatch'] is True,'source_settings_not_verified')
        for value in (old,live):
            need(value['linkedFresh'] and value['EA_TRADE_ALLOWED']==1
                 and value['chartId']>0 and value['magic']>0,'child_identity_not_ready')
            need(value['exposureMode']==registration['exposureMode'] and value['ackId']==status['commandId']
                 and value['ackStatus']==1,'policy_ack_incomplete')
            need(value['AI_MODE']==expected_mode and value['AI_PROTOCOL']==2
                 and value['AI_THRESHOLD']==registration['aiThreshold'] and value['AI_SCOPE']==0,'child_ai_policy')
        need(all(old[k]==live[k] for k in ('index','symbol','chartId','magic')),'child_identity_changed')
        need(live['chartId'] not in charts and live['magic'] not in magics,'duplicate_child')
        charts.add(live['chartId']);magics.add(live['magic'])
        if expected_mode==2:
            need(live['AI_VERIFIED']==1 and type(live['AI_AT']) is int,'live_ai_unverified')
            need(live['AI_AT']<=captured_at,'future_ai_telemetry')
    if captured_at-status['observedAtUtc']>10: raise FreshnessPending('status_not_fresh')
    if expected_mode==2 and any(captured_at-r['AI_AT']>30 for r in status['rows']):
        raise FreshnessPending('live_ai_not_fresh')
    return {'members':35,'commandId':status['commandId'],'auditAgeSeconds':captured_at-audit['observedAtUtc'],
            'statusAgeSeconds':captured_at-status['observedAtUtc'],'timeBasis':'UTC',
            'qualification':'Settings verified by audit; live AI and policy verified separately by status at capture time.'}


def current_bindings(api,manifest,installation,registration_sha,manifest_sha):
    actual,rpc=api.context(manifest)
    need(actual==installation and sha(raw(manifest))==manifest_sha,'installation_changed')
    registration,digest=api.read_bounded(rpc/'registration.json')
    need(digest==registration_sha,'registration_changed')
    api.validate_registration(registration,installation)
    return registration,rpc


def write_new(path,value):
    with Path(path).open('xb') as handle:handle.write(value);handle.flush();os.fsync(handle.fileno())


def capture_pair(api,manifest,audit_path,output_dir,host,request_status=None,*,clock=time.monotonic,sleep=time.sleep,now=time.time):
    """Read-only native status RPCs only; caller must hold orchestration ownership.

    A timeout/error is not resubmitted. Only valid stale status/AI observations
    permit another status call, bounded by 90s and 19 calls. No audit is reissued.
    """
    assert_api(api);manifest=Path(manifest);output_dir=Path(output_dir)
    need(not output_dir.exists(),'proof_directory_must_be_new')
    installation,rpc=api.context(manifest);manifest_sha=sha(raw(manifest))
    registration,reg_sha=api.read_bounded(rpc/'registration.json');api.validate_registration(registration,installation)
    audit_bytes=raw(audit_path);audit=decode(api,audit_bytes)
    need(type(audit.get('id')) is str and re.fullmatch('[a-f0-9]{32}',audit['id']) is not None,'audit_id')
    native_audit=rpc/(audit['id']+'.json')
    need(sha(native_raw(native_audit))==sha(audit_bytes) and audit['registrationSha256']==reg_sha,'native_audit_binding')
    row={'directory':installation['directory']};processes=host.processes(row)
    need(type(processes) is list and len(processes)==1,'single_current_process_required');process=processes[0]
    need(process_created(process,installation)<=audit['observedAtUtc'],'audit_from_prior_process')
    deadline=clock()+90;attempts=0
    while True:
        need(clock()<deadline and attempts<19,'fresh_status_capture_timeout')
        current_bindings(api,manifest,installation,reg_sha,manifest_sha)
        need(host.processes(row)==[process],'process_changed')
        need(0<=now()-audit['observedAtUtc']<=120,'audit_settings_expired')
        attempts+=1
        timeout=max(1,min(30,deadline-clock()))
        value=request_status() if request_status else api.request(manifest,'status',timeout=timeout)
        need(type(value) is dict and type(value.get('id')) is str
             and re.fullmatch('[a-f0-9]{32}',value['id']) is not None,'status_result')
        native_status=rpc/(value['id']+'.json');status_bytes=native_raw(native_status);status=decode(api,status_bytes)
        need(status==value,'status_native_bytes_changed')
        current_bindings(api,manifest,installation,reg_sha,manifest_sha)
        need(host.processes(row)==[process] and sha(native_raw(native_audit))==sha(audit_bytes),'capture_identity_changed')
        captured=now();need(clock()<=deadline,'fresh_status_capture_timeout')
        try:summary=verify_pair(api,audit,status,registration,installation,captured,process)
        except FreshnessPending:
            need(clock()+5<deadline,'fresh_status_capture_timeout');sleep(5);continue
        break
    proof={'schema':SCHEMA,'apiPins':dict(API_PINS),'eaSha256':installation['eaSha256'],'buildId':BUILD_ID,
           'manifestPath':str(manifest.resolve()),'manifestSha256':manifest_sha,
           'registrationPath':str((rpc/'registration.json').resolve()),'registrationSha256':reg_sha,
           'process':process,'capturedAtUtc':captured,
           'audit':{'nativePath':str(native_audit.resolve()),'savedFile':'audit.native.json','sha256':sha(audit_bytes),
                    'id':audit['id'],'observedAtUtc':audit['observedAtUtc']},
           'status':{'nativePath':str(native_status.resolve()),'savedFile':'status.native.json','sha256':sha(status_bytes),
                     'id':status['id'],'observedAtUtc':status['observedAtUtc']},
           'summary':summary,'statusAttempts':attempts}
    output_dir.mkdir(parents=True,exist_ok=False)
    write_new(output_dir/'audit.native.json',audit_bytes);write_new(output_dir/'status.native.json',status_bytes)
    write_new(output_dir/'proof.json',encoded(proof)+b'\n')
    return output_dir/'proof.json'


def verify_stored_pair(api,proof_path,installation,registration,registration_sha,*,now=None,max_age=600,current_process=None):
    assert_api(api);proof_path=Path(proof_path);proof=decode(api,raw(proof_path));now=time.time() if now is None else now
    fields={'schema','apiPins','eaSha256','buildId','manifestPath','manifestSha256','registrationPath',
            'registrationSha256','process','capturedAtUtc','audit','status','summary','statusAttempts'}
    need(type(proof) is dict and set(proof)==fields and proof['schema']==SCHEMA,'proof_schema')
    need(proof['apiPins']==API_PINS and proof['eaSha256']==installation['eaSha256'] and proof['buildId']==BUILD_ID,'proof_source')
    need(type(max_age) in (int,float) and 0<max_age<=14400 and type(now) in (int,float) and math.isfinite(now),'history_age_bound')
    need(type(proof['capturedAtUtc']) in (int,float) and math.isfinite(proof['capturedAtUtc'])
         and 0<=now-proof['capturedAtUtc']<=max_age,'historical_proof_expired')
    need(type(proof['statusAttempts']) is int and 1<=proof['statusAttempts']<=19,'status_attempt_bound')
    need(proof['registrationSha256']==registration_sha,'proof_registration')
    actual,rpc=api.context(Path(proof['manifestPath']))
    need(actual==installation and sha(raw(proof['manifestPath']))==proof['manifestSha256'],'proof_manifest')
    need(Path(proof['registrationPath'])== (rpc/'registration.json').resolve(),'proof_registration_path')
    current,current_sha=api.read_bounded(rpc/'registration.json')
    need(current_sha==registration_sha and current==registration,'proof_current_registration')
    api.validate_registration(current,installation)
    receipts={}
    for action in ('audit','status'):
        evidence=proof[action]
        need(type(evidence) is dict and set(evidence)=={'nativePath','savedFile','sha256','id','observedAtUtc'},'evidence_schema')
        need(type(evidence['id']) is str and re.fullmatch('[a-f0-9]{32}',evidence['id']) is not None,'evidence_id')
        need(evidence['savedFile']==action+'.native.json' and Path(evidence['nativePath'])==(rpc/(evidence['id']+'.json')).resolve(),'evidence_path')
        saved=raw(proof_path.parent/evidence['savedFile'])
        need(sha(saved)==evidence['sha256']==sha(native_raw(evidence['nativePath'])),'evidence_hash')
        value=decode(api,saved)
        need(value['id']==evidence['id'] and value['observedAtUtc']==evidence['observedAtUtc'],'evidence_metadata')
        need(value['registrationSha256']==registration_sha,'receipt_registration_binding')
        receipts[action]=value
    need(current_process is None or proof['process']==current_process,'current_process_mismatch')
    summary=verify_pair(api,receipts['audit'],receipts['status'],registration,installation,proof['capturedAtUtc'],proof['process'])
    need(summary==proof['summary'],'proof_summary')
    return {'proof':proof,**receipts}
