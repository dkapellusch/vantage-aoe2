import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHandler } from '../src/vantage/web/view-worker.js';

const response = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });

test('the view worker fetches with high priority and posts the parsed view back', async () => {
  const posts = [], seen = [];
  const handle = createHandler((m) => posts.push(m), async (url, opts) => { seen.push([url, opts.priority]); return response({ time: 1000 }); });
  await handle({ id: 1, url: 'http://x/api/view?t=1000' });
  assert.deepEqual(posts, [{ id: 1, value: { time: 1000 } }]);
  assert.deepEqual(seen, [['http://x/api/view?t=1000', 'high']]);
});

test('errors come back as messages, and an aborted request posts nothing', async () => {
  const posts = [];
  let release;
  const handle = createHandler((m) => posts.push(m), async (url, opts) => {
    if (url.endsWith('404')) return response(null, false, 404);
    await new Promise((r) => { release = r; opts.signal.addEventListener('abort', r); });
    throw new DOMException('aborted', 'AbortError');
  });
  await handle({ id: 1, url: 'http://x/404' });
  assert.equal(posts.length, 1); assert.match(posts[0].error, /404/);
  const pending = handle({ id: 2, url: 'http://x/slow' });
  await handle({ abort: 2 });
  await pending;
  assert.equal(posts.length, 1); // the cancelled request is not answered
});
