// Offline execution of production MQL parser/selftest after syntax-only conversion.
// This does not test native ChartSaveTemplate, its encoding, or file cleanup.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.join(__dirname,'..');
const source=fs.readFileSync(path.join(root,'GOATPortfolioChildAudit.mqh'),'utf8');
let text=source.slice(0,source.indexOf('bool GoatChildAuditRead('))+source.slice(source.indexOf('bool GoatPortfolioChildAuditSelfTest('));
text=text.replace(/^\uFEFF/,'').replace(/^#.*$/gm,'').replace(/\b(?:bool|string|int) (Goat\w+)\(/g,'function $1(')
 .replace(/\bconst (?:string|int) /g,'').replace(/\bstring &(\w+)\[\]/g,'$1')
 .replace(/\bstring (\w+)\[\d+\]=\{([^}]+)\}/g,'let $1=[$2]')
 .replace(/\b(?:string|int|bool|ushort) /g,'let ').replace(/\b(\w+)\[\](?=[,;])/g,'$1=[]')
 .replace(/'([^'\\]|\\[nr])'/g,(_,c)=>String(c==='\\n'?10:c==='\\r'?13:c.charCodeAt(0)))
 .replace(/StringTrimLeft\((\w+)\)/g,'$1=$1.trimStart()').replace(/StringTrimRight\((\w+)\)/g,'$1=$1.trimEnd()')
 .replace(/StringToLower\((\w+)\)/g,'$1=$1.toLowerCase()')
 .replace(/StringReplace\((\w+),([^;]+)\)/g,'$1=$1.replaceAll($2)')
 .replace(/function ([^(]+)\(([^)]*)\)/g,(_,name,args)=>'function '+name+'('+args.replace(/\blet /g,'').replace(/^void$/,'')+')');
const api={StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
 StringFind:(s,q)=>s.indexOf(q),StringGetCharacter:(s,i)=>s.charCodeAt(i),ArraySize:a=>a.length,
 ArrayResize:(a,n)=>{a.length=n;return n;},StringSplit:(s,c,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(c)));return out.length;},
 TerminalInfoString:()=> 'C:\\Fixture',TERMINAL_DATA_PATH:1,
 GOATIsLowerHex:(v,n)=>typeof v==='string'&&v.length===n&&/^[0-9a-f]+$/.test(v),
 GoatApplyAILaunchPolicy:(body,mode,threshold,protocol)=>{
  if(mode===0)return body;
  const changes={Mode_Bias:mode===1?'0':'2',Bias_threshold:String(threshold),Bias_Protocol:String(protocol),Mode_Bias_Trades:'0'};
  const seen=new Set();let out=body.split(/\r?\n/).filter((s,i,a)=>s||i<a.length-1).map(s=>{const i=s.indexOf('=');const k=s.slice(0,i);if(i>0&&k in changes){seen.add(k);return k+'='+changes[k];}return s;});
  for(const [k,v]of Object.entries(changes))if(!seen.has(k))out.push(k+'='+v);return out.join('\r\n')+'\r\n';
 }};
