"""Frozen standalone SeedFarming matrix and recoverable, bounded process driver.

No native batch queue/control files are armed. All process effects have a durable
write-ahead state; uncertain start/close is never automatically retried.
"""
import hashlib
import math
import json
from pathlib import Path
import re
from contextlib import ExitStack
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_installation import read_json
from studio_native_gate import GateBusy,exclusive_gate
from studio_optimization_inputs import explicit_optimization_inputs,verify_explicit_inputs
from studio_research_launch import ResearchLaunchRefused
from studio_settings import validate_tester
from studio_strategy_settings import read_values,numeric
from studio_template_tools import source_bytes,validate_raw
from studio_seed_results import collect,read_seed_json,MAX_MANIFEST_BYTES,MAX_STATE_BYTES,MAX_RESULT_BYTES,MAX_XML_BYTES
from studio_seed_slot import guard_active_seed
from studio_terminal_isolation import controller_preflight

TERMINAL={'completed','cancelled','timeout','failed','missing_output'}
MAX_RETAINED_INPUT_BYTES=128*1024*1024
MAX_PUBLIC_MEMBERS=100
# A member that ran and ended without a usable result. It fails only itself: the batch continues
# with its pending members until a breaker rule trips (Claude-Mac, goatai#1885 5989126739).
FAILED_MEMBER=frozenset(('failed','timeout','missing_output'))
BREAKER_IN_A_ROW=3          # this many attempted members in a row failed
BREAKER_SHARE_MIN=4         # or at least half of the attempted members failed, once this many were attempted

BUSY={'reserved','starting','running','reconcile_required','verifying'}
# A batch-level doubt: some MT5 of the selected terminal ran between members (a person, or demo launch-terminal).
# It clears only once that MT5 is closed again and nothing runs a member (goatai#1885, T2 2026-10-05).
UNOWNED_BETWEEN_MEMBERS='Unowned selected-terminal process appeared between seed members'
# A member whose launch was sent but whose MT5 identity was never seen (a WMI stall at the launch, T2 2026-10-05)
# may be re-identified on resume/reconcile (_reidentify). The MT5 must be created inside its launch window:
# from the start record (less the 2 s clock margin of the output-age check) until start()'s own pre-launch
# inventory has finished, which can run through a full WMI stall retry (about 2 minutes) before the launch.
REIDENTIFY_EARLY_SECONDS=2
REIDENTIFY_LATE_SECONDS=240


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def launch_unconfirmed(error):
    """True for a member start error that only means "its MT5 identity was not seen" (never an explicit refusal
    such as a different PID, two processes or an exit): the startup wait ran out, a row had no path, or the
    inventory itself stalled or failed (members stranded before goatai#1885 PR D kept that raw error)."""
    from studio_seed_process import STARTUP_UNSEEN,UNKNOWN_EXECUTABLE
    error=str(error or '')
    return (error==UNKNOWN_EXECUTABLE or error.startswith(STARTUP_UNSEEN)
            or re.fullmatch(r"Command '.*' (timed out after [0-9.]+ seconds|returned non-zero exit status -?[0-9]+\.)",error,re.S) is not None)


