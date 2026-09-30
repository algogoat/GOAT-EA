"""Retire an exact rejected, never-consumed demo attempt without replaying it.

The native request, permit, rejected receipts, authored configuration and queue
remain evidence. A local failed settlement is never a native cancellation claim.
The updater may subsequently reopen its verified inert monitor; this tool never
launches research, changes permissions or clears a human stop.
"""
from datetime import datetime, timezone
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from campaign_ledger import packed, sha
from native_control_transaction import NAMES, contents, digest, restore
from studio_bridge import write_json
from studio_derived_report_recovery import _no_human_pending, retain
from studio_dispatch_observe import observe_dispatch
from studio_driver_suspend import require_no_publishers
from studio_handover import safe_path
from studio_installation import load_installation, read_json
from studio_monitor_probe import inspect_idle_demo
from studio_native_gate import exclusive_gate
from studio_rejected_monitor import require_demo, unstarted_material
from studio_same_ea_rebind import ALLOWED_RECEIPT_DELTA, _beta, rebind
from studio_seed_process import WindowsSeedProcess
from studio_seed_slot import guard_active_seed


def original_receipt(receipt):
    """Read the exact same-EA predecessor; no session or native file effects."""
    receipt = safe_path(Path(receipt).absolute())
    current = load_installation(receipt)
    state = safe_path(Path(current['controller_state_root']))
    session = read_json(state/'session.json')
    if session['installation_sha256'] == sha(current):
        return receipt, current
    matches = []
    for path in safe_path(state/'ea-update-backups').glob('*/installation.json'):
        previous = load_installation(safe_path(path))
        if sha(previous) == session['installation_sha256']:
            matches.append((path, previous))
    if len(matches) != 1:
        raise ValueError('Exactly one preserved previous receipt must bind this session')
    path, previous = matches[0]
    if previous.get('receipt_path') != current.get('receipt_path'):
        raise ValueError('Registered receipt path changed')
    if current.get('receipt_path') and Path(current['receipt_path']).resolve() != receipt:
        raise ValueError('Registered receipt does not match the selected installation')
    if any(previous.get(k) != current.get(k) for k in set(previous)|set(current)
           if k not in ALLOWED_RECEIPT_DELTA):
        raise ValueError('Recovery refuses changed EA bytes, account binding or installation fields')
    old, new = _beta(previous.get('bundle_version')), _beta(current.get('bundle_version'))
    if old[:3] != new[:3] or new[3] <= old[3]:
        raise ValueError('Recovery requires a forward update on the same beta line')
    return path, current


def _guard(c):
    state = c.state()
    if c.session.get('demo_only') is not True or state['owner'] != 'agent':
        raise ValueError('Existing demo binding and current agent ownership required')
    # Restricted owner research and direct-demo adapters have separate recovery
    # contracts. Customer repair cannot turn either into a human grant.
    from studio_research_authority import authority
    binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
    if authority(c.store.db, binding, state) is not None:
        raise ValueError('Restricted research uses its existing recovery contract')
    for path in (c.root/'STOP', c.root/'demo-agent/STOP'):
        if path.exists():
            raise ValueError('Owner STOP is retained; no self-repair native action')
    _no_human_pending(c)
    require_no_publishers(c)
    guard_active_seed(c.root)
    for root in (c.root, Path(c.install['terminal_data_root']), Path(c.install['common_files_root'])):
        if shutil.disk_usage(root).free < 5*1024**3:
            raise ValueError('At least 5 GiB free disk is required')
    return state


