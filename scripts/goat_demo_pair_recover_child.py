"""One inspected terminal07/deploy:6 repair; no native commands or process launch.

Keep the original journal. Stage only after actual exit, then restart inert and
use a fresh ordinary inspection plus this pinned proof for one recovery attempt.
"""
import argparse, hashlib, json, ntpath, re, time
from pathlib import Path
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_profile as p
import goat_demo_pair_prepare as prep
import goat_demo_pair_orchestrate as o
import goat_demo_pair_trust as trust
from goat_demo_pair_lifecycle import replace_preserving_acl

SCHEMA='goat-partial-child-recovery-v1'


def reset_state(blob,registration,failure):
    text,encoding,bom=p.decode_text(blob);lines=text.splitlines(keepends=True)
    c.require(len(lines)==36 and lines[0].rstrip('\r\n')=='#GOAT_AI_LAUNCH_V147_2\t0\t50\t2','state_shape')
    for index,(line,member,old) in enumerate(zip(lines[1:],registration['members'],failure['rows'])):
        fields=line.rstrip('\r\n').split('\t')
        c.require(len(fields)==9 and fields[0]==member['path'] and fields[2]==member['symbol']
                  and fields[7:]==[str(old['chartId']),str(old['magic'])],'state_identity')
        if index==6:
            ending=line[len(line.rstrip('\r\n')):]
            lines[index+1]='\t'.join(fields[:7]+['0','0'])+ending
    return bom+''.join(lines).encode(encoding)


def empty_chart(blob,failed_cid):
    text=p.decode_text(blob)[0];lines=[v.strip() for v in text.splitlines() if v.strip()]
    c.require(lines[0]=='<chart>' and lines[-1]=='</chart>' and all('<' not in v and '>' not in v for v in lines[1:-1]),'orphan_not_empty_chart')
    values=c.unique_object([line.split('=',1) for line in lines[1:-1]])
    c.require(values.get('id') in ('0',str(failed_cid)) and values.get('symbol')=='EURUSD'
              and values.get('period_type')=='0' and values.get('period_size')=='1' and values.get('windows_total')=='0','orphan_not_empty_chart')


def saved_prefix(directory,registration,failure,orphan):
    folder=directory/'MQL5/Profiles/Charts/Default';paths=[];files={};seen=set();dashboards=0
    c.require(folder.is_dir() and not any(v.is_symlink() or v.is_junction() for v in [folder,*folder.parents]),'profile_alias')
    expected={r['chartId']:(m,r) for m,r in zip(registration['members'][:6],failure['rows'][:6])}
    c.require(len(expected)==6,'prefix_duplicate')
    for path in folder.rglob('*'):
        c.require(len(paths)<1024,'profile_bound');paths.append(path)
    for path in sorted(paths):
        c.require(not path.is_symlink() and not path.is_junction(),'profile_alias')
        if not path.is_file():continue
        c.require(len(files)<512,'profile_bound');blob=g.raw(path);files[path.relative_to(folder).as_posix()]=blob
        if path==orphan:empty_chart(blob,failure['rows'][6]['chartId']);continue
        if path.name=='order.wnd':
            c.require(orphan.name not in p.decode_text(blob)[0].splitlines(),'orphan_still_in_order');continue
        c.require(path.suffix.casefold()=='.chr','unexpected_profile_file')
        chart,inputs,role=p.chart_details(blob,directory)
        if role=='dashboard':
            dashboards+=1
            explicit=p.chart_details(prep.fresh_chart(),directory)[1]
            c.require(chart.get('symbol')=='EURUSD' and chart.get('period_type')=='0' and chart.get('period_size')=='1'
                      and all(k in inputs and p.input_equal(k,v,inputs[k]) for k,v in explicit.items()),'dashboard_changed')
        else:
            cid=int(chart.get('id','0'));c.require(cid in expected and cid not in seen,'unknown_or_duplicate_child');seen.add(cid)
            member,_=expected[cid];effective=p.effective_inputs(member,registration)
            c.require(chart.get('symbol')==member['symbol'] and chart.get('period_type')=='0' and chart.get('period_size')=='1'
                      and set(inputs)==set(effective) and all(p.input_equal(k,v,inputs[k]) for k,v in effective.items()),'saved_child_inputs_changed')
    c.require(dashboards==1 and seen==set(expected) and orphan.relative_to(folder).as_posix() in files,'exact_saved_prefix_required')
    return files


