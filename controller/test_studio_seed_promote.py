"""Seed candidate promotion: exact values, plain name, narrow validation ladder, create-only."""
import hashlib
from pathlib import Path
import unittest

import test_studio_seed as base
from studio_installation import read_json
from studio_seed_promote import promote
from studio_strategy_settings import read_values


class SeedPromoteTests(unittest.TestCase):
    setUp = base.SeedTests.setUp
    tearDown = base.SeedTests.tearDown
    close = base.SeedTests.close
    start = base.SeedTests.start
    sleep = base.SeedTests.sleep
    prepare = base.SeedTests.prepare
    member = base.SeedTests.member
    output = base.SeedTests.output

    def run_seed(self):
        self.prepare(); self.auto = True
        self.assertEqual(self.runner.start('batch', 10)['status'], 'completed')
        row = self.runner.report('batch')['members'][0]
        return read_json(row['result_path'])['candidates']

    def test_promotes_exact_values_with_plain_name_and_narrow_ladder(self):
        candidates = self.run_seed()
        first = promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'EURUSD Period Ten', runner=self.runner)
        fixed = read_values(Path(first['fixed_set']['path']).read_bytes())
        validation = read_values(Path(first['validation_set']['path']).read_bytes())
        self.assertEqual(fixed['EA_Desc'], 'EURUSD Period Ten'); self.assertEqual(validation['EA_Desc'], 'EURUSD Period Ten')
        self.assertEqual(fixed['Period'], '10||10||5||20||N', 'fixed SET keeps the ladder but turns the axis off')
        self.assertEqual(validation['Period'], '10||10||5||15||Y', 'one step either side, clipped to the seed ladder')
        self.assertEqual(fixed['Size'], '1.5'); self.assertEqual(validation['Size'], '1.5')
        self.assertTrue(Path(first['validation_set']['path']).read_bytes().startswith(b'\xff\xfe'))
        for key in ('fixed_set', 'validation_set'):
            self.assertEqual(hashlib.sha256(Path(first[key]['path']).read_bytes()).hexdigest(), first[key]['sha256'])
        self.assertEqual(first['seed_window'], dict(symbol='EURUSD', period='H1', from_date='2026.01.01', to_date='2026.03.01'))
        self.assertFalse(first['native_launch_qualified']); self.assertIn('after seed_window.to_date', first['scope'])
        second = promote(self.controller, 'batch', candidates[1]['candidate_sha256'], 'EURUSD Period Fifteen', neighborhood=0, runner=self.runner)
        self.assertEqual(read_values(Path(second['validation_set']['path']).read_bytes())['Period'], '15||15||5||15||Y')

    def test_repeat_returns_receipt_and_conflicts_refuse(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        first = promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner)
        self.assertEqual(promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner), first)
        with self.assertRaisesRegex(ValueError, 'already promoted'):
            promote(self.controller, 'batch', candidate, 'Other name', runner=self.runner)
        Path(first['validation_set']['path']).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'promoted SET changed'):
            promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner)

    def test_identical_values_in_two_members_require_the_member(self):
        import copy
        second = copy.deepcopy(self.plan['jobs'][0]); second['tester']['Symbol'] = 'GBPUSD'; self.plan['jobs'].append(second)
        self.prepare(); self.auto = True
        self.assertEqual(self.runner.start('batch', 10)['status'], 'completed')
        rows = self.runner.report('batch')['members']
        shared = read_json(rows[1]['result_path'])['candidates'][0]['candidate_sha256']
        self.assertEqual(shared, read_json(rows[0]['result_path'])['candidates'][0]['candidate_sha256'], 'same values, same hash')
        with self.assertRaisesRegex(ValueError, 'matches 2 seed members; pass member'):
            promote(self.controller, 'batch', shared, 'Ambiguous', runner=self.runner)
        gbp = promote(self.controller, 'batch', shared, 'GBPUSD pick', member=rows[1]['alias'], runner=self.runner)
        self.assertEqual(gbp['seed_window']['symbol'], 'GBPUSD'); self.assertEqual(gbp['alias'], rows[1]['alias'])
        eur = promote(self.controller, 'batch', shared, 'EURUSD pick', member=rows[0]['member_id'], runner=self.runner)
        self.assertEqual(eur['seed_window']['symbol'], 'EURUSD')
        self.assertNotEqual(gbp['validation_set']['path'], eur['validation_set']['path'])

    def test_refuses_unknown_candidates_bad_names_and_changed_evidence(self):
        candidates = self.run_seed()
        with self.assertRaisesRegex(ValueError, 'not in this seed batch'):
            promote(self.controller, 'batch', 'f' * 64, 'Name', runner=self.runner)
        for name in ('', 'S1@{mode=SeedFarming}', 'has/slash', 'x' * 64):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Name must be'):
                promote(self.controller, 'batch', candidates[0]['candidate_sha256'], name, runner=self.runner)
        with self.assertRaisesRegex(ValueError, 'neighborhood'):
            promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'Name', neighborhood=6, runner=self.runner)
        row = self.runner.report('batch')['members'][0]
        Path(row['result_path']).write_text(Path(row['result_path']).read_text().replace('"Period": "10"', '"Period": "15"'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'Name', runner=self.runner)


if __name__ == '__main__':
    unittest.main()
