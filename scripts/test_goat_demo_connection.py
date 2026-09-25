"""Connection contract tests; fake SDK never contacts any broker."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import goat_demo_connection as connection


class FakeSDK:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, directory):
        self.runtime = SimpleNamespace(data_path=str(directory), connected=True, trade_allowed=False, build=6182)
        self.account = SimpleNamespace(login=123, server="Broker-Demo", trade_mode=0, currency="USD", margin_mode=2,
                                       trade_allowed=False, balance=100000, equity=100000, leverage=200)
        self.calls = []
        self.position_count = 0
        self.order_count = 0
        self.accept = True
        self.error_code = -6

    def initialize(self, *args, **kwargs):
        self.calls.append(("initialize", kwargs))
        return self.accept

    def last_error(self):
        return (self.error_code, "SDK text MUST NOT be copied")

    def terminal_info(self): return self.runtime
    def account_info(self): return self.account
    def positions_total(self): return self.position_count
    def orders_total(self): return self.order_count
    def shutdown(self): self.calls.append(("shutdown", {}))
    def symbol_select(self, symbol, selected):
        self.calls.append(("symbol_select", {"symbol": symbol}))
        return True
    def symbol_info(self, symbol): return SimpleNamespace(select=True, visible=True)


class DemoConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "terminal64.exe").write_bytes(b"fixture terminal")
        self.m = {"schemaVersion": "goat-demo-connection-v1", "purpose": "isolated-demo-setup",
                  "directory": str(self.root), "account": 123, "server": "Broker-Demo", "loginServer": "demo.example",
                  "currency": "USD", "marginMode": 2, "credentialRole": "investor", "symbols": ["EURUSD"],
                  "terminalSha256": hashlib.sha256(b"fixture terminal").hexdigest(),
                  "process": {"pid": 42, "startedUtc": "2026-09-24T00:00:00.123456Z"}}
        self.identity = lambda pid: {"path": str(self.root / "terminal64.exe"), "startedUtc": self.m["process"]["startedUtc"]}
        self.sdk = FakeSDK(self.root)
        self.secret = {"account": 123, "role": "investor", "password": "DO_NOT_PRINT_SECRET"}
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(self.m))
        self.receipt = self.root / "receipt.json"

    def run_case(self, action="connect"):
        return connection.run(self.m, self.sdk, action, self.secret, self.identity)

    def test_success_prepares_symbols_but_is_not_ea_readiness(self):
        result = self.run_case()
        self.assertEqual(result["status"], "connected_inert_demo")
        self.assertEqual(result["preparedSymbols"], ["EURUSD"])
        self.assertNotIn(self.secret["password"], json.dumps(result))
        self.assertEqual(self.sdk.calls[-1][0], "shutdown")

    def test_inspect_never_sends_password_or_selects_symbols(self):
        self.run_case("inspect")
        self.assertNotIn("password", self.sdk.calls[0][1])
        self.assertFalse(any(c[0] == "symbol_select" for c in self.sdk.calls))

    def test_auth_rejection_is_single_attempt_and_fixed_error(self):
        self.sdk.accept = False
        result = self.run_case()
        self.assertEqual(result, {"status": "failed", "code": "native_attach_failed", "nativeCode": -6})
        self.assertEqual(sum(c[0] == "initialize" for c in self.sdk.calls), 1)

    def test_wrong_pid_creation_and_executable_refuse_before_sdk(self):
        for observed in ({"path": str(self.root / "other.exe"), "startedUtc": self.m["process"]["startedUtc"]},
                         {"path": str(self.root / "terminal64.exe"), "startedUtc": "2026-09-23T00:00:00Z"}):
            with self.subTest(observed=observed), self.assertRaises(connection.ConnectionError):
                connection.run(self.m, self.sdk, "connect", self.secret, lambda pid: observed)
        self.assertFalse(self.sdk.calls)

    def test_changed_executable_refuses_before_sdk(self):
        (self.root / "terminal64.exe").write_bytes(b"changed")
        with self.assertRaisesRegex(connection.ConnectionError, "terminal_hash_mismatch"):
            self.run_case()
        self.assertFalse(self.sdk.calls)

    def test_credential_identity_and_role_do_not_fall_back(self):
        for key, value in (("role", "trader"), ("account", 456)):
            secret = {**self.secret, key: value}
            with self.subTest(key=key), self.assertRaisesRegex(connection.ConnectionError, "secret_identity_mismatch"):
                connection.run(self.m, self.sdk, "connect", secret, self.identity)
        self.assertFalse(self.sdk.calls)

    def test_runtime_guards_precede_symbol_changes(self):
        cases = [("runtime", "connected", False), ("runtime", "trade_allowed", True),
                 ("runtime", "data_path", str(self.root / "other")), ("account", "login", 456),
                 ("account", "server", "Broker-Live"), ("account", "trade_mode", 2),
                 ("account", "currency", "EUR"), ("account", "margin_mode", 0),
                 ("account", "trade_allowed", True)]
        for group, key, value in cases:
            self.sdk = FakeSDK(self.root)
            setattr(getattr(self.sdk, group), key, value)
            with self.subTest(key=key), self.assertRaises(connection.ConnectionError):
                self.run_case()
            self.assertFalse(any(c[0] == "symbol_select" for c in self.sdk.calls))
            self.assertEqual(self.sdk.calls[-1][0], "shutdown")

    def test_unknown_or_nonflat_positions_fail(self):
        for count in (None, 1):
            self.sdk.position_count = count
            with self.subTest(count=count), self.assertRaisesRegex(connection.ConnectionError, "flat_demo_required"):
                self.run_case()

    def test_trader_role_requires_explicit_manifest_and_permission(self):
        self.m["credentialRole"] = self.secret["role"] = "trader"
        with self.assertRaisesRegex(connection.ConnectionError, "trader_permission_mismatch"):
            self.run_case()
        self.sdk.account.trade_allowed = True
        self.assertEqual(self.run_case()["status"], "connected_inert_demo")

    def test_sdk_exception_text_is_never_reported_and_intent_is_retained(self):
        out = io.StringIO()
        with patch.object(connection, "preflight"), patch.object(connection.importlib, "import_module", side_effect=RuntimeError("SECRET")), contextlib.redirect_stdout(out):
            code = connection.main(["inspect", "--manifest", str(self.manifest), "--receipt", str(self.receipt)])
        self.assertEqual(code, 1)
        self.assertNotIn("SECRET", out.getvalue() + self.receipt.read_text())
        self.assertTrue((self.root / "GOAT-demo-connection.lock").exists())

    def test_existing_receipt_cannot_trigger_another_attach(self):
        self.receipt.write_text("original retained intent")
        with patch.object(connection, "preflight"), patch.object(connection.importlib, "import_module") as importer, contextlib.redirect_stdout(io.StringIO()):
            code = connection.main(["inspect", "--manifest", str(self.manifest), "--receipt", str(self.receipt)])
        self.assertEqual(code, 1)
        importer.assert_not_called()
        self.assertEqual(self.receipt.read_text(), "original retained intent")

    def test_new_receipt_cannot_bypass_existing_terminal_attempt(self):
        (self.root / "GOAT-demo-connection.lock").write_text("old attempt")
        with patch.object(connection, "preflight"), patch.object(connection.importlib, "import_module") as importer, contextlib.redirect_stdout(io.StringIO()):
            connection.main(["inspect", "--manifest", str(self.manifest), "--receipt", str(self.receipt)])
        importer.assert_not_called()
        self.assertEqual(json.loads(self.receipt.read_text())["code"], "terminal_attempt_retained")
        self.assertEqual((self.root / "GOAT-demo-connection.lock").read_text(), "old attempt")

    def test_duplicate_manifest_keys_rejected(self):
        self.manifest.write_text('{"account":123,"account":456}')
        with self.assertRaisesRegex(connection.ConnectionError, "duplicate_manifest_key"):
            connection.read_manifest(self.manifest)


if __name__ == "__main__":
    unittest.main()
