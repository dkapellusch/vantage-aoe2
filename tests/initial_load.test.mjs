import test from 'node:test';
import assert from 'node:assert/strict';
import { InitialFrame } from '../src/vantage/web/initial-load.js';

const complete = { data: true, graphics: true, hud: true, images: true, fonts: true };
test('a first frame waits for every dependency, including delayed sprites and fonts', () => {
  for (const key of Object.keys(complete)) {
    const gate = new InitialFrame();
    assert.equal(gate.update({ ...complete, [key]: false }, 'layout', 0), false);
    assert.deepEqual(gate.missing, [key]);
    assert.equal(gate.update({ ...complete, [key]: false }, 'layout', 5000), false);
    assert.equal(gate.state, 'loading');
    assert.equal(gate.update(complete, 'layout', 5100), false);
    assert.equal(gate.update(complete, 'layout', 5200), true);
    assert.equal(gate.pending, false);
    gate.finish();
    assert.equal(gate.state, 'ready');
  }
});
test('a size change or newly requested asset restarts layout settling', () => {
  const gate = new InitialFrame();
  gate.update(complete, 'before icons', 0);
  assert.equal(gate.update(complete, 'after icons', 90), false);
  assert.equal(gate.update(complete, 'after icons', 180), false);
  gate.update({ ...complete, images: false }, 'after icons', 185);
  assert.equal(gate.update(complete, 'after icons', 190), false);
  assert.equal(gate.update(complete, 'after icons', 290), true);
  assert.equal(gate.update(complete, 'new view during playback', 400), false);
});
test('a usable first frame degrades to placeholders after its budget and can finish', () => {
  const gate = new InitialFrame({ timeoutMs: 500 });
  gate.update({ ...complete, graphics: false }, 'layout', 0);
  assert.equal(gate.update({ ...complete, graphics: false }, 'layout', 500), true);
  assert.equal(gate.state, 'prepared'); assert.equal(gate.degraded, true);
  gate.finish(); assert.equal(gate.state, 'ready');
});
test('missing mandatory data never reveals fabricated content; later recovery can finish', () => {
  const gate = new InitialFrame({ timeoutMs: 500, settleMs: 0 });
  gate.update({ ...complete, data: false }, 'layout', 0);
  assert.equal(gate.update({ ...complete, data: false }, 'layout', 30000), false);
  assert.equal(gate.state, 'loading');
  assert.equal(gate.update(complete, 'layout', 30001), true);
  gate.finish(); assert.equal(gate.state, 'ready');
});
