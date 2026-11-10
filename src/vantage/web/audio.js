// Game sound: notifications, unit sounds and taunts, played as playback passes
// the moments they belong to, plus the world's own soundscape (fights, villager
// work, animals, burning buildings, the outdoor ambience) built from what is on
// screen. Audio comes from the installed game via /audio/.
//
// Mixing: every sound goes to a bus gain (settings.soundVolumes /
// soundVolumesExtra) and then the master (soundOutputVolume). World buses also
// send to an outdoor reverb (a synthetic impulse response) whose return level
// is soundVolumesExtra.reverb.

import { S, settings, unitInfo } from './state.js';
import { scene } from './world.js';
import { selectedOwners, eventAllowed, AlertCadence } from './audio-focus.js';
import { eventIndexAfter } from './playback.js';

let ctx = null;
const buffers = new Map();
const busy = new Set();
let lastT = null;
const lastPlay = new Map(); // bus -> time of its last sound

// World buses feeding the reverb, and their soundVolumesExtra keys.
const REVERB_BUSES = new Set(['villagers', 'critters', 'ambience', 'combatImpacts', 'combat', 'units']);

function audioCtx() {
  if (!ctx) {
    try { ctx = new AudioContext(); } catch (e) { ctx = null; }
  }
  return ctx;
}

// Browsers only start audio after a user gesture.
window.addEventListener('pointerdown', () => { const c = audioCtx(); if (c && c.state === 'suspended') c.resume(); }, { once: false });

async function load(url) {
  if (buffers.has(url)) return buffers.get(url);
  if (busy.has(url)) return null;
  busy.add(url);
  try {
    const r = await fetch(url);
    if (!r.ok) { buffers.set(url, null); return null; }
    const buf = await audioCtx().decodeAudioData(await r.arrayBuffer());
    buffers.set(url, buf);
    return buf;
  } catch (e) {
    buffers.set(url, null);
    return null;
  } finally {
    busy.delete(url);
  }
}

// -- mixer ------------------------------------------------------------------------------

let mix = null;

function busVolume(bus) {
  const v = settings.soundVolumes && settings.soundVolumes[bus];
  if (v != null) return v;
  const x = settings.soundVolumesExtra && settings.soundVolumesExtra[bus];
  return x != null ? x : 1;
}

// Two seconds of decaying stereo noise: a soft outdoor tail.
function impulse(c) {
  const len = Math.floor(c.sampleRate * 2.2);
  const buf = c.createBuffer(2, len, c.sampleRate);
  let seed = 12345;
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) {
      seed = (seed * 1103515245 + 12345) >>> 0;
      const n = (seed / 4294967296) * 2 - 1;
      d[i] = n * Math.pow(1 - i / len, 3.2) * (i < 64 ? i / 64 : 1);
    }
  }
  return buf;
}

function mixer() {
  const c = audioCtx();
  if (!c) return null;
  if (mix) return mix;
  const master = c.createGain();
  master.connect(c.destination);
  const verb = c.createConvolver();
  verb.buffer = impulse(c);
  const verbReturn = c.createGain();
  verb.connect(verbReturn).connect(master);
  mix = { master, verb, verbReturn, buses: new Map() };
  return mix;
}

function bus(name) {
  const m = mixer();
  if (!m) return null;
  let b = m.buses.get(name);
  if (!b) {
    b = audioCtx().createGain();
    b.connect(m.master);
    if (REVERB_BUSES.has(name)) b.connect(m.verb);
    m.buses.set(name, b);
  }
  return b;
}

// Follow the settings every frame (cheap: a few gain values).
function updateMix() {
  if (!mix) return;
  mix.master.gain.value = settings.soundOutputVolume ?? 1;
  mix.verbReturn.gain.value = (settings.soundVolumesExtra && settings.soundVolumesExtra.reverb) ?? 0;
  for (const [name, g] of mix.buses) g.gain.value = busVolume(name);
}

/** Play one sound. ``opts.gain`` scales it, ``opts.minGap`` (ms) throttles the bus. */
export async function play(url, busName = 'events', pan = 0, opts = {}) {
  const c = audioCtx();
  if (!c || c.state !== 'running') return null;
  if ((settings.soundOutputVolume ?? 1) <= 0 || busVolume(busName) <= 0) return null;
  const now = performance.now();
  const gap = opts.minGap ?? (busName === 'selection' ? 0 : 60);
  if (now - (lastPlay.get(busName) || 0) < gap) return null; // don't stack dozens of sounds
  lastPlay.set(busName, now);
  const buf = await load(url);
  const out = bus(busName);
  if (!buf || !out) return null;
  updateMix();
  const src = c.createBufferSource();
  src.buffer = buf;
  src.loop = !!opts.loop;
  const gain = c.createGain();
  gain.gain.value = opts.gain ?? 1;
  const panner = c.createStereoPanner();
  panner.pan.value = Math.max(-1, Math.min(1, pan));
  src.connect(gain).connect(panner).connect(out);
  src.start();
  return { src, gain, panner };
}

