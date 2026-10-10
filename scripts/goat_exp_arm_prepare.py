"""Fresh experiment-arm inert installation from a pinned plan. Dry-run by default; never starts MT5.

Plan-driven generalisation of goat_demo_pair_prepare (Exp 02). Both arms receive the SAME frozen
SET bytes and the same reviewed EA; the only per-arm difference is the dashboard state AI launch
header (#GOAT_AI_LAUNCH_V147_2 mode/threshold/protocol). Sources are explicit signed-terminal and
broker-server files, the plan's EA and frozen SETs. No old common.ini, profile, account database
or token is copied, read or written. Run on the intended host with a pinned plan and a fresh
protected-terminals witness after reviewing dry-run output.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import ntpath
from pathlib import Path
import re
import subprocess
import time

import goat_demo_pair_connection as conn
from goat_demo_pair_connection import require, Refused, canonical, unique_object, WindowsHost
from goat_demo_pair_guard import raw, read, write_new, lifecycle_lock, all_processes, assert_new_pair_paths
from goat_demo_pair_builds import BUILDS

need = require

PLAN_SCHEMA = 'goat-exp-arm-install-v1'
WITNESS_SCHEMA = 'goat-protected-terminals-v1'
MANIFEST_SCHEMA = 'goat-exp-arm-connection-v1'
AI_HEADER = '#GOAT_AI_LAUNCH_V147_2'
PLAN_KEYS = {'schema','experiment','commonFiles','outputDirectory','setNamespace','sources','ea','account','policy','members','arms'}
ROW_KEYS = {'terminal','directory','login','server','currency','leverage','terminalSha256','profile','profileSha256',
            'commonIniSha256','savedAlgoEnabled','eaSha256','expertRelativePath','credentialRelativePath','buildId'}
NAME = r'[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,63}'  # one Windows path component; never '..', ':' or a separator
HEX = r'[a-f0-9]{64}'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_ok(value, limit):
    return isinstance(value,str) and 0<len(value)<=limit and not any(c in value for c in '\t\r\n')


def component(value):
    return isinstance(value,str) and re.fullmatch(NAME,value) is not None and not value.endswith(('.',' '))


def absolute(value):
    return text_ok(value,1024) and ntpath.isabs(value) and '..' not in re.split(r'[\\/]',value)


def relative(value, prefix, suffix):
    # Posix-style path under a fixed root, recorded/joined verbatim by the native tools.
    return (text_ok(value,260) and value.startswith(prefix) and value.endswith(suffix)
            and '\\' not in value and all(component(part) for part in value.split('/')))


def number(value):
    try: return float(value)
    except (TypeError, ValueError): return math.nan


def source(entry, limit=128*1024*1024):
    need(type(entry) is dict and set(entry)=={'path','sha256'} and absolute(entry['path']), 'source_reference')
    need(isinstance(entry['sha256'],str) and re.fullmatch(HEX,entry['sha256']) is not None
         and entry['sha256'] != '0'*64, 'source_hash_required')
    data=raw(entry['path'], limit)
    need(sha(data)==entry['sha256'], 'source_hash_changed')
    return data


def chart_expert(relative_path):
    # 'MQL5/Experts/GOAT Experiment/GOAT V1.49.ex5' -> ('GOAT V1.49', 'Experts\\GOAT Experiment\\GOAT V1.49.ex5')
    parts=relative_path.split('/')
    return parts[-1][:-4], '\\'.join(parts[1:])


def fresh_chart(name, path):
    # Exp 02's parent dashboard chart and inputs, bound to the plan's EA. No inherited ID,
    # objects, positions, order history or child magic. MT5 assigns the persistent chart
    # identity on first load and saves it on exit.
    text=('<chart>\nsymbol=EURUSD\nperiod_type=0\nperiod_size=1\nscale=8\nmode=1\ngrid=0\nscroll=1\none_click=0\n'
          'window_left=0\nwindow_top=0\nwindow_right=1280\nwindow_bottom=800\nwindow_type=3\nfloating=0\nwindows_total=1\n'
          '<expert>\nname='+name+'\npath='+path+'\nexpertmode=5\n<inputs>\nMode_Operation=8\nDashboard_Resume_Saved=true\n'
          'Mode_Bias=1\nBias_Protocol=2\nBias_threshold=50\n</inputs>\n</expert>\n'
          '<window>\nheight=100.000000\nobjects=0\n<indicator>\nname=Main\npath=\napply=1\nshow_data=1\n</indicator>\n</window>\n'
          '</chart>\n')
    return text.replace('\n','\r\n').encode('utf-16')


def bare_chart():
    text=fresh_chart('','').decode('utf16')
    return re.sub(r'<expert>.*?</expert>\r\n','',text,flags=re.S).encode('utf16')


def fresh_common(login, server):
    # Plain URLs are not MT5's native opaque allowlist. Leave permission disabled
    # until an approved same-host trust migration; Algo remains disabled.
    return (f'[Common]\r\nLogin={login}\r\nServer={server}\r\nKeepPrivate=1\r\nNewsEnable=0\r\n'
            '[Charts]\r\nProfileLast=Default\r\n'
            '[Experts]\r\nEnabled=0\r\nAllowLiveTrading=1\r\nAllowDllImport=1\r\n'
            'Account=0\r\nProfile=0\r\nChart=0\r\n'
            'WebRequest=0\r\nWebRequestUrl=\r\n').encode('utf-16')


def bias_label(ai):
    return 'OFF' if ai['mode']==0 else f"ON / {'DEMO' if ai['protocol']==2 else 'LIVE'} / {ai['threshold']}%"


def checked_witness_n(path, host, expected=None, now=None):
    """goat_demo_pair_guard.checked_witness with an explicit protected-terminal count."""
    value = read(path)
    need(type(value) is dict and set(value) == {'schema','observedAtUtc','expiresAtUtc','processes','lifecycleLock','expectedCount'}
         and value['schema'] == WITNESS_SCHEMA, 'protected_witness_schema')
    clock = time.time() if now is None else now
    need(type(value['observedAtUtc']) in (int,float) and type(value['expiresAtUtc']) in (int,float)
         and value['observedAtUtc'] <= clock < value['expiresAtUtc']
         and value['expiresAtUtc']-value['observedAtUtc'] <= 8*3600, 'protected_witness_expired')
    need(type(value['expectedCount']) is int and value['expectedCount'] >= 1
         and type(value['processes']) is list and len(value['processes']) == value['expectedCount'], 'protected_count_mismatch')
    need(ntpath.isabs(value['lifecycleLock']), 'lifecycle_lock_path')
    need(expected is None or value == expected, 'protected_witness_changed')
    seen = set()
    actual = all_processes(host)
    for process in value['processes']:
        need(type(process) is dict and set(process) == {'pid','path','created'}
             and type(process['pid']) is int and process['pid'] > 0
             and ntpath.isabs(process['path']) and canonical(process['path']) not in seen,
             'protected_process_schema')
        need(datetime.fromisoformat(process['created']).tzinfo is not None, 'process_timezone')
        seen.add(canonical(process['path']))
        matches = [p for p in actual if canonical(p['path']) == canonical(process['path'])]
        need(len(matches) == 1 and matches[0]['pid'] == process['pid']
             and datetime.fromisoformat(matches[0]['created']) == datetime.fromisoformat(process['created']),
             'protected_process_changed')
    return value


def validate_manifest(value):
    need(type(value) is dict and set(value)=={'schema','experiment','terminals'} and value['schema']==MANIFEST_SCHEMA
         and component(value['experiment']), 'manifest_schema')
    need(type(value['terminals']) is list and len(value['terminals'])==2, 'exact_pair_required')
    roots=[]
    for row in value['terminals']:
        need(type(row) is dict and set(row)==ROW_KEYS, 'terminal_schema')
        need(type(row['terminal']) is int and 1<=row['terminal']<=99 and type(row['login']) is int and row['login']>0
             and row['login'] not in conn.PAIR_ACCOUNTS.values(), 'account_binding')
        need(absolute(row['directory']) and ntpath.basename(row['directory']).startswith(f"{row['terminal']:02d} - "), 'directory_binding')
        need(isinstance(row['server'],str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}',row['server']) is not None
             and row['server'].endswith('-Demo') and isinstance(row['currency'],str) and re.fullmatch('[A-Z]{3}',row['currency']) is not None
             and type(row['leverage']) is int and 1<=row['leverage']<=10000, 'account_policy')
        need(type(row['savedAlgoEnabled']) is bool, 'saved_algo_required')
        need(row['profile']=='Default', 'profile_name')
        need(relative(row['expertRelativePath'],'MQL5/Experts/','.ex5') and relative(row['credentialRelativePath'],'GOAT/Credentials/','.token')
             and isinstance(row['buildId'],str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}',row['buildId']) is not None, 'build_paths')
        for key in ('terminalSha256','profileSha256','commonIniSha256','eaSha256'):
            need(isinstance(row[key],str) and re.fullmatch(HEX,row[key]) is not None and row[key]!='0'*64, 'qualified_hash_required')
        need(row['buildId'] not in BUILDS or row['eaSha256']==BUILDS[row['buildId']]['artifactSHA256'], 'registered_build_hash')
        roots.append(canonical(row['directory']))
    first,second=value['terminals']
    need(first['terminal']!=second['terminal'] and first['login']!=second['login'], 'arm_identity')
    need(all(first[k]==second[k] for k in ('server','currency','leverage','terminalSha256','eaSha256','expertRelativePath',
                                           'credentialRelativePath','buildId','profile')), 'arm_build_mismatch')
    need(len(set(roots))==2 and not any(a.startswith(b+'\\') for a in roots for b in roots if a!=b), 'arm_paths_overlap')
    return sorted(value['terminals'], key=lambda r: r['terminal'])


def prepare(plan, host, witness_path, apply=False, progress=None):
    progress={} if progress is None else progress
    progress['stage']='validate_plan'
    need(type(plan) is dict and set(plan)==PLAN_KEYS and plan['schema']==PLAN_SCHEMA, 'plan_schema')
    need(component(plan['experiment']), 'experiment_name')
    need(absolute(plan['commonFiles']) and absolute(plan['outputDirectory']), 'absolute_paths')
    witness=checked_witness_n(witness_path, host)
    namespace=re.split(r'[\\/]',plan['setNamespace']) if isinstance(plan['setNamespace'],str) else []
    need(text_ok(plan['setNamespace'],260) and 0<len(namespace)<=4 and all(component(p) for p in namespace), 'set_namespace')
    need(type(plan['sources']) is dict and set(plan['sources'])=={'terminal','servers','ea'}, 'source_allowlist')
    exe=source(plan['sources']['terminal']); servers=source(plan['sources']['servers'], 8*1024*1024)
    ea=source(plan['sources']['ea'],32*1024*1024)
    build=plan['ea']
    need(type(build) is dict and set(build)=={'buildId','expertRelativePath','sha256','credentialRelativePath'}, 'ea_schema')
    need(build['sha256']==plan['sources']['ea']['sha256']==sha(ea), 'ea_hash_mismatch')
    need(isinstance(build['buildId'],str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}',build['buildId']) is not None, 'build_id')
    # A registered pair build must keep its reviewed bytes; an unregistered build is pinned by the plan only.
    need(build['buildId'] not in BUILDS or BUILDS[build['buildId']]['artifactSHA256']==build['sha256'], 'registered_build_hash')
    need(relative(build['expertRelativePath'],'MQL5/Experts/','.ex5'), 'expert_path')
    # Recorded for the later admission/connect step only; never read, written or created here.
    need(relative(build['credentialRelativePath'],'GOAT/Credentials/','.token'), 'credential_path')
    account=plan['account']
    need(type(account) is dict and set(account)=={'server','currency','leverage'}
         and isinstance(account['server'],str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}',account['server']) is not None
         and isinstance(account['currency'],str) and re.fullmatch('[A-Z]{3}',account['currency']) is not None
         and type(account['leverage']) is int and 1<=account['leverage']<=10000, 'account_policy')
    need(account['server'].endswith('-Demo'), 'demo_server_required')
    policy=plan['policy']
    need(type(policy) is dict and set(policy)=={'Mode_Lots','Risk','Mode_Bias','memberCount'} and type(policy['Mode_Lots']) is int
         and type(policy['Risk']) in (int,float) and math.isfinite(policy['Risk']) and policy['Risk']>0
         and type(policy['Mode_Bias']) is int and type(policy['memberCount']) is int and policy['memberCount']>=1, 'policy_schema')
    # Verify vendor signature from the source binary before copying it.
    quoted=str(Path(plan['sources']['terminal']['path'])).replace("'", "''")
    signature=host.powershell("$s=Get-AuthenticodeSignature -LiteralPath '"+quoted+"'; "
        "@{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject}|ConvertTo-Json -Compress")
    signature=json.loads(signature, object_pairs_hook=unique_object)
    need(type(signature) is dict and signature.get('status')=='Valid' and 'MetaQuotes' in str(signature.get('subject','')), 'terminal_signature')
    common=Path(plan['commonFiles']); output=Path(plan['outputDirectory'])
    # The dashboard only resolves SET paths under <TERMINAL_COMMONDATA_PATH>\Files.
    need(common.is_dir() and common.name.casefold()=='files', 'common_files_root')
    need(not output.exists(), 'output_already_exists')
    progress['stage']='validate_arms'
    need(type(plan['arms']) is list and len(plan['arms'])==2, 'pair_required')
    terminals=set(); logins=set()
    for arm in plan['arms']:
        need(type(arm) is dict and set(arm)=={'terminal','login','directory','label','aiLaunch'}, 'arm_schema')
        need(type(arm['terminal']) is int and 1<=arm['terminal']<=99, 'arm_terminal')
        progress['terminal']=arm['terminal']
        need(arm['terminal'] not in terminals, 'duplicate_terminal'); terminals.add(arm['terminal'])
        need(type(arm['login']) is int and arm['login']>0, 'arm_login')
        need(arm['login'] not in logins, 'duplicate_login'); logins.add(arm['login'])
        need(arm['login'] not in conn.PAIR_ACCOUNTS.values(), 'exp02_account_reserved')
        need(component(arm['label']), 'arm_label')
        need(absolute(arm['directory']) and ntpath.basename(arm['directory'])==f"{arm['terminal']:02d} - {arm['label']}", 'arm_directory')
        ai=arm['aiLaunch']
        need(type(ai) is dict and set(ai)=={'mode','threshold','protocol'}, 'ai_launch_schema')
        # Same bounds as the dashboard resume parser; Display Only (1) is not an experiment arm.
        need(type(ai['mode']) is int and ai['mode'] in (0,2), 'ai_launch_mode')
        need(type(ai['threshold']) is int and 1<=ai['threshold']<=100, 'ai_launch_threshold')
        need(type(ai['protocol']) is int and ai['protocol'] in (1,2), 'ai_launch_protocol')
        # An As Optimized (mode 0) arm runs each SET's own AI inputs, so the frozen bytes must pin them:
        # 1 = Bias_Disabled makes that arm truly AI-OFF (GOAT_Inputs_Definitions.mqh ENUM_ACTION_BIAS).
        need(ai['mode']!=0 or policy['Mode_Bias']==1, 'ai_off_requires_bias_disabled')
        directory=Path(arm['directory'])
        need(directory.parent.is_dir(), 'terminal_parent_missing')
        need(not directory.exists() and not host.processes(arm), 'new_directory_required')
    progress.pop('terminal',None)
    progress['stage']='verify_members'
    need(type(plan['members']) is list and len(plan['members'])==policy['memberCount'], 'member_count')
    members=[]; names=set()
    for index,member in enumerate(plan['members']):
        progress['memberIndex']=index
        need(type(member) is dict and set(member)=={'index','source','symbol','strategyName','name'}
             and type(member['index']) is int and member['index']==index, 'member_schema')
        name=member['name']
        need(isinstance(name,str) and Path(name).name==name and name.endswith('.set')
             and not any(c in name for c in '\t\r\n:'), 'member_filename')
        need(name.casefold() not in names, 'duplicate_set_path'); names.add(name.casefold())
        symbol=member['symbol']; label=member['strategyName']
        need(isinstance(symbol,str) and re.fullmatch('[A-Za-z0-9._-]{1,32}',symbol) is not None
             and isinstance(label,str) and not any(c in label for c in '\t\r\n'), 'member_labels')
        data=source(member['source'],2*1024*1024)
        try: text=data.decode('utf-16') if data.startswith(b'\xff\xfe') else data.decode('utf-8-sig')
        except UnicodeDecodeError: raise Refused('set_encoding') from None
        values={}
        for line in text.splitlines():
            if not line or line.startswith(';') or '=' not in line: continue
            key,value=line.split('=',1)
            need(key not in values, 'duplicate_set_input'); values[key]=value
        need(values.get('Mode_Operation')=='9', 'mode_operation_mismatch')
        need(values.get('Mode_Lots')==str(policy['Mode_Lots']), 'mode_lots_mismatch')
        need(number(values.get('Risk'))==policy['Risk'], 'risk_mismatch')
        need(values.get('Mode_Bias')==str(policy['Mode_Bias']), 'mode_bias_mismatch')
        members.append(dict(index=index,name=name,symbol=symbol,strategyName=label,data=data,sha256=sha(data)))
    progress.pop('memberIndex',None)
    progress['stage']='assemble_arms'
    expert_name,expert_path=chart_expert(build['expertRelativePath'])
    risk=f"Risk ${int(policy['Risk'])}"
    rows=[]; prepared=[]; arm_sets=[]
    for arm in sorted(plan['arms'],key=lambda a:a['terminal']):
        ordinal=arm['terminal']; login=arm['login']; directory=Path(arm['directory']); ai=arm['aiLaunch']
        progress['terminal']=ordinal
        header='\t'.join([AI_HEADER,str(ai['mode']),str(ai['threshold']),str(ai['protocol'])])
        label=bias_label(ai)
        sets_dir=common.joinpath(*namespace)/f"{ordinal:02d} - {arm['label']}"
        need(not sets_dir.exists(), 'set_namespace_exists')
        state=[header]; files={}; drafted=[]; paths=set()
        for member in members:
            dest=sets_dir/member['name']; need(str(dest).casefold() not in paths, 'duplicate_set_path'); paths.add(str(dest).casefold())
            state.append('\t'.join([str(dest),member['name'],member['symbol'],member['strategyName'],'OFF',label,risk,'0','0']))
            files[dest]=member['data']
            drafted.append(dict(index=member['index'],path=str(dest),symbol=member['symbol'],sha256=member['sha256']))
        arm_sets.append(tuple((member['name'],sha(files[sets_dir/member['name']])) for member in members))
        chart=bare_chart(); order='chart01.chr\r\n'.encode('utf-16'); config=fresh_common(login,account['server'])
        profile_claims=[['chart01.chr',sha(chart)],['order.wnd',sha(order)]]
        row=dict(terminal=ordinal,directory=str(directory),login=login,server=account['server'],currency=account['currency'],
                 leverage=account['leverage'],terminalSha256=sha(exe),eaSha256=sha(ea),profile='Default',
                 profileSha256=sha(json.dumps(profile_claims,separators=(',',':')).encode()),commonIniSha256=sha(config),
                 savedAlgoEnabled=False,expertRelativePath=build['expertRelativePath'],
                 credentialRelativePath=build['credentialRelativePath'],buildId=build['buildId'])
        rows.append(row)
        files.update({directory/'terminal64.exe':exe,directory/'config/servers.dat':servers,directory/'config/common.ini':config,
                      directory/build['expertRelativePath']:ea,directory/'MQL5/Profiles/Charts/Default/chart01.chr':chart,
                      directory/'MQL5/Profiles/Charts/Default/order.wnd':order})
        statepath=common/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
        controllers=[common/'GOAT'/n/directory.name for n in ('AgentSetup','AgentPortfolio')]
        need(not statepath.exists() and all(not p.exists() for p in controllers), 'controller_namespace_exists')
        files[statepath]=('\r\n'.join(state)+'\r\n').encode('utf-16')
        install=dict(directory=str(directory),account=login,server=account['server'],buildId=build['buildId'],eaSha256=sha(ea),
                     commonFiles=str(common),expertRelativePath=build['expertRelativePath'],
                     credentialRelativePath=build['credentialRelativePath'])
        draft=dict(schema=1,account=login,server=account['server'],directory=str(directory),buildId=build['buildId'],
                   expiresAtUtc=int(time.time())+14400,aiMode=ai['mode'],aiThreshold=ai['threshold'],aiProtocol=ai['protocol'],
                   exposureMode=0,members=drafted)
        files[output/f'dashboard-{ordinal:02d}.chr']=fresh_chart(expert_name,expert_path)
        fresh=[directory,sets_dir,statepath]+controllers
        prepared.append((row,files,install,draft,fresh,dict(terminal=ordinal,directory=str(directory),login=login,
                                                            aiLaunchHeader=header,biasLabel=label)))
    progress.pop('terminal',None)
    need(len(set(arm_sets))==1, 'set_bytes_differ')
    manifest=dict(schema=MANIFEST_SCHEMA,experiment=plan['experiment'],terminals=rows)
    validate_manifest(manifest); assert_new_pair_paths(rows,witness)
    summary={'status':'preflight_passed','tradingEnabled':False,'experiment':plan['experiment'],
             'arms':[item[5] for item in prepared],
             'members':[dict(index=m['index'],symbol=m['symbol'],name=m['name'],sha256=m['sha256']) for m in members],
             'identicalSetBytesAcrossArms':True,
             'files':[{str(p):sha(v) for p,v in item[1].items()} for item in prepared]}
    if not apply: return summary
    progress['stage']='acquire_lifecycle_lock'
    with lifecycle_lock(witness):
        progress['stage']='revalidate_protected_processes'
        checked_witness_n(witness_path,host,expected=witness)
        need(not output.exists() and all(not p.exists() for item in prepared for p in item[4])
             and all(not host.processes(r) for r in rows), 'preparation_race')
        progress['stage']='create_output'
        output.mkdir(parents=True,exist_ok=False)
        progress['stage']='write_installation_intent'
        write_new(output/'installation-intent.json',{'experiment':plan['experiment'],
                  'planSha256':sha(json.dumps(plan,sort_keys=True).encode()),'atUtc':time.time()})
        for row,files,install,draft,_,_ in prepared:
            progress.update(stage='create_terminal_directory',terminal=row['terminal'])
            directory=Path(row['directory']); directory.mkdir()
            progress['stage']='restrict_terminal_acl'
            acl=subprocess.run(['icacls',str(directory),'/inheritance:r','/grant:r','Administrator:(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True)
            need(acl.returncode==0, 'installation_acl_failed')
            for index,(path,data) in enumerate(files.items()):
                progress.update(stage='write_prepared_file',fileIndex=index)
                path.parent.mkdir(parents=True,exist_ok=True); write_new(path,data)
            progress.pop('fileIndex',None)
            progress['stage']='write_native_manifests'
            write_new(output/f'terminal-{row["terminal"]:02d}.json',install)
            write_new(output/f'portfolio-{row["terminal"]:02d}.json',draft)
            progress['stage']='verify_installed_files'
            conn.verify_files(row,True)
            need(all(sha(raw(path,128*1024*1024))==sha(data) for path,data in files.items()), 'installed_file_hash')
        progress.pop('terminal',None)
        progress['stage']='verify_final_protected_processes'
        checked_witness_n(witness_path,host,expected=witness)
        progress['stage']='write_completion'
        write_new(output/'reconnect-manifest.json',manifest)
        summary['status']='prepared_inert_no_launch'; write_new(output/'preparation.json',summary)
        progress['stage']='release_lifecycle_lock'
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--protected-witness',type=Path,required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    progress={'stage':'read_plan'}
    try: result=prepare(read(args.plan),WindowsHost(),args.protected_witness,args.apply,progress)
    except Exception as error:
        # No exception message, argv, local variables or full paths are emitted.
        result={'status':'needs_review','reason':str(error) if isinstance(error,Refused) else 'unexpected_error_inspect_retained_preparation',
                'stage':progress['stage'],'terminal':progress.get('terminal'),'memberIndex':progress.get('memberIndex'),
                'fileIndex':progress.get('fileIndex'),'exceptionType':type(error).__name__,
                'errno':error.errno if type(getattr(error,'errno',None)) is int else None,
                'winerror':error.winerror if type(getattr(error,'winerror',None)) is int else None}
    print(json.dumps(result));return 2 if result['status']=='needs_review' else 0

if __name__=='__main__':raise SystemExit(main())
