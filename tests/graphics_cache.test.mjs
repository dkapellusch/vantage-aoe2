import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ViewGraphics, SpriteHistory } from '../src/vantage/web/graphics-cache.js';

test('a pending animation keeps its last complete pose after many seconds at 8x speed', () => {
  const history=new SpriteHistory(), row=[42,1,82,0,0,1,1];
  const complete=[['castle-body'],['castle-roof']];
  history.remember(row,1,1000,complete);
  assert.equal(history.get(row,1,17000),complete);
  assert.equal(history.get(row,1,33000),complete);
});
test('sprite fallback never borrows a pose from another game, owner, type or death state', () => {
  const history=new SpriteHistory(), row=[42,1,82,0,0,1,1];
  history.remember(row,1,1000,['pose']);
  assert.equal(history.get(row,1,999),null);
  assert.equal(history.get(row,2,1000),null);
  for(const [column,value] of [[1,2],[2,109],[6,257]]) {
    const changed=[...row]; changed[column]=value;
    assert.equal(history.get(changed,1,1000),null);
  }
});

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

test('remembering a pose reuses its entry and pruning scans at most once a second', () => {
  const history = new SpriteHistory(), row = [42, 1, 82, 0, 0, 1, 1];
  history.remember(row, 1, 1000, ['a']);
  const entry = history.frames.get(42);
  history.remember(row, 1, 1100, ['b']);
  assert.equal(history.frames.get(42), entry); // updated in place, no new object per frame
  assert.deepEqual(history.get(row, 1, 1200), ['b']);
  assert.equal(history.get([42, 2, 82, 0, 0, 1, 1], 1, 1200), null); // converted: another owner
  assert.equal(history.get([42, 1, 82, 0, 0, 1, 257], 1, 1200), null); // the 256 flag changed
  for (let i = 0; i < 5000; i++) history.remember([1000 + i, 1, 4, 0, 0, 1, 1], 1, 0, []);
  history.prune(20000);
  assert.equal(history.frames.size, 0); // all last seen more than 10 s before
  for (let i = 0; i < 5000; i++) history.remember([1000 + i, 1, 4, 0, 0, 1, 1], 1, 0, []);
  history.prune(20500); // within a second of the last scan: skipped
  assert.equal(history.frames.size, 5000);
  history.prune(21500);
  assert.equal(history.frames.size, 0);
});

test('margin strips are prefetched once the on-screen ones are in, and never hold playback', () => {
  const loaded = new Set(), requested = [];
  const cache = new ViewGraphics(() => ({ core: ['a'], extra: ['m1', 'm2'] }), (r) => loaded.has(r), (r) => requested.push(r));
  const view = {}, catalog = {};
  assert.equal(cache.ready(view, 'camera', catalog, 0), false);
  assert.deepEqual(requested, ['a']); // the screen first: the margin waits
  loaded.add('a'); requested.length = 0;
  assert.equal(cache.ready(view, 'camera', catalog, 1), true); // margin strips not loaded: still ready
  assert.deepEqual(requested, ['m1', 'm2']);
  requested.length = 0;
  assert.equal(cache.ready(view, 'camera', catalog, 1), true);
  assert.deepEqual(requested, []);
});
