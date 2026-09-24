"""Connect or inspect one explicitly owned, already-running, inert demo terminal.

No install, launch, restart, order submission, or Algo toggle. Passwords enter
through stdin only. Each attempt has an exclusive receipt; never retry an
unresolved attempt. See docs/operations/DEMO-CONNECTION.md.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys


class ConnectionError(Exception):
    """Fixed diagnostic code only; never interpolate SDK/secret exceptions."""


def require(condition, code):
    if not condition:
        raise ConnectionError(code)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "invalid_process_time")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ConnectionError("invalid_process_time") from None


def read_manifest(path):
    try:
        raw = Path(path).read_bytes()
        require(len(raw) <= 65536, "manifest_too_large")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "duplicate_manifest_key")
                result[key] = value
            return result
        m = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
        require(m["schemaVersion"] == "goat-demo-connection-v1", "invalid_manifest")
        require(m["purpose"] == "isolated-demo-setup", "invalid_purpose")
        require(type(m["account"]) is int and m["account"] > 0, "invalid_account")
        require(m["credentialRole"] in ("investor", "trader"), "invalid_role")
        require(type(m["process"]["pid"]) is int and m["process"]["pid"] > 0, "invalid_process")
        timestamp(m["process"]["startedUtc"])
        for key in ("server", "loginServer", "currency"):
            require(isinstance(m[key], str) and re.fullmatch(r"[A-Za-z0-9 ._:-]{1,128}", m[key]), "invalid_broker_identity")
        require(type(m["marginMode"]) is int and m["marginMode"] in (0, 1, 2), "invalid_margin_mode")
        require(re.fullmatch(r"[a-fA-F0-9]{64}", m["terminalSha256"]) is not None, "invalid_terminal_hash")
        directory = Path(m["directory"])
        require(directory.is_absolute() and directory.is_dir(), "invalid_directory")
        require(isinstance(m.get("symbols", []), list) and len(m.get("symbols", [])) <= 500, "invalid_symbols")
        require(all(isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9._#-]{1,64}", s) for s in m.get("symbols", [])), "invalid_symbols")
        require(len(set(m.get("symbols", []))) == len(m.get("symbols", [])), "duplicate_symbols")
        return m, hashlib.sha256(raw).hexdigest()
    except (OSError, KeyError, TypeError, ValueError):
        raise ConnectionError("invalid_manifest") from None


def process_identity(pid):
    """Windows process metadata only; no UI or terminal interaction."""
    require(os.name == "nt", "windows_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    require(bool(handle), "process_not_available")
    try:
        exit_code = wintypes.DWORD()
        require(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value == 259, "process_exited")
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        require(kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)), "process_path_unavailable")
        created, exited, kern, user = (wintypes.FILETIME() for _ in range(4))
        require(kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kern), ctypes.byref(user)), "process_time_unavailable")
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        # Integer microseconds avoid floating-point rounding of FILETIME.
        from datetime import timedelta
        started = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
        return {"path": image.value, "startedUtc": started.isoformat()}
    finally:
        kernel.CloseHandle(handle)


def preflight(m, identity=process_identity):
    exe = Path(m["directory"]) / "terminal64.exe"
    current = identity(m["process"]["pid"])
    require(Path(current["path"]).resolve() == exe.resolve(), "process_path_mismatch")
    require(timestamp(current["startedUtc"]) == timestamp(m["process"]["startedUtc"]), "process_creation_mismatch")
    require(exe.is_file() and hashlib.sha256(exe.read_bytes()).hexdigest() == m["terminalSha256"].lower(), "terminal_hash_mismatch")


def validate_observation(m, sdk):
    runtime, account = sdk.terminal_info(), sdk.account_info()
    require(runtime is not None and account is not None, "native_readback_missing")
    require(Path(runtime.data_path).resolve() == Path(m["directory"]).resolve(), "native_directory_mismatch")
    require(runtime.connected, "native_disconnected")
    require(not runtime.trade_allowed, "algo_trading_enabled")
    require(account.login == m["account"] and account.server == m["server"], "native_account_mismatch")
    require(account.trade_mode == sdk.ACCOUNT_TRADE_MODE_DEMO, "demo_required")
    require(account.currency == m["currency"] and account.margin_mode == m["marginMode"], "native_policy_mismatch")
    require(sdk.positions_total() == 0 and sdk.orders_total() == 0, "flat_demo_required")
    if m["credentialRole"] == "investor":
        require(not account.trade_allowed, "investor_permission_mismatch")
    else:
        require(account.trade_allowed, "trader_permission_mismatch")
    return {"account": account.login, "server": account.server, "currency": account.currency,
            "balance": account.balance, "equity": account.equity, "leverage": account.leverage,
            "marginMode": account.margin_mode, "accountTradeAllowed": account.trade_allowed,
            "terminalTradeAllowed": runtime.trade_allowed, "connected": runtime.connected,
            "positions": 0, "orders": 0, "dataPath": runtime.data_path, "terminalBuild": runtime.build}


def run(m, sdk, action, secret=None, identity=process_identity):
    preflight(m, identity)
    kwargs = {"portable": True, "timeout": 30000}
    if action == "connect":
        require(isinstance(secret, dict) and set(secret) == {"account", "role", "password"}, "invalid_secret_envelope")
        require(secret["account"] == m["account"] and secret["role"] == m["credentialRole"], "secret_identity_mismatch")
        require(isinstance(secret["password"], str) and 1 <= len(secret["password"]) <= 256
                and not any(c in secret["password"] for c in "\r\n\x00"), "invalid_password")
        kwargs.update(login=m["account"], server=m["loginServer"], password=secret["password"])
    try:
        if not sdk.initialize(str(Path(m["directory"]) / "terminal64.exe"), **kwargs):
            code = sdk.last_error()[0]
            return {"status": "failed", "code": "native_attach_failed", "nativeCode": code if type(code) is int else None}
        observed = validate_observation(m, sdk)
        preflight(m, identity)
        selected = []
        # Inspection does not modify Market Watch. Connection prepares only
        # explicitly registered symbols after all account checks have passed.
        if action == "connect":
            for symbol in m.get("symbols", []):
                require(sdk.symbol_select(symbol, True), "symbol_selection_failed")
                info = sdk.symbol_info(symbol)
                require(info is not None and info.select and info.visible, "symbol_not_visible")
                selected.append(symbol)
        return {"status": "connected_inert_demo", "observation": observed, "preparedSymbols": selected,
                "qualification": "Connection only; EA initialization, portfolio attachment and trading readiness remain separate."}
    finally:
        kwargs.clear()
        sdk.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "inspect", "connect"))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--sdk-path", type=Path, help="Optional directory containing the installed MetaTrader5 module")
    args = parser.parse_args(argv)
    receipt = {"schemaVersion": "goat-demo-connection-receipt-v1", "action": args.action,
               "startedAtUtc": datetime.now(timezone.utc).isoformat(), "status": "not_started",
               "tradingEnabledByTool": False}
    handle = None
    lock = None
    secret = None
    try:
        m, digest = read_manifest(args.manifest)
        preflight(m)
        receipt.update(manifestSha256=digest, account=m["account"], credentialRole=m["credentialRole"], process=m["process"])
        # Never overwrite a prior result or silently repeat a retained attempt.
        handle = args.receipt.open("x", encoding="utf-8")
        receipt["status"] = "attempt_retained"
        handle.write(json.dumps(receipt, indent=2)); handle.flush(); os.fsync(handle.fileno())
        if args.action == "preflight":
            receipt.update(status="preflight_passed", qualification="Process identity and disk executable only; no broker connection attempted.")
        else:
            lock_path = Path(m["directory"]) / "GOAT-demo-connection.lock"
            try:
                lock = lock_path.open("x", encoding="utf-8")
            except FileExistsError:
                raise ConnectionError("terminal_attempt_retained") from None
            lock.write(json.dumps({"receipt": str(args.receipt.resolve()), "manifestSha256": digest}))
            lock.flush(); os.fsync(lock.fileno())
            if args.sdk_path:
                sys.path.insert(0, str(args.sdk_path.resolve()))
            sdk = importlib.import_module("MetaTrader5")
            if args.action == "connect":
                line = sys.stdin.readline(8193)
                require(len(line) <= 8192, "secret_envelope_too_large")
                secret = json.loads(line)
                line = None
            receipt.update(run(m, sdk, args.action, secret))
    except FileExistsError:
        receipt.update(status="blocked", code="receipt_already_exists")
    except ConnectionError as error:
        receipt.update(status="failed", code=str(error))
    except Exception:
        # Raw exception messages can contain account passwords or SDK internals.
        receipt.update(status="failed", code="connection_tool_error")
    finally:
        secret = None
        receipt["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        if handle:
            handle.close()
            # The original retained intent survives a crash during final writing.
            final_path = args.receipt.with_name(args.receipt.name + ".finishing")
            with final_path.open("x", encoding="utf-8") as finished:
                finished.write(json.dumps(receipt, indent=2)); finished.flush(); os.fsync(finished.fileno())
            os.replace(final_path, args.receipt)
        if lock:
            lock.close()
            # Preserve ambiguous outcomes for inspection; never auto-retry IPC.
            if receipt["status"] == "connected_inert_demo" or (receipt.get("code") == "native_attach_failed" and receipt.get("nativeCode") == -6):
                lock_path.unlink()
    print(json.dumps(receipt))
    return 0 if receipt["status"] in ("preflight_passed", "connected_inert_demo") else 1


if __name__ == "__main__":
    sys.exit(main())
