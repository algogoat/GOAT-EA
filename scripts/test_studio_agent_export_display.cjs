'use strict';
// Execute the same primitive policy expressions used by MQL, with retained-draft
// fixtures. These are source/behavior fixtures, not native chart qualification.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const policy=fs.readFileSync(path.join(root,'GOATStudioDraftDisplayPolicy.mqh'),'utf8');
const ui=fs.readFileSync(path.join(root,'GOATStudioUI.mqh'),'utf8');
function expression(name,args){
    const body=policy.match(new RegExp('bool '+name+'\\([^)]*\\)\\s*\\{([\\s\\S]*?)\\}'))?.[1];
    assert.ok(body,`actual MQL policy ${name} missing`);
    const value=body.match(/return ([^;]+);/)?.[1];
    assert.ok(value && /^[a-z_ !&|()]+$/.test(value),'Only the actual primitive boolean expression is executable');
    return new Function(...args,`return ${value};`);
}
const io=expression('GoatStudioHumanDraftIO',['human_owner']);
const hydrate=expression('GoatStudioHydrateSnapshot',['agent_owner','local_dirty','loaded','version_changed']);
const committed={SetsToExport:'2',MinScore:'60.0',TargetDD:'100',AdjustLots:false,BackOOSDate:'2024.12.26',MinARF:'0.2',MinSR:'2.5',IncludeBackOOS:true,IncludeSequenceData:true};
const edits={...committed,SetsToExport:' ',MinScore:' ',TargetDD:' ',MinARF:' ',MinSR:' ',IncludeBackOOS:false,IncludeSequenceData:false};
const original=Buffer.from(' { "revision":1094, "generation":2, "export":'+JSON.stringify(edits)+', "baseline":'+JSON.stringify(committed)+' }\n');
function fixture(raw=original){
    let bytes=Buffer.from(raw), display={...edits}, baseline={...committed}, owner='agent', revision=1094,generation=2,loaded=true,retainedBody='';
    const body=()=>JSON.stringify({revision,generation,export:display,baseline});
    return {refresh(snapshot){
        if(io(owner==='human')&&body()!==retainedBody){bytes=Buffer.from(body());retainedBody=body();}
        const changedOwner=owner!==snapshot.owner; owner=snapshot.owner;
        if(io(owner==='human')&&changedOwner){const saved=JSON.parse(bytes);display={...saved.export};baseline={...saved.baseline};revision=saved.revision;generation=saved.generation;retainedBody=body();}
        const dirty=JSON.stringify(display)!==JSON.stringify(baseline);
        if(hydrate(owner==='agent',dirty,loaded,revision!==snapshot.revision||generation!==snapshot.generation)){
            display={...snapshot.export};if(!('IncludeSequenceData' in display))display.IncludeSequenceData=true;
            baseline={...display};revision=snapshot.revision;generation=snapshot.generation;loaded=true;
        }
        return {...display};
    },bytes:()=>bytes,owner:()=>owner,revision:()=>revision,edit:values=>{display={...display,...values};}};
}
let checks=0;const check=fn=>{fn();checks++;};
const f=fixture();
check(()=>assert.deepEqual(f.refresh({owner:'agent',revision:1221,generation:2,export:committed}),committed));
check(()=>assert.deepEqual(f.bytes(),original,'Agent refresh retains ALL human draft bytes, including formatting'));
check(()=>assert.equal(f.revision(),1221));
const newer={...committed,MinSR:'3.0',BackOOSDate:'2025.06.26'};
check(()=>assert.deepEqual(f.refresh({owner:'agent',revision:1222,generation:2,export:newer}),newer));
check(()=>assert.deepEqual(f.refresh({owner:'agent',revision:1222,generation:3,export:committed}),committed));
check(()=>assert.deepEqual(f.refresh({owner:'human',revision:1223,generation:4,export:committed}),edits,'Human regains the retained unsaved editor values'));
check(()=>assert.deepEqual(f.bytes(),original,'Restoration does not consume or clear the human file'));
check(()=>assert.deepEqual(f.refresh({owner:'agent',revision:1224,generation:5,export:newer}),newer));
check(()=>assert.deepEqual(f.bytes(),original,'Ownership/display round trip does not rewrite human bytes'));
check(()=>assert.deepEqual(f.refresh({owner:'human',revision:1225,generation:6,export:committed}),edits));
f.edit({MinScore:'71'});
check(()=>assert.deepEqual(f.refresh({owner:'agent',revision:1226,generation:7,export:committed}),committed));
check(()=>assert.equal(JSON.parse(f.bytes()).export.MinScore,'71','Actual human changes are retained before giving away the editor'));
const invalid=fixture(Buffer.from('malformed retained human bytes'));
check(()=>assert.deepEqual(invalid.refresh({owner:'agent',revision:10,generation:2,export:committed}),committed));
check(()=>assert.equal(invalid.bytes().toString(),'malformed retained human bytes'));
check(()=>assert.throws(()=>invalid.refresh({owner:'human',revision:11,generation:3,export:committed})));
const legacy=fixture(),eight={...committed};delete eight.IncludeSequenceData;
check(()=>assert.equal(legacy.refresh({owner:'agent',revision:20,generation:2,export:eight}).IncludeSequenceData,true));
check(()=>assert.equal(legacy.refresh({owner:'agent',revision:20,generation:2,export:{...committed,IncludeSequenceData:false}}).IncludeSequenceData,false,'Same revision capability/field transition refreshes agent view'));
check(()=>assert.equal(io(false),false));
check(()=>assert.equal(hydrate(false,true,true,true),false,'Dirty human editor is never overwritten by a newer snapshot'));
// Tie the primitive policy fixtures to the real UI I/O and hydration call sites.
const persist=ui.slice(ui.indexOf('bool CStrategyTesterDialog::ManagedPersistDraft'),ui.indexOf('bool CStrategyTesterDialog::ManagedRestoreDraft'));
const restore=ui.slice(ui.indexOf('bool CStrategyTesterDialog::ManagedRestoreDraft'),ui.indexOf('void CStrategyTesterDialog::Destroy'));
const refresh=ui.slice(ui.indexOf('void CStrategyTesterDialog::ManagedRefresh'),ui.indexOf('void CStrategyTesterDialog::ManagedSave'));
check(()=>assert.ok(persist.indexOf('if(!GoatStudioHumanDraftIO(m_studioOwner=="human")) return true;')<persist.indexOf('GoatStudioWriteUtf8')));
check(()=>assert.ok(persist.indexOf('if(body==m_studioRetainedDraftBody) return true;')<persist.indexOf('GoatStudioWriteUtf8')));
check(()=>assert.ok(restore.indexOf('if(!GoatStudioHumanDraftIO(m_studioOwner=="human")) return true;')<restore.indexOf('m_studioDraftChecked')));
check(()=>assert.ok(restore.includes('m_studioRetainedDraftBody=ManagedDraftBody();')));
check(()=>assert.ok(refresh.indexOf('m_studioOwner=owner;')<refresh.indexOf('if(!ManagedRestoreDraft())')));
check(()=>assert.ok(refresh.includes('if(GoatStudioHydrateSnapshot(agent_mirror,dirty,m_studioLoaded,')));
check(()=>assert.ok(refresh.includes('Showing committed agent settings')&&refresh.includes('local human draft retained')));
console.log(`Studio agent committed export display: ${checks}/${checks} source fixtures passed; no native UI or trading exercised.`);
