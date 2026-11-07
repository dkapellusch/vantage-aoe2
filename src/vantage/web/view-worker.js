// Fetches and parses keyframe views (/api/view, a few hundred KB of JSON each,
// up to ~14 a second at 8x) off the main thread; state.js posts { id, url } and
// gets { id, value } or { id, error } back, and { abort: id } cancels a request.
// The page falls back to fetching on the main thread when workers are missing.

/** The message handler, separate from the worker global so it can be tested. */
export function createHandler(post, fetchImpl = (...a) => fetch(...a)) {
  const inflight = new Map();
  return async (msg) => {
    if (msg.abort != null) {
      const c = inflight.get(msg.abort);
      if (c) { inflight.delete(msg.abort); c.abort(); }
      return;
    }
    const ctl = new AbortController();
    inflight.set(msg.id, ctl);
    try {
      const r = await fetchImpl(msg.url, { priority: 'high', signal: ctl.signal });
      if (!r.ok) throw new Error(`${msg.url}: ${r.status}`);
      const value = await r.json();
      if (inflight.get(msg.id) === ctl) post({ id: msg.id, value });
    } catch (e) {
      if (inflight.get(msg.id) === ctl) post({ id: msg.id, error: String((e && e.message) || e) });
    } finally {
      if (inflight.get(msg.id) === ctl) inflight.delete(msg.id);
    }
  };
}

if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  const handle = createHandler((m) => globalThis.postMessage(m));
  globalThis.onmessage = (e) => { handle(e.data); };
}
