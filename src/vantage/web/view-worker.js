// Views off the main thread. state.js posts { id, url, t } and gets { id, value }
// or { id, error } back; { abort: id } cancels a request.
//
// A view comes from the match's pack when this browser holds the chunk it is in
// (timeline-pack.js: rebuilt here in a few ms, no network), else from /api/view
// (a few hundred KB of JSON each, up to ~14 a second at 8x), fetched and parsed
// here. { pack: url, t } starts the pack; { focus: t } says where the playhead
// went; { id, tiles: 'trees' | 'terrain', t, url } asks for a forest or terrain
// snapshot and is answered with { id, value: { t, bytes, kinds } | null };
// localOnly on a view request answers null rather than ask the server.
// The page falls back to fetching on the main thread when workers are missing.

import { requestResource } from './startup-assets.js';
import { PackStore } from './timeline-pack.js';

const bytesOf = (text) => {
  const s = atob(text), out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
};

/** The message handler, separate from the worker global so it can be tested. */
export function createHandler(post, fetchImpl = (...a) => fetch(...a), cacheStorage = null) {
  const inflight = new Map();
  const store = new PackStore({ fetchImpl, cacheStorage, notify: (status) => post({ pack: status }) });
  const handle = async (msg) => {
    if (msg.abort != null) {
      const c = inflight.get(msg.abort);
      if (c) { inflight.delete(msg.abort); c.abort(); }
      return;
    }
    if (msg.pack != null) { await store.start(msg.pack, msg.t || 0); return; }
    if (msg.focus != null) { store.setFocus(msg.focus); return; }
    const ctl = new AbortController();
    inflight.set(msg.id, ctl);
    const live = () => inflight.get(msg.id) === ctl;
    try {
      let value, transfer, local = false;
      if (msg.t != null && store.holds(msg.t)) {
        // A chunk that turns out to be gone (the browser cleared it) falls
        // through to the network.
        try {
          value = msg.tiles ? await store.tiles(msg.tiles, msg.t) : await store.view(msg.t);
          local = true;
        } catch { local = false; }
      }
      if (!local && msg.localOnly) value = null;
      else if (!local) {
        value = await requestResource(msg.url, { priority: 'high', signal: ctl.signal }, r => r.json(), fetchImpl);
        if (msg.tiles) value = value && value.tiles ? { t: value.t, bytes: bytesOf(value.tiles), kinds: value.kinds || [] } : null;
      }
      if (msg.tiles && value) transfer = [value.bytes.buffer];
      if (live()) post(local ? { id: msg.id, value, local: true } : { id: msg.id, value }, transfer);
    } catch (e) {
      if (live()) post({ id: msg.id, error: String((e && e.message) || e) });
    } finally {
      if (live()) inflight.delete(msg.id);
    }
  };
  handle.store = store;
  return handle;
}

if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  const handle = createHandler((m, transfer) => globalThis.postMessage(m, transfer || []), undefined,
    typeof caches !== 'undefined' ? caches : null);
  globalThis.onmessage = (e) => { handle(e.data); };
}
