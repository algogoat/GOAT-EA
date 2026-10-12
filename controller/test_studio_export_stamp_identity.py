"""B44 condition 2 (GOAT-EA, goatai#2350 6127809765): the '; EXPORT:' stamp changes no identity.

A B44 blind=0 export carries '; EXPORT: blind=0 ranked=full_span sr=mt5_stat' as the last line of its SET header;
its B43 twin (the same run on B43) has no such line. Fixture: the real B35-01 Kestrel export (UTF-16, CRLF) and its
stamped twin, placed where WriteSet puts the stamp (after OnTester's description, before the GENERAL SETTINGS line).

What is the same (asserted below): the SET reader (strategy_registry.inspect_set: values, canonical hash, EA_Desc,
axes), the header windows the evidence reader parses, the qualification header tokens, read_export's values
identity / windows / metrics / qualification / evidence end, the strategy-library fingerprint, and the
studio_deploy_profile child chart byte for byte (equal to the G4 golden). studio_deploy_profile and
GOATDeployProfileWriter.mqh drop the stamp line from the staged inputs (B44); before that both kept every comment line
holding '=' as an input line, so the stamp would have reached the child chart.

What differs, by design: the raw file sha256. The controller uses the raw SET sha256 only to pin a specific file
(the capture manifest's binding, a registration's expected hash read again by the EA, held-out freeze cells, export
scan stamps, strategy_registry revisions of a template suite), never as a strategy identity or dedup key across files:
identity is values_sha256 (canonical values, comments excluded) and the library fingerprint (values).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import studio_deploy_profile as profile
from strategy_registry import inspect_set
from studio_evidence import parse_header, read_export
from studio_export_qualification import header_tokens
from studio_strategy_attribution import fingerprint, set_values

FIX = Path(__file__).resolve().parent / 'contracts' / 'profile-fixtures'
STAMP = '; EXPORT: blind=0 ranked=full_span sr=mt5_stat'
GENERAL = '; ===========GENERAL SETTINGS============'
POLICY = dict(aiMode=0, aiThreshold=50, aiProtocol=2)
DEPLOYMENT = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
EA = 'GOAT-EA\\GOAT V1.49.ex5'


def twin_pair():
    b43 = (FIX / 'kestrel-b35-01.set').read_bytes()
    text = b43[2:].decode('utf-16-le')
    assert text.count(GENERAL) == 1
    b44 = b'\xff\xfe' + text.replace(GENERAL, STAMP + '\r\n' + GENERAL).encode('utf-16-le')
    return b43, b44


class StampIdentityTests(unittest.TestCase):
    def setUp(self):
        self.b43, self.b44 = twin_pair()

    def test_the_twin_differs_only_by_the_stamp_line(self):
        a = self.b43[2:].decode('utf-16-le').split('\r\n')
        b = self.b44[2:].decode('utf-16-le').split('\r\n')
        self.assertEqual([line for line in b if line not in a], [STAMP])
        self.assertEqual([line for line in b if line != STAMP], a)

    def test_the_set_reader_and_identity_are_the_same(self):
        a, b = inspect_set(self.b43), inspect_set(self.b44)
        for key in ('canonical_sha256', 'canonical_json', 'ea_desc', 'axes', 'encoding', 'crlf'):
            self.assertEqual(a[key], b[key], key)
        self.assertNotEqual(a['sha256'], b['sha256'], 'the raw file hash is a file pin and does change')
        self.assertEqual(set_values(self.b43), set_values(self.b44))
        self.assertEqual(fingerprint(set_values(self.b43)), fingerprint(set_values(self.b44)))

    def test_header_readers_are_the_same(self):
        decode = lambda raw: raw[2:].decode('utf-16-le')
        self.assertEqual(parse_header(decode(self.b43)), parse_header(decode(self.b44)))
        tokens = lambda raw: {k: (str(v.value), v.source, v.decimals) for k, v in header_tokens(decode(raw)).items()}
        self.assertEqual(tokens(self.b43), tokens(self.b44))
        self.assertEqual(sorted(tokens(self.b43)), ['ARF', 'Prf', 'SR'])

    def test_read_export_is_the_same(self):
        with tempfile.TemporaryDirectory() as folder:
            stem = 'GOAT V1.49 EURUSD,M1_Trds=471_Prf=4177_DD=440_PF=2.42_SR=4.10_ARF=1.332'
            results = []
            for name, raw in (('b43', self.b43), ('b44', self.b44)):
                unit = Path(folder) / name
                unit.mkdir()
                (unit / (stem + '.set')).write_bytes(raw)
                (unit / (stem + '.csv')).write_bytes(('<DATE>\t<BALANCE>\t<EQUITY>\t<DEPOSIT LOAD>\r\n'
                                                      '2026.09.17 23:58\t104177.00\t104177.00\t0.0\r\n').encode('utf-16'))
                results.append(read_export(unit / (stem + '.set')))
            a, b = results
            for key in ('values_sha256', 'alias', 'windows', 'metrics', 'evidence_end', 'evidence_end_source', 'problems'):
                self.assertEqual(a[key], b[key], key)
            for key in ('status', 'missed', 'ea_native_passed'):
                self.assertEqual(a['qualification'][key], b['qualification'][key], key)
            self.assertNotEqual(a['set_sha256'], b['set_sha256'])

    def test_the_deploy_profile_child_chart_is_byte_identical(self):
        member = lambda raw: dict(symbol='EURUSD', name='GOAT V1.49 EURUSD,M1_B35-01_Kestrel-Trend-Breakout.set', raw=raw)
        a = profile.child_chart(member(self.b43), EA, POLICY, DEPLOYMENT)
        b = profile.child_chart(member(self.b44), EA, POLICY, DEPLOYMENT)
        self.assertEqual(a, b)
        self.assertEqual(a, (FIX / 'g4' / 'p1-m1-ai-off' / 'chart02.chr').read_bytes(), 'and both equal the G4 golden')
        self.assertNotIn(STAMP, profile.set_input_lines(self.b44))
        # Other comment lines holding '=' are still kept exactly as before (the writer's contract is unchanged).
        self.assertIn('; PF=2.421 RF=9.483 SR=4.104 ARF=1.332', profile.set_input_lines(self.b44))

    def test_a_blind_stamp_is_dropped_too(self):
        text = self.b43[2:].decode('utf-16-le').replace(GENERAL, '; EXPORT: blind=1 ranked=fit+fwd sr=daily_ann\r\n' + GENERAL)
        self.assertEqual(profile.set_input_lines(b'\xff\xfe' + text.encode('utf-16-le')), profile.set_input_lines(self.b43))


if __name__ == '__main__':
    unittest.main()
