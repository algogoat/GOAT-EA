"""Function-level certificate units (studio_function_units) and the build externals manifest.

Negative controls for every fail-closed rule, a positive control where only an allowlisted UI
function differs, input/global defaults, trading-path functions hiding in a reviewed file, the
certificate integration and the compile-log externals manifest."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

import studio_equivalence as eq
import studio_function_units as fu

MAIN = '''#define GOAT_BUILD_ID "V9.99-OLD-1"
#define GOAT_FEATURE 1
#include "Panel.mqh"
input double Risk=500.0; // per trade
double g_lot=0.1;
CPng LOGO(data);
// the trading path
void Enter(double lots)
  {
   if(Risk>0) trade.Buy(lots);
  }
void Enter(int n)
  {
   Enter((double)n);
  }
void OnTick()
  {
   Enter(g_lot);
  }
// the panel
void DrawPanel(void)
  {
   ObjectSetString(0,"lbl",OBJPROP_TEXT,"Hello");
  }
class CDialog
  {
public:
   int m_x;
   void Paint(void) { DrawPanel(); }
  };
void OnChartEvent(const int id,const long &l,const double &d,const string &s)
  {
   CDialog dlg; dlg.Paint();
  }
'''
FILE = 'GOAT V1.49.mq5'


def units_of(text, **kw):
    return {u['key']: u for u in fu.parse_units(text, FILE, **kw)['units']}


def receipt(entries, confirmed=True):
    """A function allowlist receipt: entries = {key: (versions, extra)} for FILE."""
    units = {}
    for key, (texts, extra) in entries.items():
        hashes = {}
        for text in texts:
            hashes[units_of(text)[key]['sha256']] = ['test']
        units[key] = dict(category='panel_ui', reason='test review', reviewed_sha256=hashes, **(extra or {}))
    return dict(schema=fu.ALLOWLIST_SCHEMA, id='test-functions', confirmed=confirmed, units={FILE: units})


def compare(old, new, allowlist=None, *, extra_files=None):
    files_old = dict({FILE: old}, **(extra_files or {}))
    files_new = dict({FILE: new}, **(extra_files or {}))
    return fu.compare_texts(FILE, old, new, allowlist=allowlist or receipt({}),
                            old_graph=fu.call_graph(files_old, strict_files=(FILE,)),
                            new_graph=fu.call_graph(files_new, strict_files=(FILE,)))


DRAW = 'function DrawPanel(void)'
ENTER = 'function Enter(double lots)'
HI = MAIN.replace('"Hello"', '"Hi"')


class ParseTests(unittest.TestCase):
    def test_units_tile_the_file_and_have_stable_keys(self):
        result = fu.parse_units(MAIN, FILE)
        keys = [u['key'] for u in result['units']]
        for key in ('#define GOAT_BUILD_ID', '#define GOAT_FEATURE', '#include "Panel.mqh"', 'input Risk', 'global g_lot',
                    'declare LOGO(data)', ENTER, 'function Enter(int n)', 'function OnTick()', DRAW, 'class CDialog',
                    'method CDialog::Paint(void)', 'function OnChartEvent(const int id, const long &l, const double &d, const string &s)'):
            self.assertIn(key, keys)
        tiles = sorted((u for u in result['units'] if not u.get('inner')), key=lambda u: u['start'])
        self.assertEqual(''.join(MAIN[u['start']:u['end']] for u in tiles), MAIN)
        shell = units_of(MAIN)['class CDialog']['text']
        self.assertIn('<method CDialog::Paint(void)>', shell)
        self.assertNotIn('DrawPanel', shell)

    def test_the_tiling_check_catches_text_no_unit_holds(self):
        original = fu._add_gaps
        fu._add_gaps = lambda src, units: []   # simulate a parser that loses the text between units
        try:
            with self.assertRaisesRegex(fu.UnitParseError, 'do not tile the file'):
                fu.parse_units(MAIN, FILE)
        finally:
            fu._add_gaps = original

    def test_the_real_entrypoint_and_optimizer_parse(self):
        root = Path(__file__).resolve().parent.parent
        for name in (FILE, 'Optimizer.mqh'):
            path = root / name
            if not path.is_file():
                self.skipTest('no EA source next to the controller')
            result = fu.parse_units(eq.normalize(eq.decode(path.read_bytes())), name)
            kinds = {u['kind'] for u in result['units']}
            self.assertTrue({'function', 'directive', 'gap'} <= kinds, name)
            self.assertTrue(any(u['key'].startswith('event_map ') for u in result['units']), name)

    def fails(self, text, message):
        with self.assertRaisesRegex(fu.UnitParseError, message):
            fu.parse_units(text, FILE)

    def test_fail_closed_on_unbalanced_braces_and_literals(self):
        self.fails(MAIN + 'void Broken(){ if(x) {\n', 'unbalanced braces')
        self.fails(MAIN + '}\n', 'unbalanced closing brace')
        self.fails(MAIN + 'void F(){ Print("open); }\n', 'unterminated string')
        self.fails(MAIN + '/* never closed\n', 'unterminated block comment')
        self.fails(MAIN + 'double g_x=(1;\n', 'unterminated declaration')

    def test_fail_closed_on_conditionals_that_change_unit_boundaries(self):
        self.fails(MAIN + '#ifdef A\nvoid F(){\n#else\nvoid F(int a){\n#endif\n}\n', 'changes unit boundaries')
        self.fails(MAIN + 'void F(){\n#ifdef A\n if(x){\n#else\n if(y){\n#endif\n }\n}\n', 'another brace depth')
        self.fails(MAIN + '#ifdef A\nvoid F(){\n#endif\n}\n', 'changes unit boundaries')
        self.fails(MAIN + 'void F(){\n#endif\n}\n', 'opened outside this unit')
        self.fails(MAIN + 'void F(){\n#ifdef A\n}\n', 'still open at its end')
        self.fails(MAIN + '#ifdef A\nvoid F(){}\n', 'unclosed top-level conditional')
        self.fails(MAIN + 'double g_y=\n#ifdef A\n1\n#else\n2\n#endif\n;\n', 'directive inside a top-level declaration')
        # A conditional wholly inside a body, or around whole units, is fine and keyed.
        ok = units_of(MAIN + 'void F(){\n#ifdef A\n Print(1);\n#else\n Print(2);\n#endif\n}\n#ifdef B\nvoid G(){}\n#else\nvoid G(){}\n#endif\n')
        self.assertIn('[#ifdef B] function G()', ok)
        self.assertIn('[#ifdef B / #else] function G()', ok)

    def test_fail_closed_on_macros_that_can_define_functions(self):
        self.fails(MAIN + '#define MAKE(n) void n(){ }\n', 'could define a function')
        self.fails(MAIN + '#define STOP return;\n', 'could define a function')
        self.fails(MAIN + 'DECLARE_HANDLER(Foo) void Bar(){ }\n', 'unclassifiable')
        self.fails(MAIN + '#define WRAP(x) x\nWRAP(int) F(){ return 0; }\n', 'function-like macro WRAP')
        self.fails(MAIN + 'REGISTER(Foo);\nvoid Bar(){ }\n', 'unclassifiable')
        # The standard event map is the one accepted function-defining macro pair, in its exact shape.
        events = MAIN + 'EVENT_MAP_BEGIN(CDialog)\n ON_EVENT(ON_CLICK,m_btn,DrawPanel)\nEVENT_MAP_END(CAppDialog)\n'
        self.assertIn('event_map CDialog::OnEvent', units_of(events))
        self.fails(MAIN + 'EVENT_MAP_BEGIN(CDialog)\n ON_EVENT(ON_CLICK,m_btn,DrawPanel)\n', 'without EVENT_MAP_END')
        self.fails(MAIN + 'EVENT_MAP_BEGIN(CDialog)\n {\nEVENT_MAP_END(CAppDialog)\n}\n', 'inside an open brace')

    def test_fail_closed_on_directives_inside_bodies(self):
        self.fails(MAIN + 'void F(){\n#include "Other.mqh"\n}\n', '#include inside a function or class body')
        self.fails(MAIN + 'void F(){\n#define LOCAL 1\n}\n', '#define inside a function or class body')
        self.fails(MAIN + 'class C {\n#resource "x.png"\n};\n', '#resource inside')
        self.fails(MAIN + '#pragma once\n', 'unknown preprocessor directive')

    def test_fail_closed_on_duplicate_or_ambiguous_signatures(self):
        self.fails(MAIN + 'void DrawPanel(void)\n  {\n  }\n', 'duplicate unit function DrawPanel')
        self.fails(MAIN + 'void Enter(double size)\n  {\n  }\n', 'ambiguous signature')
        self.fails(MAIN + 'double g_lot=0.2;\n', 'duplicate unit global g_lot')
        overloads = units_of(MAIN)
        self.assertIn('function Enter(int n)', overloads)
        self.assertIn(ENTER, overloads)

    def test_fail_closed_on_unclassifiable_statements(self):
        self.fails(MAIN + 'if(x) { }\n', 'unclassifiable top-level statement|control statement')
        self.fails(MAIN + '{ int a; }\n', 'unclassifiable')
        self.fails(MAIN + 'struct { int a; } anon;\n', 'anonymous struct')


class CompareTests(unittest.TestCase):
    def test_positive_control_only_an_allowlisted_ui_function_differs(self):
        result = compare(MAIN, HI, receipt({DRAW: ((MAIN, HI), None)}))
        self.assertEqual((result['equivalent'], result['blocking'], result['layout']), (True, [], []))
        self.assertEqual([d['unit'] for d in result['differing']], [DRAW])
        item = result['differing'][0]
        self.assertEqual((item['allowlisted'], item['reachable_from_trading'], item['reachability_certain']), ('panel_ui', [], True))
        self.assertIn('OnChartEvent', item['reachable_from_lifecycle'])

    def test_an_unconfirmed_receipt_or_an_unreviewed_version_blocks(self):
        unconfirmed = compare(MAIN, HI, receipt({DRAW: ((MAIN, HI), None)}, confirmed=False))
        self.assertIn('not confirmed yet', unconfirmed['differing'][0]['blocking'])
        # Confirmation is per entry: a confirmed entry passes inside an unconfirmed receipt.
        entry = compare(MAIN, HI, receipt({DRAW: ((MAIN, HI), dict(confirmed=True, confirmed_ref='test'))}, confirmed=False))
        self.assertTrue(entry['equivalent'])
        unreviewed = compare(MAIN, MAIN.replace('"Hello"', '"Howdy"'), receipt({DRAW: ((MAIN, HI), None)}))
        self.assertIn('is not in the reviewed receipt', unreviewed['differing'][0]['blocking'])
        missing = compare(MAIN, HI)
        self.assertEqual(missing['differing'][0]['blocking'], 'not on the non-trading function allowlist')

    def test_a_changed_input_default_blocks_even_when_listed(self):
        changed = MAIN.replace('Risk=500.0', 'Risk=250.0')
        result = compare(MAIN, changed, receipt({'input Risk': ((MAIN, changed), None)}))
        self.assertFalse(result['equivalent'])
        self.assertEqual(result['differing'][0]['blocking'], 'input unit changed (never allowlistable)')
        added = compare(MAIN, MAIN.replace('double g_lot', 'input int Magic=7;\ndouble g_lot'))
        self.assertIn('input unit changed', next(d for d in added['differing'] if d['unit'] == 'input Magic')['blocking'])

    def test_a_changed_global_default_or_constructor_argument_blocks(self):
        changed = MAIN.replace('g_lot=0.1', 'g_lot=0.2')
        result = compare(MAIN, changed, receipt({'global g_lot': ((MAIN, changed), None)}))
        self.assertIn('never allowlistable', result['differing'][0]['blocking'])
        ctor = compare(MAIN, MAIN.replace('LOGO(data)', 'LOGO(other)'))
        self.assertFalse(ctor['equivalent'])

    def test_a_trading_path_function_change_blocks_even_inside_a_reviewed_file(self):
        # The panel function is reviewed and changes; a trading function in the same file changes too.
        both = HI.replace('trade.Buy(lots)', 'trade.Buy(lots*2)')
        result = compare(MAIN, both, receipt({DRAW: ((MAIN, HI, both), None)}))
        self.assertFalse(result['equivalent'])
        self.assertEqual(result['blocking'], [ENTER])
        enter = next(d for d in result['differing'] if d['unit'] == ENTER)
        self.assertEqual(enter['reachable_from_trading'], ['OnTick'])
        # Even listed, it needs trading_path_reviewed, and the GUARD still sees the order call.
        listed = compare(MAIN, both, receipt({DRAW: ((MAIN, HI, both), None), ENTER: ((MAIN, both), None)}))
        self.assertIn('touches trading', next(d for d in listed['differing'] if d['unit'] == ENTER)['blocking'])
        quiet = MAIN.replace('   if(Risk>0) trade.Buy(lots);', '   if(Risk>0) trade.Buy(lots);\n   Comment("x");')
        on_path = compare(MAIN, quiet, receipt({ENTER: ((MAIN, quiet), None)}))
        self.assertIn('trading_path_reviewed', on_path['differing'][0]['blocking'])
        acknowledged = compare(MAIN, quiet, receipt({ENTER: ((MAIN, quiet), dict(trading_path_reviewed=True))}))
        self.assertTrue(acknowledged['equivalent'])
        entry = MAIN.replace('   Enter(g_lot);', '   Enter(g_lot);\n   Comment("t");')
        root = compare(MAIN, entry, receipt({'function OnTick()': ((MAIN, entry), None)}))
        self.assertTrue(root['differing'][0]['trading_entry_point'])
        self.assertIn('trading_path_reviewed', root['differing'][0]['blocking'])

    def test_reachability_follows_macros_methods_and_is_uncertain_with_an_unparsed_file(self):
        via_macro = MAIN.replace('#define GOAT_FEATURE 1', '#define GOAT_FEATURE 1\n#define PAINT DrawPanel()').replace(
            '   Enter(g_lot);', '   Enter(g_lot); PAINT;')
        changed = via_macro.replace('"Hello"', '"Hi"')
        result = compare(via_macro, changed, receipt({DRAW: ((via_macro, changed), None)}))
        self.assertEqual(result['differing'][0]['reachable_from_trading'], ['OnTick'])
        self.assertIn('trading_path_reviewed', result['differing'][0]['blocking'])
        opaque = compare(MAIN, HI, receipt({DRAW: ((MAIN, HI), None)}), extra_files={'Broken.mqh': 'void X(){ \n'})
        item = opaque['differing'][0]
        self.assertFalse(item['reachability_certain'])
        self.assertIn('cannot rule out reaching', item['blocking'])

    def test_preprocessor_changes_and_layout_never_certify(self):
        flag = MAIN.replace('#define GOAT_FEATURE 1', '#define GOAT_FEATURE 1\n#define GOAT_NEW_FLAG 1')
        result = compare(MAIN, flag)
        self.assertIn('directive unit changed (never allowlistable)', next(d for d in result['differing'] if d['kind'] == 'directive')['blocking'])
        self.assertIn('the sequence of preprocessor lines changed', result['layout'])
        value = compare(MAIN, MAIN.replace('GOAT_FEATURE 1', 'GOAT_FEATURE 2'))
        self.assertFalse(value['equivalent'])
        reordered = MAIN.replace('input double Risk=500.0; // per trade\ndouble g_lot=0.1;\n', 'double g_lot=0.1;\ninput double Risk=500.0; // per trade\n')
        order = compare(MAIN, reordered, receipt({}))
        self.assertTrue(any('declaration order changed' in l for l in order['layout']))
        self.assertFalse(order['equivalent'])
        moved = MAIN.replace('#include "Panel.mqh"\n', '').replace('// the panel\n', '// the panel\n#include "Panel.mqh"\n')
        across = compare(MAIN, moved)
        self.assertFalse(across['equivalent'])

    def test_comment_gaps_are_reported_and_code_between_units_blocks(self):
        comment = MAIN.replace('// the panel', '// the panel, reworded')
        result = compare(MAIN, comment)
        self.assertTrue(result['equivalent'])
        self.assertTrue(result['differing'][0]['comment_or_whitespace_only'])
        stray = compare(MAIN, MAIN.replace('// the panel\n', '// the panel\n;\n'))
        self.assertIn('a token between units', stray['differing'][0]['blocking'])
        # Claude-Mac #157 answer 2: a changed gap passes only when BOTH versions normalise to empty, so a
        # comment edit next to an unchanged stray ';' still blocks.
        with_token = MAIN.replace('// the panel\n', '// the panel\n;\n')
        same_token = compare(with_token, with_token.replace('// the panel', '// the panel, reworded'))
        self.assertIn('a token between units', same_token['differing'][0]['blocking'])
        lined = MAIN.replace('ObjectSetString(0,"lbl",OBJPROP_TEXT,"Hello");', 'Print(__LINE__);')
        line_shift = compare(lined, lined.replace('// the panel', '// the panel\n// one more line'))
        self.assertIn('__LINE__', line_shift['differing'][0]['blocking'])
        inside = compare(MAIN, MAIN.replace('   Enter(g_lot);', '   Enter(g_lot); // note'))
        self.assertFalse(inside['equivalent'])   # inside a unit nothing is stripped

    def test_class_shell_and_inline_methods_are_separate_units(self):
        body = compare(MAIN, MAIN.replace('void Paint(void) { DrawPanel(); }', 'void Paint(void) { DrawPanel(); ChartRedraw(); }'))
        self.assertEqual([d['unit'] for d in body['differing']], ['method CDialog::Paint(void)'])
        field = compare(MAIN, MAIN.replace('   int m_x;', '   int m_x;\n   int m_y;'))
        self.assertEqual([d['unit'] for d in field['differing']], ['class CDialog'])

    def test_function_allowlist_receipt(self):
        record = fu.load_function_allowlist()
        self.assertIs(record['confirmed'], False)   # new entries need their own confirmation
        self.assertEqual(record['confirmation_required_from'], 'Claude-Mac')
        for file, units in record['units'].items():
            for key, entry in units.items():
                self.assertTrue(key.startswith(('function ', 'method ')), key)
                self.assertTrue(entry['reason'] and entry['category'], key)
                self.assertIn('5987995933', entry['confirmed_ref'], key)   # Claude-Mac's APPROVE on #157
        license = record['units'][FILE]['function VerifyLicense(long AccNum, string AccName, string AccServer, bool init = false)']
        self.assertIs(license['trading_path_reviewed'], True)   # it gates OnInit
        path = Path(tempfile.mkdtemp()) / 'r.json'
        for change, message in (({'function X()': dict(category='panel_ui', reviewed_sha256={})}, 'needs a category, a reason'),
                                ({'function X()': dict(category='panel_ui', reason='r', reviewed_sha256={'a' * 64: ['t']}, confirmed=True)},
                                 'confirmed without a confirmed_ref')):
            broken = copy.deepcopy(record)
            broken['units']['Optimizer.mqh'] = change
            path.write_text(json.dumps(broken), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, message):
                fu.load_function_allowlist(path)
        shutil.rmtree(path.parent)


# ---- certificate integration ---------------------------------------------------------------
def write_tree(root, main_text, optimizer='void Optimize(){ }\n'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / FILE).write_text(main_text.replace('#include "Panel.mqh"', '#include "Panel.mqh"\n#include "Optimizer.mqh"'), encoding='utf-8')
    (root / 'Panel.mqh').write_text('void PanelHelper(){ }\n', encoding='utf-8')
    (root / 'Optimizer.mqh').write_text(optimizer, encoding='utf-8')
    return root


def build(root, ea):
    resolved = eq.resolve_build(None, source_dir=root)
    return resolved | dict(ea_sha256=ea, compiler_sha256='c' * 64, externals_sha256={})


FILE_ALLOW = dict(schema='goat-non-trading-allowlist-receipt-v1', id='t', files={}, kept_in_scope={})


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cert(self, new_main, allowlist, optimizer_new='void Optimize(){ }\n'):
        old = build(write_tree(self.root / 'old', MAIN), 'a' * 64)
        new = build(write_tree(self.root / 'new', new_main, optimizer_new), 'b' * 64)
        return eq.certificate(old, new, allowlist=FILE_ALLOW, function_allowlist=allowlist)

    def main_key(self):
        return write_tree(self.root / 'probe', MAIN).joinpath(FILE).read_text(encoding='utf-8')

    def test_an_allowlisted_ui_change_in_the_entrypoint_certifies(self):
        main_old = self.main_key()
        main_new = main_old.replace('"Hello"', '"Hi"')
        allow = dict(schema=fu.ALLOWLIST_SCHEMA, id='t', confirmed=True, units={FILE: {DRAW: dict(
            category='panel_ui', reason='r', reviewed_sha256={units_of(t)[DRAW]['sha256']: ['t'] for t in (main_old, main_new)})}})
        cert = self.cert(HI, allow)
        self.assertEqual(cert['source_status'], 'pending_canary', cert['comparison'])
        item = cert['comparison']['differing'][0]
        self.assertEqual((item['file'], item['function_level']['equivalent']), (FILE, True))
        self.assertEqual(cert['function_level']['allowlist']['confirmed'], True)
        eq.verify_certificate(cert)

    def test_a_trading_change_or_a_parse_doubt_in_the_entrypoint_does_not(self):
        cert = self.cert(MAIN.replace('trade.Buy(lots)', 'trade.Buy(lots*2)'), fu.load_function_allowlist())
        self.assertEqual(cert['source_status'], 'not_equivalent')
        self.assertIn('function-level: 1 differing units block', cert['comparison']['differing'][0]['blocking'])
        doubt = self.cert(MAIN + 'void Broken(){ \n', fu.load_function_allowlist())
        self.assertEqual(doubt['source_status'], 'not_comparable')
        self.assertIn('function-level comparison of GOAT V1.49.mq5 is uncertain', doubt['problems'][0])
        optimizer = self.cert(MAIN, fu.load_function_allowlist(), optimizer_new='void Optimize(){ OrderSend(r,s); }\n')
        self.assertEqual(optimizer['comparison']['blocking'], ['Optimizer.mqh'])
        self.assertIn('function-level', optimizer['comparison']['differing'][0]['blocking'])


# ---- externals manifest --------------------------------------------------------------------
def sha(data):
    return hashlib.sha256(data).hexdigest()


class ExternalsManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.mql5 = self.root / 'MQL5'
        (self.mql5 / 'Include/Trade').mkdir(parents=True)
        (self.mql5 / 'Include/Controls/res').mkdir(parents=True)
        (self.mql5 / 'Indicators').mkdir()
        (self.mql5 / 'Include/Trade/Trade.mqh').write_text('#include "OrderInfo.mqh"\n', encoding='utf-8')
        (self.mql5 / 'Include/Trade/OrderInfo.mqh').write_text('int a;\n', encoding='utf-8')
        (self.mql5 / 'Include/Controls/Btn.mqh').write_text('#resource "res\\\\Up.bmp"\n', encoding='utf-8')
        (self.mql5 / 'Include/Controls/res/Up.bmp').write_bytes(b'bmp')
        (self.mql5 / 'Indicators/MACD - GOAT 2.ex5').write_bytes(b'macd')
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        main = ('#include <Trade\\Trade.mqh>\n#include <Controls\\Btn.mqh>\n#resource "\\\\Indicators\\\\MACD - GOAT 2.ex5"\n'
                '#ifdef SILENT\n#resource "RunMe.ex5" as uchar RunMe[]\n#endif\nvoid OnTick(){ }\n')
        (self.stage / FILE).write_text(main, encoding='utf-8')
        self.binary = self.root / 'GOAT V1.49.ex5'
        self.binary.write_bytes(b'ex5')
        self.compiler = self.root / 'MetaEditor64.exe'
        self.compiler.write_bytes(b'metaeditor')
        self.identity = self.root / 'identity.json'
        self.identity.write_text(json.dumps(dict(build_id='V9.99-X1', sources={FILE: sha((self.stage / FILE).read_bytes())},
                                                 binary=dict(sha256=sha(b'ex5')))), encoding='utf-8')
        self.receipt = self.root / 'compile-receipt.json'
        started = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() + 60)) + '.1234567Z'
        self.receipt.write_text(json.dumps(dict(source_head='f' * 40, compiler_sha256=sha(b'metaeditor'), compiler_version='5.0.0.6230',
                                                compile_started_at=started, output=dict(sha256=sha(b'ex5')))), encoding='utf-8')
        s, m = str(self.stage), str(self.mql5)
        lines = ['%s\\%s : information: compiling %s\\%s' % (s, FILE, s, FILE),
                 '%s\\%s : information: including \r\n%s\\Include\\Trade\\Trade.mqh' % (s, FILE, m),
                 '%s\\Include\\Trade\\Trade.mqh : information: including %s\\Include\\Trade\\OrderInfo.mqh' % (m, m),
                 '%s\\%s : information: including %s\\Include\\Controls\\Btn.mqh' % (s, FILE, m),
                 "%s\\Include\\Controls\\res\\Up.bmp : information: resource 'Up.bmp' as resource \"::res\\Up.bmp\"" % m,
                 "%s\\Indicators\\MACD - GOAT 2.ex5 : information: resource 'MACD - GOAT 2.ex5' as resource \"::Indicators\\MACD - GOAT 2.ex5\"" % m,
                 'Result: 0 errors, 0 warnings, 100 ms elapsed']
        self.log = self.root / 'compile.log'
        self.log.write_bytes('\r\n'.join(lines).encode('utf-16'))

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, **kw):
        return eq.externals_manifest(self.mql5, self.log, self.stage, binary=self.binary, identity=self.identity, receipt=self.receipt,
                                     compiler=self.compiler, **kw)

    def test_a_clean_compile_fingerprints_every_external_it_read(self):
        record = self.manifest()
        self.assertEqual(record['problems'], [])
        self.assertEqual(sorted(record['consumed']), ['Include/Controls/Btn.mqh', 'Include/Controls/res/Up.bmp', 'Include/Trade/OrderInfo.mqh',
                                                      'Include/Trade/Trade.mqh', 'Indicators/MACD - GOAT 2.ex5'])
        self.assertEqual(record['externals_sha256']['resource-unversioned:RunMe.ex5'], eq.NOT_CONSUMED)
        self.assertEqual(record['externals_sha256']['resource:\\Indicators\\MACD - GOAT 2.ex5'], sha(b'macd'))
        # the standard include hash now covers the bitmap its #resource embeds
        before = record['externals_sha256']['include:<Controls\\Btn.mqh>']
        (self.mql5 / 'Include/Controls/res/Up.bmp').write_bytes(b'bmp2')
        self.assertNotEqual(eq.hash_externals(self.mql5, ['include:<Controls\\Btn.mqh>'])['include:<Controls\\Btn.mqh>'], before)

    def test_every_doubt_is_a_problem(self):
        cases = []
        (self.stage / FILE).write_text((self.stage / FILE).read_text(encoding='utf-8') + '// edited\n', encoding='utf-8')
        cases.append(('differs from the identity', self.manifest()))
        self.setUp()
        self.binary.write_bytes(b'other')
        cases.append(('is not the identity/receipt binary', self.manifest()))
        self.setUp()
        self.compiler.write_bytes(b'other')
        cases.append(('is not the receipt compiler', self.manifest()))
        self.setUp()
        (self.mql5 / 'Include/Trade/OrderInfo.mqh').unlink()
        cases.append(('no longer in the MQL5 tree', self.manifest()))
        self.setUp()
        later = time.time() + 3600
        os.utime(self.mql5 / 'Include/Trade/Trade.mqh', (later, later))
        cases.append(('modified after the compile started', self.manifest()))
        self.setUp()
        self.log.write_bytes(self.log.read_bytes().decode('utf-16').replace('Result: 0 errors', 'Result: 2 errors').encode('utf-16'))
        cases.append(('no clean result line', self.manifest()))
        self.setUp()
        (self.mql5 / 'Include/Extra.mqh').write_text('int z;\n', encoding='utf-8')
        self.log.write_bytes((self.log.read_bytes().decode('utf-16') + '\r\n%s\\%s : information: including %s\\Include\\Extra.mqh'
                              % (self.stage, FILE, self.mql5)).encode('utf-16'))
        cases.append(('no per-name external hash covers', self.manifest()))
        for message, record in cases:
            with self.subTest(message=message):
                self.assertTrue(any(message in p for p in record['problems']), record['problems'])

    def test_the_certificate_consumes_the_manifest_and_compares_what_was_read(self):
        record = self.manifest()
        path = self.root / 'externals.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        loaded = eq.load_externals_manifest(path, binary_sha256=sha(b'ex5'), source_head='f' * 40)
        with self.assertRaisesRegex(ValueError, 'for another build'):
            eq.load_externals_manifest(path, binary_sha256='0' * 64)
        doubtful = dict(record, problems=['staged x differs from the identity'])
        doubtful = doubtful | dict(digest=eq.digest_of({k: v for k, v in doubtful.items() if k not in ('digest', 'created_utc')}))
        path.write_text(json.dumps(doubtful), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'records problems'):
            eq.load_externals_manifest(path)
        tampered = dict(record, consumed=dict(record['consumed'], **{'Include/Trade/Trade.mqh': '0' * 64}))
        path.write_text(json.dumps(tampered), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'digest'):
            eq.load_externals_manifest(path)
        old = eq.apply_externals_manifest(eq.resolve_build(None, source_dir=self.stage) | dict(ea_sha256='a' * 64), loaded, path)
        new = eq.apply_externals_manifest(eq.resolve_build(None, source_dir=self.stage) | dict(ea_sha256='b' * 64), copy.deepcopy(loaded), path)
        allow = dict(schema='goat-non-trading-allowlist-receipt-v1', id='t', files={}, kept_in_scope={})
        same = eq.certificate(old, new, allowlist=allow)
        self.assertEqual((same['source_status'], same['comparison']['externals_consumed_compared']), ('pending_canary', True))
        new['externals_consumed']['Include/Controls/res/Up.bmp'] = '1' * 64   # a bitmap the parser alone never sees
        moved = eq.certificate(old, new, allowlist=allow)
        self.assertEqual((moved['source_status'], moved['comparison']['externals_consumed_differs']), ('not_equivalent', ['Include/Controls/res/Up.bmp']))
        # "not consumed" is accepted only from a compile-log manifest
        bare = dict(old)
        bare.pop('externals_manifest')
        self.assertIn('marked not consumed without a compile-log externals manifest', ' '.join(eq.certificate(bare, new, allowlist=allow)['problems']))

    def test_not_consumed_holds_only_while_the_resource_cannot_compile(self):
        # Claude-Mac #157 answer 5: accept RunMe.ex5 as not consumed, but fail closed (not_comparable) as soon
        # as the source could compile it: its #ifdef macro gets defined, or the resource leaves the block.
        record = self.manifest()
        path = self.root / 'externals.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        allow = dict(schema='goat-non-trading-allowlist-receipt-v1', id='t', files={}, kept_in_scope={})
        main = (self.stage / FILE).read_text(encoding='utf-8')

        def cert_with(text):
            folder = self.root / ('s%d' % len(list(self.root.glob('s*'))))
            folder.mkdir()
            (folder / FILE).write_text(text, encoding='utf-8')
            build = lambda ea: eq.apply_externals_manifest(eq.resolve_build(None, source_dir=folder) | dict(ea_sha256=ea),
                                                           copy.deepcopy(record), path)
            return eq.certificate(build('a' * 64), build('b' * 64), allowlist=allow)

        self.assertEqual(cert_with(main)['source_status'], 'pending_canary')
        for text in ('#define SILENT\n' + main, main.replace('#ifdef SILENT\n', '').replace('#endif\n', ''),
                     main.replace('#ifdef SILENT', '#ifndef SILENT')):
            with self.subTest(text=text[:40]):
                cert = cert_with(text)
                self.assertEqual(cert['source_status'], 'not_comparable')
                self.assertIn('recorded as not consumed', ' '.join(cert['problems']))

    def test_an_explicit_manifest_is_bound_to_the_build_compiler(self):
        # Codex P2 on #157: the --*-externals route checks the compiler like resolve_build does.
        path = self.root / 'externals.json'
        path.write_text(json.dumps(self.manifest()), encoding='utf-8')
        build = dict(ea_sha256=sha(b'ex5'), commit='f' * 40, compiler_sha256='9' * 64)
        with self.assertRaisesRegex(ValueError, 'for another build'):
            eq.use_explicit_manifest(build, path)
        good = eq.use_explicit_manifest(dict(build, compiler_sha256=sha(b'metaeditor')), path)
        self.assertEqual(good['externals_manifest']['path'], str(path))

    @unittest.skipUnless(shutil.which('git'), 'git is required')
    def test_resolve_build_reads_externals_json_next_to_the_identity(self):
        repo = self.root / 'repo'
        shutil.copytree(self.stage, repo)
        run = lambda *a: subprocess.run(['git', '-C', str(repo), *a], capture_output=True, check=True, text=True).stdout.strip()
        run('init', '-q'); run('config', 'user.email', 't@example.invalid'); run('config', 'user.name', 't'); run('config', 'core.autocrlf', 'false')
        run('add', '-A'); run('commit', '-q', '-m', 'c')
        head = run('rev-parse', 'HEAD')
        folder = repo / 'candidate-builds' / 'X1'
        folder.mkdir(parents=True)
        shutil.copy(self.identity, folder / 'identity.json')
        receipt = json.loads(self.receipt.read_text(encoding='utf-8')) | dict(source_head=head)
        (folder / 'compile-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        manifest = self.manifest()
        (folder / 'externals.json').write_text(json.dumps(manifest), encoding='utf-8')
        # Claude-Mac #157 answer 7: only a manifest the compile receipt binds is used.
        unbound = eq.resolve_build(repo, ea_sha256=sha(b'ex5'))
        self.assertNotIn('externals_manifest', unbound)
        self.assertTrue(any('not bound by its compile receipt' in n for n in unbound['notes']))
        eq.bind_externals_manifest(folder / 'compile-receipt.json', manifest)
        with self.assertRaisesRegex(ValueError, 'already binds another'):
            eq.bind_externals_manifest(folder / 'compile-receipt.json', dict(manifest, digest='0' * 64))
        resolved = eq.resolve_build(repo, ea_sha256=sha(b'ex5'))
        self.assertEqual(resolved['status'], 'resolved')
        self.assertEqual(resolved['externals_manifest']['path'], str(folder / 'externals.json'))
        self.assertEqual(resolved['externals_sha256']['resource-unversioned:RunMe.ex5'], eq.NOT_CONSUMED)
        record = json.loads((folder / 'externals.json').read_text(encoding='utf-8'))
        record['source_head'] = '0' * 40
        (folder / 'externals.json').write_text(json.dumps(record), encoding='utf-8')
        ignored = eq.resolve_build(repo, ea_sha256=sha(b'ex5'))
        self.assertNotIn('externals_manifest', ignored)
        self.assertTrue(any('digest' in n or 'another build' in n for n in ignored['notes']))


if __name__ == '__main__':
    unittest.main()
