// Which map changes can affect a cached ground picture? Bounds are inclusive
// tile coordinates from the renderer's own culling range, including its border.

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

