"""Read-only reason for a native_error batch, taken from the selected terminal's EA journal.

The native queue only says a member ended in Error. The EA writes why (for example
its DEINIT line `XML Migration incomplete: root=GOAT\\R...\\reports files=0; ...
Aborting exports.`) to MQL5\\Logs\\<yyyymmdd>.log. This module quotes those lines
for the exact run so batch-status and finish can show them. It never writes,
retries or interprets the evidence as a qualification; absence is not proof.
"""
import json
from pathlib import Path
import re

MAX_LOG_FILES = 3
MAX_TAIL_BYTES = 8 * 1024 * 1024
MAX_LINES = 5
MAX_LINE_CHARS = 500
# Relative to the terminal data folder: never the absolute path (it holds the Windows user name).
LOG_FOLDER = 'MQL5\\Logs'
REASON = re.compile(r'incomplete|abort|error|fail|refus|reject', re.IGNORECASE)


def _decode(raw):
    if raw.startswith(b'\xff\xfe') or (len(raw) > 1 and raw[1:2] == b'\x00'):
        return raw.decode('utf-16-le', errors='replace').lstrip('﻿')
    return raw.decode('utf-8', errors='replace').lstrip('﻿')


def _tail(path):
    size = path.stat().st_size
    with path.open('rb') as stream:
        if size > MAX_TAIL_BYTES:
            # Keep UTF-16 code-unit alignment for the usual MT5 journal encoding.
            stream.seek(size - MAX_TAIL_BYTES + (size % 2))
        return stream.read(MAX_TAIL_BYTES)


def native_error_evidence(terminal_data_root, native_run_relative):
    """Quote at most a few recent EA journal lines naming this native run."""
    if not isinstance(native_run_relative, str) or not re.fullmatch(r'GOAT\\R[0-9a-f]{12}', native_run_relative):
        return dict(status='unavailable', reason='invalid native run identity')
    run = native_run_relative.split('\\')[1]
    logs = Path(terminal_data_root)/'MQL5'/'Logs'
    try:
        if logs.is_symlink() or not logs.is_dir():
            return dict(status='unavailable', reason='terminal EA journal folder not found', folder=LOG_FOLDER)
        files = sorted((item for item in logs.iterdir()
                        if re.fullmatch(r'\d{8}\.log', item.name) and item.is_file() and not item.is_symlink()),
                       key=lambda item: item.name)[-MAX_LOG_FILES:]
        lines = []
        for item in files:
            for line in _decode(_tail(item)).splitlines():
                if run in line and REASON.search(line):
                    lines.append(dict(log=item.name, line=line.strip()[:MAX_LINE_CHARS]))
    except OSError as error:
        return dict(status='unavailable', reason='terminal EA journal unreadable: ' + type(error).__name__, folder=LOG_FOLDER)
    if not lines:
        return dict(status='not_found', folder=LOG_FOLDER,
                    note='No EA journal line names this run with an error; inspect the MT5 Experts journal')
    return dict(status='observed', folder=LOG_FOLDER, lines=lines[-MAX_LINES:],
                note='Quoted from the EA journal; read-only diagnostic, not a retry or qualification')


def for_job(controller, job, native, no_edge=None):
    """Evidence for a job whose native observation ended in native_error, else None.

    `no_edge` holds the member indexes tested with nothing qualifying
    (studio_finish research_outcomes). MT5 also ends those members in Error, but
    they are research results, so they are named apart and never as failures.
    """
    if not isinstance(native, dict) or native.get('status') != 'native_error':
        return None
    no_edge = sorted({i for i in (no_edge or ()) if type(i) is int})
    members = native.get('members') if isinstance(native.get('members'), list) else []
    errored = [i for i, m in enumerate(members) if isinstance(m, dict) and m.get('status') == 'native_error']
    failed = [i for i in errored if i not in no_edge]
    if no_edge and errored and not failed:
        return dict(status='no_edge_only', members_no_edge=no_edge, members_failed=[],
                    note='Every member MT5 ended in Error was tested with nothing qualifying in its window (no profitable settings, none qualifying with the forward period, or every re-tested set lost money): '
                         'a research result, not a failure. Nothing to diagnose.')
    try:
        path = Path(job['launch_intent']['package'])/'manifest.json'
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('manifest exceeds read bound')
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        evidence = native_error_evidence(controller.install['terminal_data_root'], manifest.get('native_run_relative'))
    except (OSError, ValueError, KeyError, TypeError) as error:
        evidence = dict(status='unavailable', reason='native run identity unreadable: ' + type(error).__name__)
    if no_edge:
        evidence.update(members_no_edge=no_edge, members_failed=failed,
                        no_edge_note='Members in members_no_edge were tested with nothing qualifying (no profitable settings, none qualifying with the forward period, or every re-tested set lost money): results, not failures')
    return evidence
