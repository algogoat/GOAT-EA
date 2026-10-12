"""run-batch on the research terminal starts a detached driver; a refusal it raises before its journal keeps its code.

GOAT-EA#223 refuses a package prepared before GOAT Research with PACKAGE_PREDATES_RESEARCH_PROFILE before any
journal. The detached child used to exit with only "Detached driver exited before a journal was recorded", so the
app (goatai#2488, keyed on refusal_code only) could not re-prepare. The child now records the refusal on its own
worker record and the caller returns it in the direct path's exact shape.

RealDetachedPathTests runs the real caller, the real durable host (studio_durable_driver.launch and bootstrap) and a
real python child running `_drive-batch` up to the real legacy-package check. Only the Windows task registration
(the repo's own seam, studio_durable_driver.subprocess.run) and the broker scope (_studio, which would attach to MT5)
are replaced. No MT5, no real installation: everything lives in a temp folder.
"""
from contextlib import contextmanager, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_agent
from demo_agent import DemoAgent, read_json, write_json
from studio_installation import VERSION
from studio_refusal import Refusal
from studio_research_profile import LEGACY_PACKAGE_REFUSAL, PACKAGE_REFUSAL_CODE, legacy_package_refusal

BATCH = 'old-batch'
BROKER = dict(login='3000082754', server='Darwinex-Demo')
CONTROLLER_DIR = str(Path(__file__).resolve().parent)


def lay_out(folder):
    """A temp installation whose prepared batch predates GOAT Research. Returns the installation receipt path."""
    folder = Path(folder)
    root, data, common = folder / 'state', folder / 'data', folder / 'common'
    for path in (root, data / 'MQL5/Files/GOATStudio', common, folder / 'bin'):
        path.mkdir(parents=True, exist_ok=True)
    (folder / 'bin/terminal64.exe').write_bytes(b'fixture, never run')
    binary = data / 'MQL5/Experts/GOAT-EA/GOAT V1.49.ex5'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fixture-ea')
    installation = root / 'installation.json'
    installation.write_text(json.dumps(dict(schema_version=1, controller_version=VERSION, ea_version='1.49',
        ea_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), controller_state_root=str(root),
        terminal_data_root=str(data), common_files_root=str(common),
        terminal_executable=str(folder / 'bin/terminal64.exe'), ea_relative_path=r'GOAT-EA\GOAT V1.49.ex5')))
    (root / 'session.json').write_text(json.dumps(dict(directory_id='session-one', terminal_id='terminal-one',
        run_id='session-one', demo_only=True, authority_kind='demo_direct', account=dict(BROKER))))
    # Packaged before batches ran on GOAT Research: its plan names the monitor profile.
    package = root / 'packages' / BATCH
    package.mkdir(parents=True)
    (package / 'studio-plan.json').write_text(json.dumps(dict(research_binding=dict(
        research_profile='GOAT-Studio-' + 'a' * 32, report_location_bridge='installation_to_data_v1',
        startup_monitor=dict(expert='GOAT.ex5', preset='GOAT Studio Agent.set', preset_sha256='b' * 64)))))
    return installation


class FixtureController:
    """The controller the broker scope yields, on the temp folder. Any native step fails the test."""

    def __init__(self, folder):
        folder = Path(folder).resolve()
        self.root = folder / 'state'
        self.local = folder / 'data/MQL5/Files/GOATStudio'
        self.install = dict(controller_state_root=str(self.root), terminal_data_root=str(folder / 'data'),
                            common_files_root=str(folder / 'common'))
        self.session = json.loads((self.root / 'session.json').read_text())

    def job(self, job_id):
        return dict(job_id=job_id, status='pending')

    def state(self):
        return dict(owner='agent', generation=1, queue=[self.job(BATCH)])

    def start_config(self, *args, **kwargs):
        raise AssertionError('a refused package never reaches a config start')

    def start(self, *args, **kwargs):
        raise AssertionError('a refused package never reaches a start')


@contextmanager
def fixture_studio(agent, operation_name, **kwargs):
    """DemoAgent._studio without the broker readback (which attaches to MT5)."""
    yield FixtureController(agent.root.parent), dict(BROKER)


def child_seam():
    """Run inside the real child before the durable host's bootstrap: the same broker-scope seam as the caller."""
    DemoAgent._studio = fixture_studio


# The detached child: the real studio_durable_driver.bootstrap, so the real demo_agent main runs `_drive-batch`.
CHILD = ('import sys; sys.path.insert(0, sys.argv[1]); import test_detached_refusal_passthrough as fixture; '
         'fixture.child_seam(); import studio_durable_driver; '
         'raise SystemExit(studio_durable_driver.bootstrap(sys.argv[2]))')


