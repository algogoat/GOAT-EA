"""GOAT peers: other GOAT-owned MT5 terminals on this PC that may keep running.

goatai#1885 (2026-10-05): opening Terminal 3 for a demo blocked Banker until it
closed ("Unmapped terminal process requires ownership inspection"), and the one
reviewed protected peer (policy.json) holds a single terminal, so reviewing a
second one replaced the first.

A GOAT peer is exempt from that refusal and from nothing else. It is never
read, closed, launched or written to, it is never part of a package binding,
and it never shares this terminal's batch folder: at every native start
studio_terminal_isolation.preflight still refuses any live terminal resolving
to this terminal's namespace GOAT\\<EA>-<server>-<login>-<terminal hash>.

The effective peers of a terminal are:

1. the reviewed peer in policy.json (studio_protected_peer), unchanged and never
   rewritten here: strict executable-bytes identity, the ``protected`` role,
   bound into every prepared package;
2. peers.json: terminals registered with peer-add (the peer need not run);
3. GOAT installation receipts on this PC
   (%LOCALAPPDATA%\\GOAT Portfolio Desktop\\suite\\*\\installation.json),
   recognised automatically, so opening another GOAT terminal never blocks;
minus the terminals peer-remove excluded.

A running terminal64.exe is a GOAT peer (2 or 3) only when, at that moment:
(a) this lane runs an isolated EA (V1.49 per-terminal/login batch folders);
(b) its data folder belongs to it: origin.txt there names its folder, or a
    portable terminal's own folder holds MQL5;
(c) that data folder and its program folder overlap none of this terminal's
    program, data, controller state or Common Files folders;
(d) the data folder hashes to a different batch namespace than this terminal;
(e) its terminal64.exe has a Valid Authenticode signature from MetaQuotes. The
    identity is the program path, data folder and origin.txt binding, never the
    bytes: an MT5 live update is accepted on the signature and journaled as
    ``peer_binary_changed`` by the next start;
(f) every record naming it (peers.json, receipts) gives the same data folder.
Everything else still refuses with the historical message prefix.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess

from campaign_ledger import sha
from studio_installation import read_json
from studio_subprocess import background_creationflags

ROSTER = 'peers.json'
JOURNAL = 'peer-roster.jsonl'
POLICY_FOLDER = '.studio-peer-policy'
UNMAPPED = 'Unmapped terminal process requires ownership inspection'
NOT_A_PEER = ('is not this terminal, its reviewed peer or one of its GOAT peers. Ask the user to close it, or, '
              'with their yes, register it with peer-add (see "Keep another MT5 running")')
NOT_REVIEWED = ('is not the selected terminal or its reviewed peer. Ask the user to close it; '
                'never close it yourself')
SIGNER = 'MetaQuotes Ltd.'
SIGNER_ORGANISATIONS = frozenset((SIGNER, 'MetaQuotes Software Corp.'))
# Fixed command; the path travels in an environment variable, never in shell syntax.
SIGNATURE_COMMAND = ('$ErrorActionPreference="Stop"; '
                     '$s=Get-AuthenticodeSignature -LiteralPath $env:GOAT_PEER_EXECUTABLE; '
                     'ConvertTo-Json -Compress -InputObject @{status=[string]$s.Status; '
                     'subject=[string]$s.SignerCertificate.Subject; thumbprint=[string]$s.SignerCertificate.Thumbprint}')
INVENTORY_COMMAND = ('ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter '
                     '"Name=\'terminal64.exe\' OR Name=\'terminal.exe\'" | Select-Object ProcessId,ExecutablePath,'
                     '@{Name="CreatedUtc";Expression={$_.CreationDate.ToUniversalTime().ToString("o")}})')
RECEIPT_PATHS = ('terminal_executable', 'terminal_data_root', 'controller_state_root')
_VALID_SIGNATURES = {}


class Unbound(ValueError):
    """The data folder named for a terminal does not (or no longer does) belong to it."""


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def suite_root():
    """Where GOAT desktop keeps one folder per installed terminal (its receipt and controller state)."""
    base = os.environ.get('LOCALAPPDATA')
    return Path(base) / 'GOAT Portfolio Desktop' / 'suite' if base else None


def policy_folder(data_root):
    """This terminal's peer policy folder, beside policy.json (studio_protected_peer.directory)."""
    return Path(data_root) / 'MQL5' / 'Files' / POLICY_FOLDER


