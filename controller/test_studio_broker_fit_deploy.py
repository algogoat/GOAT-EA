"""The broker-fit deploy hook in deploy-load (controller/contracts/broker-fit.md, section Deploy). Fixture-only.

Golden: a plan with a broker-fit block at scale 1.0 (no edits) stages byte-for-byte what the same plan without it
stages, and validates to the same members. A scaled plan stages the controller's own scaled SET, hash-bound to the
reviewed broker-fit result, and the journal keeps {memberId, setSha256Reference, setSha256Deployed, scale} per member
plus the deploy identity. Before anything is staged, deploy-load re-reads the live broker (attach-only read_broker,
faked here) and re-derives every value from the plan's manifest; it refuses FIT_STALE when the fit no longer holds.
"""
import hashlib
import json
import unittest
from unittest.mock import patch

import studio_broker_fit as bf
import studio_demo_deploy as deploy
from studio_installation import contracts
from studio_refusal import Refusal
from test_studio_agent_setup import DeployFixture, FakeMT5, member
from test_studio_broker_fit import manifest, plan_block, reading, reference, symbol

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

    def members(self):
        pairs = [reference_member(0), reference_member(1, 'GBPUSD')]
        return [m for m, _ in pairs], [raw for _, raw in pairs]

    def review(self, equity=None, account_equity=100000.0, **reference_changes):
        """The broker-fit result on this account and the plan block the app assembles from it."""
        members, raws = self.members()
        data = house(list(zip(members, raws)), **reference_changes)
        result = bf.build_result(data, {hashlib.sha256(raw).hexdigest(): raw for raw in raws}, schema=self.c.schema, equity=equity,
                                 **reading(account=dict(ACCOUNT, equity=account_equity), symbols=SYMBOLS))
        self.assertTrue(result['offered'], result['refusal'])
        return members, raws, plan_block(result)

    def reads(self, *args, **kwargs):
        return patch('studio_broker_fit.read_broker', return_value=live_read(*args, **kwargs))

    def staged(self, plan_path):
        plan = json.loads(plan_path.read_text())
        members = deploy.validate_plan(self.c, self.c.session, plan)
        where = deploy.paths(self.c, plan['deploymentId'])
        for m in members:
            m['path'] = str(where['sets'] / m['name'])
        return members, deploy.staged_bytes(self.c, plan, members)

    def test_scale_one_stages_byte_identical_files_golden(self):
        members, raws, block = self.review()
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
        self.assertEqual(edits, [dict(Risk='250.0'), dict(Risk='250.0')])
        prepared, staged = self.staged(self.plan(members, brokerFit=block))
        for row, raw, edit in zip(prepared, raws, edits):
            scaled = bf.rewrite_set(raw, edit)
            self.assertEqual((row['raw'], row['sha256']), (scaled, hashlib.sha256(scaled).hexdigest()))
            self.assertEqual(staged[deploy.paths(self.c, 'e' * 32)['sets'] / row['name']], scaled)
            self.assertIn('Risk=250.0', scaled.decode('utf-16'))

    def test_a_plan_whose_scaled_set_differs_from_the_review_is_refused(self):
        members, raws, block = self.review(equity=50000)
        def refuses(pattern, changed):
            with self.assertRaisesRegex(ValueError, pattern):
                deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=changed).read_text()))
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
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, extra=1).read_text()))

    def test_the_money_safety_check_runs_on_the_deployed_bytes(self):
        members, raws, block = self.review(equity=50000)
        seen = []
        with patch('studio_demo_deploy.check_member_values', side_effect=lambda controller, name, raw: seen.append(raw)):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=block).read_text()))
        self.assertEqual(seen, [bf.rewrite_set(raw, entry['edits']) for raw, entry in zip(raws, block['members'])])

    def test_load_rechecks_the_live_broker_and_records_the_broker_fit(self):
        members, raws, block = self.review(equity=50000)
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(50000.0) as read:
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        read.assert_called_once()
        self.assertEqual([m['memberId'] for m in read.call_args.args[2]['members']], ['m0', 'm1'], 'only the plan members are read')
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
                    deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, equity, currency), sleep=lambda s: None)
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
            deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 99999.0), sleep=lambda s: None)
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'Risk'))

    def test_an_expired_plan_is_refused(self):
        members, raws, block = self.review(equity=50000)
        expired = dict(block, reviewedAtUtc=block['reviewedAtUtc'] - bf.PLAN_TTL_SECONDS - 1)
        with self.assertRaises(Refusal) as caught, self.reads(50000.0):
            deploy.load(self.c, self.plan(members, brokerFit=expired), mt5=live(self.c, 50000.0), sleep=lambda s: None)
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'reviewedAtUtc'))

    def test_a_reference_identical_plan_deploys_while_every_condition_holds(self):
        # goatai#2350 6130033743: the reference bytes at scale 1.0 deploy on live equity in the one-sided 5% band.
        members, raws, block = self.review(**NO_START)
        self.assertIsNotNone(block['referenceIdentical'])
        self.start_ea(pairing='none')
        with self.relaunch(), self.reads(103000.0):
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 103000.0), sleep=lambda s: None)
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
                    deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, **account), sleep=lambda s: None)
                self.assertEqual((caught.exception.code, [row['input'] for row in caught.exception.fields['stale']]), (bf.FIT_STALE, [failing]))
                self.assertFalse(where['sets'].exists())
        # A hand-made exemption block (another server or startingBalance) is a claim the re-derivation refuses.
        other = dict(block, referenceIdentical=dict(block['referenceIdentical'], server='Darwinex-Demo'))
        with self.assertRaises(Refusal) as caught, self.reads(100000.0):
            deploy.load(self.c, self.plan(members, brokerFit=other, deploymentId='f' * 32), mt5=live(self.c, 100000.0), sleep=lambda s: None)
        self.assertEqual([row['input'] for row in caught.exception.fields['stale']], ['referenceIdentical'])

    def test_a_plan_without_broker_fit_keeps_todays_journal_shape(self):
        self.start_ea(pairing='none')
        with self.relaunch(), patch('studio_broker_fit.read_broker', side_effect=AssertionError('no broker-fit read')):
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertNotIn('broker_fit', result)
        self.assertEqual(result['phase'], 'ready')


if __name__ == '__main__':
    unittest.main()
