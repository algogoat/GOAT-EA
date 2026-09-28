"""Restricted owner continuation: real file/store/upgrade fixtures, no native MT5."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from campaign_ledger import packed,sha
from goat_studio import Controller
from studio_bridge import write_json
from studio_build_upgrade import replace_build
from studio_handover import apply,review,paths
from studio_installation import read_json
from studio_owner_continuation import prepare_install,bootstrap
from studio_owner_maintenance import directory
from studio_research_authority import operation,dispatch,before_native_dispatch
from studio_batch import prepare_batch
import test_studio_owner_maintenance as maintenance_fixtures


class ResearchAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=maintenance_fixtures.OwnerMaintenanceTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        patch('studio_owner_continuation.stopped').start()
        patch('studio_installation_upgrade.stopped').start()
        patch('studio_owner_continuation.POLICY_PATH',self.fixture.fixture.policy_path).start()
        self.old=self.fixture.c
        self.folder=self.old.root.parent
        source=self.folder/'continuation-template.set'
        source.write_bytes('EA_Desc=Frozen Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        portable=self.fixture.fixture.fixture.fixture
        spec=dict(schema_version=1,export=portable.exports,members=[dict(set_path=str(source),
            tester=portable.tester|{'Expert':self.old.install['ea_relative_path']})])
        self.plan=self.folder/'frozen-plan.json';self.plan.write_text(json.dumps(spec),encoding='utf-8')
        self.ea=self.folder/'new.ex5';self.ea.write_bytes(b'corrective9 fixture')
        self.fixture.policy['maintenance']['target_ea_sha256']=hashlib.sha256(self.ea.read_bytes()).hexdigest()
        self.fixture.policy['maintenance']['plan_sha256']=hashlib.sha256(self.plan.read_bytes()).hexdigest()
        write_json(self.fixture.fixture.policy_path,self.fixture.policy)
        self.fixture.mint();self.record_id=self.fixture.record_id;self.fixture.stop()
        self.review_id=review(self.old)['review_id']
        apply(self.old,self.review_id,owner_maintenance=self.record_id)
        self.intent=prepare_install(self.old,self.record_id)
        candidate=self.folder/'candidate-installation.json'
        write_json(candidate,self.old.install|dict(ea_sha256=hashlib.sha256(self.ea.read_bytes()).hexdigest()))
        old_sha=hashlib.sha256((self.old.root/'installation.json').read_bytes()).hexdigest()
        with patch('studio_installation_upgrade.stopped'):
            replace_build(self.old.root/'installation.json',self.review_id,candidate,self.ea,old_sha)
        self.c=Controller(self.old.root/'installation.json')
        self.c.schema,self.c.policy=self.old.schema,self.old.policy
        patch('studio_owner_continuation.saved_launch_policy').start()
        patch('studio_installation_upgrade.stopped').start()
        self.addCleanup(lambda:self.c.store.close() if self.c.store else None)

    def boot(self):
        with operation('owner-maintenance-bootstrap'):
            result=bootstrap(self.c,self.record_id,self.plan)
        with operation('state'):self.c.open()
        return result

    def test_exact_install_bootstrap_creates_typed_authority_not_human_grant(self):
        result=self.boot()
        self.assertEqual(result['authority_kind'],'research_continuation')
        self.assertFalse(result['human_grant_created'])
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_receipts').fetchone()[0],0)
        with operation('state'):
            self.assertEqual(self.c.state()['owner'],'agent')
        with operation('owner-maintenance-bootstrap'),self.assertRaisesRegex(ValueError,'retired'):
            bootstrap(self.c,self.record_id,self.plan)

    def test_unknown_operation_and_missing_or_unknown_authority_fail_closed(self):
        self.boot()
        for name in ('seed-start','new-future-operation',None):
            with operation(name),self.assertRaisesRegex(ValueError,'allowlisted'):
                self.c.state()
        self.c.store.db.execute("UPDATE studio_authorities SET kind='unrecognized'")
        with operation('state'),self.assertRaisesRegex(ValueError,'Unknown authority'):
            self.c.state()
        self.c.store.db.execute('DELETE FROM studio_authorities')
        with operation('state'),self.assertRaisesRegex(ValueError,'no classified authority'):
            self.c.state()

    def test_only_exact_frozen_plan_and_members_can_be_prepared(self):
        self.boot()
        changed=self.folder/'changed-plan.json';changed.write_text('{}')
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'exact frozen'):
            dispatch(self.c,SimpleNamespace(operation='prepare-batch',plan=changed))
        with operation('prepare-batch'):
            result=prepare_batch(self.c,'frozen-batch',self.plan)
            self.assertFalse(result['native_started'])
            self.assertEqual(len(self.c.state()['queue']),1)
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'once'):
            prepare_batch(self.c,'second-batch',self.plan)

    def test_human_takeover_permanently_ends_continuation_and_cannot_regrant(self):
        self.boot()
        with operation('state'):
            state=self.c.state()
            request=dict(schema_version=1,request_id='takeover',terminal_id=self.c.terminal,run_id=self.c.run,
                         expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
            self.c.store.submit(request,actor='human')
            now=self.c.state();self.assertEqual(now['owner'],'human')
            self.assertGreater(now['generation'],state['generation'])
            request.update(request_id='cannot-regrant',expected_revision=now['revision'],generation=now['generation'],command='control.grant_agent')
            with self.assertRaisesRegex(ValueError,'promote'):
                self.c.store.submit(request,actor='human')
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'permanently revoked'):
            self.c.state()

    def test_changed_session_authority_and_forged_install_refuse(self):
        journal=paths(self.old)[2]/self.review_id/'build-upgrade.json'
        data=read_json(journal);write_json(journal,data|dict(candidate_ea_sha256='0'*64))
        with operation('owner-maintenance-bootstrap'),self.assertRaisesRegex(ValueError,'completion evidence'):
            bootstrap(self.c,self.record_id,self.plan)
        self.assertFalse((self.c.root/'session.json').exists())
        write_json(journal,data);self.boot()
        session=read_json(self.c.root/'session.json');session.pop('authority_kind')
        write_json(self.c.root/'session.json',session)
        with operation('state'),self.assertRaisesRegex(ValueError,'Required session'):
            self.c.state()

    def test_bootstrap_crash_after_session_write_reconciles_exact_intent(self):
        from studio_owner_continuation import retain
        def interrupt(path,raw):
            retain(path,raw)
            if path==self.c.root/'session.json':raise OSError('session published')
        with operation('owner-maintenance-bootstrap'),patch('studio_owner_continuation.retain',side_effect=interrupt):
            with self.assertRaises(OSError):bootstrap(self.c,self.record_id,self.plan)
        self.assertEqual(self.boot()['status'],'research_continuation_bootstrapped')

    def test_algo_off_and_same_demo_are_checked_before_native_dispatch(self):
        self.boot()
        with operation('prepare-batch'):prepare_batch(self.c,'frozen-batch',self.plan)
        native=dict(demo=True,connected=True,account_matches=True,algo_trading=False,positions=0,orders=0,tester_state='idle')
        with operation('start'):
            job=self.c.job('frozen-batch')
            for key,value in [('algo_trading',True),('demo',False),('positions',1),('account_matches',False),('connected',False)]:
                with patch('studio_monitor_probe.inspect_idle_demo',return_value=native|{key:value}):
                    with self.assertRaisesRegex(ValueError,'Algo OFF'):
                        before_native_dispatch(self.c,job)
            with patch('studio_monitor_probe.inspect_idle_demo',return_value=native):
                before_native_dispatch(self.c,job)

    def test_bootstrap_saved_algo_or_login_refusal_has_no_session_effect(self):
        with operation('owner-maintenance-bootstrap'),patch('studio_owner_continuation.saved_launch_policy',side_effect=ValueError('Algo OFF required')):
            with self.assertRaisesRegex(ValueError,'Algo OFF'):
                bootstrap(self.c,self.record_id,self.plan)
        self.assertFalse((self.c.root/'session.json').exists())

    def test_template_change_under_same_plan_path_cannot_widen_research(self):
        self.boot()
        spec=json.loads(self.plan.read_text())
        source=Path(spec['members'][0]['set_path'])
        source.write_bytes(source.read_bytes().replace('0.3'.encode('utf-16-le'),'0.4'.encode('utf-16-le')))
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'immutable research'):
            prepare_batch(self.c,'changed',self.plan)
        with operation('state'):self.assertEqual(self.c.state()['queue'],[])

    def test_recovery_checks_original_typed_scope_and_pending_takeover(self):
        from studio_research_authority import recovery_authorization
        self.boot()
        with operation('orphan-recovery-apply'):
            self.c.runtime=lambda **kw:(dict(owner='agent',revision=0,generation=0),{})
            native=dict(demo=True,connected=True,account_matches=True,algo_trading=False,positions=0,orders=0,tester_state='idle')
            with patch('studio_monitor_probe.inspect_idle_demo',return_value=native):
                proof=recovery_authorization(self.c,'orphan-recovery-apply','a'*32)
                self.assertEqual(proof['authorization'],'research_continuation')
                self.assertFalse(proof['human_confirmation_fabricated'])
                takeover=self.c.bridge.root/'human/inbox/takeover.json';takeover.write_text('{}')
                with self.assertRaisesRegex(ValueError,'permanently revoked'):
                    recovery_authorization(self.c,'orphan-recovery-apply','a'*32)
                takeover.unlink()
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'permanently revoked'):
            self.c.state()


if __name__=='__main__':unittest.main()
