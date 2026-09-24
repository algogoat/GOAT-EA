"""Local fixture tests: python -m unittest discover -s scripts -p test_goat_setup_status.py."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import goat_setup_status as status


class SetupStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.common = self.root / "Common/Files"
        self.terminal = self.root / "Standard - Filter OFF - AI OFF"
        self.terminal.mkdir()
        self.manifest = self.root / "installation.json"
        self.manifest.write_text(json.dumps({"terminals": [{"directory": str(self.terminal), "accountId": "123"}]}))
        self.credential = self.common / "GOAT/Credentials/api-bearer.token"
        self.credential.parent.mkdir(parents=True)
        self.native = self.common / "GOAT" / f"activation-status-{self.terminal.name}.json"
        self.ea = self.terminal / status.EA_RELATIVE
        self.now = 1800000000

    def emit(self, **overrides):
        data = dict(accountId="123", buildId="GOAT-1.47-setup", reason="awaiting_approval",
                    httpStatus=201, nativeError=0, retrySeconds=5, observedAtUtc=self.now - 10)
        data.update(overrides)
        self.native.write_text(json.dumps(data), encoding="utf-8")

    def inspect(self, **kwargs):
        return status.inspect(self.manifest, self.common, now=self.now, **kwargs)

    def test_fresh_account_observation_and_optional_disk_hash(self):
        self.emit(reason="approved", httpStatus=200, retrySeconds=0)
        self.ea.parent.mkdir(parents=True)
        self.ea.write_bytes(b"synthetic EA fixture")
        result = self.inspect()
        self.assertIsNone(result["terminals"][0]["installedEa"]["sha256"])
        result = self.inspect(hash_ea=True)
        terminal = result["terminals"][0]
        self.assertEqual(terminal["activation"]["status"], "fresh")
        self.assertEqual(terminal["activation"]["accountMatch"], "match")
        self.assertEqual(terminal["activation"]["runtimeWebRequestPermission"], "unknown")
        self.assertEqual(terminal["installedEa"]["sha256"], hashlib.sha256(b"synthetic EA fixture").hexdigest())

    def test_credential_presence_never_opens_or_hashes_credential(self):
        secret = b"NEVER-PRINT-THIS-CREDENTIAL"
        self.credential.write_bytes(secret)
        self.emit()
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == self.credential:
                self.fail("Credential contents were opened")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            result = self.inspect(hash_ea=True)
        self.assertEqual(result["credential"], {"present": True, "status": "present"})
        encoded = json.dumps(result)
        self.assertNotIn(secret.decode(), encoded)
        self.assertNotIn(hashlib.sha256(secret).hexdigest(), encoded)

    def test_missing_and_empty_credentials_distinct(self):
        self.assertEqual(self.inspect()["credential"], {"present": False, "status": "missing"})
        self.credential.touch()
        self.assertEqual(self.inspect()["credential"], {"present": False, "status": "empty"})

    def test_isolated_pair_paths_do_not_describe_legacy_token(self):
        self.credential.write_bytes(b'legacy fixture')
        relative = 'MQL5/Experts/GOAT Experiment/GOAT V1.48.ex5'
        binary = self.terminal / relative
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'pair fixture')
        result = self.inspect(hash_ea=True, expert_relative_path=relative,
                              credential_relative_path='GOAT/Credentials/api-bearer-pair.token')
        self.assertEqual(result['credential']['status'], 'missing')
        self.assertEqual(result['terminals'][0]['installedEa']['sha256'], hashlib.sha256(b'pair fixture').hexdigest())

    def test_version_path_traversal_rejected(self):
        with self.assertRaises(status.InspectionError):
            self.inspect(expert_relative_path='MQL5/Experts/../../other.ex5')

    def test_missing_status_not_replaced_by_saved_webrequest_settings(self):
        config = self.terminal / "config"
        config.mkdir()
        (config / "common.ini").write_text("WebRequest=1\nWebRequestUrl=https://goatedge.ai")
        result = self.inspect()["terminals"][0]["activation"]
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["runtimeWebRequestPermission"], "unknown")

    def test_stale_approval_is_not_current_and_age_is_configurable(self):
        self.emit(reason="approved", observedAtUtc=self.now - 1801)
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["status"], "stale")
        self.assertEqual(self.inspect(maximum_age=1801)["terminals"][0]["activation"]["status"], "fresh")

    def test_future_native_time_not_current(self):
        self.emit(observedAtUtc=self.now + 61)
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["status"], "future_timestamp")

    def test_account_mismatch_cannot_satisfy_permission_observation(self):
        self.emit(accountId="456", reason="webrequest_permission_required", httpStatus=-1, nativeError=4014)
        result = self.inspect()["terminals"][0]["activation"]
        self.assertEqual(result["status"], "account_mismatch")
        self.assertEqual(result["runtimeWebRequestPermission"], "unknown")

    def test_permission_required_only_from_fresh_native_evidence(self):
        self.emit(reason="webrequest_permission_required", httpStatus=-1, nativeError=4014)
        result = self.inspect()["terminals"][0]["activation"]
        self.assertEqual(result["runtimeWebRequestPermission"], "required_by_native_observation")
        self.emit(reason="webrequest_permission_required", httpStatus=-1, nativeError=4014, observedAtUtc=self.now-2000)
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["runtimeWebRequestPermission"], "unknown")

    def test_contradictory_permission_error_tuples_are_malformed(self):
        for http_status, native_error in ((200, 0), (200, 4014), (-1, 0), (-2, 4014)):
            with self.subTest(httpStatus=http_status, nativeError=native_error):
                self.emit(reason="webrequest_permission_required", httpStatus=http_status, nativeError=native_error)
                result = self.inspect()["terminals"][0]["activation"]
                self.assertEqual(result["status"], "malformed")
                self.assertEqual(result["runtimeWebRequestPermission"], "unknown")
                self.assertNotIn("native", result)

    def test_malformed_native_does_not_echo_contents(self):
        for raw in (b'{"secret":"DO-NOT-ECHO"', b'\xff\xfe', b'[]', b'{}'):
            with self.subTest(raw=raw):
                self.native.write_bytes(raw)
                result = self.inspect()["terminals"][0]["activation"]
                self.assertEqual(result["status"], "malformed")
                self.assertNotIn("DO-NOT-ECHO", json.dumps(result))
                self.assertNotIn("native", result)

    def test_invalid_types_and_unknown_reason_fail_closed(self):
        for override in ({"observedAtUtc": "1800000000"}, {"observedAtUtc": True},
                         {"retrySeconds": -1}, {"reason": "arbitrary secret"}, {"accountId": "secret"}):
            self.emit(**override)
            self.assertEqual(self.inspect()["terminals"][0]["activation"]["status"], "malformed")

    def test_unknown_fields_are_not_echoed(self):
        self.emit(secret="DO-NOT-ECHO", token="DO-NOT-ECHO")
        self.assertNotIn("DO-NOT-ECHO", json.dumps(self.inspect()))

    def test_activation_not_pending_and_storage_error_are_visible_observations(self):
        for reason in ("activation_not_pending", "activation_storage_error"):
            with self.subTest(reason=reason):
                self.emit(reason=reason)
                result = self.inspect()["terminals"][0]["activation"]
                self.assertEqual(result["status"], "fresh")
                self.assertEqual(result["native"]["reason"], reason)
                self.assertEqual(result["runtimeWebRequestPermission"], "unknown")

    def test_oversized_and_duplicate_status_fields_are_refused(self):
        self.native.write_bytes(b"x" * 16385)
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["status"], "oversized")
        self.native.write_text('{"accountId":"123","accountId":"456"}')
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["status"], "malformed")

    def test_account_alias_and_absent_expected_account(self):
        self.emit()
        self.manifest.write_text(json.dumps({"terminals": [{"directory": str(self.terminal), "account": 123}]}))
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["accountMatch"], "match")
        self.manifest.write_text(json.dumps({"terminals": [{"directory": str(self.terminal)}]}))
        self.assertEqual(self.inspect()["terminals"][0]["activation"]["accountMatch"], "not_configured")

    def test_duplicate_terminal_basename_and_conflicting_accounts_rejected(self):
        rows = [{"directory": str(self.terminal)}, {"directory": str(self.root / "other" / self.terminal.name)}]
        self.manifest.write_text(json.dumps({"terminals": rows}))
        with self.assertRaisesRegex(status.InspectionError, "duplicate_terminal_basename"):
            self.inspect()
        rows = [{"directory": str(self.terminal), "accountId": "123", "account": 456}]
        self.manifest.write_text(json.dumps({"terminals": rows}))
        with self.assertRaisesRegex(status.InspectionError, "conflicting_accounts"):
            self.inspect()

    def test_hardlinked_credential_is_never_read_as_ea_or_status(self):
        self.credential.write_bytes(b"DO-NOT-READ")
        self.ea.parent.mkdir(parents=True)
        os.link(self.credential, self.ea)
        os.link(self.credential, self.native)
        result = self.inspect(hash_ea=True)["terminals"][0]
        self.assertEqual(result["installedEa"]["status"], "unsafe_file_alias")
        self.assertIsNone(result["installedEa"]["sha256"])
        self.assertEqual(result["activation"]["status"], "malformed")

    def test_cli_errors_are_json_and_do_not_echo_arbitrary_input(self):
        self.manifest.write_text('{"private":"DO-NOT-ECHO"')
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = status.main(["--installation", str(self.manifest), "--common-files", str(self.common)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"], "malformed")
        self.assertEqual(errors.getvalue(), "")
        self.assertNotIn("DO-NOT-ECHO", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = status.main(["--DO-NOT-ECHO"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"], "invalid_arguments")

    def test_six_terminal_inventory_without_process_or_network_calls(self):
        self.manifest.write_text(json.dumps({"terminals": [{"directory": str(self.root / f"terminal-{i}")} for i in range(6)]}))
        result = self.inspect()
        self.assertEqual(len(result["terminals"]), 6)
        self.assertTrue(all(t["activation"]["status"] == "missing" for t in result["terminals"]))


if __name__ == "__main__":
    unittest.main()
