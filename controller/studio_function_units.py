"""Function-level comparison of the EA entrypoint and Optimizer.mqh (goat-function-units-v1).

The trading-equivalence certificate (``studio_equivalence``) compares every closure file as a
whole. ``GOAT V1.49.mq5`` and ``Optimizer.mqh`` hold trading code next to panel, Studio and
report code, and every build changes them, so whole-file comparison can never certify a new
build. This module splits those two files into top-level units and lets the certificate accept
a changed file only when every unit that differs is on a reviewed non-trading FUNCTION
allowlist (Claude-Mac, algogoat/GOAT-EA#141 APPROVE: "function-by-function comparison of the
entrypoint and Optimizer.mqh ... must fail closed on any parse uncertainty").

Units (keys are stable across builds; the hash is over the unit's exact text after the
certificate's own ``normalize``: encoding, line endings, build id/marker, nothing else):
- ``function <Qualified::name>(<parameters>)``: a function or out-of-line method definition.
  Overloads are distinct keys; the return type and body are in the hash.
- ``method <Class>::<name>(<parameters>)``: an inline method defined in a class body.
- ``class <Name>`` / ``struct`` / ``enum`` / ``union`` / ``interface``: the type's shell (every
  field, declaration and nested type, member order included; inline method bodies are their own
  units and appear in the shell by key).
- ``global <names>``, ``input <names>``, ``declare <name>(...)`` (a prototype or an object built
  with constructor arguments), ``typedef ...``.
- ``#define NAME``, ``#undef NAME``, ``#include ...``, ``#import "dll"`` (the whole block),
  ``#resource ...``, ``#property NAME`` and the conditional lines themselves.
- ``gap before <key>`` / ``gap at end``: the text between units. A tiling check proves every
  character of the file is in exactly one unit or gap, so a gap holds only comments, whitespace
  and stray ``;``. A gap difference is reported; it blocks only when a token other than a comment
  or whitespace changed (comments between units cannot change compiled code; inside a unit
  nothing is stripped, exactly as the file-level hash).
A unit inside a top-level ``#if``/``#ifdef``/``#ifndef`` group carries the group in its key.

Fail closed (``UnitParseError`` -> certificate ``not_comparable`` with the reason) on: unbalanced
braces or parentheses, an unterminated string or comment, a preprocessor conditional whose
branches change brace depth or that opens and closes in different units, a directive inside a
top-level declaration, ``#include``/``#import``/``#resource``/``#property`` inside a body, a
``#define``/``#undef`` inside a body, a macro whose replacement holds ``{``, ``}`` or ``;`` (it can
define functions), a known function-like macro in a function header, any top-level statement the
parser cannot classify, and duplicate or ambiguous signatures (same name and parameter types).

Blocking rules for a differing unit (``compare_texts``): preprocessor units, ``input`` units and a
changed ``global``/``declare`` (default or constructor argument) are never allowlistable; a moved
directive, a changed top-level declaration order, or a unit moved across a directive blocks; every
other differing, added or removed unit blocks unless its (file, key) is in the reviewed receipt
with both hashes, the receipt is confirmed, its changed lines pass the certificate's GUARD, and,
when a conservative name-level call graph reaches it from a trading entry point (``OnTick``,
``OnTester``, ``OnTesterInit``, ``OnTesterPass``, ``OnTesterDeinit``, ``OnTradeTransaction``), the
entry says ``trading_path_reviewed: true``. Reachability is evidence for the reviewer; it never
clears a unit by itself.

Research tooling: reads text, never touches MT5. CLI: ``python studio_function_units.py
units-diff`` prints the differing units of two builds with suggested receipt stubs, and
``externals-manifest`` fingerprints a candidate compile (see ``studio_equivalence``).
"""
from bisect import bisect_right
import difflib
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'goat-function-units-v1'
ALLOWLIST_SCHEMA = 'goat-non-trading-function-allowlist-receipt-v1'
FUNCTION_ALLOWLIST_PATH = Path(__file__).resolve().parent / 'contracts' / 'equivalence' / 'non-trading-function-allowlist-v1.json'
OPTIMIZER = 'Optimizer.mqh'
TRADING_ROOTS = ('OnTick', 'OnTester', 'OnTesterInit', 'OnTesterPass', 'OnTesterDeinit', 'OnTradeTransaction')
LIFECYCLE_ROOTS = ('OnInit', 'OnDeinit', 'OnTimer', 'OnTrade', 'OnChartEvent', 'OnBookEvent')
TYPE_KEYWORDS = ('class', 'struct', 'enum', 'union', 'interface')
NEVER_ALLOWLISTED = ('directive', 'input')
RULES = [
    'units: functions (exact signature, overloads distinct), class/struct/enum shells and inline methods, globals, inputs, '
    'declarations, every preprocessor line, and the comment/whitespace gaps between units',
    'unit hash: sha256 of the unit text after the certificate normalization (encoding, line endings, build id/marker)',
    'units and gaps tile the file exactly; a gap (between units) blocks only when a non-comment, non-whitespace token changed',
    'fail closed (not_comparable) on any parse uncertainty: unbalanced braces, conditionals that change unit boundaries, '
    'macros that can define functions, unclassifiable statements, #include/#define inside a body, duplicate or ambiguous signatures',
    'never allowlistable: any preprocessor unit, any input, a changed global or declaration, directive order, global order, '
    'a unit moved across a directive',
    'allowlistable only with a confirmed receipt entry holding both hashes, no GUARD hit, and trading_path_reviewed when the '
    'call graph reaches the unit from OnTick/OnTester/OnTesterInit/OnTesterPass/OnTesterDeinit/OnTradeTransaction',
]
_CONTROL = frozenset(('if', 'for', 'while', 'switch', 'return', 'sizeof', 'else', 'do', 'case', 'new', 'delete', 'typename'))
_AFTER_PARAMS = frozenset(('const', 'override', 'final'))


class UnitParseError(ValueError):
    """The parser is not certain of a unit boundary or classification: the certificate fails closed."""


