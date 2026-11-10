import assert from 'node:assert/strict';
import { test } from 'node:test';
import { followRows } from '../src/vantage/web/camera-follow.js';

const row = (id, x, y) => [id, 1, 83, x, y];

test('following converges at the same rate at 30, 60 and 144 frames per second', () => {
  const positions = [];
  for (const rate of [30, 60, 144]) {
    const camera = { x: 0, y: 0 }, rows = [row(7, 100, 40)], selected = new Set([7]);
    for (let i = 0; i < rate / 2; i++) followRows(camera, selected, rows, 1 / rate);
    positions.push(camera);
  }
  for (const camera of positions.slice(1)) {
    assert.ok(Math.abs(camera.x - positions[0].x) < 1e-10);
    assert.ok(Math.abs(camera.y - positions[0].y) < 1e-10);
  }
  // Preserve the old 60 Hz response for a single tick.
  const camera = { x: 0, y: 0 };
  followRows(camera, new Set([7]), [row(7, 100, 40)], 1 / 60);
  assert.ok(Math.abs(camera.x - 20) < 1e-10);
  assert.ok(Math.abs(camera.y - 8) < 1e-10);
});

test('following uses the current selected rows and ignores absent selections', () => {
  const camera = { x: 0, y: 0 }, selected = new Set([1, 2, 3]);
  followRows(camera, selected, [row(1, 10, 20), row(2, 30, 40), row(4, 1000, 1000)], 1 / 60);
  assert.ok(Math.abs(camera.x - 4) < 1e-10);
  assert.ok(Math.abs(camera.y - 6) < 1e-10);
  const before = { ...camera };
  followRows(camera, selected, [row(4, 1, 1)], 1 / 60);
  followRows(camera, selected, [row(1, 1, 1)], 0);
  followRows(camera, selected, [row(1, 1, 1)], NaN);
  assert.deepEqual(camera, before);
});

test('the draw path follows this frame’s interpolated position', async () => {
  // A canvas stub is sufficient: without terrain, draw still interpolates and
  // follows the selected row before it returns.
  const ctx = new Proxy({}, { get: (o, p) => o[p] ?? (() => {}), set: (o, p, v) => (o[p] = v, true) });
  const canvas = { getContext: () => ctx, style: {}, classList: { add() {}, remove() {} },
    addEventListener() {}, width: 100, height: 100 };
  globalThis.document = { getElementById: () => canvas, createElement: () => canvas,
    addEventListener() {}, body: { appendChild() {} } };
  globalThis.window = { addEventListener() {}, devicePixelRatio: 1 };
  const { S } = await import('../src/vantage/web/state.js');
  const world = await import('../src/vantage/web/world.js');
  const moving = (x) => [7, 1, 83, x, 0, 1, 4, 2, [], 2];
  S.view = { time: 0, entities: [moving(0)] };
  S.nextView = { time: 1000, entities: [moving(4)] };
  S.t = 500; S.camera = { x: 0, y: 0, zoom: 1 }; S.selection = new Set([7]);
  S.followSelection = true;
  world.draw(1 / 60);
  assert.equal(world.currentRows()[0][3], 2);
  assert.ok(Math.abs(S.camera.x - 0.4) < 1e-10);
  S.followSelection = false; S.t = 750;
  world.draw(1 / 60);
  assert.equal(world.currentRows()[0][3], 3);
  assert.ok(Math.abs(S.camera.x - 0.4) < 1e-10);
});
