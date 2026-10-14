"""Remote deploy v0 on the controller (goatai docs/remote-deploy-design.md section 3.1 and 5; Claude-Mac APPROVE
goatai#2350 6129098775). Fixture-only: the fake EA, fake MT5 process and fake Popen of test_studio_agent_setup, plus a
scripted dashboard on real mailbox files and fake clocks. No MT5 terminal is touched.

- No --timing-profile (and the explicit built-in `desktop`) is the pre-profile controller, byte for byte: the golden
  trace in controller/contracts/deploy-timing-fixtures/desktop-load-golden.json was captured on the unchanged code.
- vps-cold-36 (and any reviewed profile) waits are the ones applied: close, dashboard, child start, link request, ack.
- The link race (T2, T9): a retained `started` receipt and a locked mailbox file are pending until the window ends
  (the Exp 03 prototype's test_link_race.py, ported onto the controller's own _link_children).
- The resume re-check (T5) and resumeAllowed (T6): a resume re-proves the terminal, bytes and registration; past the
  4 h registration age it unwinds, records why, and the next deploy-load is a fresh attempt.
- A crash that is not a ValueError journals `failure` and, after the launch, unwinds (D3).
- refused_before_stage keeps the attempt counter.
- Every deploy-load, deploy-stop and close-terminal journals its observed phase durations (observed_seconds) next to
  the profile, on the waits' own monotonic clock; a duration a failure ended is kept and named in
  observed_cut_by_failure (goatai#2350 6130033743).
- The CLI's --timing-profile on deploy-load, deploy-stop and close-terminal.
"""
import copy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import uuid

import studio_agent_mailbox as mailbox
import studio_agent_setup as agent_setup
import studio_demo_deploy as deploy
import studio_deploy_timing as timing
from studio_refusal import Refusal
from test_studio_agent_setup import BUILD, DeployFixture, FakeMT5, FakeProcess

FIXTURES = Path(__file__).resolve().parent / 'contracts' / 'deploy-timing-fixtures'
GOLDEN = json.loads((FIXTURES / 'desktop-load-golden.json').read_text(encoding='utf-8'))
SHAS = {key: value['sha256'] for key, value in json.loads((FIXTURES / 'profile-cases.json').read_text(encoding='utf-8'))['builtins'].items()}
VPS = timing.PROFILES['vps-cold-36']


class Killed(BaseException):
    """A process kill runs no handler: what a resume test needs to leave a journal mid-phase."""


class Clock:
    """A monotonic clock that only moves when someone waits (or a test says so)."""

    def __init__(self):
        self.t = 0.0
        self.on_tick = None

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.on_tick:
            self.on_tick()


def relative(text, root):
    return str(text).replace(str(root), '<root>')


def staged_digest(path, root):
    """sha256 of a staged file. The resume file and the namespace claim name absolute paths of the temp fixture, so
    their text is hashed with that root replaced; every other staged file is hashed as raw bytes."""
    raw = path.read_bytes()
    if path.suffix == '.tsv' or (path.suffix == '.json' and path.parent.name == 'namespaces'):
        text = raw.decode('utf-16') if path.suffix == '.tsv' else raw.decode('utf-8')
        for base in sorted({str(root), str(Path(root).resolve())}, key=len, reverse=True):
            for variant in (base, base.casefold()):
                text = text.replace(variant.replace('\\', '\\\\'), '<root>').replace(variant, '<root>')
        return 'text:' + hashlib.sha256(text.encode('utf-8')).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def trace_load(case, *, pending_polls=2, **load_kwargs):
    """The desktop happy path with every wait-bearing call recorded (the same capture as the golden's)."""
    calls = dict(requests=[], sleeps=[], closes=[], popen=[])
    real_close = deploy.close_terminal

    def close(controller, attempt_id, **kwargs):
        calls['closes'].append([attempt_id, sorted(kwargs.items())])
        return real_close(controller, attempt_id, **kwargs)

    def request(controller, ident, action, **kwargs):
        calls['requests'].append([action, kwargs.get('timeout')])
        return mailbox.portfolio_request(controller, ident, action, **kwargs)

    root = Path(case.c.root).parent
    case.start_ea(pairing='none', pending_polls=pending_polls)
    with case.relaunch() as launch, patch.object(deploy, 'close_terminal', close):
        result = deploy.load(case.c, case.plan(), mt5=FakeMT5(case.c), request=request, sleep=calls['sleeps'].append, **load_kwargs)
    calls['popen'] = [relative(Path(a), root) if i else 'terminal64' for i, a in enumerate(launch.call_args.args[0])]
    plan = json.loads(case.plan().read_text())
    members = deploy.validate_plan(case.c, case.c.session, plan)
    where = deploy.paths(case.c, plan['deploymentId'])
    for m in members:
        m['path'] = str(where['sets'] / m['name'])
    staged = {relative(path, root): staged_digest(path, root) for path in deploy.staged_bytes(case.c, plan, members)}
    profile = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(where['profile'].iterdir())}
    stable = {k: result[k] for k in ('phase', 'attempt', 'link_result', 'linked_rows', 'profile_format', 'members', 'plan_sha256', 'instruction',
                                     'command_id', 'trading_changed', 'positions_closed', 'startup_sha256', 'pid', 'deployment_id')}
    readback = {k: v for k, v in result['readback'].items() if k not in ('audit_id', 'observed_at_utc', 'registration_sha256')}
    trace = dict(calls=calls, staged=staged, profile=profile, journal_keys=sorted(result), journal=stable, readback=readback,
                 previous_terminal_keys=sorted(result['previous_terminal']), previous_profile_keys=sorted(result['previous_profile']))
    return json.loads(json.dumps(trace)), result


# What a desktop journal gains over the pre-profile golden: the profile (first v0 commit), the observed durations and
# the launched MT5's identity (pid, image, creation time) a resume re-checks (review 6160002799 item 3).
NEW_JOURNAL_FIELDS = ('timing_profile', 'observed_seconds', 'launched_process')
PHASES = {'close', 'launch_observe', 'dashboard_first_answer', 'child_start', 'link', 'ack', 'audit'}


def without_timing_record(trace):
    trace = copy.deepcopy(trace)
    for key in NEW_JOURNAL_FIELDS:
        trace['journal_keys'].remove(key)
    return trace


