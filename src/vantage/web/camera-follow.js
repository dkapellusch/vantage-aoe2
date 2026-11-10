// Follow a selection at the same rate regardless of rendering cadence.
// The 60 Hz response matches the original 20% correction per rendered frame.
export function followRows(camera, selection, rows, dt) {
  if (!selection.size || !Number.isFinite(dt) || dt <= 0) return;
  let x = 0, y = 0, count = 0;
  for (const row of rows) {
    if (!selection.has(row[0])) continue;
    x += row[3]; y += row[4]; count++;
  }
  if (!count) return;
  const amount = 1 - Math.pow(0.8, dt * 60);
  camera.x += (x / count - camera.x) * amount;
  camera.y += (y / count - camera.y) * amount;
}
