// Vantage: boot, playback clock, data refresh, actions.

import {
  S, settings, saveSettings, SPEEDS, api, fetchView, cachedView, cachedViewAt, clearViewCache, toast, players, playerName,
  playerColor, fmtTime, unitInfo, unitIcon, applyServerConfig, tip, esc, tooltipLevel, refreshSeries, probeAssetOrigin, abortViews, viewTimings, viewStats,
} from './state.js';
import * as world from './world.js';
import { loadMoments, toggleReviewTimeline, reviewStatus } from './review-workspace.js';
import * as panels from './panels.js';
import { toggleTeamBoardView } from './team-board.js';
import * as overlays from './overlays.js';
import { actionFor, rebuild as rebuildKeys, binding, describeConflicts } from './hotkeys.js';
import { t, setLanguage, detectLanguage, language, translateStatic, keyLabel } from './i18n.js';
import { fidelityNotice } from './recording-fidelity.js';
import * as audio from './audio.js';
import * as layout from './layout.js';
import { patchHtml } from './dom.js';
import { shuttleSpeed, eventIndexAfter, replayBufferWait, matchEnded } from './playback.js';
import { GOTO_BUILDINGS, applyGame } from './games.js';
import { chooseFight, FightSelection, highlightParticipants } from './autocast-focus.js';
import { installPanelResizing } from './panel-resize.js';

const $ = (id) => document.getElementById(id);
let generation = -1;
let showResLeft = false;
let lastFrame = performance.now();
let nextFrameDue = 0;
let mouse = { x: null, y: null };
let fpsAcc = 0, fpsN = 0;
let endgameShown = false;

// Shell-owned shared state.
S.slideout = null;   // null | 'techs' | 'graph' (HUD renders the slide-outs)
S.highlight = { list: false, seq: null }; // autocast highlight sequence

const isLive = () => !!(S.session && S.session.mode === 'live');
const source = () => (S.session && S.session.source) || {};
// Seeking is off when the user disabled scrubbing.
const seekLocked = () => !!settings.disableScrubbing;

// -- data -----------------------------------------------------------------------------

async function loadStatic() {
  const [match, map, catalog] = await Promise.all([api('/api/match'), api('/api/map'), api(`/api/catalog?lang=${language}`)]);
  S.match = match && match.players ? match : { players: {} };
  if (map && map.width) world.setMap(map);
  S.catalog = catalog;
}

// Performance view (Ctrl+Alt+Shift+P): frame time percentiles, view fetch
// latency and sprite memory, updated twice a second.
const perf = { on: false, frames: [], work: [], update: [], minimap: [], fetches: [], last: 0 };
function perfTick(now, dt) {
  if (!perf.on) return;
  perf.frames.push(dt * 1000);
  if (perf.frames.length > 240) perf.frames.shift();
  for (const xs of [perf.work, perf.update, perf.minimap]) if (xs.length > 240) xs.splice(0, xs.length - 240);
  // View requests (in the view worker): their timings come from state.js.
  perf.fetches = viewTimings.slice(-60);
  if (now - perf.last < 500) return;
  perf.last = now;
  const pct = (xs, p) => { if (!xs.length) return 0; const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
  const mem = world.spriteMemory ? world.spriteMemory() : { bytes: 0, strips: 0 };
  const heap = performance.memory ? ` · heap ${(performance.memory.usedJSHeapSize / 1048576).toFixed(0)} MB` : '';
  const dts = world.drawTimes, dn = Math.max(1, dts.n);
  const parts = `draw: ground ${(dts.ground / dn).toFixed(1)} · entities ${(dts.entities / dn).toFixed(1)} · outlines ${(dts.outlines / dn).toFixed(1)} · effects ${(dts.effects / dn).toFixed(1)} · post ${(dts.post / dn).toFixed(1)} ms · ground repaints ${dts.paints}/${dts.n} frames (${dts.patches} partial; trees ${(dts.trees / Math.max(1, dts.paints)).toFixed(1)}, chunks ${(dts.chunks / Math.max(1, dts.paints)).toFixed(1)} ms each)\n`;
  const detail = `outline stage: masks ${(dts.masks / dn).toFixed(1)} · prefetch ${(dts.readAhead / dn).toFixed(1)} · projectiles ${(dts.missiles / dn).toFixed(1)} · FX clear ${(dts.fxClear / dn).toFixed(1)} ms\n`;
  dts.ground = dts.entities = dts.outlines = dts.masks = dts.readAhead = dts.missiles = dts.fxClear = dts.effects = dts.post = dts.n = dts.paints = dts.patches = dts.trees = dts.chunks = 0;
  $('perf-view').textContent = parts + detail + `frame p50 ${pct(perf.frames, 0.5).toFixed(1)} ms · p95 ${pct(perf.frames, 0.95).toFixed(1)} ms · max ${Math.max(0, ...perf.frames).toFixed(1)} ms\n`
    + `work p50 ${pct(perf.work, 0.5).toFixed(1)} ms · p95 ${pct(perf.work, 0.95).toFixed(1)} ms (script + draw per frame; view update p50 ${pct(perf.update, 0.5).toFixed(1)} · p95 ${pct(perf.update, 0.95).toFixed(1)}, minimap p50 ${pct(perf.minimap, 0.5).toFixed(1)} ms)\n`
    + `view fetch p50 ${pct(perf.fetches, 0.5).toFixed(0)} ms · p95 ${pct(perf.fetches, 0.95).toFixed(0)} ms (${perf.fetches.length})\n`
    + `sprites ${mem.strips} strips · ${(mem.bytes / 1048576).toFixed(0)} MB${heap}\n`
    + gpuLine()
    + `sprite fallbacks/s: stale frame ${world.spriteStats.stale * 2} · placeholder ${world.spriteStats.missing * 2} · facing stand-in ${world.spriteStats.standIn * 2}`;
  world.spriteStats.stale = 0; world.spriteStats.missing = 0; world.spriteStats.standIn = 0;
}

// GPU sprite batch (sprite-gl.js): instances and frame uploads per second, atlas use.
let gpuPrev = null;
function gpuLine() {
  const g = world.gpuSpriteStats();
  if (!g.on) return `GPU sprites off${g.error ? ` (${g.error})` : ''}\n`;
  const p = gpuPrev || g;
  gpuPrev = g;
  const per = (k) => (g[k] - p[k]) * 2;
  return `GPU sprites: ${per('draws') ? Math.round(per('instances') / per('draws')) : 0} per batch · ${per('uploads')} frame uploads/s (${per('deferred')} deferred) · ${g.memory.used}/${g.memory.layers} atlas layers (${g.grows} grows) · ${g.evictions} evictions · ${g.flushes} pressure flushes · ${g.full} atlas misses · ${g.tooLarge} too large\n`;
}

// The game's spectator API must be new enough for what Vantage asks of it
// (LoadGame needs API 11).
const MIN_API_VERSION = 11;
let compatWarned = false;
function checkCompatibility(desc) {
  const api = desc && desc.source && desc.source.api_version;
  if (compatWarned || settings.gameWarningsDismissed || !api || api >= MIN_API_VERSION) return;
  compatWarned = true;
  toast(t('This game version (spectator API {v}) is older than Vantage supports ({min}); some features may not work. Update the game, or hide this warning in Settings.', { v: api, min: MIN_API_VERSION }));
}

// A link or command asked the game to load something while a game is in
// progress: ask before leaving it ("Continue with request?").
let confirmAskedFor = -1;
async function askToContinue(desc) {
  const src = desc.source || {};
  if (desc.mode !== 'live' || src.status !== 'needs_confirm' || !src.request || confirmAskedFor === desc.generation) return;
  confirmAskedFor = desc.generation;
  const what = src.request.lobby ? t('join the lobby') : src.request.replay ? t('load the replay') : t('switch games');
  const yes = await overlays.confirmDialog(t('Continue with request?'),
    t('To {what}, the game will exit your current game.', { what }), t('Continue'));
  if (yes) await api('/api/live', { ...src.request, confirm: true }).catch(() => {});
  else { await api('/api/stop', {}).catch(() => {}); toast(t('Request cancelled')); }
}

// Without the game install the view falls back to plain shapes and no sound: say
// why once, with where to fix it.
let gameDataWarned = false;
function checkGameData(desc) {
  if (gameDataWarned || !desc || desc.game_data !== false || desc.mode === 'idle') return;
  gameDataWarned = true;
  toast(t('Age of Empires II: DE install not found: showing plain graphics without sound. Set the game folder in Settings → Interface → Game directory.'));
}

// Session updates arrive on every timeline change (many a second while a
// recording loads or a game streams). Apply one at a time, always the newest:
// overlapping runs each fetched the events and the whole series again. A hidden
// tab keeps only the newest and applies it when shown again.
let refreshing = null, pendingDesc = null;
function refreshSession(desc) {
  pendingDesc = desc;
  if (!refreshing && !document.hidden) {
    refreshing = (async () => {
      try {
        while (pendingDesc && !document.hidden) {
          const next = pendingDesc;
          pendingDesc = null;
          // One failed update (a request that failed) must not stop the next.
          await applySession(next).catch(console.error);
        }
      } finally { refreshing = null; }
    })();
  }
  return refreshing || Promise.resolve();
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && pendingDesc) refreshSession(pendingDesc).catch(console.error); });

function renderFidelityNotice(desc) {
  const el = document.getElementById('fidelity-banner');
  if (!el) return;
  const notice = fidelityNotice(desc);
  el.textContent = notice ? t(notice) : '';
  el.classList.toggle('hidden', !notice);
}

async function applySession(desc) {
  checkCompatibility(desc);
  checkGameData(desc);
  askToContinue(desc);
  S.session = desc;
  renderFidelityNotice(desc);
  // Age names, techs and age-up rules follow the game (AoE2 or Return of Rome).
  S.game = desc.game || 'aoe2';
  if (applyGame(S.game)) {
    document.body.dataset.game = S.game;
    if (S.game === 'ror' && !settings.seenRorTutorial && settings.seenTutorial && !document.body.classList.contains('overlay-mode')) {
      showTutorial(0, ROR_TUTORIAL, 'seenRorTutorial');
    }
  }
  const tl = desc.timeline;
  if (desc.generation !== generation) {
    generation = desc.generation;
    clearViewCache();
    resetViews();
    S.events = []; S.eventsTo = -1; S.series = null; S.summary = null; S.selection = new Set();
    if (autocast.on) { autocast.selection.resume(S.selection); autocast.nextMove = 0; }
    S.bookmarks = await api('/api/bookmarks').catch(() => []);
    await loadMoments(); S.reviewPlaybackUntil = null;
    endgameShown = false;
    // The previous game's results must not stay over a new session.
    if (overlays.isOpen('overlay-endgame')) overlays.closeAll();
    S.highlight.seq = null;
    S.followLive = desc.mode === 'live';
    readAheadArmed = desc.mode === 'live';
    S.map = null; S.t = 0;
    lastWindowState = null;
    if (desc.mode === 'live' && document.hasFocus()) gameWindow('MINIMIZED');
  }
  if (tl) {
    S.start = tl.start; S.end = tl.end; S.complete = tl.complete;
    if ((!S.map || !S.match.map_size) && tl.end > 0) await loadStatic();
    if (tl.catalog_version !== S.catalogVersion) {
      S.catalogVersion = tl.catalog_version;
      S.catalog = await api(`/api/catalog?lang=${language}`);
    }
    if (S.t === 0 && desc.mode === 'recording') S.t = tl.start;
    // New events since the last fetch.
    if (tl.end > S.eventsTo) {
      const from = S.eventsTo + 1, events = S.events;
      const evs = await api(`/api/events?from=${from}&to=${tl.end}`, undefined, { priority: 'low' }).catch(() => null);
      // One push per event: spreading a large first batch overflows the call stack.
      if (evs && events === S.events) { for (const e of evs) events.push(e); S.eventsTo = tl.end; }
    }
    if (!S.series || (S.end - S.seriesAt > 15000) || (tl.complete && S.seriesAt !== S.end)) {
      await refreshSeries().catch(() => S.series);
    }
  }
  $('status-line').textContent = statusText(desc);
  renderLaunchStatus();
}

// Launch status (live): connecting -> joining lobby -> waiting in lobby -> loading -> ready -> playing -> ended.
const LAUNCH_TEXT = {
  connecting: 'Connecting to the game…',
  joining: 'Joining spectator lobby…',
  waiting_lobby: 'Waiting in lobby…',
  loading: 'Loading the game…',
  ready: 'Ready to watch',
  ended: 'Game over',
};

function lobbyInfo(src) {
  const l = src.lobby;
  if (l == null || l === '') return null;
  if (typeof l !== 'object') return { id: l };
  return { ...l, id: l.id ?? l.lobbyid ?? l.lobby_id ?? '' };
}

function specDelay(src) {
  const l = lobbyInfo(src) || {};
  const d = src.spec_delay ?? l.spec_delay ?? l.delay ?? l.spectator_delay;
  if (d != null && d !== '') return Number(d);
  // Otherwise count down to the lobby's match start time (epoch ms).
  const ms = Number(l.match_start_time);
  return ms > 1e11 ? Math.max(0, Math.round((ms - Date.now()) / 1000)) : null;
}

function launchText(src) {
  const st = src.status;
  if (st === 'joining') {
    const l = lobbyInfo(src);
    return l && l.id !== '' ? t('Joining spectator lobby #{id}…', { id: l.id }) : t(LAUNCH_TEXT.joining);
  }
  if (st === 'loading' && src.replay) return t('Loading replay…');
  return LAUNCH_TEXT[st] ? t(LAUNCH_TEXT[st]) : '';
}

function statusText(desc) {
  // A stopped live session keeps its last error; it is no longer retrying.
  const stopped = desc.mode === 'live' && (desc.source || {}).status === 'ended';
  if (desc.error && !stopped) return `⚠ ${overlays.friendlyError(desc.error)}`;
  if (desc.mode === 'native_replay') {
    const labels = { queued: 'Replay queued', converting: 'Converting replay…', failed: 'Replay conversion failed', cancelled: 'Replay conversion cancelled' };
    const src = desc.source || {};
    return t(src.status === 'converting' && src.phase === 'loading' ? 'Loading replay…' : (labels[src.status] || 'Replay queued'));
  }
  const tl = desc.timeline;
  if (desc.mode === 'live') {
    const src = desc.source || {};
    const parts = [desc.live_connected ? `● ${t('live')}` : `○ ${t('reconnecting…')}`];
    const st = launchText(src);
    if (st && src.status !== 'playing') parts.push(st);
    const d = specDelay(src);
    if (d) parts.push(t('Spec delay: {n}s', { n: Math.round(d) }));
    if (recordingActive()) parts.push(`● ${t('REC')}`);
    return parts.join(' · ');
  }
  if (desc.mode === 'recording' && tl && !tl.complete) return t('loading {time}…', { time: fmtTime(tl.end) });
  return '';
}

// -- starting the game ------------------------------------------------------------------
// POST /api/launch_game starts Age II through Steam; GET reports its status
// while the server's watcher polls the game (every 2 s, 5 min deadline).
const GAME_STATUS = {
  unknown: 'Unknown', noGameExe: 'Game exe missing', opening: 'Starting Age II…', running: 'Running',
  runningPlayer: 'Running — you are playing a game, not spectating',
  runningCadeNeedsUpdate: 'Running — this game version needs a newer Vantage',
  connected: 'Connected', launchFailed: 'Launch failed', exited: 'Exited',
};
const LAUNCH_WAITING = ['unknown', 'opening', 'running', 'runningPlayer', 'runningCadeNeedsUpdate'];
const LAUNCH_FAILED = ['noGameExe', 'launchFailed', 'exited'];
const launch = { status: null, detail: '', timer: null, since: 0, connectedAt: 0, liveAsked: false };