vm.createContext(api);vm.runInContext(text,api);assert.equal(api.GoatPortfolioChildAuditSelfTest(),true);
let passed=12;
for(const [a,b,expected]of [['0.05','00.0500',true],['-0.00','0',true],['9007199254740992','9007199254740993',false],['.5','0.50',true],['1e2','100',false],['2.0','2.0001',false]]){
 assert.equal(api.GoatChildAuditValue('Risk',a,b),expected);passed++;
}
const original='EA_Desc=Fixture\nRisk=500\nMode_Bias=1\n';
const inputs=original+'Studio_ReadOnlyMonitor=false\nStudio_MonitorRunPath=\nDashboard_Resume_Saved=false\n';
const head='<chart>\n<expert>\npath=Experts\\GOAT Experiment\\GOAT V1.47.ex5\n<inputs>\n',tail='</inputs>\n</expert>\n</chart>\n';
const expert='Experts\\GOAT Experiment\\GOAT V1.47.ex5';
for(const bad of [head+inputs.replace('Risk=500\n','')+tail,head+inputs.replace('Monitor=false','Monitor=true')+tail,head+inputs+tail+head+inputs+tail,head+inputs+tail.replace('</inputs>','</window>')]){
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,bad,expert),false);passed++;
}
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+'===========GROUP============ =\n'+inputs+tail,expert),true);passed++;
// CA41 (ported from 4f3f2f9): a V1.49 child template carries six inputs WriteSet omits. Accepted only at their defaults.
const declared='Sequence_Export_Enabled=false\nSequence_Export_Id=\nSequence_Export_Start=0\nSequence_Export_End=0\nSequence_Export_Model=4\nGOAT_FitnessRunNonce=0\n';
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared+tail,expert),true);passed++;
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared.replace('Sequence_Export_Model=4\n','')+tail,expert),true);passed++;
assert.equal(api.GoatChildAuditMaps(original+'Sequence_Export_Model=4\n',0,50,2,head+inputs+declared+tail,expert),true);passed++;
for(const [from,to] of [['Enabled=false','Enabled=true'],['Id=\n','Id=x\n'],['Start=0','Start=1750896000'],['End=0','End=1'],['Model=4','Model=1'],['Nonce=0','Nonce=7']]){
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared.replace(from,to)+tail,expert),false,from);passed++;
}
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared+'Unknown=1\n'+tail,expert),false);passed++;
// B44 item 5: a B44 child template also carries BlindExport, which WriteSet omits. Accepted only at its default.
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared+'BlindExport=false\n'+tail,expert),true);passed++;
assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+declared+'BlindExport=true\n'+tail,expert),false);passed++;
assert.equal(api.GoatChildAuditMaps(original+'BlindExport=true\n',0,50,2,head+inputs+declared+'BlindExport=false\n'+tail,expert),false);passed++;
assert.equal(api.GoatChildAuditMaps(original+'Sequence_Export_Model=1\n',0,50,2,head+inputs+declared+tail,expert),false);passed++;
// B49a (F2; Codex GOAT-EA#267): a B49a child template carries Ledger_Mode, which WriteSet writes only when it is not
// Legacy. A Legacy SET (no Ledger_Mode) maps to a child holding 0, never to one holding PositionJoin; a PositionJoin
// SET carries Ledger_Mode=1 and is compared exactly.
{const ledger=head+inputs+declared+'BlindExport=false\n';
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,ledger+'Ledger_Mode=0\n'+tail,expert),true,'Legacy SET, B49a child at Legacy');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,ledger+'Ledger_Mode=1\n'+tail,expert),false,'Legacy SET, child at PositionJoin');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Ledger_Mode=1\n',0,50,2,ledger+'Ledger_Mode=1\n'+tail,expert),true,'PositionJoin SET and child');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Ledger_Mode=1\n',0,50,2,ledger+'Ledger_Mode=0\n'+tail,expert),false,'PositionJoin SET, child at Legacy');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Ledger_Mode=1\n',0,50,2,ledger+tail,expert),false,'PositionJoin SET, a B47 child without the input');passed++;
 // B49b (F7): Fix_MoneyVolume follows the same rule (written only when on; a child that carries it must hold Off).
 const fix=ledger+'Ledger_Mode=0\n';
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=0\n'+tail,expert),true,'Off SET, B49b child at Off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=1\n'+tail,expert),false,'Off SET, child at On');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_MoneyVolume=1\n',0,50,2,fix+'Fix_MoneyVolume=1\n'+tail,expert),true,'On SET and child');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_MoneyVolume=1\n',0,50,2,fix+'Fix_MoneyVolume=0\n'+tail,expert),false,'On SET, child at Off');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_MoneyVolume=1\n',0,50,2,fix+tail,expert),false,'On SET, a B49a child without the input');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+tail,expert),true,'Off SET, a B49a child without the input');passed++;
 // B49b (F5): Gate_Recheck under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=0\nGate_Recheck=0\n'+tail,expert),true,'Legacy SET, B49b child at Legacy');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=0\nGate_Recheck=1\n'+tail,expert),false,'Legacy SET, child rechecking');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Gate_Recheck=1\n',0,50,2,fix+'Fix_MoneyVolume=0\nGate_Recheck=1\n'+tail,expert),true,'AtFirstOrder SET and child');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Gate_Recheck=1\n',0,50,2,fix+'Fix_MoneyVolume=0\n'+tail,expert),false,'AtFirstOrder SET, a PR-1 child without the input');passed++;
 // B49b (F3): Fix_ClosePath under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=0\nGate_Recheck=0\nFix_ClosePath=0\n'+tail,expert),true,'Off SET, B49b child at Off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_MoneyVolume=0\nGate_Recheck=0\nFix_ClosePath=1\n'+tail,expert),false,'Off SET, child at On');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_ClosePath=1\n',0,50,2,fix+'Fix_ClosePath=1\n'+tail,expert),true,'On SET and child');passed++;
 // B49b (F6): the pre-trade caps under the same rule (0 = off), compared as numbers.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Max_Spread_Points=0\nMin_Margin_Level_PC=0.0\n'+tail,expert),true,'Off SET, B49b child with both caps off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Max_Spread_Points=30\n'+tail,expert),false,'Off SET, child with a spread cap');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Min_Margin_Level_PC=150\n'+tail,expert),false,'Off SET, child with a margin floor');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Min_Margin_Level_PC=150\n',0,50,2,fix+'Min_Margin_Level_PC=150.0\n'+tail,expert),true,'Set SET and child, as numbers');passed++;
 // B49b (LAG-A): Fix_FeedGuard under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_FeedGuard=0\n'+tail,expert),true,'Off SET, B49b child with Fix_FeedGuard off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_FeedGuard=1\n'+tail,expert),false,'Off SET, child with Fix_FeedGuard on');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_FeedGuard=1\n',0,50,2,fix+'Fix_FeedGuard=1\n'+tail,expert),true,'On SET and child');passed++;
 // B49b (LAG-T): Diag_TickTiming under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Diag_TickTiming=0\n'+tail,expert),true,'Off SET, B49b child with Diag_TickTiming off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Diag_TickTiming=1\n'+tail,expert),false,'Off SET, child with Diag_TickTiming on');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Diag_TickTiming=1\n',0,50,2,fix+'Diag_TickTiming=1\n'+tail,expert),true,'On SET and child');passed++;
 // B49b (LAG-B): Fix_TickLoad under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_TickLoad=0\n'+tail,expert),true,'Off SET, B49b child with Fix_TickLoad off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_TickLoad=1\n'+tail,expert),false,'Off SET, child with Fix_TickLoad on');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_TickLoad=1\n',0,50,2,fix+'Fix_TickLoad=1\n'+tail,expert),true,'On SET and child');passed++;
 // B49b (F4/R2): Fix_Clock under the same rule.
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_Clock=0\n'+tail,expert),true,'Off SET, B49b child with Fix_Clock off');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,fix+'Fix_Clock=1\n'+tail,expert),false,'Off SET, child with Fix_Clock on');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Fix_Clock=1\n',0,50,2,fix+'Fix_Clock=1\n'+tail,expert),true,'On SET and child');passed++;}
// B50 (A0): a B50 child template carries the twelve B50 inputs, which WriteSet writes only when they differ from their
// defaults. A SET without them maps only to a child holding every default; a SET that carries one is compared exactly.
{const b50='Engine_Mode=0\nSingle_SL_ATR=0.0\nSingle_TP_ATR=0\nSingle_TP_R=0.00\nSingle_Exit_Opposite=false\nSingle_Time_Stop_Bars=0\n'
  +'Single_Time_Stop_TF=0\nClock_Mode=0\nServer_Clock_Model=0\nServer_UTC_Offset=2\nNY_Session=09:30-16:00\nRollover_Block_Minutes=0\n';
 const child=head+inputs+declared+'BlindExport=false\nLedger_Mode=0\n';
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b50+tail,expert),true,'B49a SET, B50 child at the defaults');passed++;
 for(const [from,to] of [['Engine_Mode=0','Engine_Mode=1'],['Single_SL_ATR=0.0','Single_SL_ATR=1.5'],['Single_Exit_Opposite=false','Single_Exit_Opposite=true'],
  ['Single_Time_Stop_TF=0','Single_Time_Stop_TF=1440'],['Clock_Mode=0','Clock_Mode=1'],['Server_UTC_Offset=2','Server_UTC_Offset=3'],
  ['NY_Session=09:30-16:00','NY_Session=08:00-17:00'],['Rollover_Block_Minutes=0','Rollover_Block_Minutes=15']]){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b50.replace(from,to)+tail,expert),false,'B49a SET, child at '+to);passed++;
 }
 const single=original+'Engine_Mode=1\nSingle_SL_ATR=1.5\n';
 assert.equal(api.GoatChildAuditMaps(single,0,50,2,child+b50.replace('Engine_Mode=0','Engine_Mode=1').replace('Single_SL_ATR=0.0','Single_SL_ATR=1.50')+tail,expert),true,'Single SET and child');passed++;
 assert.equal(api.GoatChildAuditMaps(single,0,50,2,child+b50+tail,expert),false,'Single SET, grid child');passed++;
 assert.equal(api.GoatChildAuditMaps(single,0,50,2,child+tail,expert),false,'Single SET, a B49a child without the inputs');passed++;}
