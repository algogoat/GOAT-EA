"""B55 gate 0 (docs/b55/BREAKOUT_SEQUENCE_SPEC.md section 6.2): effective-input equality with B54, the controller half.

The files (question 7; Claude-Mac goatai#2750 6789761790: every file in the pool at A0's merge, not only the 61):
  - every pool folder under scripts/fixtures (a folder named *-pool with a manifest.json, one sha256 per file). Today that
    is b54-pool, the 61 qualified SETs. A SET admitted later joins by landing in such a folder with its manifest row; this
    module and scripts/test_b55_gate0.cjs then read it with no code change;
  - B54's own breakout SETs, a mode on under Engine_Single: scripts/fixtures/b54-axes (18 synthetic optimisation SETs, each
    BRK and ORB axis at Y). "Flags off" means BRK_Start_Seq=false, not BRK_Mode off, so B54's breakout behaviour is inside
    the parity claim;
  - the 11 preregistered D1 hunt SETs (scripts/fixtures/hunt-d1).

Baseline: B54 = a8c6766 (GOAT-EA#306's merge, V1.49-BETA17-54). Its controller package and its contracts/v149 (S54) are
read from that commit (git archive) and run in a separate interpreter, so the baseline is B54's own code on B54's own
schema. The candidate is this tree's code on this tree's contracts/v149 (S55). Per file:
  1. the SET does not name BRK_Start_Seq;
  2. pinned_tester_inputs(values, S55), restricted to the B54 result's keys, equals the B54 result byte for byte; the one
     other key is BRK_Start_Seq at its declared default (appended_default: false; an sinput has no axis tuple);
  3. explicit_optimization_inputs(text, S55) equals the B54 result (an sinput adds no line); verify_explicit_inputs with
     the SET's frozen (Y) axes gives the same answer under both;
  4. validate_strategy gives the same answer under both (accepted with the same axes, or the same refusal, word for word),
     and so does check_tester_init (the OnInit rule mirror: EA_INIT_RULES runs inside validate_strategy).
Also, before the files: S55 is S54 with every B54 input unchanged and in order, plus exactly BRK_Start_Seq at the end,
declared as the spec's table says (0); S55 is what studio_input_schema.discover reads from this tree's header; and this
tree's code on S54 gives B54's results exactly (the A0 controller change is neutral on a B54 schema, init rules included).
Items 5 (OnInit through scripts/b50_tick_harness.cjs) and 6 (WriteSet bytes) are scripts/test_b55_gate0.cjs.
Load-bearing: the same checks must fail on mutated schemas (an existing default changed, two existing inputs reordered,
an existing input's type altered, the new input's default changed, the new input made an axis, a second input appended).
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
from studio_strategy_settings import (APPENDED_GROUPS, APPENDED_INPUTS, B55_INPUTS, appended_default, read_values,
                                      validate_strategy)
from studio_tester_report import pinned_tester_inputs

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'scripts' / 'fixtures'
B54_SOURCE = 'a8c6766243ff577bdcfc90495a6de33ce0797c88'
OTHER_FOLDERS = ('b54-axes', 'hunt-d1')   # B54's own breakout SETs (a mode on under Engine_Single); the D1 hunt SETs
# The spec's input table (section 3.1): name, declaration, type, default expression, the default as a SET spells it, and
# whether it is an optimization axis (an sinput never is).
B55_DECLARED = (
    ('BRK_Start_Seq', 'sinput', 'bool', 'false', 'false', False),
)
B55_NAMES = tuple(row[0] for row in B55_DECLARED)


def gate_files():
    """{'folder/name.set': bytes} for every gate-0 file, and the pool folders' manifests."""
    files, manifests = {}, {}
    for manifest in sorted(FIXTURES.glob('*-pool/manifest.json')):
        folder = manifest.parent
        manifests[folder.name] = json.loads(manifest.read_text(encoding='utf-8'))
        for row in manifests[folder.name]['files']:
            files[folder.name + '/' + row['file']] = (folder / row['file']).read_bytes()
    for name in OTHER_FOLDERS:
        for path in sorted((FIXTURES / name).glob('*.set')):
            files[name + '/' + path.name] = path.read_bytes()
    return files, manifests


def evaluate(raw, schema, read_values, validate_strategy, pinned_tester_inputs, explicit_optimization_inputs,
             verify_explicit_inputs, check_tester_init):
    """Everything gate 0 compares for one SET under one schema, with one build's controller functions (passed in, so the
    B54 interpreter runs exactly this body with B54's functions; it is sent there as source)."""
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


def b54_baseline(names):
    """B54's own controller code on B54's own schema, in a fresh interpreter over that commit's controller package."""
    with tempfile.TemporaryDirectory() as directory:
        zipfile.ZipFile(io.BytesIO(_git('archive', '--format=zip', B54_SOURCE, 'controller'))).extractall(directory)
        done = subprocess.run([sys.executable, '-I', '-c', _DRIVER, str(Path(directory) / 'controller'), str(FIXTURES),
                               json.dumps(names)], capture_output=True, check=False)
        if done.returncode != 0:
            raise AssertionError('the B54 baseline failed: ' + done.stderr.decode('utf-8', 'replace')[-2000:])
        return json.loads(done.stdout)


