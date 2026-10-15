"""Held-out lock (library scoring v1 phase 1, goatai#2221 §4): registry, enforcement, redaction.

Acceptance #3 (any changed byte fails verification, fail closed), #4 (no surface leaks a
locked value, including export file names and agent-readable log lines) and #5 (a lock
declared after prepare refuses that batch's start).
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import goat_studio
import studio_evidence_end
import studio_heldout as heldout
import test_goat_studio as fixtures
from campaign_ledger import packed
from studio_batch import prepare_batch
from studio_heldout import GENESIS, HeldOutRefused, canonical, chain_hash, lock_id, read_registry
from studio_heldout_guard import check_catchup, check_runner_start, check_seed_jobs, guard_error, guard_output, scrub

GOLDEN = Path(__file__).parent / 'fixtures' / 'heldout'
NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)      # AUTO evidence end: Friday 2026-10-02
NOW_AT = '2026-10-03T12:00:00Z'
REAL_UTC = studio_evidence_end._utc
CELL_SET = 'c' * 64

# Distinctive values the leak walk hunts for (the oosc r8 USDCHF export, B40 sentences, a seed and a catch-up).
SECRET_NUMBERS = {198, 1990, 415, 3.82, 8.73, 0.295, 48.1, 61.7, 0.37, -254.5, 7311, 19907, 4153, 2.47, 1.91}
SECRET_TEXT = re.compile(r'(?<![0-9a-fA-F.])(1990|415|3\.82|8\.73|0\.295|48\.10?|61\.7|0\.37|-254\.50?|7311|19907|4153|2\.47|1\.91)(?![0-9])')


def declaration(key, start, end, reveal_after, *, exposure_end=None, declared_at='2026-10-04T01:00:00Z'):
    body = dict(strategyKey=key, start=start, end=end, revealableAfter=reveal_after, weeks=13,
                exposureEnd=exposure_end or start, declaredAt=declared_at)
    return dict(body, lockId=lock_id(body))


def registry_bytes(events):
    """The desktop's writer, as the spec defines it: one canonical, hash-chained line per event."""
    prev, lines = GENESIS, []
    for seq, (op, lock, at) in enumerate(events):
        entry = dict(seq=seq, at=at, op=op, ref=lock['lockId'], lock=lock, prev=prev)
        entry['hash'] = chain_hash(prev, entry)
        lines.append(canonical(entry))
        prev = entry['hash']
    return ('\n'.join(lines) + '\n').encode('utf-8') if lines else b''


def write_registry(evidence_root, events):
    path = Path(evidence_root) / 'heldout' / 'locks.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(registry_bytes(events))
    return path


def golden_events():
    beacon = declaration('beacon-european-pullback', '2026-10-05', '2027-01-04', '2027-01-01', exposure_end='2026-10-02')
    compass = declaration('compass-trend-pullback', '2026-07-06', '2026-10-05', '2026-10-02', exposure_end='2026-07-03',
                          declared_at='2026-07-04T00:00:00Z')
    cells = dict(lockId=compass['lockId'], cells=[dict(symbol='EURUSD', timeframe='H1', setSha256=CELL_SET)])
    return [('declare', compass, '2026-07-04T00:00:00Z'), ('freeze', cells, '2026-10-03T00:00:00Z'),
            ('declare', beacon, '2026-10-04T01:00:00Z')]