class Base(DeployFixture):
    def journal(self, deployment='e' * 32):
        return json.loads(deploy.paths(self.c, deployment)['journal'].read_text())

    def registration_path(self):
        return mailbox.portfolio_root(self.c) / 'registration.json'

    def crash_at(self, crash_action, exception=Killed, **load_kwargs):
        """deploy-load until the first `crash_action` request, which raises `exception` instead."""
        def crashing(controller, ident, action, timeout=60):
            if action == crash_action:
                raise exception('controller killed at ' + action)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        with self.relaunch(), self.assertRaises(exception):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=crashing, sleep=lambda s: None, **load_kwargs)


# ======================================================================= timing profiles

class DesktopGolden(Base):
    def test_no_profile_is_byte_identical_to_the_pre_profile_controller(self):
        trace, result = trace_load(self)
        self.assertEqual(without_timing_record(trace), GOLDEN)
        self.assertEqual(result['timing_profile'], dict(id='desktop', sha256=SHAS['desktop'], source='default',
                                                        values=timing.effective(timing.PROFILES['desktop'])))
        # The golden diff, stated: the journal gains exactly these keys and nothing else changes.
        self.assertEqual(set(trace['journal_keys']) - set(GOLDEN['journal_keys']), set(NEW_JOURNAL_FIELDS))
        self.assertEqual(result['launched_process'], dict(pid=77, executable='terminal64.exe', created_utc='2026-10-02T01:00:00+00:00'))
        self.assertEqual(set(GOLDEN['journal_keys']) - set(trace['journal_keys']), set())
        self.assertEqual(set(result['observed_seconds']), PHASES)
        self.assertTrue(all(isinstance(v, float) and v >= 0 for v in result['observed_seconds'].values()))
        self.assertNotIn('observed_cut_by_failure', result)

    def test_the_explicit_desktop_profile_is_the_same_deploy(self):
        profile, _ = timing.load_profile('desktop')
        trace, result = trace_load(self, timing=profile)
        self.assertEqual(without_timing_record(trace), GOLDEN)
        self.assertEqual((result['timing_profile']['id'], result['timing_profile']['sha256'], result['timing_profile']['source']),
                         ('desktop', SHAS['desktop'], 'parameter'))


