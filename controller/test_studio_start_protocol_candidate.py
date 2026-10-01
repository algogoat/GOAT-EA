"""Keep the forward SP30 candidate distinct from retained release artifacts."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / 'candidate-builds/start-protocol-SP30'


class StartProtocolCandidateTests(unittest.TestCase):
    def test_candidate_binary_binds_to_exact_source_and_compile_result(self):
        identity = json.loads((CANDIDATE / 'identity.json').read_text(encoding='utf-8'))
        receipt = json.loads((CANDIDATE / 'compile-receipt.json').read_text(encoding='utf-8'))
        main = ROOT / 'GOAT V1.49.mq5'
        text = main.read_text(encoding='utf-8-sig')
        self.assertIn('#define   GOAT_VERSION_LABEL "1.49"', text)
        self.assertIn('#define   GOAT_BUILD_ID "' + identity['build_id'] + '"', text)
        self.assertIn('#define   GOAT_BUILD_MARKER "' + identity['build_marker'] + '"', text)
        self.assertEqual(identity['build_marker'], 'SP30')
        for relative, expected in identity['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)
        binary = CANDIDATE / 'GOAT V1.49.ex5'
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
        self.assertFalse(identity['native_qualified'])
        self.assertFalse(identity['customer_delivery'])
        policy = json.loads((ROOT / 'controller/contracts/v149/dependencies.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(policy['main_sha256'], identity['sources']['GOAT V1.49.mq5'])
        self.assertEqual(policy['header_sha256'], identity['sources']['GOAT_Inputs_Definitions.mqh'])
        retained = hashlib.sha256((ROOT / 'GOAT V1.49.ex5').read_bytes()).hexdigest()
        self.assertEqual(retained, '05acac509fd9aa0d84611cdb2b5d83b7dd23b0070ec910733e868568c8e95bd9')
        self.assertNotEqual(digest, retained)
        for record in (identity, receipt):
            serialized = json.dumps(record)
            self.assertNotIn('C:\\', serialized)
            self.assertNotIn('G:\\', serialized)
            self.assertNotIn('AppData', serialized)


if __name__ == '__main__':
    unittest.main()
