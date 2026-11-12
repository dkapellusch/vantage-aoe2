// The Customize drawer (Alt+V, ▣ by the minimap): three levels, and most
// people stop at the first. Pick a preset; tick panels; tick metrics inside a
// panel. Below that: the layout (edit mode, saved layouts, lock), the share
// link (the same hash drives the ?overlay=1 OBS page) and reset.
//
// Loaded on first use. Every control is a real button or checkbox, the preset
// row is a radio group (arrow keys), Esc closes and returns the focus to the
// toolbar button.

import { settings, saveSettings, esc, api, tip } from './state.js';
import { t } from './i18n.js';
import { binding } from './hotkeys.js';
import {
  PANELS, PRESETS, PRESET_ORDER, hud, setHud, applyPreset, isVisible, setVisible, isCollapsed, setCollapsed, presetIsChanged,
  restorePresetDefault, pulseMetrics, setPulseMetric, shareHash, LAYOUTS, hudLayout, setHudLayout, toggleEditLayout,
  showEverything, resetHud, applyPanels, scene,
} from './layout.js';
import { PULSE_METRICS, PULSE_METRIC_LABELS, CUSTOM, snapshotLayout, layoutPatch, SCENES } from './hud-model.js';
import { METRICS } from './metrics.js';
import { SECTIONS } from './team-board.js';
import { resetPanelSizes, syncPanelSizes } from './panel-resize.js';
import { panelChecks } from './stream-check.js';

const $ = (id) => document.getElementById(id);
const key = (action) => { const k = action ? binding(action) : '—'; return k && k !== '—' ? `<kbd>${esc(k)}</kbd>` : ''; };
const ROW_IDS = SECTIONS.flatMap((s) => s.rows.map((r) => r.id)).filter(Boolean);

function presetsHtml() {
  const h = hud(), names = [...PRESET_ORDER, ...(h.preset === CUSTOM || h.edits[CUSTOM] ? [CUSTOM] : [])];
  const buttons = names.map((name) => {
    const p = PRESETS[name] || { label: 'Custom', detail: 'From a shared link' };
    const on = h.preset === name, changed = name !== CUSTOM && presetIsChanged(name);
    return `<button type="button" role="radio" aria-checked="${on}" tabindex="${on ? 0 : -1}" data-preset="${name}" ${tip(t(p.label), t(p.detail))}>
      <span>${esc(t(p.label))}${changed ? `<i class="cz-dot" title="${esc(t('Changed from its default'))}"></i><span class="sr-only"> (${esc(t('changed'))})</span>` : ''}</span>${key(p.action)}</button>`;
  }).join('');
  const cur = PRESETS[h.preset] || { detail: 'From a shared link' };
  const restore = h.preset !== CUSTOM && presetIsChanged(h.preset) ? `<button type="button" data-cz="restore">${esc(t('Restore default'))}</button>` : '';
  return `<div class="cz-presets" role="radiogroup" aria-label="${esc(t('HUD preset'))}">${buttons}</div>
    <p class="hint cz-detail">${esc(t(cur.detail))}. ${restore} ${t('Hold {key} to peek at the Full HUD.', { key: `<kbd>${esc(binding('peekFullHud'))}</kbd>` })}</p>`;
}

function panelRow(p) {
  const on = isVisible(p.id);
  return `<div class="cz-row"><label ${p.detail ? tip(t(p.label), t(p.detail)) : ''}><input type="checkbox" data-cz-show="${p.id}" ${on ? 'checked' : ''}> ${esc(t(p.label))}</label>${key(p.action)}${p.collapse ? `<button type="button" data-cz-collapse="${p.id}" aria-pressed="${isCollapsed(p.id)}" aria-label="${esc(t('Collapse {p} to its top strip', { p: t(p.label) }))}">${isCollapsed(p.id) ? '▾' : '▴'}</button>` : ''}</div>`;
}

