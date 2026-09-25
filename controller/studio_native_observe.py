"""Read native queue evidence for a frozen package; never authorize a retry."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from campaign_ledger import sha


def observe(package):
    package = Path(package).resolve()
    manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    plan = json.loads((package/'studio-plan.json').read_text(encoding='utf-8'))
    if manifest['campaign_id'] != sha(plan) or not manifest['jobs']:
        raise ValueError('Frozen package identity mismatch')
    relative = manifest['native_run_relative']
    if not re.fullmatch(r'GOAT\\R[0-9a-f]{12}', relative):
        raise ValueError('Invalid native run path')
    root = Path(plan['research_binding']['common_files_root']).resolve()
    run = (root / relative.replace('\\','/')).resolve()
    if not run.is_relative_to(root):
        raise ValueError('Native run escapes Common Files')
    aliases=[item['run_alias'] for item in manifest['jobs']]
    if len(set(aliases))!=len(aliases) or any(not re.fullmatch(r'R[0-9a-f]{20}',alias) for alias in aliases):
        raise ValueError('Invalid or duplicate native alias')
    result = dict(observed_at=datetime.now(timezone.utc).isoformat(),
                  studio_source=plan['studio_source'], native_run=str(run),
                  run_alias=aliases[0], member_count=len(aliases), launch_permitted=False, retry_permitted=False,
                  process_liveness='not_observed', export_qualification='not_evaluated')
    queue = run/'queue.GOAT'
    if not queue.exists():
        return result | dict(status='native_evidence_missing',
                             next_action='Inspect activation and process ownership; absence does not prove stopped')
    raw = queue.read_bytes()
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    entries = [entry.strip() for entry in text.split('\x1f') if entry.strip()]
    if len(entries)!=len(manifest['jobs']):
        raise ValueError('Native queue/frozen member count mismatch')
    members=[];artifacts=[dict(path=str(queue),sha256=hashlib.sha256(raw).hexdigest())]
    for index,(entry,item) in enumerate(zip(entries,manifest['jobs'])):
        alias=item['run_alias'];lines=entry.splitlines();header=lines[0]
        match = re.fullmatch(r';(Pending|Queued|OnGoing|Completed|Error|Cancelled)_[^;\r\n]+:'+re.escape(alias)+r';', header)
        if not match:raise ValueError('Native queue identity/order/status mismatch')
        parser=configparser.ConfigParser(interpolation=None,strict=True);parser.optionxform=str
        parser.read_string('\n'.join(lines[1:]))
        expected={k:str(v) for k,v in item['tester'].items()}
        if parser.defaults() or parser.sections()!=['Tester'] or dict(parser['Tester'])!=expected:
            raise ValueError('Native tester configuration differs from frozen member')
        inputs=run/'inputs'/alias/'Inputs.GOAT';input_raw=inputs.read_bytes()
        if hashlib.sha256(input_raw).hexdigest()!=item['staged_sha256']:
            raise ValueError('Native strategy input drift')
        artifact=dict(path=str(inputs),sha256=hashlib.sha256(input_raw).hexdigest());artifacts.append(artifact)
        members.append(dict(index=index,run_alias=alias,status='native_'+match[1].lower(),
                            symbol=item['tester']['Symbol'],tester=item['tester'],input_artifact=artifact))
    states=[m['status'] for m in members]
    if states.count('native_ongoing')>1 or states.count('native_queued')>1:
        raise ValueError('Native batch has multiple active or queued members')
    if all(state=='native_completed' for state in states):status='native_completed'
    elif 'native_ongoing' in states:status='native_ongoing'
    elif 'native_queued' in states:status='native_queued'
    elif 'native_pending' in states:status='native_pending'
    elif 'native_error' in states:status='native_error'
    else:status='native_cancelled'
    return result | dict(status=status,members=members,status_counts={state:states.count(state) for state in sorted(set(states))},
        completed_count=states.count('native_completed'),finished_count=sum(state in ('native_completed','native_cancelled','native_error') for state in states),
        active_indices=[i for i,state in enumerate(states) if state in ('native_ongoing','native_queued')],artifacts=artifacts,
        next_action=('Verify each completed member report and export before finishing the batch' if status in ('native_completed','native_cancelled','native_error')
                     else 'Inspect native process and timeline before any execution-state transition'))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path)
    print(json.dumps(observe(parser.parse_args().package),indent=2))
