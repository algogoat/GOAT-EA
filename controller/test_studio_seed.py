import copy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from xml.sax.saxutils import escape

from studio_installation import read_json
from studio_seed import SeedRunner
from studio_seed_results import collect,HEADERS
from studio_seed_slot import guard_active_seed


def xml_result(member,rows):
    props={'Title':member['output_base'],'Author':'GOAT SeedFarming','Server':member['account']['server'],'Mode':'SeedFarming','Target':str(member['frame_target']),'Strategy':member['alias']}
    def row(values):return '<Row>'+''.join('<Cell><Data ss:Type="'+('Number' if isinstance(v,(int,float)) else 'String')+'">'+escape(str(v))+'</Data></Cell>' for v in values)+'</Row>'
    axes=list(member['axes']) if rows else []
    return ('<?xml version="1.0" encoding="UTF-8"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><DocumentProperties xmlns="urn:schemas-microsoft-com:office:office">'+''.join('<'+k+'>'+escape(v)+'</'+k+'>' for k,v in props.items())+'</DocumentProperties><Worksheet ss:Name="Tester Optimizator Results"><Table>'+row(HEADERS+axes)+''.join(row(r) for r in rows)+'</Table></Worksheet></Workbook>').encode()


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.now=1000000.0;self.process_state=dict(pid=10,executable='terminal64.exe',created_utc='first');self.starts=[];self.closes=[];self.auto=False
        self.controller=SimpleNamespace(root=self.root/'controller',local=self.root/'local')
        self.controller.root.mkdir();(self.controller.local/'native-gate').mkdir(parents=True)
        data=self.root/'terminal';binary=data/'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5';binary.parent.mkdir(parents=True);binary.write_bytes(b'ex5')
        self.controller.install=dict(terminal_data_root=str(data),common_files_root=str(self.root/'common'),terminal_executable=str(data/'terminal64.exe'),ea_relative_path='GOAT-EA\\GOAT V1.48.ex5',ea_version='1.48',ea_sha256=hashlib.sha256(b'ex5').hexdigest())
        self.controller.session=dict(account={'login':'123','server':'Test-Demo'})
        self.controller.schema={'source_sha256':'a'*64,'inputs':{'EA_Desc':dict(type='string',optimizable=False),'Period':dict(type='int',optimizable=True),'Size':dict(type='double',optimizable=True)}}
        self.controller.policy=dict(header_sha256='a'*64,main_sha256='b'*64,coverage='indicator_mode_gates_only',rules=[])
        self.owner=dict(owner='agent',generation=1,queue=[])
        self.controller.state=lambda:copy.deepcopy(self.owner)
        self.controller.bridge=SimpleNamespace(pump=lambda:None)
        self.controller.runtime=lambda **kw:({'loaded':True,'owner':self.owner['owner'],'generation':self.owner['generation']}, {})
        self.process=SimpleNamespace(inspect=lambda:copy.deepcopy(self.process_state),close=self.close,start=self.start)
        self.runner=SeedRunner(self.controller,process=self.process,clock=lambda:self.now,sleep=self.sleep)
        self.source=self.root/'source.set';self.source.write_bytes('; Source header\r\nEA_Desc=Original\r\nPeriod=10||10||5||20||Y\r\nSize=1.5\r\n'.encode('utf-16'))
        tester=dict(Expert=self.controller.install['ea_relative_path'],Symbol='EURUSD',Period='H1',Model=4,ExecutionMode=0,Optimization=2,OptimizationCriterion=6,FromDate='2026.01.01',ToDate='2026.03.01',ForwardMode=0,ForwardDate='',Deposit=10000,Currency='USD',Leverage='1:100',UseLocal=1,UseRemote=0,UseCloud=0,Visual=0)
        self.plan=dict(schema_version=1,max_attempts_per_job=1,job_timeout_seconds=30,cutoff=dict(min_fitness=0,min_trades=1),jobs=[dict(set_path=str(self.source),tester=tester,frame_target=2)])

    def tearDown(self):self.tmp.cleanup()
    def close(self,identity):
        self.assertEqual(identity,self.process_state);self.closes.append(identity);self.process_state=None
    def start(self,config):
        self.assertIsNone(self.process_state);self.starts.append(config)
        self.process_state=dict(pid=10+len(self.starts),executable='terminal64.exe',created_utc='run'+str(len(self.starts)))
        return copy.deepcopy(self.process_state)
    def sleep(self,seconds):
        self.now+=seconds
        if self.auto and self.starts and self.process_state:
            manifest=read_json(self.runner.path('batch')/'manifest.json');member=manifest['members'][len(self.starts)-1]
            self.output(member);self.process_state=None
    def prepare(self):return self.runner.prepare('batch',self.plan)
    def member(self,index=0):return read_json(self.runner.path('batch')/'manifest.json')['members'][index]
    def output(self,member,rows=None,suffix=None):
        rows=[[1,4,10,2,2,2,2,4,1,10,10],[2,-2,0,0,0,0,0,-2,0,0,15]] if rows is None else rows
        suffix=suffix or ('_N2_AvgFit=1.000_Health=50.00_Zero=1_AvgTrades=5.0_Best=4.000.xml' if rows else '_N0_AvgFit=0.000_Health=0.00_Zero=0_AvgTrades=0.0_Best=0.000.xml')
        path=Path(self.controller.install['common_files_root'])/'GOAT/SeedFarmingXML'/(member['output_base']+suffix);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(xml_result(member,rows));return path

    def test_prepare_preserves_source_and_only_tags_description(self):
        original=self.source.read_bytes();result=self.prepare();m=self.member()
        self.assertEqual(self.source.read_bytes(),original);self.assertEqual(result['status'],'prepared');self.assertFalse(self.starts)
        new=Path(m['set_path']).read_bytes();self.assertTrue(new.startswith(b'\xff\xfe'))
        self.assertIn('@{mode=SeedFarming,n=2,from=2026.01.01,to=2026.03.01}',new.decode('utf-16'))
        ini=Path(m['config_path']).read_text(encoding='utf-16');self.assertIn('ShutdownTerminal=1',ini);self.assertIn('AllowLiveTrading=0',ini);self.assertNotIn('Password',ini)
        self.assertNotIn('BatchOnGoing',ini)

    def test_matrix_complete_with_exact_candidate_values(self):
        second=copy.deepcopy(self.plan['jobs'][0]);second['tester']['Symbol']='GBPUSD';self.plan['jobs'].append(second)
        self.prepare();self.auto=True;state=self.runner.start('batch',10)
        self.assertEqual(state['status'],'completed');self.assertEqual(len(self.starts),2)
        self.assertEqual(len(self.closes),1);guard_active_seed(self.controller.root)
        result=self.runner.report('batch');row=result['members'][0]
        self.assertEqual(row['actual_frames'],2);self.assertEqual(row['result']['summary']['health_percent'],50)
        self.assertEqual(row['result']['summary']['qualifying_count'],1)
        self.assertEqual(row['result']['candidates'][0]['values']['Size'],'1.5')
        self.assertEqual(row['result']['candidates'][0]['values']['Period'],'10')
        self.runner.resume('batch',1);self.assertEqual(len(self.starts),2)

    def test_resume_running_does_not_restart_and_missing_output_is_null(self):
        self.prepare();state=self.runner.start('batch',1);self.assertTrue(state['driver_budget_exhausted']);self.assertEqual(len(self.starts),1)
        self.runner.resume('batch',1);self.assertEqual(len(self.starts),1)
        self.process_state=None;state=self.runner.status('batch');self.assertEqual(state['members'][0]['status'],'missing_output')
        self.assertIsNone(self.runner.report('batch')['members'][0]['actual_frames'])
        self.runner.resume('batch',1);self.assertEqual(len(self.starts),1)

    def test_zero_frame_native_result_is_explicit_zero(self):
        self.prepare();m=self.member();result=collect(self.output(m,[]),m,self.controller.schema,self.plan['cutoff'])
        self.assertEqual(result['summary']['actual_frames'],0)

    def test_output_identity_axes_range_and_metrics_fail_closed(self):
        self.prepare();m=self.member();path=self.output(m)
        wrong=copy.deepcopy(m);wrong['account']['server']='Other'
        with self.assertRaisesRegex(ValueError,'metadata'):collect(path,wrong,self.controller.schema,self.plan['cutoff'])
        text=path.read_text();path.write_text(text.replace('>Period<','>Unknown<'))
        with self.assertRaisesRegex(ValueError,'axes'):collect(path,m,self.controller.schema,self.plan['cutoff'])
        path=self.output(m,[[1,4,10,2,2,2,2,4,1,10,11],[2,-2,0,0,0,0,0,-2,0,0,15]])
        with self.assertRaisesRegex(ValueError,'ladder'):collect(path,m,self.controller.schema,self.plan['cutoff'])
        path=self.output(m,suffix='_N2_AvgFit=2.000_Health=50.00_Zero=1_AvgTrades=5.0_Best=4.000.xml')
        with self.assertRaisesRegex(ValueError,'metrics'):collect(path,m,self.controller.schema,self.plan['cutoff'])

    def test_plan_rejects_forward_duplicate_and_invalid_axes(self):
        for change in ('forward','duplicate','axis'):
            plan=copy.deepcopy(self.plan)
            if change=='forward':plan['jobs'][0]['tester']['ForwardMode']=1
            if change=='duplicate':plan['jobs'].append(copy.deepcopy(plan['jobs'][0]))
            if change=='axis':self.source.write_bytes(self.source.read_bytes().replace('20||Y'.encode('utf-16-le'),'21||Y'.encode('utf-16-le')))
            with self.assertRaises(ValueError):self.runner.prepare('bad'+change,plan)
            self.assertFalse(self.runner.path('bad'+change).exists())

    def test_human_grant_and_native_queue_block_first_close(self):
        self.prepare();self.owner['owner']='human'
        with self.assertRaisesRegex(ValueError,'grant'):self.runner.start('batch',1)
        self.owner['owner']='agent';self.owner['queue']=[{'status':'running'}]
        with self.assertRaisesRegex(ValueError,'Unresolved'):self.runner.start('batch',1)
        self.assertFalse(self.closes);self.assertFalse(self.starts)

    def test_revoked_generation_and_changed_process_do_not_close(self):
        self.prepare();self.runner.start('batch',1);self.owner['generation']=2
        with self.assertRaisesRegex(ValueError,'grant'):self.runner.resume('batch',1)
        with self.assertRaisesRegex(ValueError,'grant'):self.runner.cancel('batch')
        self.owner['generation']=1;self.process_state['pid']=999
        state=self.runner.status('batch');self.assertEqual(state['status'],'reconcile_required')
        with self.assertRaisesRegex(ValueError,'provenance'):self.runner.cancel('batch')
        self.assertEqual(len(self.closes),1)

    def test_timeout_and_cancel_never_retry(self):
        self.prepare();self.runner.start('batch',1);self.now+=31
        state=self.runner.resume('batch',2);self.assertEqual(state['members'][0]['status'],'timeout');self.assertEqual(len(self.starts),1)
        self.assertEqual(len(self.closes),2)

    def test_prepared_cancel_never_closes_existing_terminal(self):
        self.prepare();state=self.runner.cancel('batch');self.assertTrue(state['stop_verified']);self.assertFalse(self.closes)
        self.assertEqual(state['status'],'stopped')

    def test_running_cancel_requires_exit_before_releasing_slot(self):
        self.prepare();self.runner.start('batch',1);self.runner.cancel('batch')
        state=self.runner.status('batch');self.assertEqual(state['members'][0]['status'],'cancelled');guard_active_seed(self.controller.root)

    def test_uncertain_launch_retains_slot_and_no_retry(self):
        self.prepare()
        def failed(config):raise OSError('unknown start result')
        self.process.start=failed
        with self.assertRaises(OSError):self.runner.start('batch',1)
        self.assertEqual(self.runner.status('batch')['status'],'reconcile_required')
        with self.assertRaises(ValueError):guard_active_seed(self.controller.root)
        self.runner.resume('batch',1);self.assertFalse(self.starts)

    def test_frozen_material_and_completed_evidence_cannot_change(self):
        self.prepare();m=self.member();Path(m['set_path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'material'):self.runner.start('batch',1)
        self.assertFalse(self.closes)

    def test_completed_evidence_revalidated_before_resume(self):
        self.prepare();self.auto=True;self.runner.start('batch',5);m=self.member();self.output(m).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'completed seed evidence'):self.runner.resume('batch',1)


if __name__=='__main__':unittest.main()