function setLaunchStatus(r) {
  if (serverConfig && serverConfig.native_replays) return;
  const st = r && typeof r === 'object' ? r.status : null;
  if (!st) return;
  if (st !== launch.status && st === 'connected') launch.connectedAt = performance.now();
  launch.status = st;
  launch.detail = (r.detail || r.error || '') && String(r.detail || r.error);
  // The game is up: start watching it if nothing is being watched yet.
  if ((st === 'running' || st === 'connected') && !launch.liveAsked && !(S.session && S.session.mode && S.session.mode !== 'idle')) {
    launch.liveAsked = true;
    api('/api/live', { host: '127.0.0.1', port: 4341 })
      .then(() => afterOpen()).catch(() => null);
  }
}

async function pollLaunch() {
  if (serverConfig && serverConfig.native_replays) return;
  clearTimeout(launch.timer);
  const r = await api('/api/launch_game').catch(() => null);
  if (r) setLaunchStatus(r);
  renderLaunchStatus();
  if (LAUNCH_WAITING.includes(launch.status) && performance.now() - launch.since < 6 * 60000) launch.timer = setTimeout(pollLaunch, 2000);
}

async function startGame() {
  if (serverConfig && serverConfig.native_replays) return;
  launch.since = performance.now();
  launch.liveAsked = false;
  launch.status = 'opening'; launch.detail = '';
  renderLaunchStatus();
  const r = await api('/api/launch_game', {}).catch((e) => ({ status: 'launchFailed', detail: String(e.message || e) }));
  setLaunchStatus(r);
  if (LAUNCH_FAILED.includes(launch.status)) toast(`${t('Age II status: {s}', { s: t(GAME_STATUS[launch.status] || launch.status) })}`);
  renderLaunchStatus();
  if (LAUNCH_WAITING.includes(launch.status)) launch.timer = setTimeout(pollLaunch, 2000);
}

// "{map} | {N} players" for the ready card (source.game_details, else the match).
function gameDetails(src) {
  const gd = src.game_details || {};
  const ps = (S.match && S.match.players) || {};
  const n = gd.player_count ?? (Object.keys(ps).filter((k) => Number(k) > 0).length || null);
  let map = gd.map_name || (S.match && (S.match.map_name || S.match.map)) || '';
  if (!map && S.match && S.match.map_file) map = String(S.match.map_file).replace(/\.rms2?$/i, '').replace(/_/g, ' ');
  if (!map && !n) return t('Unknown game');
  return t('{map} | {n} players', { map: map || t('Unknown map'), n: n ?? '?' });
}

let launchKey = '';
function renderLaunchStatus() {
  const el = $('launch-status');
  if (S.end > S.start && !(source().status === 'needs_confirm')) { el.classList.add('hidden'); return; }
  if (serverConfig && serverConfig.native_replays) { el.classList.add('hidden'); return; }
  const src = source();
  const st = src.status;
  const connected = !!(S.session && S.session.live_connected);
  const waitingForStream = isLive() && !st && !connected && S.end === 0;
  // The certificate files are missing: known at once from the session, before
  // the first connection attempt times out.
  const missing = (S.session && S.session.certs && S.session.certs.missing) || [];
  if (isLive() && !connected && (st === 'needs_certs' || (missing.length && ['connecting', undefined, null, ''].includes(st)))) {
    renderCertsCard(el, S.session.certs);
    return;
  }
  const liveCard = isLive() && (['connecting', 'joining', 'waiting_lobby', 'loading', 'ready'].includes(st) || waitingForStream);
  // Nothing answers on the game's port: say so rather than "Connecting…" forever.
  const gameOff = liveCard && st === 'connecting' && !connected && overlays.gameUnreachable((S.session && S.session.error) || '');
  // A launch in progress shows the card on its own; "Connected" lingers 3 s.
  const ls = launch.status;
  const launchCard = !!ls && (ls !== 'connected' || performance.now() - launch.connectedAt < 3000)
    && !(connected && st === 'playing');
  if (!liveCard && !launchCard) { el.classList.add('hidden'); launchKey = ''; return; }
  const l = lobbyInfo(src);
  const d = specDelay(src);
  const title = gameOff && !LAUNCH_WAITING.includes(ls) ? t('Age II is not running')
    : liveCard ? (launchText(src) || t(LAUNCH_TEXT.connecting)) : t(LAUNCH_WAITING.includes(ls) ? 'Starting Age II…' : 'Start Age II');
  const details = [];
  if (liveCard && st === 'ready') details.push(esc(gameDetails(src)));
  if (l && l.name) details.push(esc(l.name));
  if (l && Array.isArray(l.players) && l.players.length) details.push(esc(l.players.map((p) => (typeof p === 'object' ? p.name : p)).join(' · ')));
  if (d) details.push(t('Spec delay: {n}s', { n: Math.round(d) }));
  if (src.replay) details.push(esc(String(src.replay).split(/[\\/]/).pop()));
  if (src.load_result != null && src.load_result !== 0 && src.load_result !== 'OK') details.push(t('The game replied: {code}', { code: esc(src.load_result) }));
  if (ls) {
    const cls = LAUNCH_FAILED.includes(ls) ? 'bad' : ls === 'connected' ? 'good' : '';
    details.push(`<span class="ls-game ${cls}">${esc(t('Age II status: {s}', { s: t(GAME_STATUS[ls] || ls) }))}</span>${launch.detail ? ` <span class="hint">${esc(launch.detail)}</span>` : ''}`);
  }
  // Offer to start the game while nothing is connected and no launch is under way.
  const canStart = !connected && !LAUNCH_WAITING.includes(ls) && (!liveCard || ['connecting', undefined, null, ''].includes(st) || LAUNCH_FAILED.includes(ls));
  const spinning = (liveCard && st !== 'ready') || LAUNCH_WAITING.includes(ls);
  const key = `${title}|${details.join('|')}|${canStart}|${spinning}|${liveCard}|${language}`;
  el.classList.remove('hidden');
  if (key === launchKey) return;
  launchKey = key;
  patchHtml(el, `<div class="ls-title">${spinning ? '<span class="ls-spin"></span>' : ''}${esc(title)}</div>
    ${details.map((x) => `<div class="ls-detail">${x}</div>`).join('')}
    <div class="ls-actions">
    ${canStart ? `<button data-ls-start class="on" ${tip(t('Start Age II'), t('Starts Age of Empires II: DE through Steam so Vantage is ready to watch games. Make sure you are logged in to Steam, or the game will fail to launch.'))}>▶ ${t('Start Age II')}</button>` : ''}
    ${liveCard ? `<button data-ls-stop ${tip(t('Stop watching'), t('Disconnect from the game and go back to the home screen'))}>■ ${t('Stop watching')}</button>` : `<button data-ls-dismiss>${t('Close')}</button>`}
    </div>`);
  const stop = el.querySelector('[data-ls-stop]');
  if (stop) stop.onclick = stopWatching;
  const start = el.querySelector('[data-ls-start]');
  if (start) start.onclick = () => startGame();
  const dismiss = el.querySelector('[data-ls-dismiss]');
  if (dismiss) dismiss.onclick = () => { clearTimeout(launch.timer); launch.status = null; renderLaunchStatus(); };
}

function renderCertsCard(el, certs) {
  const files = (certs.missing || []).map((f) => `<code>${esc(f)}</code>`).join(' ');
  const key = `certs|${files}|${certs.dir}|${language}`;
  el.classList.remove('hidden');
  if (key === launchKey) return;
  launchKey = key;
  el.innerHTML = `<div class="ls-title">⚠ ${esc(t('Certificate files needed'))}</div>
    <div class="ls-detail">${t('The game accepts only a spectator app holding its client certificate. Put these files in {dir}:', { dir: `<code>${esc(certs.dir || '')}</code>` })}</div>
    <div class="ls-detail">${files}</div>
    <div class="ls-detail"><a href="${esc(certs.docs || `${overlays.REPO_URL}/wiki/Live-games`)}" target="_blank" rel="noopener">${esc(t('About the certificate files'))}</a></div>
    <div class="ls-detail hint">${esc(t('Vantage keeps trying and connects once the files are in place.'))}</div>
    <div class="ls-actions"><button data-ls-stop>■ ${esc(t('Stop watching'))}</button></div>`;
  el.querySelector('[data-ls-stop]').onclick = stopWatching;
}

function subscribe() {
  const es = new EventSource('/api/stream');
  es.onmessage = (m) => { refreshSession(JSON.parse(m.data)).catch(console.error); };
  // Skin files changed (the server watches the enabled skins).
  es.addEventListener('skins', () => { if (settings.toggleHTMLServer) reloadSkins(); });
  es.onerror = () => { $('status-line').textContent = `⚠ ${t('server unreachable')}`; };
}

// -- skin debugging ---------------------------------------------------------------------
// Skin CSS is easiest to iterate on in a browser with dev tools. Vantage already
// is a web page, so the setting means: listen for skin-file changes and
// live-reload the skin stylesheets (and the merged skin options/assets), and
// "Open webpage" opens Vantage in a normal browser tab for dev tools.
// /stats-dump serves the stats.
let skinEs = null, skinPoll = null, skinVersion = null;
function syncHtmlServer() {
  const on = !!settings.toggleHTMLServer;
  if (on && !skinEs && !skinPoll) {
    skinEs = new EventSource('/sse?skins=1');
    const onUpdate = (m) => { if (!m || m.data == null || String(m.data).includes('update')) reloadSkins(); };
    skinEs.addEventListener('skins', onUpdate);
    skinEs.onmessage = onUpdate;
    skinEs.onerror = () => {
      // No SSE route: poll the skins version instead.
      if (skinEs && skinEs.readyState === EventSource.CLOSED) { skinEs = null; skinPoll = setInterval(pollSkinVersion, 2000); }
    };
  } else if (!on && (skinEs || skinPoll)) {
    if (skinEs) skinEs.close();
    clearInterval(skinPoll);
    skinEs = null; skinPoll = null; skinVersion = null;
  }
}
async function pollSkinVersion() {
  const r = await api('/api/skins/version').catch(() => null);
  if (!r || r.version == null) return;
  if (skinVersion != null && r.version !== skinVersion) reloadSkins();
  skinVersion = r.version;
}
let skinReloadAt = 0;
function reloadSkins() {
  const now = performance.now();
  if (now - skinReloadAt < 200) return; // debounce bursts of file events
  skinReloadAt = now;
  const v = Date.now();
  for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
    const href = link.getAttribute('href') || '';
    if (!href.includes('/skins/')) continue;
    const u = new URL(href, location.href);
    u.searchParams.set('v', String(v));
    link.href = u.pathname + u.search;
  }
  document.dispatchEvent(new CustomEvent('vantage:skins'));
  toast(t('Skin reloaded'));
}
function openHtmlServer() {
  window.open(`${location.origin}/`, '_blank', 'noopener');
}

let pendingView = null, viewEpoch = 0, viewRetryAt = 0;
// While the time bar is dragged, views are asked for on the shared 1 s grid (as
// look-ahead is): positions a few pixels apart then reuse one request and one
// cached view. The release asks for its exact time.
function viewRequestTime(t) {
  return S.scrubbing ? Math.max(S.start, Math.floor(t / 1000) * 1000) : t;
}
// `keepView`: a seek in the same game keeps drawing the current view (still,
// as at the live edge) until the new one arrives, instead of a blank world.
function resetViews(keepView = false) {
  viewEpoch++;
  pendingView = null;
  viewRetryAt = 0;
  abortViews();
  if (!keepView) S.view = null;
  S.nextView = null; S.aheadView = null; S.upcoming = [];
}

// Use a shared request grid so adjacent keyframes reuse the same look-ahead
// requests, even when their actual times are a few milliseconds off the grid.
function viewRequests(v) {
  const rate = S.playing ? SPEEDS[S.speedIndex] || 1 : 1;
  const sp = Math.abs(rate);
  const far = !isLive() && sp >= 8 ? 16 : sp >= 4 ? 5 : 4;
  const base = Math.floor(v.time / 1000) * 1000;
  const offsets = Array.from({ length: rate < 0 ? 3 : far }, (_, i) => i + 1);
  if (rate < 0) for (let k = 1; k <= far; k++) offsets.push(-k);
  return [...new Set(offsets.map((k) => Math.max(S.start, Math.min(S.end, base + k * 1000))))];
}

function primeViews(v, epoch) {
  for (const at of viewRequests(v)) {
    fetchView(at).then((a) => {
      if (epoch !== viewEpoch || !a || a.time <= v.time) return;
      // A refetch of a view that was not final (its track was still filling)
      // replaces the one held for the same time.
      const newer = (held) => held && held !== a && held.time === a.time && held.final === false;
      if (S.view === v && (!S.nextView || a.time < S.nextView.time || newer(S.nextView))) S.nextView = a;
      if (a.time > S.t && !S.upcoming.includes(a)) {
        S.upcoming = [...S.upcoming.filter((u) => u.time > S.t && u.time !== a.time), a].sort((x, y) => x.time - y.time);
        S.aheadView = S.upcoming.at(-1);
      }
    });
  }
}

async function updateView() {
  if (pendingView) return;
  if (S.view && S.nextView && S.t >= S.view.time && S.t < S.nextView.time) return;
  // At the live edge, retry look-ahead as the stream grows, without issuing a
  // different request for every animation frame.
  if (S.view && !S.nextView && S.t >= S.view.time && S.t < S.view.time + 3000) {
    if (!S.scrubbing && performance.now() >= viewRetryAt) {
      viewRetryAt = performance.now() + 100;
      primeViews(S.view, viewEpoch);
      // The newest keyframe's track fills in after it is first served: take
      // the final version once the cache lets it be fetched again.
      if (S.view.final === false) {
        const held = S.view, epoch = viewEpoch;
        fetchView(held.time).then((a) => { if (epoch === viewEpoch && S.view === held && a && a !== held && a.time === held.time) S.view = a; });
      }
    }
    return;
  }
  const epoch = viewEpoch;
  pendingView = (async () => {
    // Crossing into the next view: show that very view, the one graphics
    // buffering checked (a refetch by time can resolve to another keyframe).
    const n = S.nextView;
    const cached = cachedViewAt(S.t);
    const v = n && S.view && n.time > S.view.time && S.t >= n.time && S.t < n.time + 1500
      ? n : cached && S.t - cached.time < 3000 ? cached : await fetchView(viewRequestTime(S.t));
    if (epoch !== viewEpoch) return;
    if (v && v.time != null) {
      S.view = v;
      if (S.jump && !S.jump.wait && Math.abs(v.time - S.jump.to) < 2500) S.jump = null;
      // Install the next cached target in this same frame. Awaiting it here
      // left one or more frames with no interpolation at every boundary.
      S.nextView = null;
      for (const at of viewRequests(v)) {
        const a = cachedView(at);
        if (a && a.time > v.time && (!S.nextView || a.time < S.nextView.time)) S.nextView = a;
      }
      // Normal speed and live playback need look-ahead too, so the following
      // target and its graphics arrive before this interpolation finishes.
      // Not while the scrub bar is dragged: only the released position matters.
      if (!S.scrubbing) primeViews(v, epoch);
      world.refreshTrees(S.t);
      world.refreshTerrain(S.t);
    }
  })().finally(() => { if (epoch === viewEpoch) pendingView = null; });
}

