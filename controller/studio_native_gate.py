"""Exclusive file gate shared with MQL FileOpen without FILE_SHARE_* flags.

Serializes cooperating controller commits and terminal launch consumption. It
does not coordinate legacy EA writers or establish native tester ownership.
"""
from contextlib import contextmanager
import json
import hashlib
import re
import os
from pathlib import Path


@contextmanager
def exclusive_gate(root):
    with file_gate(root, shared=False):
        yield


@contextmanager
def shared_gate(root):
    """Concurrent controller holds; excluded by an exclusive handover hold."""
    with file_gate(root, shared=True):
        yield


@contextmanager
def file_gate(root, *, shared):
    path=Path(root)/'launch.lock'
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                         wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        close=kernel.CloseHandle
        close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
        # Both access and share checks are symmetric: readers coexist, but an
        # exclusive handle cannot open until every shared handle is released.
        handle=create(str(path),0xC0000000,3 if shared else 0,None,4,0x80,None)
        if handle==ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:yield
        finally:close(handle)
    else:
        import fcntl
        with path.open('a+b') as handle:
            mode=fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            fcntl.flock(handle.fileno(),mode|fcntl.LOCK_NB)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def configure_gate(store, root):
    """One-time installation; callers must quiesce controller clients first."""
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    database=str(Path(store.db.execute('PRAGMA database_list').fetchone()[2]).resolve())
    with exclusive_gate(root):
        owner=root/'controller.json'
        if owner.exists():
            if json.loads(owner.read_text())!={'database':database}:
                raise ValueError('Native gate belongs to another controller')
        else:
            with owner.open('x',encoding='utf-8') as handle:
                json.dump({'database':database},handle);handle.flush();os.fsync(handle.fileno())
        store.db.execute('BEGIN IMMEDIATE')
        try:
            current=store.db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
            if current and Path(current[0])!=root:raise ValueError('Native gate cannot be rebound')
            for row in store.db.execute('SELECT jobs FROM studio_queues'):
                if any(j['status'] in ('reserved','starting','running','reconcile_required','verifying') for j in json.loads(row[0])):
                    raise ValueError('Cannot install native gate while an attempt is unresolved')
            store.db.execute('INSERT OR IGNORE INTO studio_native_gate VALUES(1,?)',(str(root),))
            store.db.execute('COMMIT')
        except BaseException:
            store.db.execute('ROLLBACK');raise


def _read_gate_evidence(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Linked native evidence is not accepted')
    if not path.is_file() or path.stat().st_size > 64*1024*1024:
        raise ValueError('Missing or oversized native evidence')
    with path.open('rb') as stream:
        raw = stream.read(64*1024*1024+1)
    if len(raw) > 64*1024*1024:
        raise ValueError('Oversized native evidence')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate native evidence key')
            value[key] = item
        return value
    return raw, json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)


