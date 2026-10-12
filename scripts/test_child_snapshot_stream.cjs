// B44 item 3 (goatai#2350): the child snapshot audit reads a saved template line by line with no whole-file cap
// and keeps only the chart's one <expert> block. Before B44 GoatChildAuditRead refused a template over 8 MB and
// GoatChildAuditTemplate one over 65,536 lines or 4,000,000 characters, so a child whose chart carried many objects
// or indicators was never adopted (a silent child_unmatched). This runs the production GoatChildAuditExpertBlock,
// GoatChildAuditTemplate and GoatChildAuditMaps after a syntax-only MQL-to-JS conversion. Native ChartSaveTemplate,
// FileOpen and FileReadArray are not exercised here.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=process.env.GOAT_EA_ROOT||path.join(__dirname,'..');
const source=fs.readFileSync(path.join(ROOT,'GOATPortfolioChildAudit.mqh'),'utf8').replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
let passed=0;const ok=()=>passed++;

// The pure parser (as test_portfolio_child_audit.cjs converts it) plus the B44 streaming reader.
function convert(text){
 return text.replace(/^#.*$/gm,'').replace(/\b(?:bool|string|int) (Goat\w+)\(/g,'function $1(')
  .replace(/\bconst (?:string|int) /g,'').replace(/\bstring &(\w+)\[\]/g,'$1')
  .replace(/\bstring (\w+)\[\d+\]=\{([^}]+)\}/g,'let $1=[$2]')
  .replace(/\b(?:string|int|bool|ushort|uchar) /g,'let ').replace(/\b(\w+)\[\](?=[,;])/g,'$1=[]')
  .replace(/'([^'\\]|\\[nr])'/g,(_,c)=>String(c==='\\n'?10:c==='\\r'?13:c.charCodeAt(0)))
  .replace(/\(ushort\)/g,'')
  .replace(/StringTrimLeft\((\w+)\)/g,'$1=$1.trimStart()').replace(/StringTrimRight\((\w+)\)/g,'$1=$1.trimEnd()')
  .replace(/StringToLower\((\w+)\)/g,'$1=$1.toLowerCase()')
  .replace(/StringReplace\((\w+),([^;]+)\)/g,'$1=$1.replaceAll($2)')
  .replace(/function ([^(]+)\(([^)]*)\)/g,(_,name,args)=>'function '+name+'('+args.replace(/\blet /g,'').replace(/^void$/,'')+')');
}
const pure=source.slice(0,source.indexOf('bool GoatChildAuditRead('));
const blockStart=source.indexOf('bool GoatChildAuditExpertBlock(');
const blockEnd=source.indexOf('// One saved-template snapshot of a chart');
assert.ok(blockStart>0 && blockEnd>blockStart,'GoatChildAuditExpertBlock present');
let block=source.slice(blockStart,blockEnd);
assert.equal((block.match(/\bbody=/g)||[]).length,2);
block=block.replace('bool GoatChildAuditExpertBlock(const uchar &bytes[],const int total,string &body,string &refusal)','function GoatChildAuditExpertBlock(bytes,total,out)')
 .replace(/\bbody=/g,'out.body=').replace(/\brefusal=/g,'out.refusal=');
const api={StringLen:s=>s.length,StringSubstr:(s,a,n)=>n===undefined?s.slice(a):s.slice(a,a+n),
 StringFind:(s,q)=>s.indexOf(q),StringGetCharacter:(s,i)=>s.charCodeAt(i),ArraySize:a=>a.length,
 ArrayResize:(a,n)=>{a.length=n;return n;},StringSplit:(s,c,out)=>{out.splice(0,out.length,...s.split(String.fromCharCode(c)));return out.length;},
 TerminalInfoString:()=>'C:\\Fixture',TERMINAL_DATA_PATH:1,GOATIsLowerHex:(v,n)=>typeof v==='string'&&v.length===n&&/^[0-9a-f]+$/.test(v),
 GoatApplyAILaunchPolicy:body=>body,CP_UTF8:65001,WHOLE_ARRAY:-1,
 ShortArrayToString:(u,start,count)=>{let s='';for(let i=start;i<start+count;i+=8192) s+=String.fromCharCode(...u.slice(i,Math.min(i+8192,start+count)));return s;},
 CharArrayToString:(b,start,count)=>Buffer.from(b.subarray(start,start+count)).toString('utf8'),
 StringToCharArray:(s,out)=>{const b=Buffer.from(s,'utf8');out.length=0;for(const x of b)out.push(x);out.push(0);return b.length+1;}};
vm.createContext(api);vm.runInContext(convert(pure)+'\n'+convert(block),api);
const read=bytes=>{const out={body:'',refusal:''};const accepted=api.GoatChildAuditExpertBlock(bytes,bytes.length,out);return {accepted,...out};};
const u16=text=>Buffer.concat([Buffer.from([255,254]),Buffer.from(text,'utf16le')]);
const u8=text=>Buffer.concat([Buffer.from([239,187,191]),Buffer.from(text,'utf8')]);
const EXPERT='Experts\\GOAT-EA\\GOAT V1.49.ex5';
const SET='EA_Desc=Fixture\nRisk=500\nMode_Bias=1\n';
const INPUTS=SET+'Studio_ReadOnlyMonitor=false\nStudio_MonitorRunPath=\nDashboard_Resume_Saved=false\n';
const expertBlock='<expert>\nname=GOAT V1.49\npath='+EXPERT+'\nexpertmode=5\n<inputs>\n'+INPUTS+'</inputs>\n</expert>\n';
const objects=n=>{let s='';for(let i=0;i<n;i++) s+='<object>\ntype=1\nname=line '+i+'\ndate1=1760000000\nvalue1=1.1'+i+'\n</object>\n';return s;};
const chart=(middle,after='')=>'<chart>\nid=133098787211876843\nsymbol=EURUSD\nperiod_type=0\n'+expertBlock+'<window>\nheight=100\n'+middle+'</window>\n</chart>\n'+after;
const crlf=t=>t.replace(/\n/g,'\r\n');

