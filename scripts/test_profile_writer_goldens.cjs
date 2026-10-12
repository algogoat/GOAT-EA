// B44 Deploy All (P-beta25-D5-dashboard-deploy-all): the production MQL deploy-profile writer core,
// GOATDeployProfileWriter.mqh, run offline after a syntax-only conversion, must write byte for byte what
// controller/studio_deploy_profile.py writes: every G2 golden (controller/contracts/profile-fixtures/g2) and every
// G4 golden (g4, emitted by controller/deploy_profile_goldens.py), and it must refuse every refusal case with the
// Python writer's code. Source mutations prove the harness executes the source it reads.
//
// Not covered here (B44.1 native check): MetaEditor's compile, MQL's own string and uchar semantics at run time,
// the sandbox write, the create-only copy into Profiles\Charts and the readback.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto');
const ROOT=path.join(__dirname,'..');
const FIX=path.join(ROOT,'controller','contracts','profile-fixtures');
const SOURCE=fs.readFileSync(path.join(ROOT,'GOATDeployProfileWriter.mqh'),'utf8');
const fixture=name=>fs.readFileSync(path.join(FIX,name));
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
let passed=0;const ok=()=>passed++;

// ---- syntax-only conversion -------------------------------------------------------------------
function strip(source){
 const strings=[];
 let text=source.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n').replace(/"(?:[^"\\\r\n]|\\.)*"/g,s=>{strings.push(s);return '__S'+(strings.length-1)+'__';});
 text=text.replace(/\/\/[^\r\n]*/g,'').replace(/\/\*[\s\S]*?\*\//g,'');
 return {text,strings};
}
const CHAR_ESCAPES={'\\\\':92,"\\'":39,'\\n':10,'\\r':13,'\\t':9,'\\0':0};
function convert(source){
 let {text,strings}=strip(source);
 text=text.replace(/'(\\.|[^'\\])'/g,(_,c)=>String(c.length===1?c.charCodeAt(0):CHAR_ESCAPES[c]));
 text=text.replace(/^[ \t]*#(?:ifndef|endif)\b[^\r\n]*/gm,'').replace(/^[ \t]*#define[ \t]+\w+[ \t]*$/gm,'')
  .replace(/^[ \t]*#define[ \t]+(\w+)[ \t]+([^\r\n]+)$/gm,'const $1=$2;');
 text=text.replace(/\b(?:bool|string|int|void)\s+(GoatProfileWriter\w+)\s*\(([^)]*)\)/g,(_,name,params)=>'function '+name+'('
  +params.split(',').map(p=>p.replace(/\bconst\b/g,'').replace(/\b(?:string|int|bool|uchar|ushort)\b/g,'').replace(/[&\[\]]/g,'').trim()).filter(Boolean).join(',')+')');
 text=text.replace(/\bstring\s+(\w+)\[\]\s*=\s*\{([^}]*)\}/g,'let $1=[$2]')
  .replace(/\b(?:string|ushort|uchar|int)\s+(\w+)\[\]\s*;/g,'let $1=[];')
  .replace(/\((?:uchar|ushort|int)\)/g,'')
  .replace(/\b(?:string|int|bool|ushort|uchar)\s+(?=[A-Za-z_])/g,'let ');
 return text.replace(/__S(\d+)__/g,(_,i)=>strings[+i]);
}
function load(source){
 const api={StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringFind:(s,q,start)=>s.indexOf(q,start||0),StringGetCharacter:(s,i)=>s.charCodeAt(i),ArraySize:a=>a.length,
  ArrayResize:(a,n)=>{a.length=n;return n;},IntegerToString:n=>String(n),
  ShortArrayToString:(a,start,count)=>{let out='';for(let i=start;i<start+count;i+=4096)out+=String.fromCharCode(...a.slice(i,Math.min(start+count,i+4096)));return out;}};
 vm.createContext(api);vm.runInContext(convert(source),api);return api;
}

