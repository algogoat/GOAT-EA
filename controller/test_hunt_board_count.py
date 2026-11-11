"""The hunt board counter counts what the records support and refuses the rest.

The fixture (controller/fixtures/hunt-board) is cut from the real records of round 13a (2026-11-11): a clean group
with two reserves, a clean group with unjudged-eligible files, an inherited-ledger (disclosed) member on a machine
with no tester journal, a disclosed new group, and six migrated files of which one folder holds four passes.
Each refusal test alters one record of a copy and expects the counter to name that file.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import hunt_board_count as board

FIXTURE = Path(__file__).parent / 'fixtures' / 'hunt-board'
CLEAN_COUNTED = 'Cc7f257b6799f4936_00006'           # T3 p1 member 3, trail on EURGBP: Legacy ledger everywhere
THRUSH = ('Cc7f257b6799f4936_00080', 'Cc7f257b6799f4936_00081', 'Cc7f257b6799f4936_00082')   # T3 p2 member 15, export order
DISCLOSED_BANKER = 'C4bf9008d5a8d4835_00004'        # Banker p1 member 10, brook on WS30: inherited ledger, counted
MIGRATED_COUNTED = 'C1d6ad0a6f9114d8a_00069'        # crane on WS30, first of four passes in one folder
MIGRATED_RESERVE = 'C1d6ad0a6f9114d8a_00075'        # the fourth


class Folder:
    """A private copy of the fixture whose record files a test may alter."""

    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'board-input'
        shutil.copytree(FIXTURE, self.path)

    def read(self, name):
        return json.loads((self.path / name).read_text(encoding='utf-8'))

    def write(self, name, data):
        (self.path / name).write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8', newline='\n')

    def alter(self, name, change):
        data = self.read(name)
        change(data)
        self.write(name, data)


def judged(folder, alias):
    return next(x for x in folder.read('judged.json') if x['alias'] == alias)


class HuntBoardCountTests(unittest.TestCase):
    def refused(self, folder):
        with self.assertRaises(board.Refused) as caught:
            board.count(folder.path)
        return caught.exception

    def test_fixture_is_cut_from_real_records_and_counts(self):
        b = board.count(FIXTURE)
        c = b['counted']
        self.assertEqual((c['clean'], c['disclosed'], c['o3pool'], c['total'], c['groups'], c['assets']), (9, 3, 4, 16, 7, 4))
        self.assertEqual(b['pool'], dict(files=6, groups=4, assets=4))
        self.assertEqual((b['judged'], b['passes'], b['unverified_exports'], b['tagged']), (13, 9, 5, 5))
        self.assertEqual(c['largest_asset'], dict(asset='WS30', files=7, share=0.4375))
        self.assertEqual(c['families'], {'RangeReversion': 8, 'TrendPullback': 3, 'CounterTrend': 4, 'DualRSI': 1})
        self.assertEqual((c['rr_share'], c['family_unknown']), (0.5, 0))
        self.assertEqual(c['new_groups'], ['Rcc6969deafa4926d3085'])
        self.assertEqual(b['apart']['files'], 0)

    def test_cap_counts_in_export_order_and_keeps_the_rest_as_reserves(self):
        b = board.count(FIXTURE)
        states = {f['alias']: (f['state'], f['kind']) for f in b['files']}
        # held group Ra128d8877c0ec5e29c2e already holds 2: one of three clean passes fits
        self.assertEqual([states[a] for a in THRUSH], [('counted', 'clean'), ('reserve', 'clean'), ('reserve', 'clean')])
        # held group R48b97122d7d7028944f7 holds 1: two of three inherited-ledger passes fit, each disclosed
        brook = sorted(v for a, v in states.items() if a.startswith('C4bf9008d5a8d4835_'))
        self.assertEqual(brook, [('counted', 'disclosed'), ('counted', 'disclosed'), ('reserve', 'disclosed')])
        self.assertEqual(b['reserves'], dict(t3=2, banker=1))
        disclosed = [f for f in b['files'] if f['kind'] == 'disclosed' and f['state'] == 'counted']
        self.assertEqual({f['disclosure'] for f in disclosed}, {'ledger PositionJoin, inherited'})
        self.assertEqual(len(disclosed), 3)
        # migrated: four passes in one folder, the fourth is the reserve
        self.assertEqual(b['o3pool']['reserve'], [MIGRATED_RESERVE])
        self.assertEqual(sum(f['state'] == 'counted' for f in b['o3_files']), 4)
        self.assertNotIn('C1d6ad0a6f9114d8a_00001', {f['alias'] for f in b['o3_files']})   # failed its hold-out: not a candidate

    def test_a_pool_file_more_in_the_group_turns_a_counted_file_into_a_reserve(self):
        folder = Folder(self)
        folder.alter('pool.json', lambda pool: pool.append(dict(pool[0], source=pool[0]['source'] + '.copy', group='R82bfad4262fc4d3fecf5')))
        b = board.count(folder.path)
        trail = [f['state'] for f in b['files'] if f['group'] == 'R82bfad4262fc4d3fecf5']
        self.assertEqual(trail, ['counted', 'reserve'])

    def test_r1_refuses_without_the_tag_file(self):
        folder = Folder(self)
        (folder.path / board.DISCLOSED).unlink()
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path), ('R1', str(folder.path / board.DISCLOSED)))

    def test_r2_refuses_an_untagged_unverified_export_and_names_it(self):
        tags = json.loads((FIXTURE / board.DISCLOSED).read_text(encoding='utf-8'))['exports']
        for position in range(len(tags)):
            folder = Folder(self)
            folder.alter(board.DISCLOSED, lambda data: data['exports'].pop(position))
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R2', tags[position]['set_path'].lower()))

    def test_r3_refuses_a_tag_on_a_clean_export_another_reason_or_a_stated_ledger(self):
        clean = judged(Folder(self), CLEAN_COUNTED)['source']
        folder = Folder(self)
        folder.alter(board.DISCLOSED, lambda data: data['exports'].append(dict(data['exports'][0], set_path=clean)))
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R3', clean.lower()))
        folder = Folder(self)
        folder.alter(board.DISCLOSED, lambda data: data['exports'][1].update(reason='some other reason'))
        self.assertEqual(self.refused(folder).rule, 'R3')
        folder = Folder(self)   # the member's own source states the ledger: that is not an inherited value
        folder.alter('prove-exports.json', lambda rows: [r.update(source_ledger='1') for r in rows if r['status'] == 'unverified'])
        self.assertEqual(self.refused(folder).rule, 'R3')

    def alter_holdout(self, alias, change):
        folder = Folder(self)
        source = judged(folder, alias)['source']

        def apply(data):
            hit = [r for r in data['members'] if r['source'].lower() == source.lower()]
            self.assertEqual(len(hit), 1)
            change(hit[0])
        folder.alter('holdout.json', apply)
        return folder, source

    def test_r4_refuses_a_clean_file_whose_holdout_ran_on_an_inherited_ledger(self):
        def inherit(r):   # what a hold-out on PositionJoin leaves behind: the EA writes Ledger_Mode=1 into the re-test SET
            self.assertIsNone(r['original_ledger_mode'])
            r['retest_ledger_mode'] = r['retest_run_effective_ledger_mode'] = '1'
            r['retest_vs_original']['only_second'] = ['Ledger_Mode']
            r['inherited_in_retest'] = r['appended_differ'] = ['Ledger_Mode']
        folder, source = self.alter_holdout(CLEAN_COUNTED, inherit)
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R4', source.lower()))
        self.assertIn('Ledger_Mode', refusal.why)

    def test_r4_refuses_on_the_flag_alone_another_value_other_bytes_or_no_record(self):
        for change in (lambda r: r.update(same_inputs=False, reasons=['altered']),
                       lambda r: r['retest_vs_original']['different'].update(Grid_Size=['-3.75', '-3.0']),
                       lambda r: r.update(original_set_sha256='0' * 64),
                       lambda r: r.update(retest_values_sha256='0' * 64),
                       lambda r: r.update(judged=False)):
            folder, source = self.alter_holdout(DISCLOSED_BANKER, change)
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R4', source.lower()))

    def test_a_reserve_with_a_bad_holdout_record_does_not_stop_the_count(self):
        reserve = next(f for f in board.count(FIXTURE)['files'] if f['state'] == 'reserve')
        folder, _ = self.alter_holdout(reserve['alias'], lambda r: r.update(same_inputs=False))
        self.assertEqual(board.count(folder.path)['counted']['total'], 16)

    def alter_report(self, alias, change):
        folder = Folder(self)

        def apply(data):
            hit = [i for i, r in enumerate(data['runs']) if r['alias'] == alias]
            self.assertEqual(len(hit), 1)
            if change is None:
                del data['runs'][hit[0]]
            else:
                change(data['runs'][hit[0]])
        folder.alter('reports.json', apply)
        return folder

    def test_r5_refuses_a_counted_file_without_an_identical_report(self):
        for alias, source in ((DISCLOSED_BANKER, None), (CLEAN_COUNTED, None), (MIGRATED_COUNTED, 'original_set')):
            for change in (None, lambda r: r.update(passed=False), lambda r: r.update(problems=['report differs from the ini pin: Ledger_Mode 0 / 1'])):
                folder = self.alter_report(alias, change)
                expected = (next(r for r in folder.read('o3pool.json')['members'] if r['alias'] == alias)['original_set'] if source
                            else judged(folder, alias)['source'])
                refusal = self.refused(folder)
                self.assertEqual((refusal.rule, refusal.path.lower()), ('R5', expected.lower()))

    def test_r6_refuses_a_migrated_file_with_a_duplicate_or_other_inputs(self):
        for change in (lambda r: r.update(duplicate_hits=['values hash + symbol = pool file X'], condition1_no_duplicate=False),
                       lambda r: r.update(same_inputs=False, condition2_inputs=False, reasons=['altered']),
                       lambda r: r.update(inherited_in_retest=['Ledger_Mode'])):
            folder = Folder(self)
            folder.alter('o3pool.json', lambda data: [change(r) for r in data['members'] if r['alias'] == MIGRATED_COUNTED])
            target = next(r for r in folder.read('o3pool.json')['members'] if r['alias'] == MIGRATED_COUNTED)['original_set']
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R6', target.lower()))

    def mark_duplicate(self, alias, hits=('values hash + symbol = pool file X',)):
        folder = Folder(self)
        folder.alter('judged.json', lambda rows: [r.update(duplicate=True, **({'duplicate_hits': list(hits)} if hits else {})) for r in rows if r['alias'] == alias])
        return folder, judged(folder, alias)['source']

    def test_r6_refuses_a_round_file_that_would_be_counted_and_is_a_duplicate(self):
        # real negative: the same file, not marked, is counted
        states = {f['alias']: (f['state'], f['duplicate']) for f in board.count(FIXTURE)['files']}
        self.assertEqual(states[CLEAN_COUNTED], ('counted', False))
        self.assertEqual(states[DISCLOSED_BANKER], ('counted', False))
        # real positive: marked, it stops the count and is named with what it duplicates
        for alias in (CLEAN_COUNTED, DISCLOSED_BANKER):
            folder, source = self.mark_duplicate(alias)
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R6', source.lower()))
            self.assertIn('values hash + symbol = pool file X', refusal.why)
        folder, source = self.mark_duplicate(CLEAN_COUNTED, hits=None)   # the flag alone is enough
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R6', source.lower()))
        self.assertIn('no hit listed', refusal.why)

    def test_a_round_reserve_that_is_a_duplicate_does_not_stop_the_count(self):
        folder, _ = self.mark_duplicate(THRUSH[2])
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], b['duplicates']), (16, 1))
        row = next(f for f in b['files'] if f['alias'] == THRUSH[2])
        self.assertEqual((row['state'], row['duplicate']), ('reserve', True))
        # the duplicate keeps its place in the export order: marking the first of the three moves nothing up in silence
        folder, source = self.mark_duplicate(THRUSH[0])
        self.assertEqual(self.refused(folder).path.lower(), source.lower())

    def test_a_migrated_reserve_with_a_duplicate_does_not_stop_the_count(self):
        folder = Folder(self)
        folder.alter('o3pool.json', lambda data: [r.update(duplicate_hits=['x'], condition1_no_duplicate=False) for r in data['members'] if r['alias'] == MIGRATED_RESERVE])
        self.assertEqual(board.count(folder.path)['counted']['o3pool'], 4)

    def test_no_journal_and_no_real_tick_report_keeps_the_file_apart(self):
        b = board.count(FIXTURE)
        self.assertEqual(b['proof_by_machine'], dict(t3=['tester journal'], banker=['MT5 report inputs identical (goatai#2750 comment 6791842328)']))
        folder = self.alter_report(DISCLOSED_BANKER, lambda r: r.update(history_quality='99% real ticks'))
        b = board.count(folder.path)
        self.assertEqual((b['apart']['files'], b['apart']['machines'], b['apart']['disclosed']), (1, ['banker'], 1))
        self.assertEqual((b['counted']['disclosed'], b['counted']['total']), (2, 15))
        folder = Folder(self)   # with the tester journal proven the report is not needed as proof
        folder.alter('journals.json', lambda data: data['banker'].update(proven=True, matched=33, gaps=0))
        self.assertEqual(board.count(folder.path)['proof_by_machine']['banker'], ['tester journal'])

    def test_r7_refuses_a_judged_status_that_differs_from_its_export_record(self):
        # real negative: with the two copies agreeing the file is counted as disclosed (9 clean + 3 disclosed)
        b = board.count(FIXTURE)
        self.assertEqual(next(f for f in b['files'] if f['alias'] == DISCLOSED_BANKER)['kind'], 'disclosed')
        self.assertEqual((b['counted']['clean'], b['counted']['disclosed']), (9, 3))
        # real positive (Codex 4536282619): only the judged copy says "candidate"; before, this gave 10 clean + 2 disclosed
        for alias, status in ((DISCLOSED_BANKER, 'native_threshold_candidate'), (CLEAN_COUNTED, 'unverified'), (THRUSH[2], 'unverified')):
            folder = Folder(self)
            folder.alter('judged.json', lambda rows: [r.update(prove_status=status) for r in rows if r['alias'] == alias])
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R7', judged(folder, alias)['source'].lower()))
            self.assertIn(status, refusal.why)
        folder = Folder(self)   # a judged file the Prove reports do not list at all
        source = judged(folder, CLEAN_COUNTED)['source']
        folder.alter('prove-exports.json', lambda rows: rows.remove(next(r for r in rows if r['set_path'].lower() == source.lower())))
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R7', source.lower()))

    def test_an_apart_file_leaves_every_counted_breakdown_and_gets_its_own_state(self):
        # real negative: proven by its report, the file is counted and in the Banker breakdown
        b = board.count(FIXTURE)
        self.assertEqual(next(f for f in b['files'] if f['alias'] == DISCLOSED_BANKER)['state'], 'counted')
        self.assertEqual((b['counted_by_machine']['banker'], b['apart_by_machine']), (dict(clean=0, disclosed=2), dict(t3=0, banker=0)))
        # real positive (Codex 4536282628): without proof it is apart everywhere, not only in the headline
        folder = self.alter_report(DISCLOSED_BANKER, lambda r: r.update(history_quality='99% real ticks'))
        b = board.count(folder.path)
        row = next(f for f in b['files'] if f['alias'] == DISCLOSED_BANKER)
        self.assertEqual((row['state'], row['proof']), ('apart', None))
        self.assertEqual(b['counted_by_machine']['banker'], dict(clean=0, disclosed=1))
        self.assertEqual(b['apart_by_machine'], dict(t3=0, banker=1))
        self.assertEqual(sum(f['state'] == 'counted' for f in b['files']) + b['pool']['files'] + b['counted']['o3pool'], b['counted']['total'])
        self.assertEqual((b['counted']['total'], b['counted']['disclosed'], b['apart']['files']), (15, 2, 1))
        self.assertEqual(b['reserves'], dict(t3=2, banker=1))   # the apart file frees no slot: the reserve stays a reserve

    def test_audit_notes_travel_with_the_file_onto_the_board(self):
        note = dict(note='seed 2026-10-13 stepped TF ladder, frames show the two stated rungs', evidence='ENUM-LADDER-AUDIT.md', sha256='ab' * 32)
        b = board.count(FIXTURE)   # none in the fixture: every row carries an empty list and the Markdown has no section
        self.assertTrue(all(f['audit_notes'] == [] for f in b['files'] + b['o3_files']))
        self.assertNotIn('## Audit notes', board.markdown(b))
        folder = Folder(self)
        folder.alter('o3pool.json', lambda data: [r.update(audit_notes=[note]) for r in data['members'] if r['alias'] in (MIGRATED_COUNTED, MIGRATED_RESERVE)])
        folder.alter('judged.json', lambda rows: [r.update(audit_notes=[note]) for r in rows if r['alias'] == CLEAN_COUNTED])
        b = board.count(folder.path)
        self.assertEqual(b['counted']['total'], 16)   # a note never changes the count
        carried = {f['alias']: f['audit_notes'] for f in b['files'] + b['o3_files'] if f['audit_notes']}
        self.assertEqual(carried, {MIGRATED_COUNTED: [note], MIGRATED_RESERVE: [note], CLEAN_COUNTED: [note]})
        text = board.markdown(b)
        self.assertIn('- "seed 2026-10-13 stepped TF ladder, frames show the two stated rungs": evidence `ENUM-LADDER-AUDIT.md`, sha256 `%s`; 3 files: ' % ('ab' * 32), text)
        self.assertIn('%s (reserve)' % MIGRATED_RESERVE, text)
        for bad in ([dict(note, sha256='xyz')], [dict(note='x', evidence='y')], 'a string', [dict(note, extra='field')]):
            folder = Folder(self)
            folder.alter('o3pool.json', lambda data: [r.update(audit_notes=bad) for r in data['members'] if r['alias'] == MIGRATED_COUNTED])
            with self.assertRaises(ValueError):
                board.count(folder.path)

    def test_a_folder_without_a_record_file_is_an_error_not_a_board(self):
        folder = Folder(self)
        (folder.path / 'holdout.json').unlink()
        with self.assertRaises(ValueError):
            board.count(folder.path)
        folder = Folder(self)
        folder.alter('rules.json', lambda rules: rules.update(schema='something-else'))
        with self.assertRaises(ValueError):
            board.count(folder.path)

    def test_command_exit_codes_and_never_overwrites(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = board.main(['--input', str(FIXTURE)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['counted']['total'], 16)
        folder = Folder(self)
        (folder.path / board.DISCLOSED).unlink()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = board.main(['--input', str(folder.path)])
        self.assertEqual(code, 3)
        self.assertTrue(out.getvalue().startswith('REFUSED R1: ') and err.getvalue().startswith('REFUSED R1: '))
        target = Path(folder.tmp.name) / 'BOARD.md'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(board.main(['--input', str(FIXTURE), '--markdown', str(target), '--output', str(target.with_suffix('.json'))]), 0)
        text = target.read_text(encoding='utf-8')
        self.assertIn('**9 clean + 3 disclosed + 4 migrated = 16**', text)
        self.assertIn('| **Counted** | 9 | 3 | 4 | **16** | 7 | 4 | WS30 7 (43.8%) | 50.0% |', text)
        self.assertEqual(json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))['counted']['total'], 16)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError):
            board.main(['--input', str(FIXTURE), '--markdown', str(target)])


if __name__ == '__main__':
    unittest.main()
