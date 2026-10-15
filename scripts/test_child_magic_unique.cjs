// B44: a new child's magic is unique by construction (Exp 03, 2026-10-12, goatai#2350). 36 charts cold-started
// together on the experiment VPS; ChartWindowsHandle(0) returned 0 under load (MT5 error 4102) and two children
// seeded in the same GetTickCount tick drew the same MathRand()+9+ChartWindowsHandle(0) = 27425, so the dashboard
// refused the second one on every launch. GOAT V1.49.mq5 now derives a new live magic from the chart id
// (GoatChildMagicCandidate / GoatChildMagicHeld / GoatDeriveChildMagic) and steps on while another chart's CID
// record holds the value. This runs the production functions (and the real GoatParseChildGVName,
// GoatTruncateCidValue and GoatFindMagicByCid from the input header) after a syntax-only MQL-to-JS conversion
// against a modelled GlobalVariable store, then runs the OnInit magic block itself. Source semantics only: native
// MT5 chart ids and GlobalVariables are not exercised here.
// B45 (GOAT-EA#227 review item 4): a saved profile carries fixed chart ids, so two terminals on one login loaded from
// the same profile drew the same magic. The candidate now hashes "<n>#<chart id>#<salt>", the salt being the account
// login and a hash of the terminal's data path (GoatChildMagicSalt). Section 8 runs two terminals on one login from
// one profile, and the upgrade path: a chart with a CID record (B43 random or B44 unsalted) restores its magic.
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
const SALT=bodyOf(main,'string GoatChildMagicSalt(void)');
const CANDIDATE=bodyOf(main,'int GoatChildMagicCandidate(const long magic_chart,const int magic_n,const string magic_salt)');
const HELD=bodyOf(main,'bool GoatChildMagicHeld(const int magic_value,const long magic_chart)');
const DERIVE=bodyOf(main,'int GoatDeriveChildMagic(const long magic_chart,const string magic_salt)');
const once=(text,from,to,label)=>{assert.equal(text.split(from).length,2,'exactly one '+label);return text.replace(from,()=>to);};
const code=
 // GoatParseChildGVName's outputs are written just before its final return.
 'function GoatParseChildGVName(gv_name,__m,__s,__f){let magic=0,symbol="",field="";'
  +js(once(PARSE,'return(symbol!="" && field!="");','__m(magic);__s(symbol);__f(field);return(symbol!="" && field!="");','parse return'))+'}\n'
 +'function GoatFindMagicByCid(symbol,chart_id,__out){let magic_out=0;'+js(FIND).replace(/\bmagic_out=([^;]+);/g,'__out(magic_out=$1);')+'}\n'
 +fn(TRUNC,'GoatTruncateCidValue',['cid'],TRUNC)
 +fn(SALT,'GoatChildMagicSalt',[],SALT)
 +fn(CANDIDATE,'GoatChildMagicCandidate',['magic_chart','magic_n','magic_salt'],CANDIDATE)
 +fn(HELD,'GoatChildMagicHeld',['magic_value','magic_chart'],HELD)
 +fn(DERIVE,'GoatDeriveChildMagic',['magic_chart','magic_salt'],DERIVE);
// OnInit's magic block, from the restore to the policy-pause read (the CID record write follows it unchanged).
const BLOCK=region(main,'    long restored_magic=0;\n','     if(GlobalVariableCheck(GoatPortfolioGVName("DashboardPolicyPaused")))');