// -- playback ---------------------------------------------------------------------------

function gameSpeed() { return (S.match && S.match.speed) || 1.7; }

// Real speed: game ms advanced per wall ms, measured over ~1 s windows.
const speedMeter = { t: null, wall: 0, real: null };

function measureSpeed(now) {
  if (speedMeter.t == null) { speedMeter.t = S.t; speedMeter.wall = now; return; }
  const dw = now - speedMeter.wall;
  if (dw < 1000) return;
  const r = (S.t - speedMeter.t) / dw;
  speedMeter.real = speedMeter.real == null ? r : speedMeter.real * 0.4 + r * 0.6;
  speedMeter.t = S.t; speedMeter.wall = now;
}

// -- buffering for fast live replay ---------------------------------------------------
// The game cannot always replay as fast as the chosen speed (late in a large game
// it simulates ~5-6x on a typical PC). With the replay's length known, playback
// waits at the right moment so the rest can be watched at the chosen speed
// without catching up with the game: a few buffering pauses instead of a crawl.
const production = { t: null, end: 0, rate: null, samples: 0 };
function measureProduction(now) {
  if (!isLive()) { production.t = null; production.rate = null; production.samples = 0; return; }
  if (production.t == null || S.end < production.end) { production.t = now; production.end = S.end; return; }
  const dw = now - production.t;
  if (dw < 3000) return;
  const r = (S.end - production.end) / dw; // game ms per wall ms
  // A slow average (~15 s): the game's pace drifts as armies grow, frame bursts don't count.
  production.rate = production.rate == null ? r : production.rate * 0.8 + r * 0.2;
  production.samples++;
  production.t = now; production.end = S.end;
}
/** Wall ms playback should still wait so it never catches up with the game (0 = play). */
export function bufferWait() {
  const src = source();
  if (!isLive() || S.followLive || !S.liveSpeedPicked || !S.playing) return 0;
  return replayBufferWait({
    total: src.replay_duration_ms, end: S.end, t: S.t,
    watch: SPEEDS[S.speedIndex] * gameSpeed(), rate: production.rate, samples: production.samples,
    producing: !gameStoppedProducing(src),
  });
}
/** The game sends no more frames: paused (a replay pauses itself at its end), over, or stalled. */
function gameStoppedProducing(src) {
  return !!(src.paused || matchEnded(src) || src.waiting);
}

function targetSpeed() {
  if (isLive() && S.followLive) return null; // the game sets the pace
  const q = S.highlight.seq;
  if (q && q.rate != null && S.playing) return q.rate;
  return S.playing ? SPEEDS[S.speedIndex] * gameSpeed() : 0;
}

let gameOverCheckAt = 0;
let serverConfig = null, playbackEndedSent = false;
// `--exit-on-stream-end` for a recording: the server exits once the browser has
// played it to the end (only the browser knows when that is).
function reportPlaybackEnd(live) {
  if (playbackEndedSent || live || !S.complete || !serverConfig || !serverConfig.exit_on_stream_end) return;
  playbackEndedSent = true;
  api('/api/playback_ended', {}).catch(() => {});
}
function gameOver(live) {
  if (!live) return !!(S.view && S.view.game_ended === true);
  if (matchEnded(source()) || S.complete) return true;
  const now = performance.now();
  if (now < gameOverCheckAt) return false;
  gameOverCheckAt = now + 500;
  return S.events.some((e) => e.cat === 'status' && e.kind === 'won');
}

const GFX_HOLD_MS = 5000; // a stuck request must not freeze playback; any real strip arrives well within it
let gfxHoldSince = 0;
function tick(now) {
  requestAnimationFrame(tick);
  if (settings.limitToSixtyFps) {
    // 60 fps cap: draw when the next 1/60 s slot is due (1 ms tolerance for jitter).
    if (now < nextFrameDue - 1) return;
    nextFrameDue = Math.max(nextFrameDue + 1000 / 60, now - 1000 / 60);
  }
  const t0 = performance.now(); // our own start (the rAF time is the frame's start)
  const dt = Math.min(0.25, (now - lastFrame) / 1000);
  lastFrame = now;
  fpsAcc += dt; fpsN++;
  perfTick(now, dt);
  if (fpsAcc > 0.5) { S.fps = Math.round(fpsN / fpsAcc); fpsAcc = 0; fpsN = 0; }
  const live = isLive();
  S.bufferWait = 0; S.gfxWait = false;
  // A finished match sends nothing more: its last frame is the end, with no 0.4 s hold behind it.
  const over = live && matchEnded(source());
  if (live && S.followLive) {
    S.t = over ? S.end : Math.max(S.start, S.end - 400);
  } else if (S.jump && S.jump.wait) {
    // A jump past the loaded part of a recording waits for the loader.
    if (S.end >= S.jump.to) { S.t = S.jump.to; S.jump.wait = false; resetViews(); }
    else S.t = S.end;
  } else if (S.playing && (S.bufferWait = bufferWait()) > 0) {
    // Buffering for fast replay: hold until the rest can be watched at full speed.
  } else if (S.playing) {
    const q = S.highlight.seq;
    const prev = S.t;
    S.t += dt * 1000 * (q && q.rate != null ? q.rate : SPEEDS[S.speedIndex] * gameSpeed());
    // Live, playback holds 0.4 s behind the newest data (as following the live
    // edge does) so there is a next view to interpolate towards; never backwards.
    const edge = live && !over ? Math.max(S.start, S.end - 400) : S.end;
    if (S.t >= edge) {
      S.t = Math.max(Math.min(prev, S.end), edge);
      if (over) S.playing = false; // the end of a finished match: stopped, not stuck playing
      // Caught up with the live edge: follow it, unless a speed was picked in this
      // live session (then wait at the edge and keep that speed: at 4x the game is
      // told to run faster than 4x so a buffer builds, and the view stays at 4x).
      if (live && !over && !S.highlight.seq && !S.liveSpeedPicked) S.followLive = true;
    }
    if (S.t < S.start) { S.t = S.start; S.playing = false; }
    // Graphics buffering (world.viewReady): hold just before the next view until
    // the strips it draws on screen are in, at most GFX_HOLD_MS at a time.
    const n = S.nextView;
    if (!live && settings.waitForGraphics !== false && n && S.t >= n.time && prev < n.time) {
      if (world.viewReady(n)) gfxHoldSince = 0;
      else {
        if (!gfxHoldSince) gfxHoldSince = now;
        if (now - gfxHoldSince < GFX_HOLD_MS) { S.t = Math.max(prev, n.time - 1); S.gfxWait = true; }
      }
    }
  }
  if (S.reviewPlaybackUntil != null && S.t >= S.reviewPlaybackUntil) { S.t = S.reviewPlaybackUntil; S.playing = false; S.reviewPlaybackUntil = null; }
  if (!endgameShown && S.end > 0 && S.t >= S.end - 1500 && !S.highlight.seq && gameOver(live)) { endgameShown = true; showEndgame(); }
  if (S.end > 0 && S.t >= S.end) reportPlaybackEnd(live);
  measureSpeed(now);
  startReadAhead();
  measureProduction(now);
  const tv = performance.now();
  updateView();
  if (perf.on) perf.update.push(performance.now() - tv);
  world.refreshTerrain(S.t); // no-op unless a throttled terrain change is still waiting
  world.refreshTrees(S.t); // likewise for the forest
  world.edgeScroll(mouse.x, mouse.y, dt);
  autocastTick(now, dt);
  audio.tick(world.toScreen);
  world.draw(dt);
  const tm = performance.now();
  world.drawMinimap();
  if (perf.on) {
    perf.minimap.push(performance.now() - tm);
    perf.work.push(performance.now() - t0);
  }
  if (S.showFps) {
    const real = speedMeter.real == null ? '–' : `${speedMeter.real.toFixed(2)}×`;
    const target = targetSpeed();
    $('status-line').textContent = `${S.fps} fps · ${t('real')} ${real} · ${t('target')} ${target == null ? t('live') : `${target.toFixed(2)}×`} ${t('game')}`;
  }
}

// The left column (team overview, techs, production) sits below the scoreboard
// when the two would overlap (6-8 player scoreboards are wide) and ends above
// the time bar. Re-measured only when one of them changes size.
// The dashboard is centred at the bottom unless that would put it over the minimap
// (left) or past the window (right): then it starts just right of the minimap.
// Placing the dashboard resets and measures panel boxes, a forced layout: do it
// when one of the panels involved changed size (or the window did), and once a
// second for anything else (a panel dragged elsewhere), not four times a second.
let placeDirty = true, placedAt = 0;
const placeObserver = new ResizeObserver(() => { placeDirty = true; });
let placeObserved = false;
function placeDashboard() {
  placeDirty = false; placedAt = performance.now();
  if (!placeObserved) {
    placeObserved = true;
    for (const id of ['dashboard', 'minimap-wrap', 'timebar', 'unitpanel', 'events']) if ($(id)) placeObserver.observe($(id));
    window.addEventListener('resize', () => { placeDirty = true; });
  }
  const d = $('dashboard'), m = $('minimap-wrap'), eventsPanel = $('events');
  if (eventsPanel) eventsPanel.style.maxHeight = '';
  // Caster: the selection panel sits left of the minimap (hud-layout.css --mm-gap).
  if (m) {
    const gap = m.classList.contains('hidden') ? '8px' : `${Math.round(window.innerWidth - m.getBoundingClientRect().left + 8)}px`;
    if (document.documentElement.style.getPropertyValue('--mm-gap') !== gap) document.documentElement.style.setProperty('--mm-gap', gap);
  }
  if (!d || d.classList.contains('hidden')) return;
  const vw = window.innerWidth;
  const shown = (el) => el && !el.classList.contains('hidden') && !el.classList.contains('panel-off') && el.getClientRects().length;
  const tb = $('timebar');
  let left;
  if (document.body.dataset.hudLayout === 'caster') {
    // Between the panels stacked bottom left and the minimap bottom right.
    const band = window.innerHeight - 8 - d.offsetHeight;
    let lo = 8, hi = vw - 8;
    for (const el of document.querySelectorAll('#leftcol > .panel, #leftcol2 > .panel')) {
      if (!shown(el) || el.classList.contains('hud-custom-size')) continue;
      const r = el.getBoundingClientRect();
      if (r.bottom > band) lo = Math.max(lo, r.right + 8);
    }
    if (shown(m) && !m.classList.contains('hud-custom-size')) hi = Math.min(hi, m.getBoundingClientRect().left - 8);
    if (shown(tb) && !tb.classList.contains('hud-custom-size') && tb.getBoundingClientRect().bottom > band) hi = Math.min(hi, tb.getBoundingClientRect().left - 8);
    const maxW = `${Math.max(240, Math.round(hi - lo))}px`;
    if (d.style.maxWidth !== maxW) d.style.maxWidth = maxW;
    left = Math.round(Math.min(Math.max((vw - d.offsetWidth) / 2, lo), Math.max(lo, hi - d.offsetWidth)));
  } else {
    if (d.style.maxWidth) d.style.maxWidth = '';
    // Clear of the minimap, and of the time bar above it when the dashboard is tall
    // enough to reach its height (the time bar widens with a 1:00:00 clock).
    let clear = shown(m) ? m.getBoundingClientRect().right + 8 : 8;
    if (shown(tb)) {
      const r = tb.getBoundingClientRect();
      if (r.bottom > window.innerHeight - 8 - d.offsetHeight) clear = Math.max(clear, r.right + 8);
    }
    left = Math.max(clear, Math.round((vw - d.offsetWidth) / 2));
  }
  const want = `${left}px`;
  if (d.style.left !== want) { d.style.left = want; d.style.transform = 'none'; }
  // A wide page on a narrow window reaches under the unit panel (bottom right):
  // the unit panel then sits above the dashboard, between it and the events.
  const up = $('unitpanel');
  if (!up || up.classList.contains('hidden')) return;
  up.style.bottom = ''; up.style.maxHeight = '';
  const a = d.getBoundingClientRect(), b = up.getBoundingClientRect();
  if (a.right <= b.left || b.right <= a.left || a.bottom <= b.top) return;
  const ev = $('events');
  if (ev && !ev.classList.contains('hidden') && ev.getBoundingClientRect().right > b.left) {
    const reserve = Math.min(350, window.innerHeight * .55);
    ev.style.maxHeight = `${Math.max(80, Math.floor(a.top - ev.getBoundingClientRect().top - reserve - 18))}px`;
  }
  const evBottom = ev && !ev.classList.contains('hidden') && ev.getBoundingClientRect().right > b.left ? ev.getBoundingClientRect().bottom : 0;
  up.style.bottom = `${Math.round(window.innerHeight - a.top + 6)}px`;
  up.style.maxHeight = `${Math.max(120, Math.round(a.top - 12 - evBottom))}px`;
}

function layoutLeftColumn() {
  const col = $('leftcol'), sb = $('scoreboard'), tb = $('timebar');
  if (!col || !sb || !tb) return;
  const s = sb.getBoundingClientRect(), b = tb.getBoundingClientRect();
  // Slide-outs and toasts open below the scoreboard, never over it.
  document.documentElement.style.setProperty('--sb-bottom', `${!sb.classList.contains('hidden') && s.height > 0 ? Math.round(s.bottom) : 8}px`);
  const colRight = col.getBoundingClientRect().left + Math.max(col.scrollWidth, 340);
  const overlaps = !sb.classList.contains('hidden') && s.width > 0 && s.left < colRight;
  // Caster: the column fills the height under the scoreboard and its panels stack
  // from the bottom (hud-layout.css); the time controls are bottom right.
  const caster = document.body.dataset.hudLayout === 'caster';
  const sbShown = !sb.classList.contains('hidden') && s.height > 0;
  const top = caster ? Math.round((sbShown ? s.bottom : 2) + 6) : overlaps ? Math.max(64, Math.round(s.bottom + 6)) : 64;
  const tbLeft = !tb.classList.contains('hidden') && b.height > 0 && b.left < colRight;
  const bottom = (caster ? tbLeft : !tb.classList.contains('hidden') && b.height > 0) ? b.top - 6 : window.innerHeight - 8;
  const maxH = `${Math.max(120, Math.round(bottom - top))}px`;
  col.style.top = `${top}px`;
  col.style.maxHeight = maxH;
  col.style.height = caster ? maxH : '';
  // Panels that do not fit under the overview (a short window) move to a second
  // column beside it instead of hiding below a scroll fold.
  const col2 = $('leftcol2');
  if (!col2) return;
  for (const id of ['techs', 'production']) {
    const el = $(id);
    if (!el) continue;
    el.classList.remove('no-room');
    if (el.classList.contains('hud-custom-size')) continue;
    if (el.parentElement !== col) col.appendChild(el);
  }
  for (const id of ['production', 'techs']) {
    if (col.scrollHeight <= col.clientHeight + 1) break;
    const el = $(id);
    if (el && !el.classList.contains('hidden') && !el.classList.contains('hud-custom-size')) col2.prepend(el);
  }
  const left = Math.round(col.getBoundingClientRect().right + 6);
  // Slide-outs (right-anchored) stop short of the left-hand panels.
  const lastRight = Math.max(col.getBoundingClientRect().right, col2.children.length ? col2.getBoundingClientRect().right : 0);
  document.documentElement.style.setProperty('--left-panels', `${Math.round(lastRight + 6)}px`);
  col2.style.top = `${top}px`;
  col2.style.maxHeight = maxH;
  col2.style.height = caster && col2.children.length ? maxH : '';
  col2.style.left = `${left}px`;
  // Still no room (a small window with every panel on): a panel that would run
  // under the events panel or off the bottom is left out, with a note once,
  // rather than drawn cut off.
  const ev = $('events');
  const right = ev && !ev.classList.contains('hidden') ? ev.getBoundingClientRect().left - 6 : window.innerWidth - 8;
  col2.style.maxWidth = `${Math.max(200, right - left)}px`; // production's rows wrap to fit
  for (const id of ['techs', 'production']) {
    const el = $(id);
    if (!el || el.parentElement !== col2 || el.classList.contains('hidden') || el.classList.contains('hud-custom-size')) continue;
    if (el.scrollWidth > el.clientWidth + 1 || col2.scrollHeight > col2.clientHeight + 1) {
      el.classList.add('no-room');
      if (!noRoomNoted.has(id)) {
        noRoomNoted.add(id);
        toast(t(id === 'techs' ? 'No room for the technology grid in this window: open it as a slide-out instead' : 'No room for the production panel in this window'));
      }
    }
  }
}
const noRoomNoted = new Set();
const leftColObserver = new ResizeObserver(() => layoutLeftColumn());

