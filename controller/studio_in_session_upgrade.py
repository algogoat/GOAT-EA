"""Exact admitted EA switch for an already granted, idle Studio session.

The authenticated desktop supplies the candidate and its short-lived admission.
This transaction never edits a grant, research plan, queue, terminal permission or
Algo Trading setting. Its durable fence makes ordinary controller calls fail
closed across an interrupted EA/receipt exchange.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import time
import uuid

from campaign_ledger import packed, sha
from studio_bridge import write_json
from studio_build_upgrade import receipt_snapshot, replace_bytes, retain
from studio_handover import safe_path
from studio_installation import load_installation, read_json
from studio_installation_migration import (digest, pending_path, preflight,
    verify_installation_chain, validate_candidate, installation_recovery)
from studio_native_gate import exclusive_gate
from studio_seed_process import WindowsSeedProcess


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')


def _record(path, phase, **extra):
    value = read_json(path)
    value.update(phase=phase, **extra)
    write_json(path, value)
    return value


def _wait_absent(process, clock):
    deadline = clock.monotonic()+60
    while process.inspect() is not None:
        if clock.monotonic() >= deadline:
            raise ValueError('Selected MT5 normal close is unresolved; reconcile the same transaction ID')
        clock.sleep(.5)


def _live_epoch(root, session, expected, now):
    """Recheck the persisted real epoch on same-ID recovery, even after swap."""
    import sqlite3
    from contextlib import closing
    if (root/'continuation-revocation/revoked.json').exists():
        raise ValueError('Human takeover revoked the research epoch')
    binding = packed(dict(terminal_id=session['terminal_id'],run_id=session['run_id']))
    with closing(sqlite3.connect((root/'studio.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        state = db.execute('SELECT owner,generation FROM studio_state WHERE binding=?',(binding,)).fetchone()
        row = db.execute('SELECT provenance FROM studio_research_epochs WHERE binding=? AND generation=?',
            (binding,expected['generation'])).fetchone()
    if (state != ('agent',expected['generation']) or row is None or json.loads(row[0]) != expected
            or expected['account'] != session['account'] or not expected['created_utc'] <= now < expected['expires_utc']):
        raise ValueError('Genuine research owner, epoch or original expiry changed')


def _ensure_anchor(root, folder, record, receipt, binary):
    """Finish the exact archive anchor if power failed after its outer fence."""
    anchor=digest(folder/'migration.json')
    with sqlite3.connect(root/'studio.sqlite') as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS studio_build_migrations(sequence INTEGER PRIMARY KEY,record_sha256 TEXT NOT NULL)')
            rows=list(db.execute('SELECT sequence,record_sha256 FROM studio_build_migrations ORDER BY sequence'))
            if rows:
                if rows != [(1,anchor)]:raise ValueError('Existing migration anchor changed')
            else:
                if (digest(receipt)!=record['previous_receipt_sha256']
                        or digest(binary)!=record['previous_ea_sha256']):
                    raise ValueError('Unanchored upgrade changed installed EA or receipt')
                archive=read_json(folder/'archive.json')
                if sha(archive)!=record['archive_sha256'] or any(
                        digest(folder/name)!=file_sha for name,file_sha in archive.items()):
                    raise ValueError('Unanchored upgrade archive changed')
                if ((root/'session.json').read_bytes()!=(folder/'session.json').read_bytes()
                        or (root/'research-authority.json').read_bytes()!=
                        (folder/'research-authority.json').read_bytes()):
                    raise ValueError('Unanchored genuine grant archive changed')
                db.execute('INSERT INTO studio_build_migrations VALUES(1,?)',(anchor,))
            db.commit()
        except BaseException:
            db.rollback()
            raise


def _monitor_config(controller, folder):
    from studio_onboarding import saved_launch_policy, verify_monitor_profile
    from studio_driver_suspend import require_no_publishers
    saved_launch_policy(controller, controller.session)
    profile = read_json(controller.root/'monitor-profile.json')
    verify_monitor_profile(controller,profile)
    preset = safe_path(Path(controller.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set')
    expected_preset = ('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\n'
                       'Studio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n').encode('utf-16')
    if preset.read_bytes() != expected_preset:
        raise ValueError('Saved inert monitor preset changed')
    require_no_publishers(controller)
    config = safe_path(folder/'monitor.ini')
    raw = ('[Charts]\r\nProfileLast='+profile['profile_name']+'\r\n[Experts]\r\n'
           'Enabled=0\r\nAllowLiveTrading=0\r\n[StartUp]\r\nExpert='+
           controller.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+
           '\r\nPeriod=M1\r\n').encode('utf-16')
    retain(config,raw)
    return config,hashlib.sha256(raw).hexdigest()


def upgrade(receipt, transaction_id, candidate_receipt, candidate_ea, admission_path,
            expected_sha256, *, clock=time, process_factory=WindowsSeedProcess,
            native_probe=None):
    """Switch once; same-ID calls only reconcile retained exact bytes and phases.

    A crash after launch intent never launches twice. If process identity cannot
    be proven, the fence remains and a human/operator inspects the retained
    evidence before any later action.
    """
    if (not re.fullmatch('[a-f0-9]{32}',str(transaction_id))
            or not re.fullmatch('[a-f0-9]{64}',str(expected_sha256))):
        raise ValueError('Exact transaction ID and old receipt SHA-256 required')
    receipt = safe_path(receipt)
    if receipt.name != 'installation.json':
        raise ValueError('Registered installation.json required')
    root = safe_path(receipt.parent)
    pending = pending_path(root)
    directory = safe_path(root/'installation-migrations')
    stage=safe_path(pending.parent/transaction_id/'archive')
    final=safe_path(directory/'000001')
    candidate_receipt,candidate_ea,admission_path = [safe_path(item) for item in
        (candidate_receipt,candidate_ea,admission_path)]
    old_source = (final/'installation.before.json' if final.exists() else
                  stage/'installation.before.json') if pending.exists() else receipt
    old_raw,old = receipt_snapshot(safe_path(old_source))
    if hashlib.sha256(old_raw).hexdigest() != expected_sha256 or old.get('controller_state_root') != str(root):
        raise ValueError('Exact previous registered receipt changed')
    local = safe_path(Path(old['terminal_data_root'])/'MQL5/Files/GOATStudio')
    for source in (candidate_receipt,candidate_ea,admission_path):
        if source.is_relative_to(root) or source.is_relative_to(local):
            raise ValueError('Stage candidate and admission outside active state')
    new_raw,new = receipt_snapshot(candidate_receipt)
    ea_bytes = candidate_ea.read_bytes()
    checked = read_json(admission_path)
    expected = dict(transaction_id=transaction_id,previous_receipt_sha256=expected_sha256,
        candidate_receipt_sha256=hashlib.sha256(new_raw).hexdigest(),
        candidate_ea_sha256=hashlib.sha256(ea_bytes).hexdigest(),admission_sha256=sha(checked))
    relative=PureWindowsPath(old['ea_relative_path'])
    binary=safe_path(Path(old['terminal_data_root'])/'MQL5/Experts'/Path(*relative.parts))
    lock=safe_path(local.parent/'.studio-handover-lock')
    driver_gate=safe_path(root/'batch-driver-gate')
    lock.mkdir(parents=True,exist_ok=True)
    driver_gate.mkdir(exist_ok=True)
    with exclusive_gate(lock),exclusive_gate(driver_gate),installation_recovery(),ExitStack() as opened:
        from goat_studio import Controller
        retained = read_json(pending) if pending.exists() else None
        if retained is not None:
            if retained != expected:
                raise ValueError('Different in-session upgrade owns this fenced transaction')
            if not final.exists():
                if not stage.is_dir():raise ValueError('Fenced upgrade archive is missing')
                directory.mkdir(parents=True,exist_ok=True)
                os.replace(stage,final)
            folder=final
            record=read_json(folder/'migration.json')
            if (record['previous_receipt_sha256']!=expected_sha256
                    or record['candidate_receipt_sha256']!=expected['candidate_receipt_sha256']
                    or record['candidate_ea_sha256']!=expected['candidate_ea_sha256']
                    or record['admission_sha256']!=expected['admission_sha256']):
                raise ValueError('Retained upgrade differs from exact candidate')
            session=read_json(root/'session.json')
            _live_epoch(root,session,read_json(folder/'epoch.json'),clock.time())
            journal=safe_path(folder/'transaction.json')
            current=read_json(journal)
            if current.get('transaction_id')!=transaction_id:
                raise ValueError('Retained transaction identity changed')
            validate_candidate(old,new,ea_bytes,checked,session['account'],record['created_utc'])
            _ensure_anchor(root,folder,record,receipt,binary)
            verify_installation_chain(root,new,record['previous_installation_sha256'])
        else:
            if directory.exists() and any(directory.iterdir()):
                raise ValueError('Existing migration history requires an exact continuation review')
            if digest(receipt)!=expected_sha256 or digest(binary)!=old['ea_sha256']:
                raise ValueError('Installed EA/receipt compare-and-swap failed')
            if stage.exists():
                # This uncommitted copy predates the external fence and had no
                # native effect. Preserve it for diagnosis; fresh admission is
                # required to prepare a new exact archive.
                os.replace(stage,safe_path(stage.parent/('abandoned-'+uuid.uuid4().hex)))
            controller=opened.enter_context(_controller(Controller(receipt)))
            with exclusive_gate(local/'native-gate'):
                controller.open()
                proof=preflight(controller,candidate_receipt,candidate_ea,checked,
                    clock=clock.time,native_probe=native_probe,process=process_factory(controller))
                session=controller.session
                folder=stage
                folder.mkdir(parents=True,exist_ok=False)
                values={'session.json':session,
                    'research-authority.json':read_json(root/'research-authority.json'),
                    'epoch.json':proof['epoch'],'native-state.json':proof['native'],
                    'queue.json':proof['state']['queue'],'native-gate.json':proof['native_gate']}
                archive={}
                for name,value in values.items():
                    raw=(root/name).read_bytes() if name in ('session.json','research-authority.json') else _json_bytes(value)
                    retain(folder/name,raw)
                    archive[name]=hashlib.sha256(raw).hexdigest()
                for name,raw in (('installation.before.json',old_raw),
                                 ('ea.before.ex5',binary.read_bytes()),('ea.after.ex5',ea_bytes)):
                    retain(folder/name,raw)
                    archive[name]=hashlib.sha256(raw).hexdigest()
                retain(folder/'installation.after.json',new_raw)
                retain(folder/'admission.json',_json_bytes(checked))
                retain(folder/'archive.json',_json_bytes(archive))
                record=dict(schema_version=1,sequence=1,
                    previous_installation_sha256=sha(old),candidate_installation_sha256=sha(new),
                    previous_receipt_sha256=expected_sha256,
                    candidate_receipt_sha256=expected['candidate_receipt_sha256'],
                    previous_ea_sha256=old['ea_sha256'],candidate_ea_sha256=new['ea_sha256'],
                    epoch_sha256=sha(proof['epoch']),epoch_expires_utc=proof['epoch']['expires_utc'],
                    admission_sha256=sha(checked),bundle_manifest_sha256=proof['bundle_manifest_sha256'],
                    archive_sha256=sha(archive),created_utc=proof['created_utc'],
                    account=session['account'],plan_sha256=proof['epoch']['plan_sha256'])
                retain(folder/'migration.json',_json_bytes(record))
                pending.parent.mkdir(parents=True,exist_ok=True)
                write_json(pending,expected)
                journal=safe_path(folder/'transaction.json')
                write_json(journal,dict(transaction_id=transaction_id,phase='prepared'))
                directory.mkdir(parents=True,exist_ok=True)
                os.replace(stage,final)
                folder=final
                journal=safe_path(folder/'transaction.json')
                _ensure_anchor(root,folder,record,receipt,binary)
                current=read_json(journal)
        phase=current['phase']
        process=process_factory(controller if retained is None else _process_controller(old,root,local,session))
        if phase in ('prepared','close_issued','stopped','publication_intent'):
            with exclusive_gate(local/'native-gate'):
                if phase=='prepared':
                    controller=opened.enter_context(_controller(Controller(receipt))) if retained is not None else controller
                    controller.open(recovery=True) if retained is not None else None
                    proof=preflight(controller,candidate_receipt,candidate_ea,checked,
                        clock=clock.time,native_probe=native_probe,process=process,
                        admission_time=record['created_utc'])
                    if sha(proof['epoch'])!=record['epoch_sha256'] or proof['selected_process']!=read_json(folder/'native-state.json')['process']:
                        raise ValueError('Selected native process or genuine grant changed')
                    _record(journal,'close_issued')
                    process.close(proof['selected_process'])
                    phase='close_issued'
                if phase=='close_issued':
                    _wait_absent(process,clock)
                    _record(journal,'stopped')
                    phase='stopped'
                if phase in ('stopped','publication_intent'):
                    if process.inspect() is not None:
                        raise ValueError('Selected terminal reopened before build publication')
                    old_pair=(digest(receipt)==expected_sha256 and digest(binary)==old['ea_sha256'])
                    new_ea_old_receipt=(digest(receipt)==expected_sha256 and digest(binary)==new['ea_sha256'])
                    new_pair=(digest(receipt)==expected['candidate_receipt_sha256'] and digest(binary)==new['ea_sha256'])
                    if not (old_pair or new_ea_old_receipt or new_pair):
                        raise ValueError('Installed pair differs from retained exact bytes')
                    _live_epoch(root,session,read_json(folder/'epoch.json'),clock.time())
                    _record(journal,'publication_intent')
                    if old_pair:replace_bytes(binary,ea_bytes)
                    if not new_pair:replace_bytes(receipt,new_raw)
                    if digest(receipt)!=expected['candidate_receipt_sha256'] or load_installation(receipt)!=new:
                        raise ValueError('Published EA/receipt readback differs')
                    verify_installation_chain(root,new,record['previous_installation_sha256'])
                    _record(journal,'published')
                    phase='published'
        if phase in ('published','launch_issued','started_unverified'):
            controller=opened.enter_context(_controller(Controller(receipt)))
            controller.open(recovery=True)
            _live_epoch(root,session,read_json(folder/'epoch.json'),clock.time())
            if phase=='published':
                if process.inspect() is not None:
                    raise ValueError('Selected terminal reopened before controlled relaunch')
                config,config_sha=_monitor_config(controller,folder)
                _record(journal,'launch_issued',config_sha256=config_sha,launch_issued_utc=clock.time())
                selected=process_factory(controller).start(config)
                _record(journal,'started_unverified',process=selected)
                phase='started_unverified'
            if phase=='launch_issued':
                raise ValueError('Launch intent has uncertain process identity; preserve fence and inspect')
            selected=read_json(journal)['process']
            if process.inspect()!=selected:
                raise ValueError('Relaunched selected monitor identity changed')
            deadline=clock.monotonic()+30
            while True:
                try:
                    controller.runtime(require_idle=True,expected_batch_ongoing=False)
                    observation=safe_path(controller.local/'ui-observation.json')
                    if not observation.is_file() or observation.stat().st_mtime <= read_json(journal)['launch_issued_utc']:
                        raise ValueError('New monitor has not written a post-launch EA observation')
                    observed=(native_probe or __import__('studio_monitor_probe').inspect_idle_demo)(controller)
                    if observed.get('process')!=selected or any(observed.get(key)!=value for key,value in
                            dict(account_matches=True,demo=True,connected=True,algo_trading=False,
                                 positions=0,orders=0,tester_state='idle').items()):
                        raise ValueError('Relaunched EA is not the exact idle demo monitor')
                    from studio_research_authority import authority,operation
                    with operation('state'):
                        live=authority(controller.store.db,
                            packed(dict(terminal_id=controller.terminal,run_id=controller.run)),controller.state())
                    if sha(live)!=record['epoch_sha256']:
                        raise ValueError('Genuine grant changed after upgrade')
                    break
                except ValueError:
                    if clock.monotonic()>=deadline:raise
                    clock.sleep(1)
            _record(journal,'verified',readback=observed)
            phase='verified'
        if phase=='verified':
            controller=opened.enter_context(_controller(Controller(receipt)))
            controller.open(recovery=True)
            if process.inspect()!=read_json(journal)['process']:
                raise ValueError('Verified selected monitor changed before fence release')
            controller.runtime(require_idle=True,expected_batch_ongoing=False)
            _live_epoch(root,session,read_json(folder/'epoch.json'),clock.time())
            if pending.read_bytes()!=_json_bytes(expected):
                raise ValueError('Upgrade fence changed before completion')
            pending.unlink()
        else:
            raise ValueError('Unknown retained upgrade phase')
        return dict(status='verified',transaction_id=transaction_id,
            installation_sha256=record['candidate_installation_sha256'],
            epoch_expires_utc=record['epoch_expires_utc'],
            grant_created=False,plan_changed=False,trading_enabled=False)


def _process_controller(install,root,local,session):
    from types import SimpleNamespace
    return SimpleNamespace(install=install,root=root,local=local,session=session)


def _controller(controller):
    from contextlib import contextmanager
    @contextmanager
    def managed():
        try:yield controller
        finally:
            if controller.store:controller.store.close()
    return managed()
