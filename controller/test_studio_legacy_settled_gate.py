"""Legacy settlement proofs use real SQLite stores and canonical retained files."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from campaign_ledger import packed, sha
from studio_legacy_settled_gate import assert_legacy_settled_request


def digest(raw): return hashlib.sha256(raw).hexdigest()
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class LegacySettledGateTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve(); scope = 'banker-fixture'; attempt = 'a'*64
        gate = base/'terminal'/'bridge'/'native-gate'; gate.mkdir(parents=True)
        database = base/scope/'controller.sqlite'; database.parent.mkdir()
        db = sqlite3.connect(database); self.addCleanup(db.close)
        db.executescript('CREATE TABLE studio_native_gate(id INTEGER PRIMARY KEY,root TEXT); CREATE TABLE studio_queues(binding TEXT PRIMARY KEY,jobs TEXT);')
        db.execute('INSERT INTO studio_native_gate VALUES(1,?)',(str(gate),))
        registry_path = base/'workers.sqlite'; registry = sqlite3.connect(registry_path); self.addCleanup(registry.close)
        registry.executescript('CREATE TABLE workers(scope TEXT PRIMARY KEY,configuration TEXT); CREATE TABLE attempts(scope TEXT,attempt TEXT,claim TEXT,released INTEGER,release_evidence TEXT,PRIMARY KEY(scope,attempt));')
        worker = dict(scope=scope, controller=str(database), bridge=str(gate.parent), common_root=str(base/'common'))
        registry.execute('INSERT INTO workers VALUES(?,?)',(scope,json.dumps(worker)))
        package = base/'retained-campaign'/scope/'campaign'/'jobs'/'001'/'package'; package.mkdir(parents=True)
        config = {'tester': {'Symbol':'CADCHF'}}; configuration_hash = sha(config)
        request = dict(request_id=attempt,terminal_id=scope,run_id='retained-run',job_id='settled-job',
                       action='arm_restart',native_control_scope=scope,configuration_sha256=configuration_hash,account_server='Demo', pointer_sha256='c'*64, native_config_sha256='c'*64, guard_sha256='c'*64)
        write(gate/'request.json',request); request_raw = (gate/'request.json').read_bytes()
        write(gate/('issued-'+attempt+'.json'),dict(request=request,request_sha256=digest(request_raw)))
        (gate/('consumed-'+attempt+'.json')).write_bytes(request_raw)
        write(gate/('result-'+attempt+'.json'),dict(request_id=attempt,request_sha256=digest(request_raw),status='RESTART_ARMED_RECONCILE'))
        write(gate/'controller.json',{'database':str(database)})
        source = {k:request[k] for k in ('terminal_id','run_id','job_id','configuration_sha256')}
        plan = dict(studio_source=source,research_binding=dict(controller_database=str(database),bridge_root=str(gate.parent),
                    concurrent_worker_registry=str(registry_path),native_control_scope=scope,live_trading_allowed=False))
        write(package/'studio-plan.json',plan)
        alias = 'R'+'b'*20; (package/(alias+'.set')).write_bytes(b'fixed parameters'); (package/(alias+'.ini')).write_bytes(b'fixed tester configuration')
        manifest = dict(schema_version=1,stage='native_batch_package_unactivated',campaign_id=sha(plan),jobs=[dict(run_alias=alias,
                        staged_sha256=digest((package/(alias+'.set')).read_bytes()),ini_sha256=digest((package/(alias+'.ini')).read_bytes()))])
        write(package/'manifest.json',manifest)
        outcome = dict(outcome='execution_and_report_integrity_verified',attempt_id=attempt,scope=scope,job_id='settled-job',
                       configuration_sha256=configuration_hash,native={'status':'native_error'},negative_selection={'kind':'native_replays_not_profitable'})
        activation=package.parent/'activation'; completion=activation/'completion'
        write(completion/'outcome.json',outcome)
        transaction=dict(owner=attempt,phase='restored',base=str(base/'common'/'GOAT'/'Workers'/scope/'GOAT V1.47-Demo'),
                         files={n:dict(before=None,before_sha256=None,after_sha256='c'*64) for n in ('active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini')})
        write(activation/'transaction.json',transaction)
        host={'pid':123,'created_utc':'2026-09-23T00:00:00Z','executable':str(base/'python.exe')}
        release=dict(scope=scope,attempt_id=attempt,host=host,controls_retired=True,outcome_sha256=sha(outcome))
        write(completion/'release.json',release)
        proof=dict(receipt_path=str(completion/'release.json'),receipt_sha256=digest((completion/'release.json').read_bytes()))
        registry.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(scope,attempt,json.dumps(host),1,json.dumps(proof)));registry.commit()
        job=dict(job_id='settled-job',status='failed',configuration=config,configuration_sha256=configuration_hash,
                 launch_intent=dict(attempt_id=attempt,package=str(package),package_sha256=digest((package/'manifest.json').read_bytes())),completion=outcome)
        binding=packed(dict(terminal_id=scope,run_id='retained-run'));db.execute('INSERT INTO studio_queues VALUES(?,?)',(binding,json.dumps([job])));db.commit()
        return locals()

    def check(self,f):return assert_legacy_settled_request(f['db'],f['gate'],f['registry_path'])
    def save_job(self,f):
        f['db'].execute('UPDATE studio_queues SET jobs=?',(json.dumps([f['job']]),));f['db'].commit()
    def test_real_stores_prove_historical_only_preserving_bytes(self):
        f=self.fixture();f['registry'].execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(f['scope'],'new-passive-monitor','{}',0,None));f['registry'].commit()
        before={p:digest(p.read_bytes()) for p in f['base'].rglob('*') if p.is_file()}
        result=self.check(f)
        self.assertEqual(result['status'],'historical_attempt_settled');self.assertFalse(result['worker_clearance'])
        self.assertEqual(result['scope'],'historical_attempt_only')
        self.assertEqual(before,{p:digest(p.read_bytes()) for p in f['base'].rglob('*') if p.is_file()})
    def test_missing_evidence_never_falls_back_to_db_completion(self):
        for relative in ['outcome.json','release.json']:
            with self.subTest(relative=relative):
                f=self.fixture();(f['completion']/relative).unlink()
                with self.assertRaises(ValueError):self.check(f)
    def test_transport_missing_mismatch_and_permit_refuse(self):
        for kind in ('issued','consumed','result','permit'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='permit':write(f['gate']/'permit.json',{})
                else:(f['gate']/(kind+'-'+f['attempt']+'.json')).write_bytes(b'{}')
                with self.assertRaises(ValueError):self.check(f)
    def test_unreleased_or_foreign_registry_evidence_refuses(self):
        for sql in ["UPDATE attempts SET released=0", "UPDATE attempts SET claim='{}'", "UPDATE attempts SET release_evidence='{}'", "DELETE FROM workers"]:
            with self.subTest(sql=sql):
                f=self.fixture();f['registry'].execute(sql);f['registry'].commit()
                with self.assertRaises(ValueError):self.check(f)
    def test_altered_completion_or_restoration_or_release_refuses(self):
        for kind in ('outcome','transaction','release'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='outcome':f[kind]['job_id']='foreign';write(f['completion']/'outcome.json',f[kind])
                if kind=='transaction':f[kind]['phase']='installed';write(f['activation']/'transaction.json',f[kind])
                if kind=='release':f[kind]['controls_retired']=False;write(f['completion']/'release.json',f[kind])
                with self.assertRaises(ValueError):self.check(f)
    def test_active_job_public_schema_or_frozen_config_change_refuses(self):
        for kind in ('active','public','configuration'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='active':f['job']['status']='running'
                if kind=='public':f['job']['completion_path']=str(f['completion']/'outcome.json')
                if kind=='configuration':f['job']['configuration']['tester']['Symbol']='OTHER'
                self.save_job(f)
                with self.assertRaises(ValueError):self.check(f)
    def test_package_byte_drift_and_unsafe_path_refuse(self):
        for kind in ('set','manifest','remote','outside','traversal'):
            with self.subTest(kind=kind):
                f=self.fixture()
                if kind=='set':(f['package']/(f['alias']+'.set')).write_bytes(b'changed')
                elif kind=='manifest':(f['package']/'manifest.json').write_bytes(b'{}')
                else:
                    f['job']['launch_intent']['package']= {'remote':'//server/share/package','outside':str(f['base'].parent/'unowned/package'),'traversal':str(f['base']/'..'/'package')}[kind];self.save_job(f)
                with self.assertRaises(ValueError):self.check(f)
    def test_linked_completion_refuses(self):
        f=self.fixture();p=f['completion']/'outcome.json';target=f['base']/'elsewhere.json';p.rename(target);p.symlink_to(target)
        with self.assertRaises(ValueError):self.check(f)
    def test_another_worker_registration_cannot_authorize_path(self):
        f=self.fixture();f['worker']['controller']=str(f['base']/'other.sqlite')
        f['registry'].execute('UPDATE workers SET configuration=?',(json.dumps(f['worker']),));f['registry'].commit()
        with self.assertRaises(ValueError):self.check(f)
    def test_concurrent_file_change_during_inspection_refuses(self):
        f=self.fixture()
        import studio_legacy_settled_gate as module
        original=module._read_gate_evidence
        def changed(path):
            result=original(path)
            if path==f['completion']/'release.json':(f['gate']/'request.json').write_bytes(b'{}')
            return result
        with patch.object(module,'_read_gate_evidence',side_effect=changed):
            with self.assertRaises(ValueError):self.check(f)


if __name__ == '__main__': unittest.main()