@unittest.skipUnless(os.name == 'nt', 'run-batch detaches through the Windows durable host')
class RealDetachedPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.installation = lay_out(self.temp.name)
        self.children = []
        self.addCleanup(self.reap)

    def reap(self):
        for child in self.children:
            try:
                child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()

    def register(self, *args, **kwargs):
        """The Windows task registration, replaced: start the envelope's bootstrap as a real python child."""
        worker = read_json(Path(self.temp.name).resolve() / 'state/demo-agent/workers' / (BATCH + '.json'))
        self.children.append(subprocess.Popen([sys.executable, '-c', CHILD, CONTROLLER_DIR, worker['launch_envelope']],
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        return SimpleNamespace(returncode=0)

    def test_the_real_child_refusal_reaches_run_batch_in_the_direct_shape(self):
        stderr = io.StringIO()
        with patch.object(DemoAgent, '_studio', fixture_studio), \
                patch('studio_durable_driver.subprocess.run', side_effect=self.register), redirect_stderr(stderr):
            code = demo_agent.main(['--installation', str(self.installation), 'run-batch', '--batch-id', BATCH,
                                    '--max-seconds', '600'])
        self.reap()
        reply = json.loads(stderr.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 1, reply)
        self.assertEqual(len(self.children), 1, 'one real detached child')
        self.assertEqual(reply, dict(ok=False, code='REFUSED', error=LEGACY_PACKAGE_REFUSAL,
                                     refusal_code=PACKAGE_REFUSAL_CODE, batch_id=BATCH, kind='batch', prepare_again=True,
                                     next_action='Prepare the same plan again under a new batch ID, then start that batch.'))
        self.assertTrue(reply['error'].startswith('This batch was prepared by an older GOAT; it will be prepared again.'))
        root = Path(self.temp.name).resolve() / 'state'
        worker = read_json(root / 'demo-agent/workers' / (BATCH + '.json'))
        self.assertEqual((worker['status'], worker['refusal_code'], worker['error']),
                         ('refused', PACKAGE_REFUSAL_CODE, LEGACY_PACKAGE_REFUSAL))
        self.assertEqual(worker['refusal_fields'], dict(batch_id=BATCH, kind='batch', prepare_again=True,
                         next_action='Prepare the same plan again under a new batch ID, then start that batch.'))
        self.assertFalse((root / 'batch-drivers' / (BATCH + '.json')).exists(), 'refused before any journal')
        # The child's own CLI printed the direct path's reply into its log: the caller's reply is the same JSON.
        log = root / 'demo-agent/workers' / (BATCH + '-' + worker['nonce'] + '.log')
        direct = json.loads([line for line in log.read_text(encoding='utf-8').splitlines() if line.startswith('{')][-1])
        self.assertEqual(reply, direct)
        finished = read_json(log.with_suffix('.finished.json'))
        self.assertEqual((finished['exit_code'], finished['nonce']), (1, worker['nonce']))


class CallerTests(unittest.TestCase):
    """The caller's wait, with a fake launch: only this nonce's recorded refusal changes the reply."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.agent = DemoAgent(lay_out(self.temp.name), process=SimpleNamespace())
        self.worker_path = self.agent.state_root / 'workers' / (BATCH + '.json')

    def launch_writing(self, change):
        def launch(argv, *, log_path, worker_path):
            nonce = argv[argv.index('--nonce') + 1]
            write_json(worker_path, dict(read_json(worker_path), **change(nonce)))
            return SimpleNamespace(pid=4321, poll=lambda: 1)
        return launch

    def run_batch(self, change):
        with patch.object(DemoAgent, '_studio', fixture_studio), \
                patch('studio_durable_driver.launch', side_effect=self.launch_writing(change)):
            return self.agent.run_batch(BATCH, 600)

    def test_a_recorded_refusal_reaches_the_caller_with_code_and_fields(self):
        fields = dict(batch_id=BATCH, kind='batch', prepare_again=True, next_action='Prepare again.')
        with self.assertRaises(Refusal) as caught:
            self.run_batch(lambda nonce: dict(status='refused', refusal_code=PACKAGE_REFUSAL_CODE,
                                              refusal_fields=fields, error=LEGACY_PACKAGE_REFUSAL))
        self.assertEqual((str(caught.exception), caught.exception.code, caught.exception.fields),
                         (LEGACY_PACKAGE_REFUSAL, PACKAGE_REFUSAL_CODE, fields))

    def test_an_early_exit_without_a_refusal_keeps_the_old_message(self):
        with self.assertRaisesRegex(ValueError, 'Detached driver exited before a journal was recorded; inspect ') as caught:
            self.run_batch(lambda nonce: dict(status='failed', error='The terminal lock stayed busy'))
        self.assertNotIsInstance(caught.exception, Refusal)

    def test_a_stale_refusal_of_another_nonce_is_ignored(self):
        with self.assertRaisesRegex(ValueError, 'Detached driver exited before a journal was recorded') as caught:
            self.run_batch(lambda nonce: dict(status='refused', nonce='f' * 32, refusal_code=PACKAGE_REFUSAL_CODE,
                                              refusal_fields=dict(batch_id=BATCH), error=LEGACY_PACKAGE_REFUSAL))
        self.assertNotIsInstance(caught.exception, Refusal)

    def test_a_malformed_record_is_ignored(self):
        for bad in (dict(refusal_code='not a code'), dict(refusal_fields=['batch_id']), dict(error='')):
            with self.subTest(bad=bad):
                record = dict(status='refused', refusal_code=PACKAGE_REFUSAL_CODE, refusal_fields={},
                              error=LEGACY_PACKAGE_REFUSAL)
                record.update(bad)
                with self.assertRaisesRegex(ValueError, 'Detached driver exited before a journal was recorded') as caught:
                    self.run_batch(lambda nonce: record)
                self.assertNotIsInstance(caught.exception, Refusal)
                self.worker_path.unlink()

    def test_batch_driver_status_reports_a_refused_start_without_a_journal(self):
        write_json(self.worker_path, dict(schema_version=1, batch_id=BATCH, nonce='e' * 32, status='refused',
                                          refusal_code=PACKAGE_REFUSAL_CODE, refusal_fields=dict(batch_id=BATCH),
                                          error=LEGACY_PACKAGE_REFUSAL))

        @contextmanager
        def scope(operation_name, batch_id):
            yield FixtureController(self.temp.name), dict(BROKER), None
        with patch.object(self.agent, '_batch_read_scope', side_effect=scope), \
                patch('studio_batch_driver.status', side_effect=AssertionError('no journal to read')):
            reply = self.agent.batch_driver_status(BATCH)
        self.assertIsNone(reply['driver'])
        self.assertEqual((reply['worker']['status'], reply['worker']['refusal_code'], reply['worker']['error']),
                         ('refused', PACKAGE_REFUSAL_CODE, LEGACY_PACKAGE_REFUSAL))
        # Any other worker record still reads the journal as before.
        write_json(self.worker_path, dict(schema_version=1, batch_id=BATCH, nonce='e' * 32, status='failed', error='x'))
        with patch.object(self.agent, '_batch_read_scope', side_effect=scope), \
                patch('studio_batch_driver.status', return_value=dict(status='observing')) as status:
            self.assertEqual(self.agent.batch_driver_status(BATCH)['driver'], dict(status='observing'))
        status.assert_called_once()


class ChildTests(unittest.TestCase):
    """_drive_batch records only a Refusal raised before its journal, only on its own nonce's record."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.agent = DemoAgent(lay_out(self.temp.name), process=SimpleNamespace())
        self.worker_path = self.agent.state_root / 'workers' / (BATCH + '.json')
        self.nonce = 'a' * 32

    def drive(self, error, *, journal=False):
        write_json(self.worker_path, dict(schema_version=1, batch_id=BATCH, nonce=self.nonce, status='spawned',
                                          resume=False, max_seconds=600))
        def run(controller, batch_id, **kwargs):
            if journal:
                write_json(self.agent.root / 'batch-drivers' / (batch_id + '.json'), dict(status='start_issued'))
            raise error
        with patch.object(DemoAgent, '_studio', fixture_studio), patch('studio_batch_driver.run', side_effect=run):
            with self.assertRaises(type(error)) as caught:
                self.agent._drive_batch(BATCH, self.nonce, 600)
        self.assertIs(caught.exception, error, 'the original exception still reaches the CLI')
        return read_json(self.worker_path)

    def test_a_refusal_before_the_journal_is_recorded_on_the_worker(self):
        worker = self.drive(legacy_package_refusal(BATCH))
        self.assertEqual((worker['status'], worker['nonce'], worker['refusal_code'], worker['error']),
                         ('refused', self.nonce, PACKAGE_REFUSAL_CODE, LEGACY_PACKAGE_REFUSAL))
        self.assertEqual((worker['refusal_fields']['batch_id'], worker['refusal_fields']['kind'],
                          worker['refusal_fields']['prepare_again']), (BATCH, 'batch', True))
        self.assertEqual(str(DemoAgent._refused_start(self.worker_path, self.nonce)), LEGACY_PACKAGE_REFUSAL)

    def test_other_errors_and_refusals_after_the_journal_change_nothing(self):
        self.assertEqual(self.drive(ValueError('Batch dispatch refused: disk_low'))['status'], 'supervising')
        self.assertEqual(self.drive(Refusal('late', 'SOME_LATER_CODE'), journal=True)['status'], 'supervising')


if __name__ == '__main__':
    unittest.main()
