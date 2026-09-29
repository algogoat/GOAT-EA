"""Owner recovery scope does not replace native guards or manufacture consent."""
import hashlib
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch, Mock

from campaign_ledger import sha
from studio_bridge import write_json
from studio_owner_research import authorize, BINDING_KEYS
from studio_orphan_recovery import prepare, apply
from studio_orphan_recovery import plan_path
from studio_orphan_rejection import reconcile_rejection
import test_studio_orphan_recovery as recovery_fixtures


class OwnerResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recovery_fixtures.OrphanRecoveryTests(); self.fixture.setUp(); self.c = self.fixture.c
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(self.fixture.doCleanups)
        c = self.c
        c.install["terminal_portable"] = False
        c.install['ea_sha256'] = hashlib.sha256((Path(c.install['terminal_data_root'])/'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5').read_bytes()).hexdigest()
        c.session['installation_sha256'] = sha(c.install)
        write_json(c.root/'installation.json',c.install); write_json(c.root/'session.json',c.session)
        request = dict(schema_version=1, request_id='human-grant', terminal_id=c.terminal, run_id=c.run,
                       expected_revision=0, generation=0, command='control.grant_agent', payload={})
        self.request = request
        raw = (json.dumps(request)+'\n').encode()
        self.archive = c.bridge.root/'human/archive'
        self.archive.mkdir(parents=True,exist_ok=True)
        self.original = self.archive/('human-grant.'+hashlib.sha256(raw).hexdigest()+'.json')
        self.original.write_bytes(raw)
        binding = {key:c.install[key] for key in BINDING_KEYS}; binding['account']=c.session['account']
        self.policy = dict(schema_version=1, operations=['orphan-recovery-apply','orphan-recovery-reconcile-rejection'],
                           account=c.session['account'], binding_sha256=sha(binding), run_id=c.run,
                           grant_request_id='human-grant',grant_payload_hash=sha(dict(request=request,actor='human')),
                           generation=1,ea_version='1.49',allowed_ea_sha256=[c.install['ea_sha256']],
                           not_before_utc=int(time.time())-60, expires_utc=int(time.time())+3600)
        self.policy_path=c.root.parent/'policy.json';write_json(self.policy_path,self.policy)
        self.addCleanup(patch.stopall)
        patch('studio_owner_research.POLICY_PATH',self.policy_path).start()
        self.native=dict(process={'pid':123,'created_utc':'fixed'},protected=None,account_matches=True,
                         demo=True,connected=True,algo_trading=False,positions=0,orders=0,tester_state='idle',build=6230,sdk_version='test')
        patch('studio_owner_research.inspect_idle_demo',side_effect=lambda unused:dict(self.native)).start()
        def runtime(**kwargs):
            if kwargs['expected_batch_ongoing']!=self.fixture.flags: raise ValueError('Runtime policy mismatch: batch_ongoing')
            return dict(recovery_capability=self.fixture.cap,runtime=dict(batch_ongoing=self.fixture.flags),
                        observed_terminal_utc=self.fixture.terminal_utc(),
                        **{k:c.state()[k] for k in ('owner','revision','generation')}),{'modified':time.time()-self.fixture.observation_age}
        c.runtime.side_effect=runtime

    def authorization(self): return authorize(self.c,'orphan-recovery-apply','a'*32)

    def test_existing_human_grant_authorizes_without_creating_or_copying_control(self):
        before=self.c.state(); rows=list(self.c.store.db.execute('SELECT * FROM studio_receipts'))
        proof=self.authorization()
        self.assertEqual(proof['authorization'],'existing_owner_research_grant')
        self.assertFalse(proof['human_confirmation_fabricated'])
        self.assertEqual(self.c.state(),before)
        self.assertEqual(list(self.c.store.db.execute('SELECT * FROM studio_receipts')),rows)
        self.assertFalse((self.c.local/'native-gate/permit.json').exists())

    def test_scope_rejects_wrong_account_terminal_build_session_and_expiry(self):
        for key,value in [('account',dict(login='other',server='Customer-Demo')),('binding_sha256','a'*64),
                          ('run_id','another'),('allowed_ea_sha256',['b'*64]),('ea_version','1.48'),
                          ('expires_utc',0),('not_before_utc',int(time.time())+3600)]:
            with self.subTest(key=key):
                write_json(self.policy_path,self.policy|{key:value})
                with self.assertRaises(ValueError):self.authorization()
        write_json(self.policy_path,self.policy)
        with self.assertRaises(ValueError):authorize(self.c,'switch-apply','a'*32)

    def test_revoked_or_regranted_epoch_and_pending_human_takeover_refuse(self):
        self.c.store.db.execute("UPDATE studio_state SET owner='human'")
        with self.assertRaisesRegex(ValueError,'revoked'):self.authorization()
        self.c.store.db.execute("UPDATE studio_state SET owner='agent',generation=3")
        with self.assertRaisesRegex(ValueError,'revoked'):self.authorization()
        self.c.store.db.execute('UPDATE studio_state SET generation=1')
        for folder in ('inbox','processing'):
            p=self.c.bridge.root/'human'/folder/'takeover.json';p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'human control'):self.authorization()
            p.unlink()

    def test_missing_changed_duplicate_and_agent_channel_grants_refuse(self):
        raw=self.original.read_bytes();self.original.unlink()
        with self.assertRaisesRegex(ValueError,'retained native'):self.authorization()
        self.original.write_bytes(raw)
        other=self.archive/'human-grant.other.json';other.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'Exactly one'):self.authorization()
        other.unlink()
        self.original.write_text(json.dumps(self.request|dict(command='control.takeover')))
        with self.assertRaisesRegex(ValueError,'differs'):self.authorization()
        self.original.write_bytes(raw)
        self.c.store.db.execute('UPDATE studio_receipts SET payload_hash=? WHERE request_id=?',
                               (sha(dict(request=self.request,actor='agent')),'human-grant'))
        with self.assertRaisesRegex(ValueError,'receipt'):self.authorization()

    def test_trading_positions_orders_live_or_disconnected_native_observation_refuse(self):
        for key,value in [('demo',False),('connected',False),('account_matches',False),('algo_trading',True),
                          ('positions',1),('orders',1),('tester_state','running')]:
            old=self.native[key];self.native[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'idle demo'):self.authorization()
            self.native[key]=old

    def test_native_monitor_must_confirm_current_generation(self):
        self.c.runtime.side_effect=lambda **kw:(dict(owner='agent',revision=0,generation=0),{})
        with self.assertRaisesRegex(ValueError,'monitor'):self.authorization()

    def test_recovery_owner_route_retains_authority_without_human_confirmation(self):
        before=self.c.state(); review=prepare(self.c)['review_id']
        result=apply(self.c,review,owner_research=True)
        self.assertEqual(result['status'],'published_not_recovered')
        self.assertEqual(self.c.state(),before)
        proof=json.loads((self.c.root/'owner-research-audit'/('orphan-recovery-apply-'+review+'.json')).read_text())
        self.assertEqual(proof['revocation_epoch'],1)
        issued=(self.c.local/'native-gate/request.json').read_bytes()
        self.assertEqual(apply(self.c,review,owner_research=True)['status'],'reconcile_required')
        self.assertEqual((self.c.local/'native-gate/request.json').read_bytes(),issued)

    def test_foreign_native_control_still_blocks_owner_route(self):
        review=prepare(self.c)['review_id']
        p=self.c.local/'foreign/controller.json';p.parent.mkdir();p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'foreign'):apply(self.c,review,owner_research=True)
        self.assertFalse((self.c.local/'native-gate/permit.json').exists())

    def test_owner_settlement_preserves_native_refusal_and_never_clears_flag(self):
        review=prepare(self.c)['review_id'];apply(self.c,review,owner_research=True)
        self.fixture.consume(review,'ORPHAN_FOREIGN_CONTROL',consumed=False)
        plan=json.loads(plan_path(self.c,review).read_text())
        gate=self.c.local/'native-gate';before=self.c.state()
        result_path=gate/('result-'+plan['record']['request']['request_id']+'.json')
        native_result=result_path.read_bytes()
        with patch('studio_orphan_rejection.time.time',return_value=plan['record']['request']['expires_utc']+1):
            result=reconcile_rejection(self.c,review,owner_research=True)
        self.assertEqual(result['status'],'rejected_settled')
        self.assertEqual(result_path.read_bytes(),native_result)
        self.assertEqual(self.c.state(),before);self.assertTrue(self.fixture.flags)
        self.assertFalse((gate/'permit.json').exists())
        self.assertTrue((self.c.root/'owner-research-audit'/('orphan-recovery-reconcile-rejection-'+review+'.json')).is_file())

    def test_owner_settlement_never_replays_consumption(self):
        review=prepare(self.c)['review_id'];apply(self.c,review,owner_research=True)
        self.fixture.consume(review,'ORPHAN_FOREIGN_CONTROL',consumed=True)
        plan=json.loads(plan_path(self.c,review).read_text())
        with patch('studio_orphan_rejection.time.time',return_value=plan['record']['request']['expires_utc']+1):
            with self.assertRaisesRegex(ValueError,'consumption'):
                reconcile_rejection(self.c,review,owner_research=True)
        self.assertTrue((self.c.root/'orphan-recovery-pending.json').exists())
        self.assertTrue((self.c.local/'native-gate/permit.json').exists())

    def test_pending_takeover_during_native_probe_stops_authorization(self):
        def probe(unused):
            (self.c.bridge.root/'human/inbox/takeover.json').write_text('{}')
            return dict(self.native)
        with patch('studio_owner_research.inspect_idle_demo',side_effect=probe):
            with self.assertRaisesRegex(ValueError,'Pending human control appeared'):self.authorization()

    def test_legacy_confirmation_remains_required_and_routes_cannot_mix(self):
        review=prepare(self.c)['review_id']
        with self.assertRaisesRegex(ValueError,'Explicit user'):apply(self.c,review)
        with self.assertRaisesRegex(ValueError,'one explicit'):apply(self.c,review,confirmed=True,owner_research=True)


