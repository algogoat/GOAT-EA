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


if __name__ == "__main__":
    unittest.main()
