import assert from 'node:assert/strict';
import { test } from 'node:test';

// A page small enough for layout.js: a body with a dataset and a class list, no panels.
const classes = new Set();
const store = new Map();
globalThis.window = { addEventListener() {}, innerWidth: 1920, innerHeight: 1080 };
window.self = window; window.top = window;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
globalThis.document = {
  getElementById() { return null; }, addEventListener() {}, dispatchEvent() {}, querySelectorAll() { return []; },
  documentElement: { style: { setProperty() {} } },
  body: { dataset: {}, classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }, contains: (c) => classes.has(c), add: (c) => classes.add(c), remove: (c) => classes.delete(c) }, matches() { return false; } },
};
globalThis.location = { pathname: '/', search: '', hash: '' };
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
store.set('vantage.settings.v1', JSON.stringify({ settingsVersion: 9, showProduction: false, showEvents: true, hiddenPanels: ['timebar'], seenTutorial: true }));

const { settings, S } = await import('../src/vantage/web/state.js');
const L = await import('../src/vantage/web/layout.js');
const HK = await import('../src/vantage/web/hotkeys.js');
const saved = () => JSON.parse(store.get('vantage.settings.v1'));
const visible = () => L.PANELS.filter((p) => L.isVisible(p.id)).map((p) => p.id);
const LEGACY = ['scoreboard', 'overview', 'dashboard', 'events', 'unitpanel', 'minimap'];

test('an existing setup opens on Full, exactly as its flags describe it', () => {
  L.applyPanels();
  assert.equal(L.activePreset(), 'full');
  assert.deepEqual(visible(), LEGACY, 'production (its flag), techs (its switch) and the hidden time controls stay off');
  assert.equal(document.body.dataset.hudPreset, 'full');
});

test('presets show their own panels and never rewrite Full', () => {
  L.applyPreset('minimal');
  assert.deepEqual(visible(), ['pulse', 'minimap', 'selchip']);
  assert.ok(L.isAuto('timebar'), 'Minimal reveals the time controls by themselves');
  L.applyPreset('caster');
  assert.deepEqual(visible(), ['pulse', 'minimap', 'focus', 'ticker', 'selchip']);
  L.applyPreset('review');
  assert.deepEqual(visible(), ['pulse', 'unitpanel', 'minimap', 'reviewcards', 'story']);
  assert.ok(!L.isAuto('timebar'), 'the Match story carries the playback buttons');
  L.applyPreset('analyst');
  assert.deepEqual(visible(), ['scoreboard', 'overview', 'dashboard', 'unitpanel', 'timebar', 'minimap']);
  assert.equal(saved().hud.preset, 'analyst', 'the choice is saved');
  L.applyPreset('full');
  assert.deepEqual(visible(), LEGACY);
  assert.equal(settings.showProduction, false);
  assert.deepEqual(settings.hiddenPanels, ['timebar']);
});

test('a panel toggled in one preset changes that preset only, and can be restored', () => {
  L.applyPreset('caster');
  L.setVisible('dashboard', true);
  L.setVisible('ticker', false);
  assert.deepEqual(visible(), ['pulse', 'dashboard', 'minimap', 'focus', 'selchip']);
  assert.ok(L.presetIsChanged('caster'));
  assert.equal(settings.showDashboard, true, 'Full\'s own flag is not what was toggled');
  L.applyPreset('review');
  assert.ok(!L.isVisible('dashboard'));
  assert.ok(!L.presetIsChanged('review'));
  L.applyPreset('full');
  assert.deepEqual(visible(), LEGACY);
  L.applyPreset('caster');
  assert.ok(L.isVisible('dashboard'), 'the edit is remembered');
  L.restorePresetDefault('caster');
  assert.deepEqual(visible(), ['pulse', 'minimap', 'focus', 'ticker', 'selchip']);
  L.applyPreset('full');
});

test('in Full the old flags stay the source of truth; newer panels are listed beside them', () => {
  L.setVisible('production', true);
  assert.equal(settings.showProduction, true);
  L.setVisible('production', false);
  L.setVisible('techs', true);
  assert.equal(settings.showStaticTechs, true, 'ticking Techs switches the grid on too');
  assert.ok(L.isVisible('techs'));
  L.setVisible('techs', false);
  assert.equal(settings.showStaticTechs, false);
  L.setVisible('pulse', true);
  assert.deepEqual(settings.hud.edits.full.panels, ['pulse']);
  assert.ok(L.isVisible('pulse') && L.isVisible('scoreboard'));
  L.setVisible('pulse', false);
  assert.deepEqual(settings.hud.edits, {});
  assert.deepEqual(visible(), LEGACY);
});

