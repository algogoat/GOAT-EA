"""The broker-fit deploy hook in deploy-load (controller/contracts/broker-fit.md, section Deploy). Fixture-only.

Golden: a plan with a broker-fit block at scale 1.0 (no edits) stages byte-for-byte what the same plan without it
stages, and validates to the same members. A scaled plan stages the controller's own scaled SET, hash-bound to the
reviewed broker-fit result, and the journal keeps {memberId, setSha256Reference, setSha256Deployed, scale} per member
plus the deploy identity. Before anything is staged, deploy-load re-reads the live broker (attach-only read_broker,
faked here) and re-derives every value from the plan's manifest; it refuses FIT_STALE when the fit no longer holds.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import studio_agent_mailbox as mailbox
import studio_broker_fit as bf
import studio_demo_deploy as deploy
from studio_installation import contracts
from studio_refusal import Refusal
from test_studio_agent_setup import DeployFixture, FakeMT5, FakeProcess, member
from test_studio_broker_fit import manifest, plan_block, reading, reference, sign, symbol, with_test_key

SERVER = 'Customer-Demo'                     # the fixture's bound demo server
ACCOUNT = dict(login='123456', server=SERVER, currency='USD', equity=100000.0, leverage=200, demo=True)
SYMBOLS = [symbol(), symbol('GBPUSD')]
NO_START = dict(startLot=None, startLotSource=None)


def reference_member(index, symbol_name='EURUSD', risk='500.0'):
    raw = ('EA_Desc=Trend ' + str(index) + '\r\nMode_Lots=2\r\nMax_Seq_Trades=4\r\nRisk=' + risk + '\r\nLots_Max=20.0\r\n').encode('utf-16')
    return member(index, symbol_name, content=raw), raw


def house(pairs, **reference_changes):
    """The house manifest of the plan members (reference account = this fixture's server, so the clock is the same)."""
    entries = [dict(memberId='m%d' % index, symbol=plan['symbol'], canonicalSymbol=plan['symbol'], timeframe='M1',
                    setName=plan['fileName'], setSha256=hashlib.sha256(raw).hexdigest(), setBytes=len(raw),
                    backtestTraceSha256=None, backtestTraceBytes=None, reference=reference(plan['symbol'], **reference_changes))
               for index, (plan, raw) in enumerate(pairs)]
    return manifest(entries, referenceAccount=dict(server=SERVER, currency='USD', startingBalance=100000, leverage=200))


def live(controller, equity, currency='USD', leverage=200):
    """The broker_proof readback (demo, flat, bound account)."""
    return FakeMT5(controller, account=dict(equity=equity, currency=currency, leverage=leverage))


def live_read(equity=100000.0, **changes):
    """What the attach-only read_broker returns at deploy (patched in: no MT5 here)."""
    data = reading(account=dict(ACCOUNT, equity=equity, **changes), symbols=SYMBOLS)
    return (data['account'], data['symbols'], data['ticks'], data['quotes'], data['margins'], data['utc_now'], data['arrived'])


class BrokerFitDeployTests(DeployFixture):
    def setUp(self):
        super().setUp()
        # The shared fixture's compact schema has no sizing inputs; production reads the shipped V1.48 contracts.
        self.c.schema, _ = contracts('1.48')
        # Manifests here are signed with the test publisher key, pinned in place of the house key (round 5 F2).
        keys = with_test_key(); keys.start(); self.addCleanup(keys.stop)

    def members(self):
        pairs = [reference_member(0), reference_member(1, 'GBPUSD')]
        return [m for m, _ in pairs], [raw for _, raw in pairs]

    def review(self, equity=None, account_equity=100000.0, **reference_changes):
        """The broker-fit result on this account and the plan block the app assembles from it."""
        members, raws = self.members()
        data = sign(house(list(zip(members, raws)), **reference_changes))
        result = bf.build_result(data, {hashlib.sha256(raw).hexdigest(): raw for raw in raws}, schema=self.c.schema, equity=equity,
                                 **reading(account=dict(ACCOUNT, equity=account_equity), symbols=SYMBOLS))
        self.assertTrue(result['offered'], result['refusal'])
        # The house feed's manifestSha256 of the genuine manifest: what the app passes as --manifest-sha256.
        self.genuine = result['manifestSha256']
        self.assertEqual(self.genuine, bf.manifest_sha256(data))
        return members, raws, plan_block(result)

    genuine = None

    def validate(self, plan, manifest_sha256=...):
        return deploy.validate_plan(self.c, self.c.session, plan,
                                    manifest_sha256=self.genuine if manifest_sha256 is ... else manifest_sha256)

    def reads(self, *args, **kwargs):
        return patch('studio_broker_fit.read_broker', return_value=live_read(*args, **kwargs))

    def staged(self, plan_path):
        plan = json.loads(plan_path.read_text())
        members = self.validate(plan)
        where = deploy.paths(self.c, plan['deploymentId'])
        for m in members:
            m['path'] = str(where['sets'] / m['name'])
        return members, deploy.staged_bytes(self.c, plan, members)

    def test_scale_one_stages_byte_identical_files_golden(self):
        # Members without reference.startLot on the reference-identical account: the reference bytes at scale 1.0 (a
        # member with a start lot gets a round 5 F1 band-lowered Risk even at scale 1.0).
        members, raws, block = self.review(**NO_START)
        self.assertEqual([entry['edits'] for entry in block['members']], [{}, {}])
        plain_members, plain = self.staged(self.plan(members))
        fit_members, fitted = self.staged(self.plan(members, brokerFit=block))
        self.assertEqual(fit_members, plain_members)
        self.assertEqual(fitted, plain, 'every staged file (SETs, profile charts, dashboard state, namespace) is byte-identical')
        for path, raw in fitted.items():
            if path.suffix == '.set':
                self.assertIn(raw, raws)

    def test_a_scaled_plan_stages_the_controllers_scaled_set(self):
        members, raws, block = self.review(equity=50000)
        edits = [entry['edits'] for entry in block['members']]
        # 250.0 equity-linear, lowered by the round 5 F1 point-grid band (Grid_Size 10.0 in the V1.48 defaults).
        self.assertEqual(edits, [dict(Risk='228.12'), dict(Risk='228.12')])
        prepared, staged = self.staged(self.plan(members, brokerFit=block))
        for row, raw, edit in zip(prepared, raws, edits):
            scaled = bf.rewrite_set(raw, edit)
            self.assertEqual((row['raw'], row['sha256']), (scaled, hashlib.sha256(scaled).hexdigest()))
            self.assertEqual(staged[deploy.paths(self.c, 'e' * 32)['sets'] / row['name']], scaled)
            self.assertIn('Risk=228.12', scaled.decode('utf-16'))

    def test_a_plan_whose_scaled_set_differs_from_the_review_is_refused(self):
        members, raws, block = self.review(equity=50000)
        def refuses(pattern, changed):
            with self.assertRaisesRegex(ValueError, pattern):
                self.validate(json.loads(self.plan(members, brokerFit=changed).read_text()))
        entry = block['members'][0]
        refuses('differs from the reviewed broker-fit result.*nothing was written',
                dict(block, members=[dict(entry, setSha256Deployed='0' * 64), block['members'][1]]))
        # Only Risk, Lots_Input and point distances.
        refuses('Unsupported broker-fit edit', dict(block, members=[dict(entry, edits=dict(Mode_Lots='0')), block['members'][1]]))
        refuses('every deployed member', dict(block, members=block['members'][:1]))
        refuses('Invalid broker-fit number', dict(block, rate='x'))
        refuses('Invalid broker-fit block', dict(block, accountCurrency='usd'))
        refuses('Invalid broker-fit block', dict(block, schema='goat-broker-fit-deploy-v1'))
        refuses('does not match its plan member', dict(block, members=[dict(entry, brokerSymbol='EURUSD.raw'), block['members'][1]]))
        with self.assertRaisesRegex(ValueError, 'Invalid demo deploy plan'):
            self.validate(json.loads(self.plan(members, extra=1).read_text()))

    def test_the_money_safety_check_runs_on_the_deployed_bytes(self):
        members, raws, block = self.review(equity=50000)
        seen = []
        with patch('studio_demo_deploy.check_member_values', side_effect=lambda controller, name, raw: seen.append(raw)):
            self.validate(json.loads(self.plan(members, brokerFit=block).read_text()))
        self.assertEqual(seen, [bf.rewrite_set(raw, entry['edits']) for raw, entry in zip(raws, block['members'])])

    def test_load_rechecks_the_live_broker_and_records_the_broker_fit(self):
        members, raws, block = self.review(equity=50000)
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(50000.0) as read:
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        read.assert_called_once()
        self.assertEqual([m['memberId'] for m in read.call_args.args[2]['members']], ['m0', 'm1'], 'the whole manifest is read')
        deployed = [entry['setSha256Deployed'] for entry in block['members']]
        self.assertEqual(result['broker_fit'], dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, deployIdentity=bf.deploy_identity(0.5, deployed),
                                                    members=[dict(memberId='m%d' % i, setSha256Reference=hashlib.sha256(raw).hexdigest(),
                                                                  setSha256Deployed=sha, scale=0.5)
                                                             for i, (raw, sha) in enumerate(zip(raws, deployed))]))
        # The journal's member hashes (and the registration the dashboard audits) are the DEPLOYED bytes.
        self.assertEqual([m['sha256'] for m in result['members']], deployed)
        where = deploy.paths(self.c, 'e' * 32)
        self.assertEqual((where['sets'] / members[0]['fileName']).read_bytes(), bf.rewrite_set(raws[0], block['members'][0]['edits']))

    def test_a_stale_fit_is_refused_before_anything_is_written(self):
        members, raws, block = self.review(equity=50000)
        where = deploy.paths(self.c, 'e' * 32)
        for equity, currency in ((49000.0, 'USD'), (60000.0, 'USD'), (50000.0, 'EUR'), (None, 'USD')):
            with self.subTest(equity=equity, currency=currency):
                with self.assertRaises(Refusal) as caught, self.reads(equity, currency=currency):
                    deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, equity, currency), manifest_sha256=self.genuine, sleep=lambda s: None)
                self.assertEqual(caught.exception.code, bf.FIT_STALE)
                self.assertIn('The account changed since the check; run the fit again. Nothing was written or launched.',
                              str(caught.exception))
                self.assertFalse(where['sets'].exists(), 'no SET was staged')
                self.assertFalse(where['profile'].exists(), 'no chart was staged')
                self.assertFalse(where['state'].exists(), 'no dashboard state was staged')
                self.assertEqual(json.loads(where['journal'].read_text())['phase'], 'refused_before_stage')
        self.assertEqual(caught.exception.fields['stale'][0]['input'], 'account')
        self.assertEqual(self.process.inspect() is not None, True, 'MT5 was never closed or relaunched')

    def test_a_scale_one_plan_also_rechecks(self):
        members, raws, block = self.review()
        with self.assertRaises(Refusal) as caught, self.reads(99999.0):
            deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 99999.0), manifest_sha256=self.genuine, sleep=lambda s: None)
        # Reviewed at exactly scale 1.0 on the reference-identical account (round 6: the reference bytes), so live
        # 99,999 is below the one-sided band.
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']),
                         (bf.FIT_STALE, 'referenceIdentical.equityWithinTolerance'))

    def test_an_expired_plan_is_refused(self):
        members, raws, block = self.review(equity=50000)
        expired = dict(block, reviewedAtUtc=block['reviewedAtUtc'] - bf.PLAN_TTL_SECONDS - 1)
        with self.assertRaises(Refusal) as caught, self.reads(50000.0):
            deploy.load(self.c, self.plan(members, brokerFit=expired), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'reviewedAtUtc'))

    def test_a_reference_identical_plan_deploys_while_every_condition_holds(self):
        # goatai#2350 6130033743: the reference bytes at scale 1.0 deploy on live equity in the one-sided 5% band.
        members, raws, block = self.review(**NO_START)
        self.assertIsNotNone(block['referenceIdentical'])
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(103000.0):
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 103000.0), manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        where = deploy.paths(self.c, 'e' * 32)
        self.assertEqual((where['sets'] / members[0]['fileName']).read_bytes(), raws[0], 'the reference bytes, unscaled')

    def test_a_reference_identical_plan_is_stale_once_a_condition_fails(self):
        members, raws, block = self.review(**NO_START)
        where = deploy.paths(self.c, 'e' * 32)
        cases = ((dict(equity=100000.0, leverage=100), 'referenceIdentical.sameLeverage'),
                 (dict(equity=106000.0), 'referenceIdentical.equityWithinTolerance'),
                 (dict(equity=99999.0), 'referenceIdentical.equityWithinTolerance'),     # one-sided: never below the reference
                 (dict(equity=94000.0), 'referenceIdentical.equityWithinTolerance'))
        for account, failing in cases:
            with self.subTest(account=account):
                with self.assertRaises(Refusal) as caught, self.reads(**account):
                    deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, **account), manifest_sha256=self.genuine, sleep=lambda s: None)
                self.assertEqual((caught.exception.code, [row['input'] for row in caught.exception.fields['stale']]), (bf.FIT_STALE, [failing]))
                self.assertFalse(where['sets'].exists())
        # A hand-made exemption block (another server or startingBalance) is a claim the re-derivation refuses.
        other = dict(block, referenceIdentical=dict(block['referenceIdentical'], server='Darwinex-Demo'))
        with self.assertRaises(Refusal) as caught, self.reads(100000.0):
            deploy.load(self.c, self.plan(members, brokerFit=other, deploymentId='f' * 32), mt5=live(self.c, 100000.0), manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual([row['input'] for row in caught.exception.fields['stale']], ['referenceIdentical'])

    def test_a_broker_fit_plan_needs_the_published_manifest_sha(self):
        # Round 4 R1 (goatai#2350 6132804177): MANIFEST_UNVERIFIED unless --manifest-sha256 is given and equals the
        # JCS sha256 of the plan's manifest. Re-review 6132018108 probes: a manifest with startingBalance 10000 deploys
        # 10x the Risk on a 10k account; contractSize and tickValue x10 turn FixedLots 0.10 into 1.0.
        members, raws, block = self.review(equity=50000)
        plan = json.loads(self.plan(members, brokerFit=block).read_text())
        self.assertEqual(len(self.validate(plan)), 2, 'the genuine manifest passes')
        probe_a = json.loads(json.dumps(block))
        probe_a['manifest']['referenceAccount']['startingBalance'] = 10000
        probe_b = json.loads(json.dumps(block))
        for entry in probe_b['manifest']['members']:
            entry['reference'].update(contractSize=entry['reference']['contractSize'] * 10, tickValue=entry['reference']['tickValue'] * 10)
        cases = ((plan, None, 'no flag'), (plan, '0' * 64, 'a wrong sha'), (plan, 'not-a-sha', 'not a sha'),
                 (dict(plan, brokerFit=probe_a), self.genuine, 'probe A: startingBalance 10000'),
                 (dict(plan, brokerFit=probe_b), self.genuine, 'probe B: contractSize and tickValue x10'))
        where = deploy.paths(self.c, 'e' * 32)
        for candidate, sha, label in cases:
            with self.subTest(case=label):
                with self.assertRaises(Refusal) as caught:
                    self.validate(candidate, sha)
                self.assertEqual((caught.exception.code, str(caught.exception)), (bf.MANIFEST_UNVERIFIED, bf.MANIFEST_UNVERIFIED_MESSAGE))
                # Round 5 F2: the forged manifests fail their signature first; the sha stays as defence in depth.
                self.assertEqual(caught.exception.fields, dict(reason={'no flag': 'sha_missing', 'a wrong sha': 'sha_mismatch',
                                                                       'not a sha': 'sha_mismatch'}.get(label, 'signature_invalid')))
                path = self.plan(candidate['members'], brokerFit=candidate['brokerFit'])
                with self.assertRaises(Refusal) as caught, self.reads(50000.0):
                    deploy.load(self.c, path, mt5=live(self.c, 50000.0), manifest_sha256=sha, sleep=lambda s: None)
                self.assertEqual(caught.exception.code, bf.MANIFEST_UNVERIFIED)
                self.assertFalse(where['sets'].exists() or where['journal'].exists(), 'nothing written, not even a journal')
        # The forged manifests hash differently: a caller cannot pass the genuine sha with forged values.
        self.assertNotEqual(bf.manifest_sha256(probe_a['manifest']), self.genuine)
        self.assertNotEqual(bf.manifest_sha256(probe_b['manifest']), self.genuine)
        # The CLI takes the flag; no default skips it.
        from goat_studio import OPERATION_CONTRACTS
        self.assertEqual(OPERATION_CONTRACTS['deploy-load'].get('optional'), ['manifest-sha256', 'server-time-utc', 'timing-profile'])
        self.assertIn('MANIFEST_UNVERIFIED', OPERATION_CONTRACTS['deploy-load']['effect'])

    def test_an_unsigned_or_unverifiable_manifest_never_deploys(self):
        # Round 5 F2 at deploy: validate_plan checks the signature, not only the sha.
        members, raws, block = self.review(equity=50000)
        unsigned = dict(block, manifest={k: v for k, v in block['manifest'].items() if k != 'signature'})
        plan = json.loads(self.plan(members, brokerFit=unsigned).read_text())
        with self.assertRaises(Refusal) as caught:
            self.validate(plan)
        self.assertEqual(caught.exception.fields['reason'], 'unsigned')
        import sys
        good = json.loads(self.plan(members, brokerFit=block).read_text())
        with patch.dict(sys.modules, {'cryptography': None, 'cryptography.hazmat': None, 'cryptography.hazmat.primitives': None}):
            with self.assertRaises(Refusal) as caught:
                self.validate(good)
        self.assertEqual((caught.exception.code, caught.exception.fields['reason']), (bf.MANIFEST_UNVERIFIED, 'verifier_unavailable'))

    def test_the_deploy_recheck_gets_the_trusted_server_time(self):
        # Round 5 F3: deploy-load --server-time-utc reaches read_broker, whose clock guard (more than 120 s off -> no
        # tick proves the offset) then holds at deploy exactly as at review.
        members, raws, block = self.review(equity=50000)
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(50000.0) as read:
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine,
                                 server_time_utc=1791900000.0, sleep=lambda s: None)
        self.assertEqual((result['phase'], read.call_args.kwargs['server_time_utc']), ('ready', 1791900000.0))
        with self.assertRaisesRegex(ValueError, 'unix seconds'):
            deploy.load(self.c, self.plan(members, brokerFit=block), manifest_sha256=self.genuine, server_time_utc=float('nan'))
        # Through the real read: a skewed PC clock leaves no arrived tick, so the re-derived Kestrel-shaped members lose
        # their spread sample and the plan is stale.
        import studio_broker_fit as real
        from test_studio_broker_fit import FakeMT5 as BrokerMT5, FakeTerminalProcess
        now = reading()['utc_now']
        mt5 = BrokerMT5(self.c, symbols=SYMBOLS, clock=lambda: now)
        mt5.account_info = lambda: SimpleNamespace(login=123456, server=SERVER, trade_mode=0, currency='USD', equity=50000.0, leverage=200)
        session = dict(account=dict(login='123456', server=SERVER))
        plan = json.loads(self.plan(members, brokerFit=block).read_text())
        with self.assertRaises(Refusal) as caught:
            real.check_live(self.c, session, plan, mt5=mt5, process=FakeTerminalProcess(), clock=lambda: now, sleep=lambda s: None,
                            server_time_utc=now - 121)
        self.assertEqual(caught.exception.code, bf.FIT_STALE)
        self.assertIn(bf.SPREAD_SAMPLE_UNAVAILABLE, [row['input'] for row in caught.exception.fields['stale']])

    # ---- every resume re-checks (GOAT-EA#229 reviews 6160002799 and 6160692543)

    def stop_at(self, phase, members, block, deployment_id='e' * 32):
        """A first deploy-load of the plan reviewed at 50k that passes the live check, then stops at `phase`: 'staged'
        (MT5 did not confirm the close), 'closed' (MT5 closed, then seen running again before the launch), 'attached'
        (the exposure policy was not dispatched) or 'policy_applied' (the settings audit did not complete)."""
        failing = dict(attached='apply_policy', policy_applied='audit').get(phase)

        def close(controller, attempt_id, build_id=None):
            return dict(phase='close_unconfirmed' if phase == 'staged' else 'stopped')   # the fake MT5 keeps running

        def request(controller, ident, action, timeout=20):
            return dict(result='rejected_for_test') if action == failing else mailbox.portfolio_request(controller, ident, action, timeout=timeout)

        if failing and self.ea is None:
            self.start_ea(pairing='none')
        launch = self.relaunch() if failing else patch('studio_demo_deploy.subprocess.Popen', side_effect=AssertionError('launched'))
        with self.reads(50000.0), launch:
            with self.assertRaises(ValueError):
                deploy.load(self.c, self.plan(members, brokerFit=block, deploymentId=deployment_id), mt5=live(self.c, 50000.0),
                            close=None if failing else close, request=request, manifest_sha256=self.genuine, sleep=lambda s: None)
        where = deploy.paths(self.c, deployment_id)
        self.assertEqual(json.loads(where['journal'].read_text())['phase'], phase)
        return where

    def test_a_stale_staged_resume_sets_itself_aside_and_a_fresh_check_deploys(self):
        # The review's probe: reviewed at 50k (scale 0.5), stopped at 'staged', deploy-load run again at 20k live equity.
        # Before the fix it closed and relaunched MT5 with the 0.5 bytes and reached 'ready' (about 2.5x the risk).
        members, raws, block = self.review(equity=50000)
        where = self.stop_at('staged', members, block)
        closes = []
        with self.relaunch() as popen, self.reads(20000.0) as read, self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 20000.0), close=lambda *a, **k: closes.append(a),
                        manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual((caught.exception.code, caught.exception.fields['liveEquity']), (bf.FIT_STALE, 20000.0))
        self.assertTrue(caught.exception.fields['stale'])
        message = str(caught.exception)
        self.assertTrue(message.startswith('The account changed since the check; run the fit again. Nothing was closed or launched: '
                                           'GOAT set this deployment aside'), message)
        self.assertTrue(message.endswith('Check again to re-plan.'), message)
        self.assertNotIn('deploy-stop', message)
        read.assert_called_once()
        self.assertEqual((closes, popen.call_count), ([], 0), 'nothing was closed or launched')
        self.assertIsNotNone(self.process.inspect())
        journal = json.loads(where['journal'].read_text())
        self.assertEqual((journal['phase'], journal['stop_reason'], journal['auto_unwind']['status']), ('stopped', bf.FIT_STALE, 'unwound'))
        self.assertFalse(where['state'].exists() or where['profile'].exists(), 'the staged files were set aside')
        self.assertIsNone(deploy.current_deployment(self.c), 'nothing is live any more')
        # "Check again": a new plan reviewed at the live equity deploys on the same terminal, not "another deployment is live".
        members, raws, fresh = self.review(equity=20000)
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(20000.0):
            result = deploy.load(self.c, self.plan(members, brokerFit=fresh, deploymentId='f' * 32), mt5=live(self.c, 20000.0),
                                 manifest_sha256=self.genuine, sleep=lambda s: None)
        self.assertEqual((result['phase'], result['broker_fit']['scale']), ('ready', 0.2))

    def test_a_staged_resume_with_a_fresh_fit_deploys(self):
        members, raws, block = self.review(equity=50000)
        self.stop_at('staged', members, block)
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(50000.0) as read:
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine,
                                 sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        read.assert_called_once()   # before the close; this call's own check covers the launch

    def test_an_expired_closed_resume_sets_itself_aside_exactly_as_deploy_stop_does(self):
        data = Path(self.c.install['terminal_data_root'])
        (data / 'config/common.ini').write_text('[Common]\nLogin=123456\nServer=Customer-Demo\n[Charts]\nProfileLast=Default\n'
                                                '[Experts]\nEnabled=0\n')
        previous = data / 'MQL5/Profiles/Charts/Default'
        previous.mkdir(parents=True)
        (previous / 'chart01.chr').write_bytes(b'the person\'s own chart')
        members, raws, block = self.review(equity=50000)
        # deploy-stop of a never-launched 'closed' journal...
        self.stop_at('closed', members, block, deployment_id='e' * 32)
        self.process.identity = None
        stopped = deploy.stop(self.c, 'stop-test', mt5=live(self.c, 50000.0))
        # ...and the expired resume of the same journal shape: the same renames and profile restore, by the same code.
        self.process.identity = FakeProcess().identity
        where = self.stop_at('closed', members, block, deployment_id='f' * 32)
        self.process.identity = None

        class Later(datetime):   # a later rename stamp than deploy-stop's (the dashboard state file is shared)
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(hours=1)

        with patch.object(deploy, 'datetime', Later), patch.object(deploy, '_unwind', wraps=deploy._unwind) as unwind, \
                self.relaunch() as popen, patch('studio_broker_fit.read_broker', side_effect=AssertionError('MT5 is closed')), \
                self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(members, brokerFit=block, deploymentId='f' * 32), mt5=live(self.c, 50000.0),
                        manifest_sha256=self.genuine, sleep=lambda s: None, utc_clock=lambda: block['reviewedAtUtc'] + bf.PLAN_TTL_SECONDS + 1)
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'reviewedAtUtc'))
        self.assertIn('Nothing was closed or launched: GOAT set this deployment aside and restored the previous chart profile Default.',
                      str(caught.exception))
        self.assertNotIn('deploy-stop', str(caught.exception))
        self.assertEqual((unwind.call_count, unwind.call_args.kwargs['reason']), (1, bf.PLAN_EXPIRED))
        self.assertEqual(popen.call_count, 0)
        self.assertFalse(where['config'].exists(), 'no startup configuration was written')
        journal = json.loads(where['journal'].read_text())
        self.assertEqual((journal['phase'], journal['stop_reason']), ('stopped', bf.PLAN_EXPIRED))

        def shape(record, deployment_id):
            names = sorted(re.sub(r'\d{8}T\d{6}Z', 'STAMP', Path(path).name).replace(deployment_id[:16], 'ID') for path in record['archived'])
            return names, record['rollback'], record['phase'], record['trading_changed'], record['positions_closed']
        self.assertEqual(shape(journal, 'f' * 32), shape(stopped, 'e' * 32))
        self.assertTrue(journal['rollback']['profile_restored'])
        self.assertTrue(any('GOAT-Deploy-' in name for name in shape(journal, 'f' * 32)[0]), 'the deploy profile was renamed aside')
        self.assertEqual((previous / 'chart01.chr').read_bytes(), b'the person\'s own chart')
        self.assertIsNone(deploy.current_deployment(self.c))

    def test_an_expired_closed_resume_trusts_the_later_of_both_clocks(self):
        members, raws, block = self.review(equity=50000)
        where = self.stop_at('closed', members, block)
        self.process.identity = None
        reviewed = block['reviewedAtUtc']
        # A PC clock that lags is not trusted over the app's server time.
        with self.relaunch() as popen, patch('studio_broker_fit.read_broker', side_effect=AssertionError('MT5 is closed')), \
                self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine,
                        sleep=lambda s: None, utc_clock=lambda: reviewed + 60, server_time_utc=float(reviewed + bf.PLAN_TTL_SECONDS + 1))
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'reviewedAtUtc'))
        self.assertEqual(popen.call_count, 0)
        self.assertEqual(json.loads(where['journal'].read_text())['phase'], 'stopped')

    def test_a_closed_resume_inside_the_ttl_rechecks_after_the_launch(self):
        members, raws, block = self.review(equity=50000)
        self.stop_at('closed', members, block)
        self.process.identity = None
        self.start_ea(pairing='none')
        with self.relaunch() as popen, self.reads(50000.0) as read:
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), manifest_sha256=self.genuine,
                                 sleep=lambda s: None, utc_clock=lambda: block['reviewedAtUtc'] + 60)
        self.assertEqual(result['phase'], 'ready')
        popen.assert_called_once()
        read.assert_called_once()   # after the launch

    def test_a_stale_fit_after_a_resumed_launch_unwinds(self):
        members, raws, block = self.review(equity=50000)
        where = self.stop_at('closed', members, block)
        self.process.identity = None
        ea = self.start_ea(pairing='none')
        with self.relaunch() as popen, self.reads(20000.0) as read, self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 20000.0), manifest_sha256=self.genuine,
                        sleep=lambda s: None, utc_clock=lambda: block['reviewedAtUtc'] + 60)
        self.assertEqual((caught.exception.code, caught.exception.fields['liveEquity']), (bf.FIT_STALE, 20000.0))
        self.assertIn('The account changed since the check; run the fit again. GOAT closed MT5 with Algo Trading off', str(caught.exception))
        self.assertIn('nothing traded', str(caught.exception))
        popen.assert_called_once()
        read.assert_called_once()
        journal = json.loads(where['journal'].read_text())
        self.assertEqual((journal['phase'], journal['stop_reason'], journal['auto_unwind']['status'], journal['failure']['code']),
                         ('stopped', bf.FIT_STALE, 'unwound', bf.FIT_STALE))
        self.assertEqual((journal['trading_changed'], journal['positions_closed']), (False, False))
        self.assertNotIn('linked_rows', journal)
        self.assertEqual(ea.link_requests, 0, 'no child was linked')
        self.assertIn('Enabled=0', where['config'].read_bytes().decode('utf-16'), 'relaunched with Algo Trading off')
        self.assertIsNone(self.process.inspect(), 'MT5 was closed normally')
        self.assertFalse(where['state'].exists() or where['profile'].exists(), 'the deployment was set aside')

    def resume_at(self, phase, equity):
        """A plan reviewed at 50k, stopped at `phase` after the launch, resumed with live equity `equity`."""
        members, raws, block = self.review(equity=50000)
        where = self.stop_at(phase, members, block)
        audits = []

        def request(controller, ident, action, timeout=20):
            audits.extend([action] if action == 'audit' else [])
            return mailbox.portfolio_request(controller, ident, action, timeout=timeout)

        with self.relaunch() as popen, self.reads(equity) as read:
            try:
                outcome = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, equity), request=request,
                                      manifest_sha256=self.genuine, sleep=lambda s: None)
            except Refusal as exc:
                outcome = exc
        read.assert_called_once()
        self.assertEqual(popen.call_count, 0, 'the resume never launches again')
        return where, outcome, audits

    def assert_unwound_before_ready(self, where, outcome, audits):
        self.assertIsInstance(outcome, Refusal)
        self.assertEqual((outcome.code, outcome.fields['liveEquity']), (bf.FIT_STALE, 20000.0))
        self.assertIn('GOAT closed MT5 with Algo Trading off', str(outcome))
        journal = json.loads(where['journal'].read_text())
        self.assertEqual((journal['phase'], journal['stop_reason'], journal['auto_unwind']['status']), ('stopped', bf.FIT_STALE, 'unwound'))
        self.assertEqual((journal['trading_changed'], journal['positions_closed']), (False, False))
        self.assertNotIn('readback', journal, 'readiness was never claimed')
        self.assertEqual(audits, [], 'no settings audit ran')
        self.assertIsNone(self.process.inspect(), 'MT5 was closed normally')

    def test_a_stale_fit_found_at_attached_unwinds_before_ready(self):
        where, outcome, audits = self.resume_at('attached', 20000.0)
        self.assert_unwound_before_ready(where, outcome, audits)
        self.assertEqual(self.ea.command, 0, 'the exposure policy was never dispatched')

    def test_a_fresh_fit_found_at_attached_reaches_ready(self):
        where, outcome, audits = self.resume_at('attached', 50000.0)
        self.assertEqual((outcome['phase'], audits[:1]), ('ready', ['audit']))

    def test_a_stale_fit_found_at_policy_applied_unwinds_before_ready(self):
        where, outcome, audits = self.resume_at('policy_applied', 20000.0)
        self.assert_unwound_before_ready(where, outcome, audits)

    def test_a_fresh_fit_found_at_policy_applied_reaches_ready(self):
        where, outcome, audits = self.resume_at('policy_applied', 50000.0)
        self.assertEqual((outcome['phase'], audits[:1]), ('ready', ['audit']))

    def test_a_plan_without_broker_fit_keeps_todays_journal_shape(self):
        self.start_ea(pairing='none')
        with self.relaunch(), patch('studio_broker_fit.read_broker', side_effect=AssertionError('no broker-fit read')):
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertNotIn('broker_fit', result)
        self.assertEqual(result['phase'], 'ready')


if __name__ == '__main__':
    unittest.main()
