// B44 item 9 (goatai#2350): a failed panel never removes a chart, and no deploy-mode path opens a modal Alert().
// Before B44 "Panel GUI creation Failed" made OnInit return INIT_FAILED (a deployed child removed itself) and its
// Alert() window blocked a graceful terminal close. This runs the production GoatPanelCreate, SetEdit,
// GoatDeployMode and GoatDeployNotice after a syntax-only MQL-to-JS conversion, and pins the wiring: the Alert
// redirection covers every Alert() in the compile closure, and the panel is never read by trading code.
// Native check (documented in candidate-builds/beta17-B44/README.md): a build with GOAT_PANEL_FAIL_INJECT defined
// on a demo terminal; the child logs panel_unavailable, is adopted and trades, and the terminal closes gracefully.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const main=read('GOAT V1.49.mq5');
let passed=0;const ok=()=>passed++;
function unit(signature){
 // The definition (a prototype ends in ';', a definition in a new line).
 const a=main.indexOf(signature+'\n');assert.ok(a>=0,'missing '+signature);assert.equal(main.indexOf(signature+'\n',a+1),-1);
 let i=main.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<main.length;j++){if(main[j]==='{')depth++;if(main[j]==='}')depth--;}
 return main.slice(i+1,j-1);
}
const js=t=>t.replace(/\/\/.*$/gm,'').replace(/^#ifdef GOAT_PANEL_FAIL_INJECT\n.*\n#else\n(.*)\n#endif$/m,'$1')
 .replace(/\b(?:bool|int|string) (?=\w+=)/g,'let ').replace(/for\(int /g,'for(let ');

// 1) Three tries with a short backoff, a partial panel removed without ExpertRemove, then headless.
function panel(failures){
 const calls=[],sleeps=[],phases=[],prints=[];let made=0;
 const c={EA_Name_generated:'GOAT V1.49',REASON_INITFAILED:8,REASON_PROGRAM:0,ChartID:()=>7,ResetLastError:()=>{},GetLastError:()=>4102,
  IntegerToString:String,Sleep:n=>sleeps.push(n),Print:(...a)=>prints.push(a.join('')),GoatDeploymentPhase:(p,t,d,e)=>phases.push([p,d??'',e??0]),
  PanelDialog:{Create:()=>{calls.push('create');return ++made>failures;},Destroy:r=>calls.push('destroy:'+r)}};
 vm.createContext(c);
 const result=vm.runInContext('(function(panel_x1,panel_y1,panel_x2,panel_y2){'+js(unit('bool GoatPanelCreate(const int panel_x1,const int panel_y1,const int panel_x2,const int panel_y2)'))+'})',c)(10,20,300,400);
 return {result,calls,sleeps,phases,prints};
}
{const r=panel(99);
 assert.equal(r.result,false);assert.deepEqual(r.calls,['create','destroy:8','create','destroy:8','create','destroy:8']);
 assert.deepEqual(r.sleeps,[250,500]);assert.ok(r.calls.every(x=>x!=='destroy:0'),'never REASON_PROGRAM (which calls ExpertRemove)');
 assert.deepEqual(r.phases.map(p=>p[0]),['panel_retry','panel_retry','panel_retry','panel_unavailable']);
 assert.ok(r.prints.at(-1).includes('panel_unavailable'));ok();}
{const r=panel(1);assert.deepEqual([r.result,r.calls,r.sleeps],[true,['create','destroy:8','create'],[250]]);ok();}
{const r=panel(0);assert.deepEqual([r.result,r.calls,r.sleeps,r.phases],[true,['create'],[],[]]);ok();}
// 2) OnInit keeps the chart: no INIT_FAILED and no Alert for the panel any more; Run only on a real panel.
{assert.ok(!main.includes('Alert("Panel GUI creation Failed'));
 assert.match(main,/if\(MAGIC1==0\) \{\n[^\n]*\n       g_GoatPanelUnavailable=!GoatPanelCreate\(x1,y1,x2,y2\);\n       if\(!g_GoatPanelUnavailable\) \{Sleep\(100\); PanelDialog\.Run\(\); Sleep\(100\);\}\n      \}/);
 assert.match(main,/#ifdef GOAT_PANEL_FAIL_INJECT\n      bool panel_made=false;/);
 assert.ok(!/#define GOAT_PANEL_FAIL_INJECT/.test(main),'never defined in a release build');ok();}
// 3) Headless: SetEdit draws nothing, the news list is skipped, panel chart events and maximize are skipped.
{const touched=[];const c={FastSpeed_Flag:false,g_GoatPanelUnavailable:true,clrNONE:-1,GetFontName:x=>x};vm.createContext(c);
 const setEdit=vm.runInContext('(function(edit1,text,ctext=-1,Fsize=0,cback=-1,cborder=-1,font=0){'+js(unit('bool SetEdit(CEdit &edit1,string text,color ctext=clrNONE,int Fsize=0,color cback=clrNONE,color cborder=clrNONE,ENUM_FONT font=0)'))+'})',c);
 const edit=new Proxy({},{get:(_,k)=>(...a)=>touched.push(k)});
 assert.equal(setEdit(edit,'x',1,2,3,4,5),false);assert.deepEqual(touched,[]);
 c.g_GoatPanelUnavailable=false;assert.equal(setEdit(edit,'x',1),true);assert.deepEqual(touched,['Text','Color']);
 assert.match(unit('void NewsDisplayFunction(bool active,color clrtext)'),/^\s*if\(Mode_News==News_Disabled \|\| g_GoatPanelUnavailable\) return;/);
 const events=main.slice(main.indexOf('void OnChartEvent('),main.indexOf('void OnChartEvent(')+4000);
 assert.match(events,/else if\(!g_GoatPanelUnavailable\)[^\n]*\n      \{\n       PanelDialog\.HandleChartEvent/);
 assert.match(events,/Mode_Operation!=Operation_Dash && !g_GoatPanelUnavailable\) PanelDialog\.maximizeWindow\(\);/);
 assert.match(events,/Mode_Operation!=Operation_Dash && !g_GoatPanelUnavailable\) \{for\(int i=0; i<ArraySize\(Obj_names\)/);ok();}
// 4) Trading never reads the panel: every PanelDialog reference outside the panel class, SetEdit display calls,
//    OnInit's panel block, the chart events, OnDeinit and the news list is absent.
{const outside=main.split('\n').map((l,i)=>[i+1,l]).filter(([,l])=>/PanelDialog\./.test(l)&&!/^\s*\/\//.test(l)
   &&!/SetEdit\(PanelDialog\.m_edit_/.test(l)&&!/CreateBiEditRow|CreateEditRow|CreateButton|CreateListView|CreateLogo/.test(l));
 const allowed=['PanelDialog.Create(ChartID(),EA_Name_generated','PanelDialog.Destroy(REASON_INITFAILED)','PanelDialog.Run()','PanelDialog.Destroy(reason)',
  'PanelDialog.HandleChartEvent','PanelDialog.Left()','PanelDialog.maximizeWindow()','PanelDialog.OnClickCaption()','PanelDialog.m_list_News','PanelDialog.Move',
  'PanelDialog.Top()','PanelDialog.ControlsTotal()','PanelDialog.Control(i)'];
 for(const [n,l] of outside) assert.ok(allowed.some(a=>l.includes(a)),'unexpected panel read at GOAT V1.49.mq5:'+n+': '+l.trim());ok();}
// 5) Deploy mode and the notice.
function notice(o){
 const alerts=[],prints=[],phases=[];
 const c={MQL_TESTER:1,MQL_OPTIMIZATION:2,MQL_FORWARD:3,MQLInfoInteger:k=>(o.tester&&k===1)?1:0,Mode_Operation:o.mode,Operation_Dash:8,Operation_Standard:9,
  Dashboard_Resume_Saved:!!o.resume,Studio_MonitorRunPath:o.run??'',StringFind:(s,t)=>s.indexOf(t),GlobalVariableCheck:k=>k==='Dashboard_ChartID'&&!!o.dash,
  Alert:t=>alerts.push(t),Print:t=>prints.push(t),GoatDeploymentPhase:(p,t,d)=>phases.push([p,d]),ChartID:()=>7,StringSubstr:(s,a,n)=>s.slice(a,a+n)};
 vm.createContext(c);
 vm.runInContext('function GoatDeployMode(){'+js(unit('bool GoatDeployMode(void)'))+'}',c);
 vm.runInContext('function GoatDeployNotice(goat_notice_text){'+js(unit('void GoatDeployNotice(const string goat_notice_text)'))+'}',c);
 c.GoatDeployNotice('Max Daily DD Hit : Trading Stopped');
 return {deploy:c.GoatDeployMode(),alerts,prints,phases};
}
for(const [label,o,deploy] of [['staged child',{mode:9,run:'deploy=0123456789abcdef0123456789abcdef'},true],['child on a dashboard terminal',{mode:9,dash:true},true],
  ['resumed dashboard',{mode:8,resume:true},true],['manual chart',{mode:9},false],['dashboard opened by hand',{mode:8},false],
  ['studio',{mode:5,dash:true},false],['tester child',{mode:9,dash:true,tester:true},false]]){
 const r=notice(o);assert.equal(r.deploy,deploy,label);
 if(deploy){assert.deepEqual(r.alerts,[],label+': no modal');assert.equal(r.prints.length,1);assert.deepEqual(r.phases,[['notice','Max Daily DD Hit : Trading Stopped']]);}
 else assert.deepEqual([r.alerts,r.prints],[['Max Daily DD Hit : Trading Stopped'],[]],label+': the Alert as before');
 ok();
}
// 6) The redirection covers every Alert() in the compile closure: it is defined right after the input header (which
//    has none), before every other include, and undefined only at the end of the entrypoint.
{const lines=main.split('\n');
 const def=lines.indexOf('#define Alert(goat_alert_text) GoatDeployNotice(goat_alert_text)'),undef=lines.indexOf('#undef Alert');
 assert.ok(def>0&&undef>def);
 assert.equal(lines.findIndex(l=>/^#include "GOAT_Inputs_Definitions\.mqh"/.test(l)),def-5,'just after the input header include');
 assert.ok(lines.every((l,i)=>!/^#include/.test(l)||i<def-4||i>def),'every other include follows it');
 assert.ok(!lines.slice(undef+1).some(l=>/^#include/.test(l)),'no include after the #undef');
 const after=lines.slice(undef+1).join('\n');assert.deepEqual([...after.matchAll(/(?<![\w.])Alert\s*\(/g)].length,1,'only GoatDeployNotice calls the real Alert');
 assert.ok(!/(?<![\w.])Alert\s*\(/.test(read('GOAT_Inputs_Definitions.mqh').replace(/\/\/.*$/gm,'')),'the input header has no Alert');
 assert.equal(lines.filter(l=>/^\s*#undef\s+Alert\b/.test(l)).length,1);
 let calls=0;for(const f of ['GOAT V1.49.mq5',...fs.readdirSync(ROOT).filter(f=>f.endsWith('.mqh'))]) calls+=(read(f).match(/(?<![\w.])Alert\s*\(/g)||[]).length;
 assert.ok(calls>60,'the closure has '+calls+' Alert() calls, all redirected');ok();}
console.log(JSON.stringify({passed,nativePanel:false}));
