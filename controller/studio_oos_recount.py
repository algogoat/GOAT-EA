"""oos-rule-recount: re-judge stored OOS catch-ups under every OOS window rule version. Read-only.

A catch-up result stores the ``oos_rule`` its re-test was judged with (studio_catchup._collect). This module reads
a stored catch-up where the catch-up report reads it (``catchups/<id>/manifest.json``, ``state.json`` and each
member's ``<alias>.result.json``), reads each member's original export and re-test unit again (the SET, the equity
CSV and the capture's deals.csv, through ``studio_evidence.read_export``) and judges it with
``studio_oos_windows.judge_retest`` once per version in ``studio_oos_windows.RULE_VERSIONS``. The reply puts the
stored verdict next to each version's, so a rule change is counted before any verdict is used.

Read-only by construction
-------------------------
Every file is opened for reading. Nothing is written, created, renamed or removed: no manifest, state, receipt,
report or cache. No terminal lease is taken, no process is inspected or started and no broker is asked, so it is
safe while research runs on the same terminal. It never calls ``catchup-status`` or ``catchup-report``: both settle
state or write ``report.json``. It also does not require the installed EA or the installation to be the ones the
catch-up ran on (the runner's own reads do): a recount reads stored evidence only.

Never guessed
-------------
A member is judged only from its own stored inputs, each checked against what the catch-up recorded: the result
file against the SHA-256 in ``state.json``, the original export and the re-test SET against their recorded
SHA-256, the original's evidence end against the recorded one. A member whose inputs are missing, moved or
changed is listed ``readable: false`` with the reason and gets no verdict. A catch-up whose manifest or state
cannot be read is listed the same way. Build-migration members hold no verdict and are listed as such.

Self-check
----------
``self_check`` (per catch-up in ``counts`` and over all of them in ``totals``) asks one question: does every judged
file with a stored verdict, judged again under the rule version it was stored with, get that verdict back? It
compares ``judged_with_stored`` files and nothing else; a judged file with no stored ``oos_rule`` (``stored_missing``:
for example a ``not_comparable`` re-test stored before the catch-up hook judged those) is left out, never counted as a
match or a mismatch. ``ok`` is None when it compared no file.

Held-out lock
-------------
Every member's verdicts sit under ``oos_rule`` and every catch-up's counts under ``counts``, both keys the
held-out guard redacts (studio_heldout_guard.METRIC_KEYS), and every block names its ``catchup_id``. The command
(demo_agent ``oos-rule-recount``) guards each catch-up block and builds the totals from the blocks that came back
unredacted (``totals``), so a locked catch-up adds nothing to them.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from studio_agent_mailbox import sharing_retry
from studio_evidence import read_export, unit_paths
from studio_evidence_archive import ArchiveUnreachable, locate
import studio_oos_windows as rule
from studio_seed_results import MAX_MANIFEST_BYTES, MAX_RESULT_BYTES, MAX_STATE_BYTES

SCHEMA = 'goat-oos-rule-recount-v1'
FOLDER = 'catchups'
CATCHUP_ID = re.compile('[A-Za-z0-9_-]{1,80}')
MAX_CATCHUPS = 500
# Catch-up verdicts that are never judged with the OOS rule (studio_catchup.UNJUDGED / CatchupRunner._oos_rule).
UNJUDGED = ('not_comparable', 'unjudged')
MIGRATION_KIND = 'build_migration_retest'
SCOPE = ('Read-only recount: each stored catch-up member judged again from its own stored evidence under every OOS '
         'window rule version. Nothing is written and no stored verdict changes. v1_matches_stored and '
         'v2_matches_stored count, of the judged files with a stored verdict (judged_with_stored), those whose status '
         'under that version equals the stored one. A judged file with no stored verdict (stored_missing) is compared '
         'with nothing. self_check is the reproduction check: every judged file with a stored verdict, judged again '
         'under the rule version it was stored with, matches it (ok); files with no stored verdict are left out of it.')
# The self-check (Claude-Mac, goatai#2750 6789761790): what it compares, in the words every reply carries.
SELF_CHECK_BASIS = ('judged files with a stored verdict, each judged again under the rule version it was stored with; a '
                    'judged file with no stored verdict (stored_missing) is left out, never counted as a match or a mismatch')


class Unreadable(Exception):
    """A catch-up or a member whose stored inputs cannot be read or no longer match what was recorded."""


def label(version):
    return 'v%d' % version


def _io(path):
    """``path`` for reading: the extended-length form on Windows when it is too long for a plain path."""
    text = os.path.abspath(str(path))
    if os.name == 'nt' and len(text) > 240 and not text.startswith('\\\\'):
        return Path('\\\\?\\' + text)
    return Path(text)


def _bytes(path, limit):
    def read():
        with _io(path).open('rb') as stream:
            return stream.read(limit + 1)
    raw = sharing_retry(read)   # a running catch-up can replace its state while this reads: retry that, nothing else
    if len(raw) > limit:
        raise ValueError('%s exceeds its byte bound' % Path(path).name)
    return raw


def _json(raw, name):
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(name + ' is not a JSON object')
    return value


def catchup_ids(root):
    """Every stored catch-up of this controller state: the folders of ``catchups`` that hold a manifest, by name."""
    base = _io(Path(root) / FOLDER)
    if not base.is_dir():
        return []
    return sorted(entry.name for entry in base.iterdir()
                  if CATCHUP_ID.fullmatch(entry.name) and (entry / 'manifest.json').is_file())


def _stored(record):
    """The stored ``oos_rule`` of a member, as the reply shows it (None fields when the result holds none)."""
    if not isinstance(record, dict):
        return dict(present=False, status=None, reasons=None, rule_version=None, in_sample_dd=None)
    return dict(present=True, status=record.get('status'), reasons=record.get('reasons'),
                rule_version=rule.record_rule_version(record), in_sample_dd=record.get('in_sample_dd'))


def _view(result, version):
    """One version's verdict: the judge's own record without its long texts, plus the figures a recount compares.

    Every figure is read from the judge's record by name, so a rule version that states more (the window count and
    ``loss_leg_applied`` on the record itself, a different ``bar.in_sample``) shows it here without a change."""
    windows = result.get('windows') if isinstance(result.get('windows'), dict) else {}
    boos = windows.get('boos') if isinstance(windows.get('boos'), dict) else {}
    foos = windows.get('foos') if isinstance(windows.get('foos'), dict) else {}
    return dict(rule_version=version, status=result.get('status'), reasons=result.get('reasons'),
                in_sample_dd=result.get('in_sample_dd'), in_sample_base=(result.get('bar') or {}).get('in_sample'),
                in_sample_windows=result.get('in_sample_windows', boos.get('in_sample_windows')),
                in_sample_p10=boos.get('in_sample_p10'), loss_leg_applied=result.get('loss_leg_applied'),
                boos_trades=boos.get('trades'), foos_trades=foos.get('trades'),
                foos_judged_through=result.get('foos_judged_through'), windows=windows or None)


def _unit(root, set_path):
    """The re-test unit to read: its SET where it lives now (the verified archive copy when evidence-archive moved
    it), with its equity CSV and deals.csv verified the same way."""
    physical, moved = locate(root, set_path)
    if moved:
        logical = unit_paths(set_path)
        for part in (logical['csv'], logical['goatseq'] / 'manifest.json', logical['goatseq'] / 'deals.csv'):
            locate(root, part)        # size and SHA-256 against the archive manifest; ArchiveUnreachable when they differ
    return physical


def _judge(original, retest, spec, manifest, verdict, version):
    """``CatchupRunner._oos_rule`` for one stored member under one rule version, without its write-side stamps."""
    if verdict in UNJUDGED:
        return dict(status='no_data', reasons=['the re-test was not judged as the same test as the original (%s)' % verdict])
    try:
        return rule.judge_retest(original, retest, tester=spec['original'].get('tester'),
                                 evidence_end=manifest['evidence_end']['iso'], rule_version=version)
    except (OSError, ArchiveUnreachable):
        raise                          # a file that cannot be read is an unreadable member, never a verdict
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return dict(status='no_data', reasons=['could not apply the OOS window rule: ' + str(exc)[:240]])


def _member(root, manifest, spec, item, versions):
    tester = spec.get('tester') if isinstance(spec.get('tester'), dict) else {}
    source = spec.get('original') if isinstance(spec.get('original'), dict) else {}
    row = dict(catchup_id=manifest.get('batch_id'), alias=spec.get('alias'), member_id=spec.get('member_id'),
               member_status=item.get('status'), symbol=tester.get('Symbol'), period=tester.get('Period'),
               original_set=source.get('set_path'), original_set_sha256=source.get('set_sha256'),
               retest_set=None, retest_set_sha256=None, evidence_end=(manifest.get('evidence_end') or {}).get('iso'),
               readable=False, unreadable=None, oos_rule=None)
    try:
        if spec.get('build_migration') or manifest.get('build_migration'):
            raise Unreadable('A build-migration member holds no catch-up verdict; the OOS rule never judged it')
        saved = item.get('result')
        if not isinstance(saved, dict) or not isinstance(saved.get('path'), str):
            raise Unreadable('No stored result: the member is %s' % item.get('status'))
        raw = _bytes(saved['path'], MAX_RESULT_BYTES)
        if hashlib.sha256(raw).hexdigest() != saved.get('sha256'):
            raise Unreadable('The stored result file changed since the catch-up recorded it')
        result = _json(raw, 'The stored result')
        if result.get('kind') == MIGRATION_KIND:
            raise Unreadable('A build-migration record holds no catch-up verdict; the OOS rule never judged it')
        verdict = result.get('verdict') if isinstance(result.get('verdict'), dict) else {}
        row.update(retest_set=result.get('path'), retest_set_sha256=result.get('sha256'))
        stored = _stored(verdict.get('oos_rule'))
        original = retest = None
        if verdict.get('verdict') not in UNJUDGED:
            if not isinstance(source.get('set_path'), str) or not isinstance(result.get('path'), str):
                raise Unreadable('The catch-up recorded no original export or re-test SET path for this member')
            original = read_export(source['set_path'])
            if original['set_sha256'] != source.get('set_sha256') or original['evidence_end'] != source.get('evidence_end'):
                raise Unreadable('The original export changed since the catch-up was prepared')
            retest = read_export(_unit(root, result['path']))
            if retest['set_sha256'] != result.get('sha256'):
                raise Unreadable('The re-test SET changed since the catch-up collected it')
            if not retest.get('csv_path'):
                raise Unreadable('The re-test equity CSV is missing next to its SET')
            if not retest.get('evidence_end'):
                raise Unreadable('The re-test export has no evidence end')
            # Without deals.csv the judges read "trades unavailable" and return no_data, which would count as a failed
            # reproduction of the stored verdict (Codex on GOAT-EA#309). A member whose stored verdict was measured from
            # its capture, or whose capture is recorded complete, must still have the deals; one that never had a
            # capture is judged as it was.
            capture = retest.get('capture') if isinstance(retest.get('capture'), dict) else {}
            kept = bool(capture.get('complete') and capture.get('path'))
            measured = isinstance(verdict.get('oos_rule'), dict) and verdict['oos_rule'].get('trade_source') == 'capture_deals'
            if (kept or measured) and not (kept and _io(Path(capture['path']).parent / 'deals.csv').is_file()):
                raise Unreadable("The re-test capture's deals.csv is missing (the capture is recorded complete, or the "
                                 'stored verdict was measured from it)')
        judged ={label(version): _view(_judge(original, retest, spec, manifest, verdict.get('verdict'), version), version)
                  for version in versions}
    except Unreadable as exc:
        row['unreadable'] = str(exc)
        return row
    except (OSError, ValueError, KeyError, TypeError, ArchiveUnreachable) as exc:
        row['unreadable'] = 'Stored inputs cannot be read: ' + (str(exc)[:300] or type(exc).__name__)
        return row
    first, last = judged[label(versions[0])], judged[label(versions[-1])]
    change = None
    if len(versions) > 1:
        change = ('gained' if last['status'] == 'pass' and first['status'] != 'pass' else
                  'lost' if first['status'] == 'pass' and last['status'] != 'pass' else 'unchanged')
    row.update(readable=True, oos_rule=dict(catchup_verdict=verdict.get('verdict'), stored=stored, **judged, change=change,
                                            **{label(version) + '_matches_stored':
                                               (judged[label(version)]['status'] == stored['status'] if stored['present'] else None)
                                               for version in versions}))
    return row


def _stored_version_key(version):
    """The self-check's key for a stored rule version: 'v1', 'v2', ...; a version the module cannot name is kept as
    written ('unknown:...'), so it is checked and can only mismatch, never match another version's column."""
    return label(version) if type(version) is int else 'unknown:%r' % (version,)


