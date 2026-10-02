// Terminal isolation (INV-BATCH-01, INV-CRED-01): runs the production V1.49 MQL path,
// credential, migration, claim and tester-fitness code in a JS VM over a simulated
// Common Files store shared by several terminals, including interleaved (concurrent)
// moves. MQL-free: no MetaEditor, MT5 or network is used.
// GOAT_EA_ROOT may point at another source tree (used by test_terminal_isolation_mutations.cjs).
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const defs=read('GOAT_Inputs_Definitions.mqh'),activation=read('GOATEADeviceActivation.mqh'),main=read('GOAT V1.49.mq5'),compare=read('GOATStudioSettingCompare.mqh');

// ---- MQL -> JS for the exact functions under test (V1.49 macros defined).
function preprocess(text,defined){
  const out=[],stack=[];let active=true;
  for(const line of text.split('\n')){
    const m=line.match(/^\s*#(ifdef|ifndef|else|endif)\b\s*(\w*)/);
    if(m){
      if(m[1]==='ifdef'||m[1]==='ifndef'){const on=defined.has(m[2])===(m[1]==='ifdef');stack.push([active,on]);active=active&&on;}
      else if(m[1]==='else'){const [parent,on]=stack[stack.length-1];active=parent&&!on;}
      else active=stack.pop()[0];
      continue;
    }
    if(/^\s*#define\b/.test(line))continue;
    if(active)out.push(line);
  }
  return out.join('\n');
}
function stripComments(text){
  let out='',i=0,quote=false;
  while(i<text.length){
    const c=text[i];
    if(quote){out+=c;if(c==='\\'){out+=text[i+1];i+=2;continue;}if(c==='"')quote=false;i++;continue;}
    if(c==='"'){quote=true;out+=c;i++;continue;}
    if(c==='/'&&text[i+1]==='/'){while(i<text.length&&text[i]!=='\n')i++;continue;}
    out+=c;i++;
  }
  return out;
}
function block(text,from){
  let brace=text.indexOf('{',from),depth=1,end=brace+1,quote='';
  while(depth){
    assert.ok(end<text.length,'unbalanced block');
    const ch=text[end];
    if(quote){if(ch==='\\')end++;else if(ch===quote)quote='';}
    else if(ch==='"'||ch==="'")quote=ch;
    else if(ch==='{')depth++;
    else if(ch==='}')depth--;
    end++;
  }
  return [brace,end];
}
function extract(text,name){
  const start=text.search(new RegExp('^(?:string|bool|void|int|long)\\s+'+name+'\\s*\\(','m'));
  assert.ok(start>=0,'missing '+name);
  const [brace,end]=block(text,start);
  const header=text.slice(start,brace),params=header.slice(header.indexOf('(')+1,header.lastIndexOf(')'));
  const names=params.trim()==='void'||!params.trim()?[]:params.split(',').map(p=>p.replace(/=.*/,'').trim().split(/[\s&]+/).pop());
  return 'function '+name+'('+names.join(',')+')'+convert(text.slice(brace,end));
}
const TYPES='string|bool|int|uint|long|ulong|ushort|uchar|datetime|double';
function convert(body){
  body=body.replace(/'(\\.|[^'\\])'/g,(_,c)=>String(({'\\n':10,'\\\\':92,"\\'":39}[c])??c.charCodeAt(0)));
  body=body.replace(new RegExp('\\((?:'+TYPES+')\\)','g'),'');
  body=body.replace(new RegExp('\\b(?:'+TYPES+')\\s+(\\w+)\\[\\]\\s*=\\s*\\{([\\s\\S]*?)\\};','g'),'let $1=[$2];');
  body=body.replace(new RegExp('(^|[;{(]|\\n)(\\s*)(?:const\\s+)?(?:'+TYPES+')\\s+(?=[A-Za-z_])','g'),'$1$2let ');
  body=body.replace(/let ([^;]*);/g,(m,decl)=>'let '+decl.replace(/(\w+)\[\]/g,'$1=[]')+';');
  body=body.replace(/let (\w+);/g,'let $1="";');
  body=body.replace(/StringReplace\((\w+),/g,'$1=__replace($1,');
  body=body.replace(/StringTrimLeft\((\w+)\);/g,'$1=$1.replace(/^\\s+/,"");').replace(/StringTrimRight\((\w+)\);/g,'$1=$1.replace(/\\s+$/,"");');
  body=body.replace(/\bpath\[(\w+)\]/g,'path.charCodeAt($1)');
  body=body.replace(/FileFindFirst\(([^;]*?),name,FILE_COMMON\);/g,'FileFindFirst($1,FILE_COMMON);name=__found;');
  body=body.replace(/while\(FileFindNext\(search,name\)\);/g,'while(FileFindNext(search)&&((name=__found),true));');
  return body;
}
const macros=t=>t.replace(/\bGOAT_API_BEARER_FILE\b/g,'GOATApiBearerFile()').replace(/\bGOAT_API_BEARER_LEGACY_FILE\b/g,'"GOAT\\\\Credentials\\\\api-bearer-v149.token"')
  .replace(/\bGOAT_OPT_ISOLATION_RECEIPT\b/g,'"terminal-isolation.ini"').replace(/\bGOAT_OPT_ISOLATION_CLAIM\b/g,'"terminal-isolation-claim.ini"')
  .replace(/\bGOAT_VERSION_LABEL\b/g,'"1.49"').replace(/\bKey\b/g,'"GOAT"').replace(/\bEA_Name\b/g,'"GOAT V1.49"').replace(/\bServer\b/g,'"Darwinex-Demo"')
  .replace(/\bGOAT_BATCH_CANCELLED_GV\b/g,'"GOAT_BatchCancelled"');
const isolation=new Set(['GOAT_TERMINAL_ISOLATION_V149','GOAT_MONITOR_ONBOARDING_V149','GOAT_ORPHAN_RECOVERY_V149','GOAT_SEQUENCE_EXPORT_V148']);
const D=stripComments(preprocess(defs,isolation)),A=stripComments(preprocess(activation,isolation));
const M=stripComments(preprocess(main,isolation)),C=stripComments(preprocess(compare,isolation));
const names=['GOATIsSafeApiBearerToken','GOATLoginDigitsValid','GOATAccountLoginDigits','GOATApiBearerFileFor','GOATApiBearerFile','GOATCredentialStatusApproved',
  'GOATCredentialMigrateLegacyOnce','GOATBuildAuthenticatedRequestHeaders','GoatOptLegacyBasePath','GoatOptTerminalHash','GoatOptLoginToken',
  'GoatOptBasePath','GoatOptFolderOf','GoatOptEnsureCommonFolderTree','GoatOptWriteTextFile','GoatOptReadTextFile','GoatOptReadIniValue',
  'GoatOptIsolationFlagsHeld','GoatOptIsolationReceipt','GoatOptIsolationClaim','GoatOptMigrateLegacyBatchStateLocked','GoatOptMigrateLegacyBatchState',
  'GoatOptForeignNamespaceFolder','GoatOptTesterFitnessFile'];
const fitnessStart=M.indexOf('if((Mode_Opti==Opti_PF_MRFp||Mode_Opti==Opti_PF_MRF_SRp) && MQLInfoInteger(MQL_OPTIMIZATION)');
assert.ok(fitnessStart>0,'agent fitness block');
const [,fitnessEnd]=block(M,fitnessStart);
const program=macros(names.map(n=>extract(D,n)).join('\n')+'\n'+extract(A,'GOATDeviceActivationWriteCredential')+'\n'+extract(C,'GoatStudioRunNonceValue')
  +'\n'+extract(M,'OnTesterInit')+'\nfunction AgentFitness(){'+convert(M.slice(fitnessStart,fitnessEnd))+'}');
assert.match(main,/#define GOAT_TERMINAL_ISOLATION_V149 1\r?\n#define GOAT_API_BEARER_LEGACY_FILE "GOAT\\\\Credentials\\\\api-bearer-v149\.token"\r?\n#define GOAT_API_BEARER_FILE GOATApiBearerFile\(\)\r?\n#include "GOAT_Inputs_Definitions\.mqh"/);

// ---- One Windows user: a Common Files store shared by every terminal, local Files per terminal.
const F={FILE_READ:1,FILE_WRITE:2,FILE_BIN:4,FILE_TXT:16,FILE_ANSI:32,FILE_UNICODE:64,FILE_SHARE_READ:128,FILE_SHARE_WRITE:256,FILE_REWRITE:512,FILE_COMMON:4096};
const GATE='goatstudio\\native-gate\\launch.lock';
function host(){return {files:new Map(),dirs:new Set(),clock:1000,ticks:0,opened:[],hook:null};}
function terminal(h,login,dataPath,{globals=new Map(),name=''}={}){
  const t={login,dataPath,logs:[],globals,name,gateHeld:false,gvTemp:0,parameters:{},mutations:0};let handles=new Map(),next=1,lastError=0;
  const key=(p,common)=>(common?'C|':'L|'+dataPath+'|')+p.toLowerCase();
  const mutate=op=>{t.mutations++;if(h.hook)h.hook(t,op);};
  const c={...F,INVALID_HANDLE:-1,ACCOUNT_LOGIN:1,TERMINAL_DATA_PATH:2,MQL_TESTER:3,MQL_OPTIMIZATION:4,MQL_FORWARD:5,WHOLE_ARRAY:-1,CP_UTF8:65001,
    CRYPT_HASH_SHA256:6,FILE_MODIFY_DATE:9,ERR_FILE_IS_DIRECTORY:5018,TIME_DATE:1,TIME_SECONDS:4,INIT_FAILED:1,INIT_SUCCEEDED:0,
    Opti_PF_MRFp:1,Opti_PF_MRF_SRp:2,Mode_Opti:0,EA_Desc:'Rabcdefabcdefabcdefabcd',GOAT_FitnessRunNonce:0,g_goat_fitness_nonce:0,
    tester:0,optimization:0,forward:0,__found:'',
    AccountInfoInteger:()=>t.login,TerminalInfoString:()=>t.dataPath,
    MQLInfoInteger:k=>k===3?c.tester:k===4?c.optimization:k===5?c.forward:0,IntegerToString:n=>String(n),
    StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.substr(a,n),StringFind:(s,x,from=0)=>s.indexOf(x,from),
    StringGetCharacter:(s,i)=>s.charCodeAt(i),__replace:(s,a,b)=>s.split(a).join(b),
    StringToShortArray:(s,arr,start,count)=>{arr.length=0;const n=Math.min(count,s.length-start);for(let i=0;i<n;i++)arr.push(s.charCodeAt(start+i));return n;},
    ShortArrayToString:(arr,start,count)=>String.fromCharCode(...arr.slice(start,start+count)),
    StringToCharArray:(s,arr)=>{arr.length=0;for(const b of Buffer.from(s,'utf8'))arr.push(b);arr.push(0);return arr.length;},
    ArrayResize:(arr,n)=>{arr.length=n;return n;},ArraySize:a=>a.length,
    CryptEncode:(m,data,k,digest)=>{digest.length=0;for(const b of crypto.createHash('sha256').update(Buffer.from(data)).digest())digest.push(b);return 32;},
    StringFormat:(f,v)=>v.toString(16).padStart(2,'0'),StringToDouble:s=>Number(s)||0,
    StringSplit:(s,sep,arr)=>{arr.length=0;for(const p of s.split(String.fromCharCode(sep)))arr.push(p);return arr.length;},
    TimeToString:()=>'2026.10.02 00:00:00',TimeGMT:()=>h.clock,GetMicrosecondCount:()=>123456+t.mutations+(t.login%997)*1009+t.dataPath.length,
    GetTickCount64:()=>(h.ticks+=1000),Print:(...m)=>t.logs.push(m.join('')),Sleep:()=>{},
    ResetLastError:()=>{lastError=0;},GetLastError:()=>lastError,
    GlobalVariableGet:n=>t.globals.get(n)??0,GlobalVariableSet:(n,v)=>{t.globals.set(n,v);return 1;},
    GlobalVariableTemp:n=>{t.gvTemp++;if(!t.globals.has(n))t.globals.set(n,0);return true;},
    GlobalVariableSetOnCondition:(n,v,old)=>{if((t.globals.get(n)??null)!==old)return false;t.globals.set(n,v);return true;},
    ParameterSetRange:(name,enable,value)=>{t.parameters[name]={enable,value};return !t.parameterRefused;},
    FolderCreate:(p,common)=>{h.dirs.add(key(p,common));return true;},
    FileIsExist:(p,common)=>{const k=key(p,common);if(h.files.has(k))return true;if(h.dirs.has(k))lastError=5018;return false;},
    FileGetInteger:(p,prop,common)=>(h.files.get(key(p,common))||{}).mtime||0,
    FileDelete:(p,common)=>{mutate('delete '+p);return h.files.delete(key(p,common));},
    FileMove:(a,af,b,bf)=>{mutate('move '+a);const s=key(a,af&F.FILE_COMMON),d=key(b,bf&F.FILE_COMMON);if(!h.files.has(s))return false;
      if(h.files.has(d)&&!(bf&F.FILE_REWRITE))return false;h.files.set(d,h.files.get(s));h.files.delete(s);return true;},
    FileOpen:(p,mode)=>{const k=key(p,mode&F.FILE_COMMON);h.opened.push(k);
      if(k==='L|'+dataPath+'|'+GATE){if(t.gateHeld||!h.files.has(k))return -1;handles.set(next,{gate:true});return next++;}
      if(t.openHook)t.openHook(p,mode);
      if(mode&F.FILE_WRITE&&!(mode&F.FILE_READ&&h.files.has(k)&&mode&F.FILE_SHARE_READ)){handles.set(next,{k,write:true,buf:''});return next++;}
      const file=h.files.get(k);if(!file)return -1;
      const lines=file.text.split(/\r?\n/);if(file.text.endsWith('\n'))lines.pop();
      handles.set(next,{k,lines,pos:0,size:file.text.length,write:!!(mode&F.FILE_WRITE),buf:''});return next++;},
    FileReadString:id=>{const x=handles.get(id);return x&&x.lines&&x.pos<x.lines.length?x.lines[x.pos++]:'';},
    FileIsEnding:id=>{const x=handles.get(id);return !x||!x.lines||x.pos>=x.lines.length;},
    FileSize:id=>handles.get(id).size,FileWriteString:(id,s)=>{handles.get(id).buf+=s;return s.length;},FileFlush:()=>{},
    FileWrite:(id,v)=>{handles.get(id).buf+=String(v)+'\r\n';return 1;},
    FileClose:id=>{const x=handles.get(id);if(x&&x.write&&!x.gate){mutate('write '+x.k);h.files.set(x.k,{text:x.buf,mtime:h.clock});}handles.delete(id);},
    FileFindFirst:(pattern,common)=>{const folder=pattern.slice(0,pattern.lastIndexOf('\\')+1),glob=pattern.slice(folder.length).toLowerCase();
      const re=new RegExp('^'+glob.replace(/[.]/g,'\\.').replace(/\*/g,'[^\\\\]*')+'$'),prefix=key(folder,common);
      const found=[...h.files.keys()].filter(k=>k.startsWith(prefix)&&re.test(k.slice(prefix.length))).map(k=>k.slice(prefix.length));
      if(!found.length)return -1;handles.set(next,{found,pos:1});c.__found=found[0];return next++;},
    FileFindNext:id=>{const x=handles.get(id);if(x.pos>=x.found.length)return false;c.__found=x.found[x.pos++];return true;},
    FileFindClose:id=>handles.delete(id),Symbol:()=>'EURUSD',
    // OnTesterInit collaborators outside this test's scope.
    GoatBatchStartAllowed:()=>true,SeedFarmingPrepareReceiver:()=>false,ShowPrompt:()=>{},
    AdjustFitness:f=>f,fitness:0,fitness_real:0,trades:10,mean_duration:1,readVal:0,FileTester_handle:-1,
    g_GOATCredentialMigrationChecked:false,g_goat_opt_terminal_hash:'',g_goat_opt_login:'',g_batchStartupAccepted:false,
    requestHeaders:'Content-Type: application/json; charset=UTF-8\r\n',g_GOATDeviceActivationCandidate:'',g_GOATDeviceActivationAccountId:''};
  vm.createContext(c);vm.runInContext(program,c);t.c=c;return t;
}
const put=(h,p,text,mtime=1)=>h.files.set('C|'+p.toLowerCase(),{text,mtime});
const get=(h,p)=>(h.files.get('C|'+p.toLowerCase())||{}).text;
const commonUnder=(h,folder)=>[...h.files.keys()].filter(k=>k.startsWith('C|'+folder.toLowerCase()+'\\')).map(k=>k.slice(folder.length+3));
const token=ch=>'goat_ea_'+ch.repeat(64);
const LEGACY='GOAT\\Credentials\\api-bearer-v149.token';
const BANKER='G:\\MetaTrader5 Data\\Terminals\\Terminal 1 - Banker',T2='G:\\MetaTrader5 Data\\Terminals\\Terminal 2 - GOAT';
let passed=0;const ok=(cond,msg)=>{assert.ok(cond,msg);passed++;};

// ---- INV-BATCH-01: the path formula. Pins are shared with controller/test_studio_terminal_isolation.py.
{
  const h=host(),banker=terminal(h,3000082754,BANKER),peer=terminal(h,3000082754,T2),other=terminal(h,3000107825,BANKER);
  ok(banker.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo')==='GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-c2408708','pinned Banker base');
  ok(peer.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo')==='GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-30d46804','same login, second terminal');
  ok(other.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo')!==banker.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo'),'other login, same data path');
  ok(banker.c.GoatOptLegacyBasePath('GOAT V1.49','Darwinex-Demo')==='GOAT\\GOAT V1.49-Darwinex-Demo','legacy shared base');
  ok(terminal(h,3000082754,'g:/metatrader5 data/terminals/terminal 1 - banker/').c.GoatOptTerminalHash()==='c2408708','case, slash and trailing separator normalised');
  const flapping=terminal(h,3000082754,BANKER);flapping.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo');flapping.login=0;
  ok(flapping.c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo').endsWith('-3000082754-c2408708'),'a momentary zero login keeps the namespace');
  ok(terminal(h,0,BANKER).c.GoatOptBasePath('GOAT V1.49','Darwinex-Demo').endsWith('-0-c2408708'),'no account never resolves the shared base');
  // Foreign = another terminal's hash only; this terminal under any login, -0- or any case still blocks.
  const own=banker.c.GoatOptTerminalHash();
  ok(banker.c.GoatOptForeignNamespaceFolder('GOAT V1.49-Darwinex-Demo-3000082754-30d46804',own),'other terminal folder is foreign');
  ok(banker.c.GoatOptForeignNamespaceFolder('GOAT V1.49-Darwinex-Demo-3000082754-30D46804',own),'other terminal folder in upper case is foreign');
  for(const mine of ['GOAT V1.49-Darwinex-Demo-3000082754-c2408708','GOAT V1.49-Darwinex-Demo-3000107825-c2408708','GOAT V1.49-Darwinex-Demo-0-c2408708',
                     'GOAT V1.49-Darwinex-Demo-3000082754-C2408708','GOAT V1.48-Customer-Demo-1-c2408708'])
    ok(!banker.c.GoatOptForeignNamespaceFolder(mine,own),'this terminal still blocks: '+mine);
  for(const shared of ['GOAT V1.49-Darwinex-Demo','GOAT V1.48-Customer-Demo','GOAT V1.49-Demo-x-0123abcd','GOAT V1.49-Demo-1-0123abcg'])
    ok(!banker.c.GoatOptForeignNamespaceFolder(shared,own),'shared/legacy folder still blocks: '+shared);
}

// ---- INV-BATCH-01 tester side: OnTesterInit and every agent use one nonce-keyed fitness file per run.
{
  const h=host(),init=terminal(h,3000082754,BANKER),agent=terminal(h,3000082754,BANKER),other=terminal(h,3000107825,T2);
  for(const t of [init,other])t.c.Mode_Opti=2;
  ok(init.c.OnTesterInit()===0&&other.c.OnTesterInit()===0,'optimizations initialise');
  const nonce=init.parameters.GOAT_FitnessRunNonce;
  ok(nonce&&nonce.enable===false&&nonce.value===init.c.g_goat_fitness_nonce&&nonce.value>0,'OnTesterInit hands its nonce to the agents');
  const file=init.c.GoatOptTesterFitnessFile(init.c.EA_Desc,'EURUSD',nonce.value);
  ok(get(h,file)==='0.02\r\n','OnTesterInit seeds the per-run file');
  ok(file!==other.c.GoatOptTesterFitnessFile(other.c.EA_Desc,'EURUSD',other.parameters.GOAT_FitnessRunNonce.value),'same EA_Desc and symbol on two terminals: separate files');
  ok(!/Tester\.txt"/.test(M.slice(M.indexOf('int OnTesterInit()'),M.indexOf('bool StartExporter('))),'no shared GOAT\\Tester.txt remains in the batch tester path');
  const deinit=M.slice(M.indexOf('void OnTesterDeinit()'));
  ok(/FileDelete\(GoatOptTesterFitnessFile\(EA_Desc,Symbol\(\),g_goat_fitness_nonce\),FILE_COMMON\)/.test(deinit.slice(0,deinit.indexOf('seedFarming'))),'OnTesterDeinit deletes exactly its run file');
  const run=(t,{stored,fitness})=>{Object.assign(t.c,{Mode_Opti:2,optimization:1,forward:0,GOAT_FitnessRunNonce:nonce.value,fitness,fitness_real:fitness});
    if(stored===undefined)h.files.delete('C|'+file.toLowerCase());else put(h,file,stored);t.c.AgentFitness();return get(h,file);};
  ok(run(agent,{stored:'0.02\r\n',fitness:5})==='5\r\n','agent raises the running maximum in its run file');
  ok(run(agent,{stored:'9\r\n',fitness:5})==='9\r\n','a lower fitness never overwrites the maximum');
  ok(run(agent,{stored:undefined,fitness:5})===undefined,'missing file: bounded wait, nothing written');
  ok(run(agent,{stored:'',fitness:5})==='','unreadable (empty) maximum is never overwritten');
  init.parameterRefused=true;const refused=terminal(h,3000082754,BANKER);refused.parameterRefused=true;refused.c.Mode_Opti=2;
  ok(refused.c.OnTesterInit()===1,'optimization refused when the nonce cannot be handed to agents');
  ok(Object.keys(refused.parameters).length===1&&[...h.files.keys()].filter(k=>k.includes('tester-')).length===2,'refusal precedes any fitness file');
  // The native readback tolerates only a plain non-optimized integer for the nonce.
  for(const v of ['0','1759363200123456','5||5||1||5||N'])ok(init.c.GoatStudioRunNonceValue(v),'nonce readback accepted: '+v);
  for(const v of ['','-1','x','5||5||1||5||Y','5||5||1||N','1.5'])ok(!init.c.GoatStudioRunNonceValue(v),'nonce readback refused: '+v);
}

// ---- INV-CRED-01: two licensed terminals on one PC.
{
  const h=host(),A=terminal(h,3000082754,BANKER),B=terminal(h,3000107825,T2);
  ok(A.c.GOATApiBearerFile()==='GOAT\\Credentials\\api-bearer-v149-3000082754.token','per-login credential path');
  ok(terminal(h,0,BANKER).c.GOATApiBearerFile()==='GOAT\\Credentials\\no-account.token','no account: never the shared file');
  put(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token',token('b'),h.clock); // B stays licensed
  const pair=(t,account,ch)=>{t.c.g_GOATDeviceActivationCandidate=token(ch);t.c.g_GOATDeviceActivationAccountId=String(account);return t.c.GOATDeviceActivationWriteCredential();};
  const readHeaders=t=>vm.runInContext('(function(){let h="";return GOATBuildAuthenticatedRequestHeaders(h);})()',t.c);
  h.clock++;ok(pair(A,3000082754,'a'),'A pairs');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000082754.token')===token('a'),'A credential stored in its own file');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('b'),'B credential untouched by A pairing');
  ok(get(h,LEGACY)===undefined,'shared legacy file never written');
  h.clock++;ok(pair(B,3000107825,'c'),'B re-pairs');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000082754.token')===token('a'),'A credential untouched by B pairing');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('c'),'B credential replaced only in B file');
  ok(readHeaders(A)&&readHeaders(B),'both terminals licensed at once');
  const opened=h.opened.length;readHeaders(A);
  ok(h.opened.slice(opened).every(k=>!k.includes('3000107825')),'A never opens B credential');
  h.clock++;ok(!pair(A,3000107825,'d'),'account mismatch refused');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('c'),'mismatch wrote nothing');
  // The login reads 0 in the middle of the write: the path was fixed from the approved account.
  const late=terminal(h,3000082754,BANKER);late.openHook=p=>{if(p.endsWith('.pending'))late.login=0;};
  pair(late,3000082754,'e');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000082754.token')===token('e')&&get(h,'GOAT\\Credentials\\no-account.token')===undefined
     &&get(h,'GOAT\\Credentials\\no-account.token.pending')===undefined,'mid-write zero login never writes no-account.token');
}

// ---- Credential migration: copy only, only when this login provably wrote the shared file.
{
  const status=(h,name,account,reason,mtime,build='V1.49-NDX-SYMBOL-MAP-31')=>put(h,'GOAT\\activation-status-'+name+'.json',
    '{"accountId":"'+account+'","buildId":"'+build+'","reason":"'+reason+'","httpStatus":200,"nativeError":0,"retrySeconds":0,"observedAtUtc":1}',mtime);
  const own='GOAT\\Credentials\\api-bearer-v149-3000082754.token';
  const scenario=(setup)=>{const h=host();setup(h);const t=terminal(h,3000082754,BANKER);t.c.GOATCredentialMigrateLegacyOnce();return {h,t};};
  let r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',10);});
  ok(get(r.h,own)===token('a')&&get(r.h,LEGACY)===token('a'),'proven own legacy credential copied; legacy kept');
  ok(r.t.logs.some(l=>/copied the shared V1\.49 credential/.test(l))&&!r.t.logs.join().includes('goat_ea_'),'copy logged without the token');
  r=scenario(h=>{put(h,LEGACY,token('b'),20);status(h,'Terminal 1 - Banker','3000082754','approved',10);status(h,'Terminal 2 - GOAT','3000107825','activation_oninit_observed',21);});
  ok(get(r.h,own)===undefined&&get(r.h,LEGACY)===token('b'),'Banker case: another login overwrote the shared file; left untouched');
  ok(!r.h.opened.includes('C|'+LEGACY.toLowerCase()),'another login token is never opened');
  r=scenario(h=>{put(h,LEGACY,token('a'),20);status(h,'Terminal 1 - Banker','3000082754','approved',10);});
  ok(get(r.h,own)===undefined&&!r.h.opened.includes('C|'+LEGACY.toLowerCase()),'own approval older than the shared file is not proof');
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',10);status(h,'Terminal 2 - GOAT','3000107825','approved',12);});
  ok(get(r.h,own)===undefined,'ambiguous later approvals: no copy');
  for(const reason of ['awaiting_approval','activation_reload_pending','ACTIVATION_RELOAD_REQUIRED','activation_oninit_observed']){
    r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754',reason,11);});
    ok(get(r.h,own)===undefined,reason+' is not proof of authorship');
  }
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',11,'V1.48-PAIR-1');});
  ok(get(r.h,own)===undefined,'other version family is not proof');
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',10);put(h,own,token('z'),5);});
  ok(get(r.h,own)===token('z'),'existing per-login credential is never replaced');
  ok(!r.h.opened.includes('C|'+LEGACY.toLowerCase()),'an account with its own credential never opens the shared file');
}

// ---- INV-BATCH-01 migration: the production EA mover over a shared pre-isolation folder.
const legacyBase='GOAT\\GOAT V1.49-Darwinex-Demo',bankerBase='GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-c2408708',peerBase='GOAT\\GOAT V1.49-Darwinex-Demo-3000107825-30d46804';
const pointer=run=>'[ActiveOptimizationRun]\r\nRunPath='+run+'\r\nUpdatedAt=2026.10.01 00:00:00\r\n';
const guard='[ActiveOptimizationLaunch]\r\nLaunchId=1_2\r\nRunPath=GOAT\\Rabcdefabcdef\r\nConfigPath='+legacyBase+'\\active_optimization_config.ini\r\nCreatedAt=x\r\n';
const SHARED=['active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini'];
const sharedState=h=>{put(h,legacyBase+'\\active_optimization_run.ini',pointer('GOAT\\Rabcdefabcdef'));put(h,legacyBase+'\\active_optimization_config.ini','[Tester]\r\n');put(h,legacyBase+'\\active_optimization_launch.ini',guard);};
const move=(t,flags=false)=>t.c.GoatOptMigrateLegacyBatchStateLocked('GOAT V1.49','Darwinex-Demo',flags);
const wrapper=t=>t.c.GoatOptMigrateLegacyBatchState('GOAT V1.49','Darwinex-Demo');
{
  let h=host();sharedState(h);
  const t2=terminal(h,3000107825,T2);
  ok(/was not run on this MT5 terminal/.test(move(t2)),'idle terminal leaves another terminal batch in place');
  ok(get(h,legacyBase+'\\active_optimization_run.ini')!==undefined&&/Decision=left_for_other_terminal/.test(get(h,peerBase+'\\terminal-isolation.ini')),'decision recorded, nothing moved');
  const b=terminal(h,3000082754,BANKER,{globals:new Map([['BatchOnGoing',1]])});
  ok(/moved to its own folder/.test(wrapper(b)),'batch owner moves its in-flight state through the wrapper');
  for(const n of SHARED)ok(get(h,legacyBase+'\\'+n)===undefined&&get(h,bankerBase+'\\'+n)!==undefined,'moved '+n);
  ok(get(h,bankerBase+'\\active_optimization_launch.ini').includes('ConfigPath='+bankerBase+'\\active_optimization_config.ini'),'guard follows the moved config');
  ok(/GuardConfigPathBefore=GOAT\\GOAT V1\.49-Darwinex-Demo\\active_optimization_config\.ini/.test(get(h,bankerBase+'\\terminal-isolation.ini')),'old guard path kept in receipt');
  ok(get(h,bankerBase+'\\active_optimization_run.ini')===pointer('GOAT\\Rabcdefabcdef'),'pointer bytes unchanged');
  ok(/Login=3000082754[\s\S]*TerminalHash=c2408708/.test(get(h,legacyBase+'\\terminal-isolation-claim.ini')),'shared folder claim names the mover');
  ok(get(h,legacyBase+'\\migrated-to-3000082754-c2408708.ini')!==undefined,'shared folder records where its state went');
  const temps=b.gvTemp;ok(wrapper(b)===''&&b.gvTemp===temps,'one-time: a decided receipt never takes the lock again');
  // Idle pointer: only the terminal holding the run's local reports takes it.
  h=host();put(h,legacyBase+'\\active_optimization_run.ini',pointer('GOAT\\Rabcdefabcdef'));
  const local=terminal(h,3000082754,BANKER);h.dirs.add('L|'+BANKER+'|goat\\rabcdefabcdef');
  ok(/moved to its own folder/.test(move(local)),'idle pointer moves to the terminal that ran it');
  // Both folders hold state: refuse, move nothing.
  h=host();put(h,legacyBase+'\\active_optimization_run.ini',pointer(''));put(h,bankerBase+'\\active_optimization_run.ini',pointer('GOAT\\Rffffffffffff'));
  const both=terminal(h,3000082754,BANKER);
  ok(/both the shared folder .* hold batch state/.test(move(both)),'both-exist refusal');
  ok(get(h,legacyBase+'\\active_optimization_run.ini')===pointer('')&&get(h,bankerBase+'\\terminal-isolation.ini')===undefined,'refusal changes nothing');
  // Controller-owned shared controls are never moved by the EA.
  h=host();sharedState(h);put(h,legacyBase+'\\agent-native-control-owner.json','{}');
  const owned=terminal(h,3000082754,BANKER);
  ok(/unfinished controller attempt/.test(move(owned,true))&&get(h,bankerBase+'\\active_optimization_run.ini')===undefined,'owned controls refused');
  // A copied portable terminal carries Banker's flags and local runs: Banker's claim still wins.
  h=host();sharedState(h);const flags=()=>new Map([['BatchOnGoing',1]]);
  const banker=terminal(h,3000082754,BANKER,{globals:flags()}),copy=terminal(h,3000082754,T2,{globals:flags()});
  h.dirs.add('L|'+T2+'|goat\\rabcdefabcdef');
  ok(/moved to its own folder/.test(wrapper(banker)),'Banker loads SM32 first and moves');
  ok(/claimed the shared folder|Nothing|^$/.test(wrapper(copy))&&commonUnder(h,'GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-30d46804').every(n=>!SHARED.includes(n)),'the copy never adopts Banker state');
  h=host();sharedState(h);put(h,legacyBase+'\\terminal-isolation-claim.ini','[TerminalIsolationClaim]\r\nLogin=3000082754\r\nTerminalHash=c2408708\r\n');
  const late=terminal(h,3000082754,T2,{globals:flags()});
  ok(/claimed the shared folder .* first/.test(move(late,true))&&SHARED.every(n=>get(h,legacyBase+'\\'+n)!==undefined),'claim held by another terminal: nothing moves');
}

// ---- Interrupted moves resume; unexpected receipts never move arbitrary files.
{
  const moving=(planned,before='')=>'[TerminalIsolation]\r\nDecision=moving\r\nPlanned='+planned+'\r\nGuardConfigPathBefore='+before+'\r\n';
  const claimed=h=>put(h,legacyBase+'\\terminal-isolation-claim.ini','[TerminalIsolationClaim]\r\nLogin=3000082754\r\nTerminalHash=c2408708\r\n');
  let h=host();put(h,legacyBase+'\\log.GOAT','log');put(h,bankerBase+'\\active_optimization_run.ini',pointer(''));claimed(h);
  put(h,bankerBase+'\\terminal-isolation.ini',moving('log.GOAT|active_optimization_run.ini'));
  let t=terminal(h,3000082754,BANKER);move(t);
  ok(get(h,bankerBase+'\\log.GOAT')==='log'&&/Decision=moved/.test(get(h,bankerBase+'\\terminal-isolation.ini')),'interrupted move resumes');
  // Crash after the new guard landed but before the old one was removed.
  h=host();claimed(h);put(h,legacyBase+'\\active_optimization_launch.ini',guard);
  const rewritten=guard.split('ConfigPath='+legacyBase).join('ConfigPath='+bankerBase);
  put(h,bankerBase+'\\active_optimization_launch.ini',rewritten);
  put(h,bankerBase+'\\terminal-isolation.ini',moving('active_optimization_launch.ini',legacyBase+'\\active_optimization_config.ini'));
  t=terminal(h,3000082754,BANKER);
  ok(/moved to its own folder/.test(move(t))&&get(h,legacyBase+'\\active_optimization_launch.ini')===undefined&&get(h,bankerBase+'\\active_optimization_launch.ini')===rewritten,'guard crash between write and delete completes on resume');
  ok(/GuardConfigPathBefore=GOAT\\GOAT V1\.49-Darwinex-Demo\\active_optimization_config\.ini/.test(get(h,bankerBase+'\\terminal-isolation.ini')),'resumed receipt keeps the old guard path');
  // A different guard in both folders is a real conflict.
  h=host();claimed(h);put(h,legacyBase+'\\active_optimization_launch.ini',guard);put(h,bankerBase+'\\active_optimization_launch.ini','[ActiveOptimizationLaunch]\r\nLaunchId=other\r\n');
  put(h,bankerBase+'\\terminal-isolation.ini',moving('active_optimization_launch.ini'));
  ok(/exists in both/.test(move(terminal(h,3000082754,BANKER))),'different guard in both folders refused');
  h=host();claimed(h);put(h,legacyBase+'\\log.GOAT','old');put(h,bankerBase+'\\log.GOAT','new');put(h,bankerBase+'\\terminal-isolation.ini',moving('log.GOAT'));
  ok(/log\.GOAT exists in both/.test(move(terminal(h,3000082754,BANKER)))&&get(h,legacyBase+'\\log.GOAT')==='old'&&get(h,bankerBase+'\\log.GOAT')==='new','plain file in both folders refused, nothing overwritten');
  // A staged guard left by a crash before its rename is simply rewritten.
  h=host();claimed(h);put(h,legacyBase+'\\active_optimization_launch.ini',guard);put(h,bankerBase+'\\active_optimization_launch.ini.moving','partial');
  put(h,bankerBase+'\\terminal-isolation.ini',moving('active_optimization_launch.ini'));
  ok(/moved to its own folder/.test(move(terminal(h,3000082754,BANKER)))&&get(h,bankerBase+'\\active_optimization_launch.ini')===rewritten,'stale staged guard does not block');
  h=host();claimed(h);put(h,'GOAT\\GOAT V1.49-Darwinex-Demo\\..\\x','victim');put(h,bankerBase+'\\terminal-isolation.ini',moving('..\\x|log.GOAT'));
  ok(/unexpected file/.test(move(terminal(h,3000082754,BANKER)))&&get(h,'GOAT\\GOAT V1.49-Darwinex-Demo\\..\\x')==='victim','unexpected Planned name refused');
  h=host();put(h,legacyBase+'\\log.GOAT','log');put(h,legacyBase+'\\terminal-isolation-claim.ini','[TerminalIsolationClaim]\r\nLogin=3000107825\r\nTerminalHash=30d46804\r\n');
  put(h,bankerBase+'\\terminal-isolation.ini',moving('log.GOAT'));
  ok(/claimed by another MT5 terminal/.test(move(terminal(h,3000082754,BANKER)))&&get(h,legacyBase+'\\log.GOAT')==='log','resume refuses when another terminal holds the claim');
  h=host();const clean=terminal(h,3000082754,BANKER);
  ok(move(clean)===''&&/Decision=nothing_to_move/.test(get(h,bankerBase+'\\terminal-isolation.ini')),'nothing to move recorded');
}

// ---- The wrapper: chart lock, native gate and no-account skip.
{
  let h=host();sharedState(h);let t=terminal(h,3000082754,BANKER,{globals:new Map([['BatchOnGoing',1],['GOAT_StateIsolationLock',1]])});
  ok(/another GOAT chart in this terminal/.test(wrapper(t))&&SHARED.every(n=>get(h,legacyBase+'\\'+n)!==undefined),'chart lock held: nothing moves');
  h=host();sharedState(h);t=terminal(h,3000082754,BANKER,{globals:new Map([['BatchOnGoing',1]])});
  h.files.set('L|'+BANKER+'|'+GATE,{text:'',mtime:1});t.gateHeld=true;
  ok(/controller is busy/.test(wrapper(t))&&SHARED.every(n=>get(h,legacyBase+'\\'+n)!==undefined)&&t.globals.get('GOAT_StateIsolationLock')===0,'native gate held: deferred, lock released');
  t.gateHeld=false;ok(/moved to its own folder/.test(wrapper(t)),'gate free: moves under the gate');
  h=host();sharedState(h);t=terminal(h,0,BANKER,{globals:new Map([['BatchOnGoing',1]])});
  ok(wrapper(t)===''&&t.gvTemp===0&&[...h.files.keys()].every(k=>!k.includes('-0-')),'no account: never decides, claims or writes');
  h=host();sharedState(h);t=terminal(h,3000082754,BANKER);t.c.tester=1;
  ok(wrapper(t)===''&&t.gvTemp===0,'tester agents never migrate');
}

// ---- Concurrency: terminal B runs its whole move between any two of terminal A's file operations.
{
  let steps=0;{const h=host();sharedState(h);const a=terminal(h,3000082754,BANKER,{globals:new Map([['BatchOnGoing',1]])});wrapper(a);steps=a.mutations;}
  ok(steps>=6,'interleaving covers every file operation of a move ('+steps+')');
  for(let k=0;k<=steps;k++)for(const sameLogin of [false,true]){
    const h=host();sharedState(h);
    const a=terminal(h,3000082754,BANKER,{globals:new Map([['BatchOnGoing',1]])});
    const b=terminal(h,sameLogin?3000082754:3000107825,T2,{globals:new Map([['BatchOnGoing',1]])});
    const bBase=sameLogin?'GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-30d46804':peerBase;
    h.hook=(t,op)=>{if(t===a&&a.mutations===k+1){h.hook=null;wrapper(b);}};
    if(k===steps){wrapper(a);h.hook=null;wrapper(b);}else wrapper(a);
    const where=n=>[legacyBase,bankerBase,bBase].filter(f=>get(h,f+'\\'+n)!==undefined);
    const tag=' (B after A step '+k+(sameLogin?', same login)':')');
    ok(SHARED.every(n=>where(n).length===1),'every file exists exactly once'+tag);
    const inA=SHARED.filter(n=>get(h,bankerBase+'\\'+n)!==undefined),inB=SHARED.filter(n=>get(h,bBase+'\\'+n)!==undefined);
    ok(inA.length===0||inB.length===0,'only one terminal ever receives the shared state'+tag);
    const claim=get(h,legacyBase+'\\terminal-isolation-claim.ini')||'',holder=/TerminalHash=c2408708/.test(claim)?inA:inB;
    ok(claim!==''&&holder.length===SHARED.length,'the claim holder, and only it, received everything'+tag);
  }
}
console.log(JSON.stringify({passed,terminalIsolation:true,perLoginCredential:true,concurrentMoves:true,nativeExecution:false}));
