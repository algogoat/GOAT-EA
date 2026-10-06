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
    ('catch-up re-tests a research unit by default', CATCHUP, "    if export.get('research_only') and not include_below_threshold:",
     "    if False:"),
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
