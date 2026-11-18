"""B55 PR A0 (docs/b55/BREAKOUT_SEQUENCE_SPEC.md 3.7 and 7; Claude-Mac goatai#2750 6789761790): the controller half of the
b55-init rules, on files.

scripts/fixtures/b55-axes holds synthetic optimisation SETs (never pool files): each is a complete SET at the schema's
defaults on a breakout sequence as the spec's section 7 lists it for the templates (the grid engine, BRK_Start_Seq, both
delays 0, no delayed lots, RSI off, an explicit ATR_TF_), with its axes at Y. axes.json names, per SET, the rule the EA
reports at each probe (the SET's values, then each Y axis at its start and at its stop, the others at their values) and
for the whole ladder (every rung of every axis; this module only, the EA runs one pass at a time).

Here the controller (validate_strategy, so EA_INIT_RULES over the reachable values) must give each probe and each ladder
exactly that rule; scripts/test_b55_init.cjs runs the same files through the EA's OnInit (b50_tick_harness), so the
mirror and the EA agree on the same files. A0 ships the switch refused (BRK_SEQ_NOT_BUILT, the block's last line): a
probe that names it passed every earlier rule, and no probe with the switch on is 'ok'. PR A's commit that adds the
sequence start path removes the rule and turns those probes into 'ok'.

The spec's table (3.7) names a SET each rule must refuse and one it must pass, on committed files: B54's synthetic single
(scripts/fixtures/b54-axes/brk-nbar-ends.set) and a pool sequence (scripts/fixtures/b54-pool/01-EURCAD-sequence.set), each
as committed and with the named lines changed. The third proof (spec 7, the applicable_rules trap) runs the same files on
B54's own schema, read from B54's commit: it has no BRK_Start_Seq and must still refuse a breakout on the grid engine.
"""
import json
from pathlib import Path
import re
import subprocess
import unittest

from studio_ea_init_rules import EA_INIT_CODE, EA_INIT_RULES, EA_SOURCE, applicable_rules
from studio_installation import contracts
from studio_strategy_settings import B55_INPUTS, read_values, validate_strategy
from studio_template_tools import schema_default

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / 'scripts' / 'fixtures' / 'b55-axes'
TABLE = json.loads((DIR / 'axes.json').read_text(encoding='utf-8'))
SCHEMA = contracts('1.49')[0]
B54_SOURCE = 'a8c6766243ff577bdcfc90495a6de33ce0797c88'   # B54 (V1.49-BETA17-54), the merge of GOAT-EA#306
B55_LINES = range(5148, 5161)   # GOAT V1.49.mq5's b55-init block
B55_RULES = ('BRK_SEQ_WITHOUT_BRK', 'BRK_SEQ_WITH_SINGLE', 'BRK_SEQ_WITH_DELAY', 'BRK_SEQ_NOT_BUILT')
NARROWED = 'BRK_WITHOUT_SINGLE'   # line 5128, in the b54-init block: narrowed by the switch, B54's alert and code
B54_SINGLE = ROOT / 'scripts' / 'fixtures' / 'b54-axes' / 'brk-nbar-ends.set'
POOL_SEQUENCE = ROOT / 'scripts' / 'fixtures' / 'b54-pool' / '01-EURCAD-sequence.set'


def render(entry, schema=SCHEMA):
    """The SET MT5 would read: every input in the schema's order, at the entry's value, else the base's, else the default."""
    lines = ['; GOAT B55 synthetic axis SET ' + entry['file'] + ' (scripts/fixtures/b55-axes/axes.json; not a pool file)']
    for name, definition in schema['inputs'].items():
        value = entry['lines'].get(name, TABLE['base'].get(name))
        lines.append(name + '=' + (value if value is not None else schema_default(name, definition, schema.get('defines'))))
    return b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def probes(values):
    """(name, fixed values): the SET's values, then each Y axis at its start and at its stop."""
    current = {name: text.split('||')[0] for name, text in values.items()}
    yield 'current', current
    for name, text in values.items():
        parts = text.split('||')
        if len(parts) == 5 and parts[4] == 'Y':
            yield name + '@start', dict(current, **{name: parts[1]})
            yield name + '@stop', dict(current, **{name: parts[3]})