def leaks(value, path='$'):
    """Every place a distinctive metric value survives in a reply."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found += leaks(item, path + '.' + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += leaks(item, '%s[%d]' % (path, index))
    elif isinstance(value, bool) or value is None:
        pass
    elif isinstance(value, (int, float)):
        if value in SECRET_NUMBERS:
            found.append((path, value))
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        found.append((path, value))
    return found


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = dict(controller_state_root=str(self.root / 'suite' / 'abc'), evidence_root=str(self.root / 'evidence'))

    def read(self, now=NOW):
        return read_registry(self.install, now=now)

    def test_golden_registry_verifies_and_the_writer_reproduces_it_byte_for_byte(self):
        golden = (GOLDEN / 'locks.golden.jsonl').read_bytes()
        expected = json.loads((GOLDEN / 'locks.golden.json').read_text(encoding='utf-8'))
        self.assertEqual(registry_bytes(golden_events()), golden)   # the format cannot drift silently
        shutil.copytree(GOLDEN, self.root / 'evidence' / 'heldout', ignore=shutil.ignore_patterns('*.json'))
        (self.root / 'evidence' / 'heldout' / 'locks.golden.jsonl').rename(self.root / 'evidence' / 'heldout' / 'locks.jsonl')
        registry = self.read()
        self.assertEqual(registry['state'], 'ok', registry['error'])
        self.assertEqual(registry['head'], expected['head'])
        self.assertEqual({l['strategy_key']: l['status'] for l in registry['locks']}, expected['status_at_2026_10_03'])
        self.assertEqual([l['lock_id'] for l in registry['locks']], expected['lock_ids'])
        compass = registry['locks'][0]
        self.assertEqual(compass['candidate'], [dict(symbol='EURUSD', timeframe='H1', set_sha256=CELL_SET)])

    def test_no_file_binds_nothing_and_no_evidence_root_is_not_configured(self):
        self.assertEqual(self.read()['state'], 'absent')
        (self.root / 'evidence' / 'heldout').mkdir(parents=True)       # a present root without locks.jsonl: no locks
        self.assertEqual((self.read()['state'], self.read()['locks']), ('absent', []))
        (self.root / 'evidence' / 'heldout' / 'locks.jsonl').mkdir()     # present but not a readable file: fail closed
        self.assertEqual(self.read()['state'], 'unavailable')
        (self.root / 'evidence' / 'heldout' / 'locks.jsonl').rmdir()
        self.assertEqual(read_registry(dict(controller_state_root=str(self.root / 'state')))['state'], 'not_configured')
        # The desktop layout needs no installation key: <data>/suite/<id> -> <data>/evidence.
        layout = read_registry(dict(controller_state_root=str(self.root / 'suite' / 'abc')))
        self.assertEqual(layout['path'], str(self.root / 'evidence' / 'heldout' / 'locks.jsonl'))

    def test_any_changed_byte_makes_the_registry_unavailable(self):
        path = write_registry(self.root / 'evidence', golden_events())
        clean = path.read_bytes()
        self.assertEqual(self.read()['state'], 'ok')
        lines = clean.split(b'\n')[:-1]
        for index, line in enumerate(lines):
            for position in (line.index(b'"start"') if b'"start"' in line else 20, len(line) // 2, len(line) - 5):
                changed = bytearray(line)
                changed[position] = ord('7') if changed[position] != ord('7') else ord('8')
                tampered = lines[:index] + [bytes(changed)] + lines[index + 1:]
                path.write_bytes(b'\n'.join(tampered) + b'\n')
                registry = self.read()
                self.assertEqual(registry['state'], 'unavailable', (index, position))
                self.assertIn('line %d' % (index + 1), registry['error'])
        for broken in (clean[:-1], clean.replace(b'","', b'", "', 1), clean + b'\n', b'\n'.join(lines[1:]) + b'\n',
                       b'\xff' + clean):
            path.write_bytes(broken)
            self.assertEqual(self.read()['state'], 'unavailable', broken[:40])

    def test_impossible_lock_histories_fail_closed(self):
        alpha = declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30')
        again = declaration('alpha', '2026-11-02', '2027-02-01', '2027-01-29')
        freeze = dict(lockId=alpha['lockId'], cells=[dict(symbol='EURUSD', timeframe='H1', setSha256=CELL_SET)])
        bad_id = dict(alpha, lockId='d' * 64)
        floaty = declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30') | dict(weeks=13.0)
        floaty['lockId'] = lock_id(floaty)
        for events, reason in (
                ([('declare', alpha, NOW_AT), ('declare', again, NOW_AT)], 'already has an active lock'),
                ([('declare', alpha, NOW_AT), ('reveal', dict(lockId=alpha['lockId']), NOW_AT)], 'reveal needs a frozen'),
                ([('freeze', freeze, NOW_AT)], 'undeclared'),
                ([('declare', bad_id, NOW_AT)], 'lockId is not'),
                ([('declare', floaty, NOW_AT)], 'non-integer'),
                ([('declare', alpha, NOW_AT), ('freeze', freeze, NOW_AT), ('reveal', dict(lockId=alpha['lockId']), NOW_AT),
                  ('revealed', dict(lockId=alpha['lockId']), NOW_AT), ('breach', dict(lockId=alpha['lockId']), NOW_AT)],
                 'cannot be breached')):
            write_registry(self.root / 'evidence', events)
            registry = self.read()
            self.assertEqual(registry['state'], 'unavailable', reason)
            self.assertIn(reason, registry['error'])

    def test_lifecycle_statuses_and_which_bind(self):
        alpha = declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30')
        freeze = dict(lockId=alpha['lockId'], cells=[dict(symbol='EURUSD', timeframe='H1', setSha256=CELL_SET)])
        ref = dict(lockId=alpha['lockId'])
        steps = [('declare', alpha, NOW_AT), ('freeze', freeze, NOW_AT), ('reveal', ref, NOW_AT), ('revealed', ref, NOW_AT)]
        expected = ['locked', 'locked', 'revealing', 'revealed']
        for count, status in zip(range(1, 5), expected):
            write_registry(self.root / 'evidence', steps[:count])
            lock = self.read()['locks'][0]
            self.assertEqual((lock['status'], lock['active']), (status, status != 'revealed'))
        self.assertEqual(self.read(datetime(2026, 11, 7, 12, tzinfo=timezone.utc))['locks'][0]['status'], 'revealed')
        write_registry(self.root / 'evidence', steps[:1])
        self.assertEqual(self.read(datetime(2026, 11, 7, 12, tzinfo=timezone.utc))['locks'][0]['status'], 'revealable')
        write_registry(self.root / 'evidence', steps[:1] + [('breach', dict(ref, reason='late import'), NOW_AT)])
        lock = self.read()['locks'][0]
        self.assertEqual((lock['status'], lock['active']), ('breached', False))
        # After the breach the key may declare again: the window can never earn L4 anyway.
        write_registry(self.root / 'evidence', steps[:1] + [('breach', ref, NOW_AT),
                                                            ('declare', declaration('alpha', '2026-11-02', '2027-02-01', '2027-01-29'), NOW_AT)])
        self.assertEqual(self.read()['state'], 'ok')

    def test_scrub_removes_metric_tokens_from_names_and_log_lines(self):
        cases = {
            'GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set':
                'GOAT V1.49 USDCHF,M1_Trds=locked_Prf=locked_DD=locked_PF=locked_SR=locked_ARF=locked.set',
            'x_N500_AvgFit=1.91_Health=97.2_Zero=3_AvgTrades=48.1_Best=2.47.xml':
                'x_N500_AvgFit=locked_Health=locked_Zero=locked_AvgTrades=locked_Best=locked.xml',
            'base_CombinedRows_Score=61.7.xml': 'base_CombinedRows_Score=locked.xml',
        }
        for raw, expected in cases.items():
            self.assertEqual(scrub(raw), expected)
        b40 = ('Tested 161 settings on USDJPY H1 in 2026.04.01 to 2026.08.01: 3 were profitable with 50+ trades in-sample but '
               'none scored 60+ once the forward period to 2026.10.02 was included (best 61.7). A result for this window, not an error.')
        no_edge = 'DEINIT: Tested 161 settings on USDJPY H1 in 2026.04.01 to 2026.08.01: none was profitable with 50+ trades (best profit -254.50). No exports.'
        details = 'outcome=no_profitable_passes;best_profit=48.10;best_score=0.3700;best_combined_score=61.7'
        for line in (b40, no_edge, details, '; BOOS: 2024.12.26-2025.06.26 Days=129 Trades=42 PL=440',
                     'Finished reading & matching Back/Forward data. Found rows = 7311'):
            self.assertEqual(leaks(scrub(line)), [], scrub(line))
            self.assertNotIn('PL=440', scrub(line))
        self.assertIn('2026.04.01 to 2026.08.01', scrub(b40))      # dates and counts that are not results stay


class EnforcementTests(unittest.TestCase):
    """Real prepare-batch / run-batch / dispatch against a private synthetic installation."""

    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.evidence = self.fixture.root / 'desktop evidence'
        self.fixture.receipt['evidence_root'] = str(self.evidence)
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        self.source = self.fixture.root / 'Template.set'
        self.source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        clock = patch('studio_evidence_end._utc', side_effect=lambda now: NOW if now is None else REAL_UTC(now))
        clock.start(); self.addCleanup(clock.stop)

    def ref(self, key='alpha'):
        return dict(strategy_key=key, template_id=key, template_revision='r' + key, template_sha256='e' * 64,
                    catalog_revision='goat-beta-2026.09.26-v149-candidate.1')

    def plan(self, name, refs=(None, None)):
        members = []
        for symbol, ref in zip(('EURUSD.customer', 'GBPUSD.customer'), refs):
            member = dict(set_path=str(self.source), tester=self.fixture.tester | {'Symbol': symbol})
            if ref is not None:
                member['strategy_ref'] = ref
            members.append(member)
        path = self.fixture.root / (name + '.json')
        path.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=members)), encoding='utf-8')
        return path

    def lock(self, key='alpha', start='2026-08-03', end='2026-11-02', reveal_after='2026-10-30'):
        write_registry(self.evidence, [('declare', declaration(key, start, end, reveal_after), NOW_AT)])

    def assertNothingStaged(self, name):
        self.assertFalse((self.c.root / 'packages' / name).exists())
        self.assertEqual([j['job_id'] for j in self.c.state()['queue'] if j['job_id'] == name], [])

    def test_prepare_refuses_a_member_of_the_locked_strategy_before_anything_is_staged(self):
        self.lock()
        with self.assertRaises(HeldOutRefused) as refused:
            prepare_batch(self.c, 'alpha-batch', self.plan('alpha-batch', (self.ref(), self.ref())))
        self.assertEqual(refused.exception.code, 'HELDOUT_LOCKED_WINDOW')
        self.assertIn('stays locked until its Prove reveal. Member 1 (EURUSD.customer M15) tests 2026-01-01', refused.exception.plain)
        self.assertIn('End its dates before 2026-08-03, or reveal the lock.', refused.exception.plain)
        self.assertEqual(refused.exception.locked_windows[0]['strategy_key'], 'alpha')
        self.assertNothingStaged('alpha-batch')

    def test_a_member_without_strategy_ref_is_refused_when_it_overlaps_any_lock(self):
        self.lock()
        with self.assertRaises(HeldOutRefused) as refused:
            prepare_batch(self.c, 'loose-batch', self.plan('loose-batch'))
        self.assertEqual(refused.exception.code, 'HELDOUT_UNATTRIBUTED_MEMBER')
        self.assertIn('strategy_ref', refused.exception.plain)
        self.assertNothingStaged('loose-batch')

    def test_another_strategy_or_a_window_before_the_lock_prepares_and_binds_its_strategy(self):
        self.lock()
        result = prepare_batch(self.c, 'beta-batch', self.plan('beta-batch', (self.ref('beta'), self.ref('beta'))))
        plan = json.loads((Path(result['package']) / 'studio-plan.json').read_text(encoding='utf-8'))
        self.assertEqual([r['strategy_key'] for r in plan['strategy_refs']], ['beta', 'beta'])
        source = json.loads((self.c.root / 'packages' / 'beta-batch.source.json').read_text(encoding='utf-8'))
        self.assertEqual(source['members'][0]['strategy_ref']['strategy_key'], 'beta')
        self.lock(start='2025-06-02', end='2025-09-01', reveal_after='2025-08-29')   # wholly before BackOOSDate
        prepare_batch(self.c, 'alpha-early', self.plan('alpha-early', (self.ref(), self.ref())))

    def test_a_successor_keeps_each_members_strategy_ref(self):
        prepare_batch(self.c, 'beta-batch', self.plan('beta-batch', (self.ref('beta'), self.ref('gamma'))))
        state = self.c.state()
        for job in state['queue']:
            if job['job_id'] == 'beta-batch':
                job['status'] = 'cancelled'
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.c.store.db.commit()
        from studio_batch import resume_batch
        result = resume_batch(self.c, 'beta-batch', 'beta-batch-r1')
        plan = json.loads((Path(result['package']) / 'studio-plan.json').read_text(encoding='utf-8'))
        self.assertEqual([r['strategy_key'] for r in plan['strategy_refs']], ['beta', 'gamma'])
        self.lock('gamma')      # the successor is refused for the member of the now-locked strategy
        with self.assertRaises(HeldOutRefused) as refused:
            resume_batch(self.c, 'beta-batch', 'beta-batch-r2')
        self.assertIn('Member 2 (GBPUSD.customer M15)', refused.exception.plain)

    def test_a_plan_without_any_strategy_ref_keeps_its_frozen_identity_when_no_lock_binds(self):
        result = prepare_batch(self.c, 'legacy-batch', self.plan('legacy-batch'))
        plan = json.loads((Path(result['package']) / 'studio-plan.json').read_text(encoding='utf-8'))
        self.assertNotIn('strategy_refs', plan)

    def test_an_unverifiable_registry_refuses_every_prepare(self):
        self.lock()
        path = self.evidence / 'heldout' / 'locks.jsonl'
        path.write_bytes(path.read_bytes().replace(b'alpha', b'alphb'))
        with self.assertRaises(HeldOutRefused) as refused:
            prepare_batch(self.c, 'beta-batch', self.plan('beta-batch', (self.ref('beta'), self.ref('beta'))))
        self.assertEqual(refused.exception.code, 'HELDOUT_REGISTRY_UNAVAILABLE')
        self.assertNothingStaged('beta-batch')

    def test_a_lock_declared_after_prepare_refuses_that_batchs_start(self):
        """Acceptance #5: run-batch (before any journal) and the shared native dispatch hook."""
        prepare_batch(self.c, 'alpha-batch', self.plan('alpha-batch', (self.ref(), self.ref())))
        self.lock()
        from studio_batch_driver import run
        with self.assertRaises(HeldOutRefused) as refused:
            run(self.c, 'alpha-batch', max_seconds=60)
        self.assertEqual(refused.exception.code, 'HELDOUT_LOCKED_WINDOW')
        self.assertFalse((self.c.root / 'batch-drivers' / 'alpha-batch.json').exists())
        from studio_research_authority import before_native_dispatch
        with self.assertRaises(HeldOutRefused):
            before_native_dispatch(self.c, self.c.job('alpha-batch'))
        self.assertEqual(self.c.job('alpha-batch')['status'], 'pending')
        self.assertNotIn('launch_intent', self.c.job('alpha-batch'))

    def test_an_edited_strategy_ref_after_prepare_refuses_the_start(self):
        """Claude-Mac (#1885 5975997350): strategy_ref is read only from the plan its manifest
        hashed; editing it after prepare refuses the start, lock or no lock."""
        result = prepare_batch(self.c, 'alpha-batch', self.plan('alpha-batch', (self.ref(), self.ref())))
        plan_path = Path(result['package']) / 'studio-plan.json'
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        plan['strategy_refs'] = [self.ref('beta'), self.ref('beta')]          # try to step out from under alpha
        plan_path.write_text(json.dumps(plan), encoding='utf-8')
        from studio_batch_driver import run
        from studio_research_authority import before_native_dispatch
        # No lock: the package check every start runs before its journal refuses the edited plan.
        from studio_batch import _verify_package
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            _verify_package(self.c, self.c.job('alpha-batch'))
        with self.assertRaises(ValueError):
            run(self.c, 'alpha-batch', max_seconds=60, restart_consent=True)
        self.assertFalse((self.c.root / 'batch-drivers' / 'alpha-batch.json').exists())
        # A lock on the declared strategy: the held-out check itself refuses the edited plan.
        self.lock('alpha')
        with self.assertRaises(HeldOutRefused) as refused:
            run(self.c, 'alpha-batch', max_seconds=60)
        self.assertEqual(refused.exception.code, 'HELDOUT_PLAN_MISMATCH')
        self.assertIn('no longer matches the hash its manifest recorded at prepare', refused.exception.plain)
        with self.assertRaises(HeldOutRefused) as refused:
            before_native_dispatch(self.c, self.c.job('alpha-batch'))
        self.assertEqual(refused.exception.code, 'HELDOUT_PLAN_MISMATCH')
        self.assertFalse((self.c.root / 'batch-drivers' / 'alpha-batch.json').exists())
        self.assertNotIn('launch_intent', self.c.job('alpha-batch'))
        # Replies and the trial journal never trust the edited strategy either.
        self.assertEqual(guard_output(self.c.install, dict(batch_id='alpha-batch', profit=1990))['profit']['locked'], True)
        from studio_trial_journal import journal
        entries = [e for e in journal(self.c.root, self.c.install)['entries'] if e['batch_id'] == 'alpha-batch']
        self.assertEqual({e['attribution'] for e in entries}, {'unattributed'})
        self.assertIn('frozen plan differs from its manifest hash: declared strategy_refs ignored', entries[0]['gaps'])

    def test_cli_refusal_names_its_code_and_lock_and_nothing_runs(self):
        self.lock()
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), redirect_stdout(output):
            code = goat_studio.main(['--installation', str(self.fixture.path), 'prepare-batch', '--batch-id', 'alpha-cli',
                                     '--plan', str(self.plan('alpha-cli', (self.ref(), self.ref())))])
        reply = json.loads(output.getvalue())
        self.assertEqual((code, reply['ok'], reply['code']), (2, False, 'HELDOUT_LOCKED_WINDOW'))
        self.assertEqual(reply['locked_windows'][0]['start'], '2026-08-03')
        self.assertIn('never work around it', reply['recovery'])

    def test_discover_and_heldout_status_report_the_verified_registry(self):
        self.lock()
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), redirect_stdout(output):
            goat_studio.main(['--installation', str(self.fixture.path), 'discover'])
        capabilities = json.loads(output.getvalue())['result']['capabilities']
        self.assertEqual(capabilities['heldout_enforcement']['registry'], 'ok')
        self.assertTrue(capabilities['trial_journal']['supported'])
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), redirect_stdout(output):
            goat_studio.main(['--installation', str(self.fixture.path), 'heldout-status'])
        status = json.loads(output.getvalue())['result']
        self.assertEqual((status['registry']['state'], status['active'][0]['strategy_key']), ('ok', 'alpha'))
        self.assertIn('stays locked until its Prove reveal', status['plain'])


