"""Public CLI integration against private synthetic installation receipts only."""
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import goat_studio
import test_goat_studio as fixtures


class SeedCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PortableControllerTests();self.fixture.setUp()
        c=self.fixture.bound();self.schema,self.policy=c.schema,c.policy
        c.store.close();c.store=None
        self.source=self.fixture.root/'Seed source.set'
        self.source.write_bytes('; Real layout\r\nEA_Desc=Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        self.plan=dict(schema_version=1,max_attempts_per_job=1,job_timeout_seconds=30,
            cutoff=dict(min_fitness=0,min_trades=1),jobs=[dict(set_path=str(self.source),
                tester=self.fixture.tester|{'ForwardMode':0,'ForwardDate':''},frame_target=2)])
        self.plan_path=self.fixture.root/'seed-plan.json';self.plan_path.write_text(json.dumps(self.plan))
        self.process=SimpleNamespace(inspect=Mock(return_value=None),
            start=Mock(side_effect=AssertionError('No native launch allowed in CLI test')),
            close=Mock(side_effect=AssertionError('No native close allowed in CLI test')))

    def tearDown(self):self.fixture.tearDown()

    def cli(self,*args):
        output=io.StringIO()
        with patch.object(goat_studio,'contracts',return_value=(self.schema,self.policy)),patch('studio_seed_process.WindowsSeedProcess',return_value=self.process),redirect_stdout(output):
            code=goat_studio.main(['--installation',str(self.fixture.path),*args])
        return code,json.loads(output.getvalue())

    def prepare(self):return self.cli('seed-prepare','--batch-id','cli-matrix','--plan',str(self.plan_path))

    def test_discovery_exposes_every_seed_command_and_driver_limits(self):
        code,result=self.cli('discover');self.assertEqual(code,0)
        info=result['result']
        for operation in ('seed-prepare','seed-start','seed-resume','seed-status','seed-cancel','seed-report'):
            self.assertIn(operation,info['operations']);self.assertIn(operation,info['operation_contracts'])
        self.assertEqual(info['operation_contracts']['seed-start']['defaults']['max-seconds'],60)
        self.assertEqual(info['operation_contracts']['seed-resume']['limits']['max-seconds'],[1,3600])
        self.assertFalse(info['execution_ready'])

    def test_help_exposes_only_declared_seed_driver_flags(self):
        output=io.StringIO()
        with redirect_stdout(output),self.assertRaises(SystemExit) as raised:
            goat_studio.main(['--installation','unused.json','seed-resume','--help'])
        self.assertEqual(raised.exception.code,0)
        self.assertIn('--batch-id',output.getvalue());self.assertIn('--max-seconds',output.getvalue())
        self.assertNotIn('--force',output.getvalue())

    def test_prepare_routes_full_plan_and_creates_real_frozen_material(self):
        before=self.source.read_bytes();code,response=self.prepare();self.assertEqual(code,0,response)
        result=response['result'];self.assertEqual(result['status'],'prepared')
        manifest=json.loads(Path(result['manifest_path']).read_text())
        member=manifest['members'][0]
        self.assertEqual(member['frame_target'],2);self.assertEqual(member['tester']['ForwardMode'],0)
        self.assertIn('mode=SeedFarming',Path(member['set_path']).read_text(encoding='utf-16'))
        self.assertEqual(self.source.read_bytes(),before);self.assertEqual(list(self.fixture.common.iterdir()),[])
        self.process.start.assert_not_called();self.process.close.assert_not_called()

    def test_unknown_plan_field_and_duplicate_json_fail_as_structured_errors(self):
        self.plan_path.write_text(json.dumps(self.plan|{'force':True}))
        code,result=self.prepare();self.assertEqual(code,2);self.assertFalse(result['ok'])
        self.plan_path.write_text('{"schema_version":1,"schema_version":1}')
        code,result=self.prepare();self.assertEqual(code,2);self.assertIn('Duplicate',result['error'])
        self.assertFalse((Path(self.fixture.receipt['controller_state_root'])/'seeds/cli-matrix').exists())

    def test_start_routes_real_human_gate_without_process_effects(self):
        self.assertEqual(self.prepare()[0],0)
        code,result=self.cli('seed-start','--batch-id','cli-matrix','--max-seconds','1')
        self.assertEqual(code,2);self.assertIn('grant',result['error'])
        self.process.start.assert_not_called();self.process.close.assert_not_called()

    def test_driver_bounds_reject_before_native_effects(self):
        for operation in ('seed-start','seed-resume'):
            for budget in ('0','3601'):
                code,result=self.cli(operation,'--batch-id','unused','--max-seconds',budget)
                self.assertEqual(code,2);self.assertIn('max_seconds',result['error'])
        self.process.start.assert_not_called();self.process.close.assert_not_called()

    def test_status_and_report_keep_missing_results_unknown(self):
        self.assertEqual(self.prepare()[0],0)
        code,result=self.cli('seed-status','--batch-id','cli-matrix');self.assertEqual(code,0)
        self.assertEqual(result['result']['members'][0]['status'],'pending')
        code,result=self.cli('seed-report','--batch-id','cli-matrix');self.assertEqual(code,0)
        member=result['result']['members'][0]
        self.assertIsNone(member['actual_frames']);self.assertEqual(member['tester']['ForwardMode'],0)
        self.assertEqual(len(member['frozen_set_sha256']),64);self.assertEqual(len(member['config_sha256']),64)

    def test_start_resume_defaults_and_cancel_dispatch_exact_arguments(self):
        runner=Mock()
        for operation in ('start','resume','cancel'):getattr(runner,operation).return_value={'synthetic_route_only':True}
        with patch('studio_seed.SeedRunner',return_value=runner):
            for operation in ('start','resume'):
                self.assertEqual(self.cli('seed-'+operation,'--batch-id','selected')[0],0)
                getattr(runner,operation).assert_called_once_with('selected',max_seconds=60)
            self.assertEqual(self.cli('seed-cancel','--batch-id','selected')[0],0)
            runner.cancel.assert_called_once_with('selected')

    def test_undeclared_force_flag_is_rejected_by_parser(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as raised:
            goat_studio.main(['--installation',str(self.fixture.path),'seed-start','--batch-id','x','--force'])
        self.assertEqual(raised.exception.code,2)
        self.process.start.assert_not_called()


if __name__=='__main__':unittest.main()