def _proof(c, job):
    state = _guard(c)
    attempt = job['launch_intent']['attempt_id']
    gate = c.local/'native-gate'
    cancel = sha([attempt, 'cancel'])
    if any(gate.glob('start-intent-*.json')) or any(gate.glob('arm-intent-*.json')):
        raise ValueError('Native start or arm intent exists; execution outcome is uncertain')
    dispatch = observe_dispatch(gate, cancel)
    current = read_json(safe_path(gate/'request.json'))
    issued = read_json(safe_path(gate/('issued-'+cancel+'.json')))
    request = issued['request']
    if (dispatch.get('consumed') is not False or dispatch.get('status') != 'receipt_observed'
            or dispatch['receipt']['status'] != 'REQUEST_REJECTED' or current != request
            or request.get('request_id') != cancel or request.get('attempt_id') != attempt
            or request.get('action') != 'cancel' or request.get('job_id') != job['job_id']
            or request.get('terminal_id') != c.terminal or request.get('run_id') != c.run
            or request.get('generation') != state['generation']
            or request.get('configuration_sha256') != job['configuration_sha256']
            or request.get('expires_utc', time.time()+1) >= time.time()):
        raise ValueError('Exact expired pre-consumption native cancel rejection required')
    permit = safe_path(gate/'permit.json')
    if permit.exists() and read_json(permit) != {'request_sha256': issued['request_sha256']}:
        raise ValueError('Permit differs from the retained original cancel')
    # Causal zero-work proof includes rejected original start, unarmed activation,
    # byte-exact native queue/input/control files and no local reports/tester cache.
    recorded = datetime.fromisoformat(job['launch_intent']['recorded_at']).timestamp()
    scope = dict(configuration_sha256=job['configuration_sha256'], generation=state['generation'],
                 binding=dict(terminal_id=c.terminal, run_id=c.run), created_utc=recorded)
    unstarted_material(c, job, scope)
    evidence = safe_path(c.root/'attempts'/attempt)
    transaction = read_json(evidence/'transaction.json')
    base = safe_path(Path(transaction['base']))
    expected_base = safe_path(Path(c.install['common_files_root'])/'GOAT'/
                             ('GOAT V'+c.install['ea_version']+'-'+c.session['account']['server']))
    if (base != expected_base or transaction['owner'] != attempt or transaction['phase'] != 'installed'
            or read_json(base/'agent-native-control-owner.json') != dict(owner=attempt, evidence=str(evidence))
            or any(transaction['files'][n]['before'] is not None for n in NAMES)
            or any(digest(contents(base/n)) != transaction['files'][n]['after_sha256'] for n in NAMES)):
        raise ValueError('Exact untouched owned controls with absent original controls required')
    fields = dict(owner='agent', data_path=c.install['terminal_data_root'],
                  installation_path=str(Path(c.install['terminal_executable']).parent),
                  account_login=c.session['account']['login'], account_server=c.session['account']['server'],
                  native_run=read_json(Path(job['launch_intent']['package'])/'manifest.json')['native_run_relative'],
                  pointer_sha256=digest((base/'active_optimization_run.ini').read_bytes()),
                  native_owner_sha256=digest((base/'agent-native-control-owner.json').read_bytes()))
    start = read_json(gate/('issued-'+attempt+'.json'))['request']
    if any(start.get(k) != v or request.get(k) != v for k,v in fields.items()):
        raise ValueError('Original start/cancel terminal, account or native-control identity differs')
    return transaction


def _append(path, phase, **fields):
    with path.open('a', encoding='utf-8', newline='\n') as output:
        output.write(packed(dict(at=datetime.now(timezone.utc).isoformat(), phase=phase, **fields))+'\n')
        output.flush(); os.fsync(output.fileno())


def _record_guard(c, record):
    state = _guard(c)
    if state['owner'] != record['state']['owner'] or state['generation'] != record['state']['generation']:
        raise ValueError('Human ownership generation changed during repair')
    job = c.job(record['job_id'])
    expected = record['state']['revision'] + (1 if job.get('completion',{}).get('repair_action_id') == record['action_id'] else 0)
    if state['revision'] != expected:
        raise ValueError('Controller revision changed outside this repair')
    return state


