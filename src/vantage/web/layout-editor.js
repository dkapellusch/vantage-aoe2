// The layout editor (Alt+L, Customize → Edit layout): "use" and "edit" are
// separate modes, with a visible exit. It builds on arrange mode
// (panel-resize.js: drag any panel, snapping, guides) and adds
//
//   a bar      the scene being edited, snap grid, safe area, the reserved
//              (webcam) zone, Undo, Reset, Done
//   a library  every panel and widget; the ones on screen are marked
//   an inspector for the selected panel: size, scale, opacity, anchor, the
//              scenes it shows in, its content, and the stream-safe checks
//
// Every drag has a keyboard equivalent: Tab reaches a panel, arrows move it
// (Shift: 1 px), Alt+arrows resize it, Delete hides it, Ctrl+Z undoes.
// Loaded on first use.

import { settings, saveSettings, esc, tip } from './state.js';
import { t } from './i18n.js';
import { PANELS, panelInfo, hud, setHud, isVisible, setVisible, setEditorScene, togglePanelsMenu, PRESETS } from './layout.js';
import { SCENES, ANCHORS, safeFrame } from './hud-model.js';
import { arranging, setArranging, pinHandles, savedRect, setPanelRect, resetPanel, resetPanelSizes, syncPanelSizes, nudgePanel, resizeRect } from './panel-resize.js';
import { panelChecks } from './stream-check.js';
import { SERIES_LABEL, seriesLabel } from './overlays.js';

const $ = (id) => document.getElementById(id);
const hostOf = (id) => { const p = panelInfo(id); return $(p && p.host ? p.host : id); };
const idOfHost = (hostId) => { const p = PANELS.find((x) => (x.host || x.id) === hostId); return p ? p.id : null; };
const vp = () => ({ width: window.innerWidth, height: window.innerHeight });
const ANCHOR_NAMES = { tl: 'Top left', t: 'Top', tr: 'Top right', l: 'Left', c: 'Centre', r: 'Right', bl: 'Bottom left', b: 'Bottom', br: 'Bottom right' };
const GROUPS = [['Panels', (p) => !p.widget], ['Single metrics', (p) => p.widget === 'metric'], ['Charts', (p) => p.widget === 'chart' || p.id === 'story'], ['Casting', (p) => p.widget === 'casting']];
const UNDO_KEYS = ['hud', 'panelSizes', 'panelOrder', 'hiddenPanels', 'collapsedPanels', 'showProduction', 'showDashboard', 'showEvents', 'showStaticTechs', 'disableScoreboard'];

