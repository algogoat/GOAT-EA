"""Verify an append-only, same-session EA build migration chain.

The original session and research authority are never relabelled. Every later
installed build must be linked by a retained exact admission and a second
digest in the controller database. This module verifies history; it never
creates or extends a grant.
"""
from contextlib import closing, contextmanager
from contextvars import ContextVar
import hashlib
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import time

from campaign_ledger import sha
from studio_handover import safe_path
from studio_installation import read_json


_RECOVERING_INSTALLATION = ContextVar('recovering_in_session_installation', default=False)


@contextmanager
def installation_recovery():
    """Allow the fenced writer to read the original receipt before publication."""
    token = _RECOVERING_INSTALLATION.set(True)
    try:
        yield
    finally:
        _RECOVERING_INSTALLATION.reset(token)


def preflight(controller, candidate_receipt, candidate_ea, checked, *, clock=time.time,
              native_probe=None, process=None, admission_time=None):
    """Verify a live, genuinely granted idle demo before an in-session switch.

    Caller must hold the exclusive session, batch-driver and native gates. No
    file or native state is changed here; the transaction rechecks the evidence
    immediately before its first effect.
    """
    from studio_build_upgrade import receipt_snapshot
    from studio_native_gate import assert_clear_controls
    from studio_research_authority import authority, operation
    from studio_seed_slot import guard_active_seed
    from studio_monitor_probe import inspect_idle_demo
    from studio_seed_process import WindowsSeedProcess
    from studio_driver_suspend import require_no_publishers
    from campaign_ledger import packed

    root = safe_path(controller.root)
    local = safe_path(controller.local)
    sources = [safe_path(candidate_receipt), safe_path(candidate_ea)]
    if any(source.is_relative_to(root) or source.is_relative_to(local) for source in sources):
        raise ValueError('Stage candidate outside controller and selected terminal state')
    raw, desired = receipt_snapshot(sources[0])
    ea_bytes = sources[1].read_bytes()
    with operation('state'):
        state = controller.state()
    if state['owner'] != 'agent' or any(job['status'] not in
            ('completed','cancelled','failed','removed') for job in state['queue']):
        raise ValueError('A genuine agent owner with no pending native job is required')
    guard_active_seed(root)
    require_no_publishers(controller)
    for journal in (root/'batch-drivers').glob('*.json'):
        record = read_json(safe_path(journal))
        if record.get('stopped') is not True:
            raise ValueError('A batch driver remains active or uncertain')
    with operation('state'):
        epoch = authority(controller.store.db,
            packed(dict(terminal_id=controller.terminal,run_id=controller.run)),state)
    now = clock()
    if (not isinstance(epoch,dict) or not isinstance(epoch.get('renewal'),dict)
            or epoch.get('generation') != state['generation']
            or epoch.get('account') != controller.session['account']
            or not epoch.get('created_utc',0) <= now < epoch.get('expires_utc',0)):
        raise ValueError('Live genuine renewed research epoch required')
    admission = validate_candidate(controller.install,desired,ea_bytes,checked,
        controller.session['account'],now if admission_time is None else admission_time)
    relative = PureWindowsPath(controller.install['ea_relative_path'])
    binary = safe_path(Path(controller.install['terminal_data_root'])/'MQL5/Experts'/Path(*relative.parts))
    if digest(binary) != controller.install['ea_sha256']:
        raise ValueError('Installed EA changed before in-session upgrade')
    gate = assert_clear_controls(controller.store.db,local/'native-gate')
    controller.runtime(require_idle=True,expected_batch_ongoing=False)
    native = (native_probe or inspect_idle_demo)(controller)
    if (native.get('account_matches') is not True or native.get('demo') is not True
            or native.get('connected') is not True or native.get('algo_trading') is not False
            or native.get('positions') != 0 or native.get('orders') != 0
            or native.get('tester_state') != 'idle'):
        raise ValueError('Upgrade requires idle connected demo, Algo OFF and zero orders/positions')
    selected = (process or WindowsSeedProcess(controller)).inspect()
    if selected is None or selected != native.get('process'):
        raise ValueError('Selected idle native monitor identity changed')
    return dict(previous=controller.install,candidate=desired,receipt_bytes=raw,ea_bytes=ea_bytes,
        epoch=epoch,account=controller.session['account'],state=state,native=native,
        selected_process=selected,native_gate=gate,created_utc=now,**admission)


def digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def pending_path(root):
    root = safe_path(root)
    return safe_path(root.parent/'.in-session-ea-upgrades'/root.name/'pending.json')


def guard_pending(root):
    pending = pending_path(root)
    if pending.exists():
        raise ValueError('In-session EA upgrade is unfinished; reconcile its exact transaction ID')


