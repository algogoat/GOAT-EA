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
            return dict(status='unavailable', reason='terminal EA journal folder not found', folder=str(logs))
        files = sorted((item for item in logs.iterdir()
                        if re.fullmatch(r'\d{8}\.log', item.name) and item.is_file() and not item.is_symlink()),
                       key=lambda item: item.name)[-MAX_LOG_FILES:]
        lines = []
        for item in files:
            for line in _decode(_tail(item)).splitlines():
                if run in line and REASON.search(line):
                    lines.append(dict(log=item.name, line=line.strip()[:MAX_LINE_CHARS]))
    except OSError as error:
        return dict(status='unavailable', reason='terminal EA journal unreadable: ' + type(error).__name__, folder=str(logs))
    if not lines:
        return dict(status='not_found', folder=str(logs),
                    note='No EA journal line names this run with an error; inspect the MT5 Experts journal')
    return dict(status='observed', folder=str(logs), lines=lines[-MAX_LINES:],
                note='Quoted from the EA journal; read-only diagnostic, not a retry or qualification')


def for_job(controller, job, native):
    """Evidence for a job whose native observation ended in native_error, else None."""
    if not isinstance(native, dict) or native.get('status') != 'native_error':
        return None
    try:
        path = Path(job['launch_intent']['package'])/'manifest.json'
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('manifest exceeds read bound')
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        return native_error_evidence(controller.install['terminal_data_root'], manifest.get('native_run_relative'))
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(status='unavailable', reason='native run identity unreadable: ' + type(error).__name__)
