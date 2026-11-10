// Vantage hub: the upload page ("/") and a match's page ("/m/<id>").
import { drawChart, METRICS } from './chart.js';

const app = document.getElementById('app');
const KEY = 'vantage-hub-matches';
const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
};
const getJson = async (url, opts) => {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `Request failed (${r.status})`);
  return body;
};
const mine = () => { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; } };
const remember = (id) => localStorage.setItem(KEY, JSON.stringify([id, ...mine().filter((x) => x !== id)].slice(0, 100)));
const forget = (id) => localStorage.setItem(KEY, JSON.stringify(mine().filter((x) => x !== id)));

export const clock = (ms) => {
  if (ms == null) return '–';
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, '0');
  return `${h ? `${h}:` : ''}${mm}:${String(s % 60).padStart(2, '0')}`;
};
const num = (v) => (v == null ? '–' : Math.round(v).toLocaleString('en'));
const day = (unix) => (unix ? new Date(unix * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '');
// The game's player colours by lobby colour id, for a replay not yet analysed.
const LOBBY = ['#4a78ff', '#ff3b30', '#22c55e', '#facc15', '#22d3ee', '#d946ef', '#a3a3a3', '#fb923c'];
// A colour that still reads on the dark page (the game's blue and grey are dark).
export const ink = (hex) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#9aa4b2';
  const n = parseInt(m[1], 16);
  let [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  if (lum < 0.32) { const k = (0.32 - lum) / (1 - lum); r += (255 - r) * k; g += (255 - g) * k; b += (255 - b) * k; }
  return `rgb(${r | 0},${g | 0},${b | 0})`;
};

const STATUS = {
  queued: 'In the queue',
  converting: 'The game is playing it',
  analyzing: 'Reading the recording',
  ready: 'Ready',
  failed: 'Failed',
};
const statusText = (m) => (m.status === 'queued' && m.ahead ? `In the queue · ${m.ahead} ahead` : m.status === 'queued' ? 'The game is playing it' : STATUS[m.status] || m.status);

function playersLine(replay) {
  const teams = new Map();
  for (const p of replay?.players || []) {
    const key = p.team > 0 ? `t${p.team}` : `p${p.number}`;
    teams.set(key, [...(teams.get(key) || []), p]);
  }
  const sides = [...teams.values()].map((side) => el('span', { class: 'side' }, side.map((p) => el('span', { class: 'pl' },
    el('i', { class: 'dot', style: `background:${ink(LOBBY[p.color_id] || '')}` }), p.name,
    replay.winners?.includes(p.number) ? el('span', { class: 'won', title: 'Won' }, ' ♛') : null))));
  return el('span', { class: 'players' }, sides.flatMap((s, i) => (i ? [el('span', { class: 'vs' }, 'vs'), s] : [s])));
}

// -- upload page -----------------------------------------------------------------------

async function home() {
  document.title = 'Vantage · replay analysis';
  const info = await getJson('/api/info').catch(() => ({}));
  const note = el('p', { class: 'note' });
  const input = el('input', { type: 'file', accept: '.aoe2record', multiple: true, hidden: true, onchange: () => send([...input.files]) });
  const drop = el('button', { class: 'drop', type: 'button', onclick: () => input.click() },
    el('strong', {}, 'Drop replays here'), el('span', {}, 'or choose .aoe2record files'),
    el('small', {}, `Up to ${info.max_mb || 64} MB each${info.build ? ` · game build ${info.build}` : ''}`));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); send([...e.dataTransfer.files]); });
  const list = el('ul', { class: 'matches' });
  app.replaceChildren(
    el('section', { class: 'hero' },
      el('h1', {}, 'Watch and analyse your Age of Empires II replays'),
      el('p', {}, 'Upload a recorded game. The server plays it once, then you get the match in the Vantage viewer, with economy, army and timing statistics for every player.')),
    drop, input, note,
    el('section', { class: 'yours' }, el('h2', {}, 'Your uploads'), list,
      el('p', { class: 'muted' }, 'Kept in this browser. Anyone with a match link can open it.')),
    el('section', { class: 'where' }, el('h2', {}, 'Where are my replays?'),
      el('p', {}, 'Windows: ', el('code', {}, '%USERPROFILE%\\Games\\Age of Empires 2 DE\\<your id>\\savegame'), '. In the game: Single Player or Multiplayer › Load Game › Replays › Open Folder.')));

  async function send(files) {
    note.className = 'note';
    for (const file of files) {
      if (file.size > (info.max_mb || 64) * 1048576) {
        note.className = 'note bad';
        note.textContent = `${file.name}: replays up to ${info.max_mb || 64} MB are accepted.`;
        return;
      }
      note.textContent = `Uploading ${file.name}…`;
      try {
        const r = await getJson(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: 'POST', body: file });
        remember(r.id);
        if (files.length === 1) { go(`/m/${r.id}`); return; }
      } catch (err) {
        note.className = 'note bad';
        note.textContent = `${file.name}: ${err.message}`;
        await refresh();
        return;
      }
    }
    note.textContent = '';
    await refresh();
  }

  let timer = 0;
  async function refresh() {
    clearTimeout(timer);
    const rows = await Promise.all(mine().map((id) => getJson(`/api/match/${id}`).catch(() => ({ id, gone: true }))));
    if (!list.isConnected) return;
    rows.filter((m) => m.gone).forEach((m) => forget(m.id));
    const shown = rows.filter((m) => !m.gone);
    list.replaceChildren(...(shown.length ? shown.map((m) => el('li', {},
      el('a', { href: `/m/${m.id}`, onclick: link }, playersLine(m.replay),
        el('span', { class: 'meta' }, `${clock(m.replay?.duration_ms)} · ${day(m.replay?.started_at || m.uploaded)}`)),
      el('span', { class: `chip ${m.status}` }, statusText(m)))) : [el('li', { class: 'muted' }, 'Nothing uploaded yet.')]));
    if (shown.some((m) => !['ready', 'failed'].includes(m.status))) timer = setTimeout(refresh, 4000);
  }
  refresh();
}

