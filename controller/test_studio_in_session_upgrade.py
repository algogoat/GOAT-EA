"""Exercise the retained switch against a real typed grant/store, with native IO faked."""
import hashlib
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_installation_migration import verify_installation_chain
from studio_in_session_upgrade import upgrade
import test_studio_research_regrant as fixtures


class Process:
    def __init__(self):
        self.current=dict(pid=42,created_utc='fixture',executable='fixture')
        self.closes=0
        self.starts=0
        self.on_start=None
    def inspect(self):return self.current
    def close(self,identity):
        if identity!=self.current:raise ValueError('process changed')
        self.closes+=1;self.current=None
    def start(self,config):
        if self.current is not None:raise ValueError('process still running')
        self.starts+=1
        self.current=dict(pid=43,created_utc='relaunched',executable='fixture')
        if self.on_start is not None:self.on_start()
        return self.current


class InSessionUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ResearchRegrantTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.addCleanup(patch.stopall)
        self.f.take();request,result=self.f.grant();self.assertTrue(result['ok'])
        self.c=self.f.c;self.process=Process()
        self.root=self.c.root
        self.process.on_start=self.fresh_observation
        self.old=read_json(self.root/'installation.json')
        self.old_raw=(self.root/'installation.json').read_bytes()
        self.old_sha=hashlib.sha256(self.old_raw).hexdigest()
        self.binary=Path(self.old['terminal_data_root'])/'MQL5/Experts'/self.old['ea_relative_path'].replace('\\','/')
        self.old_ea=self.binary.read_bytes()
        folder=self.root.parent/'candidate-in-session'
        folder.mkdir()
        self.ea=folder/'candidate.ex5';self.ea.write_bytes(b'admitted diagnostic EA')
        self.next=self.old|dict(ea_sha256=hashlib.sha256(self.ea.read_bytes()).hexdigest())
        self.candidate=folder/'candidate.json';write_json(self.candidate,self.next)
        now=int(time.time()*1000)
        self.checked=dict(input=dict(accountId=self.c.session['account']['login'],
            buildId='V1.49-DIAGNOSTIC',selection=dict(
                terminalExecutable=self.old['terminal_executable'],
                terminalDataRoot=self.old['terminal_data_root'],portable=self.old.get('terminal_portable',False))),
            admission=dict(mode='INTERNAL_REVIEWED',uid='real-authenticated-fixture',
                accountId=self.c.session['account']['login'],buildId='V1.49-DIAGNOSTIC',
                artifactSha256=self.next['ea_sha256'],sourceCommit='b'*40,
                compileReceiptSha256='d'*64,admissionSha256='e'*64,grantsControl=False,
                checkedAtMs=now,validUntilMs=now+30000,notBeforeMs=now-1000,
                persistent=False,expiresAtMs=now+60000),
            identity=dict(eaSha256=self.next['ea_sha256'],eaVersion=self.next['ea_version'],
                controllerVersion=self.next['controller_version'],eaSourceRevision='b'*40,
                manifestSha256='c'*64))
        self.admission=folder/'admission.json';write_json(self.admission,self.checked)
        self.native=dict(account_matches=True,demo=True,connected=True,algo_trading=False,
            positions=0,orders=0,tester_state='idle')
        patch('studio_driver_suspend.require_no_publishers').start()
        patch('studio_in_session_upgrade._monitor_config',side_effect=self.monitor_config).start()
        patch('goat_studio.Controller.runtime',return_value=({},{})).start()

    def probe(self,controller):return dict(self.native,process=self.process.current)
    def monitor_config(self,controller,folder):
        config=folder/'monitor.ini';raw=b'fixture inert monitor startup'
        config.write_bytes(raw)
        return config,hashlib.sha256(raw).hexdigest(),'e'*64
    def fresh_observation(self):
        import os
        observation=self.c.local/'ui-observation.json'
        if not observation.exists():write_json(observation,dict(monitor='fixture'))
        fresh=time.time()+.01
        os.utime(observation,(fresh,fresh))
    def run_upgrade(self, clock=time):
        return upgrade(self.root/'installation.json','a'*32,self.candidate,self.ea,self.admission,
            self.old_sha,clock=clock,process_factory=lambda c:self.process,native_probe=self.probe)

    def test_genuine_epoch_plan_and_failed_history_survive_exact_switch(self):
        session=(self.root/'session.json').read_bytes()
        authority=(self.root/'research-authority.json').read_bytes()
        from campaign_ledger import packed
        binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
        epoch=self.c.store.db.execute('SELECT provenance FROM studio_research_epochs WHERE binding=?',(binding,)).fetchone()[0]
        result=self.run_upgrade()
        self.assertEqual(result['status'],'verified')
        self.assertEqual((self.process.closes,self.process.starts),(1,1))
        self.assertEqual((self.root/'session.json').read_bytes(),session)
        self.assertEqual((self.root/'research-authority.json').read_bytes(),authority)
        self.assertEqual(self.c.store.db.execute('SELECT provenance FROM studio_research_epochs WHERE binding=?',(binding,)).fetchone()[0],epoch)
        self.assertEqual(verify_installation_chain(self.root,self.next,sha(self.old))['migrations'],1)
        self.assertEqual(self.binary.read_bytes(),self.ea.read_bytes())
        launch=read_json(self.root/('monitor-launches/in-session-'+('a'*32)+'.json'))
        self.assertEqual((launch['status'],launch['pid'],launch['installation_sha256']),
            ('process_started_unverified',43,sha(self.next)))
        self.assertEqual(launch['startup_sha256'],hashlib.sha256(b'fixture inert monitor startup').hexdigest())
        self.assertEqual(self.run_upgrade(),result)
        self.assertEqual((self.process.closes,self.process.starts),(1,1))
        with self.assertRaisesRegex(ValueError,'previous registered receipt changed'):
            upgrade(self.root/'installation.json','b'*32,self.candidate,self.ea,self.admission,
                self.old_sha,process_factory=lambda c:self.process,native_probe=self.probe)

    def test_algo_on_refuses_without_closing_or_changing_installation(self):
        self.native['algo_trading']=True
        with self.assertRaises(ValueError):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(0,0))
        self.assertEqual((self.root/'installation.json').read_bytes(),self.old_raw)
        self.assertEqual(self.binary.read_bytes(),self.old_ea)

    def test_corrupt_published_ea_refuses_before_relaunch_and_keeps_fence(self):
        from studio_build_upgrade import replace_bytes
        def corrupt(target,raw):
            replace_bytes(target,raw)
            if target==self.binary:target.write_bytes(b'foreign EA bytes')
        with patch('studio_in_session_upgrade.replace_bytes',side_effect=corrupt):
            with self.assertRaisesRegex(ValueError,'Published EA/receipt readback differs'):
                self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(1,0))
        from studio_installation_migration import pending_path
        self.assertTrue(pending_path(self.root).exists())

    def test_foreign_admission_refuses_before_native_effect(self):
        self.checked['admission']['accountId']='9999999999';write_json(self.admission,self.checked)
        with self.assertRaisesRegex(ValueError,'admission'):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(0,0))

    def test_expired_admission_refuses_before_native_effect(self):
        self.checked['admission']['validUntilMs']=self.checked['admission']['checkedAtMs']
        write_json(self.admission,self.checked)
        with self.assertRaisesRegex(ValueError,'admission'):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(0,0))

    def test_pending_native_job_refuses_before_native_effect(self):
        with patch.object(self.c.store,'snapshot',return_value=dict(owner='agent',generation=2,
                queue=[dict(job_id='pending',status='pending')])):
            # The new Controller opens its own store; fake the same snapshot at
            # the shared store boundary, before any native close.
            from studio_command_store import StudioStore
            with patch.object(StudioStore,'snapshot',return_value=dict(owner='agent',generation=2,
                    queue=[dict(job_id='pending',status='pending')])):
                with self.assertRaisesRegex(ValueError,'no pending native job'):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(0,0))

    def test_exact_same_id_reconciles_after_close_effect_then_exception(self):
        original=self.process.close
        def uncertain(identity):
            original(identity)
            raise ValueError('simulated interrupted close acknowledgement')
        with patch.object(self.process,'close',side_effect=uncertain):
            with self.assertRaisesRegex(ValueError,'interrupted close'):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(1,0))
        self.assertEqual(read_json(self.root/'installation-migrations/000001/transaction.json')['phase'],'close_issued')
        from goat_studio import Controller
        with self.assertRaisesRegex(ValueError,'unfinished'):
            Controller(self.root/'installation.json').open()
        result=self.run_upgrade()
        self.assertEqual(result['status'],'verified')
        self.assertEqual((self.process.closes,self.process.starts),(1,1))

    def test_crash_after_fence_before_anchor_rebuilds_only_exact_archive(self):
        with patch('studio_in_session_upgrade._ensure_anchor',side_effect=ValueError('interrupted anchor')):
            with self.assertRaisesRegex(ValueError,'interrupted anchor'):self.run_upgrade()
        self.assertEqual((self.process.closes,self.process.starts),(0,0))
        from studio_installation_migration import pending_path
        self.assertTrue(pending_path(self.root).exists())
        self.assertEqual(self.run_upgrade()['status'],'verified')
        self.assertEqual((self.process.closes,self.process.starts),(1,1))

    def test_prepared_journal_exists_before_external_fence(self):
        from studio_installation_migration import pending_path
        from studio_in_session_upgrade import write_json as original
        pending=pending_path(self.root)
        def interrupted(path,value):
            if path==pending:
                stage=pending.parent/('a'*32)/'archive'
                self.assertEqual(read_json(stage/'transaction.json')['phase'],'prepared')
                raise ValueError('interrupted before fence publication')
            return original(path,value)
        with patch('studio_in_session_upgrade.write_json',side_effect=interrupted):
            with self.assertRaisesRegex(ValueError,'interrupted before fence'):
                self.run_upgrade()
        self.assertFalse(pending.exists())
        self.assertEqual((self.process.closes,self.process.starts),(0,0))
        self.assertEqual(self.run_upgrade()['status'],'verified')

    def test_uncommitted_archive_copy_is_preserved_and_cannot_block_old_session(self):
        from studio_installation_migration import pending_path
        stage=pending_path(self.root).parent/('a'*32)/'archive'
        stage.mkdir(parents=True)
        (stage/'partial.json').write_text('{"copy":"interrupted"}')
        from goat_studio import Controller
        controller=Controller(self.root/'installation.json').open()
        controller.store.close()
        self.assertEqual(self.run_upgrade()['status'],'verified')
        self.assertEqual((self.process.closes,self.process.starts),(1,1))
        self.assertEqual(len(list(stage.parent.glob('abandoned-*/partial.json'))),1)

    def test_stale_post_launch_evidence_remains_fenced_and_same_id_retries_without_relaunch(self):
        class FastClock:
            elapsed=0
            def time(self):return time.time()
            def monotonic(self):return self.elapsed
            def sleep(self,seconds):self.elapsed+=seconds
        self.process.on_start=None
        with self.assertRaisesRegex(ValueError,'post-launch EA observation'):
            self.run_upgrade(clock=FastClock())
        self.assertEqual((self.process.closes,self.process.starts),(1,1))
        from studio_installation_migration import pending_path
        self.assertTrue(pending_path(self.root).exists())
        from goat_studio import Controller
        with self.assertRaisesRegex(ValueError,'unfinished'):
            Controller(self.root/'installation.json').open()
        self.fresh_observation()
        self.assertEqual(self.run_upgrade()['status'],'verified')
        self.assertEqual((self.process.closes,self.process.starts),(1,1))


if __name__=='__main__':unittest.main()
