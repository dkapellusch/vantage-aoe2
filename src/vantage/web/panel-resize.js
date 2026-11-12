import { settings, saveSettings } from './state.js';
import { t } from './i18n.js';
import { isAnchored, toAnchored, fromAnchored, migratePanelSizes, snapToGrid, avoidZone, safeFrame } from './hud-model.js';

// HUD panel rectangles the user set: resized from a corner handle, or moved by
// the ⠿ grip in the hover toolbar (layout.js) or anywhere on a panel in arrange
// mode (Alt+L). settings.panelSizes[id] is stored as an anchor and fractions of
// the window (hud-model.js toAnchored: {anchor, x, y, w, h, moved?, auto?,
// scale?, opacity?}), so a layout survives a window resize and an OBS source of
// another size; this module works in pixels and converts at the edges.
// Rectangles saved by older builds ({left, top, width, height}) are converted
// on first use. moved panels leave their column; auto ones were only moved, so
// they keep their natural size. Moves and resizes snap to the window edges and
// to other panels' edges (Shift while dragging: no snapping); in the layout
// editor also to its grid and safe frame, and out of the reserved zone.

const SELECTOR = '.panel[id], .overlay[id], .review-surface[id]';
const EXCLUDE = new Set(['omni-menu', 'panels-menu', 'jump-banner', 'launch-status', 'autocast-banner']);
// Corner handles and edge handles (data-corner keeps its name for both).
const corners = ['nw', 'ne', 'sw', 'se', 'n', 's', 'e', 'w'];
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const MARGIN = 8, SNAP = 8, GAP = 6;

export function fitRect(rect, viewport) {
  const width = clamp(Number(rect.width) || 240, 80, Math.max(80, viewport.width - 16));
  const height = clamp(Number(rect.height) || 100, 50, Math.max(50, viewport.height - 16));
  return { left: clamp(Number(rect.left) || 0, 8, Math.max(8, viewport.width - width - 8)),
    top: clamp(Number(rect.top) || 0, 8, Math.max(8, viewport.height - height - 8)), width, height };
}

export function resizeRect(rect, corner, dx, dy, viewport, minimum = { width: 200, height: 80 }) {
  const west = corner.includes('w'), north = corner.includes('n');
  const right = rect.left + rect.width, bottom = rect.top + rect.height;
  const left = west ? clamp(rect.left + dx, 8, right - minimum.width) : rect.left;
  const top = north ? clamp(rect.top + dy, 8, bottom - minimum.height) : rect.top;
  const width = west ? right - left : clamp(rect.width + dx, minimum.width, viewport.width - left - 8);
  const height = north ? bottom - top : clamp(rect.height + dy, minimum.height, viewport.height - top - 8);
  return fitRect({ left, top, width, height }, viewport);
}

/** The rectangle moved by (dx, dy), kept inside the window. */
export function moveRect(rect, dx, dy, viewport) {
  return fitRect({ ...rect, left: rect.left + dx, top: rect.top + dy }, viewport);
}

/**
 * Snap a rectangle's moving edges to the window margin and to other panels:
 * edge to edge (aligned) or GAP apart (side by side). mode is 'move' (the
 * whole rectangle shifts, nearest edge wins) or the resize corner ('se', ...;
 * only those edges move). Returns the snapped rectangle and guide lines
 * ({axis: 'x' | 'y', at}) to draw.
 */
