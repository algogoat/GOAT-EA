"""Real controller/file transitions with mocked native effects, not native QA."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from campaign_ledger import packed, sha
from native_control_transaction import begin, NAMES
from studio_bridge import write_json
from studio_installation import read_json
from studio_launch_intent import record_intent
from studio_self_repair import repair, original_receipt
import test_studio_batch as fixtures


class SelfRepairFixture(unittest.TestCase):
    """Shared real-controller fixture: one reserved, controls-installed attempt; no tests."""
    def setUp(self):
        self.f = fixtures.NativeBatchTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.c = self.f.controller
        self.f.prepare('original')
        job = self.c.job('original'); self.package = self.c.root/'packages/original'
        self.manifest = read_json(self.package/'manifest.json')
        package_hash = hashlib.sha256((self.package/'manifest.json').read_bytes()).hexdigest()
        self.c.submit('queue.reserve',dict(job_id='original',configuration_sha256=job['configuration_sha256'],package_sha256=package_hash),'reserve')
        state = self.c.state()
        intent = record_intent(self.c.store,self.c.terminal,self.c.run,'original',self.package,actor='agent',revision=state['revision'],generation=state['generation'])
        self.attempt = intent['attempt_id']; self.gate = self.c.local/'native-gate'
        self.common = Path(self.c.install['common_files_root'])/self.manifest['native_run_relative'].replace('\\','/')
        shutil.copytree(self.package,self.common)
        for name in ('queue.GOAT','portfolio.goatbatch'):
            (self.common/name).write_bytes((self.package/name).read_bytes().decode('utf-16').replace(';Pending_',';Queued_',1).encode('utf-16'))
        for item in self.manifest['jobs']:
            (self.common/'inputs'/item['run_alias']/'config.ini').write_bytes((self.package/(item['run_alias']+'.ini')).read_bytes())
        self.evidence = self.c.root/'attempts'/self.attempt
        self.base = Path(self.c.install['common_files_root'])/'GOAT'/('GOAT V'+self.c.install['ea_version']+'-'+self.c.session['account']['server'])
        self.base.mkdir(parents=True,exist_ok=True)
        begin(self.base,self.evidence,dict(zip(NAMES,[b'pointer',b'config',b'guard'])),{n:None for n in NAMES},self.attempt)
        write_json(self.evidence/'activation.json',dict(stage='CONTROLS_INSTALLED_NOT_ARMED',attempt_id=self.attempt))
        fields = dict(terminal_id=self.c.terminal,run_id=self.c.run,job_id='original',generation=state['generation'],
                      configuration_sha256=job['configuration_sha256'],expires_utc=1,owner='agent',
                      data_path=self.c.install['terminal_data_root'],installation_path=str(Path(self.c.install['terminal_executable']).parent),
                      account_login=self.c.session['account']['login'],account_server=self.c.session['account']['server'],
                      native_run=self.manifest['native_run_relative'],
                      pointer_sha256=hashlib.sha256((self.base/NAMES[0]).read_bytes()).hexdigest(),
                      native_owner_sha256=hashlib.sha256((self.base/'agent-native-control-owner.json').read_bytes()).hexdigest())
        self.issue(self.attempt,fields|dict(request_id=self.attempt,action='start'))
        self.cancel = sha([self.attempt,'cancel'])
        self.issue(self.cancel,fields|dict(request_id=self.cancel,attempt_id=self.attempt,action='cancel'))
        issued = read_json(self.gate/('issued-'+self.cancel+'.json'))
        write_json(self.gate/'permit.json',dict(request_sha256=issued['request_sha256']))
        self.native = dict(process=dict(pid=44,created_utc='fixed'),demo=True,connected=True,algo_trading=False,
                           positions=0,orders=0,account_matches=True,tester_state='idle')
        self.current = self.native['process']
        self.process = Mock(); self.process.inspect.side_effect = lambda:self.current
        self.process.close.side_effect = lambda identity:setattr(self,'current',None)
        self.addCleanup(patch.stopall)
        patch('studio_self_repair.inspect_idle_demo',return_value=self.native).start()
        patch('studio_driver_suspend.processes',return_value=[]).start()
        patch('demo_agent.DemoAgent._exclusive',return_value=nullcontext()).start()
        self.action = str(uuid.uuid4()); self.queue_raw = (self.common/'queue.GOAT').read_bytes()
        self.before = self.c.job('original')

    def issue(self, identity, request):
        raw = (json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n').encode()
        h = hashlib.sha256(raw).hexdigest()
        write_json(self.gate/('issued-'+identity+'.json'),dict(request=request,request_sha256=h))
        write_json(self.gate/('result-'+identity+'.json'),dict(request_id=identity,request_sha256=h,status='REQUEST_REJECTED'))
        (self.gate/'request.json').write_bytes(raw)

    def run_repair(self):
        return repair(self.f.fixture.path,'original',self.action,linked_login=self.c.session['account']['login'],controller=self.c,process=self.process)

    def assert_refused(self, reason):
        result = self.run_repair()
        self.assertEqual(result['status'],'refused',result)
        self.assertIn(reason,result['local_reason'])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()
        self.assertEqual(self.c.job('original'),self.before)
        self.assertTrue((self.gate/'request.json').exists())


class SelfRepairTests(SelfRepairFixture):
    def test_rejected_never_started_retirement_preserves_queue_grant_and_receipts(self):
        grant_before = self.c.state()['generation']
        result = self.run_repair()
        self.assertEqual(result['status'],'repaired_terminal_stopped',result)
        self.assertFalse(result['native_qualification']); self.assertFalse(result['native_cancellation_claimed'])
        self.assertEqual(result['cancel_evidence'],'rejected')
        self.assertEqual(self.c.job('original')['completion']['executed_members'],0)
        self.assertEqual(self.c.state()['generation'],grant_before)
        self.assertEqual(self.c.state()['owner'],'agent')
        self.assertEqual((self.common/'queue.GOAT').read_bytes(),self.queue_raw)
        self.assertFalse((self.gate/'request.json').exists()); self.assertFalse((self.gate/'permit.json').exists())
        self.assertTrue((self.gate/('issued-'+self.attempt+'.json')).exists())
        self.assertFalse((self.gate/('consumed-'+self.attempt+'.json')).exists())
        self.assertFalse(any((self.base/n).exists() for n in NAMES))
        self.process.close.assert_called_once_with(self.native['process']);self.process.start.assert_not_called()
        self.assertEqual(self.run_repair(),result)
        self.process.close.assert_called_once()

    def test_absent_cancel_result_is_not_zero_execution_proof(self):
        (self.gate/('result-'+self.cancel+'.json')).unlink()
        self.assert_refused('cancel rejection')

    def test_expired_unconsumed_start_and_cancel_without_permit_retire_never_started(self):
        for identity in (self.attempt,self.cancel):
            (self.gate/('result-'+identity+'.json')).unlink()
        (self.gate/'permit.json').unlink()
        original_request=(self.gate/'request.json').read_bytes()
        result=self.run_repair()
        self.assertEqual(result['status'],'repaired_terminal_stopped',result)
        self.assertEqual(result['cancel_evidence'],'expired_unconsumed')
        self.assertEqual(self.c.job('original')['completion']['classification'],'retired_never_started')
        self.assertEqual(self.c.job('original')['completion']['executed_members'],0)
        folder=self.c.root/'self-repair'/self.action
        self.assertEqual((folder/'request-before.json').read_bytes(),original_request)
        self.assertEqual(read_json(folder/'transaction.json')['cancel_evidence'],'expired_unconsumed')
        self.assertFalse((self.gate/'request.json').exists())
        self.assertEqual((self.common/'queue.GOAT').read_bytes(),self.queue_raw)
        self.assertFalse(any((self.base/n).exists() for n in NAMES))
        self.process.close.assert_called_once();self.process.start.assert_not_called()
        self.assertEqual(self.run_repair(),result)

    def test_unexpired_unconsumed_cancel_without_permit_refuses(self):
        issued=read_json(self.gate/('issued-'+self.cancel+'.json'))
        self.issue(self.cancel,issued['request']|dict(expires_utc=time.time()+3600))
        (self.gate/('result-'+self.cancel+'.json')).unlink()
        (self.gate/'permit.json').unlink()
        self.assert_refused('cancel rejection')

    def test_consumed_cancel_without_receipt_or_permit_refuses(self):
        (self.gate/('result-'+self.cancel+'.json')).unlink()
        (self.gate/'permit.json').unlink()
        (self.gate/('consumed-'+self.cancel+'.json')).write_bytes((self.gate/'request.json').read_bytes())
        self.assert_refused('cancel rejection')

    def test_expired_unconsumed_start_without_cancel_proof_stays_rejected_only(self):
        (self.gate/('result-'+self.attempt+'.json')).unlink()
        (self.gate/'permit.json').unlink()
        self.assert_refused('REQUEST_REJECTED')

    def test_consumed_start_refuses(self):
        issued = read_json(self.gate/('issued-'+self.attempt+'.json'))
        (self.gate/('consumed-'+self.attempt+'.json')).write_bytes((json.dumps(issued['request'],ensure_ascii=False,allow_nan=False)+'\n').encode())
        self.assert_refused('consumed start')

    def test_native_start_intent_refuses_even_without_consumption(self):
        write_json(self.gate/('start-intent-'+self.attempt+'.json'),dict(attempt=self.attempt))
        self.assert_refused('execution outcome is uncertain')

    def test_native_output_refuses(self):
        (self.common/'work.bin').write_bytes(b'native output')
        self.assert_refused('artifacts')

    def test_foreign_permit_refuses(self):
        write_json(self.gate/'permit.json',dict(request_sha256='f'*64))
        self.assert_refused('Permit differs')

    def test_changed_current_request_bytes_refuse_even_if_json_is_equivalent(self):
        target=self.gate/'request.json';target.write_bytes(target.read_bytes()+b'\n')
        self.assert_refused('cancel rejection')

    def test_live_sdk_refuses_before_projection_or_close(self):
        with patch('studio_self_repair.inspect_idle_demo',return_value=self.native|dict(demo=False)):
            self.assert_refused('SDK-confirmed')

    def test_human_stop_is_retained(self):
        stop = self.c.root/'demo-agent/STOP';stop.parent.mkdir();stop.write_text('human stop')
        self.assert_refused('Owner STOP')
        self.assertEqual(stop.read_text(),'human stop')

    def test_pending_human_control_refuses(self):
        write_json(self.c.bridge.root/'human/inbox/take.json',{'command':'control.takeover'})
        self.assert_refused('Pending human')

    def test_low_disk_refuses(self):
        with patch('studio_self_repair.shutil.disk_usage',return_value=SimpleNamespace(free=4*1024**3)):
            self.assert_refused('5 GiB')

    def test_close_uncertainty_is_not_retried_and_support_payload_has_no_paths(self):
        self.process.close.side_effect = ValueError('C:/secret/account detail')
        result = self.run_repair()
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('secret',json.dumps(result['repair']))
        self.current = {'pid':45}
        again = self.run_repair()
        self.assertEqual(again['status'],'failed')
        self.process.close.assert_called_once()
        self.assertTrue((self.gate/'request.json').exists())

    def test_interrupted_restoration_resumes_without_second_close(self):
        from studio_self_repair import write_json as real
        def interrupt(path,value):
            if path.name == 'transaction.json' and value.get('phase') == 'controls_restored':
                raise OSError('interrupted after restore')
            return real(path,value)
        with patch('studio_self_repair.write_json',side_effect=interrupt):
            self.assertEqual(self.run_repair()['status'],'failed')
        self.assertEqual(self.run_repair()['status'],'repaired_terminal_stopped')
        self.process.close.assert_called_once(); self.process.start.assert_not_called()

    def test_support_payload_normalizes_against_server_contract(self):
        result = self.run_repair()
        for payload in (result['repair'],repair(self.f.fixture.path,'original',str(uuid.uuid4()),linked_login=self.c.session['account']['login'],controller=self.c,process=self.process)['repair']):
            self.assertEqual(set(payload),{'schemaVersion','tool','versions','outcome','summary','observed','changes','before','after','nativeAction'})
            self.assertNotIn(str(self.f.root),json.dumps(payload))
            self.assertEqual(payload['tool'],'studio.self-repair')
            self.assertLessEqual(len(payload['changes']),20)
            self.assertLessEqual(len(payload['summary']),600)
            for change in payload['changes']:
                self.assertFalse(Path(change['target']).is_absolute())
                self.assertNotIn('..',change['target'])
                for field in ('beforeSha256','afterSha256'):
                    if change[field] is not None:self.assertRegex(change[field],r'^[a-f0-9]{64}$')

    def test_takeover_between_close_and_restore_refuses_without_faking_settlement(self):
        old_close = self.process.close.side_effect
        def close(identity):
            old_close(identity)
            # Native gate is held; represent a committed ownership change from
            # a prior human operation observed at the next database boundary.
            self.c.store.db.execute('UPDATE studio_state SET generation=generation+1')
        self.process.close.side_effect = close
        result = self.run_repair()
        self.assertEqual(result['status'],'failed')
        self.assertFalse((self.evidence/'result.json').exists())

    def test_exact_same_ea_predecessor_selection_and_changed_receipt_refusal(self):
        path = self.f.fixture.path
        old = read_json(path); old['bundle_version']='0.5.0-beta.7';write_json(path,old)
        self.c.session['installation_sha256']=sha(old);write_json(self.c.root/'session.json',self.c.session)
        backup = self.c.root/'ea-update-backups/update-one';backup.mkdir(parents=True)
        write_json(backup/'installation.json',old)
        newer = old|dict(bundle_version='0.5.0-beta.10',installed_at='2026-09-29T19:46:08Z')
        write_json(path,newer)
        previous,current = original_receipt(path)
        self.assertEqual(previous,backup/'installation.json')
        self.assertEqual(current,newer)
        write_json(path,newer|dict(catalog_root=str(self.f.root/'foreign')))
        with self.assertRaisesRegex(ValueError,'changed EA bytes'):original_receipt(path)

    def test_caller_linked_login_mismatch_refuses_before_native_effect(self):
        result = repair(self.f.fixture.path,'original',self.action,linked_login='999999',controller=self.c,process=self.process)
        self.assertEqual(result['status'],'refused')
        self.assertIn('Caller-linked login',result['local_reason'])
        self.process.close.assert_not_called(); self.process.start.assert_not_called()

    def test_changed_retained_outcome_refuses_without_another_close(self):
        self.assertEqual(self.run_repair()['status'],'repaired_terminal_stopped')
        path=self.c.root/'self-repair'/self.action/'outcome.json'
        outcome=read_json(path);outcome['repair']['summary']='changed';write_json(path,outcome)
        self.assertEqual(self.run_repair()['status'],'failed')
        self.process.close.assert_called_once();self.process.start.assert_not_called()

    def test_pending_update_refuses_without_touching_original_transport(self):
        write_json(self.c.root/'ea-update.pending.json',dict(interrupted=True))
        self.assert_refused('Interrupted desktop EA update')

    def test_physical_ea_drift_refuses_before_native_action(self):
        binary=Path(self.c.install['terminal_data_root'])/'MQL5/Experts'/self.c.install['ea_relative_path'].replace('\\','/')
        binary.write_bytes(b'different EA')
        self.assert_refused('Physical EA changed')

    def test_restored_transaction_with_retained_owner_marker_resumes_cleanup(self):
        from studio_self_repair import write_json as real
        def interrupt(path,value):
            if path.name == 'transaction.json' and value.get('phase') == 'controls_restored':
                # Represents interruption after the restore receipt but before
                # marker retirement. Replay must verify and retire this owner.
                write_json(self.base/'agent-native-control-owner.json',dict(owner=self.attempt,evidence=str(self.evidence)))
                raise OSError('marker cleanup interrupted')
            return real(path,value)
        with patch('studio_self_repair.write_json',side_effect=interrupt):
            self.assertEqual(self.run_repair()['status'],'failed')
        self.assertTrue((self.base/'agent-native-control-owner.json').exists())
        self.assertEqual(self.run_repair()['status'],'repaired_terminal_stopped')
        self.assertFalse((self.base/'agent-native-control-owner.json').exists())
        self.process.close.assert_called_once()



class RefusedRestartStartTests(SelfRepairFixture):
    """Jan df1c3c7d: a config restart-arm start the EA refused before consuming it."""
    def setUp(self):
        super().setUp()
        self.make_restart()

    def make_restart(self, status='START_PROTOCOL_NOT_QUALIFIED', cancel=False):
        job = self.c.job('original')
        self.startup = 'e'*64
        job['restart_intent'] = dict(attempt_id=self.attempt, phase='controls_installed', startup_sha256=self.startup,
                                     history=[dict(phase='prepared', at=1.0), dict(phase='controls_installed', at=2.0)])
        self.store_job(job)
        start = read_json(self.gate/('issued-'+self.attempt+'.json'))['request']
        for identity in (self.attempt, self.cancel):
            for prefix in ('issued-', 'result-'): (self.gate/(prefix+identity+'.json')).unlink(missing_ok=True)
        (self.gate/'permit.json').unlink(missing_ok=True)
        if cancel:
            self.issue(self.cancel, start|dict(request_id=self.cancel, attempt_id=self.attempt, action='cancel'))
        self.issue(self.attempt, start|dict(action='arm_restart', startup_sha256=self.startup), status=status)
        self.permit_for(self.attempt)
        self.before = self.c.job('original')

    def store_job(self, job):
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed([job]), binding))
        self.c.store.db.execute('UPDATE studio_state SET revision=revision+1 WHERE binding=?', (binding,))
        self.c.store.db.commit()

    def permit_for(self, identity):
        issued = read_json(self.gate/('issued-'+identity+'.json'))
        write_json(self.gate/'permit.json', dict(request_sha256=issued['request_sha256']))

    def issue(self, identity, request, status='REQUEST_REJECTED'):
        super().issue(identity, request)
        result = read_json(self.gate/('result-'+identity+'.json'))
        write_json(self.gate/('result-'+identity+'.json'), result|dict(status=status))

    def set_arm_status(self, status):
        result = read_json(self.gate/('result-'+self.attempt+'.json'))
        write_json(self.gate/('result-'+self.attempt+'.json'), result|dict(status=status))

    def test_refused_restart_arm_retires_never_started_and_says_so_plainly(self):
        grant_before = self.c.state()['generation']
        result = self.run_repair()
        self.assertEqual(result['status'], 'repaired_terminal_stopped', result)
        self.assertEqual(result['cancel_evidence'], 'refused:START_PROTOCOL_NOT_QUALIFIED')
        self.assertFalse(result['research_started']); self.assertFalse(result['native_cancellation_claimed'])
        self.assertIn('refused before it ran', result['repair']['summary'])
        self.assertIn('any stop you set is still in place', result['repair']['summary'])
        self.assertNotIn('started again', result['repair']['summary'])
        completion = self.c.job('original')['completion']
        self.assertEqual((completion['classification'], completion['executed_members']), ('retired_never_started', 0))
        self.assertEqual(self.c.state()['generation'], grant_before)
        self.assertEqual((self.common/'queue.GOAT').read_bytes(), self.queue_raw)
        self.assertFalse(any((self.base/n).exists() for n in NAMES))
        self.assertFalse((self.gate/'request.json').exists()); self.assertFalse((self.gate/'permit.json').exists())
        for prefix in ('issued-', 'result-'): self.assertTrue((self.gate/(prefix+self.attempt+'.json')).exists())
        self.assertFalse((self.gate/('consumed-'+self.attempt+'.json')).exists())
        self.process.close.assert_called_once_with(self.native['process']); self.process.start.assert_not_called()
        self.assertEqual(self.run_repair(), result)                      # replay-safe: no second close
        self.process.close.assert_called_once()

    def test_every_pre_consumption_refusal_is_accepted(self):
        from studio_self_repair import PRE_CONSUMPTION_REFUSALS, _proof
        for status in sorted(PRE_CONSUMPTION_REFUSALS):
            with self.subTest(status):
                self.set_arm_status(status)
                _, evidence = _proof(self.c, self.c.job('original'))
                self.assertEqual(evidence, 'refused:'+status)

    def test_a_success_or_unknown_receipt_is_not_a_refusal(self):
        for status in ('RESTART_ARMED_RECONCILE', 'START_SENT', 'SOMETHING_NEW',
                       'HUMAN_CANCEL_RETAINED', 'NATIVE_CONTROL_DRIFT'):
            with self.subTest(status):
                self.set_arm_status(status)
                self.assert_refused('pre-consumption refusal')

    def test_consumed_arm_refuses(self):
        (self.gate/('consumed-'+self.attempt+'.json')).write_bytes((self.gate/'request.json').read_bytes())
        self.assert_refused('consum')

    def test_arm_intent_refuses(self):
        (self.gate/('arm-intent-'+self.attempt+'.json')).write_text('{}')
        self.assert_refused('arm intent')

    def test_unexpired_refused_request_refuses(self):
        issued = read_json(self.gate/('issued-'+self.attempt+'.json'))
        self.issue(self.attempt, issued['request']|dict(expires_utc=time.time()+3600), status='START_PROTOCOL_NOT_QUALIFIED')
        self.permit_for(self.attempt)
        self.assert_refused('expired restart attempt')

    def test_rejected_cancel_alongside_refusal_is_accepted(self):
        self.make_restart(cancel=True)
        result = self.run_repair()
        self.assertEqual(result['status'], 'repaired_terminal_stopped', result)

    def test_consumed_cancel_refuses(self):
        self.make_restart(cancel=True)
        stop = read_json(self.gate/('issued-'+self.cancel+'.json'))['request']
        (self.gate/('consumed-'+self.cancel+'.json')).write_bytes((json.dumps(stop, ensure_ascii=False, allow_nan=False)+'\n').encode())
        self.assert_refused('cancel')

    def test_native_output_refuses_on_restart_route(self):
        (self.common/'work.bin').write_bytes(b'native output')
        self.assert_refused('artifacts')

    def test_start_action_with_restart_intent_refuses(self):
        issued = read_json(self.gate/('issued-'+self.attempt+'.json'))
        self.issue(self.attempt, issued['request']|dict(action='start'), status='START_PROTOCOL_NOT_QUALIFIED')
        self.permit_for(self.attempt)
        self.assert_refused('Refused start differs')

    def test_drifted_frozen_configuration_refuses_on_restart_route(self):
        job = self.c.job('original')
        job['configuration'] = job['configuration'] | dict(drifted=True)   # digest field left as frozen
        self.store_job(job); self.before = self.c.job('original')
        # The queue guard refuses first; the proof's own digest check is defence in depth.
        self.assert_refused('configuration')
        from studio_self_repair import _refused_restart_proof
        with self.assertRaisesRegex(ValueError, 'frozen digest'):
            _refused_restart_proof(self.c, self.c.job('original'), self.c.state())

    def test_changed_current_request_bytes_refuse_on_restart_route(self):
        raw = (self.gate/'request.json').read_bytes()
        (self.gate/'request.json').write_bytes(json.dumps(json.loads(raw), indent=2).encode())
        self.assert_refused('request bytes')

    def test_owned_report_junction_is_retired_with_the_frozen_run(self):
        bridge = dict(kind='owned_run_junction', path='C:/install/MQL5/Files/GOAT/R000000000000',
                      target='C:/data/MQL5/Files/GOAT/R000000000000')
        job = self.c.job('original'); job['restart_intent']['report_bridge'] = bridge
        self.store_job(job); self.before = self.c.job('original')
        plan = read_json(self.package/'studio-plan.json')
        with patch('studio_report_bridge.retire') as retire:
            result = self.run_repair()
        self.assertEqual(result['status'], 'repaired_terminal_stopped', result)
        retire.assert_called_once()
        self.assertEqual(retire.call_args.args[:3], (plan['research_binding'], self.manifest['native_run_relative'], bridge))

if __name__ == '__main__': unittest.main()