const variant = () => Math.floor(Math.random() * 5);
const ev = (id) => `/audio/event/${id}.ogg?v=${variant()}`;
const notify = (name, v = variant()) => `/audio/notify/${name}.ogg?v=${v}`;

/** Taunt voice language: the setting, else the interface language. */
function tauntLanguage() {
  const lang = settings.tauntLanguage || settings.language || (navigator.language || 'en');
  return encodeURIComponent(lang);
}

// Event relevance is independent of the fog/statistics perspective.
function allowed(kind, event, owners, toScreen) {
  const mode = (settings.soundEventConfig || {})[kind] || 'selectedPlayer';
  return eventAllowed(mode, event, S.perspective, owners, onScreen(event.x, event.y, toScreen) !== null);
}

function onScreen(x, y, toScreen) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  const [px, py] = toScreen(x, y);
  if (px < -100 || py < -100 || px > innerWidth + 100 || py > innerHeight + 100) return null;
  return (px / innerWidth) * 2 - 1;
}

const alertCadence = new AlertCadence();
function alert(name, event, owners, toScreen, kind) {
  if (!allowed(kind, event, owners, toScreen)) return;
  if (!alertCadence.allow(performance.now(), settings.soundAlertInterval ?? 3000)) return;
  play(notify(name), 'events', onScreen(event.x, event.y, toScreen) ?? 0);
}

// Called every frame with the playback clock; plays what was crossed since last call.
export function tick(toScreen) {
  const t = S.t;
  const prev = lastT;
  lastT = t;
  updateMix();
  const running = !(prev == null || t <= prev || t - prev > 3000 || !S.playing);
  world(running, toScreen);
  if (!running) return; // seeking / rewinding / paused: silence
  const owners = selectedOwners(S);
  // The events of this frame's step only (the log is sorted by time): scanning
  // the whole game's log every frame grew with the game.
  const events = S.events;
  for (let i = eventIndexAfter(events, prev); i < events.length && events[i].t <= t; i++) {
    const e = events[i];
    switch (e.kind) {
      case 'age_up': play(notify('age_up')); break;
      case 'researched': if (e.cat !== 'age' && allowed('research', e, owners, toScreen)) play(notify('tech_researched')); break;
      case 'trained': {
        const snd = unitInfo(e.master).sounds?.created;
        const pan = onScreen(e.x, e.y, toScreen);
        if (snd && allowed('train', e, owners, toScreen) && pan !== null) play(ev(snd), 'units', pan);
        break;
      }
      case 'under_attack': alert(e.alert === 2 ? 'under_attack_town' : e.alert === 1 ? 'under_attack_animals' : 'under_attack', e, owners, toScreen, 'attack'); break;
      case 'kill': {
        const pan = onScreen(e.x, e.y, toScreen);
        const snd = e.victim && unitInfo(e.victim.master).sounds?.death;
        if (snd && pan !== null) play(ev(snd), 'combat', pan);
        break;
      }
      case 'sound': {
        // A per-entity SoundEvent from the stream (when the server forwards them).
        const pan = onScreen(e.x, e.y, toScreen);
        if (e.event && pan !== null) play(ev(e.event), e.bus || 'combatImpacts', pan);
        break;
      }
      case 'conversion': alert('under_attack_conversion', e, owners, toScreen, 'conversion'); break;
      case 'tribute': play(notify('tribute')); break;
      case 'buy': play(notify('market_buy')); break;
      case 'sell': play(notify('market_sell')); break;
      case 'won': play(notify('victory')); break;
      case 'lost': case 'resigned': play(notify('player_eliminated')); break;
      case 'wonder_started': case 'wonder_completed': case 'wonder_destroyed': play(notify(e.kind)); break;
      case 'chat': {
        const opt = settings.chatEventSoundOption || 'chatAlertAndTaunt';
        if (opt === 'none') break;
        const taunt = /^\s*(\d{1,3})\s*$/.exec(e.text || '');
        if (opt === 'chatAlertAndTaunt' && taunt && +taunt[1] >= 1 && +taunt[1] <= 105) play(`/audio/taunt/${+taunt[1]}.ogg?lang=${tauntLanguage()}`, 'taunts');
        else play(notify('chat'));
        break;
      }
      default: break;
    }
  }
}

export function selectionSound(mid) {
  const snd = unitInfo(mid).sounds?.selected;
  if (snd) play(ev(snd), 'selection');
}

// -- world soundscape ---------------------------------------------------------------------
// Sampled from world.js's `scene` (what was drawn this frame). Each kind of
// sound has its own cadence so the mix stays sparse, like the game's.

const next = { combat: 0, hit: 0, work: 0, critter: 0, ambience: 0, gulls: 0 };
let fire = null; // the looping building-fire voice

const pickOne = (list) => list[Math.floor(Math.random() * list.length)];
const later = (now, ms, jitter) => now + ms + Math.random() * jitter;