def _same(left, right):
    return PureWindowsPath(str(left)) == PureWindowsPath(str(right))


def _overlap(left, right):
    left, right = PureWindowsPath(str(left)), PureWindowsPath(str(right))
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def peer_id(executable, data_root):
    text = str(PureWindowsPath(str(executable))).casefold() + '|' + str(PureWindowsPath(str(data_root))).casefold()
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# ------------------------------------------------------------------- the lane

def lane_of(binding, *, controller_state_root=None):
    """This research lane as the peer rules need it, or None when it has no GOAT peers.

    Only an isolated EA (V1.49) keeps its batch state apart from every other
    terminal, so only such a lane exempts GOAT peers. Others keep the reviewed
    peer's exact-instance rule alone.
    """
    from studio_terminal_isolation import isolated
    executable, data = binding.get('research_terminal'), binding.get('research_data_root')
    if not isinstance(executable, str) or not executable or not isinstance(data, str) or not data:
        return None
    if not isolated(binding.get('ea_version')):
        return None
    others = [root for root in (binding.get('common_files_root'), controller_state_root)
              if isinstance(root, str) and root]
    return dict(executable=executable, data_root=data, ea_version=binding['ea_version'], other_roots=others)


def controller_lane(c):
    i = c.install
    return lane_of(dict(research_terminal=i['terminal_executable'], research_data_root=i['terminal_data_root'],
                        ea_version=i['ea_version'], common_files_root=i['common_files_root']),
                   controller_state_root=i['controller_state_root'])


# ------------------------------------------------------------ peer evidence

def binding_proof(executable, data_root):
    """(b): the origin.txt binding of data_root to executable; its sha256, None for a portable folder."""
    exe, data = PureWindowsPath(str(executable)), PureWindowsPath(str(data_root))
    if not exe.is_absolute() or not data.is_absolute():
        raise Unbound('the paths are not absolute')
    if exe.name.casefold() != 'terminal64.exe' or not Path(exe).is_file():
        raise Unbound(str(exe) + ' is not an existing terminal64.exe')
    if not (Path(data) / 'MQL5').is_dir():
        raise Unbound(str(data) + ' has no MQL5 folder')
    if data == exe.parent:
        return None   # Portable: the program folder is its own data folder.
    origin = Path(data) / 'origin.txt'
    if not origin.is_file():
        raise Unbound(str(data) + ' has no origin.txt binding it to ' + str(exe.parent))
    raw = origin.read_bytes()
    try:
        text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise Unbound(str(origin) + ' is unreadable') from None
    named = text.strip().strip('\x00').strip()
    if not named or PureWindowsPath(named) != exe.parent:
        raise Unbound(str(origin) + ' names ' + (named or 'nothing') + ', not ' + str(exe.parent))
    return hashlib.sha256(raw).hexdigest()


def separate(lane, executable, data_root):
    """(c) and (d): the peer never overlaps this terminal and never shares its batch namespace."""
    from studio_terminal_isolation import terminal_hash
    exe, data = PureWindowsPath(str(executable)), PureWindowsPath(str(data_root))
    own = [PureWindowsPath(lane['executable']).parent, PureWindowsPath(lane['data_root']),
           *(PureWindowsPath(root) for root in lane['other_roots'])]
    if exe == PureWindowsPath(lane['executable']):
        raise ValueError('it is this terminal itself')
    if any(_overlap(path, root) for path in (exe.parent, data) for root in own):
        raise ValueError('its program or data folder overlaps this terminal\'s program, data, controller state '
                         'or Common Files folder')
    if data == PureWindowsPath(lane['data_root']) or terminal_hash(str(data)) == terminal_hash(lane['data_root']):
        raise ValueError('its data folder ' + str(data) + ' has this terminal\'s batch namespace (terminal hash '
                         + terminal_hash(lane['data_root']) + '); two terminals never share one')
    return terminal_hash(str(data))


