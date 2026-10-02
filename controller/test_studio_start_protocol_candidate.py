"""Keep the forward EX33 candidate, and the retained SM31 and SP30 ones, distinct from release artifacts."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / 'candidate-builds/ea-experience-EX33'
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
        self.assertEqual((identity['build_id'], identity['build_marker']), ('V1.49-EA-EXPERIENCE-33', 'EX33'))
        self.assertEqual(identity['supersedes_candidate'], 'ndx-symbol-map-SM31')
        for relative, expected in identity['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
        self.assertFalse(identity['native_qualified'])
        self.assertFalse(identity['customer_delivery'])
        policy = json.loads((ROOT / 'controller/contracts/v149/dependencies.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(policy['main_sha256'], identity['sources']['GOAT V1.49.mq5'])
        self.assertEqual(policy['header_sha256'], identity['sources']['GOAT_Inputs_Definitions.mqh'])
        # The pinned input header is unchanged from SM31, so saved batch packages stay valid.
        sm31 = json.loads((RETAINED_SM31 / 'identity.json').read_text(encoding='utf-8'))
        self.assertEqual(identity['sources']['GOAT_Inputs_Definitions.mqh'], sm31['sources']['GOAT_Inputs_Definitions.mqh'])
        self.assertEqual(hashlib.sha256((ROOT / 'GOAT V1.49.ex5').read_bytes()).hexdigest(), RETAINED_ROOT_BINARY)
        serialized = json.dumps(identity)
        for host in ('C:\\', 'G:\\', 'AppData'):
            self.assertNotIn(host, serialized)

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
        for folder, marker, supersedes in ((RETAINED_SM31, 'SM31', 'start-protocol-SP30'), (RETAINED, 'SP30', None)):
            identity = json.loads((folder / 'identity.json').read_text(encoding='utf-8'))
            receipt = json.loads((folder / 'compile-receipt.json').read_text(encoding='utf-8'))
            self.assertEqual(identity['build_marker'], marker)
            digest = hashlib.sha256((folder / 'GOAT V1.49.ex5').read_bytes()).hexdigest()
            self.assertEqual(digest, identity['binary']['sha256'])
            self.assertEqual(digest, receipt['output']['sha256'])
            if forward['binary'] is not None:
                self.assertNotEqual(digest, forward['binary']['sha256'])
            if supersedes:
                self.assertEqual(identity['supersedes_candidate'], supersedes)


if __name__ == '__main__':
    unittest.main()
