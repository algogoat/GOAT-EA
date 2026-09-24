"""Migrate only an already approved same-host native GOAT WebRequest record.

Dry-run by default. Requires closed, inert, single-dashboard new pair and native
shutdown receipts. Never decodes URLs or copies credentials / a whole config.
"""
import argparse, configparser, hashlib, json, ntpath, re, time
from pathlib import Path
import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_profile as p
from goat_demo_pair_lifecycle import replace_preserving_acl


def pinned(item):
    c.require(set(item)=={'path','sha256'},'pin_schema')
    raw=g.raw(item['path']);c.require(hashlib.sha256(raw).hexdigest()==item['sha256'],'pin_changed')
    return raw


def trust_records(raw):
    text,enc,bom=p.decode_text(raw)
    c.require(enc=='utf-16-le' and bom==b'\xff\xfe','native_ini_encoding')
    parser=configparser.ConfigParser(interpolation=None,strict=True);parser.read_string(text)
    c.require(not parser.defaults() and len({s.casefold() for s in parser.sections()})==len(parser.sections())
              and '\x00' not in text,'ambiguous_native_ini')
    matches=list(re.finditer(r'(?ms)^\[Experts\]\r?\n(.*?)(?=^\[|\Z)',text))
    c.require(len(matches)==1,'experts_section')
    body=matches[0].group(1);records={}
    for key in ('Enabled','WebRequest','WebRequestUrl'):
        rows=list(re.finditer(r'(?m)^'+key+r'=([^\r\n]*)\r?$',body))
        c.require(len(rows)==1,'trust_record_count')
        records[key]=rows[0].group(1)
    return text,records


def patch_trust(target,source):
    _,approved=trust_records(source);text,old=trust_records(target)
    c.require(approved['WebRequest']=='1' and re.fullmatch('[A-Fa-f0-9]{16,4096}',approved['WebRequestUrl']) is not None,'approved_native_trust_required')
    c.require(old['Enabled']=='0','target_algo_must_be_off')
    c.require((old['WebRequest'],old['WebRequestUrl']) in (('0',''),('1','https://goatedge.ai')),'existing_target_trust_requires_review')
    section=re.search(r'(?ms)^\[Experts\]\r?\n(.*?)(?=^\[|\Z)',text)
    body=section.group(1)
    for key in ('WebRequest','WebRequestUrl'):
        body,count=re.subn(r'(?m)^'+key+r'=[^\r\n]*',lambda _:key+'='+approved[key],body)
        c.require(count==1,'trust_patch_count')
    return (text[:section.start(1)]+body+text[section.end(1):]).encode('utf-16')


def shutdown_state(receipt,row):
    c.require(set(receipt)=={'schema','id','result','account','server','directory','buildId','observedAtUtc',
              'connected','tradingAllowed','activationOnly','positions','orders','charts'}
              and type(receipt['schema']) is int and receipt['schema']==1
              and re.fullmatch('[a-f0-9]{32}',receipt['id']) is not None,'shutdown_schema')
    c.require(receipt['result']=='shutdown_requested' and receipt['account']==row['login'] and receipt['directory']==row['directory']
              and receipt['buildId']==row['buildId'] and receipt['server']==row['server']
              and receipt['tradingAllowed'] is False and receipt['connected'] is True and receipt['activationOnly'] is True
              and all(type(receipt[k]) is int for k in ('account','observedAtUtc','orders','positions','charts'))
              and receipt['orders']==receipt['positions']==0 and receipt['charts']==1,'shutdown_state')
    c.require(0<=time.time()-receipt['observedAtUtc']<=4*3600,'shutdown_stale')


