import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fromTrackpad, wheelKind, pinchFactor } from '../src/vantage/web/wheel-input.js';

// Event values as Chromium reports them.
const macTrackpad = (dy, dx = 0) => ({ deltaMode: 0, deltaX: dx, deltaY: dy, wheelDeltaY: -3 * dy, ctrlKey: false });
const macMouse = (dy) => ({ deltaMode: 0, deltaX: 0, deltaY: dy, wheelDeltaY: dy > 0 ? -120 : 120, ctrlKey: false });
const pcMouse = (notches) => ({ deltaMode: 0, deltaX: 0, deltaY: 100 * notches, wheelDeltaY: -120 * notches, ctrlKey: false });
const pcTouchpad = (dy) => ({ deltaMode: 0, deltaX: 0, deltaY: dy, wheelDeltaY: -dy * 1.2, ctrlKey: false });
const firefoxMouse = (lines) => ({ deltaMode: 1, deltaX: 0, deltaY: lines, ctrlKey: false });
const firefoxTrackpad = (dy) => ({ deltaMode: 0, deltaX: 0, deltaY: dy, ctrlKey: false });

test('a notched mouse wheel is told from a trackpad', () => {
  for (const e of [macMouse(4.000244140625), macMouse(-13.5), pcMouse(1), pcMouse(-3), firefoxMouse(3), firefoxMouse(-1)]) {
    assert.equal(fromTrackpad(e), false, JSON.stringify(e));
  }
  for (const e of [macTrackpad(1), macTrackpad(-2.5), macTrackpad(40), macTrackpad(0, 6), pcTouchpad(7), pcTouchpad(-33),
    firefoxTrackpad(1.5), firefoxTrackpad(-12)]) {
    assert.equal(fromTrackpad(e), true, JSON.stringify(e));
  }
});

test('two fingers pan, a pinch zooms, a mouse wheel zooms', () => {
  assert.equal(wheelKind(macTrackpad(3, 1), {}, 0), 'pan');
  assert.equal(wheelKind(macMouse(4.0002), {}, 0), 'zoom');
  assert.equal(wheelKind(pcMouse(1), {}, 0), 'zoom');
  // A pinch arrives as a wheel event with ctrlKey set while no key is down.
  assert.equal(wheelKind({ ...macTrackpad(-2.3), ctrlKey: true }, {}, 0), 'pinch');
  // Control really held with a mouse wheel is not a pinch.
  assert.equal(wheelKind({ ...pcMouse(1), ctrlKey: true }, {}, 0, 'auto', true), 'zoom');
});

test('one gesture is one kind, and the setting overrides the guess', () => {
  const m = {};
  assert.equal(wheelKind(macTrackpad(5), m, 1000), 'pan');
  // An event that on its own looks like a wheel notch, in the same stream.
  assert.equal(wheelKind(pcMouse(1), m, 1016), 'pan');
  assert.equal(m.started, 1000);
  // After a pause it is a new gesture.
  assert.equal(wheelKind(pcMouse(1), m, 1400), 'zoom');
  assert.equal(m.started, 1400);
  // A pinch begins at once, in the middle of a scroll, and ends as abruptly.
  assert.equal(wheelKind({ ...macTrackpad(-1), ctrlKey: true }, m, 1410), 'pinch');
  assert.equal(wheelKind(macTrackpad(2), m, 1420), 'pan');
  assert.equal(wheelKind(macTrackpad(2), {}, 0, 'zoom'), 'zoom');
  assert.equal(wheelKind(pcMouse(1), {}, 0, 'pan'), 'pan');
  assert.equal(wheelKind({ ...macTrackpad(2), ctrlKey: true }, {}, 0, 'zoom'), 'pinch');
});

test('a pinch zooms in small steps, both ways, evenly', () => {
  assert.ok(pinchFactor(-5) > 1 && pinchFactor(5) < 1);
  assert.ok(Math.abs(pinchFactor(-5) * pinchFactor(5) - 1) < 1e-12);
  assert.ok(pinchFactor(-3) < 1.05);
  assert.equal(pinchFactor(-100), pinchFactor(-30)); // a wheel notch does not jump
  assert.ok(pinchFactor(-5, 2) > pinchFactor(-5));
});