function panelsHtml() {
  const main = PANELS.filter((p) => !p.widget), widgets = PANELS.filter((p) => p.widget);
  const anyWidget = widgets.some((p) => isVisible(p.id));
  return `${main.map(panelRow).join('')}
    <details class="cz-more" ${anyWidget ? 'open' : ''}><summary>${esc(t('Single metrics, a chart and casting widgets'))}</summary>${widgets.map(panelRow).join('')}</details>`;
}

function metricsHtml() {
  const on = pulseMetrics(), pulse = isVisible('pulse');
  return `<div class="cz-grid" ${pulse ? '' : `title="${esc(t('Shown when the Pulse strip is on'))}"`}>${PULSE_METRICS.map((id) => `<label><input type="checkbox" data-cz-metric="${id}" ${on.includes(id) ? 'checked' : ''}> ${esc(t(PULSE_METRIC_LABELS[id]))}</label>`).join('')}</div>`;
}

function rowsHtml() {
  const hidden = hud().hiddenRows || [];
  return `<div class="cz-grid">${ROW_IDS.map((id) => `<label><input type="checkbox" data-cz-row="${id}" ${hidden.includes(id) ? '' : 'checked'}> ${esc(t(METRICS[id].label))}</label>`).join('')}</div>`;
}

function layoutHtml() {
  const h = hud(), full = h.preset === 'full';
  const names = Object.keys(h.layouts || {}).sort();
  return `${full ? `<div class="cz-line"><span class="hint">${esc(t('Placement'))}</span>${LAYOUTS.map(([k, l]) => `<button type="button" data-cz-layout="${k}" aria-pressed="${hudLayout() === k}">${esc(t(l))}</button>`).join('')}<button type="button" data-cz="everything" ${tip(t('Everything'), t('Every panel, none collapsed'))}>${esc(t('Everything'))}</button></div>` : ''}
    <div class="cz-line"><button type="button" data-cz="edit" class="cz-primary" ${tip(t('Edit layout'), t('Drag panels, resize them, add widgets, set anchors and scenes'))}>${esc(t('Edit layout…'))} ${key('arrangePanels')}</button><button type="button" data-cz="reset-layout" ${tip(t('Reset layout'), t('Every panel back to its place and size'))}>${esc(t('Reset layout'))}</button></div>
    <label class="cz-check" ${tip(t('Lock panels'), t('Nothing moves or resizes by accident while watching: only Edit layout can'))}><input type="checkbox" data-cz-flag="lock" ${h.lock ? 'checked' : ''}> ${esc(t('Lock panels outside Edit layout'))}</label>
    <label class="cz-check" ${tip(t('Hide duplicates'), t('With the Team board on screen, the dashboard Overview drops Villagers, Idle, Military and Army value'))}><input type="checkbox" data-cz-flag="dedupe" ${h.dedupe ? 'checked' : ''}> ${esc(t('Hide dashboard columns the Team board shows'))}</label>
    <div class="cz-line"><label class="sr-only" for="cz-layout-list">${esc(t('Saved layouts'))}</label><select id="cz-layout-list"><option value="">${esc(t('Saved layouts…'))}</option>${names.map((n) => `<option value="${esc(n)}" ${n === h.layoutName ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      <button type="button" data-cz="load-layout">${esc(t('Load'))}</button><button type="button" data-cz="delete-layout">${esc(t('Delete'))}</button></div>
    <div class="cz-line"><label class="sr-only" for="cz-layout-name">${esc(t('Layout name'))}</label><input id="cz-layout-name" size="14" maxlength="40" placeholder="${esc(t('Layout name'))}" value="${esc(h.layoutName || '')}">
      <button type="button" data-cz="save-layout" ${tip(t('Save layout'), t('Panels, metrics, positions and scenes under a name, in this browser'))}>${esc(t('Save'))}</button>
      <button type="button" data-cz="publish-layout" ${tip(t('Publish for OBS'), t('Also store it as a settings profile on this Vantage, so an OBS browser source can load it by name'))}>${esc(t('Publish for OBS'))}</button></div>
    <div class="cz-line"><button type="button" data-cz="export-layout">${esc(t('Export to file'))}</button><label class="filebtn">${esc(t('Import from file'))}<input type="file" id="cz-import" accept=".json,application/json" hidden></label></div>`;
}

function shareUrls() {
  const base = `${location.origin}${location.pathname}`, params = new URLSearchParams(location.search);
  params.delete('overlay'); params.delete('hud');
  const q = params.toString(), h = hud(), sc = h.scene && h.scene !== 'auto' ? `.${h.scene}` : '';
  const named = h.layoutName && (h.layouts || {})[h.layoutName] ? `&layout=${encodeURIComponent(h.layoutName)}` : '';
  return {
    link: `${base}${q ? `?${q}` : ''}#${shareHash()}`,
    obs: `${base}?overlay=1${q ? `&${q}` : ''}#${shareHash()}${sc}${named}`,
  };
}

