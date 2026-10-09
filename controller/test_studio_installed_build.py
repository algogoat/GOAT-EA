"""The installed EA build comes from its binary; the activation status is a cross-check (goatai#2350 6089206538, Claude-Mac 6089229465)."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_build_migration as bm
import studio_catchup as sc
import studio_installed_build as ib
from studio_installation import read_json
from test_studio_build_migration import SOURCE, TARGET, MigrationCase

ROOT = Path(__file__).resolve().parents[1]
B43_SHA = 'e630ee34cb04c26513f16860a927074ec745f3c62869d984260230a89fd4dc24'
B40_SHA = '55d3e393ec80e73612b4305732d4066a925f429c98f80afbe46b41f67088b99b'
# Banker, 2026-10-09: the B40 status the EA last wrote (activation-status-B192...json) and the B43 update.
B40_OBSERVED = 1791302421                                                               # 2026-10-06T16:00:21Z
B43_INSTALLED = datetime(2026, 10, 9, 17, 49, 57, tzinfo=timezone.utc).timestamp()     # EX5 mtime = demo_installed_at
TOKEN = 'B192A4598DA3528A412E93A85A2C2F64'


def epoch(text):
    return datetime.fromisoformat(text).timestamp()


class PinnedTableTests(unittest.TestCase):
    def test_table_is_exactly_the_pinned_candidate_identities(self):
        derived = {}
        for path in sorted((ROOT / 'candidate-builds').glob('*/identity.json')):
            identity = json.loads(path.read_text(encoding='utf-8-sig'))
            binary = path.parent / identity['binary']['name']
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), identity['binary']['sha256'], path.parent.name)
            self.assertNotIn(identity['binary']['sha256'], derived, path.parent.name)
            derived[identity['binary']['sha256']] = identity['build_id']
        self.assertEqual(ib.PINNED_BUILDS, derived)
        self.assertEqual(ib.PINNED_BUILDS[B43_SHA], 'V1.49-BETA17-43')

    def test_one_resolver_reads_the_activation_status_build(self):
        """No second copy of the old status-only logic: only studio_installed_build reads buildId to state the installed build."""
        for name in ('studio_catchup.py', 'studio_holdup.py', 'studio_research_status.py'):
            text = (ROOT / 'controller' / name).read_text(encoding='utf-8')
            self.assertNotIn("get('buildId')", text, name)
        self.assertIn('installed_build.build_id(self.c.install', (ROOT / 'controller' / 'studio_catchup.py').read_text(encoding='utf-8'))


class ResolverTests(unittest.TestCase):
    """The Banker shape, fresh agreeing and disagreeing statuses, unknown binaries. Fixture files only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.data, self.common = base / TOKEN, base / 'common'
        self.binary = self.data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'b43')
        os.utime(self.binary, (B43_INSTALLED, B43_INSTALLED))
        (self.common / 'GOAT').mkdir(parents=True)
        self.install = dict(terminal_data_root=str(self.data), common_files_root=str(self.common),
                            ea_relative_path='GOAT-EA\\GOAT V1.49.ex5', ea_sha256=B43_SHA,
                            installed_at='2026-09-28T01:09:10.536Z', demo_installed_at='2026-10-09T17:49:57.908302+00:00')

    def status(self, build, observed=None, mtime=None):
        path = self.common / 'GOAT' / ('activation-status-' + TOKEN + '.json')
        value = dict(accountId='3000082754', buildId=build, reason='activation_oninit_observed', httpStatus=0)
        if observed is not None:
            value['observedAtUtc'] = observed
        path.write_text(json.dumps(value), encoding='utf-8')
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_banker_shape_stale_b40_status_before_the_b43_install_is_ignored(self):
        self.status(SOURCE, B40_OBSERVED, mtime=B40_OBSERVED)
        found = ib.resolve(self.install)
        self.assertEqual((found['build_id'], found['source'], found['status']['state']), (TARGET, 'ea_binary_sha256', 'stale'))
        self.assertEqual((found['install_time_source'], found['status']['build_id']), ('receipt_demo_installed_at', SOURCE))
        self.assertEqual(found['status']['observed_utc'], '2026-10-06T16:00:21+00:00')
        self.assertIn('V1.49-BETA17-40 observed 2026-10-06T16:00:21+00:00 predates the install at 2026-10-09T17:49:57+00:00', found['basis'])
        self.assertIn('ignored as stale', found['basis'])
        self.assertEqual(ib.build_id(self.install), TARGET)

    def test_a_fresh_status_that_agrees_is_ok(self):
        self.status(TARGET, int(B43_INSTALLED) + 60)
        found = ib.resolve(self.install)
        self.assertEqual((found['build_id'], found['status']['state']), (TARGET, 'agrees'))

    def test_a_fresh_status_that_disagrees_refuses_naming_both(self):
        self.status(SOURCE, int(B43_INSTALLED) + 60)
        with self.assertRaises(ib.InstalledBuildError) as caught:
            ib.resolve(self.install)
        self.assertEqual(caught.exception.code, ib.CONFLICT)
        self.assertRegex(str(caught.exception), '^INSTALLED_BUILD_STATUS_CONFLICT: .* is V1.49-BETA17-43, but its activation status .* reports V1.49-BETA17-40')
        self.assertEqual(caught.exception.detail['status']['state'], 'conflict')
        self.assertIsNone(ib.build_id(self.install, strict=False))
        # At the install second exactly is not before it: checked, not ignored.
        self.status(SOURCE, int(B43_INSTALLED) + 1)
        with self.assertRaises(ib.InstalledBuildError):
            ib.resolve(dict(self.install, demo_installed_at=None))

    def test_unknown_binary_refuses_with_or_without_a_status(self):
        unknown = dict(self.install, ea_sha256='0' * 64)
        for build in (None, TARGET):
            if build:
                self.status(build, int(B43_INSTALLED) + 60)
            with self.subTest(status=build), self.assertRaises(ib.InstalledBuildError) as caught:
                ib.resolve(unknown)
            self.assertEqual(caught.exception.code, ib.UNKNOWN)
            self.assertTrue(str(caught.exception).startswith('INSTALLED_BUILD_UNKNOWN: the installed EA binary (sha256 000000000000)'))
            self.assertIsNone(ib.build_id(unknown, strict=False))
        self.assertEqual(ib.public(unknown)['code'], ib.UNKNOWN)

    def test_without_an_install_time_no_status_can_be_shown_stale(self):
        self.binary.unlink()
        bare = {k: v for k, v in self.install.items() if k not in ('installed_at', 'demo_installed_at')}
        self.status(SOURCE, B40_OBSERVED)
        with self.assertRaises(ib.InstalledBuildError) as caught:
            ib.resolve(bare)
        self.assertEqual(caught.exception.code, ib.CONFLICT)

    def test_install_time_is_the_latest_of_binary_and_receipt(self):
        # A copy that kept an older file time does not make a pre-install status fresh: the receipt time wins.
        os.utime(self.binary, (B40_OBSERVED - 3600, B40_OBSERVED - 3600))
        self.assertEqual(ib.install_time(self.install), (epoch('2026-10-09T17:49:57.908302+00:00'), 'receipt_demo_installed_at'))
        self.status(SOURCE, B40_OBSERVED)
        self.assertEqual(ib.resolve(self.install)['status']['state'], 'stale')
        # Without receipt times, the EX5 file time; a zoneless receipt time is not used.
        os.utime(self.binary, (B43_INSTALLED, B43_INSTALLED))
        self.assertEqual(ib.install_time(dict(self.install, installed_at='2026-10-10T00:00:00', demo_installed_at=None)),
                         (B43_INSTALLED, 'ea_binary_mtime'))

    def test_a_status_without_observed_time_uses_its_file_time(self):
        self.status(SOURCE, None, mtime=B40_OBSERVED)
        found = ib.resolve(self.install)
        self.assertEqual((found['status']['state'], found['status']['observed_source']), ('stale', 'file_mtime'))
        self.status(SOURCE, None, mtime=B43_INSTALLED + 60)
        with self.assertRaises(ib.InstalledBuildError):
            ib.resolve(self.install)

    def test_missing_unreadable_or_buildless_status_leaves_the_binary_build(self):
        self.assertEqual(ib.resolve(self.install)['status']['state'], 'missing')
        path = self.status(TARGET, 1)
        path.write_text('{not json', encoding='utf-8')
        self.assertEqual(ib.resolve(self.install)['status']['state'], 'unreadable')
        path.write_text(json.dumps(dict(reason='awaiting_approval', observedAtUtc=int(B43_INSTALLED) + 60)), encoding='utf-8')
        self.assertEqual((ib.resolve(self.install)['build_id'], ib.resolve(self.install)['status']['state']), (TARGET, 'no_build'))

    def test_holdup_and_research_status_use_the_same_resolver(self):
        from studio_holdup import HoldupRunner
        from studio_research_status import research_status
        self.status(SOURCE, B40_OBSERVED)
        holder = SimpleNamespace(c=SimpleNamespace(install=self.install))
        calls = []
        real = ib.resolve

        def spy(install):
            calls.append(install)
            return real(install)
        with patch.object(ib, 'resolve', spy):
            self.assertEqual(HoldupRunner._installed_build_id(holder), TARGET)
            self.assertEqual(sc.CatchupRunner._installed_build_id(holder), TARGET)
            local = self.data / 'MQL5/Files/GOATStudio'; local.mkdir(parents=True)
            state = Path(self.tmp.name) / 'state'; state.mkdir()
            value = research_status(root=state, install=self.install, session=dict(run_id='r', terminal_id='t', account=dict(login='1', server='Demo')),
                                    local=local, now=B43_INSTALLED + 600, process=None, jobs=[])
        self.assertEqual(len(calls), 3)
        self.assertEqual((value['ea']['installed_build']['build_id'], value['ea']['installed_build']['status']['state']), (TARGET, 'stale'))
        # Hold-up records identity only: an unknown binary is None there, never a failed collection.
        holder.c.install = dict(self.install, ea_sha256='0' * 64)
        self.assertIsNone(HoldupRunner._installed_build_id(holder))
        self.assertEqual(research_status(root=state, install=holder.c.install, session=dict(run_id='r', terminal_id='t', account=dict(login='1', server='Demo')),
                                         local=local, now=B43_INSTALLED + 600, process=None, jobs=[])['ea']['installed_build']['code'], ib.UNKNOWN)


