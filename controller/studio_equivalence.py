"""Trading-equivalence certificate and empirical canary for OOS catch-up (goat-trading-equivalence-v1).

A catch-up re-test is comparable only on the EA build that made the export. This module
lets a newer installed build stand in for the export's build when, and only when, both
of these hold (Claude-Mac, algogoat/goatai#1885, comments 5974337974 and 5974343541):

1. **Source equivalence, by exclusion.** The certificate covers the EA's FULL source
   dependency closure: every ``#include "..."``, ``#resource``, ``#property icon`` and
   input declaration reachable from the entrypoint (``GOAT V1.49.mq5``), plus the names of
   every external dependency (standard-library ``#include <...>``, MQL5-root resources such
   as the MACD indicator, unversioned binary resources such as MTTester's ``RunMe.ex5``,
   ``#import`` DLLs and ``iCustom`` literals). Git cannot hold these, so each build must
   carry their hashes (``externals_sha256``; ``hash_externals`` reads an MQL5 folder) and a
   known compiler (``compiler_sha256``); only system-DLL imports are compared by name.
   Anything missing fails closed (``not_comparable``), as does a missing ``#include``.
   Equivalence means: the same input header (kind, type, name and default of every
   ``input``/``sinput``, in closure order), the same external names and hashes, the same
   compiler, and byte-identical normalized hashes of every closure file that is NOT on the
   reviewed non-trading allowlist. The allowlist is a receipt
   (``contracts/equivalence/non-trading-allowlist-v1.json``) pinned by full repo path and
   by the normalized hash of each reviewed version: an unreviewed version of an
   allowlisted file is in scope (Claude-Mac #141 HIGH 3). The changed-line ``GUARD``
   (trading or signal API, ``#define``/``#undef``, inputs) is defence in depth.
2. **Empirical canary.** At least ten distinct historical sets are re-run over the same
   window and model on the installed build, each deal file bound to the binary that made
   it, and every deal (time, type, entry, volume, price) must equal the export build's
   deal list. Only a stored canary with matching deals in 10+ distinct sets, no protocol
   error and no unfinished member, bound to the certificate digest, makes the certificate
   ``active``, for the models it ran; activation is re-derived from the stored sets. Drift
   in any protocol-clean set refutes the certificate for good.

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

# Reviewed non-trading allowlist: a receipt pinned by full repo path AND by the normalized content
# hash of every reviewed version (Claude-Mac #141 review, HIGH 3). A version that is not in the
# receipt is in scope until a new review adds it; the text GUARD is defence in depth only.
ALLOWLIST_PATH = Path(__file__).resolve().parent / 'contracts' / 'equivalence' / 'non-trading-allowlist-v1.json'


def load_allowlist(path=None):
    record = json.loads(Path(path or ALLOWLIST_PATH).read_text(encoding='utf-8'))
    if record.get('schema') != 'goat-non-trading-allowlist-receipt-v1' or not isinstance(record.get('files'), dict):
        raise ValueError('Not a non-trading allowlist receipt')
    for rel, entry in record['files'].items():
        if not isinstance(entry, dict) or not entry.get('category') or not isinstance(entry.get('reviewed_sha256'), dict):
            raise ValueError('Allowlist entry %s needs a category and reviewed_sha256 versions' % rel)
    return record


ALLOWLIST = load_allowlist()


def allowed(allowlist, rel):
    """The receipt entry for this exact repo-relative path (case-insensitive), or None."""
    key = rel.replace('\\', '/').lower()
    return next((dict(entry, path=path) for path, entry in allowlist['files'].items() if path.lower() == key), None)


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
    if not isinstance(identity.get('sources'), dict) or not identity['sources']:
        return ['<the identity lists no source hashes>']
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
            build = base | dict(status='resolved', provenance='candidate_identity', identity_path=item['path'], commit=source.commit,
                                source=source, label=source.label, build_id=identity.get('build_id') or build_id, notes=notes,
                                compiler_sha256=item['receipt'].get('compiler_sha256'),
                                externals_sha256=identity.get('externals_sha256') if isinstance(identity.get('externals_sha256'), dict) else None)
            # The build's externals manifest (candidate-builds/<build>/externals.json), bound to this binary,
            # compile commit and compiler; one that does not verify is ignored (the certificate then fails closed).
            # It counts only when the compile receipt binds it (externals_manifest_digest; Claude-Mac, #157 answer 7).
            manifest = Path(item['path']).parent / EXTERNALS_FILE
            if manifest.is_file():
                try:
                    record = load_externals_manifest(manifest, binary_sha256=ea_sha256, source_head=head,
                                                     compiler_sha256=item['receipt'].get('compiler_sha256'))
                    bound = item['receipt'].get('externals_manifest_digest')
                    if bound != record['digest']:
                        raise ValueError('%s is not bound by its compile receipt (externals_manifest_digest %s)' % (manifest, bound))
                    apply_externals_manifest(build, record, manifest)
                except (OSError, ValueError) as exc:
                    notes.append(str(exc))
            return build
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
        # A known binary that matches nothing stays unknown: a build-id label is no proof of that binary's source.
        notes.append('no candidate identity or git EX5 blob has binary ' + ea_sha256[:12])
        return base | dict(status='unknown', reason='No recoverable source for binary %s' % ea_sha256[:12], notes=notes)
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


def _public_build(build, tree, allowlist):
    keep = ('status', 'provenance', 'ea_sha256', 'build_id', 'commit', 'commits', 'identity_path', 'label', 'reason', 'notes', 'main',
            'compiler_sha256', 'externals_sha256', 'externals_manifest')
    value = {k: build[k] for k in keep if build.get(k) is not None}
    if tree:
        value.update(closure_sha256=tree['closure_sha256'], input_header_sha256=tree['input_header_sha256'],
                     files={k: dict(sha256=v['sha256'], raw_sha256=v['raw_sha256'], allowlisted=(allowed(allowlist, k) or {}).get('category'))
                            for k, v in sorted(tree['files'].items())},
                     externals=tree['externals'], input_count=len(tree['inputs']), missing=tree['missing'])
    return value


def hashed_externals(externals):
    """Externals that must be hashed per build: everything but #import of system DLLs (compared by name)."""
    return [name for name in externals if not name.startswith('import:')]


