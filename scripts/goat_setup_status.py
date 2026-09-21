"""Read-only local GOAT setup inventory; no network, processes or credentials.

Run on the installation host, for example::

    python scripts/goat_setup_status.py --installation installation.json \
        --common-files "C:/Users/Administrator/AppData/Roaming/MetaQuotes/Terminal/Common/Files" \
        --hash-installed-ea

Installation shape: {"terminals": [{"directory": "C:/GOAT Experiment/Terminal 1",
"accountId": "123456"}]}. Optional ``account`` is an alias for accountId; both
must agree if supplied. Native observedAtUtc is Unix UTC seconds. Default maximum
age is 1800 seconds, configurable with --max-age-seconds. Status is an observation,
not proof a terminal is running, a binary is loaded, or trading is ready. A stale
approved observation remains stale; there is no assumed native heartbeat.

Valid inspections return exit 0 even when setup evidence is missing/stale.
Invalid arguments/manifests return exit 2 with a fixed JSON error code. Unknown
native fields are omitted; malformed file contents and exception text never
reach stdout/stderr. common.ini is never read. Credential bytes are never read
or hashed. Installed EA hashes, when requested, describe disk bytes only.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import time


EA_RELATIVE = Path("MQL5/Experts/GOAT Experiment/GOAT V1.47.ex5")
REASONS = frozenset({"build_not_admitted", "rate_limited", "webrequest_permission_required",
                     "network_error", "service_error", "waiting_for_host_activation",
                     "host_activation_cooldown", "awaiting_approval", "approved",
                     "activation_not_pending", "activation_storage_error"})
NATIVE_FIELDS = ("accountId", "buildId", "reason", "httpStatus", "nativeError",
                 "retrySeconds", "observedAtUtc")


class InspectionError(Exception):
    """Carries only a fixed, nonsecret diagnostic code."""


def read_json(path, limit, forbidden=None):
    try:
        if path.name.casefold() == "api-bearer.token" or (forbidden is not None and forbidden.exists() and path.samefile(forbidden)):
            raise InspectionError("unsafe_file_alias")
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise InspectionError("oversized")
        # Duplicate keys can otherwise hide an earlier account/status value.
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise InspectionError("malformed")
                result[key] = value
            return result
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs)
    except FileNotFoundError:
        raise InspectionError("missing") from None
    except (UnicodeError, ValueError, RecursionError):
        raise InspectionError("malformed") from None
    except OSError:
        raise InspectionError("unreadable") from None


def account_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise InspectionError("invalid_account")
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise InspectionError("invalid_account")
    return str(int(value))


def installations(path, credential):
    data = read_json(path, 1024 * 1024, credential)
    if not isinstance(data, dict) or not isinstance(data.get("terminals"), list) or not 1 <= len(data["terminals"]) <= 100:
        raise InspectionError("invalid_installation")
    result, tokens = [], set()
    for row in data["terminals"]:
        if not isinstance(row, dict) or not isinstance(row.get("directory"), str):
            raise InspectionError("invalid_installation")
        directory = Path(row["directory"])
        token = directory.name
        if (not directory.is_absolute() or not token or token in (".", "..")
                or any(ord(c) < 32 for c in str(directory)) or len(token) > 200):
            raise InspectionError("invalid_directory")
        if token.casefold() in tokens:
            raise InspectionError("duplicate_terminal_basename")
        tokens.add(token.casefold())
        expected = [account_id(row[k]) for k in ("accountId", "account") if k in row]
        if len(set(expected)) > 1:
            raise InspectionError("conflicting_accounts")
        result.append((directory, token, expected[0] if expected else None))
    return result


def credential_status(path):
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return {"present": False, "status": "not_regular_file"}
        return {"present": info.st_size > 0, "status": "present" if info.st_size > 0 else "empty"}
    except FileNotFoundError:
        return {"present": False, "status": "missing"}
    except OSError:
        return {"present": False, "status": "unreadable"}


def installed_ea(path, credential, hash_requested):
    result = {"path": str(path), "status": "missing", "sha256": None,
              "evidence": "installed_disk_file_only"}
    try:
        if path.is_symlink():
            result["status"] = "unsafe_file_alias"
            return result
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            result["status"] = "not_regular_file"
            return result
        # Never hash credential bytes, even through a hard link or parent symlink.
        if credential.exists() and path.samefile(credential):
            result["status"] = "unsafe_file_alias"
            return result
        result.update(status="present", bytes=info.st_size)
        if hash_requested:
            if info.st_size > 64 * 1024 * 1024:
                result["status"] = "oversized"
                return result
            digest, count = hashlib.sha256(), 0
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    count += len(chunk)
                    if count > 64 * 1024 * 1024:
                        raise InspectionError("oversized")
                    digest.update(chunk)
            after = path.stat()
            if count != info.st_size or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                result["status"] = "changed_during_read"
            else:
                result["sha256"] = digest.hexdigest()
    except FileNotFoundError:
        result["status"] = "missing"
    except InspectionError:
        result["status"] = "oversized"
    except OSError:
        result["status"] = "unreadable"
    return result


def native_status(path, expected, now, maximum_age, credential):
    result = {"path": str(path), "status": "missing", "ageSeconds": None,
              "accountMatch": "not_checked", "runtimeWebRequestPermission": "unknown"}
    try:
        data = read_json(path, 16384, credential)
        if not isinstance(data, dict) or any(k not in data for k in NATIVE_FIELDS):
            raise InspectionError("malformed")
        account = account_id(data["accountId"])
        if (not isinstance(data["buildId"], str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", data["buildId"])
                or not isinstance(data["reason"], str) or data["reason"] not in REASONS):
            raise InspectionError("malformed")
        for key, minimum, maximum in (("httpStatus", -10000, 599), ("nativeError", 0, 2147483647),
                                     ("retrySeconds", 0, 86400), ("observedAtUtc", 0, 253402300799)):
            if type(data[key]) is not int or not minimum <= data[key] <= maximum:
                raise InspectionError("malformed")
        if data["reason"] == "webrequest_permission_required" and (data["httpStatus"] != -1 or data["nativeError"] != 4014):
            raise InspectionError("malformed")
        native = {key: data[key] for key in NATIVE_FIELDS}
        native["accountId"] = account
        age = now - native["observedAtUtc"]
        result.update(native=native, ageSeconds=age,
                      accountMatch="not_configured" if expected is None else "match" if expected == account else "mismatch")
        result["status"] = ("account_mismatch" if result["accountMatch"] == "mismatch" else
                            "future_timestamp" if age < -60 else "stale" if age > maximum_age else "fresh")
        if (result["status"] == "fresh" and native["reason"] == "webrequest_permission_required"
                and native["httpStatus"] == -1 and native["nativeError"] == 4014):
            result["runtimeWebRequestPermission"] = "required_by_native_observation"
    except InspectionError as error:
        result["status"] = str(error) if str(error) in ("missing", "oversized", "unreadable") else "malformed"
    return result


def inspect(installation, common_files, maximum_age=1800, hash_ea=False, now=None):
    if type(maximum_age) is not int or not 1 <= maximum_age <= 604800:
        raise InspectionError("invalid_max_age")
    now = int(time.time()) if now is None else now
    common_files = Path(common_files)
    credential = common_files / "GOAT/Credentials/api-bearer.token"
    terminals = []
    for directory, token, expected in installations(Path(installation), credential):
        terminals.append({"directory": str(directory), "terminalToken": token, "expectedAccountId": expected,
                          "activation": native_status(common_files / "GOAT" / f"activation-status-{token}.json", expected, now, maximum_age, credential),
                          "installedEa": installed_ea(directory / EA_RELATIVE, credential, hash_ea)})
    return {"schemaVersion": "goat-setup-status-v1", "observedAtUtc": now, "maximumAgeSeconds": maximum_age,
            "credential": credential_status(credential), "terminals": terminals,
            "qualification": "Native activation observations and installed files only; no process, loaded-binary, portfolio or trading-readiness verification. Saved common.ini is not runtime WebRequest evidence."}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InspectionError("invalid_arguments")


def main(argv=None):
    try:
        parser = JsonArgumentParser(description=__doc__)
        parser.add_argument("--installation", required=True, type=Path)
        parser.add_argument("--common-files", required=True, type=Path)
        parser.add_argument("--max-age-seconds", type=int, default=1800)
        parser.add_argument("--hash-installed-ea", action="store_true")
        args = parser.parse_args(argv)
        output = inspect(args.installation, args.common_files, args.max_age_seconds, args.hash_installed_ea)
    except InspectionError as error:
        print(json.dumps({"schemaVersion": "goat-setup-status-v1", "error": str(error)}))
        return 2
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
