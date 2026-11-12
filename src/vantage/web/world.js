// Isometric world view + minimap, camera and selection.
//
// Map tile (x, y): x runs from the left corner to the bottom corner of the
// diamond, y from the left corner to the top corner (AoE2 convention).
//
// Picture pipeline, per frame: terrain (flat or textured) -> grid -> fog (Spy
// mode: under the entities) -> entities (sprites, damage, foundations) -> range
// circles -> particles -> fog (Standard mode: over everything) -> bloom ->
// per-channel colour/opacity -> FXAA. The page applies brightness, contrast,
// saturation and gamma to the canvas element as CSS filters.
//
// With GPU rendering (settings.gpuSprites, the default where WebGL2 works and
// bloom, FXAA and the colour channels are off) the picture is three stacked
// canvases: this one (ground, selection rings, spy fog; graded by the passes),
// sprite-gl.js's (every sprite in one instanced draw, the unit outline pass,
// graded in its shader) and an overlay (bars, flames, range circles, particles,
// fog). Terrain chunks are then composited by terrain-gl.js composeChunk.

import { S, settings, playerColor, unitInfo, unitIcon, entityInfo, entityStatsValid, players, api, gameKey, assetUrl, withAssetVersion } from './state.js';
import * as TG from './terrain-gl.js';
import * as SG from './sprite-gl.js';
import { RowInterpolator, sortByKey } from './playback.js';
import { followRows } from './camera-follow.js';
import { changedTilesInRegion, terrainRegion, changedTreeTiles, groundProjection, mergeDirtyRect, treeSpriteState, OutlineCache, coalesceRects } from './render-cache.js';
import { ViewGraphics, SpriteHistory } from './graphics-cache.js';

const TW = 32, TH = 16;           // tile size on screen at zoom 1
const TERRAIN_TW = 16, TERRAIN_TH = 8; // pre-rendered terrain resolution

const canvas = document.getElementById('world');
// The map's 2D context; draw() points it at an offscreen canvas while it
// paints the cached ground layer, so every helper below draws through `ctx`.
let ctx = canvas.getContext('2d');
const mainCtx = ctx;
// Particles (flames, smoke, trails, dust) draw here: their own layer during a
// frame (laid over the world after the grade, see fxComposite), else the world.
let pctx = mainCtx;
let fxLayer = null;
const mini = document.getElementById('minimap');
const mctx = mini.getContext('2d');

let terrainCanvas = null, miniTerrain = null, treeTiles = null, treeFacets = null, treesT = -1, treeKinds = [];

// -- settings helpers ------------------------------------------------------------
// Settings objects merge shallowly with stored ones, so nested keys can be missing.

/** Texture filtering toggle (settings.filtering): true = smooth (bilinear). */
function filt(key) {
  const f = settings.filtering;
  return !f || f[key] !== false;
}

function postExtra() {
  return {
    red: 1, green: 1, blue: 1, alpha: 1, fxaa: false,
    bloomEnable: false, bloomThreshold: 0.9, bloomBlur: 8, bloomScale: 1, bloomBrightness: 1, bloomQuality: 'medium',
    ...(settings.postExtra || {}),
  };
}

/** Sprite-mod query part, so a different mod set never reuses cached strips. */
// Called for every strip key, many times a frame: hash the mod folders once
// per change of the setting, not per call.
let modMemo = { on: null, dirs: null, value: '' };
function modQuery() {
  if (!(settings.enableGraphicsMods || settings.enableSpriteMods)) return '';
  const list = settings.modDirectories || [];
  if (modMemo.on === true && modMemo.dirs === list) return modMemo.value;
  modMemo = { on: true, dirs: list, value: hashModDirs(list) };
  return modMemo.value;
}
function hashModDirs(list) {
  const dirs = list.join('|');
  let h = 0;
  for (let i = 0; i < dirs.length; i++) h = (h * 31 + dirs.charCodeAt(i)) | 0;
  return `&mods=${(h >>> 0).toString(36)}`;
}

// -- game sprites ----------------------------------------------------------------
// Sprites are drawn at the game's own scale: a standard-resolution (x1) sprite
// is authored for a 96-pixel-wide tile.
const SPRITE_TILE = 96;
const spriteCache = new Map();
// Decoded strips are budgeted by the atlas memory settings: past the
// budget the least recently drawn strips are dropped (and refetched if needed).
let spriteBytes = 0;
let spriteRevision = 0;
function spriteBudget(hd) {
  return 1048576 * Math.max(32, Number(hd ? settings.atlasMemoryUhd : settings.atlasMemoryNormal) || 256);
}
function evictSprites(hd) {
  const budget = spriteBudget(hd);
  for (const [k, v] of spriteCache) {
    if (spriteBytes <= budget) break;
    if (!v.img || v.pin) continue;
    spriteBytes -= v.bytes || 0;
    spriteCache.delete(k);
    spriteRevision++;
  }
}
export function spriteMemory() { return { bytes: spriteBytes, strips: spriteCache.size }; }
let spriteRequests = 0;
let firstFrameSpritesPending = false;
/** null = unknown, true/false once the server answered a layer=shadow request. */
let layerSplit = null;

// opts.dmg: damage level 1-3 (the SLD damage mask at 25/50/75 % lost);
// opts.layer: 'shadow' | 'main' (a single layer, for separate filtering).
// Strip queries are built for every layer of every entity, every frame: keep
// the few distinct ones (game, resolution, mods x damage, layer, facing, mask).
let queryMemo = { base: '', table: new Map() };
function stripQuery(opts) {
  const hd = settings.enhancedGraphics && S.camera.zoom >= 1.4;
  // The game is part of the key: Return of Rome reuses AoE2's sprite ids.
  const base = `g=${S.game}${hd ? '&hd=1' : ''}${modQuery()}`;
  if (base !== queryMemo.base) queryMemo = { base, table: new Map() };
  // Memoized only for the usual option values (whole damage levels, the two layers).
  const usual = !opts || (Number.isInteger(opts.dmg || 0) && (!opts.layer || opts.layer === 'shadow' || opts.layer === 'main'));
  const code = !usual ? -1 : !opts ? 0 : 1 + (opts.dmg || 0) * 16 + (opts.layer === 'shadow' ? 4 : opts.layer === 'main' ? 8 : 0)
    + (opts.dir ? 2 : 0) + (opts.pm ? 1 : 0);
  const known = code >= 0 ? queryMemo.table.get(code) : undefined;
  if (known !== undefined) return known;
  const q = buildStripQuery(base, opts);
  if (code >= 0) queryMemo.table.set(code, q);
  return q;
}
function buildStripQuery(base, opts) {
  let query = base;
  // Damage shading, as the game's sprite shader darkens a damaged building.
  if (opts && opts.dmg) query += `&dmg=${opts.dmg}`;
  if (opts && opts.layer) query += `&layer=${opts.layer}`;
  // Units: the facing is a heading (the server maps it to the SLD's facing order).
  if (opts && opts.dir) query += '&dir=1';
  // Uncoloured, the player mask below it: the GPU batch applies the colour.
  if (opts && opts.pm) query += '&pm=1';
  return query;
}

// Which strip a sprite layer of a player's object is drawn from: [colour index,
// player mask]. With GPU rendering one uncoloured strip carrying the player mask
// serves every player (an 8-player battle fetched each sprite 8 times); shadows
// have no player colour at all. Sprites without a mask (SMX files) and the 2D
// path take strips in the player's colour.
const noMask = new Set();
function gpuDrawing() { return spritesOn() && gpuLayers() && SG.available(); }
function stripColor(sid, owner, layer, gpu) {
  if (colourless.has(sid) || layer === 'shadow') return [-1, false];
  if (gpu && owner && settings.gpuTint !== false && !noMask.has(sid)) return [-1, true];
  return [colorIndex(owner), false];
}
/** The colour the GPU tints a player's sprites with (the server's own table). */
function spriteTint(owner) {
  const pc = S.catalog && S.catalog.player_colors, c = pc && pc[colorIndex(owner)];
  return c ? (c[0] << 16) | (c[1] << 8) | c[2] : -1;
}
// Sprites whose strips have no player colour (meta.pc false: most projectiles):
// one copy, colour -1, serves every player.
const colourless = new Set();
function spriteStrip(sid, facet, color, opts) {
  if (colourless.has(sid)) color = -1;
  const hd = settings.enhancedGraphics && S.camera.zoom >= 1.4;
  const query = stripQuery(opts);
  const key = `${sid}/${facet}/${color}?${query}`;
  let e = spriteCache.get(key);
  // A transient failure (network, server busy) is retried after a while; a 404 is
  // the game having no picture there and stays as it is.
  if (e && e.retryAt && performance.now() > e.retryAt) { spriteCache.delete(key); spriteRevision++; e = null; }
  if (e) {
    if (countingDraw && !e.img && !e.failed) firstFrameSpritesPending = true;
    spriteCache.delete(key); spriteCache.set(key, e); // most recent last
    if (e.img || e.failed || !(opts && opts.dir)) return e;
    const near = nearestFacing(sid, facet, color, query);
    if (near && countingDraw) spriteStats.standIn++;
    return near || e;
  }
  evictSprites(hd);
  if (countingDraw) firstFrameSpritesPending = true;
  if (spriteRequests > 32) return null; // don't flood the server; retry next frame
  e = { meta: null, img: null, failed: false };
  spriteCache.set(key, e);
  const standIn = opts && opts.dir ? nearestFacing(sid, facet, color, query) : null;
  spriteRequests++;
  e.tile = hd ? SPRITE_TILE * 2 : SPRITE_TILE;
  const [path] = key.split('?');
  // One request: the PNG, its layout in the X-Sprite-Meta header (an older server
  // without it gets the .json as before), decoded off the main thread.
  fetch(assetUrl(`/sprite/${path}.png?${query}`))
    .then(async (r) => {
      if (!r.ok) throw new Error(String(r.status));
      const hdr = r.headers.get('X-Sprite-Meta');
      const m = hdr ? JSON.parse(hdr) : await fetch(assetUrl(`/sprite/${path}.json?${query}`)).then((j) => j.json());
      // Premultiplied: the GPU batch (sprite-gl.js) uploads the pixels as they are.
      const img = await createImageBitmap(await r.blob(), { premultiplyAlpha: 'premultiply' });
      e.meta = m;
      if (m.pc === false) colourless.add(sid);
      // Asked for the player mask, got none (an SMX sprite): coloured strips from now on.
      if (opts && opts.pm && !m.pm && m.pc !== false) noMask.add(sid);
      // A server that ignores ?layer= answers with the full strip: stop asking.
      if (opts && opts.layer) layerSplit = m.layer === opts.layer;
      e.img = img; e.bytes = img.width * img.height * 4; spriteBytes += e.bytes; spriteRequests--;
      // A colourless strip asked for in a player's colour, or with the player mask
      // (before the sprite was known to be colourless), also answers for the plain
      // colourless key: its top band is that strip, without a mask to apply.
      if (m.pc === false && (color !== -1 || (opts && opts.pm))) {
        const plain = opts && opts.pm ? stripQuery({ ...opts, pm: false }) : query;
        const k2 = `${sid}/${facet}/-1?${plain}`, cur = spriteCache.get(k2);
        if (!cur || !cur.img) spriteCache.set(k2, { meta: { ...m, pm: false }, img, tile: e.tile, failed: false, bytes: 0, pin: e.pin });
      }
    })
    .catch((err) => {
      e.failed = true;
      if (!(err && err.message === '404')) e.retryAt = performance.now() + 5000;
      spriteRequests--;
    });
  if (standIn && countingDraw) spriteStats.standIn++;
  return standIn || e;
}

// Strips the coming views will need on screen (new unit types, colours, facings,
// death animations), requested seconds early: graphics buffering (viewReady)
// holds at a view until they are in, and this way it rarely has to. Projectile
// headings go first. (A wider two-screen prefetch filled the sprite budget with
// strips never drawn, and eviction then dropped ones that were.)
let upcomingCheckAt = 0;
function prefetchUpcoming() {
  prefetchProjectileFacings();
  const now = performance.now();
  if (now - upcomingCheckAt > 100) {
    upcomingCheckAt = now;
    for (const n of [S.nextView, ...(S.upcoming || [])]) if (n && n.time > S.t && spriteRequests < 24) viewReady(n);
  }
}
/** The sprites a row's layers draw: composite roots expand into their parts
 * (catalog sprite_deltas), as drawSprites does. */
function layerSprites(layers) {
  const deltas = S.catalog && S.catalog.sprite_deltas;
  const out = [];
  for (const l of layers || []) {
    const parts = deltas && deltas[l[0]];
    if (parts) for (const p of parts) out.push(p[0]);
    else out.push(l[0]);
  }
  return out;
}

// Projectiles change heading every sample (100 ms), too often to buffer for: once a
// projectile sprite is seen in a colour, all its headings are requested (32 at
// most, small strips), so later shots draw their own heading, not a neighbour's.
const projectileSprites = new Set();
const projectileQueue = [];
function prefetchProjectileFacings() {
  const track = S.view && S.view.missile_track;
  if (track && track.length) {
    for (const [, rows] of track) {
      const gpu = gpuDrawing();
      for (const m of rows) {
        for (const sid of layerSprites(m[7])) {
          const [color, pm] = stripColor(sid, m[1], null, gpu);
          const k = `${sid}|${color}|${pm}`;
          if (projectileSprites.has(k)) continue;
          projectileSprites.add(k);
          for (let f = 0; f < 32; f++) projectileQueue.push([sid, f, color, pm]);
        }
      }
    }
  }
  // Ahead of the views' strips: a projectile type's headings are a one-off set,
  // and until they are in, every shot of it borrows a neighbour's heading.
  while (projectileQueue.length && spriteRequests < 30) {
    const [sid, f, color, pm] = projectileQueue.shift();
    const e = spriteStrip(sid, f, color, { dmg: 0, layer: null, dir: true, pm });
    if (e) e.pin = true; // small and reused by every shot: never evicted
  }
}


// Graphics buffering: is every strip the view `n` draws on screen loaded (or known
// to have no picture)? Missing ones are requested. Playback holds before entering
// a view that is not ready (app.js), as a video buffers, so a new unit, facing or
// death is never drawn as a placeholder or a stand-in: at 8x in a battle 20-30
// strips a second are new, and one takes ~0.2 s to arrive. Projectiles count
// too: the view's track names every heading its shots will take.
const viewGraphics = new ViewGraphics(collectViewSprites, spriteRequirementLoaded, requestSpriteRequirement);
export function graphicsChecks() { return { builds: viewGraphics.builds, hits: viewGraphics.hits }; }

// The camera enters the key coarsely: on a GRAPHICS_CELL px screen grid and in
// 4 % zoom steps. Keyed exactly, every pan step (follow-selection, Autocast,
// edge scrolling) rebuilt the requirements of up to 17 upcoming views (2,500
// rows each) ten times a second. collectViewSprites prefetches (but does not
// wait for) a margin as wide as the camera can drift inside one cell.
const GRAPHICS_CELL = 64;
const GRAPHICS_ZOOM_STEP = 0.04;
function graphicsContext() {
  const c = S.camera;
  const z = Math.exp(Math.round(Math.log(c.zoom) / GRAPHICS_ZOOM_STEP) * GRAPHICS_ZOOM_STEP);
  const cx = Math.round(((c.x + c.y) * TW / 2 * z) / GRAPHICS_CELL);
  const cy = Math.round(((c.y - c.x) * TH / 2 * z) / GRAPHICS_CELL);
  // The zoom cut-offs that change which strips are drawn (HD from 1.4, sprites
  // from 0.7) are exact, not stepped.
  const hd = settings.enhancedGraphics && c.zoom >= 1.4;
  let key = `${S.game}|${cx}|${cy}|${z.toFixed(4)}|${hd}|${spritesOn()}|${viewSize.w}|${viewSize.h}|${!!settings.enhancedGraphics}|${layerSplit}|${filt('unitShadow')}|${filt('unitColor')}|${modQuery()}|${gpuDrawing()}`;
  for (let pid = 0; pid <= 8; pid++) key += `|${colorIndex(pid)}`;
  return key;
}

function requirementKey(r) {
  return colourless.has(r.sid) ? `${r.sid}/${r.facet}/-1?${r.query}` : r.key;
}
function spriteRequirementLoaded(r) {
  const e = spriteCache.get(requirementKey(r));
  return !!(e && (e.img || e.failed));
}
function requestSpriteRequirement(r) {
  // Margin strips (prefetch) only while the budget has room: past it each one
  // would evict a strip that is on screen, which then has to load again.
  if (r.core === false && spriteBytes > 0.8 * spriteBudget(settings.enhancedGraphics && S.camera.zoom >= 1.4)) return;
  spriteStrip(r.sid, r.facet, r.color, r.opts);
  // Pin the exact projectile strip, rather than a temporary facing stand-in.
  const exact = r.pin && spriteCache.get(requirementKey(r));
  if (exact) exact.pin = true;
}

export function viewReady(n) {
  if (!n || !spritesOn() || !S.catalog) return true;
  return viewGraphics.ready(n, graphicsContext(), S.catalog, spriteRevision);
}

// Includes decoded images and the painted ground, not merely finished HTTP
// requests. Hidden first-frame draws also upload the GPU atlas before reveal.
export function initialFrameReady() {
  if (!S.map || !S.view || !S.catalog || !terrainCanvas) return false;
  buildViewTerrain();
  const terrain = !S.map.terrain_textures || !!viewTerrainCanvas;
  const sprites = viewReady(S.view);
  const images = [...imgCache.values()].every((im) => im.failed || (im.complete && im.naturalWidth));
  const trees = S.view.trees_t == null || S.view.trees_t < 0 || S.view.trees_t === treesT;
  const tiles = S.view.terrain_t == null || S.view.terrain_t < 0 || S.view.terrain_t === terrainT;
  return terrain && sprites && !firstFrameSpritesPending && images && trees && tiles
    && !treesPending && !terrainPending
    && ground.map === S.map && !!ground.key;
}

function collectViewSprites(n) {
  const deltas = S.catalog.sprite_deltas;
  const split = layerSplit !== false && filt('unitShadow') !== filt('unitColor');
  // Core: 120 px around the screen, what playback waits for (graphics buffering).
  // Extra: the camera's drift within one graphics cell (up to a cell diagonal)
  // and a zoom step about the centre, prefetched but never waited for.
  const m = 120, m_ = 120;
  const drift = GRAPHICS_CELL * 1.5 + GRAPHICS_ZOOM_STEP * Math.max(viewSize.w, viewSize.h) / 2;
  const requests = new Map();
  const gpu = gpuDrawing();
  let core = true;
  const add = (sid, facet, color, opts, pin = false) => {
    const query = stripQuery(opts), key = `${sid}/${facet}/${color}?${query}`;
    const old = requests.get(key);
    if (!old) requests.set(key, { sid, facet, color, opts, query, key, pin, core });
    else { if (pin) old.pin = true; if (core) old.core = true; }
  };
  const outside = (px, py, k, bottom) => px < -k || py < -k || px > viewSize.w + k || py > viewSize.h + bottom;
  for (const rows of [n.entities, n.remains || []]) {
    for (const r of rows) {
      if (r[0] < 0) continue;
      const [px, py] = entityScreen(r, n);
      if (outside(px, py, m + drift, m * 2 + drift)) continue;
      core = !outside(px, py, m, m * 2);
      const u = entityInfo(r, n);
      let layers = r[8] && r[8].length ? r[8] : u.sprite != null && u.sprite >= 0 ? [[u.sprite, 0, 0, 0]] : [];
      if (deltas) layers = layers.flatMap((l) => (deltas[l[0]] ? deltas[l[0]].map(([ps]) => [ps]) : [l]));
      const building = r[6] & 1, foundation = r[6] & 16;
      const lost = building && !foundation && r[1] ? 1 - r[5] : 0;
      const dmg = building && !foundation ? Math.min(5, Math.round(lost * 5)) : 0;
      const annex = TOWN_CENTER_PARTS.has(r[2]) && layerSplit !== false;
      const passes = annex ? ['main'] : split ? ['shadow', 'main'] : [null];
      const facet = r[7] || 0;
      for (const [sid] of layers) {
        for (const layer of passes) {
          const [color, pm] = stripColor(sid, r[1], layer, gpu);
          add(sid, facet, color, { dmg, layer, dir: !building, pm });
        }
      }
    }
  }
  for (const [, rows] of n.missile_track || []) {
    for (const m of rows) {
      const [px, py] = toScreen(m[3], m[4]);
      if (outside(px, py, m_ + drift, m_ + drift)) continue;
      core = !outside(px, py, m_, m_);
      for (const sid of layerSprites(m[7])) {
        for (const layer of split ? ['shadow', 'main'] : [null]) {
          const [color, pm] = stripColor(sid, m[1], layer, gpu);
          add(sid, m[6] || 0, color, { dmg: 0, layer, dir: true, pm }, true);
        }
      }
    }
  }
  const all = [...requests.values()];
  return { core: all.filter((r) => r.core), extra: all.filter((r) => !r.core) };
}

// While a heading's strip loads, a loaded strip of the same sprite at the nearest
// heading stands in (a new arrow or unit facing would otherwise be invisible for
// the fetch: 150-300 times a second at 8x in a battle). Only for heading-faced
// sprites: elsewhere the facet picks a variant (trees, cliffs), not a direction.
function nearestFacing(sid, facet, color, query) {
  for (let d = 1; d <= 16; d++) {
    for (const f of [facet - d, facet + d]) {
      // No wrap-around: the facing count (16, 32, ...) is the sprite's own.
      if (f < 0) continue;
      const e = spriteCache.get(`${sid}/${f}/${color}?${query}`);
      if (e && e.img) return e;
    }
  }
  return null;
}

function colorIndex(owner) {
  if (!owner) return -1;
  if (S.colorOverride[owner] != null) return S.colorOverride[owner] % 8;
  const p = S.match.players[owner];
  return p ? ((p.color_id % 8) + 8) % 8 : (owner - 1) % 8;
}

export function spritesOn() {
  return S.gameArt !== false && settings.gameGraphics !== false && S.camera.zoom >= 0.7;
}

// Particles (fire, smoke, dust, impacts). The game draws them from texture
// atlases named by each particle definition; frames are TexturePacker rects.
let particleDefs = null;
const atlases = new Map();
function particleDefByName(name) {
  if (particleDefs === null) {
    particleDefs = {};
    api('/api/particles').then((d) => { particleDefs = d || {}; }).catch(() => {});
  }
  return particleDefs[name];
}
function particleDef(defId) {
  const names = (S.map && S.map.particle_definitions) || [];
  return particleDefByName(names[defId]);
}
function atlas(path) {
  let a = atlases.get(path);
  if (a) return a;
  a = { img: null, meta: null };
  atlases.set(path, a);
  const q = encodeURIComponent(path);
  api(`/particle_atlas.json?path=${q}`).then((meta) => {
    a.meta = meta;
    const im = new Image();
    im.onload = () => { a.k = atlasScale(meta, im); a.img = im; };
    im.src = withAssetVersion(`/particle_atlas.png?path=${q}`);
  }).catch(() => {});
  return a;
}

