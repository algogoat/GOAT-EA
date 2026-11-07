// Every preregistered D1 hunt design SET inits on the tree's OnInit (the method fix after GOAT-EA#296: B49b F6's
// unconditional RiskperSeq refusal refused every hunt single at B52's a98ea439, Codex 4502334956, and two independent
// reads of the merge did not see it). The 11 SETs of goatai docs/preregs/d1-hunt-20261107 (5 grid, 6 single) are fixtures
// here, byte-identical (scripts/fixtures/hunt-d1, -text in .gitattributes; each sha256 is the prereg's
// SET-SHA256SUMS.sha256). Each one runs scripts/b50_tick_harness.cjs's real OnInit slices (the session table, the sizes,
// the lot chain with every input refusal B49b, B50, B51 and B52 added, B50's block) in the tester:
// - at the SET's own values;
// - for each optimized axis (Y), at the range's start and at its stop, every other input at the SET's value.
// Every one must init. scripts/test_b52_review_mutations.cjs runs this file on an entrypoint whose F6 refusal is unconditional
// again (GOAT_EA_MAIN): it must fail.
// What it does not prove: OnInit's licence, dashboard and file paths (not in the harness), or a live chart's refusals.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const H=require('./b50_tick_harness.cjs');
const DIR=path.join(__dirname,'fixtures','hunt-d1');
// goatai docs/preregs/d1-hunt-20261107/SET-SHA256SUMS.sha256 (prereg goatai#2765), verbatim.
const PREREG={
 '01-thrush-rr-d1veto.set':'92c947fbec6f49d378deb4924fe4adfdc6f75dfb82aa9edbc00939ceb03d89ae',
 '02-thrush-rr-d1veto-single.set':'25ea6949c75b9146567ec4c4171db47376861838253612e891bbdbc41c4828e3',
 '03-merganser-ct-d1veto.set':'c3902433734b630df706c5b854b5bc4d35ad5128adffd3fe4e75c202526d82ea',
 '04-merganser-ct-d1veto-single.set':'17f73d26ed53667a719e5669b85ae66023910c4aff8c742880248b10ae7af4ac',
 '05-dotterel-rr-d1regime.set':'eb1bbdf117651df720dcbd462c11da80a8b1d4f6b5f99921092a63e47ceb4696',
 '06-dotterel-rr-d1regime-single.set':'3f7638837669a4ba1eae1cd3261e8cf217d6c1385135c824e54e6cd829b36df3',
 '07-dipper-tp-d1trend.set':'5949a23a781d69ad9e791ecb237fbba7f8a82938e4a7901ce214b6ba4c80ebd6',
 '08-dipper-tp-d1trend-single.set':'faa16b5073c21f59fd095e2a26b6ed71271535c98e6b5c987440ec04f7e0e93d',
 '09-bittern-ct-d1stretch.set':'182a90702b5ab9644d7c24fe92d965540f3f1d71d8844520ebe31f7037cf1a12',
 '10-bittern-ct-d1stretch-single.set':'190aa90b5c9234e3a83e99be63fd4a9589d849e0297f81650d1777efb5777d1c',
 '11-dipper-tp-d1trend-single-plain.set':'82de4ccfa4e841f1c5e5639786aece7b06d729d02b7a85bc4a69c6b388d7e032',
};
// A SET as MT5 writes it (UTF-16LE with a BOM): name=value, or name=value||start||step||stop||Y/N for an optimizable input.
function parse(file){
 const buf=fs.readFileSync(file);
 assert.deepEqual([...buf.subarray(0,2)],[0xFF,0xFE],path.basename(file)+': UTF-16LE with a BOM, as MT5 writes it');
 const rows=[];
 for(const line of buf.subarray(2).toString('utf16le').split(/\r?\n/)){
  if(!line||line.startsWith(';'))continue;
  const e=line.indexOf('=');if(e<1)continue;
  const f=line.slice(e+1).split('||');
  rows.push({name:line.slice(0,e),cur:f[0],start:f[1],stop:f[3],opt:f[4]==='Y'});
 }
 return rows;
}
const value=v=>v==='true'?true:v==='false'?false:(v!==''&&!isNaN(Number(v))?Number(v):v);
const files=H.loadSources();   // the working tree (GOAT_EA_MAIN: a mutated entrypoint)
const C=H.compile(files);
const INPUTS=new Set(C.globals.filter(g=>g.input).map(g=>g.name));
const ENGINE_SINGLE=C.unit.constants.get('Engine_Single'),RISK_PER_SEQ=C.unit.constants.get('RiskperSeq');
assert.equal(typeof ENGINE_SINGLE,'number');assert.equal(typeof RISK_PER_SEQ,'number');
function init(inputs){
 try{H.build({files},{tester:true,inputs,indicator:()=>undefined});return 'ok';}
 catch(e){return e.initCode!==undefined?'OnInit refused: code '+e.initCode:'error: '+String(e.message).split('\n')[0];}
}

assert.deepEqual(fs.readdirSync(DIR).sort(),Object.keys(PREREG).sort(),'the fixtures are exactly the 11 preregistered SETs');
const failures=[],summary={};let runs=0,singles=0;
for(const [name,expected] of Object.entries(PREREG)){
 const file=path.join(DIR,name);
 assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),expected,name+': byte-identical to the prereg');
 const rows=parse(file);
 const unknown=rows.filter(r=>!INPUTS.has(r.name)).map(r=>r.name);
 assert.deepEqual(unknown,[],name+': every SET line is an input of this source');
 const base=Object.fromEntries(rows.map(r=>[r.name,value(r.cur)]));
 const single=base.Engine_Mode===ENGINE_SINGLE;if(single)singles++;
 assert.equal(base.Mode_Lots,RISK_PER_SEQ,name+': RiskperSeq (prereg section 2)');
 const results=[['current values',init(base)]];
 for(const r of rows.filter(r=>r.opt)) for(const [end,v] of [['start',r.start],['stop',r.stop]])
  results.push([r.name+'='+v+' ('+end+')',init({...base,[r.name]:value(v)})]);
 runs+=results.length;
 for(const [what,result] of results) if(result!=='ok') failures.push(name+' at '+what+': '+result);
 summary[name]={engine:single?'single':'grid',Max_Seq_Trades:base.Max_Seq_Trades,inits:results.length};
}
assert.equal(singles,6,'6 single and 5 grid designs');
assert.deepEqual(failures,[],'every hunt SET inits at its values and at each axis\'s start and stop');
console.log(JSON.stringify({passed:Object.keys(PREREG).length,test:'hunt_sets_init',inits:runs,sets:summary}));
