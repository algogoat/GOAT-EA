"""Trading-equivalence certificate and empirical canary for OOS catch-up (goat-trading-equivalence-v1).

A catch-up re-test is comparable only on the EA build that made the export. This module
lets a newer installed build stand in for the export's build when, and only when, both
of these hold (Claude-Mac, algogoat/goatai#1885, comments 5974337974 and 5974343541):

1. **Source equivalence, by exclusion.** The certificate covers the EA's FULL source
   dependency closure: every ``#include "..."``, ``#resource``, ``#property icon`` and
   input declaration reachable from the entrypoint (``GOAT V1.49.mq5``), plus the names of
   every external dependency (standard-library ``#include <...>``, MQL5-root resources such
   as the MACD indicator, unversioned binary resources such as MTTester's ``RunMe.ex5``,
   ``#import`` DLLs and ``iCustom`` literals; these cannot be hashed from git, so they are
   compared by name and covered by the canary). A missing ``#include`` is unknown source.
   Equivalence means:
   the same input header (kind, type, name and default of every ``input``/``sinput``, in
   closure order), the same external dependency names, and byte-identical normalized
   hashes of every closure file that is NOT on the reviewed non-trading allowlist
   (``ALLOWLIST``: panel/UI, Studio chart-side control, activation, telemetry, pairing).
   Allowlisted files may differ, but a changed line in one that touches a trading or
   signal API, a ``#define``/``#undef`` or an input fails the certificate anyway
   (``GUARD``), so a signal change cannot slip through as "not trading". A file whose
   source cannot be recovered makes the export build ``not_comparable``.
2. **Empirical canary.** About ten historical sets are re-run over the same window and
   model on the installed build, and every deal (time, type, entry, volume, price) must
   equal the export build's deal list. Only a stored canary result with matching deals,
   bound to the certificate digest, makes the certificate ``active``. A canary that
   shows any drift refutes the certificate for good.

Normalizations before hashing text files (``NORMALIZATIONS``, stamped on every
certificate): byte-order mark and encoding (UTF-8/UTF-16 decoded, re-encoded UTF-8), line
endings (CRLF -> LF), and the build identity strings ``#define GOAT_BUILD_ID`` and
``#define GOAT_BUILD_MARKER`` (they differ between any two builds by construction and only
label the build). Nothing else is normalized: a comment or whitespace change in a
non-allowlisted file still breaks equivalence. Raw file hashes are kept alongside.

Where a build's source comes from (``resolve_build``), strongest first:
- a candidate build's ``identity.json`` whose binary hash matches, with its
  ``compile-receipt.json`` source commit; every file hash in the identity must equal the
  recovered source (working-tree form, ``git cat-file --filters``);
- a git commit that introduced an ``.ex5`` blob with the export's binary hash (the build
  commits bind the EX5 next to its source);
- every commit whose entrypoint defines ``GOAT_BUILD_ID`` as the reported build id, only
  when all of them have the same normalized closure (otherwise ``ambiguous``).
Unknown or ambiguous source is ``not_comparable``. This is research tooling: it reads git
and files, writes only under the controller state ``equivalence`` folder, and never
touches MT5.
"""
from datetime import datetime, timezone
import csv
import difflib
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from studio_subprocess import background_creationflags

SCHEMA = 'goat-trading-equivalence-certificate-v1'
CANARY_SCHEMA = 'goat-trading-equivalence-canary-v1'
DEFAULT_MAIN = 'GOAT V1.49.mq5'
MIN_CANARY_SETS = 10
MAX_CANARY_SETS = 50
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_DEALS_CSV = 256 * 1024 * 1024
TEXT_SUFFIXES = ('.mq5', '.mqh', '.mq4')
STATUSES = ('not_comparable', 'not_equivalent', 'pending_canary', 'active', 'refuted')

# Reviewed non-trading allowlist (Claude-PC 2026-10-03, for Claude-Mac's review on #1885).
# Each entry was read for trade/position/order calls, indicator handles, signal state and
# inputs. Anything not listed here stays in scope, including the entrypoint.
ALLOWLIST = dict(
    id='goat-non-trading-allowlist-v1',
    files={
        # panel / UI
        'Dashboard.mqh': 'panel_ui',
        'GOAT_DashboardOverview.mqh': 'panel_ui',
        'GOATStudioUI.mqh': 'panel_ui',
        'GOATStudioControlFeedback.mqh': 'panel_ui',
        'GOATStudioDraftDisplayPolicy.mqh': 'panel_ui',
        'GOATStudioQueueList.mqh': 'panel_ui',
        'GOATStudioCompletion.mqh': 'panel_ui',
        # Studio chart-side control of the MT5 tester window (never runs inside a tester pass)
        'GOATStudioBridge.mqh': 'studio_control',
        'GOATStudioNative.mqh': 'studio_control',
        'GOATStudioDispatch.mqh': 'studio_control',
        'GOATStudioWorkers.mqh': 'studio_control',
        'GOATStudioRecovery.mqh': 'studio_control',
        'GOATStudioRecoveryFiles.mqh': 'studio_control',
        'GOATTesterStopConfirm.mqh': 'studio_control',
        'GOATBatchCancelOrigin.mqh': 'studio_control',
        # activation / licensing
        'GOATEADeviceActivation.mqh': 'activation',
        'GOATLicenseInitRetry.mqh': 'activation',
        # telemetry
        'GOATDeploymentDiagnostics.mqh': 'telemetry',
        # pairing / demo setup RPC
        'GOATSetupControl.mqh': 'pairing_setup',
        'GOATPortfolioSetupControl.mqh': 'pairing_setup',
        'GOATPortfolioChildAudit.mqh': 'pairing_setup',
        # image resources
        'GOAT Gradient Logo.png': 'resource_image',
        'GOAT Head Transparent.png': 'resource_image',
        'GOAT.ico': 'resource_image',
    },
    kept_in_scope={
        'GOAT V1.49.mq5': 'entrypoint: trading, risk, sizing, order and signal logic',
        'GOAT_Inputs_Definitions.mqh': 'input header and enums',
        'GOATOptimizationInputs.mqh': 'inputs',
        'GOAT_DashboardAILaunchPolicy.mqh': 'rewrites AI bias inputs at launch',
        'GOATAIWireV2.mqh': 'AI bias signal wire',
        'NewsBiasFilter.mqh': 'news/bias trade filter',
        'GOAT_DirectionGuard.mqh': 'direction guard (trade gating)',
        'GOAT_DirectionGuardCore.mqh': 'direction guard (trade gating)',
        'Optimizer.mqh': 'optimizer, export pass and OnTester code',
        'Tester.mqh': 'tester settings and export pass',
        'MTTester.mqh': 'tester automation',
        'XmlProcessor.mqh': 'optimization result parsing (choice of exported sets)',
        'GOATStudioExportDates.mqh': 'export windows',
        'GOATStudioSettingTypes.mqh': 'setting types used by inputs',
        'GOATStudioSettingValues.mqh': 'setting values used by inputs',
        'GOATStudioSettingCompare.mqh': 'setting comparison used by inputs',
        'GOATEvidenceEnd.mqh': 'export end date',
        'GOAT_SequenceExport.mqh': 'capture runs inside the tester pass',
        'GOAT_SequencePackage.mqh': 'capture inputs',
        'GOAT_SequenceHostIO.mqh': 'capture host I/O',
    })
