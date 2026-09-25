"""GOAT Studio controller. Discovery is read-only; all mutations are explicit.

Use the installed receipt from GOAT Setup. Never copy another user's receipt,
account, state database or native attempt. See README.md for complete workflows.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import subprocess
import time
import uuid

from campaign_ledger import packed,sha
from studio_installation import VERSION,load_installation,read_json,contracts
from studio_bridge import StudioBridge,write_json,pump_for,display_state
from studio_command_store import StudioStore
from studio_native_gate import configure_gate,exclusive_gate
from studio_strategy_settings import read_values
from studio_settings import FIELDS,PERIODS,validate_tester,validate_export

OPERATION_CONTRACTS = {
    'seed-prepare':dict(required=['batch-id','plan'],effect='freeze a dedicated SeedFarming matrix; no launch'),
    'seed-start':dict(required=['batch-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='explicit bounded driver for dedicated SeedFarming; preserves active work on call timeout'),
    'seed-resume':dict(required=['batch-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='continue verified retained seed work; uncertain effects require reconciliation'),
    'seed-status':dict(required=['batch-id'],effect='observe dedicated seed campaign state and native process evidence'),
    'seed-cancel':dict(required=['batch-id'],effect='request normal close of exact owned seed process; receipt is not exit proof'),
    'seed-report':dict(required=['batch-id'],effect='report actual seed XML metrics and frozen provenance; missing evidence remains unavailable'),
    'prepare-batch':dict(required=['batch-id','plan'],effect='validate and freeze a full native Studio batch; no launch'),
    'batch-status':dict(required=['batch-id'],effect='reconcile whole native batch and report member progress'),
    'save-batch':dict(required=['batch-id','output'],effect='save native .goatbatch without overwriting'),
    'load-batch':dict(required=['batch-id','file'],effect='validate saved .goatbatch as a new unstarted batch on this installation'),
    'resume-batch':dict(required=['source-batch-id','batch-id'],effect='prepare remaining members under a new identity after original stop/finish; failed members require include-failed'),
    'validate-set':dict(required=['set'],defaults={'require-optimization':False},effect='read-only exact schema, encoding, range and partial dependency validation; no launch'),
    'build-set':dict(required=['source','output','spec'],effect='clone real SET with narrow typed changes, unique EA_Desc, support notes and provenance; never overwrite'),
    'discover':dict(required=[],effect='read installation and schema; runtime readiness not evaluated'),
    'bootstrap':dict(required=['account-login','account-server'],effect='create human-owned local binding and monitor preset; no launch'),
    'onboarding-status':dict(required=[],effect='read-only staged local monitor evidence and precise recovery; never grants control'),
    'monitor-prepare':dict(required=['symbol'],effect='create a separate persistent monitor profile only while terminals are stopped; no permissions or launch'),
    'monitor-launch':dict(required=['attempt-id'],effect='one retained stopped-terminal launch of prepared inert profile; saved login and Algo-off required'),
    'serve':dict(required=[],defaults={'watch-seconds':3600},limits={'watch-seconds':[0,3600]},effect='process durable draft/ownership inboxes; no native launch'),
    'state':dict(required=[],effect='process UI inbox then return full controller state'),
    'submit':dict(required=['request'],effect='apply exact agent envelope with revision and generation checks'),
    'prepare':dict(required=['job-id','set','configuration'],effect='freeze explicit settings and stage pending native package'),
    'start':dict(required=['job-id'],effect='explicit one-time native dispatch for first pending job; reconcile receipt'),
    'status':dict(required=['job-id'],effect='observe retained attempt; update reconciled state without retry'),
    'reconcile':dict(required=['job-id'],effect='alias of status'),
    'cancel':dict(required=['job-id'],effect='cancel pending job or publish exact owned native stop; receipt is not stop proof'),
    'finish':dict(required=['job-id'],effect='verify finished queue and idle runtime, retain result, restore owned controls')
}


class Controller:
    def __init__(self, receipt):
        self.install = load_installation(receipt)
        self.root = Path(self.install['controller_state_root'])
        self.local = Path(self.install['terminal_data_root'])/'MQL5/Files/GOATStudio'
        self.schema,self.policy = contracts()
        self.store = None

    def open(self):
        self.session = read_json(self.root/'session.json')
        if self.session['installation_sha256'] != sha(self.install):
            raise ValueError('Installation changed since bootstrap; reconcile before repair')
        if not (self.root/'studio.sqlite').is_file(): raise ValueError('Controller database missing; preserve remaining receipts')
        self.store = StudioStore(self.root/'studio.sqlite',input_schema=self.schema,dependency_policy=self.policy)
        self.terminal,self.run = self.session['terminal_id'],self.session['run_id']
        self.bridge = StudioBridge(self.local/self.session['directory_id'],self.store,self.terminal,self.run)
        return self

    def state(self): return self.store.snapshot(self.terminal,self.run)

    def submit(self,command,payload,request_id):
        state = self.state()
        request = dict(schema_version=1,request_id=request_id,terminal_id=self.terminal,run_id=self.run,
                       expected_revision=state['revision'],generation=state['generation'],command=command,payload=payload)
        # Persist the exact envelope before submission, making transport retries idempotent.
        path = self.root/'requests'/(request_id+'.json')
        if path.exists():
            prior = read_json(path)
            if prior['command'] != command or prior['payload'] != payload: raise ValueError('Request ID content changed')
            request = prior
        else: write_json(path,request)
        result = self.store.submit(request,actor='agent')
        self.bridge.pump()
        return result

    def job(self,job_id):
        job = next((j for j in self.state()['queue'] if j['job_id']==job_id),None)
        if job is None: raise ValueError('Unknown job; use state to discover retained jobs')
        return job

    def binding(self):
        i=self.install;s=self.session
        return dict(research_terminal=i['terminal_executable'],research_data_root=i['terminal_data_root'],
                    common_files_root=i['common_files_root'],ea_relative_path=i['ea_relative_path'],
                    ea_sha256=i['ea_sha256'],ea_version=i['ea_version'],account_server=s['account']['server'],
                    protected_data_roots=[],account_confirmation_pending=False,live_trading_allowed=False)

    def native_args(self):
        i=self.install
        return dict(account=self.session['account'],observation_path=self.local/'ui-observation.json',
                    monitor_path=Path(i['terminal_data_root'])/'MQL5/Experts'/i['ea_relative_path'].replace('\\','/'),
                    monitor_sha256=i['ea_sha256'],input_schema=self.schema)

    def bootstrap(self,login,server):
        if not login or not re.fullmatch('[0-9]+',login) or not server or not re.fullmatch('[A-Za-z0-9_. -]+',server):
            raise ValueError('Explicit demo account login and server required')
        if (self.root/'session.json').exists():
            self.open()
            if self.session['account'] != {'login':login,'server':server}: raise ValueError('Existing account binding differs')
            return self.session
        if (self.local/'active.json').exists(): raise ValueError('Existing Studio activation requires reconciliation; no overwrite')
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'requests').mkdir(exist_ok=True)
        terminal='terminal-'+sha(self.install['terminal_data_root'])[:16]
        run='session-'+uuid.uuid4().hex
        self.local.mkdir(parents=True,exist_ok=True)
        self.store=StudioStore(self.root/'studio.sqlite',input_schema=self.schema,dependency_policy=self.policy)
        self.store.bind(terminal,run)
        configure_gate(self.store,self.local/'native-gate')
        bridge=StudioBridge(self.local/run,self.store,terminal,run);bridge.pump()
        session=dict(schema_version=1,installation_sha256=sha(self.install),terminal_id=terminal,run_id=run,
                     directory_id=run,account=dict(login=login,server=server),demo_only=True)
        preset=Path(self.install['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
        raw='Mode_Operation=11\r\nStudio_ReadOnlyMonitor=true\r\nStudio_MonitorRunPath=\r\nEA_Desc=Studio Monitor\r\n'.encode('utf-16')
        preset.parent.mkdir(parents=True,exist_ok=True)
        if preset.exists() and preset.read_bytes()!=raw: raise ValueError('Existing monitor preset differs; preserve it before setup')
        preset.write_bytes(raw)
        write_json(self.root/'session.json',session)
        write_json(self.local/'active.json',dict(directory_id=run,terminal_id=terminal,run_id=run,
                                               terminal_data_path=self.install['terminal_data_root']))
        return session|dict(monitor_preset=str(preset),next_action='Run onboarding-status. With selected terminal stopped, monitor-prepare --symbol <exact broker symbol> then monitor-launch --attempt-id <new-id> stages and opens a persistent monitor. User approves DLL/WebRequest, keeps Algo Trading off; run serve, then human Give to Agent.')

    def prepare(self,job_id,set_path,configuration):
        from strategy_registry import connect,inspect_set
        from studio_native_stage import stage_job
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',job_id): raise ValueError('Job ID must be 1..80 letters, digits, underscore or hyphen')
        config=read_json(configuration)
        if set(config)!={'tester','export'}: raise ValueError('Configuration requires tester and export sections')
        tester=validate_tester(config['tester']);exports=validate_export(config['export'],tester)
        if tester['Expert']!=self.install['ea_relative_path']: raise ValueError('Tester Expert must match installation')
        if tester['ForwardMode']!=4: raise ValueError('Beta native pipeline requires custom forward mode 4')
        raw=Path(set_path).read_bytes();info=inspect_set(raw);values=read_values(raw)
        package=self.root/'packages'/job_id
        existing=next((j for j in self.state()['queue'] if j['job_id']==job_id),None)
        if existing and (package/'manifest.json').exists():
            plan=read_json(package/'studio-plan.json')
            if existing['configuration']['tester']!=tester or existing['configuration']['export']!=exports or existing['configuration']['strategy']['values']!=values:
                raise ValueError('Job ID already belongs to different inputs')
            return dict(job_id=job_id,package=str(package),manifest=read_json(package/'manifest.json'),reused=True)
        self.submit('draft.replace_configuration',dict(tester=tester,export=exports),job_id+'-settings')
        self.submit('draft.replace_strategy',dict(schema_hash=sha(self.schema),values=values),job_id+'-strategy')
        self.submit('queue.enqueue',dict(job_id=job_id),job_id+'-queue')
        registry=self.root/'templates.sqlite';db=connect(registry)
        template=sha(str(Path(set_path).resolve()));revision=sha([template,info['sha256']]);now=datetime.now(timezone.utc).isoformat()
        try:
            db.execute('INSERT OR IGNORE INTO templates VALUES(?,?,?)',(template,str(Path(set_path).resolve()),now))
            db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?,?,?,?,?,?)',(revision,template,info['sha256'],info['canonical_sha256'],info['ea_desc'],raw,info['canonical_json'],'{}',now));db.commit()
        finally: db.close()
        package.parent.mkdir(exist_ok=True)
        result=stage_job(self.store,self.terminal,self.run,job_id,registry,revision,self.binding(),package)
        write_json(self.root/'packages'/(job_id+'.source.json'),dict(set_path=str(Path(set_path).resolve()),set_sha256=info['sha256']))
        return dict(job_id=job_id,package=str(package),manifest=result['receipt'],native_started=False)

    def start(self,job_id):
        from studio_seed_slot import guard_active_seed
        guard_active_seed(self.root)
        from studio_process_check import inspect_processes,revalidate_processes
        from studio_launch_intent import record_intent
        from studio_open_activation import activate_open
        from studio_dispatch_transport import publish
        from studio_native_request import validate_activated_job
        state=self.state();job=self.job(job_id);binding=self.binding();args=self.native_args()
        if state['owner']!='agent': raise ValueError('Human must Give to Agent in Studio first')
        if job['status']!='pending': raise ValueError('Only pending job can start; reconcile existing attempt')
        # Check runtime BEFORE recording an irreversible attempt.
        self.runtime(require_idle=True,expected_batch_ongoing=False)
        baseline=inspect_processes(binding)
        package=self.root/'packages'/job_id
        digest=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
        self.submit('queue.reserve',dict(job_id=job_id,configuration_sha256=job['configuration_sha256'],package_sha256=digest),job_id+'-reserve')
        state=self.state()
        intent=record_intent(self.store,self.terminal,self.run,job_id,package,actor='agent',revision=state['revision'],generation=state['generation'])
        evidence=self.root/'attempts'/intent['attempt_id'];evidence.parent.mkdir(exist_ok=True)
        def ownership(bound,inventory):
            revalidate_processes(bound,baseline)
            self.runtime(require_idle=True,expected_batch_ongoing=False)
        with exclusive_gate(self.local/'native-gate'):
            activate_open(self.state(),self.job(job_id),**args,evidence=evidence,process_baseline=baseline,validate_ownership=ownership)
        state=self.state()
        def validate(state,job):
            revalidate_processes(binding,baseline)
            return validate_activated_job(state,job,**args,evidence=evidence)
        return publish(self.store,self.terminal,self.run,job_id,self.bridge.root,actor='agent',revision=state['revision'],generation=state['generation'],validate_native=validate)

    def runtime(self,require_idle=False,expected_batch_ongoing=False):
        from studio_resilient_read import read_observation
        from studio_runtime_check import check_runtime
        observation,modified=read_observation(self.local/'ui-observation.json')
        i=self.install
        args=dict(now=time.time(),modified=modified,data_path=i['terminal_data_root'],installation_path=str(Path(i['terminal_executable']).parent),program_path=str(self.native_args()['monitor_path'].resolve()),account_login=self.session['account']['login'],account_server=self.session['account']['server'],require_idle=require_idle,expected_batch_ongoing=expected_batch_ongoing)
        check_runtime(observation,**args)
        return observation,args

    def reconcile(self,job_id):
        from studio_reconcile import reconcile
        job=self.job(job_id)
        if 'launch_intent' not in job: return dict(status=job['status'],native_attempt=False)
        from studio_dispatch_observe import observe_dispatch
        dispatch=observe_dispatch(self.local/'native-gate',job['launch_intent']['attempt_id'])
        cancel_id=sha([job['launch_intent']['attempt_id'],'cancel'])
        cancellation=observe_dispatch(self.local/'native-gate',cancel_id)
        if cancellation['status']=='awaiting_receipt':
            return dict(status='cancel_pending',dispatch=cancellation,job=job)
        if cancellation['status']=='not_issued' and dispatch['status']=='awaiting_receipt':
            return dict(status='dispatch_pending',dispatch=dispatch,job=job)
        kwargs={}
        try:
            raw=read_json(self.local/'ui-observation.json')
            observation,args=self.runtime(expected_batch_ongoing=raw['runtime']['batch_ongoing'])
            kwargs=dict(runtime_observation=observation,runtime_check_args=args)
        except (ValueError,OSError,KeyError): pass
        result=reconcile(self.store,self.terminal,self.run,job_id,job['launch_intent']['attempt_id'],revision=self.state()['revision'],**kwargs)
        self.bridge.pump()
        return result|dict(job=self.job(job_id))

    def cancel(self,job_id):
        from studio_cancel import publish_cancel
        job=self.job(job_id)
        if job['status']=='pending': return self.submit('queue.cancel',dict(job_id=job_id),job_id+'-cancel')
        return publish_cancel(self,job)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation',type=Path,required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('seed-prepare');p.add_argument('--batch-id',required=True);p.add_argument('--plan',type=Path,required=True)
    for command in ('seed-start','seed-resume'):
        p=sub.add_parser(command);p.add_argument('--batch-id',required=True);p.add_argument('--max-seconds',type=int,default=60)
    for command in ('seed-status','seed-cancel','seed-report'):
        p=sub.add_parser(command);p.add_argument('--batch-id',required=True)
    p=sub.add_parser('prepare-batch');p.add_argument('--batch-id',required=True);p.add_argument('--plan',type=Path,required=True)
    p=sub.add_parser('batch-status');p.add_argument('--batch-id',required=True)
    p=sub.add_parser('save-batch');p.add_argument('--batch-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('load-batch');p.add_argument('--batch-id',required=True);p.add_argument('--file',type=Path,required=True)
    p=sub.add_parser('resume-batch');p.add_argument('--batch-id',required=True);p.add_argument('--source-batch-id',required=True);p.add_argument('--include-failed',action='store_true')
    sub.add_parser('discover');sub.add_parser('state');sub.add_parser('onboarding-status')
    p=sub.add_parser('monitor-prepare');p.add_argument('--symbol',required=True)
    p=sub.add_parser('monitor-launch');p.add_argument('--attempt-id',required=True)
    p=sub.add_parser('validate-set');p.add_argument('--set',type=Path,required=True);p.add_argument('--require-optimization',action='store_true')
    p=sub.add_parser('build-set');p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--spec',type=Path,required=True)
    p=sub.add_parser('bootstrap');p.add_argument('--account-login',required=True);p.add_argument('--account-server',required=True)
    p=sub.add_parser('serve');p.add_argument('--watch-seconds',type=float,default=3600)
    p=sub.add_parser('submit');p.add_argument('--request',type=Path,required=True)
    p=sub.add_parser('prepare');p.add_argument('--job-id',required=True);p.add_argument('--set',type=Path,required=True);p.add_argument('--configuration',type=Path,required=True)
    for command in ('start','status','cancel','reconcile','finish'):
        p=sub.add_parser(command);p.add_argument('--job-id',required=True)
    args=parser.parse_args(argv);controller=None
    try:
        controller=Controller(args.installation)
        if args.operation=='discover':
            result=dict(controller_version=VERSION,ea_version=controller.install['ea_version'],input_schema=controller.schema,dependency_policy=controller.policy,installation=controller.install,operations=list(sub.choices),operation_contracts=OPERATION_CONTRACTS,tester_fields=sorted(FIELDS),periods=sorted(PERIODS),export_fields=['SetsToExport','MinScore','TargetDD','AdjustLots','BackOOSDate','MinARF','MinSR','IncludeBackOOS','IncludeSequenceData'],native_constraints=['Windows MT5 demo connected; DLL enabled; Algo Trading off','Only selected MT5 executable may be running for ordinary native batch activation','Ordinary optimization/export batches require custom forward and local workers','Give to Agent required; explicit batch start; EA advances members'],seed_constraints=['Dedicated SeedFarming uses ForwardMode=0 and empty ForwardDate','Explicit bounded seed-start/seed-resume driver; selected terminal closes and relaunches for frozen members','Seed and ordinary native execution share one exclusive terminal slot','Actual native seed launch qualification is pending'],documentation=['AGENT-START-HERE.md','goat-beta-agent-guide.md','goat-agent-capabilities.md','INPUT-REFERENCE.md','TEMPLATE-WORKFLOW.md','SEED-WORKFLOW.md'],readiness_scope='Runtime and ownership checked at start, not by discovery',execution_ready=False)
        elif args.operation=='bootstrap': result=controller.bootstrap(args.account_login,args.account_server)
        elif args.operation in ('onboarding-status','monitor-prepare','monitor-launch'):
            from studio_onboarding import onboarding_status,monitor_prepare,monitor_launch
            if args.operation=='onboarding-status': result=onboarding_status(controller)
            elif args.operation=='monitor-prepare': result=monitor_prepare(controller,args.symbol)
            else: result=monitor_launch(controller,args.attempt_id)
        elif args.operation=='validate-set':
            from studio_template_tools import validate_set
            result=validate_set(args.set,controller.schema,controller.policy,require_optimization=args.require_optimization)
        elif args.operation=='build-set':
            from studio_template_tools import build_set
            result=build_set(args.source,args.output,read_json(args.spec),controller.schema,controller.policy,
                controller_version=VERSION,ea_version=controller.install['ea_version'],
                forbidden_roots=[controller.install['catalog_root']] if controller.install.get('catalog_root') else [])
        else:
            controller.open()
            if args.operation.startswith('seed-'):
                from studio_seed import SeedRunner
                runner=SeedRunner(controller)
                if args.operation=='seed-prepare':
                    from studio_batch import _json
                    result=runner.prepare(args.batch_id,_json(args.plan))
                elif args.operation in ('seed-start','seed-resume'):
                    result=getattr(runner,args.operation.removeprefix('seed-'))(args.batch_id,max_seconds=args.max_seconds)
                else: result=getattr(runner,args.operation.removeprefix('seed-'))(args.batch_id)
            elif args.operation=='serve': result=pump_for(controller.bridge,args.watch_seconds)
            elif args.operation=='state': controller.bridge.pump();result=controller.state()
            elif args.operation=='submit':
                result=controller.store.submit(read_json(args.request),actor='agent');controller.bridge.pump()
            elif args.operation=='prepare': result=controller.prepare(args.job_id,args.set,args.configuration)
            elif args.operation=='prepare-batch':
                from studio_batch import prepare_batch
                result=prepare_batch(controller,args.batch_id,args.plan)
            elif args.operation=='batch-status':
                from studio_batch import batch_status
                result=batch_status(controller,args.batch_id)
            elif args.operation=='save-batch':
                from studio_batch import save_batch
                result=save_batch(controller,args.batch_id,args.output)
            elif args.operation=='load-batch':
                from studio_batch import load_batch
                result=load_batch(controller,args.batch_id,args.file)
            elif args.operation=='resume-batch':
                from studio_batch import resume_batch
                result=resume_batch(controller,args.source_batch_id,args.batch_id,include_failed=args.include_failed)
            elif args.operation=='start': result=controller.start(args.job_id)
            elif args.operation=='cancel': result=controller.cancel(args.job_id)
            elif args.operation=='finish':
                from studio_finish import finish
                result=finish(controller,args.job_id)
            else: result=controller.reconcile(args.job_id)
        print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
    except (OSError,ValueError,KeyError,sqlite3.Error,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(ok=False,error=str(exc),recovery='Preserve receipts; inspect state and matching job/attempt before retrying a mutation')));return 2
    finally:
        if controller and controller.store: controller.store.close()

if __name__=='__main__': sys.exit(main())
