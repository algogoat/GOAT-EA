"""EvidenceEnd export setting (EA FU35): one resolved evidence end staged for every member."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import studio_evidence_end as ee
import studio_evidence_end_export as export_end
import test_goat_studio as fixtures
from activate_research_campaign import verify_export_policy
from studio_batch import batch_status, load_batch, prepare_batch, resume_batch, save_batch

SATURDAY = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / 'scripts' / 'test_ea_followups.cjs'


def node():
    explicit = os.environ.get('GOAT_NODE')
    return explicit if explicit and Path(explicit).is_file() else shutil.which('node')


class PolicyTests(unittest.TestCase):
    def policy(self):
        return dict(requested='auto', mode='auto', target='2026-10-02', native_export_end='ea_last_friday_exclusive',
                    native_end_if_exported_now='2026-10-01')

    def test_unsupported_capability_keeps_the_legacy_end(self):
        for capability in (dict(supported=False, capability=ee.CAPABILITY, basis='monitor_build_lacks_evidence_end'),
                           dict(supported=True, capability='another-capability'), None, 'yes'):
            with self.subTest(capability=capability):
                result = export_end.native_policy(self.policy(), capability)
                self.assertEqual(result['native_export_end'], 'ea_last_friday_exclusive')
                self.assertNotIn('ea_setting', result)
                self.assertIsNone(export_end.setting(dict(evidence_end=result)))
        self.assertIsNone(export_end.native_policy(None, dict(supported=True, capability=ee.CAPABILITY)))

    def test_supported_capability_stages_the_explicit_resolved_date(self):
        result = export_end.native_policy(self.policy(), dict(supported=True, capability=ee.CAPABILITY, basis='monitor_observation'))
        self.assertEqual(result['ea_setting'], dict(key='EvidenceEnd', value='2026.10.02'))
        self.assertEqual((result['native_export_end'], result['native_end_if_exported_now']), ('evidence_end_setting', '2026-10-02'))
        native = dict(evidence_end=result)
        self.assertEqual(export_end.setting(native), '2026.10.02')
        self.assertEqual(export_end.serialize('[Export]\r\nMinSR=2.5\r\n', native), '[Export]\r\nMinSR=2.5\r\nEvidenceEnd=2026.10.02\r\n')
        self.assertEqual(export_end.serialize('[Export]\r\n', dict()), '[Export]\r\n')

    def test_a_staged_value_that_differs_from_the_target_refuses(self):
        result = export_end.native_policy(self.policy(), dict(supported=True, capability=ee.CAPABILITY))
        for change in (dict(ea_setting=dict(key='EvidenceEnd', value='2026.09.25')),
                       dict(ea_setting=dict(key='EvidenceEnd', value='AUTO')),
                       dict(ea_setting=dict(key='EvidenceEnd', value='2026.10.02', extra=1)),
                       dict(native_export_end='ea_last_friday_exclusive'), dict(target='2026-09-25')):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    export_end.setting(dict(evidence_end=result | change))

    def test_controller_without_a_bound_installation_is_unsupported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            # A capability observation without an installation to bind it is never trusted.
            (Path(folder) / 'ui-observation.json').write_text(json.dumps(dict(evidence_end=ee.CAPABILITY,
                runtime=dict(program_path='C:\\x\\GOAT V1.49.ex5'))), encoding='utf-8')
            class Unbound: install = None; local = Path(folder)
            result = export_end.for_controller(Unbound(), self.policy())
        self.assertEqual(result['ea_capability'], dict(supported=False, capability=ee.CAPABILITY, basis='installation_unbound'))
        self.assertNotIn('ea_setting', result)

    def test_saved_values(self):
        self.assertIsNone(export_end.saved_value({'MinSR': '2.5'}))
        self.assertEqual(export_end.saved_value({'EvidenceEnd': '2026.09.25'}), '2026-09-25')
        self.assertEqual(export_end.saved_value({'EvidenceEnd': ' AUTO '}), 'auto')
        with self.assertRaises(ValueError):
            export_end.saved_value({'EvidenceEnd': 'friday'})


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp()
        self.controller = self.fixture.bound(); self.fixture.grant(self.controller)
        self.root = self.fixture.root
        source = self.root / 'Template.set'
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        self.spec = dict(schema_version=1, export=self.fixture.exports, evidence_end='auto',
            members=[dict(set_path=str(source), tester=self.fixture.tester | {'Symbol': symbol})
                     for symbol in ('EURUSD.customer', 'GBPUSD.customer')])

    def tearDown(self): self.fixture.tearDown()

    def observe(self, capability=ee.CAPABILITY, program=None):
        install = self.controller.install
        program = program or str(Path(install['terminal_data_root']) / 'MQL5' / 'Experts' / install['ea_relative_path'])
        body = dict(schema_version=1, runtime=dict(program_path=program))
        if capability is not None:
            body['evidence_end'] = capability
        path = self.controller.local / 'ui-observation.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding='utf-8')

    def prepare(self, name):
        file = self.root / (name + '.json'); file.write_text(json.dumps(self.spec), encoding='utf-8')
        return prepare_batch(self.controller, name, file, now=SATURDAY)

    def export_text(self, package):
        return (Path(package) / 'export_settings.GOAT').read_bytes().decode('utf-16')

    def test_capable_monitor_gets_one_explicit_evidence_end_for_every_member(self):
        self.observe()
        result = self.prepare('evidence-batch')
        policy = result['evidence_end']
        self.assertEqual((policy['target'], policy['native_export_end'], policy['ea_setting']['value']),
                         ('2026-10-02', 'evidence_end_setting', '2026.10.02'))
        text = self.export_text(result['package'])
        self.assertEqual(text.count('EvidenceEnd='), 1)
        self.assertIn('EvidenceEnd=2026.10.02\r\n', text)
        self.assertNotIn('AUTO', text.upper().replace('AUTOMATIC', ''))
        package = Path(result['package'])
        manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
        plan = json.loads((package / 'studio-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['export_evidence_end'], '2026.10.02')
        self.assertEqual(plan['native_batch']['evidence_end'], policy)
        # One export file for the whole native queue: every member reads the same boundary.
        self.assertEqual(manifest['export_settings'], plan['native_batch']['export_settings'])
        batch = (package / 'portfolio.goatbatch').read_bytes().decode('utf-16')
        self.assertIn('[GOAT_EXPORT_SETTINGS]\r\n' + text + '[/GOAT_EXPORT_SETTINGS]', batch)
        verify_export_policy(package, plan, manifest)
        self.assertEqual(batch_status(self.controller, 'evidence-batch')['evidence_end']['ea_setting']['value'], '2026.10.02')

    def test_successor_and_saved_batch_keep_the_same_date_after_the_next_friday(self):
        self.observe()
        self.prepare('evidence-batch'); self.controller.cancel('evidence-batch')
        later = SATURDAY + timedelta(days=7)
        successor = resume_batch(self.controller, 'evidence-batch', 'evidence-batch-r1', now=later)
        self.assertEqual((successor['evidence_end']['requested'], successor['evidence_end']['ea_setting']['value']),
                         ('2026-10-02', '2026.10.02'))
        self.assertIn('EvidenceEnd=2026.10.02\r\n', self.export_text(successor['package']))
        output = self.root / 'saved.goatbatch'
        save_batch(self.controller, 'evidence-batch', output)
        loaded = load_batch(self.controller, 'loaded-evidence', output)
        self.assertEqual(loaded['evidence_end']['requested'], '2026-10-02')
        self.assertIn('EvidenceEnd=2026.10.02\r\n', self.export_text(loaded['package']))
        self.assertNotIn('EvidenceEnd', self.controller.job('loaded-evidence')['configuration']['export'])

    def test_older_build_or_foreign_program_keeps_legacy_package_bytes(self):
        for name, capability, program in (('no-capability', None, None), ('foreign', ee.CAPABILITY, 'C:\\elsewhere\\GOAT V1.49.ex5')):
            with self.subTest(name=name):
                self.observe(capability, program)
                result = self.prepare(name)
                self.assertEqual(result['evidence_end']['native_export_end'], 'ea_last_friday_exclusive')
                self.assertFalse(result['evidence_end']['ea_capability']['supported'])
                self.assertNotIn('EvidenceEnd', self.export_text(result['package']))
                self.assertNotIn('export_evidence_end', json.loads((Path(result['package']) / 'manifest.json').read_text()))
        del self.spec['evidence_end']
        self.observe()
        result = self.prepare('no-evidence-end')
        self.assertIsNone(result['evidence_end'])
        self.assertNotIn('EvidenceEnd', self.export_text(result['package']))

    def test_tampered_staged_evidence_end_refuses(self):
        self.observe()
        package = Path(self.prepare('evidence-batch')['package'])
        plan = json.loads((package / 'studio-plan.json').read_text(encoding='utf-8'))
        manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
        target = package / 'export_settings.GOAT'; original = target.read_bytes()
        text = original.decode('utf-16')
        for changed in (text.replace('EvidenceEnd=2026.10.02', 'EvidenceEnd=2026.09.25'),
                        text.replace('EvidenceEnd=2026.10.02', 'EvidenceEnd=AUTO'),
                        text.replace('EvidenceEnd=2026.10.02\r\n', '')):
            with self.subTest(changed=changed[-30:]):
                target.write_bytes(changed.encode('utf-16'))
                with self.assertRaises(ValueError):
                    verify_export_policy(package, plan, manifest)
        target.write_bytes(original)
        verify_export_policy(package, plan, manifest)
        # Consistently rewritten export file and .goatbatch still disagree with the reviewed plan.
        batch = package / 'portfolio.goatbatch'; batch_original = batch.read_bytes()
        target.write_bytes(text.replace('EvidenceEnd=2026.10.02', 'EvidenceEnd=2026.09.25').encode('utf-16'))
        batch.write_bytes(batch_original.decode('utf-16').replace('EvidenceEnd=2026.10.02', 'EvidenceEnd=2026.09.25').encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'Staged EvidenceEnd differs'):
            verify_export_policy(package, plan, manifest)
        target.write_bytes(original); batch.write_bytes(batch_original)
        with self.assertRaisesRegex(ValueError, 'Manifest EvidenceEnd'):
            verify_export_policy(package, plan, {k: v for k, v in manifest.items() if k != 'export_evidence_end'})

    def test_saved_batch_with_an_open_evidence_end_refuses_at_load(self):
        self.observe()
        self.prepare('evidence-batch')
        output = self.root / 'open.goatbatch'
        save_batch(self.controller, 'evidence-batch', output)
        text = output.read_bytes().decode('utf-16').replace('EvidenceEnd=2026.10.02', 'EvidenceEnd=2999.01.01')
        output.write_bytes(text.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'not a closed broker day'):
            load_batch(self.controller, 'open-evidence', output)


@unittest.skipUnless(node() and HARNESS.is_file(), 'node is required for the EA mirror check')
class EaMirrorTests(unittest.TestCase):
    """The EA's AUTO and explicit checks (GOATEvidenceEnd.mqh, run in node) equal studio_evidence_end."""

    def test_ea_auto_matches_the_controller_rule_for_every_hour_of_three_weeks(self):
        start = datetime(2026, 9, 21, 0, 30)
        moments = [start + timedelta(hours=hour) for hour in range(21 * 24)]
        request = dict(window_end='2026.06.01', cases=[dict(setting='AUTO', server=moment.strftime('%Y.%m.%d %H:%M')) for moment in moments])
        answers = self.ea(request)
        for moment, answer in zip(moments, answers):
            expected = ee.auto(moment.replace(tzinfo=timezone.utc), clock='utc')
            self.assertEqual((answer['evidence_end'], answer['to_date']), (expected['date'], expected['tester_to_date']), moment)

    def test_ea_explicit_dates_match_the_controller_closed_day_rule(self):
        now = datetime(2026, 10, 3, 9, 0)
        values = ['2026.10.02', '2026.10.03', '2026.10.04', '2026.09.25', '2026.06.01', '2026.05.31', '2026.02.30', '2026-10-02', ' 2026.09.30 ']
        answers = self.ea(dict(window_end='2026.06.01', cases=[dict(setting=value, server=now.strftime('%Y.%m.%d %H:%M')) for value in values]))
        for value, answer in zip(values, answers):
            try:
                expected = ee.resolve(value, now.replace(tzinfo=timezone.utc), clock='utc',
                                      not_before=[('2026.06.01', 'window end')])
            except ValueError:
                expected = None
            accepted = answer['to_date'] != ''
            if value == '2026-10-02':
                self.assertFalse(accepted)  # The EA reads MT5 dates only; the controller always stages YYYY.MM.DD.
                continue
            self.assertEqual(accepted, expected is not None, value)
            if expected is not None:
                self.assertEqual((answer['evidence_end'], answer['to_date']), (expected['date'], expected['tester_to_date']), value)

    def ea(self, request):
        result = subprocess.run([node(), str(HARNESS), '--mirror'], input=json.dumps(request), capture_output=True,
                                text=True, encoding='utf-8', timeout=60, env=os.environ | dict(GOAT_EA_ROOT=str(REPO)))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


if __name__ == '__main__':
    unittest.main()