let hudTimer = null;
let tooltipMode = null;
// While a mouse button is held on the UI, the 250 ms re-render waits: a panel
// rebuilt between mousedown and mouseup loses the click.
// Only for controls the re-render rebuilds (not the scrub bar, the minimap or form
// fields, which are dragged), and only for a click's length: a held or dragged
// press must not freeze the clock and panels.
let uiPress = 0;
window.addEventListener('mousedown', (e) => {
  const tgt = e.target;
  uiPress = tgt !== $('world') && tgt.closest('#hud, .overlay') && !tgt.closest('#scrub, #minimap-wrap, input, select, textarea')
    ? performance.now() : 0;
}, true);
const releasePress = () => { if (uiPress) { uiPress = 0; setTimeout(renderHud, 0); } };
window.addEventListener('mouseup', releasePress, true);
window.addEventListener('contextmenu', releasePress, true);
window.addEventListener('blur', releasePress);
function renderHud() {
  reviewStatus(autocast.on ? 'Auto' : S.followSelection ? 'Follow selection' : 'Free');
  if (uiPress && performance.now() - uiPress < 400) return;
  const sp = SPEEDS[S.speedIndex];
  const label = isLive() && S.followLive ? t('LIVE') : `${S.playing ? '' : t('paused') + ' · '}${sp}×`;
  panels.renderScoreboard(label);
  panels.renderOverview();
  panels.renderTechs();
  panels.renderProduction();
  panels.renderDashboard();
  if (placeDirty || performance.now() - placedAt > 1000) placeDashboard();
  if (settings.showEvents) panels.renderEvents(seek);
  $('events').classList.toggle('hidden', !settings.showEvents);
  panels.renderUnitPanel();
  panels.renderResourcesLeft(showResLeft);
  panels.renderTimebar();
  layout.applyPanels();
  const pp = settings.post || {};
  const g = pp.gamma || 1;
  // Only on change: rewriting the SVG filter invalidates the CSS filter using it.
  const exponent = String(1 / g);
  for (const id of ['gamma-func', 'gamma-r', 'gamma-g', 'gamma-b']) {
    const el = $(id);
    if (el && el.getAttribute('exponent') !== exponent) el.setAttribute('exponent', exponent);
  }
  // A CSS filter on the full-screen canvas costs a filter pass every frame (heavy in
  // Firefox), so the neutral picture uses none at all.
  const b = pp.brightness || 1, c = pp.contrast || 1, sat = pp.saturation || 1;
  const filter = b === 1 && c === 1 && sat === 1 && g === 1 ? 'none'
    : `brightness(${b}) contrast(${c}) saturate(${sat})${g !== 1 ? ' url(#gamma)' : ''}`;
  if ($('world').style.filter !== filter) $('world').style.filter = filter;
  for (const sk of ['classic', 'contrast', 'clean']) document.body.classList.toggle(`skin-${sk}`, settings.skin === sk);
  // Tooltip mode: body[data-tooltips] drives the CSS and the static title= texts.
  const mode = tooltipLevel();
  if (mode !== tooltipMode) { tooltipMode = mode; document.body.dataset.tooltips = mode; translateStatic(); }
  if ($('fog-label').textContent !== fogLabel()) $('fog-label').textContent = fogLabel();
  panels.rememberSelection();
  renderTimeExtras();
  renderPauseBanner();
  renderJumpBanner();
  renderLaunchStatus();
  syncHtmlServer();
  renderHighlights();
}

function renderPauseBanner() {
  const src = source();
  const pb = $('pause-banner');
  const waiting = waitingPlayers();
  // The banner hides while the end-game screen shows; who paused is known only from API 22.
  const namesPauser = src.paused_by > 0 && Number(src.api_version) >= 22;
  if (overlays.isOpen('overlay-endgame')) pb.classList.add('hidden');
  // Reading a replay ahead, the game runs (and at its end pauses) well before the viewer
  // gets there: while buffered footage is still playing, the game's pause is not news.
  else if (src.paused && readAhead() && S.end - S.t > 1500) pb.classList.add('hidden');
  else if (src.paused && readAhead() && src.replay_duration_ms && S.end >= src.replay_duration_ms - 5000) { pb.textContent = t('Replay finished'); pb.classList.remove('hidden'); }
  else if (src.paused) { pb.textContent = namesPauser ? t('Game paused by {p}', { p: playerName(src.paused_by) }) : t('Game paused'); pb.classList.remove('hidden'); }
  else if (waiting) { pb.textContent = waiting.length ? t('Waiting for players: {who}', { who: waiting.map(playerName).join(', ') }) : t('Waiting for players'); pb.classList.remove('hidden'); }
  else pb.classList.add('hidden');
}

// Jump banner:
// "Jumping to {time}" while a seek is in flight, "Rendering" when the view is
// loading with no target. The bar is real progress when the jump waits for a
// recording to load past its end; for an ordinary seek (one keyframe fetch)
// it is indeterminate. Stop Jump cancels: back to where the jump started, or
// stay at the loaded end for a waiting jump.
let jumpKey = '';
function renderJumpBanner() {
  const el = $('jump-banner');
  const j = S.jump;
  // A seek keeps drawing the old view until the new one arrives: still loading.
  const loading = (!S.view || (j && !j.wait && Math.abs(S.view.time - j.to) > 2500)) && S.end > 0;
  const show = !!(j && j.wait) || (loading && (!j || performance.now() - j.at > 150));
  if (!show) { el.classList.add('hidden'); jumpKey = ''; return; }
  const text = j ? t('Jumping to {time}', { time: fmtTime(j.to) }) : t('Rendering');
  const span = j ? Math.abs(j.to - j.from) : 0;
  const pct = j && j.wait && span > 0 ? Math.max(0, Math.min(1, Math.abs(S.end - j.from) / span)) : null;
  el.classList.remove('hidden');
  const key = `${text}|${!!j}|${pct == null}|${language}`;
  if (key !== jumpKey) {
    jumpKey = key;
    patchHtml(el, `<div class="jb-text">${esc(text)}</div><div class="jb-bar${pct == null ? ' indeterminate' : ''}"><i></i></div>
      ${j ? `<button data-stop-jump ${tip(t('Stop Jump'), t('Cancel the jump'))}>${t('Stop Jump')}</button>` : ''}`);
    const b = el.querySelector('[data-stop-jump]');
    if (b) b.onclick = () => { stopJump(); renderHud(); };
  }
  if (pct != null) el.querySelector('.jb-bar i').style.width = `${(pct * 100).toFixed(1)}%`;
}

function stopJump() {
  const j = S.jump;
  if (!j) return;
  S.jump = null;
  if (!j.wait) { S.t = Math.max(S.start, Math.min(S.end, j.from)); resetViews(); }
  if (S.highlight.seq) { S.highlight.seq.paused = true; S.highlight.seq.pausedAt = S.t; S.playing = false; }
}

// Players the game is waiting for (lagging / reconnecting): from the live
// source, or from a 'waiting' event at the playback time. null = nobody.
function waitingPlayers() {
  const w = source().waiting;
  const list = (x) => (Array.isArray(x) ? x : x && typeof x === 'object' ? (x.players || []) : []).map((p) => (typeof p === 'object' ? p.id ?? p.player : p)).filter((p) => p != null);
  if (w && (!isLive() || S.followLive)) return list(w);
  for (let i = S.events.length - 1; i >= 0; i--) {
    const e = S.events[i];
    if (e.t > S.t) continue;
    if (S.t - e.t > 3000) break;
    if (e.kind === 'waiting') return list(e.players || (e.player != null ? [e.player] : []));
  }
  return null;
}

function renderTimeExtras() {
  const live = isLive();
  document.body.classList.toggle('live-session', live);
  document.body.classList.toggle('no-scrub', seekLocked());
  $('tc-rec').classList.toggle('on', recordingActive());
  const real = speedMeter.real, target = targetSpeed();
  const el = $('tc-real');
  // Paused, the measured speed only decays towards 0: show nothing then.
  if (S.playing && S.bufferWait > 0) {
    panels.setText(el, t('Buffering for {x}×: {time}', { x: SPEEDS[S.speedIndex], time: fmtTime(S.bufferWait) }));
    el.classList.remove('off-target');
  } else if (S.playing && gfxHoldSince && performance.now() - gfxHoldSince > 300) {
    panels.setText(el, t('Loading graphics…'));
    el.classList.remove('off-target');
  } else if (real == null || !S.playing) panels.setText(el, '');
  else {
    panels.setText(el, `${t('real')} ${(real / gameSpeed()).toFixed(2)}×`);
    el.classList.toggle('off-target', target != null && target > 0 && Math.abs(real - target) > target * 0.15);
  }
  renderSkips();
}

// Markers where the stream skipped (status.skips: [[from_ms, to_ms], …]).
let skipsKey = '';
function renderSkips() {
  const tl = (S.session && S.session.timeline) || {};
  const skips = tl.skips || (S.session && S.session.skips) || source().skips || [];
  const key = `${S.start}|${S.end}|${skips.length}|${seekLocked()}`;
  if (key === skipsKey) return;
  skipsKey = key;
  const span = Math.max(1, S.end - S.start);
  $('scrub-skips').innerHTML = skips.map(([a, b]) => {
    const l = Math.max(0, Math.min(100, ((a - S.start) / span) * 100));
    const w = Math.max(0, Math.min(100 - l, ((b - a) / span) * 100));
    return `<i style="left:${l}%;width:${w}%" ${tip(t('Stream skipped'), `${fmtTime(a)} → ${fmtTime(b)}`)}></i>`;
  }).join('');
}

const FOG_MODES = ['off', 'spy', 'standard'];
const FOG_NAMES = { off: 'No fog', spy: 'Spy fog', standard: 'Fog' };

function fogLabel() {
  const who = S.perspective ? playerName(S.perspective) : t('Gaia (all players)');
  return `${t(FOG_NAMES[S.fogMode] || 'Fog')}${S.combinedFog ? ` (${t('team')})` : ''} · ${who} · ${t(S.minimapMode)}`;
}

export function seek(time, force = false) {
  if (seekLocked() && !force) { toast(t('Seeking is disabled')); return; }
  S.seekVersion++;
  autocast.selection.focus = null; autocast.nextMove = 0;
  const from = S.jump && S.jump.wait ? S.jump.from : S.t;
  const target = Math.max(S.start, time);
  // A recording that is still loading can be jumped past its loaded end: the
  // jump then waits for the loader (the banner shows its progress).
  const wait = !!(S.session && S.session.mode === 'recording' && !S.complete && target > S.end + 1000);
  S.t = Math.min(S.end, target);
  S.jump = { from, to: wait ? target : S.t, at: performance.now(), wait };
  S.followLive = false;
  resetViews(true);
  speedMeter.t = null;
  // Seeking (e.g. "click to jump back") closes the end-game screen.
  if (overlays.isOpen('overlay-endgame')) overlays.closeAll();
}

// Read-ahead (settings.replayReadAhead): a replay the game plays for us runs at the
// game's fastest speed from the start with the light stream, and the view plays
// from that buffer at the chosen speed. By the time 4-8x is wanted the game is
// usually well ahead, so big late games need few or no buffering pauses. Live
// matches (and lobbies) are never sped up.
function readAhead() {
  const src = source();
  return isLive() && settings.replayReadAhead !== false && !!src.replay && !src.lobby;
}
let readAheadArmed = false;
function startReadAhead() {
  if (!readAheadArmed || !readAhead() || source().status !== 'playing') return;
  readAheadArmed = false;
  S.followLive = false; S.liveSpeedPicked = true;
  api('/api/control', { action: 'speed', value: 'EXTRA_FAST' }).catch(() => null);
  // The game shows its window again when the replay starts; a game window over the
  // browser makes it throttle Vantage to one frame a second.
  lastWindowState = null;
  if (document.hasFocus()) gameWindow('MINIMIZED');
}

function setSpeed(i) {
  S.speedIndex = Math.max(0, Math.min(SPEEDS.length - 1, i));
  S.playing = true;
  S.followLive = false;
  S.liveSpeedPicked = readAhead() || (isLive() && SPEEDS[S.speedIndex] !== 1);
  if (S.view) primeViews(S.view, viewEpoch);
  if (!readAhead()) liveControl('speed', SPEEDS[S.speedIndex]);
}

// Rewind / fast forward (the time bar's ⏪ ⏩): playback.js shuttleSpeed.
function shuttle(dir) {
  setSpeed(SPEEDS.indexOf(shuttleSpeed(SPEEDS[S.speedIndex], S.playing, dir)));
}

function togglePause() {
  if (S.highlight.seq && !S.highlight.seq.loading) { toggleSequencePause(); return; }
  // Play at the end of a finished match: watch it again from the start.
  if (!S.playing && isLive() && matchEnded(source()) && S.t >= S.end - 500) { seek(S.start); S.playing = true; return; }
  S.playing = !S.playing;
  if (!S.playing) S.followLive = false;
  if (!readAhead()) liveControl('pause', !S.playing); // reading ahead: the game keeps filling the buffer
}

// quiet: an automatic request (minimising the game) reports no error, as the
// game may simply not be connected yet. Resolves to whether the game agreed.
async function liveControl(action, value, quiet = false) {
  if (!isLive()) return false;
  let v = value;
  if (action === 'speed') {
    const sp = Math.abs(value);
    v = sp <= 0.5 ? 'SLOW' : sp <= 1 ? 'NORMAL' : sp <= 2 ? 'FAST' : 'EXTRA_FAST';
    if (value < 0) return false;
  }
  const r = await api('/api/control', { action, value: v }).catch(() => null);
  if (r && !r.ok && r.error && !quiet) toast(t(r.error));
  return !!(r && r.ok);
}

// -- live session controls ------------------------------------------------------------

let recOverride = null; // optimistic state until the server reports it
function recordingActive() {
  const src = source();
  if (src.recording_active != null) return !!src.recording_active;
  const server = !!src.recording && !src.recording_saved;
  if (recOverride != null && recOverride !== server) return recOverride;
  recOverride = null;
  return server;
}

