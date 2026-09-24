"""Pair-only audit, inert close, restart rehearsal and closed Algo transition.

No terminal kill, order, credential access, profile repair, or blind retry.
Each operation requires a new output directory plus retained host-scoped intents.
Root owns start authorization and compares both arms before enabled startup.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

import goat_demo_pair_connection as conn
import goat_demo_pair_guard as guard
import goat_demo_pair_orchestrate as orch
import goat_demo_pair_profile as profile
import goat_demo_pair_readiness as paired
import goat_demo_pair_restart as restart

need=conn.require


def replace_preserving_acl(path, data):
    need(os.name=='nt','windows_replace_required')
    temporary=path.with_name(path.name+'.pair-'+uuid.uuid4().hex+'.pending')
    guard.write_new(temporary,data)
    fn=ctypes.WinDLL('kernel32',use_last_error=True).ReplaceFileW
    fn.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p]
    fn.restype=ctypes.c_int
    need(bool(fn(str(path),str(temporary),None,0,None,None)),'replace_failed_pending_retained')


def context(args):
    orch.PINS=guard.read(args.pins); paired.configure_pins(orch.PINS)
    rows=conn.validate_manifest(guard.read(args.reconnect_manifest))
    row=next(r for r in rows if r['terminal']==args.terminal);conn.verify_files(row)
    api=orch.NativeAPI(orch.load_api(args.control_dir),args.manifest,args.draft,args.terminal)
    need(api.installation['directory']==row['directory'] and api.installation['account']==row['login']
         and api.installation['eaSha256']==row['eaSha256'],'installation_binding')
    return rows,row,api


def verify_close_registration(api,manifest):
    _,root=api.module.setup.scope(manifest)
    registration=api.module.setup.read(root/'registration.json')
    schema=registration.get('schema')
    fields={'schema','account','server','directory','buildId','expiresAtUtc'}
    need(type(schema) is int and schema in (1,2)
         and set(registration)==fields|({'allowPairingRead'} if schema==2 else set())
         and (schema==1 or registration['allowPairingRead'] is True),'setup_registration_shape')
    need(type(registration.get('account')) is int
         and all(registration.get(key)==api.installation[key] for key in ('account','server','directory','buildId')),
         'setup_registration_identity_changed')
    now=time.time();expiry=registration.get('expiresAtUtc')
    need(type(expiry) is int and now+120<expiry<=int(now)+(900 if schema==2 else 86400),
         'setup_registration_needs_renewal_before_close')


def run(args):
    rows,row,api=context(args);host=conn.WindowsHost()
    witness=guard.checked_witness(args.protected_witness,host);guard.assert_new_pair_paths(rows,witness)
    need(not args.output.exists() and all(not args.output.resolve().is_relative_to(Path(r['directory']).resolve()) for r in rows),'new_external_output_required')
    with guard.lifecycle_lock(witness):
        lock=api.root/'orchestration.lock';descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        try:
            os.write(descriptor,str(os.getpid()).encode());os.fsync(descriptor)
            guard.checked_witness(args.protected_witness,host,expected=witness)
            args.output.mkdir(parents=True,exist_ok=False)
            result=operate(args,rows,row,api,host,witness)
            guard.checked_witness(args.protected_witness,host,expected=witness)
            guard.write_new(args.output/'completion.json',result)
            return result
        finally:
            os.close(descriptor);api.module.setup.sharing_retry(lock.unlink)


def operate(args,rows,row,api,host,witness):
    current=host.processes(row)
    if args.operation=='audit':
        need(len(current)==1,'single_process_required')
        process=current[0];started=time.time()
        guard.write_new(args.output/'audit-intent.json',{'process':process,'startedAtUtc':started,'registrationSha256':api.digest})
        value=api.request('audit')
        guard.write_new(args.output/'audit-result.json',value)
        need(value.get('result')=='observed' and int(started)<=value['observedAtUtc']<=time.time(),'audit_failed_or_old')
        need(host.processes(row)==[process],'audit_process_changed')
        proof=paired.capture_pair(api.module,api.manifest,api.root/(value['id']+'.json'),args.output/'paired-readiness',host)
        return {'status':'paired_readiness_captured','proofPath':str(proof),'proofSha256':paired.sha(guard.raw(proof))}
    need(args.proof is not None,'paired_proof_required')
    pair=paired.verify_stored_pair(api.module,args.proof,api.installation,api.reg,api.digest,max_age=(14400 if args.operation=='post-restart' else 600))
    if args.operation=='post-restart':
        need(args.prior_runtime is not None and args.restart_receipt is not None,'restart_evidence_required')
        process=restart.paired_restart_binding(pair,guard.read(args.prior_runtime),guard.read(args.restart_receipt),row,time.time())
        need(current==[process],'restarted_process_changed')
        journal=orch.Journal(args.output);runner=orch.Runner(api,api.reg,journal)
        journal.add('start',process=process,priorProofSha256=paired.sha(guard.raw(args.proof)))
        return restart.run_policy(api,runner,host,row,process,pair['audit'],api.root/'restart-policy-claims',orch.write_new,paired,args.output/'paired-readiness')
    if args.operation=='close':
        need(current==[pair['proof']['process']],'paired_process_changed')
        # Refuse before SDK attachment or the once-only shutdown claim. Renew
        # the same scoped registration separately, retaining old/new evidence.
        verify_close_registration(api,args.manifest)
        need(args.sdk_path is not None,'sdk_path_required');sys.path.insert(0,str(args.sdk_path));import MetaTrader5 as mt
        need(mt.initialize(str(Path(row['directory'])/'terminal64.exe'),portable=True,timeout=15000),'observe_attach_failed')
        try:
            snap=conn.snapshot(mt,row)
            need(snap['connected'] and not snap['algoEnabled'] and not snap['positionTickets'] and not snap['orderTickets'],'not_inert')
            snap.update(terminal=row['terminal'],status='observed',process=current[0],observedAtUtc=time.time())
            guard.write_new(args.output/'runtime-before.json',{'readOnly':True,'accounts':[snap]})
        finally:mt.shutdown()
        need(host.processes(row)==current,'close_process_changed')
        verify_close_registration(api,args.manifest)
        claims=api.root/'shutdown-claims';claims.mkdir(exist_ok=True)
        key=paired.sha(paired.encoded(current[0]))
        guard.claim_once(claims/(key+'.json'),{'operation':'shutdown_once','process':current[0],'output':str(args.output),'atUtc':time.time()})
        value=api.module.setup.request(args.manifest,'shutdown',timeout=30)
        guard.write_new(args.output/'shutdown.json',value)
        need(value['result']=='shutdown_requested' and value['charts']==36,'shutdown_not_accepted_or_wrong_chart_count')
        deadline=time.monotonic()+40
        while host.processes(row) and time.monotonic()<deadline:time.sleep(1)
        need(not host.processes(row),'await_actual_exit')
        return {'status':'closed','terminal':row['terminal'],'shutdownId':value['id'],'process':current[0]}
    need(args.operation in ('freeze-off','freeze-on') and not current and args.shutdown is not None,'closed_freeze_required')
    shut=guard.read(args.shutdown)
    _,setuproot=api.module.setup.scope(args.manifest)
    need(shut.get('result')=='shutdown_requested' and shut['account']==row['login'] and shut['directory']==row['directory']
         and shut['buildId']==row['buildId'] and shut['connected'] and not shut['tradingAllowed']
         and shut['positions']==0 and shut['orders']==0 and shut['charts']==36
         and guard.read(setuproot/(shut['id']+'.json'))==shut
         and pair['proof']['capturedAtUtc']<=shut['observedAtUtc']<=time.time(),'shutdown_evidence')
    enabled=args.operation=='freeze-on'
    if enabled:
        need(args.rehearsal is not None,'inert_restart_rehearsal_required')
        rehearsal=guard.read(args.rehearsal)
        need(rehearsal.get('status')=='restart_policy_paired_ready' and rehearsal.get('members')==35
             and rehearsal.get('process')==pair['proof']['process']
             and rehearsal.get('pairedProofSha256')==paired.sha(guard.raw(args.proof)),'restart_rehearsal_binding')
    directory=Path(row['directory']);common=directory/'config/common.ini';before=guard.raw(common)
    after=profile.patch_common(before,row['login'],int(enabled))
    profile_hash,claims=profile.profile_claims(directory,conn,api.reg,pair['audit'])
    state=Path(api.installation['commonFiles'])/'GOAT'/('dashboard_state_'+directory.name+'.tsv');state_raw=guard.raw(state)
    profile.verify_dashboard(state_raw,api.reg,pair['audit'])
    globals_raw=guard.raw(directory/'bases/gvariables.dat',32*1024*1024)
    for member in api.reg['members']:need(paired.sha(guard.raw(member['path']))==member['sha256'],'source_set_changed')
    guard.write_new(args.output/'manifest-before.json',{'schema':'goat-demo-pair-connection-v1','terminals':rows})
    guard.write_new(args.output/'profile-claims.json',claims)
    guard.write_new(args.output/'common-before.ini',before);guard.write_new(args.output/'dashboard-before.tsv',state_raw)
    guard.write_new(args.output/'globals-before.dat',globals_raw)
    for name,digest in claims:
        content=guard.raw(directory/'MQL5/Profiles/Charts/Default'/name)
        need(paired.sha(content)==digest,'profile_changed')
        target=args.output/'profile'/name;target.parent.mkdir(parents=True,exist_ok=True);guard.write_new(target,content)
    guard.write_new(args.output/'freeze-intent.json',{'account':row['login'],'enabled':enabled,'profileSha256':profile_hash,'beforeSha256':paired.sha(before),'afterSha256':paired.sha(after)})
    need(not host.processes(row) and guard.raw(common)==before and guard.raw(state)==state_raw,'freeze_race')
    need(profile.profile_claims(directory,conn,api.reg,pair['audit'])==(profile_hash,claims)
         and guard.raw(directory/'bases/gvariables.dat',32*1024*1024)==globals_raw,'freeze_persistence_race')
    guard.checked_witness(args.protected_witness,host,expected=witness)
    row.update(profileSha256=profile_hash,commonIniSha256=paired.sha(after),savedAlgoEnabled=enabled)
    if before!=after:replace_preserving_acl(common,after)
    conn.verify_files(row,True)
    persistence_path=None;persistence_sha=None
    if enabled:
        persistence=dict(schema='goat-demo-pair-persistence-v1',terminal=row['terminal'],account=row['login'],
            directory=row['directory'],buildId=row['buildId'],eaSha256=row['eaSha256'],profileSha256=profile_hash,
            commonIniSha256=row['commonIniSha256'],registrationSha256=api.digest,
            pairedProofSha256=paired.sha(guard.raw(args.proof)),createdAtUtc=time.time(),process=pair['proof']['process'],
            shutdownId=shut['id'],globalsSha256=paired.sha(globals_raw),dashboardStatePath=str(state),
            dashboardStateSha256=paired.sha(state_raw))
        persistence_path=args.output/'enabled-persistence.json';guard.write_new(persistence_path,persistence)
        persistence_sha=paired.sha(guard.raw(persistence_path))
        profile.verify_enabled_persistence(row,persistence_path,persistence_sha)
    manifest={'schema':'goat-demo-pair-connection-v1','terminals':rows}
    conn.validate_manifest(manifest);guard.write_new(args.output/'reconnect-manifest.json',manifest)
    # Caller selects this newly frozen manifest deliberately; canonical previous
    # manifests remain immutable and are never silently overwritten.
    return {'status':'staged_closed_no_launch','terminal':row['terminal'],'enabled':enabled,'atUtc':time.time(),
            'profileSha256':profile_hash,'reconnectManifest':str(args.output/'reconnect-manifest.json'),
            'enabledPersistenceProof':str(persistence_path) if persistence_path else None,
            'enabledPersistenceSha256':persistence_sha}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['audit','close','freeze-off','freeze-on','post-restart'])
    for name in ['control-dir','pins','manifest','draft','reconnect-manifest','protected-witness','output']:
        p.add_argument('--'+name,type=Path,required=True)
    for name in ['proof','shutdown','rehearsal','prior-runtime','restart-receipt','sdk-path']:
        p.add_argument('--'+name,type=Path)
    p.add_argument('--terminal',type=int,choices=[7,8],required=True);args=p.parse_args()
    try:result=run(args)
    except (conn.Refused,paired.Refused,orch.Stop) as error:result={'status':'needs_review','reason':str(error)}
    except Exception:result={'status':'needs_review','reason':'unexpected_error_inspect_retained_evidence'}
    if result['status']=='needs_review' and args.output.exists() and not (args.output/'failure.json').exists():guard.write_new(args.output/'failure.json',result)
    print(json.dumps(result));return 2 if result['status']=='needs_review' else 0

if __name__=='__main__':raise SystemExit(main())