export function installLayoutEditor(ctx) {
  let selected = null, scene = null, history = [];
  const root = document.createElement('div');
  root.id = 'layout-editor'; root.className = 'hidden';
  root.innerHTML = `<div id="le-grid" aria-hidden="true"></div><div id="le-safe" aria-hidden="true"><span>${esc(t('Safe area'))}</span></div>
    <div id="le-zone" class="hidden" tabindex="0" role="group" aria-label="${esc(t('Reserved zone: panels keep out of it. Drag to move, arrow keys nudge.'))}"><span>${esc(t('Reserved: webcam'))}</span><i data-zone-size aria-hidden="true"></i></div>
    <div id="le-bar" class="panel" role="toolbar" aria-label="${esc(t('Edit layout'))}"></div>
    <aside id="le-lib" class="panel" aria-label="${esc(t('Widget library'))}"></aside>
    <aside id="le-insp" class="panel" aria-label="${esc(t('Inspector'))}"></aside>
    <button type="button" id="le-lib-tab" data-le-unfold="lib" aria-label="${esc(t('Show the library'))}">▸ ${esc(t('Library'))}</button>
    <button type="button" id="le-insp-tab" data-le-unfold="insp" aria-label="${esc(t('Show the inspector'))}">${esc(t('Inspector'))} ◂</button>`;
  document.body.appendChild(root);
  const bar = $('le-bar'), lib = $('le-lib'), insp = $('le-insp'), zone = $('le-zone');

  // -- undo ---------------------------------------------------------------------------------
  const snapshot = () => JSON.stringify(Object.fromEntries(UNDO_KEYS.map((k) => [k, settings[k]])));
  const remember = () => { const s = snapshot(); if (history[history.length - 1] !== s) { history.push(s); if (history.length > 60) history.shift(); } };
  function undo() {
    // Drop snapshots equal to the present (a press that changed nothing), then go back one.
    const now = snapshot();
    while (history.length && history[history.length - 1] === now) history.pop();
    const prev = history.pop();
    if (!prev) { ctx.toast(t('Nothing to undo')); return; }
    Object.assign(settings, JSON.parse(prev));
    setHud(settings.hud);
    syncPanelSizes();
    refresh();
    ctx.onChange();
  }

  // -- the bar ----------------------------------------------------------------------------------
  function renderBar() {
    const h = hud(), name = h.layoutName || t((PRESETS[h.preset] || { label: 'Custom' }).label);
    bar.innerHTML = `<b class="le-title">${esc(t('EDIT LAYOUT'))}</b><button type="button" data-le="layouts" ${tip(t('Saved layouts'), t('Save, load, export and import layouts in Customize'))}>${esc(name)} ▾</button>
      <span class="le-scenes" role="radiogroup" aria-label="${esc(t('Scene shown while editing'))}">${[[null, 'Live'], ...SCENES].map(([id, label]) => `<button type="button" role="radio" aria-checked="${scene === id}" data-le-scene="${id || ''}" ${id ? '' : tip(t('Live'), t('Whichever scene the match is in'))}>${esc(t(label))}</button>`).join('')}</span>
      <label ${tip(t('Snap'), t('Positions snap to an 8 px grid and to other panels. Shift while dragging: free'))}><input type="checkbox" data-le-flag="snap" ${h.snap !== false ? 'checked' : ''}> ${esc(t('Snap'))}</label>
      <label ${tip(t('Safe area'), t('Show the title-safe frame and snap to it'))}><input type="checkbox" data-le-flag="safeArea" ${h.safeArea ? 'checked' : ''}> ${esc(t('Safe area'))}</label>
      <label ${tip(t('Webcam zone'), t('A reserved rectangle panels are pushed out of'))}><input type="checkbox" data-le-zone ${h.reserved ? 'checked' : ''}> ${esc(t('Webcam zone'))}</label>
      <span class="le-size" aria-label="${esc(t('Window size'))}">${window.innerWidth}×${window.innerHeight}</span>
      <button type="button" data-le="undo" ${history.length ? '' : 'disabled'} ${tip(t('Undo'), 'Ctrl+Z')}>${esc(t('Undo'))}</button>
      <button type="button" data-le="reset" ${tip(t('Reset layout'), t('Every panel back to its place and size'))}>${esc(t('Reset'))}</button>
      <button type="button" data-le="done" class="le-done">${esc(t('Done'))} · Esc</button>`;
  }

  // -- the library ------------------------------------------------------------------------------
  function renderLib() {
    // A name adds the panel (or selects it when it is already on screen); ✕ takes it off.
    const item = (p) => { const on = isVisible(p.id); return `<div class="le-item${on ? ' on' : ''}${selected === p.id ? ' sel' : ''}"><button type="button" data-le-add="${p.id}" aria-pressed="${on}" ${p.detail ? tip(t(p.label), t(p.detail)) : ''}>${esc(t(p.label))}</button>${on ? `<button type="button" data-le-remove="${p.id}" aria-label="${esc(t('Remove {p}', { p: t(p.label) }))}">✕</button>` : ''}</div>`; };
    lib.innerHTML = `<div class="le-pane-head"><h2>${esc(t('Library'))}</h2><button type="button" data-le-fold="lib" aria-expanded="true" aria-label="${esc(t('Fold the library'))}">◂</button></div><p class="hint">${esc(t('Press a name to add it, or to select it when it is on screen (✓).'))}</p>
      ${GROUPS.map(([title, test]) => `<h3>${esc(t(title))}</h3><div class="le-items">${PANELS.filter(test).map(item).join('')}</div>`).join('')}`;
  }

  // -- the inspector -------------------------------------------------------------------------------
  function contentHtml(id) {
    const w = (hud().widgets || {})[id] || {};
    if (id === 'focus') return `<label>${esc(t('Card'))} <select data-le-focus>${[['production', 'Production & composition'], ['techs', 'Research'], ['eco', 'Economy'], ['fight', 'Last fight'], ['none', 'Empty']].map(([k, l]) => `<option value="${k}" ${hud().focus === k ? 'selected' : ''}>${esc(t(l))}</option>`).join('')}</select></label>`;
    if (id === 'w-chart') return `<label>${esc(t('Series'))} <select data-le-widget="series">${Object.keys(SERIES_LABEL).map((k) => `<option value="${k}" ${(w.series || 'army_value') === k ? 'selected' : ''}>${esc(seriesLabel(k))}</option>`).join('')}</select></label>`;
    if (id === 'w-text') return `<label>${esc(t('Text'))} <input data-le-widget="text" maxlength="200" value="${esc(w.text || '')}"></label><label>${esc(t('Image address'))} <input data-le-widget="image" maxlength="2000" placeholder="https://…" value="${esc(w.image || '')}"></label>`;
    if (id === 'pulse') return `<p class="hint">${esc(t('Its metrics are ticked in Customize → Pulse strip metrics.'))}</p>`;
    return '';
  }

  function renderInsp() {
    const p = selected && panelInfo(selected), el = p && hostOf(selected);
    if (!p || !el || !el.getClientRects().length) {
      insp.innerHTML = `<div class="le-pane-head"><h2>${esc(t('Inspector'))}</h2><button type="button" data-le-fold="insp" aria-expanded="true" aria-label="${esc(t('Fold the inspector'))}">▸</button></div><p class="hint">${esc(t('Select a panel: click it, or Tab to it. Arrows move it, Alt+arrows resize it, Delete hides it.'))}</p>`;
      return;
    }
    const r = el.getBoundingClientRect(), saved = savedRect(el.id) || {}, v = vp();
    const raw = (settings.panelSizes || {})[el.id] || {};
    const pct = (n, of) => Math.round((100 * n) / of);
    const num = (key, label, value, min, max) => `<label>${esc(t(label))} <input type="number" data-le-num="${key}" min="${min}" max="${max}" step="1" value="${value}"></label>`;
    const hide = (hud().sceneHide || {})[selected] || [];
    const content = contentHtml(selected);
    insp.innerHTML = `<div class="le-pane-head"><h2>${esc(t(p.label))}</h2><button type="button" data-le-fold="insp" aria-expanded="true" aria-label="${esc(t('Fold the inspector'))}">▸</button></div>
      <p class="hint">${Math.round(r.width)} × ${Math.round(r.height)} · ${esc(saved.moved ? t('floating') : el.classList.contains('hud-custom-size') ? t('resized in place') : t('docked in its default place'))}</p>
      <div class="le-fields">${num('width', 'Width %', pct(r.width, v.width), 5, 100)}${num('height', 'Height %', pct(r.height, v.height), 5, 100)}${num('scale', 'Scale %', Math.round((saved.scale || 1) * 100), 50, 200)}${num('opacity', 'Opacity %', Math.round((saved.opacity ?? 1) * 100), 20, 100)}</div>
      <h3>${esc(t('Anchor'))}</h3>
      <div class="le-anchors" role="radiogroup" aria-label="${esc(t('Anchor: the corner or edge of the window the panel holds on to'))}">${ANCHORS.map((a) => `<button type="button" role="radio" aria-checked="${raw.anchor === a}" data-le-anchor="${a}" aria-label="${esc(t(ANCHOR_NAMES[a]))}" title="${esc(t(ANCHOR_NAMES[a]))}"></button>`).join('')}</div>
      <h3>${esc(t('Show in scenes'))}</h3>
      <div class="le-checks">${SCENES.map(([id, label]) => `<label><input type="checkbox" data-le-scene-show="${id}" ${hide.includes(id) ? '' : 'checked'}> ${esc(t(label))}</label>`).join('')}</div>
      <h3>${esc(t('Stream check'))}</h3>
      <ul class="le-stream">${panelChecks(el).map((c) => `<li class="${c.ok ? 'ok' : 'warn'}"><span aria-hidden="true">${c.ok ? '✓' : '!'}</span> ${esc(t(c.text, c.args))}</li>`).join('')}</ul>
      ${content ? `<h3>${esc(t('Content'))}</h3><div class="le-content">${content}</div>` : ''}
      <div class="le-actions"><button type="button" data-le="dock" ${tip(t('Dock'), t('Back to its default place and size'))}>${esc(t('Dock'))}</button><button type="button" data-le="hide">${esc(t('Hide'))}</button></div>`;
  }

  function placeStage() {
    const h = hud(), v = vp(), f = safeFrame(v), safe = $('le-safe');
    $('le-grid').classList.toggle('hidden', h.snap === false);
    safe.classList.toggle('hidden', !h.safeArea);
    Object.assign(safe.style, { left: `${f.left}px`, top: `${f.top}px`, width: `${f.width}px`, height: `${f.height}px` });
    zone.classList.toggle('hidden', !h.reserved);
    if (h.reserved) Object.assign(zone.style, { left: `${h.reserved.x * v.width}px`, top: `${h.reserved.y * v.height}px`, width: `${h.reserved.w * v.width}px`, height: `${h.reserved.h * v.height}px` });
  }

  function select(id) {
    selected = id && panelInfo(id) && isVisible(id) ? id : null;
    for (const el of document.querySelectorAll('#hud .le-selected')) el.classList.remove('le-selected');
    const el = selected && hostOf(selected);
    if (el) el.classList.add('le-selected');
    pinHandles(el || null);
    renderInsp();
    for (const row of lib.querySelectorAll('.le-item')) row.classList.toggle('sel', !!selected && row.querySelector(`[data-le-add="${selected}"]`) != null);
  }

  function refresh() {
    if (!arranging()) return;
    // Panels are reachable by Tab while editing.
    for (const p of PANELS) { const el = hostOf(p.id); if (el) { el.tabIndex = 0; el.setAttribute('aria-label', t(p.label)); } }
    renderBar(); renderLib(); placeStage();
    if (selected && !isVisible(selected)) select(null); else renderInsp();
  }

  function show(on) {
    document.body.classList.toggle('hud-editor', on);
    root.classList.toggle('hidden', !on);
    const banner = $('arrange-banner');
    if (banner) banner.classList.add('hidden');
    if (on) { history = []; scene = null; refresh(); bar.querySelector('.le-done').focus({ preventScroll: true }); }
    else {
      select(null); pinHandles(null); setEditorScene(null);
      for (const p of PANELS) { const el = hostOf(p.id); if (el) el.removeAttribute('tabindex'); }
      saveSettings();
    }
    ctx.onChange();
  }

  document.addEventListener('vantage:arrange', (e) => show(!!e.detail.on));
  document.addEventListener('vantage:panel-press', (e) => { remember(); select(idOfHost(e.detail.id)); });
  document.addEventListener('vantage:hud-changed', () => { if (arranging()) refresh(); });
  window.addEventListener('resize', () => { if (arranging()) refresh(); });
  // After a drag or a resize: the inspector shows the new size.
  window.addEventListener('pointerup', () => { if (arranging()) setTimeout(() => { renderInsp(); renderBar(); }, 0); });

  // -- the bar's controls ---------------------------------------------------------------------------
  bar.addEventListener('click', (e) => {
    const sc = e.target.closest('[data-le-scene]');
    if (sc) { scene = sc.dataset.leScene || null; setEditorScene(scene); refresh(); ctx.onChange(); return; }
    const b = e.target.closest('[data-le]');
    if (!b) return;
    if (b.dataset.le === 'done') setArranging(false);
    else if (b.dataset.le === 'undo') undo();
    else if (b.dataset.le === 'reset') { remember(); resetPanelSizes(); refresh(); }
    else if (b.dataset.le === 'layouts') { setArranging(false); togglePanelsMenu(); }
    ctx.onChange();
  });
  bar.addEventListener('change', (e) => {
    remember();
    if (e.target.dataset.leFlag) setHud({ ...hud(), [e.target.dataset.leFlag]: e.target.checked });
    else if ('leZone' in e.target.dataset) setHud({ ...hud(), reserved: e.target.checked ? { x: 0.76, y: 0.1, w: 0.2, h: 0.26 } : null });
    refresh();
  });

  // Fold a pane to its edge to reach what is under it; the tab that is left unfolds it.
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-le-fold], [data-le-unfold]');
    if (!b) return;
    const which = b.dataset.leFold || b.dataset.leUnfold;
    root.classList.toggle(`fold-${which}`, !!b.dataset.leFold);
    const other = root.querySelector(b.dataset.leFold ? `[data-le-unfold="${which}"]` : `[data-le-fold="${which}"]`);
    if (other) other.focus({ preventScroll: true });
  });

  lib.addEventListener('click', (e) => {
    const rm = e.target.closest('[data-le-remove]');
    if (rm) { remember(); setVisible(rm.dataset.leRemove, false); refresh(); ctx.onChange(); const b = lib.querySelector(`[data-le-add="${rm.dataset.leRemove}"]`); if (b) b.focus({ preventScroll: true }); return; }
    const b = e.target.closest('[data-le-add]');
    if (!b) return;
    const id = b.dataset.leAdd;
    if (!isVisible(id)) { remember(); setVisible(id, true); ctx.onChange(); }
    // The panel may be created by a module that is still loading: select it once it is there.
    const pick = (tries) => { if (isVisible(id) && hostOf(id)) { refresh(); select(id); const again = lib.querySelector(`[data-le-add="${id}"]`); if (again) again.focus({ preventScroll: true }); } else if (tries > 0) setTimeout(() => pick(tries - 1), 150); };
    pick(20);
  });

  // -- the inspector's controls -----------------------------------------------------------------------
  insp.addEventListener('change', (e) => {
    const d = e.target.dataset, el = selected && hostOf(selected);
    if (!el) return;
    remember();
    const r = el.getBoundingClientRect(), v = vp(), rect = { left: r.left, top: r.top, width: r.width, height: r.height };
    if (d.leNum) {
      const n = Math.max(+e.target.min, Math.min(+e.target.max, +e.target.value || 0));
      if (d.leNum === 'width') setPanelRect(el.id, { ...rect, width: (n / 100) * v.width, auto: false });
      else if (d.leNum === 'height') setPanelRect(el.id, { ...rect, height: (n / 100) * v.height, auto: false });
      else if (d.leNum === 'scale') setPanelRect(el.id, { ...rect, width: r.width, height: r.height, scale: n / 100, ...(savedRect(el.id) ? {} : { auto: true, moved: true }) });
      else if (d.leNum === 'opacity') setPanelRect(el.id, { ...rect, opacity: n / 100, ...(savedRect(el.id) ? {} : { auto: true, moved: true }) });
    } else if (d.leSceneShow) {
      const now = ((hud().sceneHide || {})[selected] || []).filter((s) => s !== d.leSceneShow);
      const next = e.target.checked ? now : [...now, d.leSceneShow];
      const sceneHide = { ...(hud().sceneHide || {}) };
      if (next.length) sceneHide[selected] = next; else delete sceneHide[selected];
      setHud({ ...hud(), sceneHide });
    } else if ('leFocus' in d) setHud({ ...hud(), focus: e.target.value });
    else if (d.leWidget) setHud({ ...hud(), widgets: { ...(hud().widgets || {}), [selected]: { ...((hud().widgets || {})[selected] || {}), [d.leWidget]: e.target.value } } });
    ctx.onChange();
    setTimeout(renderInsp, 0);
  });
  insp.addEventListener('click', (e) => {
    const el = selected && hostOf(selected);
    if (!el) return;
    const a = e.target.closest('[data-le-anchor]');
    if (a) {
      remember();
      const r = el.getBoundingClientRect();
      setPanelRect(el.id, { left: r.left, top: r.top, width: r.width, height: r.height, anchor: a.dataset.leAnchor, fixed: true, moved: true, ...(savedRect(el.id) ? {} : { auto: true }) });
      renderInsp();
      const again = insp.querySelector(`[data-le-anchor="${a.dataset.leAnchor}"]`);
      if (again) again.focus();
      return;
    }
    const b = e.target.closest('[data-le]');
    if (!b) return;
    remember();
    if (b.dataset.le === 'dock') { resetPanel(el.id); renderInsp(); }
    else if (b.dataset.le === 'hide') { setVisible(selected, false); refresh(); }
    ctx.onChange();
  });

  // -- keyboard: every drag has an arrow-key equivalent ------------------------------------------------
  document.addEventListener('focusin', (e) => {
    if (!arranging()) return;
    const id = e.target.closest ? idOfHost((e.target.closest('#hud .panel[id]') || {}).id) : null;
    if (id && id !== selected && e.target.matches('#hud .panel[id]')) select(id);
  });
  document.addEventListener('keydown', (e) => {
    if (!arranging()) return;
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.code === 'KeyZ') { e.preventDefault(); e.stopImmediatePropagation(); undo(); return; }
    const onPanel = e.target.matches && e.target.matches('#hud .panel[id], #le-zone');
    if (!onPanel) return;
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (e.target === zone) {
      if (!d) return;
      e.preventDefault(); e.stopImmediatePropagation();
      const z = hud().reserved, step = (e.shiftKey ? 1 : 10);
      remember();
      setHud({ ...hud(), reserved: e.altKey
        ? { ...z, w: Math.max(0.05, z.w + (d[0] * step) / window.innerWidth), h: Math.max(0.05, z.h + (d[1] * step) / window.innerHeight) }
        : { ...z, x: Math.max(0, Math.min(1 - z.w, z.x + (d[0] * step) / window.innerWidth)), y: Math.max(0, Math.min(1 - z.h, z.y + (d[1] * step) / window.innerHeight)) } });
      placeStage();
      return;
    }
    const el = selected && hostOf(selected);
    if (!el || e.target !== el) return;
    if (d) {
      e.preventDefault(); e.stopImmediatePropagation();
      remember();
      const step = e.shiftKey ? 1 : 10;
      if (e.altKey) {
        const r = el.getBoundingClientRect();
        setPanelRect(el.id, { ...resizeRect({ left: r.left, top: r.top, width: r.width, height: r.height }, 'se', d[0] * step, d[1] * step, vp(), { width: 80, height: 40 }), auto: false, ...(savedRect(el.id)?.moved ? { moved: true } : {}) });
      } else nudgePanel(el, d[0] * step, d[1] * step);
      renderInsp();
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault(); e.stopImmediatePropagation();
      remember(); setVisible(selected, false); refresh(); ctx.onChange();
    }
  }, true);

  // -- the reserved zone: drag to move, its corner to resize ----------------------------------------------
  let zdrag = null;
  zone.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    remember();
    const z = hud().reserved;
    zdrag = { x: e.clientX, y: e.clientY, z, size: !!e.target.closest('[data-zone-size]') };
    zone.setPointerCapture(e.pointerId); e.preventDefault(); e.stopPropagation();
  });
  zone.addEventListener('pointermove', (e) => {
    if (!zdrag) return;
    const dx = (e.clientX - zdrag.x) / window.innerWidth, dy = (e.clientY - zdrag.y) / window.innerHeight, z = zdrag.z;
    const next = zdrag.size ? { ...z, w: Math.max(0.05, Math.min(1 - z.x, z.w + dx)), h: Math.max(0.05, Math.min(1 - z.y, z.h + dy)) }
      : { ...z, x: Math.max(0, Math.min(1 - z.w, z.x + dx)), y: Math.max(0, Math.min(1 - z.h, z.y + dy)) };
    settings.hud = { ...hud(), reserved: next };
    placeStage();
  });
  const zend = () => { if (zdrag) { zdrag = null; setHud(hud()); } };
  zone.addEventListener('pointerup', zend); zone.addEventListener('pointercancel', zend);

  return {
    toggle() { setArranging(!arranging()); },
    isOpen: () => arranging(),
    undo,
  };
}
