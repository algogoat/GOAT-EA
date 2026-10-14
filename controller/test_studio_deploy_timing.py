"""Deploy timing profiles (goat-deploy-timing-v1): the Python port of goatai tools/remote-deploy/deploy_timing_profile.cjs.
Fixture-only, no MT5, no I/O beyond temp files.

The ten checks of the reference's test_deploy_timing_profile.cjs are ported case by case into the shared
controller/contracts/deploy-timing-fixtures/profile-cases.json (with extra cases on the same rules); every verdict here
must equal the reference's (the file at 7cb5591 was run through the .cjs validator: 35 cases, 0 mismatches; review
6160002799 item 4 then changed the evidence and resume rules here first, and the .cjs reference must follow). Also: the
built-in profiles' budgets, runner timeouts and effective sha256, the --timing-profile loader, and that the desktop
profile is exactly the controller's pinned constants.
"""
import copy
import inspect
import json
import math
from pathlib import Path
import tempfile
import unittest

import studio_agent_setup as agent_setup
import studio_demo_deploy as deploy
import studio_deploy_timing as timing
from studio_refusal import Refusal

CASES = json.loads((Path(__file__).resolve().parent / 'contracts' / 'deploy-timing-fixtures' / 'profile-cases.json').read_text(encoding='utf-8'))


def build(case):
    if 'profile' in case:
        return case['profile']
    profile = copy.deepcopy(timing.PROFILES[case['base']])
    profile.update(case.get('set', {}))
    for key in case.get('delete', []):
        del profile[key]
    return profile


def verdict(fn):
    try:
        fn()
    except timing.TimingRefusal as exc:
        return exc.code
    return 'ok'