def inspect(plan,host,witness_path):
    c.require(set(plan)=={'schema','manifest','source','commonFiles','outputDirectory','targets'} and plan['schema']=='goat-pair-native-trust-v1','plan_schema')
    witness=g.checked_witness(witness_path,host)
    source=Path(plan['source']['path'])
    c.require(str(source)==r'C:\GOAT Experiment\01 - Standard - Clean R5\config\common.ini','source_scope')
    c.require(any(c.canonical(x['path'])==c.canonical(str(source.parents[1]/'terminal64.exe')) for x in witness['processes']),'source_not_witnessed')
    approved=pinned(plan['source'])
    manifest=json.loads(pinned(plan['manifest']),object_pairs_hook=c.unique_object)
    rows=c.validate_manifest(manifest);g.assert_new_pair_paths(rows,witness)
    out=Path(plan['outputDirectory']);common_files=Path(plan['commonFiles'])
    c.require(ntpath.isabs(str(out)) and ntpath.isabs(str(common_files)) and out.parent.is_dir(),'absolute_evidence_paths')
    for path in [out.parent,common_files,source.parent,*[Path(r['directory']) for r in rows]]:
        c.require(path.is_dir() and not any(v.is_symlink() or v.is_junction() for v in [path,*path.parents]),'trust_path_alias')
    for directory in [ntpath.dirname(v['path']) for v in witness['processes']]+[r['directory'] for r in rows]:
        a=c.canonical(str(out));b=c.canonical(directory)
        c.require(a!=b and not a.startswith(b+'\\') and not b.startswith(a+'\\'),'evidence_terminal_overlap')
    c.require(len(plan['targets'])==2 and [t['terminal'] for t in plan['targets']]==[7,8],'target_pair')
    prepared=[]
    for row,target in zip(rows,plan['targets']):
        c.require(set(target)=={'terminal','chartId','shutdown'} and target['terminal']==row['terminal']
                  and type(target['chartId']) is int and target['chartId']>0 and not row['savedAlgoEnabled'],'target_schema')
        c.require(not host.processes(row),'target_running')
        receipt=json.loads(pinned(target['shutdown']),object_pairs_hook=c.unique_object)
        shutdown_state(receipt,row)
        native=Path(plan['commonFiles'])/'GOAT/AgentSetup'/Path(row['directory']).name/(receipt['id']+'.json')
        c.require(g.read(native)==receipt,'shutdown_native_mismatch')
        directory=Path(row['directory']);folder=directory/'MQL5/Profiles/Charts/Default'
        claims=[];charts=[]
        for file in sorted(folder.rglob('*')):
            c.require(len(claims)<512,'profile_file_bound')
            c.require(not file.is_symlink() and not file.is_junction(),'profile_alias')
            if file.is_file():
                raw=g.raw(file);claims.append([file.relative_to(folder).as_posix(),hashlib.sha256(raw).hexdigest()])
                if file.suffix.lower()=='.chr':
                    chart,inputs,role=p.chart_details(raw,directory)
                    c.require(role=='dashboard' and chart['id']==str(target['chartId']) and chart['symbol']=='EURUSD'
                              and chart['period_type']=='0' and chart['period_size']=='1','saved_dashboard_identity')
                    charts.append(file)
        c.require(len(charts)==1,'single_dashboard_required')
        common=directory/'config/common.ini';before=g.raw(common);after=patch_trust(before,approved)
        c.require(p.patch_common(before,row['login'],0)==before and p.patch_common(after,row['login'],0)==after,'inert_config_required')
        row['profileSha256']=hashlib.sha256(json.dumps(claims,separators=(',',':')).encode()).hexdigest()
        row['commonIniSha256']=hashlib.sha256(before).hexdigest();c.verify_files(row,True)
        prepared.append((row,common,before,after,claims))
    return witness,rows,prepared


def run(args):
    plan=g.read(args.plan);host=c.WindowsHost()
    witness,rows,prepared=inspect(plan,host,args.protected_witness)
    out=Path(plan['outputDirectory']);c.require(not out.exists(),'retained_migration_requires_review')
    if not args.apply:return {'status':'dry_run_passed','terminals':[7,8],'records':['WebRequest','WebRequestUrl']}
    with g.lifecycle_lock(witness):
        current,rows,rechecked=inspect(plan,host,args.protected_witness)
        c.require(current==witness and rechecked==prepared,'migration_state_changed');prepared=rechecked
        out.mkdir()
        quoted=str(out).replace("'","''")
        host.powershell("$ErrorActionPreference='Stop'; & icacls '"+quoted+"' /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; if($LASTEXITCODE -ne 0){throw 'private evidence ACL failed'}")
        g.write_new(out/'intent.json',plan)
        for row,common,before,after,claims in prepared:
            pinned(plan['source'])
            g.checked_witness(args.protected_witness,host,expected=witness)
            g.write_new(out/('before-'+str(row['terminal'])+'.ini'),before)
            g.write_new(out/('after-'+str(row['terminal'])+'.ini'),after)
            g.write_new(out/('profile-'+str(row['terminal'])+'.json'),claims)
            c.require(g.raw(common)==before and all(not host.processes(r) for r in rows),'target_changed')
            c.verify_files(row,True)
            replace_preserving_acl(common,after)
            row['commonIniSha256']=hashlib.sha256(after).hexdigest();c.verify_files(row,True)
        g.checked_witness(args.protected_witness,host,expected=witness)
        c.require(all(not host.processes(r) for r in rows),'target_started')
        result={'status':'trust_migrated_inert_native_verification_pending','terminals':[7,8],'nativePermissionVerified':False,
                'hashes':[{'terminal':row['terminal'],'before':hashlib.sha256(before).hexdigest(),
                           'after':hashlib.sha256(after).hexdigest(),'profile':row['profileSha256']} for row,_,before,after,_ in prepared]}
        g.write_new(out/'reconnect-manifest.json',{'schema':'goat-demo-pair-connection-v1','terminals':rows})
        g.write_new(out/'completion.json',result);return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True)
    ap.add_argument('--protected-witness',type=Path,required=True);ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    try:print(json.dumps(run(args)))
    except c.Refused as error:print(json.dumps({'status':'needs_review','reason':str(error)}));raise SystemExit(2)
    except Exception as error:
        print(json.dumps({'status':'needs_review','reason':'inspect_retained_trust_evidence','exceptionType':type(error).__name__}));raise SystemExit(2)