def validate_candidate(old, new, ea_bytes, checked, account, now):
    """Reject an unadmitted or identity-changing EA before any native effect."""
    mutable = {'bundle_version','ea_sha256','agent_guide_path','installed_at'}
    if (not isinstance(old,dict) or not isinstance(new,dict)
            or set(old) != set(new)
            or any(old[key] != new[key] for key in set(old)-mutable)
            or old.get('ea_version') != '1.49'
            or new.get('ea_sha256') == old.get('ea_sha256')
            or not isinstance(ea_bytes,bytes) or not ea_bytes or len(ea_bytes) > 100_000_000
            or hashlib.sha256(ea_bytes).hexdigest() != new.get('ea_sha256')):
        raise ValueError('Candidate changes installation identity or reviewed EA bytes')
    if not isinstance(checked,dict) or set(checked) != {'input','admission','identity'}:
        raise ValueError('Authenticated internal qualification required')
    request, admission, identity = checked['input'], checked['admission'], checked['identity']
    if not all(isinstance(value,dict) for value in (request,admission,identity)):
        raise ValueError('Malformed internal qualification evidence')
    if (not isinstance(account,dict) or not isinstance(now,(int,float))
            or not 0 < now < 4_000_000_000
            or not isinstance(request.get('selection'),dict)):
        raise ValueError('Malformed internal qualification account or time')
    when = now*1000
    if (
            admission.get('mode') != 'INTERNAL_REVIEWED'
            or admission.get('grantsControl') is not False
            or admission.get('accountId') != account.get('login')
            or request.get('accountId') != account.get('login')
            or request.get('buildId') != admission.get('buildId')
            or not isinstance(admission.get('uid'),str) or not admission['uid']
            or admission.get('artifactSha256') != new['ea_sha256']
            or identity.get('eaSha256') != new['ea_sha256']
            or identity.get('eaVersion') != new['ea_version']
            or identity.get('controllerVersion') != new['controller_version']
            or admission.get('sourceCommit') != identity.get('eaSourceRevision')
            or not re.fullmatch('[a-f0-9]{40}',str(identity.get('eaSourceRevision','')))
            or not re.fullmatch('[a-f0-9]{64}',str(admission.get('compileReceiptSha256','')))
            or not re.fullmatch('[a-f0-9]{64}',str(admission.get('admissionSha256','')))
            or not re.fullmatch('[a-f0-9]{64}',str(identity.get('manifestSha256','')))
            or request.get('selection',{}).get('terminalExecutable') != new['terminal_executable']
            or request.get('selection',{}).get('terminalDataRoot') != new['terminal_data_root']
            or request.get('selection',{}).get('portable') != new.get('terminal_portable',
                Path(new['terminal_data_root']) == Path(new['terminal_executable']).parent)
            or not isinstance(admission.get('checkedAtMs'),(int,float))
            or not isinstance(admission.get('validUntilMs'),(int,float))
            or not isinstance(admission.get('notBeforeMs'),(int,float))
            or type(admission.get('persistent')) is not bool
            or not admission['checkedAtMs'] < admission['validUntilMs'] <= admission['checkedAtMs'] + 30_000
            or not admission['checkedAtMs'] <= when < admission['validUntilMs']
            or when - admission['checkedAtMs'] > 30_000
            or when < admission['notBeforeMs']
            or (not admission.get('persistent',False) and admission.get('expiresAtMs') is not None
                and (not isinstance(admission['expiresAtMs'],(int,float))
                    or when >= admission['expiresAtMs']))):
        raise ValueError('Fresh exact own-account EA admission differs from candidate')
    return dict(admission_sha256=sha(checked),bundle_manifest_sha256=identity['manifestSha256'])