// Particles are drawn ungraded on their own layer (fxBegin/fxComposite). Flames
// are emissive; other particles are lit like the ground (TERRAIN_LIGHT): a
// mangonel's smoke trail shows brighter than its atlas's own white. The lit atlas
// is one pixel pass, ~1 M pixels a frame (the fire atlas is 2048 x 4096); it
// shows unlit meanwhile.
let invWorkAt = 0;
function particleImage(a, lit) {
  // Lit (non-fire) particles: the atlas times the terrain light, mapped once.
  const L = lit ? TERRAIN_LIGHT : 1;
  if (L === 1) return a.img;
  const maps = a.maps || (a.maps = new Map());
  let m = maps.get(L);
  if (m && m.done) return m.c;
  if (!m) {
    const c = document.createElement('canvas');
    c.width = a.img.width; c.height = a.img.height;
    // brightness(L) is the same per-channel multiply and clamp as the pixel loop
    // below, done by the canvas in one draw instead of ~1M pixels per frame on
    // the main thread. The loop stays for a canvas without filter support.
    const fc = c.getContext('2d');
    if (typeof fc.filter === 'string') {
      fc.filter = `brightness(${L})`;
      fc.drawImage(a.img, 0, 0);
      fc.filter = 'none';
      maps.set(L, (m = { c, done: true }));
      return c;
    }
    const cx = c.getContext('2d', { willReadFrequently: true });
    cx.drawImage(a.img, 0, 0);
    m = { c, cx, data: cx.getImageData(0, 0, c.width, c.height), i: 0, done: false };
    maps.set(L, m);
  }
  const now = performance.now();
  if (now - invWorkAt < 12) return a.img; // one chunk per frame, over all atlases
  invWorkAt = now;
  const px = m.data.data;
  const end = Math.min(px.length, m.i + 4 * 1048576);
  for (let i = m.i; i < end; i += 4) {
    if (!px[i + 3]) continue;
    px[i] = Math.min(255, px[i] * L); px[i + 1] = Math.min(255, px[i + 1] * L); px[i + 2] = Math.min(255, px[i + 2] * L);
  }
  m.i = end;
  if (end < px.length) return a.img;
  m.cx.putImageData(m.data, 0, 0);
  m.data = null; m.done = true;
  return m.c;
}

// Image pixels per frame-rectangle unit. The server may send a smaller mip of
// a big atlas (meta.scale < 1), but an atlas without that mip arrives at full
// size with the same scale; trust the image: the full atlas is the power of
// two that holds every frame.
function atlasScale(meta, im) {
  let maxX = 1;
  for (const fr of meta.frames || []) {
    const r = fr.frame;
    maxX = Math.max(maxX, r.x + (fr.rotated ? r.h : r.w));
  }
  const full = 2 ** Math.ceil(Math.log2(maxX));
  return Math.min(1, im.naturalWidth / full);
}

// One atlas frame centred on its pivot at (px, py); s = screen px per atlas px.
function drawAtlasFrame(a, idx, px, py, s, rot, lit = false) {
  const fr = a.meta.frames[idx % a.meta.frames.length];
  if (!fr) return;
  const k = a.k || a.meta.scale || 1;
  const r = fr.frame, sss = fr.spriteSourceSize, src = fr.sourceSize;
  pctx.translate(px, py);
  if (rot) pctx.rotate((rot * Math.PI) / 180);
  // Place the trimmed frame inside its source rectangle, centred on the pivot.
  const ox = (sss.x - src.w / 2) * s, oy = (sss.y - src.h / 2) * s;
  if (fr.rotated) {
    // Stored rotated 90° clockwise in the atlas.
    pctx.rotate(-Math.PI / 2);
    fxDrawn = true; pctx.drawImage(particleImage(a, lit), r.x * k, r.y * k, r.h * k, r.w * k, -oy - sss.h * s, ox, sss.h * s, sss.w * s);
  } else {
    fxDrawn = true; pctx.drawImage(particleImage(a, lit), r.x * k, r.y * k, r.w * k, r.h * k, ox, oy, sss.w * s, sss.h * s);
  }
  pctx.setTransform(viewSize.dpr, 0, 0, viewSize.dpr, 0, 0);
}

function drawParticles() {
  const elapsed = Math.max(0, S.t - S.view.time) / 1000;
  const base = (S.camera.zoom * TW) / SPRITE_TILE;
  pctx.save();
  pctx.imageSmoothingEnabled = filt('particle');
  // The keyframe's particles, then those born after it (missile_track births:
  // [birth_t, ...row]) once their birth time has come.
  const born = [];
  for (const fr of S.view.missile_track || []) {
    if (fr[0] > S.t + 100) break;
    for (const b of fr[2] || []) {
      // Born after the keyframe (earlier ones are in its own particle list).
      if (b[0] > S.t || b[0] < S.view.time) continue;
      const row = b.slice(1);
      row[4] = (S.view.time - b[0]) / 1000; // so that age + elapsed = time since birth
      born.push(row);
    }
  }
  for (const p of born.length ? S.view.particles.concat(born) : S.view.particles) {
    const [x, y, zh, , age, dur, scale, alpha, , , , , defId, image, rot, offX, offY] = p;
    // The emitter's spot on its object's picture (x1 pixels): flames across a
    // burning roof, smoke out of the chimney.
    const [px0, py00] = toScreen(x, y);
    const px = px0 + (offX || 0) * base, py0 = py00 + (offY || 0) * base;
    if (px < -120 || px > viewSize.w + 120 || py0 < -120 || py0 > viewSize.h + 120) continue;
    const def = particleDef(defId);
    if (!def) continue;
    if (def.fire && fireOwnedTiles.has(`${Math.floor(x)},${Math.floor(y)}`)) continue; // drawn by the damage graphic
    const a = atlas(def.atlas);
    if (!a.img || !a.meta || !a.meta.frames.length) continue;
    const t = age + elapsed;
    if (t < 0 || (dur > 0 && def.type !== 'Loop' && t > dur)) continue; // not born yet / burnt out
    const idx = image >= def.first && image < def.first + def.count ? image
      : def.first + Math.floor(((dur > 0 ? t / dur : t / Math.max(0.05, def.duration)) * def.count)) % def.count;
    pctx.globalAlpha = Math.max(0, Math.min(1, alpha));
    // z is the particle's absolute height in elevation levels (as Entity.worldZ).
    drawAtlasFrame(a, idx, px, py0 - (zh || 0) * TH / 2 * S.camera.zoom, base * (scale || def.scale || 1), rot, !def.fire);
  }
  pctx.restore();
}

// -- damage graphics ------------------------------------------------------------------
// The catalog's damage_sprites (per master, by increasing pct) say what a
// building shows once that share of its hit points is gone: flames placed by a
// draw list (each naming a looping fire particle effect), or a replacement
// graphic (mode 2, e.g. broken walls). Without that data, buildings still burn
// at 25/50/75 % damage with flames spread over the footprint.

function damageGraphic(u, lost) {
  const list = u.damage_sprites;
  if (!list || !list.length || lost <= 0) return null;
  let best = null;
  for (const d of list) if (lost * 100 >= d.pct) best = d;
  return best;
}

/** Footprint tiles of buildings whose damage graphic draws their fire (this frame). */
const fireOwnedTiles = new Set();
/** Does the stream carry fire particles on this building's footprint? */
function streamedFire(r, u) {
  const v = S.view;
  if (!v || !v.particles || !v.particles.length) return false;
  if (!v._fireTiles) {
    v._fireTiles = new Set();
    for (const p of v.particles) {
      const def = particleDef(p[12]);
      if (def && def.fire) v._fireTiles.add(`${Math.floor(p[0])},${Math.floor(p[1])}`);
    }
  }
  if (!v._fireTiles.size) return false;
  const h = Math.ceil(Math.max(1, u.size || 1) / 2);
  for (let dy = -h; dy <= h; dy++) for (let dx = -h; dx <= h; dx++) {
    if (v._fireTiles.has(`${Math.floor(r[3]) + dx},${Math.floor(r[4]) + dy}`)) return true;
  }
  return false;
}

// -- projectiles -------------------------------------------------------------------------
// view.missile_track: [[t, rows], ...] per stream frame after the view's keyframe,
// rows [id, owner, master, x, y, z, facet, layers]. Drawn at the playback time,
// each projectile moved between the two samples around it.
function drawMissiles(track) {
  let i = 0;
  while (i + 1 < track.length && track[i + 1][0] <= S.t) i++;
  const [t0, rows0] = track[i];
  if (S.t < t0) return; // before the first sample after the keyframe
  drawTrails(track, i);
  const next = i + 1 < track.length ? track[i + 1] : null;
  const later = next ? new Map(next[1].map((q) => [q[0], q])) : null;
  const f = next ? Math.min(1, (S.t - t0) / Math.max(1, next[0] - t0)) : 0;
  const z = S.camera.zoom;
  for (const m of rows0) {
    const q = later && later.get(m[0]);
    const x = q ? m[3] + (q[3] - m[3]) * f : m[3], y = q ? m[4] + (q[4] - m[4]) * f : m[4];
    const h = q ? m[5] + (q[5] - m[5]) * f : m[5];
    const [px, py0] = toScreen(x, y);
    const py = py0 - h * TH / 2 * z;
    if (px < -60 || py < -60 || px > viewSize.w + 60 || py > viewSize.h + 60) continue;
    if (fogState() === 'standard' && !isVisible(x, y)) continue;
    drawSprites([m[0], m[1], m[2], x, y, 1, 0, m[6], m[7], 0], px, py);
  }
}

// Projectile trails (catalog unit .trail: the effect the game drops every
// `spacing` tiles of flight; never streamed). Each puff is placed along the
// recorded flight path and ages from the moment the projectile passed it.
// Against the game (40:00 mangonel volley, ffa6) one trail object shows as a
// continuous streak: TRAIL_PUFFS puffs per spacing, each at its own rotation
// (the effect's Rotation1..2 range is the full circle).
const TRAIL_PUFFS = 4;
function drawTrails(track, upto) {
  const paths = [], active = new Map();
  for (let k = 0; k <= upto; k++) {
    const [t, rows] = track[k], present = new Set();
    for (const m of rows) {
      present.add(m[0]);
      // New samples own their historical effective metadata; absent trail means
      // no trail, including an explicit ownMaster reset or missing prototype.
      const trail = m.length > 8 ? m[8].trail : unitInfo(m[2]).trail;
      if (!trail) { active.delete(m[0]); continue; }
      const incarnation = m.length > 8 ? m[8].incarnation : null;
      let p = active.get(m[0]);
      if (!p || p.incarnation !== incarnation || p.trail.particle !== trail.particle || p.trail.spacing !== trail.spacing) {
        p = { trail, pts: [], incarnation }; active.set(m[0], p); paths.push(p);
      }
      p.pts.push([t, m[3], m[4], m[5]]);
    }
    for (const id of active.keys()) if (!present.has(id)) active.delete(id);
  }
  if (!paths.length) return;
  // Up to where the projectile is drawn now (between the last sample and the next).
  const next = track[upto + 1];
  if (next && next[0] > track[upto][0]) {
    const f = Math.min(1, Math.max(0, (S.t - track[upto][0]) / (next[0] - track[upto][0])));
    for (const m of next[1]) {
      const p = active.get(m[0]);
      const trail = m.length > 8 ? m[8].trail : unitInfo(m[2]).trail;
      const incarnation = m.length > 8 ? m[8].incarnation : null;
      if (!p || !trail || p.incarnation !== incarnation
          || p.trail.particle !== trail.particle || p.trail.spacing !== trail.spacing) continue;
      const [, xa, ya, za] = p.pts[p.pts.length - 1];
      p.pts.push([S.t, xa + (m[3] - xa) * f, ya + (m[4] - ya) * f, za + (m[5] - za) * f]);
    }
  }
  const base = (S.camera.zoom * TW) / SPRITE_TILE;
  pctx.save();
  pctx.imageSmoothingEnabled = filt('particle');
  for (const { trail, pts } of paths) {
    const def = particleDefByName(trail.particle);
    if (!def || pts.length < 2) continue;
    const a = atlas(def.atlas);
    if (!a.img || !a.meta || !a.meta.frames.length) continue;
    const life = Math.max(0.05, def.duration || 1) * 1000;
    const step = trail.spacing / TRAIL_PUFFS;
    let carry = 0, n = 0;
    for (let k = 1; k < pts.length; k++) {
      const [ta, xa, ya, za] = pts[k - 1], [tb, xb, yb, zb] = pts[k];
      const len = Math.hypot(xb - xa, yb - ya);
      for (let d = step - carry; d <= len; d += step) {
        n++;
        const f = len ? d / len : 0;
        const tp = ta + (tb - ta) * f, age = S.t - tp;
        if (age < 0 || age > life) continue;
        const x = xa + (xb - xa) * f, y = ya + (yb - ya) * f, z = za + (zb - za) * f;
        const [px, py0] = toScreen(x, y);
        const py = py0 - z * TH / 2 * S.camera.zoom;
        if (px < -60 || py < -60 || px > viewSize.w + 60 || py > viewSize.h + 60) continue;
        const u = age / life;
        pctx.globalAlpha = Math.max(0, (def.alpha_start ?? 1) + ((def.alpha_end ?? 1) - (def.alpha_start ?? 1)) * u);
        const idx = def.first + Math.min(def.count - 1, Math.floor(u * def.count));
        drawAtlasFrame(a, idx, px, py, base * (def.scale || 1), (n * 137.5) % 360, !def.fire);
      }
      carry = (carry + len) % step;
    }
  }
  pctx.restore();
}

// -- units behind buildings ------------------------------------------------------------
// The game outlines a unit in its player colour where a building in front of it
// hides it (its sprite shader's outline pass). Every sprite drawn this frame is
// logged (main layer only); afterwards each player unit overlapped by a building
// drawn later gets its outline, cut to that building's pixels.
const drawLog = [];
let logEntry = null;
function logPart(r, img, sx, sw, sh, dx, dy, dw, dh) {
  if (!logEntry || logEntry.r !== r) {
    logEntry = { r, parts: [], x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    drawLog.push(logEntry);
  }
  logEntry.parts.push([img, sx, sw, sh, dx, dy, dw, dh]);
  logEntry.x0 = Math.min(logEntry.x0, dx); logEntry.y0 = Math.min(logEntry.y0, dy);
  logEntry.x1 = Math.max(logEntry.x1, dx + dw); logEntry.y1 = Math.max(logEntry.y1, dy + dh);
}
let outlineA = null, outlineB = null, outlineC = null;
const outlineCache = new OutlineCache();
const outlinePositions = new Map();
let outlineCamera = '';
export function outlineMemory() {
  return { bytes: outlineCache.bytes, entries: outlineCache.entries.size, hits: outlineCache.hits, misses: outlineCache.misses };
}
function scratch2d(c, w, h) {
  if (!c) { c = document.createElement('canvas'); c.width = w; c.height = h; }
  if (c.width < w || c.height < h) { c.width = Math.max(c.width, w); c.height = Math.max(c.height, h); }
  const g = c.getContext('2d');
  // Reuse the allocation, but bound Porter-Duff operations to this unit's
  // active rectangle. source-in/destination-in otherwise clear the entire
  // backing store, including space retained for a previous, larger sprite.
  g.restore();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalCompositeOperation = 'source-over';
  g.save();
  g.beginPath(); g.rect(0, 0, w, h); g.clip();
  g.clearRect(0, 0, w, h);
  return c;
}
function paintParts(g, entry, ox, oy, k) {
  for (const [img, sx, sw, sh, dx, dy, dw, dh] of entry.parts) g.drawImage(img, sx, 0, sw, sh, (dx - ox) * k, (dy - oy) * k, dw * k, dh * k);
}
function drawOccludedOutlines() {
  const log = drawLog.slice();
  drawLog.length = 0; logEntry = null;
  if (S.camera.zoom < 0.9 || settings.unitOutlines === false) return;
  const k = viewSize.dpr;
  const camera = `${S.camera.x}|${S.camera.y}|${S.camera.zoom}|${k}`;
  const stillCamera = camera === outlineCamera;
  outlineCamera = camera;
  if (outlinePositions.size > 2048) outlinePositions.clear();
  // Buildings in a screen grid, so each unit looks only at the buildings near it
  // (every unit against every later entry was quadratic in a large battle).
  const CELL = 128, grid = new Map();
  for (let j = 0; j < log.length; j++) {
    const b = log[j];
    if (!(b.r[6] & 1)) continue;
    for (let gy = Math.floor(b.y0 / CELL); gy <= Math.floor(b.y1 / CELL); gy++) {
      for (let gx = Math.floor(b.x0 / CELL); gx <= Math.floor(b.x1 / CELL); gx++) {
        const key = gx * 65536 + gy;
        let cell = grid.get(key);
        if (!cell) grid.set(key, (cell = []));
        cell.push(j);
      }
    }
  }
  for (let i = 0; i < log.length; i++) {
    const u = log[i];
    if (!(u.r[6] & 4) || !u.r[1]) continue; // player units
    let found = null;
    for (let gy = Math.floor(u.y0 / CELL); gy <= Math.floor(u.y1 / CELL); gy++) {
      for (let gx = Math.floor(u.x0 / CELL); gx <= Math.floor(u.x1 / CELL); gx++) {
        for (const j of grid.get(gx * 65536 + gy) || []) {
          const b = log[j];
          if (j <= i || b.x1 <= u.x0 || b.x0 >= u.x1 || b.y1 <= u.y0 || b.y0 >= u.y1) continue;
          (found ||= new Set()).add(j);
        }
      }
    }
    // Drawn after the unit, in draw order (as the full scan found them).
    const occ = found ? [...found].sort((a, b) => a - b).map((j) => log[j]) : null;
    if (!occ) continue;
    const ox = Math.floor(u.x0) - 2, oy = Math.floor(u.y0) - 2;
    const w = Math.ceil((u.x1 - ox + 2) * k), h = Math.ceil((u.y1 - oy + 2) * k);
    if (w > 1600 || h > 1600) continue;
    const position = outlinePositions.get(u.r[0]);
    const still = stillCamera && position && position.x === u.r[3] && position.y === u.r[4];
    if (position) { position.x = u.r[3]; position.y = u.r[4]; }
    else outlinePositions.set(u.r[0], { x: u.r[3], y: u.r[4] });
    const color = playerColor(u.r[1]);
    const key = still ? outlineCache.key(u.parts, color, ox, oy, k, w, h) : null;
    const ring = key ? outlineCache.get(key) : null;
    // A: the unit's silhouette in its colour; B: A spread by a pixel, minus A
    // (the outline ring); C: the occluding buildings. B kept where C covers it.
    outlineB = scratch2d(outlineB, w, h); outlineC = scratch2d(outlineC, w, h);
    const gb = outlineB.getContext('2d'), gc = outlineC.getContext('2d');
    if (ring) gb.drawImage(ring, 0, 0);
    else {
      outlineA = scratch2d(outlineA, w, h);
      const ga = outlineA.getContext('2d');
      paintParts(ga, u, ox, oy, k);
      ga.globalCompositeOperation = 'source-in'; ga.fillStyle = color; ga.fillRect(0, 0, w, h);
      const d = Math.max(1, Math.round(k));
      for (const [dx, dy] of [[d, 0], [-d, 0], [0, d], [0, -d]]) gb.drawImage(outlineA, 0, 0, w, h, dx, dy, w, h);
      gb.globalCompositeOperation = 'destination-out'; gb.drawImage(outlineA, 0, 0, w, h, 0, 0, w, h);
      if (key) {
        const raster = document.createElement('canvas'); raster.width = w; raster.height = h;
        raster.getContext('2d').drawImage(outlineB, 0, 0, w, h, 0, 0, w, h);
        outlineCache.set(key, raster, w * h * 4);
      }
    }
    for (const b of occ) paintParts(gc, b, ox, oy, k);
    gb.globalCompositeOperation = 'destination-in';
    gb.drawImage(outlineC, 0, 0, w, h, 0, 0, w, h);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(outlineB, 0, 0, w, h, ox * k, oy * k, w, h);
    ctx.restore();
  }
}

const FALLBACK_FIRES = [null, ['fire_small_left', 2], ['fire_medium_left', 4], ['fire_large_left', 6]];
const fallbackParts = new Map();
function fallbackFlames(r, level, size) {
  const key = `${r[2]}/${level}/${r[0] % 7}`;
  let parts = fallbackParts.get(key);
  if (parts) return parts;
  const [name, n] = FALLBACK_FIRES[level];
  parts = [];
  let h = (r[0] * 2654435761) >>> 0;
  const rnd = () => { h = (h * 1103515245 + 12345) >>> 0; return (h >>> 8) / 16777216; };
  for (let i = 0; i < n; i++) {
    // A point inside the footprint diamond, lifted towards the roof (x1 pixels).
    const a = (rnd() - 0.5) * size * 0.7, b = (rnd() - 0.5) * size * 0.7;
    parts.push([-1, name, Math.round((a + b) * 48), Math.round((a - b) * 24 - rnd() * size * 28)]);
  }
  fallbackParts.set(key, parts);
  return parts;
}

const FLAME_SCALE = 1; // the definition's own Scale, as the game draws it
// Flames are drawn after every entity, like the game's particles, so a
// building's own annex parts (town centre) never cover its fire.
const flameQueue = [];
// One flame per emitter (x1-pixel offset, phase, size): two out-of-phase puffs
// each showed two to four times the game's count on a burning building.
const FLAME_PUFFS = [[0, 0, 0, 1]];

function drawFlames(parts, r, px, py) {
  const s = (S.camera.zoom * TW) / SPRITE_TILE;
  const t = S.t / 1000;
  pctx.save();
  pctx.imageSmoothingEnabled = filt('unitDamage');
  parts.forEach(([sid, particle, ox, oy], i) => {
    const x = px + ox * s, y = py + oy * s;
    const def = particle && particleDefByName(particle);
    if (def) {
      const a = atlas(def.atlas);
      if (!a.img || !a.meta || !a.meta.frames.length) return;
      const phase = ((r[0] * 7 + i * 13) % 17) / 17;
      const k = s * (def.scale || 1) * FLAME_SCALE;
      // Each emitter loops through lives of Duration1-Duration2 seconds, fading in
      // and out at either end (the definition's StartMode / StopMode): at any
      // moment some flames are faint, as in the game.
      const [l1, l2] = def.life || [0, 0];
      let fade = 1;
      if (l1 > 0) {
        const life = l1 + (l2 - l1) * (((r[0] * 31 + i * 17) % 23) / 23);
        const age = (t + phase * life) % life;
        if (def.fade_in > 0 && age < def.fade_in) fade = age / def.fade_in;
        else if (def.fade_out > 0 && age > life - def.fade_out) fade = (life - age) / def.fade_out;
      }
      for (const [dx, dy, ph, f] of FLAME_PUFFS) {
        const idx = def.first + Math.floor(((t / Math.max(0.05, def.duration)) + phase + ph) * def.count) % def.count;
        pctx.globalAlpha = Math.max(0, Math.min(1, fade));
        drawAtlasFrame(a, idx, x + dx * s, y + dy * s, k * f, 0, !def.fire);
      }
      pctx.globalAlpha = 1;
    } else if (sid >= 0) {
      const e = spriteStrip(sid, 0, -1);
      if (!e || !e.img || !e.meta) return;
      const m = e.meta, k = (S.camera.zoom * TW) / (e.tile || SPRITE_TILE);
      const f = Math.floor(t / Math.max(0.02, m.duration || 0.05) / m.step) % m.n;
      fxDrawn = true; pctx.drawImage(e.img, f * m.cw, 0, m.cw, m.ch, x - m.ax * k, y - m.ay * k, m.cw * k, m.ch * k);
    }
  });
  pctx.restore();
}

// -- foundations ------------------------------------------------------------------------

/** Construction progress 0..1 of a foundation row (hit points grow with it). */
export function constructionPct(r) {
  const c = S.view && S.view.construction;
  const v = c ? c[r[0]] : undefined;
  return v != null ? v : Math.max(0, Math.min(1, r[5] || 0));
}

function progressBar(px, py, w, frac) {
  ctx.fillStyle = 'rgba(0,0,0,.7)';
  ctx.fillRect(px - w / 2, py, w, 3);
  ctx.fillStyle = '#6fb6ea';
  ctx.fillRect(px - w / 2, py, w * frac, 3);
}

// Per entity: the sprite frames drawn last (stale-while-loading), and counters
// for the performance view.
const lastDrawn = new SpriteHistory();
/** Time per frame spent in each part of draw() (summed; the perf view averages). */
export const drawTimes = { ground: 0, entities: 0, outlines: 0, masks: 0, readAhead: 0, missiles: 0, fxClear: 0, effects: 0, post: 0, n: 0, paints: 0, patches: 0, trees: 0, chunks: 0 };
export const spriteStats = { stale: 0, missing: 0, standIn: 0, missingMasters: new Map() };
let countingDraw = false; // spriteStats.standIn counts on-screen draws only, not prefetching
export function pruneLastDrawn() {
  lastDrawn.prune(S.t);
}

// Sprite pictures go to the GPU batch (sprite-gl.js) while one is open for the
// context being drawn on (gpuTarget), else straight to the 2D context. With the
// batch the picture is three stacked canvases: this one (ground, selection
// rings, spy fog; graded here), the sprite canvas (graded in its shader) and the
// overlay canvas (bars, outlines, flames, range circles, particles, fog).
let gpuTarget = null;
const gpuBars = [];
let topCanvas = null, topCtx = null, layered = false;
// Bloom, FXAA and the colour channels filter the whole frame: with any of them on,
// sprites stay on the 2D canvas.
function gpuLayers() {
  if (settings.gpuSprites === false) return false;
  const p = postExtra();
  if (p.fxaa || (p.bloomEnable && Number(p.bloomBrightness) > 0)) return false;
  return [p.red, p.green, p.blue, p.alpha].every((v) => num(v, 1) === 1);
}
function overlayBegin() {
  const gl = SG.canvasAfter(canvas);
  if (!topCanvas) {
    topCanvas = document.createElement('canvas');
    topCanvas.id = 'world-top';
    topCtx = topCanvas.getContext('2d');
  }
  if (!topCanvas.parentNode) gl.after(topCanvas);
  if (topCanvas.width !== canvas.width || topCanvas.height !== canvas.height) { topCanvas.width = canvas.width; topCanvas.height = canvas.height; }
  // The picture settings (CSS filters on the world canvas) apply to every layer.
  if (gl.style.filter !== canvas.style.filter) { gl.style.filter = canvas.style.filter; topCanvas.style.filter = canvas.style.filter; }
  topCanvas.classList.add('on');
  topCtx.setTransform(1, 0, 0, 1, 0, 0);
  topCtx.clearRect(0, 0, topCanvas.width, topCanvas.height);
  topCtx.setTransform(viewSize.dpr, 0, 0, viewSize.dpr, 0, 0);
  topCtx.globalAlpha = 1;
  topCtx.globalCompositeOperation = 'source-over';
  return topCtx;
}
function layersOff() {
  SG.hide();
  if (topCanvas) topCanvas.classList.remove('on');
}
/** The haze and grade the sprite shader applies (as hazePass and gradePass). */
function spriteLook() {
  const p = activeGrade();
  let haze = null;
  if (p && settings.distanceHaze !== false && Array.isArray(p.distance_fog_color) && num(p.distance_fog_visible_intensity, 0) > 0) {
    const k = num(p.distance_fog_visible_intensity, 0);
    haze = p.distance_fog_color.map((v) => Math.round(Math.max(0, Math.min(1, v * k)) * 255) / 255);
  }
  // Units behind buildings (as drawOccludedOutlines: from zoom 0.9, a device pixel wide).
  const outline = S.camera.zoom >= 0.9 && settings.unitOutlines !== false ? Math.max(1, Math.round(viewSize.dpr)) : 0;
  return { haze, grade: gradeParams(), outline };
}
function blit(img, sx, sw, sh, dx, dy, dw, dh, smooth, role = SG.ROLE_NONE, rgb = 0, tint = -1, maskRows = 0) {
  if (gpuTarget === ctx && SG.draw(img, sx, sw, sh, dx, dy, dw, dh, ctx.globalAlpha, smooth, role, rgb, tint, maskRows)) return;
  if (maskRows) return; // an uncoloured strip would draw in the wrong colour
  ctx.imageSmoothingEnabled = smooth;
  ctx.drawImage(img, sx, 0, sw, sh, dx, dy, dw, dh);
}
// The outline pass's part for an entity: a player unit it outlines (the 2D pass's
// rule, drawOccludedOutlines: flag 4), a building that hides units, or neither.
function outlineRole(r) {
  if (r[6] & 1) return SG.ROLE_OCCLUDER;
  return r[6] & 4 && r[1] ? SG.ROLE_OUTLINED : SG.ROLE_NONE;
}
const rgbCache = new Map();
function packedColor(owner) {
  const hex = playerColor(owner);
  let v = rgbCache.get(hex);
  if (v === undefined) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex);
    v = m ? parseInt(m[1], 16) : 0xffffff;
    rgbCache.set(hex, v);
  }
  return v;
}
export function gpuSpriteStats() { return { ...SG.stats, on: !!(settings.gpuSprites !== false && SG.available()), error: SG.initError, memory: SG.memory() }; }

