import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_legacy_root_gate import assert_legacy_root_settled
from test_studio_legacy_settled_gate import LegacySettledGateTests, write, digest


class RootGateTests(unittest.TestCase):
    def fixture(self):
        f = LegacySettledGateTests.fixture(self)
        gate = f['base']/'terminal/MQL5/Files/GOATStudio/native-gate'
        gate.parent.mkdir(parents=True)
        f['gate'].rename(gate)
        f['gate'] = gate
        f['db'].execute('UPDATE studio_native_gate SET root=?', (str(gate),))
        f['request'].pop('native_control_scope')
        write(gate/'request.json', f['request'])
        raw = (gate/'request.json').read_bytes()
        write(gate/('issued-'+f['attempt']+'.json'), dict(request=f['request'], request_sha256=digest(raw)))
        (gate/('consumed-'+f['attempt']+'.json')).write_bytes(raw)
        write(gate/('result-'+f['attempt']+'.json'), dict(request_id=f['attempt'], request_sha256=digest(raw), status='RESTART_ARMED_RECONCILE'))
        f['installation'] = dict(terminal_data_root=str(f['base']/'terminal'),
                                terminal_executable=str(f['base']/'terminal.exe'), common_files_root=str(f['base']/'common'))
        f['plan']['research_binding'] = dict(research_data_root=f['installation']['terminal_data_root'],
            research_terminal=f['installation']['terminal_executable'], common_files_root=f['installation']['common_files_root'], live_trading_allowed=False)
        write(f['package']/'studio-plan.json', f['plan'])
        f['manifest']['campaign_id'] = sha(f['plan'])
        write(f['package']/'manifest.json', f['manifest'])
        f['job']['launch_intent']['package_sha256'] = digest((f['package']/'manifest.json').read_bytes())
        f['outcome']['native'].update(studio_source=f['source'], run_alias=f['alias'], native_run=str(f['base']/'common/GOAT/R0123456789ab'))
        write(f['completion']/'outcome.json', f['outcome'])
        f['transaction']['base'] = str(f['base']/'common/GOAT/GOAT V1.47-Demo')
        write(f['activation']/'transaction.json', f['transaction'])
        write(f['activation']/'activation.json', dict(attempt_id=f['attempt'], run=f['outcome']['native']['native_run']))
        self.save(f)
        return f

    def save(self, f):
        f['db'].execute('UPDATE studio_queues SET jobs=?', (json.dumps([f['job']]),))
        f['db'].commit()

    def check(self, f):
        return assert_legacy_root_settled(f['db'], f['gate'], f['installation'])

    def test_settlement_is_read_only_and_not_launch_clearance(self):
        f = self.fixture()
        before = {p: digest(p.read_bytes()) for p in f['base'].rglob('*') if p.is_file()}
        self.assertFalse(self.check(f)['worker_clearance'])
        self.assertEqual(before, {p: digest(p.read_bytes()) for p in f['base'].rglob('*') if p.is_file()})

    def test_active_public_foreign_changed_evidence_refused(self):
        for kind in ('active', 'public', 'foreign', 'permit', 'consumed', 'transaction', 'outcome', 'bytes', 'controls', 'owner'):
            with self.subTest(kind=kind):
                f = self.fixture()
                if kind == 'active': f['job']['status'] = 'running'; self.save(f)
                if kind == 'public': f['job']['completion_path'] = 'canonical'; self.save(f)
                if kind == 'foreign': f['installation']['terminal_executable'] += '.other'
                if kind == 'permit': write(f['gate']/'permit.json', {})
                if kind == 'consumed': (f['gate']/('consumed-'+f['attempt']+'.json')).write_bytes(b'{}')
                if kind == 'transaction':
                    f['transaction']['phase'] = 'installed'; write(f['activation']/'transaction.json', f['transaction'])
                if kind == 'outcome': write(f['completion']/'outcome.json', {})
                if kind == 'bytes': (f['package']/(f['alias']+'.set')).write_bytes(b'changed')
                if kind in ('controls', 'owner'):
                    write(Path(f['transaction']['base'])/('active_optimization_run.ini' if kind == 'controls' else 'agent-native-control-owner.json'), {})
                with self.assertRaises(ValueError): self.check(f)

    def test_missing_and_linked_completion_refused(self):
        for link in (False, True):
            f = self.fixture(); p = f['completion']/'outcome.json'
            target = f['base']/'elsewhere.json'; p.rename(target)
            if link: p.symlink_to(target)
            with self.assertRaises(ValueError): self.check(f)

    def test_evidence_race_refused(self):
        f = self.fixture()
        import studio_legacy_root_gate as module
        original = module._read_gate_evidence
        def read(path):
            value = original(path)
            if path == f['activation']/'activation.json': (f['gate']/'request.json').write_bytes(b'{}')
            return value
        with patch.object(module, '_read_gate_evidence', side_effect=read):
            with self.assertRaises(ValueError): self.check(f)

    def test_handover_routes_only_historical_root(self):
        f = self.fixture()
        from studio_bootstrap_retirement import handover_gate
        c = SimpleNamespace(local=f['gate'].parent, root=f['base']/'installed', install=f['installation'])
        with patch('studio_bootstrap_retirement.legacy_registration', return_value=None):
            self.assertEqual(handover_gate(c, f['db'], f['gate'])['status'], 'historical_attempt_settled')
            f['job']['completion_path'] = 'missing'; self.save(f)
            with self.assertRaises(ValueError): handover_gate(c, f['db'], f['gate'])


if __name__ == '__main__': unittest.main()
