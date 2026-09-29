"""First-member startup ordering, stop/binding refusal and real Windows report alias."""
from contextlib import nullcontext,ExitStack
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import Mock,patch
import studio_config_start as start
from studio_report_bridge import prepare,verify


class ConfigStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        c=types.SimpleNamespace(root=root,local=root/'local',terminal='terminal',run='run',schema={},
            session=dict(authority_kind='demo_direct',account=dict(login='123',server='Demo')))
        self.c=c;self.events=[];self.attempt='a'*64
        self.job=dict(job_id='batch',status='pending',configuration_sha256='frozen')
        self.state=dict(owner='agent',generation=2,revision=1,queue=[self.job])
        c.state=lambda:copy.deepcopy(self.state)
        c.job=lambda job_id:copy.deepcopy(self.state['queue'][0])
        c.bridge=types.SimpleNamespace(root=root/'bridge',pump=lambda:None)
        def execute(sql,values):
            if sql.startswith('UPDATE studio_queues'):self.state['queue']=json.loads(values[0])
            elif sql.startswith('UPDATE studio_state'):self.state['revision']+=1
            else:raise AssertionError(sql)
        c.store=types.SimpleNamespace(transaction=lambda:nullcontext(),db=types.SimpleNamespace(execute=execute))
        c.runtime=Mock();c.native_args=lambda:dict(account=c.session['account'],
            observation_path=c.local/'ui-observation.json',monitor_path=root/'monitor.ex5',
            monitor_sha256='binary',input_schema={})
        def submit(*args,**kwargs):
            self.events.append('reserve');self.state['queue'][0]['status']='reserved'
        c.submit=submit
        self.package=root/'packages/batch';self.package.mkdir(parents=True)
        self.binding=dict(research_terminal=str(root/'install/terminal64.exe'),research_data_root=str(root/'data'),
            report_location_bridge='installation_to_data_v1',startup_monitor={'bound':True},research_profile='GOAT-Studio-fixture')
        self.plan=dict(research_binding=self.binding)
        (self.package/'studio-plan.json').write_text(json.dumps(self.plan))
        (self.package/'manifest.json').write_text('{}')
        (root/'batch-drivers').mkdir()
        (root/'batch-drivers/batch.json').write_text(json.dumps(dict(deadline_wall=time.time()+600)))
        (c.local/'native-gate').mkdir(parents=True)
        raw=b'[Experts]\r\nEnabled=0\r\n[Tester]\r\nModel=1\r\nReport=owned.xml\r\n'
        self.material=dict(startup_raw=raw,startup_receipt={'sha256':hashlib.sha256(raw).hexdigest()},
                           manifest={'native_run_relative':r'GOAT\R123456789abc'})
        self.identity=dict(pid=11,executable=self.binding['research_terminal'],created_utc='2026-09-29T00:00:00Z')
        self.baseline=dict(research=self.identity,protected=None,observed_unix=time.time())
        self.process=Mock();self.process.inspect.return_value=self.identity
        def close(identity):self.events.append('close');self.process.inspect.return_value=None
        def launch(config):
            self.events.append('launch');self.assertEqual(config.read_bytes(),raw)
            return dict(pid=22,executable=self.binding['research_terminal'],created_utc='2026-09-29T01:00:00Z')
        self.process.close.side_effect=close;self.process.start.side_effect=launch
        def intent(*args,**kwargs):
            self.state['queue'][0].update(status='starting',launch_intent={'attempt_id':self.attempt})
            return {'attempt_id':self.attempt}
        def install(*args,**kwargs):
            self.events.append('install');kwargs['evidence'].mkdir()
            (root/'data/MQL5/Files/GOAT/R123456789abc/reports').mkdir(parents=True)
        def arm(*args,**kwargs):
            self.events.append('arm');kwargs['validate_native'](c.state(),c.job('batch'))
            return {'request_id':self.attempt}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        replacements=dict(guard_active_seed=Mock(),before_native_dispatch=Mock(),
            inspect_processes=Mock(return_value=self.baseline),revalidate_processes=Mock(),
            record_intent=Mock(side_effect=intent),validate_launch_material=Mock(return_value=self.material),
            _install_controls=Mock(side_effect=install),validate_restart_controls=Mock(return_value={}),
            publish_restart_arm=Mock(side_effect=arm),observe_dispatch=Mock(return_value=dict(
                status='receipt_observed',consumed=True,receipt={'status':'RESTART_ARMED_RECONCILE'})),
            validate_restart_material=Mock(return_value=self.material))
        self.mocks={name:self.stack.enter_context(patch.object(start,name,value)) for name,value in replacements.items()}

    def run_start(self):return start.start(self.c,'batch',expected_generation=2,process=self.process)

    def test_one_arm_close_config_launch_and_retained_phases(self):
        result=self.run_start()
        self.assertEqual(self.events,['reserve','install','arm','close','launch'])
        self.assertFalse(result['native_running_verified'])
        phases=[row['phase'] for row in self.c.job('batch')['restart_intent']['history']]
        self.assertEqual(phases,['prepared','controls_installed','close_issued','research_exited',
                                 'launch_issued','process_started_unverified'])
        with self.assertRaisesRegex(ValueError,'new pending'):self.run_start()
        self.process.start.assert_called_once()

    def test_refused_or_unconsumed_arm_never_closes_or_launches(self):
        self.mocks['observe_dispatch'].return_value['consumed']=False
        with self.assertRaisesRegex(ValueError,'arming refused'):self.run_start()
        self.process.close.assert_not_called();self.process.start.assert_not_called()

    def test_owner_stop_before_start_never_reserves(self):
        folder=self.c.root/'demo-agent';folder.mkdir();(folder/'STOP').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Owner STOP'):self.run_start()
        self.assertEqual(self.events,[])

    def test_elapsed_budget_never_reserves_or_launches(self):
        (self.c.root/'batch-drivers/batch.json').write_text(json.dumps(dict(deadline_wall=time.time()-1)))
        with self.assertRaisesRegex(ValueError,'deadline elapsed'):self.run_start()
        self.assertEqual(self.events,[])

    def test_report_bridge_refuses_unrelated_existing_folder_without_overwrite(self):
        target=self.c.root/'data/MQL5/Files/GOAT/R123456789abc';target.mkdir(parents=True)
        source=self.c.root/'install/MQL5/Files/GOAT/R123456789abc';source.mkdir(parents=True)
        evidence=source/'keep.xml';evidence.write_text('unrelated')
        with self.assertRaisesRegex(ValueError,'already exists'):prepare(self.binding,r'GOAT\R123456789abc')
        self.assertEqual(evidence.read_text(),'unrelated')

    def test_takeover_after_close_never_launches(self):
        def close(identity):
            self.process.inspect.return_value=None;self.state['owner']='human'
        self.process.close.side_effect=close
        with self.assertRaisesRegex(ValueError,'Ownership changed'):self.run_start()
        self.process.start.assert_not_called()

    def test_startup_drift_after_exit_never_launches(self):
        def validate(*args,**kwargs):return self.material|dict(startup_receipt={'sha256':'0'*64})
        self.mocks['validate_restart_material'].side_effect=validate
        with self.assertRaisesRegex(ValueError,'Startup bytes changed'):self.run_start()
        self.process.start.assert_not_called()

    def test_close_error_does_not_retry(self):
        self.process.close.side_effect=OSError('normal close failed')
        with self.assertRaisesRegex(OSError,'normal close failed'):self.run_start()
        with self.assertRaisesRegex(ValueError,'new pending'):self.run_start()
        self.process.close.assert_called_once();self.process.start.assert_not_called()

    def test_historical_package_requires_new_identity_before_reservation(self):
        self.plan['research_binding'].pop('startup_monitor')
        (self.package/'studio-plan.json').write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError,'Prepare a new'):self.run_start()
        self.assertEqual(self.events,[])

    def test_report_alias_makes_actual_installation_write_visible_in_data_root(self):
        target=self.c.root/'data/MQL5/Files/GOAT/R123456789abc'
        target.mkdir(parents=True)
        receipt=prepare(self.binding,r'GOAT\R123456789abc')
        (Path(receipt['path'])/'proof.xml').write_text('native report fixture')
        self.assertEqual((target/'proof.xml').read_text(),'native report fixture')
        verify(receipt)
        with self.assertRaisesRegex(ValueError,'already exists'):prepare(self.binding,r'GOAT\R123456789abc')


