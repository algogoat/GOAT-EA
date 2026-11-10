"""B54 gate 0 (docs/b54/BREAKOUT_ENTRIES_SPEC.md section 6.2): effective-input equality on the pool, the controller half.

The pool (ruling 2) is the 61 SETs of the qualified inventory (nonrr-round08 qualified-inventory-final.json, sha256
f4337e1b...; rounds 09-12 admitted none, so the round-12 inventory is the same file): 59 sequence, 2 single. They are
committed byte-identical under scripts/fixtures/b54-pool (-text in .gitattributes) with manifest.json, one sha256 per
file, as scripts/test_hunt_sets_init.cjs keeps the D1 hunt SETs.

Baseline: B53 = 216e1622 (GOAT-EA#296's merge, V1.49-BETA17-53). Its controller package and its contracts/v149 (S53)
are read from that commit (git archive) and run in a separate interpreter, so the baseline is B53's own code on B53's own
schema. The candidate is this tree's code on this tree's contracts/v149 (S54). Per file:
  1. the SET names none of the 14 B54 inputs;
  2. pinned_tester_inputs(values, S54), restricted to the B53 result's keys, equals the B53 result byte for byte; the other
     keys are exactly the 14 new names, each at its declared default (appended_default), an optimizable one as d||d||0||d||N;
  3. explicit_optimization_inputs(text, S54) equals the B53 result plus only the 11 new optimizable lines, in order;
     verify_explicit_inputs with the SET's frozen (Y) axes passes under both;
  4. validate_strategy accepts the file under both with the same axes, and check_tester_init (TESTER_INIT_RULES) passes
     the same way (the OnInit rule mirror: EA_INIT_RULES runs inside validate_strategy).
Also, before the files: S54 is S53 with every B53 input unchanged and in order, plus exactly the 14 B54 inputs at the end,
declared as the spec's tables say (0); S54 is what studio_input_schema.discover reads from this tree's header; and this
tree's code on S53 gives B53's results exactly (the A0 controller change is neutral on a B53 schema).
Items 5 (OnInit through scripts/b50_tick_harness.cjs) and 6 (WriteSet bytes) are scripts/test_b54_gate0.cjs.
Load-bearing: the same checks must fail on mutated schemas (an existing default changed, two existing inputs reordered,
an existing input's type altered, a new input's default changed, a fifteenth input appended).
"""
import copy
import hashlib
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from studio_input_schema import discover
from studio_ea_init_rules import check_tester_init
from studio_optimization_inputs import explicit_optimization_inputs, verify_explicit_inputs
from studio_strategy_settings import (APPENDED_GROUPS, APPENDED_INPUTS, B54_INPUTS, appended_default, read_values,
                                      validate_strategy)
from studio_tester_report import pinned_tester_inputs

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / 'scripts' / 'fixtures' / 'b54-pool'
B53_SOURCE = '216e16225441cfc1bfe0546c1c70adaf327405cf'
INVENTORY_SHA256 = 'f4337e1bd296f7a4de3c5e53d6f7acab9d7454d8b6172739eb5729183984936c'
# The spec's input tables (sections 3.1 and 4.1), in declaration order: name, declaration, type, default expression,
# the default as a SET spells it, and whether it is an optimization axis (an input that is not a string).
B54_DECLARED = (
    ('BRK_Mode', 'sinput', 'ENUM_MODE_BRK', 'BRK_Disabled', '0', False),
    ('BRK_TF_', 'input', 'ENUM_MODE_TFs', 'TF_H1', '60', True),
    ('BRK_Bars', 'input', 'int', '20', '20', True),
    ('BRK_Buffer_ATR', 'input', 'double', '0.0', '0.0', True),
    ('BRK_Once_Per_Level', 'input', 'bool', 'true', 'true', True),
    ('ORB_Mode', 'sinput', 'ENUM_MODE_ORB', 'ORB_Disabled', '0', False),
    ('ORB_Clock', 'sinput', 'ENUM_ORB_CLOCK', 'ORB_Clock_NewYork', '0', False),
    ('ORB_TF_', 'input', 'ENUM_MODE_TFs', 'TF_M5', '5', True),
    ('ORB_Start_Minute', 'input', 'int', '570', '570', True),
    ('ORB_Range_Minutes', 'input', 'int', '30', '30', True),
    ('ORB_Entry_Minutes', 'input', 'int', '0', '0', True),
    ('ORB_Buffer_ATR', 'input', 'double', '0.0', '0.0', True),
    ('ORB_Min_Range_ATR', 'input', 'double', '0.0', '0.0', True),
    ('ORB_Max_Range_ATR', 'input', 'double', '0.0', '0.0', True),
)
B54_NAMES = tuple(row[0] for row in B54_DECLARED)
B54_ENUMS = {'ENUM_MODE_BRK': {'BRK_Disabled': 0, 'BRK_NBar': 1, 'BRK_PriorDay': 2},
             'ENUM_MODE_ORB': {'ORB_Disabled': 0, 'ORB_Breakout': 1},
             'ENUM_ORB_CLOCK': {'ORB_Clock_NewYork': 0, 'ORB_Clock_London': 1}}
