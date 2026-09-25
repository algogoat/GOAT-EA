"""Explicit cancel publication; never treats a request as confirmed stop."""
import hashlib
import json
from pathlib import Path
import time
from campaign_ledger import sha
from studio_bridge import write_json,display_state
from studio_native_gate import exclusive_gate
from studio_dispatch_observe import observe_dispatch

def publish_cancel(controller, job):
    if job['status'] not in ('starting','running','reconcile_required','verifying'):
        raise ValueError('An existing native attempt is required')
    attempt=job['launch_intent']['attempt_id'];request_id=sha([attempt,'cancel'])
    gate=controller.local/'native-gate'
    with exclusive_gate(gate):
        state=controller.state();current=controller.job(job['job_id'])
        if state['owner']!='agent' or current['launch_intent']['attempt_id']!=attempt:
            raise ValueError('Current agent ownership and exact attempt required')
        if (gate/('issued-'+request_id+'.json')).exists():
            return dict(request_id=request_id,dispatch=observe_dispatch(gate,request_id),stopped=False)
        manifest=json.loads((Path(job['launch_intent']['package'])/'manifest.json').read_text())
        base=Path(controller.install['common_files_root'])/'GOAT'/('GOAT V'+controller.install['ea_version']+'-'+controller.session['account']['server'])
        owner=json.loads((base/'agent-native-control-owner.json').read_text())
        if owner['owner']!=attempt: raise ValueError('Native controls belong to another attempt')
        request=dict(schema_version=1,action='cancel',request_id=request_id,attempt_id=attempt,
            terminal_id=controller.terminal,run_id=controller.run,owner='agent',revision=state['revision'],generation=state['generation'],
            job_id=job['job_id'],configuration_sha256=job['configuration_sha256'],expires_utc=int(time.time())+120,
            data_path=controller.install['terminal_data_root'],installation_path=str(Path(controller.install['terminal_executable']).parent),
            account_login=controller.session['account']['login'],account_server=controller.session['account']['server'],
            native_run=manifest['native_run_relative'],native_owner_sha256=hashlib.sha256((base/'agent-native-control-owner.json').read_bytes()).hexdigest(),
            pointer_sha256=hashlib.sha256((base/'active_optimization_run.ini').read_bytes()).hexdigest())
        digest=hashlib.sha256((json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n').encode()).hexdigest()
        write_json(gate/('issued-'+request_id+'.json'),dict(request=request,request_sha256=digest))
        write_json(controller.bridge.root/'snapshot.json',dict(protocol_version=1,state=display_state(state),schema_hash=controller.store.input_schema_hash,execution_ready=False))
        # Revokes an unconsumed start permit and replaces it with an owned stop.
        (gate/'permit.json').unlink(missing_ok=True)
        write_json(gate/'request.json',request)
        write_json(gate/'permit.json',dict(request_sha256=digest))
        return dict(request_id=request_id,status='cancel_published_not_confirmed',stopped=False,next_action='Run status, then finish only after native cancellation and idle are confirmed')
