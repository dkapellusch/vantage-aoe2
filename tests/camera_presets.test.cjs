// Actual camera functions/preset expressions extracted from frozen source copies.
// Only DOM/import-free camera region is evaluated; no browser or recording runs.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const root = path.resolve(__dirname, '..');
const legacy = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/camera_presets_legacy.json'), 'utf8'));
const unguarded = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/camera_presets_unguarded.json'), 'utf8'));
const check = test;

function scene(variant, smooth = 1250) {
  const installed = path.join(root, 'src/vantage/web');
  const archive = variant === 'before' ? legacy
    : variant === 'unguarded' ? unguarded : null;
  const world = archive ? archive.worldCameraRegion
    : fs.readFileSync(path.join(installed, 'world.js'), 'utf8');
  const app = archive ? archive.appPresets
    : fs.readFileSync(path.join(installed, 'app.js'), 'utf8');
  const start = world.indexOf('const ZOOM_MIN =');
  const end = world.indexOf('// -- picking & selection', start);
  assert(start >= 0 && end > start);
  const region = world.slice(start, end).replaceAll('export function ', 'function ');
  const context = vm.createContext({clockValue: 0});
  vm.runInContext(`
    const S = {camera: {x:72, y:72, zoom:1}};
    const settings = {cameraSmoothMs:${smooth}, zoomLevels:{one:1.6,two:1,three:.55}};
    const performance = {now: () => clockValue};
    const TW = 32, TH = 16;
    function toWorld() { throw new Error('Unexpected anchor conversion'); }
    ${region}
    globalThis.world = {centerOn, setZoom, stepCamera, ${variant === 'before' ? '' : 'zoomTo,'}};
    globalThis.read = () => JSON.parse(JSON.stringify({camera:S.camera, pan:camAnim, zoom:zoomAnim}));
    globalThis.panRef = () => camAnim;
    globalThis.zoomRef = () => zoomAnim;
    globalThis.rawZoom = () => S.camera.zoom;
    globalThis.setLevels = value => settings.zoomLevels = value;
    globalThis.setSmooth = value => settings.cameraSmoothMs = value;
  `, context);
  const actions = ['One', 'Two', 'Three'].map(name => {
    const found = app.match(new RegExp(`setZoomLevel${name}: (\\(\\) => [^\\n]+),`));
    assert(found, `Missing actual preset ${name}`);
    return `${name.toLowerCase()}:${found[1]}`;
  });
  vm.runInContext(`globalThis.actions = {${actions.join(',')}}`, context);
  return {
    api: context.world, actions: context.actions, read: context.read,
    panRef: context.panRef, zoomRef: context.zoomRef, rawZoom: context.rawZoom,
    setLevels: context.setLevels, setSmooth: context.setSmooth,
    tick(time) { context.clockValue = time; context.world.stepCamera(time); },
  };
}
function near(actual, expected) { assert(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`); }
function position(s, x, y) { near(s.read().camera.x, x); near(s.read().camera.y, y); }

check('original immediate Space-style focus then actual preset loses destination', () => {
  const s = scene('before'); s.api.centerOn(28.16, 41.8);
  assert.equal(s.read().pan.x1, 28.16);
  s.actions.two(); assert.equal(s.read().pan.x1, 72);
  s.tick(1250); position(s, 72, 72);
});
check('original mid-pan preset truncates destination to current position', () => {
  const s = scene('before'); s.api.centerOn(10, 20); s.tick(500);
  const midway = s.read().camera; s.actions.one(); s.tick(1750);
  position(s, midway.x, midway.y); assert.notEqual(s.read().camera.x, 10);
});
check('new immediate preset retains destination and same pan instance/timing', () => {
  const s = scene('staged'); s.api.centerOn(28.16, 41.8); const pan = s.panRef();
  s.actions.two(); assert.equal(s.panRef(), pan);
  assert.equal(s.read().pan.t0, 0); assert.equal(s.read().pan.dur, 1250);
  s.tick(625); position(s, (72+28.16)/2, (72+41.8)/2);
  s.tick(1250); position(s, 28.16, 41.8); near(s.read().camera.zoom, 1);
});
check('new mid-pan zoom completes pan at original deadline, zoom independently', () => {
  const s = scene('staged'); s.api.centerOn(10, 20); s.tick(500); const pan = s.panRef();
  s.actions.one(); assert.equal(s.panRef(), pan); assert.equal(s.read().pan.t0, 0);
  s.tick(1250); position(s, 10, 20); assert.equal(s.read().pan, null);
  assert(s.read().camera.zoom > 1 && s.read().camera.zoom < 1.6);
  s.tick(1750); near(s.read().camera.zoom, 1.6); position(s, 10, 20);
});
check('repeated presets do not extend or replace an in-flight pan', () => {
  const s = scene('staged'); s.api.centerOn(50, 55); const pan = s.panRef();
  for (const [time, action] of [[250,'three'], [400,'one'], [600,'two']]) {
    s.tick(time); s.actions[action](); assert.equal(s.panRef(), pan);
    assert.equal(s.read().pan.t0, 0); assert.equal(s.read().pan.dur, 1250);
  }
  s.tick(1250); position(s, 50, 55); s.tick(1850); near(s.read().camera.zoom, 1);
});
check('preset overrides coupled pan zoom while retaining pan remaining duration', () => {
  const s = scene('staged'); s.api.centerOn(10, 20, 3); s.tick(500);
  const pan = s.panRef(); s.actions.three(); assert.equal(s.panRef(), pan);
  assert.equal(s.read().pan.z1, null);
  s.tick(1250); position(s, 10, 20); s.tick(1750); near(s.read().camera.zoom, .55);
});
check('zoom-only preset leaves position unchanged', () => {
  const s = scene('staged'); s.actions.three(); s.tick(1250);
  position(s, 72, 72); near(s.read().camera.zoom, .55);
});
check('smoothMs zero applies zoom immediately and leaves position fixed', () => {
  const s = scene('staged', 0); s.api.centerOn(10, 20); s.actions.one();
  position(s, 10, 20); near(s.read().camera.zoom, 1.6);
  assert.equal(s.read().pan, null); assert.equal(s.read().zoom, null);
});
check('zero smoothing selected mid-pan changes zoom without replacing existing pan', () => {
  const s = scene('staged'); s.api.centerOn(10, 20); s.tick(500); const pan = s.panRef();
  s.setSmooth(0); s.actions.three(); assert.equal(s.panRef(), pan);
  near(s.read().camera.zoom, .55); s.tick(1250); position(s, 10, 20);
});
check('smooth zoom clamps lower and upper bounds without moving the camera', () => {
  const s = scene('staged'); s.api.zoomTo(-20); s.tick(1250); near(s.read().camera.zoom, .12);
  s.api.zoomTo(999); s.tick(2500); near(s.read().camera.zoom, 6); position(s, 72, 72);
});
check('zero and excessive smoothing durations follow existing smoothMs bounds', () => {
  const s = scene('staged', -5); s.api.zoomTo(2); near(s.read().camera.zoom, 2);
  s.setSmooth(99999); s.api.zoomTo(3); assert.equal(s.read().zoom.dur, 5000);
  s.tick(5000); near(s.read().camera.zoom, 3);
});


check('archived unguarded partial configuration reproduces NaN at zero and smooth duration', () => {
  for (const duration of [0, 1250]) {
    const s = scene('unguarded', duration); s.setLevels({one:2});
    s.actions.two(); s.tick(1250); assert(Number.isNaN(s.rawZoom()));
  }
});
check('actual missing preset two preserves pending pan destination, identity and deadline', () => {
  const s = scene('staged'); s.setLevels({one:2}); s.api.centerOn(28.16, 41.8);
  s.tick(250); const pan = s.panRef(), snapshot = s.read(); s.actions.two();
  assert.equal(s.panRef(), pan); assert.deepEqual(s.read(), snapshot);
  s.tick(1250); position(s, 28.16, 41.8); near(s.rawZoom(), 1);
});
check('present partial preset still works and missing third preserves its active zoom', () => {
  const s = scene('staged'); s.setLevels({one:2}); s.actions.one(); s.tick(250);
  const zoom = s.zoomRef(), snapshot = s.read(); s.actions.three();
  assert.equal(s.zoomRef(), zoom); assert.deepEqual(s.read(), snapshot);
  s.tick(1250); near(s.rawZoom(), 2);
});
check('ignored values leave pending coupled pan, reference, timing and zoom unchanged', () => {
  for (const value of [undefined, null, 0, false, '', NaN, 'not-a-number']) {
    const s = scene('staged'); s.api.centerOn(10, 20, 3); s.tick(250);
    const pan = s.panRef(), snapshot = s.read(); s.api.zoomTo(value);
    assert.equal(s.panRef(), pan); assert.deepEqual(s.read(), snapshot);
    s.tick(1250); position(s, 10, 20); near(s.rawZoom(), 3);
  }
});
check('ignored values leave both ongoing independent zoom and pan unchanged', () => {
  for (const value of [undefined, null, 0, false, '', NaN, 'bad']) {
    const s = scene('staged'); s.api.centerOn(10, 20); s.tick(250); s.api.zoomTo(1.6);
    s.tick(400); const pan = s.panRef(), zoom = s.zoomRef(), snapshot = s.read();
    s.api.zoomTo(value); assert.equal(s.panRef(), pan); assert.equal(s.zoomRef(), zoom);
    assert.deepEqual(s.read(), snapshot);
    s.tick(1250); position(s, 10, 20); s.tick(1500); near(s.rawZoom(), 1.6);
  }
});
check('ignored zero-duration calls preserve finite camera without creating animations', () => {
  for (const value of [undefined, null, 0, false, '', NaN, 'bad']) {
    const s = scene('staged', 0), snapshot = s.read(); s.api.zoomTo(value);
    assert.deepEqual(s.read(), snapshot); near(s.rawZoom(), 1);
  }
});
check('truthy numeric strings and infinities retain legacy coercion and clamps', () => {
  for (const [value, target] of [['2.5',2.5], ['0',.12], ['999',6], ['-20',.12], [Infinity,6], [-Infinity,.12]]) {
    const old = scene('before'), fixed = scene('staged');
    old.api.centerOn(72, 72, value); fixed.api.zoomTo(value);
    old.tick(1250); fixed.tick(1250); near(old.rawZoom(), target); near(fixed.rawZoom(), target);
    position(fixed, 72, 72);
  }
});
check('falsy preset admission agrees with archived legacy centerOn zoom behavior', () => {
  for (const value of [undefined, null, 0, false, '', NaN]) {
    const old = scene('before'), fixed = scene('staged');
    old.api.centerOn(72, 72, value); fixed.api.zoomTo(value);
    old.tick(1250); fixed.tick(1250); near(old.rawZoom(), 1); near(fixed.rawZoom(), 1);
  }
});
