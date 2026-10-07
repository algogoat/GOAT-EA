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
assert.equal(api.GoatChildAuditMaps(original+'Sequence_Export_Model=1\n',0,50,2,head+inputs+declared+tail,expert),false);passed++;
// Deployment nonce (beta.25, goatai#1885 6034810079): a profile-staged child carries
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