class ReferenceChecks(unittest.TestCase):
    """test_deploy_timing_profile.cjs, check by check."""

    def test_1_shipped_profiles_validate(self):
        for profile in timing.PROFILES.values():
            self.assertIs(timing.validate_profile(profile), profile)

    def test_2_desktop_budget_keeps_the_apps_15_minute_timeout(self):
        self.assertEqual(timing.budget_seconds(timing.PROFILES['desktop']), 720)
        self.assertEqual(timing.runner_timeout_ms(timing.PROFILES['desktop']), 15 * 60_000)

    def test_3_vps_budget_needs_more_than_the_apps_fixed_15_minutes(self):
        self.assertEqual(timing.budget_seconds(timing.PROFILES['vps-cold-36']), 1410)
        self.assertEqual(timing.runner_timeout_ms(timing.PROFILES['vps-cold-36']), 1_590_000)
        self.assertGreater(timing.runner_timeout_ms(timing.PROFILES['vps-cold-36']), 15 * 60_000)

    def test_4_to_10_every_shared_case_has_the_references_verdict(self):
        for case in CASES['validate']:
            with self.subTest(case['name']):
                self.assertEqual(verdict(lambda: timing.validate_profile(build(case))), case['expect'])
        for case in CASES['resume']:
            with self.subTest(case['name']):
                age = math.nan if case['ageSeconds'] == 'NaN' else case['ageSeconds']
                answer = timing.resume_allowed(timing.PROFILES[case['base']], age)
                self.assertEqual('ok' if answer['ok'] else answer['code'], case['expect'])
        self.assertEqual(len([c for c in CASES['validate'] + CASES['resume'] if c['check'] is not None]), 17,
                         'every assertion of the reference checks 1 and 4-10 is a case')

    def test_10_resume_details_match_the_reference(self):
        profile = timing.PROFILES['vps-cold-36']
        fresh = timing.resume_allowed(profile, 600)
        # Review 6160002799 item 4 (Codex P2): the resume re-check's status re-poll (dashboardWaitSeconds 480) is needed too.
        self.assertEqual(fresh, dict(ok=True, leftSeconds=13800, neededSeconds=480 + 480 + 60 + 90 + 90))
        late = timing.resume_allowed(profile, timing.REGISTRATION_SECONDS - 600)
        self.assertEqual((late['ok'], late['code'], late['leftSeconds'], late['neededSeconds']), (False, 'RESUME_REGISTRATION_TOO_OLD', 600, 1200))
        # Codex's example: 800 s left passed against the old 720 s; the status poll could then use 480 of them.
        self.assertEqual(timing.resume_allowed(profile, timing.REGISTRATION_SECONDS - 800)['code'], 'RESUME_REGISTRATION_TOO_OLD')
        self.assertEqual(timing.resume_allowed(timing.PROFILES['desktop'], 0)['neededSeconds'], 180 + 240 + 60 + 90 + 90)
        self.assertEqual(timing.resume_allowed(profile, math.nan)['code'], 'RESUME_AGE_UNKNOWN')
        for bad in (None, math.inf, True, '600'):
            self.assertEqual(timing.resume_allowed(profile, bad)['code'], 'RESUME_AGE_UNKNOWN', bad)
        with self.assertRaises(timing.TimingRefusal):
            timing.resume_allowed(dict(profile, linkRequestSeconds=91), 600)

    def test_refusals_carry_the_code_and_are_controller_refusals(self):
        with self.assertRaises(timing.TimingRefusal) as caught:
            timing.validate_profile(dict(timing.PROFILES['vps-cold-36'], dashboardWaitSeconds=180))
        self.assertIsInstance(caught.exception, Refusal); self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.code, 'TIMING_BELOW_EVIDENCE')
        self.assertEqual(str(caught.exception), 'TIMING_BELOW_EVIDENCE: dashboardWaitSeconds 180 s does not cover the measured '
                                                'coldStartSeconds 190 s x 1.5')
        self.assertEqual(verdict(lambda: timing.runner_timeout_ms(timing.PROFILES['desktop'], -1)), 'TIMING_INVALID')

    def test_the_margin_is_mandatory_and_the_close_wait_has_the_measured_vps_floor(self):
        # Review 6160002799 item 4: no `evidence: null` bypass, and close-wait >= the measured VPS close x 1.5.
        vps = timing.PROFILES['vps-cold-36']
        self.assertEqual((timing.MEASURED_VPS_CLOSE_SECONDS, timing.CLOSE_WAIT_FLOOR_SECONDS), (vps['evidence']['closeSeconds'], 118.5))
        with self.assertRaises(timing.TimingRefusal) as caught:
            timing.validate_profile(dict(vps, id='my-vps', evidence=None))
        self.assertEqual(caught.exception.code, 'TIMING_EVIDENCE_REQUIRED')
        fast = dict(vps, id='fast-host', closeWaitSeconds=118, evidence=dict(vps['evidence'], closeSeconds=10))
        with self.assertRaises(timing.TimingRefusal) as caught:
            timing.validate_profile(fast)
        self.assertEqual(str(caught.exception), 'TIMING_BELOW_EVIDENCE: closeWaitSeconds 118 s does not cover the measured VPS close 79 s x 1.5')
        self.assertEqual(verdict(lambda: timing.validate_profile(dict(fast, closeWaitSeconds=119))), 'ok')
        # The one profile without evidence is the pinned desktop (the controller's own constants with no flag).
        self.assertEqual(verdict(lambda: timing.validate_profile(copy.deepcopy(timing.PROFILES['desktop']))), 'ok')
        self.assertEqual(verdict(lambda: timing.validate_profile(dict(timing.PROFILES['desktop'], closeWaitSeconds=31))), 'TIMING_EVIDENCE_REQUIRED')

    def test_constants_match_the_reference(self):
        self.assertEqual((timing.SCHEMA, timing.PORTFOLIO_REQUEST_CAP_SECONDS, timing.REGISTRATION_SECONDS, timing.APPLY_POLICY_SECONDS,
                          timing.MIN_MARGIN), ('goat-deploy-timing-v1', 90, 14400, 60, 1.5))
        self.assertEqual([(name, low, high) for name, low, high in timing.FIELDS],
                         [('closeWaitSeconds', 10, 600), ('launchObserveSeconds', 5, 120), ('dashboardWaitSeconds', 60, 1200),
                          ('childStartWaitSeconds', 60, 1200), ('linkRequestSeconds', 1, 90), ('ackWaitSeconds', 30, 600),
                          ('auditWaitSeconds', 30, 600)])
        self.assertEqual(timing.PROFILES['vps-cold-36']['evidence'],
                         dict(measuredUtc='2026-10-12', charts=36, closeSeconds=79, coldStartSeconds=190, coldLinkSeconds=88))