async function toggleRecord() {
  const on = !recordingActive();
  const r = await api('/api/record', { on }).catch(() => null);
  if (!r || r.ok === false) { toast(t(r && r.error) || t('Recording is not available')); return; }
  recOverride = on;
  toast(on ? t('Recording started') : (r.path || r.saved ? t('Saved to {path}', { path: r.path || r.saved }) : t('Recording stopped')));
  renderHud();
}

async function stopWatching() {
  await api('/api/stop', {}).catch(() => null);
  S.highlight.seq = null;
  toast(t('Stopped watching'));
  afterOpen().catch(() => null);
  if (!overlays.isOpen('overlay-home')) ACTIONS.openHome();
}

// Auto-minimise the game while Vantage has focus (settings.autoMinimizeGame).
let lastWindowState = null;
function gameWindow(state) {
  if (!settings.autoMinimizeGame || !isLive() || lastWindowState === state) return;
  lastWindowState = state;
  // Not connected yet: forget the request so the next focus change retries it.
  liveControl('window', state, true).then((ok) => { if (!ok && lastWindowState === state) lastWindowState = null; });
}

// -- selection --------------------------------------------------------------------------

function onSelect(sel) {
  if (sel.perspective) { setPerspective(sel.perspective); return; }
  if (autocast.on || S.highlight.seq) autocast.selection.enabled = false;
  const ids = sel.rows.map((r) => r[0]);
  if (sel.ctrl) { for (const id of ids) { if (S.selection.has(id)) S.selection.delete(id); else S.selection.add(id); } }
  else if (sel.shift) ids.forEach((id) => S.selection.add(id));
  else S.selection = new Set(ids);
  if (sel.rows.length && !sel.ctrl) audio.selectionSound(sel.rows[0][2]);
  panels.rememberSelection();
  // A hidden selection panel looks like a broken click: say where it went, once.
  if (S.selection.size && !layout.isVisible('unitpanel') && !hiddenSelectionHinted) {
    hiddenSelectionHinted = true;
    toast(t('{p} hidden · ▣ Panels (Alt+V) brings it back', { p: t('Selection panel') }));
  }
  renderHud();
}
let hiddenSelectionHinted = false;

// Perspective 0 is Gaia: the whole map, no fog.
function setPerspective(pid) {
  S.perspective = pid;
  if (pid && S.fogMode === 'off') S.fogMode = 'standard';
  if (!pid) S.fogMode = 'off';
  toast(pid ? t('Perspective: {p}', { p: playerName(pid) }) : t('Perspective: Gaia (whole map)'));
  liveControl('perspective', pid);
}

function cycleFog() {
  const next = FOG_MODES[(FOG_MODES.indexOf(S.fogMode) + 1) % FOG_MODES.length];
  if (next !== 'off' && !S.perspective) {
    const p = selectionOwner() || (players()[0] && players()[0].id);
    if (!p) return;
    S.perspective = p;
    liveControl('perspective', p);
  }
  S.fogMode = next;
  liveControl('fog', next === 'standard');
  toast(`${t(FOG_NAMES[next])} · ${S.perspective ? playerName(S.perspective) : ''}`);
}

function cycleMinimap() {
  const modes = ['standard', 'military', 'resource'];
  S.minimapMode = modes[(modes.indexOf(S.minimapMode) + 1) % modes.length];
}

const goIndex = {};

function gotoNext(filter, key) {
  const rows = world.currentRows().filter(filter);
  if (!rows.length) { toast(t('None')); return; }
  goIndex[key] = ((goIndex[key] ?? -1) + 1) % rows.length;
  const r = rows[goIndex[key]];
  world.centerOn(r[3], r[4]);
  S.selection = new Set([r[0]]);
}

function selectionOwner() {
  const owners = new Set(world.currentRows().filter((r) => S.selection.has(r[0])).map((r) => r[1]));
  return owners.size === 1 ? [...owners][0] : null;
}

// Krepost (1251) has its own go-to (Ctrl+T); the shared table
// in games.js lists it with castles, so split it here.
const KREPOST = [1251];
const GOTO_ACTIONS = ['gotoTownCenter', 'gotoBarracks', 'gotoArcheryRange', 'gotoStable', 'gotoSiegeWorkshop', 'gotoCastle',
  'gotoKrepost', 'gotoMonastery', 'gotoMarket', 'gotoBlacksmith', 'gotoUniversity', 'gotoDock', 'gotoMill', 'gotoLumberCamp'];

function buildingMasters(action) {
  if (action === 'gotoKrepost') return GOTO_BUILDINGS.gotoKrepost || (GOTO_BUILDINGS.gotoCastle || []).filter((m) => KREPOST.includes(m));
  const list = GOTO_BUILDINGS[action] || [];
  return action === 'gotoCastle' && !GOTO_BUILDINGS.gotoKrepost ? list.filter((m) => !KREPOST.includes(m)) : list;
}

// Select every building of a type: the perspective player's, else the
// selection owner's, else everyone's.
function selectAllOf(action) {
  const masters = buildingMasters(action);
  const owner = S.perspective || selectionOwner();
  const rows = world.currentRows().filter((r) => masters.includes(r[2]) && r[1] > 0 && (!owner || r[1] === owner));
  if (!rows.length) { toast(t('None')); return; }
  S.selection = new Set(rows.map((r) => r[0]));
  panels.rememberSelection();
  toast(t('{n} selected', { n: rows.length }));
}

// -- Autocast: an automatic camera director ---------------------------------------------
// Two parts. The director (Alt+A) follows the fight: the camera moves to the
// densest recent kills, and units that rack up kills become "heroes" whose
// streaks are announced. The highlight sequence ("Kills by entity") replays one
// entity's story: its birth, its kills (kills under 10 s apart merged into a
// killing spree) and its death, each element
// from t − 5 s to t + 2 s with the camera following the killer, then the victim
// from 1 s before each kill, zooming in and slowing down as the moment comes.
// Entry points: the end-game "Most kills" commendation's "Show all" (event
// 'vantage:autocast' {unitId}) and the hero list (Alt+Shift+A).

const autocast = { on: false, nextMove: 0, nextBook: 0, announced: new Set(), selection: new FightSelection() };
const HERO_KILLS = 3;
const SPREE_GAP_MS = 10000;           // consecutive kills closer than this form one spree
const EL_LEAD_MS = 5000, EL_TAIL_MS = 2000;
const VICTIM_LEAD_MS = 1000;          // the camera switches to the victim 1 s before a kill
const ZOOM_LEVEL_TO = 6;              // zoom level 0 -> 6 over [t − 5 s, t]
const SPEED_FROM = 1.7, SPEED_TO = 0.5; // game speed (game s per real s) eased into each moment

// Kill events grouped by killer entity, up to a time. Every hero carries its
// death event (`fellEv`) when it died.
// The kill events of S.events, kept in step as the log grows (it only appends;
// a new game replaces the array): killers() runs four times a second and
// scanned the whole log twice each time.
const killLog = { events: null, seen: 0, kills: [] };
function killEvents() {
  if (killLog.events !== S.events || killLog.seen > S.events.length) { killLog.events = S.events; killLog.seen = 0; killLog.kills = []; }
  for (; killLog.seen < S.events.length; killLog.seen++) {
    const e = S.events[killLog.seen];
    if (e.kind === 'kill') killLog.kills.push(e);
  }
  return killLog.kills;
}

function killers(upTo = S.t) {
  const by = new Map();
  const kills = killEvents();
  const end = upTo === Infinity ? kills.length : eventIndexAfter(kills, upTo);
  for (let i = 0; i < end; i++) {
    const e = kills[i];
    if (e.friendly || !e.killer || e.killer.id == null) continue;
    let h = by.get(e.killer.id);
    if (!h) by.set(e.killer.id, (h = { id: e.killer.id, mid: e.killer.master, owner: e.killer.owner, kills: [], victims: new Map(), fell: null, fellEv: null }));
    h.kills.push(e);
    const vm = e.victim && e.victim.master;
    if (vm != null) h.victims.set(vm, (h.victims.get(vm) || 0) + 1);
  }
  for (let i = 0; i < end; i++) {
    const e = kills[i];
    if (e.victim && by.has(e.victim.id)) { const h = by.get(e.victim.id); h.fell = e.t; h.fellEv = e; }
  }
  return by;
}

function heroes(upTo = S.t) {
  return [...killers(upTo).values()].filter((h) => h.kills.length >= HERO_KILLS).sort((a, b) => b.kills.length - a.kills.length);
}

// The entity with the most kills in the whole game (the "Most kills"
// commendation and its "Kills by entity" sequence).
function topKiller() {
  let best = null;
  for (const h of killers(Infinity).values()) if (!best || h.kills.length > best.kills.length) best = h;
  return best && { id: best.id, master: best.mid, owner: best.owner, kills: best.kills.length };
}

// The unit type a hero killed most.
function mostKilled(h) {
  let mid = null, n = 0;
  for (const [m, c] of h.victims) if (c > n) { mid = m; n = c; }
  return mid == null ? null : { mid, n };
}

function mostKilledTag(h) {
  const m = mostKilled(h);
  return m ? t('Most killed: {u} ×{n}', { u: unitInfo(m.mid).name, n: m.n }) : '';
}

function autocastTick(now, dt) {
  runSequence(dt);
  if (!autocast.on || !S.view || S.highlight.seq) return;
  autocast.selection.observe(S.selection);
  if (now >= autocast.nextBook) {
    autocast.nextBook = now + 250;
    bookkeepHeroes();
  }
  if (now < autocast.nextMove) return;
  const best = chooseFight(S.events, S.t);
  // Nothing to watch: look again in half a second, not every frame.
  if (!best) { autocast.nextMove = now + 500; return; }
  autocast.nextMove = now + 4000;
  const info = autocast.selection.select(best, S.events, S.view.entities || [], S.t);
  if (info) {
    S.selection = new Set(info.keys());
    for (const [id, identity] of info) S.selectionInfo.set(id, identity);
    S.followSelection = false;
  }
  world.centerOn(best.x, best.y, Math.max(S.camera.zoom, 1.3));
}

// Hero announcements (settings.autocastHighlights): born, sprees, falls. A
// fallen hero's story is replayed automatically when seeking is possible.
function bookkeepHeroes() {
  if (!settings.autocastHighlights) return;
  const all = heroes(S.t);
  for (const h of all) {
    const last = h.kills[h.kills.length - 1].t;
    for (const n of [3, 5, 10, 20]) {
      const key = `${h.id}:${n}`;
      if (h.kills.length >= n && !autocast.announced.has(key)) {
        autocast.announced.add(key);
        if (S.t - last >= 5000) continue; // old news (autocast switched on late, or a seek)
        const tag = mostKilledTag(h);
        banner(n === 3 ? t('Our hero is born: {u}', { u: heroName(h) }) : t('Killing spree! {u} — kill {n}', { u: heroName(h), n: h.kills.length }), tag);
      }
    }
  }
  for (const h of all) {
    if (h.fell == null || h.kills.length < 5) continue;
    const key = `fall${h.id}`;
    if (autocast.announced.has(key)) continue;
    autocast.announced.add(key);
    if (S.t - h.fell >= 5000) continue;
    banner(t('Our hero falls! {u} ({n} kills)', { u: heroName(h), n: h.kills.length }), mostKilledTag(h));
    if (!seekLocked()) setTimeout(() => { if (autocast.on && !S.highlight.seq) startSequence(h, true); }, 2500);
  }
}

function heroName(h) {
  const nick = settings.entityNames[h.id];
  return `${nick || unitInfo(h.mid, h.owner).name} · ${playerName(h.owner)}`;
}

// "<unit> <id>" as the sequence caption shows it.
function heroLabel(h) {
  const nick = settings.entityNames[h.id];
  const name = unitInfo(h.mid, h.owner).name;
  return nick ? `${nick} (${name} ${h.id})` : `${name} ${h.id}`;
}

