import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as M from '../src/vantage/web/hud-model.js';

test('the stock presets hold the panels the design names, and Full has no list of its own', () => {
  assert.deepEqual(M.PRESET_ORDER, ['minimal', 'caster', 'review', 'analyst', 'full']);
  assert.deepEqual(M.PRESETS.minimal.panels, ['pulse', 'selchip', 'minimap']);
  assert.deepEqual(M.PRESETS.caster.panels, ['pulse', 'focus', 'ticker', 'selchip', 'minimap']);
  assert.deepEqual(M.PRESETS.review.panels, ['pulse', 'reviewcards', 'story', 'unitpanel', 'minimap']);
  assert.deepEqual(M.PRESETS.analyst.panels, ['scoreboard', 'overview', 'dashboard', 'unitpanel', 'timebar', 'minimap']);
  assert.equal(M.PRESETS.full.panels, null);
  for (const name of M.PRESET_ORDER) {
    for (const id of M.PRESETS[name].panels || []) assert.ok(M.PANEL_CODES[id], `${name}: ${id} is a known panel`);
    for (const m of M.PRESETS[name].metrics) assert.ok(M.PULSE_METRICS.includes(m), `${name}: ${m} is a Pulse metric`);
  }
  assert.equal(new Set(Object.values(M.PANEL_CODES)).size, Object.keys(M.PANEL_CODES).length, 'panel codes are unique');
});

test('a new viewer starts on Minimal when hosted or embedded and on Full in the desktop app; saved settings win', () => {
  assert.equal(M.initialPreset({ hasSaved: false, embedded: true }), 'minimal');
  assert.equal(M.initialPreset({ hasSaved: false, hosted: true }), 'minimal');
  assert.equal(M.initialPreset({ hasSaved: false }), 'full');
  assert.equal(M.initialPreset({ hasSaved: false, phone: true }), 'minimal');
  assert.equal(M.initialPreset({ hasSaved: true, phone: true }), 'full');
  assert.equal(M.initialPreset({ hasSaved: true, embedded: true, hosted: true }), 'full');
  assert.equal(M.initialPreset({ hasSaved: true, savedPreset: 'review', embedded: true }), 'review');
  assert.equal(M.initialPreset({ hasSaved: true, savedPreset: 'nonsense' }), 'full');
  // A link asks for one visit.
  assert.equal(M.initialPreset({ hasSaved: true, savedPreset: 'full', requested: 'caster' }), 'caster');
  assert.equal(M.initialPreset({ hasSaved: false, requested: 'bogus' }), 'full');
});

test('each preset keeps its own edits, and an edit equal to stock is dropped', () => {
  let hud = M.defaultHud();
  hud = M.withPanels(hud, 'caster', [...M.PRESETS.caster.panels, 'dashboard']);
  assert.ok(M.presetChanged(hud, 'caster'));
  assert.ok(!M.presetChanged(hud, 'review'));
  assert.deepEqual(M.presetPanels(hud, 'review'), M.PRESETS.review.panels);
  assert.ok(M.presetPanels(hud, 'caster').includes('dashboard'));
  hud = M.withPanels(hud, 'caster', M.PRESETS.caster.panels.slice().reverse());
  assert.ok(!M.presetChanged(hud, 'caster'), 'the same set in another order is stock');
  hud = M.withMetrics(hud, 'minimal', ['age', 'vil']);
  assert.deepEqual(M.presetMetrics(hud, 'minimal'), ['age', 'vil']);
  assert.deepEqual(M.presetMetrics(hud, 'caster'), M.PRESETS.caster.metrics);
  hud = M.restorePreset(hud, 'minimal');
  assert.deepEqual(hud.edits, {});
  // Full lists only the newer panels switched on beside the settings flags.
  hud = M.withPanels(hud, 'full', ['pulse']);
  assert.deepEqual(hud.edits.full.panels, ['pulse']);
  assert.deepEqual(M.withPanels(hud, 'full', []).edits, {});
});