# ---- lexer ---------------------------------------------------------------------------------
_TOKEN = re.compile(r'''
 (?P<ws>[ \t\f\v\r]+)
|(?P<nl>\n)
|(?P<lc>//[^\n]*)
|(?P<bc>/\*.*?\*/)
|(?P<bcopen>/\*)
|(?P<str>"(?:[^"\\\n]|\\.)*")
|(?P<strbad>")
|(?P<chr>'(?:[^'\\\n]|\\.)*')
|(?P<chrbad>')
|(?P<id>[A-Za-z_]\w*)
|(?P<num>(?:0[xX][0-9A-Fa-f]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)[A-Za-z]*)
|(?P<punct><<=|>>=|::|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^!=<>]=|\#\#|[^\s\w])
''', re.S | re.X)


class Tok(tuple):
    __slots__ = ()
    kind = property(lambda self: self[0])
    start = property(lambda self: self[1])
    end = property(lambda self: self[2])
    value = property(lambda self: self[3])


class Text:
    def __init__(self, text, file):
        self.text, self.file = text, file
        self._lines = [i for i, c in enumerate(text) if c == '\n']

    def line(self, offset):
        return bisect_right(self._lines, offset - 1) + 1

    def fail(self, offset, message):
        raise UnitParseError('%s line %d: %s' % (self.file, self.line(offset), message))


def _directive_code(src, start, end):
    """Comment-free directive text with whitespace and line continuations collapsed to one space."""
    raw, out, pos, gap = src.text[start:end], [], 0, False
    while pos < len(raw):
        m = _TOKEN.match(raw, pos)
        kind = m.lastgroup
        if kind == 'bcopen':
            src.fail(start + pos, 'a block comment opened on a preprocessor line runs past it')
        if kind in ('strbad', 'chrbad'):
            src.fail(start + pos, 'unterminated literal on a preprocessor line')
        if kind == 'lc':
            break
        if kind in ('ws', 'nl', 'bc'):
            gap = True
        elif kind == 'punct' and m.group() == '\\' and raw[m.end():].lstrip(' \t\r').startswith('\n'):
            gap = True
        else:
            if gap and out:
                out.append(' ')
            out.append(m.group())
            gap = False
        pos = m.end()
    return ''.join(out)


def lex(src):
    text, toks, pos, n, line_start = src.text, [], 0, len(src.text), True
    while pos < n:
        if line_start and text[pos] == '#':
            end = pos
            while True:
                k = text.find('\n', end)
                if k < 0:
                    k = n
                    break
                if text[end:k].rstrip(' \t\r').endswith('\\'):
                    end = k + 1
                    continue
                break
            toks.append(Tok(('pp', pos, k, _directive_code(src, pos, k))))
            pos, line_start = k, False
            continue
        m = _TOKEN.match(text, pos)
        kind = m.lastgroup
        if kind == 'nl':
            line_start = True
        elif kind in ('ws', 'lc', 'bc'):
            pass
        elif kind == 'bcopen':
            src.fail(pos, 'unterminated block comment')
        elif kind in ('strbad', 'chrbad'):
            src.fail(pos, 'unterminated string or character literal')
        else:
            toks.append(Tok((kind, pos, m.end(), m.group())))
            line_start = False
        pos = m.end()
    return toks


def _collapse(toks):
    return ' '.join(t.value for t in toks)


def _sig(toks):
    """Readable, stable parameter text for unit keys: ``const string &name,int x[]=0``-style spacing."""
    out, prev = [], None
    for tok in toks:
        v = tok.value
        if out and not (v in (',', ')', ']', '[', '::') or prev in ('(', '[', '&', '*', '~', '::')):
            out.append(' ')
        out.append(v)
        prev = v
    return ''.join(out)


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


_EMPTY = _sha('')


# ---- parser --------------------------------------------------------------------------------
def _directive_word(code):
    m = re.match(r'#\s*(\w+)\s*(.*)$', code, re.S)
    return (m.group(1), m.group(2)) if m else ('', code)


def _macro_name(rest):
    m = re.match(r'(\w+)(\()?', rest)
    return (m.group(1), bool(m.group(2))) if m else (None, False)


