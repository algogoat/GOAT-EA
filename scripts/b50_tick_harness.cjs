// B50 tick harness (B50-alpha A0 scaffold, docs/b50/B50_ALPHA_DESIGN.md section 4). A library, not a test: the B50
// tests load it (test_b50_parity.cjs here; A1-A3's flags-on tests).
//
// It converts real MQL5 to JavaScript and runs it against a modelled terminal, as test_restart_adopt.cjs does for a
// few methods, but for the whole OnTick path of a given source (the working tree, a git revision, or overridden text):
// - the entrypoint with the input header (and GOAT_NYClock.mqh when it exists) inlined at their #include, after the
//   preprocessor (object-like #define macros expanded, #ifdef/#ifndef/#else/#endif honoured);
// - converted: GoatTickBody, GoatTradeTransactionBody, WriteSet, SignalEntryTrigger, UpdateCurrentSignals, UpdateRSI,
//   GetSize, OpenPosition, CloseAllPositions and every free function they reach, every B50 function (GoatSingle*,
//   GoatSignalAll, GoatNY*), every class (SEQUENCE with TRADELEVEL, INTERVAL, BUF) and every global with its initializer,
//   plus OnInit's own slices for a fixture (the session table, the sizes, Buy_EN/Sell_EN, and the lot chain through the
//   indicator handles, B50's block included). MOCKS models what never sends, modifies or closes an order: chart objects
//   and the panel, tracing, performance counters, the direction guard and CID guard (both allow), the dashboard bus;
// - the converter is syntax-level: declarations become let (statics persist per function, shared across instances as in
//   MQL), casts become helpers, scalar reference parameters become boxes, class members become this.<member>. MQL integer
//   division and integer overflow are NOT modelled (every comparison runs both sides through the same converter);
// - the terminal: one hedging account and one symbol (EURUSD, 5 digits, 1 USD per point per lot, normalized quotes),
//   positions and deals (OrderSend fills at the requested price; PositionModify, PositionClose and PositionClosePartial
//   act at once; a position whose SL or TP the price reaches is filled by the "broker" before the tick), indicator
//   buffers by handle name (ATR, ATR_MA, RSI, MA0.., ADX, BB, MACD) and series from the fixture, GlobalVariables, the
//   clock (TimeGMT is the server time in the tester, server - serverOffset h live), and the trade transaction pumped once
//   per deal after the tick (as MT5 runs OnTradeTransaction after OnTick). Every OrderSend, PositionModify, close and
//   broker fill lands in world.trace, in order.
// API: build(source, fixture) -> {ctx, w, tick(t,bid,ask), run([[t,bid,ask?],..]), setInput(name,value), pump};
//   source: undefined (the tree), a revision ('65fde12'), or {files} from loadSources(ref, {file: text}).
//   fixture: {inputs:{name: value or enum label}, tester, optimization, fastSpeed, magic, start, bid, spread,
//   indicator(name,buffer,shift,w), series(tf,shift,barTime,w), news(time,w), bias(time,w), adopt(ctx,w), world:{...}}.
//   An OnInit refusal throws (error.initCode). ctx is the MQL global scope (inputs, globals, functions, Seq_Buy...).
// What it does not prove: compile cleanliness, MT5's fills, slippage or tick order. The native Banker parity does.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..');
const MAIN='GOAT V1.49.mq5',HEADER='GOAT_Inputs_Definitions.mqh';
const INLINED=[HEADER,'GOAT_NYClock.mqh'];   // inlined at their #include; every other include is modelled (MOCKS, EXTERNS)

