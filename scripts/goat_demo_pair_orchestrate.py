"""Bounded R5 deployment orchestration. Never registers, trades or enables Algo."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from goat_demo_pair_connection import BUILD_ID, PAIR_ACCOUNTS, WindowsHost, verify_files
from goat_demo_pair_guard import checked_witness, lifecycle_lock, assert_new_pair_paths
import goat_demo_pair_readiness as paired
PINS = {}


class Stop(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Stop(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def bounded(path, cap=131072):
    require(not path.is_symlink(), 'aliased_evidence')
    with path.open('rb') as handle:
        raw = handle.read(cap+1)
    require(0 < len(raw) <= cap, 'evidence_size')
    return raw


def write_new(path, value):
    with path.open('xb') as handle:
        handle.write(encoded(value)+b'\n');handle.flush();os.fsync(handle.fileno())


class Journal:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory/'journal.jsonl'
        self.records = []
        if self.path.exists():
            raw = bounded(self.path, 8*1024*1024)
            require(raw.endswith(b'\n'), 'incomplete_journal')
            for line in raw.splitlines():
                record = json.loads(line)
                require(record['sequence'] == len(self.records) and record['previous'] == self.tail(), 'journal_chain')
                self.records.append(record)

    def tail(self):
        return sha(encoded(self.records[-1])) if self.records else '0'*64

    def add(self, kind, **data):
        require(len(self.records) < 4096, 'journal_limit')
        record = dict(sequence=len(self.records), previous=self.tail(), kind=kind, atUtc=int(time.time()), **data)
        with self.path.open('ab') as handle:
            handle.write(encoded(record)+b'\n');handle.flush();os.fsync(handle.fileno())
        self.records.append(record)

    def tried(self, target):
        return any(r['kind'] == 'intent' and r.get('target') == target for r in self.records)


def identities(value):
    return [(row['chartId'], row['magic']) for row in value['rows']]


def count_attached(value):
    found_gap, count = False, 0
    for row in value['rows']:
        chart, magic = row['chartId'], row['magic']
        require((chart > 0) == (magic > 0), 'partial_child_identity')
        if chart > 0:
            require(not found_gap, 'nonsequential_deployment')
            count += 1
        else:
            found_gap = True
    positive = identities(value)[:count]
    require(len({pair[0] for pair in positive}) == count and len({pair[1] for pair in positive}) == count, 'duplicate_child_identity')
    return count


class Runner:
    def __init__(self, api, registration, journal, resumed=False, clock=time.monotonic, sleep=time.sleep, recovery=None):
        self.api, self.reg, self.journal = api, registration, journal
        self.resumed, self.clock, self.sleep = resumed, clock, sleep
        self.deadline = clock()+3600
        self.calls = 0
        self.recovery = recovery

    def deployment_target(self,count,value):
        target=f'deploy:{count}'
        if count==6 and self.recovery is not None:
            require([list(v) for v in identities(value)[:6]]==self.recovery['prefix'],'recovery_prefix_changed')
            require(count_attached(value)==6 and self.journal.tried(target),'recovery_not_original_failure')
            return self.recovery['target']
        return target

    def call(self, action, target=None):
        require(self.clock() < self.deadline and self.calls < 1024, 'overall_bound')
        if target is not None:
            require(not self.journal.tried(target), 'mutation_already_attempted')
            self.journal.add('intent', action=action, target=target)
        else:
            self.journal.add('read_intent', action=action)
        self.calls += 1
        value = self.api.request(action)
        # Preserve native receipt before interpreting a failure. Adapter refuses
        # malformed receipts, which remain in the native mailbox for inspection.
        name = f'receipt-{len(self.journal.records):04d}.json'
        write_new(self.journal.directory/name, value)
        rows=value.get('rows',[])
        self.journal.add('receipt', action=action, file=name, sha256=sha(encoded(value)+b'\n'), result=value.get('result'),
                         attached=sum(r['chartId']>0 and r['magic']>0 for r in rows),
                         linked=sum(r['linkedFresh'] and r['chartId']>0 and r['magic']>0 for r in rows))
        require(value.get('result') in self.api.successes[action], 'native_command_failed')
        require(value['connected'] and not value['tradingAllowed'] and value['positions'] == 0 and value['orders'] == 0,
                'terminal_not_inert')
        require(0 <= time.time()-value['observedAtUtc'] <= (120 if action=='audit' else 30), 'stale_native_observation')
        return value

    def wait(self, value, predicate, reason):
        end = min(self.deadline, self.clock()+90)
        while not predicate(value):
            require(self.clock() < end, reason)
            self.sleep(2)
            value = self.call('status')
        return value

    def policy_matches(self, value):
        return all(value[key] == self.reg[key] for key in ('aiMode','aiThreshold','aiProtocol'))

    def run(self, inspected=None):
        value = self.call('status')
        if inspected is not None:
            require(identities(value) == identities(inspected) and self.policy_matches(value)
                    == self.policy_matches(inspected) and value['commandId'] == inspected['commandId'], 'inspection_state_changed')
        count = count_attached(value)
        require(self.resumed or count == 0, 'preexisting_deployment_requires_inspection')
        if count == 0 and not self.journal.tried('configure'):
            value = self.call('configure', 'configure')
        require(self.policy_matches(value), 'configuration_unverified_no_retry')
        require(not value['commandPending'] or (count == len(self.reg['members']) and self.journal.tried('apply_policy')),
                'preexisting_command_pending')
        while count < len(self.reg['members']):
            # All existing children must still be linked before one more launch.
            value = self.wait(value, lambda v: count_attached(v) == count and all(r['linkedFresh'] for r in v['rows'][:count]), 'prior_child_link_timeout')
            before = identities(value)
            value = self.call('deploy_next', self.deployment_target(count,value))
            require(value['result'] == 'child_attached' and count_attached(value) == count+1,
                    'unexpected_deploy_count')
            require(identities(value)[:count] == before[:count], 'existing_child_changed')
            new_identity = identities(value)
            value = self.wait(value, lambda v: identities(v) == new_identity and all(r['linkedFresh'] for r in v['rows'][:count+1]), 'new_child_link_timeout')
            count += 1
        value = self.wait(value, lambda v: count_attached(v) == count and all(r['linkedFresh'] for r in v['rows']), 'all_child_link_timeout')
        policy_identities=identities(value)
        if not self.journal.tried('apply_policy'):
            value = self.call('apply_policy', 'apply_policy')
        expected_id = 0
        for record in reversed(self.journal.records):
            if record['kind']=='receipt' and record['action']=='apply_policy' and record['result']=='policy_dispatched':
                raw=bounded(self.journal.directory/record['file'])
                require(sha(raw)==record['sha256'],'policy_receipt_changed')
                expected_id=json.loads(raw)['commandId'];break
        require(expected_id > 0, 'policy_command_unknown')
        def ack(v):
            require(identities(v)==policy_identities,'policy_child_identity_changed')
            require(v['commandId'] == expected_id, 'policy_command_replaced')
            for row in v['rows']:
                if row['ackId'] == expected_id:
                    require(row['ackStatus'] in (0, 1), 'policy_ack_rejected')
            return not v['commandPending'] and all(r['linkedFresh'] and r['ackId'] == expected_id
                and r['ackStatus'] == 1 and r['exposureMode'] == self.reg['exposureMode'] for r in v['rows'])
        value = self.wait(value, ack, 'policy_ack_timeout')
        audit = self.call('audit')
        require(identities(audit) == identities(value) and audit['commandId'] == expected_id, 'audit_state_changed')
        proof=paired.capture_pair(self.api.module,self.api.manifest,
             self.api.root/(audit['id']+'.json'),self.journal.directory/'paired-readiness',self.api.host)
        self.journal.add('paired_proof',path=str(proof),sha256=sha(bounded(proof)))
        self.journal.add('ready', members=count, linked=count, ready=True)
        return {'members':count, 'linked':count, 'ready':True}


class NativeAPI:
    def __init__(self, module, manifest, draft, terminal):
        self.module, self.manifest = module, manifest
        self.installation, self.root = module.context(manifest)
        require(manifest.name == f'terminal-{terminal:02d}.json', 'manifest_name')
        require(terminal in PAIR_ACCOUNTS and self.installation['account'] == PAIR_ACCOUNTS[terminal]
                and self.installation['server'] == 'Darwinex-Demo'
                and self.installation['buildId'] == BUILD_ID, 'fixed_terminal_binding')
        self.host=WindowsHost()
        self.reg, self.digest = module.read_bounded(self.root/'registration.json')
        module.validate_registration(self.reg, self.installation)
        reviewed, _ = module.read_bounded(draft)
        require({k:v for k,v in reviewed.items() if k!='expiresAtUtc'} == {k:v for k,v in self.reg.items() if k!='expiresAtUtc'}, 'reviewed_draft_mismatch')
        require(len(self.reg['members'])==35 and self.reg['aiMode']==(0 if terminal==7 else 2)
                and self.reg['aiThreshold']==50 and self.reg['aiProtocol']==2 and self.reg['exposureMode']==0,'pair_policy')
        self.successes = module.SUCCESSES

    def request(self, action):
        _, digest = self.module.read_bounded(self.root/'registration.json')
        require(digest == self.digest, 'registration_changed')
        return self.module.request(self.manifest, action, timeout=(90 if action=='audit' else 60))

    def verify_ready(self, value, registration):
        return self.module.verify_ready(value, registration)

    def inspection(self, path, journal):
        value, _ = self.module.read_bounded(path)
        require(set(value) == {'schema','decision','journalSha256','receiptPath','receiptSha256'} and value['schema'] == 1
                and value['decision'] == 'resume_from_observed_state', 'inspection_schema')
        require(value['journalSha256'] == sha(bounded(journal.path,8*1024*1024)), 'inspection_journal_mismatch')
        receipt_path = Path(value['receiptPath'])
        receipt, digest = self.module.read_bounded(receipt_path)
        require(digest == value['receiptSha256'] and receipt_path.resolve() == (self.root/(receipt['id']+'.json')).resolve(), 'inspection_receipt_binding')
        request = {k:receipt[k] for k in ('id','action','registrationSha256')}
        self.module.verify_receipt(receipt, request, self.installation, self.reg['members'])
        require(receipt['action'] == 'status' and receipt['result'] == 'observed' and receipt['registrationSha256'] == self.digest
                and 0 <= time.time()-receipt['observedAtUtc'] <= 120, 'fresh_inspected_status_required')
        return receipt


def load_api(directory):
    require(len(PINS)==2,'api_pins_unset')
    for name, expected in PINS.items():
        require(sha(bounded(directory/name)) == expected, 'api_pin_mismatch')
    sys.path.insert(0,str(directory))
    spec=importlib.util.spec_from_file_location('goat_portfolio_setup',directory/'goat_portfolio_setup.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def claim_terminal(root, run_directory, binding):
    # Durable pointer prevents using a fresh output folder to evade old intents.
    path = root/'orchestration-owner.json'
    owner = {'schema':1,'runDirectory':str(run_directory.resolve()),'binding':binding}
    if path.exists():
        require(json.loads(bounded(path)) == owner, 'different_terminal_orchestration_owner')
    else:
        write_new(path, owner)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--draft',type=Path,required=True)
    parser.add_argument('--terminal',type=int,choices=(7,8),required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--inspection',type=Path)
    parser.add_argument('--pins',type=Path,required=True)
    parser.add_argument('--protected-witness',type=Path,required=True)
    parser.add_argument('--reconnect-manifest',type=Path,required=True)
    parser.add_argument('--recovery-proof',type=Path)
    parser.add_argument('--recovery-proof-sha256')
    args=parser.parse_args()
    global PINS
    PINS=json.loads(bounded(args.pins))
    paired.configure_pins(PINS)
    summary={'terminal':args.terminal,'ready':False,'members':0,'linked':0,'status':'needs_review'}
    journal=None;fd=None;native_fd=None;lock=None;native_lock=None
    witness=None; lifecycle=None
    try:
        from goat_demo_pair_connection import validate_manifest
        rows=validate_manifest(json.loads(bounded(args.reconnect_manifest)))
        row=next(r for r in rows if r['terminal']==args.terminal)
        host=WindowsHost(); witness=checked_witness(args.protected_witness,host)
        assert_new_pair_paths(rows,witness); verify_files(row)
        lifecycle=lifecycle_lock(witness); lifecycle.__enter__()
        args.run_dir.mkdir(parents=True,exist_ok=True)
        lock=args.run_dir/'orchestration.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        os.write(fd,str(os.getpid()).encode())
        journal=Journal(args.run_dir)
        api=NativeAPI(load_api(args.control_dir),args.manifest,args.draft,args.terminal)
        require(api.installation['directory']==row['directory'] and api.installation['eaSha256']==row['eaSha256'],'connection_installation_binding')
        native_lock=api.root/'orchestration.lock';native_fd=os.open(native_lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        os.write(native_fd,str(os.getpid()).encode())
        summary['members']=len(api.reg['members'])
        binding={'terminal':args.terminal,'registrationSha256':api.digest,'manifestSha256':sha(bounded(args.manifest))}
        claim_terminal(api.root,args.run_dir,binding)
        inspected=None
        if journal.records:
            require(args.inspection is not None and journal.records[0].get('binding') == binding, 'explicit_inspection_required')
            inspected=api.inspection(args.inspection,journal)
        else:
            require(args.inspection is None,'no_prior_journal')
            journal.add('start',binding=binding)
        recovery=None
        require(bool(args.recovery_proof)==bool(args.recovery_proof_sha256),'recovery_pin_required')
        if args.recovery_proof:
            require(args.terminal==7 and inspected is not None,'recovery_scope')
            from goat_demo_pair_recover_child import validate_authority
            recovery=validate_authority(args.recovery_proof,args.recovery_proof_sha256,journal,api)
        journal.add('attempt',resumed=inspected is not None)
        summary.update(Runner(api,api.reg,journal,inspected is not None,recovery=recovery).run(inspected))
        checked_witness(args.protected_witness,host,expected=witness)
        summary['status']='ready_for_separate_trading_check'
    except Stop as error:
        summary['reason']=str(error)
    except Exception:
        summary['reason']='operation_failed_inspect_retained_evidence'
    if journal is not None and journal.records:
        for record in reversed(journal.records):
            if record['kind']=='receipt':
                summary['linked']=record['linked'];summary['attached']=record['attached'];break
        try:journal.add('summary',summary=summary)
        except Exception:summary['ready']=False;summary['status']='evidence_write_failed'
    for descriptor,path in ((native_fd,native_lock),(fd,lock)):
        if descriptor is not None:
            try:os.close(descriptor);path.unlink()
            except Exception:summary['ready']=False;summary['status']='lock_release_requires_review'
    if lifecycle is not None:
        try:lifecycle.__exit__(None,None,None)
        except Exception:summary.update(ready=False,status='lifecycle_lock_review')
    print(json.dumps(summary))
    return 0 if summary['ready'] else 2


if __name__=='__main__':raise SystemExit(main())