def schema_problems(s54, s55):
    """Item 0: S55 = S54 + exactly BRK_Start_Seq, appended, as declared; nothing of B54's changed."""
    problems = []
    names54, names55 = list(s54['inputs']), list(s55['inputs'])
    if names55[:len(names54)] != names54:
        problems.append('B54 inputs not kept in order')
    if names55[len(names54):] != list(B55_NAMES):
        problems.append('new inputs are not exactly BRK_Start_Seq at the end: ' + repr(names55[len(names54):]))
    for name in names54:
        if s55['inputs'].get(name) != s54['inputs'][name]:
            problems.append('B54 input changed: ' + name)
    if s55.get('defines') != s54.get('defines'):
        problems.append('defines changed')
    for name, declaration, kind, expression, _, axis in B55_DECLARED:
        definition = s55['inputs'].get(name) or {}
        want = dict(type=kind, declaration=declaration, default_expression=expression, optimizable=axis, enum_choices=None,
                    dependency_audited=False)
        if definition != want:
            problems.append('B55 input not as the spec declares it: ' + name + ' ' + repr(definition))
    return problems


def file_problems(text, base, cand, s55):
    """Items 1-4 for one SET: base is B54's result on S54, cand this tree's on S55."""
    problems = []
    for name in B55_NAMES:                                                                              # 1
        if ('\n' + name + '=') in '\n' + text:
            problems.append('the SET names ' + name)
    pinned54, pinned55 = base['pinned'], cand['pinned']                                                 # 2
    if {k: pinned55.get(k) for k in pinned54} != pinned54:
        problems.append('pinned inputs differ on B54 keys: '
                        + repr(sorted(k for k in pinned54 if pinned55.get(k) != pinned54[k])[:6]))
    if sorted(set(pinned55) - set(pinned54)) != sorted(B55_NAMES):
        problems.append('pinned inputs add other keys than BRK_Start_Seq: ' + repr(sorted(set(pinned55) - set(pinned54))))
    for name, _, _, _, default, axis in B55_DECLARED:
        want = default + '||' + default + '||0||' + default + '||N' if axis else default
        definition = s55['inputs'].get(name)
        if definition is None or appended_default(definition) != default or pinned55.get(name) != want:
            problems.append('pinned ' + name + '=' + repr(pinned55.get(name)) + ', not ' + want)
    if cand['explicit'] != base['explicit']:                                                             # 3
        problems.append('explicit optimization inputs are not B54\'s (an sinput adds no line)')
    if base['verify'] != cand['verify']:
        problems.append('verify_explicit_inputs: B54 ' + base['verify'] + ', B55 ' + cand['verify'])
    if base['axes'] != cand['axes']:
        problems.append('frozen axes differ')
    if cand['validate'] != base['validate']:                                                             # 4
        problems.append('validate_strategy: B54 ' + repr(base['validate'])[:200] + ', B55 ' + repr(cand['validate'])[:200])
    if base['tester_init'] != cand['tester_init']:
        problems.append('check_tester_init: B54 ' + base['tester_init'] + ', B55 ' + cand['tester_init'])
    return problems


