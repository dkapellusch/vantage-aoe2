import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ShelfAtlas, available, draw } from '../src/vantage/web/sprite-gl.js';

test('frames pack side by side on shelves, then on new shelves, then in the next layer', () => {
  const a = new ShelfAtlas(2, 100);
  assert.deepEqual(a.place(40, 30, 1), [0, 0, 0]);
  assert.deepEqual(a.place(40, 25, 1), [0, 40, 0]); // fits the 30-high shelf
  assert.deepEqual(a.place(40, 30, 1), [0, 0, 30]); // that shelf is full: a new one below
  assert.deepEqual(a.place(30, 10, 1), [0, 0, 60]); // under 60 % of a shelf's height: its own shelf
  assert.deepEqual(a.place(50, 40, 1), [1, 0, 0]); // layer 0 has no room left
  assert.equal(a.usedLayers(), 2);
  assert.equal(a.place(101, 1, 1), null); // larger than a layer
});

test('a full atlas empties its least recently used layer, never one drawn this frame', () => {
  const a = new ShelfAtlas(2, 100);
  a.place(100, 60, 1);
  a.place(100, 60, 1); // layer 1
  a.touch(1, 2);
  assert.equal(a.gen(0), 0);
  // Frame 3: layer 0 (last used in frame 1) is emptied and reused.
  assert.deepEqual(a.place(100, 100, 3), [0, 0, 0]);
  assert.equal(a.gen(0), 1);
  assert.equal(a.gen(1), 0);
  assert.equal(a.evictions, 1);
  // Still frame 3, layer 1 last used in frame 2: emptied in turn.
  assert.deepEqual(a.place(100, 100, 3), [1, 0, 0]);
  // Both layers hold frame 3's pictures: nothing can be evicted.
  assert.equal(a.place(100, 100, 3), null);
  assert.equal(a.evictions, 2);
});

test('without WebGL2 the batch reports unavailable and draws nothing', () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.equal(available(), false);
    assert.equal(draw({ width: 1 }, 0, 1, 1, 0, 0, 1, 1), false);
  } finally { console.warn = warn; }
});
