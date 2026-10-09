"""The installed EA's build ID, from its installed binary (goatai#2350 6089206538, Claude-Mac ruling 6089229465).

Source of truth: the receipt's ``ea_sha256`` (the installed EX5's SHA-256, verified against the file when the
receipt is loaded and before every start) mapped through ``PINNED_BUILDS``, the controller's own table of pinned
builds. The table is copied from ``candidate-builds/<build>/identity.json`` (``binary.sha256`` -> ``build_id``);
test_studio_installed_build asserts it equals those identities and that each retained EX5 hashes to its entry.
A binary that is not in the table is ``INSTALLED_BUILD_UNKNOWN``: it is refused, never guessed. The six EAs shipped
before build B38 (``PRE_B38_EXCLUDED``; evidence in shipped_ea_builds.json) refuse with the same code and a plain
sentence (``UPDATE_EA``), also on catch-up and hold-up paths that need no build (``refuse_pre_b38``). Not because
those flows need B38 (V1.48-SEQUENCE-EXPORT-1 already wrote .goatseq), but because evidence from a binary with no
recoverable build identity cannot be attributed to a build, so it can never feed the fit map or the registry.
Updating the EA is one action; refusing before anything is written is the honest outcome (Claude-Mac, #2350).

The EA's ``Common Files\\GOAT\\activation-status-<data folder>.json`` ``buildId`` is a cross-check only. The EA
writes that file on activation problems, so after a clean update it keeps the previous build (Banker,
2026-10-09: a B40 status from 2026-10-06 after the B43 install). A status observed before the EX5's install
time is stale and ignored (reported in ``status``); a status observed at or after it must name the same build,
or the read is refused with ``INSTALLED_BUILD_STATUS_CONFLICT`` naming both values.

Install time = the latest of the EX5 file's modification time and the receipt's ``installed_at`` and
``demo_installed_at``: every moment this binary may have been put in place. When none can be read, no status
can be shown stale, so any status is checked. The status time is its ``observedAtUtc`` (epoch seconds), or
the file's modification time when the EA wrote none.

Read-only: nothing here writes, launches or opens MT5.
"""
from datetime import datetime, timezone
import json
from pathlib import Path, PureWindowsPath

from studio_refusal import Refusal

UNKNOWN = 'INSTALLED_BUILD_UNKNOWN'
CONFLICT = 'INSTALLED_BUILD_STATUS_CONFLICT'
SOURCE = 'ea_binary_sha256'
MAX_STATUS_BYTES = 256 * 1024
MAX_BUILD_CHARS = 96

# binary.sha256 -> build_id of every candidate-builds/*/identity.json (test_studio_installed_build keeps them equal).
PINNED_BUILDS = {
    '7f03c9bae1e6367f0cff731f5ad1fa95599ca6e54ea5d8fb592efb85067e07df': 'V1.49-BETA17-38',
    '27226cfb61c02d066c7eabc0a598b0762b0ed055752ea9f14c5a7e2a01d5f517': 'V1.49-BETA17-39',
    '55d3e393ec80e73612b4305732d4066a925f429c98f80afbe46b41f67088b99b': 'V1.49-BETA17-40',
    'd5cbcbfd182f7ff18afce79c4245c2ac8ff1044ca3b7ec6e7cbfa663deee8913': 'V1.49-BETA17-41',
    'e630ee34cb04c26513f16860a927074ec745f3c62869d984260230a89fd4dc24': 'V1.49-BETA17-43',
    'e7e1c97f92f3ee1a58f46539336bb9baa63e203077dd218b21a82f05da2dfebc': 'V1.49-EA-EXPERIENCE-33',
    'f05a63c7a72a980d0ab442ba143be4241efcd2f96819bb7432e729e0b3800a33': 'V1.49-NDX-SYMBOL-MAP-31',
    '57e4062c354ab6feb9ecc3a65af3a072e02cedfe257d6f5d23eb34d64734758f': 'V1.49-START-PROTOCOL-ROUTE-30',
    '96ce46e60e8a8038be572b66d4b3b2f0b155fa9cc9d15c73dc0bb06fa3c73e0f': 'V1.49-TERMINAL-ISOLATION-32',
}


