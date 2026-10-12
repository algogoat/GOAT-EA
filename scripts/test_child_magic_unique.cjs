// B44: a new child's magic is unique by construction (Exp 03, 2026-10-12, goatai#2350). 36 charts cold-started
// together on the experiment VPS; ChartWindowsHandle(0) returned 0 under load (MT5 error 4102) and two children
// seeded in the same GetTickCount tick drew the same MathRand()+9+ChartWindowsHandle(0) = 27425, so the dashboard
// refused the second one on every launch. GOAT V1.49.mq5 now derives a new live magic from the chart id
// (GoatChildMagicCandidate / GoatChildMagicHeld / GoatDeriveChildMagic) and steps on while another chart's CID
// record holds the value. This runs the production functions (and the real GoatParseChildGVName,
// GoatTruncateCidValue and GoatFindMagicByCid from the input header) after a syntax-only MQL-to-JS conversion
// against a modelled GlobalVariable store, then runs the OnInit magic block itself. Source semantics only: native
// MT5 chart ids and GlobalVariables are not exercised here.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const main=read('GOAT V1.49.mq5'),header=read('GOAT_Inputs_Definitions.mqh');
let passed=0;const ok=()=>passed++;

function bodyOf(text,signature){
 const a=text.indexOf(signature);assert.ok(a>=0,'missing '+signature);
 assert.equal(text.indexOf(signature,a+1),-1,'one definition of '+signature);
 let i=text.indexOf('{',a),depth=1,j=i+1;for(;depth&&j<text.length;j++){if(text[j]==='{')depth++;if(text[j]==='}')depth--;}
 return text.slice(i+1,j-1);
}
function region(text,start,end){
 const a=text.indexOf(start);assert.ok(a>=0,'missing '+start);
 const b=text.indexOf(end,a+start.length);assert.ok(b>a,'missing '+end);
 return text.slice(a,b);
}
const TYPES='(?:const )?(?:string|int|uint|long|ulong|bool|ushort|double)';
function js(text){
 return text.replace(/\/\/.*$/gm,'')
  .replace(/'([^'\\])'/g,(_,c)=>String(c.charCodeAt(0)))
  .replace(new RegExp('\\b'+TYPES+' ','g'),'let ')
  .replace(/\((?:long|int|uint|ulong|double)\)/g,'')
  // By-reference outputs become setter callbacks.
  .replace(/GoatParseChildGVName\((\w+),(\w+),(\w+),(\w+)\)/g,'GoatParseChildGVName($1,v=>$2=v,v=>$3=v,v=>$4=v)')
  .replace(/GoatFindMagicByCid\(([^,()]+(?:\(\))?),([^,()]+(?:\(\))?),(\w+)\)/g,'GoatFindMagicByCid($1,$2,v=>$3=v)');
}
function fn(text,signature,args,body){return 'function '+signature+'('+args.join(',')+'){'+js(body)+'}\n';}

// ---- the production functions, converted ----
const PARSE=bodyOf(header,'bool GoatParseChildGVName(const string gv_name,long &magic,string &symbol,string &field)');
const FIND=bodyOf(header,'bool GoatFindMagicByCid(const string symbol,const long chart_id,long &magic_out)');
const TRUNC=bodyOf(header,'long GoatTruncateCidValue(const long cid)');
const CANDIDATE=bodyOf(main,'int GoatChildMagicCandidate(const long magic_chart,const int magic_n)');
const HELD=bodyOf(main,'bool GoatChildMagicHeld(const int magic_value,const long magic_chart)');
const DERIVE=bodyOf(main,'int GoatDeriveChildMagic(const long magic_chart)');
const once=(text,from,to,label)=>{assert.equal(text.split(from).length,2,'exactly one '+label);return text.replace(from,()=>to);};
const code=
 // GoatParseChildGVName's outputs are written just before its final return.
 'function GoatParseChildGVName(gv_name,__m,__s,__f){let magic=0,symbol="",field="";'
  +js(once(PARSE,'return(symbol!="" && field!="");','__m(magic);__s(symbol);__f(field);return(symbol!="" && field!="");','parse return'))+'}\n'
 +'function GoatFindMagicByCid(symbol,chart_id,__out){let magic_out=0;'+js(FIND).replace(/\bmagic_out=([^;]+);/g,'__out(magic_out=$1);')+'}\n'
 +fn(TRUNC,'GoatTruncateCidValue',['cid'],TRUNC)
 +fn(CANDIDATE,'GoatChildMagicCandidate',['magic_chart','magic_n'],CANDIDATE)
 +fn(HELD,'GoatChildMagicHeld',['magic_value','magic_chart'],HELD)
 +fn(DERIVE,'GoatDeriveChildMagic',['magic_chart'],DERIVE);
