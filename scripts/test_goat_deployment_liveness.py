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
        # BeginChildAttach, ApplyTemplate (human wait), FailChildAttachTimeout, CompleteChildAttach.
        cls.apply = region(cls.dashboard, 'bool CGOATDashboard::BeginChildAttach(', 'bool CGOATDashboard::NewSingleInstance(')
        cls.timeout = region(cls.dashboard, 'void CGOATDashboard::FailChildAttachTimeout(', 'bool CGOATDashboard::CompleteChildAttach(')
        cls.agent_begin = region(cls.dashboard, 'bool CGOATDashboard::AgentBeginDeployRow(', 'int CGOATDashboard::AgentPollDeployRow(')
        cls.agent_poll = region(cls.dashboard, 'int CGOATDashboard::AgentPollDeployRow(', 'bool CGOATDashboard::AgentExposurePolicy(')
        cls.setup = (ROOT / 'GOATPortfolioSetupControl.mqh').read_text(encoding='utf-8-sig')

    def test_polling_does_not_refresh_or_reissue_child_chart(self):
        body = region(self.apply, 'while(!NewSingleInstance(idx))', 'return CompleteChildAttach(idx,tplName);')
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
        self.assertIn('FailChildAttachTimeout(idx,tplName);', region(self.apply, 'if(GetTickCount()-wait_start>20000)', 'Sleep(50);'))
        for timeout in (self.timeout, self.agent_poll):
            self.assertNotIn('g_sets[idx].cid=', timeout)
        # The human timeout leaves its chart for inspection; the agent closes it but keeps the ID as the lock.
        self.assertNotIn('ChartClose(', self.timeout)
        # Every failed agent attach (timeout or not inert) goes through one unwind that closes the chart.
        self.assertEqual(1, self.agent_poll.count('AgentUnwindFailedAttach(idx);'))
        unwind = region(self.dashboard, 'void CGOATDashboard::AgentUnwindFailedAttach(', 'void CGOATDashboard::SweepStaleChildTemplates(')
        self.assertIn('CloseFailedChildChart(idx,false);', unwind)
        self.assertIn('bool chart_closed=ChartClose(cid);', region(self.dashboard, 'void CGOATDashboard::CloseFailedChildChart(', 'void CGOATDashboard::AgentUnwindFailedAttach('))
        self.assertIn('DeleteCopiedTemplate(tplName);', self.timeout)
        self.assertEqual(1, self.apply.count('ChartApplyTemplate('))

    def test_agent_attach_returns_before_the_handshake(self):
        # ChartApplyTemplate only queues; the agent handler must return before the child can start.
        self.assertIn('BeginChildAttach(idx,tf,tplName)', self.agent_begin)
        for blocking in ('while(', 'Sleep(', 'NewSingleInstance(', 'ApplyTemplate(idx', 'DoActivate('):
            self.assertNotIn(blocking, self.agent_begin)
        # B41.2/B41.3: the pending child chart is refreshed every 2 s (T3 6030127717) on that row's chart only,
        # inside the cadence block, until our EA is on it. A NULL CHART_EXPERT_NAME must not stop it (B41.3).
        refresh = region(self.agent_poll, 'if(!m_agent_attach_nudge_done && GetTickCount()-m_agent_attach_refresh>=2000)', 'return 0;')
        self.assertIn('ChartSetSymbolPeriod(child_cid,g_sets[idx].sym,m_agent_attach_tf);', refresh)
        self.assertIn('ChartRedraw(child_cid);', refresh)
        self.assertIn('bool expert_ours=(StringLen(child_expert)>0 && child_expert==EA_Name_);', self.agent_poll)
        self.assertNotIn('child_expert!=""', self.agent_poll)
        # The one-off re-apply probe is diagnostic, behind its own define (T3 only, Mac 6031532401).
        reapply = region(self.agent_poll, '#ifdef GOAT_ATTACH_REAPPLY_PROBE', '#endif')
        self.assertEqual(1, reapply.count('ChartApplyTemplate('))
        self.assertIn('m_agent_attach_reapplied=true;', reapply)
        passive_handshake(self.agent_poll.replace(refresh, '').replace(reapply, ''))
        for blocking in ('while(', 'Sleep('):
            self.assertNotIn(blocking, self.agent_poll)
        self.assertIn('GetTickCount()-m_agent_attach_start<=GOAT_AGENT_ATTACH_BUDGET_MS', self.agent_poll)
        self.assertIn('#define GOAT_AGENT_ATTACH_BUDGET_MS 75000', self.dashboard)
        self.assertIn('CompleteChildAttach(idx,tplName)', self.agent_poll)
        self.assertIn('FailChildAttachTimeout(idx,tplName)', self.agent_poll)
        deploy = region(self.setup, 'else if(action=="deploy_next")', 'else if(action=="apply_policy")')
        self.assertIn('DashboardDialog.AgentBeginDeployRow(next)', deploy)
        for blocking in ('AgentDeployRow(', 'DoActivate(', 'ApplyTemplate(', 'Sleep('):
            self.assertNotIn(blocking, deploy)
        poll = region(self.setup, 'void GoatPortfolioSetupPoll(void)', 'string registration=')
        self.assertIn('GoatPortfolioAttachContinue(root)', poll)

    def test_encoding_and_current_build_identity_preserved(self):
        for name in ('GOAT V1.48.mq5', 'Dashboard.mqh', 'GOATDeploymentDiagnostics.mqh'):
            data = (ROOT / name).read_bytes()
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'), name)
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''), name)
        self.assertIn('#define   GOAT_BUILD_ID "V1.48-DASHBOARD-AI-PAIR-R2"', self.main)


if __name__ == '__main__':
    unittest.main()