class DirectDemoRecoveryTests(OwnerResearchTests):
    def recovery_agent(self, legacy=False):
        from demo_agent import DemoAgent
        agent=DemoAgent.__new__(DemoAgent);agent.root=self.c.root
        agent._exclusive=lambda:nullcontext();agent._append=Mock()
        binding=self.c.binding();patch.object(self.c,'binding',return_value=binding).start()
        @contextmanager
        def scoped(*args,**kwargs):
            if legacy:
                from studio_research_authority import demo_agent_scope, operation
                with operation('demo-recover-orphan'), demo_agent_scope(root=self.c.root,
                        installation_sha256=sha(self.c.install), account=self.c.session['account'], legacy_recovery=True):
                    yield self.c,dict(demo=True,algo_trading=False)
            else:
                with self.direct():yield self.c,dict(demo=True,algo_trading=False)
        agent._studio=scoped
        return agent

    @contextmanager
    def direct(self, operation_name='demo-recover-orphan', account=None):
        from studio_research_authority import demo_agent_scope, operation
        c=self.c
        c.session.update(authority_kind='demo_direct',demo_only=True,
                         account=account or dict(login='3000082754',server='Darwinex-Demo'))
        write_json(c.root/'session.json',c.session)
        with operation(operation_name), demo_agent_scope(root=c.root,
                installation_sha256=sha(c.install),account=c.session['account']):
            yield

    def test_direct_wrapper_publishes_once_and_reconciles_without_grant_or_start(self):
        from demo_agent import DemoAgent
        agent=DemoAgent.__new__(DemoAgent);agent.root=self.c.root
        agent._exclusive=lambda:nullcontext();agent._append=Mock()
        binding=self.c.binding()
        patch.object(self.c,'binding',return_value=binding).start()
        @contextmanager
        def scoped(*args,**kwargs):
            with self.direct():yield self.c,dict(demo=True,algo_trading=False)
        agent._studio=scoped
        with self.direct():before=self.c.state()
        result=agent.recover_orphan(wait_seconds=0);review=result['review_id']
        self.assertEqual(result['status'],'published_not_recovered')
        request=(self.fixture.gate/'request.json').read_bytes()
        self.assertEqual(agent.recover_orphan(wait_seconds=0)['status'],'reconcile_required')
        self.assertEqual((self.fixture.gate/'request.json').read_bytes(),request)
        self.fixture.consume(review);self.fixture.flags=False
        self.assertEqual(agent.recover_orphan(review)['status'],'recovered')
        with self.direct():self.assertEqual(self.c.state(),before)
        proof=json.loads((self.c.root/'owner-research-audit'/('orphan-recovery-apply-'+review+'.json')).read_text())
        self.assertEqual(proof['authorization'],'broker_verified_demo_recovery')
        self.assertFalse(proof['human_confirmation_fabricated'])

    def test_direct_requires_fresh_adapter_scope_and_only_exact_operation(self):
        with self.direct():self.assertEqual(self.authorization()['revocation_epoch'],1)
        with self.assertRaisesRegex(ValueError,'broker-verified'):self.authorization()
        with self.direct('run-batch'),self.assertRaisesRegex(ValueError,'only for'):self.authorization()
        with self.direct(),self.assertRaisesRegex(ValueError,'only for'):
            authorize(self.c,'owner-maintenance-prepare','a'*32)

    def test_direct_recovery_uses_the_current_paired_customer_scope(self):
        with self.direct(account=dict(login='55500012345',server='Customer-Demo')):
            proof=self.authorization()
            self.assertEqual(proof['authorization'],'broker_verified_demo_recovery')
            self.assertEqual(proof['grant_request_id'],'human-grant')

    def test_direct_changed_archived_grant_human_owner_and_takeover_refuse(self):
        with self.direct():
            raw=self.original.read_bytes();self.original.write_text('{}')
            with self.assertRaisesRegex(ValueError,'differs'):self.authorization()
            self.original.write_bytes(raw)
            self.c.store.db.execute("UPDATE studio_state SET owner='human'")
            with self.assertRaisesRegex(ValueError,'TAKE CONTROL|revoked'):self.authorization()
            self.c.store.db.execute("UPDATE studio_state SET owner='agent'")
            (self.c.bridge.root/'human/inbox/takeover.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'human control'):self.authorization()

    def test_direct_nonidle_or_trading_native_state_refuses(self):
        with self.direct():
            for key,value in [('demo',False),('connected',False),('account_matches',False),
                              ('algo_trading',True),('positions',1),('orders',1),('tester_state','running')]:
                old=self.native[key];self.native[key]=value
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'same idle demo'):self.authorization()
                self.native[key]=old

    def test_direct_live_worker_refuses_before_recovery_publication(self):
        from demo_agent import DemoAgent
        agent=DemoAgent.__new__(DemoAgent);agent.root=self.c.root
        agent._exclusive=lambda:nullcontext();agent._append=Mock();agent._worker_alive=Mock(return_value=True)
        worker=self.c.root/'demo-agent/workers/active.json';worker.parent.mkdir(parents=True);worker.write_text('{}')
        @contextmanager
        def scoped(*args,**kwargs):yield self.c,dict(demo=True)
        agent._studio=scoped
        with self.assertRaisesRegex(ValueError,'live demo driver'):agent.recover_orphan()
        self.assertFalse((self.fixture.gate/'permit.json').exists())
        agent._append.assert_not_called()

    def test_direct_one_command_waits_for_native_receipt_and_delayed_readback(self):
        from demo_agent import DemoAgent
        from studio_orphan_recovery import status as real_status
        agent=DemoAgent.__new__(DemoAgent);agent.root=self.c.root
        agent._exclusive=lambda:nullcontext();agent._append=Mock()
        binding=self.c.binding();patch.object(self.c,'binding',return_value=binding).start()
        @contextmanager
        def scoped(*args,**kwargs):
            with self.direct():yield self.c,dict(demo=True,algo_trading=False)
        agent._studio=scoped
        calls=[]
        def observe(c,review):
            calls.append(review)
            if len(calls)==1:
                self.fixture.consume(review)
                raise ValueError('Runtime policy mismatch: batch_ongoing')
            self.fixture.flags=False
            return real_status(c,review)
        with patch('studio_orphan_recovery.status',side_effect=observe),patch('demo_agent.time.sleep'):
            result=agent.recover_orphan()
        self.assertEqual(result['status'],'recovered')
        self.assertEqual(len(set(calls)),1)
        self.assertEqual(len(list(self.fixture.gate.glob('issued-*.json'))),1)

    def rejected_review(self, *, consumed=False):
        agent=self.recovery_agent()
        with self.direct():
            review=prepare(self.c)['review_id'];apply(self.c,review,confirmed=True)
        self.fixture.consume(review,'ORPHAN_REVIEW_REJECTED',consumed=consumed)
        plan=json.loads(plan_path(self.c,review).read_text())
        return agent,review,plan

    def test_edward_expired_review_rejection_retained_then_one_fresh_successor(self):
        agent,original,plan=self.rejected_review()
        request_id=plan['record']['request']['request_id']
        request=(self.fixture.gate/'request.json').read_bytes()
        receipt=(self.fixture.gate/('result-'+request_id+'.json')).read_bytes()
        with self.direct():before=self.c.state()
        with patch('studio_orphan_rejection.time.time',return_value=plan['record']['request']['expires_utc']+1):
            result=agent.recover_orphan(wait_seconds=0)
        successor=result['review_id']
        self.assertNotEqual(successor,original)
        self.assertEqual(result['status'],'published_not_recovered')
        old=json.loads(plan_path(self.c,original).read_text())
        self.assertEqual(old['status'],'rejected_settled')
        retained=plan_path(self.c,original).parent/'rejection-settlement'
        self.assertEqual((retained/'request.json').read_bytes(),request)
        self.assertEqual((retained/'result.json').read_bytes(),receipt)
        self.assertEqual((self.fixture.gate/('result-'+request_id+'.json')).read_bytes(),receipt)
        self.assertEqual(len(list(self.fixture.gate.glob('issued-*.json'))),2)
        with self.direct():self.assertEqual(self.c.state(),before)
        new_request=(self.fixture.gate/'request.json').read_bytes()
        self.assertEqual(agent.recover_orphan(wait_seconds=0)['status'],'reconcile_required')
        self.assertEqual((self.fixture.gate/'request.json').read_bytes(),new_request)
        self.fixture.consume(successor,'ORPHAN_REVIEW_REJECTED',consumed=False)
        result=agent.recover_orphan(wait_seconds=0)
        self.assertFalse(result['automatic_successor_available'])
        self.assertEqual(len(list(self.fixture.gate.glob('issued-*.json'))),2)

    def test_consumed_refusal_never_settles_or_reissues(self):
        agent,review,plan=self.rejected_review(consumed=True)
        original=(self.fixture.gate/'request.json').read_bytes()
        result=agent.recover_orphan(wait_seconds=0)
        self.assertEqual(result['status'],'reconcile_required')
        self.assertEqual((self.fixture.gate/'request.json').read_bytes(),original)
        self.assertEqual(len(list(self.fixture.gate.glob('issued-*.json'))),1)
        self.assertFalse((plan_path(self.c,review).parent/'rejection-settlement').exists())

    def test_explicit_observation_and_unexpired_refusal_do_not_replace(self):
        agent,review,plan=self.rejected_review()
        self.assertEqual(agent.recover_orphan(review,wait_seconds=0)['status'],'reconcile_required')
        with self.assertRaisesRegex(ValueError,'expired'):
            agent.recover_orphan(wait_seconds=0)
        self.assertEqual(len(list(self.fixture.gate.glob('issued-*.json'))),1)

    def test_existing_customer_review_can_recover_without_session_or_binary_adoption(self):
        agent=self.recovery_agent(legacy=True)
        before=(self.c.root/'session.json').read_bytes()
        review=prepare(self.c)['review_id'];apply(self.c,review,confirmed=True)
        self.fixture.consume(review,'ORPHAN_REVIEW_REJECTED',consumed=False)
        plan=json.loads(plan_path(self.c,review).read_text())
        with patch('studio_orphan_rejection.time.time',return_value=plan['record']['request']['expires_utc']+1):
            result=agent.recover_orphan(wait_seconds=0)
        self.assertEqual(result['status'],'published_not_recovered')
        self.assertNotEqual(result['review_id'],review)
        self.assertEqual((self.c.root/'session.json').read_bytes(),before)
        self.assertEqual(self.c.session.get('authority_kind'),'native_human_control')

    def test_legacy_scope_is_recovery_only_and_cannot_reserve_or_grant(self):
        from studio_research_authority import demo_agent_scope, operation, require_demo_agent_scope
        scope=dict(root=self.c.root,installation_sha256=sha(self.c.install),account=self.c.session['account'],legacy_recovery=True)
        with operation('run-batch'),demo_agent_scope(**scope),self.assertRaisesRegex(ValueError,'broker-verified'):
            require_demo_agent_scope(self.c.root,self.c.install,self.c.session)
        with operation('demo-recover-orphan'),demo_agent_scope(**scope):
            with self.assertRaisesRegex(ValueError,'exact agent job'):
                self.c.submit('queue.reserve',dict(job_id='foreign'),'foreign-reserve')

    def test_real_adapter_opens_legacy_recovery_without_adopting_session(self):
        from demo_agent import DemoAgent, digest
        c=self.c;agent=DemoAgent(c.root/'installation.json')
        broker=dict(process=dict(pid=123,created_utc='fixed'),login=c.session['account']['login'],
                    server=c.session['account']['server'],demo=True,algo_trading=False)
        before=(c.root/'session.json').read_bytes()
        def readback(expected):
            agent.state_root.mkdir(parents=True,exist_ok=True)
            write_json(agent.state_root/'verified-build.json',dict(ea_sha256=expected,process=broker['process']))
        with patch.object(agent,'_owner_clear'),patch.object(agent,'_space'),patch.object(agent,'_broker',return_value=broker),patch.object(agent,'_readback_current',side_effect=readback) as verified:
            with agent._studio('demo-recover-orphan',idle=True,recovery=True) as (opened,_):
                self.assertEqual(opened.state()['owner'],'agent')
                self.assertEqual(opened.session.get('authority_kind'),'native_human_control')
            verified.assert_called_once_with(digest(agent.binary))
            with self.assertRaisesRegex(ValueError,'Install and verify'):
                with agent._studio('run-batch',idle=True):pass
        self.assertEqual((c.root/'session.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
