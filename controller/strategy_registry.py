"""Local immutable SET inventory. No terminal, queue, trading or source mutations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_set(raw):
    if raw.startswith(b'\xff\xfe'):
        text, encoding = raw.decode('utf-16'), 'utf-16-le-bom'
    else:
        text, encoding = raw.decode('utf-8-sig'), 'utf-8'
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(';') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in values:
            raise ValueError(f'Duplicate SET key: {key}')
        values[key] = value
    if not values.get('EA_Desc'):
        raise ValueError('Missing EA_Desc')
    canonical, axes = {}, []
    for key, value in sorted(values.items()):
        if key == 'EA_Desc':
            continue
        parts = value.split('||')
        if len(parts) not in (1, 5):
            raise ValueError(f'Malformed tuple: {key}')
        normalized = []
        for part in parts:
            try:
                number = Decimal(part)
                if not number.is_finite():
                    raise ValueError(f'Nonfinite value: {key}')
                normalized.append('0' if number == 0 else format(number.normalize(), 'f'))
            except InvalidOperation:
                normalized.append(part)
        canonical[key] = normalized
        if len(parts) == 5:
            if parts[4] not in ('Y', 'N'):
                raise ValueError(f'Invalid optimization flag: {key}')
            if parts[4] == 'Y':
                axes.append(key)
    canonical_json = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return dict(sha256=digest(raw), canonical_sha256=digest(canonical_json.encode()),
                canonical_json=canonical_json, ea_desc=values['EA_Desc'], encoding=encoding,
                axes=axes, crlf='\r\n' in text)


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS templates(
      template_id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS revisions(
      revision_id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES templates,
      sha256 TEXT NOT NULL, canonical_sha256 TEXT NOT NULL, ea_desc TEXT NOT NULL,
      source_bytes BLOB NOT NULL, canonical_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(template_id,sha256));
    CREATE TABLE IF NOT EXISTS imports(
      import_id TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, suite_ref TEXT NOT NULL,
      snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')
    version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if version and version[0] != '1':
        raise ValueError('Unsupported registry schema')
    db.execute("INSERT OR IGNORE INTO metadata VALUES('schema_version','1')")
    db.commit()
    return db


def import_suite(suite, registry):
    suite = Path(suite).resolve()
    if Path(registry).resolve().is_relative_to(suite):
        raise ValueError('Registry must be outside immutable source suite')
    manifest_bytes = (suite / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes.decode('utf-8-sig'))
    original_root = str(manifest['suite']).replace('\\', '/').rstrip('/')
    entries, seen = [], set()
    for entry in manifest['templates']:
        stored = str(entry['path']).replace('\\', '/')
        if not stored.casefold().startswith((original_root + '/').casefold()):
            raise ValueError('Manifest source outside declared suite')
        relative = stored[len(original_root) + 1:]
        path = (suite / relative).resolve()
        if not path.is_relative_to(suite) or path in seen:
            raise ValueError('Escaping or duplicate source path')
        seen.add(path)
        raw = path.read_bytes()
        info = inspect_set(raw)
        if info['sha256'] != entry['sha256'].lower():
            raise ValueError(f'Manifest hash mismatch: {relative}')
        entries.append((relative, raw, info, entry))
    if not entries:
        raise ValueError('Empty suite')
    now = datetime.now(timezone.utc).isoformat()
    db = connect(registry)
    try:
        db.execute('BEGIN IMMEDIATE')
        snapshot = []
        for relative, raw, info, entry in entries:
            # Stable within this declared suite/source identity. Renames need explicit
            # alias review; equal settings do not silently merge template identities.
            source_key = original_root.casefold() + '/' + relative.casefold()
            found = db.execute('SELECT template_id FROM templates WHERE source_key=?', (source_key,)).fetchone()
            template_id = found[0] if found else str(uuid.uuid4())
            if not found:
                db.execute('INSERT INTO templates VALUES(?,?,?)', (template_id, source_key, now))
            found = db.execute('SELECT revision_id FROM revisions WHERE template_id=? AND sha256=?',
                               (template_id, info['sha256'])).fetchone()
            revision_id = found[0] if found else str(uuid.uuid4())
            if not found:
                meta = dict(relative_source=relative, encoding=info['encoding'], crlf=info['crlf'],
                            optimized_axes=info['axes'], lineage_status='unverified_manifest_claims',
                            manifest_claims=entry, semantic_range_validation='not_performed')
                db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?)',
                           (revision_id, template_id, info['sha256'], info['canonical_sha256'],
                            info['ea_desc'], raw, info['canonical_json'], json.dumps(meta), now))
            snapshot.append(dict(template_id=template_id, revision_id=revision_id, source=relative,
                                 sha256=info['sha256'], canonical_sha256=info['canonical_sha256'],
                                 legacy_alias=info['ea_desc'], enabled_axes=len(info['axes'])))
        snapshot.sort(key=lambda item: item['source'])
        payload = json.dumps(snapshot, sort_keys=True)
        import_id = digest((digest(manifest_bytes) + payload).encode())
        db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?,?,?)',
                   (import_id, digest(manifest_bytes), str(suite), payload, now))
        db.commit()
        groups = {}
        aliases = {}
        for item in snapshot:
            groups.setdefault(item['canonical_sha256'], []).append(item['template_id'])
            aliases.setdefault(item['legacy_alias'], []).append(item['template_id'])
        return dict(schema_version=1, import_id=import_id, templates=snapshot,
                    identical_settings_groups=[v for v in groups.values() if len(v) > 1],
                    alias_collisions={k:v for k,v in aliases.items() if len(v)>1},
                    source_mutations=0, deployment_lineage='not_imported',
                    semantic_range_validation='not_performed')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, type=Path)
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    if args.receipt.resolve().is_relative_to(args.suite.resolve()):
        raise ValueError('Receipt must be outside immutable source suite')
    result = import_suite(args.suite, args.registry)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.receipt.with_name(args.receipt.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    temporary.replace(args.receipt)
    print(json.dumps(dict(import_id=result['import_id'], templates=len(result['templates']),
                          identical_settings_groups=len(result['identical_settings_groups']),
                          alias_collisions=len(result['alias_collisions']))))


if __name__ == '__main__':
    main()
