"""Trading-equivalence certificate (closure diff, pinned allowlist, externals, resolution) and canary deal-list comparison.

Each Claude-Mac #141 finding has a negative control here (HIGH 1-3, MEDIUM 4-6, LOW 7)."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import studio_equivalence as eq

MAIN = '﻿#define   GOAT_BUILD_ID "V9.99-OLD-1"\r\n#define   GOAT_BUILD_MARKER "OLD1"\r\n#include "Inputs.mqh"\r\n#include "Trade.mqh"\r\n' \
       '#include "Panel.mqh"\r\n#include <Trade\\Trade.mqh>\r\n#resource "\\\\Indicators\\\\MACD - GOAT 2.ex5"\r\n#resource "Logo.png"\r\n' \
       '// #include "Ghost.mqh" is a comment, not a dependency\r\nint OnInit(){ string url="https://x//y"; return 0; }\r\n'
FILES = {
    'GOAT V1.49.mq5': MAIN,
    'Inputs.mqh': 'input double Risk=500.0; // per trade\r\nsinput int Magic=7;\r\ninput string Label="a;b";\r\n',
    'Trade.mqh': 'void Enter(){ if(DashboardTradeAllowBuy) trade.Buy(0.1); }\r\nint h=iCustom(_Symbol,PERIOD_M1,"MACD - GOAT 2",12,26);\r\n',
    'Panel.mqh': 'bool DashboardTradeAllowBuy=true;\r\nvoid Draw(){ if(!MQLInfoInteger(MQL_TESTER)) ObjectSetString(0,"lbl",OBJPROP_TEXT,"Hello"); }\r\n',
    'Unrelated.mqh': 'void Never(){ }\r\n',
}
PANEL_HI = FILES['Panel.mqh'].replace('Hello', 'Hi')
PANEL_TRADER = FILES['Panel.mqh'].replace('Hello', 'Hello, trader') + 'void Extra(){ }\r\n'
EXTERNALS = ['icustom:MACD - GOAT 2', 'include:<Trade\\Trade.mqh>', 'resource:\\Indicators\\MACD - GOAT 2.ex5']


def text_sha(text):
    return hashlib.sha256(eq.normalize(text.lstrip('﻿')).encode('utf-8')).hexdigest()


def receipt(panel_versions=(FILES['Panel.mqh'], PANEL_HI, PANEL_TRADER), logos=(b'\x89PNG', b'\x89PNG2')):
    return dict(schema='goat-non-trading-allowlist-receipt-v1', id='test-allowlist', review_ref='test',
                files={'Panel.mqh': dict(category='panel_ui', reviewed_sha256={text_sha(t): ['test'] for t in panel_versions}),
                       'Logo.png': dict(category='resource_image', reviewed_sha256={hashlib.sha256(b).hexdigest(): ['test'] for b in logos})},
                kept_in_scope={})


ALLOW = receipt()


def tree(root, changes=None, binary=b'\x89PNG'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    files = dict(FILES)
    files.update(changes or {})
    for name, text in files.items():
        if text is not None:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(text.encode('utf-8'))
    (root / 'Logo.png').write_bytes(binary)
    return root


def built(root, ea, build_id=None, *, compiler='c' * 64, externals=None):
    build = eq.resolve_build(None, source_dir=root)
    names = eq.closure(build['source'])['externals']
    hashes = {n: 'e' * 64 for n in eq.hashed_externals(names)} if externals is None else externals
    return build | dict(ea_sha256=ea, build_id=build_id or build['build_id'], compiler_sha256=compiler, externals_sha256=hashes)


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cert(self, new_changes=None, old_changes=None, allowlist=ALLOW, old_kw=None, new_kw=None, **kw):
        self.n = getattr(self, 'n', 0) + 1
        old = built(tree(self.root / ('old%d' % self.n), old_changes), 'a' * 64, **(old_kw or {}))
        new = built(tree(self.root / ('new%d' % self.n), new_changes, **kw), 'b' * 64, **(new_kw or {}))
        return eq.certificate(old, new, allowlist=allowlist)

    def test_closure_follows_includes_resources_and_inputs_not_comments(self):
        closure = eq.closure(eq.DirSource(tree(self.root / 'old')))
        self.assertEqual(sorted(closure['files']), ['GOAT V1.49.mq5', 'Inputs.mqh', 'Logo.png', 'Panel.mqh', 'Trade.mqh'])
        self.assertEqual(closure['externals'], EXTERNALS)
        self.assertEqual(closure['inputs'], [['input', 'double', 'Risk', '500.0'], ['sinput', 'int', 'Magic', '7'], ['input', 'string', 'Label', '"a;b"']])
        self.assertEqual(closure['missing'], [])

    def test_only_the_build_identity_differs_so_the_source_is_equivalent(self):
        main = MAIN.replace('V9.99-OLD-1', 'V9.99-NEW-2').replace('OLD1', 'NEW2').replace('\r\n', '\n')   # and LF line endings
        cert = self.cert({'GOAT V1.49.mq5': main})
        self.assertEqual((cert['source_status'], cert['source_equivalent']), ('pending_canary', True))
        self.assertEqual(cert['comparison']['differing'], [])
        self.assertEqual([n['id'] for n in cert['normalizations']], ['encoding', 'line_endings', 'build_id', 'build_marker'])
        eq.verify_certificate(cert)

    def test_a_trading_file_change_is_not_equivalent(self):
        cert = self.cert({'Trade.mqh': FILES['Trade.mqh'].replace('0.1', '0.2')})
        self.assertEqual(cert['source_status'], 'not_equivalent')
        self.assertEqual(cert['comparison']['blocking'], ['Trade.mqh'])
        item = cert['comparison']['differing'][0]
        self.assertEqual((item['allowlisted'], item['changed_lines'], item['blocking']), (None, 2, 'not on the non-trading allowlist'))

    def test_even_a_comment_change_in_a_trading_file_counts(self):
        self.assertEqual(self.cert({'Trade.mqh': FILES['Trade.mqh'] + '// note\r\n'})['source_status'], 'not_equivalent')

    def test_a_reviewed_allowlisted_ui_change_is_equivalent(self):
        cert = self.cert({'Panel.mqh': PANEL_TRADER}, binary=b'\x89PNG2')
        self.assertEqual(cert['source_status'], 'pending_canary')
        self.assertEqual(sorted(d['file'] for d in cert['comparison']['differing']), ['Logo.png', 'Panel.mqh'])
        self.assertEqual(cert['comparison']['blocking'], [])

    def test_high3_an_unreviewed_version_of_an_allowlisted_file_never_certifies(self):
        # Claude-Mac's probes: a trade-gating global flipped in the panel, and the tester exemption deleted.
        for changed in (FILES['Panel.mqh'].replace('DashboardTradeAllowBuy=true', 'DashboardTradeAllowBuy=false'),
                        FILES['Panel.mqh'].replace('if(!MQLInfoInteger(MQL_TESTER)) ', ''),
                        FILES['Panel.mqh'].replace('Hello', 'Howdy')):
            with self.subTest(changed=changed[:60]):
                cert = self.cert({'Panel.mqh': changed})
                self.assertEqual(cert['source_status'], 'not_equivalent')
                self.assertIn('is not in the reviewed receipt', cert['comparison']['differing'][0]['blocking'])
        unreviewed_logo = self.cert(binary=b'\x89PNG-new')
        self.assertIn('is not in the reviewed receipt', unreviewed_logo['comparison']['differing'][0]['blocking'])

    def test_the_guard_still_blocks_a_reviewed_version_that_trades(self):
        trading = FILES['Panel.mqh'] + 'void Close(){ PositionClose(1); }\r\n'
        cert = self.cert({'Panel.mqh': trading}, allowlist=receipt(panel_versions=(FILES['Panel.mqh'], trading)))
        self.assertEqual(cert['source_status'], 'not_equivalent')
        self.assertTrue(cert['comparison']['differing'][0]['guard_hits'])

    def test_medium4_allowlist_matches_the_full_path_not_the_basename(self):
        main = MAIN + '#include "ui/Panel.mqh"\r\n'
        cert = self.cert({'GOAT V1.49.mq5': main, 'ui/Panel.mqh': 'void X(){ HandleBiasExitBuy(1); }\r\n'},
                         old_changes={'GOAT V1.49.mq5': main, 'ui/Panel.mqh': 'void X(){ }\r\n'})
        item = next(d for d in cert['comparison']['differing'] if d['file'] == 'ui/Panel.mqh')
        self.assertEqual((item['allowlisted'], item['blocking']), (None, 'not on the non-trading allowlist'))

    def test_input_default_or_external_change_is_not_equivalent(self):
        cert = self.cert({'Inputs.mqh': FILES['Inputs.mqh'].replace('500.0', '250.0')})
        self.assertFalse(cert['comparison']['input_header_equal'])
        self.assertEqual(cert['comparison']['input_header_first_difference']['installed'], ['input', 'double', 'Risk', '250.0'])
        renamed = self.cert({'GOAT V1.49.mq5': MAIN.replace('MACD - GOAT 2.ex5', 'MACD - GOAT 3.ex5')},
                            new_kw=dict(externals={n.replace('GOAT 2.ex5', 'GOAT 3.ex5'): 'e' * 64 for n in EXTERNALS}))
        self.assertFalse(renamed['comparison']['externals_equal'])
        self.assertEqual(renamed['source_status'], 'not_equivalent')

    def test_medium5_externals_and_compiler_are_hashed_and_fail_closed(self):
        indicator = 'resource:\\Indicators\\MACD - GOAT 2.ex5'
        changed = self.cert(new_kw=dict(externals={n: ('f' * 64 if n == indicator else 'e' * 64) for n in EXTERNALS}))
        self.assertEqual((changed['source_status'], changed['comparison']['externals_hash_differs']), ('not_equivalent', [indicator]))
        missing = self.cert(old_kw=dict(externals={n: 'e' * 64 for n in EXTERNALS if n != 'include:<Trade\\Trade.mqh>'}))
        self.assertEqual(missing['source_status'], 'not_comparable')
        self.assertIn("no hash for external dependencies ['include:<Trade\\\\Trade.mqh>']", missing['problems'][0])
        compiler = self.cert(new_kw=dict(compiler='d' * 64))
        self.assertEqual((compiler['source_status'], compiler['comparison']['compiler_equal']), ('not_equivalent', False))
        unknown = self.cert(old_kw=dict(compiler=None))
        self.assertIn('compiler identity unknown', unknown['problems'][0])
        # A resource missing from the source tree is no longer silently "unversioned": it needs a hash too.
        runme = MAIN + '#resource "RunMe.ex5" as uchar RunMe[]\r\n'
        given = dict(externals={n: 'e' * 64 for n in EXTERNALS})
        absent = self.cert({'GOAT V1.49.mq5': runme}, old_changes={'GOAT V1.49.mq5': runme}, old_kw=given, new_kw=given)
        self.assertEqual(absent['source_status'], 'not_comparable')
        self.assertIn('resource-unversioned:RunMe.ex5', ' '.join(absent['problems']))

    def test_hash_externals_reads_the_mql5_tree_with_nested_includes(self):
        mql5 = self.root / 'MQL5'
        (mql5 / 'Include/Trade').mkdir(parents=True)
        (mql5 / 'Indicators').mkdir()
        (mql5 / 'Include/Trade/Trade.mqh').write_text('#include "OrderInfo.mqh"\n', encoding='utf-8')
        (mql5 / 'Include/Trade/OrderInfo.mqh').write_text('int a;\n', encoding='utf-8')
        (mql5 / 'Indicators/MACD - GOAT 2.ex5').write_bytes(b'macd')
        first = eq.hash_externals(mql5, EXTERNALS)
        self.assertEqual(sorted(first), EXTERNALS)
        self.assertEqual(first['resource:\\Indicators\\MACD - GOAT 2.ex5'], hashlib.sha256(b'macd').hexdigest())
        (mql5 / 'Include/Trade/OrderInfo.mqh').write_text('int b;\n', encoding='utf-8')   # a nested change moves the hash
        self.assertNotEqual(eq.hash_externals(mql5, EXTERNALS)['include:<Trade\\Trade.mqh>'], first['include:<Trade\\Trade.mqh>'])
        (mql5 / 'Indicators/MACD - GOAT 2.ex5').unlink()
        self.assertNotIn('resource:\\Indicators\\MACD - GOAT 2.ex5', eq.hash_externals(mql5, EXTERNALS))

    def test_a_new_file_in_scope_or_a_missing_include_blocks(self):
        cert = self.cert({'GOAT V1.49.mq5': MAIN + '#include "Unrelated.mqh"\r\n'})
        self.assertEqual(cert['comparison']['blocking'], ['GOAT V1.49.mq5', 'Unrelated.mqh'])
        added = next(d for d in cert['comparison']['differing'] if d['file'] == 'Unrelated.mqh')
        self.assertEqual(added['change'], 'added')
        missing = self.cert({'Trade.mqh': None})
        self.assertEqual(missing['source_status'], 'not_comparable')
        self.assertIn('unresolved files', ' '.join(missing['problems']))

    def test_unknown_source_is_not_comparable(self):
        old = dict(status='unknown', reason='The source of this build cannot be recovered', ea_sha256='a' * 64)
        cert = eq.certificate(old, built(tree(self.root / 'new'), 'b' * 64), allowlist=ALLOW)
        self.assertEqual((cert['source_status'], cert['source_equivalent']), ('not_comparable', None))

    def test_digest_detects_tampering(self):
        cert = self.cert()
        cert['source_status'] = 'active'
        with self.assertRaisesRegex(ValueError, 'digest'):
            eq.verify_certificate(cert)

    def test_reviewed_allowlist_receipt_pins_every_file_and_keeps_trading_files_out(self):
        allowlist = eq.load_allowlist()
        for name in ('GOAT V1.49.mq5', 'GOAT_Inputs_Definitions.mqh', 'NewsBiasFilter.mqh', 'GOATAIWireV2.mqh', 'GOAT_DirectionGuard.mqh',
                     'Optimizer.mqh', 'Tester.mqh', 'GOAT_SequenceExport.mqh', 'GOAT_DashboardAILaunchPolicy.mqh'):
            self.assertIsNone(eq.allowed(allowlist, name))
            self.assertIn(name, allowlist['kept_in_scope'])
        for path, entry in allowlist['files'].items():
            self.assertTrue(entry['reviewed_sha256'], path)
            self.assertTrue(all(len(h) == 64 for h in entry['reviewed_sha256']), path)
        self.assertEqual(eq.allowed(allowlist, 'dashboard.MQH')['path'], 'Dashboard.mqh')
        self.assertIsNone(eq.allowed(allowlist, 'ui/Dashboard.mqh'))


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which('git'), 'git is required for source resolution')
class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.repo = Path(self.tmp.name)
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.email', 't@example.invalid'); git(self.repo, 'config', 'user.name', 'test')
        git(self.repo, 'config', 'core.autocrlf', 'false')

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, changes=None, binary=None, message='c'):
        tree(self.repo, changes)
        if binary is not None:
            (self.repo / 'GOAT V1.49.ex5').write_bytes(binary)
        git(self.repo, 'add', '-A'); git(self.repo, 'commit', '-q', '-m', message)
        return git(self.repo, 'rev-parse', 'HEAD')

    def test_binary_hash_finds_the_commit_that_introduced_it(self):
        first = self.commit(binary=b'bin-old')
        self.commit({'Trade.mqh': FILES['Trade.mqh'].replace('0.1', '0.3')})   # source edited later, binary unchanged
        build = eq.resolve_build(self.repo, ea_sha256=hashlib.sha256(b'bin-old').hexdigest())
        self.assertEqual((build['status'], build['provenance'], build['commit'], build['build_id']), ('resolved', 'git_ex5_blob', first, 'V9.99-OLD-1'))
        self.assertIn('0.1', eq.decode(build['source'].read('Trade.mqh')))
        self.assertEqual(eq.resolve_build(self.repo, ea_sha256='c' * 64)['status'], 'unknown')

    def test_medium6_a_known_binary_never_falls_back_to_its_build_id_label(self):
        self.commit()
        self.assertEqual(eq.resolve_build(self.repo, build_id='V9.99-OLD-1')['status'], 'resolved')
        build = eq.resolve_build(self.repo, ea_sha256='c' * 64, build_id='V9.99-OLD-1')
        self.assertEqual(build['status'], 'unknown')
        self.assertIn('No recoverable source for binary', build['reason'])

    def test_build_id_must_name_one_source(self):
        first = self.commit()
        self.assertEqual(eq.resolve_build(self.repo, build_id='V9.99-OLD-1')['commit'], first)
        self.commit({'Trade.mqh': FILES['Trade.mqh'].replace('0.1', '0.4')})
        ambiguous = eq.resolve_build(self.repo, build_id='V9.99-OLD-1')
        self.assertEqual(ambiguous['status'], 'ambiguous')
        self.assertEqual(eq.resolve_build(self.repo, build_id='V0-NEVER')['status'], 'unknown')

    def test_candidate_identity_is_verified_against_its_compile_commit(self):
        head = self.commit()
        folder = self.repo / 'candidate-builds' / 'X1'
        folder.mkdir(parents=True)
        sources = {name: hashlib.sha256((self.repo / name).read_bytes()).hexdigest() for name in ('GOAT V1.49.mq5', 'Trade.mqh')}
        write = lambda value: (folder / 'identity.json').write_text(json.dumps(dict(build_id='V9.99-X1', binary=dict(sha256='d' * 64), **value)))
        write(dict(sources=sources))
        (folder / 'compile-receipt.json').write_text(json.dumps(dict(source_head=head, compiler_sha256='9' * 64)))
        build = eq.resolve_build(self.repo, ea_sha256='d' * 64)
        self.assertEqual((build['status'], build['provenance'], build['commit'], build['compiler_sha256']), ('resolved', 'candidate_identity', head, '9' * 64))
        write(dict(sources=dict(sources, **{'Trade.mqh': 'e' * 64})))
        refused = eq.resolve_build(self.repo, ea_sha256='d' * 64)
        self.assertEqual(refused['status'], 'unknown')
        self.assertIn('differs from the identity for Trade.mqh', ' '.join(refused['notes']))
        write(dict())   # MEDIUM 6: an identity without source hashes proves nothing
        empty = eq.resolve_build(self.repo, ea_sha256='d' * 64)
        self.assertEqual(empty['status'], 'unknown')
        self.assertIn('lists no source hashes', ' '.join(empty['notes']))


HEADER = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,profit,commission,fee,swap,deal_magic,join_basis'


def deals_csv(path, deals):
    rows = [HEADER, '1,1000,0,1,1,1,0,2,0,0.0,0.0,10000,0,0,0,0,balance']   # a balance deal is ignored
    rows += ['%d,%d,1,%d,%d,%d,0,%s,%s,%s,%s,0,0,0,0,1,known' % (i + 2, t, i, i, i, kind, entry, lots, price)
             for i, (t, kind, entry, lots, price) in enumerate(deals)]
    Path(path).write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return str(path)


DEALS = [(2000 + i, '0' if i % 2 == 0 else '1', '0' if i % 2 == 0 else '1', '0.05', '1.25117') for i in range(6)]


def set_deals(n):
    """Distinct deals per set (a canary set counts once)."""
    return [(t + n * 100000, *rest) for t, *rest in DEALS]


def canary_pairs(root, cert, count=10, *, drift=None, model=(4, 4), window=None, values=None, reference_ea=None, candidate_ea=None):
    result = []
    for n in range(count):
        reference = set_deals(n)
        candidate = list(reference)
        if drift == n:
            candidate[3] = candidate[3][:4] + ('1.25118',)
        result.append(dict(label='S%d' % n, values_sha256=(values or 'v%d') % n if '%' in (values or 'v%d') else values,
                           reference_deals=deals_csv(Path(root) / ('r%d.csv' % n), reference),
                           candidate_deals=deals_csv(Path(root) / ('c%d.csv' % n), candidate), reference_model=model[0], candidate_model=model[1],
                           reference_ea=reference_ea or cert['export_build']['ea_sha256'], candidate_ea=candidate_ea or cert['installed_build']['ea_sha256'],
                           reference_window=['2026-01-05', '2026-09-24 23:59'], candidate_window=window or ['2026-01-05', '2026-09-24 23:59']))
    return result


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        old = built(tree(self.root / 'old'), 'a' * 64)
        new = built(tree(self.root / 'new', {'Panel.mqh': PANEL_HI}), 'b' * 64)
        self.cert = eq.certificate(old, new, allowlist=ALLOW)
        self.assertEqual(self.cert['source_status'], 'pending_canary')
        self.controller = self.root / 'controller'
        eq.save_certificate(self.controller, self.cert)

    def tearDown(self):
        self.tmp.cleanup()

    def pairs(self, count=10, **kw):
        folder = self.root / ('p%d' % len(list(self.root.glob('p*'))))
        folder.mkdir()
        return canary_pairs(folder, self.cert, count, **kw)

    def status(self):
        return eq.state(self.controller, self.cert['digest'])['status']

    def test_deal_lists_compare_on_time_side_volume_and_price(self):
        same = eq.compare_deals(eq.deal_list(deals_csv(self.root / 'a.csv', DEALS)), eq.deal_list(deals_csv(self.root / 'b.csv', DEALS)))
        self.assertEqual((same['matched'], same['reference_deals']), (True, 6))
        noise = [d[:4] + ('1.2511700000000001',) if i == 0 else d for i, d in enumerate(DEALS)]
        self.assertFalse(eq.compare_deals(eq.deal_list(deals_csv(self.root / 'c.csv', noise)), eq.deal_list(self.root / 'a.csv'))['matched'])
        cut = eq.deal_list(self.root / 'a.csv', cut_msc=2003)
        self.assertEqual([d[0] for d in cut], [2000, 2001, 2002])

    def test_identical_deals_in_ten_distinct_sets_activate_the_certificate(self):
        self.assertEqual(self.status(), 'pending_canary')
        canary = eq.canary_result(self.cert, self.pairs())
        self.assertTrue(canary['matched'])
        self.assertIn('Identical deal lists in all 10 sets', canary['plain'])
        eq.save_canary(self.controller, canary)
        state = eq.state(self.controller, self.cert['digest'])
        self.assertEqual((state['status'], state['active'], state['canary_digest'], state['canary_models']), ('active', True, canary['digest'], [4]))

    def test_high1_ten_sets_is_a_hard_floor(self):
        for low in (1, 9):
            with self.subTest(min_sets=low), self.assertRaisesRegex(ValueError, 'hard floor'):
                eq.canary_result(self.cert, self.pairs(count=1), min_sets=low)
        few = eq.canary_result(self.cert, self.pairs(count=4))
        self.assertEqual((few['matched'], few['refutes']), (False, False))
        eq.save_canary(self.controller, few)
        self.assertEqual(self.status(), 'pending_canary')
        # A stored record claiming matched with a lower floor is re-derived from its sets, not trusted.
        forged = dict(few, matched=True, min_sets=1)
        forged = forged | dict(digest=eq.digest_of({k: v for k, v in forged.items() if k not in ('digest', 'created_utc')}))
        eq.save_canary(self.controller, forged)
        self.assertEqual(self.status(), 'pending_canary')

    def test_codex_p1_repeated_sets_count_once(self):
        one = self.pairs(count=1)[0]
        repeated = [dict(one, label='S%d' % n) for n in range(10)]
        canary = eq.canary_result(self.cert, repeated)
        self.assertFalse(canary['matched'])
        self.assertIn('repeats a set already in this canary', canary['plain'])
        same_values = eq.canary_result(self.cert, self.pairs(values='same-values'))
        self.assertFalse(same_values['matched'])

    def test_high2_drift_refutes_even_beside_a_protocol_error_and_for_good(self):
        mixed = self.pairs(drift=4)
        mixed[7]['candidate_model'] = 1                      # a protocol error elsewhere must not mask the drift
        drift = eq.canary_result(self.cert, mixed)
        self.assertEqual((drift['matched'], drift['refutes'], drift['drift']), (False, True, ['S4']))
        first = drift['sets'][4]['first_difference']
        self.assertEqual((first['index'], first['reference']['price'], first['candidate']['price']), (3, '1.25117', '1.25118'))
        eq.save_canary(self.controller, drift)
        eq.save_canary(self.controller, eq.canary_result(self.cert, self.pairs()))   # a later clean canary
        self.assertEqual(self.status(), 'refuted')

    def test_an_empty_canary_never_certifies(self):
        # Claude-Mac #157: VerifyLicense gates OnInit, so two builds that both fail init trade nothing
        # and their equal-empty deal lists must never "match" into an active certificate.
        empty = deals_csv(self.root / 'empty.csv', [])
        all_empty = [dict(p, reference_deals=empty, candidate_deals=empty) for p in self.pairs()]
        canary = eq.canary_result(self.cert, all_empty)
        self.assertEqual((canary['matched'], canary['refutes'], canary['sets_with_trades']), (False, False, 0))
        self.assertIn('0 deals on both sides', canary['plain'])
        eq.save_canary(self.controller, canary)
        self.assertEqual(self.status(), 'pending_canary')
        # One empty set among eleven good ones still blocks: every set needs deals on both sides.
        mixed = self.pairs(count=11)
        mixed[5] = dict(mixed[5], reference_deals=empty, candidate_deals=empty)
        one_empty = eq.canary_result(self.cert, mixed)
        self.assertFalse(one_empty['matched'])
        eq.save_canary(self.controller, one_empty)
        self.assertEqual(self.status(), 'pending_canary')
        # A stored record forged to claim a match is re-derived from its sets and stays inactive.
        forged = dict(one_empty, matched=True, protocol_errors=[], sets=[dict(s, protocol_errors=[]) for s in one_empty['sets']])
        forged = forged | dict(digest=eq.digest_of({k: v for k, v in forged.items() if k not in ('digest', 'created_utc')}))
        eq.save_canary(self.controller, forged)
        self.assertEqual(self.status(), 'pending_canary')
        # A one-sided empty list is drift, not an empty set: it refutes.
        drifted = self.pairs()
        drifted[2] = dict(drifted[2], candidate_deals=empty)
        self.assertTrue(eq.canary_result(self.cert, drifted)['refutes'])

    def test_protocol_errors_and_incomplete_members_never_activate(self):
        model = eq.canary_result(self.cert, self.pairs(model=(4, 1)))
        self.assertFalse(model['matched'])
        self.assertIn('different or unknown tester models', model['plain'])
        window = eq.canary_result(self.cert, self.pairs(window=['2026-02-01', '2026-09-24 23:59']))
        self.assertIn('different or unknown windows', window['plain'])
        incomplete = eq.canary_result(self.cert, self.pairs(), incomplete=[dict(alias='C1', reason='failed')])
        self.assertFalse(incomplete['matched'])
        self.assertIn('did not finish', incomplete['plain'])

    def test_low7_each_deal_file_must_be_bound_to_its_binary(self):
        wrong_reference = eq.canary_result(self.cert, self.pairs(reference_ea='f' * 64))
        self.assertIn('reference deals not recorded as made by the export build', wrong_reference['plain'])
        wrong_candidate = eq.canary_result(self.cert, self.pairs(candidate_ea='a' * 64))
        self.assertIn('candidate deals not recorded as made by the installed build', wrong_candidate['plain'])
        self.assertFalse(wrong_candidate['matched'])

    def test_a_not_equivalent_certificate_never_activates(self):
        old = built(tree(self.root / 'o2'), 'a' * 64)
        new = built(tree(self.root / 'n2', {'Trade.mqh': FILES['Trade.mqh'].replace('0.1', '0.2')}), 'b' * 64)
        cert = eq.certificate(old, new, allowlist=ALLOW)
        eq.save_certificate(self.controller, cert)
        folder = self.root / 'ne'; folder.mkdir()
        eq.save_canary(self.controller, eq.canary_result(cert, canary_pairs(folder, cert)))
        self.assertEqual(eq.state(self.controller, cert['digest'])['status'], 'not_equivalent')

    def test_medium6_a_binary_certificate_never_covers_an_export_without_that_binary(self):
        state = eq.state(self.controller, self.cert['digest'])
        installed = self.cert['installed_build']['ea_sha256']
        self.assertTrue(eq.covers(state, export_ea_sha256='a' * 64, installed_ea_sha256=installed))
        self.assertFalse(eq.covers(state, export_build_id=self.cert['export_build']['build_id'], installed_ea_sha256=installed))
        self.assertFalse(eq.covers(state, export_ea_sha256='a' * 64, installed_ea_sha256='0' * 64))

    def test_store_is_create_only_and_checked(self):
        path = eq.save_certificate(self.controller, self.cert)   # same digest: idempotent
        record = json.loads(path.read_text(encoding='utf-8'))
        record['comparison']['blocking'] = ['x']
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'digest'):
            eq.state(self.controller, self.cert['digest'])
        with self.assertRaisesRegex(ValueError, '64 lowercase hex'):
            eq.state(self.controller, '../x')


if __name__ == '__main__':
    unittest.main()
