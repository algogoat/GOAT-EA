"""Mutation check for research-only below_score exports in the controller (GOAT-EA BS42, goatai#1885).

Each fail-closed guard is weakened in a temporary copy of controller/ and
controller/test_studio_below_score.py must fail. The repository is never modified.
Works with an embedded Python that ignores cwd (sys.path is set here).
GOAT_MUTATION_TMP may name the scratch folder (default: the system temp folder).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
RUNNER = ('import sys,unittest\n'
          'root=sys.argv[1]\n'
          'sys.path[:]=[p for p in sys.path if not p.rstrip("\\\\/").lower().endswith("controller")]\n'
          'sys.path.insert(0,root)\n'
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_below_score.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
EQ, EV, STATUS, CATCHUP = 'studio_export_qualification.py', 'studio_evidence.py', 'studio_research_status.py', 'studio_catchup.py'
MUTATIONS = [
    # The tier: either signal is enough, and an unknown tier is research only too.
    ('the header line is ignored', EQ, "            if match:\n                return BELOW_SCORE if", "            if False:\n                return BELOW_SCORE if"),
    ('an unknown tier reads as standard', EQ,
     "return BELOW_SCORE if match.group(1) == BELOW_SCORE else 'unrecognised:' + match.group(1)[:40]",
     "return BELOW_SCORE if match.group(1) == BELOW_SCORE else STANDARD_TIER"),
    ('the below_score folder is ignored', EQ, "        if len(parents) > 2 and parents[2].name.lower() == BELOW_SCORE_FOLDER:",
     "        if False:"),
    ('the whole SET is read for the tier', EQ, "            if index >= TIER_HEADER_LINES:\n                break\n", ""),
    # The stamp: an attempt, never a pass.
    ('a research-only stamp keeps passed', EQ, "    return dict(stamp, status='unknown', selection=SELECTION['unknown'], missed=[BELOW_SCORE],",
     "    return dict(stamp, missed=[BELOW_SCORE],"),
    ('stamp_set never reads the tier of a passing set', EQ,
     "    if stamp['status'] == 'passed' or with_sha256 or raw_cache:", "    if with_sha256 or raw_cache:"),
    ('stamp_set ignores the folder on the status path', EQ,
     "    elif export_tier(None, path) != STANDARD_TIER:", "    elif False:"),
    ('scan_run mixes research units into nothing (no count)', EQ,
     "    counts['below_score_sets'] = len(research)", "    counts['below_score_sets'] = 0"),
    ('scan_run stamps research units by thresholds alone', EQ,
     "        stamp = stamp_set(set_path, thresholds)\n        research.append(",
     "        stamp = dict(qualify(file_name_tokens(set_path.name[:-4]), thresholds), set_name=set_path.name, set_sha256='0' * 64)\n        research.append("),
    ('export scan offers a tagged unit', 'studio_export_scan.py', "        stamp = research_only_stamp(stamp, export_tier(", "        stamp = (lambda s, t: s)(stamp, export_tier("),
    # Evidence and catch-up.
    ('read_export lets a research unit pass', EV, "    qualification = research_only_stamp(qualification, tier)\n", ""),
    ('a research unit keeps the EA native pass (re-test eligible)', EQ,
     "                status_before_tier=stamp.get('status'), ea_native_passed=False,",
     "                status_before_tier=stamp.get('status'),"),
    ('a run folder scan skips the research folder', EV,
     "    bases = [base] + ([path / BELOW_SCORE_FOLDER] if base == deploy", "    bases = [base] + ([] if base == deploy"),
    ('catch-up re-tests a research unit by default', CATCHUP, "        elif not include_research_only:\n", "        elif False:\n"),
    ('include_below_threshold admits a research unit', CATCHUP, "    if export.get('research_only'):\n", "    if export.get('research_only') and not include_below_threshold:\n"),
    ('the research opt-in admits ordinary below-threshold sets', CATCHUP,
     "    elif not eligible and not include_below_threshold:", "    elif not eligible and not include_below_threshold and not include_research_only:"),
    ('an unknown tier re-tested', CATCHUP, "        if tier != 'below_score':\n", "        if False:\n"),
    ('the re-test loses its tier', CATCHUP, "    tail = ',tier=below_score' if tier == 'below_score' else ''", "    tail = ''"),
    ('the re-test EA_Desc ignores the tier', CATCHUP, "EA_Desc=_export_desc(alias, window, tier)", "EA_Desc=_export_desc(alias, window)"),
    ('evidence-version.json drops the tier', CATCHUP,
     "                       export_tier=spec.get('export_tier', 'standard'), research_only=bool(spec.get('research_only')),\n", ""),
    ('the manifest drops the research opt-in', CATCHUP,
     "                        include_research_only=plan.get('include_research_only', False), native_launch_qualified=False)",
     "                        native_launch_qualified=False)"),
    # Item 4 and its reasons.
    # Claude-Mac 6026738987 item 2: the re-test must read back its original's tier.
    ('a re-test that reads back another tier is collected', CATCHUP,
     "        if (got_tier, got_research) != (want_tier, want_research):\n", "        if False:\n"),
    ('the read-back trusts a research-only original', CATCHUP,
     "        want_tier, want_research = spec.get('export_tier', 'standard'), bool(spec.get('research_only'))\n",
     "        want_tier, want_research = 'standard', False\n"),
    # Claude-Mac 6026738987 item 3: the finish reply carries each member's research-only set count for the matrix.
    ('finish omits the below_score sets', 'studio_finish.py', "below_score_sets=below_score_sets(found[i]))", "below_score_sets=0)"),
    ('a lost or unreadable pick counts its sets', STATUS,
     "    return kept if below.get('result') == 'exported' and kept in (1, 2) else 0\n", "    return kept or 0\n"),
    ('an impossible count is recorded', STATUS,
     "    return kept if below.get('result') == 'exported' and kept in (1, 2) else 0\n",
     "    return kept if below.get('result') == 'exported' and kept else 0\n"),
    ('an unknown reason accepted', STATUS, "        facts['reason'] = reason if reason in BELOW_SCORE_REASONS else 'unreadable'", "        facts['reason'] = reason"),
    # Nit a: the user sentence's em dash, back to its UTF-8-as-cp1252 mojibake.
    ('the no-FWD-eligible sentence mojibake', STATUS, " ' — '\n                + str(outcome['score_qualifying_rows'])",
     " ' â€” '\n                + str(outcome['score_qualifying_rows'])"),
    ('multiple pairs need NO_FWD_ELIGIBLE_PASS counts', STATUS,
     " and 'no_fwd_eligible_pass' not in below and below.get('reason') != 'multiple_pairs')):", " and 'no_fwd_eligible_pass' not in below)):"),
    # research-status: its own count, never qualifying; unreadable reports never read as kept.
    ('research units counted as qualifying', STATUS,
     "    counted.update(below_score_sets=sum(research), below_score_members=sum(1 for n in research if n))",
     "    counted.update(below_score_sets=sum(research), below_score_members=sum(1 for n in research if n),\n"
     "                   qualifying=counted['qualifying'] + sum(1 for n in research if n))"),
    ('the headline hides research units', STATUS, "    if research:\n        # GOAT-EA BS42", "    if False:\n        # GOAT-EA BS42"),
    ('an unknown result reads as kept', STATUS,
     "    facts = dict(result=result if result in BELOW_SCORE_RESULTS else 'unreadable',", "    facts = dict(result=result,"),
    ('an exported pick without figures reads as kept', STATUS,
     "    elif result == 'exported':\n        facts['result'] = 'unreadable'\n", ""),
    ('a kept count that disagrees with slot 2 reads as exported', STATUS,
     "        if kept not in (1, 2) or (kept == 2) != (slot2 == 'kept'):", "        if kept not in (1, 2, 3):"),
    # Switch on (Claude-Mac 6023896492): NoFwdEligibleRows is a research result only with its proof; never silent.
    ('NoFwdEligibleRows not read', STATUS, "                             'NoFwdEligibleRows': NO_FWD_ELIGIBLE_ROWS}", "                             }"),
    ('a fall-through row without a below_score report accepted', STATUS,
     "            or below is None or below['result'] not in ('exported', 'lost', 'none', 'failed')\n", ""),
    ('nothing exported without its counts accepted', STATUS,
     "            or (below['result'] == 'none' and 'no_fwd_eligible_pass' not in below and below.get('reason') != 'multiple_pairs')):", "            ):"),
    ('a best score under the threshold accepted', STATUS,
     "or not x['score_threshold'] <= x['best_combined_score'] < float('inf')", "or not 0 <= x['best_combined_score'] < float('inf')"),
    ('no score-qualifying pass accepted', STATUS, "or not 1 <= x['score_qualifying_rows'] <= kept", "or not 0 <= x['score_qualifying_rows'] <= kept"),
    ('unreadable NO_FWD_ELIGIBLE_PASS counts accepted', STATUS,
     "        except (KeyError, ValueError):\n            facts['result'] = 'unreadable'\n    reason = values.get('below_score_reason')",
     "        except (KeyError, ValueError):\n            pass\n    reason = values.get('below_score_reason')"),
    ('the fall-through sentence hides what was kept', STATUS,
     "if below.get('result') == 'exported' else 'nothing was exported (no FWD-eligible pass)')", "if True else '')"),
    # The disk estimate prepare-batch shows.
    ('disk estimate ignores below_score', 'studio_export_disk.py',
     "    total_high = normal['high_bytes'] + below['high_p90_bytes']", "    total_high = normal['high_bytes']"),
    ('disk estimate uses the median for the high bound', 'studio_export_disk.py',
     "high_bytes=members * sets * p90)", "high_bytes=members * sets * median)"),
    ('disk estimate never warns', 'studio_export_disk.py',
     "        result['fits'] = int(free_bytes) - total_high >= MIN_FREE_BYTES", "        result['fits'] = True"),
    ('disk estimate ignores slot 2', 'studio_export_disk.py', "high_p90_bytes=int(2 * high_units * p90))", "high_p90_bytes=int(high_units * p90))"),
    ('an unreadable disk fits', 'studio_export_disk.py', "        result.update(free_bytes=None, fits=False)", "        result.update(free_bytes=None, fits=True)"),
    ('prepare-batch drops the disk estimate', 'studio_batch.py',
     "        native_started=False, disk_estimate=_disk_estimate(controller, checked), next_action=", "        native_started=False, next_action="),
    # Calibration and the held-out guard.
    ('gate calibration loads a tagged unit', 'studio_gate_calibration.py', "            if tier != STANDARD_TIER:\n                raise ValueError",
     "            if False:\n                raise ValueError"),
    ('research counts not redacted under a held-out lock', 'studio_heldout_guard.py',
     "    'below_score_sets', 'below_score_members', 'research_only', 'below_score', 'status_before_tier',\n", ""),
]


def run_mutation(mutation, scratch):
    label, name, old, new = mutation
    with tempfile.TemporaryDirectory(dir=scratch) as work:
        copy = Path(work) / 'controller'
        shutil.copytree(CONTROLLER, copy, ignore=shutil.ignore_patterns('__pycache__'))
        module = copy / name
        text = module.read_text(encoding='utf-8').replace('\r\n', '\n')
        if text.count(old) != 1:
            raise SystemExit('mutation anchor missing or repeated: ' + label)
        module.write_text(text.replace(old, new, 1), encoding='utf-8')
        log = Path(work) / 'log.txt'
        result = subprocess.run([sys.executable, '-B', '-c', RUNNER, str(copy), str(log)], timeout=900,
                                capture_output=True, text=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        report = log.read_text(encoding='utf-8') if log.exists() else ''
        # Caught means the below_score tests ran and failed, not that the copy broke.
        return result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report


def main():
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    jobs = int(os.environ.get('GOAT_MUTATION_JOBS') or min(8, os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(lambda m: run_mutation(m, scratch), MUTATIONS))
    for (label, _, _, _), failed in zip(MUTATIONS, results):
        print(('CAUGHT ' if failed else 'MISSED ') + label)
    caught = sum(results)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
