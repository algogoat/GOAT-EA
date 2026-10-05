import copy
import hashlib
from pathlib import Path
import tempfile
import json
import sqlite3
from unittest.mock import patch
import studio_seed
import studio_seed_results
from types import SimpleNamespace
import unittest
from xml.sax.saxutils import escape

from studio_bridge import write_json
from studio_installation import read_json
from studio_seed import SeedRunner
from studio_seed_results import collect,HEADERS
from studio_seed_slot import guard_active_seed


def xml_result(member,rows):
    props={'Title':member['xml_title'],'Author':'GOAT SeedFarming','Server':member['account']['server'],'Mode':'SeedFarming','Target':str(member['frame_target']),'Strategy':member['alias']}
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
        self.assertEqual(row['actual_frames'],2);self.assertEqual(row['summary']['health_percent'],50)
        self.assertEqual(row['summary']['qualifying_count'],1)
        result=read_json(row['result_path']);candidate=result['candidates'][0]
        exact=result['base_values']|candidate['value_overrides']
        self.assertEqual(exact['Size'],'1.5')
        self.assertEqual(exact['Period'],'10')
        self.assertNotIn('Size',candidate['value_overrides'])
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

    def test_filename_and_metadata_match_actual_ea_source_rules(self):
        source=(Path(__file__).parents[1]/'GOAT V1.48.mq5').read_text(encoding='utf-8-sig')
        self.assertIn('string strategy=SeedFarmingSafePart(Strat);',source)
        self.assertIn('" "+range+" "+Strat;',source)
        for index,(symbol,period) in enumerate([('EURUSD.pro','M5'),('US500#','H4'),('GER40 cash','MN1')]):
            plan=copy.deepcopy(self.plan);plan['jobs'][0]['tester'].update(Symbol=symbol,Period=period)
            self.runner.prepare('naming'+str(index),plan)
            member=studio_seed_results.read_seed_json(self.runner.path('naming'+str(index))/'manifest.json',studio_seed_results.MAX_MANIFEST_BYTES)['members'][0]
            prefix='GOAT V1.48 '+symbol+','+period+' 2026.01.01-2026.03.01 '
            self.assertEqual(member['output_base'],prefix+member['alias'].replace('_',''))
            self.assertEqual(member['xml_title'],prefix+member['alias'])
            self.assertEqual(collect(self.output(member),member,self.controller.schema,self.plan['cutoff'])['summary']['actual_frames'],2)

    def test_aggregate_input_budget_rejects_before_any_staged_files(self):
        with patch.object(studio_seed,'MAX_RETAINED_INPUT_BYTES',1):
            with self.assertRaisesRegex(ValueError,'128 MiB'):self.prepare()
        self.assertFalse(self.runner.path('batch').exists())
        self.assertFalse((Path(self.controller.install['terminal_data_root'])/'config/GOATStudio/Seeds').exists())

    def test_seed_json_streaming_bound_duplicates_and_supported_large_payload(self):
        file=self.root/'json.json';file.write_text(' '*2_000_001+'{"value":1}')
        self.assertEqual(studio_seed_results.read_seed_json(file),{'value':1})
        with self.assertRaisesRegex(ValueError,'byte bound'):studio_seed_results.read_seed_json(file,20)
        file.write_text('{"value":1,"value":2}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):studio_seed_results.read_seed_json(file)

    def test_candidate_result_budget_is_explicit_and_never_truncates_silently(self):
        self.prepare();member=self.member()
        with patch.object(studio_seed_results,'MAX_RESULT_BYTES',1):
            with self.assertRaisesRegex(ValueError,'candidate evidence'):collect(self.output(member),member,self.controller.schema,self.plan['cutoff'])

    def test_cancel_requires_its_exact_terminal_slot_before_close(self):
        self.prepare();self.runner.start('batch',1)
        slot=read_json(self.runner.slot);slot['batch_id']='other';self.runner.slot.write_text(json.dumps(slot))
        with self.assertRaisesRegex(ValueError,'ownership receipt differs'):self.runner.cancel('batch')
        self.assertEqual(len(self.closes),1)

    def test_foreign_run_native_reservation_blocks_seed_close(self):
        self.prepare();db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE studio_queues(jobs TEXT)');db.execute('INSERT INTO studio_queues VALUES(?)',(json.dumps([{'status':'reserved'}]),))
        self.controller.store=SimpleNamespace(db=db)
        with self.assertRaisesRegex(ValueError,'Unresolved'):self.runner.start('batch',1)
        self.assertFalse(self.closes)

    def test_state_member_truncation_cannot_release_seed_ownership(self):
        self.prepare();self.runner.start('batch',1);file=self.runner.path('batch')/'state.json'
        state=read_json(file);state['members']=[];file.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'identity/count'):self.runner.status('batch')
        with self.assertRaises(ValueError):guard_active_seed(self.controller.root)

    def test_public_reports_reference_complete_candidate_artifacts(self):
        self.prepare();self.auto=True;self.runner.start('batch',5)
        with patch.object(studio_seed,'MAX_PUBLIC_MEMBERS',0):
            reply=self.runner.report('batch');self.assertTrue(reply['members_omitted']);self.assertNotIn('members',reply)
        report=studio_seed_results.read_seed_json(reply['report_path']);row=report['members'][0]
        self.assertNotIn('result',row);self.assertEqual(row['actual_frames'],2)
        artifact=studio_seed_results.read_seed_json(row['result_path'],studio_seed_results.MAX_RESULT_BYTES)
        self.assertEqual(len(artifact['candidates']),2);self.assertEqual(artifact['base_values']['Size'],'1.5')

    def test_completed_evidence_revalidated_before_resume(self):
        self.prepare();self.auto=True;self.runner.start('batch',5);m=self.member();self.output(m).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'completed seed evidence'):self.runner.resume('batch',1)


