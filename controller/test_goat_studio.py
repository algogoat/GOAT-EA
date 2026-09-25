"""Portable-host acceptance checks; no MT5 process is launched."""
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
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

    def test_native_reservation_excludes_active_seed_inside_transaction(self):
        c=self.bound();self.grant(c);self.prepare(c)
        before=c.state();job=c.job('beta-job')
        payload=dict(job_id='beta-job',configuration_sha256=job['configuration_sha256'],package_sha256='a'*64)
        slot=c.root/'seed-active.json';slot.write_text(json.dumps(dict(status='active',batch_id='seed-fixture')))
        with self.assertRaisesRegex(ValueError,'Seed runner owns'):
            c.submit('queue.reserve',payload,'native-reserve-after-seed')
        self.assertEqual(c.state(),before)
        slot.write_text(json.dumps(dict(status='released',batch_id='seed-fixture')))
        c.submit('queue.reserve',payload,'native-reserve-after-seed')
        self.assertEqual(c.job('beta-job')['status'],'reserved')

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

    def activated_fixture(self):
        """Exact real package/store/ownership files; MT5 itself is not started."""
        from studio_launch_intent import record_intent
        from native_control_transaction import begin,NAMES
        c=self.bound();self.grant(c);result=self.prepare(c)
        package=Path(result['package']);manifest=result['manifest'];job=c.job('beta-job')
        c.submit('queue.reserve',dict(job_id='beta-job',configuration_sha256=job['configuration_sha256'],package_sha256=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()),'beta-job-reserve')
        state=c.state();intent=record_intent(c.store,c.terminal,c.run,'beta-job',package,actor='agent',revision=state['revision'],generation=state['generation'])
        native=self.common/manifest['native_run_relative'].replace('\\','/');shutil.copytree(package,native)
        base=self.common/'GOAT/GOAT V1.48-Customer-Demo';base.mkdir(parents=True)
        evidence=c.root/'attempts'/intent['attempt_id'];evidence.parent.mkdir(parents=True)
        alias=manifest['jobs'][0]['run_alias']
        controls=dict(zip(NAMES,[('[ActiveOptimizationRun]\r\nRunPath='+manifest['native_run_relative']+'\r\n').encode('utf-16'),(package/(alias+'.ini')).read_bytes(),b'guard']))
        begin(base,evidence,controls,{name:None for name in NAMES},intent['attempt_id'])
        return c,native,base,evidence

    def test_active_cancel_is_owned_idempotent_publication_not_stop(self):
        from studio_dispatch_observe import observe_dispatch
        c,native,base,evidence=self.activated_fixture()
        result=c.cancel('beta-job')
        self.assertEqual(result['status'],'cancel_published_not_confirmed');self.assertFalse(result['stopped'])
        gate=c.local/'native-gate';request=json.loads((gate/'request.json').read_text())
        self.assertEqual(request['action'],'cancel');self.assertEqual(request['account_server'],'Customer-Demo')
        prior=(gate/'request.json').read_bytes()
        again=c.cancel('beta-job')
        self.assertEqual(again['request_id'],result['request_id']);self.assertEqual((gate/'request.json').read_bytes(),prior)
        self.assertEqual(observe_dispatch(gate,result['request_id'])['status'],'awaiting_receipt')

    def test_cancel_rejects_different_native_owner(self):
        c,native,base,evidence=self.activated_fixture()
        (base/'agent-native-control-owner.json').write_text(json.dumps(dict(owner='some-other-attempt',evidence=str(evidence))))
        with self.assertRaisesRegex(ValueError,'another attempt'):c.cancel('beta-job')
        self.assertFalse((c.local/'native-gate/permit.json').exists())

    def test_cancel_pending_status_does_not_revoke_permit(self):
        c,native,base,evidence=self.activated_fixture();c.cancel('beta-job')
        result=c.reconcile('beta-job')
        self.assertEqual(result['status'],'cancel_pending')
        self.assertTrue((c.local/'native-gate/permit.json').exists())

    def test_finish_cancelled_restores_owned_controls_and_retains_result(self):
        from studio_finish import finish
        c,native,base,evidence=self.activated_fixture()
        queue=native/'queue.GOAT';queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Pending_',';Cancelled_').encode('utf-16'))
        with patch.object(c,'runtime',return_value=({},{})):
            result=finish(c,'beta-job')
        self.assertEqual(result['status'],'cancelled')
        self.assertTrue(Path(result['result_path']).is_file());self.assertTrue(result['result']['matrix_result_required'])
        self.assertFalse((base/'agent-native-control-owner.json').exists())
        self.assertEqual(c.job('beta-job')['status'],'cancelled')
        self.assertEqual(finish(c,'beta-job')['reused'],True)

    def test_finish_unknown_state_preserves_ownership(self):
        from studio_finish import finish
        c,native,base,evidence=self.activated_fixture()
        with self.assertRaisesRegex(ValueError,'not finished'):finish(c,'beta-job')
        self.assertTrue((base/'agent-native-control-owner.json').exists())

    def test_finish_complete_without_reports_cannot_release(self):
        from studio_finish import finish
        c,native,base,evidence=self.activated_fixture()
        queue=native/'queue.GOAT';queue.write_bytes(queue.read_bytes().decode('utf-16').replace(';Pending_',';Completed_').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'report pair'):finish(c,'beta-job')
        self.assertTrue((base/'agent-native-control-owner.json').exists())

if __name__=='__main__':unittest.main()
