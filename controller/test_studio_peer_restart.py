"""A restarted protected peer is the same reviewed peer; never inspects or mutates real terminals.

Two MT5 terminals on one PC (Banker and a QA peer) must run independently. The
peer is identified by its reviewed executable, data root and origin binding, not
by the PID of one process instance, once this lane's batch state is isolated.
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import test_goat_studio as fixtures
from campaign_ledger import sha
from studio_batch import prepare_batch, _verify_package
from studio_process_check import (RollingBaseline, classify_processes, restart_tolerant, revalidate_processes,
                                  role_unchanged, verify_research_exited)
from studio_protected_peer import (JOURNAL, apply, binding_fields, comparable, directory, policy, prepare,
                                   process_binding, refresh_process)
from test_studio_fast_lane import synthetic


class PeerFixture(unittest.TestCase):
    version = '1.49'

    def setUp(self):
        self.f = fixtures.PortableControllerTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.c = self.f.bound()
        self.c.install = dict(self.c.install, ea_version=self.version)
        self.exe = self.f.root / 'peer-program/terminal64.exe'; self.exe.parent.mkdir(); self.exe.write_bytes(b'peer')
        self.data = self.f.root / 'peer-data'; (self.data / 'MQL5').mkdir(parents=True)
        (self.data / 'origin.txt').write_text(str(self.exe.parent))
        self.row = dict(ProcessId=7788, ExecutablePath=str(self.exe), CreatedUtc='2026-10-02T20:00:00.0000000Z',
                        Name='terminal64.exe')
        self.rows = [self.row]
        inventory = lambda *a, **k: json.dumps(self.rows)
        for target in ('studio_protected_peer.subprocess.check_output', 'studio_process_check.subprocess.check_output'):
            p = patch(target, side_effect=inventory); p.start(); self.addCleanup(p.stop)

    def register(self):
        return apply(self.c, prepare(self.c, self.exe, self.data)['review_id'], True)

    def restarted(self, pid=7790, created='2026-10-02T22:15:00.0000000Z'):
        return dict(self.row, ProcessId=pid, CreatedUtc=created)

    def journal(self):
        path = directory(self.c) / JOURNAL
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


class PeerRestartTests(PeerFixture):
    def test_restarted_peer_is_accepted_without_review_and_journaled(self):
        self.register()
        reviewed, binding = policy(self.c), self.c.binding()
        self.assertNotIn('protected_process', binding)
        self.assertNotIn('protected_policy_sha256', binding)
        self.assertEqual(binding['protected_peer_sha256'], sha(reviewed['peer']))
        self.rows = [self.restarted()]
        classify_processes(self.rows, binding, observed_unix=1, research_running=False)
        result = refresh_process(self.c)
        self.assertEqual(result['status'], 'restart_accepted')
        self.assertEqual((result['previous_process']['pid'], result['process']['pid']), (7788, 7790))
        self.assertEqual(policy(self.c), reviewed)            # the human review is never rewritten
        self.assertEqual(self.c.binding(), binding)           # and no package identity moves
        [line] = self.journal()
        self.assertEqual((line['event'], line['previous_pid'], line['pid']), ('peer_restart_accepted', 7788, 7790))
        self.assertEqual((line['review_id'], line['peer_sha256']), (reviewed['review_id'], sha(reviewed['peer'])))
        self.assertEqual(refresh_process(self.c)['status'], 'unchanged')
        self.assertEqual(len(self.journal()), 1)
        self.rows = [self.restarted(7795, '2026-10-02T23:00:00.0000000Z')]
        self.assertEqual(refresh_process(self.c)['previous_process']['pid'], 7790)
        self.assertEqual([line['pid'] for line in self.journal()], [7790, 7795])

    def test_closed_then_reopened_peer_never_blocks(self):
        self.register(); binding = self.c.binding()
        self.rows = []
        self.assertEqual(refresh_process(self.c)['status'], 'peer_closed')
        self.assertIsNone(classify_processes(self.rows, binding, observed_unix=1, research_running=False)['protected'])
        self.assertEqual(self.journal(), [])
        self.rows = [self.restarted()]
        self.assertEqual(refresh_process(self.c)['status'], 'restart_accepted')
        self.assertEqual(self.c.binding(), binding)

    def test_foreign_mt5_is_refused(self):
        self.register(); binding = self.c.binding()
        self.rows = [self.restarted(), dict(self.row, ProcessId=9000, ExecutablePath='C:/Other MT5/terminal64.exe')]
        with self.assertRaisesRegex(ValueError, 'Unmapped terminal process'):
            classify_processes(self.rows, binding, observed_unix=1, research_running=False)
        with self.assertRaisesRegex(ValueError, 'Unmapped terminal process'):
            refresh_process(self.c)
        self.assertEqual(self.journal(), [])

    def test_two_processes_of_the_peer_are_refused(self):
        self.register(); binding = self.c.binding()
        self.rows = [self.row, self.restarted()]
        with self.assertRaisesRegex(ValueError, 'one protected terminal'):
            classify_processes(self.rows, binding, observed_unix=1, research_running=False)
        with self.assertRaisesRegex(ValueError, 'one protected terminal'):
            refresh_process(self.c)
        self.assertEqual(self.journal(), [])

    def test_changed_peer_executable_is_refused(self):
        self.register()
        self.rows = [self.restarted()]
        self.exe.write_bytes(b'updated peer build')
        with self.assertRaisesRegex(ValueError, 'changed; review again'):
            refresh_process(self.c)
        with self.assertRaisesRegex(ValueError, 'changed; review again'):
            self.c.binding()
        self.assertEqual(self.journal(), [])

    def test_changed_peer_data_root_is_refused(self):
        self.register()
        self.rows = [self.restarted()]
        (self.data / 'origin.txt').write_text('C:/Another MT5')
        with self.assertRaisesRegex(ValueError, 'origin'):
            refresh_process(self.c)
        (self.data / 'origin.txt').write_text(str(self.exe.parent))
        (self.data / 'MQL5').rmdir()
        with self.assertRaisesRegex(ValueError, 'data root required'):
            self.c.binding()
        self.assertEqual(self.journal(), [])

    def test_process_binding_carries_the_isolation_proof(self):
        self.register()
        binding = process_binding(self.c)
        self.assertTrue(restart_tolerant(binding))
        self.rows = [self.restarted()]
        classify_processes(self.rows, binding, observed_unix=1, research_running=False)

    def test_explicit_review_of_a_closed_peer_refuses(self):
        self.rows = []
        with self.assertRaisesRegex(ValueError, 'closed peer cannot be reviewed'):
            prepare(self.c, self.exe, self.data)


class IsolationGateTests(unittest.TestCase):
    base = dict(research_terminal='C:/Banker/terminal64.exe', research_data_root='G:/Banker',
                protected_terminal='C:/QA/terminal64.exe', protected_data_roots=['C:/Users/x/Terminal/BF13'],
                protected_may_be_stopped=True, ea_version='1.49')

    def test_tolerance_needs_isolation_and_a_separate_namespace(self):
        self.assertTrue(restart_tolerant(self.base))
        for change in (dict(ea_version='1.48'), dict(ea_version=None), dict(protected_may_be_stopped=False),
                       dict(protected_data_roots=['G:/Banker']), dict(protected_data_roots=['g:/banker/']),
                       dict(protected_data_roots=['C:/a', 'C:/b']), dict(protected_data_roots=[]),
                       dict(research_data_root=None), dict(protected_terminal=None)):
            with self.subTest(change=change):
                self.assertFalse(restart_tolerant(dict(self.base, **change)))

    def test_same_namespace_hash_is_not_tolerated(self):
        with patch('studio_terminal_isolation.terminal_hash', return_value='0badf00d'):
            self.assertFalse(restart_tolerant(self.base))

    def test_role_continuity_is_relaxed_only_for_a_tolerant_peer(self):
        old, new = dict(pid=1, executable='C:/QA/terminal64.exe', created_utc='a'), dict(pid=2, executable='C:/QA/terminal64.exe', created_utc='b')
        self.assertTrue(role_unchanged(self.base, 'protected', new, old))
        self.assertTrue(role_unchanged(self.base, 'protected', None, old))
        self.assertFalse(role_unchanged(self.base, 'research', new, old))
        self.assertFalse(role_unchanged(dict(self.base, ea_version='1.48'), 'protected', new, old))


class StrictLaneTests(PeerFixture):
    """A lane without proven batch isolation keeps the exact-instance rule unchanged."""
    version = '1.48'

    def test_restart_still_needs_an_exact_instance_without_isolation(self):
        self.register()
        binding = self.c.binding()
        self.assertEqual(binding['protected_process']['pid'], 7788)
        self.rows = [self.restarted()]
        with self.assertRaisesRegex(ValueError, 'Protected peer process changed'):
            classify_processes(self.rows, binding, observed_unix=1, research_running=False)
        self.assertEqual(refresh_process(self.c)['status'], 'refreshed')
        self.assertEqual(self.journal(), [])

    def test_closed_peer_no_longer_refuses_refresh(self):
        # Formerly "Expected research process state and one protected terminal required".
        self.register()
        self.rows = []
        self.assertEqual(refresh_process(self.c)['status'], 'peer_closed')


class PreparedPackageTests(PeerFixture):
    # The compact fixture schema stages V1.48 packages; the isolation proof is the
    # same restart_tolerant gate, with this fixture's version counted as isolated.
    version = '1.48'

    def setUp(self):
        super().setUp()
        isolated = patch('studio_terminal_isolation.ISOLATED_VERSIONS', frozenset({'1.48', '1.49'}))
        isolated.start(); self.addCleanup(isolated.stop)
        self.register()
        self.f.grant(self.c)

    def test_prepared_package_survives_a_peer_restart(self):
        prepare_batch(self.c, 'chunk', synthetic(self.f, self.c, 3))
        plan = json.loads((self.c.root / 'packages/chunk/studio-plan.json').read_text(encoding='utf-8'))
        self.assertNotIn('protected_process', plan['research_binding'])
        _verify_package(self.c, self.c.job('chunk'))
        self.rows = [self.restarted()]
        self.assertEqual(refresh_process(self.c)['status'], 'restart_accepted')
        _verify_package(self.c, self.c.job('chunk'))
        self.rows = []
        _verify_package(self.c, self.c.job('chunk'))

    def legacy_package(self, batch_id):
        """A package prepared by the previous exact-instance code."""
        with patch('studio_protected_peer.tolerant', return_value=False):
            prepare_batch(self.c, batch_id, synthetic(self.f, self.c, 2))
        plan = json.loads((self.c.root / 'packages' / batch_id / 'studio-plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['research_binding']['protected_process']['pid'], 7788)
        return plan

    def test_package_prepared_before_this_fix_still_verifies_after_a_restart(self):
        self.legacy_package('legacy')
        _verify_package(self.c, self.c.job('legacy'))
        self.rows = [self.restarted()]
        refresh_process(self.c)
        _verify_package(self.c, self.c.job('legacy'))
        # The previous code re-reviewed a restarted peer; its retained review still names this peer.
        apply(self.c, prepare(self.c, self.exe, self.data)['review_id'], True)
        self.assertEqual(policy(self.c)['process']['pid'], 7790)
        _verify_package(self.c, self.c.job('legacy'))

    def test_package_naming_another_peer_or_policy_still_refuses(self):
        self.legacy_package('legacy')
        current = self.c.binding()
        plan = json.loads((self.c.root / 'packages/legacy/studio-plan.json').read_text(encoding='utf-8'))
        recorded = plan['research_binding']
        for index, forged in enumerate((dict(recorded, protected_policy_sha256='f' * 64),
                                        dict(recorded, protected_process=dict(recorded['protected_process'], pid=1)),
                                        dict(recorded, protected_data_roots=['C:/elsewhere']),
                                        dict(recorded, ea_sha256='0' * 64))):
            with self.subTest(index=index):
                left, right = comparable(self.c, forged, current)
                self.assertNotEqual(left, right)
        left, right = comparable(self.c, recorded, current)
        self.assertEqual(left, right)

    def test_changed_peer_bytes_invalidate_the_package(self):
        prepare_batch(self.c, 'chunk', synthetic(self.f, self.c, 2))
        self.exe.write_bytes(b'updated peer build')
        with self.assertRaisesRegex(ValueError, 'review again'):
            _verify_package(self.c, self.c.job('chunk'))


class StartPathTests(PeerFixture):
    """The next start's own process checks across a peer restart (config start route)."""

    def setUp(self):
        super().setUp()
        self.register()
        self.research = dict(ProcessId=5000, ExecutablePath=str(self.f.bin), CreatedUtc='2026-10-02T19:00:00Z',
                             Name='terminal64.exe')
        self.rows = [self.research, self.row]
        self.binding = self.c.binding()

    def inspect(self, binding, research_running=True):
        from studio_process_check import inspect_processes
        return inspect_processes(binding, research_running=research_running)

    def test_rolling_baseline_tolerates_a_peer_restart_but_not_a_research_change(self):
        first = self.inspect(self.binding)
        rolling = RollingBaseline(self.binding, first).take_over(first)
        self.rows = [self.research, self.restarted()]
        rolling.check()
        self.rows = [self.research]
        rolling.check()
        self.rows = [dict(self.research, ProcessId=5001), self.restarted()]
        with self.assertRaisesRegex(ValueError, 'changed'):
            rolling.check()

    def test_research_exit_and_revalidation_tolerate_a_peer_restart(self):
        baseline = self.inspect(self.binding)
        self.rows = [self.research, self.restarted()]
        revalidate_processes(self.binding, baseline)
        self.rows = [self.restarted(7799)]
        verify_research_exited(self.binding, baseline)

    def test_start_records_the_restart_it_saw(self):
        from studio_protected_peer import record_observed
        self.rows = [self.research, self.restarted()]
        seen = self.inspect(self.binding)
        self.assertEqual(record_observed(self.c, self.binding, seen['protected'], source='config_start:x')['status'],
                         'restart_accepted')
        self.assertEqual(self.journal()[-1]['source'], 'config_start:x')

    def test_strict_binding_still_refuses_a_restart_mid_start(self):
        strict = dict(self.binding, ea_version='1.48', protected_process=policy(self.c)['process'])
        baseline = self.inspect(strict)
        self.rows = [self.research, self.restarted()]
        with self.assertRaisesRegex(ValueError, 'Protected peer process changed'):
            revalidate_processes(strict, baseline)


