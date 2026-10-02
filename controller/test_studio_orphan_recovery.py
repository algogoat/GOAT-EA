"""Recovery protocol fixtures. Native terminal qualification is separate."""
from datetime import datetime, timezone
import time
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from campaign_ledger import sha
from studio_bridge import write_json
from studio_handover import guard
from studio_orphan_recovery import prepare, apply, status, inspect, plan_path
import test_goat_studio as fixtures


class OrphanRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PortableControllerTests(); self.fixture.setUp()
        self.c=self.fixture.bound(); self.fixture.grant(self.c); self.fixture.prepare(self.c)
        self.c.install['ea_version']='1.49'
        self.c.install['ea_relative_path']='GOAT-EA\\GOAT V1.49.ex5'
        expert=Path(self.c.install['terminal_data_root'])/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
        expert.write_bytes(b'qualified test fixture')
        self.c.session['installation_sha256']=sha(self.c.install)
        write_json(self.c.root/'installation.json',self.c.install)
        write_json(self.c.root/'session.json',self.c.session)
        (self.fixture.common/'GOAT').mkdir()
        self.gate=self.c.local/'native-gate'
        self.cap=dict(protocol=1,ea_version='1.49',monitor_instance='instance-one',terminal_running=False)
        self.flags=True
        self.clock_offset=0
        self.observation_age=0
        self.terminal_utc=lambda:datetime.fromtimestamp(time.time()-self.observation_age+self.clock_offset,timezone.utc).strftime('%Y.%m.%d %H:%M:%S')
        def runtime(**kwargs):
            if kwargs['expected_batch_ongoing']!=self.flags: raise ValueError('Runtime policy mismatch: batch_ongoing')
            return dict(recovery_capability=self.cap,runtime=dict(batch_ongoing=self.flags),observed_terminal_utc=self.terminal_utc()),{'modified':time.time()-self.observation_age}
        self.addCleanup(patch.stopall)
        patch.object(self.c,'runtime',side_effect=runtime).start()
        patch('studio_orphan_recovery.inspect_writers').start()
        patch('studio_orphan_recovery.inspect_processes',return_value={'research':{'pid':123,'created_utc':'fixed'}}).start()

    def tearDown(self): self.fixture.tearDown()

    def consume(self,review_id, outcome='ORPHAN_RECOVERED', *, consumed=True):
        plan=json.loads(plan_path(self.c,review_id).read_text()); record=plan['record']; request=record['request']
        request_id=request['request_id']
        if consumed: (self.gate/('consumed-'+request_id+'.json')).write_bytes((self.gate/'request.json').read_bytes())
        write_json(self.gate/('result-'+request_id+'.json'),dict(request_id=request_id,request_sha256=record['request_sha256'],status=outcome))

    def test_review_publish_readback_preserves_jobs_and_grants_and_never_reissues(self):
        before=self.c.state()
        reviewed=prepare(self.c); review_id=reviewed['review_id']
        with self.assertRaisesRegex(ValueError,'Explicit user'): apply(self.c,review_id)
        published=apply(self.c,review_id,confirmed=True)
        self.assertEqual(published['status'],'published_not_recovered')
        exact=(self.gate/'request.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'orphan recovery'): guard(self.c)
        self.assertEqual(status(self.c,review_id)['status'],'reconcile_required')
        self.assertEqual(apply(self.c,review_id,confirmed=True)['status'],'reconcile_required')
        self.assertEqual((self.gate/'request.json').read_bytes(),exact)
        self.consume(review_id); self.flags=False
        self.assertEqual(status(self.c,review_id)['status'],'recovered')
        self.assertFalse((self.gate/'permit.json').exists())
        self.assertFalse((self.gate/'request.json').exists())
        guard(self.c)
        self.assertEqual(self.c.state(),before)
        self.assertTrue(list(self.gate.glob('consumed-*.json')))
        self.assertEqual(status(self.c,review_id)['status'],'recovered')

    def test_one_second_ahead_controller_fits_native_expiry_ceiling(self):
        with patch('studio_orphan_recovery.time.time',return_value=1800000000):
            self.clock_offset=-1
            review=prepare(self.c)['review_id']
            published=apply(self.c,review,confirmed=True)
            request=json.loads((self.gate/'request.json').read_text())
            terminal_now=1799999999
            # Mirror the unchanged native validity interval: the old +60 fails.
            self.assertGreater(1800000000+60,terminal_now+60)
            self.assertGreater(request['expires_utc'],terminal_now)
            self.assertLessEqual(request['expires_utc'],terminal_now+60)
            self.assertEqual(request['expires_utc'],1800000045)
            self.assertEqual(published['status'],'published_not_recovered')
            self.assertFalse(published['launch_permitted'])

    def test_clock_refusal_leaves_review_snapshot_transport_and_grant_unchanged(self):
        with patch('studio_orphan_recovery.time.time',return_value=1800000000):
            review=prepare(self.c)['review_id'];before=self.c.state()
            review_bytes=plan_path(self.c,review).read_bytes()
            snapshot=(self.c.bridge.root/'snapshot.json').read_bytes()
            for offset in (-8,8,-3600,3600):
                self.clock_offset=offset
                with self.subTest(offset=offset),self.assertRaisesRegex(ValueError,'5 seconds'):
                    apply(self.c,review,confirmed=True)
                self.assertEqual(plan_path(self.c,review).read_bytes(),review_bytes)
                self.assertEqual((self.c.bridge.root/'snapshot.json').read_bytes(),snapshot)
                self.assertFalse((self.gate/'request.json').exists())
                self.assertFalse((self.gate/'permit.json').exists())
                self.assertFalse((self.c.root/'orphan-recovery-pending.json').exists())
                self.assertEqual(list(self.gate.glob('issued-*.json')),[])
                self.assertEqual(self.c.state(),before)
            # A later fresh observation permits this still-valid review, once.
            self.clock_offset=0
            self.observation_age=15
            self.assertEqual(apply(self.c,review,confirmed=True)['status'],'published_not_recovered')

    def test_fifteen_second_old_zero_skew_feedback_passes_real_freshness_guard(self):
        with patch('studio_orphan_recovery.time.time',return_value=1800000000):
            review=prepare(self.c)['review_id']
            install=self.c.install
            observation=dict(schema_version=1,bound=True,recovery_capability=self.cap,runtime=dict(
                batch_ongoing=True,tester_state='idle',connected=True,account_demo=True,
                terminal_trade_allowed=False,restart_pending=False,
                data_path=install['terminal_data_root'],
                installation_path=str(Path(install['terminal_executable']).parent),
                program_path=str(self.c.native_args()['monitor_path'].resolve()),
                account_login=str(self.c.session['account']['login']),account_server=self.c.session['account']['server']))
            def read_observation(unused):
                observation['observed_terminal_utc']=self.terminal_utc()
                return observation,time.time()-self.observation_age
            # Exercise production freshness rather than bypassing it in this case.
            self.c.runtime.side_effect=lambda **kwargs:type(self.c).runtime(self.c,**kwargs)
            with patch('studio_resilient_read.read_observation',side_effect=read_observation):
                self.observation_age=21
                with self.assertRaisesRegex(ValueError,'stale or future-dated'):
                    apply(self.c,review,confirmed=True)
                self.assertFalse((self.gate/'permit.json').exists())
                self.observation_age=15
                self.assertEqual(apply(self.c,review,confirmed=True)['status'],'published_not_recovered')

    def test_missing_or_malformed_terminal_time_never_publishes(self):
        review=prepare(self.c)['review_id']
        for value in (None,True,1800000000,'invalid','2026.13.01 00:00:00'):
            self.terminal_utc=lambda:value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'valid terminal UTC'):
                apply(self.c,review,confirmed=True)
            self.assertFalse((self.gate/'permit.json').exists())
            self.assertFalse((self.c.root/'orphan-recovery-pending.json').exists())

    def test_legacy_missing_capability_runtime_identity_and_changed_review_refuse(self):
        self.c.install['ea_version']='1.48'
        with self.assertRaisesRegex(ValueError,'V1.49'): prepare(self.c)
        self.c.install['ea_version']='1.49'
        self.cap['protocol']=0
        with self.assertRaisesRegex(ValueError,'capability'): prepare(self.c)
        self.cap['protocol']=1
        review_id=prepare(self.c)['review_id']
        self.cap['monitor_instance']='reloaded'
        with self.assertRaisesRegex(ValueError,'changed'): apply(self.c,review_id,confirmed=True)
        self.assertFalse((self.gate/'permit.json').exists())

    def test_legacy_gates_cross_version_controls_seed_and_unresolved_bindings_refuse(self):
        foreign=self.c.local/'older/native-gate/controller.json'; foreign.parent.mkdir(parents=True); write_json(foreign,{'database':'legacy.sqlite'})
        with self.assertRaisesRegex(ValueError,'Legacy/foreign'): prepare(self.c)
        foreign.unlink()
        folder=self.fixture.common/'GOAT/GOAT V1.47-Customer-Demo'; folder.mkdir()
        pointer=folder/'active_optimization_run.ini'; pointer.write_text('retained')
        with self.assertRaisesRegex(ValueError,'legacy EA'): prepare(self.c)
        self.assertEqual(pointer.read_text(),'retained'); pointer.unlink()
        seed=self.c.root/'seed-active.json'; write_json(seed,{'status':'active'})
        with self.assertRaisesRegex(ValueError,'Seed runner'): prepare(self.c)
        seed.unlink()
        self.c.store.bind('foreign','binding')
        with self.assertRaisesRegex(ValueError,'Multiple controller'): prepare(self.c)

    def test_other_terminal_batch_state_never_blocks_but_own_and_shared_folders_do(self):
        # INV-BATCH-01: mirrors GoatStudioRecoveryCommonClear in the EA.
        from studio_terminal_isolation import controller_base_name, controller_hash, legacy_base_name
        common=self.fixture.common/'GOAT'; account=self.c.session['account']
        own=controller_base_name(self.c); own_hash=controller_hash(self.c)
        other=common/('GOAT V1.49-'+account['server']+'-'+account['login']+'-00000000')
        self.assertNotEqual(other.name,own)
        other.mkdir(); (other/'active_optimization_run.ini').write_text('other terminal'); (other/'agent-native-control-owner.json').write_text('{}')
        self.assertEqual(prepare(self.c)['status'],'review')
        self.assertEqual((other/'active_optimization_run.ini').read_text(),'other terminal')
        # This terminal's folder under another login, its -0- folder and an upper-case spelling all block.
        for name in (own, legacy_base_name('1.49',account['server']), 'GOAT V1.49-'+account['server']+'-987654-'+own_hash,
                     'GOAT V1.49-'+account['server']+'-0-'+own_hash, 'GOAT V1.49-'+account['server']+'-'+account['login']+'-'+own_hash.upper()):
            folder=common/name; folder.mkdir(exist_ok=True); pointer=folder/'active_optimization_run.ini'; pointer.write_text('retained')
            with self.assertRaisesRegex(ValueError,'Native controls exist'): prepare(self.c)
            pointer.unlink()

    def test_crash_after_consumption_or_missing_consumption_never_reports_success(self):
        review_id=prepare(self.c)['review_id']; apply(self.c,review_id,confirmed=True)
        self.consume(review_id,consumed=False); self.flags=False
        self.assertEqual(status(self.c,review_id)['status'],'reconcile_required')
        self.consume(review_id,outcome='ORPHAN_CONSUMED_RECONCILE')
        self.assertEqual(status(self.c,review_id)['status'],'reconcile_required')
        self.assertTrue((self.c.root/'orphan-recovery-pending.json').exists())
        self.assertTrue((self.gate/'permit.json').exists())

    def test_foreign_transport_and_posteffect_state_change_preserve_fence(self):
        review_id=prepare(self.c)['review_id']; apply(self.c,review_id,confirmed=True)
        self.consume(review_id); self.flags=False
        original=(self.gate/'permit.json').read_bytes()
        write_json(self.gate/'permit.json',{'request_sha256':'foreign'})
        with self.assertRaisesRegex(ValueError,'controls changed'): status(self.c,review_id)
        self.assertEqual(json.loads((self.gate/'permit.json').read_text())['request_sha256'],'foreign')
        (self.gate/'permit.json').write_bytes(original)
        self.c.store.db.execute('UPDATE studio_state SET revision=revision+1')
        with self.assertRaisesRegex(ValueError,'identity/state changed'): status(self.c,review_id)
        self.assertTrue((self.c.root/'orphan-recovery-pending.json').exists())

    def test_native_contract_guard_and_sole_effect_ordering(self):
        root=Path(__file__).resolve().parent.parent
        native=(root/'GOATStudioRecovery.mqh').read_text(encoding='utf-8-sig')
        self.assertIn('#ifdef GOAT_ORPHAN_RECOVERY_V149',native)
        self.assertEqual(native.count('GlobalVariableDel('),1)
        self.assertIn('GlobalVariableDel("BatchOnGoing")',native)
        effect=native.index('if(!GlobalVariableDel("BatchOnGoing"))')
        self.assertLess(native.index('if(!GoatStudioWriteUtf8(consumed,body))'),effect)
        for forbidden in ('ClickStart(', 'ClickStop(', 'GlobalVariableSet(', 'FileDelete(', 'OrderSend(', 'ReconstructFile('):
            self.assertNotIn(forbidden,native)
        for version in ('1.47','1.48'):
            self.assertNotIn('#define GOAT_ORPHAN_RECOVERY_V149',(root/('GOAT V'+version+'.mq5')).read_text(encoding='utf-8-sig'))
        from studio_installation import contracts
        schema,policy=contracts('1.49')
        self.assertEqual(schema['defines']['GOAT_VERSION_LABEL'],'"1.49"')
        self.assertEqual(policy['main_sha256'],hashlib.sha256((root/'GOAT V1.49.mq5').read_bytes()).hexdigest())

    def test_controller_construction_occurs_under_exclusive_session_hold(self):
        from studio_handover import paths
        from studio_native_gate import shared_gate
        self.c.store.close();self.c.store=None
        original=self.c.open
        def opened(**kwargs):
            with self.assertRaises(OSError):
                with shared_gate(paths(self.c)[3]): pass
            return original(**kwargs)
        with patch.object(self.c,'open',side_effect=opened):
            self.assertEqual(prepare(self.c)['status'],'review')
        self.assertIsNone(self.c.store)

    def test_settled_prior_dispatch_is_preserved_before_new_recovery_publication(self):
        import test_studio_settled_gate as settled
        fixture=settled.SettledGateTests(); fixture.setUp()
        try:
            fixture.settle();c=fixture.c
            c.install.update(ea_version='1.49',ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
            expert=Path(c.install['terminal_data_root'])/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
            expert.write_bytes(b'qualified test fixture')
            c.session['installation_sha256']=sha(c.install)
            write_json(c.root/'installation.json',c.install);write_json(c.root/'session.json',c.session)
            old=(fixture.gate/'request.json').read_bytes()
            preserved={p:p.read_bytes() for p in fixture.gate.iterdir() if p.name.startswith(('issued-','consumed-','result-'))}
            observation={'recovery_capability':self.cap,'runtime':{'tester_state':'idle','batch_ongoing':True},'observed_terminal_utc':self.terminal_utc()}
            with patch.object(c,'runtime',return_value=(observation,{'modified':time.time()})), \
                 patch('studio_resilient_read.read_observation',return_value=(observation,1)), \
                 patch('studio_process_check.inspect_processes'):
                from studio_queue_clear import recovery_status
                diagnosed=recovery_status(c)
                self.assertEqual(diagnosed['blockers'],[])
                self.assertTrue(diagnosed['orphan_recovery_supported'])
                review_id=prepare(c)['review_id']; apply(c,review_id,confirmed=True)
            plan=json.loads(plan_path(c,review_id).read_text())
            self.assertEqual(plan['prior_request_utf8'].encode('utf-8'),old)
            self.assertEqual(plan['record']['prior_control']['status'],'settled')
            for path,raw in preserved.items(): self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(c.job('beta-job')['status'],'cancelled')
        finally: fixture.tearDown()


if __name__=='__main__': unittest.main()
