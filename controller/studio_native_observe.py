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
    if manifest['campaign_id'] != sha(plan) or len(manifest['jobs']) != 1:
        raise ValueError('Frozen package identity mismatch')
    relative = manifest['native_run_relative']
    if not re.fullmatch(r'GOAT\\R[0-9a-f]{12}', relative):
        raise ValueError('Invalid native run path')
    root = Path(plan['research_binding']['common_files_root']).resolve()
    run = (root / relative.replace('\\','/')).resolve()
    if not run.is_relative_to(root):
        raise ValueError('Native run escapes Common Files')
    item = manifest['jobs'][0]
    alias = item['run_alias']
    if not re.fullmatch(r'R[0-9a-f]{20}', alias):
        raise ValueError('Invalid native alias')
    result = dict(observed_at=datetime.now(timezone.utc).isoformat(),
                  studio_source=plan['studio_source'], native_run=str(run),
                  run_alias=alias, launch_permitted=False, retry_permitted=False,
                  process_liveness='not_observed', export_qualification='not_evaluated')
    queue = run/'queue.GOAT'
    if not queue.exists():
        return result | dict(status='native_evidence_missing',
                             next_action='Inspect activation and process ownership; absence does not prove stopped')
    raw = queue.read_bytes()
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    entries = [entry.strip() for entry in text.split('\x1f') if entry.strip()]
    if len(entries) != 1:
        raise ValueError('Single-job native queue expected')
    lines = entries[0].splitlines()
    header = lines[0]
    match = re.fullmatch(r';(Pending|Queued|OnGoing|Completed|Error|Cancelled)_[^;\r\n]+:'+re.escape(alias)+r';', header)
    if not match:
        raise ValueError('Native queue identity/status mismatch')
    parser = configparser.ConfigParser(interpolation=None,strict=True)
    parser.optionxform = str
    parser.read_string('\n'.join(lines[1:]))
    expected = {k:str(v) for k,v in item['tester'].items()}
    if parser.defaults() or parser.sections()!=['Tester'] or dict(parser['Tester'])!=expected:
        raise ValueError('Native tester configuration differs from frozen job')
    # Queue headers change as execution advances; frozen inputs must not.
    inputs = run/'inputs'/alias/'Inputs.GOAT'
    input_raw = inputs.read_bytes()
    if hashlib.sha256(input_raw).hexdigest()!=item['staged_sha256']:
        raise ValueError('Native strategy input drift')
    status = match[1]
    return result | dict(status='native_'+status.lower(),
        artifacts=[dict(path=str(queue),sha256=hashlib.sha256(raw).hexdigest()),
                   dict(path=str(inputs),sha256=hashlib.sha256(input_raw).hexdigest())],
        next_action=('Verify reports and exports before completing the Studio job' if status=='Completed'
                     else 'Inspect native process and timeline before any execution-state transition'))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path)
    print(json.dumps(observe(parser.parse_args().package),indent=2))
