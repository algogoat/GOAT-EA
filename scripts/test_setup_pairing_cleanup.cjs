// Execute native cleanup control flow with an in-memory Common Files fixture.
// This checks source semantics, not MQL filesystem/terminal runtime behavior.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '..', 'GOATSetupControl.mqh'), 'utf8');
function extract(name) {
  const start = source.indexOf(name + '('), brace = source.indexOf('{', start);
  let depth = 1, end = brace + 1;
  for (; depth; end++) { if (source[end] === '{') depth++; if (source[end] === '}') depth--; }
  return source.slice(brace + 1, end - 1)
    .replace(/SGOATJsonToken (\w+)\[\];/g, 'let $1=[];')
    .replace(/string (\w+)\[\]=\{([^}]+)\};/g, 'let $1=[$2];')
    .replace(/\b(?:string|long|int|bool|ushort) /g, 'let ')
    .replace(/\(long\)/g, '')
    .replace(/GOATJsonGet(String|Integer|Boolean)\((\w+),(\w+),0,"([^"]+)",(\w+)\)/g,
      'get($2,"$4","$1",v=>$5=v)')
    .replace(/GoatSetupRead\(([^,]+),(\w+)\)/g, 'read($1,v=>$2=v)')
    .replace(/GoatSetupExpiredPairing\(([^,]+),([^,]+),(\w+)\)/g, 'expired($1,$2,v=>$3=v)')
    .replace(/FileFindFirst\(([^,]+),(\w+),FILE_COMMON\)/g, 'findFirst($1,v=>$2=v)')
    .replace(/FileFindNext\(([^,]+),(\w+)\)/g, 'findNext($1,v=>$2=v)');
}
const id = 'a'.repeat(32), root = 'scope/', account = 123, now = 2000;
const envelope = {schema: 2, id, account, server: 'Demo', directory: 'Terminal', buildId: 'BUILD-TEST', expiresAtUtc: 1500, action: 'pairing'};
const payload = {schema: 1, id, account, server: 'Demo', directory: 'Terminal', buildId: 'BUILD-TEST', observedAtUtc: 1900,
  result: 'pairing_available', connected: true, tradingAllowed: false, activationOnly: true, positions: 0, orders: 0, charts: 1,
  userCode: 'ABCD-2345', activationId: 'x'.repeat(32), responseExpiresAtUtc: 1960, pairingExpiresAtMs: 2200000};
