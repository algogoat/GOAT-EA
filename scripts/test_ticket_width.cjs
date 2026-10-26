// B49a: no int holds a ticket (goatai#2587 6427752813 / 6427772701). MT5 position, deal and order tickets are 64-bit.
// Through B47 the EA kept the last order/deal ticket in `int` globals (GOAT_Inputs_Definitions.mqh) and cast
// `(int)resolvedPositionTicket` / `(int)result.deal` after every OrderSend. Demo-server position tickets were
// 2,121,259,469 on 2026-10-26 (about 26.2 M under INT_MAX, growing about 240k/day), so they cross INT_MAX between late
// Jan and late Mar 2027. After that the cast wraps negative, the new level stores a negative ticket,
// PositionSelectByTicket((ulong)ticket) fails, and the EA treats the level as closed (the D8 shape: the position keeps
// only its broker TP/SL).
// 1. Lint: across the V1.49 compile closure, no narrow cast ((int), (uint), (short), (ushort), (char), (uchar)) takes a
//    ticket-like operand, and no narrow variable or field is named like a ticket.
// 2. Fixture: the widths are read from the source (the globals' declared type, the casts in both OrderSend success
//    blocks, the level struct's ticket field), and tickets above INT_MAX are replayed through them with MQL5 integer
//    semantics: the level keeps the ticket and the readback selects the same position. Source semantics only: a
//    backtest cannot issue a ticket above INT_MAX, so the native half is the compile (a narrowing assignment warns,
//    and B49a must compile with 0 warnings).
// 3. Negative control: both checks run on B47's source and must catch it.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B47_SOURCE='ccb0a07';
const readTree=f=>fs.readFileSync(path.join(ROOT,f),'utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
const readB47=f=>execFileSync('git',['show',B47_SOURCE+':'+f],{cwd:ROOT,maxBuffer:64<<20,stdio:['ignore','pipe','ignore']}).toString('utf8').replace(/^﻿/,'').replace(/\r\n/g,'\n');
// Comments (and, for the lint, string contents) blanked, line numbers kept.
const stripComments=text=>text.replace(/"(?:\\.|[^"\\\n])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g,m=>m.startsWith('"')?m:m.replace(/[^\n]/g,' '));
const strip=text=>stripComments(text).replace(/"(?:\\.|[^"\\\n])*"/g,'""');
let passed=0;