def verdict(values, schema=SCHEMA):
    try:
        validate_strategy(values, schema)
    except ValueError as refusal:
        found = re.match(re.escape(EA_INIT_CODE) + r': .*? Rule (\w+) \(', str(refusal))
        if not found:
            raise
        return found[1]
    return 'ok'


def b54_schema():
    blob = subprocess.run(['git', 'show', B54_SOURCE + ':controller/contracts/v149/inputs.json'], cwd=ROOT, capture_output=True,
                          check=True).stdout
    return json.loads(blob.decode('utf-8-sig'))


class B55AxisSetTests(unittest.TestCase):
    def test_the_alerts_and_codes_are_the_eas(self):
        source = (ROOT / EA_SOURCE).read_text(encoding='utf-8-sig').split('\n')
        b55 = [rule for rule in EA_INIT_RULES if rule['lines'][0] in B55_LINES]
        self.assertEqual(tuple(rule['id'] for rule in b55), B55_RULES)
        narrowed = next(rule for rule in EA_INIT_RULES if rule['id'] == NARROWED)
        self.assertEqual(narrowed['lines'], (5128,))
        self.assertEqual(TABLE['alerts'], {rule['id']: rule['alert'] for rule in [narrowed] + b55})
        for rule in [narrowed] + b55:
            line = source[rule['lines'][0]-1]
            self.assertIn('return ' + TABLE['codes'][rule['id']] + ';', line, rule['id'])
        self.assertIn('&& !BRK_Start_Seq)', source[5128-1], 'line 5128 is narrowed by the switch')

    def test_the_files_are_the_tables_sets_rendered(self):
        self.assertEqual(sorted(path.name for path in DIR.glob('*.set')), sorted(entry['file'] for entry in TABLE['sets']))
        for entry in TABLE['sets']:
            with self.subTest(file=entry['file']):
                self.assertEqual((DIR / entry['file']).read_bytes(), render(entry))

    def test_each_probe_gets_the_tables_rule(self):
        for entry in TABLE['sets']:
            values = read_values((DIR / entry['file']).read_bytes())
            seen = {}
            for name, fixed in probes(values):
                with self.subTest(file=entry['file'], probe=name):
                    seen[name] = verdict(fixed)
            self.assertEqual(seen, entry['probes'], entry['file'])

    def test_the_whole_ladder_gets_the_tables_rule(self):
        for entry in TABLE['sets']:
            with self.subTest(file=entry['file']):
                self.assertEqual(verdict(read_values((DIR / entry['file']).read_bytes())), entry['ladder'])

    def test_every_rule_is_hit_and_the_switch_is_never_accepted(self):
        hit = {rule for entry in TABLE['sets'] for rule in entry['probes'].values()}
        self.assertEqual(hit, set(B55_RULES) | {NARROWED, 'ok'})
        # A0: the switch is refused as not built, so no probe with the switch on is accepted; with it off, a probe is
        # accepted or refused by B54's rule alone.
        for entry in TABLE['sets']:
            switch = entry['lines'].get('BRK_Start_Seq', TABLE['base']['BRK_Start_Seq'])
            for probe, rule in entry['probes'].items():
                with self.subTest(file=entry['file'], probe=probe):
                    if switch == 'true':
                        self.assertIn(rule, B55_RULES)
                    else:
                        self.assertIn(rule, ('ok', NARROWED))
        # The two valid sequences the spec names pass every rule but the not-built one, at every probe and rung.
        for name in ('seq-nbar-inside.set', 'seq-pday-inside.set'):
            entry = next(entry for entry in TABLE['sets'] if entry['file'] == name)
            self.assertEqual(set(entry['probes'].values()) | {entry['ladder']}, {'BRK_SEQ_NOT_BUILT'}, name)


