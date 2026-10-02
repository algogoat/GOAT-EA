// Terminal isolation (INV-BATCH-01, INV-CRED-01): runs the production V1.49 MQL path,
// credential and migration functions in a JS VM over a simulated Common Files store
// shared by several terminals. MQL-free: no MetaEditor, MT5 or network is used.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const read=n=>fs.readFileSync(path.join(root,n),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const defs=read('GOAT_Inputs_Definitions.mqh'),activation=read('GOATEADeviceActivation.mqh'),main=read('GOAT V1.49.mq5');

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
function extract(text,name){
  const start=text.search(new RegExp('^(?:string|bool|void|int|long)\\s+'+name+'\\s*\\(','m'));
  assert.ok(start>=0,'missing '+name);
  let brace=text.indexOf('{',start),depth=1,end=brace+1,quote='';
  while(depth){
    assert.ok(end<text.length,'unbalanced '+name);
    const ch=text[end];
    if(quote){if(ch==='\\')end++;else if(ch===quote)quote='';}
    else if(ch==='"'||ch==="'")quote=ch;
    else if(ch==='{')depth++;
    else if(ch==='}')depth--;
    end++;
  }
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
const isolation=new Set(['GOAT_TERMINAL_ISOLATION_V149','GOAT_MONITOR_ONBOARDING_V149','GOAT_ORPHAN_RECOVERY_V149']);
const D=stripComments(preprocess(defs,isolation)),A=stripComments(preprocess(activation,isolation));
const names=['GOATIsSafeApiBearerToken','GOATAccountLoginDigits','GOATApiBearerFileFor','GOATApiBearerFile','GOATCredentialStatusApproved',
  'GOATCredentialMigrateLegacyOnce','GOATBuildAuthenticatedRequestHeaders','GoatOptLegacyBasePath','GoatOptTerminalHash','GoatOptLoginToken',
  'GoatOptBasePath','GoatOptFolderOf','GoatOptEnsureCommonFolderTree','GoatOptWriteTextFile','GoatOptReadTextFile','GoatOptReadIniValue',
  'GoatOptIsolationFlagsHeld','GoatOptIsolationReceipt','GoatOptMigrateLegacyBatchStateLocked','GoatOptForeignNamespaceFolder','GoatOptTesterFitnessFile'];
let program=names.map(n=>extract(D,n)).join('\n')+'\n'+extract(A,'GOATDeviceActivationWriteCredential');
program=program.replace(/\bGOAT_API_BEARER_FILE\b/g,'GOATApiBearerFile()').replace(/\bGOAT_API_BEARER_LEGACY_FILE\b/g,'"GOAT\\\\Credentials\\\\api-bearer-v149.token"')
  .replace(/\bGOAT_OPT_ISOLATION_RECEIPT\b/g,'"terminal-isolation.ini"').replace(/\bGOAT_VERSION_LABEL\b/g,'"1.49"').replace(/\bKey\b/g,'"GOAT"').replace(/\bEA_Name\b/g,'"GOAT V1.49"');
assert.match(main,/#define GOAT_TERMINAL_ISOLATION_V149 1\r?\n#define GOAT_API_BEARER_LEGACY_FILE "GOAT\\\\Credentials\\\\api-bearer-v149\.token"\r?\n#define GOAT_API_BEARER_FILE GOATApiBearerFile\(\)\r?\n#include "GOAT_Inputs_Definitions\.mqh"/);

// ---- One Windows user: a Common Files store shared by every terminal, local Files per terminal.
const F={FILE_READ:1,FILE_WRITE:2,FILE_BIN:4,FILE_TXT:16,FILE_ANSI:32,FILE_UNICODE:64,FILE_SHARE_READ:128,FILE_SHARE_WRITE:256,FILE_REWRITE:512,FILE_COMMON:4096};
function host(){return {files:new Map(),dirs:new Set(),clock:1000,opened:[]};}
function terminal(h,login,dataPath,{globals=new Map()}={}){
  const t={login,dataPath,logs:[],globals};let handles=new Map(),next=1,lastError=0;
  const key=(p,common)=>(common?'C|':'L|'+dataPath+'|')+p.toLowerCase();
  const c={...F,INVALID_HANDLE:-1,ACCOUNT_LOGIN:1,TERMINAL_DATA_PATH:2,MQL_TESTER:3,WHOLE_ARRAY:-1,CP_UTF8:65001,CRYPT_HASH_SHA256:6,
    FILE_MODIFY_DATE:9,ERR_FILE_IS_DIRECTORY:5018,TIME_DATE:1,TIME_SECONDS:4,__found:'',
    AccountInfoInteger:()=>t.login,TerminalInfoString:()=>t.dataPath,MQLInfoInteger:()=>0,IntegerToString:n=>String(n),
    StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.substr(a,n),StringFind:(s,x,from=0)=>s.indexOf(x,from),
    StringGetCharacter:(s,i)=>s.charCodeAt(i),__replace:(s,a,b)=>s.split(a).join(b),
    StringToShortArray:(s,arr,start,count)=>{arr.length=0;for(let i=0;i<count;i++)arr.push(s.charCodeAt(i));return count;},
    ShortArrayToString:(arr,start,count)=>String.fromCharCode(...arr.slice(start,start+count)),
    StringToCharArray:(s,arr)=>{arr.length=0;for(const b of Buffer.from(s,'utf8'))arr.push(b);arr.push(0);return arr.length;},
    ArrayResize:(arr,n)=>{arr.length=n;return n;},ArraySize:a=>a.length,
    CryptEncode:(m,data,k,digest)=>{digest.length=0;for(const b of crypto.createHash('sha256').update(Buffer.from(data)).digest())digest.push(b);return 32;},
    StringFormat:(f,v)=>v.toString(16).padStart(2,'0'),
    StringSplit:(s,sep,arr)=>{arr.length=0;for(const p of s.split(String.fromCharCode(sep)))arr.push(p);return arr.length;},
    TimeToString:()=>'2026.10.02 00:00:00',TimeGMT:()=>h.clock,Print:m=>t.logs.push(m),Sleep:()=>{},
    ResetLastError:()=>{lastError=0;},GetLastError:()=>lastError,
    GlobalVariableGet:n=>t.globals.get(n)??0,GlobalVariableSet:(n,v)=>{t.globals.set(n,v);return 1;},
    FolderCreate:(p,common)=>{h.dirs.add(key(p,common));return true;},
    FileIsExist:(p,common)=>{const k=key(p,common);if(h.files.has(k))return true;if(h.dirs.has(k))lastError=5018;return false;},
    FileGetInteger:(p,prop,common)=>(h.files.get(key(p,common))||{}).mtime||0,
    FileDelete:(p,common)=>h.files.delete(key(p,common)),
    FileMove:(a,af,b,bf)=>{const s=key(a,af&F.FILE_COMMON),d=key(b,bf&F.FILE_COMMON);if(!h.files.has(s))return false;
      if(h.files.has(d)&&!(bf&F.FILE_REWRITE))return false;h.files.set(d,h.files.get(s));h.files.delete(s);return true;},
    FileOpen:(p,mode)=>{const k=key(p,mode&F.FILE_COMMON);h.opened.push(k);
      if(mode&F.FILE_WRITE){handles.set(next,{k,write:true,buf:''});return next++;}
      const file=h.files.get(k);if(!file)return -1;
      const lines=file.text.split(/\r?\n/);if(file.text.endsWith('\n'))lines.pop();
      handles.set(next,{k,lines,pos:0,size:file.text.length});return next++;},
    FileReadString:id=>{const x=handles.get(id);return x&&x.pos<x.lines.length?x.lines[x.pos++]:'';},
    FileIsEnding:id=>{const x=handles.get(id);return !x||x.pos>=x.lines.length;},
    FileSize:id=>handles.get(id).size,FileWriteString:(id,s)=>{handles.get(id).buf+=s;return s.length;},FileFlush:()=>{},
    FileClose:id=>{const x=handles.get(id);if(x&&x.write){h.files.set(x.k,{text:x.buf,mtime:h.clock});}handles.delete(id);},
    FileFindFirst:(pattern,common)=>{const folder=pattern.slice(0,pattern.lastIndexOf('\\')+1),glob=pattern.slice(folder.length).toLowerCase();
      const re=new RegExp('^'+glob.replace(/[.]/g,'\\.').replace(/\*/g,'[^\\\\]*')+'$'),prefix=key(folder,common);
      const found=[...h.files.keys()].filter(k=>k.startsWith(prefix)&&re.test(k.slice(prefix.length))).map(k=>k.slice(prefix.length));
      if(!found.length)return -1;handles.set(next,{found,pos:1});c.__found=found[0];return next++;},
    FileFindNext:id=>{const x=handles.get(id);if(x.pos>=x.found.length)return false;c.__found=x.found[x.pos++];return true;},
    FileFindClose:id=>handles.delete(id),
    g_GOATCredentialMigrationChecked:false,g_goat_opt_terminal_hash:'',g_goat_opt_login:'',
    requestHeaders:'Content-Type: application/json; charset=UTF-8\r\n',g_GOATDeviceActivationCandidate:'',g_GOATDeviceActivationAccountId:''};
  vm.createContext(c);vm.runInContext(program,c);t.c=c;return t;
}
const put=(h,p,text,mtime)=>h.files.set('C|'+p.toLowerCase(),{text,mtime});
const get=(h,p)=>(h.files.get('C|'+p.toLowerCase())||{}).text;
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
  const own='GOAT V1.49-Darwinex-Demo-3000082754-c2408708';
  ok(banker.c.GoatOptForeignNamespaceFolder('GOAT V1.49-Darwinex-Demo-3000082754-30d46804',own),'other terminal folder is foreign');
  ok(!banker.c.GoatOptForeignNamespaceFolder(own,own),'own folder is not foreign');
  for(const shared of ['GOAT V1.49-Darwinex-Demo','GOAT V1.48-Customer-Demo','GOAT V1.49-Broker-Demo-1-ABCDEF12','GOAT V1.49-Demo-x-0123abcd'])
    ok(!banker.c.GoatOptForeignNamespaceFolder(shared,own),'shared/legacy folder still blocks: '+shared);
  // Tester side: agents and OnTesterInit/OnTesterDeinit share only EA, EA_Desc and symbol.
  const a=banker.c.GoatOptTesterFitnessFile('Rabc','EURUSD'),b=peer.c.GoatOptTesterFitnessFile('Rdef','EURUSD');
  ok(/^GOAT\\Tester-[0-9a-f]{16}\.txt$/.test(a)&&a!==b&&a===other.c.GoatOptTesterFitnessFile('Rabc','EURUSD'),'per-run fitness file, independent of terminal data path');
  ok(!/Tester\.txt"/.test(main.slice(main.indexOf('int OnTesterInit()'),main.indexOf('bool StartExporter(')).replace(/\/\/[^\n]*/g,'')),'no shared GOAT\\Tester.txt remains in the batch tester path');
}

// ---- INV-CRED-01: two licensed terminals on one PC.
{
  const h=host(),A=terminal(h,3000082754,BANKER),B=terminal(h,3000107825,T2);
  ok(A.c.GOATApiBearerFile()==='GOAT\\Credentials\\api-bearer-v149-3000082754.token','per-login credential path');
  ok(terminal(h,0,BANKER).c.GOATApiBearerFile()==='GOAT\\Credentials\\no-account.token','no account: never the shared file');
  put(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token',token('b'),h.clock); // B stays licensed
  const pair=(t,account,ch)=>{t.c.g_GOATDeviceActivationCandidate=token(ch);t.c.g_GOATDeviceActivationAccountId=String(account);return t.c.GOATDeviceActivationWriteCredential();};
  h.clock++;ok(pair(A,3000082754,'a'),'A pairs');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000082754.token')===token('a'),'A credential stored in its own file');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('b'),'B credential untouched by A pairing');
  ok(get(h,LEGACY)===undefined,'shared legacy file never written');
  // Reverse: B re-pairs while A stays licensed.
  h.clock++;ok(pair(B,3000107825,'c'),'B re-pairs');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000082754.token')===token('a'),'A credential untouched by B pairing');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('c'),'B credential replaced only in B file');
  // Each terminal reads only its own login's file.
  // MQL passes headers by reference; the production reader's boolean result is what licenses a terminal.
  const readHeaders=t=>vm.runInContext('(function(){let h="";return GOATBuildAuthenticatedRequestHeaders(h);})()',t.c);
  ok(readHeaders(A)&&readHeaders(B),'both terminals licensed at once');
  const opened=h.opened.length;readHeaders(A);
  ok(h.opened.slice(opened).every(k=>!k.includes('3000107825')),'A never opens B credential');
  // An approval for another account cannot land in this terminal's per-login file.
  h.clock++;ok(!pair(A,3000107825,'d'),'account mismatch refused');
  ok(get(h,'GOAT\\Credentials\\api-bearer-v149-3000107825.token')===token('c'),'mismatch wrote nothing');
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
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',10);status(h,'Terminal 2 - GOAT','3000107825','approved',12);});
  ok(get(r.h,own)===undefined,'ambiguous later approvals: no copy');
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','awaiting_approval',11);});
  ok(get(r.h,own)===undefined,'pending activation is not proof');
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',11,'V1.48-PAIR-1');});
  ok(get(r.h,own)===undefined,'other version family is not proof');
  r=scenario(h=>{put(h,LEGACY,token('a'),10);status(h,'Terminal 1 - Banker','3000082754','approved',10);put(h,own,token('z'),5);});
  ok(get(r.h,own)===token('z'),'existing per-login credential is never replaced');
  ok(!r.h.opened.includes('C|'+LEGACY.toLowerCase()),'an account with its own credential never opens the shared file');
}

// ---- INV-BATCH-01 migration: the production EA mover over a shared pre-isolation folder.
{
  const legacy='GOAT\\GOAT V1.49-Darwinex-Demo',banker='GOAT\\GOAT V1.49-Darwinex-Demo-3000082754-c2408708',peer='GOAT\\GOAT V1.49-Darwinex-Demo-3000107825-30d46804';
  const pointer=run=>'[ActiveOptimizationRun]\r\nRunPath='+run+'\r\nUpdatedAt=2026.10.01 00:00:00\r\n';
  const guard='[ActiveOptimizationLaunch]\r\nLaunchId=1_2\r\nRunPath=GOAT\\Rabcdefabcdef\r\nConfigPath='+legacy+'\\active_optimization_config.ini\r\nCreatedAt=x\r\n';
  const move=(t,flags=false)=>t.c.GoatOptMigrateLegacyBatchStateLocked('GOAT V1.49','Darwinex-Demo',flags);
  // In-flight batch on Banker: its flags prove ownership; Terminal 2 leaves it alone.
  let h=host();put(h,legacy+'\\active_optimization_run.ini',pointer('GOAT\\Rabcdefabcdef'),1);put(h,legacy+'\\active_optimization_config.ini','[Tester]\r\n',1);put(h,legacy+'\\active_optimization_launch.ini',guard,1);
  const t2=terminal(h,3000107825,T2);
  ok(/was not run on this MT5 terminal/.test(move(t2)),'idle terminal leaves another terminal batch in place');
  ok(get(h,legacy+'\\active_optimization_run.ini')!==undefined&&/Decision=left_for_other_terminal/.test(get(h,peer+'\\terminal-isolation.ini')),'decision recorded, nothing moved');
  const b=terminal(h,3000082754,BANKER);
  ok(/moved to its own folder/.test(move(b,true)),'batch owner moves its in-flight state');
  for(const n of ['active_optimization_run.ini','active_optimization_config.ini','active_optimization_launch.ini'])
    ok(get(h,legacy+'\\'+n)===undefined&&get(h,banker+'\\'+n)!==undefined,'moved '+n);
  ok(get(h,banker+'\\active_optimization_launch.ini').includes('ConfigPath='+banker+'\\active_optimization_config.ini'),'guard follows the moved config');
  ok(/GuardConfigPathBefore=GOAT\\GOAT V1\.49-Darwinex-Demo\\active_optimization_config\.ini/.test(get(h,banker+'\\terminal-isolation.ini')),'old guard path kept in receipt');
  ok(get(h,banker+'\\active_optimization_run.ini')===pointer('GOAT\\Rabcdefabcdef'),'pointer bytes unchanged');
  ok(get(h,legacy+'\\migrated-to-3000082754-c2408708.ini')!==undefined,'shared folder records where its state went');
  ok(move(b,true)==='','one-time: a decided receipt is never re-run');
  // Idle pointer: only the terminal holding the run's local reports takes it.
  h=host();put(h,legacy+'\\active_optimization_run.ini',pointer('GOAT\\Rabcdefabcdef'),1);
  const local=terminal(h,3000082754,BANKER);h.dirs.add('L|'+BANKER+'|goat\\rabcdefabcdef');
  ok(/moved to its own folder/.test(move(local)),'idle pointer moves to the terminal that ran it');
  // Both folders hold state: refuse, move nothing.
  h=host();put(h,legacy+'\\active_optimization_run.ini',pointer(''),1);put(h,banker+'\\active_optimization_run.ini',pointer('GOAT\\Rffffffffffff'),1);
  const both=terminal(h,3000082754,BANKER);
  ok(/both the shared folder .* hold batch state/.test(move(both)),'both-exist refusal');
  ok(get(h,legacy+'\\active_optimization_run.ini')===pointer('')&&get(h,banker+'\\active_optimization_run.ini')===pointer('GOAT\\Rffffffffffff')&&get(h,banker+'\\terminal-isolation.ini')===undefined,'refusal changes nothing');
  // Controller-owned shared controls are never moved by the EA.
  h=host();put(h,legacy+'\\active_optimization_run.ini',pointer('GOAT\\Rabcdefabcdef'),1);put(h,legacy+'\\agent-native-control-owner.json','{}',1);
  const owned=terminal(h,3000082754,BANKER);
  ok(/unfinished controller attempt/.test(move(owned,true))&&get(h,banker+'\\active_optimization_run.ini')===undefined,'owned controls refused');
  // Interrupted move resumes from its receipt; files already moved are not touched again.
  h=host();put(h,legacy+'\\log.GOAT','log',1);put(h,banker+'\\active_optimization_run.ini',pointer(''),1);
  put(h,banker+'\\terminal-isolation.ini','[TerminalIsolation]\r\nDecision=moving\r\nPlanned=log.GOAT|active_optimization_run.ini\r\n',1);
  const resume=terminal(h,3000082754,BANKER);move(resume);
  ok(get(h,banker+'\\log.GOAT')==='log'&&/Decision=moved/.test(get(h,banker+'\\terminal-isolation.ini')),'interrupted move resumes');
  // Nothing shared: record the decision once.
  h=host();const clean=terminal(h,3000082754,BANKER);
  ok(move(clean)===''&&/Decision=nothing_to_move/.test(get(h,banker+'\\terminal-isolation.ini')),'nothing to move recorded');
}
console.log(JSON.stringify({passed,terminalIsolation:true,perLoginCredential:true,nativeExecution:false}));