def organisation(subject):
    match = re.search(r'(?:^|,)\s*O=(?:"([^"]*)"|([^,]*))', subject or '')
    return ((match.group(1) if match.group(1) is not None else match.group(2)).strip()) if match else ''


def signer_ok(signer):
    return (isinstance(signer, dict) and signer.get('status') == 'Valid'
            and organisation(signer.get('subject')) in SIGNER_ORGANISATIONS)


def signature(executable):
    """(e): Authenticode status and signer of one terminal64.exe. Only a valid result is cached."""
    path = Path(executable)
    stat = path.stat()
    key = (str(PureWindowsPath(str(path))).casefold(), stat.st_size, stat.st_mtime_ns)
    if key in _VALID_SIGNATURES:
        return dict(_VALID_SIGNATURES[key])
    output = subprocess.check_output(['powershell', '-NoProfile', '-Command', SIGNATURE_COMMAND], text=True,
                                     encoding='utf-8-sig', timeout=60, creationflags=background_creationflags(),
                                     env=dict(os.environ, GOAT_PEER_EXECUTABLE=str(path)))
    value = json.loads(output)
    if not isinstance(value, dict):
        raise ValueError('Authenticode result unreadable for ' + str(path))
    result = {key_: str(value.get(key_) or '') for key_ in ('status', 'subject', 'thumbprint')}
    if signer_ok(result):
        _VALID_SIGNATURES[key] = dict(result)
    return result


def signature_refusal(executable, signer):
    """Amendment A (#1885): name the signer that was seen."""
    subject = (signer or {}).get('subject') or ''
    seen = organisation(subject) or subject
    status = (signer or {}).get('status') or 'unknown'
    if not seen:
        return 'terminal64.exe at ' + str(executable) + ' is not signed (Authenticode ' + status + '), not by ' + SIGNER
    if seen in SIGNER_ORGANISATIONS:
        return ('terminal64.exe at ' + str(executable) + ' carries a ' + seen + ' signature that Windows does not '
                'accept (Authenticode ' + status + ')')
    return ('terminal64.exe at ' + str(executable) + ' is signed by ' + seen + ', not ' + SIGNER
            + ' (Authenticode ' + status + ')')


# ------------------------------------------------------------- the sources

def receipts(lane, root=None):
    """GOAT installation receipts of the other terminals on this PC: (usable, skipped with reason)."""
    root = suite_root() if root is None else Path(root)
    found, skipped = [], []
    if root is None or not root.is_dir():
        return found, skipped
    for folder in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        path = folder / 'installation.json'
        if not folder.is_dir() or not path.is_file():
            continue
        try:
            value = read_json(path)
            if not isinstance(value, dict) or value.get('schema_version') != 1:
                raise ValueError('not a version 1 GOAT installation receipt')
            if any(not isinstance(value.get(key), str) or not PureWindowsPath(value[key]).is_absolute()
                   for key in RECEIPT_PATHS):
                raise ValueError('its terminal and controller paths are not absolute')
            if not _same(value['controller_state_root'], folder):
                raise ValueError('its controller_state_root is not the receipt\'s own folder (a copied receipt)')
        except (OSError, ValueError) as exc:
            skipped.append(dict(receipt_path=str(path), reason=str(exc)))
            continue
        if _same(value['terminal_executable'], lane['executable']):
            continue   # This terminal's own receipt.
        found.append(dict(receipt_path=str(path), executable=value['terminal_executable'],
                          data_root=value['terminal_data_root'], ea_version=value.get('ea_version'),
                          controller_state_root=value['controller_state_root']))
    return found, skipped


