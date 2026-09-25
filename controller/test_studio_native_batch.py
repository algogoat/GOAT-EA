"""Real multi-member packages and receipts; no native terminal is launched."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from campaign_ledger import packed,sha
from prepare_native_campaign import prepare,native_run_relative
from studio_batch_contract import configuration_members
from studio_launch_intent import record_intent
from studio_native_observe import observe
from studio_native_request import _validate_material
from studio_report_observe import observe_reports
from studio_report_paths import report_paths
from native_control_transaction import begin,NAMES

class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture=importlib.import_module('test_goat_studio').PortableControllerTests()
        self.fixture.setUp();self.c=self.fixture.bound();self.fixture.grant(self.c)
        original=self.fixture.prepare(self.c);base=Path(original['package'])
        first=copy.deepcopy(self.c.job('beta-job')['configuration']);second=copy.deepcopy(first)
        second['tester']['Symbol']='BROKER_GOLD'
        self.config=copy.deepcopy(first)|dict(batch_members=[first,second])
        plan=json.loads((base/'studio-plan.json').read_text())
        plan['studio_source']['configuration_sha256']=sha(self.config)
        second_job=copy.deepcopy(plan['jobs'][0]);second_job['symbol']='BROKER_GOLD';plan['jobs'].append(second_job)
        plan['native_batch']['run_relative']=native_run_relative(plan)
        self.plan=plan;self.package=self.c.root/'packages/native-multi';planpath=self.c.root/'multi-plan.json';planpath.write_text(json.dumps(plan))
        self.manifest=prepare(planpath,self.c.root/'templates.sqlite',self.package)
        (self.package/'studio-plan.json').write_text(json.dumps(plan))
        state=self.c.state();job=state['queue'][0];job['configuration']=self.config;job['configuration_sha256']=sha(self.config)
        self.c.store.db.execute('UPDATE studio_queues SET jobs=?',(packed(state['queue']),))
        self.c.submit('queue.reserve',dict(job_id='beta-job',configuration_sha256=sha(self.config),package_sha256=hashlib.sha256((self.package/'manifest.json').read_bytes()).hexdigest()),'multi-reserve')
        state=self.c.state();self.intent=record_intent(self.c.store,self.c.terminal,self.c.run,'beta-job',self.package,actor='agent',revision=state['revision'],generation=state['generation'])
        self.native=self.fixture.common/self.manifest['native_run_relative'].replace('\\','/')
        shutil.copytree(self.package,self.native)

    def tearDown(self):self.fixture.tearDown()

    def queue(self,states):
        raw=(self.package/'queue.GOAT').read_bytes().decode('utf-16')
        parts=[entry for entry in raw.split('\x1f') if entry.strip()]
        content='\x1f\r\n'.join(entry.replace(';Pending_',';'+state+'_',1).strip() for entry,state in zip(parts,states))+'\x1f\r\n'
        (self.native/'queue.GOAT').write_bytes(content.encode('utf-16'))

    def test_progress_tracks_every_file_asset_member(self):
        self.queue(['Completed','OnGoing']);result=observe(self.package)
        self.assertEqual(result['status'],'native_ongoing');self.assertEqual(result['member_count'],2)
        self.assertEqual(result['completed_count'],1);self.assertEqual(result['active_indices'],[1])
        self.assertEqual(result['members'][1]['symbol'],'BROKER_GOLD')
        self.assertEqual(result['members'][0]['status'],'native_completed')

    def test_first_queued_rest_pending_is_launchable_status(self):
        self.queue(['Queued','Pending']);result=observe(self.package)
        self.assertEqual(result['status'],'native_queued');self.assertEqual(result['finished_count'],0)

    def test_second_member_input_drift_rejected(self):
        second=self.manifest['jobs'][1]['run_alias']
        (self.native/'inputs'/second/'Inputs.GOAT').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'input drift'):observe(self.package)

    def test_member_order_or_missing_rows_rejected(self):
        queue=self.native/'queue.GOAT';text=queue.read_bytes().decode('utf-16');parts=[p for p in text.split('\x1f') if p.strip()]
        queue.write_bytes(('\x1f'.join(reversed(parts))+'\x1f').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'identity/order'):observe(self.package)
        queue.write_bytes((parts[0]+'\x1f').encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'member count'):observe(self.package)

    def test_material_verifies_all_members_and_keeps_first_paste(self):
        args=self.c.native_args();args.pop('observation_path')
        result=_validate_material(self.c.state(),self.c.job('beta-job'),**args)
        self.assertEqual(len(result['members']),2)
        self.assertEqual(result['sections']['Tester']['Symbol'],'BROKER_EURUSD')
        self.assertEqual(result['members'][1]['sections']['Tester']['Symbol'],'BROKER_GOLD')
        second=self.manifest['jobs'][1]['run_alias'];(self.package/(second+'.set')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SET/INI drift'):_validate_material(self.c.state(),self.c.job('beta-job'),**args)

    def test_report_paths_cover_both_members(self):
        one=report_paths(self.plan,self.manifest,0);two=report_paths(self.plan,self.manifest,1)
        self.assertNotEqual(one['common_back'],two['common_back']);self.assertEqual(one['common_run'],two['common_run'])
        self.assertIn('BROKER_GOLD',str(two['common_back']))
        result=observe_reports(self.package,self.config,self.c.schema)
        self.assertEqual(result['status'],'batch_reports_pending');self.assertEqual(len(result['members']),2)

    def test_partial_cancel_keeps_completed_report_obligation(self):
        self.queue(['Completed','Cancelled']);result=observe(self.package)
        self.assertEqual(result['status'],'native_cancelled');self.assertEqual(result['finished_count'],2)
        reports=observe_reports(self.package,self.config,self.c.schema,member_statuses=['native_completed','native_cancelled'])
        self.assertEqual(reports['status'],'batch_reports_pending')
        self.assertEqual(reports['members'][0]['status'],'reports_pending')
        self.assertEqual(reports['members'][1]['native_status'],'native_cancelled')

    def test_complete_or_error_outcome_is_not_first_member_only(self):
        self.queue(['Completed','Error']);self.assertEqual(observe(self.package)['status'],'native_error')
        self.queue(['Completed','Completed']);self.assertEqual(observe(self.package)['status'],'native_completed')
        self.queue(['Completed','Pending']);self.assertEqual(observe(self.package)['status'],'native_pending')

    def test_aggregate_cannot_disagree_with_first_member_or_export_policy(self):
        changed=copy.deepcopy(self.config);changed['tester']['Symbol']='OTHER'
        with self.assertRaisesRegex(ValueError,'First native member'):configuration_members(changed)
        changed=copy.deepcopy(self.config);changed['batch_members'][1]['export']['IncludeSequenceData']=True
        with self.assertRaisesRegex(ValueError,'share the frozen export'):configuration_members(changed)

    def test_activation_allocates_all_report_paths_and_queues_first_only(self):
        from studio_open_activation import activate_open
        # Remove only the fixture-created copied native package; activation must
        # create its own namespace. This directory is beneath our temp fixture.
        self.assertTrue(self.native.is_relative_to(self.fixture.root));shutil.rmtree(self.native)
        args=self.c.native_args();material=_validate_material(self.c.state(),self.c.job('beta-job'),**{k:v for k,v in args.items() if k!='observation_path'})
        evidence=self.c.root/'attempts'/self.intent['attempt_id'];evidence.parent.mkdir()
        with patch('studio_open_activation.validate_launch_material',return_value=material),patch('studio_open_activation.revalidate_processes',return_value={}),patch('studio_open_activation.validate_activated_job',return_value={'verified':'fixture'}):
            activate_open(self.c.state(),self.c.job('beta-job'),**args,evidence=evidence,process_baseline={},validate_ownership=lambda *args:None)
        self.assertEqual([m['status'] for m in observe(self.package)['members']],['native_queued','native_pending'])
        for index,item in enumerate(self.manifest['jobs']):
            paths=report_paths(self.plan,self.manifest,index)
            self.assertTrue(paths['local_back'].parent.is_dir());self.assertTrue(paths['common_back'].parent.is_dir())
            self.assertEqual((self.native/'inputs'/item['run_alias']/'config.ini').read_bytes(),(self.package/(item['run_alias']+'.ini')).read_bytes())

if __name__=='__main__':unittest.main()
