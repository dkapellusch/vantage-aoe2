// Keep inspection state while live data replaces the selected object's markup.
import { patchHtml } from './dom.js';
const contexts = new WeakMap();

// The per-object Details section is one setting for the user, whatever the object:
// economic units name it "mechanics", the others "activity".
const settingKey = (key) => (key === 'mechanics' || key === 'activity' ? 'details' : key);

export function setSelectionHtml(el, html, context) {
  let state = contexts.get(el);
  const changedSelection = !state || state.context !== context;
  if (!changedSelection && el._html === html) return;
  const scrollTop = changedSelection ? 0 : el.scrollTop;
  let focusedDetail = null;
  // Which sections are open is the user's choice and outlives the selection: take it
  // from the markup being replaced (a toggle since the last refresh counts).
  const open = state ? state.open : new Map();
  for (const detail of el.querySelectorAll('details[data-panel-detail]')) {
    open.set(settingKey(detail.dataset.panelDetail), detail.open);
  }
  if (!changedSelection) {
    const active = el.ownerDocument?.activeElement;
    if (active?.tagName === 'SUMMARY' && el.contains(active)) {
      focusedDetail = active.closest('details[data-panel-detail]')?.dataset.panelDetail;
    }
  }
  state = { context, open };
  contexts.set(el, state);
  el._html = html;
  patchHtml(el, html, changedSelection, true);
  for (const detail of el.querySelectorAll('details[data-panel-detail]')) {
    const key = detail.dataset.panelDetail;
    if (open.has(settingKey(key))) detail.open = open.get(settingKey(key));
    if (key === focusedDetail) detail.querySelector('summary')?.focus({ preventScroll: true });
  }
  el.scrollTop = scrollTop;
}
