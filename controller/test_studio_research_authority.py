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

    def test_fresh_frozen_queue_publishes_complete_native_settings_without_editor_mutation(self):
        from studio_bridge import display_state
        import copy
        self.boot()
        with operation('prepare-batch'):prepare_batch(self.c,'fresh-queued',self.plan)
        with operation('state'):
            state=self.c.state();before=copy.deepcopy(state)
            self.assertIsNone(state['tester_draft']);self.assertIsNone(state['export_draft'])
            actual=read_json(self.c.bridge.root/'snapshot.json')['state']
            expected=state['queue'][0]['configuration']
            self.assertEqual(actual['tester_draft'],expected['tester'])
            self.assertEqual(actual['export_draft'],expected['export'])
            self.assertEqual(self.c.state(),before)
            human=copy.deepcopy(state)
            human['tester_draft']=expected['tester']|{'Symbol':'GBPUSD'}
            human['export_draft']=expected['export']
            self.assertEqual(display_state(human)['tester_draft']['Symbol'],'GBPUSD')
            altered=copy.deepcopy(state);altered['queue'][0]['configuration']['tester']['Symbol']='USDJPY'
            with self.assertRaisesRegex(ValueError,'configuration changed'):display_state(altered)
            partial=copy.deepcopy(state);partial['tester_draft']=expected['tester']
            self.assertIsNone(display_state(partial)['export_draft'])

    def test_expired_driver_keeps_supervision_but_cannot_reserve_or_dispatch(self):
        self.boot()
        with operation('prepare-batch'):prepare_batch(self.c,'frozen-batch',self.plan)
        value=read_json(self.c.root/'research-authority.json')
        from studio_research_authority import command
        with operation('run-batch'),patch('studio_research_authority.time.time',return_value=value['expires_utc']+1):
            state=self.c.state()
            binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
            # Cancellation stays authorized in the same retained driver scope.
            command(self.c.store.db,binding,state,dict(command='queue.cancel',payload={'job_id':'frozen-batch'}),'agent')
            with self.assertRaisesRegex(ValueError,'no new reservation'):
                command(self.c.store.db,binding,state,dict(command='queue.reserve',payload={'job_id':'frozen-batch'}),'agent')
            with self.assertRaisesRegex(ValueError,'no native dispatch'):
                before_native_dispatch(self.c,self.c.job('frozen-batch'))

    def test_running_driver_crosses_authority_expiry_and_cancels_at_deadline(self):
        import test_studio_batch_driver as driver_fixtures
        self.boot()
        expiry=read_json(self.c.root/'research-authority.json')['expires_utc']
        fixture=driver_fixtures.BatchDriverTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.c.clock.wall=expiry-1
        original=fixture.c.state
        def scoped_state():
            self.c.state()  # Real store authority checked on each driver observation.
            return original()
        fixture.c.state=scoped_state
        with operation('run-batch'),patch('studio_research_authority.time.time',side_effect=fixture.c.clock.time):
            result=fixture.drive(max_seconds=3)
        self.assertEqual(result['status'],'cancelled')
        self.assertTrue(result['stopped'])
        self.assertEqual((fixture.c.starts,fixture.c.cancels),(1,1))

    def test_legacy_human_grant_classifies_atomically_without_agent_fallback(self):
        from studio_command_store import StudioStore
        db=StudioStore(self.folder/'legacy.sqlite')
        self.addCleanup(db.close)
        state=db.bind('legacy','run')
        db.db.execute('DROP TRIGGER IF EXISTS studio_authority_immutable_delete')
        db.db.execute('DELETE FROM studio_authorities')
        request=dict(schema_version=1,request_id='real-human',terminal_id='legacy',run_id='run',
            expected_revision=state['revision'],generation=state['generation'],command='control.grant_agent',payload={})
        with self.assertRaisesRegex(ValueError,'Human control'):
            db.submit(request,actor='agent')
        self.assertEqual(db.db.execute('SELECT COUNT(*) FROM studio_authorities').fetchone()[0],0)
        bad=request|{'expected_revision':99}
        with self.assertRaisesRegex(ValueError,'Stale state'):db.submit(bad,actor='human')
        self.assertEqual(db.db.execute('SELECT COUNT(*) FROM studio_authorities').fetchone()[0],0)
        db.submit(request,actor='human')
        self.assertEqual(db.snapshot('legacy','run')['owner'],'agent')
        self.assertEqual(db.db.execute('SELECT kind FROM studio_authorities').fetchone()[0],'native_human_control')
        db.db.execute('DROP TRIGGER IF EXISTS studio_authority_immutable_delete')
        db.db.execute('DELETE FROM studio_authorities')
        with self.assertRaisesRegex(ValueError,'no classified authority'):db.snapshot('legacy','run')

    def test_unknown_operation_and_missing_or_unknown_authority_fail_closed(self):
        self.boot()
        for name in ('seed-start','new-future-operation',None):
            with operation(name),self.assertRaisesRegex(ValueError,'allowlisted'):
                self.c.state()
        with self.assertRaisesRegex(Exception,'immutable'):
            self.c.store.db.execute("UPDATE studio_authorities SET kind='native_human_control'")
        with self.assertRaisesRegex(Exception,'immutable'):
            self.c.store.db.execute('DELETE FROM studio_authorities')
        with self.assertRaisesRegex(Exception,'immutable'):
            self.c.store.db.execute("INSERT OR REPLACE INTO studio_authorities SELECT binding,'native_human_control','{}' FROM studio_authorities")
        # Deliberately damage the DB below to test refusal independent of triggers.
        self.c.store.db.execute('DROP TRIGGER studio_authority_immutable_update')
        self.c.store.db.execute('DROP TRIGGER studio_authority_immutable_delete')
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

    def test_human_takeover_revokes_original_and_non_owner_cannot_regrant(self):
        self.boot()
        with operation('state'):
            state=self.c.state()
            request=dict(schema_version=1,request_id='takeover',terminal_id=self.c.terminal,run_id=self.c.run,
                         expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
            self.c.store.submit(request,actor='human')
            now=self.c.state();self.assertEqual(now['owner'],'human')
            self.assertGreater(now['generation'],state['generation'])
            request.update(request_id='cannot-regrant',expected_revision=now['revision'],generation=now['generation'],command='control.grant_agent')
            with self.assertRaisesRegex(ValueError,'Owner demo research renewal scope required'):
                self.c.store.submit(request,actor='human')
            self.assertEqual(self.c.state(),now)
            self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],0)
        with operation('run-batch'),self.assertRaisesRegex(ValueError,'permanently revoked'):
            self.c.state()

    def test_legacy_agent_receipt_migrates_and_restored_human_is_classified(self):
        import test_studio_owner_research as owner_fixtures
        from studio_command_store import StudioStore
        fixture=owner_fixtures.OwnerResearchTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        c=fixture.c
        session=read_json(c.root/'session.json');session.pop('authority_kind',None)
        write_json(c.root/'session.json',session)
        c.store.db.execute('DROP TRIGGER studio_authority_immutable_delete')
        c.store.db.execute('DELETE FROM studio_authorities')
        # Pre-migration read-only dispatch can verify the archived human grant.
        with operation('start'):dispatch(c,SimpleNamespace(operation='start'))
        c.store.close()
        c.store=StudioStore(c.root/'studio.sqlite')
        self.assertEqual(c.state()['owner'],'agent')
        self.assertEqual(c.store.db.execute('SELECT kind FROM studio_authorities').fetchone()[0],'native_human_control')
        # PARK revokes the generation; legacy restored human state remains human.
        c.store.db.execute('DROP TRIGGER studio_authority_immutable_delete')
        c.store.db.execute('DELETE FROM studio_authorities')
        c.store.db.execute("UPDATE studio_state SET owner='human',generation=generation+1")
        c.store.close();c.store=StudioStore(c.root/'studio.sqlite')
        self.assertEqual(c.state()['owner'],'human')
        self.assertEqual(c.store.db.execute('SELECT kind FROM studio_authorities').fetchone()[0],'native_human_control')

    def test_human_channel_takeover_survives_unclassified_agent_authority(self):
        self.boot()
        with operation('state'):state=self.c.state()
        self.c.store.db.execute('DROP TRIGGER studio_authority_immutable_delete')
        self.c.store.db.execute('DELETE FROM studio_authorities')
        request=dict(schema_version=1,request_id='real-takeover',terminal_id=self.c.terminal,run_id=self.c.run,
            expected_revision=state['revision'],generation=state['generation'],command='control.takeover',payload={})
        write_json(self.c.bridge.root/'human/inbox/real-takeover.json',request)
        with operation('serve'):
            self.assertTrue(self.c.bridge.pump()[0]['ok'])
        with operation('state'):self.assertEqual(self.c.state()['owner'],'human')

    def test_takeover_allows_reviewed_human_park_and_restore(self):
        self.boot()
        with operation('prepare-batch'):prepare_batch(self.c,'human-cancel',self.plan)
        with operation('state'):
            state=self.c.state()
            self.c.store.submit(dict(schema_version=1,request_id='takeover-park',terminal_id=self.c.terminal,
                run_id=self.c.run,expected_revision=state['revision'],generation=state['generation'],
                command='control.takeover',payload={}),actor='human')
        with operation('cancel'):
            state=self.c.state()
            self.c.store.submit(dict(schema_version=1,request_id='human-cancel',terminal_id=self.c.terminal,
                run_id=self.c.run,expected_revision=state['revision'],generation=state['generation'],
                command='queue.cancel',payload={'job_id':'human-cancel'}),actor='human')
            self.assertEqual(self.c.job('human-cancel')['status'],'cancelled')
        # Real handover journals; only stopped-process probe is a fixture.
        with patch('studio_handover.stopped'),operation('switch-plan'):
            park_id=review(self.c)['review_id']
            dispatch(self.c,SimpleNamespace(operation='switch-plan'))
        self.c.store.close();self.c.store=None
        with patch('studio_handover.stopped'),operation('switch-apply'):
            dispatch(self.c,SimpleNamespace(operation='switch-apply',confirm_reviewed=True))
            apply(self.c,park_id,confirmed=True)
        with patch('studio_handover.stopped'),operation('switch-plan'):
            restore_id=review(self.c,park_id)['review_id']
        with patch('studio_handover.stopped'),operation('switch-apply'):
            apply(self.c,restore_id,confirmed=True)
        with operation('state'):
            self.c.open()
            self.assertEqual(self.c.state()['owner'],'human')

    def test_confirmation_flags_and_native_downgrade_are_refused(self):
        self.boot()
        for name in ('orphan-recovery-apply','orphan-recovery-reconcile-rejection'):
            with operation(name),self.assertRaisesRegex(ValueError,'human-confirmation'):
                dispatch(self.c,SimpleNamespace(operation=name,confirm_reviewed=True))
        from studio_orphan_recovery import apply as recover
        from studio_orphan_rejection import reconcile_rejection
        for fn in (recover,reconcile_rejection):
            with self.assertRaisesRegex(ValueError,'human-confirmation'):
                fn(self.c,'a'*32,confirmed=True)
        self.c.store.db.execute('DROP TRIGGER studio_authority_immutable_update')
        binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_authorities SET kind=?,provenance=?',
            ('native_human_control',packed(dict(kind='native_human_control',binding=json.loads(binding)))))
        with operation('seed-start'),self.assertRaisesRegex(ValueError,'cannot downgrade'):self.c.state()

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
        with operation('start'),self.assertRaisesRegex(ValueError,'live bounded'):
            before_native_dispatch(self.c,self.c.job('frozen-batch'))
        driver=self.c.root/'batch-drivers/frozen-batch.json'
        driver.parent.mkdir(exist_ok=True)
        intent=dict(status='start_issued',start_issued=True,attempt_id=None,binding=dict(job_id='frozen-batch'))
        write_json(driver,intent)
        with operation('run-batch'):
            job=self.c.job('frozen-batch')
            for key,value in [('algo_trading',True),('demo',False),('positions',1),('account_matches',False),('connected',False)]:
                with patch('studio_monitor_probe.inspect_idle_demo',return_value=native|{key:value}):
                    with self.assertRaisesRegex(ValueError,'Algo OFF'):
                        before_native_dispatch(self.c,job)
            with patch('studio_monitor_probe.inspect_idle_demo',return_value=native):
                before_native_dispatch(self.c,job)
            write_json(driver,intent|dict(status='start_uncertain'))
            with self.assertRaisesRegex(ValueError,'retained failed'):
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
