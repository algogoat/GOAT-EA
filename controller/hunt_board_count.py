"""Count a hunt board from one folder of record files, and refuse to count a file nobody has explained.

Why (Claude-Mac, GOAT-EA#315 comment 6791427047, ruling 4b): a board number is a claim about files. It has to come
from a mechanism that stops on a file whose evidence does not add up, not from a tally a person keeps. This module is
that mechanism. It reads only the folder given by --input: never a terminal, the controller state, MT5 or the registry.
It writes nothing unless --output / --markdown name files that do not exist yet.

Input folder (schema ``hunt-board-input-v1``; a close step cuts these records from its own audited outputs):

  rules.json              cap, machines (their order is the export order across machines), disclosure_reason,
                          disclosure_ruling, prove_reason, report_ruling, real_ticks, reading, o3_ruling
  pool.json               the files already on the board: source, asset, family, group
  judged.json             every file the round's catch-up judged: machine, part, index, position (the product's export
                          order), catchup, alias, source, asset, family, template, member, held_group (the held group a
                          second file belongs to, else null), rule (pass / fail / not_eligible_yet), export_bar,
                          prove_status, set_sha256, duplicate
  prove-exports.json      every export of the round's Prove reports: set_path, machine, part, index, status, reason,
                          source_ledger, ini_ledger, export_ledger (the Ledger_Mode line of the member's source SET, of
                          its start config and of the exported SET; null when the line is absent)
  disclosed-exports.json  the ruled tags: {exports: [{set_path, reason, ruling, ...}]}
  holdout.json            {members: [...]}: per judged file, its export SET against the SET the catch-up re-test wrote
  reports.json            {runs: [...]}: per catch-up run, MT5's report inputs against the run's effective inputs and
                          its start-config pin
  o3pool.json             {members: [...]}: migrated older files (candidate, group, duplicate hits, inputs, family)
  journals.json           per machine: tester-journal blocks expected / matched, gaps, flagged lines, proven

How a file is counted: a judged file with rule ``pass`` that passed the export bar and is no duplicate is counted while
its group has room (cap minus what the pool already holds in that group), in export order; later passes are reserves.
A counted file whose Prove report says ``unverified`` is shown as disclosed, with the ruled reason. A counted file is
proven by its machine's tester journal, or by its own identical MT5 report when the ruling in rules.json lets reports
stand in; a counted file with neither is shown apart and not counted. Migrated files are counted up to the cap per group
in the order of o3pool.json.

It REFUSES (exit 3; the rule, the file and the reason on stdout and stderr) when:

  R1  disclosed-exports.json is missing or unreadable;
  R2  an export the Prove report calls ``unverified`` carries no tag;
  R3  a tag is wrong: its export is not unverified for the ruled Prove reason, its reason or ruling text is not the
      ruled one, or the export is not an inherited-ledger case (source and start config silent, export states 1);
  R4  a counted file has no hold-out record, or the record shows the hold-out did not run on the inputs of its export
      (an input only in one SET, another value, an appended or inherited input, another ledger, another values hash,
      same_inputs false), or the record is for other SET bytes;
  R5  a counted file (round or migrated) has no MT5-report record, or its record failed;
  R6  a counted migrated file has a duplicate hit, or its re-test did not run the inputs its SET states.

Nothing here judges a strategy: the verdicts, the duplicate check and the input comparisons are the close's records.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

SCHEMA = 'hunt-board-input-v1'
FILES = ('rules.json', 'pool.json', 'judged.json', 'prove-exports.json', 'holdout.json', 'reports.json', 'o3pool.json',
         'journals.json')
DISCLOSED = 'disclosed-exports.json'
EMPTY_DIFF = {'only_first': ['?'], 'only_second': [], 'different': {}}


class Refused(Exception):
    """One refusal: the rule (R1..R6), the file it is about and the reason."""

    def __init__(self, rule, path, why):
        super().__init__('%s: %s: %s' % (rule, path, why))
        self.rule, self.path, self.why = rule, str(path), why


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load(folder):
    """The input folder's records; a missing record file is a plain error, not a refusal (nothing was counted)."""
    folder = Path(folder)
    data = {}
    for name in FILES:
        path = folder / name
        if not path.is_file():
            raise ValueError('Board input folder has no ' + name + ': ' + str(folder))
        data[name[:-5]] = read_json(path)
    if data['rules'].get('schema') != SCHEMA:
        raise ValueError('Board input folder is not ' + SCHEMA + ': ' + str(folder))
    return data


