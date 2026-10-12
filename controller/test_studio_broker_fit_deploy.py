"""The broker-fit deploy hook in deploy-load (controller/contracts/broker-fit.md, section Deploy). Fixture-only.

Golden: a plan with a broker-fit block at scale 1.0 (no edits) stages byte-for-byte what the same plan without it
stages, and validates to the same members. A scaled plan stages the controller's own scaled SET, hash-bound to the
reviewed broker-fit result, and the journal keeps {memberId, setSha256Reference, setSha256Deployed, scale} per member.
"""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

import studio_broker_fit as bf
import studio_demo_deploy as deploy
from test_studio_agent_setup import DeployFixture, FakeMT5, member


def reference_member(index, symbol='EURUSD', risk='500.0'):
    raw = ('EA_Desc=Trend ' + str(index) + '\r\nMode_Lots=2\r\nMax_Seq_Trades=4\r\nRisk=' + risk + '\r\nLots_Max=20.0\r\n').encode('utf-16')
    return member(index, symbol, content=raw), raw


def fit_block(raws, edits=None, scale=1.0):
    edits = edits or [{} for _ in raws]
    return dict(schema=bf.DEPLOY_SCHEMA, scale=scale, members=[
        dict(index=i, memberId='m%d' % i, setSha256Reference=hashlib.sha256(raw).hexdigest(),
             setSha256Deployed=hashlib.sha256(bf.rewrite_set(raw, e)).hexdigest(), edits=e) for i, (raw, e) in enumerate(zip(raws, edits))])


class BrokerFitDeployTests(DeployFixture):
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
        with self.assertRaisesRegex(ValueError, 'Invalid demo deploy plan'):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, extra=1).read_text()))

    def test_the_money_safety_check_runs_on_the_deployed_bytes(self):
        # check_member_values (risk-per-sequence and RISK_NOT_CHOSEN rules) sees what is staged, not only the reference.
        members, raws = self.members()
        edits = [dict(Risk='250.0'), {}]
        seen = []
        with patch('studio_demo_deploy.check_member_values', side_effect=lambda controller, name, raw: seen.append(raw)):
            deploy.validate_plan(self.c, self.c.session, json.loads(self.plan(members, brokerFit=fit_block(raws, edits, 0.5)).read_text()))
        self.assertEqual(seen, [bf.rewrite_set(raws[0], edits[0]), raws[1]])

    def test_load_records_the_broker_fit_per_member(self):
        members, raws = self.members()
        edits = [dict(Risk='250.0'), {}]
        block = fit_block(raws, edits, scale=0.5)
        self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(members, brokerFit=block), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(result['broker_fit'], dict(schema=bf.DEPLOY_SCHEMA, scale=0.5, members=[
            dict(memberId='m0', setSha256Reference=hashlib.sha256(raws[0]).hexdigest(),
                 setSha256Deployed=hashlib.sha256(bf.rewrite_set(raws[0], edits[0])).hexdigest(), scale=0.5),
            dict(memberId='m1', setSha256Reference=hashlib.sha256(raws[1]).hexdigest(),
                 setSha256Deployed=hashlib.sha256(raws[1]).hexdigest(), scale=0.5)]))
        # The journal's member hashes (and the registration the dashboard audits) are the DEPLOYED bytes.
        self.assertEqual([m['sha256'] for m in result['members']], [e['setSha256Deployed'] for e in block['members']])
        where = deploy.paths(self.c, 'e' * 32)
        self.assertEqual((where['sets'] / members[0]['fileName']).read_bytes(), bf.rewrite_set(raws[0], edits[0]))

    def test_a_plan_without_broker_fit_keeps_todays_journal_shape(self):
        self.start_ea(pairing='none')
        with self.relaunch():
            result = deploy.load(self.c, self.plan(), mt5=FakeMT5(self.c), sleep=lambda s: None)
        self.assertNotIn('broker_fit', result)
        self.assertEqual(result['phase'], 'ready')


if __name__ == '__main__':
    unittest.main()
