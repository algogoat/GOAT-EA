"""news-history-sync (goatai#2350): GOAT_News.csv from /api/ea/news-history.

Every HTTP exchange is mocked (no request ever leaves the test) and every file lives in a temporary folder.
The credential tests prove the stored credential never reaches stdout, stderr, the reply, the receipt, the
request URL or any file other than its own, on success and on every failure path.
"""
from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import re
import urllib.error
import urllib.request
import urllib.response

from campaign_ledger import packed, sha
import studio_news_history as news
from studio_refusal import Refusal

NOW = 1791504000.0                                     # 2026-10-09T00:00:00Z
LOGIN = '3000082754'
TOKEN = 'Tk' + 'a1B2c3D4e5' * 7                       # 72 characters of the EA's safe alphabet
HEADER = news.HEADER


def csv_text(rows):
    return HEADER + '\r\n' + ''.join(row + '\r\n' for row in rows)


ROWS = ['2023.01.03 13:30:00,USD,90,ISM Manufacturing PMI,48.40,48.50,49.00,1,',
        '2026.10.02 12:30:00,USD,97,Nonfarm Payrolls,254.00,140.00,159.00,1,',
        '2026.10.07 08:55:00,EUR,85,German Factory Orders,0.20,0.10,-1.80,1,']


def response(rows=ROWS, *, min_impact=85, complete=True, **overrides):
    text = csv_text(rows)
    data = news.BOM + text.encode('utf-16-le')
    value = dict(schema=news.SCHEMA, minImpact=min_impact,
                 tier=dict(requested=min_impact, historyWriteFloor=85, complete=complete), warnings=[],
                 source='calendar_history', range=dict(fromUtc='2023-01-01T00:00:00.000Z', toUtc='2026-10-08T20:00:00.000Z',
                                                       latestReleasedUtc='2026-10-07T08:55:00.000Z'),
                 coverage=dict(firstUtc='2023-01-03T13:30:00.000Z', lastUtc='2026-10-07T08:55:00.000Z', rows=len(rows)),
                 monthlyCounts={'2023-01': 1}, excluded=dict(invalid=0, outsideRange=0, afterLatestRelease=2, belowTier=0, duplicate=0),
                 format=dict(fileName='GOAT_News.csv', columns=HEADER.split(','), time='YYYY.MM.DD HH:MM:SS UTC', delimiter=',',
                             lineEnding='CRLF', mt5FileEncoding='UTF-16LE with BOM'),
                 sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(), mt5FileSha256=hashlib.sha256(data).hexdigest(),
                 csv=text, generatedAt='2026-10-08T20:00:01.000Z', license=dict(accountId=LOGIN))
    value.update(overrides)
    return value


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self.body if limit is None or limit < 0 else self.body[:limit]


class FakeOpener:
    """Records the one request; answers with a body, or raises the given error."""
    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return FakeResponse(json.dumps(self.answer).encode('utf-8') if isinstance(self.answer, dict) else self.answer)


def http_error(code, body):
    return urllib.error.HTTPError(news.API_BASE + news.ENDPOINT, code, 'refused', {}, BytesIO(json.dumps(body).encode('utf-8')))


SERVICES = dict(ProcessId=900, ParentProcessId=4, Name='services.exe', ExecutablePath=None)