function fixture() {
  const files = new Map([[root + 'request.json', JSON.stringify(envelope)]]), writes = [];
  let names = [], cursor = 0;
  const c = {files, writes, FILE_COMMON: 1, FILE_READ: 2, FILE_WRITE: 4, FILE_BIN: 8, INVALID_HANDLE: -1,
    ACCOUNT_LOGIN: 1, ACCOUNT_SERVER: 2, GOAT_BUILD_ID: 'BUILD-TEST', TimeGMT: () => now,
    AccountInfoInteger: () => account, AccountInfoString: () => 'Demo', GoatSetupDirectoryMatches: x => x === 'Terminal',
    StringLen: x => x.length, StringGetCharacter: (x, i) => x[i], StringFind: (x, y) => x.indexOf(y),
    StringSubstr: (x, i, n) => x.slice(i, n === undefined ? undefined : i + n), IntegerToString: String, GoatSetupQuote: JSON.stringify,
    GOATDeviceActivationValidCode: x => /^[A-Z2-9]{4}-[A-Z2-9]{4}$/.test(x),
    GOATJsonParse: x => { try { JSON.parse(x); return true; } catch { return false; } },
    GOATJsonExactFields: (x, _t, _i, fields) => Object.keys(JSON.parse(x)).sort().join() === [...fields].sort().join(),
    get: (x, field, type, setter) => { const v = JSON.parse(x)[field];
      const okay = type === 'Integer' ? Number.isSafeInteger(v) : typeof v === type.toLowerCase(); if (okay) setter(v); return okay; },
    read: (p, setter) => { if (!files.has(p)) return false; setter(files.get(p)); return true; },
    FileOpen: () => 1, FileClose: () => {}, FileIsExist: p => files.has(p), FileFindClose: () => {},
    GoatSetupWrite: (p, value) => { writes.push(p); if (c.failWrite === p) return false; files.set(p, value); return true; },
    findFirst: (_pattern, setter) => { names = [...files.keys()].filter(p => p.startsWith(root + id + '.json.') && p.endsWith('.pending')).map(p => p.slice(root.length)); cursor = 0;
      if (!names.length) return -1; setter(names[0]); return 1; },
    findNext: (_handle, setter) => { if (++cursor >= names.length) return false; setter(names[cursor]); return true; }};
  vm.createContext(c);
  vm.runInContext('function expired(path,expected_id,setTombstone){let tombstone="";' + extract('GoatSetupExpiredPairing').replace('return true;', 'setTombstone(tombstone);return true;') + '}\nfunction cleanup(root){' + extract('GoatSetupCleanupExpiredPairing') + '}', c);
  return c;
}
let checks = 0;
for (const changes of [{}, {server: 'Foreign'}, {directory: 'Other'}, {buildId: 'Other'}, {account: 456},
  {responseExpiresAtUtc: 2050, observedAtUtc: 1995}, {responseExpiresAtUtc: 1900}, {credentialCandidate: 'never scrub unknown'},
  {activationId: 'bad'}, {orders: 1}, {pairingExpiresAtMs: 999999999999}, {userCode: 'bad'}]) {
  const c = fixture(), p = root + id + '.json'; c.files.set(p, JSON.stringify({...payload, ...changes}));
  const before = c.files.get(p); c.cleanup(root);
  if (!Object.keys(changes).length) {
    const after = JSON.parse(c.files.get(p)); assert.equal(after.result, 'pairing_consumed'); assert(!('userCode' in after)); assert(!('activationId' in after));
  } else assert.equal(c.files.get(p), before);
  checks++;
}
for (const suffix of ['123.pending', '123.456.1.pending']) {
  const c = fixture(), orphan = root + id + '.json.' + suffix; c.files.set(orphan, JSON.stringify(payload)); c.cleanup(root);
  assert.equal(JSON.parse(c.files.get(root + id + '.json')).result, 'pairing_consumed');
  assert.equal(JSON.parse(c.files.get(orphan)).result, 'pairing_consumed');
  assert.equal(c.files.size, 3); checks++;
}
for (const suffix of ['unknown.pending', '123..1.pending', '123.1.pending', '123.1.2.3.pending']) {
  const c = fixture(), orphan = root + id + '.json.' + suffix; c.files.set(orphan, JSON.stringify(payload)); c.cleanup(root);
  assert.equal(c.writes.length, 0); checks++;
}
{
  const c = fixture(), receipt = root + id + '.json', orphan = receipt + '.123.pending';
  c.files.set(orphan, JSON.stringify(payload)); c.failWrite = receipt; c.cleanup(root);
  assert.equal(JSON.parse(c.files.get(orphan)).result, 'pairing_available'); checks++;
}
{
  const c = fixture(), receipt = root + id + '.json', orphan = receipt + '.123.pending';
  c.files.set(receipt, 'unknown evidence'); c.files.set(orphan, JSON.stringify(payload)); c.cleanup(root);
  assert.equal(c.files.get(receipt), 'unknown evidence'); assert.equal(JSON.parse(c.files.get(orphan)).result, 'pairing_consumed'); checks++;
}
{
  const c = fixture(); c.files.set(root + 'request.json', JSON.stringify({...envelope, directory: 'Foreign'}));
  c.files.set(root + id + '.json', JSON.stringify(payload)); c.cleanup(root); assert.equal(c.writes.length, 0); checks++;
}
{
  const c = fixture(); c.FileOpen = () => -1; c.files.set(root + id + '.json', JSON.stringify(payload)); c.cleanup(root); assert.equal(c.writes.length, 0); checks++;
}
{
  const c = fixture(); for (let i = 0; i < 17; i++) c.files.set(root + id + '.json.' + i + '.pending', JSON.stringify(payload));
  c.cleanup(root); assert.equal([...c.files.values()].filter(v => JSON.parse(v).result === 'pairing_available').length, 1); checks++;
}
assert(source.indexOf('GoatSetupCleanupExpiredPairing(root)') < source.indexOf('if(!GoatSetupRead(root+"registration.json"'));
assert(!source.includes('FileDelete('));
const writeBody = extract('GoatSetupWrite');
assert(writeBody.indexOf('FileIsExist(temporary') < writeBody.indexOf('FileOpen(temporary'));
console.log(`PASS ${checks} actual native cleanup source-flow fixtures; no native runtime claim`);