test('the share hash round-trips stock presets, custom HUDs and scenes, and stays short', () => {
  const hud = M.defaultHud();
  for (const name of M.PRESET_ORDER) {
    assert.equal(M.encodeHud({ ...hud, preset: name }), name);
    assert.deepEqual(M.decodeHud(name), { preset: name, scene: null });
  }
  assert.equal(M.encodeHud({ ...hud, preset: 'caster' }, { scene: 'fight' }), 'caster.fight');
  assert.deepEqual(M.decodeHud('caster.fight'), { preset: 'caster', scene: 'fight' });
  const edited = M.withMetrics(M.withPanels({ ...hud, preset: 'caster' }, 'caster', ['pulse', 'focus', 'events', 'selchip', 'minimap']), 'caster', ['age', 'vil', 'mil', 'army', 'idle', 'bank', 'rate']);
  const hash = M.encodeHud(edited);
  assert.equal(hash, 'c1.pu-fo-ev-sc-mm.age-vil-mil-army-idle-bank-rate');
  assert.ok(`#hud=${hash}`.length < 120);
  const back = M.decodeHud(hash);
  assert.deepEqual(back, { preset: 'custom', panels: ['pulse', 'focus', 'events', 'selchip', 'minimap'], metrics: ['age', 'vil', 'mil', 'army', 'idle', 'bank', 'rate'], scene: null });
  const applied = M.applyDecoded(hud, back);
  assert.equal(applied.preset, 'custom');
  assert.deepEqual(M.presetPanels(applied, 'custom'), back.panels);
  assert.equal(M.encodeHud(applied), hash, 'encode(decode(x)) is x');
  // A custom hash that equals a stock preset is that preset.
  assert.deepEqual(M.decodeHud(`c1.pu-sc-mm.${M.PRESETS.minimal.metrics.join('-')}.post`), { preset: 'minimal', scene: 'post' });
  // Every panel and metric on still fits a link.
  const all = M.encodeHud(M.withMetrics(M.withPanels({ ...hud, preset: 'caster' }, 'caster', Object.keys(M.PANEL_CODES)), 'caster', M.PULSE_METRICS));
  assert.ok(`#hud=${all}`.length < 160, all);
  // Full shares what is on screen.
  assert.equal(M.encodeHud(hud, { fullPanels: ['scoreboard', 'minimap'] }).split('.')[1], 'sb-mm');
});

test('a malformed hash is ignored, never thrown on', () => {
  for (const bad of ['', 'x', 'c1', 'c1.pu', 'c1.pu.age.fight.extra', 'full.nowhere', 'caster.fight.fight', 'c2.pu.age', null, 42, 'a'.repeat(500)]) assert.equal(M.decodeHud(bad), null, String(bad));
  assert.deepEqual(M.decodeHud('c1.zz-pu.age-bogus'), { preset: 'custom', panels: ['pulse'], metrics: ['age'], scene: null });
  assert.deepEqual(M.decodeHud('c1.0.0'), { preset: 'custom', panels: [], metrics: [], scene: null });
  assert.deepEqual(M.parseHash('#hud=caster.fight&layout=My%20Cast&junk&=x&bad=%E0%A4%A'), { hud: 'caster.fight', layout: 'My Cast' });
  assert.deepEqual(M.parseHash(''), {});
});

test('saved HUD settings are normalised: unknown ids dropped, missing keys defaulted, nothing thrown', () => {
  assert.deepEqual(M.normalizeHud(undefined), M.defaultHud());
  assert.deepEqual(M.normalizeHud('nope'), M.defaultHud());
  const hud = M.normalizeHud({ preset: 'caster', edits: { caster: { panels: ['pulse', 'nope', 'pulse'], metrics: ['age', 'x'] }, bogus: { panels: ['pulse'] }, review: 7 },
    lock: true, focus: 'eco', scene: 'fight', sceneHide: { focus: ['fight', 'never'], nope: ['fight'], pulse: [] }, reserved: { x: 0.7, y: 2, w: 0.2, h: 0.2 },
    hiddenRows: ['kills', 3], layouts: { A: { hud: {} } }, layoutName: 'A', hintSeen: 'yes' });
  assert.equal(hud.preset, 'caster');
  assert.deepEqual(hud.edits, { caster: { panels: ['pulse'], metrics: ['age'] } });
  assert.equal(hud.lock, true); assert.equal(hud.focus, 'eco'); assert.equal(hud.scene, 'fight');
  assert.deepEqual(hud.sceneHide, { focus: ['fight'] });
  assert.deepEqual(hud.reserved, { x: 0.7, y: 1, w: 0.2, h: 0.2 });
  assert.deepEqual(hud.hiddenRows, ['kills']);
  assert.equal(hud.hintSeen, false);
  assert.equal(hud.layoutName, 'A');
  // The custom preset needs its panel list.
  assert.equal(M.normalizeHud({ preset: 'custom' }).preset, 'full');
  assert.deepEqual(M.normalizeHud(hud), hud, 'idempotent');
});

