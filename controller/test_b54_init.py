"""B54 PR A (docs/b54/BREAKOUT_ENTRIES_SPEC.md 4.6; Claude-Mac's ruling on GOAT-EA#303, condition 4): the controller half of
the synthetic axis SETs.

The pool has no `||Y` line, so gate 0's start/stop probes run nothing there. scripts/fixtures/b54-axes holds synthetic
optimisation SETs (never pool files): each is a complete SET at the schema's defaults on a valid single
(Engine_Single, Single_SL_ATR 1.0), with a breakout family on and its axes at Y. axes.json names, per SET, the rule the
EA reports at each probe (the SET's values, then each Y axis at its start and at its stop, the others at their values;
gate 0's item 5) and for the whole ladder (every rung of every axis; this module only, the EA runs one pass at a time).

Here the controller (validate_strategy, so EA_INIT_RULES over the reachable values) must give each probe and each ladder
exactly that rule; scripts/test_b54_init.cjs runs the same files through the EA's OnInit (b50_tick_harness), so the
mirror and the EA agree on the same files. N-bar and prior day have their signal terms, so a probe inside every bound is
'ok'; ORB_Breakout has none yet, so every ORB probe ends at ORB_BREAKOUT_NOT_BUILT, or earlier (it is the block's last line).
"""
import json
from pathlib import Path
import re
import unittest

from studio_ea_init_rules import EA_INIT_CODE, EA_INIT_RULES, EA_SOURCE
from studio_installation import contracts
from studio_strategy_settings import read_values, validate_strategy
from studio_template_tools import schema_default

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / 'scripts' / 'fixtures' / 'b54-axes'
TABLE = json.loads((DIR / 'axes.json').read_text(encoding='utf-8'))
SCHEMA = contracts('1.49')[0]
B54_LINES = range(5122, 5151)   # GOAT V1.49.mq5's b54-init block
AXES = ('BRK_TF_', 'BRK_Bars', 'BRK_Buffer_ATR', 'BRK_Once_Per_Level', 'ORB_TF_', 'ORB_Start_Minute', 'ORB_Range_Minutes',
        'ORB_Entry_Minutes', 'ORB_Buffer_ATR', 'ORB_Min_Range_ATR', 'ORB_Max_Range_ATR')


def render(entry, schema=SCHEMA):
    """The SET MT5 would read: every input in the schema's order, at the entry's value, else the base's, else the default."""
    lines = ['; GOAT B54 synthetic axis SET ' + entry['file'] + ' (scripts/fixtures/b54-axes/axes.json; not a pool file)']
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


def verdict(values):
    try:
        validate_strategy(values, SCHEMA)
    except ValueError as refusal:
        found = re.match(re.escape(EA_INIT_CODE) + r': .*? Rule (\w+) \(', str(refusal))
        if not found:
            raise
        return found[1]
    return 'ok'


class B54AxisSetTests(unittest.TestCase):
    def test_the_alerts_and_codes_are_the_eas(self):
        source = (ROOT / EA_SOURCE).read_text(encoding='utf-8-sig').split('\n')
        b54 = [rule for rule in EA_INIT_RULES if rule['lines'][0] in B54_LINES]
        self.assertEqual(len(b54), 14)
        self.assertEqual(TABLE['alerts'], {rule['id']: rule['alert'] for rule in b54})
        for rule in b54:
            line = source[rule['lines'][0]-1]
            self.assertIn('return ' + TABLE['codes'][rule['id']] + ';', line, rule['id'])

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

    def test_every_axis_is_at_y_and_every_range_rule_is_hit_at_a_probe(self):
        at_y = {name for entry in TABLE['sets'] for name, text in entry['lines'].items() if text.endswith('||Y')}
        self.assertEqual(at_y, set(AXES), 'PR A: each B54 axis at Y in some synthetic SET')
        hit = {rule for entry in TABLE['sets'] for rule in entry['probes'].values()}
        ranges = {'BRK_BARS_RANGE', 'BRK_BUFFER_RANGE', 'BRK_PRIOR_DAY_ON_D1', 'ORB_TF_NOT_M1_TO_H1', 'ORB_START_RANGE',
                  'ORB_RANGE_MINUTES', 'ORB_ENTRY_WINDOW', 'ORB_BUFFER_RANGE', 'ORB_RANGE_FILTER_NEGATIVE',
                  'ORB_RANGE_FILTER_ORDER'}
        self.assertLessEqual(ranges, hit)
        # Both ends: an axis refused at its start in one place and at its stop in another (or the same SET).
        for axis in ('BRK_Bars', 'BRK_Buffer_ATR'):
            ends = {probe.split('@')[1] for entry in TABLE['sets'] for probe, rule in entry['probes'].items()
                    if probe.startswith(axis + '@') and rule.endswith('_RANGE')}
            self.assertEqual(ends, {'start', 'stop'}, axis)


if __name__ == '__main__':
    unittest.main()
