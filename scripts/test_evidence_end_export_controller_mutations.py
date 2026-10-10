"""Mutation check for the controller's EvidenceEnd export staging (EA FU35).

Each guard is weakened in a temporary copy of controller/ and
controller/test_studio_evidence_end_export.py must fail. The repository is never
modified. Works with an embedded Python that ignores cwd (sys.path is set here).
GOAT_MUTATION_TMP may name the scratch folder (default: the system temp folder).
"""
import os
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
          'suite=unittest.defaultTestLoader.discover(root,pattern="test_studio_evidence_end_export.py",top_level_dir=root)\n'
          'result=unittest.TextTestRunner(stream=open(sys.argv[2],"w",encoding="utf-8"),verbosity=1).run(suite)\n'
          'sys.exit(0 if result.wasSuccessful() else 1)\n')
EXPORT = 'studio_evidence_end_export.py'
VERIFY = 'activate_research_campaign.py'
MUTATIONS = [
    ('unsupported build gets EvidenceEnd', EXPORT, "capability.get('supported') is not True", "False"),
    ('any capability name accepted', EXPORT, "            or capability.get('capability') != CAPABILITY:", "            or False:"),
    ('AUTO staged instead of the resolved date', EXPORT, "value = mt5(parse_date(policy['target']))", "value = 'AUTO'"),
    ('staged value not checked against the target', EXPORT,
     "or evidence['ea_setting'] != dict(key=KEY, value=mt5(parse_date(evidence.get('target'))))):", "or False):"),
    ('native end label not checked', EXPORT, "if (evidence.get('native_export_end') != NATIVE_END\n", "if (False\n"),
    ('setting never serialized', EXPORT, "return export_text if value is None else export_text + KEY + '=' + value + '\\r\\n'", "return export_text"),
    ('unreadable installation assumed capable', EXPORT, "capability = dict(supported=False, capability=CAPABILITY, basis='installation_unbound')",
     "capability = dict(supported=True, capability=CAPABILITY, basis='installation_unbound')"),
    ('saved AUTO refused', EXPORT, "if value.strip().lower() == 'auto':", "if False:"),
    ('prepare ignores the EA capability', 'studio_batch.py', "    evidence = for_controller(controller, evidence)\n", ""),
    ('saved EvidenceEnd dropped on load', 'studio_batch.py', "        imported_plan['evidence_end'] = saved_evidence_end\n", "        pass\n"),
    ('saved EvidenceEnd parsed as a number', 'studio_batch.py', "if k != 'EvidenceEnd'", "if k != 'EvidenceEndX'"),
    ('package export file lacks EvidenceEnd', 'prepare_native_campaign.py',
     "export = with_evidence_end(serialize_export(export_settings), native)", "export = serialize_export(export_settings)"),
    ('manifest lacks EvidenceEnd', 'prepare_native_campaign.py',
     "            receipt['export_evidence_end'] = evidence_end_setting(native)\n", "            pass\n"),
    ('manifest EvidenceEnd not verified', VERIFY, "    if manifest.get('export_evidence_end')!=evidence_end:\n", "    if False:\n"),
    ('staged EvidenceEnd value not verified', VERIFY,
     "    if evidence_end is not None and parser['Export'][EVIDENCE_END_KEY]!=evidence_end:\n", "    if False:\n"),
    ('staged export keys not verified', VERIFY,
     "keys=set(expected)|({EVIDENCE_END_KEY} if evidence_end is not None else set())", "keys=set(parser['Export'])"),
]


def main():
    caught = 0
    scratch = os.environ.get('GOAT_MUTATION_TMP') or None
    for label, name, old, new in MUTATIONS:
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
            # Caught means the export tests ran and failed, not that the copy broke.
            failed = result.returncode == 1 and 'FAILED (' in report and 'ImportError' not in report and 'SyntaxError' not in report
            caught += failed
            print(('CAUGHT ' if failed else 'MISSED ') + label)
    print(f'{caught}/{len(MUTATIONS)} mutations caught')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
