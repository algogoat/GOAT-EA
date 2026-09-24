"""Fresh pair-only inert installation. Dry-run by default; never starts MT5.

Sources are explicit signed-terminal/broker-server files, the reviewed V1.48 EA,
and frozen SETs. No old common.ini, profile, account database or token is copied.
Run on the intended host with a pinned plan after reviewing dry-run output.
"""
import argparse
import hashlib
import json
import ntpath
from pathlib import Path
import re
import subprocess
import time

import goat_demo_pair_connection as conn
from goat_demo_pair_guard import raw, read, write_new, checked_witness, lifecycle_lock, assert_new_pair_paths

need = conn.require


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source(entry, limit=128*1024*1024):
    need(type(entry) is dict and set(entry)=={'path','sha256'}, 'source_reference')
    need(re.fullmatch('[a-f0-9]{64}', entry['sha256'] or '') is not None
         and entry['sha256'] != '0'*64, 'source_hash_required')
    data=raw(entry['path'], limit)
    need(sha(data)==entry['sha256'], 'source_hash_changed')
    return data


def fresh_chart():
    # No inherited ID, objects, positions, order history or child magic. MT5
    # assigns the persistent chart identity on first load and saves it on exit.
    text='''<chart>
symbol=EURUSD
period_type=0
period_size=1
scale=8
mode=1
grid=0
scroll=1
one_click=0
window_left=0
window_top=0
window_right=1280
window_bottom=800
window_type=3
floating=0
windows_total=1
<expert>
name=GOAT V1.48
path=Experts\\GOAT Experiment\\GOAT V1.48.ex5
expertmode=5
<inputs>
Mode_Operation=8
Dashboard_Resume_Saved=true
Mode_Bias=1
Bias_Protocol=2
Bias_threshold=50
</inputs>
</expert>
<window>
height=100.000000
objects=0
<indicator>
name=Main
path=
apply=1
show_data=1
</indicator>
</window>
</chart>
'''
    return text.replace('\n','\r\n').encode('utf-16')


def fresh_common(login):
    # Native permissions still require runtime proof. These are intentional
    # user-authorized settings for the new accounts only; Algo remains disabled.
    return (f'[Common]\r\nLogin={login}\r\nServer=Darwinex-Demo\r\nKeepPrivate=1\r\nNewsEnable=0\r\n'
            '[Charts]\r\nProfileLast=Default\r\n'
            '[Experts]\r\nEnabled=0\r\nAllowLiveTrading=1\r\nAllowDllImport=1\r\n'
            'Account=0\r\nProfile=0\r\nChart=0\r\n'
            'WebRequest=1\r\nWebRequestUrl=https://goatedge.ai\r\n').encode('utf-16')


def bare_chart():
    text=fresh_chart().decode('utf16')
    return re.sub(r'<expert>.*?</expert>\r\n','',text,flags=re.S).encode('utf16')