def empty_roster(lane):
    return dict(schema_version=1, target=dict(terminal_executable=lane['executable'],
                                              terminal_data_root=lane['data_root']), peers=[], excluded=[])


def read_roster(folder, lane):
    path = Path(folder) / ROSTER
    if not path.is_file():
        return empty_roster(lane)
    value = read_json(path)
    target = value.get('target') if isinstance(value, dict) else None
    if (not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(target, dict)
            or not _same(target.get('terminal_executable') or '?', lane['executable'])
            or not _same(target.get('terminal_data_root') or '?', lane['data_root'])
            or not isinstance(value.get('peers'), list) or not isinstance(value.get('excluded'), list)
            or any(not isinstance(item, dict) or not isinstance(item.get('executable'), str)
                   or not isinstance(item.get('data_root'), str) for item in value['peers'])
            or any(not isinstance(item, dict) or not isinstance(item.get('executable'), str)
                   for item in value['excluded'])):
        raise ValueError('GOAT peer roster ' + str(path) + ' is not recognised for this terminal; preserve it for review')
    return value


def sources_for(executable, *, roster, found):
    sources = [dict(source=item.get('source') or 'user_reviewed', record=str(ROSTER), data_root=item['data_root'],
                    receipt_path=item.get('receipt_path')) for item in roster['peers'] if _same(item['executable'], executable)]
    sources += [dict(source='goat_receipt', record=item['receipt_path'], data_root=item['data_root'],
                     receipt_path=item['receipt_path']) for item in found if _same(item['executable'], executable)]
    return sources


def resolve(lane, executable, *, roster, found, signature_check=None):
    """(peer, None) when executable is an eligible GOAT peer of lane now, else (None, plain reason)."""
    image = PureWindowsPath(str(executable))
    for item in roster['excluded']:
        if _same(item['executable'], image):
            return None, ('was removed from this terminal\'s GOAT peers (peer-remove, ' + str(item.get('removed_utc'))
                          + '). Ask the user to close it, or peer-add it again with their yes')
    sources = sources_for(image, roster=roster, found=found)
    if not sources:
        return None, NOT_A_PEER
    roots = []
    for item in sources:
        if not any(_same(item['data_root'], root) for root in roots):
            roots.append(item['data_root'])
    records = ', '.join(sorted({item['record'] for item in sources}))
    if len(roots) > 1:
        # (f) strict (#1885): any mismatch between sources refuses; nothing is guessed.
        return None, ('is named with different data folders by its GOAT records (' + ' vs '.join(roots) + '; '
                      + records + '). Run peer-list; if MT5 moved, repair that installation in GOAT or peer-remove '
                      'the stale entry, then peer-add it again')
    data_root = roots[0]
    try:
        origin = binding_proof(image, data_root)
        namespace = separate(lane, image, data_root)
    except Unbound as exc:
        return None, ('is recorded with data folder ' + data_root + ' (' + records + '), but ' + str(exc)
                      + '. If MT5 moved or was reinstalled, run peer-list and register the folder MT5 shows in '
                      'File > Open Data Folder')
    except ValueError as exc:
        return None, ('cannot be a GOAT peer: ' + str(exc))
    signer = (signature_check or signature)(str(image))
    if not signer_ok(signer):
        return None, ('cannot be a GOAT peer: ' + signature_refusal(image, signer) + '. Inspect it, then peer-add '
                      'it again only with the user\'s yes')
    return dict(peer_id=peer_id(image, data_root), executable=str(image), data_root=data_root, origin_sha256=origin,
                namespace_hash=namespace, sources=sources, signer=signer), None


