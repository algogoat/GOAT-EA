"""news-history-sync: refresh the Strategy Tester's news file from the GOAT server (goatai#2350).

Backtests with ``Mode_News`` on read ``Common\\Files\\GOAT\\GOAT_News.csv`` (``LoadBacktestFileAndFillNews`` in
NewsBiasFilter.mqh). This command replaces that file with the server's ``/api/ea/news-history`` export
(goatai docs/EA_WIRE_CONTRACT.md, "News history for the Strategy Tester"):

* **Auth** is the calendar feed's EA authentication, exactly as the EA sends it to ``/api/ea/calendar``
  (``GOATBuildAuthenticatedRequestHeaders`` in GOAT_Inputs_Definitions.mqh): ``Authorization: Bearer
  <credential>`` plus ``id=<MT5 login>``. The credential is the one the installed EA stored for this
  installation's account (``credential_relative_path`` in the receipt; per login on V1.49, see
  ``studio_terminal_isolation.credential_relative_path``), validated as the EA validates it. It is sent only
  in that header, only over HTTPS to ``URL_API``, and never follows a redirect (urllib would copy the header
  to the new host). It is never printed, logged, written to a file or put in a URL, and every error sentence
  this module raises is scrubbed of it.
* **The write** is UTF-16LE with a BOM (the EA's ``FILE_UNICODE`` encoding). The bytes must hash to the
  response's ``mt5FileSha256`` before anything is written and again after the temporary file is written and
  read back. The temporary file sits in the same folder and is renamed over the target; the previous file
  is kept as ``GOAT_News.csv.bak`` (or ``GOAT_News.csv.<UTC stamp>.bak`` when that exists) and is never
  deleted. An identical file is left alone.
* **Refusal while a tester may read the file.** The file is shared by every terminal on this Windows user,
  so the command refuses while any GOAT installation that shares this Common Files folder has a running or
  pausing batch, seed hunt, catch-up or hold-up test, or a held seed/catch-up terminal slot, and while any
  ``metatester64.exe`` that is not a Windows-service agent is running (a terminal's local agents, or an agent
  whose parent cannot be identified). Service agents (MetaTester-N services, children of services.exe) run
  in their own sandbox and never read this user's Common Files; they are counted, not refused. The check
  runs before the download and again right before the rename. There is no force flag.
* **A receipt** under ``<controller state>\\news-history\\`` records the file sha and the request, so every
  sweep can name the news file it used. Files from before goatai#2363/#2364 (2026-10-08 history cleanup
  and rescoring) are not comparable with later ones.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from studio_installation import read_json
from studio_refusal import Refusal

API_BASE = 'https://goatedge.ai'            # URL_API in GOAT_Inputs_Definitions.mqh
ENDPOINT = '/api/ea/news-history'
SCHEMA = 'goat-news-history-v1'
RECEIPT_SCHEMA = 'goat-news-history-sync-v1'
RECEIPT_FOLDER = 'news-history'
FILE_NAME = 'GOAT_News.csv'                  # NEWS_FILE = Key+"\\GOAT_News.csv", read with FILE_COMMON
HEADER = 'Time,Currency,ImpactScore,Name,Actual,Forecast,Previous,Outcome,Description'
BOM = b'\xff\xfe'
DEFAULT_MIN_IMPACT = 85
DEFAULT_FROM = '2023-01-01'
MIN_IMPACT_LIMITS = (70, 100)                # the server's accepted range
TIMEOUT = 120
MAX_RESPONSE_BYTES = 32 * 1024 * 1024        # 20,000 rows (the server's cap) are about 2 MB of CSV
TOKEN = re.compile(r'[A-Za-z0-9._~-]{64,512}')   # GOATIsSafeApiBearerToken
TOKEN_FILE_BYTES = (64, 1024)                # GOATBuildAuthenticatedRequestHeaders size bounds
ROW_TIME = re.compile(r'(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
INSTANT = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?')
AGENT_NAMES = frozenset(('metatester64.exe', 'metatester.exe'))
SERVICE_PARENT = 'services.exe'
INVENTORY_NAMES = ('metatester64.exe', 'metatester.exe', 'terminal64.exe', 'terminal.exe', SERVICE_PARENT)
INVENTORY_FIELDS = ('ProcessId', 'ParentProcessId', 'Name', 'ExecutablePath')
BUSY_STATES = frozenset(('running', 'pausing'))
RUNNER_KINDS = ('seed', 'catchup', 'holdup')


def _scrub(text, secret):
    """The text with the credential (and any bearer value) removed."""
    text = str(text)
    if secret:
        text = text.replace(secret, '[credential]')
    return re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[credential]', text)


def _utc_stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ parameters

def request_params(min_impact=DEFAULT_MIN_IMPACT, from_date=DEFAULT_FROM, to_date=None):
    """The validated query parameters (the server re-validates; this refuses early and plainly)."""
    if type(min_impact) is not int or not MIN_IMPACT_LIMITS[0] <= min_impact <= MIN_IMPACT_LIMITS[1]:
        raise Refusal('--min-impact must be a whole number from 70 to 100.', 'NEWS_HISTORY_PARAMS_INVALID')
    params = {'minImpact': str(min_impact)}
    for flag, key, value in (('--from', 'from', from_date), ('--to', 'to', to_date)):
        if value is None:
            continue
        if not isinstance(value, str) or not (DAY.fullmatch(value) or INSTANT.fullmatch(value)):
            raise Refusal(flag + ' must be a UTC date such as 2023-01-01 or an ISO 8601 time such as 2026-10-02T21:00:00Z.',
                          'NEWS_HISTORY_PARAMS_INVALID')
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise Refusal(flag + ' is not a real date or time: ' + value, 'NEWS_HISTORY_PARAMS_INVALID') from None
        params[key] = value
    return params


# ------------------------------------------------------------------ credential

def credential_file(install, login):
    """Absolute path of the credential the installed EA uses for this account (never its contents)."""
    from studio_terminal_isolation import credential_relative_path, isolated, valid_login
    legacy = install.get('credential_relative_path')
    if not isinstance(legacy, str) or not legacy:
        raise Refusal('This installation receipt names no GOAT credential file, so the news history cannot be '
                      'requested; run GOAT Setup for this terminal again.', 'NEWS_HISTORY_CREDENTIAL_MISSING')
    login = valid_login(str(login))
    per_login = credential_relative_path(legacy, login)     # also validates GOAT/Credentials/api-bearer*.token
    # V1.49 (terminal isolation) reads GOAT\Credentials\<stem>-<login>.token; earlier builds the receipt's file.
    relative = per_login if isolated(install['ea_version']) else legacy
    return Path(install['common_files_root']).joinpath(*PureWindowsPath(relative).parts)


def load_credential(path):
    """The bearer credential, validated exactly as GOATBuildAuthenticatedRequestHeaders does."""
    refusal = ('The GOAT sign-in for this MT5 account is missing or invalid (' + str(path) + '). Approve the '
               'connection code on the GOAT chart of this terminal, then retry.')
    try:
        if path.is_symlink() or not path.is_file():
            raise Refusal(refusal, 'NEWS_HISTORY_CREDENTIAL_MISSING')
        raw = path.read_bytes()
    except OSError:
        raise Refusal(refusal, 'NEWS_HISTORY_CREDENTIAL_MISSING') from None
    if not TOKEN_FILE_BYTES[0] <= len(raw) <= TOKEN_FILE_BYTES[1]:
        raise Refusal(refusal, 'NEWS_HISTORY_CREDENTIAL_MISSING')
    try:
        lines = raw.decode('ascii').replace('\r\n', '\n').split('\n')
    except UnicodeError:
        raise Refusal(refusal, 'NEWS_HISTORY_CREDENTIAL_MISSING') from None
    token = lines[0]
    if any(line for line in lines[1:]) or not TOKEN.fullmatch(token):
        raise Refusal(refusal, 'NEWS_HISTORY_CREDENTIAL_MISSING')
    return token


# ------------------------------------------------------------------ transport

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error: urllib would resend the Authorization header to the new location."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect())


def request_url(params, login):
    """The request URL: the query and the account id only, never the credential."""
    query = dict(params, id=str(login))
    return API_BASE + ENDPOINT + '?' + urllib.parse.urlencode(query)


def fetch(url, token):
    """The decoded JSON body of one GET. Every failure is a Refusal whose sentence never holds the credential."""
    if not url.startswith('https://'):
        raise Refusal('The news history is only requested over HTTPS.', 'NEWS_HISTORY_TRANSPORT')
    request = urllib.request.Request(url, method='GET', headers={
        'Content-Type': 'application/json; charset=UTF-8', 'Accept': 'application/json',
        'Authorization': 'Bearer ' + token})
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            status = getattr(response, 'status', None) or response.getcode()
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            raw = error.read(64 * 1024)
            value = json.loads(raw.decode('utf-8'))
            if isinstance(value, dict):
                detail = ' '.join(str(value.get(k)) for k in ('code', 'message', 'error') if value.get(k))
        except Exception:     # an unreadable error body adds nothing
            detail = ''
        sentence = 'The GOAT server refused the news history request (HTTP ' + str(error.code) + ')' + (
            ': ' + detail[:300] if detail else '') + '. Nothing was written.'
        if error.code in (301, 302, 303, 307, 308):
            sentence = ('The GOAT server answered with a redirect (HTTP ' + str(error.code) + '); GOAT never follows '
                        'one with your sign-in attached. Nothing was written.')
        raise Refusal(_scrub(sentence, token), 'NEWS_HISTORY_HTTP_ERROR', http_status=error.code) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, 'reason', error)
        raise Refusal(_scrub('The GOAT server could not be reached for the news history (' + str(reason)[:200]
                             + '). Nothing was written.', token), 'NEWS_HISTORY_UNREACHABLE') from None
    if status != 200:
        raise Refusal('The GOAT server answered HTTP ' + str(status) + ' for the news history. Nothing was written.',
                      'NEWS_HISTORY_HTTP_ERROR', http_status=status)
    if len(body) > MAX_RESPONSE_BYTES:
        raise Refusal('The news history response is larger than ' + str(MAX_RESPONSE_BYTES) + ' bytes. Nothing was written.',
                      'NEWS_HISTORY_RESPONSE_INVALID')
    try:
        value = json.loads(body.decode('utf-8'))
    except (UnicodeError, ValueError):
        raise Refusal('The news history response is not JSON. Nothing was written.', 'NEWS_HISTORY_RESPONSE_INVALID') from None
    if not isinstance(value, dict):
        raise Refusal('The news history response is not a JSON object. Nothing was written.', 'NEWS_HISTORY_RESPONSE_INVALID')
    return value


# ------------------------------------------------------------------ response

def _invalid(sentence):
    return Refusal('The news history response is not usable: ' + sentence + ' Nothing was written.',
                   'NEWS_HISTORY_RESPONSE_INVALID')


def _iso(row_time):
    match = ROW_TIME.fullmatch(row_time)
    return '%s-%s-%sT%s:%s:%sZ' % match.groups()


def check_response(value, min_impact):
    """(file bytes, summary) from a verified response; refuses on any mismatch before anything is written."""
    csv, file_sha, text_sha = value.get('csv'), value.get('mt5FileSha256'), value.get('sha256')
    if value.get('schema') != SCHEMA:
        raise _invalid('schema is ' + repr(value.get('schema'))[:80] + ', not ' + SCHEMA + '.')
    if not isinstance(csv, str) or not all(isinstance(h, str) and re.fullmatch('[0-9a-f]{64}', h) for h in (file_sha, text_sha)):
        raise _invalid('csv, sha256 or mt5FileSha256 is missing.')
    if value.get('minImpact') != min_impact:
        raise _invalid('it is for minImpact ' + repr(value.get('minImpact'))[:20] + ', not ' + str(min_impact) + '.')
    file_name = (value.get('format') or {}).get('fileName') if isinstance(value.get('format'), dict) else None
    if file_name != FILE_NAME:
        raise _invalid('format.fileName is ' + repr(file_name)[:80] + ', not ' + FILE_NAME + '.')
    tier = value.get('tier')
    if not isinstance(tier, dict) or type(tier.get('complete')) is not bool:
        raise _invalid('tier.complete is missing.')
    if _sha256(csv.encode('utf-8')) != text_sha:
        raise _invalid('the csv text does not hash to its sha256.')
    data = BOM + csv.encode('utf-16-le')
    if _sha256(data) != file_sha:
        raise Refusal('The UTF-16LE file bytes do not hash to the server\'s mt5FileSha256, so the file was not written.',
                      'NEWS_HISTORY_SHA_MISMATCH')
    if not csv.startswith(HEADER + '\r\n') or not csv.endswith('\r\n'):
        raise _invalid('the csv does not start with the GOAT_News.csv header or does not end with CRLF.')
    rows = csv[len(HEADER) + 2:-2].split('\r\n') if len(csv) > len(HEADER) + 2 else []
    if not rows:
        raise _invalid('it holds no news rows.')
    for index, row in enumerate(rows):
        fields = row.split(',')
        if len(fields) != 9 or not ROW_TIME.fullmatch(fields[0]) or not re.fullmatch(r'\d{1,3}', fields[2]) \
                or int(fields[2]) < min_impact:
            raise _invalid('row ' + str(index + 1) + ' is not a GOAT_News.csv row at impact ' + str(min_impact) + ' or above.')
    coverage = value.get('coverage') if isinstance(value.get('coverage'), dict) else {}
    if coverage.get('rows') not in (None, len(rows)):
        raise _invalid('coverage.rows is ' + str(coverage.get('rows'))[:20] + ' but the csv holds ' + str(len(rows)) + ' rows.')
    warnings = value.get('warnings') if isinstance(value.get('warnings'), list) else []
    summary = dict(rows=len(rows), firstRelease=_iso(rows[0].split(',')[0]), lastRelease=_iso(rows[-1].split(',')[0]),
                   sha256=file_sha, csvSha256=text_sha, minImpact=min_impact, tierComplete=tier['complete'],
                   warnings=[str(w)[:300] for w in warnings][:20])
    return data, summary


# ------------------------------------------------------------------ readers

def process_inventory():
    """Read-only rows for tester agents, terminals and services.exe (WMI with the native fallback)."""
    from studio_process_query import process_rows
    filter_text = ' OR '.join("Name='" + name + "'" for name in INVENTORY_NAMES)
    command = ('ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "' + filter_text + '" '
               '| Select-Object ' + ','.join(INVENTORY_FIELDS) + ')')
    rows = process_rows(command, purpose='news-history tester agents', fields=INVENTORY_FIELDS, names=INVENTORY_NAMES)
    if not isinstance(rows, list):
        raise ValueError('Complete tester agent inventory required')
    return rows


def agent_readers(processes):
    """(agents that may read Common Files, count of Windows-service agents)."""
    by_pid = {row.get('ProcessId'): row for row in processes if isinstance(row, dict)}
    readers, service = [], 0
    for row in processes:
        if not isinstance(row, dict) or str(row.get('Name') or '').casefold() not in AGENT_NAMES:
            continue
        parent = by_pid.get(row.get('ParentProcessId')) if row.get('ParentProcessId') != row.get('ProcessId') else None
        parent_name = str((parent or {}).get('Name') or '').casefold()
        if parent_name == SERVICE_PARENT:
            service += 1
            continue
        readers.append(dict(pid=row.get('ProcessId'), executable=row.get('ExecutablePath'),
                            parent=parent_name or None, parent_executable=(parent or {}).get('ExecutablePath')))
    return readers, service


def sharing_installations(install):
    """Controller roots of every GOAT installation in this suite whose Common Files is this one's."""
    own = Path(install['controller_state_root'])
    common = PureWindowsPath(str(install['common_files_root']))
    roots, unreadable = [(own, install)], []
    try:
        siblings = sorted(p for p in own.parent.iterdir() if p.is_dir() and not p.name.startswith('.') and p != own)
    except OSError:
        siblings = []
    for folder in siblings:
        receipt = folder / 'installation.json'
        if not receipt.is_file():
            continue
        try:
            other = read_json(receipt)
            shared = PureWindowsPath(str(other['common_files_root'])) == common
        except (OSError, ValueError, KeyError, TypeError):
            unreadable.append(str(folder))
            continue
        if shared:
            roots.append((folder, other))
    return roots, unreadable


