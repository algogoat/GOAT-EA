"""Keep the forward B50 candidate, and the retained B49a, B47, B46, B45, B44, B43, B41, B40, B39, B38, EX33, SM32, SM31 and SP30 ones, distinct from release artifacts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / 'candidate-builds/beta17-B50'
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
    def test_forward_candidate_binds_to_exact_source(self):
        identity = json.loads((CANDIDATE / 'identity.json').read_text(encoding='utf-8'))
        text = (ROOT / 'GOAT V1.49.mq5').read_text(encoding='utf-8-sig')
        self.assertIn('#define   GOAT_VERSION_LABEL "1.49"', text)
        self.assertIn('#define   GOAT_BUILD_ID "' + identity['build_id'] + '"', text)
        self.assertIn('#define   GOAT_BUILD_MARKER "' + identity['build_marker'] + '"', text)
        self.assertEqual((identity['build_id'], identity['build_marker']), ('V1.49-BETA17-50', 'B50'))
        self.assertEqual(identity['supersedes_candidate'], 'beta17-B49a')
        # B50 is B49a plus B50-alpha (goatai#2587, research only): the single-trade engine, D1 and the New York clock,
        # each in its own reviewed PR into claude-mac/b50-alpha. It differs from B49a in exactly the no-drift guard's
        # CHANGED and ADDED files, every changed line marked (scripts/test_b50_no_drift.cjs), and every source hashes to
        # the identity. The compile closure is B49a's plus ADDED.
        self.assertEqual(sorted(identity['consolidates']), ['B50.0', 'B50.0b', 'B50.1', 'B50.2', 'B50.3'])
        # B51 in progress (claude-mac/b50-beta1a, -beta1b): the tree is B50 plus marked B51 lines in the files
        # scripts/test_b51_no_drift.cjs lists, and every other B50 source is byte-identical (proven there, against B50's
        # commit). Those files carry B51's lines by design, so each is checked where it hashes to B50's identity: B50's
        # own commit (32df4eb, checked out with CRLF as .gitattributes does). The B51 assembly binds the tree to its own.
        b51_guard = (ROOT / 'scripts/test_b51_no_drift.cjs').read_text(encoding='utf-8')
        b51_changed = set(json.loads('[' + re.search(r"^const CHANGED=\[([^\]]*)\]", b51_guard, re.M)[1].replace("'", '"') + ']'))
        self.assertTrue({'GOAT V1.49.mq5', 'GOAT_Inputs_Definitions.mqh'} <= b51_changed)
        for relative, expected in identity['sources'].items():
            if relative not in b51_changed:
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
            else:
                blob = subprocess.run(['git', 'show', '32df4eb:' + relative], cwd=ROOT, capture_output=True, check=True).stdout
                blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, relative + ' (B50 commit)')
        b49a = json.loads((RETAINED_B49A / 'identity.json').read_text(encoding='utf-8'))
        b50_guard = (ROOT / 'scripts/test_b50_no_drift.cjs').read_text(encoding='utf-8')
        b50_list = lambda name: json.loads('[' + re.search(r"^const " + name + r"=\[([^\]]*)\]", b50_guard, re.M)[1].replace("'", '"') + ']')
        b50_changed, b50_added = b50_list('CHANGED'), b50_list('ADDED')
        self.assertEqual(sorted(name for name in identity['sources'] if identity['sources'][name] != b49a['sources'].get(name)), sorted(b50_changed + b50_added))
        self.assertEqual(sorted(identity['sources']), sorted(list(b49a['sources']) + b50_added), 'B49a closure plus ADDED')
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
        # B50 changes it again (12 appended inputs and TF_D1), so B50 batch packages carry B50's.
        sm32 = json.loads((RETAINED_SM32 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(b47['sources']['GOAT_Inputs_Definitions.mqh'], sm32['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(b49a['sources']['GOAT_Inputs_Definitions.mqh'], sm32['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertNotEqual(identity['sources']['GOAT_Inputs_Definitions.mqh'], b49a['sources']['GOAT_Inputs_Definitions.mqh'])
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
        for folder, marker, supersedes in ((RETAINED_B49A, 'B49a', 'beta17-B47'), (RETAINED_B47, 'B47', 'beta17-B46'), (RETAINED_B46, 'B46', 'beta17-B45'), (RETAINED_B45, 'B45', 'beta17-B44'), (RETAINED_B44, 'B44', 'beta17-B43'), (RETAINED_B43, 'B43', 'beta17-B41'), (RETAINED_B41, 'B41', 'beta17-B40'), (RETAINED_B40, 'B40', 'beta17-B39'), (RETAINED_B39, 'B39', 'beta17-B38'), (RETAINED_B38, 'B38', 'ea-experience-EX33'),
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