// Draw one entity's sprite layers; false if nothing could be drawn yet. After a
// draw, spriteTop is the screen y of the picture's top edge (null when the game
// has no picture for it: nothing to hang a health bar on).
let spriteTop = null;
function drawSprites(r, px, py) {
  spriteTop = null;
  let layers = r[8];
  const u = entityInfo(r);
  if (!layers || !layers.length) {
    // No active sprite in the stream (e.g. walls): the master's standing sprite.
    if (u.sprite == null || u.sprite < 0) return false;
    layers = [[u.sprite, 0, 0, 0]];
  }
  // Composite sprites (catalog sprite_deltas): the game streams the root only, its
  // draw list adds the parts (a palisade wall's body under its flag).
  const deltas = S.catalog && S.catalog.sprite_deltas;
  if (deltas && layers.some((l) => deltas[l[0]])) {
    layers = layers.flatMap(([sid, frame, ox, oy]) => {
      const parts = deltas[sid];
      return parts ? parts.map(([ps, dx, dy]) => [ps, frame, ox + dx, oy + dy]) : [[sid, frame, ox, oy]];
    });
  }
  const flags = r[6];
  const building = flags & 1, foundation = flags & 16;
  const lost = building && !foundation && r[1] ? 1 - r[5] : 0;
  const level = lost >= 0.75 ? 3 : lost >= 0.5 ? 2 : lost >= 0.25 ? 1 : 0;
  const gpu = gpuTarget === ctx;
  const dg = damageGraphic(u, lost);
  let replaced = false;
  if (dg && dg.mode === 2 && dg.sprite >= 0) {
    const [dc, dpm] = stripColor(dg.sprite, r[1], null, gpu);
    const e = spriteStrip(dg.sprite, r[7] || 0, dc, { pm: dpm });
    if (e && e.img && e.meta) { layers = [[dg.sprite, 0, 0, 0]]; replaced = true; }
  }
  const facet = r[7] || 0;
  // The pose's own snapshot is the animation clock's origin (column 11: a pose the
  // interpolator took from the next snapshot, which may still lie ahead).
  const elapsed = S.view ? S.t - (r[11] != null ? r[11] : S.view.time) : 0;
  const tint = gpu ? spriteTint(r[1]) : -1;
  const role = gpu ? outlineRole(r) : SG.ROLE_NONE, rgb = role === SG.ROLE_OUTLINED ? packedColor(r[1]) : 0;
  if (gpu) SG.nextGroup();
  // Unhammered foundations are translucent, like the game's placement ghost.
  const ghost = foundation && constructionPct(r) <= 0.001;
  const split = layerSplit !== false && filt('unitShadow') !== filt('unitColor');
  // Shading steps of a fifth of the hit points (sprites.DAMAGE_LEVELS).
  const dmg = building && !replaced && !foundation ? Math.min(5, Math.round(lost * 5)) : 0;
  let drew = false, failed = 0, pendingMain = false;
  let drawn = [];
  // No save()/restore() per entity (a canvas state flush each, the costliest
  // call at 8x): only the alpha and the smoothing flag change, set directly.
  if (ghost) ctx.globalAlpha = 0.45;
  for (const [sid, frame, ox, oy] of layers) {
    // Town centre annex parts repeat the main part's shadow; stacked, the
    // half-transparent shadows go black, so they draw their graphic only.
    const annex = TOWN_CENTER_PARTS.has(r[2]) && layerSplit !== false;
    const passes = annex ? [['main', 'unitColor']]
      : split ? [['shadow', 'unitShadow'], ['main', 'unitColor']] : [[null, 'unitColor']];
    for (const [layer, filterKey] of passes) {
      const [color, pm] = stripColor(sid, r[1], layer, gpu);
      const e = spriteStrip(sid, facet, color, { dmg, layer, dir: !building, pm });
      if (e && e.failed && !e.retryAt) { if (layer !== 'shadow') failed++; continue; }
      if (!e || !e.img || !e.meta) { if (layer !== 'shadow') pendingMain = true; continue; }
      const m = e.meta;
      const perMs = Math.max(1, (m.duration || 0.1) * 1000);
      const fi = Math.floor((frame + elapsed / perMs) / m.step);
      // Remains play once; static pieces use their facet, animations loop.
      const f = !m.duration && m.n > 1 ? facet % m.n : flags & 256 ? Math.max(0, Math.min(m.n - 1, fi)) : ((fi % m.n) + m.n) % m.n;
      if (m.pm && !gpu) continue;
      drawn.push([e, f, ox, oy, filterKey]);
    }
  }
  const generation = S.session?.generation;
  const previous = pendingMain && lastDrawn.get(r, generation, S.t);
  if (previous) { drawn = previous; spriteStats.stale++; }
  for (const [e, f, ox, oy, filterKey] of drawn) {
    const m = e.meta, s = (S.camera.zoom * TW) / (e.tile || SPRITE_TILE);
    if (m.pm && !gpu) continue;
    const main = filterKey !== 'unitShadow';
    blit(e.img, f * m.cw, m.cw, m.ch, px + (ox - m.ax) * s, py + (oy - m.ay) * s, m.cw * s, m.ch * s, filt(filterKey), main ? role : SG.ROLE_NONE, rgb, m.pm ? tint : -1, m.pm ? m.ch : 0);
    if (main) {
      drew = true; spriteTop = Math.min(spriteTop ?? Infinity, py + (oy - m.ay) * s);
      if (!gpu) logPart(r, e.img, f * m.cw, m.cw, m.ch, px + (ox - m.ax) * s, py + (oy - m.ay) * s, m.cw * s, m.ch * s);
    }
  }
  // Do not replace a complete pose with a half-loaded building or animation.
  if (drew && !pendingMain) lastDrawn.remember(r, generation, S.t, drawn);
  if (!drew && !failed) {
    spriteStats.missing++;
    spriteStats.missingMasters.set(r[2], (spriteStats.missingMasters.get(r[2]) || 0) + 1);
  }
  // Permanently empty game graphics have no visible body or health-bar anchor.
  if (!drew && failed && !pendingMain) drew = true;
  if (ghost) ctx.globalAlpha = 1;
  // A damage graphic's flames are the whole fire (a mill at 41 % showed six in the
  // game; the stream carried one of them): they are drawn, and the streamed fire
  // particles on the building are not (fireOwnedTiles), so none burns twice. A
  // building without a damage graphic burns with the streamed particles, else
  // with stand-in flames.
  if (drew && level && !replaced) {
    if (dg) {
      // Mode 0/1 graphics draw their own sprite over the building, then any flames.
      const parts = dg.sprite >= 0 && dg.mode !== 2 ? [[dg.sprite, '', 0, 0], ...(dg.parts || [])] : dg.parts || [];
      if (parts.length) {
        flameQueue.push([parts, r, px, py]);
        const h = Math.ceil(Math.max(1, u.size || 1) / 2);
        for (let dy = -h; dy <= h; dy++) for (let dx = -h; dx <= h; dx++) fireOwnedTiles.add(`${Math.floor(r[3]) + dx},${Math.floor(r[4]) + dy}`);
      }
    }
    // Town centre annex parts share the main part's fire.
    else if (!u.damage_sprites && !TOWN_CENTER_PARTS.has(r[2]) && !streamedFire(r, u)) flameQueue.push([fallbackFlames(r, level, Math.max(1, u.size || 1)), r, px, py]);
  }
  return drew;
}
let fogCanvas = null, fogKey = '', fogSmall = null;
let mapW = 0, mapH = 0;
const imgCache = new Map();
let entityRows = [];   // interpolated rows used for drawing and picking
let groundClip = null; // screen rectangle while updating part of the cached ground
const viewSize = { w: 0, h: 0, dpr: 1 };

export function resize() {
  const dpr = window.devicePixelRatio || 1;
  viewSize.w = window.innerWidth; viewSize.h = window.innerHeight; viewSize.dpr = dpr;
  canvas.width = Math.round(viewSize.w * dpr);
  canvas.height = Math.round(viewSize.h * dpr);
  resizeMinimap();
}

export function resizeMinimap() {
  const dpr = window.devicePixelRatio || 1, mr = mini.getBoundingClientRect();
  const width = Math.round(mr.width * dpr), height = Math.round(mr.height * dpr);
  if (mini.width !== width) mini.width = width;
  if (mini.height !== height) mini.height = height;
}

function img(src) {
  if (!src) return null;
  let im = imgCache.get(src);
  if (!im) {
    im = new Image();
    im.src = src;
    im.onerror = () => { im.failed = true; };
    imgCache.set(src, im);
  }
  return im.complete && !im.failed && im.naturalWidth ? im : null;
}

// -- projection ----------------------------------------------------------------

export function toScreen(x, y) {
  const c = S.camera, z = c.zoom;
  const px = ((x + y) - (c.x + c.y)) * TW / 2 * z + viewSize.w / 2;
  const py = ((y - x) - (c.y - c.x)) * TH / 2 * z + viewSize.h / 2;
  return [px, py];
}

export function toWorld(px, py) {
  const c = S.camera, z = c.zoom;
  const a = (px - viewSize.w / 2) / (TW / 2 * z) + (c.x + c.y);  // x + y
  const b = (py - viewSize.h / 2) / (TH / 2 * z) + (c.y - c.x);  // y - x
  return [(a - b) / 2, (a + b) / 2];
}

// -- map layers ------------------------------------------------------------------

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function setMap(map) {
  if (!map || !map.width) return;
  S.map = map;
  mapW = map.width; mapH = map.height;
  const terrain = Uint8Array.from(atob(map.terrain), (c) => c.charCodeAt(0));
  const elev = Uint8Array.from(atob(map.elevation), (c) => c.charCodeAt(0));
  map._terrain = terrain; map._elev = elev;
  const shapes = map.shapes ? Uint8Array.from(atob(map.shapes), (c) => c.charCodeAt(0)) : null;
  TG.setHeights(elev, shapes, mapW, mapH);
  // The layer terrain the game draws over each tile through its overlay mask (255: none).
  map._layers = map.layers ? Uint8Array.from(atob(map.layers), (c) => c.charCodeAt(0)) : new Uint8Array(terrain.length).fill(255);
  terrainPatterns.clear(); chunkCache.clear(); chunkGen++;
  if (TG.available()) TG.dropChunks();
  viewTerrainCanvas = null; viewTerrainImage = null; textureAvg.clear();
  biomeAt = 0;
  const colors = map.terrain_colors.map(hexToRgb);
  buildTerrain(terrain, elev, colors);
  buildViewTerrain();
  buildFlatMap();
  if (S.camera.x === 60 && S.camera.y === 60) {
    S.camera.x = mapW / 2; S.camera.y = mapH / 2;
    S.camera.zoom = Math.min(viewSize.w / ((mapW + mapH) * TW / 2), 1.2);
  }
}

let terrainImage = null, terrainColors = null;
// The zoomed-out main view's flat layer (see rasterTerrain): built once every
// terrain texture and overlay mask on the map has loaded; until then the
// minimap-palette layer stands in.
let viewTerrainCanvas = null, viewTerrainImage = null, viewColors = null, viewMaskMean = null;
const textureAvg = new Map(), maskAvg = new Map();
function mapTerrainIds() {
  const ids = new Set(S.map._terrain);
  for (const l of S.map._layers) if (l !== 255) ids.add(l);
  return [...ids];
}
function buildViewTerrain() {
  if (viewTerrainCanvas || !terrainCanvas || !S.map || !S.map.terrain_textures) return;
  const ids = mapTerrainIds();
  for (const i of ids) {
    const p = terrainPattern(i);
    const tex = S.map.terrain_textures[i];
    if (!p || (typeof p !== 'string' && !textureAvg.has(i)) || terrainMask(tex && tex[2]) === null) return; // loading
  }
  viewColors = terrainColors.map((c, i) => textureAvg.get(i) || c);
  viewMaskMean = S.map.terrain_textures.map((tex) => (tex && tex[2] && maskAvg.has(tex[2]) ? maskAvg.get(tex[2]) : 1));
  const c = document.createElement('canvas');
  c.width = terrainCanvas.width; c.height = terrainCanvas.height;
  viewTerrainImage = c.getContext('2d').createImageData(c.width, c.height);
  rasterTerrain(0, 0, c.width, c.height, true);
  c.getContext('2d').putImageData(viewTerrainImage, 0, 0);
  viewTerrainCanvas = c;
  buildFlatMap();
  terrainGen++;
}
/** Mean colour of an image (its 1x1 downscale). */
function meanColor(im) {
  const c = document.createElement('canvas');
  c.width = c.height = 8;
  const g = c.getContext('2d');
  g.drawImage(im, 0, 0, 8, 8);
  const d = g.getImageData(0, 0, 8, 8).data;
  let r = 0, gg = 0, b = 0;
  for (let k = 0; k < d.length; k += 4) { r += d[k]; gg += d[k + 1]; b += d[k + 2]; }
  const n = d.length / 4;
  return [r / n, gg / n, b / n];
}

function buildTerrain(terrain, elev, colors) {
  const w = (mapW + mapH) * TERRAIN_TW / 2, h = (mapW + mapH) * TERRAIN_TH / 2;
  terrainCanvas = document.createElement('canvas');
  terrainCanvas.width = w; terrainCanvas.height = h;
  const tc = terrainCanvas.getContext('2d');
  terrainImage = tc.createImageData(w, h);
  terrainColors = colors;
  rasterTerrain(0, 0, w, h);
  tc.putImageData(terrainImage, 0, 0);
  buildMiniTerrain();
}

// The flat-colour ground for the height-mapped (WebGL) view: one pixel per tile in
// map space, the same colours and shading as rasterTerrain.
let flatMap = null, flatMapImage = null;
function buildFlatMap() {
  if (!S.map || !mapW) return;
  if (!flatMap || flatMap.width !== mapW || flatMap.height !== mapH) {
    flatMap = document.createElement('canvas');
    flatMap.width = mapW; flatMap.height = mapH;
    flatMapImage = flatMap.getContext('2d').createImageData(mapW, mapH);
  }
  for (let i = 0; i < mapW * mapH; i++) flatPixel(i);
  flatMap.getContext('2d').putImageData(flatMapImage, 0, 0);
  flatMap._dirty = true;
}
function flatPixel(i) {
  const terrain = S.map._terrain, elev = S.map._elev, layers = S.map._layers;
  const view = !!viewColors;
  const colors = view ? viewColors : terrainColors;
  let c = colors[terrain[i]] || [60, 90, 40];
  if (view && layers[i] !== 255 && colors[layers[i]]) {
    const l = colors[layers[i]], m = viewMaskMean[layers[i]] ?? 1;
    c = [c[0] + (l[0] - c[0]) * m, c[1] + (l[1] - c[1]) * m, c[2] + (l[2] - c[2]) * m];
  }
  const x = i % mapW, y = Math.floor(i / mapW), e = elev[i];
  const dr = (y + 1 < mapH ? elev[i + mapW] : e) - (y > 0 ? elev[i - mapW] : e);
  const shade = 1 + dr * 0.1 + e * 0.02;
  const d = flatMapImage.data, k = i * 4;
  d[k] = Math.min(255, c[0] * shade); d[k + 1] = Math.min(255, c[1] * shade); d[k + 2] = Math.min(255, c[2] * shade); d[k + 3] = 255;
}

/** Ground height (levels) under an entity row; birds and projectiles carry their own. */
function liftOf(r, view = S.view) {
  const air = view && view.air && view.air[r[0]];
  return air != null ? air : TG.heightAt(r[3], r[4]);
}
/** Screen position of an entity row, lifted by the ground (or its flying) height. */
export function entityScreen(r, view = S.view) {
  const [px, py] = toScreen(r[3], r[4]);
  return [px, py - liftOf(r, view) * TH / 2 * S.camera.zoom];
}
/** Screen position of a ground point (x, y), on the terrain surface. */
function groundScreen(x, y) {
  const [px, py] = toScreen(x, y);
  return [px, py - TG.heightAt(x, y) * TH / 2 * S.camera.zoom];
}

// Paint the flat-colour terrain pixels of one rectangle of a terrain image: the
// game's minimap palette (terrainImage), or with ``view`` the average colour of
// each texture blended with its layer terrain (viewTerrainImage: the zoomed-out
// main view, so zooming out keeps the ground's colours).
function rasterTerrain(x0, y0, x1, y1, view = false) {
  const terrain = S.map._terrain, elev = S.map._elev, layers = S.map._layers;
  const img = view ? viewTerrainImage : terrainImage;
  const colors = view ? viewColors : terrainColors;
  const w = img.width, d = img.data;
  // Rasterise: for every output pixel, find its tile (inverse projection).
  const ox = 0, oy = mapW * TERRAIN_TH / 2;
  for (let py = Math.max(0, y0); py < Math.min(img.height, y1); py++) {
    for (let px = Math.max(0, x0); px < Math.min(w, x1); px++) {
      const a = (px - ox) / (TERRAIN_TW / 2);
      const b = (py - oy) / (TERRAIN_TH / 2);
      const x = Math.floor((a - b) / 2), y = Math.floor((a + b) / 2);
      if (x < 0 || y < 0 || x >= mapW || y >= mapH) continue;
      const i = y * mapW + x;
      let c = colors[terrain[i]] || [60, 90, 40];
      if (view && layers[i] !== 255 && colors[layers[i]]) {
        const l = colors[layers[i]], m = viewMaskMean[layers[i]] ?? 1;
        c = [c[0] + (l[0] - c[0]) * m, c[1] + (l[1] - c[1]) * m, c[2] + (l[2] - c[2]) * m];
      }
      const e = elev[i];
      // Lit from the upper left, as the textured terrain (see chunkCanvas).
      const dr = (y + 1 < mapH ? elev[i + mapW] : e) - (y > 0 ? elev[i - mapW] : e);
      const shade = 1 + dr * 0.1 + e * 0.02;
      const k = (py * w + px) * 4;
      d[k] = Math.min(255, c[0] * shade); d[k + 1] = Math.min(255, c[1] * shade);
      d[k + 2] = Math.min(255, c[2] * shade); d[k + 3] = 255;
    }
  }
}

