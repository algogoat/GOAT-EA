"""One classifier for a retained native-gate request.json (goatai#1885), and a guard that keeps it so.

settled_native_request() is the only way controller code may treat a leftover request.json as
settled: issued-<request_id> binds sha256(request.json), consumed-<request_id> is byte-identical
and result-<request_id> names that same hash, for the caller's terminal/run binding, with no
permit. The shared fixtures here write the Terminal 3 shape and every pending/mismatch variant
for each site's own tests; the guard fails if any controller code refuses on the mere presence
of request.json without consulting the helper.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import unittest

from studio_native_gate import settled_native_request


CONTROLLER = Path(__file__).resolve().parent
HELPER = 'settled_native_request'
REQUEST = 'request.json'

# Every pending or mismatched shape a site must still refuse. The permit variant is last because
# fixtures never delete gate files: once written, the permit stays for the rest of a test.
PENDING_VARIANTS = ('not-consumed', 'consumed-without-result', 'other-binding', 'different-consumed-bytes',
                    'other-request-id', 'result-other-hash', 'permit-present')


def retain_request(gate, terminal_id, run_id, seed='pilot-2-r3', *, action='arm_restart', consumed=True, result=True,
                   permit=False, status='RESTART_ARMED_RECONCILE'):
    """The Terminal 3 shape: request.json kept after the EA consumed and answered it.

    request_id is the attempt identity carried in the request, not a hash of its bytes; the
    receipts bind sha256(request.json) as request_sha256, and consumed-<request_id> is the EA's
    byte-identical claim copy. Returns (request_id, request.json bytes).
    """
    gate = Path(gate); gate.mkdir(parents=True, exist_ok=True)
    request_id = hashlib.sha256(seed.encode()).hexdigest()
    request = dict(action=action, schema_version=1, request_id=request_id, terminal_id=terminal_id, run_id=run_id,
                   owner='agent', revision=7, generation=3, job_id=seed, configuration_sha256='c' * 64,
                   expires_utc=int(time.time()) - 4 * 3600)
    raw = (json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n').encode()
    digest = hashlib.sha256(raw).hexdigest()
    (gate / ('issued-' + request_id + '.json')).write_bytes(json.dumps(dict(request_sha256=digest, request=request)).encode())
    (gate / 'request.json').write_bytes(raw)
    if consumed:
        (gate / ('consumed-' + request_id + '.json')).write_bytes(raw)
    if result:
        (gate / ('result-' + request_id + '.json')).write_bytes(json.dumps(dict(
            request_id=request_id, request_sha256=digest, status=status, observed_utc='2026.10.03 21:58:06')).encode())
    if permit:
        (gate / 'permit.json').write_bytes(json.dumps(dict(request_sha256=digest)).encode())
    return request_id, raw


def retain_pending_variant(name, gate, terminal_id, run_id, *, action='arm_restart'):
    """Write one PENDING_VARIANTS shape under its own request id; returns the request.json bytes."""
    gate = Path(gate); seed = 'pending-' + name
    if name == 'not-consumed':                  # issued, never claimed by the EA
        return retain_request(gate, terminal_id, run_id, seed, action=action, consumed=False, result=False)[1]
    if name == 'consumed-without-result':       # claimed, the EA's handler has not returned
        return retain_request(gate, terminal_id, run_id, seed, action=action, result=False)[1]
    if name == 'other-binding':                 # another session's request on this gate
        return retain_request(gate, 'terminal-other', 'session-other', seed, action=action)[1]
    if name == 'permit-present':                # a permit always refuses
        return retain_request(gate, terminal_id, run_id, seed, action=action, permit=True)[1]
    if name == 'different-consumed-bytes':      # the consumed copy is not byte-identical
        request_id, raw = retain_request(gate, terminal_id, run_id, seed, action=action)
        (gate / ('consumed-' + request_id + '.json')).write_bytes(raw.replace(b'"revision": 7', b'"revision": 8'))
        return raw
    if name == 'other-request-id':              # identical bytes, but claimed under another request id
        request_id, raw = retain_request(gate, terminal_id, run_id, seed, action=action, consumed=False)
        (gate / ('consumed-' + hashlib.sha256(('another-' + seed).encode()).hexdigest() + '.json')).write_bytes(raw)
        return raw
    if name == 'result-other-hash':             # the result answers another request hash
        request_id, raw = retain_request(gate, terminal_id, run_id, seed, action=action)
        (gate / ('result-' + request_id + '.json')).write_bytes(json.dumps(dict(
            request_id=request_id, request_sha256='e' * 64, status='RESTART_ARMED_RECONCILE')).encode())
        return raw
    raise AssertionError('unknown variant ' + name)


def gate_files(gate):
    return {path.name: path.read_bytes() for path in Path(gate).iterdir() if path.is_file() and path.name != 'launch.lock'}


class SettledNativeRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.gate = Path(temporary.name) / 'native-gate'
        self.session = dict(terminal_id='terminal-3', run_id='session-3')

    def test_the_terminal_3_shape_is_settled_and_left_untouched(self):
        request_id, raw = retain_request(self.gate, 'terminal-3', 'session-3')
        before = gate_files(self.gate)
        self.assertEqual(settled_native_request(self.gate, self.session), dict(
            request_id=request_id, request_sha256=hashlib.sha256(raw).hexdigest(), action='arm_restart',
            result='RESTART_ARMED_RECONCILE'))
        self.assertEqual(settled_native_request(str(self.gate), self.session)['request_id'], request_id)
        self.assertEqual(gate_files(self.gate), before, 'read-only: nothing is deleted or rewritten')

    def test_every_pending_or_mismatched_variant_is_not_settled(self):
        for name in PENDING_VARIANTS:
            with self.subTest(name):
                raw = retain_pending_variant(name, self.gate, 'terminal-3', 'session-3')
                before = gate_files(self.gate)
                if name == 'permit-present':
                    # The helper classifies request.json only; every caller refuses for permit.json itself.
                    self.assertTrue((self.gate / 'permit.json').exists())
                else:
                    self.assertIsNone(settled_native_request(self.gate, self.session))
                self.assertEqual((self.gate / 'request.json').read_bytes(), raw)
                self.assertEqual(gate_files(self.gate), before)

    def test_missing_unreadable_or_foreign_requests_are_not_settled(self):
        self.assertIsNone(settled_native_request(self.gate, self.session))
        self.gate.mkdir(parents=True)
        for body in (b'{}', b'not json', json.dumps(dict(request_id='f' * 64)).encode(),
                     json.dumps(dict(request_id='short', terminal_id='terminal-3', run_id='session-3')).encode()):
            with self.subTest(body=body[:20]):
                (self.gate / 'request.json').write_bytes(body)
                self.assertIsNone(settled_native_request(self.gate, self.session))


# ---------------------------------------------------------------------------------------------
# Guard: no controller code may refuse on the mere presence of native-gate request.json.
#
# A refusal is an `if` whose body raises (or calls _refuse...), an assert, or require(cond, ...).
# It is a bare presence refusal when its test is true because a path that can name request.json
# exists, nothing in the test reads or compares that request, and the test does not consult the
# helper. Paths are resolved structurally (gate / 'request.json', gate / name for a loop over
# names, safe_path(...), bound names at their latest preceding assignment).

EXISTENCE = {'exists', 'is_file', 'is_symlink', 'lexists'}
PATH_WRAPPERS = {'safe_path', 'safe', '_path', 'Path', 'PurePath', 'PureWindowsPath', 'str'}
REFUSAL_CALL = re.compile(r'_?refuse\w*')
DEMANDS = {'require', '_require'}
# The only places that may classify a retained request.json: each calls the one helper.
HELPER_CALL_SITES = {
    ('studio_agent_setup.py', 'close_terminal.refuse_pending_native'),
    ('studio_same_ea_rebind.py', 'rebind'),
    ('studio_never_started_retirement.py', '_verify'),
    ('studio_bootstrap_retirement.py', 'state_view'),
    ('studio_unissued_start.py', 'native_absence'),
}
_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_DEPTH = 8


class _Scope:
    """Name bindings of one function; closures see the enclosing scopes."""

    def __init__(self, parent=None):
        self.parent, self.names = parent, {}

    def bind(self, name, value, line):
        self.names.setdefault(name, []).append((line, value))

    def lookup(self, name, line):
        """The binding(s) at the latest assignment before `line` (all of them if none precede it)."""
        scope = self
        while scope is not None:
            if name in scope.names:
                bindings = scope.names[name]
                before = [item for item in bindings if item[0] <= line]
                if not before:
                    return [value for _, value in bindings]
                last = max(item[0] for item in before)
                return [value for item_line, value in before if item_line == last]
            scope = scope.parent
        return []


def _literals(node):
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
        return frozenset(item.value for item in node.elts)
    return None


def _bind_target(scope, target, value, line):
    if isinstance(target, ast.Name):
        scope.bind(target.id, value, line)
    elif isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            for item, part in zip(target.elts, value.elts):
                _bind_target(scope, item, part, line)
        else:
            for item in target.elts:
                _bind_target(scope, item, value, line)
    elif isinstance(target, ast.Starred):
        _bind_target(scope, target.value, value, line)


def _bind_iteration(scope, target, iterable, line):
    literal = _literals(iterable)
    _bind_target(scope, target, literal if literal is not None else iterable, line)


def _own_nodes(function):
    """Nodes of this function (or module) body, excluding nested function/class bodies."""
    pending = [node for node in function.body if not isinstance(node, _NESTED)]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, _NESTED))


def _nested_functions(function):
    """(definition, relative qualified name) for functions defined directly in this scope."""
    pending = [(node, '') for node in function.body]
    while pending:
        node, prefix = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, prefix + node.name
        elif isinstance(node, ast.ClassDef):
            pending.extend((item, prefix + node.name + '.') for item in node.body)
        elif not isinstance(node, ast.Lambda):
            pending.extend((child, prefix) for child in ast.iter_child_nodes(node))


def _collect(scope, function):
    for node in _own_nodes(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _bind_target(scope, target, node.value, node.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            _bind_target(scope, node.target, node.value, node.lineno)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _bind_iteration(scope, node.target, node.iter, node.lineno)
        elif isinstance(node, ast.comprehension):
            _bind_iteration(scope, node.target, node.iter, node.target.lineno)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    _bind_target(scope, item.optional_vars, item.context_expr, node.lineno)


def _request_path(expr, scope, narrowed, depth=0):
    """Whether this path expression can name request.json."""
    if depth > _DEPTH:
        return False
    if isinstance(expr, ast.Constant):
        return expr.value == REQUEST
    if isinstance(expr, ast.Name):
        if expr.id in narrowed:
            return REQUEST in narrowed[expr.id]
        for value in scope.lookup(expr.id, expr.lineno):
            if isinstance(value, frozenset):
                if REQUEST in value:
                    return True
            elif value is not expr and _request_path(value, scope, narrowed, depth + 1):
                return True
        return False
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        return _request_path(expr.right, scope, narrowed, depth + 1)
    if isinstance(expr, ast.Subscript):
        return _request_path(expr.slice, scope, narrowed, depth + 1)
    if isinstance(expr, ast.IfExp):
        return any(_request_path(part, scope, narrowed, depth + 1) for part in (expr.body, expr.orelse))
    if isinstance(expr, ast.Call):
        func = expr.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
        if name in PATH_WRAPPERS and expr.args:
            return _request_path(expr.args[0], scope, narrowed, depth + 1)
        if isinstance(func, ast.Attribute) and name in ('resolve', 'absolute'):
            return _request_path(func.value, scope, narrowed, depth + 1)
        if isinstance(func, ast.Attribute) and name in ('joinpath', 'join', 'with_name') and expr.args:
            return _request_path(expr.args[-1], scope, narrowed, depth + 1)
    return False


def _reads_request(expr, scope, narrowed):
    """Whether a non-existence part of a test touches the request itself (bytes, JSON, digest)."""
    return any(isinstance(node, (ast.Name, ast.BinOp, ast.Subscript, ast.Call)) and _request_path(node, scope, narrowed)
               for node in ast.walk(expr))


def _involves_helper(expr, scope, depth=0):
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == HELPER) or (isinstance(func, ast.Attribute) and func.attr == HELPER):
                return True
        if isinstance(node, ast.Name) and depth < _DEPTH:
            if any(not isinstance(value, frozenset) and value is not expr and _involves_helper(value, scope, depth + 1)
                   for value in scope.lookup(node.id, node.lineno)):
                return True
    return False


def _narrowing(node):
    """`name == 'x.json'` or `name in (...)`: the loop variable takes only those values here."""
    if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and len(node.ops) == 1
            and len(node.comparators) == 1):
        op, right = node.ops[0], node.comparators[0]
        if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and isinstance(right.value, str):
            return node.left.id, frozenset([right.value])
        if isinstance(op, ast.In) and _literals(right) is not None:
            return node.left.id, _literals(right)
    return None


def _leaves(expr, scope, narrowed, positive=True, depth=0):
    """(kind, positive, node, scope, narrowed) for each boolean leaf of a test."""
    if isinstance(expr, ast.BoolOp):
        inner = dict(narrowed)
        if isinstance(expr.op, ast.And):
            for value in expr.values:
                narrow = _narrowing(value)
                if narrow:
                    inner[narrow[0]] = narrow[1]
        for value in expr.values:
            yield from _leaves(value, scope, inner, positive, depth)
    elif isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        yield from _leaves(expr.operand, scope, narrowed, not positive, depth)
    elif (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in ('any', 'all')
          and len(expr.args) == 1 and isinstance(expr.args[0], (ast.GeneratorExp, ast.ListComp))):
        inner = _Scope(scope)
        for generator in expr.args[0].generators:
            _bind_iteration(inner, generator.target, generator.iter, 0)
        yield from _leaves(expr.args[0].elt, inner, narrowed, positive, depth)
    elif isinstance(expr, ast.Name) and depth < _DEPTH and expr.id not in narrowed:
        values = scope.lookup(expr.id, expr.lineno)
        if not values or any(isinstance(value, frozenset) for value in values):
            yield ('other', positive, expr, scope, narrowed)
        for value in values:
            if not isinstance(value, frozenset):
                yield from _leaves(value, scope, narrowed, positive, depth + 1)
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr in EXISTENCE:
        os_path = isinstance(expr.func.value, ast.Attribute) and expr.func.value.attr == 'path'
        receiver = expr.args[0] if os_path and expr.args else expr.func.value
        yield ('exists', positive, receiver, scope, narrowed)
    elif _narrowing(expr):
        yield ('narrow', positive, expr, scope, narrowed)
    else:
        yield ('other', positive, expr, scope, narrowed)


def _enclosing_narrowing(node, parents):
    """Narrowing from enclosing `if name == 'permit.json' ...:` blocks around this node."""
    narrowed, child = {}, node
    while id(child) in parents:
        parent = parents[id(child)]
        if isinstance(parent, ast.If) and any(item is child for item in parent.body):
            clauses = parent.test.values if isinstance(parent.test, ast.BoolOp) and isinstance(parent.test.op, ast.And) else [parent.test]
            for clause in clauses:
                narrow = _narrowing(clause)
                if narrow:
                    narrowed.setdefault(*narrow)
        child = parent
    return narrowed


def _bare_request_refusal(test, scope, narrowed):
    """True when the test refuses because request.json merely exists, without the helper.

    A test that also reads or compares the request (bytes, JSON, digest) is a classifier, not
    a bare presence refusal; a negated existence (absence) check is not a refusal on presence.
    """
    if _involves_helper(test, scope):
        return False
    leaves = list(_leaves(test, scope, narrowed))
    present = any(kind == 'exists' and positive and _request_path(node, where, narrowed)
                  for kind, positive, node, where, narrowed in leaves)
    inspected = any(kind == 'other' and _reads_request(node, where, narrowed)
                    for kind, positive, node, where, narrowed in leaves)
    return present and not inspected


def _refuses(body):
    for statement in body:
        if isinstance(statement, ast.Raise):
            return True
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            func = statement.value.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
            if REFUSAL_CALL.fullmatch(name):
                return True
    return False


def bare_request_refusals(source, filename='<source>'):
    """[(line, qualified function)] for every refusal on request.json presence alone."""
    tree = ast.parse(source, filename)
    found = []

    def visit(function, parent, qualname):
        scope = _Scope(parent); _collect(scope, function)
        parents = {id(child): node for node in [function, *_own_nodes(function)]
                   for child in ast.iter_child_nodes(node) if not isinstance(child, _NESTED)}
        for node in _own_nodes(function):
            test = None
            if isinstance(node, ast.If) and _refuses(node.body):
                test = node.test
            elif isinstance(node, ast.Assert):
                test = ast.UnaryOp(op=ast.Not(), operand=node.test)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DEMANDS
                  and node.args):
                test = ast.UnaryOp(op=ast.Not(), operand=node.args[0])
            if test is not None and _bare_request_refusal(test, scope, _enclosing_narrowing(node, parents)):
                found.append((node.lineno, qualname or '<module>'))
        for child, name in _nested_functions(function):
            visit(child, scope, (qualname + '.' if qualname else '') + name)

    visit(tree, None, '')
    return sorted(set(found))


def helper_call_sites(source, filename='<source>'):
    """({qualified function calling settled_native_request}, {qualified functions defining it})."""
    tree = ast.parse(source, filename)
    calls, definitions = set(), set()

    def visit(node, qualname):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = (qualname + '.' if qualname else '') + child.name
                if child.name == HELPER and not isinstance(child, ast.ClassDef):
                    definitions.add(name)
                visit(child, name)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                if (isinstance(func, ast.Name) and func.id == HELPER) or (isinstance(func, ast.Attribute) and func.attr == HELPER):
                    calls.add(qualname or '<module>')
            visit(child, qualname)

    visit(tree, '')
    return calls, definitions


def controller_modules():
    for path in sorted(CONTROLLER.glob('*.py')):
        if not path.name.startswith('test_'):
            yield path


class NoBareRequestRefusalGuardTests(unittest.TestCase):
    def test_no_controller_code_refuses_on_request_json_presence_without_the_helper(self):
        offenders = []
        for path in controller_modules():
            for line, function in bare_request_refusals(path.read_text(encoding='utf-8-sig'), str(path)):
                offenders.append('%s:%d %s' % (path.name, line, function))
        self.assertEqual(offenders, [], 'A native-gate request.json may be a settled leftover (goatai#1885): '
                         'classify it with studio_native_gate.settled_native_request, never refuse on presence alone')

    def test_the_helper_is_defined_once_and_called_only_at_the_reviewed_sites(self):
        sites, definitions = set(), []
        for path in controller_modules():
            calls, defined = helper_call_sites(path.read_text(encoding='utf-8-sig'), str(path))
            sites |= {(path.name, name) for name in calls}
            definitions += [(path.name, name) for name in defined]
        self.assertEqual(definitions, [('studio_native_gate.py', HELPER)], 'one helper, never a copy')
        self.assertEqual(sites, HELPER_CALL_SITES, 'a new caller is reviewed and added here with its own site tests')
        for module, _ in HELPER_CALL_SITES:
            imports = [node for node in ast.walk(ast.parse((CONTROLLER / module).read_text(encoding='utf-8-sig')))
                       if isinstance(node, ast.ImportFrom) and any(alias.name == HELPER for alias in node.names)]
            self.assertTrue(imports and all(node.module == 'studio_native_gate' for node in imports), module)

    def test_the_guard_catches_every_pre_helper_refusal_shape(self):
        # The shapes these sites had before the helper (GOAT-EA #144 and this change), plus aliases.
        before = {
            'close_terminal': """