// -- match page ------------------------------------------------------------------------

async function match(id) {
  const head = el('section', { class: 'match-head' });
  const body = el('section', { class: 'match-body' });
  app.replaceChildren(el('p', { class: 'back' }, el('a', { href: '/', onclick: link }, '← Upload another replay')), head, body);
  let shown = '';
  async function poll() {
    let m;
    try { m = await getJson(`/api/match/${id}`); } catch (err) {
      head.replaceChildren(el('h1', {}, 'No such match'), el('p', { class: 'muted' }, err.message));
      return;
    }
    if (!head.isConnected) return;
    remember(id);
    const r = m.replay || {};
    document.title = `${(r.players || []).map((p) => p.name).join(' vs ') || 'Match'} · Vantage`;
    head.replaceChildren(
      el('h1', {}, playersLine(r)),
      el('p', { class: 'meta' }, [r.game_type, r.ranked ? 'Ranked' : null, clock(r.duration_ms), day(r.started_at)].filter(Boolean).join(' · '),
        el('span', { class: `chip ${m.status}` }, statusText(m))));
    const state = `${m.status}:${m.analysis}`;
    if (state !== shown) {
      shown = state;
      if (m.status === 'failed') {
        body.replaceChildren(el('div', { class: 'panel bad' }, el('h2', {}, 'This replay could not be converted'), el('p', {}, m.error || ''),
          el('button', { type: 'button', onclick: async (e) => { e.target.disabled = true; await getJson(`/api/match/${id}/retry`, { method: 'POST' }).catch(() => {}); shown = ''; poll(); } }, 'Try again')));
      } else if (m.status !== 'ready') {
        body.replaceChildren(el('div', { class: 'panel wait' }, el('div', { class: 'spinner', role: 'img', 'aria-label': 'Working' }),
          el('div', {}, el('h2', {}, statusText(m)), el('p', { class: 'muted' }, 'The game plays the whole match at up to 27 times its speed: a 40-minute game takes about two minutes, longer when the game has to start first. This page updates by itself.'))));
      } else {
        await ready(m, body);
      }
    }
    if (!['ready', 'failed'].includes(m.status)) setTimeout(poll, 3000);
  }
  poll();
}

const AGES = ['Feudal', 'Castle', 'Imperial'];

