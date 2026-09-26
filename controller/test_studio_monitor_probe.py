from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from studio_monitor_probe import inspect_idle_demo


class MonitorProbeTests(unittest.TestCase):
    def fixture(self):
        c=SimpleNamespace(install=dict(terminal_executable='C:/selected/terminal64.exe',terminal_data_root='C:/data'),
                          session=dict(account=dict(login='123',server='Demo')))
        terminal=SimpleNamespace(path='C:/selected',data_path='C:/data',connected=True,trade_allowed=False,build=6230)
        account=SimpleNamespace(login=123,server='Demo',trade_mode=0)
        sdk=SimpleNamespace(initialize=Mock(return_value=True),shutdown=Mock(),terminal_info=Mock(return_value=terminal),
                            account_info=Mock(return_value=account),positions_get=Mock(return_value=()),orders_get=Mock(return_value=()),
                            ACCOUNT_TRADE_MODE_DEMO=0,__version__='fixture')
        processes={'research':dict(pid=12,executable=c.install['terminal_executable'],created_utc='first'),'protected':None}
        return c,terminal,account,sdk,processes

    def run_probe(self, c, sdk, processes, tester='idle'):
        with patch.dict('sys.modules', {'MetaTrader5':sdk}), patch('studio_monitor_probe.process_binding',return_value={}), \
                patch('studio_monitor_probe.inspect_processes',side_effect=processes), patch('studio_monitor_probe.tester_state',return_value=tester):
            return inspect_idle_demo(c)

    def test_only_read_calls_and_explicit_already_running_path(self):
        c,t,a,s,p=self.fixture()
        result=self.run_probe(c,s,[p,p])
        self.assertTrue(result['account_matches']);self.assertEqual(result['tester_state'],'idle')
        s.initialize.assert_called_once_with(c.install['terminal_executable'],timeout=5000)
        s.shutdown.assert_called_once()

    def test_bad_or_unknown_native_state_cannot_authorize_close(self):
        for kind in ('wrong-path','wrong-data','wrong-account','wrong-server','live','trading','disconnected','positions','orders','missing','busy','unknown','replacement'):
            with self.subTest(kind=kind):
                c,t,a,s,p=self.fixture();states=[p,p];tester='idle'
                if kind=='wrong-path':t.path='C:/other'
                if kind=='wrong-data':t.data_path='C:/other'
                if kind=='wrong-account':a.login=456
                if kind=='wrong-server':a.server='Other'
                if kind=='live':a.trade_mode=2
                if kind=='trading':t.trade_allowed=True
                if kind=='disconnected':t.connected=False
                if kind=='positions':s.positions_get.return_value=(object(),)
                if kind=='orders':s.orders_get.return_value=(object(),)
                if kind=='missing':s.positions_get.return_value=None
                if kind in ('busy','unknown'):tester=kind
                if kind=='replacement':states=[p,dict(p,research=dict(p['research'],pid=99))]
                with self.assertRaises(ValueError):self.run_probe(c,s,states,tester)
                s.shutdown.assert_called_once()


if __name__=='__main__':unittest.main()
