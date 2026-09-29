"""A stopped metadata repair never settles attempts or invents a grant."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from goat_studio import Controller
from studio_installation import load_installation, read_json
from studio_same_ea_rebind import rebind
import test_goat_studio as fixtures


class SameEaRebindTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests()
        self.fixture.setUp()
        self.fixture.receipt['bundle_version'] = '0.5.0-beta.7'
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        self.c = self.fixture.bound()
        self.addCleanup(self.fixture.tearDown)
        self.old = self.fixture.path.read_bytes()
        self.session_path = self.c.root / 'session.json'
        self.old_session = self.session_path.read_bytes()
        backup = self.c.root / 'ea-update-backups' / 'plan-one'
        backup.mkdir(parents=True)
        (backup / 'installation.json').write_bytes(self.old)
        receipt = json.loads(self.old)
        receipt.update(bundle_version='0.5.0-beta.10', installed_at='2026-09-29T19:46:08Z',
                       agent_guide_path=str(self.fixture.root / 'new-guide.md'))
        self.fixture.path.write_text(json.dumps(receipt))
        self.process = SimpleNamespace(inspect=lambda: None)

    def test_exact_preserved_same_ea_receipt_rebinds_without_native_action(self):
        with self.assertRaisesRegex(ValueError, 'Installation changed since bootstrap'):
            Controller(self.fixture.path).open()
        old_receipt = self.c.root / 'ea-update-backups' / 'plan-one' / 'installation.json'
        previous = Controller(old_receipt).open()
        self.assertEqual(previous.state()['run_id'], self.c.run)
        previous.store.close()
        before_db = (self.c.root / 'studio.sqlite').read_bytes()
        result = rebind(self.fixture.path, process=self.process)
        self.assertEqual(result['status'], 'rebound')
        self.assertIs(result['native_action'], False)
        self.assertIs(result['native_qualification'], False)
        self.assertEqual(read_json(self.session_path)['installation_sha256'], sha(load_installation(self.fixture.path)))
        self.assertEqual((self.c.root / 'studio.sqlite').read_bytes(), before_db)
        self.assertEqual(Path(result['previous_session_backup']).read_bytes(), self.old_session)
        self.assertEqual(rebind(self.fixture.path, process=self.process)['status'], 'already_bound')
        recovered = Controller(self.fixture.path).open()
        recovered.store.close()

    def test_pending_native_request_refuses_without_changing_session(self):
        gate = self.c.local / 'native-gate'
        gate.mkdir(parents=True, exist_ok=True)
        (gate / 'request.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unresolved native request or permit'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)

    def test_running_process_and_changed_backup_refuse(self):
        with self.assertRaisesRegex(ValueError, 'must be stopped'):
            rebind(self.fixture.path, process=SimpleNamespace(inspect=lambda: {'pid': 55}))
        backup = self.c.root / 'ea-update-backups' / 'plan-one' / 'installation.json'
        backup.write_text('{}')
        with self.assertRaises(ValueError):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)

    def test_changed_nonmetadata_receipt_and_duplicate_backup_refuse(self):
        receipt = json.loads(self.fixture.path.read_text())
        receipt['catalog_root'] = str(self.fixture.root / 'different-catalog')
        self.fixture.path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'changed installation field'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)
        receipt.pop('catalog_root')
        self.fixture.path.write_text(json.dumps(receipt))
        duplicate = self.c.root / 'ea-update-backups' / 'plan-two'
        duplicate.mkdir()
        (duplicate / 'installation.json').write_bytes(self.old)
        with self.assertRaisesRegex(ValueError, 'Exactly one preserved previous installation'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)

    def test_downgrade_beta_receipt_refuses(self):
        receipt = json.loads(self.fixture.path.read_text())
        receipt['bundle_version'] = '0.5.0-beta.6'
        self.fixture.path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)

    def test_live_or_unknown_session_flag_cannot_rebind(self):
        session = read_json(self.session_path)
        session['demo_only'] = False
        self.session_path.write_text(json.dumps(session))
        before = self.session_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'exact demo session'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_low_disk_or_pending_human_control_preserves_binding(self):
        with patch('studio_same_ea_rebind.shutil.disk_usage',
                   return_value=SimpleNamespace(free=4 * 1024 ** 3)):
            with self.assertRaisesRegex(ValueError, '5 GiB'):
                rebind(self.fixture.path, process=self.process)
        human = self.c.local / self.c.session['directory_id'] / 'human/inbox'
        human.mkdir(parents=True, exist_ok=True)
        (human / 'pending-take.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Pending human control'):
            rebind(self.fixture.path, process=self.process)
        self.assertEqual(self.session_path.read_bytes(), self.old_session)

    def test_installed_cli_rebinds_before_controller_open(self):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name('goat_studio.py')),
             '--installation', str(self.fixture.path), 'same-ea-rebind'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(json.loads(completed.stdout)['result']['status'], 'rebound')
        self.assertEqual(read_json(self.session_path)['installation_sha256'], sha(load_installation(self.fixture.path)))


if __name__ == '__main__':
    unittest.main()