def cap_states(rules, pool, judged):
    """{source: counted | reserve | duplicate | not_counted_export_bar} for every pass, in export order."""
    rank = {machine: number for number, machine in enumerate(rules['machines'])}
    held = Counter(p['group'] for p in pool)
    used, states = Counter(), {}
    for x in sorted(judged, key=lambda x: (x['part'], rank[x['machine']], x['index'], x['position'])):
        if x['rule'] != 'pass':
            continue
        group = ('held', x['held_group']) if x.get('held_group') else ('new', x['member'])
        room = max(0, rules['cap'] - (held[x['held_group']] if x.get('held_group') else 0))
        if x['export_bar'] != 'passed':
            state = 'not_counted_export_bar'
        elif x.get('duplicate'):
            state = 'duplicate'
        elif used[group] < room:
            used[group] += 1
            state = 'counted'
        else:
            state = 'reserve'
        states[x['source'].lower()] = state
    return states


def metrics(pool, counted, migrated=()):
    assets = Counter(p['asset'] for p in pool) + Counter(x['asset'] for x in counted) + Counter(x['symbol'] for x in migrated)
    families = (Counter(p['family'] for p in pool) + Counter(x['family'] for x in counted)
                + Counter(x.get('family') or 'unknown' for x in migrated))
    groups = ({('pool', p['group']) for p in pool}
              | {('pool', x['held_group']) if x.get('held_group') else ('new', x['member']) for x in counted}
              | {('o3', x['group']) for x in migrated})
    total = len(pool) + len(counted) + len(migrated)
    top = max(assets.items(), key=lambda item: item[1])
    clean = sum(x['prove_status'] != 'unverified' for x in counted)
    return dict(clean=len(pool) + clean, disclosed=len(counted) - clean, o3pool=len(migrated), total=total,
                groups=len(groups), o3_groups=len({g for g in groups if g[0] == 'o3'}),
                new_groups=sorted(g[1] for g in groups if g[0] == 'new'),
                new_assets=sorted(set(assets) - {p['asset'] for p in pool}), assets=len(assets),
                assets_detail=dict(sorted(assets.items())),
                largest_asset=dict(asset=top[0], files=top[1], share=round(top[1] / total, 4)),
                families=dict(families), family_unknown=families.get('unknown', 0),
                rr_share=round(families['RangeReversion'] / total, 4))


