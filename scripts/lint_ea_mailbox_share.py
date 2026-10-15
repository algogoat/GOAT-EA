"""EA-MAILBOX-SHARE-01: the EA never opens a controller mailbox file for reading without FILE_SHARE_READ.

B44 doesn't pin while it fails.

Why (2026-10-12 VPS crash, goatai#2350 6127147178): GoatSetupRead opened request.json with
FILE_READ|FILE_BIN|FILE_COMMON and no FILE_SHARE_READ, so while the EA read it the controller's
open('rb') got errno 13 and its bounded sharing_retry ran out. The controller writes every mailbox
file through a temporary file and a rename, so a reader needs FILE_SHARE_READ only.

Rule, over GOAT V1.49.mq5 and every .mqh at the repo root (comments ignored):
- A mailbox path is a FileOpen path built from the setup, portfolio or Studio native-gate root
  (GOAT\\AgentSetup\\, GOAT\\AgentPortfolio\\, GOATStudio\\native-gate) or naming request.json,
  registration.json, a .pending or .request.json file (receipts live under those roots). A path that is a parameter or a local
  is followed to every value it is given (call sites and assignments, a few levels deep).
- Every reader-only open (FILE_READ without FILE_WRITE) of a mailbox path carries FILE_SHARE_READ and
  never FILE_SHARE_WRITE (that would allow a torn read).
- A read-write open of a mailbox path is refused, except the explicit lock allowlist: owner.lock and
  native-gate launch.lock (deliberate exclusive locks).
- Write-only opens (the EA's own temporary files before a rename) are listed, not refused.

Usage: python scripts/lint_ea_mailbox_share.py [--root <GOAT-EA>] [--json]. Exit 0 clean, 1 findings.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RULE = 'EA-MAILBOX-SHARE-01'
MAIN = 'GOAT V1.49.mq5'
# Receipts are `<root><id>.json` (and native-gate result-<id>.json): the root tokens cover them.
MAILBOX_TOKENS = ('AgentSetup', 'AgentPortfolio', 'native-gate', 'request.json', 'registration.json', '.pending',
                  '.request.json', 'owner.lock', 'launch.lock')
LOCK_ALLOWLIST = ('owner.lock', 'launch.lock')
MAX_DEPTH = 4
_HEADER = re.compile(r'^[ \t]*(?:static[ \t]+|virtual[ \t]+)?(?:const[ \t]+)?[A-Za-z_]\w*[ \t&*]+(?:[A-Za-z_]\w*::)?'
                     r'([A-Za-z_]\w*)[ \t]*\(([^;{}]*)\)[ \t]*(?:const)?[ \t]*(?:\{|$)', re.M)
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'else', 'sizeof'}


def strip_comments(text):
    """Comments become spaces; string literals and line numbers are kept."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def call_args(text, open_paren):
    """Top-level arguments of the call whose '(' is at open_paren, and the index after its ')'."""
    depth, args, start, i = 0, [], open_paren + 1, open_paren
    while i < len(text):
        c = text[i]
        if c == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            i = j
        elif c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
            if depth == 0:
                args.append(text[start:i].strip())
                return args, i + 1
        elif c == ',' and depth == 1:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    raise ValueError('unbalanced call at offset %d' % open_paren)


class Source:
    def __init__(self, name, text):
        self.name, self.text = name, strip_comments(text)
        self.functions = []   # (start, name, params)
        for m in _HEADER.finditer(self.text):
            if m.group(1) in _KEYWORDS:
                continue
            params = [p.strip() for p in m.group(2).split(',') if p.strip() and p.strip() != 'void']
            names = [re.sub(r'=.*$', '', p).strip() for p in params]
            names = [re.sub(r'\[\s*\]$', '', n).strip() for n in names]
            names = [re.split(r'[\s&*]+', n)[-1] for n in names]
            self.functions.append((m.start(), m.group(1), names))

    def line(self, offset):
        return self.text.count('\n', 0, offset) + 1

    def enclosing(self, offset):
        found = None
        for start, name, params in self.functions:
            if start <= offset:
                found = (start, name, params)
        return found