def verify_installation_chain(root, current, original_sha256):
    """Return only after current bytes follow the immutable session install."""
    root = safe_path(root)
    directory = safe_path(root/'installation-migrations')
    database = safe_path(root/'studio.sqlite')
    if not directory.is_dir() and sha(current) == original_sha256:
        return dict(migrations=0, installation_sha256=original_sha256)
    if not directory.is_dir() or not database.is_file():
        raise ValueError('Installation changed since bootstrap; no migration chain')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_build_migrations'").fetchone() is None:
            raise ValueError('Installation migration anchor is missing')
        anchors = list(db.execute('SELECT sequence,record_sha256 FROM studio_build_migrations ORDER BY sequence'))
        if not anchors or len(anchors) > 32 or [row[0] for row in anchors] != list(range(1,len(anchors)+1)):
            raise ValueError('Installation migration sequence is incomplete')
        expected = original_sha256
        for sequence, anchor in anchors:
            if not isinstance(anchor,str) or not re.fullmatch('[a-f0-9]{64}',anchor):
                raise ValueError('Malformed installation migration anchor')
            name = f'{sequence:06d}'
            folder = safe_path(directory/name)
            path = safe_path(folder/'migration.json')
            if digest(path) != anchor:
                raise ValueError('Installation migration receipt changed')
            record = read_json(path)
            if (set(record) != {'schema_version','sequence','previous_installation_sha256',
                    'candidate_installation_sha256','previous_receipt_sha256','candidate_receipt_sha256',
                    'previous_ea_sha256','candidate_ea_sha256','epoch_sha256','epoch_expires_utc',
                    'admission_sha256','bundle_manifest_sha256','archive_sha256','created_utc','account','plan_sha256'}
                    or record['schema_version'] != 1 or record['sequence'] != sequence
                    or record['previous_installation_sha256'] != expected):
                raise ValueError('Installation migration chain differs from original session')
            old = read_json(safe_path(folder/'installation.before.json'))
            new = read_json(safe_path(folder/'installation.after.json'))
            if (sha(old) != expected or sha(new) != record['candidate_installation_sha256']
                    or digest(folder/'installation.before.json') != record['previous_receipt_sha256']
                    or digest(folder/'installation.after.json') != record['candidate_receipt_sha256']
                    or old['ea_sha256'] != record['previous_ea_sha256']
                    or new['ea_sha256'] != record['candidate_ea_sha256']):
                raise ValueError('Installation migration bytes or build identity changed')
            mutable = {'bundle_version','ea_sha256','agent_guide_path','installed_at'}
            if set(old) != set(new) or any(old[key] != new[key] for key in set(old)-mutable):
                raise ValueError('Installation migration changed account, terminal or catalog')
            checked = read_json(safe_path(folder/'admission.json'))
            identity = validate_candidate(old,new,safe_path(folder/'ea.after.ex5').read_bytes(),
                checked,record['account'],record['created_utc'])
            if (identity['admission_sha256'] != record['admission_sha256']
                    or identity['bundle_manifest_sha256'] != record['bundle_manifest_sha256']):
                raise ValueError('Exact reviewed build admission changed')
            archive = read_json(safe_path(folder/'archive.json'))
            required_archive = {'session.json','research-authority.json','epoch.json',
                'installation.before.json','ea.before.ex5','ea.after.ex5','native-state.json',
                'queue.json','native-gate.json'}
            if (not isinstance(archive,dict) or sha(archive) != record['archive_sha256']
                    or not required_archive <= set(archive)):
                raise ValueError('Migration archive manifest changed')
            for relative, file_sha in archive.items():
                if (not isinstance(relative,str) or not relative or '/' in relative or '\\' in relative
                        or relative in ('.','..') or not re.fullmatch('[a-f0-9]{64}',file_sha)
                        or digest(folder/relative) != file_sha):
                    raise ValueError('Archived session, queue or native evidence changed')
            if digest(folder/'ea.before.ex5') != old['ea_sha256']:
                raise ValueError('Previous EA binary archive changed')
            archived_session = read_json(safe_path(folder/'session.json'))
            archived_authority = read_json(safe_path(folder/'research-authority.json'))
            if (archived_session.get('installation_sha256') != original_sha256
                    or archived_session.get('authority_sha256') != sha(archived_authority)
                    or archived_session.get('account') != record['account']
                    or archived_authority.get('plan_sha256') != record['plan_sha256']):
                raise ValueError('Original session or frozen research authority changed')
            epoch = read_json(safe_path(folder/'epoch.json'))
            if (sha(epoch) != record['epoch_sha256'] or epoch['expires_utc'] != record['epoch_expires_utc']
                    or epoch['account'] != record['account'] or epoch['plan_sha256'] != record['plan_sha256']
                    or epoch['installation_sha256'] != original_sha256
                    or record['created_utc'] >= epoch['expires_utc']):
                raise ValueError('Migration changed genuine epoch, plan or expiry')
            expected = record['candidate_installation_sha256']
        if expected != sha(current):
            # The append-only anchor is committed before the normal MT5 close.
            # Only this writer, with its matching external fence and unfinished
            # phase, may inspect the still-original receipt during that gap.
            if (not _RECOVERING_INSTALLATION.get() or len(anchors) != 1
                    or sha(current) != original_sha256):
                raise ValueError('Installed build is not the end of the migration chain')
            pending = pending_path(root)
            journal = directory/'000001'/'transaction.json'
            if not pending.is_file() or not journal.is_file():
                raise ValueError('Installation migration recovery fence is missing')
            fence = read_json(pending)
            transaction = read_json(journal)
            if (transaction.get('phase') not in
                    ('prepared','close_issued','stopped','publication_intent')
                    or transaction.get('transaction_id') != fence.get('transaction_id')
                    or fence.get('previous_receipt_sha256') !=
                    digest(directory/'000001'/'installation.before.json')
                    or fence.get('candidate_receipt_sha256') !=
                    digest(directory/'000001'/'installation.after.json')
                    or fence.get('candidate_ea_sha256') !=
                    digest(directory/'000001'/'ea.after.ex5')):
                raise ValueError('Installation migration recovery fence changed')
            return dict(migrations=0,installation_sha256=original_sha256,
                pending_migration=True)
        return dict(migrations=len(anchors), installation_sha256=expected)
