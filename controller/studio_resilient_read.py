"""Bounded retries for observation reads only; never retries commands."""
import json
import time
from pathlib import Path


def read_observation(path, *, attempts=6, delay=0.05):
    if not 1 <= attempts <= 20 or not 0 <= delay <= 0.25:
        raise ValueError('Invalid read retry budget')
    path=Path(path)
    for attempt in range(attempts):
        try:
            before=path.stat().st_mtime_ns
            value=json.loads(path.read_text(encoding='utf-8'))
            after=path.stat().st_mtime_ns
            if before!=after:
                raise PermissionError('Observation changed during read')
            return value, after/1_000_000_000
        except (PermissionError, json.JSONDecodeError):
            if attempt==attempts-1:raise
            time.sleep(delay)