class Gate0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.manifests = gate_files()
        cls.names = list(cls.raw)
        cls.s55 = json.loads((ROOT / 'controller/contracts/v149/inputs.json').read_text(encoding='utf-8-sig'))
        cls.b54 = b54_baseline(cls.names)
        cls.s54 = cls.b54['schema']
        cls.cand = {name: tree(cls.raw[name], cls.s55) for name in cls.names}

    def test_the_files_are_every_pool_folder_and_b54s_breakout_sets(self):
        self.assertIn('b54-pool', self.manifests, 'the 61 qualified SETs')
        self.assertEqual(len(self.manifests['b54-pool']['files']), 61)
        for folder, manifest in self.manifests.items():
            rows = manifest['files']
            self.assertEqual(sorted(p.name for p in (FIXTURES / folder).iterdir() if p.name != 'manifest.json'),
                             sorted(row['file'] for row in rows), folder + ': the fixture folder is exactly its manifest')
            for row in rows:
                with self.subTest(file=folder + '/' + row['file']):
                    raw = self.raw[folder + '/' + row['file']]
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'], 'byte-identical')
                    self.assertTrue(raw.startswith(b'\xff\xfe'), 'UTF-16LE with a BOM, as MT5 writes it')
        pool = sum(len(manifest['files']) for manifest in self.manifests.values())
        self.assertEqual(len(self.names), pool + 18 + 11, 'every pool file, the 18 b54-axes SETs, the 11 D1 hunt SETs')
        # B54's breakout behaviour is inside the claim: the b54-axes SETs run a breakout mode on the single engine.
        on = [name for name in self.names if name.startswith('b54-axes/')
              and (self.cand[name]['pinned']['BRK_Mode'] != '0' or self.cand[name]['pinned']['ORB_Mode'] != '0')]
        self.assertEqual(len(on), 18)
        self.assertTrue(all(self.cand[name]['pinned']['Engine_Mode'] == '1' for name in on))
        # Not vacuous: accepted files and refused ladders are both in the set, and every file is answered either way.
        accepted = [name for name in self.names if isinstance(self.b54['files'][name]['validate'], dict)]
        self.assertGreaterEqual(len(accepted), pool)
        self.assertTrue(any(not isinstance(self.b54['files'][name]['validate'], dict) for name in self.names))

    def test_0_the_schema_is_b54_plus_the_switch(self):
        self.assertEqual(schema_problems(self.s54, self.s55), [])
        header = (ROOT / 'GOAT_Inputs_Definitions.mqh').read_bytes()
        self.assertEqual(discover(header, self.s55['defines']), self.s55, 'contracts/v149 is what discover reads from this header')
        self.assertEqual(self.s55['source_sha256'], hashlib.sha256(header).hexdigest())
        self.assertEqual(B55_INPUTS, B55_NAMES)
        self.assertEqual(APPENDED_INPUTS, tuple(self.b54['appended']) + B55_NAMES, 'B55_INPUTS appended last')
        self.assertEqual([list(g) for g in APPENDED_GROUPS], self.b54['groups'] + [list(B55_NAMES)])

    def test_this_trees_code_on_b54s_schema_is_b54(self):
        for name in self.names:
            with self.subTest(file=name):
                self.assertEqual(json.loads(json.dumps(tree(self.raw[name], self.s54))), self.b54['files'][name])

    def test_1_to_4_every_file(self):
        for name in self.names:
            with self.subTest(file=name):
                self.assertEqual(file_problems(self.raw[name].decode('utf-16'), self.b54['files'][name], self.cand[name],
                                               self.s55), [])

    def test_the_gate_is_load_bearing(self):
        def mutant(change):
            schema = copy.deepcopy(self.s55)
            change(schema)
            return schema
        def reorder(schema):
            items = list(schema['inputs'].items())
            items[10], items[11] = items[11], items[10]
            schema['inputs'] = dict(items)
        def retype(schema):
            schema['inputs']['Random_Seed']['type'] = 'long'
        def extra(schema):
            schema['inputs']['BRK_Start_Extra'] = dict(schema['inputs']['BRK_Start_Seq'])
        mutants = {
            'an existing default changed (Single_SL_ATR 0.0 -> 0.5)':
                mutant(lambda s: s['inputs']['Single_SL_ATR'].update(default_expression='0.5')),
            'an existing B54 default changed (BRK_Bars 20 -> 21)':
                mutant(lambda s: s['inputs']['BRK_Bars'].update(default_expression='21')),
            'two existing inputs reordered': mutant(reorder),
            'an existing input retyped (Random_Seed int -> long)': mutant(retype),
            'the new default changed (BRK_Start_Seq false -> true)':
                mutant(lambda s: s['inputs']['BRK_Start_Seq'].update(default_expression='true')),
            'the new input made an axis (input, optimizable)':
                mutant(lambda s: s['inputs']['BRK_Start_Seq'].update(declaration='input', optimizable=True)),
            'a second input appended': mutant(extra),
        }
        # A pre-B50 pool SET (it omits Single_SL_ATR and the B54 inputs) and a pool single (it carries the B51 inputs).
        pool = [name for name in self.names if name.startswith('b54-pool/')]
        single = next(row['file'] for row in self.manifests['b54-pool']['files'] if row['engine'] == 'single')
        probes = [next(n for n in pool if 'Single_SL_ATR=' not in self.raw[n].decode('utf-16')), 'b54-pool/' + single]
        for label, schema in mutants.items():
            with self.subTest(mutant=label):
                problems = schema_problems(self.s54, schema)
                for name in probes:
                    problems += file_problems(self.raw[name].decode('utf-16'), self.b54['files'][name],
                                              tree(self.raw[name], schema), schema)
                self.assertTrue(problems, 'mutant not caught: ' + label)
        # The per-file checks alone catch a changed default: an existing one on a SET that omits that input (item 2), and
        # the switch's own on every SET (items 2 and 4: a pool sequence with the switch on is refused at init).
        for label in ('an existing default changed (Single_SL_ATR 0.0 -> 0.5)', 'the new default changed (BRK_Start_Seq false -> true)'):
            changed = mutants[label]
            self.assertTrue(file_problems(self.raw[probes[0]].decode('utf-16'), self.b54['files'][probes[0]],
                                          tree(self.raw[probes[0]], changed), changed), label)


if __name__ == '__main__':
    unittest.main()
