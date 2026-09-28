"""A migrated build must retain the exact original grant and archived evidence."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from campaign_ledger import sha
from studio_installation_migration import verify_installation_chain
from studio_installation import read_json


def raw(path, data):
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def stored(path, value):
    return raw(path, (json.dumps(value, sort_keys=True) + '\n').encode())


class InstallationMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.account = {'login': '3000082754', 'server': 'Darwinex-Demo'}
        old_ea = b'old reviewed EA'
        new_ea = b'new reviewed EA'
        self.old = dict(ea_sha256=hashlib.sha256(old_ea).hexdigest(),
            bundle_version='old', agent_guide_path='C:/old/guide', installed_at='before',
            terminal_executable='C:/MT5/terminal64.exe', terminal_data_root='C:/MT5/Data',
            catalog_root='C:/MT5/Common/Catalog', controller_state_root=str(self.root),
            ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        self.new = self.old | dict(ea_sha256=hashlib.sha256(new_ea).hexdigest(),
            bundle_version='new', agent_guide_path='C:/new/guide', installed_at='after')
        self.original_sha = sha(self.old)
        folder = self.root/'installation-migrations'/'000001'
        folder.mkdir(parents=True)
        self.folder = folder
        old_raw = stored(folder/'installation.before.json', self.old)
        new_raw = stored(folder/'installation.after.json', self.new)
        epoch = dict(installation_sha256=self.original_sha, account=self.account,
            plan_sha256='a'*64, expires_utc=200)
        authority = dict(plan_sha256=epoch['plan_sha256'])
        session = dict(installation_sha256=self.original_sha, account=self.account,
            authority_sha256=sha(authority))
        checked = dict(input=dict(accountId=self.account['login'], buildId='V1.49-DIAGNOSTIC',
            selection=dict(terminalExecutable=self.new['terminal_executable'],
                terminalDataRoot=self.new['terminal_data_root'])),
            admission=dict(mode='INTERNAL_REVIEWED', artifactSha256=self.new['ea_sha256'],
                sourceCommit='b'*40, accountId=self.account['login'], buildId='V1.49-DIAGNOSTIC',
                grantsControl=False, checkedAtMs=99000, validUntilMs=110000,
                notBeforeMs=0, persistent=False, expiresAtMs=190000),
            identity=dict(manifestSha256='c'*64, eaSha256=self.new['ea_sha256'],
                eaSourceRevision='b'*40))
        stored(folder/'admission.json', checked)
        archive = {}
        for name, value in (('session.json', session), ('research-authority.json', authority),
                            ('epoch.json', epoch), ('native-state.json', {'owner': 'agent'}),
                            ('queue.json', {'jobs': ['cancelled']}), ('native-gate.json', {'pending': False})):
            archive[name] = stored(folder/name, value)
        archive['installation.before.json'] = old_raw
        archive['ea.before.ex5'] = raw(folder/'ea.before.ex5', old_ea)
        stored(folder/'archive.json', archive)
        record = dict(schema_version=1, sequence=1,
            previous_installation_sha256=self.original_sha,
            candidate_installation_sha256=sha(self.new),
            previous_receipt_sha256=old_raw, candidate_receipt_sha256=new_raw,
            previous_ea_sha256=self.old['ea_sha256'], candidate_ea_sha256=self.new['ea_sha256'],
            epoch_sha256=sha(epoch), epoch_expires_utc=200,
            admission_sha256=sha(checked), bundle_manifest_sha256='c'*64,
            archive_sha256=sha(archive), created_utc=100, account=self.account,
            plan_sha256=epoch['plan_sha256'])
        anchor = stored(folder/'migration.json', record)
        with closing(sqlite3.connect(self.root/'studio.sqlite')) as db:
            db.execute('CREATE TABLE studio_build_migrations(sequence INTEGER PRIMARY KEY,record_sha256 TEXT NOT NULL)')
            db.execute('INSERT INTO studio_build_migrations VALUES(1,?)', (anchor,))
            db.commit()

    def reseal_admission(self, change):
        checked = read_json(self.folder/'admission.json')
        change(checked['admission'])
        stored(self.folder/'admission.json', checked)
        record = read_json(self.folder/'migration.json')
        record['admission_sha256'] = sha(checked)
        anchor = stored(self.folder/'migration.json', record)
        with closing(sqlite3.connect(self.root/'studio.sqlite')) as db:
            db.execute('UPDATE studio_build_migrations SET record_sha256=? WHERE sequence=1', (anchor,))
            db.commit()

    def test_original_build_needs_no_migration(self):
        self.assertEqual(verify_installation_chain(self.root,self.old,self.original_sha)['migrations'], 0)

    def test_exact_archived_build_chain_is_accepted(self):
        self.assertEqual(verify_installation_chain(self.root,self.new,self.original_sha)['migrations'], 1)

    def test_changed_current_build_is_rejected(self):
        with self.assertRaises(ValueError):
            verify_installation_chain(self.root,self.new | {'ea_sha256': '0'*64},self.original_sha)

    def test_changed_archive_or_admission_is_rejected(self):
        for name in ('ea.before.ex5','admission.json','epoch.json'):
            with self.subTest(name=name):
                path = self.folder/name
                prior = path.read_bytes()
                try:
                    path.write_bytes(prior+b'changed')
                    with self.assertRaises(ValueError):
                        verify_installation_chain(self.root,self.new,self.original_sha)
                finally:
                    path.write_bytes(prior)

    def test_consistently_resealed_expired_admission_is_rejected(self):
        self.reseal_admission(lambda value: value.update(validUntilMs=99000))
        with self.assertRaisesRegex(ValueError, 'admission'):
            verify_installation_chain(self.root,self.new,self.original_sha)

    def test_consistently_resealed_foreign_admission_is_rejected(self):
        self.reseal_admission(lambda value: value.update(accountId='9999999999'))
        with self.assertRaisesRegex(ValueError, 'admission'):
            verify_installation_chain(self.root,self.new,self.original_sha)

    def test_consistently_resealed_control_grant_is_rejected(self):
        self.reseal_admission(lambda value: value.update(grantsControl=True))
        with self.assertRaisesRegex(ValueError, 'admission'):
            verify_installation_chain(self.root,self.new,self.original_sha)


if __name__ == '__main__':
    unittest.main()
