"""Exact install authorization and typed, one-time owner research continuation."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import time

from campaign_ledger import packed, sha
from studio_bridge import StudioBridge, write_json
from studio_build_upgrade import retain
from studio_command_store import StudioStore
from studio_handover import paths, stopped, safe_path, load_plan, guard, tree
from studio_installation import read_json, load_installation
from studio_installation_upgrade import inspect_park
from studio_native_gate import exclusive_gate, configure_gate
from studio_owner_maintenance import read_record, authorize_park, human_clear, revoke, POLICY_PATH
from studio_onboarding import saved_launch_policy


def original(c, value):
    return SimpleNamespace(root=c.root, local=c.local, install=value['installation'])


def parked(c, record_id):
    folder, value = read_record(c, record_id)
    if (folder/'retired.json').exists():
        raise ValueError('Owner maintenance record is retired; no further upgrade or bootstrap')
    old = original(c, value)
    intent = read_json(folder/'park-intent.json')
    plan = load_plan(old, intent['review_id'])
    if plan['status']!='complete':
        raise ValueError('Exact completed owner PARK required')
    stopped(c, [v['path'] for v in plan['after_ownership']])
    authorize_park(old, record_id, plan)
    if read_json(folder/'parked.json') != dict(intent, receipt_sha256=sha(plan), grants_control=False, starts_work=False):
        raise ValueError('Owner PARK completion audit differs')
    return folder, value, old, plan


def prepare_install(c, record_id):
    """Freeze exact input for the existing authenticated desktop installer."""
    lock = paths(c)[3]; lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock):
        folder, value, old, plan = parked(c, record_id)
        guard(c)
        if c.install!=value['installation']:
            raise ValueError('Install authorization requires the original parked installation')
        verification = inspect_park(old, plan['review_id'])
        params = dict(accountId=value['session']['account']['login'], buildId='V1.49-ORPHAN-DIRECTORY-9',
                      selection=dict(portable=c.install['terminal_portable'],
                        terminalDataRoot=c.install['terminal_data_root'],terminalExecutable=c.install['terminal_executable']),
                      parkReviewId=plan['review_id'])
        intent = dict(step='install',record_sha256=sha(value),park_receipt_sha256=sha(plan),
                      previous_receipt_sha256=verification['receipt_sha256'],
                      target_ea_sha256=value['target_ea_sha256'],params=params)
        retain(folder/'install-intent.json',(packed(intent)+'\n').encode())
        return dict(status='exact_install_authorized', record_id=record_id, params=params,
                    target_ea_sha256=value['target_ea_sha256'], grants_control=False, starts_work=False)


def verify_install(c, folder, value, old, plan):
    guard(c)
    intent = read_json(folder/'install-intent.json')
    archive = paths(c)[2]/plan['review_id']
    journal = read_json(archive/'build-upgrade.json')
    raw = (c.root/'installation.json').read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if (intent['record_sha256']!=sha(value) or intent['park_receipt_sha256']!=sha(plan)
            or intent['target_ea_sha256']!=value['target_ea_sha256']
            or journal.get('status')!='build_replaced' or journal.get('review_id')!=plan['review_id']
            or journal.get('previous_sha256')!=intent['previous_receipt_sha256']
            or journal.get('previous_installation_sha256')!=sha(value['installation'])
            or journal.get('candidate_installation_sha256')!=sha(c.install)
            or journal.get('candidate_sha256')!=digest or journal.get('receipt_sha256')!=digest
            or c.install.get('ea_sha256')!=value['target_ea_sha256']
            or journal.get('ea_sha256')!=value['target_ea_sha256']
            or journal.get('candidate_ea_sha256')!=value['target_ea_sha256']
            or any(journal.get(k) is not False for k in ('session_created','agent_control_granted','terminal_started'))
            or load_installation(c.root/'installation.json')!=c.install
            or (archive/'build-upgrade.candidate.json').read_bytes()!=raw
            or hashlib.sha256((archive/'build-upgrade.candidate.ex5').read_bytes()).hexdigest()!=value['target_ea_sha256']):
        raise ValueError('Exact authenticated install/CAS completion evidence required')
    mutable = {'bundle_version','ea_sha256','agent_guide_path','installed_at'}
    if set(c.install)!=set(old.install) or any(c.install[k]!=old.install[k] for k in set(c.install)-mutable):
        raise ValueError('Research continuation cannot change terminal, account or installation scope')
    installed = dict(step='installed', record_sha256=sha(value), journal_sha256=sha(journal),
                     receipt_sha256=digest, target_ea_sha256=value['target_ea_sha256'])
    retain(folder/'installed.json',(packed(installed)+'\n').encode())
    return installed


def bootstrap(c, record_id, plan_path):
    """Publish a pre-bound restricted session while every native writer is absent."""
    lock = paths(c)[3]; lock.mkdir(parents=True,exist_ok=True)
    with exclusive_gate(lock):
        folder, value, old, plan = parked(c, record_id)
        installed = verify_install(c, folder, value, old, plan)
        # Uses the prior broker-confirmed demo and exact normal-stop identity;
        # saved login/server and Algo OFF must also remain unchanged. Actual SDK
        # connected-demo/Algo OFF checks run again before every native dispatch.
        saved_launch_policy(c, value['session'])
        from studio_batch import read_plan
        config, members, _, plan_hash, _ = read_plan(c, plan_path)
        if plan_hash!=value['plan_sha256']:
            raise ValueError('Replacement session only authorizes the exact frozen batch plan')
        expected = dict(record_sha256=sha(value), installed_sha256=sha(installed),
                        configuration_sha256=sha(config), members_sha256=sha(members),
                        installation_sha256=sha(c.install), plan_sha256=plan_hash,
                        account=value['session']['account'], generation=0,
                        kind='research_continuation',
                        binding=dict(terminal_id=value['session']['terminal_id'],run_id=value['replacement_run_id']),
                        original_grant_request_id=value['original_grant_request_id'],
                        original_grant_payload_hash=value['original_grant_payload_hash'],
                        original_generation=value['original_generation'])
        intent_path = folder/'bootstrap-intent.json'
        if intent_path.exists():
            intent = read_json(intent_path)
            authority = intent['authority']
            if any(authority.get(k)!=v for k,v in expected.items()):
                raise ValueError('Interrupted bootstrap identity changed; never widen or re-mint')
            if not authority['created_utc']<=time.time()<authority['expires_utc']<=authority['created_utc']+86400:
                raise ValueError('Retained research bootstrap authority expired')
        else:
            inspect_park(old,plan['review_id'],allowed_receipt_sha256=installed['receipt_sha256'])
            now = time.time()
            authority = dict(expected,created_utc=now,expires_utc=min(now+86400,read_json(POLICY_PATH)['expires_utc']))
            intent = dict(step='bootstrap',authority=authority)
            retain(intent_path,(packed(intent)+'\n').encode())
        run = value['replacement_run_id']; terminal=value['session']['terminal_id']
        session = dict(schema_version=1,installation_sha256=sha(c.install),terminal_id=terminal,
                       run_id=run,directory_id=run,account=value['session']['account'],demo_only=True,
                       authority_kind='research_continuation',authority_sha256=sha(authority))
        active = dict(directory_id=run,terminal_id=terminal,run_id=run,terminal_data_path=c.install['terminal_data_root'])
        # Exact-prefix recovery only. A published differing session or any new
        # human event is never adopted or overwritten.
        for name, item in (('session.json',session),('research-authority.json',authority)):
            retain(c.root/name,(packed(item)+'\n').encode())
        (c.root/'requests').mkdir(exist_ok=True)
        if any((c.root/'requests').iterdir()):
            raise ValueError('Unexpected command request during continuation bootstrap')
        c.local.mkdir(parents=True,exist_ok=True)
        if (c.local/'active.json').exists() and read_json(c.local/'active.json')!=active:
            raise ValueError('Another session became active during continuation bootstrap')
        human = c.local/run/'human'
        if human.exists():
            human_clear(folder,human)
        store = StudioStore(c.root/'studio.sqlite',input_schema=c.schema,dependency_policy=c.policy)
        try:
            configure_gate(store,c.local/'native-gate')
            with store.transaction(require_clear_controls=True):
                binding = packed(authority['binding'])
                rows = list(store.db.execute('SELECT binding,revision,generation,owner FROM studio_state'))
                if rows and [tuple(row) for row in rows]!=[(binding,0,0,'agent')]:
                    revoke(folder,'replacement state was changed or taken over')
                for table in ('studio_receipts','studio_drafts','studio_export_drafts','studio_queues','studio_strategy_drafts'):
                    if store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:
                        raise ValueError('Unexpected work or human receipt during bootstrap')
                authorities = [tuple(row) for row in store.db.execute('SELECT binding,kind,provenance FROM studio_authorities')]
                wanted = (binding,'research_continuation',packed(authority))
                if authorities and authorities!=[wanted]:
                    raise ValueError('Replacement authority differs; no promotion or grant migration')
                if human.exists(): human_clear(folder,human)
                store.db.execute('INSERT OR IGNORE INTO studio_authorities VALUES(?,?,?)',wanted)
                store.db.execute('INSERT OR IGNORE INTO studio_state VALUES(?,0,0,?)',(binding,'agent'))
                # No control.grant_agent command or actor=human receipt exists.
            bridge = StudioBridge(c.local/run,store,terminal,run)
            bridge.pump()
            human_clear(folder,human)
            preset = Path(c.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
            raw='Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
            preset.parent.mkdir(parents=True,exist_ok=True)
            retain(preset,raw)
            retain(c.local/'active.json',(packed(active)+'\n').encode())
            completed=dict(step='bootstrapped',record_sha256=sha(value),authority_sha256=sha(authority),
                           session_sha256=sha(session),human_grant_created=False,trading_enabled=False,work_started=False)
            retain(folder/'bootstrapped.json',(packed(completed)+'\n').encode())
            retain(folder/'retired.json',(packed(dict(record_sha256=sha(value),completion_sha256=sha(completed)))+'\n').encode())
            return dict(status='research_continuation_bootstrapped',run_id=run,
                        authority_kind='research_continuation',human_grant_created=False,work_started=False)
        finally:
            store.close()
