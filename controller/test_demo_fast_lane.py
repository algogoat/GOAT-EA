"""Demo-lane Stop / Start / Continue entry points: routing and one-sentence refusals."""
import unittest
from unittest.mock import patch

import test_demo_agent


class DemoFastLaneTests(unittest.TestCase):
    def setUp(self):
        base = test_demo_agent.DemoAgentTests('test_broker_reported_demo_and_exact_allowlist_required')
        base.setUp(); self.addCleanup(base.doCleanups)
        self.root, self.agent = base.root, base.agent

    def test_start_refuses_under_owner_stop_with_the_next_command(self):
        (self.root / 'demo-agent').mkdir(exist_ok=True)
        (self.root / 'demo-agent/STOP').write_text('{"actor":"demo_agent"}')
        with self.assertRaisesRegex(ValueError, r'^Owner STOP is on; run clear-stop, then start again\.$'):
            self.agent.start('batch-1')

    def test_start_uses_the_bounded_driver_with_a_default_budget(self):
        with patch.object(self.agent, 'run_batch', return_value=dict(status='driver_journal_recorded')) as run:
            self.agent.start('batch-1')
        run.assert_called_once_with('batch-1', 172800)

    def test_stop_of_one_unstarted_batch_does_not_set_owner_stop(self):
        with patch.object(self.agent, '_native_active_batches', return_value=[]), \
                patch.object(self.agent, '_stop_unstarted', return_value=dict(status='cancelled')) as unstarted:
            self.assertEqual(self.agent.stop(batch_id='batch-1'), dict(status='cancelled'))
        unstarted.assert_called_once_with('batch-1')
        self.assertFalse((self.root / 'demo-agent/STOP').exists())

    def test_stop_of_an_active_batch_keeps_the_owner_stop_route(self):
        with patch.object(self.agent, '_native_active_batches', return_value=['batch-1']), \
                patch.object(self.agent, '_stop_unstarted') as unstarted, \
                patch.object(self.agent, '_unactivated', return_value=True), \
                patch.object(self.agent, 'retire_unactivated', return_value=dict(attempt_id='a' * 64)):
            result = self.agent.stop(batch_id='batch-1')
        unstarted.assert_not_called()
        self.assertEqual((result['status'], result['retired']), ('cancelled', 'retired_never_activated'))
        self.assertTrue((self.root / 'demo-agent/STOP').exists())

    def test_continue_names_unknown_batches_plainly(self):
        with patch.object(self.agent, '_jobs_readonly', return_value=[]), \
                patch.object(self.agent, '_is_seed', return_value=False):
            with self.assertRaisesRegex(ValueError, r'^Unknown batch batch-9; research-status lists the batches of this terminal\.$'):
                self.agent.continue_batch('batch-9')

    def test_continue_under_owner_stop_asks_for_clear_stop(self):
        (self.root / 'demo-agent').mkdir(exist_ok=True)
        (self.root / 'demo-agent/STOP').write_text('{"actor":"demo_agent"}')
        job = dict(job_id='batch-1', status='cancelled')
        with patch.object(self.agent, '_jobs_readonly', return_value=[job]), \
                patch.object(self.agent, '_is_seed', return_value=False), \
                patch('studio_research_status.monitor_state', return_value={}):
            with self.assertRaisesRegex(ValueError, r'^Owner STOP is on; continue with --clear-stop to lift it\.$'):
                self.agent.continue_batch('batch-1')


if __name__ == '__main__':
    unittest.main()