// Weapon sound for a fighting unit, by unit class (class 0 is streamed as -1).
function weaponSound(mid) {
  const u = unitInfo(mid);
  const range = (u.stats && u.stats.range) || 0;
  switch (u.cls) {
    case 54: return 'weapon_trebuchet';
    case 55: return 'weapon_scorpion';
    case 13: return range > 9 ? 'weapon_bombard' : 'weapon_mangonel';
    case 44: return 'weapon_shoot_hand_cannon';
    case -1: case 36: return range > 0 ? 'weapon_shoot_bow' : 'weapon_swing_mace';
    case 6: return Math.random() < 0.5 ? 'weapon_swing_spear' : 'weapon_swing_club';
    case 12: case 47: case 23: return 'weapon_swing_mace';
    default: return range >= 2 ? 'weapon_shoot_crossbow' : 'weapon_swing_club';
  }
}

const WORK_SOUNDS = { 3: 'villager_wood', 4: 'villager_mining', 5: 'villager_mining', 6: 'villager_build', 7: 'villager_build' };
const FARMERS = new Set([214, 259]), FISHERS = new Set([56, 57]);
function workSound(mid, act) {
  if (act === 2) return FARMERS.has(mid) ? 'villager_farm' : FISHERS.has(mid) ? 'villager_fishing' : 'villager_forage';
  return WORK_SOUNDS[act] || null;
}

function world(running, toScreen) {
  const c = ctx;
  const live = running && c && c.state === 'running' && !document.hidden;
  updateFire(live);
  if (!live) return;
  const now = performance.now();
  if (now > next.combat && scene.fights.length) {
    next.combat = later(now, 260, 260);
    const [mid, pan] = pickOne(scene.fights);
    play(notify(weaponSound(mid)), 'combatImpacts', pan, { minGap: 0, gain: 0.8 });
  }
  if (now > next.hit && scene.hits.length) {
    // Hit points lost since the last keyframe: the victim's own damage sound
    // (the master's damageSoundEvent) when it has one, else a generic impact.
    next.hit = later(now, 380, 300);
    const [mid, x, y] = pickOne(scene.hits);
    const pan = onScreen(x, y, toScreen);
    if (pan !== null) {
      const own = unitInfo(mid).sounds?.damage;
      play(own ? ev(own) : notify('weapon_hit_club'), 'combatImpacts', pan, { minGap: 0, gain: 0.7 });
    }
  }
  if (now > next.work && scene.workers.length) {
    next.work = later(now, 900, 900);
    const [mid, act, pan] = pickOne(scene.workers);
    const name = workSound(mid, act);
    if (name) play(notify(name), 'villagers', pan, { minGap: 0, gain: 0.7 });
  }
  if (now > next.critter && scene.animals.length) {
    next.critter = later(now, 3500, 4000);
    const [mid, pan] = pickOne(scene.animals);
    const snd = unitInfo(mid).sounds?.selected || unitInfo(mid).sounds?.created;
    if (snd) play(ev(snd), 'critters', pan, { minGap: 0, gain: 0.6 });
  }
  if (now > next.ambience) {
    // Overlapping layers of the biome's ambience bed (birds, wind, water...).
    next.ambience = later(now, 1600, 1600);
    play(notify(`ambience_${scene.biome || 'plains'}`, Math.floor(Math.random() * 64)), 'ambience', (Math.random() - 0.5) * 1.2, { minGap: 0, gain: 0.8 });
  }
  if (now > next.gulls && scene.water > 0.15) {
    next.gulls = later(now, 12000, 12000);
    play(notify('seagulls'), 'ambience', (Math.random() - 0.5) * 1.6, { minGap: 0, gain: 0.5 });
  }
}

// One looping fire voice whose level follows how many buildings burn on screen.
function updateFire(live) {
  const want = live && scene.burning > 0;
  if (want && !fire) {
    fire = { voice: null, pending: true };
    const holder = fire;
    play(notify('building_fire', 0), 'combatImpacts', 0, { loop: true, minGap: 0, gain: 0 }).then((v) => {
      holder.pending = false;
      if (fire !== holder || !v) { if (v) v.src.stop(); if (fire === holder) fire = null; return; }
      holder.voice = v;
    });
  }
  if (!fire || !fire.voice) { if (!want && fire && !fire.pending) fire = null; return; }
  const v = fire.voice, t = ctx.currentTime;
  if (!want) {
    v.gain.gain.setTargetAtTime(0, t, 0.25);
    const old = fire;
    fire = null;
    setTimeout(() => { try { old.voice.src.stop(); } catch (e) { /* already stopped */ } }, 1500);
    return;
  }
  const level = Math.min(1, 0.35 + 0.15 * scene.burning);
  v.gain.gain.setTargetAtTime(level, t, 0.3);
  v.panner.pan.setTargetAtTime(Math.max(-1, Math.min(1, scene.burnPan / scene.burning)), t, 0.3);
}