// -- live terrain -----------------------------------------------------------------
// The game repaints tiles as the match goes on (farms, pastures, foundations, the
// dirt under buildings): the view names the terrain snapshot in force and only the
// changed tiles are repainted (flat layer, minimap, textured chunks).
let terrainT = -1, terrainPending = false, terrainGen = 0, terrainAt = 0;
export async function refreshTerrain(t) {
  if (!S.map || !S.map._terrain || terrainPending) return;
  const want = S.view && S.view.terrain_t != null ? S.view.terrain_t : -1;
  if (want < 0 || want === terrainT) return;
  // At 4-8x a new snapshot arrives several times a second; each one rebuilds the
  // terrain chunks it touches, so they are applied at most every 0.7 s of wall time.
  if (performance.now() - terrainAt < 700) return;
  terrainAt = performance.now();
  terrainPending = true;
  try {
    const r = await api(`/api/terrain?t=${Math.round(t)}`).catch(() => null);
    terrainT = want;
    if (!r || !r.tiles) return;
    const both = Uint8Array.from(atob(r.tiles), (c) => c.charCodeAt(0));
    const cur = S.map._terrain, curL = S.map._layers;
    const n = cur.length;
    if (both.length !== n && both.length !== 2 * n) return;
    const next = both.subarray(0, n), nextL = both.length === 2 * n ? both.subarray(n) : curL;
    const changed = [];
    for (let i = 0; i < n; i++) if (next[i] !== cur[i] || nextL[i] !== curL[i]) changed.push(i);
    if (!changed.length) return;
    S.map._terrain = next.slice(); S.map._layers = nextL.slice();
    repaintTiles(changed);
  } finally { terrainPending = false; }
}

function repaintTiles(changed) {
  const hw = TERRAIN_TW / 2, hh = TERRAIN_TH / 2, oy = mapW * TERRAIN_TH / 2;
  const rects = [];
  for (const i of changed) {
    const x = i % mapW, y = Math.floor(i / mapW);
    const px = (x + y + 1) * hw, py = (y - x) * hh + oy;
    // The tile and the shading of its neighbour below: repaint a little around it.
    const x0 = Math.floor(px - hw * 2), y0 = Math.floor(py - hh * 2), x1 = Math.ceil(px + hw * 2), y1 = Math.ceil(py + hh * 2);
    rasterTerrain(x0, y0, x1, y1);
    if (viewTerrainImage) rasterTerrain(x0, y0, x1, y1, true);
    rects.push([Math.max(0, x0), Math.max(0, y0), x1, y1]);
    // A chunk blends one tile past its edge: only edge tiles touch a neighbour.
    const cx = Math.floor(x / CHUNK), cy = Math.floor(y / CHUNK), lx = x % CHUNK, ly = y % CHUNK;
    const xs = [cx, ...(lx === 0 ? [cx - 1] : lx === CHUNK - 1 ? [cx + 1] : [])];
    const ys = [cy, ...(ly === 0 ? [cy - 1] : ly === CHUNK - 1 ? [cy + 1] : [])];
    // Stale, not dropped: the old picture stays up until its rebuild (one per
    // ground repaint) is done, so a farm appearing never stalls a frame.
    for (const ky of ys) for (const kx of xs) { const c = chunkCache.get(`${kx},${ky}`); if (c) c.stale = true; }
  }
  // Upload the changed areas only (one bounding box of farms at opposite
  // corners re-uploaded the whole terrain canvas).
  const dirty = coalesceRects(rects);
  const tctx = terrainCanvas.getContext('2d');
  for (const [x0, y0, x1, y1] of dirty) tctx.putImageData(terrainImage, 0, 0, x0, y0, x1 - x0, y1 - y0);
  if (flatMap) {
    for (const i of changed) for (const j of [i, i - mapW, i + mapW]) if (j >= 0 && j < mapW * mapH) flatPixel(j);
    flatMap.getContext('2d').putImageData(flatMapImage, 0, 0);
    flatMap._dirty = true;
  }
  if (viewTerrainCanvas) {
    const vctx = viewTerrainCanvas.getContext('2d');
    for (const [x0, y0, x1, y1] of dirty) vctx.putImageData(viewTerrainImage, 0, 0, x0, y0, x1 - x0, y1 - y0);
  }
  miniDirty = true;
  if (ground.map !== S.map || !ground.key) terrainGen++;
  else for (const i of changedTilesInRegion(changed, mapW, ground.terrainRange)) dirtyGround(terrainGroundRect(i));
}

// The terrain grid is drawn live over whatever terrain layer is showing, so the
// intensity setting applies at once. Intensity (settings.terrainGrid): 0
// disables, 0..1 (the 0–100 % slider, step 5 %, recommended 50 %; values
// above 1 are read as percent) scales the line
// opacity linearly up to fully dark lines at 100 %. When tiles get too small
// for single lines to read, the grid fades instead of turning into a wash.
export function gridIntensity(v = settings.terrainGrid) {
  let k = Number(v) || 0;
  if (k > 1) k /= 100;
  return Math.max(0, Math.min(1, k));
}
function drawGrid() {
  const k = gridIntensity();
  if (k <= 0 || !mapW) return;
  const tilePx = TW * S.camera.zoom;
  const fade = Math.max(0, Math.min(1, (tilePx - 4) / 8));
  if (fade <= 0) return;
  const [minX, maxX, minY, maxY] = visibleTileRange();
  ctx.save();
  ctx.strokeStyle = `rgba(0,0,0,${(k * fade).toFixed(3)})`;
  ctx.lineWidth = Math.max(0.5, Math.min(1.25, S.camera.zoom * 0.8));
  ctx.beginPath();
  // Along the ground surface, one segment per tile edge (hills bend the lines).
  for (let i = minX; i <= maxX + 1; i++) {
    for (let j = minY; j <= maxY + 1; j++) {
      const [ax, ay] = groundScreen(i, j);
      if (j === minY) ctx.moveTo(ax, ay); else ctx.lineTo(ax, ay);
    }
  }
  for (let j = minY; j <= maxY + 1; j++) {
    for (let i = minX; i <= maxX + 1; i++) {
      const [ax, ay] = groundScreen(i, j);
      if (i === minX) ctx.moveTo(ax, ay); else ctx.lineTo(ax, ay);
    }
  }
  ctx.stroke();
  ctx.restore();
}

// Terrain and tree changes arrive several times a second at 8x; the minimap's
// full redraw (every tile) runs at most once a second for them.
let miniDirty = false, miniBuiltAt = 0;
function refreshMiniTerrain() {
  if (!miniDirty || performance.now() - miniBuiltAt < 1000) return;
  miniDirty = false;
  buildMiniTerrain();
}

let miniTerrainRev = 0;
function buildMiniTerrain() {
  miniBuiltAt = performance.now();
  // Repainted about once a second while farms and trees change: reuse the
  // (map-sized, tens of MB) canvas rather than allocating a new one each time.
  if (!miniTerrain) miniTerrain = document.createElement('canvas');
  if (miniTerrain.width !== terrainCanvas.width || miniTerrain.height !== terrainCanvas.height) {
    miniTerrain.width = terrainCanvas.width; miniTerrain.height = terrainCanvas.height;
  }
  miniTerrainRev++;
  const m = miniTerrain.getContext('2d');
  m.clearRect(0, 0, miniTerrain.width, miniTerrain.height);
  m.drawImage(terrainCanvas, 0, 0);
  if (treeTiles) drawTrees(m, TERRAIN_TW, TERRAIN_TH, mapW * TERRAIN_TH / 2, 'rgba(18,52,20,0.85)');
}

function drawTrees(c, tw, th, oy, color) {
  c.fillStyle = color;
  for (let y = 0; y < mapH; y++) {
    for (let x = 0; x < mapW; x++) {
      if (!treeTiles[y * mapW + x]) continue;
      const px = (x + y + 1) * tw / 2, py = (y - x) * th / 2 + oy;
      c.beginPath();
      c.moveTo(px - tw / 2, py); c.lineTo(px, py - th / 2); c.lineTo(px + tw / 2, py); c.lineTo(px, py + th / 2);
      c.fill();
    }
  }
}

let treesAt = 0, treesPending = false;
export async function refreshTrees(t) {
  if (!S.map || treesPending) return;
  const want = S.view && S.view.trees_t != null ? S.view.trees_t : -1;
  if (want === treesT) return;
  // A snapshot every 3 game seconds is several a second at 4-8x: fetched (and the
  // forest redrawn) at most every 0.7 s of wall time, like the terrain.
  if (performance.now() - treesAt < 700) return;
  treesAt = performance.now();
  treesT = want;
  treesPending = true;
  const r = await api(`/api/trees?t=${Math.round(t)}`).catch(() => null).finally(() => { treesPending = false; });
  if (!r || !r.tiles) return;
  const both = Uint8Array.from(atob(r.tiles), (c) => c.charCodeAt(0));
  const n = mapW * mapH;
  const next = { tiles: both.subarray(0, n), facets: both.length >= 2 * n ? both.subarray(n, 2 * n) : null, kinds: r.kinds || [] };
  const before = { tiles: treeTiles, facets: treeFacets, kinds: treeKinds };
  const changed = changedTreeTiles(before, next, mapW, ground.treeRange);
  if (ground.map !== S.map || !ground.key || changed === null) treeGen++;
  else for (const i of changed) {
    const old = treeGroundRect(i, before), now = treeGroundRect(i, next);
    if (old === undefined || now === undefined) { treeGen++; break; }
    dirtyGround(old); dirtyGround(now);
  }
  treeTiles = next.tiles; treeFacets = next.facets; treeKinds = next.kinds;
  miniDirty = true;
}

// -- fog --------------------------------------------------------------------------
// S.fogMode: 'off' (no fog), 'spy' (every entity shown; terrain still shaded by
// what the perspective has explored and sees) or 'standard' (the player's own
// view: hidden entities are not drawn, explored buildings are remembered).

function perspectiveMask() {
  if (S.perspective === 0) return 0;
  if (!S.combinedFog) return 1 << (S.perspective - 1);
  const me = S.match.players[S.perspective];
  let mask = 0;
  for (const p of players()) if (me && p.team_key === me.team_key) mask |= 1 << (p.id - 1);
  return mask;
}

/** Fog mode actually in force: 'off' when there is no perspective or no data. */
function fogState() {
  if (S.fogMode === 'off' || S.perspective === 0 || !fogBytes) return 'off';
  return S.fogMode === 'spy' ? 'spy' : 'standard';
}

let fogBytes = null;
function decodeFog() {
  const view = S.view;
  if (!view || !view.fog) return null;
  if (view._fogDecoded) {
    // A view decoded earlier (look-ahead, or seen before) becomes current.
    if (fogBytes !== view._fogDecoded) { fogBytes = view._fogDecoded; fogKey = ''; }
    return fogBytes;
  }
  // Inflating is async: start it once per view (not once per frame until it
  // lands) and attach the bytes to that view, whichever view is current then.
  if (!view._fogPromise) {
    try {
      const raw = Uint8Array.from(atob(view.fog), (c) => c.charCodeAt(0));
      view._fogPromise = inflate(raw).then((b) => {
        view._fogDecoded = b;
        if (S.view === view) { fogBytes = b; fogKey = ''; }
      }, () => {});
    } catch (e) { view._fogPromise = Promise.resolve(); /* malformed */ }
  }
  return fogBytes;
}

