import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import goat_portfolio_setup as p


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        terminal = self.root / 'Terminal'
        binary = terminal / 'MQL5/Experts/GOAT Experiment/GOAT V1.47.ex5'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'candidate')
        self.installation = dict(directory=str(terminal), account=12345, server='Broker-Demo',
                                 buildId='V1.47-TEST', eaSha256=hashlib.sha256(b'candidate').hexdigest(),
                                 commonFiles=str(self.root / 'Common'))
        self.manifest = self.root / 'installation.json'
        p.setup.atomic(self.manifest, self.installation)
        member = self.root / 'Common/portfolio/member.set'
        member.parent.mkdir(parents=True)
        member.write_bytes(b'Mode_Bias=2\r\n')
        self.reg = {k: self.installation[k] for k in ('directory', 'account', 'server', 'buildId')}
        self.reg.update(schema=1, expiresAtUtc=int(time.time())+3600, aiMode=2, aiProtocol=2, aiThreshold=50, exposureMode=1,
                        members=[dict(index=0, path=str(member), symbol='EURUSD', sha256=hashlib.sha256(member.read_bytes()).hexdigest())])
        self.draft = self.root / 'draft.json'
        p.setup.atomic(self.draft, self.reg)
        p.register(self.manifest, self.draft)
        _, self.rpc = p.context(self.manifest)
        self.reg, self.digest = p.read_bounded(self.rpc / 'registration.json')
        self.req = dict(schema=1, id='a'*32, action='audit', registrationSha256=self.digest, expiresAtUtc=int(time.time())+120)

    def receipt(self):
        value = {k: self.installation[k] for k in ('directory', 'account', 'server', 'buildId')}
        value.update(schema=1, id=self.req['id'], action='audit', registrationSha256=self.digest, result='observed',
                     observedAtUtc=int(time.time()), brokerTime=1234, connected=True, tradingAllowed=False,
                     positions=0, orders=0, aiMode=2, aiThreshold=50, aiProtocol=2, commandId=45, commandPending=False,
                     rows=[dict(index=0, symbol='EURUSD', chartId=10, magic=20, linkedFresh=True, settingsMatch=True,
                                exposureMode=1, ackId=45, ackStatus=1, AI_MODE=2, AI_PROTOCOL=2, AI_THRESHOLD=50,
                                AI_SCOPE=0, AI_VERIFIED=1, AI_AVAILABLE=0, AI_AT=int(time.time()), EA_TRADE_ALLOWED=1)])
        return value

    def test_valid_audit_including_verified_withhold(self):
        value = p.verify_receipt(self.receipt(), self.req, self.installation, self.reg['members'])
        self.assertTrue(p.verify_ready(value, self.reg))

    def test_files_changed_or_outside_common_rejected(self):
        Path(self.reg['members'][0]['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError): p.validate_registration(self.reg, self.installation)
        altered = copy.deepcopy(self.reg)
        altered['members'][0]['path'] = str(self.draft)
        with self.assertRaises(ValueError): p.validate_registration(altered, self.installation)

    def test_registration_obeys_producer_lock(self):
        lock = self.rpc / 'producer.lock'
        lock.write_text('owner')
        with self.assertRaises(FileExistsError): p.register(self.manifest, self.draft)
        self.assertEqual(lock.read_text(), 'owner')

    def test_unresolved_intent_cannot_be_renewed_or_reissued(self):
        p.setup.atomic(self.rpc / 'request.json', self.req)
        value = self.receipt(); value['result'] = 'started'
        p.setup.atomic(self.rpc / (self.req['id']+'.json'), value)
        for operation in (lambda: p.register(self.manifest, self.draft), lambda: p.request(self.manifest, 'deploy_next', 1)):
            with self.assertRaisesRegex(ValueError, 'unresolved'): operation()
        self.assertEqual(p.read_bounded(self.rpc / 'request.json')[0], self.req)

    def test_renewal_archives_verified_request(self):
        p.setup.atomic(self.rpc / 'request.json', self.req)
        p.setup.atomic(self.rpc / (self.req['id']+'.json'), self.receipt())
        self.assertEqual(p.register(self.manifest, self.draft)['result'], 'registered')
        self.assertTrue((self.rpc / (self.req['id']+'.request.json')).exists())

    def test_malformed_retained_receipt_not_renewed(self):
        p.setup.atomic(self.rpc / 'request.json', self.req)
        p.setup.atomic(self.rpc / (self.req['id']+'.json'), {'result':'observed'})
        with self.assertRaises(ValueError): p.register(self.manifest, self.draft)

    def test_strict_receipt_identity_and_no_extra_fields(self):
        for field, wrong in [('account', 99), ('directory', 'other'), ('buildId', 'other'), ('registrationSha256', '0'*64), ('schema', True), ('secret', 'forbidden')]:
            value = self.receipt(); value[field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.verify_receipt(value, self.req, self.installation, self.reg['members'])
        value = self.receipt(); value['rows'][0]['symbol'] = 'USDJPY'
        with self.assertRaises(ValueError): p.verify_receipt(value, self.req, self.installation, self.reg['members'])

    def test_readiness_rejects_wrong_or_unverified_policy(self):
        for field, wrong in [('linkedFresh', False), ('settingsMatch', False), ('EA_TRADE_ALLOWED',0), ('ackId', 44), ('ackStatus', 2), ('exposureMode', 0), ('AI_MODE', 1), ('AI_PROTOCOL', 1), ('AI_THRESHOLD', 60), ('AI_SCOPE', 1), ('AI_VERIFIED', 0)]:
            value = self.receipt(); value['rows'][0][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError): p.verify_ready(value, self.reg)

    def test_frozen_broker_clock_cannot_keep_ai_fresh(self):
        value = self.receipt()
        value['rows'][0]['AI_AT'] -= 60
        with self.assertRaises(ValueError): p.verify_ready(value, self.reg)

    def test_old_status_cannot_be_readiness(self):
        for field, wrong in [('action','status'), ('observedAtUtc',int(time.time())-60), ('tradingAllowed',True), ('commandPending',True), ('positions',1)]:
            value = self.receipt(); value[field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError): p.verify_ready(value, self.reg)

    def test_preserve_source_policy_requires_actual_off(self):
        value = self.receipt(); value['aiMode'] = 0
        reg = copy.deepcopy(self.reg); reg['aiMode'] = 0
        with self.assertRaises(ValueError): p.verify_ready(value, reg)
        value['rows'][0]['AI_MODE'] = 1
        self.assertTrue(p.verify_ready(value, reg))

    def test_timeout_retains_request(self):
        with patch.object(p.time, 'monotonic', side_effect=[0, 2]):
            result = p.request(self.manifest, 'deploy_next', 1)
        self.assertEqual(result['result'], 'receipt_timeout')
        self.assertTrue((self.rpc / 'request.json').exists())

    def test_duplicate_json_rejected(self):
        self.draft.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError): p.read_bounded(self.draft)

    def test_cli_rejections_fail_process(self):
        with patch('sys.argv', ['tool', 'deploy_next', '--manifest', str(self.manifest)]), patch.object(p, 'request', return_value={'result':'child_attach_failed'}), patch('builtins.print'):
            self.assertEqual(p.main(), 1)


if __name__ == '__main__': unittest.main()