class _Parser:
    def __init__(self, src, strict=True, function_macros=frozenset()):
        self.src, self.strict, self.function_macros = src, strict, set(function_macros)
        self.toks = lex(src)
        self.units, self.cond, self.segment, self.ordinals = [], [], 0, {}
        self.macros = {}   # name -> identifiers of its replacement (for the call graph)

    def fail(self, tok, message):
        self.src.fail(tok.start if tok is not None else len(self.src.text), message)

    def _key(self, base):
        prefix = ''.join('[%s] ' % c for c in self.cond)
        key = prefix + base
        count = self.ordinals.get(key, 0) + 1
        self.ordinals[key] = count
        return key if count == 1 else '%s @%d' % (key, count)

    def add(self, kind, base, start, end, *, name=None, idents=(), text=None, code=None, extra=None, ordinal=False):
        key = self._key(base) if ordinal else ''.join('[%s] ' % c for c in self.cond) + base
        body = self.src.text[start:end] if text is None else text
        unit = dict(key=key, kind=kind, name=name, start=start, end=end, line=self.src.line(start), end_line=self.src.line(end),
                    sha256=_sha(body), code_sha256=_sha(code if code is not None else body), segment=self.segment,
                    idents=sorted(set(idents)), text=body)
        unit.update(extra or {})
        self.units.append(unit)
        return unit

    # -- directives
    def directive(self, i):
        tok = self.toks[i]
        word, rest = _directive_word(tok.value)
        end = tok.end
        if word in ('if', 'ifdef', 'ifndef'):
            self.add('directive', tok.value, tok.start, end, code=tok.value, ordinal=True)
            self.cond.append(tok.value)
        elif word in ('elif', 'else'):
            if not self.cond:
                self.fail(tok, '#%s without an open conditional' % word)
            opened = self.cond.pop()
            self.add('directive', tok.value + ' (of ' + opened + ')', tok.start, end, code=tok.value, ordinal=True)
            self.cond.append(opened + ' / ' + tok.value)
        elif word == 'endif':
            if not self.cond:
                self.fail(tok, '#endif without an open conditional')
            opened = self.cond.pop()
            self.add('directive', '#endif (of ' + opened + ')', tok.start, end, code=tok.value, ordinal=True)
        elif word in ('define', 'undef'):
            name, function_like = _macro_name(rest)
            if not name:
                self.fail(tok, 'unreadable #%s' % word)
            if word == 'define':
                replacement = rest[len(name):]
                if function_like:
                    self.function_macros.add(name)
                if self.strict and re.search(r'[{};]', re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', '', replacement)):
                    self.fail(tok, 'macro %s holds { } or ; and could define a function' % name)
                self.macros[name] = set(re.findall(r'[A-Za-z_]\w*', re.sub(r'"(?:[^"\\]|\\.)*"', '', replacement)))
            self.add('directive', '#%s %s' % (word, name), tok.start, end, code=tok.value, ordinal=True)
        elif word == 'import':
            if rest:
                j = i + 1
                while j < len(self.toks) and not (self.toks[j].kind == 'pp' and _directive_word(self.toks[j].value) == ('import', '')):
                    if self.toks[j].kind == 'pp' or self.toks[j].value in ('{', '}'):
                        self.fail(self.toks[j], 'unexpected directive or body inside an #import block')
                    j += 1
                if j >= len(self.toks):
                    self.fail(tok, 'unterminated #import block')
                body = self.toks[i + 1:j]
                self.add('directive', tok.value, tok.start, self.toks[j].end, code=tok.value + ' ' + _collapse(body), ordinal=True)
                self.segment += 1
                return j + 1
            self.fail(tok, 'a closing #import without an opening one')
        elif word in ('include', 'resource', 'property'):
            base = tok.value if word != 'property' else '#property ' + (rest.split() or [''])[0]
            self.add('directive', base, tok.start, end, code=tok.value, ordinal=True)
        else:
            self.fail(tok, 'unknown preprocessor directive #%s' % word)
        self.segment += 1
        return i + 1

    # -- bodies
    def _body_directive(self, tok, depth, stack):
        """A directive inside a body: conditionals must open and close at one brace depth inside the unit."""
        word, rest = _directive_word(tok.value)
        if word in ('if', 'ifdef', 'ifndef'):
            stack.append(depth)
        elif word in ('elif', 'else', 'endif'):
            if not stack:
                self.fail(tok, '#%s closes a conditional opened outside this unit (it changes unit boundaries)' % word)
            if stack[-1] != depth:
                self.fail(tok, '#%s at another brace depth than its #if (the branches change unit boundaries)' % word)
            if word == 'endif':
                stack.pop()
        elif word in ('include', 'import', 'resource', 'property'):
            self.fail(tok, '#%s inside a function or class body' % word)
        elif word in ('define', 'undef'):
            if self.strict:
                self.fail(tok, '#%s inside a function or class body' % word)
            name, function_like = _macro_name(rest)
            if word == 'define' and name:
                if function_like:
                    self.function_macros.add(name)
                self.macros[name] = set(re.findall(r'[A-Za-z_]\w*', re.sub(r'"(?:[^"\\]|\\.)*"', '', rest[len(name):])))
        else:
            self.fail(tok, 'unknown preprocessor directive #%s inside a body' % word)

    def event_map(self, i):
        """The standard library's EVENT_MAP_BEGIN(Class) ... EVENT_MAP_END(Parent) pair (ControlsPlus/Controls
        Defines.mqh, hashed as an external): it expands to ``bool Class::OnEvent(...) { ... return(Parent::OnEvent(...)); }``.
        It is the only function-defining macro the parser accepts, and only in this exact shape."""
        t = self.toks
        if not (i + 3 < len(t) and t[i + 1].value == '(' and t[i + 2].kind == 'id' and t[i + 3].value == ')'):
            self.fail(t[i], 'unreadable EVENT_MAP_BEGIN')
        cls, depth, stack, j = t[i + 2].value, 0, [], i + 4
        while j < len(t):
            tok = t[j]
            if tok.kind == 'pp':
                self._body_directive(tok, depth, stack)
            elif tok.kind == 'punct' and tok.value == '{':
                depth += 1
            elif tok.kind == 'punct' and tok.value == '}':
                depth -= 1
                if depth < 0:
                    self.fail(tok, 'unbalanced closing brace inside an event map')
            elif tok.kind == 'id' and tok.value == 'EVENT_MAP_BEGIN':
                self.fail(tok, 'an event map inside an event map')
            elif tok.kind == 'id' and tok.value == 'EVENT_MAP_END':
                if depth or stack:
                    self.fail(tok, 'EVENT_MAP_END inside an open brace or conditional')
                if not (j + 3 < len(t) and t[j + 1].value == '(' and t[j + 2].kind == 'id' and t[j + 3].value == ')'):
                    self.fail(tok, 'unreadable EVENT_MAP_END')
                body = t[i:j + 4]
                self.add('method', 'event_map %s::OnEvent' % cls, t[i].start, t[j + 3].end, name='OnEvent', code=_collapse(body),
                         idents=[x.value for x in body if x.kind == 'id'], extra=dict(qualified=cls + '::OnEvent', types=['event_map']))
                return j + 4
            j += 1
        self.fail(t[i], 'EVENT_MAP_BEGIN without EVENT_MAP_END')

    def body_end(self, i):
        """Index of the '}' matching toks[i] == '{'. Checks every directive inside the body."""
        depth, stack = 0, []
        for j in range(i, len(self.toks)):
            tok = self.toks[j]
            if tok.kind == 'pp':
                self._body_directive(tok, depth, stack)
                continue
            if tok.value == '{' and tok.kind == 'punct':
                depth += 1
            elif tok.value == '}' and tok.kind == 'punct':
                depth -= 1
                if depth == 0:
                    if stack:
                        self.fail(tok, 'a conditional opened in this unit is still open at its end (it changes unit boundaries)')
                    return j
        self.fail(self.toks[i], 'unbalanced braces: this body never closes')

    # -- declarations
    def _scan(self, i, limit, *, top):
        """End of one declaration starting at i: ('decl', j) at ';' or ('body', j) at a body '{'."""
        paren = 0
        j = i
        while j < limit:
            tok = self.toks[j]
            if tok.kind == 'pp':
                self.fail(tok, 'a preprocessor directive inside a %s declaration' % ('top-level' if top else 'member'))
            v = tok.value if tok.kind == 'punct' else None
            if v in ('(', '['):
                paren += 1
            elif v in (')', ']'):
                paren -= 1
                if paren < 0:
                    self.fail(tok, 'unbalanced parentheses')
            elif v == ';' and paren == 0:
                return 'decl', j
            elif v == '{' and paren == 0:
                header = self.toks[i:j]
                if _at_depth0(header, '='):
                    j = self.body_end(j) + 1
                    continue
                return 'body', j
            elif v == '{':
                self.fail(tok, 'a brace inside parentheses')
            elif v == '}':
                self.fail(tok, 'unbalanced closing brace')
            j += 1
        self.fail(self.toks[i], 'unterminated declaration (unbalanced braces or a missing ;)')

    def top(self, i):
        if self.toks[i].kind == 'id' and self.toks[i].value == 'EVENT_MAP_BEGIN':
            return self.event_map(i)
        kind, j = self._scan(i, len(self.toks), top=True)
        if kind == 'decl':
            self.declaration(i, j)
            return j + 1
        header = self.toks[i:j]
        word = _type_keyword(header)
        if word:
            close = self.body_end(j)
            end = close + 1
            if end < len(self.toks) and self.toks[end].value == ';':
                pass
            else:
                kind2, end = self._scan(end, len(self.toks), top=True)
                if kind2 != 'decl':
                    self.fail(self.toks[close], 'a type definition followed by another body')
            self.type_unit(i, j, close, end, word)
            return end + 1
        if not header or not _at_depth0(header, '('):
            self.fail(header[0] if header else self.toks[j], 'unclassifiable top-level statement before a body')
        close = self.body_end(j)
        self.function_unit(i, j, close, qualifier=None)
        end = close + 1
        return end

    def declaration(self, i, j, *, owner=None):
        toks = self.toks[i:j]
        if not toks:
            return None   # a stray ';' (e.g. after a function body): it stays in the gap, which is hashed
        first = toks[0]
        if first.kind != 'id':
            self.fail(first, 'unclassifiable declaration')
        for tok in toks:
            if tok.kind == 'id' and tok.value in self.function_macros:
                self.fail(tok, 'function-like macro %s in a declaration' % tok.value)
        start, end = first.start, self.toks[j].end
        code = _collapse(toks)
        if first.value in ('input', 'sinput'):
            if len(toks) > 1 and toks[1].value == 'group':
                return self.add('input', 'input group ' + _collapse(toks[2:]), start, end, name='group', code=code, ordinal=True)
            names = _declarator_names(toks[1:])
            return self.add('input', 'input ' + ','.join(names), start, end, name=names[0] if names else None, code=code)
        if first.value == 'typedef':
            return self.add('declaration', 'typedef ' + code[8:], start, end, code=code)
        if first.value in TYPE_KEYWORDS and len(toks) == 2 and toks[1].kind == 'id':
            return self.add('declaration', 'declare %s %s' % (first.value, toks[1].value), start, end, code=code)
        open_at = _index_depth0(toks, '(')
        if open_at is not None and open_at > 0 and not _at_depth0(toks[:open_at], '='):
            name_tok = toks[open_at - 1]
            if name_tok.kind != 'id' or name_tok.value in _CONTROL or open_at < 2:
                self.fail(name_tok, 'unclassifiable declaration (no type before %s: a macro call?)' % name_tok.value)
            close = _match(toks, open_at)
            if close is None:
                self.fail(toks[open_at], 'unbalanced parentheses')
            tail = toks[close + 1:]
            if any(t.value not in _AFTER_PARAMS for t in tail):
                self.fail(tail[0], 'unclassifiable tokens after a parameter list (a macro?)')
            qualified = _qualified(toks, open_at - 1)
            params = _sig(toks[open_at + 1:close])
            return self.add('declaration', 'declare %s(%s)' % ((owner + '::' if owner else '') + qualified, params), start, end,
                            name=name_tok.value, code=code)
        names = _declarator_names(toks)
        if not names:
            self.fail(first, 'unclassifiable declaration')
        return self.add('global', 'global ' + ','.join(names), start, end, name=names[0], code=code,
                        idents=[t.value for t in toks if t.kind == 'id'])

    def function_unit(self, i, j, close, *, qualifier, kind='function'):
        header = self.toks[i:j]
        open_at = _index_depth0(header, '(')
        name_at = open_at - 1
        if name_at < 0:
            self.fail(header[0], 'a body without a function name')
        name_tok = header[name_at]
        if header[name_at].kind != 'id':
            # operator overloads: operator== etc.
            k = name_at
            while k >= 0 and header[k].value != 'operator':
                k -= 1
            if k < 0:
                self.fail(name_tok, 'unclassifiable function header')
            name_at = k
        simple = header[name_at].value if header[name_at].value != 'operator' else _collapse(header[name_at:open_at])
        if simple in _CONTROL:
            self.fail(name_tok, 'a control statement at top level')
        for tok in header:
            if tok.kind == 'id' and tok.value in self.function_macros:
                self.fail(tok, 'function-like macro %s in a function header' % tok.value)
        close_p = _match(header, open_at)
        if close_p is None:
            self.fail(header[open_at], 'unbalanced parentheses in a function header')
        tail = header[close_p + 1:]
        if tail and not (all(t.value in _AFTER_PARAMS for t in tail) or _is_initializer_list(tail)):
            self.fail(tail[0], 'unclassifiable tokens between a parameter list and its body (a macro?)')
        qualified = _qualified(header, name_at) if header[name_at].value != 'operator' else simple
        if qualifier is None and '::' not in qualified and name_at == 0:
            self.fail(name_tok, 'a top-level body with no return type before %s (a macro?)' % simple)
        if name_at > 0 and header[name_at - 1].value == '~':
            qualified = qualified.replace(simple, '~' + simple, 1) if '::' not in qualified else qualified.rsplit('::', 1)[0] + '::~' + simple
        params = header[open_at + 1:close_p]
        full = (qualifier + '::' if qualifier else '') + qualified
        start, end = header[0].start, self.toks[close].end
        body = self.toks[j:close + 1]
        unit = self.add(kind, '%s %s(%s)' % (kind, full, _sig(params)), start, end, name=simple.lstrip('~'),
                        code=_collapse(self.toks[i:close + 1]), idents=[t.value for t in body if t.kind == 'id'],
                        extra=dict(qualified=full, types=_param_types(params), inner=qualifier is not None))
        return unit

    def type_unit(self, i, j, close, end, word):
        header = self.toks[i:j]
        names = [t.value for t in header if t.kind == 'id' and t.value not in TYPE_KEYWORDS + ('template', 'typename', 'public', 'private', 'protected', 'virtual')]
        name = names[0] if names else None
        if word == 'enum':
            label = name or ('{' + ','.join(t.value for t in self.toks[j + 1:close] if t.kind == 'id')[:80] + '}')
            return self.add('type', 'enum ' + label, header[0].start, self.toks[end].end, name=name, code=_collapse(self.toks[i:end + 1]))
        if not name:
            self.fail(header[0], 'an anonymous %s' % word)
        # members: inline method bodies become their own units; everything else stays in the shell
        pieces, cursor, k, member_cond = [], self.toks[i].start, j + 1, []
        saved_cond = list(self.cond)
        methods = []
        while k < close:
            tok = self.toks[k]
            if tok.kind == 'pp':
                w, _ = _directive_word(tok.value)
                if w in ('if', 'ifdef', 'ifndef'):
                    member_cond.append(tok.value)
                elif w in ('elif', 'else'):
                    member_cond[-1] = member_cond[-1].split(' / ')[0] + ' / ' + tok.value
                elif w == 'endif':
                    member_cond.pop()
                k += 1
                continue
            if tok.kind == 'id' and tok.value in ('public', 'private', 'protected') and k + 1 < close and self.toks[k + 1].value == ':':
                k += 2
                continue
            kind, m = self._scan(k, close, top=False)
            if kind == 'decl':
                k = m + 1
                continue
            mheader = self.toks[k:m]
            mclose = self.body_end(m)
            if _type_keyword(mheader) or not _at_depth0(mheader, '('):
                # a nested type: stays in the shell (its methods too)
                k = mclose + 1
                continue
            self.cond = saved_cond + member_cond
            unit = self.function_unit(k, m, mclose, qualifier=name, kind='method')
            methods.append(unit)
            pieces.append(self.src.text[cursor:unit['start']])
            pieces.append('<%s>' % unit['key'])
            cursor = unit['end']
            k = mclose + 1
            if k < close and self.toks[k].value == ';':
                k += 1
        self.cond = saved_cond
        pieces.append(self.src.text[cursor:self.toks[end].end])
        shell = ''.join(pieces)
        unit = self.add('type', '%s %s' % (word, name), header[0].start, self.toks[end].end, name=name, text=shell,
                        code=_collapse(self.toks[i:end + 1]), extra=dict(methods=[m['key'] for m in methods]))
        # the type unit comes before its methods in file order
        self.units.remove(unit)
        self.units.insert(len(self.units) - len(methods), unit)
        return unit

    def parse(self):
        i = 0
        while i < len(self.toks):
            if self.toks[i].kind == 'pp':
                i = self.directive(i)
            else:
                i = self.top(i)
        if self.cond:
            self.fail(None, 'an unclosed top-level conditional (%s)' % self.cond[-1])
        return self.units


def _at_depth0(toks, value):
    return _index_depth0(toks, value) is not None


def _index_depth0(toks, value):
    depth = 0
    for k, tok in enumerate(toks):
        v = tok.value if tok.kind == 'punct' else None
        if v == value and depth == 0:
            return k
        if v in ('(', '[', '{'):
            depth += 1
        elif v in (')', ']', '}'):
            depth -= 1
    return None


def _match(toks, k):
    depth = 0
    for m in range(k, len(toks)):
        v = toks[m].value if toks[m].kind == 'punct' else None
        if v in ('(', '['):
            depth += 1
        elif v in (')', ']'):
            depth -= 1
            if depth == 0:
                return m
    return None


def _qualified(toks, name_at):
    parts, k = [toks[name_at].value], name_at
    while k >= 2 and toks[k - 1].value == '::' and toks[k - 2].kind == 'id':
        parts.insert(0, toks[k - 2].value)
        k -= 2
    return '::'.join(parts)


def _is_initializer_list(tail):
    if not tail or tail[0].value != ':':
        return False
    k = 1
    while k < len(tail):
        if tail[k].kind != 'id':
            return False
        while k + 1 < len(tail) and tail[k + 1].value == '::':
            k += 2
        if k + 1 >= len(tail) or tail[k + 1].value != '(':
            return False
        close = _match(tail, k + 1)
        if close is None:
            return False
        k = close + 1
        if k < len(tail):
            if tail[k].value != ',':
                return False
            k += 1
    return True


def _type_keyword(header):
    k = 0
    if header and header[0].value == 'template':
        depth = 0
        for k, tok in enumerate(header):
            if tok.value == '<':
                depth += 1
            elif tok.value == '>':
                depth -= 1
                if depth == 0:
                    k += 1
                    break
    return header[k].value if k < len(header) and header[k].value in TYPE_KEYWORDS else None


def _split_depth0(toks, sep=','):
    parts, current, depth = [], [], 0
    for tok in toks:
        v = tok.value if tok.kind == 'punct' else None
        if v in ('(', '[', '{'):
            depth += 1
        elif v in (')', ']', '}'):
            depth -= 1
        if v == sep and depth == 0:
            parts.append(current)
            current = []
        else:
            current.append(tok)
    parts.append(current)
    return parts


def _declarator_names(toks):
    names = []
    for index, part in enumerate(_split_depth0(toks)):
        cut = _index_depth0(part, '=')
        part = part[:cut] if cut is not None else part
        bracket = _index_depth0(part, '[')
        part = part[:bracket] if bracket is not None else part
        ids = [t.value for t in part if t.kind == 'id']
        if not ids:
            return []
        names.append(ids[-1] if index == 0 else ids[0] if len(ids) == 1 else ids[-1])
    return names


def _param_types(params):
    types = []
    for part in _split_depth0(params):
        cut = _index_depth0(part, '=')
        part = part[:cut] if cut is not None else part
        ids = [k for k, t in enumerate(part) if t.kind == 'id']
        if len(ids) > 1:
            part = part[:ids[-1]] + part[ids[-1] + 1:]
        types.append(_collapse(part))
    return types


def _add_gaps(src, units):
    """The text between units as gap units keyed by the next unit: comments, whitespace and stray ';'."""
    ordered = sorted(units, key=lambda u: u['start'])
    gaps, cursor = [], 0

    def gap_unit(key, start, end, segment):
        text = src.text[start:end]
        code = _collapse(lex(Text(text, src.file)))
        return dict(key=key, kind='gap', name=None, start=start, end=end, line=src.line(start), end_line=src.line(end),
                    sha256=_sha(text), code_sha256=_sha(code), segment=segment, idents=[], text=text)

    for unit in ordered:
        if unit.get('inner'):
            continue   # an inline method inside its class shell
        if unit['start'] > cursor:
            gaps.append(gap_unit('gap before ' + unit['key'], cursor, unit['start'], unit['segment']))
        cursor = max(cursor, unit['end'])
    if cursor < len(src.text):
        gaps.append(gap_unit('gap at end', cursor, len(src.text), None))
    return gaps


def parse_units(text, file='<text>', *, strict=True, function_macros=frozenset(), gaps=True):
    """Top-level units of one MQL5 source text (already normalized). Raises UnitParseError when unsure."""
    src = Text(text, file)
    parser = _Parser(src, strict=strict, function_macros=function_macros)
    units = parser.parse()
    seen, signatures = {}, {}
    for unit in units:
        if unit['key'] in seen:
            src.fail(unit['start'], 'duplicate unit %s (also at line %d)' % (unit['key'], seen[unit['key']]['line']))
        seen[unit['key']] = unit
        if unit['kind'] in ('function', 'method'):
            prefix = unit['key'].split('function ' if unit['kind'] == 'function' else 'method ', 1)[0]
            sig = (prefix, unit['qualified'], tuple(unit['types']))
            if sig in signatures:
                src.fail(unit['start'], 'ambiguous signature: %s and %s have the same name and parameter types'
                         % (unit['key'], signatures[sig]['key']))
            signatures[sig] = unit
    if gaps:
        units = units + _add_gaps(src, units)
        # Every character belongs to exactly one top-level unit or gap, and methods sit inside their class.
        cursor = 0
        for unit in sorted((u for u in units if not u.get('inner')), key=lambda u: u['start']):
            if unit['start'] != cursor:
                src.fail(unit['start'], 'units do not tile the file (parser uncertainty near %s)' % unit['key'])
            cursor = unit['end']
        if cursor != len(text):
            src.fail(cursor, 'units do not cover the end of the file')
    return dict(file=file, units=units, macros=parser.macros, function_macros=sorted(parser.function_macros))


# ---- call graph ----------------------------------------------------------------------------
def call_graph(texts, *, strict_files=()):
    """A conservative name-level call graph over every closure text file.

    ``texts``: {file: normalized text}. A function's edges go to every function or method whose
    simple name appears anywhere in its body (or in a macro it uses), so overloads, methods of
    any class and virtual overrides are all included. A file that does not parse makes
    reachability ``uncertain``.
    """
    nodes, by_name, macros, opaque = {}, {}, {}, []
    parsed = {}
    function_macros = set()
    for file, text in texts.items():
        try:
            parsed[file] = parse_units(text, file, strict=file in strict_files, gaps=False)
        except UnitParseError as exc:
            opaque.append(dict(file=file, reason=str(exc)))
            continue
        macros.update(parsed[file]['macros'])
        function_macros.update(parsed[file]['function_macros'])
    for file, result in parsed.items():
        for unit in result['units']:
            if unit['kind'] in ('function', 'method'):
                node = (file, unit['key'])
                nodes[node] = unit
                by_name.setdefault(unit['name'], []).append(node)

    def expand(names):
        out, stack = set(), list(names)
        while stack:
            name = stack.pop()
            if name in out:
                continue
            out.add(name)
            stack.extend(macros.get(name, ()))
        return out

    edges = {node: sorted({target for name in expand(unit['idents']) for target in by_name.get(name, ()) if target != node})
             for node, unit in nodes.items()}
    roots = {}
    for node, unit in nodes.items():
        if unit['kind'] == 'function' and '::' not in unit.get('qualified', '') and unit['name'] in TRADING_ROOTS + LIFECYCLE_ROOTS:
            roots.setdefault(unit['name'], []).append(node)
    reach = {}
    for root, starts in roots.items():
        seen, stack = set(), list(starts)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(edges.get(node, ()))
        for node in seen:
            reach.setdefault(node, set()).add(root)
    return dict(reach={node: sorted(r) for node, r in reach.items()}, opaque=opaque, nodes=len(nodes),
                roots=sorted(roots), edges=sum(len(e) for e in edges.values()))


def reachability(graph, file, key):
    """(trading roots, lifecycle roots, certain) for one unit."""
    roots = graph['reach'].get((file, key), []) if graph else []
    return ([r for r in roots if r in TRADING_ROOTS], [r for r in roots if r in LIFECYCLE_ROOTS], not (graph or {}).get('opaque'))


# ---- function allowlist --------------------------------------------------------------------
def load_function_allowlist(path=None):
    record = json.loads(Path(path or FUNCTION_ALLOWLIST_PATH).read_text(encoding='utf-8'))
    if record.get('schema') != ALLOWLIST_SCHEMA or not isinstance(record.get('units'), dict):
        raise ValueError('Not a non-trading function allowlist receipt')
    for file, units in record['units'].items():
        if not isinstance(units, dict):
            raise ValueError('Function allowlist file %s must map unit keys to entries' % file)
        for key, entry in units.items():
            if not isinstance(entry, dict) or not entry.get('category') or not entry.get('reason') \
                    or not isinstance(entry.get('reviewed_sha256'), dict) or not entry['reviewed_sha256']:
                raise ValueError('Function allowlist entry %s / %s needs a category, a reason and reviewed_sha256 versions' % (file, key))
            if any(not re.fullmatch('[0-9a-f]{64}', h) for h in entry['reviewed_sha256']):
                raise ValueError('Function allowlist entry %s / %s has a malformed hash' % (file, key))
    return record


def function_entry(allowlist, file, key):
    for path, units in (allowlist or {}).get('units', {}).items():
        if path.lower() == file.replace('\\', '/').lower() and key in units:
            return dict(units[key], path=path)
    return None


def allowlist_summary(allowlist):
    from studio_equivalence import digest_of
    return dict(id=allowlist.get('id'), sha256=digest_of(allowlist), confirmed=allowlist.get('confirmed') is True,
                review_ref=allowlist.get('review_ref'), entries=sum(len(u) for u in allowlist.get('units', {}).values()))


# ---- comparison ----------------------------------------------------------------------------
def _segments(units):
    return {u['key']: u['segment'] for u in units if u['kind'] not in ('gap', 'method', 'directive')}


def _ordered(units, kinds):
    return [u['key'] for u in sorted(units, key=lambda u: u['start']) if u['kind'] in kinds]


def _common_order(a, b):
    common = set(a) & set(b)
    return [k for k in a if k in common], [k for k in b if k in common]


def compare_texts(file, old_text, new_text, *, allowlist=None, old_graph=None, new_graph=None):
    """Unit-by-unit comparison of one file between two builds (texts already normalized).

    Returns the differing units, which of them block and why, and ``equivalent``. Raises
    UnitParseError when either side cannot be split with certainty."""
    from studio_equivalence import GUARD, _changed_lines, _guard_hits   # noqa: F401 (shared rules)
    old = parse_units(old_text, file + ' (export build)')
    new = parse_units(new_text, file + ' (installed build)')
    old_by, new_by = {u['key']: u for u in old['units']}, {u['key']: u for u in new['units']}
    confirmed = (allowlist or {}).get('confirmed') is True
    line_macros = any(re.search(r'\b__(LINE|COUNTER)__\b', t) for t in (old_text, new_text))
    differing, blocking = [], []
    for key in sorted(set(old_by) | set(new_by), key=lambda k: ((old_by.get(k) or new_by.get(k))['start'], k)):
        a, b = old_by.get(key), new_by.get(key)
        if a and b and a['sha256'] == b['sha256']:
            continue
        unit = a or b
        change = 'changed' if a and b else ('removed' if a else 'added')
        item = dict(unit=key, kind=unit['kind'], change=change, export_sha256=a and a['sha256'], installed_sha256=b and b['sha256'],
                    export_lines=a and [a['line'], a['end_line']], installed_lines=b and [b['line'], b['end_line']],
                    code_equal=bool(a and b and a['code_sha256'] == b['code_sha256']))
        lines = _changed_lines(a['text'] if a else '', b['text'] if b else '')
        item.update(changed_lines=len(lines), added=sum(l.startswith('+') for l in lines), removed=sum(l.startswith('-') for l in lines))
        hits = _guard_hits(lines)
        if hits:
            item['guard_hits'] = hits[:20]
        if unit['kind'] in ('function', 'method'):
            trading_old, life_old, certain_old = reachability(old_graph, file, key) if a else ([], [], True)
            trading_new, life_new, certain_new = reachability(new_graph, file, key) if b else ([], [], True)
            item['reachable_from_trading'] = sorted(set(trading_old) | set(trading_new))
            item['reachable_from_lifecycle'] = sorted(set(life_old) | set(life_new))
            item['reachability_certain'] = bool(old_graph and new_graph) and certain_old and certain_new
            item['trading_entry_point'] = unit['name'] in TRADING_ROOTS and '::' not in unit.get('qualified', '')
        entry = function_entry(allowlist, file, key)
        item['allowlisted'] = entry and entry['category']
        unreviewed = [h for h in (item['export_sha256'], item['installed_sha256']) if h and entry and h not in entry['reviewed_sha256']]
        on_path = unit['kind'] in ('function', 'method') and (item['reachable_from_trading'] or item['trading_entry_point']
                                                              or not item['reachability_certain'])
        if unit['kind'] == 'gap':
            # Between units there are only comments, whitespace and stray ';' (the tiling check proves it).
            # Comments and whitespace cannot change compiled code; any other token difference blocks.
            gap_codes = {(a or {}).get('code_sha256', _EMPTY), (b or {}).get('code_sha256', _EMPTY)}
            item['comment_or_whitespace_only'] = gap_codes == {_EMPTY} or (a is not None and b is not None and len(gap_codes) == 1)
            if not item['comment_or_whitespace_only']:
                item['blocking'] = 'code between units changed'
            elif line_macros:
                item['blocking'] = 'the file uses __LINE__/__COUNTER__, so even a comment or blank line between units can change code'
        elif unit['kind'] in NEVER_ALLOWLISTED:
            item['blocking'] = '%s unit changed (never allowlistable)' % unit['kind']
        elif unit['kind'] in ('global', 'declaration') and change == 'changed':
            item['blocking'] = 'a changed global, default or declaration (never allowlistable)'
        elif not entry:
            item['blocking'] = 'not on the non-trading function allowlist'
        elif unreviewed:
            item['blocking'] = 'allowlisted unit, but version %s is not in the reviewed receipt' % ', '.join(h[:12] for h in unreviewed)
        elif hits:
            item['blocking'] = 'allowlisted, but a changed line touches trading, signal, #define or input code'
        elif on_path and entry.get('trading_path_reviewed') is not True:
            item['blocking'] = ('allowlisted, but the call graph %s it from %s; the entry must say trading_path_reviewed'
                                % ('reaches' if item.get('reachability_certain') else 'cannot rule out reaching',
                                   ', '.join(item.get('reachable_from_trading') or ['a trading entry point'])))
        elif not confirmed:
            item['blocking'] = 'allowlisted, but the function allowlist receipt is not confirmed yet (needs Claude-Mac)'
        differing.append(item)
        if item.get('blocking'):
            blocking.append(key)
    layout = []
    if _ordered(old['units'], ('directive',)) != _ordered(new['units'], ('directive',)):
        layout.append('the sequence of preprocessor lines changed')
    a_order, b_order = _common_order(_ordered(old['units'], ('global', 'input', 'declaration', 'type')),
                                     _ordered(new['units'], ('global', 'input', 'declaration', 'type')))
    if a_order != b_order:
        first = next(i for i, (x, y) in enumerate(zip(a_order, b_order)) if x != y)
        layout.append('top-level declaration order changed (first at %s / %s)' % (a_order[first], b_order[first]))
    old_seg, new_seg = _segments(old['units']), _segments(new['units'])
    moved = sorted(k for k in set(old_seg) & set(new_seg) if old_seg[k] != new_seg[k])
    if moved and not layout:
        layout.append('%d units moved across a preprocessor line (%s)' % (len(moved), ', '.join(moved[:5])))
    counts = {}
    for item in differing:
        counts[item['change']] = counts.get(item['change'], 0) + 1
    return dict(schema=SCHEMA, file=file, export_units=len(old['units']), installed_units=len(new['units']), differing=differing,
                blocking=blocking, layout=layout, counts=counts, equivalent=not blocking and not layout)


def closure_texts(source, tree):
    """{file: normalized text} for every text file in a certificate closure."""
    from studio_equivalence import TEXT_SUFFIXES, decode, normalize
    return {rel: normalize(decode(source.read(rel))) for rel in tree['order'] if rel.lower().endswith(TEXT_SUFFIXES)}


def function_level_files(main):
    return (main, OPTIMIZER)


def stub(file, item):
    """A receipt entry skeleton for a reviewer: hashes filled in, category and reason left to the review."""
    return {file: {item['unit']: dict(category='<panel_ui|report|studio_control|telemetry|comment>', reason='<evidence>',
                                      trading_path_reviewed=bool(item.get('reachable_from_trading') or item.get('trading_entry_point')),
                                      reviewed_sha256={h: ['<build>'] for h in (item['export_sha256'], item['installed_sha256']) if h})}}


def unit_diff(file, old_text, new_text, key, *, context=2, limit=80):
    """The unified diff of one unit between two texts (for the review printout)."""
    old = {u['key']: u for u in parse_units(old_text, file)['units']}
    new = {u['key']: u for u in parse_units(new_text, file)['units']}
    a, b = old.get(key), new.get(key)
    lines = list(difflib.unified_diff((a['text'] if a else '').split('\n'), (b['text'] if b else '').split('\n'),
                                      'export', 'installed', lineterm='', n=context))
    return lines[:limit] + (['... (%d more lines)' % (len(lines) - limit)] if len(lines) > limit else [])


# ---- CLI -----------------------------------------------------------------------------------
def units_diff(repo, export_commit, installed_commit, *, main=None, files=None, allowlist=None, with_diff=True):
    """Differing units of the function-level files between two git commits, with reachability and stubs."""
    import studio_equivalence as eq
    main = main or eq.DEFAULT_MAIN
    old_source, new_source = eq.GitSource(repo, export_commit), eq.GitSource(repo, installed_commit)
    old_tree, new_tree = eq.closure(old_source, main), eq.closure(new_source, main)
    old_texts, new_texts = closure_texts(old_source, old_tree), closure_texts(new_source, new_tree)
    strict = function_level_files(main)
    old_graph, new_graph = call_graph(old_texts, strict_files=strict), call_graph(new_texts, strict_files=strict)
    allowlist = allowlist if allowlist is not None else load_function_allowlist()
    report = dict(schema=SCHEMA, export=old_source.commit, installed=new_source.commit, files=[],
                  graph=dict(export=dict(nodes=old_graph['nodes'], edges=old_graph['edges'], opaque=old_graph['opaque']),
                             installed=dict(nodes=new_graph['nodes'], edges=new_graph['edges'], opaque=new_graph['opaque'])))
    for file in files or strict:
        name = old_source.names().get(file.lower()) or file
        if name not in old_texts or name not in new_texts:
            report['files'].append(dict(file=file, problem='not in both closures'))
            continue
        if old_texts[name] == new_texts[name]:
            report['files'].append(dict(file=name, identical=True))
            continue
        try:
            result = compare_texts(name, old_texts[name], new_texts[name], allowlist=allowlist, old_graph=old_graph, new_graph=new_graph)
        except UnitParseError as exc:
            report['files'].append(dict(file=name, problem='not_comparable: ' + str(exc)))
            continue
        for item in result['differing']:
            item['stub'] = stub(name, item)
            if with_diff:
                item['diff'] = unit_diff(name, old_texts[name], new_texts[name], item['unit'])
        report['files'].append(result)
    return report


def _print_report(report):
    print('export %s -> installed %s' % (report['export'][:12], report['installed'][:12]))
    for side in ('export', 'installed'):
        graph = report['graph'][side]
        print('  call graph (%s): %d functions, %d edges, %d unparsed files %s' % (
            side, graph['nodes'], graph['edges'], len(graph['opaque']), [o['file'] for o in graph['opaque']]))
    for result in report['files']:
        if result.get('identical') or result.get('problem'):
            print('%s: %s' % (result['file'], 'identical' if result.get('identical') else result['problem']))
            continue
        never = sum(1 for d in result['differing'] if d['kind'] in NEVER_ALLOWLISTED or
                    (d['kind'] in ('global', 'declaration') and d['change'] == 'changed'))
        print('\n%s: %d differing units (%s), %d blocking, %d never allowlistable; layout: %s' % (
            result['file'], len(result['differing']), result['counts'], len(result['blocking']), never, result['layout'] or 'same'))
        for item in result['differing']:
            reach = item.get('reachable_from_trading')
            print('  - [%s] %s (%s lines +%s/-%s%s%s)\n      %s' % (
                item['change'], item['unit'], item['changed_lines'], item['added'], item['removed'],
                ', code equal' if item['code_equal'] else '', ', trading roots ' + ','.join(reach) if reach else '',
                item.get('blocking') or 'clear'))


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Function-level unit diff and build externals manifest (research tooling, no MT5 effect).')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('units-diff', help='print the differing units of the entrypoint and Optimizer.mqh between two commits')
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--export-commit', required=True)
    p.add_argument('--installed-commit', required=True)
    p.add_argument('--main')
    p.add_argument('--file', action='append')
    p.add_argument('--allowlist', type=Path)
    p.add_argument('--json', type=Path, help='write the full report (with per-unit diffs and receipt stubs) here')
    p = sub.add_parser('externals-manifest', help='fingerprint the externals a candidate compile actually used')
    p.add_argument('--mql5-root', type=Path, required=True)
    p.add_argument('--compile-log', type=Path, required=True)
    p.add_argument('--stage', type=Path, required=True, help='the staged EA source folder that was compiled')
    p.add_argument('--log-stage', help='the stage path as the compile log names it, when the stage was moved since')
    p.add_argument('--log-mql5-root', help='the MQL5 root as the compile log names it, when it differs')
    p.add_argument('--compiler', type=Path)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--identity', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--main')
    p.add_argument('--repo', type=Path, help='GOAT-EA checkout: staged files the identity does not list are checked against the compile commit')
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'units-diff':
        allowlist = load_function_allowlist(args.allowlist) if args.allowlist else None
        report = units_diff(args.repo, args.export_commit, args.installed_commit, main=args.main, files=args.file, allowlist=allowlist)
        _print_report(report)
        if args.json:
            args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
        return 0
    import studio_equivalence as eq
    manifest = eq.externals_manifest(args.mql5_root, args.compile_log, args.stage, binary=args.binary, identity=args.identity,
                                     receipt=args.receipt, compiler=args.compiler, main=args.main or eq.DEFAULT_MAIN,
                                     log_stage=args.log_stage, log_mql5_root=args.log_mql5_root, repo=args.repo)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    print(json.dumps(dict(output=str(args.output), problems=manifest['problems'], consumed=len(manifest['consumed']),
                          externals=manifest['externals_sha256']), indent=1))
    sys.stdout.flush()
    return 0 if not manifest['problems'] else 1


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
