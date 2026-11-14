"""Keep the forward B55 candidate (demo candidate for the dashboard fixes), the retained B54 (research only), B53 (the experiments' final build), B52 (superseded, never installed), B51, B50, B49a, B47, B46, B45, B44, B43, B41, B40, B39, B38, EX33, SM32, SM31 and SP30 ones, distinct from release artifacts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / 'candidate-builds/beta17-B55'
RETAINED_B54 = ROOT / 'candidate-builds/beta17-B54'
RETAINED_B53 = ROOT / 'candidate-builds/beta17-B53'
RETAINED_B52 = ROOT / 'candidate-builds/beta17-B52'
RETAINED_B51 = ROOT / 'candidate-builds/beta17-B51'
RETAINED_B50 = ROOT / 'candidate-builds/beta17-B50'
RETAINED_B49A = ROOT / 'candidate-builds/beta17-B49a'
RETAINED_B47 = ROOT / 'candidate-builds/beta17-B47'
RETAINED_B46 = ROOT / 'candidate-builds/beta17-B46'
RETAINED_B45 = ROOT / 'candidate-builds/beta17-B45'
RETAINED_B44 = ROOT / 'candidate-builds/beta17-B44'
RETAINED_B43 = ROOT / 'candidate-builds/beta17-B43'
RETAINED_B41 = ROOT / 'candidate-builds/beta17-B41'
RETAINED_B40 = ROOT / 'candidate-builds/beta17-B40'
RETAINED_B39 = ROOT / 'candidate-builds/beta17-B39'
RETAINED_B38 = ROOT / 'candidate-builds/beta17-B38'
RETAINED_EX33 = ROOT / 'candidate-builds/ea-experience-EX33'
RETAINED_SM32 = ROOT / 'candidate-builds/terminal-isolation-SM32'
RETAINED_SM31 = ROOT / 'candidate-builds/ndx-symbol-map-SM31'
RETAINED = ROOT / 'candidate-builds/start-protocol-SP30'
RETAINED_ROOT_BINARY = '05acac509fd9aa0d84611cdb2b5d83b7dd23b0070ec910733e868568c8e95bd9'


class StartProtocolCandidateTests(unittest.TestCase):
    def test_forward_b55_candidate_binds_to_exact_source(self):
        # B55 (Claude-Mac goatai#2750 6853274219): the demo candidate for the dashboard bus fixes, B54 plus PR A0 (GOAT-EA#314,
        # BRK_Start_Seq refused as not built) and the dashboard fixes (#330). Demo candidate (the T2 reading, then the two kept
        # Exp 01 terminals), no live admission. It supersedes no candidate: B54 stays the research build, B53 the experiments'
        # final build. The tree IS B55: every source hashes to it, and its build ID and marker are the tree's.
        b55 = json.loads((CANDIDATE / 'identity.json').read_text(encoding='utf-8'))
        text = (ROOT / 'GOAT V1.49.mq5').read_text(encoding='utf-8-sig')
        self.assertIn('#define   GOAT_VERSION_LABEL "1.49"', text)
        self.assertIn('#define   GOAT_BUILD_ID "' + b55['build_id'] + '"', text)
        self.assertIn('#define   GOAT_BUILD_MARKER "' + b55['build_marker'] + '"', text)
        self.assertEqual((b55['build_id'], b55['build_marker']), ('V1.49-BETA17-55', 'B55'))
        self.assertIsNone(b55['supersedes_candidate'])
        self.assertEqual(b55['source_base'], 'a8c6766243ff577bdcfc90495a6de33ce0797c88', 'B55 is built on B54\'s commit')
        self.assertEqual(b55['consolidates'], ['B55.0', 'B55.d'])
        self.assertEqual(list(b55['consolidated_heads']), b55['consolidates'])
        for relative, expected in b55['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
        b54 = json.loads((RETAINED_B54 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b55['sources']), sorted(b54['sources']), 'same compile closure as B54')
        b55_guard = (ROOT / 'scripts/test_b55_no_drift.cjs').read_text(encoding='utf-8')
        b55_changed = json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b55_guard, re.M)[1].replace("'", '"') + ']')
        self.assertEqual(sorted(name for name in b55['sources'] if b55['sources'][name] != b54['sources'][name]), sorted(b55_changed),
                         'B55 differs from B54 in exactly the files scripts/test_b55_no_drift.cjs marks')
        self.assertFalse(b55['native_qualified'])
        self.assertFalse(b55['customer_delivery'])
        serialized = json.dumps(b55)
        for host in ('C:\\', 'G:\\', 'AppData'):
            self.assertNotIn(host, serialized)

    def test_retained_b54_binds_to_its_own_commit(self):
        # B54 (Claude-Mac goatai#2750 6781557904 item 1): the research build for breakout entries, B53 plus entry A
        # (GOAT-EA#304) and entry B (#305), its own identity. It supersedes no candidate: B53 stays the experiments' final
        # build, and B54 has no demo or live admission until Claude-Mac rules. Every source hashes to the tree.
        b54 = json.loads((RETAINED_B54 / 'identity.json').read_text(encoding='utf-8'))
        # B55 (the forward candidate) is B54 plus marked lines: the tree carries B55's identity, so B54's defines are checked
        # at its own commit through its sources below, not in the tree.
        self.assertEqual((b54['build_id'], b54['build_marker']), ('V1.49-BETA17-54', 'B54'))
        self.assertIsNone(b54['supersedes_candidate'])
        self.assertEqual(b54['source_base'], '216e16225441cfc1bfe0546c1c70adaf327405cf', 'B54 is built on B53\'s commit')
        self.assertEqual(b54['consolidates'], ['B54.s', 'B54.0', 'B54.A', 'B54.B'])
        self.assertEqual(list(b54['consolidated_heads']), b54['consolidates'])
        # B55 in progress (PR A0, docs/b55/BREAKOUT_SEQUENCE_SPEC.md): the tree is B54 plus marked B55 lines in the files
        # scripts/test_b55_no_drift.cjs lists, and every other B54 source is byte-identical (proven there, against B54's
        # commit). Those files carry B55's lines by design, so each is checked where it hashes to B54's identity: B54's own
        # commit (a8c6766, checked out with CRLF as .gitattributes does). The build ID and marker stay B54's until a B55
        # assembly binds the tree to its own identity.
        b55_guard = (ROOT / 'scripts/test_b55_no_drift.cjs').read_text(encoding='utf-8')
        b55_changed = set(json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b55_guard, re.M)[1].replace("'", '"') + ']'))
        self.assertTrue({'GOAT_Inputs_Definitions.mqh'} <= b55_changed)
        for relative, expected in b54['sources'].items():
            if relative not in b55_changed:
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
            else:
                blob = subprocess.run(['git', 'show', 'a8c6766:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
                blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B54 commit)')
        b53 = json.loads((RETAINED_B53 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b54['sources']), sorted(b53['sources']), 'same compile closure as B53')
        b54_guard = (ROOT / 'scripts/test_b54_no_drift.cjs').read_text(encoding='utf-8')
        b54_changed = json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b54_guard, re.M)[1].replace("'", '"') + ']')
        self.assertEqual(sorted(name for name in b54['sources'] if b54['sources'][name] != b53['sources'][name]), sorted(b54_changed),
                         'B54 differs from B53 in exactly the files scripts/test_b54_no_drift.cjs marks')
        self.assertFalse(b54['native_qualified'])
        self.assertFalse(b54['customer_delivery'])
        serialized = json.dumps(b54)
        for host in ('C:\\', 'G:\\', 'AppData'):
            self.assertNotIn(host, serialized)

    def test_forward_candidate_binds_to_exact_source(self):
        # B53, retained (B54 is the forward candidate): the experiments' final build, not superseded.
        identity = json.loads((RETAINED_B53 / 'identity.json').read_text(encoding='utf-8'))
        text = (ROOT / 'GOAT V1.49.mq5').read_text(encoding='utf-8-sig')
        self.assertIn('#define   GOAT_VERSION_LABEL "1.49"', text)
        self.assertEqual((identity['build_id'], identity['build_marker']), ('V1.49-BETA17-53', 'B53'))
        self.assertEqual(identity['supersedes_candidate'], 'beta17-B52')
        b53_receipt = json.loads((RETAINED_B53 / 'compile-receipt.json').read_text(encoding='utf-8'))
        self.assertNotIn('do_not_install', b53_receipt)
        self.assertNotIn('superseded_by', b53_receipt)
        # B53 is the final build (goatai#2750, GOAT-EA#296): B51 with GOAT-EA#292's follow-ups, merged with B49b (claude-pc/b49b
        # 808ff728, GOAT-EA#290), the fixes of two independent reads of that merge, #294's controller change, and Codex's three
        # fixes on GOAT-EA#296. Its own identity, because B52's binary refused every RiskperSeq single at OnInit (Codex
        # 4502334956) and a fixed tree is never pinned under an old build's name. Every source hashes to the tree.
        self.assertEqual(sorted(identity['consolidates']), ['B53.1', 'B53.2', 'B53.3', 'B53.4', 'B53.c1'])
        # B54 in progress (PR A0, docs/b54/BREAKOUT_ENTRIES_SPEC.md): the tree is B53 plus marked B54 lines in the files
        # scripts/test_b54_no_drift.cjs lists, and every other B53 source is byte-identical (proven there, against B53's
        # commit). Those files carry B54's lines by design, so each is checked where it hashes to B53's identity: B53's own
        # commit (216e1622, checked out with CRLF as .gitattributes does). A B54 assembly binds the tree to its own identity.
        b54_guard = (ROOT / 'scripts/test_b54_no_drift.cjs').read_text(encoding='utf-8')
        b54_changed = set(json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b54_guard, re.M)[1].replace("'", '"') + ']'))
        self.assertTrue({'GOAT_Inputs_Definitions.mqh'} <= b54_changed)
        # B55 (GOAT-EA#330, Codex 4559573813): a file only B55 changes (Dashboard.mqh's publish order) is B54's, and so
        # B53's, at B53's commit; its marked B55 lines are proven by scripts/test_b55_no_drift.cjs against B54's commit.
        b55_guard = (ROOT / 'scripts/test_b55_no_drift.cjs').read_text(encoding='utf-8')
        b55_changed = set(json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b55_guard, re.M)[1].replace("'", '"') + ']'))
        for relative, expected in identity['sources'].items():
            if relative not in (b54_changed | b55_changed):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
            else:
                blob = subprocess.run(['git', 'show', '216e1622:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
                blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B53 commit)')
        # B52 (retained, superseded: its compile receipt says do_not_install, and studio_installed_build pins no row for it).
        # Its sources hash to its own commit (a98ea439, checked out with CRLF as .gitattributes does); B53 differs from it in
        # exactly scripts/test_b51_no_drift.cjs's B52_LATER_CHANGED (the Codex fixes and B53's identity lines, marked there).
        b52 = json.loads((RETAINED_B52 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual((b52['build_id'], b52['build_marker']), ('V1.49-BETA17-52', 'B52'))
        self.assertEqual(b52['supersedes_candidate'], 'beta17-B51')
        self.assertEqual(sorted(b52['consolidates']), ['B52.1', 'B52.2', 'B52.3', 'B52.c1'])
        b52_receipt = json.loads((RETAINED_B52 / 'compile-receipt.json').read_text(encoding='utf-8'))
        self.assertIs(b52_receipt['do_not_install'], True)
        self.assertEqual(b52_receipt['superseded_by'], 'beta17-B53')
        for relative, expected in b52['sources'].items():
            blob = subprocess.run(['git', 'show', 'a98ea439:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
            blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B52 commit)')
        b52_later = json.loads('[' + re.search(r"^const B52_LATER_CHANGED=\[([^\]]*)\]", (ROOT / 'scripts/test_b51_no_drift.cjs').read_text(encoding='utf-8'), re.M)[1].replace("'", '"') + ']')
        self.assertEqual(sorted(name for name in identity['sources'] if identity['sources'][name] != b52['sources'].get(name)), sorted(b52_later))
        self.assertEqual(sorted(identity['sources']), sorted(b52['sources']), 'same compile closure as B52')
        # B49b (Track A, goatai#2587 6433828681) was built on B49a in reviewed PRs into claude-pc/b49b. B52 differs from B51 in
        # exactly the files B49b's guard lists as CHANGED (scripts/test_b49b_no_drift.cjs proves B49b's tree, and
        # scripts/test_b51_no_drift.cjs every changed line of this one, the build ID line its one allowance); its compile
        # closure is B51's.
        b51 = json.loads((RETAINED_B51 / 'identity.json').read_text(encoding='utf-8'))
        b49b_guard = (ROOT / 'scripts/test_b49b_no_drift.cjs').read_text(encoding='utf-8')
        b49b_changed = json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b49b_guard, re.M)[1].replace("'", '"') + ']')
        self.assertIn('GOAT V1.49.mq5', b49b_changed)
        self.assertEqual(sorted(name for name in b52['sources'] if b52['sources'][name] != b51['sources'].get(name)), sorted(b49b_changed))
        self.assertEqual(sorted(b52['sources']), sorted(b51['sources']), 'same compile closure as B51')
        # B51 is B50-alpha plus B50-beta-1 (goatai#2750, research only: the D1 hunt build): the random-direction benchmark,
        # the single's break-even, trailing and partial close and the demo gate (#286, #287, #289), with #291's controller
        # change, each in its own reviewed PR into claude-mac/b50-alpha. Its assembly (goatai#2750 6702775712) gave it its
        # own identity. It differs from B50 in exactly scripts/test_b51_no_drift.cjs's CHANGED files, its compile closure is
        # B50's, and its sources hash to its own commit (GOAT-EA#293 head b4844b2e, checked out with CRLF as .gitattributes does).
        self.assertEqual((b51['build_id'], b51['build_marker']), ('V1.49-BETA17-51', 'B51'))
        self.assertEqual(b51['supersedes_candidate'], 'beta17-B50')
        self.assertEqual(sorted(b51['consolidates']), ['B51.1a', 'B51.1b', 'B51.1c', 'B51.c1'])
        for relative, expected in b51['sources'].items():
            blob = subprocess.run(['git', 'show', 'b4844b2e:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
            blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B51 commit)')
        b50 = json.loads((RETAINED_B50 / 'identity.json').read_text(encoding='utf-8'))
        b51_guard = (ROOT / 'scripts/test_b51_no_drift.cjs').read_text(encoding='utf-8')
        b51_changed = json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b51_guard, re.M)[1].replace("'", '"') + ']')
        self.assertEqual(sorted(name for name in b51['sources'] if b51['sources'][name] != b50['sources'].get(name)), sorted(b51_changed))
        self.assertEqual(sorted(b51['sources']), sorted(b50['sources']), 'same compile closure as B50')
        # B50 is B49a plus B50-alpha (goatai#2587, research only): the single-trade engine, D1 and the New York clock,
        # each in its own reviewed PR into claude-mac/b50-alpha. It differs from B49a in exactly the no-drift guard's
        # CHANGED and ADDED files, every changed line marked (scripts/test_b50_no_drift.cjs), and its sources hash to its
        # own commit (32df4eb, checked out with CRLF as .gitattributes does). The compile closure is B49a's plus ADDED.
        self.assertEqual((b50['build_id'], b50['build_marker']), ('V1.49-BETA17-50', 'B50'))
        self.assertEqual(b50['supersedes_candidate'], 'beta17-B49a')
        self.assertEqual(sorted(b50['consolidates']), ['B50.0', 'B50.0b', 'B50.1', 'B50.2', 'B50.3'])
        for relative, expected in b50['sources'].items():
            blob = subprocess.run(['git', 'show', '32df4eb:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
            blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B50 commit)')
        b49a = json.loads((RETAINED_B49A / 'identity.json').read_text(encoding='utf-8'))
        b50_guard = (ROOT / 'scripts/test_b50_no_drift.cjs').read_text(encoding='utf-8')
        b50_list = lambda name: json.loads('[' + re.search(r"^const " + name + r"=\[([^\]]*)\]", b50_guard, re.M)[1].replace("'", '"') + ']')
        b50_changed, b50_added = b50_list('CHANGED'), b50_list('ADDED')
        self.assertEqual(sorted(name for name in b50['sources'] if b50['sources'][name] != b49a['sources'].get(name)), sorted(b50_changed + b50_added))
        self.assertEqual(sorted(b50['sources']), sorted(list(b49a['sources']) + b50_added), 'B49a closure plus ADDED')
        # B49a is B47 plus WEEKEND-1031 (goatai#2587): 64-bit tickets, B48's daily CID touch, F2 Ledger_Mode and F1-lite
        # restart adoption. It differs from B47 in exactly the B49a guard's CHANGED files, every changed line marked
        # (scripts/test_b49a_no_drift.cjs proves its commit, 65fde12).
        self.assertEqual(sorted(b49a['consolidates']), ['B49a.1', 'B49a.2', 'B49a.3', 'B49a.4'])
        b47 = json.loads((RETAINED_B47 / 'identity.json').read_text(encoding='utf-8'))
        guard = (ROOT / 'scripts/test_b49a_no_drift.cjs').read_text(encoding='utf-8')
        b49a_changed = json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", guard, re.M)[1].replace("'", '"') + ']')
        self.assertEqual(sorted(name for name in b49a['sources'] if b49a['sources'][name] != b47['sources'].get(name)), sorted(b49a_changed))
        self.assertEqual(sorted(b49a['sources']), sorted(b47['sources']), 'same compile closure as B47')
        # B47 is B46 plus Claude-Mac's B46 review items (goatai#2350): live-chart CID mappings, claim heartbeat expiry,
        # the cid_duplicate add freeze, an unreadable claim refuses, no claim under login 0. Only the entrypoint differs.
        self.assertEqual(sorted(b47['consolidates']), ['B47.1', 'B47.2', 'B47.3', 'B47.4', 'B47.5'])
        b46 = json.loads((RETAINED_B46 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in b47['sources'] if b47['sources'][name] != b46['sources'].get(name)), ['GOAT V1.49.mq5'])
        self.assertEqual(sorted(b49a['sources']), sorted(b46['sources']), 'same compile closure as B46')
        # B46 is B45 plus Claude-Mac's P1 from his B45 review (goatai#2350 6186284858): a missing CID record
        # (orphan_suspected) or a duplicate one (cid_duplicate) refuses new sequences. Only the entrypoint differs from B45.
        self.assertEqual(sorted(b46['consolidates']), ['B46.1', 'B46.2'])
        b45 = json.loads((RETAINED_B45 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in b46['sources'] if b46['sources'][name] != b45['sources'].get(name)), ['GOAT V1.49.mq5'])
        self.assertEqual(sorted(b49a['sources']), sorted(b45['sources']), 'same compile closure as B45')
        # B45 is B44 plus Claude-Mac's GOAT-EA#227 review follow-ups: BlindExport window parity with studio_window_metrics,
        # BOOS-free blind outputs (and trd_FOOS from dt_Fwrd_OOS), non-FOOS sizing for AdjustLots, the per-terminal magic salt.
        # Only the entrypoint differs from B44.
        self.assertEqual(sorted(b45['consolidates']), ['B45.1', 'B45.2', 'B45.3', 'B45.4'])
        b44 = json.loads((RETAINED_B44 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in b45['sources'] if b45['sources'][name] != b44['sources'].get(name)), ['GOAT V1.49.mq5'])
        self.assertEqual(sorted(b49a['sources']), sorted(b44['sources']), 'same compile closure as B44')
        # B44 is B43 plus the reviewed items of goatai#2350 (6126836633 / 6126880655, item 11 6127147178): child magic
        # from the chart id, AI wire fast retry, snapshot audit streaming and refusal reasons, the AI gate log, BlindExport,
        # the capture marks cap, the licence retry pin, the panel retry with no modal Alert in deploy mode, no window-handle
        # read, and FILE_SHARE_READ mailbox reads.
        self.assertEqual(sorted(b44['consolidates']), ['B44.1', 'B44.10', 'B44.11', 'B44.2', 'B44.3', 'B44.4', 'B44.5', 'B44.6', 'B44.7', 'B44.9'])
        b43 = json.loads((RETAINED_B43 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in b44['sources'] if b44['sources'][name] != b43['sources'].get(name)),
                         ['GOAT V1.49.mq5', 'GOATAIWireV2.mqh', 'GOATPortfolioChildAudit.mqh', 'GOATPortfolioSetupControl.mqh', 'GOATSetupControl.mqh', 'GOAT_SequenceExport.mqh'])
        self.assertEqual(sorted(b49a['sources']), sorted(b43['sources']), 'same compile closure as B43')
        # B43 is B41 plus the EA half of the beta.25 profile-staged deploy (goatai#1885 6033450916): the
        # dashboard adopts children MT5 loads from the staged profile (link_children), the template attach
        # path is deleted, deploy_next is refused and Activate/Deploy All are disabled; plus CA41 ported from
        # 4f3f2f9 (six WriteSet-omitted inputs on the audit's exemption list). B41.x (#186) was never merged.
        self.assertEqual(sorted(b43['consolidates']), ['CA41', 'PD43'])
        b41 = json.loads((RETAINED_B41 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b41['consolidates']), ['BR41'])
        # B43 differed from B41 only in the entrypoint (build ID, marker, gate line), the dashboard, the setup control and the child audit.
        self.assertEqual(sorted(name for name in b43['sources'] if b43['sources'][name] != b41['sources'].get(name)),
                         ['Dashboard.mqh', 'GOAT V1.49.mq5', 'GOATPortfolioChildAudit.mqh', 'GOATPortfolioSetupControl.mqh'])
        self.assertIn('"Sequence_Export_Enabled","Sequence_Export_Id","Sequence_Export_Start","Sequence_Export_End","Sequence_Export_Model","GOAT_FitnessRunNonce","BlindExport"',
                      (ROOT / 'GOATPortfolioChildAudit.mqh').read_text(encoding='utf-8-sig'))
        self.assertNotIn('ChartApplyTemplate', (ROOT / 'Dashboard.mqh').read_text(encoding='utf-8-sig'))
        # B41 is B40 plus the recorded-bias live gate (tester == live at every Bias_threshold,
        # goatai#1885). B40 is B39 plus the no-qualifying-rows research outcome (Banker g6-r1b). B39 is
        # B38 plus the broker facts for zero-click demo pairing (goatai#1885). B38 is EX33
        # plus FU35 (with its two fold-ins), PS37 and LC36's activation-code file: SM32's
        # isolation and EX33's outcome stay in the source.
        self.assertIn('#define GOAT_TERMINAL_ISOLATION_V149 1', text)
        self.assertIn('#define GOAT_RESEARCH_OUTCOME_V149 1', text)
        for flag in ('GOAT_STOP_CONFIRM_V149', 'GOAT_EVIDENCE_END_V149'):
            self.assertIn('#define ' + flag + '\n', text)
        for header in ('GOATEvidenceEnd.mqh', 'GOATTesterStopConfirm.mqh', 'GOATEADeviceActivation.mqh'):
            self.assertIn(header, identity['sources'])
        self.assertIn('#define GOAT_RECORDED_BIAS_LIVE_GATE_V149\n', text)
        self.assertIn('if(is_tester) return GOATRecordedBiasLiveScore(latest_score);', (ROOT / 'NewsBiasFilter.mqh').read_text(encoding='utf-8-sig'))
        b40 = json.loads((RETAINED_B40 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b40['consolidates']), ['NQ40'])
        # B41 differed from B40 only in the entrypoint (build ID, the flag and the tester pause), the wire header (the gate) and the reader.
        self.assertEqual(sorted(name for name in b41['sources'] if b41['sources'][name] != b40['sources'].get(name)),
                         ['GOAT V1.49.mq5', 'GOATAIWireV2.mqh', 'NewsBiasFilter.mqh'])
        self.assertIn('#define GOAT_XML_NO_QUALIFYING_ROWS "no_qualifying_rows"', (ROOT / 'XmlProcessor.mqh').read_text(encoding='utf-8-sig'))
        b39 = json.loads((RETAINED_B39 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b39['consolidates']), ['BF39'])
        # B40 differed from B39 only in the entrypoint (build ID and the deinit outcome branch), the report reader and the batch summary.
        self.assertEqual(sorted(name for name in b40['sources'] if b40['sources'][name] != b39['sources'].get(name)),
                         ['GOAT V1.49.mq5', 'Optimizer.mqh', 'XmlProcessor.mqh'])
        self.assertIn('GOATBrokerFactsJson("ea-device-start")', (ROOT / 'GOATEADeviceActivation.mqh').read_text(encoding='utf-8-sig'))
        b38 = json.loads((RETAINED_B38 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(b38['consolidates']), ['FU35', 'LC36', 'PS37'])
        # B39 differed from B38 only in the entrypoint (build ID and license-check payload) and the activation header.
        self.assertEqual(sorted(name for name in b39['sources'] if b39['sources'][name] != b38['sources'].get(name)),
                         ['GOAT V1.49.mq5', 'GOATEADeviceActivation.mqh'])
        self.assertFalse(identity['native_qualified'])
        self.assertFalse(identity['customer_delivery'])
        # The controller's input contract follows the tree (B49a and B50 each change the header).
        policy = json.loads((ROOT / 'controller/contracts/v149/dependencies.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(policy['main_sha256'], hashlib.sha256((ROOT / 'GOAT V1.49.mq5').read_bytes()).hexdigest())
        self.assertEqual(policy['header_sha256'], hashlib.sha256((ROOT / 'GOAT_Inputs_Definitions.mqh').read_bytes()).hexdigest())
        # B47's input header is SM32's, unchanged by EX33, B38, B39, B40, B41, B43, B44, B45, B46 and B47, so SM32 batch packages stay valid on B47.
        # B49a changes it (64-bit tickets; F2's input is appended), so B49a batch packages carry B49a's header pin.
        # B50 changes it again (12 appended inputs and TF_D1), so B50 batch packages carry B50's; B51 appends 9 more, so
        # B51 batch packages carry B51's; B52 has B49b's 9 between B50-alpha's and B51's, so B52 batch packages carry B52's.
        sm32 = json.loads((RETAINED_SM32 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(b47['sources']['GOAT_Inputs_Definitions.mqh'], sm32['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(b49a['sources']['GOAT_Inputs_Definitions.mqh'], sm32['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(b50['sources']['GOAT_Inputs_Definitions.mqh'], b49a['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(b51['sources']['GOAT_Inputs_Definitions.mqh'], b50['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(b52['sources']['GOAT_Inputs_Definitions.mqh'], b51['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertEqual(identity['sources']['GOAT_Inputs_Definitions.mqh'], b52['sources']['GOAT_Inputs_Definitions.mqh'], 'B53 keeps B52\'s input header')
        self.assertEqual(hashlib.sha256((ROOT / 'GOAT V1.49.ex5').read_bytes()).hexdigest(), RETAINED_ROOT_BINARY)
        serialized = json.dumps(identity)
        for host in ('C:\\', 'G:\\', 'AppData'):
            self.assertNotIn(host, serialized)

    def test_superseded_unadmitted_candidates_are_not_carried(self):
        # FU35, PS37 and LC36 were never admitted; only the consolidated B38 is a candidate here.
        for folder in ('ea-followups-FU35', 'panel-steady-PS37', 'local-pairing-code-LC36', 'setup-monitor-host-MH34'):
            self.assertFalse((ROOT / 'candidate-builds' / folder).exists(), folder)

    def test_forward_candidate_binary_is_pending_or_exactly_compiled(self):
        identity = json.loads((CANDIDATE / 'identity.json').read_text(encoding='utf-8'))
        binary, receipt_path = CANDIDATE / 'GOAT V1.49.ex5', CANDIDATE / 'compile-receipt.json'
        if identity['binary'] is None:
            # Compile not yet performed: no binary or receipt may be implied.
            self.assertEqual(identity['compile'], 'pending')
            self.assertFalse(binary.exists())
            self.assertFalse(receipt_path.exists())
            return
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        self.assertEqual(binary.stat().st_size, identity['binary']['bytes'])
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.assertEqual(digest, identity['binary']['sha256'])
        self.assertEqual(digest, receipt['output']['sha256'])
        self.assertEqual(receipt['source_sha256'], identity['sources']['GOAT V1.49.mq5'])
        self.assertEqual(receipt['staged_source_sha256'], receipt['source_sha256'])
        self.assertEqual(receipt['outcome'], 'COMPILE_OK')
        self.assertIn('0 errors, 0 warnings', receipt['result_line'])
        self.assertTrue(receipt['stage_cleaned'])
        self.assertFalse(receipt['runtime_output_overwritten'])
        self.assertNotEqual(digest, RETAINED_ROOT_BINARY)

    def test_retained_candidates_keep_their_own_exact_binaries(self):
        forward = json.loads((CANDIDATE / 'identity.json').read_text(encoding='utf-8'))
        for folder, marker, supersedes in ((RETAINED_B54, 'B54', None), (RETAINED_B53, 'B53', 'beta17-B52'), (RETAINED_B52, 'B52', 'beta17-B51'), (RETAINED_B51, 'B51', 'beta17-B50'), (RETAINED_B50, 'B50', 'beta17-B49a'), (RETAINED_B49A, 'B49a', 'beta17-B47'), (RETAINED_B47, 'B47', 'beta17-B46'), (RETAINED_B46, 'B46', 'beta17-B45'), (RETAINED_B45, 'B45', 'beta17-B44'), (RETAINED_B44, 'B44', 'beta17-B43'), (RETAINED_B43, 'B43', 'beta17-B41'), (RETAINED_B41, 'B41', 'beta17-B40'), (RETAINED_B40, 'B40', 'beta17-B39'), (RETAINED_B39, 'B39', 'beta17-B38'), (RETAINED_B38, 'B38', 'ea-experience-EX33'),
                                           (RETAINED_EX33, 'EX33', 'terminal-isolation-SM32'), (RETAINED_SM32, 'SM32', 'ndx-symbol-map-SM31'),
                                           (RETAINED_SM31, 'SM31', 'start-protocol-SP30'), (RETAINED, 'SP30', None)):
            identity = json.loads((folder / 'identity.json').read_text(encoding='utf-8'))
            self.assertEqual(identity['build_marker'], marker)
            if identity['binary'] is None:
                # A retained candidate whose compile commit has not landed yet (B40): nothing implied.
                self.assertEqual(identity['compile'], 'pending')
                self.assertFalse((folder / 'GOAT V1.49.ex5').exists())
                self.assertFalse((folder / 'compile-receipt.json').exists())
                self.assertEqual(identity['supersedes_candidate'], supersedes)
                continue
            receipt = json.loads((folder / 'compile-receipt.json').read_text(encoding='utf-8'))
            digest = hashlib.sha256((folder / 'GOAT V1.49.ex5').read_bytes()).hexdigest()
            self.assertEqual(digest, identity['binary']['sha256'])
            self.assertEqual(digest, receipt['output']['sha256'])
            if forward['binary'] is not None:
                self.assertNotEqual(digest, forward['binary']['sha256'])
            if supersedes:
                self.assertEqual(identity['supersedes_candidate'], supersedes)


if __name__ == '__main__':
    unittest.main()
