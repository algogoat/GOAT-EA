"""Read-only inventory of the shared native pointer and referenced queue."""
import argparse
from collections import Counter
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re


def inventory(common, server, version='1.48'):
    if not re.fullmatch(r'[A-Za-z0-9_. -]+',server):raise ValueError('Invalid server name')
    common=Path(common).resolve();base=common/'GOAT'/('GOAT V'+version+'-'+server)
    result=dict(observed_at=datetime.now(timezone.utc).isoformat(),launch_permitted=False,
        controls={},queue=None,limitations=['Queue status is not process liveness','Terminal batch flags must be inspected separately'])
    for name in ('active_optimization_run.ini','active_optimization_config.ini',
                 'active_optimization_launch.ini','agent-native-control-owner.json'):
        p=base/name
        result['controls'][name]=None if not p.exists() else dict(path=str(p),
            sha256=hashlib.sha256(p.read_bytes()).hexdigest(),modified_unix=p.stat().st_mtime)
    pointer=base/'active_optimization_run.ini'
    if not pointer.exists():return result
    raw=pointer.read_bytes();text=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    parser=configparser.ConfigParser(interpolation=None,strict=True);parser.optionxform=str
    parser.read_string(text)
    relative=PureWindowsPath(parser['ActiveOptimizationRun']['RunPath'])
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise ValueError('Native pointer escapes Common Files')
    run=common.joinpath(*relative.parts).resolve()
    if not run.is_relative_to(common):raise ValueError('Native pointer escapes Common Files')
    queue=run/'queue.GOAT'
    if not queue.exists():return result|dict(queue={'path':str(queue),'status':'missing'})
    raw=queue.read_bytes();text=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    entries=[]
    for block in text.split('\x1f'):
        if not block.strip():continue
        header=block.strip().splitlines()[0]
        match=re.fullmatch(r';(Pending|Queued|OnGoing|Completed|Error|Cancelled)_(.+);',header)
        if not match:raise ValueError('Unrecognized native queue header')
        entries.append(dict(status=match[1],title=match[2]))
    result['queue']=dict(path=str(queue),sha256=hashlib.sha256(raw).hexdigest(),
        modified_unix=queue.stat().st_mtime,status_counts=dict(Counter(e['status'] for e in entries)),
        unresolved=[e for e in entries if e['status'] in ('Pending','Queued','OnGoing')])
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--common',required=True);parser.add_argument('--server',required=True)
    args=parser.parse_args();print(json.dumps(inventory(args.common,args.server),indent=2))
