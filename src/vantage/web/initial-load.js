// First-frame readiness: every dependency must be ready and the layout must
// remain unchanged briefly. A timeout offers retry; it never reveals half a map.
export class InitialFrame {
  constructor({ settleMs = 100, timeoutMs = 30000 } = {}) {
    this.settleMs = settleMs;
    this.timeoutMs = timeoutMs;
    this.state = 'loading';
    this.started = null;
    this.stableSince = null;
    this.layout = null;
    this.missing = [];
  }
  get pending() { return this.state === 'loading'; }
  update(requirements, layout, now) {
    if (!this.pending) return false;
    this.started ??= now;
    this.missing = Object.keys(requirements).filter((key) => !requirements[key]);
    if (this.missing.length) this.stableSince = null;
    else if (this.stableSince == null || layout !== this.layout) this.stableSince = now;
    this.layout = layout;
    if (!this.missing.length && now - this.stableSince >= this.settleMs) {
      this.state = 'revealing';
      this.revealedAt = now;
      return true;
    }
    if (now - this.started >= this.timeoutMs) this.state = 'error';
    return false;
  }
  finish() { if (this.state === 'revealing') this.state = 'ready'; }
  fail() { this.state = 'error'; }
}
