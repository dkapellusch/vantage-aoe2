// Keep inspection state while live data replaces the selected object's markup.
import { patchHtml } from './dom.js';
const contexts = new WeakMap();

export function setSelectionHtml(el, html, context) {
  let state = contexts.get(el);
  const changedSelection = !state || state.context !== context;
  if (!changedSelection && el._html === html) return;
  const scrollTop = changedSelection ? 0 : el.scrollTop;
  let focusedDetail = null;
  if (changedSelection) state = { context, open: new Map() };
  else {
    for (const detail of el.querySelectorAll('details[data-panel-detail]')) {
      state.open.set(detail.dataset.panelDetail, detail.open);
    }
    const active = el.ownerDocument?.activeElement;
    if (active?.tagName === 'SUMMARY' && el.contains(active)) {
      focusedDetail = active.closest('details[data-panel-detail]')?.dataset.panelDetail;
    }
  }
  contexts.set(el, state);
  el._html = html;
  patchHtml(el, html, changedSelection, true);
  for (const detail of el.querySelectorAll('details[data-panel-detail]')) {
    const key = detail.dataset.panelDetail;
    if (state.open.has(key)) detail.open = state.open.get(key);
    if (key === focusedDetail) detail.querySelector('summary')?.focus({ preventScroll: true });
  }
  el.scrollTop = scrollTop;
}
