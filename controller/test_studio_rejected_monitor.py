"""Real typed store/package/evidence with mocked OS effects, never native proof."""
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import time
import unittest
from unittest.mock import DEFAULT,Mock,patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import operation
from studio_batch import prepare_batch
from studio_launch_intent import record_intent
from studio_rejected_monitor import proof,restart,resume
from native_control_transaction import begin,NAMES
from studio_terminal_isolation import controller_base
import test_studio_research_authority as fixtures


class RejectedMonitorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ResearchAuthorityTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.boot();self.c=self.fixture.c
        self.addCleanup(patch.stopall)
        self.publishers=patch('studio_driver_suspend.processes',return_value=[]).start()
        patch('studio_rejected_monitor.OWNER_LOGIN',self.c.session['account']['login']).start()
        self.op=operation('research-monitor-restart');self.op.__enter__();self.addCleanup(self.op.__exit__,None,None,None)
        with operation('prepare-batch'):prepare_batch(self.c,'original',self.fixture.plan)
        self.package=self.c.root/'packages/original';self.manifest=read_json(self.package/'manifest.json')
        job=self.c.job('original');digest=hashlib.sha256((self.package/'manifest.json').read_bytes()).hexdigest()
        with operation('run-batch'):
            self.c.submit('queue.reserve',dict(job_id='original',configuration_sha256=job['configuration_sha256'],package_sha256=digest),'reserve')
        state=self.c.state()
        intent=record_intent(self.c.store,self.c.terminal,self.c.run,'original',self.package,actor='agent',revision=state['revision'],generation=state['generation'])
        self.attempt=intent['attempt_id'];self.gate=self.c.local/'native-gate'
        self.common=Path(self.c.install['common_files_root'])/self.manifest['native_run_relative'].replace('\\','/')
        shutil.copytree(self.package,self.common)
        for name in ('queue.GOAT','portfolio.goatbatch'):
            (self.common/name).write_bytes((self.package/name).read_bytes().decode('utf-16').replace(';Pending_',';Queued_',1).encode('utf-16'))
        for member in self.manifest['jobs']:
            (self.common/'inputs'/member['run_alias']/'config.ini').write_bytes((self.package/(member['run_alias']+'.ini')).read_bytes())
        self.evidence=self.c.root/'attempts'/self.attempt;self.evidence.parent.mkdir(exist_ok=True)
        self.base=controller_base(self.c)
        self.base.mkdir(parents=True,exist_ok=True)
        begin(self.base,self.evidence,dict(zip(NAMES,[('[ActiveOptimizationRun]\r\nRunPath='+self.manifest['native_run_relative']+'\r\n').encode('utf-16'),b'config',b'guard'])),{n:None for n in NAMES},self.attempt)
        write_json(self.evidence/'activation.json',dict(stage='CONTROLS_INSTALLED_NOT_ARMED',attempt_id=self.attempt))
        self.issue(self.attempt,dict(request_id=self.attempt,action='start',terminal_id=self.c.terminal,run_id=self.c.run,job_id='original',generation=state['generation'],configuration_sha256=job['configuration_sha256'],expires_utc=1),'REQUEST_REJECTED')
        self.native=dict(process=dict(pid=44,created_utc='fixed'),demo=True,connected=True,algo_trading=False,positions=0,orders=0,account_matches=True,tester_state='idle')
        self.probe=patch('studio_rejected_monitor.inspect_idle_demo',return_value=self.native).start()
        # R1: the pre-suspend proof is the EA's runtime sample plus the process inventory; never an SDK attach.
        self.runtime=patch.object(self.c,'runtime',return_value=(dict(runtime=dict(account_demo=True)),{})).start()
        self.resumed=Mock(return_value=dict(status='resumed',new_pids=dict(launcher=501,python=502)))

    def present_first(self,process,later=DEFAULT):
        """The monitor runs at the pre-suspend proof; every later inspection answers ``later`` (default: return_value)."""
        calls=[]
        def inspect():
            calls.append(1)
            if len(calls)==1:return self.native['process']
            if isinstance(later,BaseException):raise later
            return later
        process.inspect.side_effect=inspect

    def issue(self,identity,request,status):
        raw=(json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n').encode()
        write_json(self.gate/('issued-'+identity+'.json'),dict(request=request,request_sha256=hashlib.sha256(raw).hexdigest()))
        write_json(self.gate/('result-'+identity+'.json'),dict(request_id=identity,request_sha256=hashlib.sha256(raw).hexdigest(),status=status))
        (self.gate/'request.json').write_bytes(raw)
        return raw

    def test_proof_real_package_and_refusal_for_consumed_start_or_output(self):
        scope,job=proof(self.c,'original');self.assertEqual(job['job_id'],'original')
        consumed=self.gate/('consumed-'+self.attempt+'.json');consumed.write_bytes((self.gate/'request.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'consumed start'):proof(self.c,'original')
        consumed.unlink()
        extra=self.common/'checkpoint.bin';extra.write_bytes(b'work')
        with self.assertRaisesRegex(ValueError,'artifacts'):proof(self.c,'original')
        extra.unlink()
        cache=Path(self.c.install['terminal_data_root'])/'Tester/cache';cache.mkdir(parents=True)
        (cache/'result.opt').write_bytes(b'work')
        with self.assertRaisesRegex(ValueError,'Tester work'):proof(self.c,'original')

    def test_live_account_and_unstopped_publisher_refuse_before_close(self):
        # R1: the pre-suspend proof (runtime sample) refuses a non-demo terminal before anything is suspended.
        process=Mock();self.present_first(process);suspend=Mock(return_value=dict(supervisor_exited=False,native_stop_claimed=False))
        self.runtime.side_effect=ValueError('Runtime policy mismatch: account_demo')
        with self.assertRaisesRegex(ValueError,'account_demo'):restart(self.c,'original',process=process,suspend_fn=suspend,resume_fn=self.resumed)
        suspend.assert_not_called();process.close.assert_not_called();self.probe.assert_not_called()
        self.runtime.side_effect=None;self.present_first(process)
        with self.assertRaisesRegex(ValueError,'publisher'):restart(self.c,'original',process=process,suspend_fn=suspend,resume_fn=self.resumed)
        process.close.assert_not_called();self.resumed.assert_not_called()   # not verifiably stopped: never resumed blindly

    def test_failed_readback_after_suspend_resumes_the_publisher_then_refuses(self):
        # goatai#2350 6099078698 / 6101325773 (R1): the full SDK readback runs only after the suspension, under the terminal
        # lease. When it fails (here: not a demo) nothing is closed, the suspended publisher is resumed, and it refuses.
        from studio_terminal_lease import held
        process,suspend,config,draft=self.launch_fixture();order=[]
        suspend.side_effect=lambda c,job,folder:order.append('suspend') or dict(supervisor_exited=True,native_stop_claimed=False)
        def readback(c):
            order.append(('readback',held(self.c.root)))
            return dict(self.native,demo=False)
        self.probe.side_effect=readback
        self.resumed.side_effect=lambda c,job_id,folder:order.append(('resume',held(self.c.root))) or dict(new_pids=dict(launcher=501,python=502))
        with patch('studio_onboarding.verify_monitor_profile'),self.assertRaises(ValueError) as caught:
            restart(self.c,'original',process=process,suspend_fn=suspend,resume_fn=self.resumed)
        self.assertEqual(order,['suspend',('readback',True),('resume',False)],'no attach before suspending; resume after the lease is released')
        self.assertEqual((caught.exception.code,caught.exception.fields['publisher_resumed']),('MONITOR_RESTART_REFUSED',dict(launcher=501,python=502)))
        self.assertIn('SDK-confirmed same idle demo',str(caught.exception));self.assertIn('running again',str(caught.exception))
        self.resumed.assert_called_once()
        process.close.assert_not_called();process.start.assert_not_called()
        self.assertFalse(list((self.c.root/'rejected-monitor-restarts').rglob('restart.json')),'nothing recorded as issued')

    def test_a_failed_resume_is_the_answer_never_a_retry(self):
        from studio_refusal import Refusal
        process,suspend,config,draft=self.launch_fixture()
        self.probe.return_value=dict(self.native,algo_trading=True)
        self.resumed.side_effect=Refusal('could not restart that run; press Continue','PUBLISHER_RESUME_FAILED',job_id='original')
        with patch('studio_onboarding.verify_monitor_profile'),self.assertRaises(ValueError) as caught:
            restart(self.c,'original',process=process,suspend_fn=suspend,resume_fn=self.resumed)
        self.assertEqual(caught.exception.code,'PUBLISHER_RESUME_FAILED')
        self.resumed.assert_called_once();process.close.assert_not_called()

    def test_pending_real_human_takeover_is_processed_outside_gate_and_blocks_close(self):
        state=self.c.state()
        request=dict(schema_version=1,request_id='human-takeover-during-recovery',terminal_id=self.c.terminal,run_id=self.c.run,
                     expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
        write_json(self.c.bridge.root/'human/inbox/human-takeover-during-recovery.json',request)
        (self.c.root/'batch-driver-gate').mkdir(exist_ok=True)
        process=Mock();self.present_first(process);suspend=Mock(return_value=dict(supervisor_exited=True,native_stop_claimed=False))
        with self.assertRaisesRegex(ValueError,'revoked') as caught:
            restart(self.c,'original',process=process,suspend_fn=suspend,resume_fn=self.resumed)
        self.assertEqual(caught.exception.code,'MONITOR_RESTART_REFUSED');self.resumed.assert_called_once()   # R1
        with operation('state'):self.assertEqual(self.c.state()['owner'],'human')
        process.close.assert_not_called();process.start.assert_not_called()
        self.assertFalse(list((self.c.bridge.root/'human/processing').glob('*.json')))

    def launch_fixture(self):
        from studio_onboarding import monitor_chart
        profile=dict(profile_name='GOAT-Studio-fixture')
        write_json(self.c.root/'monitor-profile.json',profile)
        preset=Path(self.c.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        preset.write_bytes('Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16'))
        folder=self.c.root/'monitor-launches';folder.mkdir(exist_ok=True)
        config=folder/'original.ini'
        config.write_bytes(('[Charts]\r\nProfileLast=GOAT-Studio-fixture\r\n[Experts]\r\nEnabled=0\r\nAllowLiveTrading=0\r\n[StartUp]\r\nExpert='+self.c.install['ea_relative_path']+'\r\nExpertParameters='+preset.name+'\r\nPeriod=M1\r\n').encode('utf-16'))
        write_json(folder/'original.json',dict(pid=44,status='process_started_unverified',installation_sha256=sha(self.c.install),run_id=self.c.run,startup_config=str(config),startup_sha256=hashlib.sha256(config.read_bytes()).hexdigest()))
        draft=self.c.bridge.root/'human/ui-draft.json';draft.write_bytes(b'{"retained":"real draft fixture"}')
        driver_gate=self.c.root/'batch-driver-gate';driver_gate.mkdir(exist_ok=True)
        process=Mock();process.inspect.return_value=None;process.start.return_value=self.native['process'];self.present_first(process)
        suspend=Mock(return_value=dict(supervisor_exited=True,native_stop_claimed=False))
        return process,suspend,config,draft

    def test_single_normal_restart_preserves_draft_and_budget(self):
        process,suspend,config,draft=self.launch_fixture()
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'):
            result=restart(self.c,'original',process=process,suspend_fn=suspend)
            self.assertEqual(result['phase'],'reverified')
            self.assertEqual(draft.read_bytes(),b'{"retained":"real draft fixture"}')
            self.assertFalse(result['native_started']);self.assertFalse(result['grant_created'])
            with self.assertRaisesRegex(ValueError,'already recorded'):restart(self.c,'original',process=process,suspend_fn=suspend)
        process.close.assert_called_once_with(self.native['process']);process.start.assert_called_once_with(config)

    def retained_close(self):
        process,suspend,config,draft=self.launch_fixture()
        path=self.c.root/'batch-drivers/original.json';path.parent.mkdir(exist_ok=True);write_json(path,dict(deadline_wall=87400))
        evidence=dict(supervisor_exited=True,native_stop_claimed=False,journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        def suspension(c,job,folder):
            write_json(folder/'publisher-stopped.json',evidence)
            return evidence
        self.present_first(process,ValueError('Unknown terminal executable; exiting process fixture'))
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'),self.assertRaisesRegex(ValueError,'Unknown terminal'):
            restart(self.c,'original',process=process,suspend_fn=suspension,resume_fn=self.resumed)
        self.resumed.assert_not_called()                                      # a failure after the close never resumes
        process.inspect.side_effect=None;process.inspect.return_value=None
        process.close.assert_called_once();process.start.assert_not_called()
        return process,config,draft

    def test_exit_race_resumes_same_intent_without_second_close_or_launch(self):
        process,config,draft=self.retained_close()
        before=draft.read_bytes()
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'):
            result=resume(self.c,'original',process=process)
            self.assertEqual(result['phase'],'reverified')
            with self.assertRaisesRegex(ValueError,'never repeat'):resume(self.c,'original',process=process)
        self.assertEqual(draft.read_bytes(),before)
        process.close.assert_called_once();process.start.assert_called_once_with(config)

    def test_resume_refuses_present_monitor_and_changed_suspension_or_draft(self):
        process,config,draft=self.retained_close()
        process.inspect.return_value=self.native['process']
        with self.assertRaisesRegex(ValueError,'still present'):resume(self.c,'original',process=process)
        process.inspect.return_value=None;draft.write_bytes(b'changed retained draft')
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'),self.assertRaisesRegex(ValueError,'draft changed'):
            resume(self.c,'original',process=process)
        process.start.assert_not_called();process.close.assert_called_once()

    def test_lingering_serve_and_active_seed_refuse_before_first_relaunch(self):
        process,config,draft=self.retained_close()
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'):
            self.publishers.return_value=[dict(ProcessId=12345,ExecutablePath='old/python.exe',CommandLine='old serve')]
            with patch('studio_driver_suspend.arguments',return_value=['old','studio','--installation',str(self.c.root/'installation.json'),'serve']):
                with self.assertRaisesRegex(ValueError,'Another controller publisher'):
                    resume(self.c,'original',process=process)
            self.publishers.return_value=[]
            with patch('studio_seed_slot.guard_active_seed',side_effect=ValueError('active seed')):
                with self.assertRaisesRegex(ValueError,'active seed'):resume(self.c,'original',process=process)
        process.start.assert_not_called();process.close.assert_called_once()


if __name__=='__main__':unittest.main()