def research_readers(install, *, now):
    """(busy runs, other unfinished runs, unreadable) across every installation sharing this Common Files."""
    from studio_research_queue import ENDED, JOB_ID, batch_row, runner_row, _runner_ids
    from studio_research_status import queue_jobs
    busy, waiting = [], []
    roots, unreadable = sharing_installations(install)
    for root, other in roots:
        where = str(root)
        slot = root / 'seed-active.json'
        if slot.is_file():
            try:
                held = read_json(slot)
                if held.get('status') != 'released':
                    busy.append(dict(installation=where, kind='terminal_slot', batch_id=held.get('batch_id'), state='held'))
            except (OSError, ValueError, AttributeError):
                unreadable.append(str(slot))
        session_path = root / 'session.json'
        jobs = []
        if session_path.is_file():
            try:
                jobs = queue_jobs(root, read_json(session_path))
            except Exception as error:      # an unreadable queue may hide a running batch: fail closed
                unreadable.append(where + ' queue (' + str(error)[:120] + ')')
        for job in jobs if isinstance(jobs, list) else []:
            if not isinstance(job, dict) or not isinstance(job.get('job_id'), str) or not JOB_ID.fullmatch(job['job_id']):
                continue
            try:
                row = batch_row(root, other, job, now=now, with_progress=False)
            except Exception as error:
                unreadable.append(where + ' batch ' + job['job_id'] + ' (' + str(error)[:120] + ')')
                continue
            entry = dict(installation=where, kind='batch', batch_id=row['batch_id'], state=row['state'])
            (busy if row['state'] in BUSY_STATES else waiting if row['state'] not in ENDED else []).append(entry)
        for kind in RUNNER_KINDS:
            for batch_id in _runner_ids(root, kind):
                try:
                    row, reason = runner_row(root, kind, batch_id, now=now)
                except Exception as error:
                    row, reason = None, str(error)[:120]
                if row is None:
                    unreadable.append(where + ' ' + kind + ' ' + batch_id + ' (' + str(reason)[:120] + ')')
                    continue
                entry = dict(installation=where, kind=kind, batch_id=batch_id, state=row['state'])
                (busy if row['state'] in BUSY_STATES else waiting if row['state'] not in ENDED else []).append(entry)
    return busy, waiting, unreadable


