"""Bounded local inbox/outbox pump for the shared Studio draft controller.

Clients publish UTF-8 JSON with a temporary filename then rename to <request_id>.json.
Actor comes from the configured channel directory, never from request content.
Directories require a trusted local installation; this is not an OS-user security
boundary. No MT5 execution, native queue writes or service installation occurs.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import time
import math
from studio_agent import unique_object


def display_state(state):
    """UI queue summaries; complete frozen configurations remain in the store.

    This projection is deliberately unsuitable for launching jobs. A native
    adapter must retrieve and verify the immutable controller configuration.
    """
    result = dict(state)
    result['queue'] = [dict(job_id=job['job_id'], status=job['status'],
                            configuration_sha256=job['configuration_sha256'],
                            source_revision=job['source_revision'],
                            execution_ready=False,
                            configuration={'tester':{key:job['configuration']['tester'][key]
                                                     for key in ('Symbol','Period')}})
                       for job in state.get('queue', [])]
    result['queue_detail'] = 'display_summary_only'
    for summary, job in zip(result['queue'], state.get('queue', [])):
        if 'batch_members' in job['configuration']:
            summary['batch_member_count']=len(job['configuration']['batch_members'])
            summary['batch_members']=[dict(index=index,symbol=member['tester']['Symbol'],period=member['tester']['Period']) for index,member in enumerate(job['configuration']['batch_members'])]
        if 'native_observation' in job:
            native=job['native_observation'].get('native',{})
            summary['native_progress']={key:native[key] for key in ('member_count','status_counts','completed_count','finished_count','active_indices') if key in native}
        if 'restart_intent' in job:
            summary['restart_phase'] = job['restart_intent']['phase']
            for field in ('attempt_id', 'startup_sha256'):
                if field in job['restart_intent']:
                    summary['restart_'+field] = job['restart_intent'][field]
    return result


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8',newline='\n') as handle:
            json.dump(value,handle,ensure_ascii=False,allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        # MT5 readers briefly open without FILE_SHARE_DELETE on Windows.
        # Retry only publication of these same durable bytes, never a command.
        for attempt in range(6):
            try:
                os.replace(temporary,path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def worker_lock(root):
    with (root/'worker.lock').open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


class StudioBridge:
    def __init__(self,root,store,terminal_id,run_id):
        self.root=Path(root).resolve()
        self.store=store
        self.terminal_id,self.run_id=terminal_id,run_id
        store.snapshot(terminal_id,run_id)  # Existing binding only; never self-grant.
        self.root.mkdir(parents=True,exist_ok=True)
        self.binding=dict(protocol_version=1,terminal_id=terminal_id,run_id=run_id)
        # Also prevent two different databases from publishing into the same root.
        self.binding['database']=str(Path(store.db.execute('PRAGMA database_list').fetchone()[2]).resolve())

    def pump(self,limit=32):
        if type(limit) is not int or not 1<=limit<=256:
            raise ValueError('Pump limit must be 1..256')
        results=[]
        with worker_lock(self.root):
            binding_path=self.root/'binding.json'
            if binding_path.exists():
                if json.loads(binding_path.read_text(encoding='utf-8'))!=self.binding:
                    raise ValueError('Bridge root belongs to another controller binding')
            else:
                write_json(binding_path,self.binding)
            # Human requests get priority, including takeover revoking queued agent edits.
            for actor in ('human','agent'):
                folders={name:self.root/actor/name for name in ('inbox','processing','outbox','archive')}
                for path in folders.values():
                    path.mkdir(parents=True,exist_ok=True)
                    if not path.resolve().is_relative_to(self.root):
                        raise ValueError('Bridge directory escapes bound root')
                for source_name in ('processing','inbox'):
                    for incoming in sorted(folders[source_name].glob('*.json')):
                        if len(results)>=limit:break
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',incoming.stem):
                            raise ValueError('Invalid transport request filename')
                        if incoming.is_symlink() or incoming.resolve().parent!=folders[source_name].resolve():
                            raise ValueError('Request is not a regular bound inbox file')
                        processing=folders['processing']/incoming.name
                        if source_name=='inbox':
                            if processing.exists():
                                continue  # Unacknowledged older request must be recovered first.
                            incoming.rename(processing)
                        with processing.open('rb') as handle:
                            raw=handle.read(2_000_001)
                        fingerprint=hashlib.sha256(raw).hexdigest() if len(raw)<=2_000_000 else None
                        try:
                            if len(raw)>2_000_000:raise ValueError('Request exceeds size limit')
                            request=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique_object)
                            if not isinstance(request,dict) or request.get('request_id')!=processing.stem:
                                raise ValueError('Request identity/filename mismatch')
                            if request.get('terminal_id')!=self.terminal_id or request.get('run_id')!=self.run_id:
                                raise ValueError('Request belongs to another terminal/run')
                            receipt=self.store.submit(request,actor=actor)
                            # MQL acknowledges identity and committed revision, not
                            # a second full copy of every queued strategy.
                            summary = dict(receipt)
                            summary['state'] = {key:receipt['state'][key] for key in
                                ('terminal_id','run_id','revision','generation','owner')}
                            response=dict(ok=True,receipt=summary,receipt_detail='revision_only')
                        except ValueError as exc:
                            current=self.store.snapshot(self.terminal_id,self.run_id)
                            response=dict(ok=False,error=str(exc),state={key:current[key] for key in
                                ('terminal_id','run_id','revision','generation','owner')})
                        response.update(request_id=processing.stem,request_sha256=fingerprint)
                        # If publication fails after commit, keep processing for receipt replay.
                        write_json(folders['outbox']/processing.name,response)
                        archive=folders['archive']/(processing.stem+'.'+(fingerprint or uuid.uuid4().hex)+'.json')
                        os.replace(processing,archive)
                        results.append(dict(actor=actor,request_id=response['request_id'],ok=response['ok']))
            state=self.store.snapshot(self.terminal_id,self.run_id)
            write_json(self.root/'snapshot.json',dict(protocol_version=1,
                observed_at=datetime.now(timezone.utc).isoformat(),state=display_state(state),
                schema_hash=self.store.input_schema_hash,execution_ready=False))
        return results


def pump_for(bridge, seconds, interval=0.5, limit=32, *, clock=time.monotonic, wait=time.sleep):
    if not math.isfinite(seconds) or not 0 <= seconds <= 3600:
        raise ValueError('Watch duration must be 0..3600 seconds')
    if not math.isfinite(interval) or not 0.1 <= interval <= 10:
        raise ValueError('Poll interval must be 0.1..10 seconds')
    deadline=clock()+seconds
    cycles=processed=rejected=0
    while True:
        results=bridge.pump(limit)
        cycles+=1; processed+=len(results); rejected+=sum(not r['ok'] for r in results)
        remaining=deadline-clock()
        if remaining<=0:break
        wait(min(interval,remaining))
        if clock()>=deadline:break
    return dict(cycles=cycles,processed=processed,rejected=rejected,execution_ready=False)