test('layout schema v2: anchors and fractions survive a window of another size', () => {
  const big = { width: 2560, height: 1440 }, obs = { width: 1920, height: 1080 };
  const rect = { left: 2560 - 8 - 400, top: 1440 - 8 - 300, width: 400, height: 300, moved: true };
  const a = M.toAnchored(rect, big);
  assert.equal(a.anchor, 'br'); assert.equal(a.moved, true);
  assert.deepEqual(M.fromAnchored(a, big), rect);
  const small = M.fromAnchored(a, obs);
  assert.deepEqual(small, { left: 1920 - 6 - 300, top: 1080 - 6 - 225, width: 300, height: 225, moved: true });
  // Every anchor round-trips to the pixel.
  for (const anchor of M.ANCHORS) {
    const r = { left: 300, top: 200, width: 500, height: 280 };
    assert.deepEqual(M.fromAnchored(M.toAnchored(r, obs, anchor), obs), r, anchor);
    assert.equal(M.toAnchored(r, obs, anchor).anchor, anchor);
  }
  assert.equal(M.nearestAnchor({ left: 0, top: 0, width: 100, height: 100 }, obs), 'tl');
  assert.equal(M.nearestAnchor({ left: 900, top: 500, width: 100, height: 100 }, obs), 'c');
  assert.equal(M.nearestAnchor({ left: 900, top: 0, width: 100, height: 60 }, obs), 't');
  // A panel that keeps its natural size holds its anchored edge, whatever that size is.
  const natural = M.fromAnchored(a, obs, { width: 400, height: 120 });
  assert.equal(natural.left + natural.width, 1920 - 6); assert.equal(natural.top + natural.height, 1080 - 6);
  assert.equal(natural.width, 400);
  // Scale and opacity travel; the defaults are left out.
  const extra = M.toAnchored({ ...rect, scale: 1.25, opacity: 0.9, auto: true }, big);
  assert.equal(extra.scale, 1.25); assert.equal(extra.opacity, 0.9); assert.equal(extra.auto, true);
  assert.ok(!('scale' in M.toAnchored({ ...rect, scale: 1 }, big)));
});

test('rectangles saved by older builds migrate to schema v2 and land where they were', () => {
  const vp = { width: 1920, height: 1080 };
  const old = { overview: { left: 8, top: 500, width: 430, height: 572, moved: true }, events: { left: 1600, top: 80, width: 300, height: 400, moved: true, auto: true }, junk: 'x', bad: { left: 'a' } };
  const next = M.migratePanelSizes(old, vp);
  assert.deepEqual(Object.keys(next), ['overview', 'events']);
  assert.ok(M.isAnchored(next.overview));
  assert.deepEqual(M.fromAnchored(next.overview, vp), old.overview);
  assert.deepEqual(M.fromAnchored(next.events, vp), old.events);
  assert.deepEqual(M.migratePanelSizes(next, vp), next, 'idempotent');
  assert.deepEqual(M.migratePanelSizes(undefined, vp), {});
});

