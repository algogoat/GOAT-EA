"""The terminal's tester journal is kept with the run it belongs to, and the check refuses a missing copy (GOAT-EA#315).

Banker and T3, 2026-11-10/11: MT5 cleared the tester's older day logs when a later optimisation started, so a finished
catch-up's journal was gone when the round close needed it. The journals here are fixtures in the journal's own format
(UTF-16LE with BOM, CRLF, tab-separated, MT5 local time); the catch-up and the Prove batch are the real runners."""
from contextlib import redirect_stderr
from datetime import datetime, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import demo_agent
import studio_finish
import studio_tester_journal as journal
from studio_research_status import queue_jobs
from studio_seed_results import read_seed_json
import test_demo_catchup_agent
import test_studio_benchmark

BOM = b'\xff\xfe'


def line(when, message, source='Tester', code='HM', flag='0'):
    """One journal line as MT5 writes it: code, flag, local HH:MM:SS.mmm, source, message."""
    return '\t'.join([code, flag, when.strftime('%H:%M:%S.') + '%03d' % (when.microsecond // 1000), source, message])


def encoded(lines):
    return ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def write_log(data, day, lines, *, tail=b''):
    """``<data>\\Tester\\logs\\<yyyymmdd>.log``; appends to an existing day log, as MT5 does."""
    path = Path(data) / 'Tester' / 'logs' / (day.strftime('%Y%m%d') + '.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_bytes() if path.exists() else BOM
    path.write_bytes(before + encoded(lines) + tail)
    return path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class JournalBlockTests(unittest.TestCase):
    """keep(): the run's own lines, byte for byte, recorded; the journal itself is never touched."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data, self.out = Path(self.temp.name) / 'data', Path(self.temp.name) / 'evidence'
        self.data.mkdir(); self.out.mkdir()
        self.day = datetime(2026, 11, 10)
        at = lambda hour, minute, second=0, milli=0: self.day.replace(hour=hour, minute=minute, second=second, microsecond=milli * 1000)
        self.at = at
        # Three runs on one day: an optimisation, then two single tests. The second test Prints a two-line message.
        self.first = [line(at(7, 0), '"GOAT-EA\\GOAT V1.49.ex5" X64'), line(at(7, 0, 1), 'EURUSD,M1: optimization started'),
                      line(at(7, 4, 59), 'optimization finished, total passes 153')]
        self.second = [line(at(7, 10, 0, 120), 'C00000000000000aa_00001: testing of Experts\\GOAT-EA\\GOAT V1.49.ex5 from 2026.06.06 00:00 to 2026.11.07 00:00 started'),
                       line(at(7, 10, 2), 'EURUSD,M1: 100% real ticks', source='Core 1'),
                       line(at(7, 15, 30), 'a message that continues', source='Core 1'), 'on a second line without a time',
                       line(at(7, 19, 58, 7), 'EURUSD,M1: 4721034 ticks, 153021 bars generated. Test passed in 0:09:57.887', source='Core 1'),
                       line(at(7, 20, 0), 'successfully finished')]
        self.third = [line(at(7, 30), 'C00000000000000aa_00002: testing of Experts\\GOAT-EA\\GOAT V1.49.ex5 started'),
                      line(at(7, 41), 'successfully finished')]
        self.log = write_log(self.data, self.day, self.first + self.second + self.third)
        self.window = (at(7, 10).timestamp(), at(7, 20, 1).timestamp())

    def keep(self, since, until, **options):
        return journal.keep(self.data, since, until, self.out, **options)

    def test_a_runs_own_block_is_copied_byte_for_byte_and_recorded(self):
        before, modified = sha256(self.log), self.log.stat().st_mtime_ns
        record = self.keep(*self.window)
        self.assertEqual((record['status'], record['reason'], record['days_without_lines']), ('copied', None, []))
        (item,) = record['files']
        copy = Path(item['path'])
        self.assertEqual(copy, self.out / 'tester-journal.20261110.log')
        self.assertEqual(copy.read_bytes(), BOM + encoded(self.second))     # its own lines, the continued one included
        self.assertEqual((item['sha256'], item['bytes'], item['lines']), (sha256(copy), copy.stat().st_size, 6))
        self.assertEqual((item['content_sha256'], item['content_bytes'], item['compressed'], item['truncated']),
                         (item['sha256'], item['bytes'], False, None))
        self.assertEqual((item['first_line_time'], item['last_line_time']), ('2026-11-10 07:10:00.120', '2026-11-10 07:20:00.000'))
        self.assertEqual((item['source'], item['source_bytes']), ('Tester\\logs\\20261110.log', self.log.stat().st_size))
        self.assertEqual(self.log.read_bytes()[item['source_start']:item['source_stop']], encoded(self.second))
        self.assertEqual((sha256(self.log), self.log.stat().st_mtime_ns), (before, modified))     # the journal is untouched
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['tester-journal.20261110.log'])
        self.assertEqual(journal.verify(record), ('ok', []))

    def test_the_block_is_found_by_halving_in_a_log_many_blocks_long(self):
        # 6000 lines, one a second from 08:00, read with 4 KiB blocks: every window gives exactly its own lines.
        start = self.at(8, 0)
        lines = [line(start + timedelta(seconds=n), 'pass %d returned result 1.%04d in 0:00:01.000' % (n, n), source='Core %d' % (n % 4 + 1))
                 for n in range(6000)]
        log = write_log(self.data, self.day, lines)
        self.assertGreater(log.stat().st_size, 200 * 4096)
        with patch.object(journal, 'BLOCK', 4096):
            for first, last in ((0, 0), (0, 9), (2999, 3003), (5990, 5999), (17, 4801)):
                record = self.keep((start + timedelta(seconds=first)).timestamp(), (start + timedelta(seconds=last)).timestamp())
                self.assertEqual(record['status'], 'copied', (first, last))
                self.assertEqual(Path(record['files'][0]['path']).read_bytes(), BOM + encoded(lines[first:last + 1]), (first, last))
            # Between two lines there is nothing to copy, and after the last line neither.
            for since in (start + timedelta(seconds=10, milliseconds=100), start + timedelta(hours=3)):
                record = self.keep(since.timestamp(), since.timestamp() + 0.5)
                self.assertEqual((record['status'], record['files']), ('missing', []))

    def test_a_day_log_that_is_gone_is_recorded_as_missing_with_the_reason(self):
        self.log.unlink()                       # what MT5 did to Banker's 20261110.log
        record = self.keep(*self.window)
        self.assertEqual((record['status'], record['files']), ('missing', []))
        self.assertEqual(record['reason'], 'Tester\\logs\\20261110.log does not exist')
        self.assertEqual(list(self.out.iterdir()), [])                      # nothing invented
        state, problems = journal.verify(record)
        self.assertEqual((state, problems), ('missing', ['Tester\\logs\\20261110.log does not exist']))

    def test_a_day_log_without_a_line_of_the_run_is_missing_not_an_empty_copy(self):
        record = self.keep(self.at(9, 0).timestamp(), self.at(9, 30).timestamp())
        self.assertEqual((record['status'], record['files']), ('missing', []))
        self.assertEqual(record['reason'], 'Tester\\logs\\20261110.log has no line between 2026-11-10 09:00:00.000 and 2026-11-10 09:30:00.000')
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.keep(None, 5.0)['reason'], 'The run has no recorded start and end time, so its journal lines cannot be told apart')

    def test_a_run_over_midnight_keeps_both_days_and_needs_the_first(self):
        next_day = self.day + timedelta(days=1)
        late = [line(self.at(23, 58), 'testing started'), line(self.at(23, 59, 59, 999), 'still running', source='Core 1')]
        early = [line(next_day.replace(minute=3), 'successfully finished')]
        write_log(self.data, self.day, late)
        second = write_log(self.data, next_day, early + [line(next_day.replace(hour=2), 'another run')])
        window = (self.at(23, 58).timestamp(), next_day.replace(minute=4).timestamp())
        record = self.keep(*window)
        self.assertEqual((record['status'], [item['day'] for item in record['files']]), ('copied', ['20261110', '20261111']))
        self.assertEqual([Path(item['path']).read_bytes() for item in record['files']], [BOM + encoded(late), BOM + encoded(early)])
        # The second day's log gone: the first day still proves the start, and the record says which day has no lines.
        second.unlink()
        record = self.keep(*window)
        self.assertEqual((record['status'], [item['day'] for item in record['files']]), ('copied', ['20261110']))
        self.assertEqual(record['days_without_lines'], [dict(day='20261111', reason='Tester\\logs\\20261111.log does not exist')])
        # The first day's log gone: missing, whatever the second day holds.
        write_log(self.data, next_day, early)
        self.log.unlink()
        record = self.keep(*window)
        self.assertEqual((record['status'], record['reason']), ('missing', 'Tester\\logs\\20261110.log does not exist'))

    def test_a_line_mt5_is_still_writing_is_left_out(self):
        partial = line(self.at(7, 41, 1), 'half a li').encode('utf-16-le')
        self.log.write_bytes(self.log.read_bytes() + partial)
        record = self.keep(self.at(7, 30).timestamp(), self.at(7, 42).timestamp())
        self.assertEqual(Path(record['files'][0]['path']).read_bytes(), BOM + encoded(self.third))

    def test_a_block_past_the_bound_keeps_its_first_and_last_half_and_says_so(self):
        # Ten lines of one length from 10:00:00 to 10:00:09, bound at four lines and a bit: lines 0-1 and 8-9 are kept.
        lines = [line(self.at(10, 0, n), 'pass %d' % n) for n in range(10)]
        write_log(self.data, self.day, lines)
        one = len(encoded(lines[:1]))
        record = self.keep(self.at(10, 0).timestamp(), self.at(10, 0, 9).timestamp(), limit=4 * one + 2)
        (item,) = record['files']
        self.assertEqual(Path(item['path']).read_bytes(), BOM + encoded(lines[:2] + lines[8:]))
        self.assertEqual(item['truncated'], dict(block_bytes=10 * one, bound_bytes=4 * one + 2, omitted_lines=6))
        self.assertEqual((item['lines'], item['first_line_time'], item['last_line_time']), (4, '2026-11-10 10:00:00.000', '2026-11-10 10:00:09.000'))
        self.assertEqual(journal.verify(record), ('ok', []))
        # At the bound exactly, nothing is left out.
        record = self.keep(self.at(10, 0).timestamp(), self.at(10, 0, 9).timestamp(), limit=10 * one)
        self.assertEqual((record['files'][0]['truncated'], record['files'][0]['lines']), (None, 10))

    def test_a_batch_copy_is_the_same_bytes_gzipped(self):
        record = journal.keep(self.data, self.at(7, 0).timestamp(), self.at(7, 5).timestamp(), self.out / 'tester-journal',
                              name=journal.BATCH_FILE, compress=True, limit=None)
        (item,) = record['files']
        copy = Path(item['path'])
        self.assertEqual(copy, self.out / 'tester-journal' / '20261110.log.gz')
        plain = gzip.decompress(copy.read_bytes())
        self.assertEqual(plain, BOM + encoded(self.first))
        self.assertEqual((item['compressed'], item['sha256'], item['content_sha256'], item['content_bytes']),
                         (True, sha256(copy), hashlib.sha256(plain).hexdigest(), len(plain)))

    def test_verify_refuses_a_copy_changed_or_removed_afterwards(self):
        record = self.keep(*self.window)
        copy = Path(record['files'][0]['path'])
        original = copy.read_bytes()
        copy.write_bytes(original[:-4] + encoded(['x'])[:4])                 # same size, other bytes
        state, problems = journal.verify(record)
        self.assertEqual(state, 'changed')
        self.assertIn('no longer matches its recorded SHA-256 ' + record['files'][0]['sha256'], problems[0])
        copy.write_bytes(original + b'\x00\x00')
        self.assertEqual(journal.verify(record)[0], 'changed')
        copy.unlink()
        state, problems = journal.verify(record)
        self.assertEqual((state, problems), ('missing', ['The copy %s is gone' % copy]))
        self.assertEqual(journal.verify(None), ('missing', ['No tester journal copy was recorded for it']))


class CatchupJournalTests(unittest.TestCase):
    """The real demo catch-up lane: each member's block lands in its evidence folder in the pass that sees it end."""

    def setUp(self):
        self.fixture = test_demo_catchup_agent.DemoCatchupAgentTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.agent, self.data, self.root = self.fixture.agent, self.fixture.data, self.fixture.root
        self.blocks, self.write_journal = {}, True
        finish = self.fixture.finish_member
        def finish_member(index):
            # The member's MT5 wrote its journal while it ran (the last second of the fixture's clock, MT5 local time).
            if self.write_journal:
                when = datetime.fromtimestamp(self.fixture.now - 0.9)
                alias = self.fixture.manifest()['members'][index]['alias']
                self.blocks[index] = [line(when, alias + ': testing of Experts\\GOAT-EA\\GOAT V1.49.ex5 started'),
                                      line(when + timedelta(milliseconds=400), 'EURUSD,M1: 100% real ticks', source='Core 1'),
                                      line(when + timedelta(milliseconds=800), alias + ': successfully finished')]
                self.log = write_log(self.data, when, self.blocks[index])
            finish(index)
        self.fixture.finish_member = finish_member

    def run_catchup(self):
        self.agent.catchup_prepare('cu1', self.fixture.plan)
        self.fixture.auto = True
        self.assertEqual(self.agent.catchup_start('cu1', 60)['status'], 'completed')
        return read_seed_json(self.root / 'catchups/cu1/state.json')['members']

    def test_each_member_keeps_its_own_block_in_its_evidence_folder_and_the_check_passes(self):
        # An optimisation earlier the same day (at midnight) is in the same day log; it is nobody's block here.
        earlier = datetime.fromtimestamp(self.fixture.now).replace(hour=0, minute=0, second=0, microsecond=0)
        other = [line(earlier, 'EURUSD,M1: optimization started'), line(earlier + timedelta(milliseconds=5), 'optimization finished')]
        log = write_log(self.data, earlier, other)
        members = self.run_catchup()
        source = sha256(log)
        for index, (spec, item) in enumerate(zip(self.fixture.manifest()['members'], members)):
            record = item['tester_journal']
            self.assertEqual((record['status'], len(record['files'])), ('copied', 1))
            copy = Path(record['files'][0]['path'])
            self.assertEqual(copy.parent, Path(spec['evidence_dir']))                # the member's capture folder
            self.assertTrue((copy.parent / 'evidence-version.json').is_file())
            self.assertEqual(copy.read_bytes(), BOM + encoded(self.blocks[index]))   # its own test, nothing else
            self.assertEqual(record['files'][0]['sha256'], sha256(copy))
            self.assertLessEqual(item['started_unix'], record['window']['since_unix'])
            self.assertEqual(record['window']['until_unix'], item['finished_unix'])
        self.assertEqual(log.read_bytes(), BOM + encoded(other + self.blocks[0] + self.blocks[1]))
        self.assertEqual(sha256(log), source)
        check = self.agent.tester_journal_check(catchup_id='cu1')
        self.assertEqual((check['ok'], check['writes'], check['counts'], check['status']), (True, False, dict(ok=2), 'completed'))
        self.assertEqual([(row['journal'], row['problems'], len(row['files'])) for row in check['members']], [('ok', [], 1)] * 2)
        # A status read after the end copies nothing again and changes no record.
        self.agent.catchup_status('cu1')
        self.assertEqual(read_seed_json(self.root / 'catchups/cu1/state.json')['members'], members)

    def test_a_catchup_whose_journal_was_gone_is_recorded_missing_and_the_check_refuses(self):
        self.write_journal = False
        members = self.run_catchup()
        day = datetime.fromtimestamp(members[0]['started_unix']).strftime('%Y%m%d')
        reason = 'Tester\\logs\\%s.log does not exist' % day
        self.assertEqual([(m['tester_journal']['status'], m['tester_journal']['reason'], m['tester_journal']['files']) for m in members],
                         [('missing', reason, [])] * 2)
        self.assertFalse((self.data / 'Tester').exists())                             # nothing invented beside the terminal either
        check = self.agent.tester_journal_check(catchup_id='cu1')
        self.assertEqual((check['ok'], check['counts']), (False, dict(missing=2)))
        self.assertEqual([row['problems'] for row in check['members']], [[reason]] * 2)
        self.assertIn('2 of 2 tester journal copies of catch-up cu1 missing or changed', check['plain'])
        # The command line says it the way stop_unconfirmed does: ok false on stderr, exit 2.
        errors = io.StringIO()
        with patch('demo_agent.DemoAgent', return_value=self.agent), redirect_stderr(errors):
            code = demo_agent.main(['--installation', str(self.fixture.installation), 'tester-journal-check', '--catchup-id', 'cu1'])
        said = json.loads(errors.getvalue())
        self.assertEqual((code, said['ok'], said['code'], said['result']['counts']), (2, False, 'TESTER_JOURNAL_MISSING', dict(missing=2)))

    def test_the_check_refuses_a_copy_altered_or_removed_after_the_run(self):
        members = self.run_catchup()
        first, second = (Path(m['tester_journal']['files'][0]['path']) for m in members)
        first.write_bytes(first.read_bytes() + encoded(['a line added later']))
        check = self.agent.tester_journal_check(catchup_id='cu1')
        self.assertEqual((check['ok'], check['counts']), (False, dict(changed=1, ok=1)))
        self.assertEqual([row['journal'] for row in check['members']], ['changed', 'ok'])
        second.unlink()
        check = self.agent.tester_journal_check(catchup_id='cu1')
        self.assertEqual((check['ok'], check['counts']), (False, dict(changed=1, missing=1)))
        self.assertEqual(check['members'][1]['problems'], ['The copy %s is gone' % second])

    def test_a_catchup_that_has_not_finished_or_a_wrong_request_is_not_ok(self):
        self.agent.catchup_prepare('cu1', self.fixture.plan)
        check = self.agent.tester_journal_check(catchup_id='cu1')
        self.assertEqual((check['ok'], check['counts'], check['status']), (False, dict(not_run=2), 'prepared'))
        self.assertIn('has not finished (prepared)', check['plain'])
        for arguments, words in ((dict(), 'exactly one of'), (dict(catchup_id='cu1', batch_id='b'), 'exactly one of'),
                                 (dict(catchup_id='none'), 'No catch-up none'), (dict(batch_id='none'), 'No batch none')):
            with self.assertRaisesRegex(ValueError, words):
                self.agent.tester_journal_check(**arguments)


class BatchJournalTests(unittest.TestCase):
    """The real finish of a native (Prove) batch: the batch's block is in the attempt folder and in result.json."""

    def finished(self, lines=None):
        fixture = test_studio_benchmark.BenchmarkTests()
        real = studio_finish.observe
        def observe(package):
            # Before finish reads anything: the tester journal as it stands when the batch ends.
            if lines is not None and not getattr(fixture, 'log', None):
                time.sleep(0.01)
                when = datetime.now()
                earlier = [line(when.replace(hour=0, minute=0, second=0, microsecond=0), 'another batch: optimization finished')]
                fixture.block = [line(when + timedelta(milliseconds=n), text) for n, text in enumerate(lines)]
                fixture.log = write_log(fixture.c.install['terminal_data_root'], when, earlier + fixture.block)
                fixture.log_sha256 = sha256(fixture.log)
            return real(package)
        with patch.object(studio_finish, 'observe', side_effect=observe):
            fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def job(self, fixture):
        return next(job for job in queue_jobs(fixture.c.root, dict(terminal_id=fixture.c.terminal, run_id=fixture.c.run))
                    if job['job_id'] == 'customer-batch')

    def test_finish_keeps_the_batchs_block_next_to_its_result_and_the_check_passes(self):
        fixture = self.finished(['EURUSD,M1: optimization started', 'optimization finished, total passes 153'])
        result = json.loads(fixture.result_path.read_text(encoding='utf-8'))
        record = result['tester_journal']
        self.assertEqual((record['status'], record['reason'], len(record['files'])), ('copied', None, 1))
        copy = Path(record['files'][0]['path'])
        self.assertEqual(copy.parent, fixture.result_path.parent / 'tester-journal')
        self.assertEqual(gzip.decompress(copy.read_bytes()), BOM + encoded(fixture.block))   # the batch's lines, not the earlier batch's
        self.assertEqual(record['files'][0]['sha256'], sha256(copy))
        self.assertEqual(sha256(fixture.log), fixture.log_sha256)                              # the journal is untouched
        job = self.job(fixture)
        self.assertEqual(job['completion']['tester_journal'], record)                         # the stored result carries it
        check = journal.check_batch(fixture.c.root, job)
        self.assertEqual((check['ok'], check['journal'], check['member_count'], check['writes']), (True, 'ok', 2, False))
        copy.write_bytes(copy.read_bytes() + b'\x00')
        check = journal.check_batch(fixture.c.root, job)
        self.assertEqual((check['ok'], check['journal']), (False, 'changed'))
        copy.unlink()
        self.assertEqual(journal.check_batch(fixture.c.root, job)['journal'], 'missing')

    def test_a_batch_whose_journal_was_gone_still_finishes_and_the_check_refuses(self):
        fixture = self.finished()
        record = json.loads(fixture.result_path.read_text(encoding='utf-8'))['tester_journal']
        self.assertEqual((record['status'], record['files']), ('missing', []))
        self.assertRegex(record['reason'], r'^Tester\\logs\\\d{8}\.log does not exist$')
        self.assertFalse((fixture.result_path.parent / 'tester-journal').exists())
        job = self.job(fixture)
        self.assertEqual(job['status'], 'completed')
        check = journal.check_batch(fixture.c.root, job)
        self.assertEqual((check['ok'], check['journal'], check['problems']), (False, 'missing', [record['reason']]))
        # A batch still running, or one that never launched, is said as it is.
        self.assertEqual(journal.check_batch(fixture.c.root, dict(job, status='running'))['journal'], 'running')
        never = {key: value for key, value in job.items() if key not in ('launch_intent', 'completion')} | dict(status='cancelled')
        check = journal.check_batch(fixture.c.root, never)
        self.assertEqual((check['ok'], check['journal']), (True, 'not_run'))


if __name__ == '__main__':
    unittest.main()
