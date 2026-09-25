"""Durable Studio draft and pending-queue boundary. No native MT5 effects.

Actor identity is supplied by the trusted local adapter, never by request JSON.
The isolated UI draft adapter uses this boundary; native execution is unsupported.
"""
import json
import sqlite3
from contextlib import contextmanager
from studio_native_gate import mutation_gate
from campaign_ledger import packed, sha
from studio_settings import validate_tester, validate_export
from studio_strategy_settings import validate_strategy
from studio_dependencies import audit_dependencies
from studio_queue import COMMANDS as QUEUE_COMMANDS, change_queue, reserve_job


class Conflict(ValueError):
    pass


class StudioStore:
    def __init__(self, path, *, input_schema=None, dependency_policy=None):
        self.input_schema = None if input_schema is None else json.loads(packed(input_schema))
        self.input_schema_hash = None if input_schema is None else sha(self.input_schema)
        self.dependency_policy = None if dependency_policy is None else json.loads(packed(dependency_policy))
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS studio_native_gate(id INTEGER PRIMARY KEY CHECK(id=1), root TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_state(
          binding TEXT PRIMARY KEY, revision INTEGER NOT NULL,
          generation INTEGER NOT NULL, owner TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_receipts(
          binding TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
          receipt TEXT NOT NULL, PRIMARY KEY(binding,request_id));
        CREATE TABLE IF NOT EXISTS studio_drafts(
          binding TEXT PRIMARY KEY, settings TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_export_drafts(
          binding TEXT PRIMARY KEY, settings TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_queues(
          binding TEXT PRIMARY KEY, jobs TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS studio_strategy_drafts(
          binding TEXT PRIMARY KEY, settings TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with mutation_gate(self.db):
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def bind(self, terminal_id, run_id):
        if not all(isinstance(v, str) and v.strip() for v in (terminal_id, run_id)):
            raise ValueError('Explicit terminal and run identities required')
        binding = packed(dict(terminal_id=terminal_id, run_id=run_id))
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO studio_state VALUES(?,0,0,?)',
                            (binding, 'human'))
        return self.snapshot(terminal_id, run_id)

    def snapshot(self, terminal_id, run_id):
        binding = packed(dict(terminal_id=terminal_id, run_id=run_id))
        row = self.db.execute('SELECT s.*,d.settings,e.settings AS exports,i.settings AS strategy,q.jobs FROM studio_state s '
                              'LEFT JOIN studio_drafts d ON s.binding=d.binding '
                              'LEFT JOIN studio_export_drafts e ON s.binding=e.binding '
                              'LEFT JOIN studio_strategy_drafts i ON s.binding=i.binding '
                              'LEFT JOIN studio_queues q ON s.binding=q.binding '
                              'WHERE s.binding=?', (binding,)).fetchone()
        if row is None:
            raise ValueError('Unknown terminal/run binding')
        return dict(terminal_id=terminal_id, run_id=run_id, revision=row['revision'],
                    generation=row['generation'], owner=row['owner'],
                    tester_draft=None if row['settings'] is None else json.loads(row['settings']),
                    export_draft=None if row['exports'] is None else json.loads(row['exports']),
                    strategy_draft=None if row['strategy'] is None else json.loads(row['strategy']),
                    queue=[] if row['jobs'] is None else json.loads(row['jobs']))

    def submit(self, request, *, actor):
        fields = {'schema_version', 'request_id', 'terminal_id', 'run_id',
                  'expected_revision', 'generation', 'command', 'payload'}
        if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1:
            raise ValueError('Unsupported command envelope')
        if not all(isinstance(request[key], str) and request[key].strip()
                   for key in ('terminal_id', 'run_id', 'command')):
            raise ValueError('Explicit terminal/run and command identities required')
        if actor not in ('human', 'agent'):
            raise ValueError('Untrusted actor')
        if not isinstance(request['request_id'], str) or not request['request_id'].strip():
            raise ValueError('Request ID required')
        for key in ('expected_revision', 'generation'):
            if type(request[key]) is not int or request[key] < 0:
                raise ValueError('Nonnegative integer revision/generation required')
        command = request['command']
        if command not in ('control.takeover', 'control.grant_agent', 'draft.replace_tester', 'draft.replace_export', 'draft.replace_configuration', 'draft.replace_strategy', *QUEUE_COMMANDS):
            raise ValueError('Unsupported command or payload; no execution side effect')
        if command == 'draft.replace_strategy':
            payload = request['payload']
            if self.input_schema is None:
                raise ValueError('Trusted source input schema required')
            if not isinstance(payload,dict) or set(payload) != {'schema_hash','values'}:
                raise ValueError('Explicit schema hash and complete strategy values required')
            if payload['schema_hash'] != self.input_schema_hash:
                raise Conflict('Strategy schema changed; refresh discovery')
            settings = validate_strategy(payload['values'],self.input_schema)
            settings['schema_hash'] = self.input_schema_hash
            if self.dependency_policy is not None:
                audit = audit_dependencies(settings,self.input_schema,self.dependency_policy)
                errors = [item['message'] for item in audit['findings'] if item['severity']=='error']
                if errors:
                    raise ValueError('; '.join(errors))
                settings['dependency_validation'] = audit
        elif command == 'draft.replace_tester':
            settings = validate_tester(request['payload'])
        elif command == 'draft.replace_export':
            settings = validate_export(request['payload'])
        elif command == 'draft.replace_configuration':
            payload = request['payload']
            if not isinstance(payload,dict) or set(payload) != {'tester','export'}:
                raise ValueError('Tester and export sections required together')
            settings = dict(tester=validate_tester(payload['tester']),
                            export=validate_export(payload['export'],payload['tester']))
        elif command in QUEUE_COMMANDS:
            if not isinstance(request['payload'],dict):
                raise ValueError('Queue payload must be an object')
        elif request['payload'] != {}:
            raise ValueError('Unexpected control payload')
        binding = packed(dict(terminal_id=request['terminal_id'], run_id=request['run_id']))
        payload_hash = sha(dict(request=request, actor=actor))
        with self.transaction():
            prior = self.db.execute('SELECT * FROM studio_receipts WHERE binding=? AND request_id=?',
                                    (binding, request['request_id'])).fetchone()
            if prior:
                if prior['payload_hash'] != payload_hash:
                    raise Conflict('Request ID reused with different content or actor')
                return json.loads(prior['receipt'])
            state = self.snapshot(request['terminal_id'], request['run_id'])
            if state['revision'] != request['expected_revision']:
                raise Conflict('Stale state revision')
            if state['generation'] != request['generation']:
                raise Conflict('Revoked controller generation')
            if command in ('draft.replace_tester', 'draft.replace_export', 'draft.replace_configuration', 'draft.replace_strategy', *QUEUE_COMMANDS):
                if actor != state['owner']:
                    raise Conflict('Current controller required; take over explicitly')
                if command in QUEUE_COMMANDS:
                    if command == 'queue.reserve':
                        # Same SQLite transaction as queue revision and receipt.
                        # No second reservation in this controller, even across runs.
                        for queued in self.db.execute('SELECT jobs FROM studio_queues'):
                            if any(j['status'] in ('reserved','starting','running','reconcile_required','verifying')
                                   for j in json.loads(queued['jobs'])):
                                raise Conflict('Unresolved native reservation requires reconciliation')
                        jobs = reserve_job(state,request['payload'],sha([binding,request['request_id'],payload_hash]))
                    else:
                        jobs = change_queue(command,request['payload'],state,self.input_schema,self.dependency_policy)
                    self.db.execute('INSERT OR REPLACE INTO studio_queues VALUES(?,?)',(binding,packed(jobs)))
                    state['queue'] = jobs
                elif command == 'draft.replace_strategy':
                    self.db.execute('INSERT OR REPLACE INTO studio_strategy_drafts VALUES(?,?)',
                                    (binding, packed(settings)))
                    state['strategy_draft'] = settings
                elif command == 'draft.replace_configuration':
                    self.db.execute('INSERT OR REPLACE INTO studio_drafts VALUES(?,?)',
                                    (binding, packed(settings['tester'])))
                    self.db.execute('INSERT OR REPLACE INTO studio_export_drafts VALUES(?,?)',
                                    (binding, packed(settings['export'])))
                    state.update(tester_draft=settings['tester'],export_draft=settings['export'])
                elif command == 'draft.replace_tester':
                    if state['export_draft'] is not None:
                        validate_export(state['export_draft'],settings)
                    self.db.execute('INSERT OR REPLACE INTO studio_drafts VALUES(?,?)',
                                    (binding, packed(settings)))
                    state['tester_draft'] = settings
                else:
                    validate_export(settings,state['tester_draft'])
                    self.db.execute('INSERT OR REPLACE INTO studio_export_drafts VALUES(?,?)',
                                    (binding, packed(settings)))
                    state['export_draft'] = settings
                state['revision'] += 1
            else:
                # An agent cannot grant itself control or impersonate human takeover.
                if actor != 'human':
                    raise Conflict('Human control action required')
                owner = 'human' if command == 'control.takeover' else 'agent'
                state.update(owner=owner, revision=state['revision']+1,
                             generation=state['generation']+1)
            self.db.execute('UPDATE studio_state SET revision=?,generation=?,owner=? WHERE binding=?',
                            (state['revision'], state['generation'], state['owner'], binding))
            receipt = dict(request_id=request['request_id'], command=command,
                           status='applied', state=state, execution_effect=False)
            self.db.execute('INSERT INTO studio_receipts VALUES(?,?,?,?)',
                            (binding, request['request_id'], payload_hash, packed(receipt)))
            return receipt