async function inflate(bytes) {
  const ds = new DecompressionStream('deflate');
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Is an entity at (x, y) shown? Spy and Off show everything. */
export function isVisible(x, y) {
  if (fogState() !== 'standard') return true;
  const i = (Math.floor(y) * mapW + Math.floor(x)) * 2;
  return (fogBytes[i] & perspectiveMask()) !== 0;
}

// The fog of the current view as a map-sized alpha image (fogSmall, one pixel
// per tile: the WebGL ground and the minimap draw it with a transform). The
// isometric full-terrain-size projection (fogCanvas, ~30 MB on a large map) is
// only needed without WebGL and is built on demand (fogIso). Both canvases are
// reused: a new pair per keyframe was ~400 MB/s of canvas churn at 8x.
let fogImage = null, fogIsoKey = -1, fogRev = 0;
function buildFog() {
  const mask = perspectiveMask();
  const state = fogState();
  const key = `${state}|${mask}|${S.view ? S.view.time : 0}|${fogBytes ? fogBytes.length : 0}`;
  if (key === fogKey) return;
  fogKey = key;
  if (state === 'off' || mask === 0 || !terrainCanvas || !fogBytes) { fogSmall = null; fogCanvas = null; return; }
  const w = mapW, h = mapH;
  if (!fogSmallCanvas) fogSmallCanvas = document.createElement('canvas');
  if (fogSmallCanvas.width !== w || fogSmallCanvas.height !== h) { fogSmallCanvas.width = w; fogSmallCanvas.height = h; fogImage = null; }
  const sc = fogSmallCanvas.getContext('2d');
  if (!fogImage) fogImage = sc.createImageData(w, h);
  const d = fogImage.data;
  for (let i = 0; i < w * h; i++) {
    const vis = fogBytes[2 * i] & mask, exp = fogBytes[2 * i + 1] & mask;
    d[i * 4 + 3] = vis ? 0 : exp ? 120 : 235;
  }
  sc.putImageData(fogImage, 0, 0);
  // The canvas is reused: tell terrain-gl's texture cache (keyed by the source
  // canvas) that its pixels changed.
  fogSmallCanvas._dirty = true;
  fogRev++;
  fogSmall = fogSmallCanvas; // map space: drawn over the height-mapped ground (terrain-gl)
  fogCanvas = fogSmall; // "there is fog"; fogIso() projects it when a 2D path needs it
}
let fogSmallCanvas = null, fogIsoCanvas = null, fogPadCanvas = null, fogPadRev = -1;
// fogSmall with a one-pixel border repeating its edge pixels (for the minimap).
function paddedFog() {
  if (fogPadRev === fogRev && fogPadCanvas) return fogPadCanvas;
  fogPadRev = fogRev;
  const w = fogSmall.width, h = fogSmall.height;
  if (!fogPadCanvas) fogPadCanvas = document.createElement('canvas');
  if (fogPadCanvas.width !== w + 2 || fogPadCanvas.height !== h + 2) { fogPadCanvas.width = w + 2; fogPadCanvas.height = h + 2; }
  const c = fogPadCanvas.getContext('2d');
  c.clearRect(0, 0, w + 2, h + 2);
  c.drawImage(fogSmall, 1, 1);
  c.drawImage(fogSmall, 0, 0, w, 1, 1, 0, w, 1); // top row
  c.drawImage(fogSmall, 0, h - 1, w, 1, 1, h + 1, w, 1); // bottom row
  c.drawImage(fogPadCanvas, 1, 0, 1, h + 2, 0, 0, 1, h + 2); // left column (corners too)
  c.drawImage(fogPadCanvas, w, 0, 1, h + 2, w + 1, 0, 1, h + 2); // right column
  return fogPadCanvas;
}
function fogIso() {
  if (!fogSmall || !terrainCanvas) return null;
  if (fogIsoKey === fogRev && fogIsoCanvas) return fogIsoCanvas;
  fogIsoKey = fogRev;
  if (!fogIsoCanvas) fogIsoCanvas = document.createElement('canvas');
  if (fogIsoCanvas.width !== terrainCanvas.width || fogIsoCanvas.height !== terrainCanvas.height) {
    fogIsoCanvas.width = terrainCanvas.width; fogIsoCanvas.height = terrainCanvas.height;
  }
  const fc = fogIsoCanvas.getContext('2d');
  fc.setTransform(1, 0, 0, 1, 0, 0);
  fc.clearRect(0, 0, fogIsoCanvas.width, fogIsoCanvas.height);
  fc.imageSmoothingEnabled = true;
  const oy = mapW * TERRAIN_TH / 2;
  // tile (x,y) -> (x+y)*TW/2, (y-x)*TH/2 + oy  ==  affine transform of the square
  fc.setTransform(TERRAIN_TW / 2, -TERRAIN_TH / 2, TERRAIN_TW / 2, TERRAIN_TH / 2, 0, oy);
  fc.drawImage(fogSmall, 0, 0);
  return fogIsoCanvas;
}

// -- textured terrain ---------------------------------------------------------------

const terrainPatterns = new Map();
function terrainPattern(i) {
  if (terrainPatterns.has(i)) return terrainPatterns.get(i);
  terrainPatterns.set(i, null);
  const tex = S.map && S.map.terrain_textures && S.map.terrain_textures[i];
  const flat = (S.map && S.map.terrain_colors && S.map.terrain_colors[i]) || '#3c5a28';
  if (!tex || !tex[0]) { terrainPatterns.set(i, flat); return flat; }
  const im = new Image();
  im.onerror = () => { terrainPatterns.set(i, flat); };
  im.onload = () => {
    const p = ctx.createPattern(im, 'repeat');
    p._w = im.width;
    p._img = im; // the GPU chunk compositor's texture
    textureAvg.set(i, meanColor(im));
    terrainPatterns.set(i, p);
  };
  im.src = withAssetVersion(`/terrain/${tex[0]}.png`);
  return null;
}

// A layer terrain's overlay mask (greyscale noise) as an alpha pattern: null while
// loading, false when the game has none (the layer then covers its tiles fully).
const terrainMasks = new Map();
function terrainMask(name) {
  if (!name) return false;
  if (terrainMasks.has(name)) return terrainMasks.get(name);
  terrainMasks.set(name, null);
  const im = new Image();
  im.onerror = () => { terrainMasks.set(name, false); };
  im.onload = () => {
    const c = document.createElement('canvas');
    c.width = im.width; c.height = im.height;
    const g = c.getContext('2d');
    g.drawImage(im, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height);
    let sum = 0;
    for (let k = 0; k < d.data.length; k += 4) { sum += d.data[k]; d.data[k + 3] = d.data[k]; d.data[k] = d.data[k + 1] = d.data[k + 2] = 255; }
    maskAvg.set(name, sum / (d.data.length / 4) / 255);
    g.putImageData(d, 0, 0);
    const p = ctx.createPattern(c, 'repeat');
    p._w = c.width;
    p._img = im; // the GPU compositor reads the noise from the red channel
    terrainMasks.set(name, p);
  };
  im.src = `/terrain-mask/${name}.png`;
  return null;
}

// Terrain is composited in map space, CHUNK x CHUNK tiles at CHUNK_PX per tile,
// then drawn through the isometric transform. Each terrain type's texture is
// masked by its per-tile indicator upscaled bilinearly; the masks sum to one at
// every point, so adding the layers gives a soft blend between neighbouring
// terrains. Elevation shading is baked in the same smooth way.
const CHUNK = 16, CHUNK_PX = 32;
// Stale chunks rebuilt per ground repaint (the rest keep their old picture).
let staleBudget = 1;
const chunkCache = new Map();
let chunkGen = 0;
// The chunks composited on the GPU went with a lost context: build them again.
TG.onContextLost(() => { chunkCache.clear(); chunkGen++; });

// `gpu`: composite on the WebGL ground (terrain-gl.js composeChunk) and return its
// token for TG.drawChunk; otherwise a canvas.
function chunkCanvas(cx, cy, gpu = false) {
  const t0 = performance.now();
  try { return buildChunk(cx, cy, gpu); } finally { drawTimes.chunks += performance.now() - t0; }
}
function keepChunk(key, entry) {
  if (chunkCache.size > 96) {
    const [old, v] = chunkCache.entries().next().value;
    chunkCache.delete(old);
    if (v.canvas && v.canvas.composed) TG.dropChunks([old]);
  }
  chunkCache.set(key, entry);
}
// One byte per indicator texel: 255 where the tile (clamped to the map) is `t`.
function indicator(tiles, x0, y0, pad, t) {
  const a = new Uint8Array(pad * pad);
  for (let j = 0; j < pad; j++) for (let i = 0; i < pad; i++) {
    const x = Math.min(mapW - 1, Math.max(0, x0 - 1 + i)), y = Math.min(mapH - 1, Math.max(0, y0 - 1 + j));
    a[j * pad + i] = tiles[y * mapW + x] === t ? 255 : 0;
  }
  return a;
}
function buildChunk(cx, cy, gpu = false) {
  const key = `${cx},${cy}`;
  let c = chunkCache.get(key);
  // A GPU-composited chunk has no canvas for the 2D path: build that afresh.
  if (c && c.canvas && c.canvas.composed && !gpu) c = null;
  if (c && c.gen === chunkGen && !c.stale) return c.canvas;
  if (c && c.gen === chunkGen && c.stale && staleBudget <= 0) { groundIncomplete = true; return c.canvas; }
  if (c && c.stale) staleBudget--;
  const terrain = S.map._terrain, elev = S.map._elev;
  const x0 = cx * CHUNK, y0 = cy * CHUNK;
  const pad = CHUNK + 2;
  const types = new Set();
  for (let y = y0 - 1; y <= y0 + CHUNK; y++) for (let x = x0 - 1; x <= x0 + CHUNK; x++) {
    if (x >= 0 && y >= 0 && x < mapW && y < mapH) types.add(terrain[y * mapW + x]);
  }
  const layers = S.map._layers;
  const ltypes = new Set();
  if (layers) {
    for (let y = y0 - 1; y <= y0 + CHUNK; y++) for (let x = x0 - 1; x <= x0 + CHUNK; x++) {
      if (x >= 0 && y >= 0 && x < mapW && y < mapH && layers[y * mapW + x] !== 255) ltypes.add(layers[y * mapW + x]);
    }
  }
  for (const t of types) if (!terrainPattern(t)) return null; // textures still loading
  for (const t of ltypes) {
    const tex = S.map.terrain_textures[t];
    if (!terrainPattern(t) || terrainMask(tex && tex[2]) === null) return null;
  }
  if (gpu) {
    const token = TG.composeChunk(cx, cy, chunkSpec(x0, y0, pad, types, ltypes));
    if (token) { keepChunk(key, { canvas: token, gen: chunkGen }); return token; }
  }
  const out = document.createElement('canvas');
  out.width = out.height = CHUNK * CHUNK_PX;
  const oc = out.getContext('2d');
  oc.globalCompositeOperation = 'lighter';
  const mask = document.createElement('canvas');
  mask.width = mask.height = pad;
  const mc = mask.getContext('2d');
  const layer = document.createElement('canvas');
  layer.width = layer.height = CHUNK * CHUNK_PX;
  const lc = layer.getContext('2d');
  for (const t of types) {
    const md = mc.createImageData(pad, pad);
    for (let j = 0; j < pad; j++) for (let i = 0; i < pad; i++) {
      const x = Math.min(mapW - 1, Math.max(0, x0 - 1 + i)), y = Math.min(mapH - 1, Math.max(0, y0 - 1 + j));
      md.data[(j * pad + i) * 4 + 3] = terrain[y * mapW + x] === t ? 255 : 0;
    }
    mc.putImageData(md, 0, 0);
    lc.globalCompositeOperation = 'source-over';
    lc.clearRect(0, 0, layer.width, layer.height);
    const pat = terrainPattern(t);
    const rows = (S.map.terrain_textures[t] && S.map.terrain_textures[t][1]) || 10;
    if (typeof pat !== 'string') pat.setTransform(new DOMMatrix().translate(-x0 * CHUNK_PX, -y0 * CHUNK_PX).scale((CHUNK_PX * rows) / pat._w));
    lc.fillStyle = pat;
    lc.fillRect(0, 0, layer.width, layer.height);
    lc.globalCompositeOperation = 'destination-in';
    lc.imageSmoothingEnabled = true;
    // Mask pixel i is the centre of tile x0-1+i.
    lc.drawImage(mask, -1.5 * CHUNK_PX, -1.5 * CHUNK_PX, pad * CHUNK_PX, pad * CHUNK_PX);
    oc.drawImage(layer, 0, 0);
  }
  // Layer terrains (grass laid over dry grass...): the layer's texture through its
  // overlay mask, on the tiles that carry it, over the blended base.
  oc.globalCompositeOperation = 'source-over';
  for (const t of ltypes) {
    const md = mc.createImageData(pad, pad);
    for (let j = 0; j < pad; j++) for (let i = 0; i < pad; i++) {
      const x = Math.min(mapW - 1, Math.max(0, x0 - 1 + i)), y = Math.min(mapH - 1, Math.max(0, y0 - 1 + j));
      md.data[(j * pad + i) * 4 + 3] = layers[y * mapW + x] === t ? 255 : 0;
    }
    mc.putImageData(md, 0, 0);
    lc.globalCompositeOperation = 'source-over';
    lc.clearRect(0, 0, layer.width, layer.height);
    const tex = S.map.terrain_textures[t];
    const rows = (tex && tex[1]) || 10;
    const pat = terrainPattern(t);
    if (typeof pat !== 'string') pat.setTransform(new DOMMatrix().translate(-x0 * CHUNK_PX, -y0 * CHUNK_PX).scale((CHUNK_PX * rows) / pat._w));
    lc.fillStyle = pat;
    lc.fillRect(0, 0, layer.width, layer.height);
    lc.globalCompositeOperation = 'destination-in';
    lc.imageSmoothingEnabled = true;
    lc.drawImage(mask, -1.5 * CHUNK_PX, -1.5 * CHUNK_PX, pad * CHUNK_PX, pad * CHUNK_PX);
    const noise = terrainMask(tex && tex[2]);
    if (noise) {
      noise.setTransform(new DOMMatrix().translate(-x0 * CHUNK_PX, -y0 * CHUNK_PX).scale((CHUNK_PX * rows) / noise._w));
      lc.fillStyle = noise;
      lc.fillRect(0, 0, layer.width, layer.height);
    }
    oc.drawImage(layer, 0, 0);
  }
  // Elevation: smooth light/shadow from the slope towards the light.
  oc.globalCompositeOperation = 'source-over';
  const sd = mc.createImageData(pad, pad);
  for (let j = 0; j < pad; j++) for (let i = 0; i < pad; i++) {
    const x = Math.min(mapW - 1, Math.max(0, x0 - 1 + i)), y = Math.min(mapH - 1, Math.max(0, y0 - 1 + j));
    const k = y * mapW + x;
    // The game lights from the upper left (shadows fall to the lower right). Screen
    // down-right is tile y + 1, screen down-left tile x - 1: ground rising towards the
    // lower right faces the light (lit), falling away from it is in shade.
    const e0 = elev[k];
    const dr = (y + 1 < mapH ? elev[k + mapW] : e0) - (y > 0 ? elev[k - mapW] : e0);
    const dl = (x > 0 ? elev[k - 1] : e0) - (x + 1 < mapW ? elev[k + 1] : e0);
    const sh = dr * 0.24 + dl * 0.08;
    const o = (j * pad + i) * 4;
    if (sh >= 0) { sd.data[o] = 255; sd.data[o + 1] = 244; sd.data[o + 2] = 214; sd.data[o + 3] = Math.min(110, sh * 255); }
    else { sd.data[o + 3] = Math.min(150, -sh * 255); }
  }
  mc.putImageData(sd, 0, 0);
  oc.imageSmoothingEnabled = true;
  oc.drawImage(mask, -1.5 * CHUNK_PX, -1.5 * CHUNK_PX, pad * CHUNK_PX, pad * CHUNK_PX);
  keepChunk(key, { canvas: out, gen: chunkGen });
  return out;
}

// The GPU compositor's input for one chunk: buildChunk's passes as data.
function chunkSpec(x0, y0, pad, types, ltypes) {
  const terrain = S.map._terrain, elev = S.map._elev, layers = S.map._layers;
  const entry = (t) => {
    const pat = terrainPattern(t), tex = S.map.terrain_textures[t];
    const rows = (tex && tex[1]) || 10;
    return typeof pat === 'string' ? { color: hexToRgb(pat).map((v) => v / 255), rows } : { img: pat._img, rows };
  };
  const base = [...types].map((t) => ({ ...entry(t), mask: indicator(terrain, x0, y0, pad, t) }));
  const over = [...ltypes].map((t) => {
    const e = entry(t), tex = S.map.terrain_textures[t], noise = terrainMask(tex && tex[2]);
    return { ...e, mask: indicator(layers, x0, y0, pad, t), noise: noise ? { img: noise._img, rows: e.rows } : null };
  });
  // The elevation shading (as buildChunk), premultiplied.
  const shade = new Uint8Array(pad * pad * 4);
  for (let j = 0; j < pad; j++) for (let i = 0; i < pad; i++) {
    const x = Math.min(mapW - 1, Math.max(0, x0 - 1 + i)), y = Math.min(mapH - 1, Math.max(0, y0 - 1 + j));
    const k = y * mapW + x, e0 = elev[k];
    const dr = (y + 1 < mapH ? elev[k + mapW] : e0) - (y > 0 ? elev[k - mapW] : e0);
    const dl = (x > 0 ? elev[k - 1] : e0) - (x + 1 < mapW ? elev[k + 1] : e0);
    const sh = dr * 0.24 + dl * 0.08, o = (j * pad + i) * 4;
    if (sh >= 0) {
      const a = Math.min(110, sh * 255);
      shade[o] = Math.round(255 * a / 255); shade[o + 1] = Math.round(244 * a / 255); shade[o + 2] = Math.round(214 * a / 255); shade[o + 3] = a;
    } else shade[o + 3] = Math.min(150, -sh * 255);
  }
  return { px: CHUNK * CHUNK_PX, tile: CHUNK_PX, pad, x0: x0 * CHUNK_PX, y0: y0 * CHUNK_PX, linear: filt('terrain'), base, layers: over, shade };
}

function drawTexturedTerrain() {
  if (!S.map || !S.map._terrain || !S.map.terrain_textures) return;
  const [minX, maxX, minY, maxY] = visibleTileRange();
  const z = S.camera.zoom, dpr = viewSize.dpr;
  const [ox, oy] = toScreen(0, 0);
  ctx.save();
  // Map space (CHUNK_PX px per tile) projected to the screen.
  const k = 1 / CHUNK_PX;
  ctx.setTransform(dpr * TW / 2 * z * k, -dpr * TH / 2 * z * k, dpr * TW / 2 * z * k, dpr * TH / 2 * z * k, dpr * ox, dpr * oy);
  ctx.imageSmoothingEnabled = filt('terrain');
  let built = 0;
  for (let cy = Math.floor(minY / CHUNK); cy <= Math.floor(maxY / CHUNK); cy++) {
    for (let cx = Math.floor(minX / CHUNK); cx <= Math.floor(maxX / CHUNK); cx++) {
      const cached = chunkCache.get(`${cx},${cy}`);
      if (!cached && built >= 3) { groundIncomplete = true; continue; } // spread chunk building over frames
      if (!cached) built++;
      const c = chunkCanvas(cx, cy);
      if (!c) { groundIncomplete = true; continue; }
      // A hair of overlap hides seams between chunks.
      ctx.drawImage(c, cx * CHUNK * CHUNK_PX - 0.5, cy * CHUNK * CHUNK_PX - 0.5, c.width + 1, c.height + 1);
    }
  }
  ctx.restore();
}

function visibleTileRange() {
  const [left, top, right, bottom] = groundClip || [0, 0, viewSize.w, viewSize.h];
  const [x0, y0] = toWorld(left, top), [x1, y1] = toWorld(right, bottom);
  const [x2, y2] = toWorld(right, top), [x3, y3] = toWorld(left, bottom);
  const margin = groundClip ? 16 : TG.hasHeights() ? 8 : 0;
  return [
    Math.max(0, Math.floor(Math.min(x0, x1, x2, x3)) - 2), Math.min(mapW - 1, Math.ceil(Math.max(x0, x1, x2, x3)) + 2),
    Math.max(0, Math.floor(Math.min(y0, y1, y2, y3)) - 2), Math.min(mapH - 1, Math.ceil(Math.max(y0, y1, y2, y3)) + 3),
  ].map((v, i) => (i % 2 ? Math.min(i === 1 ? mapW - 1 : mapH - 1, v + margin) : Math.max(0, v - margin)));
}

// Trees as game sprites, back to front; a tile's frame is a stable hash of its position.
function drawTreeSprites() {
  const [minX, maxX, minY, maxY] = visibleTileRange();
  const fallback = [];
  const treeScale = settings.smallTrees ? 0.6 : 1;
  ctx.imageSmoothingEnabled = filt('unitColor');
  // Back to front: screen depth grows with y - x.
  for (let d = minY - maxX; d <= maxY - minX; d++) {
    for (let x = Math.max(minX, minY - d); x <= Math.min(maxX, maxY - d); x++) {
      const y = x + d;
      if (!treeTiles[y * mapW + x]) continue;
      const e = treeSprite(x, y);
      const [px, py] = groundScreen(x + 0.5, y + 0.5);
      if (!e) { if (e !== false) groundIncomplete = true; fallback.push([px, py]); continue; }
      const m = e.meta;
      const s = (S.camera.zoom * TW) / (e.tile || SPRITE_TILE) * treeScale;
      ctx.drawImage(e.img, 0, 0, m.cw, m.ch, px - m.ax * s, py - m.ay * s, m.cw * s, m.ch * s);
    }
  }
  if (fallback.length) {
    ctx.fillStyle = 'rgba(16,48,18,0.78)';
    const r = TW / 2 * S.camera.zoom * 0.42;
    ctx.beginPath();
    for (const [px, py] of fallback) { ctx.moveTo(px + r, py); ctx.ellipse(px, py, r, r * 0.7, 0, 0, Math.PI * 2); }
    ctx.fill();
  }
}

// -- interpolation -----------------------------------------------------------------

// Facings of a row's first sprite (catalog sprite_facets): a moving unit faces
// where it goes between snapshots (playback.js RowInterpolator).
const rowInterpolator = new RowInterpolator((r) => {
  const sf = S.catalog && S.catalog.sprite_facets, l = r[8] && r[8][0];
  return (sf && l && sf[l[0]]) || 0;
});
function interpolatedRows() { return rowInterpolator.at(S.view, S.nextView, S.t); }

// -- sound scene ----------------------------------------------------------------------
// What is on screen, gathered while drawing, for audio.js: burning buildings,
// fights, working villagers, animals, hit points lost since the last keyframe,
// and the landscape (biome) for the ambience bed. Pans are -1 (left) .. 1 (right).

const ACT_FIGHTING = 8;
const ANIMAL_CLASSES = new Set([9, 10, 58]); // prey, predator, livestock
export const scene = {
  time: 0, burning: 0, burnPan: 0, fights: [], workers: [], animals: [], hits: [],
  biome: 'plains', water: 0,
};
let sceneView = null;
const lastHp = new Map();

function sceneBegin() {
  scene.time = S.t;
  scene.burning = 0; scene.burnPan = 0;
  scene.fights.length = 0; scene.workers.length = 0; scene.animals.length = 0;
  const v = S.view;
  if (v !== sceneView) {
    // A new keyframe: entities that lost hit points since the previous one.
    scene.hits = [];
    if (v && sceneView && v.time > sceneView.time && v.time - sceneView.time <= 3000) {
      for (const r of v.entities) {
        const before = lastHp.get(r[0]);
        if (before == null || r[5] >= before - 0.001 || (r[6] & 16)) continue;
        if (r[1] === 0 && !ANIMAL_CLASSES.has(entityInfo(r).cls)) continue; // mines, bushes
        scene.hits.push([r[2], r[3], r[4]]);
      }
    }
    lastHp.clear();
    if (v) for (const r of v.entities) lastHp.set(r[0], r[5]);
    sceneView = v;
  }
  if (performance.now() > biomeAt) updateBiome();
}

function sceneAdd(r, u, px) {
  const pan = Math.max(-1, Math.min(1, (px / Math.max(1, viewSize.w)) * 2 - 1));
  const flags = r[6];
  if (flags & 1) {
    if (r[1] && !(flags & 16) && r[5] < 0.75) { scene.burning++; scene.burnPan += pan; }
    return;
  }
  if (r[9] === ACT_FIGHTING && scene.fights.length < 60) scene.fights.push([r[2], pan, r[1]]);
  else if ((flags & 4) && r[9] >= 2 && r[9] <= 7 && scene.workers.length < 60) scene.workers.push([r[2], r[9], pan]);
  if (ANIMAL_CLASSES.has(u.cls) && scene.animals.length < 40) scene.animals.push([r[2], pan]);
}

// Biome of the visible landscape, from terrain texture names and trees.
let biomeAt = 0;
const BIOME_RULES = [
  ['snow', /sno|snd|sn2|snf|ice|o_sn/],
  ['desert', /g_des|g_qs|g_ds5|g_bla/],
  ['water_deep', /g_wt\d|g_wt_|g_wtr/],
  ['water', /g_sha|g_sh\d|beach_wet/],
];
function updateBiome() {
  biomeAt = performance.now() + 2000;
  if (!S.map || !S.map._terrain || !mapW) return;
  const [minX, maxX, minY, maxY] = visibleTileRange();
  const names = (S.map.terrain_textures || []).map((t) => (t && t[0]) || '');
  const counts = { snow: 0, desert: 0, water_deep: 0, water: 0, trees: 0, jungle: 0 };
  let n = 0;
  const step = Math.max(1, Math.floor((maxX - minX) / 24));
  for (let y = minY; y <= maxY; y += step) {
    for (let x = minX; x <= maxX; x += step) {
      const [px, py] = groundScreen(x + 0.5, y + 0.5);
      if (px < 0 || py < 0 || px > viewSize.w || py > viewSize.h) continue;
      n++;
      const name = names[S.map._terrain[y * mapW + x]] || '';
      for (const [k, re] of BIOME_RULES) if (re.test(name)) { counts[k]++; break; }
      if (treeTiles && treeTiles[y * mapW + x]) { counts.trees++; if (/pal|fo2|jungle|bamboo/.test(name)) counts.jungle++; }
    }
  }
  if (!n) return;
  const f = (k) => counts[k] / n;
  scene.water = f('water_deep') + f('water');
  scene.biome = f('water_deep') > 0.35 ? 'ocean'
    : f('snow') > 0.3 ? 'snow'
    : f('water_deep') + f('water') > 0.2 ? 'lake'
    : f('desert') > 0.3 ? 'desert'
    : f('trees') > 0.2 ? (counts.jungle > counts.trees / 2 ? 'jungle' : 'forest')
    : 'plains';
}

// -- drawing ----------------------------------------------------------------------

// The ground (terrain, grid, trees) only changes when the camera, the trees or
// the terrain do, not with game time: while the camera holds still it is drawn
// once into an offscreen canvas and copied each frame. That keeps fast replay
// (4-8x) from repainting thousands of terrain and tree tiles every frame.
// A border also lets pans reuse the ground: translating this bitmap is much
// cheaper than redrawing all terrain and trees for each camera position.
const GROUND_PAD = 128; // CSS pixels on each side, independent of pixel density
const ground = { canvas: null, ctx: null, key: '', partialKey: '', retryAt: 0, x: 0, y: 0, zoom: 0, width: 0, height: 0, padding: GROUND_PAD, map: null, treeRange: null, terrainRange: null, dirty: null };
let groundIncomplete = false;
let treeGen = 0;

function cachedGroundPoint(x, y, height = 0) {
  const z = ground.zoom;
  return [(x + y - ground.x - ground.y) * TW / 2 * z + ground.width / 2,
    (y - x - ground.y + ground.x) * TH / 2 * z + ground.height / 2 - height * TH / 2 * z];
}

function dirtyGround(rect) {
  ground.dirty = mergeDirtyRect(ground.dirty, rect, ground.width, ground.height, GROUND_PAD);
}

function treeGroundRect(i, forest) {
  if (!forest.tiles?.[i]) return null;
  const mid = forest.kinds[forest.tiles[i] - 1], u = unitInfo(mid);
  const facet = forest.facets?.[i] || 0;
  const e = spriteCache.get(`${u.sprite}/${facet}/-1?${stripQuery()}`);
  // A newly encountered tree with no loaded bounds is conservatively dirty.
  if (spritesOn() && (!e?.meta || !e.img)) return undefined;
  const x = i % mapW + 0.5, y = Math.floor(i / mapW) + 0.5;
  const [px, py] = cachedGroundPoint(x, y, TG.heightAt(x, y));
  if (!spritesOn()) {
    const r = TW / 2 * ground.zoom * 0.42;
    return [px - r, py - r, px + r, py + r];
  }
  const m = e.meta, s = ground.zoom * TW / (e.tile || SPRITE_TILE) * (settings.smallTrees ? 0.6 : 1);
  return [px - m.ax * s, py - m.ay * s, px + (m.cw - m.ax) * s, py + (m.ch - m.ay) * s];
}

function terrainGroundRect(i) {
  const x = i % mapW, y = Math.floor(i / mapW);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  // Terrain masks and flat-map filtering reach into neighbouring tiles. Bound
  // that whole patch, sampling its height-field vertices as well as its edges.
  for (let ty = Math.max(0, y - 2); ty <= Math.min(mapH, y + 3); ty++) {
    for (let tx = Math.max(0, x - 2); tx <= Math.min(mapW, x + 3); tx++) {
      const h = ground.heightMapped ? TG.heightAt(Math.min(mapW - 0.0001, tx), Math.min(mapH - 0.0001, ty)) : 0;
      const [px, py] = cachedGroundPoint(tx, ty, h);
      x0 = Math.min(x0, px); y0 = Math.min(y0, py); x1 = Math.max(x1, px); y1 = Math.max(y1, py);
    }
  }
  return [x0, y0, x1, y1];
}

function patchGround(key) {
  const rect = ground.dirty, { w, h, dpr } = viewSize, camera = S.camera;
  const g = ground.ctx;
  // Clip on device-pixel edges too: fractional display scaling must not leave
  // translucent seams where a dirty rectangle meets the untouched raster.
  const [x0, y0, x1, y1] = rect.map((v, i) => (i < 2 ? Math.floor((v + GROUND_PAD) * dpr) : Math.ceil((v + GROUND_PAD) * dpr)) / dpr);
  g.save();
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.beginPath(); g.rect(x0, y0, x1 - x0, y1 - y0); g.clip();
  g.clearRect(x0, y0, x1 - x0, y1 - y0);
  ctx = g;
  S.camera = { x: ground.x, y: ground.y, zoom: ground.zoom };
  viewSize.w = ground.width + GROUND_PAD * 2; viewSize.h = ground.height + GROUND_PAD * 2;
  groundClip = [x0, y0, x1, y1];
  groundIncomplete = false;
  try {
    const [ox, oy] = toScreen(0, 0);
    paintGround(ox, oy, ground.zoom * TW / TERRAIN_TW);
    drawTimes.patches++;
  } finally {
    ctx = mainCtx; S.camera = camera; viewSize.w = w; viewSize.h = h; groundClip = null; g.restore();
  }
  ground.dirty = null;
  ground.rev = (ground.rev || 0) + 1;
  if (groundIncomplete) {
    ground.key = ''; ground.partialKey = key; ground.retryAt = performance.now() + 250;
  }
}

function groundKey() {
  const c = S.camera;
  return [viewSize.w, viewSize.h, viewSize.dpr, chunkGen, treeGen, terrainGen,
    spritesOn(), settings.enhancedGraphics && c.zoom >= 1.4, modQuery(), filt('terrain'), filt('unitColor'), gridIntensity(), settings.smallTrees, S.map && S.map.width, terrainTint().join(',')].join('|');
}

function paintGround(ox, oy, scale) {
  drawTimes.paints++;
  staleBudget = 1;
  const z = S.camera.zoom;
  if (flatMap && TG.available()) {
    // The ground as the game shapes it (hills and slopes), drawn by WebGL.
    const view = { w: viewSize.w, h: viewSize.h, tw: TW, th: TH };
    const range = visibleTileRange();
    TG.begin(viewSize.w, viewSize.h, viewSize.dpr);
    TG.setTint(terrainTint());
    TG.drawMapTexture('flat', flatMap, S.camera, view, range, { linear: filt('terrain') && z * TW < 6 });
    if (spritesOn()) drawTexturedTerrainGL(view, range);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(TG.output(), 0, 0);
    ctx.restore();
  } else {
    ctx.imageSmoothingEnabled = filt('terrain') && z * TW / TERRAIN_TW < 3;
    const flat = viewTerrainCanvas || terrainCanvas;
    ctx.drawImage(flat, ox, oy - mapW * TERRAIN_TH / 2 * scale, flat.width * scale, flat.height * scale);
    if (spritesOn()) drawTexturedTerrain();
  }
  const tg = performance.now();
  drawGrid();
  if (treeTiles) drawTreesWorld();
  drawTimes.trees += performance.now() - tg;
}

function drawTexturedTerrainGL(view, [minX, maxX, minY, maxY]) {
  if (!S.map || !S.map._terrain || !S.map.terrain_textures) return;
  let built = 0;
  const linear = filt('terrain');
  // Composited on the GPU a chunk costs well under a millisecond: build what the
  // view needs at once (on a canvas, three per frame and one stale per repaint).
  const gpu = settings.gpuSprites !== false && TG.canCompose();
  if (gpu) staleBudget = 64;
  for (let cy = Math.floor(minY / CHUNK); cy <= Math.floor(maxY / CHUNK); cy++) {
    for (let cx = Math.floor(minX / CHUNK); cx <= Math.floor(maxX / CHUNK); cx++) {
      const cached = chunkCache.get(`${cx},${cy}`);
      if (!cached && built >= (gpu ? 64 : 3)) { groundIncomplete = true; continue; } // spread chunk building over frames
      if (!cached) built++;
      const c = chunkCanvas(cx, cy, gpu);
      if (!c) { groundIncomplete = true; continue; }
      TG.drawChunk(cx, cy, CHUNK, c, S.camera, view, linear);
    }
  }
}

function drawGround(scale) {
  const key = groundKey();
  const zooming = !!(zoomAnim || (camAnim && camAnim.z1));
  let projection = ground.zoom ? groundProjection(ground, S.camera, viewSize.w, viewSize.h, TW, TH) : null;
  // Reproject through a short portion of a smooth zoom, then refresh at native
  // resolution. Once the animation settles its exact final scale is rendered.
  const scaleReady = projection && (projection.scale === 1 || (zooming && projection.scale >= 0.875 && projection.scale <= 1.125));
  const covered = ground.canvas && projection && projection.covered && scaleReady;
  // Cached and complete: one copy. An incomplete layer (a tree or chunk still
  // loading) is also reused, but redrawn every quarter second until it is
  // complete: redrawing it every frame cost ~15 ms a frame at 8x.
  const dirty = ground.dirty;
  const smallPatch = dirty && ground.canvas && (dirty[2] - dirty[0]) * (dirty[3] - dirty[1]) < ground.canvas.width * ground.canvas.height / (viewSize.dpr * viewSize.dpr) * 0.35;
  if (covered && key === ground.key && smallPatch) patchGround(key);
  else if (!covered || dirty || !(key === ground.key || (key === ground.partialKey && performance.now() < ground.retryAt))) {
    const { w, h, dpr } = viewSize;
    const pw = Math.round((w + GROUND_PAD * 2) * dpr), ph = Math.round((h + GROUND_PAD * 2) * dpr);
    if (!ground.canvas) { ground.canvas = document.createElement('canvas'); ground.ctx = ground.canvas.getContext('2d'); }
    if (ground.canvas.width !== pw || ground.canvas.height !== ph) { ground.canvas.width = pw; ground.canvas.height = ph; }
    const g = ground.ctx;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, pw, ph);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    groundIncomplete = false;
    ctx = g;
    // Expand both projection and culling together so the border contains real
    // terrain and trees, including the height-field renderer and its fallback.
    viewSize.w = w + GROUND_PAD * 2; viewSize.h = h + GROUND_PAD * 2;
    try {
      ground.treeRange = visibleTileRange();
      ground.terrainRange = terrainRegion(ground.treeRange, CHUNK);
      ground.heightMapped = !!(flatMap && TG.available());
      const [gx, gy] = toScreen(0, 0);
      paintGround(gx, gy, scale);
    } finally { ctx = mainCtx; viewSize.w = w; viewSize.h = h; }
    ground.map = S.map;
    ground.x = S.camera.x; ground.y = S.camera.y; ground.zoom = S.camera.zoom;
    ground.width = w; ground.height = h;
    ground.dirty = null;
    ground.rev = (ground.rev || 0) + 1;
    projection = groundProjection(ground, S.camera, w, h, TW, TH);
    ground.key = groundIncomplete ? '' : key;
    ground.partialKey = groundIncomplete ? key : '';
    ground.retryAt = performance.now() + 250;
  }
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.imageSmoothingEnabled = true;
  const { x, y, scale: zoom } = projection;
  const grade = bakeGradeThisFrame && zoom === 1 && projection.covered ? gradeParams() : null;
  groundGraded = !!grade;
  if (grade) ctx.drawImage(gradedGround(grade), x * viewSize.dpr, y * viewSize.dpr);
  else if (zoom === 1) ctx.drawImage(ground.canvas, x * viewSize.dpr, y * viewSize.dpr);
  else ctx.drawImage(ground.canvas, x * viewSize.dpr, y * viewSize.dpr, ground.canvas.width * zoom, ground.canvas.height * zoom);
  ctx.restore();
}