function closure(read){
 const seen=new Set(),todo=['GOAT V1.49.mq5'];
 while(todo.length){
  const f=todo.pop();if(seen.has(f))continue;seen.add(f);
  for(const m of stripComments(read(f)).matchAll(/^\s*#include\s+"([^"]+)"/gm)){
   const inc=m[1].replace(/\\/g,'/');
   try{read(inc);todo.push(inc);}catch{/* a system include */}
  }
 }
 return [...seen].sort();
}

const NARROW='(?:u?int|u?short|u?char)';
// What is cast decides, not what is mentioned: (int)HistoryDealGetInteger(ticket,DEAL_ENTRY) narrows an enum.
const TICKET_PROPERTY=/^(?:POSITION_TICKET|POSITION_IDENTIFIER|DEAL_TICKET|DEAL_ORDER|DEAL_POSITION_ID|ORDER_TICKET|ORDER_POSITION_ID|ORDER_POSITION_BY_ID)$/;
function ticketish(operand){
 const getter=/^\(?\s*(?:PositionGetInteger|HistoryDealGetInteger|HistoryOrderGetInteger|OrderGetInteger)\s*\(([\s\S]*)\)\s*\)?$/.exec(operand);
 if(getter)return TICKET_PROPERTY.test(getter[1].split(',').at(-1).trim());
 if(/^\(?\s*(?:PositionGetTicket|HistoryDealGetTicket|HistoryOrderGetTicket|OrderGetTicket)\s*\(/.test(operand))return true;
 return /ticket|\.deal\b|\.order\b|\.position\b/i.test(operand);
}
// The operand of a cast: a parenthesised expression, or an identifier chain with an optional call.
function operandAt(text,i){
 while(text[i]===' ')i++;
 const balanced=start=>{let depth=0,j=start;for(;j<text.length;j++){if(text[j]==='(')depth++;else if(text[j]===')'&&--depth===0)return j+1;}return j;};
 if(text[i]==='(')return text.slice(i,balanced(i));
 const m=/^[A-Za-z_][\w.]*(?:\[[^\]]*\])*(?:\.[A-Za-z_]\w*)*/.exec(text.slice(i));if(!m)return '';
 let end=i+m[0].length;if(text[end]==='(')end=balanced(end);
 return text.slice(i,end);
}
function lint(read){
 const findings=[];
 for(const f of closure(read)){
  const text=strip(read(f));
  for(const m of text.matchAll(new RegExp('\\(\\s*'+NARROW+'\\s*\\)','g'))){
   const operand=operandAt(text,m.index+m[0].length);
   if(ticketish(operand))findings.push(f+':'+(text.slice(0,m.index).split('\n').length)+': '+m[0]+operand);
  }
  // Declarations, parameters and struct fields: a narrow type followed by a declarator list naming a ticket.
  for(const m of text.matchAll(new RegExp('(?:^|[;{}(,])\\s*(?:const\\s+|static\\s+)*('+NARROW+')\\s+([^;(){}]*)','gm'))){
   for(const declarator of m[2].split(',')){
    const name=(declarator.match(/^\s*&?\s*([A-Za-z_]\w*)/)||[])[1];
    if(name&&/ticket/i.test(name))findings.push(f+':'+(text.slice(0,m.index).split('\n').length)+': '+m[1]+' '+name);
   }
  }
 }
 return findings;
}

// 1. The lint passes on the tree, and catches B47 (4 casts, 4 globals).
assert.deepEqual(lint(readTree),[],'no int holds a ticket');passed++;
const b47Findings=lint(readB47);
assert.equal(b47Findings.filter(x=>/\(int\)/.test(x)).length,4,'B47: the four (int) ticket casts are caught\n'+b47Findings.join('\n'));
for(const name of ['LastOrderTicket','LastDealTicket','LastBuyTicket','LastSellTicket']) assert.ok(b47Findings.some(x=>x.endsWith('int '+name)),'B47: int '+name+' is caught');
passed++;

// 2. The fixture: widths read from the source, tickets above INT_MAX replayed with MQL5 integer semantics.
const WIDTH={int:v=>BigInt.asIntN(32,v),uint:v=>BigInt.asUintN(32,v),long:v=>BigInt.asIntN(64,v),ulong:v=>BigInt.asUintN(64,v)};
function widths(read){
 const header=strip(read('GOAT_Inputs_Definitions.mqh')),main=strip(read('GOAT V1.49.mq5'));
 const decl=name=>{const m=new RegExp('^\\s*(\\w+)\\s+[^;\\n]*\\b'+name+'\\b[^;\\n]*;','m').exec(header);assert.ok(m,'declaration of '+name);return m[1];};
 const globals=Object.fromEntries(['LastOrderTicket','LastDealTicket','LastBuyTicket','LastSellTicket'].map(n=>[n,decl(n)]));
 // Both OrderSend success blocks: the order ticket cast and the deal cast.
 const orderCasts=[...main.matchAll(/LastOrderTicket=\((\w+)\)resolvedPositionTicket;/g)].map(m=>m[1]);
 const dealCasts=[...main.matchAll(/LastDealTicket=Last(?:Buy|Sell)Ticket=\((\w+)\)result\.deal;/g)].map(m=>m[1]);
 assert.equal(orderCasts.length,2,'two order-ticket assignments');assert.equal(dealCasts.length,2,'two deal-ticket assignments');
 // The level struct's ticket field (TradeLevels[i].ticket).
 const levelType=(/^\s*(\w+)\s+TradeLevels\s*\[/m.exec(main)||[])[1];assert.ok(levelType,'TradeLevels declaration');
 const struct=new RegExp('(?:class|struct)\\s+'+levelType+'\\s*\\{([\\s\\S]*?)\\b'+levelType+'\\s*\\(').exec(main);assert.ok(struct,'class '+levelType);
 const field=(/^\s*(\w+)\s+ticket\s*;/m.exec(struct[1])||[])[1];assert.ok(field,levelType+'.ticket');
 assert.match(main,/TradeLevels\[Level_Count-1\]\.ticket\s*=\s*LastOrderTicket;/);
 assert.match(main,/else if\(LastOrderTicket>0 && PositionSelectByTicket\(\(ulong\)LastOrderTicket\)\)/);
 return {globals,orderCasts,dealCasts,field};
}
const INT_MAX=2147483647n;
const TICKETS=[1n,2121259469n,INT_MAX,INT_MAX+1n,INT_MAX+26200000n,4294967296n+5n,9000000000000000000n];
function replay(w,ticket){
 const failures=[];
 for(const cast of w.orderCasts){
  assert.ok(WIDTH[cast]&&WIDTH[w.globals.LastOrderTicket]&&WIDTH[w.field],'known widths');
  const stored=WIDTH[w.globals.LastOrderTicket](WIDTH[cast](ticket));
  const level=WIDTH[w.field](stored);
  if(!(stored>0n))failures.push('the partial-fill readback skips ticket '+ticket+' (LastOrderTicket='+stored+')');
  if(WIDTH.ulong(stored)!==ticket)failures.push('PositionSelectByTicket gets '+WIDTH.ulong(stored)+' for '+ticket);
  if(WIDTH.ulong(level)!==ticket)failures.push('the level keeps '+WIDTH.ulong(level)+' for '+ticket);
 }
 for(const cast of w.dealCasts){
  const stored=WIDTH[w.globals.LastDealTicket](WIDTH[cast](ticket));
  if(WIDTH.ulong(stored)!==ticket)failures.push('LastDealTicket keeps '+stored+' for '+ticket);
 }
 return failures;
}
const tree=widths(readTree);
assert.deepEqual(tree.globals,{LastOrderTicket:'long',LastDealTicket:'long',LastBuyTicket:'long',LastSellTicket:'long'});
for(const ticket of TICKETS) assert.deepEqual(replay(tree,ticket),[],'ticket '+ticket);
passed++;

// 3. The same fixture catches B47: tickets up to INT_MAX survive, the first one above it does not.
const b47=widths(readB47);
for(const ticket of TICKETS.filter(t=>t<=INT_MAX)) assert.deepEqual(replay(b47,ticket),[],'B47 keeps ticket '+ticket);
const lost=replay(b47,INT_MAX+1n);
assert.ok(lost.some(x=>x.startsWith('PositionSelectByTicket gets 18446744071562067968')),'B47 selects the wrapped ticket\n'+lost.join('\n'));
assert.ok(lost.some(x=>x.startsWith('the partial-fill readback skips')),'B47 skips the readback');
passed++;

console.log('ticket_width: '+passed+' checks passed');
