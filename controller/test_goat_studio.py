"""Portable-host acceptance checks; no MT5 process is launched."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from goat_studio import Controller
from studio_installation import VERSION,load_installation,contracts
from studio_process_check import classify_processes
from studio_settings import validate_export,serialize_export
from studio_native_request import ini_sections

class PortableControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=self.root/'customer data';self.common=self.root/'common';self.bin=self.root/'program/terminal64.exe'
        (self.data/'MQL5/Experts/GOAT-EA').mkdir(parents=True);self.common.mkdir();self.bin.parent.mkdir();self.bin.write_bytes(b'mt5')
        ea=self.data/'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5';ea.write_bytes(b'qualified test fixture')
        self.receipt=dict(schema_version=1,controller_version=VERSION,ea_version='1.48',terminal_executable=str(self.bin),terminal_data_root=str(self.data),common_files_root=str(self.common),ea_relative_path='GOAT-EA\\GOAT V1.48.ex5',ea_sha256=hashlib.sha256(ea.read_bytes()).hexdigest(),controller_state_root=str(self.root/'customer state'))
        self.path=self.root/'installation.json';self.path.write_text(json.dumps(self.receipt))
        self.controller=None
        self.tester=dict(Expert=self.receipt['ea_relative_path'],Symbol='BROKER_EURUSD',Period='M15',Model=1,ExecutionMode=0,Optimization=2,OptimizationCriterion=6,FromDate='2026.02.01',ToDate='2026.09.01',ForwardMode=4,ForwardDate='2026.07.01',Deposit=10000,Currency='USD',Leverage='1:100',UseLocal=1,UseRemote=0,UseCloud=0,Visual=0)
        self.exports=dict(SetsToExport=2,MinScore=60,TargetDD=100,AdjustLots=False,BackOOSDate='2026.01.01',MinARF=0.2,MinSR=2.5,IncludeBackOOS=True,IncludeSequenceData=False)

    def tearDown(self):
        if self.controller and self.controller.store:self.controller.store.close()
        self.temp.cleanup()

    def bound(self):
        c=Controller(self.path);self.controller=c
        c.bootstrap('123456','Customer-Demo');c.store.close();c.store=None;c.open()
        # Tests supply a compact complete schema; production reads shipped V1.48 contracts.
        c.schema=dict(schema_version=1,source_sha256='a'*64,inputs={
            'EA_Desc':dict(type='string',optimizable=False),
            'Lots':dict(type='double',optimizable=True)})
        c.policy=dict(header_sha256='a'*64,main_sha256='b'*64,rules=[],coverage='test_fixture')
        c.store.input_schema=c.schema;c.store.input_schema_hash=sha(c.schema);c.store.dependency_policy=c.policy
        return c

    def grant(self,c):
        s=c.state();c.store.submit(dict(schema_version=1,request_id='human-grant',terminal_id=c.terminal,run_id=c.run,expected_revision=s['revision'],generation=s['generation'],command='control.grant_agent',payload={}),actor='human')

    def prepare(self,c):
        source=self.root/'strategy.set';source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        config=self.root/'settings.json';config.write_text(json.dumps(dict(tester=self.tester,export=self.exports)))
        return c.prepare('beta-job',source,config)

    def test_receipt_paths_and_exact_binary(self):
        self.assertEqual(load_installation(self.path)['terminal_data_root'],str(self.data))
        (self.data/'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5').write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError,'hash differs'):load_installation(self.path)

    def test_receipt_rejects_escape(self):
        self.receipt['ea_relative_path']='..\\elsewhere.ex5';self.path.write_text(json.dumps(self.receipt))
        with self.assertRaisesRegex(ValueError,'relative'):load_installation(self.path)

    def test_receipt_rejects_state_inside_terminal(self):
        self.receipt['controller_state_root']=str(self.data/'state');self.path.write_text(json.dumps(self.receipt))
        with self.assertRaisesRegex(ValueError,'outside MT5'):load_installation(self.path)

    def test_bootstrap_never_grants_or_launches(self):
        c=self.bound();self.assertEqual(c.state()['owner'],'human')
        active=json.loads((c.local/'active.json').read_text());self.assertEqual(active['terminal_data_path'],str(self.data))
        self.assertFalse((c.local/'native-gate/permit.json').exists())
        self.assertEqual(list(self.common.iterdir()),[])

    def test_bootstrap_refuses_foreign_activation(self):
        local=self.data/'MQL5/Files/GOATStudio';local.mkdir(parents=True);(local/'active.json').write_text('{}')
        c=Controller(self.path);self.controller=c
        with self.assertRaisesRegex(ValueError,'Existing Studio'):c.bootstrap('123','Customer-Demo')

    def test_prepare_requires_human_grant(self):
        c=self.bound()
        with self.assertRaisesRegex(ValueError,'Current controller'):self.prepare(c)

    def test_prepare_exact_inputs_server_version_ninth_setting(self):
        c=self.bound();self.grant(c);result=self.prepare(c)
        package=Path(result['package']);manifest=result['manifest'];alias=manifest['jobs'][0]['run_alias']
        export=ini_sections((package/'export_settings.GOAT').read_bytes())
        self.assertEqual(export['Export']['IncludeSequenceData'],'0')
        ini=ini_sections((package/(alias+'.ini')).read_bytes())
        self.assertEqual(ini['Tester']['Symbol'],'BROKER_EURUSD')
        self.assertIn('GOAT V1.48 BROKER_EURUSD',ini['Tester']['Report'])
        run=ini_sections((package/'manifest.ini').read_bytes())['OptimizationRun']
        self.assertEqual(run['Server'],'Customer-Demo');self.assertEqual(run['EA'],'GOAT V1.48')
        self.assertEqual(ini['TesterInputs']['Lots'],'0.1||0.1||0.1||0.3||Y')
        self.assertEqual(self.prepare(c)['reused'],True)
        self.assertEqual(len(c.state()['queue']),1)

    def test_pending_cancel_is_durable(self):
        c=self.bound();self.grant(c);self.prepare(c);c.cancel('beta-job')
        self.assertEqual(c.job('beta-job')['status'],'cancelled')
        self.assertFalse((c.local/'native-gate/permit.json').exists())

    def test_start_failed_preflight_creates_no_attempt(self):
        c=self.bound();self.grant(c);self.prepare(c)
        with patch.object(c,'runtime',side_effect=ValueError('wrong demo account')):
            with self.assertRaisesRegex(ValueError,'wrong demo'):c.start('beta-job')
        self.assertEqual(c.job('beta-job')['status'],'pending')
        self.assertNotIn('launch_intent',c.job('beta-job'))

    def test_sequence_setting_legacy_default_and_strict_boolean(self):
        legacy=dict(self.exports);del legacy['IncludeSequenceData']
        self.assertIs(validate_export(legacy)['IncludeSequenceData'],True)
        self.assertIn('IncludeSequenceData=0\r\n',serialize_export(self.exports))
        with self.assertRaisesRegex(ValueError,'Boolean'):validate_export(self.exports|{'IncludeSequenceData':0})

    def test_only_chosen_customer_terminal_may_run(self):
        binding=dict(research_terminal=str(self.bin))
        selected=dict(ProcessId=100,ExecutablePath=str(self.bin),CreatedUtc='now')
        observed=classify_processes([selected],binding,observed_unix=1)
        self.assertIsNone(observed['protected'])
        other=dict(ProcessId=101,ExecutablePath=str(self.root/'another/terminal64.exe'),CreatedUtc='now')
        with self.assertRaisesRegex(ValueError,'Unmapped terminal'):classify_processes([selected,other],binding,observed_unix=1)

    def test_shipped_contracts_are_v148_complete(self):
        schema,policy=contracts()
        self.assertEqual(schema['defines']['GOAT_VERSION_LABEL'],'"1.48"')
        self.assertEqual(schema['source_sha256'],policy['header_sha256'])
        for rule in policy['rules']:
            self.assertIn(rule['input'],schema['inputs']);self.assertIn(rule['controller'],schema['inputs'])

if __name__=='__main__':unittest.main()