// The colour grade baked into a copy of the cached ground (with the background
// under it), redone only when the ground repaints or the grade changes: the
// per-frame pass is three full-screen composites over the world canvas, one of
// them the non-separable 'saturation' blend. Used only when nothing else is on
// the world canvas before the grade (see bakeGradeAllowed), so the picture is
// the same as grading it every frame.
let bakeGradeThisFrame = false, groundGraded = false;
/** Was the grade baked into the ground in the last frame (performance view, checks). */
export function gradeBaked() { return groundGraded; }
const graded = { canvas: null, key: '' };
function gradedGround(g) {
  const w = ground.canvas.width, h = ground.canvas.height;
  const key = `${ground.rev}|${w}x${h}|${g.s}|${g.A}|${g.O.join(',')}`;
  if (graded.key === key && graded.canvas) return graded.canvas;
  graded.key = key;
  if (!graded.canvas) graded.canvas = document.createElement('canvas');
  if (graded.canvas.width !== w || graded.canvas.height !== h) { graded.canvas.width = w; graded.canvas.height = h; }
  const c = graded.canvas.getContext('2d');
  c.setTransform(1, 0, 0, 1, 0, 0);
  c.globalCompositeOperation = 'source-over';
  c.globalAlpha = 1;
  c.fillStyle = WORLD_BACKGROUND;
  c.fillRect(0, 0, w, h);
  c.drawImage(ground.canvas, 0, 0);
  applyGrade(c, w, h, g);
  return graded.canvas;
}
// Baking is exact when the world canvas holds only the background and the ground
// at grade time: GPU sprites (drawn and graded on their own layer), no distance
// haze (screen-space, applied before the grade), nothing selected (rings) and
// no spy fog (drawn on the world canvas).
function bakeGradeAllowed(useSprites, fog) {
  return useSprites && gpuLayers() && SG.available() && !!gradeParams() && !hazeActive()
    && S.selection.size === 0 && fog !== 'spy';
}

const WORLD_BACKGROUND = '#07080a';
let frameSerial = 0, fogRenderedFor = -1;
export function draw(dt = 1 / 60) {
  frameSerial++;
  groundGraded = false; bakeGradeThisFrame = false;
  const dpr = viewSize.dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = WORLD_BACKGROUND;
  ctx.fillRect(0, 0, viewSize.w, viewSize.h);
  stepCamera(performance.now());
  // Follow the same interpolated positions that this frame will draw.
  entityRows = interpolatedRows();
  followSelection(dt);
  pruneLastDrawn();
  if (!terrainCanvas) { layersOff(); fxaaPass(); return; }
  buildViewTerrain(); // once its textures are in (a no-op after that)
  decodeFog();
  buildFog();
  const z = S.camera.zoom;
  const [ox, oy] = toScreen(0, 0);
  const scale = (TW / TERRAIN_TW) * z;
  const tA = performance.now();
  bakeGradeThisFrame = bakeGradeAllowed(spritesOn(), fogState());
  drawGround(scale);
  const tB = performance.now();

  countingDraw = true;
  firstFrameSpritesPending = false;
  fireOwnedTiles.clear();
  sceneBegin();
  const sel = S.selection;
  const showIcons = z >= 1.15;
  const mask = perspectiveMask();
  const fog = fogState();
  // `c`/`op`: also over the particle layer ('source-atop': it shades what is there).
  const drawFog = (c = ctx, op = 'source-over') => {
    if (!fogCanvas) return;
    c.save();
    c.globalCompositeOperation = op;
    if (fogSmall && TG.available()) {
      // Over the ground surface, so fog follows the hills. Rendered once a frame:
      // the particle layer reuses the same picture.
      if (fogRenderedFor !== frameSerial) {
        fogRenderedFor = frameSerial;
        TG.begin(viewSize.w, viewSize.h, viewSize.dpr);
        TG.drawMapTexture('fog', fogSmall, S.camera, { w: viewSize.w, h: viewSize.h, tw: TW, th: TH }, visibleTileRange(), { linear: true, fog: true });
      }
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.drawImage(TG.output(), 0, 0);
    } else {
      const iso = fogIso();
      if (iso) c.drawImage(iso, ox, oy - mapW * TERRAIN_TH / 2 * scale, iso.width * scale, iso.height * scale);
    }
    c.restore();
  };
  // Spy: the land keeps the perspective's shading but every entity is drawn over it.
  if (fog === 'spy') drawFog();
  // Buildings first, then units (rough painter's order by screen y).
  const useSprites = spritesOn();
  // The GPU atlas may grow to the same budget as the decoded strips it copies from.
  if (useSprites) SG.setAtlasBudget(Number(settings.enhancedGraphics ? settings.atlasMemoryUhd : settings.atlasMemoryNormal) || 768);
  gpuTarget = useSprites && gpuLayers() && SG.begin(viewSize.w, viewSize.h, viewSize.dpr, spriteLook()) ? ctx : null;
  layered = false;
  const sorted = useSprites
    ? sortByKey(entityRows, depth)
    : sortByKey(entityRows, (r) => depth(r) - (r[6] & 1) * 1e6);
  const hidden = (r, px, py, u) => {
    const [, owner, , x, y, , flags] = r;
    const margin = flags & 1 ? Math.max(60, (u.size || 1) * TW * z * 1.4) : 60;
    if (px < -margin || py < -margin || px > viewSize.w + margin || py > viewSize.h + margin * 2) return true;
    if (fog === 'standard' && owner !== S.perspective && !(owner > 0 && sameTeam(owner) && S.combinedFog)) {
      const i = (Math.floor(y) * mapW + Math.floor(x)) * 2;
      if (!(fogBytes[i] & mask)) {
        if (!(flags & (1 | 512)) || !(fogBytes[i + 1] & mask)) return true; // buildings and cliffs stay visible once explored
      }
    }
    return false;
  };
  // What the dead leave (death animations, corpses, rubble) lies on the ground
  // under everything standing (view.remains: not units, never selected or counted).
  if (useSprites && S.view && S.view.remains) {
    const remains = sortByKey(S.view.remains, depth);
    for (const r of remains) {
      const [px, py] = entityScreen(r);
      if (hidden(r, px, py, entityInfo(r))) continue;
      if (sel.has(r[0])) drawSelection(r, px, py);
      drawSprites(r, px, py); // still loading: nothing, not a placeholder
    }
  }
  // Trees are drawn with the ground layer: a picked one gets its ring here.
  for (const id of sel) {
    if (!isTreeId(id)) continue;
    const r = treeRow(TREE_ID - id);
    if (r) drawSelection(r, ...entityScreen(r));
  }
  const track = useSprites && S.view && Array.isArray(S.view.missile_track) && S.view.missile_track.length ? S.view.missile_track : null;
  // Farms are ground: their fields go down before anything stands on them.
  for (const r of sorted) {
    const [id, owner, mid, , , , flags] = r;
    if (track && id < 0) continue; // projectiles: drawn from their track below
    const [px, py0] = entityScreen(r);
    // A town centre's annex parts stand half a tile and a tile in front of it but
    // the game draws their pictures from the centre's own spot (its main part gets
    // the same shift from its draw list): drawn at their own spot they sat 24/48 px
    // low and exposed the black inside the Khmer centre's walls.
    const py = py0 - (TC_ANNEX_LIFT[mid] || 0) * TH / 2 * S.camera.zoom;
    const u = entityInfo(r);
    if (hidden(r, px, py, u)) continue;
    if (px >= 0 && px <= viewSize.w && py >= 0 && py <= viewSize.h) sceneAdd(r, u, px);
    const color = owner === 0 ? gaiaColor(mid, u) : playerColor(owner);
    if (sel.has(id)) drawSelection(r, px, py);
    if (useSprites && drawSprites(r, px, py)) {
      // Bars sit just above the picture, as in the game (none over an invisible object).
      if (spriteTop != null) {
        const w = flags & 1 ? 40 * z : 18 * z, top = Math.max(spriteTop - 6, py - (flags & 1 ? 260 : 80) * z);
        // One bar per building, above its tallest part: a town centre's on its main
        // body (618), not on the low back part (the root, 109) or the annexes.
        const part = (TOWN_CENTER_PARTS.has(mid) && mid !== 618) || (TC_ROOTS.has(mid) && !(flags & 16)) || u.icon < 0;
        // With the GPU batch the pictures land after this loop: bars wait for them.
        if (part) { /* the main part carries the bar */ }
        else if (flags & 16) { if (gpuTarget) gpuBars.push([progressBar, px, top, w, constructionPct(r)]); else progressBar(px, top, w, constructionPct(r)); }
        else if (owner && showHp(r[5])) { if (gpuTarget) gpuBars.push([hpBar, px, top, w, r[5]]); else hpBar(px, top, w, r[5]); }
      }
      continue;
    }
    if (useSprites) {
      // Sprite still loading (a second or so after a seek): a faint shadow of the
      // footprint, or a small dot for a unit, never an outline or a badge that
      // reads as part of the game.
      if (flags & 1) {
        const sz = Math.max(1, u.size || 1);
        diamond(px, py, sz * TW / 2 * z, sz * TH / 2 * z);
        ctx.fillStyle = 'rgba(0,0,0,.18)'; ctx.fill();
      } else {
        ctx.fillStyle = color; ctx.globalAlpha = 0.7;
        ctx.beginPath(); ctx.arc(px, py - 4 * z, Math.max(1.5, 2.5 * z), 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 1;
      }
      continue;
    }
    if (flags & 1) drawBuilding(r, px, py, color, showIcons);
    else drawUnit(r, px, py, color, showIcons, owner === 0);
  }
  const tC = performance.now();
  if (useSprites) fxBegin();
  const tFx = performance.now();
  if (track) drawMissiles(track);
  if (gpuTarget) {
    SG.present(spriteLook());
    gpuTarget = null;
    // Everything drawn from here on lies over the sprites: the overlay canvas.
    ctx = overlayBegin();
    layered = true;
    for (const [fn, ...args] of gpuBars) fn(...args);
    gpuBars.length = 0;
  } else layersOff();
  const tMissiles = performance.now();
  countingDraw = false;
  if (!layered) drawOccludedOutlines(); // with the GPU batch: its own outline pass
  const tMasks = performance.now();
  if (useSprites) prefetchUpcoming();
  const tD = performance.now();
  drawTimes.fxClear += tFx - tC; drawTimes.missiles += tMissiles - tFx;
  drawTimes.masks += tMasks - tMissiles; drawTimes.readAhead += tD - tMasks;
  for (const [parts, r, px, py] of flameQueue) drawFlames(parts, r, px, py);
  flameQueue.length = 0;
  drawRangeCircles();
  if (useSprites && S.view && S.view.particles) drawParticles();
  if (fog === 'standard') { drawFog(); if (pctx !== mainCtx && fxDrawn) drawFog(pctx, 'source-atop'); }
  const tE = performance.now();
  drawTimes.ground += tB - tA; drawTimes.entities += tC - tB; drawTimes.outlines += tD - tC; drawTimes.effects += tE - tD; drawTimes.n++;
  // The passes below grade the world canvas (with layers: the ground; the sprite
  // shader grades the sprites, the overlay stays as drawn).
  ctx = mainCtx;
  bloomPass();
  channelPass();
  hazePass();
  gradePass();
  fxComposite(layered ? topCtx : mainCtx);
  drawTimes.post += performance.now() - tE;
  if (layered) ctx = topCtx;
  if (virtualCursor.locked) {
    ctx.fillStyle = '#fff'; ctx.strokeStyle = '#000';
    ctx.beginPath(); ctx.moveTo(virtualCursor.x, virtualCursor.y); ctx.lineTo(virtualCursor.x + 12, virtualCursor.y + 9); ctx.lineTo(virtualCursor.x + 5, virtualCursor.y + 11); ctx.closePath(); ctx.fill(); ctx.stroke();
  }
  ctx = mainCtx;
  fxaaPass();
}

// -- post-processing --------------------------------------------------------------------
// Bloom and the colour channels run as canvas filters built from small SVG
// filters (a bright pass and a colour matrix); each distinct parameter set gets
// its own filter element so the browser never reuses a stale compiled filter.

const svgFilterIds = new Map();
let svgRoot = null;
function svgFilter(kind, key, inner) {
  const full = `${kind}|${key}`;
  let fid = svgFilterIds.get(full);
  if (fid) return fid;
  if (!svgRoot) {
    svgRoot = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgRoot.setAttribute('width', '0'); svgRoot.setAttribute('height', '0');
    svgRoot.setAttribute('aria-hidden', 'true');
    svgRoot.classList.add('world-svg-filters');
    document.body.appendChild(svgRoot);
  }
  fid = `vantage-${kind}-${svgFilterIds.size}`;
  const f = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
  f.setAttribute('id', fid);
  f.setAttribute('color-interpolation-filters', 'sRGB');
  f.innerHTML = inner;
  svgRoot.appendChild(f);
  svgFilterIds.set(full, fid);
  if (svgFilterIds.size > 64) { svgFilterIds.clear(); svgRoot.replaceChildren(); return svgFilter(kind, key, inner); }
  return fid;
}

const canFilter = 'filter' in ctx;
let bloomCanvas = null, copyCanvas = null;

function scratch(c, w, h) {
  if (!c) c = document.createElement('canvas');
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  return c;
}

// Bloom: a bright pass above the threshold, blurred at a reduced resolution
// (quality: low 1/4, medium 1/2, high full), added back scaled by
// brightness x scale; postExtra.bloomEnable is the switch.
// A numeric quality is a blur-pass count (default 4): <= 2 low, 3-5 medium, more high.
export function bloomQualityLevel(q) {
  if (typeof q === 'string' && Number.isNaN(Number(q))) return q;
  const n = Number(q);
  return n <= 2 ? 'low' : n <= 5 ? 'medium' : 'high';
}
function bloomPass() {
  const p = postExtra();
  const amount = p.bloomEnable ? Number(p.bloomBrightness) || 0 : 0;
  if (amount <= 0 || !canFilter) return;
  const q = { low: 0.25, medium: 0.5, high: 1 }[bloomQualityLevel(p.bloomQuality)] || 0.5;
  const t = Math.max(0, Math.min(0.95, Number(p.bloomThreshold) || 0));
  const slope = 1 / (1 - t), icpt = -t / (1 - t);
  const funcs = ['R', 'G', 'B'].map((c) => `<feFunc${c} type="linear" slope="${slope}" intercept="${icpt}"/>`).join('');
  const fid = svgFilter('bright', t.toFixed(3), `<feComponentTransfer>${funcs}</feComponentTransfer>`);
  const w = Math.max(1, Math.round(canvas.width * q)), h = Math.max(1, Math.round(canvas.height * q));
  bloomCanvas = scratch(bloomCanvas, w, h);
  const bc = bloomCanvas.getContext('2d');
  bc.globalCompositeOperation = 'copy';
  const blur = Math.max(0, Number(p.bloomBlur) || 0) * q * viewSize.dpr;
  bc.filter = `url(#${fid})${blur > 0 ? ` blur(${blur.toFixed(2)}px)` : ''}`;
  bc.drawImage(canvas, 0, 0, w, h);
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = Math.min(1, amount * (Number(p.bloomScale) || 1) * 0.8);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(bloomCanvas, 0, 0, canvas.width, canvas.height);
  ctx.restore();
}

// -- the map's colour grade -------------------------------------------------------------
// The game's final pass (CombineTerrainSpriteSMP_ps): saturation about Rec.709
// luminance, contrast about 0.5, brightness, then a tint, from the map's preset
// (terrain/colorcorrection_json; the map script picks it). One colour matrix.
export function activeGrade() {
  const presets = (S.match && S.match.color_grades) || [];
  // A pick made for this game wins over the general one (the script may have
  // chosen the grade at random, so it can only be told per game).
  const byGame = (settings.colorGradeByGame || {})[gameKey()];
  const pick = byGame && byGame !== 'auto' ? byGame : settings.colorGrade;
  if (pick && pick !== 'auto') return presets.find((p) => p.name === pick) || null;
  const i = S.match && S.match.color_grade != null ? S.match.color_grade : 0;
  return presets[i] || null;
}
// The grade: the game's stage is saturation about the luma, contrast about 0.5,
// brightness, then a lerp towards the tint colour, i.e. c' = A * sat_s(c) + O with
// A = (1 - f) * b * k and O = (1 - f) * b * (1 - k) / 2 + f * T. It is done with
// three full-frame composite fills (a canvas filter or a CSS filter costs 20-60 ms a
// frame in Firefox): a 'saturation' blend of grey at alpha 1 - s (luma by the blend
// modes' Rec.601 weights, the shader's are Rec.709), a 'multiply' by A and an
// additive 'lighter' fill of O. Every preset has s <= 1.1, A < 1 and O >= -0.005;
// the rare s > 1 and the tiny negative offsets are left out.
// The game draws particles after its colour grade (a burning mill's flames kept
// their colour on a Misty map while the buildings around were graded; a
// mangonel's trail shows brighter than any graded colour can reach): they go to
// their own layer, which takes the fog like the world and is laid over it after
// the grade.
// fxDrawn: something was drawn on the particle layer this frame. A frame with
// no particles, flames or projectile trails skips the full-screen clear (when
// the layer is already empty), the fog over it and the composite.
let fxDrawn = false, fxDirty = false;
function fxBegin() {
  if (!fxLayer) fxLayer = document.createElement('canvas');
  if (fxLayer.width !== canvas.width || fxLayer.height !== canvas.height) { fxLayer.width = canvas.width; fxLayer.height = canvas.height; fxDirty = false; }
  pctx = fxLayer.getContext('2d');
  pctx.setTransform(1, 0, 0, 1, 0, 0);
  if (fxDirty) pctx.clearRect(0, 0, fxLayer.width, fxLayer.height);
  fxDirty = false; fxDrawn = false;
  pctx.setTransform(viewSize.dpr, 0, 0, viewSize.dpr, 0, 0);
}
function fxComposite(target = mainCtx) {
  if (pctx === mainCtx) return;
  if (!fxDrawn) { pctx = mainCtx; return; }
  fxDirty = true;
  target.save();
  target.setTransform(1, 0, 0, 1, 0, 0);
  target.drawImage(fxLayer, 0, 0);
  target.restore();
  pctx = mainCtx;
}

/** The active grade as the pass applies it: saturation s, scale A and offset O
 * (bytes, as filled), or null when it changes nothing. */
function gradeParams() {
  const p = activeGrade();
  if (!p) return null;
  const s = Math.min(1, num(p.saturation, 1)), k = num(p.contrast, 1), b = num(p.brightness, 1);
  const f = Math.max(0, Math.min(1, num(p.tint_factor, 0)));
  const T = Array.isArray(p.tint_color) ? p.tint_color : [1, 1, 1];
  const byte = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255);
  const A = Math.min(255, byte((1 - f) * b * k)) / 255;
  const O = [0, 1, 2].map((i) => byte((1 - f) * b * 0.5 * (1 - k) + f * num(T[i], 1)));
  if (s >= 1 && A >= 1 && O.every((v) => v === 0)) return null;
  return { s, A, O, key: `${s}|${A}|${O.join(',')}` };
}
function gradePass() {
  const g = gradeParams();
  if (!g || groundGraded) return; // baked into the ground this frame
  applyGrade(ctx, canvas.width, canvas.height, g);
}
function applyGrade(ctx, w, h, g) {
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  if (g.s < 1) {
    ctx.globalCompositeOperation = 'saturation';
    ctx.globalAlpha = 1 - g.s;
    ctx.fillStyle = '#808080';
    ctx.fillRect(0, 0, w, h);
    ctx.globalAlpha = 1;
  }
  if (g.A < 1) {
    const v = Math.round(g.A * 255);
    ctx.globalCompositeOperation = 'multiply';
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.fillRect(0, 0, w, h);
  }
  if (g.O.some((v) => v > 0)) {
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = `rgb(${g.O.join(',')})`;
    ctx.fillRect(0, 0, w, h);
  }
  ctx.restore();
}
// Distance haze (the shader's distance fog): the preset's colour times its visible
// intensity, added most at the top of the view and fading to nothing at the
// bottom ((1 - v) of the screen). Applied before the grade, as the game does.
function hazeActive() {
  const p = activeGrade();
  if (!p || settings.distanceHaze === false) return false;
  return Array.isArray(p.distance_fog_color) && num(p.distance_fog_visible_intensity, 0) > 0;
}
function hazePass() {
  const p = activeGrade();
  if (!p || settings.distanceHaze === false) return;
  const c = Array.isArray(p.distance_fog_color) ? p.distance_fog_color : null;
  const k = num(p.distance_fog_visible_intensity, 0);
  if (!c || k <= 0) return;
  const rgb = c.map((v) => Math.round(Math.max(0, Math.min(1, v * k)) * 255));
  const g = ctx.createLinearGradient(0, 0, 0, viewSize.h);
  g.addColorStop(0, `rgb(${rgb.join(',')})`);
  g.addColorStop(1, 'rgb(0,0,0)');
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, viewSize.w, viewSize.h);
  ctx.restore();
}

// The game lights terrain (not sprites) by diffuse x lightmap + ambient + base light
// colours computed at run time; measured against the game on a flat, fully lit
// 6-player map: 1.2 (with the map's grade and haze modelled).
const TERRAIN_LIGHT = 1.2;
/** The preset's terrain tint times the terrain light (the game multiplies terrain by both). */
export function terrainTint() {
  const p = activeGrade();
  const t = p && Array.isArray(p.terrain_tint_color) ? p.terrain_tint_color : [1, 1, 1];
  return t.map((v) => v * TERRAIN_LIGHT);
}

