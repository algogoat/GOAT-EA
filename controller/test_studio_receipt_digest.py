"""Receipts store a queue digest, not the queue; scans and compact-receipts.

Banker (2026-10-02): 62 receipts held 9.78 GB because each embedded the 818 MB
queue. These tests pin the new receipt shape, byte-identical replay, the
unchanged bridge outbox, identical authority scans on legacy and new receipts,
and the compact-receipts migration (preview, apply, idempotent, refusals,
archive collision, mid-run change, a scaled large-receipt check).
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed, sha
from studio_agent import unique_object
from studio_batch import prepare_batch
from studio_bridge import write_json
from studio_installation import read_json
import studio_receipt_digest
from studio_receipt_digest import (DIGEST_KEY, archive_path, compact, queue_digest, receipt_views)
from test_studio_fast_lane import synthetic


def receipts(db):
    return {row[0]: row[1] for row in db.execute('SELECT request_id,receipt FROM studio_receipts ORDER BY rowid')}


def make_legacy(db, queue, *, only=None, dump=packed):
    """Rewrite receipts to the pre-digest shape: the whole queue inside state."""
    for binding, request_id, text in db.execute('SELECT binding,request_id,receipt FROM studio_receipts').fetchall():
        if only is not None and request_id not in only:
            continue
        value = json.loads(text)
        value['state'].pop(DIGEST_KEY, None)
        value['state']['queue'] = queue
        db.execute('UPDATE studio_receipts SET receipt=? WHERE binding=? AND request_id=?', (dump(value), binding, request_id))


class ReceiptShapeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'old', synthetic(self.fixture, self.c, 2))

    def request(self, command, request_id, payload):
        state = self.c.state()
        return dict(schema_version=1, request_id=request_id, terminal_id=self.c.terminal, run_id=self.c.run,
                    expected_revision=state['revision'], generation=state['generation'], command=command, payload=payload)

    def test_new_receipts_store_the_queue_digest_and_never_the_queue(self):
        stored = receipts(self.c.store.db)
        self.assertGreaterEqual(len(stored), 2)
        for request_id, text in stored.items():
            state = json.loads(text)['state']
            self.assertNotIn('queue', state, request_id)
            self.assertEqual(set(state[DIGEST_KEY]), {'sha256', 'job_count'})
        # The latest queue receipt digests exactly the committed queue row.
        batch = json.loads(stored['old-batch'])['state'] if 'old-batch' in stored else json.loads(list(stored.values())[-1])['state']
        queue = self.c.state()['queue']
        row = self.c.store.db.execute('SELECT jobs FROM studio_queues').fetchone()[0]
        self.assertEqual(batch[DIGEST_KEY], dict(sha256=sha(queue), job_count=len(queue)))
        self.assertEqual(batch[DIGEST_KEY]['sha256'], hashlib.sha256(row.encode()).hexdigest())
        self.assertEqual(batch[DIGEST_KEY], queue_digest(queue))

    def test_replay_returns_byte_identical_receipts(self):
        request = self.request('queue.cancel', 'cancel-old', dict(job_id='old'))
        fresh = self.c.store.submit(request, actor='agent')
        replay = self.c.store.submit(request, actor='agent')
        stored = receipts(self.c.store.db)['cancel-old']
        self.assertEqual(packed(fresh), stored)
        self.assertEqual(packed(replay), stored)
        self.assertEqual(fresh, replay)
        self.assertNotIn('queue', fresh['state'])
        self.assertEqual(fresh['state'][DIGEST_KEY], queue_digest(self.c.state()['queue']))
        # A control receipt (no queue write) digests the queue it observed.
        grant = json.loads(receipts(self.c.store.db)['human-grant'])
        self.assertEqual(grant['state'][DIGEST_KEY], dict(sha256=sha([]), job_count=0))

    def test_bridge_outbox_fields_are_unchanged_and_replay_identical(self):
        request = self.request('queue.cancel', 'bridge-cancel', dict(job_id='old'))
        inbox = self.c.bridge.root / 'agent' / 'inbox' / 'bridge-cancel.json'
        outbox = self.c.bridge.root / 'agent' / 'outbox' / 'bridge-cancel.json'
        write_json(inbox, request); self.c.bridge.pump()
        first = read_json(outbox)
        self.assertTrue(first['ok'])
        self.assertEqual(first['receipt_detail'], 'revision_only')
        self.assertEqual(set(first['receipt']), {'request_id', 'command', 'status', 'state', 'execution_effect'})
        self.assertEqual(set(first['receipt']['state']), {'terminal_id', 'run_id', 'revision', 'generation', 'owner'})
        self.assertEqual(first['receipt']['state']['revision'], self.c.state()['revision'])
        write_json(inbox, request); self.c.bridge.pump()          # transport retry: replayed receipt
        self.assertEqual(read_json(outbox), first)


class ReceiptViewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE studio_receipts(binding TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(binding,request_id))')
        self.state = dict(terminal_id='t', run_id='r', revision=3, generation=2, owner='agent', tester_draft=None,
                          export_draft=dict(MinScore=60.5), strategy_draft=None)

    def put(self, request_id, text):
        self.db.execute('INSERT INTO studio_receipts VALUES(?,?,?,?)', ('b', request_id, 'h-' + request_id, text))

    def test_view_is_the_receipt_without_its_queue_on_both_formats(self):
        queue = [dict(job_id='j%d' % i, status='completed', blob='x' * 1000) for i in range(50)]
        legacy = dict(request_id='legacy', command='control.takeover', status='applied', execution_effect=False,
                      state=dict(self.state, queue=queue))
        new = dict(legacy, request_id='new', state=dict(self.state, queue_digest=queue_digest(queue)))
        self.put('legacy', packed(legacy)); self.put('new', packed(new))
        views = {rid: (payload_hash, view) for rid, payload_hash, view in receipt_views(self.db, 'b')}
        self.assertEqual(views['legacy'], ('h-legacy', dict(legacy, state=self.state)))
        self.assertEqual(views['new'], ('h-new', new))
        self.assertIs(views['legacy'][1]['execution_effect'], False)          # JSON false stays False, not 0
        self.assertEqual(receipt_views(self.db, 'b', 'new'), [('new', 'h-new', new)])
        self.assertEqual(receipt_views(self.db, 'b', 'missing'), [])

    def test_invalid_json_and_duplicate_fields_fail_closed(self):
        self.put('bad', '{"command":')
        with self.assertRaisesRegex(ValueError, 'not valid JSON'):
            receipt_views(self.db, 'b')
        self.db.execute('DELETE FROM studio_receipts')
        self.put('dup', '{"command":"control.grant_agent","command":"control.takeover","state":{"owner":"agent","queue":[1]}}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON field: command'):
            receipt_views(self.db, 'b', object_pairs_hook=unique_object)
        self.db.execute('DELETE FROM studio_receipts')
        self.put('dup', '{"command":"x","state":{"owner":"agent","owner":"human","queue":[1]}}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON field: owner'):
            receipt_views(self.db, 'b', object_pairs_hook=unique_object)


class ScanFormatTests(unittest.TestCase):
    """The regrant, owner-research and legacy-grant scans decide identically on both formats."""

    def test_renewed_epoch_authority_is_identical_on_legacy_receipts(self):
        import test_studio_research_regrant as regrant
        from studio_research_authority import authority, operation
        case = regrant.ResearchRegrantTests(); case.setUp(); self.addCleanup(case.doCleanups)
        case.take(); _, result = case.grant(); self.assertTrue(result['ok'])
        db = case.c.store.db
        state = case.state()
        with operation('prepare-batch'):
            new = authority(db, case.binding, state)
        make_legacy(db, [dict(job_id='j%d' % i, blob='q' * 500) for i in range(20)])
        self.assertIn('"queue":[', receipts(db)['native-takeover'])
        with operation('prepare-batch'):
            self.assertEqual(authority(db, case.binding, state), new)
        # A changed takeover epoch in a legacy receipt still refuses.
        text = receipts(db)['native-takeover']
        db.execute('UPDATE studio_receipts SET receipt=? WHERE request_id=?',
                   (text.replace('"owner":"human"', '"owner":"agent"'), 'native-takeover'))
        with operation('prepare-batch'), self.assertRaisesRegex(ValueError, 'One genuine native takeover receipt required'):
            authority(db, case.binding, state)

    def test_owner_research_grant_is_identical_on_legacy_receipts(self):
        import test_studio_owner_research as owner
        case = owner.OwnerResearchTests(); case.setUp(); self.addCleanup(case.doCleanups)
        new = case.authorization()
        make_legacy(case.c.store.db, [dict(job_id='j', blob='q' * 2000)])
        self.assertEqual(case.authorization(), new)
        text = receipts(case.c.store.db)['human-grant']
        case.c.store.db.execute('UPDATE studio_receipts SET receipt=? WHERE request_id=?',
                                (text.replace('"execution_effect":false', '"execution_effect":0'), 'human-grant'))
        with self.assertRaisesRegex(ValueError, 'not the reviewed grant'):
            case.authorization()

    def test_legacy_human_grant_classification_is_identical_on_both_formats(self):
        import test_studio_owner_research as owner
        from studio_research_authority import legacy_human_grant
        case = owner.OwnerResearchTests(); case.setUp(); self.addCleanup(case.doCleanups)
        c = case.c
        session = read_json(c.root / 'session.json'); session.pop('authority_kind', None)
        write_json(c.root / 'session.json', session)
        binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
        state = dict(owner='agent', generation=1)
        self.assertTrue(legacy_human_grant(c.store.db, binding, state))
        self.assertFalse(legacy_human_grant(c.store.db, binding, dict(owner='agent', generation=2)))
        make_legacy(c.store.db, [dict(job_id='j', blob='q' * 2000)])
        self.assertTrue(legacy_human_grant(c.store.db, binding, state))
        self.assertFalse(legacy_human_grant(c.store.db, binding, dict(owner='agent', generation=2)))


class CompactReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'old', synthetic(self.fixture, self.c, 2))
        self.db = self.c.store.db
        self.binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.queue = self.c.state()['queue']
        make_legacy(self.db, self.queue)
        self.legacy = receipts(self.db)
        self.assertTrue(all('"queue":[' in text for text in self.legacy.values()))

    def archive_dir(self):
        return self.c.root / 'native-evidence' / 'receipt-archive'

    def files(self):
        return sorted(p.name for p in self.archive_dir().glob('*')) if self.archive_dir().is_dir() else []

    def put_queue(self, mutate):
        queue = self.c.state()['queue']; mutate(queue)
        self.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(queue), self.binding))

    def test_preview_changes_nothing(self):
        result = compact(self.c)
        self.assertFalse(result['applied'])
        self.assertEqual(sorted(item['request_id'] for item in result['receipts']), sorted(self.legacy))
        self.assertEqual(result['receipt_bytes'], sum(len(text) for text in self.legacy.values()))
        self.assertEqual(result['receipts'][0]['job_count'], len(self.queue))
        self.assertEqual(receipts(self.db), self.legacy)
        self.assertEqual(self.files(), [])

    def test_apply_archives_exact_bytes_and_stores_the_digest(self):
        statements = []
        self.db.set_trace_callback(statements.append); self.addCleanup(self.db.set_trace_callback, None)
        with patch('studio_receipt_digest.CHUNK', 7):          # stress the streaming frame at every boundary
            result = compact(self.c, apply=True)
        self.assertTrue(result['applied'])
        self.assertFalse(any('VACUUM' in s.upper() for s in statements))
        after = receipts(self.db)
        self.assertEqual(len(result['receipts']), len(self.legacy))
        for item in result['receipts']:
            original = self.legacy[item['request_id']]
            archive = Path(item['archive']['path'])
            self.assertEqual(archive.read_bytes(), original.encode())
            self.assertEqual(item['archive']['sha256'], hashlib.sha256(original.encode()).hexdigest())
            value = json.loads(after[item['request_id']])
            self.assertNotIn('queue', value['state'])
            self.assertEqual(value['state'][DIGEST_KEY], queue_digest(self.queue))   # == sha(packed(queue))
            legacy = json.loads(original); del legacy['state']['queue']
            del value['state'][DIGEST_KEY]
            self.assertEqual(value, legacy)
            self.assertEqual(item['bytes_after'], len(after[item['request_id']]))
        self.assertEqual(sorted(self.files()), sorted(Path(item['archive']['path']).name for item in result['receipts']))
        journal = [json.loads(line) for line in Path(result['journal']).read_bytes().splitlines()]
        self.assertEqual([line['request_id'] for line in journal], [item['request_id'] for item in result['receipts']])
        self.assertEqual(journal[0]['archive'], result['receipts'][0]['archive'])
        # The migrated grant still replays (payload hash only) and stays the bridge-visible state.
        state = self.c.state()
        self.assertEqual(self.c.state()['queue'], self.queue)
        self.assertEqual(state['owner'], 'agent')

    def test_apply_is_idempotent_and_reuses_an_identical_archive(self):
        first = sorted(self.legacy)[0]
        rowid = self.db.execute('SELECT rowid FROM studio_receipts WHERE request_id=?', (first,)).fetchone()[0]
        view = receipt_views(self.db, self.binding, first)[0][2]
        path = archive_path(self.c.root, self.binding, first)
        studio_receipt_digest._archive(self.db, rowid, path, studio_receipt_digest._frame(view))   # interrupted run
        result = compact(self.c, apply=True)
        self.assertEqual(len(result['receipts']), len(self.legacy))
        snapshot = (receipts(self.db), {name: (self.archive_dir() / name).read_bytes() for name in self.files()})
        again = compact(self.c, apply=True)
        self.assertFalse(again['applied'])
        self.assertEqual(again['receipts'], [])
        self.assertEqual(again['already_compact'], len(self.legacy))
        self.assertEqual((receipts(self.db), {name: (self.archive_dir() / name).read_bytes() for name in self.files()}), snapshot)
        self.assertEqual(compact(self.c)['next_action'], 'Nothing to compact')

    def test_refuses_while_a_batch_is_active_before_any_archive(self):
        self.put_queue(lambda queue: queue.append(dict(job_id='live', status='running')))
        self.assertEqual(compact(self.c)['active_batches'], ['live'])
        with self.assertRaisesRegex(ValueError, r'^Batch live is active; compact receipts when no batch is starting or running\.$'):
            compact(self.c, apply=True)
        self.assertEqual(self.files(), [])
        self.assertEqual(receipts(self.db), self.legacy)

    def test_a_batch_that_starts_mid_run_refuses_inside_the_transaction(self):
        real = studio_receipt_digest._archive
        def then_start(*args):
            result = real(*args)
            self.put_queue(lambda queue: queue.append(dict(job_id='late', status='starting')))
            return result
        with patch('studio_receipt_digest._archive', side_effect=then_start):
            with self.assertRaisesRegex(ValueError, r'^Batch late is active'):
                compact(self.c, apply=True)
        self.assertEqual(receipts(self.db), self.legacy)
        self.assertEqual(len(self.files()), 1)            # the verified archive is kept, never deleted

    def test_a_receipt_changing_mid_run_refuses_and_changes_nothing(self):
        real = studio_receipt_digest._archive
        def then_change(db, rowid, path, frame):
            result = real(db, rowid, path, frame)
            text = db.execute('SELECT receipt FROM studio_receipts WHERE rowid=?', (rowid,)).fetchone()[0]
            db.execute('UPDATE studio_receipts SET receipt=? WHERE rowid=?', (text.replace('"old"', '"edited"', 1), rowid))
            return result
        with patch('studio_receipt_digest._archive', side_effect=then_change):
            with self.assertRaisesRegex(ValueError, r'changed during compaction; nothing was changed for it, retry$'):
                compact(self.c, apply=True)
        changed = receipts(self.db)
        self.assertTrue(all('"queue":[' in text for text in changed.values()))
        self.assertTrue(any('"edited"' in text for text in changed.values()))

    def test_a_different_existing_archive_refuses_and_is_kept(self):
        first = list(self.legacy)[0]                        # rowid order: the first one compacted
        path = archive_path(self.c.root, self.binding, first); path.parent.mkdir(parents=True)
        path.write_bytes(b'{"other":"receipt"}')
        with self.assertRaisesRegex(ValueError, 'A different receipt archive already exists'):
            compact(self.c, apply=True)
        self.assertEqual(path.read_bytes(), b'{"other":"receipt"}')
        self.assertEqual(self.files(), [path.name])        # no temporary file left behind
        self.assertEqual(receipts(self.db), self.legacy)

    def test_a_noncanonical_legacy_row_is_skipped_untouched(self):
        first = list(self.legacy)[0]
        make_legacy(self.db, self.queue, only={first}, dump=lambda value: json.dumps(value, indent=1))
        before = receipts(self.db)
        result = compact(self.c, apply=True)
        self.assertEqual([item['reason'] for item in result['skipped']], ['noncanonical_layout'])
        self.assertEqual(receipts(self.db)[first], before[first])
        self.assertNotIn(first, [item['request_id'] for item in result['receipts']])
        self.assertFalse(any(name.endswith('.tmp') for name in self.files()))

    def test_cli_contracts_and_demo_agent_route(self):
        from goat_studio import OPERATION_CONTRACTS
        from studio_research_authority import OPERATIONS, READ_OPERATIONS
        self.assertIn('compact-receipts', OPERATION_CONTRACTS)
        self.assertIn('compact-receipts', OPERATIONS); self.assertNotIn('compact-receipts', READ_OPERATIONS)
        import demo_agent
        with patch.object(demo_agent, 'DemoAgent') as agent, patch('builtins.print'):
            agent.return_value.compact_receipts.return_value = dict(applied=False)
            self.assertEqual(demo_agent.main(['--installation', 'x', 'compact-receipts', '--apply']), 0)
        agent.return_value.compact_receipts.assert_called_once_with(True)


class LargeReceiptTests(unittest.TestCase):
    """Banker's receipts scaled down: 10 receipts of about 5 MB each in a renewed epoch.

    Every renewed-epoch authority check scans the takeover receipts and reads the
    grant receipt. Python must never parse a whole receipt (legacy rows are cut by
    SQLite), and after compact-receipts the scanned bytes no longer grow with the
    old queue size.
    """
    RECEIPTS, QUEUE_BYTES = 10, 5_000_000

    def test_authority_check_does_not_scale_with_receipt_size(self):
        import test_studio_research_regrant as regrant
        from studio_research_authority import authority, operation
        case = regrant.ResearchRegrantTests(); case.setUp(); self.addCleanup(case.doCleanups)
        case.take(); _, result = case.grant(); self.assertTrue(result['ok'])
        db = case.c.store.db
        state = case.state()
        with operation('prepare-batch'):
            expected = authority(db, case.binding, state)
        queue = [dict(job_id='bank-%02d' % j, status='completed', history='h' * 100_000) for j in range(self.QUEUE_BYTES // 100_000)]
        template = json.loads(receipts(db)['native-takeover'])
        for i in range(self.RECEIPTS - 2):
            filler = dict(template, request_id='filler-%d' % i, command='queue.enqueue')
            db.execute('INSERT INTO studio_receipts VALUES(?,?,?,?)', (case.binding, filler['request_id'], 'f' * 64, packed(filler)))
        make_legacy(db, queue)
        sizes = [row[0] for row in db.execute('SELECT length(receipt) FROM studio_receipts')]
        self.assertEqual(len(sizes), self.RECEIPTS)
        self.assertTrue(all(size > self.QUEUE_BYTES for size in sizes))

        real_loads = json.loads
        largest = [0]
        def recording(text, *args, **kwargs):
            largest[0] = max(largest[0], len(text))
            return real_loads(text, *args, **kwargs)

        def check():
            best = None
            for _ in range(3):
                started = time.perf_counter()
                with operation('prepare-batch'):
                    self.assertEqual(authority(db, case.binding, state), expected)
                elapsed = time.perf_counter() - started
                best = elapsed if best is None else min(best, elapsed)
            return best

        with patch('json.loads', side_effect=recording):
            legacy_seconds = check()
        self.assertLess(largest[0], 100_000)           # no whole legacy receipt reached Python
        started = time.perf_counter(); real_loads(receipts(db)['native-takeover']); python_parse = time.perf_counter() - started

        with operation('compact-receipts'):
            done = compact(case.c, apply=True)
        self.assertEqual(len(done['receipts']), self.RECEIPTS)
        after = [row[0] for row in db.execute('SELECT length(receipt) FROM studio_receipts')]
        self.assertLess(sum(after), 50_000)
        for item in done['receipts']:
            self.assertEqual(Path(item['archive']['path']).stat().st_size, item['bytes_before'])
        largest[0] = 0
        with patch('json.loads', side_effect=recording):
            compact_seconds = check()
        self.assertLess(largest[0], 100_000)
        print('\nreceipt digest: %d receipts %.1f MB -> %.1f KB; authority check legacy %.3fs (Python would parse '
              'one receipt alone in %.3fs) -> compacted %.3fs' % (self.RECEIPTS, sum(sizes) / 1e6, sum(after) / 1e3,
                                                                 legacy_seconds, python_parse, compact_seconds))
        self.assertLess(compact_seconds, 1.0)
        self.assertLess(compact_seconds, legacy_seconds)


if __name__ == '__main__':
    unittest.main()
