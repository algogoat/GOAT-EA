"""MT5's tester profile, written from the run's own pinned [TesterInputs] right before every controller tester launch.

MT5 keeps the inputs an expert last ran in the tester in ``<terminal data>\\MQL5\\Profiles\\Tester\\<expert stem>.set``
(UTF-16LE with BOM, CRLF, ``name=value`` lines, numeric inputs with their ``||start||step||stop||Y/N`` tail). A
``/config`` launch applies its ``[TesterInputs]`` over that profile, with one exception: MT5 does not apply an empty
string value, it keeps the profile's last-used one. Since GOAT-EA#251/#252 the controller pins every input in
``[TesterInputs]``, omitted ones at their build defaults (``Sequence_Export_Id=`` among them), but Banker's hold-up
f01-starter-delay-20261020 (2026-10-20) still ran ``Sequence_Export_Id=export-1792494888-574031589-4``, left in
``GOAT V1.49.set`` by the previous exporting batch, and studio_tester_report.check() refused both members. Every
hold-up and catch-up after an exporting batch on the same terminal was refused that way.

So before every launch (hold-up, catch-up and seed members: SeedRunner._drive_passes; the native first /config
launch: studio_config_start) the controller writes that profile from the ``[TesterInputs]`` section of the exact
startup config MT5 is about to read, read back and checked against the config's recorded sha256, so MT5's "last used"
equals the pin, empty strings included (Claude-Mac, goatai#2587 6298549893 ruling 1). The profile and the config can
never differ: there is one source, the config bytes. Nothing is invented: the profile holds exactly the config's
input lines, in order, value for value (tails included). Comments and blank lines are not inputs and are left out.

Written only with MT5 stopped and under the native launch gate (native-gate\\launch.lock) held by the caller's launch,
atomically (a temporary file in the same folder, then os.replace) and read back. Only ``<expert stem>.set`` is
replaced; nothing else in Profiles\\Tester is read, changed or removed. The write returns a receipt (path, sha256,
config_sha256, the previous profile's sha256 and the input names whose value changed) that the caller records next
to the config sha, so a readback can prove what MT5 was given.
"""
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import uuid

PROFILE_FOLDER = ('MQL5', 'Profiles', 'Tester')
BOM = b'\xff\xfe'
SECTION = 'TesterInputs'
LINE_BREAK = re.compile(r'\r\n|\r|\n')
MAX_CONFIG_BYTES = 16 * 1024 * 1024
MAX_PROFILE_BYTES = 16 * 1024 * 1024
MAX_CHANGED_NAMES = 256           # a V1.49 profile has about 125 inputs: every changed name fits


def profile_path(install):
    """``<terminal_data_root>\\MQL5\\Profiles\\Tester\\<expert stem>.set`` for the installation's EA (e.g. GOAT V1.49)."""
    stem = PureWindowsPath(str(install['ea_relative_path'])).stem
    if not stem or stem in ('.', '..') or any(c in stem for c in '\\/:*?"<>|\x00'):
        raise ValueError('The installed EA path has no usable expert name for its MT5 tester profile')
    return Path(install['terminal_data_root']).joinpath(*PROFILE_FOLDER, stem + '.set')


def tester_inputs(config):
    """[(name, value)] of the one [TesterInputs] section of a controller-written startup config (UTF-16 bytes with BOM),
    exactly as written, in order. Refuses a config without exactly one such section, without inputs, or with a line
    that is not ``name=value``."""
    if not isinstance(config, (bytes, bytearray)) or not bytes(config).startswith(BOM):
        raise ValueError('The startup config is not UTF-16 with a byte order mark')
    text = bytes(config)[len(BOM):].decode('utf-16-le')
    section, found, rows, names = None, 0, [], set()
    for line in LINE_BREAK.split(text):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1].strip()
            found += section == SECTION
            continue
        if section != SECTION or not stripped or line.lstrip().startswith(';'):
            continue
        name, sep, value = line.partition('=')
        if not sep or not name:
            raise ValueError('The startup config has a [TesterInputs] line that is not name=value: ' + line[:80])
        if name in names:
            raise ValueError('The startup config sets tester input ' + name + ' twice')
        names.add(name)
        rows.append((name, value))
    if found != 1:
        raise ValueError('The startup config needs exactly one [TesterInputs] section (found %d)' % found)
    if not rows:
        raise ValueError('The startup config [TesterInputs] section sets no input')
    return rows