def check_readers(install, *, now, processes=None):
    """Refuse while a tester may read GOAT_News.csv; else the other unfinished runs and the service-agent count."""
    busy, waiting, unreadable = research_readers(install, now=now)
    if busy:
        first = busy[0]
        raise Refusal('A ' + first['kind'].replace('_', ' ') + ' (' + str(first['batch_id']) + ', ' + first['state'] + ') in '
                      + first['installation'] + ' may be reading GOAT_News.csv, so the news file was not replaced. '
                      'Run news-history-sync again once it has finished or been paused.', 'NEWS_HISTORY_TESTER_BUSY',
                      busy=busy)
    if unreadable:
        raise Refusal('GOAT could not read every research run that shares this Common Files folder (' + unreadable[0]
                      + '), so it cannot prove no tester is reading GOAT_News.csv. Nothing was replaced.',
                      'NEWS_HISTORY_TESTER_BUSY', unreadable=unreadable[:20])
    rows = process_inventory() if processes is None else processes
    readers, service = agent_readers(rows)
    if readers:
        first = readers[0]
        owner = ('MT5 ' + str(first['parent_executable'] or first['parent']) if first['parent'] in ('terminal64.exe', 'terminal.exe')
                 else 'a parent GOAT cannot identify')
        raise Refusal(str(len(readers)) + ' MT5 tester agent' + ('s are' if len(readers) != 1 else ' is') + ' running (PID '
                      + str(first['pid']) + ', started by ' + owner + ') and may be reading GOAT_News.csv, so the news file '
                      'was not replaced. Retry when no test or optimization runs and the tester agents have exited '
                      '(closing that MT5 ends them).', 'NEWS_HISTORY_TESTER_BUSY', agents=readers[:20])
    return dict(unfinished_runs=waiting, service_agents_ignored=service)


