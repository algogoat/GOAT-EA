// B51 random-direction reference (B50-beta-1a, docs/b50/B50_ALPHA_DESIGN.md section 8). A library, not a test: the B51
// tests load it (test_b51_random.cjs, test_b51_parity.cjs).
//
// scripts/b50_tick_harness.cjs converts MQL to JavaScript numbers, so it does not model ulong arithmetic: its conversion
// of GoatSingleRandomSide computes doubles and 32-bit shifts. This file gives the tests two things the harness cannot:
// - splitmix64(state): an independent JavaScript reference of SplitMix64 on BigInt, written from the published
//   algorithm (Vigna's splitmix64.c), checked against its published first outputs for the state 0;
// - mqlRandomSide(source): GoatSingleRandomSide as the source in front of it writes it (the working tree, or the mutated
//   entrypoint in GOAT_EA_MAIN), evaluated with MQL's ulong rules on BigInt: every ulong operation wraps modulo 2^64,
//   (int) keeps the low 32 bits. It reads only the function's own text, and refuses (an assertion) any token outside
//   the pure arithmetic the function may contain: its two parameters, its one local, integer literals, casts to ulong
//   and int, and the operators ^ | & + * << >> ( ). A MathRand read, a time read or a global read is refused, so it can
//   never hide behind the reference. The tests install it in the harness in place of the converted function.
'use strict';
const assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const M64=(1n<<64n)-1n;
const U=v=>BigInt.asUintN(64,BigInt(v));

// SplitMix64: z=state+gamma; z=(z^(z>>30))*C1; z=(z^(z>>27))*C2; return z^(z>>31) (all modulo 2^64).
function splitmix64(state){
 let z=(U(state)+0x9E3779B97F4A7C15n)&M64;
 z=((z^(z>>30n))*0xBF58476D1CE4E5B9n)&M64;
 z=((z^(z>>27n))*0x94D049BB133111EBn)&M64;
 return (z^(z>>31n))&M64;
}
// The documented side: 0 buy, 1 sell, the low bit of splitmix64((ulong)seed XOR (ulong)bar).
const referenceSide=(seed,bar)=>Number(splitmix64(U(seed)^U(bar))&1n);