# Shipped before build B38 (Claude-Mac, goatai#2350 6089668580): never pinned, always refused with a plain
# "update the EA" sentence. The evidence for each (bundle records, admission rows) is in shipped_ea_builds.json.
PRE_B38_EXCLUDED = {
    'fab7b7fd3613cd94f6a8488e44851a25926a44bea45399713923079e636f951d': 'V1.48 EA in beta.2; no admission row names its build',
    '38912791a76988a62a95d05dcee41c3132c9ec35e859ac9894732c38f463c373': 'V1.48-SEQUENCE-EXPORT-1, beta.2 to beta.7',
    '62a882c362880fe2682a9d427125f9a551727eabe1463f00a6523c60cd429f61': 'V1.49-MONITOR-ONBOARDING-5, beta.7 to beta.10',
    'c59a3b318526304a12aea233f27365b85bc49626c0bec62721e0864adb5186ed': 'V1.49-ORPHAN-DIRECTORY-9, beta.11 build artifacts',
    '09ff4cb051a60105aebd43a3bf5857da8b1d4d304307800a47fc2fc8f731d2a9': 'V1.49 beta.11 candidate; no admission row names its build',
    'a1c09bd858897b8a3c99ea46e8dfb05db0a89c5ad22c1d8baa717afce429a838': 'V1.49-EXPORT-BACK-BOUNDARY-28, beta.11 to beta.15',
}
UPDATE_EA = 'This terminal runs an EA from before build B38. Update the EA in GOAT, then try again.'


class InstalledBuildError(Refusal):
    """The installed build cannot be stated: ``code`` is UNKNOWN or CONFLICT; ``detail`` is the diagnostic dict.

    A Refusal, so both CLIs print ``refusal_code`` beside the sentence. ``plain``: the sentence is for a person
    (a pre-B38 EA: UPDATE_EA) and callers pass it on unchanged.
    """

    def __init__(self, code, message, detail, *, plain=False):
        super().__init__(message if plain else code + ': ' + message, code, installed_build=detail)
        self.detail, self.plain = detail, plain


def refuse_pre_b38(install):
    """Strict catch-up and hold-up paths: refuse a pre-B38 EA with the plain update sentence. Read-only.

    Evidence from a binary with no recoverable build identity cannot be attributed to a build, so it could never feed
    the fit map or the registry; the user updates the EA in one action, and nothing is written before the refusal.
    """
    sha = install.get('ea_sha256')
    if isinstance(sha, str) and sha in PRE_B38_EXCLUDED:
        raise InstalledBuildError(UNKNOWN, UPDATE_EA, _excluded_detail(install, sha), plain=True)


def _excluded_detail(install, sha):
    return dict(build_id=None, source=SOURCE, ea_sha256=sha, registry='studio_installed_build.PRE_B38_EXCLUDED',
                excluded='pre_b38', excluded_reason=PRE_B38_EXCLUDED[sha])


def _utc(epoch):
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds')


def status_path(install):
    """``Common Files\\GOAT\\activation-status-<data folder>.json``: the EA's GoatTerminalToken file."""
    token = PureWindowsPath(install['terminal_data_root']).name or Path(install['terminal_data_root']).name
    return Path(install['common_files_root']) / 'GOAT' / ('activation-status-' + token + '.json')


def binary_path(install):
    relative = PureWindowsPath(str(install['ea_relative_path']))
    return Path(install['terminal_data_root']) / 'MQL5' / 'Experts' / Path(*relative.parts)


def install_time(install):
    """(epoch, source) of the latest moment the installed EX5 may have been put in place, or (None, None)."""
    found = []
    try:
        found.append((binary_path(install).stat().st_mtime, 'ea_binary_mtime'))
    except (OSError, KeyError, TypeError, ValueError):
        pass
    for key in ('installed_at', 'demo_installed_at'):
        value = install.get(key)
        if not isinstance(value, str):
            continue
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            continue   # a time without a zone cannot be ordered against UTC evidence
        found.append((stamp.timestamp(), 'receipt_' + key))
    return max(found) if found else (None, None)


