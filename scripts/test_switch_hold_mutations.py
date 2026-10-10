"""Mutation check for the member switch hold (goatai#1885, Claude-Mac 6022613005 / 6036112715).

Each guard of studio_switch_hold and its member-loop wiring is removed in a temporary copy of
controller/ and the switch-hold tests must fail (or hang, which the timeout bounds): off by
default, the 90 s bound, the quiet slot, the publisher state, fail-open, and a stop, cancel or
pause ending a hold at once, and the wide slots (both publishers' cycles ENDed, odd :20 / even :40
to :55, Exp 01's log only beside Exp 02's). The repository is never modified. Works with an embedded Python
that ignores cwd (sys.path is set here).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
RUNNER = ('import os,sys,unittest\n'
          'os.environ.pop("GOAT_SWITCH_HOLD",None)\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[3:])\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
HOLD, SEED, AGENT = 'studio_switch_hold.py', 'studio_seed.py', 'demo_agent.py'
MUTATIONS = [
    ('runner on by default', SEED, '        self.switch_hold=None\n',
     "        self.switch_hold=dict(mode='exp02',state_path=None,max_seconds=90)\n"),
    ('unknown mode enables the hold', HOLD, '            if mode in OFF or mode not in MODES:', '            if mode in OFF:'),
    ('lane config without a valid mode enables the hold', HOLD,
     "        if not isinstance(data, dict) or data.get('mode') not in MODES:", "        if not isinstance(data, dict):"),
    ('bound not clamped to 90 s', HOLD, '    return min(number, MAX_HOLD_SECONDS)', '    return number'),
    ('bound never releases', HOLD, "        if now >= hold['deadline_unix']:", '        if False:'),
    ('over-long retained hold accepted', HOLD,
     '                    or not math.isfinite(until) or not 0 <= until - since <= MAX_HOLD_SECONDS):',
     '                    or not math.isfinite(until)):'),
    ('stale retained hold reused', HOLD, '            if now <= until + STALE_HOLD_SECONDS:', '            if True:'),
    ('clock that went back keeps holding', HOLD, '            if now < since:', '            if False:'),
    ('unreadable state holds instead of failing open', HOLD,
     "            return _release(hold, now, 'fail_open: publisher state unreadable (' + type(error).__name__ + ')', 'publisher_state')",
     "            return dict(start=False, hold=hold, journal=None)"),
    ('any odd/even minute is quiet', HOLD, '    if int(minute) % 2 == 1:', '    if True:'),
    ('slot opens at the cycle start', HOLD, '        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second < QUIET_SLOT_CLOSE',
     '        return second < QUIET_SLOT_CLOSE'),
    ('slot never closes', HOLD, '        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second < QUIET_SLOT_CLOSE',
     '        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second'),
    # Wide slots (goatai#2350 6094434583, Claude-Mac 6094451003): both logs, odd :20 / even :40 to :55, both cycles ENDed.
    ('wide odd slot keeps the narrow :35 open', HOLD, '        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second < QUIET_SLOT_CLOSE',
     '        return QUIET_SLOT_OPEN <= second < QUIET_SLOT_CLOSE'),
    ('narrow slot widened without the Exp 01 log', HOLD, '        return (WIDE_ODD_OPEN if wide else QUIET_SLOT_OPEN) <= second < QUIET_SLOT_CLOSE',
     '        return WIDE_ODD_OPEN <= second < QUIET_SLOT_CLOSE'),
    ('even slot opens at the cycle start', HOLD, '    return wide and WIDE_EVEN_OPEN <= second < QUIET_SLOT_CLOSE', '    return wide and second < QUIET_SLOT_CLOSE'),
    ('even slot never closes', HOLD, '    return wide and WIDE_EVEN_OPEN <= second < QUIET_SLOT_CLOSE', '    return wide and WIDE_EVEN_OPEN <= second'),
    ('even slot open without the Exp 01 log', HOLD, '    return wide and WIDE_EVEN_OPEN <= second < QUIET_SLOT_CLOSE', '    return WIDE_EVEN_OPEN <= second < QUIET_SLOT_CLOSE'),
    ('Exp 01 log ignored', HOLD, "    if config.get('exp01_state_path'):", '    if False:'),
    ('running publisher cycle ignored', HOLD, '        if not ended:', '        if False:'),
    ('idle publisher still waited for', HOLD,
     "        if now - newest['startedAt'] / 1000 <= PUBLISHER_IDLE_SECONDS:   # an idle publisher is not waited for",
     '        if True:'),
    ('Exp 01 log without Exp 02 state accepted (environment)', HOLD, '            if exp01 and not state:', '            if False:'),
    ('Exp 01 log without Exp 02 state accepted (lane config)', HOLD, '        if exp01 is not None and state is None:', '        if False:'),
    ('publisher state ignored', HOLD, "    if not config.get('state_path'):", '    if True:'),
    ('log head read instead of its tail', HOLD, '        start = max(0, size - tail_bytes)', '        start = 0'),
    ('waited time not reported', HOLD, "    details = dict(phase='released', waited_ms=int(round(waited * 1000)), reason=reason, source=source)",
     "    details = dict(phase='released', waited_ms=0, reason=reason, source=source)"),
    ('hold not journaled', SEED, '            try:self.locked_journal(event[0],event[1])', '            try:pass'),
    ('release not kept on the member', SEED, "            if event is not None:item['switch_hold']=event[1]", '            pass'),
    ('hold not retained across slices', SEED, "            state['switch_hold']=result['hold'];self._save(root,state)", '            pass'),
    ('stop does not end a hold', SEED, "                    if self.stop_requested():return 'stop'", "                    if False:return 'stop'"),
    ('stop during a hold is not returned', SEED,
     "                if self._hold_wait(batch_id,max(0,min(1,deadline-self.clock(),holding-self.clock())))=='stop':",
     "                if self._hold_wait(batch_id,max(0,min(1,deadline-self.clock(),holding-self.clock())))=='never':"),
    ('pause does not end a hold', SEED, "            if self.paused(batch_id):return 'pause'", "            if False:return 'pause'"),
    ('cancel does not end a hold', SEED, "            if mark()!=before:return 'state_changed'", "            if False:return 'state_changed'"),
    ('hold waits in one long sleep', SEED, '            self.sleep(min(self.HOLD_POLL_SECONDS,remaining))', '            self.sleep(remaining)'),
    ('member started despite the hold', SEED, '                        if holding is None:\n                            self._before_start(spec)',
     '                        if True:\n                            self._before_start(spec)'),
    ('demo lane never loads the PC config', AGENT,
     '        runner.switch_hold = load_config(os.environ, self.state_root / CONFIG_NAME)', '        runner.switch_hold = None'),
    ('demo lane stop does not reach the hold', AGENT, '        runner.stop_requested = self._seed_stop_reason',
     '        runner.stop_requested = None'),
]
TESTS = ['test_studio_switch_hold']


def main():
    caught = 0
    for label, name, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            try:
                result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)] + TESTS,
                                        timeout=90, capture_output=True, text=True,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                report = log.read_text(encoding='utf-8') if log.exists() else ''
                # Caught means the switch-hold tests ran and failed, not that the copy broke.
                failed = (result.returncode == 1 and 'FAILED (' in report
                          and 'ImportError' not in report and 'SyntaxError' not in report)
            except subprocess.TimeoutExpired:
                failed, label = True, label + ' (hang)'
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label, flush=True)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
