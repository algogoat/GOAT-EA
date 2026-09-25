"""Exercise production-function tests against all three pinned backports."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='goat-management-variants-') as temp:
    output=Path(temp)/'sources'
    subprocess.run([sys.executable,str(root/'scripts/build_management_variants.py'),'--output',str(output)],check=True)
    for variant in json.loads((output/'manifest.json').read_text()):
        source=Path(variant['source'])
        env={**os.environ,'GOAT_TEST_ROOT':str(source.parent),'GOAT_TEST_MAIN':source.name,'GOAT_TEST_BASE':variant['base']}
        print('Testing',variant['variant'],flush=True)
        subprocess.run(['node',str(root/'scripts/test_management_boot.cjs')],env=env,check=True)