def lookup_for(binding, *, controller_state_root=None, suite=None, signature_check=None):
    """A read-only peer lookup for studio_process_check.classify_processes, or None (no GOAT peers).

    Nothing is read until a terminal that is neither this one nor its reviewed
    peer is seen, so an ordinary check costs nothing extra.
    """
    lane = lane_of(binding, controller_state_root=controller_state_root)
    if lane is None:
        return None
    cache = {}

    def lookup(image, pid=None):
        try:
            if 'roster' not in cache:
                cache['roster'] = read_roster(policy_folder(lane['data_root']), lane)
                cache['found'] = receipts(lane, suite)[0]
            return resolve(lane, image, roster=cache['roster'], found=cache['found'], signature_check=signature_check)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return None, 'cannot be checked as a GOAT peer: ' + str(exc)
    return lookup


def lookup_for_controller(c, **options):
    i = c.install
    return lookup_for(dict(research_terminal=i['terminal_executable'], research_data_root=i['terminal_data_root'],
                           ea_version=i['ea_version'], common_files_root=i['common_files_root']),
                      controller_state_root=i['controller_state_root'], **options)


# ------------------------------------------------------------------ journal

def journal_rows(folder):
    path = Path(folder) / JOURNAL
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue   # A torn final line from an interrupted append records nothing.
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append(folder, row):
    with (Path(folder) / JOURNAL).open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return row


def record_seen(c, observed, *, source):
    """Journal the GOAT peers a start's own process check saw (append-only, never rewritten).

    One ``peer_seen`` row per new process instance; ``peer_binary_changed`` when the
    peer's terminal64.exe bytes differ from the last row (an MT5 live update the
    signature rule accepted), with the old and new SHA-256 and the signer.
    """
    if not observed:
        return []
    from studio_native_gate import exclusive_gate
    folder = policy_folder(c.install['terminal_data_root'])
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    with exclusive_gate(folder):
        last = {}
        for row in journal_rows(folder):
            if row.get('event') in ('peer_seen', 'peer_binary_changed') and isinstance(row.get('peer_id'), str):
                last[row['peer_id']] = row
        for peer in observed:
            executable = Path(peer['executable'])
            stat = executable.stat()
            binary = dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            process = dict(pid=peer['pid'], created_utc=peer['created_utc'])
            prior = last.get(peer['peer_id'])
            if prior and prior.get('process') == process and prior.get('binary') == binary:
                continue
            digest = prior['executable_sha256'] if prior and prior.get('binary') == binary else file_sha256(executable)
            changed = bool(prior) and prior.get('executable_sha256') != digest
            row = dict(schema_version=1, event='peer_binary_changed' if changed else 'peer_seen',
                       recorded_utc=now_utc(), peer_id=peer['peer_id'], executable=str(executable),
                       data_root=peer['data_root'], process=process, binary=binary, executable_sha256=digest,
                       previous_process=prior.get('process') if prior else None,
                       previous_executable_sha256=prior.get('executable_sha256') if prior else None,
                       signer=signature(executable) if changed else None, source=source)
            written.append(append(folder, row))
            last[peer['peer_id']] = row
    return written


# ---------------------------------------------------------------- commands

def refuse_under_owner_stop(c):
    # Amendment B (#1885): owner STOP is the person's "change nothing" switch.
    if (Path(c.root) / 'demo-agent' / 'STOP').exists():
        raise ValueError('Owner STOP is on: peer-add and peer-remove change nothing while it is set. '
                         'peer-list still works; ask the owner before clearing STOP')


def _reviewed(c):
    """The reviewed policy.json peer, read as is (never rewritten here)."""
    path = policy_folder(c.install['terminal_data_root']) / 'policy.json'
    if not path.is_file():
        return None
    value = read_json(path)
    peer = value.get('peer') if isinstance(value, dict) else None
    return value if isinstance(peer, dict) and isinstance(peer.get('executable'), str) else None


def _terminal(path):
    exe = PureWindowsPath(str(path))
    if not exe.is_absolute() or exe.name.casefold() != 'terminal64.exe':
        raise ValueError('Give the peer\'s full terminal64.exe path, e.g. --terminal "G:\\MT5\\Terminal 3\\terminal64.exe"')
    return exe