// 1) A small UTF-16LE CRLF template (MT5's own format) reads to the wrapped expert block, and the audit result is
//    the one the whole-template audit gives.
{const text=crlf(chart(objects(3)));const r=read(u16(text));
 assert.equal(r.accepted,true);assert.equal(r.refusal,'');
 assert.equal(r.body,'<chart>\n'+expertBlock+'</chart>\n','only the <expert> block, wrapped in <chart>');
 assert.equal(api.GoatChildAuditMaps(SET,0,50,2,r.body,EXPERT),true,'the wrapped block passes the audit');
 assert.equal(api.GoatChildAuditMaps(SET,0,50,2,text.replace(/\r/g,''),EXPERT),true,'as the whole template does');
 const changed=read(u16(crlf(chart(objects(3))).replace('Risk=500','Risk=501')));
 assert.equal(api.GoatChildAuditMaps(SET,0,50,2,changed.body,EXPERT),false,'inputs are still compared exactly');ok();}
// 2) Past every old cap: 70,000 objects (over 350,000 lines, over 8 MB as UTF-16) still read, and audit as before.
{const text=crlf(chart(objects(70000)));const bytes=u16(text);
 assert.ok(bytes.length>8000000 && text.split('\n').length>65536,'the fixture is past the old caps');
 const r=read(bytes);assert.equal(r.accepted,true,'no whole-file line or byte cap');
 assert.equal(api.GoatChildAuditMaps(SET,0,50,2,r.body,EXPERT),true);
 assert.equal(api.GoatChildAuditMaps(SET,0,50,2,text.replace(/\r/g,''),EXPERT),false,'the old whole-template audit refused it');ok();}
// 3) The <expert> block alone over the parser's limits is snapshot_too_large.
{let many='';for(let i=0;i<65600;i++) many+='x'+i+'=1\n';
 const r=read(u16(chart('').replace('<inputs>\n','<inputs>\n'+many)));
 assert.deepEqual([r.accepted,r.refusal,r.body],[false,'snapshot_too_large',''],'an oversized expert block');ok();}
// 4) A NUL unit anywhere is snapshot_nul (UTF-16 and UTF-8), even outside the expert block.
{const text=chart(objects(2));
 assert.deepEqual([read(u16(text.replace('name=line 1','name=li\u0000ne 1'))).refusal,read(u8(text.replace('height=100','height=1\u000000'))).refusal],['snapshot_nul','snapshot_nul']);ok();}
// 5) Structure is still checked over the whole file: anything GoatChildAuditTemplate refused is refused.
for(const [label,text] of [
 ['two experts',chart(expertBlock)],['an expert inside a window',chart(expertBlock).replace(expertBlock,'').replace('<window>\n','<window>\n'+expertBlock)],
 ['no expert',chart('').replace(expertBlock,'')],['text after the chart',chart('','x=1\n')],['a second chart',chart('',chart(''))],
 ['unbalanced tags',chart('<object>\n')],['a mismatched close',chart('<object>\n</window>\n</object>\n')],['a bad tag','<chart>\n'+expertBlock+'<win dow>\n</chart>\n'],
 ['an unclosed tag line',chart('<object\n')],['content before the chart','x=1\n'+chart('')],['a truncated file',chart('').slice(0,-9)]]){
 const r=read(u16(text));assert.deepEqual([r.accepted,r.refusal,r.body],[false,'snapshot_unreadable',''],label);ok();
}
// 6) Encodings: UTF-8 with or without BOM reads; invalid UTF-8 and an odd UTF-16 length do not.
{const text=chart(objects(1));
 assert.equal(read(u8(text)).accepted,true);assert.equal(read(Buffer.from(text,'utf8')).accepted,true);
 const bad=Buffer.from(text,'utf8');bad[bad.indexOf('height')]=0xC3;
 assert.equal(read(bad).accepted,false,'invalid UTF-8');
 assert.equal(read(Buffer.concat([u16(text),Buffer.from([65])])).accepted,false,'odd UTF-16 length');
 assert.equal(read(Buffer.alloc(0)).accepted,false,'empty');ok();}
// 7) Wiring: one ChartSaveTemplate, the snapshot read goes through the streaming reader, the whole-file reader only
//    serves the frozen SET, and adoption names each refusal (GOATPortfolioSetupControl.mqh).
{assert.equal((source.match(/ChartSaveTemplate\(/g)||[]).length,1);
 assert.match(source,/snapshot_read=GoatChildAuditExpertBlock\(bytes,\(int\)size,snapshot,GoatChildSnapshotRefusal\);/);
 assert.match(source,/if\(size>GOAT_CHILD_SNAPSHOT_MAX_BYTES\) GoatChildSnapshotRefusal="snapshot_too_large";/);
 assert.equal((source.match(/GoatChildAuditRead\(/g)||[]).length,2,'GoatChildAuditRead: its definition and the SET source only');
 const setup=fs.readFileSync(path.join(ROOT,'GOATPortfolioSetupControl.mqh'),'utf8');
 assert.equal((setup.match(/GoatAdoptNote\(GoatChildSnapshotRefusal,/g)||[]).length,2,'both adoption paths name the refusal');ok();}
console.log(JSON.stringify({passed,nativeTemplateIo:false}));
