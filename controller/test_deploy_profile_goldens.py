"""G4 goldens for the B44 MQL deploy-profile writer: the committed bytes are exactly what studio_deploy_profile writes.

scripts/test_profile_writer_goldens.cjs runs GOATDeployProfileWriter.mqh against the same files, so this test is
the Python half of the byte-equality proof (docs/operations/B44-DEPLOY-ALL-DESIGN.md, section 2). Fixture-only.
"""
import hashlib
import json
import unittest

import deploy_profile_goldens as goldens
import studio_deploy_profile as profile

FIXTURES = goldens.FIXTURES


def fixture(name):
    return (FIXTURES / name).read_bytes()


class G4GoldenTests(unittest.TestCase):
    def test_the_committed_g4_files_are_what_the_python_writer_emits_now(self):
        changed, extra = goldens.differences()
        self.assertEqual(changed, [], 'run controller/deploy_profile_goldens.py --write after a deliberate writer change')
        self.assertEqual(extra, [])

    def test_the_portfolios_cover_the_promised_matrix(self):
        cases = json.loads(fixture('g4/cases.json'))
        periods, modes, protocols, encodings, replaced = set(), set(), set(), set(), 0
        for spec in cases['portfolios']:
            modes.add(spec['policy']['aiMode'])
            if spec['policy']['aiMode']:
                protocols.add(spec['policy']['aiProtocol'])
            for member in spec['members']:
                periods.add(profile.period_token(member['fileName']))
                raw = fixture(member['set'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), member['setSha256'])
                encodings.add('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-bom' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
                replaced += b'Studio_MonitorRunPath=' in raw or 'Studio_MonitorRunPath='.encode('utf-16-le') in raw
        self.assertEqual(periods, {'M1', 'M5', 'H1', 'H4', 'D1'})
        self.assertEqual(modes, {0, 2})
        self.assertEqual(protocols, {1, 2})
        self.assertEqual(encodings, {'utf-16', 'utf-8-bom', 'utf-8'})
        self.assertGreaterEqual(replaced, 2, 'the nonce replaces a "" Studio_MonitorRunPath in place')

    def test_every_profile_file_is_hash_pinned_and_starts_unlinked(self):
        cases = json.loads(fixture('g4/cases.json'))
        for spec in cases['portfolios']:
            folder = 'g4/' + spec['case'] + '/'
            names = ['chart%02d.chr' % slot for slot in range(1, len(spec['members']) + 2)] + ['dashboard_state.tsv']
            self.assertEqual(sorted(spec['files']), sorted(names))
            for name, digest in spec['files'].items():
                raw = fixture(folder + name)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, folder + name)
                self.assertTrue(raw.startswith(b'\xff\xfe') and raw.endswith('\r\n'.encode('utf-16-le')), folder + name)
                text = raw[2:].decode('utf-16-le')
                self.assertNotIn('Enabled=', text)
                self.assertNotIn('AllowLiveTrading', text)
            nonce = 'Studio_MonitorRunPath=deploy=' + spec['deploymentId']
            dashboard = fixture(folder + 'chart01.chr')[2:].decode('utf-16-le')
            self.assertNotIn('Studio_MonitorRunPath', dashboard, 'chart01 carries no nonce')
            for slot in range(2, len(spec['members']) + 2):
                lines = fixture(folder + 'chart%02d.chr' % slot)[2:].decode('utf-16-le').split('\r\n')
                self.assertEqual(lines.count(nonce), 1)
                self.assertNotIn('Studio_MonitorRunPath=', [line for line in lines if line != nonce])
            rows = profile.decode_set(fixture(folder + 'dashboard_state.tsv')).split('\r\n')[1:-1]
            self.assertEqual([row.split('\t')[7:] for row in rows], [['0', '0']] * len(spec['members']))

    def test_every_refusal_case_names_the_python_verdict(self):
        cases = json.loads(fixture('g4/cases.json'))['refused']
        self.assertGreaterEqual(len(cases), 30)
        known = set(goldens.CODES) | {goldens.DECODE_REFUSED, goldens.VALUE_REFUSED}
        for case in cases:
            with self.subTest(label=case['label']):
                self.assertIn(case['code'], known)
        codes = {case['code'] for case in cases}
        self.assertEqual(codes, known, 'every refusal code is exercised')


if __name__ == '__main__':
    unittest.main()