class ConfigMaterialTests(unittest.TestCase):
    def test_real_package_keeps_owned_profile_and_does_not_add_duplicate_monitor_chart(self):
        from test_studio_native_batch import NativeBatchTests
        from campaign_ledger import sha
        from prepare_native_campaign import prepare as package_prepare,native_run_relative
        from studio_native_request import _validate_material,ini_sections
        fixture=NativeBatchTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        c=fixture.c;plan=copy.deepcopy(fixture.plan)
        preset=Path(plan['research_binding']['research_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        preset.parent.mkdir(parents=True,exist_ok=True)
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))
        plan['research_binding'].update(research_profile='GOAT-Studio-existing',
            report_location_bridge='installation_to_data_v1',startup_monitor=dict(
                expert=plan['research_binding']['ea_relative_path'],preset=preset.name,
                preset_sha256=hashlib.sha256(preset.read_bytes()).hexdigest()))
        plan['native_batch']['run_relative']=native_run_relative(plan)
        plan_path=c.root/'config-plan.json';plan_path.write_text(json.dumps(plan))
        package=c.root/'packages/config-route'
        package_prepare(plan_path,c.root/'templates.sqlite',package)
        (package/'studio-plan.json').write_text(json.dumps(plan))
        job=c.job('beta-job');job['launch_intent'].update(package=str(package),
            package_sha256=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest())
        args=c.native_args();args.pop('observation_path')
        material=_validate_material(c.state(),job,**args)
        sections=ini_sections(material['startup_raw'])
        self.assertEqual(sections['Charts'],{'ProfileLast':'GOAT-Studio-existing'})
        self.assertEqual(sections['Experts'],{'Enabled':'0','AllowLiveTrading':'0'})
        self.assertEqual(sections['Tester']['Model'],'1')
        self.assertTrue(sections['Tester']['Report'].endswith('.xml'))
        self.assertNotIn('StartUp',sections)
        # A modified monitor preset is refused before launch, not trusted from its name.
        preset.write_bytes(b'Mode_Operation=0\n')
        with self.assertRaisesRegex(ValueError,'preset drift'):_validate_material(c.state(),job,**args)


if __name__=='__main__':unittest.main()
