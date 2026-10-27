from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import studio_evidence_end as ee


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class AutoEvidenceEndTests(unittest.TestCase):
    """AUTO = the latest fully closed Friday; the FX week closes at server Saturday 00:00."""

    def test_friday_before_close_is_previous_friday(self):
        # Fri 2026-10-02 18:00 server (UTC+3 in US daylight time): this week is still open.
        result = ee.auto(utc('2026-10-02T15:00:00'))
        self.assertEqual(result['date'], '2026.09.25')
        self.assertEqual(result['tester_to_date'], '2026.09.26')
        self.assertEqual(result['server_now'], '2026-10-02 18:00')
        self.assertEqual(result['next_date'], '2026.10.02')
        # Server Saturday 00:00 = Friday 21:00 UTC (14:00 in New York ... 17:00 NY close).
        self.assertEqual(result['next_switch_utc'], '2026-10-02T21:00Z')

    def test_switch_happens_exactly_at_server_midnight(self):
        self.assertEqual(ee.auto(utc('2026-10-02T20:59:59'))['date'], '2026.09.25')
        self.assertEqual(ee.auto(utc('2026-10-02T21:00:00'))['date'], '2026.10.02')

    def test_weekend_and_midweek_point_to_last_closed_friday(self):
        for moment, expected in (('2026-10-03T08:00:00', '2026.10.02'), ('2026-10-04T12:00:00', '2026.10.02'),
                                 ('2026-10-05T09:00:00', '2026.10.02'), ('2026-10-08T23:00:00', '2026.10.02'),
                                 ('2026-10-09T20:59:00', '2026.10.02'), ('2026-10-09T21:00:00', '2026.10.09')):
            with self.subTest(moment=moment):
                self.assertEqual(ee.auto(utc(moment))['date'], expected)

    def test_standard_time_uses_utc_plus_two(self):
        # After the first Sunday of November New York is on EST: server is UTC+2, close at 22:00 UTC.
        self.assertEqual(ee.auto(utc('2026-11-06T21:30:00'))['date'], '2026.10.30')
        self.assertEqual(ee.auto(utc('2026-11-06T22:00:00'))['date'], '2026.11.06')
        self.assertEqual(ee.auto(utc('2026-11-06T21:30:00'))['next_switch_utc'], '2026-11-06T22:00Z')

    def test_us_daylight_boundaries(self):
        self.assertFalse(ee.us_daylight(utc('2026-03-08T06:59:00')))
        self.assertTrue(ee.us_daylight(utc('2026-03-08T07:00:00')))
        self.assertTrue(ee.us_daylight(utc('2026-11-01T05:59:00')))
        self.assertFalse(ee.us_daylight(utc('2026-11-01T06:00:00')))

    def test_fixed_broker_clock(self):
        # A UTC+0 server rolls over at 00:00 UTC: Friday 23:00 UTC is still Friday.
        self.assertEqual(ee.auto(utc('2026-10-02T23:00:00'), clock='utc')['date'], '2026.09.25')
        self.assertEqual(ee.auto(utc('2026-10-03T00:00:00'), clock='utc')['date'], '2026.10.02')
        self.assertEqual(ee.offset_minutes(utc('2026-01-01T00:00:00'), 'utc+3:30'), 210)
        self.assertEqual(ee.offset_minutes(utc('2026-01-01T00:00:00'), 'utc-5'), -300)
        for bad in ('gmt+2', 'utc+15', 'ny', 5):
            with self.assertRaises(ValueError):
                ee.parse_clock(bad)

    def test_friday_holiday_closes_with_thursday(self):
        # Good Friday 2026-04-03: the week closed with Thursday, so on that Friday AUTO is the same day.
        result = ee.auto(utc('2026-04-03T10:00:00'), holidays=['2026-04-03'])
        self.assertEqual(result['date'], '2026.04.03')
        self.assertTrue(result['friday_holiday'])
        self.assertEqual(result['last_session'], '2026.04.02')
        without = ee.auto(utc('2026-04-03T10:00:00'))
        self.assertEqual(without['date'], '2026.03.27')

    def test_upcoming_holiday_switches_at_its_midnight(self):
        result = ee.auto(utc('2026-03-31T10:00:00'), holidays=['2026-04-03'])
        self.assertEqual(result['date'], '2026.03.27')
        self.assertEqual(result['next_switch_utc'], '2026-04-02T21:00Z')

    def test_days_back_matches_mql_friday_rule(self):
        # MQL day_of_week Sunday=0..Saturday=6; Python Monday=0..Sunday=6.
        for python_weekday in range(7):
            mql = (python_weekday + 1) % 7
            expected = 7 if mql == 5 else (mql - 5 if mql > 5 else mql + 2)
            self.assertEqual(ee.friday_days_back(python_weekday), expected)
        self.assertEqual(ee.friday_days_back(4, friday_holiday=True), 0)