// ---- source rules: the subset the conversion is honest for --------------------------------------
{
 const text=strip(SOURCE).text.replace(/'(\\.|[^'\\])'/g,'0');
 assert.ok(!text.includes('/'),'no division (and no other slash) outside strings, char literals and comments');
 const allowed=new Set(['if','for','while','return','StringLen','StringSubstr','StringFind','StringGetCharacter','ArraySize','ArrayResize',
  'ShortArrayToString','IntegerToString','defined']);
 for(const m of text.matchAll(/\b([A-Za-z_]\w*)\s*\(/g))
  if(!m[1].startsWith('GoatProfileWriter')&&!['bool','string','int','void','uchar','ushort'].includes(m[1]))
   assert.ok(allowed.has(m[1]),'call outside the pure subset: '+m[1]);
 for(const banned of [/#import/,/#include/,/\bFile\w*\b/,/\bkernel32\b/,/\bChart\w*\b/,/\bTerminal\w*\b/,/\bAccount\w*\b/,/\bOrder\w*\b/,
  /\bPosition\w*\b/,/\bGlobalVariable\w*\b/,/\bStringFormat\b/,/\bStringToLower\b/,/\bdouble\b/,/\blong\b/,/Enabled=/,/AllowLiveTrading/])
  assert.ok(!banned.test(text),'banned in the pure core: '+banned);
 for(const m of text.matchAll(/\((?:uchar|ushort)\)\s*\(([^;]*)/g)) assert.ok(m[1].includes('&'),'every narrowing cast is masked: '+m[0].slice(0,60));
 for(const m of text.matchAll(/\b(?:string|int|bool|ushort|uchar)\s+&?\s*([A-Za-z_]\w*)/g))
  assert.ok(/^(?:pw_|g_goat_pw_|GoatProfileWriter)/.test(m[1]),'local, parameter or global without the pw_ prefix: '+m[1]);
 const converted=convert(SOURCE);
 assert.ok(!/\b(?:ushort|uchar|bool|string)\b/.test(strip(converted).text),'no MQL type keyword survives the conversion');
 ok();
}

// ---- the checks, run against any source --------------------------------------------------------
function chart(api,fn,args){
 const out=[];const okay=api[fn](...args,out);
 return okay?Buffer.from(out):{refused:api.GoatProfileWriterRefusal(),detail:api.GoatProfileWriterDetail()};
}
const child=(api,c,raw)=>chart(api,'GoatProfileWriterChildChart',[c.fileName,c.symbol,Array.from(raw),c.eaRelativePath,c.policy.aiMode,c.policy.aiThreshold,c.policy.aiProtocol,c.deploymentId]);
const dashboard=(api,symbol,ea)=>chart(api,'GoatProfileWriterDashboardChart',[symbol,ea]);
const state=(api,policy,members)=>chart(api,'GoatProfileWriterStateFile',[policy.aiMode,policy.aiThreshold,policy.aiProtocol,
 members.map(m=>m.path),members.map(m=>m.fileName),members.map(m=>m.symbol),members.map(m=>m.strategy)]);
function profileFiles(api,spec){
 assert.equal(api.GoatProfileWriterMemberCountOk(spec.members.length),true);
 const files={[api.GoatProfileWriterChartFileName(1)]:dashboard(api,spec.members[0].symbol,spec.eaRelativePath)};
 spec.members.forEach((m,i)=>{files[api.GoatProfileWriterChartFileName(i+2)]=child(api,Object.assign({},m,{eaRelativePath:spec.eaRelativePath,policy:spec.policy,
  deploymentId:spec.deploymentId}),fixture(m.set));});
 files['dashboard_state.tsv']=state(api,spec.policy,spec.members);
 return files;
}
const same=(written,expected,label)=>{assert.ok(Buffer.isBuffer(written),label+' refused: '+JSON.stringify(written));assert.ok(written.equals(expected),label+' bytes differ');};

function runAll(api,count){
 const tick=count?ok:()=>{};
 // G2: the frozen beta.25 goldens.
 const g2=JSON.parse(fixture('g2/cases.json'));
 assert.ok(g2.children.length>=5);
 for(const c of g2.children){const w=child(api,c,fixture(c.set));same(w,fixture(c.chart),'g2 '+c.case);assert.equal(sha(w),c.chartSha256);tick();}
 same(dashboard(api,g2.dashboard.symbol,g2.dashboard.eaRelativePath),fixture(g2.dashboard.chart),'g2 dashboard');tick();
 {const spec=Object.assign({},g2.profile,{members:g2.profile.members.map(m=>Object.assign({},m))});
  assert.equal(api.GoatProfileWriterProfileName(spec.deploymentId),spec.profileName);
  const files=profileFiles(api,spec);
  assert.deepEqual(Object.keys(files).sort(),Object.keys(spec.files).sort());
  for(const [name,raw] of Object.entries(files)){same(raw,fixture('g2/profile/'+name),'g2 profile '+name);assert.equal(sha(raw),spec.files[name]);}
  tick();}
 // G4: three whole portfolios emitted by the Python writer.
 const g4=JSON.parse(fixture('g4/cases.json'));
 assert.equal(g4.portfolios.length,3);
 for(const spec of g4.portfolios){
  assert.equal(api.GoatProfileWriterProfileName(spec.deploymentId),spec.profileName);
  const files=profileFiles(api,spec);
  assert.deepEqual(Object.keys(files).sort(),Object.keys(spec.files).sort());
  for(const [name,raw] of Object.entries(files)){same(raw,fixture('g4/'+spec.case+'/'+name),spec.case+' '+name);assert.equal(sha(raw),spec.files[name]);}
  tick();
 }
 // Refusals: g2/refused.json (UTF-16 texts) and the G4 cases with Python's own verdict.
 const okCase={fileName:'GOAT V1.49 EURUSD,M1_x.set',symbol:'EURUSD',eaRelativePath:'GOAT-EA\\GOAT V1.49.ex5',
  policy:{aiMode:0,aiThreshold:50,aiProtocol:2},deploymentId:'0123456789abcdef0123456789abcdef'};
 for(const c of JSON.parse(fixture('g2/refused.json')).cases){
  const w=child(api,okCase,Buffer.concat([Buffer.from([0xFF,0xFE]),Buffer.from(c.text,'utf16le')]));
  assert.ok(!Buffer.isBuffer(w),'g2 refused '+c.label+' was written');
  assert.equal(w.refused,c.label==='no inputs'?'SET_NO_INPUTS':'SET_LINE_UNSUPPORTED',c.label);tick();
 }
 assert.ok(g4.refused.length>=30);
 for(const c of g4.refused){
  const w=child(api,Object.assign({},okCase,{fileName:c.fileName,symbol:c.symbol,eaRelativePath:c.eaRelativePath,deploymentId:c.deploymentId}),Buffer.from(c.setHex,'hex'));
  assert.ok(!Buffer.isBuffer(w),'g4 refused '+c.label+' was written');assert.equal(w.refused,c.code,c.label);tick();
 }
 // Names.
 assert.equal(api.GoatProfileWriterChartFileName(1),'chart01.chr');assert.equal(api.GoatProfileWriterChartFileName(9),'chart09.chr');
 assert.equal(api.GoatProfileWriterChartFileName(10),'chart10.chr');assert.equal(api.GoatProfileWriterChartFileName(101),'chart101.chr');
 assert.equal(api.GoatProfileWriterChartFileName(0),'');assert.equal(api.GoatProfileWriterChartFileName(102),'');
 assert.equal(api.GoatProfileWriterMemberCountOk(0),false);assert.equal(api.GoatProfileWriterMemberCountOk(101),false);
 assert.equal(api.GoatProfileWriterProfileName('0123456789ABCDEF0123456789abcdef'),'');tick();
}

runAll(load(SOURCE),true);

// ---- mutations: a changed writer must fail at least one golden ----------------------------------
const MUTATIONS=[
 ['CRLF pieces keep their CR','if(pw_at<pw_count && pw_end>pw_start && pw_units[pw_end-1]==0x0D) pw_end--;',''],
 ['the window height','"height=100.000000"','"height=100.00000"'],
 ['AI inputs appended in another order','{"Mode_Bias","Bias_threshold","Bias_Protocol","Mode_Bias_Trades"}','{"Mode_Bias","Bias_Protocol","Bias_threshold","Mode_Bias_Trades"}'],
 ['the nonce always appended','if(pw_found>=0) pw_lines[pw_found]=pw_nonce;','if(false) pw_lines[pw_found]=pw_nonce;'],
 ['D1 as unit 2','return (pw_token=="H1" || pw_token=="H4" || pw_token=="D1") ? 1 : 0;','return (pw_token=="H1" || pw_token=="H4") ? 1 : (pw_token=="D1" ? 2 : 0);'],
 ['no BOM','pw_out[0]=0xFF;','pw_out[0]=0xFE;'],
 ['UTF-8 BOM kept','pw_raw[2]==0xBF) pw_at=3;','pw_raw[2]==0xBF) pw_at=0;'],
 ['astral characters dropped','if(pw_cp>=0x10000)','if(pw_cp>=0x10000 && false)'],
 ['ideographic space allowed','|| pw_u==0x205F || pw_u==0x3000','|| pw_u==0x205F'],
 ['protocol 1 written as 2','return (pw_protocol==2 ? "2" : "1");','return "2";'],
 ['trailing tab kept','while(pw_b>pw_a && (pw_units[pw_b-1]==0x20 || pw_units[pw_b-1]==0x09)) pw_b--;','while(pw_b>pw_a && pw_units[pw_b-1]==0x20) pw_b--;'],
 ['state row cid magic','+"0"+pw_tab+"0"+pw_crlf;','+"0"+pw_tab+"1"+pw_crlf;'],
];
for(const [label,from,to] of MUTATIONS){
 assert.ok(SOURCE.includes(from),'mutation anchor missing: '+label);
 let failed=false;
 try{runAll(load(SOURCE.replace(from,to)),false);}catch(e){failed=true;}
 assert.ok(failed,'mutation survived: '+label);ok();
}
console.log(JSON.stringify({passed,g2:true,g4:true,mutations:MUTATIONS.length,productionSourceExecuted:true,nativeCompileAndFileIoVerified:false}));
