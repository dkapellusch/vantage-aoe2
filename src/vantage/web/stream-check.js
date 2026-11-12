// Stream-safe checks on a placed panel: text sizes, the safe area and how much
// of the map it covers (hud-model.js streamChecks holds the rules). Used by
// the layout editor's inspector and the Customize drawer's summary.

import { streamChecks } from './hud-model.js';

const NUMERIC = /^[\d\s.,:/+\-–−%×x▲◀▶kKmM]+$/;

/** The font sizes of a panel's visible text: [{ px, kind: 'value' | 'label' }]. */
export function panelTexts(el, limit = 300) {
  const out = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node;
  while (out.length < limit && (node = walker.nextNode())) {
    const text = node.nodeValue.trim();
    if (!text) continue;
    const host = node.parentElement;
    if (!host || !host.getClientRects().length || host.closest('.sr-only, [aria-hidden="true"].sr-only')) continue;
    const style = getComputedStyle(host);
    if (style.visibility === 'hidden' || +style.opacity === 0) continue;
    // zoom (the editor's Scale) multiplies what is drawn.
    const zoom = +getComputedStyle(el).zoom || 1;
    out.push({ px: parseFloat(style.fontSize) * zoom, kind: NUMERIC.test(text) ? 'value' : 'label' });
  }
  return out;
}

export function panelChecks(el) {
  const r = el.getBoundingClientRect();
  return streamChecks({ left: r.left, top: r.top, width: r.width, height: r.height }, { width: window.innerWidth, height: window.innerHeight }, panelTexts(el));
}