test('hold-to-peek shows Full without changing the preset', () => {
  L.applyPreset('minimal');
  L.setPeek(true);
  assert.equal(L.activePreset(), 'full');
  assert.deepEqual(visible(), LEGACY);
  assert.ok(classes.has('hud-peek'));
  L.setPeek(false);
  assert.deepEqual(visible(), ['pulse', 'minimap', 'selchip']);
  assert.equal(settings.hud.preset, 'minimal');
  L.applyPreset('full');
});

test('Alt+G toggles the Pulse strip where the preset uses it and the Scoreboard elsewhere', () => {
  assert.equal(L.headlinePanel(), 'scoreboard');
  L.applyPreset('minimal');
  assert.equal(L.headlinePanel(), 'pulse');
  L.applyPreset('analyst');
  assert.equal(L.headlinePanel(), 'scoreboard');
  L.applyPreset('full');
});

test('Pulse metrics are per preset', () => {
  L.applyPreset('minimal');
  L.setPulseMetric('kd', true); L.setPulseMetric('pop', false);
  assert.deepEqual(L.pulseMetrics(), ['age', 'vil', 'mil', 'army', 'idle', 'bank', 'rate', 'kd']);
  L.applyPreset('review');
  assert.deepEqual(L.pulseMetrics(), ['age', 'vil', 'army', 'idle', 'banksum', 'ratesum']);
  L.restorePresetDefault('minimal');
  L.applyPreset('full');
});

test('the share hash describes what is on screen and a link applies without being saved', () => {
  L.applyPreset('caster');
  assert.equal(L.shareHash(), 'hud=caster');
  L.setVisible('events', true);
  assert.equal(L.shareHash(), 'hud=c1.pu-fo-et-sc-mm-ev.age-vil-mil-army-idle-pop-bank-rate');
  L.restorePresetDefault('caster');
  L.applyPreset('full');
  assert.match(L.shareHash(), /^hud=c1\.sb-tb-da-ev-se-mm\./, 'Full shares its visible panels');
  // A link for this visit.
  const before = store.get('vantage.settings.v1');
  location.hash = '#hud=c1.pu-mm.age-army.fight';
  L.readLink(); L.applyPanels();
  assert.equal(L.activePreset(), 'custom');
  assert.deepEqual(visible(), ['pulse', 'minimap']);
  assert.deepEqual(L.pulseMetrics(), ['age', 'army']);
  assert.equal(L.scene(), 'fight');
  assert.equal(settings.hud.preset, 'full');
  assert.equal(store.get('vantage.settings.v1'), before, 'nothing was written');
  // The viewer's first edit makes it their own.
  L.setVisible('focus', true);
  assert.equal(saved().hud.preset, 'custom');
  assert.deepEqual(saved().hud.edits.custom.panels, ['pulse', 'minimap', 'focus']);
  assert.equal(saved().hud.scene, 'auto', 'a link\'s scene is never saved');
  // Reloading the page on the same link keeps their change; following the link afresh applies it again.
  assert.equal(saved().hud.link, 'c1.pu-mm.age-army.fight');
  const timing = performance.getEntriesByType;
  performance.getEntriesByType = () => [{ type: 'reload' }];
  L.readLink(); L.applyPanels();
  assert.deepEqual(visible(), ['pulse', 'minimap', 'focus'], 'a reload does not drop the Focus slot they added');
  performance.getEntriesByType = () => [{ type: 'navigate' }];
  L.readLink(); L.applyPanels();
  assert.deepEqual(visible(), ['pulse', 'minimap'], 'the link, followed again, is the link');
  performance.getEntriesByType = timing;
  location.hash = '#hud=bogus';
  L.readLink(); L.applyPreset('full');
  assert.equal(L.activePreset(), 'full');
  location.hash = '';
  L.readLink();
});

