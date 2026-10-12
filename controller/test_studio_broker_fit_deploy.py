"""The broker-fit deploy hook in deploy-load (controller/contracts/broker-fit.md, section Deploy). Fixture-only.

Golden: a plan with a broker-fit block at scale 1.0 (no edits) stages byte-for-byte what the same plan without it
stages, and validates to the same members. A scaled plan stages the controller's own scaled SET, hash-bound to the
reviewed broker-fit result, and the journal keeps {memberId, setSha256Reference, setSha256Deployed, scale} per member.
Before anything is staged, deploy-load re-reads the live equity and refuses FIT_STALE when the fit no longer holds.
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

RULES = dict(volumeMin='0.01', volumeStep='0.01', volumeMax='50.0', contractRatio='1', referenceVolumeMin='0.01', startLot='0.1')


def reference_member(index, symbol='EURUSD', risk='500.0'):
    raw = ('EA_Desc=Trend ' + str(index) + '\r\nMode_Lots=2\r\nMax_Seq_Trades=4\r\nRisk=' + risk + '\r\nLots_Max=20.0\r\n').encode('utf-16')
    return member(index, symbol, content=raw), raw


def fit_block(raws, edits=None, scale=1.0):
    """The block the app assembles from the broker-fit result: deployBasis plus each fit member's deploy entry."""
    edits = edits or [{} for _ in raws]
    return dict(schema=bf.DEPLOY_SCHEMA, scale=scale, referenceEquity='100000', accountCurrency='USD', rate='1', members=[
        dict(index=i, memberId='m%d' % i, setSha256Reference=hashlib.sha256(raw).hexdigest(),
             setSha256Deployed=hashlib.sha256(bf.rewrite_set(raw, e)).hexdigest(), edits=e, rules=dict(RULES))
        for i, (raw, e) in enumerate(zip(raws, edits))])


def live(controller, equity, currency='USD'):
    return FakeMT5(controller, account=dict(equity=equity, currency=currency))


class BrokerFitDeployTests(DeployFixture):
    def setUp(self):
        super().setUp()
        # The shared fixture's compact schema has no sizing inputs; production reads the shipped V1.48 contracts.
        self.c.schema, _ = contracts('1.48')

    def members(self):
        pairs = [reference_member(0), reference_member(1, 'GBPUSD')]
        return [m for m, _ in pairs], [raw for _, raw in pairs]

    def staged(self, plan_path):
        plan = json.loads(plan_path.read_text())
        members = deploy.validate_plan(self.c, self.c.session, plan)
        where = deploy.paths(self.c, plan['deploymentId'])
        for m in members:
            m['path'] = str(where['sets'] / m['name'])
        return members, deploy.staged_bytes(self.c, plan, members)

    def test_scale_one_stages_byte_identical_files_golden(self):
        members, raws = self.members()
        plain_members, plain = self.staged(self.plan(members))
        fit_members, fitted = self.staged(self.plan(members, brokerFit=fit_block(raws)))
        self.assertEqual(fit_members, plain_members)
        self.assertEqual(fitted, plain, 'every staged file (SETs, profile charts, dashboard state, namespace) is byte-identical')
        for path, raw in fitted.items():
            if path.suffix == '.set':
                self.assertIn(raw, raws)

    def test_a_scaled_plan_stages_the_controllers_scaled_set(self):
        members, raws = self.members()
        edits = [dict(Risk='250.0'), dict(Risk='250.0')]
        prepared, staged = self.staged(self.plan(members, brokerFit=fit_block(raws, edits, scale=0.5)))
        for row, raw, edit in zip(prepared, raws, edits):
            scaled = bf.rewrite_set(raw, edit)
            self.assertEqual((row['raw'], row['sha256']), (scaled, hashlib.sha256(scaled).hexdigest()))
            self.assertEqual(staged[deploy.paths(self.c, 'e' * 32)['sets'] / row['name']], scaled)
            self.assertIn('Risk=250.0', scaled.decode('utf-16'))

    def test_a_plan_whose_scaled_set_differs_from_the_review_is_refused(self):
        members, raws = self.members()
        block = fit_block(raws, [dict(Risk='250.0'), {}])
        block['members'][0]['setSha256Deployed'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'differs from the reviewed broker-fit result.*nothing was written'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=block).read_text()))
        block = fit_block(raws)
        block['members'][0]['edits'] = dict(Mode_Lots='0')                  # only Risk, Lots_Input and point distances
        with self.assertRaisesRegex(ValueError, 'Unsupported broker-fit edit'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=block).read_text()))
        with self.assertRaisesRegex(ValueError, 'every deployed member'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=fit_block(raws[:1])).read_text()))
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit number'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=dict(fit_block(raws), rate='x')).read_text()))
        with self.assertRaisesRegex(ValueError, 'Invalid broker-fit block'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=dict(fit_block(raws), accountCurrency='usd')).read_text()))
        with self.assertRaisesRegex(ValueError, 'Invalid demo deploy plan'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, extra=1).read_text()))

    def test_the_money_safety_check_runs_on_the_deployed_bytes(self):
        members, raws = self.members()
        edits = [dict(Risk='250.0'), {}]
        seen = []
        with patch('studio_demo_deploy.check_member_values', side_effect=lambda controller, name, raw: seen.append(raw)):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=fit_block(raws, edits, 0.5)).read_text()))
        self.assertEqual(seen, [bf.rewrite_set(raws[0], edits[0]), raws[1]])

    def test_load_rechecks_the_live_equity_and_records_the_broker_fit(self):
        members, raws = self.members()
        edits = [dict(Risk='250.0'), dict(Risk='250.0')]
        block = fit_block(raws, edits, scale=0.5)
        self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=live(self.c, 50000.0), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(result['broker_fit'], dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, members=[
            dict(memberId='m%d' % i, setSha256Reference=hashlib.sha256(raw).hexdigest(),
                 setSha256Deployed=hashlib.sha256(bf.rewrite_set(raw, e)).hexdigest(), scale=0.5)
            for i, (raw, e) in enumerate(zip(raws, edits))]))
        # The journal's member hashes (and the registration the dashboard audits) are the DEPLOYED bytes.
        self.assertEqual([m['sha256'] for m in result['members']], [e['setSha256Deployed'] for e in block['members']])
        where = deploy.paths(self.c, 'e' * 32)
        self.assertEqual((where['sets'] / members[0]['fileName']).read_bytes(), bf.rewrite_set(raws[0], edits[0]))

    def test_a_stale_fit_is_refused_before_anything_is_written(self):
        members, raws = self.members()
        block = fit_block(raws, [dict(Risk='250.0'), dict(Risk='250.0')], scale=0.5)
        where = deploy.paths(self.c, 'e' * 32)
        for equity, currency in ((49000.0, 'USD'), (60000.0, 'USD'), (50000.0, 'EUR'), (None, 'USD')):
            with self.subTest(equity=equity, currency=currency):
                with self.assertRaises(Refusal) as caught:
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
        members, raws = self.members()
        with self.assertRaises(Refusal) as caught:
            deploy.load(self.c, self.plan(members, brokerFit=fit_block(raws)), mt5=live(self.c, 99999.0), sleep=lambda s: None)
        self.assertEqual((caught.exception.code, caught.exception.fields['stale'][0]['input']), (bf.FIT_STALE, 'Risk'))

    def test_a_plan_without_broker_fit_keeps_todays_journal_shape(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertNotIn('broker_fit', result)
        self.assertEqual(result['phase'], 'ready')


if __name__ == '__main__':
    unittest.main()