# Item 3: the lines explicit_optimization_inputs appends for a complete SET that omits the new axes, in input order.
NEW_EXPLICIT = ''.join(name + '=' + d + '||' + d + '||0||' + d + '||N\r\n' for name, _, _, _, d, axis in B54_DECLARED if axis)


def evaluate(raw, schema, read_values, validate_strategy, pinned_tester_inputs, explicit_optimization_inputs,
             verify_explicit_inputs, check_tester_init):
    """Everything gate 0 compares for one SET under one schema, with one build's controller functions (passed in, so the
    B53 interpreter runs exactly this body with B53's functions; it is sent there as source)."""
    values = read_values(raw)
    text = raw.decode('utf-16')
    axes = sorted(name for name, value in values.items() if name in schema['inputs'] and value.endswith('||Y'))
    explicit = explicit_optimization_inputs(text, schema)
    out = dict(names=list(values), axes=axes, pinned=pinned_tester_inputs(values, schema), explicit=explicit)
    try:
        verify_explicit_inputs(read_values(explicit.encode('utf-16')), schema, axes)
        out['verify'] = 'ok'
    except ValueError as exc:
        out['verify'] = 'refused: ' + str(exc)
    try:
        out['validate'] = validate_strategy(values, schema)['axes']
    except ValueError as exc:
        out['validate'] = 'refused: ' + str(exc)
    try:
        check_tester_init(values, schema)
        out['tester_init'] = 'ok'
    except ValueError as exc:
        out['tester_init'] = 'refused: ' + str(exc)
    return out


