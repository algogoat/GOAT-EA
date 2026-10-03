"""GOAT Studio controller. Discovery is read-only; all mutations are explicit.

Use the installed receipt from GOAT Setup. Never copy another user's receipt,
account, state database or native attempt. See README.md for complete workflows.
"""
import argparse
from contextlib import ExitStack
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
    'self-repair':dict(required=['job-id','action-id','linked-login'],effect='retire an exact expired rejected never-consumed demo start/cancel using original receipt and pristine native package proof; caller verifies linked-login eligibility, tool matches it against fresh native demo account. Republish genuine projection, normally close idle selected demo, archive transport and restore owned controls, then same-EA rebind. No research relaunch, grant, permissions, human-stop reset or native-cancellation claim; returns sanitized own-ticket repair payload'),
    'same-ea-rebind':dict(required=[],effect='repair only a stopped demo session after a proven same-EA desktop receipt rewrite; requires exact preserved previous receipt and settled native attempts, retains previous session bytes and database, never launches, grants or clears a permit'),
    'monitor-stop':dict(required=['attempt-id'],effect='normal-close exact idle connected demo once for authorized upgrade; empty unstarted sessions only, no relaunch/grant/trading; retained stop refuses a replacement process'),
    'monitor-repair':dict(required=['attempt-id'],effect='within authorized setup, read native identity/demo/Algo-off/zero positions and idle tester; normal-close once, preserve and restore prepared profile and explicitly attach monitor; empty unstarted sessions only, no grant/trading/optimization'),
    'switch-verify-park':dict(required=['review-id'],effect='read-only verification of completed park, immutable archives, external databases and absent selected terminal/session; not admission or grant'),
    'switch-replace-receipt':dict(required=['review-id','candidate-receipt','expected-sha256'],effect='authenticated installer companion: atomic old-receipt CAS under exclusive session lock after verified park and unchanged physical target; preserves old receipt/research, never grants or starts; admission remains installer responsibility'),
    'switch-replace-build':dict(required=['review-id','candidate-receipt','candidate-ea','expected-sha256'],effect='authenticated installer companion: exact same-version EA and receipt exchange under exclusive parked-session and database locks; retained journal permits exact interrupted-pair reconciliation; no admission, control grant or launch'),
    'historical-pointers-prepare':dict(required=[],effect='review older settled unowned UI pointers with every MT5/controller writer stopped; preserve historical runs, queues and native flags'),
    'historical-pointers-apply':dict(required=['review-id','confirm-reviewed'],effect='archive only reviewed exact older UI pointers with durable intent and replay; no flags, grants, launches or historical result changes'),
    'bootstrap-retirement-prepare':dict(required=['specification','bootstrap-receipts'],effect='review failed legacy passive monitor startup, exact original receipts and idle replacement; no close or claim effects'),
    'bootstrap-retirement-apply':dict(required=['review-id'],effect='within authorised selected-terminal maintenance, normal-close exact reviewed idle monitor once, then retire original startup claim/slot atomically only after native process absence; retries inspect only, never resend or restart'),
    'peer-prepare':dict(required=['terminal-executable','data-root'],effect='review one existing protected peer and exact running process; never grants or manages the peer'),
    'peer-apply':dict(required=['review-id','confirm-reviewed'],authorization='Authorized caller confirms this exact review after inspection within the user-authorized setup scope; no grant or peer management authority',effect='persist protected peer outside switched session; replacement requires fresh review; unknown terminals still block'),
    'switch-plan':dict(required=[],effect='review offline session handover; optional restore-id restores a parked session; never grants or launches'),
    'switch-status':dict(required=['review-id'],effect='read retained handover progress and recovery identity'),
    'owner-maintenance-install-prepare':dict(required=['record-id'],effect='owner-internal: consume exact completed PARK into one authenticated installer input; no installation or control effect'),
    'owner-maintenance-bootstrap':dict(required=['record-id','plan'],effect='owner-internal: verify exact installed9/CAS, immutable original grant archive and stopped terminal; create pre-bound typed continuation for only the frozen plan; no human grant or trading'),
    'owner-maintenance-prepare':dict(required=[],effect='owner-internal only: mint one short-lived exact maintenance record from the original genuine grant; no stop, PARK, install, bootstrap or grant'),
    'switch-apply':dict(required=['review-id'],authorization_required_one_of=['confirm-reviewed','owner-maintenance'],authorization='Exact human confirmation, or the owner-internal one-use maintenance record with original grant/stop evidence. Never fabricated confirmation. Trusted-local coordination, not an OS-user security boundary.',effect='apply or recover the exact user-reviewed handover; preserve research and revoke prior agent control'),
    'seed-prepare':dict(required=['batch-id','plan'],effect='freeze a dedicated SeedFarming matrix; no launch'),
    'seed-start':dict(required=['batch-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='explicit bounded driver for dedicated SeedFarming; preserves active work on call timeout'),
    'seed-resume':dict(required=['batch-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='continue verified retained seed work; uncertain effects require reconciliation'),
    'seed-status':dict(required=['batch-id'],effect='observe dedicated seed campaign state and native process evidence'),
    'seed-cancel':dict(required=['batch-id'],effect='request normal close of exact owned seed process; receipt is not exit proof'),
    'seed-report':dict(required=['batch-id'],effect='report actual seed XML metrics and frozen provenance; missing evidence remains unavailable'),
    'seed-promote':dict(required=['batch-id','candidate','name'],defaults={'neighborhood':1},limits={'neighborhood':[1,5]},effect='write a fixed SET and a narrow robustness SET (local stability check around the candidate; only the forward window is out-of-sample) for one verified seed candidate; local files only, create-only'),
    'evidence-end':dict(required=[],defaults={'value':'auto','broker-clock':'ny-close'},effect='read-only: resolve the evidence end (AUTO = latest fully closed Friday on the broker NY-close clock, or an explicit closed day) and report what this EA build ends batch exports at; no file or terminal effect'),
    'evidence-scan':dict(required=['source'],repeatable=['source'],defaults={'evidence-end':'auto','include-below-threshold':False},effect='read-only: every kept export (SET + equity CSV + .goatseq) under each source with its evidence end, threshold status and behind/current/ahead/caught_up against one target; never writes or launches'),
    'evidence-versions':dict(required=[],optional=['values-sha256'],effect='read-only: catch-up evidence versions retained under controller state, linked to their original exports'),
    'catchup-validate':dict(required=['plan'],effect='non-executing preview of a catch-up plan {schema_version:1, evidence_end, sets, job_timeout_seconds[, broker_clock, assume:{ExecutionMode}, include_below_threshold]}; no file or terminal effect'),
    'catchup-prepare':dict(required=['catchup-id','plan'],effect='freeze one single-pass (Optimization=0, Model=4) re-test per behind export from its original start to the evidence end; original exports are never changed; no launch'),
    'catchup-start':dict(required=['catchup-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='explicit bounded driver: closes the selected MT5 and relaunches it once per member with the frozen /config INI (SeedRunner process discipline, shared terminal slot, native launch not yet qualified)'),
    'catchup-resume':dict(required=['catchup-id'],defaults={'max-seconds':60},limits={'max-seconds':[1,3600]},effect='continue the retained catch-up attempt; uncertain effects require reconciliation, never a retry'),
    'catchup-status':dict(required=['catchup-id'],effect='observe catch-up state and collect finished re-tests into new evidence versions'),
    'catchup-cancel':dict(required=['catchup-id'],effect='request normal close of the exact owned catch-up process; receipt is not exit proof'),
    'catchup-report':dict(required=['catchup-id'],effect='new-weeks-only verdicts (held_up/weakened/failed/too_few_trades) with their metrics and evidence version paths'),
    'prepare-batch':dict(required=['batch-id','plan'],effect='validate and freeze a full native Studio batch; no launch'),
    'batch-status':dict(required=['batch-id'],effect='reconcile whole native batch and report member progress'),
    'save-batch':dict(required=['batch-id','output'],effect='save native .goatbatch without overwriting'),
    'load-batch':dict(required=['batch-id','file'],effect='validate saved .goatbatch as a new unstarted batch on this installation'),
    'resume-batch':dict(required=['source-batch-id','batch-id'],effect='prepare remaining members under a new identity after original stop/finish; failed members require include-failed; members tested with no profitable settings only with include-no-edge'),
    'validate-set':dict(required=['set'],defaults={'require-optimization':False},effect='read-only exact schema, encoding, range and partial dependency validation; no launch'),
    'build-set':dict(required=['source','output','spec'],effect='clone real SET with narrow typed changes, unique EA_Desc, support notes and provenance; never overwrite'),
    'discover':dict(required=[],effect='read installation and schema; runtime readiness not evaluated'),
    'bootstrap':dict(required=['account-login','account-server'],effect='create human-owned local binding and monitor preset; no launch'),
    'resource-profile':dict(required=[],effect='read-only current CPU, RAM and filesystem capacity; no throughput or worker estimate'),
    'benchmark-report':dict(required=['batch-id'],effect='read-only verified completed batch and exact native timeline; never finishes, grants or launches'),
    'onboarding-status':dict(required=[],effect='read-only staged local monitor evidence and precise recovery; never grants control'),
    'monitor-prepare':dict(required=['symbol'],effect='create a separate persistent monitor profile only while terminals are stopped; no permissions or launch'),
    'monitor-launch':dict(required=['attempt-id'],effect='one retained stopped-terminal launch of prepared inert profile; saved login and Algo-off required'),
    'serve':dict(required=[],defaults={'watch-seconds':3600},limits={'watch-seconds':[0,3600]},effect='process durable draft/ownership inboxes; no native launch'),
    'state':dict(required=[],effect='process UI inbox then return full controller state'),
    'submit':dict(required=['request'],effect='apply exact agent envelope with revision and generation checks'),
    'prepare':dict(required=['job-id','set','configuration'],effect='freeze explicit settings and stage pending native package'),
    'start':dict(required=['job-id'],refused_lanes=['native_human_control'],refused_lane_route='run-batch --mt5-restart-consent (an in-place Start never makes MT5 write batch reports)',effect='explicit one-time native dispatch for first pending job; reconcile receipt'),
    'status':dict(required=['job-id'],effect='observe retained attempt; update reconciled state without retry'),
    'reconcile':dict(required=['job-id'],effect='alias of status'),
    'cancel':dict(required=['job-id'],effect='cancel pending job or publish exact owned native stop; receipt is not stop proof'),
    'clear-queue':dict(required=[],defaults={'apply':False},apply_required=['request-id','expected-revision'],effect='preview pending jobs; explicit apply removes only pending work atomically, preserving all history/packages/results; refuses unresolved native attempts, seed ownership and outstanding native controls; never resets EA flags or starts work'),
    'native-recovery-status':dict(required=[],effect='diagnose flags, native controls and running monitor capability without effects; only matched V1.49 supports reviewed orphan recovery, and foreign ownership still blocks'),
    'orphan-recovery-prepare':dict(required=[],effect='V1.49 only: freeze single-owner idle orphan-flag recovery review; no mutation to native state'),
    'orphan-recovery-apply':dict(required=['review-id'],authorization_required_one_of=['confirm-reviewed','owner-research'],authorization='Explicit user confirmation (--confirm-reviewed), or the finite reviewed owner-demo original-grant scope (--owner-research); never fabricate human confirmation',effect='publish one exact V1.49 recovery action; no launch, stop, queue or grant change; receipt/readback required'),
    'orphan-recovery-status':dict(required=['review-id'],effect='reconcile exact native receipt and fresh readback; retain fence on uncertain effects; never resend'),
    'orphan-recovery-reconcile-rejection':dict(required=['review-id'],optional=['terminal-stopped'],terminal_stopped_authorization='Explicit human confirmation only; no offline owner or typed research authority',authorization_required_one_of=['confirm-reviewed','owner-research'],authorization='Exact reviewed rejection under explicit confirmation or finite reviewed owner-demo original-grant scope; settlement is not approval for another native recovery',effect='settle only an expired supported pre-consumption rejection with no consumption and either unchanged idle orphan identity or explicitly confirmed stopped-terminal local identity; retain evidence, never retry recovery or change native flags, queue or grant'),
    'run-batch':dict(required=['job-id'],start_required=['max-seconds'],limits={'max-seconds':[1,172800]},min_free_bytes_default=5368709120,resume='Use --resume without a new budget or disk threshold; retained deadline and guard do not reset',native_human_control_start_required=['mt5-restart-consent'],mt5_restart='Customer lane: the first member starts through /config so MT5 writes its main/forward reports; the driver closes the selected MT5 normally once and reopens it with the batch startup file (MT5 also restarts itself between members). Tell the user first; pass --mt5-restart-consent only after their yes. The consent binds the running selected MT5 process and expires after 600 s; positions/orders/account are re-proved right before the close; a start that stops after arming returns recovery with where MT5 was left and the plain next step',effect='bounded owned batch driver with durable dispatch deadline and one cancel request at budget, low disk or unavailable capacity; stop must be observed, never assumed; no force kill or uncertain relaunch'),
    'retire-unactivated':dict(required=['job-id'],demo_lane='goat.exe demo retire-unactivated --batch-id <id> (broker-verified; allowed under owner STOP)',effect='settle a start refused before MT5 was touched (launch intent and reservation, restart phase absent or prepared) to cancelled after proving under the native gate: no attempt folder or controls, no gate file naming the attempt/cancel/job, any current request belongs to a settled other job, no native run or report folder, no native queue, and a fresh idle EA sample with no batch ongoing; sends nothing to MT5, never claims a native cancellation, keeps reservation/intent/journal as evidence; idempotent. continue/resume-batch then prepares every member under a new ID'),
    'batch-stop':dict(required=['job-id'],demo_lane='goat.exe demo stop --batch-id <id>',effect='one stop for any state: pending -> cancelled; reserved-not-started -> released and cancelled; start refused before MT5 was touched -> retire-unactivated; dispatched -> the EA native cancel (same queue/flag effect as the Studio STOP button), then run-batch --resume observes and finishes it; finished -> no-op. Refusals are one sentence with the next action'),
    'batch-continue':dict(required=['job-id'],optional=['new-batch-id','include-failed','include-no-edge'],demo_lane='goat.exe demo continue --batch-id <id> (also starts the bounded driver)',effect='prepare the remaining work of a finished, stopped or paused batch as a successor (default <id>-rN): never-run members first, then failures with include-failed; across an EA build change the members are re-prepared and fully verified under the current installation, with lineage and binding_changed_keys recorded; a retained never-started successor is reused, and an existing --new-batch-id is reused only when its lineage names this batch; a start refused before activation is retired first; refuses in a typed research continuation session (it authorizes only its exact frozen plan). No launch'),
    'compact-evidence':dict(required=[],optional=['apply'],effect='preview, then with --apply move the in-row native evidence history of finished jobs into verified append-only logs (native-evidence/*.history.jsonl) so every state read stays fast; refuses while a batch is active (rechecked inside the queue transaction); skips a job whose never-started retirement proof compares the whole row; archives are temp-written, fsynced, sha256-verified and atomically renamed; no native effect'),
    'compact-receipts':dict(required=[],optional=['apply'],effect='preview, then with --apply rewrite each legacy receipt that still embeds the whole queue (state.queue) to the digest form new receipts use (state.queue_digest = {sha256, job_count}); the exact original receipt bytes are first archived one file per receipt (native-evidence/receipt-archive/<request_id>.<binding12>.receipt.json: temp-written, fsynced, sha256-verified, atomically renamed, never deleted); each row is rewritten in its own transaction under the mutation gate after re-checking that no batch is active, the session authority, and that the row still equals its archive by sha256; streams one receipt at a time; journal native-evidence/receipt-compactions.jsonl; no VACUUM (the file keeps its size until a separate reviewed VACUUM); no native effect'),
    'batch-driver-status':dict(required=['job-id'],effect='read retained driver journal and current binding match; never starts, resumes or cancels work'),
    'research-monitor-restart':dict(required=['job-id'],effect='owner-only typed continuation: gracefully suspend exact old publisher and reload one idle monitor after verified pre-consumption rejection; preserves evidence and budget; no batch start'),
    'research-monitor-restart-status':dict(required=['job-id'],effect='reverify an already launched recovery monitor; never close or launch again'),
    'research-monitor-reopen-prepare':dict(required=['job-id'],effect='prepare an audited profile-pointer-only change while stopped; no launch or permission edits'),
    'research-monitor-adopt-reopen':dict(required=['job-id','human-reopened'],effect='observe an actual human-reopened exact idle demo monitor once; never launch, grant or change permissions'),
    'research-monitor-repair-derived-report':dict(required=['job-id'],effect='repair only a proven generated report baseline, with controller-owned close/reopen and unchanged permissions; never start research or grant control'),
    'research-monitor-repair-revoked-report':dict(required=['job-id'],effect='maintenance only after genuine takeover: repair derived baseline and reopen idle monitor, retaining human ownership and revoked old authority'),
    'research-retire-never-started':dict(required=['job-id'],effect='after genuine native re-grant, stop the selected idle monitor, archive and retire the exact never-consumed original attempt, restore its owned controls, and reverify one inert relaunch; no native cancellation or research start is invented'),
    'research-regrant-status':dict(required=[],effect='read-only proof of genuine takeover and current native connection readiness; never create a grant'),
    'research-monitor-restart-resume':dict(required=['job-id'],effect='reconcile an already-issued monitor close and perform only its never-issued first relaunch; no repeated close or launch'),
    'cancel-rejected-successor':dict(required=['job-id'],effect='owner-only: publish one new stop identity after exact expired unconsumed native cancel rejection and reverified monitor restart; keeps both stop receipts'),
    'batch-pause':dict(required=['job-id'],optional=['immediate','supervise-seconds'],limits={'supervise-seconds':[1,172800]},demo_lane='goat.exe demo batch-pause --batch-id <id> (broker-verified; starts its own bounded supervisor)',effect='durable idempotent pause request: one cancel only at a safe point (right after a member turns OnGoing, or tester idle after the member-boundary relaunch) while the bound monitor reports; an expired unconsumed cancel is answered by the EA with CANCEL_REJECTED and only that exact receipt admits exactly one successor stop (cancel-rejected-successor identity rules, both receipts kept, never blind replay); a closed, unbound or unlicensed monitor is a named blocker with its fix; the driver keeps its disk guard and finish, never records cancel_issued for a pause and adopts an outstanding unconfirmed stop; finish harvests completed members and records paused with a resume token. States: pausing, paused, pause_failed (one sentence + fix), finished. Optional supervise-seconds runs the bounded pause supervisor in this call'),
    'batch-resume':dict(required=['job-id'],optional=['new-batch-id','resume-token','include-failed','include-no-edge'],demo_lane='goat.exe demo batch-resume --batch-id <id> (also refreshes a restarted protected peer and starts the bounded driver)',effect='after paused: verify the exact paused result and resume token, build the remaining-work plan from per-member native evidence (resume-batch) tolerating only a refreshed protected-peer process, prepare the successor under a new ID (default <id>-rN) and record lineage paused batch -> successor; no start in this CLI, run-batch starts it'),
    'research-status':dict(required=[],effect='read-only lane status for one installation: terminal, account, EA build, current batch or seed hunt (status, members done/total, qualifying, last member, pace and ETA, lineage, pause), driver health, disk headroom and monitor/licence state with the plain reason and fix when unbound; never opens the mutable store, launches or signals MT5'),
    'finish':dict(required=['job-id'],effect='verify finished queue and idle runtime, retain result, restore owned controls')
}


class Controller:
    def __init__(self, receipt):
        self.install = load_installation(receipt)
        self.root = Path(self.install['controller_state_root'])
        self.local = Path(self.install['terminal_data_root'])/'MQL5/Files/GOATStudio'
        self.schema,self.policy = contracts(self.install['ea_version'])
        self.store = None

    def open(self, *, recovery=False):
        from studio_handover import guard
        if not recovery: guard(self)
        self.session = read_json(self.root/'session.json')
        if self.session['installation_sha256'] != sha(self.install):
            raise ValueError('Installation changed since bootstrap; reconcile before repair')
        if not (self.root/'studio.sqlite').is_file(): raise ValueError('Controller database missing; preserve remaining receipts')
        expected = dict(directory_id=self.session['directory_id'],terminal_id=self.session['terminal_id'],
                        run_id=self.session['run_id'],terminal_data_path=self.install['terminal_data_root'])
        if read_json(self.local/'active.json') != expected:
            raise ValueError('Controller session is not active; inspect the retained handover')
        self.store = StudioStore(self.root/'studio.sqlite',input_schema=self.schema,dependency_policy=self.policy)
        self.terminal,self.run = self.session['terminal_id'],self.session['run_id']
        self.bridge = StudioBridge(self.local/self.session['directory_id'],self.store,self.terminal,self.run)
        return self

    def state(self): return self.store.snapshot(self.terminal,self.run)

    def submit(self,command,payload,request_id,*,expected_revision=None,expected_generation=None):
        state = self.state()
        request = dict(schema_version=1,request_id=request_id,terminal_id=self.terminal,run_id=self.run,
                       expected_revision=state['revision'] if expected_revision is None else expected_revision,
                       generation=state['generation'] if expected_generation is None else expected_generation,command=command,payload=payload)
        # Persist the exact envelope before submission, making transport retries idempotent.
        path = self.root/'requests'/(request_id+'.json')
        if path.exists():
            prior = read_json(path)
            if prior['command'] != command or prior['payload'] != payload: raise ValueError('Request ID content changed')
            if expected_revision is not None and prior['expected_revision'] != expected_revision:
                raise ValueError('Request ID revision changed; retry the exact original request')
            if expected_generation is not None and prior['generation'] != expected_generation:
                raise ValueError('Request ID generation changed; retry the exact original request')
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
        from studio_protected_peer import binding_fields
        i=self.install;s=self.session
        peer=binding_fields(self)
        extra={}
        # Report-capable /config route material. The customer lane gains it once
        # onboarding staged its monitor profile (monitor-prepare); a session
        # without one keeps its historical binding and cannot use config start.
        if s.get('authority_kind')=='demo_direct' or (s.get('authority_kind')=='native_human_control'
                                                      and (self.root/'monitor-profile.json').is_file()):
            from studio_strategy_settings import read_values
            profile=read_json(self.root/'monitor-profile.json')
            name=profile.get('profile_name','')
            if not re.fullmatch(r'GOAT-Studio-[A-Za-z0-9_-]{1,100}',name):
                raise ValueError('Bound passive monitor profile required')
            preset=Path(i['terminal_data_root'])/'MQL5/Presets/GOAT Studio Agent.set'
            raw=preset.read_bytes()
            if read_values(raw)!=dict(Mode_Operation='11',Studio_ReadOnlyMonitor='true',
                                      Studio_MonitorRunPath='',EA_Desc='Studio Monitor'):
                raise ValueError('Exact passive monitor preset required')
            extra=dict(research_profile=name,report_location_bridge='installation_to_data_v1',
                startup_monitor=dict(expert=i['ea_relative_path'],preset=preset.name,
                                     preset_sha256=hashlib.sha256(raw).hexdigest()))
        return dict(research_terminal=i['terminal_executable'],research_data_root=i['terminal_data_root'],
                    common_files_root=i['common_files_root'],ea_relative_path=i['ea_relative_path'],
                    ea_sha256=i['ea_sha256'],ea_version=i['ea_version'],account_server=s['account']['server'],
                    account_confirmation_pending=False,live_trading_allowed=False,**({'protected_data_roots':[]}|peer),**extra)

    def native_args(self):
        i=self.install
        return dict(account=self.session['account'],observation_path=self.local/'ui-observation.json',
                    monitor_path=Path(i['terminal_data_root'])/'MQL5/Experts'/i['ea_relative_path'].replace('\\','/'),
                    monitor_sha256=i['ea_sha256'],input_schema=self.schema)

    def bootstrap(self,login,server):
        from studio_handover import guard
        guard(self)
        if not login or not re.fullmatch('[0-9]+',login) or not server or not re.fullmatch('[A-Za-z0-9_. -]+',server):
            raise ValueError('Explicit demo account login and server required')
        if (self.root/'session.json').exists():
            self.open()
            if self.session['account'] != {'login':login,'server':server}: raise ValueError('Existing account binding differs')
            return self.session
        if (self.local/'active.json').exists(): raise ValueError('Existing Studio activation requires reconciliation; use switch-plan and user review, never overwrite')
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
                     directory_id=run,account=dict(login=login,server=server),demo_only=True,authority_kind='native_human_control')
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

    def start_config(self,job_id,*,expected_generation=None,on_attempt=None):
        from studio_config_start import start
        return start(self,job_id,expected_generation=expected_generation,on_attempt=on_attempt)

    def start(self,job_id,*,expected_generation=None):
        from studio_seed_slot import guard_active_seed
        guard_active_seed(self.root)
        from studio_process_check import inspect_processes,revalidate_processes
        from studio_launch_intent import record_intent
        from studio_open_activation import activate_open
        from studio_dispatch_transport import publish
        from studio_native_request import validate_activated_job
        state=self.state();job=self.job(job_id);binding=self.binding();args=self.native_args()
        if state['owner']!='agent': raise ValueError('Human must Give to Agent in Studio first')
        generation=state['generation'] if expected_generation is None else expected_generation
        if state['generation']!=generation: raise ValueError('Controller generation changed before start')
        if job['status']!='pending': raise ValueError('Only pending job can start; reconcile existing attempt')
        # Check runtime BEFORE recording an irreversible attempt.
        self.runtime(require_idle=True,expected_batch_ongoing=False)
        from studio_research_authority import before_native_dispatch
        before_native_dispatch(self,job)
        baseline=inspect_processes(binding)
        package=self.root/'packages'/job_id
        digest=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()
        self.submit('queue.reserve',dict(job_id=job_id,configuration_sha256=job['configuration_sha256'],package_sha256=digest),job_id+'-reserve',expected_generation=generation)
        state=self.state()
        intent=record_intent(self.store,self.terminal,self.run,job_id,package,actor='agent',revision=state['revision'],generation=generation)
        evidence=self.root/'attempts'/intent['attempt_id'];evidence.parent.mkdir(exist_ok=True)
        def ownership(bound,inventory):
            revalidate_processes(bound,baseline)
            self.runtime(require_idle=True,expected_batch_ongoing=False)
        with exclusive_gate(self.local/'native-gate'):
            if self.state()['generation']!=generation: raise ValueError('Controller generation changed before activation')
            activate_open(self.state(),self.job(job_id),**args,evidence=evidence,process_baseline=baseline,validate_ownership=ownership)
        state=self.state()
        def validate(state,job):
            revalidate_processes(binding,baseline)
            before_native_dispatch(self,job)
            return validate_activated_job(state,job,**args,evidence=evidence)
        return publish(self.store,self.terminal,self.run,job_id,self.bridge.root,actor='agent',revision=state['revision'],generation=generation,validate_native=validate)

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
        from studio_cancel_successor import cancel_id
        cancellation=observe_dispatch(self.local/'native-gate',cancel_id(self.root,job,self.local/'native-gate'))
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

    def cancel(self,job_id,*,expected_generation=None):
        from studio_cancel import publish_cancel
        job=self.job(job_id)
        if job['status']=='pending': return self.submit('queue.cancel',dict(job_id=job_id),job_id+'-cancel',expected_generation=expected_generation)
        return publish_cancel(self,job,expected_generation=expected_generation)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation',type=Path,required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('peer-prepare');p.add_argument('--terminal-executable',type=Path,required=True);p.add_argument('--data-root',type=Path,required=True)
    p=sub.add_parser('peer-apply');p.add_argument('--review-id',required=True);p.add_argument('--confirm-reviewed',action='store_true')
    p=sub.add_parser('bootstrap-retirement-prepare');p.add_argument('--specification',type=Path,required=True);p.add_argument('--bootstrap-receipts',type=Path,required=True)
    p=sub.add_parser('bootstrap-retirement-apply');p.add_argument('--review-id',required=True)
    p=sub.add_parser('switch-verify-park');p.add_argument('--review-id',required=True)
    p=sub.add_parser('switch-replace-receipt');p.add_argument('--review-id',required=True);p.add_argument('--candidate-receipt',type=Path,required=True);p.add_argument('--expected-sha256',required=True)
    p=sub.add_parser('switch-replace-build');p.add_argument('--review-id',required=True);p.add_argument('--candidate-receipt',type=Path,required=True);p.add_argument('--candidate-ea',type=Path,required=True);p.add_argument('--expected-sha256',required=True)
    sub.add_parser('historical-pointers-prepare')
    p=sub.add_parser('historical-pointers-apply');p.add_argument('--review-id',required=True);p.add_argument('--confirm-reviewed',action='store_true')
    p=sub.add_parser('switch-plan');p.add_argument('--restore-id')
    p=sub.add_parser('owner-maintenance-prepare')
    p=sub.add_parser('owner-maintenance-install-prepare');p.add_argument('--record-id',required=True)
    p=sub.add_parser('owner-maintenance-bootstrap');p.add_argument('--record-id',required=True);p.add_argument('--plan',type=Path,required=True)
    p=sub.add_parser('switch-apply');p.add_argument('--review-id',required=True);p.add_argument('--confirm-reviewed',action='store_true');p.add_argument('--owner-maintenance',help='Owner-internal exact one-use record; refuses outside pinned scope')
    p=sub.add_parser('switch-status');p.add_argument('--review-id',required=True)
    p=sub.add_parser('seed-prepare');p.add_argument('--batch-id',required=True);p.add_argument('--plan',type=Path,required=True)
    for command in ('seed-start','seed-resume'):
        p=sub.add_parser(command);p.add_argument('--batch-id',required=True);p.add_argument('--max-seconds',type=int,default=60)
    for command in ('seed-status','seed-cancel','seed-report'):
        p=sub.add_parser(command);p.add_argument('--batch-id',required=True)
    p=sub.add_parser('seed-promote');p.add_argument('--batch-id',required=True);p.add_argument('--candidate',required=True);p.add_argument('--name',required=True);p.add_argument('--neighborhood',type=int,default=1);p.add_argument('--member')
    p=sub.add_parser('evidence-end');p.add_argument('--value',default='auto');p.add_argument('--broker-clock')
    p=sub.add_parser('evidence-scan');p.add_argument('--source',type=Path,action='append',required=True);p.add_argument('--evidence-end',default='auto');p.add_argument('--broker-clock');p.add_argument('--include-below-threshold',action='store_true')
    p=sub.add_parser('evidence-versions');p.add_argument('--values-sha256')
    p=sub.add_parser('catchup-validate');p.add_argument('--plan',type=Path,required=True)
    p=sub.add_parser('catchup-prepare');p.add_argument('--catchup-id',required=True);p.add_argument('--plan',type=Path,required=True)
    for command in ('catchup-start','catchup-resume'):
        p=sub.add_parser(command);p.add_argument('--catchup-id',required=True);p.add_argument('--max-seconds',type=int,default=60)
    for command in ('catchup-status','catchup-cancel','catchup-report'):
        p=sub.add_parser(command);p.add_argument('--catchup-id',required=True)
    p=sub.add_parser('prepare-batch');p.add_argument('--batch-id',required=True);p.add_argument('--plan',type=Path,required=True)
    p=sub.add_parser('batch-status');p.add_argument('--batch-id',required=True)
    p=sub.add_parser('save-batch');p.add_argument('--batch-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('load-batch');p.add_argument('--batch-id',required=True);p.add_argument('--file',type=Path,required=True)
    p=sub.add_parser('resume-batch');p.add_argument('--batch-id',required=True);p.add_argument('--source-batch-id',required=True);p.add_argument('--include-failed',action='store_true');p.add_argument('--include-no-edge',action='store_true',help='Also re-run members tested with no profitable settings (results, not failures)')
    sub.add_parser('resource-profile')
    p=sub.add_parser('benchmark-report');p.add_argument('--batch-id',required=True)
    sub.add_parser('discover');sub.add_parser('state');sub.add_parser('onboarding-status')
    sub.add_parser('same-ea-rebind')
    p=sub.add_parser('self-repair');p.add_argument('--job-id',required=True);p.add_argument('--action-id',required=True);p.add_argument('--linked-login',required=True)
    p=sub.add_parser('monitor-prepare');p.add_argument('--symbol',required=True)
    p=sub.add_parser('monitor-launch');p.add_argument('--attempt-id',required=True)
    p=sub.add_parser('monitor-repair');p.add_argument('--attempt-id',required=True)
    p=sub.add_parser('monitor-stop');p.add_argument('--attempt-id',required=True)
    p=sub.add_parser('validate-set');p.add_argument('--set',type=Path,required=True);p.add_argument('--require-optimization',action='store_true')
    p=sub.add_parser('build-set');p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--spec',type=Path,required=True)
    p=sub.add_parser('bootstrap');p.add_argument('--account-login',required=True);p.add_argument('--account-server',required=True)
    p=sub.add_parser('serve');p.add_argument('--watch-seconds',type=float,default=3600)
    p=sub.add_parser('clear-queue');p.add_argument('--apply',action='store_true');p.add_argument('--request-id');p.add_argument('--expected-revision',type=int)
    sub.add_parser('native-recovery-status')
    sub.add_parser('orphan-recovery-prepare')
    p=sub.add_parser('orphan-recovery-apply');p.add_argument('--review-id',required=True);p.add_argument('--confirm-reviewed',action='store_true');p.add_argument('--owner-research',action='store_true',help='Use the reviewed owner-demo grant scope; never represents a human confirmation')
    p=sub.add_parser('orphan-recovery-status');p.add_argument('--review-id',required=True)
    p=sub.add_parser('orphan-recovery-reconcile-rejection',help='Settle one reviewed expired pre-consumption review/runtime/foreign-control rejection; never retry recovery');p.add_argument('--review-id',required=True);p.add_argument('--confirm-reviewed',action='store_true');p.add_argument('--owner-research',action='store_true',help='Use the reviewed owner-demo grant scope; never represents a human confirmation');p.add_argument('--terminal-stopped',action='store_true',help='Explicit human-confirmed cleanup with the selected terminal stopped; no offline owner authority or native flag changes')
    p=sub.add_parser('run-batch');p.add_argument('--job-id',required=True);p.add_argument('--max-seconds',type=int);p.add_argument('--resume',action='store_true');p.add_argument('--mt5-restart-consent',action='store_true',help='The user agreed that GOAT closes and reopens the selected MT5 once to start this batch through /config (required to start on the customer lane)');p.add_argument('--min-free-bytes',type=int,help='Positive free-space reserve on each output filesystem; default 5368709120 (5 GiB), frozen at start; omit on resume')
    p=sub.add_parser('batch-driver-status');p.add_argument('--job-id',required=True)
    p=sub.add_parser('retire-unactivated');p.add_argument('--job-id',required=True)
    p=sub.add_parser('batch-stop');p.add_argument('--job-id',required=True)
    p=sub.add_parser('batch-continue');p.add_argument('--job-id',required=True);p.add_argument('--new-batch-id');p.add_argument('--include-failed',action='store_true');p.add_argument('--include-no-edge',action='store_true')
    p=sub.add_parser('compact-evidence');p.add_argument('--apply',action='store_true')
    p=sub.add_parser('compact-receipts');p.add_argument('--apply',action='store_true')
    p=sub.add_parser('batch-pause');p.add_argument('--job-id',required=True);p.add_argument('--immediate',action='store_true');p.add_argument('--supervise-seconds',type=int)
    p=sub.add_parser('batch-resume');p.add_argument('--job-id',required=True);p.add_argument('--new-batch-id');p.add_argument('--resume-token');p.add_argument('--include-failed',action='store_true');p.add_argument('--include-no-edge',action='store_true',help='Also re-run members tested with no profitable settings')
    sub.add_parser('research-status')
    p=sub.add_parser('submit');p.add_argument('--request',type=Path,required=True)
    p=sub.add_parser('prepare');p.add_argument('--job-id',required=True);p.add_argument('--set',type=Path,required=True);p.add_argument('--configuration',type=Path,required=True)
    for command in ('start','status','cancel','reconcile','finish','research-monitor-restart','research-monitor-restart-resume','research-monitor-restart-status','cancel-rejected-successor'):
        p=sub.add_parser(command);p.add_argument('--job-id',required=True)
    p=sub.add_parser('research-monitor-reopen-prepare');p.add_argument('--job-id',required=True)
    p=sub.add_parser('research-monitor-adopt-reopen');p.add_argument('--job-id',required=True);p.add_argument('--human-reopened',action='store_true')
    p=sub.add_parser('research-monitor-repair-derived-report');p.add_argument('--job-id',required=True)
    p=sub.add_parser('research-monitor-repair-revoked-report');p.add_argument('--job-id',required=True)
    p=sub.add_parser('research-retire-never-started');p.add_argument('--job-id',required=True)
    sub.add_parser('research-regrant-status')
    args=parser.parse_args(argv);controller=None;locks=ExitStack()
    try:
        from studio_research_authority import operation,dispatch
        locks.enter_context(operation(args.operation))
        if args.operation=='self-repair':
            from studio_self_repair import repair
            result=repair(args.installation,args.job_id,args.action_id,linked_login=args.linked_login)
            print(json.dumps(dict(ok=result['status']=='repaired_terminal_stopped',result=result),ensure_ascii=False,allow_nan=False))
            return 0 if result['status']=='repaired_terminal_stopped' else 2
        if args.operation=='switch-replace-build':
            from studio_build_upgrade import replace_build
            result=replace_build(args.installation,args.review_id,args.candidate_receipt,args.candidate_ea,args.expected_sha256)
            print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
        if args.operation=='same-ea-rebind':
            from studio_same_ea_rebind import rebind
            result=rebind(args.installation)
            print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
        controller=Controller(args.installation)
        from studio_build_upgrade import guard_pending
        guard_pending(controller.root)
        if args.operation!='owner-maintenance-bootstrap': dispatch(controller,args)
        if args.operation.startswith('historical-pointers-'):
            from studio_historical_pointers import prepare as historical_prepare,apply as historical_apply
            result=historical_prepare(controller) if args.operation=='historical-pointers-prepare' else historical_apply(controller,args.review_id,confirmed=args.confirm_reviewed)
            print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
        from studio_historical_pointers import guard_pending as historical_guard
        historical_guard(controller)
        if args.operation=='research-status':
            from studio_research_status import research_status
            from studio_seed_process import WindowsSeedProcess
            try:process=WindowsSeedProcess(controller).inspect()
            except (OSError,ValueError,subprocess.SubprocessError):process='unknown'
            result=research_status(root=controller.root,install=controller.install,session=read_json(controller.root/'session.json'),
                                   local=controller.local,now=time.time(),process=process,
                                   owner_stop=(controller.root/'demo-agent/STOP').exists())
            print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
        if args.operation in ('evidence-end','evidence-scan','evidence-versions','catchup-validate'):
            from studio_catchup import read_operation
            result=read_operation(controller,args)
            print(json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False));return 0
        if args.operation not in ('peer-prepare','peer-apply','switch-plan','switch-apply','switch-status','switch-verify-park','switch-replace-receipt','discover','resource-profile') and not args.operation.startswith(('orphan-recovery-','bootstrap-retirement-','owner-maintenance-')):
            from studio_handover import session_lock,guard
            locks.enter_context(session_lock(controller));guard(controller)
        if args.operation in ('switch-verify-park','switch-replace-receipt'):
            from studio_installation_upgrade import verify_park,replace_receipt
            result=verify_park(controller,args.review_id) if args.operation=='switch-verify-park' else replace_receipt(controller,args.review_id,args.candidate_receipt,args.expected_sha256)
        elif args.operation in ('owner-maintenance-install-prepare','owner-maintenance-bootstrap'):
            from studio_owner_continuation import prepare_install,bootstrap
            result=prepare_install(controller,args.record_id) if args.operation=='owner-maintenance-install-prepare' else bootstrap(controller,args.record_id,args.plan)
        elif args.operation=='owner-maintenance-prepare':
            from studio_owner_maintenance import prepare
            result=prepare(controller)
        elif args.operation.startswith('bootstrap-retirement-'):
            from studio_bootstrap_retirement import prepare,apply
            result=prepare(controller,args.specification,args.bootstrap_receipts) if args.operation=='bootstrap-retirement-prepare' else apply(controller,args.review_id)
        elif args.operation in ('peer-prepare','peer-apply'):
            from studio_protected_peer import prepare,apply
            result=prepare(controller,args.terminal_executable,args.data_root) if args.operation=='peer-prepare' else apply(controller,args.review_id,args.confirm_reviewed)
        elif args.operation in ('switch-plan','switch-apply','switch-status'):
            from studio_handover import review,apply,load_plan,public
            if args.operation=='switch-plan': result=review(controller,args.restore_id)
            elif args.operation=='switch-status': result=public(load_plan(controller,args.review_id))
            else: result=apply(controller,args.review_id,args.confirm_reviewed,owner_maintenance=args.owner_maintenance)
        elif args.operation=='discover':
            from studio_customer_skills import customer_skills
            result=dict(agent_skills=customer_skills(),controller_version=VERSION,ea_version=controller.install['ea_version'],input_schema=controller.schema,dependency_policy=controller.policy,installation=controller.install,operations=list(sub.choices),operation_contracts=OPERATION_CONTRACTS,tester_fields=sorted(FIELDS),tester_recommendations=dict(Model=1,model_name='1 minute OHLC',policy='Default for new optimization plans; retain explicit user overrides and never rewrite frozen runs'),periods=sorted(PERIODS),export_fields=['SetsToExport','MinScore','TargetDD','AdjustLots','BackOOSDate','MinARF','MinSR','IncludeBackOOS','IncludeSequenceData'],native_constraints=['Windows MT5 demo connected; DLL enabled; Algo Trading off','Only selected MT5 and an explicitly reviewed exact protected peer may be running; unknown/replaced processes block','Ordinary optimization/export batches require custom forward and local workers','Give to Agent required; explicit batch start; EA advances members'],seed_constraints=['Dedicated SeedFarming uses ForwardMode=0 and empty ForwardDate','Explicit bounded seed-start/seed-resume driver; selected terminal closes and relaunches for frozen members','Seed and ordinary native execution share one exclusive terminal slot','Actual native seed launch qualification is pending'],documentation=['AGENT-START-HERE.md','GOAT-OPERATING-MODEL.md','CUSTOMER-SKILLS.md','OPTIMIZATION-PLAYBOOK.md','goat-beta-agent-guide.md','goat-agent-capabilities.md','INPUT-REFERENCE.md','TEMPLATE-WORKFLOW.md','SEED-WORKFLOW.md'],readiness_scope='Runtime and ownership checked at start, not by discovery',execution_ready=False)
        elif args.operation=='resource-profile':
            from studio_resources import resource_profile
            result=resource_profile(controller.install)
        elif args.operation=='benchmark-report':
            from studio_benchmark import benchmark_report
            result=benchmark_report(controller,args.batch_id)
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
            if not args.operation.startswith('orphan-recovery-'): controller.open()
            if args.operation in ('monitor-repair','monitor-stop'):
                from studio_monitor_repair import repair
                result=repair(controller,args.attempt_id,stop_only=args.operation=='monitor-stop')
            elif args.operation.startswith('orphan-recovery-'):
                from studio_orphan_recovery import prepare,apply,status
                if args.operation=='orphan-recovery-prepare': result=prepare(controller)
                elif args.operation=='orphan-recovery-apply': result=apply(controller,args.review_id,confirmed=args.confirm_reviewed,owner_research=args.owner_research)
                elif args.operation=='orphan-recovery-reconcile-rejection':
                    from studio_orphan_rejection import reconcile_rejection
                    result=reconcile_rejection(controller,args.review_id,confirmed=args.confirm_reviewed,owner_research=args.owner_research,terminal_stopped=args.terminal_stopped)
                else: result=status(controller,args.review_id)
            elif args.operation=='seed-promote':
                from studio_seed_promote import promote
                result=promote(controller,args.batch_id,args.candidate,args.name,neighborhood=args.neighborhood,member=args.member)
            elif args.operation.startswith('catchup-'):
                from studio_catchup import CatchupRunner
                runner=CatchupRunner(controller)
                if args.operation=='catchup-prepare':
                    from studio_batch import _json
                    result=runner.prepare(args.catchup_id,_json(args.plan))
                elif args.operation in ('catchup-start','catchup-resume'):
                    result=getattr(runner,args.operation.removeprefix('catchup-'))(args.catchup_id,max_seconds=args.max_seconds)
                else: result=getattr(runner,args.operation.removeprefix('catchup-'))(args.catchup_id)
            elif args.operation.startswith('seed-'):
                from studio_seed import SeedRunner
                runner=SeedRunner(controller)
                if args.operation=='seed-prepare':
                    from studio_batch import _json
                    result=runner.prepare(args.batch_id,_json(args.plan))
                elif args.operation in ('seed-start','seed-resume'):
                    result=getattr(runner,args.operation.removeprefix('seed-'))(args.batch_id,max_seconds=args.max_seconds)
                else: result=getattr(runner,args.operation.removeprefix('seed-'))(args.batch_id)
            elif args.operation in ('run-batch','batch-driver-status'):
                from studio_batch_driver import run,status
                if args.operation=='run-batch': result=run(controller,args.job_id,max_seconds=args.max_seconds,resume=args.resume,min_free_bytes=args.min_free_bytes,restart_consent=args.mt5_restart_consent)
                else: result=status(controller,args.job_id)
            elif args.operation in ('batch-stop','batch-continue'):
                from studio_fast_lane import stop as fast_stop,continue_batch
                result=fast_stop(controller,args.job_id) if args.operation=='batch-stop' else continue_batch(controller,args.job_id,new_batch_id=args.new_batch_id,include_failed=args.include_failed,include_no_edge=args.include_no_edge)
            elif args.operation=='compact-evidence':
                from studio_evidence_log import compact
                result=compact(controller,apply=args.apply)
            elif args.operation=='compact-receipts':
                from studio_receipt_digest import compact as compact_receipts
                result=compact_receipts(controller,apply=args.apply)
            elif args.operation=='retire-unactivated':
                from studio_retire_unactivated import retire
                result=retire(controller,args.job_id)
            elif args.operation=='batch-pause':
                from studio_batch_pause import request as request_pause,load as load_pause,public as public_pause
                journal_path=controller.root/'batch-drivers'/(args.job_id+'.json')
                record,_=request_pause(controller.root,controller.job(args.job_id),read_json(journal_path) if journal_path.is_file() else None,
                                       now=time.time(),requested_by='studio_cli',immediate=args.immediate)
                driver=None
                if args.supervise_seconds is not None and record['state']=='pausing':
                    from studio_batch_driver import run
                    driver=run(controller,args.job_id,resume=True,pause_seconds=args.supervise_seconds)
                result=dict(public_pause(load_pause(controller.root,args.job_id)),driver=driver)
            elif args.operation=='batch-resume':
                from studio_batch import resume_batch
                from studio_batch_pause import verify_resumable,successor_id,plan_resume,mark_resumed,load as load_pause
                verify_resumable(controller,args.job_id,args.resume_token)
                retained=load_pause(controller.root,args.job_id)
                new_id=args.new_batch_id or retained.get('resume_batch_id') or retained.get('successor_batch_id') or successor_id(args.job_id,{j['job_id'] for j in controller.state()['queue']})
                plan_resume(controller.root,args.job_id,new_id,now=time.time())
                prepared=resume_batch(controller,args.job_id,new_id,include_failed=args.include_failed,include_no_edge=args.include_no_edge,allow_peer_refresh=True)
                mark_resumed(controller.root,args.job_id,new_id,now=time.time(),selected=prepared.get('member_count'))
                result=dict(state='resumed',source_batch_id=args.job_id,batch_id=new_id,prepared=prepared,
                            next_action='run-batch --job-id '+new_id+' --max-seconds <budget> starts the successor'+
                            (' (add --mt5-restart-consent after the user agrees GOAT closes and reopens their MT5)'
                             if controller.session.get('authority_kind')=='native_human_control' else ''))
            elif args.operation=='research-monitor-restart':
                from studio_rejected_monitor import restart
                result=restart(controller,args.job_id)
            elif args.operation=='research-monitor-reopen-prepare':
                from studio_human_reopen import prepare
                result=prepare(controller,args.job_id)
            elif args.operation=='research-monitor-repair-derived-report':
                from studio_derived_report_recovery import recover
                result=recover(controller,args.job_id)
            elif args.operation=='research-monitor-repair-revoked-report':
                from studio_derived_report_recovery import recover
                result=recover(controller,args.job_id,revoked_maintenance=True)
            elif args.operation=='research-retire-never-started':
                from studio_never_started_retirement import retire
                result=retire(controller,args.job_id)
            elif args.operation=='research-regrant-status':
                from studio_research_regrant import takeover,native
                from campaign_ledger import packed
                state=controller.state()
                _,base,prior=takeover(controller.store.db,packed(dict(terminal_id=controller.terminal,run_id=controller.run)),state)
                result=dict(owner=state['owner'],generation=state['generation'],original_scope_revoked=True,takeover=prior,
                            native=native(controller,state),grant_created=False)
            elif args.operation=='research-monitor-adopt-reopen':
                from studio_human_reopen import adopt
                result=adopt(controller,args.job_id,human_reopened=args.human_reopened)
            elif args.operation=='research-monitor-restart-status':
                from studio_rejected_monitor import reverify
                result=reverify(controller,args.job_id)
            elif args.operation=='research-monitor-restart-resume':
                from studio_rejected_monitor import resume
                result=resume(controller,args.job_id)
            elif args.operation=='cancel-rejected-successor':
                from studio_cancel_successor import create
                result=create(controller,args.job_id)
            elif args.operation=='serve': result=pump_for(controller.bridge,args.watch_seconds)
            elif args.operation=='state': controller.bridge.pump();result=controller.state()
            elif args.operation=='clear-queue':
                from studio_queue_clear import clear_queue
                result=clear_queue(controller,apply=args.apply,request_id=args.request_id,expected_revision=args.expected_revision)
            elif args.operation=='native-recovery-status':
                from studio_queue_clear import recovery_status
                result=recovery_status(controller)
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
                result=resume_batch(controller,args.source_batch_id,args.batch_id,include_failed=args.include_failed,include_no_edge=args.include_no_edge)
            elif args.operation=='start':
                from studio_config_start import refuse_raw_start
                refuse_raw_start(controller.session)
                result=controller.start(args.job_id)
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
        locks.close()

if __name__=='__main__': sys.exit(main())
