"""Profile-staged deploy writer (beta.25, goatai#1885 6033450916): golden bytes and invariants. Fixture-only.

G1: the writer's <expert> block equals the real BuildTemplate output for the B35-01 Kestrel SET.
G2: frozen writer bytes (controller/contracts/profile-fixtures/g2), which the beta.26 MQL writer must also produce.
G3: MT5's own saves of a child (Balanced35 VPS chart02.chr, T3 saved-native-E1.tpl) agree with the writer.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

import studio_demo_deploy as deploy
import studio_deploy_profile as profile
from studio_refusal import Refusal

FIXTURES = Path(__file__).resolve().parent / 'contracts' / 'profile-fixtures'
EA = 'GOAT-EA\\GOAT V1.49.ex5'
AI_OFF = dict(aiMode=0, aiThreshold=50, aiProtocol=2)
AI_ON = dict(aiMode=2, aiThreshold=50, aiProtocol=2)
DEPLOYMENT = '0123456789abcdef0123456789abcdef'
NONCE = 'Studio_MonitorRunPath=deploy=' + DEPLOYMENT
# Declared by V1.49 but omitted by WriteSet (the audit's omitted list) or added by CA41 (declared defaults).
V149_DECLARED_EXTRAS = {'Dashboard_Resume_Saved', 'Studio_MonitorRunPath', 'Studio_ReadOnlyMonitor', 'GOAT_FitnessRunNonce',
                        'Sequence_Export_Enabled', 'Sequence_Export_End', 'Sequence_Export_Id', 'Sequence_Export_Model',
                        'Sequence_Export_Start'}
OMITTED_DEFAULTS = {'Studio_ReadOnlyMonitor': 'false', 'Studio_MonitorRunPath': '', 'Dashboard_Resume_Saved': 'false'}


def fixture(name):
    return (FIXTURES / name).read_bytes()


def u16(text):
    return b'\xff\xfe' + text.encode('utf-16-le')


def chart_lines(raw):
    return profile.decode_chart(raw).split('\r\n')


class FixtureProvenanceTests(unittest.TestCase):
    def test_every_copied_evidence_file_is_byte_identical_to_its_cited_source(self):
        manifest = json.loads(fixture('manifest.json'))['fixtures']
        self.assertEqual(set(manifest), {'kestrel-b35-01.set', 'g1-buildtemplate-kestrel.tpl', 'g3-b35-chart02-mt5-saved.chr',
                                         'g3-t3-saved-native-e1.tpl', 'g3-b35-dashboard-rows.tsv'})
        for name, entry in manifest.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256(fixture(name)).hexdigest(), entry['sha256'])
        # The SHA-256 the proposal cites for the MT5-saved B35 child (43C28DA1...F460) and the G1 template (2EE0E0C6...).
        self.assertTrue(manifest['g3-b35-chart02-mt5-saved.chr']['sha256'].startswith('43c28da1'))
        self.assertTrue(manifest['g3-b35-chart02-mt5-saved.chr']['sha256'].endswith('f460'))
        self.assertTrue(manifest['g1-buildtemplate-kestrel.tpl']['sha256'].startswith('2ee0e0c6'))


class WriterGoldenTests(unittest.TestCase):
    def test_g1_the_expert_block_is_byte_for_byte_the_real_buildtemplate_output(self):
        template = fixture('g1-buildtemplate-kestrel.tpl').decode('ascii').split('\r\n')
        start, end = template.index('<expert>'), template.index('</expert>')
        written = profile.expert_block(EA, profile.effective_input_lines(fixture('kestrel-b35-01.set'), AI_OFF))
        self.assertEqual(written, template[start:end + 1])
        # ...and the staged chart holds exactly that block plus the deployment nonce as its last input.
        chart = chart_lines(profile.child_chart(dict(name='GOAT V1.49 EURUSD,M1_B35-01_Kestrel-Trend-Breakout.set', symbol='EURUSD',
                                                     raw=fixture('kestrel-b35-01.set')), EA, AI_OFF, DEPLOYMENT))
        self.assertEqual(chart[chart.index('<expert>'):chart.index('</expert>') + 1], written[:-2] + [NONCE] + written[-2:])
        self.assertIn('EA_Desc=R99475c1ec8ee7bd0b661', chart, 'EA_Desc (the order comment) is never touched')
        self.assertTrue(any(line.startswith('; PF=') for line in written), 'BuildTemplate keeps ; lines that hold =')

    def test_g2_every_case_is_byte_for_byte_the_frozen_golden(self):
        cases = json.loads(fixture('g2/cases.json'))
        self.assertGreaterEqual(len(cases['children']), 5)
        for case in cases['children']:
            with self.subTest(case=case['case']):
                written = profile.child_chart(dict(name=case['fileName'], symbol=case['symbol'], raw=fixture(case['set'])),
                                              case['eaRelativePath'], case['policy'], case['deploymentId'])
                self.assertEqual(written, fixture(case['chart']))
                self.assertEqual(hashlib.sha256(written).hexdigest(), case['chartSha256'])
        dashboard = cases['dashboard']
        self.assertEqual(profile.dashboard_chart(dashboard['symbol'], dashboard['eaRelativePath']), fixture(dashboard['chart']))

    def test_g2_the_whole_profile_and_its_state_file_are_the_frozen_golden(self):
        spec = json.loads(fixture('g2/cases.json'))['profile']
        members = [dict(name=m['fileName'], symbol=m['symbol'], raw=fixture(m['set'])) for m in spec['members']]
        files = profile.profile_files(spec['eaRelativePath'], spec['policy'], members, spec['deploymentId'])
        self.assertEqual(sorted(files), ['chart01.chr', 'chart02.chr', 'chart03.chr'])
        for name, raw in files.items():
            self.assertEqual(raw, fixture('g2/profile/' + name), name)
        state = deploy.state_bytes(dict(policy='\t'.join(str(spec['policy'][k]) for k in ('aiMode', 'aiThreshold', 'aiProtocol')),
                                        members=[dict(path=m['path'], name=m['fileName'], symbol=m['symbol'], strategy=m['strategy'])
                                                 for m in spec['members']]))
        self.assertEqual(state, fixture('g2/profile/dashboard_state.tsv'))
        self.assertEqual(profile.profile_name(spec['deploymentId']), spec['profileName'])
        # Every staged row starts unlinked: the dashboard writes cid/magic when it adopts the child.
        rows = profile.decode_set(state).split('\r\n')[1:-1]
        self.assertEqual([row.split('\t')[7:] for row in rows], [['0', '0'], ['0', '0']])

    def test_g3_mt5s_saved_b35_child_has_the_writers_frame_and_audit_equal_inputs(self):
        saved = profile.parse_chart(fixture('g3-b35-chart02-mt5-saved.chr'))
        ours = profile.parse_chart(profile.child_chart(dict(name='GOAT V1.48 EURUSD,M1_B35-01.set', symbol='EURUSD',
                                                            raw=fixture('kestrel-b35-01.set')), 'GOAT Experiment\\GOAT V1.48.ex5', AI_OFF,
                                                       DEPLOYMENT))
        self.assertEqual(saved['expert'], ours['expert'], 'name, path and expertmode=5 exactly as MT5 saved them')
        self.assertEqual({k: saved['chart'][k] for k in ('symbol', 'period_type', 'period_size')},
                         {k: ours['chart'][k] for k in ('symbol', 'period_type', 'period_size')})
        self.assertNotIn('id', ours['chart'], 'the writer leaves id= to MT5')
        expected, actual = profile.audit_inputs(ours['inputs']), profile.audit_inputs(saved['inputs'])
        # The staged child differs only by the deployment nonce, which adoption requires and settingsMatch pins.
        self.assertEqual((expected['Studio_MonitorRunPath'], actual['Studio_MonitorRunPath']), ('deploy=' + DEPLOYMENT, ''))
        expected['Studio_MonitorRunPath'] = ''
        for name, value in OMITTED_DEFAULTS.items():
            expected.setdefault(name, value)
        self.assertEqual(set(expected), set(actual))
        self.assertEqual([name for name in expected if not profile.audit_equal(name, expected[name], actual[name])], [])

    def test_g3_t3s_save_of_the_g1_template_shows_expertmode_4_and_audit_equal_inputs(self):
        saved = profile.parse_chart(fixture('g3-t3-saved-native-e1.tpl'))
        ours = profile.parse_chart(profile.child_chart(dict(name='GOAT V1.49 EURUSD,M1_B35-01.set', symbol='EURUSD',
                                                            raw=fixture('kestrel-b35-01.set')), EA, AI_OFF, DEPLOYMENT))
        # D2 evidence: applied as 5, saved as 4 on a terminal without AllowLiveTrading. The writer still emits 5 (D1).
        self.assertEqual((saved['expert']['expertmode'], ours['expert']['expertmode']), ('4', '5'))
        self.assertEqual({k: v for k, v in saved['expert'].items() if k != 'expertmode'},
                         {k: v for k, v in ours['expert'].items() if k != 'expertmode'})
        expected, actual = profile.audit_inputs(ours['inputs']), profile.audit_inputs(saved['inputs'])
        self.assertEqual((expected['Studio_MonitorRunPath'], actual['Studio_MonitorRunPath']), ('deploy=' + DEPLOYMENT, ''))
        expected['Studio_MonitorRunPath'] = ''
        self.assertEqual(set(actual) - set(expected), V149_DECLARED_EXTRAS - {'Studio_MonitorRunPath'})
        self.assertEqual([name for name in expected if not profile.audit_equal(name, expected[name], actual[name])], [])

    def test_g3_each_saved_rows_cid_is_its_chart_files_id(self):
        links = profile.saved_profile_links({'chart02.chr': fixture('g3-b35-chart02-mt5-saved.chr')}, fixture('g3-b35-dashboard-rows.tsv'))
        self.assertEqual(links, [dict(index=0, symbol='EURUSD', cid='55933097152258', magic='893668', chart='chart02.chr')])
        # A row naming a chart no saved file carries, or a chart of another symbol, is refused.
        other = fixture('g3-b35-dashboard-rows.tsv').replace('55933097152258'.encode('utf-16-le'), '55933097152259'.encode('utf-16-le'))
        with self.assertRaisesRegex(ValueError, 'no saved chart file carries'):
            profile.saved_profile_links({'chart02.chr': fixture('g3-b35-chart02-mt5-saved.chr')}, other)
        swapped = fixture('g3-b35-dashboard-rows.tsv').replace('\tEURUSD\t'.encode('utf-16-le'), '\tGBPUSD\t'.encode('utf-16-le'))
        with self.assertRaisesRegex(ValueError, 'is not row 0'):
            profile.saved_profile_links({'chart02.chr': fixture('g3-b35-chart02-mt5-saved.chr')}, swapped)
        # Staged (unlinked) rows name no chart yet.
        staged = profile.saved_profile_links({}, fixture('g2/profile/dashboard_state.tsv'))
        self.assertEqual([row['chart'] for row in staged], [None, None])


class WriterRuleTests(unittest.TestCase):
    def child(self, text, name='GOAT V1.49 EURUSD,M1_x.set', policy=AI_OFF, raw=None):
        raw = raw if raw is not None else u16('EA_Desc=t\r\n' + text)
        return chart_lines(profile.child_chart(dict(name=name, symbol=name.split(' ')[2].split(',')[0], raw=raw), EA, policy, DEPLOYMENT))

    def inputs(self, lines):
        return [line for line in lines[lines.index('<inputs>') + 1:lines.index('</inputs>')] if line not in ('EA_Desc=t', NONCE)]

    def test_encoding_is_utf16le_with_bom_and_crlf_and_every_chart_has_expertmode_5(self):
        raw = profile.child_chart(dict(name='GOAT V1.49 EURUSD,M1_x.set', symbol='EURUSD', raw=u16('EA_Desc=a\r\nA=1\r\n')), EA, AI_OFF, DEPLOYMENT)
        self.assertTrue(raw.startswith(b'\xff\xfe<\x00c\x00'))
        text = profile.decode_chart(raw)
        self.assertTrue(text.endswith('</chart>\r\n')); self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertNotIn('\r', text.replace('\r\n', ''))
        for chart in (raw, profile.dashboard_chart('EURUSD', EA)):
            self.assertEqual(re.findall(r'expertmode=\d+', profile.decode_chart(chart)), ['expertmode=5'])

    def test_no_written_chart_ever_carries_an_algo_switch_or_an_id(self):
        files = profile.profile_files(EA, AI_ON, [dict(name='GOAT V1.49 EURUSD,M1_a.set', symbol='EURUSD', raw=fixture('kestrel-b35-01.set')),
                                                  dict(name='GOAT V1.49 WS30,D1_b.set', symbol='WS30', raw=u16('Mode_Operation=9\r\nEA_Desc=b\r\nX=1\r\n'))],
                                      DEPLOYMENT)
        for name, raw in files.items():
            text = profile.decode_chart(raw)
            for forbidden in ('Enabled=', 'AllowLiveTrading', 'AllowDllImport', '\nid=', '[StartUp]'):
                self.assertNotIn(forbidden, text, name)

    def test_the_dashboard_is_chart01_with_the_six_preset_values_and_children_follow_in_plan_order(self):
        members = [dict(name='GOAT V1.49 GBPUSD,M1_a.set', symbol='GBPUSD', raw=u16('EA_Desc=a\r\n')),
                   dict(name='GOAT V1.49 USDJPY,H1_b.set', symbol='USDJPY', raw=u16('EA_Desc=b\r\n'))]
        files = profile.profile_files(EA, AI_OFF, members, DEPLOYMENT)
        self.assertEqual(list(files), ['chart01.chr', 'chart02.chr', 'chart03.chr'])
        dashboard = chart_lines(files['chart01.chr'])
        self.assertEqual(self.inputs(dashboard), ['Mode_Operation=8', 'Dashboard_Resume_Saved=true', 'Mode_Bias=1', 'Bias_Protocol=2',
                                                  'Bias_threshold=50', 'EA_Desc=GOAT Dashboard'])
        self.assertEqual(dashboard[1:4], ['symbol=GBPUSD', 'period_type=0', 'period_size=1'])
        self.assertEqual(chart_lines(files['chart03.chr'])[1:4], ['symbol=USDJPY', 'period_type=1', 'period_size=1'])
        self.assertEqual(profile.chart_file_name(101), 'chart101.chr')

    def test_periods_follow_mt5s_own_encoding_and_the_whole_token(self):
        for token, unit, count in (('M1', 0, 1), ('M5', 0, 5), ('H1', 1, 1), ('H4', 1, 4), ('D1', 1, 24)):
            with self.subTest(token=token):
                self.assertEqual(self.child('A=1', name='GOAT V1.49 EURUSD,' + token + '_x.set')[2:4],
                                 ['period_type=' + str(unit), 'period_size=' + str(count)])
        # The whole token, as the dashboard's adoption reads it (beta.24's TF() read two characters: M15 opened M1).
        self.assertEqual(profile.period_token('GOAT V1.49 EURUSD,H4.set'), 'H4')
        # M15 and M30 are read whole (never as M1) and refused in plain English until the B42 list adds them.
        for token in ('M15', 'M30'):
            with self.subTest(token=token), self.assertRaises(Refusal) as caught:
                profile.period_token('GOAT V1.49 EURUSD,' + token + '_x.set')
            self.assertEqual((caught.exception.code, caught.exception.fields['timeframe']), (profile.PERIOD_REFUSED, token))
            self.assertTrue(str(caught.exception).startswith("This portfolio has a timeframe the app can't deploy yet (" + token + ')'))
        self.assertEqual(profile.MT5_PERIODS['M15'], (0, 15))
        for name in ('GOAT V1.49 EURUSD,W1_x.set', 'GOAT V1.49 EURUSD,MN1_x.set', 'GOAT V1.49 EURUSD_x.set', 'GOAT V1.49 EURUSD,m1_x.set',
                     'GOAT V1.49 EURUSD,M10_x.set', 'GOAT V1.49 EURUSD,M1X_x.set', 'GOAT V1.49 EURUSD,_M1.set'):
            with self.subTest(name=name), self.assertRaisesRegex(Refusal, "^This portfolio has a timeframe the app can't deploy yet"):
                profile.period_token(name)

    def test_buildtemplate_line_rules_keep_comments_with_equals_and_trim_each_line(self):
        lines = self.inputs(self.child('; header without equals\r\n; PF=2.4\r\n=no key\r\n   Risk=500.0  \r\n\tA = b\t\r\n\r\nGrid=1'))
        self.assertEqual(lines, ['; PF=2.4', 'Risk=500.0', 'A = b', 'Grid=1'])
        crlf, lf = u16('EA_Desc=t\r\nA=1\r\nB=2\r\n'), u16('EA_Desc=t\nA=1\nB=2\n')
        self.assertEqual(self.child('', raw=crlf), self.child('', raw=lf))
        self.assertEqual(self.child('', raw=crlf), self.child('', raw='EA_Desc=t\r\nA=1\r\nB=2'.encode('utf-8')))
        self.assertEqual(self.child('', raw=crlf), self.child('', raw=b'\xef\xbb\xbfEA_Desc=t\nA=1\nB=2'))

    def test_lines_both_writers_could_read_differently_are_refused(self):
        for text, label in (('A=1\rB=2', 'lone CR'), ('A=1\r', 'lone CR at the end'), ('A=1\r\r\nB=2', 'CR before CRLF'), ('A=<b>', 'angle bracket'), ('A=1\x00', 'NUL'), ('A=\x07', 'control'),
                            ('A=1\u00a0', 'non-ASCII whitespace at the end'), ('; only comments\r\n', 'no inputs'), ('', 'empty')):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, 'SET_LINE_UNSUPPORTED|SET_NO_INPUTS'):
                self.child('', raw=u16(text))

    def test_the_ai_policy_matches_the_mql_self_test_vectors(self):
        source = ['Mode_Bias=1', 'Bias_threshold=60', 'Bias_Protocol=1', 'Mode_Bias_Trades=0', 'Mode_Bias_Exit=1', 'Mode_News=3',
                  'News_threshold=85', 'Risk=100']
        unchanged = ['Mode_Bias_Exit=1', 'Mode_News=3', 'News_threshold=85', 'Risk=100']
        self.assertEqual(profile.apply_ai_policy(source, 0, 75, 1), source)
        self.assertEqual(profile.apply_ai_policy(source, 99, 75, 1), source)
        self.assertEqual(profile.apply_ai_policy(source, 1, 75, 1), ['Mode_Bias=0', 'Bias_threshold=75', 'Bias_Protocol=1', 'Mode_Bias_Trades=0'] + unchanged)
        self.assertEqual(profile.apply_ai_policy(source, 2, 75, 1), ['Mode_Bias=2', 'Bias_threshold=75', 'Bias_Protocol=1', 'Mode_Bias_Trades=0'] + unchanged)
        self.assertEqual(profile.apply_ai_policy(['Risk=100'], 2, 60, 1), ['Risk=100', 'Mode_Bias=2', 'Bias_threshold=60', 'Bias_Protocol=1', 'Mode_Bias_Trades=0'])
        self.assertEqual(profile.apply_ai_policy(source, 2, 50, 2), ['Mode_Bias=2', 'Bias_threshold=50', 'Bias_Protocol=2', 'Mode_Bias_Trades=0'] + unchanged)
        self.assertEqual(profile.apply_ai_policy(source, 0, 50, 2), source)
        # Names are compared untrimmed, exactly like the MQL split: a padded name is not the policy input.
        self.assertEqual(profile.apply_ai_policy(['Mode_Bias =1'], 2, 50, 2),
                         ['Mode_Bias =1', 'Mode_Bias=2', 'Bias_threshold=50', 'Bias_Protocol=2', 'Mode_Bias_Trades=0'])

    def test_the_writer_applies_the_ai_policy_to_every_child(self):
        lines = self.inputs(self.child('Mode_Bias=1\r\nRisk=1', policy=dict(aiMode=2, aiThreshold=70, aiProtocol=2)))
        self.assertEqual(lines, ['Mode_Bias=2', 'Risk=1', 'Bias_threshold=70', 'Bias_Protocol=2', 'Mode_Bias_Trades=0'])

    def test_every_child_carries_the_deployment_nonce_and_nothing_else_changes(self):
        chart = self.child('Risk=1')
        inputs = chart[chart.index('<inputs>') + 1:chart.index('</inputs>')]
        self.assertEqual(inputs, ['EA_Desc=t', 'Risk=1', NONCE], 'appended last; EA_Desc (the order comment) untouched')
        # A SET carrying the input with its "" default is replaced in place; any other value is refused.
        inplace = self.child('', raw=u16('EA_Desc=t\r\nStudio_MonitorRunPath=\r\nRisk=1\r\n'))
        self.assertEqual(inplace[inplace.index('<inputs>') + 1:inplace.index('</inputs>')], ['EA_Desc=t', NONCE, 'Risk=1'])
        for raw, label in ((u16('EA_Desc=t\r\nStudio_MonitorRunPath=C:\\run\r\n'), 'a monitor run path'),
                           (u16('Studio_MonitorRunPath=\r\nStudio_MonitorRunPath=\r\n'), 'twice')):
            with self.subTest(label=label), self.assertRaises(Refusal) as caught:
                self.child('', raw=raw)
            self.assertEqual(caught.exception.code, profile.SET_NONCE_INPUT_REFUSED)
        for bad in ('E' * 32, 'e' * 31, None):
            with self.subTest(deployment=bad), self.assertRaises(ValueError):
                profile.deploy_nonce(bad)
        # A comment that mentions the input is not the input; the dashboard chart carries no nonce.
        self.assertIn('; Studio_MonitorRunPath=x', self.child('; Studio_MonitorRunPath=x\r\nRisk=1'))
        self.assertNotIn('deploy=', profile.decode_chart(profile.dashboard_chart('EURUSD', EA)))

    def test_unsafe_symbols_and_ea_paths_are_refused(self):
        for symbol in ('EUR USD', 'EUR<', '', 'x' * 65):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                profile.chart_text_lines(symbol, 'M1', EA, ['A=1'])
        for path in ('..\\GOAT.ex5', 'C:\\GOAT.ex5', 'GOAT-EA\\GOAT.ex4', 'GOAT-EA/GOAT V1.49.ex5', 'GOAT\r\n.ex5'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                profile.expert_identity(path)

    def test_audit_equal_duplicates_are_refused_and_distinct_members_pass(self):
        a = dict(name='GOAT V1.49 EURUSD,M1_a.set', symbol='EURUSD', raw=u16('EA_Desc=same\r\nRisk=500.0\r\nDownload_StartDate=2025.01.01\r\n'))
        b = dict(name='GOAT V1.49 EURUSD,M1_b.set', symbol='EURUSD', raw=u16('; another export\r\nEA_Desc=same\r\nRisk=500.00\r\n'
                                                                            'Download_StartDate=2025.01.01 00:00:00\r\n'))
        with self.assertRaises(Refusal) as caught:
            profile.refuse_duplicates([a, b], AI_OFF)
        self.assertEqual(caught.exception.code, profile.DUPLICATE_MEMBER_SETTINGS)
        self.assertEqual(str(caught.exception), 'Two members have identical settings on the same symbol and timeframe; remove one '
                                                '(GOAT V1.49 EURUSD,M1_a.set and GOAT V1.49 EURUSD,M1_b.set).')
        with self.assertRaisesRegex(Refusal, '^Two members have identical settings'):
            profile.refuse_duplicates([a, dict(a, name='GOAT V1.49 EURUSD,M1_copy.set')], AI_OFF)  # byte-identical SETs
        for changed in (dict(b, symbol='GBPUSD', name='GOAT V1.49 GBPUSD,M1_b.set'), dict(b, name='GOAT V1.49 EURUSD,M5_b.set'),
                        dict(b, raw=u16('EA_Desc=other\r\nRisk=500.0\r\nDownload_StartDate=2025.01.01\r\n'))):
            profile.refuse_duplicates([a, changed], AI_OFF)

    def test_audit_value_keys_reproduce_goatchildauditvalue(self):
        equal = [('Risk', '500.0', '500.000'), ('Risk', '-0.0', '0'), ('Risk', '+1.50', '1.5'), ('Risk', '.5', '0.5'),
                 ('Download_StartDate', '2025.01.01', '2025.01.01 00:00:00'), ('Download_StartDate', '2025.01.01 00:00', '2025.01.01 00:00:00'),
                 ('Mode', 'abc', 'abc')]
        different = [('EA_Desc', '001', '1'), ('Active_Time_ASIA', '01:30-11:00', '01:30-12:00'), ('Risk', '500.0', '500.00000000000001'),
                     ('Risk', '1e3', '1000'), ('Risk', '500', '501'), ('Mode', 'true', 'True'), ('Download_StartDate', '2025.01.01', '2025.01.02')]
        for name, left, right in equal:
            self.assertTrue(profile.audit_equal(name, left, right), (name, left, right))
        for name, left, right in different:
            self.assertFalse(profile.audit_equal(name, left, right), (name, left, right))


class StartupInvariantTests(unittest.TestCase):
    """D1: the deploy startup ini ALWAYS writes [Experts] Enabled=0, and no controller code path writes Enabled=1."""

    def test_the_startup_ini_has_exactly_one_enabled_line_and_it_is_off(self):
        raw = deploy.startup_config('GOAT-Deploy-0123456789abcdef')
        self.assertTrue(raw.startswith(b'\xff\xfe'))
        text = raw.decode('utf-16')
        self.assertEqual(text, '[Charts]\r\nProfileLast=GOAT-Deploy-0123456789abcdef\r\n[Experts]\r\nEnabled=0\r\nAccount=1\r\n')
        self.assertEqual(re.findall(r'(?im)^[ \t]*enabled[ \t]*=[^\r\n]*', text), ['Enabled=0'])
        self.assertNotIn('[StartUp]', text); self.assertNotIn('AllowLiveTrading', text)

    def test_no_controller_module_writes_enabled_1_or_allow_live_trading_1(self):
        root = Path(__file__).resolve().parent
        patterns = [re.compile(p, re.I) for p in (r'Enabled\s*=\s*1', r'[\'"]Enabled[\'"]\s*:\s*1\b', r'Enabled\s*=\s*[\'"]\s*\+',
                                                   r'AllowLiveTrading\s*=\s*1', r'[\'"]AllowLiveTrading[\'"]\s*:\s*1\b',
                                                   r'Enabled=1', r'enabled\s*=\s*True')]
        offenders = []
        for path in sorted(root.glob('*.py')):
            if path.name.startswith('test_'):
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if any(pattern.search(line) for pattern in patterns):
                    offenders.append(f'{path.name}:{number}: {line.strip()[:120]}')
        self.assertEqual(offenders, [])

    def test_the_deploy_modules_never_write_allow_live_trading(self):
        # D2: reported (read through the ini key), never written. Neither module holds an assignment of it.
        for name in ('studio_demo_deploy.py', 'studio_deploy_profile.py'):
            text = (Path(__file__).resolve().parent / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'AllowLiveTrading\s*=', name)


if __name__ == '__main__':
    unittest.main()