function shareHtml() {
  const u = shareUrls();
  return `<div class="cz-line"><label class="sr-only" for="cz-link">${esc(t('Share link'))}</label><input id="cz-link" readonly value="${esc(u.link)}"><button type="button" data-cz-copy="cz-link">${esc(t('Copy'))}</button></div>
    <div class="cz-line"><label class="sr-only" for="cz-obs">${esc(t('OBS browser source link'))}</label><input id="cz-obs" readonly value="${esc(u.obs)}"><button type="button" data-cz-copy="cz-obs">${esc(t('Copy'))}</button></div>
    <p class="hint">${esc(t('The first link opens this HUD for anyone. The second is the transparent OBS page with the same HUD; add .fight, .break or .post after the preset for a scene.'))}</p>`;
}

function checksHtml() {
  const lines = [];
  for (const p of PANELS) {
    const el = $(p.host || p.id);
    if (!el || !isVisible(p.id) || !el.getClientRects().length) continue;
    for (const c of panelChecks(el)) if (!c.ok) lines.push(`<li><b>${esc(t(p.label))}</b>: ${esc(t(c.text, c.args))}</li>`);
  }
  return lines.length ? `<ul class="cz-checks">${lines.join('')}</ul>` : `<p class="hint cz-ok">✓ ${esc(t('Every panel passes: text sizes, safe area, map cover'))}</p>`;
}

