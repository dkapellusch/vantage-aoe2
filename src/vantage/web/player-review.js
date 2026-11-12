// Player context and compact, explicitly scoped military information.
import { S, player, playerName, playerTextColor, playerStats, emblem, ageIcon, ageName,
  esc, fmtNum, fmtTime, tip } from './state.js';
import { t } from './i18n.js';

const PATHS = {
  kills: 'M4 4l16 16M4 20L20 4M4 4l5 1-4 4zM20 4l-1 5-4-4zM3 16l5 5M16 21l5-5',
  deaths: 'M6 16v-3a8 8 0 1 1 12 0v3h-3v5H9v-5zM8 10h1M15 10h1M12 14v1M10 18v3M14 18v3',
  value: 'M4 7l8-4 8 4-8 4zM4 7v10l8 4 8-4V7M12 11v10',
  idle: 'M9 6v12M15 6v12M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0',
  pressure: 'M4 17v-4a4 4 0 0 1 8 0v4M8 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4M13 14a5 5 0 1 0 10 0 5 5 0 0 0-10 0M18 11v3l2 1',
  location: 'M12 21s7-7 7-12a7 7 0 0 0-14 0c0 5 7 12 7 12zM10 9h4',
  time: 'M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0M12 7v5l4 2',
  play: 'M7 4l14 8-14 8z',
  workers: 'M5 21v-5a7 7 0 0 1 14 0v5M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  healing: 'M9 3h6v6h6v6h-6v6H9v-6H3V9h6z',
};
export function reviewIcon(name) {
  return `<svg class="review-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${PATHS[name] || PATHS.value}"/></svg>`;
}

export function ownerIdentity(pid, count = null, strip = false) {
  const p = player(pid);
  const civ = p && (p.civ_name || S.catalog.civs?.[p.civ]);
  const age = playerStats(pid)?.age;
  const civImage = p?.civ != null ? `<img class="review-civ" src="${emblem(p.civ)}" alt="${esc(civ || '')}" ${tip(civ || '')}>` : '';
  const ageImage = Number.isInteger(age)
    ? `<img class="review-age" src="${ageIcon(age, pid)}" alt="${esc(ageName(age, pid))}" ${tip(ageName(age, pid))}>`
    : `<span class="hint" ${tip(t('Age unavailable'))}>–</span>`;
  return `<div class="review-owner${strip ? ' review-owner-strip' : ''}" style="--owner-color:${playerTextColor(pid)}">
    ${civImage}<span class="review-owner-name">${esc(pid ? playerName(pid) : t('Gaia'))}</span>
    ${count != null ? `<span class="hint">×${count}</span>` : ''}${pid ? ageImage : ''}</div>`;
}

export function selectionHeader(row, u, name, shownOwner = row[1]) {
  const villager = u.cls === 4;
  const identity = ownerIdentity(shownOwner, null, villager);
  const object = `<div class="up-head review-object"><img src="${u.icon_url}" alt="">
    <div class="review-object-copy"><div class="up-name" id="up-name" ${tip(t('Click to rename'))}>${esc(name)}</div>
      ${villager ? '' : identity}</div></div>`;
  return villager ? identity + object : object;
}

export function reviewBounds() {
  const at = Math.round(S.view?.time ?? S.t);
  if (S.reviewScope === 'minute') return { end: at, since: Math.max(S.start, at - 60000) };
  if (S.reviewScope === 'fight' && S.reviewRange) {
    const end = Math.min(at, S.reviewRange.to);
    return { end, since: Math.min(end, Math.max(S.start, S.reviewRange.from)) };
  }
  return { end: at, since: null };
}

export function militaryQuery(ids) {
  const { end, since } = reviewBounds();
  const canonical = [...new Set(ids)].filter((id) => Number.isInteger(id) && id >= 0).sort((a, b) => a - b).slice(0, 600);
  return { ids: canonical, end, since,
    url: `/api/group?ids=${canonical.join(',')}&t=${end}${since == null ? '' : `&since=${since}`}` };
}

