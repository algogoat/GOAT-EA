from datetime import datetime,timezone,timedelta
import hashlib
import time
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_human_reopen import prepare,adopt
from studio_onboarding import monitor_chart,monitor_paths,verify_monitor_profile
import test_studio_rejected_monitor as fixtures


class HumanReopenTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RejectedMonitorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c;self.process,_,self.draft=self.f.retained_close()
        self.path=self.c.root/'rejected-monitor-restarts'/self.f.attempt/'restart.json'
        record=read_json(self.path);record['phase']='stopped';write_json(self.path,record)
        name,folder=monitor_paths(self.c,self.c.session);folder.mkdir(parents=True,exist_ok=True)
        chart=folder/'chart01.chr';chart.write_bytes(monitor_chart(self.c,'EURUSD').decode('utf-16').replace('expertmode=0','expertmode=4').encode('utf-16'))
        self.profile=dict(installation_sha256=sha(self.c.install),run_id=self.c.run,profile_name=name,profile_path=str(folder),symbol='EURUSD')
        write_json(self.c.root/'monitor-profile.json',self.profile)
        data=Path(self.c.install['terminal_data_root']);(data/'origin.txt').write_text(str(Path(self.c.install['terminal_executable']).parent))
        self.common=data/'config/common.ini';self.common.parent.mkdir(exist_ok=True)
        self.before=('[Common]\r\nLogin='+self.c.session['account']['login']+'\r\nServer='+self.c.session['account']['server']+
                     '\r\n[Experts]\r\nEnabled=0\r\nAllowDllImport=1\r\n[Charts]\r\nProfileLast=older-profile\r\n').encode('utf-16')
        self.common.write_bytes(self.before)
        self.native=self.f.native|dict(process=dict(pid=45,created_utc=datetime.now(timezone.utc).isoformat()))
        self.probe=patch('studio_human_reopen.inspect_idle_demo',side_effect=lambda c:self.native).start()
        self.runtime=patch.object(self.c,'runtime',side_effect=lambda **kw:(self.observation(),dict(modified=time.time()))).start()
        patch('studio_human_reopen.human_launch',side_effect=lambda c,p:dict(process=dict(p),active_console_session_id=1)).start()
        self.addCleanup(patch.stopall)

    def observation(self,age=0):
        stamp=datetime.now(timezone.utc)-timedelta(seconds=age)
        return self.c.state()|dict(observed_terminal_utc=stamp.strftime('%Y.%m.%d %H:%M:%S'))

    def prepared(self):
        receipt=prepare(self.c,'original',process=self.process)
        self.native['process']['created_utc']=datetime.now(timezone.utc).isoformat()
        self.process.inspect.return_value=self.native['process']
        return receipt

    def test_pointer_only_then_single_observation_without_launch_or_grant(self):
        self.prepared()
        self.assertEqual(self.common.read_bytes(),self.before.decode('utf-16').replace('older-profile',self.profile['profile_name']).encode('utf-16'))
        self.assertEqual((self.path.parent/'common-before.ini').read_bytes(),self.before)
        with self.assertRaisesRegex(ValueError,'permissions changed'):verify_monitor_profile(self.c,self.profile)
        with self.assertRaisesRegex(ValueError,'Actual human'):adopt(self.c,'original',process=self.process)
        result=adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(result['phase'],'reverified');self.assertTrue(result['human_reopened'])
        self.assertFalse(result['grant_created']);self.assertFalse(result['native_started'])
        self.process.start.assert_not_called();self.process.close.assert_called_once() # historical fixture close only
        with self.assertRaisesRegex(ValueError,'never-launched'):adopt(self.c,'original',human_reopened=True,process=self.process)

    def test_existing_process_and_changed_permissions_refuse_preparation(self):
        self.process.inspect.return_value=self.native['process']
        with self.assertRaisesRegex(ValueError,'remain stopped'):prepare(self.c,'original',process=self.process)
        self.process.inspect.return_value=None
        self.common.write_bytes(self.before.decode('utf-16').replace('Enabled=0','Enabled=1').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'Algo Trading off'):prepare(self.c,'original',process=self.process)
        self.assertFalse((self.path.parent/'human-reopen.json').exists())

    def test_old_process_live_sdk_and_changed_protected_draft_refuse_adoption(self):
        self.prepared()
        self.native['process']['created_utc']='2000-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'opened after'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.native['process']['created_utc']=datetime.now(timezone.utc).isoformat()
        self.native['algo_trading']=True
        with self.assertRaisesRegex(ValueError,'SDK-confirmed'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.native['algo_trading']=False
        self.draft.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Protected'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(read_json(self.path)['phase'],'stopped');self.process.start.assert_not_called()

    def test_changed_common_chart_and_session_observation_refuse(self):
        self.prepared();after=self.common.read_bytes()
        self.common.write_bytes(after.decode('utf-16').replace('AllowDllImport=1','AllowDllImport=0').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'configuration changed'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.common.write_bytes(after)
        chart=Path(self.profile['profile_path'])/'chart01.chr';raw=chart.read_bytes();chart.write_bytes(raw+'\r\n'.encode('utf-16-le'))
        with self.assertRaisesRegex(ValueError,'chart changed'):adopt(self.c,'original',human_reopened=True,process=self.process)
        chart.write_bytes(raw)
        self.runtime.side_effect=lambda **kw:(self.observation()|dict(owner='human'),dict(modified=time.time()))
        with self.assertRaisesRegex(ValueError,'exact typed session'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(read_json(self.path)['phase'],'stopped');self.process.start.assert_not_called()

    def test_interrupted_adoption_reverifies_same_process_without_readoption(self):
        from studio_rejected_monitor import reverify
        self.prepared();self.probe.side_effect=[self.native,ValueError('temporary SDK unavailable')]
        with self.assertRaisesRegex(ValueError,'temporary SDK'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(read_json(self.path)['phase'],'adopted_unverified')
        self.probe.side_effect=lambda c:self.native
        self.runtime.side_effect=lambda **kw:(self.c.state(),dict(modified=time.time()-10))
        with self.assertRaisesRegex(ValueError,'predates'):reverify(self.c,'original')
        self.assertEqual(read_json(self.path)['phase'],'adopted_unverified')
        self.runtime.side_effect=lambda **kw:(self.observation(age=10),dict(modified=time.time()))
        with self.assertRaisesRegex(ValueError,'observation timestamp predates'):reverify(self.c,'original')
        self.assertEqual(read_json(self.path)['phase'],'adopted_unverified')
        self.runtime.side_effect=lambda **kw:(self.observation(),dict(modified=time.time()))
        result=reverify(self.c,'original');self.assertEqual(result['phase'],'reverified')
        self.native['process']=dict(pid=46,created_utc=datetime.now(timezone.utc).isoformat())
        with self.assertRaisesRegex(ValueError,'process changed'):reverify(self.c,'original')
        self.process.start.assert_not_called()

    def test_fresh_but_previous_process_feedback_refuses_adoption(self):
        self.prepared()
        self.runtime.side_effect=lambda **kw:(self.c.state(),dict(modified=time.time()-10))
        with self.assertRaisesRegex(ValueError,'predates'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(read_json(self.path)['phase'],'stopped');self.process.start.assert_not_called()

    def test_recently_copied_previous_process_observation_refuses_adoption(self):
        self.prepared()
        self.runtime.side_effect=lambda **kw:(self.observation(age=10),dict(modified=time.time()))
        with self.assertRaisesRegex(ValueError,'observation timestamp predates'):adopt(self.c,'original',human_reopened=True,process=self.process)
        self.assertEqual(read_json(self.path)['phase'],'stopped');self.process.start.assert_not_called()

    def test_interrupted_pointer_publication_resumes_exact_bytes_once(self):
        original=os.replace
        def fail_pointer(source,target):
            if Path(target)==self.common:raise OSError('sharing violation')
            return original(source,target)
        with patch('studio_human_reopen.os.replace',side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError,'sharing violation'):prepare(self.c,'original',process=self.process)
        audit=(self.path.parent/'human-reopen.json').read_bytes()
        self.assertEqual(self.common.read_bytes(),self.before)
        # A process appearing after the interrupted write still forbids replay.
        self.process.inspect.return_value=self.native['process']
        with self.assertRaisesRegex(ValueError,'remain stopped'):prepare(self.c,'original',process=self.process)
        self.process.inspect.return_value=None
        prepare(self.c,'original',process=self.process)
        expected=self.before.decode('utf-16').replace('older-profile',self.profile['profile_name']).encode('utf-16')
        self.assertEqual(self.common.read_bytes(),expected)
        prepare(self.c,'original',process=self.process)
        self.assertEqual((self.path.parent/'human-reopen.json').read_bytes(),audit)
        self.process.start.assert_not_called()

    def test_complete_receipt_mutation_refuses_resume_and_adoption(self):
        self.prepared();audit=self.path.parent/'human-reopen.json';raw=audit.read_bytes()
        self.process.inspect.return_value=None
        for key,value in (('created_utc',time.time()-100),('schema_version',3),('launch_issued',True),('permissions_changed',True)):
            with self.subTest(key=key):
                write_json(audit,read_json(self.path.parent/'human-reopen-intent.json')|{key:value})
                with self.assertRaisesRegex(ValueError,'receipt bytes changed'):prepare(self.c,'original',process=self.process)
                self.process.inspect.return_value=self.native['process']
                with self.assertRaisesRegex(ValueError,'receipt bytes changed'):adopt(self.c,'original',human_reopened=True,process=self.process)
                self.process.inspect.return_value=None
        audit.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'receipt bytes changed'):prepare(self.c,'original',process=self.process)
        audit.write_bytes(raw);prepare(self.c,'original',process=self.process)
        self.assertEqual(audit.read_bytes(),raw)

    def test_interrupted_receipt_copy_uses_original_intent(self):
        original=write_json
        def fail_audit(path,value):
            if Path(path).name=='human-reopen.json':raise OSError('interrupted receipt copy')
            return original(path,value)
        with patch('studio_human_reopen.write_json',side_effect=fail_audit):
            with self.assertRaisesRegex(OSError,'interrupted receipt'):prepare(self.c,'original',process=self.process)
        raw=(self.path.parent/'human-reopen-intent.json').read_bytes()
        original_replace=os.replace
        def fail_replace(source,target):
            if Path(target).name=='human-reopen.json':raise OSError('interrupted atomic publish')
            return original_replace(source,target)
        with patch('studio_human_reopen.os.replace',side_effect=fail_replace):
            with self.assertRaisesRegex(OSError,'atomic publish'):prepare(self.c,'original',process=self.process)
        self.assertFalse((self.path.parent/'human-reopen.json').exists())
        prepare(self.c,'original',process=self.process)
        self.assertEqual((self.path.parent/'human-reopen.json').read_bytes(),raw)

    def test_missing_intent_refuses_new_adoption_and_legacy_republication(self):
        self.prepared();audit=self.path.parent/'human-reopen.json'
        (self.path.parent/'human-reopen-intent.json').unlink()
        with self.assertRaisesRegex(ValueError,'Original publication intent'):adopt(self.c,'original',human_reopened=True,process=self.process)
        write_json(audit,read_json(audit)|dict(schema_version=1))
        self.process.inspect.return_value=None
        with self.assertRaisesRegex(ValueError,'Original publication intent'):prepare(self.c,'original',process=self.process)
        self.process.inspect.return_value=self.native['process']
        self.assertEqual(adopt(self.c,'original',human_reopened=True,process=self.process)['phase'],'reverified')


if __name__=='__main__':unittest.main()
