"""Two files on one symbol whose re-test curves are one curve are one file (R8, duplicates in effect).

Ruling: Claude-Mac, goatai#2750 comment 6807210838. The fixture (controller/fixtures/hunt-board-duplicates.json) holds
the real records of the board of 148 (2026-11-11): two USDCHF files with a byte-identical re-test equity CSV, two NDX
files whose daily returns correlate 1.0000 with the same net to the dollar, and a third USDCHF file of the same group
at 0.9967, which stays a file. Each test adds records to a copy of the hunt-board fixture and counts it.
"""
import contextlib
import io
import json
from pathlib import Path
import unittest

import hunt_board_count as board
from test_hunt_board_count import CLEAN_COUNTED, FIXTURE, MIGRATED_COUNTED, THRUSH, Folder, judged

REAL = json.loads((Path(__file__).parent / 'fixtures' / 'hunt-board-duplicates.json').read_text(encoding='utf-8'))['files']
CURVE_KEYS = ('source', 'set_sha256', 'symbol', 'curve_sha256', 'first_day', 'returns')


def pearson(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5


def add_pool(folder, *names, **change):
    """Puts real files on the board as pool files, in the order given (the board order), each with its curve record."""
    rows = [dict(REAL[name], **change) for name in names]
    folder.alter('pool.json', lambda pool: pool.extend(dict(source=r['source'], asset=r['asset'], family=r['family'], group=r['group']) for r in rows))
    folder.alter(board.CURVES, lambda data: data['curves'].extend(dict({k: r[k] for k in CURVE_KEYS}, symbol=r['asset']) for r in rows))
    return rows


def curve_of(folder, source):
    return next(c for c in folder.read(board.CURVES)['curves'] if c['source'].lower() == source.lower())


def repeat_curve(folder, source, earlier):
    """Gives one board file the re-test curve of an earlier file on the same symbol (same CSV hash, same days)."""
    model = curve_of(folder, earlier)
    folder.alter(board.CURVES, lambda data: [c.update(curve_sha256=model['curve_sha256'], first_day=model['first_day'], returns=model['returns'])
                                             for c in data['curves'] if c['source'].lower() == source.lower()])


class DuplicateInEffectTests(unittest.TestCase):
    def refused(self, folder):
        with self.assertRaises(board.Refused) as caught:
            board.count(folder.path)
        return caught.exception

    def test_the_fixture_board_has_a_curve_for_every_counted_file_and_no_duplicate(self):
        b = board.count(FIXTURE)
        self.assertEqual((b['counted']['total'], b['duplicates_in_effect']), (16, []))
        self.assertEqual(b['curves'], dict(records=16, checked=16, correlation=0.999, min_common_days=20))

    def test_each_real_pair_collapses_to_one_file_and_the_later_one_is_listed(self):
        folder = Folder(self)
        add_pool(folder, 'usdchf_pool', 'usdchf_first_wave', 'usdchf_wave2', 'ndx_pool', 'ndx_first_wave')
        b = board.count(folder.path)
        self.assertEqual(b['counted']['total'], 16 + 5 - 2)                       # five files added, three of them count
        self.assertEqual((b['counted']['assets_detail']['USDCHF'], b['counted']['assets_detail']['NDX']), (2, 1))
        self.assertEqual(b['pool']['files'], 11)                                  # the pool as given; the count is in `counted`
        listed = {d['set_sha256']: d for d in b['duplicates_in_effect']}
        self.assertEqual(set(listed), {REAL['usdchf_wave2']['set_sha256'], REAL['ndx_first_wave']['set_sha256']})
        usdchf, ndx = listed[REAL['usdchf_wave2']['set_sha256']], listed[REAL['ndx_first_wave']['set_sha256']]
        # byte-identical re-test equity CSV: the earlier file stays, the later one is named with it
        self.assertEqual((usdchf['duplicate_of_set_sha256'], usdchf['where'], usdchf['state']),
                         (REAL['usdchf_first_wave']['set_sha256'], 'pool', 'duplicate_in_effect'))
        self.assertEqual(usdchf['curve_sha256'], usdchf['duplicate_of_curve_sha256'])
        self.assertIn('identical re-test equity curve', usdchf['evidence'])
        # other bytes, the same curve: 1.0000 over the whole common re-test
        self.assertEqual(ndx['duplicate_of_set_sha256'], REAL['ndx_pool']['set_sha256'])
        self.assertNotEqual(ndx['curve_sha256'], ndx['duplicate_of_curve_sha256'])
        self.assertGreaterEqual(ndx['correlation'], 0.9999)
        self.assertEqual(ndx['common_days'], 152)
        self.assertIn('correlate 1.000000 over the 152 common days', ndx['evidence'])
        text = board.markdown(b)
        self.assertIn('## Duplicates in effect', text)
        self.assertIn('| USDCHF | pool | `%s` | `%s` | identical re-test equity curve' % (REAL['usdchf_wave2']['set_sha256'], REAL['usdchf_first_wave']['set_sha256']), text)
        self.assertIn('2 of 21 files checked', text)

    def test_the_earlier_file_in_board_order_is_the_one_that_stays(self):
        folder = Folder(self)
        add_pool(folder, 'usdchf_wave2', 'usdchf_first_wave')                     # the other way round
        d = board.count(folder.path)['duplicates_in_effect']
        self.assertEqual([(x['set_sha256'], x['duplicate_of_set_sha256']) for x in d],
                         [(REAL['usdchf_first_wave']['set_sha256'], REAL['usdchf_wave2']['set_sha256'])])

    def test_real_negative_the_third_usdchf_file_at_0_9967_stays_a_file(self):
        a, b_ = REAL['usdchf_pool'], REAL['usdchf_first_wave']
        self.assertEqual((a['first_day'], b_['first_day'], len(b_['returns']) - len(a['returns'])), ('2026-06-08', '2026-06-08', 1))
        c = pearson(a['returns'], b_['returns'][:len(a['returns'])])
        self.assertTrue(0.996 < c < 0.998, c)                                     # same group, same entries, other exits
        folder = Folder(self)
        add_pool(folder, 'usdchf_pool', 'usdchf_first_wave')
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], b['duplicates_in_effect']), (18, []))

    def test_two_files_on_one_symbol_at_0_95_stay_two(self):
        c = pearson(REAL['usdchf_first_wave']['returns'], REAL['usdchf_synthetic_095']['returns'])
        self.assertTrue(0.94 < c < 0.96, c)
        folder = Folder(self)
        add_pool(folder, 'usdchf_first_wave', 'usdchf_synthetic_095')
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], b['counted']['assets_detail']['USDCHF'], b['duplicates_in_effect']), (18, 2, []))

    def test_identical_curves_on_different_symbols_are_not_merged(self):
        folder = Folder(self)
        add_pool(folder, 'usdchf_first_wave')
        add_pool(folder, 'usdchf_wave2', asset='NDX')                             # the same curve bytes, filed on another symbol
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], b['duplicates_in_effect']), (18, []))
        folder = Folder(self)                                                     # real positive: on one symbol the same two are one
        add_pool(folder, 'usdchf_first_wave', 'usdchf_wave2')
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], len(b['duplicates_in_effect'])), (17, 1))

    def test_a_round_file_that_repeats_a_pool_file_is_not_counted_and_frees_no_slot(self):
        folder = Folder(self)
        thrush = judged(folder, THRUSH[0])                                        # counted; THRUSH[1] and [2] are its group's reserves
        pool_file = next(p for p in folder.read('pool.json') if p['group'] == thrush['held_group'])
        repeat_curve(folder, thrush['source'], pool_file['source'])
        b = board.count(folder.path)
        states = {f['alias']: f['state'] for f in b['files']}
        self.assertEqual([states[a] for a in THRUSH], ['duplicate_in_effect', 'reserve', 'reserve'])
        self.assertEqual((b['counted']['total'], b['counted']['clean'], b['counted_by_machine']['t3']['clean']), (15, 8, 2))
        d = b['duplicates_in_effect']
        self.assertEqual([(x['source'], x['duplicate_of'], x['where']) for x in d], [(thrush['source'], pool_file['source'], 'round')])
        self.assertEqual(sum(f['state'] == 'counted' for f in b['files']) + b['pool']['files'] + b['counted']['o3pool'], b['counted']['total'])

    def test_a_migrated_file_that_repeats_a_pool_file_is_not_counted(self):
        folder = Folder(self)
        target = next(r for r in folder.read('o3pool.json')['members'] if r['alias'] == MIGRATED_COUNTED)
        pool_file = next(p for p in folder.read('pool.json') if p['asset'] == target['symbol'])
        repeat_curve(folder, target['original_set'], pool_file['source'])
        b = board.count(folder.path)
        self.assertEqual((b['counted']['total'], b['counted']['o3pool'], b['o3pool']['counted']), (15, 3, 3))
        self.assertEqual(next(f for f in b['o3_files'] if f['alias'] == MIGRATED_COUNTED)['state'], 'duplicate_in_effect')
        self.assertEqual(b['duplicates_in_effect'][0]['where'], 'migrated')

    def test_r8_refuses_a_board_without_curve_records(self):
        folder = Folder(self)
        (folder.path / board.CURVES).unlink()
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path), ('R8', str(folder.path / board.CURVES)))
        for bad in (lambda data: data.update(schema='something-else'), lambda data: data['curves'].append(dict(data['curves'][0])),
                    lambda data: data['curves'][0].update(returns=[]), lambda data: data['curves'][0].update(curve_sha256='xyz'),
                    lambda data: data['curves'][0].update(first_day='yesterday')):
            folder = Folder(self)
            folder.alter(board.CURVES, bad)
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path), ('R8', str(folder.path / board.CURVES)))

    def test_r8_refuses_a_file_on_the_board_without_its_own_curve_record_and_names_it(self):
        base = Folder(self)
        targets = [('pool', base.read('pool.json')[2]['source']), ('round', judged(base, CLEAN_COUNTED)['source']),
                   ('migrated', next(r for r in base.read('o3pool.json')['members'] if r['alias'] == MIGRATED_COUNTED)['original_set'])]
        for where, source in targets:
            folder = Folder(self)
            folder.alter(board.CURVES, lambda data: data['curves'].remove(next(c for c in data['curves'] if c['source'].lower() == source.lower())))
            refusal = self.refused(folder)
            self.assertEqual((refusal.rule, refusal.path.lower()), ('R8', source.lower()))
            self.assertIn(where, refusal.why)
        folder = Folder(self)   # a record for another symbol, and one for other SET bytes
        source = targets[1][1]
        folder.alter(board.CURVES, lambda data: [c.update(symbol='NDX') for c in data['curves'] if c['source'].lower() == source.lower()])
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R8', source.lower()))
        folder = Folder(self)
        folder.alter(board.CURVES, lambda data: [c.update(set_sha256='0' * 64) for c in data['curves'] if c['source'].lower() == source.lower()])
        refusal = self.refused(folder)
        self.assertEqual((refusal.rule, refusal.path.lower()), ('R8', source.lower()))
        self.assertIn('other SET bytes', refusal.why)

    def test_a_reserve_needs_no_curve_record_and_a_short_common_span_is_not_read(self):
        b = board.count(FIXTURE)
        reserves = [f['source'].lower() for f in b['files'] if f['state'] == 'reserve']
        have = {c['source'].lower() for c in json.loads((FIXTURE / board.CURVES).read_text(encoding='utf-8'))['curves']}
        self.assertTrue(reserves and not have.intersection(reserves))             # the fixture counts with no record for its reserves
        folder = Folder(self)
        add_pool(folder, 'ndx_pool')
        add_pool(folder, 'ndx_first_wave', returns=REAL['ndx_first_wave']['returns'][:board.MIN_COMMON_DAYS - 1])
        self.assertEqual(board.count(folder.path)['duplicates_in_effect'], [])    # 19 common days: no correlation is read
        folder = Folder(self)
        add_pool(folder, 'ndx_pool')
        add_pool(folder, 'ndx_first_wave', returns=REAL['ndx_first_wave']['returns'][:60])
        self.assertEqual(len(board.count(folder.path)['duplicates_in_effect']), 1)

    def test_command_exit_code_and_output_carry_the_rule(self):
        folder = Folder(self)
        (folder.path / board.CURVES).unlink()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = board.main(['--input', str(folder.path)])
        self.assertEqual(code, 3)
        self.assertTrue(out.getvalue().startswith('REFUSED R8: ') and err.getvalue().startswith('REFUSED R8: '))
        folder = Folder(self)
        add_pool(folder, 'ndx_pool', 'ndx_first_wave')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(board.main(['--input', str(folder.path)]), 0)
        printed = json.loads(out.getvalue())
        self.assertEqual((printed['counted']['total'], len(printed['duplicates_in_effect'])), (17, 1))


if __name__ == '__main__':
    unittest.main()