class RunnerEnforcementTests(unittest.TestCase):
    """Seed hunts and catch-ups (unit level: frozen members as SeedRunner/CatchupRunner build them)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.c = SimpleNamespace(install=dict(controller_state_root=str(root / 'state'), evidence_root=str(root / 'evidence')),
                                 root=root / 'state')
        self.evidence = root / 'evidence'
        clock = patch('studio_evidence_end._utc', side_effect=lambda now: NOW if now is None else REAL_UTC(now))
        clock.start(); self.addCleanup(clock.stop)

    def member(self, alias, symbol='EURUSD', start='2026.06.01', end='2026.09.26', ref=None, source='a' * 64):
        value = dict(member_id=alias + '-id', alias=alias, source_sha256=source, values={'EA_Desc': alias, 'Lots': '0.1'},
                     tester=dict(Symbol=symbol, Period='H1', FromDate=start, ToDate=end))
        if ref:
            value['strategy_ref'] = dict(strategy_key=ref, template_id=ref, template_revision='r', template_sha256='e' * 64,
                                         catalog_revision='c')
        return value

    def test_seed_prepare_refuses_and_seed_start_rechecks_each_member(self):
        write_registry(self.evidence, [('declare', declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30'), NOW_AT)])
        with self.assertRaises(HeldOutRefused) as refused:
            check_seed_jobs(self.c, {}, [self.member('S1', ref='alpha')])
        self.assertEqual(refused.exception.code, 'HELDOUT_LOCKED_WINDOW')
        check_seed_jobs(self.c, {}, [self.member('S1', ref='alpha', end='2026.08.01')])   # ends before the lock
        manifest = dict(members=[self.member('S1', ref='beta'), self.member('S2', ref='alpha')])
        check_runner_start(self.c, manifest, manifest['members'][0])
        with self.assertRaises(HeldOutRefused):
            check_runner_start(self.c, manifest, manifest['members'][1])
        with self.assertRaises(HeldOutRefused):
            check_runner_start(self.c, manifest)

    def test_a_reveal_runs_only_its_frozen_candidate_while_revealing(self):
        alpha = declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30')
        freeze = dict(lockId=alpha['lockId'], cells=[dict(symbol='EURUSD', timeframe='H1', setSha256='a' * 64)])
        ref = dict(lockId=alpha['lockId'])
        plan = dict(heldout_reveal=dict(lock_id=alpha['lockId']))
        target = dict(iso='2026-10-30')
        members = [self.member('C1', ref='alpha', start='2025.06.01', end='2026.10.31')]
        write_registry(self.evidence, [('declare', alpha, NOW_AT), ('freeze', freeze, NOW_AT)])
        with self.assertRaisesRegex(HeldOutRefused, 'starts the reveal'):
            check_catchup(self.c, plan, members, target)
        write_registry(self.evidence, [('declare', alpha, NOW_AT), ('freeze', freeze, NOW_AT), ('reveal', ref, NOW_AT)])
        reveal = check_catchup(self.c, plan, members, target)
        self.assertEqual(reveal, dict(lock_id=alpha['lockId'], strategy_key='alpha', start='2026-08-03', end='2026-11-02'))
        check_runner_start(self.c, dict(members=members, heldout_reveal=reveal))
        for wrong, why in (([self.member('C1', ref='alpha', source='b' * 64, start='2025.06.01', end='2026.10.31')], 'frozen candidate'),
                           ([self.member('C1', ref='beta', start='2025.06.01', end='2026.10.31')], 'strategy_key alpha'),
                           (members + [self.member('C2', symbol='GBPUSD', ref='alpha', start='2025.06.01', end='2026.10.31')], 'frozen candidate')):
            with self.assertRaisesRegex(HeldOutRefused, why):
                check_catchup(self.c, plan, wrong, target)
        with self.assertRaisesRegex(HeldOutRefused, 'through Friday 2026-10-30'):
            check_catchup(self.c, plan, members, dict(iso='2026-10-23'))
        # A plain catch-up of the locked strategy stays refused while the reveal runs.
        with self.assertRaises(HeldOutRefused):
            check_catchup(self.c, {}, members, target)
        write_registry(self.evidence, [('declare', alpha, NOW_AT), ('freeze', freeze, NOW_AT), ('reveal', ref, NOW_AT),
                                       ('revealed', ref, NOW_AT)])
        with self.assertRaises(HeldOutRefused) as refused:
            check_catchup(self.c, plan, members, target)
        self.assertEqual(refused.exception.code, 'HELDOUT_ALREADY_REVEALED')


class LeakWalkTests(unittest.TestCase):
    """Acceptance #4: while a lock is active no surface returns a value derived from its window,
    export file names and log lines included; with no lock every reply is unchanged."""

    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.evidence = self.fixture.root / 'desktop evidence'
        self.fixture.receipt['evidence_root'] = str(self.evidence)
        self.fixture.path.write_text(json.dumps(self.fixture.receipt))
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        source = self.fixture.root / 'Template.set'
        source.write_bytes('EA_Desc=Customer Template\r\nLots=0.1||0.1||0.1||0.3||Y\r\n'.encode('utf-16'))
        clock = patch('studio_evidence_end._utc', side_effect=lambda now: NOW if now is None else REAL_UTC(now))
        clock.start(); self.addCleanup(clock.stop)

        def plan(name, ref):
            members = [dict(set_path=str(source), tester=self.fixture.tester | {'Symbol': 'USDCHF'})]
            if ref:
                members[0]['strategy_ref'] = dict(strategy_key=ref, template_id=ref, template_revision='r', template_sha256='e' * 64,
                                                  catalog_revision='c')
            path = self.fixture.root / (name + '.json')
            path.write_text(json.dumps(dict(schema_version=1, export=self.fixture.exports, members=members)), encoding='utf-8')
            return path
        prepare_batch(self.c, 'locked-batch', plan('locked-batch', None))      # legacy: no strategy named
        prepare_batch(self.c, 'free-batch', plan('free-batch', 'beta'))        # another strategy
        self.completion = self.result_json('locked-batch')
        self.finish_rows({'locked-batch': self.completion, 'free-batch': self.result_json('free-batch')})
        self.seed_and_catchup()
        self.exports = self.fixture.root / 'GOAT'
        shutil.copytree(Path(__file__).parent / 'fixtures' / 'oosc' / 'r8', self.exports / 'r8')

    # ---- fixture shapes (sanitized from this PC's attempts/, seeds/ and the catch-up code) -------------
    def result_json(self, job_id):
        name = 'GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295'
        member = dict(index=0, run_alias='R' + '1' * 20, status='native_completed', symbol='USDCHF', tester=self.fixture.tester)
        report = dict(status='report_pair_verified', index=0, run_alias=member['run_alias'], symbol='USDCHF',
                      evidence=dict(status='PAIR_STRUCTURE_AND_OPTIMIZED_VALUES_VERIFIED', title='GOAT V1.49 USDCHF,M1 2026.02.01-2026.09.01',
                                    back_rows=7311, forward_rows=7311, paired_rows=7311),
                      exports=dict(status='export_inventory_observed', native_threshold_candidate_count=1, files=[dict(
                          name=name, status='native_threshold_candidate',
                          artifacts=[dict(path='C:\\Common\\GOAT\\R1\\deploy\\' + name + '.set', sha256='0' * 64)],
                          native_filename_metrics=dict(Trds=198, Prf=1990, DD=415, PF=3.82, SR=8.73, ARF=0.295),
                          equity_samples=dict(first=dict(balance=10000), last=dict(balance=19907), sampled_equity_drawdown=4153))]))
        return dict(schema_version=1, attempt_id='a' * 64, job_id=job_id, status='completed', member_outcomes=[member],
                    native=dict(observed_at='2026-09-10T12:00:00Z', status='native_completed'),
                    reports=report, research_outcomes=[dict(index=0, outcome='no_profitable_passes', passes=161, best_profit=-254.5,
                                                            best_score=0.37, forward_rows=161,
                                                            summary='USDCHF M1: tested, no edge — best profit -254.50.')],
                    native_error_evidence=dict(status='observed', lines=[dict(log='20261003.log', line=(
                        'GOAT V1.49: Tested 161 settings on USDCHF M1 in 2026.02.01 to 2026.07.01: 3 were profitable with 50+ '
                        'trades in-sample but none scored 60+ once the forward period to 2026.09.01 was included (best 61.7).'))]))

    def finish_rows(self, completions):
        state = self.c.state()
        for job in state['queue']:
            if job['job_id'] in completions:
                job.update(status='completed', completion=completions[job['job_id']],
                           launch_intent=dict(attempt_id='a' * 64, recorded_at='2026-09-02T00:00:00Z'),
                           native_observation=dict(status='verifying', reports=completions[job['job_id']]['reports']),
                           completion_path=str(self.c.root / 'attempts' / ('a' * 64) / 'result.json'))
        binding = packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding))
        self.c.store.db.commit()

    def seed_and_catchup(self):
        tester = dict(Symbol='EURUSD', Period='H1', FromDate='2026.06.01', ToDate='2026.09.26', ForwardMode=0)
        seed = self.c.root / 'seeds' / 'seed-locked'; seed.mkdir(parents=True)
        (seed / 'manifest.json').write_text(json.dumps(dict(batch_id='seed-locked', plan={}, members=[dict(
            member_id='m1', alias='S1', tester=tester, source_sha256='a' * 64, values={'EA_Desc': 'S1'})])), encoding='utf-8')
        catchup = self.c.root / 'catchups' / 'catchup-locked'; catchup.mkdir(parents=True)
        (catchup / 'manifest.json').write_text(json.dumps(dict(batch_id='catchup-locked', plan={}, members=[dict(
            member_id='c1', alias='C1', tester=tester | dict(FromDate='2025.01.01', ToDate='2026.10.03'), source_sha256='b' * 64,
            new_window=dict(first_day='2026.07.01', last_day='2026-10-02'))])), encoding='utf-8')

    def surfaces(self):
        """Every reply shape §4.3 lists, as the controller builds it."""
        xml = 'GOAT V1.49 EURUSD,H1 2026.06.01-2026.09.26 S1_N500_AvgFit=1.91_Health=97.2_Zero=3_AvgTrades=48.1_Best=2.47.xml'
        return dict(
            finish=dict(self.completion),
            research_status=dict(activity=dict(kind='batch', batch_id='locked-batch', status='completed', qualifying=3, exported_sets=3,
                                               no_edge=[self.completion['research_outcomes'][0]],
                                               last_member=dict(exported_sets=3, qualifies=True, summary='best profit 48.10'),
                                               headline='Batch locked-batch: 3 qualifying, best profit 48.10')),
            seed_report=dict(schema_version=1, batch_id='seed-locked', status='completed', members=[dict(
                member_id='m1', alias='S1', symbol='EURUSD', status='completed', actual_frames=500,
                summary=dict(actual_frames=500, average_fitness=1.91, best_fitness=2.47, qualifying_count=4),
                xml_path='C:\\Common\\GOAT\\SeedFarmingXML\\' + xml)]),
            seed_status=dict(batch_id='seed-locked', members=[dict(alias='S1', result=dict(summary=dict(best_fitness=2.47), xml_path=xml))]),
            catchup_report=dict(schema_version=1, batch_id='catchup-locked', counts=dict(held_up=1, weakened=0), members=[dict(
                alias='C1', summary=dict(verdict='held_up', net=1990, dd=415, pf=3.82, trades=198,
                                         plain='+1990, 198 trades, DD 415, PF 3.82; forward pace 48.10 a day'),
                signals=dict(pf=3.82), original_set='C:\\Common\\GOAT\\R8\\deploy\\GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set')]),
            catchup_status=dict(batch_id='catchup-locked', members=[dict(alias='C1', result=dict(summary=dict(net=1990, plain='+1990')))]),
            benchmark=dict(batch_id='locked-batch', members=[dict(index=0, actual_back_report_rows=7311, actual_forward_report_rows=7311)]),
        )

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(goat_studio, 'contracts', return_value=(self.c.schema, self.c.policy)), redirect_stdout(output):
            code = goat_studio.main(['--installation', str(self.fixture.path), *args])
        return code, json.loads(output.getvalue())

    def lock(self, key='alpha'):
        write_registry(self.evidence, [('declare', declaration(key, '2026-08-03', '2026-11-02', '2026-10-30'), NOW_AT)])

    def test_without_an_active_lock_every_reply_is_unchanged(self):
        before = self.cli('batch-status', '--batch-id', 'locked-batch')
        self.assertTrue(leaks(before[1]))                     # the fixture really carries the values
        for value in self.surfaces().values():
            self.assertIs(guard_output(self.c.install, value), value)
        self.lock('alpha')
        write_registry(self.evidence, [('declare', declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30'), NOW_AT),
                                       ('breach', dict(lockId=declaration('alpha', '2026-08-03', '2026-11-02', '2026-10-30')['lockId']), NOW_AT)])
        self.assertEqual(self.cli('batch-status', '--batch-id', 'locked-batch'), before)   # a breached lock binds nothing

    def test_every_surface_redacts_the_locked_run_and_keeps_the_free_one(self):
        free_before = self.cli('batch-status', '--batch-id', 'free-batch')
        self.lock('alpha')
        code, reply = self.cli('batch-status', '--batch-id', 'locked-batch')
        self.assertEqual(code, 0)
        result = reply['result']
        self.assertEqual(leaks(result), [])
        self.assertEqual(result['status'], 'completed')                          # flow control stays readable
        self.assertEqual(result['locked_windows'][0]['strategy_key'], 'alpha')
        self.assertEqual(result['research_outcomes']['locked'], True)
        self.assertIn('Prf=locked', json.dumps(result))
        self.assertEqual(self.cli('batch-status', '--batch-id', 'free-batch'), free_before)
        code, state = self.cli('state')
        rows = {row['job_id']: row for row in state['result']['queue']}
        self.assertEqual(leaks(rows['locked-batch']), [])
        self.assertTrue(leaks(rows['free-batch']))                               # another strategy's values stay
        for name, value in self.surfaces().items():
            self.assertTrue(leaks(value), name)                  # each shape really carries locked values
            redacted = guard_output(self.c.install, value)
            self.assertEqual(leaks(redacted), [], name)
            self.assertTrue(redacted['locked_windows'], name)
            self.assertIn('never work around them', redacted['heldout']['plain'])

    def test_export_file_names_in_evidence_scan_are_redacted(self):
        before = self.cli('evidence-scan', '--source', str(self.exports))
        self.assertIn('Prf=1990', json.dumps(before[1]))
        self.lock('alpha')
        code, reply = self.cli('evidence-scan', '--source', str(self.exports))
        self.assertEqual(code, 0, reply)
        self.assertEqual(leaks(reply['result']), [])
        self.assertNotIn('Prf=1990', json.dumps(reply))
        self.assertEqual(reply['result']['exports'][0]['metrics']['locked'], True)
        # A lock that ends before the export's window leaves it readable.
        write_registry(self.evidence, [('declare', declaration('alpha', '2023-01-02', '2023-04-03', '2023-03-31'), NOW_AT)])
        self.assertEqual(self.cli('evidence-scan', '--source', str(self.exports)), before)

    def test_a_finished_run_without_evidence_end_is_bounded_by_what_it_could_export(self):
        """Its EA exported to its own last Friday when it finished (2026-09-03 inclusive): a lock that
        starts later binds none of its values, though the plan's export end was open."""
        before = self.cli('batch-status', '--batch-id', 'locked-batch')
        write_registry(self.evidence, [('declare', declaration('alpha', '2026-10-05', '2027-01-04', '2027-01-01'), NOW_AT)])
        self.assertEqual(self.cli('batch-status', '--batch-id', 'locked-batch'), before)
        # The same plan never started: nothing was tested, so nothing can be locked.
        self.finish_rows({})
        state = self.c.state()
        for job in state['queue']:
            job.pop('launch_intent', None); job.pop('completion', None); job['status'] = 'pending'
        self.c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?',
                                (packed(state['queue']), packed(dict(terminal_id=self.c.terminal, run_id=self.c.run))))
        self.c.store.db.commit()
        self.lock('alpha')
        reply = guard_output(self.c.install, dict(batch_id='locked-batch', note='x', profit=1990))
        self.assertEqual(reply['profit'], 1990)

    def test_research_status_lists_the_active_locks_of_the_batchs_strategies(self):
        from studio_heldout_guard import run_locks
        self.lock('alpha')
        self.assertEqual([l['strategy_key'] for l in run_locks(self.c.install, self.c.root, 'locked-batch')['active_locks']], ['alpha'])
        self.assertEqual(run_locks(self.c.install, self.c.root, 'free-batch')['active_locks'], [])
        code, reply = self.cli('research-status')
        self.assertEqual(code, 0, reply)
        self.assertEqual(reply['result']['heldout_locks']['registry'], 'ok')
        self.assertEqual(leaks(reply['result']), [])

    def test_a_caught_up_export_row_speaks_for_its_new_weeks_too(self):
        from studio_heldout_guard import _node_span
        row = dict(set_path='C:\\x.set', evidence_start='2025-01-02', evidence_end='2026-07-30', effective_end='2026-09-25')
        self.assertEqual(_node_span(row)['end'].isoformat(), '2026-09-26')
        self.assertEqual(_node_span(dict(row, previous_attempt=dict(verdict='not_comparable')))['end'], heldout.date.max)

    def test_log_lines_and_error_sentences_are_scrubbed(self):
        self.lock('alpha')
        lines = guard_output(self.c.install, dict(batch_id='locked-batch', native_error_evidence=self.completion['native_error_evidence']))
        self.assertEqual(leaks(lines), [])
        self.assertEqual(lines['native_error_evidence']['lines'][0]['line']['locked'], True)
        text = 'Export SET changed while planning: C:\\R8\\GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set'
        self.assertEqual(leaks(guard_error(self.c.install, text)), [])

    def test_an_unverifiable_registry_redacts_every_reply(self):
        self.lock('alpha')
        path = self.evidence / 'heldout' / 'locks.jsonl'
        path.write_bytes(path.read_bytes()[:-1])
        code, reply = self.cli('batch-status', '--batch-id', 'free-batch')
        self.assertEqual(code, 0)
        self.assertEqual(leaks(reply['result']), [])
        self.assertEqual(reply['result']['heldout']['code'], 'HELDOUT_REGISTRY_UNAVAILABLE')
        for name, value in self.surfaces().items():
            self.assertEqual(leaks(guard_output(self.c.install, value)), [], name)

    def test_the_demo_lane_prints_through_the_same_guard(self):
        import demo_agent
        surfaces = self.surfaces()

        class Agent:
            def __init__(agent, installation):
                agent.install, agent.root = self.c.install, self.c.root

            def batch_status(agent, batch_id):
                return dict(surfaces['finish'], batch_id=batch_id)
        self.lock('alpha')
        output = io.StringIO()
        with patch.object(demo_agent, 'DemoAgent', Agent), redirect_stdout(output):
            code = demo_agent.main(['--installation', str(self.fixture.path), 'batch-status', '--batch-id', 'locked-batch'])
        self.assertEqual(code, 0)
        self.assertEqual(leaks(json.loads(output.getvalue())), [])


if __name__ == '__main__':
    unittest.main()