export function snapRect(rect, others, viewport, mode = 'move', threshold = SNAP, gap = GAP) {
  const r = { ...rect }, guides = [];
  const xs = { l: [MARGIN], r: [viewport.width - MARGIN] }, ys = { t: [MARGIN], b: [viewport.height - MARGIN] };
  for (const o of others) {
    xs.l.push(o.left, o.left + o.width + gap); xs.r.push(o.left + o.width, o.left - gap);
    ys.t.push(o.top, o.top + o.height + gap); ys.b.push(o.top + o.height, o.top - gap);
  }
  const near = (v, list) => {
    let best = null;
    for (const x of list) { const d = x - v; if (Math.abs(d) <= threshold && (best === null || Math.abs(d) < Math.abs(best))) best = d; }
    return best;
  };
  if (mode === 'move') {
    const dl = near(r.left, xs.l), dr = near(r.left + r.width, xs.r);
    const dx = dl === null ? dr : dr === null ? dl : Math.abs(dl) <= Math.abs(dr) ? dl : dr;
    if (dx !== null) { r.left += dx; guides.push({ axis: 'x', at: dx === dl ? r.left : r.left + r.width }); }
    const dt = near(r.top, ys.t), db = near(r.top + r.height, ys.b);
    const dy = dt === null ? db : db === null ? dt : Math.abs(dt) <= Math.abs(db) ? dt : db;
    if (dy !== null) { r.top += dy; guides.push({ axis: 'y', at: dy === dt ? r.top : r.top + r.height }); }
    return { rect: r, guides };
  }
  if (mode.includes('w')) { const d = near(r.left, xs.l); if (d !== null) { r.left += d; r.width -= d; guides.push({ axis: 'x', at: r.left }); } }
  if (mode.includes('e')) { const d = near(r.left + r.width, xs.r); if (d !== null) { r.width += d; guides.push({ axis: 'x', at: r.left + r.width }); } }
  if (mode.includes('n')) { const d = near(r.top, ys.t); if (d !== null) { r.top += d; r.height -= d; guides.push({ axis: 'y', at: r.top }); } }
  if (mode.includes('s')) { const d = near(r.top + r.height, ys.b); if (d !== null) { r.height += d; guides.push({ axis: 'y', at: r.top + r.height }); } }
  return { rect: r, guides };
}

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });
const minimum = id => ({ width: id === 'minimap-wrap' ? 180 : 220, height: id === 'scoreboard' ? 60 : 90 });
let handleBox, guideBox, host = null, drag = null, move = null, changed = () => {};
const slots = new Map();

function dropSlot(id) { const slot = slots.get(id); if (slot) { slot.remove(); slots.delete(id); } }

// A panel resized in place keeps its place in its column (a sized slot holds
// it); a moved one leaves the column, which closes up.
function syncSlot(el, rect) {
  if (rect.moved || !['leftcol', 'leftcol2'].includes(el.parentElement?.id)) { dropSlot(el.id); return; }
  let slot = slots.get(el.id);
  if (!slot) {
    slot = document.createElement('div'); slot.className = 'panel-size-slot'; slot.dataset.for = el.id;
    slots.set(el.id, slot);
  }
  if (slot.nextSibling !== el || slot.parentElement !== el.parentElement) el.before(slot);
  slot.style.width = `${rect.width}px`;
  slot.style.height = `${el.classList.contains('collapsed') ? 28 : rect.height}px`;
  slot.hidden = el.classList.contains('hidden') || el.classList.contains('panel-off');
}

function dockTimebar() {
  const map = document.getElementById('minimap-wrap'), bar = document.getElementById('timebar');
  if (!map || !bar || bar.classList.contains('hud-custom-size')) return;
  if (map.classList.contains('hud-custom-size')) {
    const bottom = clamp(window.innerHeight - map.getBoundingClientRect().top + 8, 8,
      window.innerHeight - bar.offsetHeight - 8);
    bar.style.bottom = `${bottom}px`; bar.dataset.minimapDocked = 'true';
  } else if (bar.dataset.minimapDocked) {
    bar.style.bottom = ''; delete bar.dataset.minimapDocked;
  }
}

// The last-moved panel draws over other moved ones (still under slide-outs and menus).
const topmost = () => (Array.isArray(settings.panelOrder) ? settings.panelOrder.at(-1) : null);

function setRect(el, rect) {
  el.classList.add('hud-custom-size');
  el.classList.toggle('hud-auto-size', !!rect.auto);
  // zoom scales the element's own lengths too: divide, so the rectangle stays the one asked for.
  const z = typeof rect.scale === 'number' && rect.scale > 0 ? rect.scale : 1;
  for (const key of ['left', 'top', 'width', 'height']) el.style.setProperty(`--panel-${key}`, `${rect[key] / z}px`);
  el.style.zoom = z === 1 ? '' : String(z);
  if (typeof rect.opacity === 'number' && rect.opacity < 1) el.style.setProperty('--panel-opacity', String(rect.opacity));
  else el.style.removeProperty('--panel-opacity');
  el.style.zIndex = rect.moved ? (topmost() === el.id ? '2' : '1') : '';
  syncSlot(el, rect);
}

