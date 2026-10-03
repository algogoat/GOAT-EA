// Zero-click demo pairing (goatai#1885): the EA sends its own MT5 readback of trade mode and broker
// server, as `brokerFacts`, on device/start and on the license check. goatai's agent_demo_pairing.js
// lets an agent approve only a demo trade mode on a reviewed demo server, and revokes an
// agent-approved credential when a later license check reports anything else.
// Runs the actual MQL functions and payload expressions, translated, against a fake terminal.
// Source semantics only: not MQL runtime or native terminal proof.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync(path.join(__dirname, '..', 'GOATEADeviceActivation.mqh'), 'utf8');
const main = fs.readFileSync(path.join(__dirname, '..', 'GOAT V1.49.mq5'), 'utf8');
// goatai functions/serve-api/agent_demo_pairing.js BROKER_FACTS_SOURCE and TRADE_MODES.
const BROKER_FACTS_SOURCE = 'ea-device-start';
const TRADE_MODES = ['demo', 'contest', 'real'];

function extract(name) {
  const at = src.search(new RegExp('^string ' + name + '\\(', 'm'));
  assert.ok(at >= 0, name + ' is defined');
  const brace = src.indexOf('{', at);
  let depth = 1, i = brace + 1;
  for (let quote = null; depth; i++) {
    const ch = src[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch; else if (ch === '{') depth++; else if (ch === '}') depth--;
  }
  return src.slice(at, i)
    .replace(/^string (\w+)\(void\)/, 'function $1()')
    .replace(/^string (\w+)\(const string (\w+)\)/, 'function $1($2)')
    .replace(/\b(?:string|long|int|ushort) (\w+)=/g, 'let $1=')
    .replace(/\((?:long|int)\)/g, '')
    .replace(/'(\\?.)'/g, (_, ch) => String((ch.length === 2 ? ch[1] : ch).charCodeAt(0)));
}
const code = ['GOATDeviceActivationCodeQuote', 'GOATBrokerFactsTradeMode', 'GOATBrokerFactsJson'].map(extract).join('\n');

// The statement that builds a request body, as JS: `string json=...;` -> expression.
function payloadExpression(text, startMarker) {
  const at = text.indexOf(startMarker);
  assert.ok(at >= 0, startMarker);
  const end = text.indexOf(';', text.indexOf('}"', at));
  return text.slice(at + startMarker.length, end).replace(/\(string\)(\w+)/g, 'String($1)');
}
const startExpr = payloadExpression(src, 'string json=');
const checkExpr = payloadExpression(main, 'string json_data = ');

function terminal({ mode = 0, server = 'Darwinex-Demo' } = {}) {
  const c = {
    ACCOUNT_TRADE_MODE: 32, ACCOUNT_SERVER: 1, ACCOUNT_TRADE_MODE_DEMO: 0, ACCOUNT_TRADE_MODE_CONTEST: 1, ACCOUNT_TRADE_MODE_REAL: 2,
    AccountInfoInteger: key => { assert.equal(key, 32); return mode; },
    AccountInfoString: key => { assert.equal(key, 1); return server; },
    StringLen: s => s.length, StringGetCharacter: (s, i) => s.charCodeAt(i), ShortToString: n => String.fromCharCode(n),
    StringFormat: (_f, n) => '\\u' + n.toString(16).padStart(4, '0'),
    g_GOATDeviceActivationAccountId: '3000107825', g_GOATDeviceActivationBuildId: 'V1.49-BETA17-39', AccNum: 3000107825,
  };
  vm.createContext(c); vm.runInContext(code, c);
  return c;
}
let checks = 0; const check = fn => { fn(); checks++; };

// 1. Trade mode: MT5's three modes map to the server's words; anything unknown is real, never demo.
for (const [mode, word] of [[0, 'demo'], [1, 'contest'], [2, 'real'], [3, 'real'], [-1, 'real']])
  check(() => assert.equal(terminal({ mode }).GOATBrokerFactsTradeMode(), word, String(mode)));
check(() => assert.ok(TRADE_MODES.includes(terminal({ mode: 7 }).GOATBrokerFactsTradeMode())));

// 2. device/start: accountId, buildId and the nested brokerFacts with the server's source constant.
check(() => {
  const body = JSON.parse(vm.runInContext(startExpr, terminal()));
  assert.deepEqual(Object.keys(body), ['accountId', 'buildId', 'brokerFacts']);
  assert.deepEqual(body, { accountId: '3000107825', buildId: 'V1.49-BETA17-39',
    brokerFacts: { source: BROKER_FACTS_SOURCE, tradeMode: 'demo', server: 'Darwinex-Demo' } });
});
check(() => assert.deepEqual(JSON.parse(vm.runInContext(startExpr, terminal({ mode: 2, server: 'Darwinex-Live' }))).brokerFacts,
  { source: BROKER_FACTS_SOURCE, tradeMode: 'real', server: 'Darwinex-Live' }, 'a real account says so'));

// 3. License check: the id the server already reads, plus brokerFacts without a source.
check(() => {
  const body = JSON.parse(vm.runInContext(checkExpr, terminal({ mode: 1, server: 'MetaQuotes-Demo' })));
  assert.deepEqual(body, { id: '3000107825', brokerFacts: { tradeMode: 'contest', server: 'MetaQuotes-Demo' } });
});

// 4. A broker server name is JSON-quoted: it can never break or extend either body.
for (const server of ['Demo "x"\\é', '","tradeMode":"demo', 'A\u0000B\nC', '']) {
  check(() => {
    const start = JSON.parse(vm.runInContext(startExpr, terminal({ mode: 2, server })));
    assert.deepEqual(start.brokerFacts, { source: BROKER_FACTS_SOURCE, tradeMode: 'real', server }, JSON.stringify(server));
    const license = JSON.parse(vm.runInContext(checkExpr, terminal({ mode: 2, server })));
    assert.deepEqual(license, { id: '3000107825', brokerFacts: { tradeMode: 'real', server } });
  });
}

// 5. Payload only: the readback reads the account and nothing else; no trading call, no trade events.
check(() => {
  const facts = src.slice(src.indexOf('string GOATBrokerFactsTradeMode(void)'), src.indexOf('// The same request MT5 shows'));
  assert.equal(/Order|Position|Trade(?!Mode)|Deal|OnTrade|GOATAIWire|bias/i.test(facts.replace(/ACCOUNT_TRADE_MODE\w*|tradeMode|TradeMode|trade mode|trading, trade events/g, '')), false);
});
// 6. Wiring: device/start and the V1.49 license check carry it; the poll body is unchanged.
check(() => assert.ok(startExpr.includes('GOATBrokerFactsJson("ea-device-start")')));
check(() => assert.ok(checkExpr.includes('GOATBrokerFactsJson("")')));
check(() => assert.match(src, /string json="\{\\"activationId\\":\\""\+g_GOATDeviceActivationId\r?\n\s+\+"\\",\\"accountId\\":\\""\+g_GOATDeviceActivationAccountId\r?\n\s+\+"\\",\\"buildId\\":\\""\+g_GOATDeviceActivationBuildId\+"\\"\}";/));
console.log(`test_broker_facts_payload: ${checks}/${checks} passed`);