def close_terminal(controller):
    gate = controller.local / 'native-gate'
    def refuse_pending_native():
        if any((gate / name).exists() or (gate / name).is_symlink() for name in ('request.json', 'permit.json')):
            raise ValueError('pending')
""",
            'same_ea_rebind': """
def rebind(local):
    if any((local / 'native-gate' / name).exists() for name in ('request.json', 'permit.json')):
        raise ValueError('Unresolved native request or permit')
""",
            'never_started_retirement': """
def _verify(c):
    if any((c.local/'native-gate'/n).exists() for n in ('request.json','permit.json')):
        raise ValueError('New native request appeared after retirement')
""",
            'unissued_start': """
def native_absence(c):
    gate = safe_path(c.local / 'native-gate')
    for name in ('request.json', 'permit.json'):
        target = gate / name
        if target.exists() or target.is_symlink():
            raise ValueError('Native request or permit exists')
""",
            'bound path': """
def check(gate):
    request_path, permit_path = gate / 'request.json', gate / 'permit.json'
    present = request_path.exists() or request_path.is_symlink()
    if permit_path.exists() or present:
        _refuse('pending')
""",
            'os.path': """
import os
def check(gate):
    if os.path.exists(os.path.join(gate, 'request.json')) or os.path.exists(gate / 'request.json'):
        raise ValueError('pending')
