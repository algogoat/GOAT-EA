"""Translate one immutable Studio job to the existing non-activating packager.

Staging is not launch permission. A future runner must claim the current job and
reconcile native ownership immediately before activation, never launch this
possibly stale package solely because its files exist.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from campaign_ledger import sha
from prepare_native_campaign import native_run_relative, prepare
from studio_settings import validate_tester, validate_export
from studio_strategy_settings import read_values


def stage_job(store, terminal_id, run_id, job_id, registry_path, revision_id, binding, output, *, allow_identity_alias=False):
    state = store.snapshot(terminal_id, run_id)
    job = next((j for j in state['queue'] if j['job_id'] == job_id), None)
    if job is None or job['status'] != 'pending':
        raise ValueError('Existing pending Studio job required')
    config = job['configuration']
    if sha(config) != job['configuration_sha256']:
        raise ValueError('Frozen configuration hash mismatch')
    tester = validate_tester(config['tester'])
    exports = validate_export(config['export'], tester)
    if tester['ForwardMode'] != 4:
        raise ValueError('Native export packager currently requires custom forward')
    if tester['Expert'] != binding['ea_relative_path']:
        raise ValueError('Job expert differs from research binary binding')
    with closing(sqlite3.connect(Path(registry_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row = db.execute('SELECT template_id,sha256,source_bytes FROM revisions WHERE revision_id=?',
                         (revision_id,)).fetchone()
    if row is None or hashlib.sha256(row[2]).hexdigest() != row[1]:
        raise ValueError('Missing or corrupt registry revision')
    retained = read_values(row[2])
    queued = config['strategy']['values']
    compared = queued | {'EA_Desc':retained['EA_Desc']} if allow_identity_alias else queued
    if retained != compared:
        raise ValueError('Registry SET does not exactly match queued strategy inputs')
    # One native package per job retains its own export policy and custom window.
    plan = dict(schema_version=1,execution_authorized=False,max_attempts_per_job=1,
        research_binding=dict(binding),
        studio_source=dict(terminal_id=terminal_id,run_id=run_id,job_id=job_id,
                           source_revision=job['source_revision'],configuration_sha256=job['configuration_sha256']),
        native_batch=dict(export_end_policy='native_last_friday_record_actual',
                          back_oos_date=exports['BackOOSDate'],forward_start=tester['ForwardDate'],
                          export_settings=exports),
        jobs=[dict(template_id=row[0],revision_id=revision_id,source_sha256=row[1],symbol=tester['Symbol'],
                   conditions=dict(ea_sha256=binding['ea_sha256'],from_date=tester['FromDate'],
                                   to_date=tester['ToDate'],algorithm='FG',model=tester['Model'],
                                   remote_agents=False,cloud_agents=False,leverage=tester['Leverage'],
                                   deposit=tester['Deposit'],currency=tester['Currency'],
                                   timeframe=tester['Period'],forward_mode=4,execution_mode=tester['ExecutionMode']))])
    if retained != queued:
        plan['studio_source']['identity_alias'] = dict(registry=retained['EA_Desc'], queued=queued['EA_Desc'], trading_inputs_unchanged=True)
    plan['native_batch']['run_relative'] = native_run_relative(plan)
    with tempfile.TemporaryDirectory(prefix='goat-studio-stage-') as temporary:
        plan_path=Path(temporary)/'plan.json'
        plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
        receipt=prepare(plan_path,registry_path,output)
    (Path(output)/'studio-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    return dict(plan=plan,receipt=receipt,observed_revision=state['revision'],launch_permitted=False,
                limitation='No execution claim or source-to-binary attestation; revalidate before activation')
