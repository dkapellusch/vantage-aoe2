// Sprite readiness is monotonic until an atlas entry is evicted. Compile each
// view's visible requirements once per camera/settings/catalog combination,
// then make an already-ready view a constant-time check.
export class ViewGraphics {
  constructor(collect, loaded, request) {
    this.collect = collect;
    this.loaded = loaded;
    this.request = request;
    this.views = new WeakMap();
    this.builds = 0;
    this.hits = 0;
  }

  ready(view, context, catalog, revision) {
    let entry = this.views.get(view);
    if (!entry || entry.context !== context || entry.catalog !== catalog) {
      entry = { context, catalog, requests: this.collect(view), readyRevision: -1 };
      this.views.set(view, entry);
      this.builds++;
    }
    if (entry.readyRevision === revision) { this.hits++; return true; }
    let ready = true;
    for (const request of entry.requests) {
      if (this.loaded(request)) continue;
      ready = false;
      this.request(request);
    }
    if (ready) entry.readyRevision = revision;
    return ready;
  }
}
