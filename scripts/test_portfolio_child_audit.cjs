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
assert.match(source,/CryptEncode\(CRYPT_HASH_SHA256,bytes,key,digest\)/);
assert.match(source,/ChartSaveTemplate\(cid,"\\\\Files\\\\"\+filename\)/);
assert.match(source,/FileDelete\(filename\)/);assert.doesNotMatch(source,/\b(?:ChartApplyTemplate|Print|Alert|DeleteFileW)\s*\(/);
console.log(JSON.stringify({passed,pureSelftestPassed:true,nativeTemplateAndIoVerified:false}));