// B51 (B50-beta-1a): a B51 child also carries the B50-beta inputs at the end, which WriteSet writes only when they differ
// from their defaults: a SET without them maps only to a child holding the defaults (no benchmark, seed 1).
{const b50='Engine_Mode=0\nSingle_SL_ATR=0.0\nSingle_TP_ATR=0\nSingle_TP_R=0.00\nSingle_Exit_Opposite=false\nSingle_Time_Stop_Bars=0\n'
  +'Single_Time_Stop_TF=0\nClock_Mode=0\nServer_Clock_Model=0\nServer_UTC_Offset=2\nNY_Session=09:30-16:00\nRollover_Block_Minutes=0\n';
 const b51='Random_Direction=false\nRandom_Seed=1\nSingle_Flat_Only=false\nSingle_BE_ATR=0.0\nSingle_Trail_Start_ATR=0\nSingle_Trail_ATR=0.00\nSingle_Partial_ATR=0\nSingle_Partial_Fraction=0.0\nSingle_Partial_BE=false\n';   // beta-1b and section 8.3: three more each
 const child=head+inputs+declared+'BlindExport=false\nLedger_Mode=0\n'+b50;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b51+tail,expert),true,'B49a SET, B51 child at the defaults');passed++;
 for(const [from,to] of [['Random_Direction=false','Random_Direction=true'],['Random_Seed=1','Random_Seed=2'],['Single_Flat_Only=false','Single_Flat_Only=true'],['Single_BE_ATR=0.0','Single_BE_ATR=1.0'],
  ['Single_Trail_Start_ATR=0','Single_Trail_Start_ATR=2'],['Single_Trail_ATR=0.00','Single_Trail_ATR=0.5'],
  ['Single_Partial_ATR=0','Single_Partial_ATR=1'],['Single_Partial_Fraction=0.0','Single_Partial_Fraction=0.5'],['Single_Partial_BE=false','Single_Partial_BE=true']]){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b51.replace(from,to)+tail,expert),false,'B49a SET, child at '+to);passed++;
 }
 assert.equal(api.GoatChildAuditMaps(original+'Random_Seed=7\n',0,50,2,child+b51.replace('Random_Seed=1','Random_Seed=7')+tail,expert),true,'a seed SET and its child');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Random_Seed=7\n',0,50,2,child+tail,expert),false,'a seed SET, a B50-alpha child without the input');passed++;}
