"""B44 item 6 (GOAT-EA, goatai#2350): the controller reads a capture whose minute marks went coarser.

Past 1,000,000 rows the EA writes its minute marks every 5 minutes instead of stopping the capture at
2,000,000 rows. It records that as marks_status=marks_downsampled and marks_interval_changed_at (server msc) in
completion.csv and as sampling.status / marksIntervalChangedAt / intervalMillisecondsAfterChange in the manifest.
capture_status and the manifest status are unchanged. These fixtures prove the controller's trace readers take
such a capture as complete (no refusal) and do not read the interval change as missing data. The readers were
not changed: this test passed against them as they were.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import studio_catchup
import studio_catchup_rebase as rb
from studio_evidence import COMPLETE, read_capture, read_export
from test_studio_catchup_verdict import make_unit, msc

CHANGED = datetime(2026, 9, 15, 10, 0)


def coarse_rows(first, last):
    """Account rows every minute until CHANGED, then every 5 minutes (EA trading hours 08:00-20:00, weekdays)."""
    rows, value, day = [], Decimal('10000'), first
    while day <= last:
        if day.weekday() < 5:
            moment = datetime.combine(day, time(8))
            while moment < datetime.combine(day, time(20)):
                rows.append((moment, Decimal('10000'), value))
                value += Decimal('0.01')
                moment += timedelta(minutes=1 if moment < CHANGED else 5)
        day += timedelta(days=1)
    return rows


def downsample(set_path, changed_msc):
    """Write what B44's GoatTraceCompletion and GoatTracePublish add for a downsampled capture."""
    package = Path(str(set_path)[:-4] + '.goatseq')
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    manifest['sampling'] = dict(intervalMilliseconds=60000, drawdown='sampled', policy='minute-and-event', status='marks_downsampled',
                                marksIntervalChangedAt=changed_msc, intervalMillisecondsAfterChange=300000)
    (package / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (package / 'completion.csv').write_text(
        'key,value\ntester_finished,true\ndeinit_reason,1\nobserved_end_server_msc,%d\nrows,1000001\n'
        'marks_status,marks_downsampled\nmarks_interval_changed_at,%d\nerror,\n'
        'capture_status,complete-awaiting-external-reconciliation\nfooter,END\n'
        % (manifest['observedPeriod']['endServerMsc'], changed_msc), encoding='utf-8')
    return package


class MarksDownsampledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.last = date(2026, 10, 9)
        rows = coarse_rows(date(2026, 9, 7), self.last)
        self.rows = rows
        self.set_path = make_unit(self.root / 'unit', rows=rows, start=date(2026, 9, 7), windows=())
        self.package = downsample(self.set_path, msc(CHANGED))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_fixture_is_downsampled_after_the_change(self):
        pairs = [(a[0], (b[0] - a[0]).seconds) for a, b in zip(self.rows, self.rows[1:]) if a[0].date() == b[0].date()]
        before = [gap for moment, gap in pairs if moment < CHANGED]
        after = [gap for moment, gap in pairs if moment >= CHANGED]
        self.assertEqual((set(before), set(after)), ({60}, {300}))

    def test_read_capture_takes_it_as_complete(self):
        capture = read_capture(self.package, None)
        self.assertTrue(capture['complete'])
        self.assertEqual((capture['status'], capture['reason']), (COMPLETE, ''))

    def test_read_export_ends_at_the_observed_end_without_problems(self):
        export = read_export(self.set_path)
        self.assertEqual(export['problems'], [])
        self.assertTrue(export['capture']['complete'])
        self.assertEqual((export['evidence_end'], export['evidence_end_source']), ('2026-10-09', 'capture'))
        self.assertFalse(export['history_short'])
        # Against the catch-up target the coarser marks are not short of data (no EVIDENCE_END_SHORT).
        self.assertEqual(studio_catchup.evidence_end_short(export, '2026-10-09'), (None, None))

    def test_the_capture_files_read_across_the_change(self):
        cut = msc(datetime.combine(self.last + timedelta(days=1), time()))
        run = rb.read_run(str(self.package / 'deals.csv'), [], cut)
        self.assertEqual(run['missing'], [])
        account = list(run['account'])
        self.assertEqual(len(account), len(self.rows))
        stamps = [row[1] for row in account]
        self.assertEqual(stamps, sorted(stamps))
        self.assertIn(msc(CHANGED), stamps)
        self.assertEqual(stamps[-1], msc(self.rows[-1][0]))

    def test_without_the_change_nothing_differs(self):
        plain = make_unit(self.root / 'plain', rows=self.rows, start=date(2026, 9, 7), windows=())
        a, b = read_export(plain), read_export(self.set_path)
        for key in ('evidence_end', 'evidence_end_source', 'history_short', 'problems'):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual(a['capture']['complete'], b['capture']['complete'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
