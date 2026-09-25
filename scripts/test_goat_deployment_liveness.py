"""Source regression guards; these do not simulate MT5 or prove native liveness."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def region(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def passive_handshake(body):
    for forbidden in ('ChartSetSymbolPeriod(', 'ChartRedraw(', 'ChartApplyTemplate(', 'ChartOpen('):
        if forbidden in body:
            raise AssertionError('Chart mutation during child registration: ' + forbidden)


class DeploymentLivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = (ROOT / 'Dashboard.mqh').read_text(encoding='utf-8-sig')
        cls.main = (ROOT / 'GOAT V1.48.mq5').read_text(encoding='utf-8-sig')
        cls.diagnostics = (ROOT / 'GOATDeploymentDiagnostics.mqh').read_text(encoding='utf-8-sig')
        cls.apply = region(cls.dashboard, 'bool CGOATDashboard::ApplyTemplate(', 'bool CGOATDashboard::NewSingleInstance(')

    def test_polling_does_not_refresh_or_reissue_child_chart(self):
        body = region(self.apply, 'while(!NewSingleInstance(idx))', 'GoatDeploymentPhase("handshake_linked"')
        passive_handshake(body)
        self.assertIn('GetTickCount()-wait_start>20000', body)
        self.assertIn('Sleep(50);', body)
        self.assertIn('return false;', body)
        for injected in ('ChartSetSymbolPeriod(cid,symbol,tf);', 'ChartRedraw(cid);', 'ChartApplyTemplate(cid,tplName);'):
            with self.assertRaises(AssertionError):
                passive_handshake(body + injected)

    def test_agent_skips_focus_and_post_handshake_sleeps(self):
        tail = self.apply.split('GoatDeploymentPhase("handshake_linked",cid);', 1)[1]
        human = region(tail, 'if(!m_agent_setup_quiet)\n   {', '\n   }')
        self.assertIn('CHART_BRING_TO_TOP', human)
        self.assertIn('ChartRedraw(cid)', human)
        tail = tail.replace('if(!m_agent_setup_quiet)\n   {' + human + '\n   }', '', 1)
        tail = tail.replace('if(!m_agent_setup_quiet) {Sleep(500); ChartRedraw(); Sleep(500);}', '', 1)
        for operation in ('ChartRedraw(', 'CHART_BRING_TO_TOP', 'Sleep('):
            self.assertNotIn(operation, tail)
        self.assertIn('SaveDashboardConfig()', tail)
        self.assertIn('DeleteCopiedTemplate(tplName)', tail)

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

    def test_api_error_capture_precedes_diagnostic_io(self):
        self.assertRegex(self.apply, r'ChartOpen\(symbol, tf\);\s+int open_error=GetLastError\(\);')
        self.assertRegex(self.apply, r'ChartApplyTemplate\(cid, tplName\);\s+int template_error=GetLastError\(\);')
        controls = region(self.main, 'bool CPanelDialog::CreateBiEditRow(', '/*bool CPanelDialog::CreateBmpButton1')
        checked = [line for line in controls.splitlines() if 'if(!' in line and not line.lstrip().startswith('//')]
        self.assertEqual(11, len(checked))
        for line in checked:
            self.assertIn('return GoatPanelCreateFailed(', line)
            self.assertIn('GetLastError()', line)
        self.assertEqual(11, controls.count('ResetLastError();'))

    def test_handshake_identity_and_failure_retention_remain(self):
        handshake = region(self.dashboard, 'bool CGOATDashboard::NewSingleInstance(', 'void CGOATDashboard::ParsePortfolioFolderInfo(')
        for required in ('SETUP_CID_HI', 'SETUP_CID_LO', 'GOAT_GV_FIELD_MAGIC', 'other!=idx', 'GlobalVariableDel(pending)'):
            self.assertIn(required, handshake)
        self.assertLess(self.apply.index('SaveDashboardConfig()'), self.apply.index('ChartApplyTemplate('))
        timeout = region(self.apply, 'if(GetTickCount()-wait_start>20000)', 'Sleep(50);')
        self.assertNotIn('g_sets[idx].cid=', timeout)
        self.assertNotIn('ChartClose(', timeout)
        self.assertEqual(1, self.apply.count('ChartApplyTemplate('))

    def test_encoding_and_current_build_identity_preserved(self):
        for name in ('GOAT V1.48.mq5', 'Dashboard.mqh', 'GOATDeploymentDiagnostics.mqh'):
            data = (ROOT / name).read_bytes()
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'), name)
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''), name)
        self.assertIn('#define   GOAT_BUILD_ID "V1.48-DASHBOARD-AI-PAIR-R2"', self.main)


if __name__ == '__main__':
    unittest.main()
