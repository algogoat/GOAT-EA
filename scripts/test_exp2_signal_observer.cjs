const fs=require('node:fs'),cp=require('node:child_process'),assert=require('node:assert/strict');
const main=fs.readFileSync('GOAT V1.48.mq5','utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const observer=fs.readFileSync('GOAT_Exp2SignalTelemetry.mqh','utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const original=cp.execFileSync('git',['show','14ada7104a82052f7f966da4f7b745890781d553:GOAT V1.48.mq5'],{encoding:'utf8'}).replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
// Removing only passive call lines/include/build stamp must reproduce the exact
// reviewed R2 entry/order/risk/size code. No reordered or recomputed gate passes.
const stripped=main.split('\n').filter(l=>!l.includes('#include "GOAT_Exp2SignalTelemetry.mqh"')&&!/^\s*GoatExp2(?:ConsumedWire|Signal|SignalEnd|OrderResult|Deal|EvaluationBegin|EvaluationEnd)\(/.test(l)).join('\n').replace('V1.48-DASHBOARD-AI-PAIR-R2-OBS1','V1.48-DASHBOARD-AI-PAIR-R2');
assert.equal(stripped,original);
for(const forbidden of ['WebRequest(','GetState(','OrderSend(','HistoryDealSelect(','GlobalVariableSet(','FILE_COMMON','ACCOUNT_LOGIN','ACCOUNT_SERVER']) assert(!observer.includes(forbidden),forbidden);
assert(observer.includes('ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO'));
for(const flag of ['MQL_TESTER','MQL_OPTIMIZATION','MQL_FORWARD']) assert(observer.includes('!MQLInfoInteger('+flag+')'));
assert.equal((main.match(/OrderSend\(request,result\)/g)||[]).length,(original.match(/OrderSend\(request,result\)/g)||[]).length);
assert(main.includes('if(!HistoryDealSelect(trans.deal)) return;\n   GoatExp2Deal(trans.deal);'));
assert(observer.includes('CONTROL_AI_DISABLED')&&observer.includes('!g_exp2_wire_applied?"TAKE"'));
assert(observer.includes('SEND_ACCEPTED_NOT_FILL')&&observer.includes('NO_ORDER_SEND_OBSERVED'));
assert(observer.includes('if(g_exp2_wire_applied && kind=="signal_ai_gate")'));
assert(observer.includes('GOATSha256Utf8((string)MAGIC1,g_exp2_strategy_key)'));
assert(observer.includes('"deal:"+(string)ticket')&&observer.includes('"order:"+(string)order'));
assert(observer.includes('FileSeek(file,0,SEEK_END)')&&observer.includes('FILE_SHARE_READ'));
assert(!/if\s*\([^)]*GoatExp2/.test(main));
console.log('PASS: exact R2 core-code invariance, demo-only/timer-free passive calls, no extra wire/order/history calls, privacy hashes and separated AI permission/execution evidence');