// B54 (A0): a B54 child also carries the breakout inputs at the end, which WriteSet writes only when they differ from their
// defaults: a SET without them maps only to a child holding the defaults (both families Disabled).
{const b50='Engine_Mode=0\nSingle_SL_ATR=0.0\nSingle_TP_ATR=0\nSingle_TP_R=0.00\nSingle_Exit_Opposite=false\nSingle_Time_Stop_Bars=0\n'
  +'Single_Time_Stop_TF=0\nClock_Mode=0\nServer_Clock_Model=0\nServer_UTC_Offset=2\nNY_Session=09:30-16:00\nRollover_Block_Minutes=0\n';
 const b49b='Fix_MoneyVolume=0\nGate_Recheck=0\nFix_ClosePath=0\nMax_Spread_Points=0\nMin_Margin_Level_PC=0.0\nFix_Clock=0\nFix_FeedGuard=0\nDiag_TickTiming=0\nFix_TickLoad=0\n';
 const b51='Random_Direction=false\nRandom_Seed=1\nSingle_Flat_Only=false\nSingle_BE_ATR=0.0\nSingle_Trail_Start_ATR=0\nSingle_Trail_ATR=0.00\nSingle_Partial_ATR=0\nSingle_Partial_Fraction=0.0\nSingle_Partial_BE=false\n';
 const b54='BRK_Mode=0\nBRK_TF_=60\nBRK_Bars=20\nBRK_Buffer_ATR=0.0\nBRK_Once_Per_Level=true\nORB_Mode=0\nORB_Clock=0\nORB_TF_=5\n'
  +'ORB_Start_Minute=570\nORB_Range_Minutes=30\nORB_Entry_Minutes=0\nORB_Buffer_ATR=0.00\nORB_Min_Range_ATR=0\nORB_Max_Range_ATR=0.0\n';
 const child=head+inputs+declared+'BlindExport=false\nLedger_Mode=0\n'+b50+b49b+b51;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b54+tail,expert),true,'B49a SET, B54 child at the defaults');passed++;
 for(const [from,to] of [['BRK_Mode=0','BRK_Mode=1'],['BRK_TF_=60','BRK_TF_=15'],['BRK_Bars=20','BRK_Bars=21'],['BRK_Buffer_ATR=0.0','BRK_Buffer_ATR=0.5'],
  ['BRK_Once_Per_Level=true','BRK_Once_Per_Level=false'],['ORB_Mode=0','ORB_Mode=1'],['ORB_Clock=0','ORB_Clock=1'],['ORB_TF_=5','ORB_TF_=15'],
  ['ORB_Start_Minute=570','ORB_Start_Minute=480'],['ORB_Range_Minutes=30','ORB_Range_Minutes=60'],['ORB_Entry_Minutes=0','ORB_Entry_Minutes=120'],
  ['ORB_Buffer_ATR=0.00','ORB_Buffer_ATR=0.1'],['ORB_Min_Range_ATR=0','ORB_Min_Range_ATR=0.5'],['ORB_Max_Range_ATR=0.0','ORB_Max_Range_ATR=3.5']]){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+b54.replace(from,to)+tail,expert),false,'B49a SET, child at '+to);passed++;
 }
 assert.equal(api.GoatChildAuditMaps(original+'BRK_Bars=55\n',0,50,2,child+b54.replace('BRK_Bars=20','BRK_Bars=55')+tail,expert),true,'a B54 SET and its child');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'BRK_Bars=55\n',0,50,2,child+tail,expert),false,'a B54 SET, a B53 child without the inputs');passed++;}