class ControllerAgreement(unittest.TestCase):
    def test_the_desktop_profile_is_exactly_the_pinned_controller_constants(self):
        self.assertEqual(deploy.default_timing(), timing.PROFILES['desktop'])
        self.assertEqual(deploy.CLOSE_WAIT_SECONDS, inspect.signature(agent_setup.close_terminal).parameters['wait_seconds'].default)
        self.assertEqual(deploy.LINK_REQUEST_SECONDS, timing.PROFILES['desktop']['linkRequestSeconds'])
        import studio_agent_mailbox as mailbox
        self.assertEqual(mailbox.REGISTRATION_SECONDS, timing.REGISTRATION_SECONDS)
        self.assertEqual(timing.APPLY_POLICY_SECONDS, 60)

    def test_portfolio_request_still_refuses_over_its_90_s_cap(self):
        import studio_agent_mailbox as mailbox
        with self.assertRaisesRegex(ValueError, 'Invalid dashboard command'):
            mailbox.portfolio_request(None, None, 'link_children', timeout=timing.PORTFOLIO_REQUEST_CAP_SECONDS + 1)

    def test_the_effective_sha256_of_each_builtin_is_the_shared_golden(self):
        for profile_id, golden in CASES['builtins'].items():
            with self.subTest(profile_id):
                profile = timing.PROFILES[profile_id]
                canonical = json.dumps(dict(schema=timing.SCHEMA, **timing.effective(profile)), sort_keys=True, separators=(',', ':'))
                self.assertEqual(canonical, golden['canonical'])
                self.assertEqual(timing.effective_sha256(profile), golden['sha256'])
                self.assertEqual((timing.budget_seconds(profile), timing.runner_timeout_ms(profile)),
                                 (golden['budgetSeconds'], golden['runnerTimeoutMs']))
        # The sha names the waits, not the name or the evidence; an integral float waits the same.
        renamed = dict(timing.PROFILES['vps-cold-36'], id='my-vps', evidence=None, closeWaitSeconds=180.0)
        self.assertEqual(timing.effective_sha256(renamed), CASES['builtins']['vps-cold-36']['sha256'])
        self.assertEqual(timing.record(renamed, source='parameter'),
                         dict(id='my-vps', sha256=CASES['builtins']['vps-cold-36']['sha256'], source='parameter',
                              values=timing.effective(timing.PROFILES['vps-cold-36'])))


class LoadProfile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)

    def write(self, value, name='profile.json'):
        path = Path(self.dir.name) / name
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return str(path)

    def test_builtin_ids(self):
        for profile_id in ('desktop', 'vps-cold-36'):
            profile, record = timing.load_profile(profile_id)
            self.assertEqual(profile, timing.PROFILES[profile_id])
            self.assertEqual((record['id'], record['source'], record['sha256']), (profile_id, 'builtin', CASES['builtins'][profile_id]['sha256']))
            profile['closeWaitSeconds'] = 1
            self.assertEqual(timing.PROFILES[profile_id]['closeWaitSeconds'], 30 if profile_id == 'desktop' else 180, 'a copy, never the built-in')

    def test_a_file_profile_is_validated_and_recorded_with_its_bytes_sha(self):
        mine = dict(timing.PROFILES['vps-cold-36'], id='bilal-vps', dashboardWaitSeconds=600)
        path = self.write(mine)
        profile, record = timing.load_profile(path)
        self.assertEqual(profile, mine)
        self.assertEqual(record['id'], 'bilal-vps')
        self.assertTrue(record['source'].startswith('file:') and len(record['source']) == 5 + 64)
        self.assertEqual(record['values']['dashboardWaitSeconds'], 600)

    def test_file_refusals(self):
        cases = [
            (dict(timing.PROFILES['vps-cold-36'], linkRequestSeconds=91), 'TIMING_LINK_REQUEST_OVER_CAP'),
            (dict(timing.PROFILES['vps-cold-36'], closeWaitSeconds=60), 'TIMING_BELOW_EVIDENCE'),
            (dict(timing.PROFILES['vps-cold-36'], closeWaitSeconds=181), 'TIMING_BUILTIN_ID_MISMATCH'),
            (b'{"schema": "goat-deploy-timing-v1", "schema": "x"}', 'TIMING_INVALID'),
            (b'{"closeWaitSeconds": NaN}', 'TIMING_INVALID'),
            (b'[1, 2]', 'TIMING_INVALID'),
            (b'not json', 'TIMING_INVALID'),
            (b'', 'TIMING_INVALID'),
            (b' ' * (timing.MAX_FILE_BYTES + 1), 'TIMING_INVALID'),
        ]
        for index, (value, code) in enumerate(cases):
            with self.subTest(code=code, index=index):
                self.assertEqual(verdict(lambda: timing.load_profile(self.write(value, f'p{index}.json'))), code)
        self.assertEqual(verdict(lambda: timing.load_profile(str(Path(self.dir.name) / 'missing.json'))), 'TIMING_PROFILE_NOT_FOUND')
        self.assertEqual(verdict(lambda: timing.load_profile('vps-cold')), 'TIMING_PROFILE_NOT_FOUND')
        self.assertEqual(verdict(lambda: timing.load_profile(self.dir.name)), 'TIMING_PROFILE_NOT_FOUND', 'a folder is not a profile')
        self.assertEqual(verdict(lambda: timing.load_profile('')), 'TIMING_INVALID')

    def test_a_builtin_id_wins_over_a_file_of_that_name(self):
        import os
        cwd = os.getcwd(); os.chdir(self.dir.name); self.addCleanup(os.chdir, cwd)
        self.write(dict(timing.PROFILES['desktop'], closeWaitSeconds=600), 'desktop')
        self.assertEqual(timing.load_profile('desktop')[1]['source'], 'builtin')


if __name__ == '__main__':
    unittest.main()