const SIGNATURE='int GoatSingleRandomSide(const int seed,const datetime bar)';
function functionText(main){
 const at=main.indexOf(SIGNATURE);
 assert.ok(at>=0,'GoatSingleRandomSide is defined with its signature: '+SIGNATURE);
 assert.equal(main.indexOf(SIGNATURE,at+1),-1,'GoatSingleRandomSide is defined once');
 const open=main.indexOf('{',at);let d=0,end=open;
 for(;end<main.length;end++){if(main[end]==='{')d++;if(main[end]==='}'){d--;if(!d)break;}}
 return main.slice(open+1,end);
}
const PARAMS=['seed','bar'],LOCAL='b51_z';
// A tiny evaluator for the function body: statements `ulong z=e;`, `z=e;`, `z op= e;` (op in + ^ | & *), `return e;`.
function compileSide(body){
 const toks=H.tokenize(body.replace(/\/\/[^\n]*/g,''));
 for(const t of toks){
  if(t.t==='id') assert.ok([...PARAMS,LOCAL,'ulong','int','return'].includes(t.v),'GoatSingleRandomSide reads only its parameters and its local (found '+t.v+')');
  else if(t.t==='num') assert.match(t.v,/^(0[xX][0-9a-fA-F]+|\d+)$/,'GoatSingleRandomSide uses integer literals only (found '+t.v+')');
  else if(t.t==='op') assert.ok(['^','|','&','+','*','<<','>>','(',')',';','=','+=','^=','|=','&=','*='].includes(t.v),'GoatSingleRandomSide uses ulong arithmetic only (found '+t.v+')');
  else assert.fail('GoatSingleRandomSide: unexpected token '+JSON.stringify(t));
 }
 // Statements.
 const stmts=[];let cur=[];
 for(const t of toks){if(t.t==='op'&&t.v===';'){stmts.push(cur);cur=[];}else cur.push(t);}
 assert.equal(cur.length,0,'GoatSingleRandomSide: every statement ends with ;');
 // Expression parser (precedence as C: * > + > << >> > & > ^ > |), with casts and parentheses.
 const PREC={'*':5,'+':4,'<<':3,'>>':3,'&':2,'^':1,'|':0};
 function parse(ts){
  let i=0;
  const peek=()=>ts[i],next=()=>ts[i++];
  function unary(){
   const t=next();assert.ok(t,'GoatSingleRandomSide: an expression ends early');
   if(t.t==='op'&&t.v==='('){
    if(ts[i]&&ts[i].t==='id'&&(ts[i].v==='ulong'||ts[i].v==='int')&&ts[i+1]&&ts[i+1].v===')'){
     const type=ts[i].v;i+=2;const e=unary();
     return type==='ulong'?(env=>U(e(env))):(env=>BigInt.asIntN(32,e(env)));
    }
    const e=binary(-1);const c=next();assert.ok(c&&c.v===')','GoatSingleRandomSide: unbalanced parenthesis');return e;
   }
   if(t.t==='num'){const v=BigInt(t.v);return ()=>v;}
   if(t.t==='id'&&(PARAMS.includes(t.v)||t.v===LOCAL)){const name=t.v;return env=>{assert.ok(name in env,'GoatSingleRandomSide reads '+name+' before it is set');return env[name];};}
   assert.fail('GoatSingleRandomSide: unexpected operand '+t.v);
  }
  function binary(min){
   let left=unary();
   for(;;){
    const t=peek();if(!t||t.t!=='op'||!(t.v in PREC)||PREC[t.v]<=min)return left;
    next();const op=t.v,right=binary(PREC[op]),l=left;
    left=env=>{const a=l(env),b=right(env);
     switch(op){case '*':return (a*b)&M64;case '+':return (a+b)&M64;case '<<':return (a<<b)&M64;case '>>':return U(a)>>b;
      case '&':return a&b;case '^':return a^b;case '|':return a|b;}};
   }
  }
  const e=binary(-1);assert.equal(i,ts.length,'GoatSingleRandomSide: trailing tokens in an expression');
  return e;
 }
 const prog=stmts.map(s=>{
  if(s[0].t==='id'&&s[0].v==='return') return {ret:parse(s.slice(1))};
  let k=0;if(s[0].v==='ulong')k=1;
  assert.ok(s[k]&&s[k].v===LOCAL,'GoatSingleRandomSide assigns only '+LOCAL);
  const op=s[k+1].v;assert.ok(['=','+=','^=','|=','&=','*='].includes(op),'GoatSingleRandomSide: assignment '+op);
  const e=parse(s.slice(k+2));
  const f={'=':(a,b)=>b,'+=':(a,b)=>(a+b)&M64,'^=':(a,b)=>a^b,'|=':(a,b)=>a|b,'&=':(a,b)=>a&b,'*=':(a,b)=>(a*b)&M64}[op];
  return {set:(env)=>{env[LOCAL]=U(f(op==='='?0n:env[LOCAL],e(env)));}};
 });
 assert.ok(prog.length>0&&prog.at(-1).ret,'GoatSingleRandomSide ends with its return');
 // run(seed,bar) -> {side (the int it returns), z (the local before the return)}
 return (seed,bar)=>{
  const env={seed:BigInt.asIntN(32,BigInt(seed)),bar:U(bar)};
  for(const p of prog){if(p.ret){const v=p.ret(env);return {side:Number(BigInt.asIntN(32,v)),z:env[LOCAL]};}p.set(env);}
  assert.fail('GoatSingleRandomSide returns');
 };
}
// The source's GoatSingleRandomSide (undefined: the working tree, or GOAT_EA_MAIN), with MQL ulong semantics.
function mqlRandomSide(main=H.readSource(undefined,H.MAIN)){return compileSide(functionText(main));}
// Install it in a harness world in place of the converted (double-precision) function.
function install(W,main){const run=mqlRandomSide(main);W.ctx.GoatSingleRandomSide=(seed,bar)=>run(seed,bar).side;return run;}

module.exports={splitmix64,referenceSide,mqlRandomSide,install,functionText,M64};
