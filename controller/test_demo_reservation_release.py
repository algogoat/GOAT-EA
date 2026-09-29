"""The existing unstarted-reservation operation stays bound to one demo job."""
import sqlite3
import unittest

from campaign_ledger import packed, sha
from demo_agent import digest, read_json
from studio_research_authority import command, demo_agent_scope, operation
import test_demo_agent as fixtures


class DemoReservationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DemoAgentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_only_current_tool_job_and_exact_release_request_are_admitted(self):
        f = self.fixture
        f.agent._adopt_installed_binary(digest(f.binary))
        session = read_json(f.root / 'session.json')
        db = sqlite3.connect(f.root / 'studio.sqlite')
        self.addCleanup(db.close)
        binding = packed(dict(terminal_id='terminal-one', run_id='session-one'))
        state = dict(owner='agent', generation=2)
        with operation('run-batch'), demo_agent_scope(root=f.root,
            installation_sha256=sha(f.agent.install), account=session['account'], job_id='chosen'):
            exact = dict(command='queue.release_reservation', request_id='chosen-release-reservation',
                payload=dict(job_id='chosen', reservation_id='original-reservation'))
            self.assertIsNone(command(db, binding, state, exact, actor='agent'))
            for request in (exact | dict(request_id='arbitrary'),
                exact | dict(payload=dict(job_id='foreign', reservation_id='original-reservation')),
                exact | dict(command='control.grant_agent')):
                with self.assertRaises(ValueError):
                    command(db, binding, state, request, actor='agent')
            with self.assertRaises(ValueError):
                command(db, binding, dict(owner='human', generation=3), exact, actor='agent')


if __name__ == '__main__':
    unittest.main()
