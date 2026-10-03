"""Prepare a full native Optimization Studio queue with immutable member inputs.

The EA owns progression through the native queue, including selected exports.
Preparation never launches MT5. Revisions receive new batch IDs and preserve
previous jobs, packages and results.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import configparser
import uuid

from campaign_ledger import sha
from prepare_native_campaign import native_run_relative, prepare
from strategy_registry import connect, inspect_set
from studio_bridge import write_json
from studio_queue import validate_batch_members
from studio_strategy_settings import read_values
from studio_template_tools import source_bytes, validate_raw


MAX_PLAN_BYTES = 64 * 1024 * 1024
MAX_RETAINED_SET_BYTES = 128 * 1024 * 1024
# Binding fields that select the report-capable /config start route (goat_studio.binding).
CONFIG_START_BINDING_KEYS = ('research_profile', 'report_location_bridge', 'startup_monitor')

def _json(path, limit=MAX_PLAN_BYTES, *, with_raw=False):
    path = Path(path)
    if path.stat().st_size > limit: raise ValueError('Batch JSON exceeds its byte limit')
    with path.open('rb') as stream: raw = stream.read(limit + 1)
    if len(raw) > limit: raise ValueError('Batch JSON exceeds its byte limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate batch JSON key: ' + key)
            result[key] = value
        return result
    value=json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    return (value,raw) if with_raw else value


def _files(package):
    if Path(package).is_symlink() or getattr(Path(package), 'is_junction', lambda: False)(): raise ValueError('Linked batch package is unsupported')
    result = {}
    for file in sorted(Path(package).rglob('*')):
        if file.is_symlink() or getattr(file, 'is_junction', lambda: False)(): raise ValueError('Linked batch package artifact is unsupported')
        if file.is_file() and file != Path(package) / 'preparation.json':
            result[file.relative_to(package).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def _verify_package(controller, job, *, allow_peer_refresh=False, allow_binding_change=False):
    """Verify a frozen package against this installation.

    ``allow_peer_refresh`` is only for reading a finished package's remaining
    work: the protected peer's process instance (and so its reviewed policy hash)
    may have changed since preparation; every other binding field must match.
    """
    package = controller.root / 'packages' / job['job_id']
    receipt = _json(package / 'preparation.json')
    plan = _json(package / 'studio-plan.json'); manifest = _json(package / 'manifest.json')
    if (receipt.get('schema_version') != 1 or receipt.get('configuration_sha256') != job['configuration_sha256']
            or receipt.get('files') != _files(package) or sha(job['configuration']) != job['configuration_sha256']):
        raise ValueError('Prepared batch artifact or configuration identity changed')
    source = plan['studio_source']
    if source != dict(terminal_id=controller.terminal, run_id=controller.run, job_id=job['job_id'],
                      source_revision=job['source_revision'], configuration_sha256=job['configuration_sha256']):
        raise ValueError('Prepared batch belongs to another queue revision')
    recorded, current = plan['research_binding'], controller.binding()
    if allow_binding_change:
        # Reading a FINISHED package's remaining work after an EA build change: the
        # package is never launched again, so its own recorded binding stands; the
        # successor is prepared and fully verified under the current installation.
        if job['status'] not in ('completed', 'cancelled', 'failed'):
            raise ValueError('Only a finished package may be read across an installation change')
        current = recorded
    if allow_peer_refresh:
        if job['status'] not in ('completed', 'cancelled', 'failed'):
            raise ValueError('A refreshed protected peer only reads a finished package')
        from studio_protected_peer import PEER_BINDING_KEYS
        recorded = {key: value for key, value in recorded.items() if key not in PEER_BINDING_KEYS}
        current = {key: value for key, value in current.items() if key not in PEER_BINDING_KEYS}
    # A restarted protected peer is the same reviewed peer (studio_protected_peer):
    # a package prepared under the exact-instance rule still verifies when its
    # recorded policy names this peer's unchanged executable, data root and bytes.
    from studio_protected_peer import comparable
    recorded, current = comparable(controller, recorded, current)
    if ((getattr(controller, 'session', None) or {}).get('authority_kind') == 'native_human_control'
            and not any(key in recorded for key in CONFIG_START_BINDING_KEYS)):
        # A customer package prepared before the lane gained the report-capable
        # route stays readable for status/finish with every other identity field
        # exact. Config start still refuses it (no profile/bridge recorded).
        current = {key: value for key, value in current.items() if key not in CONFIG_START_BINDING_KEYS}
    if recorded != current or manifest['campaign_id'] != sha(plan):
        raise ValueError('Prepared batch installation or plan identity changed')
    if 'launch_intent' in job and hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest() != job['launch_intent']['package_sha256']:
        raise ValueError('Attempt package identity changed')
    from studio_batch_contract import configuration_members
    from studio_native_request import ini_sections
    from activate_research_campaign import verify_export_policy
    members = configuration_members(job['configuration'])
    if len(members) != len(manifest['jobs']): raise ValueError('Prepared batch member count changed')
    from studio_batch_seal import sealed
    # A valid prepare-time seal plus unchanged bytes stands in for the semantic pass.
    for member, item in ([] if sealed(package, job, controller.schema) else zip(members, manifest['jobs'])):
        alias = item['run_alias']
        if not re.fullmatch(r'R[0-9a-f]{20}', alias): raise ValueError('Invalid batch alias')
        for suffix, key in (('.set', 'staged_sha256'), ('.ini', 'ini_sha256')):
            if hashlib.sha256((package / (alias + suffix)).read_bytes()).hexdigest() != item[key]:
                raise ValueError('Prepared batch member artifact changed')
        if read_values((package / (alias + '.set')).read_bytes()) != (member['strategy']['values'] | {'EA_Desc': alias}):
            raise ValueError('Prepared batch strategy differs from frozen member')
        if any(str(value) != str(item['tester'].get(key)) for key, value in member['tester'].items()):
            raise ValueError('Prepared batch tester differs from frozen member')
        if ini_sections((package / (alias + '.ini')).read_bytes()).get('Tester') != {key: str(value) for key, value in item['tester'].items()}:
            raise ValueError('Prepared INI differs from frozen tester')
    verify_export_policy(package, plan, manifest)
    return package, plan, manifest


def evidence_end_policy(value, testers, *, now=None):
    """Batch evidence end ("front OOS" end): AUTO or an explicit closed broker day, recorded at prepare.

    The current EA ends each export at its own last Friday (exclusive), so the
    exports' actual end is recorded by the EA; OOS catch-up brings them to this
    target. Never later than a closed broker day, never before the window end.
    """
    from studio_evidence_end import legacy_end, resolve
    if not isinstance(value, str):
        raise ValueError('evidence_end must be "auto" or a closed broker date such as 2026-09-25')
    window_end = max(datetime.strptime(t['ToDate'], '%Y.%m.%d').date() for t in testers)
    target = resolve(value, now, not_before=[(window_end, 'the optimization window end (ToDate)')])
    return dict(requested=target['requested'], mode=target['mode'], target=target['iso'], target_label=target['label'],
                tester_to_date=target['tester_to_date'], rule=target['rule'], warnings=target['warnings'],
                resolved_utc=datetime.now(timezone.utc).isoformat(timespec='seconds') if now is None else now.isoformat(timespec='seconds'),
                native_export_end='ea_last_friday_exclusive', native_end_if_exported_now=legacy_end(now)['iso'],
                catch_up=('This EA build ends each export at its own last Friday (Thursday evidence). After the batch, '
                          'evidence-scan shows each export\'s end and catchup-prepare re-tests the stale ones to the target.'))


def read_plan(controller, plan_path):
    plan_path = Path(plan_path)
    spec, source_plan = _json(plan_path,with_raw=True)
    if (not isinstance(spec, dict) or set(spec) - {'evidence_end'} != {'schema_version', 'export', 'members'}
            or spec['schema_version'] != 1):
        raise ValueError('Batch plan requires schema_version:1, export and members (optional: evidence_end)')
    if not isinstance(spec['members'], list) or not 1 <= len(spec['members']) <= 10000:
        raise ValueError('Specify 1..10000 explicit file/asset members')
    raw_members, retained = [], []
    retained_bytes = 0
    for member in spec['members']:
        if not isinstance(member, dict) or set(member) != {'set_path', 'tester'}:
            raise ValueError('Every member requires set_path and complete tester settings')
        if not isinstance(member['set_path'], str) or not Path(member['set_path']).is_absolute():
            raise ValueError('Batch SET paths must be absolute on this installation')
        source, raw, _ = source_bytes(member['set_path'])
        retained_bytes += len(raw)
        if retained_bytes > MAX_RETAINED_SET_BYTES: raise ValueError('Batch retained SET inputs exceed 128 MiB')
        validate_raw(raw, controller.schema, controller.policy, require_optimization=True)
        if not isinstance(member['tester'], dict): raise ValueError('Complete tester object required')
        if member['tester'].get('Expert') != controller.install['ea_relative_path']:
            raise ValueError('Batch expert differs from this installed EA')
        raw_members.append(dict(tester=member['tester'], export=spec['export'],
            strategy=dict(schema_hash=sha(controller.schema), values=read_values(raw))))
        retained.append((source, raw, inspect_set(raw)))
    checked = validate_batch_members(raw_members, controller.schema, controller.policy)
    config = dict(checked[0], batch_members=checked)
    return config, raw_members, retained, hashlib.sha256(source_plan).hexdigest(), spec


def prepare_batch(controller, batch_id, plan_path, *, now=None):
    if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', batch_id):
        raise ValueError('Batch ID must be 1..80 letters, digits, underscore or hyphen')
    from studio_seed_slot import refuse_prepare_while_seed_owns
    refuse_prepare_while_seed_owns(controller.root)   # a start would refuse later with start_uncertain
    config, raw_members, retained, source_hash, spec = read_plan(controller, plan_path)
    evidence = (evidence_end_policy(spec['evidence_end'], [m['tester'] for m in config['batch_members']], now=now)
                if 'evidence_end' in spec else None)
    from studio_research_authority import authority
    # FU35+ EAs receive the one resolved date as EvidenceEnd; older builds keep the recorded legacy end.
    from studio_evidence_end_export import for_controller
    evidence = for_controller(controller, evidence)
    from campaign_ledger import packed
    scope = authority(controller.store.db,packed(dict(terminal_id=controller.terminal,run_id=controller.run)),controller.state())
    if scope is not None and (source_hash!=scope['plan_sha256'] or sha(raw_members)!=scope['members_sha256']):
        raise ValueError('Batch inputs differ from the immutable research continuation')
    checked = config['batch_members']
    snapshot = controller.state()
    existing = next((j for j in snapshot['queue'] if j['job_id'] == batch_id), None)
    package = controller.root / 'packages' / batch_id
    if existing:
        if existing['configuration_sha256'] != sha(config):
            raise ValueError('Batch ID already belongs to different members/settings; use a new revision ID')
        _, _, manifest = _verify_package(controller, existing)
        return dict(batch_id=batch_id, package=str(package), manifest=manifest, reused=True, native_started='launch_intent' in existing)
    if scope is not None and snapshot['queue']:
        from studio_research_retry import predecessor
        # Read-only preflight before staging; store rechecks under its gate/CAS.
        predecessor(controller.store.db,snapshot,scope)
        controller.runtime(require_idle=True,expected_batch_ongoing=False)
        from studio_monitor_probe import inspect_idle_demo
        from studio_rejected_monitor import require_demo
        require_demo(inspect_idle_demo(controller))
    if snapshot['owner'] != 'agent': raise ValueError('Current controller required: human must Give to Agent first')
    if package.exists(): raise ValueError('Unqueued preparation artifacts exist; preserve them and choose a new batch ID')
    # Stage every native artifact before queue publication. The original snapshot
    # revision and generation prevent a later ownership change from authorizing it.
    job = dict(job_id=batch_id, configuration=config, configuration_sha256=sha(config), source_revision=snapshot['revision'])
    binding = controller.binding()
    registry = controller.root / 'templates.sqlite'
    db = connect(registry)
    planned, sources = [], []
    now = datetime.now(timezone.utc).isoformat()
    try:
        for member, (source, raw, info) in zip(checked, retained):
            template = sha(str(source)); revision = sha([template, info['sha256']])
            db.execute('INSERT OR IGNORE INTO templates VALUES(?,?,?)', (template, str(source), now))
            db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?,?,?,?,?,?)',
                (revision, template, info['sha256'], info['canonical_sha256'], info['ea_desc'], raw, info['canonical_json'], '{}', now))
            tester = member['tester']
            planned.append(dict(template_id=template, revision_id=revision, source_sha256=info['sha256'], symbol=tester['Symbol'],
                conditions=dict(ea_sha256=binding['ea_sha256'], from_date=tester['FromDate'], to_date=tester['ToDate'],
                    algorithm='FG', model=tester['Model'], remote_agents=False, cloud_agents=False,
                    leverage=tester['Leverage'], deposit=tester['Deposit'], currency=tester['Currency'],
                    timeframe=tester['Period'], forward_mode=4, execution_mode=tester['ExecutionMode'])))
            sources.append(dict(set_path=str(source), set_sha256=info['sha256'], symbol=tester['Symbol'],
                template_id=template, revision_id=revision))
        db.commit()
    finally:
        db.close()
    exports = checked[0]['export']
    plan = dict(schema_version=1, execution_authorized=False, max_attempts_per_job=1,
        research_binding=binding, studio_source=dict(terminal_id=controller.terminal, run_id=controller.run,
            job_id=batch_id, source_revision=job['source_revision'], configuration_sha256=job['configuration_sha256']),
        native_batch=dict(export_end_policy='native_last_friday_record_actual', back_oos_date=exports['BackOOSDate'],
            forward_start=checked[0]['tester']['ForwardDate'], export_settings=exports), jobs=planned)
    if evidence is not None:
        plan['native_batch']['evidence_end'] = evidence
    plan['native_batch']['run_relative'] = native_run_relative(plan)
    package.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='goat-batch-plan-') as temporary:
        source_plan = Path(temporary) / 'plan.json'; write_json(source_plan, plan)
        manifest = prepare(source_plan, registry, package)
    write_json(package / 'studio-plan.json', plan)
    write_json(package / 'customer-plan.json', spec)
    write_json(controller.root / 'packages' / (batch_id + '.source.json'), dict(batch_id=batch_id, members=sources))
    write_json(package / 'preparation.json', dict(schema_version=1, configuration_sha256=sha(config), files=_files(package)))
    _verify_package(controller, job)
    from studio_batch_seal import write as write_seal
    write_seal(package, job, controller.schema)
    request = dict(schema_version=1, request_id=batch_id + '-batch', terminal_id=controller.terminal, run_id=controller.run,
        expected_revision=snapshot['revision'], generation=snapshot['generation'], command='queue.enqueue_batch', payload=dict(job_id=batch_id, members=raw_members))
    request_path = controller.root / 'requests' / (request['request_id'] + '.json')
    if request_path.exists(): raise ValueError('Prior batch request retained; inspect it and choose a new batch ID')
    write_json(request_path, request)
    try:
        controller.store.submit(request, actor='agent')
    except Exception as exc:
        raise ValueError('Prepared package retained; queue publication was not confirmed. Inspect queue state and use a new ID after reconciling ownership/revision: ' + str(exc)) from exc
    controller.bridge.pump()

    return dict(batch_id=batch_id, member_count=len(planned), package=str(package), manifest=manifest, evidence_end=evidence,
        native_started=False, next_action=_start_next_action(controller, batch_id))


def _start_next_action(controller, batch_id):
    if (getattr(controller, 'session', None) or {}).get('authority_kind') == 'native_human_control':
        # Raw start is refused here: an in-place Start never makes MT5 write the batch reports.
        return ('Review settings with the user, tell them GOAT closes and reopens their MT5 to start the batch, then after '
                'their yes run run-batch --job-id ' + batch_id + ' --max-seconds <budget> --mt5-restart-consent; '
                'Studio runs the entire native queue')
    return 'Review settings and use start --job-id with this batch ID; Studio runs the entire native queue'


def save_batch(controller, batch_id, output):
    job = controller.job(batch_id)
    package, plan, manifest = _verify_package(controller, job)
    output = Path(output).resolve()
    if output.is_relative_to(controller.root.resolve()):
        raise ValueError('Save outside controller state to preserve immutable packages and evidence')
    if output.suffix.lower() != '.goatbatch':
        raise ValueError('Choose a new .goatbatch filename')
    raw = (package / 'portfolio.goatbatch').read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(raw)
    return dict(path=str(output), sha256=hashlib.sha256(raw).hexdigest(), members=len(manifest['jobs']),
        state='saved_unstarted_native_batch', source_batch_id=batch_id)


def batch_status(controller, batch_id):
    job = controller.job(batch_id)
    if 'launch_intent' in job and job['status'] not in ('completed', 'failed', 'cancelled'):
        controller.reconcile(batch_id)
        job = controller.job(batch_id)
    members = job['configuration'].get('batch_members', [job['configuration']])
    extra = {}
    observed = (job.get('native_observation') or {}).get('native') or (job.get('completion') or {}).get('native')
    if isinstance(observed, dict) and observed.get('status') == 'native_error' and 'launch_intent' in job:
        from studio_native_diagnostics import for_job
        # The EA journal says why the native queue ended in Error (read-only quote).
        no_edge = [item.get('index') for item in (job.get('completion') or {}).get('research_outcomes') or [] if isinstance(item, dict)]
        extra['native_error_evidence'] = for_job(controller, job, observed, no_edge)
    evidence = None
    plan_path = controller.root / 'packages' / batch_id / 'studio-plan.json'
    if plan_path.is_file():
        try:
            evidence = (_json(plan_path).get('native_batch') or {}).get('evidence_end')
        except (OSError, ValueError):
            evidence = None
    return dict(batch_id=batch_id, status=job['status'], member_count=len(members), evidence_end=evidence, **extra,
        native=job.get('native_observation'), result_path=job.get('completion_path'),
        members=[dict(index=index, symbol=member['tester']['Symbol'], timeframe=member['tester']['Period'],
            ea_desc=member['strategy']['values']['EA_Desc'], configuration_sha256=sha(member)) for index, member in enumerate(members)],
        configuration_sha256=job['configuration_sha256'],
        # Tested with no profitable settings in their window: results, not failures.
        research_outcomes=(job.get('completion') or {}).get('research_outcomes'))


def _section(text, name):
    opening, closing = '[' + name + ']', '[/' + name + ']'
    if text.count(opening) != 1 or text.count(closing) != 1:
        raise ValueError('Missing or duplicate native batch section: ' + name)
    return text.split(opening, 1)[1].split(closing, 1)[0].strip('\r\n')


def load_batch(controller, batch_id, source):
    """Import a saved native batch as a new, unstarted customer batch.

    Saved process/account paths and recorded execution states never authorize a
    launch here; the current installation and ownership are authoritative.
    """
    source = Path(source).resolve()
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Saved batch exceeds 128 MiB')
    with source.open('rb') as stream: raw = stream.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024: raise ValueError('Saved batch exceeds 128 MiB')
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    exports_text = _section(text, 'GOAT_EXPORT_SETTINGS')
    parser = configparser.ConfigParser(interpolation=None, strict=True); parser.optionxform = str
    parser.read_string(exports_text)
    if parser.defaults() or parser.sections() != ['Export']:
        raise ValueError('Unexpected export settings in saved batch')
    export = {}
    from studio_evidence_end_export import saved_value
    saved_evidence_end = saved_value(dict(parser['Export']))
    for key, value in ((k, v) for k, v in parser['Export'].items() if k != 'EvidenceEnd'):
        if key in ('AdjustLots', 'IncludeBackOOS', 'IncludeSequenceData'):
            if value not in ('0', '1'):
                raise ValueError('Invalid saved export boolean')
            export[key] = value == '1'
        elif key == 'BackOOSDate': export[key] = value
        elif key == 'SetsToExport': export[key] = int(value)
        else: export[key] = float(value)
    legacy_sequence_default = 'IncludeSequenceData' not in export
    export.setdefault('IncludeSequenceData', True)
    from studio_settings import FIELDS
    members, buffers, aliases = [], [], set()
    for block in _section(text, 'GOAT_QUEUE').split('\x1f'):
        if not block.strip(): continue
        lines = block.strip().splitlines()
        match = re.fullmatch(r';(Pending|Queued|OnGoing|Completed|Error|Cancelled)_[^;\r\n]+:([^;\r\n]+);', lines[0])
        if not match: raise ValueError('Invalid saved native queue header')
        alias = match[2]
        if alias in aliases: raise ValueError('Duplicate saved batch input identity')
        aliases.add(alias)
        parser = configparser.ConfigParser(interpolation=None, strict=True); parser.optionxform = str
        parser.read_string('\n'.join(lines[1:]))
        if parser.defaults() or parser.sections() != ['Tester']:
            raise ValueError('Invalid saved tester configuration')
        native = dict(parser['Tester'])
        ignored = {'Report', 'ReplaceReport', 'ShutdownTerminal'}
        if set(native) - FIELDS - ignored or FIELDS - set(native):
            raise ValueError('Saved tester fields are incomplete or unsupported')
        tester = {key: native[key] for key in FIELDS}
        for key in ('Model', 'ExecutionMode', 'Optimization', 'OptimizationCriterion', 'ForwardMode', 'UseLocal', 'UseRemote', 'UseCloud', 'Visual'):
            tester[key] = int(tester[key])
        tester['Deposit'] = float(tester['Deposit'])
        if tester['Expert'] != controller.install['ea_relative_path']:
            raise ValueError('Saved batch was built for a different EA; migrate explicitly before importing')
        input_text = _section(text, 'GOAT_INPUT:' + alias) if '[GOAT_INPUT:' + alias + ']' in text and '[/GOAT_INPUT:' + alias + ']' in text else None
        # Native packages use an alias-specific opening and generic closing.
        if input_text is None:
            opening = '[GOAT_INPUT:' + alias + ']'
            if text.count(opening) != 1: raise ValueError('Missing or duplicate saved input block')
            rest = text.split(opening, 1)[1]
            if '[/GOAT_INPUT]' not in rest: raise ValueError('Unterminated saved input block')
            input_text = rest.split('[/GOAT_INPUT]', 1)[0].strip('\r\n')
        set_raw = b'\xff\xfe' + (input_text + '\r\n').encode('utf-16-le')
        members.append(dict(tester=tester, export=export, strategy=dict(schema_hash=sha(controller.schema), values=read_values(set_raw))))
        buffers.append(set_raw)
    validate_batch_members(members, controller.schema, controller.policy)
    imported = controller.root / 'batch-imports' / uuid.uuid4().hex
    imported.mkdir(parents=True)
    plan_members = []
    for index, (member, set_raw) in enumerate(zip(members, buffers)):
        set_path = imported / f'{index + 1:05d}.set'; set_path.write_bytes(set_raw)
        plan_members.append(dict(set_path=str(set_path), tester=member['tester']))
    plan_path = imported / 'plan.json'
    imported_plan = dict(schema_version=1, export=export, members=plan_members)
    if saved_evidence_end is not None:
        # A saved EvidenceEnd is revalidated at prepare; it never bypasses the closed-day rule.
        imported_plan['evidence_end'] = saved_evidence_end
    write_json(plan_path, imported_plan)
    write_json(imported / 'provenance.json', dict(source_path=str(source), source_sha256=hashlib.sha256(raw).hexdigest(),
        imported_as_new_batch=True, prior_states_do_not_authorize_execution=True))
    result = prepare_batch(controller, batch_id, plan_path)
    if legacy_sequence_default:
        result['warnings'] = ['Saved batch omitted IncludeSequenceData; V1.48 defaults it to true. Review the additional capture time and storage before starting.']
    return result


def resume_batch(controller, source_batch_id, batch_id, *, include_failed=False, include_no_edge=False,
                 allow_peer_refresh=False, allow_binding_change=False, now=None):
    """Create a new native queue containing explicitly selected unfinished work.

    `include_failed` retries real failures; members tested with no profitable
    settings are results, so only `include_no_edge` deliberately re-runs them.
    """
    previous = controller.job(source_batch_id)
    if previous['status'] not in ('completed', 'cancelled', 'failed'):
        raise ValueError('Stop/reconcile/finish the original batch before preparing its remaining work')
    package, source_plan, manifest = _verify_package(controller, previous, allow_peer_refresh=allow_peer_refresh,
                                                     allow_binding_change=allow_binding_change)
    current_binding = controller.binding()
    changed_keys = sorted(key for key in set(source_plan['research_binding']) | set(current_binding)
                          if source_plan['research_binding'].get(key) != current_binding.get(key))
    from studio_native_observe import observe
    # A start retired before activation never reached MT5: every member is unstarted.
    never_activated = (previous['status'] == 'cancelled'
                       and (previous.get('completion') or {}).get('kind') == 'retired_never_activated')
    if 'launch_intent' not in previous or never_activated:
        if previous['status'] != 'cancelled': raise ValueError('Unstarted remaining work requires an explicit cancelled batch')
        observed = [dict(run_alias=member['run_alias'], status='native_cancelled') for member in manifest['jobs']]
    else:
        observation = observe(package)
        observed = observation.get('members') or observation.get('jobs')
    if not isinstance(observed, list) or len(observed) != len(manifest['jobs']):
        raise ValueError('Complete per-member native evidence required for remaining-work selection')
    from studio_batch_contract import configuration_members
    configurations = configuration_members(previous['configuration'])
    if len(configurations) != len(manifest['jobs']): raise ValueError('Remaining-work configuration count mismatch')
    # Members tested with no profitable settings are results for their window, not
    # failures: retrying failures never re-runs them (finish recorded them); only the
    # explicit include_no_edge override does.
    no_edge = {item['index'] for item in (previous.get('completion') or {}).get('research_outcomes') or []
               if isinstance(item, dict) and type(item.get('index')) is int}
    selected, retries = [], []
    for index, (native, config, evidence) in enumerate(zip(manifest['jobs'], configurations, observed)):
        if evidence.get('run_alias') != native['run_alias']:
            raise ValueError('Remaining-work identity mismatch')
        status = evidence['status'].lower().removeprefix('native_')
        if status == 'completed': continue
        if status == 'error' and index in no_edge and not include_no_edge: continue
        if status == 'error' and index not in no_edge and not include_failed: continue
        if status not in ('pending', 'queued', 'cancelled', 'error'):
            raise ValueError('Native member remains unresolved; do not infer stopped from process absence')
        # Never-run members first, then the opted-in failure retries.
        (retries if status == 'error' else selected).append(
            dict(set_path=str(package / (native['run_alias'] + '.set')),
                 # Across a build change the successor targets this installation's EA; its
                 # inputs are then validated against this build's schema by prepare_batch.
                 tester=config['tester'] | ({'Expert': controller.install['ea_relative_path']}
                                           if allow_binding_change else {})))
    selected += retries
    if not selected: raise ValueError('No unfinished members selected')
    inputs = controller.root / 'batch-imports' / uuid.uuid4().hex; inputs.mkdir(parents=True)
    plan_path = inputs / 'remaining.json'
    remaining = dict(schema_version=1, export=previous['configuration']['export'], members=selected)
    recorded = ((_json(package / 'studio-plan.json').get('native_batch') or {}).get('evidence_end')
                if (package / 'studio-plan.json').is_file() else None)
    if isinstance(recorded, dict) and isinstance(recorded.get('target'), str):
        # The successor keeps the original batch's resolved date: "auto" must not move to a later Friday.
        remaining['evidence_end'] = recorded['target']
    write_json(plan_path, remaining)
    result = prepare_batch(controller, batch_id, plan_path, now=now)
    write_json(inputs / 'provenance.json', dict(source_batch_id=source_batch_id, new_batch_id=batch_id,
        include_failed=include_failed, include_no_edge=include_no_edge, selected_count=len(selected),
        never_run_count=len(selected) - len(retries), retry_count=len(retries),
        no_edge_members=len(no_edge), source_binding_sha256=sha(source_plan['research_binding']),
        binding_sha256=sha(current_binding), binding_changed_keys=changed_keys,
        expert=controller.install['ea_relative_path'] if allow_binding_change else None))
    return result
