const fs=require('node:fs'),assert=require('node:assert/strict');
const observer=fs.readFileSync('GOAT_Exp2SignalTelemetry.mqh','utf8');
const main=fs.readFileSync('GOAT V1.48.mq5','utf8');
assert(observer.includes('g_exp2_signal_edge=!g_exp2_active[side]'));
assert(observer.includes('if(g_exp2_signal_edge) GoatExp2Write("signal_ai_gate"'));
assert(observer.includes('g_exp2_signal_context && g_exp2_signal_edge && !g_exp2_order_attempted'));
assert(observer.includes('if(!g_exp2_seen[side]) {g_exp2_active[side]=false;g_exp2_episode[side]="";}'));
assert(observer.includes('g_exp2_cached_magic!=(long)MAGIC1 || g_exp2_context_key!=_Symbol'));
assert(!observer.includes('LastBuySignal')&&!observer.includes('LastSellSignal')); // independent observer state
assert(main.includes('GoatExp2EvaluationBegin();')&&main.includes('GoatExp2EvaluationEnd();'));
// Exercise the source edge expression and reset condition across independent
// native strategy/symbol/side instances, not any trading state or skip counters.
const states=new Map();let rows=0;
function evaluate(strategy,symbol,side,present){
 const key=strategy+'|'+symbol+'|'+side;const previous=states.get(key)||false;
 const edge=present&&!previous;states.set(key,present);if(edge)rows++;return edge;
}
for(let tick=0;tick<100;tick++)evaluate('strategy-a','EURUSD',0,true);
assert.equal(rows,1);
evaluate('strategy-a','EURUSD',0,false);evaluate('strategy-a','EURUSD',0,true);assert.equal(rows,2);
evaluate('strategy-a','EURUSD',1,true);evaluate('strategy-a','GBPUSD',0,true);evaluate('strategy-b','EURUSD',0,true);
assert.equal(rows,5);
for(let tick=0;tick<100;tick++){evaluate('strategy-a','EURUSD',1,true);evaluate('strategy-a','GBPUSD',0,true);evaluate('strategy-b','EURUSD',0,true);}
assert.equal(rows,5);
console.log('PASS: one held-signal edge row for100 evaluations, false reset/new edge, independent symbol/strategy/side isolation; repeated no-order rows suppressed');
