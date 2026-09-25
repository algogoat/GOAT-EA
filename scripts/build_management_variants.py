"""Materialize review-only R5/R6/R2 sources from pinned history; never install.

Apply the reviewed R2 management delta to each exact original source tree. Refuse
ambiguous/missing anchors rather than silently substituting another release.
"""
import argparse, difflib, hashlib, io, json, subprocess, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE='6705df944f0354f397b403bb3b53431de4c9cd54'
VARIANTS={'R5':('5e7a5cc0a6da997bf2a1ff9bd07ff169ae90ec68','GOAT V1.47.mq5'), 'R6':('5b5ce7a268c970e13ce4d1ea52391e9278253525','GOAT V1.47.mq5'), 'R2':(BASE,'GOAT V1.48.mq5')}
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT)
def norm(data): return data.decode('utf-8-sig').replace('\r\n','\n')
def write(path,text): path.write_bytes(b'\xef\xbb\xbf'+text.replace('\n','\r\n').encode())
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    baseline=norm(git('show',BASE+':GOAT V1.48.mq5'))
    candidate=norm((ROOT/'GOAT V1.48.mq5').read_bytes())
    before=baseline.splitlines(True);after=candidate.splitlines(True)
    opcodes=difflib.SequenceMatcher(a=before,b=after,autojunk=False).get_opcodes()
    manifests=[]
    for label,(revision,name) in VARIANTS.items():
        target=a.output/label;target.mkdir()
        with zipfile.ZipFile(io.BytesIO(git('archive','--format=zip',revision))) as z: z.extractall(target)
        original=norm((target/name).read_bytes());result=original
        original_build=next(l.split('"')[1] for l in original.splitlines() if 'define   GOAT_BUILD_ID ' in l)
        for tag,i,j,k,l in reversed(opcodes):
            if tag=='equal': continue
            old=''.join(before[i:j]);new=''.join(after[k:l])
            if i==j==1 and new=='#define GOAT_MANAGEMENT_ONLY_BOOT 1\n':
                assert result.startswith(before[0]);result=before[0]+new+result[len(before[0]):];continue
            if 'GOAT_BUILD_ID ' in old:
                result=result.replace(original_build,original_build+'-MANAGEMENT-R4');continue
            if 'GOAT_BUILD_MARKER ' in old:
                marker=next(line for line in original.splitlines(True) if 'define   GOAT_BUILD_MARKER ' in line)
                result=result.replace(marker,new);continue
            if old and result.count(old)==1: result=result.replace(old,new,1);continue
            # Insertions and repeated single lines need a unique surrounding anchor.
            done=False
            for context in range(1,9):
                left=''.join(before[max(0,i-context):i]);right=''.join(before[j:j+context]);anchor=left+old+right
                if result.count(anchor)==1:
                    result=result.replace(anchor,left+new+right,1);done=True;break
            if not done and not old:
                for context in range(3,9):
                    left=''.join(before[max(0,i-context):i]);right=''.join(before[j:j+context])
                    if left and result.count(left)==1:
                        result=result.replace(left,left+new,1);done=True;break
                    if right and result.count(right)==1:
                        result=result.replace(right,new+right,1);done=True;break
            if not done: raise RuntimeError(f'{label}: ambiguous/missing delta {i}:{j} {old[:100]!r}')
        write(target/name,result)
        for shared in ('GOATManagementBoot.mqh','GOATSequenceRecovery.mqh'):
            (target/shared).write_bytes((ROOT/shared).read_bytes())
        definitions=norm((target/'GOAT_Inputs_Definitions.mqh').read_bytes())
        expiry="datetime Expiry                  = D'2027.08.01 22:00:00';  // Year Month Day Hours Minutes Seconds"
        assert definitions.count(expiry)==1
        write(target/'GOAT_Inputs_Definitions.mqh',definitions.replace(expiry,'#ifndef GOAT_MANAGEMENT_ONLY_BOOT\n'+expiry+'\n#endif'))
        # Deliberately preserve each branch's original AI source and credential namespace.
        assert norm((target/'GOATAIWireV2.mqh').read_bytes())==norm(git('show',revision+':GOATAIWireV2.mqh'))
        assert 'Expiry' not in result
        manifests.append({'variant':label,'base':git('rev-parse',revision).decode().strip(),'source':str(target/name),'build':original_build+'-MANAGEMENT-R4','sha256':hashlib.sha256((target/name).read_bytes()).hexdigest(),'deployed':False})
    (a.output/'manifest.json').write_text(json.dumps(manifests,indent=2)+'\n')
    print(json.dumps(manifests,indent=2))
if __name__=='__main__': main()