def prepare(plan, host, witness_path, apply=False, progress=None):
    progress={} if progress is None else progress
    progress['stage']='validate_plan'
    need(type(plan) is dict and set(plan)=={'schema','commonFiles','outputDirectory','sources','terminals'}
         and plan['schema']=='goat-demo-pair-install-v1', 'plan_schema')
    need(ntpath.isabs(plan['commonFiles']) and ntpath.isabs(plan['outputDirectory']), 'absolute_paths')
    witness=checked_witness(witness_path, host)
    need(type(plan['terminals']) is list and len(plan['terminals'])==2, 'pair_required')
    need(set(plan['sources'])=={'terminal','servers','ea'}, 'source_allowlist')
    exe=source(plan['sources']['terminal']); servers=source(plan['sources']['servers'], 8*1024*1024)
    ea=source(plan['sources']['ea'],32*1024*1024)
    # Verify vendor signature from the source binary before copying it.
    quoted=str(Path(plan['sources']['terminal']['path'])).replace("'", "''")
    signature=host.powershell("$s=Get-AuthenticodeSignature -LiteralPath '"+quoted+"'; "
        "@{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject}|ConvertTo-Json -Compress")
    signature=json.loads(signature)
    need(signature.get('status')=='Valid' and 'MetaQuotes' in signature.get('subject',''), 'terminal_signature')
    rows=[]; prepared=[]; common=Path(plan['commonFiles']); output=Path(plan['outputDirectory'])
    need(not output.exists(), 'output_already_exists')
    for arm in sorted(plan['terminals'],key=lambda a:a['terminal']):
        need(type(arm) is dict and set(arm)=={'terminal','login','directory','members'}, 'arm_schema')
        ordinal=arm['terminal']; login=arm['login']; directory=Path(arm['directory'])
        need(ordinal in conn.PAIR_ACCOUNTS and login==conn.PAIR_ACCOUNTS[ordinal], 'pair_account')
        need(ntpath.basename(str(directory)) == f'{ordinal:02d} - Balanced 35 - AI '+('OFF' if ordinal==7 else 'ON'), 'pair_directory')
        need(not directory.exists() and not host.processes(arm), 'new_directory_required')
        need(type(arm['members']) is list and len(arm['members'])==35, 'exact35')
        ai_mode=0 if ordinal==7 else 2
        state=['\t'.join(['#GOAT_AI_LAUNCH_V147_2',str(ai_mode),'50','2'])]
        members=[]; files={}; paths=set()
        sets_dir=common/'GOAT Experiments'/'Balanced 35 AI - 2026-09-24'/f'{ordinal:02d} - {"Control" if ordinal==7 else "AI"}'
        need(not sets_dir.exists(), 'set_namespace_exists')
        for index,member in enumerate(arm['members']):
            need(type(member) is dict and set(member)=={'index','source','symbol','strategyName','name'}
                 and member['index']==index, 'member_schema')
            need(Path(member['name']).name==member['name'] and member['name'].endswith('.set')
                 and not any(c in member['name'] for c in '\t\r\n:'), 'member_filename')
            data=source(member['source'],2*1024*1024)
            text=data.decode('utf-16') if data.startswith(b'\xff\xfe') else data.decode('utf-8-sig')
            values={}
            for line in text.splitlines():
                if not line or line.startswith(';') or '=' not in line: continue
                key,value=line.split('=',1)
                need(key not in values, 'duplicate_set_input'); values[key]=value
            need(values.get('Mode_Bias')==('1' if ordinal==7 else '2')
                 and values.get('Bias_Protocol')=='2' and values.get('Bias_threshold')=='50'
                 and values.get('Mode_Lots')=='2' and float(values.get('Risk','nan'))==500, 'frozen_policy_mismatch')
            dest=sets_dir/member['name']; need(str(dest).casefold() not in paths, 'duplicate_set_path'); paths.add(str(dest).casefold())
            symbol=member['symbol']; label=member['strategyName']
            need(re.fullmatch('[A-Za-z0-9._-]{1,32}',symbol) is not None
                 and isinstance(label,str) and not any(c in label for c in '\t\r\n'), 'member_labels')
            state.append('\t'.join([str(dest),member['name'],symbol,label,'OFF',
                                     'OFF' if ordinal==7 else 'ON / DEMO / 50%','Risk $500','0','0']))
            files[dest]=data
            members.append(dict(index=index,path=str(dest),symbol=symbol,sha256=sha(data)))
        chart=bare_chart(); order='chart01.chr\r\n'.encode('utf-16'); config=fresh_common(login)
        profile_claims=[['chart01.chr',sha(chart)],['order.wnd',sha(order)]]
        row=dict(terminal=ordinal,directory=str(directory),login=login,server='Darwinex-Demo',currency='USD',leverage=200,
                 terminalSha256=sha(exe),eaSha256=sha(ea),profile='Default',profileSha256=sha(json.dumps(profile_claims,separators=(',',':')).encode()),
                 commonIniSha256=sha(config),savedAlgoEnabled=False,expertRelativePath=conn.EXPERT_RELATIVE,
                 credentialRelativePath=conn.CREDENTIAL_RELATIVE,buildId=conn.BUILD_ID)
        rows.append(row)
        files.update({directory/'terminal64.exe':exe,directory/'config/servers.dat':servers,directory/'config/common.ini':config,
                      directory/conn.EXPERT_RELATIVE:ea,directory/'MQL5/Profiles/Charts/Default/chart01.chr':chart,
                      directory/'MQL5/Profiles/Charts/Default/order.wnd':order})
        statepath=common/'GOAT'/('dashboard_state_'+directory.name+'.tsv')
        need(not statepath.exists() and all(not (common/'GOAT'/n/directory.name).exists() for n in ['AgentSetup','AgentPortfolio']), 'controller_namespace_exists')
        files[statepath]=('\r\n'.join(state)+'\r\n').encode('utf-16')
        install=dict(directory=str(directory),account=login,server='Darwinex-Demo',buildId=conn.BUILD_ID,eaSha256=sha(ea),commonFiles=str(common),
                     expertRelativePath=conn.EXPERT_RELATIVE,credentialRelativePath=conn.CREDENTIAL_RELATIVE)
        draft=dict(schema=1,account=login,server='Darwinex-Demo',directory=str(directory),buildId=conn.BUILD_ID,
                   expiresAtUtc=int(time.time())+14400,aiMode=ai_mode,aiThreshold=50,aiProtocol=2,exposureMode=0,members=members)
        files[output/f'dashboard-{ordinal:02d}.chr']=fresh_chart()
        prepared.append((row,files,install,draft))
    manifest=dict(schema='goat-demo-pair-connection-v1',terminals=rows)
    conn.validate_manifest(manifest); assert_new_pair_paths(rows,witness)
    summary={'status':'preflight_passed','tradingEnabled':False,'membersPerArm':35,'files':[{str(p):sha(v) for p,v in files.items()} for _,files,_,_ in prepared]}
    if not apply: return summary
    progress['stage']='acquire_lifecycle_lock'
    with lifecycle_lock(witness):
        progress['stage']='revalidate_protected_processes'
        checked_witness(witness_path,host,expected=witness)
        need(all(not Path(r['directory']).exists() and not host.processes(r) for r in rows), 'preparation_race')
        progress['stage']='create_output'
        output.mkdir(parents=True,exist_ok=False)
        progress['stage']='write_installation_intent'
        write_new(output/'installation-intent.json',{'planSha256':sha(json.dumps(plan,sort_keys=True).encode()),'atUtc':time.time()})
        for row,files,install,draft in prepared:
            progress.update(stage='create_terminal_directory',terminal=row['terminal'])
            directory=Path(row['directory']); directory.mkdir()
            progress['stage']='restrict_terminal_acl'
            acl=subprocess.run(['icacls',str(directory),'/inheritance:r','/grant:r','Administrator:(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True)
            need(acl.returncode==0, 'installation_acl_failed')
            for index,(path,data) in enumerate(files.items()):
                progress.update(stage='write_prepared_file',fileIndex=index)
                path.parent.mkdir(parents=True,exist_ok=True); write_new(path,data)
            progress['stage']='write_native_manifests'
            write_new(output/f'terminal-{row["terminal"]:02d}.json',install)
            write_new(output/f'portfolio-{row["terminal"]:02d}.json',draft)
            progress['stage']='verify_installed_files'
            conn.verify_files(row,True)
        progress['stage']='verify_final_protected_processes'
        checked_witness(witness_path,host,expected=witness)
        progress['stage']='write_completion'
        write_new(output/'reconnect-manifest.json',manifest)
        summary['status']='prepared_inert_no_launch'; write_new(output/'preparation.json',summary)
        progress['stage']='release_lifecycle_lock'
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--protected-witness',type=Path,required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    progress={'stage':'read_plan'}
    try: result=prepare(read(args.plan),conn.WindowsHost(),args.protected_witness,args.apply,progress)
    except Exception as error:
        # No exception message, argv, local variables or full paths are emitted.
        result={'status':'needs_review','reason':str(error) if isinstance(error,conn.Refused) else 'unexpected_error_inspect_retained_preparation',
                'stage':progress['stage'],'terminal':progress.get('terminal'),'fileIndex':progress.get('fileIndex'),
                'exceptionType':type(error).__name__,
                'errno':error.errno if type(getattr(error,'errno',None)) is int else None,
                'winerror':error.winerror if type(getattr(error,'winerror',None)) is int else None}
    print(json.dumps(result));return 2 if result['status']=='needs_review' else 0

if __name__=='__main__':raise SystemExit(main())