function clearRect(el) {
  el.classList.remove('hud-custom-size', 'hud-auto-size');
  el.style.zIndex = ''; el.style.zoom = '';
  for (const key of ['left', 'top', 'width', 'height', 'opacity']) el.style.removeProperty(`--panel-${key}`);
}

// Flags (moved, auto) and the scale and opacity survive fitting to a smaller window.
const extrasOf = (rect) => ({ ...(rect.moved ? { moved: true } : {}), ...(rect.auto ? { auto: true } : {}), ...(rect.fixed ? { fixed: true } : {}),
  ...(typeof rect.scale === 'number' ? { scale: rect.scale } : {}), ...(typeof rect.opacity === 'number' ? { opacity: rect.opacity } : {}) });
const fitted = (saved) => { const rect = fromAnchored(saved, viewport()); return { ...extrasOf(rect), ...fitRect(rect, viewport()) }; };

/** The saved rectangle of a panel in pixels for this window (undefined when it sits in its default place). */
export function savedRect(id) {
  const saved = settings.panelSizes?.[id];
  return saved && typeof saved === 'object' ? fromAnchored(saved, viewport()) : undefined;
}

// Store a pixel rectangle as an anchored one. The anchor follows the panel
// (the third of the window it is in) unless it was fixed by hand.
function store(id, rect) {
  const before = settings.panelSizes?.[id];
  const anchor = rect.fixed && rect.anchor ? rect.anchor : before && before.fixed ? before.anchor : null;
  settings.panelSizes = { ...(settings.panelSizes || {}), [id]: toAnchored(rect, viewport(), anchor) };
}

/** Place a panel from code (the layout editor's inspector, the Statistics window's dock). */
export function setPanelRect(id, rect, { save = true } = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  const before = savedRect(id) || {};
  const next = { ...extrasOf(before), ...extrasOf(rect), ...fitRect(rect, viewport()), ...(rect.anchor ? { anchor: rect.anchor } : {}) };
  if (rect.auto === false) delete next.auto;
  if (rect.fixed === false) delete next.fixed;
  if (rect.scale === 1) delete next.scale;
  if (rect.opacity === 1) delete next.opacity;
  store(id, next); setRect(el, fitted(settings.panelSizes[id])); dockTimebar(); placeHandles();
  if (save) { saveSettings(); changed(); }
}

let migrated = false;
export function applyPanelSizes() {
  if (!migrated) {
    migrated = true;
    // Schema v2: pixel rectangles from older builds become anchors and fractions (saved with the next change).
    if (Object.values(settings.panelSizes || {}).some((r) => r && !isAnchored(r))) settings.panelSizes = migratePanelSizes(settings.panelSizes, viewport());
  }
  for (const [id, rect] of Object.entries(settings.panelSizes || {})) {
    const el = document.getElementById(id);
    if (el && rect && typeof rect === 'object') setRect(el, fitted(rect));
  }
  for (const [id] of slots) {
    const el = document.getElementById(id);
    if (!el?.classList.contains('hud-custom-size') || settings.panelSizes?.[id]?.moved) dropSlot(id);
  }
  dockTimebar();
  placeHandles();
}

/** Make the page match settings.panelSizes after it was replaced (a loaded layout, an undo). */
export function syncPanelSizes() {
  const sizes = settings.panelSizes || {};
  for (const el of document.querySelectorAll('.hud-custom-size')) if (!sizes[el.id]) { clearRect(el); dropSlot(el.id); }
  migrated = false;
  applyPanelSizes();
}

/** Every panel back to the layout's own place and size. */
export function resetPanelSizes() {
  settings.panelSizes = {};
  settings.panelOrder = [];
  for (const el of document.querySelectorAll('.hud-custom-size')) clearRect(el);
  saveSettings(); changed(); placeHandles();
}

/** One panel back to the layout's own place and size. */
export function resetPanel(id) {
  const sizes = { ...settings.panelSizes }; delete sizes[id]; settings.panelSizes = sizes;
  const el = document.getElementById(id);
  if (el) clearRect(el);
  dropSlot(id);
  saveSettings(); changed(); placeHandles();
}

