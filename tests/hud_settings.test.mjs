import assert from 'node:assert/strict';
import { test } from 'node:test';

// state.js reads localStorage, window and location when it is imported, so each
// case imports a fresh copy (a query string makes a new module instance).
let n = 0;
async function load({ saved = null, embedded = false, pathname = '/', search = '', broken = false, phone = false } = {}) {
  const store = new Map(saved == null ? [] : [['vantage.settings.v1', typeof saved === 'string' ? saved : JSON.stringify(saved)]]);
  const self = { addEventListener() {} };
  self.self = self; self.top = embedded ? {} : self;
  globalThis.window = self;
  globalThis.document = { getElementById() { return null; }, addEventListener() {} };
  globalThis.location = { pathname, search, hash: '' };
  // The only media query asked at load is "a narrow or short touch screen".
  globalThis.matchMedia = (query) => ({ matches: phone && /pointer: coarse/.test(query) });
  globalThis.localStorage = broken
    ? { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } }
    : { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, v); } };
  const mod = await import(`../src/vantage/web/state.js?case=${++n}`);
  return { mod, store };
}

test('a brand-new viewer in a hub embed starts on Minimal', async () => {
  const { mod } = await load({ embedded: true });
  assert.equal(mod.settings.hud.preset, 'minimal');
  assert.equal(mod.settingsWereSaved, false);
});

test('a brand-new viewer on a hub match page starts on Minimal', async () => {
  const { mod } = await load({ pathname: '/v/mly52vnwnqovw/' });
  assert.equal(mod.settings.hud.preset, 'minimal');
});

test('the desktop app (vantage serve, not embedded) starts on Full', async () => {
  const { mod } = await load();
  assert.equal(mod.settings.hud.preset, 'full');
  assert.deepEqual(mod.hudEnvironment(), { embedded: false, hosted: false, phone: false, requested: null });
});

test('a brand-new viewer on a phone (a narrow touch screen) starts on Minimal, the preset with a phone layout', async () => {
  const { mod } = await load({ phone: true });
  assert.equal(mod.hudEnvironment().phone, true);
  assert.equal(mod.settings.hud.preset, 'minimal');
  const saved = await load({ phone: true, saved: { settingsVersion: 10, hud: { preset: 'full' } } });
  assert.equal(saved.mod.settings.hud.preset, 'full', 'a saved Full stays Full on a phone too');
});

test('existing saved settings keep Full, even inside a hub embed', async () => {
  const { mod } = await load({ saved: { settingsVersion: 9, seenTutorial: true, showProduction: false, useMinimalUi: true }, embedded: true, pathname: '/v/x/' });
  assert.equal(mod.settingsWereSaved, true);
  assert.equal(mod.settings.hud.preset, 'full');
  assert.equal(mod.settings.showProduction, false, 'the old panel flags are untouched');
  assert.equal(mod.settings.settingsVersion, 10);
  assert.ok(!('useMinimalUi' in mod.settings), 'the dead flag is dropped, not turned into Minimal');
});

test('a saved preset and its edits come back as saved', async () => {
  const hud = { preset: 'review', edits: { review: { panels: ['pulse', 'story', 'minimap'] } }, hintSeen: true };
  const { mod } = await load({ saved: { settingsVersion: 10, hud }, embedded: true });
  assert.equal(mod.settings.hud.preset, 'review');
  assert.deepEqual(mod.settings.hud.edits.review.panels, ['pulse', 'story', 'minimap']);
  assert.equal(mod.settings.hud.hintSeen, true);
});

test('the first save of a new viewer keeps the preset they were given', async () => {
  const { mod, store } = await load({ embedded: true });
  mod.saveSettings();
  assert.equal(JSON.parse(store.get('vantage.settings.v1')).hud.preset, 'minimal');
});

test('blocked or corrupt storage falls back to the defaults without throwing', async () => {
  const blocked = await load({ broken: true });
  assert.equal(blocked.mod.settings.hud.preset, 'full');
  assert.doesNotThrow(() => blocked.mod.saveSettings());
  for (const junk of ['{not json', '[1,2]', '"text"', 'null']) {
    const { mod } = await load({ saved: junk, embedded: true });
    assert.equal(mod.settings.hud.preset, 'minimal', `${junk}: treated as a new viewer`);
    assert.equal(mod.settingsWereSaved, false);
  }
});

test('migration from version 9 is idempotent and repairs a damaged hud object', async () => {
  const { mod } = await load();
  const once = mod.migrateSettings({ settingsVersion: 9, useMinimalUi: false, hud: { preset: 'nope', edits: 'x' } });
  assert.equal(once.settingsVersion, 10);
  assert.equal(once.hud.preset, 'full');
  assert.deepEqual(once.hud.edits, {});
  const twice = mod.migrateSettings(JSON.parse(JSON.stringify(once)));
  assert.deepEqual(twice, once);
});

test('"reset all settings" returns to the first preset for this environment', async () => {
  const hosted = await load({ saved: { settingsVersion: 10, hud: { preset: 'analyst' } }, pathname: '/v/x/' });
  hosted.mod.resetSettings();
  assert.equal(hosted.mod.settings.hud.preset, 'minimal');
  const desktop = await load({ saved: { settingsVersion: 10, hud: { preset: 'analyst' } } });
  desktop.mod.resetSettings();
  assert.equal(desktop.mod.settings.hud.preset, 'full');
  // The defaults themselves are never mutated by a viewer's HUD.
  assert.equal(desktop.mod.DEFAULT_SETTINGS.hud.preset, 'full');
});

test('?hud= is read as a request for this visit', async () => {
  const { mod } = await load({ search: '?overlay=1&hud=caster' });
  assert.equal(mod.hudEnvironment().requested, 'caster');
  assert.equal(mod.settings.hud.preset, 'caster', 'a new viewer starts on the requested preset');
  const saved = await load({ saved: { settingsVersion: 10, hud: { preset: 'full' } }, search: '?hud=caster' });
  assert.equal(saved.mod.settings.hud.preset, 'full', 'saved settings are not rewritten by a link');
});

test('settings from before the Selection panel memory gain its defaults; saved memory comes back', async () => {
  const old = await load({ saved: { settingsVersion: 10, hud: { preset: 'full' } } });
  assert.deepEqual(old.mod.settings.selectionPanel, { open: {}, upgrades: null, scope: 'life', expanded: false });
  const kept = await load({ saved: { settingsVersion: 10, selectionPanel: { open: { details: true }, upgrades: true, scope: 'minute', expanded: true } } });
  assert.deepEqual(kept.mod.settings.selectionPanel, { open: { details: true }, upgrades: true, scope: 'minute', expanded: true });
  assert.deepEqual(kept.mod.DEFAULT_SETTINGS.selectionPanel.open, {}, 'the defaults are not the viewer\'s object');
});