// OnInit's magic block, from the restore to the MAGIC2 line (the CID record write follows it unchanged).
const BLOCK=region(main,'    long restored_magic=0;\n','     if(MAGIC2==0)');

// A modelled terminal: GlobalVariables in creation order (MT5 lists them by name; the scan order does not matter).
const KEY=(header.match(/^#define\s+Key\s+"(\w+)"/m)||[])[1];assert.equal(KEY,'GOAT');
const CID_FIELD=(header.match(/^#define GOAT_GV_FIELD_CID\s+"(\w+)"/m)||[])[1];assert.equal(CID_FIELD,'CID');
function terminal({tester=false,chart=0n,symbol='EURUSD'}={}){
 const gv=new Map(),calls=[];
 const c={Key:KEY,GOAT_GV_FIELD_CID:CID_FIELD,MQL_TESTER:1,MQLInfoInteger:k=>(k===1&&tester)?1:0,
  StringFind:(s,t,from=0)=>s.indexOf(t,from),StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringGetCharacter:(s,i)=>s.charCodeAt(i),IntegerToString:v=>String(v),StringFormat:(f,v)=>{assert.equal(f,'%I64d');return String(v);},
  StringToInteger:s=>{const m=String(s).match(/^\s*-?\d+/);if(!m)return 0;const b=BigInt(m[0]);return b>=-(2n**53n)&&b<=2n**53n?Number(b):b;},
  GlobalVariablesTotal:()=>gv.size,GlobalVariableName:i=>[...gv.keys()][i],GlobalVariableGet:k=>gv.get(k)??0,
  Symbol:()=>symbol,ChartID:()=>chart,MAGIC1:0,
  MathRand:()=>{calls.push('MathRand');return 27416;},ChartWindowsHandle:()=>{calls.push('ChartWindowsHandle');return 0;},
  GetTickCount:()=>{calls.push('GetTickCount');return 0;}};
 vm.createContext(c);vm.runInContext(code,c);
 // What OnInit writes right after the block: GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_CID),GoatTruncateCidValue(ChartID())).
 const record=(magic,sym,cid)=>gv.set(KEY+'_ID_'+magic+'_'+sym+'_'+CID_FIELD,Number(c.GoatTruncateCidValue(cid)));
 const onInit=()=>{c.MAGIC1=0;vm.runInContext('(function(){'+js(BLOCK)+'})()',c);return c.MAGIC1;};
 return {c,gv,calls,record,onInit};
}
// Realistic MT5 chart ids (18 digits, beyond 2^53: kept as BigInt so no digit is lost), from a fixed seed.
let seed=0x2026_1012n;
const nextId=()=>{seed=(seed*6364136223846793005n+1442695040888963407n)&((1n<<64n)-1n);return 128000000000000000n+(seed%(10n**17n));};

// 1. Determinism and range: same chart id -> same magic, always a positive 31-bit int, never 0.
{const t=terminal(),other=terminal(),ids=Array.from({length:5000},nextId).concat([71300508715022n,71300456826655n,1n,9007199254740993n]);
 for(const id of ids){
  const m=t.c.GoatDeriveChildMagic(id);
  assert.ok(Number.isInteger(m)&&m>0&&m<=2147483647,'positive int magic for '+id);
  assert.equal(t.c.GoatDeriveChildMagic(id),m,'same chart id, same magic');
  assert.equal(other.c.GoatDeriveChildMagic(id),m,'same magic on another terminal, at another time');
 }
 for(let n=0;n<50;n++)for(const id of ids.slice(0,40)){const v=t.c.GoatChildMagicCandidate(id,n);assert.ok(v>=0&&v<2147483647);}
 ok();}

// 2. The 2026-10-12 cold start: 36 charts start in the same tick with ChartWindowsHandle(0)=0. Whether every
// chart derives before any CID record exists (fully simultaneous) or each writes its record before the next
// derives, all 36 magics differ. No clock, handle or random source is read.
{const ids=Array.from({length:36},(_,i)=>i===25?71300508715022n:(i===7?71300456826655n:71300400000000n+BigInt(i)));
 const together=terminal(),magics=ids.map(id=>together.c.GoatDeriveChildMagic(id));
 assert.equal(new Set(magics).size,36,'simultaneous cold start: 36 distinct magics');
 assert.deepEqual(together.calls,[],'no MathRand, ChartWindowsHandle or GetTickCount');
 const serial=terminal(),got=[];
 for(const [i,id] of ids.entries()){const m=serial.c.GoatDeriveChildMagic(id);got.push(m);serial.record(m,'S'+i,id);}
 assert.equal(new Set(got).size,36);assert.deepEqual(got,magics,'records of other charts change nothing when nothing collides');
 assert.ok(!magics.includes(27425));ok();}

// 3. A natural collision: two different chart ids whose first candidates are equal. The second chart, started
// after the first has written its CID record, steps on to its next candidate; started first, it keeps its own.
{const byMagic=new Map();let pair=null;const t=terminal();
 for(let i=0;i<600000&&!pair;i++){const id=nextId(),m=t.c.GoatChildMagicCandidate(id,0);
  if(m>0&&byMagic.has(m)&&byMagic.get(m)!==id)pair=[byMagic.get(m),id,m];else byMagic.set(m,id);}
 assert.ok(pair,'a colliding pair of chart ids exists in the search');
 const [a,b,m]=pair;
 assert.notEqual(a,b);assert.equal(t.c.GoatChildMagicCandidate(a,0),t.c.GoatChildMagicCandidate(b,0));
 const s=terminal();s.record(s.c.GoatDeriveChildMagic(a),'EURAUD',a);
 const mb=s.c.GoatDeriveChildMagic(b);
 assert.notEqual(mb,m,'the held magic is never reused by another chart');assert.equal(mb,s.c.GoatChildMagicCandidate(b,1),'deterministic re-derivation');
 s.record(mb,'USDJPY',b);
 assert.equal(s.c.GoatDeriveChildMagic(a),m,'the first chart still derives its own magic (its own record does not block it)');
 // The record may name any symbol: the magic is held terminal-wide.
 const x=terminal();x.record(m,'XAUUSD',a);assert.equal(x.c.GoatDeriveChildMagic(b),x.c.GoatChildMagicCandidate(b,1));
 console.log('  collision pair: '+a+' / '+b+' -> '+m+' ; second chart re-derived to '+mb);ok();}

// 4. Planted records: every held candidate is skipped in order; a record of this same chart (another symbol,
// e.g. after a symbol switch) does not block it; a record with a zeroed CID still counts as held.
{const id=71300508715022n,t=terminal();const c0=t.c.GoatChildMagicCandidate(id,0),c1=t.c.GoatChildMagicCandidate(id,1),c2=t.c.GoatChildMagicCandidate(id,2);
 assert.equal(new Set([c0,c1,c2]).size,3);
 assert.equal(t.c.GoatDeriveChildMagic(id),c0);
 t.record(c0,'EURAUD',71300456826655n);assert.equal(t.c.GoatDeriveChildMagic(id),c1,'held by another chart: next candidate');
 t.record(c1,'NDX',71300400000019n);assert.equal(t.c.GoatDeriveChildMagic(id),c2,'and the next');
 const own=terminal();own.record(c0,'GBPUSD',id);assert.equal(own.c.GoatDeriveChildMagic(id),c0,'its own record does not block it');
 const zero=terminal();zero.gv.set(KEY+'_ID_'+c0+'_EURAUD_'+CID_FIELD,0);assert.equal(zero.c.GoatDeriveChildMagic(id),c1,'a zeroed CID record still holds its magic');
 // Other fields and other keys never hold a magic.
 const other=terminal();other.gv.set(KEY+'_ID_'+c0+'_EURAUD_HB',5);other.gv.set('KID_ID_'+c0+'_EURAUD_CID',5);other.gv.set(KEY+'_SYM_EURAUD_CID',5);
 assert.equal(other.c.GoatDeriveChildMagic(id),c0);ok();}

// 5. The OnInit block: a restored magic wins unchanged; otherwise a live chart derives; the tester keeps its
// per-run random magic (the export CSV temp name carries MAGIC1).
{const id=71300508715022n;
 const live=terminal({chart:id,symbol:'USDJPY'});live.record(27425,'USDJPY',id);live.record(27425,'EURAUD',71300456826655n);
 assert.equal(live.onInit(),27425,'restored from the chart\'s own CID record, even a shared one (no silent re-key of a live child)');
 assert.deepEqual(live.calls,[],'a restore reads no random source');
 const fresh=terminal({chart:id,symbol:'USDJPY'});
 assert.equal(fresh.onInit(),fresh.c.GoatDeriveChildMagic(id),'a new live chart derives its magic');assert.deepEqual(fresh.calls,[],'no MathRand or ChartWindowsHandle for MAGIC1');
 const moved=terminal({chart:id,symbol:'USDJPY'});moved.record(4242,'EURUSD',id);
 assert.equal(moved.onInit(),moved.c.GoatDeriveChildMagic(id),'a record under another symbol is not a restore (unchanged GoatFindMagicByCid)');
 const tester=terminal({tester:true,chart:0n});
 assert.equal(tester.onInit(),27416+9,'tester: MathRand()+9+ChartWindowsHandle(0), as before');assert.deepEqual(tester.calls,['MathRand','ChartWindowsHandle']);
 const restoredTester=terminal({tester:true,chart:id,symbol:'USDJPY'});restoredTester.record(31337,'USDJPY',id);assert.equal(restoredTester.onInit(),31337);
 ok();}

// 6. Source pins: the derivation path reads no clock, window handle or random source; the block order is
// restore, derive (live only), legacy fallback (tester only, since derive never returns 0), then MAGIC2.
{for(const [name,body] of [['GoatChildMagicCandidate',CANDIDATE],['GoatChildMagicHeld',HELD],['GoatDeriveChildMagic',DERIVE]])
  for(const banned of ['ChartWindowsHandle','GetTickCount','MathRand','MathSrand','TimeLocal','TimeCurrent','TimeGMT','GetMicrosecondCount','TerminalInfo'])
   assert.ok(!body.includes(banned),name+' must not read '+banned);
 const lines=BLOCK.split('\n').map(l=>l.trim()).filter(l=>l&&!l.startsWith('//'));
 assert.deepEqual(lines,['long restored_magic=0;','bool restored_magic_found=GoatFindMagicByCid(Symbol(),ChartID(),restored_magic);','if(restored_magic_found)',
  'MAGIC1=(int)restored_magic;','if(MAGIC1==0 && !MQLInfoInteger(MQL_TESTER)) MAGIC1 = GoatDeriveChildMagic(ChartID());','if(MAGIC1==0) MAGIC1 = MathRand()+9+ChartWindowsHandle(0);']);
 assert.equal((main.match(/GoatDeriveChildMagic\(/g)||[]).length,2,'defined once, called once (OnInit)');
 assert.equal((main.replace(/\/\/.*$/gm,'').match(/MathRand\(\)\+9\+ChartWindowsHandle\(0\)/g)||[]).length,2,'only the tester MAGIC1 fallback and the unused MAGIC2 keep the random seed');
 // MAGIC1 is an internal global, not an input: no SET changes. The input header is byte-identical to the
 // pinned controller contract (B43), so no input, default or enum changed.
 assert.match(header,/^int\s+MAGIC1=0,MAGIC2=0,LicenseKey=0;$/m);
 for(const text of [main,header])assert.ok(!/^\s*s?input\b[^\n]*\bMAGIC[12]\b/m.test(text),'MAGIC1/2 are not inputs');
 const sha=crypto.createHash('sha256').update(fs.readFileSync(path.join(ROOT,'GOAT_Inputs_Definitions.mqh'))).digest('hex');
 const deps=JSON.parse(fs.readFileSync(path.join(ROOT,'controller/contracts/v149/dependencies.json'),'utf8').replace(/^\uFEFF/,''));
 assert.equal(sha,deps.header_sha256,'GOAT_Inputs_Definitions.mqh is unchanged (input contract pin)');
 ok();}

// 7. GlobalVariable names stay within MT5's 63 characters with a 10-digit magic and a 12-character symbol,
// for every per-child field the EA and the dashboard write.
{const fields=new Set([...header.matchAll(/^#define GOAT_GV_FIELD_\w+\s+"(\w+)"/gm)].map(m=>m[1]));
 for(const f of ['GOAT V1.49.mq5','GOATPortfolioSetupControl.mqh','Dashboard.mqh'])
  for(const m of read(f).matchAll(/GoatChildGVName\([^,()]+,[^,()]+(?:\(\))?,"(\w+)"\)/g))fields.add(m[1]);
 assert.ok(fields.has('EA_TRADE_ALLOWED')&&fields.has('PEMODE')&&fields.size>25);
 for(const f of fields){const name=KEY+'_ID_2147483646_ABCDEFGHIJKL_'+f;assert.ok(name.length<=63,name+' is '+name.length+' characters');}
 ok();}

console.log(JSON.stringify({passed,test:'child_magic_unique',productionFunctions:['GoatChildMagicCandidate','GoatChildMagicHeld','GoatDeriveChildMagic','GoatParseChildGVName','GoatTruncateCidValue','GoatFindMagicByCid','OnInit magic block']}));