class SeedRunner:
    # Words for plain member-failure reasons; runners that reuse this driver name their own output and commands.
    OUTPUT_NOUN='SeedFarming XML'
    COMMAND_PREFIX='seed'
    MEMBER_NOUN='member'
    ID_FLAG='--batch-id'

    def __init__(self,controller,*,process=None,clock=time.time,sleep=time.sleep):
        self.c=controller;self.clock=clock;self.sleep=sleep
        from studio_seed_process import WindowsSeedProcess,research_view
        if process is None:process=WindowsSeedProcess(controller)
        # Every member is a research MT5 launch (goatai#1885 PR E): low priority inside this
        # terminal's research job. The caller's own process (the demo agent's monitor) is unchanged.
        self.process=research_view(process)
        # locked_journal(event, details): set only by a caller that holds its terminal lock (the demo lane's
        # _exclusive()). Only then may seed-resume/seed-reconcile settle an unowned-process doubt (_settle_unowned)
        # or re-identify an unconfirmed member launch (_reidentify); each is journaled through it before the state.
        self.locked_journal=None
        # Member switch hold (studio_switch_hold, goatai#1885): None (the default, every tester) never holds.
        # The demo lane sets its loaded configuration and its stop check, which ends a hold at once.
        self.switch_hold=None
        self.stop_requested=None
        # Driver liveness (studio_seed_driver, support 64f1c5ae). The foreground lane records each start/resume
        # call in the run folder; a lane with its own driver record (the demo lane's detached driver) turns that
        # off and sets ``driver_probe(batch_id)`` instead. ``cli_lane``, ``receipt`` and ``next_step_budget``
        # spell the exact command in ``next_step``.
        self.driver_record=True
        self.driver_probe=None
        from studio_process_query import own_identity
        self.identity=own_identity
        self.cli_lane='studio'
        self.receipt=None
        self.next_step_budget=60
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

    def _restore_hint(self,state):
        """After the batch ends MT5 stays closed; a plain open may load an old chart profile."""
        if state.get('status') not in ('completed','stopped') or state.get('generation') is None:return {}
        run=str(getattr(self.c,'session',{}).get('run_id',''))
        profile='GOAT-Studio-'+run.removeprefix('session-') if re.fullmatch(r'session-[a-f0-9]{32}',run) else 'GOAT-Studio-<session>'
        return dict(monitor_profile=profile,next_action='Seed batch ended and MT5 is closed. Reopen the monitor with monitor-launch --attempt-id <new id>; it opens chart profile '+
            profile+' with the GOAT Studio monitor. A plain MT5 open can load the previous chart profile, which leaves runtime feedback stale (in MT5: File > Profiles > '+profile+').')

    def _public(self,root,state):
        state=state|{key:value for key,value in self._restore_hint(state).items() if key not in state}
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

    def _freeze(self,root,plan):
        """Validate the whole plan and build every frozen member in memory. Writes nothing."""
        keys={'schema_version','max_attempts_per_job','job_timeout_seconds','cutoff','jobs'}
        if not isinstance(plan,dict) or set(plan)!=keys or plan['schema_version']!=1 or type(plan['max_attempts_per_job']) is not int or plan['max_attempts_per_job']!=1:raise ValueError('Seed plan requires schema_version=1, max_attempts_per_job=1, job_timeout_seconds, cutoff and jobs')
        if type(plan['job_timeout_seconds']) is not int or not 30<=plan['job_timeout_seconds']<=86400:raise ValueError('job_timeout_seconds must be 30..86400')
        cutoff=plan['cutoff']
        if not isinstance(cutoff,dict) or set(cutoff)!={'min_fitness','min_trades'} or type(cutoff['min_fitness']) not in (int,float) or not math.isfinite(cutoff['min_fitness']) or type(cutoff['min_trades']) is not int or cutoff['min_trades']<0:raise ValueError('Explicit finite min_fitness and nonnegative integer min_trades cutoff required')
        if not isinstance(plan['jobs'],list) or not 1<=len(plan['jobs'])<=10000:raise ValueError('Seed jobs must contain 1..10000 explicit file/asset configurations')
        members=[];payloads=[];identities=set();retained_bytes=0;nonce=uuid.uuid4().hex[:16]
        account=self.c.session['account']
        for index,job in enumerate(plan['jobs']):
            if not isinstance(job,dict) or set(job)-{'strategy_ref'}!={'set_path','tester','frame_target'}:raise ValueError('Each seed job requires set_path, full tester and frame_target (optional: strategy_ref)')
            from studio_strategy_attribution import validate_ref
            strategy_ref=validate_ref(job.get('strategy_ref'),'Seed job %d'%(index+1))
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
            tagged=''.join('EA_Desc='+desc+'\r\n' if line.startswith('EA_Desc=') else line for line in text.splitlines(keepends=True))
            # Pin every non-axis optimizable input with an explicit ||N tuple so MT5's
            # saved tester profile cannot re-enable a stale optimize flag (extra axis).
            frozen=b'\xff\xfe'+explicit_optimization_inputs(tagged,self.c.schema).encode('utf-16-le')
            values=read_values(frozen)
            pinned=validate_raw(frozen,self.c.schema,self.c.policy,require_optimization=True)
            if pinned['active_axes']!=valid['active_axes'] or any(values[name]!=original_values[name] for name in valid['active_axes']):
                raise ValueError('Pinned seed inputs changed the frozen template axes')
            if set(values)!=set(original_values) or any(values[name].split('||')[0]!=original_values[name].split('||')[0]
                    for name in values if name!='EA_Desc' and self.c.schema['inputs'][name]['type']!='string') or any(
                    values[name]!=original_values[name] for name in values if name!='EA_Desc' and self.c.schema['inputs'][name]['type']=='string'):
                raise ValueError('Pinned seed inputs changed a template trading value')
            verify_explicit_inputs(values,self.c.schema,valid['active_axes'])
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
            if strategy_ref is not None:member['strategy_ref']=strategy_ref
            members.append(member);payloads.extend([(setpath,frozen),(configpath,config)])
        # Held-out lock (goatai#2221 §4.3): no member of a locked strategy may read its window.
        from studio_heldout_guard import check_seed_jobs
        check_seed_jobs(self.c,plan,members)
        return members,payloads

    @staticmethod
    def _oos_windows(plan):
        """OOS window formula (goat-oos-windows-v1): a plan with oos_windows gets SAMPLE-only dates
        (FromDate..ForwardDate, ForwardMode 0) from O and the export Friday; others are unchanged."""
        from studio_oos_windows import apply_to_seed_plan
        return apply_to_seed_plan(plan)

    def validate(self,plan):
        """Non-executing check of a seed plan and every SET it names: no file, process or terminal effect."""
        filled,oos=self._oos_windows(plan)
        members,_=self._freeze(self.base/'validation-only',filled)
        # Same aggregate bound prepare enforces, so a validated plan cannot fail it later.
        manifest=dict(schema_version=1,batch_id='validation-only',installation_sha256=sha(self.c.install),schema_sha256=sha(self.c.schema),plan_sha256=sha(plan),
            plan=plan,created_unix=self.clock(),members=members,mode='SeedFarming',native_launch_qualified=False)
        if oos is not None:manifest['oos_windows']=oos
        if len(json.dumps(manifest).encode('utf-8'))>MAX_MANIFEST_BYTES:raise ValueError('Seed manifest exceeds 128 MiB; split the matrix')
        return dict(schema_version=1,valid=True,writes=False,native_launch_qualified=False,plan_sha256=sha(plan),job_count=len(members),
            **({} if oos is None else dict(oos_windows=dict(o_weeks=oos['o_weeks'],export_friday=oos['export_friday'],
                                                            sample=oos['sample'],seed_tester=oos['seed_tester']))),
            jobs=[dict(index=m['index'],symbol=m['tester']['Symbol'],period=m['tester']['Period'],from_date=m['tester']['FromDate'],to_date=m['tester']['ToDate'],
                       frame_target=m['frame_target'],axes=m['axes'],source_path=m['source_path'],source_sha256=m['source_sha256']) for m in members[:MAX_PUBLIC_MEMBERS]],
            jobs_omitted=max(0,len(members)-MAX_PUBLIC_MEMBERS))

    def prepare(self,batch_id,plan):
        root=self.path(batch_id)
        if root.exists():
            _,old,_=self._read(batch_id)
            if old['plan_sha256']!=sha(plan):raise ValueError('Seed batch ID already belongs to a different plan')
            self._verify_prepared(batch_id,old)
            return self.status(batch_id)
        filled,oos=self._oos_windows(plan)
        members,payloads=self._freeze(root,filled)
        manifest=dict(schema_version=1,batch_id=batch_id,installation_sha256=sha(self.c.install),schema_sha256=sha(self.c.schema),plan_sha256=sha(plan),
            plan=filled,created_unix=self.clock(),members=members,mode='SeedFarming',native_launch_qualified=False)
        if oos is not None:
            # The plan as given (with its oos_windows request) stays hash-bound; the filled plan carries every date.
            manifest.update(requested_plan=plan,oos_windows=oos)
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

    def _output_dir(self,member):
        """The one folder this runner's member writes its output into. _outputs searches only here and _own_output
        accepts only a file directly in it, so a subclass that writes elsewhere overrides this (catch-up: TEMP/SQ/<token>)."""
        return Path(self.c.install['common_files_root'])/'GOAT/SeedFarmingXML'

    def _outputs(self,member):
        directory=self._output_dir(member)
        return list(directory.glob(member['output_base']+'_N*.xml')) if directory.exists() else []

    @staticmethod
    def _observed_xml(path):
        """Path, hash and filename frame count of an XML the controller did not accept.

        Hashed in chunks and only up to the collector's XML bound, so a refused
        oversized file is recorded without being loaded into memory.
        """
        sha256=None;size=None
        try:
            size=Path(path).stat().st_size
            if size<=MAX_XML_BYTES:
                h=hashlib.sha256()
                with Path(path).open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                sha256=h.hexdigest()
        except OSError:sha256=None
        match=re.search(r'_N(\d{1,7})_',Path(path).name)
        return dict(path=str(path),sha256=sha256,size_bytes=size,frames_from_filename=int(match[1]) if match else None,accepted=False)

    # Hooks for runners that reuse this process driver (studio_catchup). Seeds keep the defaults.
    def _collect(self,path,spec,manifest):
        return collect(path,spec,self.c.schema,manifest['plan']['cutoff'])

    def _before_start(self,spec):
        """Stage per-member inputs before the start receipt; must raise before any process effect."""

    def _verify_prepared(self,batch_id,manifest):
        """Refuse a seed package frozen before explicit ||N flags (MT5 could add axes).

        Runs before every process effect: prepare of an existing ID, activation,
        and each member launch, so start and resume cannot drive an old package.
        """
        for member in manifest['members']:
            try:verify_explicit_inputs(member['values'],self.c.schema,member['axes'])
            except ValueError as exc:
                raise ValueError('Seed batch '+batch_id+' was prepared before explicit optimization flags ('+str(exc)+
                    '); prepare a new batch ID') from None

    def _collect_member(self,root,manifest,spec,item,paths):
        """Collect this member's single output (age, identity and content checked), else mark it failed."""
        try:
            # Age check first: a collector may move the output it verified.
            if paths[0].stat().st_mtime<item.get('started_unix',manifest['created_unix'])-2:raise ValueError('Seed XML predates attempt')
            result=self._collect(paths[0],spec,manifest)
            write_json(root/(spec['alias']+'.result.json'),result)
            item['result']=dict(path=str(root/(spec['alias']+'.result.json')),sha256=digest(root/(spec['alias']+'.result.json')),summary=result['summary'],xml_path=result['path'],xml_sha256=result['sha256'])
            return result
        except (ValueError,OSError) as exc:
            item['status']='failed';item['error']=str(exc)
            # Keep the refused XML visible (never as accepted evidence) for diagnosis.
            item['observed_xml']=self._observed_xml(paths[0])
            return None

    LIVE_MEMBER={'running','starting','closing','cancel_requested','timeout_requested'}

    def _idle_proof(self,manifest,state,current):
        """Fresh proof that nothing of this batch can still run or write. None when proven, else the reason.

        ``current`` is the selected MT5 from the inventory taken NOW (an earlier refusal such as an
        unknown executable is never replayed). Required: no member is live; no terminal64 process
        anywhere has a member's frozen INI or alias on its command line (no terminal64 child of the
        seed); and an open selected MT5 is none of the recorded member processes, names no member
        on its own command line and reports, through the bound monitor, a loaded EA with the tester
        idle and no batch ongoing. The demo lane adds its broker process check around the call.
        """
        if any(item['status'] in self.LIVE_MEMBER for item in state['members']):
            return 'A member of this seed batch is still starting or running'
        names=[Path(spec['config_path']).name for spec in manifest['members']]+[spec['alias'] for spec in manifest['members']]
        users=getattr(self.process,'config_users',None)
        if users is not None:
            try:
                if users(names):return 'An MT5 process is still running a member of this seed batch'
            except Exception as exc:
                return 'The MT5 process inventory could not be read ('+str(exc)+')'
        elif current is not None:
            return 'This process tool cannot prove which MT5 runs a seed member'
        if current is None:return None
        if any(current==item.get('process') for item in state['members']):
            return 'The selected MT5 is the process a member started'
        reader=getattr(self.process,'command_line',None)
        if reader is None:return 'The selected MT5 command line cannot be read'
        try:line=(reader(current) or '').casefold()
        except Exception as exc:return 'The selected MT5 command line cannot be read ('+str(exc)+')'
        if any(name.casefold() in line for name in names):return 'The selected MT5 was started for a member of this seed batch'
        try:observation,_=self.c.runtime(require_idle=True,expected_batch_ongoing=False)
        except (ValueError,OSError,KeyError) as exc:return 'The GOAT monitor does not report an idle tester ('+str(exc)+')'
        if not isinstance(observation,dict) or observation.get('loaded') is not True:
            return 'The GOAT monitor is not loaded in the selected MT5'
        if (getattr(self.c,'session',None) or {}).get('authority_kind')=='native_human_control':
            # Customer lane: the broker SDK proves this exact process is the same idle demo (Algo off, no trades).
            # The owner demo lane takes its own broker readback around the call (demo_agent._lane_reconcile).
            from studio_config_start import sdk_idle_demo
            try:sdk_idle_demo(self.c,current)
            except (ValueError,OSError) as exc:return 'The broker check of the selected MT5 did not pass ('+str(exc)+')'
        return None

    def _own_output(self,spec,item):
        """The member's single output, inside its output folder, not a link, written after its start. (path, reason)."""
        directory=self._output_dir(spec)
        paths=self._outputs(spec)
        if not paths:return None,'No output from this member exists; nothing is inferred'
        if len(paths)>1:return None,'More than one output names this member; a person decides'
        path=paths[0]
        try:
            if path.is_symlink() or not path.is_file():return None,'The member output is a link or not a regular file'
            if path.resolve().parent!=directory.resolve():return None,'The member output is outside its output folder'
            if path.stat().st_mtime<item.get('started_unix',0)-2:return None,'The member output predates its start'
        except OSError as exc:return None,'The member output cannot be read ('+str(exc)+')'
        return path,None

    def _settle_member(self,root,manifest,spec,item,current,basis):
        """Collect one reconcile_required member exactly as a normal completion. Never synthesises a result."""
        path,reason=self._own_output(spec,item)
        if reason:return reason
        try:
            before=digest(path)
            result=self._collect(path,spec,manifest)
            if result.get('sha256')!=before or digest(result['path'])!=result['sha256']:
                raise ValueError('The member output changed while it was collected')
        except (ValueError,OSError,KeyError) as exc:
            item['observed_xml']=self._observed_xml(path)
            return 'The member output did not pass the completion checks: '+str(exc)
        write_json(root/(spec['alias']+'.result.json'),result)
        item['result']=dict(path=str(root/(spec['alias']+'.result.json')),sha256=digest(root/(spec['alias']+'.result.json')),
                            summary=result['summary'],xml_path=result['path'],xml_sha256=result['sha256'])
        item['reconciled']=dict(from_status='reconcile_required',prior_error=item.get('error'),reconciled_unix=self.clock(),
                                basis=basis,process=current,xml_sha256=result['sha256'])
        item.pop('error',None);item.pop('reconcile_reason',None);item.pop('reidentify',None)
        item['status']='completed';item['finished_unix']=self.clock()
        return None

    def _stray_output(self,root,spec):
        """Paths of any output a member already has before its start (its own output or a retained result)."""
        found=[str(p) for p in self._outputs(spec)]
        found+=[str(root/(spec['alias']+suffix)) for suffix in ('.result.json','.report.htm','.deals.json') if (root/(spec['alias']+suffix)).exists()]
        return found

    def _settle_unowned(self,root,manifest,state):
        """The unowned MT5 is gone (re-inspected now) and nothing runs a member: settle the doubt as a stop.

        Claude-Mac (#1885): never straight back to active. The batch becomes stopped with stopped_reason
        unowned_settled, so only the start-grade re-activation (seed-resume) continues it. A pending member that
        already has output (the unowned MT5 may have run it) fails with that reason and is never collected.
        """
        now=self.clock()
        stray=[(item,spec['alias'],paths) for spec,item in zip(manifest['members'],state['members'])
               if item['status']=='pending' for paths in [self._stray_output(root,spec)] if paths]
        pending=sum(m['status']=='pending' for m in state['members'])-len(stray)
        after={m['status'] for m in state['members'] if not any(m is s for s,_,_ in stray)}|({'failed'} if stray else set())
        settled=dict(prior_error=state['error'],unix=now,stray_members=[alias for _,alias,_ in stray],
            basis='The selected MT5 is closed (re-inspected now), no member is live and no MT5 runs a member INI or alias')
        # Journal first (under the caller's terminal lock), so a settled doubt is never unrecorded.
        self.locked_journal('unowned_settled',dict(prior_error=settled['prior_error'],stray_members=settled['stray_members'],
                                                   pending=pending,status='stopped' if pending else self._end_status(after)))
        for item,_,paths in stray:
            item.update(status='failed',finished_unix=now,stray_output=paths,
                        error='Output present before its start (an MT5 this batch did not start may have run it); it is never collected')
        stray=settled['stray_members']
        state['unowned_settled']=settled
        state['error']=None
        statuses={m['status'] for m in state['members']}
        if pending:
            state['status']='stopped'
            state['stopped_reason']=dict(rules=['unowned_settled'],pending=pending,reasons=[dict(alias=a,status='failed',error='output present before its start') for a in stray],
                plain=('An MT5 this batch did not start ran between members; it is closed now and nothing runs a member. '
                       +self.COMMAND_PREFIX+'-resume re-activates the %d pending %s%s under the start-grade check (MT5 open on the GOAT '
                       'monitor).'%(pending,self.MEMBER_NOUN,'' if pending==1 else 's')))
        else:
            state['status']=self._end_status(statuses)

    def _reconcile(self,root,manifest,state,current,*,settle_unowned=False):
        """Settle reconcile_required members whose own output passes every completion check. Returns the reasons left.

        ``settle_unowned`` (seed-resume and seed-reconcile only, never a status read) also settles the batch-level
        "unowned process" doubt once that MT5 is closed and the idle proof passes (_settle_unowned), and only for a
        caller that holds its terminal lock and journals it (``locked_journal``: the demo lane). The customer
        lane keeps the earlier rule: seed-cancel settles the doubt once MT5 is idle.
        """
        if (settle_unowned and self.locked_journal is not None and state.get('error')==UNOWNED_BETWEEN_MEMBERS
                and state['status']=='reconcile_required' and current is None
                and not any(m['status']=='reconcile_required' for m in state['members'])
                and self._idle_proof(manifest,state,current) is None):
            self._settle_unowned(root,manifest,state)
            return []
        targets=[(spec,item) for spec,item in zip(manifest['members'],state['members'])
                 if item['status']=='reconcile_required' and item.get('attempts')==1 and not item.get('result') and 'started_unix' in item]
        if not targets:reasons=[]
        elif state.get('error')==UNOWNED_BETWEEN_MEMBERS and self.locked_journal is not None:
            reasons=[state['error']+'; close that MT5, then '+self.COMMAND_PREFIX+'-resume continues (or '+self.COMMAND_PREFIX
                     +'-cancel settles it once MT5 is idle)']
        elif state.get('error') is not None:
            reasons=[state['error']+'; '+self.COMMAND_PREFIX+'-cancel settles it once MT5 is idle']
        else:
            idle=self._idle_proof(manifest,state,current)
            reasons=[idle] if idle else []
        basis=('MT5 closed' if current is None else 'MT5 open on the idle GOAT monitor')+', re-inspected now; the member wrote its own output after its start'
        for spec,item in targets:
            reason=reasons[0] if reasons else self._settle_member(root,manifest,spec,item,current,basis)
            if reason:item['reconcile_reason']=reason
        statuses={m['status'] for m in state['members']}
        if (state['status']=='reconcile_required' and 'reconcile_required' not in statuses and state.get('error') is None
                and (targets or self._idle_proof(manifest,state,current) is None)):
            if 'pending' not in statuses:
                state['status']=self._end_status(statuses)
                if statuses&FAILED_MEMBER:state['failed_members']=sum(m['status'] in FAILED_MEMBER for m in state['members'])
                if current is not None:state['idle_settled']=dict(process=current,unix=self.clock())
            elif current is None:state['status']='active'          # the driver continues the pending members
            # Pending members while MT5 is open: seed-cancel settles them; nothing is closed or relaunched here.
        return [item['reconcile_reason'] for _,item in targets if item['status']=='reconcile_required']

    def _adoption_refusal(self,spec,item,state,current):
        """Why the selected MT5 cannot be adopted as this member's own launch, or None when every proof holds NOW."""
        if self.locked_journal is None:
            return 'Re-identifying a launch needs the demo lane terminal lock (demo '+self.COMMAND_PREFIX+'-resume or -reconcile)'
        if state.get('error') is not None:return 'A batch-level doubt is open ('+str(state['error'])+')'
        if any(m['status'] in self.LIVE_MEMBER for m in state['members']):return 'Another member of this batch is live'
        from studio_seed_process import created_unix
        created=created_unix((current or {}).get('created_utc'))
        if created is None:return 'The selected MT5 creation time cannot be read'
        if not item['started_unix']-REIDENTIFY_EARLY_SECONDS<=created<=item['started_unix']+REIDENTIFY_LATE_SECONDS:
            return 'The selected MT5 was not created inside this %s launch window'%self.MEMBER_NOUN
        reader=getattr(self.process,'command_line',None);users=getattr(self.process,'config_users',None)
        if reader is None or users is None:return 'This process tool cannot read MT5 command lines'
        ini=str(Path(spec['config_path']).resolve())
        try:line=reader(current) or ''
        except Exception as exc:return 'The selected MT5 command line cannot be read ('+str(exc)+')'
        if not re.search(r'(?:^|[\s"])/config:'+re.escape(ini)+r'(?:$|[\s"])',line,re.I):
            return 'The selected MT5 command line does not name this %s\'s own /config: INI'%self.MEMBER_NOUN
        try:named=users([Path(spec['config_path']).name])
        except Exception as exc:return 'The MT5 process inventory could not be read ('+str(exc)+')'
        if len(named)!=1 or named[0].get('pid')!=current.get('pid'):
            return ('%d terminal64 processes name this %s INI; exactly one, the selected MT5, is required'
                    %(len(named),self.MEMBER_NOUN))
        try:
            # Last, after the command line: the INI MT5 runs must still be the bytes this batch wrote.
            if digest(spec['config_path'])!=spec['config_sha256']:return 'This %s INI changed after the batch wrote it'%self.MEMBER_NOUN
        except OSError as exc:return 'This %s INI cannot be read ('%self.MEMBER_NOUN+str(exc)+')'
        return None

    def _reidentify(self,root,manifest,state,current):
        """Adopt the selected MT5 as the member it was launched for when that launch was never confirmed.

        goatai#1885 PR D (Claude-Mac APPROVE with amendments): a WMI stall right after a member launch left the
        member reconcile_required while its own MT5 ran the tester. Only seed-resume and seed-reconcile come
        here (never a status read), and only for a caller that holds its terminal lock and journals the
        adoption (``locked_journal``, written before the state). Every proof is read NOW: exactly one uncertain member, whose start
        was sent but never confirmed (no recorded process); no batch-level doubt; the selected MT5 is the
        installation's own terminal64.exe, created inside that member's launch window; its command line names
        this member's own /config: INI; exactly one terminal64 anywhere names that INI; and the INI is still
        the bytes the batch wrote. Otherwise the member stays reconcile_required with the reason. Nothing is
        launched, closed or re-run: the driver then observes and collects the member as usual.
        """
        uncertain=[(spec,item) for spec,item in zip(manifest['members'],state['members']) if item['status']=='reconcile_required']
        if len(uncertain)!=1:return
        spec,item=uncertain[0]
        if (item.get('attempts')!=1 or item.get('process') is not None or item.get('result')
                or type(item.get('started_unix')) not in (int,float) or not launch_unconfirmed(item.get('error'))):
            return
        reason=self._adoption_refusal(spec,item,state,current)
        if reason:
            item['reidentify']=dict(adopted=False,reason=reason,process=current,unix=self.clock())
            return
        record=dict(process=current,prior_error=item.get('error'),unix=self.clock(),config_sha256=spec['config_sha256'],
                    basis=('The selected MT5 (re-inspected now) runs this '+self.MEMBER_NOUN+'\'s own unchanged /config: INI, '
                           'is the only terminal64 naming it and was created inside its launch window'))
        # Journal first, so an adoption is never unrecorded (Claude-Mac on GOAT-EA#163).
        self.locked_journal('reidentified',dict(record,alias=spec['alias']))
        for key in ('error','reconcile_reason','reidentify'):item.pop(key,None)
        item.update(status='running',process=current,reidentified=record)
        state['status']='active'
        self._save(root,state)

    def _observe(self,root,manifest,state,*,settle_unowned=False,budget=None):
        # Always the CURRENT inventory: an earlier refusal (e.g. an unknown executable) is never replayed.
        # A status read passes ``budget`` (POLL_BUDGET) so a WMI stall never holds it for the full launch retry.
        from studio_seed_process import inspect_within
        current=inspect_within(self.process,budget)
        if state['status']=='reconcile_required':
            state['last_inspection']=dict(process=current,unix=self.clock())
            if current is None:self._reconcile(root,manifest,state,current,settle_unowned=settle_unowned)   # MT5 closed (#132); open MT5: seed-reconcile
            elif settle_unowned:self._reidentify(root,manifest,state,current)       # resume/reconcile only: our own launch?
        if state['status']=='active' and current is not None and not any(m['status'] in ('running','starting','cancel_requested','timeout_requested') for m in state['members']):
            state['status']='reconcile_required';state['error']=UNOWNED_BETWEEN_MEMBERS
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
                result=self._collect_member(root,manifest,spec,item,paths)
            if item['status'] in ('running','closing','cancel_requested','timeout_requested'):
                item['status']='cancelled' if item['status']=='cancel_requested' else 'timeout' if item['status']=='timeout_requested' else 'completed' if result else 'missing_output'
                if item['status'] in ('timeout','missing_output') and not item.get('error'):
                    item['error']=self._failure_reason(manifest,item)
            item['finished_unix']=self.clock()
        self._settle_status(state)
        self._settle_slot(root,manifest,state,current)
        return current

    # ---- member failures (goatai#1885: one member's missing output must not end the batch) ----------------

    def _failure_reason(self,manifest,item):
        """One plain sentence for a member that ended without a usable result. Nothing is inferred from it."""
        budget=(manifest.get('plan') or {}).get('job_timeout_seconds')
        ran=None
        if type(item.get('started_unix')) in (int,float):ran=max(0,int(round(self.clock()-item['started_unix'])))
        if item['status']=='timeout':
            return ('The %s ran past its %s s budget, so GOAT asked MT5 to close normally. Nothing is inferred from it.'
                    %(self.MEMBER_NOUN,budget))
        return ('MT5 closed%s without writing this %s\'s %s. Nothing is inferred: the %s has no result. If the driver was '
                'interrupted (for example a tool timeout ended a foreground %s-start or %s-resume), MT5 may have closed with it.'
                %('' if ran is None else ' after %d s%s'%(ran,'' if budget is None else ' of its %s s budget'%budget),
                  self.MEMBER_NOUN,self.OUTPUT_NOUN,self.MEMBER_NOUN,self.COMMAND_PREFIX,self.COMMAND_PREFIX))

    @staticmethod
    def _end_status(statuses):
        """Status of a batch whose members have all ended: completed when any member completed and none was cancelled."""
        if statuses<={'completed'}:return 'completed'
        return 'completed' if 'completed' in statuses and 'cancelled' not in statuses else 'stopped'

    def _breaker(self,state):
        """stopped_reason when failures look systemic, else None (Claude-Mac, #1885 5989126739).

        Counts only members attempted since the batch was last (re-)activated, in launch order:
        3 failures in a row, or failures reaching half of at least 4 attempted members.
        Every failed member's reason is listed.
        """
        since=(state.get('reactivations') or [{}])[-1].get('unix')
        ended=sorted((m for m in state['members'] if m.get('attempts') and m['status'] in FAILED_MEMBER|{'completed'}
                      and (since is None or (m.get('started_unix') or 0)>=since)),key=lambda m:m.get('started_unix') or 0)
        failed=[m for m in ended if m['status'] in FAILED_MEMBER]
        in_a_row=0
        for m in reversed(ended):
            if m['status'] not in FAILED_MEMBER:break
            in_a_row+=1
        rules=[]
        if in_a_row>=BREAKER_IN_A_ROW:rules.append('in_a_row')
        if len(ended)>=BREAKER_SHARE_MIN and 2*len(failed)>=len(ended):rules.append('half_failed')
        if not rules:return None
        pending=sum(m['status']=='pending' for m in state['members'])
        why=[]
        if 'in_a_row' in rules:why.append('%d %ss in a row failed'%(in_a_row,self.MEMBER_NOUN))
        if 'half_failed' in rules:why.append('%d of %d attempted %ss failed'%(len(failed),len(ended),self.MEMBER_NOUN))
        return dict(rules=rules,attempted=len(ended),failed=len(failed),in_a_row=in_a_row,pending=pending,
                    reasons=[dict(alias=m['alias'],status=m['status'],error=m.get('error')) for m in failed],
                    plain=('Stopped because '+' and '.join(why)+', which looks like a systemic fault rather than bad luck: '
                           +'; '.join(m['alias']+': '+str(m.get('error') or m['status']) for m in failed)
                           +'. Fix the cause, then '+self.COMMAND_PREFIX+'-resume continues the %d pending %s%s; completed and '
                           'failed %ss are never re-run.')%(pending,self.MEMBER_NOUN,'' if pending==1 else 's',self.MEMBER_NOUN))

    def _settle_status(self,state):
        """Batch status after member outcomes. A failed, timed-out or output-less member fails only itself: while
        members are pending an active batch continues, unless the breaker trips. Cancelled (owner STOP,
        cancel, TAKE) still stops the batch, and a stopped batch stays stopped until an explicit resume."""
        statuses={m['status'] for m in state['members']}
        if 'reconcile_required' in statuses:state['status']='reconcile_required';return
        if statuses<={'completed'}:state['status']='completed';return
        if 'cancelled' in statuses:state['status']='stopped';return
        failed=statuses&FAILED_MEMBER
        if not failed or statuses&self.LIVE_MEMBER:return
        if state['status'] not in ('active','closing_monitor'):
            # Already stopped (kept as recorded, including batches stopped before this rule), or a batch-level
            # doubt beside a failed member: stopped, exactly as before. Only seed-resume re-activates it.
            state['status']='stopped'
            return
        if 'pending' not in statuses:
            state['status']=self._end_status(statuses)
            state['failed_members']=sum(m['status'] in FAILED_MEMBER for m in state['members'])
            if state['status']=='stopped':
                failures=[m for m in state['members'] if m['status'] in FAILED_MEMBER]
                state['stopped_reason']=dict(rules=['every_member_failed'],attempted=len(failures),failed=len(failures),in_a_row=None,
                    pending=0,reasons=[dict(alias=m['alias'],status=m['status'],error=m.get('error')) for m in failures],
                    plain='Every attempted %s failed, so nothing was found: '%self.MEMBER_NOUN
                          +'; '.join(m['alias']+': '+str(m.get('error') or m['status']) for m in failures)+'.')
            return
        reason=self._breaker(state)
        if reason:state['status']='stopped';state['stopped_reason']=reason

    @staticmethod
    def resumable(state):
        """A stopped batch that seed-resume may re-activate: it started, nothing is uncertain or cancelled,
        no member runs, and members are still pending with no attempt. Completed and failed members are never re-run."""
        members=state.get('members') or []
        statuses={m.get('status') for m in members}
        return (state.get('status')=='stopped' and state.get('generation') is not None and state.get('error') is None
                and 'pending' in statuses and not statuses&({'cancelled','reconcile_required'}|SeedRunner.LIVE_MEMBER)
                and all(m.get('attempts')==0 for m in members if m.get('status')=='pending'))

    def status(self,batch_id):
        from studio_process_query import POLL_BUDGET
        with self._gate():
            root,manifest,state=self._read(batch_id)
            self._observe(root,manifest,state,budget=POLL_BUDGET)
        members=[item|dict(tester=spec['tester'],source_sha256=spec['source_sha256'],frozen_set_sha256=spec['set_sha256'],config_sha256=spec['config_sha256'],requested_frames=spec['frame_target']) for spec,item in zip(manifest['members'],state['members'])]
        result=self._public(root,state|dict(members=members,native_launch_qualified=False,manifest_path=str(root/'manifest.json'),report_path=str(root/'report.json'),pause_requested=self.paused(batch_id)))
        # Added fields only (support 64f1c5ae): is a start/resume call driving this run, and the exact next step.
        # Read after the gate is released; the liveness check never writes and never holds the gate, and all of it
        # shares one short deadline (studio_seed_driver.CHECK_SECONDS).
        detail=self.driver_state(batch_id)
        return result|dict(driver=detail['state'],driver_detail=detail,next_step=self._next_step(batch_id,state,detail))

    # ---- driver liveness and the next step (support 64f1c5ae) ------------------------------------------
    #
    # This lane has no background driver: each start/resume call drives for at most --max-seconds and nothing
    # advances between calls. A status read says whether such a call is in progress now (studio_seed_driver),
    # and names the one exact command that moves the run on. Unknown is said as unknown.

    def driver_state(self,batch_id,*,budget=None,deadline=None):
        """Read-only: dict(state='running'|'none'|'unknown', basis, call, last_call) for this run's driver.
        ``deadline`` (a time.monotonic() time) is shared by several runs' checks, e.g. one research-queue call."""
        from studio_seed_driver import UNKNOWN,liveness
        root=self.path(batch_id)
        if self.driver_probe is not None:
            try:return self.driver_probe(batch_id)
            except Exception as exc:
                return dict(state=UNKNOWN,basis='GOAT cannot tell whether a driver runs this '+self.COMMAND_PREFIX+' run ('+str(exc)[:200]+'). Nothing is inferred.',
                            call=None,last_call=None)
        if not self.driver_record:
            return dict(state=UNKNOWN,basis='This lane keeps its driver record elsewhere; its own status command shows it.',call=None,last_call=None)
        if self._demo_started(batch_id):
            # Started on the owner demo lane: its detached driver records itself in demo-agent/lane-workers, not here.
            return dict(state=UNKNOWN,call=None,last_call=None,
                        basis='This run was started on the owner demo lane, whose detached driver this command does not read; '
                              'goat.exe demo --installation <receipt> '+self.COMMAND_PREFIX+'-status '+self.ID_FLAG+' '+batch_id+' shows it.')
        return liveness(root,alive=getattr(self.process,'process_alive',None),budget=budget,deadline=deadline,
                        command_prefix=self.COMMAND_PREFIX)

    def driver_summary(self,batch_id,*,budget=None,deadline=None):
        """Read-only, for research-status and research-queue: driver liveness plus next_step, from the retained state.
        No gate and no MT5 inventory; only a recorded driver's own process is checked."""
        detail=self.driver_state(batch_id,budget=budget,deadline=deadline)
        try:state=read_seed_json(self.path(batch_id)/'state.json')
        except (OSError,ValueError,KeyError) as exc:
            return detail|dict(next_step=None,state_error=str(exc)[:200])
        return detail|dict(next_step=self._next_step(batch_id,state,detail))

    def _demo_started(self,batch_id):
        """A run started on the owner demo lane (its broker-verified start record), seen from the studio lane
        (a runner that keeps its own per-call record; the demo lane's runners do not)."""
        if not self.driver_record:return False
        try:return (Path(self.c.root)/'demo-agent'/(self.COMMAND_PREFIX+'-starts')/(batch_id+'.json')).is_file()
        except (OSError,TypeError):return False

    def _command(self,operation,batch_id,*,budget=False):
        """The exact CLI line of one operation on this run (the installation receipt when known). A run started on
        the demo lane is continued there (goat.exe demo, detached, so its longer budget)."""
        receipt=self.receipt or getattr(self.c,'receipt',None)
        where='"'+str(receipt)+'"' if receipt else '<installation receipt>'
        lane,seconds=('demo',3600) if self._demo_started(batch_id) else (self.cli_lane,self.next_step_budget)
        return ('goat.exe '+lane+' --installation '+where+' '+self.COMMAND_PREFIX+'-'+operation+' '+self.ID_FLAG+' '+batch_id
                +(' --max-seconds '+str(seconds) if budget else ''))

    def _next_step(self,batch_id,state,detail):
        """One plain sentence: what moves this run on now, with the exact supported command."""
        members=state.get('members') or []
        status=state.get('status')
        pending=sum(m.get('status')=='pending' for m in members)
        live=next((m for m in members if m.get('status') in self.LIVE_MEMBER),None)
        noun=self.MEMBER_NOUN;prefix=self.COMMAND_PREFIX
        def count(n):return '%d %s%s'%(n,noun,'' if n==1 else 's')
        resume=self._command('resume',batch_id,budget=True)
        loop=(' Call it again and again until the status is completed or stopped, and call it again after any non-zero exit: '
              'each call drives for at most --max-seconds and nothing advances between calls.')
        driving=detail.get('state')=='running'
        busy=''
        if driving:
            call=detail.get('call') or {}
            busy=('A '+str(call.get('command') or prefix+'-resume')+' call (pid '+str(call.get('pid'))+') is driving this run now; '
                  'do not start a second one. ')
        if status=='prepared':
            return ('Not started yet. Start with: '+self._command('start',batch_id,budget=True)+'. Then resume with: '+resume+'.'+loop)
        if status=='reconcile_required':
            return (busy+('GOAT could not confirm how a %s started, so this run does not advance. Settle it with: '%noun)
                    +self._command('reconcile',batch_id)+'. It keeps a '+noun+'\'s own verified output and never re-runs one.')
        if status=='completed':
            return 'Completed; nothing is pending and no driver is needed. Read the results with: '+self._command('report',batch_id)+'.'
        if status=='stopped':
            if not pending:
                return 'Stopped; no '+noun+' is pending, so there is nothing to resume. Read the results with: '+self._command('report',batch_id)+'.'
            if self.resumable(state):
                return ((busy+'When it returns, resume with: ' if driving else 'Stopped with '+count(pending)+' pending and no driver running. Resume with: ')
                        +resume+' (it re-activates the pending '+noun+'s under the start-grade checks; completed and failed '+noun+'s never re-run).'+loop)
            reason=(state.get('stopped_reason') or {}).get('plain')
            return ('Stopped with '+count(pending)+' pending. '+(reason+' ' if isinstance(reason,str) else '')
                    +'When that names '+prefix+'-resume, resume with: '+resume+'.')
        # active or closing_monitor
        if self.paused(batch_id) and not driving:
            return ('Paused between '+noun+'s at your request; '+count(pending)+' pending. batch-resume releases the pause and continues '
                    'the pending '+noun+'s.')
        if driving:
            return busy+'When it returns, call '+resume+' again if the status is not completed or stopped.'+loop
        running=(' '+str(live.get('alias'))+' is still running in MT5, but nothing collects it or starts the next '+noun+' until a call drives.'
                 if live else '')
        if detail.get('state')=='unknown':
            return ('Driver unknown: '+str(detail.get('basis'))+' '+count(pending)+' pending.'+running+' If no '+prefix+'-start or '+prefix
                    +'-resume call of yours is still running, resume with: '+resume+'. Otherwise check '+self._command('status',batch_id)+' again.')
        return ('Not advancing: '+count(pending)+' pending and no driver running (no '+prefix+'-start or '+prefix+'-resume call is in progress).'
                +running+' Resume with: '+resume+'.'+loop)

    # A seed pause is a between-members stop: the running member finishes and is
    # kept, pending members stay pending (never cancelled), so resume continues
    # the same original attempt. The marker is the only effect; like STOP it needs
    # no terminal lock, and a live driver honours it before its next launch.
    def pause_path(self,batch_id):return self.path(batch_id)/'pause.json'

    def paused(self,batch_id):return self.pause_path(batch_id).is_file()

    def cancel_request_path(self,batch_id):return self.path(batch_id)/'cancel-request.json'

    def request_cancel(self,batch_id,*,now):
        """Cancel while a driver holds the terminal lease (goatai#2350, Claude-Mac 6099078698 R2): never a refusal for
        the user. The request is recorded; the driver honours it at its next safe point (after the current test, between
        members, exactly where it honours a pause) by cancelling the remaining members."""
        root,manifest,state=self._read(batch_id)
        if state['status'] in ('completed','stopped'):return self._public(root,state)
        path=self.cancel_request_path(batch_id)
        if not path.exists():
            write_json(path,dict(schema_version=1,batch_id=batch_id,manifest_sha256=state['manifest_sha256'],requested_unix=now))
        return self._public(root,state)|dict(cancel_requested=True,
            plain='Cancel requested: the run stops after the current test.',
            next_action=self.COMMAND_PREFIX+'-status shows it stop; nothing else is needed')

    def request_pause(self,batch_id,*,now):
        root,manifest,state=self._read(batch_id)
        if state['status']=='reconcile_required':
            raise ValueError('Seed hunt '+batch_id+' is not running (GOAT could not confirm how a member started), so there is '
                             'nothing to pause; settle it with seed-reconcile --batch-id '+batch_id)
        if state['status'] not in ('active','closing_monitor'):
            raise ValueError('Seed hunt '+batch_id+' is '+str(state['status'])+', not running, so there is nothing to pause')
        path=self.pause_path(batch_id)
        if not path.exists():
            write_json(path,dict(schema_version=1,batch_id=batch_id,manifest_sha256=state['manifest_sha256'],requested_unix=now))
        return self._public(root,state|dict(pause_requested=True))

    NEWS_NOUN={'seed':'Seed hunt ','catchup':'Catch-up ','holdup':'Hold-up test '}

    def _news_what(self,batch_id):
        return self.NEWS_NOUN.get(self.COMMAND_PREFIX,'Run ')+batch_id

    def accept_news_change(self,batch_id):
        """--accept-news-change (studio_news_guard): record a changed or unrecorded news file as a new news lineage.

        Persisted in state.json before any resume effect, so a detached driver continues on the accepted file;
        a later change refuses again. A news-off run, or the same file, records nothing."""
        from studio_news_guard import runner_accept
        with self._gate():
            root,manifest,state=self._read(batch_id)
            pending=next((m['alias'] for m in state['members'] if m['status']=='pending'),None)
            change=runner_accept(self.c.install,state,manifest,now=self.clock(),first_alias=pending)
            if change is not None:self._save(root,state)
        return change

    def release_pause(self,batch_id,*,now):
        path=self.pause_path(batch_id)
        if not path.exists():return False
        # News-file guard: a news-on run continues only on the file it recorded (or an accepted change).
        from studio_news_guard import runner_check
        _,manifest,state=self._read(batch_id)
        runner_check(self.c.install,state,manifest,what=self._news_what(batch_id),legacy_refuses=True)
        # Retain the pause evidence beside the seed state; never delete it.
        target=path.with_name('pause-released-'+str(int(now*1000))+'.json')
        path.replace(target)
        return True

    def _activate(self,batch_id,root,manifest,state,*,reactivate=False):
        """First start of a prepared batch, or (``reactivate``) seed-resume of a stopped batch with pending members.

        Both take the same fresh proof before the monitor closes: agent grant, idle loaded monitor, the running
        selected terminal, a free terminal slot and the one-namespace preflight. A re-activation checks only the
        pending members for stray output and records itself in ``reactivations``; nothing ended is re-run.
        """
        from studio_news_guard import runner_check,runner_record_start
        if reactivate:
            # News-file guard: a stopped news-on run resumes only on its recorded file (or an accepted change).
            runner_check(self.c.install,state,manifest,what=self._news_what(batch_id),legacy_refuses=True)
        owner=self._owner()
        observation,_=self.c.runtime(require_idle=True,expected_batch_ongoing=False)
        if observation.get('loaded') is not True or observation.get('owner')!='agent' or observation.get('generation')!=owner['generation']:
            raise ValueError('Fresh loaded licensed Studio dialog and matching human grant required')
        current=self.process.inspect()
        if current is None:
            raise ValueError(('Resuming a stopped %s batch' if reactivate else 'First %s start')%self.COMMAND_PREFIX
                             +' requires chosen running demo terminal and loaded licensed Studio')
        slot=read_json(self.slot) if reactivate and self.slot.exists() else {}
        if not (slot.get('batch_id')==batch_id and slot.get('manifest_sha256')==state['manifest_sha256']):
            guard_active_seed(self.c.root)      # a stopped batch may still hold its own slot; any other holder refuses
        # INV-BATCH-01: the running EA and every other live terminal keep their own batch folders.
        controller_preflight(self.c,observation)
        for spec,item in zip(manifest['members'],state['members']):
            if (not reactivate or item['status']=='pending') and self._outputs(spec):
                raise ValueError('Seed output identity already exists before first attempt')
        if reactivate:
            state.setdefault('reactivations',[]).append(dict(unix=self.clock(),prior_generation=state.get('generation'),
                generation=owner['generation'],prior_stopped_reason=state.pop('stopped_reason',None),
                prior_initial_process=state.get('initial_process'),process=current,
                pending=sum(m['status']=='pending' for m in state['members'])))
            state.pop('failed_members',None);state.pop('idle_settled',None)
        state['generation']=owner['generation'];state['status']='closing_monitor';state['preflight']=observation;state['initial_process']=current
        if not reactivate:runner_record_start(self.c.install,state,manifest,now=self.clock())   # the news file this run starts on
        self._save(root,state)
        write_json(self.slot,dict(status='active',batch_id=batch_id,manifest_sha256=state['manifest_sha256'],generation=state['generation']))
        self.process.close(current)

    def _research_guard(self,batch_id):
        """Two publisher budget breaches during this member (the owner research-launch guard,
        studio_research_launch) pause the lane between members. Never raises; test doubles skip."""
        from studio_seed_process import ResearchLaunch
        if not isinstance(self.process,ResearchLaunch):return False
        from studio_research_launch import pause_wanted
        if not pause_wanted(self.c) or self.paused(batch_id):return False
        try:self.request_pause(batch_id,now=self.clock())
        except ValueError:return False
        return True

    # The runner's gate waits as long as a sharing retry (40 x 25 ms) for another GOAT operation, e.g. a concurrent
    # seed-status pass, to release it (goatai#1885: a seed driver and two status calls collided on WinError 32).
    GATE_WAIT_SECONDS=1

    def _gate(self):return exclusive_gate(self.gate,wait_seconds=self.GATE_WAIT_SECONDS)

    def _status_or_busy(self,batch_id,**extra):
        """The driver's closing status read. A gate still busy after the wait is reported, never raised, so a driver
        that did its job is not recorded as failed because a status reader held the gate at that moment."""
        try:return self.status(batch_id)|extra
        except GateBusy as busy:
            return dict(batch_id=batch_id,status='status_busy',gate_busy=str(busy),**extra)

    HOLD_POLL_SECONDS=.25

    def _switch_hold(self,root,state,item):
        """None to start this member now, else the wall time its switch hold ends (studio_switch_hold).

        Off (None) never holds. The hold is retained in the state so it stays bounded across the
        demo lane's short drive slices; each hold and release is journaled with its reason and the
        released one (waited_ms, reason, source) is kept on the member.
        """
        if self.switch_hold is None:return None
        from studio_switch_hold import decide
        result=decide(self.switch_hold,state.get('switch_hold'),member_id=item['member_id'],now=self.clock())
        event=result['journal']
        if event is not None and self.locked_journal is not None:
            try:self.locked_journal(event[0],event[1])
            except Exception:pass   # throughput-only telemetry never blocks a start
        if result['start']:
            state.pop('switch_hold',None)
            if event is not None:item['switch_hold']=event[1]
            return None
        if result['hold']!=state.get('switch_hold'):
            state['switch_hold']=result['hold'];self._save(root,state)
        return result['hold']['deadline_unix']

    def _hold_wait(self,batch_id,seconds):
        """Wait out part of a switch hold. A stop ('stop'), a pause request ('pause') or any state change such as
        a cancel ('state_changed') ends it at once; the caller's next pass applies them before any start."""
        state_file=self.path(batch_id)/'state.json'
        def mark():
            try:stat=state_file.stat()
            except OSError:return None
            return stat.st_mtime_ns,stat.st_size
        before=mark();end=self.clock()+seconds
        while True:
            if self.stop_requested is not None:
                try:
                    if self.stop_requested():return 'stop'
                except Exception:
                    return 'stop'   # an unreadable stop check never extends a hold
            if self.paused(batch_id):return 'pause'
            if mark()!=before:return 'state_changed'
            remaining=end-self.clock()
            if remaining<=0:return None
            self.sleep(min(self.HOLD_POLL_SECONDS,remaining))

    def start(self,batch_id,max_seconds=60):return self._drive(batch_id,max_seconds,initial=True)
    def resume(self,batch_id,max_seconds=60,*,reactivate=True):
        """Continue the retained attempt. ``reactivate`` lets a batch stopped by failed members restart under the
        first-start checks; a caller whose own scope is not start-grade (the demo lane's ordinary resume) passes
        False, so a batch that became resumable meanwhile is returned stopped, never re-activated there."""
        return self._drive(batch_id,max_seconds,initial=False,reactivate=reactivate)

    def _drive(self,batch_id,max_seconds,initial,reactivate=False):
        if type(max_seconds) is not int or not 1<=max_seconds<=3600:raise ValueError('max_seconds must be 1..3600')
        # This call records itself in the run folder (studio_seed_driver) at its first gate pass and its return
        # here, so seed-status can say whether a call is driving the run now (support 64f1c5ae).
        call={}
        from studio_terminal_lease import terminal_lease
        # The installation's terminal lease for the whole drive: every member closes and relaunches MT5, so no reader may
        # attach meanwhile (goatai#2350 6098964146). goat_studio and the demo agent already hold it: joined here.
        try:
            with terminal_lease(self.c.root,purpose=self.COMMAND_PREFIX+'-drive '+batch_id):
                result=self._drive_passes(batch_id,max_seconds,initial,reactivate,call)
        except BaseException as exc:
            self._driver_end(call,'failed',error=str(exc) or type(exc).__name__)
            raise
        self._driver_end(call,'returned',result_status=result.get('status') if isinstance(result,dict) else None)
        return result

    def _driver_end(self,call,outcome,**details):
        """Record this call's return. Never raises: a record that stays open is read from its PID (gone = none)."""
        if not call.get('token'):return
        from studio_seed_driver import end
        try:
            with self._gate():end(call['root'],call['token'],now=self.clock(),outcome=outcome,**details)
        except Exception:
            pass

    def _drive_passes(self,batch_id,max_seconds,initial,reactivate,call):
        deadline=self.clock()+max_seconds
        while self.clock()<deadline:
            self.c.bridge.pump()
            holding=None;cancel_now=False
            held=ExitStack()
            try:held.enter_context(self._gate())
            except GateBusy:
                # Another GOAT operation still holds the gate after the bounded wait: skip this pass, never fail the
                # driver on it. Nothing was read or changed; the next pass re-checks everything.
                if self.clock()<deadline:self.sleep(min(1,deadline-self.clock()))
                continue
            with held:
                root,manifest,state=self._read(batch_id)
                if self.driver_record and 'token' not in call:
                    from studio_seed_driver import begin
                    call['root']=root
                    call['token']=begin(root,command=self.COMMAND_PREFIX+('-start' if initial else '-resume'),max_seconds=max_seconds,
                                        now=self.clock(),identity=self.identity(),gone=getattr(self.process,'process_gone',None))
                if state['status']=='reconcile_required':
                    # A member MT5 finished while its start was unconfirmed is collected from its own output.
                    self._observe(root,manifest,state,settle_unowned=True)
                if not initial and reactivate and self.resumable(state):
                    # seed-resume of a batch stopped by failed members: the same fresh proof as a first start,
                    # then the pending members continue. Never from a status read; never re-runs a member.
                    self._verify_prepared(batch_id,manifest)
                    from studio_heldout_guard import check_runner_start
                    check_runner_start(self.c,manifest)
                    self._activate(batch_id,root,manifest,state,reactivate=True)
                if state['status'] in ('completed','stopped','reconcile_required'):return self._public(root,state)
                if state['status']=='prepared':
                    if not initial:raise ValueError('Use seed-start for a prepared batch')
                    self._verify_prepared(batch_id,manifest)
                    # Held-out lock: a lock declared after prepare refuses the start (before the monitor closes).
                    from studio_heldout_guard import check_runner_start
                    check_runner_start(self.c,manifest)
                    self._activate(batch_id,root,manifest,state)
                self._owner(state['generation']);self._slot(batch_id,state)
                current=self._observe(root,manifest,state,settle_unowned=True)
                if state['status'] in ('completed','stopped','reconcile_required'):return self._public(root,state)
                if state['status']=='closing_monitor':
                    if current is not None and current!=state['initial_process']:raise ValueError('Monitor process changed during normal close')
                    if current is None:state['status']='active';self._save(root,state)
                running=next((m for m in state['members'] if m['status'] in ('running','cancel_requested','timeout_requested')),None)
                if running and running['status']=='running':self._research_guard(batch_id)
                if running:
                    if running['status']=='running' and self.clock()-running['started_unix']>=manifest['plan']['job_timeout_seconds']:
                        running['status']='timeout_requested';self._save(root,state)
                        self.process.close(running['process'])
                elif current is None and state['status']=='active' and self.cancel_request_path(batch_id).is_file():
                    cancel_now=True                  # a cancel request: honoured below, after the gate is released
                elif current is None and state['status']=='active' and self.paused(batch_id):
                    return self._public(root,state)|dict(paused=True,pause_requested=True,
                        next_action='Paused between members; batch-resume releases the pause and continues the pending members')
                elif current is None and state['status']=='active' and self.clock()<deadline:
                    index=next((i for i,m in enumerate(state['members']) if m['status']=='pending'),None)
                    if index is not None:
                        item=state['members'][index];spec=manifest['members'][index]
                        if item['attempts']!=0:raise ValueError('Seed retry forbidden')
                        if self._outputs(spec):raise ValueError('Output already exists for unstarted seed member')
                        self._owner(state['generation'])
                        self._verify_prepared(batch_id,manifest)
                        # Each member is its own MT5 launch: re-check the lock before it (nothing is sent on refusal).
                        from studio_heldout_guard import check_runner_start
                        check_runner_start(self.c,manifest,spec)
                        # News-file guard: a recorded news-on run never launches a member on another news file.
                        from studio_news_guard import runner_check,runner_tag
                        runner_check(self.c.install,state,manifest,what=self._news_what(batch_id),legacy_refuses=False)
                        holding=self._switch_hold(root,state,item)
                        if holding is None:
                            self._before_start(spec)
                            runner_tag(self.c.install,state,item)
                            item.update(status='starting',attempts=1,started_unix=self.clock());self._save(root,state)
                            try:
                                identity=self.process.start(spec['config_path'])
                                item.update(status='running',process=identity);self._save(root,state)
                            except ResearchLaunchRefused as exc:
                                # Nothing ran (the suspended MT5 was terminated before it ran, or never created):
                                # the member stays pending and the batch active; the plain refusal is raised.
                                item.update(status='pending',attempts=0,launch_refused=str(exc)[:500]);item.pop('started_unix',None)
                                self._save(root,state);raise
                            except BaseException as exc:
                                item.update(status='reconcile_required',error=str(exc));state['status']='reconcile_required';self._save(root,state);raise
            if cancel_now:
                # Between members (the current test finished): the remaining members are cancelled by the same cancel the
                # command runs, and the request is kept beside the batch as the record of who stopped it.
                result=self.cancel(batch_id)
                path=self.cancel_request_path(batch_id)
                if path.is_file():path.replace(path.with_name('cancel-request.honoured.json'))
                return result|dict(cancel_request_honoured=True)
            if holding is not None:
                # Outside the gate, so status, cancel and pause are never blocked; each pass re-checks everything.
                if self._hold_wait(batch_id,max(0,min(1,deadline-self.clock(),holding-self.clock())))=='stop':
                    return self._status_or_busy(batch_id,switch_hold_interrupted='stop')
                continue
            if self.clock()<deadline:self.sleep(min(1,deadline-self.clock()))
        return self._status_or_busy(batch_id,driver_budget_exhausted=True,next_action='seed-resume continues the retained attempt; no retry')

    def cancel(self,batch_id):
        self.c.bridge.pump()
        with self._gate():
            root,manifest,state=self._read(batch_id)
            if state['status'] in ('completed','stopped'):return self._public(root,state)
            self._owner(state['generation'])
            if state['status']!='prepared':self._slot(batch_id,state)
            if state['status']=='prepared':
                for item in state['members']:item['status']='cancelled'
                state['status']='stopped';self._save(root,state)
                return self._public(root,state)|dict(stop_verified=True,native_started=False)
            current=self._observe(root,manifest,state)
            if state['status'] in ('completed','stopped'):
                return self._public(root,state)|dict(stop_verified=True,settled='reconciled_from_output')
            if state['status']=='reconcile_required':
                # Same settle as seed-reconcile first: a member's own verified output is kept, never discarded.
                reasons=self._reconcile(root,manifest,state,current)
                if state['status'] in ('completed','stopped'):
                    self._settle_slot(root,manifest,state,current)
                    return self._public(root,state)|dict(stop_verified=True,settled='reconciled_from_output',close_sent=False)
                settled=self._settle_idle(root,manifest,state,current)
                if settled is not None:return settled
                self._save(root,state)
                if self._idle_proof(manifest,state,current) is None and reasons:
                    raise ValueError('A member wrote output that could not be settled ('+reasons[0]+'); nothing was cancelled. '
                                     'Inspect it, then run '+self.COMMAND_PREFIX+'-reconcile again.')
                raise ValueError('Uncertain process provenance requires human inspection; no close sent')
            for item in state['members']:
                if item['status']=='pending':item['status']='cancelled'
                elif item['status']=='running':item['status']='cancel_requested'
            if current and state['status']=='closing_monitor' and current!=state['initial_process']:raise ValueError('Monitor process changed')
            self._save(root,state)
            if current:
                self.process.close(current)
            else:self._observe(root,manifest,state)
            return self._public(root,state)|dict(stop_verified=current is None)

    def reconcile(self,batch_id):
        """seed-reconcile: settle reconcile_required members from their own output once MT5 is proven idle.

        Takes the process inventory NOW. Each settled member passes the same checks as a normal
        completion; anything unproven stays reconcile_required with its reason. Sends no close or
        launch, never re-runs a member and never writes a result it did not collect.
        """
        self.c.bridge.pump()
        with self._gate():
            root,manifest,state=self._read(batch_id)
            if state['status']=='prepared':raise ValueError('Seed batch '+batch_id+' never started; nothing to reconcile')
            self._owner(state['generation'])
            current=self._observe(root,manifest,state,settle_unowned=True)
            reasons=self._reconcile(root,manifest,state,current,settle_unowned=True) if state['status']=='reconcile_required' else []
            self._settle_slot(root,manifest,state,current)
        settled=not any(item['status']=='reconcile_required' for item in state['members'])
        result=self._public(root,state)|dict(settled=settled,close_sent=False,launch_sent=False)
        adopted=[m['alias'] for m in state['members'] if m['status']=='running' and m.get('reidentified')]
        if adopted and state['status']=='active':
            result['next_action']=('The selected MT5 is this batch\'s own launch of '+adopted[0]+' (re-identified by its own INI and '
                                   'creation time; nothing was closed or re-run). '+self.COMMAND_PREFIX+'-resume drives it: the '
                                   +self.MEMBER_NOUN+' is collected when MT5 finishes, then the pending '+self.MEMBER_NOUN+'s continue.')
        elif (state.get('stopped_reason') or {}).get('rules')==['unowned_settled'] and state['status']=='stopped':
            result['next_action']=state['stopped_reason']['plain']
        elif state.get('error')==UNOWNED_BETWEEN_MEMBERS and self.locked_journal is not None:
            result['next_action']=('An MT5 of this terminal ran between members that this batch did not start (a person, or demo '
                                   'launch-terminal). Close it; with MT5 closed, '+self.COMMAND_PREFIX+'-resume settles this as a '
                                   'stop, then re-activates the pending members under the start-grade check. The driver owns the '
                                   'MT5 reopen during a batch.')
        elif settled and state['status']=='reconcile_required':
            # The lane's own commands (catchup-/holdup-/seed-): seed-cancel never finds a catch-up or hold-up batch.
            result['next_action']=('Every uncertain member is settled; pending members remain while MT5 is open. Run '+self.COMMAND_PREFIX+'-cancel to stop '
                                   'them (completed results are kept), or close MT5 and run '+self.COMMAND_PREFIX+'-resume to continue them.')
        elif not settled:
            result['reasons']=reasons or [state.get('error') or 'No reconcile_required member can be settled from its own output']
            result['next_action']=('MT5 must be idle on the GOAT monitor (or closed) and the member must have written its own output. '
                                   'With no output, '+self.COMMAND_PREFIX+'-cancel settles the batch once MT5 is idle.')
            refused=[m['reidentify']['reason'] for m in state['members']
                     if m['status']=='reconcile_required' and (m.get('reidentify') or {}).get('reason')]
            if refused:result['reidentify_reason']=refused[0]      # why the open MT5 is not adopted as this launch
        return result

    def _settle_slot(self,root,manifest,state,current):
        """Persist a settled state and release the terminal slot it held (closed or idle-settled MT5 only)."""
        self._save(root,state)
        released=current is None or (state.get('idle_settled') or {}).get('process')==current
        if state['status'] in ('completed','stopped') and released and self.slot.exists():
            slot=read_json(self.slot)
            if slot.get('batch_id')==manifest['batch_id'] and slot.get('manifest_sha256')==state['manifest_sha256']:
                write_json(self.slot,slot|{'status':'released'})

    def _settle_idle(self,root,manifest,state,current):
        """seed-cancel of a reconcile_required batch while the selected MT5 is idle.

        Re-inspected NOW (``current`` is the fresh inventory, never an earlier refusal): when no
        member is live and MT5 is closed or provably runs only the idle monitor, nothing of this
        batch can still be consumed or written. Members with any output of their own are left to
        seed-reconcile; members with none are cancelled (never re-run, no evidence invented), pending
        members are cancelled, the batch is stopped and the terminal slot released. No close or
        launch is sent. Returns None when that proof is missing.
        """
        if self._idle_proof(manifest,state,current) is not None:return None
        for spec,item in zip(manifest['members'],state['members']):
            # Any output of an unsettled member means a person (or seed-reconcile) decides; never discard evidence.
            if item['status']=='reconcile_required' and self._outputs(spec):return None
        now=self.clock()
        for item in state['members']:
            if item['status']=='reconcile_required':
                item['reconciled']=dict(from_status='reconcile_required',prior_error=item.get('error'),reconciled_unix=now,
                                        basis='seed-cancel with MT5 idle (re-inspected now) and no output from this member',process=current)
                item['status']='cancelled';item['finished_unix']=now
            elif item['status']=='pending':item['status']='cancelled'
        state['settled']=dict(by='seed-cancel',prior_error=state.get('error'),process=current,unix=now)
        state['error']=None;state['status']='stopped';state['idle_settled']=dict(process=current,unix=now)
        self._settle_slot(root,manifest,state,current)
        return self._public(root,state)|dict(stop_verified=True,settled='idle_terminal',close_sent=False)

    def report(self,batch_id):
        self.status(batch_id);root,manifest,state=self._read(batch_id);rows=[]
        for spec,item in zip(manifest['members'],state['members']):
            result=None
            if item.get('result'):
                saved=item['result']
                if digest(saved['path'])!=saved['sha256'] or digest(saved['xml_path'])!=saved['xml_sha256']:raise ValueError('Retained seed result changed')
                result=read_seed_json(saved['path'],MAX_RESULT_BYTES)
            observed=item.get('observed_xml')
            if result is None and observed is None and item['status'] in TERMINAL:
                # Older state (or a member that ended without collection): show any XML on disk.
                paths=self._outputs(spec)
                if len(paths)==1:observed=self._observed_xml(paths[0])
            rows.append(dict(member_id=spec['member_id'],alias=spec['alias'],symbol=spec['tester']['Symbol'],tester=spec['tester'],source_path=spec['source_path'],source_sha256=spec['source_sha256'],frozen_set_sha256=spec['set_sha256'],config_sha256=spec['config_sha256'],status=item['status'],requested_frames=spec['frame_target'],actual_frames=result['summary']['actual_frames'] if result else None,summary=result['summary'] if result else None,
                result_path=item['result']['path'] if result else None,result_sha256=item['result']['sha256'] if result else None,
                xml_path=item['result']['xml_path'] if result else None,xml_sha256=item['result']['xml_sha256'] if result else None,
                error=item.get('error'),observed_xml=observed))
        value=dict(schema_version=1,batch_id=batch_id,status=state['status'],members=rows,cutoff=manifest['plan']['cutoff'],
            missing_output_is_zero=False,scope='Seed search only; freeze exact candidates for independent validation before portfolios',native_launch_qualified=False)
        write_json(root/'report.json',value)
        if len(rows)>MAX_PUBLIC_MEMBERS:
            return dict(schema_version=1,batch_id=batch_id,status=state['status'],member_count=len(rows),report_path=str(root/'report.json'),
                report_sha256=digest(root/'report.json'),members_omitted=True,native_launch_qualified=False)
        return value|dict(report_path=str(root/'report.json'),report_sha256=digest(root/'report.json'))