// Per-channel red/green/blue gain and world opacity, as one colour matrix.
function channelPass() {
  const p = postExtra();
  const r = num(p.red, 1), g = num(p.green, 1), b = num(p.blue, 1), a = num(p.alpha, 1);
  if (r === 1 && g === 1 && b === 1 && a === 1) return;
  copyCanvas = scratch(copyCanvas, canvas.width, canvas.height);
  const cc = copyCanvas.getContext('2d');
  cc.globalCompositeOperation = 'copy';
  cc.drawImage(canvas, 0, 0);
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = 'copy';
  if (canFilter) {
    const m = `${r} 0 0 0 0  0 ${g} 0 0 0  0 0 ${b} 0 0  0 0 0 ${a} 0`;
    ctx.filter = `url(#${svgFilter('channels', m, `<feColorMatrix type="matrix" values="${m}"/>`)})`;
  } else {
    ctx.globalAlpha = a;
  }
  ctx.drawImage(copyCanvas, 0, 0);
  ctx.restore();
}

function num(v, d) {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

// FXAA: the finished frame is uploaded to a WebGL canvas stacked over the world
// canvas and filtered with the classic FXAA edge pass (luma edge direction,
// two- and four-tap blends along it, rejecting the wide blend when it leaves
// the local luma range). The 2D canvas keeps receiving input; the GL canvas
// ignores the pointer and copies the world canvas's CSS filters.
let fx = null;
const FXAA_VS = 'attribute vec2 a;varying vec2 v;void main(){v=vec2(a.x*.5+.5,.5-a.y*.5);gl_Position=vec4(a,0.,1.);}';
const FXAA_FS = `precision mediump float;uniform sampler2D t;uniform vec2 px;varying vec2 v;
void main(){vec3 L=vec3(.299,.587,.114);vec4 c=texture2D(t,v);
float nw=dot(texture2D(t,v+vec2(-1.,-1.)*px).rgb,L),ne=dot(texture2D(t,v+vec2(1.,-1.)*px).rgb,L);
float sw=dot(texture2D(t,v+vec2(-1.,1.)*px).rgb,L),se=dot(texture2D(t,v+vec2(1.,1.)*px).rgb,L),m=dot(c.rgb,L);
float lo=min(m,min(min(nw,ne),min(sw,se))),hi=max(m,max(max(nw,ne),max(sw,se)));
vec2 d=vec2(-((nw+ne)-(sw+se)),(nw+sw)-(ne+se));
float r=max((nw+ne+sw+se)*(.25/8.),1./128.);float k=1./(min(abs(d.x),abs(d.y))+r);
d=clamp(d*k,vec2(-8.),vec2(8.))*px;
vec3 a=.5*(texture2D(t,v+d*(1./3.-.5)).rgb+texture2D(t,v+d*(2./3.-.5)).rgb);
vec3 b=a*.5+.25*(texture2D(t,v-d*.5).rgb+texture2D(t,v+d*.5).rgb);
float lb=dot(b,L);gl_FragColor=vec4((lb<lo||lb>hi)?a:b,c.a);}`;

function initFxaa() {
  const c = document.createElement('canvas');
  c.id = 'world-fx';
  const gl = c.getContext('webgl', { premultipliedAlpha: false, alpha: true, antialias: false });
  if (!gl) return null;
  const sh = (type, src) => {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const vs = sh(gl.VERTEX_SHADER, FXAA_VS), fs = sh(gl.FRAGMENT_SHADER, FXAA_FS);
  if (!vs || !fs) return null;
  const prog = gl.createProgram();
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  canvas.after(c);
  return { c, gl, px: gl.getUniformLocation(prog, 'px') };
}

function fxaaPass() {
  const on = !!postExtra().fxaa && terrainCanvas;
  if (!on) { if (fx) fx.c.classList.remove('on'); return; }
  if (fx === null) fx = initFxaa() || false;
  if (!fx) return; // no WebGL: plain picture
  const { c, gl } = fx;
  if (c.width !== canvas.width || c.height !== canvas.height) { c.width = canvas.width; c.height = canvas.height; }
  c.style.filter = canvas.style.filter;
  c.classList.add('on');
  gl.viewport(0, 0, c.width, c.height);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
  gl.uniform2f(fx.px, 1 / c.width, 1 / c.height);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}

function sameTeam(pid) {
  const me = S.match.players[S.perspective], p = S.match.players[pid];
  return me && p && me.team_key === p.team_key;
}

function treeSprite(x, y) {
  const mid = treeKinds[treeTiles[y * mapW + x] - 1];
  const u = S.catalog.units[mid];
  if (!u || u.sprite == null || u.sprite < 0) return null;
  // The facet is the variant the game draws for this tree (see tree_tiles).
  const facet = treeFacets ? treeFacets[y * mapW + x] : 0;
  const e = spriteStrip(u.sprite, facet, -1);
  return treeSpriteState(e);
}

function drawTreesWorld() {
  const z = S.camera.zoom;
  if (z < 0.35) return; // trees already baked into the minimap layer; skip when far out
  if (spritesOn()) { drawTreeSprites(); return; }
  ctx.fillStyle = 'rgba(16,48,18,0.78)';
  const [x0, y0] = toWorld(0, 0), [x1, y1] = toWorld(viewSize.w, viewSize.h);
  const [x2, y2] = toWorld(viewSize.w, 0), [x3, y3] = toWorld(0, viewSize.h);
  const minX = Math.max(0, Math.floor(Math.min(x0, x1, x2, x3)) - 1), maxX = Math.min(mapW - 1, Math.ceil(Math.max(x0, x1, x2, x3)) + 1);
  const minY = Math.max(0, Math.floor(Math.min(y0, y1, y2, y3)) - 1), maxY = Math.min(mapH - 1, Math.ceil(Math.max(y0, y1, y2, y3)) + 1);
  const r = TW / 2 * z * 0.42;
  ctx.beginPath();
  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      if (!treeTiles[y * mapW + x]) continue;
      const [px, py] = groundScreen(x + 0.5, y + 0.5);
      ctx.moveTo(px + r, py);
      ctx.ellipse(px, py, r, r * 0.7, 0, 0, Math.PI * 2);
    }
  }
  ctx.fill();
}

const GAIA_COLORS = { 32: '#f2c94c', 8: '#b9bcc0', 7: '#e26ec2', 33: '#6fc6e8', 5: '#6fc6e8', 31: '#6fc6e8', 9: '#d6b37a', 10: '#a85a3a', 1: '#ffffff', 42: '#ffffff', 29: '#e8e1d0', 48: '#f2c94c' };
const GAIA_STRUCTURE = '#b49a6c'; // bridges and other Gaia buildings
function gaiaColor(mid, info) {
  const u = info || unitInfo(mid);
  if (u.kind === 'building') return GAIA_STRUCTURE;
  return GAIA_COLORS[u.cls] || '#bbb';
}

function diamond(px, py, hw, hh) {
  ctx.beginPath();
  ctx.moveTo(px - hw, py); ctx.lineTo(px, py - hh); ctx.lineTo(px + hw, py); ctx.lineTo(px, py + hh);
  ctx.closePath();
}

function drawBuilding(r, px, py, color, showIcons) {
  const u = entityInfo(r);
  const size = Math.max(1, u.size || 1);
  const z = S.camera.zoom;
  const hw = size * TW / 2 * z, hh = size * TH / 2 * z;
  const foundation = r[6] & 16;
  const pct = foundation ? constructionPct(r) : 1;
  diamond(px, py, hw, hh);
  if (u.cls === 49) { // farm: a field with an owner-coloured edge
    ctx.fillStyle = foundation ? 'rgba(150,120,70,.25)' : 'rgba(176,140,74,.55)';
    ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = color; ctx.globalAlpha = 0.7; ctx.stroke(); ctx.globalAlpha = 1;
    return;
  }
  if (u.cls === 27 || u.cls === 39) { // walls and gates: solid
    ctx.fillStyle = color; ctx.globalAlpha = foundation ? 0.2 + 0.5 * pct : 0.95; ctx.fill(); ctx.globalAlpha = 1;
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(0,0,0,.6)'; ctx.stroke();
    return;
  }
  ctx.fillStyle = color;
  // Foundations fill in as they are built; unstarted ones are a faint ghost.
  ctx.globalAlpha = foundation ? 0.1 + 0.3 * pct : 0.42;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.lineWidth = Math.max(1, 1.5 * Math.min(2, z));
  ctx.strokeStyle = color;
  if (foundation) ctx.setLineDash([4, 3]);
  ctx.stroke();
  ctx.setLineDash([]);
  if (showIcons) {
    const im = img(unitIcon(r[2], r[1], r[0]));
    if (im) {
      const s = Math.min(hw * 0.75, 14 + 14 * z);
      if (foundation && pct <= 0.001) ctx.globalAlpha = 0.5;
      ctx.drawImage(im, px - s / 2, py - s / 2, s, s);
      ctx.globalAlpha = 1;
      ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.strokeRect(px - s / 2, py - s / 2, s, s);
    }
  } else {
    ctx.fillStyle = color;
    diamond(px, py, hw * 0.35, hh * 0.35);
    ctx.fill();
  }
  if (z < 0.6) return;
  if (foundation) progressBar(px, py - hh - 4, hw * 1.2, pct);
  else if (showHp(r[5])) hpBar(px, py - hh - 4, hw * 1.2, r[5]);
}

function drawUnit(r, px, py, color, showIcons, gaia) {
  const z = S.camera.zoom;
  const flags = r[6];
  const rad = Math.max(2, (gaia ? 0.32 : 0.3) * TW / 2 * z * (flags & 2 ? 1.15 : 1));
  if (showIcons && !gaia) {
    const im = img(unitIcon(r[2], r[1], r[0]));
    const s = rad * 2.4;
    ctx.save();
    ctx.beginPath(); ctx.arc(px, py, s / 2, 0, Math.PI * 2); ctx.closePath();
    ctx.fillStyle = color; ctx.fill();
    if (im) { ctx.clip(); ctx.drawImage(im, px - s / 2 + 2, py - s / 2 + 2, s - 4, s - 4); }
    ctx.restore();
    ctx.lineWidth = 2; ctx.strokeStyle = color;
    ctx.beginPath(); ctx.arc(px, py, s / 2, 0, Math.PI * 2); ctx.stroke();
    if (showHp(r[5])) hpBar(px, py - s / 2 - 4, s, r[5]);
    return;
  }
  ctx.beginPath();
  if (gaia) ctx.rect(px - rad, py - rad * 0.7, rad * 2, rad * 1.4);
  else ctx.arc(px, py, rad, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  if (!gaia) { ctx.lineWidth = 1; ctx.strokeStyle = (flags & 8) ? '#fff' : 'rgba(0,0,0,.7)'; ctx.stroke(); }
}

// Health bars, as the game's own option: only damaged (default), always or never.
function showHp(frac) {
  const mode = settings.healthBars || 'damaged';
  return mode === 'always' || (mode === 'damaged' && frac < 0.999);
}

function hpBar(px, py, w, frac) {
  ctx.fillStyle = 'rgba(0,0,0,.7)';
  ctx.fillRect(px - w / 2, py, w, 3);
  ctx.fillStyle = frac > 0.5 ? '#6fd36a' : frac > 0.25 ? '#e8c341' : '#e05a4a';
  ctx.fillRect(px - w / 2, py, w * frac, 3);
}

function drawSelection(r, px, py) {
  const u = entityInfo(r);
  const z = S.camera.zoom;
  const size = (r[6] & 1) ? Math.max(1, u.size || 1) : 0.8;
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = '#fff';
  ctx.beginPath();
  ctx.ellipse(px, py, size * TW / 2 * z * 0.75, size * TH / 2 * z * 0.75, 0, 0, Math.PI * 2);
  ctx.stroke();
}

// -- range circles ------------------------------------------------------------------------
// Weapon range (filled for the selection, so overlapping zones read as a heat
// map), the minimum-range dead zone, work and aura ranges, and the square
// effect areas of the Folwark and Caravanserai. Ranges come from the catalog's
// stats (range, min_range, work_range, aura_range); for selected entities the
// owner-specific numbers from /api/unit/<id> win when the server provides them.

const CARAVANSERAI = 1754;
const TOWN_CENTER_PARTS = new Set([618, 619, 620]); // annex graphics of one town centre
const TC_ROOTS = new Set([109]); // the town centre object itself (its back part's graphic)
// Draw order: screen depth (y - x). A town centre's root carries its back and floor
// pictures, which the game lays under the main body (whose spot is two tiles of
// depth behind the root's); sorted by its own spot it covered the body's base.
function depth(r) { return r[4] - r[3] - (TC_ROOTS.has(r[2]) ? 2.5 : 0); }
// Annex part -> its offset from the centre in half tiles of screen height (y - x).
const TC_ANNEX_LIFT = { 619: 1, 620: 2 };
// Square effect areas, as tiles from the building's centre. The Caravanserai's
// is its aura task's work range (8) beyond its edge. The Folwark is whichever
// master the owner's folwarkBuildingId names (the Mill id, 68, for the Poles);
// a new farm pays when its centre is within folwark_reach (4, measured on
// recorded games) of the Folwark's centre, so the square covers exactly the
// farms that pay: reach + half a farm (1.5).
const FARM_HALF = 1.5;
function squareArea(r, half) {
  if (r[2] === CARAVANSERAI) return half + 8;
  const p = S.view && S.view.players && S.view.players[r[1]];
  if (p && p.folwark_building != null && p.folwark_building === r[2]) return (p.folwark_reach || 4) + FARM_HALF;
  return null;
}
const RANGE_KEYS = ['range', 'min_range', 'work_range', 'aura_range'];
const unitDetails = new Map();
let detailRequests = 0;

function unitDetail(r) {
  const generation = S.session && S.session.generation;
  const at = Math.round(S.view && Number.isFinite(S.view.time) ? S.view.time : S.t);
  const key = `${generation}:${r[0]}`, now = performance.now();
  let c = unitDetails.get(key);
  if (!c) {
    if (unitDetails.size > 128) unitDetails.delete(unitDetails.keys().next().value);
    c = { data: null, queryAt: null, started: 0, sequence: 0, pending: false, failed: false };
    unitDetails.set(key, c);
  }
  const valid = entityStatsValid(c.data, r[0], r, at, generation, c.queryAt);
  if (!c.pending && detailRequests < 4 && (!valid || now - c.started >= 1000)
      && (!c.failed || now - c.started >= 1000)) {
    c.started = now; c.pending = true; c.failed = false; detailRequests++;
    const sequence = ++c.sequence;
    api(`/api/unit/${r[0]}?t=${at}`).then((d) => {
      if (unitDetails.get(key) !== c || c.sequence !== sequence
          || (S.session && S.session.generation) !== generation) return;
      if ((d.entity_stats_validity_version === 1 && d.generation !== generation)
          || (d.generation != null && d.generation !== generation)) { c.failed = true; return; }
      c.data = d; c.queryAt = at;
    }).catch(() => { c.failed = true; }).finally(() => {
      detailRequests--;
      if (unitDetails.get(key) === c && c.sequence === sequence) c.pending = false;
    });
  }
  if (!valid) return null;
  const out = {};
  for (const k of RANGE_KEYS) if (typeof c.data[k] === 'number') out[k] = c.data[k];
  return out;
}

function rangeEllipse(px, py, tiles) {
  const z = S.camera.zoom;
  ctx.beginPath();
  ctx.ellipse(px, py, tiles * TW / 2 * z * Math.SQRT2, tiles * TH / 2 * z * Math.SQRT2, 0, 0, Math.PI * 2);
}

// Zones of one colour are filled once as a union and outlined only where they
// reach beyond every other zone of that colour, so overlaps stay as clear as a
// single zone instead of stacking into a darker, busier patch.
const zoneLayer = document.createElement('canvas');
function ellipsePath(path, px, py, tiles) {
  const z = S.camera.zoom;
  path.moveTo(px + tiles * TW / 2 * z * Math.SQRT2, py);
  path.ellipse(px, py, tiles * TW / 2 * z * Math.SQRT2, tiles * TH / 2 * z * Math.SQRT2, 0, 0, Math.PI * 2);
}
function squarePath(path, x, y, h) {
  [[x - h, y - h], [x + h, y - h], [x + h, y + h], [x - h, y + h]]
    .map(([a, b]) => groundScreen(a, b))
    .forEach(([px, py], i) => (i ? path.lineTo(px, py) : path.moveTo(px, py)));
  path.closePath();
}
function drawZones(zones) {
  if (!zones.size) return;
  if (zoneLayer.width !== canvas.width || zoneLayer.height !== canvas.height) {
    zoneLayer.width = canvas.width; zoneLayer.height = canvas.height;
  }
  const lc = zoneLayer.getContext('2d');
  const base = ctx.getTransform();
  for (const zone of zones.values()) {
    // Outline: every outline in full, then everything inside the union removed.
    lc.setTransform(1, 0, 0, 1, 0, 0);
    lc.clearRect(0, 0, zoneLayer.width, zoneLayer.height);
    lc.setTransform(base);
    lc.globalCompositeOperation = 'source-over';
    lc.globalAlpha = 1;
    lc.strokeStyle = zone.color; lc.lineWidth = 2;
    lc.stroke(zone.path);
    lc.globalCompositeOperation = 'destination-out';
    lc.fill(zone.path);
    if (zone.stroke) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = zone.stroke;
      ctx.drawImage(zoneLayer, 0, 0);
      ctx.restore();
    }
    if (zone.fill) {
      ctx.globalAlpha = zone.fill; ctx.fillStyle = zone.color; ctx.fill(zone.path);
    }
  }
  ctx.globalAlpha = 1;
}

function drawRangeCircles() {
  if (!S.rangeCircles) return;
  const z = S.camera.zoom;
  const bMode = settings.rangeCircleModeBuildings || 'always';
  const sMode = settings.rangeCircleModeSelectedEntities || 'always';
  ctx.save();
  const zones = new Map();
  const zoneOf = (kind, color, fill, stroke) => {
    const key = `${kind}|${color}|${fill}|${stroke}`;
    let zone = zones.get(key);
    if (!zone) zones.set(key, (zone = { path: new Path2D(), color, fill, stroke }));
    return zone.path;
  };
  for (const r of entityRows) {
    const selected = S.selection.has(r[0]);
    const building = r[6] & 1;
    if ((r[6] & 16) || TOWN_CENTER_PARTS.has(r[2])) continue; // foundations do not act yet
    const show = building ? bMode === 'always' || (bMode === 'selected' && selected) : selected && sMode !== 'none';
    if (!show) continue;
    const u = entityInfo(r);
    const st = { ...(u.stats || {}), ...(selected ? unitDetail(r) || {} : {}) };
    const half = building ? Math.max(1, u.size || 1) / 2 : 0;
    const square = squareArea(r, half);
    const reach = Math.max(st.range || 0, st.work_range || 0, st.aura_range || 0, square || 0);
    if (reach < 1 && square == null) continue;
    const [px, py] = entityScreen(r);
    const m = (reach + (u.size || 1)) * TW * z;
    if (px < -m || py < -m || px > viewSize.w + m || py > viewSize.h + m) continue;
    const color = r[1] ? playerColor(r[1]) : '#ccc';
    const alpha = selected ? 0.8 : 0.35;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    if ((st.range || 0) >= 1.5) {
      ellipsePath(zoneOf('range', color, selected ? 0.07 : 0, alpha), px, py, st.range + half);
    }
    if ((st.min_range || 0) > 0) {
      // Dead zone: units closer than this cannot be hit.
      ellipsePath(zoneOf('dead', '#e05a4a', selected ? 0.16 : 0.08, 0), px, py, st.min_range + half);
      rangeEllipse(px, py, st.min_range + half);
      ctx.setLineDash([5, 4]); ctx.globalAlpha = alpha; ctx.strokeStyle = '#e05a4a'; ctx.stroke();
      ctx.setLineDash([]);
    }
    if ((st.work_range || 0) > 1) {
      rangeEllipse(px, py, st.work_range + half);
      ctx.setLineDash([2, 4]); ctx.globalAlpha = alpha; ctx.strokeStyle = '#7fd3e6'; ctx.stroke();
      ctx.setLineDash([]);
    }
    if (square != null) {
      squarePath(zoneOf('area', '#f2c94c', selected ? 0.12 : 0.06, alpha), r[3], r[4],
        r[2] === CARAVANSERAI ? half + (st.aura_range || 8) : square);
    } else if ((st.aura_range || 0) > 1) {
      rangeEllipse(px, py, st.aura_range + half);
      ctx.setLineDash([6, 3, 1, 3]); ctx.globalAlpha = alpha; ctx.strokeStyle = '#f2c94c'; ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.globalAlpha = 1;
  }
  drawZones(zones);
  ctx.restore();
}

// -- minimap ----------------------------------------------------------------------
// Base minimap space is the whole map squeezed into the canvas; the wheel zooms
// it (1-6x) around the camera, clamped so the view never leaves the map.

const miniView = { zoom: 1, cx: 0, cy: 0, W: 1, H: 1 };

function miniBase(x, y) {
  const s = mapW + mapH;
  return [(x + y) * miniView.W / s, (y - x) * miniView.H / s + mapW * miniView.H / s];
}

function updateMiniView(W, H) {
  miniView.W = W; miniView.H = H;
  const z = miniView.zoom;
  if (z <= 1 || !mapW) { miniView.zoom = 1; miniView.cx = W / 2; miniView.cy = H / 2; return; }
  const [cx, cy] = miniBase(S.camera.x, S.camera.y);
  const hw = W / (2 * z), hh = H / (2 * z);
  miniView.cx = Math.max(hw, Math.min(W - hw, cx));
  miniView.cy = Math.max(hh, Math.min(H - hh, cy));
}

// The minimap in layers, each kept in a canvas of the minimap's own size: the
// ground (redrawn when the terrain, the size or the minimap zoom changes), the
// fog (when it or the zoom changes) and the entities (at most MINI_ENTITY_HZ).
// Only the camera frame is drawn every frame. Redrawn whole, the minimap scaled
// two map-sized canvases down and drew ~2,500 entities one by one per frame.
const MINI_ENTITY_HZ = 15;
const miniLayers = { bg: null, bgKey: '', fog: null, fogKey: '', ents: null, entsKey: '', entsAt: 0 };
function miniLayer(c) {
  if (!c) c = document.createElement('canvas');
  if (c.width !== mini.width || c.height !== mini.height) { c.width = mini.width; c.height = mini.height; }
  return c;
}
// Minimap space (CSS px of the base minimap) -> the layer's device pixels.
function miniTransform(c, W, H) {
  const dpr = viewSize.dpr, z = miniView.zoom;
  c.setTransform(dpr * z, 0, 0, dpr * z, dpr * (W / 2 - miniView.cx * z), dpr * (H / 2 - miniView.cy * z));
}

export function drawMinimap() {
  refreshMiniTerrain();
  const dpr = viewSize.dpr;
  const W = mini.width / dpr, H = mini.height / dpr;
  mctx.setTransform(1, 0, 0, 1, 0, 0);
  mctx.clearRect(0, 0, mini.width, mini.height);
  if (!miniTerrain) return;
  updateMiniView(W, H);
  const z = miniView.zoom;
  const frame = `${W}|${H}|${dpr}|${z}|${miniView.cx}|${miniView.cy}`;
  const mode = S.minimapMode;
  const mask = perspectiveMask();
  const fog = fogState();
  // Ground: the costly layer (a map-sized canvas scaled down), so it holds no entities.
  const bgKey = `${frame}|${miniTerrainRev}`;
  if (bgKey !== miniLayers.bgKey) {
    miniLayers.bgKey = bgKey;
    const c = (miniLayers.bg = miniLayer(miniLayers.bg)).getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, mini.width, mini.height);
    miniTransform(c, W, H);
    c.imageSmoothingEnabled = true;
    c.drawImage(miniTerrain, 0, 0, W, H);
  }
  mctx.drawImage(miniLayers.bg, 0, 0);
  // Fog, scaled down from the map-sized canvas once per change.
  const fogLayer = () => {
    if (!fogCanvas) return null;
    const key = `${frame}|${fogRev}`;
    if (key !== miniLayers.fogKey) {
      miniLayers.fogKey = key;
      const c = (miniLayers.fog = miniLayer(miniLayers.fog)).getContext('2d');
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, mini.width, mini.height);
      miniTransform(c, W, H);
      // Clip to the map's diamond, then draw the map-space fog with its edge
      // pixels repeated one tile out: sampled at the very edge it went
      // half-transparent and left a dotted outline around the map.
      const corners = [[0, 0], [mapW, 0], [mapW, mapH], [0, mapH]].map(([a, b]) => miniBase(a, b));
      c.beginPath();
      corners.forEach(([px, py], i) => (i ? c.lineTo(px, py) : c.moveTo(px, py)));
      c.closePath();
      c.clip();
      // Tile (x, y) of the map-space fog -> miniBase(x, y): an affine map.
      const sxy = mapW + mapH;
      c.transform(W / sxy, -H / sxy, W / sxy, H / sxy, 0, mapW * H / sxy);
      c.imageSmoothingEnabled = true;
      c.globalAlpha = 0.85;
      c.drawImage(paddedFog(), -1, -1);
    }
    return miniLayers.fog;
  };
  if (fog === 'spy') { const f = fogLayer(); if (f) mctx.drawImage(f, 0, 0); }
  // Entities: at most MINI_ENTITY_HZ, sooner when the minimap itself changed.
  const now = performance.now();
  const entsKey = `${frame}|${mode}|${fog}|${mask}|${S.perspective}|${S.combinedFog}`;
  if (entsKey !== miniLayers.entsKey || now - miniLayers.entsAt >= 1000 / MINI_ENTITY_HZ) {
    miniLayers.entsKey = entsKey;
    miniLayers.entsAt = now;
    const c = (miniLayers.ents = miniLayer(miniLayers.ents)).getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, mini.width, mini.height);
    miniTransform(c, W, H);
    // Gaia structures (bridges) first, as footprints under the icons.
    if (mode !== 'military') drawMiniGaiaStructures(c, z);
    drawMiniEntities(c, z, mode, fog, mask);
  }
  mctx.drawImage(miniLayers.ents, 0, 0);
  if (fog === 'standard') { const f = fogLayer(); if (f) mctx.drawImage(f, 0, 0); }
  // camera viewport
  miniTransform(mctx, W, H);
  const corners = [toWorld(0, 0), toWorld(viewSize.w, 0), toWorld(viewSize.w, viewSize.h), toWorld(0, viewSize.h)];
  mctx.strokeStyle = 'rgba(255,255,255,.9)';
  mctx.lineWidth = 1 / z;
  mctx.beginPath();
  corners.forEach(([x, y], i) => { const [px, py] = miniBase(x, y); if (i) mctx.lineTo(px, py); else mctx.moveTo(px, py); });
  mctx.closePath();
  mctx.stroke();
}