def failure_scope(failure,registration):
    c.require(failure['action']=='deploy_next' and failure['result']=='child_attach_failed'
              and failure['connected'] is True and failure['tradingAllowed'] is False
              and failure['positions']==failure['orders']==0 and failure['commandPending'] is False
              and len(failure['rows'])==35,'known_inert_attach_failure_required')
    for index,(row,member) in enumerate(zip(failure['rows'],registration['members'])):
        c.require(row['index']==index and row['symbol']==member['symbol'],'failure_member_identity')
        if index<6:c.require(row['chartId']>0 and row['magic']>0 and row['linkedFresh'] is True,'six_good_children_required')
        elif index==6:c.require(row['chartId']>0 and row['magic']==0 and row['symbol']=='EURUSD','exact_failed_row_required')
        else:c.require(row['chartId']==row['magic']==0,'later_children_present')
    c.require(len({r['chartId'] for r in failure['rows'][:7]})==7 and len({r['magic'] for r in failure['rows'][:6]})==6,'duplicate_child_identity')


def inspect(plan,host,witness_path,expected=None):
    fields={'schema','reconnectManifest','installation','draft','pins','controlDirectory','failure','shutdown','journal','orphan','state','globals','outputDirectory'}
    c.require(set(plan)==fields and plan['schema']==SCHEMA,'recovery_plan_schema')
    witness=g.checked_witness(witness_path,host,expected=expected)
    rows=c.validate_manifest(json.loads(trust.pinned(plan['reconnectManifest']),object_pairs_hook=c.unique_object));g.assert_new_pair_paths(rows,witness)
    row=next(r for r in rows if r['terminal']==7);directory=Path(row['directory']);out=Path(plan['outputDirectory'])
    c.require(not row['savedAlgoEnabled'] and not host.processes(row),'terminal07_must_be_closed_inert');c.verify_files(row)
    c.require(out.is_absolute() and out.parent.is_dir() and not out.exists(),'new_recovery_output_required')
    for folder in [directory,out.parent,Path(plan['controlDirectory']),Path(plan['journal']['path']).parent,Path(plan['state']['path']).parent]:
        c.require(folder.is_dir() and not any(v.is_symlink() or v.is_junction() for v in [folder,*folder.parents]),'recovery_path_alias')
    for root in [ntpath.dirname(v['path']) for v in witness['processes']]+[r['directory'] for r in rows]:
        a=c.canonical(str(out));b=c.canonical(root);c.require(a!=b and not a.startswith(b+'\\') and not b.startswith(a+'\\'),'output_scope')
    trust.pinned(plan['installation']);trust.pinned(plan['draft']);o.PINS=json.loads(trust.pinned(plan['pins']))
    api=o.NativeAPI(o.load_api(Path(plan['controlDirectory'])),Path(plan['installation']['path']),Path(plan['draft']['path']),7)
    c.require(api.installation['directory']==row['directory'] and api.installation['eaSha256']==row['eaSha256'],'installation_binding')
    failure_raw=trust.pinned(plan['failure']);failure=json.loads(failure_raw)
    api.module.verify_receipt(failure,{k:failure[k] for k in ('id','action','registrationSha256')},api.installation,api.reg['members'])
    c.require(failure['registrationSha256']==api.digest and g.read(api.root/(failure['id']+'.json'))==failure,'failure_native_binding');failure_scope(failure,api.reg)
    journal_path=Path(plan['journal']['path']);journal_raw=trust.pinned(plan['journal']);journal=o.Journal(journal_path.parent)
    c.require(journal_path.name=='journal.jsonl' and not any(r['kind']=='recovery_authorized' for r in journal.records),'original_journal_required')
    intents=[r for r in journal.records if r['kind']=='intent'];receipts=[r for r in journal.records if r['kind']=='receipt']
    c.require(intents[-1]['target']=='deploy:6' and sum(r.get('target')=='deploy:6' for r in intents)==1
              and receipts[-1]['result']=='child_attach_failed' and receipts[-1]['sha256']==hashlib.sha256(failure_raw).hexdigest()
              and g.raw(journal_path.parent/receipts[-1]['file'])==failure_raw,'original_failed_attempt_required')
    binding={'terminal':7,'registrationSha256':api.digest,'manifestSha256':plan['installation']['sha256']}
    c.require(journal.records[0].get('binding')==binding and g.read(api.root/'orchestration-owner.json')==
              {'schema':1,'runDirectory':str(journal_path.parent.resolve()),'binding':binding},'original_owner_binding')
    shut=json.loads(trust.pinned(plan['shutdown']));_,setuproot=api.module.setup.scope(Path(plan['installation']['path']))
    api.module.setup.receipt_record(shut,shut['id'],api.installation)
    c.require(shut['result']=='shutdown_requested' and shut['activationOnly'] is False and shut['connected'] is True
              and shut['tradingAllowed'] is False and shut['positions']==shut['orders']==0 and shut['charts']==8
              and failure['observedAtUtc']<=shut['observedAtUtc']<=time.time()<=shut['observedAtUtc']+14400
              and g.read(setuproot/(shut['id']+'.json'))==shut,'shutdown_evidence')
    common=g.raw(directory/'config/common.ini');c.require(hashlib.sha256(common).hexdigest()==row['commonIniSha256']
              and p.patch_common(common,row['login'],0)==common,'inert_config_changed')
    orphan=Path(plan['orphan']['path']);folder=directory/'MQL5/Profiles/Charts/Default'
    c.require(orphan.parent.resolve()==folder.resolve() and orphan.suffix.casefold()=='.chr','orphan_scope');trust.pinned(plan['orphan'])
    state=Path(plan['state']['path']);expected_state=Path(api.installation['commonFiles'])/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
    c.require(state.resolve()==expected_state.resolve() and Path(plan['globals']['path']).resolve()==(directory/'bases/gvariables.dat').resolve(),'state_scope')
    state_before=trust.pinned(plan['state']);state_after=reset_state(state_before,api.reg,failure);globals_raw=trust.pinned(plan['globals'])
    files=saved_prefix(directory,api.reg,failure,orphan)
    for member in api.reg['members']:c.require(p.digest(g.raw(member['path']))==member['sha256'],'source_set_changed')
    return witness,rows,api,journal,{'common':common,'files':files,'stateBefore':state_before,'stateAfter':state_after,
        'globals':globals_raw,'failure':failure,'journalRaw':journal_raw,'registrationSha256':api.digest}


