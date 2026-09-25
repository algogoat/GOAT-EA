"""Snapshot the closed inert dashboard pair after activation; never edit MT5.

Only the five explicit bootstrap inputs have a prior source comparison. Expanded
defaults are preserved and hashed, not asserted equal to a nonexistent old copy.
"""
import argparse, hashlib, json, ntpath, time
from pathlib import Path
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_prepare as prep
import goat_demo_pair_profile as p
import goat_demo_pair_trust as trust


def snapshot_profile(row,chart_id):
    directory=Path(row['directory']);folder=directory/'MQL5/Profiles/Charts/Default'
    c.require(folder.is_dir() and not any(x.is_symlink() or x.is_junction() for x in [folder,*folder.parents]),'profile_alias')
    expected=p.chart_details(prep.fresh_chart(),directory)[1]
    files={};charts=[];paths=[]
    for path in folder.rglob('*'):
        c.require(len(paths)<1024,'profile_entry_limit');paths.append(path)
    for path in sorted(paths):
        c.require(not path.is_symlink() and not path.is_junction(),'profile_alias')
        if path.is_file():
            c.require(len(files)<512,'profile_file_limit');blob=g.raw(path);files[path.relative_to(folder).as_posix()]=blob
            if path.suffix.casefold()=='.chr':
                chart,inputs,role=p.chart_details(blob,directory)
                c.require(role=='dashboard' and chart.get('id')==str(chart_id) and chart.get('symbol')=='EURUSD'
                          and chart.get('period_type')=='0' and chart.get('period_size')=='1','dashboard_identity')
                c.require(all(k in inputs and p.input_equal(k,v,inputs[k]) for k,v in expected.items()),'dashboard_bootstrap_inputs')
                charts.append({'file':path.relative_to(folder).as_posix(),'chartId':chart_id,'explicitInputs':expected,
                               'expandedInputCount':len(inputs),'expandedInputsSha256':hashlib.sha256(g.encoded(inputs)).hexdigest()})
    c.require(len(charts)==1,'one_dashboard_only')
    claims=[[name,hashlib.sha256(blob).hexdigest()] for name,blob in files.items()]
    return files,charts[0],claims,hashlib.sha256(json.dumps(claims,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def inspect(plan,host,witness_path,expected=None):
    c.require(set(plan)=={'schema','manifest','commonFiles','outputDirectory','targets'}
              and plan['schema']=='goat-pair-dashboard-recapture-v1','plan_schema')
    witness=g.checked_witness(witness_path,host,expected=expected)
    rows=c.validate_manifest(json.loads(trust.pinned(plan['manifest']),object_pairs_hook=c.unique_object));g.assert_new_pair_paths(rows,witness)
    out=Path(plan['outputDirectory']);common=Path(plan['commonFiles'])
    c.require(ntpath.isabs(str(out)) and ntpath.isabs(str(common)) and out.parent.is_dir() and not out.exists(),'new_external_output_required')
    for path in [out.parent,common,*[Path(row['directory']) for row in rows]]:
        c.require(path.is_dir() and not any(x.is_symlink() or x.is_junction() for x in [path,*path.parents]),'path_alias')
    for directory in [ntpath.dirname(x['path']) for x in witness['processes']]+[r['directory'] for r in rows]:
        a=c.canonical(str(out));b=c.canonical(directory)
        c.require(a!=b and not a.startswith(b+'\\') and not b.startswith(a+'\\'),'output_terminal_overlap')
    c.require(type(plan['targets']) is list and [t.get('terminal') for t in plan['targets']]==[7,8],'exact_pair')
    snapshots=[]
    for row,target in zip(rows,plan['targets']):
        c.require(set(target)=={'terminal','chartId','shutdown'} and type(target['chartId']) is int
                  and target['chartId']>0 and row['savedAlgoEnabled'] is False,'target_schema')
        c.require(not host.processes(row),'target_running');c.verify_files(row)
        receipt_raw=trust.pinned(target['shutdown']);receipt=json.loads(receipt_raw,object_pairs_hook=c.unique_object)
        trust.shutdown_state(receipt,row)
        c.require(g.read(common/'GOAT/AgentSetup'/Path(row['directory']).name/(receipt['id']+'.json'))==receipt,'native_shutdown_mismatch')
        config=g.raw(Path(row['directory'])/'config/common.ini')
        c.require(hashlib.sha256(config).hexdigest()==row['commonIniSha256'],'common_ini_changed')
        c.require(p.patch_common(config,row['login'],0)==config,'inert_config_required')
        files,chart,claims,digest=snapshot_profile(row,target['chartId'])
        before=row['profileSha256'];row['profileSha256']=digest;c.verify_files(row,True)
        snapshots.append({'terminal':row['terminal'],'config':config,'profile':files,'chart':chart,'claims':claims,
                          'priorProfileSha256':before,'profileSha256':digest,'shutdown':receipt_raw})
    return witness,rows,snapshots


def run(args):
    plan=g.read(args.plan);host=c.WindowsHost();witness,rows,snapshots=inspect(plan,host,args.protected_witness)
    result={'status':'dry_run_passed','scope':'closed-inert-dashboard-only','priorExpandedDefaultsEqualityProven':False,
            'profiles':[{'terminal':v['terminal'],'profileSha256':v['profileSha256'],**v['chart']} for v in snapshots]}
    if not args.apply:return result
    with g.lifecycle_lock(witness):
        _,fresh_rows,fresh=inspect(plan,host,args.protected_witness,expected=witness)
        c.require(fresh_rows==rows and fresh==snapshots,'snapshot_changed')
        out=Path(plan['outputDirectory']);out.mkdir();quoted=str(out).replace("'","''")
        host.powershell("$ErrorActionPreference='Stop'; & icacls '"+quoted+"' /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; if($LASTEXITCODE -ne 0){throw 'private evidence ACL failed'}")
        g.write_new(out/'intent.json',{'plan':plan,'atUtc':time.time()})
        for snapshot in snapshots:
            folder=out/str(snapshot['terminal']);folder.mkdir()
            g.write_new(folder/'common.ini',snapshot['config']);g.write_new(folder/'shutdown.json',snapshot['shutdown'])
            g.write_new(folder/'profile-claims.json',snapshot['claims']);g.write_new(folder/'input-proof.json',snapshot['chart'])
            for name,blob in snapshot['profile'].items():
                path=folder/'profile'/name;path.parent.mkdir(parents=True,exist_ok=True);g.write_new(path,blob)
        g.checked_witness(args.protected_witness,host,expected=witness)
        for row in rows:c.require(not host.processes(row),'target_started');c.verify_files(row,True)
        g.write_new(out/'reconnect-manifest.json',{'schema':'goat-demo-pair-connection-v1','terminals':rows})
        result['status']='dashboard_snapshot_saved_inert_no_launch';g.write_new(out/'completion.json',result)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',required=True,type=Path)
    ap.add_argument('--protected-witness',required=True,type=Path);ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    try:print(json.dumps(run(args)))
    except c.Refused as error:print(json.dumps({'status':'needs_review','reason':str(error)}));raise SystemExit(2)
    except Exception as error:
        print(json.dumps({'status':'needs_review','reason':'inspect_retained_dashboard_snapshot','exceptionType':type(error).__name__}));raise SystemExit(2)