// The merged line (B50 + B51 with B49b): a child carries B50's, B49b's and B51's inputs, in the header's order (each
// written only when it differs from its default); a SET without them maps only to a child holding every default.
{const b50='Engine_Mode=0\nSingle_SL_ATR=0.0\nSingle_TP_ATR=0\nSingle_TP_R=0.00\nSingle_Exit_Opposite=false\nSingle_Time_Stop_Bars=0\n'
  +'Single_Time_Stop_TF=0\nClock_Mode=0\nServer_Clock_Model=0\nServer_UTC_Offset=2\nNY_Session=09:30-16:00\nRollover_Block_Minutes=0\n';
 const b49b='Fix_MoneyVolume=0\nGate_Recheck=0\nFix_ClosePath=0\nMax_Spread_Points=0\nMin_Margin_Level_PC=0.0\nFix_Clock=0\nFix_FeedGuard=0\nDiag_TickTiming=0\nFix_TickLoad=0\n';
 const b51='Random_Direction=false\nRandom_Seed=1\nSingle_Flat_Only=false\nSingle_BE_ATR=0.0\nSingle_Trail_Start_ATR=0\nSingle_Trail_ATR=0.00\nSingle_Partial_ATR=0\nSingle_Partial_Fraction=0.0\nSingle_Partial_BE=false\n';
 const child=head+inputs+declared+'BlindExport=false\nLedger_Mode=0\n'+b50+b49b+b51;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,child+tail,expert),true,'B49a SET, merged child at the defaults');passed++;
 for(const [from,to] of [['Engine_Mode=0','Engine_Mode=1'],['Fix_MoneyVolume=0','Fix_MoneyVolume=1'],['Max_Spread_Points=0','Max_Spread_Points=30'],
  ['Fix_TickLoad=0','Fix_TickLoad=1'],['Random_Seed=1','Random_Seed=2'],['Single_Partial_BE=false','Single_Partial_BE=true']]){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,child.replace(from,to)+tail,expert),false,'B49a SET, merged child at '+to);passed++;
 }
 assert.equal(api.GoatChildAuditMaps(original+'Engine_Mode=1\nSingle_SL_ATR=1.5\nFix_FeedGuard=1\n',0,50,2,
  child.replace('Engine_Mode=0','Engine_Mode=1').replace('Single_SL_ATR=0.0','Single_SL_ATR=1.50').replace('Fix_FeedGuard=0','Fix_FeedGuard=1')+tail,expert),true,'a Single SET with the feed guard, and its child');passed++;}// Deployment nonce (beta.25, goatai#1885 6034810079): a profile-staged child carries
