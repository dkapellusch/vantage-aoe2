import { settings, saveSettings } from './state.js';
import { t } from './i18n.js';

const SELECTOR = '.panel[id], .overlay[id], .review-surface[id]';
const EXCLUDE = new Set(['omni-menu', 'panels-menu', 'jump-banner', 'launch-status', 'autocast-banner']);
const corners = ['nw', 'ne', 'sw', 'se'];
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

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

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });
const minimum = id => ({ width: id === 'minimap-wrap' ? 180 : 220, height: id === 'scoreboard' ? 60 : 90 });
let handleBox, host = null, drag = null, changed = () => {};
const slots = new Map();

function syncSlot(el, rect) {
  if (!['leftcol', 'leftcol2'].includes(el.parentElement?.id)) return;
  let slot = slots.get(el.id);
  if (!slot) {
    slot = document.createElement('div'); slot.className = 'panel-size-slot';
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

function setRect(el, rect) {
  el.classList.add('hud-custom-size');
  for (const key of ['left', 'top', 'width', 'height']) el.style.setProperty(`--panel-${key}`, `${rect[key]}px`);
  syncSlot(el, rect);
}

export function applyPanelSizes() {
  for (const [id, rect] of Object.entries(settings.panelSizes || {})) {
    const el = document.getElementById(id);
    if (el && rect && typeof rect === 'object') setRect(el, fitRect(rect, viewport()));
  }
  for (const [id, slot] of slots) {
    if (!document.getElementById(id)?.classList.contains('hud-custom-size')) {
      slot.remove(); slots.delete(id);
    }
  }
  dockTimebar();
  placeHandles();
}

export function resetPanelSizes() {
  settings.panelSizes = {};
  for (const el of document.querySelectorAll('.hud-custom-size')) {
    el.classList.remove('hud-custom-size');
    for (const key of ['left', 'top', 'width', 'height']) el.style.removeProperty(`--panel-${key}`);
  }
  saveSettings(); changed(); placeHandles();
}

function placeHandles() {
  if (!handleBox) return;
  const visible = host?.isConnected && host.getClientRects().length
    && !host.closest('.hidden, .panel-off, .collapsed') && !document.body.classList.contains('no-ui');
  handleBox.classList.toggle('hidden', !visible);
  if (!visible) return;
  const r = host.getBoundingClientRect();
  for (const button of handleBox.children) {
    const corner = button.dataset.corner;
    button.style.left = `${clamp(corner.includes('w') ? r.left : r.right, 7, window.innerWidth - 7) - 7}px`;
    button.style.top = `${clamp(corner.includes('n') ? r.top : r.bottom, 7, window.innerHeight - 7) - 7}px`;
    button.setAttribute('aria-label', t('Resize {panel}', { panel: host.id.replaceAll('-', ' ') }));
    button.setAttribute('aria-description', t({ nw: 'Top left', ne: 'Top right', sw: 'Bottom left', se: 'Bottom right' }[corner]));
  }
}

function commit(rect) {
  settings.panelSizes = { ...(settings.panelSizes || {}), [host.id]: rect };
  setRect(host, rect); dockTimebar(); placeHandles();
}

export function installPanelResizing(onChange) {
  changed = onChange;
  handleBox = document.createElement('div');
  handleBox.id = 'panel-resize-handles'; handleBox.className = 'hidden';
  handleBox.innerHTML = corners.map(corner => `<button type="button" data-corner="${corner}" title="${t('Drag to resize · double-click to reset')}"></button>`).join('');
  document.body.appendChild(handleBox);
  document.addEventListener('mouseover', e => {
    if (drag || handleBox.contains(e.target)) return;
    const target = e.target.closest?.(SELECTOR);
    host = target && !EXCLUDE.has(target.id) ? target : null;
    placeHandles();
  });
  document.addEventListener('scroll', placeHandles, true);
  window.addEventListener('resize', applyPanelSizes);
  handleBox.addEventListener('pointerdown', e => {
    const corner = e.target.dataset.corner;
    if (!host || !corner || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const r = host.getBoundingClientRect();
    drag = { corner, x: e.clientX, y: e.clientY,
      rect: { left: r.left, top: r.top, width: r.width, height: r.height },
      saved: settings.panelSizes?.[host.id] };
    e.target.setPointerCapture(e.pointerId);
    document.body.classList.add('hud-resizing');
  });
  handleBox.addEventListener('pointermove', e => {
    if (!drag) return;
    commit(resizeRect(drag.rect, drag.corner, e.clientX - drag.x, e.clientY - drag.y, viewport(), minimum(host.id)));
  });
  function finish(cancel = false) {
    if (!drag) return;
    if (cancel) {
      if (drag.saved) commit(drag.saved);
      else {
        const sizes = { ...settings.panelSizes }; delete sizes[host.id]; settings.panelSizes = sizes;
        host.classList.remove('hud-custom-size');
      }
    }
    drag = null; document.body.classList.remove('hud-resizing');
    saveSettings(); changed(); placeHandles();
  }
  handleBox.addEventListener('pointerup', () => finish());
  handleBox.addEventListener('pointercancel', () => finish(true));
  document.addEventListener('keydown', e => { if (drag && e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); finish(true); } }, true);
  handleBox.addEventListener('dblclick', e => {
    if (!host || !e.target.dataset.corner) return;
    const sizes = { ...settings.panelSizes }; delete sizes[host.id]; settings.panelSizes = sizes;
    host.classList.remove('hud-custom-size'); saveSettings(); changed(); placeHandles();
  });
  handleBox.addEventListener('keydown', e => {
    if (!host || !e.target.dataset.corner || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const step = e.shiftKey ? 1 : 10, r = host.getBoundingClientRect();
    commit(resizeRect(r, e.target.dataset.corner, e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0,
      e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0, viewport(), minimum(host.id)));
    saveSettings(); changed();
  });
  applyPanelSizes();
}