let bannerTimer = null;
function banner(text, sub = '') {
  const el = $('autocast-banner');
  patchHtml(el, `${esc(text)}${sub ? `<div class="ac-sub">${esc(sub)}</div>` : ''}`);
  el.classList.remove('hidden');
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

// -- the highlight sequence -----------------------------------------------------------

// When the entity first appeared: /api/unit's `born` when the server knows it,
// else a binary search of the keyframes for its first appearance. null when it
// was there from the start (starting units) or cannot be found.
async function bornTime(h) {
  const seen = h.kills.length ? h.kills[0].t : h.fell != null ? h.fell - 1 : S.t;
  const u = await api(`/api/unit/${h.id}?t=${Math.round(seen)}`).catch(() => null);
  if (u && Number.isFinite(u.born)) return u.born > S.start ? u.born : null;
  const exists = async (at) => {
    const v = await api(`/api/view?t=${Math.round(at)}`).catch(() => null);
    return !!(v && Array.isArray(v.entities) && v.entities.some((r) => r[0] === h.id));
  };
  let lo = S.start, hi = seen;
  if (hi - lo < 1000 || !(await exists(hi)) || (await exists(lo))) return null;
  for (let i = 0; i < 24 && hi - lo > 1000; i++) {
    const mid = (lo + hi) / 2;
    if (await exists(mid)) hi = mid; else lo = mid;
  }
  return Math.round(hi);
}

// Birth, kills (grouped into sprees), death. Each element plays [t − 5 s, end + 2 s].
function buildElements(h, born) {
  const els = [];
  const N = h.kills.length;
  if (born != null) {
    const tr = S.events.filter((e) => e.kind === 'trained' && e.master === h.mid && e.player === h.owner && e.x != null && Math.abs(e.t - born) < 4000)
      .sort((a, b) => Math.abs(a.t - born) - Math.abs(b.t - born))[0];
    els.push({ kind: 'birth', t: born, last: born, kills: [], x: tr ? tr.x : null, y: tr ? tr.y : null });
  }
  const kills = [...h.kills].sort((a, b) => a.t - b.t);
  let i = 0;
  while (i < kills.length) {
    let j = i;
    while (j + 1 < kills.length && kills[j + 1].t - kills[j].t < SPREE_GAP_MS) j++;
    const group = kills.slice(i, j + 1);
    els.push({ kind: group.length > 1 ? 'spree' : 'kill', t: group[0].t, last: group[group.length - 1].t, kills: group, a: i + 1, b: j + 1, N, x: group[0].x, y: group[0].y });
    i = j + 1;
  }
  if (h.fellEv) els.push({ kind: 'death', t: h.fellEv.t, last: h.fellEv.t, kills: [], killer: h.fellEv.killer, x: h.fellEv.x, y: h.fellEv.y });
  for (const el of els) { el.start = el.t - EL_LEAD_MS; el.end = el.last + EL_TAIL_MS; }
  return els;
}

function elementTag(el) {
  if (!el) return t('None');
  if (el.kind === 'birth') return t('Our hero is born');
  if (el.kind === 'death') return t('Our hero falls!');
  if (el.kind === 'spree') return t('Killing spree! Kills {a} – {b} of {N}', { a: el.a, b: el.b, N: el.N });
  return t('Kill {n} of {N}', { n: el.a, N: el.N });
}

async function startSequence(hero, auto = false) {
  if (seekLocked()) { toast(t('Seeking is disabled')); return; }
  if (!hero || (!hero.kills.length && !hero.fellEv)) { toast(t('No kills recorded for this unit')); return; }
  const prev = S.highlight.seq;
  const back = prev ? prev.back : { t: S.t, live: isLive() && S.followLive, speedIndex: S.speedIndex, playing: S.playing, follow: S.followSelection };
  const q = { hero, els: [], idx: -1, paused: false, done: false, loading: true, rate: null, back, auto, cam: null };
  S.highlight.seq = q;
  if (!auto) autocast.selection.resume(S.selection);
  S.highlight.list = false;
  S.followSelection = false;
  renderHud();
  const born = await bornTime(hero).catch(() => null);
  if (S.highlight.seq !== q) return; // stopped or replaced while looking up the birth
  q.els = buildElements(hero, born);
  q.loading = false;
  playElement(0);
}

function playElement(i) {
  const q = S.highlight.seq;
  if (!q || !q.els.length) return;
  q.idx = Math.max(0, Math.min(q.els.length - 1, i));
  const el = q.els[q.idx];
  q.paused = false; q.done = false; q.cam = null; q.selectionReady = false;
  seek(el.start, true);
  S.playing = true;
  if (autocast.selection.enabled) {
    S.selection = new Set([q.hero.id]);
    S.selectionInfo.set(q.hero.id, { mid: q.hero.mid, owner: q.hero.owner });
    autocast.selection.owned = new Set(S.selection);
  }
  panels.rememberSelection();
  banner(elementTag(el), `${heroLabel(q.hero)} · ${t('Total kills: {n}', { n: q.hero.kills.length })}`);
  renderHud();
}

const ease = (k) => { const x = Math.max(0, Math.min(1, k)); return x * x * (3 - 2 * x); };
const lerp = (a, b, k) => a + (b - a) * k;

// Autocast zoom level (0 = default, + = closer) on Vantage's scale: the
// presets 2 (level 0) and 1 (level 4) anchor it.
function zoomForLevel(level) {
  const zl = settings.zoomLevels || {};
  const z0 = Number(zl.two) || 1, z4 = Number(zl.one) || 1.6;
  return z0 * Math.pow(Math.max(1.05, z4 / z0), level / 4);
}

// Game speed during an element: eased from 1.7 to 0.5 over the second (two
// seconds for kills) before each moment; inside a spree it recovers between
// kills that are more than a second apart.
function sequenceSpeed(el, at) {
  const lead = el.kind === 'kill' || el.kind === 'spree' ? 2000 : 1000;
  const moments = el.kills.length ? el.kills.map((k) => k.t) : [el.t];
  let speed = SPEED_FROM;
  moments.forEach((m, n) => {
    let s;
    if (at < m - lead) s = SPEED_FROM;
    else if (at <= m) s = lerp(SPEED_FROM, SPEED_TO, ease((at - (m - lead)) / lead));
    else if (n === moments.length - 1) s = SPEED_TO;
    else s = lerp(SPEED_TO, SPEED_FROM, ease((at - m - 1000) / 1000));
    speed = Math.min(speed, s);
  });
  return speed;
}

// Who the camera follows: the killer until 1 s before each kill, then the victim.
function sequenceTarget(q, el, at) {
  if (el.kind === 'birth' || el.kind === 'death') return { id: q.hero.id, x: el.x, y: el.y };
  const k = el.kills.find((x) => x.t + 400 >= at) || el.kills[el.kills.length - 1];
  if (at >= k.t - VICTIM_LEAD_MS && k.victim) return { id: k.victim.id, x: k.x, y: k.y };
  return { id: q.hero.id, x: k.x, y: k.y };
}

function runSequence(dt) {
  const q = S.highlight.seq;
  if (!q || q.loading || q.idx < 0) return;
  const el = q.els[q.idx];
  autocast.selection.observe(S.selection);
  if (q.paused || q.done) { q.rate = null; return; }
  if (S.t >= Math.min(el.end, S.end)) {
    if (q.idx + 1 < q.els.length) { playElement(q.idx + 1); return; }
    // After the last element the game pauses.
    q.done = true; q.rate = null; S.playing = false;
    renderHud();
    return;
  }
  q.rate = sequenceSpeed(el, S.t);
  if (!S.view) return; // still jumping: hold the camera
  const tgt = sequenceTarget(q, el, S.t);
  const row = (S.view.entities || []).find((r) => r[0] === tgt.id);
  let x = row ? row[3] : tgt.x, y = row ? row[4] : tgt.y;
  if (x == null && q.cam) { x = q.cam.x; y = q.cam.y; }
  if (x == null) return;
  if (autocast.selection.enabled && !q.selectionReady) {
    const info = highlightParticipants(q.hero, el, { x, y }, S.events, S.view.entities || [], S.t);
    S.selection = new Set(info.keys());
    for (const [id, identity] of info) S.selectionInfo.set(id, identity);
    autocast.selection.owned = new Set(S.selection);
    q.selectionReady = true;
  }
  const zoom = zoomForLevel(ZOOM_LEVEL_TO * ease((S.t - el.start) / (el.t - el.start || 1)));
  if (!q.cam || (q.cam.x - x) ** 2 + (q.cam.y - y) ** 2 > 30 * 30) q.cam = { x, y };
  else {
    const k = Math.min(1, dt * 5);
    q.cam = { x: q.cam.x + (x - q.cam.x) * k, y: q.cam.y + (y - q.cam.y) * k };
  }
  world.setCamera(q.cam.x, q.cam.y, zoom);
}

// Pausing remembers the world time; resuming jumps back there and goes on.
function toggleSequencePause() {
  const q = S.highlight.seq;
  if (!q) return;
  if (q.done) { // resume after the last element: carry on watching from here
    S.highlight.seq = null; S.playing = true; S.followSelection = q.back.follow;
    return;
  }
  if (!q.paused) { q.paused = true; q.pausedAt = S.t; S.playing = false; q.rate = null; return; }
  q.paused = false;
  if (q.pausedAt != null && Math.abs(S.t - q.pausedAt) > 50) seek(q.pausedAt, true);
  S.playing = true;
}

// Stop the sequence and go back to where it started (or to the live edge).
function endSequence() {
  const q = S.highlight.seq;
  if (!q) return;
  S.highlight.seq = null;
  S.speedIndex = q.back.speedIndex;
  S.followSelection = q.back.follow;
  if (q.back.live) { S.followLive = true; resetViews(); }
  else seek(q.back.t, true);
  S.playing = q.back.playing;
  renderHud();
}

// The end-game "Most kills → Show all" (overlays.js) starts the sequence for one entity.
function autocastEntity(unitId) {
  const id = Number(unitId);
  if (!Number.isFinite(id)) return;
  const h = killers(Infinity).get(id);
  if (!h) { toast(t('No kills recorded for this unit')); return; }
  if (overlays.isOpen('overlay-endgame')) overlays.closeAll();
  endgameShown = true;
  startSequence(h);
}

let hlBarKey = '', hlListKey = '';
function renderHighlights() {
  const bar = $('highlight-bar'), list = $('highlight-list');
  const q = S.highlight.seq;
  const showBar = autocast.on || !!q;
  bar.classList.toggle('hidden', !showBar);
  if (showBar) {
    const key = `${autocast.on}|${autocast.selection.enabled}|${q ? `${q.hero.id}:${q.idx}:${q.paused}:${q.done}:${q.loading}` : ''}|${S.highlight.list}|${language}`;
    if (key !== hlBarKey) {
      hlBarKey = key;
      patchHtml(bar, q ? sequenceBar(q) : `<span class="hl-label">${t('Autocast')}</span>
        ${fightSelectButton()}
        <button data-hl="all" class="${S.highlight.list ? 'on' : ''}" ${tip(t('Show all'), t('Every hero so far, with their kills'))}>${t('Show all')}</button>`);
    }
  } else hlBarKey = '';
  list.classList.toggle('hidden', !S.highlight.list);
  if (!S.highlight.list) { hlListKey = ''; return; }
  const hs = heroes(S.t);
  const key = `${hs.map((h) => `${h.id}:${h.kills.length}:${h.fell}`).join(',')}|${language}`;
  if (key === hlListKey) return;
  hlListKey = key;
  patchHtml(list, `<h3>${t('Heroes')} <span class="hint">${t('units with {n}+ kills — click to replay their story', { n: HERO_KILLS })}</span></h3>
    ${hs.length ? hs.map((h) => `<div class="hl-row" data-hero="${h.id}" ${tip(heroName(h), t('Replay its birth, kills and death'))}>
      ${unitIcon(h.mid) ? `<img src="${unitIcon(h.mid)}" alt="">` : ''}
      <div><div style="color:${playerColor(h.owner)};font-weight:600">${esc(heroName(h))}${h.fell != null ? ` <span class="hl-tag">✝ ${fmtTime(h.fell)}</span>` : ''}</div>
      <div class="hl-tag">${esc(mostKilledTag(h))}</div></div>
      <span class="hl-kills">${t('{n} kills', { n: h.kills.length })}</span></div>`).join('') : `<div class="hint">${t('No heroes yet.')}</div>`}`);
}

// The autocasting control bar: title, pause/resume, "Kills by entity <icon>",
// Previous / Current / Next element buttons (labelled with the element, or
// "None"), stop and the hero list.
function fightSelectButton() {
  return `<button data-hl="selection" aria-pressed="${autocast.selection.enabled}" class="${autocast.selection.enabled ? 'on' : ''}" ${tip(t('Select fight'), t('Select recent attackers and targets plus nearby fighting or healing units. Click a unit yourself to hold its details; click here to resume automatic selection.'))}>${t('Select fight')}</button>`;
}

function sequenceBar(q) {
  const h = q.hero;
  const icon = unitIcon(h.mid);
  const el = (i) => (i >= 0 && i < q.els.length ? q.els[i] : null);
  const navBtn = (name, i, label, help) => `<button data-hl="${name}" class="hl-nav${name === 'cur' ? ' on' : ''}" ${el(i) ? '' : 'disabled'} ${tip(label, help)}><small>${label}</small>${esc(elementTag(el(i)))}</button>`;
  const pauseLabel = q.paused || q.done ? t('Resume') : t('Pause');
  return `<div class="hl-row1">
      <span class="hl-label">${t('Autocasting')}</span>
      ${fightSelectButton()}
      <button data-hl="pause" ${q.loading ? 'disabled' : ''} ${tip(pauseLabel, t('Pause or resume the sequence; resuming returns to the paused moment'))}>${q.paused || q.done ? '▶' : '⏸'} ${pauseLabel}</button>
      <span class="hl-kbe" style="color:${playerColor(h.owner)}">${t('Kills by entity')}${icon ? ` <img src="${icon}" alt="">` : ''}</span>
      ${q.loading ? `<span class="hl-tag">${t('Preparing…')}</span>` : `${navBtn('prev', q.idx - 1, t('Previous'), t('Jump to the previous moment'))}
      ${navBtn('cur', q.idx, t('Current'), t('Replay the current moment'))}
      ${navBtn('next', q.idx + 1, t('Next'), t('Jump to the next moment'))}`}
      <button data-hl="stop" ${tip(t('Stop'), t('End the sequence and go back'))}>■</button>
      <button data-hl="all" class="${S.highlight.list ? 'on' : ''}" ${tip(t('Show all'), t('Every hero so far, with their kills'))}>${t('Show all')}</button>
    </div>
    <div class="hl-row2"><span class="hl-caption">${esc(heroLabel(h))}</span>
      <span class="hl-tag">${t('Total kills: {n}', { n: h.kills.length })}</span>
      ${q.done ? `<span class="hl-tag">${t('End of sequence')}</span>` : ''}
      <span class="hl-tag">${esc(mostKilledTag(h))}</span></div>`;
}

// -- first-run tutorial -------------------------------------------------------------------

const TUTORIAL = [
  ['Welcome to Vantage', 'A spectator for AoE2 DE. Press ? any time for the quick reference, Esc for the menu.'],
  ['Moving the camera', 'Right-drag or middle-drag to pan, wheel to zoom at the cursor, arrows or edge scroll. Click the minimap to jump.'],
  ['Selecting', 'Click, drag a box, or double-click to select every unit of that type on screen. Space centres on the selection. The panel bottom-right shows stats, kills and activity.'],
  ['Team overview & dashboard', 'Top-left: each player\'s bank, workers, age progress. Bottom: the dashboard — Alt+C / Alt+X cycles pages.'],
  ['Time controls', 'F3 pauses, [ and ] change speed (below pause plays backwards), - and = skip 30s, F4 bookmarks. Click the bar to seek.'],
  ['Statistics', 'Ctrl+Alt+S opens charts and tables. Right-click a chart to jump to that moment.'],
];
// Shown the first time a Return of Rome game is watched.
const ROR_TUTORIAL = [
  ['Return of Rome', 'This is a Return of Rome game: Stone, Tool, Bronze and Iron Ages, with names, icons and graphics from the game\'s Return of Rome data.'],
  ['Ages and techs', 'The overview shows each player\'s progress to the next age: food (and gold for the Iron Age) and the two qualifying buildings. The tech row follows Return of Rome\'s storage pit, market, government center and temple upgrades.'],
  ['Dashboard', 'Return of Rome has three dashboard pages: overview, worker efficiency and APM. Alt+C / Alt+X cycles them.'],
];
let tutorialSkip = null;
function showTutorial(i, steps = TUTORIAL, seenKey = 'seenTutorial') {
  const el = $('overlay-help');
  tutorialSkip = () => showTutorial(steps.length, steps, seenKey);
  if (i >= steps.length) {
    tutorialSkip = null;
    el.classList.remove('tutorial-card');
    overlays.closeAll(); settings[seenKey] = true; saveSettings();
    if (steps === TUTORIAL && S.game === 'ror' && !settings.seenRorTutorial) showTutorial(0, ROR_TUTORIAL, 'seenRorTutorial');
    return;
  }
  if (!overlays.isOpen('overlay-help')) overlays.toggle('overlay-help', () => {});
  el.classList.add('tutorial-card'); // a compact card, not the full-screen help panel
  el.innerHTML = `<h2>${t(steps[i][0])}</h2><p style="font-size:15px;max-width:640px">${t(steps[i][1])}</p>
    <div class="form-row"><button id="tut-next" class="on">${i + 1 < steps.length ? t('Next') : t('Done')}</button><button id="tut-skip">${t('Skip tutorial')}</button><span class="hint">${i + 1} / ${steps.length}</span></div>`;
  $('tut-next').onclick = () => showTutorial(i + 1, steps, seenKey);
  $('tut-skip').onclick = () => showTutorial(steps.length, steps, seenKey);
}

// -- documentation page ----------------------------------------------------------------------
// {k:action} placeholders show the action's current key binding.

const DOCS = [
  ['Getting started', [
    'Vantage shows a running AoE II DE game, a replay played by the game, or a saved recording (.vrec) without the game. Open the home screen with {k:openHome} or the ⌂ button: Recordings play instantly; Replays are loaded by the game and streamed; Live connects to the game you are watching.',
    'Press Esc to close the top-most window; with nothing open, Esc opens the menu (the ⛨ shield button). The quick reference ({k:openHelp}) lists every key; the tutorial is in the menu ({k:showTutorial}).',
  ]],
  ['Camera', [
    'Right-drag or middle-drag pans, the wheel zooms at the cursor, the arrow keys and (if enabled) the screen edges scroll. Click or drag on the minimap to move there.',
    'Zoom presets: {k:setZoomLevelOne}, {k:setZoomLevelTwo}, {k:setZoomLevelThree}; save the current zoom into a preset with {k:updateZoomLevelOne} (and 2, 3). {k:toggleCursorClip} locks the mouse inside the window for edge scrolling; the "lock cursor" setting re-locks it on your first click.',
  ]],
  ['Selecting and following', [
    'Click selects, drag selects a box, double-click selects every unit of that type on screen; Shift adds, Ctrl toggles. {k:focusSelection} centres on the selection, {k:followSelection} follows it, {k:unFollowSelection} stops.',
    'Go to the next building of a type with Ctrl+key (barracks {k:gotoBarracks}, town centre {k:gotoTownCenter}, krepost {k:gotoKrepost} …) and select all of them with Ctrl+Shift+key ({k:selectAllBarracks}, {k:selectAllTownCenter} …). Idle villagers: {k:gotoIdleVillager}; idle military: {k:gotoIdleMilitary}; king: {k:gotoKing}. Control groups: Ctrl+0–9 to set, 0–9 to recall.',
  ]],
  ['Fog of war and perspective', [
    'Fog modes cycle with {k:cycleFogOfWar} or by clicking or right-clicking the ◐ icon: Off (everything), Spy (all units drawn, terrain shaded by what the player has explored) and Standard (only what the player can see). {k:toggleFogOfWar} switches fog on and off; {k:toggleCombinedFogOfWar} or a middle-click on the icon combines the vision of a whole team.',
    'Watch through a player\'s eyes with Ctrl+Shift+F1–F8; {k:setPlayer0} switches to Gaia, which sees the whole map. {k:setPerspectiveForSelected} or Shift+right-click on a unit takes the perspective of its owner. Hold Tab to peek at the selection owner\'s fog. In a live game, perspective and fog are sent to the game too.',
  ]],
  ['Time controls', [
    'The bar above the minimap ({k:toggleScrubbingBar} shows or hides it): {k:pause} pauses, {k:speedStepUp} and {k:speedStepDown} change speed (below pause, playback runs backwards), {k:skipBack} and {k:skipForward} skip 30 seconds, {k:jumpStart} and {k:jumpLive} jump to the start and to the live edge.',
    'Hover the bar to see the time under the pointer; click or drag to jump there. Hatched red marks show where the stream skipped. The "real" readout is the measured playback speed; it turns orange when it falls behind the target (a slow machine or a lagging game).',
    'Bookmarks: {k:bookmark} bookmarks the moment 30 seconds ago, right-click the bar to add or remove one, and step through them with {k:bookmarkPrev} / {k:bookmarkNext} or the ◂⚑ ⚑▸ buttons. Bookmarks are saved per game.',
    'Settings can lock seeking and hide the bar (useful on stream).',
  ]],
  ['Panels', [
    'Top: the scoreboard and team overview ({k:toggleOverview}). Left: static techs ({k:toggleStaticTechnologies}) and production ({k:toggleProduction}); slide-outs with every technology ({k:toggleSlideoutStaticTechs}) and a graph ({k:toggleSlideoutGraph}). Bottom: the dashboard, cycled with {k:cycleDashboardForward} / {k:cycleDashboardBackward}. Right: the event log (Page Up / Page Down to scroll) and the unit panel.',
    '{k:toggleResourcesLeft} shows the resources left on the map; {k:togglePlayerResources} shows per-player rows. {k:swapScoreboardTeamSides} flips the team sides.',
  ]],
  ['Colours and display', [
    '{k:cycleColorMode} switches between game colours and team colours; {k:cycleBaseColorMode} cycles the colour scheme: game colours, cold/warm (one team in cool hues, the other in warm) and warm/cold. Click a player name to cycle that player\'s colour.',
    '{k:toggleOverlayDisplay} hides the interface for a clean feed ({k:toggleMinimapDisplayWhenNoOverlay} keeps the minimap); {k:toggleRangeCircles} shows range circles; {k:showGameSpeedAndFps} shows the frame rate and the real versus target speed; {k:toggleFullScreen} toggles full screen.',
  ]],
  ['Statistics and the end of the game', [
    '{k:showAchievements} opens the statistics: charts (right-click a chart to jump to that moment) and tables, with CSV/JSON export. When the game ends — in a recording and while watching live — the end-game screen shows the winner and each player\'s performance.',
  ]],
  ['Autocast', [
    '{k:toggleAutocast} turns on the automatic camera director: it moves to the biggest fights and announces heroes — units with several kills. {k:showHighlights} or "Show all" lists every hero.',
    'Click a hero, or "Show all" on the end-game "Most kills" commendation, to replay its story: its birth, every kill (kills less than 10 seconds apart form a killing spree) and its death. Each moment starts 5 seconds before and ends 2 seconds after; the camera follows the killer, then the victim from a second before each kill, zooming in and slowing down as the moment comes. The bar\'s Previous / Current / Next buttons jump between moments; Pause remembers the moment and Resume returns to it. The game pauses after the last moment; ■ stops and goes back to where you were. With highlights enabled in the settings, a fallen hero\'s story is replayed automatically.',
  ]],
  ['Live games', [
    'While connecting, the screen shows the launch status (connecting, joining a spectator lobby, loading a replay, ready — with the map and the number of players) and the spectator delay. "Start Age II" (on that card, or in the ⛨ menu) starts the game through Steam and follows it until Vantage is connected. The ● REC button records the live session to a .vrec file; ■ stops watching. With "minimise the game" enabled, the game window minimises while Vantage has focus and comes back when you switch away.',
    'Live games and replays go through the running game, which accepts only a spectator app holding its client certificate. Vantage cannot ship it: the home screen says which files are missing and where they go, and the Live-games page of the Vantage wiki has the details. Recordings (.vrec) play without them.',
  ]],
  ['Casting and streaming', [
    'The casting settings set player and team names, captains, flags or pictures, main and secondary text, the series and the stage. Open Vantage with ?overlay=1 for a transparent HUD-only page to use as an OBS browser source. Tooltips can show names only, or be switched off for streams.',
  ]],
  ['Hotkeys', [
    'Every key can be changed in Settings → Hotkeys as JSON: map an action to one key ("gotoKrepost": "Ctrl+Shift+K"), to several (["F11", "Alt+Enter"]) or to none (""). Vantage warns when two actions share a key; the first one listed keeps it.',
  ]],
];

function renderDocs() {
  const el = $('overlay-docs');
  const fill = (text) => esc(t(text)).replace(/\{k:(\w+)\}/g, (_, a) => `<kbd>${esc(keyLabel(binding(a)))}</kbd>`);
  el.innerHTML = `<button class="close" data-close>${t('✕ Esc')}</button><h2>${t('Documentation')}</h2>
    <div class="docs"><nav class="docs-nav">${DOCS.map(([h], i) => `<a data-doc="${i}">${t(h)}</a>`).join('')}</nav>
    <div class="docs-body">${DOCS.map(([h, ps], i) => `<section id="doc-${i}"><h3>${t(h)}</h3>${ps.map((p) => `<p>${fill(p)}</p>`).join('')}</section>`).join('')}</div></div>`;
  el.querySelector('[data-close]').onclick = () => overlays.closeAll();
  el.querySelectorAll('[data-doc]').forEach((a) => { a.onclick = () => $(`doc-${a.dataset.doc}`).scrollIntoView({ behavior: 'smooth', block: 'start' }); });
}

function openDocs() {
  if (!overlays.isOpen('overlay-docs')) overlays.toggle('overlay-docs', renderDocs);
}

// -- shield ("omni") menu ---------------------------------------------------------------------

const OMNI = [
  ['Home', 'openHome'], ['Statistics', 'showAchievements'], ['Settings', 'openSettings'],
  ['Panels', 'togglePanelsMenu'], ['Quick reference', 'openHelp'], ['Documentation', 'openDocs'], ['Tutorial', 'showTutorial'],
  ['Full screen', 'toggleFullScreen'],
];

function omniOpen() { return !$('omni-menu').classList.contains('hidden'); }
function closeOmni() { $('omni-menu').classList.add('hidden'); }
function toggleOmni() {
  const el = $('omni-menu');
  if (omniOpen()) { closeOmni(); return; }
  const items = [...OMNI];
  if (isLive()) items.push(['Stop watching', 'stopWatching']);
  if (!(serverConfig && serverConfig.native_replays) && !(S.session && S.session.live_connected)) items.push(['Start Age II', 'startGame']);
  if (settings.toggleHTMLServer) items.push(['Open webpage', 'openHtmlServer']);
  el.innerHTML = `<div class="omni-title">Vantage</div>${items.map(([label, a]) => {
    const k = ['openSettings', 'stopWatching', 'startGame', 'openHtmlServer'].includes(a) ? '' : binding(a);
    return `<button data-omni="${a}"><span>${t(label)}</span>${k && k !== '—' ? `<kbd>${esc(keyLabel(k))}</kbd>` : ''}</button>`;
  }).join('')}`;
  const r = $('btn-menu').getBoundingClientRect();
  el.style.left = `${Math.max(8, r.left)}px`;
  el.style.bottom = `${Math.max(8, window.innerHeight - r.top + 4)}px`;
  el.style.top = 'auto';
  el.classList.remove('hidden');
  const first = el.querySelector('button');
  if (first) first.focus();
}

function openSettings() {
  overlays.toggle('overlay-settings', () => overlays.renderSettings(applySettings));
}

// Called by the settings page after it saves.
let lastConflicts = '';
function applySettings() {
  // Warn about hotkey conflicts once per change, not on every slider move.
  const conflicts = describeConflicts(rebuildKeys(), t).join('; ');
  if (conflicts && conflicts !== lastConflicts) toast(t('Hotkey conflict: {list}', { list: conflicts }));
  lastConflicts = conflicts;
  tooltipMode = null;
  renderHud();
}

// Esc: close the top-most layer; with nothing open, open the menu.
function escapeLayerOrOpenMenu() {
  if (omniOpen()) { closeOmni(); return; }
  if (layout.panelsMenuOpen()) { layout.closePanelsMenu(); return; }
  if (S.highlight.list) { S.highlight.list = false; return; }
  // Esc on the tutorial skips it (as its Skip button does), so it does not return on reload.
  if (tutorialSkip && $('overlay-help').classList.contains('tutorial-card') && overlays.isOpen('overlay-help')) { tutorialSkip(); return; }
  if (document.querySelector('.overlay:not(.hidden)')) { overlays.closeAll(); return; }
  if (!$('techtree').classList.contains('hidden')) { panels.hideTechTree(); return; }
  if (S.slideout) { S.slideout = null; return; }
  if (S.highlight.seq) { endSequence(); return; }
  if (S.selection.size) { S.selection = new Set(); panels.rememberSelection(); return; }
  toggleOmni();
}

// -- actions ------------------------------------------------------------------------------

const BASE_COLOR_MODES = ['default', 'coldWarm', 'warmCold'];
const BASE_COLOR_NAMES = { default: 'Game colours', coldWarm: 'Cold / warm colours', warmCold: 'Warm / cold colours' };

const ACTIONS = {
  toggleScrubbingBar: () => $('timebar').classList.toggle('compact'),
  pause: togglePause,
  playPause: togglePause,
  speedStepUp: () => setSpeed(S.speedIndex + 1),
  speedStepDown: () => setSpeed(S.speedIndex - 1),
  skipForward: () => seek(S.t + 30000),
  skipBack: () => seek(S.t - 30000),
  bookmark: () => addBookmark(S.t - 30000),
  bookmarkPrev: () => { const b = [...S.bookmarks].reverse().find((x) => x < S.t - 1000); if (b != null) seek(b); else toast(t('No earlier bookmark')); },
  bookmarkNext: () => { const b = S.bookmarks.find((x) => x > S.t + 1000); if (b != null) seek(b); else toast(t('No later bookmark')); },
  jumpLive: () => { if (isLive()) { S.followLive = true; S.liveSpeedPicked = false; } else seek(S.end); },
  jumpStart: () => seek(S.start),
  followSelection: () => { S.followSelection = true; toast(t('Following selection')); },
  unFollowSelection: () => { S.followSelection = false; toast(t('Stopped following')); },
  focusSelection: () => {
    const rows = world.selectedRows();
    if (rows.length) world.centerOn(rows.reduce((a, r) => a + r[3], 0) / rows.length, rows.reduce((a, r) => a + r[4], 0) / rows.length);
  },
  showAchievements: () => overlays.toggle('overlay-stats', () => overlays.renderStats(seek)),
  cycleDashboardForward: () => { S.dashPage++; renderHud(); },
  cycleDashboardBackward: () => { S.dashPage--; renderHud(); },
  swapScoreboardTeamSides: () => { S.flipSides = !S.flipSides; },
  toggleStaticTechnologies: () => { settings.showStaticTechs = !settings.showStaticTechs; saveSettings(); },
  toggleSlideoutStaticTechs: () => { S.slideout = S.slideout === 'techs' ? null : 'techs'; },
  toggleSlideoutGraph: () => { S.slideout = S.slideout === 'graph' ? null : 'graph'; },
  toggleProduction: () => { settings.showProduction = !settings.showProduction; saveSettings(); },
  toggleResourcesLeft: () => { showResLeft = !showResLeft; },
  togglePlayerResources: () => { toggleTeamBoardView(); },
  cycleFogOfWar: cycleFog,
  toggleFogOfWar: () => { S.fogMode = S.fogMode === 'off' ? 'standard' : 'off'; liveControl('fog', S.fogMode !== 'off'); },
  toggleCombinedFogOfWar: () => { S.combinedFog = !S.combinedFog; toast(t(S.combinedFog ? 'Combined team fog' : 'Single-player fog')); },
  setPerspectiveForSelected: () => { const o = selectionOwner(); if (o) setPerspective(o); },
  cycleMinimapMode: cycleMinimap,
  toggleRangeCircles: () => { S.rangeCircles = !S.rangeCircles; },
  cycleBaseColorMode: () => {
    const cur = BASE_COLOR_MODES.indexOf(settings.baseColorMode);
    settings.baseColorMode = BASE_COLOR_MODES[(cur + 1) % BASE_COLOR_MODES.length];
    saveSettings();
    toast(t(BASE_COLOR_NAMES[settings.baseColorMode]));
  },
  cycleColorMode: () => { S.colorMode = S.colorMode === 'game' ? 'team' : 'game'; },
  setZoomLevelOne: () => world.zoomTo(settings.zoomLevels.one),
  setZoomLevelTwo: () => world.zoomTo(settings.zoomLevels.two),
  setZoomLevelThree: () => world.zoomTo(settings.zoomLevels.three),
  updateZoomLevelOne: () => { settings.zoomLevels.one = S.camera.zoom; saveSettings(); toast(t('Zoom preset 1 saved')); },
  updateZoomLevelTwo: () => { settings.zoomLevels.two = S.camera.zoom; saveSettings(); toast(t('Zoom preset 2 saved')); },
  updateZoomLevelThree: () => { settings.zoomLevels.three = S.camera.zoom; saveSettings(); toast(t('Zoom preset 3 saved')); },
  toggleOverlayDisplay: () => document.body.classList.toggle('no-ui'),
  toggleMinimapDisplayWhenNoOverlay: () => document.body.classList.toggle('keep-minimap'),
  notificationsPageUp: () => panels.eventsPage(-1),
  notificationsPageDown: () => panels.eventsPage(1),
  notificationsTopPage: () => panels.eventsPage(-1, true),
  notificationsBottomPage: () => panels.eventsPage(1, true),
  toggleCrossThreadProfiling: () => { perf.on = !perf.on; $('perf-view').classList.toggle('hidden', !perf.on); },
  showGameSpeedAndFps: () => { S.showFps = !S.showFps; if (!S.showFps && S.session) $('status-line').textContent = statusText(S.session); },
  toggleFullScreen: () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => null); },
  openHome: () => overlays.toggle('overlay-home', () => overlays.renderHome(afterOpen)),
  openHelp: () => overlays.toggle('overlay-help', overlays.renderHelp),
  openDocs,
  openSettings,
  stopWatching,
  startGame,
  openHtmlServer,
  escape: escapeLayerOrOpenMenu,
  gotoIdleVillager: () => gotoNext((r) => r[1] > 0 && (r[6] & 8), 'idlev'),
  gotoIdleMilitary: () => gotoNext((r) => r[1] > 0 && (r[6] & 2), 'idlem'),
  gotoKing: () => gotoNext((r) => r[2] === 434, 'king'),
  toggleCursorClip: () => world.toggleCursorLock(),
  toggleOverview: () => layout.setVisible('overview', !layout.isVisible('overview')),
  togglePanelsMenu: () => layout.togglePanelsMenu(),
  arrangePanels: () => layout.toggleArrange(),
  toggleAutocast: () => { autocast.on = !autocast.on; if (!autocast.on) S.highlight.list = false; else { autocast.selection.resume(S.selection); autocast.nextMove = 0; } toast(t(autocast.on ? 'Autocast on' : 'Autocast off')); },
  showHighlights: () => { S.highlight.list = !S.highlight.list; },
  showTutorial: () => showTutorial(0),
};
for (const action of GOTO_ACTIONS) {
  // Looked up per press: the table follows the game being watched.
  ACTIONS[action] = () => gotoNext((r) => buildingMasters(action).includes(r[2]) && (!S.perspective || r[1] === S.perspective), action);
  ACTIONS[action.replace(/^goto/, 'selectAll')] = () => selectAllOf(action);
}
for (let i = 0; i <= 8; i++) ACTIONS[`setPlayer${i}`] = () => setPerspective(i);
for (let i = 0; i <= 9; i++) {
  ACTIONS[`setControlGroup${i}`] = () => { S.controlGroups[i] = [...S.selection]; toast(t('Control group {n} set', { n: i })); };
  ACTIONS[`callControlGroup${i}`] = () => { if (S.controlGroups[i]) S.selection = new Set(S.controlGroups[i]); };
}

