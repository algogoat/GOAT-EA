"""Read-only lane status: monitor/licence classification, pace and ETA, qualifying exports."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from studio_bridge import write_json
from studio_research_status import (headline, monitor_state, pace, research_status, seed_progress, timeline)

NOW = 1_800_000_000
PROCESS = dict(pid=7, executable='terminal64.exe', created_utc='2026-10-01T00:00:00Z')


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.data = base / 'Terminal 1 - Banker'; self.common = base / 'common'
        self.local = self.data / 'MQL5/Files/GOATStudio'; self.local.mkdir(parents=True)
        (self.common / 'GOAT').mkdir(parents=True)
        self.install = dict(terminal_data_root=str(self.data), common_files_root=str(self.common))
        self.session = dict(run_id='run-1', terminal_id='t', account=dict(login='1', server='Demo'))

    def observe(self, age, **fields):
        path = self.local / 'ui-observation.json'
        write_json(path, dict(schema_version=1, bound=True, loaded=True, owner='agent',
                              runtime=dict(tester_state='running', terminal_build=6230)) | fields)
        os.utime(path, (NOW - age, NOW - age))

    def activation(self, token, reason, at):
        (self.common / 'GOAT' / ('activation-status-' + token + '.json')).write_text(
            json.dumps(dict(accountId='1', reason=reason, observedAtUtc=at)))

    def state(self, process=PROCESS):
        return monitor_state(self.install, self.session, self.local, now=NOW, process=process)

    def test_fresh_bound_agent_heartbeat_ticks(self):
        self.observe(3)
        value = self.state()
        self.assertEqual((value['state'], value['ticking'], value['blocker']), ('ticking', True, None))
        self.assertEqual(value['terminal_build'], 6230)

    def test_closed_terminal_and_never_reported_monitor_name_their_fix(self):
        self.assertEqual(self.state(process=None)['blocker']['code'], 'terminal_closed')
        self.assertEqual(self.state()['blocker']['code'], 'monitor_never_reported')

    def test_member_boundary_relaunch_is_transient_not_a_blocker(self):
        self.observe(90)
        value = self.state()
        self.assertEqual((value['state'], value['transient'], value['blocker']), ('relaunching', True, None))

    def test_silent_monitor_says_how_long(self):
        self.observe(900)
        self.assertIn('15 minutes ago', self.state()['blocker']['message'])

    def test_sign_in_replaced_by_another_terminal_is_a_re_pair_blocker(self):
        self.observe(3600)
        self.activation('Terminal 1 - Banker', 'awaiting_approval', NOW - 60)
        self.activation('Terminal 2 - Exp', 'approved', NOW - 1800)
        value = self.state()
        self.assertEqual((value['state'], value['blocker']['code']), ('unlicensed', 'monitor_unlicensed'))
        self.assertEqual(value['blocker']['message'], "This terminal's GOAT sign-in was replaced by another terminal — re-pair it.")
        self.assertIn('connection code', value['blocker']['fix'])

    def test_waiting_sign_in_build_and_network_reasons_are_plain(self):
        self.observe(3600)
        self.activation('Terminal 1 - Banker', 'awaiting_approval', NOW - 60)
        self.assertIn('waiting for its sign-in', self.state()['blocker']['message'])
        self.activation('Terminal 1 - Banker', 'build_not_admitted', NOW - 60)
        self.assertEqual(self.state()['blocker']['code'], 'monitor_build_not_admitted')
        self.activation('Terminal 1 - Banker', 'webrequest_permission_required', NOW - 60)
        self.assertIn('WebRequest', self.state()['blocker']['fix'])

    def test_sign_in_status_written_for_another_account_is_ignored(self):
        self.observe(3600)
        (self.common / 'GOAT' / 'activation-status-Terminal 1 - Banker.json').write_text(
            json.dumps(dict(accountId='999', reason='awaiting_approval', observedAtUtc=NOW - 60)))
        self.assertEqual(self.state()['blocker']['code'], 'monitor_silent')

    def test_old_sign_in_status_does_not_override_a_fresh_heartbeat(self):
        self.observe(2)
        self.activation('Terminal 1 - Banker', 'awaiting_approval', NOW - 7200)
        self.assertTrue(self.state()['ticking'])

    def test_unbound_human_and_foreign_session_monitors_are_named(self):
        self.observe(2, bound=False)
        self.assertEqual(self.state()['blocker']['code'], 'monitor_unbound')
        self.observe(2, owner='human')
        self.assertEqual(self.state()['blocker']['code'], 'human_took_control')
        self.observe(2, run_id='other')
        self.assertEqual(self.state()['blocker']['code'], 'monitor_other_session')


def stamp(epoch):
    return time.strftime('%Y.%m.%d %H:%M:%S', time.localtime(epoch))


class PaceTests(unittest.TestCase):
    def test_timeline_pace_and_eta_from_native_members(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = ['LocalTime\tServerTime\tEvent\tItem\tStatus\tDetails']
            for index, (start, end) in enumerate([(NOW - 4000, NOW - 3400), (NOW - 3300, NOW - 2700), (NOW - 2600, NOW - 2000)]):
                rows.append('\t'.join([stamp(start), stamp(start), 'QUEUE_STATE', 'OnGoing_x:A' + str(index), 'OnGoing', '']))
                rows.append('\t'.join([stamp(end), stamp(end), 'QUEUE_STATE', 'Completed_x:A' + str(index), 'Completed', '']))
            rows.append('\t'.join([stamp(NOW - 120), stamp(NOW - 120), 'QUEUE_STATE', 'OnGoing_x:A3', 'OnGoing', '']))
            Path(folder, 'timeline.tsv').write_text('\n'.join(rows) + '\n', encoding='utf-8')
            timing = timeline(folder, ['A0', 'A1', 'A2', 'A3', 'A4'])
        statuses = ['native_completed'] * 3 + ['native_ongoing', 'native_pending']
        value = pace(timing, statuses, now=NOW)
        self.assertEqual(value['member_minutes_median'], 10.0)
        self.assertAlmostEqual(value['minutes_per_member'], round(2000 / 3 / 60, 1))
        self.assertEqual((value['current_index'], value['current_age_seconds'], value['remaining_members']), (3, 120, 2))
        self.assertAlmostEqual(value['eta_wall'], NOW + 2 * 2000 / 3 - 120, places=3)
        self.assertEqual(value['basis'], 'native_timeline')

    def test_without_timeline_pace_uses_driver_start_and_completions(self):
        value = pace(None, ['native_completed', 'native_completed', 'native_pending'], now=NOW, fallback_started=NOW - 3600)
        self.assertEqual((value['minutes_per_member'], value['basis']), (30.0, 'driver_start_and_completed_count'))
        self.assertIsNone(pace(None, ['native_pending'], now=NOW)['eta_utc'])

    def test_headlines_are_one_plain_sentence(self):
        running = dict(kind='batch', status='running', members_total=40, members_done=13, qualifying=5,
                       pace=dict(eta_wall=NOW + 7800), current_member=dict(symbol='EURUSD', timeframe='M15'), _now=NOW)
        self.assertEqual(headline(running), 'Running on EURUSD M15; 13 of 40 members done, 5 qualifying, about 2 h 10 min left.')
        self.assertIn('Pausing this batch at the next safe point', headline(dict(running, status='pausing')))
        self.assertIn('Resume continues', headline(dict(running, status='paused')))
        self.assertEqual(headline(dict(kind='idle')), 'No research is running on this terminal.')


class SeedAndStatusTests(unittest.TestCase):
    def test_seed_progress_counts_qualifying_candidates_and_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); seed = root / 'seeds' / 'hunt'; seed.mkdir(parents=True)
            members = [dict(alias='S1', status='completed', started_unix=NOW - 1200, finished_unix=NOW - 600,
                            result=dict(summary=dict(qualifying_count=4, best_fitness=1.5))),
                       dict(alias='S2', status='running', started_unix=NOW - 300),
                       dict(alias='S3', status='pending')]
            write_json(seed / 'state.json', dict(status='active', members=members))
            value = seed_progress(root, 'hunt', now=NOW)
            self.assertEqual((value['members_done'], value['members_total'], value['qualifying'], value['qualifying_candidates']), (1, 3, 1, 4))
            self.assertEqual(value['pace']['minutes_per_member'], 10.0)
            write_json(seed / 'pause.json', dict(batch_id='hunt'))
            self.assertEqual(seed_progress(root, 'hunt', now=NOW)['status'], 'pausing')

    def test_catchup_progress_counts_held_up_never_qualifying(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); catchup = root / 'catchups' / 'cu1'; catchup.mkdir(parents=True)
            members = [dict(alias='C1', status='completed', started_unix=NOW - 1200, finished_unix=NOW - 600,
                            result=dict(summary=dict(verdict='held_up', qualifying_count=3))),
                       dict(alias='C2', status='completed', started_unix=NOW - 600, finished_unix=NOW - 300,
                            result=dict(summary=dict(verdict='not_comparable'))),
                       dict(alias='C3', status='running', started_unix=NOW - 100)]
            write_json(catchup / 'state.json', dict(status='active', members=members))
            value = seed_progress(root, 'cu1', now=NOW, kind='catchup')
            self.assertEqual((value['qualifying'], value['qualifying_candidates'], value['held_up']), (None, None, 1))
            text = headline(dict(value, current_member=dict(symbol='EURUSD', timeframe='M1')))
            self.assertIn('2 of 3 members done, 1 held up (low-sample verdicts)', text)
            self.assertNotIn('qualifying', text)

    def test_status_without_controller_queue_is_idle_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); data = base / 'data'; local = data / 'MQL5/Files/GOATStudio'; local.mkdir(parents=True)
            (base / 'common').mkdir(); (base / 'state').mkdir()
            install = dict(terminal_data_root=str(data), common_files_root=str(base / 'common'), terminal_executable='t.exe',
                           ea_version='1.49', ea_sha256='e' * 64)
            session = dict(run_id='r', terminal_id='t', account=dict(login='3000082754', server='Darwinex-Demo'), demo_only=True)
            before = sorted(str(p) for p in base.rglob('*'))
            value = research_status(root=base / 'state', install=install, session=session, local=local, now=NOW, process=None)
            self.assertEqual(sorted(str(p) for p in base.rglob('*')), before)
        self.assertEqual(value['activity']['kind'], 'idle')
        self.assertEqual(value['activity']['headline'], 'No research is running on this terminal.')
        self.assertEqual(value['monitor']['blocker']['code'], 'terminal_closed')
        self.assertEqual((value['account']['login'], value['terminal']['running'], value['read_only']), ('3000082754', False, True))
        self.assertIn('headroom_ok', value['disk'])


if __name__ == '__main__':
    unittest.main()
