const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const native = fs.readFileSync(path.join(root, 'GOATBatchCancelOrigin.mqh'), 'utf8');
const executable = native.replace(/^\uFEFF/, '').replace(/^#.*$/gm, '')
  .replace(/\b(?:void|bool) (GoatBatch\w+)\(void\)/g, 'function $1()')
  .replace(/\bdouble /g, 'let ');
const values = new Map();
let beforeCas = null, beforeCreate = null;
const c = {
  GOAT_BATCH_CANCELLED_GV: 'cancel', GOAT_BATCH_HUMAN_CANCEL_GV: 'human',
  GlobalVariableGet: k => values.get(k) ?? 0,
  GlobalVariableCheck: k => values.has(k),
  GlobalVariableSet: (k, v) => {
    if (beforeCreate) { const f = beforeCreate; beforeCreate = null; f(); }
    values.set(k, v); return 1;
  },
  GlobalVariableSetOnCondition: (k, next, expected) => {
    if (beforeCas) { const f = beforeCas; beforeCas = null; f(); }
    if (!values.has(k) || values.get(k) !== expected) return false;
    values.set(k, next); return true;
  },
};
vm.createContext(c); vm.runInContext(executable, c);
let checks = 0;
function reset(value, human = 0) {
  values.clear(); if (value !== undefined) values.set('cancel', value);
  values.set('human', human); beforeCas = beforeCreate = null;
}
for (const v of [1, -1, 3, 99]) {
  reset(v); c.GoatBatchRecordControllerCancel();
  assert.equal(values.get('cancel'), v);
  assert.equal(c.GoatBatchReleaseControllerCancel(), false);
  assert.equal(values.get('cancel'), v); checks++;
}
for (const v of [undefined, 0, 2]) {
  reset(v); c.GoatBatchRecordControllerCancel();
  assert.equal(values.get('cancel'), 2);
  assert.equal(c.GoatBatchReleaseControllerCancel(), true);
  assert.equal(values.get('cancel'), 0); checks++;
}
for (const v of [undefined, 0, 1, 2]) {
  reset(v, 1); assert.equal(c.GoatBatchReleaseControllerCancel(), false);
  assert.equal(values.get('cancel'), v); checks++;
}
reset(2); beforeCas = () => values.set('cancel', 1);
assert.equal(c.GoatBatchReleaseControllerCancel(), false);
assert.equal(values.get('cancel'), 1); checks++;
reset(2); beforeCas = () => values.set('human', 1);
assert.equal(c.GoatBatchReleaseControllerCancel(), false);
assert.equal(values.get('human'), 1); checks++;
// A human stop while the controller creates an absent latch remains dominant.
reset(undefined); beforeCreate = () => { values.set('human', 1); values.set('cancel', 1); };
c.GoatBatchRecordControllerCancel();
assert.equal(c.GoatBatchReleaseControllerCancel(), false);
assert.equal(values.get('human'), 1); checks++;
// Proven production call sites: both native start routes use the helper, while
// only the explicitly confirmed human Start action clears the human marker.
const dispatch = fs.readFileSync(path.join(root, 'GOATStudioDispatch.mqh'), 'utf8');
assert.equal((dispatch.match(/if\(!GoatBatchReleaseControllerCancel\(\)\)/g) || []).length, 2);
assert.match(dispatch, /GoatBatchRecordControllerCancel\(\);/);
const ui = fs.readFileSync(path.join(root, 'Optimizer.mqh'), 'utf8');
const stop = ui.slice(ui.indexOf('void CStrategyTesterDialog::OnClickStop('));
assert.ok(stop.indexOf('if(res!=IDYES) return;') < stop.indexOf('GlobalVariableSet(GOAT_BATCH_HUMAN_CANCEL_GV,1.0)'));
assert.ok(stop.indexOf('GlobalVariableSet(GOAT_BATCH_HUMAN_CANCEL_GV,1.0)') < stop.indexOf('GlobalVariableSet(GOAT_BATCH_CANCELLED_GV,1.0)'));
assert.equal((ui.match(/GlobalVariableDel\(GOAT_BATCH_HUMAN_CANCEL_GV\)/g) || []).length, 1);
console.log(`${checks} production cancel-origin cases and native integration checks PASS`);
