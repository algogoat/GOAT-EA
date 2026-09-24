"""Bounded shared guards for the new two-account demo setup, never the live six."""
import contextlib
from datetime import datetime
import hashlib
import json
import ntpath
import os
from pathlib import Path
import time
import uuid

from goat_demo_pair_connection import Refused, require, canonical, unique_object


def raw(path, cap=2*1024*1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and not path.is_junction()
            and path.stat().st_nlink == 1, 'unsafe_evidence_file')
    with path.open('rb') as stream:
        data = stream.read(cap+1)
    require(0 < len(data) <= cap, 'evidence_size')
    return data


def read(path):
    return json.loads(raw(path), object_pairs_hook=unique_object)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def write_new(path, value):
    data = value if isinstance(value, bytes) else encoded(value)
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def claim_once(path, value):
    write_new(path, value)
    return Path(path)


def all_processes(host):
    data = host.powershell("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "@(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | ForEach-Object { "
        "if(-not $_.ExecutablePath){throw 'unobservable process'}; "
        "@{pid=[int]$_.ProcessId;path=$_.ExecutablePath;created=$_.CreationDate.ToUniversalTime().ToString('o')} }) | ConvertTo-Json -Compress")
    values = json.loads(data) if data else []
    return [values] if isinstance(values, dict) else values


def checked_witness(path, host, expected=None, now=None):
    value = read(path)
    require(type(value) is dict and set(value) == {'schema','observedAtUtc','expiresAtUtc','processes','lifecycleLock'}
            and value['schema'] == 'goat-protected-six-v1', 'protected_witness_schema')
    clock = time.time() if now is None else now
    require(type(value['observedAtUtc']) in (int,float) and type(value['expiresAtUtc']) in (int,float)
            and value['observedAtUtc'] <= clock < value['expiresAtUtc']
            and value['expiresAtUtc']-value['observedAtUtc'] <= 8*3600, 'protected_witness_expired')
    require(type(value['processes']) is list and len(value['processes']) == 6, 'protected_six_required')
    require(ntpath.isabs(value['lifecycleLock']), 'lifecycle_lock_path')
    require(expected is None or value == expected, 'protected_witness_changed')
    seen = set()
    actual = all_processes(host)
    for process in value['processes']:
        require(type(process) is dict and set(process) == {'pid','path','created'}
                and type(process['pid']) is int and process['pid'] > 0
                and ntpath.isabs(process['path']) and canonical(process['path']) not in seen,
                'protected_process_schema')
        require(datetime.fromisoformat(process['created']).tzinfo is not None, 'process_timezone')
        seen.add(canonical(process['path']))
        matches = [p for p in actual if canonical(p['path']) == canonical(process['path'])]
        require(len(matches) == 1 and matches[0]['pid'] == process['pid']
                and datetime.fromisoformat(matches[0]['created']) == datetime.fromisoformat(process['created']),
                'protected_process_changed')
    return value


@contextlib.contextmanager
def lifecycle_lock(witness, wait_seconds=20):
    require(type(wait_seconds) in (int,float) and 0<=wait_seconds<=20,'lifecycle_lock_wait_bound')
    path = Path(witness['lifecycleLock'])
    deadline=time.monotonic()+wait_seconds
    while True:
        try:
            descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_BINARY',0))
            break
        except FileExistsError:
            remaining=deadline-time.monotonic()
            require(remaining>0,'lifecycle_lock_busy')
            time.sleep(min(0.25,remaining))
            require(time.monotonic()<deadline,'lifecycle_lock_busy')
    content=encoded({'pid':os.getpid(),'kind':'demo-pair','nonce':uuid.uuid4().hex})
    identity=None
    try:
        require(os.write(descriptor,content)==len(content),'lifecycle_lock_write')
        os.fsync(descriptor)
        # Use the same identity observation at acquisition and release.
        identity=path.stat()
        require(raw(path)==content,'lifecycle_lock_owner_changed')
        yield
    finally:
        os.close(descriptor)
        # Never remove a lock now owned by another actor, even if the operation
        # failed. Retained/replaced locks require inspection, not stale cleanup.
        current=path.stat()
        require(identity is not None and (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino)
                and raw(path)==content,'lifecycle_lock_owner_changed')
        path.unlink()


def assert_new_pair_paths(rows, witness):
    protected = [canonical(ntpath.dirname(p['path'])) for p in witness['processes']]
    for row in rows:
        target = canonical(row['directory'])
        require(not any(target == old or target.startswith(old+'\\') or old.startswith(target+'\\')
                        for old in protected), 'protected_path_overlap')


def pin_module(directory, name, expected):
    import importlib.util
    import sys
    path = Path(directory)/name
    require(hashlib.sha256(raw(path)).hexdigest() == expected, 'helper_pin_changed')
    module_name = Path(name).stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def verify_admission(path, expected_sha256, row, now=None):
    """Inspect root's pinned protected-release/readback receipt, never mint one."""
    import re
    require(path is not None and isinstance(expected_sha256,str)
            and re.fullmatch('[a-f0-9]{64}',expected_sha256) is not None,'admission_proof_required')
    data=raw(path)
    require(hashlib.sha256(data).hexdigest()==expected_sha256,'admission_proof_hash')
    value=json.loads(data,object_pairs_hook=unique_object)
    require(value.get('schemaVersion')==1 and value.get('buildId')==row['buildId']
            and value.get('artifactSHA256')==row['eaSha256']=='8fec6e0379be4f2657f3c425ec1cf2e1701d3a65324e39576dcdcb6405833b0d'
            and value.get('compileReceiptSHA256')=='ad9617637b9733e1c2c9c72ec5bf1bfe9575613848978d242e9dd5bd9a454fab'
            and value.get('sourceCommit')=='e96465d590690178176e55c51ff3c1bc8a363fde','admission_build_binding')
    accounts=value.get('allowedAccountIds')
    require(type(accounts) is list and len(accounts)==2 and all(type(x) is int for x in accounts)
            and set(accounts)=={3000109421,3000109427} and row['login'] in accounts,'admission_pair_scope')
    before=value.get('notBeforeMs');expiry=value.get('expiresAtMs');clock=time.time() if now is None else now
    require(type(before) is int and type(expiry) is int and before<=clock*1000<expiry
            and 0<expiry-before<=7*86400000,'admission_expired_or_not_yet_active')
    release=value.get('backendRelease')
    require(type(release) is dict and release.get('canaryState')=='PASS'
            and bool(release.get('runId')) and bool(release.get('attemptId'))
            and re.fullmatch('[a-f0-9]{40}',release.get('sourceCommit','')) is not None
            and re.fullmatch('[a-f0-9]{64}',release.get('publishedRecordSHA256','')) is not None
            and re.fullmatch('[a-f0-9]{64}',value.get('registrySHA256','')) is not None,
            'protected_backend_release_required')
    api=release.get('api')
    require(type(api) is dict,'protected_api_artifact_required')
    claims=[value['registrySHA256'],release['publishedRecordSHA256']]
    for key in ('verificationSHA256','sourceTreeSHA256','packageSHA256'):
        digest=api.get(key)
        require(isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest) is not None,
                'protected_api_artifact_hash')
        claims.append(digest)
    require(all(digest!='0'*64 for digest in claims) and release['sourceCommit']!='0'*40,
            'placeholder_release_hash_refused')
    return value