test('a saved layout carries the layout keys only, and loading one keeps the viewer\'s own list', () => {
  const settings = { hud: { ...M.defaultHud(), preset: 'caster', layouts: { Old: {} }, hintSeen: true }, panelSizes: { pulse: { anchor: 't', x: 0, y: 0.01, w: 1, h: 0.06 } },
    hudLayout: 'caster', showDashboard: false, customHotkeys: { pause: 'P' }, playerNames: { 1: 'x' } };
  const snap = M.snapshotLayout(settings, 'Cast');
  assert.equal(snap.name, 'Cast'); assert.equal(snap.vantageLayout, M.HUD_VERSION);
  assert.ok(!('customHotkeys' in snap) && !('playerNames' in snap));
  assert.ok(!('layouts' in snap.hud));
  snap.panelSizes.pulse.w = 0.5;
  assert.equal(settings.panelSizes.pulse.w, 1, 'a snapshot is a copy');
  const mine = { hud: { ...M.defaultHud(), layouts: { Mine: { hud: {} } }, hintSeen: true }, customHotkeys: { pause: 'Q' } };
  const patch = M.layoutPatch(snap, mine);
  assert.equal(patch.hud.preset, 'caster');
  assert.deepEqual(Object.keys(patch.hud.layouts), ['Mine']);
  assert.equal(patch.hud.hintSeen, true);
  assert.ok(!('customHotkeys' in patch));
  assert.equal(patch.showDashboard, false);
  // A whole settings profile works as a layout source too; anything else does not.
  assert.equal(M.layoutPatch({ ...settings }, mine).hud.preset, 'caster');
  assert.equal(M.layoutPatch({ showDashboard: true }, mine), null);
  assert.equal(M.layoutPatch(null, mine), null);
  assert.equal(M.layoutPatch([1], mine), null);
});

test('scenes: a forced scene wins, then break, post-game, fight, in-game', () => {
  assert.equal(M.activeScene({}), 'game');
  assert.equal(M.activeScene({ fighting: true }), 'fight');
  assert.equal(M.activeScene({ ended: true, fighting: true }), 'post');
  assert.equal(M.activeScene({ idle: true, ended: true }), 'break');
  assert.equal(M.activeScene({ forced: 'break', fighting: true }), 'break');
  assert.equal(M.activeScene({ forced: 'auto', fighting: true }), 'fight');
  const kills = [1000, 50000, 52000, 55000, 90000];
  assert.equal(M.fightAt(kills, 56000), true);
  assert.equal(M.fightAt(kills, 54000), false, 'two kills are not yet a fight');
  assert.equal(M.fightAt(kills, 80000), false, 'the window has passed');
  assert.equal(M.fightAt([], 1000), false);
});

test('stream checks: text sizes, the safe area and map cover', () => {
  const vp = { width: 1920, height: 1080 };
  assert.deepEqual(M.minTextPx(1080), { value: 18, label: 14 });
  assert.deepEqual(M.minTextPx(720), { value: 16, label: 12 });
  const ok = M.streamChecks({ left: 100, top: 100, width: 600, height: 200 }, vp, [{ px: 20, kind: 'value' }, { px: 14.4, kind: 'label' }]);
  assert.deepEqual(ok.map((c) => c.ok), [true, true, true]);
  const bad = M.streamChecks({ left: 8, top: 8, width: 1904, height: 500 }, vp, [{ px: 12, kind: 'value' }, { px: 14, kind: 'label' }]);
  assert.deepEqual(bad.map((c) => c.ok), [false, false, false]);
  assert.equal(bad[0].args.px, 12); assert.equal(bad[1].args.px, 40); assert.equal(bad[2].args.n, 46);
  assert.deepEqual(M.safeFrame(vp), { left: 48, top: 27, width: 1824, height: 1026 });
});

test('the reserved zone pushes a panel out by the shortest way; the grid rounds positions', () => {
  const zone = { left: 1400, top: 700, width: 400, height: 300 };
  const clear = { left: 100, top: 100, width: 200, height: 100 };
  assert.deepEqual(M.avoidZone(clear, zone), clear);
  assert.deepEqual(M.avoidZone(clear, null), clear);
  assert.deepEqual(M.avoidZone({ left: 1250, top: 800, width: 200, height: 100 }, zone), { left: 1200, top: 800, width: 200, height: 100 });
  assert.deepEqual(M.avoidZone({ left: 1500, top: 650, width: 200, height: 100 }, zone), { left: 1500, top: 600, width: 200, height: 100 });
  assert.deepEqual(M.snapToGrid({ left: 13, top: 20, width: 101, height: 55 }), { left: 16, top: 24, width: 101, height: 55 });
});