class BankerMigrationTests(MigrationCase):
    """Catch-up with build_migration on the exact Banker shape: the real B43 EX5 installed after a stale B40 status."""

    def setUp(self):
        super().setUp()
        binary = Path(self.controller.install['terminal_data_root']) / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
        shutil.copyfile(ROOT / 'candidate-builds/beta17-B43/GOAT V1.49.ex5', binary)
        os.utime(binary, (B43_INSTALLED, B43_INSTALLED))
        self.controller.install.update(ea_sha256=B43_SHA, installed_at='2026-09-28T01:09:10.536Z',
                                       demo_installed_at='2026-10-09T17:49:57.908302+00:00')
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), B43_SHA)
        self.status_file = Path(self.controller.install['common_files_root']) / 'GOAT' / 'activation-status-terminal.json'
        self.write_status(SOURCE, B40_OBSERVED)

    def write_status(self, build, observed):
        self.status_file.write_text(json.dumps(dict(accountId='123', buildId=build, reason='activation_oninit_observed',
                                                    observedAtUtc=observed)), encoding='utf-8')

    def test_migration_validate_passes_on_the_binary_build(self):
        result = self.runner.validate(self.mplan())
        self.assertEqual(result['member_count'], 1)
        self.assertEqual(result['build_migration']['target_build'], TARGET)

    def test_a_fresh_conflicting_status_refuses_validate_naming_both(self):
        self.write_status(SOURCE, int(B43_INSTALLED) + 60)
        with self.assertRaisesRegex(ValueError, 'build_migration targets V1.49-BETA17-43, but INSTALLED_BUILD_STATUS_CONFLICT: .*'
                                                'is V1.49-BETA17-43, .* reports V1.49-BETA17-40'):
            self.runner.validate(self.mplan())

    def test_member_start_uses_the_resolver(self):
        self.runner.prepare('bk1', self.mplan())
        self.write_status(SOURCE, int(B43_INSTALLED) + 60)
        with self.assertRaisesRegex(ValueError, 'Build-migration member .* targets V1.49-BETA17-43, but INSTALLED_BUILD_STATUS_CONFLICT.*nothing was started'):
            self.runner.start('bk1', 1)
        self.assertFalse(self.starts)

    def test_stale_status_member_runs_and_ran_on_comes_from_the_binary(self):
        self.retest_build = None   # the re-test capture names no build: ran_on is the resolver's
        state, manifest = self.run_all('bk2', self.mplan())
        member = state['members'][0]
        self.assertEqual(member['status'], 'completed', member)
        record = read_json(Path(manifest['members'][0]['evidence_dir']) / bm.RECORD_FILE)
        self.assertEqual((record['ran_on_build'], record['target_build']), (TARGET, TARGET))
        self.assertEqual(manifest['members'][0]['pins']['installed_build_id'], TARGET)


if __name__ == '__main__':
    unittest.main()