def _include_closure(root, rel, seen):
    """Hash a standard-library include, every file it includes and every #resource it embeds
    (e.g. ControlsPlus\\res\\*.bmp), recursively."""
    path = root / rel
    if rel.lower() in seen or not path.is_file():
        return
    seen[rel.lower()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not rel.lower().endswith(TEXT_SUFFIXES):
        return
    code = strip_comments(decode(path.read_bytes()))
    for local, system in _INCLUDE.findall(code):
        child = ('Include/' + system) if system else str(PurePosixPath(rel).parent / local)
        _include_closure(root, child.replace('\\', '/'), seen)
    for literal in _RESOURCE.findall(code):
        target = _unescape(literal).replace('\\', '/')
        child = target.lstrip('/') if target.startswith('/') else str(PurePosixPath(rel).parent / target)
        _include_closure(root, child, seen)


def hash_externals(mql5_root, externals, *, expert_dir='Experts/GOAT-EA'):
    """Hashes of a build's external dependencies, read from the MQL5 folder it was compiled in.

    ``include:<X>`` hashes the standard-library file and every file it includes; MQL5-root
    resources and ``icustom:`` indicators hash the .ex5 under MQL5; unversioned resources are
    looked up next to the EA (``expert_dir``). A missing file is left out, so the certificate
    fails closed on it.
    """
    root, result = Path(mql5_root), {}
    for name in hashed_externals(externals):
        kind, _, target = name.partition(':')
        target = target.replace('\\', '/')
        if kind == 'include':
            seen = {}
            _include_closure(root, 'Include/' + target.strip('<>'), seen)
            if seen:
                result[name] = digest_of(dict(sorted(seen.items())))
            continue
        if kind in ('resource', 'icon'):
            path = root / target.lstrip('/')
        elif kind in ('resource-unversioned', 'icon-unversioned'):
            path = root / expert_dir / target
        elif kind == 'icustom':
            path = root / 'Indicators' / (target if target.lower().endswith('.ex5') else target + '.ex5')
        else:
            continue
        if path.is_file():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


# ---- build externals manifest (fingerprints a candidate compile) ---------------------------
EXTERNALS_SCHEMA = 'goat-build-externals-v1'
EXTERNALS_FILE = 'externals.json'
# An unversioned resource the compiler never embedded (e.g. MTTester's RunMe.ex5 under an undefined
# #ifdef RUNEX5_SILENT). Accepted only from a manifest whose compile log proves it was not read.
NOT_CONSUMED = 'not-consumed (compile log)'
_LOG_INCLUDE = re.compile(r'^(?P<src>.+?) : information: including (?P<path>.+)$')
_LOG_RESOURCE = re.compile(r"^(?P<path>.+?) : information: resource '(?P<name>[^']*)' as (?P<target>.+)$")


def _file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_compile_log(path):
    """(included files, embedded resources, compiling line, result line) from a MetaEditor log."""
    raw = Path(path).read_bytes()
    if not raw.startswith((b'\xff\xfe', b'\xfe\xff')) and raw[1:2] == b'\x00':
        raw = b'\xff\xfe' + raw
    text = re.sub(r'information: including[ \t]*\r?\n', 'information: including ', decode(raw))
    includes, resources, compiling, result = [], [], None, None
    for line in text.splitlines():
        line = line.strip()
        m = _LOG_INCLUDE.match(line)
        if m:
            includes.append(m.group('path').strip())
            continue
        m = _LOG_RESOURCE.match(line)
        if m:
            resources.append(m.group('path').strip())
            continue
        if ': information: compiling ' in line:
            compiling = line.split(': information: compiling ', 1)[1].strip()
        if line.startswith('Result:'):
            result = line
    return includes, resources, compiling, result


def _under(path, root):
    """``path`` relative to ``root`` (forward slashes), case-insensitively, or None."""
    p, r = path.replace('/', '\\').rstrip('\\'), str(root).replace('/', '\\').rstrip('\\')
    if p.lower().startswith(r.lower() + '\\'):
        return p[len(r) + 1:].replace('\\', '/')
    return None


def externals_manifest(mql5_root, compile_log, stage, *, binary, identity, receipt, compiler=None, main=DEFAULT_MAIN,
                       log_stage=None, log_mql5_root=None, repo=None):
    """The externals a candidate compile actually used, from its MetaEditor log and its MQL5 tree.

    ``consumed`` hashes every include and resource the compiler read outside the staged EA
    source (standard library and ControlsPlus includes with nested includes, their bitmap
    resources, the MACD indicator ...). ``externals_sha256`` holds the same per-name hashes the
    certificate uses (``hash_externals`` over the staged source closure), so the certificate can
    consume the manifest directly. Every check that fails is listed in ``problems``; a manifest
    with problems is never used by a certificate."""
    problems, notes = [], []
    identity_record = json.loads(Path(identity).read_text(encoding='utf-8-sig'))
    receipt_record = json.loads(Path(receipt).read_text(encoding='utf-8-sig'))
    includes, resources, compiling, result = read_compile_log(compile_log)
    log_root, log_stage = log_mql5_root or str(mql5_root), log_stage or str(stage)
    consumed, stage_files, outside = {}, {}, []
    for kind, paths in (('include', includes), ('resource', resources)):
        for path in paths:
            rel = _under(path, log_stage)
            if rel is not None:
                staged = Path(stage) / rel
                stage_files[rel] = _file_sha256(staged) if staged.is_file() else None
                continue
            rel = _under(path, log_root)
            if rel is None:
                outside.append(path)
                continue
            local = Path(mql5_root) / rel
            consumed[rel] = _file_sha256(local) if local.is_file() else None
            if consumed[rel] is None:
                problems.append('the compile read %s, which is no longer in the MQL5 tree' % rel)
    if outside:
        problems.append('the compile log names files outside the MQL5 root and the stage: %s' % outside[:5])
    if not compiling or _under(compiling, log_stage) != main:
        problems.append('the compile log does not compile %s from the stage (%s)' % (main, compiling))
    if not result or not re.match(r'Result: 0 errors?,', result):
        problems.append('the compile log has no clean result line (%s)' % result)
    sources = identity_record.get('sources') or {}
    if not sources:
        problems.append('the identity lists no source hashes')
    for rel, expected in sorted(sources.items()):
        staged = Path(stage) / rel
        if not staged.is_file() or _file_sha256(staged) != expected:
            problems.append('staged %s differs from the identity' % rel)
    for rel, sha in sorted(stage_files.items()):
        if sha is None:
            problems.append('the compile read staged %s, which is not in the stage folder' % rel)
        elif rel in sources and sources[rel] != sha:
            problems.append('staged %s read by the compile differs from the identity' % rel)
    unlisted = sorted(rel for rel in stage_files if rel not in sources)
    staged_resources = {}
    if unlisted and repo:
        # Staged files the identity does not list (the PNG resources): checked against the compile commit itself.
        source = GitSource(repo, receipt_record.get('source_head') or 'HEAD')
        for rel in unlisted:
            found = source.names().get(rel.lower())
            git_sha = hashlib.sha256(source.read(found)).hexdigest() if found else None
            if git_sha != stage_files[rel]:
                problems.append('staged %s differs from the compile commit' % rel)
            staged_resources[rel] = stage_files[rel]
    elif unlisted:
        problems.append('the compile read staged files the identity does not list (give the repo to check them): %s' % unlisted[:5])
    binary_sha = _file_sha256(binary)
    if binary_sha != (identity_record.get('binary') or {}).get('sha256') or binary_sha != (receipt_record.get('output') or {}).get('sha256'):
        problems.append('binary %s is not the identity/receipt binary' % binary_sha[:12])
    compiler_sha = _file_sha256(compiler) if compiler else None
    if not receipt_record.get('compiler_sha256'):
        problems.append('the compile receipt has no compiler_sha256')
    elif compiler_sha and compiler_sha != receipt_record['compiler_sha256']:
        problems.append('compiler %s is not the receipt compiler' % compiler_sha[:12])
    if not compiler_sha:
        notes.append('compiler binary not re-hashed; compiler_sha256 is the receipt value')
    tree = closure(DirSource(stage), main)
    by_name = hash_externals(mql5_root, tree['externals'])
    consumed_names = {PurePosixPath(rel).name.lower() for rel in list(consumed) + list(stage_files)}
    for name in hashed_externals(tree['externals']):
        if name in by_name:
            continue
        kind, _, target = name.partition(':')
        if kind.endswith('-unversioned') and PurePosixPath(target.replace('\\', '/')).name.lower() not in consumed_names:
            by_name[name] = NOT_CONSUMED
            notes.append('%s: inside a conditional the compiler did not take; the log shows it was never read' % name)
        else:
            problems.append('no hash for external %s' % name)
    # Every file the compiler read must be covered by a per-name hash (or be staged source).
    covered = set()
    for name in hashed_externals(tree['externals']):
        kind, _, target = name.partition(':')
        if kind == 'include':
            seen = {}
            _include_closure(Path(mql5_root), 'Include/' + target.strip('<>').replace('\\', '/'), seen)
            covered.update(seen)
        elif kind == 'resource':
            covered.add(target.replace('\\', '/').lstrip('/').lower())
    uncovered = sorted(rel for rel in consumed if rel.lower() not in covered)
    if uncovered:
        problems.append('files the compiler read that no per-name external hash covers: %s' % uncovered[:8])
    started = receipt_record.get('compile_started_at')
    if started:
        stamp = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?$', started)
        if not stamp:
            raise ValueError('Unreadable compile_started_at: ' + started)
        zone = stamp.group(3) if stamp.group(3) not in (None, 'Z') else '+00:00'
        moment = datetime.fromisoformat(stamp.group(1) + (stamp.group(2) or '')[:7] + zone)
        later = sorted(rel for rel in consumed if (Path(mql5_root) / rel).is_file()
                       and datetime.fromtimestamp((Path(mql5_root) / rel).stat().st_mtime, timezone.utc) > moment)
        if later:
            problems.append('external files modified after the compile started: %s' % later[:5])
    else:
        notes.append('the receipt has no compile_started_at; file times not checked')
    body = dict(schema=EXTERNALS_SCHEMA, build_id=identity_record.get('build_id'), binary_sha256=binary_sha,
                source_head=receipt_record.get('source_head'), compiler_sha256=receipt_record.get('compiler_sha256'),
                compiler_file_sha256=compiler_sha, compiler_version=receipt_record.get('compiler_version'),
                compile_log_sha256=_file_sha256(compile_log), compile_result=result, main=main,
                externals_sha256=dict(sorted(by_name.items())), consumed=dict(sorted(consumed.items())),
                consumed_sha256=digest_of(dict(sorted(consumed.items()))), stage_files_verified=len(stage_files),
                staged_resources_checked_against_git=staged_resources,
                problems=problems, notes=notes)
    return body | dict(digest=digest_of(body), created_utc=_now())


def load_externals_manifest(path, *, binary_sha256=None, source_head=None, compiler_sha256=None):
    """A stored manifest, verified against its digest and the build it claims (fail closed)."""
    record = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    body = {k: v for k, v in record.items() if k not in ('digest', 'created_utc')}
    if record.get('schema') != EXTERNALS_SCHEMA or digest_of(body) != record.get('digest'):
        raise ValueError('Externals manifest digest does not match its contents: ' + str(path))
    if record.get('problems'):
        raise ValueError('Externals manifest %s records problems: %s' % (path, record['problems'][:3]))
    for field, expected in (('binary_sha256', binary_sha256), ('source_head', source_head), ('compiler_sha256', compiler_sha256)):
        if expected is not None and record.get(field) != expected:
            raise ValueError('Externals manifest %s is for another build (%s)' % (path, field))
    if not isinstance(record.get('externals_sha256'), dict) or not isinstance(record.get('consumed'), dict):
        raise ValueError('Externals manifest %s has no externals' % path)
    return record


_CONDITIONAL = re.compile(r'^[ \t]*#[ \t]*(ifdef|ifndef|if|elif|else|endif)\b[ \t]*(\w*)')


def _not_consumed_problems(source, tree, names):
    """A resource recorded as not consumed must, in this build's source, sit only inside ``#ifdef M``
    blocks whose macro M is never #defined anywhere in the closure (MTTester.mqh's RunMe.ex5 under
    RUNEX5_SILENT). Defining the macro, or moving the resource out of the block, fails closed."""
    texts = {rel: strip_comments(normalize(decode(source.read(rel)))) for rel in tree['order'] if rel.lower().endswith(TEXT_SUFFIXES)}
    defined = set(re.findall(r'(?m)^[ \t]*#[ \t]*define[ \t]+(\w+)', '\n'.join(texts.values())))
    problems = []
    for name in names:
        target = name.partition(':')[2]
        sites = 0
        for rel, code in texts.items():
            stack = []
            for number, line in enumerate(code.split('\n'), 1):
                m = _CONDITIONAL.match(line)
                if m:
                    word = m.group(1)
                    if word in ('ifdef', 'ifndef', 'if'):
                        stack.append((word, m.group(2)))
                    elif word in ('elif', 'else') and stack:
                        stack[-1] = ('else', '')
                    elif word == 'endif' and stack:
                        stack.pop()
                    continue
                r = _RESOURCE.match(line)
                if not r or _unescape(r.group(1)).replace('/', '\\') != target:
                    continue
                sites += 1
                guarded = bool(stack) and all(w == 'ifdef' for w, _ in stack) and not any(g in defined for _, g in stack)
                if not guarded:
                    problems.append('%s is recorded as not consumed, but %s:%d can compile it (not only inside an #ifdef whose '
                                    'macro the closure never defines)' % (name, rel, number))
        if not sites:
            problems.append('%s is recorded as not consumed, but no closure file names it' % name)
    return problems


def bind_externals_manifest(receipt, record):
    """Record a manifest's digest in its compile receipt (adds one field; never rewrites another)."""
    path = Path(receipt)
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('externals_manifest_digest') not in (None, record['digest']):
        raise ValueError('The compile receipt already binds another externals manifest')
    if record.get('problems'):
        raise ValueError('A manifest with problems is never bound')
    value['externals_manifest_digest'] = record['digest']
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return value


def use_explicit_manifest(build, path):
    """``--*-externals <manifest>``: bound to the build's binary, compile commit AND compiler (Codex P2 on #157)."""
    record = load_externals_manifest(path, binary_sha256=build.get('ea_sha256'), source_head=build.get('commit'),
                                     compiler_sha256=build.get('compiler_sha256'))
    return apply_externals_manifest(build, record, path)


def apply_externals_manifest(build, record, path):
    build['externals_sha256'] = dict(record['externals_sha256'])
    build['externals_consumed'] = dict(record['consumed'])
    build['externals_manifest'] = dict(path=str(path), digest=record['digest'], consumed_sha256=record['consumed_sha256'])
    if not build.get('compiler_sha256'):
        build['compiler_sha256'] = record['compiler_sha256']
    return build


def certificate(export_build, installed_build, *, allowlist=None, function_allowlist=None):
    """Compare two resolved builds. Returns the certificate body with its digest."""
    allowlist = allowlist or ALLOWLIST
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
        # Fail closed on what git cannot hold: every non-DLL external needs this build's hash, and the compiler identity.
        hashes = build.get('externals_sha256') or {}
        unhashed = [n for n in hashed_externals(trees[side]['externals']) if not hashes.get(n)]
        if unhashed:
            problems.append('%s build: no hash for external dependencies %s (resources, indicators and standard-library '
                            'includes are part of the trading closure)' % (side, unhashed[:6]))
        sentinels = sorted(n for n, v in hashes.items() if v == NOT_CONSUMED)
        if sentinels and not build.get('externals_manifest'):
            problems.append('%s build: %s marked not consumed without a compile-log externals manifest' % (side, sentinels[:3]))
        elif sentinels:
            problems.extend('%s build: %s' % (side, p) for p in _not_consumed_problems(build['source'], trees[side], sentinels))
        if not build.get('compiler_sha256'):
            problems.append('%s build: compiler identity unknown (compile receipt compiler_sha256)' % side)
    import studio_function_units as units
    function_allowlist = function_allowlist if function_allowlist is not None else units.load_function_allowlist()
    function_level = []
    comparison = None
    if not problems:
        old, new = trees['export'], trees['installed']
        old_by, new_by = {k.lower(): k for k in old['files']}, {k.lower(): k for k in new['files']}
        differing, blocking = [], []
        unit_files = {f.lower() for f in units.function_level_files(old['main'])} & {f.lower() for f in units.function_level_files(new['main'])}
        graphs = {}

        def graph(side, build, tree):
            # The call graph is built lazily, once per side, over every closure text file.
            if side not in graphs:
                strict = units.function_level_files(tree['main'])
                graphs[side] = units.call_graph(units.closure_texts(build['source'], tree), strict_files=strict)
            return graphs[side]
        for key in sorted(set(old_by) | set(new_by)):
            a, b = old_by.get(key), new_by.get(key)
            if a and b and old['files'][a]['sha256'] == new['files'][b]['sha256']:
                continue
            entry = allowed(allowlist, a or b)
            category = entry and entry['category']
            item = dict(file=a or b, allowlisted=category, change='changed' if a and b else ('removed' if a else 'added'),
                        export_sha256=a and old['files'][a]['sha256'], installed_sha256=b and new['files'][b]['sha256'])
            if (a or b).lower().endswith(TEXT_SUFFIXES):
                old_text = normalize(decode(export_build['source'].read(a))) if a else ''
                new_text = normalize(decode(installed_build['source'].read(b))) if b else ''
                lines = _changed_lines(old_text, new_text)
                item.update(changed_lines=len(lines), added=sum(l.startswith('+') for l in lines), removed=sum(l.startswith('-') for l in lines))
                hits = _guard_hits(lines) if category else []
                if hits:
                    item['guard_hits'] = hits[:20]
                if a and b and key in unit_files and not category:
                    # The entrypoint and Optimizer.mqh: compared unit by unit (studio_function_units).
                    try:
                        result = units.compare_texts(a, old_text, new_text, allowlist=function_allowlist,
                                                     old_graph=graph('export', export_build, old), new_graph=graph('installed', installed_build, new))
                    except units.UnitParseError as exc:
                        problems.append('function-level comparison of %s is uncertain: %s' % (a, exc))
                        result = None
                    if result is not None:
                        function_level.append(result)
                        item['function_level'] = dict(equivalent=result['equivalent'], counts=result['counts'], layout=result['layout'],
                                                      blocking_units=result['blocking'])
            unreviewed = [h for h in (item['export_sha256'], item['installed_sha256']) if h and entry and h not in entry['reviewed_sha256']]
            if item.get('function_level'):
                fl = item['function_level']
                if not fl['equivalent']:
                    item['blocking'] = 'function-level: %d differing units block%s' % (
                        len(fl['blocking_units']), (' and ' + '; '.join(fl['layout'])) if fl['layout'] else '')
            elif not category:
                item['blocking'] = 'not on the non-trading allowlist'
            elif unreviewed:
                item['blocking'] = 'allowlisted path, but version %s is not in the reviewed receipt' % ', '.join(h[:12] for h in unreviewed)
            elif item.get('guard_hits'):
                item['blocking'] = 'allowlisted, but a changed line touches trading, signal, #define or input code'
            differing.append(item)
            if item.get('blocking'):
                blocking.append(item['file'])
        inputs_equal = old['input_header_sha256'] == new['input_header_sha256']
        old_hashes, new_hashes = export_build.get('externals_sha256') or {}, installed_build.get('externals_sha256') or {}
        externals_differ = sorted(n for n in set(hashed_externals(old['externals'])) | set(hashed_externals(new['externals']))
                                  if old_hashes.get(n) != new_hashes.get(n))
        # When both builds carry a compile-log manifest, every external file the compiler read is compared too.
        old_read, new_read = export_build.get('externals_consumed'), installed_build.get('externals_consumed')
        consumed_differ = (sorted(p for p in set(old_read) | set(new_read) if old_read.get(p) != new_read.get(p))
                           if old_read is not None and new_read is not None else None)
        externals_equal = old['externals'] == new['externals'] and not externals_differ and not consumed_differ
        compiler_equal = export_build['compiler_sha256'] == installed_build['compiler_sha256']
        comparison = dict(differing=differing, blocking=blocking, input_header_equal=inputs_equal, externals_equal=externals_equal,
                          externals_hash_differs=externals_differ, compiler_equal=compiler_equal,
                          externals_consumed_compared=consumed_differ is not None, externals_consumed_differs=consumed_differ or [],
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
        source_equivalent = (not comparison['blocking'] and comparison['input_header_equal'] and comparison['externals_equal']
                             and comparison['compiler_equal'])
        status = 'pending_canary' if source_equivalent else 'not_equivalent'
    body = dict(schema=SCHEMA, export_build=_public_build(export_build, trees.get('export'), allowlist),
                installed_build=_public_build(installed_build, trees.get('installed'), allowlist),
                allowlist=dict(id=allowlist['id'], sha256=digest_of(allowlist), review_ref=allowlist.get('review_ref')),
                normalizations=NORMALIZATIONS, guard=GUARD.pattern, problems=problems, comparison=comparison,
                function_level=dict(schema=units.SCHEMA, rules=units.RULES, trading_roots=list(units.TRADING_ROOTS),
                                    allowlist=units.allowlist_summary(function_allowlist),
                                    files=[{k: v for k, v in r.items() if k != 'schema'} for r in function_level]),
                source_equivalent=source_equivalent, source_status=status,
                canary_rule=dict(min_sets=MIN_CANARY_SETS, compare='every buy/sell deal: server_time_msc, deal_type, deal_entry, lots, price',
                                 same='window and tester model per set; distinct sets; binaries recorded per deal file'))
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


def _binary_matches(build, identity):
    """A deal file's producing binary (sha256, else build id) against one certificate side."""
    if not identity:
        return False
    if build.get('ea_sha256'):
        return identity == build['ea_sha256']
    return bool(build.get('build_id')) and identity == build['build_id']


def canary_result(cert, pairs, *, min_sets=MIN_CANARY_SETS, source='pairs', incomplete=()):
    """Judge canary pairs for one certificate.

    Each pair: label, values_sha256, reference/candidate deals paths, reference/candidate binary
    (``reference_ea``/``candidate_ea``: sha256, else build id), model and window (``[from, to]``),
    optional cut_msc. ``min_sets`` can only raise the floor of MIN_CANARY_SETS. A set counts once
    (distinct values and distinct reference deal files). Drift in any protocol-clean pair refutes
    the certificate, whatever else the canary holds; a protocol error or an incomplete member only
    stops activation.
    """
    verify_certificate(cert)
    if type(min_sets) is not int or not MIN_CANARY_SETS <= min_sets <= MAX_CANARY_SETS:
        raise ValueError('min_sets must be %d..%d (10 is a hard floor)' % (MIN_CANARY_SETS, MAX_CANARY_SETS))
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_CANARY_SETS:
        raise ValueError('A canary needs 1..%d set pairs' % MAX_CANARY_SETS)
    sets, seen_values, seen_reference = [], set(), set()
    for index, pair in enumerate(pairs):
        label = str(pair.get('label') or index + 1)
        errors = []
        if pair.get('reference_model') is None or pair.get('reference_model') != pair.get('candidate_model'):
            errors.append('different or unknown tester models (%s / %s)' % (pair.get('reference_model'), pair.get('candidate_model')))
        if not pair.get('reference_window') or list(pair.get('reference_window')) != list(pair.get('candidate_window') or []):
            errors.append('different or unknown windows')
        if not _binary_matches(cert['export_build'], pair.get('reference_ea')):
            errors.append('reference deals not recorded as made by the export build (%s)' % pair.get('reference_ea'))
        if not _binary_matches(cert['installed_build'], pair.get('candidate_ea')):
            errors.append('candidate deals not recorded as made by the installed build (%s)' % pair.get('candidate_ea'))
        cut = pair.get('cut_msc')
        if cut is not None and type(cut) is not int:
            errors.append('cut_msc must be integer milliseconds')
            cut = None
        values = pair.get('values_sha256')
        reference_sha, candidate_sha = _file_sha(pair['reference_deals']), _file_sha(pair['candidate_deals'])
        if not isinstance(values, str) or not values:
            errors.append('values_sha256 is required')
        elif values in seen_values or reference_sha in seen_reference:
            errors.append('repeats a set already in this canary')
        seen_values.add(values)
        seen_reference.add(reference_sha)
        compared = compare_deals(deal_list(pair['reference_deals'], cut_msc=cut), deal_list(pair['candidate_deals'], cut_msc=cut))
        if not compared['reference_deals'] and not compared['candidate_deals']:
            # Both builds traded nothing: a licence or init failure (VerifyLicense gates OnInit) looks exactly
            # like this, so an equal-empty set proves nothing and blocks activation (Claude-Mac, #157).
            errors.append('empty set: 0 deals on both sides (an equal-empty canary never certifies)')
        sets.append(dict(label=label, values_sha256=values, model=pair.get('reference_model'), window=pair.get('reference_window'), cut_msc=cut,
                         reference_ea=pair.get('reference_ea'), candidate_ea=pair.get('candidate_ea'),
                         reference_deals_sha256=reference_sha, candidate_deals_sha256=candidate_sha, protocol_errors=errors, **compared))
    protocol = ['%s: %s' % (s['label'], e) for s in sets for e in s['protocol_errors']]
    clean = [s for s in sets if not s['protocol_errors']]
    drift = [s['label'] for s in clean if not s['matched']]
    counted = [s for s in clean if s['matched'] and s['reference_deals'] > 0 and s['candidate_deals'] > 0]
    incomplete = list(incomplete or ())
    matched = not protocol and not drift and not incomplete and len(counted) >= min_sets
    if drift:
        plain = 'Deal drift in %d of %d sets (%s): the builds do not trade the same.' % (len(drift), len(sets), ', '.join(drift[:5]))
    elif protocol:
        plain = 'Canary protocol error: ' + '; '.join(protocol[:5])
    elif incomplete:
        plain = '%d canary members did not finish; they count against the canary.' % len(incomplete)
    elif len(counted) < min_sets:
        plain = 'Deals matched, but only %d distinct sets with trades (%d needed).' % (len(counted), min_sets)
    else:
        plain = 'Identical deal lists in all %d sets (%d deals).' % (len(sets), sum(s['reference_deals'] for s in sets))
    body = dict(schema=CANARY_SCHEMA, certificate_digest=cert['digest'], export_ea_sha256=cert['export_build'].get('ea_sha256'),
                installed_ea_sha256=cert['installed_build'].get('ea_sha256'), source=source, min_sets=min_sets,
                sets=sets, sets_with_trades=len(counted), models=sorted({s['model'] for s in counted}), drift=drift,
                protocol_errors=protocol, incomplete=incomplete, matched=matched, refutes=bool(drift), plain=plain)
    return body | dict(digest=digest_of(body), created_utc=_now())


def verify_canary(record):
    body = {k: v for k, v in record.items() if k not in ('digest', 'created_utc')}
    if record.get('schema') != CANARY_SCHEMA or digest_of(body) != record.get('digest'):
        raise ValueError('Canary digest does not match its contents')
    return record


def _canary_activates(canary, cert):
    """Re-derive activation from the stored sets: the floor, distinctness and cleanliness are never trusted from flags."""
    floor = max(MIN_CANARY_SETS, (cert.get('canary_rule') or {}).get('min_sets') or 0)
    sets = canary.get('sets') or []
    if canary.get('protocol_errors') or canary.get('incomplete') or any(s.get('protocol_errors') for s in sets):
        return False, []
    if any(not s.get('matched') for s in sets):
        return False, []
    # Every set needs at least one deal on both sides; an empty set (or an empty canary) never activates.
    if not sets or any(not s.get('reference_deals') or not s.get('candidate_deals') for s in sets):
        return False, []
    counted = [s for s in sets if s.get('reference_deals', 0) > 0]
    values = {s.get('values_sha256') for s in counted}
    references = {s.get('reference_deals_sha256') for s in counted}
    if None in values or len(values) != len(counted) or len(references) != len(counted):
        return False, []
    return len(counted) >= floor, sorted({s.get('model') for s in counted})


def _canary_refutes(canary):
    return any(not s.get('matched') and not s.get('protocol_errors') for s in canary.get('sets') or [])


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
    """The certificate with its canaries and its effective status (see STATUSES).

    Any bound canary with drift in a protocol-clean set refutes the certificate for good; an
    unreadable canary file blocks activation (it might be the refuting one)."""
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
        activates, models = _canary_activates(canary, cert)
        canaries.append(dict(path=str(path), digest=canary['digest'], matched=activates and bound, models=models,
                             refutes=_canary_refutes(canary) and bound, sets=len(canary['sets']),
                             sets_with_trades=canary['sets_with_trades'], plain=canary['plain']))
    status = cert['source_status']
    active = None
    if status == 'pending_canary':
        if any(c['refutes'] for c in canaries):
            status = 'refuted'
        elif not invalid:
            active = next((c for c in canaries if c['matched']), None)
            status = 'active' if active else 'pending_canary'
    return dict(digest=digest, status=status, active=status == 'active', canary_digest=active and active['digest'],
                canary_models=active['models'] if active else [],
                export_build=dict((k, cert['export_build'].get(k)) for k in ('ea_sha256', 'build_id', 'commit', 'provenance')),
                installed_build=dict((k, cert['installed_build'].get(k)) for k in ('ea_sha256', 'build_id', 'commit', 'provenance')),
                source_equivalent=cert['source_equivalent'], canaries=canaries, invalid_canaries=invalid,
                blocking=(cert.get('comparison') or {}).get('blocking'), problems=cert.get('problems'),
                certificate_path=str(store_root(controller_root) / digest / 'certificate.json'))


def covers(cert_state, *, export_ea_sha256=None, export_build_id=None, installed_ea_sha256=None):
    """Does this certificate cover an export of this build re-tested on this installed build?

    A certificate for a specific binary covers only exports that record that binary; one made
    from a build id alone covers exports known only by that build id."""
    export, installed = cert_state['export_build'], cert_state['installed_build']
    if not installed_ea_sha256 or installed.get('ea_sha256') != installed_ea_sha256:
        return False
    if export.get('ea_sha256'):
        return export_ea_sha256 == export['ea_sha256']
    return not export_ea_sha256 and bool(export_build_id) and export.get('build_id') == export_build_id


# ---- canary from a catch-up run, canary planning -------------------------------------------
def _msc(moment):
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def catchup_pairs(controller_root, catchup_id, digest):
    """Canary pairs from a finished canary catch-up: the original export's capture deals (export
    build) against the re-test's capture deals (installed build), up to the original's last minute.
    Canary members that did not finish with both captures are returned as ``incomplete``."""
    from studio_catchup_verdict import equity_rows
    from studio_evidence import read_export
    from studio_seed_results import read_seed_json
    if not isinstance(catchup_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', catchup_id):
        raise ValueError('Catch-up ID must use 1..80 letters/digits/underscore/hyphen')
    import studio_build_migration as migration
    root = Path(controller_root) / 'catchups' / catchup_id
    manifest = read_seed_json(root / 'manifest.json')
    # A build-migration catch-up re-tests another build on purpose: never canary evidence for a certificate.
    migration.refuse(manifest.get('build_migration') or {}, 'equivalence-canary-ingest')
    run_state = read_seed_json(root / 'state.json')
    pairs, skipped, incomplete = [], [], []
    for spec, item in zip(manifest['members'], run_state['members']):
        migration.refuse(spec.get('build_migration') or {}, 'equivalence-canary-ingest')
        pins = spec.get('pins') or {}
        bridge = pins.get('equivalence') or {}
        if bridge.get('mode') != 'canary' or bridge.get('certificate_digest') != digest:
            skipped.append(dict(alias=spec['alias'], reason='not a canary member of this certificate'))
            continue
        if item.get('status') != 'completed' or not item.get('result'):
            incomplete.append(dict(alias=spec['alias'], reason='not completed (%s)' % item.get('status')))
            continue
        result = migration.refuse(read_seed_json(item['result']['path']), 'equivalence-canary-ingest')
        version = migration.refuse(json.loads(Path(result['version_path']).read_text(encoding='utf-8')), 'equivalence-canary-ingest')
        original = read_export(spec['original']['set_path'])
        if original['set_sha256'] != spec['original']['set_sha256']:
            raise ValueError('Original export changed since the canary was prepared: ' + spec['original']['set_path'])
        reference_capture, candidate_capture = original.get('capture') or {}, (version.get('retest') or {}).get('capture') or {}
        if not reference_capture.get('complete') or not candidate_capture.get('path') or candidate_capture.get('status') != COMPLETE_CAPTURE:
            incomplete.append(dict(alias=spec['alias'], reason='a capture is missing or incomplete'))
            continue
        cut = equity_rows(original['csv_path'])[-1][0]
        retest = read_export(version['retest']['set_path'])
        window_ref = [original['evidence_start'], cut.strftime('%Y-%m-%d %H:%M')]
        window_new = [retest['evidence_start'], cut.strftime('%Y-%m-%d %H:%M')]
        pairs.append(dict(label=spec['alias'] + ' ' + spec['tester']['Symbol'], values_sha256=spec['original']['values_sha256'],
                          reference_deals=str(Path(reference_capture['path']).parent / 'deals.csv'),
                          candidate_deals=str(Path(candidate_capture['path']).parent / 'deals.csv'),
                          reference_ea=pins.get('original_ea_sha256') or pins.get('original_build_id'),
                          candidate_ea=pins.get('installed_ea_sha256'),
                          reference_model=reference_capture.get('model'), candidate_model=(retest.get('capture') or {}).get('model'),
                          reference_window=window_ref, candidate_window=window_new, cut_msc=_msc(cut)))
    return pairs, skipped, incomplete


COMPLETE_CAPTURE = 'complete-awaiting-import-verification'


def canary_plan(controller_root, digest, sources, *, max_sets=MIN_CANARY_SETS, evidence_end='auto', job_timeout_seconds=7200,
                broker_clock=None, now=None):
    """A catch-up plan that canaries one source-equivalent certificate on ~10 diverse exports of its
    export build. Only exports the catch-up will actually run (``behind`` the resolved end) are chosen."""
    from studio_catchup import classify, resolve_target
    from studio_evidence import scan
    cert_state = state(controller_root, digest)
    if cert_state['status'] not in ('pending_canary', 'active'):
        raise ValueError('Certificate %s is %s; only a source-equivalent certificate is canaried' % (digest[:12], cert_state['status']))
    if type(max_sets) is not int or not MIN_CANARY_SETS <= max_sets <= MAX_CANARY_SETS:
        raise ValueError('max_sets must be %d..%d' % (MIN_CANARY_SETS, MAX_CANARY_SETS))
    target = resolve_target(evidence_end, broker_clock=broker_clock, now=now)
    exports, unreadable = scan([str(s) for s in sources])
    export_build = cert_state['export_build']
    eligible, not_behind = [], 0
    for export in exports:
        capture = export.get('capture') or {}
        run_ea = (export.get('run') or {}).get('ea_sha256')
        same = covers(cert_state, export_ea_sha256=run_ea, export_build_id=None if run_ea else capture.get('build_id'),
                      installed_ea_sha256=cert_state['installed_build'].get('ea_sha256'))
        deals = capture.get('path') and Path(capture['path']).parent / 'deals.csv'
        if not (same and capture.get('complete') and capture.get('model') == 4 and deals and deals.is_file() and not export.get('problems')):
            continue
        if classify(export, target['iso'], include_below_threshold=True)['status'] != 'behind':
            not_behind += 1
            continue
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
    if broker_clock:
        plan['broker_clock'] = broker_clock
    return dict(plan=plan, target=target['iso'], eligible=len(eligible), not_behind=not_behind,
                chosen=[dict(symbol=e['symbol'], set_path=e['set_path'], passing=e['threshold']['passing']) for e in chosen],
                unreadable=len(unreadable), enough=len(chosen) >= MIN_CANARY_SETS,
                next_action='catchup-prepare with this plan, catchup-start on the installed build, then equivalence-canary-ingest --catchup-id')


# ---- CLI -----------------------------------------------------------------------------------
OPERATIONS = ('equivalence-certificate', 'equivalence-status', 'equivalence-canary-plan', 'equivalence-canary-ingest')


def _externals_arg(path, mql5_root, tree_externals):
    if path:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
            raise ValueError('An externals file maps external names to sha256 strings')
        if NOT_CONSUMED in value.values():
            raise ValueError('"%s" is accepted only from a compile-log externals manifest' % NOT_CONSUMED)
        return value
    if mql5_root:
        return hash_externals(mql5_root, tree_externals)
    return None


def operation(controller, args):
    """CLI routes. No MT5 or terminal effect; writes only under <controller state>\\equivalence."""
    root = controller.root
    if args.operation == 'equivalence-certificate':
        main = args.main or DEFAULT_MAIN
        export = resolve_build(args.repo, ea_sha256=args.export_ea_sha256, build_id=args.export_build_id, commit=args.export_commit, main=main)
        installed_sha = args.installed_ea_sha256 or controller.install['ea_sha256']
        installed = resolve_build(args.repo, ea_sha256=None if args.installed_commit else installed_sha, commit=args.installed_commit, main=main)
        installed['ea_sha256'] = installed_sha
        for build, prefix in ((export, 'export'), (installed, 'installed')):
            compiler = getattr(args, prefix + '_compiler_sha256', None)
            if compiler:
                build['compiler_sha256'] = compiler
            if build.get('status') == 'resolved':
                path = getattr(args, prefix + '_externals', None)
                if path and json.loads(Path(path).read_text(encoding='utf-8-sig')).get('schema') == EXTERNALS_SCHEMA:
                    # A compile-log externals manifest, consumed directly (bound to the binary and the compile commit).
                    use_explicit_manifest(build, path)
                    continue
                names = closure(build['source'], main)['externals']
                given = _externals_arg(path, getattr(args, prefix + '_mql5_root', None), names)
                if given is not None:
                    build['externals_sha256'] = given
        cert = certificate(export, installed)
        path = save_certificate(root, cert)
        comparison = cert.get('comparison') or {}
        return dict(state(root, cert['digest']), certificate_path=str(path), problems=cert['problems'],
                    differing=[{k: d.get(k) for k in ('file', 'change', 'allowlisted', 'changed_lines', 'blocking')} for d in comparison.get('differing', [])],
                    input_header_equal=comparison.get('input_header_equal'), externals_equal=comparison.get('externals_equal'),
                    compiler_equal=comparison.get('compiler_equal'))
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
            pairs, skipped, incomplete = catchup_pairs(root, args.catchup_id, args.certificate)
            source = 'catchup:' + args.catchup_id
        else:
            pairs, skipped, incomplete = json.loads(Path(args.pairs).read_text(encoding='utf-8-sig')), [], []
            source = 'pairs:' + str(args.pairs)
        canary = canary_result(cert, pairs, min_sets=args.min_sets, source=source, incomplete=incomplete)
        path = save_canary(root, canary)
        return dict(canary_path=str(path), canary_digest=canary['digest'], matched=canary['matched'], refutes=canary['refutes'],
                    plain=canary['plain'], skipped=skipped, incomplete=incomplete, state=state(root, args.certificate))
    raise ValueError('Not an equivalence operation: ' + args.operation)