""",
            'assertion': """
def check(gate):
    assert not (gate / 'request.json').exists()
""",
        }
        for name, source in before.items():
            with self.subTest(name):
                self.assertTrue(bare_request_refusals(source), name)

    def test_the_guard_accepts_classifiers_and_non_refusals(self):
        accepted = {
            'helper': """
def check(gate, session):
    request = gate / 'request.json'
    requested = request.exists() or request.is_symlink()
    settled = settled_native_request(gate, session) if requested else None
    if (gate / 'permit.json').exists() or (requested and settled is None):
        raise ValueError('pending')
""",
            'inline helper': """
def check(c, gate):
    if (gate/'permit.json').exists() or ((gate/'request.json').exists() and settled_native_request(gate, c) is None):
        raise ValueError('pending')
""",
            'byte comparison': """
def check(gate, expected):
    for name in ('request.json', 'permit.json'):
        target = gate / name
        if target.exists() and digest(target.read_bytes()) != expected:
            raise ValueError('changed')
""",
            'permit only': """
def check(gate):
    for name in ('request.json', 'permit.json'):
        target = gate / name
        if name == 'permit.json' and target.exists():
            raise ValueError('permit')
""",
            'enclosing permit block': """
def check(files, absent_permit):
    for name in ('issued.json', 'permit.json', 'request.json'):
        path = files[name]
        if name == 'permit.json' and absent_permit:
            if path.exists(): raise ValueError('permit changed')
            continue
""",
            'loop variable reused': """
def check(gate, paths):
    for name in ('request.json', 'permit.json'):
        print(gate / name)
    for name in ('local_run', 'common_run'):
        root = safe_path(paths[name])
        if root.exists():
            raise ValueError('run directory')
""",
            'absence': """
def check(files):
    if not files['request.json'].exists() and files['permit.json'].exists():
        raise ValueError('order')
""",
            'not a refusal': """
def check(gate):
    if (gate / 'request.json').exists():
        return read_json(gate / 'request.json')
""",
        }
        for name, source in accepted.items():
            with self.subTest(name):
                self.assertEqual(bare_request_refusals(source), [], name)


if __name__ == '__main__':
    unittest.main()