class MemberFailureTests(unittest.TestCase):
    """goatai#1885 (T2 seedhunt-t2-4-b41 / t2-6-b41): a member that ends without a result fails only itself.

    Claude-Mac's rules (5989126739): the batch continues with its pending members; it stops after 3 attempted
    members in a row failed, or once failures reach half of at least 4 attempted members, with stopped_reason
    listing every reason. Cancelled still stops. seed-resume re-activates a batch stopped by failures under
    first-start checks; completed and failed members are never re-run, and a status read never re-activates.
    """
    setUp=SeedTests.setUp;tearDown=SeedTests.tearDown;close=SeedTests.close;start=SeedTests.start
    prepare=SeedTests.prepare;member=SeedTests.member;output=SeedTests.output
    MONITOR=dict(pid=10,executable='terminal64.exe',created_utc='first')

    def matrix(self,count,fail=()):
        """``count`` members on distinct symbols; members whose index is in ``fail`` exit with no output."""
        base=self.plan['jobs'][0];self.plan['jobs']=[]
        for index in range(count):
            job=copy.deepcopy(base);job['tester']['Symbol']='SYM'+str(index);self.plan['jobs'].append(job)
        self.fail=set(fail);self.prepare();self.auto=True

    def sleep(self,seconds):
        self.now+=seconds
        if self.auto and self.starts and self.process_state:
            index=len(self.starts)-1
            if index not in self.fail:self.output(self.member(index))
            self.process_state=None

    def statuses(self,state):return [m['status'] for m in state['members']]

    def test_a_middle_member_without_output_fails_alone_and_the_batch_completes(self):
        self.matrix(3,fail={1})
        state=self.runner.start('batch',60)
        self.assertEqual(self.statuses(state),['completed','missing_output','completed'])
        self.assertEqual((state['status'],state['failed_members']),('completed',1))
        self.assertEqual(len(self.starts),3);self.assertEqual(len(self.closes),1)     # monitor closed once; no member retried
        self.assertTrue(all(m['attempts']==1 for m in state['members']))
        error=state['members'][1]['error']
        self.assertIn('without writing this member\'s SeedFarming XML',error);self.assertIn('Nothing is inferred',error)
        self.assertIn('of its 30 s budget',error)
        report=self.runner.report('batch')
        self.assertEqual([r['actual_frames'] for r in report['members']],[2,None,2])  # missing output stays null, never zero
        self.assertEqual(report['members'][1]['error'],error)
        guard_active_seed(self.controller.root)                                      # slot released

    def test_every_member_failing_stops_with_every_reason(self):
        self.matrix(2,fail={0,1})
        state=self.runner.start('batch',60)
        self.assertEqual((state['status'],self.statuses(state)),('stopped',['missing_output','missing_output']))
        reason=state['stopped_reason']
        self.assertEqual((reason['rules'],reason['failed'],reason['pending']),(['every_member_failed'],2,0))
        self.assertEqual([r['alias'] for r in reason['reasons']],[m['alias'] for m in state['members']])
        self.assertFalse(SeedRunner.resumable(read_json(self.runner.path('batch')/'state.json')))   # nothing pending

    def test_three_failures_in_a_row_trip_the_breaker(self):
        self.matrix(5,fail={0,1,2})
        state=self.runner.start('batch',60)
        self.assertEqual(self.statuses(state),['missing_output']*3+['pending']*2)
        self.assertEqual(state['status'],'stopped');self.assertEqual(len(self.starts),3)
        reason=state['stopped_reason']
        self.assertEqual((reason['rules'],reason['in_a_row'],reason['attempted'],reason['failed'],reason['pending']),(['in_a_row'],3,3,3,2))
        self.assertEqual(len(reason['reasons']),3);self.assertTrue(all(r['error'] for r in reason['reasons']))
        self.assertIn('3 members in a row failed',reason['plain']);self.assertIn('seed-resume continues the 2 pending members',reason['plain'])
        guard_active_seed(self.controller.root)

    def test_half_of_four_or_more_failing_trips_the_breaker(self):
        self.matrix(6,fail={1,3})                                                   # completed, failed, completed, failed
        state=self.runner.start('batch',60)
        self.assertEqual(self.statuses(state),['completed','missing_output','completed','missing_output','pending','pending'])
        reason=state['stopped_reason']
        self.assertEqual((state['status'],reason['rules'],reason['attempted'],reason['failed'],reason['in_a_row']),('stopped',['half_failed'],4,2,1))
        self.assertIn('2 of 4 attempted members failed',reason['plain'])

    def test_fewer_than_four_attempted_or_under_half_failed_continue(self):
        self.matrix(5,fail={1,4})                                                   # 1 of 4, then the last one: no rule trips
        state=self.runner.start('batch',60)
        self.assertEqual((state['status'],state['failed_members']),('completed',2));self.assertNotIn('stopped_reason',state)

    def test_a_status_read_never_reactivates_and_resume_continues_only_pending_members(self):
        self.matrix(5,fail={0,1,2})
        self.runner.start('batch',60)
        self.process_state=dict(self.MONITOR)                                      # MT5 reopened on the monitor
        state=self.runner.status('batch')
        self.assertEqual((state['status'],len(self.closes),len(self.starts)),('stopped',1,3))
        resumed=self.runner.resume('batch',60)
        self.assertEqual(resumed['status'],'completed')
        self.assertEqual(self.statuses(resumed),['missing_output']*3+['completed']*2)
        self.assertEqual((len(self.starts),len(self.closes)),(5,2))                # the monitor closed again; failed members never re-run
        self.assertTrue(all(m['attempts']==1 for m in resumed['members']))
        retained=read_json(self.runner.path('batch')/'state.json')
        self.assertEqual(len(retained['reactivations']),1)
        record=retained['reactivations'][0]
        self.assertEqual((record['prior_stopped_reason']['rules'],record['pending'],record['process']),(['in_a_row'],2,self.MONITOR))
        self.assertNotIn('stopped_reason',retained);self.assertEqual(retained['failed_members'],3)
        self.assertEqual(self.runner.resume('batch',5)['status'],'completed');self.assertEqual(len(self.starts),5)

    def test_a_caller_without_start_grade_checks_never_reactivates(self):
        # Codex P2 on GOAT-EA#160: the demo lane's ordinary resume passes reactivate=False.
        self.matrix(5,fail={0,1,2})
        self.runner.start('batch',60)
        self.process_state=dict(self.MONITOR)
        state=self.runner.resume('batch',5,reactivate=False)
        self.assertEqual((state['status'],len(self.closes),len(self.starts)),('stopped',1,3))
        self.assertNotIn('reactivations',read_json(self.runner.path('batch')/'state.json'))

    def test_the_breaker_counts_only_members_since_the_last_activation(self):
        self.matrix(5,fail={0,1,2,3})
        self.runner.start('batch',60)
        self.process_state=dict(self.MONITOR)
        resumed=self.runner.resume('batch',60)                                     # member 4 fails, member 5 completes
        self.assertEqual(self.statuses(resumed),['missing_output']*4+['completed'])
        self.assertEqual((resumed['status'],resumed['failed_members']),('completed',4))

    def test_resume_of_a_stopped_batch_needs_the_running_terminal_and_the_grant(self):
        self.matrix(4,fail={0,1,2})
        self.runner.start('batch',60)
        before=(self.runner.path('batch')/'state.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'Resuming a stopped seed batch requires chosen running demo terminal'):
            self.runner.resume('batch',5)
        self.process_state=dict(self.MONITOR);self.owner['owner']='human'
        with self.assertRaisesRegex(ValueError,'grant'):self.runner.resume('batch',5)
        self.assertEqual((self.runner.path('batch')/'state.json').read_bytes(),before)   # refused before any effect
        self.assertEqual((len(self.starts),len(self.closes)),(3,1))

    def test_another_holder_of_the_terminal_slot_refuses_the_reactivation(self):
        self.matrix(4,fail={0,1,2})
        self.runner.start('batch',60)
        self.process_state=dict(self.MONITOR)
        self.runner.slot.write_text(json.dumps(dict(status='active',batch_id='other',manifest_sha256='x')))
        with self.assertRaisesRegex(ValueError,'Seed runner owns this terminal'):self.runner.resume('batch',5)
        self.assertEqual(len(self.closes),1)

    def test_cancel_still_stops_the_batch_for_good(self):
        self.matrix(3)
        self.auto=False;self.runner.start('batch',1)                               # member 1 running
        self.runner.cancel('batch');state=self.runner.status('batch')
        self.assertEqual((state['status'],self.statuses(state)),('stopped',['cancelled','cancelled','cancelled']))
        self.process_state=dict(self.MONITOR)
        self.assertEqual(self.runner.resume('batch',5)['status'],'stopped')
        self.assertEqual(len(self.starts),1)
        self.assertFalse(SeedRunner.resumable(read_json(self.runner.path('batch')/'state.json')))

    def test_a_batch_stopped_by_the_old_rule_resumes_its_pending_members(self):
        # seedhunt-t2-4-b41's shape: stopped by one missing_output member under the old rule, members after it pending.
        self.matrix(4,fail={1})
        self.auto=False;self.runner.start('batch',1)
        path=self.runner.path('batch')/'state.json';state=read_json(path)
        state['members'][0].update(status='missing_output',finished_unix=self.now);state['status']='stopped'
        state['members'][0].pop('process',None);self.process_state=None
        write_json(path,state)
        self.runner.slot.write_text(json.dumps(dict(read_json(self.runner.slot),status='released')))
        self.assertTrue(SeedRunner.resumable(read_json(path)))
        self.assertEqual(self.runner.status('batch')['status'],'stopped')         # a read keeps the recorded status
        self.process_state=dict(self.MONITOR);self.auto=True;self.fail=set()
        resumed=self.runner.resume('batch',60)
        self.assertEqual((resumed['status'],self.statuses(resumed)),('completed',['missing_output','completed','completed','completed']))
        self.assertEqual(len(self.starts),4)

    def test_only_a_clean_stop_with_untouched_pending_members_is_resumable(self):
        def state(*statuses,**extra):
            return dict(dict(status='stopped',generation=1,error=None,members=[dict(status=s,attempts=0 if s=='pending' else 1) for s in statuses]),**extra)
        self.assertTrue(SeedRunner.resumable(state('completed','missing_output','pending')))
        for label,value in (('a cancelled member',state('cancelled','missing_output','pending')),
                            ('an uncertain member',state('reconcile_required','missing_output','pending')),
                            ('a live member',state('running','missing_output','pending')),
                            ('nothing pending',state('completed','missing_output')),
                            ('never started',state('missing_output','pending',generation=None)),
                            ('a batch-level doubt',state('missing_output','pending',error='Unowned selected-terminal process appeared')),
                            ('not stopped',state('missing_output','pending',status='active')),
                            ('an attempted pending member',dict(state('missing_output','pending'),members=[dict(status='missing_output',attempts=1),dict(status='pending',attempts=1)]))):
            with self.subTest(label):self.assertFalse(SeedRunner.resumable(value))

    def test_timeout_fails_only_that_member(self):
        self.matrix(2);self.auto=False
        self.runner.start('batch',1);self.now+=31
        self.runner.resume('batch',2)                                               # timeout requested and the member closed
        state=self.runner.status('batch')
        self.assertEqual(self.statuses(state)[0],'timeout');self.assertIn('ran past its 30 s budget',state['members'][0]['error'])
        self.assertEqual(state['status'],'active')
        self.auto=True;state=self.runner.resume('batch',60)
        self.assertEqual((state['status'],self.statuses(state)),('completed',['timeout','completed']))


if __name__=='__main__':unittest.main()
