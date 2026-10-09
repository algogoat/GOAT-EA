"""OOS catch-up: bring kept exports to one evidence end with one non-optimized pass each.

An export's evidence ends where its export test ended. Exports made in different
weeks therefore end on different dates, and a portfolio built from them mixes
timelines. Catch-up re-tests each stale export's frozen values (its exact kept SET,
no optimization) from the export's original start to the new evidence end, then
judges only the newly added days (studio_catchup_verdict).

Never overwrites the original export. The re-test is a new evidence version with
the same values identity (``values_sha256``) and a later end date, stored under
``<controller state>\\evidence\\c.<10 hex of SHA-256(catch-up id)>\\<member number>\\`` with its own
``evidence-version.json`` that links back to the original. The folder's ``catchup.json`` records the
readable catch-up ID and each member's alias. The path is bounded whatever the ID: the longest file
below a member folder is len(state root) + 168 characters; past the Windows limit the controller uses
the \\\\?\\ extended-length form (MT5 never opens these folders). Catch-ups prepared before this layout
keep ``evidence\\<catch-up id>\\<alias>\\`` and are read as they are.

How it runs natively (no EA change): the native Studio queue only runs
optimizations, so catch-up reuses the SeedRunner process driver. Each member is
one MT5 start with a /config INI (Optimization=0, Model=4, ShutdownTerminal=1,
ToDate = evidence end + 1 day) whose [TesterInputs] are the frozen values plus
the EA's own export metadata (``EA_Desc=<alias>@{mode=EXPORT,...}`` and the
``Sequence_Export_*`` inputs the EA's RunAndStoreSet passes). The EA then writes
the same SET/CSV/.goatseq unit it writes for a batch export, into
``Common Files\\TEMP\\SQ\\<token>``; the runner moves it into the evidence store.
The close/relaunch cycle is the seed driver's and shares its terminal slot, so it
is ``native_launch_qualified: false`` until a native proof run.

Same-model rule (#1885, Claude-Mac APPROVE): a re-test uses the export's own tester
model (the capture's ``model``; without a capture, the EA's export pass, which every
build since V1.35 forces to real ticks, Model 4). Models 0, 1, 2 and 4 are accepted;
the sequence capture only runs on Model 4, so other models re-test without it. Every
verdict carries ``evidence_model`` (studio_catchup_verdict.model_tag): the model, the
timeframe, the model rung and the trade-list summary, for the library scorer.

Build rule: the re-test runs on the installed EA. It is comparable when that is the
export's own build (same binary, or the same build id; the installed build comes from its binary through
the pinned build table, studio_installed_build), or when the plan names
an ACTIVE trading-equivalence certificate (studio_equivalence) for exactly this export
build and this installed build. A canary plan (``canary_certificate``) runs a pending
certificate's export build on purpose: its verdicts stay ``not_comparable``; its deal
lists are what ``equivalence-canary-ingest`` compares.

Build migration (``build_migration``, goatai#2350, studio_build_migration): re-tests SETs of an older build
on the installed build on purpose, only when the installed build is the plan's ``target_build`` and every SET
names its source build and exact original. Its members write a ``build_migration_retest`` record, never an
evidence version or a verdict; every reader here checks the kind. Normal catch-ups keep refusing cross-build.

Output root (``output_root``): an absolute local folder for the evidence folders instead of
``<controller state>\\evidence``. Same layout and the same create-only, atomic moves; the root is recorded
in ``evidence-roots.json`` so ``versions`` still finds the catch-up evidence written there.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import time
import uuid

from campaign_ledger import sha
from studio_bridge import write_json
from studio_evidence import RunContext, read_export, read_json_bounded, scan, server_date, server_msc, weekdays
from studio_catchup_verdict import CAVEAT, model_tag, validate_rules
import studio_build_migration as migration
import studio_equivalence as equivalence
import studio_evidence_end as evidence_end
import studio_installed_build as installed_build
from studio_seed import SeedRunner, digest
from studio_seed_results import MAX_MANIFEST_BYTES, read_seed_json
from studio_strategy_settings import read_values
from studio_template_tools import validate_raw

MODE = 'OOSCatchup'
VERSION_SCHEMA = 'goat-evidence-version-v1'
PLAN_KEYS = {'schema_version', 'evidence_end', 'sets', 'job_timeout_seconds'}
PLAN_OPTIONAL = {'broker_clock', 'assume', 'include_below_threshold', 'verdict_rules',
                 # Library scoring v1 (goatai#2221): one strategy_ref (or null) per set, and the
                 # held-out lock this plan reveals (only its frozen candidate, while revealing).
                 'strategy_refs', 'heldout_reveal',
                 # Same-model rule and trading-equivalence certificates (#1885, GOAT-EA#141).
                 'equivalence_certificates', 'canary_certificate',
                 # goatai#2350: re-test an older build's SETs on the installed target build (studio_build_migration),
                 # and an absolute local folder for the evidence instead of <controller state>\evidence.
                 'build_migration', 'output_root'}
EVIDENCE_ROOTS = 'evidence-roots.json'
EVIDENCE_ROOTS_SCHEMA = 'goat-catchup-evidence-roots-v1'
MAX_EVIDENCE_ROOTS = 50
MAX_CERTIFICATES = 20
RETEST_MODELS = (0, 1, 2, 4)   # every tick, 1 minute OHLC, open prices, real ticks (3 = math calculations, no prices)
EXPORT_PASS_MODEL = 4          # the EA forces real ticks on its export pass (GOAT V1.35+: strT.Model="4")


def export_model(export):
    """The tester model of an export's own test, with where that comes from."""
    capture = export.get('capture') or {}
    if type(capture.get('model')) is int:
        return capture['model'], 'capture'
    return EXPORT_PASS_MODEL, 'ea_export_pass'


MAX_MEMBERS = 2000
MAX_PUBLIC = 100
OUTPUT_PATH_ROOM = 140  # longest EA export file name below a member folder, plus margin
OP_STANDARD = '9'
# Windows paths (goatai#1885 6008582393). MT5 and the EA are not long-path aware, so every path they read or
# write stays under MAX_PATH as a plain path. Controller-only folders (catchups\<id>, evidence\<folder>) use the
# \\?\ extended-length form for IO when their worst case would pass it, so a long Windows user name never blocks
# a catch-up.
MAX_PATH = 259           # longest plain Windows path (MAX_PATH 260 includes the terminating NUL)
MAX_ID = 80              # CatchupRunner.path: 1..80 letters/digits/underscore/hyphen
CATCHUP_FILE_ROOM = 72   # longest file name in catchups\<id>: <alias>.result.json plus write_json's .<32 hex>.tmp
MEMBER_FOLDER_DIGITS = 5
EVIDENCE_FOLDER_SCHEMA = 'goat-catchup-evidence-folder-v1'
EVIDENCE_FOLDER_RECORD = 'catchup.json'
WINDOWS = os.name == 'nt'


def evidence_key(catchup_id):
    """Short, stable evidence folder name for one catch-up ID: ``c.`` + 10 hex of SHA-256(id), 12 characters.

    A catch-up ID never contains ``.``, so a hashed folder can never be a legacy ``evidence\\<catch-up id>``
    folder. The readable ID is recorded in ``catchup.json`` inside it (and in every evidence-version.json).
    """
    return 'c.' + hashlib.sha256(catchup_id.encode('utf-8')).hexdigest()[:10]


def member_folder(index):
    """Evidence folder of member ``index`` (0-based): its 1-based number, 5 digits (the alias suffix)."""
    return str(index + 1).zfill(MEMBER_FOLDER_DIGITS)


def io_path(path, room=0, *, windows=None):
    """``path`` for IO: the \\\\?\\ extended-length form on Windows when ``path`` plus ``room`` passes MAX_PATH."""
    path = Path(os.path.abspath(path))
    if (WINDOWS if windows is None else windows) and len(str(path)) + room > MAX_PATH:
        from studio_handover import filesystem_path
        return filesystem_path(path)
    return path


def plain(path):
    """The display form of a path that may carry the \\\\?\\ prefix."""
    text = str(path)
    if text.startswith('\\\\?\\UNC\\'):
        return '\\\\' + text[8:]
    return text[4:] if text.startswith('\\\\?\\') else text


def evidence_worst_case(controller_root, evidence_root=None):
    """Longest path under a catch-up member's evidence folder, plain: independent of the catch-up ID.

    ``<state root>\\evidence\\c.<10 hex>\\<5 digits>\\`` + OUTPUT_PATH_ROOM = len(state root) + 168
    (with an ``output_root``: len(output root) + 159).
    """
    base = evidence_root if evidence_root is not None else Path(controller_root) / 'evidence'
    return len(os.path.abspath(base)) + 1 + 12 + 1 + MEMBER_FOLDER_DIGITS + OUTPUT_PATH_ROOM


def evidence_roots(controller_root):
    """Every evidence folder base: ``<controller state>\\evidence``, then each recorded ``output_root``."""
    bases = [Path(controller_root) / 'evidence']
    path = Path(controller_root) / EVIDENCE_ROOTS
    if not path.exists():
        return bases
    try:
        record = read_json_bounded(path)
    except (OSError, ValueError) as exc:
        # Fail closed: without the recorded roots, exports caught up there would read as behind again.
        raise ValueError('%s cannot be read (%s); catch-up evidence locations are unknown, so nothing is classified' % (path, exc)) from None
    if not isinstance(record, dict) or record.get('schema') != EVIDENCE_ROOTS_SCHEMA or not isinstance(record.get('roots'), list):
        raise ValueError('%s is not a %s record; catch-up evidence locations are unknown' % (path, EVIDENCE_ROOTS_SCHEMA))
    seen = {migration.key(bases[0])}
    for root in record['roots'][:MAX_EVIDENCE_ROOTS]:
        if isinstance(root, str) and Path(root).is_absolute() and not root.startswith(('\\\\', '//')) and migration.key(root) not in seen:
            seen.add(migration.key(root))
            bases.append(Path(root))
    return bases


def is_default_root(controller_root, root):
    return migration.key(os.path.abspath(root)) == migration.key(os.path.abspath(Path(controller_root) / 'evidence'))


def record_evidence_root(controller_root, root):
    """Add one ``output_root`` to ``evidence-roots.json`` (atomic replace), so ``versions`` reads it."""
    if is_default_root(controller_root, root):
        return   # the controller-state root is always read; never recorded twice
    roots = [str(p) for p in evidence_roots(controller_root)[1:]]
    if migration.key(root) in {migration.key(p) for p in roots}:
        return
    if len(roots) >= MAX_EVIDENCE_ROOTS:
        raise ValueError('At most %d catch-up output roots can be recorded; reuse one' % MAX_EVIDENCE_ROOTS)
    write_json(Path(controller_root) / EVIDENCE_ROOTS, dict(schema=EVIDENCE_ROOTS_SCHEMA, roots=roots + [str(root)]))


def catchups_worst_case(controller_root, catchup_id=None):
    """Longest controller file path in ``catchups\\<id>``: len(state root) + 10 + len(id) + 1 + CATCHUP_FILE_ROOM."""
    return len(os.path.abspath(Path(controller_root) / 'catchups')) + 1 + (len(catchup_id) if catchup_id else MAX_ID) + 1 + CATCHUP_FILE_ROOM