async function addBookmark(at) {
  const when = Math.max(S.start, Math.round(at));
  S.bookmarks = [...S.bookmarks, when].sort((a, b) => a - b);
  await api('/api/bookmarks', { bookmarks: S.bookmarks }).catch(() => null);
  toast(t('Bookmark at {time}', { time: fmtTime(when) }));
}

async function removeBookmarkNear(at) {
  const tol = (S.end - S.start) / 100;
  const before = S.bookmarks.length;
  S.bookmarks = S.bookmarks.filter((b) => Math.abs(b - at) > tol);
  if (S.bookmarks.length === before) return addBookmark(at);
  await api('/api/bookmarks', { bookmarks: S.bookmarks }).catch(() => null);
  toast(t('Bookmark removed'));
}

function showEndgame() {
  if (!overlays.isOpen('overlay-endgame')) overlays.toggle('overlay-endgame', () => overlays.renderEndgame(seek));
}

async function afterOpen() {
  generation = -1;
  const desc = await api('/api/session');
  await refreshSession(desc);
}

// -- wiring ---------------------------------------------------------------------------------

function wireScrub() {
  const scrub = $('scrub-canvas');
  const hover = $('scrub-hover');
  let scrubbing = false;
  const showHover = (e) => {
    const r = scrub.getBoundingClientRect();
    const x = Math.max(0, Math.min(r.width, e.clientX - r.left));
    hover.style.left = `${x}px`;
    hover.firstElementChild.textContent = fmtTime(panels.scrubTime(e));
    hover.classList.remove('hidden');
  };
  scrub.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || seekLocked()) return;
    scrubbing = true; S.scrubbing = true; showHover(e); seek(panels.scrubTime(e));
  });
  scrub.addEventListener('mousemove', (e) => { if (!seekLocked()) showHover(e); });
  scrub.addEventListener('mouseleave', () => { if (!scrubbing) hover.classList.add('hidden'); });
  // While dragging, seek at most every SCRUB_MS (each seek is a view request) and
  // land exactly where the mouse is released.
  const SCRUB_MS = 80;
  let scrubAt = 0, scrubLast = null, scrubTimer = 0;
  const scrubSeek = () => { scrubTimer = 0; scrubAt = performance.now(); if (scrubLast != null) seek(scrubLast); scrubLast = null; };
  // A release the page never saw (outside the window, a focus change) ends the drag.
  const endScrub = () => { if (scrubbing) window.dispatchEvent(new MouseEvent('mouseup')); };
  window.addEventListener('blur', endScrub);
  window.addEventListener('mousemove', (e) => {
    if (!scrubbing) return;
    if (!(e.buttons & 1)) { endScrub(); return; }
    showHover(e);
    scrubLast = panels.scrubTime(e);
    if (performance.now() - scrubAt >= SCRUB_MS) scrubSeek();
    else if (!scrubTimer) scrubTimer = setTimeout(scrubSeek, SCRUB_MS - (performance.now() - scrubAt));
  });
  window.addEventListener('mouseup', () => {
    if (!scrubbing) return;
    scrubbing = false; hover.classList.add('hidden');
    S.scrubbing = false;
    // Land exactly where released (a move still waiting for the throttle).
    if (scrubTimer) clearTimeout(scrubTimer);
    if (scrubLast != null) scrubSeek(); else scrubTimer = 0;
  });
  scrub.addEventListener('contextmenu', (e) => { e.preventDefault(); if (!seekLocked()) removeBookmarkNear(panels.scrubTime(e)); });
}

