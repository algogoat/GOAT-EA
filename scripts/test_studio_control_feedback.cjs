const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const native = fs.readFileSync(path.join(root, 'GOATStudioControlFeedback.mqh'), 'utf8');
// Execute the production presentation state machine with a deterministic clock.
// MQL compilation remains a separate check; these are not native UI tests.
const executable = native.replace(/^\uFEFF/, '').replace(/^#.*$/gm, '')
  .replace(/\b(?:void|string) (GoatStudio\w+)\(([^)]*)\)/g, (_, name, args) =>
    `function ${name}(${args.replace(/\b(?:const |string|bool)\s*/g, '')})`)
  .replace(/\b(?:string|ulong|int) /g, 'var ');
let now = 1000;
const c = {GetTickCount64: () => now};
vm.createContext(c); vm.runInContext(executable, c);
const text = owner => c.GoatStudioControlText(owner);
assert.equal(text('human'), '');
c.GoatStudioControlBegin('save', 'draft.replace_configuration');
assert.equal(text('human'), '');
c.GoatStudioControlBegin('grant1', 'control.grant_agent');
assert.match(text('human'), /^Connecting agent/);
assert.doesNotMatch(text('agent'), /Confirmed/); // Snapshot owner alone is not a receipt.
now = 31000;
c.GoatStudioControlBegin('grant1', 'control.grant_agent');
assert.match(text('human'), /^Still waiting/); // Timer retained across recovery/refresh.
c.GoatStudioControlFailure('duplicate click');
assert.match(text('human'), /^Still waiting/); // Never erase or reissue a pending request.
c.GoatStudioControlResolve(true, '');
assert.equal(text('agent'), 'Confirmed: agent controls settings');
assert.equal(text('human'), 'Confirmed: you control settings'); // Superseding snapshot.
assert.equal(text(''), '');
now = 40000;
c.GoatStudioControlBegin('take1', 'control.takeover');
assert.match(text('agent'), /^Taking control/);
c.GoatStudioControlResolve(false, 'Revision changed; refresh settings');
assert.match(text('agent'), /Revision changed; refresh settings/);
c.GoatStudioControlBegin('take1', 'control.takeover');
assert.match(text('agent'), /Revision changed/); // Refresh keeps refusal visible.
c.GoatStudioControlBegin('take2', 'control.takeover');
assert.match(text('agent'), /^Taking control/);
c.GoatStudioControlResolve(true, '');
assert.equal(text('human'), 'Confirmed: you control settings');
c.GoatStudioControlBegin('save-after-take', 'draft.replace_configuration');
assert.equal(text('human'), '', 'later save clears confirmed takeover status');
c.GoatStudioControlFailure('Save or load saved settings first');
assert.match(text('human'), /Save or load saved settings first/);
c.GoatStudioControlBegin('grant2', 'control.grant_agent');
c.GoatStudioControlResolve(false, '');
assert.match(text('human'), /Controller refused/);
c.GoatStudioControlBegin('save1', 'draft.replace_configuration');
assert.equal(text('human'), '', 'later save owns status instead of stale control refusal');
// Integration order: only a bound receipt and visible committed snapshot resolve it.
const ui = fs.readFileSync(path.join(root, 'GOATStudioUI.mqh'), 'utf8');
const receipt = ui.indexOf('if(g_StudioBridge.ReadReceipt(');
const committed = ui.indexOf('committed>revision', receipt);
const resolved = ui.indexOf('GoatStudioControlResolve(applied', receipt);
assert.ok(receipt < committed && committed < resolved);
const submit = ui.indexOf('bool GoatStudioUISubmit(');
assert.ok(ui.indexOf('g_StudioBridge.SubmitHuman(', submit) < ui.indexOf('GoatStudioControlBegin(id,command)', submit));
const controls = ui.slice(ui.indexOf('void CStrategyTesterDialog::ManagedControls('), ui.indexOf('void CStrategyTesterDialog::ManagedSelectStrategy('));
assert.ok(controls.indexOf('m_btnStop.Text("CONNECTING...")') > controls.indexOf('// Keep handoff visible'));
assert.match(controls, /m_btnStart.Disable\(\); m_btnStop.Disable\(\);/);
assert.match(controls, /GIVE CONTROL BACK TO THE AGENT/);
for (const method of ['ManagedTakeover', 'ManagedGrant']) {
 const begin = ui.indexOf(`void CStrategyTesterDialog::${method}(`);
 const end = ui.indexOf('\nvoid ', begin + 1);
 const body = ui.slice(begin, end);
 assert.match(body, /m_edtBatchProgress.Text\(GoatStudioControlText\(m_studioOwner\)\)/);
 assert.match(body, /ChartRedraw\(m_chart_id\)/);
}
const takeover = ui.slice(ui.indexOf('void CStrategyTesterDialog::ManagedTakeover('), ui.indexOf('void CStrategyTesterDialog::ManagedGrant('));
assert.ok(takeover.indexOf('MessageBox(') > 0 && takeover.indexOf('if(confirmation!=IDYES)') < takeover.indexOf('GoatStudioUISubmit("control.takeover"'));
assert.doesNotMatch(native, /SubmitHuman|FileOpen|GlobalVariableSet|ClickStart|StartProcess/);
console.log('Control feedback: 28 assertions passed; native visual qualification pending');