function drawMiniGaiaStructures(c, z) {
  for (const r of entityRows) {
    if (r[1] !== 0) continue;
    const u = entityInfo(r);
    if (u.kind !== 'building') continue;
    const h = Math.max(1, u.size || 1) / 2;
    const pts = [[r[3] - h, r[4] - h], [r[3] + h, r[4] - h], [r[3] + h, r[4] + h], [r[3] - h, r[4] + h]].map(([a, b]) => miniBase(a, b));
    c.beginPath();
    pts.forEach(([px, py], i) => (i ? c.lineTo(px, py) : c.moveTo(px, py)));
    c.closePath();
    c.fillStyle = GAIA_STRUCTURE; c.fill();
    c.lineWidth = 0.6 / z; c.strokeStyle = 'rgba(40,28,14,.8)'; c.stroke();
  }
}

// Entity marks, in the order the minimap always drew them (each mark's fill then
// its outline, so a later mark covers an earlier one's outline). Into the cached
// entity layer, at most MINI_ENTITY_HZ: the saving is the rate, not the order.
function drawMiniEntities(c, z, mode, fog, mask) {
  const k = 1 / Math.sqrt(z); // icons grow gently when zoomed in
  const sx = (miniView.W || 1) / (mapW + mapH);
  c.lineWidth = 0.7 * k;
  for (const r of entityRows) {
    const [, owner, mid, x, y, , flags] = r;
    if (owner === 0) {
      if (mode === 'military' || (flags & 512)) continue; // scenery (cliffs) is not marked
      const u = entityInfo(r);
      if (u.cls === 15 || u.kind === 'building') continue;
      c.fillStyle = gaiaColor(mid, u);
      const [px, py] = miniBase(x, y);
      c.fillRect(px - k, py - k, 2 * k, 2 * k);
      continue;
    }
    if (mode === 'military' && !(flags & 2) && !(flags & 1)) continue;
    if (mode === 'resource' && (flags & 2)) continue;
    if (fog === 'standard' && owner !== S.perspective) {
      const i = (Math.floor(y) * mapW + Math.floor(x)) * 2;
      if (!(fogBytes[i] & mask)) continue;
    }
    const [px, py] = miniBase(x, y);
    const color = playerColor(owner, 'minimap');
    if (flags & 1) {
      const u = entityInfo(r);
      const s = Math.max(3.2 * k, Math.max(1, u.size || 1) * sx * 1.1);
      if (flags & 16) {
        // Foundation: an outlined box filling up (bottom to top) as it is built.
        const pct = constructionPct(r);
        c.fillStyle = 'rgba(0,0,0,.55)'; c.fillRect(px - s / 2, py - s / 2, s, s);
        c.fillStyle = color; c.fillRect(px - s / 2, py + s / 2 - s * pct, s, s * pct);
        c.strokeStyle = color; c.strokeRect(px - s / 2, py - s / 2, s, s);
      } else {
        c.fillStyle = color; c.fillRect(px - s / 2, py - s / 2, s, s);
        c.strokeStyle = 'rgba(0,0,0,.9)'; c.strokeRect(px - s / 2, py - s / 2, s, s);
      }
    } else {
      const s = (flags & 2 ? 2.6 : 2.1) * k;
      c.fillStyle = color; c.fillRect(px - s / 2, py - s / 2, s, s);
      c.strokeStyle = 'rgba(0,0,0,.85)'; c.strokeRect(px - s / 2, py - s / 2, s, s);
    }
  }
}

function minimapToWorld(ev) {
  const r = mini.getBoundingClientRect();
  const W = r.width, H = r.height;
  const z = miniView.zoom;
  // Screen -> base minimap space -> map tile.
  const bx = (ev.clientX - r.left - W / 2) / z + (z > 1 ? miniView.cx : W / 2);
  const by = (ev.clientY - r.top - H / 2) / z + (z > 1 ? miniView.cy : H / 2);
  const a = bx / (W / (mapW + mapH));                 // x + y
  const b = (by - mapW * H / (mapW + mapH)) / (H / (mapW + mapH)); // y - x
  return [(a - b) / 2, (a + b) / 2];
}

// -- camera API ---------------------------------------------------------------------
// Moves and wheel zooms ease over settings.cameraSmoothMs (default
// 1250 ms; 0 = instant). Zoom interpolates geometrically so it feels even.

const ZOOM_MIN = 0.12, ZOOM_MAX = 6;
let camAnim = null, zoomAnim = null;
const clampZoom = (z) => Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 4);

function smoothMs() {
  const v = Number(settings.cameraSmoothMs);
  return Number.isFinite(v) ? Math.max(0, Math.min(5000, v)) : 1250;
}

function stepCamera(now) {
  if (camAnim) {
    const k = Math.min(1, (now - camAnim.t0) / camAnim.dur), e = easeInOut(k);
    S.camera.x = camAnim.x0 + (camAnim.x1 - camAnim.x0) * e;
    S.camera.y = camAnim.y0 + (camAnim.y1 - camAnim.y0) * e;
    if (camAnim.z1) S.camera.zoom = camAnim.z0 * Math.pow(camAnim.z1 / camAnim.z0, e);
    if (k >= 1) camAnim = null;
  }
  if (zoomAnim) {
    const k = Math.min(1, (now - zoomAnim.t0) / zoomAnim.dur);
    applyZoom(zoomAnim.z0 * Math.pow(zoomAnim.z1 / zoomAnim.z0, easeOut(k)), zoomAnim.ax, zoomAnim.ay);
    if (k >= 1) zoomAnim = null;
  }
}

export function centerOn(x, y, zoom) {
  const z1 = zoom ? clampZoom(zoom) : null;
  const dur = smoothMs();
  zoomAnim = null;
  if (!dur) {
    camAnim = null;
    S.camera.x = x; S.camera.y = y;
    if (z1) S.camera.zoom = z1;
    return;
  }
  camAnim = { x0: S.camera.x, y0: S.camera.y, z0: S.camera.zoom, x1: x, y1: y, z1, t0: performance.now(), dur };
}

function applyZoom(z, anchorPx, anchorPy) {
  z = clampZoom(z);
  if (anchorPx != null) {
    const [wx, wy] = toWorld(anchorPx, anchorPy);
    S.camera.zoom = z;
    const [wx2, wy2] = toWorld(anchorPx, anchorPy);
    S.camera.x += wx - wx2; S.camera.y += wy - wy2;
  } else {
    S.camera.zoom = z;
  }
}

/** Put the camera at (x, y) with an optional zoom at once, cancelling any
 * smooth move (the autocast director drives the camera every frame). */
export function setCamera(x, y, zoom) {
  camAnim = null; zoomAnim = null;
  S.camera.x = x; S.camera.y = y;
  if (zoom) S.camera.zoom = clampZoom(zoom);
}

/** Zoom at once, keeping the world point under (anchorPx, anchorPy) fixed. */
export function setZoom(z, anchorPx, anchorPy) {
  zoomAnim = null;
  applyZoom(z, anchorPx, anchorPy);
}

/** Smooth zoom only: preserve a pending pan and its remaining duration. */
export function zoomTo(z) {
  if (!z) return;
  const target = clampZoom(z);
  if (!Number.isFinite(target)) return;
  const dur = smoothMs();
  if (camAnim) camAnim.z1 = null; // this zoom takes over, without replacing the pan
  if (!dur) { setZoom(target); return; }
  zoomAnim = { z0: S.camera.zoom, z1: target, ax: null, ay: null, t0: performance.now(), dur };
}

function wheelZoom(e) {
  const f = Math.exp(-e.deltaY * 0.0015 * (settings.zoomSpeed || 1));
  const dur = smoothMs();
  const target = clampZoom((zoomAnim ? zoomAnim.z1 : S.camera.zoom) * f);
  if (!dur) { setZoom(target, e.clientX, e.clientY); return; }
  if (camAnim) camAnim.z1 = null; // the wheel takes over the zoom of a running move
  zoomAnim = { z0: S.camera.zoom, z1: target, ax: e.clientX, ay: e.clientY, t0: performance.now(), dur };
}

export function pan(dxPx, dyPx) {
  const z = S.camera.zoom;
  const a = dxPx / (TW / 2 * z), b = dyPx / (TH / 2 * z);
  S.camera.x += (a - b) / 2; S.camera.y += (a + b) / 2;
  camAnim = null;
}

// -- picking & selection ---------------------------------------------------------------

export function pick(px, py) {
  let best = null, bestD = 1e9;
  for (const r of entityRows) {
    const [sx, sy] = entityScreen(r);
    const u = entityInfo(r);
    // Buildings and Gaia resources by footprint; a unit by its body, which
    // stands above the foot point the row gives.
    const z = S.camera.zoom, wide = (r[6] & 1) || (r[6] & 32);
    const reach = wide ? Math.max(1, u.size || 1) * TW / 2 * z * 0.8 : Math.max(12, 14 * z);
    const d = Math.hypot(sx - px, (wide ? sy : sy - 12 * z) - py);
    if (d < reach && d < bestD && !(r[6] & 512) && (r[1] !== 0 || u.cls !== 15 || S.view?.entity_units?.[r[0]])) { best = r; bestD = d; }
  }
  // Compare food-bearing carcasses with standing objects, rather than letting
  // a nearby villager or a town centre's footprint always swallow the click.
  // Their bodies lie at ground level; standing units use their raised body
  // centre above. Clicking either body therefore selects the intended object.
  const remainsReach = Math.max(12, 16 * S.camera.zoom);
  for (const r of resourceRemains()) {
    const [sx, sy] = entityScreen(r);
    const d = Math.hypot(sx - px, sy - py);
    if (d < remainsReach && d <= bestD) { best = r; bestD = d; }
  }
  return best || pickTree(px, py);
}

// -- resources: carcasses and trees -------------------------------------------------------
// A hunted animal's carcass is a remains row (drawn, not a unit) whose carry
// column holds its food. Trees are a tile layer, not rows: a picked tree is
// a stand-in row with the id TREE_ID - tile index, rebuilt from the layer and
// view.trees_left (cut trees: [x, y, wood, id]) whenever it is asked for.
const TREE_ID = -2e9;
export const isTreeId = (id) => id <= TREE_ID;

function resourceRemains() {
  const rem = S.view && S.view.remains;
  return rem ? rem.filter((r) => r[1] === 0 && Array.isArray(r[10])) : [];
}

function treeRow(i) {
  if (!treeTiles || !(i >= 0 && i < mapW * mapH) || !treeTiles[i]) return null;
  const x = i % mapW, y = Math.floor(i / mapW);
  const mid = treeKinds[treeTiles[i] - 1];
  const cut = (S.view && S.view.trees_left || []).find((c) => Math.floor(c[0]) === x && Math.floor(c[1]) === y);
  const full = unitInfo(mid).storage;
  const wood = cut ? cut[2] : full ? full[1] : null;
  // Same columns as an entity row, plus the tree's own entity id when it is cut.
  return [TREE_ID - i, 0, mid, x + 0.5, y + 0.5, 1, 32, treeFacets ? treeFacets[i] : 0, [], 0, wood != null ? ['wood', wood] : 0, cut ? cut[3] : null];
}

function pickTree(px, py) {
  if (!treeTiles || S.camera.zoom < 0.35) return null;
  // A tree's picture stands well above its foot: test the trees whose picture
  // covers the cursor (near its trunk line), and take the one drawn in front.
  const z = S.camera.zoom;
  const [wx, wy] = toWorld(px, py + TH * z * 2);
  const treeScale = settings.smallTrees ? 0.6 : 1;
  let best = null, bestDepth = -1e9;
  for (let y = Math.floor(wy) - 4; y <= Math.floor(wy) + 4; y++) {
    for (let x = Math.floor(wx) - 4; x <= Math.floor(wx) + 4; x++) {
      if (x < 0 || y < 0 || x >= mapW || y >= mapH || !treeTiles[y * mapW + x]) continue;
      const [sx, sy] = groundScreen(x + 0.5, y + 0.5);
      const e = spritesOn() ? treeSprite(x, y) : null;
      let rect;
      if (e && e.meta) {
        const m = e.meta, k = z * TW / (e.tile || SPRITE_TILE) * treeScale;
        rect = [sx - m.ax * k, sy - m.ay * k, sx + (m.cw - m.ax) * k, sy + (m.ch - m.ay) * k];
      } else {
        const r = TW / 2 * z * 0.42;
        rect = [sx - r, sy - r * 2, sx + r, sy + r];
      }
      const halfW = (rect[2] - rect[0]) * 0.35;
      if (px < sx - halfW || px > sx + halfW || py < rect[1] || py > rect[3]) continue;
      if (y - x > bestDepth) { bestDepth = y - x; best = y * mapW + x; }
    }
  }
  return best == null ? null : treeRow(best);
}

/** Rows of everything selected: units and buildings, carcasses and trees. */
export function selectedRows() {
  const out = entityRows.filter((r) => S.selection.has(r[0]));
  if (out.length === S.selection.size) return out;
  for (const r of resourceRemains()) if (S.selection.has(r[0])) out.push(r);
  for (const id of S.selection) {
    if (!isTreeId(id)) continue;
    const r = treeRow(TREE_ID - id);
    if (r) out.push(r);
  }
  return out;
}

/** Villagers gathering from a resource row, by player: ``{pid: n}``. */
export function gatherersOf(r) {
  const g = S.view && S.view.gatherers;
  const id = isTreeId(r[0]) ? r[11] : r[0];
  return (g && id != null && (g[id] || g[String(id)])) || {};
}

export function boxSelect(x0, y0, x1, y1) {
  const out = [];
  const [ax, bx] = [Math.min(x0, x1), Math.max(x0, x1)], [ay, by] = [Math.min(y0, y1), Math.max(y0, y1)];
  for (const r of entityRows) {
    if (r[1] === 0) continue;
    // Only what the game lets a player select: a unit or a building with an icon,
    // not the hidden helper objects a building is made of (TC annexes, fences).
    const u = entityInfo(r);
    if ((u.kind !== 'unit' && u.kind !== 'building') || u.icon < 0 || TOWN_CENTER_PARTS.has(r[2])) continue;
    const [sx, sy] = entityScreen(r);
    if (sx >= ax && sx <= bx && sy >= ay && sy <= by) out.push(r);
  }
  // Like the game: units take priority over buildings in a box.
  const units = out.filter((r) => !(r[6] & 1));
  return units.length ? units : out;
}

/** On-screen rows of one master id; with ``owner``, only that player's (double-click). */
export function rowsOnScreenOfType(mid, owner) {
  return entityRows.filter((r) => {
    if (r[2] !== mid || (owner != null && r[1] !== owner)) return false;
    const [sx, sy] = entityScreen(r);
    return sx >= 0 && sy >= 0 && sx <= viewSize.w && sy <= viewSize.h;
  });
}

/** Resolve a real entity ID, including resource remains and felled tree tiles. */
export function rowForEntityId(id) {
  const row = entityRows.find((r) => r[0] === id) || resourceRemains().find((r) => r[0] === id);
  if (row) return row;
  const cut = S.view?.trees_left?.find((r) => r[3] === id);
  return cut ? treeRow(Math.floor(cut[1]) * mapW + Math.floor(cut[0])) : null;
}

export function currentRows() { return entityRows; }

export function followSelection(dt = 1 / 60) {
  if (!S.followSelection) return;
  followRows(S.camera, S.selection, entityRows, dt);
}

// -- cursor lock (keeps the pointer in the window for edge scrolling) -------------------

export const virtualCursor = { locked: false, x: 0, y: 0 };
export function toggleCursorLock() {
  if (document.pointerLockElement === canvas) document.exitPointerLock();
  else canvas.requestPointerLock();
}
document.addEventListener('pointerlockchange', () => {
  virtualCursor.locked = document.pointerLockElement === canvas;
});

// -- input ----------------------------------------------------------------------------

function forwardClick(target, e) {
  const init = { bubbles: true, cancelable: true, view: window, clientX: virtualCursor.x, clientY: virtualCursor.y,
    button: 0, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, altKey: e.altKey, metaKey: e.metaKey };
  for (const type of ['mousedown', 'mouseup', 'click']) target.dispatchEvent(new MouseEvent(type, init));
  if (typeof target.focus === 'function' && target.matches('input, select, textarea, button')) target.focus();
  // A form field needs the real pointer (typing, dropdowns): unlock for it.
  if (target.matches('input, select, textarea')) document.exitPointerLock();
}

export function installInput(onSelect) {
  let drag = null;
  const selbox = document.getElementById('selbox');
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('mousedown', (e) => {
    if (e.button === 2 || e.button === 1) {
      if (e.button === 2 && e.shiftKey) {
        const r = pick(e.clientX, e.clientY);
        if (r && r[1] > 0) onSelect({ perspective: r[1] });
        return;
      }
      drag = { kind: 'pan', x: e.clientX, y: e.clientY };
    } else if (e.button === 0) {
      if (virtualCursor.locked) {
        // The pointer is locked to the map, so the browser sends every click
        // here: hand clicks over the UI to the element under the drawn cursor.
        const target = document.elementFromPoint(virtualCursor.x, virtualCursor.y);
        if (target && target !== canvas) { e.stopPropagation(); forwardClick(target, e); return; }
        const r = pick(virtualCursor.x, virtualCursor.y);
        onSelect({ rows: r ? [r] : [], shift: e.shiftKey, ctrl: e.ctrlKey });
        return;
      }
      drag = { kind: 'box', x: e.clientX, y: e.clientY, moved: false };
    }
  });
  window.addEventListener('mousemove', (e) => {
    if (virtualCursor.locked) {
      virtualCursor.x = Math.max(0, Math.min(viewSize.w - 1, virtualCursor.x + e.movementX));
      virtualCursor.y = Math.max(0, Math.min(viewSize.h - 1, virtualCursor.y + e.movementY));
    }
    if (!drag) return;
    if (drag.kind === 'pan') {
      pan(-(e.clientX - drag.x), -(e.clientY - drag.y));
      drag.x = e.clientX; drag.y = e.clientY;
    } else if (drag.kind === 'box') {
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 5) drag.moved = true;
      if (drag.moved) {
        selbox.classList.remove('hidden');
        Object.assign(selbox.style, {
          left: Math.min(drag.x, e.clientX) + 'px', top: Math.min(drag.y, e.clientY) + 'px',
          width: Math.abs(e.clientX - drag.x) + 'px', height: Math.abs(e.clientY - drag.y) + 'px',
        });
      }
    }
  });
  window.addEventListener('mouseup', (e) => {
    if (!drag) return;
    if (drag.kind === 'box') {
      selbox.classList.add('hidden');
      if (drag.moved) onSelect({ rows: boxSelect(drag.x, drag.y, e.clientX, e.clientY), shift: e.shiftKey, ctrl: e.ctrlKey });
      else onSelect({ rows: (() => { const r = pick(e.clientX, e.clientY); return r ? [r] : []; })(), shift: e.shiftKey, ctrl: e.ctrlKey });
    }
    drag = null;
  });
  canvas.addEventListener('dblclick', (e) => {
    // Like the game: every on-screen unit of that type owned by the same player.
    const r = pick(e.clientX, e.clientY);
    if (r) onSelect({ rows: rowsOnScreenOfType(r[2], r[1]), shift: e.shiftKey });
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    wheelZoom(e);
  }, { passive: false });
  let miniDrag = false;
  // The minimap is a diamond in a rectangle: its corners are off the map.
  const miniMove = (e) => {
    const [x, y] = minimapToWorld(e);
    S.camera.x = Math.max(0, Math.min(mapW, x)); S.camera.y = Math.max(0, Math.min(mapH, y)); camAnim = null;
  };
  mini.addEventListener('mousedown', (e) => { if (e.button === 0) { miniDrag = true; miniMove(e); } });
  window.addEventListener('mousemove', (e) => { if (miniDrag) miniMove(e); });
  window.addEventListener('mouseup', () => { miniDrag = false; });
  mini.addEventListener('wheel', (e) => {
    e.preventDefault();
    miniView.zoom = Math.max(1, Math.min(6, miniView.zoom * Math.exp(-e.deltaY * 0.002)));
  }, { passive: false });
}

export function edgeScroll(mx, my, dt) {
  if (virtualCursor.locked) { mx = virtualCursor.x; my = virtualCursor.y; }
  if ((!settings.edgeScroll && !virtualCursor.locked) || mx == null) return;
  const m = 6, sp = 900 * settings.edgeScrollSpeed * dt;
  let dx = 0, dy = 0;
  if (mx <= m) dx = -sp; else if (mx >= viewSize.w - m) dx = sp;
  if (my <= m) dy = -sp; else if (my >= viewSize.h - m) dy = sp;
  if (dx || dy) pan(dx, dy);
}
