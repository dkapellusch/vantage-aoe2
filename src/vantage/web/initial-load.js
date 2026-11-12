// Prepare independently of visibility. Prefer a complete first frame; after the
// graphics budget, usable data and HUD can reveal with optional placeholders.
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
      this.state = 'prepared';
      this.revealedAt = now;
      return true;
    }
    if (now - this.started >= this.timeoutMs && requirements.data && requirements.hud) {
      this.degraded = this.missing.length > 0;
      this.state = 'prepared'; this.revealedAt = now;
      return true;
    }
    return false;
  }
  finish() { if (['prepared', 'revealing'].includes(this.state)) this.state = 'ready'; }
  fail() { this.state = 'error'; }
}