def evidence_folder(controller_root, catchup_id):
    """The evidence folder of one catch-up for reading: the hashed folder (under the controller state or a recorded
    output root), or a legacy ``evidence\\<id>`` one, else None."""
    base = Path(controller_root) / 'evidence'
    for root in evidence_roots(controller_root):
        hashed = io_path(root / evidence_key(catchup_id), 1 + MEMBER_FOLDER_DIGITS + OUTPUT_PATH_ROOM)
        try:
            record = read_json_bounded(hashed / EVIDENCE_FOLDER_RECORD)
            if isinstance(record, dict) and record.get('catchup_id') == catchup_id:
                return hashed
        except (OSError, ValueError):
            pass
    legacy = base / catchup_id
    return legacy if legacy.is_dir() else None
SAFE_SYMBOL = re.compile(r'[A-Za-z0-9_.# -]{1,64}')
STATUSES = ('behind', 'current', 'ahead', 'caught_up', 'ineligible')
UNJUDGED = ('not_comparable', 'unjudged')   # retained, but they do not put the export on the shared timeline


def attempt_token(capture_id):
    """GoatSeqAttemptRoot: first 8 bytes of SHA-256(id) in hex, under Common Files\\TEMP\\SQ."""
    return hashlib.sha256(capture_id.encode('utf-8')).hexdigest()[:16]


def _date(text):
    return datetime.strptime(text, '%Y.%m.%d').date()


def _mt5(day):
    return day.strftime('%Y.%m.%d')


def versions(controller_root, limit=20000):
    """Catch-up evidence versions retained under the controller state (and recorded output roots), newest end first.

    Build-migration records (``kind: build_migration_retest``) are never evidence versions: skipped by type.
    Fails closed when a recorded output root is unavailable (an unplugged drive): its exports would read as behind.
    """
    found = []
    for index, root in enumerate(evidence_roots(controller_root)):
        # Both layouts: evidence\c.<hash>\<member>\ and the legacy evidence\<catch-up id>\<alias>\ (room for the longest ID).
        base = io_path(root, 1 + MAX_ID + 1 + 23 + 1 + len('evidence-version.json'))
        if not base.is_dir():
            if index:
                raise ValueError('Catch-up output root %s (recorded in %s) is unavailable; reconnect it before reading catch-up '
                                 'evidence, or exports caught up there would read as behind' % (root, EVIDENCE_ROOTS))
            continue
        for path in sorted(base.glob('*/*/evidence-version.json')):
            try:
                record = read_json_bounded(path)
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get('schema') == VERSION_SCHEMA and not migration.is_record(record):
                found.append(record | dict(version_path=str(path)))
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    return sorted(found, key=lambda r: (r.get('evidence_end') or '', r.get('created_utc') or ''), reverse=True)


# A requalify re-test is a new candidate (studio_catchup_rebase): the original carries no status from it, so it
# never catches the original export up either. Its own evidence is the re-test (version_set_path).
UNCARRIED = UNJUDGED + ('requalify',)


VERSION_KIND = 'oos_catchup'


def build_identity(export):
    """The EA build that made an export: its capture's build ID, else ``ex5:<run manifest EA sha256>``, else None."""
    build_id = (export.get('capture') or {}).get('build_id')
    if build_id:
        return build_id
    ea = (export.get('run') or {}).get('ea_sha256')
    return 'ex5:' + ea if ea else None


def _version_key(record, *, version=True):
    """What a catch-up version must share with an export to carry it: values, symbol, period, start, the build that
    made the export it re-tested, and the record kind (goatai#2350 6070262354).

    A version names its original's build (``original.build``), so a catch-up of a build-migration re-test (made by
    the new build) never carries the older-build original it came from. Versions written before this field
    (none can descend from a build migration) carry only the exact SET they re-tested (``original.set_sha256``).
    """
    base = (record.get('values_sha256'), record.get('symbol'), record.get('period'), record.get('evidence_start'))
    if not version:   # an export row (classify)
        return base + (VERSION_KIND, record.get('build'))
    if migration.is_record(record) or record.get('kind', VERSION_KIND) != VERSION_KIND:
        return None
    original = record.get('original') or {}
    if 'build' in original:
        return base + (VERSION_KIND, original['build'])
    return base + (VERSION_KIND, ('legacy_exact_set', original.get('set_sha256')))


def _carries(version, row):
    """True when ``version`` is a catch-up of exactly this export (same key, same build or the very same SET)."""
    key = _version_key(version)
    if key is None or key[:5] != _version_key(row, version=False)[:5]:
        return False
    if isinstance(key[5], tuple):
        return key[5][1] is not None and key[5][1] == row.get('set_sha256')
    if key[5] is None or row.get('build') is None:   # unknown build on either side: None == None is not the same build
        sha = (version.get('original') or {}).get('set_sha256')   # (goatai#2350 6070608935) -> the exact-SET rule
        return sha is not None and sha == row.get('set_sha256')
    return key[5] == row.get('build')


def classify(export, target, *, include_below_threshold=False, known_versions=()):
    """Where one export stands against the target evidence end."""
    problems = list(export.get('problems') or [])
    end = export.get('evidence_end')
    row = dict(set_path=export['set_path'], member=export.get('member'), run_id=(export.get('run') or {}).get('run_id'),
               symbol=export.get('symbol'), period=export.get('period'), values_sha256=export['values_sha256'],
               evidence_start=export.get('evidence_start'), evidence_end=end, evidence_end_source=export.get('evidence_end_source'),
               threshold_passing=export['threshold']['passing'], threshold=export['threshold'], metrics=export.get('metrics'),
               capture_status=(export.get('capture') or {}).get('status'), history_short=export.get('history_short', False),
               build=build_identity(export), set_sha256=export.get('set_sha256'))
    # Re-test eligibility keeps the EA's own rounded comparison (GOAT minimum defaults for a library
    # copy); threshold_passing and the export's qualification stamp record whether it is proven.
    eligible = export['threshold'].get('retest_eligible', export['threshold']['passing'])
    if not eligible and not include_below_threshold:
        problems.append('Below the batch export thresholds (profit > 0, ARF >= %g, SR >= %g)'
                        % (export['threshold']['min_arf'], export['threshold']['min_sr']))
    if not end or not export.get('evidence_start'):
        problems.append('Evidence start or end unknown')
    if problems:
        return row | dict(status='ineligible', reasons=problems)
    target_day, end_day = date.fromisoformat(target), date.fromisoformat(end)
    # Only a catch-up version of this export's own build carries it (_version_key); a build-migration record is a
    # new-build re-test, never a catch-up of this export, and has no version key at all.
    mine = [v for v in known_versions if _carries(v, row) and (v.get('evidence_end') or '') >= target]
    # A not_comparable or unjudged re-test judged nothing, so it never carries the export forward; a re-queue may try again.
    match = [v for v in mine if (v.get('verdict') or {}).get('verdict') not in UNCARRIED]
    refused = [v for v in mine if v not in match]
    if refused:
        row['previous_attempt'] = dict(verdict=(refused[0].get('verdict') or {}).get('verdict'), version_path=refused[0]['version_path'],
                                       reasons=(refused[0].get('verdict') or {}).get('reasons'))
    if end_day < target_day and match:
        # A retained catch-up version already carries this export to (or past) the target.
        best = min(match, key=lambda v: v['evidence_end'])
        status = 'caught_up' if best['evidence_end'] == target else 'ahead'
        return row | dict(status=status, effective_end=best['evidence_end'], version_path=best['version_path'],
                          version_set_path=(best.get('retest') or {}).get('set_path'), verdict=(best.get('verdict') or {}).get('verdict'))
    if end_day < target_day:
        return row | dict(status='behind', effective_end=end, new_first_day=(end_day + timedelta(days=1)).isoformat(),
                          new_weekdays=weekdays(end_day + timedelta(days=1), target_day))
    if end_day == target_day:
        return row | dict(status='current', effective_end=end)
    return row | dict(status='ahead', effective_end=end, note='Ends after the target; the portfolio clips it to the shared end, no re-test needed')


def _n(count, noun):
    return '%d %s%s' % (count, noun, '' if count == 1 else 's')


def summarize(rows, target, *, resolved=None):
    """Counts per status, the distinct evidence ends, and one plain paragraph."""
    counts = {status: sum(r['status'] == status for r in rows) for status in STATUSES}
    ends = {}
    for row in rows:
        if row['status'] != 'ineligible':
            end = row.get('effective_end') or row['evidence_end']
            ends[end] = ends.get(end, 0) + 1
    consistent = counts['behind'] == 0 and counts['ahead'] == 0
    eligible = sum(counts[s] for s in STATUSES if s != 'ineligible')
    if consistent:
        plain = 'All %s end on %s.' % (_n(eligible, 'eligible export'), target) if eligible else 'No eligible exports.'
    else:
        plain = ('%s end before %s and need a catch-up re-test; %d already end there; %d end later and are clipped to it, not re-tested.'
                 % (_n(counts['behind'], 'export'), target, counts['current'] + counts['caught_up'], counts['ahead']))
    auto = (resolved or {}).get('auto') if (resolved or {}).get('mode') == 'auto' else None
    if counts['ahead'] and auto:
        plain += (' The exports that end later already include days of the unfinished week; after this week closes (%s, %s UTC) '
                  'auto moves to %s and everything can be brought there.' % (auto['next_date'], auto['next_switch_utc'], auto['next_date']))
    if counts['ineligible']:
        plain += ' %s ineligible (see reasons).' % ('1 is' if counts['ineligible'] == 1 else '%d are' % counts['ineligible'])
    return dict(counts=counts, evidence_ends=dict(sorted(ends.items())), consistent=consistent, plain=plain)


def resolve_target(value='auto', *, broker_clock=None, now=None):
    """Catch-up's evidence end: auto (closed Friday), auto_day (latest closed trading day) or an explicit closed day.

    Evidence for live decisions runs to the latest closed day (goatai#1885 6008215775), so catch-up alone
    accepts auto_day; the resolved date is recorded in the manifest and every result (evidenceEnd), and
    every run of one decision passes that same explicit date.
    """
    return evidence_end.resolve(value, now, clock=broker_clock or evidence_end.DEFAULT_CLOCK, allow_day=True)


def evidence_scan(sources, *, value='auto', broker_clock=None, now=None, controller_root=None, include_below_threshold=False):
    """Read-only inventory: every kept export under ``sources`` against one target end."""
    target = resolve_target(value, broker_clock=broker_clock, now=now)
    exports, unreadable = scan(sources)
    known = versions(controller_root) if controller_root else ()
    rows = [classify(e, target['iso'], include_below_threshold=include_below_threshold, known_versions=known) for e in exports]
    if controller_root:
        # Exports of a batch closed with batch-pause-close --mode exclude read ineligible with ``excluded`` set
        # (studio_batch_close); an unreadable exclusion marker refuses the scan rather than let them through.
        from studio_batch_close import apply_exclusions, exclusions
        rows = apply_exclusions(rows, exclusions(controller_root))
    return dict(schema_version=1, target=target, summary=summarize(rows, target['iso'], resolved=target), exports=rows, unreadable=unreadable,
                rules=dict(evidence_end=target['rule'], thresholds_applied_to_eligibility=not include_below_threshold,
                           thresholds='each export carries its own threshold, basis and margins'),
                writes=False, native_launch_qualified=False,
                next_action='catchup-prepare with the behind SETs re-tests them to %s; nothing runs until catchup-start' % target['iso'])


