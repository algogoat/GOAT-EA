// Mutation check for scripts/test_studio_steady_panel.cjs: each change below brings back a
// double paint, a repeated write or a lost final state in a temporary copy of the production
// sources, and the harness must fail. MQL-free; the repository files are never modified.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const repo=path.join(__dirname,'..');
const files=['GOATStudioUI.mqh','Optimizer.mqh'];
const R=String.raw;
const harness='test_studio_steady_panel.cjs';
// [label, file, from, to]
const mutations=[
  ['EX33 pre-paint of the handoff button returns','GOATStudioUI.mqh',R`   GoatStudioSteadyText(m_btnAddQueue,"SAVE SETTINGS");`,R`   m_btnStop.Text("GIVE TO AGENT"); GoatStudioSteadyText(m_btnAddQueue,"SAVE SETTINGS");`],
  ['agent chip painted directly','GOATStudioUI.mqh',R`stop_text="AGENT CONNECTED";`,R`m_btnStop.Text("AGENT CONNECTED"); stop_text="AGENT CONNECTED";`],
  ['text written when unchanged','GOATStudioUI.mqh',R`if(control.Text()!=value) control.Text(value);`,R`control.Text(value);`],
  ['text colour written when unchanged','GOATStudioUI.mqh',R`if(text!=clrNONE && control.Color()!=text) control.Color(text);`,R`if(text!=clrNONE) control.Color(text);`],
  ['background written when unchanged','GOATStudioUI.mqh',R`if(back!=clrNONE && control.ColorBackground()!=back) control.ColorBackground(back);`,R`if(back!=clrNONE) control.ColorBackground(back);`],
  ['border written when unchanged','GOATStudioUI.mqh',R`if(border!=clrNONE && control.ColorBorder()!=border) control.ColorBorder(border);`,R`if(border!=clrNONE) control.ColorBorder(border);`],
  ['enabled state written when unchanged','GOATStudioUI.mqh',R`   if(control.IsEnabled()==enabled) return;`,''],
  ['compact card hides and re-shows the handoff button','GOATStudioUI.mqh',R`|| child==GetPointer(m_btnStop)`,''],
  ['compact card hides and re-shows its backdrop','GOATStudioUI.mqh',R`child==GetPointer(c_Wnd_OPT) || `,''],
  ['pending request leaves Take Control enabled','GOATStudioUI.mqh',R`start_enabled=false; stop_enabled=false;`,R`stop_enabled=false;`],
  ['agent chip loses its lime border','GOATStudioUI.mqh',R`stop_text_color=C'190,242,100'; stop_border=C'190,242,100';`,R`stop_text_color=C'190,242,100';`],
  ['handoff loses its lime fill','GOATStudioUI.mqh',R`{stop_back=C'190,242,100'; stop_border=C'190,242,100'; stop_text_color=C'11,12,14';}`,R`{}`],
  ['status line pre-painted in ManagedRefresh','GOATStudioUI.mqh',R`   // The status line is written once, below, after the draft and receipt checks.`,R`   m_edtBatchProgress.Text(status);`],
  ['forward date stays enabled outside Custom','GOATStudioUI.mqh',R`GoatStudioSteadyEnabled(m_dtForward,m_cmbForward.Select()=="Custom");`,R`if(m_cmbForward.Select()=="Custom") GoatStudioSteadyEnabled(m_dtForward,true);`],
  ['read-only stage pre-paints the managed buttons','Optimizer.mqh',R`      if(!GoatStudioManaged())`,R`      if(true)`],
];
const scratch=fs.mkdtempSync(path.join(process.env.GOAT_MUTATION_TMP||os.tmpdir(),'goat-steady-panel-mutation-'));
function run(dir){return spawnSync(process.execPath,[path.join(__dirname,harness)],{env:{...process.env,GOAT_EA_ROOT:dir},encoding:'utf8',timeout:60000});}
let killed=0;const survivors=[];
try{
  const base=path.join(scratch,'base');fs.mkdirSync(base);
  for(const f of files)fs.copyFileSync(path.join(repo,f),path.join(base,f));
  const clean=run(base);if(clean.status!==0)throw new Error('unmutated sources fail '+harness+':\n'+clean.stdout+clean.stderr);
  mutations.forEach(([label,file,rawFrom,rawTo],n)=>{
    // Sources are CRLF; template literals are LF. Match and write CRLF either way.
    const from=rawFrom.replace(/\r?\n/g,'\r\n'),to=rawTo.replace(/\r?\n/g,'\r\n');
    const dir=path.join(scratch,'m'+n);fs.mkdirSync(dir);
    for(const f of files)fs.copyFileSync(path.join(base,f),path.join(dir,f));
    const target=path.join(dir,file),text=fs.readFileSync(target,'utf8');
    if(text.split(from).length!==2)throw new Error('mutation anchor is not unique: '+label);
    fs.writeFileSync(target,text.replace(from,()=>to));
    if(run(dir).status===0)survivors.push(label);else killed++;
  });
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
if(survivors.length){console.error('Surviving mutations: '+survivors.join('; '));process.exit(1);}
console.log(JSON.stringify({mutations:mutations.length,killed}));