def self_check(by_version, excluded):
    """The reproduction check from per-stored-version ``{checked, matches}``: ``ok`` when every checked file matches,
    None when there was nothing to check (a check that compared nothing is not a pass)."""
    checked = sum(entry['checked'] for entry in by_version.values())
    matches = sum(entry['matches'] for entry in by_version.values())
    return dict(basis=SELF_CHECK_BASIS, checked=checked, matches=matches, mismatches=checked - matches,
                ok=None if not checked else matches == checked, excluded_stored_missing=excluded,
                by_stored_version={key: dict(by_version[key]) for key in sorted(by_version)})


def count(rows, versions):
    """Counts over one catch-up's member rows. Pass counts cover the re-judged (readable) members only, so the
    stored and the per-version figures are over the same files; ``unreadable`` counts the rest.

    ``judged_with_stored`` is how many judged files carry a stored verdict; ``stored_missing`` how many do not. Each
    ``<version>_matches_stored`` counts, of the ``judged_with_stored`` files, those whose status under that version
    equals the stored one. ``self_check`` compares each of those files with the version it was stored under; a file
    with no stored verdict is in neither."""
    judged = [row for row in rows if row['readable']]
    stored = [row for row in judged if row['oos_rule']['stored']['present']]
    passes = dict(stored=sum(row['oos_rule']['stored']['status'] == 'pass' for row in judged))
    result = dict(members=len(rows), judged=len(judged), unreadable=len(rows) - len(judged),
                  judged_with_stored=len(stored), stored_missing=len(judged) - len(stored))
    for version in versions:
        name = label(version)
        passes[name] = sum(row['oos_rule'][name]['status'] == 'pass' for row in judged)
        result[name + '_matches_stored'] = sum(row['oos_rule'][name + '_matches_stored'] is True for row in stored)
    by_version = {}
    for row in stored:
        key = _stored_version_key(row['oos_rule']['stored']['rule_version'])
        entry = by_version.setdefault(key, dict(checked=0, matches=0))
        entry['checked'] += 1
        entry['matches'] += row['oos_rule'].get(key + '_matches_stored') is True
    compared = [label(versions[0]), label(versions[-1])] if len(versions) > 1 else None
    result.update({'pass': passes, 'compared': compared,
                   'gained': sum(row['oos_rule']['change'] == 'gained' for row in judged) if compared else None,
                   'lost': sum(row['oos_rule']['change'] == 'lost' for row in judged) if compared else None,
                   'self_check': self_check(by_version, result['stored_missing'])})
    return result


