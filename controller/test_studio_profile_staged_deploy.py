"""Profile-staged deploy-load and deploy-stop (beta.25, goatai#1885 6033450916). Fixture-only.

The fake EA from test_studio_agent_setup answers link_children by adopting only the children whose chart
file in the staged GOAT-Deploy profile carries the member's symbol, our EA with expertmode 5 and the frozen
SET's inputs, which is what MT5 would have started. No MT5 terminal is touched.

Covers D1 (Enabled=0 always), D2 (AllowLiveTrading reported, never written), D3 (child_not_started then
auto-unwind), the rollback of the previous chart profile, beta.24 journal and schema compatibility.
"""
import itertools
import json
import re
from pathlib import Path
from unittest.mock import patch

import studio_agent_mailbox as mailbox
import studio_demo_deploy as deploy
import studio_deploy_profile as deploy_profile
from studio_refusal import Refusal
from test_studio_agent_setup import BUILD, DeployFixture, FakeMT5, FakeProcess, member

PREVIOUS = 'GOAT-Studio-' + 'c' * 32
DEPLOY_PROFILE = 'GOAT-Deploy-' + 'e' * 16


def fast_clock(step=15):
    """A monotonic clock that jumps `step` seconds per reading, so the 240 s start-up window passes in a few polls."""
    ticks = itertools.count(0, step)
    return lambda: next(ticks)


