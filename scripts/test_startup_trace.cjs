'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const trace=fs.readFileSync(path.join(root,'GOATStartupTrace.mqh'),'utf8');
const main=fs.readFileSync(path.join(root,'GOAT V1.47.mq5'),'utf8');
const inputs=fs.readFileSync(path.join(root,'GOAT_Inputs_Definitions.mqh'),'utf8');
const activation=fs.readFileSync(path.join(root,'GOATEADeviceActivation.mqh'),'utf8');
function extract(src,name){const at=src.indexOf(name+'('),start=src.lastIndexOf('\n',at)+1,brace=src.indexOf('{',at);let depth=1,i=brace+1;for(;depth;i++){if(src[i]==='{')depth++;if(src[i]==='}')depth--;}return src.slice(start,i).replace(/^(?:bool|int|void) /,'function ').replace(/\(void\)/g,'()').replace(/const string /g,'').replace(/\b(?:int|string|uint|bool|ulong) (\w+)=/g,'let $1=').replace(/\((?:long|int)\)/g,'');}
const events=[];
const context={g_GoatStartupTracing:true,MQL_TESTER:1,ACCOUNT_TRADE_MODE:2,ACCOUNT_TRADE_MODE_DEMO:0,TERMINAL_TRADE_ALLOWED:3,
 FILE_WRITE:1,FILE_TXT:2,FILE_ANSI:4,FILE_SHARE_READ:8,INVALID_HANDLE:-1,GOAT_BUILD_ID:'R6',Mode_Operation:9,
 MQLInfoInteger:()=>false,AccountInfoInteger:()=>0,TerminalInfoInteger:()=>false,
 ChartID:()=>123,Symbol:()=> 'EURUSD',IntegerToString:String,TimeGMT:()=>100,
 FileOpen:(...v)=>{events.push(['open',...v]);return 7;},FileWriteString:(...v)=>events.push(['write',...v]),
 FileFlush:h=>events.push(['flush',h]),FileClose:h=>events.push(['close',h])};
vm.createContext(context);vm.runInContext(extract(trace,'GoatStartupTrace'),context);
context.GoatStartupTrace('license.hide.before');
assert.deepEqual(events.map(e=>e[0]),['open','write','flush','close']);
assert.equal(events[0][1],'GOAT\\StartupTrace\\R6-123.tsv');
assert.equal(events[1][2],'100\t123\tEURUSD\t9\tlicense.hide.before\r\n');
for(const [key,value] of [['g_GoatStartupTracing',false],['MQLInfoInteger',()=>true],['AccountInfoInteger',()=>2],['TerminalInfoInteger',()=>true]]){
 const old=context[key];context[key]=value;events.length=0;context.GoatStartupTrace('blocked');assert.equal(events.length,0,key);context[key]=old;
}
events.length=0;const open=context.FileOpen;context.FileOpen=()=>-1;context.GoatStartupTrace('open-failed');assert.equal(events.length,0);context.FileOpen=open;
for(const forbidden of ['FILE_COMMON','WebRequest','Print(','token','credentialCandidate','requestHeaders'])assert(!trace.includes(forbidden),forbidden);
assert(main.indexOf('#define GOAT_API_BEARER_FILE')<main.indexOf('#include "GOAT_Inputs_Definitions.mqh"'));
assert.match(inputs,/#ifndef GOAT_API_BEARER_FILE\s+#define\s+GOAT_API_BEARER_FILE "GOAT\\\\Credentials\\\\api-bearer\.token"\s+#endif/);
const destination=JSON.parse(main.match(/#define GOAT_API_BEARER_FILE ("[^\r\n]+")/)[1]);
assert.equal(destination,'GOAT\\Credentials\\api-bearer-r6-diagnostic.token');
assert(activation.includes('string temporary=GOAT_API_BEARER_FILE+".pending";'));
assert(!activation.includes('directory+"\\\\api-bearer.token.pending"'));
const writerEvents=[];
const writer={g_GOATDeviceActivationCandidate:'goat_ea_'+'a'.repeat(64),GOAT_API_BEARER_FILE:destination,
 StringLen:s=>s.length,StringFind:(s,v)=>s.indexOf(v),GOATIsSafeApiBearerToken:()=>true,
 FILE_COMMON:1,FILE_WRITE:2,FILE_TXT:4,FILE_ANSI:8,FILE_REWRITE:16,INVALID_HANDLE:-1,
 FolderCreate:()=>{},FileDelete:p=>writerEvents.push(['delete',p]),FileOpen:p=>{writerEvents.push(['open',p]);return 1;},
 FileWriteString:(_,s)=>s.length,FileFlush:()=>{},FileClose:()=>{},
 FileMove:(a,_,b)=>{writerEvents.push(['move',a,b]);return true;},GOATBuildAuthenticatedRequestHeaders:()=>true};
vm.createContext(writer);vm.runInContext(extract(activation,'GOATDeviceActivationWriteCredential'),writer);
assert.equal(writer.GOATDeviceActivationWriteCredential(),true);
assert.deepEqual(writerEvents,[['delete',destination+'.pending'],['open',destination+'.pending'],['move',destination+'.pending',destination]]);
const reader=extract(inputs,'GOATBuildAuthenticatedRequestHeaders');
assert.equal((reader.match(/FileOpen\(/g)||[]).length,1,'reader has only one destination, no alternate fallback');
assert(reader.includes('FileOpen(GOAT_API_BEARER_FILE,'));
assert(reader.includes('if(handle==INVALID_HANDLE) return false;'));
assert(!reader.includes('api-bearer.token'));
console.log('PASS startup trace production guard, local path, flush/close, open failure, no secrets; isolated production credential writer, guarded legacy default, reader no fallback');