QUALIFICATION_SCHEMA = 'goat-qualification-inputs-v1'


def qualification_inputs(spec, manifest, verdict):
    """Everything a later scored, explained qualification needs, with the rules that produced it.

    Nothing is scored here: the export thresholds (and how far the export sits from each),
    the evidence-end rule, the verdict rules and the raw signals are recorded so another
    rule set can re-judge the same evidence without re-running MT5.
    """
    target = manifest['evidence_end']
    return dict(schema=QUALIFICATION_SCHEMA, scored=False,
                evidence_end=dict(rule=target['rule'], mode=target['mode'], requested=target['requested'], date=target['iso']),
                export_thresholds=spec['original'].get('threshold'),
                thresholds_applied_to_eligibility=not manifest.get('include_below_threshold', False),
                verdict_rules=verdict.get('rules') or manifest.get('verdict_rules'),
                signals=verdict.get('signals'), verdict=verdict.get('verdict'), confidence=verdict.get('confidence'),
                assumed=spec.get('assumed', []))


CATCH_UP_SCHEMA = 'goat-catch-up-import-v1'


def catch_up_stamp(spec, manifest, verdict, created_utc, original_foos=None):
    """What a desktop import writes on the strategy (``catchUp``): when these weeks were added.

    A portfolio chosen before ``added_at`` never saw these weeks; one built from a library
    that already held them saw them when choosing, so they are not an unseen test of it.
    ``original_foos`` is the original export's FOOS header window: the re-test's own FOOS
    runs through the new weeks, so the importer restores this one and keeps the new weeks
    only in ``catchUp``. A ``comparable_rebased`` or ``requalify`` re-test is different: the re-test is
    the evidence for every window (``windows``, ``windowsBasis: retest``) and ``original_foos`` is null,
    so nothing of the old export is spliced with the new weeks. ``historyBasis`` and
    ``tickHistoryDrift`` say which history the evidence rests on and how far the re-test drifted.
    """
    # The desktop import mapping reads only catch-up verdicts: a build-migration record never becomes a catchUp stamp.
    migration.refuse(verdict, 'The desktop catch-up import stamp')
    migration.refuse(spec.get('build_migration') or {}, 'The desktop catch-up import stamp')
    window = verdict.get('new_weeks') or {}
    # comparable_rebased / requalify (studio_catchup_rebase): the re-test is the evidence for every window, so the
    # importer must not restore the original FOOS and append new weeks: it takes ``windows`` (all on the re-test).
    rebased = verdict.get('comparison') in ('comparable_rebased', 'requalify')
    return dict(schema=CATCH_UP_SCHEMA, evidence_end=manifest['evidence_end']['iso'], added_at=created_utc,
                evidenceEnd=manifest['evidence_end']['iso'], evidenceEndMode=evidence_end.evidence_end_mode(manifest['evidence_end'], catch_up=True),
                evidenceEndEffective=evidence_end.effective_end(spec['tester']['ToDate']),
                comparison=verdict.get('comparison'), historyBasis=verdict.get('historyBasis'),
                tickHistoryDrift=verdict.get('tickHistoryDrift'), windowsBasis='retest' if rebased else 'original',
                windows=verdict.get('rebasedWindows') if rebased else None,
                candidate='new' if verdict.get('comparison') == 'requalify' else None,
                carriesStatus=verdict.get('comparison') in ('comparable', 'comparable_rebased'),
                original_end=spec['original']['evidence_end'], original_foos=None if rebased else original_foos,
                first_day=spec['new_window']['first_day'], last_day=window.get('last_day') or manifest['evidence_end']['iso'],
                verdict=verdict.get('verdict'), confidence=verdict.get('confidence'),
                comparable=(verdict.get('comparability') or {}).get('comparable'),
                rules=(verdict.get('rules') or manifest.get('verdict_rules') or {}).get('id'),
                original_set_sha256=spec['original']['set_sha256'], values_sha256=spec['original']['values_sha256'],
                model=(verdict.get('evidence_model') or {}).get('model'), timeframe=(verdict.get('evidence_model') or {}).get('timeframe'),
                model_rung=(verdict.get('evidence_model') or {}).get('model_rung'),
                m1_open_price_like=(verdict.get('evidence_model') or {}).get('m1_open_price_like'),
                fidelity_table_version=(verdict.get('evidence_model') or {}).get('fidelity_table_version'),
                equivalence_certificate=((spec.get('pins') or {}).get('equivalence') or {}).get('certificate_digest'),
                equivalence_canary=((spec.get('pins') or {}).get('equivalence') or {}).get('canary_digest'),
                equivalence_status_at_collect=((spec.get('pins') or {}).get('equivalence') or {}).get('status_at_collect'))

def _same_tree(source, target):
    """A copied file or folder holds exactly the source's files with the same SHA-256 each."""
    source, target = Path(source), Path(target)
    if source.is_file():
        return target.is_file() and digest(source) == digest(target)
    mine = sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file())
    theirs = sorted(p.relative_to(target) for p in target.rglob('*') if p.is_file())
    return mine == theirs and all(digest(source / p) == digest(target / p) for p in mine)


class _NoProcess:
    """Process stand-in for previews: any terminal effect is a defect."""
    def inspect(self):
        raise ValueError('Catch-up preview never inspects the terminal')

    def start(self, config):
        raise ValueError('Catch-up preview never starts the terminal')

    def close(self, identity):
        raise ValueError('Catch-up preview never closes the terminal')


def read_operation(controller, args, *, now=None):
    """The read-only CLI operations: evidence-end, evidence-scan, evidence-versions, catchup-validate."""
    clock = getattr(args, 'broker_clock', None)
    if args.operation == 'evidence-end':
        result = resolve_target(args.value, broker_clock=clock, now=now)
        local = getattr(controller, 'local', None)
        return result | dict(batch_exports_now=evidence_end.legacy_end(now, clock=clock or evidence_end.DEFAULT_CLOCK),
                             ea_evidence_end_setting=evidence_end.ea_capability(controller.install, Path(local) / 'ui-observation.json')
                             if local else None)
    if args.operation == 'evidence-scan':
        return evidence_scan([str(p) for p in args.source], value=args.evidence_end, broker_clock=clock, now=now,
                             controller_root=controller.root, include_below_threshold=args.include_below_threshold)
    if args.operation == 'evidence-versions':
        rows = versions(controller.root)
        if args.values_sha256:
            rows = [r for r in rows if r.get('values_sha256') == args.values_sha256]
        return dict(schema_version=1, count=len(rows), versions=rows[:MAX_PUBLIC], versions_omitted=max(0, len(rows) - MAX_PUBLIC))
    if args.operation == 'catchup-validate':
        from studio_batch import _json
        from studio_installation import read_json
        controller.session = read_json(Path(controller.root) / 'session.json')
        return CatchupRunner(controller, process=_NoProcess(), now=now).validate(_json(args.plan), getattr(args, 'catchup_id', None))
    raise ValueError('Not a read-only evidence operation: ' + args.operation)


def _tester_conditions(export, assume):
    """Original tester conditions for a single re-test, with provenance per field."""
    capture, tester, windows = export.get('capture') or {}, export.get('tester') or {}, export.get('windows') or {}
    facts, assumed, missing = {}, [], []
    for key, from_capture in (('Deposit', capture.get('initial_equity')), ('Currency', capture.get('currency')),
                              ('Leverage', '1:%d' % capture['leverage'] if type(capture.get('leverage')) is int else None)):
        value = tester.get(key, from_capture)
        if value is None:
            missing.append(key)
        facts[key] = value
    if 'ExecutionMode' in tester:
        facts['ExecutionMode'] = tester['ExecutionMode']
    elif isinstance(assume, dict) and type(assume.get('ExecutionMode')) is int:
        facts['ExecutionMode'] = assume['ExecutionMode']
        assumed.append('ExecutionMode')
    else:
        missing.append('ExecutionMode')
    window = dict(FromDate=tester.get('FromDate'), ToDate=tester.get('ToDate'), ForwardDate=tester.get('ForwardDate'), source='run_manifest')
    if not all(window[k] for k in ('FromDate', 'ToDate', 'ForwardDate')):
        sample, fwd = windows.get('SAMPLE'), windows.get('FWD')
        window = dict(FromDate=sample and _mt5(date.fromisoformat(sample['start'])), ToDate=fwd and _mt5(date.fromisoformat(fwd['end'])),
                      ForwardDate=fwd and _mt5(date.fromisoformat(fwd['start'])), source='set_header')
        if not all(window[k] for k in ('FromDate', 'ToDate', 'ForwardDate')):
            window = dict(FromDate=None, ToDate=None, ForwardDate=None, source='unknown')
    return facts, window, assumed, missing


def _validate_single_pass(tester):
    """The shared tester validator, applied to a single pass (it only admits optimization batches as-is)."""
    from studio_settings import FIELDS, validate_tester
    if tester.get('Optimization') != 0 or tester.get('ForwardMode') != 0 or tester.get('Model') not in RETEST_MODELS \
            or type(tester.get('Model')) is not int or tester.get('ShutdownTerminal') != 1:
        raise ValueError('A catch-up re-test is one pass in the export\'s own price model (0, 1, 2 or 4) with no optimization '
                         'or forward window that closes MT5 after')
    view = {key: tester[key] for key in FIELDS if key in tester}
    validate_tester(view | dict(Optimization=2, OptimizationCriterion=6, ForwardDate=''))


def _export_desc(alias, window):
    """EA_Desc metadata the EA's StartExporter passes, so the re-test SET header has the same windows."""
    if window['source'] == 'unknown':
        return alias + '@{mode=EXPORT}'
    foos = _mt5(_date(window['ToDate']) + timedelta(days=1))
    return (alias + '@{mode=EXPORT,dt_BOOS_end=' + window['FromDate'] + ',dt_FOOS_start=' + foos
            + ',dt_FWD_start=' + window['ForwardDate'] + ',dt_FWD_end=' + window['ToDate'] + '}')


