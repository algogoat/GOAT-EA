"""Real file/bridge/store renewal transitions; native probes remain fixtures."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from campaign_ledger import packed,sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_research_authority import authority,operation
import test_studio_research_authority as fixtures


class ResearchRegrantTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ResearchAuthorityTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.addCleanup(patch.stopall)
        self.f.boot();self.c=self.f.c
        self.binding=packed(dict(terminal_id=self.c.terminal,run_id=self.c.run))
        self.base=read_json(self.c.root/'research-authority.json')
        self.original=(self.c.root/'research-authority.json').read_bytes()
        self.session=(self.c.root/'session.json').read_bytes()
        patch('studio_research_regrant.OWNER_ACCOUNT',self.c.session['account']).start()
        self.native=dict(demo=True,connected=True,algo_trading=False,positions=0,orders=0,
                         account_matches=True,tester_state='idle',process=dict(pid=42,created_utc='fixture'))
        self.probe=patch('studio_research_regrant.inspect_idle_demo',side_effect=lambda c:dict(self.native)).start()
        self.observation=patch('studio_resilient_read.read_observation',side_effect=self.feedback).start()

    def state(self):
        return self.c.store.snapshot(self.c.terminal,self.c.run,human_channel_view=True)

    def feedback(self,path):
        i=self.c.install
        state=self.state()
        return dict(owner=state['owner'],revision=state['revision'],generation=state['generation'],
            schema_version=1,bound=True,loaded=True,pending_id='',tester_ini='tester',export_ini='export',
            observed_terminal_utc=datetime.now(timezone.utc).strftime('%Y.%m.%d %H:%M:%S'),
            runtime=dict(data_path=i['terminal_data_root'],installation_path=str(Path(i['terminal_executable']).parent),
                program_path=str((Path(i['terminal_data_root'])/'MQL5/Experts'/i['ea_relative_path'].replace('\\','/')).resolve()),
                account_login=self.c.session['account']['login'],account_server=self.c.session['account']['server'],
                connected=True,account_demo=True,terminal_trade_allowed=False,batch_ongoing=False,
                restart_pending=False,tester_state='idle')),time.time()

    def request(self,command,ident):
        state=self.state()
        return dict(schema_version=1,request_id=ident,terminal_id=self.c.terminal,run_id=self.c.run,
                    expected_revision=state['revision'],generation=state['generation'],command=command,payload={})

    def send(self,request,actor='human'):
        write_json(self.c.bridge.root/actor/'inbox'/(request['request_id']+'.json'),request)
        with operation('serve'):return self.c.bridge.pump()[0]

    def take(self):
        request=self.request('control.takeover','native-takeover')
        self.assertTrue(self.send(request)['ok'])
        state=self.state()
        write_json(self.c.bridge.root/'human/ui-draft.json',dict(schema_version=1,terminal_id=self.c.terminal,
            run_id=self.c.run,revision=state['revision'],generation=state['generation'],
            tester_ini='tester',export_ini='export',baseline='testerexport',submitted=''))
        return request

    def grant(self):
        request=self.request('control.grant_agent','native-new-grant')
        return request,self.send(request)

    def test_real_takeover_then_real_grant_is_additive_and_old_scope_stays_unchanged(self):
        self.take()
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'revoked'):self.c.state()
        request,result=self.grant();self.assertTrue(result['ok'])
        state=self.state();self.assertEqual((state['owner'],state['generation']),('agent',self.base['generation']+2))
        with operation('prepare-batch'):scope=authority(self.c.store.db,self.binding,state)
        self.assertEqual(scope['renewal']['grant_request'],request)
        self.assertEqual(scope['expires_utc']-scope['created_utc'],172800)
        self.assertEqual(scope['renewal']['original_authority_sha256'],sha(self.base))
        self.assertEqual((self.c.root/'research-authority.json').read_bytes(),self.original)
        self.assertEqual((self.c.root/'session.json').read_bytes(),self.session)
        self.assertEqual(json.loads(self.c.store.db.execute('SELECT provenance FROM studio_authorities').fetchone()[0]),self.base)
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],1)
        for statement in ('DELETE FROM studio_research_epochs',"UPDATE studio_research_epochs SET provenance='{}'"):
            with self.assertRaisesRegex(Exception,'immutable'):self.c.store.db.execute(statement)

    def test_grant_without_preceding_takeover_and_agent_impersonation_refuse(self):
        _,result=self.grant();self.assertFalse(result['ok'])
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],0)
        self.take()
        self.assertFalse(self.send(self.request('control.grant_agent','agent-grant'),'agent')['ok'])
        self.assertEqual(self.state()['owner'],'human')

    def test_cli_actor_string_without_native_processing_request_refuses(self):
        self.take();request=self.request('control.grant_agent','not-a-native-click')
        with operation('serve'),self.assertRaisesRegex(ValueError,'Genuine native processing'):
            self.c.store.submit(request,actor='human')
        self.assertEqual(self.state()['owner'],'human')

    def test_unarchived_takeover_cannot_authorize_new_epoch(self):
        self.take()
        for path in (self.c.bridge.root/'human/archive').glob('native-takeover.*.json'):path.unlink()
        _,result=self.grant();self.assertFalse(result['ok'])
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],0)

    def test_wrong_account_and_algo_on_refuse_without_new_epoch(self):
        self.take()
        with patch('studio_research_regrant.OWNER_ACCOUNT',{'login':'different','server':'different'}):
            self.assertFalse(self.send(self.request('control.grant_agent','wrong-account'))['ok'])
        self.native['algo_trading']=True
        self.assertFalse(self.send(self.request('control.grant_agent','algo-on'))['ok'])
        self.assertEqual(self.state()['owner'],'human')
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],0)

    def test_stale_native_revision_refuses_before_grant(self):
        self.take();original=self.feedback
        def stale(path):
            value,stamp=original(path);return value|dict(revision=value['revision']-1),stamp
        self.observation.side_effect=stale
        _,result=self.grant();self.assertFalse(result['ok'])
        self.probe.assert_not_called()
        self.assertEqual(self.state()['owner'],'human')

    def test_later_takeover_revokes_new_epoch_and_old_grant_replay_cannot_revive_it(self):
        self.take();request,result=self.grant();self.assertTrue(result['ok'])
        self.assertTrue(self.send(self.request('control.takeover','second-takeover'))['ok'])
        state=self.state()
        # Receipt replay is transport idempotency; it must not rewrite state.
        self.assertTrue(self.send(request)['ok'])
        self.assertEqual(self.state(),state)
        with operation('prepare-batch'),self.assertRaisesRegex(ValueError,'revoked'):self.c.state()
        self.assertFalse(self.send(self.request('control.grant_agent','third-grant'))['ok'])
        self.assertEqual(self.c.store.db.execute('SELECT COUNT(*) FROM studio_research_epochs').fetchone()[0],1)

    def test_other_session_native_feedback_is_not_readiness_for_this_grant(self):
        self.take()
        path=self.c.bridge.root/'human/ui-draft.json';write_json(path,read_json(path)|dict(run_id='other-session'))
        _,result=self.grant();self.assertFalse(result['ok'])
        self.probe.assert_not_called()
        self.assertEqual(self.state()['owner'],'human')


if __name__=='__main__':unittest.main()
