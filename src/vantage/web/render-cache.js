// Which map changes can affect a cached ground picture? Bounds are inclusive
// tile coordinates from the renderer's own culling range, including its border.

// A permanent missing tree strip uses the fallback permanently; only pending or
// retryable strips need another ground repaint. Return the ready strip itself so
// the caller can still use its image and metadata.
export function treeSpriteState(entry) {
  if (entry?.img && entry.meta) return entry;
  if (entry?.failed && !entry.retryAt) return false;
  return null;
}

// All ground geometry (including height) scales with camera zoom. Project a
// cached raster at its original camera position into the current viewport.
export function groundProjection(cache, camera, width, height, tileWidth, tileHeight) {
  const scale = camera.zoom / cache.zoom;
  const cx = width / 2 + (cache.x + cache.y - camera.x - camera.y) * tileWidth / 2 * camera.zoom;
  const cy = height / 2 + (cache.y - cache.x - camera.y + camera.x) * tileHeight / 2 * camera.zoom;
  const x = cx - (cache.width / 2 + cache.padding) * scale;
  const y = cy - (cache.height / 2 + cache.padding) * scale;
  const w = (cache.width + cache.padding * 2) * scale, h = (cache.height + cache.padding * 2) * scale;
  return { x, y, scale, covered: x <= 0 && y <= 0 && x + w >= width && y + h >= height };
}

export function changedTilesInRegion(changed, width, bounds) {
  if (!bounds) return changed;
  const [minX, maxX, minY, maxY] = bounds;
  return changed.filter((i) => {
    const x = i % width, y = Math.floor(i / width);
    return x >= minX && x <= maxX && y >= minY && y <= maxY;
  });
}

// Terrain chunks sample the neighbouring tile when blending their edges. A
// change just outside a drawn chunk can therefore change that chunk's picture.
export function terrainRegion(bounds, chunkSize) {
  const [minX, maxX, minY, maxY] = bounds;
  return [Math.floor(minX / chunkSize) * chunkSize - 1, (Math.floor(maxX / chunkSize) + 1) * chunkSize,
    Math.floor(minY / chunkSize) * chunkSize - 1, (Math.floor(maxY / chunkSize) + 1) * chunkSize];
}

export function changedTreeTiles(before, after, width, bounds) {
  if (!bounds || !before.tiles || before.tiles.length !== after.tiles.length) return null;
  const [minX, maxX, minY, maxY] = bounds;
  const out = [];
  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const i = y * width + x;
      // Kind indices may be reordered between snapshots. Compare the actual
      // tree master, then its facet; empty tiles have no meaningful facet.
      const changed = before.kinds[before.tiles[i] - 1] !== after.kinds[after.tiles[i] - 1]
        || (after.tiles[i] && (before.facets?.[i] || 0) !== (after.facets?.[i] || 0));
      if (changed) out.push(i);
    }
  }
  return out;
}

// Dirty rectangles use the cached camera's CSS coordinates, before its border
// is added. Include two pixels for antialiasing, clip to the stored picture,
// and merge without changing a caller's existing rectangle.
export function mergeDirtyRect(current, rect, width, height, padding) {
  if (!rect) return current;
  const x0 = Math.max(-padding, Math.floor(rect[0]) - 2), y0 = Math.max(-padding, Math.floor(rect[1]) - 2);
  const x1 = Math.min(width + padding, Math.ceil(rect[2]) + 2), y1 = Math.min(height + padding, Math.ceil(rect[3]) + 2);
  if (x0 >= x1 || y0 >= y1) return current;
  return current ? [Math.min(current[0], x0), Math.min(current[1], y0), Math.max(current[2], x1), Math.max(current[3], y1)] : [x0, y0, x1, y1];
}

// A unit's outline ring depends on its actual sprite frames and subpixel
// placement, but not on which buildings cover it. Retain those small rasters
// within a separate, bounded budget; moving units need not populate this cache.
export class OutlineCache {
  constructor(limit = 32 * 1048576) {
    this.limit = limit;
    this.bytes = 0;
    this.entries = new Map();
    this.images = new WeakMap();
    this.nextImage = 1;
    this.hits = 0;
    this.misses = 0;
  }

