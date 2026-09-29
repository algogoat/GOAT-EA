"""Real staged package -> reservation -> intent, including fixed numeric flags."""
import hashlib
import json
from pathlib import Path
import unittest

from studio_launch_intent import record_intent
from studio_native_request import ini_sections
import test_goat_studio as fixtures


class LaunchTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.receipt.update(ea_version='1.49', ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        (self.fixture.data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5').write_bytes(b'qualified test fixture')
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        self.fixture.tester['Expert'] = self.fixture.receipt['ea_relative_path']
        self.c = self.fixture.bound()
        self.fixture.grant(self.c)
        self.c.schema['inputs']['RSI_Period'] = dict(type='int', optimizable=True)
        self.c.store.input_schema = self.c.schema
        from campaign_ledger import sha
        self.c.store.input_schema_hash = sha(self.c.schema)
        source = self.fixture.root / 'mixed-fixed-active.set'
        source.write_bytes('EA_Desc=Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\nRSI_Period=9\r\n'.encode('utf-16'))
        settings = self.fixture.root / 'mixed-settings.json'
        settings.write_text(json.dumps(dict(tester=self.fixture.tester, export=self.fixture.exports)))
        self.package = Path(self.c.prepare('mixed', source, settings)['package'])
        self.source = source
        self.manifest = json.loads((self.package / 'manifest.json').read_text())

    def reserve_and_record(self):
        job = self.c.job('mixed')
        digest = hashlib.sha256((self.package / 'manifest.json').read_bytes()).hexdigest()
        self.c.submit('queue.reserve', dict(job_id='mixed', configuration_sha256=job['configuration_sha256'],
            package_sha256=digest), 'mixed-reservation')
        state = self.c.state()
        return record_intent(self.c.store, self.c.terminal, self.c.run, 'mixed', self.package,
            actor='agent', revision=state['revision'], generation=state['generation'])

    def test_fixed_inactive_transport_reaches_intent_without_changing_set(self):
        source_before = self.source.read_bytes()
        alias = self.manifest['jobs'][0]['run_alias']
        sections = ini_sections((self.package / (alias + '.ini')).read_bytes())
        self.assertEqual(sections['TesterInputs']['RSI_Period'], '9||9||0||9||N')
        self.assertEqual(sections['TesterInputs']['Lots'], '0.1||0.1||0.1||0.3||Y')
        result = self.reserve_and_record()
        self.assertEqual(self.c.job('mixed')['status'], 'starting')
        self.assertFalse(result['native_launch_permitted'])
        self.assertEqual(self.source.read_bytes(), source_before)

    def test_changed_fixed_flag_refuses_even_when_manifest_hash_is_recomputed(self):
        item = self.manifest['jobs'][0]
        ini = self.package / (item['run_alias'] + '.ini')
        ini.write_bytes(ini.read_bytes().decode('utf-16').replace('RSI_Period=9||9||0||9||N',
            'RSI_Period=9||5||2||9||Y').encode('utf-16'))
        item['ini_sha256'] = hashlib.sha256(ini.read_bytes()).hexdigest()
        (self.package / 'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'input values differ'):
            self.reserve_and_record()
        self.assertEqual(self.c.job('mixed')['status'], 'reserved')
        self.assertNotIn('launch_intent', self.c.job('mixed'))


if __name__ == '__main__':
    unittest.main()
