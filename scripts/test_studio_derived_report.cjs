// Execute the production MQL comparison with MQL string-function equivalents.
// Source behavior coverage; packaged/native recovery qualification is separate.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ui = fs.readFileSync(path.join(__dirname, '../GOATStudioUI.mqh'), 'utf8');
const start = ui.indexOf('bool GoatStudioSameDraftSettings(');
const end = ui.indexOf('\nvoid CStrategyTesterDialog::ManagedQueueEnqueue', start);
assert.ok(start >= 0 && end > start);
const code = ui.slice(start, end).replace('bool GoatStudioSameDraftSettings', 'function same')
    .replace(/const string /g, '').replace(/\bint /g, 'let ');
const context = vm.createContext({
    StringFind: (text, query, offset = 0) => text.indexOf(query, offset),
    StringSubstr: (text, start, count) => count === undefined ? text.slice(start) : text.slice(start, start + count),
});
vm.runInContext(code, context);
const base = '[Tester]\nSymbol=EURUSD\nModel=4\nDeposit=100000\nReport=MQL5\\Files\\GOAT\\old\\run.xml\nVisual=0\n[Export]\nMinSR=2.5\n';
const scoped = base.replace('old\\run.xml', 'Rfixture\\reports\\run.xml');
const cases = [
    ['identical', base, base, true],
    ['derived report root', scoped, base, true],
    ['symmetric comparison', base, scoped, true],
    ['symbol edit retained', scoped.replace('EURUSD', 'GBPUSD'), base, false],
    ['model edit retained', scoped.replace('Model=4', 'Model=1'), base, false],
    ['deposit edit retained', scoped.replace('100000', '50000'), base, false],
    ['export edit retained', scoped.replace('MinSR=2.5', 'MinSR=1.5'), base, false],
    ['incomplete text retained', scoped.replace('Deposit=100000', 'Deposit='), base, false],
    ['missing report refused', scoped.replace(/Report=.*\n/, ''), base, false],
    ['empty report refused', scoped.replace(/Report=.*\n/, 'Report=\n'), base, false],
    ['duplicate report refused', scoped + 'Report=other\n', base, false],
    ['duplicate baseline refused', scoped, base + 'Report=other\n', false],
    ['unterminated report refused', '[Tester]\nReport=one', '[Tester]\nReport=two', false],
    ['header change retained', scoped.replace('[Tester]', '[Other]'), base, false],
];
for (const [name, current, baseline, expected] of cases) assert.equal(context.same(current, baseline), expected, name);
assert.equal((ui.match(/!GoatStudioSameDraftSettings\(/g) || []).length, 3, 'refresh/enqueue/handoff use identical comparison');
const candidate = ui.indexOf('bool empty_draft=');
const rejection = ui.indexOf('Queued work has no settings', candidate);
const commit = ui.indexOf('g_StudioEmptyDraft=empty_draft;', rejection);
assert.ok(candidate > 0 && rejection > candidate && commit > rejection, 'rejected snapshots cannot change accepted empty-draft mode');
console.log(`${cases.length} production comparison cases and 2 integration contracts passed`);