# A changed line in an allowlisted file that matches this is never "non-trading".
GUARD = re.compile(r'OrderSend|OrderSendAsync|OrderModify|OrderDelete|OrderCalcMargin|OrderCalcProfit|Position(Close|Modify|Open)'
                   r'|\bCTrade\b|\.(Buy|Sell|BuyLimit|SellLimit|BuyStop|SellStop|PositionClose|PositionModify|OrderOpen)\s*\('
                   r'|\bi(MA|RSI|ADX|Bands|MACD|ATR|Stochastic|CCI|Momentum|Custom)\s*\(|CopyBuffer|CopyRates|CopyClose|CopyHigh|CopyLow'
                   r'|SymbolInfoTick|#\s*(define|undef)\b|\b(s?input)\b|\bLots?_|\bRisk\b|\bGrid_|\bSL_|\bTP_|\bTSL_')
NORMALIZATIONS = [
    dict(id='encoding', rule='decode UTF-8 (BOM stripped) or UTF-16; hash UTF-8'),
    dict(id='line_endings', rule='CRLF and CR to LF'),
    dict(id='build_id', rule=r'#define GOAT_BUILD_ID "<any>" -> #define GOAT_BUILD_ID "<build>"'),
    dict(id='build_marker', rule=r'#define GOAT_BUILD_MARKER "<any>" -> #define GOAT_BUILD_MARKER "<build>"'),
]
_IDENTITY = re.compile(r'(?m)^([ \t]*#define[ \t]+GOAT_BUILD_(?:ID|MARKER)[ \t]+)"[^"\n]*"[ \t]*$')
_INCLUDE = re.compile(r'(?m)^[ \t]*#[ \t]*include[ \t]*(?:"([^"\n]+)"|<([^>\n]+)>)')
_RESOURCE = re.compile(r'(?m)^[ \t]*#[ \t]*resource[ \t]*"((?:[^"\\\n]|\\.)+)"')
_ICON = re.compile(r'(?m)^[ \t]*#[ \t]*property[ \t]+icon[ \t]*"((?:[^"\\\n]|\\.)+)"')
_IMPORT = re.compile(r'(?m)^[ \t]*#[ \t]*import[ \t]*"([^"\n]+)"')
_ICUSTOM = re.compile(r'iCustom\s*\([^,()]*,[^,()]*,\s*"((?:[^"\\\n]|\\.)+)"')
_INPUT = re.compile(r'(?m)^[ \t]*(sinput|input)[ \t]+([^;=\n]+?)[ \t]+([A-Za-z_]\w*)[ \t]*(?:=[ \t]*((?:"(?:[^"\\\n]|\\.)*"|[^;\n"])+?))?[ \t]*;')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest_of(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ---- sources -------------------------------------------------------------------------------
class DirSource:
    """A build source tree on disk (a worktree or an unpacked build folder)."""

    def __init__(self, root, label=None):
        self.root = Path(root)
        self.label = label or str(self.root)
        self._names = None

    def names(self):
        if self._names is None:
            self._names = {}
            for path in self.root.rglob('*'):
                if path.is_file() and '.git' not in path.relative_to(self.root).parts:
                    rel = path.relative_to(self.root).as_posix()
                    self._names[rel.lower()] = rel
        return self._names

    def read(self, rel):
        path = self.root / rel
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('Source file exceeds its byte bound: ' + rel)
        return path.read_bytes()


def _git(repo, *args, binary=False):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=False,
                            creationflags=background_creationflags())
    if result.returncode:
        raise ValueError('git %s failed: %s' % (' '.join(args[:2]), result.stderr.decode('utf-8', 'replace').strip()[:300]))
    return result.stdout if binary else result.stdout.decode('utf-8', 'replace')


