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
const names = [...new Set(optimizer.match(/\bm_(?:lbl|edt|btn|cmb|dt|dp|chk|list)\w+/g))];
function fixture(width, height, owner, empty, loaded) {
  const controls = Object.fromEntries(names.map(name => [name, {
    name, visible: true, bounds: null,
    Hide() { this.visible = false; }, Show() { this.visible = true; },
    Text() {}, Color() {}, ColorBackground() {}, ColorBorder() {},
    Enable() {}, Disable() {}, Height() { return 24; }, FitRows() {},
  }]));
  const container = children => ({
    ControlsTotal: () => children.length, Control: i => children[i],
    Hide() { children.forEach(c => c.Hide()); },
  });
  const c = { ...controls, m_client_area: container(Object.values(controls)),
    c_Wnd_OPT: container([]), c_Wnd_Export: container([]),
    D_Width: width, D_Height: height, m_studioOwner: owner,
    m_studioLoaded: loaded, g_StudioEmptyDraft: empty, handoff: owner === 'human',
    MathMax: Math.max, MathMin: Math.min,
    StageMove(control, x, y, visible, w, h) {
      control.bounds = {x, y, w, h}; control.visible = visible;
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
    vm.runInNewContext(production, c);
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
const reflow = ui.slice(reflowStart, reflowEnd);
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
  for (const name of ['m_btnStageSetup', 'm_btnStageTimeline', 'm_btnStageExecution',
    'm_btnStageExport', 'm_listQueue', 'm_btnStart', 'm_btnStop', 'm_lblQueue'])
    assert.ok(controls[name].visible, `${name} did not return after widening`);
  const stageControls = ['m_edtRunName', 'm_dtFrom', 'm_edtDeposit', 'm_edtSetsToExport'];
  stageControls.forEach((name, index) => assert.equal(controls[name].visible, index === selected));
  assert.ok(controls.m_btnStop.bounds.y > 400, 'Handoff stayed in compact position');
  passed++;
}
console.log(JSON.stringify({passed, nativeVisualQualification: false}));
