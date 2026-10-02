"""Seed candidate promotion: exact values, plain name, narrow robustness ladder, atomic create-only output."""
import copy
import hashlib
from pathlib import Path
import re
import shutil
import unittest
from unittest.mock import patch

import studio_seed_promote
import test_studio_seed as base
from studio_installation import read_json
from studio_seed_promote import promote
from studio_strategy_settings import read_values
from studio_template_tools import validate_raw


class SeedPromoteTests(unittest.TestCase):
    setUp = base.SeedTests.setUp
    tearDown = base.SeedTests.tearDown
    close = base.SeedTests.close
    start = base.SeedTests.start
    sleep = base.SeedTests.sleep
    prepare = base.SeedTests.prepare
    member = base.SeedTests.member
    rows = None  # native result rows for every member; None keeps the base fixture rows

    def output(self, member, rows=None, suffix=None):
        return base.SeedTests.output(self, member, self.rows if rows is None else rows, suffix)

    def run_seed(self):
        self.prepare(); self.auto = True
        self.assertEqual(self.runner.start('batch', 10)['status'], 'completed')
        row = self.runner.report('batch')['members'][0]
        return read_json(row['result_path'])['candidates']

    def folder(self, candidate):
        return self.runner.path('batch') / 'promoted' / self.member()['alias'] / candidate

    def sets(self, receipt):
        return [read_values(Path(receipt[key]['path']).read_bytes()) for key in ('fixed_set', 'robustness_set')]

    def test_promotes_exact_values_with_plain_name_and_narrow_ladder(self):
        candidates = self.run_seed()
        first = promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'EURUSD Period Ten', runner=self.runner)
        self.assertEqual(first['status'], 'written')
        fixed, robustness = self.sets(first)
        self.assertEqual(fixed['EA_Desc'], 'EURUSD Period Ten'); self.assertEqual(robustness['EA_Desc'], 'EURUSD Period Ten')
        self.assertEqual(fixed['Period'], '10||10||5||20||N', 'fixed SET keeps the ladder but turns the axis off')
        self.assertEqual(robustness['Period'], '10||10||5||15||Y', 'one step either side, clipped to the seed ladder')
        self.assertEqual(fixed['Size'], '1.5'); self.assertEqual(robustness['Size'], '1.5')
        self.assertTrue(Path(first['robustness_set']['path']).read_bytes().startswith(b'\xff\xfe'))
        folder = self.folder(candidates[0]['candidate_sha256'])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['fixed.set', 'promotion.json', 'robustness.set'])
        self.assertEqual([p.name for p in folder.parent.iterdir()], [folder.name], 'no temporary folder remains')
        for key in ('fixed_set', 'robustness_set'):
            self.assertEqual(Path(first[key]['path']).parent, folder)
            self.assertEqual(hashlib.sha256(Path(first[key]['path']).read_bytes()).hexdigest(), first[key]['sha256'])
        self.assertEqual(Path(first['receipt_path']), folder / 'promotion.json')
        self.assertEqual(read_json(first['receipt_path']), {k: v for k, v in first.items() if k not in ('status', 'receipt_path')})
        self.assertNotIn('validation_set', first)
        self.assertEqual(first['seed_window'], dict(symbol='EURUSD', period='H1', from_date='2026.01.01', to_date='2026.03.01'))
        self.assertFalse(first['native_launch_qualified'])
        self.assertIn('local stability check around the candidate; only the forward window is out-of-sample', first['scope'])
        self.assertIn('after seed_window.to_date', first['scope'])
        second = promote(self.controller, 'batch', candidates[1]['candidate_sha256'], 'EURUSD Period Fifteen', neighborhood=2, runner=self.runner)
        self.assertEqual(self.sets(second)[1]['Period'], '15||10||5||20||Y')
        self.assertEqual(second['ladder']['Period'], dict(value='15', start='10', step='5', stop='20'))

    def test_double_bool_and_enum_axes(self):
        self.controller.schema['inputs'] |= dict(
            UseTrail=dict(type='bool', optimizable=True),
            Mode=dict(type='int', optimizable=True, enum_choices={'Slow': 1, 'Normal': 2, 'Fast': 3}))
        self.source.write_bytes(('; Source header\r\nEA_Desc=Original\r\nPeriod=10||10||5||20||Y\r\nSize=1.5||0.5||0.25||2.5||Y\r\n'
                                 'UseTrail=false||false||1||true||Y\r\nMode=2||1||1||3||Y\r\n').encode('utf-16'))
        # The EA writes every axis cell, bool and enum included, with eight decimals.
        self.rows = [[1, 4, 10, 2, 2, 2, 2, 4, 1, 10, '10.00000000', '2.25000000', '1.00000000', '3.00000000'],
                     [2, -2, 0, 0, 0, 0, 0, -2, 0, 0, '15.00000000', '0.50000000', '0.00000000', '1.00000000']]
        candidates = self.run_seed()
        first = promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'Multi Axis', runner=self.runner)
        fixed, robustness = self.sets(first)
        self.assertEqual({k: fixed[k] for k in ('Period', 'Size', 'UseTrail', 'Mode')}, dict(
            Period='10||10||5||20||N', Size='2.25000000||0.5||0.25||2.5||N', UseTrail='1||false||1||true||N', Mode='3||1||1||3||N'))
        self.assertEqual({k: robustness[k] for k in ('Period', 'Size', 'UseTrail', 'Mode')}, dict(
            Period='10||10||5||15||Y', Size='2.25000000||2||0.25||2.5||Y', UseTrail='1||false||1||true||Y', Mode='3||2||1||3||Y'))
        schema, policy = self.controller.schema, self.controller.policy
        self.assertEqual(validate_raw(Path(first['fixed_set']['path']).read_bytes(), schema, policy)['active_axes'], {})
        self.assertEqual(validate_raw(Path(first['robustness_set']['path']).read_bytes(), schema, policy)['active_axes'],
                         dict(Period=2, Size=3, UseTrail=2, Mode=2))
        second = promote(self.controller, 'batch', candidates[1]['candidate_sha256'], 'Multi Axis Two', neighborhood=2, runner=self.runner)
        robustness = self.sets(second)[1]
        self.assertEqual({k: robustness[k] for k in ('Period', 'Size', 'UseTrail', 'Mode')}, dict(
            Period='15||10||5||20||Y', Size='0.50000000||0.5||0.25||1||Y', UseTrail='0||false||1||true||Y', Mode='1||1||1||3||Y'))

    def test_repeat_returns_receipt_and_conflicts_refuse(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        first = promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner)
        self.assertEqual(promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner), first | {'status': 'retained'})
        with self.assertRaisesRegex(ValueError, 'already promoted'):
            promote(self.controller, 'batch', candidate, 'Other name', runner=self.runner)
        with self.assertRaisesRegex(ValueError, 'already promoted'):
            promote(self.controller, 'batch', candidate, 'Keeper', neighborhood=2, runner=self.runner)
        Path(first['robustness_set']['path']).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'promoted SET changed'):
            promote(self.controller, 'batch', candidate, 'Keeper', runner=self.runner)

    def test_identical_values_in_two_members_require_the_member(self):
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
        self.assertNotEqual(gbp['robustness_set']['path'], eur['robustness_set']['path'])

    def test_refuses_unknown_candidates_bad_names_and_changed_evidence(self):
        candidates = self.run_seed()
        with self.assertRaisesRegex(ValueError, 'not in this seed batch'):
            promote(self.controller, 'batch', 'f' * 64, 'Name', runner=self.runner)
        for name in ('', 'S1@{mode=SeedFarming}', 'has/slash', 'x' * 64):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Name must be'):
                promote(self.controller, 'batch', candidates[0]['candidate_sha256'], name, runner=self.runner)
        for neighborhood in (0, 6, True, 1.0):
            with self.subTest(neighborhood=neighborhood), self.assertRaisesRegex(ValueError, 'neighborhood must be an integer from 1 to 5'):
                promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'Name', neighborhood=neighborhood, runner=self.runner)
        row = self.runner.report('batch')['members'][0]
        Path(row['result_path']).write_text(Path(row['result_path']).read_text().replace('"Period": "10"', '"Period": "15"'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            promote(self.controller, 'batch', candidates[0]['candidate_sha256'], 'Name', runner=self.runner)
        self.assertFalse((self.runner.path('batch') / 'promoted').exists())

    def test_merged_values_that_miss_the_candidate_hash_refuse_before_writing(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        real = studio_seed_promote.read_seed_json

        def tampered(path, limit):
            # Evidence hashes still verify; only the values handed to the merge change.
            result = real(path, limit)
            for item in result['candidates']:
                if item['candidate_sha256'] == candidate:
                    item['value_overrides']['Period'] = '15'
            return result
        with patch.object(studio_seed_promote, 'read_seed_json', tampered):
            with self.assertRaisesRegex(ValueError, 'Merged candidate values do not reproduce candidate_sha256'):
                promote(self.controller, 'batch', candidate, 'Tampered', runner=self.runner)
        self.assertFalse((self.runner.path('batch') / 'promoted').exists())
        self.assertEqual(promote(self.controller, 'batch', candidate, 'Tampered', runner=self.runner)['status'], 'written')

    def test_written_fixed_set_is_reread_before_publishing(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        folder = self.folder(candidate)
        real = studio_seed_promote._rewrite
        fixed = lambda change: lambda frozen, lines: real(frozen, change(lines) if lines['Period'].endswith('||N') else lines)
        cases = [('no active optimization axes', fixed(lambda lines: lines | {'Period': lines['Period'][:-1] + 'Y'})),
                 ('Written fixed SET does not reproduce candidate_sha256', fixed(lambda lines: lines | {'Period': '15' + lines['Period'][2:]}))]
        for message, rewrite in cases:
            with self.subTest(message=message), patch.object(studio_seed_promote, '_rewrite', rewrite):
                with self.assertRaisesRegex(ValueError, message):
                    promote(self.controller, 'batch', candidate, 'Reread', runner=self.runner)
                self.assertFalse(folder.exists()); self.assertEqual(list(folder.parent.iterdir()), [])
        real_create = studio_seed_promote._create

        def corrupt(path, raw):
            real_create(path, raw[:-2] if path.name == 'fixed.set' else raw)
        with patch.object(studio_seed_promote, '_create', corrupt), self.assertRaisesRegex(OSError, 'read-back differs: fixed.set'):
            promote(self.controller, 'batch', candidate, 'Reread', runner=self.runner)
        self.assertFalse(folder.exists()); self.assertEqual(list(folder.parent.iterdir()), [])

    def test_failed_write_leaves_no_folder_and_retry_succeeds(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        folder = self.folder(candidate)
        real = studio_seed_promote._create
        calls = []

        def second_write_fails(path, raw):
            calls.append(path.name)
            if len(calls) == 2:
                raise OSError('disk write failed')
            real(path, raw)
        for label, failure in (('write', patch.object(studio_seed_promote, '_create', second_write_fails)),
                               ('rename', patch.object(studio_seed_promote.os, 'rename', side_effect=OSError('rename failed')))):
            with self.subTest(failure=label):
                with failure, self.assertRaisesRegex(OSError, 'failed'):
                    promote(self.controller, 'batch', candidate, 'Retry Me', runner=self.runner)
                self.assertFalse(folder.exists(), 'no final folder after a failed write')
                self.assertEqual(list(folder.parent.iterdir()), [], 'temporary folder removed')
        self.assertEqual(calls, ['fixed.set', 'robustness.set'])
        retried = promote(self.controller, 'batch', candidate, 'Retry Me', runner=self.runner)
        self.assertEqual(retried['status'], 'written')
        self.assertEqual(promote(self.controller, 'batch', candidate, 'Retry Me', runner=self.runner)['status'], 'retained')

    def test_final_folder_without_valid_receipt_refuses_and_is_kept(self):
        candidate = self.run_seed()[0]['candidate_sha256']
        folder = self.folder(candidate)
        folder.mkdir(parents=True); (folder / 'fixed.set').write_bytes(b'partial')
        refusal = 'Incomplete promotion folder at ' + re.escape(str(folder)) + '; inspect and remove it manually'
        for receipt in (None, b'{"schema_version": 1', b'{"schema_version": 1}'):
            if receipt is not None:
                (folder / 'promotion.json').write_bytes(receipt)
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, refusal):
                promote(self.controller, 'batch', candidate, 'Blocked', runner=self.runner)
            self.assertEqual((folder / 'fixed.set').read_bytes(), b'partial', 'never deleted automatically')
        shutil.rmtree(folder)
        self.assertEqual(promote(self.controller, 'batch', candidate, 'Blocked', runner=self.runner)['status'], 'written')


if __name__ == '__main__':
    unittest.main()