def count(folder):
    """The board of one input folder. Raises Refused; never returns a number for a folder that fails a rule."""
    folder = Path(folder)
    data = load(folder)
    rules, pool, judged = data['rules'], data['pool'], data['judged']
    reason, ruling = rules['disclosure_reason'], rules['disclosure_ruling']
    # R1
    disclosed_path = folder / DISCLOSED
    try:
        tags_file = read_json(disclosed_path)
        tags = {t['set_path'].lower(): t for t in tags_file['exports']}
        if len(tags) != len(tags_file['exports']):
            raise ValueError('an export is tagged twice')
    except Exception as exc:
        raise Refused('R1', disclosed_path, 'disclosed-exports file missing or unreadable (%s)' % type(exc).__name__)
    exports = {e['set_path'].lower(): e for e in data['prove-exports']}
    unverified = {key: e for key, e in exports.items() if e['status'] == 'unverified'}
    # R2
    for key, e in sorted(unverified.items()):
        if key not in tags:
            raise Refused('R2', e['set_path'], 'unverified in the Prove report (%s %s member %d: %s) and not tagged in %s'
                          % (e['machine'], e['part'], e['index'], e['reason'], disclosed_path))
    # R3
    for key, tag in sorted(tags.items()):
        e = unverified.get(key)
        if e is None:
            raise Refused('R3', tag['set_path'], 'tagged, but the Prove report does not call this export unverified')
        if e['reason'] != rules['prove_reason']:
            raise Refused('R3', tag['set_path'], 'tagged, but its Prove reason is %r, not %r' % (e['reason'], rules['prove_reason']))
        if tag.get('reason') != reason or tag.get('ruling') != ruling:
            raise Refused('R3', tag['set_path'], 'tag reason / ruling is not %r / %r' % (reason, ruling))
        if e['source_ledger'] is not None or e['ini_ledger'] is not None or e['export_ledger'] != '1':
            raise Refused('R3', tag['set_path'], 'not an inherited-ledger case (source %s, start config %s, export %s)'
                          % (e['source_ledger'], e['ini_ledger'], e['export_ledger']))
    # R4
    states = cap_states(rules, pool, judged)
    passes = [x for x in judged if x['rule'] == 'pass']
    counted = [x for x in passes if states[x['source'].lower()] == 'counted']
    proof = {r['source'].lower(): r for r in data['holdout']['members'] if r.get('judged')}
    for x in counted:
        r = proof.get(x['source'].lower())
        if r is None:
            raise Refused('R4', x['source'], 'counted, but it has no hold-out record')
        d = r.get('retest_vs_original') or EMPTY_DIFF
        e = r.get('retest_effective_vs_original_effective') or EMPTY_DIFF
        problems = []
        if r.get('original_set_sha256') != x['set_sha256']:
            problems.append('record is for other SET bytes')
        if not r.get('same_inputs'):
            problems.append('same_inputs is not true: %s' % r.get('reasons'))
        if d['only_first'] or d['only_second'] or d['different']:
            problems.append('re-test SET differs from the export SET: %s' % {k: d[k] for k in ('only_first', 'only_second', 'different')})
        if e['only_first'] or e['only_second'] or e['different']:
            problems.append('effective inputs of the two runs differ: %s' % {k: e[k] for k in ('only_first', 'only_second', 'different')})
        if r.get('appended_differ') or r.get('inherited_in_retest'):
            problems.append('appended / inherited input: %s %s' % (r.get('appended_differ'), r.get('inherited_in_retest')))
        if (r.get('original_ledger_mode') != r.get('retest_ledger_mode')
                or r.get('original_run_effective_ledger_mode') != r.get('retest_run_effective_ledger_mode')):
            problems.append('ledger differs: export %s / hold-out %s (effective %s / %s)' % (
                r.get('original_ledger_mode'), r.get('retest_ledger_mode'),
                r.get('original_run_effective_ledger_mode'), r.get('retest_run_effective_ledger_mode')))
        if r.get('original_values_sha256') != r.get('retest_values_sha256'):
            problems.append('values hash differs')
        if problems:
            raise Refused('R4', x['source'], 'counted, but its hold-out did not run on the inputs of its export: ' + '; '.join(problems))
        if x['prove_status'] == 'unverified' and (r.get('retest_ledger_mode') != '1' or x['source'].lower() not in tags):
            raise Refused('R4', x['source'], 'disclosed file whose hold-out is not on PositionJoin or whose tag is missing')
    # R5 / R6
    reports = {(r['catchup'], r['alias']): r for r in data['reports']['runs']}

    def report_ok(catchup, alias, source):
        r = reports.get((catchup, alias))
        if r is None:
            raise Refused('R5', source, 'counted, but run %s %s has no MT5-report record' % (catchup, alias))
        if not r.get('passed') or r.get('problems') or (r.get('source') or '').lower() != source.lower():
            raise Refused('R5', source, 'counted, but the MT5 report of run %s %s does not match its effective inputs / start config: %s'
                          % (catchup, alias, r.get('problems') or 'record is for another file or not passed'))
        return r
    for x in counted:
        x['report'] = report_ok(x['catchup'], x['alias'], x['source'])
    used = Counter()
    migrated, migrated_reserve = [], []
    for r in data['o3pool']['members']:
        if not r.get('candidate'):
            continue
        used[r['group']] += 1
        (migrated if used[r['group']] <= rules['cap'] else migrated_reserve).append(r)
    for r in migrated:
        if r.get('duplicate_hits') or not r.get('condition1_no_duplicate'):
            raise Refused('R6', r['original_set'], 'counted migrated file with a duplicate hit: %s' % r.get('duplicate_hits'))
        if not r.get('same_inputs') or not r.get('condition2_inputs') or r.get('inherited_in_retest') or r.get('appended_differ'):
            raise Refused('R6', r['original_set'], 'counted migrated file whose re-test did not run the inputs its SET states: %s' % r.get('reasons'))
        report_ok(r['catchup'], r['alias'], r['original_set'])
    # proof of each counted round file: its machine's tester journal, else its own identical MT5 report
    journals = data['journals']
    for x in counted:
        if journals[x['machine']]['proven']:
            x['proof'] = 'tester journal'
        elif x['report'].get('history_quality') == rules['real_ticks']:
            x['proof'] = 'MT5 report inputs identical (%s)' % rules['report_ruling']
        else:
            x['proof'] = None
    proven = [x for x in counted if x['proof']]
    apart = [x for x in counted if not x['proof']]
    machines = rules['machines']
    kind = lambda x: 'disclosed' if x['prove_status'] == 'unverified' else 'clean'
    return dict(
        schema='hunt-board-v1', input=str(folder), round=rules.get('round'), reading=rules.get('reading'), rulings=ruling,
        pool=dict(files=len(pool), groups=len({p['group'] for p in pool}), assets=len({p['asset'] for p in pool})),
        judged=len(judged), passes=len(passes), journals=journals,
        counted=metrics(pool, proven, migrated), round_only=metrics(pool, proven),
        o3pool=dict(counted=len(migrated), reserve=[r['alias'] for r in migrated_reserve], groups=len({r['group'] for r in migrated}),
                    by_asset=dict(sorted(Counter(r['symbol'] for r in migrated).items())), ruling=rules.get('o3_ruling')),
        proof_by_machine={m: sorted({x['proof'] or 'none' for x in counted if x['machine'] == m}) for m in machines},
        report_crosscheck=dict(runs=len(reports), passed=sum(1 for r in reports.values() if r.get('passed'))),
        apart=dict(machines=sorted({x['machine'] for x in apart}), reason='no tester-journal proof and no identical MT5 report: no proof, no count',
                   clean=sum(kind(x) == 'clean' for x in apart), disclosed=sum(kind(x) == 'disclosed' for x in apart), files=len(apart)),
        counted_by_machine={m: dict(clean=sum(1 for x in counted if x['machine'] == m and kind(x) == 'clean'),
                                    disclosed=sum(1 for x in counted if x['machine'] == m and kind(x) == 'disclosed')) for m in machines},
        reserves={m: sum(1 for x in passes if x['machine'] == m and states[x['source'].lower()] == 'reserve') for m in machines},
        reserves_disclosed=sum(1 for x in passes if states[x['source'].lower()] == 'reserve' and kind(x) == 'disclosed'),
        clean_counted_with_ledger_stated_in_their_own_source=sum(
            1 for x in counted if kind(x) == 'clean' and proof[x['source'].lower()].get('original_ledger_mode') == '1'),
        unverified_exports=len(unverified), tagged=len(tags), duplicates=sum(1 for x in judged if x.get('duplicate')),
        files=[dict(machine=x['machine'], part=x['part'], index=x['index'], position=x['position'], alias=x['alias'], asset=x['asset'],
                    family=x['family'], template=x['template'], group=x['held_group'] or 'new:' + x['member'],
                    state=states[x['source'].lower()], kind=kind(x), disclosure=reason if kind(x) == 'disclosed' else None,
                    proof=x.get('proof'), set_sha256=x['set_sha256'], source=x['source']) for x in passes],
        o3_files=[dict(catchup=r['catchup'], alias=r['alias'], asset=r['symbol'], group=r['group'],
                       state='counted' if r in migrated else 'reserve', template=r.get('template'), family=r.get('family') or 'unknown',
                       family_established=(r.get('family_established') or 'not established').split(':')[0],
                       set_sha256=r['original_set_sha256'], source=r['original_set'])
                  for r in migrated + migrated_reserve])


