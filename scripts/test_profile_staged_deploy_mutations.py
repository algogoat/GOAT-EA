"""Mutation check for the profile-staged deploy controller (beta.25, goatai#1885 6033450916).

Each guard is broken in a temporary copy of controller/ and the named tests of
controller/test_studio_deploy_profile.py / test_studio_profile_staged_deploy.py must fail.
The repository is never modified. Works with an embedded Python that ignores cwd (sys.path is set here).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3:])\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
DEPLOY = 'studio_demo_deploy.py'
PROFILE = 'studio_deploy_profile.py'
MAILBOX = 'studio_agent_mailbox.py'
W = 'test_studio_deploy_profile.'
F = 'test_studio_profile_staged_deploy.ProfileStagedDeployTests.'
STARTUP = r"'\r\n[Experts]\r\nEnabled=0\r\nAccount=1\r\n').encode('utf-16')"
MUTATIONS = [
    # D1: Algo Trading stays off; the only switch is the human's.
    ('the startup ini turns Algo Trading on (Enabled=1)', DEPLOY, STARTUP, STARTUP.replace('Enabled=0', 'Enabled=1'),
     [W + 'StartupInvariantTests', F + 'test_the_profile_holds_the_dashboard_and_every_child_and_the_launch_has_no_startup_expert']),
    ('children are written with expertmode=4', PROFILE, "EXPERT_MODE = '5'", "EXPERT_MODE = '4'",
     [W + 'WriterGoldenTests.test_g1_the_expert_block_is_byte_for_byte_the_real_buildtemplate_output']),
    ('the startup ini names a [StartUp] expert', DEPLOY, STARTUP,
     STARTUP.replace(r"Account=1\r\n'", r"Account=1\r\n[StartUp]\r\nExpert=GOAT-EA\\GOAT V1.49.ex5\r\n'"),
     [W + 'StartupInvariantTests.test_the_startup_ini_has_exactly_one_enabled_line_and_it_is_off']),
    # D2: reported, never written.
    ('the startup ini writes AllowLiveTrading=1', DEPLOY, STARTUP, STARTUP.replace(r"Account=1\r\n'", r"Account=1\r\nAllowLiveTrading=1\r\n'"),
     [W + 'StartupInvariantTests']),
    ('preflight claims AllowLiveTrading is on', DEPLOY, "    result['allow_live_trading_default'] = allow_live",
     "    result['allow_live_trading_default'] = True", [F + 'test_preflight_reports_allow_live_trading_and_never_writes_it']),
    ('readiness drops the plain-English AllowLiveTrading step', DEPLOY,
     "        hint = ' ' + ALLOW_LIVE_TRADING_INSTRUCTION if untradable and allow_live_trading is not True else ''", "        hint = ''",
     [F + 'test_readiness_names_the_allow_live_trading_step_when_a_child_cannot_trade']),
    # The writer: BuildTemplate + GoatApplyAILaunchPolicy, byte for byte.
    ('the writer drops the AI policy', PROFILE,
     "    return apply_ai_policy(set_input_lines(raw), policy['aiMode'], policy['aiThreshold'], policy['aiProtocol'])",
     "    return set_input_lines(raw)", [W + 'WriterGoldenTests.test_g2_every_case_is_byte_for_byte_the_frozen_golden']),
    ('the writer trims ; lines (BuildTemplate keeps them)', PROFILE, "        if not line or line.find('=') <= 0:\n            continue",
     "        if not line or line.find('=') <= 0 or line.startswith(';'):\n            continue",
     [W + 'WriterGoldenTests.test_g1_the_expert_block_is_byte_for_byte_the_real_buildtemplate_output']),
    ('D1 is written as unit 2 (weeks)', PROFILE, "'D1': (1, 24)", "'D1': (2, 1)",
     [W + 'WriterGoldenTests.test_g2_every_case_is_byte_for_byte_the_frozen_golden']),
    ('the period is read from two characters (an M15 SET opens an M1 chart, as beta.24 did)', PROFILE,
     "    token = re.match(r'[A-Z0-9]*', file_name[comma + 1:]).group() if comma >= 0 else ''",
     "    token = file_name[comma + 1:comma + 3] if comma >= 0 else ''",
     [W + 'WriterRuleTests.test_periods_follow_mt5s_own_encoding_and_the_whole_token']),
    ('M15 and M30 are staged in beta.25', PROFILE, "for token in ('M1', 'M5', 'H1', 'H4', 'D1')}", "for token in ('M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1')}",
     [W + 'WriterRuleTests.test_periods_follow_mt5s_own_encoding_and_the_whole_token',
      F + 'test_unsupported_periods_lines_and_duplicate_members_are_refused_before_anything_is_written']),
    ('children are staged without the deployment nonce', PROFILE,
     "    return with_deploy_nonce(effective_input_lines(raw, policy), deployment_id)", "    return effective_input_lines(raw, policy)",
     [W + 'WriterRuleTests.test_every_child_carries_the_deployment_nonce_on_its_one_ea_desc_line',
      W + 'WriterGoldenTests.test_g2_every_case_is_byte_for_byte_the_frozen_golden']),
    ('an EA answer of rejected_deploy_next_retired is returned as a plain receipt', MAILBOX,
     "                if result['result'] == 'rejected_deploy_next_retired':\n                    raise retired_deploy_next()\n", "",
     ['test_studio_agent_setup.AgentSetupTests.test_an_ea_answer_of_rejected_deploy_next_retired_is_a_typed_refusal']),
    ('a lone CR is read as text', PROFILE, r"        if '\r' in piece:", "        if False:",
     [W + 'WriterRuleTests.test_lines_both_writers_could_read_differently_are_refused']),
    ('children shift one chart slot', PROFILE, "enumerate(members, start=DASHBOARD_SLOT + 1)", "enumerate(members, start=DASHBOARD_SLOT + 2)",
     [W + 'WriterGoldenTests.test_g2_the_whole_profile_and_its_state_file_are_the_frozen_golden']),
    ('the dashboard chart does not resume its saved rows', PROFILE, "'Dashboard_Resume_Saved=true'", "'Dashboard_Resume_Saved=false'",
     [W + 'WriterGoldenTests.test_g2_every_case_is_byte_for_byte_the_frozen_golden']),
    ('duplicate members are not refused', DEPLOY, "    deploy_profile.refuse_duplicates(prepared, policy)\n", "",
     [F + 'test_unsupported_periods_lines_and_duplicate_members_are_refused_before_anything_is_written']),
    ('a file GOAT did not stage in the profile folder is launched', DEPLOY, "    if profile.is_symlink() or extra:", "    if False:",
     [F + 'test_a_file_goat_did_not_stage_in_the_profile_folder_blocks_the_launch']),
    # Linking and D3.
    ('children_pending at the deadline counts as linked', DEPLOY, "            if last == 'children_linked' and rows_linked(rows):",
     "            if last in ('children_linked', 'children_pending'):", [F + 'test_children_pending_at_the_deadline_is_never_success']),
    ('a children_linked receipt is trusted without checking its rows', DEPLOY,
     "            if last == 'children_linked' and rows_linked(rows):", "            if last == 'children_linked':",
     [F + 'test_a_children_linked_receipt_with_an_unlinked_or_duplicate_row_is_not_accepted']),
    ('a link receipt showing Algo on or positions is accepted', DEPLOY,
     "            if receipt['tradingAllowed'] or receipt['positions'] or receipt['orders'] or not receipt['connected']:", "            if False:",
     [F + 'test_a_link_receipt_that_shows_algo_on_or_positions_is_never_accepted']),
    ('rows that never started are reported as not linked', DEPLOY,
     "reason=CHILD_NOT_LINKED if started else CHILD_NOT_STARTED", "reason=CHILD_NOT_STARTED if started else CHILD_NOT_LINKED",
     [F + 'test_a_child_that_never_starts_is_named_and_the_deploy_unwinds_itself']),
    ('the deploy does not unwind itself after child_not_started', DEPLOY, "            _unwind(controller, session, record, where, 'unwind-'",
     "            (lambda *a, **k: None)(controller, session, record, where, 'unwind-'",
     [F + 'test_a_child_that_never_starts_is_named_and_the_deploy_unwinds_itself']),
    ('a poll asks again while its unanswered request is still live', DEPLOY,
     "        sleep(LINK_RETRY_AFTER_TIMEOUT_SECONDS if last['result'] == 'receipt_timeout' else 1)", "        sleep(1)",
     [F + 'test_a_slow_dashboard_start_waits_out_the_unanswered_request_instead_of_failing']),
    ('a retry reuses the retained close attempt', DEPLOY, "    suffix = '' if attempt == 1 else '-a' + str(attempt)", "    suffix = ''",
     [F + 'test_an_auto_unwound_deploy_can_be_deployed_again_as_a_new_attempt']),
    ('a beta.24 template-staged journal is launched', DEPLOY,
     "    if record.get('profile_format') != deploy_profile.PROFILE_FORMAT and record['phase'] in", "    if False and record['phase'] in",
     [F + 'test_a_journal_staged_by_the_beta24_template_deploy_is_refused_before_any_launch']),
    ('the mailbox sends deploy_next again', MAILBOX, "PORTFOLIO_ACTIONS = ('status', 'audit', 'configure', 'apply_policy', 'link_children')",
     "PORTFOLIO_ACTIONS = ('status', 'audit', 'configure', 'apply_policy', 'link_children', 'deploy_next')",
     ['test_studio_agent_setup.AgentSetupTests.test_the_mailbox_no_longer_sends_deploy_next_but_settles_a_retained_one']),
    # Rollback.
    ('common.ini is edited although the previous profile changed', DEPLOY,
     "    if not intact:\n        return result | dict(reason='the previous profile folder changed", "    if False:\n        return result | dict(reason='the previous profile folder changed",
     [F + 'test_stop_leaves_common_ini_alone_when_the_previous_profile_changed']),
    ('common.ini is edited although MT5 names another profile', DEPLOY,
     "    if current != where['profile'].name:\n        return result", "    if False:\n        return result",
     [F + 'test_stop_leaves_common_ini_alone_when_mt5_names_another_profile']),
    ('stop renames the previous profile too', DEPLOY,
     "        for source in (where['state'], where['profile'], mailbox_root / 'request.json', mailbox_root / 'registration.json'):",
     "        for source in (where['state'], where['profile'], mailbox_root / 'request.json', mailbox_root / 'registration.json',"
     " Path((journal.get('previous_profile') or {}).get('path') or where['profile'])):",
     [F + 'test_stop_restores_the_previous_profile_exactly']),
    ('the ProfileLast edit rewrites the whole file', DEPLOY, "    patched = bom + ''.join(lines).encode(encoding)",
     "    patched = bom + ''.join(lines).replace('\\r\\n', '\\n').encode(encoding)",
     [F + 'test_profile_last_edits_are_exact_single_line_changes_in_any_encoding', F + 'test_stop_restores_the_previous_profile_exactly']),
    ('the previous profile is not restored after the unload', DEPLOY,
     "        rollback = restore_previous_profile(controller, journal, where, stamp, running=running)",
     "        rollback = dict(previous_profile=None, previous_profile_intact=None, profile_restored=False, reason='skipped')",
     [F + 'test_stop_restores_the_previous_profile_exactly']),
]


def main():
    caught = 0
    for label, name, old, new, tests in MUTATIONS:
        with tempfile.TemporaryDirectory() as work:
            copy = Path(work) / 'controller'
            shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
            module = copy / name
            text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
            if old not in text:
                raise SystemExit('mutation anchor missing: ' + label)
            module.write_text(text.replace(old, new, 1), encoding='utf-8')
            log = Path(work) / 'log.txt'
            result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log), *tests], timeout=900,
                                    capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = log.read_text(encoding='utf-8') if log.exists() else ''
            # Caught means the named tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label, flush=True)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
