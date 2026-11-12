import test from 'node:test';
import assert from 'node:assert/strict';
import { requestResource, resourceName } from '../src/vantage/web/startup-assets.js';
import { viewRequestUrl } from '../src/vantage/web/state.js';

test('transient data failures retry without animation frames, visibility or a timer tick', async () => {
  let calls = 0;
  const result = await requestResource('/api/catalog', {}, r => r.json(), async () => {
    if (++calls < 3) throw new TypeError('upstream unavailable');
    return { ok: true, json: async () => ({ ready: true }) };
  });
  assert.deepEqual(result, { ready: true }); assert.equal(calls, 3);
});
test('permanent missing resources and writes are not retried', async () => {
  for (const options of [{}, { method: 'POST' }]) {
    let calls = 0;
    await assert.rejects(requestResource('/missing', options, r => r.json(), async () => {
      calls++; return { ok: false, status: options.method ? 503 : 404 };
    }), /HTTP/);
    assert.equal(calls, 1);
  }
});
test('diagnostic resource names omit query credentials and signed URLs', () => {
  assert.equal(resourceName('https://example.test/sprite/1?secret=private'), '/sprite/1');
});
test('worker requests stay with their match even if another tab overwrites the cookie', () => {
  for (const id of ['moykyzcd4ivqs', 'mqbf7pgwd76jh'])
    assert.equal(viewRequestUrl('/api/view?t=727000', `https://hub.test/v/${id}/`), `https://hub.test/v/${id}/api/view?t=727000`);
  assert.equal(viewRequestUrl('/api/view?t=1', 'http://localhost:8740/'), 'http://localhost:8740/api/view?t=1');
});
