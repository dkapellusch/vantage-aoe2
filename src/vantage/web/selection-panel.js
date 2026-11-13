// Keep inspection state while live data replaces the selected object's markup,
// and from one selection to the next.
import { patchHtml } from './dom.js';
const contexts = new WeakMap();
const fallbacks = new WeakMap();

/**
 * The name a section's open state is kept under. It is one choice for the
 * viewer, whatever is selected: economic units call their Details section
 * "mechanics" and the others "activity"; a group's sections are named after
 * its owners ("owner-1-2-units").
 */
export function sectionKey(key) {
  if (key === 'mechanics' || key === 'activity') return 'details';
  const group = /^owner-[\d-]+-(units|lifetime)$/.exec(key);
  return group ? `group-${group[1]}` : key;
}

// Without a store (tests, a panel outside the app) the choice lives as long as the element.
function fallbackStore(el) {
  let map = fallbacks.get(el);
  if (!map) { map = new Map(); fallbacks.set(el, map); }
  return { get: (key) => map.get(key), set: (key, open) => { map.set(key, open); } };
}

/** Forget what this panel showed: the next render starts from the store (after a reset). */
export function forgetSelectionState(el) {
  contexts.delete(el); fallbacks.delete(el); el._html = null;
  // The sections on screen close too: their nodes outlive a re-render, open state included.
  for (const detail of el.querySelectorAll('details[data-panel-detail]')) detail.open = false;
}

/**
 * store: { get(name) -> boolean | undefined, set(name, open) }. Which sections
 * are open is read from it for every new selection and written to it when the
 * viewer toggles one (selection-memory.js keeps it in the settings).
 */
export function setSelectionHtml(el, html, context, store = fallbackStore(el)) {
  let state = contexts.get(el);
  const changedSelection = !state || state.context !== context;
  // A section whose open state differs from what was last applied was toggled by the
  // viewer: that is their choice from here on, for this selection and the next.
  const capture = (detail) => {
    const raw = detail.dataset.panelDetail, current = contexts.get(el);
    if (!current || !raw || current.applied.get(raw) === detail.open) return;
    current.applied.set(raw, detail.open); current.local.set(raw, detail.open);
    current.store.set(sectionKey(raw), detail.open);
  };
  if (state) { state.store = store; for (const detail of el.querySelectorAll('details[data-panel-detail]')) capture(detail); }
  if (!el._sectionToggles && el.addEventListener) {
    // At once, too: a toggle while nothing else changes (paused) is kept across a reload.
    el._sectionToggles = true;
    el.addEventListener('toggle', (event) => { if (event.target?.dataset?.panelDetail) capture(event.target); }, true);
  }
  if (!changedSelection && el._html === html) return;
  const scrollTop = changedSelection ? 0 : el.scrollTop;
  let focusedDetail = null;
  if (!changedSelection) {
    const active = el.ownerDocument?.activeElement;
    if (active?.tagName === 'SUMMARY' && el.contains(active)) {
      focusedDetail = active.closest('details[data-panel-detail]')?.dataset.panelDetail;
    }
  }
  // local: toggles within this selection, by the section's own name (the two owners
  // of a mixed group keep their own); a new selection starts from the stored choice.
  // applied: what each section was last set to. Within one selection that stands (a section the
  // viewer left closed is not opened because its neighbour was), including one briefly absent.
  state = { context, store, local: changedSelection ? new Map() : state.local, applied: changedSelection ? new Map() : state.applied };
  contexts.set(el, state);
  el._html = html;
  patchHtml(el, html, changedSelection, true);
  for (const detail of el.querySelectorAll('details[data-panel-detail]')) {
    const key = detail.dataset.panelDetail;
    const open = state.local.has(key) ? state.local.get(key) : state.applied.has(key) ? state.applied.get(key) : store.get(sectionKey(key));
    if (open !== undefined) detail.open = open;
    state.applied.set(key, detail.open);
    if (key === focusedDetail) detail.querySelector('summary')?.focus({ preventScroll: true });
  }
  el.scrollTop = scrollTop;
}