function wire() {
  window.addEventListener('resize', world.resize);
  new ResizeObserver(world.resizeMinimap).observe($('minimap'));
  // Edge scrolling follows the pointer only while it is over the map: not over a
  // HUD control near the edge, and not after it has left the window.
  window.addEventListener('mousemove', (e) => {
    mouse = e.target === $('world') ? { x: e.clientX, y: e.clientY } : { x: null, y: null };
  });
  document.documentElement.addEventListener('mouseleave', () => { mouse = { x: null, y: null }; });
  window.addEventListener('blur', () => { mouse = { x: null, y: null }; });
  window.addEventListener('keyup', (e) => {
    if (e.key === 'Tab' && S._peek) {
      S.perspective = S._peek.perspective; S.fogMode = S._peek.fogMode; S._peek = null;
    }
  });
  window.addEventListener('keydown', (e) => {
    if (e.target.matches('input, textarea, select')) return;
    if (omniOpen() && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      const items = [...$('omni-menu').querySelectorAll('button')];
      const i = items.indexOf(document.activeElement);
      items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
      return;
    }
    if (e.key === 'Tab') {
      // Hold Tab: peek at the fog of the selection's owner.
      e.preventDefault();
      const o = selectionOwner();
      if (!S._peek && o) { S._peek = { perspective: S.perspective, fogMode: S.fogMode }; S.perspective = o; S.fogMode = 'standard'; }
      return;
    }
    const a = actionFor(e);
    if (a && ACTIONS[a]) { e.preventDefault(); ACTIONS[a](); renderHud(); return; }
    const pan = 28;
    if (e.key === 'ArrowLeft') world.pan(-pan, 0);
    if (e.key === 'ArrowRight') world.pan(pan, 0);
    if (e.key === 'ArrowUp') world.pan(0, -pan);
    if (e.key === 'ArrowDown') world.pan(0, pan);
  });
  // Lock the cursor on the first click into the world (settings.clipCursorInGame).
  window.addEventListener('mousedown', (e) => {
    if (!settings.clipCursorInGame || e.button !== 0 || e.target !== $('world') || document.pointerLockElement) return;
    world.virtualCursor.x = e.clientX; world.virtualCursor.y = e.clientY;
    const p = $('world').requestPointerLock();
    if (p && p.catch) p.catch(() => null);
    e.stopPropagation();
  }, true);
  // Clicking outside the menu closes it.
  window.addEventListener('mousedown', (e) => {
    if (omniOpen() && !e.target.closest('#omni-menu, #btn-menu')) closeOmni();
  });
  // Auto-minimise the game while Vantage has focus.
  window.addEventListener('focus', () => gameWindow('MINIMIZED'));
  window.addEventListener('blur', () => gameWindow('RESTORE'));
  world.installInput(onSelect);
  $('dash-prev').onclick = ACTIONS.cycleDashboardBackward;
  $('dash-next').onclick = ACTIONS.cycleDashboardForward;
  $('tc-play').onclick = () => { togglePause(); renderHud(); };
  $('tc-back').onclick = () => { seek(S.t - 30000); renderHud(); };
  $('tc-fwd').onclick = () => { seek(S.t + 30000); renderHud(); };
  $('tc-rew').onclick = () => { shuttle(-1); renderHud(); };
  $('tc-ff').onclick = () => { shuttle(1); renderHud(); };
  $('tc-slower').onclick = () => { setSpeed(S.speedIndex - 1); renderHud(); };
  $('tc-faster').onclick = () => { setSpeed(S.speedIndex + 1); renderHud(); };
  const reviewButton = document.createElement('button'); reviewButton.id = 'tc-review'; reviewButton.textContent = t('Review'); reviewButton.onclick = () => toggleReviewTimeline(seek); $('time-controls2').prepend(reviewButton);
  window.addEventListener('vantage-review-ready', () => panels.renderUnitPanel());
  window.addEventListener('vantage-investigate', (event) => { S.investigatePlayer = event.detail?.pid; overlays.toggle('overlay-stats', () => overlays.renderStats(seek, event.detail?.metric)); });
  $('tc-bookmark').onclick = () => addBookmark(S.t - 30000);
  $('tc-bm-prev').onclick = () => { ACTIONS.bookmarkPrev(); renderHud(); };
  $('tc-bm-next').onclick = () => { ACTIONS.bookmarkNext(); renderHud(); };
  $('tc-live').onclick = () => { S.followLive = true; S.liveSpeedPicked = false; renderHud(); };
  $('tc-rec').onclick = toggleRecord;
  $('tc-stop').onclick = stopWatching;
  wireScrub();
  $('btn-menu').onclick = toggleOmni;
  $('omni-menu').onclick = (e) => {
    const b = e.target.closest('[data-omni]');
    if (!b) return;
    closeOmni();
    ACTIONS[b.dataset.omni]();
    renderHud();
  };
  $('btn-home').onclick = ACTIONS.openHome;
  $('btn-stats').onclick = ACTIONS.showAchievements;
  // Fog icon: click or right-click cycles, middle-click combines team fog.
  $('btn-fog').onclick = () => { cycleFog(); renderHud(); };
  $('btn-fog').oncontextmenu = (e) => { e.preventDefault(); cycleFog(); renderHud(); };
  $('btn-fog').onauxclick = (e) => { if (e.button === 1) { ACTIONS.toggleCombinedFogOfWar(); renderHud(); } };
  $('btn-mmmode').onclick = () => { cycleMinimap(); renderHud(); };
  $('btn-mmmode').oncontextmenu = (e) => { e.preventDefault(); cycleMinimap(); renderHud(); };
  $('btn-res').onclick = () => { showResLeft = !showResLeft; renderHud(); };
  $('btn-settings').onclick = openSettings;
  $('btn-panels').onclick = () => layout.togglePanelsMenu();
  layout.installPanelsMenu(renderHud);
  layout.installPanelTools(renderHud, toast);
  installPanelResizing(renderHud);
  $('btn-help').onclick = ACTIONS.openHelp;
  $('highlight-bar').onclick = (e) => {
    const b = e.target.closest('[data-hl]');
    if (!b) return;
    const q = S.highlight.seq;
    if (b.dataset.hl === 'selection') {
      if (autocast.selection.enabled) autocast.selection.enabled = false;
      else { autocast.selection.resume(S.selection); autocast.nextMove = 0; if (q) q.selectionReady = false; }
    }
    else if (b.dataset.hl === 'pause') toggleSequencePause();
    else if (b.dataset.hl === 'stop') endSequence();
    else if (q && b.dataset.hl === 'prev') playElement(q.idx - 1);
    else if (q && b.dataset.hl === 'cur') playElement(q.idx);
    else if (q && b.dataset.hl === 'next') playElement(q.idx + 1);
    else if (b.dataset.hl === 'all') S.highlight.list = !S.highlight.list;
    renderHud();
  };
  $('highlight-list').onclick = (e) => {
    const row = e.target.closest('[data-hero]');
    if (!row) return;
    const h = heroes(S.t).find((x) => String(x.id) === row.dataset.hero);
    if (h) startSequence(h);
    renderHud();
  };
  // Other modules (the settings page) can open the documentation.
  document.addEventListener('vantage:open-docs', openDocs);
  // The end-game "Most kills" commendation's "Show all" (overlays.js).
  document.addEventListener('vantage:autocast', (e) => autocastEntity(e.detail && e.detail.unitId));
  document.addEventListener('vantage:open-html-server', openHtmlServer);
  document.addEventListener('vantage:start-game', () => startGame());
  panels.renderEventFilters(() => renderHud());
  document.addEventListener('vantage:language', () => panels.renderEventFilters(() => renderHud()));
}

async function boot() {
  // A missing game icon should leave an empty slot, not a broken-image glyph.
  window.addEventListener('error', (e) => { if (e.target && e.target.tagName === 'IMG') e.target.style.visibility = 'hidden'; }, true);
  if (new URLSearchParams(location.search).get('overlay') === '1') {
    // On <html> too: the page background must be transparent for OBS.
    document.documentElement.classList.add('overlay-mode');
    document.body.classList.add('overlay-mode');
  }
  world.resize();
  wire();
  const probing = probeAssetOrigin();
  serverConfig = await api('/api/config').catch(() => null);
  await probing;
  S.version = (serverConfig && serverConfig.version) || '';
  applyServerConfig(serverConfig);
  document.body.dataset.tooltips = tooltipLevel();
  await setLanguage(settings.language || detectLanguage());
  const conflicts = rebuildKeys();
  if (conflicts.length) toast(t('Hotkey conflict: {list}', { list: describeConflicts(conflicts, t).join('; ') }));
  const desc = await api('/api/session').catch(() => null);
  if (desc) await refreshSession(desc);
  if (!desc || desc.mode === 'idle') ACTIONS.openHome();
  // The certificate card comes first: the tutorial can wait for a working setup.
  else if (!settings.seenTutorial && !document.body.classList.contains('overlay-mode')
    && !(desc.mode === 'live' && desc.certs && (desc.certs.missing || []).length)) showTutorial(0);
  subscribe();
  hudTimer = setInterval(() => { if (!document.hidden) renderHud(); }, 250);
  // The panels too: a caster column has a fixed height, so only they change size.
  for (const id of ['scoreboard', 'timebar', 'leftcol', 'overview', 'techs', 'production']) if ($(id)) leftColObserver.observe($(id));
  window.addEventListener('resize', layoutLeftColumn);
  requestAnimationFrame(tick);
}

// Debug/automation handle (used by the headless UI checks). openDocs and
// hotkey conflicts are also reachable from other modules through it.
window.vantage = { S, settings, seek, viewTimings, viewStats, actions: ACTIONS, world, openDocs, heroes, startSequence, topKiller, autocastEntity, reloadSkins };

boot();
