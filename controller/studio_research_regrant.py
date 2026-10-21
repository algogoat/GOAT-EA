"""A genuine native grant creates a new research epoch; old epochs stay revoked."""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
import time

from campaign_ledger import packed,sha
from studio_installation import read_json,load_installation
from studio_handover import safe_path
from studio_monitor_probe import inspect_idle_demo
from studio_receipt_digest import receipt_views
from studio_rejected_monitor import require_demo

OWNER_ACCOUNT={'login':'3000082754','server':'Darwinex-Demo'}

def context(db):
    root=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    install=load_installation(root/'installation.json');session=read_json(root/'session.json')
    if session['installation_sha256']!=sha(install):raise ValueError('Research installation changed')
    local=Path(install['terminal_data_root'])/'MQL5/Files/GOATStudio'
    expected=dict(directory_id=session['directory_id'],terminal_id=session['terminal_id'],run_id=session['run_id'],terminal_data_path=install['terminal_data_root'])
    if read_json(local/'active.json')!=expected:raise ValueError('Active research session changed')
    return SimpleNamespace(root=root,local=local,install=install,session=session,terminal=session['terminal_id'],run=session['run_id'])


def original(db,binding):
    row=db.execute('SELECT kind,provenance FROM studio_authorities WHERE binding=?',(binding,)).fetchone()
    if row is None or row[0]!='research_continuation':raise ValueError('Original typed research authority required')
    base=json.loads(row[1]);c=context(db)
    if (base!=read_json(c.root/'research-authority.json') or base['binding']!=json.loads(binding)
            or c.session.get('authority_sha256')!=sha(base) or base['installation_sha256']!=sha(c.install)
            or base['account']!=c.session['account'] or c.session.get('demo_only') is not True):
        raise ValueError('Original research authority, plan, account or build changed')
    return c,base


def takeover(db,binding,state):
    c,base=original(db,binding)
    if base['account']!=OWNER_ACCOUNT:
        raise ValueError('Owner demo research renewal scope required')
    if state['owner']!='human' or state['generation']!=base['generation']+1:
        raise ValueError('Exactly one genuine takeover of the original epoch required')
    found=[]
    # Runs on every renewed-epoch authority check: SQLite drops state.queue
    # first, so legacy multi-hundred-MB receipts are never parsed in Python.
    for row in receipt_views(db,binding):
        receipt=row[2];s=receipt.get('state',{})
        if (receipt.get('command')!='control.takeover' or receipt.get('status')!='applied'
                or receipt.get('execution_effect') is not False or s.get('owner')!='human'
                or s.get('generation')!=state['generation'] or s.get('revision')!=state['revision']):continue
        files=list(safe_path(c.local/c.session['directory_id']/'human/archive').glob(row[0]+'.*.json'))
        if len(files)!=1:raise ValueError('Exact archived native takeover required')
        request=read_json(safe_path(files[0]))
        if (request.get('command')!='control.takeover' or request.get('payload')!={}
                or request.get('generation')!=base['generation'] or request.get('expected_revision')!=state['revision']-1
                or {k:request.get(k) for k in ('terminal_id','run_id')}!=base['binding']
                or request.get('request_id')!=row[0] or sha(dict(request=request,actor='human'))!=row[1]):
            raise ValueError('Native takeover provenance changed')
        found.append(dict(request_id=row[0],payload_hash=row[1],request_sha256=hashlib.sha256(files[0].read_bytes()).hexdigest()))
    if len(found)!=1:raise ValueError('One genuine native takeover receipt required')
    return c,base,found[0]


