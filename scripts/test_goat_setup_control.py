import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import goat_setup_control as control


class SetupControlTests(unittest.TestCase):
    def receipt(self, identity):
        return {'schema': 1, 'id': identity, 'account': self.data['account'], 'server': self.data['server'],
                'directory': self.data['directory'], 'buildId': self.data['buildId'], 'result': 'observed',
                'observedAtUtc': int(time.time()), 'connected': True, 'tradingAllowed': False,
                'activationOnly': True, 'positions': 0, 'orders': 0, 'charts': 1}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        terminal = root / "Terminal 1"
        binary = terminal / "MQL5/Experts/GOAT Experiment/GOAT V1.47.ex5"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"fixture EA")
        self.manifest = root / "manifest.json"
        self.data = {"directory": str(terminal), "commonFiles": str(root / "Common"), "account": 123,
                     "server": "Fixture-Demo", "buildId": "V1.47-TEST", "eaSha256": hashlib.sha256(b"fixture EA").hexdigest()}
        control.atomic(self.manifest, self.data)
        control.register(self.manifest)
        _, self.rpc = control.scope(self.manifest)

    def test_registration_capabilities_and_lifetime(self):
        result = control.register(self.manifest)
        self.assertEqual(result["capabilities"], ["status", "shutdown"])
        self.assertLessEqual(result["expiresAtUtc"] - time.time(), 3600)

    def test_wrong_binary_prevents_request(self):
        self.data["eaSha256"] = "0" * 64
        control.atomic(self.manifest, self.data)
        with self.assertRaisesRegex(ValueError, "binary differs"):
            control.request(self.manifest, "status")

    def test_versioned_binary_and_isolated_credential_scope(self):
        self.data.update(expertRelativePath='MQL5/Experts/GOAT Experiment/GOAT V1.48.ex5',
                         credentialRelativePath='GOAT/Credentials/api-bearer-pair.token')
        binary = Path(self.data['directory']) / self.data['expertRelativePath']
        binary.write_bytes(b'fixture EA')
        control.atomic(self.manifest, self.data)
        scoped, _ = control.scope(self.manifest)
        self.assertEqual(control.credential_path(scoped).name, 'api-bearer-pair.token')
        binary.write_bytes(b'wrong version')
        with self.assertRaisesRegex(ValueError, 'binary differs'):
            control.scope(self.manifest)

    def test_version_scope_rejects_partial_and_traversal(self):
        for fields in [dict(expertRelativePath='MQL5/Experts/GOAT V1.48.ex5'),
                       dict(expertRelativePath='MQL5/Experts/../../other.ex5', credentialRelativePath='GOAT/Credentials/api-bearer-pair.token'),
                       dict(expertRelativePath='C:/other.ex5', credentialRelativePath='GOAT/Credentials/api-bearer-pair.token')]:
            control.atomic(self.manifest, dict(self.data, **fields))
            with self.assertRaises(ValueError):
                control.scope(self.manifest)

    def test_namespaced_credential_and_pending_not_read(self):
        for name in ('api-bearer-pair.token', 'api-bearer-pair.token.pending'):
            path = Path(self.temp.name) / name
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'credential alias'):
                control.read(path)

    def test_wrong_broker_registration_rejected(self):
        reg = control.read(self.rpc / "registration.json")
        reg["server"] = "Different-Demo"
        control.atomic(self.rpc / "registration.json", reg)
        with self.assertRaises(ValueError):
            control.request(self.manifest, "status")

    def test_registration_cannot_silently_change_identity(self):
        self.data["account"] = 456
        control.atomic(self.manifest, self.data)
        with self.assertRaises(ValueError):
            control.register(self.manifest)

    def test_unresolved_request_preserved(self):
        previous = {"id": "a" * 32}
        control.atomic(self.rpc / "request.json", previous)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            control.request(self.manifest, "shutdown")
        self.assertEqual(control.read(self.rpc / "request.json"), previous)

    def test_retained_producer_lock_is_not_removed(self):
        (self.rpc / "producer.lock").write_text("other")
        with self.assertRaises(FileExistsError):
            control.request(self.manifest, "status")
        self.assertEqual((self.rpc / "producer.lock").read_text(), "other")

    def test_trade_action_not_available(self):
        with self.assertRaises(ValueError):
            control.request(self.manifest, "enable_trading")

    def test_matching_receipt_and_archival(self):
        old = "a" * 32
        control.atomic(self.rpc / "request.json", {"id": old})
        control.atomic(self.rpc / (old + ".json"), self.receipt(old))
        def native():
            for _ in range(200):
                try:
                    req = control.read(self.rpc / "request.json")
                    if req["id"] != old:
                        control.atomic(self.rpc / (req["id"] + ".json"), self.receipt(req['id']))
                        return
                except FileNotFoundError:
                    pass
                time.sleep(.01)
        worker = threading.Thread(target=native)
        worker.start()
        try:
            self.assertEqual(control.request(self.manifest, "status", 3)["result"], "observed")
        finally:
            worker.join()
        self.assertTrue((self.rpc / (old + ".request.json")).exists())
        self.assertFalse((self.rpc / "producer.lock").exists())

    def test_timeout_keeps_request(self):
        with patch.object(control.time, "monotonic", side_effect=[0, 2]):
            result = control.request(self.manifest, "status", 1)
        self.assertEqual(result["result"], "receipt_timeout")
        self.assertTrue((self.rpc / "request.json").exists())

    def test_receipt_extra_secret_never_returned(self):
        receipt = self.receipt('a' * 32)
        receipt['token'] = 'must never be echoed'
        with self.assertRaises(ValueError):
            control.receipt_record(receipt, 'a' * 32, self.data)

    def test_wrong_full_directory_receipt_rejected(self):
        receipt = self.receipt('a' * 32)
        receipt['directory'] = str(Path(self.temp.name) / 'other' / 'Terminal 1')
        with self.assertRaises(ValueError):
            control.receipt_record(receipt, 'a' * 32, self.data)

    def test_wrong_full_directory_registration_rejected(self):
        reg = control.read(self.rpc / 'registration.json')
        reg['directory'] = str(Path(self.temp.name) / 'other' / 'Terminal 1')
        control.atomic(self.rpc / 'registration.json', reg)
        with self.assertRaises(ValueError):
            control.request(self.manifest, 'status')

    def test_non_object_and_oversized_data(self):
        path = self.rpc / 'fixture.json'
        for body in ('[]', 'x' * 16385):
            path.write_text(body)
            with self.assertRaises(ValueError):
                control.read(path)

    def pairing_receipt(self, identity):
        now = int(time.time())
        return dict(self.receipt(identity), result='pairing_available', userCode='ABCD-2345',
                    activationId='a' * 32, pairingExpiresAtMs=(now + 600) * 1000,
                    responseExpiresAtUtc=now + 60)

    def test_pairing_requires_explicit_capability(self):
        with self.assertRaisesRegex(ValueError, 'not authorized'):
            control.request(self.manifest, 'pairing')
        registered = control.register(self.manifest, allow_pairing=True)
        self.assertIn('pairing', registered['capabilities'])
        self.assertLessEqual(registered['expiresAtUtc'] - time.time(), 900)
        self.assertEqual(control.read(self.rpc / 'registration.json')['schema'], 2)
        control.register(self.manifest)
        self.assertEqual(control.read(self.rpc / 'registration.json')['schema'], 1)

    def test_pairing_payload_not_returned_by_status(self):
        with self.assertRaisesRegex(ValueError, 'unexpected pairing'):
            control.receipt_record(self.pairing_receipt('a' * 32), 'a' * 32, self.data)

    def test_pairing_expiry_and_identity_validation(self):
        value = self.pairing_receipt('a' * 32)
        for changes in ({'responseExpiresAtUtc': int(time.time()) - 1},
                        {'observedAtUtc': int(time.time()) + 10},
                        {'account': 456}, {'tradingAllowed': True}, {'orders': 1},
                        {'activationId': 'bad'}, {'userCode': 'bad'},
                        {'pairingExpiresAtMs': 2**53}, {'credentialCandidate': 'private'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                control.receipt_record(dict(value, **changes), 'a' * 32, self.data, pairing=True, fresh=True)

    def test_pairing_is_consumed_without_replay_or_secret_receipt(self):
        control.register(self.manifest, allow_pairing=True)
        def native():
            for _ in range(200):
                try:
                    req = control.read(self.rpc / 'request.json')
                    self.assertEqual(req['schema'], 2)
                    self.assertEqual(req['action'], 'pairing')
                    control.atomic(self.rpc / (req['id'] + '.json'), self.pairing_receipt(req['id']))
                    return
                except FileNotFoundError:
                    time.sleep(.01)
        worker = threading.Thread(target=native)
        worker.start()
        try:
            result = control.request(self.manifest, 'pairing', 3)
        finally:
            worker.join()
        self.assertEqual(result['userCode'], 'ABCD-2345')
        saved = control.read(self.rpc / (result['id'] + '.json'))
        self.assertEqual(saved['result'], 'pairing_consumed')
        self.assertNotIn('userCode', saved)
        self.assertNotIn('activationId', saved)
        self.assertTrue((self.rpc / 'request.json').exists())

    def test_expired_pairing_is_scrubbed_before_error(self):
        control.register(self.manifest, allow_pairing=True)
        identity = 'e' * 32
        value = self.pairing_receipt(identity)
        value.update(observedAtUtc=int(time.time()) - 120,
                     responseExpiresAtUtc=int(time.time()) - 60)
        control.atomic(self.rpc / (identity + '.json'), value)
        with patch.object(control.uuid, 'uuid4') as new_id:
            new_id.return_value.hex = identity
            with self.assertRaisesRegex(ValueError, 'stale'):
                control.request(self.manifest, 'pairing', 1)
        saved = control.read(self.rpc / (identity + '.json'))
        self.assertEqual(saved['result'], 'pairing_consumed')
        self.assertNotIn('userCode', saved)
        self.assertNotIn('activationId', saved)
        self.assertTrue((self.rpc / 'request.json').exists())

    def test_unknown_and_unconsumed_temporaries_prevent_archival(self):
        identity = 'b' * 32
        control.atomic(self.rpc / 'request.json', {'id': identity})
        receipt = self.rpc / (identity + '.json')
        control.atomic(receipt, self.pairing_receipt(identity))
        for suffix, value in [('123.pending', self.pairing_receipt(identity)),
                              ('unknown.pending', {'credentialCandidate': 'never echo'}),
                              ('123.1.1.pending', {'invalid': True})]:
            with self.subTest(suffix=suffix):
                temporary = self.rpc / (identity + '.json.' + suffix)
                control.atomic(temporary, value)
                before = temporary.read_bytes()
                with self.assertRaises(ValueError):
                    control.request(self.manifest, 'status', 1)
                self.assertEqual(temporary.read_bytes(), before)
                self.assertTrue((self.rpc / 'request.json').exists())
                self.assertFalse((self.rpc / (identity + '.request.json')).exists())
                temporary.unlink()
        self.assertEqual(control.read(receipt)['result'], 'pairing_consumed')

    def test_codefree_temporary_replay_markers_are_retained_and_bounded(self):
        identity = 'b' * 32
        value = dict(self.receipt(identity), result='pairing_consumed')
        for i in range(16):
            control.atomic(self.rpc / (identity + f'.json.123.1.{i}.pending'), value)
        control.verify_pairing_temporaries(self.rpc, identity, self.data, None)
        self.assertEqual(len(list(self.rpc.glob('*.pending'))), 16)
        control.atomic(self.rpc / (identity + '.json.123.1.17.pending'), value)
        with self.assertRaisesRegex(ValueError, 'too many'):
            control.verify_pairing_temporaries(self.rpc, identity, self.data, None)

    def test_duplicate_json_fields_rejected_without_echo(self):
        path = self.rpc / 'duplicate.json'
        path.write_text('{"result":"observed","result":"secret-value"}')
        with self.assertRaisesRegex(ValueError, '^duplicate controller field$'):
            control.read(path)

    def test_windows_share_retry_is_bounded_and_does_not_mask_other_errors(self):
        error = PermissionError('fixture share')
        error.winerror = 32
        with patch.object(control.time, 'sleep') as sleep:
            calls = []
            def operation():
                calls.append(1)
                if len(calls) < 3:
                    raise error
                return 'shutdown_requested'
            self.assertEqual(control.sharing_retry(operation), 'shutdown_requested')
            self.assertEqual(len(calls), 3)
            self.assertEqual(sleep.call_count, 2)
            with self.assertRaises(PermissionError):
                control.sharing_retry(lambda: (_ for _ in ()).throw(error))
            self.assertEqual(sleep.call_count, 6)
            with self.assertRaises(FileNotFoundError):
                control.sharing_retry(lambda: (_ for _ in ()).throw(FileNotFoundError()))
            self.assertEqual(sleep.call_count, 6)

    def test_shutdown_receipt_survives_transient_share_during_lock_release(self):
        identity = 'f' * 32
        control.atomic(self.rpc / (identity + '.json'), dict(self.receipt(identity), result='shutdown_requested'))
        original_unlink = Path.unlink
        calls = []
        def unlink(path, *args, **kwargs):
            if path.name == 'producer.lock':
                calls.append(1)
                if len(calls) == 1:
                    error = PermissionError('fixture shutdown share')
                    error.winerror = 32
                    raise error
            return original_unlink(path, *args, **kwargs)
        with patch.object(control.uuid, 'uuid4') as new_id, patch.object(Path, 'unlink', unlink):
            new_id.return_value.hex = identity
            result = control.request(self.manifest, 'shutdown', 1)
        self.assertEqual(result['result'], 'shutdown_requested')
        self.assertEqual(len(calls), 2)
        self.assertEqual(control.read(self.rpc / 'request.json')['id'], identity)


if __name__ == "__main__":
    unittest.main()