class GitSource:
    """A build source at one commit, in working-tree form (``git cat-file --filters``)."""

    def __init__(self, repo, commit):
        self.repo = Path(repo)
        self.commit = _git(repo, 'rev-parse', '--verify', commit + '^{commit}').strip()
        self.label = 'git:' + self.commit
        self._names = None

    def names(self):
        if self._names is None:
            listing = _git(self.repo, 'ls-tree', '-r', '--name-only', '-z', self.commit)
            self._names = {name.lower(): name for name in listing.split('\0') if name}
        return self._names

    def read(self, rel):
        return _git(self.repo, 'cat-file', '--filters', self.commit + ':' + rel, binary=True)


# ---- closure -------------------------------------------------------------------------------
def decode(raw):
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return raw.decode('utf-16')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def normalize(text):
    """Text used for equivalence hashing (see NORMALIZATIONS)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return _IDENTITY.sub(r'\1"<build>"', text)


def strip_comments(text):
    """Remove // and /* */ comments, keeping string/char literals and line structure."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            block = text[i:n if j < 0 else j + 2]
            out.append('\n' * block.count('\n'))
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _unescape(literal):
    return re.sub(r'\\(.)', r'\1', literal)


def _resolve(source, including, name):
    """A quoted include/resource: the including file's folder first, then the source root."""
    name = name.replace('\\', '/').lstrip('/')
    folder = PurePosixPath(including).parent
    candidates = [str(folder / name)] if str(folder) not in ('', '.') else []
    candidates.append(name)
    for candidate in candidates:
        parts = []
        for part in candidate.split('/'):
            if part == '..':
                if parts:
                    parts.pop()
            elif part not in ('', '.'):
                parts.append(part)
        found = source.names().get('/'.join(parts).lower())
        if found:
            return found
    return None