// ---------------------------------------------------------------------------------------------------------------
// Sources
function readSource(ref,file){
 let raw;
 if(ref===undefined||ref===null){
  const p=file===MAIN&&process.env.GOAT_EA_MAIN?process.env.GOAT_EA_MAIN:path.join(ROOT,file);
  if(!fs.existsSync(p)) return null;
  raw=fs.readFileSync(p,'utf8');
 }
 else{
  try{raw=execFileSync('git',['show',ref+':'+file],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8');}
  catch{return null;}
 }
 return raw.replace(/^﻿/,'').replace(/\r\n/g,'\n');
}
// ref: undefined = the working tree (GOAT_EA_MAIN may point at a mutated entrypoint), else a git revision.
// overrides: {file: text} replaces a file's text (mutation tests).
function loadSources(ref,overrides={}){
 const files={};
 for(const f of [MAIN,...INLINED]){const t=overrides[f]!==undefined?overrides[f]:readSource(ref,f);if(t!==null)files[f]=t;}
 if(!files[MAIN]||!files[HEADER]) throw new Error('missing source at '+(ref||'the working tree'));
 return files;
}

// ---------------------------------------------------------------------------------------------------------------
// Preprocessor: inline the INLINED includes, honour conditionals, collect object-like macros.
function preprocess(files){
 const macros=new Map(),out=[];const stack=[];let active=true;
 function run(text,name){
  for(const line of text.split('\n')){
   const d=line.match(/^\s*#\s*(\w+)\s*(.*)$/);
   if(!d){out.push(active?line:'');continue;}
   const [,op,rest]=d;out.push('');
   if(op==='ifdef'||op==='ifndef'){let br=macros.has(rest.trim().split(/\s|\/\//)[0]);if(op==='ifndef')br=!br;stack.push({parent:active,br,els:false});active=active&&br;continue;}
   if(op==='else'){const s=stack.at(-1);s.els=true;active=s.parent&&!s.br;continue;}
   if(op==='endif'){active=stack.pop().parent;continue;}
   if(!active) continue;
   if(op==='define'){
    const m=rest.match(/^(\w+)(\()?/);if(!m) continue;
    if(m[2]){macros.set(m[1],{fn:true});continue;}            // function-like (Alert): modelled by MOCKS
    macros.set(m[1],{body:rest.slice(m[1].length).replace(/\/\/.*$/,'').trim()});continue;
   }
   if(op==='undef'){macros.delete(rest.trim());continue;}
   if(op==='include'){
    const inc=(rest.match(/^"([^"]+)"/)||[])[1];
    if(inc&&INLINED.includes(inc)&&files[inc]!==undefined){out.push('/*@file '+inc+'*/');run(files[inc],inc);out.push('/*@file '+name+'*/');}
    continue;
   }
  }
 }
 run(files[MAIN],MAIN);
 return {text:out.join('\n'),macros};
}

// ---------------------------------------------------------------------------------------------------------------
// Tokenizer
const OPS=['<<=','>>=','==','!=','<=','>=','&&','||','++','--','+=','-=','*=','/=','%=','&=','|=','^=','<<','>>','::','->'];
function tokenize(src){
 const toks=[];let i=0;const n=src.length;
 while(i<n){
  const c=src[i];
  if(c===' '||c==='\t'||c==='\r'||c==='\n'){i++;continue;}
  if(c==='/'&&src[i+1]==='/'){const s=i;while(i<n&&src[i]!=='\n')i++;const m=src.slice(s,i).match(/^\/\/ B50:(begin|end) (\S+)/);if(m)toks.push({t:'mark',v:m[1]+':'+m[2]});continue;}
  if(c==='/'&&src[i+1]==='*'){const j=src.indexOf('*/',i+2);i=j<0?n:j+2;continue;}
  if(c==='"'){let j=i+1;while(j<n&&src[j]!=='"'){if(src[j]==='\\')j++;j++;}toks.push({t:'str',v:src.slice(i,j+1)});i=j+1;continue;}
  if(c==="'"){let j=i+1;while(j<n&&src[j]!=="'"){if(src[j]==='\\')j++;j++;}toks.push({t:'num',v:String(charCode(src.slice(i+1,j)))});i=j+1;continue;}
  if(/[A-Za-z_]/.test(c)){
   let j=i+1;while(j<n&&/\w/.test(src[j]))j++;const w=src.slice(i,j);
   if((w==='C'||w==='D')&&src[j]==="'"){let k=j+1;while(k<n&&src[k]!=="'")k++;toks.push({t:'num',v:String(w==='D'?mqlDate(src.slice(j+1,k)):0)});i=k+1;continue;}
   toks.push({t:'id',v:w});i=j;continue;
  }
  if(/[0-9]/.test(c)||(c==='.'&&/[0-9]/.test(src[i+1]||''))){
   const m=src.slice(i).match(/^(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)/);
   toks.push({t:'num',v:m[0].replace(/\.$/,'.0')});i+=m[0].length;continue;
  }
  const op=OPS.find(o=>src.startsWith(o,i));
  if(op){toks.push({t:'op',v:op});i+=op.length;continue;}
  toks.push({t:'op',v:c});i++;
 }
 // Adjacent string literals concatenate (C rule).
 const merged=[];
 for(const t of toks){if(t.t==='str'&&merged.length&&merged.at(-1).t==='str'){merged.at(-1).v=merged.at(-1).v+'+'+t.v;}else merged.push(t);}
 return merged;
}
function charCode(body){const map={n:10,r:13,t:9,'0':0,'\\':92,"'":39,'"':34};return body.length>1&&body[0]==='\\'?(map[body[1]]??body.charCodeAt(1)):body.charCodeAt(0);}
function mqlDate(text){const m=text.match(/^(\d{4})\.(\d{2})\.(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/);return m?Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0))/1000:0;}
const isId=(t,v)=>t&&t.t==='id'&&(v===undefined||t.v===v);
const isOp=(t,v)=>t&&t.t==='op'&&t.v===v;
function matchClose(toks,i){   // toks[i] is ( [ or {: the index of its partner
 const open=toks[i].v,close={'(':')','[':']','{':'}'}[open];let d=0;
 for(let j=i;j<toks.length;j++){if(isOp(toks[j],open))d++;else if(isOp(toks[j],close)){d--;if(!d)return j;}}
 throw new Error('unbalanced '+open);
}
// Object-like macro expansion (the C rule: a macro is not re-expanded inside itself).
function expandMacros(toks,macros){
 const cache=new Map();
 const body=name=>{if(!cache.has(name))cache.set(name,tokenize(macros.get(name).body));return cache.get(name);};
 const out=[];
 const emit=(t,seen)=>{
  if(t.t==='id'&&macros.has(t.v)&&!macros.get(t.v).fn&&!seen.has(t.v)){const s=new Set(seen);s.add(t.v);for(const b of body(t.v))emit({...b},s);return;}
  out.push(t);
 };
 for(let i=0;i<toks.length;i++){
  const t=toks[i];
  if(t.t==='id'&&i>0&&isOp(toks[i-1],'.')){out.push(t);continue;}   // a member name is never a macro
  emit(t,new Set());
 }
 return out;
}

// ---------------------------------------------------------------------------------------------------------------
// Top-level parse: enums, classes, functions, globals.
const KEYWORDS=new Set(['return','else','case','goto','delete','new','do','break','continue','default','if','for','while','switch','sizeof','typedef','public','private','protected','virtual','operator','this']);
const SCALAR_DEFAULTS={bool:'false',string:'""'};
function splitTop(toks,sep=','){   // split a token list at top-level separators
 const parts=[[]];let d=0;
 for(const t of toks){if(t.t==='op'&&'([{'.includes(t.v))d++;if(t.t==='op'&&')]}'.includes(t.v))d--;if(d===0&&isOp(t,sep)){parts.push([]);continue;}parts.at(-1).push(t);}
 return parts;
}
function parseParams(toks){   // toks between the parentheses of a definition
 if(!toks.length||(toks.length===1&&isId(toks[0],'void'))) return [];
 return splitTop(toks).map(p=>{
  const eq=p.findIndex(t=>isOp(t,'='));const decl=eq<0?p:p.slice(0,eq);
  const arr=decl.some(t=>isOp(t,'['));const ref=decl.some(t=>isOp(t,'&'));
  const name=[...decl].reverse().find(t=>t.t==='id').v;
  const type=decl.filter(t=>t.t==='id'&&t.v!=='const'&&t.v!==name).map(t=>t.v).join(' ');
  return {name,type,ref:ref&&!arr,arr,def:eq<0?null:p.slice(eq+1)};
 });
}
function parseUnit(toks){
 const unit={enums:new Map(),constants:new Map(),classes:new Map(),functions:new Map(),globals:[]};
 parseScope(toks,0,toks.length,unit,null);
 // A by-reference parameter becomes a box only for a scalar (a struct, class or array is already shared by reference).
 const scalar=type=>{const base=type.split(' ').pop();return SCALAR_TYPES.has(base)||unit.enums.has(base)||/^ENUM_/.test(base);};
 const fix=fn=>{for(const p of fn.params)p.ref=p.ref&&scalar(p.type);};
 for(const fns of unit.functions.values())fns.forEach(fix);
 for(const c of unit.classes.values()){for(const m of c.methods.values())fix(m);if(c.ctor)fix(c.ctor);}
 return unit;
}
function parseScope(toks,start,end,unit,cls){
 let stmt=[],i=start;
 const flush=()=>{if(stmt.length)handleStatement(stmt,unit,cls);stmt=[];};
 while(i<end){
  const t=toks[i];
  if(t.t==='mark'){i++;continue;}
  if(cls&&t.t==='id'&&['public','private','protected'].includes(t.v)&&isOp(toks[i+1],':')){i+=2;continue;}
  if(isOp(t,';')){flush();i++;continue;}
  if(isOp(t,'{')){
   const close=matchClose(toks,i);
   const first=stmt.findIndex(x=>x.t==='id'&&x.v!=='static'&&x.v!=='const');
   if(isId(stmt[first],'enum')){parseEnum(stmt[first+1].v,toks.slice(i+1,close),unit);stmt=[];i=close+1;if(isOp(toks[i],';'))i++;continue;}
   if(isId(stmt[first],'class')||isId(stmt[first],'struct')){
    const name=stmt[first+1].v,c={name,fields:[],methods:new Map(),ctor:null,parent:cls};
    unit.classes.set(name,c);parseScope(toks,i+1,close,unit,c);stmt=[];i=close+1;if(isOp(toks[i],';'))i++;continue;
   }
   // a function (or method) definition: <...> name ( params ) [const] {
   let k=stmt.length-1;if(isId(stmt[k],'const'))k--;
   if(isOp(stmt[k],')')){
    let d=0,o=k;for(;o>=0;o--){if(isOp(stmt[o],')'))d++;if(isOp(stmt[o],'(')){d--;if(!d)break;}}
    const nameTok=stmt[o-1];
    if(nameTok&&nameTok.t==='id'&&!KEYWORDS.has(nameTok.v)&&!stmt.slice(0,o).some(x=>isOp(x,'='))){
     const fn={name:nameTok.v,params:parseParams(stmt.slice(o+1,k)),body:toks.slice(i+1,close),cls:cls?cls.name:null,
      ret:stmt.slice(0,o-1).filter(x=>x.t==='id').map(x=>x.v).join(' ')};
     if(cls){if(nameTok.v===cls.name)cls.ctor=fn;else if(!isOp(stmt[o-2],'~'))cls.methods.set(fn.name,fn);}
     else{if(!unit.functions.has(fn.name))unit.functions.set(fn.name,[]);unit.functions.get(fn.name).push(fn);}
     stmt=[];i=close+1;continue;
    }
   }
   // a brace initializer inside a declaration
   for(let j=i;j<=close;j++)stmt.push(toks[j]);i=close+1;continue;
  }
  stmt.push(t);i++;
 }
 flush();
}
function parseEnum(name,body,unit){
 body=body.filter(t=>t.t!=='mark');
 let prev=-1;const choices=[];
 for(const part of splitTop(body)){
  if(!part.length)continue;
  const label=part[0].v;
  const value=part.length>2?evalConst(part.slice(2),unit):prev+1;
  unit.constants.set(label,value);choices.push(label);prev=value;
 }
 unit.enums.set(name,choices);
}
function evalConst(toks,unit){
 const src=toks.map(t=>t.t==='id'?(unit.constants.has(t.v)?String(unit.constants.get(t.v)):t.v):t.v).join(' ');
 // eslint-disable-next-line no-new-func
 return Function('return ('+src+')')();
}
function handleStatement(stmt,unit,cls){
 let toks=stmt;
 if(isId(toks[0],'input')&&isId(toks[1],'group')) return;
 const quals=[];while(toks.length&&toks[0].t==='id'&&['input','sinput','static','const','extern'].includes(toks[0].v)){quals.push(toks[0].v);toks=toks.slice(1);}
 if(toks.length<2||!isId(toks[0])||KEYWORDS.has(toks[0].v)) return;
 // a prototype: <type> name(...) with no initializer
 const paren=toks.findIndex(t=>isOp(t,'('));
 if(paren===2&&isId(toks[1])&&!toks.some(t=>isOp(t,'='))&&!cls&&isOp(toks.at(-1),')')){
  // `CPng EA_LOGO(LOGO_png_data)` (an object with constructor arguments) or a prototype `void f(int a)`.
  const inner=toks.slice(3,-1);const looksPrototype=inner.length===0||inner.some(t=>t.t==='id'&&(SCALAR_TYPES.has(t.v)||t.v==='const'))||isId(toks[0],'void');
  if(looksPrototype) return;
 }
 const type=toks[0].v;
 const decl={type,quals,declarators:[]};
 for(const part of splitTop(toks.slice(1))){
  if(!part.length||!isId(part[0])) continue;
  const d={name:part[0].v,dims:[],init:null,ctorArgs:null};
  let j=1;
  while(isOp(part[j],'[')){const c=matchClose(part,j);d.dims.push(part.slice(j+1,c));j=c+1;}
  if(isOp(part[j],'=')) d.init=part.slice(j+1);
  else if(isOp(part[j],'(')){d.ctorArgs=part.slice(j+1,matchClose(part,j));}
  decl.declarators.push(d);
 }
 if(cls) cls.fields.push(decl); else unit.globals.push(decl);
}
const SCALAR_TYPES=new Set(['bool','char','uchar','short','ushort','int','uint','long','ulong','float','double','string','datetime','color','void']);

// ---------------------------------------------------------------------------------------------------------------
// Conversion of one function body.
const CAST_TYPES=new Set(['int','uint','long','ulong','short','ushort','char','uchar','double','float','string','bool','datetime','color']);
const MQL_STRUCTS=new Set(['MqlDateTime','MqlTick','MqlTradeRequest','MqlTradeResult','MqlTradeTransaction','MqlTradeCheckResult','MqlRates','MqlBookInfo']);
class Converter{
 constructor(unit,refIndex){this.unit=unit;this.refIndex=refIndex;this.statics=[];}
 isType(name){
  return SCALAR_TYPES.has(name)||this.unit.enums.has(name)||this.unit.classes.has(name)||MQL_STRUCTS.has(name)||/^(ENUM_|C[A-Z]|S[A-Z])\w*$/.test(name);
 }
 defaultFor(type,dims){
  let base;
  if(type==='bool') base='false';
  else if(type==='string') base='""';
  else if(SCALAR_TYPES.has(type)||this.unit.enums.has(type)||/^ENUM_/.test(type)) base='0';
  else base='__new('+JSON.stringify(type)+')';
  if(!dims.length) return base;
  const elem='()=>'+(dims.length>1?this.defaultFor(type,dims.slice(1)):base);
  return dims[0].length?'__arrN('+this.expr(dims[0])+','+elem+')':'__arr('+elem+')';
 }
 // fn: {name, params, body, cls}; returns JS source of the function
 convert(fn,{asMethod=false}={}){
  this.fn=fn;this.members=asMethod?memberNames(this.unit,fn.cls):new Set();
  this.refParams=new Set(fn.params.filter(p=>p.ref).map(p=>p.name));
  this.locals=new Set(fn.params.map(p=>p.name));this.staticNames=new Map();
  // Locals are recorded as their declarations are converted, so a member a local shadows is not prefixed after it.
  const body=this.statements(fn.body);
  const params=fn.params.map(p=>p.name+(p.def?'='+this.expr(p.def):'')).join(',');
  return (asMethod?'':'function ')+fn.name+'('+params+'){'+body+'}';
 }
 statements(toks){
  let out=[],i=0,atStart=true;
  while(i<toks.length){
   const t=toks[i];
   if(t.t==='mark'){i++;continue;}
   if(atStart){
    const d=this.tryDeclaration(toks,i);
    if(d){out.push(d.code);i=d.next;atStart=true;continue;}
   }
   // for( init ; ... ) : the init may be a declaration
   if(isId(t,'for')&&isOp(toks[i+1],'(')){
    const close=matchClose(toks,i+1);const inner=toks.slice(i+2,close);
    const parts=splitTop(inner,';');
    const init=this.tryDeclaration([...parts[0],{t:'op',v:';'}],0);
    const head=(init?init.code.replace(/;$/,''):this.expr(parts[0]))+';'+this.expr(parts[1]||[])+';'+this.expr(parts[2]||[]);
    out.push('for('+head+')');i=close+1;atStart=true;continue;
   }
   // an expression run up to the next statement boundary
   let j=i;const stop=new Set([';','{','}']);
   if(isId(t,'else')||isId(t,'do')){out.push(t.v+' ');i++;atStart=true;continue;}
   if(isId(t,'case')||isId(t,'default')){let k=i;while(!isOp(toks[k],':'))k++;out.push(t.v+' '+this.expr(toks.slice(i+1,k))+':');i=k+1;atStart=true;continue;}
   if(isOp(t,'{')||isOp(t,'}')){out.push(t.v);i++;atStart=true;continue;}
   if(isOp(t,';')){out.push(';');i++;atStart=true;continue;}
   // control heads: if/while/switch ( ... ) then a statement
   if((isId(t,'if')||isId(t,'while')||isId(t,'switch'))&&isOp(toks[i+1],'(')){
    const close=matchClose(toks,i+1);out.push(t.v+'('+this.expr(toks.slice(i+2,close))+')');i=close+1;atStart=true;continue;
   }
   while(j<toks.length&&!(toks[j].t==='op'&&stop.has(toks[j].v))){
    if(toks[j].t==='op'&&'(['.includes(toks[j].v)){j=matchClose(toks,j)+1;continue;}
    j++;
   }
   out.push(this.expr(toks.slice(i,j)));i=j;atStart=false;
  }
  return out.join(' ');
 }
 tryDeclaration(toks,i){
  let k=i;let isStatic=false;
  while(isId(toks[k],'static')||isId(toks[k],'const')){if(toks[k].v==='static')isStatic=true;k++;}
  const typeTok=toks[k];
  if(!isId(typeTok)||KEYWORDS.has(typeTok.v)) return null;
  let n=k+1;if(isOp(toks[n],'&'))n++;
  if(!isId(toks[n])) return null;
  if(!this.isType(typeTok.v)&&!(isId(toks[n])&&(isOp(toks[n+1],';')||isOp(toks[n+1],'=')||isOp(toks[n+1],',')||isOp(toks[n+1],'['))&&!this.knownValue(typeTok.v))) return null;
  // the declaration runs to the next top-level ;
  let end=n;let d=0;
  for(;end<toks.length;end++){const x=toks[end];if(x.t==='op'&&'([{'.includes(x.v))d++;if(x.t==='op'&&')]}'.includes(x.v))d--;if(d===0&&isOp(x,';'))break;}
  const type=typeTok.v;const parts=splitTop(toks.slice(n,end));const code=[];
  for(const part of parts){
   const name=part[0].v;const dims=[];let j=1;
   while(isOp(part[j],'[')){const c=matchClose(part,j);dims.push(part.slice(j+1,c));j=c+1;}
   let init;
   if(isOp(part[j],'=')){
    const rhs=part.slice(j+1);
    init=isOp(rhs[0],'{')?'__list('+this.defaultFor(type,dims.slice(1).length?dims.slice(1):[])+',['+splitTop(rhs.slice(1,-1)).filter(p=>p.length).map(p=>this.expr(p)).join(',')+'])':this.expr(rhs);
    if(dims.length&&!isOp(rhs[0],'{')) init=this.expr(rhs);
   }
   else if(isOp(part[j],'(')) init='__new('+JSON.stringify(type)+',['+splitTop(part.slice(j+1,matchClose(part,j))).filter(p=>p.length).map(p=>this.expr(p)).join(',')+'])';
   else init=this.defaultFor(type,dims);
   if(isStatic){
    const g='__S_'+(this.fn.cls?this.fn.cls+'_':'')+this.fn.name+'_'+name;
    this.staticNames.set(name,g);this.statics.push(g);
    code.push('if(!'+g+'__i){'+g+'__i=1;'+g+'='+init+';}');
   }
   else{this.locals.add(name);code.push('let '+name+'='+init+';');}
  }
  return {code:code.join(''),next:end+1};
 }
 knownValue(name){return this.unit.constants.has(name);}
 // expression tokens -> JS
 expr(toks){
  const out=[];
  toks=toks.filter(t=>t.t!=='mark');
  for(let i=0;i<toks.length;i++){
   const t=toks[i],prev=toks[i-1];
   // casts: ( TYPE ) operand
   if(isOp(t,'(')&&isId(toks[i+1])&&isOp(toks[i+2],')')&&(CAST_TYPES.has(toks[i+1].v)||/^ENUM_/.test(toks[i+1].v))
      &&!(prev&&((prev.t==='id'&&!KEYWORDS.has(prev.v))||isOp(prev,')')||isOp(prev,']')))){
    const type=toks[i+1].v;const end=operandEnd(toks,i+3);
    out.push('__cast_'+(type.startsWith('ENUM_')?'enum':type)+'('+this.expr(toks.slice(i+3,end))+')');i=end-1;continue;
   }
   if(t.t==='id'){
    const member=prev&&(isOp(prev,'.')||isOp(prev,'->'));
    if(member&&!isOp(toks[i+1],'(')){out.push(t.v);continue;}
    let name=t.v;
    if(!member){
     if(KEYWORDS.has(name)){out.push(name);continue;}
     if(name==='NULL'){out.push('0');continue;}
     if(this.staticNames&&this.staticNames.has(name)){out.push(this.staticNames.get(name));continue;}
     if(this.refParams&&this.refParams.has(name)){out.push(name+'.v');continue;}
    }
    // a call: wrap by-reference scalar arguments in boxes
    if(isOp(toks[i+1],'(')){
     const close=matchClose(toks,i+1);
     const owner=member?'method':(this.members&&this.members.has(name)&&!this.locals.has(name)?'self':'free');
     const refs=this.refIndex(name,owner,this.fn&&this.fn.cls,splitTop(toks.slice(i+2,close)).filter(p=>p.length).length);
     const args=splitTop(toks.slice(i+2,close)).filter(p=>p.length).map((a,ix)=>{
      const js=this.expr(a);return refs.includes(ix)?'__ref(()=>('+js+'),__z=>('+js+'=__z))':js;});
     out.push((owner==='self'?'this.':'')+name+'('+args.join(',')+')');i=close;continue;
    }
    if(this.members&&this.members.has(name)&&!this.locals.has(name)){out.push('this.'+name);continue;}
    out.push(name);continue;
   }
   if(isOp(t,'->')){out.push('.');continue;}
   if(isOp(t,'{')){out.push('[');continue;}   // an initializer list inside an expression (a nested array)
   if(isOp(t,'}')){out.push(']');continue;}
   if(isOp(t,'::')){continue;}
   out.push(t.v);
  }
  return out.join(' ');
 }
}
// The end (exclusive) of the unary operand starting at toks[i].
function operandEnd(toks,i){
 while(toks[i]&&toks[i].t==='op'&&['-','+','!','~','++','--'].includes(toks[i].v))i++;
 if(isOp(toks[i],'(')&&isId(toks[i+1])&&isOp(toks[i+2],')')&&(CAST_TYPES.has(toks[i+1].v)||/^ENUM_/.test(toks[i+1].v))) return operandEnd(toks,i+3);
 if(isOp(toks[i],'(')) i=matchClose(toks,i)+1;
 else i++;
 for(;;){
  if(isOp(toks[i],'.')&&isId(toks[i+1])){i+=2;continue;}
  if(isOp(toks[i],'[')||isOp(toks[i],'(')){i=matchClose(toks,i)+1;continue;}
  if(isOp(toks[i],'++')||isOp(toks[i],'--')){i++;continue;}
  return i;
 }
}
function memberNames(unit,clsName){
 const names=new Set();
 for(let c=unit.classes.get(clsName);c;c=null){
  for(const f of c.fields)for(const d of f.declarators)names.add(d.name);
  for(const m of c.methods.keys())names.add(m);
 }
 return names;
}

// ---------------------------------------------------------------------------------------------------------------
// MT5 constants whose values the code depends on (comparisons against OP_BUY=0, return codes, timeframes). Every other
// ALL_CAPS identifier the converted code names gets a unique number of its own (property ids, colours, styles).
const API_CONSTANTS={POSITION_TYPE_BUY:0,POSITION_TYPE_SELL:1,ORDER_TYPE_BUY:0,ORDER_TYPE_SELL:1,ORDER_TYPE_BUY_LIMIT:2,ORDER_TYPE_SELL_LIMIT:3,
 ORDER_TYPE_BUY_STOP:4,ORDER_TYPE_SELL_STOP:5,DEAL_TYPE_BUY:0,DEAL_TYPE_SELL:1,DEAL_ENTRY_IN:0,DEAL_ENTRY_OUT:1,DEAL_ENTRY_INOUT:2,DEAL_ENTRY_OUT_BY:3,
 DEAL_REASON_CLIENT:0,DEAL_REASON_EXPERT:3,DEAL_REASON_SL:4,DEAL_REASON_TP:5,TRADE_ACTION_DEAL:1,TRADE_ACTION_SLTP:6,
 TRADE_RETCODE_PLACED:10008,TRADE_RETCODE_DONE:10009,TRADE_RETCODE_DONE_PARTIAL:10010,TRADE_RETCODE_INVALID_STOPS:10016,
 TRADE_TRANSACTION_DEAL_ADD:6,ACCOUNT_MARGIN_MODE_RETAIL_NETTING:0,ACCOUNT_MARGIN_MODE_EXCHANGE:1,ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:2,
 ACCOUNT_TRADE_MODE_DEMO:0,ACCOUNT_TRADE_MODE_CONTEST:1,ACCOUNT_TRADE_MODE_REAL:2,
 PERIOD_CURRENT:0,PERIOD_M1:1,PERIOD_M5:5,PERIOD_M15:15,PERIOD_M30:30,PERIOD_H1:16385,PERIOD_H4:16388,PERIOD_D1:16408,PERIOD_W1:32769,PERIOD_MN1:49153,
 MODE_SMA:0,MODE_EMA:1,MODE_SMMA:2,MODE_LWMA:3,PRICE_CLOSE:1,PRICE_OPEN:2,PRICE_HIGH:3,PRICE_LOW:4,PRICE_MEDIAN:5,PRICE_TYPICAL:6,PRICE_WEIGHTED:7,
 MAIN_LINE:0,SIGNAL_LINE:1,PLUSDI_LINE:1,MINUSDI_LINE:2,BASE_LINE:0,UPPER_BAND:1,LOWER_BAND:2,MODE_HIGH:2,MODE_LOW:1,
 INVALID_HANDLE:-1,EMPTY_VALUE:Number.MAX_VALUE,DBL_MAX:Number.MAX_VALUE,DBL_MIN:2.2250738585072014e-308,DBL_EPSILON:2.220446049250313e-16,
 INT_MAX:2147483647,INT_MIN:-2147483648,UINT_MAX:4294967295,LONG_MAX:9223372036854775807,WRONG_VALUE:-1,clrNONE:-1,
 INIT_SUCCEEDED:0,INIT_FAILED:1,INIT_PARAMETERS_INCORRECT:2,
 MQL_PROGRAM_NAME:900001,MQL_TESTER:900002,MQL_OPTIMIZATION:900003,MQL_FORWARD:900004,MQL_VISUAL_MODE:900005,MQL_PROGRAM_PATH:900006,MQL_DLLS_ALLOWED:900007};
// By-reference scalar arguments of the MT5 API (the converted call passes a box, the model writes box.v).
const API_REFS={GlobalVariableGet:n=>n===2?[1]:[],StringReplace:()=>[0],StringTrimLeft:()=>[0],StringTrimRight:()=>[0],StringToUpper:()=>[0],
 StringToLower:()=>[0],SymbolInfoInteger:n=>n===3?[2]:[],SymbolInfoDouble:n=>n===3?[2]:[],SymbolInfoString:n=>n===3?[2]:[],
 HistoryDealGetInteger:n=>n===3?[2]:[],HistoryDealGetDouble:n=>n===3?[2]:[],PositionGetDouble:n=>n===2?[1]:[],PositionGetInteger:n=>n===2?[1]:[],
 OrderCalcMargin:n=>n===5?[4]:[],OrderCalcProfit:n=>n===6?[5]:[]};
// Classes modelled instead of converted (the panel dialog).
const MOCK_CLASSES=new Set(['CPanelDialog']);
const MQL_STRUCT_FIELDS={
 MqlDateTime:{year:0,mon:0,day:0,hour:0,min:0,sec:0,day_of_week:0,day_of_year:0},
 MqlTick:{time:0,bid:0,ask:0,last:0,volume:0,time_msc:0,flags:0,volume_real:0},
 MqlTradeRequest:{action:0,magic:0,order:0,symbol:'',volume:0,price:0,stoplimit:0,sl:0,tp:0,deviation:0,type:0,type_filling:0,type_time:0,expiration:0,comment:'',position:0,position_by:0},
 MqlTradeResult:{retcode:0,deal:0,order:0,volume:0,price:0,bid:0,ask:0,comment:'',request_id:0,retcode_external:0},
 MqlTradeTransaction:{deal:0,order:0,symbol:'',type:0,order_type:0,order_state:0,deal_type:0,time_type:0,time_expiration:0,price:0,price_trigger:0,price_sl:0,price_tp:0,volume:0,position:0,position_by:0},
 MqlTradeCheckResult:{retcode:0,balance:0,equity:0,profit:0,margin:0,margin_free:0,margin_level:0,comment:''},
};
// An inert object for anything the model does not represent (the panel, dialogs): any member, any call, answers 0.
function inert(){const f=function(){return 0;};const p=new Proxy(f,{get:(o,k)=>k===Symbol.toPrimitive?()=>0:(k==='length'?0:p),apply:()=>0,set:()=>true});return p;}

// The functions modelled instead of converted. None of them sends, modifies or closes an order in the EA either:
// chart objects and the panel, evidence tracing, performance counters, the direction guard and CID guard (allow, as on
// a hedging account whose CID records are in order), the dashboard bus, the AI gate log, the fill-mode probe.
function mockFunctions(w){
 const nop=()=>{};
 return {
  SetEdit:()=>true,HLineCreate:()=>true,HLineDelete:()=>true,VLineCreate:()=>true,TextCreate:()=>true,ArrowCreate:()=>true,ArrowDelete:()=>true,
  RectLabelCreate:()=>true,RectLabelDelete:()=>true,ButtonCreate:()=>true,LabelCreate:()=>true,
  PrintTradeStatus:nop,NewsDisplayFunction:nop,BiasDisplayFunction:nop,AllDisplaySettings:nop,
  GoatTraceEnsureSequence:nop,GoatTraceActivate:nop,GoatTraceEnd:nop,GoatTraceOrderResult:nop,GoatTraceBoundary:nop,GoatTraceInit:nop,GoatTraceClose:nop,
  GoatRankTick:nop,GoatPerformanceRecord:nop,
  GoatDirectionGuardBegin:()=>true,GoatDirectionGuardResult:nop,GoatDirectionGuardEnd:nop,GoatDirectionGuardMaintenance:nop,
  GoatDirectionGuardPublish:nop,GoatDirectionGuardCaptureOrder:nop,GoatDirectionGuardDeal:nop,GoatDirectionGuardStatus:()=>'',
  GoatCidGuardRefuses:()=>false,GoatCidGuardStatus:()=>'',GoatCidGuardAddFrozen:()=>false,GoatCidGuardHeartbeat:nop,
  DashboardBusRollClosedBuckets:nop,DashboardBusSendStatus:nop,GoatGateActiveMask:()=>0,GoatGateLog:nop,
  GOATDeviceActivationOnly:()=>false,GoatStagedChildMayOpen:()=>true,DashboardExposureConflict:()=>false,
  GOATUsingControlTowerBias:()=>!!w.controlTower,
  SetTypeFillingBySymbol:nop,FillingCheckAndSet:nop,GetRetcodeID:()=>'',
  GoatDeployNotice:s=>{w.alerts.push(String(s));},
 };
}

// ---------------------------------------------------------------------------------------------------------------
// The terminal model: one hedging account, one symbol.
const PERIOD_SECONDS={0:60,1:60,5:300,15:900,30:1800,16385:3600,16388:14400,16408:86400,32769:604800};
function terminalModel(w,K){
 const sym=w.symbol;
 const pos=t=>w.positions.find(p=>p.ticket===t);
 const profitOf=p=>{const price=p.type===0?w.bid:w.ask;return Math.round(((p.type===0?price-p.open:p.open-price)/w.point)*w.tickValue*p.volume*100)/100;};
 let selP=null,selection=[];
 const dealAdd=(d)=>{const ticket=++w.nextDeal;const deal={ticket,order:d.order||0,position:d.position,symbol:sym,magic:d.magic,type:d.type,entry:d.entry,
  volume:d.volume,price:d.price,profit:d.profit||0,commission:d.commission||0,swap:0,fee:0,time:w.time,time_msc:w.time*1000,reason:d.reason,comment:d.comment||''};
  w.deals.push(deal);w.pending.push(ticket);return ticket;};
 const open=(type,volume,price,sl,tp,magic,comment)=>{
  const ticket=++w.nextTicket;
  w.positions.push({ticket,identifier:ticket,symbol:sym,magic,type,volume,open:price,sl,tp,time:w.time,time_msc:w.time*1000,comment,swap:0,commission:-w.commissionPerLot*volume});
  const deal=dealAdd({order:ticket,position:ticket,magic,type,entry:0,volume,price,commission:-w.commissionPerLot*volume,reason:3,comment});
  return {ticket,deal};
 };
 const close=(p,volume,reason,price,magic)=>{
  const px=price!==undefined?price:(p.type===0?w.bid:w.ask);const vol=Math.min(volume,p.volume);
  const profit=Math.round(((p.type===0?px-p.open:p.open-px)/w.point)*w.tickValue*vol*100)/100;
  const deal=dealAdd({order:++w.nextTicket,position:p.ticket,magic,type:p.type===0?1:0,entry:1,volume:vol,price:px,profit,reason});
  w.balance+=profit;
  p.volume=Math.round((p.volume-vol)*1e8)/1e8;if(p.volume<=1e-9)w.positions.splice(w.positions.indexOf(p),1);
  w.lastDeal=deal;return deal;
 };
 const ctrade=()=>{const o={magic:0,retcode:0,deal:0};Object.assign(o,{
  SetExpertMagicNumber:m=>{o.magic=m;},SetDeviationInPoints:()=>{},SetTypeFilling:()=>{},SetTypeFillingBySymbol:()=>true,SetAsyncMode:()=>{},LogLevel:()=>{},
  PositionModify:(t,sl,tp)=>{w.trace.push({op:'PositionModify',ticket:t,sl,tp,time:w.time});const p=pos(t);if(!p){o.retcode=10013;return false;}p.sl=sl;p.tp=tp;o.retcode=10009;return true;},
  PositionClose:(t)=>{const p=pos(t);w.trace.push({op:'PositionClose',ticket:t,volume:p?p.volume:0,time:w.time});if(!p){o.retcode=10013;return false;}o.deal=close(p,p.volume,3,undefined,o.magic);o.retcode=10009;return true;},
  PositionClosePartial:(t,v)=>{const p=pos(t);w.trace.push({op:'PositionClosePartial',ticket:t,volume:v,time:w.time});if(!p){o.retcode=10013;return false;}o.deal=close(p,v,3,undefined,o.magic);o.retcode=10009;return true;},
  ResultRetcode:()=>o.retcode,ResultDeal:()=>o.deal,ResultOrder:()=>0,ResultRetcodeDescription:()=>'',ResultComment:()=>'',ResultPrice:()=>0,ResultVolume:()=>0});return o;};
 const positionInfo=()=>{let p=null;return {
  SelectByIndex:i=>{p=w.positions[i]||null;return !!p;},SelectByTicket:t=>{p=pos(t)||null;return !!p;},Select:s=>{p=w.positions.find(x=>x.symbol===s)||null;return !!p;},
  Symbol:()=>p.symbol,Magic:()=>p.magic,Volume:()=>p.volume,PositionType:()=>p.type,Profit:()=>profitOf(p),Commission:()=>p.commission,Swap:()=>p.swap,
  Ticket:()=>p.ticket,Identifier:()=>p.identifier,PriceOpen:()=>p.open,StopLoss:()=>p.sl,TakeProfit:()=>p.tp,Time:()=>p.time,Comment:()=>p.comment,
  PriceCurrent:()=>p.type===0?w.bid:w.ask};};
 const P={POSITION_TICKET:'ticket',POSITION_IDENTIFIER:'identifier',POSITION_MAGIC:'magic',POSITION_TYPE:'type',POSITION_TIME:'time',POSITION_TIME_MSC:'time_msc',
  POSITION_VOLUME:'volume',POSITION_PRICE_OPEN:'open',POSITION_SL:'sl',POSITION_TP:'tp',POSITION_SWAP:'swap',POSITION_SYMBOL:'symbol',POSITION_COMMENT:'comment'};
 const D={DEAL_TICKET:'ticket',DEAL_ORDER:'order',DEAL_POSITION_ID:'position',DEAL_SYMBOL:'symbol',DEAL_MAGIC:'magic',DEAL_TYPE:'type',DEAL_ENTRY:'entry',
  DEAL_VOLUME:'volume',DEAL_PRICE:'price',DEAL_PROFIT:'profit',DEAL_COMMISSION:'commission',DEAL_SWAP:'swap',DEAL_FEE:'fee',DEAL_TIME:'time',DEAL_TIME_MSC:'time_msc',
  DEAL_REASON:'reason',DEAL_COMMENT:'comment'};
 const prop=(map,k)=>{const name=Object.keys(map).find(n=>K[n]===k);if(!name)throw new Error('unmodelled property '+k);return map[name];};
 const posGet=k=>{if(!selP)return 0;const f=prop(P,k);return f==='profit'?profitOf(selP):selP[f];};
 const dealOf=t=>w.deals.find(d=>d.ticket===t);
 const dealGet=(t,k)=>{const d=dealOf(t);return d?d[prop(D,k)]:0;};
 const symD=k=>{const m={SYMBOL_BID:w.bid,SYMBOL_ASK:w.ask,SYMBOL_POINT:w.point,SYMBOL_VOLUME_MIN:w.volumeMin,SYMBOL_VOLUME_MAX:w.volumeMax,SYMBOL_VOLUME_STEP:w.volumeStep,
  SYMBOL_TRADE_TICK_VALUE:w.tickValue,SYMBOL_TRADE_TICK_VALUE_PROFIT:w.tickValue,SYMBOL_TRADE_TICK_VALUE_LOSS:w.tickValue,SYMBOL_TRADE_TICK_SIZE:w.point,
  SYMBOL_TRADE_CONTRACT_SIZE:100000,SYMBOL_MARGIN_INITIAL:0,SYMBOL_SWAP_LONG:0,SYMBOL_SWAP_SHORT:0};
  const name=Object.keys(m).find(n=>K[n]===k);if(!name)throw new Error('unmodelled symbol double '+k);return m[name];};
 const symI=k=>{const m={SYMBOL_SPREAD:Math.round((w.ask-w.bid)/w.point),SYMBOL_DIGITS:w.digits,SYMBOL_TRADE_STOPS_LEVEL:w.stopsLevel,SYMBOL_TRADE_FREEZE_LEVEL:0,
  SYMBOL_FILLING_MODE:3,SYMBOL_TRADE_MODE:4,SYMBOL_TRADE_EXEMODE:2,SYMBOL_EXPIRATION_MODE:15,SYMBOL_ORDER_MODE:127};
  const name=Object.keys(m).find(n=>K[n]===k);if(!name)throw new Error('unmodelled symbol integer '+k);return m[name];};
 const symS=k=>({SYMBOL_CURRENCY_BASE:'EUR',SYMBOL_CURRENCY_PROFIT:'USD',SYMBOL_CURRENCY_MARGIN:'EUR',SYMBOL_DESCRIPTION:'Euro vs US Dollar',SYMBOL_PATH:'Forex\\EURUSD'})[Object.keys(K).find(n=>K[n]===k&&n.startsWith('SYMBOL_'))]??'';
 const equity=()=>w.balance+w.positions.reduce((a,p)=>a+profitOf(p)+p.commission+p.swap,0);
 const toStruct=(t,s)=>{const d=new Date(t*1000);Object.assign(s,{year:d.getUTCFullYear(),mon:d.getUTCMonth()+1,day:d.getUTCDate(),hour:d.getUTCHours(),min:d.getUTCMinutes(),sec:d.getUTCSeconds(),
  day_of_week:d.getUTCDay(),day_of_year:Math.floor((t-Date.UTC(d.getUTCFullYear(),0,1)/1000)/86400)});return true;};
 const tfSec=tf=>PERIOD_SECONDS[tf===0?w.period:tf]||60;
 const barTime=(tf,shift)=>Math.floor(w.time/tfSec(tf))*tfSec(tf)-shift*tfSec(tf);
 const bar=(tf,shift)=>{const b=w.series?w.series(tf===0?w.period:tf,shift,barTime(tf,shift),w):null;const mid=(w.bid+w.ask)/2;return b||{open:mid,high:mid,low:mid,close:mid};};
 return {
  // positions
  PositionsTotal:()=>w.positions.length,PositionGetTicket:i=>{selP=w.positions[i]||null;return selP?selP.ticket:0;},
  PositionSelectByTicket:t=>{selP=pos(t)||null;return !!selP;},PositionSelect:s=>{selP=w.positions.find(p=>p.symbol===s)||null;return !!selP;},
  PositionGetInteger:(k,box)=>{const v=posGet(k);if(box){box.v=v;return !!selP;}return v;},
  PositionGetDouble:(k,box)=>{const v=K.POSITION_PROFIT===k?(selP?profitOf(selP):0):posGet(k);if(box){box.v=v;return !!selP;}return v;},
  PositionGetString:k=>selP?selP[prop(P,k)]:'',
  OrdersTotal:()=>0,OrderGetTicket:()=>0,OrderSelect:()=>false,
  // history
  HistorySelect:(from,to)=>{selection=w.deals.filter(d=>d.time>=from&&d.time<=to).map(d=>d.ticket);return true;},
  HistorySelectByPosition:id=>{selection=w.deals.filter(d=>d.position===id).map(d=>d.ticket);return true;},
  HistoryDealsTotal:()=>selection.length,HistoryDealGetTicket:i=>selection[i]??0,HistoryDealSelect:t=>!!dealOf(t),
  HistoryDealGetInteger:(t,k,box)=>{const v=dealGet(t,k);if(box){box.v=v;return true;}return v;},
  HistoryDealGetDouble:(t,k,box)=>{const v=dealGet(t,k);if(box){box.v=v;return true;}return v;},
  HistoryDealGetString:(t,k)=>dealGet(t,k),HistoryOrdersTotal:()=>0,
  // trading
  OrderSend:(req,res)=>{
   w.trace.push({op:'OrderSend',type:req.type,volume:req.volume,price:req.price,sl:req.sl,tp:req.tp,magic:req.magic,comment:req.comment,time:w.time});
   if(w.rejectOrders){res.retcode=10019;return false;}
   const {ticket,deal}=open(req.type,req.volume,req.price,req.sl,req.tp,req.magic,req.comment);
   Object.assign(res,{retcode:10009,order:ticket,deal,volume:req.volume,price:req.price,bid:w.bid,ask:w.ask});return true;},
  OrderCheck:()=>true,
  // symbol, account, terminal
  Symbol:()=>sym,Period:()=>w.period,Point:()=>w.point,Digits:()=>w.digits,_Symbol:sym,_Point:w.point,_Digits:w.digits,
  SymbolInfoDouble:(s,k,box)=>{const v=symD(k);if(box){box.v=v;return true;}return v;},
  SymbolInfoInteger:(s,k,box)=>{const v=symI(k);if(box){box.v=v;return true;}return v;},
  SymbolInfoString:(s,k)=>symS(k),SymbolInfoTick:(s,tk)=>{Object.assign(tk,{time:w.time,bid:w.bid,ask:w.ask,time_msc:w.time*1000});return true;},
  SymbolSelect:()=>true,SymbolsTotal:()=>1,SymbolName:()=>sym,
  AccountInfoDouble:k=>{if(k===K.ACCOUNT_BALANCE)return w.balance;if(k===K.ACCOUNT_EQUITY)return equity();if(k===K.ACCOUNT_MARGIN)return 0;
   if(k===K.ACCOUNT_MARGIN_FREE)return equity();if(k===K.ACCOUNT_MARGIN_LEVEL)return 0;if(k===K.ACCOUNT_PROFIT)return equity()-w.balance;throw new Error('unmodelled account double '+k);},
  AccountInfoInteger:k=>{if(k===K.ACCOUNT_LOGIN)return w.login;if(k===K.ACCOUNT_MARGIN_MODE)return w.marginMode;if(k===K.ACCOUNT_TRADE_MODE)return 0;
   if(k===K.ACCOUNT_LEVERAGE)return 100;if(k===K.ACCOUNT_TRADE_ALLOWED||k===K.ACCOUNT_TRADE_EXPERT)return 1;throw new Error('unmodelled account integer '+k);},
  AccountInfoString:k=>k===K.ACCOUNT_CURRENCY?'USD':(k===K.ACCOUNT_SERVER?'Harness-Demo':(k===K.ACCOUNT_COMPANY?'Harness':'')),
  MQLInfoInteger:k=>{if(k===K.MQL_TESTER)return w.tester?1:0;if(k===K.MQL_OPTIMIZATION)return w.optimization?1:0;if(k===K.MQL_FORWARD)return 0;
   if(k===K.MQL_VISUAL_MODE)return w.visual?1:0;if(k===K.MQL_DLLS_ALLOWED)return 1;return 0;},
  MQLInfoString:k=>k===K.MQL_PROGRAM_NAME?'GOAT V1.49':'',TerminalInfoInteger:()=>0,TerminalInfoString:()=>'C:\\Harness',
  // time
  TimeCurrent:s=>{if(s&&typeof s==='object')toStruct(w.time,s);return w.time;},TimeTradeServer:s=>{if(s&&typeof s==='object')toStruct(w.time,s);return w.time;},
  TimeGMT:s=>{const t=w.tester?w.time:w.time-w.serverOffset*3600;if(s&&typeof s==='object')toStruct(t,s);return t;},
  TimeLocal:()=>w.tester?w.time:w.time-w.serverOffset*3600,TimeToStruct:(t,s)=>toStruct(t,s),
  StructToTime:s=>Date.UTC(s.year,s.mon-1,s.day,s.hour,s.min,s.sec)/1000,
  GetTickCount:()=>w.time*1000%4294967296,GetTickCount64:()=>w.time*1000,GetMicrosecondCount:()=>w.time*1e6,
  TimeToString:(t,f)=>{const d=new Date(t*1000).toISOString();const date=d.slice(0,10).replace(/-/g,'.'),hm=d.slice(11,16),s=d.slice(11,19);
   if(f===undefined)return date+' '+hm;let out=[];if(f&K.TIME_DATE)out.push(date);if(f&K.TIME_SECONDS)out.push(s);else if(f&K.TIME_MINUTES)out.push(hm);return out.join(' ');},
  StringToTime:s=>mqlDate(String(s).trim()),
  // series and indicators
  SeriesInfoInteger:(s,tf,k)=>barTime(tf,0),PeriodSeconds:tf=>tfSec(tf===undefined?0:tf),
  iTime:(s,tf,sh)=>barTime(tf,sh),iOpen:(s,tf,sh)=>bar(tf,sh).open,iHigh:(s,tf,sh)=>bar(tf,sh).high,iLow:(s,tf,sh)=>bar(tf,sh).low,iClose:(s,tf,sh)=>bar(tf,sh).close,
  iBarShift:(s,tf,t,exact)=>{const sec=tfSec(tf);return Math.floor((barTime(tf,0)-Math.floor(t/sec)*sec)/sec);},
  iHighest:()=>0,iLowest:()=>0,iBars:()=>100000,Bars:()=>100000,
  CopyBuffer:(h,b,start,count,arr)=>{
   const name=w.handleNames[h];if(name===undefined)return -1;
   const vals=[];for(let k=0;k<count;k++){const v=w.indicator(name,b,start+k,w);if(v===undefined||v===null)return -1;vals.push(v);}
   arr.length=0;arr.push(...vals);return count;},
  BarsCalculated:h=>w.handleNames[h]!==undefined?100000:-1,IndicatorRelease:()=>true,
  iATR:()=>w.newHandle('ATR'),iMA:(s,tf,p,sh,m,src)=>w.newHandle(src===w.handleIds.ATR?'ATR_MA':'MA'+(w.maCount++)),iRSI:()=>w.newHandle('RSI'),
  iADX:()=>w.newHandle('ADX'),iBands:()=>w.newHandle('BB'),iCustom:()=>w.newHandle('MACD'),
  // global variables
  GlobalVariableCheck:k=>w.gv.has(k),GlobalVariableSet:(k,v)=>{w.gv.set(k,Number(v));return w.time;},
  GlobalVariableGet:(k,box)=>{if(box){if(!w.gv.has(k))return false;box.v=w.gv.get(k);return true;}return w.gv.get(k)??0;},
  GlobalVariableDel:k=>w.gv.delete(k),GlobalVariablesFlush:()=>{},GlobalVariableTime:()=>w.time,GlobalVariablesTotal:()=>w.gv.size,
  GlobalVariableName:i=>[...w.gv.keys()][i]??'',GlobalVariableTemp:()=>true,
  // chart and objects
  ChartID:()=>w.chartId,ChartRedraw:()=>{},ChartGetInteger:()=>0,ChartGetDouble:()=>0,ChartSetInteger:()=>true,ChartSetDouble:()=>true,ChartFirst:()=>w.chartId,
  ChartNext:()=>-1,ObjectFind:()=>-1,ObjectCreate:()=>true,ObjectDelete:()=>true,ObjectsDeleteAll:()=>0,ObjectSetInteger:()=>true,ObjectSetString:()=>true,
  ObjectSetDouble:()=>true,ObjectGetInteger:()=>0,ObjectGetDouble:()=>0,ObjectGetString:()=>'',ObjectsTotal:()=>0,ObjectName:()=>'',Comment:()=>{},
  // logs and lifecycle
  Print:(...a)=>{w.logs.push(a.map(String).join(''));},PrintFormat:(f,...a)=>{w.logs.push(String(f)+' '+a.map(String).join(','));},
  Alert:(...a)=>{w.alerts.push(a.map(String).join(''));},ExpertRemove:()=>{w.removed=true;},Sleep:()=>{},GetLastError:()=>0,ResetLastError:()=>{},
  PlaySound:()=>true,SendNotification:()=>true,MessageBox:()=>1,EventSetTimer:()=>true,EventSetMillisecondTimer:()=>true,EventKillTimer:()=>{},
  IsStopped:()=>false,FileWrite:()=>0,FileClose:()=>{},FileOpen:()=>-1,FileIsExist:()=>false,
  // values
  ...mathAndStrings(),
  // modelled objects
  __ctrade:ctrade,__positionInfo:positionInfo,
  // the broker side, run before each tick: SL and TP fills
  __brokerFills:()=>{for(const p of [...w.positions]){const px=p.type===0?w.bid:w.ask;
   if(p.sl>0&&(p.type===0?px<=p.sl:px>=p.sl)){w.trace.push({op:'BrokerStop',ticket:p.ticket,price:p.sl,time:w.time});close(p,p.volume,4,p.sl,p.magic);}
   else if(p.tp>0&&(p.type===0?px>=p.tp:px<=p.tp)){w.trace.push({op:'BrokerTake',ticket:p.ticket,price:p.tp,time:w.time});close(p,p.volume,5,p.tp,p.magic);}}},
  __open:open,__equity:equity,
 };
}
function mqlNumberString(x){
 if(typeof x==='boolean') return x?'true':'false';
 if(typeof x!=='number') return String(x);
 if(Number.isInteger(x)) return String(x);
 return String(Number(x.toPrecision(16)));
}
function mathAndStrings(){
 const fix=(v,d)=>{const s=Number(v).toFixed(d);return s==='-0'||/^-0\.0*$/.test(s)?s.slice(1):s;};
 return {
  MathAbs:Math.abs,MathMax:Math.max,MathMin:Math.min,MathPow:Math.pow,MathSqrt:Math.sqrt,MathFloor:Math.floor,MathCeil:Math.ceil,
  MathRound:v=>Math.sign(v)*Math.round(Math.abs(v)),MathLog:Math.log,MathLog10:Math.log10,MathExp:Math.exp,MathMod:(a,b)=>a%b,MathIsValidNumber:v=>Number.isFinite(v),
  MathRand:()=>0,MathSrand:()=>{},MathArctan:Math.atan,MathSin:Math.sin,MathCos:Math.cos,
  fmax:Math.max,fmin:Math.min,fabs:Math.abs,round:v=>Math.sign(v)*Math.round(Math.abs(v)),floor:Math.floor,ceil:Math.ceil,
  NormalizeDouble:(v,d)=>Number(Number(v).toFixed(d)),DoubleToString:(v,d=8)=>fix(v,d),
  IntegerToString:(v,len=0,fill=32)=>{const s=String(Math.trunc(Number(v)));const ch=typeof fill==='number'?String.fromCharCode(fill):fill;return s.length>=len?s:ch.repeat(len-s.length)+s;},
  StringToInteger:s=>{const m=String(s).match(/^\s*[+-]?\d+/);return m?Number(m[0]):0;},StringToDouble:s=>{const v=parseFloat(String(s));return Number.isFinite(v)?v:0;},
  StringLen:s=>String(s).length,StringFind:(s,x,from=0)=>String(s).indexOf(x,from),StringSubstr:(s,a,n=-1)=>n<0?String(s).slice(a):String(s).substr(a,n),
  StringGetCharacter:(s,i)=>String(s).charCodeAt(i)||0,StringSplit:(s,sep,arr)=>{arr.length=0;if(String(s)==='')return 0;arr.push(...String(s).split(typeof sep==='number'?String.fromCharCode(sep):sep));return arr.length;},
  StringReplace:(box,a,b)=>{const parts=String(box.v).split(a);box.v=parts.join(b);return parts.length-1;},
  StringTrimLeft:box=>{box.v=String(box.v).replace(/^\s+/,'');return 0;},StringTrimRight:box=>{box.v=String(box.v).replace(/\s+$/,'');return 0;},
  StringToUpper:box=>{box.v=String(box.v).toUpperCase();return true;},StringToLower:box=>{box.v=String(box.v).toLowerCase();return true;},
  StringFormat:(f,...a)=>String(f)+' '+a.map(String).join(','),StringCompare:(a,b)=>a===b?0:(a<b?-1:1),EnumToString:v=>String(v),CharToString:c=>String.fromCharCode(c),
  ShortToString:c=>String.fromCharCode(c),
  ArraySize:a=>a.length,ArrayResize:(a,n)=>{while(a.length<n)a.push(a.__elem?a.__elem():0);a.length=n;return n;},
  ArrayInitialize:(a,v)=>{for(let i=0;i<a.length;i++)a[i]=v;return a.length;},ArrayFill:(a,s,n,v)=>{for(let i=s;i<s+n;i++)a[i]=v;},
  ArraySort:a=>{a.sort((x,y)=>x-y);return true;},ArrayRemove:(a,s,n=-1)=>{a.splice(s,n<0?a.length-s:n);return true;},ArraySetAsSeries:()=>true,ArrayGetAsSeries:()=>false,ArrayFree:a=>{a.length=0;},
  ArrayCopy:(d,s,ds=0,ss=0,n=-1)=>{const c=n<0?s.length-ss:n;for(let i=0;i<c;i++)d[ds+i]=s[ss+i];return c;},
  ArrayMaximum:(a,s=0,n=-1)=>{let b=-1;for(let i=s;i<(n<0?a.length:s+n);i++)if(b<0||a[i]>a[b])b=i;return b;},
  ArrayMinimum:(a,s=0,n=-1)=>{let b=-1;for(let i=s;i<(n<0?a.length:s+n);i++)if(b<0||a[i]<a[b])b=i;return b;},
  ZeroMemory:o=>{for(const k of Object.keys(o))o[k]=typeof o[k]==='string'?'':0;},
 };
}
const HELPERS=`
function __arr(elem){const a=[];Object.defineProperty(a,'__elem',{value:elem,enumerable:false});return a;}
function __arrN(n,elem){const a=__arr(elem);for(let i=0;i<n;i++)a.push(elem());return a;}
function __list(elem,vals){const a=__arr(()=>elem);a.push(...vals);return a;}
function __ref(get,set){return {get v(){return get();},set v(z){set(z);}};}
function __cast_int(x){return Math.trunc(Number(x))||0;}
const __cast_uint=__cast_int,__cast_long=__cast_int,__cast_ulong=__cast_int,__cast_short=__cast_int,__cast_ushort=__cast_int,__cast_char=__cast_int,
 __cast_uchar=__cast_int,__cast_datetime=__cast_int,__cast_color=__cast_int;
function __cast_double(x){return Number(x);}const __cast_float=__cast_double;
function __cast_bool(x){return !!x;}
function __cast_enum(x){return x;}
function __cast_string(x){return __numberString(x);}
`;

// ---------------------------------------------------------------------------------------------------------------
// Code generation: every free function reachable from the roots (plus every class), converted once per source.
const ROOTS=['GoatTickBody','GoatTradeTransactionBody','WriteSet','SignalEntryTrigger','UpdateCurrentSignals','GetSize','OpenPosition','CloseAllPositions'];
const B50_ROOTS=/^(GoatSingle\w+|GoatSignalAll|GoatNY\w+)$/;   // A1-A3 add bodies to these; they are converted when defined
// OnInit slices the harness runs for a fixture (token patterns: start inclusive, end inclusive).
const ONINIT_SLICES=[
 ['session',['string','sessionTxt','['],['Print','(','"Fri:"']],
 ['sizes',['if','(','1',')','{','Grid_Min_'],['SL_Pips_','=','SL_Pips',';']],
 ['buyen',['if','(','Mode_Trade','==','Long_and_Short','||','Mode_Trade','==','Long',')','Buy_EN'],null],
 ['lots',['StartingEquity','=','AccountInfoDouble'],['ArrayResize','(','Position_Durations',',','0',')',';']],
];
const sliceCache=new Map();
function compile(files){
 const key=JSON.stringify(files);if(sliceCache.has(key))return sliceCache.get(key);
 const pp=preprocess(files);const toks=expandMacros(tokenize(pp.text),pp.macros);const unit=parseUnit(toks);
 const dummy={positions:[],deals:[],gv:new Map(),handleNames:{},handleIds:{}};
 const mockNames=new Set(Object.keys(mockFunctions(dummy)));
 const apiNames=new Set(Object.keys(terminalModel(dummy,API_CONSTANTS)));
 const refsOf=fn=>fn.params.map((p,i)=>p.ref?i:-1).filter(i=>i>=0);
 const refIndex=(name,owner,cls,argc)=>{
  if(owner==='self'){const m=unit.classes.get(cls).methods.get(name);return m?refsOf(m):[];}
  if(owner==='method'){for(const c of unit.classes.values()){const m=c.methods.get(name);if(m&&!MOCK_CLASSES.has(c.name))return refsOf(m);}return [];}
  if(mockNames.has(name)) return [];
  const fns=unit.functions.get(name);if(fns) return refsOf(fns[0]);
  if(API_REFS[name]) return API_REFS[name](argc);
  return [];
 };
 const conv=new Converter(unit,refIndex);
 const want=new Set(),todo=[],unresolved=new Set(),parent=new Map();let scanning='(root)';
 const scan=(body,cls)=>{for(let i=0;i<body.length;i++){const t=body[i];
  if(t.t==='id'&&isOp(body[i+1],'(')&&!(i>0&&(isOp(body[i-1],'.')||isOp(body[i-1],'->')))){
   if(KEYWORDS.has(t.v)||(cls&&unit.classes.get(cls).methods.has(t.v)))continue;if(!parent.has(t.v))parent.set(t.v,scanning);todo.push(t.v);}}};
 for(const n of [...ROOTS,...[...unit.functions.keys()].filter(n=>B50_ROOTS.test(n))]) if(unit.functions.has(n)) todo.push(n);
 const classes=[...unit.classes.values()].filter(c=>!MOCK_CLASSES.has(c.name));
 for(const c of classes){for(const m of c.methods.values()){scanning=c.name+'::'+m.name;scan(m.body,c.name);}if(c.ctor){scanning=c.name+'()';scan(c.ctor.body,c.name);}}
 for(const g of unit.globals)for(const d of g.declarators){scanning='global '+d.name;if(d.init)scan(d.init);if(d.ctorArgs)scan(d.ctorArgs);}
 const onInit=unit.functions.get('OnInit')[0];
 const slices={};
 const find=(body,pat,from=0)=>{for(let i=from;i<=body.length-pat.length;i++)if(pat.every((v,k)=>body[i+k].v===v))return i;return -1;};
 for(const [name,start,end] of ONINIT_SLICES){
  const a=find(onInit.body,start);if(a<0)throw new Error('OnInit slice '+name+' not found');
  let b;
  if(end){const e=find(onInit.body,end,a);if(e<0)throw new Error('OnInit slice '+name+' has no end');b=e+end.length;
   let d=0;for(let k=a;k<b-1;k++){if(isOp(onInit.body[k],'('))d++;if(isOp(onInit.body[k],')'))d--;}
   for(;!(d===0&&isOp(onInit.body[b-1],';'));b++){const x=onInit.body[b];if(isOp(onInit.body[b-1],'('))d++;if(isOp(onInit.body[b-1],')'))d--;if(d===0&&isOp(x,';')){b++;break;}}}   // to the end of that statement
  else{b=a;while(!isOp(onInit.body[b],';'))b++;b++;let e=b;while(!isOp(onInit.body[e],';'))e++;b=e+1;}   // the if and its else (two statements)
  slices[name]=onInit.body.slice(a,b);scanning='OnInit slice '+name;scan(slices[name]);
 }
 // B50's OnInit block, when the source has one: run as written (its refusals return the INIT code).
 const mb=onInit.body.findIndex(t=>t.t==='mark'&&t.v==='begin:b50-init'),me=onInit.body.findIndex(t=>t.t==='mark'&&t.v==='end:b50-init');
 if(mb>=0){slices.b50=onInit.body.slice(mb+1,me);scan(slices.b50);}
 while(todo.length){
  const n=todo.pop();if(want.has(n)||mockNames.has(n))continue;
  const fns=unit.functions.get(n);
  if(!fns){if(!apiNames.has(n)&&!unit.classes.has(n)&&!MQL_STRUCT_FIELDS[n]&&!CAST_TYPES.has(n))unresolved.add(n);continue;}
  if(fns.length>1)throw new Error('overloaded MQL function '+n+': model it in MOCKS');
  want.add(n);scanning=n;scan(fns[0].body);
 }
 const chain=n=>{const c=[n];while(parent.has(c.at(-1))&&c.length<12)c.push(parent.get(c.at(-1)));return c.join(' <- ');};
 if(unresolved.size) throw new Error('b50_tick_harness: unmodelled MQL/MT5 functions:\n '+[...unresolved].sort().map(chain).join('\n '));
 // JavaScript
 const parts=[HELPERS];
 const dummyFn={name:'__global',params:[],body:[],cls:null};
 const prime=fn=>{conv.fn=fn;conv.members=new Set();conv.refParams=new Set();conv.locals=new Set();conv.staticNames=new Map();};
 for(const c of classes){
  prime(dummyFn);
  const fields=c.fields.flatMap(f=>f.declarators.map(d=>'this.'+d.name+'='+(d.init?conv.expr(d.init):conv.defaultFor(f.type,d.dims))+';')).join('');
  const methods=[...c.methods.values()].map(m=>conv.convert(m,{asMethod:true}));
  if(c.ctor) methods.push(conv.convert({...c.ctor,name:'__ctor'},{asMethod:true}));
  parts.push('class '+c.name+'{constructor(...__a){'+fields+(c.ctor?'this.__ctor(...__a);':'')+'}'+methods.join('\n')+'}');
 }
 parts.push('const __classes={'+classes.map(c=>c.name).join(',')+'};');
 parts.push('function __new(type,args){if(__classes[type])return new __classes[type](...(args||[]));if(__MQL_STRUCTS[type])return {...__MQL_STRUCTS[type]};'
  +'if(type==="CTrade")return __ctrade();if(type==="CPositionInfo")return __positionInfo();return __inert();}');
 for(const n of want) parts.push(conv.convert(unit.functions.get(n)[0]));
 for(const [name,body] of Object.entries(slices)) if(body){prime({name:'__oninit_'+name,params:[],body,cls:null});parts.push('function __oninit_'+name+'(){'+conv.statements(body)+'}');}
 prime(dummyFn);
 const globals=[];
 for(const g of unit.globals)for(const d of g.declarators){
  const init=d.init?(isOp(d.init[0],'{')?'__list('+conv.defaultFor(g.type,[])+',['+splitTop(d.init.slice(1,-1)).filter(p=>p.length).map(p=>conv.expr(p)).join(',')+'])':conv.expr(d.init))
   :d.ctorArgs?'__new('+JSON.stringify(g.type)+',['+splitTop(d.ctorArgs).filter(p=>p.length).map(p=>conv.expr(p)).join(',')+'])':conv.defaultFor(g.type,d.dims);
  globals.push({name:d.name,input:g.quals.includes('input')||g.quals.includes('sinput'),type:g.type,code:'var '+d.name+'='+init+';'});
 }
 const statics=[...new Set(conv.statics)].map(s=>'var '+s+','+s+'__i=0;');
 parts.splice(1,0,statics.join(''));
 parts.push(globals.map(g=>'try{'+g.code+'}catch(e){__globalErrors.push(['+JSON.stringify(g.name)+',String(e)]);}').join('\n'));
 const code=parts.join('\n');
 // Every ALL_CAPS identifier the code names and nothing defines: an MT5 constant.
 const defined=new Set([...unit.constants.keys(),...globals.map(g=>g.name),...unit.functions.keys(),...unit.classes.keys()]);
 const constants={...API_CONSTANTS};let next=1000000;
 for(const m of code.matchAll(/(?<![\w.])([A-Z][A-Z0-9_]{2,}|clr[A-Z]\w*)(?!\w)/g)){const n=m[1];if(!(n in constants)&&!defined.has(n))constants[n]=next++;}
 let script;
 try{script=new vm.Script(code,{filename:'b50_tick_harness_generated.js'});}
 catch(e){fs.writeFileSync(path.join(require('node:os').tmpdir(),'b50_harness_failed.js'),code);throw e;}
 const out={unit,code,script,constants,globals,macros:pp.macros,functions:[...want].sort(),slices:Object.keys(slices)};
 sliceCache.set(key,out);return out;
}

// ---------------------------------------------------------------------------------------------------------------
// Globals of the includes the harness does not inline, at their declared defaults (the models above stand in for
// their functions). News and Bias are the fixture's: news windows and bias scores by time.
function externs(w){
 return {
  g_trace_current_sequence:0,g_direction_guard_send_attempted:false,g_direction_guard_denied:false,
  g_GoatStudioMonitorRunPath:'',g_GoatStudioReadOnlyMonitor:false,g_GoatPanelUnavailable:false,g_GoatGateStateRead:false,g_GoatGateState:{},
  g_GoatCidGuardReason:'',
  News:{TodaysNewsList:[],Init:()=>{},IsNewsTime:(s,th,idx)=>{idx.length=0;return !!(w.news&&w.news(w.time,w));}},
  Bias:{Init:()=>{},GetCurentBiasScore:()=>w.bias?w.bias(w.time,w):-999},
  GOATBiasWireV2:inert(),PanelDialog:inert(),TesterDialog:inert(),DashboardDialog:inert(),
  LOGO_png_data:[],PANEL_LOGO_png_data:[],   // #resource arrays
 };
}

// One world: a fresh context over the compiled source, inputs set, OnInit's derivations run.
// fixture: {inputs:{name:value}, tester, optimization, fastSpeed, magic, start (server time, s), bid, spread,
//           indicator(name,buffer,shift,w), series(tf,shift,barTime,w), news(time,w), bias(time,w), world:{...}}
function build(source,fx={}){
 const files=source&&source.files?source.files:loadSources(source,source&&source.overrides||{});
 const C=compile(files);
 const spread=fx.spread??0.0001;
 const w={symbol:'EURUSD',point:1e-5,digits:5,tickValue:1,volumeMin:0.01,volumeMax:100,volumeStep:0.01,stopsLevel:0,commissionPerLot:0,
  balance:100000,login:12345678,marginMode:2,serverOffset:2,period:1,chartId:128604373052183041,
  tester:fx.tester??true,optimization:!!fx.optimization,visual:false,time:fx.start??(Date.UTC(2026,9,5,0,0,0)/1000),
  bid:fx.bid??1.1,ask:Number(((fx.bid??1.1)+spread).toFixed(5)),positions:[],deals:[],pending:[],nextTicket:5000000,nextDeal:9000000,gv:new Map(),
  trace:[],logs:[],alerts:[],handleNames:{},handleIds:{},maCount:0,indicator:fx.indicator||(()=>undefined),series:fx.series||null,news:fx.news||null,bias:fx.bias||null,
  controlTower:false,...(fx.world||{})};
 w.newHandle=name=>{const h=10+Object.keys(w.handleNames).length;w.handleNames[h]=name;w.handleIds[name]=h;return h;};
 const api=terminalModel(w,C.constants);
 const ctx={...C.constants,...Object.fromEntries(C.unit.constants),...api,...mockFunctions(w),...externs(w),
  __MQL_STRUCTS:MQL_STRUCT_FIELDS,__inert:inert,__numberString:mqlNumberString,__globalErrors:[],m_position:api.__positionInfo(),m_order:inert()};
 vm.createContext(ctx);C.script.runInContext(ctx);
 if(ctx.__globalErrors.length) throw new Error('globals failed: '+JSON.stringify(ctx.__globalErrors.slice(0,5)));
 const inputNames=new Set(C.globals.filter(g=>g.input).map(g=>g.name));
 const inputTypes=new Map(C.globals.filter(g=>g.input).map(g=>[g.name,g.type]));
 const setInput=(k,v)=>{
  if(!inputNames.has(k))throw new Error('not an input of this source: '+k);
  // an enum input may be given by its label
  ctx[k]=typeof v==='string'&&inputTypes.get(k)!=='string'&&C.unit.constants.has(v)?C.unit.constants.get(v):v;
 };
 for(const [k,v] of Object.entries(fx.inputs||{})) setInput(k,v);
 // OnInit, as it runs for this chart: identity, the session table, the sizes, the lots chain and its refusals,
 // the timeframes and indicator handles, B50's block (when the source has one), then the sequences.
 ctx.MAGIC1=fx.magic??1843920117;ctx.Strat=ctx.EA_Desc;ctx.Mode='';ctx.Expiry=Date.UTC(2099,0,1)/1000;
 const run=n=>{if(typeof ctx['__oninit_'+n]!=='function')return undefined;return ctx['__oninit_'+n]();};
 for(const n of ['session','sizes','buyen']){const r=run(n);if(r!==undefined)throw new Error('OnInit refused ('+n+'): '+r);}
 ctx.FastSpeed_Flag=fx.fastSpeed??w.tester;
 // 'lots' runs from the lot sizing to the indicator handles, B50's block included (__oninit_b50 is that block alone).
 {const r=run('lots');if(r!==undefined){const e=new Error('OnInit refused: '+r);e.initCode=r;throw e;}}
 const OP_BUY=Number(C.macros.get('OP_BUY').body),OP_SELL=Number(C.macros.get('OP_SELL').body);   // object macros (0, 1)
 ctx.Seq_Buy.Init(OP_BUY,false);ctx.Seq_Sell.Init(OP_SELL,false);
 if(Math.abs(ctx.Delay_Trade)>0){ctx.Seq_Buy_Virtual.Init(OP_BUY,true);ctx.Seq_Sell_Virtual.Init(OP_SELL,true);}
 if(fx.adopt){fx.adopt(ctx,w);ctx.Seq_Buy.AdoptOpenPositions();ctx.Seq_Sell.AdoptOpenPositions();}
 const pump=()=>{let guard=0;while(w.pending.length){if(++guard>10000)throw new Error('transaction loop');const deal=w.pending.shift();
  const trans={...MQL_STRUCT_FIELDS.MqlTradeTransaction,type:C.constants.TRADE_TRANSACTION_DEAL_ADD,deal,symbol:w.symbol};
  ctx.GoatTradeTransactionBody(trans,{...MQL_STRUCT_FIELDS.MqlTradeRequest},{...MQL_STRUCT_FIELDS.MqlTradeResult});}};
 pump();
 // One tick at server time t: the broker's SL/TP fills first, then OnTick's body, then the trade transactions.
 const px=v=>Number(Number(v).toFixed(w.digits));   // MT5 quotes are normalized to the symbol's digits
 const tick=(t,bid,ask)=>{w.time=t;w.bid=px(bid);w.ask=px(ask??bid+spread);api.__brokerFills();pump();ctx.GoatTickBody();pump();};
 return {ctx,w,C,tick,pump,setInput,
  // a path of [t,bid] points, one tick each
  run:path=>{for(const [t,bid,ask] of path)tick(t,bid,ask);return w.trace;}};
}

module.exports={ROOT,MAIN,HEADER,readSource,loadSources,preprocess,tokenize,expandMacros,parseUnit,Converter,matchClose,isId,isOp,splitTop,compile,build,API_CONSTANTS};