def markdown(b):
    c, part, a = b['counted'], b['round_only'], b['apart']
    row = lambda m: '%d | %d | %d | %s %d (%.1f%%) | %.1f%%' % (
        m['total'], m['groups'], m['assets'], m['largest_asset']['asset'], m['largest_asset']['files'],
        100 * m['largest_asset']['share'], 100 * m['rr_share'])
    out = ['# Board: %s' % b['round'], '',
           'Written by controller/hunt_board_count.py. It refuses on an untagged unverified export, a counted file whose hold-out '
           'inputs differ from its export, a counted file without an identical MT5 report, and a migrated file with a duplicate or other inputs.', '',
           'Reading: %s. Ruling: %s. Pool before: %d files / %d groups / %d assets. Judged %d, passes %d, duplicates %d.'
           % (b['reading'], b['rulings'], b['pool']['files'], b['pool']['groups'], b['pool']['assets'], b['judged'], b['passes'], b['duplicates']), '',
           '| | Clean | Disclosed | Migrated | Total | Groups | Assets | Largest asset | RangeReversion share |',
           '|---|---:|---:|---:|---:|---:|---:|---|---:|',
           '| **Counted** | %d | %d | %d | **%s%s |' % (c['clean'], c['disclosed'], c['o3pool'], row(c).replace(' |', '** |', 1),
                                                          (' (%d of unknown family)' % c['family_unknown']) if c['family_unknown'] else ''),
           '| of which pool + round | %d | %d | | %s |' % (part['clean'], part['disclosed'], row(part)),
           '| Apart: %s | %d | %d | | %d | | | | |' % (', '.join(a['machines']) or 'none', a['clean'], a['disclosed'], a['files']), '',
           '- **%d clean + %d disclosed + %d migrated = %d**. Apart (%s): %d.' % (c['clean'], c['disclosed'], c['o3pool'], c['total'], a['reason'], a['files']),
           '- Family mix, all %d counted: %s; unknown family: %d.' % (c['total'], dict(sorted(c['families'].items(), key=lambda item: -item[1])), c['family_unknown']),
           '- Assets: %s. New assets: %s.' % (c['assets_detail'], ', '.join(c['new_assets']) or 'none'),
           '- Counted by machine (clean / disclosed): ' + ', '.join('%s %d / %d' % (m, v['clean'], v['disclosed']) for m, v in b['counted_by_machine'].items())
           + '. Reserves over the cap: ' + ', '.join('%s %d' % item for item in b['reserves'].items())
           + '; migrated reserve: %s.' % (', '.join(b['o3pool']['reserve']) or 'none'),
           '- Proof of the catch-up tests: ' + '; '.join('%s: %s' % (m, ', '.join(v) or 'no counted file') for m, v in b['proof_by_machine'].items())
           + '. MT5-report records: %d of %d identical.' % (b['report_crosscheck']['passed'], b['report_crosscheck']['runs']),
           '- Unverified exports in the Prove reports: %d, tags: %d.' % (b['unverified_exports'], b['tagged']), '',
           '## Every pass (export order)', '', '| Machine | Part | Member | Export | Catch-up alias | Asset | Template | Group | State | Kind | Proof |',
           '|---|---|---:|---:|---|---|---|---|---|---|---|']
    for f in b['files']:
        out.append('| %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | %s |' % (
            f['machine'], f['part'], f['index'], f['position'], f['alias'], f['asset'], f['template'], f['group'], f['state'],
            f['kind'] + (' (%s)' % f['disclosure'] if f['disclosure'] else ''), f['proof'] or ''))
    out += ['', '## Migrated files', '', '| Catch-up | Alias | Asset | Template | Family | Established | State |', '|---|---|---|---|---|---|---|']
    for f in b['o3_files']:
        out.append('| %s | %s | %s | %s | %s | %s | %s |' % (f['catchup'], f['alias'], f['asset'], f['template'], f['family'], f['family_established'], f['state']))
    return '\n'.join(out) + '\n'


def _write_new(path, text):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:   # never overwrites a board that was already written
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Count a hunt board from one input folder; exit 3 on a refusal.')
    parser.add_argument('--input', required=True, help='board input folder (hunt-board-input-v1)')
    parser.add_argument('--output', help='write the board as JSON to this new file')
    parser.add_argument('--markdown', help='write the board as Markdown to this new file')
    args = parser.parse_args(argv)
    try:
        board = count(args.input)
    except Refused as exc:
        print('REFUSED ' + str(exc))
        print('REFUSED ' + str(exc), file=sys.stderr)
        return 3
    if args.output:
        _write_new(args.output, json.dumps(board, indent=2) + '\n')
    if args.markdown:
        _write_new(args.markdown, markdown(board))
    print(json.dumps({key: value for key, value in board.items() if key not in ('files', 'o3_files')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