def closure(source, main=DEFAULT_MAIN):
    """Every file, external dependency and input reachable from ``main`` in ``source``."""
    names = source.names()
    start = names.get(main.lower())
    if not start:
        raise ValueError('Entrypoint %s is not in %s' % (main, source.label))
    files, order, externals, missing, inputs = {}, [], set(), [], []
    stack, seen = [start], set()
    while stack:
        rel = stack.pop()
        if rel.lower() in seen:
            continue
        seen.add(rel.lower())
        raw = source.read(rel)
        entry = dict(raw_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        if not rel.lower().endswith(TEXT_SUFFIXES):
            entry['sha256'] = entry['raw_sha256']
            files[rel] = entry
            order.append(rel)
            continue
        text = normalize(decode(raw))
        entry['sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
        files[rel] = entry
        order.append(rel)
        code = strip_comments(text)
        children = []
        for local, system in _INCLUDE.findall(code):
            if system:
                externals.add('include:<%s>' % system.replace('/', '\\'))
            else:
                found = _resolve(source, rel, local)
                if found:
                    children.append(found)
                else:
                    missing.append(dict(file=rel, include=local))
        for pattern, kind in ((_RESOURCE, 'resource'), (_ICON, 'icon')):
            for literal in pattern.findall(code):
                target = _unescape(literal)
                if target.startswith(('\\', '/')) or target.startswith('::'):
                    externals.add('%s:%s' % (kind, target.replace('/', '\\')))
                    continue
                found = _resolve(source, rel, target)
                if found:
                    children.append(found)
                else:
                    # A binary the compiler took from the build machine (e.g. MTTester's RunMe.ex5), not versioned.
                    externals.add('%s-unversioned:%s' % (kind, target.replace('/', '\\')))
        externals.update('import:' + dll.lower() for dll in _IMPORT.findall(code))
        externals.update('icustom:' + _unescape(name) for name in _ICUSTOM.findall(code))
        for kind, kind_type, name, default in _INPUT.findall(code):
            inputs.append([kind, ' '.join(kind_type.split()), name, ' '.join((default or '').split())])
        # depth-first in include order
        stack.extend(reversed(children))
    return dict(main=start, files=files, order=order, externals=sorted(externals), missing=missing,
                inputs=inputs, input_header_sha256=digest_of(inputs), closure_sha256=digest_of({k: v['sha256'] for k, v in files.items()}))


# ---- build resolution ----------------------------------------------------------------------
def _ex5_for(main):
    return re.sub(r'\.mq5$', '.ex5', main, flags=re.I)


def _main_build_id(source, main):
    rel = source.names().get(main.lower())
    if not rel:
        return None
    match = re.search(r'(?m)^[ \t]*#define[ \t]+GOAT_BUILD_ID[ \t]+"([^"\n]*)"', decode(source.read(rel)))
    return match and match.group(1)


def _identity_candidates(repo):
    base = Path(repo) / 'candidate-builds'
    found = []
    if base.is_dir():
        for path in sorted(base.glob('*/identity.json')):
            try:
                identity = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            receipt = path.parent / 'compile-receipt.json'
            try:
                compile_receipt = json.loads(receipt.read_text(encoding='utf-8-sig')) if receipt.is_file() else {}
            except (OSError, ValueError):
                compile_receipt = {}
            found.append(dict(path=str(path), identity=identity, receipt=compile_receipt))
    return found


def _verify_identity(source, identity):
    """Every file hash the identity lists must equal the recovered source (working-tree bytes)."""
    names, mismatched = source.names(), []
    for rel, expected in sorted((identity.get('sources') or {}).items()):
        actual = names.get(rel.lower())
        if not actual or hashlib.sha256(source.read(actual)).hexdigest() != expected:
            mismatched.append(rel)
    return mismatched


def _commits_introducing_blob(repo, path, sha256):
    commits = [c for c in _git(repo, 'log', '--all', '--format=%H', '--', path).split() if c]
    blobs, introduced = {}, []
    for commit in commits:
        try:
            blobs[commit] = _git(repo, 'rev-parse', commit + ':' + path).strip()
        except ValueError:
            blobs[commit] = None
    hashed = {}
    for commit in commits:
        blob = blobs[commit]
        if not blob:
            continue
        if blob not in hashed:
            hashed[blob] = hashlib.sha256(_git(repo, 'cat-file', 'blob', blob, binary=True)).hexdigest()
        if hashed[blob] != sha256:
            continue
        parents = _git(repo, 'rev-list', '--parents', '-n', '1', commit).split()[1:]
        parent_blobs = []
        for parent in parents:
            try:
                parent_blobs.append(_git(repo, 'rev-parse', parent + ':' + path).strip())
            except ValueError:
                parent_blobs.append(None)
        if blob not in parent_blobs:
            introduced.append(commit)
    return introduced


def _git_batch(repo, args, lines):
    result = subprocess.run(['git', '-C', str(repo), 'cat-file', *args], input=''.join(l + '\n' for l in lines).encode('utf-8'),
                            capture_output=True, check=False, creationflags=background_creationflags())
    if result.returncode:
        raise ValueError('git cat-file failed: ' + result.stderr.decode('utf-8', 'replace')[:300])
    return result.stdout


def _commits_defining(repo, main, build_id):
    """Every commit (all refs, oldest last) whose entrypoint defines GOAT_BUILD_ID as ``build_id``."""
    commits = [c for c in _git(repo, 'rev-list', '--all').split() if c]
    if not commits:
        return []
    checks = _git_batch(repo, ['--batch-check'], ['%s:%s' % (c, main) for c in commits]).decode('utf-8', 'replace').splitlines()
    blob_of = {}
    for commit, line in zip(commits, checks):
        parts = line.split()
        if len(parts) == 3 and parts[1] == 'blob':
            blob_of[commit] = parts[0]
    ids, raw = {}, _git_batch(repo, ['--batch'], sorted(set(blob_of.values())))
    position = 0
    while position < len(raw):
        end = raw.index(b'\n', position)
        sha, _, size = raw[position:end].decode().split()
        body = raw[end + 1:end + 1 + int(size)]
        match = re.search(r'(?m)^[ \t]*#define[ \t]+GOAT_BUILD_ID[ \t]+"([^"\n]*)"', decode(body))
        ids[sha] = match and match.group(1)
        position = end + 1 + int(size) + 1
    return [c for c in commits if ids.get(blob_of.get(c)) == build_id]


def _closure_groups(repo, main, commits):
    """Distinct normalized closures among ``commits`` (blob comparison first, full closure only when needed)."""
    groups = []   # (closure digest, {path: blob})
    for commit in commits:
        listing = _git(repo, 'ls-tree', '-r', '-z', commit)
        blobs = {}
        for entry in listing.split('\0'):
            if '\t' in entry:
                meta, path = entry.split('\t', 1)
                blobs[path] = meta.split()[2]
        if any(all(blobs.get(p) == b for p, b in known.items()) for _, known in groups):
            continue
        tree_closure = closure(GitSource(repo, commit), main)
        if any(digest == tree_closure['closure_sha256'] for digest, _ in groups):
            continue
        groups.append((tree_closure['closure_sha256'], {p: blobs.get(p) for p in tree_closure['files']}))
    return groups


def resolve_build(repo, *, ea_sha256=None, build_id=None, commit=None, main=DEFAULT_MAIN, source_dir=None):
    """Recover the exact source of one EA build, or say why it is unknown."""
    base = dict(ea_sha256=ea_sha256, build_id=build_id, main=main)
    if source_dir:
        source = DirSource(source_dir)
        return base | dict(status='resolved', provenance='source_dir', source=source, label=source.label,
                           build_id=build_id or _main_build_id(source, main))
    if commit:
        source = GitSource(repo, commit)
        return base | dict(status='resolved', provenance='commit', commit=source.commit, source=source, label=source.label,
                           build_id=build_id or _main_build_id(source, main))
    notes = []
    if ea_sha256:
        for item in _identity_candidates(repo):
            identity = item['identity']
            if (identity.get('binary') or {}).get('sha256') != ea_sha256:
                continue
            head = item['receipt'].get('source_head')
            if not head:
                notes.append('%s matches the binary but has no compile source commit' % item['path'])
                continue
            try:
                source = GitSource(repo, head)
            except ValueError as exc:
                notes.append('%s: compile source %s is not in git (%s)' % (item['path'], head, exc))
                continue
            mismatched = _verify_identity(source, identity)
            if mismatched:
                notes.append('%s: compile source %s differs from the identity for %s' % (item['path'], head[:12], ', '.join(mismatched[:5])))
                continue
            return base | dict(status='resolved', provenance='candidate_identity', identity_path=item['path'], commit=source.commit,
                               source=source, label=source.label, build_id=identity.get('build_id') or build_id, notes=notes)
        introduced = _commits_introducing_blob(repo, _ex5_for(main), ea_sha256)
        if introduced:
            sources = [GitSource(repo, c) for c in introduced]
            digests = {closure(s, main)['closure_sha256'] for s in sources}
            if len(digests) == 1:
                source = sources[-1]   # git log lists newest first; the oldest introduction compiled it
                found_id = _main_build_id(source, main)
                if build_id and found_id and found_id != build_id:
                    notes.append('binary commit defines %s, the export reports %s' % (found_id, build_id))
                    return base | dict(status='unknown', reason='The binary commit and the reported build id disagree', notes=notes)
                return base | dict(status='resolved', provenance='git_ex5_blob', commit=source.commit, commits=[s.commit for s in sources],
                                   source=source, label=source.label, build_id=build_id or found_id, notes=notes)
            return base | dict(status='ambiguous', reason='The binary was introduced by commits with different sources',
                               commits=[s.commit for s in sources], notes=notes)
        notes.append('no candidate identity or git EX5 blob has binary ' + ea_sha256[:12])
    if build_id:
        matching = _commits_defining(repo, main, build_id)
        if matching:
            groups = _closure_groups(repo, main, matching)
            if len(groups) == 1:
                source = GitSource(repo, matching[-1])
                return base | dict(status='resolved', provenance='build_id_define', commit=source.commit,
                                   commits=matching, source=source, label=source.label, notes=notes)
            return base | dict(status='ambiguous', reason='%d commits define %s with %d different sources' % (len(matching), build_id, len(groups)),
                               commits=matching, notes=notes)
        notes.append('no commit defines GOAT_BUILD_ID "%s"' % build_id)
    return base | dict(status='unknown', reason='The source of this build cannot be recovered', notes=notes)


# ---- certificate ---------------------------------------------------------------------------
def _changed_lines(old_text, new_text):
    old_lines = strip_comments(old_text).split('\n')
    new_lines = strip_comments(new_text).split('\n')
    changed = []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm='', n=0):
        if line.startswith(('---', '+++', '@@')):
            continue
        if line[:1] in '+-' and line[1:].strip():
            changed.append(line)
    return changed


_INCLUDE_GUARD = re.compile(r'^\s*#\s*(define|ifndef|endif)(\s+[A-Z0-9_]+_MQH_?)?\s*$')


def _guard_hits(lines):
    """Changed lines that touch trading/signal/#define/input code (bare include-guard lines excepted)."""
    hits = []
    for line in lines:
        text = line[1:] if line[:1] in '+-' else line
        if GUARD.search(text) and not _INCLUDE_GUARD.match(text):
            hits.append(line[:200])
    return hits


def _public_build(build, tree):
    keep = ('status', 'provenance', 'ea_sha256', 'build_id', 'commit', 'commits', 'identity_path', 'label', 'reason', 'notes', 'main')
    value = {k: build[k] for k in keep if build.get(k) is not None}
    if tree:
        value.update(closure_sha256=tree['closure_sha256'], input_header_sha256=tree['input_header_sha256'],
                     files={k: dict(sha256=v['sha256'], raw_sha256=v['raw_sha256'], allowlisted=ALLOWLIST['files'].get(PurePosixPath(k).name))
                            for k, v in sorted(tree['files'].items())},
                     externals=tree['externals'], input_count=len(tree['inputs']), missing=tree['missing'])
    return value


def certificate(export_build, installed_build, *, allowlist=None):
    """Compare two resolved builds. Returns the certificate body with its digest."""
    allowlist = allowlist or ALLOWLIST
    allowed = allowlist['files']
    trees, problems = {}, []
    for side, build in (('export', export_build), ('installed', installed_build)):
        if build.get('status') != 'resolved':
            problems.append('%s build source %s: %s' % (side, build.get('status'), build.get('reason')))
            continue
        try:
            trees[side] = closure(build['source'], build.get('main') or DEFAULT_MAIN)
        except (OSError, ValueError) as exc:
            problems.append('%s build closure unreadable: %s' % (side, exc))
            continue
        if trees[side]['missing']:
            problems.append('%s build closure has unresolved files: %s' % (side, trees[side]['missing'][:5]))
    comparison = None
    if not problems:
        old, new = trees['export'], trees['installed']
        old_by, new_by = {k.lower(): k for k in old['files']}, {k.lower(): k for k in new['files']}
        differing, blocking = [], []
        for key in sorted(set(old_by) | set(new_by)):
            a, b = old_by.get(key), new_by.get(key)
            name = PurePosixPath(a or b).name
            category = allowed.get(name)
            if a and b and old['files'][a]['sha256'] == new['files'][b]['sha256']:
                continue
            item = dict(file=a or b, allowlisted=category, change='changed' if a and b else ('removed' if a else 'added'))
            if (a or b).lower().endswith(TEXT_SUFFIXES):
                old_text = normalize(decode(export_build['source'].read(a))) if a else ''
                new_text = normalize(decode(installed_build['source'].read(b))) if b else ''
                lines = _changed_lines(old_text, new_text)
                item.update(changed_lines=len(lines), added=sum(l.startswith('+') for l in lines), removed=sum(l.startswith('-') for l in lines))
                hits = _guard_hits(lines) if category else []
                if hits:
                    item['guard_hits'] = hits[:20]
            if not category:
                item['blocking'] = 'not on the non-trading allowlist'
            elif item.get('guard_hits'):
                item['blocking'] = 'allowlisted, but a changed line touches trading, signal, #define or input code'
            differing.append(item)
            if item.get('blocking'):
                blocking.append(item['file'])
        inputs_equal = old['input_header_sha256'] == new['input_header_sha256']
        externals_equal = old['externals'] == new['externals']
        comparison = dict(differing=differing, blocking=blocking, input_header_equal=inputs_equal, externals_equal=externals_equal,
                          externals_only_export=sorted(set(old['externals']) - set(new['externals'])),
                          externals_only_installed=sorted(set(new['externals']) - set(old['externals'])),
                          identical_files=len(set(old_by) & set(new_by)) - sum(1 for d in differing if d['change'] == 'changed'))
        if not inputs_equal:
            first = next((i for i, (x, y) in enumerate(zip(old['inputs'], new['inputs'])) if x != y), min(len(old['inputs']), len(new['inputs'])))
            comparison['input_header_first_difference'] = dict(index=first, export=old['inputs'][first] if first < len(old['inputs']) else None,
                                                               installed=new['inputs'][first] if first < len(new['inputs']) else None)
    if problems:
        status, source_equivalent = 'not_comparable', None
    else:
        source_equivalent = not comparison['blocking'] and comparison['input_header_equal'] and comparison['externals_equal']
        status = 'pending_canary' if source_equivalent else 'not_equivalent'
    body = dict(schema=SCHEMA, export_build=_public_build(export_build, trees.get('export')),
                installed_build=_public_build(installed_build, trees.get('installed')),
                allowlist=dict(id=allowlist['id'], sha256=digest_of(allowlist), files=allowlist['files'], kept_in_scope=allowlist.get('kept_in_scope')),
                normalizations=NORMALIZATIONS, guard=GUARD.pattern, problems=problems, comparison=comparison,
                source_equivalent=source_equivalent, source_status=status,
                canary_rule=dict(min_sets=MIN_CANARY_SETS, compare='every buy/sell deal: server_time_msc, deal_type, deal_entry, lots, price',
                                 same='window and tester model per set'))
    return body | dict(digest=digest_of(body), created_utc=_now())


def verify_certificate(record):
    body = {k: v for k, v in record.items() if k not in ('digest', 'created_utc')}
    if record.get('schema') != SCHEMA or digest_of(body) != record.get('digest'):
        raise ValueError('Certificate digest does not match its contents')
    return record


# ---- canary --------------------------------------------------------------------------------
def deal_list(path, *, cut_msc=None):
    """Buy/sell deals of a capture deals.csv as comparable tuples, before ``cut_msc`` when given."""
    path = Path(path)
    if path.stat().st_size > MAX_DEALS_CSV:
        raise ValueError('deals.csv exceeds its byte bound')
    rows = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('deal_type') not in ('0', '1'):
                continue
            stamp = int(row['server_time_msc'])
            if cut_msc is not None and stamp >= cut_msc:
                continue
            try:
                rows.append((stamp, row['deal_type'], row['deal_entry'], Decimal(row['lots']), Decimal(row['price'])))
            except InvalidOperation as exc:
                raise ValueError('Invalid number in %s' % path.name) from exc
    return rows


def _show(deal):
    return None if deal is None else dict(server_time_msc=deal[0], deal_type=deal[1], deal_entry=deal[2], lots=str(deal[3]), price=str(deal[4]))


def compare_deals(reference, candidate):
    """Identical deal lists? (time, type, entry, volume, price), first difference otherwise."""
    result = dict(reference_deals=len(reference), candidate_deals=len(candidate), matched=reference == candidate, first_difference=None)
    if not result['matched']:
        index = next((i for i, (a, b) in enumerate(zip(reference, candidate)) if a != b), min(len(reference), len(candidate)))
        result['first_difference'] = dict(index=index, reference=_show(reference[index] if index < len(reference) else None),
                                          candidate=_show(candidate[index] if index < len(candidate) else None))
    return result


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canary_result(cert, pairs, *, min_sets=MIN_CANARY_SETS, source='pairs'):
    """Judge canary pairs for one certificate. Each pair: label, reference/candidate deals paths,
    reference/candidate model and window (``[from, to]``), optional cut_msc."""
    verify_certificate(cert)
    if type(min_sets) is not int or not 1 <= min_sets <= MAX_CANARY_SETS:
        raise ValueError('min_sets must be 1..%d' % MAX_CANARY_SETS)
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_CANARY_SETS:
        raise ValueError('A canary needs 1..%d set pairs' % MAX_CANARY_SETS)
    sets, protocol = [], []
    for index, pair in enumerate(pairs):
        label = str(pair.get('label') or index + 1)
        if pair.get('reference_model') is None or pair.get('reference_model') != pair.get('candidate_model'):
            protocol.append('%s: the two runs used different or unknown tester models (%s / %s)' % (label, pair.get('reference_model'), pair.get('candidate_model')))
        if not pair.get('reference_window') or list(pair.get('reference_window')) != list(pair.get('candidate_window') or []):
            protocol.append('%s: the two runs covered different or unknown windows' % label)
        cut = pair.get('cut_msc')
        if cut is not None and type(cut) is not int:
            protocol.append('%s: cut_msc must be integer milliseconds' % label)
            cut = None
        reference = deal_list(pair['reference_deals'], cut_msc=cut)
        candidate = deal_list(pair['candidate_deals'], cut_msc=cut)
        compared = compare_deals(reference, candidate)
        sets.append(dict(label=label, values_sha256=pair.get('values_sha256'), model=pair.get('reference_model'),
                         window=pair.get('reference_window'), cut_msc=cut,
                         reference_deals_sha256=_file_sha(pair['reference_deals']), candidate_deals_sha256=_file_sha(pair['candidate_deals']),
                         **compared))
    counted = [s for s in sets if s['matched'] and s['reference_deals'] > 0]
    drift = [s['label'] for s in sets if not s['matched']]
    matched = not protocol and not drift and len(counted) >= min_sets
    if protocol:
        plain = 'Canary protocol error: ' + '; '.join(protocol[:5])
    elif drift:
        plain = 'Deal drift in %d of %d sets (%s): the builds do not trade the same.' % (len(drift), len(sets), ', '.join(drift[:5]))
    elif len(counted) < min_sets:
        plain = 'Deals matched, but only %d sets with trades (%d needed).' % (len(counted), min_sets)
    else:
        plain = 'Identical deal lists in all %d sets (%d deals).' % (len(sets), sum(s['reference_deals'] for s in sets))
    body = dict(schema=CANARY_SCHEMA, certificate_digest=cert['digest'], export_ea_sha256=cert['export_build'].get('ea_sha256'),
                installed_ea_sha256=cert['installed_build'].get('ea_sha256'), source=source, min_sets=min_sets,
                sets=sets, sets_with_trades=len(counted), drift=drift, protocol_errors=protocol, matched=matched,
                refutes=bool(drift) and not protocol, plain=plain)
    return body | dict(digest=digest_of(body), created_utc=_now())


def verify_canary(record):
    body = {k: v for k, v in record.items() if k not in ('digest', 'created_utc')}
    if record.get('schema') != CANARY_SCHEMA or digest_of(body) != record.get('digest'):
        raise ValueError('Canary digest does not match its contents')
    return record


# ---- store ---------------------------------------------------------------------------------
def store_root(controller_root):
    return Path(controller_root) / 'equivalence'


def _write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + '\n'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')).get('digest') != value.get('digest'):
            raise ValueError('A different record already exists at ' + str(path))
        return path
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    return path


def save_certificate(controller_root, cert):
    verify_certificate(cert)
    return _write_once(store_root(controller_root) / cert['digest'] / 'certificate.json', cert)


def save_canary(controller_root, canary):
    verify_canary(canary)
    load_certificate(controller_root, canary['certificate_digest'])
    return _write_once(store_root(controller_root) / canary['certificate_digest'] / ('canary-' + canary['digest'] + '.json'), canary)


def _digest_arg(digest):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Certificate digest must be 64 lowercase hex characters')
    return digest


def load_certificate(controller_root, digest):
    path = store_root(controller_root) / _digest_arg(digest) / 'certificate.json'
    if not path.is_file():
        raise ValueError('No stored certificate ' + digest)
    record = verify_certificate(json.loads(path.read_text(encoding='utf-8')))
    if record['digest'] != digest:
        raise ValueError('Stored certificate is filed under another digest')
    return record


def state(controller_root, digest):
    """The certificate with its canaries and its effective status (see STATUSES)."""
    cert = load_certificate(controller_root, digest)
    canaries, invalid = [], []
    for path in sorted((store_root(controller_root) / digest).glob('canary-*.json')):
        try:
            canary = verify_canary(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError) as exc:
            invalid.append(dict(path=str(path), reason=str(exc)))
            continue
        bound = (canary['certificate_digest'] == digest and canary['export_ea_sha256'] == cert['export_build'].get('ea_sha256')
                 and canary['installed_ea_sha256'] == cert['installed_build'].get('ea_sha256'))
        canaries.append(dict(path=str(path), digest=canary['digest'], matched=canary['matched'] and bound, refutes=canary['refutes'] and bound,
                             sets=len(canary['sets']), sets_with_trades=canary['sets_with_trades'], plain=canary['plain']))
    status = cert['source_status']
    active = None
    if status == 'pending_canary':
        if any(c['refutes'] for c in canaries):
            status = 'refuted'
        else:
            active = next((c for c in canaries if c['matched']), None)
            status = 'active' if active else 'pending_canary'
    return dict(digest=digest, status=status, active=status == 'active', canary_digest=active and active['digest'],
                export_build=dict((k, cert['export_build'].get(k)) for k in ('ea_sha256', 'build_id', 'commit', 'provenance')),
                installed_build=dict((k, cert['installed_build'].get(k)) for k in ('ea_sha256', 'build_id', 'commit', 'provenance')),
                source_equivalent=cert['source_equivalent'], canaries=canaries, invalid_canaries=invalid,
                blocking=(cert.get('comparison') or {}).get('blocking'), problems=cert.get('problems'),
                certificate_path=str(store_root(controller_root) / digest / 'certificate.json'))


def covers(cert_state, *, export_ea_sha256=None, export_build_id=None, installed_ea_sha256=None):
    """Does this certificate cover an export of this build re-tested on this installed build?"""
    export, installed = cert_state['export_build'], cert_state['installed_build']
    if not installed_ea_sha256 or installed.get('ea_sha256') != installed_ea_sha256:
        return False
    if export_ea_sha256:
        return export.get('ea_sha256') == export_ea_sha256
    return bool(export_build_id) and export.get('build_id') == export_build_id


# ---- canary from a catch-up run, canary planning -------------------------------------------
def _msc(moment):
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def catchup_pairs(controller_root, catchup_id, digest):
    """Canary pairs from a finished canary catch-up: the original export's capture deals (export
    build) against the re-test's capture deals (installed build), up to the original's last minute."""
    from studio_catchup_verdict import equity_rows
    from studio_evidence import read_export
    from studio_seed_results import read_seed_json
    if not isinstance(catchup_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', catchup_id):
        raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
    root = Path(controller_root) / 'catchups' / catchup_id
    manifest = read_seed_json(root / 'manifest.json')
    run_state = read_seed_json(root / 'state.json')
    pairs, skipped = [], []
    for spec, item in zip(manifest['members'], run_state['members']):
        bridge = (spec.get('pins') or {}).get('equivalence') or {}
        if bridge.get('mode') != 'canary' or bridge.get('certificate_digest') != digest:
            skipped.append(dict(alias=spec['alias'], reason='not a canary member of this certificate'))
            continue
        if item.get('status') != 'completed' or not item.get('result'):
            skipped.append(dict(alias=spec['alias'], reason='not completed (%s)' % item.get('status')))
            continue
        result = read_seed_json(item['result']['path'])
        version = json.loads(Path(result['version_path']).read_text(encoding='utf-8'))
        original = read_export(spec['original']['set_path'])
        if original['set_sha256'] != spec['original']['set_sha256']:
            raise ValueError('Original export changed since the canary was prepared: ' + spec['original']['set_path'])
        reference_capture, candidate_capture = original.get('capture') or {}, (version.get('retest') or {}).get('capture') or {}
        if not reference_capture.get('complete') or not candidate_capture.get('path'):
            skipped.append(dict(alias=spec['alias'], reason='a capture is missing or incomplete'))
            continue
        cut = equity_rows(original['csv_path'])[-1][0]
        retest = read_export(version['retest']['set_path'])
        window_ref = [original['evidence_start'], cut.strftime('%Y-%m-%d %H:%M')]
        window_new = [retest['evidence_start'], cut.strftime('%Y-%m-%d %H:%M')]
        pairs.append(dict(label=spec['alias'] + ' ' + spec['tester']['Symbol'], values_sha256=spec['original']['values_sha256'],
                          reference_deals=str(Path(reference_capture['path']).parent / 'deals.csv'),
                          candidate_deals=str(Path(candidate_capture['path']).parent / 'deals.csv'),
                          reference_model=reference_capture.get('model'), candidate_model=(retest.get('capture') or {}).get('model', spec['tester']['Model']),
                          reference_window=window_ref, candidate_window=window_new, cut_msc=_msc(cut)))
    return pairs, skipped


def canary_plan(controller_root, digest, sources, *, max_sets=MIN_CANARY_SETS, evidence_end='auto', job_timeout_seconds=7200):
    """A catch-up plan that canaries one source-equivalent certificate on ~10 diverse exports of its export build."""
    from studio_evidence import scan
    cert_state = state(controller_root, digest)
    if cert_state['status'] not in ('pending_canary', 'active'):
        raise ValueError('Certificate %s is %s; only a source-equivalent certificate is canaried' % (digest[:12], cert_state['status']))
    if type(max_sets) is not int or not 1 <= max_sets <= MAX_CANARY_SETS:
        raise ValueError('max_sets must be 1..%d' % MAX_CANARY_SETS)
    exports, unreadable = scan([str(s) for s in sources])
    export_build = cert_state['export_build']
    eligible = []
    for export in exports:
        capture = export.get('capture') or {}
        run_ea = (export.get('run') or {}).get('ea_sha256')
        same = (run_ea == export_build.get('ea_sha256')) if run_ea else (capture.get('build_id') == export_build.get('build_id'))
        deals = capture.get('path') and Path(capture['path']).parent / 'deals.csv'
        if same and capture.get('complete') and capture.get('model') == 4 and deals and deals.is_file() and not export.get('problems'):
            eligible.append(export)
    # Diverse: round-robin over symbols, threshold passers first, then by file name for a stable choice.
    by_symbol = {}
    for export in sorted(eligible, key=lambda e: (not e['threshold']['passing'], e['set_path'])):
        by_symbol.setdefault(export['symbol'], []).append(export)
    chosen = []
    while len(chosen) < max_sets and any(by_symbol.values()):
        for symbol in sorted(by_symbol):
            if by_symbol[symbol] and len(chosen) < max_sets:
                chosen.append(by_symbol[symbol].pop(0))
    plan = dict(schema_version=1, evidence_end=evidence_end, sets=[e['set_path'] for e in chosen], job_timeout_seconds=job_timeout_seconds,
                canary_certificate=digest, include_below_threshold=True)
    return dict(plan=plan, eligible=len(eligible), chosen=[dict(symbol=e['symbol'], set_path=e['set_path'], passing=e['threshold']['passing'])
                                                              for e in chosen],
                unreadable=len(unreadable), enough=len(chosen) >= MIN_CANARY_SETS,
                next_action='catchup-prepare with this plan, catchup-start on the installed build, then equivalence-canary-ingest --catchup-id')


# ---- CLI -----------------------------------------------------------------------------------
OPERATIONS = ('equivalence-certificate', 'equivalence-status', 'equivalence-canary-plan', 'equivalence-canary-ingest')


def operation(controller, args):
    """CLI routes. No MT5 or terminal effect; writes only under <controller state>\\equivalence."""
    root = controller.root
    if args.operation == 'equivalence-certificate':
        main = args.main or DEFAULT_MAIN
        export = resolve_build(args.repo, ea_sha256=args.export_ea_sha256, build_id=args.export_build_id, commit=args.export_commit, main=main)
        installed_sha = args.installed_ea_sha256 or controller.install['ea_sha256']
        installed = resolve_build(args.repo, ea_sha256=None if args.installed_commit else installed_sha, commit=args.installed_commit, main=main)
        installed['ea_sha256'] = installed_sha
        cert = certificate(export, installed)
        path = save_certificate(root, cert)
        comparison = cert.get('comparison') or {}
        return dict(state(root, cert['digest']), certificate_path=str(path), problems=cert['problems'],
                    differing=[{k: d.get(k) for k in ('file', 'change', 'allowlisted', 'changed_lines', 'blocking')} for d in comparison.get('differing', [])],
                    input_header_equal=comparison.get('input_header_equal'), externals_equal=comparison.get('externals_equal'))
    if args.operation == 'equivalence-status':
        return state(root, args.certificate)
    if args.operation == 'equivalence-canary-plan':
        result = canary_plan(root, args.certificate, args.source, max_sets=args.max_sets, evidence_end=args.evidence_end)
        if args.output:
            with Path(args.output).open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result['plan'], stream, indent=1)
            result['plan_path'] = str(args.output)
        return result
    if args.operation == 'equivalence-canary-ingest':
        cert = load_certificate(root, args.certificate)
        if bool(args.catchup_id) == bool(args.pairs):
            raise ValueError('Give exactly one of --catchup-id or --pairs')
        if args.catchup_id:
            pairs, skipped = catchup_pairs(root, args.catchup_id, args.certificate)
            source = 'catchup:' + args.catchup_id
        else:
            pairs, skipped, source = json.loads(Path(args.pairs).read_text(encoding='utf-8-sig')), [], 'pairs:' + str(args.pairs)
        canary = canary_result(cert, pairs, min_sets=args.min_sets, source=source)
        path = save_canary(root, canary)
        return dict(canary_path=str(path), canary_digest=canary['digest'], matched=canary['matched'], refutes=canary['refutes'],
                    plain=canary['plain'], skipped=skipped, state=state(root, args.certificate))
    raise ValueError('Not an equivalence operation: ' + args.operation)
