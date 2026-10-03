"""Trading-equivalence certificate (closure diff, allowlist, resolution) and canary deal-list comparison."""
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
    'Trade.mqh': 'void Enter(){ trade.Buy(0.1); }\r\nint h=iCustom(_Symbol,PERIOD_M1,"MACD - GOAT 2",12,26);\r\n',
    'Panel.mqh': 'void Draw(){ ObjectSetString(0,"lbl",OBJPROP_TEXT,"Hello"); }\r\n',
    'Unrelated.mqh': 'void Never(){ }\r\n',
}
ALLOW = dict(id='test-allowlist', files={'Panel.mqh': 'panel_ui', 'Logo.png': 'resource_image'}, kept_in_scope={})


def tree(root, changes=None, binary=b'\x89PNG'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    files = dict(FILES)
    files.update(changes or {})
    for name, text in files.items():
        if text is not None:
            (root / name).write_bytes(text.encode('utf-8'))
    (root / 'Logo.png').write_bytes(binary)
    return root


def built(root, ea, build_id=None):
    build = eq.resolve_build(None, source_dir=root)
    return build | dict(ea_sha256=ea, build_id=build_id or build['build_id'])


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cert(self, new_changes=None, old_changes=None, allowlist=ALLOW, **kw):
        self.n = getattr(self, 'n', 0) + 1
        old = built(tree(self.root / ('old%d' % self.n), old_changes), 'a' * 64)
        new = built(tree(self.root / ('new%d' % self.n), new_changes, **kw), 'b' * 64)
        return eq.certificate(old, new, allowlist=allowlist)

    def test_closure_follows_includes_resources_and_inputs_not_comments(self):
        closure = eq.closure(eq.DirSource(tree(self.root / 'old')))
        self.assertEqual(sorted(closure['files']), ['GOAT V1.49.mq5', 'Inputs.mqh', 'Logo.png', 'Panel.mqh', 'Trade.mqh'])
        self.assertEqual(closure['externals'], ['icustom:MACD - GOAT 2', 'include:<Trade\\Trade.mqh>', 'resource:\\Indicators\\MACD - GOAT 2.ex5'])
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

    def test_an_allowlisted_ui_change_is_equivalent(self):
        cert = self.cert({'Panel.mqh': FILES['Panel.mqh'].replace('Hello', 'Hello, trader') + 'void Extra(){ }\r\n'}, binary=b'\x89PNG2')
        self.assertEqual(cert['source_status'], 'pending_canary')
        self.assertEqual(sorted(d['file'] for d in cert['comparison']['differing']), ['Logo.png', 'Panel.mqh'])
        self.assertEqual(cert['comparison']['blocking'], [])

    def test_an_allowlisted_file_that_starts_trading_is_not_equivalent(self):
        for line in ('void Close(){ PositionClose(1); }', 'double v(){ return iMA(_Symbol,0,5,0,0,0); }', '#define FAST 9',
                     'input int Hidden=1;'):
            with self.subTest(line=line):
                cert = self.cert({'Panel.mqh': FILES['Panel.mqh'] + line + '\r\n'})
                self.assertEqual(cert['source_status'], 'not_equivalent')
                self.assertTrue(cert['comparison']['differing'][0]['guard_hits'])

    def test_input_default_or_external_change_is_not_equivalent(self):
        cert = self.cert({'Inputs.mqh': FILES['Inputs.mqh'].replace('500.0', '250.0')})
        self.assertFalse(cert['comparison']['input_header_equal'])
        self.assertEqual(cert['comparison']['input_header_first_difference']['installed'], ['input', 'double', 'Risk', '250.0'])
        changed = self.cert({'GOAT V1.49.mq5': MAIN.replace('MACD - GOAT 2.ex5', 'MACD - GOAT 3.ex5')})
        self.assertFalse(changed['comparison']['externals_equal'])
        self.assertEqual(changed['source_status'], 'not_equivalent')

    def test_a_new_file_in_scope_or_a_missing_include_blocks(self):
        cert = self.cert({'GOAT V1.49.mq5': MAIN + '#include "Unrelated.mqh"\r\n'})
        self.assertEqual(cert['comparison']['blocking'], ['GOAT V1.49.mq5', 'Unrelated.mqh'])
        added = next(d for d in cert['comparison']['differing'] if d['file'] == 'Unrelated.mqh')
        self.assertEqual(added['change'], 'added')
        missing = self.cert({'Trade.mqh': None})
        self.assertEqual(missing['source_status'], 'not_comparable')
        self.assertIn('unresolved files', missing['problems'][0])

    def test_unknown_source_is_not_comparable(self):
        old = dict(status='unknown', reason='The source of this build cannot be recovered', ea_sha256='a' * 64)
        cert = eq.certificate(old, built(tree(self.root / 'new'), 'b' * 64), allowlist=ALLOW)
        self.assertEqual((cert['source_status'], cert['source_equivalent']), ('not_comparable', None))

    def test_digest_detects_tampering(self):
        cert = self.cert()
        cert['source_status'] = 'active'
        with self.assertRaisesRegex(ValueError, 'digest'):
            eq.verify_certificate(cert)

    def test_reviewed_allowlist_never_lists_the_entrypoint_or_trading_files(self):
        for name in ('GOAT V1.49.mq5', 'GOAT_Inputs_Definitions.mqh', 'NewsBiasFilter.mqh', 'GOATAIWireV2.mqh', 'GOAT_DirectionGuard.mqh',
                     'Optimizer.mqh', 'Tester.mqh', 'GOAT_SequenceExport.mqh'):
            self.assertNotIn(name, eq.ALLOWLIST['files'])
            self.assertIn(name, eq.ALLOWLIST['kept_in_scope'])


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
        (folder / 'identity.json').write_text(json.dumps(dict(build_id='V9.99-X1', binary=dict(sha256='d' * 64), sources=sources)))
        (folder / 'compile-receipt.json').write_text(json.dumps(dict(source_head=head)))
        build = eq.resolve_build(self.repo, ea_sha256='d' * 64)
        self.assertEqual((build['status'], build['provenance'], build['commit']), ('resolved', 'candidate_identity', head))
        sources['Trade.mqh'] = 'e' * 64
        (folder / 'identity.json').write_text(json.dumps(dict(build_id='V9.99-X1', binary=dict(sha256='d' * 64), sources=sources)))
        refused = eq.resolve_build(self.repo, ea_sha256='d' * 64)
        self.assertEqual(refused['status'], 'unknown')
        self.assertIn('differs from the identity for Trade.mqh', ' '.join(refused['notes']))


HEADER = 'ordinal,server_time_msc,sequence_id,deal_id,order_id,position_id,sequence_direction,deal_type,deal_entry,lots,price,profit,commission,fee,swap,deal_magic,join_basis'


def deals_csv(path, deals):
    rows = [HEADER, '1,1000,0,1,1,1,0,2,0,0.0,0.0,10000,0,0,0,0,balance']   # a balance deal is ignored
    rows += ['%d,%d,1,%d,%d,%d,0,%s,%s,%s,%s,0,0,0,0,1,known' % (i + 2, t, i, i, i, kind, entry, lots, price)
             for i, (t, kind, entry, lots, price) in enumerate(deals)]
    Path(path).write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return str(path)


DEALS = [(2000 + i, '0' if i % 2 == 0 else '1', '0' if i % 2 == 0 else '1', '0.05', '1.25117') for i in range(6)]


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        old = built(tree(self.root / 'old'), 'a' * 64)
        new = built(tree(self.root / 'new', {'Panel.mqh': FILES['Panel.mqh'].replace('Hello', 'Hi')}), 'b' * 64)
        self.cert = eq.certificate(old, new, allowlist=ALLOW)
        self.controller = self.root / 'controller'
        eq.save_certificate(self.controller, self.cert)

    def tearDown(self):
        self.tmp.cleanup()

    def pairs(self, count=10, drift=None, model=(4, 4), window=None):
        result = []
        for n in range(count):
            reference = DEALS
            candidate = list(DEALS)
            if drift == n:
                candidate[3] = candidate[3][:4] + ('1.25118',)
            result.append(dict(label='S%d' % n, reference_deals=deals_csv(self.root / ('r%d.csv' % n), reference),
                               candidate_deals=deals_csv(self.root / ('c%d.csv' % n), candidate), reference_model=model[0], candidate_model=model[1],
                               reference_window=['2026-01-05', '2026-09-24 23:59'], candidate_window=window or ['2026-01-05', '2026-09-24 23:59']))
        return result

    def test_deal_lists_compare_on_time_side_volume_and_price(self):
        same = eq.compare_deals(eq.deal_list(deals_csv(self.root / 'a.csv', DEALS)), eq.deal_list(deals_csv(self.root / 'b.csv', DEALS)))
        self.assertEqual((same['matched'], same['reference_deals']), (True, 6))
        noise = [d[:4] + ('1.2511700000000001',) if i == 0 else d for i, d in enumerate(DEALS)]
        self.assertFalse(eq.compare_deals(eq.deal_list(deals_csv(self.root / 'c.csv', noise)), eq.deal_list(self.root / 'a.csv'))['matched'])
        cut = eq.deal_list(self.root / 'a.csv', cut_msc=2003)
        self.assertEqual([d[0] for d in cut], [2000, 2001, 2002])

    def test_identical_deals_in_ten_sets_activate_the_certificate(self):
        self.assertEqual(eq.state(self.controller, self.cert['digest'])['status'], 'pending_canary')
        canary = eq.canary_result(self.cert, self.pairs())
        self.assertTrue(canary['matched'])
        self.assertIn('Identical deal lists in all 10 sets', canary['plain'])
        eq.save_canary(self.controller, canary)
        state = eq.state(self.controller, self.cert['digest'])
        self.assertEqual((state['status'], state['active'], state['canary_digest']), ('active', True, canary['digest']))

    def test_one_deal_drift_refutes_for_good(self):
        eq.save_canary(self.controller, eq.canary_result(self.cert, self.pairs()))
        drift = eq.canary_result(self.cert, self.pairs(drift=4))
        self.assertEqual((drift['matched'], drift['refutes'], drift['drift']), (False, True, ['S4']))
        first = drift['sets'][4]['first_difference']
        self.assertEqual((first['index'], first['reference']['price'], first['candidate']['price']), (3, '1.25117', '1.25118'))
        eq.save_canary(self.controller, drift)
        self.assertEqual(eq.state(self.controller, self.cert['digest'])['status'], 'refuted')

    def test_too_few_sets_or_protocol_errors_do_not_activate(self):
        few = eq.canary_result(self.cert, self.pairs(count=4))
        self.assertEqual((few['matched'], few['refutes']), (False, False))
        model = eq.canary_result(self.cert, self.pairs(model=(4, 1)))
        self.assertFalse(model['matched'])
        self.assertIn('different or unknown tester models', model['plain'])
        window = eq.canary_result(self.cert, self.pairs(window=['2026-02-01', '2026-09-24 23:59']))
        self.assertIn('different or unknown windows', window['plain'])
        eq.save_canary(self.controller, few)
        self.assertEqual(eq.state(self.controller, self.cert['digest'])['status'], 'pending_canary')

    def test_a_not_equivalent_certificate_never_activates(self):
        old = built(tree(self.root / 'o2'), 'a' * 64)
        new = built(tree(self.root / 'n2', {'Trade.mqh': FILES['Trade.mqh'].replace('0.1', '0.2')}), 'b' * 64)
        cert = eq.certificate(old, new, allowlist=ALLOW)
        eq.save_certificate(self.controller, cert)
        eq.save_canary(self.controller, eq.canary_result(cert, self.pairs()))
        self.assertEqual(eq.state(self.controller, cert['digest'])['status'], 'not_equivalent')

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
