"""Internal runner boundary: record intent, without launching or activating MT5."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from campaign_ledger import packed, sha
from activate_research_campaign import verify_export_policy
from studio_command_store import Conflict
from studio_batch_contract import configuration_members
from studio_strategy_settings import read_values


def record_intent(store, terminal_id, run_id, job_id, package, *, actor, revision, generation):
    package=Path(package).resolve()
    raw=(package/'manifest.json').read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    manifest=json.loads(raw)
    plan=json.loads((package/'studio-plan.json').read_text(encoding='utf-8'))
    if manifest['campaign_id']!=sha(plan) or not manifest['jobs']:
        raise ValueError('Package plan identity mismatch')
    source=plan['studio_source']
    if (source['terminal_id'],source['run_id'],source['job_id'])!=(terminal_id,run_id,job_id):
        raise ValueError('Package belongs to another Studio job')
    verify_export_policy(package,plan,manifest)
    aliases=set()
    for item in manifest['jobs']:
        alias=item['run_alias']
        if not isinstance(alias,str) or not re.fullmatch(r'R[0-9a-f]{20}',alias) or alias in aliases:
            raise ValueError('Unsafe or duplicate staged alias')
        aliases.add(alias)
        for suffix,key in (('.set','staged_sha256'),('.ini','ini_sha256')):
            if hashlib.sha256((package/(alias+suffix)).read_bytes()).hexdigest()!=item[key]:
                raise ValueError('Staged input/config drift')
    # The transaction is the single-writer boundary. No external process starts
    # here; a starting state left behind by interruption requires reconciliation.
    with store.transaction():
        state=store.snapshot(terminal_id,run_id)
        if (state['revision'],state['generation'],state['owner'])!=(revision,generation,actor):
            raise Conflict('Controller changed before launch intent')
        job=next((j for j in state['queue'] if j['job_id']==job_id),None)
        if job is None or job['status']!='reserved':
            raise Conflict('Job is not reserved; reconcile any existing attempt')
        reservation=job['reservation']
        if (reservation['owner'],reservation['generation'])!=(actor,generation):
            raise Conflict('Reservation authority was revoked')
        if reservation['package_sha256']!=digest or source['configuration_sha256']!=job['configuration_sha256'] or sha(job['configuration'])!=job['configuration_sha256']:
            raise ValueError('Reserved package/configuration mismatch')
        members=configuration_members(job['configuration'])
        if len(members)!=len(manifest['jobs']):raise ValueError('Frozen package member count mismatch')
        for member,item in zip(members,manifest['jobs']):
            alias=item['run_alias']
            if read_values((package/(alias+'.set')).read_bytes())!=(member['strategy']['values']|{'EA_Desc':alias}):
                raise ValueError('Staged member differs from frozen strategy')
            if any(str(value)!=str(item['tester'].get(key)) for key,value in member['tester'].items()):
                raise ValueError('Staged member differs from frozen tester')
            from studio_native_request import ini_sections
            sections=ini_sections((package/(alias+'.ini')).read_bytes())
            if sections.get('Tester')!={key:str(value) for key,value in item['tester'].items()}:
                raise ValueError('Staged INI differs from manifest tester')
            if sections.get('TesterInputs')!=read_values((package/(alias+'.set')).read_bytes()):
                raise ValueError('Staged INI input values differ from retained SET')
        intent=dict(attempt_id=sha([reservation['reservation_id'],digest]),
                    package=str(package),package_sha256=digest,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    native_launch_permitted=False,
                    required_next_step='Fresh native ownership/account/binary checks and activation adapter')
        job.update(status='starting',launch_intent=intent)
        binding=packed(dict(terminal_id=terminal_id,run_id=run_id))
        store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(state['queue']),binding))
        store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
        return intent
