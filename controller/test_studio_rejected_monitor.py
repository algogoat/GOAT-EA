"""Real typed store/package/evidence with mocked OS effects, never native proof."""
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock,patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import operation
from studio_batch import prepare_batch
from studio_launch_intent import record_intent
from studio_rejected_monitor import proof,restart
from native_control_transaction import begin,NAMES
import test_studio_research_authority as fixtures


class RejectedMonitorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ResearchAuthorityTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.boot();self.c=self.fixture.c
        self.addCleanup(patch.stopall)
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
        self.base=Path(self.c.install['common_files_root'])/'GOAT'/('GOAT V'+self.c.install['ea_version']+'-'+self.c.session['account']['server'])
        self.base.mkdir(parents=True,exist_ok=True)
        begin(self.base,self.evidence,dict(zip(NAMES,[('[ActiveOptimizationRun]\r\nRunPath='+self.manifest['native_run_relative']+'\r\n').encode('utf-16'),b'config',b'guard'])),{n:None for n in NAMES},self.attempt)
        write_json(self.evidence/'activation.json',dict(stage='CONTROLS_INSTALLED_NOT_ARMED',attempt_id=self.attempt))
        self.issue(self.attempt,dict(request_id=self.attempt,action='start',terminal_id=self.c.terminal,run_id=self.c.run,job_id='original',generation=state['generation'],configuration_sha256=job['configuration_sha256'],expires_utc=1),'REQUEST_REJECTED')
        self.native=dict(process=dict(pid=44,created_utc='fixed'),demo=True,connected=True,algo_trading=False,positions=0,orders=0,account_matches=True,tester_state='idle')
        self.probe=patch('studio_rejected_monitor.inspect_idle_demo',return_value=self.native).start()

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
        process=Mock();suspend=Mock(return_value=dict(supervisor_exited=False,native_stop_claimed=False))
        self.probe.return_value=dict(self.native,demo=False)
        with self.assertRaisesRegex(ValueError,'SDK-confirmed'):restart(self.c,'original',process=process,suspend_fn=suspend)
        suspend.assert_not_called();process.close.assert_not_called()
        self.probe.return_value=self.native
        with self.assertRaisesRegex(ValueError,'publisher'):restart(self.c,'original',process=process,suspend_fn=suspend)
        process.close.assert_not_called()

    def test_single_normal_restart_preserves_draft_and_budget(self):
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
        process=Mock();process.inspect.return_value=None;process.start.return_value=self.native['process']
        suspend=Mock(return_value=dict(supervisor_exited=True,native_stop_claimed=False))
        with patch('studio_onboarding.verify_monitor_profile'),patch('studio_onboarding.saved_launch_policy'):
            result=restart(self.c,'original',process=process,suspend_fn=suspend)
            self.assertEqual(result['phase'],'reverified')
            self.assertEqual(draft.read_bytes(),b'{"retained":"real draft fixture"}')
            self.assertFalse(result['native_started']);self.assertFalse(result['grant_created'])
            with self.assertRaisesRegex(ValueError,'already recorded'):restart(self.c,'original',process=process,suspend_fn=suspend)
        process.close.assert_called_once_with(self.native['process']);process.start.assert_called_once_with(config)


if __name__=='__main__':unittest.main()
