// Steady Studio panel (PS37): one refresh writes each control property at most once, and a
// refresh that changes nothing writes nothing. EX33 painted the handoff button "GIVE TO AGENT"
// (grey) and then "AGENT CONNECTED" (lime) in the same refresh, up to three times per timer
// tick, and MT5 drew the half-painted state: the panel flashed. This executes the production
// ManagedControls and helpers against recording controls. It is not native visual qualification.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.env.GOAT_EA_ROOT || path.join(__dirname, '..');
const ui = fs.readFileSync(path.join(root, 'GOATStudioUI.mqh'), 'utf8').replace(/^﻿/, '');
const optimizer = fs.readFileSync(path.join(root, 'Optimizer.mqh'), 'utf8').replace(/^﻿/, '');

function preprocess(text) {
  // Every V1.49 feature flag is on; #ifndef blocks are the pre-V1.49 path.
  const stack = [true];
  return text.split(/\r?\n/).filter(line => {
    if (/^#ifn?def/.test(line)) { stack.push(stack.at(-1) && !line.startsWith('#ifndef')); return false; }
    if (/^#else/.test(line)) { stack[stack.length - 1] = stack.at(-2) && !stack.at(-1); return false; }
    if (/^#endif/.test(line)) { stack.pop(); return false; }
    return stack.at(-1);
  }).join('\n');
}
const rgb = (r, g, b) => r * 65536 + g * 256 + b;
function translate(source) {
  return preprocess(source)
    .replace(/\bvoid (GoatStudioSteady\w+)\(([^)]*)\)/g, (_, name, args) =>
      `function ${name}(${args.replace(/\b(?:const\s+)?(?:CWndObj|CWnd|string|color|bool)\s*&?\s*/g, '')})`)
    .replace(/\bvoid CStrategyTesterDialog::(\w+)\(void\)/g, 'function $1()')
    .replace(/CWnd\s*\*\s*child/g, 'let child')
    .replace(/\b(?:const\s+)?(?:bool|string|int|color)\s+(?=[A-Za-z_])/g, 'let ')
    .replace(/\(int\)/g, '')
    .replace(/C'(\d+),(\d+),(\d+)'/g, (_, r, g, b) => String(rgb(+r, +g, +b)))
    .replace(/\bclrNONE\b/g, '-1').replace(/\bNULL\b/g, 'null');
}
const helpersAt = ui.indexOf('void GoatStudioSteadyText(');
const controlsEnd = ui.indexOf('void CStrategyTesterDialog::ManagedSelectStrategy(');
assert.ok(helpersAt > 0 && controlsEnd > helpersAt, 'steady helpers precede ManagedControls');
const production = translate(ui.slice(helpersAt, controlsEnd));
const controlsSource = ui.slice(ui.indexOf('void CStrategyTesterDialog::ManagedControls('), controlsEnd);

const names = [...new Set(optimizer.match(/\bm_(?:lbl|edt|btn|cmb|dt|dp|chk|list)\w+/g))];
let writes = [];
function control(name) {
  const c = { name, visible: true, enabled: true, text: '', fg: -1, bg: -1, border: -1 };
  const record = (prop, value) => writes.push({ name, prop, value });
  Object.assign(c, {
    Text(value) { if (value === undefined) return c.text; c.text = value; record('text', value); return true; },
    Color(value) { if (value === undefined) return c.fg; c.fg = value; record('fg', value); return true; },
    ColorBackground(value) { if (value === undefined) return c.bg; c.bg = value; record('bg', value); return true; },
    ColorBorder(value) { if (value === undefined) return c.border; c.border = value; record('border', value); return true; },
    IsEnabled() { return c.enabled; },
    Enable() { c.enabled = true; record('enabled', true); return true; },
    Disable() { c.enabled = false; record('enabled', false); return true; },
    // MT5 Show/Hide of an already shown/hidden control changes nothing on screen.
    Show() { if (!c.visible) { c.visible = true; record('visible', true); } return true; },
    Hide() { if (c.visible) { c.visible = false; record('visible', false); } return true; },
    Select() { return 'Custom'; }, Current() { return 0; }, FitRows() {}, Height() { return 24; }, Width() { return 24; },
  });
  return c;
}
const LIME = rgb(190, 242, 100), DARK = rgb(15, 17, 19), GOLD = rgb(201, 163, 91), GREY_BORDER = rgb(60, 64, 70);
const INK = rgb(225, 238, 248), MUTED = rgb(100, 120, 140), GRAPHITE = rgb(11, 12, 14);

function fixture(s) {
  writes = [];
  const controls = Object.fromEntries(names.map(name => [name, control(name)]));
  const backdrop = control('c_Wnd_OPT'), tray = control('c_Wnd_Export');
  const children = [backdrop, tray, ...Object.values(controls)];
  const c = {
    ...controls, c_Wnd_OPT: backdrop, c_Wnd_Export: tray,
    m_client_area: { ControlsTotal: () => children.length, Control: i => children[i] },
    D_Width: s.width, D_Height: s.height, m_rowHeight: 34, Font_Size: 10, m_activeStage: 0,
    m_studioOwner: s.owner, m_studioLoaded: s.loaded, m_studioDraftFailed: false,
    g_StudioEmptyDraft: s.empty, g_StudioPendingId: s.pending ? 'req-1' : '', g_StudioPendingCommand: s.pending || '',
    g_StudioControlOutcome: s.outcome || 0, g_StudioControlCommand: s.outcomeCommand || '',
    g_StudioQueueStatuses: ['pending'], g_StudioQueueIds: ['job-1'], g_StudioSchemaHash: 'a'.repeat(64),
    g_StudioHasStrategy: true, g_StudioStrategyName: 'Strategy A',
    GetPointer: x => x, MathMax: Math.max, MathMin: Math.min, ArraySize: a => a.length,
    StringFind: (a, b) => String(a).indexOf(b), GlobalVariableGet: () => 0,
    GoatStudioFields: () => ',IncludeSequenceData', GOATIsLowerHex: v => /^[0-9a-f]{64}$/.test(v),
    GoatStudioComboTheme() {},
    StageMove(target, x, y, visible) { if (visible) target.Show(); else target.Hide(); },
  };
  vm.createContext(c);
  vm.runInContext(production, c);
  return { c, controls };
}
function groupByProperty(list) {
  const seen = new Map();
  for (const w of list) {
    const key = `${w.name}.${w.prop}`;
    seen.set(key, (seen.get(key) || 0) + 1);
  }
  return seen;
}
const scenarios = [
  { label: 'agent connected, full', owner: 'agent', loaded: true, empty: false, width: 1567, height: 691,
    stop: ['AGENT CONNECTED', false, LIME, DARK, LIME], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
  { label: 'agent connected, compact', owner: 'agent', loaded: true, empty: true, width: 1555, height: 640,
    stop: ['AGENT CONNECTED', false, LIME, DARK, LIME], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
  { label: 'human handoff', owner: 'human', loaded: true, empty: true, width: 1555, height: 640,
    stop: ['GIVE TO AGENT', true, GRAPHITE, LIME, LIME], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
  { label: 'human editing, full', owner: 'human', loaded: true, empty: false, width: 1567, height: 691,
    stop: ['GIVE TO AGENT', true, GRAPHITE, LIME, LIME], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
  { label: 'grant pending', owner: 'human', loaded: true, empty: true, width: 1555, height: 640, pending: 'control.grant_agent',
    stop: ['CONNECTING...', false, MUTED, DARK, GREY_BORDER], start: ['TAKE CONTROL', false, INK, DARK, GOLD] },
  { label: 'takeover pending', owner: 'agent', loaded: true, empty: false, width: 1567, height: 691, pending: 'control.takeover',
    stop: ['GIVE TO AGENT', false, MUTED, DARK, GREY_BORDER], start: ['TAKING CONTROL...', false, INK, DARK, GOLD] },
  { label: 'takeover confirmed', owner: 'human', loaded: true, empty: false, width: 1567, height: 691, outcome: 2, outcomeCommand: 'control.takeover',
    stop: ['GIVE BACK TO AGENT', true, GRAPHITE, LIME, LIME], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
  { label: 'snapshot unavailable', owner: '', loaded: false, empty: false, width: 1567, height: 691,
    stop: ['GIVE TO AGENT', false, MUTED, DARK, GREY_BORDER], start: ['TAKE CONTROL', true, INK, DARK, GOLD] },
];
let passed = 0;
for (const s of scenarios) {
  const { c, controls } = fixture(s);
  // Start from the other state's paint so the first refresh must change the buttons.
  controls.m_btnStop.text = 'READ-ONLY VIEW'; controls.m_btnStart.text = 'AGENT CONTROLS BATCH';
  writes = [];
  c.ManagedControls();
  for (const [key, count] of groupByProperty(writes))
    assert.equal(count, 1, `${s.label}: ${key} written ${count} times in one pass`);
  for (const [target, [text, enabled, fg, bg, border]] of [['m_btnStop', s.stop], ['m_btnStart', s.start]]) {
    const b = controls[target];
    assert.deepEqual([b.text, b.enabled, b.fg, b.bg, b.border], [text, enabled, fg, bg, border], `${s.label}: ${target}`);
  }
  // A refresh runs ManagedControls up to three times; with nothing changed none may write.
  for (let pass = 0; pass < 3; pass++) {
    writes = [];
    c.ManagedControls();
    assert.deepEqual(writes, [], `${s.label}: steady pass ${pass} wrote ${JSON.stringify(writes.slice(0, 4))}`);
  }
  passed++;
}
// Compact card: kept controls are never hidden and shown again in one pass.
{
  const { c, controls } = fixture({ owner: 'agent', loaded: true, empty: true, width: 1555, height: 640 });
  writes = [];
  c.ManagedControls();
  const flips = writes.filter(w => w.prop === 'visible');
  for (const name of ['m_btnStop', 'm_btnStart', 'm_lblHeading', 'm_edtBatchProgress', 'm_lblBatchControl', 'm_edtBatchErrors', 'c_Wnd_OPT'])
    assert.equal(flips.filter(w => w.name === name).length, 0, `${name} flipped visibility in the compact card`);
  assert.equal(controls.m_cmbSymbol.visible, false, 'editor fields stay hidden on the card');
  passed++;
}
// Every handoff-button write in ManagedControls goes through the single final paint.
{
  assert.doesNotMatch(controlsSource, /m_btn(?:Stop|Start)\.(?:Text|Color|ColorBackground|ColorBorder|Enable|Disable)\(/,
    'ManagedControls writes a handoff button before its final paint');
  const finalPaint = controlsSource.lastIndexOf('GoatStudioSteadyText(m_btnStart,start_text)');
  assert.ok(finalPaint > controlsSource.lastIndexOf('stop_text='), 'final paint follows every decision');
  passed++;
}
// The read-only monitor stage never pre-paints the buttons ManagedControls owns.
{
  const at = optimizer.indexOf('   if(g_GoatStudioReadOnlyMonitor)', optimizer.indexOf('void CStrategyTesterDialog::ApplyStudioStage('));
  const end = optimizer.indexOf('   if(GoatStudioManaged()) ManagedControls();', at);
  assert.ok(at > 0 && end > at);
  const block = translate(optimizer.slice(at, end));
  for (const managed of [true, false]) {
    const { c, controls } = fixture({ owner: 'agent', loaded: true, empty: false, width: 1567, height: 691 });
    Object.assign(c, { g_GoatStudioReadOnlyMonitor: true, GoatStudioManaged: () => managed });
    writes = [];
    vm.runInContext(block, c);
    const buttons = writes.filter(w => w.name === 'm_btnStop' || w.name === 'm_btnStart');
    if (managed) assert.deepEqual(buttons, [], 'managed read-only stage painted the handoff buttons');
    else assert.equal(controls.m_btnStop.text, 'READ-ONLY VIEW', 'unmanaged read-only view keeps its labels');
  }
  passed++;
  // One whole refresh as ManagedRefresh runs it: two resize passes (stage + controls), then
  // the final ManagedControls. Once settled, a refresh with nothing changed writes nothing.
  for (const s of scenarios) {
    const { c } = fixture(s);
    Object.assign(c, { g_GoatStudioReadOnlyMonitor: true, GoatStudioManaged: () => true });
    const refresh = () => { for (let i = 0; i < 2; i++) { vm.runInContext(block, c); c.ManagedControls(); } c.ManagedControls(); };
    refresh();
    // The read-only stage re-disables controls nothing ever enables; that is not a change.
    // Any write of a value the control did not already hold is a transient paint (a flash).
    const all = [c.c_Wnd_OPT, c.c_Wnd_Export, ...names.map(n => c[n])];
    const before = new Map(all.map(x => [x.name, { text: x.text, fg: x.fg, bg: x.bg, border: x.border, enabled: x.enabled, visible: x.visible }]));
    writes = [];
    refresh();
    const transient = writes.filter(w => before.get(w.name)[w.prop] !== w.value);
    assert.deepEqual(transient, [], `${s.label}: settled refresh repainted ${JSON.stringify(transient.slice(0, 4))}`);
    passed++;
  }
}
// ManagedRefresh writes the status line once, after the draft and receipt checks.
{
  const at = ui.indexOf('void CStrategyTesterDialog::ManagedRefresh(');
  const body = ui.slice(at, ui.indexOf('\n  }', at));
  const normal = body.slice(body.indexOf('bool show_agent_settings'));
  assert.equal((normal.match(/m_edtBatchProgress\.Text\(/g) || []).length, 0, 'status line pre-painted');
  assert.equal((normal.match(/GoatStudioSteadyText\(m_edtBatchProgress,status\)/g) || []).length, 1);
  assert.ok(normal.indexOf('GoatStudioSteadyText(m_edtBatchProgress,status)') > normal.indexOf('AcknowledgePending'));
  passed++;
}
console.log(JSON.stringify({ passed, nativeVisualQualification: false }));
