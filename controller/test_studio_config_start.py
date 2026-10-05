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
        self.reserve_ids=[]
        def submit(*args,**kwargs):
            self.events.append('reserve');self.state['queue'][0]['status']='reserved'
            self.reserve_ids.append(args[2])
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
        self.arm_fields=dict(action='arm_restart',startup_sha256=hashlib.sha256(raw).hexdigest())
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
            return dict(self.arm_fields)
        def arm(*args,**kwargs):
            self.events.append('arm')
            fields=kwargs['validate_native'](c.state(),c.job('batch'))
            self.assertEqual(c.job('batch')['restart_intent']['arm_request_fields'],fields)
            return {'request_id':self.attempt}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        replacements=dict(guard_active_seed=Mock(),before_native_dispatch=Mock(),
            inspect_processes=Mock(return_value=self.baseline),revalidate_processes=Mock(side_effect=lambda binding,baseline:dict(baseline)),
            record_intent=Mock(side_effect=intent),validate_launch_material=Mock(return_value=self.material),
            _install_controls=Mock(side_effect=install),validate_restart_controls=Mock(side_effect=lambda *args,**kwargs:dict(self.arm_fields)),
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

    def test_refused_research_launch_is_launch_refused_and_retries_only_the_launch(self):
        # goatai#1885 PR E (Claude-Mac note 4): nothing ran, so the batch is not stranded at launch_issued.
        from studio_research_launch import ResearchLaunchRefused
        launch=self.process.start.side_effect
        def refuse(config):
            self.events.append('refused');raise ResearchLaunchRefused('MT5 was not started: no research job. Nothing ran.')
        self.process.start.side_effect=refuse
        with self.assertRaisesRegex(ResearchLaunchRefused,'Nothing ran'):self.run_start()
        intent=self.c.job('batch')['restart_intent']
        self.assertEqual(intent['phase'],'launch_refused');self.assertIn('no research job',intent['refusal'])
        recovery=start.restart_recovery(self.c.job('batch'))
        self.assertEqual(recovery['mt5'],'closed_not_reopened');self.assertIn('Nothing ran',recovery['plain'])
        self.assertIn('run-batch --resume',recovery['next_safe_action'])
        self.process.inspect.return_value=self.identity                   # an MT5 runs now: never launch again
        with self.assertRaisesRegex(ValueError,'running now'):start.retry_refused_launch(self.c,'batch',process=self.process)
        self.process.inspect.return_value=None
        with self.assertRaisesRegex(ResearchLaunchRefused,'Nothing ran'):start.retry_refused_launch(self.c,'batch',process=self.process)
        self.assertEqual(self.c.job('batch')['restart_intent']['phase'],'launch_refused')   # a second refusal returns there
        self.process.start.side_effect=launch
        result=start.retry_refused_launch(self.c,'batch',process=self.process)
        self.assertEqual(result['status'],'config_process_started_unverified')
        self.assertEqual([e for e in self.events if e!='sdk'],['reserve','install','arm','close','refused','refused','launch'])   # one close, one arm
        phases=[row['phase'] for row in self.c.job('batch')['restart_intent']['history']]
        self.assertEqual(phases[-5:],['launch_refused','launch_issued','launch_refused','launch_issued','process_started_unverified'])
        with self.assertRaisesRegex(ValueError,'Only a config start whose research launch was refused'):
            start.retry_refused_launch(self.c,'batch',process=self.process)

    def test_driver_resume_retries_only_a_refused_launch(self):
        from studio_batch_driver import _launch_refused
        controller=types.SimpleNamespace(retry_config_launch=Mock(),job=lambda job_id:dict(restart_intent=dict(phase='launch_refused')))
        self.assertTrue(_launch_refused(controller,'batch',dict(start_route='config_restart')))
        self.assertFalse(_launch_refused(controller,'batch',dict(start_route='in_place_start')))
        for other in ('launch_issued','launch_uncertain','process_started_unverified'):
            controller.job=lambda job_id,other=other:dict(restart_intent=dict(phase=other))
            self.assertFalse(_launch_refused(controller,'batch',dict(start_route='config_restart')),other)

    def test_uncertain_research_launch_is_launch_uncertain_and_never_retried(self):
        # Claude-Mac note 1 on the native first start: the refused, never-resumed MT5 was not confirmed gone.
        from studio_research_launch import ResearchLaunchUncertain
        def uncertain(config):
            self.events.append('uncertain');raise ResearchLaunchUncertain('could not confirm that the suspended MT5 (PID 22) stopped')
        self.process.start.side_effect=uncertain
        with self.assertRaises(ResearchLaunchUncertain):self.run_start()
        intent=self.c.job('batch')['restart_intent']
        self.assertEqual(intent['phase'],'launch_uncertain');self.assertIn('PID 22',intent['refusal'])
        recovery=start.restart_recovery(self.c.job('batch'))
        self.assertEqual(recovery['mt5'],'suspended_uncertain');self.assertIn('never resumed',recovery['plain'])
        self.assertIn('do not retry',recovery['next_safe_action'])
        self.process.inspect.return_value=None
        with self.assertRaisesRegex(ValueError,'Only a config start whose research launch was refused'):
            start.retry_refused_launch(self.c,'batch',process=self.process)
        self.assertEqual(self.events.count('uncertain'),1)

    def test_unseen_startup_identity_stays_launch_issued_like_163(self):
        # GOAT-EA#163: a launch whose identity was never seen may be running; it is observed, never retried.
        from studio_seed_process import STARTUP_UNSEEN
        def unseen(config):
            self.events.append('launch');raise ValueError(STARTUP_UNSEEN+' in 90 s; inspect before recovery')
        self.process.start.side_effect=unseen
        with self.assertRaisesRegex(ValueError,STARTUP_UNSEEN):self.run_start()
        self.assertEqual(self.c.job('batch')['restart_intent']['phase'],'launch_issued')
        self.assertEqual(start.restart_recovery(self.c.job('batch'))['mt5'],'reopen_uncertain')
        with self.assertRaisesRegex(ValueError,'Only a config start whose research launch was refused'):
            start.retry_refused_launch(self.c,'batch',process=self.process)


    def test_a_retried_start_reserves_under_a_fresh_command_id(self):
        archive=self.c.root/'batch-driver-refusals';archive.mkdir()
        (archive/'batch.refused-1.json').write_text('{}')
        self.run_start()
        self.assertEqual(self.reserve_ids,['batch-reserve-r1'])

    def test_runtime_sample_may_lag_arm_receipt_without_repeating_command(self):
        self.c.runtime.side_effect=[None,ValueError('Runtime policy mismatch: batch_ongoing'),None]
        self.run_start()
        self.assertEqual(self.events.count('arm'),1)
        self.process.close.assert_called_once();self.process.start.assert_called_once()

    def test_other_runtime_mismatch_is_not_retried_or_closed(self):
        self.c.runtime.side_effect=[None,ValueError('Runtime account mismatch')]
        with self.assertRaisesRegex(ValueError,'account mismatch'):self.run_start()
        self.process.close.assert_not_called();self.process.start.assert_not_called()

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
    def test_real_arm_transport_uses_the_retained_installed_fields(self):
        from test_goat_studio import PortableControllerTests
        from studio_dispatch_transport import publish_restart_arm
        from campaign_ledger import packed
        fixture=PortableControllerTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        c,_,_,_=fixture.activated_fixture()
        state=c.state();job=state['queue'][0];attempt=job['launch_intent']['attempt_id']
        fields=dict(action='arm_restart',startup_sha256='a'*64,native_config_sha256='b'*64)
        job['restart_intent']=dict(phase='controls_installed',attempt_id=attempt,
            startup_sha256=fields['startup_sha256'],arm_request_fields=dict(fields))
        c.store.db.execute('UPDATE studio_queues SET jobs=?',(packed(state['queue']),))
        arguments=dict(actor='agent',revision=state['revision'],generation=state['generation'])
        with self.assertRaisesRegex(ValueError,'differ from installed attempt'):
            publish_restart_arm(c.store,c.terminal,c.run,job['job_id'],c.bridge.root,
                validate_native=lambda *args:fields|{'native_config_sha256':'c'*64},**arguments)
        self.assertFalse((c.local/'native-gate/permit.json').exists())
        result=publish_restart_arm(c.store,c.terminal,c.run,job['job_id'],c.bridge.root,
            validate_native=lambda *args:dict(fields),**arguments)
        self.assertEqual(result['status'],'arm_published_not_confirmed')
        issued=json.loads((c.local/'native-gate'/('issued-'+attempt+'.json')).read_text())
        self.assertEqual(issued['request']['action'],'arm_restart')
        self.assertEqual(issued['request']['native_config_sha256'],fields['native_config_sha256'])
        self.assertTrue((c.local/'native-gate/permit.json').is_file())
        with self.assertRaisesRegex(Exception,'Existing publication'):
            publish_restart_arm(c.store,c.terminal,c.run,job['job_id'],c.bridge.root,
                validate_native=lambda *args:dict(fields),**arguments)

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


class DriverRefusedLaunchTests(unittest.TestCase):
    """run-batch --resume retries only a refused /config research launch (goatai#1885 PR E)."""

    def setUp(self):
        import test_studio_batch_driver as fixtures
        from studio_bridge import write_json
        self.fixture=fixtures.BatchDriverTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c=self.fixture.c
        self.c.session['authority_kind']='demo_direct';write_json(self.c.root/'session.json',self.c.session)
        self.c.bridge=types.SimpleNamespace(root=self.c.local/self.c.run)
        self.retries=[]

    def refuse(self,job_id,*,expected_generation,on_attempt):
        from studio_research_launch import ResearchLaunchRefused
        self.c.start(job_id,expected_generation=expected_generation)
        on_attempt(self.c.current['launch_intent'])
        self.c.current['restart_intent']=dict(phase='launch_refused',attempt_id='a'*64)
        raise ResearchLaunchRefused('MT5 was not started: no research job. Nothing ran.')

    def test_resume_retries_the_refused_launch_once_then_observes(self):
        self.c.start_config=self.refuse
        first=self.fixture.drive(max_seconds=3)
        self.assertEqual((first['status'],first['recovery']['phase']),('start_uncertain','launch_refused'))
        def retry(job_id):
            self.retries.append(job_id);self.c.current['restart_intent']['phase']='process_started_unverified'
            self.c.finished=True
        self.c.retry_config_launch=retry
        resumed=self.fixture.drive(resume=True)
        self.assertEqual((resumed['status'],resumed['stopped']),('completed',True))
        self.assertEqual((self.c.starts,self.retries),(1,['batch']))           # one start, one launch retry
        self.fixture.drive(resume=True)
        self.assertEqual(self.retries,['batch'])                               # a stopped journal never retries

    def test_a_second_refusal_keeps_the_journal_resumable(self):
        from studio_research_launch import ResearchLaunchRefused
        self.c.start_config=self.refuse
        self.fixture.drive(max_seconds=3)
        def refuse_again(job_id):
            self.retries.append(job_id);raise ResearchLaunchRefused('still no research job. Nothing ran.')
        self.c.retry_config_launch=refuse_again
        again=self.fixture.drive(resume=True)
        self.assertEqual((again['status'],again['stopped'],again['recovery']['phase']),('start_uncertain',False,'launch_refused'))
        self.assertIn('still no research job',again['last_error'])

    def test_an_unconfirmed_launch_is_never_retried(self):
        def unconfirmed(job_id,*,expected_generation,on_attempt):
            self.c.start(job_id,expected_generation=expected_generation)
            on_attempt(self.c.current['launch_intent'])
            self.c.current['restart_intent']=dict(phase='launch_issued',attempt_id='a'*64)
            raise ValueError('Terminal startup identity not observed in 90 s; inspect before recovery')
        self.c.start_config=unconfirmed
        self.fixture.drive(max_seconds=3)
        self.c.retry_config_launch=lambda job_id:self.retries.append(job_id)
        self.fixture.drive(resume=True)
        self.assertEqual(self.retries,[])


if __name__=='__main__':unittest.main()
