"""Internal permit transport; the runner must supply native validation in-lock.

Not a public launch API: native activation/ownership validation is deliberately
required as a callable, never accepted as a caller-provided success boolean.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from datetime import datetime, timezone
from campaign_ledger import sha
from studio_bridge import display_state, write_json
from studio_command_store import Conflict
from studio_native_gate import exclusive_gate


def publish(store, terminal_id, run_id, job_id, bridge_root, *, actor, revision,
            generation, validate_native, lifetime=30):
    return _publish(store,terminal_id,run_id,job_id,bridge_root,actor=actor,revision=revision,
        generation=generation,validate_native=validate_native,lifetime=lifetime,restart=False)


def publish_restart_arm(store, terminal_id, run_id, job_id, bridge_root, *, actor,
                        revision, generation, validate_native, lifetime=30):
    return _publish(store,terminal_id,run_id,job_id,bridge_root,actor=actor,revision=revision,
        generation=generation,validate_native=validate_native,lifetime=lifetime,restart=True)


def _publish(store, terminal_id, run_id, job_id, bridge_root, *, actor, revision,
             generation, validate_native, lifetime, restart):
    if type(lifetime) is not int or not 1 <= lifetime <= 120:
        raise ValueError('Permit lifetime must be 1..120 seconds')
    row=store.db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
    if row is None:
        raise ValueError('Native gate must be configured before publication')
    root=Path(row[0]); bridge_root=Path(bridge_root).resolve()
    database=str(Path(store.db.execute('PRAGMA database_list').fetchone()[2]).resolve())
    with exclusive_gate(root):
        binding=json.loads((bridge_root/'binding.json').read_text(encoding='utf-8'))
        if binding!=dict(protocol_version=1,terminal_id=terminal_id,run_id=run_id,database=database):
            raise ValueError('Bridge belongs to another controller binding')
        state=store.snapshot(terminal_id,run_id)
        if (state['owner'],state['revision'],state['generation'])!=(actor,revision,generation):
            raise Conflict('Controller changed before permit publication')
        job=next((j for j in state['queue'] if j['job_id']==job_id),None)
        if not job or job['status']!='starting' or sha(job['configuration'])!=job['configuration_sha256']:
            raise Conflict('Verified starting job required')
        if not restart and 'restart_intent' in job:
            raise Conflict('Restart route already selected; open-terminal dispatch forbidden')
        if restart and job.get('restart_intent',{}).get('phase')!='controls_installed':
            raise Conflict('Installed restart controls required before arm publication')
        reservation=job['reservation']
        if (reservation['owner'],reservation['generation'])!=(actor,generation):
            raise Conflict('Reservation authority was revoked')
        attempt=job['launch_intent']['attempt_id']
        if not re.fullmatch(r'[0-9a-f]{64}',attempt):
            raise ValueError('Invalid launch attempt identity')
        issued=root/('issued-'+attempt+'.json')
        if any((root/(prefix+attempt+'.json')).exists() for prefix in
               ('issued-','consumed-','arm-intent-','start-intent-','result-')) or (root/'permit.json').exists():
            raise Conflict('Existing publication requires reconciliation, not retry')
        # Callback must inspect package, binary, fresh runtime and native owner
        # while this same lock excludes both controller commits and MQL dispatch.
        native=validate_native(state,job)
        if not isinstance(native,dict):
            raise ValueError('Native validator must return verified request fields')
        if restart:
            intent=job['restart_intent']
            if (intent['attempt_id']!=attempt or native.get('action')!='arm_restart'
                    or native.get('startup_sha256')!=intent['startup_sha256']
                    or native!=intent['arm_request_fields']):
                raise ValueError('Verified restart controls differ from installed attempt')
        elif native.get('action','start')!='start':
            raise ValueError('Open dispatch cannot publish a restart action')
        request=native | dict(schema_version=1,request_id=attempt,
            terminal_id=terminal_id,run_id=run_id,owner=actor,revision=revision,
            generation=generation,job_id=job_id,
            configuration_sha256=job['configuration_sha256'],
            expires_utc=int(time.time())+lifetime)
        body=json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n'
        digest=hashlib.sha256(body.encode('utf-8')).hexdigest()
        # An interruption after issuance is ambiguous even if permit is absent.
        # Keep the record immutable and never reissue the same attempt.
        with issued.open('x',encoding='utf-8') as handle:
            json.dump(dict(request_sha256=digest,request=request),handle,ensure_ascii=False)
            handle.flush();os.fsync(handle.fileno())
        write_json(bridge_root/'snapshot.json',dict(protocol_version=1,
            observed_at=datetime.now(timezone.utc).isoformat(),
            state=display_state(state),schema_hash=store.input_schema_hash,execution_ready=False))
        write_json(root/'request.json',request)
        if hashlib.sha256((root/'request.json').read_bytes()).hexdigest()!=digest:
            raise ValueError('Request serialization changed before publication')
        # Permit is the final write. A later controller transaction revokes it.
        write_json(root/'permit.json',dict(request_sha256=digest))
        return dict(request_id=attempt,request_sha256=digest,
            status='arm_published_not_confirmed' if restart else 'published_not_started')
