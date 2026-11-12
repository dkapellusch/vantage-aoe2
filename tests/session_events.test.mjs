import test from 'node:test';
import assert from 'node:assert/strict';
import { sessionEvents } from '../src/vantage/web/session-events.js';

test('recreates a terminal stream after proxy failures, with bounded backoff', () => {
  const sources = [], timers = [], received = [];
  const stop = sessionEvents('/api/stream', { message: e => received.push(e.data) }, {
    create: () => { const s = { closed: false, close() { this.closed = true; } }; sources.push(s); return s; },
    schedule: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    cancel: id => { timers[id - 1].cancelled = true; },
  });
  for (let i = 0; i < 5; i++) { sources.at(-1).onerror(); assert.equal(sources.at(-1).closed, true); timers.at(-1).fn(); }
  assert.deepEqual(timers.map(t => t.ms), [1000, 2000, 4000, 5000, 5000]);
  sources.at(-1).onmessage({ data: 'recovered' });
  assert.deepEqual(received, ['recovered']);
  sources.at(-1).onerror();
  assert.equal(timers.at(-1).ms, 1000);
  stop();
  assert.equal(timers.at(-1).cancelled, true);
  const count = sources.length;
  timers.at(-1).fn();
  assert.equal(sources.length, count);
});
