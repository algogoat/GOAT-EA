"""Fast lane: sealed start verification, rolling baseline, evidence log, stop/continue.

The timing tests prepare a real synthetic 1200-member native package (no MT5) and
fail if sealed start verification regresses past a fixed bound, or stops being
clearly faster than the full semantic pass it replaces.
"""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import packed, sha
from studio_batch import prepare_batch, resume_batch, _verify_package
from studio_batch_seal import seal_path, sealed
from studio_process_check import RollingBaseline

MEMBERS = 1200
# Bounds for the three sealed start-verification passes together. Measured on the
# Claude-PC desktop with the full suite running alongside: 1.9 s for 1200 members
# with 120 inputs each (this fixture uses 20). The unsealed passes measured 5.7 s.
START_VERIFICATION_BOUND_SECONDS = 8.0


def synthetic(fixture, controller, count, inputs=20):
    schema = {'EA_Desc': dict(type='string', optimizable=False)}
    for i in range(inputs):
        schema['P%03d' % i] = dict(type='double', optimizable=True)
    controller.schema = dict(schema_version=1, source_sha256='a' * 64, inputs=schema)
    controller.store.input_schema = controller.schema; controller.store.input_schema_hash = sha(controller.schema)
    folder = fixture.root / 'sets'; folder.mkdir(exist_ok=True)
    members = []
    for m in range(count):
        lines = ['EA_Desc=Member %d' % m] + ['P%03d=%s' % (i, ('%d.5||0.5||0.5||9.5||Y' % m) if i < 2 else '%d.25' % (i + m))
                                            for i in range(inputs)]
        path = folder / ('m%05d.set' % m); path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-16'))
        members.append(dict(set_path=str(path), tester=fixture.tester | {'Symbol': 'SYM%04d' % (m % 50)}))
    plan = fixture.root / ('plan-%d.json' % count)
    plan.write_text(json.dumps(dict(schema_version=1, export=fixture.exports, members=members)), encoding='utf-8')
    return plan


class LargeBatchStartTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.PortableControllerTests(); cls.fixture.setUp()
        cls.c = cls.fixture.bound(); cls.fixture.grant(cls.c)
        started = time.perf_counter()
        prepare_batch(cls.c, 'large', synthetic(cls.fixture, cls.c, MEMBERS))
        cls.prepare_seconds = time.perf_counter() - started
        cls.package = cls.c.root / 'packages' / 'large'

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDown()

    def passes(self):
        """The three start-path verifications that each used to re-parse every member."""
        from studio_launch_intent import record_intent
        from studio_native_request import _validate_material
        c = self.c
        timings = {}
        started = time.perf_counter(); _verify_package(c, c.job('large')); timings['verify_package'] = time.perf_counter() - started
        job = c.job('large')
        digest = hashlib.sha256((self.package / 'manifest.json').read_bytes()).hexdigest()
        snapshot = c.state()
        # Measure the intent's member checks on a private copy of the reserved row.
        reserved = copy.deepcopy(job) | dict(status='reserved', reservation=dict(
            reservation_id='timing', owner='agent', generation=snapshot['generation'], package_sha256=digest))
        class Store:
            input_schema = c.store.input_schema
            db = None
            def transaction(self):
                from contextlib import nullcontext
                return nullcontext()
            def snapshot(self, *args):
                return dict(revision=snapshot['revision'], generation=snapshot['generation'], owner='agent', queue=[reserved])
        class Db:
            def execute(self, *args): return None
        store = Store(); store.db = Db()
        started = time.perf_counter()
        intent = record_intent(store, c.terminal, c.run, 'large', self.package, actor='agent',
                               revision=snapshot['revision'], generation=snapshot['generation'])
        timings['record_intent'] = time.perf_counter() - started
        args = c.native_args(); args.pop('observation_path')
        started = time.perf_counter()
        _validate_material(c.state(), dict(reserved, launch_intent=intent), **args)
        timings['validate_material'] = time.perf_counter() - started
        return timings

    def test_sealed_start_verification_of_1200_members_stays_under_bound(self):
        self.assertTrue(seal_path(self.package).is_file())
        self.assertTrue(sealed(self.package, self.c.job('large'), self.c.schema))
        timings = self.passes()
        total = sum(timings.values())
        print('\nfast-lane timing members=%d prepare=%.1fs sealed=%s total=%.2fs' %
              (MEMBERS, self.prepare_seconds, {k: round(v, 2) for k, v in timings.items()}, total))
        self.assertLess(total, START_VERIFICATION_BOUND_SECONDS)

    def test_zz_stop_settles_a_never_activated_1200_member_start_under_30_seconds(self):
        # Runs last (it consumes the shared package): the g6-r1 shape at full size.
        from studio_launch_intent import record_intent
        from studio_fast_lane import stop
        c = self.c
        job = c.job('large')
        digest = hashlib.sha256((self.package / 'manifest.json').read_bytes()).hexdigest()
        c.submit('queue.reserve', dict(job_id='large', configuration_sha256=job['configuration_sha256'],
                                       package_sha256=digest), 'large-reserve')
        state = c.state()
        record_intent(c.store, c.terminal, c.run, 'large', self.package, actor='agent',
                      revision=state['revision'], generation=state['generation'])
        idle = ({'runtime': dict(tester_state='idle', batch_ongoing=False, account_demo=True)}, {})
        with patch.object(c, 'runtime', return_value=idle):
            started = time.perf_counter()
            result = stop(c, 'large')
            seconds = time.perf_counter() - started
        print('\nfast-lane stop(never-activated, %d members)=%.2fs' % (MEMBERS, seconds))
        self.assertEqual((result['status'], result['kind']), ('cancelled', 'retired_never_activated'))
        self.assertLess(seconds, 30)

    def test_sealed_path_is_clearly_faster_than_the_full_pass_it_replaces(self):
        sealed_total = sum(self.passes().values())
        with patch('studio_batch_seal.sealed', return_value=False):
            full_total = sum(self.passes().values())
        print('\nfast-lane sealed=%.2fs full=%.2fs' % (sealed_total, full_total))
        self.assertLess(sealed_total * 1.5, full_total)


class SealTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'small', synthetic(self.fixture, self.c, 3))
        self.package = self.c.root / 'packages' / 'small'

    def test_any_changed_member_byte_breaks_the_seal_and_full_checks_refuse(self):
        manifest = json.loads((self.package / 'manifest.json').read_text())
        target = self.package / (manifest['jobs'][2]['run_alias'] + '.set'); original = target.read_bytes()
        target.write_bytes(original + b'\x00')
        self.assertFalse(sealed(self.package, self.c.job('small'), self.c.schema))
        with self.assertRaises((ValueError, UnicodeError)):
            _verify_package(self.c, self.c.job('small'))
        target.write_bytes(original)
        self.assertTrue(sealed(self.package, self.c.job('small'), self.c.schema))

    def test_controller_upgrade_of_the_checking_code_invalidates_older_seals(self):
        self.assertTrue(sealed(self.package, self.c.job('small'), self.c.schema))
        with patch('studio_batch_seal.checker_sha256', return_value='0' * 64):
            self.assertFalse(sealed(self.package, self.c.job('small'), self.c.schema))

    def test_forged_or_foreign_seal_falls_back_to_full_checks(self):
        path = seal_path(self.package); value = json.loads(path.read_text())
        value['member_count'] = 99; path.write_text(json.dumps(value))
        self.assertFalse(sealed(self.package, self.c.job('small'), self.c.schema))
        _verify_package(self.c, self.c.job('small'))   # full checks still pass on intact bytes
        other = dict(self.c.schema, source_sha256='b' * 64)
        path.unlink()
        self.assertFalse(sealed(self.package, self.c.job('small'), other))


class RollingBaselineTests(unittest.TestCase):
    def identity(self, pid=11):
        return dict(research=dict(pid=pid, executable='C:/mt5/terminal64.exe', created_utc='t'), protected=None)

    def test_long_start_passes_when_every_gap_is_short(self):
        clock = [1000.0]
        def revalidate(binding, baseline):
            from studio_process_check import revalidate_processes
            with patch('studio_process_check.time.time', return_value=clock[0]), \
                    patch('studio_process_check.inspect_processes', return_value=self.identity() | dict(observed_unix=clock[0])):
                return revalidate_processes(binding, baseline)
        rolling = RollingBaseline({}, self.identity() | dict(observed_unix=1000.0), revalidate=revalidate)
        for _ in range(10):             # 10 x 100 s = 1000 s total, each gap 100 s
            clock[0] += 100; rolling.check()
        clock[0] += 121
        with self.assertRaisesRegex(ValueError, 'stale'):
            rolling.check()

    def test_identity_change_or_precheck_mismatch_refuses(self):
        rolling = RollingBaseline({}, self.identity() | dict(observed_unix=1.0),
                                  revalidate=lambda binding, baseline: self.identity(22) | dict(observed_unix=2.0))
        with self.assertRaisesRegex(ValueError, 'changed'):
            rolling.check()
        with self.assertRaisesRegex(ValueError, 'research terminal process changed'):
            RollingBaseline({}, self.identity(22) | dict(observed_unix=1.0)).take_over(self.identity())