def native(c,state,*,pending_id=''):
    from studio_resilient_read import read_observation
    from studio_runtime_check import check_runtime
    observation,modified=read_observation(c.local/'ui-observation.json')
    # EA9's observation schema has no terminal/run IDs. Bind it through the
    # verified active session plus its persisted editor, not invented wire fields.
    draft=read_json(safe_path(c.local/c.session['directory_id']/'human/ui-draft.json'))
    if (draft.get('schema_version')!=1 or observation.get('loaded') is not True
            or {k:draft.get(k) for k in ('terminal_id','run_id')}!={'terminal_id':c.terminal,'run_id':c.run}
            or any(draft.get(k)!=state[k] for k in ('revision','generation'))
            or any(draft.get(k)!=observation.get(k) for k in ('tester_ini','export_ini'))
            or draft.get('baseline')!=draft.get('tester_ini','')+draft.get('export_ini','') or draft.get('submitted')!=''):
        raise ValueError('Native editor binding or unsaved settings differ from the current session')
    i=c.install
    check_runtime(observation,now=time.time(),modified=modified,data_path=i['terminal_data_root'],
        installation_path=str(Path(i['terminal_executable']).parent),
        program_path=str((Path(i['terminal_data_root'])/'MQL5/Experts'/i['ea_relative_path'].replace('\\','/')).resolve()),
        account_login=c.session['account']['login'],account_server=c.session['account']['server'],require_idle=True)
    if any(observation.get(k)!=state[k] for k in ('owner','revision','generation')):
        raise ValueError('Native editor must confirm the actual human epoch before re-grant')
    if observation.get('pending_id') not in ('',pending_id):raise ValueError('Another native command is pending')
    result=inspect_idle_demo(c);require_demo(result)
    return result


def prepare(db,binding,state,request):
    c,base,prior=takeover(db,binding,state)
    if (request['command']!='control.grant_agent' or request['payload']!={}
            or request['generation']!=state['generation'] or request['expected_revision']!=state['revision']):
        raise ValueError('Fresh exact native grant required after takeover')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request['request_id']):
        raise ValueError('Bound native request identity required')
    if db.execute('SELECT 1 FROM studio_research_epochs WHERE binding=?',(binding,)).fetchone():
        raise ValueError('Research renewal already exists; never replay an old grant')
    # Only the trusted human bridge processing file can mint this epoch. A CLI
    # actor string or an agent-origin envelope cannot impersonate the click.
    path=safe_path(c.local/c.session['directory_id']/'human/processing'/(request['request_id']+'.json'))
    if not path.is_file() or read_json(path)!=request:raise ValueError('Genuine native processing request required')
    native_proof=native(c,state,pending_id=request['request_id'])
    now=time.time()
    value=base|dict(generation=state['generation']+1,created_utc=now,expires_utc=now+172800,
        renewal=dict(original_authority_sha256=sha(base),takeover=prior,grant_request=request,
                     grant_payload_hash=sha(dict(request=request,actor='human')),max_seconds=172800,
                     min_free_bytes=5368709120,native=native_proof))
    return value


def active(db,binding,state,base):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_research_epochs'").fetchone():return base
    row=db.execute('SELECT provenance FROM studio_research_epochs WHERE binding=? AND generation=?',(binding,state['generation'])).fetchone()
    if row is None:return base
    value=json.loads(row[0]);link=value['renewal'];request=link['grant_request']
    if state['owner']!='agent' or value['generation']!=base['generation']+2 or link['original_authority_sha256']!=sha(base):
        raise ValueError('Renewed research epoch revoked or changed')
    if {k:v for k,v in value.items() if k not in ('generation','created_utc','expires_utc','renewal')}!={k:v for k,v in base.items() if k not in ('generation','created_utc','expires_utc')}:
        raise ValueError('Renewed research scope differs from the original frozen plan/build')
    c,checked=original(db,binding)
    if value['expires_utc']!=value['created_utc']+172800 or link['max_seconds']!=172800 or link['min_free_bytes']!=5368709120:
        raise ValueError('New native research window changed')
    rows=receipt_views(db,binding,request['request_id'])
    if not rows or rows[0][1]!=link['grant_payload_hash'] or rows[0][1]!=sha(dict(request=request,actor='human')):
        raise ValueError('New native grant receipt is missing or changed')
    result=rows[0][2];granted=result['state']
    if (result.get('command')!='control.grant_agent' or result.get('status')!='applied' or result.get('execution_effect') is not False
            or granted['owner']!='agent' or granted['generation']!=value['generation']
            or request['generation']!=base['generation']+1 or granted['revision']!=request['expected_revision']+1):
        raise ValueError('Renewal does not have a genuine new-generation grant')
    _,_,prior=takeover(db,binding,dict(owner='human',generation=request['generation'],revision=request['expected_revision']))
    if prior!=link['takeover']:raise ValueError('Preceding native takeover changed')
    files=list(safe_path(c.local/c.session['directory_id']/'human/archive').glob(request['request_id']+'.*.json'))
    if len(files)!=1 or read_json(safe_path(files[0]))!=request:raise ValueError('New native grant archive required')
    return value
