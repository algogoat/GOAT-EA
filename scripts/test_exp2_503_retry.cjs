const fs=require('node:fs'),assert=require('node:assert/strict');
const wire=fs.readFileSync('GOATAIWireV2.mqh','utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
const cooldown=wire.match(/ulong refresh_ms=([^;]+);/)[1].replace(/\(ulong\)/g,'').replace('MathMax','Math.max').replace('AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO','mode===0');
const effectiveCooldown=Function('m_retry_after_503','Bias_RegenerateMinutes','mode','return '+cooldown);
assert.equal(effectiveCooldown(true,10,0),60000);assert.equal(effectiveCooldown(false,10,0),600000);
for(const mode of [1,2]) assert.equal(effectiveCooldown(true,10,mode),600000); // real/contest unchanged, including switch from demo
const due=(status,elapsed)=>elapsed>=effectiveCooldown(status===503,10,0);
assert.equal(due(503,59999),false);assert.equal(due(503,60000),true);
for(const status of [1003,401,403,429,500,502,-1,200]) {
 assert.equal(due(status,60000),false);assert.equal(due(status,599999),false);assert.equal(due(status,600000),true);
}
assert.equal((wire.match(/m_retry_after_503=false;/g)||[]).length,3); // constructor, Reset, every attempt
assert(wire.includes('m_retry_after_503=(response==503 && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO);'));
const refresh=wire.slice(wire.indexOf('bool CGOATAIWireV2::Refresh('));
assert(refresh.indexOf('GOATResetWireV2State(m_state,"REQUEST_FAILED")')<refresh.indexOf('WebRequest('));
assert(refresh.indexOf('m_last_attempt_tick=finished;')<refresh.indexOf('m_retry_after_503=(response==503 && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO);'));
assert(wire.includes('now_tick<m_last_attempt_tick')&&wire.includes('authoritative_now>=m_valid_until_ms'));
assert(wire.includes('return state.verified;')); // fail-closed, never promote failed cached state
console.log('PASS: extracted503-only60s cooldown, allnon50310min cases, reset/finish timestamp, clock reset/verifiedexpiry and no last-lean fallback');
