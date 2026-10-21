import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ViewGraphics } from '../src/vantage/web/graphics-cache.js';

test('pending graphics retain compiled requirements and become ready after loading', () => {
  const loaded = new Set(), requested = [];
  let builds = 0;
  const cache = new ViewGraphics(() => { builds++; return ['a', 'b']; }, (r) => loaded.has(r), (r) => requested.push(r));
  const view = {}, catalog = {};
  assert.equal(cache.ready(view, 'camera', catalog, 0), false);
  assert.deepEqual(requested, ['a', 'b']);
  loaded.add('a'); requested.length = 0;
  assert.equal(cache.ready(view, 'camera', catalog, 0), false);
  assert.deepEqual(requested, ['b']);
  loaded.add('b');
  assert.equal(cache.ready(view, 'camera', catalog, 0), true);
  assert.equal(builds, 1);
});

test('ready views skip all sprite checks until an eviction changes the revision', () => {
  const loaded = new Set(['a']); let checks = 0;
  const cache = new ViewGraphics(() => ['a'], (r) => { checks++; return loaded.has(r); }, () => {});
  const view = {}, catalog = {};
  assert.equal(cache.ready(view, 'camera', catalog, 0), true);
  loaded.delete('a');
  assert.equal(cache.ready(view, 'camera', catalog, 0), true);
  assert.equal(checks, 1);
  assert.equal(cache.ready(view, 'camera', catalog, 1), false);
  assert.equal(checks, 2);
});

test('camera, colour, settings, catalog and view changes rebuild the visible requirements', () => {
  let builds = 0;
  const cache = new ViewGraphics(() => { builds++; return []; }, () => true, () => {});
  const view = {}, catalog = {};
  assert.equal(cache.ready(view, 'camera:1|color:1', catalog, 0), true);
  assert.equal(cache.ready(view, 'camera:2|color:1', catalog, 0), true);
  assert.equal(cache.ready(view, 'camera:2|color:2', catalog, 0), true);
  assert.equal(cache.ready(view, 'camera:2|color:2', {}, 0), true);
  assert.equal(cache.ready({}, 'camera:2|color:2', catalog, 0), true);
  assert.equal(builds, 5);
});