def _repair(receipt, job_id, action_id, *, linked_login, process=None, clock=time, controller=None):
    """Return a support-safe repair record plus local evidence, without networking."""
    if str(uuid.UUID(action_id)) != action_id:
        raise ValueError('Canonical UUID action ID required for replay-safe reporting')
    if not isinstance(linked_login,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',linked_login):
        raise ValueError('Exact full caller-linked login required')
    owned_controller = controller is None
    if owned_controller:
        from goat_studio import Controller
        previous, current = original_receipt(receipt)
        session = read_json(Path(current['controller_state_root'])/'session.json')
        if session.get('account',{}).get('login') != linked_login:
            raise ValueError('Caller-linked login differs from retained installation account')
        c = Controller(previous).open()
    else:
        c = controller
        current = c.install
        if c.session.get('account',{}).get('login') != linked_login:
            raise ValueError('Caller-linked login differs from retained installation account')
    process = process or WindowsSeedProcess(c)
    folder = safe_path(c.root/'self-repair'/action_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'transaction.json'
    native_action = False
    locks = ExitStack()
    try:
        if path.exists() and read_json(path).get('phase') == 'complete':
            saved = read_json(path)
            if saved['job_id'] != job_id or saved['installation_sha256'] != sha(current):
                raise ValueError('Repair action ID belongs to different work')
            if digest((folder/'outcome.json').read_bytes()) != saved.get('outcome_sha256'):
                raise ValueError('Retained repair outcome changed')
            return read_json(folder/'outcome.json')
        # Own the selected demo operation lock used by update/start as well as
        # the handover gate. Rebind later takes the exclusive handover lock, so
        # release this shared hold before that metadata-only call.
        from demo_agent import DemoAgent
        locks.enter_context(DemoAgent(receipt)._exclusive())
        from studio_handover import session_lock
        locks.enter_context(session_lock(c))
        (c.root/'batch-driver-gate').mkdir(exist_ok=True)
        _guard(c)
        if not path.exists():
            native = inspect_idle_demo(c); require_demo(native)
            if process.inspect() != native['process']:
                raise ValueError('Selected native process changed')
            # Republish genuine ledger owner/revision and frozen editor settings.
            # No default drafts, control grant or native command is invented.
            c.bridge.pump()
            # The repaired projection can let the existing EA reject its old
            # expired transport on its next timer. Observe only those issued
            # identities; do not resend the cancel or renew its permit.
            pending = c.job(job_id)
            if 'launch_intent' in pending:
                attempt = pending['launch_intent']['attempt_id']
                gate = c.local/'native-gate'
                issued_stop = gate/('issued-'+sha([attempt,'cancel'])+'.json')
                if issued_stop.exists() and read_json(issued_stop)['request'].get('expires_utc',clock.time()+1) < clock.time():
                    deadline = clock.monotonic()+15
                    while any(observe_dispatch(gate,identity).get('status') == 'awaiting_receipt'
                              for identity in (attempt,sha([attempt,'cancel']))):
                        _guard(c)
                        if clock.monotonic() >= deadline: break
                        clock.sleep(.2)
        with exclusive_gate(c.root/'batch-driver-gate'), exclusive_gate(c.local/'native-gate'):
            state = _guard(c)
            job = c.job(job_id)
            if len(state['queue']) != 1 or 'launch_intent' not in job:
                raise ValueError('Exactly one retained original attempt required')
            evidence = safe_path(c.root/'attempts'/job['launch_intent']['attempt_id'])
            gate = c.local/'native-gate'
            if not path.exists():
                transaction = _proof(c, job)
                native = inspect_idle_demo(c); require_demo(native)
                if process.inspect() != native['process']:
                    raise ValueError('Selected native process changed before recovery')
                files = {'job-before.json': (packed(job)+'\n').encode(),
                         'session-before.json': (c.root/'session.json').read_bytes(),
                         'transaction-before.json': (evidence/'transaction.json').read_bytes(),
                         'request-before.json': (gate/'request.json').read_bytes()}
                if (gate/'permit.json').exists(): files['permit-before.json'] = (gate/'permit.json').read_bytes()
                for name, raw in files.items(): retain(folder/name, raw)
                record = dict(schema_version=1, phase='prepared', job_id=job_id,
                              action_id=action_id, installation_sha256=sha(current), original_installation_sha256=sha(c.install),
                              state={k:state[k] for k in ('owner','generation','revision')},
                              process=native['process'], attempt_id=job['launch_intent']['attempt_id'],
                              account_proof=dict(login=linked_login,server=c.session['account']['server'],
                                                 demo=True,observed_at=datetime.now(timezone.utc).isoformat(),
                                                 process=native['process']),
                              archive_sha256={n:digest(raw) for n,raw in files.items()},
                              native_cancellation_claimed=False, grant_created=False, research_started=False)
                write_json(path, record)
                _append(folder/'actions.jsonl', 'prepared', attempt_id=record['attempt_id'])
            record = read_json(path)
            if record.get('phase') not in ('prepared','close_issued','stopped','controls_restored','settled'):
                raise ValueError('Unknown repair phase; preserve uncertain effects')
            if (record['job_id'] != job_id or record['installation_sha256'] != sha(current)
                    or (record['original_installation_sha256'] != sha(c.install)
                        and not (record['phase'] == 'settled' and record['installation_sha256'] == sha(c.install)))
                    or any(digest(safe_path(folder/n).read_bytes()) != h for n,h in record['archive_sha256'].items())):
                raise ValueError('Retained repair evidence changed')
            before = read_json(folder/'job-before.json')
            _record_guard(c, record)
            session_digest = digest((c.root/'session.json').read_bytes())
            if (session_digest != record['archive_sha256']['session-before.json']
                    and not (record['phase'] == 'settled' and read_json(c.root/'session.json')['installation_sha256'] == sha(current))):
                raise ValueError('Controller session changed during repair')
            if record['phase'] == 'prepared':
                if job != before or {k:state[k] for k in record['state']} != record['state']:
                    raise ValueError('Controller changed before close')
                _proof(c, job)
                native = inspect_idle_demo(c); require_demo(native)
                if native['process'] != record['process'] or process.inspect() != record['process']:
                    raise ValueError('Native process changed before close')
                record['phase'] = 'close_issued'; write_json(path, record)
                native_action = True
                _append(folder/'actions.jsonl', 'close_issued', attempt_id=record['attempt_id'])
                process.close(record['process'])
            native_action = True
            if record['phase'] == 'close_issued':
                deadline = clock.monotonic()+150
                while process.inspect() is not None:
                    if process.inspect() != record['process'] or clock.monotonic() >= deadline:
                        raise ValueError('Repair close remains uncertain; no repeated close')
                    clock.sleep(.2)
                record['phase'] = 'stopped'; write_json(path, record)
            if process.inspect() is not None:
                raise ValueError('Selected terminal reappeared during stopped recovery')
            if record['phase'] == 'stopped':
                _record_guard(c, record)
                if c.job(job_id) != before:
                    raise ValueError('Job changed during stopped recovery')
                # Normal MT5 shutdown is not zero-work proof. Recheck the
                # complete causal evidence after exit before any restoration.
                if read_json(evidence/'transaction.json')['phase'] == 'installed':
                    _proof(c, job)
                for identity in (record['attempt_id'], sha([record['attempt_id'],'cancel'])):
                    if observe_dispatch(gate, identity).get('consumed') is not False:
                        raise ValueError('Native action was consumed; preserve unresolved evidence')
                for name in ('request.json','permit.json'):
                    target = safe_path(gate/name)
                    archived = 'request-before.json' if name == 'request.json' else 'permit-before.json'
                    if target.exists() and digest(target.read_bytes()) != record['archive_sha256'].get(archived):
                        raise ValueError('New native transport appeared during recovery')
                tx = read_json(evidence/'transaction.json'); prior = read_json(folder/'transaction-before.json')
                if {k:v for k,v in tx.items() if k != 'phase'} != {k:v for k,v in prior.items() if k != 'phase'}:
                    raise ValueError('Control transaction changed')
                base = safe_path(Path(tx['base']))
                observed = {n:digest(contents(base/n)) for n in NAMES}
                if any(observed[n] not in (prior['files'][n]['before_sha256'],prior['files'][n]['after_sha256']) for n in NAMES):
                    raise ValueError('New native controls refuse restoration')
                if tx['phase'] != 'restored': restore(evidence, observed)
                if any(digest(contents(base/n)) != prior['files'][n]['before_sha256'] for n in NAMES):
                    raise ValueError('Restored controls differ from original bytes')
                for name in ('request.json','permit.json'): (gate/name).unlink(missing_ok=True)
                record['phase'] = 'controls_restored'; write_json(path, record)
            result = dict(schema_version=1, status='failed', classification='retired_never_started',
                          job_id=job_id, attempt_id=record['attempt_id'], configuration=before['configuration'],
                          configuration_sha256=before['configuration_sha256'],
                          package_sha256=before['launch_intent']['package_sha256'], reports=None,
                          executed_members=0, native_cancellation_claimed=False, repair_action_id=action_id)
            result_path = evidence/'result.json'
            if result_path.exists() and read_json(result_path) != result:
                raise ValueError('Another attempt completion exists')
            write_json(result_path, result)
            # Already holding the native gate; Store.transaction would acquire
            # the non-reentrant file gate a second time.
            c.store.db.execute('BEGIN IMMEDIATE')
            try:
                state = _record_guard(c, record); current_job = c.job(job_id)
                if current_job == before:
                    current_job.update(status='failed', completion=result, completion_path=str(result_path))
                    jobs = [current_job]
                    binding = packed(dict(terminal_id=c.terminal,run_id=c.run))
                    c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',(packed(jobs),binding))
                    c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?',(binding,))
                elif current_job.get('completion') != result:
                    raise ValueError('Controller completion changed')
                c.store.db.execute('COMMIT')
            except BaseException:
                c.store.db.execute('ROLLBACK'); raise
            record['phase'] = 'settled'; write_json(path, record)
        # Rebind acquires the same native gate itself; never nest the file lock.
        locks.close()
        if sha(c.install) != sha(current): rebind(receipt, process=process)
        changes = [dict(target='attempt/result.json',action='created',beforeSha256=None,afterSha256=digest(result_path.read_bytes()))]
        previous_controls = read_json(folder/'transaction-before.json')
        changes += [dict(target='native-controls/'+name,action='removed',
                         beforeSha256=previous_controls['files'][name]['after_sha256'],afterSha256=None) for name in NAMES]
        for name in ('request-before.json','permit-before.json'):
            if name in record['archive_sha256']:
                h = record['archive_sha256'][name]
                changes += [dict(target='native-gate/'+name.replace('-before',''),action='removed',beforeSha256=h,afterSha256=None),
                            dict(target='self-repair/'+name,action='created',beforeSha256=None,afterSha256=h)]
        after_session = digest((c.root/'session.json').read_bytes())
        if after_session != record['archive_sha256']['session-before.json']:
            changes.append(dict(target='controller/session.json',action='rewrote',
                                beforeSha256=record['archive_sha256']['session-before.json'],afterSha256=after_session))
        report = dict(schemaVersion=1,tool='studio.self-repair',
                      versions=dict(app=current.get('bundle_version'),ea=current['ea_version'],controller=current['controller_version']),
                      outcome='repaired',summary='Retired a verified rejected, never-started demo attempt and restored its original controls. The verified monitor can reopen; no research or trading was started.',
                      observed=[dict(name='attempt',value=record['attempt_id'])],
                      before=[dict(name='phase',value=before['status'])],after=[dict(name='phase',value='retired_never_started')],
                      changes=changes,nativeAction=True)
        outcome = dict(status='repaired_terminal_stopped',action_id=action_id,repair=report,
                       report_action_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'goat-self-repair:'+action_id+':'+sha(report))),
                       account_proof=record['account_proof'],
                       native_cancellation_claimed=False,research_started=False,native_qualification=False,
                       next_action='Update may reopen the verified inert monitor. Existing research stop remains retained; never auto-resume the retired attempt.')
        write_json(folder/'outcome.json',outcome)
        record.update(phase='complete',outcome_sha256=digest((folder/'outcome.json').read_bytes())); write_json(path, record)
        _append(folder/'actions.jsonl','complete',attempt_id=record['attempt_id'])
        return outcome
    finally:
        locks.close()
        if owned_controller and c.store: c.store.close()