# ------------------------------------------------------------------ write

def _fsync_write(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _backup_path(folder, now):
    plain = folder / (FILE_NAME + '.bak')
    if not plain.exists():
        return plain
    stamped = folder / (FILE_NAME + '.' + _utc_stamp(now) + '.bak')
    return stamped if not stamped.exists() else folder / (FILE_NAME + '.' + _utc_stamp(now) + '-' + uuid.uuid4().hex[:8] + '.bak')


def write_news_file(folder, data, expected_sha, *, now, before_swap=None):
    """Atomic replace of GOAT_News.csv with verified bytes, keeping the previous file. Returns the write facts."""
    folder = Path(folder)
    target = folder / FILE_NAME
    previous = _sha256(target.read_bytes()) if target.is_file() else None
    if previous == expected_sha:
        return dict(path=str(target), backupPath=None, previousSha256=previous, changed=False)
    if _sha256(data) != expected_sha:
        raise Refusal('The file bytes do not hash to mt5FileSha256; nothing was written.', 'NEWS_HISTORY_SHA_MISMATCH')
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (FILE_NAME + '.' + uuid.uuid4().hex + '.news-sync-tmp')
    backup = None
    try:
        _fsync_write(temporary, data)
        if _sha256(temporary.read_bytes()) != expected_sha:
            raise Refusal('The written temporary file does not read back as mt5FileSha256; GOAT_News.csv was not replaced.',
                          'NEWS_HISTORY_SHA_MISMATCH')
        if before_swap is not None:
            before_swap()
        if target.is_file():
            backup = _backup_path(folder, now)
            try:
                os.link(target, backup)          # create-only; the old bytes stay under the backup name
            except OSError:
                old = target.read_bytes()
                _fsync_write(backup, old)
            if _sha256(backup.read_bytes()) != previous:
                raise Refusal('The backup of the previous GOAT_News.csv did not read back unchanged; nothing was replaced.',
                              'NEWS_HISTORY_BACKUP_FAILED')
        try:
            os.replace(temporary, target)
        except OSError as error:
            raise Refusal('GOAT_News.csv could not be replaced (' + str(error)[:160] + '); MT5 may hold it open. The previous '
                          'file is unchanged.', 'NEWS_HISTORY_TESTER_BUSY') from None
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        if backup is not None and backup.exists() and target.is_file() and _sha256(target.read_bytes()) == previous:
            backup.unlink()                      # only our own copy, while the original is still in place
        raise
    if _sha256(target.read_bytes()) != expected_sha:
        raise Refusal('GOAT_News.csv was replaced but does not read back as mt5FileSha256. The previous file is '
                      + str(backup) + '.', 'NEWS_HISTORY_SHA_MISMATCH', backupPath=str(backup))
    return dict(path=str(target), backupPath=None if backup is None else str(backup), previousSha256=previous, changed=True)


def write_receipt(root, record, *, now):
    folder = Path(root) / RECEIPT_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_utc_stamp(now) + '-' + record['sha256'][:12] + '.json')
    if path.exists():
        path = folder / (_utc_stamp(now) + '-' + record['sha256'][:12] + '-' + uuid.uuid4().hex[:8] + '.json')
    temporary = folder / (path.name + '.' + uuid.uuid4().hex + '.tmp')
    _fsync_write(temporary, (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8'))
    os.replace(temporary, path)
    return path


# ------------------------------------------------------------------ command

def sync(install, *, min_impact=DEFAULT_MIN_IMPACT, from_date=DEFAULT_FROM, to_date=None, now=None, processes=None):
    """news-history-sync for one installation receipt. Returns the one-line JSON result."""
    now = time.time() if now is None else now
    params = request_params(min_impact, from_date, to_date)
    root = Path(install['controller_state_root'])
    session_path = root / 'session.json'
    if not session_path.is_file():
        raise Refusal('Bind this terminal\'s demo account (bootstrap) before syncing the news history: the request '
                      'names its MT5 account.', 'NEWS_HISTORY_CREDENTIAL_MISSING')
    login = str(read_json(session_path)['account']['login'])
    readers = check_readers(install, now=now, processes=processes)       # before anything is requested
    token = load_credential(credential_file(install, login))
    try:
        value = fetch(request_url(params, login), token)
        data, summary = check_response(value, min_impact)
        def recheck():     # the download took time: check again right before the rename
            readers.update(check_readers(install, now=time.time(), processes=processes))
        written = write_news_file(Path(install['common_files_root']) / 'GOAT', data, summary['sha256'], now=now,
                                  before_swap=recheck)
    except Refusal as refusal:
        refusal.args = (_scrub(str(refusal), token),)
        raise
    except Exception as error:      # never let an unexpected message carry the credential
        raise Refusal(_scrub('news-history-sync stopped: ' + type(error).__name__ + ': ' + str(error)[:300], token),
                      'NEWS_HISTORY_FAILED') from None
    result = dict(rows=summary['rows'], firstRelease=summary['firstRelease'], lastRelease=summary['lastRelease'],
                  sha256=summary['sha256'], minImpact=summary['minImpact'], tierComplete=summary['tierComplete'],
                  path=written['path'], backupPath=written['backupPath'], changed=written['changed'],
                  previousSha256=written['previousSha256'], csvSha256=summary['csvSha256'], warnings=summary['warnings'],
                  unfinishedRuns=readers.get('unfinished_runs', []))
    record = dict(result, schema=RECEIPT_SCHEMA, syncedUtc=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
                  request=dict(endpoint=API_BASE + ENDPOINT, minImpact=min_impact, **{'from': params.get('from'), 'to': params.get('to')}),
                  accountId=login, generatedAt=value.get('generatedAt'),
                  range=value.get('range') if isinstance(value.get('range'), dict) else None,
                  monthlyCounts=value.get('monthlyCounts') if isinstance(value.get('monthlyCounts'), dict) else None,
                  excluded=value.get('excluded') if isinstance(value.get('excluded'), dict) else None,
                  serviceAgentsIgnored=readers.get('service_agents_ignored'),
                  note='Record sha256 with every sweep result; never mix results across news files with different sha256.')
    result['receiptPath'] = str(write_receipt(root, record, now=now))
    return result