test('a panel tied to scenes hides outside them; scenes follow the match when not forced', () => {
  L.applyPreset('caster');
  L.setHud({ ...L.hud(), sceneHide: { focus: ['fight'], ticker: ['game', 'post'] } });
  S.session = { mode: 'recording' }; S.view = { game_ended: false }; S.events = []; S.t = 100000;
  assert.equal(L.scene(), 'game');
  assert.ok(L.isVisible('focus') && !L.isVisible('ticker'));
  S.events = [95000, 97000, 99000].map((t) => ({ kind: 'kill', t }));
  assert.equal(L.scene(), 'fight');
  assert.ok(!L.isVisible('focus') && L.isVisible('ticker'));
  S.view = { game_ended: true };
  assert.equal(L.scene(), 'post');
  L.setEditorScene('break');
  assert.equal(L.scene(), 'break', 'the layout editor previews a scene');
  L.setEditorScene(null);
  L.setHud({ ...L.hud(), scene: 'game' });
  assert.equal(L.scene(), 'game', 'a scene forced by hand wins');
  L.setHud({ ...L.hud(), scene: 'auto', sceneHide: {} });
  S.events = []; S.view = null; S.session = null;
  L.applyPreset('full');
});

test('reset to defaults: the first preset for this environment, stock presets, saved layouts kept', () => {
  L.applyPreset('caster');
  L.setVisible('dashboard', true);
  L.setHud({ ...L.hud(), lock: true, layouts: { Mine: { hud: {} } }, hintSeen: true });
  L.resetHud();
  assert.equal(settings.hud.preset, 'full', 'the desktop app goes back to Full');
  assert.deepEqual(settings.hud.edits, {});
  assert.equal(settings.hud.lock, false);
  assert.deepEqual(Object.keys(settings.hud.layouts), ['Mine']);
  assert.equal(settings.hud.hintSeen, true);
  assert.deepEqual(settings.panelSizes, {});
});

test('every panel is registered once, with a share code, and its toggle key exists', async () => {
  const M = await import('../src/vantage/web/hud-model.js');
  const ids = L.PANELS.map((p) => p.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual([...ids].sort(), Object.keys(M.PANEL_CODES).sort());
  for (const p of L.PANELS) if (p.action) assert.ok(HK.KEYMAP[p.action], `${p.id}: ${p.action}`);
  for (const name of M.PRESET_ORDER) assert.ok(HK.KEYMAP[M.PRESETS[name].action], `${name} has a key`);
});

test('the preset keys: F6-F9, Shift+F6 for Full, a hold key to peek, and no conflicts', () => {
  assert.deepEqual(HK.hotkeyConflicts({}), []);
  const key = (init) => HK.actionFor({ key: '', code: '', ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...init });
  assert.equal(key({ key: 'F6', code: 'F6' }), 'hudPresetMinimal');
  assert.equal(key({ key: 'F7', code: 'F7' }), 'hudPresetCaster');
  assert.equal(key({ key: 'F8', code: 'F8' }), 'hudPresetReview');
  assert.equal(key({ key: 'F9', code: 'F9' }), 'hudPresetAnalyst');
  assert.equal(key({ key: 'F6', code: 'F6', shiftKey: true }), 'hudPresetFull');
  assert.equal(key({ key: 'F6', code: 'F6', ctrlKey: true, shiftKey: true }), 'setPlayer6', 'the perspective keys are untouched');
  assert.equal(key({ key: 'F10', code: 'F10' }), 'showGameSpeedAndFps');
  assert.equal(key({ key: '`', code: 'Backquote' }), 'peekFullHud');
  assert.equal(key({ key: '²', code: 'Backquote' }), 'peekFullHud', 'the key left of 1 on any layout');
  for (const [combo, action] of [['b', 'toggleDashboard'], ['e', 'toggleEvents'], ['u', 'toggleSelectionPanel'], ['g', 'toggleScoreboard'], ['k', 'toggleFocusSlot'], ['y', 'toggleStory'], ['v', 'togglePanelsMenu'], ['l', 'arrangePanels']]) {
    assert.equal(key({ key: combo, code: `Key${combo.toUpperCase()}`, altKey: true }), action);
  }
  const group = HK.describeKeyGroups().find(([title]) => title === 'HUD presets and layout');
  assert.ok(group, 'the quick reference has a HUD section');
  const text = group[1].map(([, description]) => description).join('|');
  for (const word of ['Minimal', 'Caster', 'Review', 'Analyst', 'Full', 'peek', 'Customize', 'Edit layout']) assert.match(text, new RegExp(word));
  // A rebound preset key still works, and a clash is reported.
  assert.deepEqual(HK.hotkeyConflicts({ hudPresetMinimal: 'Alt+Shift+F1' }), []);
  assert.equal(HK.hotkeyConflicts({ hudPresetMinimal: 'F7' }).length, 1);
});