const resultCache = new Map();
export function militaryResults(ids) {
  const query = militaryQuery(ids), generation = S.session?.generation;
  const scope = S.reviewScope || 'life';
  const range = scope === 'fight' ? `${S.reviewRange?.from}:${S.reviewRange?.to}` : '';
  const key = `${generation}:${S.seekVersion}:${scope}:${range}:${query.ids.join(',')}`;
  let entry = resultCache.get(key);
  if (!entry) {
    if (resultCache.size > 24) resultCache.delete(resultCache.keys().next().value);
    entry = { pending: false, result: null, at: null, url: null };
    resultCache.set(key, entry);
  }
  if (!entry.pending && entry.url !== query.url) {
    entry.pending = true; entry.url = query.url;
    fetch(query.url).then((r) => { if (!r.ok) throw Error('review'); return r.json(); }).then((data) => {
      if (S.session?.generation === generation && data.generation === generation) {
        entry.result = data; entry.at = query.end;
        window.dispatchEvent(new Event('vantage-review-ready'));
      }
    }).catch(() => { entry.url = null; }).finally(() => { entry.pending = false; });
  }
  // Refresh in place. Never replace resolved numbers with dashes on every new
  // snapshot. Explicit seeks and changed scopes have separate cache contexts;
  // the timestamp beside the controls follows the returned data.
  return entry.at != null && (query.end >= entry.at || S.playing) ? entry.result : null;
}

export function performanceCells(data, grouped, scope = 'life') {
  const supportsScopes = data != null && Object.hasOwn(data, 'since_ms');
  const totals = scope === 'life' || supportsScopes ? data?.totals : null;
  const known = data?.destroyed_known_value;
  const destroyed = data?.destroyed_value != null ? fmtNum(data.destroyed_value)
    : data?.destroyed_unknown ? `${fmtNum(known)}+?` : '–';
  const activity = data?.activity_scope ?? (scope === 'life' ? data?.activity : scope === 'minute' ? data?.activity_lm : null);
  const idle = activity ? (grouped ? ((activity.idle || 0) / 60).toFixed(1) : fmtTime((activity.idle || 0) * 1000)) : '–';
  const resources = Object.entries(data?.resources_destroyed || {}).map(([res, n]) => `${fmtNum(n)} ${t(res)}`).join(' · ');
  const cells = [
    ['kills', totals ? fmtNum(totals.kills) : '–', t('Kills'), t('Enemy units and buildings killed in this time window')],
    ['deaths', totals ? fmtNum(totals.deaths) : '–', t('Deaths'), t('Deaths among the pinned selection in this time window')],
    ['value', destroyed, t('Destroyed'), `${t('Victim resource cost at the kill')}${resources ? ` · ${resources}` : ''}${data?.destroyed_unknown ? ` · ${t('Unknown costs')}: ${data.destroyed_unknown}` : ''}`],
    ['idle', idle, grouped ? t('Idle · unit·min') : t('Idle'), t('Observed idle time; groups sum the time of their selected units')],
    ['pressure', data?.forced_idle_seconds != null ? `≈${(data.forced_idle_seconds / 60).toFixed(1)}` : '–', t('Forced · vil·min'), t('Estimated downtime of directly attacked workers moving, idle or garrisoned within 15 seconds and 12 tiles; excludes unhit workers and avoids double counting')],
  ];
  const needsRestart = data && (!Object.hasOwn(data, 'destroyed_value') || !Object.hasOwn(data, 'forced_idle_seconds') || !supportsScopes);
  return `${needsRestart ? `<div class="review-metrics-unavailable" role="status">${t('Restart Vantage for review metrics')}</div>` : ''}<div class="review-performance">${cells.map(([icon, value, label, detail]) => `<div class="review-metric" tabindex="0" ${tip(label, detail)}>${reviewIcon(icon)}<b>${value}</b>${metricLabel(label)}</div>`).join('')}</div>`;
}

// "Idle · unit·min": the name on one line and its unit beneath, so five
// metrics fit side by side without their labels running into each other.
function metricLabel(label) {
  const [name, ...unit] = label.split(' · ');
  return `<span>${name}${unit.length ? `<small>${unit.join(' · ')}</small>` : ''}</span>`;
}

