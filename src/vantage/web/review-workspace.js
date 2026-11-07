// Review moments and interval investigations share the actual replay context.
import { S, api, esc, fmtTime, fmtNum, players, playerName, playerTextColor, toast, tip, unitInfo } from './state.js';
import { t } from './i18n.js';
import { patchHtml } from './dom.js';
import { reviewIcon, ownerIdentity } from './player-review.js';

const $ = (id) => document.getElementById(id);
let moments = [], loadedGeneration = null;
export async function loadMoments() {
  const generation = S.session?.generation;
  const rows = await api('/api/review-moments').catch(() => []);
  if (generation !== S.session?.generation) return;
  moments = Array.isArray(rows) ? rows : []; loadedGeneration = generation;
  S.reviewRange = null; S.reviewScope = 'life';
}
export function captureMoment(name, note = '') {
  return { id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    name: name.trim() || fmtTime(S.t), note: note.trim(), time: Math.round(S.t),
    player: S.perspective, fog: S.fogMode, camera: { ...S.camera },
    selection: [...S.selection], selection_info: Object.fromEntries([...S.selectionInfo].filter(([id]) => S.selection.has(id))), range: S.reviewRange ? { ...S.reviewRange } : null };
}
export async function saveMoment(name, note = '') {
  if (loadedGeneration !== S.session?.generation) await loadMoments();
  const moment = captureMoment(name, note), next = [...moments, moment];
  const result = await api('/api/review-moments', { generation: S.session?.generation, moments: next });
  if (!result.ok) throw Error(result.error || t('Could not save review moment'));
  moments = next; toast(t('Moment saved')); return moment;
}
export function restoreMoment(moment, seek) {
  S.perspective = moment.player; S.fogMode = moment.fog || 'off';
  S.followSelection = false; S.reviewRange = moment.range ? { ...moment.range } : null;
  S.reviewScope = moment.range ? 'fight' : 'life'; S.playing = false;
  seek(moment.time); Object.assign(S.camera, moment.camera); S.selection = new Set(moment.selection || []);
  S.selectionInfo = new Map(Object.entries(moment.selection_info || {}).map(([id, info]) => [+id, info]));
}
export function toggleReviewTimeline(seek) {
  let box = $('review-timeline');
  if (box && !box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
  if (!box) { box = document.createElement('section'); box.id = 'review-timeline'; box.className = 'review-surface'; document.body.appendChild(box); }
  box.classList.remove('hidden'); renderTimeline(box, seek);
}
function renderTimeline(box, seek) {
  box.innerHTML = `<div class="review-toolbar"><h3>${t('Review timeline')}</h3><button data-close aria-label="${t('Close')}">×</button></div>
    <form class="review-form"><input name="name" maxlength="120" placeholder="${t('Moment name')}" aria-label="${t('Moment name')}"><button type="submit">+ ${fmtTime(S.t)}</button><textarea name="note" maxlength="2000" placeholder="${t('Note')}" aria-label="${t('Note')}"></textarea></form>
    ${moments.slice().sort((a, b) => a.time - b.time).map((m) => `<div class="review-moment"><button data-moment="${esc(m.id)}">${fmtTime(m.time)}</button><div>${esc(m.name)}<small>${esc(m.note)}${m.range ? ` · ${fmtTime(m.range.from)}–${fmtTime(m.range.to)}` : ''}${m.player ? ` · ${esc(playerName(m.player))}` : ''}</small></div><button data-delete="${esc(m.id)}" aria-label="${t('Delete moment')}">×</button></div>`).join('')}
    ${S.bookmarks.length ? `<details><summary>${t('Bookmarks')} · ${S.bookmarks.length}</summary>${S.bookmarks.map((at) => `<button data-bookmark="${at}">${fmtTime(at)}</button>`).join(' ')}</details>` : ''}`;
  box.querySelector('[data-close]').onclick = () => box.classList.add('hidden');
  box.querySelector('form').onsubmit = async (event) => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try { await saveMoment(form.elements.name.value, form.elements.note.value); renderTimeline(box, seek); }
    catch (error) { toast(error.message); button.disabled = false; }
  };
  box.querySelectorAll('[data-moment]').forEach((button) => { button.onclick = () => { restoreMoment(moments.find((m) => m.id === button.dataset.moment), seek); box.classList.add('hidden'); }; });
  box.querySelectorAll('[data-bookmark]').forEach((button) => { button.onclick = () => seek(+button.dataset.bookmark); });
  box.querySelectorAll('[data-delete]').forEach((button) => { button.onclick = async () => {
    const next = moments.filter((m) => m.id !== button.dataset.delete);
    try { const result = await api('/api/review-moments', { generation: loadedGeneration, moments: next }); if (!result.ok) throw Error(result.error); moments = next; renderTimeline(box, seek); } catch (error) { toast(error.message); }
  }; });
}

export function reviewStatusHtml(cameraMode = 'Free') {
  const live = S.session?.mode === 'live', connected = S.session?.live_connected;
  const source = live ? connected ? t('Connected') : t('Reconnecting') : t('Replay');
  const vision = S.fogMode === 'off' ? t('All vision') : `${playerName(S.perspective)}${S.combinedFog ? ' + team' : ''} · ${S.fogMode}`;
  return `<span class="review-connection${live && !connected ? ' warn' : ''}" ${tip(t('Source connection'))}>${live && connected ? '●' : '○'} ${source}</span><span ${tip(t('Buffered playback'))}>${S.playing ? '▶' : 'Ⅱ'} ${fmtTime(S.t)} / ${fmtTime(S.end)}</span><span ${tip(t('Camera'))}>${t(cameraMode)}</span><span ${tip(t('Map visibility'))}>◐ ${esc(vision)}</span><span ${tip(t('Statistics'), t('Statistics include every player regardless of map visibility'))}>${t('All-player stats')}</span>`;
}

