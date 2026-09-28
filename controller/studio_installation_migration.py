"""Verify an append-only, same-session EA build migration chain.

The original session and research authority are never relabelled. Every later
installed build must be linked by a retained exact admission and a second
digest in the controller database. This module verifies history; it never
creates or extends a grant.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3

from campaign_ledger import sha
from studio_handover import safe_path
from studio_installation import read_json


def digest(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def verify_installation_chain(root, current, original_sha256):
    """Return only after current bytes follow the immutable session install."""
    if sha(current) == original_sha256:
        return dict(migrations=0, installation_sha256=original_sha256)
    root = safe_path(root)
    directory = safe_path(root/'installation-migrations')
    database = safe_path(root/'studio.sqlite')
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
            if set(checked) != {'input','admission','identity'}:
                raise ValueError('Authenticated installation qualification is missing')
            admission, identity, request = checked['admission'], checked['identity'], checked['input']
            created_ms = record['created_utc'] * 1000
            if (sha(checked) != record['admission_sha256']
                    or identity.get('manifestSha256') != record['bundle_manifest_sha256']
                    or identity.get('eaSha256') != new['ea_sha256']
                    or admission.get('artifactSha256') != new['ea_sha256']
                    or admission.get('sourceCommit') != identity.get('eaSourceRevision')
                    or admission.get('accountId') != record['account']['login']
                    or request.get('accountId') != record['account']['login']
                    or admission.get('buildId') != request.get('buildId')
                    or request.get('selection',{}).get('terminalExecutable') != new['terminal_executable']
                    or request.get('selection',{}).get('terminalDataRoot') != new['terminal_data_root']
                    or admission.get('mode') != 'INTERNAL_REVIEWED'
                    or admission.get('grantsControl') is not False
                    or not admission.get('checkedAtMs',float('inf')) <= created_ms < admission.get('validUntilMs',0)
                    or created_ms < admission.get('notBeforeMs',float('inf'))
                    or (not admission.get('persistent',False) and admission.get('expiresAtMs') is not None
                        and created_ms >= admission['expiresAtMs'])):
                raise ValueError('Exact reviewed build admission changed')
            archive = read_json(safe_path(folder/'archive.json'))
            required_archive = {'session.json','research-authority.json','epoch.json',
                'installation.before.json','ea.before.ex5','native-state.json',
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
            raise ValueError('Installed build is not the end of the migration chain')
        return dict(migrations=len(anchors), installation_sha256=expected)
