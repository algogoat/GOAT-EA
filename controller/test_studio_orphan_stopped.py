"""Stopped cleanup source fixtures; no installed terminal or human action is used."""
import json
from pathlib import Path
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

    def setUp(self):
        super().setUp()
        self.processes=[]
        def inventory(binding,*,research_running,absent_roots):
            self.assertFalse(research_running)
            self.assertEqual(absent_roots,[str(Path(self.c.install['terminal_executable']).parent),self.c.install['terminal_data_root']])
            return classify_processes(self.processes,binding,observed_unix=self.request['expires_utc']+1,research_running=False)
        patch('studio_orphan_stopped.inspect_processes',side_effect=inventory).start()

    def run_settlement(self):
        return reconcile_rejection(self.c,self.review,confirmed=True,terminal_stopped=True)

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