class VpsWaits(Base):
    def test_the_vps_profile_sets_the_close_wait_and_the_link_request(self):
        trace, result = trace_load(self, timing=copy.deepcopy(VPS))
        calls = trace['calls']
        self.assertEqual(calls['closes'], [['deploy-' + 'e' * 24, [['build_id', 'V1.48-TEST-BUILD-01'], ['wait_seconds', 180]]]])
        self.assertEqual(calls['requests'], [['status', 20], ['link_children', 85], ['link_children', 85], ['link_children', 85],
                                             ['apply_policy', 60], ['status', 20], ['audit', 20]])
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(result['timing_profile'], dict(id='vps-cold-36', sha256=SHAS['vps-cold-36'], source='parameter',
                                                        values=timing.effective(VPS)))
        # Everything else is the desktop deploy: same files, same launch, same readback.
        for key in ('staged', 'profile', 'journal', 'readback'):
            self.assertEqual(trace[key], GOLDEN[key], key)

    def dashboard_silent(self, timing_profile):
        clock = Clock()
        def silent(controller, ident, action, timeout=60):
            if action == 'status':
                clock.t += timeout
                return dict(result='receipt_timeout', id='0' * 32, requestRetained=True)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(ValueError, r'did not answer \(receipt_timeout\)'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=silent, sleep=clock.sleep, clock=clock, timing=timing_profile)
        journal = self.journal()
        self.assertEqual(journal['failure']['code'], 'dashboard_not_ready')
        # The failed phase's duration up to the failure, on the waits' clock, named as cut by the failure.
        self.assertEqual(journal['observed_seconds']['dashboard_first_answer'], round(clock(), 3))
        self.assertEqual(journal['observed_cut_by_failure'], ['dashboard_first_answer'])
        self.assertEqual({'close', 'launch_observe', 'dashboard_first_answer', 'unwind_close'}, set(journal['observed_seconds']))
        return clock()

    def test_a_cold_vps_dashboard_gets_480_s_and_the_desktop_180_s(self):
        waited = self.dashboard_silent(copy.deepcopy(VPS))
        self.assertGreaterEqual(waited, 480); self.assertLess(waited, 480 + 32)

    def test_without_a_profile_the_dashboard_wait_is_still_180_s(self):
        waited = self.dashboard_silent(None)
        self.assertGreaterEqual(waited, 180); self.assertLess(waited, 180 + 32)

    def test_a_cold_vps_link_window_is_480_s_with_85_s_requests(self):
        clock, timeouts = Clock(), []
        def slow(controller, ident, action, timeout=60):
            if action == 'link_children':
                timeouts.append(timeout); clock.t += 10  # a cold dashboard takes its time to answer
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        self.start_ea(pairing='none', unstarted={1})
        with self.relaunch(), self.assertRaisesRegex(ValueError, r'1 of 2 members did not start as linked GOAT charts within 480 s'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=slow, sleep=clock.sleep, clock=clock, timing=copy.deepcopy(VPS))
        self.assertEqual((timeouts[0], max(timeouts)), (85, 85), 'each request asks up to 85 s, the last one what is left')
        self.assertGreaterEqual(clock(), 480); self.assertLess(clock(), 480 + 15)
        journal = self.journal()
        self.assertEqual(journal['phase'], 'stopped')
        self.assertEqual(journal['observed_cut_by_failure'], ['child_start', 'link'], 'child 1 never started')
        self.assertGreaterEqual(journal['observed_seconds']['link'], 480)

    def test_a_reviewed_profiles_ack_wait_is_the_one_applied_and_its_timeout_unwinds(self):
        # A reviewed profile carries its evidence (review 6160002799 item 4: no evidence-null bypass).
        mine = dict(VPS, id='slow-ack', ackWaitSeconds=150)
        clock, started = Clock(), []
        def unacknowledged(controller, ident, action, timeout=60):
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            if action == 'apply_policy':
                started.append(clock())
            elif started and action == 'status':
                clock.t += 5
                receipt = receipt | dict(commandPending=True)
            return receipt
        ea = self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'did not acknowledge the exposure policy in time'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=unacknowledged, sleep=clock.sleep, clock=clock, timing=mine,
                        timing_source='file:' + 'f' * 64)
        waited = clock() - started[0]
        self.assertGreaterEqual(waited, 150); self.assertLess(waited, 150 + 7)
        # Review 6160002799 item 4: an ack timeout unwinds like the other timeouts (no loaded MT5 left with Algo off).
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['auto_unwind']['status'], journal['observed_cut_by_failure']),
                         ('stopped', 'ack_timeout', 'unwound', ['ack']))
        self.assertEqual(ea.shutdowns, 2)
        self.assertEqual(journal['observed_seconds']['ack'], round(waited, 3))
        self.assertEqual(set(journal['observed_seconds']), PHASES - {'audit'} | {'unwind_close'})
        self.assertEqual((self.journal()['timing_profile']['id'], self.journal()['timing_profile']['source']), ('slow-ack', 'file:' + 'f' * 64))

    def test_an_audit_timeout_unwinds_too(self):
        clock = Clock()
        def silent_audit(controller, ident, action, timeout=60):
            if action == 'audit':
                clock.t += timeout
                return dict(result='receipt_timeout', id='0' * 32, requestRetained=True)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        ea = self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(ValueError, r'settings audit did not complete \(receipt_timeout\)'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=silent_audit, sleep=clock.sleep, clock=clock)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['auto_unwind']['status'], journal['observed_cut_by_failure']),
                         ('stopped', 'audit_timeout', 'unwound', ['audit']))
        self.assertEqual(ea.shutdowns, 2)
        self.assertIsNone(deploy.current_deployment(self.c))

    def test_an_invalid_profile_is_refused_before_anything_is_written(self):
        for bad, code in ((dict(VPS, linkRequestSeconds=91), 'TIMING_LINK_REQUEST_OVER_CAP'),
                          (dict(VPS, dashboardWaitSeconds=180), 'TIMING_BELOW_EVIDENCE')):
            with self.subTest(code=code):
                with self.assertRaises(Refusal) as caught:
                    deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), timing=bad)
                self.assertEqual(caught.exception.code, code)
                with self.assertRaises(Refusal):
                    deploy.stop(self.c, 'stop-bad', mt5=FakeMT5(self.c), timing=bad)
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['journal'].exists())
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['state'].exists())

    def test_deploy_stop_closes_with_the_profiles_wait_and_records_it(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        waits = []
        real = deploy.close_terminal
        def close(controller, attempt_id, **kwargs):
            waits.append(kwargs.get('wait_seconds'))
            return real(controller, attempt_id, **kwargs)
        with patch.object(deploy, 'close_terminal', close):
            result = deploy.stop(self.c, 'stop-vps', mt5=FakeMT5(self.c), timing=copy.deepcopy(VPS))
        self.assertEqual((result['status'], waits), ('stopped', [180]))
        self.assertEqual((result['stop_timing_profile']['id'], result['stop_timing_profile']['sha256']), ('vps-cold-36', SHAS['vps-cold-36']))
        self.assertIn('stop_close', result['observed_seconds'])
        self.assertTrue(PHASES <= set(result['observed_seconds']), 'the load\'s own durations are kept')
        self.assertEqual(self.journal()['timing_profile']['source'], 'default', 'the load\'s own record is kept')


# ======================================================================= link race

ROWS = [dict(index=i, linkedFresh=True, chartId=7000 + i, magic=9000 + i) for i in range(3)]


class Dashboard:
    """portfolio_request's observable behaviour on real mailbox files, plus a scripted cold dashboard: the first link
    request is answered `started` at +5 s and finally at `final_at` (None = never); a later request is answered at once.
    The prototype's fake (goatai claude-pc/exp03-vps-lifecycle-lock tools/exp03-vps-deploy/test_link_race.py), with
    envelopes the controller's read-only poll validates."""

    def __init__(self, root, clock, final_at, final='children_linked'):
        self.root, self.clock, self.final_at, self.final = root, clock, final_at, final
        self.requests, self.refusals = [], 0
        clock.on_tick = self.advance

    def receipt_path(self, rid):
        return self.root / (rid + '.json')

    def write_receipt(self, rid, result):
        body = dict(result=result, rows=ROWS if result != 'started' else [], tradingAllowed=False, positions=0, orders=0, connected=True)
        self.receipt_path(rid).write_text(json.dumps(body), encoding='utf-8')

    def advance(self):
        if not self.requests:
            return
        first = self.requests[0]
        if self.clock() >= 5 and not self.receipt_path(first).exists():
            self.write_receipt(first, 'started')
        if self.final_at is not None and self.clock() >= self.final_at:
            if json.loads(self.receipt_path(first).read_text())['result'] == 'started':
                self.write_receipt(first, self.final)
        for later in self.requests[1:]:
            if not self.receipt_path(later).exists():
                self.write_receipt(later, 'children_linked')

    def __call__(self, controller, ident, action, *, timeout=60, **_):
        assert action == 'link_children'
        self.advance()
        pending = self.root / 'request.json'
        if pending.exists():
            rid = json.loads(pending.read_text())['id']
            receipt = self.receipt_path(rid)
            if receipt.exists() and json.loads(receipt.read_text())['result'] == 'started':
                self.refusals += 1
                raise mailbox.UnresolvedMutation(mailbox.UNRESOLVED_MUTATION_MESSAGE)
            pending.rename(self.root / (rid + '.request.json'))
        rid = uuid.uuid4().hex
        pending.write_text(json.dumps(dict(schema=1, id=rid, action='link_children', registrationSha256='a' * 64,
                                           expiresAtUtc=int(time.time()) + 600)), encoding='utf-8')
        self.requests.append(rid)
        end = self.clock() + timeout
        while self.clock() < end:
            self.advance()
            receipt = self.receipt_path(rid)
            if receipt.exists():
                value = json.loads(receipt.read_text())
                if value['result'] != 'started':
                    return value
            self.clock.sleep(0.25 if len(self.requests) > 1 else 1)
        return dict(result='receipt_timeout', id=rid, requestRetained=True)


class LinkRace(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='goat-link-race-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.controller = types.SimpleNamespace(install=dict(common_files_root=str(self.dir), terminal_data_root=r'C:\x\11 - Remote Deploy Proof'))
        self.root = mailbox.portfolio_root(self.controller)
        self.root.mkdir(parents=True)
        self.clock = Clock()

    def link(self, request, read=mailbox.read_bounded):
        return deploy._link_children(self.controller, {}, request=request, sleep=self.clock.sleep, clock=self.clock,
                                     wait_seconds=VPS['childStartWaitSeconds'], request_seconds=VPS['linkRequestSeconds'], read=read)

    def test_a_late_started_receipt_is_pending_until_it_resolves(self):
        dash = Dashboard(self.root, self.clock, final_at=150)
        out = self.link(dash)
        self.assertEqual(out['outcome'], 'linked', out)
        self.assertEqual(dash.refusals, 1, 'the mailbox refused once and the controller waited it out')
        self.assertGreaterEqual(self.clock(), 150); self.assertLess(self.clock(), 480)
        self.assertEqual(len(dash.requests), 2, 'one fresh request after the started receipt resolved')
        self.assertEqual(out['race']['started_waits'], 1)

    def test_a_locked_mailbox_file_while_polling_keeps_polling(self):
        dash = Dashboard(self.root, self.clock, final_at=150)
        flaky = dict(n=0)
        def read(path, limit=16384):
            if self.clock() > 100 and flaky['n'] < 5:
                flaky['n'] += 1
                raise PermissionError(13, 'Permission denied', str(path))
            return mailbox.read_bounded(path, limit)
        out = self.link(dash, read=read)
        self.assertEqual(out['outcome'], 'linked', out)
        self.assertEqual((flaky['n'], dash.refusals), (5, 1))

    def test_started_resolving_inside_one_85_s_request_needs_no_wait(self):
        dash = Dashboard(self.root, self.clock, final_at=60)
        out = self.link(dash)
        self.assertEqual((out['outcome'], dash.refusals, len(dash.requests)), ('linked', 0, 1))
        self.assertNotIn('race', out)

    def test_a_receipt_stuck_at_started_ends_at_the_window_and_is_never_touched(self):
        dash = Dashboard(self.root, self.clock, final_at=None)
        out = self.link(dash)
        self.assertEqual(out['outcome'], 'timeout', out)
        self.assertGreaterEqual(self.clock(), 480); self.assertLess(self.clock(), 480 + 30, 'bounded by the child start window')
        self.assertEqual(json.loads(self.receipt_path(dash, 0).read_text())['result'], 'started', 'the poll never writes or archives')
        self.assertTrue((self.root / 'request.json').exists())
        self.assertEqual(deploy.rows_failed([dict(index=0, name='a.set', symbol='EURUSD')], out['rows'])[0]['reason'], 'child_not_started')

    def receipt_path(self, dash, index):
        return dash.receipt_path(dash.requests[index])

    def test_a_locked_request_and_the_live_request_it_leaves_are_pending(self):
        answers = iter([PermissionError(13, 'Permission denied', 'request.json'),
                        mailbox.RequestStillLive(mailbox.REQUEST_STILL_LIVE_MESSAGE),
                        ValueError(mailbox.REQUEST_STILL_LIVE_MESSAGE),  # an adapter's plain sentence counts too
                        dict(result='children_linked', rows=ROWS, tradingAllowed=False, positions=0, orders=0, connected=True)])
        def request(controller, ident, action, timeout=60):
            answer = next(answers)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        out = self.link(request)
        self.assertEqual(out['outcome'], 'linked', out)
        self.assertEqual(out['race'], dict(started_waits=0, locked_reads=1, live_waits=2))

    def test_every_other_refusal_still_ends_the_link_at_once(self):
        for error in (ValueError('Another GOAT mailbox client is active for this terminal; retry after it finishes'),
                      ValueError('Retained portfolio request belongs to another registration'),
                      FileNotFoundError(2, 'gone')):
            with self.subTest(error=str(error)):
                calls = []
                def refused(controller, ident, action, timeout=60):
                    calls.append(action)
                    raise error
                if isinstance(error, ValueError):
                    out = self.link(refused)
                    self.assertEqual((out['outcome'], len(calls)), ('refused', 1))
                    self.assertIn(str(error)[:30], out['result'])
                else:
                    with self.assertRaises(FileNotFoundError):  # not a lock: a crash, journaled by load() (CrashJournal)
                        self.link(refused)

    def test_the_mailbox_raises_typed_errors_with_the_unchanged_sentences(self):
        self.assertTrue(issubclass(mailbox.UnresolvedMutation, ValueError) and issubclass(mailbox.RequestStillLive, ValueError))
        self.assertEqual(mailbox.UNRESOLVED_MUTATION_MESSAGE, 'An unresolved dashboard mutation is retained; inspect deploy-status before continuing')
        self.assertEqual(mailbox.REQUEST_STILL_LIVE_MESSAGE, 'An unanswered portfolio request is still live; wait for it to expire')
        source = Path(mailbox.__file__).read_text(encoding='utf-8')
        self.assertNotIn("raise ValueError('An unresolved dashboard mutation", source)
        self.assertNotIn("raise ValueError('An unanswered portfolio request", source)


class LinkRaceInLoad(Base):
    def test_a_started_race_during_a_full_load_still_reaches_ready_and_is_journaled(self):
        self.start_ea(pairing='none')
        raced = dict(n=0)
        def racing(controller, ident, action, timeout=60):
            if action == 'link_children' and raced['n'] < 2:
                raced['n'] += 1
                raise mailbox.UnresolvedMutation(mailbox.UNRESOLVED_MUTATION_MESSAGE)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=racing, sleep=lambda s: None, timing=copy.deepcopy(VPS))
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(result['link_race'], dict(started_waits=2, locked_reads=0, live_waits=0))


# ======================================================================= resume re-check and the 4 h rule

class Resume(Base):
    def test_a_resume_at_dashboard_ready_re_checks_and_then_finishes(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        self.assertEqual(self.journal()['phase'], 'dashboard_ready')
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()
        self.assertEqual(result['phase'], 'ready')
        check = result['resume_check']
        self.assertEqual((check['from_phase'], check['ok'], check['terminal_pid']), ('dashboard_ready', True, 77))
        self.assertLess(check['registration_age_seconds'], 120)
        # The resume's own status re-poll (dashboardWaitSeconds) is part of what is needed (review 6160002799 item 4).
        self.assertEqual((check['resume_allowed']['ok'], check['resume_allowed']['neededSeconds']), (True, 660))

    def refused_resume(self, code, *, timing_profile=None, clock=None, registration_kept=False):
        with self.relaunch() as launch, self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=(clock.sleep if clock else lambda s: None),
                        clock=clock or time.monotonic, timing=timing_profile)
        launch.assert_not_called()
        self.assertEqual(caught.exception.code, code)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['resume_check']['code'], journal['resume_check']['ok']),
                         ('stopped', code, code, False))
        self.assertEqual(journal['auto_unwind']['status'], 'unwound')
        if registration_kept:
            # Review 6160002799 item 3: a registration that is not this deployment's own is never renamed aside.
            self.assertTrue(self.registration_path().exists(), 'a registration GOAT did not write is left in place')
            self.assertTrue(journal['mailbox_left_in_place'])
        else:
            self.assertFalse(self.registration_path().exists(), 'the retained registration is set aside, never reused')
        self.assertIn('Run deploy-load again to retry', str(caught.exception))
        return journal, str(caught.exception)

    def aged(self, seconds):
        """deploy-load's wall clock moved on by `seconds`: the registration file is untouched, so it stays this deployment's."""
        real = time.time
        return patch.object(deploy, 'time', types.SimpleNamespace(time=lambda: real() + seconds, monotonic=time.monotonic, sleep=time.sleep))

    def test_a_resume_past_the_4_h_registration_unwinds_records_why_and_the_next_load_is_fresh(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children', timing=copy.deepcopy(VPS))
        with self.aged(timing.REGISTRATION_SECONDS - 600):  # registered 3 h 50 min ago
            journal, message = self.refused_resume('RESUME_REGISTRATION_TOO_OLD', timing_profile=copy.deepcopy(VPS))
        rule = journal['resume_check']['resume_allowed']
        self.assertEqual((rule['ok'], rule['neededSeconds']), (False, 1200))
        self.assertLessEqual(rule['leftSeconds'], 600)
        self.assertGreaterEqual(journal['resume_check']['registration_age_seconds'], 13790)
        self.assertIn('the retained registration would expire before the deploy can finish', message)
        self.assertEqual(ea.shutdowns, 2, 'the inert MT5 was closed once more to unwind')
        # The next deploy-load is a fresh attempt with a new 4 h registration, once MT5 is open again.
        ea.rows = []
        self.process.identity = FakeProcess().identity
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, timing=copy.deepcopy(VPS))
        launch.assert_called_once()
        self.assertEqual((result['phase'], result['attempt']), ('ready', 2))
        fresh = json.loads(self.registration_path().read_text())
        self.assertGreater(fresh['expiresAtUtc'], int(time.time()) + 14400 - 120)

    def test_the_desktop_rule_needs_660_s_of_registration(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        with self.aged(timing.REGISTRATION_SECONDS - 600):  # 600 s left: enough before, not with the status re-poll
            journal, _ = self.refused_resume('RESUME_REGISTRATION_TOO_OLD')
        self.assertEqual(journal['resume_check']['resume_allowed']['neededSeconds'], 180 + 240 + 60 + 90 + 90)

    def test_a_missing_registration_is_an_unknown_age(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        self.registration_path().rename(self.registration_path().with_name('registration.json.moved'))
        self.refused_resume('RESUME_AGE_UNKNOWN', registration_kept=False)

    def test_a_registration_that_changed_is_refused_and_left_in_place(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children')
        registration = json.loads(self.registration_path().read_text())
        registration['aiThreshold'] = 51
        foreign = json.dumps(registration, separators=(',', ':'))
        self.registration_path().write_text(foreign)
        self.refused_resume('RESUME_REGISTRATION_CHANGED', registration_kept=True)
        self.assertEqual(self.registration_path().read_text(), foreign, 'byte for byte, never renamed or rewritten')
        self.assertEqual(ea.shutdowns, 2, 'only the MT5 this deployment launched (pid and creation time) is closed')

    def test_a_too_old_registration_that_is_not_ours_is_left_in_place(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        registration = json.loads(self.registration_path().read_text())
        registration['expiresAtUtc'] = int(time.time()) + 300  # not the bytes this deployment registered
        self.registration_path().write_text(json.dumps(registration, separators=(',', ':')))
        self.refused_resume('RESUME_REGISTRATION_TOO_OLD', registration_kept=True)

    def test_the_resume_unwind_closes_only_the_mt5_it_proved(self):
        # The proven identity reaches close_terminal, which re-checks it right before its close.
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        seen = []
        real = deploy.close_terminal
        def close(controller, attempt_id, **kwargs):
            seen.append(kwargs.get('expected_process'))
            return real(controller, attempt_id, **kwargs)
        with patch.object(deploy, 'close_terminal', close), self.aged(timing.REGISTRATION_SECONDS - 300):
            self.refused_resume('RESUME_REGISTRATION_TOO_OLD')
        self.assertEqual(seen, [dict(pid=77, executable='terminal64.exe', created_utc='2026-10-02T01:00:00+00:00')])

    def test_a_terminal_gone_since_the_launch_is_waited_for_then_unwound_without_a_close(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children')
        self.process.identity = None
        clock = Clock()
        self.refused_resume('RESUME_TERMINAL_GONE', clock=clock)
        self.assertGreaterEqual(clock(), deploy.LAUNCH_OBSERVE_SECONDS, 'observed for launchObserveSeconds first')
        self.assertEqual(ea.shutdowns, 1, 'nothing to close')

    def changed_terminal(self, ea, from_phase):
        """Review 6160002799 item 3: an MT5 GOAT did not launch is refused with no mutation at all."""
        where = deploy.paths(self.c, 'e' * 32)
        registration = self.registration_path().read_bytes() if self.registration_path().exists() else None
        with self.relaunch() as launch, self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()
        self.assertEqual(caught.exception.code, 'RESUME_TERMINAL_CHANGED')
        self.assertIn('GOAT closed, unloaded and renamed nothing', str(caught.exception))
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['resume_check']['code']),
                         (from_phase, 'RESUME_TERMINAL_CHANGED', 'RESUME_TERMINAL_CHANGED'))
        self.assertNotIn('auto_unwind', journal)
        self.assertEqual(ea.shutdowns, 1, 'never closed: only the deploy\'s own first close happened')
        self.assertEqual(self.process.closed, []); self.assertIsNotNone(self.process.identity, 'that MT5 keeps running')
        self.assertTrue(where['state'].exists() and where['profile'].exists(), 'nothing renamed aside')
        if registration is not None:
            self.assertEqual(self.registration_path().read_bytes(), registration)
        return journal

    def test_a_different_mt5_process_is_never_resumed_or_touched(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children')
        self.process.identity = dict(pid=99, executable='terminal64.exe', created_utc='2026-10-02T02:00:00+00:00')
        journal = self.changed_terminal(ea, 'dashboard_ready')
        self.assertEqual(journal['resume_check']['terminal_pid'], 99)

    def test_the_same_pid_with_another_creation_time_is_another_process(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children')
        self.process.identity = dict(pid=77, executable='terminal64.exe', created_utc='2026-10-02T03:00:00+00:00')  # a reused pid
        journal = self.changed_terminal(ea, 'dashboard_ready')
        self.assertEqual((journal['resume_check']['terminal_pid'], journal['resume_check']['terminal_created_utc']),
                         (77, '2026-10-02T03:00:00+00:00'))

    def test_a_set_changed_after_the_launch_is_never_resumed(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        where = deploy.paths(self.c, 'e' * 32)
        target = next(where['sets'].iterdir())
        target.write_bytes(target.read_bytes() + b'X')
        self.refused_resume('RESUME_BYTES_CHANGED')

    def test_a_resume_at_registered_re_checks_the_terminal_too(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('status')
        self.assertEqual(self.journal()['phase'], 'registered')
        self.process.identity = dict(pid=99, executable='terminal64.exe', created_utc='2026-10-02T02:00:00+00:00')
        self.changed_terminal(ea, 'registered')

    def test_a_resume_that_finds_algo_trading_on_is_never_linked(self):
        ea = self.start_ea(pairing='none')
        self.crash_at('link_children')
        ea.algo = True
        with self.relaunch(), self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(caught.exception.code, 'RESUME_NOT_INERT')
        self.assertIn('GOAT could not unload it', str(caught.exception))
        self.assertNotIn(self.journal()['phase'], ('attached', 'ready'))
        self.assertEqual(ea.link_requests, 0)


# ======================================================================= crash journaling

class CrashJournal(Base):
    def run_crash(self, crash):
        ea = self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=crash, sleep=lambda s: None)
        return ea, caught.exception

    def test_a_runtime_error_mid_link_journals_failure_and_unwinds(self):
        def crash(controller, ident, action, timeout=60):
            if action == 'link_children':
                raise RuntimeError('bug in a fake')
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        ea, exc = self.run_crash(crash)
        self.assertEqual(exc.code, 'DEPLOY_CONTROLLER_CRASH')
        self.assertIsInstance(exc.__context__, RuntimeError)
        self.assertIn('RuntimeError: bug in a fake', str(exc)); self.assertIn('GOAT closed MT5 with Algo Trading off', str(exc))
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['failure']['phase'], journal['failure']['exception']),
                         ('stopped', 'controller_crash', 'dashboard_ready', 'RuntimeError'))
        self.assertEqual((journal['auto_unwind']['status'], journal['stop_reason']), ('unwound', 'controller_crash'))
        self.assertEqual(journal['observed_cut_by_failure'], ['child_start', 'link'])
        self.assertIn('unwind_close', journal['observed_seconds'])
        self.assertEqual(ea.shutdowns, 2); self.assertIsNone(self.process.identity)
        self.assertIsNone(deploy.current_deployment(self.c))

    def test_a_key_error_while_applying_the_policy_unwinds_too(self):
        def crash(controller, ident, action, timeout=60):
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            return dict(result='policy_dispatched') if action == 'apply_policy' else receipt  # no commandId: KeyError
        ea, exc = self.run_crash(crash)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['phase'], journal['failure']['exception']), ('stopped', 'attached', 'KeyError'))
        self.assertEqual(ea.shutdowns, 2)

    def test_a_crash_before_the_launch_journals_failure_and_resumes_the_same_plan(self):
        ea = self.start_ea(pairing='none')
        with self.relaunch() as launch, patch.object(deploy, 'saved_launch_policy', side_effect=RuntimeError('disk gone')), \
                self.assertRaisesRegex(RuntimeError, 'disk gone'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['failure']['phase']), ('closed', 'controller_crash', 'closed'))
        self.assertNotIn('auto_unwind', journal)
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        self.assertNotIn('failure', result)
        self.assertEqual([f['message'] for f in result['earlier_failures']], ['RuntimeError: disk gone'])
        self.assertEqual(ea.shutdowns, 1)

    def test_a_crash_writing_a_phase_never_journals_the_unwritten_phase(self):
        real, crashed = deploy.write_json, []
        def crash_once(path, value):
            if value.get('phase') == 'staged' and 'failure' not in value and not crashed:
                crashed.append(True); raise RuntimeError('power loss')
            return real(path, value)
        with patch.object(deploy, 'write_json', crash_once), self.assertRaisesRegex(RuntimeError, 'power loss'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['phase']), ('validated', 'validated'))

    def test_a_crash_inside_the_auto_unwind_never_unwinds_twice_and_keeps_the_first_failure(self):
        # Review 6160002799 item 2: dashboard_not_ready unwinds, and the unwind's close itself raises a non-ValueError.
        clock, closes = Clock(), []
        def silent(controller, ident, action, timeout=60):
            if action == 'status':
                clock.t += timeout
                return dict(result='receipt_timeout', id='0' * 32, requestRetained=True)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        def close(controller, attempt_id, **kwargs):
            closes.append(attempt_id)
            if attempt_id.startswith('unwind-'):
                raise RuntimeError('bug in the unwind close')
            return deploy.close_terminal(controller, attempt_id, **kwargs)
        self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(RuntimeError, 'bug in the unwind close'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=silent, close=close, sleep=clock.sleep, clock=clock)
        self.assertEqual(len([c for c in closes if c.startswith('unwind-')]), 1, 'close is called once: never a second unwind')
        journal = self.journal()
        self.assertEqual(journal['failure']['code'], 'dashboard_not_ready', 'the first failure is kept, not controller_crash')
        self.assertEqual((journal['auto_unwind']['status'], journal['auto_unwind']['exception']), ('failed', 'RuntimeError'))
        self.assertIn('RuntimeError: bug in the unwind close', journal['auto_unwind']['error'])
        self.assertEqual(journal['phase'], 'registered')

    def test_an_unwind_after_the_launch_never_closes_a_foreign_mt5(self):
        # Review 6161742880: the MT5 this deployment launched was replaced (another pid and creation time) while the
        # dashboard wait ran. The unwind refuses with nothing closed or set aside, and the journal says why.
        clock = Clock()
        foreign = dict(pid=91, executable='terminal64.exe', created_utc='2026-10-02T05:00:00+00:00')
        def replaced(controller, ident, action, timeout=60):
            if action == 'status':
                self.process.identity = foreign
                clock.t += timeout
                return dict(result='receipt_timeout', id='0' * 32, requestRetained=True)
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        ea = self.start_ea(pairing='none')
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'is not the one this deployment launched'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=replaced, sleep=clock.sleep, clock=clock)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['auto_unwind']['status']),
                         ('registered', 'dashboard_not_ready', 'failed'))
        self.assertIn('(pid 91, started 2026-10-02T05:00:00+00:00) is not the one this deployment launched (pid 77', journal['auto_unwind']['error'])
        self.assertEqual((ea.shutdowns, self.process.closed, self.process.identity), (1, [], foreign), 'the foreign MT5 keeps running')
        self.assertTrue(deploy.paths(self.c, 'e' * 32)['state'].exists(), 'nothing was set aside')

    def test_a_popen_crash_keeps_the_inspect_mt5_stop_and_closes_nothing(self):
        # Review 6160002799 item 4: Popen itself raised, so MT5 may or may not have started. Another MT5 the user opened
        # meanwhile is never closed, and the next deploy-load keeps the old stop (never launched twice).
        ea = self.start_ea(pairing='none')
        other = dict(pid=88, executable='terminal64.exe', created_utc='2026-10-02T04:00:00+00:00')
        def failing(*args, **kwargs):
            self.process.identity = other
            raise FileNotFoundError(2, 'The system cannot find the file specified')
        with patch('studio_demo_deploy.subprocess.Popen', side_effect=failing), self.assertRaises(FileNotFoundError):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['failure']['code'], journal['failure']['phase'], journal['failure']['exception']),
                         ('launch_intent', 'controller_crash', 'launch_intent', 'FileNotFoundError'))
        self.assertNotIn('auto_unwind', journal)
        self.assertEqual((ea.shutdowns, self.process.closed, self.process.identity), (1, [], other))
        with self.relaunch() as launch, self.assertRaisesRegex(ValueError, r'inspect MT5 before retrying \(never launched twice\)'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()

    def test_a_kill_runs_no_handler(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        journal = self.journal()
        self.assertEqual(journal['phase'], 'dashboard_ready')
        self.assertNotIn('failure', journal)


class DeployStatus(Base):
    def test_a_live_request_during_a_deploy_wait_is_pending_not_an_error(self):
        # Review 6160002799 item 4: deploy-status while deploy-load waits on its own dashboard, ack or audit request.
        self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        for error, reason in ((mailbox.RequestStillLive(mailbox.REQUEST_STILL_LIVE_MESSAGE), 'request_still_live'),
                              (ValueError(mailbox.REQUEST_STILL_LIVE_MESSAGE), 'request_still_live'),
                              (mailbox.UnresolvedMutation(mailbox.UNRESOLVED_MUTATION_MESSAGE), 'mutation_started')):
            with self.subTest(reason=reason, error=type(error).__name__):
                def busy(controller, ident, action, timeout=60):
                    raise error
                result = deploy.status(self.c, request=busy)
                self.assertEqual(result['dashboard'], dict(result='pending', reason=reason, rows=[]))
                self.assertNotIn('dashboard_error', result)
        def other(controller, ident, action, timeout=60):
            raise ValueError('Retained portfolio request belongs to another registration')
        self.assertEqual(deploy.status(self.c, request=other)['dashboard_error'], 'Retained portfolio request belongs to another registration')


class AttemptCounter(Base):
    def test_refused_before_stage_keeps_the_attempt_so_a_later_deploy_closes_afresh(self):
        ea = self.start_ea(pairing='none', unstarted={1})
        clock = Clock()
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'child_not_started'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=clock.sleep, clock=clock)
        self.assertIsNone(self.process.identity)
        ea.unstarted, ea.rows = set(), []
        with self.assertRaisesRegex(ValueError, 'Open the selected MT5'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual((self.journal()['phase'], self.journal()['attempt']), ('refused_before_stage', 2))
        self.process.identity = FakeProcess().identity
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual((result['phase'], result['attempt']), ('ready', 2))
        self.assertEqual(result['previous_terminal']['close_attempt_id'], 'deploy-' + 'e' * 24 + '-a2', 'a new close, never attempt 1\'s')
        self.assertTrue(launch.call_args.args[0][1].endswith('e' * 32 + '.attempt-2.ini'))
        # And the attempt after that still has a free slot for its kept journal.
        deploy.stop(self.c, 'stop-a2', mt5=FakeMT5(self.c))
        ea.rows = []
        self.process.identity = FakeProcess().identity
        with self.relaunch():
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['attempt'], 3)


# ======================================================================= observed durations

class ObservedDurations(Base):
    def test_each_phase_duration_is_journaled_on_the_waits_own_clock(self):
        clock, links = Clock(), dict(n=0)
        steps = dict(status=7, link_children=13, apply_policy=2, audit=3)
        def timed(controller, ident, action, timeout=60):
            clock.t += steps[action]  # how long the dashboard takes to answer each request
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            if action == 'link_children':
                links['n'] += 1
                if links['n'] == 3:  # every child has started, but the dashboard reports pending once more
                    receipt = receipt | dict(result='children_pending')
            return receipt
        self.start_ea(pairing='none', pending_polls=2)
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=timed, sleep=clock.sleep, clock=clock,
                                 timing=copy.deepcopy(VPS))
        self.assertEqual(result['phase'], 'ready')
        # close and launch take no time on this clock (the fakes are instant); every other value is exact:
        # child start = 3 answers x 13 + 2 polls x 2; link = 4 x 13 + 3 x 2.
        self.assertEqual(result['observed_seconds'], dict(close=0.0, launch_observe=0.0, dashboard_first_answer=7.0, child_start=43.0,
                                                          link=58.0, ack=7.0, audit=3.0))
        self.assertEqual(result['timing_profile']['id'], 'vps-cold-36')
        self.assertNotIn('observed_cut_by_failure', result)
        self.assertEqual(self.journal()['observed_seconds'], result['observed_seconds'])

    def test_a_resume_records_its_own_launch_observation_and_keeps_the_earlier_durations(self):
        self.start_ea(pairing='none')
        self.crash_at('link_children')
        before = self.journal()['observed_seconds']
        self.assertEqual(set(before), {'close', 'launch_observe', 'dashboard_first_answer'}, 'a kill journals what was written')
        self.process.identity = None
        clock = Clock()
        clock.on_tick = lambda: setattr(self.process, 'identity', dict(pid=77, executable='terminal64.exe',
                                                                       created_utc='2026-10-02T01:00:00+00:00')) if clock() >= 4 else None
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=clock.sleep, clock=clock)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(result['observed_seconds']['launch_observe'], 4.0, 'MT5 was listed again after 4 s')
        self.assertEqual(result['observed_seconds']['close'], before['close'])
        self.assertEqual(set(result['observed_seconds']), PHASES)

    def test_close_terminal_journals_its_close_duration_and_profile(self):
        self.start_ea(pairing='none')
        record = timing.load_profile('vps-cold-36')[1]
        result = agent_setup.close_terminal(self.c, 'close-observed', build_id=BUILD, timing_record=record)
        journal = json.loads((Path(self.c.root) / 'terminal-closes' / 'close-observed.json').read_text())
        self.assertEqual(result['phase'], 'stopped')
        self.assertEqual(journal['timing_profile'], record)
        self.assertEqual(set(journal['observed_seconds']), {'close'})
        self.assertGreaterEqual(journal['observed_seconds']['close'], 0)
        self.assertNotIn('observed_cut_by_failure', journal)
        # Without a profile (every other caller), only the duration is added.
        self.process.identity = FakeProcess().identity
        agent_setup.close_terminal(self.c, 'close-plain', build_id=BUILD)
        plain = json.loads((Path(self.c.root) / 'terminal-closes' / 'close-plain.json').read_text())
        self.assertNotIn('timing_profile', plain); self.assertIn('close', plain['observed_seconds'])

    def test_a_close_that_never_exits_records_the_wait_up_to_the_failure(self):
        self.process.close = lambda identity: None  # MT5 ignores the normal close
        ticks = iter(range(0, 10_000, 5))
        result = agent_setup.close_terminal(self.c, 'close-stuck', wait_seconds=30, clock=lambda: next(ticks))
        self.assertEqual(result['status'], 'close_outcome_unresolved')
        journal = json.loads((Path(self.c.root) / 'terminal-closes' / 'close-stuck.json').read_text())
        self.assertEqual((journal['phase'], journal['observed_cut_by_failure']), ('close_issued', ['close']))
        self.assertGreaterEqual(journal['observed_seconds']['close'], 30)
        self.assertLess(journal['observed_seconds']['close'], 30 + 15)