function placeHandles() {
  if (!handleBox) return;
  // No handles where nothing may be resized: a locked layout or the OBS overlay
  // (outside the layout editor), and the phone layout.
  const locked = document.body.classList.contains('hud-phone') || (document.body.classList.contains('hud-locked') && !arranging() && !!host?.closest('#hud'));
  const visible = !move && !locked && host?.isConnected && host.getClientRects().length
    && !host.closest('.hidden, .panel-off, .collapsed') && !document.body.classList.contains('no-ui');
  handleBox.classList.toggle('hidden', !visible);
  if (!visible) return;
  // A HUD panel's handles hide under an open overlay (shell.css): the overlay
  // may open from the keyboard while the pointer still rests on the panel.
  handleBox.classList.toggle('for-hud', !!host.closest('#hud'));
  const r = host.getBoundingClientRect();
  for (const button of handleBox.children) {
    const corner = button.dataset.corner;
    if (corner.length === 1) {
      // An edge: a thin strip between the corners, mostly outside the panel so its own controls stay clickable.
      const across = corner === 'n' || corner === 's';
      button.style.left = `${across ? r.left + 12 : clamp(corner === 'w' ? r.left : r.right, 4, window.innerWidth - 2) - 4}px`;
      button.style.top = `${across ? clamp(corner === 'n' ? r.top : r.bottom, 4, window.innerHeight - 2) - 4 : r.top + 12}px`;
      button.style.width = `${across ? Math.max(0, r.width - 24) : 6}px`;
      button.style.height = `${across ? 6 : Math.max(0, r.height - 24)}px`;
    } else {
      button.style.left = `${clamp(corner.includes('w') ? r.left : r.right, 7, window.innerWidth - 7) - 7}px`;
      button.style.top = `${clamp(corner.includes('n') ? r.top : r.bottom, 7, window.innerHeight - 7) - 7}px`;
    }
    button.setAttribute('aria-label', t('Resize {panel}', { panel: host.id.replaceAll('-', ' ') }));
    button.setAttribute('aria-description', t({ nw: 'Top left', ne: 'Top right', sw: 'Bottom left', se: 'Bottom right', n: 'Top edge', s: 'Bottom edge', e: 'Right edge', w: 'Left edge' }[corner]));
  }
}

function commit(el, rect) {
  const before = savedRect(el.id);
  // Scale and opacity (set in the layout editor) stay through moves and resizes.
  const next = { ...(before ? { ...(typeof before.scale === 'number' ? { scale: before.scale } : {}), ...(typeof before.opacity === 'number' ? { opacity: before.opacity } : {}) } : {}), ...rect };
  store(el.id, next);
  setRect(el, next); dockTimebar(); placeHandles();
}

// Put back what was saved before a cancelled move or resize (the stored form, untouched).
function restore(el, raw) {
  settings.panelSizes = { ...(settings.panelSizes || {}), [el.id]: raw };
  setRect(el, fitted(raw)); dockTimebar(); placeHandles();
}

// The layout editor's extra rules: its snap grid, the safe frame as a snap
// target, and the reserved zone (a webcam) panels stay out of.
function editorRules() {
  const h = settings.hud || {};
  const vp = viewport(), z = h.reserved;
  return {
    grid: arranging() && h.snap !== false,
    frame: arranging() && h.safeArea ? safeFrame(vp) : null,
    zone: z ? { left: z.x * vp.width, top: z.y * vp.height, width: z.w * vp.width, height: z.h * vp.height } : null,
  };
}

// Snap targets: the other visible HUD panels.
function otherRects(el) {
  const out = [];
  for (const o of document.querySelectorAll('#hud .panel[id]')) {
    if (o === el || o.contains(el) || el.contains(o) || EXCLUDE.has(o.id) || o.closest('.hidden, .panel-off')) continue;
    const r = o.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) out.push({ left: r.left, top: r.top, width: r.width, height: r.height });
  }
  return out;
}

function showGuides(guides) {
  if (!guideBox) return;
  guideBox.innerHTML = guides.map((g) => `<i class="${g.axis}" style="${g.axis === 'x' ? 'left' : 'top'}:${Math.round(g.at)}px"></i>`).join('');
}

function raise(id) {
  settings.panelOrder = [...(Array.isArray(settings.panelOrder) ? settings.panelOrder : []).filter((x) => x !== id), id].slice(-12);
  for (const [pid, rect] of Object.entries(settings.panelSizes || {})) {
    const el = document.getElementById(pid);
    if (el && rect?.moved) el.style.zIndex = pid === id ? '2' : '1';
  }
}