def _session_lane(c):
    path = Path(c.root) / 'session.json'
    try:
        return read_json(path).get('authority_kind') if path.is_file() else None
    except (OSError, ValueError):
        return None


def add(c, terminal, data_root=None, *, confirmed=False, signature_check=None, suite=None):
    """peer-add: register another terminal as a GOAT peer of this one; it need not be running.

    Without ``confirmed`` this is a preview: the exact data folder, its
    origin.txt binding and the batch namespace hash the peer will be held to.
    With it, peers.json gains the entry and peer-roster.jsonl the receipt. No
    package binding, policy.json or MT5 state changes.
    """
    from studio_native_gate import exclusive_gate
    refuse_under_owner_stop(c)
    lane = controller_lane(c)
    if lane is None:
        raise ValueError('GOAT peers need this terminal on GOAT EA V1.49 (each terminal keeps its own batch folder). '
                         'On this build keep using peer-prepare and peer-apply with the peer running')
    exe = _terminal(terminal)
    reviewed = _reviewed(c)
    if reviewed is not None and _same(reviewed['peer']['executable'], exe):
        return dict(status='already_reviewed_peer', peer=reviewed['peer'], review_id=reviewed.get('review_id'),
                    plain='This MT5 is already this terminal\'s reviewed peer (policy.json); nothing to add.')
    found, _ = receipts(lane, suite)
    named = [item for item in found if _same(item['executable'], exe)]
    if named:
        roots = []
        for item in named:
            if not any(_same(item['data_root'], root) for root in roots):
                roots.append(item['data_root'])
        if len(roots) > 1:
            raise ValueError('GOAT receipts name different data folders for ' + str(exe) + ' (' + ' vs '.join(roots)
                             + '); repair those installations in GOAT first')
        if data_root is not None and not _same(data_root, roots[0]):
            raise ValueError('GOAT receipt ' + named[0]['receipt_path'] + ' names data folder ' + roots[0] + ' for '
                             + str(exe) + ', not ' + str(data_root) + '. One peer has one data folder: if MT5 moved, '
                             'repair that installation in GOAT so its receipt names the new folder')
        root, source, receipt_path = roots[0], 'goat_receipt', named[0]['receipt_path']
    else:
        if data_root is None:
            raise ValueError('No GOAT installation receipt on this PC names ' + str(exe) + '. Give its data folder with '
                             '--data-root (in that MT5: File > Open Data Folder)')
        root, source, receipt_path = str(PureWindowsPath(str(data_root))), 'user_reviewed', None
    try:
        origin = binding_proof(exe, root)
        namespace = separate(lane, exe, root)
    except ValueError as exc:
        raise ValueError('Cannot add ' + str(exe) + ' as a GOAT peer: ' + str(exc)) from None
    signer = (signature_check or signature)(str(exe))
    if not signer_ok(signer):
        raise ValueError('Cannot add ' + str(exe) + ' as a GOAT peer: ' + signature_refusal(exe, signer))
    from studio_terminal_isolation import terminal_hash
    record = dict(peer_id=peer_id(exe, root), executable=str(exe), data_root=root, origin_sha256=origin,
                  namespace_hash=namespace, source=source, receipt_path=receipt_path,
                  executable_sha256_at_add=file_sha256(exe), signer_at_add=signer, lane=_session_lane(c))
    held_to = dict(data_root=root, namespace_hash=namespace, own_namespace_hash=terminal_hash(lane['data_root']),
                   origin_binding=('portable: ' + root + ' is the program folder' if origin is None else
                                   root + '\\origin.txt names ' + str(exe.parent) + ' (sha256 ' + origin + ')'),
                   signer=organisation(signer.get('subject')), rule='exe path + data folder + origin.txt binding; '
                   'new MT5 bytes only with a Valid MetaQuotes Authenticode signature')
    if not confirmed:
        return dict(status='preview', peer=record, held_to=held_to,
                    effect='Exempts this MT5 from the "unmapped terminal" refusal only. GOAT never reads, closes, '
                           'launches or writes to it, never shares its batch folder, and prepared batches stay valid.',
                    next_action='Show the user the data folder and namespace above. With their yes, run peer-add again '
                                'with --confirm-reviewed.')
    folder = policy_folder(lane['data_root'])
    folder.mkdir(parents=True, exist_ok=True)
    with exclusive_gate(folder):
        roster = read_roster(folder, lane)
        before = sha(roster)
        existing = [item for item in roster['peers'] if _same(item['executable'], exe)]
        excluded = [item for item in roster['excluded'] if _same(item['executable'], exe)]
        if existing and not excluded and all(_same(item['data_root'], root) for item in existing):
            return dict(status='unchanged', peer=existing[0], held_to=held_to, roster=str(folder / ROSTER))
        record['added_utc'] = now_utc()
        roster['peers'] = [item for item in roster['peers'] if not _same(item['executable'], exe)] + [record]
        roster['excluded'] = [item for item in roster['excluded'] if not _same(item['executable'], exe)]
        from studio_bridge import write_json
        write_json(folder / ROSTER, roster)
        receipt = append(folder, dict(schema_version=1, event='peer_added', recorded_utc=record['added_utc'],
                                      peer=record, replaced=existing or None, readmitted=excluded or None,
                                      roster_sha256_before=before, roster_sha256_after=sha(roster),
                                      lane=record['lane']))
    return dict(status='peer_added', peer=record, held_to=held_to, receipt=receipt,
                roster=str(folder / ROSTER), journal=str(folder / JOURNAL))


