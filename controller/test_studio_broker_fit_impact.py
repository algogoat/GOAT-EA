"""The read-only broker-fit report tools (studio_broker_fit_impact.py, GOAT-EA#228 round 5). Fixture-only: temp folders,
never a real portfolio folder."""
from decimal import Decimal
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import studio_broker_fit as bf
import studio_broker_fit_impact as impact
from test_studio_broker_fit import KESTREL, SCHEMA, kestrel_with

REFERENCE = dict(server='Darwinex-Demo', symbol='EURUSD', digits=5, point=0.00001, tickSize=0.00001, tickValue=1, contractSize=100000,
                 volumeMin=0.01, volumeStep=0.01, volumeMax=100, typicalSpreadPts=8, currency='USD')


def member_id(raw, symbol='EURUSD'):
    return '%s.M1.%s' % (symbol, hashlib.sha256(raw).hexdigest()[:16])


class ReferenceDigitsTests(unittest.TestCase):
    def test_an_index_with_zero_digits_has_reference_facts(self):
        # WS30 quotes whole points (digits 0): its facts used to read as missing, so every WS30 member was excluded.
        ws30 = dict(REFERENCE, symbol='WS30', digits=0, point=1, tickSize=1, tickValue=1, contractSize=1, typicalSpreadPts=1)
        self.assertIsNotNone(bf.reference_facts(ws30))
        for bad in (1.5, -1, None):
            with self.subTest(digits=bad):
                self.assertIsNone(bf.reference_facts(dict(ws30, digits=bad)))


class StartLotTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.traces = self.root / 'traces'

    def write_trace(self, name, sequences):
        raw = json.dumps(dict(schemaVersion='goat-sequence-replay-v2', initialEquity=100000, sequences=sequences)).encode()
        path = self.traces / 'shared' / name / 'trace.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest(), 'traces/shared/%s/trace.json' % name

    @staticmethod
    def sequence(strategy, time, lot, direction='buy'):
        return dict(id='s', strategyId=strategy, direction=direction, events=[dict(kind='entry', time=time, lotsAfter=lot),
                                                                              dict(kind='exit', time=time + 60000, lotsAfter=0)])

    def test_trace_start_lots_are_the_first_entry_of_each_sequence(self):
        # Two portfolio-level traces replaying the same week: the same sequences appear in both and count once.
        sequences = [self.sequence('k', 1789338600000, 0.16), self.sequence('k', 1789400000000, 0.17, 'sell'),
                     self.sequence('other', 1789338600000, 9.0)]
        first, first_path = self.write_trace('aaaa', sequences)
        second, second_path = self.write_trace('bbbb', sequences)
        bad_sha = '0' * 64
        member = member_id(KESTREL)
        pointer = self.traces / ('01-' + member[-12:])
        pointer.mkdir(parents=True)
        (pointer / 'trace-ref.json').write_text(json.dumps(dict(setSha256=hashlib.sha256(KESTREL).hexdigest(), traces=[
            dict(traceSha256=first, path=first_path, strategyIdInTrace='k'), dict(traceSha256=second, path=second_path, strategyIdInTrace='k'),
            dict(traceSha256=bad_sha, path=first_path, strategyIdInTrace='k')])))
        reference = {member: dict(reference=REFERENCE), 'EURUSD.M1.0000000000000000': dict(reference=REFERENCE)}
        result = impact.start_lots_from_traces(self.traces, reference)
        self.assertEqual(result['missingMembers'], ['EURUSD.M1.0000000000000000'])
        self.assertEqual(result['unverifiedTraces'], [dict(memberId=member, traceSha256=bad_sha)])
        row = result['members'][0]
        self.assertEqual((row['memberId'], row['startLotSource']), (member, 'trace:%s,%s' % (first, second)))
        arm = row['arms']['trace']
        self.assertEqual((arm['n'], arm['median'], arm['min'], arm['max']), (2, 0.165, 0.16, 0.17))
        self.assertEqual([s['direction'] for s in arm['sequences']], ['buy', 'sell'])
        # The output reads back through the impact reader (the same shape as Ops' arms file).
        path = self.root / 'lots.json'
        path.write_text(json.dumps(result))
        self.assertEqual(impact.read_start_lots(path)[member]['startLot'], 0.165)

    def test_the_larger_arm_median_is_used_and_flagged(self):
        path = self.root / 'ops.json'
        path.write_text(json.dumps(dict(members=[
            dict(memberId='A', arms={'09': dict(n=2, median=0.10, min=0.09, max=0.11), '10': dict(n=1, median=0.12, min=0.12, max=0.12)},
                 armMediansDiffer=True),
            dict(memberId='B', arms={'09': dict(n=1, median=0.2, min=0.2, max=0.2)}, armMediansDiffer=False),
            dict(memberId='C', arms={})])))
        lots = impact.read_start_lots(path)
        self.assertEqual((lots['A']['startLot'], lots['A']['n'], lots['A']['min'], lots['A']['max'], lots['A']['armMediansDiffer']),
                         (0.12, 1, 0.09, 0.12, True))
        self.assertEqual((lots['B']['startLot'], lots['B']['armMediansDiffer']), (0.2, False))
        self.assertNotIn('C', lots, 'no start yet: not a start lot')
        flat = self.root / 'flat.json'
        flat.write_text(json.dumps(dict(D=dict(startLot=0.05, n=3, window='x', sourceArm='10'))))
        self.assertEqual((impact.read_start_lots(flat)['D']['startLot'], impact.read_start_lots(flat)['D']['source']), (0.05, '10'))


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_outcomes_per_equity_and_the_band_top_check(self):
        other = kestrel_with(EA_Desc='no start')
        sets = self.root / 'sets'
        sets.mkdir()
        (sets / 'a.set').write_bytes(KESTREL)
        (sets / 'b.set').write_bytes(other)
        reference = {member_id(KESTREL): dict(canonicalSymbol='EURUSD', reference=REFERENCE),
                     member_id(other): dict(canonicalSymbol='EURUSD', reference=REFERENCE)}
        lots_path = self.root / 'lots.json'
        lots_path.write_text(json.dumps(dict(members=[dict(memberId=member_id(KESTREL), arms={'09': dict(n=3, median=0.1, min=0.09, max=0.17)})])))
        result = impact.impact(reference, impact.load_sets(sets, reference), impact.read_start_lots(lots_path),
                               [Decimal(10000), Decimal(50000)], schema=SCHEMA)
        self.assertEqual(result['counts'], {
            '10000': dict(fit=0, BELOW_MIN_LOT=1, MARGIN_UNKNOWN_NO_START_LOT=1, MARGIN_UNKNOWN=0, other=0),
            '50000': dict(fit=1, BELOW_MIN_LOT=0, MARGIN_UNKNOWN_NO_START_LOT=1, MARGIN_UNKNOWN=0, other=0)})
        row = next(row for row in result['members'] if row['memberId'] == member_id(KESTREL))
        self.assertEqual((row['gridKind'], row['bandTop'], row['maxOverMedian'], row['withinBandTop']), ('atr', 1.6, 1.7, False))
        self.assertEqual(row['outcomes']['50000']['detail']['Risk'], 209.56)
        self.assertIn('margin per lot (MARGIN_TOO_HIGH)', result['notAssessed'])

    def test_a_cent_account_on_a_cent_contract_sizes_like_the_same_number_of_dollars(self):
        # P-beta38-cent-accounts: 50,000 USC on the reference specs scaled to a cent contract = 50,000 USD standard.
        sets = self.root / 'sets'
        sets.mkdir()
        (sets / 'a.set').write_bytes(KESTREL)
        reference = {member_id(KESTREL): dict(canonicalSymbol='EURUSD', reference=REFERENCE)}
        lots = self.root / 'lots.json'
        lots.write_text(json.dumps(dict(members=[dict(memberId=member_id(KESTREL), arms={'09': dict(n=3, median=0.1, min=0.1, max=0.1)})])))
        args = (reference, impact.load_sets(sets, reference), impact.read_start_lots(lots), [Decimal(50000)])
        cent = impact.impact(*args, schema=SCHEMA, account_currency='USC')
        standard = impact.impact(*args, schema=SCHEMA)
        self.assertEqual(cent['members'][0]['outcomes'], standard['members'][0]['outcomes'])
        self.assertEqual((cent['accountUnit']['centOf'], cent['contract']), ('USD', 'reference contract / 100 (cent)'))
        # Only USC: EUC and the other cent currencies need a live base/USD quote (Codex P2 on #236), never USC's 0.01.
        for currency in ('EUR', 'EUC', 'GBC', 'CHC', 'AUC', 'CAC', 'USc'):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                impact.impact(*args, schema=SCHEMA, account_currency=currency)

    def test_the_cli_reads_a_portfolio_export_and_writes_nothing(self):
        import base64
        export = self.root / 'p.goatportfolio'
        export.write_text(json.dumps(dict(memberSetFilesBinary={'GOAT V1.49 EURUSD,M1_x.set': base64.b64encode(KESTREL).decode()})))
        reference = self.root / 'member-reference.json'
        reference.write_text(json.dumps({member_id(KESTREL): dict(canonicalSymbol='EURUSD', reference=REFERENCE)}))
        before = sorted(p.name for p in self.root.iterdir())
        out = StringIO()
        with patch('sys.stdout', out):
            impact.main(['impact', '--member-reference', str(reference), '--sets', str(export), '--equities', '50000'])
        result = json.loads(out.getvalue())
        self.assertEqual(result['counts']['50000']['MARGIN_UNKNOWN_NO_START_LOT'], 1)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before, 'nothing written')


if __name__ == '__main__':
    unittest.main()
