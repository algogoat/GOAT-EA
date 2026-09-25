"""Frozen standalone SeedFarming matrix and recoverable, bounded process driver.

No native batch queue/control files are armed. All process effects have a durable
write-ahead state; uncertain start/close is never automatically retried.
"""
import hashlib
import math
import json
from pathlib import Path
import re
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import exclusive_gate
from studio_settings import validate_tester
from studio_strategy_settings import read_values,numeric
from studio_template_tools import source_bytes,validate_raw
from studio_seed_results import collect,read_seed_json,MAX_MANIFEST_BYTES,MAX_STATE_BYTES,MAX_RESULT_BYTES
from studio_seed_slot import guard_active_seed

TERMINAL={'completed','cancelled','timeout','failed','missing_output'}
MAX_RETAINED_INPUT_BYTES=128*1024*1024
MAX_PUBLIC_MEMBERS=100

BUSY={'reserved','starting','running','reconcile_required','verifying'}


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SeedRunner:
    def __init__(self,controller,*,process=None,clock=time.time,sleep=time.sleep):
        self.c=controller;self.clock=clock;self.sleep=sleep
        if process is None:
            from studio_seed_process import WindowsSeedProcess
            process=WindowsSeedProcess(controller)
        self.process=process
        self.base=controller.root/'seeds';self.slot=controller.root/'seed-active.json'
        self.gate=controller.local/'native-gate'

    def path(self,batch_id):
        if not isinstance(batch_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',batch_id):raise ValueError('Seed batch ID must use 1..80 letters/digits/underscore/hyphen')
        return self.base/batch_id

    def _read(self,batch_id):
        root=self.path(batch_id);manifest=read_seed_json(root/'manifest.json',MAX_MANIFEST_BYTES);state=read_seed_json(root/'state.json')
        if state['manifest_sha256']!=digest(root/'manifest.json') or manifest['installation_sha256']!=sha(self.c.install) or manifest['schema_sha256']!=sha(self.c.schema):raise ValueError('Seed manifest/installation/schema identity changed')
        if (state.get('batch_id')!=batch_id or manifest.get('batch_id')!=batch_id or len(state['members'])!=len(manifest['members'])
                or [(m['member_id'],m['alias']) for m in state['members']]!=[(m['member_id'],m['alias']) for m in manifest['members']]):raise ValueError('Seed state member identity/count changed')
        binary=Path(self.c.install['terminal_data_root'])/'MQL5/Experts'/self.c.install['ea_relative_path'].replace('\\','/')
        if digest(binary)!=self.c.install['ea_sha256']:raise ValueError('Installed EA binary changed')
        for member in manifest['members']:
            for key,hashkey in [('set_path','set_sha256'),('config_path','config_sha256')]:
                if digest(member[key])!=member[hashkey]:raise ValueError('Frozen seed material changed: '+key)
        for item in state['members']:
            if item.get('result'):
                saved=item['result']
                if digest(saved['path'])!=saved['sha256'] or digest(saved['xml_path'])!=saved['xml_sha256']:raise ValueError('Retained completed seed evidence changed')
        return root,manifest,state

    def _save(self,root,state):
        state['updated_unix']=self.clock()
        if len(json.dumps(state).encode('utf-8'))>MAX_STATE_BYTES:raise ValueError('Seed state exceeds 32 MiB')
        write_json(root/'state.json',state)

    def _public(self,root,state):
        if len(state['members'])<=MAX_PUBLIC_MEMBERS:return state
        counts={}
        for item in state['members']:counts[item['status']]=counts.get(item['status'],0)+1
        return {key:value for key,value in state.items() if key!='members'}|dict(member_count=len(state['members']),status_counts=counts,
            members_omitted=True,state_path=str(root/'state.json'),manifest_path=str(root/'manifest.json'),native_launch_qualified=False)

    def _owner(self,generation=None):
        state=self.c.state()
        if state['owner']!='agent' or (generation is not None and state['generation']!=generation):raise ValueError('Human Studio grant is missing or changed; no further seed effects')
        queues=[state['queue']]
        if hasattr(self.c,'store'):
            queues=[json.loads(row[0]) for row in self.c.store.db.execute('SELECT jobs FROM studio_queues')]
        if any(j['status'] in BUSY for jobs in queues for j in jobs):raise ValueError('Unresolved native batch must finish before seed workflow')
        return state

    def _slot(self,batch_id,state):
        if not self.slot.exists():raise ValueError('Seed ownership receipt missing')
        slot=read_json(self.slot)
        if slot.get('batch_id')!=batch_id or slot.get('manifest_sha256')!=state['manifest_sha256'] or slot.get('status')!='active':raise ValueError('Seed ownership receipt differs')

    def prepare(self,batch_id,plan):
        root=self.path(batch_id)
        keys={'schema_version','max_attempts_per_job','job_timeout_seconds','cutoff','jobs'}
        if not isinstance(plan,dict) or set(plan)!=keys or plan['schema_version']!=1 or type(plan['max_attempts_per_job']) is not int or plan['max_attempts_per_job']!=1:raise ValueError('Seed plan requires schema_version=1, max_attempts_per_job=1, job_timeout_seconds, cutoff and jobs')
        if type(plan['job_timeout_seconds']) is not int or not 30<=plan['job_timeout_seconds']<=86400:raise ValueError('job_timeout_seconds must be 30..86400')
        cutoff=plan['cutoff']
        if not isinstance(cutoff,dict) or set(cutoff)!={'min_fitness','min_trades'} or type(cutoff['min_fitness']) not in (int,float) or not math.isfinite(cutoff['min_fitness']) or type(cutoff['min_trades']) is not int or cutoff['min_trades']<0:raise ValueError('Explicit finite min_fitness and nonnegative integer min_trades cutoff required')
        if not isinstance(plan['jobs'],list) or not 1<=len(plan['jobs'])<=10000:raise ValueError('Seed jobs must contain 1..10000 explicit file/asset configurations')
        if root.exists():
            _,old,_=self._read(batch_id)
            if old['plan_sha256']!=sha(plan):raise ValueError('Seed batch ID already belongs to a different plan')
            return self.status(batch_id)
        members=[];payloads=[];identities=set();retained_bytes=0;nonce=uuid.uuid4().hex[:16]
        account=self.c.session['account']
        for index,job in enumerate(plan['jobs']):
            if not isinstance(job,dict) or set(job)!={'set_path','tester','frame_target'}:raise ValueError('Each seed job requires set_path, full tester and frame_target')
            tester=validate_tester(job['tester'])
            if tester['ForwardMode']!=0 or tester['Expert']!=self.c.install['ea_relative_path']:raise ValueError('Seed tester must use installed Expert and ForwardMode=0')
            if not re.fullmatch(r'[A-Za-z0-9_.# -]{1,80}',tester['Symbol']):raise ValueError('Symbol cannot contain filename/protocol delimiters')
            target=job['frame_target']
            if type(target) is not int or not 1<=target<=1000000:raise ValueError('frame_target must be 1..1000000')
            if not isinstance(job['set_path'],str) or not Path(job['set_path']).is_absolute():raise ValueError('Seed source SET path must be absolute')
            source,raw,text=source_bytes(job['set_path']);valid=validate_raw(raw,self.c.schema,self.c.policy,require_optimization=True)
            original_values=read_values(raw)
            for name in valid['active_axes']:
                definition=self.c.schema['inputs'][name];parts=original_values[name].split('||')
                for position in (1,2,3):
                    number=numeric(parts[position],definition,step=position==2)
                    if abs(number)>2**53 or (number*100000000).denominator!=1:
                        raise ValueError('Seed XML cannot preserve this axis precision exactly: '+name)
            identity=sha([valid['sha256'],tester,target])
            if identity in identities:raise ValueError('Duplicate seed file/asset/settings identity')
            identities.add(identity)
            alias='S'+nonce+'_'+str(index+1).zfill(5)
            desc=alias+'@{mode=SeedFarming,n='+str(target)+',from='+tester['FromDate']+',to='+tester['ToDate']+'}'
            frozen=b'\xff\xfe'+''.join('EA_Desc='+desc+'\r\n' if line.startswith('EA_Desc=') else line for line in text.splitlines(keepends=True)).encode('utf-16-le')
            values=read_values(frozen)
            validate_raw(frozen,self.c.schema,self.c.policy,require_optimization=True)
            setpath=root/(alias+'.set')
            configpath=Path(self.c.install['terminal_data_root'])/'config/GOATStudio/Seeds'/(alias+'.ini')
            sections={'Common':{'Login':account['login'],'Server':account['server']},'Experts':{'Enabled':0,'AllowLiveTrading':0},
                'Tester':tester|{'ShutdownTerminal':1,'ReplaceReport':0,'Report':'MQL5\\Files\\GOATStudio\\SeedReports\\'+alias+'.xml'},'TesterInputs':values}
            ini=''
            for section,items in sections.items():
                ini+='['+section+']\r\n'
                for key,value in items.items():
                    if any(c in str(value) for c in '\r\n\x00'):raise ValueError('Unsafe startup value')
                    ini+=key+'='+str(value)+'\r\n'
            config=ini.encode('utf-16')
            retained_bytes+=len(raw)+len(frozen)+len(config)
            if retained_bytes>MAX_RETAINED_INPUT_BYTES:raise ValueError('Retained seed input matrix exceeds 128 MiB')
            member=dict(member_id=identity,index=index,alias=alias,account=account,tester=tester,frame_target=target,
                source_path=str(source),source_sha256=valid['sha256'],set_path=str(setpath),set_sha256=hashlib.sha256(frozen).hexdigest(),
                config_path=str(configpath),config_sha256=hashlib.sha256(config).hexdigest(),values=values,axes=valid['active_axes'],
                xml_title=Path(self.c.install['ea_relative_path'].replace('\\','/')).stem+' '+tester['Symbol']+','+tester['Period']+' '+tester['FromDate']+'-'+tester['ToDate']+' '+alias,
                output_base=Path(self.c.install['ea_relative_path'].replace('\\','/')).stem+' '+tester['Symbol']+','+tester['Period']+' '+tester['FromDate']+'-'+tester['ToDate']+' '+re.sub('[^A-Za-z0-9]','',alias)[:52])
            members.append(member);payloads.extend([(setpath,frozen),(configpath,config)])
        manifest=dict(schema_version=1,batch_id=batch_id,installation_sha256=sha(self.c.install),schema_sha256=sha(self.c.schema),plan_sha256=sha(plan),
            plan=plan,created_unix=self.clock(),members=members,mode='SeedFarming',native_launch_qualified=False)
        if len(json.dumps(manifest).encode('utf-8'))>MAX_MANIFEST_BYTES:raise ValueError('Seed manifest exceeds 128 MiB; split the matrix')
        # No SET/config write before every job and aggregate bound passes validation.
        root.mkdir(parents=True,exist_ok=False)
        (Path(self.c.install['terminal_data_root'])/'MQL5/Files/GOATStudio/SeedReports').mkdir(parents=True,exist_ok=True)
        for path,raw in payloads:
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(raw)
        write_json(root/'manifest.json',manifest)
        state=dict(schema_version=1,batch_id=batch_id,manifest_sha256=digest(root/'manifest.json'),status='prepared',generation=None,
            members=[dict(member_id=m['member_id'],alias=m['alias'],status='pending',attempts=0,result=None) for m in members])
        self._save(root,state)
        return self.status(batch_id)

    def _outputs(self,member):
        directory=Path(self.c.install['common_files_root'])/'GOAT/SeedFarmingXML'
        return list(directory.glob(member['output_base']+'_N*.xml')) if directory.exists() else []

    def _observe(self,root,manifest,state):
        current=self.process.inspect()
        if state['status']=='active' and current is not None and not any(m['status'] in ('running','starting','cancel_requested','timeout_requested') for m in state['members']):
            state['status']='reconcile_required';state['error']='Unowned selected-terminal process appeared between seed members'
        for spec,item in zip(manifest['members'],state['members']):
            if item['status'] not in ('running','closing','starting','cancel_requested','timeout_requested'):continue
            expected=item.get('process')
            if item['status']=='starting' and expected is None:
                state['status']='reconcile_required';item['status']='reconcile_required';item['error']='Start receipt has no process identity; automatic retry forbidden';break
            if current is not None:
                if current!=expected:
                    state['status']='reconcile_required';item['status']='reconcile_required';item['error']='Selected terminal PID/provenance changed';break
                continue
            paths=self._outputs(spec)
            result=None
            if len(paths)>1:
                item['status']='failed';item['error']='Ambiguous seed XML outputs'
            elif paths:
                try:
                    result=collect(paths[0],spec,self.c.schema,manifest['plan']['cutoff'])
                    if paths[0].stat().st_mtime<item.get('started_unix',manifest['created_unix'])-2:raise ValueError('Seed XML predates attempt')
                    write_json(root/(spec['alias']+'.result.json'),result)
                    item['result']=dict(path=str(root/(spec['alias']+'.result.json')),sha256=digest(root/(spec['alias']+'.result.json')),summary=result['summary'],xml_path=result['path'],xml_sha256=result['sha256'])
                except (ValueError,OSError) as exc:item['status']='failed';item['error']=str(exc)
            if item['status'] in ('running','closing','cancel_requested','timeout_requested'):
                item['status']='cancelled' if item['status']=='cancel_requested' else 'timeout' if item['status']=='timeout_requested' else 'completed' if result else 'missing_output'
            item['finished_unix']=self.clock()
        statuses={m['status'] for m in state['members']}
        if 'reconcile_required' in statuses:state['status']='reconcile_required'
        elif statuses<={'completed'}:state['status']='completed'
        elif any(s in statuses for s in ('failed','timeout','missing_output','cancelled')):state['status']='stopped'
        self._save(root,state)
        if state['status'] in ('completed','stopped') and current is None and self.slot.exists():
            slot=read_json(self.slot)
            if slot.get('batch_id')==manifest['batch_id'] and slot.get('manifest_sha256')==state['manifest_sha256']:
                write_json(self.slot,slot|{'status':'released'})
        return current

    def status(self,batch_id):
        with exclusive_gate(self.gate):
            root,manifest,state=self._read(batch_id)
            self._observe(root,manifest,state)
        members=[item|dict(tester=spec['tester'],source_sha256=spec['source_sha256'],frozen_set_sha256=spec['set_sha256'],config_sha256=spec['config_sha256'],requested_frames=spec['frame_target']) for spec,item in zip(manifest['members'],state['members'])]
        return self._public(root,state|dict(members=members,native_launch_qualified=False,manifest_path=str(root/'manifest.json'),report_path=str(root/'report.json')))

    def _activate(self,batch_id,root,manifest,state):
        owner=self._owner()
        observation,_=self.c.runtime(require_idle=True,expected_batch_ongoing=False)
        if observation.get('loaded') is not True or observation.get('owner')!='agent' or observation.get('generation')!=owner['generation']:
            raise ValueError('Fresh loaded licensed Studio dialog and matching human grant required')
        current=self.process.inspect()
        if current is None:raise ValueError('First seed start requires chosen running demo terminal and loaded licensed Studio')
        guard_active_seed(self.c.root)
        for spec in manifest['members']:
            if self._outputs(spec):raise ValueError('Seed output identity already exists before first attempt')
        state['generation']=owner['generation'];state['status']='closing_monitor';state['preflight']=observation;state['initial_process']=current
        self._save(root,state)
        write_json(self.slot,dict(status='active',batch_id=batch_id,manifest_sha256=state['manifest_sha256'],generation=state['generation']))
        self.process.close(current)

    def start(self,batch_id,max_seconds=60):return self._drive(batch_id,max_seconds,initial=True)
    def resume(self,batch_id,max_seconds=60):return self._drive(batch_id,max_seconds,initial=False)

    def _drive(self,batch_id,max_seconds,initial):
        if type(max_seconds) is not int or not 1<=max_seconds<=3600:raise ValueError('max_seconds must be 1..3600')
        deadline=self.clock()+max_seconds
        while self.clock()<deadline:
            self.c.bridge.pump()
            with exclusive_gate(self.gate):
                root,manifest,state=self._read(batch_id)
                if state['status'] in ('completed','stopped','reconcile_required'):return self._public(root,state)
                if state['status']=='prepared':
                    if not initial:raise ValueError('Use seed-start for a prepared batch')
                    self._activate(batch_id,root,manifest,state)
                self._owner(state['generation']);self._slot(batch_id,state)
                current=self._observe(root,manifest,state)
                if state['status'] in ('completed','stopped','reconcile_required'):return self._public(root,state)
                if state['status']=='closing_monitor':
                    if current is not None and current!=state['initial_process']:raise ValueError('Monitor process changed during normal close')
                    if current is None:state['status']='active';self._save(root,state)
                running=next((m for m in state['members'] if m['status'] in ('running','cancel_requested','timeout_requested')),None)
                if running:
                    if running['status']=='running' and self.clock()-running['started_unix']>=manifest['plan']['job_timeout_seconds']:
                        running['status']='timeout_requested';self._save(root,state)
                        self.process.close(running['process'])
                elif current is None and state['status']=='active' and self.clock()<deadline:
                    index=next((i for i,m in enumerate(state['members']) if m['status']=='pending'),None)
                    if index is not None:
                        item=state['members'][index];spec=manifest['members'][index]
                        if item['attempts']!=0:raise ValueError('Seed retry forbidden')
                        if self._outputs(spec):raise ValueError('Output already exists for unstarted seed member')
                        self._owner(state['generation'])
                        item.update(status='starting',attempts=1,started_unix=self.clock());self._save(root,state)
                        try:
                            identity=self.process.start(spec['config_path'])
                            item.update(status='running',process=identity);self._save(root,state)
                        except BaseException as exc:
                            item.update(status='reconcile_required',error=str(exc));state['status']='reconcile_required';self._save(root,state);raise
            if self.clock()<deadline:self.sleep(min(1,deadline-self.clock()))
        return self.status(batch_id)|dict(driver_budget_exhausted=True,next_action='seed-resume continues the retained attempt; no retry')

    def cancel(self,batch_id):
        self.c.bridge.pump()
        with exclusive_gate(self.gate):
            root,manifest,state=self._read(batch_id)
            if state['status'] in ('completed','stopped'):return self._public(root,state)
            self._owner(state['generation'])
            if state['status']!='prepared':self._slot(batch_id,state)
            if state['status']=='prepared':
                for item in state['members']:item['status']='cancelled'
                state['status']='stopped';self._save(root,state)
                return self._public(root,state)|dict(stop_verified=True,native_started=False)
            current=self._observe(root,manifest,state)
            if state['status']=='reconcile_required':raise ValueError('Uncertain process provenance requires human inspection; no close sent')
            for item in state['members']:
                if item['status']=='pending':item['status']='cancelled'
                elif item['status']=='running':item['status']='cancel_requested'
            if current and state['status']=='closing_monitor' and current!=state['initial_process']:raise ValueError('Monitor process changed')
            self._save(root,state)
            if current:
                self.process.close(current)
            else:self._observe(root,manifest,state)
            return self._public(root,state)|dict(stop_verified=current is None)

    def report(self,batch_id):
        self.status(batch_id);root,manifest,state=self._read(batch_id);rows=[]
        for spec,item in zip(manifest['members'],state['members']):
            result=None
            if item.get('result'):
                saved=item['result']
                if digest(saved['path'])!=saved['sha256'] or digest(saved['xml_path'])!=saved['xml_sha256']:raise ValueError('Retained seed result changed')
                result=read_seed_json(saved['path'],MAX_RESULT_BYTES)
            rows.append(dict(member_id=spec['member_id'],alias=spec['alias'],symbol=spec['tester']['Symbol'],tester=spec['tester'],source_path=spec['source_path'],source_sha256=spec['source_sha256'],frozen_set_sha256=spec['set_sha256'],config_sha256=spec['config_sha256'],status=item['status'],requested_frames=spec['frame_target'],actual_frames=result['summary']['actual_frames'] if result else None,summary=result['summary'] if result else None,
                result_path=item['result']['path'] if result else None,result_sha256=item['result']['sha256'] if result else None,
                xml_path=item['result']['xml_path'] if result else None,xml_sha256=item['result']['xml_sha256'] if result else None))
        value=dict(schema_version=1,batch_id=batch_id,status=state['status'],members=rows,cutoff=manifest['plan']['cutoff'],
            missing_output_is_zero=False,scope='Seed search only; freeze exact candidates for independent validation before portfolios',native_launch_qualified=False)
        write_json(root/'report.json',value)
        if len(rows)>MAX_PUBLIC_MEMBERS:
            return dict(schema_version=1,batch_id=batch_id,status=state['status'],member_count=len(rows),report_path=str(root/'report.json'),
                report_sha256=digest(root/'report.json'),members_omitted=True,native_launch_qualified=False)
        return value|dict(report_path=str(root/'report.json'),report_sha256=digest(root/'report.json'))