class SpecTableTests(unittest.TestCase):
    """Spec 3.7's table: per rule, the SET it must refuse and the SET it must pass, on committed files."""
    @classmethod
    def setUpClass(cls):
        cls.single = read_values(B54_SINGLE.read_bytes())
        cls.pool = read_values(POOL_SEQUENCE.read_bytes())
        cls.seq = {entry['file']: read_values((DIR / entry['file']).read_bytes()) for entry in TABLE['sets']}

    def test_the_committed_files_name_no_b55_input(self):
        for values in (self.single, self.pool):
            self.assertFalse(set(B55_INPUTS) & set(values))
        self.assertEqual((self.single['Engine_Mode'], self.single['BRK_Mode'].split('||')[0]), ('1', '1'))
        self.assertNotIn('BRK_Mode', self.pool)
        self.assertEqual((self.pool['Delay_Trade'].split('||')[0], self.pool['Delay_Trade_Live'].split('||')[0]), ('0', '0'))

    def test_brk_without_single_changed(self):
        grid = dict(self.single, Engine_Mode='0')
        self.assertEqual(verdict(grid), 'BRK_WITHOUT_SINGLE')                                                # must refuse
        self.assertEqual(verdict(dict(grid, BRK_Start_Seq='true', Delay_Trade='0', Delay_Trade_Live='0')),   # must pass it
                         'BRK_SEQ_NOT_BUILT')                                                                # (A0; PR A: ok)
        self.assertEqual(verdict(self.single), 'ok')                                                         # must pass

    def test_brk_seq_without_brk(self):
        self.assertEqual(verdict(dict(self.pool, BRK_Start_Seq='true')), 'BRK_SEQ_WITHOUT_BRK')
        self.assertEqual(verdict(self.pool), 'ok')

    def test_brk_seq_with_single(self):
        self.assertEqual(verdict(dict(self.single, BRK_Start_Seq='true')), 'BRK_SEQ_WITH_SINGLE')
        self.assertEqual(verdict(dict(self.single, BRK_Start_Seq='true', Delay_Trade='0', Delay_Trade_Live='0')), 'BRK_SEQ_WITH_SINGLE')
        self.assertEqual(verdict(self.single), 'ok')

    def test_brk_seq_with_delay(self):
        inside = self.seq['seq-nbar-inside.set']
        self.assertEqual(verdict(dict(inside, Delay_Trade='1')), 'BRK_SEQ_WITH_DELAY')
        self.assertEqual(verdict(dict(inside, Delay_Trade_Live='0||0||1||1||Y')), 'BRK_SEQ_WITH_DELAY')
        with self.assertRaisesRegex(ValueError, r'Rule BRK_SEQ_WITH_DELAY .*\(reachable through the optimization range of Delay_Trade_Live\)'):
            validate_strategy(dict(inside, Delay_Trade_Live='0||0||1||1||Y'), SCHEMA)
        for name in ('seq-nbar-inside.set', 'seq-pday-inside.set'):                                          # must pass it
            self.assertEqual(verdict(self.seq[name]), 'BRK_SEQ_NOT_BUILT', name)                             # (A0; PR A: ok)

    def test_the_third_proof_b54s_own_schema_keeps_b54s_rule(self):
        b54 = b54_schema()
        self.assertFalse(set(B55_INPUTS) & set(b54['inputs']))
        ids = {rule['id'] for rule in applicable_rules(b54)}
        self.assertIn(NARROWED, ids)
        self.assertFalse(ids & set(B55_RULES))
        self.assertEqual(verdict(dict(self.single, Engine_Mode='0'), b54), 'BRK_WITHOUT_SINGLE')
        self.assertEqual(verdict(dict(self.single, Engine_Mode='0', Delay_Trade='0', Delay_Trade_Live='0'), b54), 'BRK_WITHOUT_SINGLE')
        self.assertEqual(verdict(self.single, b54), 'ok')
        self.assertEqual(verdict(self.pool, b54), 'ok')
        # Every b54-axes file and every pool file validates on this tree's schema exactly as on B54's (set-compatibility
        # rule 5: before any new guard is trusted).
        for folder in ('b54-axes', 'b54-pool'):
            files = sorted((ROOT / 'scripts' / 'fixtures' / folder).glob('*.set'))
            self.assertTrue(files, folder)
            for path in files:
                with self.subTest(file=folder + '/' + path.name):
                    values = read_values(path.read_bytes())
                    self.assertEqual(verdict(values), verdict(values, b54))


if __name__ == '__main__':
    unittest.main()