def recount_catchup(root, catchup_id, versions=None):
    """One stored catch-up as a reply block: its members re-judged, or ``readable: false`` with the reason."""
    versions = tuple(rule.RULE_VERSIONS if versions is None else versions)
    block = dict(catchup_id=catchup_id, readable=False, unreadable=None, status=None, evidence_end=None, counts=None, members=[])
    try:
        if not isinstance(catchup_id, str) or not CATCHUP_ID.fullmatch(catchup_id):
            raise Unreadable('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
        folder = Path(root) / FOLDER / catchup_id
        manifest_raw = _bytes(folder / 'manifest.json', MAX_MANIFEST_BYTES)
        manifest = _json(manifest_raw, 'manifest.json')
        state = _json(_bytes(folder / 'state.json', MAX_STATE_BYTES), 'state.json')
        if state.get('manifest_sha256') != hashlib.sha256(manifest_raw).hexdigest():
            raise Unreadable('state.json belongs to a different manifest.json')
        specs, items = manifest.get('members'), state.get('members')
        if (manifest.get('batch_id') != catchup_id or state.get('batch_id') != catchup_id
                or not isinstance(specs, list) or not isinstance(items, list)
                or [(m.get('member_id'), m.get('alias')) for m in specs] != [(m.get('member_id'), m.get('alias')) for m in items]):
            raise Unreadable('The catch-up manifest and state do not name the same members')
        if not isinstance((manifest.get('evidence_end') or {}).get('iso'), str):
            raise Unreadable('The catch-up manifest records no evidence end')
    except Unreadable as exc:
        block['unreadable'] = str(exc)
        return block
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        block['unreadable'] = 'The stored catch-up cannot be read: ' + (str(exc)[:300] or type(exc).__name__)
        return block
    rows = [_member(root, manifest, spec, item, versions) for spec, item in zip(specs, items)]
    block.update(readable=True, status=state.get('status'), evidence_end=manifest['evidence_end']['iso'],
                 counts=count(rows, versions), members=rows)
    return block


def totals(blocks, versions=None):
    """Totals over the catch-up blocks whose counts are still numbers: a block the held-out guard redacted (its
    ``counts`` became a lock marker) or that could not be read adds nothing and is named instead."""
    versions = tuple(rule.RULE_VERSIONS if versions is None else versions)
    counted = [block for block in blocks if isinstance(block.get('counts'), dict) and 'members' in block['counts']]
    names = ['stored'] + [label(version) for version in versions]
    compared = [label(versions[0]), label(versions[-1])] if len(versions) > 1 else None
    result = dict(catchups=len(blocks), counted_catchups=len(counted),
                  locked_catchups=[block.get('catchup_id') for block in blocks
                                   if isinstance(block.get('counts'), dict) and block['counts'].get('locked')],
                  unreadable_catchups=[block.get('catchup_id') for block in blocks if block.get('readable') is False])
    for key in ('members', 'judged', 'unreadable', 'judged_with_stored', 'stored_missing'):
        result[key] = sum(block['counts'][key] for block in counted)
    for version in versions:
        key = label(version) + '_matches_stored'
        result[key] = sum(block['counts'][key] for block in counted)
    by_version = {}
    for block in counted:
        for key, entry in block['counts']['self_check']['by_stored_version'].items():
            total = by_version.setdefault(key, dict(checked=0, matches=0))
            total['checked'] += entry['checked']
            total['matches'] += entry['matches']
    result.update({'pass': {name: sum(block['counts']['pass'][name] for block in counted) for name in names},
                   'compared': compared,
                   'gained': sum(block['counts']['gained'] for block in counted) if compared else None,
                   'lost': sum(block['counts']['lost'] for block in counted) if compared else None,
                   'self_check': self_check(by_version, result['stored_missing'])})
    return result


def recount(root, catchup_ids_wanted=None, *, every=False, guard=None):
    """The ``oos-rule-recount`` reply for the named catch-ups (or ``every`` stored one) of one controller state.

    ``guard(block)`` is the held-out guard for one catch-up block (demo_agent passes ``guard_output``); the totals
    are built from the guarded blocks.
    """
    if every == bool(catchup_ids_wanted):
        raise ValueError('oos-rule-recount takes --catchup-id (repeatable) or --all, not both and not neither')
    wanted = catchup_ids(root) if every else list(catchup_ids_wanted)
    if len(wanted) != len(set(wanted)):
        raise ValueError('A catch-up ID is named twice')
    if len(wanted) > MAX_CATCHUPS:
        raise ValueError('At most %d catch-ups in one recount; name fewer' % MAX_CATCHUPS)
    for catchup_id in wanted:
        if not isinstance(catchup_id, str) or not CATCHUP_ID.fullmatch(catchup_id):
            raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
        if not _io(Path(root) / FOLDER / catchup_id).is_dir():
            raise ValueError('Unknown catch-up ' + catchup_id + '; nothing was read')
    versions = tuple(rule.RULE_VERSIONS)
    blocks = [recount_catchup(root, catchup_id, versions) for catchup_id in wanted]
    if guard is not None:
        blocks = [guard(block) for block in blocks]
    return dict(schema=SCHEMA, read_only=True, writes=False, rule=rule.EVALUATION, rule_versions=list(versions),
                default_rule_version=rule.RULE_VERSION, catchups=blocks, totals=totals(blocks, versions), scope=SCOPE)
