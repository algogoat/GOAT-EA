"""Read-only planning evidence from synthetic completed native batches; no MT5 launch."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import shutil
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

import goat_studio
import studio_benchmark as benchmark
import studio_resources as resources
from campaign_ledger import packed
from studio_launch_intent import record_intent
from studio_native_observe import observe
from studio_report_observe import observe_reports
from studio_report_paths import report_paths
import test_studio_batch as fixtures


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeBatchTests();self.fixture.setUp()
        self.c=self.fixture.controller;self.root=self.fixture.root
        prepared=self.fixture.prepare();self.package=Path(prepared['package']);self.manifest=prepared['manifest']
        self.plan=json.loads((self.package/'studio-plan.json').read_text())
        job=self.c.job('customer-batch')
        self.c.submit('queue.reserve',dict(job_id='customer-batch',configuration_sha256=job['configuration_sha256'],package_sha256=hashlib.sha256((self.package/'manifest.json').read_bytes()).hexdigest()),'benchmark-reserve')
        state=self.c.state()
        self.intent=record_intent(self.c.store,self.c.terminal,self.c.run,'customer-batch',self.package,actor='agent',revision=state['revision'],generation=state['generation'])
        self.native=self.fixture.fixture.common/self.manifest['native_run_relative'].replace('\\','/')
        shutil.copytree(self.package,self.native)
        queue=(self.package/'queue.GOAT').read_bytes().decode('utf-16')
        self.titles=[entry.strip().splitlines()[0].strip(';') for entry in queue.split('\x1f') if entry.strip()]
        (self.native/'queue.GOAT').write_bytes(queue.replace(';Pending_',';Completed_').encode('utf-16'))
        self.config=job['configuration'];self.report_paths=[]
        for index,member in enumerate(self.config['batch_members']):
            paths=report_paths(self.plan,self.manifest,index)
            tester=member['tester'];title=f"{PureWindowsPath(tester['Expert']).stem} {tester['Symbol']},{tester['Period']} {tester['FromDate']}-{tester['ToDate']}"
            for forward,key in [(False,'common_back'),(True,'common_forward')]:
                def row(values):return '<Row>'+''.join('<Cell><Data ss:Type="String">'+escape(str(value))+'</Data></Cell>' for value in values)+'</Row>'
                raw=('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><DocumentProperties xmlns="urn:schemas-microsoft-com:office:office"><Title>'+escape(title)+'</Title></DocumentProperties><Worksheet><Table>'+row(['Pass','Forward Result' if forward else 'Result','Profit','Trades','Lots'])+row([1,1,2,10,0.1])+'</Table></Worksheet></Workbook>').encode()
                paths[key].parent.mkdir(parents=True,exist_ok=True);paths[key].write_bytes(raw);self.report_paths.append(paths[key])
        native=observe(self.package);reports=observe_reports(self.package,self.config,self.c.schema)
        self.assertEqual(reports['status'],'report_batch_verified')
        from studio_finish import finish
        self.result_path=self.c.root/'attempts'/self.intent['attempt_id']/'result.json'
        self.result_path.parent.mkdir(parents=True,exist_ok=True)
        (self.result_path.parent/'transaction.json').write_text(json.dumps(dict(phase='restored')))
        # Native process/idle qualification is outside this fixture. All package,
        # queue, report and durable completion work follows production finish.
        with patch.object(self.c,'runtime',return_value=None):
            finished=finish(self.c,'customer-batch')
        self.assertEqual(finished['status'],'completed')
        self.timeline=self.native/'timeline.tsv';self.timeline.write_bytes(self.timeline_bytes())

    def tearDown(self):self.fixture.tearDown()

    def timeline_bytes(self):
        lines=['LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails']
        for index,start,end in [(0,'12:00:00','12:02:00'),(1,'12:02:10','12:05:10')]:
            for clock,status in [(start,'OnGoing'),(end,'Completed')]:
                lines.append('\t'.join(['2026.09.25 '+clock,'2026.01.01 00:00:00','QUEUE_STATE',self.titles[index].replace('Pending_',status+'_',1),status,'fixture']))
        return ('\r\n'.join(lines)+'\r\n').encode('utf-16')

    def report(self):return benchmark.benchmark_report(self.c,'customer-batch')

    def test_exact_member_observations_and_gap_are_not_forecasts(self):
        report=self.report()
        self.assertEqual([m['elapsed_seconds'] for m in report['members']],[120,180])
        self.assertEqual(report['timing']['observed_batch_span_seconds'],310)
        self.assertEqual(report['timing']['between_member_seconds'],10)
        self.assertTrue(all(m['actual_back_report_rows']==1 for m in report['members']))
        self.assertNotEqual(report['members'][0]['workload_sha256'],report['members'][1]['workload_sha256'])
        self.assertEqual(report['artifact_bytes']['report_xml'],sum(p.stat().st_size for p in self.report_paths))
        self.assertIsNone(report['historical_environment']['enabled_mt5_workers'])
        self.assertIsNone(report['estimate']);self.assertFalse(report['execution_ready'])

    def test_read_does_not_open_pump_launch_grant_or_write(self):
        inbox=self.c.local/'inbox'/'unconsumed.json';inbox.parent.mkdir(exist_ok=True);inbox.write_text('{"human_control":"pending"}')
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(goat_studio.Controller,'open',side_effect=AssertionError('open')),patch.object(self.c.bridge,'pump',side_effect=AssertionError('pump')),patch.object(self.c.store,'submit',side_effect=AssertionError('submit')),patch('subprocess.Popen',side_effect=AssertionError('launch')):
            self.report()
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_missing_timeline_is_unknown_not_zero(self):
        self.timeline.unlink();report=self.report()
        self.assertEqual(report['timing']['status'],'timing_unknown')
        self.assertTrue(all(m['elapsed_seconds'] is None for m in report['members']))

    def test_ambiguous_timeline_is_unknown(self):
        text=self.timeline_bytes().decode('utf-16');lines=text.splitlines()
        variations=[text.replace('12:02:00','11:59:59'),text.replace('12:02:00','12:00:00'),text.replace('QUEUE_STATE','QUEUE_BROKEN',1),'\n'.join(lines[:2]+[lines[1]]+lines[2:]),text.replace('OnGoing_','OnGoing_WRONG_',1),text.replace('2026.09.25','bad-date',1),'\n'.join(lines[:-1]),text+'2026.09.25 12:06:00\tserver\tBATCH_TERMINATED\titem\tstatus\tdetails\n']
        for changed in variations:
            with self.subTest(changed=changed):
                self.timeline.write_bytes(changed.encode('utf-16'))
                self.assertEqual(self.report()['timing']['status'],'timing_unknown')

    def test_duplicate_queued_event_refuses_elapsed(self):
        lines=self.timeline_bytes().decode('utf-16').splitlines()
        queued=lines[1].replace('OnGoing','Queued')
        self.timeline.write_bytes(('\n'.join([lines[0],queued,queued]+lines[1:])).encode('utf-16'))
        self.assertEqual(self.report()['timing']['status'],'timing_unknown')

    def test_unfinished_job_refuses_without_finish(self):
        state=self.c.state();state['queue'][0]['status']='running';self.c.store.db.execute('UPDATE studio_queues SET jobs=?',(packed(state['queue']),))
        with self.assertRaisesRegex(ValueError,'completed retained'):self.report()

    def test_frozen_and_completion_drift_refuse(self):
        for target in [self.package/'studio-plan.json',self.result_path,self.report_paths[0],self.native/'queue.GOAT',self.native/'inputs'/self.manifest['jobs'][0]['run_alias']/'Inputs.GOAT']:
            with self.subTest(path=target):
                raw=target.read_bytes();target.write_bytes(raw.replace(b'completed',b'failed') if target==self.result_path else raw+b' ')
                with self.assertRaises((ValueError,UnicodeError)):self.report()
                target.write_bytes(raw)

    def test_timeline_changed_during_observation_refuses(self):
        original=benchmark.timeline_timings
        def change(*args):
            value=original(*args);self.timeline.write_bytes(self.timeline_bytes()+b' ');return value
        with patch.object(benchmark,'timeline_timings',side_effect=change):
            with self.assertRaisesRegex(ValueError,'changed'):self.report()

    def test_oversized_exact_artifact_refuses_before_observer(self):
        with patch.object(benchmark,'MAX_FILE_BYTES',1),patch.object(benchmark,'observe',side_effect=AssertionError('unbounded read')):
            with self.assertRaisesRegex(ValueError,'oversized|64 MiB'):self.report()

    def test_cli_read_branch_never_opens_controller(self):
        output=io.StringIO()
        with patch.object(goat_studio,'Controller',return_value=self.c),patch.object(self.c,'open',side_effect=AssertionError('open')),redirect_stdout(output):
            goat_studio.main(['--installation',str(self.fixture.fixture.path),'benchmark-report','--batch-id','customer-batch'])
        self.assertEqual(json.loads(output.getvalue())['result']['status'],'completed_evidence_verified')
        # main closes an already-open fixture store, unlike a fresh read-only controller.
        self.c.store=None


class ResourceTests(unittest.TestCase):
    def setUp(self):
        from test_goat_studio import PortableControllerTests
        self.fixture=PortableControllerTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()

    @unittest.skipUnless(resources.os.name=='nt','Windows CIM resource contract')
    def test_current_hardware_has_no_invented_workers_or_speed(self):
        native=dict(processors=[dict(Name='Fixture CPU',NumberOfCores=8,NumberOfLogicalProcessors=16)],os='Fixture OS',architecture='64-bit',total_memory_kib=1024,free_memory_kib=512)
        before=list(self.fixture.root.rglob('*'))
        with patch.object(resources,'windows_resources',return_value=native):result=resources.resource_profile(self.fixture.receipt)
        self.assertEqual(result['physical_cores'],8);self.assertEqual(result['memory_available_bytes'],512*1024)
        self.assertIsNone(result['enabled_mt5_workers']);self.assertFalse(result['execution_ready'])
        self.assertEqual(len(result['disks']),3);self.assertEqual(before,list(self.fixture.root.rglob('*')))
        self.assertFalse(Path(self.fixture.receipt['controller_state_root']).exists())

    def test_unavailable_or_invalid_native_inventory_stays_unknown(self):
        for value in [{},dict(processors=[],free_memory_kib=False)]:
            with patch.object(resources,'windows_resources',return_value=value):result=resources.resource_profile(self.fixture.receipt)
            self.assertIsNone(result['physical_cores']);self.assertIsNone(result['memory_total_bytes']);self.assertTrue(result['unavailable'])

    def test_resource_cli_works_without_bootstrap(self):
        output=io.StringIO()
        with patch.object(resources,'windows_resources',side_effect=OSError('fixture')),patch.object(goat_studio.Controller,'open',side_effect=AssertionError('open')),redirect_stdout(output):
            goat_studio.main(['--installation',str(self.fixture.path),'resource-profile'])
        self.assertEqual(json.loads(output.getvalue())['result']['scope'],'current_host_snapshot')
        self.assertFalse(Path(self.fixture.receipt['controller_state_root']).exists())


if __name__=='__main__':unittest.main()
