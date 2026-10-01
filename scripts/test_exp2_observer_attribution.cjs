const fs=require('node:fs'),assert=require('node:assert/strict');
const observer=fs.readFileSync('GOAT_Exp2SignalTelemetry.mqh','utf8');
const main=fs.readFileSync('GOAT V1.48.mq5','utf8');
const wire=fs.readFileSync('GOATAIWireV2.mqh','utf8').replace(/\r\n/g,'\n');
assert(observer.includes('g_exp2_consumed_wire.actionable')&&observer.includes('signed_probability_percent>0'));
assert(observer.includes('rescue_suppressed?"BIAS_RESCUE_ACTIVE"'));
assert(observer.includes('g_exp2_combined_bias_allowed=bias_allowed;'));
assert(observer.includes('"combined_bias_allowed"'));
assert(observer.includes('kind=="signal_ai_gate"?(g_exp2_combined_bias_allowed?"true":"false")'));
const mismatch=(permission,combined)=> (permission==='TAKE')!==combined;
assert(mismatch('TAKE',false));assert(mismatch('VETO',true));
assert(!mismatch('TAKE',true));assert(!mismatch('VETO',false));
assert(main.includes('Sequence_New_News,Seq_Buy.BiasRescueActive')&&main.includes('Sequence_New_News,Seq_Sell.BiasRescueActive'));
// A valid favorable AI state is TAKE even when non-AI rescue suppresses entry;
// contrary AI is still VETO, with rescue separately recorded as a confounder.
const permission=(applied,verified,available,actionable,signed,side)=>!applied?'TAKE':
 verified&&available&&actionable&&(side===0?signed>0:signed<0)?'TAKE':verified&&available?'VETO':'NO_WIRE';
assert.equal(permission(true,true,true,true,70,0),'TAKE');
assert.equal(permission(true,true,true,true,-70,0),'VETO');
assert.equal(permission(true,true,true,false,45,0),'VETO');
assert.equal(permission(true,false,false,false,0,0),'NO_WIRE');
assert.equal(permission(false,false,false,false,0,0),'TAKE');
// Candidate retry code is preprocessed away without this entrypoint-only define.
const historical=wire.replace(/\s*#ifdef GOAT_EXP2_DEMO_503_NEXT_MINUTE\n([\s\S]*?)\n\s*#endif/g,(_,body)=>body.includes('\n#else\n')?body.split('\n#else\n')[1]:'');
assert(!historical.includes('m_retry_after_503'));
assert(historical.includes('ulong refresh_ms=(ulong)MathMax(1,Bias_RegenerateMinutes)*60000;'));
assert(main.includes('#define GOAT_EXP2_DEMO_503_NEXT_MINUTE 1'));
console.log('PASS: consumed-AI decision versus distinct non-AI rescue marker; historical entrypoints preprocess to original10min retry');