test('a natural-size panel holds on to a corner, so a taller or shorter content moves one edge only', () => {
  const vp = { width: 1920, height: 1080 };
  // Dragged to the middle of the screen: not the centre anchor (both edges would move).
  const dragged = { left: 559, top: 284, width: 320, height: 349, moved: true, auto: true };
  const a = M.toAnchored(dragged, vp);
  assert.equal(a.anchor, 'tl');
  for (const height of [349, 506, 264]) {
    const r = M.fromAnchored(a, vp, { width: 320, height });
    assert.equal(r.top, 284); assert.equal(r.left, 559);
  }
  // In the lower right it holds its bottom-right corner instead.
  const low = M.toAnchored({ left: 1164, top: 589, width: 320, height: 349, moved: true, auto: true }, vp);
  assert.equal(low.anchor, 'br');
  for (const height of [349, 506]) { const r = M.fromAnchored(low, vp, { width: 320, height }); assert.equal(r.top + r.height, 938); }
  assert.equal(M.cornerAnchor({ left: 1700, top: 100, width: 100, height: 100 }, vp), 'tr');
  assert.equal(M.cornerAnchor({ left: 100, top: 900, width: 100, height: 100 }, vp), 'bl');
  // A panel with a size of its own still takes the nearest of the nine anchors.
  assert.equal(M.toAnchored({ ...dragged, auto: false }, vp).anchor, 'c');
});

test('natural-size panels saved on a centre or edge anchor move to a corner, where they were dragged to', () => {
  const vp = { width: 1920, height: 1080 };
  const old = { unitpanel: { anchor: 'c', x: -0.12552, y: -0.07556, w: 0.16667, h: 0.32335, moved: true, auto: true },
    focus: { anchor: 'bl', x: 0.1, y: 0.1, w: 0.2, h: 0.1, moved: true, auto: true },
    events: { anchor: 'c', x: 0, y: 0, w: 0.2, h: 0.3, moved: true },
    pulse: { anchor: 't', x: 0, y: 0.05, w: 0.5, h: 0.06, moved: true, auto: true, fixed: true } };
  const next = M.reanchorAutoPanels(old, vp);
  assert.equal(next.unitpanel.anchor, 'tl');
  assert.deepEqual(M.fromAnchored(next.unitpanel, vp), M.fromAnchored(old.unitpanel, vp), 'the same rectangle on screen');
  assert.equal(next.focus, old.focus); assert.equal(next.events, old.events, 'a sized panel keeps its anchor');
  assert.equal(next.pulse, old.pulse, 'an anchor chosen by hand stays');
  assert.deepEqual(M.reanchorAutoPanels(next, vp), next, 'idempotent');
});

test('the Selection panel memory is normalised and travels with a saved layout', () => {
  assert.deepEqual(M.normalizeSelectionPanel(undefined), { open: {}, upgrades: null, scope: 'life', expanded: false });
  assert.deepEqual(M.normalizeSelectionPanel({ open: { details: true, junk: 'yes', 'group-units': false }, upgrades: true, scope: 'fight', expanded: 1 }),
    { open: { details: true, 'group-units': false }, upgrades: true, scope: 'life', expanded: false });
  assert.deepEqual(M.normalizeSelectionPanel({ scope: 'minute', expanded: true, open: [] }), { open: {}, upgrades: null, scope: 'minute', expanded: true });
  const settings = { hud: M.defaultHud(), selectionPanel: { open: { details: true }, upgrades: true, scope: 'minute', expanded: false }, panelSizes: { unitpanel: { anchor: 'tl', x: 0.3, y: 0.3, w: 0.2, h: 0.4, moved: true } } };
  const snap = M.snapshotLayout(settings, 'Review');
  assert.deepEqual(snap.selectionPanel, settings.selectionPanel);
  const patch = M.layoutPatch(snap, { hud: M.defaultHud() });
  assert.deepEqual(patch.selectionPanel.open, { details: true });
  assert.equal(patch.panelSizes.unitpanel.anchor, 'tl');
});