def identifiers(expr):
    return [m.group(0) for m in re.finditer(r'(?<![\w."])[A-Za-z_]\w*(?![\w"])', re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr))]


class Linter:
    def __init__(self, sources):
        self.sources = sources

    def callers(self, function):
        pattern = re.compile(r'(?<![\w.:])' + re.escape(function) + r'\s*\(')
        for source in self.sources:
            for m in pattern.finditer(source.text):
                enclosing = source.enclosing(m.start())
                if enclosing and enclosing[1] == function and source.text[enclosing[0]:m.start()].count('\n') == 0:
                    continue   # the definition itself
                try:
                    args, _ = call_args(source.text, m.end() - 1)
                except ValueError:
                    continue
                yield source, m.start(), args

    def values(self, source, offset, expr, depth=0, seen=None):
        """Every expression the path may come from: expr itself, then what its parameters and locals are given."""
        seen = set() if seen is None else seen
        key = (source.name, offset, expr)
        if key in seen or depth > MAX_DEPTH:
            return
        seen.add(key)
        yield expr
        enclosing = source.enclosing(offset)
        if not enclosing:
            return
        start, function, params = enclosing
        body = source.text[start:offset]
        for ident in identifiers(expr):
            if ident in params:
                index = params.index(ident)
                for caller, at, args in self.callers(function):
                    if index < len(args):
                        yield from self.values(caller, at, args[index], depth + 1, seen)
            for m in re.finditer(r'(?<![\w.])' + re.escape(ident) + r'\s*(?:\+=|=(?!=))\s*([^;]+);', body):
                yield from self.values(source, start + m.start(), m.group(1), depth + 1, seen)

    def run(self):
        findings, writers, checked = [], [], []
        for source in self.sources:
            for m in re.finditer(r'(?<![\w.:])FileOpen\s*\(', source.text):
                args, _ = call_args(source.text, m.end() - 1)
                if len(args) < 2:
                    continue
                path, flags = args[0], set(re.findall(r'FILE_\w+', args[1]))
                origins = list(self.values(source, m.start(), path))
                hits = sorted({token for origin in origins for token in MAILBOX_TOKENS if token in origin})
                if not hits:
                    continue
                where = '%s:%d' % (source.name, source.line(m.start()))
                entry = dict(where=where, path=path, flags=sorted(flags), mailbox=hits)
                reads, writes = 'FILE_READ' in flags, 'FILE_WRITE' in flags
                if any(lock in origin for origin in origins for lock in LOCK_ALLOWLIST) and reads and writes:
                    checked.append(dict(entry, verdict='lock allowlist'))
                elif reads and not writes:
                    problems = []
                    if 'FILE_SHARE_READ' not in flags:
                        problems.append('reader-only open without FILE_SHARE_READ')
                    if 'FILE_SHARE_WRITE' in flags:
                        problems.append('reader-only open with FILE_SHARE_WRITE (torn read)')
                    (findings if problems else checked).append(dict(entry, verdict='; '.join(problems) or 'shared read'))
                elif reads and writes:
                    findings.append(dict(entry, verdict='read-write open of a mailbox file outside the lock allowlist'))
                else:
                    writers.append(dict(entry, verdict='write-only (temporary before rename), listed'))
        return dict(rule=RULE, ok=not findings, findings=findings, checked=checked, writers=writers)


def load(root):
    root = Path(root)
    names = [MAIN] + sorted(p.name for p in root.glob('*.mqh'))
    return [Source(name, (root / name).read_text(encoding='utf-8-sig', errors='replace')) for name in names]


def main(argv=None):
    parser = argparse.ArgumentParser(description=RULE)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument('--json', action='store_true')
    options = parser.parse_args(argv)
    report = Linter(load(options.root)).run()
    if options.json:
        print(json.dumps(report, indent=1))
    else:
        for item in report['findings']:
            print('%s FAIL %s: %s (path %s, flags %s)' % (RULE, item['where'], item['verdict'], item['path'], '|'.join(item['flags'])))
        print('%s %s: %d finding(s), %d reader/lock open(s) checked, %d write-only open(s) listed'
              % (RULE, 'PASS' if report['ok'] else 'FAIL', len(report['findings']), len(report['checked']), len(report['writers'])))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
