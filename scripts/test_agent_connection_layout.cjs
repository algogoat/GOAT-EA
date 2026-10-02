// Execute the production compact-layout block against the MT5 control hierarchy.
// This is a visibility/geometry regression, not native screenshot qualification.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const ui = fs.readFileSync(path.join(root, 'GOATStudioUI.mqh'), 'utf8');
const optimizer = fs.readFileSync(path.join(root, 'Optimizer.mqh'), 'utf8');
const start = ui.indexOf('// Keep handoff visible');
const end = ui.indexOf('#endif', start);
assert.ok(start >= 0 && end > start);
const production = ui.slice(start, end)
  .replace(/CWnd\s*\*\s*child/g, 'let child')
  .replace(/\bint\s+/g, 'let ')
  .replace(/\(int\)/g, '')
  .replace(/\bNULL\b/g, 'null')
  .replace(/C'\d+,\d+,\d+'/g, '0');
// Create* helpers use CDialog::Add, whose MT5 implementation registers controls
// in m_client_area. c_Wnd_OPT is a sibling decorative container with no children.
assert.match(optimizer, /Add\(lbl\)/);
assert.match(optimizer, /Add\(btn\)/);
assert.match(optimizer, /Add\(edt\)/);
assert.match(optimizer, /Add\(cmb\)/);
assert.match(optimizer, /Add\(c_Wnd_OPT\)/);
assert.match(optimizer, /Add\(c_Wnd_Export\)/);
const names = [...new Set(optimizer.match(/\bm_(?:lbl|edt|btn|cmb|dt|dp|chk|list)\w+/g))];
function fixture(width, height, owner, empty, loaded, batchFlag = 0, queued = []) {
  const controls = Object.fromEntries(names.map(name => [name, {
    name, visible: true, bounds: null,
    Hide() { this.visible = false; }, Show() { this.visible = true; },
    Text(value) { if (value === undefined) return this.text || ''; this.text = value; }, Color() {}, ColorBackground() {}, ColorBorder() {},
    Enable() {}, Disable() {}, Height() { return 24; }, Width() { return 24; }, FitRows() {},
  }]));
  const container = children => ({
    visible: true, bounds: null,
    ControlsTotal: () => children.length, Control: i => children[i],
    Hide() { this.visible = false; children.forEach(c => c.Hide()); },
  });
  const backdrop = container([]), exportTray = container([]);
  const c = { ...controls, m_client_area: container([backdrop, exportTray, ...Object.values(controls)]),
    c_Wnd_OPT: backdrop, c_Wnd_Export: exportTray, shown: [],
    D_Width: width, D_Height: height, m_studioOwner: owner,
    m_studioLoaded: loaded, g_StudioEmptyDraft: empty, handoff: owner === 'human',
    m_rowHeight: 34, Font_Size: 10,
    MathMax: Math.max, MathMin: Math.min, StringFind: (s, t) => String(s).indexOf(t),
    GlobalVariableGet: name => (name === 'BatchOnGoing' ? batchFlag : 0), ArraySize: a => a.length, g_StudioQueueIds: queued,
    StageMove(control, x, y, visible, w, h) {
      control.bounds = {x, y, w, h}; control.visible = visible;
      if (visible) c.shown.push(control);
    },
  };
  return {c, controls};
}
let passed = 0;
for (const [width, height, empty, loaded] of [
  [1555, 640, true, true], // Reported overlapping onboarding screen.
  [1555, 640, true, false], // First load / unavailable snapshot.
  [780, 600, false, true], // Populated editor switches to compact on narrow chart.
  [1200, 400, false, true], // Short chart also switches to compact.
  [400, 220, true, true],
]) for (const owner of ['human', 'agent']) {
  const {c, controls} = fixture(width, height, owner, empty, loaded);
  for (let reveal = 0; reveal < 3; reveal++) {
    // Native Show/Maximize recursively exposes all children before reflow.
    Object.values(controls).forEach(control => control.Show());
    c.shown = [];
    vm.runInNewContext(production, c);
    assert.ok(c.c_Wnd_OPT.visible, 'Compact view must retain its panel background');
    assert.equal(c.shown[0], c.c_Wnd_OPT, 'Restore the backdrop before foreground controls');
    assert.deepEqual(c.c_Wnd_OPT.bounds, {x: 0, y: 0, w: width-16, h: height-4});
    assert.equal(c.c_Wnd_Export.visible, false);
    const expected = ['m_lblHeading', 'm_edtBatchProgress', 'm_btnStop'];
    if (owner === 'agent') expected.push('m_btnStart');
    if (height >= 230) expected.push('m_lblBatchControl');
    if (height >= 270) expected.push('m_edtBatchErrors');
    if (!empty && height >= 350) expected.push('m_listQueue');
    assert.deepEqual(Object.values(controls).filter(x => x.visible).map(x => x.name).sort(),
      expected.sort(), `Unexpected editor controls: ${width}x${height} ${owner}`);
    const visible = Object.values(controls).filter(x => x.visible);
    for (const control of visible) {
      const b = control.bounds;
      assert.ok(b.x >= 0 && b.y >= 0 && b.x+b.w <= width && b.y+b.h <= height);
      for (const other of visible.filter(x => x.name !== control.name)) {
        const a = other.bounds;
        assert.ok(b.x+b.w <= a.x || a.x+a.w <= b.x || b.y+b.h <= a.y || a.y+a.h <= b.y,
          `Overlapping ${control.name} and ${other.name}`);
      }
    }
    passed++;
  }
}
// The compact card says what is queued, including an armed flag with nothing queued.
for (const [flag, queued, want] of [[1, [], /^A batch flag is set, but nothing is queued here\.$/],
  [0, [], /^No batch queued yet\./], [1, ['job-1'], /^No batch queued yet\./]]) {
  const {c, controls} = fixture(1555, 640, 'agent', true, true, flag, queued);
  vm.runInNewContext(production, c);
  assert.match(controls.m_lblBatchControl.text, want); passed++;
}
function preprocess(text) {
  const stack = [true];
  return text.split('\n').filter(line => {
    if (/^#ifn?def/.test(line)) { stack.push(stack.at(-1) && !line.startsWith('#ifndef')); return false; }
    if (/^#else/.test(line)) { stack[stack.length-1] = stack.at(-2) && !stack.at(-1); return false; }
    if (/^#endif/.test(line)) { stack.pop(); return false; }
    return stack.at(-1);
  }).join('\n').replace(/\b(?:const )?(?:int|color)\s+/g, 'let ')
    .replace(/\(int\)/g, '').replace(/C'\d+,\d+,\d+'/g, '0');
}
const stageStart = optimizer.indexOf('void CStrategyTesterDialog::ApplyStudioStage(const int stage)');
const stageEnd = optimizer.indexOf('//+------------------------------------------------------------------+', stageStart);
const stage = optimizer.slice(optimizer.indexOf('{', stageStart)+1, optimizer.lastIndexOf('}', stageEnd));
const reflowStart = ui.indexOf('   int tabs_width=');
const reflowEnd = ui.indexOf('\n  }', reflowStart);
const backdropReflow = ui.match(/StageMove\(c_Wnd_OPT,0,0,true,width-16,height-4\);/)[0];
const reflow = backdropReflow + ui.slice(reflowStart, reflowEnd);
assert.ok(stageStart > 0 && reflowStart > 0 && reflow.includes('ApplyStudioStage'));
for (let selected = 0; selected < 4; selected++) {
  const {c, controls} = fixture(780, 600, 'agent', false, true);
  vm.runInNewContext(production, c); // Existing populated form, narrowed.
  Object.assign(c, {D_Width: 1555, D_Height: 640, width: 1555, height: 640,
    m_leftMargin: 16, m_topMargin: 8, m_rowHeight: 34, m_controlHeight: 28,
    m_GapHoriz: 10, editor_width: 685, m_labelWidth: 100, m_controlWidth: 575,
    m_activeStage: selected, Font_Size: 10, m_chart_id: 1,
    g_GoatStudioReadOnlyMonitor: true, Id() {}, ChartRedraw() {},
    GoatStudioManaged: () => true,
    ManagedControls: () => vm.runInNewContext(production, c),
    ApplyStudioStage(value) { c.stage = value; vm.runInNewContext(preprocess(stage), c); },
  });
  vm.runInNewContext(preprocess(reflow), c);
  assert.ok(c.c_Wnd_OPT.visible, 'Full view must retain its panel background');
  for (const name of ['m_btnStageSetup', 'm_btnStageTimeline', 'm_btnStageExecution',
    'm_btnStageExport', 'm_listQueue', 'm_btnStart', 'm_btnStop', 'm_lblQueue'])
    assert.ok(controls[name].visible, `${name} did not return after widening`);
  const stageControls = ['m_edtRunName', 'm_dtFrom', 'm_edtDeposit', 'm_edtSetsToExport'];
  stageControls.forEach((name, index) => assert.equal(controls[name].visible, index === selected));
  assert.ok(controls.m_btnStop.bounds.y > 400, 'Handoff stayed in compact position');
  assert.equal(controls.m_btnDelQ.visible, false, 'Delete All has no managed handler and stays hidden');
  const actions = ['m_btnDelQitem', 'm_btnUpQitem', 'm_btnDownQitem', 'm_btnCancelSelected', 'm_btnMakePending'].map(n => controls[n].bounds);
  actions.slice(1).forEach((b, i) => assert.ok(actions[i].x + actions[i].w <= b.x, 'Queue actions overlap'));
  assert.ok(actions.at(-1).x + actions.at(-1).w <= 1555, 'Queue actions overflow');
  passed++;
}
console.log(JSON.stringify({passed, nativeVisualQualification: false}));