/** Start moving a panel from a pointerdown (the ⠿ grip, or any panel in arrange mode). */
export function startMove(el, e) {
  if (!el || e.button !== 0 || drag || move) return;
  e.preventDefault(); e.stopPropagation();
  const r = el.getBoundingClientRect();
  const saved = settings.panelSizes?.[el.id];
  const rules = editorRules();
  move = { el, x: e.clientX, y: e.clientY, saved, rules, others: [...otherRects(el), ...(rules.frame ? [rules.frame] : [])],
    rect: { left: r.left, top: r.top, width: r.width, height: r.height },
    auto: saved ? !!saved.auto : true };
  raise(el.id);
  document.body.classList.add('hud-moving');
  placeHandles();
}

function moveTo(e) {
  if (!move) return;
  let rect = moveRect(move.rect, e.clientX - move.x, e.clientY - move.y, viewport()), guides = [];
  if (!e.shiftKey) {
    ({ rect, guides } = snapRect(rect, move.others, viewport()));
    // The grid takes the axes no edge claimed.
    if (move.rules.grid) {
      const g = snapToGrid(rect);
      rect = { ...rect, left: guides.some((x) => x.axis === 'x') ? rect.left : g.left, top: guides.some((x) => x.axis === 'y') ? rect.top : g.top };
    }
  }
  rect = avoidZone(rect, move.rules.zone);
  showGuides(guides);
  commit(move.el, { ...fitRect(rect, viewport()), moved: true, ...(move.auto ? { auto: true } : {}) });
}

function endMove(cancel = false) {
  if (!move) return;
  const { el, saved, x, y, last } = move;
  if (cancel) { if (saved) restore(el, saved); else resetPanel(el.id); }
  else if (!last || (Math.abs(last.x - x) < 3 && Math.abs(last.y - y) < 3)) {
    // A click on the grip, not a drag: nothing moves.
    if (saved) restore(el, saved); else { const sizes = { ...settings.panelSizes }; delete sizes[el.id]; settings.panelSizes = sizes; clearRect(el); }
  }
  move = null; showGuides([]);
  document.body.classList.remove('hud-moving');
  saveSettings(); changed(); placeHandles();
}

/** Nudge a panel with the keyboard (the grip focused): 10 px, 1 px with Shift. */
export function nudgePanel(el, dx, dy) {
  const r = el.getBoundingClientRect(), saved = savedRect(el.id);
  raise(el.id);
  commit(el, { ...moveRect({ left: r.left, top: r.top, width: r.width, height: r.height }, dx, dy, viewport()), moved: true, ...(!saved || saved.auto ? { auto: true } : {}) });
  saveSettings(); changed();
}

// -- arrange mode (Alt+L): drag any panel by its body ---------------------------------------

export function arranging() { return document.body.classList.contains('hud-arrange'); }
export function setArranging(on) {
  if (arranging() === !!on) return;
  document.body.classList.toggle('hud-arrange', on);
  const banner = document.getElementById('arrange-banner');
  // The layout editor (layout-editor.js) replaces the banner with its own bar when it is loaded.
  if (banner) banner.classList.toggle('hidden', !on || document.body.classList.contains('hud-editor'));
  document.dispatchEvent(new CustomEvent('vantage:arrange', { detail: { on: !!on } }));
  placeHandles();
}