class Fixture(unittest.TestCase):
    """A demo_direct V1.49 installation in a suite folder, with its per-login credential in Common Files."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.suite = base / 'suite'; self.root = self.suite / 'own'
        self.data = base / 'data'; self.common = base / 'common'
        for folder in (self.root, self.data / 'MQL5/Experts/GOAT-EA', self.common / 'GOAT/Credentials'):
            folder.mkdir(parents=True)
        self.exe = base / 'bin/terminal64.exe'; self.exe.parent.mkdir(); self.exe.write_bytes(b'fake')
        binary = self.data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'; binary.write_bytes(b'ea-149')
        self.install = dict(schema_version=1, controller_version='1.49-beta.1', ea_version='1.49',
                            ea_sha256=hashlib.sha256(b'ea-149').hexdigest(), controller_state_root=str(self.root),
                            terminal_data_root=str(self.data), common_files_root=str(self.common),
                            terminal_executable=str(self.exe), ea_relative_path=r'GOAT-EA\GOAT V1.49.ex5',
                            credential_relative_path=r'GOAT\Credentials\api-bearer-v149.token')
        self.installation = self.root / 'installation.json'
        self.installation.write_text(json.dumps(self.install), encoding='utf-8')
        from studio_installation import load_installation
        self.install = load_installation(self.installation)
        self.binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        (self.root / 'session.json').write_text(json.dumps(dict(directory_id='session-one', terminal_id='terminal-one',
            run_id='session-one', demo_only=True, account=dict(login=LOGIN, server='Darwinex-Demo'),
            authority_kind='demo_direct', installation_sha256=sha(self.install))), encoding='utf-8')
        self.jobs([])
        self.credential = self.common / ('GOAT/Credentials/api-bearer-v149-' + LOGIN + '.token')
        self.credential.write_bytes(TOKEN.encode('ascii'))
        self.target = self.common / 'GOAT/GOAT_News.csv'
        self.old = news.BOM + csv_text(ROWS[:1]).encode('utf-16-le')
        self.target.write_bytes(self.old)
        self.processes = [SERVICES, dict(ProcessId=901, ParentProcessId=900, Name='metatester64.exe', ExecutablePath=None)]

    def jobs(self, jobs, root=None):
        with closing(sqlite3.connect((root or self.root) / 'studio.sqlite', isolation_level=None)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS studio_queues (binding TEXT PRIMARY KEY, jobs TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_state (binding TEXT PRIMARY KEY, owner TEXT, generation INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS studio_authorities (binding TEXT PRIMARY KEY, kind TEXT, provenance TEXT)')
            db.execute('INSERT OR REPLACE INTO studio_queues VALUES (?, ?)', (self.binding, json.dumps(jobs)))
            db.execute('INSERT OR REPLACE INTO studio_state VALUES (?, ?, ?)', (self.binding, 'agent', 1))

    def runner(self, kind, batch_id, status, root=None):
        folder = (root or self.root) / news_folder(kind) / batch_id
        folder.mkdir(parents=True)
        tester = dict(Symbol='EURUSD', Period='M1')
        (folder / 'state.json').write_text(json.dumps(dict(batch_id=batch_id, status=status,
            members=[dict(status='running' if status == 'active' else 'pending')])), encoding='utf-8')
        (folder / 'manifest.json').write_text(json.dumps(dict(batch_id=batch_id, members=[dict(tester=tester)])), encoding='utf-8')

    def sync(self, answer, **kwargs):
        opener = FakeOpener(answer)
        with patch('studio_news_history._opener', return_value=opener):
            result = news.sync(self.install, now=NOW, processes=kwargs.pop('processes', self.processes), **kwargs)
        return result, opener

    def files(self):
        return {p.name: p.read_bytes() for p in (self.common / 'GOAT').iterdir() if p.is_file()}


def news_folder(kind):
    return dict(seed='seeds', catchup='catchups', holdup='holdups')[kind]


class SyncTests(Fixture):
    def test_writes_utf16_with_bom_verified_against_the_server_hash_and_keeps_the_previous_file(self):
        value = response()
        result, opener = self.sync(value)
        data = self.target.read_bytes()
        self.assertTrue(data.startswith(b'\xff\xfe'))
        self.assertEqual(data[2:].decode('utf-16-le'), value['csv'])
        self.assertEqual(hashlib.sha256(data).hexdigest(), value['mt5FileSha256'])
        self.assertEqual({key: result[key] for key in ('rows', 'firstRelease', 'lastRelease', 'sha256', 'minImpact',
                                                       'tierComplete', 'path', 'backupPath')},
                         dict(rows=3, firstRelease='2023-01-03T13:30:00Z', lastRelease='2026-10-07T08:55:00Z',
                              sha256=value['mt5FileSha256'], minImpact=85, tierComplete=True, path=str(self.target),
                              backupPath=str(self.target.with_name('GOAT_News.csv.bak'))))
        self.assertEqual(self.target.with_name('GOAT_News.csv.bak').read_bytes(), self.old)
        self.assertEqual((result['changed'], result['previousSha256']), (True, hashlib.sha256(self.old).hexdigest()))
        self.assertEqual(sorted(self.files()), ['GOAT_News.csv', 'GOAT_News.csv.bak'])     # no temporary file left
        # The request: the endpoint, the parameters and the account id; the credential only in its header.
        request = opener.requests[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, news.API_BASE + news.ENDPOINT + '?minImpact=85&from=2023-01-01&id=' + LOGIN)
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
        # The receipt: the result plus the request, under the controller state.
        receipt = json.loads(Path(result['receiptPath']).read_text(encoding='utf-8'))
        self.assertEqual(Path(result['receiptPath']).parent, self.root / 'news-history')
        self.assertEqual((receipt['schema'], receipt['sha256'], receipt['request']['from'], receipt['request']['to'],
                          receipt['request']['minImpact'], receipt['accountId'], receipt['monthlyCounts']),
                         (news.RECEIPT_SCHEMA, value['mt5FileSha256'], '2023-01-01', None, 85, LOGIN, {'2023-01': 1}))
        self.assertEqual(receipt['serviceAgentsIgnored'], 1)

    def test_parameters_reach_the_query_and_the_reply(self):
        result, opener = self.sync(response(ROWS[:2], min_impact=90, complete=False, warnings=['tier below floor']),
                                  min_impact=90, from_date='2024-01-01', to_date='2026-10-02T21:00:00Z')
        self.assertIn('minImpact=90&from=2024-01-01&to=2026-10-02T21%3A00%3A00Z&id=' + LOGIN, opener.requests[0].full_url)
        self.assertEqual((result['minImpact'], result['tierComplete'], result['warnings']), (90, False, ['tier below floor']))
        for bad in (dict(min_impact=69), dict(min_impact=101), dict(from_date='2023/01/01'), dict(to_date='2026-13-01')):
            with self.subTest(bad), self.assertRaises(Refusal) as caught:
                self.sync(response(), **bad)
            self.assertEqual(caught.exception.code, 'NEWS_HISTORY_PARAMS_INVALID')

    def test_second_sync_keeps_bak_and_uses_a_stamped_backup_and_an_identical_file_is_left_alone(self):
        first, _ = self.sync(response())
        second, _ = self.sync(response(ROWS[:2]))
        self.assertEqual(Path(second['backupPath']).name, 'GOAT_News.csv.20261009T000000Z.bak')
        self.assertEqual(Path(second['backupPath']).read_bytes(), news.BOM + csv_text(ROWS).encode('utf-16-le'))
        self.assertEqual(self.target.with_name('GOAT_News.csv.bak').read_bytes(), self.old)   # never replaced
        before = self.files()
        third, _ = self.sync(response(ROWS[:2]))
        self.assertEqual((third['changed'], third['backupPath']), (False, None))
        self.assertEqual(self.files(), before)
        self.assertEqual(len(list((self.root / 'news-history').glob('*.json'))), 3)

    def test_first_file_has_no_backup(self):
        self.target.unlink()
        result, _ = self.sync(response())
        self.assertIsNone(result['backupPath'])
        self.assertEqual(sorted(self.files()), ['GOAT_News.csv'])

    def test_hash_mismatches_and_bad_responses_write_nothing(self):
        good = response()
        cases = dict(file_sha=dict(mt5FileSha256='0' * 64), text_sha=dict(sha256='0' * 64), schema=dict(schema='other'),
                     impact=dict(minImpact=70), name=dict(format=dict(fileName='other.csv')), tier=dict(tier={}),
                     rows=dict(coverage=dict(rows=99)))
        for label, change in cases.items():
            with self.subTest(label), self.assertRaises(Refusal) as caught:
                self.sync(dict(good, **change))
            self.assertIn(caught.exception.code, ('NEWS_HISTORY_SHA_MISMATCH', 'NEWS_HISTORY_RESPONSE_INVALID'))
            self.assertEqual(self.files(), {'GOAT_News.csv': self.old})
        below = response(ROWS + ['2026.10.07 09:00:00,GBP,70,Low impact,0.00,0.00,0.00,1,'])
        with self.assertRaisesRegex(Refusal, 'row 4'):
            self.sync(below)
        with self.assertRaisesRegex(Refusal, 'no news rows'):
            self.sync(response([]))
        self.assertEqual(self.files(), {'GOAT_News.csv': self.old})

    def test_temporary_file_that_reads_back_wrong_is_removed_and_the_target_is_unchanged(self):
        real = news._fsync_write
        def corrupt(path, data):
            real(path, data[:-2] if path.name.endswith('.news-sync-tmp') else data)
        with patch('studio_news_history._fsync_write', side_effect=corrupt), self.assertRaises(Refusal) as caught:
            self.sync(response())
        self.assertEqual(caught.exception.code, 'NEWS_HISTORY_SHA_MISMATCH')
        self.assertEqual(self.files(), {'GOAT_News.csv': self.old})

    def test_a_failed_rename_keeps_the_old_file_and_removes_only_its_own_temporary_and_backup(self):
        with patch('studio_news_history.os.replace', side_effect=PermissionError(13, 'in use')), \
                self.assertRaises(Refusal) as caught:
            self.sync(response())
        self.assertEqual(caught.exception.code, 'NEWS_HISTORY_TESTER_BUSY')
        self.assertEqual(self.files(), {'GOAT_News.csv': self.old})

    def test_backup_copies_when_a_hard_link_is_not_possible(self):
        with patch('studio_news_history.os.link', side_effect=OSError('no links here')):
            result, _ = self.sync(response())
        self.assertEqual(Path(result['backupPath']).read_bytes(), self.old)


class ReaderTests(Fixture):
    def assert_busy(self, pattern, **kwargs):
        with self.assertRaisesRegex(Refusal, pattern) as caught:
            self.sync(response(), **kwargs)
        self.assertEqual(caught.exception.code, 'NEWS_HISTORY_TESTER_BUSY')
        self.assertEqual(self.files(), {'GOAT_News.csv': self.old})
        return caught.exception

    def test_running_or_pausing_batch_refuses_before_any_request(self):
        for status in ('running', 'starting', 'reserved'):
            self.jobs([dict(job_id='banker-g17', status=status, configuration={})])
            with patch('studio_news_history.fetch') as fetch:
                refusal = self.assert_busy('batch \\(banker-g17, running\\)')
            fetch.assert_not_called()
            self.assertEqual(refusal.fields['busy'][0]['batch_id'], 'banker-g17')

    def test_finished_or_queued_batches_do_not_refuse_and_unfinished_ones_are_reported(self):
        self.jobs([dict(job_id='done', status='completed', configuration={}),
                   dict(job_id='later', status='pending', configuration={})])
        result, _ = self.sync(response())
        self.assertEqual([(row['batch_id'], row['state']) for row in result['unfinishedRuns']], [('later', 'queued')])

    def test_active_seed_catchup_or_holdup_and_a_held_slot_refuse(self):
        for kind in news.RUNNER_KINDS:
            with self.subTest(kind):
                self.runner(kind, kind + '-run', 'active')
                self.assert_busy(kind + ' \\(' + kind + '-run, running\\)')
                import shutil; shutil.rmtree(self.root / news_folder(kind))
        (self.root / 'seed-active.json').write_text(json.dumps(dict(batch_id='e1', status='held')), encoding='utf-8')
        self.assert_busy('terminal slot \\(e1, held\\)')
        (self.root / 'seed-active.json').write_text(json.dumps(dict(batch_id='e1', status='released')), encoding='utf-8')
        self.sync(response())

    def test_another_installation_sharing_common_files_refuses_one_with_other_common_files_does_not(self):
        other = self.suite / 'banker'; other.mkdir()
        (other / 'installation.json').write_text(json.dumps(dict(self.install, controller_state_root=str(other))), encoding='utf-8')
        self.runner('seed', 'g18', 'active', root=other)
        self.assert_busy(re.escape('seed (g18, running) in ' + str(other)))
        (other / 'installation.json').write_text('{not json', encoding='utf-8')
        self.assert_busy('could not read every research run')
        (other / 'installation.json').write_text(json.dumps(dict(self.install, controller_state_root=str(other),
                                                                 common_files_root=str(self.data))), encoding='utf-8')
        self.sync(response())                                    # another Common Files folder: not this file

    def test_unreadable_queue_or_run_fails_closed(self):
        broken = self.root / 'seeds/half'; broken.mkdir(parents=True)
        (broken / 'state.json').write_text('{"status": "act', encoding='utf-8')
        self.assert_busy('could not read every research run')

    def test_terminal_tester_agents_refuse_service_agents_do_not(self):
        terminal = dict(ProcessId=50, ParentProcessId=1, Name='terminal64.exe', ExecutablePath='G:\\T1\\terminal64.exe')
        local = dict(ProcessId=51, ParentProcessId=50, Name='metatester64.exe', ExecutablePath='G:\\T1\\metatester64.exe')
        refusal = self.assert_busy('1 MT5 tester agent is running \\(PID 51, started by MT5 G:\\\\T1\\\\terminal64.exe\\)',
                                   processes=self.processes + [terminal, local])
        self.assertEqual(refusal.fields['agents'][0]['parent'], 'terminal64.exe')
        orphan = dict(ProcessId=52, ParentProcessId=12345, Name='metatester64.exe', ExecutablePath=None)
        self.assert_busy('a parent GOAT cannot identify', processes=self.processes + [orphan])
        result, _ = self.sync(response(), processes=self.processes)        # only Windows-service agents
        self.assertTrue(result['changed'])

    def test_readers_are_checked_again_right_before_the_rename(self):
        calls = []
        real = news.check_readers
        def appears(install, *, now, processes=None):
            calls.append(now)
            if len(calls) == 2:
                raise Refusal('A batch started meanwhile', 'NEWS_HISTORY_TESTER_BUSY')
            return real(install, now=now, processes=processes)
        with patch('studio_news_history.check_readers', side_effect=appears), self.assertRaisesRegex(Refusal, 'started meanwhile'):
            self.sync(response())
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.files(), {'GOAT_News.csv': self.old})

    def test_process_inventory_command_filters_agents_terminals_and_services(self):
        with patch('studio_process_query.process_rows', return_value=[]) as rows:
            self.assertEqual(news.process_inventory(), [])
        command = rows.call_args.args[0]
        for name in news.INVENTORY_NAMES:
            self.assertIn("Name='" + name + "'", command)
        self.assertEqual(rows.call_args.kwargs['fields'], news.INVENTORY_FIELDS)


class CredentialTests(Fixture):
    def test_per_login_credential_is_the_one_used(self):
        self.assertEqual(news.credential_file(self.install, LOGIN), self.credential)
        legacy = dict(self.install, ea_version='1.48', credential_relative_path=r'GOAT\Credentials\api-bearer-v148.token')
        self.assertEqual(news.credential_file(legacy, LOGIN), self.common / 'GOAT/Credentials/api-bearer-v148.token')
        for path in (None, '', r'GOAT\Other\api-bearer.token', r'..\api-bearer.token'):
            with self.subTest(path), self.assertRaises(ValueError):
                news.credential_file(dict(self.install, credential_relative_path=path), LOGIN)

    def test_missing_or_invalid_credential_refuses_before_any_request(self):
        for content in (None, b'short', TOKEN.encode() + b'\r\nsecond', (TOKEN[:-1] + '!').encode(), b'x' * 2000):
            with self.subTest(content=content and content[:8]):
                if content is None:
                    self.credential.unlink()
                else:
                    self.credential.write_bytes(content)
                with patch('studio_news_history.fetch') as fetch, self.assertRaises(Refusal) as caught:
                    self.sync(response())
                fetch.assert_not_called()
                self.assertEqual(caught.exception.code, 'NEWS_HISTORY_CREDENTIAL_MISSING')
        self.credential.write_bytes(TOKEN.encode() + b'\r\n')     # one trailing line break is what a text editor adds
        self.sync(response())

    def test_redirect_is_never_followed(self):
        class Redirecting(urllib.request.BaseHandler):
            handler_order = 100
            seen = []
            def https_open(self, request):
                self.seen.append((request.full_url, request.get_header('Authorization')))
                from email.message import Message
                headers = Message(); headers['Location'] = 'https://elsewhere.example/steal'
                reply = urllib.response.addinfourl(BytesIO(b''), headers, request.full_url, 302)
                reply.msg = 'Found'
                return reply
        opener = urllib.request.build_opener(news._NoRedirect(), Redirecting())
        with patch('studio_news_history._opener', return_value=opener), self.assertRaises(Refusal) as caught:
            news.fetch(news.API_BASE + news.ENDPOINT + '?minImpact=85', TOKEN)
        self.assertEqual((caught.exception.code, caught.exception.fields['http_status']), ('NEWS_HISTORY_HTTP_ERROR', 302))
        self.assertEqual([url for url, _ in Redirecting.seen], [news.API_BASE + news.ENDPOINT + '?minImpact=85'])
        self.assertNotIn(TOKEN, str(caught.exception))
        with self.assertRaisesRegex(Refusal, 'HTTPS'):
            news.fetch('http://goatedge.ai/api/ea/news-history', TOKEN)


class CliTests(Fixture):
    """The whole controller CLI: the credential never reaches stdout, stderr, the reply or any file."""
    def cli(self, answer, *argv):
        out, err, opener = StringIO(), StringIO(), FakeOpener(answer)
        from goat_studio import main
        with patch('studio_news_history._opener', return_value=opener), \
                patch('studio_news_history.process_inventory', return_value=self.processes), \
                redirect_stdout(out), redirect_stderr(err):
            code = main(['--installation', str(self.installation), 'news-history-sync', *argv])
        return code, out.getvalue(), err.getvalue(), opener

    def assert_never_written(self, *texts):
        for text in texts:
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(TOKEN[:24], text)
        for folder in (self.root, self.common, self.data):
            for path in Path(folder).rglob('*'):
                if path.is_file() and path != self.credential:
                    raw = path.read_bytes()
                    for encoded in (TOKEN.encode('ascii'), TOKEN.encode('utf-16-le')):
                        self.assertNotIn(encoded, raw, str(path))

    def test_success_prints_one_json_line_without_the_credential(self):
        value = response()
        code, out, err, opener = self.cli(value, '--min-impact', '85', '--from', '2023-01-01')
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        reply = json.loads(out)
        self.assertTrue(reply['ok'])
        for key in ('rows', 'firstRelease', 'lastRelease', 'sha256', 'minImpact', 'tierComplete', 'path', 'backupPath'):
            self.assertIn(key, reply['result'])
        self.assertEqual(reply['result']['sha256'], value['mt5FileSha256'])
        self.assertNotIn(TOKEN, opener.requests[0].full_url)
        self.assert_never_written(out, err)

    def test_every_failure_path_keeps_the_credential_out_of_stdout_stderr_and_files(self):
        failures = dict(
            unauthorized=http_error(401, dict(code='EA_AUTH_INVALID', message='Bearer ' + TOKEN + ' is not valid', token=TOKEN)),
            forbidden=http_error(403, dict(code='EA_NOT_ENTITLED', error='no entitlement for ' + TOKEN)),
            server=http_error(500, dict(message='crash with Authorization: Bearer ' + TOKEN)),
            redirect=http_error(302, dict(message=TOKEN)),
            unreachable=urllib.error.URLError('proxy said ' + TOKEN),
            timeout=TimeoutError('timed out after header Bearer ' + TOKEN),
            unexpected=RuntimeError('boom ' + TOKEN),
            not_json=b'<html>' + TOKEN.encode() + b'</html>',
            bad_hash=response(mt5FileSha256='0' * 64))
        for label, answer in failures.items():
            with self.subTest(label):
                code, out, err, opener = self.cli(answer)
                self.assertEqual(code, 2, out)
                reply = json.loads(out)
                self.assertFalse(reply['ok'])
                self.assertTrue(reply['refusal_code'].startswith('NEWS_HISTORY_'), reply)
                self.assert_never_written(out, err)
                self.assertNotIn(TOKEN, opener.requests[0].full_url)
                self.assertEqual(self.target.read_bytes(), self.old)
        self.assertIn('HTTP 401', json.loads(self.cli(failures['unauthorized'])[1])['error'])

    def test_busy_tester_refuses_through_the_cli_without_a_request(self):
        self.jobs([dict(job_id='banker-g17', status='running', configuration={})])
        code, out, err, opener = self.cli(response())
        reply = json.loads(out)
        self.assertEqual((code, reply['refusal_code']), (2, 'NEWS_HISTORY_TESTER_BUSY'))
        self.assertEqual(opener.requests, [])
        self.assert_never_written(out, err)

    def test_contract_and_local_file_classification(self):
        from goat_studio import OPERATION_CONTRACTS
        from studio_research_authority import LOCAL_FILE_OPERATIONS, OPERATIONS, READ_OPERATIONS
        contract = OPERATION_CONTRACTS['news-history-sync']
        self.assertEqual((contract['required'], contract['optional'], contract['defaults'], contract['limits']),
                         ([], ['min-impact', 'from', 'to'], {'min-impact': 85, 'from': '2023-01-01'}, {'min-impact': [70, 100]}))
        for phrase in ('never printed, logged, written or put in a URL', 'no force flag', 'mt5FileSha256', '.bak',
                       'Never opens the store or MT5'):
            self.assertIn(phrase, contract['effect'])
        self.assertTrue({'news-history-sync'} <= LOCAL_FILE_OPERATIONS <= READ_OPERATIONS <= OPERATIONS)


DEMO_REFUSAL = 'Demo mutation requires the broker-verified agent tool'
MIXED_REFUSAL = 'modules of another controller'
# Every launcher starts from an explicit sys.path: the interpreter's own library only (sys.base_prefix / sys.prefix),
# so no python313._pth entry, PYTHONPATH, user site or working folder can reach an installed GOAT controller. It then
# adds only the fixture folders the entrypoint needs and, at exit, writes every loaded module file to the audit file.
# argv: script, checkout controller, fixture "installed" controller, audit file, then the CLI arguments.
PRELUDE = (
    'import atexit, json, os, sys\n'
    'script, checkout, installed, audit = sys.argv[1:5]\nargs = sys.argv[5:]\n'
    'def inside(path, root):\n'
    '    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))\n'
    '    try:\n        return os.path.commonpath([path, root]) == root\n'
    '    except ValueError:\n        return False\n'
    'roots = sorted({sys.base_prefix, sys.prefix})\n'
    'sys.path[:] = [p for p in sys.path if p and any(inside(p, r) for r in roots)]\n'
    'def report():\n'
    '    files = sorted({f for f in (getattr(m, "__file__", None) for m in list(sys.modules.values())) if isinstance(f, str)})\n'
    '    with open(audit, "w", encoding="utf-8") as stream:\n'
    '        json.dump(dict(roots=roots, files=files), stream)\n'
    'atexit.register(report)\n')
RUN_SCRIPT = 'import runpy\nsys.argv = [script] + args\nrunpy.run_path(script, run_name="__main__")\n'
CALL_MAIN = 'sys.path.insert(0, checkout)\nimport goat_studio\nsys.exit(goat_studio.main(args))\n'
LAUNCHERS = dict(
    # How an interpreter with safe_path runs a script: the script folder is never on sys.path, nothing installed.
    safe_path=PRELUDE + RUN_SCRIPT,
    # The bundled GOAT Python on Banker 2026-10-09: python313._pth lists the installed controller (here an older one)
    # and never the script folder. runpy.run_path never adds the script folder either.
    embedded=PRELUDE + 'sys.path.append(installed)\n' + RUN_SCRIPT,
    # The wrapper that succeeded on Banker: the checkout inserted first, then runpy.
    runpy=PRELUDE + 'sys.path.append(installed)\nsys.path.insert(0, checkout)\n' + RUN_SCRIPT,
    # A caller that imports goat_studio and calls main().
    imported=PRELUDE + 'sys.path.append(installed)\n' + CALL_MAIN,
    # A caller that imported the older controller's authority first, then this goat_studio: two revisions in one process.
    mixed=PRELUDE + 'sys.path.append(installed)\nimport studio_research_authority\n' + CALL_MAIN)
ENTRYPOINTS = ('plain', 'safe_path', 'embedded', 'runpy', 'imported')


def embedded_interpreter():
    """The bundled GOAT Python: a ._pth file beside it fixes sys.path, so a plain run cannot be isolated from its install."""
    import sys
    return any(Path(sys.executable).parent.glob('*._pth'))


class EntrypointTests(Fixture):
    """Banker 2026-10-09 (Claude-Mac P1, goatai#2350 6073065632): the checkout's goat_studio.py run with the bundled GOAT
    Python refused news-history-sync with "Demo mutation requires the broker-verified agent tool"; the same arguments
    through a wrapper that put the checkout first on sys.path succeeded.

    Root cause: that Python's python313._pth sets safe_path and lists ../controller, so the script's own folder was
    never on sys.path. The checkout's goat_studio.py dispatched news-history-sync, but studio_research_authority (and
    every other module) came from the INSTALLED controller, whose LOCAL_FILE_OPERATIONS predates news-history-sync, so
    its default-deny demo_direct branch refused it. authority() itself never depended on the entrypoint; the process
    ran two controller revisions. goat_studio.py now puts its own folder first and refuses to run with another
    folder's controller modules, so every entrypoint resolves the same classification and authority.

    Hermetic: the "installed" controller is a complete copy of this controller in the test's temp folder, with an
    older studio_research_authority. Every entrypoint runs in a fresh, isolated process (-I) whose sys.path holds only
    the interpreter's own library plus these folders, and every module it loaded is audited: none comes from anywhere
    else, and only the mixed process loads anything from the "installed" copy."""
    HERE = Path(__file__).resolve().parent

    def installed_controller(self):
        """A complete installed controller (every module and contract) whose authority predates news-history-sync."""
        import shutil
        folder = Path(self.temp.name) / 'installed controller'
        if not folder.is_dir():
            shutil.copytree(self.HERE, folder, ignore=shutil.ignore_patterns(
                '__pycache__', 'test_*.py', 'fixtures', 'skills', 'tests', '*.md'))
            path = folder / 'studio_research_authority.py'
            source = path.read_text(encoding='utf-8')
            older = source.replace(", 'news-history-sync'))", '))', 1)
            self.assertNotEqual(older, source)
            path.write_text(older, encoding='utf-8')
        return folder

    def run_entry(self, entry, *argv):
        import subprocess, sys
        script = str(self.HERE / 'goat_studio.py')
        cli = ['--installation', str(self.installation), *argv]
        audit = Path(self.temp.name) / ('audit-' + entry + '.json')
        if audit.exists():
            audit.unlink()
        installed = self.installed_controller()
        if entry == 'plain':
            # -I: no script folder (safe path), no PYTHONPATH, no user site; only on an interpreter without a ._pth.
            command = [sys.executable, '-I', script, *cli]
        else:
            command = [sys.executable, '-I', '-c', LAUNCHERS[entry], script, str(self.HERE), str(installed), str(audit), *cli]
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PYTHON')}
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, cwd=self.temp.name,
                                   env=dict(env, PYTHONDONTWRITEBYTECODE='1'))
        lines = completed.stdout.strip().splitlines()
        self.assertTrue(lines, (entry, completed.stderr[-2000:]))
        if entry != 'plain':
            self.assert_hermetic(entry, json.loads(audit.read_text(encoding='utf-8')), installed)
        return completed.returncode, json.loads(lines[-1])

    def assert_hermetic(self, entry, audit, installed):
        """Every loaded module is the interpreter's own library, this checkout or the fixture's installed copy."""
        def inside(path, root):
            path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
            try:
                return os.path.commonpath([path, root]) == root
            except ValueError:
                return False
        allowed = audit['roots'] + [str(self.HERE), str(installed)]
        stray = [f for f in audit['files'] if not any(inside(f, root) for root in allowed)]
        self.assertEqual(stray, [], entry)
        from_installed = sorted(Path(f).name for f in audit['files'] if inside(f, installed))
        if entry == 'mixed':
            # The other revision really was loaded (the authority and its own imports), and goat_studio refused it.
            self.assertIn('studio_research_authority.py', from_installed)
            self.assertNotIn('goat_studio.py', from_installed)
        else:
            self.assertEqual(from_installed, [], entry)        # one revision: the checkout's

    def entrypoints(self):
        return [entry for entry in ENTRYPOINTS if entry != 'plain' or not embedded_interpreter()]
    def test_news_history_sync_is_allowed_on_demo_direct_on_every_entrypoint(self):
        # --min-impact 101 refuses inside news-history-sync itself, before any process inventory, credential or request:
        # reaching it proves the authority allowed the operation.
        for entry in self.entrypoints():
            with self.subTest(entry=entry):
                code, reply = self.run_entry(entry, 'news-history-sync', '--min-impact', '101')
                self.assertEqual((code, reply.get('refusal_code')), (2, 'NEWS_HISTORY_PARAMS_INVALID'), reply)
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_a_real_mutation_still_refuses_on_every_entrypoint(self):
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text('{}', encoding='utf-8')
        for entry in self.entrypoints():
            for argv in (('prepare-batch', '--batch-id', 'demo-batch', '--plan', str(plan)),
                         ('peer-add', '--terminal', str(self.exe), '--confirm-reviewed')):
                with self.subTest(entry=entry, operation=argv[0]):
                    code, reply = self.run_entry(entry, *argv)
                    self.assertEqual((code, reply['error']), (2, DEMO_REFUSAL), reply)
        self.assertNotIn('demo-batch', (self.root / 'studio.sqlite').read_bytes().decode('latin-1'))

    def test_a_process_holding_another_controller_revision_runs_nothing(self):
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text('{}', encoding='utf-8')
        for argv in (('news-history-sync', '--min-impact', '101'), ('prepare-batch', '--batch-id', 'demo-batch', '--plan', str(plan))):
            with self.subTest(operation=argv[0]):
                code, reply = self.run_entry('mixed', *argv)
                self.assertEqual(code, 2, reply)
                self.assertIn(MIXED_REFUSAL, reply['error'])
                self.assertNotIn('refusal_code', reply)

    def test_the_operation_is_classified_as_a_local_file_operation(self):
        from studio_research_authority import LOCAL_FILE_OPERATIONS, READ_OPERATIONS, authority, operation
        self.assertIn('news-history-sync', LOCAL_FILE_OPERATIONS)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'studio.sqlite')) as db:
            with operation('news-history-sync'):
                self.assertIsNone(authority(db, self.binding, dict(owner='agent', generation=1)))
            for name in ('prepare-batch', 'run-batch', 'peer-add', 'seed-start', 'catchup-prepare'):
                with operation(name), self.assertRaisesRegex(ValueError, DEMO_REFUSAL):
                    authority(db, self.binding, dict(owner='agent', generation=1))

if __name__ == '__main__':
    unittest.main()
