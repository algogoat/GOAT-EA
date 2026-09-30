"""Stopped cleanup source fixtures; no installed terminal or human action is used."""
import json
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from studio_bridge import write_json
from studio_installation import read_json
from studio_orphan_rejection import reconcile_rejection
from studio_process_check import classify_processes
import studio_orphan_stopped as stopped
import studio_orphan_rejection as settlement
import test_studio_orphan_rejection as fixtures


class StoppedRejectionTests(fixtures.ReviewRejectedRecoveryTests):
    inspection_module=stopped
    inspection_name='inspect_local'
    cli_flags=['--terminal-stopped']
    initial_missing_permit_supported=True

    def setUp(self):
        super().setUp()
        self.processes=[]
        def inventory(binding,*,research_running,absent_roots):
            self.assertFalse(research_running)
            self.assertEqual(absent_roots,[str(Path(self.c.install['terminal_executable']).parent),self.c.install['terminal_data_root']])
            result=classify_processes(self.processes,binding,observed_unix=self.request['expires_utc']+1,research_running=False)
            result['root_inventory']=dict(roots=[str(PureWindowsPath(root)) for root in absent_roots],
                process_count=len(self.processes),unavailable_path_count=0,
                limitation='Windows-visible executable paths only; unrelated unreadable system paths cannot be attributed to a terminal')
            return result
        patch('studio_orphan_stopped.inspect_processes',side_effect=inventory).start()

    def run_settlement(self):
        return reconcile_rejection(self.c,self.review,confirmed=True,terminal_stopped=True)

    def test_retained_report_missing_permit_settles_only_exact_expired_rejection(self):
        # Regression for report03afb685/fc60: issued+request+native rejection
        # remain exact, but permit.json is absent before any cleanup intent.
        (self.gate/'permit.json').unlink()
        preserved={name:(self.gate/name).read_bytes() for name in ('request.json','issued-'+self.request_id+'.json','result-'+self.request_id+'.json')}
        self.c.runtime.side_effect=AssertionError('Stopped cleanup must not claim fresh native feedback')
        result=self.run_settlement()
        self.assertEqual(result['status'],'rejected_settled')
        self.assertIs(result['launch_permitted'],False);self.assertIs(result['recovery_retried'],False)
        intent=read_json(self.root/'intent.json')
        self.assertEqual(intent['schema_version'],3);self.assertEqual(intent['absent_transport'],['permit.json'])
        self.assertNotIn('permit.json',intent['sha256']);self.assertFalse((self.root/'permit.json').exists())
        self.assertEqual((self.root/'request.json').read_bytes(),preserved['request.json'])
        for name in ('issued-'+self.request_id+'.json','result-'+self.request_id+'.json'):
            self.assertEqual((self.gate/name).read_bytes(),preserved[name])
        self.assertEqual(self.c.state(),self.before);self.assertTrue(self.fixture.flags)
        self.assertFalse(self.fence.exists());self.assertFalse((self.gate/'request.json').exists())
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_missing_permit_does_not_prove_unknown_or_consumed_dispatch_safe(self):
        (self.gate/'permit.json').unlink()
        for name in ('request.json','issued-'+self.request_id+'.json','result-'+self.request_id+'.json'):
            path=self.gate/name;raw=path.read_bytes();path.unlink()
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Required rejected recovery evidence'):
                self.run_settlement()
            self.assert_fenced();self.assertFalse((self.root/'intent.json').exists());path.write_bytes(raw)
        for outcome in ('ORPHAN_RECOVERED','ORPHAN_CHANGED_AFTER_CLAIM','unknown'):
            self.fixture.consume(self.review,outcome,consumed=False)
            with self.subTest(outcome=outcome),self.assertRaisesRegex(ValueError,'pre-consumption'):
                self.run_settlement()
            self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())
        self.fixture.consume(self.review,self.rejection_status,consumed=True)
        with self.assertRaisesRegex(ValueError,'consumption'):self.run_settlement()
        self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_null_malformed_or_foreign_permit_refuses_without_mutation(self):
        permit=self.gate/'permit.json'
        for raw in (b'null',b'{',b'[]',b'{"request_sha256":null}',b'{"request_sha256":"foreign"}'):
            permit.write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.run_settlement()
            self.assertEqual(permit.read_bytes(),raw);self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_missing_permit_unexpired_rejection_refuses(self):
        (self.gate/'permit.json').unlink()
        for now in (self.request['expires_utc']-1,self.request['expires_utc']):
            with patch('studio_orphan_rejection.time.time',return_value=now),self.assertRaisesRegex(ValueError,'expired'):
                self.run_settlement()
            self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_missing_permit_malformed_or_null_native_result_refuses_typed(self):
        (self.gate/'permit.json').unlink()
        result=self.gate/('result-'+self.request_id+'.json')
        for raw in (b'null',b'{',b'[]',b'{}'):
            result.write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.run_settlement()
            self.assertEqual(result.read_bytes(),raw);self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_missing_permit_interrupted_intent_resumes_only_exact_absence(self):
        (self.gate/'permit.json').unlink();original=Path.unlink
        def interrupted(path,*args,**kwargs):
            if path==self.gate/'request.json':raise OSError('before request cleanup')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupted),self.assertRaises(OSError):self.run_settlement()
        self.assert_fenced();intent_file=self.root/'intent.json';raw=intent_file.read_bytes()
        intent=json.loads(raw);intent['absent_transport']=['request.json'];write_json(intent_file,intent)
        with self.assertRaisesRegex(ValueError,'transport absence changed'):self.run_settlement()
        self.assert_fenced();intent_file.write_bytes(raw)
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_missing_permit_different_consumption_also_blocks(self):
        (self.gate/'permit.json').unlink();other=self.c.local/'other-evidence';other.mkdir()
        (other/('consumed-'+'a'*64+'.json')).write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'consumption'):self.run_settlement()
        self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())

    def test_permit_appearing_after_absent_intent_stays_fenced_and_is_never_removed(self):
        (self.gate/'permit.json').unlink()
        original=settlement.write_json
        def appeared(path,value):
            original(path,value)
            if path.name=='intent.json':write_json(self.gate/'permit.json',{'foreign':'permit'})
        with patch('studio_orphan_rejection.write_json',side_effect=appeared),self.assertRaisesRegex(ValueError,'absent permit changed'):
            self.run_settlement()
        self.assertEqual(read_json(self.gate/'permit.json'),{'foreign':'permit'})
        self.assert_fenced();self.assertTrue((self.gate/'request.json').exists())

    def test_missing_permit_cli_returns_supported_settlement_not_errno(self):
        from goat_studio import main
        import io
        (self.gate/'permit.json').unlink();output=io.StringIO()
        with patch('goat_studio.Controller',return_value=self.c),patch('sys.stdout',output):
            code=main(['--installation',str(self.c.root/'installation.json'),'orphan-recovery-reconcile-rejection',
                       '--review-id',self.review,'--confirm-reviewed','--terminal-stopped'])
        self.assertEqual(code,0);self.assertEqual(json.loads(output.getvalue())['result']['status'],'rejected_settled')

    def test_process_monitor_account_generation_and_batch_drift_refuse(self):
        # No stale native monitor/account/flag observation is used offline.
        self.c.runtime.side_effect=AssertionError('Stopped cleanup must not claim fresh native feedback')
        for rows in ([{'ProcessId':777,'ExecutablePath':self.c.install['terminal_executable'],'CreatedUtc':'new'}],
                     [{'ProcessId':777,'ExecutablePath':None,'CreatedUtc':'new'}],
                     [{'ProcessId':777,'ExecutablePath':'C:/unmapped/terminal64.exe','CreatedUtc':'new'}]):
            self.processes=rows
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.run_settlement()
            self.assert_fenced()
        self.processes=[]
        before=dict(self.c.session['account'])
        self.c.session['account']['login']='999'
        write_json(self.c.root/'session.json',self.c.session)
        with self.assertRaisesRegex(ValueError,'account or session'):self.run_settlement()
        self.c.session['account']=before;write_json(self.c.root/'session.json',self.c.session)
        self.c.store.db.execute('UPDATE studio_state SET generation=generation+1')
        with self.assertRaisesRegex(ValueError,'state changed'):self.run_settlement()
        self.assertTrue(self.fence.exists());self.assertTrue((self.gate/'permit.json').exists())

    def test_explicit_offline_mode_preserves_result_and_records_actual_absence(self):
        self.c.runtime.side_effect=AssertionError('No live runtime while stopped')
        result_path=self.gate/('result-'+self.request_id+'.json');raw=result_path.read_bytes()
        result=self.run_settlement()
        self.assertEqual(result['status'],'rejected_settled')
        intent=read_json(self.root/'intent.json')
        self.assertEqual(intent['schema_version'],2);self.assertIs(intent['terminal_stopped'],True)
        self.assertIsNone(intent['process_observation']['research'])
        self.assertIs(intent['process_observation']['launch_permitted'],False)
        self.assertEqual(result_path.read_bytes(),raw)
        self.assertTrue(self.fixture.flags);self.assertEqual(self.c.state(),self.before)

    def test_offline_authority_never_inferred_from_owner_or_typed_session(self):
        for kwargs in ({}, {'owner_research':True}, {'confirmed':True,'owner_research':True}, {'confirmed':1}):
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(ValueError,'explicit human confirmation'):
                reconcile_rejection(self.c,self.review,terminal_stopped=True,**kwargs)
            self.assert_fenced()
        session=read_json(self.c.root/'session.json')
        write_json(self.c.root/'session.json',session|{'authority_kind':'research_continuation'})
        with self.assertRaisesRegex(ValueError,'Typed continuation'):
            self.run_settlement()
        self.assertTrue((self.gate/'permit.json').exists())
        write_json(self.c.root/'session.json',session)

    def test_pending_human_channels_refuse_without_consuming_commands(self):
        for channel in ('inbox','processing'):
            path=self.c.bridge.root/'human'/channel/'human-takeover.json'
            path.write_bytes(b'{"pending":"human takeover"}')
            with self.assertRaisesRegex(ValueError,'human control channel'):self.run_settlement()
            self.assertEqual(path.read_bytes(),b'{"pending":"human takeover"}')
            self.assert_fenced();path.unlink()

    def test_human_command_arriving_during_final_process_scan_keeps_fence(self):
        original=stopped.inspect_processes
        command=self.c.bridge.root/'human/inbox/human-takeover.json'
        def arriving(*args,**kwargs):
            result=original(*args,**kwargs)
            # The final verifier runs after the terminal plan is durable but
            # before the fence is removed. Exercise that specific boundary.
            if read_json(self.path)['status']=='rejected_settled':
                command.write_bytes(b'{"pending":"human takeover"}')
            return result
        with patch('studio_orphan_stopped.inspect_processes',side_effect=arriving),self.assertRaisesRegex(ValueError,'human control channel'):
            self.run_settlement()
        self.assert_fenced()
        self.assertEqual(read_json(self.path)['status'],'rejected_settled')
        self.assertEqual(command.read_bytes(),b'{"pending":"human takeover"}')
        self.assertFalse((self.gate/'permit.json').exists())
        self.assertFalse((self.gate/'request.json').exists())
        command.unlink() # Fixture simulates later legitimate human-channel reconciliation.
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_terminal_restart_during_cleanup_preserves_remaining_transport_and_fence(self):
        original=Path.unlink
        def restarted(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==self.gate/'permit.json':
                self.processes=[{'ProcessId':777,'ExecutablePath':self.c.install['terminal_executable'],'CreatedUtc':'new'}]
            return result
        with patch.object(Path,'unlink',restarted),self.assertRaisesRegex(ValueError,'Expected research process'):
            self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'request.json').exists())
        self.assertFalse((self.gate/'permit.json').exists())
        self.processes=[]
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_interrupted_offline_intent_cannot_resume_via_running_mode(self):
        original=Path.unlink
        def interrupted(path,*args,**kwargs):
            if path==self.gate/'permit.json':raise OSError('before cleanup')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupted),self.assertRaises(OSError):self.run_settlement()
        with self.assertRaisesRegex(ValueError,'mode differs'):
            reconcile_rejection(self.c,self.review,confirmed=True)
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_running_intent_cannot_be_reinterpreted_as_offline(self):
        original=Path.unlink
        def interrupted(path,*args,**kwargs):
            if path==self.gate/'permit.json':raise OSError('before cleanup')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupted),self.assertRaises(OSError):
            reconcile_rejection(self.c,self.review,confirmed=True)
        with self.assertRaisesRegex(ValueError,'mode differs'):self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())

    def test_changed_offline_proof_refuses_before_retirement(self):
        original=settlement.write_json
        def changed(path,value):
            original(path,value)
            if path.name=='intent.json':
                proof=read_json(path);proof['process_observation']['research']={'pid':777};original(path,proof)
        with patch('studio_orphan_rejection.write_json',side_effect=changed),self.assertRaisesRegex(ValueError,'Stopped recovery settlement intent'):
            self.run_settlement()
        self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())

    def test_interrupted_intent_refuses_missing_or_altered_inventory(self):
        original=Path.unlink
        def interrupted(path,*args,**kwargs):
            if path==self.gate/'permit.json':raise OSError('before cleanup')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',interrupted),self.assertRaises(OSError):self.run_settlement()
        saved=(self.root/'intent.json').read_bytes()
        for change in ('missing','roots','valid_count','negative_count','unknown_count','limitation'):
            intent=json.loads(saved);proof=intent['process_observation']
            if change=='missing':proof.pop('root_inventory')
            elif change=='roots':proof['root_inventory']['roots']=['C:\\wrong']
            elif change=='valid_count':proof['root_inventory']['process_count']+=1
            elif change=='negative_count':proof['root_inventory']['process_count']=-1
            elif change=='unknown_count':proof['root_inventory']['unavailable_path_count']=1
            else:proof['root_inventory']['limitation']='complete proof'
            write_json(self.root/'intent.json',intent)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'inventory evidence|retained process observation'):
                self.run_settlement()
            self.assert_fenced();self.assertTrue((self.gate/'permit.json').exists())
        (self.root/'intent.json').write_bytes(saved)
        self.assertEqual(self.run_settlement()['status'],'rejected_settled')

    def test_interrupted_before_intent_reuses_original_archived_observation(self):
        original=settlement.write_json
        def interrupted(path,value):
            if path.name=='intent.json':raise OSError('before intent')
            original(path,value)
        with patch('studio_orphan_rejection.write_json',side_effect=interrupted),self.assertRaises(OSError):self.run_settlement()
        before=(self.root/'process-observation.json').read_bytes()
        self.assert_fenced();self.assertFalse((self.root/'intent.json').exists())
        scan=stopped.inspect_processes
        def later(*args,**kwargs):
            result=scan(*args,**kwargs);result['observed_unix']+=10;return result
        with patch('studio_orphan_stopped.inspect_processes',side_effect=later):
            self.assertEqual(self.run_settlement()['status'],'rejected_settled')
        self.assertEqual((self.root/'process-observation.json').read_bytes(),before)
        self.assertEqual(read_json(self.root/'intent.json')['process_observation'],json.loads(before))
