"""Observe bound back/forward report evidence without qualifying or releasing a job."""
from decimal import InvalidOperation
import hashlib
import json
from pathlib import Path, PureWindowsPath
import xml.etree.ElementTree as ET
from campaign_ledger import sha
from studio_report_paths import report_paths
from verify_native_reports import verify_pair, read_report
from studio_export_scan import scan_exports
from studio_batch_contract import configuration_members


def observe_reports(package, configuration, schema=None, member_statuses=None):
    package = Path(package)
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    plan = json.loads((package / 'studio-plan.json').read_text(encoding='utf-8'))
    if (manifest['campaign_id'] != sha(plan)
            or plan['studio_source']['configuration_sha256'] != sha(configuration)):
        raise ValueError('Report package/configuration binding mismatch')
    members=configuration_members(configuration)
    if len(members)!=len(manifest['jobs']):raise ValueError('Report/frozen member count mismatch')
    if member_statuses is not None and (not isinstance(member_statuses,list) or len(member_statuses)!=len(members)):
        raise ValueError('Complete native member status coverage required')
    results=[]
    for index,member in enumerate(members):
        native_status=member_statuses[index] if member_statuses is not None else 'native_completed'
        if native_status=='native_completed':
            observed=_observe_member(package,plan,manifest,member,schema,index)
        else:
            observed=dict(status='member_not_completed',native_status=native_status,export_qualification='not_evaluated')
        results.append(observed|dict(index=index,run_alias=manifest['jobs'][index]['run_alias'],symbol=member['tester']['Symbol']))
    if len(results)==1:return results[0]
    verified=all(item['status']=='report_pair_verified' or (item['status']=='member_not_completed' and item['native_status'] in ('native_cancelled','native_error')) for item in results)
    return dict(status='report_batch_verified' if verified else 'batch_reports_pending',members=results,
                member_count=len(results),verified_completed_count=sum(item['status']=='report_pair_verified' for item in results),
                launch_permitted=False,retry_permitted=False,release_permitted=False,
                export_qualification='Per-member native evidence; independent portfolio import verification required')


def _observe_member(package,plan,manifest,configuration,schema,index):
    paths = report_paths(plan, manifest, index)
    tester = configuration['tester']
    axes = sorted(configuration['strategy']['axes'])
    title = (f"{PureWindowsPath(tester['Expert']).stem} {tester['Symbol']},{tester['Period']} "
             f"{tester['FromDate']}-{tester['ToDate']}")
    reports = [paths['common_back'], paths['common_forward']]
    result = dict(status='reports_pending', expected_paths=[str(p) for p in reports],
                  launch_permitted=False, retry_permitted=False, release_permitted=False,
                  export_qualification='not_evaluated')
    # Native frame deinit migrates reports to Common Files. Never substitute an
    # unrelated report or treat a missing/partial migration as zero qualifiers.
    missing = [str(p) for p in reports if not p.is_file()]
    if missing:
        return result | dict(missing=missing)
    try:
        evidence = verify_pair(*reports, title, axes)
        # A producer may still be finishing migration; changed bytes invalidate
        # this observation. Retain hashes so later reconciliation notices drift.
        for artifact in evidence['artifacts']:
            if hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
                return result | dict(status='reports_changing')
    except (OSError, ValueError, InvalidOperation, ET.ParseError) as exc:
        return result | dict(status='reports_unverified', reason=str(exc))
    exports = dict(status='trusted_schema_required', qualified_count=None, release_permitted=False)
    if schema is not None and sha(schema) == configuration['strategy']['schema_hash']:
        native_job = manifest['jobs'][index]
        source_path = paths['common_run']/'inputs'/native_job['run_alias']/'Inputs.GOAT'
        source_raw = source_path.read_bytes()
        if hashlib.sha256(source_raw).hexdigest() != native_job['staged_sha256']:
            raise ValueError('Export source input drift')
        back = read_report(reports[0], title, axes, False)
        forward = read_report(reports[1], title, axes, True)
        if [back['sha256'], forward['sha256']] != [a['sha256'] for a in evidence['artifacts']]:
            return result | dict(status='reports_changing')
        if configuration['export']['AdjustLots']:
            exports = dict(status='adjusted_lot_provenance_required', qualified_count=None, release_permitted=False)
        else:
            exports = scan_exports(paths['common_run']/'deploy'/native_job['run_alias']/tester['Symbol'],
                source_raw, schema, back['passes'], forward['passes'], alias=native_job['run_alias'],
                symbol=tester['Symbol'], period=tester['Period'], expert_name=PureWindowsPath(tester['Expert']).stem,
                min_arf=configuration['export']['MinARF'], min_sr=configuration['export']['MinSR'])
    return result | dict(status='report_pair_verified', evidence=evidence, exports=exports,
                         remaining=['runtime/config acceptance', 'journal coverage', 'export qualification'])
