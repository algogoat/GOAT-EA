"""Source contracts for journal diagnostics; these do not execute or qualify MQL5."""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source(name):
    return (ROOT / name).read_text(encoding="utf-8-sig")


def function(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class RecoveryDiagnosticsSourceTests(unittest.TestCase):
    def setUp(self):
        self.native = source("GOATStudioRecovery.mqh")
        self.guard = function(self.native, "bool GoatStudioRecoveryRuntime(const string login,const string server,const string instance,\n")
        self.wrapper = function(self.native, "bool GoatStudioRecoveryRuntime(const string login,const string server,const string instance)\n")
        self.logger = function(self.native, "void GoatStudioRecoveryDiagnostic(")
        self.observer = function(self.native, "void GoatStudioRecoveryObserveCurrent(")

    def test_recovery_action_claim_effect_and_status_bytes_unchanged(self):
        action = self.native[self.native.index("string GoatStudioRecoverOrphan("):self.native.index("\n#endif")]
        self.assertEqual(hashlib.sha256(action.encode()).hexdigest(),
                         "c3327504534d0555a3c6fb85dd05dd8e70ede161bf97332e992394594ac567e6")

    def test_existing_observation_wire_and_write_unchanged(self):
        ui = source("GOATStudioUI.mqh")
        hook = ("#ifdef GOAT_ORPHAN_RECOVERY_V149\n"
                "   // Observe only the current inert monitor; never replay or attribute an old request.\n"
                "   if(g_GoatStudioReadOnlyMonitor && g_StudioBound && m_studioLoaded\n"
                '      && GlobalVariableGet("BatchOnGoing")!=0) GoatStudioRecoveryObserveCurrent();\n'
                "#endif\n")
        observation = ui[ui.index("void CStrategyTesterDialog::ManagedObservation("):ui.index("\nvoid CStrategyTesterDialog::ManagedSave")]
        self.assertEqual(observation.count(hook), 1)
        self.assertLess(observation.index('now-g_StudioObservationMillis<5000'), observation.index(hook))
        self.assertEqual(hashlib.sha256(observation.replace(hook, "").encode()).hexdigest(),
                         "ccb0895972457bd25c75d808792e8def54728ab85ec07bb3d1d9bf7156b296e2")
        self.assertEqual(ui.count("GoatStudioRecoveryObserveCurrent();"), 1)

    def test_original_scalar_predicates_preserve_order_and_short_circuit(self):
        expected = [
            ('!IsStopped()', 'EA_STOPPED'),
            ('g_GoatStudioReadOnlyMonitor', 'NOT_READ_ONLY_MONITOR'),
            ('!MQLInfoInteger(MQL_TESTER)', 'IN_TESTER'),
            ('MQLInfoInteger(MQL_DLLS_ALLOWED)', 'DLL_NOT_ALLOWED'),
            ('GoatStudioTesterState()=="idle"', 'TESTER_NOT_IDLE'),
            ('TerminalInfoInteger(TERMINAL_CONNECTED)', 'TERMINAL_DISCONNECTED'),
            ('!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)', 'ALGO_TRADING_ENABLED'),
            ('AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO', 'NOT_DEMO'),
            ('login==(string)AccountInfoInteger(ACCOUNT_LOGIN)', 'ACCOUNT_CHANGED'),
            ('server==AccountInfoString(ACCOUNT_SERVER)', 'SERVER_CHANGED'),
            ('instance==GoatStudioRecoveryInstance()', 'MONITOR_CHANGED'),
            ('GlobalVariableGet("BatchOnGoing")!=0', 'BATCH_FLAG_ABSENT'),
            ('GlobalVariableGet("TerminalRunning")==0', 'TERMINAL_RUNNING'),
            ('GlobalVariableGet("GOAT_BatchRestartPending")==0', 'RESTART_PENDING'),
        ]
        calls = ['GoatStudioRecoveryRuntimeCheck(' + predicate + ',"' + reason + '",reason)' for predicate, reason in expected]
        expression = self.guard[self.guard.index('   return GoatStudioRecoveryRuntimeCheck'):].strip()
        self.assertEqual(re.sub(r"\s+", " ", expression), "return " + " && ".join(calls) + "; }")
        check = function(self.native, "bool GoatStudioRecoveryRuntimeCheck(")
        self.assertEqual(check[check.index("{"):], "{\n   if(!ok) reason=code;\n   return ok;\n  }")

    def test_chart_guards_keep_order_and_capture_failure_without_reset(self):
        ordered = ['long chart=ChartFirst();int charts=0;bool own=false;',
                   'while(chart>=0)', 'if(++charts>1000)', 'int query_before=GetLastError();',
                   'if(!ChartGetString(chart,CHART_EXPERT_NAME,expert))',
                   '{after=GetLastError();before=query_before;reason="EXPERT_QUERY_FAILED";return false;}',
                   'query_before=GetLastError();', 'if(!ChartGetString(chart,CHART_SCRIPT_NAME,script))',
                   '{after=GetLastError();before=query_before;reason="SCRIPT_QUERY_FAILED";return false;}',
                   'if(StringLen(script)>0)', 'if(chart==ChartID()) own=true;', 'else if(StringLen(expert)>0)',
                   'chart=ChartNext(chart);', 'if(!own)', 'return GoatStudioRecoveryRuntimeCheck']
        position = 0
        for fragment in ordered:
            position = self.guard.index(fragment, position) + len(fragment)
        self.assertEqual(self.guard.count('ChartGetString('), 2)
        self.assertNotIn('ResetLastError', self.guard + self.wrapper + self.logger + self.observer)

    def test_guard_and_observer_call_inventory_is_read_only(self):
        names = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', self.guard + self.observer))
        self.assertEqual(names, {'GoatStudioRecoveryRuntime', 'GoatStudioRecoveryObserveCurrent',
            'GoatStudioRecoveryDiagnostic', 'GoatStudioRecoveryRuntimeCheck', 'ChartFirst', 'ChartNext',
            'ChartID', 'ChartGetString', 'StringLen', 'GetLastError', 'IsStopped', 'MQLInfoInteger',
            'GoatStudioTesterState', 'TerminalInfoInteger', 'AccountInfoInteger', 'AccountInfoString',
            'GoatStudioRecoveryInstance', 'GlobalVariableGet', 'PrintFormat', 'if', 'while'})
        self.assertIn('if(StringLen(script)>0)', self.guard)
        self.assertIn('if(!g_StudioScriptDiagnosticLogged)', self.guard)
        self.assertIn('g_StudioScriptDiagnosticLogged=true;', self.guard)
        self.assertIn('PrintFormat("GOAT ORPHAN SCRIPT chart=%I64d own=%s script=%s diagnostic_only",chart,chart==ChartID()?"yes":"no",script);', self.guard)
        self.assertIn('reason="SCRIPT_PRESENT";return false;', self.guard)
        self.assertLess(self.guard.index('g_StudioScriptDiagnosticLogged=true;'), self.guard.index('PrintFormat("GOAT ORPHAN SCRIPT'))
        self.assertNotIn('GoatStudioRecoverOrphan(', self.observer)
        self.assertNotIn('GoatStudioDispatch(', self.observer)

    def test_recovery_return_value_is_not_changed_by_logging(self):
        self.assertIn('bool ok=GoatStudioRecoveryRuntime(login,server,instance,reason,before,after);', self.wrapper)
        self.assertIn('if(!ok) GoatStudioRecoveryDiagnostic("RECOVERY_RUNTIME_REJECTED",reason,before,after);', self.wrapper)
        self.assertTrue(self.wrapper.endswith('return ok;\n  }'))
        self.assertEqual(self.wrapper.count('return '), 1)

    def test_journal_is_bounded_deduplicated_and_has_no_identifiers(self):
        self.assertIn('string g_StudioRecoveryDiagnosticKeys[16];', self.native)
        self.assertIn('if(g_StudioRecoveryDiagnosticCount>=16) return;', self.logger)
        self.assertIn('if(g_StudioRecoveryDiagnosticKeys[i]==key) return;', self.logger)
        self.assertLess(self.logger.index('g_StudioRecoveryDiagnosticKeys[g_StudioRecoveryDiagnosticCount++]=key;'), self.logger.index('PrintFormat('))
        self.assertEqual(self.logger.count('PrintFormat('), 1)
        for forbidden in ('login', 'server', 'instance', 'ChartID', 'request', 'token', 'path', 'File', 'GlobalVariable'):
            self.assertNotIn(forbidden, self.logger)
        self.assertIn('query_error_before=%d query_error_after=%d', self.logger)
        self.assertIn('NO_ACTION current_state_not_original_rejection', self.logger)

    def test_current_observer_never_uses_original_request_identity(self):
        self.assertIn('if(g_StudioRecoveryDiagnosticCount>=16) return;', self.observer)
        self.assertIn('(string)AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER)', self.observer)
        self.assertIn('GoatStudioRecoveryInstance(),reason,before,after);', self.observer)
        self.assertIn('GoatStudioRecoveryDiagnostic("CURRENT_MONITOR_OBSERVATION",reason,before,after);', self.observer)
        self.assertIn('reason="CURRENT_GUARD_PASS";before=0;after=0;', self.guard)

    def test_unknown_start_protocol_refuses_before_intent_or_batch_arm(self):
        dispatch = source("GOATStudioDispatch.mqh")
        execute = function(dispatch, "string GoatStudioExecuteRequest(")
        gate = 'if(start_build!=6182 && start_build!=6230) return "START_PROTOCOL_NOT_QUALIFIED";'
        self.assertIn(gate, execute)
        self.assertLess(execute.index(gate), execute.index('"GOATStudio\\\\native-gate\\\\consumed-"'))
        self.assertLess(execute.index(gate), execute.index('GlobalVariableSet("BatchOnGoing",1.0)'))
        self.assertLess(execute.index(gate), execute.index('MTTESTER::ClickStart(false,1)'))
        self.assertIn('GOAT_STUDIO_WORKER_READBACK build=%d', source("GOATStudioWorkers.mqh"))

    def test_idle_monitor_readback_does_not_require_a_start_request(self):
        main = source('GOAT V1.49.mq5')
        timer = function(main, 'void GoatTimerBody(void)\n')
        self.assertIn('g_GoatStudioReadOnlyMonitor', timer)
        self.assertIn('tester_state=="idle"', timer)
        self.assertIn('GoatStudioReadWorkerPolicy(worker_local,worker_remote,worker_cloud)', timer)
        self.assertIn('FileOpen("GOATStudio\\\\native-gate\\\\launch.lock",FILE_READ|FILE_WRITE|FILE_BIN)', timer)
        self.assertLess(timer.index('int diagnostic_gate=FileOpen('), timer.index('GoatStudioReadWorkerPolicy('))
        self.assertLess(timer.index('GoatStudioReadWorkerPolicy('), timer.index('FileClose(diagnostic_gate);'))
        self.assertIn('bool still_idle=(algo_off', timer)
        self.assertIn('readback && still_idle ? "READBACK_OK"', timer)
        self.assertLess(timer.index('GoatStudioReadWorkerPolicy('), timer.index('TesterDialog.OnClickRefresh(true);'))
        self.assertIn('GOAT / Optimization Studio / ', timer)
        self.assertIn('GOAT_BUILD_ID', timer)
        self.assertIn('FileIsExist("GOATStudio\\\\native-gate\\\\request.json")', timer)
        self.assertIn('FileIsExist("GOATStudio\\\\native-gate\\\\permit.json")', timer)
        self.assertNotIn('MTTESTER::ClickStart', timer)
        self.assertNotIn('GlobalVariableSet("BatchOnGoing",1.0)', timer)

    def test_source_and_compiled_candidate_identity(self):
        main = source('GOAT V1.49.mq5')
        self.assertIn('#define   GOAT_VERSION_LABEL "1.49"', main)
        self.assertIn('#define   GOAT_BUILD_ID "V1.49-CANCEL-ORIGIN-23"', main)
        self.assertEqual(hashlib.sha256((ROOT/'GOAT V1.49.ex5').read_bytes()).hexdigest(),
                         'f3e3a9700aef2b967b9c2c5d90dad0b86522bd65511ace4ba5c4bd65c324c066')
        for name in ('GOATStudioRecovery.mqh', 'GOATStudioRecoveryFiles.mqh', 'GOATStudioUI.mqh',
                     'GOATStudioWorkers.mqh', 'GOATStudioExportDates.mqh', 'GOATStudioControlFeedback.mqh', 'GOAT V1.49.mq5'):
            raw = (ROOT/name).read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        for version in ('1.47', '1.48'):
            self.assertNotIn('#define GOAT_ORPHAN_RECOVERY_V149', source('GOAT V'+version+'.mq5'))


if __name__ == '__main__':
    unittest.main()
