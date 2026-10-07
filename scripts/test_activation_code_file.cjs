// LC36: the EA shares the connection code it already shows with GOAT on this PC through
// GOAT/activation-code-<data folder>.json (Common Files), so `studio pairing-code` reads it
// without a screenshot. Runs the actual MQL functions, translated, against a fake terminal.
// Source semantics only: not MQL runtime or native terminal proof.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync(path.join(__dirname, '..', 'GOATEADeviceActivation.mqh'), 'utf8');
const main = fs.readFileSync(path.join(__dirname, '..', 'GOAT V1.49.mq5'), 'utf8');
function extract(name) {
  const at = src.search(new RegExp('^(?:bool|void|string) ' + name + '\\(', 'm'));
  assert.ok(at >= 0, name + ' is defined');
  const brace = src.indexOf('{', at);
  let depth = 1, i = brace + 1;
  // Braces inside string and character literals do not count.
  for (let quote = null; depth; i++) {
    const ch = src[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch; else if (ch === '{') depth++; else if (ch === '}') depth--;
  }
  return src.slice(at, i)
    .replace(/^(?:bool|void|string) (\w+)\(void\)/, 'function $1()')
    .replace(/^(?:bool|void|string) (\w+)\(const string (\w+)\)/, 'function $1($2)')
    .replace(/\b(?:string|long|int|ushort|ulong|uint|bool) (\w+)=/g, 'let $1=')
    .replace(/,body=""/g, ';let body=""')
    .replace(/uchar bytes\[\];/g, 'let bytes=[];')
    .replace(/\((?:long|int|uint)\)/g, '')
    .replace(/'(\\?.)'/g, (_, ch) => String((ch.length === 2 ? ch[1] : ch).charCodeAt(0)));
}
const names = ['GOATDeviceActivationCodePath', 'GOATDeviceActivationCodeQuote', 'GOATDeviceActivationCodeShareable',
  'GOATDeviceActivationShareCode', 'GOATDeviceActivationWithdrawCode', 'GOATDeviceActivationSyncCode'];
const code = names.map(extract).join('\n');
const NOW = 1_800_000_000;
function terminal(state = {}) {
  const files = new Map(), deleted = [];
  let handle = 0; const open = new Map();
  const c = {
    Key: 'GOAT', FILE_COMMON: 4096, FILE_WRITE: 2, FILE_READ: 1, FILE_TXT: 16, FILE_ANSI: 32, FILE_BIN: 4, FILE_REWRITE: 512,
    INVALID_HANDLE: -1, CP_UTF8: 65001, MQL_TESTER: 6, ACCOUNT_TRADE_MODE: 32, ACCOUNT_TRADE_MODE_DEMO: 0, ACCOUNT_LOGIN: 0, ACCOUNT_SERVER: 1,
    GOAT_DEVICE_ACTIVATION_PENDING: 2,
    g_GOATDeviceActivationCodeShared: false, g_GOATDeviceActivationState: 2, g_GOATDeviceActivationUserCode: 'ABCD-EF23',
    g_GOATDeviceActivationAccountId: '3000107825', g_GOATDeviceActivationServer: 'Darwinex-Demo', g_GOATDeviceActivationBuildId: 'V1.49-LOCAL-PAIRING-CODE-36',
    g_GOATDeviceActivationId: 'c'.repeat(32), g_GOATDeviceActivationExpiresAtMs: (NOW + 600) * 1000,
    g_GOATDeviceActivationCandidate: 'goat_ea_' + 'x'.repeat(64),
    ...state,
    GoatTerminalToken: () => 'T2DATA', TimeGMT: () => NOW, GetTickCount64: () => 99, ChartID: () => state.chart ?? 7,
    MQLInfoInteger: () => (state.tester ? 1 : 0), AccountInfoInteger: key => key === 32 ? (state.real ? 2 : 0) : Number(state.login ?? 3000107825),
    AccountInfoString: () => state.server ?? 'Darwinex-Demo', IntegerToString: String, StringLen: s => s.length,
    StringGetCharacter: (s, i) => s.charCodeAt(i), ShortToString: n => String.fromCharCode(n),
    StringFormat: (_f, n) => '\\u' + n.toString(16).padStart(4, '0'), StringFind: (s, v) => s.indexOf(v),
    GOATIsSafeId: (v, min, max) => typeof v === 'string' && v.length >= min && v.length <= max && /^[A-Za-z0-9_-]+$/.test(v),
    FolderCreate: () => true, FileIsExist: name => files.has(name),
    FileOpen: (name, flags) => {
      if (state.unwritable && flags & 2) return -1;
      if (flags & 1 && !files.has(name)) return -1;
      open.set(++handle, { name, text: flags & 2 ? '' : files.get(name) }); return handle;
    },
    FileWriteString: (h, text) => { open.get(h).text += text; return text.length; },
    FileFlush: () => {}, FileClose: h => { const f = open.get(h); if (f && f.name.endsWith('.pending')) files.set(f.name, f.text); open.delete(h); },
    FileMove: (from, _a, to) => { files.set(to, files.get(from)); files.delete(from); return true; },
    FileDelete: name => { deleted.push(name); files.delete(name); return true; },
    FileSize: h => Buffer.byteLength(open.get(h).text), ArrayResize: (arr, n) => n,
    FileReadArray: (h, arr) => { const bytes = Buffer.from(open.get(h).text); arr.push(...bytes); return bytes.length; },
    CharArrayToString: arr => Buffer.from(arr).toString('utf8'),
  };
  vm.createContext(c); vm.runInContext(code, c);
  return { c, files, deleted };
}
const PATH = 'GOAT\\activation-code-T2DATA.json';
let checks = 0; const check = fn => { fn(); checks++; };

// 1. What is shared: exactly the code MT5 shows, bound to login, server, build and request; never the credential.
check(() => {
  const t = terminal();
  t.c.GOATDeviceActivationShareCode();
  const record = JSON.parse(t.files.get(PATH));
  assert.deepEqual(Object.keys(record), ['schema', 'accountId', 'server', 'buildId', 'activationId', 'userCode', 'expiresAtMs', 'observedAtUtc', 'chart']);
  assert.deepEqual(record, { schema: 1, accountId: '3000107825', server: 'Darwinex-Demo', buildId: 'V1.49-LOCAL-PAIRING-CODE-36', activationId: 'c'.repeat(32),
    userCode: 'ABCD-EF23', expiresAtMs: (NOW + 600) * 1000, observedAtUtc: NOW, chart: 7 });
  assert.equal(t.files.get(PATH).includes('goat_ea_'), false, 'the credential candidate never leaves the EA');
  assert.equal([...t.files.keys()].some(name => name.endsWith('.pending')), false, 'written atomically through a temporary');
  assert.equal(t.c.g_GOATDeviceActivationCodeShared, true);
});
// 2. Nothing is shared unless it is the pending demo request MT5 shows for this login and server.
for (const [label, state] of [['not pending', { g_GOATDeviceActivationState: 1 }], ['blocked', { g_GOATDeviceActivationState: 4 }],
  ['malformed code', { g_GOATDeviceActivationUserCode: 'ABCD-EF2' }], ['lowercase code', { g_GOATDeviceActivationUserCode: 'abcd-ef23' }],
  ['ambiguous characters', { g_GOATDeviceActivationUserCode: 'ABCD-EF10' }], ['no code', { g_GOATDeviceActivationUserCode: '' }],
  ['real money', { real: true }], ['strategy tester', { tester: true }], ['another login', { login: 3000000001 }],
  ['another server', { server: 'Darwinex-Live' }], ['unsafe activation', { g_GOATDeviceActivationId: 'c'.repeat(31) + '"' }],
  ['expired', { g_GOATDeviceActivationExpiresAtMs: NOW * 1000 }], ['too far ahead', { g_GOATDeviceActivationExpiresAtMs: (NOW + 901) * 1000 }]])
  check(() => { const t = terminal(state); t.c.GOATDeviceActivationShareCode(); assert.equal(t.files.size, 0, label); assert.equal(t.c.g_GOATDeviceActivationCodeShared, false, label); });
// 3. A failed write leaves nothing behind and claims nothing.
check(() => { const t = terminal({ unwritable: true }); t.c.GOATDeviceActivationShareCode(); assert.equal(t.files.size, 0); assert.equal(t.c.g_GOATDeviceActivationCodeShared, false); });
// 4. The server name is JSON-quoted, so a broker name cannot break or extend the record.
check(() => { const t = terminal({ server: 'Demo "x"\\é', g_GOATDeviceActivationServer: 'Demo "x"\\é' }); t.c.GOATDeviceActivationShareCode();
  assert.equal(JSON.parse(t.files.get(PATH)).server, 'Demo "x"\\é'); });
// 5. Withdrawal: the moment the code is no longer shown (expired, cleared, approved) the record goes; only this chart's.
for (const change of [{ g_GOATDeviceActivationUserCode: '' }, { g_GOATDeviceActivationState: 3 }, { g_GOATDeviceActivationExpiresAtMs: NOW * 1000 - 1 }])
  check(() => { const t = terminal(); t.c.GOATDeviceActivationShareCode(); Object.assign(t.c, change); t.c.GOATDeviceActivationSyncCode();
    assert.equal(t.files.has(PATH), false, JSON.stringify(change)); assert.equal(t.c.g_GOATDeviceActivationCodeShared, false); });
check(() => { const t = terminal(); t.c.GOATDeviceActivationShareCode(); t.c.GOATDeviceActivationSyncCode(); assert.equal(t.files.has(PATH), true, 'a shown code stays shared'); });
check(() => {
  const t = terminal(); t.c.GOATDeviceActivationShareCode();
  // Another chart of this terminal shared a newer code: ours is withdrawn without touching theirs.
  t.files.set(PATH, t.files.get(PATH).replace('"chart":7}', '"chart":8}'));
  t.c.GOATDeviceActivationWithdrawCode();
  assert.equal(t.files.has(PATH), true); assert.deepEqual(t.deleted, []);
});
check(() => { const t = terminal(); t.files.set(PATH, '{"chart":7}'); t.c.GOATDeviceActivationWithdrawCode(); assert.equal(t.files.has(PATH), true, 'a chart that shared nothing deletes nothing'); });
// 5b. B38 (Codex P2s on #125): the file is reconciled every tick, never only once.
check(() => {
  // The first write failed: the next tick shares the code MT5 still shows.
  const state = { unwritable: true }; const t = terminal(state);
  t.c.GOATDeviceActivationShareCode(); assert.equal(t.files.has(PATH), false);
  state.unwritable = false; t.c.GOATDeviceActivationSyncCode();
  assert.equal(JSON.parse(t.files.get(PATH)).chart, 7); assert.equal(t.c.g_GOATDeviceActivationCodeShared, true);
});
check(() => {
  // Another chart replaced our record and then withdrew its own: ours comes back.
  const t = terminal(); t.c.GOATDeviceActivationShareCode(); t.files.delete(PATH);
  t.c.GOATDeviceActivationSyncCode();
  assert.equal(JSON.parse(t.files.get(PATH)).userCode, 'ABCD-EF23');
});
check(() => {
  // A newer record another chart shared is left alone while it is there.
  const t = terminal(); t.c.GOATDeviceActivationShareCode();
  const theirs = t.files.get(PATH).replace('"chart":7}', '"chart":8}'); t.files.set(PATH, theirs);
  t.c.GOATDeviceActivationSyncCode(); t.c.GOATDeviceActivationSyncCode();
  assert.equal(t.files.get(PATH), theirs);
});
check(() => {
  // Nothing shareable and nothing shared: a tick writes nothing.
  const t = terminal({ real: true }); t.c.GOATDeviceActivationSyncCode();
  assert.equal(t.files.size, 0); assert.equal(t.c.g_GOATDeviceActivationCodeShared, false);
});
// 6. Wiring in the EA: shared right after the code is shown; withdrawn on scrub, approval/reload and monitor close; synced every tick.
const body = name => { const at = src.indexOf(name); return src.slice(at, src.indexOf('\n  }\r\n', at)); };
check(() => assert.match(body('bool GOATDeviceActivationRequestStart(void)'), /GOATDeviceActivationShowCode\(user_code,verification_url\);\r?\n   GOATDeviceActivationShareCode\(\);/));
check(() => assert.match(body('void GOATDeviceActivationScrub(void)'), /^void GOATDeviceActivationScrub\(void\)\r?\n  \{\r?\n   GOATDeviceActivationWithdrawCode\(\);/));
check(() => assert.match(body('void GOATDeviceActivationRequestReload(void)'), /g_GOATDeviceActivationUserCode="";\r?\n   GOATDeviceActivationWithdrawCode\(\);/));
check(() => { const timer = body('void GOATDeviceActivationTimer(void)');
  assert.ok(timer.indexOf('GOATDeviceActivationSyncCode();') > 0 && timer.indexOf('GOATDeviceActivationSyncCode();') < timer.indexOf('if(!GOATDeviceActivationOnly()'), 'synced before any early return'); });
check(() => assert.match(main, /if\(g_GoatStudioReadOnlyMonitor\)\r?\n   \{GOATDeviceActivationWithdrawCode\(\);TesterDialog\.Destroy\(reason\);EventKillTimer\(\);return;\}/));
// 7. The operational status file still never carries a code, and no code is ever printed.
check(() => { const status = src.slice(src.indexOf('void GOATDeviceActivationStatus'), src.indexOf('int GOATDeviceActivationRetrySeconds'));
  for (const secret of ['UserCode', 'user_code', 'Candidate']) assert.equal(status.includes(secret), false, secret); });
check(() => { for (const line of src.split('\n').filter(text => /\bPrint(Format)?\(/.test(text))) assert.equal(/UserCode|user_code/.test(line), false, line); });
check(() => assert.match(main, /#define   GOAT_BUILD_ID "V1\.49-BETA17-41\.3"/));
console.log(`test_activation_code_file: ${checks}/${checks} passed`);