export function militaryCard(ids, { healing = true } = {}) {
  const range = S.reviewRange;
  const data = militaryResults(ids);
  return `<div class="review-scopes"><span>${fmtTime(data?.as_of_ms ?? S.view?.time ?? S.t)}</span>${[['life', t('Life')], ['minute', '60s'], ['fight', range ? `${fmtTime(range.from)}–${fmtTime(range.to)}` : t('Fight')]].map(([key, label]) => `<button data-review-scope="${key}" aria-pressed="${(S.reviewScope || 'life') === key}" ${key === 'fight' && !range ? 'disabled' : ''} ${tip(key === 'fight' && !range ? t('Choose a review interval in Statistics') : label)}>${label}</button>`).join('')}</div>${performanceCells(data, ids.length > 1, S.reviewScope || 'life')}${healing ? healingCells(data?.healing) : ''}`;
}

export function healingCells(healing, { lifetime = false } = {}) {
  if (!healing?.healer_count) return '';
  const marker = healing.partial ? '≥' : '≈';
  const value = healing.value == null ? `${fmtNum(healing.known_value)}+?` : fmtNum(healing.value);
  const resources = Object.entries(healing.resources || {}).filter(([, n]) => n > 0)
    .map(([r, n]) => `${Number(n.toFixed(2))} ${t(r)}`).join(' · ');
  const method = t('Observed direct healing; concurrent damage is included. Shared healing is split once between known healers. Regeneration, repair and ambiguous healing are excluded.');
  const valuation = t('HP restored ÷ target maximum HP × its owner’s unit cost at that time. Estimated replacement value, not resources added to the stockpile.');
  return `<div class="review-healing${lifetime ? ' review-healing-lifetime' : ''}" data-ui-key="healing-performance">${lifetime ? `<h4>${t('Lifetime healing')}</h4>` : ''}<div class="review-metric" tabindex="0" ${tip(t('HP healed'), method)}>${reviewIcon('healing')}<b>${marker}${fmtNum(healing.hp)}</b><span>${t('HP healed')}</span></div><div class="review-metric" tabindex="0" ${tip(t('Restored value'), `${valuation}${resources ? ` · ${resources}` : ''}${healing.unpriced_hp ? ` · ${t('Unpriced HP')}: ${fmtNum(healing.unpriced_hp)}` : ''}`)}>${reviewIcon('value')}<b>${marker}${value}</b><span>${t('Restored value')}</span></div><div class="review-healing-resources" tabindex="0" ${tip(t('Restored value'), valuation)}>${marker} ${esc(resources || (healing.unpriced_hp ? '?' : '0'))}${resources && healing.unpriced_hp ? ' + ?' : ''}</div></div>`;
}

export function wireReviewControls(el) {
  if (el._reviewControls) return;
  el._reviewControls = true;
  el.addEventListener('click', (event) => {
    const control = event.target.closest?.('[data-review-scope]');
    if (!control || control.disabled) return;
    S.reviewScope = control.dataset.reviewScope;
  });
}

// Only advertise drilldowns that have an actual selection or history destination.
export const DASH_HISTORY = {
  food: 'res_food', wood: 'res_wood', gold: 'res_gold', stone: 'res_stone',
  colF: 'col_food', colW: 'col_wood', colG: 'col_gold', colS: 'col_stone', colT: 'col_total',
  kd: 'kills', ecoKills: 'kills', ecoDeaths: 'deaths', ecoKD: 'kills', killsTotal: 'kills',
  deathsTotal: 'deaths', razings: 'razings', pop: 'pop', popOnly: 'pop', eco: 'eco_units',
  milGold: 'army_value', peakArmy: 'army_value', techs: 'techs', relics: 'relics', explored: 'explored',
  tcIdle: 'tc_idle', housed: 'housed', idleTcHoused: 'tc_idle', eff: 'efficiency_lm',
  apm: 'apm', apmEco: 'apm_eco', apmMil: 'apm_mil', trade: 'trade_units',
};
export const DASH_SELECTIONS = new Set(['vils', 'mil', 'milValue', 'wFood', 'wWood', 'wGold', 'wStone', 'build', 'idle', 'tc', 'castles', 'tcCastle']);