# ======================================================================= CLI

class Cli(Base):
    def main(self, *argv):
        from goat_studio import main
        if self.c.store:
            self.c.store.close(); self.c.store = None
        output = StringIO()
        with redirect_stdout(output):
            code = main(['--installation', str(self.fixture.path), *argv])
        return code, json.loads(output.getvalue())

    def test_the_three_operations_take_a_timing_profile(self):
        from goat_studio import OPERATION_CONTRACTS
        for name in ('close-terminal', 'deploy-load', 'deploy-stop'):
            self.assertIn('timing-profile', OPERATION_CONTRACTS[name]['optional'], name)
            self.assertIn('vps-cold-36', OPERATION_CONTRACTS[name]['timing_profile'])

    def test_an_unknown_or_invalid_profile_is_refused_with_its_code_and_nothing_is_written(self):
        bad = Path(self.c.root) / 'bad-profile.json'
        bad.write_text(json.dumps(dict(VPS, id='too-long-link', linkRequestSeconds=91)))
        for value, code in (('vps-cold', 'TIMING_PROFILE_NOT_FOUND'), (str(bad), 'TIMING_LINK_REQUEST_OVER_CAP')):
            for operation in (['deploy-load', '--plan', str(self.plan())], ['deploy-stop', '--attempt-id', 'stop-1'],
                              ['close-terminal', '--attempt-id', 'close-1']):
                with self.subTest(value=value, operation=operation[0]):
                    exit_code, reply = self.main(*operation, '--timing-profile', value)
                    self.assertEqual((exit_code, reply['ok'], reply['refusal_code']), (2, False, code))
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['journal'].exists())
        self.assertFalse((Path(self.c.root) / 'terminal-closes').exists() and any((Path(self.c.root) / 'terminal-closes').iterdir()))

    def test_the_profile_reaches_each_operation(self):
        seen = {}
        def load(controller, plan, **kwargs):
            seen['load'] = kwargs; return dict(phase='ready')
        def stop(controller, attempt_id, **kwargs):
            seen['stop'] = kwargs; return dict(status='no_live_deployment')
        def close(controller, attempt_id, **kwargs):
            seen['close'] = kwargs; return dict(phase='stopped')
        with patch.object(deploy, 'load', load), patch.object(deploy, 'stop', stop), patch('studio_agent_setup.close_terminal', close):
            self.assertEqual(self.main('deploy-load', '--plan', str(self.plan()), '--timing-profile', 'vps-cold-36')[0], 0)
            self.assertEqual(self.main('deploy-stop', '--attempt-id', 'stop-1', '--timing-profile', 'vps-cold-36')[0], 0)
            code, reply = self.main('close-terminal', '--attempt-id', 'close-1', '--timing-profile', 'vps-cold-36')
            # deploy-load also gets the broker-fit flags from the base (#228), None without them.
            self.assertEqual(seen['load'], dict(manifest_sha256=None, server_time_utc=None, timing=VPS, timing_source='builtin'))
            self.assertEqual(seen['stop'], dict(timing=VPS, timing_source='builtin'))
            self.assertEqual(seen['close'], dict(build_id=None, wait_seconds=180, timing_record=timing.load_profile('vps-cold-36')[1]))
            self.assertEqual(code, 0)
            # Without the flag every call is exactly today's.
            self.main('deploy-load', '--plan', str(self.plan()))
            self.main('deploy-stop', '--attempt-id', 'stop-2')
            code, reply = self.main('close-terminal', '--attempt-id', 'close-2')
        self.assertEqual((seen['load'], seen['stop'], seen['close']), (dict(manifest_sha256=None, server_time_utc=None), {},
                                                                       dict(build_id=None, timing_record=timing.default_record())))
        self.assertEqual(seen['close']['timing_record']['sha256'], SHAS['desktop'])


if __name__ == '__main__':
    unittest.main()