class ProfileStagedDeployTests(DeployFixture):
    def journal(self, deployment='e' * 32):
        return json.loads(deploy.paths(self.c, deployment)['journal'].read_text())

    def write_common(self, profile_last=PREVIOUS, allow_live=None):
        lines = ['[Common]', 'Login=123456', 'Server=Customer-Demo', '[Charts]', 'ProfileLast=' + profile_last, 'MaxBars=100000',
                 '[Experts]', 'Enabled=0'] + ([] if allow_live is None else ['AllowLiveTrading=' + allow_live]) + ['Account=1', 'WebRequest=1']
        raw = b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')
        (self.data / 'config/common.ini').write_bytes(raw)
        return raw

    def write_previous_profile(self):
        folder = self.data / 'MQL5/Profiles/Charts' / PREVIOUS
        folder.mkdir(parents=True)
        (folder / 'chart01.chr').write_bytes(b'\xff\xfe' + '<chart>\r\nid=133\r\nsymbol=EURUSD\r\n</chart>\r\n'.encode('utf-16-le'))
        (folder / 'order.wnd').write_bytes(b'\x01\x02\x03')
        return folder, {p.name: p.read_bytes() for p in folder.iterdir()}

    def mt5_selects_deploy_profile(self, argv):
        """What MT5 persists while it runs the deploy: common.ini names the deploy profile (one line changes)."""
        ini = self.data / 'config/common.ini'
        ini.write_bytes(ini.read_bytes().replace(('ProfileLast=' + PREVIOUS).encode('utf-16-le'), ('ProfileLast=' + DEPLOY_PROFILE).encode('utf-16-le')))

    # ---------------------------------------------------------------- staging and linking

    def test_the_profile_holds_the_dashboard_and_every_child_and_the_launch_has_no_startup_expert(self):
        ea = self.start_ea(pairing='none')
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        where = deploy.paths(self.c, 'e' * 32)
        plan = json.loads(self.plan().read_text())
        files = {p.name: p.read_bytes() for p in where['profile'].iterdir()}
        members = [dict(name=m['fileName'], symbol=m['symbol'], raw=(where['sets'] / m['fileName']).read_bytes()) for m in plan['members']]
        self.assertEqual(files, deploy_profile.profile_files(self.c.install['ea_relative_path'], plan['policy'], members, 'e' * 32))
        self.assertIn('\r\nStudio_MonitorRunPath=deploy=' + 'e' * 32 + '\r\n</inputs>', deploy_profile.decode_chart(files['chart02.chr']))
        registration = json.loads((mailbox.portfolio_root(self.c) / 'registration.json').read_text())
        self.assertEqual(registration['deploymentId'], 'e' * 32, 'the registration binds the nonce the EA requires')
        dashboard = deploy_profile.parse_chart(files['chart01.chr'])
        self.assertEqual(deploy_profile.audit_inputs(dashboard['inputs'])['Mode_Operation'], '8')
        self.assertEqual(dashboard['expert'], dict(name='GOAT V1.48', path='Experts\\GOAT-EA\\GOAT V1.48.ex5', expertmode='5'))
        config = Path(launch.call_args.args[0][1].removeprefix('/config:')).read_bytes()
        self.assertEqual(config, deploy.startup_config(DEPLOY_PROFILE))
        self.assertFalse((self.data / 'MQL5/Presets/GOAT Dashboard Agent.set').exists(), 'the startup preset is no longer staged')
        journal = self.journal()
        self.assertEqual((journal['profile_format'], journal['attempt'], journal['link_result']), ('profile-staged-v1', 1, 'children_linked'))
        self.assertEqual(journal['linked_rows'], [dict(index=0, chartId=1000, magic=5000), dict(index=1, chartId=1001, magic=5001)])
        self.assertGreaterEqual(ea.link_requests, 1)

    def test_the_registration_binds_the_deployment_and_beta24_registrations_still_validate(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        registration = json.loads((mailbox.portfolio_root(self.c) / 'registration.json').read_text())
        self.assertEqual(registration['deploymentId'], 'e' * 32)
        common = self.c.install['common_files_root']
        mailbox.validate_portfolio_registration(registration, self.ident, common)
        mailbox.validate_portfolio_registration({k: v for k, v in registration.items() if k != 'deploymentId'}, self.ident, common)
        for bad in ('E' * 32, 'e' * 31, 7, None):
            with self.subTest(deploymentId=bad), self.assertRaisesRegex(ValueError, 'deployment'):
                mailbox.validate_portfolio_registration(registration | dict(deploymentId=bad), self.ident, common)
        with self.assertRaisesRegex(ValueError, 'schema'):
            mailbox.validate_portfolio_registration(registration | dict(extra=1), self.ident, common)

    def test_pending_children_are_asked_again_until_every_row_is_linked(self):
        ea = self.start_ea(pairing='none', pending_polls=3)
        sleeps = []
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=sleeps.append)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(ea.link_requests, 4)
        self.assertEqual(sleeps.count(deploy.LINK_POLL_SECONDS), 3)
        self.assertEqual(deploy.CHILD_START_WAIT_SECONDS, 240)

    def test_a_child_that_never_starts_is_named_and_the_deploy_unwinds_itself(self):
        ea = self.start_ea(pairing='none', unstarted={1})
        with self.relaunch(), self.assertRaises(ValueError) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())
        message = str(caught.exception)
        self.assertIn('1 of 2 members did not start as linked GOAT charts within 240 s', message)
        self.assertIn('GOAT V1.48 GBPUSD,M1_Trds1.set (GBPUSD): child_not_started', message)
        self.assertIn('GOAT closed MT5 with Algo Trading off', message); self.assertIn('nothing traded', message)
        journal = self.journal()
        self.assertEqual(journal['phase'], 'stopped')
        self.assertEqual(journal['rows_failed'], [dict(index=1, fileName='GOAT V1.48 GBPUSD,M1_Trds1.set', symbol='GBPUSD', reason='child_not_started')])
        self.assertEqual((journal['failure']['code'], journal['auto_unwind']['status'], journal['stop_reason']),
                         ('child_not_started', 'unwound', 'child_not_started'))
        # Never a half-loaded MT5: closed through the EA (once before the deploy, once to unwind), everything set aside.
        self.assertIsNone(self.process.identity); self.assertEqual(ea.shutdowns, 2)
        where = deploy.paths(self.c, 'e' * 32)
        self.assertFalse(where['state'].exists()); self.assertFalse(where['profile'].exists())
        self.assertFalse((mailbox.portfolio_root(self.c) / 'registration.json').exists())
        self.assertTrue(any(DEPLOY_PROFILE + '.stopped-' in name for name in journal['archived']))
        self.assertIsNone(deploy.current_deployment(self.c))
        self.assertNotIn('readback', journal)

    def test_children_pending_at_the_deadline_is_never_success(self):
        self.start_ea(pairing='none', unstarted={0, 1})
        with self.relaunch(), self.assertRaisesRegex(ValueError, r'2 of 2 members did not start .*child_not_started.*child_not_started'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())
        self.assertEqual(self.journal()['phase'], 'stopped')

    def test_a_children_linked_receipt_with_an_unlinked_or_duplicate_row_is_not_accepted(self):
        self.start_ea(pairing='none')
        def lying(controller, ident, action, timeout=60):
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            if action == 'link_children':
                rows = [dict(r) for r in receipt['rows']]
                rows[1].update(chartId=rows[0]['chartId'])  # two rows claim one chart
                receipt = receipt | dict(result='children_linked', rows=rows)
            return receipt
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'child_not_linked'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=lying, sleep=lambda s: None, clock=fast_clock())
        self.assertEqual(self.journal()['rows_failed'][0]['reason'], 'child_not_linked')

    def test_a_link_receipt_that_shows_algo_on_or_positions_is_never_accepted(self):
        ea = self.start_ea(pairing='none')
        with self.relaunch():
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)  # leaves a live registration to ask
        self.assertTrue(deploy._link_children(self.c, self.ident, request=mailbox.portfolio_request, sleep=lambda s: None,
                                              clock=fast_clock())['outcome'] == 'linked')
        for change in (dict(tradingAllowed=True), dict(positions=1), dict(orders=2), dict(connected=False)):
            with self.subTest(change=change):
                def raced(controller, ident, action, timeout=60):
                    receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
                    return receipt | change if action == 'link_children' else receipt
                link = deploy._link_children(self.c, self.ident, request=raced, sleep=lambda s: None, clock=fast_clock())
                self.assertEqual(link['outcome'], 'not_inert')
        deploy.stop(self.c, 'stop-raced', mt5=FakeMT5(self.c))
        ea.rows = []
        self.process.identity = FakeProcess().identity
        def algo_reported(controller, ident, action, timeout=60):
            receipt = mailbox.portfolio_request(controller, ident, action, timeout=timeout)
            return receipt | dict(tradingAllowed=True) if action == 'link_children' else receipt
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'stopped being inert'):
            deploy.load(self.c, self.plan(deploymentId='4' * 32), mt5=FakeMT5(self.c), request=algo_reported, sleep=lambda s: None,
                        clock=fast_clock())
        self.assertNotEqual(self.journal('4' * 32)['phase'], 'ready')

    def test_algo_turned_on_while_linking_stops_and_is_never_reported_ready(self):
        ea = self.start_ea(pairing='none', pending_polls=1000)
        def algo_on(controller, ident, action, timeout=60):
            if action == 'link_children':
                ea.algo = True  # the person turned Algo Trading on mid-link
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        with self.relaunch(), self.assertRaises(ValueError) as caught:
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=algo_on, sleep=lambda s: None, clock=fast_clock())
        message = str(caught.exception)
        self.assertIn('stopped being inert', message); self.assertIn('GOAT could not unload it', message); self.assertIn('deploy-stop', message)
        journal = self.journal()
        self.assertNotIn(journal['phase'], ('ready', 'attached', 'stopped'))
        self.assertEqual(journal['auto_unwind']['status'], 'failed')
        self.assertIsNotNone(self.process.identity, 'GOAT never closes a terminal that is not inert')

    def test_a_dashboard_that_never_answers_after_the_launch_unwinds_too(self):
        ea = self.start_ea(pairing='none')
        def silent(controller, ident, action, timeout=60):
            return dict(result='receipt_timeout', id='0' * 32, requestRetained=True) if action == 'status' else \
                mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        with self.relaunch(), self.assertRaisesRegex(ValueError, r'did not answer \(receipt_timeout\).*GOAT closed MT5'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=silent, sleep=lambda s: None, clock=fast_clock())
        self.assertEqual((self.journal()['phase'], self.journal()['failure']['code']), ('stopped', 'dashboard_not_ready'))
        self.assertEqual(ea.shutdowns, 2)

    def test_a_slow_dashboard_start_waits_out_the_unanswered_request_instead_of_failing(self):
        """The mailbox refuses a new request while an unanswered one is live (wait + 5 s, archivable 5 s later)."""
        now, live_until, answers = [0.0], [None], iter(['receipt_timeout', 'receipt_timeout', 'observed'])
        def request(controller, ident, action, timeout=20):
            if live_until[0] is not None and now[0] <= live_until[0]:
                raise ValueError('An unanswered portfolio request is still live; wait for it to expire')
            answer = next(answers)
            if answer == 'receipt_timeout':
                now[0] += timeout; live_until[0] = now[0] + 10  # issued at now - timeout, archivable after +timeout+10
                return dict(result='receipt_timeout', id='0' * 32, requestRetained=True)
            return dict(result='observed')
        def sleep(seconds):
            now[0] += seconds
        status = deploy._poll_until(self.c, self.ident, 'status', lambda r: r['result'] == 'observed', seconds=deploy.DASHBOARD_WAIT_SECONDS,
                                    request=request, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(status['result'], 'observed')
        self.assertLessEqual(now[0], deploy.DASHBOARD_WAIT_SECONDS)

    def test_an_auto_unwound_deploy_can_be_deployed_again_as_a_new_attempt(self):
        ea = self.start_ea(pairing='none', unstarted={1})
        with self.relaunch(), self.assertRaisesRegex(ValueError, 'child_not_started'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())
        ea.unstarted, ea.rows = set(), []
        self.process.identity = FakeProcess().identity  # the research monitor is back
        with self.relaunch() as launch:
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual((result['phase'], result['attempt']), ('ready', 2))
        self.assertEqual(result['previous_terminal']['close_attempt_id'], 'deploy-' + 'e' * 24 + '-a2', 'a new close, never the retained one')
        self.assertTrue(launch.call_args.args[0][1].endswith('e' * 32 + '.attempt-2.ini'))
        kept = json.loads((Path(self.c.root) / 'demo-deployments' / ('e' * 32 + '.attempt-1.json')).read_text())
        self.assertEqual((kept['phase'], kept['rows_failed'][0]['index']), ('stopped', 1))

    def test_a_beta24_journal_in_dashboard_ready_resumes_into_link_children(self):
        self.start_ea(pairing='none')
        def crash_at_link(controller, ident, action, timeout=60):
            if action == 'link_children':
                raise RuntimeError('controller killed')
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)
        with self.relaunch(), self.assertRaisesRegex(RuntimeError, 'controller killed'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), request=crash_at_link, sleep=lambda s: None)
        journal = self.journal()
        self.assertEqual(journal['phase'], 'dashboard_ready')
        for key in ('profile_format', 'attempt', 'previous_profile'):
            journal.pop(key)  # what a beta.24 controller wrote
        deploy.paths(self.c, 'e' * 32)['journal'].write_text(json.dumps(journal))
        with self.relaunch() as launch:
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')
        launch.assert_not_called()

    def test_a_journal_staged_by_the_beta24_template_deploy_is_refused_before_any_launch(self):
        where = deploy.paths(self.c, 'e' * 32)
        where['journal'].parent.mkdir(parents=True, exist_ok=True)
        plan = json.loads(self.plan().read_text())
        import hashlib
        legacy = dict(schema_version=1, deployment_id='e' * 32, phase='staged', build_id=BUILD,
                      plan_sha256=hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        where['journal'].write_text(json.dumps(legacy))
        with self.relaunch() as launch, self.assertRaisesRegex(ValueError, 'staged by an earlier GOAT'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        launch.assert_not_called()

    def test_a_file_goat_did_not_stage_in_the_profile_folder_blocks_the_launch(self):
        where = deploy.paths(self.c, 'e' * 32)
        def plant():
            (where['profile'] / 'chart09.chr').write_bytes(b'\xff\xfe')
        with self.relaunch() as launch, self.assertRaisesRegex(ValueError, r'files GOAT did not stage \(chart09.chr\)'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), close=self.staged_then(plant), sleep=lambda s: None)
        launch.assert_not_called()

    def test_unsupported_periods_lines_and_duplicate_members_are_refused_before_anything_is_written(self):
        twin = member(1, content=('EA_Desc=Trend 0\r\nLots=0.1\r\n').encode('utf-16'))  # member 0's inputs on the same symbol and period
        bad_line = ('EA_Desc=x\rLots=0.1\r\n').encode('utf-16')
        timeframe = "^This portfolio has a timeframe the app can't deploy yet"
        cases = (([member(0, name='GOAT V1.48 EURUSD,M15_Trds0.set')], 'SET_PERIOD_UNSUPPORTED', timeframe + r' \(M15\)'),
                 ([member(0, name='GOAT V1.48 EURUSD,M30_Trds0.set')], 'SET_PERIOD_UNSUPPORTED', timeframe + r' \(M30\)'),
                 ([member(0, name='GOAT V1.48 EURUSD,W1_Trds0.set')], 'SET_PERIOD_UNSUPPORTED', timeframe),
                 ([member(0, content=('EA_Desc=x\r\nStudio_MonitorRunPath=C:\\x\r\n').encode('utf-16'))], 'SET_RUN_PATH_UNSUPPORTED',
                  'only a Studio monitor uses'),
                 ([member(0), twin], 'DUPLICATE_MEMBER_SETTINGS',
                  r'^Two members have identical settings on the same symbol and timeframe; remove one'))
        for members, code, message in cases:
            with self.subTest(code=code, message=message), self.assertRaisesRegex(Refusal, message) as caught:
                deploy.load(self.c, self.plan(members), mt5=FakeMT5(self.c))
            self.assertEqual(caught.exception.code, code)
        with self.assertRaisesRegex(ValueError, 'SET_LINE_UNSUPPORTED'):
            deploy.load(self.c, self.plan([member(0, content=bad_line)]), mt5=FakeMT5(self.c))
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['profile'].exists())
        self.assertFalse(deploy.paths(self.c, 'e' * 32)['journal'].exists())

    # ---------------------------------------------------------------- rollback

    def test_stop_restores_the_previous_profile_exactly(self):
        original = self.write_common()
        folder, before = self.write_previous_profile()
        self.start_ea(pairing='none')
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile):
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')
        journal = self.journal()
        self.assertEqual((journal['previous_profile']['name'], journal['previous_profile']['exists']), (PREVIOUS, True))
        self.assertEqual(set(journal['previous_profile']['manifest']), {'chart01.chr', 'order.wnd'})
        self.assertNotEqual((self.data / 'config/common.ini').read_bytes(), original)
        result = deploy.stop(self.c, 'stop-rollback', mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['previous_profile_intact'], result['profile_restored']), ('stopped', True, True))
        self.assertEqual((self.data / 'config/common.ini').read_bytes(), original, 'only the ProfileLast line changed back, byte for byte')
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before, 'the previous profile is never written')
        self.assertEqual(sorted(p.name for p in folder.parent.iterdir() if p.name.startswith(PREVIOUS)), [PREVIOUS],
                         'only the deploy profile is set aside, never the previous one')
        rollback = result['rollback']
        self.assertEqual(Path(rollback['common_ini_after']).read_bytes(), original)
        self.assertEqual(Path(rollback['common_ini_before']).read_bytes().replace(DEPLOY_PROFILE.encode('utf-16-le'), PREVIOUS.encode('utf-16-le')), original)
        self.assertEqual(result['next_action'], 'Run monitor-launch with a new attempt ID to return this terminal to research.')

    def test_the_auto_unwind_restores_the_previous_profile_too(self):
        original = self.write_common()
        self.write_previous_profile()
        self.start_ea(pairing='none', unstarted={0})
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile), self.assertRaisesRegex(ValueError, 'restored the previous chart profile ' + PREVIOUS):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())
        self.assertEqual((self.data / 'config/common.ini').read_bytes(), original)

    def test_stop_leaves_common_ini_alone_when_the_previous_profile_changed(self):
        self.write_common()
        folder, _ = self.write_previous_profile()
        self.start_ea(pairing='none')
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        (folder / 'chart01.chr').write_bytes(b'changed by someone')
        selected = (self.data / 'config/common.ini').read_bytes()
        result = deploy.stop(self.c, 'stop-changed', mt5=FakeMT5(self.c))
        self.assertEqual((result['status'], result['previous_profile_intact'], result['profile_restored']), ('stopped', False, False))
        self.assertIn('changed or is missing', result['rollback']['reason'])
        self.assertEqual((self.data / 'config/common.ini').read_bytes(), selected, 'never edited without an intact previous profile')
        # MT5 still names the archived deploy profile, so the person is told the one step, in plain words.
        instruction = ("MT5 would still open GOAT's set-aside deploy profile next time, because your previous chart profile " + PREVIOUS
                       + ' changed while GOAT was deployed. In MT5, choose File > Profiles and select ' + PREVIOUS + '.')
        self.assertEqual(result['rollback']['select_profile_instruction'], instruction)
        self.assertTrue(result['next_action'].startswith(instruction))

    def test_the_auto_unwind_tells_the_person_to_pick_a_profile_when_it_could_not_restore_one(self):
        self.write_common()
        folder, _ = self.write_previous_profile()
        self.start_ea(pairing='none', unstarted={0})
        def launched(argv):
            self.mt5_selects_deploy_profile(argv)
            (folder / 'order.wnd').write_bytes(b'changed during the deploy')
        with self.relaunch(on_launch=launched), self.assertRaisesRegex(ValueError, 'In MT5, choose File > Profiles and select ' + PREVIOUS):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())

    def test_stop_leaves_common_ini_alone_when_mt5_names_another_profile(self):
        self.write_common()
        self.write_previous_profile()
        self.start_ea(pairing='none')
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        ini = self.data / 'config/common.ini'
        ini.write_bytes(ini.read_bytes().replace(DEPLOY_PROFILE.encode('utf-16-le'), 'Default'.encode('utf-16-le')))  # the person switched
        chosen = ini.read_bytes()
        result = deploy.stop(self.c, 'stop-other', mt5=FakeMT5(self.c))
        self.assertEqual((result['previous_profile_intact'], result['profile_restored']), (True, False))
        self.assertIn('names profile Default', result['rollback']['reason'])
        self.assertEqual(ini.read_bytes(), chosen)
        self.assertNotIn('select_profile_instruction', result['rollback'], 'MT5 is not on the deploy profile: nothing to tell')
        self.assertEqual(result['next_action'], 'Run monitor-launch with a new attempt ID to return this terminal to research.')

    def test_profile_last_edits_are_exact_single_line_changes_in_any_encoding(self):
        for encode in (lambda t: b'\xff\xfe' + t.encode('utf-16-le'), lambda t: t.encode('utf-8'), lambda t: b'\xef\xbb\xbf' + t.encode('utf-8')):
            for newline in ('\r\n', '\n'):
                text = newline.join(['[Common]', 'Login=1', '[Charts]', 'ProfileLast = ' + DEPLOY_PROFILE + '  ', 'X=ProfileLast=Y', '[Experts]',
                                     'ProfileLast=not charts', 'Enabled=0']) + newline
                raw = encode(text)
                patched = deploy.patch_profile_last(raw, DEPLOY_PROFILE, PREVIOUS)
                self.assertEqual(patched, encode(text.replace('ProfileLast = ' + DEPLOY_PROFILE + '  ', 'ProfileLast = ' + PREVIOUS + '  ')))
                self.assertEqual(deploy.profile_last(patched), PREVIOUS)
        twice = '[Charts]\r\nProfileLast=a\r\nprofilelast=b\r\n'.encode('utf-8')
        with self.assertRaisesRegex(ValueError, 'more than one'):
            deploy.patch_profile_last(twice, 'a', PREVIOUS)
        with self.assertRaisesRegex(ValueError, 'does not name'):
            deploy.patch_profile_last('[Charts]\r\nProfileLast=Default\r\n'.encode('utf-8'), DEPLOY_PROFILE, PREVIOUS)

    # ---------------------------------------------------------------- D2 and D1

    def test_preflight_reports_allow_live_trading_and_never_writes_it(self):
        for allow_live, expected in ((None, False), ('0', False), ('1', True)):
            with self.subTest(allow_live=allow_live):
                raw = self.write_common(allow_live=allow_live)
                with patch('studio_monitor_probe.tester_state', return_value='idle'):
                    result = deploy.preflight(self.c, mt5=FakeMT5(self.c))
                self.assertEqual((result['schema_version'], result['allow_live_trading_default']), (3, expected))
                self.assertEqual(result['readiness_blockers'], [] if expected else
                                 [dict(code='allow_live_trading_off', message=deploy.ALLOW_LIVE_TRADING_INSTRUCTION)])
                self.assertEqual((self.data / 'config/common.ini').read_bytes(), raw, 'read-only')
        (self.data / 'config/common.ini').unlink()
        with patch('studio_monitor_probe.tester_state', return_value='idle'):
            result = deploy.preflight(self.c, mt5=FakeMT5(self.c))
        self.assertEqual((result['allow_live_trading_default'], result['readiness_blockers']), (None, []))

    def test_readiness_names_the_allow_live_trading_step_when_a_child_cannot_trade(self):
        for allow_live, hinted in ((None, True), ('1', False)):
            with self.subTest(allow_live=allow_live):
                for path in [*Path(self.c.root).glob('demo-deployments/*'), *Path(self.c.root).glob('terminal-closes/*')]:
                    path.unlink()
                for path in (deploy.paths(self.c, 'e' * 32)['state'], mailbox.portfolio_root(self.c) / 'registration.json',
                             mailbox.portfolio_root(self.c) / 'request.json'):
                    if path.exists(): path.unlink()
                self.process.identity = FakeProcess().identity
                self.write_common(allow_live=allow_live)
                self.start_ea(pairing='none', child_trade=0)
                with self.relaunch(), self.assertRaises(ValueError) as caught:
                    deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
                self.assertIn('child chart is not allowed to trade', str(caught.exception))
                self.assertEqual(deploy.ALLOW_LIVE_TRADING_INSTRUCTION in str(caught.exception), hinted)
                self.assertNotEqual(self.journal()['phase'], 'ready')
                self.ea.stop(); self.ea = None

    def test_no_file_anywhere_says_enabled_1_or_allow_live_trading_after_deploy_unwind_and_stop(self):
        self.write_common()
        self.write_previous_profile()
        ea = self.start_ea(pairing='none', unstarted={1})
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile), self.assertRaisesRegex(ValueError, 'child_not_started'):
            deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None, clock=fast_clock())
        ea.unstarted, ea.rows = set(), []
        self.process.identity = FakeProcess().identity
        with self.relaunch(on_launch=self.mt5_selects_deploy_profile):
            self.assertEqual(deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)['phase'], 'ready')
        deploy.stop(self.c, 'stop-scan', mt5=FakeMT5(self.c))
        enabled_on = re.compile(r'(?im)^[ \t]*Enabled[ \t]*=[ \t]*1')
        offenders = []
        for root in (self.data, Path(self.c.install['common_files_root']), Path(self.c.root)):
            for path in root.rglob('*'):
                if not path.is_file() or path.suffix in ('.sqlite', '.exe', '.ex5', '.lock'):
                    continue
                raw = path.read_bytes()
                text = raw[2:].decode('utf-16-le', errors='ignore') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8', errors='ignore')
                if enabled_on.search(text) or 'AllowLiveTrading' in text:
                    offenders.append(str(path))
        self.assertEqual(offenders, [])

    # ---------------------------------------------------------------- beta.24 compatibility

    def test_the_ready_result_status_and_receipt_rows_keep_the_beta24_shape(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        # demoDeployService.ts (beta.24) reads exactly these.
        self.assertEqual((result['phase'], result['deployment_id'], result['instruction']), ('ready', 'e' * 32, deploy.READY_INSTRUCTION))
        readback = result['readback']
        self.assertTrue({'demo', 'algo_trading', 'trading_allowed', 'login'} <= set(readback))
        self.assertEqual((readback['demo'], readback['algo_trading'], readback['trading_allowed'], readback['login']), (True, False, False, '123456'))
        for row in readback['rows']:
            self.assertEqual(set(row), {'index', 'symbol', 'sha256', 'chartId', 'magic', 'settingsMatch'})
        beta24_keys = {'schema_version', 'deployment_id', 'plan_sha256', 'phase', 'portfolio', 'account', 'build_id', 'members', 'created_utc',
                       'trading_changed', 'positions_closed', 'previous_terminal', 'startup_sha256', 'pid', 'launch_telemetry',
                       'registration_sha256', 'command_id', 'readback', 'instruction', 'updated_utc'}
        self.assertTrue(beta24_keys <= set(result), beta24_keys - set(result))
        self.assertEqual(mailbox.ROW_FIELDS, {'index', 'symbol', 'chartId', 'magic', 'linkedFresh', 'settingsMatch', 'exposureMode', 'ackId',
                                              'ackStatus', 'AI_MODE', 'AI_PROTOCOL', 'AI_THRESHOLD', 'AI_SCOPE', 'AI_VERIFIED',
                                              'AI_AVAILABLE', 'AI_AT', 'EA_TRADE_ALLOWED'})
        status = deploy.status(self.c)
        self.assertTrue({'schema_version', 'deployment', 'terminal', 'dashboard', 'trading'} <= set(status))
        self.assertEqual([set(row) for row in status['dashboard']['rows']], [{'index', 'symbol', 'linkedFresh'}] * 2)
        stopped = deploy.stop(self.c, 'stop-shape', mt5=FakeMT5(self.c))
        self.assertEqual((stopped['status'], stopped['terminal'], stopped['trading_changed'], stopped['positions_closed']),
                         ('stopped', 'stopped', False, False))
        self.assertIn('next_action', stopped)