class ResolveTests(unittest.TestCase):
    NOW = utc('2026-10-02T15:00:00')  # Friday 18:00 server, week still open

    def test_auto_spellings(self):
        for value in (None, '', 'auto', 'AUTO', 'Auto'):
            result = ee.resolve(value, self.NOW)
            self.assertEqual((result['mode'], result['date'], result['iso']), ('auto', '2026.09.25', '2026-09-25'))
            self.assertEqual(result['warnings'], [])

    def test_explicit_closed_days(self):
        result = ee.resolve('2026-09-18', self.NOW)
        self.assertEqual((result['mode'], result['date'], result['tester_to_date'], result['label']),
                         ('explicit', '2026.09.18', '2026.09.19', 'Fri Sep 18'))
        self.assertEqual(result['warnings'], [])
        mt5 = ee.resolve('2026.10.01', self.NOW)
        self.assertEqual(mt5['iso'], '2026-10-01')
        self.assertEqual(len(mt5['warnings']), 2)  # not a Friday, and inside the unfinished week
        self.assertIn('not a Friday', mt5['warnings'][0])

    def test_today_and_future_are_refused(self):
        for value in ('2026-10-02', '2026-10-09', '2027-01-01'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'not a closed broker day'):
                ee.resolve(value, self.NOW)

    def test_not_before_limits(self):
        with self.assertRaisesRegex(ValueError, 'nothing new would be tested'):
            ee.resolve('2026-09-18', self.NOW, not_before=[('2026-09-24', 'the export end')])
        self.assertEqual(ee.resolve('2026-09-25', self.NOW, not_before=[(date(2026, 9, 24), 'x')])['iso'], '2026-09-25')

    def test_malformed_dates(self):
        for value in ('2026-9-25', '2026.09-25', '25/09/2026', '2026-02-30', 'tomorrow', 20260925):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ee.resolve(value, self.NOW)

    def test_naive_now_is_utc_and_bad_now_refused(self):
        self.assertEqual(ee.resolve('auto', datetime(2026, 10, 2, 15))['date'], '2026.09.25')
        with self.assertRaises(ValueError):
            ee.auto('2026-10-02')

    def test_legacy_end_is_thursday_before_the_eas_last_friday(self):
        # GetLastFridayDate returns today on Friday; ToDate is exclusive, so evidence ends Thursday.
        friday = ee.legacy_end(utc('2026-10-02T15:00:00'))
        self.assertEqual((friday['tester_to_date'], friday['date'], friday['weekday']), ('2026.10.02', '2026.10.01', 'Thu'))
        thursday = ee.legacy_end(utc('2026-10-01T10:00:00'))
        self.assertEqual((thursday['tester_to_date'], thursday['date']), ('2026.09.25', '2026.09.24'))


class CapabilityAndHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = dict(terminal_data_root=str(self.root / 'data'), ea_relative_path='GOAT-EA\\GOAT V1.49.ex5')
        self.observation = self.root / 'ui-observation.json'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, value, encoding='utf-8'):
        self.observation.write_bytes(json.dumps(value).encode(encoding))

    def test_capability_requires_matching_program_and_flag(self):
        self.assertEqual(ee.ea_capability(self.install, self.observation)['basis'], 'monitor_observation_missing')
        program = str(Path(self.install['terminal_data_root']) / 'MQL5' / 'Experts' / 'GOAT-EA' / 'GOAT V1.49.ex5')
        self.write(dict(runtime=dict(program_path=program)))
        self.assertEqual(ee.ea_capability(self.install, self.observation)['basis'], 'monitor_build_lacks_evidence_end')
        self.write(dict(runtime=dict(program_path='C:\\other\\GOAT V1.49.ex5'), evidence_end=ee.CAPABILITY))
        self.assertEqual(ee.ea_capability(self.install, self.observation)['basis'], 'monitor_program_differs')
        self.write(dict(runtime=dict(program_path=program), evidence_end=ee.CAPABILITY), 'utf-16')
        self.assertTrue(ee.ea_capability(self.install, self.observation)['supported'])
        self.observation.write_text('{not json')
        self.assertEqual(ee.ea_capability(self.install, self.observation)['basis'], 'monitor_observation_unreadable')

    def test_history_probe_is_advisory(self):
        self.assertEqual(ee.history_check(self.install, 'Darwinex-Demo', 'AUDUSD', '2026-10-02')['status'], 'missing')
        folder = Path(self.install['terminal_data_root']) / 'bases' / 'Darwinex-Demo' / 'ticks' / 'AUDUSD'
        folder.mkdir(parents=True)
        self.assertIn('2026-10', ee.history_check(self.install, 'Darwinex-Demo', 'AUDUSD', '2026-10-02')['note'])
        (folder / '202610.tkc').write_bytes(b'x')
        self.assertEqual(ee.history_check(self.install, 'Darwinex-Demo', 'AUDUSD', '2026.10.02')['status'], 'present')
        self.assertEqual(ee.history_check(self.install, 'Darwinex-Demo', '..\\x', '2026-10-02')['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