export function installPanelResizing(onChange) {
  changed = onChange;
  handleBox = document.createElement('div');
  handleBox.id = 'panel-resize-handles'; handleBox.className = 'hidden';
  handleBox.innerHTML = corners.map(corner => `<button type="button" data-corner="${corner}" title="${t('Drag to resize · double-click to reset')}"></button>`).join('');
  document.body.appendChild(handleBox);
  guideBox = document.createElement('div');
  guideBox.id = 'panel-guides';
  document.body.appendChild(guideBox);
  const banner = document.createElement('div');
  banner.id = 'arrange-banner'; banner.className = 'panel hidden';
  banner.innerHTML = `<b>${t('Arranging panels')}</b><span>${t('Drag a panel to move it · corners resize · Shift: no snapping')}</span><button type="button" data-arrange="reset">${t('Reset layout')}</button><button type="button" data-arrange="done">${t('Done (Esc)')}</button>`;
  document.body.appendChild(banner);
  banner.addEventListener('click', (e) => {
    const b = e.target.closest('[data-arrange]');
    if (!b) return;
    if (b.dataset.arrange === 'reset') resetPanelSizes(); else setArranging(false);
    changed();
  });
  document.addEventListener('mouseover', e => {
    if (drag || move || handleBox.contains(e.target)) return;
    const target = e.target.closest?.(SELECTOR);
    host = target && !EXCLUDE.has(target.id) ? target : null;
    placeHandles();
  });
  document.addEventListener('scroll', placeHandles, true);
  window.addEventListener('resize', applyPanelSizes);
  // Arrange mode: a press anywhere on a HUD panel starts moving it.
  document.addEventListener('pointerdown', e => {
    if (!arranging() || e.button !== 0) return;
    const panel = e.target.closest?.('#hud .panel[id]');
    if (panel && !EXCLUDE.has(panel.id)) startMove(panel, e);
  }, true);
  window.addEventListener('pointermove', e => { if (move) { move.last = { x: e.clientX, y: e.clientY }; moveTo(e); } });
  window.addEventListener('pointerup', () => endMove());
  window.addEventListener('pointercancel', () => endMove(true));
  // Clicks that ended a move must not also press what was under the panel.
  document.addEventListener('click', e => { if (arranging() && e.target.closest?.('#hud .panel[id]')) { e.preventDefault(); e.stopPropagation(); } }, true);
  handleBox.addEventListener('pointerdown', e => {
    const corner = e.target.dataset.corner;
    if (!host || !corner || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const r = host.getBoundingClientRect();
    drag = { corner, x: e.clientX, y: e.clientY, others: otherRects(host),
      rect: { left: r.left, top: r.top, width: r.width, height: r.height },
      saved: settings.panelSizes?.[host.id], moved: !!savedRect(host.id)?.moved };
    e.target.setPointerCapture(e.pointerId);
    document.body.classList.add('hud-resizing');
  });
  handleBox.addEventListener('pointermove', e => {
    if (!drag) return;
    // An edge handle moves one axis only.
    const dx = /^[ns]$/.test(drag.corner) ? 0 : e.clientX - drag.x, dy = /^[ew]$/.test(drag.corner) ? 0 : e.clientY - drag.y;
    let rect = resizeRect(drag.rect, drag.corner, dx, dy, viewport(), minimum(host.id)), guides = [];
    if (!e.shiftKey) ({ rect, guides } = snapRect(rect, drag.others, viewport(), drag.corner));
    showGuides(guides);
    // A resized panel keeps where it was moved to, now at the size it was given.
    commit(host, { ...fitRect(rect, viewport()), ...(drag.moved ? { moved: true } : {}) });
  });
  function finish(cancel = false) {
    if (!drag) return;
    if (cancel) {
      if (drag.saved) restore(host, drag.saved);
      else {
        const sizes = { ...settings.panelSizes }; delete sizes[host.id]; settings.panelSizes = sizes;
        clearRect(host);
      }
    }
    drag = null; showGuides([]); document.body.classList.remove('hud-resizing');
    saveSettings(); changed(); placeHandles();
  }
  handleBox.addEventListener('pointerup', () => finish());
  handleBox.addEventListener('pointercancel', () => finish(true));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (drag) { e.preventDefault(); e.stopImmediatePropagation(); finish(true); }
    else if (move) { e.preventDefault(); e.stopImmediatePropagation(); endMove(true); }
    else if (arranging()) { e.preventDefault(); e.stopImmediatePropagation(); setArranging(false); changed(); }
  }, true);
  handleBox.addEventListener('dblclick', e => {
    if (!host || !e.target.dataset.corner) return;
    resetPanel(host.id);
  });
  handleBox.addEventListener('keydown', e => {
    if (!host || !e.target.dataset.corner || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const step = e.shiftKey ? 1 : 10, r = host.getBoundingClientRect(), saved = savedRect(host.id), corner = e.target.dataset.corner;
    const kx = /^[ns]$/.test(corner) ? 0 : e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
    const ky = /^[ew]$/.test(corner) ? 0 : e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
    commit(host, { ...resizeRect(r, corner, kx, ky, viewport(), minimum(host.id)), ...(saved?.moved ? { moved: true } : {}) });
    saveSettings(); changed();
  });
  applyPanelSizes();
}