def _status(install):
    """The activation status as evidence: path, state, build_id, observed epoch and its source. Never raises."""
    path = status_path(install)
    out = dict(path=str(path), state='missing', build_id=None, observed_utc=None, observed_source=None)
    try:
        if not path.is_file():
            return out, None
        stat = path.stat()
        if stat.st_size > MAX_STATUS_BYTES:
            return dict(out, state='unreadable'), None
        value = json.loads(path.read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return dict(out, state='unreadable'), None
    if not isinstance(value, dict):
        return dict(out, state='unreadable'), None
    build = value.get('buildId')
    if not isinstance(build, str) or not 0 < len(build) <= MAX_BUILD_CHARS:
        return dict(out, state='no_build'), None
    observed = value.get('observedAtUtc')
    if type(observed) is int and observed > 0:
        epoch, source = float(observed), 'observedAtUtc'
    else:
        epoch, source = stat.st_mtime, 'file_mtime'
    return dict(out, state='read', build_id=build, observed_utc=_utc(epoch), observed_source=source), epoch


def resolve(install):
    """The installed build and how it was established. Raises InstalledBuildError (UNKNOWN, CONFLICT)."""
    sha = install.get('ea_sha256')
    build = PINNED_BUILDS.get(sha) if isinstance(sha, str) else None
    installed_epoch, installed_source = install_time(install)
    status, observed = _status(install)
    detail = dict(build_id=build, source=SOURCE, ea_sha256=sha, registry='studio_installed_build.PINNED_BUILDS',
                  install_time_utc=_utc(installed_epoch), install_time_source=installed_source, status=status)
    short = (sha or '?')[:12]
    refuse_pre_b38(install)
    if build is None:
        raise InstalledBuildError(UNKNOWN, 'the installed EA binary (sha256 %s) is not a pinned GOAT build, so its build is not known; '
                                  'install a pinned build (activation status: %s)' % (short, _status_words(status)), dict(detail))
    if status['state'] == 'read':
        if installed_epoch is not None and observed < installed_epoch:
            status['state'] = 'stale'
        elif status['build_id'] != build:
            status['state'] = 'conflict'
            raise InstalledBuildError(CONFLICT, 'the installed EA binary (sha256 %s) is %s, but its activation status observed %s, '
                                      'at or after the install at %s, reports %s; nothing is assumed'
                                      % (short, build, status['observed_utc'], _utc(installed_epoch) or 'an unknown time',
                                         status['build_id']), dict(detail))
        else:
            status['state'] = 'agrees'
    detail['basis'] = 'from its binary sha256 %s (%s); activation status %s' % (short, detail['registry'], _status_words(status, detail))
    return detail


def _status_words(status, detail=None):
    state = status['state']
    if state == 'stale':
        return '%s observed %s predates the install at %s (%s), ignored as stale' % (
            status['build_id'], status['observed_utc'], detail['install_time_utc'], detail['install_time_source'])
    if state == 'agrees':
        return '%s observed %s agrees' % (status['build_id'], status['observed_utc'])
    if state == 'read':
        return '%s observed %s' % (status['build_id'], status['observed_utc'])
    return dict(missing='missing', unreadable='unreadable, not used', no_build='names no build, not used').get(state, state)


def build_id(install, *, strict=True):
    """The installed build ID. ``strict``: raise InstalledBuildError; otherwise None when it cannot be stated."""
    try:
        return resolve(install)['build_id']
    except InstalledBuildError:
        if strict:
            raise
        return None


def public(install):
    """Never raises: the resolution for a status read (build_id None plus ``code``/``message`` when refused)."""
    try:
        return dict(resolve(install), code=None, message=None)
    except InstalledBuildError as error:
        return dict(error.detail, build_id=None, code=error.code, message=str(error))
    except (KeyError, TypeError, AttributeError) as error:
        return dict(build_id=None, source=SOURCE, code=UNKNOWN, message=UNKNOWN + ': the installation receipt cannot be read ('
                    + str(error)[:200] + ')')
