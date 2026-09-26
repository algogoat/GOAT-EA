"""Source guards for MT5 retained globals; native activation remains required."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "GOATEADeviceActivation.mqh").read_text(encoding="utf-8-sig")
MAIN = (ROOT / "GOAT V1.49.mq5").read_text(encoding="utf-8-sig")

def body(name):
    start = SOURCE.index("{", SOURCE.index(name + "(void)"))
    depth = 1
    end = start + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[start+1:end-1]

class ActivationReloadSourceContract(unittest.TestCase):
    def test_all_non_pending_paths_reset_before_normal_initialization(self):
        wrapper = re.sub(r"//[^\n]*", "", body("GOATActivationReloadOnInit"))
        self.assertEqual(re.sub(r"\s+", "", wrapper),
            "if(GOATActivationReloadPendingOnInit())returntrue;GOATActivationReloadReset();returnfalse;")
        init = MAIN[MAIN.index("int OnInit("):MAIN.index("void OnDeinit(")]
        self.assertIn("if(GOATActivationReloadOnInit()) return INIT_SUCCEEDED;", init)

    def test_retained_globals_are_cleared_for_monitor_and_ordinary_deinit(self):
        # Evaluate the actual reset assignments; unlike a fresh-load fixture,
        # start with APPROVED and retained timer/reload values after both paths.
        reset = body("GOATActivationReloadReset")
        self.assertIn("GOATDeviceActivationScrub();", reset)
        scrub = body("GOATDeviceActivationScrub")
        for monitor in (True, False):
            with self.subTest(monitor=monitor):
                state = {"g_GOATDeviceActivationState": "APPROVED",
                    "g_GOATActivationReloadDeadline": "20000",
                    "g_GOATDeviceActivationReloadRequested": "true" if monitor else "false"}
                for code in (scrub, reset):
                    for key,value in re.findall(r"(g_GOAT\w+)\s*=\s*([^;]+);", code):
                        state[key] = value.strip()
                self.assertEqual(state["g_GOATDeviceActivationState"], "GOAT_DEVICE_ACTIVATION_INACTIVE")
                self.assertEqual(state["g_GOATActivationReloadDeadline"], "0")
                self.assertEqual(state["g_GOATDeviceActivationReloadRequested"], "false")

    def test_completed_ticket_guard_precedes_any_failure_mutation(self):
        required = body("GOATActivationReloadRequired")
        guard = required.index('completedPhase=="reinitialized"')
        reset = required.index("{GOATActivationReloadReset(); return;}")
        mutation = required.index("g_GOATDeviceActivationState=")
        self.assertLess(guard,reset)
        self.assertLess(reset,mutation)
        self.assertIn("completedBuild==GOAT_BUILD_ID",required[:mutation])
        self.assertIn("completedSymbol==Symbol()",required[:mutation])

    def test_expired_reload_requires_durable_ack(self):
        pending = body("GOATActivationReloadPendingOnInit")
        expired = pending.split("if(expires<",1)[1].split('if(phase=="switch_requested"',1)[0]
        self.assertIn('if(!GOATActivationReloadWrite("reinitialized"',expired)
        self.assertIn("GOATActivationReloadRequired(); return true;",expired)

if __name__ == "__main__":
    unittest.main()
