"""Mutation check for cancel-regrant (studio_cancel_regrant and what it binds).

Each guard is removed in a temporary copy of controller/ and test_studio_cancel_regrant must
fail; a NameError, ImportError or SyntaxError in the report means the mutated copy broke, which is
never counted as caught. A mutant whose run exceeds MUTANT_TIMEOUT_SECONDS is reported TIMEOUT, not counted as
caught, and the sweep continues. The repository is never modified. Run it directly: python scripts/test_cancel_regrant_mutations.py
Optional arguments START STOP run that slice of the list, so a long sweep can be split; a slice never reports the total as 100%.
Off Windows, msvcrt is stubbed after the stdlib loads so demo_agent imports; that is local convenience,
never evidence about Windows. Not wired into the CI shards.
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTROLLER = REPO / 'controller'
RUNNER = ('import asyncio,multiprocessing,os,shutil,subprocess,sys,types,unittest\n'
          'root=sys.argv[1]\n'
          'if os.name!="nt":\n'
          '    stub=types.ModuleType("msvcrt");stub.LK_NBLCK=2;stub.LK_UNLCK=0;stub.LK_LOCK=1\n'
          '    stub.locking=lambda fd,mode,n:None;stub.get_osfhandle=lambda fd:fd;sys.modules["msvcrt"]=stub\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.loadTestsFromName("test_studio_cancel_regrant")\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
R = 'studio_cancel_regrant.py'
BROKEN_COPY = ('ImportError', 'SyntaxError', 'NameError', 'UnboundLocalError')
# The whole test file takes about 9 minutes at Idle priority on a busy PC (11-07), so 600 s cut healthy runs short.
MUTANT_TIMEOUT_SECONDS = 1800
MUTATIONS = [
    # Admission clauses
    ('lane not required', R, "if session.get('authority_kind') not in LANES or session.get('demo_only') is not True:",
     "if session.get('demo_only') is not True:"),
    ('demo_only not required', R, "if session.get('authority_kind') not in LANES or session.get('demo_only') is not True:",
     "if session.get('authority_kind') not in LANES:"),
    ('frozen configuration not checked', R, "if sha(job['configuration']) != job['configuration_sha256']:", "if False:"),
    ('owner not checked', R, "if state['owner'] != 'agent':\n        _refuse('REGRANT_OWNER_NOT_AGENT', 'The human owns this terminal; ask them to click GIVE TO AGENT first.')\n    root, gate",
     "if False:\n        pass\n    root, gate"),
    ('successor not required', R, "if not successor_path.exists():", "if False:"),
    ('unpublished successor accepted', R, "    if prior is None:\n", "    if False:\n"),
    ('second stop at one generation', R, "if retained is not None and (gate / ('issued-' + retained['request_id'] + '.json')).exists():", "if False:"),
    ('link ahead accepted', R, "if links and links[-1]['generation'] > state['generation']:", "if False:"),
    ('same generation accepted', R, "if state['generation'] <= prior['generation']:", "if False:"),
    ('consumed prior accepted', R, "if dispatch.get('consumed') is not False:", "if False:"),
    ('live prior accepted', R, "if prior['expires_utc'] >= now:", "if False:"),
    ('any prior receipt accepted', R, "if dispatch['status'] == 'receipt_observed' and dispatch['receipt']['status'] not in REPLACEABLE_RECEIPTS:", "if False:"),
    ('no archived grant needed', R, "    grant = _archived_grant(controller, state)\n", "    grant = None\n"),
    ('archive not hashed to its human receipt', R, "or sha(dict(request=request, actor='human')) != payload_hash):", "or False):"),
    ('native hashes not checked', R, "    hashes = _native_hashes(controller, job, prior)\n", "    hashes = {}\n"),
    ('owner hash not checked', R, "if owner.get('owner') != job['launch_intent']['attempt_id'] or owner_hash != prior.get('native_owner_sha256'):", "if False:"),
    ('pointer hash not checked', R, "if (pointer_hash != prior.get('pointer_sha256') or manifest", "if (False or manifest"),
    ('EA sample not checked', R, "    batch_ongoing = _runtime(controller, state)\n", "    batch_ongoing = True\n"),
    ('grant need not be observed', R, "if observation.get('owner') != 'agent' or observation.get('generation') != state['generation']:", "if False:"),
    ('broker not checked', R, "    native = _broker(controller)\n", "    native = {}\n"),
    ('ordinary cancel publishes an unissued link', R, "if any(value['request_id'] == request_id for value in _links(root, attempt)):", "if False:"),
    ('disk floor not read before publishing', R, "                disk = _disk_gate(controller)\n", "                disk = dict(volumes=[])\n"),
    ('disk floor ignored', R, "    if disk['reason']:\n        reading", "    if False:\n        reading"),
    ('disk reading not given', R, "'Disk when sent: ' + _disk_reading(disk) + '.')", "'')"),
    # Identity chain
    ('link identity not verified', R, "or value.get('request_id') != sha([attempt, 'cancel-successor-regrant', value.get('prior_issued_sha256'), generation])", "or False"),
    ('prior evidence not verified', R, "or _digest(gate / ('issued-' + latest + '.json')) != value['prior_issued_sha256']):", "or False):"),
    ('cancel_id ignores the link', 'studio_cancel_successor.py', "return current_stop(root,gate,value)", "return value['request_id']"),
    # Finding 1: nothing irreversible before finish's own refusals are read
    ('finish preflight removed', R, "    _finish_preflight(controller, job)\n", ""),
    ('report verdict ignored', R, "    if not reports_verified(reports):\n        rows =", "    if False:\n        rows ="),
    ('preflight reads the queue before the stop', R, "after_stop = ['native_cancelled' if member['status'] in ('native_pending', 'native_queued', 'native_ongoing')\n                      else member['status'] for member in native['members']]",
     "after_stop = [member['status'] for member in native['members']]"),
    ('missing native queue accepted', R, "        if native.get('status') == 'native_evidence_missing':", "        if False:"),
    ('source evidence not read first', R, "        read_json(Path(controller.root) / 'packages' / (job['job_id'] + '.source.json'))\n", ""),
    ('transaction not read first', R, "transaction = read_json(evidence / 'transaction.json')", "transaction = dict(owner=intent['attempt_id'], phase='restored')"),
    ('report bridge evidence not compared', R, "if read_json(evidence / 'report-bridge.json') != bridge or sha(plan) != manifest['campaign_id']:", "if False:"),
    ('report alias not checked first', R, "            check_retirable(plan['research_binding'], manifest['native_run_relative'], bridge, evidence)\n", ""),
    ('alias check skips the junction', 'studio_report_bridge.py', "    elif exists:\n        verify(expected)\n", "    elif exists:\n        pass\n"),
    ('alias check accepts a missing alias', 'studio_report_bridge.py', "    elif retained is None:\n        raise ValueError('Report alias missing without retirement intent')\n", ""),
    ('control backup not validated first', R, "            restorable(evidence)\n", "            pass\n"),
    ('another attempts transaction accepted', R, "if transaction['owner'] != intent['attempt_id']:", "if False:"),
    ('backup hash not checked', 'native_control_transaction.py', "if digest(raw) != item['before_sha256']:", "if False:"),
    ('lost report treated as a retry', R, "if all(row['status'] == 'reports_changing' for row in unverified):", "if True:"),
    ('changing report treated as lost', R, "if all(row['status'] == 'reports_changing' for row in unverified):", "if False:"),
    ('finish still gates reports', 'studio_finish.py', "    if not reports_verified(reports):\n", "    if False:\n"),
    # Finding 2: settle does what the revoked driver would
    ('settle skips reconcile', R, "            controller.reconcile(job_id)\n", "            pass\n"),
    ('settle skips the end state', R, "    _end_state(controller, job_id, record, path, time, end_state_fn)\n", ""),
    ('settle skips idle maintenance', R, "    after_batch(controller)\n", ""),
    ('end state not reported', R, "    if end_state.get('plain'):\n", "    if False:\n"),
    ('disk observation not recorded', R, "disk_observation=_capacity(controller, record.get('min_free_bytes') or DEFAULT_MIN_FREE_BYTES))", "disk_observation=None)"),
    ('admission skips the attempt binding', R, "    _owned(controller, job, journal)\n    batch_ongoing", "    batch_ongoing"),
    ('settle skips the attempt binding', R, "        _owned(controller, job, journal)\n        _refuse_undelivered", "        _refuse_undelivered"),
    ('driver journal not required', R, "    if journal is None:\n        _refuse('REGRANT_NO_DRIVER_JOURNAL', 'This batch has no driver journal to bind the re-grant to.')\n    _owned", "    _owned"),
    # Finding 3: a stop that never reached MT5 is named, not waited on
    ('admission calls it already issued', R, "        _refuse_undelivered(gate, retained['request_id'], dispatch)\n", ""),
    ('settle waits on an undelivered stop', R, "        _refuse_undelivered(gate, request_id, dispatch)\n        if not links", "        if not links"),
    # Reboot between the EA's claim and its receipt, and the other dead ends: one named code each
    ('admission gives the wrong advice on a dead claim', R, "    _escalate_claim(controller, job, latest, dispatch)\n", ""),
    ('settle waits on a dead claim', R, "        _escalate_claim(controller, job, request_id, dispatch)\n", "        pass\n"),
    ('a good receipt counts as a dead claim', R, "if dispatch.get('consumed') is not True or dispatch.get('receipt', {}).get('status') in CONSUMED_RECEIPTS:\n        return", "if dispatch.get('consumed') is not True:\n        return"),
    ('a claim is read without the gate MT5 holds', R, "    with exclusive_gate(gate, wait_seconds=NATIVE_GATE_WAIT_SECONDS):\n        dispatch = observe_dispatch(gate, request_id)\n", "    dispatch = observe_dispatch(gate, request_id)\n"),
    ('finish refusal never escalates', R, "if waited > FINISH_PATIENCE_SECONDS:", "if False:"),
    ('consumed successor cannot settle', R, "if not links and dispatch.get('consumed') is not True:", "if not links:"),
    ('unconsumed successor settles', R, "if not links and dispatch.get('consumed') is not True:", "if False:"),
    ('journal omits the pause', R, "record.update(status='paused' if pause['state'] == 'paused' else result['status'], pause_id=pause['pause_id'],", "record.update(status=result['status'],"),
    # Settling and the pause
    ('settle finishes an unconsumed stop', R, "if dispatch.get('consumed') is not True or dispatch.get('receipt', {}).get('status') not in CONSUMED_RECEIPTS:", "if False:"),
    ('one stop re-arms a failed pause repeatedly', 'studio_batch_pause.py', "if record['state'] == 'pause_failed':\n        if record.get('regrant_request_id') == request_id:", "if record['state'] == 'pause_failed':\n        if False:"),
    ('failed pause not re-armed', 'studio_batch_pause.py', "record.update(state='pausing', failure=None, blocker=None, generation=generation, regrant_request_id=request_id)", "record.update(failure=None, blocker=None, generation=generation, regrant_request_id=request_id)"),
    # Verb
    # The verb reads the shared human_waiting (studio_cancel_regrant); its inbox/processing/pending_id mutants are below.
    ('verb ignores a waiting human request', 'demo_agent.py', "if human_waiting(controller):   # the bridge's inbox", "if False:   # the bridge's inbox"),
    ('verb refused under owner STOP', 'demo_agent.py', "with self._studio('cancel-regrant', idle=False, owner_required=False, job_id=batch_id)", "with self._studio('cancel-regrant', idle=False, owner_required=True, job_id=batch_id)"),
    ('verb skips the broker', 'demo_agent.py', "            try:\n                self._broker(idle=False)\n            except Refusal:\n                raise\n            except ValueError as exc:\n                raise Refusal(str(exc) + ' Nothing was sent.', 'REGRANT_BROKER_NOT_IDLE_DEMO') from exc\n", ""),
    # Round 3: the customer lane (goat.exe studio cancel-regrant) and its demo proof
    ('customer lane refused', R, "LANES = frozenset(('demo_direct', 'native_human_control'))", "LANES = frozenset(('demo_direct',))"),
    ('broker skipped on the customer lane', R, "    native = _broker(controller)\n",
     "    native = _broker(controller) if controller.session.get('authority_kind') == 'demo_direct' else {}\n"),
    ('EA sample skipped on the customer lane', R, "    batch_ongoing = _runtime(controller, state)\n",
     "    batch_ongoing = _runtime(controller, state) if controller.session.get('authority_kind') == 'demo_direct' else True\n"),
    ('customer entry ignores a waiting human request', R, "    if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):\n        return True",
     "    if False:\n        return True"),
    ('customer entry reads only the inbox', R, "    if any(any((human / channel).glob('*.json')) for channel in ('inbox', 'processing')):\n        return True",
     "    if any(any((human / channel).glob('*.json')) for channel in ('inbox',)):\n        return True"),
    ('customer entry skips the Open Lab refusal', R, "    if str(session['account']['login']) in OPEN_LAB_LOGINS:", "    if False:"),
    ('customer entry outside the terminal lease', 'goat_studio.py', "'bootstrap-retirement-apply','cancel-regrant'))", "'bootstrap-retirement-apply'))"),
    # Round 3: the P3s
    ('a cut pointer escapes as an internal error', R, "    except (OSError, ValueError, configparser.Error) as error:\n        _refuse('REGRANT_NATIVE_OWNER_CHANGED'",
     "    except (OSError, ValueError) as error:\n        _refuse('REGRANT_NATIVE_OWNER_CHANGED'"),
    ('a cut block in finish escapes as an internal error', R, "READ_ERRORS = (OSError, ValueError, KeyError, TypeError, configparser.Error)",
     "READ_ERRORS = (OSError, ValueError, KeyError, TypeError)"),
    ('an unreadable volume is told to free space', R, "    if disk['reason'] == 'disk_probe_unavailable':", "    if False:"),
    ('finish escalation names no destination', R, "                          **_escalation('REGRANT_ESCALATE_FINISH_REFUSED'))", "                          )"),
    ('claim escalation names no destination', R, "**facts, **_escalation('REGRANT_ESCALATE_CLAIM_WITHOUT_OUTCOME'))", "**facts)"),
    ('reports escalation names no destination', R, "members=unverified, **_escalation('REGRANT_ESCALATE_REPORTS_LOST'))", "members=unverified)"),
    # Round 3 review: the settle path, V1.48's cancellation flag, an MT5 that is not reporting
    ('Open Lab refusal skipped under --settle', R, "    if str(session['account']['login']) in OPEN_LAB_LOGINS:",
     "    if not settle_stop and str(session['account']['login']) in OPEN_LAB_LOGINS:"),
    ('human-pending refusal skipped under --settle', R, "    if human_waiting(controller):", "    if not settle_stop and human_waiting(controller):"),
    ('entry ignores the panel pending_id', R, "    return isinstance(observation, dict) and bool(observation.get('pending_id'))", "    return False"),
    ('admission ignores the panel pending_id', R, "    if observation.get('pending_id'):\n        # The panel", "    if False:\n        # The panel"),
    ('settle skips the demo-only lane', R, "    _require_lane(controller.session)\n    job, state = _read(controller, job_id)\n    attempt",
     "    job, state = _read(controller, job_id)\n    attempt"),
    ('customer entry accepts any lane', R, "    if session.get('authority_kind') != 'native_human_control':", "    if False:"),
    ('V1.48 resume not refused', 'studio_batch_pause.py', "    if version not in (None, '1.48'):\n        return", "    if True:\n        return"),
    ('V1.48 refusal for every pause', 'studio_batch_pause.py', "    if not regrant:\n        return", "    if False:\n        return"),
    ('verify_resumable skips the V1.48 refusal', 'studio_batch_pause.py',
     "    refuse_v148_cancel_latch(controller.root, job_id, job=controller.job(job_id))\n", ""),
    ('continue skips the V1.48 refusal', 'studio_fast_lane.py', "    refuse_v148_cancel_latch(c.root, job_id, job=source)   # read-only", "    (c.root, job_id, source)   # read-only"),
    ('owner resume refuses only after writing', 'demo_agent.py', "        refuse_v148_cancel_latch(self.root, batch_id,\n                                 job=next((item",
     "        dict(root=self.root, batch_id=batch_id,\n                                 job=next((item"),
    ('owner continue refuses only after writing', 'demo_agent.py', "        refuse_v148_cancel_latch(self.root, batch_id, job=job)\n", ""),
    # Round 3, fourth review: resume-batch, and a version that cannot be read fails closed
    ('resume-batch skips the V1.48 refusal', 'studio_batch.py', "    refuse_v148_cancel_latch(controller.root, source_batch_id, job=previous)\n", ""),
    ('an unreadable stop version passes', 'studio_batch_pause.py', "    if version not in (None, '1.48'):", "    if version != '1.48':"),
    ('no fallback to the job completion', 'studio_batch_pause.py',
     "    if version is None:\n        version = ((job or {}).get('completion') or {}).get('ea_version')",
     "    if False:\n        version = None"),
    ('an unreadable pause record counts as no re-grant', 'studio_batch_pause.py', "else _regrant_links(root, job)", "else False"),
    ('V1.48 settle advises batch-resume', R, "    if (finished.get('result') or {}).get('ea_version') == '1.48':   # the receipt's EA",
     "    if False:   # the receipt's EA"),
    ('V1.48 finished batch told members remain', R, "if record['state'] == 'finished'\n                       else 'The finished members",
     "if False\n                       else 'The finished members"),
    ('finish refusal escalates while MT5 is not reporting', R, "        if waited > FINISH_PATIENCE_SECONDS and not _monitor_reporting(controller, monitor):", "        if False:"),
    ('a stale sample counts as reporting', R, "    return 0 <= time.time() - modified <= RUNTIME_MAX_AGE_SECONDS", "    return True"),
    ('a silent monitor counts as reporting', R, "    if monitor.get('ticking') is not True:\n        return False", "    if False:\n        return False"),
]


def main():
    caught = timed_out = 0
    selected = MUTATIONS[slice(*map(int, sys.argv[1:3]))] if len(sys.argv) > 2 else MUTATIONS
    for label, name, old, new in selected:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy(REPO / 'GOATStudioDispatch.mqh', Path(work) / 'GOATStudioDispatch.mqh')
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            started = time.monotonic()
            try:
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=MUTANT_TIMEOUT_SECONDS,
                                        cwd=str(copy), capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                # Its own outcome, never counted as caught: a hang proves nothing about the guard. The sweep goes on.
                timed_out += 1
                print('TIMEOUT ' + label + ' after ' + str(MUTANT_TIMEOUT_SECONDS) + ' s', flush=True)
                continue
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the tests ran and failed, not that the copy broke: a mutant whose own text fails to import,
            # parse or name its variables (ImportError, SyntaxError, NameError) proves nothing about the guard it removed.
            failed = (result.returncode == 1 and 'FAILED (' in report
                      and not any(broken in report for broken in BROKEN_COPY))
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label + ' (' + str(round(time.monotonic() - started)) + ' s)', flush=True)
    print(f'{caught}/{len(selected)} selected mutations caught, {timed_out} timed out, of {len(MUTATIONS)} in the list')
    return 0 if caught == len(selected) else 1


if __name__ == '__main__':
    sys.exit(main())
