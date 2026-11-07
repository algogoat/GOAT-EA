"""B49b (F8; goatai#2587 6433828681, Claude-Mac 6433854745 ruling 3, 6443122557): the export-format stamp.

From B49b every export carries '; EXPORT format:2 rank:arf_sr|pf' after its B44 stamp (GOAT V1.49.mq5
GoatExportFormatLine; scripts/test_b49b_f8.cjs). The controller reads it as the export's evidence segment: a SET without
it is format 1, a stamp it cannot read refuses, and format 1 and format 2 exports never pool (MIXED_EXPORT_FORMAT). The
line holds no '=', and the deploy writer drops it like every '; EXPORT' line, so a deployed chart is unchanged by it.

Fixture: a real kept B49a export (controller/fixtures/oosc/g6, UTF-16), copied without its capture and stamped where
WriteSet puts the line (after the description, before the GENERAL SETTINGS line).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import studio_deploy_profile as profile
from studio_evidence import (MIXED_EXPORT_FORMAT, parse_export_format, parse_header, read_export,
                             require_one_export_format)

FIXTURE = next((Path(__file__).resolve().parent / 'fixtures' / 'oosc' / 'g6' / 'deploy').rglob('GOAT V1.49 AUDUSD,M1_Trds=406_*.set'))
B44 = '; EXPORT blind:0 ranked:full_span sr:mt5_stat'


def stamped(text, line):
    """``text`` with ``line`` placed where WriteSet puts the export stamps (before the GENERAL SETTINGS line)."""
    marker = text.index('; ===========GENERAL SETTINGS')
    return text[:marker] + line + '\r\n' + text[marker:]


class ParseTests(unittest.TestCase):
    def test_no_stamp_is_format_1(self):
        self.assertEqual(parse_export_format('; SAMPLE: x\n' + B44 + '\nRisk=500\n'), dict(format=1, rank='arf_sr'))

    def test_format_2_and_its_rank(self):
        for rank in ('arf_sr', 'pf'):
            text = '; ----\r\n' + B44 + '\r\n; EXPORT format:2 rank:' + rank + '\r\nRisk=500\r\n'
            self.assertEqual(parse_export_format(text), dict(format=2, rank=rank))
        self.assertEqual(parse_export_format('﻿; EXPORT format:2 rank:pf\n')['format'], 2, 'a BOM before the line')

    def test_unreadable_unknown_or_repeated_stamps_refuse(self):
        for line, reason in (('; EXPORT format:2', 'Unreadable'), ('; EXPORT format:2 rank:PF', 'Unreadable'),
                             ('; EXPORT format=2 rank=pf', 'Unreadable'), ('; EXPORT format:2 rank:pf extra', 'Unreadable'),
                             ('; EXPORT format:3 rank:pf', 'Unknown export format 3'),
                             ('; EXPORT format:1 rank:arf_sr', 'Unknown export format 1')):
            with self.assertRaisesRegex(ValueError, reason, msg=line):
                parse_export_format('; ----\n' + line + '\n')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_export_format('; EXPORT format:2 rank:pf\n; EXPORT format:2 rank:pf\n')

    def test_the_b44_stamp_is_not_a_format_line(self):
        self.assertEqual(parse_export_format(B44 + '\n; EXPORT blind:1 ranked:fit+fwd sr:daily_ann\n')['format'], 1)


class PoolTests(unittest.TestCase):
    def test_one_format_pools(self):
        self.assertEqual(require_one_export_format([dict(export_format=2), dict(export_format=2)]), 2)
        self.assertEqual(require_one_export_format([dict(export_format=1)]), 1)
        self.assertIsNone(require_one_export_format([]))

    def test_a_mixed_pool_is_refused(self):
        with self.assertRaisesRegex(ValueError, MIXED_EXPORT_FORMAT + r'.*format 1: 2, format 2: 1'):
            require_one_export_format([dict(export_format=1), dict(export_format=2), dict(export_format=1)])


class RealExportTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        raw = FIXTURE.read_bytes()
        self.text = raw.decode('utf-16')
        self.assertNotIn('EXPORT format', self.text, 'the fixture is a B49a (format 1) export')

    def write(self, text, name):
        path = self.dir / name / FIXTURE.name
        path.parent.mkdir()
        path.write_bytes(b'\xff\xfe' + text.encode('utf-16-le'))
        return path

    def test_read_export_reports_the_format_and_a_mixed_scan_refuses(self):
        old = read_export(self.write(self.text, 'old'))
        new = read_export(self.write(stamped(self.text, '; EXPORT format:2 rank:pf'), 'new'))
        self.assertEqual((old['export_format'], old['export_rank']), (1, 'arf_sr'))
        self.assertEqual((new['export_format'], new['export_rank']), (2, 'pf'))
        self.assertEqual(old['windows'], new['windows'], 'the stamp is not a window line')
        self.assertEqual(old['values_sha256'], new['values_sha256'], 'nor an input: the strategy identity is unchanged')
        with self.assertRaisesRegex(ValueError, MIXED_EXPORT_FORMAT):
            require_one_export_format([old, new])

    def test_an_unreadable_stamp_makes_the_export_unreadable(self):
        with self.assertRaisesRegex(ValueError, 'Unreadable export-format stamp'):
            read_export(self.write(stamped(self.text, '; EXPORT format:two rank:pf'), 'bad'))

    def test_the_deploy_writer_drops_the_line(self):
        plain = profile.set_input_lines(self.write(self.text, 'plain').read_bytes())
        with_stamp = profile.set_input_lines(self.write(stamped(self.text, '; EXPORT format:2 rank:arf_sr'), 'stamp').read_bytes())
        self.assertEqual(plain, with_stamp, 'a deployed chart is byte for byte its format 1 twin')
        self.assertEqual(parse_header(self.text), parse_header(stamped(self.text, '; EXPORT format:2 rank:arf_sr')))


if __name__ == '__main__':
    unittest.main()