export function installCustomize(ctx) {
  const el = $('panels-menu'), button = $('btn-panels');
  let checks = '';
  const sceneLabel = () => t((SCENES.find(([id]) => id === scene()) || SCENES[0])[1]);

  function render() {
    const focused = document.activeElement && el.contains(document.activeElement) ? document.activeElement : null;
    const marker = focused ? ['data-preset', 'data-cz-show', 'data-cz-metric', 'data-cz-row', 'data-cz', 'data-cz-flag', 'data-cz-collapse', 'data-cz-layout', 'data-cz-copy', 'id']
      .map((a) => (focused.getAttribute(a) != null ? `[${a}="${CSS.escape(focused.getAttribute(a))}"]` : '')).find(Boolean) : null;
    const open = [...el.querySelectorAll('details[data-cz-sec]')].filter((d) => d.open).map((d) => d.dataset.czSec);
    const sec = (id, title, body, first = false) => `<details data-cz-sec="${id}" ${first || open.includes(id) ? 'open' : ''}><summary><h3>${esc(t(title))}</h3></summary>${body}</details>`;
    const scroll = el.scrollTop;
    el.innerHTML = `<div class="cz-head"><h2 id="customize-title">${esc(t('Customize'))}</h2><button type="button" data-cz="close" aria-label="${esc(t('Close'))}">${esc(t('✕ Esc'))}</button></div>
      <p class="hint">${esc(t('Pick a preset, tick panels, tick metrics.'))} ${t('{key} edits the whole layout.', { key: key('arrangePanels') })}</p>
      <section aria-label="${esc(t('Presets'))}"><h3>${esc(t('Presets'))}</h3>${presetsHtml()}</section>
      <section aria-label="${esc(t('Panels'))}"><h3>${esc(t('Panels'))} <span class="hint">· ${esc(t('scene: {scene}', { scene: sceneLabel() }))}</span></h3>${panelsHtml()}</section>
      ${sec('metrics', 'Pulse strip metrics', metricsHtml(), !el.firstChild)}
      ${sec('rows', 'Team board rows', rowsHtml())}
      ${sec('layout', 'Layout', layoutHtml())}
      ${sec('share', 'Share link', shareHtml())}
      ${sec('check', 'Stream check', `<div class="cz-line"><button type="button" data-cz="check">${esc(t('Check the panels on screen'))}</button></div><div id="cz-check-out" role="status">${checks}</div>`)}
      <div class="cz-foot"><button type="button" data-cz="reset-hud" class="warn" ${tip(t('Reset HUD to defaults'), t('The first preset, every preset as shipped, panels in their places. Saved layouts stay.'))}>${esc(t('Reset HUD to defaults'))}</button></div>`;
    el.scrollTop = scroll;
    if (marker) { const again = el.querySelector(marker); if (again) again.focus({ preventScroll: true }); }
  }

  const changed = () => { render(); ctx.onChange(); };
  const close = () => {
    if (el.classList.contains('hidden')) return;
    el.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
    if (el.contains(document.activeElement) || document.activeElement === document.body) button.focus({ preventScroll: true });
    ctx.onChange();
  };
  const openDrawer = () => {
    render();
    el.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
    const first = el.querySelector('[role="radio"][aria-checked="true"]') || el.querySelector('[role="radio"]');
    if (first) first.focus({ preventScroll: true });
    ctx.onChange();
  };

  el.addEventListener('change', (e) => {
    const d = e.target.dataset || {};
    if (d.czShow) setVisible(d.czShow, e.target.checked);
    else if (d.czMetric) setPulseMetric(d.czMetric, e.target.checked);
    else if (d.czRow) {
      const hidden = (hud().hiddenRows || []).filter((x) => x !== d.czRow);
      setHud({ ...hud(), hiddenRows: e.target.checked ? hidden : [...hidden, d.czRow] });
    } else if (d.czFlag) setHud({ ...hud(), [d.czFlag]: e.target.checked });
    else if (e.target.id === 'cz-import') { importLayout(e.target.files && e.target.files[0]); return; }
    else return;
    changed();
  });

  async function importLayout(file) {
    if (!file) return;
    try {
      const obj = JSON.parse(await file.text());
      if (!layoutPatch(obj, settings)) throw new Error('no layout');
      const name = String(obj.name || file.name.replace(/\.json$/i, '') || 'Imported').slice(0, 40);
      const snap = snapshotLayout(obj, name);
      setHud({ ...hud(), layouts: { ...(hud().layouts || {}), [name]: snap } });
      loadLayout(name);
    } catch (error) { ctx.toast(t('Not a Vantage layout file')); }
  }

  function loadLayout(name) {
    const patch = layoutPatch((hud().layouts || {})[name], settings);
    if (!patch) { ctx.toast(t('No saved layout with that name')); return; }
    Object.assign(settings, patch);
    settings.hud = { ...settings.hud, layoutName: name };
    setHud(settings.hud);
    syncPanelSizes();
    ctx.toast(t('Layout loaded: {name}', { name }));
    changed();
  }

  el.addEventListener('click', async (e) => {
    const preset = e.target.closest('[data-preset]');
    if (preset) { applyPreset(preset.dataset.preset); changed(); return; }
    const coll = e.target.closest('[data-cz-collapse]');
    if (coll) { setCollapsed(coll.dataset.czCollapse, !isCollapsed(coll.dataset.czCollapse)); changed(); return; }
    const lay = e.target.closest('[data-cz-layout]');
    if (lay) { setHudLayout(lay.dataset.czLayout); changed(); return; }
    const copy = e.target.closest('[data-cz-copy]');
    if (copy) {
      const input = $(copy.dataset.czCopy);
      input.select();
      try { await navigator.clipboard.writeText(input.value); ctx.toast(t('Link copied')); }
      catch (error) { ctx.toast(t('Select the link and copy it (Ctrl+C)')); }
      return;
    }
    const b = e.target.closest('[data-cz]');
    if (!b) return;
    const act = b.dataset.cz, name = () => ($('cz-layout-name').value || '').trim().slice(0, 40), picked = () => $('cz-layout-list').value;
    if (act === 'close') { close(); return; }
    if (act === 'restore') restorePresetDefault(hud().preset);
    else if (act === 'edit') { close(); toggleEditLayout(); return; }
    else if (act === 'reset-layout') resetPanelSizes();
    else if (act === 'everything') showEverything();
    else if (act === 'reset-hud') { resetHud(); ctx.toast(t('HUD reset to its defaults')); }
    else if (act === 'check') { checks = checksHtml(); }
    else if (act === 'save-layout') {
      if (!name()) { ctx.toast(t('Give the layout a name first')); $('cz-layout-name').focus(); return; }
      const n = name();
      setHud({ ...hud(), layoutName: n, layouts: { ...(hud().layouts || {}), [n]: snapshotLayout({ ...settings, hud: { ...hud(), layoutName: n } }, n) } });
      ctx.toast(t('Layout saved: {name}', { name: n }));
    } else if (act === 'publish-layout') {
      const n = name() || picked();
      if (!n || !/^[\w -]{1,40}$/.test(n)) { ctx.toast(t('Use letters, digits, spaces, - and _ in the name')); return; }
      if (!(hud().layouts || {})[n]) setHud({ ...hud(), layoutName: n, layouts: { ...(hud().layouts || {}), [n]: snapshotLayout({ ...settings, hud: { ...hud(), layoutName: n } }, n) } });
      const r = await api('/api/profile', { name: n, settings }).catch(() => ({ ok: false }));
      ctx.toast(r && r.ok ? t('Published: add #layout={name} to the OBS link', { name: n }) : t('This Vantage cannot store profiles: the layout stays in this browser'));
    } else if (act === 'load-layout') { if (picked()) loadLayout(picked()); return; }
    else if (act === 'delete-layout') {
      if (!picked()) return;
      const layouts = { ...(hud().layouts || {}) }; delete layouts[picked()];
      setHud({ ...hud(), layouts, layoutName: hud().layoutName === picked() ? '' : hud().layoutName });
    } else if (act === 'export-layout') {
      const n = name() || hud().layoutName || 'layout';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(snapshotLayout({ ...settings, hud: hud() }, n), null, 1)], { type: 'application/json' }));
      a.download = `vantage-layout-${n.replace(/[^\w-]+/g, '-')}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      return;
    } else return;
    changed();
  });

  el.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    const radio = e.target.closest('[role="radio"]');
    if (!radio || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const all = [...el.querySelectorAll('[role="radio"]')], i = all.indexOf(radio);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (i + (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1) + all.length) % all.length;
    applyPreset(all[next].dataset.preset);
    changed();
    const again = el.querySelector(`[data-preset="${all[next].dataset.preset}"]`);
    if (again) again.focus();
  });

  // A preset picked by its key, or a panel hidden from its toolbar, shows here at once.
  document.addEventListener('vantage:hud-changed', () => { if (!el.classList.contains('hidden')) render(); });

  applyPanels();
  return {
    toggle() { if (el.classList.contains('hidden')) openDrawer(); else close(); },
    close,
    render,
  };
}