_DRIVER = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from studio_strategy_settings import read_values, validate_strategy, APPENDED_INPUTS, APPENDED_GROUPS
from studio_tester_report import pinned_tester_inputs
from studio_optimization_inputs import explicit_optimization_inputs, verify_explicit_inputs
from studio_ea_init_rules import check_tester_init
''' + inspect.getsource(evaluate) + '''
schema = json.loads((Path(sys.argv[1]) / 'contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
files = {name: evaluate((Path(sys.argv[2]) / name).read_bytes(), schema, read_values, validate_strategy,
                        pinned_tester_inputs, explicit_optimization_inputs, verify_explicit_inputs, check_tester_init)
         for name in json.loads(sys.argv[3])}
print(json.dumps(dict(files=files, schema=schema, appended=list(APPENDED_INPUTS), groups=[list(g) for g in APPENDED_GROUPS])))
'''


def tree(raw, schema):
    return evaluate(raw, schema, read_values, validate_strategy, pinned_tester_inputs, explicit_optimization_inputs,
                    verify_explicit_inputs, check_tester_init)


def _git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def b53_baseline(names):
    """B53's own controller code on B53's own schema, in a fresh interpreter over that commit's controller package."""
    with tempfile.TemporaryDirectory() as directory:
        zipfile.ZipFile(io.BytesIO(_git('archive', '--format=zip', B53_SOURCE, 'controller'))).extractall(directory)
        done = subprocess.run([sys.executable, '-I', '-c', _DRIVER, str(Path(directory) / 'controller'), str(POOL),
                               json.dumps(names)], capture_output=True, check=False)
        if done.returncode != 0:
            raise AssertionError('the B53 baseline failed: ' + done.stderr.decode('utf-8', 'replace')[-2000:])
        return json.loads(done.stdout)


def schema_problems(s53, s54):
    """Item 0: S54 = S53 + exactly the 14, appended, as declared; nothing of B53's changed."""
    problems = []
    names53, names54 = list(s53['inputs']), list(s54['inputs'])
    if names54[:len(names53)] != names53:
        problems.append('B53 inputs not kept in order')
    if names54[len(names53):] != list(B54_NAMES):
        problems.append('new inputs are not exactly the 14 B54 inputs at the end: ' + repr(names54[len(names53):]))
    for name in names53:
        if s54['inputs'].get(name) != s53['inputs'][name]:
            problems.append('B53 input changed: ' + name)
    if s54.get('defines') != s53.get('defines'):
        problems.append('defines changed')
    tfs = s53['inputs']['ATR_TF_']['enum_choices']
    for name, declaration, kind, expression, _, axis in B54_DECLARED:
        definition = s54['inputs'].get(name) or {}
        want = dict(type=kind, declaration=declaration, default_expression=expression, optimizable=axis,
                    enum_choices=tfs if kind == 'ENUM_MODE_TFs' else B54_ENUMS.get(kind), dependency_audited=False)
        if definition != want:
            problems.append('B54 input not as the spec declares it: ' + name + ' ' + repr(definition))
    return problems


def file_problems(text, base, cand, s54):
    """Items 1-4 for one SET: base is B53's result on S53, cand this tree's on S54."""
    problems = []
    for name in B54_NAMES:                                                                              # 1
        if ('\n' + name + '=') in '\n' + text:
            problems.append('the SET names ' + name)
    pinned53, pinned54 = base['pinned'], cand['pinned']                                                 # 2
    if {k: pinned54.get(k) for k in pinned53} != pinned53:
        problems.append('pinned inputs differ on B53 keys: '
                        + repr(sorted(k for k in pinned53 if pinned54.get(k) != pinned53[k])[:6]))
    if sorted(set(pinned54) - set(pinned53)) != sorted(B54_NAMES):
        problems.append('pinned inputs add other keys than the 14: ' + repr(sorted(set(pinned54) - set(pinned53))))
    for name, _, _, _, default, axis in B54_DECLARED:
        want = default + '||' + default + '||0||' + default + '||N' if axis else default
        definition = s54['inputs'].get(name)
        if definition is None or appended_default(definition) != default or pinned54.get(name) != want:
            problems.append('pinned ' + name + '=' + repr(pinned54.get(name)) + ', not ' + want)
    if cand['explicit'] != base['explicit'] + NEW_EXPLICIT:                                              # 3
        problems.append('explicit optimization inputs are not B53\'s plus the 11 new lines')
    if base['verify'] != 'ok' or cand['verify'] != 'ok':
        problems.append('verify_explicit_inputs: B53 ' + base['verify'] + ', B54 ' + cand['verify'])
    if base['axes'] != cand['axes']:
        problems.append('frozen axes differ')
    if not isinstance(base['validate'], dict) or cand['validate'] != base['validate']:                   # 4
        problems.append('validate_strategy: B53 ' + repr(base['validate'])[:200] + ', B54 ' + repr(cand['validate'])[:200])
    if base['tester_init'] != cand['tester_init']:
        problems.append('check_tester_init: B53 ' + base['tester_init'] + ', B54 ' + cand['tester_init'])
    return problems


class Gate0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((POOL / 'manifest.json').read_text(encoding='utf-8'))
        cls.names = [row['file'] for row in cls.manifest['files']]
        cls.raw = {name: (POOL / name).read_bytes() for name in cls.names}
        cls.s54 = json.loads((ROOT / 'controller/contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        cls.b53 = b53_baseline(cls.names)
        cls.s53 = cls.b53['schema']
        cls.cand = {name: tree(cls.raw[name], cls.s54) for name in cls.names}

    def test_the_pool_is_the_61_byte_identical(self):
        inventory = self.manifest['inventory']
        self.assertEqual(inventory['sha256'], INVENTORY_SHA256, 'the spec\'s inventory (nonrr-round08)')
        self.assertEqual(inventory['round12_sha256'], INVENTORY_SHA256, 'rounds 09-12 admitted none')
        self.assertEqual((inventory['rows'], inventory['sequence'], inventory['single']), (61, 59, 2))
        self.assertEqual(len(self.names), 61)
        self.assertEqual(len(set(self.names)), 61)
        self.assertEqual(sorted(p.name for p in POOL.iterdir() if p.name != 'manifest.json'), sorted(self.names),
                         'the fixture folder is exactly the manifest')
        self.assertEqual(len({row['original_path'] for row in self.manifest['files']}), 61)
        self.assertEqual(sum(row['engine'] == 'single' for row in self.manifest['files']), 2)
        for row in self.manifest['files']:
            with self.subTest(file=row['file']):
                self.assertEqual(hashlib.sha256(self.raw[row['file']]).hexdigest(), row['sha256'], 'byte-identical')
                self.assertTrue(self.raw[row['file']].startswith(b'\xff\xfe'), 'UTF-16LE with a BOM, as MT5 writes it')
                self.assertIn('\\' + row['asset'] + '\\', row['original_path'])
                self.assertEqual(row['file'].split('-')[1], row['asset'])

    def test_0_the_schema_is_b53_plus_the_14(self):
        self.assertEqual(schema_problems(self.s53, self.s54), [])
        header = (ROOT / 'GOAT_Inputs_Definitions.mqh').read_bytes()
        self.assertEqual(discover(header, self.s54['defines']), self.s54, 'contracts/v149 is what discover reads from this header')
        self.assertEqual(self.s54['source_sha256'], hashlib.sha256(header).hexdigest())
        self.assertEqual(B54_INPUTS, B54_NAMES)
        self.assertEqual(APPENDED_INPUTS, tuple(self.b53['appended']) + B54_NAMES, 'B54_INPUTS appended last')
        self.assertEqual([list(g) for g in APPENDED_GROUPS], self.b53['groups'] + [list(B54_NAMES)])

    def test_this_trees_code_on_b53s_schema_is_b53(self):
        for name in self.names:
            with self.subTest(file=name):
                self.assertEqual(json.loads(json.dumps(tree(self.raw[name], self.s53))), self.b53['files'][name])

    def test_1_to_4_every_pool_set(self):
        # Every pool SET is complete (it validates), so under S54 each gains the 11 new axis lines: item 3 is never vacuous.
        for name in self.names:
            with self.subTest(file=name):
                self.assertEqual(file_problems(self.raw[name].decode('utf-16'), self.b53['files'][name], self.cand[name],
                                               self.s54), [])

    def test_the_gate_is_load_bearing(self):
        def mutant(change):
            schema = copy.deepcopy(self.s54)
            change(schema)
            return schema
        def reorder(schema):
            items = list(schema['inputs'].items())
            items[10], items[11] = items[11], items[10]
            schema['inputs'] = dict(items)
        def retype(schema):
            schema['inputs']['Random_Seed']['type'] = 'long'
        def extra(schema):
            schema['inputs']['BRK_Extra'] = dict(schema['inputs']['BRK_Bars'])
        mutants = {
            'an existing default changed (Single_SL_ATR 0.0 -> 0.5)':
                mutant(lambda s: s['inputs']['Single_SL_ATR'].update(default_expression='0.5')),
            'two existing inputs reordered': mutant(reorder),
            'an existing input retyped (Random_Seed int -> long)': mutant(retype),
            'a new default changed (BRK_Bars 20 -> 21)':
                mutant(lambda s: s['inputs']['BRK_Bars'].update(default_expression='21')),
            'a new optimizable input made an sinput (ORB_TF_)':
                mutant(lambda s: s['inputs']['ORB_TF_'].update(declaration='sinput', optimizable=False)),
            'a fifteenth input appended': mutant(extra),
        }
        # A pre-B50 SET (it omits Single_SL_ATR) and a single (it carries the B51 inputs).
        probes = [next(n for n in self.names if 'Single_SL_ATR=' not in self.raw[n].decode('utf-16')),
                  next(row['file'] for row in self.manifest['files'] if row['engine'] == 'single')]
        for label, schema in mutants.items():
            with self.subTest(mutant=label):
                problems = schema_problems(self.s53, schema)
                for name in probes:
                    problems += file_problems(self.raw[name].decode('utf-16'), self.b53['files'][name],
                                              tree(self.raw[name], schema), schema)
                self.assertTrue(problems, 'mutant not caught: ' + label)
        # A per-file check alone (item 2) catches a changed existing default on a SET that omits that input.
        changed = mutants['an existing default changed (Single_SL_ATR 0.0 -> 0.5)']
        self.assertTrue(file_problems(self.raw[probes[0]].decode('utf-16'), self.b53['files'][probes[0]],
                                      tree(self.raw[probes[0]], changed), changed))


if __name__ == '__main__':
    unittest.main()
