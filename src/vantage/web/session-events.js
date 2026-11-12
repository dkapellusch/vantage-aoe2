// EventSource retries ordinary disconnects, but HTTP 502/503 can close it for
// good. Recreate it explicitly so proxy outages cannot disable session updates.
export function sessionEvents(url, { message, skins, error }, {
  create = path => new EventSource(path),
  schedule = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id),
} = {}) {
  let source = null, timer = null, stopped = false, delay = 1000;
  const connect = () => {
    if (stopped) return;
    source = create(url);
    source.onmessage = event => { delay = 1000; message(event); };
    if (skins) source.addEventListener('skins', skins);
    source.onerror = () => {
      source.close(); error?.();
      if (stopped || timer !== null) return;
      timer = schedule(() => { timer = null; connect(); }, delay);
      delay = Math.min(5000, delay * 2);
    };
  };
  connect();
  return () => { stopped = true; source?.close(); if (timer !== null) cancel(timer); };
}
