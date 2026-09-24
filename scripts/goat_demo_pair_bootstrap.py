"""After bare broker qualification, gracefully close and stage one dashboard.

No kill fallback. Admission is required before the dashboard is installed into
the saved profile. Reconnect is a separate deliberate invocation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_prepare as p
from goat_demo_pair_lifecycle import replace_preserving_acl


def run(args):
    rows=c.validate_manifest(g.read(args.manifest));row=next(r for r in rows if r['terminal']==args.terminal)
    c.verify_files(row);g.verify_admission(args.admission_proof,args.admission_sha256,row)
    receipt=g.read(args.initial_receipt)
    c.require(receipt.get('status')=='verified_same_account' and receipt.get('initialLogin') is True
              and receipt.get('terminal')==row['terminal'] and receipt.get('launched') is True,'initial_receipt_required')
    process=receipt['process'];host=c.WindowsHost();witness=g.checked_witness(args.protected_witness,host)
    g.assert_new_pair_paths(rows,witness);c.require(host.processes(row)==[process],'initial_process_changed')
    draft=g.read(args.draft);c.require(draft['account']==row['login'] and draft['directory']==row['directory'] and len(draft['members'])==35,'draft_binding')
    c.require(not args.output.exists(),'new_output_required')
    with g.lifecycle_lock(witness):
        g.checked_witness(args.protected_witness,host,expected=witness)
        c.require(host.processes(row)==[process],'bootstrap_process_changed')
        args.output.mkdir(parents=True,exist_ok=False)
        g.claim_once(Path(row['directory'])/'GOAT-dashboard-bootstrap-intent.json',{'process':process,'output':str(args.output),'account':row['login']})
        sys.path.insert(0,str(args.sdk_path));import MetaTrader5 as mt
        c.require(mt.initialize(str(Path(row['directory'])/'terminal64.exe'),portable=True,timeout=15000),'inspect_attach')
        try:
            state=c.snapshot(mt,row)
            c.require(state['connected'] and not state['algoEnabled'] and state['balance']==100000 and state['equity']==100000
                      and not state['positionTickets'] and not state['orderTickets'],'initial_state_changed')
            for symbol in sorted({m['symbol'] for m in draft['members']}):
                c.require(mt.symbol_select(symbol,True),'symbol_select_failed')
                info=mt.symbol_info(symbol);c.require(info is not None and info.select and info.visible,'symbol_not_visible')
            g.write_new(args.output/'runtime-before.json',state)
        finally:mt.shutdown()
        c.require(host.processes(row)==[process],'before_close_process_changed')
        directory=Path(row['directory']);folder=directory/'MQL5/Profiles/Charts/Default'
        for chart in folder.glob('*.chr'):
            blob=g.raw(chart);text=blob.decode('utf16') if blob.startswith(b'\xff\xfe') else blob.decode('utf-8-sig')
            c.require('<expert>' not in text,'bare_profile_required')
        g.write_new(args.output/'close-intent.json',{'process':process,'atUtc':time.time(),'method':'graceful_close_main_window'})
        # Exact pinned PID revalidated immediately above; this is graceful close,
        # never TerminateProcess/Stop-Process. Failure leaves retained intent.
        executable=process['path'].replace("'","''");created=process['created'].replace("'","''")
        raw=host.powershell("$n=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(process['pid'])+"'; "
             "if(-not $n -or $n.ExecutablePath -ne '"+executable+"' -or $n.CreationDate.ToUniversalTime() -ne [datetime]::Parse('"+created+"').ToUniversalTime()){throw 'process changed'}; "
             "$p=Get-Process -Id "+str(process['pid'])+" -ErrorAction Stop; @{accepted=[bool]$p.CloseMainWindow()}|ConvertTo-Json -Compress")
        close=json.loads(raw);g.write_new(args.output/'close-result.json',close)
        c.require(close.get('accepted') is True,'graceful_close_not_accepted')
        deadline=time.monotonic()+45
        while host.processes(row) and time.monotonic()<deadline:time.sleep(1)
        c.require(not host.processes(row),'graceful_close_not_finished')
        g.checked_witness(args.protected_witness,host,expected=witness)
        charts=list(folder.glob('*.chr'));c.require(len(charts)==1,'unexpected_bare_chart_count')
        chart=charts[0];before=g.raw(chart);g.write_new(args.output/'bare-chart-before.chr',before)
        replacement=p.fresh_chart()
        replace_preserving_acl(chart,replacement)
        claims=[]
        for file in sorted(folder.rglob('*')):
            c.require(not file.is_symlink() and not file.is_junction(),'profile_alias')
            if file.is_file():claims.append([file.relative_to(folder).as_posix(),c.file_hash(file,2*1024*1024)])
        row['profileSha256']=hashlib.sha256(json.dumps(claims,separators=(',',':')).encode()).hexdigest()
        row['commonIniSha256']=c.file_hash(directory/'config/common.ini',1024*1024)
        c.verify_files(row,True)
        manifest={'schema':'goat-demo-pair-connection-v1','terminals':rows};c.validate_manifest(manifest)
        g.write_new(args.output/'reconnect-manifest.json',manifest)
        result={'status':'dashboard_staged_inert_no_launch','terminal':row['terminal'],'account':row['login'],
                'reconnectManifest':str(args.output/'reconnect-manifest.json'),'closedProcess':process,
                'symbolsSelected':len({m['symbol'] for m in draft['members']}),'atUtc':time.time()}
        g.write_new(args.output/'completion.json',result);return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['manifest','initial-receipt','draft','protected-witness','sdk-path','output','admission-proof']:
        ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--admission-sha256',required=True);ap.add_argument('--terminal',type=int,choices=[7,8],required=True);args=ap.parse_args()
    try:result=run(args)
    except c.Refused as error:result={'status':'needs_review','reason':str(error)}
    except Exception:result={'status':'needs_review','reason':'bootstrap_failed_inspect_retained_evidence'}
    if result['status']=='needs_review' and args.output.exists() and not (args.output/'failure.json').exists():g.write_new(args.output/'failure.json',result)
    print(json.dumps(result));return 2 if result['status']=='needs_review' else 0

if __name__=='__main__':raise SystemExit(main())