def repair(receipt, job_id, action_id, **kwargs):
    """Do not copy exception text, machine paths or account IDs into support."""
    try:
        return _repair(receipt, job_id, action_id, **kwargs)
    except (OSError, ValueError, KeyError, TypeError) as error:
        current = {}
        native_action = False
        try:
            current = load_installation(receipt)
            folder = safe_path(Path(current['controller_state_root'])/'self-repair'/str(uuid.UUID(action_id)))
            journal = folder/'transaction.json'
            if journal.exists(): native_action = read_json(journal).get('phase') not in ('prepared',)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        report = dict(schemaVersion=1,tool='studio.self-repair',
                      versions=dict(app=current.get('bundle_version','unknown'),ea=current.get('ea_version','unknown'),controller=current.get('controller_version')),
                      outcome='failed' if native_action else 'refused',
                      summary='Automatic recovery retained the original evidence because a required demo, ownership or never-started proof is unavailable. No request was replayed and no human stop was cleared.',
                      observed=[],before=[],after=[],changes=[],nativeAction=native_action)
        # The local-only reason is useful to the caller; report is the sole
        # network payload. Report plumbing must never serialize this envelope.
        return dict(status=report['outcome'],action_id=action_id,repair=report,
                    report_action_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'goat-self-repair:'+str(action_id)+':'+sha(report))),
                    local_reason=str(error),native_qualification=False,research_started=False,
                    next_action='Retain the exact original action ID and evidence; inspect the local reason before retrying this repair. Never replay the old research start.')