export function reviewStatus(cameraMode = 'Free') {
  let bar = $('review-status');
  if (!bar) { bar = document.createElement('div'); bar.id = 'review-status'; bar.setAttribute('role', 'status'); ($('timebar') || document.body).appendChild(bar); }
  patchHtml(bar, reviewStatusHtml(cameraMode));
}

export function intervalDelta(pid, key, from, to) {
  const rows = S.series?.[String(pid)] || [];
  const at = (time) => { let result = null; for (const row of rows) { if (row.t > time) break; result = row; } return result?.[key]; };
  const a = at(from), b = at(to);
  return typeof a === 'number' && typeof b === 'number' ? b - a : null;
}
export function investigationHtml(key = 'army_value') {
  const range = S.reviewRange || { from: Math.max(S.start, S.t - 60000), to: S.t };
  const options = players().map((p) => `<option value="${p.id}">${esc(playerName(p.id))}</option>`).join('');
  return `<section class="review-investigation"><div class="review-toolbar"><h3>${t('Investigate')}</h3><select id="review-player" aria-label="${t('Player')}">${options}</select><span>↔</span><select id="review-opponent" aria-label="${t('Compare player')}">${options}</select></div>
    <div class="review-toolbar" style="margin-top:9px"><input id="review-from" aria-label="${t('Interval start')}" value="${fmtTime(range.from)}"><span>–</span><input id="review-to" aria-label="${t('Interval end')}" value="${fmtTime(range.to)}"><button id="review-apply">${t('Apply')}</button><button id="review-play" aria-label="${t('Review interval')}" ${tip(t('Play this interval'))}>${reviewIcon('play')}</button><button id="review-save" aria-label="${t('Save interval')}" ${tip(t('Save review moment'))}>⚑</button><span class="hint">Δ ${esc(key.replaceAll('_', ' '))}</span></div><div id="review-observations"></div></section>`;
}
export function parseReviewTime(value) {
  const parts = String(value).trim().split(':');
  if (!parts.length || parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return null;
  const result = parts.reduce((total, part) => total * 60 + Number(part), 0) * 1000;
  return Number.isSafeInteger(result) ? result : null;
}
export function wireInvestigation(el, key, seek, close, onRange = null) {
  const a = el.querySelector('#review-player'), b = el.querySelector('#review-opponent');
  if (!a || !b) return;
  a.value = String(S.investigatePlayer || players()[0]?.id); b.value = String(S.investigateOpponent || players().find((p) => p.id !== +a.value)?.id || a.value);
  const apply = () => {
    const rawFrom = parseReviewTime(el.querySelector('#review-from').value), from = rawFrom == null ? null : Math.max(S.start, rawFrom), to = parseReviewTime(el.querySelector('#review-to').value);
    if (from == null || to == null || from < S.start || to > S.end || to < from) { toast(t('Choose an interval within the replay')); return false; }
    S.reviewRange = { from, to }; S.reviewScope = 'fight';
    S.investigatePlayer = +a.value; S.investigateOpponent = +b.value;
    if (onRange) onRange(from, to, [+a.value, +b.value]);
    const comparison = [+a.value, +b.value].map((pid) => {
      const delta = intervalDelta(pid, key, from, to);
      return `<div style="--owner-color:${playerTextColor(pid)}">${ownerIdentity(pid)}<b>${delta == null ? '–' : `${delta > 0 ? '+' : ''}${fmtNum(delta)}`}</b><small>Δ ${esc(key.replaceAll('_', ' '))}</small></div>`;
    }).join('');
    const events = S.events.filter((event) => event.t >= from && event.t <= to && [event.player, event.killer?.owner, event.victim?.owner, event.owner].some((pid) => [+a.value, +b.value].includes(pid))).slice(-35);
    el.querySelector('#review-observations').innerHTML = `<div class="review-comparison">${comparison}</div><div class="review-event-list">${events.map((event, i) => `<button data-review-event="${i}">${fmtTime(event.t)} · ${esc(event.kind === 'kill' ? `${unitInfo(event.killer?.master, event.killer?.owner).name} → ${unitInfo(event.victim?.master, event.victim?.owner).name}` : event.kind.replaceAll('_', ' '))}${event.tech != null ? ` · ${esc(S.catalog.techs?.[event.tech]?.name || event.tech)}` : ''}</button>`).join('') || `<span class="hint">${t('No recorded events in this interval')}</span>`}</div>`;
    el.querySelectorAll('[data-review-event]').forEach((button) => { button.onclick = () => { seek(events[+button.dataset.reviewEvent].t); close(); }; });
    return true;
  };
  el.querySelector('#review-apply').onclick = apply; a.onchange = b.onchange = apply;
  el.querySelector('#review-play').onclick = () => { if (!apply()) return; seek(S.reviewRange.from); S.reviewPlaybackUntil = S.reviewRange.to; S.playing = true; close(); };
  el.querySelector('#review-save').onclick = () => { if (!apply()) return; close(); toggleReviewTimeline(seek); };
  apply();
}