// A modelled terminal: GlobalVariables in creation order (MT5 lists them by name; the scan order does not matter).
const KEY=(header.match(/^#define\s+Key\s+"(\w+)"/m)||[])[1];assert.equal(KEY,'GOAT');
const CID_FIELD=(header.match(/^#define GOAT_GV_FIELD_CID\s+"(\w+)"/m)||[])[1];assert.equal(CID_FIELD,'CID');
// B45: each terminal has its data path and its account login (the salt's inputs). Defaults: one terminal, one demo.
const DATA_PATH='C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\D0E8209F77C8CF37AD8BF550E51FF075';
function terminal({tester=false,chart=0n,symbol='EURUSD',login=3000107825,dataPath=DATA_PATH}={}){
 const gv=new Map(),calls=[],reads=[];
 const c={Key:KEY,GOAT_GV_FIELD_CID:CID_FIELD,MQL_TESTER:1,MQLInfoInteger:k=>(k===1&&tester)?1:0,
  ACCOUNT_LOGIN:7,TERMINAL_DATA_PATH:8,
  AccountInfoInteger:k=>{assert.equal(k,7);reads.push('login');return login;},
  TerminalInfoString:k=>{assert.equal(k,8);reads.push('data_path');return dataPath;},
  StringFind:(s,t,from=0)=>s.indexOf(t,from),StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
  StringGetCharacter:(s,i)=>s.charCodeAt(i),IntegerToString:v=>String(v),StringFormat:(f,v)=>{assert.equal(f,'%I64d');return String(v);},
  StringToInteger:s=>{const m=String(s).match(/^\s*-?\d+/);if(!m)return 0;const b=BigInt(m[0]);return b>=-(2n**53n)&&b<=2n**53n?Number(b):b;},
  GlobalVariablesTotal:()=>gv.size,GlobalVariableName:i=>[...gv.keys()][i],GlobalVariableGet:k=>gv.get(k)??0,
  Symbol:()=>symbol,ChartID:()=>chart,MAGIC1:0,
  MathRand:()=>{calls.push('MathRand');return 27416;},ChartWindowsHandle:()=>{calls.push('ChartWindowsHandle');return 0;},
  GetTickCount:()=>{calls.push('GetTickCount');return 0;},
  // B44 condition 3: the account's open positions and pending orders (magics), selected by index.
  positions:[],orders:[],POSITION_MAGIC:1,ORDER_MAGIC:2,PositionsTotal:()=>c.positions.length,OrdersTotal:()=>c.orders.length,
  PositionGetTicket:i=>{c.sel=c.positions[i];return 1000+i;},PositionGetInteger:k=>{assert.equal(k,1);return c.sel;},
  OrderGetTicket:i=>{c.selo=c.orders[i];return 2000+i;},OrderGetInteger:k=>{assert.equal(k,2);return c.selo;}};
 vm.createContext(c);vm.runInContext(code,c);
 // The salted calls OnInit makes: GoatDeriveChildMagic(ChartID(),GoatChildMagicSalt()).
 c.derive=id=>c.GoatDeriveChildMagic(id,c.GoatChildMagicSalt());c.cand=(id,n)=>c.GoatChildMagicCandidate(id,n,c.GoatChildMagicSalt());
 // What OnInit writes right after the block: GlobalVariableSet(GoatChildGVName(MAGIC1,Symbol(),GOAT_GV_FIELD_CID),GoatTruncateCidValue(ChartID())).
 const record=(magic,sym,cid)=>gv.set(KEY+'_ID_'+magic+'_'+sym+'_'+CID_FIELD,Number(c.GoatTruncateCidValue(cid)));
 const onInit=()=>{c.MAGIC1=0;vm.runInContext('(function(){'+js(BLOCK)+'})()',c);return c.MAGIC1;};
 return {c,gv,calls,reads,record,onInit};
}
// Realistic MT5 chart ids (18 digits, beyond 2^53: kept as BigInt so no digit is lost), from a fixed seed.
let seed=0x2026_1012n;
const nextId=()=>{seed=(seed*6364136223846793005n+1442695040888963407n)&((1n<<64n)-1n);return 128000000000000000n+(seed%(10n**17n));};

// 1. Determinism and range: same chart id on the same terminal and login -> same magic, always a positive 31-bit
// int, never 0. B45: the same chart id on another terminal (data path) or another login draws another magic.
{const t=terminal(),again=terminal(),otherPath=terminal({dataPath:DATA_PATH.replace('D0E8','D0E9')}),otherLogin=terminal({login:3000107826});
 const ids=Array.from({length:5000},nextId).concat([71300508715022n,71300456826655n,1n,9007199254740993n]);
 let samePath=0,sameLogin=0;
 for(const id of ids){
  const m=t.c.derive(id);
  assert.ok(Number.isInteger(m)&&m>0&&m<=2147483647,'positive int magic for '+id);
  assert.equal(t.c.derive(id),m,'same chart id, same magic');
  assert.equal(again.c.derive(id),m,'same magic on the same terminal and login, at another time');
  if(otherPath.c.derive(id)===m)samePath++;if(otherLogin.c.derive(id)===m)sameLogin++;
 }
 assert.equal(samePath,0,'another terminal data path: no chart id draws the same magic');assert.equal(sameLogin,0,'another login: none either');
 for(let n=0;n<50;n++)for(const id of ids.slice(0,40)){const v=t.c.cand(id,n);assert.ok(v>=0&&v<2147483647);}
 ok();}

// 2. The 2026-10-12 cold start: 36 charts start in the same tick with ChartWindowsHandle(0)=0. Whether every
// chart derives before any CID record exists (fully simultaneous) or each writes its record before the next
// derives, all 36 magics differ. No clock, handle or random source is read.
{const ids=Array.from({length:36},(_,i)=>i===25?71300508715022n:(i===7?71300456826655n:71300400000000n+BigInt(i)));
 const together=terminal(),magics=ids.map(id=>together.c.derive(id));
 assert.equal(new Set(magics).size,36,'simultaneous cold start: 36 distinct magics');
 assert.deepEqual(together.calls,[],'no MathRand, ChartWindowsHandle or GetTickCount');
 const serial=terminal(),got=[];
 for(const [i,id] of ids.entries()){const m=serial.c.derive(id);got.push(m);serial.record(m,'S'+i,id);}
 assert.equal(new Set(got).size,36);assert.deepEqual(got,magics,'records of other charts change nothing when nothing collides');
 assert.ok(!magics.includes(27425));ok();}

// 3. A natural collision: two different chart ids whose first candidates are equal. The second chart, started
// after the first has written its CID record, steps on to its next candidate; started first, it keeps its own.
{const byMagic=new Map();let pair=null;const t=terminal();
 for(let i=0;i<600000&&!pair;i++){const id=nextId(),m=t.c.cand(id,0);
  if(m>0&&byMagic.has(m)&&byMagic.get(m)!==id)pair=[byMagic.get(m),id,m];else byMagic.set(m,id);}
 assert.ok(pair,'a colliding pair of chart ids exists in the search');
 const [a,b,m]=pair;
 assert.notEqual(a,b);assert.equal(t.c.cand(a,0),t.c.cand(b,0));
 const s=terminal();s.record(s.c.derive(a),'EURAUD',a);
 const mb=s.c.derive(b);
 assert.notEqual(mb,m,'the held magic is never reused by another chart');assert.equal(mb,s.c.cand(b,1),'deterministic re-derivation');
 s.record(mb,'USDJPY',b);
 assert.equal(s.c.derive(a),m,'the first chart still derives its own magic (its own record does not block it)');
 // The record may name any symbol: the magic is held terminal-wide.
 const x=terminal();x.record(m,'XAUUSD',a);assert.equal(x.c.derive(b),x.c.cand(b,1));
 console.log('  collision pair: '+a+' / '+b+' -> '+m+' ; second chart re-derived to '+mb);ok();}

// 4. Planted records: every held candidate is skipped in order; a record of this same chart (another symbol,
// e.g. after a symbol switch) does not block it; a record with a zeroed CID still counts as held.
{const id=71300508715022n,t=terminal();const c0=t.c.cand(id,0),c1=t.c.cand(id,1),c2=t.c.cand(id,2);
 assert.equal(new Set([c0,c1,c2]).size,3);
 assert.equal(t.c.derive(id),c0);
 t.record(c0,'EURAUD',71300456826655n);assert.equal(t.c.derive(id),c1,'held by another chart: next candidate');
 t.record(c1,'NDX',71300400000019n);assert.equal(t.c.derive(id),c2,'and the next');
 const own=terminal();own.record(c0,'GBPUSD',id);assert.equal(own.c.derive(id),c0,'its own record does not block it');
 const zero=terminal();zero.gv.set(KEY+'_ID_'+c0+'_EURAUD_'+CID_FIELD,0);assert.equal(zero.c.derive(id),c1,'a zeroed CID record still holds its magic');
 // Other fields and other keys never hold a magic.
 const other=terminal();other.gv.set(KEY+'_ID_'+c0+'_EURAUD_HB',5);other.gv.set('KID_ID_'+c0+'_EURAUD_CID',5);other.gv.set(KEY+'_SYM_EURAUD_CID',5);
 assert.equal(other.c.derive(id),c0);ok();}

// 4b. B44 condition 3 (goatai#2350 6127809765): a magic an open position or pending order carries is held, even with
// no CID record (a chart closed with its trades left open). An open position on candidate n=0 steps to n=1.
{const id=71300508715022n,t=terminal();const c0=t.c.cand(id,0),c1=t.c.cand(id,1),c2=t.c.cand(id,2);
 t.c.positions=[12345,c0];assert.equal(t.c.derive(id),c1,'an open position on candidate 0 steps to candidate 1');
 const o=terminal();o.c.orders=[c0];assert.equal(o.c.derive(id),c1,'a pending order holds it too');
 const both=terminal();both.c.positions=[c0];both.record(c1,'EURAUD',71300456826655n);assert.equal(both.c.derive(id),c2,'position, then a CID record');
 const free=terminal();free.c.positions=[c0+1];free.c.orders=[0];assert.equal(free.c.derive(id),c0,'other magics hold nothing');
 // The OnInit block: a restored magic still wins even when its own position is open (no re-key of a live child).
 const live=terminal({chart:id,symbol:'USDJPY'});live.record(c0,'USDJPY',id);live.c.positions=[c0];assert.equal(live.onInit(),c0);
 ok();}

// 5. The OnInit block: a restored magic wins unchanged; otherwise a live chart derives; the tester keeps its
// per-run random magic (the export CSV temp name carries MAGIC1).
{const id=71300508715022n;
 const live=terminal({chart:id,symbol:'USDJPY'});live.record(27425,'USDJPY',id);live.record(27425,'EURAUD',71300456826655n);
 assert.equal(live.onInit(),27425,'restored from the chart\'s own CID record, even a shared one (no silent re-key of a live child)');
 assert.deepEqual(live.calls,[],'a restore reads no random source');
 const fresh=terminal({chart:id,symbol:'USDJPY'});
 assert.equal(fresh.onInit(),fresh.c.derive(id),'a new live chart derives its magic');assert.deepEqual(fresh.calls,[],'no MathRand or ChartWindowsHandle for MAGIC1');
 const moved=terminal({chart:id,symbol:'USDJPY'});moved.record(4242,'EURUSD',id);
 assert.equal(moved.onInit(),moved.c.derive(id),'a record under another symbol is not a restore (unchanged GoatFindMagicByCid)');
 const tester=terminal({tester:true,chart:0n});
 assert.equal(tester.onInit(),27416+9,'tester: MathRand()+9, its per-run random magic (B44 item 10: no window handle)');assert.deepEqual(tester.calls,['MathRand']);
 const restoredTester=terminal({tester:true,chart:id,symbol:'USDJPY'});restoredTester.record(31337,'USDJPY',id);assert.equal(restoredTester.onInit(),31337);
 ok();}

// 6. Source pins: the derivation path reads no clock, window handle or random source; the block order is
// restore, derive (live only), the tester fallback (tester only, since derive never returns 0); no window handle.
{for(const [name,body] of [['GoatChildMagicCandidate',CANDIDATE],['GoatChildMagicHeld',HELD],['GoatDeriveChildMagic',DERIVE]])
  for(const banned of ['ChartWindowsHandle','GetTickCount','MathRand','MathSrand','TimeLocal','TimeCurrent','TimeGMT','GetMicrosecondCount','TerminalInfo'])
   assert.ok(!body.includes(banned),name+' must not read '+banned);
 // B45: the salt reads the login and the data path only: no clock, handle or random source.
 for(const banned of ['ChartWindowsHandle','GetTickCount','MathRand','MathSrand','TimeLocal','TimeCurrent','TimeGMT','GetMicrosecondCount','ChartID'])
  assert.ok(!SALT.includes(banned),'GoatChildMagicSalt must not read '+banned);
 assert.deepEqual([...SALT.matchAll(/\b(AccountInfo\w+|TerminalInfo\w+)\(([A-Z_]+)\)/g)].map(m=>m[1]+'('+m[2]+')').sort(),
  ['AccountInfoInteger(ACCOUNT_LOGIN)','TerminalInfoString(TERMINAL_DATA_PATH)']);
 const lines=BLOCK.split('\n').map(l=>l.trim()).filter(l=>l&&!l.startsWith('//'));
 assert.deepEqual(lines,['long restored_magic=0;','bool restored_magic_found=GoatFindMagicByCid(Symbol(),ChartID(),restored_magic);','if(restored_magic_found)',
  'MAGIC1=(int)restored_magic;','if(MAGIC1==0 && !MQLInfoInteger(MQL_TESTER)) MAGIC1 = GoatDeriveChildMagic(ChartID(),GoatChildMagicSalt());','if(MAGIC1==0) MAGIC1 = MathRand()+9;']);
 assert.equal((main.match(/GoatDeriveChildMagic\(/g)||[]).length,2,'defined once, called once (OnInit)');
 // B46: the CID guard reads the salt too, as the terminal's identity in its claim files (test_cid_guard.cjs).
 assert.equal((main.match(/GoatChildMagicSalt\(/g)||[]).length,3,'the salt: defined once, called in OnInit and by GoatCidGuardEvaluate');
 assert.match(main,/^   string cidg_terminal=GoatChildMagicSalt\(\);$/m);
 // B44 item 10: no ChartWindowsHandle read is left in the entrypoint, and the unused MAGIC2 is no longer seeded.
 assert.equal((main.replace(/\/\/.*$/gm,'').match(/ChartWindowsHandle\s*\(|CHART_WINDOW_HANDLE/g)||[]).length,0,'no window-handle read in the entrypoint');
 assert.ok(!/MAGIC2\s*=/.test(main.replace(/\/\/.*$/gm,'')),'MAGIC2 is never assigned');
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

// 8. B45 (GOAT-EA#227 review item 4): two terminals on one login, both loaded from one saved profile (the same 36
// fixed chart ids, studio_deploy_profile.py saved_profile_links reads them from each chart's id=), cold-start together
// before either has traded. Each terminal's CID records are its own and no position exists yet, so only the salt
// can keep them apart: no magic is drawn by both. Without the salt (B44) every one of them collided.
{const ids=Array.from({length:36},(_,i)=>71300400000000n+BigInt(i*7919));
 const a=terminal(),b=terminal({dataPath:'C:\\Program Files\\GOAT Terminal 2\\MQL5\\..'});
 const ma=ids.map(id=>a.c.derive(id)),mb=ids.map(id=>b.c.derive(id));
 assert.equal(new Set(ma).size,36);assert.equal(new Set(mb).size,36);
 assert.deepEqual(ma.filter(m=>mb.includes(m)),[],'two terminals on one login, one profile: no shared magic');
 // Same-terminal ownership stays fail-closed: a record or an open position on this terminal still steps the candidate on.
 const id=ids[0],c0=a.c.cand(id,0),c1=a.c.cand(id,1);
 const held=terminal();held.record(c0,'EURAUD',ids[1]);assert.equal(held.c.derive(id),c1,'another chart\'s CID record on this terminal');
 const pos=terminal();pos.c.positions=[c0];assert.equal(pos.c.derive(id),c1,'an open position of this login (whichever terminal opened it)');
 // A login that is not known yet (cold start before the account connects) still separates two terminals.
 const a0=terminal({login:0}),b0=terminal({login:0,dataPath:'D:\\MT5\\T3'});
 assert.deepEqual(ids.map(i=>a0.c.derive(i)).filter(m=>ids.map(i=>b0.c.derive(i)).includes(m)),[],'login 0: the data path still separates them');
 assert.deepEqual(a.reads.slice(0,2),['data_path','login'],'the salt reads the data path and the login');
 ok();}

// 9. B45 upgrade: a running child keeps its magic and so its open positions. OnInit restores a chart's magic from its
// own CID record before any derivation runs, so a B43 random magic or a B44 unsalted one comes back unchanged, positions
// open or not. A chart whose CID record is gone never re-adopted positions by derivation (B44 condition 3 already holds
// any magic an open position carries), and with the salt it still cannot take a magic an open position carries.
{const id=71300508715022n,b44=(()=>{const s='0#'+id;let h=0;for(let k=0;k<s.length;k++)h=(h*48271+s.charCodeAt(k))%2147483647;return h;})();
 for(const old of [27425,b44]){
  const t=terminal({chart:id,symbol:'USDJPY'});t.record(old,'USDJPY',id);t.c.positions=[old];t.c.orders=[old];
  assert.equal(t.onInit(),old,'restored unchanged: '+old);
 }
 const lost=terminal({chart:id,symbol:'USDJPY'});const s0=lost.c.cand(id,0),s1=lost.c.cand(id,1);lost.c.positions=[b44,s0];
 const got=lost.onInit();assert.ok(![b44,s0].includes(got),'no CID record: a magic an open position carries is never drawn');
 assert.equal(got,s1);ok();}

console.log(JSON.stringify({passed,test:'child_magic_unique',productionFunctions:['GoatChildMagicCandidate','GoatChildMagicHeld','GoatDeriveChildMagic','GoatParseChildGVName','GoatTruncateCidValue','GoatFindMagicByCid','OnInit magic block']}));
