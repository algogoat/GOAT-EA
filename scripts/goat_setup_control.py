"""Local file RPC for the opt-in GOAT demo setup controller. No credentials/trades.

Run on the VPS via SSH. Required manifest fields: directory, account, server,
buildId, eaSha256, commonFiles. Register defaults to status/shutdown for one hour.
Explicit --allow-pairing-read adds a 15-minute public-challenge capability. Only
the pairing action returns that challenge; never log it as ordinary status.
Native shutdown is refused unless connected, trading disabled, no orders/positions.
An observed status is not portfolio readiness; shutdown_requested is not exit proof.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid


def read(path, credential=None):
    if path.name.casefold() == 'api-bearer.token' or (credential is not None and credential.exists() and path.samefile(credential)):
        raise ValueError("credential alias refused")
    with path.open('rb') as handle:
        data = handle.read(16385)
    if len(data) > 16384:
        raise ValueError("oversized controller file")
    result = json.loads(data.decode("utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("controller object required")
    return result


def atomic(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def scope(manifest):
    data = read(Path(manifest))
    expected = {"directory", "account", "server", "buildId", "eaSha256", "commonFiles"}
    if set(data) != expected or type(data["account"]) is not int or data["account"] <= 0:
        raise ValueError("invalid setup manifest")
    directory, common = Path(data["directory"]), Path(data["commonFiles"])
    if not directory.is_absolute() or not common.is_absolute() or directory.name in ("", ".", ".."):
        raise ValueError("absolute installation paths required")
    data['directory'] = str(directory.resolve())
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,96}", data["buildId"]):
        raise ValueError("invalid build identity")
    if not re.fullmatch(r"[a-f0-9]{64}", data["eaSha256"]):
        raise ValueError("invalid binary hash")
    if not isinstance(data["server"], str) or not data["server"] or any(ord(c) < 32 for c in data["server"]):
        raise ValueError("invalid broker server")
    binary = directory / "MQL5/Experts/GOAT Experiment/GOAT V1.47.ex5"
    credential = common / 'GOAT/Credentials/api-bearer.token'
    if binary.is_symlink() or (credential.exists() and binary.samefile(credential)) or binary.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("unsafe binary file")
    digest = hashlib.sha256()
    count = 0
    with binary.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            count += len(chunk)
            if count > 64 * 1024 * 1024:
                raise ValueError("oversized binary")
            digest.update(chunk)
    if digest.hexdigest() != data["eaSha256"]:
        raise ValueError("installed binary differs from registered candidate")
    return data, common / "GOAT/AgentSetup" / directory.name


def receipt_record(value, identity, data, pairing=False, fresh=False):
    fields = {'schema', 'id', 'result', 'account', 'server', 'directory', 'buildId', 'observedAtUtc',
              'connected', 'tradingAllowed', 'activationOnly', 'positions', 'orders', 'charts'}
    if value.get('result') == 'pairing_available':
        if not pairing:
            raise ValueError('unexpected pairing payload')
        fields |= {'userCode', 'activationId', 'pairingExpiresAtMs', 'responseExpiresAtUtc'}
        if not isinstance(value.get('userCode'), str) or not re.fullmatch(r'[A-Z2-9]{4}-[A-Z2-9]{4}', value['userCode']):
            raise ValueError('invalid pairing code')
        if not isinstance(value.get('activationId'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', value['activationId']):
            raise ValueError('invalid pairing identity')
        expiry, response_expiry = value.get('pairingExpiresAtMs'), value.get('responseExpiresAtUtc')
        if type(expiry) is not int or type(response_expiry) is not int:
            raise ValueError('invalid pairing expiry')
        observed = value.get('observedAtUtc')
        if type(observed) is not int or not observed < response_expiry <= min(observed + 60, expiry // 1000) or not observed * 1000 < expiry <= (observed + 900) * 1000:
            raise ValueError('invalid pairing lifetime')
        if fresh and not observed <= time.time() < response_expiry:
            raise ValueError('stale pairing payload')
        if value.get('connected') is not True or value.get('tradingAllowed') is not False or value.get('activationOnly') is not True or value.get('positions') != 0 or value.get('orders') != 0:
            raise ValueError('pairing is not inert')
    if set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid receipt schema')
    if value['id'] != identity or any(value[k] != data[k] for k in ('account', 'server', 'buildId')) or os.path.normcase(value['directory']) != os.path.normcase(data['directory']):
        raise ValueError('receipt identity mismatch')
    if value['result'] not in ('observed', 'shutdown_requested', 'rejected_envelope', 'rejected_not_inert', 'pairing_available', 'pairing_unavailable', 'pairing_consumed'):
        raise ValueError('invalid receipt result')
    for key in ('connected', 'tradingAllowed', 'activationOnly'):
        if type(value[key]) is not bool:
            raise ValueError('invalid receipt flags')
    for key in ('account', 'observedAtUtc', 'positions', 'orders', 'charts'):
        if type(value[key]) is not int or not 0 <= value[key] <= 2**53:
            raise ValueError('invalid receipt numbers')
    return {key: value[key] for key in fields}


def register(manifest, allow_pairing=False):
    data, root = scope(manifest)
    root.mkdir(parents=True, exist_ok=True)
    record = {"schema": 1, "account": data["account"], "server": data["server"], "directory": data['directory'],
              "buildId": data["buildId"], "expiresAtUtc": int(time.time()) + 3600}
    if allow_pairing:
        record.update(schema=2, allowPairingRead=True, expiresAtUtc=int(time.time()) + 900)
    path = root / "registration.json"
    if path.exists():
        old = read(path, Path(data['commonFiles']) / 'GOAT/Credentials/api-bearer.token')
        if any(old.get(key) != record[key] for key in ("account", "server", "buildId", "directory")):
            raise ValueError("retained registration identity differs; inspect before replacement")
    atomic(path, record)
    return {"registered": True, "expiresAtUtc": record["expiresAtUtc"], "capabilities": ["status", "shutdown"] + (["pairing"] if allow_pairing else [])}


def request(manifest, action, timeout=30):
    if action not in ("status", "shutdown", "pairing") or not 1 <= timeout <= 60:
        raise ValueError("unsupported action or timeout")
    data, root = scope(manifest)
    credential = Path(data['commonFiles']) / 'GOAT/Credentials/api-bearer.token'
    reg = read(root / "registration.json", credential)
    if reg.get("expiresAtUtc", 0) < time.time():
        raise ValueError("setup registration expired")
    if any(reg.get(key) != data[key] for key in ("account", "server", "buildId", "directory")):
        raise ValueError("setup registration mismatch")
    if action == 'pairing' and (reg.get('schema') != 2 or reg.get('allowPairingRead') is not True):
        raise ValueError('pairing read was not authorized')
    # Exclusive producer lock; native receipt IDs provide replay protection.
    lock = root / "producer.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        pending = root / "request.json"
        if pending.exists():
            old = read(pending, credential)
            previous = old.get("id", "")
            if not re.fullmatch(r"[a-f0-9]{32}", previous) or not (root / (previous + ".json")).exists():
                raise ValueError("unresolved request retained; do not overwrite or repeat")
            old_receipt = receipt_record(read(root / (previous + '.json'), credential), previous, data, pairing=True)
            if old_receipt['result'] == 'pairing_available':
                consume_pairing(root / (previous + '.json'), old_receipt)
            archived = root / (previous + ".request.json")
            if archived.exists():
                raise ValueError("request archive already exists; inspect retained state")
            pending.rename(archived)
        identity = uuid.uuid4().hex
        envelope = {"schema": 1, "id": identity, "account": data["account"], "server": data["server"], "directory": data['directory'],
                    "buildId": data["buildId"], "expiresAtUtc": int(time.time()) + 120, "action": action}
        if action == 'pairing':
            envelope['schema'] = 2
        atomic(pending, envelope)
        receipt = root / (identity + ".json")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if receipt.exists():
                result = receipt_record(read(receipt, credential), identity, data, pairing=(action == 'pairing'), fresh=True)
                if result['result'] == 'pairing_available':
                    consume_pairing(receipt, result)
                return result
            time.sleep(0.25)
        return {"id": identity, "result": "receipt_timeout", "requestRetained": True}
    finally:
        os.close(fd)
        lock.unlink()


def consume_pairing(path, value):
    tombstone = {key: item for key, item in value.items() if key not in ('userCode', 'activationId', 'pairingExpiresAtMs', 'responseExpiresAtUtc')}
    tombstone['result'] = 'pairing_consumed'
    atomic(path, tombstone)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("register", "status", "shutdown", "pairing"))
    parser.add_argument('--allow-pairing-read', action='store_true', help='Explicit 15-minute pairing-read capability; register only')
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        if args.allow_pairing_read and args.operation != 'register':
            raise ValueError('capability flag is registration only')
        result = register(args.manifest, args.allow_pairing_read) if args.operation == "register" else request(args.manifest, args.operation, args.timeout)
        print(json.dumps(result))
        return 1 if result.get("result") == "receipt_timeout" else 0
    except (ValueError, OSError, KeyError, TypeError):
        # File paths and arbitrary malformed contents are not echoed.
        print(json.dumps({"result": "setup_control_error", "action": args.operation}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