def assert_clear_controls(db, root):
    """Read-only settled-request classification; caller holds exclusive_gate.

    A native dispatch result alone never proves tester completion. Retained
    requests are accepted only after exact consumption AND durable controller
    finish/released-transaction evidence. This helper deletes no evidence.
    """
    from campaign_ledger import packed, sha
    from studio_dispatch_observe import observe_dispatch
    root = Path(root)
    if (root/'permit.json').exists() or (root/'permit.json').is_symlink():
        raise ValueError('Native request or permit remains; reconcile before clearing pending work')
    request_path = root/'request.json'
    if not request_path.exists() and not request_path.is_symlink():
        return dict(status='absent')
    try:
        raw, request = _read_gate_evidence(request_path)
        request_id = request['request_id']
        if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{64}', request_id):
            raise ValueError('Invalid retained request identity')
        database = str(Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve())
        _, owner = _read_gate_evidence(root/'controller.json')
        if owner != {'database': database}:
            raise ValueError('Gate belongs to another controller database')
        _, issued = _read_gate_evidence(root/('issued-'+request_id+'.json'))
        for prefix in ('consumed-', 'result-'):
            _read_gate_evidence(root/(prefix+request_id+'.json'))
        digest = hashlib.sha256(raw).hexdigest()
        if issued['request'] != request or issued['request_sha256'] != digest:
            raise ValueError('Retained request differs from issuance')
        dispatch = observe_dispatch(root, request_id)
        if dispatch['status'] != 'receipt_observed' or dispatch['consumed'] is not True or dispatch['request_sha256'] != digest:
            raise ValueError('Exact consumed dispatch and result required')
        binding = packed(dict(terminal_id=request['terminal_id'], run_id=request['run_id']))
        row = db.execute('SELECT jobs FROM studio_queues WHERE binding=?', (binding,)).fetchone()
        if row is None:
            raise ValueError('Retained request has no controller binding')
        jobs = [job for job in json.loads(row[0]) if job['job_id'] == request['job_id']]
        if len(jobs) != 1 or jobs[0]['status'] not in ('completed', 'cancelled', 'failed'):
            raise ValueError('Retained request is not durably finished')
        job = jobs[0]; intent = job['launch_intent']; attempt = intent['attempt_id']
        if not isinstance(attempt, str) or not re.fullmatch('[a-f0-9]{64}', attempt):
            raise ValueError('Invalid retained attempt identity')
        action = request.get('action', 'start')
        if action not in ('start', 'arm_restart', 'cancel'):
            raise ValueError('Unsupported retained execution request')
        expected_id = sha([attempt, 'cancel']) if action == 'cancel' else attempt
        if request_id != expected_id or (action == 'cancel' and request.get('attempt_id') != attempt):
            raise ValueError('Request belongs to another attempt')
        if sha(job['configuration']) != job['configuration_sha256'] or request['configuration_sha256'] != job['configuration_sha256']:
            raise ValueError('Settled configuration differs from request')
        controller_root = Path(database).parent
        result_path = controller_root/'attempts'/attempt/'result.json'
        if Path(job['completion_path']).resolve() != result_path:
            raise ValueError('Completion is not the canonical attempt result')
        result_raw, completion = _read_gate_evidence(result_path)
        _, transaction = _read_gate_evidence(result_path.parent/'transaction.json')
        outcomes = {'completed': 'native_completed', 'cancelled': 'native_cancelled', 'failed': 'native_error'}
        if (completion != job['completion'] or completion['status'] != job['status']
                or completion['job_id'] != job['job_id'] or completion['attempt_id'] != attempt
                or completion['configuration_sha256'] != job['configuration_sha256']
                or completion['configuration'] != job['configuration']
                or completion['package_sha256'] != intent['package_sha256']
                or completion['native']['status'] != outcomes[job['status']]
                or transaction['phase'] != 'restored' or transaction['owner'] != attempt):
            raise ValueError('Controller finish or restored transaction evidence differs')
        package = controller_root/'packages'/job['job_id']
        if Path(intent['package']).resolve() != package:
            raise ValueError('Attempt package is not the canonical job package')
        manifest_raw, _ = _read_gate_evidence(package/'manifest.json')
        if hashlib.sha256(manifest_raw).hexdigest() != intent['package_sha256']:
            raise ValueError('Finished package manifest changed')
        return dict(status='settled', request_id=request_id, request_sha256=digest,
                    attempt_id=attempt, job_id=job['job_id'], terminal_id=request['terminal_id'],
                    run_id=request['run_id'], completion_sha256=hashlib.sha256(result_raw).hexdigest())
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('Native request or permit remains unresolved: '+str(error)) from error


@contextmanager
def mutation_gate(db, *, require_clear_controls=False):
    row=db.execute('SELECT root FROM studio_native_gate WHERE id=1').fetchone()
    if row is None:
        yield
        return
    root=Path(row[0])
    with exclusive_gate(root):
        if require_clear_controls:
            assert_clear_controls(db, root)
        # Invalidating an unconsumed permit before any database mutation is
        # conservative on rollback: stale requests cannot launch afterward.
        (root/'permit.json').unlink(missing_ok=True)
        yield