def remove(c, terminal, *, confirmed=False, suite=None):
    """peer-remove: stop exempting a terminal; also excludes it from auto-recognition."""
    from studio_native_gate import exclusive_gate
    refuse_under_owner_stop(c)
    exe = _terminal(terminal)
    reviewed = _reviewed(c)
    if reviewed is not None and _same(reviewed['peer']['executable'], exe):
        raise ValueError('This MT5 is the reviewed peer in policy.json, bound into this terminal\'s prepared batches; '
                         'peer-remove leaves it unchanged')
    lane = dict(executable=c.install['terminal_executable'], data_root=c.install['terminal_data_root'], other_roots=[])
    folder = policy_folder(lane['data_root'])
    found, _ = receipts(lane, suite)
    folder.mkdir(parents=True, exist_ok=True)
    with exclusive_gate(folder):
        roster = read_roster(folder, lane)
        entries = [item for item in roster['peers'] if _same(item['executable'], exe)]
        auto = [item for item in found if _same(item['executable'], exe)]
        if any(_same(item['executable'], exe) for item in roster['excluded']) and not entries:
            return dict(status='unchanged', excluded=str(exe), roster=str(folder / ROSTER))
        if not entries and not auto:
            raise ValueError(str(exe) + ' is not a GOAT peer of this terminal; peer-list shows them')
        exclusion = dict(executable=str(exe), removed_utc=now_utc(),
                         peer_ids=sorted({peer_id(exe, item['data_root']) for item in entries + auto}))
        if not confirmed:
            return dict(status='preview', removes=entries, excludes=exclusion, auto_recognised=auto,
                        effect='While it runs, this MT5 blocks this terminal again ("Unmapped terminal process").',
                        next_action='With the user\'s yes, run peer-remove again with --confirm-reviewed.')
        before = sha(roster)
        roster['peers'] = [item for item in roster['peers'] if not _same(item['executable'], exe)]
        roster['excluded'] = roster['excluded'] + [exclusion]
        from studio_bridge import write_json
        write_json(folder / ROSTER, roster)
        receipt = append(folder, dict(schema_version=1, event='peer_removed', recorded_utc=exclusion['removed_utc'],
                                      executable=str(exe), removed=entries or None, excluded=exclusion,
                                      roster_sha256_before=before, roster_sha256_after=sha(roster),
                                      lane=_session_lane(c)))
    return dict(status='peer_removed', removed=entries, excluded=exclusion, receipt=receipt,
                roster=str(folder / ROSTER), journal=str(folder / JOURNAL))