class CatchupRunner(SeedRunner):
    """SeedRunner driver with catch-up members: one non-optimized MT5 pass each."""
    OUTPUT_NOUN = 're-test export (SET and CSV under Common Files\\TEMP\\SQ)'
    COMMAND_PREFIX = 'catchup'
    ID_FLAG = '--catchup-id'

    def __init__(self, controller, *, process=None, clock=time.time, sleep=time.sleep, now=None):
        super().__init__(controller, process=process, clock=clock, sleep=sleep)
        # Controller-only folders: extended-length IO when the longest ID's files would pass MAX_PATH.
        self.base = io_path(controller.root / 'catchups', 1 + MAX_ID + 1 + CATCHUP_FILE_ROOM)
        self.evidence = controller.root / 'evidence'
        self.now = now
        self.heldout_reveal, self._strategy_refs = None, {}
        self.migration = None

    def path(self, batch_id):
        if not isinstance(batch_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', batch_id):
            raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
        return self.base / batch_id

    # ---- plan --------------------------------------------------------------------------
    def _plan(self, plan):
        if not isinstance(plan, dict) or not PLAN_KEYS <= set(plan) or set(plan) - PLAN_KEYS - PLAN_OPTIONAL or plan['schema_version'] != 1:
            raise ValueError('Catch-up plan requires schema_version:1, evidence_end, sets and job_timeout_seconds '
                             '(optional: broker_clock, assume, include_below_threshold, verdict_rules, strategy_refs, heldout_reveal, '
                             'equivalence_certificates, canary_certificate, build_migration, output_root)')
        certificates = plan.get('equivalence_certificates', [])
        if not isinstance(certificates, list) or len(certificates) > MAX_CERTIFICATES or len(set(map(str, certificates))) != len(certificates) \
                or any(not isinstance(d, str) or not re.fullmatch('[0-9a-f]{64}', d) for d in certificates):
            raise ValueError('equivalence_certificates must list up to %d distinct certificate digests' % MAX_CERTIFICATES)
        canary = plan.get('canary_certificate')
        if canary is not None and (not isinstance(canary, str) or not re.fullmatch('[0-9a-f]{64}', canary) or certificates):
            raise ValueError('canary_certificate is one certificate digest, and a canary plan names no other certificates')
        if type(plan['job_timeout_seconds']) is not int or not 60 <= plan['job_timeout_seconds'] <= 86400:
            raise ValueError('job_timeout_seconds must be 60..86400')
        sets = plan['sets']
        if not isinstance(sets, list) or not 1 <= len(sets) <= MAX_MEMBERS or any(not isinstance(p, str) or not Path(p).is_absolute() for p in sets):
            raise ValueError('sets must list 1..%d absolute exported .set paths' % MAX_MEMBERS)
        if len({str(Path(p)).lower() for p in sets}) != len(sets):
            raise ValueError('Duplicate SET path in catch-up plan')
        assume = plan.get('assume', {})
        if not isinstance(assume, dict) or set(assume) - {'ExecutionMode'} or ('ExecutionMode' in assume and (
                type(assume['ExecutionMode']) is not int or not -1 < assume['ExecutionMode'] <= 600000)):
            raise ValueError('assume may only give a fixed ExecutionMode delay 0..600000 (random delay -1 cannot reproduce)')
        if type(plan.get('include_below_threshold', False)) is not bool:
            raise ValueError('include_below_threshold must be true or false')
        validate_rules(plan.get('verdict_rules'))
        from studio_strategy_attribution import parse_ref_list
        self._strategy_refs = dict(zip((str(Path(p)).lower() for p in sets),
                                       parse_ref_list(plan.get('strategy_refs'), len(sets), 'Catch-up set')))
        self.evidence = migration.output_root(plan['output_root']) if 'output_root' in plan else self.c.root / 'evidence'
        if self.evidence.exists() and not self.evidence.is_dir():
            raise ValueError('output_root is a file, not a folder: %s' % self.evidence)
        self.migration = None
        if 'build_migration' in plan:
            if certificates or canary is not None:
                raise ValueError('A build_migration plan names no equivalence or canary certificate: its re-tests are new '
                                 'evidence on the target build, never comparable catch-ups')
            if 'heldout_reveal' in plan:
                raise ValueError('A build_migration plan never reveals a held-out lock: a lock is revealed by a catch-up of its '
                                 'frozen candidate on its own build')
            self.migration = migration.validate_plan(plan['build_migration'], sets)
        return assume

    def _freeze(self, root, plan):
        members, payloads, _, _ = self._build(root, plan)
        return members, payloads

    def _build(self, root, plan):
        """Validate the plan and build every member in memory. Writes nothing."""
        assume = self._plan(plan)
        target = resolve_target(plan['evidence_end'], broker_clock=plan.get('broker_clock'), now=self.now)
        install, account = self.c.install, self.c.session['account']
        expert = install['ea_relative_path']
        runs, rows, members, payloads = RunContext(), [], [], []
        nonce = uuid.uuid4().hex[:16]
        certificates = self._certificates(plan)
        if self.migration:
            self._check_migration_target()
            # Every SET's recorded original first (SET, equity CSV, deals.csv): a missing or changed one refuses the
            # whole plan, naming the SET.
            for path in plan['sets']:
                entry = self.migration['originals'][migration.key(path)]
                entry['baseline'] = migration.check_original(entry, path)
        # A build migration re-tests on purpose: earlier catch-up versions of the old build never skip a member.
        known = () if self.migration else versions(self.c.root)
        # An export of a batch closed with exclude (studio_batch_close) is never re-tested.
        from studio_batch_close import apply_exclusions, exclusions
        markers = exclusions(self.c.root)
        for path in plan['sets']:
            entry = self.migration['originals'][migration.key(path)] if self.migration else None
            try:
                export = read_export(path, runs=runs)
            except (OSError, ValueError, UnicodeError) as exc:
                rows.append(dict(set_path=path, status='ineligible', reasons=['Unreadable export: ' + str(exc)]))
                continue
            if entry is not None and export['set_sha256'] != entry['original_sha256']:
                raise ValueError('build_migration: SET %s changed while planning; nothing was planned' % path)
            row = classify(export, target['iso'], include_below_threshold=plan.get('include_below_threshold', False), known_versions=known)
            row = apply_exclusions([row], markers)[0]
            if row['status'] == 'behind':
                reasons, bridge = self._member_problems(export, account, certificates=certificates, migration_entry=entry)
                facts, window, assumed, missing = _tester_conditions(export, assume)
                if missing:
                    reasons.append('Unknown original tester settings: ' + ', '.join(missing)
                                   + ('; keep the export next to its run folder, or pass assume.ExecutionMode' if 'ExecutionMode' in missing else ''))
                if reasons:
                    row = row | dict(status='ineligible', reasons=reasons)
                else:
                    member, files = self._member(root, export, target, facts, window, assumed, account, expert, nonce, len(members),
                                                 bridge=bridge, migration_entry=entry)
                    ref = self._strategy_refs.get(str(Path(path)).lower())
                    if ref is not None:
                        member['strategy_ref'] = ref
                    members.append(member)
                    payloads.extend(files)
                    row = row | dict(alias=member['alias'])
            rows.append(row)
        if len({m['member_id'] for m in members}) != len(members):
            raise ValueError('Duplicate export values/window in catch-up plan')
        if 'output_root' in plan and members and not is_default_root(self.c.root, self.evidence):
            migration.free_space_check(self.evidence, len(members))
        # Held-out lock (goatai#2221 §4.3): catch-up re-tests run to the evidence end, so they are
        # the likeliest to read a locked window. A reveal plan must be its lock's frozen candidate.
        from studio_heldout_guard import check_catchup
        self.heldout_reveal = check_catchup(self.c, plan, members, target, now=self.now)
        return members, payloads, rows, target

    def _installed_build_id(self, *, strict=True):
        """The installed EA's build ID from its binary (studio_installed_build, goatai#2350 6089229465). Read-only.

        ``strict``: raise InstalledBuildError (a ValueError: INSTALLED_BUILD_UNKNOWN or INSTALLED_BUILD_STATUS_CONFLICT);
        otherwise None. Hold-up tests reuse this method unbound (studio_holdup), so it needs only ``self.c.install``.
        """
        return installed_build.build_id(self.c.install, strict=strict)

    def _check_migration_target(self):
        """build_migration runs only when the installed EA is exactly the plan's target build. Read-only."""
        target = self.migration['target_build']
        try:
            installed = installed_build.resolve(self.c.install)
        except installed_build.InstalledBuildError as error:
            raise ValueError('build_migration targets %s, but %s' % (target, error)) from None
        if installed['build_id'] != target:
            raise ValueError('build_migration targets %s, but the installed EA is %s (%s); a build migration runs only on its '
                             'target build' % (target, installed['build_id'], installed['basis']))
        if self.migration['target_ea_sha256'] != self.c.install['ea_sha256']:
            raise ValueError('build_migration pins target EA %s, but the installed EA binary is %s'
                             % (self.migration['target_ea_sha256'][:12], self.c.install['ea_sha256'][:12]))

    def _certificates(self, plan):
        """Trading-equivalence certificate states the plan names, as (mode, state). Missing or altered ones refuse the plan."""
        named = [('active', digest) for digest in plan.get('equivalence_certificates', [])]
        if plan.get('canary_certificate'):
            named.append(('canary', plan['canary_certificate']))
        return [(mode, equivalence.state(self.c.root, digest)) for mode, digest in named]

    @staticmethod
    def _bridge(mode, cert):
        return dict(mode=mode, certificate_digest=cert['digest'], canary_digest=cert.get('canary_digest'), status=cert['status'],
                    export_build=cert['export_build'], installed_build=cert['installed_build'])

    def _member_problems(self, export, account, *, certificates=(), migration_entry=None):
        """Reasons this export cannot be re-tested here, and the equivalence bridge it needs (None: the same build).

        ``migration_entry`` (build_migration): the build check is replaced by the plan's recorded source build; every
        other check (server, model, symbol, standard mode, installed inputs) stays.
        """
        problems, bridge = [], None
        capture = export.get('capture') or {}
        if not export.get('symbol') or not SAFE_SYMBOL.fullmatch(export['symbol']):
            problems.append('Symbol cannot be used in a tester file name')
        if capture.get('server') and capture['server'] != account['server']:
            problems.append('Export came from broker server %s; this terminal is on %s, so ticks and symbols differ'
                            % (capture['server'], account['server']))
        model, _ = export_model(export)
        if model not in RETEST_MODELS:
            problems.append('Export was tested with model %s; a re-test repeats the export\'s own model and can only use 0, 1, 2 or 4' % model)
        if capture.get('asset') and capture['asset'] != export.get('symbol'):
            problems.append('Capture symbol differs from the export file name')
        # A re-test is only comparable on the same EA build, or on an installed build an ACTIVE
        # trading-equivalence certificate binds to the export's build (studio_equivalence).
        run_ea, build_id = (export.get('run') or {}).get('ea_sha256'), capture.get('build_id')
        installed_sha = self.c.install['ea_sha256']
        canary = next((cert for mode, cert in certificates if mode == 'canary'), None)
        covering = lambda cert: equivalence.covers(cert, export_ea_sha256=run_ea, export_build_id=None if run_ea else build_id,
                                                   installed_ea_sha256=installed_sha)
        if migration_entry is not None:
            # Cross-build on purpose: the plan's recorded source build must agree with what the export itself says.
            if build_id and build_id != migration_entry['source_build']:
                raise ValueError('build_migration: SET %s was made by EA build %s (its capture), but the plan names source_build %s'
                                 % (export['set_path'], build_id, migration_entry['source_build']))
            if run_ea and migration_entry.get('source_ea_sha256') and run_ea != migration_entry['source_ea_sha256']:
                raise ValueError('build_migration: SET %s was made by EA binary %s (its run manifest), but the plan names %s'
                                 % (export['set_path'], run_ea[:12], migration_entry['source_ea_sha256'][:12]))
        elif canary is not None:
            if not covering(canary):
                problems.append('Canary plan for certificate %s: this export was not made by its export build, or this terminal does '
                                'not run its installed build' % canary['digest'][:12])
            elif canary['status'] not in ('pending_canary', 'active'):
                problems.append('Canary plan: certificate %s is %s; only a source-equivalent certificate is canaried'
                                % (canary['digest'][:12], canary['status']))
            elif not capture.get('complete') or model != 4:
                problems.append('Canary plan: the export needs a complete Model-4 capture; its deal list is the reference')
            else:
                bridge = self._bridge('canary', canary)
        elif run_ea and run_ea != installed_sha or not run_ea and build_id:
            same, unknown = False, None
            if not run_ea:
                try:
                    installed = self._installed_build_id()
                except installed_build.InstalledBuildError as error:
                    installed, unknown = None, error
                same = installed == build_id
            cert = None if same else next((c for mode, c in certificates if mode == 'active' and covering(c)), None)
            if same:
                pass
            elif cert and cert['active'] and model in cert['canary_models']:
                bridge = self._bridge('active', cert)
            elif cert and cert['active']:
                problems.append('Trading-equivalence certificate %s is active only for model(s) %s (its canary); this export is '
                                'model %s, so a re-test would not be comparable' % (cert['digest'][:12], cert['canary_models'], model))
            elif cert:
                problems.append('Trading-equivalence certificate %s covers this export but is %s (it needs a matching canary), so a '
                                're-test would not be comparable' % (cert['digest'][:12], cert['status']))
            elif run_ea:
                problems.append('Export was made by another EA binary than the installed one, so a re-test would not be comparable'
                                ' (no active trading-equivalence certificate covers it)')
            elif installed is None:
                problems.append('The EA build that made this export (%s) is known only from its capture, and the installed EA build '
                                'is not known (%s), so a re-test could not be compared; install a pinned GOAT build, or import '
                                'the export with its run folder' % (build_id, unknown))
            else:
                problems.append('Export was made by EA build %s; the installed EA binary is %s, so a re-test would not be comparable'
                                % (build_id, installed))
        elif not run_ea:
            problems.append('The EA build that made this export is unknown (no run manifest or capture), so a re-test could not be compared')
        values = read_values(Path(export['set_path']).read_bytes())
        if values.get('Mode_Operation') != OP_STANDARD:
            problems.append('Exported SET is not in standard operation mode (Mode_Operation=9)')
        try:
            validate_raw(Path(export['set_path']).read_bytes(), self.c.schema, self.c.policy)
        except ValueError as exc:
            problems.append('SET does not match the installed EA inputs: ' + str(exc))
        return problems, bridge

    def _member(self, root, export, target, facts, window, assumed, account, expert, nonce, index, *, bridge=None, migration_entry=None):
        alias = 'C' + nonce + '_' + str(index + 1).zfill(5)
        capture_id = 'catchup-' + nonce + '-' + str(index + 1).zfill(5)
        start, to_date = date.fromisoformat(export['evidence_start']), _date(target['tester_to_date'])
        deposit = facts['Deposit']
        if type(deposit) is float and deposit.is_integer():
            deposit = int(deposit)
        if type(deposit) not in (int, float) or deposit <= 0:
            raise ValueError('Original deposit must be a positive number: ' + export['set_path'])
        model, model_source = export_model(export)
        tester = dict(Expert=expert, Symbol=export['symbol'], Period=export['period'], Model=model, ExecutionMode=facts['ExecutionMode'],
                      Optimization=0, FromDate=_mt5(start), ToDate=_mt5(to_date), ForwardMode=0, Deposit=deposit,
                      Currency=facts['Currency'], Leverage=facts['Leverage'], UseLocal=1, UseRemote=0, UseCloud=0, Visual=0,
                      ShutdownTerminal=1, ReplaceReport=0, Report='MQL5\\Files\\GOATStudio\\CatchupReports\\' + alias)
        _validate_single_pass(tester)
        # The closed day must be fully covered: MT5 ToDate is exclusive, so ToDate = evidence end + 1 day.
        if evidence_end.effective_end(tester['ToDate']) != target['iso']:
            raise ValueError('Catch-up ToDate %s would not cover the evidence end %s' % (tester['ToDate'], target['iso']))
        raw = Path(export['set_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != export['set_sha256']:
            raise ValueError('Export SET changed while planning: ' + export['set_path'])
        text = raw.decode('utf-16')
        frozen_text, count = re.subn(r'(?m)^EA_Desc=[^\r\n]*', 'EA_Desc=' + alias, text)
        if count != 1:
            raise ValueError('Exported SET needs exactly one EA_Desc line: ' + export['set_path'])
        frozen = b'\xff\xfe' + frozen_text.encode('utf-16-le')
        capture = export.get('capture')
        source_inputs, source_inputs_origin = None, None
        if capture and model == 4:   # the EA's sequence capture only runs on real ticks
            candidate = Path(capture['path']).parent / 'source-inputs.set'
            if candidate.is_file() and candidate.stat().st_size <= 1024 * 1024:
                source_inputs, source_inputs_origin = candidate.read_bytes(), 'capture'
        if migration_entry is not None and source_inputs is None and model == 4:
            # No .goatseq on the export (the V1.47 SETs): the re-test writes one. The EA needs a source input snapshot
            # to capture; it is the original SET's own bytes, staged as they are. The SET itself is never written.
            source_inputs, source_inputs_origin = raw, 'original_set'
        if bridge and bridge['mode'] == 'canary' and source_inputs is None:
            raise ValueError('A canary member needs the export capture\'s source-inputs.set: ' + export['set_path'])
        values = read_values(frozen)
        inputs = dict(values, EA_Desc=_export_desc(alias, window), Sequence_Export_Enabled='true' if source_inputs is not None else 'false',
                      Sequence_Export_Id=capture_id, Sequence_Export_Start=tester['FromDate'], Sequence_Export_End=tester['ToDate'],
                      Sequence_Export_Model='4')
        sections = {'Common': {'Login': account['login'], 'Server': account['server']}, 'Experts': {'Enabled': 0, 'AllowLiveTrading': 0},
                    'Tester': tester, 'TesterInputs': inputs}
        ini = ''
        for section, items in sections.items():
            ini += '[' + section + ']\r\n'
            for key, value in items.items():
                if any(c in str(value) for c in '\r\n\x00'):
                    raise ValueError('Unsafe startup value: ' + key)
                ini += key + '=' + str(value) + '\r\n'
        config = ini.encode('utf-16')
        set_path = root / (alias + '.set')
        config_path = Path(self.c.install['terminal_data_root']) / 'config/GOATStudio/Catchups' / (alias + '.ini')
        # Bounded whatever the catch-up ID: evidence\c.<10 hex>\<5 digits>\ (extended-length IO past MAX_PATH).
        evidence_dir = io_path(self.evidence / evidence_key(root.name) / member_folder(index), OUTPUT_PATH_ROOM)
        files = [(set_path, frozen), (config_path, config)]
        member = dict(member_id=sha([export['values_sha256'], export['symbol'], export['period'], tester['FromDate'], tester['ToDate'],
                                     deposit, facts['Currency'], facts['Leverage'], facts['ExecutionMode']]),
                      index=index, alias=alias, account=account, tester=tester, frame_target=1, capture_id=capture_id,
                      attempt_token=attempt_token(capture_id), capture=source_inputs is not None,
                      source_path=export['set_path'], source_sha256=export['set_sha256'],
                      set_path=str(set_path), set_sha256=hashlib.sha256(frozen).hexdigest(),
                      config_path=str(config_path), config_sha256=hashlib.sha256(config).hexdigest(),
                      evidence_dir=str(evidence_dir), assumed=assumed, optimization_window=window,
                      original=dict(set_path=export['set_path'], set_sha256=export['set_sha256'], values_sha256=export['values_sha256'],
                                    member=export.get('member'), run_id=(export.get('run') or {}).get('run_id'),
                                    evidence_start=export['evidence_start'], evidence_end=export['evidence_end'],
                                    evidence_end_source=export['evidence_end_source'], metrics=export.get('metrics'),
                                    tester=export.get('tester'), threshold=export['threshold'], ea_name=export.get('ea_name'),
                                    build=build_identity(export)),
                      pins=dict(installed_ea_sha256=self.c.install['ea_sha256'], original_ea_sha256=(export.get('run') or {}).get('ea_sha256'),
                                original_build_id=(capture or {}).get('build_id'), original_server=(capture or {}).get('server'),
                                installed_build_id=self._installed_build_id(strict=False),
                                server=account['server'], model=model, original_model=model, model_source=model_source,
                                timeframe=export['period'], deposit=deposit, currency=facts['Currency'], leverage=facts['Leverage'],
                                execution_mode=facts['ExecutionMode'], assumed=assumed, original_tester=export.get('tester') or {},
                                equivalence=bridge),
                      new_window=dict(first_day=(date.fromisoformat(export['evidence_end']) + timedelta(days=1)).isoformat(),
                                      last_day=target['iso'], weekdays=weekdays(date.fromisoformat(export['evidence_end']) + timedelta(days=1),
                                                                                date.fromisoformat(target['iso']))))
        if source_inputs is not None:
            staged = root / (alias + '.source-inputs.set')
            files.append((staged, source_inputs))
            member.update(source_inputs_path=str(staged), source_inputs_sha256=hashlib.sha256(source_inputs).hexdigest(),
                          source_inputs_origin=source_inputs_origin)
        if migration_entry is not None:
            target_build = self.migration['target_build']
            member['build_migration'] = dict(kind=migration.KIND, provenance=migration.provenance(target_build),
                                             source_build=migration_entry['source_build'],
                                             source_ea_sha256=migration_entry.get('source_ea_sha256') or (export.get('run') or {}).get('ea_sha256'),
                                             target_build=target_build, target_ea_sha256=self.c.install['ea_sha256'],
                                             original_path=migration_entry['original_path'], original_sha256=migration_entry['original_sha256'],
                                             original_csv_sha256=migration_entry['original_csv_sha256'],
                                             original_deals_sha256=migration_entry.get('original_deals_sha256'),
                                             goatseq_from=source_inputs_origin)
        return member, files

    def validate(self, plan, catchup_id=None):
        """Non-executing preview of a catch-up plan: no file, process or terminal effect.

        Sized exactly as ``prepare`` would be: with ``catchup_id`` its own folders, else the longest legal ID.
        """
        root = self.path(catchup_id) if catchup_id is not None else self.base / 'validation-only'
        members, _, rows, target = self._build(root, plan)
        self._check_mt5_paths(members)
        return self._preview(members, rows, target, plan, writes=False) | dict(paths=self.path_report(catchup_id, members))

    def path_report(self, catchup_id=None, members=()):
        """How long this catch-up's paths get, and which use the \\\\?\\ extended-length form (agent-readable)."""
        root = self.c.root
        evidence = self.evidence / evidence_key(catchup_id or 'validation-only')
        custom = self.evidence != root / 'evidence'
        worst = evidence_worst_case(root, self.evidence)
        report = dict(max_path=MAX_PATH, state_root_length=len(os.path.abspath(root)),
                      catchup_id=catchup_id, catchup_id_length=len(catchup_id) if catchup_id else None,
                      evidence_root=plain(os.path.abspath(self.evidence)), evidence_root_source='output_root' if custom else 'controller_state',
                      evidence_folder=plain(io_path(evidence)) if catchup_id else None,
                      evidence_worst_case=worst,
                      evidence_formula=('len(output root) + 159 = %d + 159' % len(os.path.abspath(self.evidence)) if custom else
                                        'len(state root) + 168 = %d + 168' % len(os.path.abspath(root))) + '; the catch-up ID does not change it',
                      evidence_extended_length=worst > MAX_PATH and WINDOWS,
                      catchups_worst_case=catchups_worst_case(root, catchup_id),
                      catchups_formula='len(state root) + 83 + len(catch-up ID, %s)' % ('%d' % len(catchup_id) if catchup_id else 'longest 80'),
                      catchups_extended_length=str(self.base).startswith('\\\\?\\'))
        if members:
            exact = [len(path) for m in members for path, _ in self._mt5_paths(m)]
            unit = max(self._ea_unit_worst_case(m) for m in members)
            report.update(mt5_longest_exact=max(exact), mt5_export_unit_worst_case=unit)
            if unit > MAX_PATH:
                report['warnings'] = ['The EA writes each re-test unit under Common Files\\TEMP\\SQ; with a long export file name it '
                                      'could reach %d characters, past the Windows limit MT5 can write. If a member fails to export, '
                                      'shorten the Windows user (Common Files) path.' % unit]
        return report

    def _mt5_paths(self, member):
        """The exact paths MT5 or the EA opens for one member, plain (neither is long-path aware), with what each is."""
        data, common = Path(self.c.install['terminal_data_root']), Path(self.c.install['common_files_root'])
        paths = [(os.path.abspath(member['config_path']), 'tester INI (/config)'),
                 (os.path.abspath(data / (member['tester']['Report'] + '.htm')), 'tester report')]
        if member.get('capture'):
            paths.append((os.path.abspath(common / 'GOATSequencePending' / member['capture_id'] / 'source-inputs.set'), 'capture inputs'))
        return paths

    def _ea_unit_worst_case(self, member):
        """Longest path of the EA's SET/CSV/.goatseq unit in Common Files\\TEMP\\SQ\\<token> (EA file names, with margin)."""
        return len(os.path.abspath(self._attempt_dir(member))) + 1 + OUTPUT_PATH_ROOM

    def _check_mt5_paths(self, members):
        """MT5 cannot be given \\\\?\\ paths: refuse a member whose exact MT5 paths pass MAX_PATH, before any write."""
        if not WINDOWS:
            return
        for member in members:
            for path, what in self._mt5_paths(member):
                if len(path) > MAX_PATH:
                    raise ValueError('The MT5 %s path would be %d characters, past the Windows %d-character limit MT5 can open: %s'
                                     % (what, len(path), MAX_PATH + 1, path))

    def _migration_public(self):
        """The plan's build migration as the manifest and previews record it (None for a normal catch-up)."""
        if not self.migration:
            return None
        target = self.migration['target_build']
        return dict(kind=migration.KIND, provenance=migration.provenance(target), target_build=target,
                    target_ea_sha256=self.c.install['ea_sha256'], record=migration.RECORD_FILE, tolerances=migration.public_tolerances(),
                    plain='Re-tests on %s as new evidence records (%s); never a catch-up verdict on the original exports.'
                          % (target, migration.provenance(target)))

    def _preview(self, members, rows, target, plan, *, writes):
        value = dict(schema_version=1, valid=True, writes=writes, native_launch_qualified=False, mode=MODE,
                     target=target, plan_sha256=sha(plan), member_count=len(members), summary=summarize(rows, target['iso'], resolved=target),
                     exports=rows[:MAX_PUBLIC], exports_omitted=max(0, len(rows) - MAX_PUBLIC),
                     members=[dict(alias=m['alias'], symbol=m['tester']['Symbol'], period=m['tester']['Period'], from_date=m['tester']['FromDate'],
                                   to_date=m['tester']['ToDate'], original_end=m['original']['evidence_end'], new_weekdays=m['new_window']['weekdays'],
                                   assumed=m['assumed'], capture=m['capture'], model=m['tester']['Model'],
                                   equivalence=(m['pins'].get('equivalence') or {}).get('mode'),
                                   certificate=(m['pins'].get('equivalence') or {}).get('certificate_digest'))
                              | (dict(source_build=m['build_migration']['source_build'], goatseq_from=m['build_migration']['goatseq_from'])
                                 if m.get('build_migration') else {}) for m in members[:MAX_PUBLIC]])
        if self.migration:
            value['build_migration'] = self._migration_public()
        if 'output_root' in plan:
            value['output_root'] = plain(os.path.abspath(self.evidence))
        return value

    def prepare(self, batch_id, plan):
        root = self.path(batch_id)
        if root.exists():
            _, old, _ = self._read(batch_id)
            if old['plan_sha256'] != sha(plan):
                raise ValueError('Catch-up ID already belongs to a different plan; choose a new ID')
            return self.status(batch_id)
        members, payloads, rows, target = self._build(root, plan)
        if not members:
            raise ValueError('Nothing to catch up to %s. %s' % (target['iso'], summarize(rows, target['iso'], resolved=target)['plain']))
        self._check_mt5_paths(members)
        folder = io_path(self.evidence / evidence_key(batch_id), 1 + MEMBER_FOLDER_DIGITS + OUTPUT_PATH_ROOM)
        record_path = folder / EVIDENCE_FOLDER_RECORD
        if folder.exists():
            try:
                owner = read_json_bounded(record_path).get('catchup_id')
            except (OSError, ValueError, AttributeError):
                owner = None
            if owner != batch_id:
                raise ValueError('Catch-up evidence folder %s already belongs to %s; choose another catch-up ID'
                                 % (plain(folder), owner or 'an unrecorded catch-up'))
        manifest = dict(schema_version=1, batch_id=batch_id, installation_sha256=sha(self.c.install), schema_sha256=sha(self.c.schema),
                        plan_sha256=sha(plan), plan=plan, created_unix=self.clock(), members=members, mode=MODE,
                        evidence_end=target, exports=rows, verdict_rules=validate_rules(plan.get('verdict_rules')),
                        include_below_threshold=plan.get('include_below_threshold', False), native_launch_qualified=False)
        if self.heldout_reveal is not None:
            manifest['heldout_reveal'] = self.heldout_reveal
        if self.migration:
            manifest['build_migration'] = self._migration_public()
        custom_root = 'output_root' in plan
        if custom_root:
            manifest['output_root'] = plain(os.path.abspath(self.evidence))
        if len(json.dumps(manifest).encode('utf-8')) > MAX_MANIFEST_BYTES:
            raise ValueError('Catch-up manifest exceeds 128 MiB; split the plan')
        if custom_root:
            # Recorded before any member runs, so versions() finds catch-up evidence written there.
            self.evidence.mkdir(parents=True, exist_ok=True)
            record_evidence_root(self.c.root, os.path.abspath(self.evidence))
        root.mkdir(parents=True, exist_ok=False)
        (Path(self.c.install['terminal_data_root']) / 'MQL5/Files/GOATStudio/CatchupReports').mkdir(parents=True, exist_ok=True)
        for path, raw in payloads:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        write_json(root / 'manifest.json', manifest)
        if not folder.exists():
            # The readable catch-up ID and each member folder's alias, next to the short hashed folder names.
            folder.mkdir(parents=True)
            write_json(record_path, dict(schema=EVIDENCE_FOLDER_SCHEMA, catchup_id=batch_id, manifest_sha256=digest(root / 'manifest.json'),
                                         evidence_end=target['iso'], created_unix=self.clock(),
                                         members={member_folder(m['index']): dict(alias=m['alias'], symbol=m['tester']['Symbol'],
                                                                                  period=m['tester']['Period'], source_path=m['source_path'])
                                                  for m in members}))
        state = dict(schema_version=1, batch_id=batch_id, manifest_sha256=digest(root / 'manifest.json'), status='prepared', generation=None,
                     members=[dict(member_id=m['member_id'], alias=m['alias'], status='pending', attempts=0, result=None) for m in members])
        self._save(root, state)
        return self.status(batch_id) | dict(preview=self._preview(members, rows, target, plan, writes=True),
                                            paths=self.path_report(batch_id, members))

    # ---- native hooks ------------------------------------------------------------------
    def _attempt_dir(self, member):
        return Path(self.c.install['common_files_root']) / 'TEMP' / 'SQ' / member['attempt_token']

    def _outputs(self, member):
        folder = self._attempt_dir(member)
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.glob('*.set') if p.is_file())

    def _stray_output(self, root, spec):
        """A pending member's output before its start also includes a native capture in its own namespace.

        An unowned MT5 that ran a capture member leaves GOATSequencePending/<capture id>/run.csv; _before_start
        would refuse that member later and strand the batch, so the settle fails it now (Claude-Mac, GOAT-EA#163).
        """
        found = super()._stray_output(root, spec)
        if spec.get('capture'):
            run = Path(self.c.install['common_files_root']) / 'GOATSequencePending' / spec['capture_id'] / 'run.csv'
            if run.exists():
                found.append(str(run))
        return found

    def _verify_prepared(self, batch_id, manifest):
        """Catch-up members are single Optimization=0 passes with no axes, so saved
        tester-profile optimize flags cannot add a search axis; nothing to refuse."""

    def _before_start(self, spec):
        """Stage the EA's capture input snapshot (GoatTraceInit refuses without it). Create-only.

        A build-migration member starts only while the installed EA is still its target build.
        """
        if spec.get('build_migration'):
            target = spec['build_migration']['target_build']
            try:
                installed = self._installed_build_id()
            except installed_build.InstalledBuildError as error:
                raise ValueError('Build-migration member %s targets %s, but %s; nothing was started' % (spec['alias'], target, error)) from None
            if installed != target or self.c.install['ea_sha256'] != spec['build_migration']['target_ea_sha256']:
                raise ValueError('Build-migration member %s targets %s, but the installed EA binary (sha256 %s) is now %s; nothing was started'
                                 % (spec['alias'], target, self.c.install['ea_sha256'][:12], installed))
        if not spec['capture']:
            return
        raw = Path(spec['source_inputs_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['source_inputs_sha256']:
            raise ValueError('Frozen catch-up capture inputs changed')
        pending = Path(self.c.install['common_files_root']) / 'GOATSequencePending' / spec['capture_id']
        target = pending / 'source-inputs.set'
        if (pending / 'run.csv').exists():
            raise ValueError('Capture namespace already holds a native capture; no restart')
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('Capture namespace already holds different inputs')
            return
        pending.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)

    def _collect(self, path, spec, manifest):
        """Verify the EA's re-test unit, move it into the evidence store and judge the new weeks."""
        from studio_catchup_verdict import evaluate
        if spec.get('build_migration'):
            return self._collect_migration(path, spec, manifest)
        if len(self._outputs(spec)) != 1:
            raise ValueError('Expected exactly one exported SET from a single catch-up pass')
        retest = read_export(path)
        tester = spec['tester']
        if (retest['symbol'], retest['period']) != (tester['Symbol'], tester['Period']) or retest['alias'] != spec['alias']:
            raise ValueError('Re-test export identity differs from the frozen member')
        capture = retest.get('capture')
        if spec['capture']:
            if not capture or capture['run_id'] != spec['capture_id']:
                raise ValueError('Re-test capture is missing or belongs to another attempt')
            if (capture['requested_start_msc'], capture['requested_end_msc']) != (server_msc(_date(tester['FromDate'])), server_msc(_date(tester['ToDate']))):
                raise ValueError('Re-test capture window differs from the frozen member')
        original = read_export(spec['original']['set_path'])
        if original['set_sha256'] != spec['original']['set_sha256'] or original['evidence_end'] != spec['original']['evidence_end']:
            raise ValueError('Original export changed since the catch-up was prepared')
        moved = self._move(path, Path(spec['evidence_dir']))
        retest = read_export(moved)
        if not retest['evidence_end']:
            raise ValueError('Re-test export has no evidence end')
        pins = dict(spec.get('pins') or {})
        if pins.get('equivalence'):
            # The certificate is checked again now: a later drifting canary refutes it for every pending verdict.
            bridge = dict(pins['equivalence'])
            try:
                current = equivalence.state(self.c.root, bridge['certificate_digest'])
            except (OSError, ValueError) as exc:
                current = dict(status='unreadable: ' + str(exc), active=False, canary_digest=None)
            bridge.update(status_at_collect=current['status'], canary_digest=current.get('canary_digest') or bridge.get('canary_digest'),
                          valid_at_collect=bridge['mode'] == 'active' and bool(current['active']))
            pins['equivalence'] = bridge
        try:
            verdict = evaluate(original, retest, new_end=min(retest['evidence_end'], manifest['evidence_end']['iso']),
                               tester=spec['original'].get('tester'), rules=manifest.get('verdict_rules'), pins=pins)
        except (OSError, ValueError, KeyError, ArithmeticError) as exc:
            # The re-test evidence is kept either way; only the judgement is unavailable.
            reason = 'Could not judge the new weeks: ' + str(exc)
            verdict = dict(verdict='unjudged', confidence='none', reasons=[reason], plain=reason,
                           new_weeks=dict(first_day=spec['new_window']['first_day'], last_day=retest['evidence_end'], weekdays=None,
                                          trades=None, net=None, dd=None, pf=None),
                           reproduction=dict(reproduced=None), comparability=None, rules=manifest.get('verdict_rules'),
                           evidence_model=model_tag(tester['Model'], tester['Period'], source=pins.get('model_source')),
                           equivalence=pins.get('equivalence'))
        # Evidence for live decisions runs to the latest closed day: every result stamps the catch-up's resolved end.
        verdict['evidenceEnd'] = manifest['evidence_end']['iso']
        verdict['evidenceEndMode'] = evidence_end.evidence_end_mode(manifest['evidence_end'], catch_up=True)
        verdict['evidenceEndEffective'] = evidence_end.effective_end(tester['ToDate'])     # the last day the re-test covers
        verdict['oos_rule'] = self._oos_rule(original, retest, spec, verdict, evidence_end=manifest['evidence_end']['iso'])
        verdict['oos_rule']['evidenceEndEffective'] = verdict['evidenceEndEffective']
        created = datetime.now(timezone.utc).isoformat(timespec='seconds')
        version = dict(schema=VERSION_SCHEMA, kind=VERSION_KIND, values_sha256=retest['values_sha256'], symbol=retest['symbol'], period=retest['period'],
                       evidence_start=retest['evidence_start'], evidence_end=retest['evidence_end'], evidence_end_source=retest['evidence_end_source'],
                       target_end=manifest['evidence_end']['iso'], catchup_id=manifest['batch_id'], alias=spec['alias'],
                       created_utc=created, catch_up=catch_up_stamp(dict(spec, pins=pins), manifest, verdict, created,
                                                                    (original.get('windows') or {}).get('FOOS')),
                       original=dict(spec['original'], csv_path=original['csv_path']),
                       retest=dict(set_path=retest['set_path'], set_sha256=retest['set_sha256'], csv_path=retest['csv_path'],
                                   capture=retest.get('capture') and dict(path=retest['capture']['path'], status=retest['capture']['status'],
                                                                         manifest_sha256=retest['capture']['manifest_sha256'])),
                       tester=tester, assumed=spec['assumed'],
                       verdict={k: verdict[k] for k in ('verdict', 'confidence', 'plain', 'reasons')}, caveat=CAVEAT,
                       comparability=verdict.get('comparability'), evidence_model=verdict.get('evidence_model'),
                       equivalence=pins.get('equivalence'),
                       qualification=qualification_inputs(spec, manifest, verdict),
                       history_short=retest['history_short'], ea_desc_metadata=spec['optimization_window']['source'],
                       oos_rule=verdict['oos_rule'], evidenceEnd=verdict['evidenceEnd'], evidenceEndMode=verdict['evidenceEndMode'],
                       evidenceEndEffective=verdict['evidenceEndEffective'],
                       comparison=verdict.get('comparison'), historyBasis=verdict.get('historyBasis'),
                       tickHistoryDrift=verdict.get('tickHistoryDrift'), rebase=verdict.get('rebase'),
                       rebasedWindows=verdict.get('rebasedWindows'))
        version_path = Path(spec['evidence_dir']) / 'evidence-version.json'
        with version_path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(version, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
        window = verdict['new_weeks']
        summary = dict(verdict=verdict['verdict'], confidence=verdict['confidence'], new_first_day=window['first_day'],
                       new_last_day=window['last_day'], weekdays=window['weekdays'], trades=window['trades'], net=window['net'],
                       dd=window['dd'], pf=window.get('pf'), reproduced=verdict['reproduction']['reproduced'], plain=verdict['plain'],
                       history_short=retest['history_short'], comparable=(verdict.get('comparability') or {}).get('comparable'),
                       model=(verdict.get('evidence_model') or {}).get('model'), model_rung=(verdict.get('evidence_model') or {}).get('model_rung'),
                       equivalence_certificate=(pins.get('equivalence') or {}).get('certificate_digest'),
                       equivalence_mode=(pins.get('equivalence') or {}).get('mode'),
                       oos_rule=verdict['oos_rule']['status'], evidenceEnd=verdict['evidenceEnd'],
                       evidenceEndMode=verdict['evidenceEndMode'], evidenceEndEffective=verdict['evidenceEndEffective'],
                       comparison=verdict.get('comparison'), historyBasis=verdict.get('historyBasis'),
                       tickHistoryDrift=verdict.get('tickHistoryDrift'),
                       firstFailingRule=verdict.get('firstFailingRule'), firstFailingCause=verdict.get('firstFailingCause'),
                       firstDifference=verdict.get('firstDifference'))
        return dict(status='verified_catchup_retest', path=retest['set_path'], sha256=retest['set_sha256'], schema_version=1,
                    member_id=spec['member_id'], summary=summary, verdict=verdict, version_path=str(version_path),
                    native_launch_qualification=False)

    def _collect_migration(self, path, spec, manifest):
        """A build-migration member: verify the unit, move it, and write a ``build_migration_retest`` record.

        No verdict, no catch-up stamp: the drift against the exact original (judged only over the original's own span),
        and the re-test's own windows and new weeks as measured numbers. The unseen weeks are never judged here
        (Claude-Mac, #2350 6070262354): that is the external prereg analysis.
        """
        from studio_catchup_rebase import rebased_windows
        from studio_catchup_verdict import equity_rows
        from studio_window_metrics import equity_samples, window as metric_window
        bm = spec['build_migration']
        if len(self._outputs(spec)) != 1:
            raise ValueError('Expected exactly one exported SET from a single build-migration pass')
        retest = read_export(path)
        tester = spec['tester']
        if (retest['symbol'], retest['period']) != (tester['Symbol'], tester['Period']) or retest['alias'] != spec['alias']:
            raise ValueError('Re-test export identity differs from the frozen member')
        capture = retest.get('capture')
        if spec['capture']:
            if not capture or capture['run_id'] != spec['capture_id']:
                raise ValueError('Re-test capture is missing or belongs to another attempt')
            if (capture['requested_start_msc'], capture['requested_end_msc']) != (server_msc(_date(tester['FromDate'])), server_msc(_date(tester['ToDate']))):
                raise ValueError('Re-test capture window differs from the frozen member')
        ran_on = (capture or {}).get('build_id') or self._installed_build_id()
        if ran_on != bm['target_build']:
            raise ValueError('Re-test ran on EA build %s, not the build-migration target %s; nothing was moved' % (ran_on, bm['target_build']))
        if retest['values_sha256'] != spec['original']['values_sha256']:
            raise ValueError('Re-test inputs differ from the original SET; nothing was moved')
        # The drift baseline is pinned whole: the SET, its equity CSV and its deals.csv must be the ones the plan recorded.
        baseline = migration.check_original(dict(original_path=bm['original_path'], original_sha256=bm['original_sha256'],
                                                 original_csv_sha256=bm['original_csv_sha256'],
                                                 original_deals_sha256=bm.get('original_deals_sha256')), bm['original_path'])
        original = read_export(bm['original_path'])
        moved = self._move(path, Path(spec['evidence_dir']))
        retest = read_export(moved)
        if not retest['evidence_end']:
            raise ValueError('Re-test export has no evidence end')
        target_end = manifest['evidence_end']['iso']
        new_end = date.fromisoformat(min(retest['evidence_end'], target_end))
        pins = spec.get('pins') or {}
        drift = migration.drift(original, retest, deposit=pins.get('deposit'))
        tested = retest.get('capture') or {}
        deals = str(Path(tested['path']).parent / 'deals.csv') if tested.get('complete') and tested.get('path') else None
        if deals and not Path(deals).is_file():
            deals = None
        first_new = date.fromisoformat(original['evidence_end']) + timedelta(days=1)
        windows, new_weeks, window_error = None, None, None
        try:
            windows = rebased_windows(original, retest, equity_rows(retest['csv_path']), deals,
                                      tester=spec['original'].get('tester'), tested_through=new_end)
            if new_end >= first_new:
                new_weeks = dict(metric_window(equity_samples(Path(retest['csv_path']).read_bytes()), first_new, new_end, deals=deals),
                                 name='new_weeks', basis='retest')
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            window_error = 'Could not measure the re-test windows: ' + str(exc)[:240]
        created = datetime.now(timezone.utc).isoformat(timespec='seconds')
        evidence_model = model_tag(tester['Model'], tester['Period'], source=pins.get('model_source'))
        record = dict(schema=migration.RECORD_SCHEMA, kind=migration.KIND, provenance=bm['provenance'],
                      catchup_id=manifest['batch_id'], alias=spec['alias'], created_utc=created,
                      source_build=bm['source_build'], source_ea_sha256=bm.get('source_ea_sha256'),
                      target_build=bm['target_build'], target_ea_sha256=bm['target_ea_sha256'], ran_on_build=ran_on,
                      symbol=retest['symbol'], period=retest['period'], values_sha256=retest['values_sha256'],
                      original=dict(path=bm['original_path'], sha256=bm['original_sha256'], csv_sha256=baseline['csv'],
                                    deals_sha256=baseline['deals'], values_sha256=original['values_sha256'],
                                    evidence_start=original['evidence_start'], evidence_end=original['evidence_end'],
                                    csv_path=original['csv_path'], metrics=original.get('metrics'), windows=original.get('windows'),
                                    capture_status=(original.get('capture') or {}).get('status'), threshold=spec['original'].get('threshold')),
                      retest=dict(set_path=retest['set_path'], set_sha256=retest['set_sha256'], values_sha256=retest['values_sha256'],
                                  csv_path=retest['csv_path'], evidence_start=retest['evidence_start'], evidence_end=retest['evidence_end'],
                                  metrics=retest.get('metrics'), goatseq=bool(tested), goatseq_from=bm.get('goatseq_from'),
                                  capture=tested and dict(path=tested['path'], status=tested['status'], complete=tested['complete'],
                                                          manifest_sha256=tested['manifest_sha256'], build_id=tested.get('build_id'))),
                      inputs_unchanged=True, original_set_unchanged=True, source_inputs_sha256=spec.get('source_inputs_sha256'),
                      drift=drift, windows=windows, new_weeks=new_weeks, window_error=window_error,
                      new_weeks_judged=False, judgement=migration.UNSEEN_WEEKS,
                      evidenceEnd=target_end, evidenceEndMode=evidence_end.evidence_end_mode(manifest['evidence_end'], catch_up=True),
                      evidenceEndEffective=evidence_end.effective_end(tester['ToDate']), new_first_day=first_new.isoformat(),
                      tester=tester, assumed=spec['assumed'], evidence_model=evidence_model, history_short=retest['history_short'],
                      ea_desc_metadata=spec['optimization_window']['source'],
                      plain='A new evidence record on %s (%s), never a catch-up verdict on the original export. %s'
                            % (bm['target_build'], bm['provenance'], drift['plain']))
        record_path = Path(spec['evidence_dir']) / migration.RECORD_FILE
        temporary = record_path.with_name(record_path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(record, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, record_path)   # create-only and atomic: rename never replaces an existing record on Windows
        summary = dict(kind=migration.KIND, provenance=bm['provenance'], source_build=bm['source_build'], target_build=bm['target_build'],
                       drift=drift['verdict'], drift_delta=drift['delta'], drift_reasons=drift['reasons'], goatseq=bool(tested),
                       goatseq_from=bm.get('goatseq_from'), new_first_day=first_new.isoformat(), new_last_day=new_end.isoformat(),
                       new_weeks=None if not new_weeks else {k: new_weeks.get(k) for k in ('trades', 'profit', 'pf', 'maxDd', 'equityNet', 'days')},
                       new_weeks_judged=False, evidenceEnd=target_end, evidenceEndEffective=record['evidenceEndEffective'],
                       history_short=retest['history_short'], model=evidence_model.get('model'), plain=record['plain'])
        return dict(status=migration.RESULT_STATUS, kind=migration.KIND, provenance=bm['provenance'], path=retest['set_path'],
                    sha256=retest['set_sha256'], schema_version=1, member_id=spec['member_id'], summary=summary,
                    record_path=str(record_path), native_launch_qualification=False)

    @staticmethod
    def _oos_rule(original, retest, spec, verdict, evidence_end=None):
        """BOOS/FOOS verdict under the OOS window formula (goat-oos-window-rule-v1), next to the catch-up verdict.

        Formula batches only (their exports stop at the optimization end, so the new weeks are the FOOS hold-out);
        other exports read not_applicable. A re-test that is not the same test as the original is never judged.
        Every result stamps ``evidenceEnd``: the catch-up's resolved end (any closed trading day), or the earlier
        re-test end it was judged through.
        """
        from studio_oos_windows import BOOS_CONTAMINATED_BY, EVALUATION, judge_retest
        # OOS-rule judging of a catch-up reads verdicts only: a build-migration member is never judged as one.
        migration.refuse(verdict, 'The OOS-rule catch-up judge')
        migration.refuse(spec.get('build_migration') or {}, 'The OOS-rule catch-up judge')
        if verdict.get('verdict') in ('not_comparable', 'unjudged'):
            reason = 'the re-test was not judged as the same test as the original (%s)' % verdict.get('verdict')
            result = dict(schema=EVALUATION, status='no_data', reasons=[reason], used_for_ranking=False,
                        boosContaminatedBy=BOOS_CONTAMINATED_BY,
                        plain='No hold-out data under the OOS window rule: ' + reason + '.')
        else:
            try:
                result = judge_retest(original, retest, tester=spec['original'].get('tester'), evidence_end=evidence_end)
            except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
                reason = 'could not apply the OOS window rule: ' + str(exc)[:240]
                result = dict(schema=EVALUATION, status='no_data', reasons=[reason], used_for_ranking=False,
                            boosContaminatedBy=BOOS_CONTAMINATED_BY,
                            plain='No hold-out data: ' + reason + '.')
        result.setdefault('evidenceEnd', evidence_end)
        # comparable_rebased: the gates ran on the re-based evidence (judge_retest measures every window on the
        # re-test). requalify: the same gates judge the re-test as a new candidate, with no status carried.
        comparison = verdict.get('comparison')
        if comparison in ('comparable_rebased', 'requalify'):
            result.update(evidenceBasis='retest', comparison=comparison, candidate='new' if comparison == 'requalify' else None)
        return result
    def _move(self, set_path, destination):
        """Move the EA's SET/CSV/.goatseq unit out of TEMP into the evidence folder. Never overwrites.

        The unit is assembled in ``<member folder>~`` (one character longer, inside OUTPUT_PATH_ROOM's margin) next to
        the destination and renamed into place in one step, so an output root on another drive (a copy, not a
        rename) never leaves a half-written member folder. A copied part is verified (every file's SHA-256) and its
        source in Common Files\\TEMP\\SQ is removed only after the member folder is in place.
        """
        stem = set_path.name[:-4]
        staging = destination.with_name(destination.name + '~')
        parts = [(set_path, set_path.name), (set_path.with_name(stem + '.csv'), stem + '.csv')]
        package = set_path.with_name(stem + '.goatseq')
        if package.is_dir():
            parts.append((package, package.name))
        if destination.exists():
            raise ValueError('Catch-up evidence folder already exists; inspect it, nothing was moved')
        if staging.exists():
            raise ValueError('Catch-up evidence staging folder %s already exists; inspect it, nothing was moved' % plain(staging))
        for source, _ in parts:
            if not source.exists():
                raise ValueError('Re-test unit incomplete: ' + source.name)
        staging.mkdir(parents=True)
        copied = []
        for source, name in parts:
            target = staging / name
            try:
                os.rename(source, target)
            except OSError:
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
                if not _same_tree(source, target):
                    raise ValueError('Copied re-test file differs: ' + source.name)
                copied.append(source)
        os.rename(staging, destination)
        for source in copied:   # cross-drive copies: the TEMP unit goes only once the verified copy is in place
            try:
                shutil.rmtree(source) if source.is_dir() else source.unlink()
            except OSError:
                pass   # a leftover TEMP file is harmless; the evidence is complete and verified
        return destination / set_path.name

    # ---- reports -----------------------------------------------------------------------
    def report(self, batch_id):
        self.status(batch_id)
        root, manifest, state = self._read(batch_id)
        if manifest.get('build_migration'):
            return self._migration_report(root, manifest, state)
        rows, counts = [], {}
        for spec, item in zip(manifest['members'], state['members']):
            result = read_seed_json(item['result']['path']) if item.get('result') else None
            if result is not None:
                migration.refuse(result, 'catchup-report')   # a catch-up report counts verdicts only
                migration.refuse(spec.get('build_migration') or {}, 'catchup-report')
            verdict = result['summary']['verdict'] if result else None
            counts[verdict or item['status']] = counts.get(verdict or item['status'], 0) + 1
            rows.append(dict(alias=spec['alias'], status=item['status'], symbol=spec['tester']['Symbol'], period=spec['tester']['Period'],
                             original_set=spec['original']['set_path'], original_end=spec['original']['evidence_end'],
                             new_end=manifest['evidence_end']['iso'], summary=result['summary'] if result else None,
                             version_path=result['version_path'] if result else None, error=item.get('error'),
                             export_thresholds=spec['original'].get('threshold'),
                             signals=(result.get('verdict') or {}).get('signals') if result else None,
                             oos_rule=(result.get('verdict') or {}).get('oos_rule') if result else None,
                             evidenceEnd=manifest['evidence_end']['iso'],
                             evidenceEndEffective=evidence_end.effective_end(spec['tester']['ToDate'])))
        value = dict(schema_version=1, batch_id=batch_id, mode=MODE, status=state['status'], evidence_end=manifest['evidence_end'],
                     counts=counts, members=rows, verdict_rules=manifest.get('verdict_rules') or validate_rules(),
                     thresholds_applied_to_eligibility=not manifest.get('include_below_threshold', False),
                     qualification_schema=QUALIFICATION_SCHEMA, scored=False, native_launch_qualified=False,
                     scope='New-weeks-only verdicts on unseen data; a few weeks is a small sample.')
        return self._write_report(root, value, rows)

    @staticmethod
    def _write_report(root, value, rows):
        write_json(root / 'report.json', value)
        if len(rows) > MAX_PUBLIC:
            return {k: v for k, v in value.items() if k != 'members'} | dict(member_count=len(rows), members_omitted=True,
                                                                             report_path=str(root / 'report.json'))
        return value | dict(report_path=str(root / 'report.json'))

    def _migration_report(self, root, manifest, state):
        """catchup-report for a build migration: its own kind, drift counts, no verdicts (handled explicitly by type)."""
        rows, counts, drift = [], {}, {}
        for spec, item in zip(manifest['members'], state['members']):
            result = read_seed_json(item['result']['path']) if item.get('result') else None
            if result is not None and (result.get('kind') != migration.KIND or result.get('status') != migration.RESULT_STATUS):
                raise ValueError('Build-migration catch-up %s holds a result that is not a %s record: %s'
                                 % (manifest['batch_id'], migration.KIND, item['result']['path']))
            counts[item['status']] = counts.get(item['status'], 0) + 1
            if result:
                drift[result['summary']['drift']] = drift.get(result['summary']['drift'], 0) + 1
            bm = spec.get('build_migration') or {}
            rows.append(dict(alias=spec['alias'], status=item['status'], symbol=spec['tester']['Symbol'], period=spec['tester']['Period'],
                             kind=migration.KIND, provenance=bm.get('provenance'), source_build=bm.get('source_build'),
                             target_build=bm.get('target_build'), original_set=bm.get('original_path'), original_sha256=bm.get('original_sha256'),
                             original_end=spec['original']['evidence_end'], new_end=manifest['evidence_end']['iso'],
                             summary=result['summary'] if result else None, record_path=result['record_path'] if result else None,
                             error=item.get('error'), evidenceEnd=manifest['evidence_end']['iso'],
                             evidenceEndEffective=evidence_end.effective_end(spec['tester']['ToDate'])))
        public = manifest['build_migration']
        value = dict(schema_version=1, batch_id=manifest['batch_id'], mode=MODE, kind=migration.KIND, provenance=public['provenance'],
                     target_build=public['target_build'], status=state['status'], evidence_end=manifest['evidence_end'],
                     counts=counts, drift_counts=drift, tolerances=public.get('tolerances') or migration.public_tolerances(),
                     output_root=manifest.get('output_root'), members=rows, native_launch_qualified=False,
                     scope='Build-migration re-tests: new evidence on the target build with drift against each original. '
                           'Not catch-up verdicts; nothing here carries a status to the original exports.')
        return self._write_report(root, value, rows)