def render(rows):
    """MT5 tester-profile bytes of ``rows``: BOM, UTF-16LE, one ``name=value`` CRLF line per input, in order."""
    text = ''
    for name, value in rows:
        if not name or '=' in name or any(c in name + value for c in '\r\n\x00'):
            raise ValueError('Unsafe tester profile line: ' + name)
        text += name + '=' + value + '\r\n'
    return BOM + text.encode('utf-16-le')


def profile_for_config(config):
    """The tester profile bytes for one startup config: render(tester_inputs(config))."""
    return render(tester_inputs(config))


def _is_link(path):
    junction = getattr(os.path, 'isjunction', None)
    return path.is_symlink() or bool(junction and junction(path))


def _previous(path):
    """(sha256, {name: value}) of the profile being replaced; (None, None) when absent, values None when unreadable."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
    except FileNotFoundError:
        return None, None
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw[len(BOM):].decode('utf-16-le') if raw.startswith(BOM) else raw.decode('utf-8-sig')
        values = {}
        for line in LINE_BREAK.split(text):
            name, sep, value = line.partition('=')
            if sep and name and not line.lstrip().startswith(';'):
                values.setdefault(name, value)
        return digest, values
    except UnicodeError:
        return digest, None


def write_profile(install, config_path, *, config_sha256=None, inspect=None):
    """Replace the installation's MT5 tester profile with the [TesterInputs] of the startup config at ``config_path``.

    The caller holds the native launch gate and launches MT5 with this same config right after. ``config_sha256`` (the
    sha recorded when the config was written) must match the bytes read now; ``inspect`` (optional) re-reads the
    selected MT5 and must report it stopped (None). Raises ValueError/OSError before writing when anything does not
    hold; on success returns the receipt the caller records next to the config sha."""
    config_path = Path(config_path)
    with config_path.open('rb') as stream:
        config = stream.read(MAX_CONFIG_BYTES + 1)
    if len(config) > MAX_CONFIG_BYTES:
        raise ValueError('The startup config is larger than GOAT reads: ' + str(config_path))
    digest = hashlib.sha256(config).hexdigest()
    if config_sha256 is not None and digest != config_sha256:
        raise ValueError('The startup config changed since it was written, so GOAT did not write the tester profile and '
                         'launched nothing: ' + str(config_path))
    rows = tester_inputs(config)
    raw = render(rows)
    path = profile_path(install)
    data = Path(install['terminal_data_root'])
    for part in (data / 'MQL5', data / 'MQL5' / 'Profiles', path.parent, path):
        if _is_link(part):
            raise ValueError(str(part) + ' is a link or junction; GOAT never writes through it, so it launched nothing')
    if path.exists() and not path.is_file():
        raise ValueError('The MT5 tester profile ' + str(path) + ' is not a file; GOAT left it as it is and launched nothing')
    if inspect is not None and inspect() is not None:
        raise ValueError('MT5 is running, so GOAT did not write its tester profile; nothing was launched')
    previous_sha256, previous = _previous(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.goat-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        from studio_agent_mailbox import sharing_retry
        sharing_retry(lambda: os.replace(temporary, path))
    except BaseException:
        try:
            temporary.unlink()          # only GOAT's own temporary file; the profile itself is untouched
        except OSError:
            pass
        raise
    if path.read_bytes() != raw:
        raise ValueError('The MT5 tester profile did not read back as written: ' + str(path))
    written = dict(rows)
    changed = None if previous is None else sorted(name for name in set(written) | set(previous)
                                                   if written.get(name) != previous.get(name))
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), inputs=len(rows),
                config_path=str(config_path), config_sha256=digest, previous_sha256=previous_sha256,
                changed=None if changed is None else changed[:MAX_CHANGED_NAMES],
                changed_count=None if changed is None else len(changed))
