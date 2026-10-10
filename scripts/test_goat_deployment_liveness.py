"""Source regression guards; these do not simulate MT5 or prove native liveness.

beta.25 (goatai#1885 6033450916): the dashboard no longer opens child charts or applies templates, so the
template handshake these guards used to cover is deleted. They now guard the adoption that replaced it:
it is passive (no chart mutation), inert-only, and records its outcome in the deployment diagnostics.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHART_MUTATIONS = ('ChartSetSymbolPeriod(', 'ChartRedraw(', 'ChartApplyTemplate(', 'ChartOpen(', 'ChartClose(',
                   'ChartSetInteger(', 'ChartSetString(', 'ObjectCreate(', 'EventChartCustom(')


def region(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def passive(body):
    for forbidden in CHART_MUTATIONS:
        if forbidden in body:
            raise AssertionError('Chart mutation during child adoption: ' + forbidden)


class DeploymentLivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = (ROOT / 'Dashboard.mqh').read_text(encoding='utf-8-sig')
        cls.setup = (ROOT / 'GOATPortfolioSetupControl.mqh').read_text(encoding='utf-8-sig')
        cls.main = (ROOT / 'GOAT V1.48.mq5').read_text(encoding='utf-8-sig')
        cls.diagnostics = (ROOT / 'GOATDeploymentDiagnostics.mqh').read_text(encoding='utf-8-sig')
        cls.adoption = region(cls.setup, '// ---- Profile-staged deploy', 'string GoatPortfolioSnapshot(')
        cls.adopt_child = region(cls.dashboard, 'bool CGOATDashboard::AdoptChild(', 'void CGOATDashboard::ParsePortfolioFolderInfo(')

    def test_adoption_never_mutates_a_chart(self):
        passive(self.adoption)
        passive(self.adopt_child)
        for injected in ('ChartSetSymbolPeriod(adopt_chart,adopt_sym,adopt_period);', 'ChartRedraw(adopt_chart);',
                         'ChartApplyTemplate(adopt_chart,"x.tpl");', 'ChartOpen(adopt_sym,adopt_period);'):
            with self.assertRaises(AssertionError):
                passive(self.adoption + injected)
        # The only chart access is reading: symbol, period, expert name and one saved-template snapshot.
        self.assertEqual(sorted(set(re.findall(r'\b(Chart\w+)\(', self.adoption))),
                         ['ChartFirst', 'ChartGetString', 'ChartID', 'ChartNext', 'ChartPeriod', 'ChartSymbol'])
        self.assertIn('GoatChildChartSnapshot(', self.adoption)

    def test_adoption_has_no_wait_loop_or_sleep(self):
        for blocking in ('Sleep(', 'GetTickCount()', 'while('):
            self.assertNotIn(blocking, self.adoption)
            self.assertNotIn(blocking, self.adopt_child)
        self.assertIn('adopt_walked<1000', self.adoption)

    def test_adoption_is_inert_only_and_persists_before_it_counts(self):
        self.assertIn('if(!GoatAdoptInert() || adopt_rows<1 || ArraySize(adopt_hashes)!=adopt_rows) return 0;', self.adoption)
        inert = region(self.adoption, 'bool GoatAdoptInert(void)', 'void GoatAdoptNote(')
        for required in ('ACCOUNT_TRADE_MODE_DEMO', 'TERMINAL_CONNECTED', '!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)',
                         'PositionsTotal()==0', 'OrdersTotal()==0', '!MQLInfoInteger(MQL_TESTER)'):
            self.assertIn(required, inert)
        self.assertLess(self.adopt_child.index('if(!SaveDashboardConfig())'), self.adopt_child.index('g_sets[adopt_idx].status="Linked";'))
        self.assertLess(self.adopt_child.index('if(!SaveDashboardConfig())'), self.adopt_child.index('GlobalVariableDel('))

    def test_diagnostics_are_local_append_only_and_demo_scoped(self):
        d = self.diagnostics
        self.assertIn('#ifdef GOAT_DEPLOY_STARTUP_DIAGNOSTICS', d)
        self.assertIn('MQLInfoInteger(MQL_TESTER)', d)
        self.assertIn('ACCOUNT_TRADE_MODE_DEMO', d)
        self.assertIn('FILE_READ|FILE_WRITE', d)
        self.assertIn('FileSeek(h,0,SEEK_END)', d)
        self.assertIn('FileFlush(h)', d)
        self.assertIn('FileSize(h)<4194304', d)
        for forbidden in ('FILE_COMMON', 'FileDelete(', 'ChartGet', 'ObjectFind(', 'ChartSymbol(', 'ACCOUNT_LOGIN', 'AccountInfoString(', 'WebRequest('):
            self.assertNotIn(forbidden, d)
        # Adoption outcomes reach the same diagnostics, without SET paths.
        for phase in ('child_unmatched', 'child_identity_ambiguous', 'child_not_started'):
            self.assertIn('GoatAdoptNote("' + phase + '"', self.adoption)
        for phase in ('child_adopted', 'child_adopt_save_failed'):
            self.assertIn('GoatDeploymentPhase("' + phase + '"', self.adopt_child)
        self.assertNotIn('.path', region(self.adoption, 'void GoatAdoptNote(', 'bool GoatAdoptChartFits('))

    def test_panel_api_error_capture_precedes_diagnostic_io(self):
        controls = region(self.main, 'bool CPanelDialog::CreateBiEditRow(', '/*bool CPanelDialog::CreateBmpButton1')
        checked = [line for line in controls.splitlines() if 'if(!' in line and not line.lstrip().startswith('//')]
        self.assertEqual(11, len(checked))
        for line in checked:
            self.assertIn('return GoatPanelCreateFailed(', line)
            self.assertIn('GetLastError()', line)
        self.assertEqual(11, controls.count('ResetLastError();'))

    def test_encoding_and_build_identity_preserved(self):
        for name in ('GOAT V1.48.mq5', 'GOAT V1.49.mq5', 'Dashboard.mqh', 'GOATPortfolioSetupControl.mqh',
                     'GOATPortfolioChildAudit.mqh', 'GOATDeploymentDiagnostics.mqh'):
            data = (ROOT / name).read_bytes()
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'), name)
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''), name)
        self.assertIn('#define   GOAT_BUILD_ID "V1.49-BETA17-43"', (ROOT / 'GOAT V1.49.mq5').read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
