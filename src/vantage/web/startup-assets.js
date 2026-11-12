// Asset completion, rather than animation frames, drives first-frame preparation.
const assets = new Map();
const changed = () => globalThis.window?.dispatchEvent?.(new CustomEvent('vantage:asset-settled'));
export function resourceName(url) {
  try { const u = new URL(url, globalThis.location?.href || 'http://localhost'); return u.pathname; }
  catch { return String(url).slice(0, 200); }
}
export function reportResourceError(url, error, attempt = 1) {
  globalThis.window?.dispatchEvent?.(new CustomEvent('vantage:resource-error', {
    detail: { resource: resourceName(url), message: String(error?.message || error).slice(0, 300), attempt },
  }));
}
export async function requestResource(url, options = {}, decode = r => r.json(), fetchImpl = (...args) => fetch(...args)) {
  const tries = !options.method || options.method === 'GET' ? 3 : 1;
  for (let attempt = 1; attempt <= tries; attempt++) {
    const controller = new AbortController();
    const signal = options.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal;
    const timeout = setTimeout(() => controller.abort(new Error('Resource timed out')), 5000);
    try {
      const response = await fetchImpl(url, { ...options, signal });
      if (!response.ok) { const e = new Error(`HTTP ${response.status}`); e.status = response.status; throw e; }
      return await decode(response);
    } catch (error) {
      if (options.signal?.aborted) throw error;
      reportResourceError(url, error, attempt);
      if (attempt === tries || (error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status))) throw error;
    } finally { clearTimeout(timeout); }
  }
}
export function trackAsset(url, task) {
  const item = { resource: resourceName(url), state: 'loading' };
  assets.set(url, item);
  return Promise.resolve().then(task).then(result => {
    item.state = 'ready'; return result;
  }, error => {
    item.state = 'failed'; reportResourceError(url, error); throw error;
  }).finally(changed);
}
export function startupAssets() { return [...assets.values()]; }
export function trackedImage(image, url, loaded = () => {}, failed = () => {}) {
  const item = { resource: resourceName(url), state: 'loading' };
  assets.set(url, item);
  let attempt = 0, timer;
  const begin = () => {
    const token = ++attempt;
    const fail = error => {
      if (token !== attempt || item.state !== 'loading') return;
      clearTimeout(timer);
      reportResourceError(url, error, attempt);
      if (attempt < 3) { begin(); return; }
      item.state = 'failed'; failed(); changed();
    };
    image.onload = () => {
      if (token !== attempt) return;
      clearTimeout(timer); item.state = 'ready'; loaded(); changed();
    };
    image.onerror = () => fail(new Error('Image failed to load'));
    timer = setTimeout(() => fail(new Error('Image timed out')), 5000);
    const retry = new URL(url, location.href);
    if (attempt > 1) retry.searchParams.set('retry', String(attempt));
    image.src = retry.href;
  };
  begin();
  return image;
}
export function notifyAssetsChanged() { changed(); }
