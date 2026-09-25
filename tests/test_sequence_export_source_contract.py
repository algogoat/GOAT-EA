"""Regression guards for producer lifecycle placement and immutable export identity.

Run with unittest; native package helper harness and economic parity remain required.
These guards protect the asynchronous ordering that native tests alone cannot prove.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProducerSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / 'GOAT V1.48.mq5').read_text(encoding='utf-8-sig')
        cls.trace = (ROOT / 'GOAT_SequenceExport.mqh').read_text(encoding='utf-8-sig')
        cls.package = (ROOT / 'GOAT_SequencePackage.mqh').read_text(encoding='utf-8-sig')
        cls.tester = (ROOT / 'Tester.mqh').read_text(encoding='utf-8-sig')

    def test_fixed_selected_export_only(self):
        init = self.trace.split('bool GoatTraceInit()', 1)[1].split('string names[6]', 1)[0]
        for guard in ('!Sequence_Export_Enabled', 'Sequence_Export_Id==""', 'Mode!="EXPORT"',
                      '!MQLInfoInteger(MQL_TESTER)', 'MQLInfoInteger(MQL_OPTIMIZATION)', 'MQLInfoInteger(MQL_FORWARD)'):
            self.assertIn(guard, init)
        self.assertIn('(Init?"false":"true")', self.main)
        self.assertLess(self.main.index('if(!GoatSeqClaimAttempt())'), self.main.index('FileCSV_handle = FileOpen'))

    def test_history_selection_not_changed_inside_order_or_end(self):
        code = re.sub(r'//[^\n]*', '', self.trace)
        self.assertNotIn('HistoryDealSelect(', code)
        for fn, nxt in [('GoatTraceOrderResult', 'GoatTraceDeal'), ('GoatTraceEnd', 'GoatTraceCommitEnd')]:
            body = code.split('void ' + fn + '(', 1)[1].split('void ' + nxt + '(', 1)[0]
            self.assertNotIn('HistorySelect(', body)
            self.assertNotIn('PositionGetTicket(', body)
        self.assertIn('GoatTickBody();\n   GoatTraceBoundary();', self.main)
        self.assertIn('GoatTimerBody();\n   GoatTraceTimer();', self.main)
        self.assertIn('GoatTradeTransactionBody(trans,request,result);', self.main)

    def test_timer_keeps_sparse_historical_marks(self):
        timer = self.trace.split('void GoatTraceTimer()', 1)[1].split('bool GoatTraceInit()', 1)[0]
        self.assertNotIn('GoatTraceBoundary(true)', timer)
        self.assertNotIn('GoatTraceDrainDeals()', timer)
        self.assertIn('if(g_trace_dirty) GoatTraceBoundary();', timer)
        self.assertEqual(timer.count('GoatTraceMarks("minute")'), 1)
        self.assertIn('for(int i=g_trace_history_count;i<count;++i)', self.trace)

    def test_end_waits_for_native_exit_deal(self):
        boundary = self.trace.split('void GoatTraceBoundary(', 1)[1].split('void GoatTraceFlush()', 1)[0]
        self.assertLess(boundary.index('GoatTraceDrainDeals()'), boundary.index('GoatTraceCommitEnd('))
        self.assertIn('g_trace_pending_end_times', boundary)
        end = self.trace.split('void GoatTraceEnd(', 1)[1].split('void GoatTraceCommitEnd(', 1)[0]
        self.assertNotIn('logical_active=false', end)

    def test_identity_is_final_set_and_actual_input_snapshot(self):
        self.assertIn('WriteSet("; Actual resolved native inputs before trading")', self.trace)
        close = self.trace.split('void GoatTraceClose(', 1)[1]
        self.assertIn('GoatSeqHash(g_sequence_export_set,set_hash,set_size)', close)
        self.assertIn('"source_set_sha256_claim",set_hash', close)
        self.assertIn('GoatSeqCopyBytes(g_sequence_export_set,package+"effective.set")', self.trace)

    def test_completion_and_export_discovery_are_ordered(self):
        ready = self.tester.split('bool GoatSeqAttemptReady(', 1)[1]
        self.assertIn('!MTTESTER::IsIdle()', ready)
        self.assertIn('GoatSeqStem(csv)!=GoatSeqStem(set)', ready)
        self.assertIn('.goatseq\\\\manifest.json', ready)
        self.assertIn('==".goatseq") continue;', self.tester)
        self.assertIn('fname=ent;', self.tester)
        self.assertNotIn('FindExports("TEMP",exports); DeleteExports(exports)', self.main)
        transfer = self.package.split('bool GoatSeqTransferUnit(', 1)[1].split('bool GoatSeqDeleteUnit(', 1)[0]
        self.assertLess(transfer.index('GoatSeqCopyBytes(source[i],target[i])'), transfer.index('GoatSeqMoveFile(target[count-1]+".tmp"'))
        self.assertLess(transfer.index('GoatSeqMoveFile(target[count-1]+".tmp"'), transfer.index('GoatSeqDeleteFile(source[count-1]'))

    def test_host_adapter_is_gated_and_never_decodes_file_bytes(self):
        host = (ROOT / 'GOAT_SequenceHostIO.mqh').read_text(encoding='utf-8-sig')
        self.assertIn('bool context=!MQLInfoInteger(MQL_TESTER)', host)
        self.assertIn('MQLInfoInteger(MQL_DLLS_ALLOWED)', host)
        self.assertIn('parts[i]==".."', host)
        self.assertIn('MTTESTER::FileCopy(from,to,false)', host)
        self.assertIn('MTTESTER::FileMove(from,to,false)', host)
        self.assertNotIn('#import', host)
        self.assertNotIn('CharArrayToString', host)

    def test_mql_encoding_preserved(self):
        for name in ('GOAT V1.48.mq5', 'Tester.mqh', 'GOAT_SequencePackage.mqh', 'GOAT_SequenceExport.mqh', 'GOAT_SequenceHostIO.mqh'):
            data = (ROOT / name).read_bytes()
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'), name)
            self.assertNotIn(b'\n', data.replace(b'\r\n', b''), name)


if __name__ == '__main__':
    unittest.main()