def _running():
    rows = json.loads(subprocess.check_output(['powershell', '-NoProfile', '-Command', INVENTORY_COMMAND], text=True,
                                              encoding='utf-8-sig', timeout=20, creationflags=background_creationflags()))
    if not isinstance(rows, list):
        raise ValueError('Complete terminal inventory required')
    return rows


def listing(c, *, signature_check=None, suite=None, inventory=True):
    """peer-list: read-only. Every peer source, whether it is eligible now and why not, and what runs."""
    i = c.install
    lane = controller_lane(c)
    folder = policy_folder(i['terminal_data_root'])
    plain_lane = lane or dict(executable=i['terminal_executable'], data_root=i['terminal_data_root'], other_roots=[])
    reviewed = _reviewed(c)
    result = dict(terminal=i['terminal_executable'], data_root=i['terminal_data_root'], goat_peers_enabled=lane is not None,
                  policy_folder=str(folder), reviewed_peer=None, peers=[], excluded=[], skipped_receipts=[],
                  running=None, blocking=[])
    if reviewed is not None:
        from studio_protected_peer import policy
        try:
            policy(c)
            state = 'protected'
        except (OSError, ValueError) as exc:
            state = 'refused: ' + str(exc)
        result['reviewed_peer'] = dict(executable=reviewed['peer']['executable'], data_root=reviewed['peer'].get('data_root'),
                                       review_id=reviewed.get('review_id'), source='reviewed_policy', status=state,
                                       rule='strict: executable bytes, data root and origin; bound into prepared batches')
    if lane is None:
        result['plain'] = 'This terminal runs an EA without per-terminal batch folders, so only the reviewed peer may run.'
    roster = read_roster(folder, plain_lane)
    found, skipped = receipts(plain_lane, suite)
    result['skipped_receipts'] = skipped
    result['excluded'] = roster['excluded']
    names = []
    for item in roster['peers'] + found:
        if not any(_same(item['executable'], name) for name in names):
            names.append(item['executable'])
    for name in names:
        entry = dict(executable=name, sources=sources_for(name, roster=roster, found=found))
        if lane is None:
            entry.update(eligible=False, reason='GOAT peers need this terminal on GOAT EA V1.49')
        else:
            peer, reason = resolve(lane, name, roster=roster, found=found, signature_check=signature_check)
            entry.update(eligible=peer is not None, reason=reason)
            if peer is not None:
                entry.update(data_root=peer['data_root'], namespace_hash=peer['namespace_hash'],
                             origin_sha256=peer['origin_sha256'], signer=organisation(peer['signer'].get('subject')))
        if reviewed is not None and _same(reviewed['peer']['executable'], name):
            entry['note'] = 'also the reviewed peer; the reviewed (strict) rule applies'
        result['peers'].append(entry)
    if inventory:
        rows = _running()
        result['running'] = [dict(pid=row.get('ProcessId'), executable=row.get('ExecutablePath'),
                                  created_utc=row.get('CreatedUtc')) for row in rows]
        for row in result['running']:
            image = row['executable']
            if not image or _same(image, i['terminal_executable']):
                continue
            if reviewed is not None and _same(image, reviewed['peer']['executable']):
                continue
            entry = next((item for item in result['peers'] if _same(item['executable'], image)), None)
            if entry is not None and entry['eligible']:
                entry.setdefault('running_pids', []).append(row['pid'])
                continue
            reason = (entry or {}).get('reason') or (NOT_A_PEER if lane else NOT_REVIEWED)
            excluded = next((item for item in roster['excluded'] if _same(item['executable'], image)), None)
            if excluded is not None and lane is not None:
                reason = resolve(lane, image, roster=roster, found=found, signature_check=signature_check)[1]
            result['blocking'].append(dict(row, reason=UNMAPPED + ': ' + str(image) + ' (PID ' + str(row['pid']) + ') '
                                           + reason))
    return result