class EvidenceLogTests(unittest.TestCase):
    def test_reconcile_keeps_history_out_of_the_queue_row(self):
        fixture = fixtures.PortableControllerTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        c, native, base, evidence = fixture.activated_fixture()
        c.reconcile('beta-job')
        job = c.job('beta-job')
        self.assertNotIn('native_evidence_history', job)
        log = job['native_evidence_log']
        from studio_evidence_log import read
        entries = read(log['path'])
        self.assertEqual((log['entries'], len(entries)), (1, 1))
        self.assertEqual(entries[0]['attempt_id'], job['launch_intent']['attempt_id'])
        self.assertEqual(hashlib.sha256(Path(log['path']).read_bytes()).hexdigest(), log['last_sha256'])

    def test_compaction_moves_finished_history_with_verified_archive(self):
        fixture = fixtures.PortableControllerTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        c = fixture.bound(); fixture.grant(c)
        prepare_batch(c, 'old', synthetic(fixture, c, 2))
        state = c.state(); job = state['queue'][0]
        history = [dict(native=dict(status='native_ongoing', n=i)) for i in range(50)]
        job.update(status='completed', native_evidence_history=history)
        binding = packed(dict(terminal_id=c.terminal, run_id=c.run))
        c.store.db.execute('UPDATE studio_queues SET jobs=? WHERE binding=?', (packed(state['queue']), binding)); c.store.db.commit()
        from studio_evidence_log import compact, read
        preview = compact(c)
        self.assertFalse(preview['applied']); self.assertEqual(preview['jobs'][0]['entries'], 50)
        self.assertIn('native_evidence_history', c.job('old'))
        done = compact(c, apply=True)
        self.assertLess(done['queue_bytes_after'], done['queue_bytes_before'])
        archive = c.job('old')['native_evidence_archive']
        self.assertNotIn('native_evidence_history', c.job('old'))
        self.assertEqual(read(archive['path']), history)
        self.assertFalse(compact(c, apply=True)['applied'])


class StopContinueTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableControllerTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.c = self.fixture.bound(); self.fixture.grant(self.c)
        prepare_batch(self.c, 'batch', synthetic(self.fixture, self.c, 3))

    def test_stop_cancels_pending_and_is_a_no_op_when_finished(self):
        from studio_fast_lane import stop
        self.assertEqual(stop(self.c, 'batch')['status'], 'cancelled')
        self.assertTrue(stop(self.c, 'batch')['already_settled'])

    def test_stop_releases_an_unpermitted_reservation_then_cancels(self):
        from studio_fast_lane import stop
        job = self.c.job('batch')
        digest = hashlib.sha256((self.c.root / 'packages/batch/manifest.json').read_bytes()).hexdigest()
        self.c.submit('queue.reserve', dict(job_id='batch', configuration_sha256=job['configuration_sha256'],
                                            package_sha256=digest), 'batch-reserve')
        self.assertEqual(stop(self.c, 'batch')['status'], 'cancelled')

    def test_continue_after_build_change_reprepares_under_current_installation(self):
        from studio_fast_lane import stop, continue_batch
        stop(self.c, 'batch')
        binary = self.fixture.data / 'MQL5/Experts/GOAT-EA/GOAT V1.48.ex5'
        binary.write_bytes(b'new per-login EA build')                 # the new EA build
        new_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.c.install = dict(self.c.install, ea_sha256=new_sha)
        with self.assertRaisesRegex(ValueError, 'installation or plan identity changed'):
            resume_batch(self.c, 'batch', 'manual-resume')
        result = continue_batch(self.c, 'batch')
        self.assertEqual((result['batch_id'], result['members']), ('batch-r1', 3))
        self.assertEqual(result['binding_changed_keys'], ['ea_sha256'])
        plan = json.loads((self.c.root / 'packages/batch-r1/studio-plan.json').read_text())
        self.assertEqual(plan['research_binding']['ea_sha256'], new_sha)
        _verify_package(self.c, self.c.job('batch-r1'))                # fully valid under the new build
        lineage = json.loads((self.c.root / 'batch-lineage/batch-r1.json').read_text())
        self.assertEqual(lineage['predecessor_batch_id'], 'batch')
        again = continue_batch(self.c, 'batch')
        self.assertTrue(again['reused'])

    def test_continue_refuses_a_live_batch_with_one_sentence(self):
        from studio_fast_lane import continue_batch
        with self.assertRaisesRegex(ValueError, r'is still pending; stop it first: stop --batch-id batch\.'):
            continue_batch(self.c, 'batch')


if __name__ == '__main__':
    unittest.main()
