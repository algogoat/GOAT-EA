"""Static proof that MT5 is only ever attached to under the installation's terminal lease (goatai#2350 6098964146).

``mt5.initialize(path)`` STARTS the terminal when it is not running. This scan of every non-test controller module
pins where it may be called, and proves each call runs inside ``with terminal_lease(...)``: lexically, or (for
DemoAgent._broker_readback) only from the one caller that holds the lease around it. A new call site, or a new
module importing MetaTrader5, fails here until it is leased and listed.
"""
import ast
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
# Where initialize may be called, and how the lease covers it: 'lexical' = inside `with terminal_lease(...)` in the
# same function; otherwise the qualname of the only function allowed to call it, which must hold the lease around that call.
INITIALIZE_SITES = {
    ('demo_agent', 'DemoAgent._broker_readback'): 'DemoAgent._broker',
    ('studio_agent_setup', 'broker_proof'): 'lexical',
    ('studio_monitor_probe', 'inspect_idle_demo'): 'lexical',
}
METATRADER_IMPORTERS = {'demo_agent', 'studio_agent_setup', 'studio_monitor_probe'}


def modules():
    for path in sorted(HERE.glob('*.py')):
        if not path.name.startswith('test_'):
            yield path.stem, ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def is_lease(item):
    call = item.context_expr
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return (isinstance(func, ast.Name) and func.id == 'terminal_lease') or (isinstance(func, ast.Attribute) and func.attr == 'terminal_lease')


def walk(node, qual=(), leased=False):
    """Yield (node, qualname, under_lease) for every node, tracking class/function nesting and enclosing lease blocks."""
    for child in ast.iter_child_nodes(node):
        child_qual, child_leased = qual, leased
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            child_qual, child_leased = qual + (child.name,), False      # a nested def runs later: no inherited lease
        elif isinstance(child, (ast.With, ast.AsyncWith)) and any(is_lease(item) for item in child.items):
            child_leased = True
        yield child, '.'.join(child_qual), child_leased
        yield from walk(child, child_qual, child_leased)


class TerminalLeaseStaticTests(unittest.TestCase):
    def test_every_initialize_call_is_listed_and_runs_under_the_lease(self):
        found = {}
        for module, tree in modules():
            for node, qual, leased in walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'initialize':
                    found.setdefault((module, qual), []).append(leased)
        self.assertEqual(set(found), set(INITIALIZE_SITES), 'every initialize(path) site is listed here and leased')
        for site, rule in INITIALIZE_SITES.items():
            if rule == 'lexical':
                self.assertTrue(all(found[site]), '%s.%s calls initialize outside `with terminal_lease`' % site)

    def test_broker_readback_is_only_reached_from_inside_the_lease(self):
        callers = []
        for module, tree in modules():
            for node, qual, leased in walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_broker_readback':
                    callers.append((module, qual, leased))
        self.assertEqual(callers, [('demo_agent', INITIALIZE_SITES[('demo_agent', 'DemoAgent._broker_readback')], True)])

    def test_only_the_listed_modules_import_metatrader5(self):
        importers = set()
        for module, tree in modules():
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) else [])
                if any(name and name.split('.')[0] == 'MetaTrader5' for name in names):
                    importers.add(module)
        self.assertEqual(importers, METATRADER_IMPORTERS)


if __name__ == '__main__':
    unittest.main()
