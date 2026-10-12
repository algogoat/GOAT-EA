"""B44 condition 2 (GOAT-EA, goatai#2350 6127809765, 6128225191): the export stamp changes no identity and never reaches
a deployed chart, with the current controller or with the testers' c708cae4 one.

A B44 export carries '; EXPORT blind:0 ranked:full_span sr:mt5_stat' (blind=0) or '; EXPORT blind:1 ranked:fit+fwd
sr:daily_ann' plus '; RANKED fit+fwd ... Days:.. Trades:.. PL:.. SR:.. ARF:..' (blind=1) in its SET header. Neither
line holds '=': every controller writer copies only comment lines holding '=' into a chart, so c708cae4 (pinned here as
an untouched copy of its studio_deploy_profile.py, controller/contracts/profile-fixtures/c708cae4) drops them by
itself; the current writer and GOATDeployProfileWriter.mqh also drop any '; EXPORT' line (defence in depth).

Fixture: the real B35-01 Kestrel export (UTF-16, CRLF) and its stamped twins, the stamp placed where WriteSet puts it
(after OnTester's description, before the GENERAL SETTINGS line).

Same (asserted): the SET reader (inspect_set values, canonical hash, EA_Desc, axes), the header windows, the
qualification header tokens, read_export's values identity / windows / metrics / qualification / evidence end, the
library fingerprint, and the child chart byte for byte (the G4 golden) from both writers.

Different, by design: the raw file sha256. The controller uses it only to pin one specific file (the capture manifest's
binding, a registration's expected hash, held-out freeze cells, export-scan stamps, strategy_registry revisions of a
template suite), never as a strategy identity or dedup key across files.
"""
import hashlib
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

import studio_deploy_profile as profile
from strategy_registry import inspect_set
from studio_evidence import parse_header, read_export
from studio_export_qualification import header_tokens
from studio_strategy_attribution import fingerprint, set_values

FIX = Path(__file__).resolve().parent / 'contracts' / 'profile-fixtures'
OLD_WRITER = FIX / 'c708cae4' / 'studio_deploy_profile.py.txt'
OLD_WRITER_BLOB = '6dfb4de96dc8f24afe5714b28c9015e444a9184a'   # git ls-tree c708cae4 controller/studio_deploy_profile.py
STAMP0 = '; EXPORT blind:0 ranked:full_span sr:mt5_stat'
STAMP1 = '; EXPORT blind:1 ranked:fit+fwd sr:daily_ann'
RANKED = '; RANKED fit+fwd 2026.03.02-2026.08.15 Days:120 Trades:335 PL:3345.00 SR:1.234 ARF:0.456'
PRE_RELEASE = '; EXPORT: blind=0 ranked=full_span sr=mt5_stat'
GENERAL = '; ===========GENERAL SETTINGS============'
POLICY = dict(aiMode=0, aiThreshold=50, aiProtocol=2)
DEPLOYMENT = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
EA = 'GOAT-EA\\GOAT V1.49.ex5'
GOLDEN = FIX / 'g4' / 'p1-m1-ai-off' / 'chart02.chr'


def old_writer():
    raw = OLD_WRITER.read_bytes()
    assert hashlib.sha1(b'blob %d\0' % len(raw) + raw).hexdigest() == OLD_WRITER_BLOB, 'the pinned c708cae4 writer was edited'
    loader = importlib.machinery.SourceFileLoader('studio_deploy_profile_c708cae4', str(OLD_WRITER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def b43_text():
    raw = (FIX / 'kestrel-b35-01.set').read_bytes()
    text = raw[2:].decode('utf-16-le')
    assert text.count(GENERAL) == 1
    return text


def encode(text):
    return b'\xff\xfe' + text.encode('utf-16-le')


def stamped(text, *lines):
    return text.replace(GENERAL, ''.join(line + '\r\n' for line in lines) + GENERAL)


def blind_header(text):
    """A blind=1 SET as GoatBlindDesc writes it: the program line, separators and BOOS/SAMPLE/FWD lines only."""
    head, body = text.split(GENERAL, 1)
    kept = [line for line in head.split('\r\n') if line.startswith(('; ---', '; GOAT ', '; BOOS:', '; SAMPLE:', '; FWD:'))]
    return '\r\n'.join(kept) + '\r\n' + GENERAL + body


def member(raw):
    return dict(symbol='EURUSD', name='GOAT V1.49 EURUSD,M1_B35-01_Kestrel-Trend-Breakout.set', raw=raw)


class StampIdentityTests(unittest.TestCase):
    def setUp(self):
        self.text = b43_text()
        self.b43, self.b44 = encode(self.text), encode(stamped(self.text, STAMP0))

    def test_the_stamp_lines_hold_no_equals_sign(self):
        for line in (STAMP0, STAMP1, RANKED):
            self.assertNotIn('=', line)

    def test_the_twin_differs_only_by_the_stamp_line(self):
        a, b = self.text.split('\r\n'), stamped(self.text, STAMP0).split('\r\n')
        self.assertEqual([line for line in b if line not in a], [STAMP0])
        self.assertEqual([line for line in b if line != STAMP0], a)

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


class DeployedChartTests(unittest.TestCase):
    """The child chart: current writer and the testers' c708cae4 writer, blind=0 and blind=1."""

    def setUp(self):
        self.text = b43_text()
        self.old = old_writer()

    def chart(self, writer, text):
        return writer.child_chart(member(encode(text)), EA, POLICY, DEPLOYMENT)

    def test_blind0_with_both_writers_is_the_unstamped_golden(self):
        golden = GOLDEN.read_bytes()
        for writer in (profile, self.old):
            with self.subTest(writer=writer.__name__):
                self.assertEqual(self.chart(writer, self.text), golden)
                self.assertEqual(self.chart(writer, stamped(self.text, STAMP0)), golden)

    def test_blind1_with_both_writers_equals_its_unstamped_twin(self):
        blind = blind_header(self.text)
        unstamped = self.chart(self.old, blind)
        for writer in (profile, self.old):
            with self.subTest(writer=writer.__name__):
                self.assertEqual(self.chart(writer, stamped(blind, STAMP1, RANKED)), unstamped)
                self.assertEqual(self.chart(writer, blind), unstamped)

    def test_the_hole_closed_the_equals_form_would_reach_a_c708cae4_chart(self):
        # The pre-release '; EXPORT: blind=...' line holds '=': c708cae4 would copy it into the chart; the current
        # writer drops it (defence in depth); the shipped key:value form never reaches either.
        self.assertNotEqual(self.chart(self.old, stamped(self.text, PRE_RELEASE)), GOLDEN.read_bytes())
        self.assertIn(PRE_RELEASE, self.old.set_input_lines(encode(stamped(self.text, PRE_RELEASE))))
        self.assertEqual(self.chart(profile, stamped(self.text, PRE_RELEASE)), GOLDEN.read_bytes())

    def test_current_writer_drops_only_the_stamp(self):
        lines = profile.set_input_lines(encode(stamped(self.text, STAMP0, PRE_RELEASE)))
        self.assertNotIn(STAMP0, lines)
        self.assertNotIn(PRE_RELEASE, lines)
        self.assertIn('; PF=2.421 RF=9.483 SR=4.104 ARF=1.332', lines, "other comment lines holding '=' are kept as before")


if __name__ == '__main__':
    unittest.main()