async function ready(m, body) {
  const analysis = m.analysis ? await getJson(`/api/match/${m.id}/analysis`).catch(() => null) : null;
  const viewer = el('div', { class: 'viewer' },
    el('div', { class: 'bar' }, el('h2', {}, 'Viewer'),
      el('a', { class: 'btn', href: m.viewer, target: '_blank', rel: 'noopener' }, 'Open in its own tab ↗')),
    el('iframe', { src: m.viewer, title: 'Vantage viewer', allow: 'fullscreen; autoplay', allowfullscreen: true, loading: 'lazy' }));
  if (!analysis) {
    body.replaceChildren(viewer, el('p', { class: 'muted' }, 'The statistics for this match are not available.'));
    return;
  }
  const players = Object.entries(analysis.match.players).map(([pid, p]) => ({ pid, ...p, s: analysis.summary[pid] || {}, color: ink(p.color) }));
  players.sort((a, b) => (a.team_key ?? 0) - (b.team_key ?? 0) || a.pid - b.pid);
  const facts = [analysis.match.map, analysis.match.game_mode, `${clock(analysis.status.end)} game time`, `${analysis.match.pop_limit} pop`].filter(Boolean);

  const cols = [
    ['Player', (p) => el('span', { class: 'pl' }, el('i', { class: 'dot', style: `background:${p.color}` }), p.name, p.s.status === 'won' ? el('span', { class: 'won', title: 'Won' }, ' ♛') : null), 'l'],
    ['Civilisation', (p) => p.civ_name || '–', 'l'],
    ['Score', (p) => num(p.s.score)],
    ['Kills', (p) => num(p.s.kills)],
    ['Losses', (p) => num(p.s.deaths)],
    ['Razed', (p) => num(p.s.razings)],
    ['Collected', (p) => num(p.s.collected?.total)],
    ['Peak villagers', (p) => num(p.s.peak_villagers)],
    ['Peak army value', (p) => num(p.s.peak_army_value)],
    ['eAPM', (p) => num(p.s.geapm ?? p.s.avg_apm)],
    ['Efficiency', (p) => (p.s.efficiency == null ? '–' : `${p.s.efficiency.toFixed(0)}%`)],
    ['TC idle', (p) => clock((p.s.tc_idle_seconds ?? 0) * 1000)],
    ...AGES.map((age, i) => [age, (p) => clock(p.s.age_times?.[i + 1])]),
  ];
  const table = el('div', { class: 'scroll' }, el('table', { class: 'score' },
    el('thead', {}, el('tr', {}, cols.map(([name, , align]) => el('th', { class: align || 'r', scope: 'col' }, name)))),
    el('tbody', {}, players.map((p) => el('tr', {}, cols.map(([, cell, align]) => el('td', { class: align || 'r' }, cell(p))))))));

  const canvas = el('canvas', { class: 'chart', role: 'img', tabindex: 0 });
  const tip = el('div', { class: 'tip', hidden: true });
  const legend = el('div', { class: 'legend' }, players.map((p) => el('span', { class: 'pl' }, el('i', { class: 'dot', style: `background:${p.color}` }), p.name)));
  let metric = 'army_value';
  const tabs = el('div', { class: 'tabs', role: 'tablist' }, Object.entries(METRICS).map(([key, def]) => el('button', {
    type: 'button', role: 'tab', 'aria-selected': String(key === metric), 'data-key': key,
    onclick: () => { metric = key; tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.key === key))); paint(); },
  }, def.label)));
  const series = players.map((p) => ({ name: p.name, color: p.color, rows: analysis.series[p.pid] || [], ages: p.s.age_times || {} }));
  const paint = () => drawChart(canvas, tip, series, metric, analysis.status.end);
  new ResizeObserver(paint).observe(canvas);

  body.replaceChildren(
    viewer,
    el('div', { class: 'panel' }, el('div', { class: 'bar' }, el('h2', {}, 'Result'), el('span', { class: 'muted' }, facts.join(' · '))), table),
    el('div', { class: 'panel' }, el('div', { class: 'bar' }, el('h2', {}, 'Over time'), legend), tabs, el('div', { class: 'chart-wrap' }, canvas, tip)));
  paint();
}

// -- routing ---------------------------------------------------------------------------

function link(e) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
  e.preventDefault();
  go(e.currentTarget.getAttribute('href'));
}
function go(path) { history.pushState(null, '', path); route(); }
function route() {
  const m = /^\/m\/(m[a-z2-7]{12})$/.exec(location.pathname);
  window.scrollTo(0, 0);
  if (m) match(m[1]); else home();
}
window.addEventListener('popstate', route);
route();
