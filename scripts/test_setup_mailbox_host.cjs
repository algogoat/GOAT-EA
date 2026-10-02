// Source semantics of which charts host the opt-in setup mailbox, and when a shutdown
// is allowed on the read-only Studio monitor. Not MQL runtime or native terminal proof.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '..', 'GOATSetupControl.mqh'), 'utf8');
function body(name) {
  const start = source.indexOf('bool ' + name + '('), brace = source.indexOf('{', start);
  assert.ok(start >= 0, name + ' is defined');
  let depth = 1, end = brace + 1;
  for (; depth; end++) { if (source[end] === '{') depth++; if (source[end] === '}') depth--; }
  return source.slice(brace + 1, end - 1);
}
function run(name, state) {
  const c = { Operation_Dash: 8, Operation_Batch: 11, MQL_TESTER: 1, ...state,
    MQLInfoInteger: () => (state.tester ? 1 : 0), GoatStudioTesterState: () => state.testerState ?? 'idle',
    GlobalVariableGet: key => (state.globals ?? {})[key] ?? 0, FileIsExist: file => (state.files ?? []).includes(file) };
  vm.createContext(c);
  return vm.runInContext('(function(){' + body(name) + '})()', c);
}
let checks = 0;
const check = fn => { fn(); checks++; };
const monitor = { Mode_Operation: 11, g_GoatStudioReadOnlyMonitor: true };
check(() => assert.equal(run('GoatSetupMailboxHost', { Mode_Operation: 8, g_GoatStudioReadOnlyMonitor: false }), true, 'the dashboard hosts the mailbox as before'));
check(() => assert.equal(run('GoatSetupMailboxHost', monitor), true, 'the read-only Studio monitor hosts it too'));
check(() => assert.equal(run('GoatSetupMailboxHost', { Mode_Operation: 11, g_GoatStudioReadOnlyMonitor: false }), false, 'an ordinary Studio chart does not'));
check(() => assert.equal(run('GoatSetupMailboxHost', { Mode_Operation: 9, g_GoatStudioReadOnlyMonitor: false }), false, 'a trading chart never does'));
check(() => assert.equal(run('GoatSetupMailboxHost', { ...monitor, tester: true }), false, 'never inside the Strategy Tester'));
check(() => assert.equal(run('GoatSetupResearchIdle', { Mode_Operation: 8 }), true, 'the dashboard keeps its inert-only rule'));
check(() => assert.equal(run('GoatSetupResearchIdle', monitor), true));
for (const busy of [{ testerState: 'running' }, { testerState: 'unknown' }, { globals: { BatchOnGoing: 1 } }, { globals: { GOAT_BatchRestartPending: 1 } },
  { files: ['GOATStudio\\native-gate\\request.json'] }, { files: ['GOATStudio\\native-gate\\permit.json'] }])
  check(() => assert.equal(run('GoatSetupResearchIdle', { ...monitor, ...busy }), false, JSON.stringify(busy)));
// The poll itself uses the host predicate, and a shutdown needs the idle research state.
const poll = source.slice(source.indexOf('void GoatSetupControlPoll(void)'));
check(() => assert.match(poll, /if\(!GoatSetupMailboxHost\(\)\) return;/));
check(() => assert.match(poll, /research_gate=FileOpen\("GOATStudio\\\\native-gate\\\\launch\.lock",FILE_READ\|FILE_WRITE\|FILE_BIN\);/, 'the monitor takes the research launch gate like the V1.49 diagnostic'));
check(() => assert.match(poll, /bool closable=inert && \(Mode_Operation!=Operation_Batch \|\| \(research_gate!=INVALID_HANDLE && GoatSetupResearchIdle\(\)\)\);/, 'no gate, no close'));
check(() => assert.ok(poll.indexOf('TerminalClose(0);') < poll.indexOf('FileClose(research_gate);'), 'the gate is held through TerminalClose'));
check(() => assert.match(poll, /action=="shutdown" && !closable \? "rejected_not_inert"/));
check(() => assert.match(poll, /AccountInfoInteger\(ACCOUNT_TRADE_MODE\)!=ACCOUNT_TRADE_MODE_DEMO\) return;/, 'still demo-only'));
console.log(`test_setup_mailbox_host: ${checks}/${checks} passed`);