def validate_authority(path,expected_sha,journal,api):
    proof=json.loads(trust.pinned({'path':str(path),'sha256':expected_sha}));authority=[r for r in journal.records if r['kind']=='recovery_authorized']
    c.require(proof.get('schema')==SCHEMA and proof.get('status')=='closed_partial_repair_complete'
              and proof.get('terminal')==7 and proof.get('index')==6 and proof.get('registrationSha256')==api.digest
              and proof.get('runDirectory')==str(journal.directory.resolve()) and len(authority)==1,'recovery_authority_scope')
    event=authority[0];prefix=g.raw(journal.path,8*1024*1024).splitlines(keepends=True)[:event['sequence']]
    c.require(event.get('proofSha256')==expected_sha and event.get('proofPath')==str(Path(path).resolve())
              and hashlib.sha256(b''.join(prefix)).hexdigest()==proof['journalBeforeSha256'],'recovery_authority_chain')
    old=journal.records[:event['sequence']];intents=[r for r in old if r['kind']=='intent'];receipts=[r for r in old if r['kind']=='receipt']
    c.require(intents and receipts and intents[-1].get('target')=='deploy:6' and receipts[-1].get('result')=='child_attach_failed'
              and receipts[-1].get('sha256')==proof['failureSha256'],'recovery_failure_history')
    c.require(proof['target']=='recovery:deploy:6:'+proof['failureSha256'] and event.get('target')==proof['target']
              and len(proof['prefix'])==6 and len({v[0] for v in proof['prefix']})==6 and len({v[1] for v in proof['prefix']})==6
              and all(type(n) is int and n>0 for v in proof['prefix'] for n in v),'recovery_target')
    return proof