  key(parts, color, ox, oy, scale, width, height) {
    let key = `${color}|${scale}|${width}|${height}`;
    for (const [img, sx, sw, sh, dx, dy, dw, dh] of parts) {
      let id = this.images.get(img);
      if (!id) { id = this.nextImage++; this.images.set(img, id); }
      key += `|${id},${sx},${sw},${sh},${(dx - ox) * scale},${(dy - oy) * scale},${dw * scale},${dh * scale}`;
    }
    return key;
  }

  get(key) {
    const entry = this.entries.get(key);
    if (!entry) { this.misses++; return null; }
    this.entries.delete(key); this.entries.set(key, entry);
    this.hits++;
    return entry.raster;
  }

  set(key, raster, bytes) {
    const old = this.entries.get(key);
    if (old) { this.bytes -= old.bytes; this.entries.delete(key); }
    if (bytes > this.limit) return;
    while (this.bytes + bytes > this.limit && this.entries.size) {
      const first = this.entries.keys().next().value;
      this.bytes -= this.entries.get(first).bytes;
      this.entries.delete(first);
    }
    this.entries.set(key, { raster, bytes }); this.bytes += bytes;
  }
}

/**
 * Dirty rectangles [x0, y0, x1, y1] merged where that is cheap: two merge when
 * their bounding box is at most `waste` times their combined area. Terrain
 * repaints went out as one bounding box, so two farms at opposite corners
 * re-uploaded the whole (~30 MB) terrain canvas.
 */
export function coalesceRects(rects, waste = 1.5) {
  const area = (r) => (r[2] - r[0]) * (r[3] - r[1]);
  // Pairwise merging is quadratic or worse: many rectangles (a seek in a game
  // full of farms) are first gathered per 256 px cell, one box per cell.
  if (rects.length > 64) {
    const cells = new Map();
    for (const r of rects) {
      const k = Math.floor(r[0] / 256) * 65536 + Math.floor(r[1] / 256);
      const c = cells.get(k);
      if (!c) cells.set(k, r.slice());
      else { c[0] = Math.min(c[0], r[0]); c[1] = Math.min(c[1], r[1]); c[2] = Math.max(c[2], r[2]); c[3] = Math.max(c[3], r[3]); }
    }
    rects = [...cells.values()];
  }
  let out = rects.map((r) => r.slice());
  for (let merged = true; merged && out.length > 1;) {
    merged = false;
    for (let i = 0; i < out.length && !merged; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const a = out[i], b = out[j];
        const u = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
        if (area(u) <= (area(a) + area(b)) * waste) { out[i] = u; out.splice(j, 1); merged = true; break; }
      }
    }
  }
  return out;
}

/**
 * Where to ask for strips ahead of a moving camera: the room beyond the screen on
 * each side, [left, top, right, bottom] px, or null when it is (nearly) still.
 * `motion`: { vx, vy } screen px/s and vz, the zoom's logarithmic rate per second;
 * `delayMs`: how long a strip takes to arrive; `zoomTo`: where an eased zoom ends.
 */
export function prefetchRoom(motion, delayMs, w, h, zoomTo = 0, zoom = 1) {
  const lead = Math.min(1, 0.12 + 1.5 * delayMs / 1000);
  const cap = 0.75;
  let left = Math.max(0, -motion.vx * lead), right = Math.max(0, motion.vx * lead);
  let top = Math.max(0, -motion.vy * lead), bottom = Math.max(0, motion.vy * lead);
  // Zooming out shows more on every side: as far as the zoom is going (an eased
  // wheel step knows its end), else as far as it gets within the delay.
  const shrink = zoomTo > 0 && zoomTo < zoom ? zoom / zoomTo : motion.vz < 0 ? Math.exp(-motion.vz * lead) : 1;
  if (shrink > 1) {
    const grow = Math.min(2, shrink) - 1;
    left += w / 2 * grow; right += w / 2 * grow; top += h / 2 * grow; bottom += h / 2 * grow;
  }
  if (Math.max(left, right, top, bottom) < 48) return null;
  return [Math.min(left, w * cap), Math.min(top, h * cap), Math.min(right, w * cap), Math.min(bottom, h * cap)];
}