class RunningDriverTests(unittest.TestCase):
    """What an already running driver does when the peer restarts: nothing peer-related.

    The EA advances members natively (MT5's between-member relaunch); the driver
    only reconciles, finishes and watches disk, STOP and pauses. It takes no
    terminal inventory, so a peer restart cannot stop or fail a running batch.
    """

    def test_running_driver_never_inventories_terminals(self):
        from test_studio_batch_driver import Controller
        from studio_batch_driver import run
        with tempfile.TemporaryDirectory() as folder:
            c = Controller(folder)
            calls = []
            def inventory(*args, **kwargs):
                calls.append(args)
                raise AssertionError('running driver took a terminal inventory')
            sleeps = []
            def member_boundary():
                sleeps.append(1)
                if len(sleeps) == 3:
                    c.finished = True   # members advanced natively while the peer restarted
            c.clock.on_sleep = member_boundary
            with patch('studio_batch_driver._verify_package'), \
                    patch('studio_batch_driver.shutil.disk_usage', return_value=type('U', (), {'free': 100 * 1024 ** 3})()), \
                    patch('studio_process_check.subprocess.check_output', side_effect=inventory), \
                    patch('studio_protected_peer.subprocess.check_output', side_effect=inventory):
                result = run(c, 'batch', max_seconds=600, poll_seconds=1, cancel_grace_seconds=2,
                             clock=c.clock, finish_fn=c.finish)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual((c.starts, c.cancels), (1, 0))
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
