"""Transactional campaign state; deliberately contains no MT5 launch/stop code."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class Ledger:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, plan TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, campaign TEXT NOT NULL REFERENCES campaigns,
          spec TEXT NOT NULL, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs,
          number INTEGER NOT NULL, owner TEXT NOT NULL, state TEXT NOT NULL, evidence TEXT,
          UNIQUE(job,number));
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, at TEXT NOT NULL,
          campaign TEXT NOT NULL, job TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def event(self, campaign, job, action, detail):
        self.db.execute('INSERT INTO events(at,campaign,job,action,detail) VALUES(?,?,?,?,?)',
                        (datetime.now(timezone.utc).isoformat(), campaign, job, action, packed(detail)))

    def request(self, key, payload, operation):
        if not key or not isinstance(key, str):
            raise ValueError('Explicit idempotency key required')
        encoded = packed(payload)
        with self.transaction():
            prior = self.db.execute('SELECT * FROM requests WHERE key=?', (key,)).fetchone()
            if prior:
                if prior['payload'] != encoded:
                    raise ValueError('Idempotency key reused for different request')
                return json.loads(prior['result'])
            result = operation()
            self.db.execute('INSERT INTO requests VALUES(?,?,?)', (key, encoded, packed(result)))
            return result

    def plan(self, plan):
        if plan.get('schema_version') != 1 or not plan.get('jobs'):
            raise ValueError('Nonempty schema_version 1 plan required')
        if plan.get('execution_authorized') is not False:
            raise ValueError('This planning adapter only accepts non-executing plans')
        if not isinstance(plan.get('max_attempts_per_job'), int) or not 1 <= plan['max_attempts_per_job'] <= 3:
            raise ValueError('Explicit attempt bound 1..3 required')
        identities = []
        for job in plan['jobs']:
            for field in ('template_id', 'revision_id', 'source_sha256', 'symbol', 'conditions'):
                if not job.get(field):
                    raise ValueError(f'Missing job field: {field}')
            identities.append(sha(job))
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate job identity')
        campaign = sha(plan)
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM campaigns WHERE id=?', (campaign,)).fetchone():
                self.db.execute('INSERT INTO campaigns VALUES(?,?)', (campaign, packed(plan)))
                for identity, job in zip(identities, plan['jobs']):
                    job_id = sha([campaign, identity])
                    self.db.execute('INSERT INTO jobs(id,campaign,spec,state) VALUES(?,?,?,?)',
                                    (job_id, campaign, packed(job), 'pending'))
                self.event(campaign, None, 'planned', dict(jobs=len(identities)))
        return dict(campaign_id=campaign, jobs=len(identities), execution_authorized=False)

    def claim(self, campaign, owner, key):
        if not owner:
            raise ValueError('Owner required')
        def operation():
            if not self.db.execute('SELECT 1 FROM campaigns WHERE id=?', (campaign,)).fetchone():
                raise ValueError('Unknown campaign')
            # One unresolved native job across this ledger, not merely per campaign.
            # Multiple ledgers targeting a terminal need an external terminal lock.
            active = self.db.execute("SELECT id,state FROM jobs WHERE state IN ('claimed','running','reconcile_required')").fetchone()
            if active:
                raise ValueError('Unresolved job must be reconciled before another claim')
            job = self.db.execute("SELECT * FROM jobs WHERE campaign=? AND state='pending' ORDER BY rowid LIMIT 1", (campaign,)).fetchone()
            if not job:
                return dict(job_id=None)
            attempt = str(uuid.uuid4())
            number = job['attempt'] + 1
            self.db.execute('INSERT INTO attempts(id,job,number,owner,state) VALUES(?,?,?,?,?)',
                            (attempt, job['id'], number, owner, 'claimed'))
            self.db.execute("UPDATE jobs SET state='claimed',attempt=? WHERE id=?", (number, job['id']))
            self.event(campaign, job['id'], 'claimed', dict(attempt_id=attempt, owner=owner))
            return dict(job_id=job['id'], attempt_id=attempt, number=number,
                        spec=json.loads(job['spec']), launch_permitted=False)
        return self.request(key, ['claim', campaign, owner], operation)

    def transition(self, attempt, owner, outcome, evidence, key):
        allowed = {'running', 'reconcile_required', 'qualified', 'no_qualifier', 'infra_failed', 'cancelled'}
        if outcome not in allowed or not isinstance(evidence, dict) or not evidence:
            raise ValueError('Known outcome and nonempty evidence required')
        def operation():
            row = self.db.execute('SELECT a.*,j.campaign,j.spec FROM attempts a JOIN jobs j ON a.job=j.id WHERE a.id=?', (attempt,)).fetchone()
            if not row or row['owner'] != owner:
                raise ValueError('Attempt owner mismatch')
            if row['state'] not in ('claimed', 'running', 'reconcile_required'):
                raise ValueError('Attempt already terminal')
            if outcome == 'running' and row['state'] != 'claimed':
                raise ValueError('Running acknowledgement requires claimed attempt')
            # Evidence is an adapter assertion, not independent proof of MT5 state.
            if outcome in ('qualified', 'no_qualifier'):
                spec = json.loads(row['spec'])
                if evidence.get('source_sha256') != spec['source_sha256'] or evidence.get('symbol') != spec['symbol']:
                    raise ValueError('Result identity mismatch')
                artifacts = evidence.get('artifacts')
                if not isinstance(artifacts, list) or not artifacts:
                    raise ValueError('Result artifact references required')
                count = evidence.get('qualifying_exports')
                if type(count) is not int or count < 0 or (outcome == 'qualified') != (count > 0):
                    raise ValueError('Outcome/export count mismatch')
            self.db.execute('UPDATE attempts SET state=?,evidence=? WHERE id=?', (outcome, packed(evidence), attempt))
            self.db.execute('UPDATE jobs SET state=? WHERE id=?', (outcome, row['job']))
            self.event(row['campaign'], row['job'], outcome, dict(attempt_id=attempt, evidence=evidence))
            return dict(attempt_id=attempt, state=outcome)
        return self.request(key, ['transition', attempt, owner, outcome, evidence], operation)

    def retry(self, job_id, reconciliation, key):
        if not isinstance(reconciliation, dict) or reconciliation.get('native_terminal_state') != 'stopped' or not reconciliation.get('receipt_ref'):
            raise ValueError('Explicit stopped-native reconciliation receipt required')
        def operation():
            row = self.db.execute('SELECT j.*,c.plan FROM jobs j JOIN campaigns c ON j.campaign=c.id WHERE j.id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'infra_failed':
                raise ValueError('Only infrastructure failures can be retried')
            if row['attempt'] >= json.loads(row['plan'])['max_attempts_per_job']:
                raise ValueError('Attempt budget exhausted')
            self.db.execute("UPDATE jobs SET state='pending' WHERE id=?", (job_id,))
            self.event(row['campaign'], job_id, 'retry_queued', reconciliation)
            return dict(job_id=job_id, state='pending')
        return self.request(key, ['retry', job_id, reconciliation], operation)

    def status(self):
        return dict(campaigns=[dict(r) for r in self.db.execute('SELECT id FROM campaigns')],
                    jobs=[dict(r) for r in self.db.execute('SELECT id,campaign,state,attempt FROM jobs ORDER BY rowid')],
                    attempts=[dict(r) for r in self.db.execute('SELECT id,job,number,owner,state FROM attempts ORDER BY rowid')],
                    event_count=self.db.execute('SELECT count(*) FROM events').fetchone()[0],
                    native_execution_supported=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    plan = sub.add_parser('plan'); plan.add_argument('file', type=Path)
    args = parser.parse_args()
    ledger = Ledger(args.db)
    try:
        result = ledger.plan(json.loads(args.file.read_text(encoding='utf-8-sig'))) if args.command == 'plan' else ledger.status()
        print(json.dumps(result, indent=2))
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