// Studio_MonitorRunPath=deploy=<deploymentId>. With the registration's id, exactly that value passes;
// everything else in the map is still compared exactly. Without an id, the input keeps its "" default.
{
 const D='0123456789abcdef0123456789abcdef',E='fedcba9876543210fedcba9876543210';
 const tagged=tag=>inputs.replace('Studio_MonitorRunPath=\n','Studio_MonitorRunPath='+tag+'\n');
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+D)+tail,expert,D),true,'current nonce');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+D)+declared+tail,expert,D),true,'nonce with CA41 defaults');passed++;
 for(const [label,value] of [['missing',''],['other deployment','deploy='+E],['padded','deploy='+D+' '],['longer','deploy='+D+'0'],
                             ['upper key','DEPLOY='+D],['bare id',D],['prefixed','x deploy='+D],['upper id','deploy='+D.toUpperCase()]]){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged(value)+tail,expert,D),false,label);passed++;
 }
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+D)+tail,expert),false,'no registered id: a tagged child is refused');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+inputs+tail,expert,''),true,'no registered id: the default still passes');passed++;
 for(const bad of [D.toUpperCase(),D.slice(1),'deploy='+D,''+D+'0']){
  assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+bad)+tail,expert,bad),false,'invalid id '+bad);passed++;
 }
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+D).replace('Risk=500','Risk=501')+tail,expert,D),false,'everything else exact');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Studio_MonitorRunPath=\n',0,50,2,head+tagged('deploy='+D)+tail,expert,D),true,'a SET carrying the default');passed++;
 assert.equal(api.GoatChildAuditMaps(original+'Studio_MonitorRunPath=deploy='+D+'\n',0,50,2,head+tagged('deploy='+D)+tail,expert,D),false,'a SET never carries the nonce');passed++;
 assert.equal(api.GoatChildAuditMaps(original,0,50,2,head+tagged('deploy='+D).replace('Dashboard_Resume_Saved=false','Dashboard_Resume_Saved=true')+tail,expert,D),false,'other pinned inputs unchanged');passed++;
}
assert.match(source,/CryptEncode\(CRYPT_HASH_SHA256,bytes,key,digest\)/);
// beta.25: one snapshot routine serves the audit (by row) and adoption (by chart id).
assert.equal((source.match(/ChartSaveTemplate\(/g)||[]).length,1);
assert.match(source,/bool GoatChildChartSnapshot\(const long cid,string &snapshot\)/);
assert.match(source,/bool matched=GoatChildChartSnapshot\(cid,snapshot\) && GoatChildSnapshotMatchesSet\(source,snapshot,deploy_tag\);/);
assert.match(source,/ChartSaveTemplate\(cid,"\\\\Files\\\\"\+filename\)/);
assert.match(source,/FileDelete\(filename\)/);assert.doesNotMatch(source,/\b(?:ChartApplyTemplate|Print|Alert|DeleteFileW)\s*\(/);
console.log(JSON.stringify({passed,pureSelftestPassed:true,nativeTemplateAndIoVerified:false}));
