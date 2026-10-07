// B41.1 no-drift guard (goatai#1885): against B41's source (278ec109), only the deploy path, the
// child audit and the build ID/marker may differ. StartExporter, the trade path in the entrypoint,
// Optimizer.mqh, the input header and every other closure file must be byte-identical once
// normalised (CRLF to LF, BOM dropped, the GOAT_BUILD_ID/GOAT_BUILD_MARKER defines blanked).
// Needs git history containing 278ec109; it reports a skip rather than passing on a shallow clone.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const ROOT=path.join(__dirname,'..'),B41='278ec109be4e95a6e934d4897a91cb28ed71345c';
const ALLOWED=['Dashboard.mqh','GOAT V1.49.mq5','GOATPortfolioChildAudit.mqh','GOATPortfolioSetupControl.mqh'];
const norm=t=>t.replace(/^﻿/,'').replace(/\r\n/g,'\n')
 .replace(/^#define\s+GOAT_BUILD_ID\s+"[^"]*"$/m,'#define GOAT_BUILD_ID ""').replace(/^#define\s+GOAT_BUILD_MARKER\s+"[^"]*"$/m,'#define GOAT_BUILD_MARKER ""');
let old;
try{old=f=>execFileSync('git',['show',B41+':'+f],{cwd:ROOT,maxBuffer:64<<20}).toString('utf8');old('GOAT V1.49.mq5');}
catch(e){
 // CI checks out full history (fetch-depth: 0); a missing base there is a failure, not a skip.
 console.log(JSON.stringify({skipped:'278ec109 not in this clone'}));process.exit(process.env.CI ? 1 : 0);
}
const now=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const identity=JSON.parse(now('candidate-builds/beta17-B41.1/identity.json'));
const b41=JSON.parse(old('candidate-builds/beta17-B41/identity.json'));
assert.deepEqual(Object.keys(identity.sources).sort(),Object.keys(b41.sources).sort(),'same closure as B41');
const differing=Object.keys(identity.sources).filter(f=>norm(now(f))!==norm(old(f))).sort();
assert.deepEqual(differing,['Dashboard.mqh','GOATPortfolioChildAudit.mqh','GOATPortfolioSetupControl.mqh'],
 'normalised, only the deploy path and the child audit differ from B41 (the entrypoint differs only in its build ID and marker)');
for(const f of ALLOWED) assert.ok(identity.sources[f],f);
// StartExporter in full, and the entrypoint's trade-event and tick handlers, are byte-identical.
function body(text,signature){
 const start=text.indexOf(signature);assert.ok(start>=0,signature);
 let i=text.indexOf('{',start),depth=1;for(i++;depth;i++){if(text[i]==='{')depth++;if(text[i]==='}')depth--;}
 return text.slice(start,i);
}
const main=norm(now('GOAT V1.49.mq5')),mainB41=norm(old('GOAT V1.49.mq5'));
let checked=0;
for(const sig of ['bool StartExporter(bool reportMode)','void OnTick(','void OnTradeTransaction(','void GoatTradeTransactionBody(','void OnTimer(void)','void GoatTimerBody(void)']){
 assert.equal(body(main,sig),body(mainB41,sig),sig);checked++;
}
// The trade-path headers are untouched byte for byte, not just normalised.
for(const f of ['GOAT_Inputs_Definitions.mqh','Optimizer.mqh','GOAT_DirectionGuard.mqh','GOAT_DirectionGuardCore.mqh','NewsBiasFilter.mqh','GOATAIWireV2.mqh'])
 assert.equal(identity.sources[f],b41.sources[f],f);
console.log(JSON.stringify({passed:true,differing,identicalEntrypointUnits:checked,base:B41.slice(0,8)}));