def run(args):
    plan=g.read(args.plan);host=c.WindowsHost();witness,rows,api,journal,data=inspect(plan,host,args.protected_witness)
    if not args.apply:return {'status':'dry_run_passed','terminal':7,'preservedChildren':6,'recoveryIndex':6,'nativeCommands':0,'priorExpandedDashboardDefaultsEqualityProven':False}
    with g.lifecycle_lock(witness):
        # Reuse the original orchestration locks; no second native writer.
        import contextlib
        with contextlib.ExitStack() as stack:
            for path in (journal.directory/'orchestration.lock',api.root/'orchestration.lock'):
                stack.enter_context(g.lifecycle_lock({'lifecycleLock':str(path)},wait_seconds=0))
            _,rows,api,journal,fresh=inspect(plan,host,args.protected_witness,expected=witness);c.require(fresh==data,'recovery_state_changed')
            out=Path(plan['outputDirectory']);out.mkdir();quoted=str(out).replace("'","''")
            host.powershell("$ErrorActionPreference='Stop'; & icacls '"+quoted+"' /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; if($LASTEXITCODE -ne 0){throw 'private evidence ACL failed'}")
            g.write_new(out/'intent.json',plan)
            for name,key in [('common.ini','common'),('dashboard-before.tsv','stateBefore'),('dashboard-after.tsv','stateAfter'),('gvariables.dat','globals'),('journal-before.jsonl','journalRaw')]:g.write_new(out/name,data[key])
            for name,blob in data['files'].items():
                path=out/'profile-before'/name;path.parent.mkdir(parents=True,exist_ok=True);g.write_new(path,blob)
            row=next(r for r in rows if r['terminal']==7);directory=Path(row['directory']);orphan=Path(plan['orphan']['path']);state=Path(plan['state']['path'])
            c.require(not host.processes(row) and g.raw(state)==data['stateBefore'],'terminal_or_state_changed')
            trust.pinned(plan['orphan']);orphan.rename(out/'quarantined-empty-chart.chr')
            replace_preserving_acl(state,data['stateAfter'])
            c.require(g.raw(state)==data['stateAfter'] and g.raw(directory/'bases/gvariables.dat')==data['globals'],'repair_readback')
            claims=[[name,p.digest(blob)] for name,blob in data['files'].items() if name!=orphan.name]
            row['profileSha256']=p.digest(json.dumps(claims,separators=(',',':'),ensure_ascii=True).encode());c.verify_files(row,True)
            g.checked_witness(args.protected_witness,host,expected=witness);c.require(not host.processes(row),'terminal_started_during_repair')
            g.write_new(out/'reconnect-manifest.json',{'schema':'goat-demo-pair-connection-v1','terminals':rows})
            proof={'schema':SCHEMA,'status':'closed_partial_repair_complete','terminal':7,'index':6,'registrationSha256':api.digest,
                   'runDirectory':str(journal.directory.resolve()),'journalBeforeSha256':p.digest(data['journalRaw']),
                   'failureSha256':plan['failure']['sha256'],'target':'recovery:deploy:6:'+plan['failure']['sha256'],
                   'prefix':[[r['chartId'],r['magic']] for r in data['failure']['rows'][:6]],'createdAtUtc':time.time(),
                   'stateAfterSha256':p.digest(data['stateAfter']),'profileSha256':row['profileSha256'],
                   'priorExpandedDashboardDefaultsEqualityProven':False}
            proof_path=out/'recovery-proof.json';g.write_new(proof_path,proof);proof_sha=p.digest(g.raw(proof_path))
            c.require(g.raw(journal.path,8*1024*1024)==data['journalRaw'],'journal_changed_during_repair')
            journal.add('recovery_authorized',proofPath=str(proof_path.resolve()),proofSha256=proof_sha,target=proof['target'])
            result={'status':'closed_repair_staged_no_launch','recoveryProof':str(proof_path),'recoveryProofSha256':proof_sha,'nativeCommands':0}
            g.write_new(out/'completion.json',result);return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',required=True,type=Path);ap.add_argument('--protected-witness',required=True,type=Path)
    ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    try:print(json.dumps(run(args)))
    except (c.Refused,o.Stop) as error:print(json.dumps({'status':'needs_review','reason':str(error)}));raise SystemExit(2)
    except Exception as error:print(json.dumps({'status':'needs_review','reason':'inspect_retained_recovery_evidence','exceptionType':type(error).__name__}));raise SystemExit(2)
